from __future__ import annotations

from ingestion.common.runtime import backfill_resolution_profiles
from ingestion.common.store import InMemoryStore, new_id


def seed_legacy_case(
    store: InMemoryStore,
    *,
    case_reference: str,
    title: str = "Test Borrower",
    estimated_liability: float | None = 1_500_000,
    filing_date: str | None = "2026-01-15",
    status: str | None = "active",
    liability_account_number: str | None = "ACC123",
    asset_description: str | None = "3BHK flat",
    with_document: bool = True,
) -> str:
    """Mirrors what a pre-Phase-1 scraper run actually left behind:
    case/liability/asset/document rows, and NOTHING in the evidence
    layer — exactly the state backfill is meant to repair."""
    case_id = new_id()
    store.cases[case_id] = {
        "id": case_id,
        "case_reference": case_reference,
        "title": title,
        "estimated_liability": estimated_liability,
        "filing_date": filing_date,
        "status": status,
        "next_hearing_date": None,
    }
    if liability_account_number is not None:
        liability_id = new_id()
        store.liabilities[liability_id] = {
            "id": liability_id,
            "case_id": case_id,
            "loan_type": "Business Loan",
            "account_number": liability_account_number,
            "outstanding_amount": estimated_liability,
        }
    if asset_description is not None:
        asset_id = new_id()
        store.assets[asset_id] = {
            "id": asset_id,
            "case_id": case_id,
            "description": asset_description,
            "auction_date": None,
            "auction_status": None,
        }
    if with_document:
        doc_id = new_id()
        store.documents[doc_id] = {"id": doc_id, "case_id": case_id}
    return case_id


def test_backfill_populates_case_liability_and_asset_observations():
    store = InMemoryStore()
    case_id = seed_legacy_case(store, case_reference="SBI-aaa111")

    summary = backfill_resolution_profiles(store)

    assert summary.cases_processed == 1
    assert summary.by_source == {"SBI": 1}

    case_obs = [o for o in store.observations.values() if o["entity_type"] == "case" and o["entity_id"] == case_id]
    field_names = {o["field_name"] for o in case_obs}
    assert "estimated_liability" in field_names
    assert "filing_date" in field_names
    assert "status" in field_names
    assert all(o["is_current"] for o in case_obs)

    liability_obs = [o for o in store.observations.values() if o["entity_type"] == "liability"]
    assert {"outstanding_amount", "loan_type", "account_number"} <= {o["field_name"] for o in liability_obs}

    asset_obs = [o for o in store.observations.values() if o["entity_type"] == "asset"]
    assert any(o["field_name"] == "description" and o["value_text"] == "3BHK flat" for o in asset_obs)


def test_backfill_never_creates_or_modifies_legacy_rows():
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="SBI-bbb222")
    cases_before = dict(store.cases)
    liabilities_before = dict(store.liabilities)
    assets_before = dict(store.assets)

    backfill_resolution_profiles(store)

    assert store.cases == cases_before
    assert store.liabilities == liabilities_before
    assert store.assets == assets_before


def test_backfill_is_idempotent():
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="SBI-ccc333")

    first = backfill_resolution_profiles(store)
    obs_count_after_first = len(store.observations)
    ident_count_after_first = len(store.identifiers)

    second = backfill_resolution_profiles(store)

    assert second.cases_processed == first.cases_processed  # still visits every case
    assert len(store.observations) == obs_count_after_first  # but writes nothing new
    assert len(store.identifiers) == ident_count_after_first


def test_source_inferred_from_case_reference_prefix():
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="SBI-aaa")
    seed_legacy_case(store, case_reference="CANARA-bbb")
    seed_legacy_case(store, case_reference="MANUAL-ccc")

    summary = backfill_resolution_profiles(store)

    assert summary.by_source == {"SBI": 1, "Canara": 1, "Legacy": 1}
    source_names = {s["name"] for s in store.sources.values()}
    assert {"SBI", "Canara", "Legacy"} <= source_names


