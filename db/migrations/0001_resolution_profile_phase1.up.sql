-- ResolveHub — Phase 1: Resolution Profile evidence/enrichment layer
--
-- ADDITIVE ONLY. This migration creates six new tables. It does not
-- ALTER, rename, or add a column to any existing table — cases,
-- parties, case_parties, liabilities, assets, documents are untouched
-- and keep their current data, constraints and RLS policies exactly
-- as they are today. New tables reference the existing ones only via
-- foreign keys that point AT them (never the reverse), so this can be
-- applied against the live production database with zero risk of
-- data loss or behavior change in the existing app.
--
-- Rollback: 0001_resolution_profile_phase1.down.sql drops exactly
-- these six tables, in reverse dependency order, and touches nothing
-- else.

-- Supabase/Postgres 13+ ships gen_random_uuid() via pgcrypto already
-- enabled on most projects; this is idempotent if it's already on.
create extension if not exists pgcrypto;

-- ---------------------------------------------------------------
-- sources — registry of where information comes from. One row per
-- adapter (SBI, Canara, and later IBBI/NCLT/MCA/auction portals).
-- ---------------------------------------------------------------
create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,              -- short code used by adapters, e.g. 'SBI', 'CANARA'
  full_name text not null,                -- e.g. 'State Bank of India'
  source_type text not null check (source_type in ('bank', 'ibbi', 'nclt', 'mca', 'auction_portal', 'manual', 'other')),
  base_url text,
  created_at timestamptz not null default now()
);

comment on table sources is 'Registry of ingestion sources. One row per adapter (bank, IBBI, NCLT, MCA, auction portal, ...).';

-- ---------------------------------------------------------------
-- ingestion_runs — one row per adapter execution. Gives us auditability
-- and the counters needed to distinguish success/partial/failed runs.
-- ---------------------------------------------------------------
create table if not exists ingestion_runs (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references sources(id),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  status text not null default 'running' check (status in ('running', 'success', 'partial', 'failed')),
  records_seen integer not null default 0,
  records_ingested integer not null default 0,
  records_skipped integer not null default 0,
  records_failed integer not null default 0,
  error_summary text,
  created_at timestamptz not null default now()
);

create index if not exists idx_ingestion_runs_source on ingestion_runs(source_id, started_at desc);

comment on table ingestion_runs is 'One row per adapter execution — enables idempotent, resumable, auditable ingestion.';

-- ---------------------------------------------------------------
-- field_observations — the provenance/evidence ledger. One row per
-- observed value for one field on one entity from one source, at one
-- point in time. Never updated in place and never deleted — a changed
-- value is always a NEW row, with `is_current` recomputed across all
-- rows for that (entity, field). This is what makes reserve-price
-- history, and disagreement between sources, first-class instead of
-- a silent overwrite.
--
-- entity_id is polymorphic (points at cases.id, liabilities.id,
-- assets.id, or parties.id depending on entity_type) and intentionally
-- has NO foreign key — Postgres can't constrain a column against one
-- of several tables. Application code is responsible for entity_id
-- validity; a future improvement could add a trigger-based check.
--
-- Only value_numeric / value_text / value_date / value_jsonb that
-- actually applies to a given field_name is populated; value_jsonb is
-- reserved for genuinely source-specific attributes that don't map to
-- a typed column (e.g. one IBBI page including a nested claims
-- breakdown) — most fields should use a typed column, not JSON.
-- ---------------------------------------------------------------
create table if not exists field_observations (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null check (entity_type in ('case', 'liability', 'asset', 'party')),
  entity_id uuid not null,
  field_name text not null,
  value_numeric numeric,
  value_text text,
  value_date date,
  value_jsonb jsonb,
  unit text,
  source_id uuid not null references sources(id),
  source_document_id uuid references documents(id),
  source_record_ref text,
  published_at date,
  retrieved_at timestamptz not null default now(),
  confidence text not null default 'source_derived' check (confidence in ('verified', 'source_derived', 'inferred')),
  is_current boolean not null default true,
  superseded_by uuid references field_observations(id),
  ingestion_run_id uuid references ingestion_runs(id),
  created_at timestamptz not null default now(),
  constraint field_observations_value_present check (
    value_numeric is not null or value_text is not null or value_date is not null or value_jsonb is not null
  )
);

create index if not exists idx_field_observations_entity on field_observations(entity_type, entity_id, field_name);
create index if not exists idx_field_observations_current on field_observations(entity_type, entity_id, field_name) where is_current;
create index if not exists idx_field_observations_source on field_observations(source_id);

comment on table field_observations is 'Provenance ledger: every observed value for every field, with source, confidence and full history. is_current is recomputed, never hand-edited.';

-- ---------------------------------------------------------------
-- case_events — a curated, human-readable timeline derived from
-- field_observations (e.g. a reserve-price change becomes both a new
-- field_observations row AND a case_events row), plus room for events
-- that don't reduce to a single field (e.g. "CIRP admitted").
-- ---------------------------------------------------------------
create table if not exists case_events (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id),
  event_type text not null,
  event_date date,
  description text,
  source_id uuid references sources(id),
  field_observation_id uuid references field_observations(id),
  ingestion_run_id uuid references ingestion_runs(id),
  created_at timestamptz not null default now()
);

create index if not exists idx_case_events_case on case_events(case_id, event_date);

comment on table case_events is 'Curated timeline of what happened to a case over time — reserve price changes, auction outcomes, legal milestones.';

-- ---------------------------------------------------------------
-- entity_identifiers — authoritative identifiers used for deterministic
-- entity resolution (CIN, LLPIN, bank account ref, IBBI/NCLT case ref,
-- our own case_reference, ...). The unique constraint is deliberate:
-- it makes a second source claiming the same identifier for a
-- DIFFERENT entity a hard conflict the application must handle
-- explicitly (see entity_match_candidates) rather than something that
-- can silently succeed.
-- ---------------------------------------------------------------
create table if not exists entity_identifiers (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null check (entity_type in ('case', 'party')),
  entity_id uuid not null,
  identifier_type text not null,
  identifier_value text not null,
  source_id uuid not null references sources(id),
  match_method text not null default 'deterministic' check (match_method in ('deterministic', 'fuzzy')),
  confidence numeric,
  created_at timestamptz not null default now(),
  unique (entity_type, identifier_type, identifier_value)
);

create index if not exists idx_entity_identifiers_lookup on entity_identifiers(identifier_type, identifier_value);

comment on table entity_identifiers is 'Authoritative identifiers for deterministic entity resolution. Unique per (entity_type, identifier_type, identifier_value) so conflicting claims surface instead of silently merging.';

-- ---------------------------------------------------------------
-- entity_match_candidates — where a probable link between two entities
-- is recorded (fuzzy name match, or a deterministic-identifier
-- conflict) WITHOUT ever automatically merging them. A human — or a
-- later, explicit workflow — resolves these.
-- ---------------------------------------------------------------
create table if not exists entity_match_candidates (
  id uuid primary key default gen_random_uuid(),
  entity_type text not null check (entity_type in ('case', 'party')),
  entity_id_a uuid not null,
  entity_id_b uuid not null,
  match_method text not null check (match_method in ('deterministic', 'fuzzy')),
  confidence numeric,
  evidence jsonb,
  status text not null default 'pending' check (status in ('pending', 'confirmed', 'rejected')),
  created_at timestamptz not null default now()
);

create index if not exists idx_entity_match_candidates_status on entity_match_candidates(status);

comment on table entity_match_candidates is 'Uncertain or conflicting entity matches awaiting review. Nothing is auto-merged into here.';
