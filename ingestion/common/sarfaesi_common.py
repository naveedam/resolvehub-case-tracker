"""
ResolveHub - shared core for banks using the standardized RBI-format
SARFAESI possession-notice disclosure table.
-----------------------------------------------------------------------
Many banks (confirmed so far: Canara, Union Bank, Bank of India, Axis,
City Union Bank) publish the same table shape: Branch/RO/Circle info,
State, Borrower, Guarantor, addresses, Outstanding Amount, Asset
Classification, a date, Security Details, Title Holder. COLUMN ORDER
VARIES between banks (e.g. Union Bank puts Classification before Date;
Canara puts Date before Classification) - so this detects each column's
position from the PDF's own header row at runtime via keyword matching,
rather than trusting a hardcoded index per bank.

Each bank's scraper.py should be a thin wrapper that imports
run_standard_scraper from this file and calls it with that bank's
source name and PDF URL.

This does NOT create or alter any DB tables - it only inserts rows into
tables that already exist in your Supabase project.

Env vars required: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
Install: pip install requests pdfplumber supabase python-dotenv --break-system-packages
"""

import os
import re
import time
import hashlib
import requests
import pdfplumber
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

HEADERS = {"User-Agent": "ResolveHub-Research/0.1 (contact: <your-email>)"}

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def execute_with_retry(builder, retries=4, delay=2):
    """Retry-with-backoff wrapper for every Supabase call. A dropped
    connection recovers automatically instead of killing an hours-long
    run - learned the hard way scraping Canara's 863-page document."""
    last_exc = None
    for attempt in range(retries):
        try:
            return builder.execute()
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                wait = delay * (attempt + 1)
                print(f"    (retrying after connection error, attempt {attempt + 1}/{retries}, waiting {wait}s: {e})")
                time.sleep(wait)
    raise last_exc


# --- Dynamic column detection -------------------------------------------

COLUMN_KEYWORDS = {
    "branch": ["branch"],
    "state": ["state"],
    "borrower": ["borrower name"],
    "guarantor": ["guarantor name", "guarantor"],
    "outstanding": ["outstanding amount", "outstanding"],
    "classification": ["asset classification"],
    "class_date": ["date of asset classification", "date of npa", "npa date"],
    "security": ["details of security", "security possessed"],
}


def detect_column_map(header_row):
    """Matches column names by keyword rather than trusting position -
    each bank's actual column order can differ."""
    mapping = {}
    for idx, cell in enumerate(header_row):
        text = (cell or "").strip().lower()
        if not text:
            continue
        for field, keywords in COLUMN_KEYWORDS.items():
            if field not in mapping and any(kw in text for kw in keywords):
                mapping[field] = idx
    return mapping


def is_header_row(row):
    joined = " ".join((c or "") for c in row).lower()
    hits = sum(1 for kws in COLUMN_KEYWORDS.values() for kw in kws if kw in joined)
    return hits >= 4


# --- Field parsing --------------------------------------------------------

def parse_amount(raw):
    """Outstanding amount in this table format is a plain full-digit
    number - no Lakh/Crore unit ambiguity. Sanity bounds learned from
    SBI still apply regardless of source."""
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.]", "", raw)
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if value < 1_000 or value > 100_000_000_000:
        return None
    return value


ASSET_TYPE_KEYWORDS = {
    "Apartment": ["apartment", "flat", "flat no", "residential flat"],
    "House": ["house", "bungalow", "residential building", "residential property", "duplex"],
    "Land": ["land", "plot", "acre", "vacant site", "agricultural land", "khasra", "gata", "survey no"],
    "Vehicle": ["vehicle", "car", "truck", "lorry", "motor", "bus"],
    "Gold": ["gold", "jewellery", "jewelry", "ornament"],
    "Machinery": ["machinery", "equipment", "plant &", "plant and machinery"],
    "Inventory": ["inventory", "stock", "goods"],
    "Business": ["business", "shop", "commercial establishment", "godown", "industrial", "factory"],
}


