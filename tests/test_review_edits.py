import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from columns import (
    COL_INCLUDE,
    COL_NEW_PATH,
    COL_NEW_URL,
    COL_NOTES,
    COL_OLD_PATH,
    COL_OLD_URL,
    COL_REDIRECT_TYPE,
    COL_STATUS,
    STATUS_APPROVED,
    STATUS_EXCLUDED,
    STATUS_NEEDS_REVIEW,
    STATUS_UNMAPPED,
)
from review_edits import is_in_path_prefix, merge_editor_edits, path_prefix, path_prefix_summary


def _row(old_path, new_path="", status=STATUS_UNMAPPED, include=False):
    return {
        COL_INCLUDE: include,
        COL_OLD_URL: f"https://old.com{old_path}",
        COL_OLD_PATH: old_path,
        COL_NEW_URL: "",
        COL_NEW_PATH: new_path,
        COL_REDIRECT_TYPE: "301",
        COL_STATUS: status,
        COL_NOTES: "",
    }


def test_picking_a_destination_for_an_unmapped_row_redirects_it():
    full = pd.DataFrame([_row("/gone"), _row("/other")])
    edited = full.copy()
    edited.loc[0, COL_NEW_PATH] = "/services"

    merged = merge_editor_edits(full, edited)

    assert merged.loc[0, COL_NEW_PATH] == "/services"
    assert merged.loc[0, COL_STATUS] == STATUS_APPROVED
    assert bool(merged.loc[0, COL_INCLUDE]) is True
    assert merged.loc[1, COL_STATUS] == STATUS_UNMAPPED
    assert bool(merged.loc[1, COL_INCLUDE]) is False


def test_changing_an_existing_destination_leaves_status_alone():
    full = pd.DataFrame([_row("/a", "/b", status=STATUS_NEEDS_REVIEW, include=True)])
    edited = full.copy()
    edited.loc[0, COL_NEW_PATH] = "/c"

    merged = merge_editor_edits(full, edited)

    assert merged.loc[0, COL_STATUS] == STATUS_NEEDS_REVIEW


def test_a_deliberately_excluded_row_is_not_reincluded_by_an_edit_elsewhere():
    full = pd.DataFrame([_row("/same", "/same", status=STATUS_EXCLUDED, include=False)])
    edited = full.copy()
    edited.loc[0, COL_NOTES] = "kept on purpose"

    merged = merge_editor_edits(full, edited)

    assert merged.loc[0, COL_STATUS] == STATUS_EXCLUDED
    assert bool(merged.loc[0, COL_INCLUDE]) is False


def test_path_prefix_is_the_first_segment_only():
    assert path_prefix("/collections/x/products/y") == "/collections"
    assert path_prefix("/") == "/ (home)"
    assert is_in_path_prefix("/products/a", "/products")
    assert not is_in_path_prefix("/collections/x/products/y", "/products")


def test_prefix_summary_counts_unmapped_and_homepage_rows_as_no_match():
    df = pd.DataFrame(
        [
            _row("/products/a"),
            _row("/products/b"),
            _row("/products/c", "/", status=STATUS_APPROVED, include=True),
            _row("/about", "/about-us", status=STATUS_APPROVED, include=True),
            _row("/", "/", status=STATUS_EXCLUDED),
        ]
    )

    summary = path_prefix_summary(df).set_index("Path prefix")

    assert summary.loc["/products", "URLs"] == 3
    assert summary.loc["/products", "No match"] == 3
    assert summary.loc["/products", "No match %"] == 100
    assert summary.loc["/about", "No match"] == 0
    assert summary.loc["/ (home)", "No match"] == 0
    assert path_prefix_summary(df).iloc[0]["Path prefix"] == "/products"
