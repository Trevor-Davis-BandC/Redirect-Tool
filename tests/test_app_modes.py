import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest

from sitemap import SitemapResult


def _app() -> AppTest:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.session_state["_authenticated"] = True
    at.session_state["_auth_expires"] = time.time() + 3600
    at.run()
    return at


def test_project_mode_survives_reruns_on_later_pages():
    at = _app()
    at.radio(key="project_mode_choice").set_value("audit").run()

    old = SitemapResult(domain="example.com")
    old.urls = ["https://www.example.com/about/"]
    new = SitemapResult(domain="example.com", sitemap_url="https://www.example.com/sitemap.xml")
    new.urls = ["https://www.example.com/about-us"]
    at.session_state["old_sitemap_result"] = old
    at.session_state["new_sitemap_result"] = new
    at.session_state["new_domain"] = "example.com"
    at.session_state["new_sitemap_paths"] = {"/about-us"}
    at.session_state["page"] = "discovery"

    for _ in range(3):
        at.run()
        assert not at.exception
        assert at.session_state["project_mode"] == "audit"
        assert "Check which old URLs are actually broken" in [s.value for s in at.subheader]


def test_returning_to_new_project_shows_the_saved_mode():
    at = _app()
    at.radio(key="project_mode_choice").set_value("gsc").run()
    at.session_state["page"] = "discovery"
    at.run()
    at.session_state["page"] = "new_project"
    at.run()
    assert at.radio(key="project_mode_choice").value == "gsc"
