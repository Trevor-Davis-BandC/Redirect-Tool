"""Pure helpers behind the Redirect Review page.

Kept out of app.py so they can be tested without running the Streamlit script.
"""

from __future__ import annotations

import pandas as pd

from columns import (
    COL_INCLUDE,
    COL_NEW_PATH,
    COL_OLD_PATH,
    COL_OLD_URL,
    COL_STATUS,
    STATUS_APPROVED,
    STATUS_UNMAPPED,
)


def path_prefix(path: str) -> str:
    """The first path segment, e.g. "/collections/x/products/y" -> "/collections".

    Deliberately NOT a substring match -- "/collections/x/products/y" contains
    the text "/products" but does not belong under the "/products" prefix, so
    this only ever looks at the leading segment, not anywhere else in the path.
    """
    segments = [s for s in (path or "").split("/") if s]
    return "/" + segments[0] if segments else "/ (home)"


def is_in_path_prefix(path: str, prefix: str) -> bool:
    if prefix == "/ (home)":
        return not path or path == "/"
    return path == prefix or path.startswith(prefix + "/")


def path_prefix_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Group old paths by their first path segment and show, per group, how
    many had no match (Unmapped, or pointed at the homepage) -- a prefix where
    most URLs had no match suggests that whole section structurally doesn't belong on the new site
    (e.g. an old platform's full product catalog, which has nothing to match
    against on a small marketing site), worth noticing before reviewing rows
    one at a time. Platform-agnostic by design: it's just "did this whole
    group fail to match," not a guess at any particular platform's URLs.
    """
    work = df[[COL_OLD_PATH, COL_NEW_PATH, COL_STATUS]].copy()
    work["_prefix"] = work[COL_OLD_PATH].map(path_prefix)
    work["_defaulted"] = (work[COL_STATUS] == STATUS_UNMAPPED) | (
        (work[COL_NEW_PATH] == "/") & (work[COL_OLD_PATH] != "/")
    )

    rows = []
    for prefix, group in work.groupby("_prefix"):
        total = len(group)
        defaulted = int(group["_defaulted"].sum())
        rows.append(
            {
                "Path prefix": prefix,
                "URLs": total,
                "No match": defaulted,
                "No match %": round(100 * defaulted / total) if total else 0,
                "Example": group[COL_OLD_PATH].iloc[0],
            }
        )
    summary = pd.DataFrame(rows, columns=["Path prefix", "URLs", "No match", "No match %", "Example"])
    return summary.sort_values("No match", ascending=False).reset_index(drop=True)


def is_blank(value) -> bool:
    return value is None or bool(pd.isna(value)) or str(value).strip() == ""


def merge_editor_edits(full_df: pd.DataFrame, edited: pd.DataFrame) -> pd.DataFrame:
    """Fold the review table's edits (keyed by Old URL) back into the full table.

    Choosing a destination for a row that had none -- an Unmapped row, left
    without a redirect on purpose -- is an explicit decision to redirect it,
    so it is switched to Approved and included, rather than making the person
    also hunt for the Include checkbox and Status.
    """
    full = full_df.set_index(COL_OLD_URL, drop=False)
    edited_indexed = edited.set_index(COL_OLD_URL, drop=False)
    for old_url, edited_row in edited_indexed.iterrows():
        edited_row = edited_row.copy()
        picked_destination = is_blank(full.loc[old_url, COL_NEW_PATH]) and not is_blank(edited_row[COL_NEW_PATH])
        if picked_destination and edited_row[COL_STATUS] == STATUS_UNMAPPED and not edited_row[COL_INCLUDE]:
            edited_row[COL_STATUS] = STATUS_APPROVED
            edited_row[COL_INCLUDE] = True
        full.loc[old_url] = edited_row
    return full.reset_index(drop=True)
