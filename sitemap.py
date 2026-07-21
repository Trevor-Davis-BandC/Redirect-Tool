"""Sitemap discovery and parsing.

Given a domain (or an explicit sitemap URL override), this module finds and
parses the site's XML sitemap(s) -- including sitemap index files and
nested sitemaps -- and returns a flat, deduplicated list of page URLs.

Safety features:
- Blocks localhost / private-network / file:// targets (SSRF guard)
- Uses defused XML parsing settings (no external entity resolution)
- Enforces limits on sitemap file count, URL count, and recursion depth
- Uses a descriptive User-Agent and a request timeout
- Never crashes the caller -- all failures are returned as SitemapResult
  warnings/errors rather than raised exceptions
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import requests
from lxml import etree

from config import (
    MAX_SITEMAP_FILES,
    MAX_URLS_PER_SITE,
    MAX_SITEMAP_RECURSION_DEPTH,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    SITEMAP_CANDIDATE_PATHS,
    ROBOTS_TXT_PATH,
    BLOCKED_HOSTNAMES,
)

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

# A parser that disables entity resolution / network access to prevent XXE
# and billion-laughs style attacks.
_SAFE_XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    dtd_validation=False,
    load_dtd=False,
    huge_tree=False,
)


@dataclass
class SitemapResult:
    domain: str
    sitemap_url: str | None = None
    urls: list[str] = field(default_factory=list)
    sitemap_files_used: list[str] = field(default_factory=list)
    duplicates_removed: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def success(self) -> bool:
        return bool(self.urls) and not self.errors


class BlockedUrlError(Exception):
    """Raised internally when a URL targets a disallowed network location."""


def _normalize_domain_to_base_url(domain: str) -> str:
    domain = domain.strip()
    if not domain:
        raise ValueError("Domain cannot be empty.")
    if not domain.startswith(("http://", "https://")):
        domain = "https://" + domain
    parts = urlsplit(domain)
    if not parts.netloc:
        raise ValueError(f"'{domain}' does not look like a valid domain or URL.")
    return f"{parts.scheme}://{parts.netloc}"


def _is_blocked_host(hostname: str) -> bool:
    """Guard against SSRF: block localhost, private/reserved IPs, etc."""
    if not hostname:
        return True
    host = hostname.lower()
    if host in BLOCKED_HOSTNAMES or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
    except ValueError:
        pass
    # Resolve hostname and check the resulting IPs too.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False  # let the request fail naturally with a friendly error
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def _validate_fetchable_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedUrlError(f"Refusing to fetch non-HTTP(S) URL: {url}")
    if _is_blocked_host(parts.hostname or ""):
        raise BlockedUrlError(f"Refusing to fetch a local/private network address: {url}")


def _fetch(url: str, session: requests.Session) -> requests.Response:
    _validate_fetchable_url(url)
    headers = {"User-Agent": USER_AGENT}
    return session.get(
        url,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=True,
    )


def _friendly_request_error(exc: Exception, url: str) -> str:
    if isinstance(exc, requests.exceptions.SSLError):
        return f"An SSL/certificate error occurred while contacting {url}. The site's certificate may be invalid."
    if isinstance(exc, requests.exceptions.ConnectTimeout) or isinstance(exc, requests.exceptions.ReadTimeout):
        return f"The request to {url} timed out after {REQUEST_TIMEOUT_SECONDS} seconds."
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"Could not connect to {url}. Check that the domain is correct and reachable."
    if isinstance(exc, BlockedUrlError):
        return str(exc)
    return f"An unexpected error occurred while contacting {url}: {exc}"


def _parse_robots_txt_for_sitemaps(text: str) -> list[str]:
    sitemaps = []
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            value = line.split(":", 1)[1].strip()
            if value:
                sitemaps.append(value)
    return sitemaps


def _discover_candidate_sitemap_urls(base_url: str, session: requests.Session, warnings: list[str]) -> list[str]:
    """Return an ordered, deduplicated list of sitemap URLs to try."""
    candidates: list[str] = []

    robots_url = urljoin(base_url + "/", ROBOTS_TXT_PATH.lstrip("/"))
    try:
        resp = _fetch(robots_url, session)
        if resp.status_code == 200 and resp.text:
            found = _parse_robots_txt_for_sitemaps(resp.text)
            for sm in found:
                resolved = urljoin(base_url + "/", sm)
                if resolved not in candidates:
                    candidates.append(resolved)
        elif resp.status_code >= 400:
            warnings.append(f"robots.txt returned HTTP {resp.status_code}; falling back to common sitemap paths.")
    except BlockedUrlError as exc:
        warnings.append(str(exc))
    except requests.exceptions.RequestException as exc:
        warnings.append(_friendly_request_error(exc, robots_url))

    for path in SITEMAP_CANDIDATE_PATHS:
        resolved = urljoin(base_url + "/", path.lstrip("/"))
        if resolved not in candidates:
            candidates.append(resolved)

    return candidates


def _looks_like_xml(content_type: str, body: bytes) -> bool:
    if "xml" in (content_type or "").lower():
        return True
    stripped = body.lstrip()[:200]
    return stripped.startswith(b"<?xml") or stripped.startswith(b"<")


def _local_tag(element) -> str:
    tag = element.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_sitemap_xml(body: bytes):
    """Return (kind, entries) where kind is 'urlset' or 'sitemapindex'.

    entries is a list of (loc, lastmod) tuples for urlset, or a list of loc
    strings for sitemapindex. Raises etree.XMLSyntaxError on malformed XML.
    """
    root = etree.fromstring(body, parser=_SAFE_XML_PARSER)
    root_tag = _local_tag(root)

    if root_tag == "sitemapindex":
        locs = []
        for sitemap_el in root:
            if _local_tag(sitemap_el) != "sitemap":
                continue
            loc = None
            for child in sitemap_el:
                if _local_tag(child) == "loc":
                    loc = (child.text or "").strip()
            if loc:
                locs.append(loc)
        return "sitemapindex", locs

    if root_tag == "urlset":
        urls = []
        for url_el in root:
            if _local_tag(url_el) != "url":
                continue
            loc = None
            for child in url_el:
                if _local_tag(child) == "loc":
                    loc = (child.text or "").strip()
            if loc:
                urls.append(loc)
        return "urlset", urls

    # Some feeds are a bare <urlset>-less list, or use rss-style feeds; treat
    # unknown root elements as "no URLs found".
    return "unknown", []


def _crawl_sitemap(
    url: str,
    session: requests.Session,
    depth: int,
    visited: set[str],
    all_urls: list[str],
    files_used: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    if depth > MAX_SITEMAP_RECURSION_DEPTH:
        warnings.append(f"Stopped following nested sitemaps at {url}: maximum recursion depth reached.")
        return
    if url in visited:
        return
    visited.add(url)
    if len(files_used) >= MAX_SITEMAP_FILES:
        warnings.append("Reached the maximum number of sitemap files; some sitemaps may not have been read.")
        return
    if len(all_urls) >= MAX_URLS_PER_SITE:
        return

    try:
        resp = _fetch(url, session)
    except BlockedUrlError as exc:
        errors.append(str(exc))
        return
    except requests.exceptions.RequestException as exc:
        warnings.append(_friendly_request_error(exc, url))
        return

    if resp.status_code == 404:
        return
    if resp.status_code >= 400:
        warnings.append(f"{url} returned HTTP {resp.status_code}.")
        return

    if not _looks_like_xml(resp.headers.get("Content-Type", ""), resp.content):
        warnings.append(f"{url} did not look like an XML sitemap and was skipped.")
        return

    try:
        kind, entries = _parse_sitemap_xml(resp.content)
    except etree.XMLSyntaxError as exc:
        warnings.append(f"{url} could not be parsed as XML ({exc}).")
        return

    files_used.append(resp.url)  # resp.url reflects the final URL after redirects

    if kind == "sitemapindex":
        for child_loc in entries:
            if len(files_used) >= MAX_SITEMAP_FILES:
                warnings.append("Reached the maximum number of sitemap files; some sitemaps may not have been read.")
                break
            resolved = urljoin(url, child_loc)
            _crawl_sitemap(resolved, session, depth + 1, visited, all_urls, files_used, warnings, errors)
            if len(all_urls) >= MAX_URLS_PER_SITE:
                break
    elif kind == "urlset":
        for loc in entries:
            if len(all_urls) >= MAX_URLS_PER_SITE:
                warnings.append(f"Reached the maximum of {MAX_URLS_PER_SITE} URLs; additional URLs were ignored.")
                break
            all_urls.append(urljoin(url, loc))
    else:
        warnings.append(f"{url} was valid XML but was not a recognized sitemap format.")


def discover_and_parse_sitemap(domain_or_url: str, override_sitemap_url: str | None = None) -> SitemapResult:
    """Discover and fully parse the sitemap(s) for a domain.

    If override_sitemap_url is given, it is used directly (still subject to
    the same safety and recursion rules) instead of probing robots.txt and
    common paths.
    """
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

    session = requests.Session()
    all_urls: list[str] = []
    files_used: list[str] = []
    visited: set[str] = set()

    if override_sitemap_url:
        candidates = [override_sitemap_url]
    else:
        candidates = _discover_candidate_sitemap_urls(base_url, session, result.warnings)

    found = False
    attempt_warnings: list[str] = []
    for candidate in candidates:
        attempt_urls: list[str] = []
        attempt_files: list[str] = []
        attempt_errors: list[str] = []
        local_warnings: list[str] = []
        _crawl_sitemap(candidate, session, 0, set(), attempt_urls, attempt_files, local_warnings, attempt_errors)

        if attempt_errors:
            result.errors.extend(attempt_errors)
            continue

        if attempt_urls:
            all_urls = attempt_urls
            files_used = attempt_files
            result.sitemap_url = candidate
            result.warnings.extend(local_warnings)
            found = True
            break
        elif local_warnings:
            # Preserve the specific reason (HTTP status, non-XML content,
            # parse failure, timeout, ...) instead of losing it in favor of
            # a generic "not found" message.
            attempt_warnings.extend(local_warnings)
        else:
            attempt_warnings.append(f"No page URLs were found at {candidate}.")

    if not found:
        if not result.errors:
            result.warnings.extend(attempt_warnings)
            result.errors.append(
                "No sitemap was found automatically. Enter the sitemap URL manually and try again."
            )
        return result

    # Deduplicate while counting duplicates removed, preserving first-seen order.
    seen = set()
    deduped = []
    for u in all_urls:
        if u in seen:
            result.duplicates_removed += 1
            continue
        seen.add(u)
        deduped.append(u)

    if len(deduped) > MAX_URLS_PER_SITE:
        deduped = deduped[:MAX_URLS_PER_SITE]
        result.truncated = True
        result.warnings.append(f"Only the first {MAX_URLS_PER_SITE} URLs were kept due to the configured limit.")

    result.urls = deduped
    result.sitemap_files_used = files_used
    return result
