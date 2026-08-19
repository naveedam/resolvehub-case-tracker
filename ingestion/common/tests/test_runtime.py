from __future__ import annotations

from datetime import date

import pytest

from ingestion.common.models import FieldObservation, Identifier, NormalizedRecord
from ingestion.common.runtime import run_ingestion
from ingestion.common.store import InMemoryStore


class FakeAdapter:
    source_name = "TEST"
    source_full_name = "Test Source"
    source_type = "bank"

    def __init__(self, records):
        self._records = records

    def collect(self):
        return list(self._records)


class RaisingAdapter:
    source_name = "TEST"
    source_full_name = "Test Source"
    source_type = "bank"

    def collect(self):
        raise ConnectionError("site unreachable")


def make_record(case_reference="CASE-1", *, amount=None, npa_date=None, description=None, published_at=None, borrower="Jane Doe"):
    obs = []
    if amount is not None:
        obs.append(FieldObservation(entity_type="case", field_name="estimated_liability", value_numeric=amount, unit="INR", published_at=published_at))
        obs.append(FieldObservation(entity_type="liability", field_name="outstanding_amount", value_numeric=amount, unit="INR", published_at=published_at))
    if description is not None:
        obs.append(FieldObservation(entity_type="asset", field_name="description", value_text=description, published_at=published_at))
    return NormalizedRecord(
        case_reference=case_reference,
        title=borrower,
        case_type="SARFAESI",
        summary="test notice",
        borrower_name=borrower,
        borrower_type="Individual",
        lender_name="Test Bank",
        field_observations=obs,
    )


def test_new_case_is_ingested_and_creates_evidence():
    store = InMemoryStore()
    result = run_ingestion(FakeAdapter([make_record(amount=1_500_000)]), store)

    assert result.status == "success"
    assert result.ingested == 1
    assert result.skipped == 0
    assert len(store.cases) == 1
    assert len(store.liabilities) == 1
    # both a case-level and a liability-level observation were recorded
    assert len(store.observations) == 2
    assert all(o["is_current"] for o in store.observations.values())


def test_rerunning_same_record_is_idempotent():
    store = InMemoryStore()
    record = make_record(amount=1_500_000, published_at=date(2026, 1, 1))

    run_ingestion(FakeAdapter([record]), store)
    result2 = run_ingestion(FakeAdapter([record]), store)

    assert result2.ingested == 0
    assert result2.skipped == 1
    assert len(store.cases) == 1  # no duplicate case
    assert len(store.observations) == 2  # no duplicate observations — same source, same value, no-op
    assert len(store.case_parties) == 2  # lender + borrower, not re-linked a second time


def test_conflicting_values_are_preserved_as_history_and_produce_an_event():
    store = InMemoryStore()
    first = make_record(amount=15_000_000, published_at=date(2026, 1, 1))
    run_ingestion(FakeAdapter([first]), store)

    second = make_record(amount=13_500_000, published_at=date(2026, 3, 1))
    run_ingestion(FakeAdapter([second]), store)

    # both observations survive — nothing was overwritten in place
    case_amount_obs = [o for o in store.observations.values() if o["entity_type"] == "case" and o["field_name"] == "estimated_liability"]
    assert len(case_amount_obs) == 2
    values = {o["value_numeric"] for o in case_amount_obs}
    assert values == {15_000_000, 13_500_000}

    current = [o for o in case_amount_obs if o["is_current"]]
    assert len(current) == 1
    assert current[0]["value_numeric"] == 13_500_000  # later published_at wins

    old = [o for o in case_amount_obs if not o["is_current"]][0]
    assert old["superseded_by"] == current[0]["id"]

    # a reserve/liability-amount change is a tracked event, not a silent overwrite
    events = [e for e in store.case_events.values() if e["event_type"] == "liability_amount_change"]
    assert len(events) == 1


def test_out_of_order_publication_does_not_overwrite_a_newer_value():
    store = InMemoryStore()
    run_ingestion(FakeAdapter([make_record(amount=13_500_000, published_at=date(2026, 3, 1))]), store)
    # a late-arriving report for an OLDER date shouldn't become "current"
    run_ingestion(FakeAdapter([make_record(amount=15_000_000, published_at=date(2026, 1, 1))]), store)

    case_amount_obs = [o for o in store.observations.values() if o["entity_type"] == "case" and o["field_name"] == "estimated_liability"]
    assert len(case_amount_obs) == 2
    current = [o for o in case_amount_obs if o["is_current"]][0]
    assert current["value_numeric"] == 13_500_000


def test_progressive_enrichment_adds_asset_on_a_later_run():
    store = InMemoryStore()
    run_ingestion(FakeAdapter([make_record(amount=1_000_000)]), store)
    assert len(store.assets) == 0

    run_ingestion(FakeAdapter([make_record(amount=1_000_000, description="3BHK flat, Sector 12")]), store)
    assert len(store.assets) == 1
    assert list(store.assets.values())[0]["description"] == "3BHK flat, Sector 12"


def test_duplicate_identifier_across_entities_is_flagged_not_merged():
    store = InMemoryStore()
    record_a = make_record("CASE-A", amount=1_000_000, borrower="Alpha Traders")
    record_a.identifiers = [Identifier(entity_type="case", identifier_type="bank_account_ref", identifier_value="ACC123")]
    record_b = make_record("CASE-B", amount=2_000_000, borrower="Beta Traders")
    record_b.identifiers = [Identifier(entity_type="case", identifier_type="bank_account_ref", identifier_value="ACC123")]

    run_ingestion(FakeAdapter([record_a]), store)
    run_ingestion(FakeAdapter([record_b]), store)

    # every case also gets an auto-seeded case_reference identifier; only
    # look at the one both records actually compete over
    account_ref_identifiers = [i for i in store.identifiers.values() if i["identifier_type"] == "bank_account_ref"]
    assert len(account_ref_identifiers) == 1  # only the first claim was recorded as authoritative
    assert len(store.match_candidates) == 1  # the conflict was filed for review, not silently resolved
    candidate = list(store.match_candidates.values())[0]
    assert candidate["status"] == "pending"
    assert {candidate["entity_id_a"], candidate["entity_id_b"]} == {
        store.find_case_id_by_reference("CASE-A"),
        store.find_case_id_by_reference("CASE-B"),
    }


def test_one_bad_record_does_not_lose_the_rest_of_the_run():
    store = InMemoryStore()

    class ExplodingRecord:
        case_reference = "BOOM"

        def __getattr__(self, item):
            raise RuntimeError("simulated extraction failure")

    good = make_record("CASE-GOOD", amount=1_000_000)
    result = run_ingestion(FakeAdapter([ExplodingRecord(), good]), store)

    assert result.status == "partial"
    assert result.failed == 1
    assert result.ingested == 1
    assert len(store.cases) == 1


def test_adapter_level_failure_marks_whole_run_failed():
    store = InMemoryStore()
    result = run_ingestion(RaisingAdapter(), store)

    assert result.status == "failed"
    assert result.seen == 0
    assert len(store.cases) == 0
    run_row = store.runs[result.run_id]
    assert run_row["status"] == "failed"
