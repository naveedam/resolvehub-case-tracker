"""Shared ingestion runtime.

This is the ONLY code that decides what happens to a NormalizedRecord.
Every adapter (SBI, Canara, future IBBI/NCLT/MCA) hands its records to
`run_ingestion()` here, which:

  1. Upserts the legacy case/party/document/liability/asset rows using
     the exact same case_reference dedup key and get-or-create-party
     logic the original scripts used — so existing behavior for the
     six production tables is unchanged.
  2. Writes typed field_observations for every fact the record carries,
     never overwriting a prior observation — a changed value becomes a
     new row, and `is_current` is recomputed via a transparent, documented
     precedence rule (see `_new_observation_wins`).
  3. Emits a case_events row when a field the app cares about (reserve
     price, auction date/status, possession status, liability amount)
     actually changes value.
  4. Records identifiers deterministically, and — if two different
     entities claim the same identifier — files an entity_match_candidate
     instead of silently merging them.
  5. Is resumable and idempotent: re-running the same source over the
     same data does not duplicate cases, parties, documents, or
     observations, and a failure on one record doesn't lose the run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

from ingestion.common.adapter import SourceAdapter
from ingestion.common.models import EVENT_TRIGGER_FIELDS, FieldObservation, Identifier, NormalizedRecord
from ingestion.common.store import DuplicateIdentifierError, Store


@dataclass
class IngestionRunResult:
    run_id: str
    status: str  # 'success' | 'partial' | 'failed'
    seen: int
    ingested: int
    skipped: int
    failed: int
    errors: list[str]


def run_ingestion(adapter: SourceAdapter, store: Store) -> IngestionRunResult:
    source_id = store.get_or_create_source(adapter.source_name, adapter.source_full_name, adapter.source_type)
    run_id = store.start_run(source_id)

    seen = ingested = skipped = failed = 0
    errors: list[str] = []

    try:
        records = adapter.collect()
    except Exception as e:  # adapter-level failure (e.g. site unreachable) — nothing was processed
        store.finish_run(run_id, status="failed", seen=0, ingested=0, skipped=0, failed=0, error_summary=str(e))
        return IngestionRunResult(run_id, "failed", 0, 0, 0, 0, [str(e)])

    for record in records:
        seen += 1
        try:
            outcome = _ingest_record(store, source_id, run_id, record, adapter.source_name)
            if outcome == "new":
                ingested += 1
            else:
                skipped += 1
        except Exception as e:  # one bad record must not lose the rest of the run
            failed += 1
            errors.append(f"{record.case_reference if hasattr(record, 'case_reference') else '?'}: {e}")

    if failed == 0:
        status = "success"
    elif ingested or skipped:
        status = "partial"
    else:
        status = "failed"

    store.finish_run(
        run_id,
        status=status,
        seen=seen,
        ingested=ingested,
        skipped=skipped,
        failed=failed,
        error_summary="; ".join(errors[:20]) if errors else None,
    )
    return IngestionRunResult(run_id, status, seen, ingested, skipped, failed, errors)


def _ingest_record(store: Store, source_id: str, run_id: str, record: NormalizedRecord, source_name: str) -> str:
    """Returns 'new' if this case didn't exist before this call, 'existing'
    otherwise. Either way, field reconciliation runs — an already-known
    case can still receive a changed reserve price, a newly available
    liability figure, etc. on a later run."""

    case_id = store.find_case_id_by_reference(record.case_reference)
    is_new = case_id is None

    if is_new:
        case_id = store.insert_case(
            {
                "case_reference": record.case_reference,
                "title": record.title,
                "case_type": record.case_type,
                "status": "active",
                "court_name": None,
                "next_hearing_date": None,
                "filing_date": record.filing_date.isoformat() if record.filing_date else None,
                "estimated_liability": _num(record.get("case", "estimated_liability")),
                "summary": record.summary,
                "metadata": {"source": source_name},
            }
        )

        lender_id = store.get_or_create_party(record.lender_name, record.lender_type)
        store.link_case_party(case_id, lender_id, "Lender")

        borrower_id = store.get_or_create_party(record.borrower_name, record.borrower_type)
        store.link_case_party(case_id, borrower_id, "Borrower")

        for guarantor_name, guarantor_type in record.guarantors:
            guarantor_id = store.get_or_create_party(guarantor_name, guarantor_type)
            store.link_case_party(case_id, guarantor_id, "Guarantor")

        for doc in record.documents:
            store.insert_document(
                {
                    "case_id": case_id,
                    "document_type": doc.document_type,
                    "document_name": doc.document_name,
                    "storage_path": doc.storage_path,
                    "processed": doc.processed,
                }
            )

        # seed the case_reference itself as a deterministic identifier —
        # useful even before CIN/IBBI/NCLT identifiers exist for this case
        _reconcile_identifier(
            store,
            entity_type="case",
            entity_id=case_id,
            ident=Identifier(entity_type="case", identifier_type="case_reference", identifier_value=record.case_reference),
            source_id=source_id,
        )
    else:
        lender_id = store.get_or_create_party(record.lender_name, record.lender_type)

    # --- liability: create on first sight of an amount, or later if this
    # case previously had none (progressive enrichment) ---
    outstanding_obs = record.get("liability", "outstanding_amount")
    liability_id = store.find_liability_id_by_case(case_id)
    if liability_id is None and outstanding_obs is not None:
        loan_type_obs = record.get("liability", "loan_type")
        account_obs = record.get("liability", "account_number")
        liability_id = store.insert_liability(
            {
                "case_id": case_id,
                "lender_id": lender_id,
                "loan_type": loan_type_obs.value_text if loan_type_obs else "Other",
                "account_number": account_obs.value_text if account_obs else None,
                "outstanding_amount": outstanding_obs.value_numeric,
                "currency_code": "INR",
                "secured": True,
                "remarks": f"Auto-ingested from {source_name}; verify against source document.",
            }
        )

    # --- asset: same progressive-enrichment approach ---
    description_obs = record.get("asset", "description")
    asset_id = store.find_asset_id_by_case(case_id)
    if asset_id is None and description_obs is not None:
        auction_date_obs = record.get("asset", "auction_date")
        auction_status_obs = record.get("asset", "auction_status")
        asset_id = store.insert_asset(
            {
                "case_id": case_id,
                "asset_type": record.asset_type or "Other",
                "description": description_obs.value_text,
                "auction_date": auction_date_obs.value_date.isoformat()
                if auction_date_obs and auction_date_obs.value_date
                else None,
                "auction_status": auction_status_obs.value_text if auction_status_obs else None,
            }
        )

    entity_ids = {"case": case_id, "liability": liability_id, "asset": asset_id}

    for obs in record.field_observations:
        entity_id = entity_ids.get(obs.entity_type)
        if entity_id is None:
            # e.g. a liability-scoped observation before any liability row
            # exists yet and this particular obs isn't the one that created it
            continue
        _reconcile_observation(store, entity_type=obs.entity_type, entity_id=entity_id, obs=obs, source_id=source_id, run_id=run_id, case_id=case_id)

    for ident in record.identifiers:
        target_entity_id = case_id if ident.entity_type == "case" else None
        if target_entity_id is None:
            continue  # Phase 1 only resolves case-level identifiers; party identifiers are future work
        _reconcile_identifier(store, entity_type=ident.entity_type, entity_id=target_entity_id, ident=ident, source_id=source_id)

    return "new" if is_new else "existing"


def _num(obs: FieldObservation | None) -> float | None:
    return obs.value_numeric if obs else None


def _new_observation_wins(prev_published_at: date | None, new_published_at: date | None) -> bool:
    """Phase 1 precedence rule for which observation is 'current' when two
    disagree: the observation with the more recent published_at wins.
    If neither (or both) have a published_at, the newer one — i.e. the one
    being processed now — wins, since ingestion always processes in real
    chronological order. This is intentionally simple and fully
    documented rather than a black box; a later phase can swap in
    source-trust weighting without changing the storage model."""
    if new_published_at is None and prev_published_at is None:
        return True
    if new_published_at is None:
        return False
    if prev_published_at is None:
        return True
    return new_published_at >= prev_published_at


def _to_date(value) -> date | None:
    """published_at round-trips through storage as an ISO string (that's
    exactly what a real Postgres/Supabase read returns too, so this keeps
    the in-memory test double and the real store behaving identically)."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _reconcile_observation(store: Store, *, entity_type: str, entity_id: str, obs: FieldObservation, source_id: str, run_id: str, case_id: str) -> None:
    current = store.find_current_observations(entity_type, entity_id, obs.field_name)
    prev = current[0] if current else None

    if prev is not None and prev["source_id"] == source_id and _same_value(prev, obs):
        return  # identical re-observation from the same source — no-op, keeps re-runs idempotent

    new_wins = _new_observation_wins(_to_date(prev["published_at"]) if prev else None, obs.published_at)

    new_id = store.insert_observation(
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_name": obs.field_name,
            "value_numeric": obs.value_numeric,
            "value_text": obs.value_text,
            "value_date": obs.value_date.isoformat() if obs.value_date else None,
            "value_jsonb": obs.value_jsonb,
            "unit": obs.unit,
            "source_id": source_id,
            "source_document_id": obs.source_document_id,
            "source_record_ref": obs.source_record_ref,
            "published_at": obs.published_at.isoformat() if obs.published_at else None,
            "confidence": obs.confidence,
            "is_current": new_wins,
            "ingestion_run_id": run_id,
        }
    )

    if prev is not None and new_wins:
        store.set_current(prev["id"], False)
        store.mark_superseded(prev["id"], new_id)

        value_changed = not _same_value(prev, obs)
        if value_changed and obs.field_name in EVENT_TRIGGER_FIELDS:
            store.insert_case_event(
                {
                    "case_id": case_id,
                    "event_type": EVENT_TRIGGER_FIELDS[obs.field_name],
                    "event_date": obs.published_at.isoformat() if obs.published_at else None,
                    "description": f"{obs.field_name} changed from {_display(prev)!r} to {obs.value!r}",
                    "source_id": source_id,
                    "field_observation_id": new_id,
                    "ingestion_run_id": run_id,
                }
            )


