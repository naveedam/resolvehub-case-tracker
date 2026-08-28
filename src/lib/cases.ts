// Data access layer — real Supabase queries.
import { queryOptions } from "@tanstack/react-query";
import { supabase } from "./supabase";
import type { CaseDetail, CaseListRow, DashboardStats } from "./types";

const SUPABASE_PAGE_SIZE = 1000;

async function fetchAllRows<T>(
  buildPage: (
    from: number,
    to: number,
  ) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>,
): Promise<T[]> {
  const rows: T[] = [];
  let from = 0;

  for (;;) {
    const { data, error } = await buildPage(from, from + SUPABASE_PAGE_SIZE - 1);

    if (error) throw error;
    if (!data || data.length === 0) break;

    rows.push(...data);

    if (data.length < SUPABASE_PAGE_SIZE) break;
    from += SUPABASE_PAGE_SIZE;
  }

  return rows;
}

// ---------------- DRT PROCEEDINGS ----------------

async function fetchCases(): Promise<CaseListRow[]> {
  const rows = await fetchAllRows<any>((from, to) =>
    supabase
      .from("v_drt_cases")
      .select("*")
      .order("filing_date", { ascending: false })
      .range(from, to),
  );

  return rows.map((r) => ({
    id: r.id,
    case_reference: r.case_reference,
    title: r.display_title,
    display_title: r.display_title,
    case_type: r.case_type,
    court_name: r.court_name,
    borrower_name: null,
    status: r.current_status,
    next_hearing_date: r.next_hearing_date,
    estimated_liability: null,
    filing_date: r.filing_date,
    summary: null,
    deleted_at: null,
  }));
}

// ---------------- BANK CASES ----------------

async function fetchLegacyCases(): Promise<any[]> {
  return fetchAllRows<any>((from, to) =>
    supabase
      .from("cases")
      .select("*")
      .is("deleted_at", null)
      .order("created_at", { ascending: false })
      .range(from, to),
  );
}

async function fetchDrtProfiles(): Promise<any[]> {
  return fetchAllRows<any>((from, to) =>
    supabase
      .from("drt_profiles")
      .select("case_id")
      .range(from, to),
  );
}

// ---------------- CASE DETAIL ----------------

async function fetchCaseDetail(caseId: string): Promise<CaseDetail | null> {
  const { data: caseRow, error } = await supabase
    .from("cases")
    .select("*")
    .eq("id", caseId)
    .maybeSingle();

  if (error) throw error;
  if (!caseRow) return null;

  const [
    { data: parties },
    { data: documents },
    { data: liabilities },
    { data: assets },
    { data: drtProfile },
  ] = await Promise.all([
    supabase.from("case_parties").select("*, parties(*)").eq("case_id", caseId),
    supabase.from("documents").select("*").eq("case_id", caseId),
    supabase.from("liabilities").select("*, parties(*)").eq("case_id", caseId),
    supabase.from("assets").select("*").eq("case_id", caseId),
    supabase.from("drt_profiles").select("*").eq("case_id", caseId).maybeSingle(),
  ]);

  return {
    case: caseRow,
    parties: (parties ?? []).map((p: any) => ({ ...p, party: p.parties })),
    documents: documents ?? [],
    liabilities: (liabilities ?? []).map((l: any) => ({ ...l, lender: l.parties })),
    assets: assets ?? [],
    drt_profile: drtProfile ?? null,
  };
}

// ---------------- DASHBOARD ----------------

async function fetchDashboardStats(): Promise<DashboardStats> {
  const { data, error } = await supabase.rpc("dashboard_stats").single();
  if (error) throw error;
  return data as DashboardStats;
}

async function fetchUpcomingHearings(): Promise<CaseListRow[]> {
  const all = await fetchCases();
  const now = Date.now();

  return all
    .filter((c) => c.next_hearing_date && new Date(c.next_hearing_date).getTime() > now)
    .sort((a, b) => (a.next_hearing_date! < b.next_hearing_date! ? -1 : 1));
}

// ---------------- EXPORTS ----------------

export const casesQueryOptions = () =>
  queryOptions({
    queryKey: ["cases"],
    queryFn: fetchCases,
  });

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

export const caseDetailQueryOptions = (caseId: string) =>
  queryOptions({
    queryKey: ["cases", caseId],
    queryFn: () => fetchCaseDetail(caseId),
  });

export const dashboardStatsQueryOptions = () =>
  queryOptions({
    queryKey: ["dashboard-stats"],
    queryFn: fetchDashboardStats,
  });

export const upcomingHearingsQueryOptions = () =>
  queryOptions({
    queryKey: ["upcoming-hearings"],
    queryFn: fetchUpcomingHearings,
  });

// ---------------- HELPERS ----------------

export function formatCurrency(value: number | null | undefined) {
  if (value == null) return "—";

  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatDate(value: string | null | undefined) {
  if (!value) return "—";

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

export type TicketSize = "small" | "mid" | "large" | "unknown";

export const TICKET_SIZE_LABELS: Record<TicketSize, string> = {
  small: "Small (≤ ₹10L)",
  mid: "Mid-market (₹10L – ₹5Cr)",
  large: "Large corporate (> ₹5Cr)",
  unknown: "Unclassified",
};

export function classifyTicketSize(value: number | null | undefined): TicketSize {
  if (value == null) return "unknown";
  if (value <= 1_000_000) return "small";
  if (value <= 50_000_000) return "mid";
  return "large";
}
