"""
ResolveHub — SBI SARFAESI notice scraper (pilot)
--------------------------------------------------
Scrapes SBI's public "Sarfaesi And Others" auction notice page, downloads the
linked sale notice PDFs, extracts key fields, and inserts into the existing
Supabase schema (cases / documents / liabilities / assets).

This does NOT create or alter any tables — it only inserts rows into tables
that already exist in your Supabase project (eesbjpjwamzmiormzzop).

Run this from your own infra (a scheduled Vercel/cron job, or manually for
now) — it needs outbound access to sbi.bank.in, which a sandboxed dev
environment may not have.

Install:
    pip install requests beautifulsoup4 pdfplumber supabase python-dateutil --break-system-packages

Env vars required:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""

import os
import re
import io
import time
import hashlib
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
import pdfplumber
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://sbi.bank.in/web/sbi-in-the-news/auction-notices/sarfaesi-and-others"
SOURCE_NAME = "SBI"
SOURCE_NAME_FULL = "State Bank of India"
HEADERS = {"User-Agent": "ResolveHub-Research/0.1 (contact: <your-email>)"}
REQUEST_DELAY_SECONDS = 2  # be polite — don't hammer the bank's site

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def fetch_notice_page(url: str) -> tuple[BeautifulSoup, str]:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser"), resp.text


def extract_portlet_instance_id(html: str) -> str | None:
    """SBI's notice table is rendered by a Liferay Asset Publisher portlet
    with a page-specific instance ID baked into its layout. Pagination
    requires this exact ID in every query param name — a plain 'Next'
    link doesn't exist; the site paginates via portlet AJAX requests."""
    m = re.search(
        r"com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_([A-Za-z0-9]+)",
        html,
    )
    return m.group(1) if m else None


def build_page_url(instance_id: str, page_num: int, delta: int = 200) -> str:
    portlet_id = f"com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_{instance_id}"
    return (
        f"{BASE_URL}?p_p_id={portlet_id}&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        f"&_{portlet_id}_delta={delta}&p_r_p_resetCur=false&_{portlet_id}_cur={page_num}"
    )


def parse_notice_rows(soup: BeautifulSoup) -> list[dict]:
    """Parse the 'Asset Publisher' table into row dicts."""
    rows = []
    table = soup.find("table")
    if not table:
        return rows

    for tr in table.find_all("tr")[1:]:  # skip header row
        cells = tr.find_all("td")
        if len(cells) < 3:
            continue

        description = cells[0].get_text(strip=True)
        auction_date_raw = cells[1].get_text(strip=True)
        doc_links = [
            {"label": a.get_text(strip=True), "url": requests.compat.urljoin("https://sbi.bank.in", a["href"])}
            for a in cells[2].find_all("a", href=True)
        ]

        try:
            auction_date = dateparser.parse(auction_date_raw, dayfirst=True).date().isoformat()
        except (ValueError, TypeError):
            auction_date = None

        rows.append({
            "description": description,
            "auction_date": auction_date,
            "documents": doc_links,
        })
    return rows


def download_and_extract_pdf_text(url: str) -> str:
    time.sleep(REQUEST_DELAY_SECONDS)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    text_parts = []
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


UNIT_MULTIPLIERS = {
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "cr.": 10_000_000,
}


def parse_rupee_amount(match: re.Match | None) -> float | None:
    """Applies the Lakh/Crore multiplier when the source states the
    figure that way (e.g. 'Rs 240.00 Lakh') instead of full digits
    (e.g. 'Rs.2,40,00,000/-'). Missing this was silently shrinking
    those amounts by 100,000x or 10,000,000x.

    Safety check: only apply the multiplier if the raw number is small
    (< 1 lakh as a bare figure) — a genuine 'X Lakh'/'X Crore' phrasing
    always has a small X (e.g. '240 Lakh', '52.88 Crore'). Some source
    documents redundantly/mistakenly append a unit word AFTER an
    already-complete full-digit figure (e.g. 'Rs. 52,88,42,189.84
    Crore' when 52,88,42,189.84 is already the full rupee amount) —
    applying the multiplier there would inflate an already-correct
    number by another 10,000,000x."""
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    unit = (match.group(2) or "").strip().lower()
    value = float(raw)
    multiplier = UNIT_MULTIPLIERS.get(unit, 1)
    if multiplier > 1 and value >= 100_000:
        return value
    return value * multiplier