def _same_value(prev_row: dict, obs: FieldObservation) -> bool:
    if prev_row.get("value_numeric") is not None:
        return prev_row["value_numeric"] == obs.value_numeric
    if prev_row.get("value_text") is not None:
        return prev_row["value_text"] == obs.value_text
    if prev_row.get("value_date") is not None:
        return _to_date(prev_row["value_date"]) == obs.value_date
    if prev_row.get("value_jsonb") is not None:
        return prev_row["value_jsonb"] == obs.value_jsonb
    return obs.value is None


def _display(prev_row: dict):
    for key in ("value_numeric", "value_text", "value_date", "value_jsonb"):
        if prev_row.get(key) is not None:
            return prev_row[key]
    return None


def _reconcile_identifier(store: Store, *, entity_type: str, entity_id: str, ident: Identifier, source_id: str) -> None:
    existing = store.find_identifier(entity_type, ident.identifier_type, ident.identifier_value)
    if existing is not None:
        _resolve_identifier_conflict(store, entity_type=entity_type, entity_id=entity_id, ident=ident, source_id=source_id, existing=existing)
        return

    try:
        store.insert_identifier(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "identifier_type": ident.identifier_type,
                "identifier_value": ident.identifier_value,
                "source_id": source_id,
                "match_method": ident.match_method,
                "confidence": ident.confidence,
            }
        )
    except DuplicateIdentifierError:
        # The row already exists despite find_identifier not seeing it a
        # moment ago — most likely a network retry resent an insert that
        # had already succeeded server-side (a long-running backfill hit
        # exactly this in production: a transient timeout mid-response,
        # after the write had already landed). Re-resolve against
        # what's actually there now, exactly as if find_identifier had
        # seen it the first time — this is not a new kind of conflict,
        # just a delayed discovery of one.
        existing_after_race = store.find_identifier(entity_type, ident.identifier_type, ident.identifier_value)
        if existing_after_race is None:
            raise  # genuinely inconsistent state — don't silently swallow
        _resolve_identifier_conflict(store, entity_type=entity_type, entity_id=entity_id, ident=ident, source_id=source_id, existing=existing_after_race)


