"""Wayback Machine (archive.org) URL discovery for dead sites.

Used as a fallback when a site's sitemap can't be found AND it can't be
crawled either -- most commonly because the site itself is dead (domain
expired, hosting cancelled, DNS no longer resolving). The CDX API returns
every URL archive.org has ever captured for a domain, which becomes a
substitute URL list for redirect matching when nothing live is left to read
a sitemap from or crawl.

Nothing here ever fetches the target domain itself -- only archive.org's own
API, with the domain passed as a query string. The returned URLs are used
purely as strings for the redirect-matching pipeline, exactly like sitemap
URLs are, never fetched individually.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import requests

from sitemap import SitemapResult, _dedupe_and_truncate_urls, _normalize_domain_to_base_url
from config import (
    USER_AGENT,
    CRAWL_SKIP_EXTENSIONS,
    WAYBACK_CDX_API_URL,
    WAYBACK_REQUEST_TIMEOUT_SECONDS,
    WAYBACK_CDX_ROW_LIMIT,
    WAYBACK_SKIP_PATH_PREFIXES,
)


def _looks_like_real_page(url: str, mimetype: str, statuscode: str) -> bool:
    """Filter out archived non-page noise: redirects, errors, assets, and
    well-known probe/bot paths that sites accumulate over the years."""
    if statuscode and not statuscode.startswith("2"):
        return False
    if mimetype and mimetype not in ("text/html", "application/xhtml+xml"):
        return False
    path = urlsplit(url).path.lower()
    if path.startswith(WAYBACK_SKIP_PATH_PREFIXES):
        return False
    if any(path.endswith(ext) for ext in CRAWL_SKIP_EXTENSIONS):
        return False
    return True


def fetch_wayback_urls(domain_or_url: str) -> SitemapResult:
    """Query the Wayback Machine's CDX API for every archived page URL under
    a domain, for use as a stand-in "sitemap" when the live site is gone.
    """
    result = SitemapResult(domain=domain_or_url)

    try:
        base_url = _normalize_domain_to_base_url(domain_or_url)
    except ValueError as exc:
        result.errors.append(str(exc))
        return result

    host = urlsplit(base_url).netloc

    params = {
        "url": f"{host}/*",
        "output": "json",
        "fl": "original,mimetype,statuscode",
        "collapse": "urlkey",
        # Filtering server-side (rather than fetching everything and
        # discarding redirects/errors/assets client-side) cuts both payload
        # size and response time dramatically -- an unfiltered query for a
        # site with a long archive history can take over a minute and time
        # out, where the filtered equivalent typically returns in seconds.
        "filter": ["statuscode:200", "mimetype:text/html"],
        "limit": str(WAYBACK_CDX_ROW_LIMIT),
    }

    try:
        resp = requests.get(
            WAYBACK_CDX_API_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=WAYBACK_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        result.errors.append(f"Could not reach the Wayback Machine's archive API: {exc}")
        return result

    if resp.status_code >= 400:
        result.errors.append(f"The Wayback Machine's archive API returned HTTP {resp.status_code}.")
        return result

    try:
        rows = resp.json()
    except ValueError:
        result.errors.append("The Wayback Machine's archive API returned an unreadable response.")
        return result

    if not rows:
        result.errors.append(f"No archived pages were found for {host} in the Wayback Machine.")
        return result

    header, *data_rows = rows
    try:
        url_i = header.index("original")
        mime_i = header.index("mimetype")
        status_i = header.index("statuscode")
    except (ValueError, AttributeError):
        result.errors.append("The Wayback Machine's archive API response was in an unexpected format.")
        return result

    all_urls = []
    for row in data_rows:
        url = row[url_i]
        mimetype = row[mime_i] if mime_i < len(row) else ""
        statuscode = row[status_i] if status_i < len(row) else ""
        if _looks_like_real_page(url, mimetype, statuscode):
            all_urls.append(url)

    if not all_urls:
        result.errors.append(
            f"The Wayback Machine has archived {len(data_rows)} URL(s) for {host}, "
            "but none looked like real pages."
        )
        return result

    result.urls = _dedupe_and_truncate_urls(all_urls, result)
    result.wayback_source = host
    return result
