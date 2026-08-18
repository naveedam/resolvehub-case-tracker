"""Test isolation for ingestion/sbi/tests only.

ingestion/sbi/scraper.py creates a real Supabase client at import time
(`supabase = create_client(os.environ["SUPABASE_URL"], ...)`), which is
correct for production use — the SBI adapter genuinely needs those
credentials to run live ingestion. But test_adapter.py only imports
scraper.py for its pure extraction/classification functions and never
touches the network or a database, so it shouldn't need real
credentials just to be collected.

os.environ.setdefault means this never overrides real credentials if
they happen to be set in the environment already — it only fills the
gap so the module-level `os.environ[...]` lookups in scraper.py don't
raise KeyError during import.

pytest imports conftest.py in a directory before importing the test
files in that same directory, so this runs before test_adapter.py's
`from ingestion.sbi import scraper` line.
"""

import os

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder-service-role-key")
