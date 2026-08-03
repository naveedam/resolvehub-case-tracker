// Domain types mirroring the existing Supabase schema (project eesbjpjwamzmiormzzop).
// Field names match the database exactly — do not rename.

export const PARTY_TYPES = [
  "Individual",
  "Company",
  "Bank",
  "NBFC",
  "Government",
  "Trust",
  "NGO",
  "Charity",
  "Court",
  "Other",
] as const;
export type PartyType = (typeof PARTY_TYPES)[number];

export const CASE_PARTY_ROLES = [
  "Borrower",
  "Co-Borrower",
  "Guarantor",
  "Lender",
  "Plaintiff",
  "Defendant",
  "Resolution Professional",
  "Petitioner",
  "Respondent",
  "Other",
] as const;
export type CasePartyRole = (typeof CASE_PARTY_ROLES)[number];

export const LOAN_TYPES = [
  "Home Loan",
  "Gold Loan",
  "Personal Loan",
  "Business Loan",
  "Education Loan",
  "Vehicle Loan",
  "Credit Card",
  "Agriculture Loan",
  "Trade Credit",
  "Other",
] as const;
export type LoanType = (typeof LOAN_TYPES)[number];

export const ASSET_TYPES = [
  "Gold",
  "House",
  "Apartment",
  "Land",
  "Vehicle",
  "Machinery",
  "Inventory",
  "Business",
  "Other",
] as const;
export type AssetType = (typeof ASSET_TYPES)[number];

export interface Case {
  id: string;
  title: string;
  case_type: string | null;
  status: string | null;
  court_name: string | null;
  filing_date: string | null;
  next_hearing_date: string | null;
  estimated_liability: number | null;
  summary: string | null;
  deleted_at: string | null;
}

export interface Party {
  id: string;
  full_name: string;
  party_type: PartyType | null;
  deleted_at: string | null;
}

export interface CaseParty {
  id: string;
  case_id: string;
  party_id: string;
  role: CasePartyRole;
  deleted_at: string | null;
}

export interface Liability {
  id: string;
  case_id: string;
  lender_id: string | null;
  loan_type: LoanType | null;
  account_number: string | null;
  outstanding_amount: number | null;
  deleted_at: string | null;
}

export interface Asset {
  id: string;
  case_id: string;
  asset_type: AssetType | null;
  description: string | null;
  auction_date: string | null;
  auction_status: string | null;
  deleted_at: string | null;
}

export interface CaseDocument {
  id: string;
  case_id: string;
  document_type: string | null;
  document_name: string | null;
  storage_path: string | null;
  deleted_at: string | null;
}

export interface DashboardStats {
  total_cases: number;
  active_cases: number;
  total_liability: number;
  assets_at_risk: number;
  upcoming_hearings_count: number;
}

/** A case row enriched with the party linked via role = 'Borrower'. */
export interface CaseListRow extends Case {
  borrower_name: string | null;
}

export interface CasePartyWithParty extends CaseParty {
  party: Party | null;
}

export interface LiabilityWithLender extends Liability {
  lender: Party | null;
}

export interface CaseDetail {
  case: Case;
  parties: CasePartyWithParty[];
  documents: CaseDocument[];
  liabilities: LiabilityWithLender[];
  assets: Asset[];
}