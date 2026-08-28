import { queryOptions } from "@tanstack/react-query";
import { supabase } from "./supabase";
import type {
  CaseDetail,
  ResolutionProfile,
  FieldObservation,
  CaseEvent,
  EntityIdentifier,
  Source,
} from "./types";

async function fetchResolutionProfile(caseDetail: CaseDetail): Promise<ResolutionProfile> {
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
    new Set([
      ...(observations ?? []).map((o) => o.source_id),
      ...(events ?? [])
        .map((e) => e.source_id)
        .filter(Boolean) as string[],
      ...(identifiers ?? []).map((i) => i.source_id),
    ]),
  );

  const { data: sources } =
    sourceIds.length === 0
      ? { data: [] }
      : await supabase.from("sources").select("*").in("id", sourceIds);

  const sourcesById: Record<string, Source> = {};
  (sources ?? []).forEach((s) => {
    sourcesById[s.id] = s;
  });

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
