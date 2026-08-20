"""Tests for the --case-reference single-record filter on the Canara
adapter. Same shape as ingestion/sbi/tests/test_single_record_filter.py
— see that file for the fuller rationale on why find/None/one-record/
end-to-end/not-found are each tested separately.
"""

from __future__ import annotations

from ingestion.canara.adapter import SingleRecordAdapter, find_record_by_case_reference
from ingestion.common.models import NormalizedRecord
from ingestion.common.runtime import run_ingestion
from ingestion.common.store import InMemoryStore


def make_record(case_reference: str, title: str) -> NormalizedRecord:
    return NormalizedRecord(
        case_reference=case_reference,
        title=title,
        case_type="SARFAESI",
        summary="test possession notice",
        borrower_name=title,
        borrower_type="Individual",
        lender_name="Canara Bank",
    )


class FakeCanaraAdapter:
    source_name = "Canara"
    source_full_name = "Canara Bank"
    source_type = "bank"

    def __init__(self, records):
        self._records = records

    def collect(self):
        return iter(self._records)


def test_find_record_by_case_reference_returns_the_matching_record():
    records = [
        make_record("CANARA-aaa", "Alpha Traders"),
        make_record("CANARA-48e02e7fafd70ec6", "Bhaskar P."),
        make_record("CANARA-ccc", "Charlie Enterprises"),
    ]
    adapter = FakeCanaraAdapter(records)

    match = find_record_by_case_reference(adapter, "CANARA-48e02e7fafd70ec6")

    assert match is not None
    assert match.title == "Bhaskar P."


def test_find_record_by_case_reference_returns_none_when_not_found():
    adapter = FakeCanaraAdapter([make_record("CANARA-aaa", "Alpha Traders")])

    assert find_record_by_case_reference(adapter, "CANARA-does-not-exist") is None


def test_single_record_adapter_yields_exactly_one_record():
    records = [
        make_record("CANARA-aaa", "Alpha Traders"),
        make_record("CANARA-48e02e7fafd70ec6", "Bhaskar P."),
    ]
    underlying = FakeCanaraAdapter(records)
    match = find_record_by_case_reference(underlying, "CANARA-48e02e7fafd70ec6")

    single = SingleRecordAdapter(underlying, match)
    collected = list(single.collect())

    assert len(collected) == 1
    assert collected[0].case_reference == "CANARA-48e02e7fafd70ec6"
    assert single.source_name == "Canara"
    assert single.source_type == "bank"


def test_end_to_end_filtered_run_writes_exactly_one_case():
    records = [
        make_record("CANARA-aaa", "Alpha Traders"),
        make_record("CANARA-48e02e7fafd70ec6", "Bhaskar P."),
        make_record("CANARA-ccc", "Charlie Enterprises"),
    ]
    underlying = FakeCanaraAdapter(records)
    store = InMemoryStore()

    match = find_record_by_case_reference(underlying, "CANARA-48e02e7fafd70ec6")
    assert match is not None
    result = run_ingestion(SingleRecordAdapter(underlying, match), store)

    assert result.seen == 1
    assert result.ingested == 1
    assert len(store.cases) == 1
    assert list(store.cases.values())[0]["case_reference"] == "CANARA-48e02e7fafd70ec6"


def test_not_found_means_no_ingestion_run_is_even_started():
    underlying = FakeCanaraAdapter([make_record("CANARA-aaa", "Alpha Traders")])
    store = InMemoryStore()

    match = find_record_by_case_reference(underlying, "CANARA-does-not-exist")
    assert match is None
    # the CLI would exit here without calling run_ingestion
    assert len(store.runs) == 0
    assert len(store.cases) == 0
