import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import audit
from audit import (
    VERDICT_BROKEN,
    VERDICT_LIVE,
    VERDICT_REDIRECTS,
    VERDICT_UNCHECKED,
    AuditResult,
    UrlCheck,
    audit_urls,
    check_url,
    gather_old_urls,
    live_origin,
    parse_pasted_lines,
    to_live_url,
)
from sitemap import SitemapResult

ORIGIN = "https://www.example.com"
ROOT = "example.com"


class FakeResp:
    def __init__(self, status, location=None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}


def fake_fetch(table, calls=None):
    def _fetch(url, session):
        if calls is not None:
            calls.append(url)
        entry = table.get(url, FakeResp(404))
        if isinstance(entry, Exception):
            raise entry
        return entry
    return _fetch


# --- check_url -------------------------------------------------------------

def test_200_is_live(monkeypatch):
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch({f"{ORIGIN}/a": FakeResp(200)}))
    assert check_url(f"{ORIGIN}/a", ROOT, None).verdict == VERDICT_LIVE


def test_404_and_410_are_broken(monkeypatch):
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch({f"{ORIGIN}/gone": FakeResp(410)}))
    assert check_url(f"{ORIGIN}/gone", ROOT, None).verdict == VERDICT_BROKEN
    assert check_url(f"{ORIGIN}/never-existed", ROOT, None).verdict == VERDICT_BROKEN


def test_redirect_to_working_page_is_already_handled(monkeypatch):
    table = {f"{ORIGIN}/about": FakeResp(301, "/about-us"), f"{ORIGIN}/about-us": FakeResp(200)}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table))
    check = check_url(f"{ORIGIN}/about", ROOT, None)
    assert check.verdict == VERDICT_REDIRECTS
    assert check.final_url == f"{ORIGIN}/about-us"
    assert check.hops == 1


def test_redirect_into_a_404_is_still_broken(monkeypatch):
    table = {f"{ORIGIN}/a": FakeResp(301, "/b")}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table))
    check = check_url(f"{ORIGIN}/a", ROOT, None)
    assert check.verdict == VERDICT_BROKEN
    assert "itself not found" in check.detail


def test_redirect_to_another_site_is_not_followed(monkeypatch):
    calls = []
    table = {f"{ORIGIN}/shop": FakeResp(301, "https://shop.other.com/")}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table, calls))
    check = check_url(f"{ORIGIN}/shop", ROOT, None)
    assert check.verdict == VERDICT_REDIRECTS
    assert calls == [f"{ORIGIN}/shop"]


def test_www_and_apex_count_as_the_same_site(monkeypatch):
    table = {f"{ORIGIN}/a": FakeResp(301, "https://example.com/a"), "https://example.com/a": FakeResp(200)}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table))
    assert check_url(f"{ORIGIN}/a", ROOT, None).verdict == VERDICT_REDIRECTS


def test_redirect_loop_is_unchecked(monkeypatch):
    table = {f"{ORIGIN}/a": FakeResp(301, "/b"), f"{ORIGIN}/b": FakeResp(301, "/a")}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table))
    check = check_url(f"{ORIGIN}/a", ROOT, None)
    assert check.verdict == VERDICT_UNCHECKED
    assert "loop" in check.detail


def test_forbidden_and_server_errors_are_unchecked_not_broken(monkeypatch):
    table = {f"{ORIGIN}/a": FakeResp(403), f"{ORIGIN}/b": FakeResp(503)}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table))
    assert check_url(f"{ORIGIN}/a", ROOT, None).verdict == VERDICT_UNCHECKED
    assert check_url(f"{ORIGIN}/b", ROOT, None).verdict == VERDICT_UNCHECKED


def test_network_error_is_unchecked(monkeypatch):
    table = {f"{ORIGIN}/a": requests.exceptions.ConnectionError("boom")}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table))
    check = check_url(f"{ORIGIN}/a", ROOT, None)
    assert check.verdict == VERDICT_UNCHECKED
    assert "Could not connect" in check.detail


