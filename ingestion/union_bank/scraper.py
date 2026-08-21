"""
ResolveHub - Union Bank of India SARFAESI possession-notice scraper.
Thin wrapper around the shared standardized-format core - see
ingestion/common/sarfaesi_common.py for the actual parsing logic.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from sarfaesi_common import run_standard_scraper

SOURCE_NAME = "UnionBank"
SOURCE_NAME_FULL = "Union Bank of India"
PDF_URL = "https://www.unionbankofindia.bank.in/pdf/information-on-secured-assets-possessed-under-the-sarfaesi-act-2002.pdf"
LOCAL_PDF_PATH = "unionbank_master.pdf"


def run(max_pages=None, start_page=0):
    run_standard_scraper(SOURCE_NAME, SOURCE_NAME_FULL, PDF_URL, LOCAL_PDF_PATH,
                          max_pages=max_pages, start_page=start_page)


if __name__ == "__main__":
    run()
