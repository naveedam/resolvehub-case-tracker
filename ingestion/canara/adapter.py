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
                            record = self._build_record(row, page_num)
                        except Exception:
                            continue  # a malformed row shouldn't stop the whole page/PDF
                        if record is not None:
                            yield record

    def _build_record(self, row: list, page_num: int) -> NormalizedRecord | None:
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
        asset_classification_raw = scraper.clean_cell(row[10])
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

        # Every observation traces back to the one master PDF plus the
        # specific page its row was extracted from — the master PDF is a
        # single ~13MB document covering every branch, so "which page"
        # is the only meaningful provenance granularity available (there
        # is no per-row publication date to set as published_at, unlike
        # a per-notice PDF — same reasoning as the SBI published_at fix:
        # don't invent a date the source doesn't actually give us).
        source_kwargs = {
            "source_document_url": scraper.MASTER_PDF_URL,
            "source_record_ref": f"master_pdf_page_{page_num + 1}",
        }

        observations: list[FieldObservation] = []
        if amount:
            observations.append(
                FieldObservation(
                    entity_type="case", field_name="estimated_liability",
                    value_numeric=amount, unit="INR", **source_kwargs,
                )
            )
            observations.append(
                FieldObservation(
                    entity_type="liability", field_name="outstanding_amount",
                    value_numeric=amount, unit="INR", **source_kwargs,
                )
            )
        if npa_date:
            observations.append(
                FieldObservation(entity_type="case", field_name="npa_date", value_date=npa_date, **source_kwargs)
            )

        asset_type = None
        if security_details and security_details not in ("#N/A", "-"):
            asset_type = scraper.classify_asset_type(security_details)
            observations.append(
                FieldObservation(
                    entity_type="asset", field_name="description", value_text=security_details, **source_kwargs,
                )
            )
            observations.append(
                FieldObservation(
                    entity_type="asset", field_name="possession_status", value_text="possessed", **source_kwargs,
                )
            )
        # Distinct from `asset_type` above: that's a classification WE
        # derive locally from security_details via keyword matching;
        # asset_classification_raw is the bank's OWN reported category
        # (row[10] — captured in the pre-Phase-1 scraper.ingest_row()'s
        # metadata blob, but silently dropped when this adapter was
        # first ported to the evidence-layer model). Both are worth
        # keeping since they can disagree.
        if asset_classification_raw and asset_classification_raw not in ("#N/A", "-"):
            observations.append(
                FieldObservation(
                    entity_type="asset", field_name="asset_classification",
                    value_text=asset_classification_raw, confidence="source_derived", **source_kwargs,
                )
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


def find_record_by_case_reference(adapter: "CanaraAdapter", case_reference: str) -> NormalizedRecord | None:
    """Same pattern as ingestion/sbi/adapter.py's equivalent: walks the
    adapter's normal collection and returns the first match, or None —
    run BEFORE run_ingestion so a --case-reference that doesn't match
    anything is detected without ever touching Supabase. Kept local
    rather than shared from ingestion.sbi.adapter to avoid touching
    SBI's already-live production single-record workflow in this
    Canara-scoped change; a shared ingestion/common module is a
    reasonable follow-up, not done here."""
    for record in adapter.collect():
        if record.case_reference == case_reference:
            return record
    return None


class SingleRecordAdapter:
    """Wraps a real adapter so run_ingestion() sees exactly one,
    already-selected record. See ingestion/sbi/adapter.py's identical
    class for the full rationale."""

    def __init__(self, adapter: "CanaraAdapter", record: NormalizedRecord):
        self.source_name = adapter.source_name
        self.source_full_name = adapter.source_full_name
        self.source_type = adapter.source_type
        self._record = record

    def collect(self) -> Iterator[NormalizedRecord]:
        yield self._record


if __name__ == "__main__":
    import argparse
    import os
    import sys

    from dotenv import load_dotenv
    from supabase import create_client

    from ingestion.common.runtime import run_ingestion
    from ingestion.common.store import SupabaseStore

    parser = argparse.ArgumentParser(description="Run the Canara ingestion adapter.")
    parser.add_argument(
        "--case-reference",
        metavar="CASE_REF",
        help=(
            "Only ingest the single record matching this case_reference "
            "(e.g. CANARA-48e02e7fafd70ec6). The adapter still collects "
            "normally (downloads and scans the whole master PDF); only "
            "this one record is passed to the ingestion runtime. If no "
            "record matches, nothing is written. Omit this flag to run "
            "the full collection, exactly as before."
        ),
    )
    args = parser.parse_args()

    load_dotenv()
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    store = SupabaseStore(client)
    adapter = CanaraAdapter()

    if args.case_reference:
        print(f"Scanning Canara's master PDF for case_reference={args.case_reference!r} ...")
        match = find_record_by_case_reference(adapter, args.case_reference)
        if match is None:
            print(f"No record found with case_reference={args.case_reference!r}. Nothing written.")
            sys.exit(1)
        print(f"Selected case: {match.case_reference} — {match.title}")
        print(f"  case_type: {match.case_type} | documents: {len(match.documents)} | "
              f"observations: {len(match.field_observations)}")
        target_adapter = SingleRecordAdapter(adapter, match)
    else:
        target_adapter = adapter

    result = run_ingestion(target_adapter, store)
    print(f"Canara run {result.run_id}: {result.status} — seen {result.seen}, "
          f"new {result.ingested}, existing {result.skipped}, failed {result.failed}")
    if result.errors:
        print("Errors:", result.errors)
