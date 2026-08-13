import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import requests

import sitemap

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status_code, content, content_type="application/xml", url=None, location=None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.headers = {"Content-Type": content_type}
        if location:
            self.headers["Location"] = location
        self.url = url or ""


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def make_fake_fetch(url_map):
    def _fake_fetch(url, session, allow_redirects=True):
        entry = url_map.get(url)
        if entry is None:
            return FakeResponse(404, b"Not Found", "text/plain", url)
        if isinstance(entry, Exception):
            raise entry
        return entry
    return _fake_fetch


def test_urlset_simple_and_duplicate_removal(monkeypatch):
    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain", "https://example.com/robots.txt"),
        "https://example.com/sitemap.xml": FakeResponse(
            200, _read("urlset_simple.xml"), "application/xml", "https://example.com/sitemap.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.sitemap_url == "https://example.com/sitemap.xml"
    assert result.duplicates_removed == 1
    assert len(result.urls) == 3
    assert not result.errors


def test_query_string_variants_of_the_same_page_are_deduped(monkeypatch):
    """Regression test: a quoting widget or similar dynamic page often
    appears in a sitemap many times over with only a query string differing
    (e.g. "?catsvc=7102005|7109679" vs "?catsvc=7102005|7109684"). Since only
    the path is ever exported, these are the same destination for redirect
    purposes and should collapse to one row, not one per query variant.
    """
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/quote</loc></url>
      <url><loc>https://example.com/quote?catsvc=7102005|7109679</loc></url>
      <url><loc>https://example.com/quote?catsvc=7102005|7109684</loc></url>
      <url><loc>https://example.com/quote?svc=[GEODIRECTIONLINK]</loc></url>
      <url><loc>https://example.com/about-us</loc></url>
    </urlset>"""
    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap.xml": FakeResponse(200, xml, "application/xml", "https://example.com/sitemap.xml"),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert len(result.urls) == 2
    assert result.duplicates_removed == 3
    assert not result.errors


def test_sitemap_index_with_nested_sitemaps(monkeypatch):
    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap.xml": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap_index.xml": FakeResponse(
            200, _read("sitemap_index.xml"), "application/xml", "https://example.com/sitemap_index.xml"
        ),
        "https://example.com/sitemap-pages.xml": FakeResponse(
            200, _read("sitemap_pages.xml"), "application/xml", "https://example.com/sitemap-pages.xml"
        ),
        "https://example.com/sitemap-posts.xml": FakeResponse(
            200, _read("sitemap_posts.xml"), "application/xml", "https://example.com/sitemap-posts.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.sitemap_url == "https://example.com/sitemap_index.xml"
    assert len(result.urls) == 4
    assert not result.errors


def test_no_sitemap_found_gives_friendly_error(monkeypatch):
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch({}))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.urls == []
    assert result.errors
    assert "manually" in result.errors[0].lower()


def test_sitemap_override_is_used_directly(monkeypatch):
    url_map = {
        "https://example.com/custom-sitemap.xml": FakeResponse(
            200, _read("urlset_simple.xml"), "application/xml", "https://example.com/custom-sitemap.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap(
        "example.com", override_sitemap_url="https://example.com/custom-sitemap.xml"
    )

    assert result.sitemap_url == "https://example.com/custom-sitemap.xml"
    assert len(result.urls) == 3


def test_self_referencing_sitemap_index_does_not_infinite_loop(monkeypatch):
    loop_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/loop.xml</loc></sitemap>
    </sitemapindex>"""
    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap.xml": FakeResponse(200, loop_xml, "application/xml", "https://example.com/sitemap.xml"),
        "https://example.com/loop.xml": FakeResponse(200, loop_xml, "application/xml", "https://example.com/loop.xml"),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    # Should terminate without hanging and without finding any actual page URLs.
    assert result.urls == []


def test_blocked_localhost_domain_is_rejected():
    result = sitemap.discover_and_parse_sitemap("localhost")
    assert result.urls == []
    assert result.errors
    assert "local" in result.errors[0].lower() or "private" in result.errors[0].lower()


def test_blocked_private_ip_is_rejected():
    result = sitemap.discover_and_parse_sitemap("192.168.1.5")
    assert result.urls == []
    assert result.errors


def test_blocked_candidate_surfaces_specific_reason_not_generic_message(monkeypatch):
    """Regression test: when a real sitemap candidate is blocked (e.g. bot
    protection returning 403) or otherwise fails with a specific, known
    reason, that reason must reach the caller instead of being discarded in
    favor of a generic "No page URLs were found" message.
    """
    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap.xml": FakeResponse(403, b"Forbidden", "text/html", "https://example.com/sitemap.xml"),
        "https://example.com/sitemap_index.xml": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap-index.xml": FakeResponse(404, b"", "text/plain"),
        "https://example.com/wp-sitemap.xml": FakeResponse(404, b"", "text/plain"),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.urls == []
    all_messages = " ".join(result.warnings + result.errors)
    assert "403" in all_messages
    assert "sitemap.xml" in all_messages


def test_unescaped_ampersand_is_recovered_not_rejected(monkeypatch):
    """A stray unescaped "&" in a <loc> is a common real-world bug in
    auto-generated WordPress sitemaps. The parser should recover and still
    extract the real URLs instead of rejecting the whole file.
    """
    malformed_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/about-us/</loc></url>
      <url><loc>https://example.com/deals?a=1&b=2</loc></url>
    </urlset>"""
    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap.xml": FakeResponse(
            200, malformed_xml, "application/xml", "https://example.com/sitemap.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.sitemap_url == "https://example.com/sitemap.xml"
    assert len(result.urls) == 2
    assert not result.errors


def test_non_sitemap_response_includes_content_snippet_for_diagnosis(monkeypatch):
    """When a candidate returns XML-ish content that isn't a real sitemap
    (e.g. a bot-protection/WAF block page), the warning should include a
    snippet of the actual response so the real cause is diagnosable.
    """
    block_page = b"<html><head><title>Attention Required! Access Denied</title></head><body>Blocked</body></html>"
    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap.xml": FakeResponse(
            200, block_page, "text/html", "https://example.com/sitemap.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.urls == []
    all_messages = " ".join(result.warnings + result.errors)
    assert "Attention Required" in all_messages


def test_uploaded_urlset_is_parsed_directly_without_any_fetch(monkeypatch):
    """A plain urlset upload needs no network access at all -- if _fetch is
    ever called, this test should fail loudly rather than silently pass.
    """
    def _unexpected_fetch(url, session):
        raise AssertionError(f"parse_uploaded_sitemap should not fetch anything, but tried: {url}")

    monkeypatch.setattr(sitemap, "_fetch", _unexpected_fetch)

    result = sitemap.parse_uploaded_sitemap(_read("urlset_simple.xml"), "old-sitemap.xml", "oldsite.com")

    assert result.uploaded_filename == "old-sitemap.xml"
    assert result.sitemap_url is None
    assert result.duplicates_removed == 1
    assert len(result.urls) == 3
    assert not result.errors


def test_uploaded_sitemapindex_still_fetches_its_child_sitemaps(monkeypatch):
    """Only the top-level file is local -- a sitemapindex's <loc> children
    are real URLs and still need to be fetched over the network."""
    url_map = {
        "https://example.com/sitemap-pages.xml": FakeResponse(
            200, _read("sitemap_pages.xml"), "application/xml", "https://example.com/sitemap-pages.xml"
        ),
        "https://example.com/sitemap-posts.xml": FakeResponse(
            200, _read("sitemap_posts.xml"), "application/xml", "https://example.com/sitemap-posts.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.parse_uploaded_sitemap(_read("sitemap_index.xml"), "sitemap_index.xml")

    assert result.uploaded_filename == "sitemap_index.xml"
    assert len(result.urls) == 4
    assert not result.errors


def test_domain_forwarding_to_a_different_domain_is_followed(monkeypatch):
    """Regression test: a .com registrar-forwarded to a .net (signature
    shutters.com -> signatureshutters.net was the real-world case). If the
    forward doesn't preserve the requested path, probing /robots.txt and
    /sitemap.xml against the OLD domain would land on the new domain's
    homepage instead of the real files. Detecting the domain switch up
    front and probing the resolved domain directly avoids that.
    """
    url_map = {
        "https://example.com/": FakeResponse(
            301, b"", "text/html", "https://example.com/", location="https://newsite.com"
        ),
        "https://newsite.com/": FakeResponse(200, b"<html></html>", "text/html", "https://newsite.com/"),
        "https://newsite.com/robots.txt": FakeResponse(404, b"", "text/plain", "https://newsite.com/robots.txt"),
        "https://newsite.com/sitemap.xml": FakeResponse(
            200, _read("urlset_simple.xml"), "application/xml", "https://newsite.com/sitemap.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.sitemap_url == "https://newsite.com/sitemap.xml"
    assert len(result.urls) == 3
    assert not result.errors
    assert any("redirects to https://newsite.com" in w for w in result.warnings)


def test_domain_forwarding_to_unreachable_destination_reports_the_reason(monkeypatch):
    """Regression test for the real-world case: a .com forwards to a .net,
    but the .net's SSL certificate turns out to be broken (a hosting
    misconfiguration during a DNS cutover, in the case that surfaced this).
    The redirect should still be detected and reported by name, with the
    specific reason it couldn't be followed further -- not silently dropped
    in favor of generic "no sitemap found" noise about the OLD domain.
    """
    url_map = {
        "https://example.com/": FakeResponse(
            301, b"", "text/html", "https://example.com/", location="https://newsite.com"
        ),
        "https://newsite.com/": requests.exceptions.SSLError("certificate verify failed"),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.urls == []
    all_messages = " ".join(result.warnings + result.errors)
    assert "redirects to https://newsite.com" in all_messages
    assert "certificate" in all_messages.lower()


def test_same_domain_redirect_does_not_trigger_forwarding_warning(monkeypatch):
    """A same-domain https upgrade or www normalization shouldn't be reported
    as cross-domain forwarding."""
    url_map = {
        "https://example.com/": FakeResponse(200, b"<html></html>", "text/html", "https://example.com/"),
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap.xml": FakeResponse(
            200, _read("urlset_simple.xml"), "application/xml", "https://example.com/sitemap.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert not any("redirects to" in w for w in result.warnings)


def test_robots_txt_declaring_multiple_sitemaps_pulls_and_merges_all(monkeypatch):
    """Regression test: robots.txt listing a video-sitemap.xml before
    sitemap.xml previously caused discovery to stop at whichever one it
    tried first and never look at the other -- even though robots.txt
    explicitly declares both as valid sitemaps for the site, and one isn't
    a superset of the other (e.g. a video sitemap vs. the main page
    sitemap). Both should be fetched and merged.
    """
    robots_txt = (
        "User-agent: *\n"
        "Disallow: /wp-admin/\n\n"
        "Sitemap: https://example.com/video-sitemap.xml\n"
        "Sitemap: https://example.com/sitemap.xml\n"
    )
    video_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/videos/demo</loc></url>
    </urlset>"""
    url_map = {
        "https://example.com/": FakeResponse(200, b"<html></html>", "text/html", "https://example.com/"),
        "https://example.com/robots.txt": FakeResponse(200, robots_txt.encode(), "text/plain", "https://example.com/robots.txt"),
        "https://example.com/video-sitemap.xml": FakeResponse(
            200, video_xml, "application/xml", "https://example.com/video-sitemap.xml"
        ),
        "https://example.com/sitemap.xml": FakeResponse(
            200, _read("urlset_simple.xml"), "application/xml", "https://example.com/sitemap.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.sitemap_url == "https://example.com/video-sitemap.xml"
    # 1 from video-sitemap.xml + 3 from sitemap.xml
    assert len(result.urls) == 4
    assert "https://example.com/videos/demo" in result.urls
    assert not result.errors
    assert any("Combined 2 sitemaps" in w for w in result.warnings)


def test_robots_txt_sitemap_that_404s_falls_back_to_common_paths(monkeypatch):
    """If every sitemap robots.txt declares turns out to be dead, fall back
    to guessing common paths rather than giving up."""
    robots_txt = "Sitemap: https://example.com/stale-sitemap.xml\n"
    url_map = {
        "https://example.com/": FakeResponse(200, b"<html></html>", "text/html", "https://example.com/"),
        "https://example.com/robots.txt": FakeResponse(200, robots_txt.encode(), "text/plain", "https://example.com/robots.txt"),
        "https://example.com/stale-sitemap.xml": FakeResponse(404, b"", "text/plain"),
        "https://example.com/sitemap.xml": FakeResponse(
            200, _read("urlset_simple.xml"), "application/xml", "https://example.com/sitemap.xml"
        ),
    }
    monkeypatch.setattr(sitemap, "_fetch", make_fake_fetch(url_map))

    result = sitemap.discover_and_parse_sitemap("example.com")

    assert result.sitemap_url == "https://example.com/sitemap.xml"
    assert len(result.urls) == 3
    assert not result.errors


def test_uploaded_file_with_no_urls_gives_friendly_error(monkeypatch):
    monkeypatch.setattr(sitemap, "_fetch", lambda url, session: (_ for _ in ()).throw(AssertionError("no fetch expected")))

    result = sitemap.parse_uploaded_sitemap(b"<html><body>Not a sitemap</body></html>", "not-a-sitemap.xml")

    assert result.urls == []
    assert result.errors
    assert "not-a-sitemap.xml" in result.errors[0]
