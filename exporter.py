"""Duda-compatible CSV export.

The default export matches Duda's bulk URL redirect import template exactly:
three columns -- Old Page URL, Destination Page URL, and Redirect Type (301
or 302) -- with paths only, never a domain. An optional Duda-provided
template CSV can also be uploaded, whose headers, column order, and extra
required columns are preserved.

Duda's importer only accepts MAX_REDIRECTS_PER_CSV rows per file, so the
`_chunks` variants of the export functions split larger redirect lists into
multiple CSV files.
"""

from __future__ import annotations

import io
import re
from datetime import date
from urllib.parse import urlsplit

import pandas as pd

from columns import (
    COL_INCLUDE,
    COL_OLD_PATH,
    COL_NEW_PATH,
    COL_REDIRECT_TYPE,
    COL_STATUS,
    STATUS_UNMAPPED,
    REDIRECT_TYPE_PERMANENT,
)
from config import MAX_REDIRECTS_PER_CSV

# Exact header text expected by Duda's bulk redirect import template. Note
# the leading space before "Redirect Type" -- that's how Duda's own template
# is formatted, so it's preserved verbatim rather than "cleaned up".
DEFAULT_OLD_COLUMN = "Old Page URL"
DEFAULT_NEW_COLUMN = "Destination Page URL"
DEFAULT_REDIRECT_TYPE_COLUMN = " Redirect Type"

SOURCE_COLUMN_HINTS = ["old", "source", "from", "current", "original"]
DEST_COLUMN_HINTS = ["new", "destination", "dest", "to", "target"]
REDIRECT_TYPE_COLUMN_HINTS = ["redirect type", "type", "status code", "code"]