def extract_fields_from_pdf_text(text: str) -> dict:
    """Tuned against SBI's actual IBA-style e-auction terms template
    (numbered sections: 01 Borrower, 02 Branch, 03 Asset Description,
    04 Encumbrances, 05 Secured Debt...). Other banks may use a similar
    IBA template, but treat these patterns as a starting point to verify
    against each new source, not a universal guarantee."""

    def find(pattern, group=1, flags=re.I):
        m = re.search(pattern, text, flags)
        return m.group(group).strip() if m else None

    unit_suffix = r"\s*(Lakhs?|Lacs?|Crores?|Cr\.?)?"

    amount = parse_rupee_amount(
        re.search(rf"0?5\.?\s+The secured.{{0,200}}?Rs\.?\s*([\d,]+(?:\.\d+)?){unit_suffix}", text, re.I | re.S)
        or re.search(rf"secured debt for.{{0,150}}?Rs\.?\s*([\d,]+(?:\.\d+)?){unit_suffix}", text, re.I | re.S)
        or re.search(rf"(?:outstanding|due|dues of)[^\d₹]{{0,20}}(?:Rs\.?|₹)\s*([\d,]+(?:\.\d+)?){unit_suffix}", text, re.I)
        or re.search(rf"total (?:outstanding|dues)[^\n]{{0,40}}(?:Rs\.?|₹)\s*([\d,]+\.?\d*){unit_suffix}", text, re.I)
    )

    # Sanity bounds: real SARFAESI secured debts are essentially never
    # under ₹1,000 (extraction grabbed a fragment) or over ₹10,000 crore
    # (extraction bug or a source drafting error) — treat either as a
    # failed extraction (falls through to debug review) rather than
    # silently storing a confidently wrong number.
    if amount is not None and (amount < 1_000 or amount > 100_000_000_000):
        amount = None

    # Property description sits between "...assets to be sold" and the
    # encumbrances clause — anchor on those phrases directly rather than
    # exact section numbers (numbering style and spacing varies enough
    # between branches that "03"/"04" isn't reliable, e.g. "D etails"
    # with a stray space has been seen in at least one branch's PDF).
    # The anchor's own internal whitespace must also be flexible — real
    # PDFs (e.g. SARB Jorhat's Bhaskar Jyoti Saikia notice, fetched
    # 2026-08-18) wrap mid-phrase as "Details of the\nencumbrances",
    # which a literal single-space match silently fails on, dropping the
    # property description entirely for that record.
    raw_section_03 = find(
        r"assets to be sold\.?\s*(.*?)\s*D\s*etails\s+of\s+the\s+encumbrances",
        flags=re.I | re.S,
    )
    property_desc = None
    if raw_section_03:
        property_desc = re.sub(r"\s+", " ", raw_section_03).strip() or None

    loan_account = _first_plausible_account_ref(
        find(r"(?:loan|account)\s*(?:no\.?|number)[:\s]*([A-Za-z0-9/-]+)"),
        find(r"Property ID[-:\s]*([A-Za-z0-9]+)"),
    )

    return {
        "estimated_liability": amount,
        "loan_account_ref": loan_account,
        "asset_description": property_desc,
    }


def _first_plausible_account_ref(*candidates: str | None) -> str | None:
    """Returns the first candidate that looks like a real account/Property
    ID rather than a stray word picked up from a flattened PDF table
    header. Seen in production: a 2-column table ("Property ID | No |
    EMD (Rs.)") collapses into linear text as "Property ID No EMD
    (Rs.)...", and the naive 'Property ID[-:\\s]*([A-Za-z0-9]+)' fallback
    then captures the header word "No" as if it were the ID itself
    (account_number = "No" — SBI-Manoj Solanki notice, fetched
    2026-08-18). Real SBI Property IDs/account numbers (e.g.
    'SBIN200060644879') always contain digits and run considerably
    longer than a stray header word, so that's the bar for 'plausible'."""
    for candidate in candidates:
        if candidate and len(candidate) >= 6 and any(ch.isdigit() for ch in candidate):
            return candidate
    return None


