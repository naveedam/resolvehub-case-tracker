import { useMemo, useState } from "react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Gavel, Search } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { casesQueryOptions, formatDate } from "@/lib/cases";

export const Route = createFileRoute("/cases/")({
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(casesQueryOptions());
  },
  component: CasesPage,
});

const ALL = "ALL";

export default function CasesPage() {
  const { data: cases } = useSuspenseQuery(casesQueryOptions());

  const [search, setSearch] = useState("");
  const [type, setType] = useState(ALL);
  const [status, setStatus] = useState(ALL);

  const rows = useMemo(() => {
    const term = search.toLowerCase().trim();

    return [...cases]
      .filter((c) => (type === ALL ? true : c.case_type === type))
      .filter((c) =>
        status === ALL
          ? true
          : (c.status ?? "").toLowerCase().includes(status.toLowerCase()),
      )
      .filter((c) =>
        term === ""
          ? true
          : (c.display_title ?? c.title).toLowerCase().includes(term) ||
            c.case_reference.toLowerCase().includes(term),
      )
      .sort((a, b) =>
        new Date(b.filing_date ?? 0).getTime() -
        new Date(a.filing_date ?? 0).getTime(),
      );
  }, [cases, search, type, status]);

  const oaCount = cases.filter((c) => c.case_type === "OA").length;
  const saCount = cases.filter((c) => c.case_type === "SA").length;

  return (
    <>
      <PageHeader
        title="DRT Proceedings"
        description={`${rows.length.toLocaleString()} proceedings across Bangalore DRT-I`}
      />

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <Card className="p-5">
          <div className="text-sm text-muted-foreground">Total Proceedings</div>
          <div className="text-3xl font-bold mt-2">{cases.length.toLocaleString()}</div>
        </Card>

        <Card className="p-5">
          <div className="text-sm text-muted-foreground">Original Applications</div>
          <div className="text-3xl font-bold mt-2">{oaCount}</div>
        </Card>

        <Card className="p-5">
          <div className="text-sm text-muted-foreground">Securitisation Applications</div>
          <div className="text-3xl font-bold mt-2">{saCount}</div>
        </Card>
      </div>

      <Card className="p-4 mb-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by bank, borrower or case reference"
              className="pl-9"
            />
          </div>

          <div className="flex gap-2">
            {["ALL", "OA", "SA"].map((t) => (
              <button
                key={t}
                onClick={() => setType(t)}
                className={`rounded-full px-4 py-2 text-sm border ${
                  type === t
                    ? "bg-black text-white dark:bg-white dark:text-black"
                    : "bg-background"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="flex gap-2">
            {["ALL", "Pending", "Disposed"].map((s) => (
              <button
                key={s}
                onClick={() => setStatus(s)}
                className={`rounded-full px-4 py-2 text-sm border ${
                  status === s
                    ? "bg-black text-white dark:bg-white dark:text-black"
                    : "bg-background"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </Card>

      <Card className="overflow-hidden p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Proceeding</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Filed</TableHead>
              <TableHead>Next Hearing</TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            {rows.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <Link
                    to="/cases/$caseId"
                    params={{ caseId: c.id }}
                    className="block hover:underline"
                  >
                    <div className="font-semibold">
                      {c.display_title ?? c.title}
                    </div>

                    <div className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                      <Gavel className="h-3 w-3" />
                      {c.case_reference}
                    </div>
                  </Link>
                </TableCell>

                <TableCell>
                  <span className="rounded-full bg-secondary px-3 py-1 text-xs">
                    {c.case_type}
                  </span>
                </TableCell>

                <TableCell>
                  <StatusBadge value={c.status} />
                </TableCell>

                <TableCell>{formatDate(c.filing_date)}</TableCell>

                <TableCell>{formatDate(c.next_hearing_date)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </>
  );
}
