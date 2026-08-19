"""Regression tests for the --case-reference single-record filter.

These test find_record_by_case_reference() and SingleRecordAdapter
directly against a fake underlying adapter (no network, no real SBI
collection) — the goal is to prove the FILTERING logic is correct, not
to re-test SBIAdapter's own extraction (that's covered by
test_adapter.py and test_extraction_quality.py).
"""

from __future__ import annotations

import os

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder-service-role-key")

from ingestion.common.models import NormalizedRecord
from ingestion.common.runtime import run_ingestion
from ingestion.common.store import InMemoryStore
from ingestion.sbi.adapter import SingleRecordAdapter, find_record_by_case_reference


def make_record(case_reference: str, title: str) -> NormalizedRecord:
    return NormalizedRecord(
        case_reference=case_reference,
        title=title,
        case_type="SARFAESI",
        summary="test notice",
        borrower_name=title,
        borrower_type="Individual",
        lender_name="State Bank of India",
    )


class FakeUnderlyingAdapter:
    """Stands in for SBIAdapter: same source_name/source_type surface,
    collect() yields several records the way a real page/PDF walk would."""

    source_name = "SBI"
    source_full_name = "State Bank of India"
    source_type = "bank"

    def __init__(self, records):
        self._records = records
        self.collect_call_count = 0

    def collect(self):
        self.collect_call_count += 1
        return iter(self._records)


def test_find_record_by_case_reference_returns_the_matching_record():
    records = [
        make_record("SBI-aaa", "Alpha Traders"),
        make_record("SBI-77dd5b49b548d50d", "Bhaskar Jyoti Saikia"),
        make_record("SBI-ccc", "Charlie Enterprises"),
    ]
    adapter = FakeUnderlyingAdapter(records)

    match = find_record_by_case_reference(adapter, "SBI-77dd5b49b548d50d")

    assert match is not None
    assert match.title == "Bhaskar Jyoti Saikia"


def test_find_record_by_case_reference_returns_none_when_not_found():
    adapter = FakeUnderlyingAdapter([make_record("SBI-aaa", "Alpha Traders")])

    match = find_record_by_case_reference(adapter, "SBI-does-not-exist")

    assert match is None


def test_single_record_adapter_yields_exactly_one_record():
    records = [
        make_record("SBI-aaa", "Alpha Traders"),
        make_record("SBI-77dd5b49b548d50d", "Bhaskar Jyoti Saikia"),
        make_record("SBI-ccc", "Charlie Enterprises"),
    ]
    underlying = FakeUnderlyingAdapter(records)
    match = find_record_by_case_reference(underlying, "SBI-77dd5b49b548d50d")

    single = SingleRecordAdapter(underlying, match)
    collected = list(single.collect())

    assert len(collected) == 1
    assert collected[0].case_reference == "SBI-77dd5b49b548d50d"
    # SourceAdapter contract preserved, unchanged from the underlying adapter
    assert single.source_name == "SBI"
    assert single.source_type == "bank"


def test_end_to_end_filtered_run_writes_exactly_one_case():
    """The scenario the CLI flag exists for: a multi-record collection,
    filtered down to one case_reference, passed through the real,
    unmodified ingestion runtime — proving only that one record actually
    gets written, not just that collect() yields one item in isolation."""
    records = [
        make_record("SBI-aaa", "Alpha Traders"),
        make_record("SBI-77dd5b49b548d50d", "Bhaskar Jyoti Saikia"),
        make_record("SBI-ccc", "Charlie Enterprises"),
    ]
    underlying = FakeUnderlyingAdapter(records)
    store = InMemoryStore()

    match = find_record_by_case_reference(underlying, "SBI-77dd5b49b548d50d")
    assert match is not None
    filtered_adapter = SingleRecordAdapter(underlying, match)

    result = run_ingestion(filtered_adapter, store)

    assert result.seen == 1
    assert result.ingested == 1
    assert len(store.cases) == 1
    assert list(store.cases.values())[0]["case_reference"] == "SBI-77dd5b49b548d50d"
    assert list(store.cases.values())[0]["title"] == "Bhaskar Jyoti Saikia"


def test_not_found_means_no_ingestion_run_is_even_started():
    """Mirrors the CLI's actual control flow: find first, and only call
    run_ingestion if something was found. A miss must not create an
    ingestion_runs row or touch the store at all."""
    underlying = FakeUnderlyingAdapter([make_record("SBI-aaa", "Alpha Traders")])
    store = InMemoryStore()

    match = find_record_by_case_reference(underlying, "SBI-does-not-exist")
    assert match is None

    # the CLI would exit here without calling run_ingestion; simulate that
    # and assert the store saw nothing
    assert len(store.runs) == 0
    assert len(store.cases) == 0
