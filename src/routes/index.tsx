import { useMemo } from "react";
import { queryOptions, useSuspenseQuery } from "@tanstack/react-query";
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
  formatDate,
} from "@/lib/cases";
import { supabase } from "@/lib/supabase";

const dashboardCountsQuery = queryOptions({
  queryKey: ["dashboard-counts"],
  queryFn: async () => {
    const [
      { count: bankCases, error: bankErr },
      { count: drtProfiles, error: drtErr },
    ] = await Promise.all([
      supabase
        .from("cases")
        .select("*", { count: "exact", head: true }),
      supabase
        .from("drt_profiles")
        .select("*", { count: "exact", head: true }),
    ]);

    if (bankErr) throw bankErr;
    if (drtErr) throw drtErr;

    return {
      bankCases: bankCases ?? 0,
      drtProfiles: drtProfiles ?? 0,
      totalCases: (bankCases ?? 0) + (drtProfiles ?? 0),
    };
  },
});

export const Route = createFileRoute("/")({
  loader: ({ context }) => {
    context.queryClient.ensureQueryData(dashboardCountsQuery);
    context.queryClient.ensureQueryData(casesQueryOptions());
  },
  component: Dashboard,
});

function Dashboard() {
  const { data: counts } = useSuspenseQuery(dashboardCountsQuery);
  const { data: drtCases } = useSuspenseQuery(casesQueryOptions());

  const upcomingHearings = useMemo(
    () =>
      drtCases
        .filter((c) => c.next_hearing_date)
        .sort((a, b) =>
          a.next_hearing_date!.localeCompare(b.next_hearing_date!),
        )
        .slice(0, 8),
    [drtCases],
  );

  const oaCount = useMemo(
    () => drtCases.filter((c) => c.case_type === "OA").length,
    [drtCases],
  );

  const saCount = useMemo(
    () => drtCases.filter((c) => c.case_type === "SA").length,
    [drtCases],
  );

  const kpis = [
    {
      label: "Total Cases",
      value: counts.totalCases.toLocaleString("en-IN"),
      icon: FolderOpen,
    },
    {
      label: "Bank Ingestion Cases",
      value: counts.bankCases.toLocaleString("en-IN"),
      icon: Landmark,
    },
    {
      label: "DRT Ingestion Cases",
      value: counts.drtProfiles.toLocaleString("en-IN"),
      icon: ShieldCheck,
    },
    {
      label: "OA Proceedings",
      value: oaCount.toLocaleString("en-IN"),
      icon: Briefcase,
    },
    {
      label: "SA Proceedings",
      value: saCount.toLocaleString("en-IN"),
      icon: Gavel,
    },
    {
      label: "Upcoming Hearings",
      value: upcomingHearings.length.toString(),
      icon: CalendarClock,
    },
  ];

  return (
    <>
      <PageHeader
        title="ResolveHub Intelligence"
        description="Unified litigation intelligence across Bank SARFAESI and DRT proceedings."
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
              <div className="text-3xl font-bold">{kpi.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="mt-8">
        <CardHeader>
          <CardTitle>Upcoming DRT Hearings</CardTitle>
        </CardHeader>
        <CardContent className="divide-y p-0">
          {upcomingHearings.length === 0 ? (
            <p className="p-6 text-muted-foreground">
              No hearings currently scheduled.
            </p>
          ) : (
            upcomingHearings.map((c) => (
              <Link
                key={c.id}
                to="/cases/$caseId"
                params={{ caseId: c.id }}
                className="flex items-center justify-between p-4 hover:bg-muted/50"
              >
                <div>
                  <p className="font-medium">{c.title}</p>
                  <p className="text-sm text-muted-foreground">
                    {c.case_reference} · {c.court_name}
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
