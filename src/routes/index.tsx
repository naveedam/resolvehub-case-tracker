import { useMemo } from "react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  Briefcase,
  CalendarClock,
  FolderOpen,
  Gavel,
  Landmark,
  ShieldCheck,
} from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  casesQueryOptions,
  classifyTicketSize,
  formatCurrency,
  formatDate,
  TICKET_SIZE_LABELS,
  type TicketSize,
} from "@/lib/cases";

export const Route = createFileRoute("/")({
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(casesQueryOptions());
  },
  component: Dashboard,
});

const TICKET_SIZE_ORDER: TicketSize[] = ["small", "mid", "large", "unknown"];

function Dashboard() {
  const { data: cases } = useSuspenseQuery(casesQueryOptions());

  const pendingHearings = useMemo(
    () => cases.filter((c) => c.next_hearing_date).length,
    [cases],
  );

  const oaCases = useMemo(
    () => cases.filter((c) => c.case_type === "OA").length,
    [cases],
  );

  const saCases = useMemo(
    () => cases.filter((c) => c.case_type === "SA").length,
    [cases],
  );

  const kpis = [
    { label: "DRT Proceedings", value: String(cases.length), icon: FolderOpen },
    { label: "Pending Hearings", value: String(pendingHearings), icon: CalendarClock },
    { label: "OA Matters", value: String(oaCases), icon: Briefcase },
    { label: "SA Matters", value: String(saCases), icon: ShieldCheck },
    { label: "Last Hearing This Week", value: "12", icon: Gavel },
    { label: "Assets Under Recovery", value: "48", icon: Landmark },
  ];

  const ticketBuckets = useMemo(() => {
    const buckets: Record<TicketSize, { count: number; total: number }> = {
      small: { count: 0, total: 0 },
      mid: { count: 0, total: 0 },
      large: { count: 0, total: 0 },
      unknown: { count: 0, total: 0 },
    };

    for (const c of cases) {
      const bucket = classifyTicketSize(c.estimated_liability);
      buckets[bucket].count += 1;
      buckets[bucket].total += c.estimated_liability ?? 0;
    }

    return buckets;
  }, [cases]);

  const upcoming = useMemo(
    () =>
      [...cases]
        .filter((c) => c.next_hearing_date)
        .sort((a, b) => a.next_hearing_date!.localeCompare(b.next_hearing_date!))
        .slice(0, 10),
    [cases],
  );

  return (
    <>
      <PageHeader
        title="ResolveHub DRT Intelligence"
        description={`${cases.length} live proceedings across the DRT corpus.`}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
        {kpis.map((kpi) => (
          <Card key={kpi.label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {kpi.label}
              </CardTitle>
              <kpi.icon className="size-4 text-amber-600" />
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold">{kpi.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="mt-8">
        <CardHeader>
          <CardTitle>Liability by Ticket Size</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          {TICKET_SIZE_ORDER.map((size) => (
            <div key={size} className="rounded-lg border p-4">
              <p className="text-sm text-muted-foreground">
                {TICKET_SIZE_LABELS[size]}
              </p>
              <p className="mt-2 text-xl font-semibold">
                {formatCurrency(ticketBuckets[size].total)}
              </p>
              <p className="text-sm text-muted-foreground">
                {ticketBuckets[size].count} proceedings
              </p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="mt-8">
        <CardHeader>
          <CardTitle>Upcoming Hearings</CardTitle>
        </CardHeader>
        <CardContent className="divide-y p-0">
          {upcoming.length === 0 ? (
            <p className="p-6 text-muted-foreground">No hearings scheduled.</p>
          ) : (
            upcoming.map((c) => (
              <Link
                key={c.id}
                to="/cases/$caseId"
                params={{ caseId: c.id }}
                className="flex items-center justify-between p-4 hover:bg-muted/50"
              >
                <div>
                  <p className="font-medium">{c.display_title ?? c.title}</p>
                  <p className="text-sm text-muted-foreground">
                    {c.court_name} · {c.borrower_name ?? "—"}
                  </p>
                </div>
                <div className="text-sm font-medium">
                  {formatDate(c.next_hearing_date)}
                </div>
              </Link>
            ))
          )}
        </CardContent>
      </Card>
    </>
  );
}
