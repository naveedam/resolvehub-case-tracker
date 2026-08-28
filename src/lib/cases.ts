// ADD these two functions below fetchCases()

async function fetchLegacyCases(): Promise<any[]> {
  return fetchAllRows<any>((from, to) =>
    supabase
      .from("legacy_cases")
      .select("*")
      .order("created_at", { ascending: false })
      .range(from, to),
  );
}

async function fetchDrtProfiles(): Promise<any[]> {
  return fetchAllRows<any>((from, to) =>
    supabase
      .from("drt_profiles")
      .select("id")
      .range(from, to),
  );
}

// ADD these exports at the bottom (do not remove existing ones)

export const legacyCasesQueryOptions = () =>
  queryOptions({
    queryKey: ["legacy-cases"],
    queryFn: fetchLegacyCases,
  });

export const drtProfilesQueryOptions = () =>
  queryOptions({
    queryKey: ["drt-profiles"],
    queryFn: fetchDrtProfiles,
  });