def _resolve_identifier_conflict(store: Store, *, entity_type: str, entity_id: str, ident: Identifier, source_id: str, existing: dict) -> None:
    if existing["entity_id"] == entity_id:
        return  # already recorded, possibly by a different source — fine
    store.insert_match_candidate(
        {
            "entity_type": entity_type,
            "entity_id_a": existing["entity_id"],
            "entity_id_b": entity_id,
            "match_method": ident.match_method,
            "confidence": ident.confidence,
            "evidence": {
                "identifier_type": ident.identifier_type,
                "identifier_value": ident.identifier_value,
                "conflicting_source_id": source_id,
            },
            "status": "pending",
        }
    )


# ---------------------------------------------------------------------
# Phase 1.5 — Resolution Profile backfill
#
# Reconstructs field_observations/entity_identifiers for cases that
# already existed BEFORE the evidence layer did — i.e. every case, since
# all ~11,400 were created by the pre-Phase-1 scrapers. Deliberately
# reuses _reconcile_observation/_reconcile_identifier (the exact same
# functions live ingestion uses) rather than re-implementing upsert
# logic, so idempotency, is_current precedence, and case_events
# generation all come for free and behave identically. Never creates,
# modifies, or deletes a case/liability/asset/party/document row — only
# adds evidence-layer rows alongside what already exists.
# ---------------------------------------------------------------------

