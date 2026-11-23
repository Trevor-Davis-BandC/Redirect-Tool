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


def test_one_or_two_homepage_redirects_are_not_flagged():
    df = _df([_row("/discontinued-service", "/"), _row("/old-landing-page", "/")])
    report = validate_redirects(df, "newsite.com")
    assert not report.has_critical_errors
    assert not report.warnings
    assert len(report.homepage_redirects) == 2


def test_many_old_urls_sent_to_the_homepage_warn_about_soft_404s():
    df = _df([_row(f"/old-{i}", "/") for i in range(3)])
    report = validate_redirects(df, "newsite.com")
    assert not report.has_critical_errors
    assert any("soft 404" in w for w in report.warnings)
    assert sorted(report.homepage_redirects) == ["/old-0", "/old-1", "/old-2"]


def test_the_old_homepage_pointing_at_the_homepage_is_not_counted():
    df = _df([_row("/index.html", "/")] + [_row(f"/old-{i}", "/about") for i in range(5)])
    report = validate_redirects(df, "newsite.com")
    assert report.homepage_redirects == []
    assert not any("soft 404" in w for w in report.warnings)


def test_a_redirect_to_itself_is_critical():
    report = validate_redirects(_df([_row("/about", "/about")]), "newsite.com")
    assert report.has_critical_errors
    assert report.self_redirects == ["/about"]
    assert any("redirects to itself" in e for e in report.critical_errors)


def test_a_trailing_slash_only_rule_is_not_a_self_redirect_or_loop():
    report = validate_redirects(_df([_row("/about/", "/about")]), "newsite.com")
    assert not report.has_critical_errors
    assert report.self_redirects == []
    assert report.redirect_loops == []


def test_a_two_step_loop_is_critical_and_reported_once():
    df = _df([_row("/a", "/b"), _row("/b", "/a")])
    report = validate_redirects(df, "newsite.com")
    assert report.has_critical_errors
    assert len(report.redirect_loops) == 1
    assert "Redirect loop" in report.critical_errors[0]


def test_a_chain_is_a_warning_naming_the_final_destination():
    df = _df([_row("/a", "/b"), _row("/b", "/c")])
    report = validate_redirects(df, "newsite.com")
    assert not report.has_critical_errors
    assert report.redirect_chains == ["/a -> /b -> /c"]
    assert any("straight at '/c'" in w for w in report.warnings)


def test_a_long_chain_is_reported_once_from_its_head():
    df = _df([_row("/a", "/b"), _row("/b", "/c"), _row("/c", "/d")])
    report = validate_redirects(df, "newsite.com")
    assert report.redirect_chains == ["/a -> /b -> /c -> /d"]


def test_external_destinations_are_not_part_of_chains_or_loops():
    df = _df([_row("/shop", "https://shop.example.com/"), _row("/b", "/shop")])
    report = validate_redirects(df, "newsite.com")
    assert report.redirect_chains == []
    assert report.redirect_loops == []
    assert not report.has_critical_errors


def test_sources_duda_cannot_redirect_are_flagged():
    df = _df([_row("/index.php", "/"), _row("/caf%C3%A9", "/cafe"), _row("/page?id=1", "/page"), _row("/fine", "/ok")])
    report = validate_redirects(df, "newsite.com")
    assert sorted(report.duda_unsupported_sources) == ["/caf%C3%A9", "/index.php", "/page?id=1"]
    assert any("Duda can't redirect" in w for w in report.warnings)


def test_unmapped_rows_with_no_destination_are_not_validated():
    df = _df([_row("/gone", "", include=False, status=STATUS_UNMAPPED)])
    report = validate_redirects(df, "newsite.com")
    assert not report.has_critical_errors
    assert report.total_unmapped == 1


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
