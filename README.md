# Redirect Tool

Redirect Tool is a local, browser-based tool for planning website
migrations. It compares the XML sitemap of an old website to the sitemap of
a new website, suggests redirects between matching pages, lets you review
and edit those suggestions, validates the final list, and exports a CSV you
can import directly into **Duda's bulk URL redirect tool**.

It is intentionally narrow in scope. It is **not** a crawler, an SEO audit
tool, or a Screaming Frog replacement -- it only reads sitemaps, compares
URLs, and helps you build a clean redirect list.

## What it does

1. You enter an old domain and a new domain (or a Duda preview-domain URL --
   e.g. a temporary `*.bvmlocal.com` staging site).
2. It looks for each site's XML sitemap automatically (checking `robots.txt`
   and common sitemap paths), following sitemap indexes and nested sitemaps.
3. It compares every old URL against every new URL and suggests a
   destination for each one. If nothing on the new site is a clear match,
   the destination defaults to the homepage (`/`) rather than being left
   unmapped -- every old URL always ends up with a usable destination.
4. You review the suggestions in a plain editable table: edit the
   destination path directly, uncheck **Include** to exclude a row, or set
   **Status** to *Unmapped* for pages you're intentionally not redirecting.
5. It validates the final list for the issues that would actually break a
   Duda import: duplicate source paths, blank/missing destinations, and
   duplicate redirect rules.
6. It exports a CSV matching Duda's own bulk redirect import template
   (`Old Page URL,Destination Page URL, Redirect Type`), or fills in a
   different uploaded Duda template CSV.

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

## Sharing with a team (free, password-protected)

To let teammates use the app without installing anything, deploy it to
[Streamlit Community Cloud](https://share.streamlit.io) (free, no per-app
cost) as a normal **public** app -- then lock it with a shared password so
strangers with the URL can't get in:

1. Push this repo to GitHub (public or private both work).
2. On [share.streamlit.io](https://share.streamlit.io), create a new app
   pointing at this repo, branch `main`, main file `app.py`. Leave sharing
   set to the default (do **not** use Streamlit's "private app" viewer-list
   feature -- the free tier caps that at one app, and it requires each
   viewer to sign in and link a GitHub/Google account).
3. In the app's **Settings -> Secrets**, paste:
   ```toml
   APP_PASSWORD = "choose-a-shared-team-password"
   ```
   (see `.streamlit/secrets.toml.example` for the template).
4. Share the app's URL and the password with your team. They open the link,
   type the password once per session, and use the app -- no account, no
   sign-in, no GitHub access required on their end.

If `APP_PASSWORD` isn't set (the default for local/double-click use), the
app skips the password screen entirely and behaves exactly as before.

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

For each domain, Redirect Tool:

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

Redirect Tool does **not** crawl a site to find pages; if no sitemap can
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

## How matching works

The review table is intentionally simple -- no confidence scores or match
labels are shown -- but under the hood, every old URL is still compared
against the new site's URLs using a few layers, tried in order: exact
normalized path, exact final URL segment ("slug"), then word/path
similarity (via RapidFuzz). Whichever layer produces a hit becomes the
suggested destination.

**If nothing is a reliable match, the destination defaults to the
homepage (`/`)** instead of being left blank -- every old URL always ends
up with a real destination ready to export. Rows are still marked
**Status: Needs Review** in that case (and get a `302` instead of `301`,
since it's a fallback rather than a confirmed page-to-page move) so you
know to double-check them, but nothing blocks export by default.

Common low-value words (`service`, `page`, `category`, `blog`, `html`,
etc. -- see `config.STOP_WORDS`) are ignored only when scoring similarity.
They are never removed from the URLs you actually see or export.

The matching code is organized so a future content-based signal (page
title, H1, meta description, body text) could be added as an additional
layer later -- see the `PageContent` / `content_similarity_score()`
placeholder at the bottom of `matcher.py`. It does nothing in this MVP; no
AI APIs or content crawling are used.

## How Duda CSV export works

By default, the export matches Duda's own bulk URL redirect import
template exactly -- a three-column CSV (see `sample_data/duda_import_template.csv`
for the reference file this is based on):

```csv
Old Page URL,Destination Page URL, Redirect Type
/old-page,/new-page,301
/old-about,/about,301
/contact-old,/,302
```

Note the header's leading space before `Redirect Type` -- that's preserved
verbatim because it matches Duda's own template exactly.

**Redirect Type** is editable per row in the review table (301 = permanent,
302 = temporary). It defaults to `301` for confident, real page-to-page
matches, and `302` for anything that falls back to the homepage or has no
reliable match, since those aren't confirmed permanent mappings.

Rules applied automatically:

- Only rows with **Include** checked are exported.
- Rows marked **Unmapped** are excluded, even if checked.
- Only the path is exported -- scheme and host are always stripped, fragments
  are removed, and leading slashes are preserved. This matters if your "new"
  site is actually a temporary staging/preview domain (e.g. a
  `*.bvmlocal.com` test environment): that domain is discovered and used
  only to compare site structure, and **never** appears in the exported CSV,
  even though it may show up in the on-screen "Suggested New URL" column so
  you can click through and preview the actual page while reviewing.
- Duplicate source paths are collapsed to a single row (the validator will
  have already flagged this as a critical issue to resolve).
- The file is UTF-8 encoded and values are CSV-escaped automatically.
- The filename includes your project name and today's date, e.g.
  `my-project-redirects-2026-07-15.csv`.

**Duda only accepts 200 redirects per CSV import.** If your export has more
than that, Redirect Tool automatically splits it into multiple files --
`my-project-redirects-2026-07-15-part1-of-3.csv`, `-part2-of-3.csv`, and so
on -- each with a separate download button. Import them into Duda one at a
time. This limit is configurable via `config.MAX_REDIRECTS_PER_CSV`.

You can also upload a different Duda-exported template CSV if a particular
client/site needs different columns. Redirect Tool reads its header row,
guesses which column is the source URL, the destination URL, and the
redirect-type column (by looking for words like "old"/"source",
"new"/"destination", and "type"/"redirect type"), and lets you correct any
guess if needed. Any other columns in the template are preserved and filled
with a default value taken from the template's first example row (if it has
one) -- your redirect data is never written into unrelated columns.

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
- Validation is intentionally minimal -- it checks for duplicate source
  paths, blank/missing destinations, and duplicate redirect rules. It does
  not check for redirect loops/chains, external destinations, or how often a
  destination is reused, since redirecting many unmatched pages to the
  homepage is expected in this workflow, not a problem to flag.
- There is no undo/history for edits within a session beyond re-loading a
  previously saved project JSON.

## Future improvement ideas

- Optional content-based matching (title/H1/meta description similarity)
  using the documented extension point in `matcher.py`.
- Bulk actions in the review table (e.g. "approve all Needs Review rows").
- Direct integration with Duda's API to push redirects without a manual CSV
  import, if/when that becomes available.
- Support for additional sitemap formats (e.g. RSS/Atom-based feeds).
- A diff view to compare two saved project JSON files.
