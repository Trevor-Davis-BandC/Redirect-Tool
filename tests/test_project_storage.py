import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from columns import COL_OLD_PATH, COL_REDIRECT_TYPE, REDIRECT_TYPE_PERMANENT, REDIRECT_TYPE_TEMPORARY
from project_storage import redirect_table_to_dataframe


def test_legacy_302_rows_are_normalized_to_301_on_load():
    """Regression test: a project saved before the "always 301" policy can
    have 302s baked into its redirect table. Loading it must not resurrect
    those -- every row becomes 301, same as a freshly generated project.
    """
    table = [
        {COL_OLD_PATH: "/a", COL_REDIRECT_TYPE: REDIRECT_TYPE_PERMANENT},
        {COL_OLD_PATH: "/b", COL_REDIRECT_TYPE: REDIRECT_TYPE_TEMPORARY},
        {COL_OLD_PATH: "/c", COL_REDIRECT_TYPE: "garbage"},
    ]

    df = redirect_table_to_dataframe(table)

    assert (df[COL_REDIRECT_TYPE] == REDIRECT_TYPE_PERMANENT).all()


def test_empty_redirect_table_does_not_error():
    df = redirect_table_to_dataframe([])
    assert df.empty
