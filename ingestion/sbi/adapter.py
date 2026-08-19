"""SBIAdapter — wraps the existing scraper.py extraction logic (Liferay
pagination, PDF download/extraction, field regex) and yields
NormalizedRecord objects for the shared ingestion runtime, instead of
writing to Supabase directly the way scraper.py's own
`run()`/`ingest_notice()` still do.

scraper.py itself is left completely unmodified and remains runnable
standalone exactly as it was before Phase 1. Once this adapter path has
been validated against production, scraper.py's now-redundant
`ingest_notice`/`run` can be retired in a follow-up cleanup — not done
here, to keep this change purely additive.
"""

from __future__ import annotations

from datetime import date
from typing import Iterator

from ingestion.common.models import FieldObservation, Identifier, NormalizedDocument, NormalizedRecord
from ingestion.sbi import scraper


class SBIAdapter:
    source_name = "SBI"
    source_full_name = "State Bank of India"
    source_type = "bank"

    def __init__(self, max_pages: int | None = None):
        self.max_pages = max_pages

    def collect(self) -> Iterator[NormalizedRecord]:
        soup, html = scraper.fetch_notice_page(scraper.BASE_URL)
        instance_id = scraper.extract_portlet_instance_id(html)

        yield from self._records_from_rows(scraper.parse_notice_rows(soup))

        if not instance_id:
            return  # matches scraper.py's own fallback behavior: page 1 only

        page_num = 2
        while True:
            if self.max_pages and page_num > self.max_pages:
                break
            url = scraper.build_page_url(instance_id, page_num)
            soup, _ = scraper.fetch_notice_page(url)
            rows = scraper.parse_notice_rows(soup)
            if not rows:
                break
            yield from self._records_from_rows(rows)
            page_num += 1

    def _records_from_rows(self, rows: list[dict]) -> Iterator[NormalizedRecord]:
        for row in rows:
            for borrower_name, docs in scraper.group_documents_by_borrower(row["documents"]).items():
                if not borrower_name:
                    continue
                record = self._build_record(row, borrower_name, docs)
                if record is not None:
                    yield record

    def _build_record(self, row: dict, borrower_name: str, docs: list[dict]) -> NormalizedRecord:
        case_reference = scraper.make_case_reference(row["description"], row["auction_date"], borrower_name)

        merged_fields: dict = {}
        merged_sources: dict[str, str] = {}
        for doc in docs:
            try:
                text = scraper.download_and_extract_pdf_text(doc["url"])
            except Exception:
                text = ""
            if text:
                extracted = scraper.extract_fields_from_pdf_text(text)
                for k, v in extracted.items():
                    if v and not merged_fields.get(k):
                        merged_fields[k] = v
                        merged_sources[k] = doc["url"]

        auction_date = _parse_iso_date(row["auction_date"])
        borrower_type = scraper.classify_party_type(borrower_name)
        observations: list[FieldObservation] = []

        # NOTE: SBI's notice page only ever gives us an auction date, never
        # an actual publication date for the notice/PDF — parse_notice_rows
        # doesn't extract one because the source doesn't expose one. Using
        # auction_date as published_at was wrong: it's the date the sale is
        # scheduled FOR, not the date this information was published. Every
        # observation below leaves published_at unset (None) unless a real
        # publication date becomes available from a future source. The
        # auction_date FIELD itself still correctly carries auction_date as
        # its *value* — that part was never wrong.
        if merged_fields.get("estimated_liability"):
            amount = merged_fields["estimated_liability"]
            amount_source_url = merged_sources.get("estimated_liability")
            observations.append(
                FieldObservation(
                    entity_type="case", field_name="estimated_liability",
                    value_numeric=amount, unit="INR",
                    source_document_url=amount_source_url,
                )
            )
            observations.append(
                FieldObservation(
                    entity_type="liability", field_name="outstanding_amount",
                    value_numeric=amount, unit="INR",
                    source_document_url=amount_source_url,
                )
            )
            observations.append(
                FieldObservation(
                    entity_type="liability", field_name="loan_type",
                    value_text=scraper.classify_loan_type(row["description"], borrower_name),
                    confidence="inferred",
                )
            )

        if merged_fields.get("loan_account_ref"):
            observations.append(
                FieldObservation(
                    entity_type="liability", field_name="account_number",
                    value_text=merged_fields["loan_account_ref"],
                    source_document_url=merged_sources.get("loan_account_ref"),
                )
            )

        asset_type = None
        if merged_fields.get("asset_description"):
            asset_type = scraper.classify_asset_type(merged_fields["asset_description"])
            observations.append(
                FieldObservation(
                    entity_type="asset", field_name="description",
                    value_text=merged_fields["asset_description"],
                    source_document_url=merged_sources.get("asset_description"),
                )
            )
            if auction_date:
                observations.append(
                    FieldObservation(
                        entity_type="asset", field_name="auction_date",
                        value_date=auction_date,
                    )
                )
            observations.append(
                FieldObservation(
                    entity_type="asset", field_name="auction_status",
                    value_text="scheduled", confidence="inferred",
                )
            )

        identifiers: list[Identifier] = []
        if merged_fields.get("loan_account_ref"):
            identifiers.append(
                Identifier(
                    entity_type="case", identifier_type="bank_account_ref",
                    identifier_value=merged_fields["loan_account_ref"],
                )
            )

        return NormalizedRecord(
            case_reference=case_reference,
            title=borrower_name,
            case_type="SARFAESI",
            summary=row["description"],
            borrower_name=borrower_name,
            borrower_type=borrower_type,
            lender_name=scraper.SOURCE_NAME_FULL,
            filing_date=auction_date,
            asset_type=asset_type,
            documents=[
                NormalizedDocument(
                    document_type=scraper.classify_document_type(doc["label"]),
                    document_name=doc["label"],
                    storage_path=doc["url"],
                )
                for doc in docs
            ],
            field_observations=observations,
            identifiers=identifiers,
        )


