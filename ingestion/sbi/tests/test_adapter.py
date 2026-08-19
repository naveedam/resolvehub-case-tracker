"""Regression test for the SBI adapter's published_at handling.

SBI's notice page (see scraper.parse_notice_rows) only ever gives us an
auction date — there is no publication date anywhere in the source. A
previous version of this adapter used auction_date as published_at on
every FieldObservation, which is a real semantic error: auction_date is
when the sale is scheduled, not when the information was published.
This test locks in the fix: published_at must be None everywhere,
while auction_date must still be correctly stored as the *value* of
the 'auction_date' field itself.
"""

from __future__ import annotations

from datetime import date

from ingestion.sbi import scraper
from ingestion.sbi.adapter import SBIAdapter


def test_auction_date_is_not_used_as_published_at(monkeypatch):
    monkeypatch.setattr(scraper, "download_and_extract_pdf_text", lambda url: "dummy pdf text")
    monkeypatch.setattr(
        scraper,
        "extract_fields_from_pdf_text",
        lambda text: {
            "estimated_liability": 1_500_000.0,
            "loan_account_ref": "ACC123",
            "asset_description": "3BHK flat, Sector 12",
        },
    )

    row = {
        "description": "Sale notice - Jane Doe",
        "auction_date": "2026-05-01",
        "documents": [],
    }
    docs = [{"label": "Sale Notice - Jane Doe", "url": "https://sbi.bank.in/a.pdf"}]

    adapter = SBIAdapter()
    record = adapter._build_record(row, "Jane Doe", docs)

    assert record.field_observations, "expected observations to be produced"
    for obs in record.field_observations:
        assert obs.published_at is None, (
            f"{obs.entity_type}.{obs.field_name} must not carry a published_at "
            "— SBI's source has no publication date, only an auction date"
        )

    auction_date_obs = record.get("asset", "auction_date")
    assert auction_date_obs is not None
    # the auction date is still correctly captured as the field's VALUE —
    # only its (mis)use as published_at metadata was wrong
    assert auction_date_obs.value_date == date(2026, 5, 1)
    assert auction_date_obs.published_at is None
