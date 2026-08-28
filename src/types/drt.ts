export interface DRTCase {
  id: string
  case_reference: string
  display_title: string
  case_number: string | null
  case_type: string
  court_name: string
  diary_number: string
  filing_date: string
  current_status: string
  next_hearing_date: string | null
  applicant_advocate: string | null
  respondent_advocate: string | null
}
