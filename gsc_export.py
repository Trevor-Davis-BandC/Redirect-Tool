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
"""

from __future__ import annotations

import io
from urllib.parse import urlsplit

import pandas as pd

from sitemap import SitemapResult, _dedupe_and_truncate_urls

_URL_COLUMN_NAMES = {"url", "page", "address", "old url", "page url"}


def _find_url_column(headers: list[str]) -> tuple[str | None, bool]:
    """Return (column name to use, whether it had to be guessed)."""
    for h in headers:
        if h.strip().lower() in _URL_COLUMN_NAMES:
            return h, False
    return (headers[0], True) if headers else (None, False)


def _is_real_url(value: str) -> bool:
    if not value:
        return False
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


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

    all_urls: list[str] = []
    skipped: list[str] = []
    for raw_value in df[url_column]:
        value = (raw_value or "").strip()
        if not value:
            continue
        if _is_real_url(value):
            all_urls.append(value)
        else:
            skipped.append(value)

    if skipped:
        sample = ", ".join(repr(s) for s in skipped[:5])
        more = f" and {len(skipped) - 5} more" if len(skipped) > 5 else ""
        result.warnings.append(
            f"Skipped {len(skipped)} row(s) with no usable http(s) URL: {sample}{more}."
        )

    if not all_urls:
        result.errors.append(f"No usable page URLs were found in '{filename}'.")
        return result

    result.urls = _dedupe_and_truncate_urls(all_urls, result)
    return result