def classify_asset_type(description):
    lowered = description.lower()
    for asset_type, keywords in ASSET_TYPE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return asset_type
    return "Other"


COMPANY_KEYWORDS = ["m/s", "ms ", "pvt ltd", "pvt. ltd", "ltd", "llp", "enterprise", "enterprises",
                    "industries", "traders", "trading", "trade link", "group", "mill", "mills",
                    "agency", "agencies", "corporation", "company", "sansthan", "samiti", "society",
                    "firm", "proprietor"]


def classify_party_type(name):
    lowered = name.lower()
    if any(kw in lowered for kw in COMPANY_KEYWORDS):
        return "Company"
    return "Individual"


# --- Party / case helpers --------------------------------------------------

def get_or_create_party(full_name, party_type, cache):
    key = full_name.lower()
    if key in cache:
        return cache[key]
    existing = execute_with_retry(
        supabase.table("parties")
        .select("id")
        .ilike("full_name", full_name)
        .is_("deleted_at", "null")
    )
    if existing.data:
        party_id = existing.data[0]["id"]
    else:
        inserted = execute_with_retry(
            supabase.table("parties").insert({"full_name": full_name, "party_type": party_type})
        )
        party_id = inserted.data[0]["id"]
    cache[key] = party_id
    return party_id


def link_case_party(case_id, party_id, role):
    execute_with_retry(
        supabase.table("case_parties").insert({"case_id": case_id, "party_id": party_id, "role": role})
    )


def case_exists(case_reference):
    result = execute_with_retry(
        supabase.table("cases")
        .select("id")
        .eq("case_reference", case_reference)
        .is_("deleted_at", "null")
    )
    return len(result.data) > 0


def clean_cell(value):
    return (value or "").replace("\n", " ").strip()


# --- Row ingestion ----------------------------------------------------------

def ingest_row(row, column_map, source_name, source_name_full, pdf_url, lender_cache, party_cache):
    """Returns 'ingested', 'skipped', or 'bad'."""
    required = ["borrower", "outstanding"]
    if any(f not in column_map for f in required):
        return "bad"

    def get(field):
        idx = column_map.get(field)
        return clean_cell(row[idx]) if idx is not None and idx < len(row) else ""

    branch = get("branch")
    state = get("state")
    borrower_name = get("borrower")
    guarantor_name = get("guarantor")
    outstanding_raw = get("outstanding")
    class_date = get("class_date")
    asset_classification = get("classification")
    security_details = get("security")

    if not borrower_name or borrower_name in ("#N/A", "-"):
        return "bad"
    if guarantor_name in ("#N/A", "-", ""):
        guarantor_name = None

    amount = parse_amount(outstanding_raw)

    raw_key = f"{source_name}|{branch}|{borrower_name.lower()}|{outstanding_raw}|{class_date}"
    case_reference = source_name.upper() + "-" + hashlib.sha256(raw_key.encode()).hexdigest()[:16]

    if case_exists(case_reference):
        return "skipped"

    case_row = {
        "case_reference": case_reference,
        "title": borrower_name,
        "case_type": "SARFAESI",
        "status": "active",
        "court_name": None,
        "next_hearing_date": None,
        "filing_date": None,
        "estimated_liability": amount,
        "summary": f"Possession taken - {branch}, {state} ({source_name_full})".strip(", "),
        "metadata": {
            "source": source_name,
            "source_urls": [pdf_url],
            "state": state or None,
            "asset_classification": asset_classification or None,
            "classification_date": class_date or None,
        },
    }

    try:
        inserted_case = execute_with_retry(supabase.table("cases").insert(case_row).select())
        case_id = inserted_case.data[0]["id"]
    except Exception as e:
        print(f"  ! failed to insert case for {borrower_name}: {e}")
        return "bad"

    lender_id = get_or_create_party(source_name_full, "Bank", lender_cache)
    link_case_party(case_id, lender_id, "Lender")

    borrower_id = get_or_create_party(borrower_name, classify_party_type(borrower_name), party_cache)
    link_case_party(case_id, borrower_id, "Borrower")

    if guarantor_name:
        first_guarantor = re.split(r"[,\n]", guarantor_name)[0].strip()
        if first_guarantor:
            guarantor_id = get_or_create_party(first_guarantor, classify_party_type(first_guarantor), party_cache)
            link_case_party(case_id, guarantor_id, "Guarantor")

    execute_with_retry(
        supabase.table("documents").insert({
            "case_id": case_id,
            "document_type": "possession_notice",
            "document_name": f"Secured Assets Possessed - {source_name_full}",
            "storage_path": pdf_url,
            "processed": True,
            "metadata": {"source": source_name},
        })
    )

    if amount:
        execute_with_retry(
            supabase.table("liabilities").insert({
                "case_id": case_id,
                "lender_id": lender_id,
                "loan_type": "Other",
                "outstanding_amount": amount,
                "currency_code": "INR",
                "secured": True,
                "remarks": f"Auto-ingested from {source_name_full} possession notice; verify against source PDF.",
            })
        )

    if security_details:
        execute_with_retry(
            supabase.table("assets").insert({
                "case_id": case_id,
                "asset_type": classify_asset_type(security_details),
                "description": security_details,
                "auction_status": "possessed",
            })
        )

    return "ingested"


