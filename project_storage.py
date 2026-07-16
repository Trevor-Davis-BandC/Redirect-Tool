"""Local project save/load as JSON. No database required.

The project file captures everything needed to resume a migration: domains,
discovered sitemap locations and URLs, the redirect table (including manual
edits, include/exclude flags, and notes), and the most recent validation
summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import APP_VERSION

REQUIRED_TOP_LEVEL_KEYS = [
    "app_version",
    "project_name",
    "old_domain",
    "new_domain",
    "old_sitemap_override",
    "new_sitemap_override",
    "old_sitemap_url",
    "new_sitemap_url",
    "old_urls",
    "new_urls",
    "duplicates_removed_old",
    "duplicates_removed_new",
    "redirect_table",
    "validation_summary",
]


class ProjectFileError(Exception):
    """Raised when a project JSON file is missing required data or malformed."""


def build_project_dict(
    project_name: str,
    old_domain: str,
    new_domain: str,
    old_sitemap_override: str,
    new_sitemap_override: str,
    old_sitemap_url: str,
    new_sitemap_url: str,
    old_urls: list[str],
    new_urls: list[str],
    duplicates_removed_old: int,
    duplicates_removed_new: int,
    redirect_table: pd.DataFrame,
    validation_summary: dict[str, Any] | None = None,
) -> dict:
    return {
        "app_version": APP_VERSION,
        "project_name": project_name,
        "old_domain": old_domain,
        "new_domain": new_domain,
        "old_sitemap_override": old_sitemap_override,
        "new_sitemap_override": new_sitemap_override,
        "old_sitemap_url": old_sitemap_url,
        "new_sitemap_url": new_sitemap_url,
        "old_urls": old_urls,
        "new_urls": new_urls,
        "duplicates_removed_old": duplicates_removed_old,
        "duplicates_removed_new": duplicates_removed_new,
        "redirect_table": redirect_table.to_dict(orient="records") if redirect_table is not None else [],
        "validation_summary": validation_summary or {},
    }


def save_project_json(project: dict) -> str:
    """Serialize a project dict to a pretty-printed JSON string."""
    return json.dumps(project, indent=2, ensure_ascii=False)


def load_project_json(raw: str | bytes) -> dict:
    """Parse and lightly validate a project JSON file, filling in safe defaults."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProjectFileError(f"This file is not valid JSON ({exc}).") from exc

    if not isinstance(data, dict):
        raise ProjectFileError("This file does not contain a Redirect Tool project object.")

    defaults = {
        "app_version": APP_VERSION,
        "project_name": "",
        "old_domain": "",
        "new_domain": "",
        "old_sitemap_override": "",
        "new_sitemap_override": "",
        "old_sitemap_url": "",
        "new_sitemap_url": "",
        "old_urls": [],
        "new_urls": [],
        "duplicates_removed_old": 0,
        "duplicates_removed_new": 0,
        "redirect_table": [],
        "validation_summary": {},
    }
    for key, default_value in defaults.items():
        data.setdefault(key, default_value)

    if not isinstance(data["redirect_table"], list):
        raise ProjectFileError("The project's redirect table is malformed.")

    return data


def redirect_table_to_dataframe(redirect_table: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(redirect_table)
