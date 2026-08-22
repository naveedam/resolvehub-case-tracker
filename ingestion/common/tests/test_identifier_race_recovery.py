"""Regression test for a real production failure: a long-running
backfill (Axis/UnionBank, ~24 minutes, 2500+ cases) crashed with
postgrest.exceptions.APIError: duplicate key value violates unique
constraint "entity_identifiers_entity_type_identifier_type_identifier_v_key"

Root cause: Store._execute()'s retry wrapper retries ANY exception,
including one raised when an INSERT actually succeeded server-side but
the client never received the response (a transient timeout during a
long-running session). The retry then resent the same INSERT, which
now legitimately violates the unique constraint — and since that's
also an exception, every remaining retry hit the same error until the
whole run crashed.

InMemoryStore previously had NO uniqueness enforcement on identifiers
at all, so this exact bug class couldn't have been caught by the
existing suite — fixed as part of this regression test.
"""

from __future__ import annotations

import pytest

from ingestion.common.models import Identifier
from ingestion.common.runtime import _reconcile_identifier
from ingestion.common.store import DuplicateIdentifierError, InMemoryStore, new_id


class OneShotRaceStore(InMemoryStore):
    """find_identifier misses on the FIRST lookup for a given key —
    simulating the production race window (a prior insert already
    committed server-side but wasn't visible/acknowledged in time yet)
    — then behaves normally on every subsequent lookup for that same
    key, since a fresh query moments later would correctly see the row.
    Missing forever (never recovering) would defeat the point of
    testing recovery at all."""

    def __init__(self):
        super().__init__()
        self._missed_once: set[tuple] = set()

    def find_identifier(self, entity_type, identifier_type, identifier_value):
        key = (entity_type, identifier_type, identifier_value)
        if key not in self._missed_once:
            self._missed_once.add(key)
            return None
        return super().find_identifier(entity_type, identifier_type, identifier_value)


def test_in_memory_store_enforces_the_same_unique_constraint_as_production():
    store = InMemoryStore()
    store.insert_identifier(
        {
            "entity_type": "case", "entity_id": "case-a", "identifier_type": "case_reference",
            "identifier_value": "AXIS-aaa", "source_id": "src-1", "match_method": "deterministic", "confidence": None,
        }
    )
    with pytest.raises(DuplicateIdentifierError):
        store.insert_identifier(
            {
                "entity_type": "case", "entity_id": "case-a", "identifier_type": "case_reference",
                "identifier_value": "AXIS-aaa", "source_id": "src-1", "match_method": "deterministic", "confidence": None,
            }
        )


def test_retried_insert_of_the_same_identifier_by_the_same_case_is_recovered_as_a_no_op():
    """The actual production scenario: find_identifier misses the row
    once (the race window), so _reconcile_identifier proceeds to
    insert_identifier — but by then the row already exists (from a
    prior, successful-but-unacknowledged attempt), so it genuinely
    raises a duplicate-key error. Must recover to a no-op, not crash —
    the row is already correct, just claimed by the same case again."""
    store = OneShotRaceStore()
    case_id = new_id()
    source_id = store.get_or_create_source("Axis", "Axis Bank", "bank")
    ident = Identifier(entity_type="case", identifier_type="case_reference", identifier_value="AXIS-ed96c29f942d978f")

    # first reconciliation: find_identifier misses (nothing exists yet
    # regardless), insert_identifier succeeds normally
    _reconcile_identifier(store, entity_type="case", entity_id=case_id, ident=ident, source_id=source_id)
    assert len(store.identifiers) == 1

    # a hand-crafted second race for the SAME key: force find_identifier
    # to miss one more time (as it did in production, moments before the
    # row became visible), so insert_identifier hits the real
    # constraint. Must not crash the whole backfill.
    store._missed_once.discard(("case", "case_reference", "AXIS-ed96c29f942d978f"))
    _reconcile_identifier(store, entity_type="case", entity_id=case_id, ident=ident, source_id=source_id)

    assert len(store.identifiers) == 1  # still exactly one row — no crash, no duplicate
    assert len(store.match_candidates) == 0  # same entity claimed it both times — not a real conflict


