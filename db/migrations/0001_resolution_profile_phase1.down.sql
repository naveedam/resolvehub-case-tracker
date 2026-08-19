-- Rollback for 0001_resolution_profile_phase1.up.sql
--
-- Drops exactly the six tables that migration created, in reverse
-- dependency order. Does not touch cases, parties, case_parties,
-- liabilities, assets, documents, or the pgcrypto extension (other
-- parts of the database may depend on gen_random_uuid()).

drop table if exists entity_match_candidates;
drop table if exists entity_identifiers;
drop table if exists case_events;
drop table if exists field_observations;
drop table if exists ingestion_runs;
drop table if exists sources;