def _parse_iso_date(raw: str | None) -> date | None:
    """row['auction_date'] arrives already normalized to ISO by
    scraper.parse_notice_rows(), so this is a plain parse, not free-form."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def find_record_by_case_reference(adapter: "SBIAdapter", case_reference: str) -> NormalizedRecord | None:
    """Walks the adapter's normal collection — the same pages and PDFs it
    would always walk — and returns the first record whose
    case_reference matches, or None. This runs BEFORE run_ingestion, so
    a --case-reference that doesn't match anything is detected (and can
    be reported) without ever calling run_ingestion — meaning without
    ever touching Supabase, not even to register a zero-record run."""
    for record in adapter.collect():
        if record.case_reference == case_reference:
            return record
    return None


class SingleRecordAdapter:
    """Wraps a real adapter so run_ingestion() sees exactly one,
    already-selected record. Satisfies the same SourceAdapter contract
    (source_name/source_full_name/source_type/collect()) as the real
    adapter, so ingestion/common/runtime.py needs no changes at all to
    support this — it has no idea a filter is in play."""

    def __init__(self, adapter: "SBIAdapter", record: NormalizedRecord):
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

    parser = argparse.ArgumentParser(description="Run the SBI ingestion adapter.")
    parser.add_argument(
        "--case-reference",
        metavar="CASE_REF",
        help=(
            "Only ingest the single record matching this case_reference "
            "(e.g. SBI-77dd5b49b548d50d). The adapter still collects "
            "normally; only this one record is passed to the ingestion "
            "runtime. If no record matches, nothing is written — not even "
            "an ingestion_runs row. Omit this flag to run the full "
            "collection, exactly as before."
        ),
    )
    args = parser.parse_args()

    load_dotenv()
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    store = SupabaseStore(client)
    adapter = SBIAdapter()

    if args.case_reference:
        print(f"Searching SBI's current notices for case_reference={args.case_reference!r} ...")
        match = find_record_by_case_reference(adapter, args.case_reference)
        if match is None:
            print(f"No record found with case_reference={args.case_reference!r}. Nothing written.")
            sys.exit(1)
        print(f"Selected case: {match.case_reference} — {match.title}")
        print(f"  case_type: {match.case_type} | filing_date: {match.filing_date} | "
              f"documents: {len(match.documents)} | observations: {len(match.field_observations)}")
        target_adapter = SingleRecordAdapter(adapter, match)
    else:
        target_adapter = adapter

    result = run_ingestion(target_adapter, store)
    print(f"SBI run {result.run_id}: {result.status} — seen {result.seen}, "
          f"new {result.ingested}, existing {result.skipped}, failed {result.failed}")
    if result.errors:
        print("Errors:", result.errors)
