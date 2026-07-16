"""Shared column-name constants for the redirect review table.

Centralized so app.py, matcher.py output, validator.py, exporter.py, and
project_storage.py all agree on the same field names.
"""

COL_INCLUDE = "Include"
COL_OLD_URL = "Old URL"
COL_OLD_PATH = "Old Path"
COL_NEW_URL = "Suggested New URL"
COL_NEW_PATH = "Suggested New Path"
COL_REDIRECT_TYPE = "Redirect Type"
COL_STATUS = "Status"
COL_NOTES = "Notes"

# Kept for backward compatibility with saved project JSON files and existing
# tests. No longer part of ALL_COLUMNS -- the review table no longer shows a
# numeric confidence score or match-type label; matching still happens
# internally in matcher.py, it's just not surfaced as separate columns.
COL_CONFIDENCE = "Confidence Score"
COL_MATCH_TYPE = "Match Type"

ALL_COLUMNS = [
    COL_INCLUDE,
    COL_OLD_URL,
    COL_OLD_PATH,
    COL_NEW_URL,
    COL_NEW_PATH,
    COL_REDIRECT_TYPE,
    COL_STATUS,
    COL_NOTES,
]

STATUS_APPROVED = "Approved"
STATUS_NEEDS_REVIEW = "Needs Review"
STATUS_EXCLUDED = "Excluded"
STATUS_UNMAPPED = "Unmapped"

ALL_STATUSES = [STATUS_APPROVED, STATUS_NEEDS_REVIEW, STATUS_EXCLUDED, STATUS_UNMAPPED]

REDIRECT_TYPE_PERMANENT = "301"
REDIRECT_TYPE_TEMPORARY = "302"
REDIRECT_TYPE_OPTIONS = [REDIRECT_TYPE_PERMANENT, REDIRECT_TYPE_TEMPORARY]
