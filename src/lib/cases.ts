// Data access layer — real Supabase queries.
import { queryOptions } from "@tanstack/react-query";
import { supabase } from "./supabase";
import type { CaseDetail, CaseListRow, DashboardStats } from "./types";

async function fetchCases(): Promise<CaseListRow[]> {
  const { data: cases, error } = await supabase
    .from("cases")
    .select("*")
    .is("deleted_at", null);
  if (error) throw error;
  if (!cases || cases.length === 0) return [];

  const caseIds = cases.map((c) => c.id);
  const { data: links, error: linkErr } = await supabase
    .from("case_parties")
    .select("case_id, parties(full_name)")
    .in("case_id", caseIds)
    .eq("role", "Borrower");
  if (linkErr) throw linkErr;

  const borrowerByCase = new Map(
    (links ?? []).map((l: any) => [l.case_id, l.parties?.full_name ?? null]),
  );

  return cases.map((c) => ({
    ...c,
    borrower_name: borrowerByCase.get(c.id) ?? null,
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

  const [{ data: parties, error: partiesErr }, { data: documents, error: docsErr },
         { data: liabilities, error: liabErr }, { data: assets, error: assetsErr }] =
    await Promise.all([
      supabase.from("case_parties").select("*, parties(*)").eq("case_id", caseId),
      supabase.from("documents").select("*").eq("case_id", caseId).is("deleted_at", null),
      supabase.from("liabilities").select("*, parties(*)").eq("case_id", caseId).is("deleted_at", null),
      supabase.from("assets").select("*").eq("case_id", caseId).is("deleted_at", null),
    ]);
  if (partiesErr) throw partiesErr;
  if (docsErr) throw docsErr;
  if (liabErr) throw liabErr;
  if (assetsErr) throw assetsErr;

  return {
    case: caseRow,
    parties: (parties ?? []).map((cp: any) => ({ ...cp, party: cp.parties ?? null })),
    documents: documents ?? [],
    liabilities: (liabilities ?? []).map((l: any) => ({ ...l, lender: l.parties ?? null })),
    assets: assets ?? [],
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
  queryOptions({ queryKey: ["cases"], queryFn: fetchCases });

export const caseDetailQueryOptions = (caseId: string) =>
  queryOptions({ queryKey: ["cases", caseId], queryFn: () => fetchCaseDetail(caseId) });

export const dashboardStatsQueryOptions = () =>
  queryOptions({ queryKey: ["dashboard-stats"], queryFn: fetchDashboardStats });

export const upcomingHearingsQueryOptions = () =>
  queryOptions({ queryKey: ["upcoming-hearings"], queryFn: fetchUpcomingHearings });

// Keep your existing formatCurrency/formatDate functions below this line —
// they don't touch Supabase and didn't need to change.
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