def test_case_reference_identifier_is_seeded_for_every_case():
    store = InMemoryStore()
    case_id = seed_legacy_case(store, case_reference="SBI-ddd444", liability_account_number=None)

    backfill_resolution_profiles(store)

    ref_idents = [
        i for i in store.identifiers.values()
        if i["identifier_type"] == "case_reference" and i["identifier_value"] == "SBI-ddd444"
    ]
    assert len(ref_idents) == 1
    assert ref_idents[0]["entity_id"] == case_id


def test_duplicate_account_number_across_cases_becomes_a_match_candidate_not_a_merge():
    """Exactly the real scenario this session already found in
    production (three separate 'Bhaskar Jyoti Saikia' case rows) — if
    two legacy cases happen to share a liability account_number, that
    must surface for review, never silently merge."""
    store = InMemoryStore()
    seed_legacy_case(store, case_reference="SBI-eee555", liability_account_number="SHARED-ACC")
    seed_legacy_case(store, case_reference="SBI-fff666", liability_account_number="SHARED-ACC")

    backfill_resolution_profiles(store)

    account_idents = [i for i in store.identifiers.values() if i["identifier_value"] == "SHARED-ACC"]
    assert len(account_idents) == 1  # only the first case claims it
    assert len(store.match_candidates) == 1  # the second is flagged, not merged


def test_observations_link_to_the_case_existing_document_when_one_exists():
    store = InMemoryStore()
    case_id = seed_legacy_case(store, case_reference="SBI-ggg777", with_document=True)
    doc_id = next(d["id"] for d in store.documents.values() if d["case_id"] == case_id)

    backfill_resolution_profiles(store)

    case_obs = [o for o in store.observations.values() if o["entity_type"] == "case" and o["entity_id"] == case_id]
    assert all(o["source_document_id"] == doc_id for o in case_obs)


def test_missing_document_leaves_source_document_id_unset():
    store = InMemoryStore()
    case_id = seed_legacy_case(store, case_reference="SBI-hhh888", with_document=False)

    backfill_resolution_profiles(store)

    case_obs = [o for o in store.observations.values() if o["entity_type"] == "case" and o["entity_id"] == case_id]
    assert all(o["source_document_id"] is None for o in case_obs)


def test_pagination_visits_every_case_across_multiple_pages():
    store = InMemoryStore()
    for i in range(5):
        seed_legacy_case(store, case_reference=f"SBI-page-{i:03d}")

    summary = backfill_resolution_profiles(store, page_size=2, progress_every=500)

    assert summary.cases_processed == 5
    assert summary.by_source == {"SBI": 5}


def test_progress_is_printed_at_the_configured_interval(capsys):
    store = InMemoryStore()
    for i in range(3):
        seed_legacy_case(store, case_reference=f"SBI-progress-{i:03d}")

    backfill_resolution_profiles(store, progress_every=2)

    out = capsys.readouterr().out
    assert "2 cases processed" in out
    assert "3 cases processed" not in out  # only fires on the configured multiple, not at the very end


def test_null_and_placeholder_legacy_values_are_skipped_not_written_as_garbage():
    store = InMemoryStore()
    case_id = seed_legacy_case(
        store,
        case_reference="SBI-iii999",
        estimated_liability=None,
        filing_date=None,
        status=None,
        liability_account_number=None,
        asset_description=None,
    )

    summary = backfill_resolution_profiles(store)

    case_obs = [o for o in store.observations.values() if o["entity_type"] == "case" and o["entity_id"] == case_id]
    assert case_obs == []  # nothing to report, and nothing fabricated
    assert summary.observations_written == 0
    # the case_reference identifier is still seeded regardless — that's
    # not conditional on there being any observations
    assert any(
        i["identifier_type"] == "case_reference" and i["entity_id"] == case_id for i in store.identifiers.values()
    )
