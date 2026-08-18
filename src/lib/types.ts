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

// --- Phase 1 Resolution Profile layer (additive tables — see
// db/migrations/0001_resolution_profile_phase1.up.sql) ---

export type ObservationEntityType = "case" | "liability" | "asset" | "party";
export type Confidence = "verified" | "source_derived" | "inferred";

export interface Source {
  id: string;
  name: string;
  full_name: string;
  source_type: string;
}

export interface FieldObservation {
  id: string;
  entity_type: ObservationEntityType;
  entity_id: string;
  field_name: string;
  value_numeric: number | null;
  value_text: string | null;
  value_date: string | null;
  value_jsonb: unknown | null;
  unit: string | null;
  source_id: string;
  published_at: string | null;
  retrieved_at: string;
  confidence: Confidence;
  is_current: boolean;
  superseded_by: string | null;
}

export interface CaseEvent {
  id: string;
  case_id: string;
  event_type: string;
  event_date: string | null;
  description: string | null;
  source_id: string | null;
}

export interface EntityIdentifier {
  id: string;
  entity_type: "case" | "party";
  entity_id: string;
  identifier_type: string;
  identifier_value: string;
  source_id: string;
  match_method: "deterministic" | "fuzzy";
}

export interface ResolutionProfile {
  observations: FieldObservation[];
  sourcesById: Record<string, Source>;
  events: CaseEvent[];
  identifiers: EntityIdentifier[];
}