# --- Top-level runner --------------------------------------------------------

def download_pdf(pdf_url, local_path):
    if os.path.exists(local_path):
        print(f"Using existing {local_path} (delete it to force a fresh download)")
        return
    print(f"Downloading from {pdf_url} ...")
    resp = requests.get(pdf_url, headers=HEADERS, timeout=300, stream=True)
    resp.raise_for_status()
    with open(local_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
    print(f"Downloaded {os.path.getsize(local_path) / 1024 / 1024:.1f} MB")


def run_standard_scraper(source_name, source_name_full, pdf_url, local_pdf_path,
                          max_pages=None, start_page=0):
    download_pdf(pdf_url, local_pdf_path)

    lender_cache = {}
    party_cache = {}
    total_ingested = total_skipped = total_bad = 0
    column_map = {}

    with pdfplumber.open(local_pdf_path) as pdf:
        total_page_count = len(pdf.pages)
        print(f"PDF has {total_page_count} pages")
        end_page = total_page_count if max_pages is None else min(start_page + max_pages, total_page_count)

        for page_num in range(start_page, end_page):
            page = pdf.pages[page_num]
            tables = page.extract_tables()
            page_ingested = page_skipped = page_bad = 0

            for table in tables:
                for row in table:
                    if not row:
                        continue
                    if is_header_row(row):
                        detected = detect_column_map(row)
                        if detected:
                            column_map = detected
                        continue
                    if not column_map:
                        # No header seen yet on this page/table - skip
                        # rather than guess at column positions.
                        page_bad += 1
                        continue
                    try:
                        result = ingest_row(row, column_map, source_name, source_name_full,
                                             pdf_url, lender_cache, party_cache)
                    except Exception as e:
                        print(f"  ! row error (page {page_num + 1}), skipping this row: {e}")
                        result = "bad"
                    if result == "ingested":
                        page_ingested += 1
                    elif result == "skipped":
                        page_skipped += 1
                    else:
                        page_bad += 1

            total_ingested += page_ingested
            total_skipped += page_skipped
            total_bad += page_bad

            if page_num % 10 == 0 or page_num == end_page - 1:
                print(f"  page {page_num + 1}/{total_page_count}: "
                      f"+{page_ingested} ingested this page "
                      f"(running total: {total_ingested} ingested, {total_skipped} skipped, {total_bad} bad)")

    print(f"\nDone. Ingested: {total_ingested}, skipped: {total_skipped}, bad rows: {total_bad}")