LOAN_TYPE_KEYWORDS = {
    "Business Loan": ["m/s", "pvt ltd", "pvt. ltd", "enterprise", "industries", "traders",
                       "ispat", "ceramics", "fuels", "metals", "auto pvt", "solutions pvt"],
    "Home Loan": ["home loan", "housing loan", "residential flat", "apartment"],
    "Vehicle Loan": ["vehicle loan", "car loan", "auto loan", "commercial vehicle"],
    "Gold Loan": ["gold loan", "jewel loan", "jewellery loan"],
    "Agriculture Loan": ["agriculture loan", "kisan", "crop loan", "agricultural land"],
    "Education Loan": ["education loan", "student loan"],
    "Credit Card": ["credit card"],
    "Trade Credit": ["trade credit", "cash credit", "working capital"],
}


def classify_loan_type(description: str, doc_label: str) -> str:
    """Matches the DB's fixed loan_type enum. Conservative keyword match
    on the notice description and document label — defaults to 'Other'
    when nothing matches rather than guessing a specific category."""
    lowered = f"{description} {doc_label}".lower()
    for loan_type, keywords in LOAN_TYPE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return loan_type
    return "Other"


ASSET_TYPE_KEYWORDS = {
    "Apartment": ["apartment", "flat", "flat no", "residential flat"],
    "House": ["house", "bungalow", "residential building", "residential property"],
    "Land": ["land", "plot", "acre", "vacant site", "agricultural land"],
    "Vehicle": ["vehicle", "car", "truck", "lorry", "motor", "bus"],
    "Gold": ["gold", "jewellery", "jewelry", "ornament"],
    "Machinery": ["machinery", "equipment", "plant &", "plant and machinery"],
    "Inventory": ["inventory", "stock", "goods"],
    "Business": ["business", "shop", "commercial establishment", "godown"],
}


def classify_asset_type(description: str) -> str:
    """Matches the DB's fixed asset_type enum. Keyword-based and
    intentionally conservative — falls back to 'Other' rather than
    guessing, since the extracted description text is often noisy."""
    lowered = description.lower()
    for asset_type, keywords in ASSET_TYPE_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return asset_type
    return "Other"


_LENDER_PARTY_CACHE: dict[str, str] = {}
_BORROWER_PARTY_CACHE: dict[str, str] = {}

COMPANY_KEYWORDS = ["m/s", "pvt ltd", "pvt. ltd", "ltd", "llp", "enterprise", "enterprises",
                    "industries", "traders", "ispat", "ceramics", "fuels", "metals", "solutions"]


def clean_party_name(doc_label: str) -> str:
    """Doc labels look like '1. M/S GOVINDA INDUSTRIES PVT LTD(396.72 KB)',
    '2. SHRI BRAJESH VISHWAKARMA:USP(813.18 KB)', or (seen on later pages)
    'DIPANKAR BORTHAKUR-T&C' / 'DIPANKAR BORTHAKUR-SALE NOTICE' — SBI uses
    both colon and dash as the document-type suffix separator depending
    on the branch/batch. Strip numbering, file size, and EITHER suffix
    style to get just the party's name."""
    name = re.sub(r"^\d+\.\s*", "", doc_label)
    name = re.sub(r"\([\d.]+\s*[KM]?B\)\s*$", "", name)
    name = re.sub(
        r"[:\-]\s*(USP|SALE\s*NOTICE|T\s*&\s*C|TERMS?\s*(AND|&)\s*CONDITIONS?)\s*.*$",
        "",
        name,
        flags=re.I,
    )
    return name.strip()


def classify_party_type(name: str) -> str:
    """Matches the DB's fixed party_type enum. Defaults to 'Individual'
    since most SARFAESI borrowers are — flags to 'Company' only on a
    clear textual signal."""
    lowered = name.lower()
    if any(kw in lowered for kw in COMPANY_KEYWORDS):
        return "Company"
    return "Individual"


