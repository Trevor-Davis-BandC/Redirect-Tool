# Migration Mapper

Migration Mapper is a local, browser-based tool for planning website
migrations. It compares the XML sitemap of an old website to the sitemap of
a new website, suggests redirects between matching pages, lets you review
and edit those suggestions, validates the final list, and exports a CSV you
can import directly into **Duda's bulk URL redirect tool**.

It is intentionally narrow in scope. It is **not** a crawler, an SEO audit
tool, or a Screaming Frog replacement -- it only reads sitemaps, compares
URLs, and helps you build a clean redirect list.

## What it does

1. You enter an old domain and a new domain (or a Duda preview-domain URL).
2. It looks for each site's XML sitemap automatically (checking `robots.txt`
   and common sitemap paths), following sitemap indexes and nested sitemaps.
3. It compares every old URL against every new URL using a layered matching
   system (exact path, exact slug, token similarity, partial similarity) and
   assigns each suggestion a 0-100 confidence score.
4. You review the suggestions in an editable table: approve, exclude, mark
   as intentionally unmapped, pick an alternative destination, or type a
   custom one.
5. It validates the final list for common redirect problems (duplicates,
   loops, chains, self-redirects, missing destinations, external links,
   homepage fallbacks) before you export.
6. It exports a CSV in Duda's `Old URL,New URL` format, or fills in an
   uploaded Duda template CSV.

## Requirements

- Python 3.11 or newer
- macOS, Linux, or Windows
- Internet access to reach the old and new websites (no other external
  services or paid APIs are used)

## Installation

### 1. Create a virtual environment

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows (Command Prompt):

```bat
python -m venv .venv
.venv\Scripts\activate.bat
```

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

## Running the application

```bash
streamlit run app.py
```

Streamlit will print a local URL (typically `http://localhost:8501`) and
should open it in your browser automatically.

## Running the tests

```bash
pytest
```

This runs the full automated test suite (URL normalization, sitemap
parsing, matching, validation, and CSV export) using sample XML fixtures
under `tests/fixtures/`.

## Project structure

```
app.py                 Streamlit UI (the 4-page workflow)
sitemap.py              Sitemap discovery and XML parsing
url_normalizer.py        URL normalization and tokenization helpers
matcher.py               Layered redirect-matching logic and confidence scoring
validator.py             Pre-export validation checks
exporter.py               Duda CSV export (default + template-based)
project_storage.py        Save/load a project as local JSON
columns.py                 Shared column-name constants for the redirect table
config.py                   Limits and tunable thresholds
sample_data/sample_redirects.csv   Example of the default export format
tests/                        Pytest suite + XML fixtures
```

## How sitemap discovery works

For each domain, Migration Mapper:

1. Fetches `/robots.txt` and looks for `Sitemap:` declarations.
2. Falls back to trying, in order: `/sitemap.xml`, `/sitemap_index.xml`,
   `/sitemap-index.xml`, `/wp-sitemap.xml`.
3. Parses whatever XML it finds. If it's a `<sitemapindex>`, it follows each
   listed sitemap (including relative references) up to a recursion depth
   and file-count limit. If it's a `<urlset>`, it collects the page URLs.
4. Deduplicates the collected URLs and reports how many duplicates were
   removed.

If you already know the sitemap URL (or the site doesn't publish one in a
standard location), enter it directly in the **sitemap URL override** field
on the New Project page -- this skips discovery and parses that URL only.

Migration Mapper does **not** crawl a site to find pages; if no sitemap can
be found, it tells you so and asks for a manual URL rather than guessing.

Safety limits (configurable in `config.py`):

- Maximum 100 sitemap files per site
- Maximum 20,000 URLs per site
- Maximum recursion depth of 5 (for nested sitemap indexes)
- 15-second request timeout per fetch
- Refuses to fetch `localhost`, private/loopback IP addresses, or non-HTTP(S)
  URLs (including `file://`), to prevent the app from being used to probe
  your local network
- XML is parsed with entity resolution and network access disabled, to
  prevent XXE-style attacks

## How confidence scores work

Every old URL is compared against the new site's URLs using four layers,
tried in order:

| Match type | Confidence | What it means |
|---|---|---|
| Exact Path | 100 | The normalized path is identical on both sites. |
| Exact Slug | 90-96 | The final URL segment matches exactly, even though the folder path differs. |
| Token Similarity | up to 89 | The meaningful words in the path are very similar (via RapidFuzz), ignoring order. |
| Partial Path Similarity | up to 79 | Some combination of shared words, slug, parent folder, and depth suggests a loose match. |
| No Reliable Match | below 60 | Nothing on the new site is similar enough to suggest with confidence. |

Common low-value words (`service`, `page`, `category`, `blog`, `html`,
etc. -- see `config.STOP_WORDS`) are ignored only when scoring similarity.
They are never removed from the URLs you actually see or export.

Only exact/near-exact matches (95+) are included by default; everything
else starts out unchecked with a status of "Needs Review" so a person signs
off on it. Unmatched pages are **never** automatically redirected to the
homepage -- they're flagged for manual review instead.

The matching code is organized so a future content-based signal (page
title, H1, meta description, body text) could be added as an additional
layer later -- see the `PageContent` / `content_similarity_score()`
placeholder at the bottom of `matcher.py`. It does nothing in this MVP; no
AI APIs or content crawling are used.

## How Duda CSV export works

By default, the export is a two-column CSV:

```csv
Old URL,New URL
/old-page,/new-page
/old-about,/about
```

Rules applied automatically:

- Only rows with **Include** checked are exported.
- Rows marked **Unmapped** are excluded, even if checked.
- Only the path is exported (scheme/host are stripped; fragments are
  removed; leading slashes are preserved).
- Duplicate source paths are collapsed to a single row (the validator will
  have already flagged this as a critical issue to resolve).
- The file is UTF-8 encoded and values are CSV-escaped automatically.
- The filename includes your project name and today's date, e.g.
  `my-project-redirects-2026-07-15.csv`.

You can also upload a Duda-exported template CSV. Migration Mapper reads its
header row, guesses which column is the source URL and which is the
destination URL (by looking for words like "old"/"source" and
"new"/"destination"), and lets you correct the guess if needed. Any other
columns in the template are preserved and filled with a default value taken
from the template's first example row (if it has one) -- your redirect data
is never written into unrelated columns.

## Known MVP limitations

- Sitemap discovery only checks the standard locations listed above; it does
  not crawl the site to discover pages that aren't in a sitemap.
- Matching relies entirely on URL structure (words, path shape). It does not
  look at page titles, headings, or content -- see the content-matching
  placeholder in `matcher.py` for how this could be extended.
- Very large sitemaps (tens of thousands of URLs) will fall back to a
  token-index-based comparison rather than a full brute-force comparison
  between every old/new pair, which can occasionally miss a loose match that
  shares no tokens at all.
- Redirect-loop/chain detection operates only on the redirect list you've
  built in this session -- it can't detect a loop that involves a rule
  already live on the production server.
- There is no undo/history for edits within a session beyond re-loading a
  previously saved project JSON.

## Future improvement ideas

- Optional content-based matching (title/H1/meta description similarity)
  using the documented extension point in `matcher.py`.
- Bulk actions in the review table (e.g. "approve all Strong Suggestions").
- Direct integration with Duda's API to push redirects without a manual CSV
  import, if/when that becomes available.
- Support for additional sitemap formats (e.g. RSS/Atom-based feeds).
- A diff view to compare two saved project JSON files.
