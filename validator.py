"""Redirect list validation.

Runs a small set of checks over the reviewed redirect table before export:
duplicate source paths, blank/malformed destinations, and duplicate redirect
rules. These are the checks that would actually break a Duda import or
produce a broken redirect file -- everything else (loops, chains, homepage
fallbacks, external destinations) was dropped as unnecessary noise for this
workflow, where redirecting an unmatched page to the homepage is expected
and not a problem to flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from columns import COL_INCLUDE, COL_OLD_PATH, COL_NEW_PATH, COL_STATUS, STATUS_EXCLUDED, STATUS_UNMAPPED
from url_normalizer import normalize_path


@dataclass
class ValidationReport:
    total_old_urls: int = 0
    total_included: int = 0
    total_excluded: int = 0
    total_unmapped: int = 0

    duplicate_source_paths: list[str] = field(default_factory=list)
    duplicate_redirect_rules: list[tuple[str, str]] = field(default_factory=list)
    blank_or_malformed: list[str] = field(default_factory=list)

    critical_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_critical_errors(self) -> bool:
        return bool(self.critical_errors)


def validate_redirects(
    df: pd.DataFrame,
    new_domain: str = "",
    new_sitemap_paths: set[str] | None = None,
) -> ValidationReport:
    """Validate the redirect table. `new_domain`/`new_sitemap_paths` are accepted
    for backward compatibility with callers but are no longer used by any check.
    """
    report = ValidationReport()
    report.total_old_urls = len(df)

    if COL_STATUS in df.columns:
        report.total_excluded = int((df[COL_STATUS] == STATUS_EXCLUDED).sum())
        report.total_unmapped = int((df[COL_STATUS] == STATUS_UNMAPPED).sum())
    if COL_INCLUDE in df.columns:
        report.total_included = int(df[COL_INCLUDE].fillna(False).astype(bool).sum())

    included = df[df[COL_INCLUDE].fillna(False).astype(bool)] if COL_INCLUDE in df.columns else df

    source_norm_to_paths: dict[str, list[str]] = {}
    rule_pairs: dict[tuple[str, str], int] = {}

    for _, row in included.iterrows():
        old_path = str(row.get(COL_OLD_PATH, "") or "").strip()
        new_path = str(row.get(COL_NEW_PATH, "") or "").strip()

        if not old_path:
            report.blank_or_malformed.append("(blank old path)")
            report.critical_errors.append("A redirect is included with a blank source path.")
            continue

        if not new_path:
            report.blank_or_malformed.append(old_path)
            report.critical_errors.append(f"'{old_path}' is included but has no destination.")
            continue

        old_norm = normalize_path(old_path)
        new_norm = normalize_path(new_path) if not ("://" in new_path or new_path.startswith("//")) else new_path

        source_norm_to_paths.setdefault(old_norm, []).append(old_path)

        pair_key = (old_norm, new_norm)
        rule_pairs[pair_key] = rule_pairs.get(pair_key, 0) + 1

    for norm_path, originals in source_norm_to_paths.items():
        if len(originals) > 1:
            report.duplicate_source_paths.append(norm_path)
            report.critical_errors.append(
                f"'{norm_path}' appears as the source of {len(originals)} included redirects."
            )

    for (src, dest), count in rule_pairs.items():
        if count > 1:
            report.duplicate_redirect_rules.append((src, dest))
            report.warnings.append(f"The redirect rule '{src}' -> '{dest}' is duplicated {count} times.")

    return report
