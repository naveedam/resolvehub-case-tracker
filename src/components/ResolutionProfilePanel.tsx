import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
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
  findCurrent,
  historyFor,
  resolutionProfileQueryOptions,
} from "@/lib/resolution-profile";
import type { CaseDetail, FieldObservation, Source } from "@/lib/types";

const CONFIDENCE_TONE: Record<FieldObservation["confidence"], string> = {
  verified: "bg-success/12 text-success border-success/30",
  source_derived: "bg-secondary text-foreground border-border",
  inferred: "bg-warning/15 text-warning-foreground border-warning/40",
};

function ConfidenceBadge({ obs }: { obs: FieldObservation | undefined }) {
  if (!obs) return null;
  return (
    <Badge variant="outline" className={`text-xs ${CONFIDENCE_TONE[obs.confidence]}`}>
      {CONFIDENCE_LABEL[obs.confidence]}
    </Badge>
  );
}

function SourceLine({
  obs,
  sourcesById,
}: {
  obs: FieldObservation | undefined;
  sourcesById: Record<string, Source>;
}) {
  if (!obs) return null;
  const source = sourcesById[obs.source_id];
  return (
    <p className="mt-1 text-xs text-muted-foreground">
      {source?.name ?? "Unknown source"}
      {obs.published_at ? ` · ${formatDate(obs.published_at)}` : ""}
    </p>
  );
}

