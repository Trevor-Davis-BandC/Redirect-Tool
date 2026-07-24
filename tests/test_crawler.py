import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import crawler


class FakeResponse:
    def __init__(self, status_code, content, content_type="text/html", url=None):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.headers = {"Content-Type": content_type}
        self.url = url or ""


def make_fake_fetch(url_map):
    def _fake_fetch(url, session):
        entry = url_map.get(url)
        if entry is None:
            return FakeResponse(404, b"Not Found", "text/plain", url)
        if isinstance(entry, Exception):
            raise entry
        return entry
    return _fake_fetch


def _page(html: str, url: str) -> FakeResponse:
    return FakeResponse(200, html.encode("utf-8"), "text/html", url)


def test_crawl_follows_same_domain_links(monkeypatch):
    home = _page(
        '<html><body><a href="/about-us">About</a> <a href="/contact">Contact</a></body></html>',
        "https://example.com/",
    )
    about = _page('<html><body><a href="/">Home</a></body></html>', "https://example.com/about-us")
    contact = _page("<html><body>No links here.</body></html>", "https://example.com/contact")

    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/": home,
        "https://example.com/about-us": about,
        "https://example.com/contact": contact,
    }
    monkeypatch.setattr(crawler, "_fetch", make_fake_fetch(url_map))

    result = crawler.crawl_site_links("example.com")

    assert set(result.urls) == {
        "https://example.com/",
        "https://example.com/about-us",
        "https://example.com/contact",
    }
    assert not result.errors
    assert result.crawled_from == "https://example.com/"


def test_crawl_ignores_offsite_links(monkeypatch):
    home = _page(
        '<html><body><a href="https://otherdomain.com/page">Off-site</a> '
        '<a href="/local">Local</a></body></html>',
        "https://example.com/",
    )
    local = _page("<html><body>Nothing here.</body></html>", "https://example.com/local")

    url_map = {
        "https://example.com/robots.txt": FakeResponse(404, b"", "text/plain"),
        "https://example.com/": home,
        "https://example.com/local": local,
    }
    monkeypatch.setattr(crawler, "_fetch", make_fake_fetch(url_map))

    result = crawler.crawl_site_links("example.com")

    assert "https://otherdomain.com/page" not in result.urls
    assert "https://example.com/local" in result.urls


def test_crawl_respects_robots_disallow(monkeypatch):
    home = _page(
        '<html><body><a href="/private/secret">Secret</a> <a href="/public">Public</a></body></html>',
        "https://example.com/",
    )
    public = _page("<html><body>Public page.</body></html>", "https://example.com/public")
    secret = _page("<html><body>Should never be fetched.</body></html>", "https://example.com/private/secret")

    url_map = {
        "https://example.com/robots.txt": FakeResponse(
            200, b"User-agent: *\nDisallow: /private/\n", "text/plain"
        ),
        "https://example.com/": home,
        "https://example.com/public": public,
        "https://example.com/private/secret": secret,
    }
    monkeypatch.setattr(crawler, "_fetch", make_fake_fetch(url_map))

    result = crawler.crawl_site_links("example.com")

    assert "https://example.com/public" in result.urls
    assert "https://example.com/private/secret" not in result.urls


def test_crawl_stops_at_page_limit(monkeypatch):
    # A chain of 5 pages, each linking to the next.
    url_map = {"https://example.com/robots.txt": FakeResponse(404, b"", "text/plain")}
    for i in range(5):
        page_url = f"https://example.com/page{i}"
        next_href = f"/page{i + 1}"
        url_map[page_url] = _page(f'<html><body><a href="{next_href}">Next</a></body></html>', page_url)
    url_map["https://example.com/"] = _page('<html><body><a href="/page0">Start</a></body></html>', "https://example.com/")

    monkeypatch.setattr(crawler, "_fetch", make_fake_fetch(url_map))

    result = crawler.crawl_site_links("example.com", max_pages=3)

    assert len(result.urls) == 3
    assert result.truncated is True
    assert result.warnings


def test_crawl_no_pages_reachable_gives_friendly_error(monkeypatch):
    monkeypatch.setattr(crawler, "_fetch", make_fake_fetch({}))

    result = crawler.crawl_site_links("example.com")

    assert result.urls == []
    assert result.errors
    assert "example.com" in result.errors[0]


def test_crawl_blocked_localhost_domain_is_rejected():
    result = crawler.crawl_site_links("localhost")
    assert result.urls == []
    assert result.errors