def get_or_create_party(full_name: str, party_type: str, cache: dict) -> str:
    """Dedupes by exact (case-insensitive) name match within a run.
    Note: this is a same-run cache only — across separate script runs,
    repeat names will re-query Supabase but should still resolve to the
    same existing row via the ilike lookup, avoiding duplicates."""
    key = full_name.lower()
    if key in cache:
        return cache[key]

    existing = (
        supabase.table("parties")
        .select("id")
        .ilike("full_name", full_name)
        .is_("deleted_at", "null")
        .execute()
    )
    if existing.data:
        party_id = existing.data[0]["id"]
    else:
        inserted = supabase.table("parties").insert({
            "full_name": full_name,
            "party_type": party_type,
        }).execute()
        party_id = inserted.data[0]["id"]

    cache[key] = party_id
    return party_id


def link_case_party(case_id: str, party_id: str, role: str):
    supabase.table("case_parties").insert({
        "case_id": case_id,
        "party_id": party_id,
        "role": role,
    }).execute()


def classify_document_type(label: str) -> str:
    """No DB constraint on this column, but keeping it a controlled
    vocabulary anyway for consistency across sources."""
    lowered = label.lower()
    if "sale notice" in lowered:
        return "sale_notice"
    if "usp" in lowered:
        return "property_fact_sheet"
    return "terms_and_conditions"


def make_case_reference(description: str, auction_date: str | None, borrower_name: str) -> str:
    """Stable dedup key so re-running the scraper doesn't create duplicate
    cases. Keyed on borrower identity (not a single doc URL) since one
    case can now have multiple attached documents."""
    raw = f"{SOURCE_NAME}|{description}|{auction_date}|{borrower_name.lower()}"
    return "SBI-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def case_exists(case_reference: str) -> bool:
    result = (
        supabase.table("cases")
        .select("id")
        .eq("case_reference", case_reference)
        .is_("deleted_at", "null")
        .execute()
    )
    return len(result.data) > 0


def group_documents_by_borrower(documents: list[dict]) -> dict[str, list[dict]]:
    """A single notice row can cover multiple distinct people, and each
    person can have multiple PDFs (Terms & Conditions, Sale Notice, USP
    fact sheet). Group by cleaned name so all of one person's documents
    land on one case instead of being split into separate cases."""
    groups: dict[str, list[dict]] = {}
    for doc in documents:
        name = clean_party_name(doc["label"])
        groups.setdefault(name, []).append(doc)
    return groups


