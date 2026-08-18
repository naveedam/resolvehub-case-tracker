// Resolution Profile read model — Phase 1.
//
// This reads the new, additive tables (sources / field_observations /
// case_events / entity_identifiers) created by
// db/migrations/0001_resolution_profile_phase1.up.sql, and joins them
// onto a case's existing liability/asset rows. It never writes to
// these tables — only the ingestion adapters
// (ingestion/common/runtime.py) do that.
import { queryOptions } from "@tanstack/react-query";
import { supabase } from "./supabase";
import type {
  CaseDetail,
  CaseEvent,
  EntityIdentifier,
  FieldObservation,
  ResolutionProfile,
  Source,
} from "./types";

async function fetchResolutionProfile(caseDetail: CaseDetail): Promise<ResolutionProfile> {
  const caseId = caseDetail.case.id;
  const liabilityIds = caseDetail.liabilities.map((l) => l.id);
  const assetIds = caseDetail.assets.map((a) => a.id);

  const observationQueries = [
    supabase
      .from("field_observations")
      .select("*")
      .eq("entity_type", "case")
      .eq("entity_id", caseId),
  ];
  if (liabilityIds.length > 0) {
    observationQueries.push(
      supabase
        .from("field_observations")
        .select("*")
        .eq("entity_type", "liability")
        .in("entity_id", liabilityIds),
    );
  }
  if (assetIds.length > 0) {
    observationQueries.push(
      supabase
        .from("field_observations")
        .select("*")
        .eq("entity_type", "asset")
        .in("entity_id", assetIds),
    );
  }

  const [observationResults, eventsResult, identifiersResult] = await Promise.all([
    Promise.all(observationQueries),
    supabase
      .from("case_events")
      .select("*")
      .eq("case_id", caseId)
      .order("event_date", { ascending: false }),
    supabase
      .from("entity_identifiers")
      .select("*")
      .eq("entity_type", "case")
      .eq("entity_id", caseId),
  ]);

  for (const r of observationResults) if (r.error) throw r.error;
  if (eventsResult.error) throw eventsResult.error;
  if (identifiersResult.error) throw identifiersResult.error;

  const observations: FieldObservation[] = observationResults.flatMap((r) => r.data ?? []);
  const events: CaseEvent[] = eventsResult.data ?? [];
  const identifiers: EntityIdentifier[] = identifiersResult.data ?? [];

  const sourceIds = Array.from(
    new Set([
      ...observations.map((o) => o.source_id),
      ...events.map((e) => e.source_id).filter((id): id is string => !!id),
      ...identifiers.map((i) => i.source_id),
    ]),
  );

  let sourcesById: Record<string, Source> = {};
  if (sourceIds.length > 0) {
    const { data: sources, error } = await supabase.from("sources").select("*").in("id", sourceIds);
    if (error) throw error;
    sourcesById = Object.fromEntries((sources ?? []).map((s) => [s.id, s]));
  }

  return { observations, sourcesById, events, identifiers };
}

export const resolutionProfileQueryOptions = (caseDetail: CaseDetail | null | undefined) =>
  queryOptions({
    queryKey: ["resolution-profile", caseDetail?.case.id],
    queryFn: () => fetchResolutionProfile(caseDetail as CaseDetail),
    enabled: !!caseDetail,
  });

// --- helpers for the UI ---

export function currentValue(obs: FieldObservation): string {
  if (obs.value_numeric != null) {
    return obs.unit === "INR"
      ? new Intl.NumberFormat("en-IN", {
          style: "currency",
          currency: "INR",
          maximumFractionDigits: 0,
        }).format(obs.value_numeric)
      : String(obs.value_numeric);
  }
  if (obs.value_text != null) return obs.value_text;
  if (obs.value_date != null) return obs.value_date;
  if (obs.value_jsonb != null) return JSON.stringify(obs.value_jsonb);
  return "—";
}

export function currentObservations(observations: FieldObservation[]): FieldObservation[] {
  return observations.filter((o) => o.is_current);
}

export function historyFor(
  observations: FieldObservation[],
  obs: FieldObservation,
): FieldObservation[] {
  return observations
    .filter(
      (o) =>
        o.entity_type === obs.entity_type &&
        o.entity_id === obs.entity_id &&
        o.field_name === obs.field_name,
    )
    .sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""));
}

export const CONFIDENCE_LABEL: Record<FieldObservation["confidence"], string> = {
  verified: "Verified",
  source_derived: "Source-derived",
  inferred: "Inferred",
};
