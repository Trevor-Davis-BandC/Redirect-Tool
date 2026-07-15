"""Duda-compatible CSV export.

Supports a simple default export (Old URL, New URL columns of paths) and an
optional Duda-provided template CSV whose headers, column order, and extra
required columns are preserved.
"""

from __future__ import annotations

import io
import re
from datetime import date
from urllib.parse import urlsplit

import pandas as pd

from columns import COL_INCLUDE, COL_OLD_PATH, COL_NEW_PATH, COL_STATUS, STATUS_UNMAPPED

DEFAULT_OLD_COLUMN = "Old URL"
DEFAULT_NEW_COLUMN = "New URL"

SOURCE_COLUMN_HINTS = ["old", "source", "from", "current", "original"]
DEST_COLUMN_HINTS = ["new", "destination", "dest", "to", "target", "redirect"]


def _to_export_path(value: str) -> str:
    """Reduce a value (path or full URL) to an exportable path: leading slash, no fragment."""
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


def build_export_filename(project_name: str, extension: str = "csv") -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", (project_name or "migration-mapper").strip()).strip("-")
    safe_name = safe_name or "migration-mapper"
    today = date.today().isoformat()
    return f"{safe_name}-redirects-{today}.{extension}"


def build_default_export_rows(df: pd.DataFrame) -> list[dict]:
    """Build the list of {Old URL, New URL} dicts to export, applying all export rules."""
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

        rows.append({DEFAULT_OLD_COLUMN: old_path, DEFAULT_NEW_COLUMN: new_path})

    return rows


def export_default_csv(df: pd.DataFrame) -> str:
    """Return CSV text (UTF-8, quoted as needed) for the default Duda format."""
    rows = build_default_export_rows(df)
    out_df = pd.DataFrame(rows, columns=[DEFAULT_OLD_COLUMN, DEFAULT_NEW_COLUMN])
    buf = io.StringIO()
    out_df.to_csv(buf, index=False, encoding=None)  # StringIO is already text; encode on write
    return buf.getvalue()


def guess_column_mapping(headers: list[str]) -> dict[str, str | None]:
    """Best-effort guess at which template headers are the source/destination columns."""
    source_col = None
    dest_col = None

    lowered = {h: h.lower() for h in headers}

    for h, lh in lowered.items():
        if source_col is None and any(hint in lh for hint in SOURCE_COLUMN_HINTS):
            source_col = h
        if dest_col is None and any(hint in lh for hint in DEST_COLUMN_HINTS):
            dest_col = h

    return {"source": source_col, "destination": dest_col}


def read_template_headers(file_obj) -> tuple[list[str], pd.DataFrame]:
    """Read an uploaded template CSV, returning (headers, dataframe-of-existing-rows)."""
    df = pd.read_csv(file_obj, dtype=str, keep_default_na=False)
    return list(df.columns), df


def export_with_template(
    df: pd.DataFrame,
    template_headers: list[str],
    source_column: str,
    destination_column: str,
    default_values: dict[str, str] | None = None,
) -> str:
    """Build CSV text matching a Duda template's headers and column order.

    Unmapped columns are filled from `default_values` (typically taken from
    an example row in the uploaded template) or left blank; they are never
    derived from the redirect data.
    """
    default_values = default_values or {}
    rows = build_default_export_rows(df)

    out_rows = []
    for r in rows:
        out_row = {}
        for header in template_headers:
            if header == source_column:
                out_row[header] = r[DEFAULT_OLD_COLUMN]
            elif header == destination_column:
                out_row[header] = r[DEFAULT_NEW_COLUMN]
            else:
                out_row[header] = default_values.get(header, "")
        out_rows.append(out_row)

    out_df = pd.DataFrame(out_rows, columns=template_headers)
    buf = io.StringIO()
    out_df.to_csv(buf, index=False)
    return buf.getvalue()
