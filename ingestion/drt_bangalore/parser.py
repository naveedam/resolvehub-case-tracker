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



def parse(path):
    html = load_webarchive(path)
    soup = BeautifulSoup(html, "html.parser")

    tribunal = soup.find(string=re.compile("DEBTS RECOVERY TRIBUNAL", re.I))
    tribunal = tribunal.strip() if tribunal else "DRT"

    cases = []

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue

        cells = [_clean(td.get_text(" ", strip=True)) for td in tds]

        if len(cells) > 1 and "Applicant vs Respondent" in cells[1]:
            continue

        party_text = cells[1]
        parts = re.split(r"\bvs\b", party_text, flags=re.I)

        if len(parts) == 2:
            applicant = parts[0].strip()
            respondent = parts[1].strip()
        else:
            applicant = party_text
            respondent = ""

        case_number = None

        for td in tds:
            txt = _clean(td.get_text(" ", strip=True))
            m = re.search(
                r"\b(OA|SA|TA|IA|RA|RC)\s*/\s*(\d+)\s*/\s*(\d{4})\b",
                txt,
                re.I,
            )
            if m:
                case_number = f"{m.group(1).upper()}/{m.group(2)}/{m.group(3)}"
                break

        if not case_number:
            raw = str(tr)
            m = re.search(
                r"\b(OA|SA|TA|IA|RA|RC)\s*/\s*(\d+)\s*/\s*(\d{4})\b",
                raw,
                re.I,
            )
            if m:
                case_number = f"{m.group(1).upper()}/{m.group(2)}/{m.group(3)}"

        filing_date = _parse_date(cells[5])

        cases.append({
            "tribunal": tribunal,
            "case_number": case_number,
            "case_type": cells[3].upper(),
            "diary_number": cells[4],
            "filing_date": filing_date,
            "applicant": applicant.upper(),
            "respondent": respondent.upper(),
            "applicant_advocate": cells[6].upper() if len(cells) > 6 else None,
            "respondent_advocate": cells[7].upper() if len(cells) > 7 else None,
            "status": "Pending",
        })

    return cases
