"""Shared column-name constants for the redirect review table.

Centralized so app.py, matcher.py output, validator.py, exporter.py, and
project_storage.py all agree on the same field names.
"""

COL_INCLUDE = "Include"
COL_OLD_URL = "Old URL"
COL_OLD_PATH = "Old Path"
COL_NEW_URL = "Suggested New URL"
COL_NEW_PATH = "Suggested New Path"
COL_CONFIDENCE = "Confidence Score"
COL_MATCH_TYPE = "Match Type"
COL_STATUS = "Status"
COL_NOTES = "Notes"

# Internal-only columns, not shown as primary table columns but carried
# alongside each row for alternative-match lookups and status tracking.
COL_ALTERNATIVES = "_alternatives"
COL_EXPLANATION = "_explanation"

ALL_COLUMNS = [
    COL_INCLUDE,
    COL_OLD_URL,
    COL_OLD_PATH,
    COL_NEW_URL,
    COL_NEW_PATH,
    COL_CONFIDENCE,
    COL_MATCH_TYPE,
    COL_STATUS,
    COL_NOTES,
]

STATUS_APPROVED = "Approved"
STATUS_NEEDS_REVIEW = "Needs Review"
STATUS_EXCLUDED = "Excluded"
STATUS_UNMAPPED = "Unmapped"

ALL_STATUSES = [STATUS_APPROVED, STATUS_NEEDS_REVIEW, STATUS_EXCLUDED, STATUS_UNMAPPED]
