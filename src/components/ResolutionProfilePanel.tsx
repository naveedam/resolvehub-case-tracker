import { useSuspenseQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { resolutionProfileQueryOptions } from "@/lib/resolution-profile";
import { formatCurrency, formatDate } from "@/lib/cases";

type Props = {
  caseDetail: any;
};

export function ResolutionProfilePanel({ caseDetail }: Props) {
  const { data: profile } = useSuspenseQuery(
    resolutionProfileQueryOptions(caseDetail),
  );

  // Prevent crashes for legacy bank cases
  const observations = profile?.observations ?? [];
  const timeline = profile?.timeline ?? [];
  const recommendations = profile?.recommendations ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Resolution Profile</CardTitle>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Observations */}
        <section>
          <h3 className="font-semibold mb-2">Key Observations</h3>

          {observations.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No observations available for this case.
            </p>
          ) : (
            <div className="space-y-2">
              {observations.map((o: any) => (
                <div
                  key={o.id}
                  className="rounded border p-3 text-sm"
                >
                  <div className="font-medium">{o.field_name}</div>
                  <div className="text-muted-foreground">
                    {o.value_text ??
                      o.value_numeric ??
                      formatDate(o.value_date)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Timeline */}
        <section>
          <h3 className="font-semibold mb-2">Timeline</h3>

          {timeline.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No timeline available.
            </p>
          ) : (
            <div className="space-y-2">
              {timeline.map((e: any) => (
                <div
                  key={e.id}
                  className="flex justify-between text-sm border-b pb-2"
                >
                  <span>{e.event_type}</span>
                  <span>{formatDate(e.event_date)}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Recommendations */}
        <section>
          <h3 className="font-semibold mb-2">Recommendations</h3>

          {recommendations.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No recommendations generated.
            </p>
          ) : (
            <ul className="list-disc pl-5 space-y-1 text-sm">
              {recommendations.map((r: any) => (
                <li key={r.id}>{r.text}</li>
              ))}
            </ul>
          )}
        </section>

        {/* Exposure */}
        <section>
          <h3 className="font-semibold mb-2">Exposure</h3>

          <div className="text-2xl font-bold">
            {formatCurrency(caseDetail.case.estimated_liability)}
          </div>
        </section>
      </CardContent>
    </Card>
  );
}