BACKFILL_PAGE_SIZE = 1000

# Legacy columns don't carry their own type info the way a FieldObservation
# does — this is how we know which value_* to populate.
_LEGACY_NUMERIC_FIELDS = {"estimated_liability", "outstanding_amount"}
_LEGACY_DATE_FIELDS = {"filing_date", "next_hearing_date", "auction_date"}

_CASE_LEGACY_FIELDS = ("estimated_liability", "status", "filing_date", "next_hearing_date")
_LIABILITY_LEGACY_FIELDS = ("outstanding_amount", "loan_type", "account_number")
_ASSET_LEGACY_FIELDS = ("description", "auction_date", "auction_status")


@dataclass
class BackfillSummary:
    cases_processed: int
    observations_written: int
    identifier_reconciliations: int  # case_reference + any account refs seen; conflicts are safely filed as match candidates, not merged
    by_source: dict[str, int] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


def _infer_source_for_case_reference(case_reference: str) -> tuple[str, str, str]:
    """(name, full_name, source_type) for get_or_create_source, inferred
    from the case_reference prefix each adapter's make_case_reference()
    already stamps on every case it creates. Reuses the SAME source row
    live ingestion uses (get_or_create_source finds-or-creates by
    `name`) — these observations genuinely did come from these banks,
    just extracted by a scraper that predates (or, for AXIS/UNIONBANK,
    runs outside of) the evidence layer.

    NOTE for Axis/UnionBank: 'UnionBank'/'Union Bank of India' matches
    the source_name/source_name_full already committed in
    ingestion/union_bank/scraper.py, so a backfill run reuses that same
    sources row rather than creating a duplicate. Axis has no adapter
    committed to this repo at all (see chat context) — 'Axis'/'Axis
    Bank' is a reasonable default, but if Axis ingestion already
    registered a sources row under a different name out-of-band,
    confirm and adjust before running against production to avoid a
    duplicate source row."""
    if case_reference.startswith("SBI-"):
        return "SBI", "State Bank of India", "bank"
    if case_reference.startswith("CANARA-"):
        return "Canara", "Canara Bank", "bank"
    if case_reference.startswith("AXIS-"):
        return "Axis", "Axis Bank", "bank"
    if case_reference.startswith("UNIONBANK-"):
        return "UnionBank", "Union Bank of India", "bank"
    return "Legacy", "Legacy / unattributed import", "manual"


