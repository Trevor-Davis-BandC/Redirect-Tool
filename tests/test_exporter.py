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
    COL_REDIRECT_TYPE,
    COL_CONFIDENCE,
    COL_MATCH_TYPE,
    COL_STATUS,
    COL_NOTES,
    STATUS_APPROVED,
    STATUS_UNMAPPED,
    REDIRECT_TYPE_PERMANENT,
    REDIRECT_TYPE_TEMPORARY,
)
from exporter import (
    export_default_csv,
    build_export_filename,
    guess_column_mapping,
    export_with_template,
    DEFAULT_OLD_COLUMN,
    DEFAULT_NEW_COLUMN,
    DEFAULT_REDIRECT_TYPE_COLUMN,
)


def _row(old_path, new_path, include=True, status=STATUS_APPROVED, redirect_type=REDIRECT_TYPE_PERMANENT):
    return {
        COL_INCLUDE: include,
        COL_OLD_URL: f"https://oldsite.com{old_path}",
        COL_OLD_PATH: old_path,
        COL_NEW_URL: f"https://staging164721.bvmlocal.com{new_path}" if new_path else "",
        COL_NEW_PATH: new_path,
        COL_REDIRECT_TYPE: redirect_type,
        COL_CONFIDENCE: 100.0,
        COL_MATCH_TYPE: "Exact Path",
        COL_STATUS: status,
        COL_NOTES: "",
    }


def test_default_export_matches_duda_template_header():
    df = pd.DataFrame([_row("/old-page", "/new-page"), _row("/old-about", "/about")])
    csv_text = export_default_csv(df)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "Old Page URL,Destination Page URL, Redirect Type"
    assert "/old-page,/new-page,301" in lines
    assert "/old-about,/about,301" in lines


def test_default_export_never_includes_staging_domain():
    df = pd.DataFrame([_row("/old-page", "/new-page")])
    csv_text = export_default_csv(df)
    assert "bvmlocal" not in csv_text
    assert "http" not in csv_text


def test_export_excludes_unchecked_rows():
    df = pd.DataFrame([_row("/kept", "/kept-new", include=True), _row("/dropped", "/dropped-new", include=False)])
    csv_text = export_default_csv(df)
    assert "/kept,/kept-new,301" in csv_text
    assert "dropped" not in csv_text


def test_export_excludes_unmapped_rows():
    df = pd.DataFrame([_row("/kept", "/kept-new"), _row("/unmapped-page", "", status=STATUS_UNMAPPED)])
    csv_text = export_default_csv(df)
    assert "/kept,/kept-new,301" in csv_text
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
    assert parsed.iloc[0][DEFAULT_OLD_COLUMN] == "/old,page"


def test_export_preserves_redirect_type_per_row():
    df = pd.DataFrame([
        _row("/old-page", "/new-page", redirect_type=REDIRECT_TYPE_PERMANENT),
        _row("/contact", "/", redirect_type=REDIRECT_TYPE_TEMPORARY),
    ])
    csv_text = export_default_csv(df)
    assert "/old-page,/new-page,301" in csv_text
    assert "/contact,/,302" in csv_text


def test_export_falls_back_to_301_for_invalid_redirect_type():
    df = pd.DataFrame([_row("/old-page", "/new-page", redirect_type="")])
    csv_text = export_default_csv(df)
    assert "/old-page,/new-page,301" in csv_text


def test_filename_includes_project_name_and_date():
    from datetime import date

    filename = build_export_filename("My Project")
    assert filename.startswith("My-Project-redirects-")
    assert date.today().isoformat() in filename
    assert filename.endswith(".csv")


def test_guess_column_mapping_finds_likely_columns():
    guess = guess_column_mapping(["Old Page URL", "Destination Page URL", "Redirect Type"])
    assert guess["source"] == "Old Page URL"
    assert guess["destination"] == "Destination Page URL"
    assert guess["redirect_type"] == "Redirect Type"


def test_export_with_template_preserves_headers_and_order():
    df = pd.DataFrame([_row("/old-page", "/new-page", redirect_type=REDIRECT_TYPE_PERMANENT)])
    headers = ["Redirect Type", "Source URL", "Destination URL"]
    csv_text = export_with_template(
        df, headers, source_column="Source URL", destination_column="Destination URL",
        redirect_type_column="Redirect Type",
    )
    parsed = pd.read_csv(io.StringIO(csv_text), dtype=str)
    assert list(parsed.columns) == headers
    assert parsed.iloc[0]["Source URL"] == "/old-page"
    assert parsed.iloc[0]["Destination URL"] == "/new-page"
    assert parsed.iloc[0]["Redirect Type"] == "301"


def test_export_with_template_fills_unmapped_columns_from_defaults():
    df = pd.DataFrame([_row("/old-page", "/new-page")])
    headers = ["Source URL", "Destination URL", "Notes"]
    csv_text = export_with_template(
        df, headers, source_column="Source URL", destination_column="Destination URL",
        default_values={"Notes": "bulk import"},
    )
    parsed = pd.read_csv(io.StringIO(csv_text))
    assert parsed.iloc[0]["Notes"] == "bulk import"
