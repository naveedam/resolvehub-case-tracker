from __future__ import annotations

import plistlib
import re
from datetime import datetime
from bs4 import BeautifulSoup


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _parse_date(value: str):
    value = _clean(value)
    if not value:
        return None

    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass

    return value


def load_webarchive(path: str) -> str:
    """Extract rendered HTML from a Safari .webarchive."""
    with open(path, "rb") as f:
        archive = plistlib.load(f)

    data = archive["WebMainResource"]["WebResourceData"]
    return data.decode("utf-8", errors="ignore")


def parse(path: str):
    html = load_webarchive(path)
    soup = BeautifulSoup(html, "html.parser")

    tables = soup.find_all("table")
    if not tables:
        raise ValueError("No table found")

    # Largest table is the Party-wise report
    table = max(tables, key=lambda t: len(t.find_all("tr")))
    rows = table.find_all("tr")

    headers = [_clean(th.get_text()).lower() for th in rows[0].find_all(["th", "td"])]

    cases = []

    for tr in rows[1:]:
        cols = [_clean(td.get_text()) for td in tr.find_all("td")]

        if len(cols) < len(headers):
            continue

        row = dict(zip(headers, cols))

        applicant = ""
        respondent = ""

        party_text = row.get("applicant vs respondent", "")
        if " vs " in party_text.lower():
            parts = re.split(r"\bvs\b", party_text, flags=re.IGNORECASE)
            applicant = _clean(parts[0])
            respondent = _clean(parts[1])

        cases.append(
            {
                "tribunal": "Debts Recovery Tribunal - Bangalore (DRT-1)",
                "case_number": row.get("case no.") or row.get("case no"),
                "case_type": row.get("case type"),
                "diary_number": row.get("diary no.") or row.get("diary no"),
                "filing_date": _parse_date(row.get("date of filing")),
                "applicant": applicant,
                "respondent": respondent,
                "applicant_advocate": row.get("applicant's advocate"),
                "respondent_advocate": row.get("respondent's advocate") or None,
                "status": "pending",
            }
        )

    return cases
