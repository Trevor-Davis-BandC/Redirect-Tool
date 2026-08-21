import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import wayback


class FakeResponse:
    def __init__(self, status_code, json_data=None, raise_json_error=False):
        self.status_code = status_code
        self._json_data = json_data
        self._raise_json_error = raise_json_error

    def json(self):
        if self._raise_json_error:
            raise ValueError("not json")
        return self._json_data


def test_returns_filtered_real_pages(monkeypatch):
    rows = [
        ["original", "mimetype", "statuscode"],
        ["http://example.com/", "text/html", "200"],
        ["http://example.com/about-us/", "text/html", "200"],
        ["http://example.com/about-us/", "text/html", "200"],  # duplicate path
        ["http://example.com/old-post?x=1", "text/html", "200"],
        ["http://example.com/old-post?x=2", "text/html", "200"],  # dup by path
    ]
    monkeypatch.setattr(
        wayback.requests, "get", lambda *a, **kw: FakeResponse(200, rows)
    )

    result = wayback.fetch_wayback_urls("example.com")

    assert result.wayback_source == "example.com"
    assert len(result.urls) == 3
    assert result.duplicates_removed == 2
    assert not result.errors


def test_skips_assets_and_well_known_paths_even_if_marked_html(monkeypatch):
    """Some archived non-page paths (well-known probes, admin paths) can
    still be recorded as text/html 200 -- these should be filtered out even
    though they pass the basic status/mimetype checks."""
    rows = [
        ["original", "mimetype", "statuscode"],
        ["http://example.com/real-page/", "text/html", "200"],
        ["http://example.com/.well-known/security.txt", "text/html", "200"],
        ["http://example.com/wp-admin/admin-ajax.php", "text/html", "200"],
        ["http://example.com/style.css", "text/html", "200"],
    ]
    monkeypatch.setattr(
        wayback.requests, "get", lambda *a, **kw: FakeResponse(200, rows)
    )

    result = wayback.fetch_wayback_urls("example.com")

    assert result.urls == ["http://example.com/real-page/"]


def test_no_archived_pages_gives_friendly_error(monkeypatch):
    monkeypatch.setattr(wayback.requests, "get", lambda *a, **kw: FakeResponse(200, []))

    result = wayback.fetch_wayback_urls("example.com")

    assert result.urls == []
    assert result.errors
    assert "example.com" in result.errors[0]


def test_only_junk_rows_gives_friendly_error(monkeypatch):
    rows = [
        ["original", "mimetype", "statuscode"],
        ["http://example.com/.well-known/security.txt", "text/html", "200"],
    ]
    monkeypatch.setattr(wayback.requests, "get", lambda *a, **kw: FakeResponse(200, rows))

    result = wayback.fetch_wayback_urls("example.com")

    assert result.urls == []
    assert result.errors


def test_network_error_gives_friendly_message(monkeypatch):
    def _raise(*a, **kw):
        raise requests.exceptions.ConnectTimeout("timed out")

    monkeypatch.setattr(wayback.requests, "get", _raise)

    result = wayback.fetch_wayback_urls("example.com")

    assert result.urls == []
    assert result.errors
    assert "Wayback Machine" in result.errors[0]


def test_http_error_status_gives_friendly_message(monkeypatch):
    monkeypatch.setattr(wayback.requests, "get", lambda *a, **kw: FakeResponse(503))

    result = wayback.fetch_wayback_urls("example.com")

    assert result.urls == []
    assert result.errors
    assert "503" in result.errors[0]


def test_unreadable_response_gives_friendly_message(monkeypatch):
    monkeypatch.setattr(
        wayback.requests, "get", lambda *a, **kw: FakeResponse(200, raise_json_error=True)
    )

    result = wayback.fetch_wayback_urls("example.com")

    assert result.urls == []
    assert result.errors


def test_invalid_domain_gives_friendly_error():
    result = wayback.fetch_wayback_urls("")

    assert result.urls == []
    assert result.errors
