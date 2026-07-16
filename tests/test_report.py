import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from columns import (
    COL_INCLUDE,
    COL_OLD_URL,
    COL_OLD_PATH,
    COL_NEW_URL,
    COL_NEW_PATH,
    COL_REDIRECT_TYPE,
    COL_STATUS,
    COL_NOTES,
    STATUS_APPROVED,
    STATUS_NEEDS_REVIEW,
    STATUS_EXCLUDED,
    STATUS_UNMAPPED,
    REDIRECT_TYPE_PERMANENT,
)
from validator import validate_redirects
from report import build_redirect_report_pdf


def _row(old_path, new_path, status, include=True, notes=""):
    return {
        COL_INCLUDE: include,
        COL_OLD_URL: f"https://oldsite.com{old_path}",
        COL_OLD_PATH: old_path,
        COL_NEW_URL: f"https://newsite.com{new_path}" if new_path else "",
        COL_NEW_PATH: new_path,
        COL_REDIRECT_TYPE: REDIRECT_TYPE_PERMANENT,
        COL_STATUS: status,
        COL_NOTES: notes,
    }


def _sample_df():
    return pd.DataFrame([
        _row("/about", "/about-us", STATUS_APPROVED),
        _row("/services", "/offerings", STATUS_NEEDS_REVIEW),
        _row("/old-promo", "/promo", STATUS_EXCLUDED, include=False),
        _row("/legacy-page", "", STATUS_UNMAPPED, include=False),
    ])


def test_report_produces_valid_pdf_bytes():
    df = _sample_df()
    validation = validate_redirects(df, "newsite.com")
    pdf_bytes = build_redirect_report_pdf("Test Project", "oldsite.com", "newsite.com", df, validation)
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert pdf_bytes.startswith(b"%PDF")
    assert pdf_bytes.rstrip().endswith(b"%%EOF")


def test_report_handles_empty_dataframe():
    df = pd.DataFrame(columns=[COL_INCLUDE, COL_OLD_URL, COL_OLD_PATH, COL_NEW_URL, COL_NEW_PATH, COL_REDIRECT_TYPE, COL_STATUS, COL_NOTES])
    validation = validate_redirects(df, "newsite.com")
    pdf_bytes = build_redirect_report_pdf("Empty Project", "oldsite.com", "newsite.com", df, validation)
    assert pdf_bytes.startswith(b"%PDF")


def test_report_handles_blank_project_and_domain_fields():
    df = _sample_df()
    validation = validate_redirects(df, "")
    pdf_bytes = build_redirect_report_pdf("", "", "", df, validation)
    assert pdf_bytes.startswith(b"%PDF")


def test_report_handles_many_rows_per_section():
    """Regression test: multi_cell must reset its x-position after each bullet
    line, or the cursor drifts rightward across iterations until fpdf2 raises
    'Not enough horizontal space to render a single character'.
    """
    rows = [_row(f"/page-{i}", f"/new-page-{i}", STATUS_NEEDS_REVIEW) for i in range(30)]
    rows += [_row(f"/removed-{i}", f"/removed-target-{i}", STATUS_EXCLUDED, include=False) for i in range(30)]
    df = pd.DataFrame(rows)
    validation = validate_redirects(df, "newsite.com")
    pdf_bytes = build_redirect_report_pdf("Big Project", "oldsite.com", "newsite.com", df, validation)
    assert pdf_bytes.startswith(b"%PDF")
    assert pdf_bytes.rstrip().endswith(b"%%EOF")
