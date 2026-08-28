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

async function fetchCaseDetail(caseId: string): Promise<CaseDetail | null> {
  const { data: caseRow, error: caseErr } = await supabase
    .from("cases")
    .select("*")
    .eq("id", caseId)
    .is("deleted_at", null)
    .maybeSingle();

  if (caseErr) throw caseErr;
  if (!caseRow) return null;

  const [
    { data: parties, error: partiesErr },
    { data: documents, error: docsErr },
    { data: liabilities, error: liabErr },
    { data: assets, error: assetsErr },
    { data: drtProfile, error: drtErr },
  ] = await Promise.all([
    supabase
      .from("case_parties")
      .select("*, parties(*)")
      .eq("case_id", caseId),

    supabase
      .from("documents")
      .select("*")
      .eq("case_id", caseId)
      .is("deleted_at", null),

    supabase
      .from("liabilities")
      .select("*, parties(*)")
      .eq("case_id", caseId)
      .is("deleted_at", null),

    supabase
      .from("assets")
      .select("*")
      .eq("case_id", caseId)
      .is("deleted_at", null),

    supabase
      .from("drt_profiles")
      .select("*")
      .eq("case_id", caseId)
      .maybeSingle(),
  ]);

  if (partiesErr) throw partiesErr;
  if (docsErr) throw docsErr;
  if (liabErr) throw liabErr;
  if (assetsErr) throw assetsErr;
  if (drtErr) throw drtErr;

  return {
    case: caseRow,
    parties: (parties ?? []).map((cp: any) => ({
      ...cp,
      party: cp.parties ?? null,
    })),
    documents: documents ?? [],
    liabilities: (liabilities ?? []).map((l: any) => ({
      ...l,
      lender: l.parties ?? null,
    })),
    assets: assets ?? [],
    drt_profile: drtProfile ?? null,
  };
}

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

export const casesQueryOptions = () =>
  queryOptions({
    queryKey: ["cases"],
    queryFn: fetchCases,
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
