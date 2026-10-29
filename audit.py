"""Post-launch audit: find which old URLs are actually broken on the live site.

For a site that launched before ThreeOhOne was run, the "old site" no longer
exists -- it was replaced in place on the same domain. So the old URL list is
gathered from wherever it can still be found (the Wayback Machine, pasted
URLs, an uploaded CSV), every URL is re-pointed at the live site's own origin,
and each one is requested to see what it does *today*. Only URLs that now
404/410 need a redirect; ones that still load, or already redirect somewhere
that loads, are left alone so they never become self-redirects in the export.

Safety: every request goes to the live site's own host. Redirects are only
followed while they stay on that same site, and every hop passes the same
network-location guard the sitemap fetcher uses.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from config import (
    AUDIT_MAX_REDIRECT_HOPS,
    AUDIT_MAX_URLS,
    AUDIT_MAX_WORKERS,
    AUDIT_TIME_BUDGET_SECONDS,
    CRAWL_SKIP_EXTENSIONS,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)
from sitemap import (
    BlockedUrlError,
    SitemapResult,
    _dedupe_and_truncate_urls,
    _friendly_request_error,
    _normalize_domain_to_base_url,
    _validate_fetchable_url,
)
from url_normalizer import normalize_path
from wayback import fetch_wayback_urls

VERDICT_LIVE = "Still live"
VERDICT_REDIRECTS = "Already redirects"
VERDICT_BROKEN = "Broken (404/410)"
VERDICT_UNCHECKED = "Couldn't check"

SOURCE_WAYBACK = "Wayback Machine"
SOURCE_CSV = "Uploaded URL list"
SOURCE_PASTED = "Pasted URLs"

def _site_key(host: str) -> str:
    """A host reduced to what identifies the site: lowercase, no port, no www."""
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def _is_same_site(url: str, root_key: str) -> bool:
    """Whether a URL is on the live site. Compares the hostname only, since
    archived URLs commonly carry a default port (http://example.com:80/...)."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and _site_key(parts.hostname or "") == root_key


_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
_BLOCKED_STATUSES = (401, 403, 429)


# ---------------------------------------------------------------------------
# Gathering the old URL list
# ---------------------------------------------------------------------------

def live_origin(new_result: SitemapResult, typed_domain: str) -> str:
    """The live site's scheme://host, preferring whatever discovery actually
    resolved (e.g. an apex domain that forwards to www) over what was typed."""
    for candidate in (new_result.sitemap_url, new_result.crawled_from):
        if candidate:
            parts = urlsplit(candidate)
            if parts.scheme and parts.netloc:
                return f"{parts.scheme}://{parts.netloc}"
    return _normalize_domain_to_base_url(typed_domain)


def to_live_url(value: str, origin: str) -> str | None:
    """Re-point a URL or bare path at the live site's origin.

    Returns None for anything that isn't a page on the live site -- another
    host, a non-http scheme, or an asset file -- since only the live site is
    ever requested.
    """
    value = (value or "").strip()
    if not value:
        return None
    root_key = _site_key(urlsplit(origin).hostname or "")
    parts = urlsplit(value)
    if not (value.startswith("/") and not value.startswith("//")) and not _is_same_site(value, root_key):
        return None
    path = parts.path or "/"
    if path.lower().endswith(CRAWL_SKIP_EXTENSIONS):
        return None
    base = urlsplit(origin)
    return urlunsplit((base.scheme, base.netloc, path, parts.query, ""))


def parse_pasted_lines(text: str) -> list[str]:
    """One URL or path per line. Blank lines and #comments are ignored; a
    line like "www.site.com/about" or "about" is completed sensibly."""
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().strip(",")
        if not line or line.startswith("#"):
            continue
        if "://" in line or line.startswith("/"):
            out.append(line)
        elif "." in line.split("/", 1)[0]:
            out.append("https://" + line)
        else:
            out.append("/" + line)
    return out


def fetch_wayback_variants(domain: str) -> SitemapResult:
    """Wayback lookup for both the typed host and its www/non-www twin, since
    an old site may have been archived under either."""
    result = SitemapResult(domain=domain)
    try:
        host = urlsplit(_normalize_domain_to_base_url(domain)).netloc
    except ValueError as exc:
        result.errors.append(str(exc))
        return result
    twin = host[4:] if host.startswith("www.") else "www." + host

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(fetch_wayback_urls, [host, twin]))

    urls: list[str] = []
    errors: list[str] = []
    for r in results:
        urls.extend(r.urls)
        errors.extend(r.errors)
        if r.wayback_source and not result.wayback_source:
            result.wayback_source = r.wayback_source
    if urls:
        result.urls = _dedupe_and_truncate_urls(urls, result)
    elif errors:
        result.errors.append(errors[0])
    return result


