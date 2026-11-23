import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from matcher import (
    generate_redirect_suggestions,
    MATCH_TYPE_EXACT_PATH,
    MATCH_TYPE_EXACT_SLUG,
    MATCH_TYPE_TOKEN_SIMILARITY,
    MATCH_TYPE_NO_MATCH,
    MATCH_TYPE_WILDCARD_PATTERN,
)
from columns import STATUS_APPROVED, STATUS_EXCLUDED, STATUS_UNMAPPED
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


def test_no_reliable_match_is_left_without_a_redirect():
    old_urls = ["https://oldsite.com/xyzzy-quux-plugh/"]
    new_urls = ["https://newsite.com/completely-different-topic-area"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best is not None
    assert r.best.match_type == MATCH_TYPE_NO_MATCH
    assert r.best.new_path == ""
    assert r.best.new_url == ""
    assert r.include_default is False
    assert r.status_default == STATUS_UNMAPPED
    assert "404" in r.note


def test_no_reliable_match_never_points_at_the_homepage_even_when_one_exists():
    old_urls = ["https://oldsite.com/xyzzy-quux-plugh/"]
    new_urls = ["https://newsite.com/", "https://newsite.com/completely-different-topic-area"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.new_path == ""
    assert r.include_default is False


def test_identical_path_on_the_new_site_needs_no_redirect():
    old_urls = ["https://oldsite.com/services", "https://oldsite.com/"]
    new_urls = ["https://newsite.com/services", "https://newsite.com/"]

    results = generate_redirect_suggestions(old_urls, new_urls)

    for old_url in old_urls:
        r = _result_for(results, old_url)
        assert r.best.match_type == MATCH_TYPE_EXACT_PATH
        assert r.include_default is False
        assert r.status_default == STATUS_EXCLUDED
        assert "no redirect is needed" in r.note


def test_a_trailing_slash_difference_still_gets_a_rule():
    old_urls = ["https://oldsite.com/services/"]
    new_urls = ["https://newsite.com/services"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.match_type == MATCH_TYPE_EXACT_PATH
    assert r.include_default is True
    assert r.status_default == STATUS_APPROVED
    assert r.note == ""


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


def test_shared_location_suffix_does_not_override_topic_word():
    """Regression test: two unrelated topics that happen to share a location
    suffix (e.g. "-summerville") must not out-rank a page that actually
    shares the topic word, just because of character-level string overlap
    in the unrelated word ("flood" vs "smoke"). Real-world case: BVM Clean
    Masters migration, where /tag/smoke-damage-summerville/ was matching to
    a flood-damage post instead of the site's actual smoke-damage page.
    """
    old_urls = ["https://oldsite.com/tag/smoke-damage-summerville/"]
    new_urls = [
        "https://newsite.com/smoke-damage-restoration",
        "https://newsite.com/2017/10/15/flood-damage-summerville",
    ]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    # Whatever the outcome (a confident match or a review-needed fallback),
    # it must never be the topically-wrong flood-damage page.
    assert r.best.new_path != "/2017/10/15/flood-damage-summerville"


def test_concatenated_slug_matches_hyphenated_equivalent_instead_of_homepage():
    """Regression test: BVM Travel migration, where /objectionbusters (no
    separator) failed to match /objection-busters (hyphenated) and fell back
    to the homepage, even though they're obviously the same page. Word-
    overlap tokenization sees zero shared words here, since the concatenated
    slug never gets split into "objection" + "busters" -- an exact match
    once hyphens/underscores are stripped is now treated as a strong signal.
    """
    old_urls = ["https://oldsite.com/objectionbusters"]
    new_urls = ["https://newsite.com/", "https://newsite.com/objection-busters"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.new_path == "/objection-busters"
    assert r.best.match_type != MATCH_TYPE_NO_MATCH


def test_concatenated_slug_matches_even_when_also_renested_under_a_folder():
    """Regression test: same migration, /adultonlycruises moved from the
    site root to /services/adult-only-cruises on the new site -- combining
    the concatenated-vs-hyphenated issue above with a folder-depth change.
    Neither difference alone should be enough to lose the match, since
    site redesigns commonly both reformat slugs and reorganize into
    category folders.
    """
    old_urls = ["https://oldsite.com/adultonlycruises"]
    new_urls = [
        "https://newsite.com/",
        "https://newsite.com/services",
        "https://newsite.com/services/adult-only-cruises",
    ]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.new_path == "/services/adult-only-cruises"
    assert r.best.match_type != MATCH_TYPE_NO_MATCH


def test_wildcard_pattern_entries_are_never_redirected():
    """Regression test: GSC's 404 report can include pattern-style entries
    alongside real crawled URLs -- e.g. "/wp-*.php" or
    "/wp-content/themes/Divi-child/*" -- which aren't real pages at all. A
    real-world case (signatureshutters.net) confirmed these currently land
    on the homepage anyway via fuzzy scoring, but that's coincidental, not
    guaranteed -- so this is enforced deterministically, bypassing fuzzy
    matching entirely.
    """
    old_urls = [
        "https://oldsite.com/wp-*.php",
        "https://oldsite.com/wp-content/uploads/*",
        "https://oldsite.com/wp-content/themes/Divi-child/*",
        "https://oldsite.com/*",
    ]
    new_urls = ["https://newsite.com/", "https://newsite.com/about-us"]

    results = generate_redirect_suggestions(old_urls, new_urls)

    for old_url in old_urls:
        r = _result_for(results, old_url)
        assert r.best.new_path == ""
        assert r.best.match_type == MATCH_TYPE_WILDCARD_PATTERN
        assert r.include_default is False
        assert r.status_default == STATUS_UNMAPPED
        assert r.note


def test_wildcard_pattern_wins_over_a_coincidentally_similar_real_page():
    """A wildcard entry must stay unredirected even when a real page on the new
    site happens to share words with the pattern text -- fuzzy matching
    should never get a chance to run for these at all.
    """
    old_urls = ["https://oldsite.com/wp-content/uploads/*"]
    new_urls = [
        "https://newsite.com/",
        "https://newsite.com/wp-content-uploads-showcase",
    ]

    results = generate_redirect_suggestions(old_urls, new_urls)
    r = _result_for(results, old_urls[0])

    assert r.best.new_path == ""
    assert r.best.match_type == MATCH_TYPE_WILDCARD_PATTERN
    assert r.status_default == STATUS_UNMAPPED


def test_multiple_old_urls_each_get_a_result():
    old_urls = ["https://oldsite.com/about/", "https://oldsite.com/contact/"]
    new_urls = ["https://newsite.com/about", "https://newsite.com/contact"]

    results = generate_redirect_suggestions(old_urls, new_urls)
    assert len(results) == 2
    assert {r.old_url for r in results} == set(old_urls)