def test_blocked_network_location_is_unchecked(monkeypatch):
    def _raise(url, session):
        raise audit.BlockedUrlError("Refusing to fetch a local/private network address")
    monkeypatch.setattr(audit, "_fetch_once", _raise)
    assert check_url(f"{ORIGIN}/a", ROOT, None).verdict == VERDICT_UNCHECKED


# --- audit_urls ------------------------------------------------------------

def test_sitemap_listed_urls_are_never_requested(monkeypatch):
    calls = []
    table = {f"{ORIGIN}/old": FakeResp(404)}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table, calls))
    result = audit_urls(
        [f"{ORIGIN}/about-us/", f"{ORIGIN}/old"], ORIGIN, {"/about-us"}, max_workers=2
    )
    assert calls == [f"{ORIGIN}/old"]
    assert [c.verdict for c in result.checks] == [VERDICT_LIVE, VERDICT_BROKEN]


def test_input_order_is_preserved(monkeypatch):
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch({}))
    urls = [f"{ORIGIN}/p{i}" for i in range(20)]
    result = audit_urls(urls, ORIGIN, set(), max_workers=4)
    assert [c.old_url for c in result.checks] == urls


def test_duplicates_by_normalized_path_are_collapsed(monkeypatch):
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch({}))
    result = audit_urls([f"{ORIGIN}/a", f"{ORIGIN}/a/", f"{ORIGIN}/a?x=1"], ORIGIN, set())
    assert len(result.checks) == 1


def test_cap_truncates_and_reports(monkeypatch):
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch({}))
    urls = [f"{ORIGIN}/p{i}" for i in range(10)]
    result = audit_urls(urls, ORIGIN, set(), max_urls=4)
    assert len(result.checks) == 4
    assert result.truncated == 6


def test_progress_reports_every_url(monkeypatch):
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch({}))
    seen = []
    audit_urls([f"{ORIGIN}/a", f"{ORIGIN}/b", f"{ORIGIN}/c"], ORIGIN, {"/a"}, progress=lambda d, t: seen.append((d, t)))
    assert seen[0] == (1, 3)
    assert seen[-1] == (3, 3)


def test_urls_needing_redirect_respects_the_unchecked_toggle():
    result = AuditResult(
        checks=[
            UrlCheck("u1", VERDICT_BROKEN),
            UrlCheck("u2", VERDICT_UNCHECKED),
            UrlCheck("u3", VERDICT_LIVE),
            UrlCheck("u4", VERDICT_REDIRECTS),
        ]
    )
    assert result.urls_needing_redirect(include_unchecked=True) == ["u1", "u2"]
    assert result.urls_needing_redirect(include_unchecked=False) == ["u1"]


def test_blocked_site_is_detected():
    blocked = AuditResult(checks=[UrlCheck(f"u{i}", VERDICT_UNCHECKED, 403) for i in range(6)])
    assert blocked.blocked_suspected
    healthy = AuditResult(checks=[UrlCheck(f"u{i}", VERDICT_BROKEN, 404) for i in range(6)])
    assert not healthy.blocked_suspected
    too_few = AuditResult(checks=[UrlCheck("u", VERDICT_UNCHECKED, 403)])
    assert not too_few.blocked_suspected


# --- URL gathering ---------------------------------------------------------

def test_to_live_url_repoints_paths_and_same_site_urls():
    assert to_live_url("/about/", ORIGIN) == f"{ORIGIN}/about/"
    assert to_live_url("http://example.com/about/?a=1#frag", ORIGIN) == f"{ORIGIN}/about/?a=1"
    assert to_live_url("https://www.example.com", ORIGIN) == f"{ORIGIN}/"


def test_to_live_url_rejects_other_sites_and_assets():
    assert to_live_url("https://other.com/about", ORIGIN) is None
    assert to_live_url("//other.com/about", ORIGIN) is None
    assert to_live_url("/logo.png", ORIGIN) is None
    assert to_live_url("ftp://example.com/a", ORIGIN) is None
    assert to_live_url("", ORIGIN) is None


