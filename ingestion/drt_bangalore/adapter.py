"""
ResolveHub - DRT-1 Bangalore adapter (canonical reference implementation)
----------------------------------------------------------------------------
Maps parser.py's structured output onto the EXISTING ResolveHub schema -
cases / parties / case_parties. No new tables, no Resolution Profile
concepts. Idempotent: safe to re-run, does nothing if the case already
exists.

Also serves as the orchestrator: fetch -> parse -> ingest, mirroring the
scraper.py run() pattern used by SBI/Canara/Axis.

Env vars required: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
"""

import os
import re
from supabase import create_client
from dotenv import load_dotenv

import scraper
import parser as drt_parser  # avoid shadowing the stdlib-adjacent name

load_dotenv()

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

COMPANY_KEYWORDS = ["m/s", "pvt ltd", "pvt. ltd", "ltd", "llp", "associates", "enterprise",
                    "enterprises", "industries", "traders", "corporation", "company", "bank"]


def classify_party_type(name: str) -> str:
    """Reuses the same keyword-based approach as sarfaesi_common.py's
    classify_party_type, extended with 'bank'/'associates' since those
    are common in judicial-proceeding party names."""
    lowered = name.lower()
    if "bank" in lowered:
        return "Bank"
    if any(kw in lowered for kw in COMPANY_KEYWORDS):
        return "Company"
    return "Individual"


def make_case_reference(tribunal_short: str, case_number: str) -> str:
    """e.g. tribunal_short='BLR1', case_number='SA/382/2025' ->
    'DRT1-SA-382-2025'."""
    safe_case_number = re.sub(r"[^A-Za-z0-9]+", "-", case_number).strip("-").upper()
    return f"DRT-{tribunal_short}-{safe_case_number}"


def case_exists(case_reference: str) -> bool:
    result = (
        supabase.table("cases")
        .select("id")
        .eq("case_reference", case_reference)
        .is_("deleted_at", "null")
        .execute()
    )
    return len(result.data) > 0


def get_or_create_party(full_name: str, party_type: str) -> str:
    existing = (
        supabase.table("parties")
        .select("id")
        .ilike("full_name", full_name)
        .is_("deleted_at", "null")
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    inserted = supabase.table("parties").insert({
        "full_name": full_name,
        "party_type": party_type,
    }).execute()
    return inserted.data[0]["id"]


def link_case_party(case_id: str, party_id: str, role: str):
    supabase.table("case_parties").insert({
        "case_id": case_id,
        "party_id": party_id,
        "role": role,
    }).execute()


def ingest(fields: dict, tribunal_short: str = "BLR1"):
    """Takes parser.py's output dict, inserts into cases/parties/
    case_parties. Returns the case_id, or None if it already existed
    (idempotent no-op)."""
    case_number = fields.get("case_number")
    if not case_number:
        raise ValueError("Parsed fields missing case_number - cannot build a case_reference")

    case_reference = make_case_reference(tribunal_short, case_number)

    if case_exists(case_reference):
        print(f"Case {case_reference} already exists - skipping (idempotent).")
        return None

    status = (fields.get("status") or "pending").strip().lower()

    case_row = {
        "case_reference": case_reference,
        "title": (fields.get("applicant") or "UNKNOWN APPLICANT").upper(),
        "case_type": fields.get("case_type") or "SA",
        "status": status,
        "court_name": fields.get("tribunal"),
        "filing_date": fields.get("filing_date"),
        "next_hearing_date": None,
        "estimated_liability": None,
        "summary": f"{case_number} - Securitisation Application before {fields.get('tribunal')}."
                   + (f" Diary No. {fields['diary_number']}." if fields.get("diary_number") else ""),
        "metadata": {
            "source": "DRT-Bangalore",
            "drt_case_number": case_number,
            "diary_number": fields.get("diary_number"),
            "applicant_advocate": fields.get("applicant_advocate"),
            "respondent_advocate": fields.get("respondent_advocate"),
        },
    }

    inserted = supabase.table("cases").insert(case_row).select().execute()
    case_id = inserted.data[0]["id"]
    print(f"Inserted case {case_reference} (id={case_id})")

    if fields.get("applicant"):
        applicant_id = get_or_create_party(fields["applicant"], classify_party_type(fields["applicant"]))
        link_case_party(case_id, applicant_id, "Petitioner")
        print(f"  linked applicant: {fields['applicant']} (role: Petitioner)")

    if fields.get("respondent"):
        respondent_id = get_or_create_party(fields["respondent"], classify_party_type(fields["respondent"]))
        link_case_party(case_id, respondent_id, "Respondent")
        print(f"  linked respondent: {fields['respondent']} (role: Respondent)")

    return case_id


def run():
    html = scraper.fetch_local_html("SA-382-2025.html")
    fields = drt_parser.parse_case_html(html)
    print(f"Parsed fields: {fields}")
    ingest(fields)
    print("\nDone.")


if __name__ == "__main__":
    run()
