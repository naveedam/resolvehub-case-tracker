import { useMemo } from "react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { AlertTriangle, Briefcase, CalendarClock, FolderOpen, IndianRupee } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  casesQueryOptions,
  classifyTicketSize,
  dashboardStatsQueryOptions,
  formatCurrency,
  formatDate,
  TICKET_SIZE_LABELS,
  type TicketSize,
  upcomingHearingsQueryOptions,
} from "@/lib/cases";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Dashboard — ResolveHub Case Tracking" },
      {
        name: "description",
        content:
          "Portfolio-wide view of financial distress cases: total liability, active matters, assets at risk and upcoming hearings.",
      },
      { property: "og:title", content: "Dashboard — ResolveHub Case Tracking" },
      {
        property: "og:description",
        content: "Live KPIs and upcoming hearings across every financial distress case.",
      },
    ],
  }),
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(dashboardStatsQueryOptions());
    context.queryClient.ensureQueryData(upcomingHearingsQueryOptions());
    context.queryClient.ensureQueryData(casesQueryOptions());
  },
  component: Dashboard,
  errorComponent: ({ error }) => (
    <p role="alert" className="text-sm text-destructive">
      {error.message}
    </p>
  ),
  notFoundComponent: () => <p className="text-sm text-muted-foreground">Nothing here.</p>,
});

const TICKET_SIZE_ORDER: TicketSize[] = ["small", "mid", "large", "unknown"];

function Dashboard() {
  const { data: stats } = useSuspenseQuery(dashboardStatsQueryOptions());
  const { data: hearings } = useSuspenseQuery(upcomingHearingsQueryOptions());
  const { data: cases } = useSuspenseQuery(casesQueryOptions());

  const kpis = [
  { label: "DRT Cases", value: String(stats.total_cases), icon: FolderOpen },
  { label: "Pending Hearings", value: String(stats.upcoming_hearings_count), icon: CalendarClock },
  { label: "OA Matters", value: String(cases.filter(c => c.case_type === "OA").length), icon: Briefcase },
  { label: "SA Matters", value: String(cases.filter(c => c.case_type === "SA").length), icon: ShieldCheck },
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

  return (
    <>
      <PageHeader
  title="ResolveHub DRT Intelligence"
  description="Live litigation portfolio across DRT Bangalore."
/>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {kpis.map((kpi) => (
          <Card key={kpi.label}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {kpi.label}
              </CardTitle>
              <kpi.icon className="size-4 text-accent" />
            </CardHeader>
            <CardContent>
              <p className="font-serif text-2xl">{kpi.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="mt-10">
        <CardHeader>
          <CardTitle className="font-serif text-xl">Liability by ticket size</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {TICKET_SIZE_ORDER.map((size) => (
            <div key={size} className="rounded-lg border border-border p-4">
              <p className="text-sm font-medium text-muted-foreground">
                {TICKET_SIZE_LABELS[size]}
              </p>
              <p className="mt-1 font-serif text-xl">{formatCurrency(ticketBuckets[size].total)}</p>
              <p className="text-sm text-muted-foreground">{ticketBuckets[size].count} cases</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card className="mt-10">
        <CardHeader>
          <CardTitle className="font-serif text-xl">Upcoming hearings</CardTitle>
        </CardHeader>
        <CardContent className="divide-y divide-border p-0">
          {hearings.length === 0 ? (
            <p className="px-6 py-8 text-sm text-muted-foreground">No hearings scheduled.</p>
          ) : (
            hearings.map((c) => (
              <Link
                key={c.id}
                to="/cases/$caseId"
                params={{ caseId: c.id }}
                className="flex flex-wrap items-center justify-between gap-2 px-6 py-4 transition-colors hover:bg-secondary"
              >
                <div>
                  <p className="font-medium">{c.title}</p>
                  <p className="text-sm text-muted-foreground">
                    {c.court_name ?? "Court not set"} · {c.borrower_name ?? "No borrower linked"}
                  </p>
                </div>
                <p className="text-sm font-medium">{formatDate(c.next_hearing_date)}</p>
              </Link>
            ))
          )}
        </CardContent>
      </Card>
    </>
  );
}