def test_duplicate_identifier_error_from_a_different_entity_still_becomes_a_match_candidate():
    """The DuplicateIdentifierError recovery path must not accidentally
    suppress a REAL conflict — a different entity claiming the same
    identifier still has to be flagged, not silently treated as fine.
    Uses the normal (non-racy) path, since a genuine conflict is
    correctly caught by find_identifier without needing a race at all —
    this just confirms the pre-existing conflict behavior wasn't
    changed by the new recovery logic."""
    store = InMemoryStore()
    case_a = new_id()
    case_b = new_id()
    source_id = store.get_or_create_source("Axis", "Axis Bank", "bank")
    ident = Identifier(entity_type="case", identifier_type="bank_account_ref", identifier_value="SHARED-ACC")

    _reconcile_identifier(store, entity_type="case", entity_id=case_a, ident=ident, source_id=source_id)
    _reconcile_identifier(store, entity_type="case", entity_id=case_b, ident=ident, source_id=source_id)

    assert len(store.identifiers) == 1  # only case_a's claim is authoritative
    assert len(store.match_candidates) == 1  # case_b's conflicting claim was flagged, not lost
    candidate = list(store.match_candidates.values())[0]
    assert {candidate["entity_id_a"], candidate["entity_id_b"]} == {case_a, case_b}


def test_race_recovery_still_flags_a_genuine_conflict_from_a_different_entity():
    """The harder case: the race window hides an existing row from
    find_identifier, AND that row belongs to a genuinely different
    entity — not just a retry of our own insert. Must still end up as
    a match_candidate, not a silent no-op."""
    store = OneShotRaceStore()
    case_a = new_id()
    case_b = new_id()
    source_id = store.get_or_create_source("Axis", "Axis Bank", "bank")
    ident = Identifier(entity_type="case", identifier_type="bank_account_ref", identifier_value="SHARED-ACC")

    _reconcile_identifier(store, entity_type="case", entity_id=case_a, ident=ident, source_id=source_id)
    # force the race again for case_b's attempt at the SAME identifier value
    store._missed_once.discard(("case", "bank_account_ref", "SHARED-ACC"))
    _reconcile_identifier(store, entity_type="case", entity_id=case_b, ident=ident, source_id=source_id)

    assert len(store.identifiers) == 1
    assert len(store.match_candidates) == 1
    candidate = list(store.match_candidates.values())[0]
    assert {candidate["entity_id_a"], candidate["entity_id_b"]} == {case_a, case_b}


def test_insert_identifier_raising_something_other_than_a_race_still_propagates():
    """If find_identifier misses a row for a reason that ISN'T a benign
    retry-of-our-own-insert (e.g. it's actually not there at all, and
    insert_identifier fails for some other real, non-transient reason),
    the recovery path must not swallow a genuine failure."""

    class BrokenStore(InMemoryStore):
        def insert_identifier(self, identifier_row):
            raise DuplicateIdentifierError("simulated")

        def find_identifier(self, entity_type, identifier_type, identifier_value):
            return None  # even after the "duplicate", nothing is actually found — inconsistent state

    store = BrokenStore()
    source_id = store.get_or_create_source("Axis", "Axis Bank", "bank")
    ident = Identifier(entity_type="case", identifier_type="case_reference", identifier_value="AXIS-broken")

    with pytest.raises(DuplicateIdentifierError):
        _reconcile_identifier(store, entity_type="case", entity_id=new_id(), ident=ident, source_id=source_id)


def test_supabase_store_translates_the_real_postgrest_duplicate_key_error():
    """Confirms the actual translation seen in production:
    postgrest.exceptions.APIError carrying code='23505' becomes our own
    DuplicateIdentifierError, not left as a raw library exception."""
    from ingestion.common.store import SupabaseStore

    class FakeDuplicateKeyError(Exception):
        code = "23505"

    class FakeQuery:
        def insert(self, _row):
            return self

        def execute(self):
            raise FakeDuplicateKeyError(
                "duplicate key value violates unique constraint "
                '"entity_identifiers_entity_type_identifier_type_identifier_v_key"'
            )

    class FakeClient:
        def table(self, _name):
            return FakeQuery()

    store = SupabaseStore(FakeClient(), retries=1)
    with pytest.raises(DuplicateIdentifierError):
        store.insert_identifier(
            {
                "entity_type": "case", "entity_id": "x", "identifier_type": "case_reference",
                "identifier_value": "AXIS-x", "source_id": "y", "match_method": "deterministic", "confidence": None,
            }
        )