@dataclass
class GatheredUrls:
    result: SitemapResult
    source_counts: dict[str, int] = field(default_factory=dict)
    skipped_off_site: int = 0


def gather_old_urls(
    typed_domain: str,
    origin: str,
    *,
    include_wayback: bool = True,
    csv_result: SitemapResult | None = None,
    pasted_text: str = "",
) -> GatheredUrls:
    """Merge every available source of old URLs into one de-duplicated list
    of live-origin URLs. Pasted URLs come first so a client's specific
    complaints sit at the top of the review table."""
    result = SitemapResult(domain=typed_domain)
    counts: dict[str, int] = {}
    skipped = 0
    all_urls: list[str] = []

    def _absorb(label: str, raw_urls: list[str]) -> None:
        nonlocal skipped
        kept = []
        for raw in raw_urls:
            live = to_live_url(raw, origin)
            if live is None:
                skipped += 1
            else:
                kept.append(live)
        counts[label] = len(kept)
        all_urls.extend(kept)

    pasted = parse_pasted_lines(pasted_text)
    if pasted:
        _absorb(SOURCE_PASTED, pasted)

    if csv_result is not None:
        result.gsc_import_filename = csv_result.gsc_import_filename
        result.warnings.extend(csv_result.warnings)
        result.errors.extend(csv_result.errors)
        if csv_result.urls:
            _absorb(SOURCE_CSV, csv_result.urls)

    if include_wayback:
        wayback = fetch_wayback_variants(typed_domain)
        if wayback.urls:
            result.wayback_source = wayback.wayback_source
            _absorb(SOURCE_WAYBACK, wayback.urls)
        else:
            result.warnings.extend(wayback.errors or [f"No archived pages were found for {typed_domain}."])

    if skipped:
        result.warnings.append(
            f"Ignored {skipped} URL(s) that weren't pages on the live site (another domain, or an image/script/PDF)."
        )

    if all_urls:
        result.urls = _dedupe_and_truncate_urls(all_urls, result)
        # A partial failure (e.g. a bad CSV row) is only a warning once real URLs exist.
        result.warnings.extend(result.errors)
        result.errors = []
    elif not result.errors:
        result.errors.append(
            "No old URLs could be gathered. Turn on the Wayback Machine lookup, paste some URLs, or upload a URL list."
        )
    return GatheredUrls(result=result, source_counts=counts, skipped_off_site=skipped)


# ---------------------------------------------------------------------------
# Checking what each old URL does today
# ---------------------------------------------------------------------------

@dataclass
class UrlCheck:
    old_url: str
    verdict: str
    status_code: int | None = None
    final_url: str = ""
    hops: int = 0
    detail: str = ""


def _fetch_once(url: str, session: requests.Session) -> requests.Response:
    """One GET with redirects left alone, so every hop can be vetted. The body
    is never downloaded -- only the status line and headers are needed."""
    _validate_fetchable_url(url)
    resp = session.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
        stream=True,
    )
    resp.close()
    return resp


