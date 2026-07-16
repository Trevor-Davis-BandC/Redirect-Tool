"""Redirect Tool -- Streamlit UI.

A local tool that compares an old site's sitemap to a new site's sitemap,
suggests redirects, lets a support specialist review/edit them, validates
the list, and exports a Duda-compatible redirect CSV.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from columns import (
    COL_INCLUDE,
    COL_OLD_URL,
    COL_OLD_PATH,
    COL_NEW_URL,
    COL_NEW_PATH,
    COL_REDIRECT_TYPE,
    COL_STATUS,
    COL_NOTES,
    ALL_COLUMNS,
    STATUS_APPROVED,
    STATUS_UNMAPPED,
    ALL_STATUSES,
    REDIRECT_TYPE_PERMANENT,
    REDIRECT_TYPE_TEMPORARY,
    REDIRECT_TYPE_OPTIONS,
)
from sitemap import discover_and_parse_sitemap
from matcher import generate_redirect_suggestions, MATCH_TYPE_NO_MATCH
from url_normalizer import build_normalized_url
from validator import validate_redirects
from exporter import (
    export_default_csv_chunks,
    export_with_template_chunks,
    build_export_filename,
    guess_column_mapping,
    read_template_headers,
)
from report import build_redirect_report_pdf
from config import MAX_REDIRECTS_PER_CSV
from project_storage import (
    build_project_dict,
    save_project_json,
    load_project_json,
    redirect_table_to_dataframe,
    ProjectFileError,
)

st.set_page_config(page_title="Redirect Tool", layout="wide")

PAGE_NEW_PROJECT = "new_project"
PAGE_DISCOVERY = "discovery"
PAGE_REVIEW = "review"
PAGE_EXPORT = "export"

PAGE_ORDER = [PAGE_NEW_PROJECT, PAGE_DISCOVERY, PAGE_REVIEW, PAGE_EXPORT]
PAGE_LABELS = {
    PAGE_NEW_PROJECT: "1. New Project",
    PAGE_DISCOVERY: "2. Sitemap Discovery",
    PAGE_REVIEW: "3. Redirect Review",
    PAGE_EXPORT: "4. Validate & Export",
}


def _default_redirect_type(old_path: str, new_path: str, match_type: str) -> str:
    """301 for confident, real page-to-page matches; 302 for fallback/uncertain ones."""
    old_norm = build_normalized_url(old_path).normalized_path
    new_norm = build_normalized_url(new_path).normalized_path if new_path else ""
    is_homepage_fallback = new_norm == "/" and old_norm != "/"
    if match_type == MATCH_TYPE_NO_MATCH or is_homepage_fallback:
        return REDIRECT_TYPE_TEMPORARY
    return REDIRECT_TYPE_PERMANENT


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def init_session_state() -> None:
    defaults = {
        "page": PAGE_NEW_PROJECT,
        "project_name": "",
        "old_domain": "",
        "new_domain": "",
        "old_sitemap_override": "",
        "new_sitemap_override": "",
        "old_sitemap_result": None,
        "new_sitemap_result": None,
        "redirect_df": None,
        "new_sitemap_paths": set(),
        "export_despite_warnings": False,
        "last_updated_path": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_project() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_session_state()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> None:
    with st.sidebar:
        st.title("Redirect Tool")
        st.caption("Old sitemap -> new sitemap -> Duda redirect CSV")

        st.markdown("### Workflow")
        for page_key in PAGE_ORDER:
            is_current = st.session_state.page == page_key
            label = f"➡️ {PAGE_LABELS[page_key]}" if is_current else PAGE_LABELS[page_key]
            if st.button(
                label,
                key=f"nav_{page_key}",
                use_container_width=True,
                disabled=is_current,
            ):
                st.session_state.page = page_key
                st.rerun()

        st.markdown("---")
        st.markdown("### Project")

        if st.button("Reset Project", use_container_width=True):
            reset_project()
            st.rerun()

        if st.session_state.redirect_df is not None:
            project = build_project_dict(
                project_name=st.session_state.project_name,
                old_domain=st.session_state.old_domain,
                new_domain=st.session_state.new_domain,
                old_sitemap_override=st.session_state.old_sitemap_override,
                new_sitemap_override=st.session_state.new_sitemap_override,
                old_sitemap_url=(st.session_state.old_sitemap_result.sitemap_url or "")
                if st.session_state.old_sitemap_result
                else "",
                new_sitemap_url=(st.session_state.new_sitemap_result.sitemap_url or "")
                if st.session_state.new_sitemap_result
                else "",
                old_urls=st.session_state.old_sitemap_result.urls if st.session_state.old_sitemap_result else [],
                new_urls=st.session_state.new_sitemap_result.urls if st.session_state.new_sitemap_result else [],
                duplicates_removed_old=st.session_state.old_sitemap_result.duplicates_removed
                if st.session_state.old_sitemap_result
                else 0,
                duplicates_removed_new=st.session_state.new_sitemap_result.duplicates_removed
                if st.session_state.new_sitemap_result
                else 0,
                redirect_table=st.session_state.redirect_df,
            )
            st.download_button(
                "Download Project JSON",
                data=save_project_json(project),
                file_name=build_export_filename(st.session_state.project_name, "json"),
                mime="application/json",
                use_container_width=True,
            )

        uploaded_project = st.file_uploader("Upload Project JSON", type=["json"], key="project_uploader")
        if uploaded_project is not None:
            try:
                data = load_project_json(uploaded_project.read())
            except ProjectFileError as exc:
                st.error(str(exc))
            else:
                st.session_state.project_name = data["project_name"]
                st.session_state.old_domain = data["old_domain"]
                st.session_state.new_domain = data["new_domain"]
                st.session_state.old_sitemap_override = data["old_sitemap_override"]
                st.session_state.new_sitemap_override = data["new_sitemap_override"]
                st.session_state.redirect_df = redirect_table_to_dataframe(data["redirect_table"])
                st.session_state.new_sitemap_paths = {
                    build_normalized_url(u).normalized_path for u in data["new_urls"]
                }
                st.session_state.page = PAGE_REVIEW
                st.success(f"Loaded project '{data['project_name']}'.")
                st.rerun()


# ---------------------------------------------------------------------------
# Page 1: New project
# ---------------------------------------------------------------------------

def render_new_project_page() -> None:
    st.header("1. New Project")
    st.write(
        "Enter the old and new website domains. Redirect Tool will look for each site's "
        "XML sitemap automatically, or you can provide a direct sitemap URL."
    )

    with st.form("new_project_form"):
        project_name = st.text_input("Project name", value=st.session_state.project_name)
        old_domain = st.text_input(
            "Old website domain", value=st.session_state.old_domain, placeholder="oldsite.com"
        )
        new_domain = st.text_input(
            "New website domain (or Duda preview-domain URL)",
            value=st.session_state.new_domain,
            placeholder="newsite.com or https://12345.dudapreview.com",
        )

        st.caption(
            "Only fill in the sitemap URL overrides below if the automatic checks above fail to find "
            "a site's sitemap."
        )
        col1, col2 = st.columns(2)
        with col1:
            old_override = st.text_input(
                "Old sitemap URL override (optional)", value=st.session_state.old_sitemap_override
            )
        with col2:
            new_override = st.text_input(
                "New sitemap URL override (optional)", value=st.session_state.new_sitemap_override
            )

        submitted = st.form_submit_button("Find Sitemaps and Compare", type="primary")

    if not submitted:
        return

    errors = []
    if not project_name.strip():
        errors.append("Project name is required.")
    if not old_domain.strip():
        errors.append("The old website domain is required.")
    if not new_domain.strip():
        errors.append("The new website domain is required.")

    if errors:
        for e in errors:
            st.error(e)
        return

    st.session_state.project_name = project_name.strip()
    st.session_state.old_domain = old_domain.strip()
    st.session_state.new_domain = new_domain.strip()
    st.session_state.old_sitemap_override = old_override.strip()
    st.session_state.new_sitemap_override = new_override.strip()

    with st.spinner("Looking for the old site's sitemap..."):
        old_result = discover_and_parse_sitemap(old_domain.strip(), old_override.strip() or None)
    with st.spinner("Looking for the new site's sitemap..."):
        new_result = discover_and_parse_sitemap(new_domain.strip(), new_override.strip() or None)

    st.session_state.old_sitemap_result = old_result
    st.session_state.new_sitemap_result = new_result
    st.session_state.new_sitemap_paths = {
        build_normalized_url(u).normalized_path for u in new_result.urls
    }
    st.session_state.page = PAGE_DISCOVERY
    st.rerun()


# ---------------------------------------------------------------------------
# Page 2: Sitemap discovery results
# ---------------------------------------------------------------------------

def render_discovery_page() -> None:
    st.header("2. Sitemap Discovery Results")

    old_result = st.session_state.old_sitemap_result
    new_result = st.session_state.new_sitemap_result

    if old_result is None or new_result is None:
        st.warning("Start a new project first.")
        if st.button("Go to New Project"):
            st.session_state.page = PAGE_NEW_PROJECT
            st.rerun()
        return

    col1, col2 = st.columns(2)
    for col, label, result in ((col1, "Old website", old_result), (col2, "New website", new_result)):
        with col:
            st.subheader(label)
            if result.sitemap_url:
                st.write(f"**Sitemap found:** {result.sitemap_url}")
            else:
                st.write("**Sitemap found:** none")
            st.metric("Pages found", len(result.urls))
            st.metric("Duplicate URLs removed", result.duplicates_removed)
            if result.errors:
                for err in result.errors:
                    st.error(err)
            if result.warnings:
                for warn in result.warnings:
                    st.warning(warn)

    can_continue = bool(old_result.urls) and bool(new_result.urls)

    if not can_continue:
        st.info(
            "No sitemap could be located automatically for one or both sites. "
            "Go back and enter a sitemap URL manually in the override fields."
        )
        if st.button("Back to New Project"):
            st.session_state.page = PAGE_NEW_PROJECT
            st.rerun()
        return

    st.markdown("---")
    back_col, next_col = st.columns([1, 3])
    with back_col:
        if st.button("Back to New Project"):
            st.session_state.page = PAGE_NEW_PROJECT
            st.rerun()
    with next_col:
        if st.button("Generate Redirect Suggestions", type="primary"):
            with st.spinner("Comparing URLs and generating redirect suggestions..."):
                results = generate_redirect_suggestions(old_result.urls, new_result.urls)

            rows = []
            for r in results:
                best = r.best
                rows.append(
                    {
                        COL_INCLUDE: r.include_default,
                        COL_OLD_URL: r.old_url,
                        COL_OLD_PATH: r.old_path,
                        COL_NEW_URL: best.new_url,
                        COL_NEW_PATH: best.new_path,
                        COL_REDIRECT_TYPE: _default_redirect_type(r.old_path, best.new_path, best.match_type),
                        COL_STATUS: r.status_default,
                        COL_NOTES: "",
                    }
                )

            st.session_state.redirect_df = pd.DataFrame(rows, columns=ALL_COLUMNS)
            st.session_state.page = PAGE_REVIEW
            st.rerun()


# ---------------------------------------------------------------------------
# Page 3: Redirect review
# ---------------------------------------------------------------------------

def render_review_page() -> None:
    st.header("3. Redirect Review")

    df = st.session_state.redirect_df
    if df is None:
        st.warning("Generate redirect suggestions first.")
        if st.button("Go to Sitemap Discovery"):
            st.session_state.page = PAGE_DISCOVERY
            st.rerun()
        return

    if st.session_state.get("last_updated_path"):
        st.success(f"Updated the destination for '{st.session_state.last_updated_path}'.")
        st.session_state.last_updated_path = None

    st.write(
        "Every old URL gets a destination -- pages with no clear match on the new site default to "
        "the homepage (`/`). Edit **Suggested New Path** directly to point somewhere else, uncheck "
        "**Include** to exclude a row, or set **Status** to *Unmapped* for pages you're intentionally "
        "not redirecting. Only the path is ever exported -- the domain shown in *Suggested New URL* "
        "(including any staging/preview domain) is for your reference only."
    )

    status_options = ["All"] + ALL_STATUSES
    status_filter = st.radio("Filter by status", status_options, horizontal=True)

    col_a, col_b = st.columns(2)
    with col_a:
        search_old = st.text_input("Search old URLs contains")
    with col_b:
        search_new = st.text_input("Search new URLs contains")

    display_df = df.copy()

    if status_filter != "All":
        display_df = display_df[display_df[COL_STATUS] == status_filter]

    if search_old.strip():
        display_df = display_df[display_df[COL_OLD_URL].str.contains(search_old.strip(), case=False, na=False)]
    if search_new.strip():
        display_df = display_df[display_df[COL_NEW_URL].str.contains(search_new.strip(), case=False, na=False)]

    st.caption(f"Showing {len(display_df)} of {len(df)} redirects.")

    edited = st.data_editor(
        display_df,
        key="redirect_editor",
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        column_config={
            COL_INCLUDE: st.column_config.CheckboxColumn("Include"),
            COL_OLD_URL: st.column_config.TextColumn("Old URL", disabled=True),
            COL_OLD_PATH: st.column_config.TextColumn("Old Path", disabled=True),
            COL_NEW_URL: st.column_config.TextColumn("Suggested New URL"),
            COL_NEW_PATH: st.column_config.TextColumn("Suggested New Path"),
            COL_REDIRECT_TYPE: st.column_config.SelectboxColumn("Redirect Type", options=REDIRECT_TYPE_OPTIONS),
            COL_STATUS: st.column_config.SelectboxColumn("Status", options=ALL_STATUSES),
            COL_NOTES: st.column_config.TextColumn("Notes"),
        },
    )

    # Merge edits (keyed by Old URL, which is unique per redirect) back into the full dataframe.
    if not edited.equals(display_df):
        full_df = st.session_state.redirect_df.set_index(COL_OLD_URL, drop=False)
        edited_indexed = edited.set_index(COL_OLD_URL, drop=False)
        for old_url, edited_row in edited_indexed.iterrows():
            full_df.loc[old_url] = edited_row
        st.session_state.redirect_df = full_df.reset_index(drop=True)
        df = st.session_state.redirect_df

    st.markdown("---")
    st.subheader("Change a specific redirect's destination")
    st.caption(
        "You can also edit the Suggested New Path cell directly in the table above -- use this if that's "
        "easier, e.g. for pointing a page somewhere other than the suggestion or the homepage fallback."
    )
    old_paths = list(df[COL_OLD_PATH])
    if old_paths:
        pick_col, dest_col, button_col = st.columns([2, 2, 1])
        with pick_col:
            selected_path = st.selectbox("Old path", old_paths, key="change_dest_old_path")
        current_dest = df.loc[df[COL_OLD_PATH] == selected_path, COL_NEW_PATH].iloc[0]
        with dest_col:
            new_dest = st.text_input("New destination path", value=current_dest, key="change_dest_new_path")
        with button_col:
            st.write("")
            st.write("")
            update_clicked = st.button("Update")
        if update_clicked and new_dest.strip():
            idx = df.index[df[COL_OLD_PATH] == selected_path][0]
            st.session_state.redirect_df.loc[idx, COL_NEW_PATH] = new_dest.strip()
            st.session_state.redirect_df.loc[idx, COL_NEW_URL] = ""
            st.session_state.redirect_df.loc[idx, COL_REDIRECT_TYPE] = _default_redirect_type(
                selected_path, new_dest.strip(), "Manual / Custom"
            )
            st.session_state.redirect_df.loc[idx, COL_STATUS] = STATUS_APPROVED
            st.session_state.redirect_df.loc[idx, COL_INCLUDE] = True
            st.session_state.last_updated_path = selected_path
            st.rerun()

    st.markdown("---")
    back_col, next_col = st.columns([1, 3])
    with back_col:
        if st.button("Back to Sitemap Discovery"):
            st.session_state.page = PAGE_DISCOVERY
            st.rerun()
    with next_col:
        if st.button("Continue to Validation and Export", type="primary"):
            st.session_state.page = PAGE_EXPORT
            st.rerun()


# ---------------------------------------------------------------------------
# Page 4: Validation and export
# ---------------------------------------------------------------------------

def render_export_page() -> None:
    st.header("4. Validate & Export")

    df = st.session_state.redirect_df
    if df is None:
        st.warning("Generate redirect suggestions first.")
        if st.button("Go to Sitemap Discovery"):
            st.session_state.page = PAGE_DISCOVERY
            st.rerun()
        return

    if st.button("Back to Redirect Review"):
        st.session_state.page = PAGE_REVIEW
        st.rerun()

    report = validate_redirects(df, st.session_state.new_domain, st.session_state.new_sitemap_paths)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total old URLs", report.total_old_urls)
    col2.metric("Included redirects", report.total_included)
    col3.metric("Excluded URLs", report.total_excluded)
    col4.metric("Unmapped URLs", report.total_unmapped)

    def _list_section(title: str, items: list, empty_text: str = "None found.") -> None:
        with st.expander(f"{title} ({len(items)})", expanded=bool(items)):
            if not items:
                st.write(empty_text)
            else:
                for item in items:
                    st.write(f"- {item}")

    _list_section("Duplicate source paths", report.duplicate_source_paths)
    _list_section(
        "Duplicate redirect rules",
        [f"{s} -> {d}" for s, d in report.duplicate_redirect_rules],
    )
    _list_section("Blank or missing destinations", report.blank_or_malformed)

    st.markdown("---")
    st.subheader("Redirect Report")
    st.write(
        "A summary PDF listing every old URL, what it matched or was suggested, what was removed or "
        "left unmapped, and any validation issues -- useful to keep on file or share with the team."
    )
    report_pdf_bytes = build_redirect_report_pdf(
        st.session_state.project_name,
        st.session_state.old_domain,
        st.session_state.new_domain,
        df,
        report,
    )
    st.download_button(
        "Download Redirect Report (PDF)",
        data=report_pdf_bytes,
        file_name=build_export_filename(st.session_state.project_name, "pdf"),
        mime="application/pdf",
    )

    st.markdown("---")

    if report.has_critical_errors:
        st.error(
            f"{len(report.critical_errors)} critical issue(s) must be resolved before exporting:"
        )
        for e in report.critical_errors:
            st.write(f"- {e}")
        export_anyway = st.checkbox("Export despite warnings", value=st.session_state.export_despite_warnings)
        st.session_state.export_despite_warnings = export_anyway
    else:
        export_anyway = True
        if report.warnings:
            st.warning(f"{len(report.warnings)} warning(s) found. Review them above before exporting.")
        else:
            st.success("No validation issues found.")

    can_export = (not report.has_critical_errors) or export_anyway

    st.markdown("---")
    st.subheader("Export")

    template_file = st.file_uploader("Optional: upload a Duda CSV template", type=["csv"])

    csv_chunks = None

    if template_file is not None:
        try:
            headers, template_df = read_template_headers(template_file)
        except Exception as exc:  # malformed upload -- show a friendly message, not a traceback
            st.error(f"Could not read the uploaded template: {exc}")
        else:
            guess = guess_column_mapping(headers)
            st.write("Map your template's columns:")
            m1, m2, m3 = st.columns(3)
            with m1:
                source_col = st.selectbox(
                    "Source/old URL column", headers, index=headers.index(guess["source"]) if guess["source"] in headers else 0
                )
            with m2:
                dest_col = st.selectbox(
                    "Destination/new URL column",
                    headers,
                    index=headers.index(guess["destination"]) if guess["destination"] in headers else min(1, len(headers) - 1),
                )
            with m3:
                type_options = ["(none)"] + headers
                type_default = guess["redirect_type"] if guess["redirect_type"] in headers else "(none)"
                type_col_choice = st.selectbox(
                    "Redirect type column (optional)", type_options, index=type_options.index(type_default)
                )
            redirect_type_col = None if type_col_choice == "(none)" else type_col_choice

            exclude_cols = {source_col, dest_col} | ({redirect_type_col} if redirect_type_col else set())
            default_values = {}
            if len(template_df) > 0:
                first_row = template_df.iloc[0].to_dict()
                default_values = {k: v for k, v in first_row.items() if k not in exclude_cols}

            if can_export:
                csv_chunks = export_with_template_chunks(
                    df, headers, source_col, dest_col, redirect_type_col, default_values
                )
    else:
        if can_export:
            csv_chunks = export_default_csv_chunks(df)

    if not can_export:
        st.button("Download Duda Redirect CSV", disabled=True)
        st.caption("Resolve critical issues, or check 'Export despite warnings', to enable download.")
    elif csv_chunks is not None:
        total_parts = len(csv_chunks)
        if total_parts > 1:
            st.info(
                f"Duda accepts up to {MAX_REDIRECTS_PER_CSV} redirects per CSV import, so this export "
                f"is split into {total_parts} files -- import each one separately."
            )
        for i, csv_text in enumerate(csv_chunks, start=1):
            label = "Download Duda Redirect CSV" if total_parts == 1 else f"Download Duda Redirect CSV -- Part {i} of {total_parts}"
            filename = build_export_filename(
                st.session_state.project_name,
                part=i if total_parts > 1 else None,
                total_parts=total_parts if total_parts > 1 else None,
            )
            st.download_button(
                label,
                data=csv_text.encode("utf-8"),
                file_name=filename,
                mime="text/csv",
                type="primary",
                key=f"csv_download_{i}",
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    init_session_state()
    render_sidebar()

    page = st.session_state.page
    if page == PAGE_NEW_PROJECT:
        render_new_project_page()
    elif page == PAGE_DISCOVERY:
        render_discovery_page()
    elif page == PAGE_REVIEW:
        render_review_page()
    elif page == PAGE_EXPORT:
        render_export_page()
    else:
        st.session_state.page = PAGE_NEW_PROJECT
        render_new_project_page()


if __name__ == "__main__":
    main()
