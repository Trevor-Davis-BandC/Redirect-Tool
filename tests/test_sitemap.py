import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import sitemap

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status_code, content, content_type="application/xml", url=None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.headers = {"Content-Type": content_type}
        self.url = url or ""


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def make_fake_fetch(url_map):
    def _fake_fetch(url, session):
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
