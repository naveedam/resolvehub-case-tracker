"""
ResolveHub - DRT-1 Bangalore scraper (canonical reference implementation)
----------------------------------------------------------------------------
Currently reads a saved HTML fixture instead of a live DRT portal - no
live scraping yet, per this milestone's scope. fetch_live() is stubbed
so the interface is ready for a real DRT case-status URL once one is
identified, without needing to change parser.py or adapter.py.
"""

import os

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample")


def fetch_local_html(filename: str = "SA-382-2025.html") -> str:
    """Reads a saved HTML fixture from sample/."""
    path = os.path.join(SAMPLE_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def fetch_live(url: str) -> str:
    """Not implemented yet - live DRT portal scraping is a future milestone.
    Kept as a stub so scraper.py's interface doesn't need to change when
    that milestone starts; only this function needs a real implementation
    (e.g. requests.get(url).text with the same polite-delay/retry patterns
    used in sarfaesi_common.py)."""
    raise NotImplementedError(
        "Live DRT portal scraping isn't built yet - use fetch_local_html() "
        "with a saved fixture for now."
    )
