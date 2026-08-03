import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link, notFound } from "@tanstack/react-router";
import { ArrowLeft, ExternalLink } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { caseDetailQueryOptions, formatCurrency, formatDate } from "@/lib/cases";
import { CASE_PARTY_ROLES } from "@/lib/types";

export const Route = createFileRoute("/cases/$caseId")({
  head: () => ({
    meta: [
      { title: "Case file — ResolveHub Case Tracking" },
      {
        name: "description",
        content:
          "Complete case file: parties by role, source documents, lender liabilities and secured assets.",
      },
      { property: "og:title", content: "Case file — ResolveHub Case Tracking" },
      {
        property: "og:description",
        content: "Parties, documents, liabilities and assets for a single distress matter.",
      },
    ],
  }),
  loader: async ({ context, params }) => {
    const detail = await context.queryClient.ensureQueryData(
      caseDetailQueryOptions(params.caseId),
    );
    if (!detail) throw notFound();
  },
  component: CaseDetailPage,
  errorComponent: ({ error }) => (
    <p role="alert" className="text-sm text-destructive">
      {error.message}
    </p>
  ),
  notFoundComponent: () => (
    <p className="text-sm text-muted-foreground">This case does not exist or was removed.</p>
  ),
});

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs tracking-wide text-muted-foreground uppercase">{label}</p>
      <div className="mt-1 text-sm font-medium">{value}</div>
    </div>
  );
}

function CaseDetailPage() {
  const { caseId } = Route.useParams();
  const { data } = useSuspenseQuery(caseDetailQueryOptions(caseId));
  if (!data) return null;
  const { case: c, parties, documents, liabilities, assets } = data;

  return (
    <>
      <Link
        to="/cases"
        className="mb-6 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> All cases
      </Link>

      <PageHeader title={c.title} description={c.summary ?? undefined} />

      <Card>
        <CardContent className="grid gap-6 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="Type" value={c.case_type ?? "—"} />
          <Field label="Status" value={<StatusBadge value={c.status} />} />
          <Field label="Court" value={c.court_name ?? "—"} />
          <Field label="Filed" value={formatDate(c.filing_date)} />
          <Field label="Next hearing" value={formatDate(c.next_hearing_date)} />
          <Field label="Est. liability" value={formatCurrency(c.estimated_liability)} />
        </CardContent>
      </Card>

      <div className="mt-8 grid gap-8 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-xl">Parties</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            {parties.length === 0 ? (
              <p className="text-sm text-muted-foreground">No parties linked.</p>
            ) : (
              CASE_PARTY_ROLES.filter((role) => parties.some((p) => p.role === role)).map(
                (role, index) => (
                  <div key={role}>
                    {index > 0 ? <Separator className="mb-5" /> : null}
                    <p className="text-xs tracking-wide text-muted-foreground uppercase">{role}</p>
                    <ul className="mt-2 space-y-1">
                      {parties
                        .filter((p) => p.role === role)
                        .map((p) => (
                          <li key={p.id} className="text-sm font-medium">
                            {p.party?.full_name ?? "Unknown party"}
                            {p.party?.party_type ? (
                              <span className="ml-2 text-xs font-normal text-muted-foreground">
                                {p.party.party_type}
                              </span>
                            ) : null}
                          </li>
                        ))}
                    </ul>
                  </div>
                ),
              )
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-xl">Documents</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {documents.length === 0 ? (
              <p className="text-sm text-muted-foreground">No documents on file.</p>
            ) : (
              documents.map((d) => (
                <a
                  key={d.id}
                  href={d.storage_path ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between gap-4 rounded-md border border-border px-4 py-3 transition-colors hover:bg-secondary"
                >
                  <span>
                    <span className="block text-sm font-medium">
                      {d.document_name ?? "Untitled document"}
                    </span>
                    <span className="text-xs text-muted-foreground">{d.document_type ?? "—"}</span>
                  </span>
                  <ExternalLink className="size-4 shrink-0 text-muted-foreground" />
                </a>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-8 overflow-hidden">
        <CardHeader>
          <CardTitle className="font-serif text-xl">Liabilities</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Lender</TableHead>
                <TableHead>Loan type</TableHead>
                <TableHead>Account</TableHead>
                <TableHead className="text-right">Outstanding</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {liabilities.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                    No liabilities recorded.
                  </TableCell>
                </TableRow>
              ) : (
                liabilities.map((l) => (
                  <TableRow key={l.id}>
                    <TableCell className="font-medium">{l.lender?.full_name ?? "—"}</TableCell>
                    <TableCell>{l.loan_type ?? "—"}</TableCell>
                    <TableCell className="tabular-nums">{l.account_number ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatCurrency(l.outstanding_amount)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card className="mt-8 overflow-hidden">
        <CardHeader>
          <CardTitle className="font-serif text-xl">Assets</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Auction date</TableHead>
                <TableHead>Auction status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assets.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                    No assets recorded.
                  </TableCell>
                </TableRow>
              ) : (
                assets.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">{a.asset_type ?? "—"}</TableCell>
                    <TableCell className="max-w-md">{a.description ?? "—"}</TableCell>
                    <TableCell>{formatDate(a.auction_date)}</TableCell>
                    <TableCell>
                      <StatusBadge value={a.auction_status} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}