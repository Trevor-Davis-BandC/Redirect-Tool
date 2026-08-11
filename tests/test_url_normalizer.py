import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from url_normalizer import (
    normalize_url,
    normalize_path,
    tokenize_path,
    get_final_slug,
    get_parent_path,
    get_path_depth,
    build_normalized_url,
)


def test_http_vs_https_treated_as_equivalent():
    assert normalize_url("http://example.com/about") == normalize_url("https://example.com/about")


def test_www_vs_non_www_treated_as_equivalent():
    assert normalize_url("https://www.example.com/about") == normalize_url("https://example.com/about")


def test_trailing_slash_normalized():
    assert normalize_url("https://example.com/about/") == normalize_url("https://example.com/about")


def test_duplicate_slashes_collapsed():
    assert normalize_path("//about//us//") == normalize_path("/about/us/")


def test_fragment_dropped():
    assert normalize_url("https://example.com/about#team") == normalize_url("https://example.com/about")


def test_percent_encoding_decoded():
    assert normalize_url("https://example.com/about%2Dus") == normalize_url("https://example.com/about-us")


def test_case_insensitive_path():
    assert normalize_url("https://example.com/About-Us") == normalize_url("https://example.com/about-us")


def test_homepage_normalizes_to_slash():
    assert normalize_path("") == "/"
    assert normalize_path("/") == "/"
    assert normalize_url("https://example.com") == normalize_url("https://example.com/")


def test_default_index_filename_stripped():
    assert normalize_path("/blog/index.html") == normalize_path("/blog/")


def test_leading_trailing_whitespace_stripped():
    assert normalize_path("  /about-us/  ") == normalize_path("/about-us/")


def test_tokenize_removes_stopwords():
    tokens = tokenize_path("/services/residential-roof-cleaning/")
    assert "services" not in tokens
    assert "residential" not in tokens
    assert "roof" in tokens
    assert "cleaning" in tokens


def test_tokenize_can_keep_stopwords():
    tokens = tokenize_path("/services/roof-cleaning/", remove_stopwords=False)
    assert "services" in tokens


def test_tokenize_falls_back_to_unfiltered_when_every_word_is_a_stopword():
    """Regression test: a page that's simply "/services" (a stop word)
    would otherwise tokenize to [], making it invisible to word-overlap
    matching even for an exact, obvious match like "/our-services/". Some
    signal beats none, so the unfiltered words are kept in that case.
    """
    assert tokenize_path("/services") == ["services"]
    assert tokenize_path("/blog") == ["blog"]
    # "our" is a true filler word (always stripped) and "services" is a
    # domain-generic one (stripped only when something else survives) --
    # here both are stop words, so filtering empties the list and the
    # fallback keeps everything rather than losing the page's only content.
    assert tokenize_path("/our-services") == ["our", "services"]
    # But normal filtering still applies when a genuinely distinct word
    # remains alongside a stop word.
    assert tokenize_path("/roof-services") == ["roof"]


def test_final_slug():
    assert get_final_slug("/services/gutter-cleaning/") == "gutter-cleaning"
    assert get_final_slug("/") == ""


def test_parent_path():
    assert get_parent_path("/services/gutter-cleaning/") == "/services"
    assert get_parent_path("/about-us") == "/"
    assert get_parent_path("/") == "/"


def test_path_depth():
    assert get_path_depth("/") == 0
    assert get_path_depth("/about") == 1
    assert get_path_depth("/services/gutter-cleaning") == 2


def test_build_normalized_url_preserves_original():
    n = build_normalized_url("https://OldSite.com/About-Us/?utm_source=x#top")
    assert n.original_url == "https://OldSite.com/About-Us/?utm_source=x#top"
    assert n.normalized_path == "/about-us"
    assert n.final_slug == "about-us"
    assert n.parent_path == "/"
    assert n.path_depth == 1
