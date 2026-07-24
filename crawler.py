"""Fallback link-crawler for sites with no discoverable XML sitemap.

Some sites simply don't publish a sitemap anywhere sitemap.py knows to look.
When that happens, this module offers a Screaming-Frog-style fallback:
starting at the site's homepage, follow same-domain <a href> links
breadth-first, up to a safe page limit, and build the URL list from whatever
real pages are actually reachable that way.

Reuses sitemap.py's request/session/SSRF-safety plumbing (fetch, timeout,
User-Agent, blocked-host checks) rather than duplicating it, and returns the
same SitemapResult shape so the rest of the app doesn't need to special-case
a crawl result vs. a sitemap result.
"""

from __future__ import annotations

from collections import deque
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from config import ROBOTS_TXT_PATH, MAX_CRAWL_PAGES, CRAWL_SKIP_EXTENSIONS
from sitemap import (
    SitemapResult,
    BlockedUrlError,
    _normalize_domain_to_base_url,
    _validate_fetchable_url,
    _fetch,
    _friendly_request_error,
)

_SKIP_LINK_SCHEMES = ("#", "mailto:", "tel:", "javascript:")


def _parse_robots_disallow(text: str) -> list[str]:
    """Return Disallow path prefixes for the "User-agent: *" group.

    A deliberately simple prefix-match implementation of the common subset
    of robots.txt -- enough to be a good citizen, not a full spec parser.
    """
    rules: list[str] = []
    applies = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            applies = value == "*"
        elif field == "disallow" and applies and value:
            rules.append(value)
    return rules


def _is_disallowed(path: str, rules: list[str]) -> bool:
    return any(path.startswith(rule) for rule in rules)


def _registrable_netloc(netloc: str) -> str:
    netloc = netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _is_same_site(url: str, root_netloc: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    return _registrable_netloc(parts.netloc) == root_netloc


def _extract_links(page_url: str, html: bytes) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(_SKIP_LINK_SCHEMES):
            continue
        links.append(urljoin(page_url, href))
    return links


def crawl_site_links(domain_or_url: str, max_pages: int = MAX_CRAWL_PAGES) -> SitemapResult:
    """Crawl a site's internal links from its homepage as a sitemap fallback."""
    result = SitemapResult(domain=domain_or_url)

    try:
        base_url = _normalize_domain_to_base_url(domain_or_url)
    except ValueError as exc:
        result.errors.append(str(exc))
        return result

    try:
        _validate_fetchable_url(base_url)
    except BlockedUrlError as exc:
        result.errors.append(str(exc))
        return result

    home_url = base_url + "/"
    result.crawled_from = home_url
    root_netloc = _registrable_netloc(urlsplit(base_url).netloc)

    session = requests.Session()

    disallow_rules: list[str] = []
    robots_url = urljoin(home_url, ROBOTS_TXT_PATH.lstrip("/"))
    try:
        resp = _fetch(robots_url, session)
        if resp.status_code == 200 and resp.text:
            disallow_rules = _parse_robots_disallow(resp.text)
    except (BlockedUrlError, requests.exceptions.RequestException):
        pass  # robots.txt is best-effort; crawling still proceeds without it

    queue: deque[str] = deque([home_url])
    visited: set[str] = set()
    found_urls: list[str] = []
    seen_found: set[str] = set()

    while queue and len(found_urls) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        parts = urlsplit(url)
        if not _is_same_site(url, root_netloc):
            continue
        if _is_disallowed(parts.path or "/", disallow_rules):
            continue
        if parts.path.lower().endswith(CRAWL_SKIP_EXTENSIONS):
            continue

        try:
            resp = _fetch(url, session)
        except BlockedUrlError:
            continue
        except requests.exceptions.RequestException as exc:
            result.warnings.append(_friendly_request_error(exc, url))
            continue

        if resp.status_code >= 400:
            continue
        if "html" not in resp.headers.get("Content-Type", "").lower():
            continue

        final_url = resp.url
        if final_url in seen_found:
            result.duplicates_removed += 1
        else:
            seen_found.add(final_url)
            found_urls.append(final_url)

        for link in _extract_links(final_url, resp.content):
            if link not in visited:
                queue.append(link)

    result.urls = found_urls

    if queue and len(result.urls) >= max_pages:
        result.truncated = True
        result.warnings.append(
            f"Reached the maximum of {max_pages} crawled pages; some pages may not have been discovered."
        )

    if not result.urls:
        result.errors.append(f"No pages could be reached by crawling {base_url}.")

    return result
