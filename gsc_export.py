"""Google Search Console (or similar tool's) URL-list CSV parsing.

GSC's "Page indexing" report lets you drill into a reason (e.g. "Not found
(404)") and export the affected URLs as a CSV. This module turns that CSV
into the same SitemapResult shape the rest of the app already works with,
so a list of 404'd URLs can be matched against a site's own current
sitemap and turned into redirects exactly like a migration's old-site
list -- without ever fetching any of the 404 URLs themselves, since GSC
already told us they don't resolve.

Real-world exports are messier than sitemaps: they can include blank rows
or robots.txt-style wildcard patterns (e.g. "/wp-content/plugins/*") that
GSC is still flagging as a 404. Those are kept, not discarded -- if GSC
flagged it, it needs a redirect (typically to home) and a human revalidates
in GSC afterward; only rows with no usable http(s) URL at all are skipped.

A site-crawl export (Screaming Frog and similar tools) is a different
animal, though: it's every URL the crawler touched, not a pre-filtered
list of known problems, so it includes images, scripts, PDFs, and broken
or redirecting links alongside real pages -- none of which should turn
into a suggested redirect. When the CSV has its own Status Code and/or
Content Type columns (as Screaming Frog's exports do, but a bare GSC
export never does), those are used to keep only live HTML pages; a CSV
with neither column is trusted as-is, exactly like before.
"""

from __future__ import annotations

import io
from urllib.parse import urlsplit

import pandas as pd

from sitemap import SitemapResult, _dedupe_and_truncate_urls
from config import CRAWL_SKIP_EXTENSIONS

_URL_COLUMN_NAMES = {"url", "page", "address", "old url", "page url"}
_STATUS_COLUMN_NAMES = {"status code", "status_code", "statuscode", "http status", "response code"}
_CONTENT_TYPE_COLUMN_NAMES = {"content type", "content_type", "contenttype", "mime type", "mimetype"}


def _find_url_column(headers: list[str]) -> tuple[str | None, bool]:
    """Return (column name to use, whether it had to be guessed)."""
    for h in headers:
        if h.strip().lower() in _URL_COLUMN_NAMES:
            return h, False
    return (headers[0], True) if headers else (None, False)


def _find_optional_column(headers: list[str], names: set[str]) -> str | None:
    for h in headers:
        if h.strip().lower() in names:
            return h
    return None


def _is_real_url(value: str) -> bool:
    if not value:
        return False
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _status_looks_live(value: str) -> bool:
    """True for a blank value (nothing to judge by) or one starting with
    "2" (Screaming Frog writes plain codes like "200", but also things like
    "200 OK" -- only the leading digit matters)."""
    value = (value or "").strip()
    return not value or value[:1] == "2"


def _content_type_looks_like_html(value: str) -> bool:
    value = (value or "").strip().lower()
    return not value or value.startswith(("text/html", "application/xhtml+xml"))


def parse_gsc_csv(file_bytes: bytes, filename: str, domain_or_url: str = "") -> SitemapResult:
    """Parse a GSC (or Screaming Frog, etc.) URL-list CSV export."""
    result = SitemapResult(domain=domain_or_url or filename)
    result.gsc_import_filename = filename

    try:
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
    except Exception as exc:
        result.errors.append(f"Could not read '{filename}' as a CSV file: {exc}")
        return result

    headers = list(df.columns)
    url_column, guessed = _find_url_column(headers)
    if url_column is None:
        result.errors.append(f"'{filename}' does not appear to have any columns.")
        return result
    if guessed:
        result.warnings.append(
            f"No column named \"URL\" was found in '{filename}'; used the first column "
            f'("{url_column}") instead.'
        )

    status_column = _find_optional_column(headers, _STATUS_COLUMN_NAMES)
    content_type_column = _find_optional_column(headers, _CONTENT_TYPE_COLUMN_NAMES)
    # A site-crawl export identifies itself by carrying its own Status Code
    # and/or Content Type columns -- only then do we filter to live HTML
    # pages. A bare GSC-style export (just a URL column) is trusted as-is,
    # unchanged from before.
    is_crawl_export = status_column is not None or content_type_column is not None

    all_urls: list[str] = []
    skipped: list[str] = []
    skipped_non_html = 0
    for _, row in df.iterrows():
        value = (row[url_column] or "").strip()
        if not value:
            continue
        if not _is_real_url(value):
            skipped.append(value)
            continue
        if is_crawl_export:
            status_ok = status_column is None or _status_looks_live(row[status_column])
            type_ok = content_type_column is None or _content_type_looks_like_html(row[content_type_column])
            is_asset_path = urlsplit(value).path.lower().endswith(CRAWL_SKIP_EXTENSIONS)
            if not status_ok or not type_ok or is_asset_path:
                skipped_non_html += 1
                continue
        all_urls.append(value)

    if skipped:
        sample = ", ".join(repr(s) for s in skipped[:5])
        more = f" and {len(skipped) - 5} more" if len(skipped) > 5 else ""
        result.warnings.append(
            f"Skipped {len(skipped)} row(s) with no usable http(s) URL: {sample}{more}."
        )

    if skipped_non_html:
        result.warnings.append(
            f"Skipped {skipped_non_html} row(s) that weren't a live HTML page (non-200 status, "
            "non-HTML content type, or an asset file), based on the CSV's own Status Code / "
            "Content Type columns."
        )

    if not all_urls:
        result.errors.append(f"No usable page URLs were found in '{filename}'.")
        return result

    result.urls = _dedupe_and_truncate_urls(all_urls, result)
    return result