def test_parse_pasted_lines_handles_paths_urls_and_noise():
    text = "/about\n\n# a comment\nhttps://www.example.com/team,\nwww.example.com/pricing\nfaq\n"
    assert parse_pasted_lines(text) == [
        "/about",
        "https://www.example.com/team",
        "https://www.example.com/pricing",
        "/faq",
    ]


def test_live_origin_prefers_what_discovery_resolved():
    resolved = SitemapResult(domain="example.com", sitemap_url="https://www.example.com/sitemap.xml")
    assert live_origin(resolved, "example.com") == "https://www.example.com"
    crawled = SitemapResult(domain="example.com", crawled_from="https://www.example.com/")
    assert live_origin(crawled, "example.com") == "https://www.example.com"
    assert live_origin(SitemapResult(domain="example.com"), "example.com") == "https://example.com"


def _wayback(urls, errors=None):
    def _fake(domain):
        r = SitemapResult(domain=domain)
        r.urls = list(urls)
        r.errors = list(errors or [])
        if urls:
            r.wayback_source = domain
        return r
    return _fake


def test_gather_merges_sources_dedupes_and_puts_pasted_first(monkeypatch):
    monkeypatch.setattr(
        audit,
        "fetch_wayback_urls",
        lambda host: _wayback(["http://example.com/about/", "http://example.com/our-team", "https://other.com/x"])(host)
        if host == "example.com" else _wayback([])(host),
    )
    csv_result = SitemapResult(domain="example.com", gsc_import_filename="ga.csv")
    csv_result.urls = [f"{ORIGIN}/our-team", f"{ORIGIN}/pricing"]

    gathered = gather_old_urls(
        "example.com", ORIGIN, include_wayback=True, csv_result=csv_result, pasted_text="/about"
    )

    assert gathered.result.urls[0] == f"{ORIGIN}/about"
    paths = [u.replace(ORIGIN, "") for u in gathered.result.urls]
    assert sorted(paths) == ["/about", "/our-team", "/pricing"]
    assert gathered.source_counts == {"Pasted URLs": 1, "Uploaded URL list": 2, "Wayback Machine": 2}
    assert gathered.skipped_off_site == 1
    assert not gathered.result.errors


def test_gather_errors_only_when_nothing_was_found(monkeypatch):
    monkeypatch.setattr(audit, "fetch_wayback_urls", _wayback([], errors=["No archived pages were found."]))
    gathered = gather_old_urls("example.com", ORIGIN, include_wayback=True)
    assert gathered.result.errors
    assert not gathered.result.urls


def test_gather_without_wayback_never_calls_it(monkeypatch):
    def _boom(host):
        raise AssertionError("Wayback should not be called")
    monkeypatch.setattr(audit, "fetch_wayback_urls", _boom)
    gathered = gather_old_urls("example.com", ORIGIN, include_wayback=False, pasted_text="/about")
    assert gathered.result.urls == [f"{ORIGIN}/about"]


def test_bad_csv_is_only_a_warning_when_other_sources_have_urls(monkeypatch):
    csv_result = SitemapResult(domain="example.com", gsc_import_filename="bad.csv")
    csv_result.errors = ["No usable page URLs were found in 'bad.csv'."]
    gathered = gather_old_urls("example.com", ORIGIN, include_wayback=False, csv_result=csv_result, pasted_text="/about")
    assert gathered.result.urls
    assert not gathered.result.errors
    assert any("bad.csv" in w for w in gathered.result.warnings)


def test_default_ports_on_archived_urls_do_not_make_them_off_site():
    assert to_live_url("http://example.com:80/about/", ORIGIN) == f"{ORIGIN}/about/"
    assert to_live_url("https://www.example.com:443/team", ORIGIN) == f"{ORIGIN}/team"
    assert to_live_url("http://other.com:80/about/", ORIGIN) is None


def test_a_redirect_carrying_a_port_still_counts_as_same_site(monkeypatch):
    table = {f"{ORIGIN}/a": FakeResp(301, "https://www.example.com:443/b"), "https://www.example.com:443/b": FakeResp(200)}
    monkeypatch.setattr(audit, "_fetch_once", fake_fetch(table))
    assert check_url(f"{ORIGIN}/a", ROOT, None).verdict == VERDICT_REDIRECTS
