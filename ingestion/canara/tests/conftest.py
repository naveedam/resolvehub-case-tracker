"""Test isolation for ingestion/canara/tests only.

ingestion/canara/scraper.py creates a real Supabase client at import
time, same as ingestion/sbi/scraper.py — see the identical conftest.py
under ingestion/sbi/tests/ for the full rationale. Placeholder values
only fill the gap when real credentials aren't already present.
"""

import os

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder-service-role-key")
