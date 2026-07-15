import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io

import pandas as pd

from columns import (
    COL_INCLUDE,
    COL_OLD_URL,
    COL_OLD_PATH,
    COL_NEW_URL,
    COL_NEW_PATH,
    COL_CONFIDENCE,
    COL_MATCH_TYPE,
    COL_STATUS,
    COL_NOTES,
    STATUS_APPROVED,
    STATUS_UNMAPPED,
)
from exporter import (
    export_default_csv,
    build_export_filename,
    guess_column_mapping,
    export_with_template,
)


def _row(old_path, new_path, include=True, status=STATUS_APPROVED):
    return {
        COL_INCLUDE: include,
        COL_OLD_URL: f"https://oldsite.com{old_path}",
        COL_OLD_PATH: old_path,
        COL_NEW_URL: f"https://newsite.com{new_path}" if new_path else "",
        COL_NEW_PATH: new_path,
        COL_CONFIDENCE: 100.0,
        COL_MATCH_TYPE: "Exact Path",
        COL_STATUS: status,
        COL_NOTES: "",
    }


def test_default_export_has_expected_header_and_rows():
    df = pd.DataFrame([_row("/old-page", "/new-page"), _row("/old-about", "/about")])
    csv_text = export_default_csv(df)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "Old URL,New URL"
    assert "/old-page,/new-page" in lines
    assert "/old-about,/about" in lines


def test_export_excludes_unchecked_rows():
    df = pd.DataFrame([_row("/kept", "/kept-new", include=True), _row("/dropped", "/dropped-new", include=False)])
    csv_text = export_default_csv(df)
    assert "/kept,/kept-new" in csv_text
    assert "dropped" not in csv_text


def test_export_excludes_unmapped_rows():
    df = pd.DataFrame([_row("/kept", "/kept-new"), _row("/unmapped-page", "", status=STATUS_UNMAPPED)])
    csv_text = export_default_csv(df)
    assert "/kept,/kept-new" in csv_text
    assert "unmapped-page" not in csv_text


def test_export_removes_fragments_and_keeps_leading_slash():
    df = pd.DataFrame([_row("/old-page", "/new-page#section")])
    csv_text = export_default_csv(df)
    assert "/new-page#section" not in csv_text
    assert "/new-page" in csv_text


def test_export_deduplicates_source_paths():
    df = pd.DataFrame([_row("/dup", "/first"), _row("/dup", "/second")])
    csv_text = export_default_csv(df)
    lines = [l for l in csv_text.strip().splitlines() if l.startswith("/dup")]
    assert len(lines) == 1


def test_export_escapes_commas_in_values():
    df = pd.DataFrame([_row("/old,page", "/new-page")])
    csv_text = export_default_csv(df)
    parsed = pd.read_csv(io.StringIO(csv_text))
    assert parsed.iloc[0]["Old URL"] == "/old,page"


def test_filename_includes_project_name_and_date():
    from datetime import date

    filename = build_export_filename("My Project")
    assert filename.startswith("My-Project-redirects-")
    assert date.today().isoformat() in filename
    assert filename.endswith(".csv")


def test_guess_column_mapping_finds_likely_columns():
    guess = guess_column_mapping(["Old Page URL", "New Page URL", "Redirect Type"])
    assert guess["source"] == "Old Page URL"
    assert guess["destination"] == "New Page URL"


def test_export_with_template_preserves_headers_and_order():
    df = pd.DataFrame([_row("/old-page", "/new-page")])
    headers = ["Redirect Type", "Source URL", "Destination URL"]
    csv_text = export_with_template(
        df, headers, source_column="Source URL", destination_column="Destination URL",
        default_values={"Redirect Type": "301"},
    )
    parsed = pd.read_csv(io.StringIO(csv_text))
    assert list(parsed.columns) == headers
    assert parsed.iloc[0]["Source URL"] == "/old-page"
    assert parsed.iloc[0]["Destination URL"] == "/new-page"
    assert parsed.iloc[0]["Redirect Type"] == 301 or str(parsed.iloc[0]["Redirect Type"]) == "301"
