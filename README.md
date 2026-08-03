# Case Resolve Hub

Connect to my existing Supabase project with ID eesbjpjwamzmiormzzop

(not a new project). Do not modify the database schema — it already

has real data in it.

Build a financial distress case tracking platform ("ResolveHub") with

the following:

1. AUTHENTICATION

Email/password login using Supabase Auth. Require login before

accessing any page — redirect unauthenticated users to a login screen.

No public signup form. Add a logout button in the header/nav.

2. DATA LAYER

Real queries (no mock data) against these existing tables: cases,

documents, liabilities, assets, parties, case_parties.

Key relationships:

- case_parties links cases to parties via case_id + party_id, with a

  role column (Borrower, Co-Borrower, Guarantor, Lender, Plaintiff,

  Defendant, Resolution Professional, Petitioner, Respondent, Other)

- liabilities.lender_id references parties(id)

- documents, liabilities, and assets all have a case_id foreign key

  to cases

- All tables use soft deletes — always filter deleted_at is null

- cases.estimated_liability, cases.status, cases.case_type,

  cases.court_name, cases.next_hearing_date, cases.filing_date,

  cases.summary are the core case fields

- assets.asset_type is a fixed set: Gold, House, Apartment, Land,

  Vehicle, Machinery, Inventory, Business, Other

- liabilities.loan_type is a fixed set: Home Loan, Gold Loan, Personal

  Loan, Business Loan, Education Loan, Vehicle Loan, Credit Card,

  Agriculture Loan, Trade Credit, Other

3. CASES LIST PAGE

Table/list of all cases (title, case_type, status, court_name,

next_hearing_date, estimated_liability), each showing the linked

Borrower name (from case_parties where role = 'Borrower', joined to

parties). Filters on case_type and status. Sortable by

estimated_liability. Search by borrower name or case title.

4. CASE DETAIL PAGE

Full case info, plus everything linked to it: all parties grouped by

role, all documents (with links to storage_path — these are external

source URLs, open in new tab), all liabilities (with the linked lender

name from parties), all assets.

5. DASHBOARD PAGE

Call the existing Postgres function via

supabase.rpc('dashboard_stats').single() to get: total_cases,

active_cases, total_liability, assets_at_risk,

upcoming_hearings_count. Show these as KPI cards. Below them, list

upcoming hearings (cases with next_hearing_date in the future,

soonest first).

Use React/TypeScript/Vite with shadcn/ui components, clean and

professional styling suitable for showing to law firms, NGOs, and

financial institutions. Row Level Security is enabled on all tables

restricting reads to authenticated users only — make sure all

Supabase queries run after login.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/50319866-3474-4ba0-b2d7-43a29190137c).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