def ingest_notice(row: dict) -> tuple[int, int]:
    ingested_count = 0
    skipped_count = 0

    for borrower_name, docs in group_documents_by_borrower(row["documents"]).items():
        if not borrower_name:
            continue  # couldn't extract a usable name — skip rather than create an unlabeled case

        case_reference = make_case_reference(row["description"], row["auction_date"], borrower_name)
        if case_exists(case_reference):
            skipped_count += 1
            continue  # already ingested, skip

        # Fetch + extract every doc for this borrower, merging fields —
        # e.g. the T&C doc usually has the amount, the USP doc usually
        # has a cleaner property description. First non-empty value wins.
        merged_fields: dict = {}
        pdf_texts: dict[str, str] = {}
        for doc in docs:
            try:
                text = download_and_extract_pdf_text(doc["url"])
            except Exception as e:
                print(f"  ! failed to fetch/parse PDF {doc['url']}: {e}")
                text = ""
            pdf_texts[doc["url"]] = text
            if text:
                extracted = extract_fields_from_pdf_text(text)
                for k, v in extracted.items():
                    if v and not merged_fields.get(k):
                        merged_fields[k] = v

        # Only dump for debugging if NONE of this borrower's docs yielded
        # a liability amount — avoids false "failures" when one doc in
        # the group (e.g. the USP fact sheet) legitimately has no figure.
        if not merged_fields.get("estimated_liability"):
            os.makedirs("debug_pdf_text", exist_ok=True)
            for i, (url, text) in enumerate(pdf_texts.items()):
                if text:
                    with open(f"debug_pdf_text/{case_reference}_{i}.txt", "w", encoding="utf-8") as f:
                        f.write(text)

        case_row = {
            "case_reference": case_reference,
            "title": borrower_name,
            "case_type": "SARFAESI",
            "status": "active",
            "court_name": None,  # SARFAESI is out-of-court; leave null or store DRT if appeal exists
            "next_hearing_date": None,
            "filing_date": row["auction_date"],  # closest available date; adjust if you find a better one
            "estimated_liability": merged_fields.get("estimated_liability"),
            "summary": row["description"],
            "metadata": {
                "source": SOURCE_NAME,
                "source_urls": [d["url"] for d in docs],
                "loan_account_ref": merged_fields.get("loan_account_ref"),
            },
        }

        inserted_case = supabase.table("cases").insert(case_row).select().execute()
        case_id = inserted_case.data[0]["id"]

        # --- Parties: lender (cached across the whole run) and borrower ---
        lender_id = get_or_create_party(SOURCE_NAME_FULL, "Bank", _LENDER_PARTY_CACHE)
        link_case_party(case_id, lender_id, "Lender")

        borrower_type = classify_party_type(borrower_name)
        borrower_id = get_or_create_party(borrower_name, borrower_type, _BORROWER_PARTY_CACHE)
        link_case_party(case_id, borrower_id, "Borrower")

        # --- Documents: attach ALL of this borrower's PDFs to the one case ---
        for doc in docs:
            supabase.table("documents").insert({
                "case_id": case_id,
                "document_type": classify_document_type(doc["label"]),
                "document_name": doc["label"],
                "storage_path": doc["url"],  # storing source URL for now; swap for Supabase Storage path if you mirror the PDF
                "processed": bool(pdf_texts.get(doc["url"])),
                "metadata": {"source": SOURCE_NAME},
            }).execute()

        if merged_fields.get("estimated_liability"):
            supabase.table("liabilities").insert({
                "case_id": case_id,
                "lender_id": lender_id,
                "loan_type": classify_loan_type(row["description"], borrower_name),
                "account_number": merged_fields.get("loan_account_ref"),
                "outstanding_amount": merged_fields["estimated_liability"],
                "currency_code": "INR",
                "secured": True,
                "remarks": f"Auto-ingested from {SOURCE_NAME} sale notice; verify against source PDF.",
            }).execute()

        if merged_fields.get("asset_description"):
            supabase.table("assets").insert({
                "case_id": case_id,
                "asset_type": classify_asset_type(merged_fields["asset_description"]),
                "description": merged_fields["asset_description"],
                "auction_date": row["auction_date"],
                "auction_status": "scheduled",
            }).execute()

        print(f"  + ingested case {case_reference} ({borrower_name}, {len(docs)} docs)")
        ingested_count += 1

    return ingested_count, skipped_count


def run(max_pages: int | None = None):
    """max_pages=None scrapes until a page returns zero notices (the real
    end of the list) rather than a hardcoded page count, since SBI's total
    page count can drift over time as new notices are published."""
    total_ingested = 0
    total_skipped = 0

    print(f"Fetching page 1: {BASE_URL}")
    soup, html = fetch_notice_page(BASE_URL)
    instance_id = extract_portlet_instance_id(html)
    if not instance_id:
        print("  ! could not find the Liferay portlet instance ID — "
              "SBI may have changed their page layout. Falling back to page 1 only.")
        rows = parse_notice_rows(soup)
        print(f"  found {len(rows)} notices")
        for row in rows:
            ingested, skipped = ingest_notice(row)
            total_ingested += ingested
            total_skipped += skipped
        print(f"\nDone. Ingested: {total_ingested}, skipped (already existed): {total_skipped}")
        return

    print(f"  found portlet instance id: {instance_id}")
    rows = parse_notice_rows(soup)
    print(f"  found {len(rows)} notices")
    for row in rows:
        ingested, skipped = ingest_notice(row)
        total_ingested += ingested
        total_skipped += skipped

    page_num = 2
    while True:
        if max_pages and page_num > max_pages:
            break

        url = build_page_url(instance_id, page_num)
        print(f"Fetching page {page_num}: {url}")
        soup, _ = fetch_notice_page(url)
        rows = parse_notice_rows(soup)
        print(f"  found {len(rows)} notices")

        if not rows:
            print("  (empty page — reached the end of the list)")
            break

        for row in rows:
            ingested, skipped = ingest_notice(row)
            total_ingested += ingested
            total_skipped += skipped

        page_num += 1

    print(f"\nDone. Ingested: {total_ingested}, skipped (already existed): {total_skipped}")


if __name__ == "__main__":
    run()