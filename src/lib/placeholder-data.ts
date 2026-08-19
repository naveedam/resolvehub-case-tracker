// TEMPORARY placeholder data so the UI renders before the existing Supabase
// project (eesbjpjwamzmiormzzop) is connected. Delete this file once
// src/lib/cases.ts talks to Supabase.
import type {
  Asset,
  Case,
  CaseDocument,
  CaseParty,
  DashboardStats,
  Liability,
  Party,
} from "./types";

export const parties: Party[] = [
  { id: "p1", full_name: "Ramesh Kumar", party_type: "Individual", deleted_at: null },
  { id: "p2", full_name: "Lakshmi Kumar", party_type: "Individual", deleted_at: null },
  { id: "p3", full_name: "State Bank of India", party_type: "Bank", deleted_at: null },
  { id: "p4", full_name: "Muthoot Finance Ltd.", party_type: "NBFC", deleted_at: null },
  { id: "p5", full_name: "Anita Desai", party_type: "Individual", deleted_at: null },
  { id: "p6", full_name: "Adv. S. Narayanan", party_type: "Individual", deleted_at: null },
];

export const cases: Case[] = [
  {
    id: "c1",
    case_reference: "PLACEHOLDER-C1",
    title: "SBI v. Ramesh Kumar — SARFAESI recovery",
    case_type: "SARFAESI",
    status: "Active",
    court_name: "DRT Chennai",
    filing_date: "2025-11-04",
    next_hearing_date: "2026-08-19",
    estimated_liability: 4250000,
    summary:
      "Secured creditor action over a residential property mortgage following 9 months of missed EMIs. Borrower is seeking a restructuring settlement.",
    deleted_at: null,
  },
  {
    id: "c2",
    case_reference: "PLACEHOLDER-C2",
    title: "In re: Anita Desai — Personal insolvency",
    case_type: "Insolvency",
    status: "Under Review",
    court_name: "NCLT Bengaluru",
    filing_date: "2026-02-17",
    next_hearing_date: "2026-09-02",
    estimated_liability: 1180000,
    summary:
      "Petition for personal insolvency resolution covering unsecured credit card and personal loan exposure across three lenders.",
    deleted_at: null,
  },
  {
    id: "c3",
    case_reference: "PLACEHOLDER-C3",
    title: "Muthoot Finance — Gold auction dispute",
    case_type: "Recovery",
    status: "Closed",
    court_name: "District Court Madurai",
    filing_date: "2024-06-11",
    next_hearing_date: null,
    estimated_liability: 320000,
    summary: "Challenge to a gold auction conducted without the statutory notice period.",
    deleted_at: null,
  },
];

export const caseParties: CaseParty[] = [
  { id: "cp1", case_id: "c1", party_id: "p1", role: "Borrower", deleted_at: null },
  { id: "cp2", case_id: "c1", party_id: "p2", role: "Co-Borrower", deleted_at: null },
  { id: "cp3", case_id: "c1", party_id: "p3", role: "Lender", deleted_at: null },
  { id: "cp4", case_id: "c2", party_id: "p5", role: "Borrower", deleted_at: null },
  { id: "cp5", case_id: "c2", party_id: "p6", role: "Resolution Professional", deleted_at: null },
  { id: "cp6", case_id: "c3", party_id: "p1", role: "Borrower", deleted_at: null },
  { id: "cp7", case_id: "c3", party_id: "p4", role: "Lender", deleted_at: null },
];

export const liabilities: Liability[] = [
  {
    id: "l1",
    case_id: "c1",
    lender_id: "p3",
    loan_type: "Home Loan",
    account_number: "XXXX-4471",
    outstanding_amount: 3850000,
    deleted_at: null,
  },
  {
    id: "l2",
    case_id: "c1",
    lender_id: "p4",
    loan_type: "Gold Loan",
    account_number: "GL-99120",
    outstanding_amount: 400000,
    deleted_at: null,
  },
  {
    id: "l3",
    case_id: "c2",
    lender_id: "p3",
    loan_type: "Credit Card",
    account_number: "XXXX-8802",
    outstanding_amount: 380000,
    deleted_at: null,
  },
  {
    id: "l4",
    case_id: "c2",
    lender_id: "p4",
    loan_type: "Personal Loan",
    account_number: "PL-33417",
    outstanding_amount: 800000,
    deleted_at: null,
  },
  {
    id: "l5",
    case_id: "c3",
    lender_id: "p4",
    loan_type: "Gold Loan",
    account_number: "GL-11238",
    outstanding_amount: 320000,
    deleted_at: null,
  },
];

export const assets: Asset[] = [
  {
    id: "a1",
    case_id: "c1",
    asset_type: "House",
    description: "2BHK independent house, Perambur, Chennai (1,250 sq ft)",
    auction_date: "2026-09-15",
    auction_status: "Scheduled",
    deleted_at: null,
  },
  {
    id: "a2",
    case_id: "c1",
    asset_type: "Vehicle",
    description: "Maruti Ertiga, 2019, hypothecated",
    auction_date: null,
    auction_status: "Not scheduled",
    deleted_at: null,
  },
  {
    id: "a3",
    case_id: "c2",
    asset_type: "Business",
    description: "Tailoring unit with 4 machines, Jayanagar",
    auction_date: null,
    auction_status: "Under valuation",
    deleted_at: null,
  },
  {
    id: "a4",
    case_id: "c3",
    asset_type: "Gold",
    description: "86 g gold ornaments pledged against GL-11238",
    auction_date: "2024-10-02",
    auction_status: "Auctioned",
    deleted_at: null,
  },
];

export const documents: CaseDocument[] = [
  {
    id: "d1",
    case_id: "c1",
    document_type: "Notice",
    document_name: "Section 13(2) demand notice",
    storage_path: "https://example.org/docs/sbi-13-2-notice.pdf",
    deleted_at: null,
  },
  {
    id: "d2",
    case_id: "c1",
    document_type: "Agreement",
    document_name: "Home loan sanction letter",
    storage_path: "https://example.org/docs/sanction-letter.pdf",
    deleted_at: null,
  },
  {
    id: "d3",
    case_id: "c2",
    document_type: "Petition",
    document_name: "Insolvency petition filing",
    storage_path: "https://example.org/docs/insolvency-petition.pdf",
    deleted_at: null,
  },
  {
    id: "d4",
    case_id: "c3",
    document_type: "Order",
    document_name: "Final order dated 12-01-2025",
    storage_path: "https://example.org/docs/final-order.pdf",
    deleted_at: null,
  },
];

export const dashboardStats: DashboardStats = {
  total_cases: cases.length,
  active_cases: cases.filter((c) => c.status === "Active").length,
  total_liability: cases.reduce((sum, c) => sum + (c.estimated_liability ?? 0), 0),
  assets_at_risk: assets.filter((a) => a.auction_status === "Scheduled").length,
  upcoming_hearings_count: cases.filter(
    (c) => c.next_hearing_date && new Date(c.next_hearing_date) > new Date(),
  ).length,
};
