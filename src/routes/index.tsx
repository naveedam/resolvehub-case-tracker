import { useMemo } from "react";
import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import {
  FolderOpen,
  Landmark,
  Scale,
  ShieldCheck,
  CalendarClock,
  IndianRupee,
} from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  dashboardStatsQueryOptions,
  upcomingHearingsQueryOptions,
  legacyCasesQueryOptions,
  drtProfilesQueryOptions,
  formatCurrency,
} from "@/lib/cases";
export const Route = createFileRoute("/")({
  loader: ({ context }) => {
    return Promise.all([
      context.queryClient.ensureQueryData(dashboardStatsQueryOptions()),
      context.queryClient.ensureQueryData(upcomingHearingsQueryOptions()),
      context.queryClient.ensureQueryData(legacyCasesQueryOptions()),
      context.queryClient.ensureQueryData(drtProfilesQueryOptions()),
    ]);
  },
  component: Dashboard,
  errorComponent: ({ error }) => (
    <div className="p-8 text-red-600">
      <h2 className="text-lg font-bold">Dashboard Error</h2>
      <pre className="mt-2 text-xs whitespace-pre-wrap">
        {String(error.message)}
      </pre>
    </div>
  ),
});

function Dashboard() {
  const { data: drtCases } = useSuspenseQuery(casesQueryOptions());
  const { data: hearings } = useSuspenseQuery(upcomingHearingsQueryOptions());
  const { data: bankCases } = useSuspenseQuery(legacyCasesQueryOptions());
  const { data: drtProfiles } = useSuspenseQuery(drtProfilesQueryOptions());

  const totalExposure = useMemo(
    () =>
      bankCases.reduce(
        (sum, c) => sum + (c.estimated_liability ?? 0),
        0,
      ),
    [bankCases],
  );

  const kpis = [
    {
      label: "Total Cases",
      value: (bankCases.length + drtProfiles.length).toLocaleString(),
      icon: FolderOpen,
    },
    {
      label: "Bank Ingestion Cases",
      value: bankCases.length.toLocaleString(),
      icon: Landmark,
    },
    {
      label: "DRT Ingestion Cases",
      value: drtProfiles.length.toLocaleString(),
      icon: ShieldCheck,
    },
        {
      label: "Live DRT Proceedings",
      value: stats.total_cases.toLocaleString(),
      icon: Scale,
    },
    {
      label: "Upcoming Hearings",
      value: hearings.length.toString(),
      icon: CalendarClock,
    },
    {
      label: "Total Exposure",
      value: formatCurrency(totalExposure),
      icon: IndianRupee,
    },
  ];

  return (
    <>
      <PageHeader
        title="ResolveHub Intelligence"
        description="Unified litigation intelligence across Bank SARFAESI and DRT proceedings."
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {kpis.map((kpi) => (
          <Card key={kpi.label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm text-muted-foreground">
                {kpi.label}
              </CardTitle>
              <kpi.icon className="h-4 w-4 text-orange-600" />
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold">{kpi.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}
