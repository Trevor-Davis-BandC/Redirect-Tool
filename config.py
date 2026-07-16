"""Central configuration and safety limits for Redirect Tool.

Keep all tunable limits here so they are easy to find and adjust.
"""

APP_VERSION = "0.1.0"

# --- Network / discovery limits ---
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = "RedirectToolBot/0.1 (+local website migration tool; contact: site-admin)"
MAX_SITEMAP_FILES = 100
MAX_URLS_PER_SITE = 20000
MAX_SITEMAP_RECURSION_DEPTH = 5

# Candidate sitemap paths to probe when no override is supplied, in priority order.
SITEMAP_CANDIDATE_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
]

ROBOTS_TXT_PATH = "/robots.txt"

# --- Matching thresholds ---
EXACT_PATH_CONFIDENCE = 100
EXACT_SLUG_CONFIDENCE_MAX = 96
EXACT_SLUG_CONFIDENCE_MIN = 90
TOKEN_SIMILARITY_CONFIDENCE_MAX = 89
PARTIAL_SIMILARITY_CONFIDENCE_MAX = 79

STRONG_SUGGESTION_THRESHOLD = 80
NEEDS_REVIEW_THRESHOLD = 60
# Below NEEDS_REVIEW_THRESHOLD => No Reliable Match

AUTO_INCLUDE_MIN_CONFIDENCE = 95  # exact / near-exact matches may be auto-included

# Low value words ignored only during similarity scoring (never stripped from export URLs).
STOP_WORDS = {
    "service",
    "services",
    "page",
    "pages",
    "category",
    "categories",
    "residential",
    "commercial",
    "blog",
    "post",
    "posts",
    "index",
    "html",
    "php",
}

DEFAULT_INDEX_FILENAMES = {
    "index.html",
    "index.htm",
    "index.php",
    "default.html",
    "default.htm",
}

# Warn when a single destination absorbs more than this many source redirects.
DESTINATION_REUSE_WARNING_THRESHOLD = 5

# If an old URL shares no tokens with any new URL, only fall back to a full
# brute-force comparison when the new sitemap is smaller than this, to keep
# matching fast on large sites.
BRUTE_FORCE_FALLBACK_LIMIT = 3000

MAX_ALTERNATIVES = 5

# Blocked network targets (SSRF guardrails).
BLOCKED_HOSTNAMES = {"localhost"}
