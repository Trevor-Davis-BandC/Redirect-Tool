"""Redirect list validation.

Runs checks over the reviewed redirect table before export.

Errors (would break a Duda import or the rules involved): duplicate source
paths, blank/malformed destinations, a redirect that points at itself, and
redirect loops. Duda documents that a loop blocks every redirect involved.

Warnings (work, but hurt SEO or won't take effect): duplicate rules, redirect
chains (Google advises redirecting straight to the final URL), many old URLs
redirected to the homepage (Google treats redirecting many old URLs to an
unrelated page as a soft 404), and source URLs Duda can't redirect (it ignores
query strings and can't handle `.php` or `%` in a source).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from columns import COL_INCLUDE, COL_OLD_PATH, COL_NEW_PATH, COL_STATUS, STATUS_EXCLUDED, STATUS_UNMAPPED
from config import HOMEPAGE_REDIRECT_WARNING_THRESHOLD
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
    self_redirects: list[str] = field(default_factory=list)
    redirect_loops: list[str] = field(default_factory=list)
    redirect_chains: list[str] = field(default_factory=list)
    homepage_redirects: list[str] = field(default_factory=list)
    duda_unsupported_sources: list[str] = field(default_factory=list)

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
    graph: dict[str, str] = {}

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

        is_external = "://" in new_path or new_path.startswith("//")
        if old_path == new_path:
            report.self_redirects.append(old_path)
            report.critical_errors.append(
                f"'{old_path}' redirects to itself. Duda blocks every redirect involved in a loop -- "
                "uncheck Include, since an unchanged URL needs no redirect."
            )
        elif not is_external and old_norm != new_norm:
            graph.setdefault(old_norm, new_norm)
            if new_norm == "/" and old_norm != "/":
                report.homepage_redirects.append(old_path)

        if any(marker in old_path for marker in (".php", "%", "?")):
            report.duda_unsupported_sources.append(old_path)

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

    _check_loops_and_chains(graph, report)

    if len(report.homepage_redirects) >= HOMEPAGE_REDIRECT_WARNING_THRESHOLD:
        report.warnings.append(
            f"{len(report.homepage_redirects)} different old URLs are redirected to the homepage. Google treats "
            "redirecting many old URLs to an unrelated page as a soft 404, so those URLs usually do better "
            "left as a 404 unless the homepage really is the right replacement."
        )

    if report.duda_unsupported_sources:
        report.warnings.append(
            f"{len(report.duda_unsupported_sources)} source URL(s) contain .php, %, or a query string, which "
            "Duda can't redirect, so these rules won't take effect: "
            + ", ".join(report.duda_unsupported_sources[:5])
            + ("..." if len(report.duda_unsupported_sources) > 5 else "")
        )

    return report


def _check_loops_and_chains(graph: dict[str, str], report: ValidationReport) -> None:
    """Find redirect loops (critical) and chains (warning) in source -> destination rules."""
    in_loop: set[str] = set()
    reported_loops: set[frozenset[str]] = set()

    for start in graph:
        path = [start]
        seen = {start}
        node = graph[start]
        while node in graph:
            if node in seen:
                cycle = path[path.index(node):]
                key = frozenset(cycle)
                if key not in reported_loops:
                    reported_loops.add(key)
                    in_loop.update(cycle)
                    shown = " -> ".join(cycle + [node])
                    report.redirect_loops.append(shown)
                    report.critical_errors.append(
                        f"Redirect loop: {shown}. Duda blocks every redirect involved in a loop."
                    )
                break
            path.append(node)
            seen.add(node)
            node = graph[node]

    destinations = set(graph.values())
    for start, first in graph.items():
        # Only report from the head of a chain, so A -> B -> C -> D is listed once.
        if start in in_loop or start in destinations or first not in graph:
            continue
        hops = [start, first]
        node = first
        while node in graph and graph[node] not in hops:
            node = graph[node]
            hops.append(node)
        if hops[-1] in in_loop or len(hops) < 3:
            continue
        shown = " -> ".join(hops)
        report.redirect_chains.append(shown)
        report.warnings.append(
            f"Redirect chain: {shown}. Point '{start}' straight at '{hops[-1]}' -- Google advises avoiding chains."
        )