def _legacy_observation(entity_type: str, field_name: str, value, source_document_id: str | None) -> FieldObservation | None:
    kwargs: dict = {
        "entity_type": entity_type,
        "field_name": field_name,
        "confidence": "source_derived",  # genuinely bank-reported data, just backfilled late
        "source_document_id": source_document_id,
    }
    try:
        if field_name in _LEGACY_NUMERIC_FIELDS:
            if value is None:
                return None
            kwargs["value_numeric"] = float(value)
            kwargs["unit"] = "INR"
        elif field_name in _LEGACY_DATE_FIELDS:
            if not value:
                return None
            kwargs["value_date"] = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        else:
            text = str(value).strip() if value is not None else ""
            if not text:
                return None
            kwargs["value_text"] = text
        return FieldObservation(**kwargs)
    except (ValueError, TypeError):
        return None  # malformed legacy value — skip rather than crash the whole backfill


def backfill_resolution_profiles(
    store: Store,
    *,
    page_size: int = BACKFILL_PAGE_SIZE,
    progress_every: int = 500,
    case_reference_prefixes: list[str] | None = None,
) -> BackfillSummary:
    """case_reference_prefixes, when given, restricts this run to cases
    whose case_reference starts with one of the given prefixes (e.g.
    ["AXIS-", "UNIONBANK-"]) — every other existing case is not just
    left unmodified but never even read or re-visited. None (the
    default) processes every non-deleted case, exactly as before this
    parameter existed."""
    start = time.monotonic()
    cases_processed = 0
    observations_written = 0
    identifier_reconciliations = 0
    by_source: dict[str, int] = {}
    source_ids: dict[str, str] = {}
    run_ids: dict[str, str] = {}
    run_counts: dict[str, int] = {}

    prefixes = case_reference_prefixes or [None]  # None -> one unfiltered pass over everything

    for prefix in prefixes:
        from_idx = 0
        while True:
            page = store.list_cases_page(from_idx, from_idx + page_size - 1, case_reference_prefix=prefix)
            if not page:
                break

            case_ids = [c["id"] for c in page]
            liabilities_by_case: dict[str, list[dict]] = {}
            for liability in store.list_liabilities_for_cases(case_ids):
                liabilities_by_case.setdefault(liability["case_id"], []).append(liability)
            assets_by_case: dict[str, list[dict]] = {}
            for asset in store.list_assets_for_cases(case_ids):
                assets_by_case.setdefault(asset["case_id"], []).append(asset)
            documents_by_case: dict[str, list[dict]] = {}
            for doc in store.list_documents_for_cases(case_ids):
                documents_by_case.setdefault(doc["case_id"], []).append(doc)

            for case in page:
                case_id = case["id"]
                case_reference = case["case_reference"]
                name, full_name, source_type = _infer_source_for_case_reference(case_reference)

                if name not in source_ids:
                    source_ids[name] = store.get_or_create_source(name, full_name, source_type)
                    run_ids[name] = store.start_run(source_ids[name])
                    run_counts[name] = 0
                source_id = source_ids[name]
                run_id = run_ids[name]

                documents = documents_by_case.get(case_id, [])
                source_document_id = documents[0]["id"] if documents else None

                for field_name in _CASE_LEGACY_FIELDS:
                    obs = _legacy_observation("case", field_name, case.get(field_name), source_document_id)
                    if obs is None:
                        continue
                    _reconcile_observation(
                        store, entity_type="case", entity_id=case_id, obs=obs,
                        source_id=source_id, run_id=run_id, case_id=case_id,
                    )
                    observations_written += 1

                for liability in liabilities_by_case.get(case_id, []):
                    for field_name in _LIABILITY_LEGACY_FIELDS:
                        obs = _legacy_observation("liability", field_name, liability.get(field_name), source_document_id)
                        if obs is None:
                            continue
                        _reconcile_observation(
                            store, entity_type="liability", entity_id=liability["id"], obs=obs,
                            source_id=source_id, run_id=run_id, case_id=case_id,
                        )
                        observations_written += 1
                    if liability.get("account_number"):
                        _reconcile_identifier(
                            store, entity_type="case", entity_id=case_id,
                            ident=Identifier(
                                entity_type="case", identifier_type="bank_account_ref",
                                identifier_value=liability["account_number"],
                            ),
                            source_id=source_id,
                        )
                        identifier_reconciliations += 1

                for asset in assets_by_case.get(case_id, []):
                    for field_name in _ASSET_LEGACY_FIELDS:
                        obs = _legacy_observation("asset", field_name, asset.get(field_name), source_document_id)
                        if obs is None:
                            continue
                        _reconcile_observation(
                            store, entity_type="asset", entity_id=asset["id"], obs=obs,
                            source_id=source_id, run_id=run_id, case_id=case_id,
                        )
                        observations_written += 1

                _reconcile_identifier(
                    store, entity_type="case", entity_id=case_id,
                    ident=Identifier(entity_type="case", identifier_type="case_reference", identifier_value=case_reference),
                    source_id=source_id,
                )
                identifier_reconciliations += 1

                cases_processed += 1
                run_counts[name] += 1
                by_source[name] = by_source.get(name, 0) + 1

                if cases_processed % progress_every == 0:
                    elapsed = time.monotonic() - start
                    print(
                        f"  ...{cases_processed} cases processed "
                        f"({observations_written} observations, {identifier_reconciliations} identifier "
                        f"reconciliations so far, {elapsed:.0f}s elapsed)"
                    )

            if len(page) < page_size:
                break
            from_idx += page_size

    for name, run_id in run_ids.items():
        store.finish_run(
            run_id, status="success", seen=run_counts[name], ingested=run_counts[name], skipped=0, failed=0,
            error_summary=None,
        )

    return BackfillSummary(
        cases_processed=cases_processed,
        observations_written=observations_written,
        identifier_reconciliations=identifier_reconciliations,
        by_source=by_source,
        elapsed_seconds=time.monotonic() - start,
    )


