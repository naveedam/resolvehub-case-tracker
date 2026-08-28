import { queryOptions } from "@tanstack/react-query";
import { supabase } from "./supabase";
import type {
  CaseDetail,
  ResolutionProfile,
  FieldObservation,
  CaseEvent,
  EntityIdentifier,
  Source,
  Confidence,
} from "./types";

async function fetchResolutionProfile(
  caseDetail: CaseDetail,
): Promise<ResolutionProfile> {
  const caseId = caseDetail.case.id;

  const [{ data: observations }, { data: events }, { data: identifiers }] =
    await Promise.all([
      supabase
        .from("field_observations")
        .select("*")
        .eq("entity_type", "case")
        .eq("entity_id", caseId)
        .eq("is_current", true),

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

  const sourceIds = Array.from(
    new Set((observations ?? []).map((o) => o.source_id).filter(Boolean)),
  );

  let sourcesById: Record<string, Source> = {};

  if (sourceIds.length) {
    const { data: sources } = await supabase
      .from("sources")
      .select("*")
      .in("id", sourceIds);

    sourcesById = Object.fromEntries((sources ?? []).map((s) => [s.id, s]));
  }

  return {
    observations: (observations ?? []) as FieldObservation[],
    events: (events ?? []) as CaseEvent[],
    identifiers: (identifiers ?? []) as EntityIdentifier[],
    sourcesById,
  };
}

export const resolutionProfileQueryOptions = (caseDetail: CaseDetail) =>
  queryOptions({
    queryKey: ["resolution-profile", caseDetail.case.id],
    queryFn: () => fetchResolutionProfile(caseDetail),
  });

export const CONFIDENCE_LABEL: Record<Confidence, string> = {
  verified: "Verified",
  source_derived: "Source derived",
  inferred: "Inferred",
};

export function currentObservations(
  profile: ResolutionProfile,
  field: string,
): FieldObservation[] {
  return profile.observations.filter((o) => o.field_name === field);
}

export function findCurrent(
  profile: ResolutionProfile,
  field: string,
): FieldObservation | undefined {
  return currentObservations(profile, field)[0];
}

export function currentValue(
  profile: ResolutionProfile,
  field: string,
): string | number | null {
  const obs = findCurrent(profile, field);
  if (!obs) return null;
  return obs.value_text ?? obs.value_numeric ?? obs.value_date ?? null;
}

export function historyFor(
  profile: ResolutionProfile,
  field: string,
): FieldObservation[] {
  return profile.observations.filter((o) => o.field_name === field);
}
