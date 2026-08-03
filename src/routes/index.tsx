import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { AlertTriangle, Briefcase, CalendarClock, FolderOpen, IndianRupee } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  dashboardStatsQueryOptions,
  formatCurrency,
  formatDate,
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
  },
  component: Dashboard,
  errorComponent: ({ error }) => (
    <p role="alert" className="text-sm text-destructive">
      {error.message}
    </p>
  ),
  notFoundComponent: () => <p className="text-sm text-muted-foreground">Nothing here.</p>,
});

function Dashboard() {
  const { data: stats } = useSuspenseQuery(dashboardStatsQueryOptions());
  const { data: hearings } = useSuspenseQuery(upcomingHearingsQueryOptions());

  const kpis = [
    { label: "Total cases", value: String(stats.total_cases), icon: FolderOpen },
    { label: "Active cases", value: String(stats.active_cases), icon: Briefcase },
    { label: "Total liability", value: formatCurrency(stats.total_liability), icon: IndianRupee },
    { label: "Assets at risk", value: String(stats.assets_at_risk), icon: AlertTriangle },
    {
      label: "Upcoming hearings",
      value: String(stats.upcoming_hearings_count),
      icon: CalendarClock,
    },
  ];

  return (
    <>
      <PageHeader title="Dashboard" description="Portfolio overview across all live matters." />

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
