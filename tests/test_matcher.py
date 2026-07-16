import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matcher import (
    generate_redirect_suggestions,
    MATCH_TYPE_EXACT_PATH,
    MATCH_TYPE_EXACT_SLUG,
    MATCH_TYPE_TOKEN_SIMILARITY,
    MATCH_TYPE_NO_MATCH,
)
from config import MAX_ALTERNATIVES


def _result_for(results, old_url):
    for r in results:
        if r.old_url == old_url:
            return r
    raise AssertionError(f"No result for {old_url}")


def test_exact_normalized_path_match_is_confidence_100():
    old_urls = ["https://oldsite.com/about-us/"]
    new_urls = ["https://newsite.com/about-us"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.match_type == MATCH_TYPE_EXACT_PATH
    assert r.best.confidence == 100
    assert r.include_default is True


def test_exact_slug_match_scores_lower_than_exact_path():
    old_urls = ["https://oldsite.com/services/gutter-cleaning/"]
    new_urls = ["https://newsite.com/gutter-cleaning"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.match_type == MATCH_TYPE_EXACT_SLUG
    assert r.best.confidence < 100
    assert r.best.confidence >= 80


def test_token_similarity_match():
    old_urls = ["https://oldsite.com/residential-roof-cleaning/"]
    new_urls = ["https://newsite.com/roof-cleaning", "https://newsite.com/completely-unrelated-page"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.new_path == "/roof-cleaning"
    assert r.best.match_type in (MATCH_TYPE_TOKEN_SIMILARITY,)
    assert r.best.confidence < 100


def test_no_reliable_match_falls_back_to_homepage():
    old_urls = ["https://oldsite.com/xyzzy-quux-plugh/"]
    new_urls = ["https://newsite.com/completely-different-topic-area"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best is not None
    assert r.best.new_path == "/"
    assert r.best.match_type == MATCH_TYPE_NO_MATCH
    assert r.include_default is True
    assert r.status_default == "Needs Review"


def test_no_reliable_match_uses_actual_homepage_url_when_present():
    old_urls = ["https://oldsite.com/xyzzy-quux-plugh/"]
    new_urls = ["https://newsite.com/", "https://newsite.com/completely-different-topic-area"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.new_path == "/"
    assert r.best.new_url == "https://newsite.com/"


def test_alternatives_capped_at_five():
    old_urls = ["https://oldsite.com/roofing-services/"]
    new_urls = [f"https://newsite.com/roofing-page-{i}" for i in range(10)]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert len(r.alternatives) <= MAX_ALTERNATIVES


def test_homepage_matches_homepage_exactly():
    old_urls = ["https://oldsite.com/"]
    new_urls = ["https://newsite.com/"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.match_type == MATCH_TYPE_EXACT_PATH
    assert r.best.new_path == "/"


def test_multiple_old_urls_each_get_a_result():
    old_urls = ["https://oldsite.com/about/", "https://oldsite.com/contact/"]
    new_urls = ["https://newsite.com/about", "https://newsite.com/contact"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    assert len(results) == 2
    assert {r.old_url for r in results} == set(old_urls)
