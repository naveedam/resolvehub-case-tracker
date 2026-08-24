from __future__ import annotations
"""
ResolveHub - DRT-1 Bangalore parser (canonical reference implementation)
---------------------------------------------------------------------------
Parses a DRT case-status HTML page (currently the local fixture in
sample/) into a structured dict. Doesn't care whether the HTML came from
a saved fixture or a live fetch - scraper.py owns that distinction.
"""

import re
from datetime import datetime
from bs4 import BeautifulSoup

FIELD_KEY_MAP = {
    "tribunal": "tribunal",
    "case no.": "case_number",
    "case no": "case_number",
    "diary no.": "diary_number",
    "diary no": "diary_number",
    "case type": "case_type",
    "date of filing": "filing_date_raw",
    "applicant": "applicant",
    "respondent": "respondent",
    "applicant advocate": "applicant_advocate",
    "respondent advocate": "respondent_advocate",
    "status": "status",
}


def parse_case_html(html: str) -> dict:
    """Returns a dict with normalized keys: tribunal, case_number,
    diary_number, case_type, filing_date (ISO yyyy-mm-dd), applicant,
    respondent, applicant_advocate, respondent_advocate, status."""
    soup = BeautifulSoup(html, "html.parser")
    fields = {}

    for row in soup.select("table.case-info-table tr"):
        label_cell = row.find("td", class_="label")
        value_cell = row.find("td", class_="value")
        if not label_cell or not value_cell:
            continue
        label = label_cell.get_text(strip=True).lower()
        value = value_cell.get_text(strip=True)
        key = FIELD_KEY_MAP.get(label)
        if key:
            fields[key] = value or None

    filing_date_raw = fields.pop("filing_date_raw", None)
    fields["filing_date"] = _parse_date(filing_date_raw) if filing_date_raw else None

    # Empty strings (e.g. an unfilled Respondent Advocate cell) should be
    # None, not "" - distinguishes "known to be blank" from "not present".
    for k, v in fields.items():
        if v == "":
            fields[k] = None

    return fields


def _parse_date(raw: str) -> str | None:
    """DRT portals typically show DD-MM-YYYY; normalize to ISO."""
    raw = raw.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None
