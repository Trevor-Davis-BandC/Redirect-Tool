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
    STATUS_EXCLUDED,
    STATUS_UNMAPPED,
    REDIRECT_TYPE_PERMANENT,
)
from validator import validate_redirects


def _row(old_path, new_path, include=True, status=STATUS_APPROVED, notes=""):
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


def _df(rows):
    return pd.DataFrame(rows)


def test_duplicate_source_paths_flagged_as_critical():
    df = _df([
        _row("/about", "/about-us"),
        _row("/about", "/about-us-2"),
    ])
    report = validate_redirects(df, "newsite.com")
    assert report.duplicate_source_paths
    assert report.has_critical_errors


def test_blank_source_path_is_critical():
    row = _row("", "/somewhere")
    df = _df([row])
    report = validate_redirects(df, "newsite.com")
    assert report.has_critical_errors


def test_blank_destination_is_critical():
    row = _row("/about", "")
    df = _df([row])
    report = validate_redirects(df, "newsite.com")
    assert report.has_critical_errors


def test_homepage_fallback_is_not_flagged():
    """Redirecting an unmatched page to home is expected, not an error."""
    df = _df([_row("/random-unrelated-page", "/")])
    report = validate_redirects(df, "newsite.com")
    assert not report.has_critical_errors
    assert not report.warnings


def test_excluded_and_unmapped_counts():
    df = _df([
        _row("/a", "/a2", include=True, status=STATUS_APPROVED),
        _row("/b", "/b2", include=False, status=STATUS_EXCLUDED),
        _row("/c", "/", include=False, status=STATUS_UNMAPPED),
    ])
    report = validate_redirects(df, "newsite.com")
    assert report.total_old_urls == 3
    assert report.total_included == 1
    assert report.total_excluded == 1
    assert report.total_unmapped == 1


def test_duplicate_redirect_rule_detected():
    df = _df([
        _row("/a", "/z"),
        _row("/a", "/z"),
    ])
    report = validate_redirects(df, "newsite.com")
    assert report.duplicate_redirect_rules


def test_non_duplicate_rows_produce_no_issues():
    df = _df([
        _row("/a", "/a2"),
        _row("/b", "/b2"),
        _row("/c", "/"),
    ])
    report = validate_redirects(df, "newsite.com")
    assert not report.has_critical_errors
    assert not report.duplicate_source_paths
    assert not report.duplicate_redirect_rules
