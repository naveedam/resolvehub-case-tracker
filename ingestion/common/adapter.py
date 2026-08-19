"""The one interface every ResolveHub source implements.

Deliberately smaller than a generic discover/fetch/parse/validate
pipeline: SBI and Canara's actual scraping shapes (paginated HTML +
per-notice PDFs vs. one master PDF's table rows) are different enough
that forcing them through identical discover/fetch/parse steps would
mean rewriting working extraction code to fit the abstraction — which
is exactly what we're not doing. Each adapter keeps its own
source-specific walk (pages, PDFs, table rows) and is responsible only
for yielding NormalizedRecord objects; ingestion/common/runtime.py
owns everything after that (dedup, provenance, events, identifiers,
idempotency).
"""

from __future__ import annotations

from typing import Iterable, Protocol

from ingestion.common.models import NormalizedRecord


class SourceAdapter(Protocol):
    source_name: str  # short code, must match a `sources.name` row, e.g. 'SBI'
    source_full_name: str  # e.g. 'State Bank of India'
    source_type: str  # 'bank', 'ibbi', 'nclt', 'mca', 'auction_portal', ...

    def collect(self) -> Iterable[NormalizedRecord]:
        """Yield one NormalizedRecord per resolvable unit found. May raise
        for a fatal, adapter-level failure (e.g. couldn't reach the site
        at all) — the runtime will mark the whole run 'failed'. A failure
        specific to one record should be handled inside collect() (skip
        that record, keep going) so one bad row doesn't lose an entire
        run; the runtime treats a record-processing exception it catches
        as 'failed' for that record only and keeps going regardless, but
        adapters that can distinguish should still isolate it first."""
        ...