/** Renders nothing if the Phase 1 evidence tables genuinely have no rows
 * for this case yet — additive UI, not a replacement for the case
 * detail sections above it. Not a suspense query: a fetch failure here
 * must never take down the rest of an otherwise-working case page. */
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
  if (observations.length === 0 && events.length === 0 && identifiers.length === 0) return null;

  const current = currentObservations(observations);
  const get = (entityType: FieldObservation["entity_type"], field: string) =>
    findCurrent(observations, entityType, field);

  // --- current-value fields, once, reused across cards ---
  const status = get("case", "status");
  const filingDate = get("case", "filing_date");
  const nextHearing = get("case", "next_hearing_date");
  const npaDate = get("case", "npa_date");
  const estimatedLiability = get("case", "estimated_liability");
  const outstandingAmount = get("liability", "outstanding_amount");
  const loanType = get("liability", "loan_type");
  const accountNumber = get("liability", "account_number");
  const description = get("asset", "description");
  const assetClassification = get("asset", "asset_classification");
  const auctionStatus = get("asset", "auction_status");
  const auctionDate = get("asset", "auction_date");
  const possessionStatus = get("asset", "possession_status");
  const reservePrice = get("asset", "reserve_price");

  const liabilityHeadline = outstandingAmount ?? estimatedLiability;

  // --- evidence sources summary: which sources fed the values shown above ---
  const sourceCounts = new Map<string, number>();
  for (const obs of current)
    sourceCounts.set(obs.source_id, (sourceCounts.get(obs.source_id) ?? 0) + 1);
  const sourceSummaries = Array.from(sourceCounts.entries())
    .map(([sourceId, count]) => ({ source: sourcesById[sourceId], count }))
    .filter((s): s is { source: Source; count: number } => !!s.source)
    .sort((a, b) => b.count - a.count);

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
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
          </TabsList>

          {/* ---------- Current Values: KPI / intelligence cards ---------- */}
          <TabsContent value="current">
            <div className="grid grid-cols-1 gap-4 py-2 md:grid-cols-2">
              {/* Borrower Snapshot */}
              <Card className="shadow-none">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Borrower snapshot
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <p className="font-serif text-lg leading-tight">{caseDetail.case.title}</p>
                  <p className="text-xs text-muted-foreground">{caseDetail.case.case_reference}</p>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Badge variant="outline">
                      {caseDetail.case.case_type ?? "Case type unknown"}
                    </Badge>
                    {(status?.value_text ?? caseDetail.case.status) && (
                      <Badge variant="outline" className="capitalize">
                        {status?.value_text ?? caseDetail.case.status}
                      </Badge>
                    )}
                    <ConfidenceBadge obs={status} />
                  </div>
                  {(filingDate?.value_date ?? caseDetail.case.filing_date) && (
                    <p className="text-xs text-muted-foreground">
                      Filed {formatDate(filingDate?.value_date ?? caseDetail.case.filing_date)}
                    </p>
                  )}
                </CardContent>
              </Card>

              {/* Outstanding Liability */}
              <Card className="shadow-none">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Outstanding liability
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {liabilityHeadline ? (
                    <>
                      <p className="font-serif text-2xl tabular-nums">
                        {currentValue(liabilityHeadline)}
                      </p>
                      <div className="flex items-center gap-2">
                        <ConfidenceBadge obs={liabilityHeadline} />
                        {historyFor(observations, liabilityHeadline).length > 1 && (
                          <span className="text-xs text-muted-foreground">
                            {historyFor(observations, liabilityHeadline).length} observations over
                            time
                          </span>
                        )}
                      </div>
                      <SourceLine obs={liabilityHeadline} sourcesById={sourcesById} />
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No liability amount recorded yet.
                    </p>
                  )}
                  {(loanType || accountNumber) && (
                    <>
                      <Separator />
                      <div className="space-y-1 text-sm">
                        {loanType && <p>{loanType.value_text}</p>}
                        {accountNumber && (
                          <p className="text-muted-foreground">
                            Account: {accountNumber.value_text}
                          </p>
                        )}
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>

              {/* Asset Summary */}
              <Card className="shadow-none">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Asset summary
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {description || assetClassification ? (
                    <>
                      {description && (
                        <p className="text-sm leading-snug">{description.value_text}</p>
                      )}
                      <div className="flex flex-wrap gap-2">
                        {assetClassification && (
                          <Badge variant="outline">{assetClassification.value_text}</Badge>
                        )}
                        {reservePrice && (
                          <Badge variant="outline" className="tabular-nums">
                            Reserve {currentValue(reservePrice)}
                          </Badge>
                        )}
                      </div>
                      <SourceLine
                        obs={description ?? assetClassification}
                        sourcesById={sourcesById}
                      />
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">No asset details recorded yet.</p>
                  )}
                </CardContent>
              </Card>

              {/* Recovery Stage */}
              <Card className="shadow-none">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Recovery stage
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {auctionStatus || possessionStatus ? (
                    <div className="flex flex-wrap items-center gap-2">
                      {auctionStatus && (
                        <Badge variant="outline" className="capitalize">
                          Auction: {auctionStatus.value_text}
                        </Badge>
                      )}
                      {possessionStatus && (
                        <Badge variant="outline" className="capitalize">
                          Possession: {possessionStatus.value_text}
                        </Badge>
                      )}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No recovery-stage signal recorded yet.
                    </p>
                  )}
                  <div className="space-y-1 text-xs text-muted-foreground">
                    {auctionDate && <p>Auction date: {formatDate(auctionDate.value_date)}</p>}
                    {nextHearing && <p>Next hearing: {formatDate(nextHearing.value_date)}</p>}
                    {npaDate && <p>NPA date: {formatDate(npaDate.value_date)}</p>}
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* ---------- Evidence Timeline ---------- */}
          <TabsContent value="timeline">
            <Card className="mt-2 shadow-none">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  Evidence timeline
                </CardTitle>
              </CardHeader>
              <CardContent>
                {events.length === 0 ? (
                  <p className="py-4 text-sm text-muted-foreground">No tracked changes yet.</p>
                ) : (
                  <ul className="space-y-4">
                    {events.map((event) => (
                      <li key={event.id} className="border-l-2 border-border pl-4">
                        <p className="text-xs tracking-wide text-muted-foreground uppercase">
                          {formatDate(event.event_date)}
                        </p>
                        <p className="text-sm font-medium">
                          {event.description ?? event.event_type}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ---------- Evidence: sources + identifiers ---------- */}
          <TabsContent value="evidence">
            <div className="mt-2 grid grid-cols-1 gap-4 md:grid-cols-2">
              <Card className="shadow-none">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Evidence sources
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {sourceSummaries.length === 0 ? (
                    <p className="py-4 text-sm text-muted-foreground">No sourced values yet.</p>
                  ) : (
                    <ul className="space-y-3">
                      {sourceSummaries.map(({ source, count }) => (
                        <li key={source.id} className="flex items-center justify-between">
                          <div>
                            <p className="text-sm font-medium">{source.full_name}</p>
                            <p className="text-xs capitalize text-muted-foreground">
                              {source.source_type}
                            </p>
                          </div>
                          <Badge variant="outline">
                            {count} field{count === 1 ? "" : "s"}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>

              <Card className="shadow-none">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    Identifiers
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {identifiers.length === 0 ? (
                    <p className="py-4 text-sm text-muted-foreground">
                      No authoritative identifiers (CIN, IBBI/NCLT reference, ...) linked yet.
                    </p>
                  ) : (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Type</TableHead>
                          <TableHead>Value</TableHead>
                          <TableHead>Match</TableHead>
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
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
