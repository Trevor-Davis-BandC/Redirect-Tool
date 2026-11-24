"""PDF redirect report generation.

Builds a downloadable summary PDF covering the full redirect list --
matched (approved) redirects, suggested (needs-review) redirects,
removed/excluded URLs, intentionally unmapped URLs, and any validation
issues -- useful as a record to keep or share after a migration.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fpdf import FPDF

from columns import (
    COL_OLD_PATH,
    COL_NEW_PATH,
    COL_REDIRECT_TYPE,
    COL_STATUS,
    COL_NOTES,
    STATUS_APPROVED,
    STATUS_NEEDS_REVIEW,
    STATUS_EXCLUDED,
    STATUS_UNMAPPED,
)
from config import HOMEPAGE_REDIRECT_WARNING_THRESHOLD
from validator import ValidationReport

PAGE_MARGIN = 15
NAVY = (27, 44, 66)
GRAY = (90, 90, 90)


def _pdf_safe(text: str) -> str:
    """Make text safe for the core Helvetica font, which only supports
    Latin-1. Redirect data (URLs, project/domain names, GSC-sourced paths)
    is free-form and can contain arbitrary characters -- rather than crash
    the whole report on one unsupported character, swap it for "?" so the
    PDF still generates.
    """
    return text.encode("latin-1", "replace").decode("latin-1")


class _ReportPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")


def _section_title(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 9, _pdf_safe(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _bullet_list(pdf: FPDF, items: list[str], empty_text: str) -> None:
    pdf.set_font("Helvetica", "", 9)
    if not items:
        pdf.multi_cell(0, 5, _pdf_safe(f"- {empty_text}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        return
    for item in items:
        pdf.multi_cell(0, 5, _pdf_safe(f"- {item}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _redirect_lines(df: pd.DataFrame) -> list[str]:
    lines = []
    for _, row in df.iterrows():
        old_path = row.get(COL_OLD_PATH, "")
        new_path = row.get(COL_NEW_PATH, "")
        redirect_type = row.get(COL_REDIRECT_TYPE, "")
        notes = str(row.get(COL_NOTES, "") or "").strip()
        line = f"{old_path}  ->  {new_path or '(none)'}  [{redirect_type}]"
        if notes:
            line += f"  -- {notes}"
        lines.append(line)
    return lines


def build_redirect_report_pdf(
    project_name: str,
    old_domain: str,
    new_domain: str,
    df: pd.DataFrame,
    report: ValidationReport,
) -> bytes:
    """Build a PDF summarizing the full redirect list for record-keeping."""
    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=PAGE_MARGIN)
    pdf.set_margins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 12, "Redirect Report", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 6, _pdf_safe(f"Project: {project_name or '(untitled)'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _pdf_safe(f"Old domain: {old_domain or '(not set)'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _pdf_safe(f"New domain: {new_domain or '(not set)'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Generated: {date.today().isoformat()}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)

    matched_df = df[df[COL_STATUS] == STATUS_APPROVED]
    suggested_df = df[df[COL_STATUS] == STATUS_NEEDS_REVIEW]
    removed_df = df[df[COL_STATUS] == STATUS_EXCLUDED]
    unmapped_df = df[df[COL_STATUS] == STATUS_UNMAPPED]

    _section_title(pdf, "Summary")
    pdf.set_font("Helvetica", "", 10)
    summary_lines = [
        f"Total old URLs: {len(df)}",
        f"Matched (Approved): {len(matched_df)}",
        f"Suggested (Needs Review): {len(suggested_df)}",
        f"Removed (Excluded): {len(removed_df)}",
        f"Unmapped (intentionally not redirected): {len(unmapped_df)}",
    ]
    for line in summary_lines:
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    _section_title(pdf, f"Matched Redirects ({len(matched_df)})")
    _bullet_list(pdf, _redirect_lines(matched_df), "No confidently matched redirects.")

    _section_title(pdf, f"Suggested Redirects -- Needs Review ({len(suggested_df)})")
    _bullet_list(pdf, _redirect_lines(suggested_df), "No suggested redirects awaiting review.")

    _section_title(pdf, f"Removed URLs ({len(removed_df)})")
    _bullet_list(pdf, _redirect_lines(removed_df), "No URLs were removed.")

    _section_title(pdf, f"Unmapped URLs ({len(unmapped_df)})")
    _bullet_list(pdf, [str(p) for p in unmapped_df[COL_OLD_PATH]], "No intentionally unmapped URLs.")

    _section_title(pdf, "Important Notes")
    _bullet_list(
        pdf,
        [f"Duplicate source path: {p}" for p in report.duplicate_source_paths],
        "No duplicate source paths.",
    )
    _bullet_list(
        pdf,
        [f"Duplicate redirect rule: {s} -> {d}" for s, d in report.duplicate_redirect_rules],
        "No duplicate redirect rules.",
    )
    _bullet_list(
        pdf,
        [f"Blank or missing destination: {p}" for p in report.blank_or_malformed],
        "No blank or missing destinations.",
    )
    _bullet_list(
        pdf,
        [f"Redirects to itself: {p}" for p in report.self_redirects]
        + [f"Redirect loop: {c}" for c in report.redirect_loops],
        "No self-redirects or redirect loops.",
    )
    _bullet_list(pdf, [f"Redirect chain: {c}" for c in report.redirect_chains], "No redirect chains.")
    _bullet_list(
        pdf,
        [f"Redirected to the homepage: {p}" for p in report.homepage_redirects]
        if len(report.homepage_redirects) >= HOMEPAGE_REDIRECT_WARNING_THRESHOLD
        else [],
        "No large group of old URLs redirected to the homepage.",
    )
    _bullet_list(
        pdf,
        [f"Duda can't redirect this source: {p}" for p in report.duda_unsupported_sources],
        "No sources Duda is unable to redirect.",
    )

    return bytes(pdf.output())


def build_link_check_pdf(project_name: str, domain: str, result) -> bytes:
    """Build a PDF listing a site's broken internal links and where each one
    appears, for sharing with whoever will fix them. `result` is a
    linkcheck.LinkCheckResult."""
    from linkcheck import describe_status, is_hard_failure

    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=PAGE_MARGIN)
    pdf.set_margins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 12, "Broken Link Report", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 6, _pdf_safe(f"Project: {project_name or '(untitled)'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _pdf_safe(f"Site: {domain or '(not set)'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Generated: {date.today().isoformat()}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)

    _section_title(pdf, "Summary")
    pdf.set_font("Helvetica", "", 10)
    for line in (
        f"Pages crawled: {result.pages_crawled}",
        f"Links checked: {result.links_checked}",
        f"Broken links (page not found): {result.dead_count}",
        f"Other links that didn't load: {result.other_count}",
    ):
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    def _lines(links) -> list[str]:
        lines = []
        for b in links:
            status = f"HTTP {b.status}" if b.status else "no response"
            line = f"{b.url}  [{status}]"
            if b.linked_from:
                line += "\n    Found on: " + "\n    Found on: ".join(b.linked_from)
            lines.append(line)
        return lines

    dead = [b for b in result.broken if is_hard_failure(b.status)]
    other = [b for b in result.broken if not is_hard_failure(b.status)]

    _section_title(pdf, f"Broken Links ({len(dead)})")
    _bullet_list(pdf, _lines(dead), "No broken links were found.")

    _section_title(pdf, f"Other Links That Didn't Load ({len(other)})")
    if other:
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(
            0,
            5,
            "These returned an error other than 'not found' -- some sites refuse automated "
            "checkers, so check them in a browser before treating them as broken. Reasons: "
            + "; ".join(sorted({describe_status(b.status) for b in other})) + ".",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(1)
    _bullet_list(pdf, _lines(other), "None.")

    if result.warnings or result.truncated:
        _section_title(pdf, "Notes")
        _bullet_list(pdf, list(dict.fromkeys(result.warnings))[:20], "None.")

    return bytes(pdf.output())
