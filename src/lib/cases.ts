// Data access layer.
//
// TODO(supabase): once the existing project (eesbjpjwamzmiormzzop) is connected,
// replace every placeholder read below with the queries noted in each function.
// All tables are soft-deleted: every query must include `.is("deleted_at", null)`.
import { queryOptions } from "@tanstack/react-query";

import {
  assets as assetRows,
  caseParties as casePartyRows,
  cases as caseRows,
  dashboardStats as dashboardStatsRow,
  documents as documentRows,
  liabilities as liabilityRows,
  parties as partyRows,
} from "./placeholder-data";
import type { CaseDetail, CaseListRow, DashboardStats } from "./types";

const partyById = (id: string | null) =>
  id ? (partyRows.find((p) => p.id === id && !p.deleted_at) ?? null) : null;

/** supabase.from("cases").select("*, case_parties(role, parties(full_name))").is("deleted_at", null) */
async function fetchCases(): Promise<CaseListRow[]> {
  return caseRows
    .filter((c) => !c.deleted_at)
    .map((c) => {
      const link = casePartyRows.find(
        (cp) => cp.case_id === c.id && cp.role === "Borrower" && !cp.deleted_at,
      );
      return { ...c, borrower_name: partyById(link?.party_id ?? null)?.full_name ?? null };
    });
}

/** One case + case_parties/parties, documents, liabilities (+lender), assets. */
async function fetchCaseDetail(caseId: string): Promise<CaseDetail | null> {
  const found = caseRows.find((c) => c.id === caseId && !c.deleted_at);
  if (!found) return null;
  return {
    case: found,
    parties: casePartyRows
      .filter((cp) => cp.case_id === caseId && !cp.deleted_at)
      .map((cp) => ({ ...cp, party: partyById(cp.party_id) })),
    documents: documentRows.filter((d) => d.case_id === caseId && !d.deleted_at),
    liabilities: liabilityRows
      .filter((l) => l.case_id === caseId && !l.deleted_at)
      .map((l) => ({ ...l, lender: partyById(l.lender_id) })),
    assets: assetRows.filter((a) => a.case_id === caseId && !a.deleted_at),
  };
}

/** supabase.rpc("dashboard_stats").single() */
async function fetchDashboardStats(): Promise<DashboardStats> {
  return dashboardStatsRow;
}

/** cases with next_hearing_date in the future, soonest first. */
async function fetchUpcomingHearings(): Promise<CaseListRow[]> {
  const now = Date.now();
  const all = await fetchCases();
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