import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gsc_export import parse_gsc_csv


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_parses_simple_gsc_csv():
    csv_text = (
        "URL,Last crawled\n"
        "https://example.com/about-us/,2026-08-08\n"
        "https://example.com/old-page/,2026-08-07\n"
    )
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert result.gsc_import_filename == "export.csv"
    assert set(result.urls) == {"https://example.com/about-us/", "https://example.com/old-page/"}
    assert not result.errors


def test_wildcard_pattern_rows_are_kept_as_404s_not_skipped():
    """Regression test: GSC flagging "/wp-content/plugins/*" as a 404 means
    it needs a redirect (typically to home) like anything else GSC flags --
    the tool shouldn't second-guess that and silently drop it. Only rows
    with no usable URL at all (blank) are skipped.
    """
    csv_text = (
        "URL,Last crawled\n"
        "https://example.com/real-page/,2026-08-08\n"
        "https://example.com/wp-content/plugins/*,2026-07-16\n"
        "https://example.com/*,2026-07-15\n"
        ",2026-07-01\n"
    )
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert set(result.urls) == {
        "https://example.com/real-page/",
        "https://example.com/wp-content/plugins/*",
        "https://example.com/*",
    }
    # The blank row is silently ignored (too mundane to warn about) -- only
    # non-blank-but-unparseable values would trigger a "skipped" warning.
    assert not result.warnings


def test_dedupes_query_string_variants_by_path():
    csv_text = (
        "URL,Last crawled\n"
        "https://example.com/events/list/?tribe-bar-date=2022-01-01,2026-08-08\n"
        "https://example.com/events/list/?tribe-bar-date=2022-02-02,2026-08-07\n"
        "https://example.com/events/list/?tribe-bar-date=2022-03-03,2026-08-06\n"
    )
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert len(result.urls) == 1
    assert result.duplicates_removed == 2


def test_missing_url_column_falls_back_to_first_column_with_warning():
    csv_text = "Link,Notes\nhttps://example.com/page-one/,ok\n"
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert result.urls == ["https://example.com/page-one/"]
    assert any('"Link"' in w for w in result.warnings)


def test_recognizes_screaming_frog_address_column():
    csv_text = "Address,Status Code\nhttps://example.com/page-one/,200\n"
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert result.urls == ["https://example.com/page-one/"]
    assert not result.warnings


def test_non_blank_unparseable_values_are_skipped_with_a_warning():
    csv_text = "URL,Last crawled\nhttps://example.com/real-page/,2026-08-08\nnot a url at all,2026-07-01\n"
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert result.urls == ["https://example.com/real-page/"]
    assert result.warnings
    assert "Skipped 1" in result.warnings[0]


def test_all_blank_rows_gives_friendly_error():
    csv_text = "URL,Last crawled\n,2026-07-16\n,2026-07-01\n"
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert result.urls == []
    assert result.errors
    assert "export.csv" in result.errors[0]


def test_not_a_csv_file_gives_friendly_error():
    result = parse_gsc_csv(b"\x00\x01\x02 not a csv at all", "export.csv", "example.com")

    assert result.urls == []
    assert result.errors


def test_screaming_frog_export_drops_assets_and_broken_and_redirected_links():
    csv_text = (
        "Address,Content Type,Status Code\n"
        "https://example.com/,text/html; charset=UTF-8,200\n"
        "https://example.com/about-us/,text/html; charset=UTF-8,200\n"
        "https://example.com/logo.png,image/png,200\n"
        "https://example.com/style.css,text/css,200\n"
        "https://example.com/old-page/,text/html; charset=UTF-8,301\n"
        "https://example.com/gone-page/,text/html; charset=UTF-8,404\n"
    )
    result = parse_gsc_csv(_csv(csv_text), "internal_all.csv", "example.com")

    assert set(result.urls) == {
        "https://example.com/",
        "https://example.com/about-us/",
    }
    assert any("non-200 status" in w or "asset file" in w for w in result.warnings)


def test_screaming_frog_export_status_only_column_still_filters():
    csv_text = "Address,Status Code\nhttps://example.com/real/,200\nhttps://example.com/broken/,500\n"
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert result.urls == ["https://example.com/real/"]


def test_bare_gsc_export_without_status_or_content_type_is_unfiltered():
    """No Status Code / Content Type column at all -- a bare GSC 404 export
    -- means every row is trusted as-is, same as before this feature."""
    csv_text = "URL,Last crawled\nhttps://example.com/old-file.pdf,2026-08-08\n"
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert result.urls == ["https://example.com/old-file.pdf"]
    assert not result.warnings


def test_screaming_frog_export_all_filtered_out_gives_friendly_error():
    csv_text = "Address,Status Code\nhttps://example.com/logo.png,200\n"
    result = parse_gsc_csv(_csv(csv_text), "export.csv", "example.com")

    assert result.urls == []
    assert result.errors
