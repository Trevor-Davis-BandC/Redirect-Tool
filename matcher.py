"""Layered redirect-matching logic.

For every old URL, this module finds the best candidate destination on the
new site using a sequence of increasingly fuzzy strategies, and returns a
confidence score, a match type label, up to five alternative destinations,
and a plain-language explanation of why the match was chosen.

Matching layers (in priority order):
    1. Exact normalized path match            -> confidence 100
    2. Exact final slug match                 -> confidence 90-96
    3. Token similarity (RapidFuzz)            -> confidence up to 89
    4. Partial path similarity (composite)      -> confidence up to 79
    5. No reliable match                        -> below 60

A placeholder interface for future content-based matching (title/H1/meta
description/body text) is included at the bottom, unused by the MVP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from url_normalizer import NormalizedUrl, build_normalized_url
from config import (
    EXACT_PATH_CONFIDENCE,
    EXACT_SLUG_CONFIDENCE_MIN,
    EXACT_SLUG_CONFIDENCE_MAX,
    TOKEN_SIMILARITY_CONFIDENCE_MAX,
    PARTIAL_SIMILARITY_CONFIDENCE_MAX,
    NEEDS_REVIEW_THRESHOLD,
    AUTO_INCLUDE_MIN_CONFIDENCE,
    BRUTE_FORCE_FALLBACK_LIMIT,
    MAX_ALTERNATIVES,
)
from columns import STATUS_APPROVED, STATUS_NEEDS_REVIEW, STATUS_EXCLUDED, STATUS_UNMAPPED

MATCH_TYPE_EXACT_PATH = "Exact Path"
MATCH_TYPE_EXACT_SLUG = "Exact Slug"
MATCH_TYPE_TOKEN_SIMILARITY = "Token Similarity"
MATCH_TYPE_PARTIAL_SIMILARITY = "Partial Path Similarity"
MATCH_TYPE_NO_MATCH = "No Reliable Match"


@dataclass
class MatchCandidate:
    new_url: str
    new_path: str
    confidence: float
    match_type: str


@dataclass
class MatchResult:
    old_url: str
    old_path: str
    best: MatchCandidate | None
    alternatives: list[MatchCandidate] = field(default_factory=list)
    explanation: str = ""
    include_default: bool = False
    status_default: str = STATUS_NEEDS_REVIEW


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return 100.0 * len(a & b) / len(union)


def _depth_similarity(depth_a: int, depth_b: int) -> float:
    diff = abs(depth_a - depth_b)
    return max(0.0, 100.0 - diff * 20.0)


def token_similarity_score(old: NormalizedUrl, new: NormalizedUrl) -> float:
    """RapidFuzz token-sort ratio over meaningful path words (0-100)."""
    old_str = " ".join(old.tokens)
    new_str = " ".join(new.tokens)
    if not old_str or not new_str:
        return 0.0
    return float(fuzz.token_sort_ratio(old_str, new_str))


def partial_similarity_score(old: NormalizedUrl, new: NormalizedUrl) -> float:
    """Composite score blending slug, parent-folder, depth, and token overlap."""
    slug_ratio = float(fuzz.ratio(old.final_slug, new.final_slug)) if (old.final_slug or new.final_slug) else 0.0
    parent_ratio = float(fuzz.ratio(old.parent_path, new.parent_path))
    depth_sim = _depth_similarity(old.path_depth, new.path_depth)
    token_overlap = _jaccard(set(old.tokens), set(new.tokens))
    return 0.40 * slug_ratio + 0.20 * parent_ratio + 0.15 * depth_sim + 0.25 * token_overlap


def _build_indexes(new_norms: list[NormalizedUrl]):
    path_index: dict[str, int] = {}
    slug_index: dict[str, list[int]] = {}
    token_index: dict[str, list[int]] = {}

    for i, n in enumerate(new_norms):
        path_index.setdefault(n.normalized_path, i)
        if n.final_slug:
            slug_index.setdefault(n.final_slug, []).append(i)
        for tok in set(n.tokens):
            token_index.setdefault(tok, []).append(i)

    return path_index, slug_index, token_index


def _candidates_to_alternatives(
    scored: list[tuple[int, float, str]], new_norms: list[NormalizedUrl]
) -> list[MatchCandidate]:
    seen_urls = set()
    alts = []
    for idx, score, match_type in scored:
        n = new_norms[idx]
        if n.original_url in seen_urls:
            continue
        seen_urls.add(n.original_url)
        alts.append(
            MatchCandidate(
                new_url=n.original_url,
                new_path=n.original_path,
                confidence=round(score, 1),
                match_type=match_type,
            )
        )
        if len(alts) >= MAX_ALTERNATIVES:
            break
    return alts


def _explain(match_type: str, confidence: float, old: NormalizedUrl, best_new: NormalizedUrl | None) -> str:
    if match_type == MATCH_TYPE_EXACT_PATH:
        return "The destination's normalized path is identical to the source path."
    if match_type == MATCH_TYPE_EXACT_SLUG:
        return (
            f"The final URL segment ('{old.final_slug}') matches a page on the new site exactly, "
            "even though the folder structure is different."
        )
    if match_type == MATCH_TYPE_TOKEN_SIMILARITY:
        return f"The meaningful words in the path are very similar ({confidence:.0f}% similarity), even though the path structure differs."
    if match_type == MATCH_TYPE_PARTIAL_SIMILARITY:
        return f"Some words and folder structure are similar ({confidence:.0f}% composite score), but this match is not certain."
    return "No page on the new site shares enough words or path structure with this URL to suggest a confident match."


def match_single_url(
    old_norm: NormalizedUrl,
    new_norms: list[NormalizedUrl],
    path_index: dict[str, int],
    slug_index: dict[str, list[int]],
    token_index: dict[str, list[int]],
) -> MatchResult:
    old_url = old_norm.original_url
    old_path = old_norm.original_path

    # --- Layer 1: exact normalized path ---
    if old_norm.normalized_path in path_index:
        idx = path_index[old_norm.normalized_path]
        n = new_norms[idx]
        best = MatchCandidate(
            new_url=n.original_url,
            new_path=n.original_path,
            confidence=float(EXACT_PATH_CONFIDENCE),
            match_type=MATCH_TYPE_EXACT_PATH,
        )
        result = MatchResult(old_url=old_url, old_path=old_path, best=best, alternatives=[])
        result.explanation = _explain(MATCH_TYPE_EXACT_PATH, best.confidence, old_norm, n)
        result.include_default = True
        result.status_default = STATUS_APPROVED
        return result

    # --- Layer 2: exact final slug ---
    if old_norm.final_slug and old_norm.final_slug in slug_index:
        candidate_idxs = slug_index[old_norm.final_slug]
        scored = []
        for idx in candidate_idxs:
            n = new_norms[idx]
            parent_ratio = float(fuzz.ratio(old_norm.parent_path, n.parent_path))
            bonus = (parent_ratio / 100.0) * (EXACT_SLUG_CONFIDENCE_MAX - EXACT_SLUG_CONFIDENCE_MIN)
            score = EXACT_SLUG_CONFIDENCE_MIN + bonus
            scored.append((idx, score, MATCH_TYPE_EXACT_SLUG))
        scored.sort(key=lambda t: t[1], reverse=True)

        # Also add token-similarity alternatives for extra visibility.
        extra = _fuzzy_candidates(old_norm, new_norms, token_index)
        for idx, score, mtype in extra:
            if idx not in candidate_idxs:
                scored.append((idx, score, mtype))
        scored.sort(key=lambda t: t[1], reverse=True)

        best_idx, best_score, best_type = scored[0]
        best_n = new_norms[best_idx]
        best = MatchCandidate(
            new_url=best_n.original_url,
            new_path=best_n.original_path,
            confidence=round(best_score, 1),
            match_type=best_type,
        )
        alternatives = _candidates_to_alternatives(scored[1:], new_norms)
        result = MatchResult(old_url=old_url, old_path=old_path, best=best, alternatives=alternatives)
        result.explanation = _explain(best_type, best.confidence, old_norm, best_n)
        result.include_default = best.confidence >= AUTO_INCLUDE_MIN_CONFIDENCE
        result.status_default = STATUS_APPROVED if result.include_default else STATUS_NEEDS_REVIEW
        return result

    # --- Layers 3 & 4: fuzzy token / partial similarity ---
    scored = _fuzzy_candidates(old_norm, new_norms, token_index, allow_brute_force=len(new_norms) <= BRUTE_FORCE_FALLBACK_LIMIT)
    scored.sort(key=lambda t: t[1], reverse=True)

    if not scored:
        result = MatchResult(old_url=old_url, old_path=old_path, best=None, alternatives=[])
        result.explanation = _explain(MATCH_TYPE_NO_MATCH, 0, old_norm, None)
        result.include_default = False
        result.status_default = STATUS_NEEDS_REVIEW
        return result

    best_idx, best_score, best_type = scored[0]
    best_n = new_norms[best_idx]

    if best_score < NEEDS_REVIEW_THRESHOLD:
        best = MatchCandidate(
            new_url=best_n.original_url,
            new_path=best_n.original_path,
            confidence=round(best_score, 1),
            match_type=MATCH_TYPE_NO_MATCH,
        )
        alternatives = _candidates_to_alternatives(scored[1:], new_norms)
        result = MatchResult(old_url=old_url, old_path=old_path, best=best, alternatives=alternatives)
        result.explanation = _explain(MATCH_TYPE_NO_MATCH, best.confidence, old_norm, best_n)
        result.include_default = False
        result.status_default = STATUS_NEEDS_REVIEW
        return result

    best = MatchCandidate(
        new_url=best_n.original_url,
        new_path=best_n.original_path,
        confidence=round(best_score, 1),
        match_type=best_type,
    )
    alternatives = _candidates_to_alternatives(scored[1:], new_norms)
    result = MatchResult(old_url=old_url, old_path=old_path, best=best, alternatives=alternatives)
    result.explanation = _explain(best_type, best.confidence, old_norm, best_n)
    result.include_default = best.confidence >= AUTO_INCLUDE_MIN_CONFIDENCE
    result.status_default = STATUS_APPROVED if result.include_default else STATUS_NEEDS_REVIEW
    return result


def _fuzzy_candidates(
    old_norm: NormalizedUrl,
    new_norms: list[NormalizedUrl],
    token_index: dict[str, list[int]],
    allow_brute_force: bool = True,
) -> list[tuple[int, float, str]]:
    pool: set[int] = set()
    for tok in old_norm.tokens:
        pool.update(token_index.get(tok, []))

    if not pool and allow_brute_force:
        pool = set(range(len(new_norms)))

    scored = []
    for idx in pool:
        n = new_norms[idx]
        token_score = token_similarity_score(old_norm, n)
        partial_score = partial_similarity_score(old_norm, n)
        if token_score >= partial_score:
            raw = min(token_score, TOKEN_SIMILARITY_CONFIDENCE_MAX)
            mtype = MATCH_TYPE_TOKEN_SIMILARITY
        else:
            raw = min(partial_score, PARTIAL_SIMILARITY_CONFIDENCE_MAX)
            mtype = MATCH_TYPE_PARTIAL_SIMILARITY
        scored.append((idx, raw, mtype))
    return scored


def generate_redirect_suggestions(old_urls: list[str], new_urls: list[str]) -> list[MatchResult]:
    """Generate a MatchResult for every old URL against the pool of new URLs."""
    old_norms = [build_normalized_url(u) for u in old_urls]
    new_norms = [build_normalized_url(u) for u in new_urls]

    path_index, slug_index, token_index = _build_indexes(new_norms)

    results = []
    for old_norm in old_norms:
        results.append(match_single_url(old_norm, new_norms, path_index, slug_index, token_index))
    return results


# ---------------------------------------------------------------------------
# Future content-matching placeholder (NOT implemented in this MVP).
#
# The layered matching pipeline above is organized so a content-based signal
# can be added later without restructuring: a new layer would compute a
# score here, blend it into `_fuzzy_candidates`, and contribute its own
# match-type label (e.g. "Content Similarity"). No AI/embedding calls are
# made in the MVP -- this is a documented extension point only.
# ---------------------------------------------------------------------------


@dataclass
class PageContent:
    """Container for page signals a future content-matching layer would use."""

    title: str = ""
    h1: str = ""
    meta_description: str = ""
    main_content: str = ""


def content_similarity_score(old_content: "PageContent | None", new_content: "PageContent | None") -> float | None:
    """Placeholder for a future content-based similarity score (0-100).

    Not implemented in the MVP -- no crawling or AI calls are performed.
    Returns None to indicate the signal is unavailable, so callers should
    treat this as "no opinion" rather than a low score.
    """
    return None
