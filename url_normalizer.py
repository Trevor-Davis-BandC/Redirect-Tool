"""URL normalization utilities.

Produces comparable, deduplicated representations of URLs while preserving
the original URL for display and export. Nothing here mutates data that
will be exported -- normalization is only used for comparison/matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit, unquote

from config import STOP_WORDS, DEFAULT_INDEX_FILENAMES


@dataclass
class NormalizedUrl:
    """All the derived fields we need for comparison, display, and export."""

    original_url: str
    normalized_url: str
    original_path: str
    normalized_path: str
    tokens: list[str] = field(default_factory=list)
    final_slug: str = ""
    parent_path: str = ""
    path_depth: int = 0
    is_homepage: bool = False


def _collapse_slashes(path: str) -> str:
    out = []
    prev_slash = False
    for ch in path:
        if ch == "/":
            if prev_slash:
                continue
            prev_slash = True
        else:
            prev_slash = False
        out.append(ch)
    return "".join(out)


def _strip_default_index(path: str) -> str:
    """Remove trailing default index filenames (e.g. /foo/index.html -> /foo/)."""
    segments = path.split("/")
    if segments and segments[-1].lower() in DEFAULT_INDEX_FILENAMES:
        segments[-1] = ""
    return "/".join(segments)


def normalize_path(path: str) -> str:
    """Normalize a URL path for comparison purposes.

    Handles percent-decoding, case, duplicate slashes, trailing slashes,
    and default index filenames. Always returns a leading-slash path.
    """
    path = (path or "").strip()
    if not path:
        return "/"

    path = unquote(path)
    path = path.lower()
    path = _collapse_slashes(path)

    if not path.startswith("/"):
        path = "/" + path

    path = _strip_default_index(path)

    # Trailing slash normalization: treat "/foo" and "/foo/" as equivalent,
    # but always keep the root as "/".
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
        if not path:
            path = "/"

    return path or "/"


def normalize_url(url: str) -> str:
    """Normalize a full URL for comparison: scheme, host, path, query.

    - Forces https scheme for comparison (http vs https treated as equivalent)
    - Strips a leading "www."
    - Drops fragments
    - Normalizes path per normalize_path()
    - Keeps query string (sorted) since it can matter for some sites, but
      most sitemap URLs won't have one.
    """
    url = (url or "").strip()
    if not url:
        return ""

    parts = urlsplit(url)
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    # Drop port if it's a default one
    if netloc.endswith(":80") or netloc.endswith(":443"):
        netloc = netloc.rsplit(":", 1)[0]

    path = normalize_path(parts.path)

    query = parts.query
    if query:
        pairs = sorted(p for p in query.split("&") if p)
        query = "&".join(pairs)

    normalized = urlunsplit(("https", netloc, path, query, ""))
    return normalized


def tokenize_path(path: str, remove_stopwords: bool = True) -> list[str]:
    """Break a normalized path into meaningful lowercase word tokens.

    If every word in the path happens to be a stop word (e.g. a page is
    simply "/services" or "/blog" -- both stop words, since they're usually
    noise inside a longer slug), stripping them all would leave zero tokens
    and make that page invisible to word-overlap matching even though it's
    an exact, obvious match for a similarly-named old page. In that case the
    unfiltered words are kept instead -- some signal beats none.
    """
    path = path.lower()
    # Split on path separators, hyphens, underscores, and dots
    raw = path.replace("_", "-").split("/")
    all_words: list[str] = []
    filtered_words: list[str] = []
    for segment in raw:
        if not segment:
            continue
        for word in segment.replace(".", "-").split("-"):
            word = word.strip()
            if not word:
                continue
            all_words.append(word)
            if not (remove_stopwords and word in STOP_WORDS):
                filtered_words.append(word)
    if remove_stopwords and not filtered_words and all_words:
        return all_words
    return filtered_words


def get_final_slug(path: str) -> str:
    """Return the last non-empty path segment, or '' for the homepage."""
    path = path.rstrip("/")
    if not path:
        return ""
    segments = [s for s in path.split("/") if s]
    return segments[-1] if segments else ""


def get_parent_path(path: str) -> str:
    """Return the parent directory path of a normalized path."""
    path = path.rstrip("/")
    if not path:
        return "/"
    segments = [s for s in path.split("/") if s]
    if len(segments) <= 1:
        return "/"
    return "/" + "/".join(segments[:-1])


def get_path_depth(path: str) -> int:
    path = path.rstrip("/")
    if not path:
        return 0
    return len([s for s in path.split("/") if s])


def build_normalized_url(original_url: str) -> NormalizedUrl:
    """Build the full set of normalized fields for a single URL."""
    original_url = (original_url or "").strip()
    parts = urlsplit(original_url)
    original_path = parts.path or "/"

    normalized_full = normalize_url(original_url)
    normalized_path = urlsplit(normalized_full).path or "/"

    tokens = tokenize_path(normalized_path)
    slug = get_final_slug(normalized_path)
    parent = get_parent_path(normalized_path)
    depth = get_path_depth(normalized_path)
    is_home = normalized_path == "/"

    return NormalizedUrl(
        original_url=original_url,
        normalized_url=normalized_full,
        original_path=original_path,
        normalized_path=normalized_path,
        tokens=tokens,
        final_slug=slug,
        parent_path=parent,
        path_depth=depth,
        is_homepage=is_home,
    )
