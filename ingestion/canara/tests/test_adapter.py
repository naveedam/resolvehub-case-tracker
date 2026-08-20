"""Tests for ingestion/canara/adapter.py.

Unlike SBI, Canara's extraction needs no network or PDF text parsing to
test — _build_record() operates directly on an already-parsed table
row (a list of cell strings), the same shape pdfplumber's
extract_tables() produces. So these tests build synthetic rows
directly, matching the real column layout documented at the top of
scraper.py, rather than monkeypatching a PDF fetch.
"""

from __future__ import annotations

from datetime import date

from ingestion.canara.adapter import CanaraAdapter

# Column layout (scraper.py docstring):
# 0 Circle | 1 RO | 2 Branch | 3 State | 4 Borrower | 5 Borrower addr |
# 6 Guarantor | 7 Guarantor addr | 8 Outstanding | 9 NPA date |
# 10 Asset classification | 11 Security details | 12 Title holder |
# 13 Authorised officer | 14 Contact no


def make_row(**overrides) -> list:
    row = [
        "Bengaluru Circle",  # 0 circle
        "Bengaluru RO",  # 1 ro_name
        "Koramangala Branch",  # 2 branch
        "Karnataka",  # 3 state
        "Test Borrower Pvt Ltd",  # 4 borrower_name
        "123 Test Street",  # 5 borrower address
        "Test Guarantor, Second Guarantor",  # 6 guarantor
        "456 Guarantor Street",  # 7 guarantor address
        "15,00,000",  # 8 outstanding
        "15.03.2025",  # 9 npa_date
        "Immovable Property",  # 10 asset_classification
        "3BHK Flat, Sector 12, Bengaluru",  # 11 security_details
        "Test Borrower Pvt Ltd",  # 12 title holder
        "Authorised Officer Name",  # 13 authorised officer
        "9999999999",  # 14 contact
    ]
    for key, value in overrides.items():
        index = {
            "circle": 0, "ro_name": 1, "branch": 2, "state": 3, "borrower": 4,
            "guarantor": 6, "outstanding": 8, "npa_date": 9,
            "asset_classification": 10, "security_details": 11,
        }[key]
        row[index] = value
    return row


def test_full_row_produces_correctly_provenanced_observations():
    adapter = CanaraAdapter()
    record = adapter._build_record(make_row(), page_num=42)

    assert record is not None
    assert record.case_type == "SARFAESI"
    assert record.borrower_name == "Test Borrower Pvt Ltd"
    assert record.borrower_type == "Company"  # "Pvt Ltd" keyword match
    assert record.asset_type == "Apartment"  # "flat" keyword match on security_details

    assert record.field_observations, "expected observations to be produced"
    for obs in record.field_observations:
        # Canara's master PDF has no per-row publication date — same
        # principle as the SBI published_at fix: don't invent one.
        assert obs.published_at is None
        # every observation must be traceable to the master PDF and page
        assert obs.source_document_url == "https://www.canarabank.bank.in/documents/d/guest/regional-office-agra_1"
        assert obs.source_record_ref == "master_pdf_page_43"  # page_num=42 -> page 43 (1-indexed)

    liability_obs = record.get("case", "estimated_liability")
    assert liability_obs is not None
    assert liability_obs.value_numeric == 1_500_000.0
    assert liability_obs.unit == "INR"

    npa_obs = record.get("case", "npa_date")
    assert npa_obs is not None
    assert npa_obs.value_date == date(2025, 3, 15)

    description_obs = record.get("asset", "description")
    assert description_obs is not None
    assert description_obs.value_text == "3BHK Flat, Sector 12, Bengaluru"

    possession_obs = record.get("asset", "possession_status")
    assert possession_obs is not None
    assert possession_obs.value_text == "possessed"


def test_asset_classification_is_captured():
    """The field this audit found was silently dropped when the adapter
    was first ported to the evidence-layer model — the pre-Phase-1
    scraper.ingest_row() stored it in a metadata blob; the ported
    adapter never read row[10] at all. Locking in the fix."""
    adapter = CanaraAdapter()
    record = adapter._build_record(make_row(asset_classification="Movable - Vehicle"), page_num=0)

    assert record is not None
    classification_obs = record.get("asset", "asset_classification")
    assert classification_obs is not None
    assert classification_obs.value_text == "Movable - Vehicle"
    assert classification_obs.confidence == "source_derived"  # bank-reported, not our own inference


def test_placeholder_security_details_produces_no_asset_observations():
    """Same bug class as the SBI Property-ID/'No' fix: a placeholder
    token ('-' or '#N/A') in a source column must not be stored as if
    it were real extracted data. security_details had no placeholder
    guard at all — found by test_asset_classification_independent_of_
    security_details below failing unexpectedly during this audit."""
    adapter = CanaraAdapter()
    for placeholder in ("-", "#N/A"):
        record = adapter._build_record(make_row(security_details=placeholder), page_num=0)
        assert record is not None
        assert record.get("asset", "description") is None
        assert record.get("asset", "possession_status") is None
        assert record.asset_type is None


def test_asset_classification_independent_of_security_details():
    """asset_classification and description are two separate bank-
    reported fields — one being blank shouldn't suppress the other."""
    adapter = CanaraAdapter()
    record = adapter._build_record(
        make_row(asset_classification="Immovable Property", security_details="-"), page_num=0,
    )

    assert record is not None
    assert record.get("asset", "asset_classification") is not None
    assert record.get("asset", "description") is None  # "-" security_details means: nothing to report


def test_placeholder_asset_classification_is_not_captured():
    adapter = CanaraAdapter()
    record = adapter._build_record(make_row(asset_classification="#N/A"), page_num=0)

    assert record is not None
    assert record.get("asset", "asset_classification") is None


def test_only_the_first_guarantor_is_linked():
    adapter = CanaraAdapter()
    record = adapter._build_record(make_row(guarantor="First Guarantor, Second Guarantor"), page_num=0)

    assert record is not None
    assert len(record.guarantors) == 1
    assert record.guarantors[0][0] == "First Guarantor"


def test_placeholder_guarantor_produces_no_guarantors():
    adapter = CanaraAdapter()
    record = adapter._build_record(make_row(guarantor="#N/A"), page_num=0)

    assert record is not None
    assert record.guarantors == []


def test_short_row_is_rejected():
    adapter = CanaraAdapter()
    assert adapter._build_record(["only", "a", "few", "cells"], page_num=0) is None


def test_placeholder_borrower_is_rejected():
    adapter = CanaraAdapter()
    assert adapter._build_record(make_row(borrower="#N/A"), page_num=0) is None
    assert adapter._build_record(make_row(borrower="-"), page_num=0) is None


def test_below_sanity_floor_amount_produces_no_liability_observation():
    """parse_amount() rejects values under Rs. 1,000 as almost certainly
    a parsing artifact, not a real outstanding balance — mirrors the
    same sanity-bound principle already applied to SBI's amounts."""
    adapter = CanaraAdapter()
    record = adapter._build_record(make_row(outstanding="500"), page_num=0)

    assert record is not None
    assert record.get("case", "estimated_liability") is None
    assert record.get("liability", "outstanding_amount") is None
