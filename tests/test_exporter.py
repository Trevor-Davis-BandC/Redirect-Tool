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
    export_default_csv_chunks,
    export_with_template,
    export_with_template_chunks,
    build_export_filename,
    guess_column_mapping,
    chunk_rows,
    DEFAULT_OLD_COLUMN,
    DEFAULT_NEW_COLUMN,
    DEFAULT_REDIRECT_TYPE_COLUMN,
)
from config import MAX_REDIRECTS_PER_CSV


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


def test_export_forces_everything_to_301_regardless_of_stored_value():
    """Every redirect is always 301 -- a stale 302 from a project saved
    before this policy (or any other stored value) must never reach an
    export, since Duda's importer treats these as permanent moves only."""
    df = pd.DataFrame([
        _row("/old-page", "/new-page", redirect_type=REDIRECT_TYPE_PERMANENT),
        _row("/contact", "/", redirect_type=REDIRECT_TYPE_TEMPORARY),
        _row("/garbage", "/garbage-new", redirect_type=""),
    ])
    csv_text = export_default_csv(df)
    assert "/old-page,/new-page,301" in csv_text
    assert "/contact,/,301" in csv_text
    assert "/garbage,/garbage-new,301" in csv_text
    assert "302" not in csv_text


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


def test_chunk_rows_returns_single_chunk_when_under_limit():
    rows = [{"a": i} for i in range(5)]
    chunks = chunk_rows(rows, chunk_size=10)
    assert len(chunks) == 1
    assert chunks[0] == rows


def test_chunk_rows_splits_evenly_and_with_remainder():
    rows = [{"a": i} for i in range(5)]
    chunks = chunk_rows(rows, chunk_size=2)
    assert [len(c) for c in chunks] == [2, 2, 1]
    assert [row["a"] for chunk in chunks for row in chunk] == list(range(5))


def test_chunk_rows_returns_one_empty_chunk_for_no_rows():
    assert chunk_rows([], chunk_size=200) == [[]]


def test_default_export_chunks_single_file_when_under_limit():
    df = pd.DataFrame([_row(f"/old-{i}", f"/new-{i}") for i in range(3)])
    chunks = export_default_csv_chunks(df, chunk_size=200)
    assert len(chunks) == 1
    lines = chunks[0].strip().splitlines()
    assert len(lines) == 1 + 3  # header + 3 rows


def test_default_export_chunks_splits_when_over_limit():
    df = pd.DataFrame([_row(f"/old-{i}", f"/new-{i}") for i in range(5)])
    chunks = export_default_csv_chunks(df, chunk_size=2)
    assert len(chunks) == 3
    for chunk in chunks:
        assert chunk.strip().splitlines()[0] == "Old Page URL,Destination Page URL, Redirect Type"
    row_counts = [len(c.strip().splitlines()) - 1 for c in chunks]
    assert row_counts == [2, 2, 1]


def test_default_export_chunks_preserve_all_rows_across_files():
    df = pd.DataFrame([_row(f"/old-{i}", f"/new-{i}") for i in range(7)])
    chunks = export_default_csv_chunks(df, chunk_size=3)
    all_old_paths = set()
    for chunk in chunks:
        parsed = pd.read_csv(io.StringIO(chunk))
        all_old_paths.update(parsed[DEFAULT_OLD_COLUMN])
    assert all_old_paths == {f"/old-{i}" for i in range(7)}


def test_default_export_chunks_uses_configured_duda_limit_by_default():
    df = pd.DataFrame([_row(f"/old-{i}", f"/new-{i}") for i in range(MAX_REDIRECTS_PER_CSV + 1)])
    chunks = export_default_csv_chunks(df)
    assert len(chunks) == 2
    assert len(chunks[0].strip().splitlines()) - 1 == MAX_REDIRECTS_PER_CSV
    assert len(chunks[1].strip().splitlines()) - 1 == 1


def test_export_with_template_chunks_splits_when_over_limit():
    df = pd.DataFrame([_row(f"/old-{i}", f"/new-{i}") for i in range(5)])
    headers = ["Source URL", "Destination URL"]
    chunks = export_with_template_chunks(
        df, headers, source_column="Source URL", destination_column="Destination URL", chunk_size=2
    )
    assert len(chunks) == 3
    row_counts = [len(c.strip().splitlines()) - 1 for c in chunks]
    assert row_counts == [2, 2, 1]
    for chunk in chunks:
        assert chunk.strip().splitlines()[0] == "Source URL,Destination URL"


def test_build_export_filename_includes_part_suffix_when_multiple_parts():
    filename = build_export_filename("My Project", part=2, total_parts=3)
    assert "part2-of-3" in filename
    assert filename.startswith("My-Project-redirects-")


def test_build_export_filename_omits_part_suffix_for_single_part():
    filename = build_export_filename("My Project", part=1, total_parts=1)
    assert "part" not in filename
