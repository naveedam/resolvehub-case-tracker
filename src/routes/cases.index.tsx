import { useMemo, useState } from "react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, Search } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  casesQueryOptions,
  classifyTicketSize,
  formatCurrency,
  formatDate,
  TICKET_SIZE_LABELS,
  type TicketSize,
} from "@/lib/cases";

export const Route = createFileRoute("/cases/")({
  head: () => ({
    meta: [
      { title: "Cases — ResolveHub Case Tracking" },
      {
        name: "description",
        content:
          "Search, filter and sort every financial distress case by type, status, borrower and estimated liability.",
      },
      { property: "og:title", content: "Cases — ResolveHub Case Tracking" },
      {
        property: "og:description",
        content: "Every distress matter with borrower, court, hearing date and exposure.",
      },
    ],
  }),
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(casesQueryOptions());
  },
  component: CasesPage,
  errorComponent: ({ error }) => (
    <p role="alert" className="text-sm text-destructive">
      {error.message}
    </p>
  ),
  notFoundComponent: () => <p className="text-sm text-muted-foreground">No cases found.</p>,
});

const ALL = "__all__";
const TICKET_SIZE_ORDER: TicketSize[] = ["small", "mid", "large", "unknown"];

function CasesPage() {
  const { data: cases } = useSuspenseQuery(casesQueryOptions());
  const [search, setSearch] = useState("");
  const [caseType, setCaseType] = useState<string>(ALL);
  const [status, setStatus] = useState<string>(ALL);
  const [ticketSize, setTicketSize] = useState<string>(ALL);
  const [sortDesc, setSortDesc] = useState(true);

  const caseTypes = useMemo(
    () => Array.from(new Set(cases.map((c) => c.case_type).filter(Boolean) as string[])).sort(),
    [cases],
  );
  const statuses = useMemo(
    () => Array.from(new Set(cases.map((c) => c.status).filter(Boolean) as string[])).sort(),
    [cases],
  );

  const rows = useMemo(() => {
  const term = search.trim().toLowerCase();

  return cases
    .filter((c) => (caseType === ALL ? true : c.case_type === caseType))
    .filter((c) => (status === ALL ? true : c.status === status))
    .filter((c) =>
      ticketSize === ALL
        ? true
        : classifyTicketSize(c.estimated_liability) === ticketSize,
    )
    .filter((c) =>
      term
        ? (c.display_title ?? c.title).toLowerCase().includes(term) ||
          (c.borrower_name ?? "").toLowerCase().includes(term) ||
          c.case_reference.toLowerCase().includes(term)
        : true,
    )
    .sort((a, b) => {
      const diff = (a.estimated_liability ?? 0) - (b.estimated_liability ?? 0);
      return sortDesc ? -diff : diff;
    });
}, [cases, search, caseType, status, ticketSize, sortDesc]);
      )
      .sort((a, b) => {
        const diff = (a.estimated_liability ?? 0) - (b.estimated_liability ?? 0);
        return sortDesc ? -diff : diff;
      });
  }, [cases, search, caseType, status, ticketSize, sortDesc]);

  return (
    <>
      <PageHeader
        title="Cases"
        description={`${rows.length} of ${cases.length} matters shown.`}
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-64 flex-1">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by case title, borrower name or case reference"
            className="pl-9"
          />
        </div>
        <Select value={caseType} onValueChange={setCaseType}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Case type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All case types</SelectItem>
            {caseTypes.map((t) => (
              <SelectItem key={t} value={t}>
                {t}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            {statuses.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={ticketSize} onValueChange={setTicketSize}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Ticket size" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All ticket sizes</SelectItem>
            {TICKET_SIZE_ORDER.map((size) => (
              <SelectItem key={size} value={size}>
                {TICKET_SIZE_LABELS[size]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Case</TableHead>
              <TableHead>Borrower</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Court</TableHead>
              <TableHead>Next hearing</TableHead>
              <TableHead className="text-right">
                <button
                  type="button"
                  onClick={() => setSortDesc((v) => !v)}
                  className="inline-flex items-center gap-1 font-medium hover:text-foreground"
                >
                  Est. liability
                  {sortDesc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />}
                </button>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                  No cases match these filters.
                </TableCell>
              </TableRow>
            ) : (
              rows.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">
                    <Link to="/cases/$caseId" params={{ caseId: c.id }} className="hover:underline">
                      {c.display_title ?? c.title}
                    </Link>
                  </TableCell>
                  <TableCell>{c.borrower_name ?? "—"}</TableCell>
                  <TableCell>{c.case_type ?? "—"}</TableCell>
                  <TableCell>
                    <StatusBadge value={c.status} />
                  </TableCell>
                  <TableCell>{c.court_name ?? "—"}</TableCell>
                  <TableCell>{formatDate(c.next_hearing_date)}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatCurrency(c.estimated_liability)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>
    </>
  );
}