if __name__ == "__main__":
    import argparse
    import os

    from dotenv import load_dotenv
    from supabase import create_client

    from ingestion.common.store import SupabaseStore

    parser = argparse.ArgumentParser(description="Shared ResolveHub ingestion runtime.")
    parser.add_argument(
        "--backfill-resolution-profiles",
        action="store_true",
        help=(
            "Reconstruct field_observations/entity_identifiers for every "
            "non-deleted case already in Supabase, from its existing "
            "cases/liabilities/assets/documents columns. Never creates, "
            "modifies, or deletes a case/liability/asset/party/document "
            "row. Safe to re-run — idempotent, same as live ingestion."
        ),
    )
    parser.add_argument(
        "--case-reference-prefix",
        action="append",
        dest="case_reference_prefixes",
        metavar="PREFIX",
        help=(
            "Restrict the backfill to cases whose case_reference starts "
            "with this prefix (e.g. AXIS-, UNIONBANK-). Repeatable — "
            "pass it multiple times to cover several prefixes in one "
            "run. Every other existing case is left completely "
            "untouched, not just unmodified. Omit to process every "
            "non-deleted case, exactly as before this flag existed."
        ),
    )
    args = parser.parse_args()

    if not args.backfill_resolution_profiles:
        parser.print_help()
        raise SystemExit(0)

    load_dotenv()
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    store = SupabaseStore(client)

    if args.case_reference_prefixes:
        print(f"Starting Resolution Profile backfill for prefixes: {args.case_reference_prefixes} ...")
    else:
        print("Starting Resolution Profile backfill for all non-deleted cases...")
    summary = backfill_resolution_profiles(store, case_reference_prefixes=args.case_reference_prefixes)

    print("\nBackfill complete.")
    print(f"  cases processed:            {summary.cases_processed}")
    print(f"  observations written:       {summary.observations_written}")
    print(f"  identifier reconciliations: {summary.identifier_reconciliations}")
    print(f"  by source:                  {summary.by_source}")
    print(f"  elapsed:                    {summary.elapsed_seconds:.0f}s")
