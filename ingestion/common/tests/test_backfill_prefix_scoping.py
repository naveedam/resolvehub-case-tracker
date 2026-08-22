from __future__ import annotations

from ingestion.common.runtime import backfill_resolution_profiles
from ingestion.common.store import InMemoryStore

from .test_backfill import seed_legacy_case


def test_prefix_filter_processes_only_matching_cases():
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="SBI-aaa111")
    seed_legacy_case(store, case_reference="CANARA-bbb222")
    seed_legacy_case(store, case_reference="AXIS-ccc333")
    seed_legacy_case(store, case_reference="UNIONBANK-ddd444")

    summary = backfill_resolution_profiles(store, case_reference_prefixes=["AXIS-", "UNIONBANK-"])

    assert summary.cases_processed == 2
    assert summary.by_source == {"Axis": 1, "UnionBank": 1}


def test_prefix_filter_leaves_existing_profiles_completely_untouched():
    """The exact scenario this was built for: 11,419 SBI/Canara profiles
    must not be re-visited at all, not just left unmodified, when
    backfilling only the two new banks."""
    store = InMemoryStore()
    sbi_case_id = seed_legacy_case(store, case_reference="SBI-aaa111")
    canara_case_id = seed_legacy_case(store, case_reference="CANARA-bbb222")

    # first, a normal full backfill establishes the "existing 11,419 profiles"
    backfill_resolution_profiles(store)
    sbi_obs_before = {o["id"]: dict(o) for o in store.observations.values() if o["entity_id"] == sbi_case_id}
    canara_obs_before = {o["id"]: dict(o) for o in store.observations.values() if o["entity_id"] == canara_case_id}
    total_obs_before = len(store.observations)
    total_idents_before = len(store.identifiers)

    # now add the two new banks and run a PREFIX-SCOPED backfill
    seed_legacy_case(store, case_reference="AXIS-ccc333")
    seed_legacy_case(store, case_reference="UNIONBANK-ddd444")
    summary = backfill_resolution_profiles(store, case_reference_prefixes=["AXIS-", "UNIONBANK-"])

    assert summary.cases_processed == 2  # only the two new cases, not 4
    assert "SBI" not in summary.by_source
    assert "Canara" not in summary.by_source

    # every pre-existing SBI/Canara observation is byte-for-byte identical —
    # not re-written, not touched, not even superseded
    sbi_obs_after = {o["id"]: dict(o) for o in store.observations.values() if o["entity_id"] == sbi_case_id}
    canara_obs_after = {o["id"]: dict(o) for o in store.observations.values() if o["entity_id"] == canara_case_id}
    assert sbi_obs_after == sbi_obs_before
    assert canara_obs_after == canara_obs_before

    # only new rows were added, none removed or mutated in place
    assert len(store.observations) > total_obs_before
    assert len(store.identifiers) > total_idents_before


def test_axis_and_unionbank_sources_are_attributed_correctly():
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="AXIS-aaa")
    seed_legacy_case(store, case_reference="UNIONBANK-bbb")

    backfill_resolution_profiles(store, case_reference_prefixes=["AXIS-", "UNIONBANK-"])

    sources_by_name = {s["name"]: s for s in store.sources.values()}
    assert sources_by_name["Axis"]["full_name"] == "Axis Bank"
    assert sources_by_name["UnionBank"]["full_name"] == "Union Bank of India"


def test_multiple_prefixes_in_one_run_each_get_their_own_run_row():
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="AXIS-aaa")
    seed_legacy_case(store, case_reference="AXIS-bbb")
    seed_legacy_case(store, case_reference="UNIONBANK-ccc")

    backfill_resolution_profiles(store, case_reference_prefixes=["AXIS-", "UNIONBANK-"])

    runs_by_source_name = {}
    for run in store.runs.values():
        source_name = next(s["name"] for s in store.sources.values() if s["id"] == run["source_id"])
        runs_by_source_name[source_name] = run

    assert runs_by_source_name["Axis"]["records_ingested"] == 2
    assert runs_by_source_name["UnionBank"]["records_ingested"] == 1
    assert all(r["status"] == "success" for r in runs_by_source_name.values())


def test_unmatched_prefix_processes_nothing():
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="SBI-aaa")

    summary = backfill_resolution_profiles(store, case_reference_prefixes=["AXIS-"])

    assert summary.cases_processed == 0
    assert summary.by_source == {}
    assert len(store.observations) == 0


def test_no_prefix_argument_still_processes_everything_as_before():
    """Backward compatibility: omitting case_reference_prefixes must
    behave exactly as the original, unscoped backfill did."""
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="SBI-aaa")
    seed_legacy_case(store, case_reference="CANARA-bbb")
    seed_legacy_case(store, case_reference="AXIS-ccc")

    summary = backfill_resolution_profiles(store)

    assert summary.cases_processed == 3
    assert set(summary.by_source) == {"SBI", "Canara", "Axis"}
