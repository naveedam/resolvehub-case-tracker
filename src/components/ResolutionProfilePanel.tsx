import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatDate } from "@/lib/cases";
import {
  CONFIDENCE_LABEL,
  currentObservations,
  currentValue,
  historyFor,
  resolutionProfileQueryOptions,
} from "@/lib/resolution-profile";
import type { CaseDetail, FieldObservation } from "@/lib/types";

const FIELD_LABELS: Record<string, string> = {
  estimated_liability: "Estimated liability",
  status: "Status",
  filing_date: "Filing date",
  next_hearing_date: "Next hearing",
  npa_date: "NPA date",
  outstanding_amount: "Outstanding amount",
  account_number: "Account number",
  loan_type: "Loan type",
  reserve_price: "Reserve price",
  auction_date: "Auction date",
  auction_status: "Auction status",
  description: "Description",
  possession_status: "Possession status",
};

const CONFIDENCE_TONE: Record<FieldObservation["confidence"], string> = {
  verified: "bg-success/12 text-success border-success/30",
  source_derived: "bg-secondary text-foreground border-border",
  inferred: "bg-warning/15 text-warning-foreground border-warning/40",
};

/** Renders nothing if the Phase 1 evidence tables genuinely have no rows
 * for this case yet (e.g. it hasn't been re-ingested) — this is additive
 * UI, not a replacement for the existing case detail sections above it.
 *
 * Deliberately NOT a suspense query: a Resolution Profile fetch failure
 * (permissions, network, anything) must never take down the rest of an
 * otherwise-working case page, and "no data" and "the query failed" are
 * different situations that need to be visibly different — silently
 * treating both as "render nothing" is what made this hard to diagnose
 * in the first place. */
export function ResolutionProfilePanel({ caseDetail }: { caseDetail: CaseDetail }) {
  const { data, error, isLoading } = useQuery(resolutionProfileQueryOptions(caseDetail));

  if (error) {
    console.error("[ResolutionProfilePanel] failed to load evidence data:", error);
    return (
      <Card className="mt-8 border-warning/40 bg-warning/5">
        <CardContent className="py-4 text-sm text-muted-foreground">
          Resolution profile is temporarily unavailable. (Check the browser console for details.)
        </CardContent>
      </Card>
    );
  }

  if (isLoading || !data) return null;

  const { observations, sourcesById, events, identifiers } = data;

  if (observations.length === 0 && events.length === 0 && identifiers.length === 0) {
    return null;
  }

  const current = currentObservations(observations);

  return (
    <Card className="mt-8 overflow-hidden">
      <CardHeader>
        <CardTitle className="font-serif text-xl">Resolution profile</CardTitle>
        <p className="text-sm text-muted-foreground">
          What we know about this case, where we learned it, and how it has changed over time.
        </p>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="current">
          <TabsList>
            <TabsTrigger value="current">Current values</TabsTrigger>
            <TabsTrigger value="timeline">Timeline ({events.length})</TabsTrigger>
            <TabsTrigger value="identifiers">Identifiers ({identifiers.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="current">
            {current.length === 0 ? (
              <p className="py-6 text-sm text-muted-foreground">No observed values yet.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Field</TableHead>
                    <TableHead>Value</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Confidence</TableHead>
                    <TableHead>Published</TableHead>
                    <TableHead>History</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {current.map((obs) => {
                    const history = historyFor(observations, obs);
                    const source = sourcesById[obs.source_id];
                    return (
                      <TableRow key={obs.id}>
                        <TableCell className="font-medium">
                          {FIELD_LABELS[obs.field_name] ?? obs.field_name}
                        </TableCell>
                        <TableCell className="tabular-nums">{currentValue(obs)}</TableCell>
                        <TableCell>{source?.name ?? "—"}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className={CONFIDENCE_TONE[obs.confidence]}>
                            {CONFIDENCE_LABEL[obs.confidence]}
                          </Badge>
                        </TableCell>
                        <TableCell>{formatDate(obs.published_at)}</TableCell>
                        <TableCell className="text-muted-foreground">
                          {history.length > 1 ? `${history.length} observations` : "First report"}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </TabsContent>

          <TabsContent value="timeline">
            {events.length === 0 ? (
              <p className="py-6 text-sm text-muted-foreground">No tracked changes yet.</p>
            ) : (
              <ul className="space-y-4 py-2">
                {events.map((event) => (
                  <li key={event.id} className="border-l-2 border-border pl-4">
                    <p className="text-xs tracking-wide text-muted-foreground uppercase">
                      {formatDate(event.event_date)}
                    </p>
                    <p className="text-sm font-medium">{event.description ?? event.event_type}</p>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>

          <TabsContent value="identifiers">
            {identifiers.length === 0 ? (
              <p className="py-6 text-sm text-muted-foreground">
                No authoritative identifiers (CIN, IBBI/NCLT reference, ...) linked yet.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Type</TableHead>
                    <TableHead>Value</TableHead>
                    <TableHead>Match method</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {identifiers.map((id) => (
                    <TableRow key={id.id}>
                      <TableCell className="font-medium">{id.identifier_type}</TableCell>
                      <TableCell className="tabular-nums">{id.identifier_value}</TableCell>
                      <TableCell className="capitalize text-muted-foreground">
                        {id.match_method}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
