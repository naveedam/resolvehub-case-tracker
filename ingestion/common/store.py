"""Storage abstraction used by the shared ingestion runtime.

The old SBI/Canara scripts called `supabase.table(...)` directly,
scattered through their ingest functions. The new runtime instead goes
through a small `Store` protocol with one explicit method per
operation. Two implementations exist:

  * SupabaseStore — thin wrapper over the real supabase-py client, used
    in production (ingestion/sbi/adapter.py, ingestion/canara/adapter.py).
  * InMemoryStore — a plain-Python test double used by
    ingestion/common/tests/, so adapter/runtime logic (idempotency,
    conflicting observations, event generation, entity-match handling)
    can be tested without a live database or network access.

Both implementations satisfy the same interface, so
`ingestion/common/runtime.py` never needs to know which one it's
talking to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol


def new_id() -> str:
    return str(uuid.uuid4())


# A page of 1000 case_ids in a single .in_("case_id", [...]) filter builds a
# GET request URL with ~1000 UUIDs (~37KB of query string) — large enough
# that PostgREST/the transport in front of it can reject it outright
# ("JSON could not be generated", 400) rather than reject individual rows.
# This is purely a request-size limit, unrelated to list_cases_page's own
# .range()-based pagination (two integers — no such limit applies there),
# so only the .in_()-based batch reads need chunking.
IN_FILTER_CHUNK_SIZE = 200


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class Store(Protocol):
    # sources / runs
    def get_or_create_source(self, name: str, full_name: str, source_type: str) -> str: ...
    def start_run(self, source_id: str) -> str: ...
    def finish_run(self, run_id: str, *, status: str, seen: int, ingested: int, skipped: int, failed: int, error_summary: str | None) -> None: ...

    # legacy tables (cases/parties/case_parties/documents/liabilities/assets)
    def find_case_id_by_reference(self, case_reference: str) -> str | None: ...
    def insert_case(self, case_row: dict) -> str: ...
    def get_or_create_party(self, full_name: str, party_type: str) -> str: ...
    def link_case_party(self, case_id: str, party_id: str, role: str) -> None: ...
    def insert_document(self, doc_row: dict) -> str: ...
    def insert_liability(self, liability_row: dict) -> str: ...
    def insert_asset(self, asset_row: dict) -> str: ...
    def find_liability_id_by_case(self, case_id: str) -> str | None: ...
    def find_asset_id_by_case(self, case_id: str) -> str | None: ...

    # evidence layer
    def find_current_observations(self, entity_type: str, entity_id: str, field_name: str) -> list[dict]: ...
    def insert_observation(self, obs_row: dict) -> str: ...
    def mark_superseded(self, observation_id: str, superseded_by: str) -> None: ...
    def set_current(self, observation_id: str, is_current: bool) -> None: ...
    def insert_case_event(self, event_row: dict) -> str: ...
    def find_identifier(self, entity_type: str, identifier_type: str, identifier_value: str) -> dict | None: ...
    def insert_identifier(self, identifier_row: dict) -> str: ...
    def insert_match_candidate(self, candidate_row: dict) -> str: ...

    # backfill — read legacy tables directly (paginated/batched; the
    # frontend's cases.ts fetchCases() bug taught this codebase why
    # every unbounded Supabase select must be paginated explicitly)
    def list_cases_page(self, from_idx: int, to_idx: int) -> list[dict]: ...
    def list_liabilities_for_cases(self, case_ids: list[str]) -> list[dict]: ...
    def list_assets_for_cases(self, case_ids: list[str]) -> list[dict]: ...
    def list_documents_for_cases(self, case_ids: list[str]) -> list[dict]: ...


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------
# In-memory test double
# ---------------------------------------------------------------------


@dataclass
class InMemoryStore:
    """A plain-Python stand-in for Supabase, used by the adapter/runtime
    test suite. Keeps just enough state to exercise idempotency, history
    and conflict-handling logic."""

    sources: dict[str, dict] = field(default_factory=dict)
    runs: dict[str, dict] = field(default_factory=dict)
    cases: dict[str, dict] = field(default_factory=dict)
    parties: dict[str, dict] = field(default_factory=dict)
    case_parties: list[dict] = field(default_factory=list)
    documents: dict[str, dict] = field(default_factory=dict)
    liabilities: dict[str, dict] = field(default_factory=dict)
    assets: dict[str, dict] = field(default_factory=dict)
    observations: dict[str, dict] = field(default_factory=dict)
    case_events: dict[str, dict] = field(default_factory=dict)
    identifiers: dict[str, dict] = field(default_factory=dict)
    match_candidates: dict[str, dict] = field(default_factory=dict)

    _party_by_name: dict[str, str] = field(default_factory=dict)
    _case_by_reference: dict[str, str] = field(default_factory=dict)

    # -- sources / runs --
    def get_or_create_source(self, name: str, full_name: str, source_type: str) -> str:
        for sid, s in self.sources.items():
            if s["name"] == name:
                return sid
        sid = new_id()
        self.sources[sid] = {"id": sid, "name": name, "full_name": full_name, "source_type": source_type}
        return sid

    def start_run(self, source_id: str) -> str:
        rid = new_id()
        self.runs[rid] = {
            "id": rid,
            "source_id": source_id,
            "status": "running",
            "records_seen": 0,
            "records_ingested": 0,
            "records_skipped": 0,
            "records_failed": 0,
            "started_at": utcnow(),
            "completed_at": None,
            "error_summary": None,
        }
        return rid

    def finish_run(self, run_id, *, status, seen, ingested, skipped, failed, error_summary):
        r = self.runs[run_id]
        r.update(
            status=status,
            records_seen=seen,
            records_ingested=ingested,
            records_skipped=skipped,
            records_failed=failed,
            error_summary=error_summary,
            completed_at=utcnow(),
        )

    # -- legacy tables --
    def find_case_id_by_reference(self, case_reference: str) -> str | None:
        return self._case_by_reference.get(case_reference)

    def insert_case(self, case_row: dict) -> str:
        cid = new_id()
        self.cases[cid] = {"id": cid, **case_row}
        self._case_by_reference[case_row["case_reference"]] = cid
        return cid

    def get_or_create_party(self, full_name: str, party_type: str) -> str:
        key = full_name.lower()
        if key in self._party_by_name:
            return self._party_by_name[key]
        pid = new_id()
        self.parties[pid] = {"id": pid, "full_name": full_name, "party_type": party_type}
        self._party_by_name[key] = pid
        return pid

    def link_case_party(self, case_id: str, party_id: str, role: str) -> None:
        self.case_parties.append({"case_id": case_id, "party_id": party_id, "role": role})

    def insert_document(self, doc_row: dict) -> str:
        did = new_id()
        self.documents[did] = {"id": did, **doc_row}
        return did

    def insert_liability(self, liability_row: dict) -> str:
        lid = new_id()
        self.liabilities[lid] = {"id": lid, **liability_row}
        return lid

    def insert_asset(self, asset_row: dict) -> str:
        aid = new_id()
        self.assets[aid] = {"id": aid, **asset_row}
        return aid

    def find_liability_id_by_case(self, case_id: str) -> str | None:
        # Phase 1 sources (SBI, Canara) create at most one liability row per
        # case, so "first match" is unambiguous today. A source that can
        # report multiple liabilities per case will need a real key
        # (e.g. account_number) before this can stay a single lookup.
        for lid, l in self.liabilities.items():
            if l["case_id"] == case_id:
                return lid
        return None

    def find_asset_id_by_case(self, case_id: str) -> str | None:
        for aid, a in self.assets.items():
            if a["case_id"] == case_id:
                return aid
        return None

    # -- evidence layer --
    def find_current_observations(self, entity_type: str, entity_id: str, field_name: str) -> list[dict]:
        return [
            o
            for o in self.observations.values()
            if o["entity_type"] == entity_type
            and o["entity_id"] == entity_id
            and o["field_name"] == field_name
            and o["is_current"]
        ]

    def insert_observation(self, obs_row: dict) -> str:
        oid = new_id()
        self.observations[oid] = {"id": oid, "is_current": True, "superseded_by": None, **obs_row}
        return oid

    def mark_superseded(self, observation_id: str, superseded_by: str) -> None:
        self.observations[observation_id]["superseded_by"] = superseded_by

    def set_current(self, observation_id: str, is_current: bool) -> None:
        self.observations[observation_id]["is_current"] = is_current

    def insert_case_event(self, event_row: dict) -> str:
        eid = new_id()
        self.case_events[eid] = {"id": eid, **event_row}
        return eid

    def find_identifier(self, entity_type: str, identifier_type: str, identifier_value: str) -> dict | None:
        for i in self.identifiers.values():
            if (
                i["entity_type"] == entity_type
                and i["identifier_type"] == identifier_type
                and i["identifier_value"] == identifier_value
            ):
                return i
        return None

    def insert_identifier(self, identifier_row: dict) -> str:
        iid = new_id()
        self.identifiers[iid] = {"id": iid, **identifier_row}
        return iid

    def insert_match_candidate(self, candidate_row: dict) -> str:
        cid = new_id()
        self.match_candidates[cid] = {"id": cid, **candidate_row}
        return cid

    # -- backfill reads --
    def list_cases_page(self, from_idx: int, to_idx: int) -> list[dict]:
        ordered = sorted(self.cases.values(), key=lambda c: c["id"])
        return ordered[from_idx : to_idx + 1]

    def list_liabilities_for_cases(self, case_ids: list[str]) -> list[dict]:
        ids = set(case_ids)
        return [l for l in self.liabilities.values() if l["case_id"] in ids]

    def list_assets_for_cases(self, case_ids: list[str]) -> list[dict]:
        ids = set(case_ids)
        return [a for a in self.assets.values() if a["case_id"] in ids]

    def list_documents_for_cases(self, case_ids: list[str]) -> list[dict]:
        ids = set(case_ids)
        return [d for d in self.documents.values() if d["case_id"] in ids]


# ---------------------------------------------------------------------
# Real Supabase-backed implementation
# ---------------------------------------------------------------------


class SupabaseStore:
    """Thin wrapper over supabase-py. Every method here is a single,
    explicit operation — no query building leaks into the runtime or the
    adapters. Retries connection errors the same way the original Canara
    scraper did (see `_execute`), since that's a real failure mode
    Canara's ingestion already hit in production."""

    def __init__(self, supabase_client, *, retries: int = 4, retry_delay: float = 2.0):
        self.sb = supabase_client
        self.retries = retries
        self.retry_delay = retry_delay

    def _execute(self, builder):
        import time

        last_exc = None
        for attempt in range(self.retries):
            try:
                return builder.execute()
            except Exception as e:  # noqa: BLE001 - deliberately broad, see Canara scraper precedent
                last_exc = e
                if attempt < self.retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        raise last_exc

    def get_or_create_source(self, name: str, full_name: str, source_type: str) -> str:
        existing = self._execute(self.sb.table("sources").select("id").eq("name", name))
        if existing.data:
            return existing.data[0]["id"]
        inserted = self._execute(
            self.sb.table("sources").insert({"name": name, "full_name": full_name, "source_type": source_type})
        )
        return inserted.data[0]["id"]

    def start_run(self, source_id: str) -> str:
        inserted = self._execute(
            self.sb.table("ingestion_runs").insert({"source_id": source_id, "status": "running"})
        )
        return inserted.data[0]["id"]

    def finish_run(self, run_id, *, status, seen, ingested, skipped, failed, error_summary):
        self._execute(
            self.sb.table("ingestion_runs")
            .update(
                {
                    "status": status,
                    "records_seen": seen,
                    "records_ingested": ingested,
                    "records_skipped": skipped,
                    "records_failed": failed,
                    "error_summary": error_summary,
                    "completed_at": utcnow().isoformat(),
                }
            )
            .eq("id", run_id)
        )

    def find_case_id_by_reference(self, case_reference: str) -> str | None:
        result = self._execute(
            self.sb.table("cases").select("id").eq("case_reference", case_reference).is_("deleted_at", "null")
        )
        return result.data[0]["id"] if result.data else None

    def insert_case(self, case_row: dict) -> str:
        inserted = self._execute(self.sb.table("cases").insert(case_row).select())
        return inserted.data[0]["id"]

    def get_or_create_party(self, full_name: str, party_type: str) -> str:
        existing = self._execute(
            self.sb.table("parties").select("id").ilike("full_name", full_name).is_("deleted_at", "null")
        )
        if existing.data:
            return existing.data[0]["id"]
        inserted = self._execute(self.sb.table("parties").insert({"full_name": full_name, "party_type": party_type}))
        return inserted.data[0]["id"]

    def link_case_party(self, case_id: str, party_id: str, role: str) -> None:
        self._execute(
            self.sb.table("case_parties").insert({"case_id": case_id, "party_id": party_id, "role": role})
        )

    def insert_document(self, doc_row: dict) -> str:
        inserted = self._execute(self.sb.table("documents").insert(doc_row))
        return inserted.data[0]["id"]

    def insert_liability(self, liability_row: dict) -> str:
        inserted = self._execute(self.sb.table("liabilities").insert(liability_row))
        return inserted.data[0]["id"]

    def insert_asset(self, asset_row: dict) -> str:
        inserted = self._execute(self.sb.table("assets").insert(asset_row))
        return inserted.data[0]["id"]

    def find_liability_id_by_case(self, case_id: str) -> str | None:
        result = self._execute(self.sb.table("liabilities").select("id").eq("case_id", case_id).limit(1))
        return result.data[0]["id"] if result.data else None

    def find_asset_id_by_case(self, case_id: str) -> str | None:
        result = self._execute(self.sb.table("assets").select("id").eq("case_id", case_id).limit(1))
        return result.data[0]["id"] if result.data else None

    def find_current_observations(self, entity_type: str, entity_id: str, field_name: str) -> list[dict]:
        result = self._execute(
            self.sb.table("field_observations")
            .select("*")
            .eq("entity_type", entity_type)
            .eq("entity_id", entity_id)
            .eq("field_name", field_name)
            .eq("is_current", True)
        )
        return result.data

    def insert_observation(self, obs_row: dict) -> str:
        inserted = self._execute(self.sb.table("field_observations").insert(obs_row))
        return inserted.data[0]["id"]

    def mark_superseded(self, observation_id: str, superseded_by: str) -> None:
        self._execute(
            self.sb.table("field_observations").update({"superseded_by": superseded_by}).eq("id", observation_id)
        )

    def set_current(self, observation_id: str, is_current: bool) -> None:
        self._execute(
            self.sb.table("field_observations").update({"is_current": is_current}).eq("id", observation_id)
        )

    def insert_case_event(self, event_row: dict) -> str:
        inserted = self._execute(self.sb.table("case_events").insert(event_row))
        return inserted.data[0]["id"]

    def find_identifier(self, entity_type: str, identifier_type: str, identifier_value: str) -> dict | None:
        result = self._execute(
            self.sb.table("entity_identifiers")
            .select("*")
            .eq("entity_type", entity_type)
            .eq("identifier_type", identifier_type)
            .eq("identifier_value", identifier_value)
        )
        return result.data[0] if result.data else None

    def insert_identifier(self, identifier_row: dict) -> str:
        inserted = self._execute(self.sb.table("entity_identifiers").insert(identifier_row))
        return inserted.data[0]["id"]

    def insert_match_candidate(self, candidate_row: dict) -> str:
        inserted = self._execute(self.sb.table("entity_match_candidates").insert(candidate_row))
        return inserted.data[0]["id"]

    # -- backfill reads --
    def list_cases_page(self, from_idx: int, to_idx: int) -> list[dict]:
        result = self._execute(
            self.sb.table("cases")
            .select("id, case_reference, estimated_liability, filing_date, status, next_hearing_date")
            .is_("deleted_at", "null")
            .order("id", desc=False)
            .range(from_idx, to_idx)
        )
        return result.data

    def list_liabilities_for_cases(self, case_ids: list[str]) -> list[dict]:
        rows: list[dict] = []
        for chunk in _chunked(case_ids, IN_FILTER_CHUNK_SIZE):
            result = self._execute(
                self.sb.table("liabilities")
                .select("id, case_id, loan_type, account_number, outstanding_amount")
                .in_("case_id", chunk)
                .is_("deleted_at", "null")
            )
            rows.extend(result.data)
        return rows

    def list_assets_for_cases(self, case_ids: list[str]) -> list[dict]:
        rows: list[dict] = []
        for chunk in _chunked(case_ids, IN_FILTER_CHUNK_SIZE):
            result = self._execute(
                self.sb.table("assets")
                .select("id, case_id, description, auction_date, auction_status")
                .in_("case_id", chunk)
                .is_("deleted_at", "null")
            )
            rows.extend(result.data)
        return rows

    def list_documents_for_cases(self, case_ids: list[str]) -> list[dict]:
        rows: list[dict] = []
        for chunk in _chunked(case_ids, IN_FILTER_CHUNK_SIZE):
            result = self._execute(
                self.sb.table("documents")
                .select("id, case_id")
                .in_("case_id", chunk)
                .is_("deleted_at", "null")
            )
            rows.extend(result.data)
        return rows
