"""CanaraAdapter — wraps the existing scraper.py master-PDF table
extraction and yields NormalizedRecord objects for the shared ingestion
runtime, instead of writing to Supabase directly the way scraper.py's
own `run()`/`ingest_row()` still do.

scraper.py itself is left completely unmodified. See the equivalent note
in ingestion/sbi/adapter.py.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterator

import pdfplumber

from ingestion.canara import scraper
from ingestion.common.models import FieldObservation, NormalizedDocument, NormalizedRecord


class CanaraAdapter:
    source_name = "Canara"
    source_full_name = "Canara Bank"
    source_type = "bank"

    def __init__(self, max_pages: int | None = None, start_page: int = 0):
        self.max_pages = max_pages
        self.start_page = start_page

    def collect(self) -> Iterator[NormalizedRecord]:
        scraper.download_master_pdf()
        with pdfplumber.open(scraper.LOCAL_PDF_PATH) as pdf:
            total_pages = len(pdf.pages)
            end_page = total_pages if self.max_pages is None else min(self.start_page + self.max_pages, total_pages)
            for page_num in range(self.start_page, end_page):
                for table in pdf.pages[page_num].extract_tables():
                    for row in table:
                        if not row or scraper.is_header_row(row):
                            continue
                        try:
                            record = self._build_record(row)
                        except Exception:
                            continue  # a malformed row shouldn't stop the whole page/PDF
                        if record is not None:
                            yield record

    def _build_record(self, row: list) -> NormalizedRecord | None:
        if len(row) < 15:
            return None

        circle = scraper.clean_cell(row[0])
        ro_name = scraper.clean_cell(row[1])
        branch = scraper.clean_cell(row[2])
        state = scraper.clean_cell(row[3])
        borrower_name = scraper.clean_cell(row[4])
        guarantor_raw = scraper.clean_cell(row[6])
        outstanding_raw = scraper.clean_cell(row[8])
        npa_date_raw = scraper.clean_cell(row[9])
        security_details = scraper.clean_cell(row[11])

        if not borrower_name or borrower_name in ("#N/A", "-"):
            return None
        if guarantor_raw in ("#N/A", "-", ""):
            guarantor_raw = None

        amount = scraper.parse_amount(outstanding_raw)
        case_reference = scraper.make_case_reference(branch, borrower_name, outstanding_raw, npa_date_raw)
        borrower_type = scraper.classify_party_type(borrower_name)
        npa_date = _parse_loose_date(npa_date_raw)

        guarantors: list[tuple[str, str]] = []
        if guarantor_raw:
            first_guarantor = re.split(r"[,\n]", guarantor_raw)[0].strip()
            if first_guarantor:
                guarantors.append((first_guarantor, scraper.classify_party_type(first_guarantor)))

        observations: list[FieldObservation] = []
        if amount:
            observations.append(
                FieldObservation(entity_type="case", field_name="estimated_liability", value_numeric=amount, unit="INR")
            )
            observations.append(
                FieldObservation(entity_type="liability", field_name="outstanding_amount", value_numeric=amount, unit="INR")
            )
        if npa_date:
            observations.append(FieldObservation(entity_type="case", field_name="npa_date", value_date=npa_date))

        asset_type = None
        if security_details:
            asset_type = scraper.classify_asset_type(security_details)
            observations.append(
                FieldObservation(entity_type="asset", field_name="description", value_text=security_details)
            )
            observations.append(
                FieldObservation(entity_type="asset", field_name="possession_status", value_text="possessed")
            )

        return NormalizedRecord(
            case_reference=case_reference,
            title=borrower_name,
            case_type="SARFAESI",
            summary=f"Possession taken - {branch}, {state} (Circle: {circle}, RO: {ro_name})",
            borrower_name=borrower_name,
            borrower_type=borrower_type,
            lender_name=scraper.SOURCE_NAME_FULL,
            guarantors=guarantors,
            asset_type=asset_type,
            documents=[
                NormalizedDocument(
                    document_type="possession_notice",
                    document_name="Possession Taken - Bank As A Whole",
                    storage_path=scraper.MASTER_PDF_URL,
                )
            ],
            field_observations=observations,
        )


def _parse_loose_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            from datetime import datetime

            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv
    from supabase import create_client

    from ingestion.common.runtime import run_ingestion
    from ingestion.common.store import SupabaseStore

    load_dotenv()
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    result = run_ingestion(CanaraAdapter(), SupabaseStore(client))
    print(f"Canara run {result.run_id}: {result.status} — seen {result.seen}, "
          f"new {result.ingested}, existing {result.skipped}, failed {result.failed}")
    if result.errors:
        print("Errors:", result.errors)
