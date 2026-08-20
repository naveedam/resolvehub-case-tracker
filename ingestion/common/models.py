"""Shared data model for ResolveHub ingestion adapters.

These types are the contract between a source-specific adapter (SBI's
Liferay/PDF parsing, Canara's master-PDF table parsing, and future
IBBI/NCLT/MCA adapters) and the shared ingestion runtime in
`ingestion/common/runtime.py`. An adapter's job is to produce
NormalizedRecord objects; it never talks to Supabase directly — that
is the runtime's job, so every source gets provenance, deduplication
and idempotency for free instead of reimplementing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

EntityType = Literal["case", "liability", "asset", "party"]
Confidence = Literal["verified", "source_derived", "inferred"]
MatchMethod = Literal["deterministic", "fuzzy"]

# Canonical field vocabulary per entity type. This is NOT enforced by the
# database (field_observations.field_name is a free-text column so a new
# source can introduce a new field without a migration) — it's enforced
# here so every adapter, and the Resolution Profile UI, agree on what a
# field is called. Add to these sets rather than inventing a new name for
# something that already exists.
CASE_FIELDS = {"estimated_liability", "status", "filing_date", "next_hearing_date", "npa_date"}
LIABILITY_FIELDS = {"outstanding_amount", "account_number", "loan_type"}
ASSET_FIELDS = {"reserve_price", "auction_date", "auction_status", "description", "possession_status", "asset_classification"}

_FIELDS_BY_ENTITY = {"case": CASE_FIELDS, "liability": LIABILITY_FIELDS, "asset": ASSET_FIELDS}

# Fields where a *changed* value is significant enough to also produce a
# human-readable case_events row, not just a new observation. Keep this
# narrow — everything still gets a field_observations row regardless.
EVENT_TRIGGER_FIELDS = {
    "reserve_price": "reserve_price_change",
    "auction_date": "auction_rescheduled",
    "auction_status": "auction_status_change",
    "possession_status": "possession_status_change",
    "estimated_liability": "liability_amount_change",
}


@dataclass
class FieldObservation:
    entity_type: EntityType
    field_name: str
    value_numeric: float | None = None
    value_text: str | None = None
    value_date: date | None = None
    value_jsonb: dict[str, Any] | None = None
    unit: str | None = None
    source_document_url: str | None = None
    source_record_ref: str | None = None
    published_at: date | None = None
    confidence: Confidence = "source_derived"

    def __post_init__(self) -> None:
        known_fields = _FIELDS_BY_ENTITY.get(self.entity_type)
        if known_fields is not None and self.field_name not in known_fields:
            raise ValueError(
                f"Unknown {self.entity_type} field {self.field_name!r} — "
                f"add it to the vocabulary in ingestion/common/models.py first"
            )
        if all(v is None for v in (self.value_numeric, self.value_text, self.value_date, self.value_jsonb)):
            raise ValueError("FieldObservation needs at least one value_* set")

    @property
    def value(self) -> Any:
        for v in (self.value_numeric, self.value_text, self.value_date, self.value_jsonb):
            if v is not None:
                return v
        return None


@dataclass
class Identifier:
    entity_type: Literal["case", "party"]
    identifier_type: str  # 'CIN', 'LLPIN', 'bank_account_ref', 'case_reference', 'ibbi_ref', ...
    identifier_value: str
    match_method: MatchMethod = "deterministic"
    confidence: float | None = None


@dataclass
class NormalizedDocument:
    document_type: str
    document_name: str
    storage_path: str  # source URL today; swap for a Supabase Storage path if PDFs get mirrored
    processed: bool = True


@dataclass
class NormalizedRecord:
    """One resolvable unit (in practice, today: one borrower's case)
    extracted from a source. Carries everything the shared runtime needs
    to (a) upsert the case/party/document/liability/asset rows exactly as
    the original scrapers did, and (b) additionally write typed,
    provenance-tracked observations, identifiers, and — where a value
    actually changed — events."""

    case_reference: str
    title: str
    case_type: str
    summary: str | None
    borrower_name: str
    borrower_type: str
    lender_name: str
    lender_type: str = "Bank"
    guarantors: list[tuple[str, str]] = field(default_factory=list)  # (name, party_type)
    filing_date: date | None = None
    asset_type: str | None = None  # classification (e.g. 'Land', 'Machinery'); not a sourced observation
    documents: list[NormalizedDocument] = field(default_factory=list)
    field_observations: list[FieldObservation] = field(default_factory=list)
    identifiers: list[Identifier] = field(default_factory=list)

    def get(self, entity_type: EntityType, field_name: str) -> FieldObservation | None:
        for obs in self.field_observations:
            if obs.entity_type == entity_type and obs.field_name == field_name:
                return obs
        return None