def _to_export_path(value: str) -> str:
    """Reduce a value (path or full URL) to an exportable path: leading slash, no fragment.

    Only the path is ever exported -- any domain (including a temporary
    staging/preview domain) is stripped, since Duda's importer expects a
    path relative to the site it's applied to.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value or value.startswith("//"):
        parts = urlsplit(value if "://" in value else "https:" + value)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
    else:
        path = value
        # Strip a fragment from a bare path like "/page#section".
        path = path.split("#", 1)[0]

    if not path.startswith("/"):
        path = "/" + path
    return path


def _clean_redirect_type(value: str) -> str:
    value = str(value or "").strip()
    return value if value in ("301", "302") else REDIRECT_TYPE_PERMANENT


def build_export_filename(
    project_name: str,
    extension: str = "csv",
    part: int | None = None,
    total_parts: int | None = None,
) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", (project_name or "threeohone").strip()).strip("-")
    safe_name = safe_name or "threeohone"
    today = date.today().isoformat()
    if part is not None and total_parts is not None and total_parts > 1:
        return f"{safe_name}-redirects-{today}-part{part}-of-{total_parts}.{extension}"
    return f"{safe_name}-redirects-{today}.{extension}"


def chunk_rows(rows: list[dict], chunk_size: int = MAX_REDIRECTS_PER_CSV) -> list[list[dict]]:
    """Split a list of export rows into chunks of at most `chunk_size` rows.

    Always returns at least one (possibly empty) chunk, so callers can
    build a CSV even when there's nothing to export.
    """
    if not rows:
        return [[]]
    return [rows[i : i + chunk_size] for i in range(0, len(rows), chunk_size)]


def _csv_text_from_rows(rows: list[dict], columns: list[str]) -> str:
    out_df = pd.DataFrame(rows, columns=columns)
    buf = io.StringIO()
    out_df.to_csv(buf, index=False)
    return buf.getvalue()


def build_default_export_rows(df: pd.DataFrame) -> list[dict]:
    """Build the list of export-ready row dicts, applying all export rules.

    Each dict has keys DEFAULT_OLD_COLUMN, DEFAULT_NEW_COLUMN, and
    DEFAULT_REDIRECT_TYPE_COLUMN.
    """
    rows = []
    seen_sources: set[str] = set()

    for _, row in df.iterrows():
        included = bool(row.get(COL_INCLUDE, False))
        status = str(row.get(COL_STATUS, "") or "")
        if not included or status == STATUS_UNMAPPED:
            continue

        old_path = _to_export_path(str(row.get(COL_OLD_PATH, "") or ""))
        new_path = _to_export_path(str(row.get(COL_NEW_PATH, "") or ""))

        if not old_path or not new_path:
            continue
        if old_path in seen_sources:
            continue
        seen_sources.add(old_path)

        redirect_type = _clean_redirect_type(row.get(COL_REDIRECT_TYPE, REDIRECT_TYPE_PERMANENT))

        rows.append(
            {
                DEFAULT_OLD_COLUMN: old_path,
                DEFAULT_NEW_COLUMN: new_path,
                DEFAULT_REDIRECT_TYPE_COLUMN: redirect_type,
            }
        )

    return rows


def export_default_csv(df: pd.DataFrame) -> str:
    """Return CSV text (UTF-8, quoted as needed) matching Duda's import template.

    Contains every exportable row in one file, ignoring Duda's per-file
    row limit -- use `export_default_csv_chunks` when that limit matters.
    """
    rows = build_default_export_rows(df)
    columns = [DEFAULT_OLD_COLUMN, DEFAULT_NEW_COLUMN, DEFAULT_REDIRECT_TYPE_COLUMN]
    return _csv_text_from_rows(rows, columns)


def export_default_csv_chunks(df: pd.DataFrame, chunk_size: int = MAX_REDIRECTS_PER_CSV) -> list[str]:
    """Return one or more CSV texts, each with at most `chunk_size` rows."""
    rows = build_default_export_rows(df)
    columns = [DEFAULT_OLD_COLUMN, DEFAULT_NEW_COLUMN, DEFAULT_REDIRECT_TYPE_COLUMN]
    return [_csv_text_from_rows(chunk, columns) for chunk in chunk_rows(rows, chunk_size)]


def guess_column_mapping(headers: list[str]) -> dict[str, str | None]:
    """Best-effort guess at which template headers are the source/destination/type columns."""
    source_col = None
    dest_col = None
    redirect_type_col = None

    lowered = {h: h.strip().lower() for h in headers}

    for h, lh in lowered.items():
        if redirect_type_col is None and any(hint in lh for hint in REDIRECT_TYPE_COLUMN_HINTS):
            redirect_type_col = h
            continue
        if source_col is None and any(hint in lh for hint in SOURCE_COLUMN_HINTS):
            source_col = h
        if dest_col is None and any(hint in lh for hint in DEST_COLUMN_HINTS):
            dest_col = h

    return {"source": source_col, "destination": dest_col, "redirect_type": redirect_type_col}


def read_template_headers(file_obj) -> tuple[list[str], pd.DataFrame]:
    """Read an uploaded template CSV, returning (headers, dataframe-of-existing-rows)."""
    df = pd.read_csv(file_obj, dtype=str, keep_default_na=False)
    return list(df.columns), df


def _map_rows_to_template(
    rows: list[dict],
    template_headers: list[str],
    source_column: str,
    destination_column: str,
    redirect_type_column: str | None,
    default_values: dict[str, str] | None,
) -> list[dict]:
    default_values = default_values or {}
    out_rows = []
    for r in rows:
        out_row = {}
        for header in template_headers:
            if header == source_column:
                out_row[header] = r[DEFAULT_OLD_COLUMN]
            elif header == destination_column:
                out_row[header] = r[DEFAULT_NEW_COLUMN]
            elif redirect_type_column is not None and header == redirect_type_column:
                out_row[header] = r[DEFAULT_REDIRECT_TYPE_COLUMN]
            else:
                out_row[header] = default_values.get(header, "")
        out_rows.append(out_row)
    return out_rows


def export_with_template(
    df: pd.DataFrame,
    template_headers: list[str],
    source_column: str,
    destination_column: str,
    redirect_type_column: str | None = None,
    default_values: dict[str, str] | None = None,
) -> str:
    """Build CSV text matching a Duda template's headers and column order.

    Unmapped columns are filled from `default_values` (typically taken from
    an example row in the uploaded template) or left blank; they are never
    derived from the redirect data. Contains every exportable row in one
    file -- use `export_with_template_chunks` when Duda's per-file row
    limit matters.
    """
    rows = build_default_export_rows(df)
    out_rows = _map_rows_to_template(rows, template_headers, source_column, destination_column, redirect_type_column, default_values)
    return _csv_text_from_rows(out_rows, template_headers)


def export_with_template_chunks(
    df: pd.DataFrame,
    template_headers: list[str],
    source_column: str,
    destination_column: str,
    redirect_type_column: str | None = None,
    default_values: dict[str, str] | None = None,
    chunk_size: int = MAX_REDIRECTS_PER_CSV,
) -> list[str]:
    """Return one or more CSV texts matching a Duda template, each with at most `chunk_size` rows."""
    rows = build_default_export_rows(df)
    csv_texts = []
    for chunk in chunk_rows(rows, chunk_size):
        out_rows = _map_rows_to_template(chunk, template_headers, source_column, destination_column, redirect_type_column, default_values)
        csv_texts.append(_csv_text_from_rows(out_rows, template_headers))
    return csv_texts
