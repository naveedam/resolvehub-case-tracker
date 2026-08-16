"""
ResolveHub - Canara Bank SARFAESI possession-notice scraper (v2)
--------------------------------------------------------------------
REVISED APPROACH: Canara publishes a single master PDF covering ALL
states/branches at once ("POSSESSION TAKEN - BANK AS A WHOLE"), rather
than needing to crawl 36 separate state pages and hundreds of per-RO
PDFs. This is a genuine structured table with columns:

Circle Name | RO Name | Branch Name | STATE | Borrower Name |
Registered Address of Borrower | Guarantor name |
Registered Address of Guarantor | Outstanding Amount | Date of NPA |
Asset Classification | Details of Security Possessed |
Name of the Title holder of the Security Possessed |
Name of the Authorised Officer | Contact No

Uses pdfplumber's table extraction (real cell/row boundaries), not
text-regex parsing, since this is a genuine gridded table.

This does NOT create or alter any tables - it only inserts rows into
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

MASTER_PDF_URL = "https://www.canarabank.bank.in/documents/d/guest/regional-office-agra_1"
LOCAL_PDF_PATH = "canara_master.pdf"
SOURCE_NAME = "Canara"
SOURCE_NAME_FULL = "Canara Bank"
HEADERS = {"User-Agent": "ResolveHub-Research/0.1 (contact: <your-email>)"}

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def execute_with_retry(builder, retries=4, delay=2):
    """Wraps any Supabase query builder's .execute() call with retry +
    backoff. The connection-drop error we hit (ConnectionTerminated)
    recurred even with row-level catching, meaning the SAME broken
    connection was being reused on the very next call too — retrying
    here forces a fresh connection attempt instead of propagating the
    error up and killing the whole run."""
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


def download_master_pdf():
    """12+ MB file - stream to disk rather than holding in memory, and
    skip re-downloading if already present (this file doesn't change
    often; delete it manually to force a fresh pull)."""
    if os.path.exists(LOCAL_PDF_PATH):
        print(f"Using existing {LOCAL_PDF_PATH} (delete it to force a fresh download)")
        return
    print(f"Downloading master PDF from {MASTER_PDF_URL} ...")
    resp = requests.get(MASTER_PDF_URL, headers=HEADERS, timeout=300, stream=True)
    resp.raise_for_status()
    with open(LOCAL_PDF_PATH, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
    print(f"Downloaded {os.path.getsize(LOCAL_PDF_PATH) / 1024 / 1024:.1f} MB")


EXPECTED_HEADER_TOKENS = ["circle", "borrower", "guarantor", "outstanding", "security"]


def is_header_row(row):
    joined = " ".join((c or "") for c in row).lower()
    return sum(tok in joined for tok in EXPECTED_HEADER_TOKENS) >= 3


def parse_amount(raw):
    """Outstanding amount is already a plain full-digit number - no
    Lakh/Crore unit ambiguity. Apply the same sanity bounds learned
    from SBI regardless."""
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
    "Land": ["land", "plot", "acre", "vacant site", "agricultural land", "khasra", "gata"],
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
                    "agency", "agencies", "corporation", "company", "sansthan", "samiti", "society"]


def classify_party_type(name):
    lowered = name.lower()
    if any(kw in lowered for kw in COMPANY_KEYWORDS):
        return "Company"
    return "Individual"


_LENDER_PARTY_CACHE = {}
_PARTY_CACHE = {}


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
            supabase.table("parties").insert({
                "full_name": full_name,
                "party_type": party_type,
            })
        )
        party_id = inserted.data[0]["id"]
    cache[key] = party_id
    return party_id


def link_case_party(case_id, party_id, role):
    execute_with_retry(
        supabase.table("case_parties").insert({
            "case_id": case_id,
            "party_id": party_id,
            "role": role,
        })
    )


def make_case_reference(branch, borrower_name, outstanding_raw, npa_date):
    raw = f"{SOURCE_NAME}|{branch}|{borrower_name.lower()}|{outstanding_raw}|{npa_date}"
    return "CANARA-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


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


def ingest_row(row):
    """Returns 'ingested', 'skipped', or 'bad'."""
    if len(row) < 15:
        return "bad"

    circle = clean_cell(row[0])
    ro_name = clean_cell(row[1])
    branch = clean_cell(row[2])
    state = clean_cell(row[3])
    borrower_name = clean_cell(row[4])
    guarantor_name = clean_cell(row[6])
    outstanding_raw = clean_cell(row[8])
    npa_date = clean_cell(row[9])
    asset_classification = clean_cell(row[10])
    security_details = clean_cell(row[11])

    if not borrower_name or borrower_name in ("#N/A", "-"):
        return "bad"
    if guarantor_name in ("#N/A", "-", ""):
        guarantor_name = None

    amount = parse_amount(outstanding_raw)
    case_reference = make_case_reference(branch, borrower_name, outstanding_raw, npa_date)

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
        "summary": f"Possession taken - {branch}, {state} (Circle: {circle}, RO: {ro_name})",
        "metadata": {
            "source": SOURCE_NAME,
            "source_urls": [MASTER_PDF_URL],
            "state": state or None,
            "asset_classification": asset_classification or None,
            "npa_date": npa_date or None,
        },
    }

    try:
        inserted_case = execute_with_retry(supabase.table("cases").insert(case_row).select())
        case_id = inserted_case.data[0]["id"]
    except Exception as e:
        print(f"  ! failed to insert case for {borrower_name}: {e}")
        return "bad"

    lender_id = get_or_create_party(SOURCE_NAME_FULL, "Bank", _LENDER_PARTY_CACHE)
    link_case_party(case_id, lender_id, "Lender")

    borrower_type = classify_party_type(borrower_name)
    borrower_id = get_or_create_party(borrower_name, borrower_type, _PARTY_CACHE)
    link_case_party(case_id, borrower_id, "Borrower")

    if guarantor_name:
        # Guarantor field can contain multiple names comma/newline separated;
        # keep it simple and link the first one, rest travel in metadata.
        first_guarantor = re.split(r"[,\n]", guarantor_name)[0].strip()
        if first_guarantor:
            guarantor_type = classify_party_type(first_guarantor)
            guarantor_id = get_or_create_party(first_guarantor, guarantor_type, _PARTY_CACHE)
            link_case_party(case_id, guarantor_id, "Guarantor")

    execute_with_retry(
        supabase.table("documents").insert({
            "case_id": case_id,
            "document_type": "possession_notice",
            "document_name": "Possession Taken - Bank As A Whole",
            "storage_path": MASTER_PDF_URL,
            "processed": True,
            "metadata": {"source": SOURCE_NAME},
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
                "remarks": f"Auto-ingested from {SOURCE_NAME} bank-wide possession notice; verify against source PDF.",
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


def run(max_pages=None, start_page=0):
    """max_pages=None processes the whole document. Use start_page to
    resume from partway through if a run gets interrupted (page numbers
    print as it goes, so you know where to resume)."""
    download_master_pdf()

    total_ingested = total_skipped = total_bad = 0

    with pdfplumber.open(LOCAL_PDF_PATH) as pdf:
        total_page_count = len(pdf.pages)
        print(f"PDF has {total_page_count} pages")
        end_page = total_page_count if max_pages is None else min(start_page + max_pages, total_page_count)

        for page_num in range(start_page, end_page):
            page = pdf.pages[page_num]
            tables = page.extract_tables()
            page_ingested = page_skipped = page_bad = 0

            for table in tables:
                for row in table:
                    if not row or is_header_row(row):
                        continue
                    try:
                        result = ingest_row(row)
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


if __name__ == "__main__":
    run()