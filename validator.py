"""Redirect list validation.

Runs a battery of checks over the reviewed redirect table before export:
duplicate sources, self-redirects, redirect loops/chains, missing or
malformed destinations, homepage fallbacks, external destinations, and
duplicate redirect rules. Findings are split into `critical_errors` (which
block export unless the user opts in to "export despite warnings") and
`warnings` (shown for awareness but non-blocking).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

import pandas as pd

from columns import (
    COL_INCLUDE,
    COL_OLD_PATH,
    COL_NEW_PATH,
    COL_STATUS,
    STATUS_EXCLUDED,
    STATUS_UNMAPPED,
)
from url_normalizer import normalize_path
from config import DESTINATION_REUSE_WARNING_THRESHOLD


@dataclass
class ValidationReport:
    total_old_urls: int = 0
    total_included: int = 0
    total_excluded: int = 0
    total_unmapped: int = 0

    duplicate_source_paths: list[str] = field(default_factory=list)
    duplicate_redirect_rules: list[tuple[str, str]] = field(default_factory=list)
    missing_destinations: list[tuple[str, str]] = field(default_factory=list)
    redirect_loops: list[list[str]] = field(default_factory=list)
    redirect_chains: list[tuple[str, str, str]] = field(default_factory=list)
    self_redirects: list[str] = field(default_factory=list)
    external_destinations: list[tuple[str, str]] = field(default_factory=list)
    homepage_fallbacks: list[str] = field(default_factory=list)
    blank_or_malformed: list[str] = field(default_factory=list)
    overused_destinations: list[tuple[str, int]] = field(default_factory=list)

    critical_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_critical_errors(self) -> bool:
        return bool(self.critical_errors)


def _resolve_destination(raw_dest: str, new_domain_netloc: str) -> tuple[str, bool, bool]:
    """Return (normalized_path, is_external, is_malformed) for a destination value."""
    raw_dest = (raw_dest or "").strip()
    if not raw_dest:
        return "", False, True

    if raw_dest.startswith("//") or "://" in raw_dest:
        parts = urlsplit(raw_dest if "://" in raw_dest else "https:" + raw_dest)
        if not parts.netloc:
            return "", False, True
        netloc = parts.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        is_external = bool(new_domain_netloc) and netloc != new_domain_netloc
        return normalize_path(parts.path or "/"), is_external, False

    if not raw_dest.startswith("/"):
        raw_dest = "/" + raw_dest
    return normalize_path(raw_dest), False, False


def _normalize_new_domain(new_domain: str) -> str:
    new_domain = (new_domain or "").strip()
    if not new_domain:
        return ""
    parts = urlsplit(new_domain if "://" in new_domain else "https://" + new_domain)
    netloc = (parts.netloc or parts.path).lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split("/")[0]


def validate_redirects(
    df: pd.DataFrame,
    new_domain: str = "",
    new_sitemap_paths: set[str] | None = None,
) -> ValidationReport:
    report = ValidationReport()
    report.total_old_urls = len(df)
    new_sitemap_paths = new_sitemap_paths or set()
    new_domain_netloc = _normalize_new_domain(new_domain)

    if COL_STATUS in df.columns:
        report.total_excluded = int((df[COL_STATUS] == STATUS_EXCLUDED).sum())
        report.total_unmapped = int((df[COL_STATUS] == STATUS_UNMAPPED).sum())
    if COL_INCLUDE in df.columns:
        report.total_included = int(df[COL_INCLUDE].fillna(False).astype(bool).sum())

    included = df[df[COL_INCLUDE].fillna(False).astype(bool)] if COL_INCLUDE in df.columns else df

    source_norm_to_paths: dict[str, list[str]] = {}
    rule_pairs: dict[tuple[str, str], int] = {}
    dest_counts: dict[str, int] = {}
    edges: dict[str, str] = {}  # normalized source path -> normalized dest path (included rows only)

    for _, row in included.iterrows():
        old_path = str(row.get(COL_OLD_PATH, "") or "").strip()
        raw_dest = str(row.get(COL_NEW_PATH, "") or "").strip()

        if not old_path:
            report.blank_or_malformed.append("(blank old path)")
            report.critical_errors.append("A redirect is included with a blank source path.")
            continue

        old_norm = normalize_path(old_path)
        dest_norm, is_external, is_malformed = _resolve_destination(raw_dest, new_domain_netloc)

        if is_malformed:
            report.blank_or_malformed.append(old_path)
            report.critical_errors.append(f"'{old_path}' is included but has no valid destination.")
            continue

        source_norm_to_paths.setdefault(old_norm, []).append(old_path)
        edges[old_norm] = dest_norm
        dest_counts[dest_norm] = dest_counts.get(dest_norm, 0) + 1

        pair_key = (old_norm, dest_norm)
        rule_pairs[pair_key] = rule_pairs.get(pair_key, 0) + 1

        if old_norm == dest_norm:
            report.self_redirects.append(old_path)
            report.warnings.append(f"'{old_path}' redirects to itself.")

        if dest_norm == "/" and old_norm != "/":
            report.homepage_fallbacks.append(old_path)
            report.warnings.append(f"'{old_path}' falls back to the homepage ('/'). Confirm this is intentional.")

        if is_external:
            report.external_destinations.append((old_path, raw_dest))
            report.warnings.append(f"'{old_path}' redirects to an external destination: {raw_dest}")

        if new_sitemap_paths and dest_norm not in new_sitemap_paths and not is_external:
            report.missing_destinations.append((old_path, raw_dest))
            report.warnings.append(
                f"The destination for '{old_path}' ('{raw_dest}') was not found in the new sitemap. "
                "If this is intentional (e.g. a manually entered page), no action is needed."
            )

    # Duplicate source paths.
    for norm_path, originals in source_norm_to_paths.items():
        if len(originals) > 1:
            report.duplicate_source_paths.append(norm_path)
            report.critical_errors.append(
                f"'{norm_path}' appears as the source of {len(originals)} included redirects."
            )

    # Duplicate redirect rules (identical source+destination pairs).
    for (src, dest), count in rule_pairs.items():
        if count > 1:
            report.duplicate_redirect_rules.append((src, dest))
            report.warnings.append(f"The redirect rule '{src}' -> '{dest}' is duplicated {count} times.")

    # Redirect chains and loops: does a destination also appear as a source?
    visited_chain_starts: set[str] = set()
    for src, dest in edges.items():
        if dest in edges and dest != src:
            # Detect a loop by walking forward until we revisit a node or exceed the edge count.
            path_chain = [src, dest]
            current = dest
            is_loop = False
            for _ in range(len(edges) + 1):
                nxt = edges.get(current)
                if nxt is None:
                    break
                if nxt == src:
                    is_loop = True
                    break
                if nxt in path_chain:
                    break
                path_chain.append(nxt)
                current = nxt

            if is_loop:
                loop_key = tuple(sorted(path_chain))
                if loop_key not in visited_chain_starts:
                    visited_chain_starts.add(loop_key)
                    report.redirect_loops.append(path_chain + [src])
                    report.critical_errors.append(
                        f"A redirect loop was detected: {' -> '.join(path_chain + [src])}."
                    )
            elif src not in visited_chain_starts:
                visited_chain_starts.add(src)
                report.redirect_chains.append((src, dest, edges[dest]))
                report.warnings.append(
                    f"'{src}' redirects to '{dest}', which itself redirects to '{edges[dest]}'. "
                    f"Consider redirecting '{src}' directly to '{edges[dest]}'."
                )

    # Overused destinations.
    for dest, count in dest_counts.items():
        if count > DESTINATION_REUSE_WARNING_THRESHOLD:
            report.overused_destinations.append((dest, count))
            report.warnings.append(
                f"'{dest}' is used as the destination for {count} redirects. "
                "This can be legitimate, but confirm it isn't a mismatch."
            )

    return report
