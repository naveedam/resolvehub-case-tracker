import { useState } from "react";

import { useQuery } from "@tanstack/react-query";
import {
  Banknote,
  Check,
  ChevronDown,
  FileText,
  Gavel,
  Home,
  Scale,
  ShieldCheck,
  Sparkles,
  User,
} from "lucide-react";

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
  findCurrent,
  historyFor,
  resolutionProfileQueryOptions,
} from "@/lib/resolution-profile";
import type { CaseDetail, FieldObservation, Source } from "@/lib/types";

// ResolveHub brand accent — deep teal / ivory / slate. Scoped to this
// component only (arbitrary Tailwind values, not a global theme change)
// so the rest of the app keeps its existing IBM Plex / blue-grey chrome.
const TEAL = "#0F4C46";
const TEAL_DARK = "#0B3B37";
const IVORY = "#FAF8F3";

const CONFIDENCE_TONE: Record<FieldObservation["confidence"], string> = {
  verified: "bg-success/12 text-success border-success/30",
  source_derived: "bg-slate-100 text-slate-700 border-slate-200",
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

function SourceBadge({
  obs,
  sourcesById,
}: {
  obs: FieldObservation | undefined;
  sourcesById: Record<string, Source>;
}) {
  if (!obs) return null;
  const source = sourcesById[obs.source_id];
  if (!source) return null;
  return (
    <Badge variant="outline" className="border-slate-200 bg-white text-xs text-slate-600">
      {source.name}
    </Badge>
  );
}

function KpiCard({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ElementType;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Card
      className="overflow-hidden border-t-4 shadow-none"
      style={{ borderTopColor: TEAL, backgroundColor: IVORY }}
    >
      <CardContent className="space-y-2 pt-5">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500">
          <Icon className="h-3.5 w-3.5" style={{ color: TEAL }} />
          {label}
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

// Recovery journey — inferred from which signals actually exist on the
// case, not a fabricated score. Every SARFAESI case starts with a
// notice; possession/auction/DRT stages light up only when their
// underlying field has been observed.
type Stage = "notice" | "possession" | "auction" | "drt";
const STAGES: { key: Stage; label: string; icon: React.ElementType }[] = [
  { key: "notice", label: "Notice", icon: FileText },
  { key: "possession", label: "Possession", icon: Home },
  { key: "auction", label: "Auction", icon: Gavel },
  { key: "drt", label: "DRT / NCLT", icon: Scale },
];

function inferStageIndex(opts: {
  hasAuction: boolean;
  hasPossession: boolean;
  isLegalProceeding: boolean;
}): number {
  if (opts.isLegalProceeding) return 3;
  if (opts.hasAuction) return 2;
  if (opts.hasPossession) return 1;
  return 0;
}

function RecoveryJourney({ currentIndex }: { currentIndex: number }) {
  return (
    <div className="flex items-center">
      {STAGES.map((stage, i) => {
        const done = i < currentIndex;
        const active = i === currentIndex;
        const Icon = stage.icon;
        return (
          <div key={stage.key} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={`flex h-9 w-9 items-center justify-center rounded-full border-2 transition-colors ${
                  active
                    ? "text-white"
                    : done
                      ? "border-transparent bg-slate-100 text-slate-500"
                      : "border-slate-200 bg-white text-slate-300"
                }`}
                style={active ? { backgroundColor: TEAL, borderColor: TEAL } : undefined}
              >
                {done ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
              </div>
              <span
                className={`text-xs font-medium ${active ? "" : done ? "text-slate-500" : "text-slate-400"}`}
                style={active ? { color: TEAL_DARK } : undefined}
              >
                {stage.label}
              </span>
            </div>
            {i < STAGES.length - 1 && (
              <div
                className="mx-2 h-0.5 flex-1"
                style={{ backgroundColor: i < currentIndex ? TEAL : "#e2e8f0" }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Renders nothing if the Phase 1 evidence tables genuinely have no rows
 * for this case yet — additive UI, not a replacement for the case
 * detail sections above it. Not a suspense query: a fetch failure here
 * must never take down the rest of an otherwise-working case page. */
export function ResolutionProfilePanel({ caseDetail }: { caseDetail: CaseDetail }) {
  const { data, error, isLoading } = useQuery(resolutionProfileQueryOptions(caseDetail));
  const [scheduleOpen, setScheduleOpen] = useState(false);

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
  const stageIndex = inferStageIndex({
    hasAuction: !!auctionStatus || !!auctionDate,
    hasPossession: !!possessionStatus,
    isLegalProceeding:
      (caseDetail.case.case_type ?? "").toUpperCase().includes("DRT") ||
      (caseDetail.case.case_type ?? "").toUpperCase().includes("NCLT"),
  });

  // The subtitle (KPI card AND the journey caption below the stepper)
  // must always describe the SAME stage stageIndex picked for the
  // highlighted step — not whichever field happens to be non-null
  // first. auction_date and possession_status can both legitimately
  // exist at once (an asset can be possessed AND now scheduled for
  // auction), so a generic fallback chain would silently borrow text
  // from an earlier stage instead of the one actually shown as active.
  const stageSubtitle = ((): string => {
    switch (stageIndex) {
      case 3:
        return caseDetail.case.status ?? "Legal proceeding";
      case 2: {
        // Legacy assets.auction_status occasionally contains "possessed"
        // rather than a genuine auction-progress value (a vocabulary
        // collision from the source data, not a fallback bug — there is
        // no reference to possessionStatus anywhere in this branch).
        // Showing "Auction: possessed" verbatim is misleading regardless
        // of why the column holds that value, so treat it as
        // uninformative for the Auction stage specifically.
        const text = auctionStatus?.value_text?.trim();
        const isPossessionWordedValue = text?.toLowerCase() === "possessed";
        if (text && !isPossessionWordedValue) return text;
        return auctionDate ? `Scheduled ${formatDate(auctionDate.value_date)}` : "Auction pending";
      }
      case 1:
        return possessionStatus?.value_text ?? "Possession taken";
      default:
        return caseDetail.case.status ?? "Notice issued";
    }
  })();

  const assetSummarySentence = [description?.value_text, assetClassification?.value_text]
    .filter(Boolean)
    .join(" — ");
  const hasLegalSchedule = !!(
    description ||
    assetClassification ||
    auctionDate ||
    auctionStatus ||
    possessionStatus ||
    reservePrice
  );

  // Evidence tab: group current observations by source, not a flat row-per-field table.
  const bySource = new Map<string, FieldObservation[]>();
  for (const obs of current) {
    const list = bySource.get(obs.source_id) ?? [];
    list.push(obs);
    bySource.set(obs.source_id, list);
  }
  const sourceGroups = Array.from(bySource.entries())
    .map(([sourceId, obs]) => ({ source: sourcesById[sourceId], obs }))
    .filter((g): g is { source: Source; obs: FieldObservation[] } => !!g.source)
    .sort((a, b) => b.obs.length - a.obs.length);

  const hasTimeline = events.length > 0;

  const evidenceContent = (
    <>
      <p className="mb-3 mt-2 text-xs text-slate-500">
        {sourceGroups.length === 0
          ? "No sourced values yet."
          : `Current values grouped by the ${sourceGroups.length} source${sourceGroups.length === 1 ? "" : "s"} that reported them.`}
      </p>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {sourceGroups.map(({ source, obs }) => (
          <Card key={source.id} className="shadow-none">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-medium text-slate-700">
                  {source.full_name}
                </CardTitle>
                <Badge variant="outline" className="capitalize text-slate-500">
                  {source.source_type}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="divide-y divide-slate-100">
              {obs.map((o) => (
                <div
                  key={o.id}
                  className="flex items-center justify-between py-1.5 text-sm first:pt-0 last:pb-0"
                >
                  <span className="capitalize text-slate-500">
                    {o.field_name.replace(/_/g, " ")}
                  </span>
                  <span className="flex items-center gap-2 font-medium text-slate-800">
                    {currentValue(o)}
                    {historyFor(observations, o).length > 1 && (
                      <span className="text-xs font-normal text-slate-400">
                        ({historyFor(observations, o).length}×)
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}

        <Card className="shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-700">Identifiers</CardTitle>
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
                      <TableCell className="font-medium capitalize">
                        {id.identifier_type.replace(/_/g, " ")}
                      </TableCell>
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
    </>
  );

  return (
    <Card className="mt-8 overflow-hidden">
      <CardHeader>
        <CardTitle className="text-xl font-semibold" style={{ color: TEAL_DARK }}>
          Resolution profile
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          What we know about this case, where we learned it, and how it has changed over time.
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* ---------- Executive snapshot: 4 KPI cards, 5-second scan ---------- */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <KpiCard icon={Banknote} label="Outstanding liability">
            {liabilityHeadline ? (
              <>
                <p className="text-2xl font-bold tabular-nums" style={{ color: TEAL_DARK }}>
                  {currentValue(liabilityHeadline)}
                </p>
                <ConfidenceBadge obs={liabilityHeadline} />
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Not yet recorded</p>
            )}
          </KpiCard>

          <KpiCard icon={ShieldCheck} label="Secured asset">
            {assetClassification || description ? (
              <>
                <p className="text-sm font-semibold leading-snug text-slate-800">
                  {assetClassification?.value_text ?? "Asset on record"}
                </p>
                {reservePrice && (
                  <p className="text-xs tabular-nums text-slate-500">
                    Reserve {currentValue(reservePrice)}
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Not yet recorded</p>
            )}
          </KpiCard>

          <KpiCard icon={Gavel} label="Recovery stage">
            <p className="text-sm font-semibold" style={{ color: TEAL_DARK }}>
              {STAGES[stageIndex]?.label ?? "Notice"}
            </p>
            <p className="text-xs text-slate-500">{stageSubtitle}</p>
          </KpiCard>

          <KpiCard icon={User} label="Borrower">
            <p className="text-sm font-semibold leading-snug text-slate-800">
              {caseDetail.case.title}
            </p>
            {caseDetail.case.case_type && (
              <p className="text-xs text-slate-500">{caseDetail.case.case_type}</p>
            )}
          </KpiCard>
        </div>

        {/* ---------- Recovery journey ---------- */}
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <p className="mb-4 text-xs font-medium uppercase tracking-wide text-slate-500">
            Recovery journey{" "}
            <span className="normal-case text-slate-400">— inferred from available signals</span>
          </p>
          <RecoveryJourney currentIndex={stageIndex} />
          <p className="mt-4 text-sm font-medium" style={{ color: TEAL_DARK }}>
            {STAGES[stageIndex]?.label ?? "Notice"}:{" "}
            <span className="font-normal text-slate-600">{stageSubtitle}</span>
          </p>
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
            {npaDate && <span>NPA: {formatDate(npaDate.value_date)}</span>}
            {auctionDate && <span>Auction date: {formatDate(auctionDate.value_date)}</span>}
            {nextHearing && <span>Next hearing: {formatDate(nextHearing.value_date)}</span>}
            {filingDate && <span>Filed: {formatDate(filingDate.value_date)}</span>}
          </div>
        </div>

        {/* ---------- Asset Intelligence ---------- */}
        <Card className="border-slate-200 shadow-none">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-slate-600">Asset intelligence</CardTitle>
          </CardHeader>
          <CardContent>
            {hasLegalSchedule ? (
              <div>
                <p className="line-clamp-4 text-sm leading-relaxed text-slate-700">
                  {assetSummarySentence || "Asset details recorded; see full schedule below."}
                </p>
                <div className="mt-2">
                  <SourceBadge obs={description ?? assetClassification} sourcesById={sourcesById} />
                </div>
                <button
                  type="button"
                  aria-expanded={scheduleOpen}
                  onClick={() => setScheduleOpen((v) => !v)}
                  className="mt-3 flex items-center gap-1 text-xs font-medium hover:underline"
                  style={{ color: TEAL }}
                >
                  <ChevronDown
                    className={`h-3.5 w-3.5 transition-transform ${scheduleOpen ? "rotate-180" : ""}`}
                  />
                  {scheduleOpen ? "Hide" : "View"} complete legal schedule
                </button>
                {/* Plain conditional rendering, not Radix's CollapsibleContent —
                    when scheduleOpen is false this subtree does not exist in the
                    DOM at all, no CSS-hiding involved. */}
                {scheduleOpen && (
                  <div className="mt-4 space-y-3 rounded-md border border-slate-100 bg-slate-50/60 p-4 text-sm">
                    {description && (
                      <p className="leading-relaxed text-slate-700">{description.value_text}</p>
                    )}
                    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
                      {assetClassification && (
                        <div className="flex justify-between gap-2 sm:block">
                          <dt className="text-slate-500">Classification</dt>
                          <dd className="font-medium text-slate-700">
                            {assetClassification.value_text}
                          </dd>
                        </div>
                      )}
                      {possessionStatus && (
                        <div className="flex justify-between gap-2 sm:block">
                          <dt className="text-slate-500">Possession</dt>
                          <dd className="font-medium text-slate-700">
                            {possessionStatus.value_text}
                          </dd>
                        </div>
                      )}
                      {auctionStatus && (
                        <div className="flex justify-between gap-2 sm:block">
                          <dt className="text-slate-500">Auction status</dt>
                          <dd className="font-medium text-slate-700">{auctionStatus.value_text}</dd>
                        </div>
                      )}
                      {auctionDate && (
                        <div className="flex justify-between gap-2 sm:block">
                          <dt className="text-slate-500">Auction date</dt>
                          <dd className="font-medium text-slate-700">
                            {formatDate(auctionDate.value_date)}
                          </dd>
                        </div>
                      )}
                      {reservePrice && (
                        <div className="flex justify-between gap-2 sm:block">
                          <dt className="text-slate-500">Reserve price</dt>
                          <dd className="font-medium text-slate-700">
                            {currentValue(reservePrice)}
                          </dd>
                        </div>
                      )}
                      {(loanType || accountNumber) && (
                        <div className="flex justify-between gap-2 sm:block">
                          <dt className="text-slate-500">Loan</dt>
                          <dd className="font-medium text-slate-700">
                            {[loanType?.value_text, accountNumber?.value_text]
                              .filter(Boolean)
                              .join(" · ")}
                          </dd>
                        </div>
                      )}
                    </dl>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No asset details recorded yet.</p>
            )}
          </CardContent>
        </Card>

        {/* ---------- ResolveHub Insight — reserved for future AI ---------- */}
        <Card className="border-dashed border-slate-300 bg-slate-50/60 shadow-none">
          <CardContent className="flex items-center gap-3 py-5">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-slate-200">
              <Sparkles className="h-4 w-4 text-slate-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-slate-600">ResolveHub Insight</p>
              <p className="text-xs text-slate-500">
                AI-generated resolution guidance for this case isn't available yet — reserved for a
                future release.
              </p>
            </div>
          </CardContent>
        </Card>

        {/* ---------- Timeline / Evidence ---------- */}
        {hasTimeline ? (
          <Tabs defaultValue="timeline">
            <TabsList>
              <TabsTrigger value="timeline">Timeline ({events.length})</TabsTrigger>
              <TabsTrigger value="evidence">Evidence ({sourceGroups.length})</TabsTrigger>
            </TabsList>

            <TabsContent value="timeline">
              <ol className="relative mt-4 space-y-5 border-l-2 border-slate-200 pl-6">
                {events.map((event) => {
                  const eventSource = event.source_id ? sourcesById[event.source_id] : undefined;
                  return (
                    <li key={event.id} className="relative">
                      <span
                        className="absolute -left-[31px] top-1 flex h-3.5 w-3.5 items-center justify-center rounded-full ring-4 ring-white"
                        style={{ backgroundColor: TEAL }}
                      />
                      <div className="rounded-md border border-slate-100 bg-white p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
                            {formatDate(event.event_date)}
                          </span>
                          {eventSource && (
                            <Badge
                              variant="outline"
                              className="border-slate-200 text-xs text-slate-600"
                            >
                              {eventSource.name}
                            </Badge>
                          )}
                        </div>
                        <p className="mt-1 text-sm font-medium text-slate-800">
                          {event.description ?? event.event_type}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </TabsContent>

            <TabsContent value="evidence">{evidenceContent}</TabsContent>
          </Tabs>
        ) : (
          // No timeline events at all: skip the tab chrome entirely
          // rather than showing a single-item tab list or a "No tracked
          // changes yet" placeholder — just the Evidence content.
          <div>
            <p className="mb-3 text-xs font-medium uppercase tracking-wide text-slate-500">
              Evidence ({sourceGroups.length})
            </p>
            {evidenceContent}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
