import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import crawler
import linkcheck
from report import build_link_check_pdf
from test_crawler import FakeResponse, _page, make_fake_fetch

ROBOTS = {"https://example.com/robots.txt": FakeResponse(404, b"", "text/plain")}


def _site(monkeypatch, pages, extra=None):
    url_map = dict(ROBOTS)
    url_map.update(pages)
    url_map.update(extra or {})
    monkeypatch.setattr(crawler, "_fetch", make_fake_fetch(url_map))


def test_finds_broken_link_and_every_page_it_is_on(monkeypatch):
    _site(
        monkeypatch,
        {
            "https://example.com/": _page(
                '<a href="/about">About</a><a href="/gone">Old</a>', "https://example.com/"
            ),
            "https://example.com/about": _page('<a href="/gone">Old</a>', "https://example.com/about"),
        },
    )
    result = linkcheck.check_site_links("example.com")

    assert [b.url for b in result.broken] == ["https://example.com/gone"]
    broken = result.broken[0]
    assert broken.status == 404
    assert broken.linked_from == ["https://example.com/", "https://example.com/about"]
    assert result.pages_crawled == 2
    assert result.dead_count == 1 and result.other_count == 0


def test_clean_site_reports_nothing_broken(monkeypatch):
    _site(
        monkeypatch,
        {
            "https://example.com/": _page('<a href="/about">About</a>', "https://example.com/"),
            "https://example.com/about": _page("hi", "https://example.com/about"),
        },
    )
    result = linkcheck.check_site_links("example.com")
    assert result.broken == []
    assert not result.errors
    assert result.links_checked == 2


def test_external_links_are_not_checked(monkeypatch):
    _site(
        monkeypatch,
        {"https://example.com/": _page('<a href="https://other.com/x">Out</a>', "https://example.com/")},
    )
    result = linkcheck.check_site_links("example.com")
    assert result.broken == []


def test_fragment_links_are_not_fetched_twice_or_reported_separately(monkeypatch):
    _site(
        monkeypatch,
        {
            "https://example.com/": _page(
                '<a href="/about#team">A</a><a href="/about">B</a><a href="/gone#x">C</a>',
                "https://example.com/",
            ),
            "https://example.com/about": _page("hi", "https://example.com/about"),
        },
    )
    result = linkcheck.check_site_links("example.com")
    assert [b.url for b in result.broken] == ["https://example.com/gone"]
    assert result.links_checked == 3  # home, /about, /gone


def test_other_failures_are_separated_from_dead_links(monkeypatch):
    _site(
        monkeypatch,
        {
            "https://example.com/": _page(
                '<a href="/gone">a</a><a href="/private">b</a><a href="/boom">c</a>', "https://example.com/"
            ),
            "https://example.com/private": FakeResponse(403, b"no", "text/html", "https://example.com/private"),
            "https://example.com/boom": FakeResponse(500, b"err", "text/html", "https://example.com/boom"),
        },
    )
    result = linkcheck.check_site_links("example.com")
    by_url = {b.url: b for b in result.broken}
    assert by_url["https://example.com/gone"].status == 404
    assert by_url["https://example.com/private"].status == 403
    assert by_url["https://example.com/boom"].status == 500
    assert result.dead_count == 1 and result.other_count == 2
    # Dead links sort first.
    assert result.broken[0].url == "https://example.com/gone"
    assert "Blocked" in linkcheck.describe_status(403)
    assert linkcheck.describe_status(500) == "Server error"


def test_connection_failure_is_reported_with_status_zero(monkeypatch):
    _site(
        monkeypatch,
        {"https://example.com/": _page('<a href="/slow">s</a>', "https://example.com/")},
        {"https://example.com/slow": requests.exceptions.ReadTimeout("slow")},
    )
    result = linkcheck.check_site_links("example.com")
    assert [(b.url, b.status) for b in result.broken] == [("https://example.com/slow", 0)]
    assert "No response" in linkcheck.describe_status(0)


def test_unreachable_homepage_is_an_error_not_a_broken_link(monkeypatch):
    _site(monkeypatch, {"https://example.com/": FakeResponse(500, b"x", "text/html", "https://example.com/")})
    result = linkcheck.check_site_links("example.com")
    assert result.errors
    assert result.broken == []


def test_referrers_are_capped(monkeypatch):
    n = crawler.MAX_REFERRERS_PER_LINK + 5
    home_links = "".join(f'<a href="/p{i}">p</a>' for i in range(n))
    pages = {"https://example.com/": _page(home_links, "https://example.com/")}
    for i in range(n):
        pages[f"https://example.com/p{i}"] = _page('<a href="/gone">g</a>', f"https://example.com/p{i}")
    _site(monkeypatch, pages)
    result = linkcheck.check_site_links("example.com")
    assert len(result.broken[0].linked_from) == crawler.MAX_REFERRERS_PER_LINK


def test_progress_callback_is_called(monkeypatch):
    _site(
        monkeypatch,
        {
            "https://example.com/": _page('<a href="/a">a</a>', "https://example.com/"),
            "https://example.com/a": _page("x", "https://example.com/a"),
        },
    )
    seen = []
    linkcheck.check_site_links("example.com", on_progress=lambda c, q: seen.append(c))
    assert seen == [1, 2]


def test_csv_has_one_row_per_link_and_page(monkeypatch):
    _site(
        monkeypatch,
        {
            "https://example.com/": _page('<a href="/about">A</a><a href="/gone">G</a>', "https://example.com/"),
            "https://example.com/about": _page('<a href="/gone">G</a>', "https://example.com/about"),
        },
    )
    result = linkcheck.check_site_links("example.com")
    lines = linkcheck.broken_links_csv(result).decode("utf-8-sig").strip().splitlines()
    assert lines[0] == "Broken link,Status,Problem,Found on"
    assert len(lines) == 3
    assert lines[1].startswith("https://example.com/gone,404,Page not found,https://example.com/")


def test_dataframe_columns_and_filename(monkeypatch):
    _site(monkeypatch, {"https://example.com/": _page('<a href="/gone">G</a>', "https://example.com/")})
    result = linkcheck.check_site_links("example.com")
    df = linkcheck.broken_links_dataframe(result)
    assert list(df.columns) == [
        linkcheck.COL_BROKEN_LINK,
        linkcheck.COL_STATUS,
        linkcheck.COL_PROBLEM,
        linkcheck.COL_PAGES,
        linkcheck.COL_FOUND_ON,
    ]
    assert df.iloc[0][linkcheck.COL_PAGES] == 1
    assert linkcheck.build_link_check_filename("https://www.Example.com/", "csv").startswith(
        "www-example-com-broken-links-"
    )


def test_pdf_builds_with_and_without_findings(monkeypatch):
    _site(monkeypatch, {"https://example.com/": _page('<a href="/gone">G</a>', "https://example.com/")})
    dirty = linkcheck.check_site_links("example.com")
    assert build_link_check_pdf("Proj", "example.com", dirty).startswith(b"%PDF")

    _site(monkeypatch, {"https://example.com/": _page("clean", "https://example.com/")})
    clean = linkcheck.check_site_links("example.com")
    assert build_link_check_pdf("", "example.com", clean).startswith(b"%PDF")
