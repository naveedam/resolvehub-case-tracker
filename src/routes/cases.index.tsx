import { useMemo, useState } from "react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Search } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import {
  legacyCasesQueryOptions,
  casesQueryOptions,
  formatCurrency,
  formatDate,
} from "@/lib/cases";

export const Route = createFileRoute("/cases/")({
  loader: ({ context }) =>
    Promise.all([
      context.queryClient.ensureQueryData(legacyCasesQueryOptions()),
      context.queryClient.ensureQueryData(casesQueryOptions()),
    ]),
  component: CasesPage,
});

function CasesPage() {
  const [view, setView] = useState<"bank" | "drt">("bank");
  const [search, setSearch] = useState("");

  const { data: bankCases } = useSuspenseQuery(legacyCasesQueryOptions());
  const { data: drtCases } = useSuspenseQuery(casesQueryOptions());
  
  const bankRows = useMemo(() => {
  const term = search.toLowerCase()

  return bankCases.filter((c: any) => {
    const isBankCase = c.case_type === "SARFAESI"
const matches =
      c.title?.toLowerCase().includes(term) ||
      c.borrower_name?.toLowerCase().includes(term)
      return isBankCase && matches
  })
}, [bankCases, search])
  const drtRows = useMemo(() => {
  const term = search.toLowerCase();

  return drtCases.filter((c: any) => {
    const isDrtCase = c.case_type !== "SARFAESI";

    const matches =
      c.title?.toLowerCase().includes(term) ||
      c.case_reference?.toLowerCase().includes(term);

    return isDrtCase && matches;
  });
}, [drtCases, search]);

  return (
    <>
      <PageHeader
        title="Cases"
        description={
          view === "bank"
            ? `${bankRows.length.toLocaleString()} Bank SARFAESI cases`
            : `${drtRows.length.toLocaleString()} Live DRT proceedings`
        }
      />

      <div className="flex gap-2 mb-5">
        <Button
          variant={view === "bank" ? "default" : "outline"}
          onClick={() => setView("bank")}
        >
          Bank Cases ({bankRows.length.toLocaleString()})
        </Button>

        <Button
          variant={view === "drt" ? "default" : "outline"}
          onClick={() => setView("drt")}
        >
          DRT Proceedings ({drtRows.length.toLocaleString()})
        </Button>
      </div>

      <div className="relative mb-5">
        <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-9"
          placeholder={
            view === "bank"
              ? "Search borrower or bank case..."
              : "Search OA / SA or case reference..."
          }
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <Card className="overflow-hidden">
        <Table>
          <TableHeader>
            {view === "bank" ? (
              <TableRow>
                <TableHead>Borrower</TableHead>
                <TableHead>Case Title</TableHead>
                <TableHead className="text-right">Liability</TableHead>
              </TableRow>
            ) : (
              <TableRow>
                <TableHead>Case</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Next Hearing</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            )}
          </TableHeader>

          <TableBody>
            {view === "bank"
              ? bankRows.map((c: any) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-medium">
                      {c.borrower_name ?? "—"}
                    </TableCell>

                    <TableCell>
                      <Link
                        to="/cases/$caseId"
                        params={{ caseId: c.id }}
                        className="hover:underline"
                      >
                        {c.title}
                      </Link>
                    </TableCell>

                    <TableCell className="font-medium">
  <Link
    to="/cases/$caseId"
    params={{ caseId: c.id }}
    className="hover:underline"
  >
    {c.title}
  </Link>
</TableCell>

                    <TableCell>{c.case_type}</TableCell>

                    <TableCell>
                      {formatDate(c.next_hearing_date)}
                    </TableCell>

                    <TableCell>{c.status}</TableCell>
                  </TableRow>
                ))}
          </TableBody>
        </Table>
      </Card>
    </>
  );
}
