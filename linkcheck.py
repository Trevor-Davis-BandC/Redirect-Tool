"""Standalone broken-link check for a live site.

Crawls a site's own internal links (the same crawler used elsewhere in the
app) and reports every link that doesn't load, along with the pages that
link to it -- so the person fixing it knows where to go. Nothing here is
specific to redirects or migrations; it's for "is this site's navigation
and content free of dead links?", e.g. as a launch checklist item.

Only internal links are checked. External links are deliberately out of
scope: big sites (LinkedIn, Facebook, Instagram) answer automated requests
with 403/999 whether or not the link works, which would drown the report
in false alarms.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from config import LINKCHECK_TIME_BUDGET_SECONDS, MAX_CRAWL_PAGES
from crawler import BrokenLink, LinkReport, crawl_site_links

COL_BROKEN_LINK = "Broken link"
COL_STATUS = "Status"
COL_PROBLEM = "Problem"
COL_FOUND_ON = "Found on"
COL_PAGES = "Pages linking to it"

# Statuses where the server is refusing automated visitors, not saying the
# page is gone -- real visitors usually load these fine.
_BLOCKED_STATUSES = {401, 403, 429}


def describe_status(status: int) -> str:
    """Plain-English reason for a failed link's status code."""
    if status == 0:
        return "No response (timed out or couldn't connect)"
    if status in (404, 410):
        return "Page not found"
    if status in _BLOCKED_STATUSES:
        return "Blocked or restricted (may load fine for real visitors)"
    if status >= 500:
        return "Server error"
    return "Client error"


def is_hard_failure(status: int) -> bool:
    """True for links that are definitely dead (404/410), as opposed to ones
    the checker merely couldn't open."""
    return status in (404, 410)


@dataclass
class LinkCheckResult:
    domain: str
    pages_crawled: int = 0
    links_checked: int = 0
    broken: list[BrokenLink] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def dead_count(self) -> int:
        return sum(1 for b in self.broken if is_hard_failure(b.status))

    @property
    def other_count(self) -> int:
        return len(self.broken) - self.dead_count


def check_site_links(
    domain_or_url: str,
    max_pages: int = MAX_CRAWL_PAGES,
    time_budget: float | None = LINKCHECK_TIME_BUDGET_SECONDS,
    on_progress: Callable[[int, int], None] | None = None,
) -> LinkCheckResult:
    """Crawl `domain_or_url` and collect every internal link that fails."""
    report = LinkReport()
    crawl = crawl_site_links(
        domain_or_url,
        max_pages=max_pages,
        time_budget=time_budget,
        link_report=report,
        on_progress=on_progress,
    )
    result = LinkCheckResult(
        domain=domain_or_url,
        pages_crawled=len(crawl.urls),
        links_checked=report.links_checked,
        warnings=list(crawl.warnings),
        errors=list(crawl.errors),
        truncated=crawl.truncated,
    )
    # Definitely-dead links first, then by URL so the order is stable.
    result.broken = sorted(report.broken.values(), key=lambda b: (not is_hard_failure(b.status), b.url))
    return result


def broken_links_dataframe(result: LinkCheckResult) -> pd.DataFrame:
    """One row per broken link, for on-screen display."""
    rows = []
    for b in result.broken:
        rows.append(
            {
                COL_BROKEN_LINK: b.url,
                COL_STATUS: b.status if b.status else "none",
                COL_PROBLEM: describe_status(b.status),
                COL_PAGES: len(b.linked_from),
                COL_FOUND_ON: b.linked_from[0] if b.linked_from else "",
            }
        )
    df = pd.DataFrame(rows, columns=[COL_BROKEN_LINK, COL_STATUS, COL_PROBLEM, COL_PAGES, COL_FOUND_ON])
    # Mixed int/"none" would trip Arrow's type conversion in st.dataframe.
    df[COL_STATUS] = df[COL_STATUS].astype(str)
    return df


def broken_links_csv(result: LinkCheckResult) -> bytes:
    """One row per (broken link, page it appears on) -- the shape a person
    fixing links wants: filter or sort by page and work through each one."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([COL_BROKEN_LINK, COL_STATUS, COL_PROBLEM, COL_FOUND_ON])
    for b in result.broken:
        status = b.status if b.status else ""
        problem = describe_status(b.status)
        for page in b.linked_from or [""]:
            writer.writerow([b.url, status, problem, page])
    return out.getvalue().encode("utf-8-sig")


def build_link_check_filename(domain: str, extension: str) -> str:
    safe = re.sub(r"^https?://", "", (domain or "").strip().lower())
    safe = re.sub(r"[^a-z0-9_-]+", "-", safe).strip("-") or "site"
    return f"{safe}-broken-links-{date.today().isoformat()}.{extension}"
