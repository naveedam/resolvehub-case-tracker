"""Regression tests for ingestion/sbi/scraper.py's extract_fields_from_pdf_text.

Both fixtures below are synthetic but structurally representative of
real SBI IBA-template notices — modeled on patterns actually observed
in a live 5-record preview run on 2026-08-18 (see the Phase 1 SBI
extraction-quality pass), not verbatim copies of any single PDF.
"""

from __future__ import annotations

import os

os.environ.setdefault("SUPABASE_URL", "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "placeholder-service-role-key")

from ingestion.sbi.scraper import extract_fields_from_pdf_text


def test_property_description_survives_a_linebreak_inside_the_anchor_phrase():
    """A previous version of the anchor regex required 'Details of the
    encumbrances' to be a single contiguous run of literal spaces. Real
    pdfplumber extraction wraps mid-phrase often enough (observed live:
    the SARB Jorhat Bhaskar Jyoti Saikia notice) that this silently
    dropped the property description for any notice that wrapped there."""
    text = """
    03 Complete Description of the immovable secured
    assets to be sold with identification marks or number, if any.
    Flat No. 402, Sector 12, Test City, PIN 100001
    04 Details of the
    encumbrances known to the secured creditor
    No encumbrances known to the Authorised Officer.
    """
    fields = extract_fields_from_pdf_text(text)
    assert fields["asset_description"] is not None
    assert "Flat No. 402, Sector 12, Test City" in fields["asset_description"]
    # must not have swallowed the encumbrances section itself
    assert "encumbrances known to the secured creditor" not in fields["asset_description"]


def test_property_description_still_works_without_a_linebreak():
    """The original, non-wrapped case must keep working after the fix."""
    text = """
    03 Complete Description of the immovable secured
    assets to be sold with identification marks or number, if any.
    Flat No. 402, Sector 12, Test City, PIN 100001
    04 Details of the encumbrances known to the secured creditor
    No encumbrances known to the Authorised Officer.
    """
    fields = extract_fields_from_pdf_text(text)
    assert fields["asset_description"] is not None
    assert "Flat No. 402, Sector 12, Test City" in fields["asset_description"]


def test_property_id_table_header_does_not_produce_account_number_no():
    """A 2-column table ('Property ID | No | EMD (Rs.)') collapses into
    linear PDF text as 'Property ID No EMD (Rs.)...' — the naive
    fallback then captured the header word 'No' as if it were the ID
    (observed live: the SBI-Manoj Solanki notice, account_number
    incorrectly came out as the string 'No'). The fix must reject that
    match rather than accept it as a plausible ID."""
    text = """
    07 Reserve price of the immovable secured assets
    Property ID No EMD (Rs.)
    SBIN200060644879 2,23,000.00
    """
    fields = extract_fields_from_pdf_text(text)
    assert fields["loan_account_ref"] != "No"
    # no genuine 'loan/account no' phrasing is present in this fixture,
    # and the Property ID fallback correctly has nothing plausible to
    # fall back to here — None is the right answer, not a wrong guess
    assert fields["loan_account_ref"] is None


def test_property_id_still_extracted_when_genuinely_present():
    """A real, well-formed 'Property ID: <id>' line must still work."""
    text = """
    03 Complete Description of the immovable secured assets to be sold.
    Property ID: SBIN200051872031
    All that part and parcel of Residential House situated at Test Village.
    """
    fields = extract_fields_from_pdf_text(text)
    assert fields["loan_account_ref"] == "SBIN200051872031"


def test_loan_account_no_pattern_still_takes_priority_over_property_id():
    """When both an explicit 'Account No' and a 'Property ID' are present,
    the explicit account number should still win, as before this fix."""
    text = """
    Account No: 38401351282
    Property ID: SBIN200051872031
    """
    fields = extract_fields_from_pdf_text(text)
    assert fields["loan_account_ref"] == "38401351282"