def check_url(url: str, root_key: str, session: requests.Session) -> UrlCheck:
    """Classify one URL by following its same-site redirects to the end."""
    current = url
    hops = 0
    while True:
        try:
            resp = _fetch_once(current, session)
        except BlockedUrlError as exc:
            return UrlCheck(url, VERDICT_UNCHECKED, hops=hops, detail=str(exc))
        except requests.RequestException as exc:
            return UrlCheck(url, VERDICT_UNCHECKED, hops=hops, detail=_friendly_request_error(exc, current))

        status = resp.status_code
        if status in _REDIRECT_STATUSES:
            location = resp.headers.get("Location")
            if not location:
                return UrlCheck(url, VERDICT_UNCHECKED, status, hops=hops, detail="Redirect with no destination.")
            target = urljoin(current, location)
            if not _is_same_site(target, root_key):
                return UrlCheck(
                    url, VERDICT_REDIRECTS, status, final_url=target, hops=hops + 1,
                    detail="Redirects to another site.",
                )
            hops += 1
            if hops > AUDIT_MAX_REDIRECT_HOPS:
                return UrlCheck(url, VERDICT_UNCHECKED, status, hops=hops, detail="Too many redirects (possible loop).")
            current = target
            continue

        if 200 <= status < 300:
            if hops == 0:
                return UrlCheck(url, VERDICT_LIVE, status, final_url=current)
            return UrlCheck(url, VERDICT_REDIRECTS, status, final_url=current, hops=hops, detail="Redirects to a working page.")
        if status in (404, 410):
            detail = "Not found." if hops == 0 else "Redirects to a page that is itself not found."
            return UrlCheck(url, VERDICT_BROKEN, status, final_url=current, hops=hops, detail=detail)
        return UrlCheck(url, VERDICT_UNCHECKED, status, final_url=current, hops=hops, detail=f"The site answered HTTP {status}.")


@dataclass
class AuditResult:
    checks: list[UrlCheck] = field(default_factory=list)
    truncated: int = 0

    def count(self, verdict: str) -> int:
        return sum(1 for c in self.checks if c.verdict == verdict)

    @property
    def blocked_suspected(self) -> bool:
        """Most network answers were 401/403/429 -- the site is likely refusing
        ThreeOhOne's requests, so the verdicts can't be trusted."""
        answered = [c for c in self.checks if c.status_code is not None and c.detail != "Listed in the live sitemap."]
        if len(answered) < 5:
            return False
        blocked = sum(1 for c in answered if c.status_code in _BLOCKED_STATUSES)
        return blocked / len(answered) >= 0.5

    def urls_needing_redirect(self, include_unchecked: bool = True) -> list[str]:
        wanted = {VERDICT_BROKEN}
        if include_unchecked:
            wanted.add(VERDICT_UNCHECKED)
        return [c.old_url for c in self.checks if c.verdict in wanted]


_thread_local = threading.local()


def _thread_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def audit_urls(
    urls: list[str],
    origin: str,
    live_paths: set[str],
    progress=None,
    max_workers: int = AUDIT_MAX_WORKERS,
    max_urls: int = AUDIT_MAX_URLS,
    time_budget: float = AUDIT_TIME_BUDGET_SECONDS,
) -> AuditResult:
    """Check every old URL against the live site.

    `live_paths` are the normalized paths in the live sitemap -- a URL whose
    path is listed there is live by definition and is not requested at all.
    `progress(done, total)` is called from the calling thread.
    """
    result = AuditResult()
    root_key = _site_key(urlsplit(origin).hostname or "")

    ordered: list[str] = []
    seen: set[str] = set()
    for u in urls:
        key = normalize_path(urlsplit(u).path)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(u)
    if len(ordered) > max_urls:
        result.truncated = len(ordered) - max_urls
        ordered = ordered[:max_urls]

    total = len(ordered)
    checks: list[UrlCheck | None] = [None] * total
    todo: list[int] = []
    for i, u in enumerate(ordered):
        if normalize_path(urlsplit(u).path) in live_paths:
            checks[i] = UrlCheck(u, VERDICT_LIVE, detail="Listed in the live sitemap.")
        else:
            todo.append(i)

    done = total - len(todo)
    if progress:
        progress(done, total)

    if todo:
        def _work(idx: int) -> UrlCheck:
            return check_url(ordered[idx], root_key, _thread_session())

        pool = ThreadPoolExecutor(max_workers=max_workers)
        futures = {pool.submit(_work, i): i for i in todo}
        try:
            for fut in as_completed(futures, timeout=time_budget):
                checks[futures[fut]] = fut.result()
                done += 1
                if progress:
                    progress(done, total)
        except FuturesTimeout:
            pass
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        for fut, i in futures.items():
            if checks[i] is None:
                checks[i] = UrlCheck(ordered[i], VERDICT_UNCHECKED, detail="Skipped -- the status check ran out of time.")

    result.checks = [c for c in checks if c is not None]
    return result
