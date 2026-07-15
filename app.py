"""Migration Mapper -- Streamlit UI.

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
    COL_CONFIDENCE,
    COL_MATCH_TYPE,
    COL_STATUS,
    COL_NOTES,
    ALL_COLUMNS,
    STATUS_APPROVED,
    STATUS_NEEDS_REVIEW,
    STATUS_EXCLUDED,
    STATUS_UNMAPPED,
    ALL_STATUSES,
)
from sitemap import discover_and_parse_sitemap
from matcher import generate_redirect_suggestions, MATCH_TYPE_NO_MATCH
from url_normalizer import build_normalized_url
from validator import validate_redirects
from exporter import (
    export_default_csv,
    export_with_template,
    build_export_filename,
    guess_column_mapping,
    read_template_headers,
)
from project_storage import (
    build_project_dict,
    save_project_json,
    load_project_json,
    redirect_table_to_dataframe,
    ProjectFileError,
)

st.set_page_config(page_title="Migration Mapper", layout="wide")

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


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def init_session_state() -> None:
    defaults = {
        "page": PAGE_NEW_PROJECT,
        "project_name": "",
        "old_domain": "",
        "new_domain": "",
        "production_domain": "",
        "old_sitemap_override": "",
        "new_sitemap_override": "",
        "old_sitemap_result": None,
        "new_sitemap_result": None,
        "redirect_df": None,
        "new_sitemap_paths": set(),
        "alternatives_by_old_path": {},
        "explanations_by_old_path": {},
        "export_despite_warnings": False,
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
        st.title("Migration Mapper")
        st.caption("Old sitemap -> new sitemap -> Duda redirect CSV")

        st.markdown("### Workflow")
        for page_key in PAGE_ORDER:
            marker = "➡️ " if st.session_state.page == page_key else "　"
            st.write(f"{marker}{PAGE_LABELS[page_key]}")

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
                production_domain=st.session_state.production_domain,
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
                st.session_state.production_domain = data["production_domain"]
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
        "Enter the old and new website domains. Migration Mapper will look for each site's "
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
        production_domain = st.text_input(
            "Final production domain (optional)",
            value=st.session_state.production_domain,
            placeholder="Used only for reference; leave blank if unsure",
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
    st.session_state.production_domain = production_domain.strip()
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
    if st.button("Generate Redirect Suggestions", type="primary"):
        with st.spinner("Comparing URLs and generating redirect suggestions..."):
            results = generate_redirect_suggestions(old_result.urls, new_result.urls)

        rows = []
        alternatives_by_old_path = {}
        explanations_by_old_path = {}
        for r in results:
            best = r.best
            rows.append(
                {
                    COL_INCLUDE: r.include_default,
                    COL_OLD_URL: r.old_url,
                    COL_OLD_PATH: r.old_path,
                    COL_NEW_URL: best.new_url if best else "",
                    COL_NEW_PATH: best.new_path if best else "",
                    COL_CONFIDENCE: best.confidence if best else 0.0,
                    COL_MATCH_TYPE: best.match_type if best else MATCH_TYPE_NO_MATCH,
                    COL_STATUS: r.status_default,
                    COL_NOTES: "",
                }
            )
            alternatives_by_old_path[r.old_path] = [
                {"new_url": a.new_url, "new_path": a.new_path, "confidence": a.confidence, "match_type": a.match_type}
                for a in r.alternatives
            ]
            explanations_by_old_path[r.old_path] = r.explanation

        st.session_state.redirect_df = pd.DataFrame(rows, columns=ALL_COLUMNS)
        st.session_state.alternatives_by_old_path = alternatives_by_old_path
        st.session_state.explanations_by_old_path = explanations_by_old_path
        st.session_state.page = PAGE_REVIEW
        st.rerun()


# ---------------------------------------------------------------------------
# Page 3: Redirect review
# ---------------------------------------------------------------------------

def _confidence_bucket(row: pd.Series) -> str:
    match_type = row[COL_MATCH_TYPE]
    confidence = row[COL_CONFIDENCE]
    status = row[COL_STATUS]
    if status == STATUS_EXCLUDED:
        return "Excluded"
    if match_type == MATCH_TYPE_NO_MATCH or confidence < 60:
        return "No Match"
    if confidence >= 95:
        return "Exact Matches"
    if confidence >= 80:
        return "Strong Suggestions"
    return "Needs Review"


def render_review_page() -> None:
    st.header("3. Redirect Review")

    df = st.session_state.redirect_df
    if df is None:
        st.warning("Generate redirect suggestions first.")
        if st.button("Go to Sitemap Discovery"):
            st.session_state.page = PAGE_DISCOVERY
            st.rerun()
        return

    st.write(
        "Review each suggested redirect. Uncheck **Include** to exclude a row, or set **Status** to "
        "*Unmapped* for pages you're intentionally not redirecting. Edit **Suggested New Path** to "
        "point somewhere else."
    )

    filter_options = ["All", "Exact Matches", "Strong Suggestions", "Needs Review", "No Match", "Excluded"]
    status_filter = st.radio("Filter by category", filter_options, horizontal=True)

    col_a, col_b, col_c = st.columns([1, 1, 1])
    with col_a:
        conf_range = st.slider("Confidence range", 0, 100, (0, 100))
    with col_b:
        search_old = st.text_input("Search old URLs contains")
    with col_c:
        search_new = st.text_input("Search new URLs contains")

    sort_desc = st.checkbox("Sort by confidence (highest first)", value=True)

    display_df = df.copy()
    display_df["_bucket"] = display_df.apply(_confidence_bucket, axis=1)

    if status_filter != "All":
        display_df = display_df[display_df["_bucket"] == status_filter]

    display_df = display_df[
        (display_df[COL_CONFIDENCE] >= conf_range[0]) & (display_df[COL_CONFIDENCE] <= conf_range[1])
    ]

    if search_old.strip():
        display_df = display_df[display_df[COL_OLD_URL].str.contains(search_old.strip(), case=False, na=False)]
    if search_new.strip():
        display_df = display_df[display_df[COL_NEW_URL].str.contains(search_new.strip(), case=False, na=False)]

    display_df = display_df.sort_values(COL_CONFIDENCE, ascending=not sort_desc)
    display_df = display_df.drop(columns=["_bucket"])

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
            COL_CONFIDENCE: st.column_config.NumberColumn("Confidence Score", disabled=True, format="%.1f"),
            COL_MATCH_TYPE: st.column_config.TextColumn("Match Type", disabled=True),
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
    st.subheader("Inspect a redirect / view alternative matches")

    old_paths = list(df[COL_OLD_PATH])
    if old_paths:
        selected_path = st.selectbox("Old path", old_paths)
        current_row = df[df[COL_OLD_PATH] == selected_path].iloc[0]
        explanation = st.session_state.explanations_by_old_path.get(selected_path, "")
        st.write(f"**Current suggestion:** {current_row[COL_NEW_PATH] or '(none)'}")
        st.write(f"**Why this match was chosen:** {explanation}")

        alternatives = st.session_state.alternatives_by_old_path.get(selected_path, [])
        if alternatives:
            st.write("**Alternative destinations found on the new site:**")
            for i, alt in enumerate(alternatives):
                alt_col1, alt_col2 = st.columns([4, 1])
                with alt_col1:
                    st.write(f"{alt['new_path']} — {alt['confidence']}% ({alt['match_type']})")
                with alt_col2:
                    if st.button("Use this", key=f"use_alt_{i}_{selected_path}"):
                        idx = df.index[df[COL_OLD_PATH] == selected_path][0]
                        st.session_state.redirect_df.loc[idx, COL_NEW_URL] = alt["new_url"]
                        st.session_state.redirect_df.loc[idx, COL_NEW_PATH] = alt["new_path"]
                        st.session_state.redirect_df.loc[idx, COL_CONFIDENCE] = alt["confidence"]
                        st.session_state.redirect_df.loc[idx, COL_MATCH_TYPE] = alt["match_type"]
                        st.session_state.redirect_df.loc[idx, COL_STATUS] = STATUS_NEEDS_REVIEW
                        st.session_state.redirect_df.loc[idx, COL_INCLUDE] = True
                        st.rerun()
        else:
            st.caption("No alternative matches were found for this URL.")

        with st.form("custom_destination_form"):
            custom_dest = st.text_input("Enter a custom destination path")
            custom_submit = st.form_submit_button("Set custom destination")
        if custom_submit and custom_dest.strip():
            idx = df.index[df[COL_OLD_PATH] == selected_path][0]
            st.session_state.redirect_df.loc[idx, COL_NEW_URL] = ""
            st.session_state.redirect_df.loc[idx, COL_NEW_PATH] = custom_dest.strip()
            st.session_state.redirect_df.loc[idx, COL_MATCH_TYPE] = "Manual / Custom"
            st.session_state.redirect_df.loc[idx, COL_CONFIDENCE] = 100.0
            st.session_state.redirect_df.loc[idx, COL_STATUS] = STATUS_APPROVED
            st.session_state.redirect_df.loc[idx, COL_INCLUDE] = True
            st.rerun()

    st.markdown("---")
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
    _list_section(
        "Missing destination URLs (not found in new sitemap)",
        [f"{s} -> {d}" for s, d in report.missing_destinations],
    )
    _list_section("Possible redirect loops", [" -> ".join(chain) for chain in report.redirect_loops])
    _list_section(
        "Redirect chains",
        [f"{a} -> {b} -> {c}" for a, b, c in report.redirect_chains],
    )
    _list_section("Self-redirects", report.self_redirects)
    _list_section(
        "External destination URLs",
        [f"{s} -> {d}" for s, d in report.external_destinations],
    )
    _list_section("Homepage fallback redirects", report.homepage_fallbacks)
    _list_section(
        "Destinations used unusually often",
        [f"{d} ({c} times)" for d, c in report.overused_destinations],
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

    csv_text = None
    filename = build_export_filename(st.session_state.project_name)

    if template_file is not None:
        try:
            headers, template_df = read_template_headers(template_file)
        except Exception as exc:  # malformed upload -- show a friendly message, not a traceback
            st.error(f"Could not read the uploaded template: {exc}")
        else:
            guess = guess_column_mapping(headers)
            st.write("Map your template's columns:")
            m1, m2 = st.columns(2)
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

            default_values = {}
            if len(template_df) > 0:
                first_row = template_df.iloc[0].to_dict()
                default_values = {k: v for k, v in first_row.items() if k not in (source_col, dest_col)}

            if can_export:
                csv_text = export_with_template(df, headers, source_col, dest_col, default_values)
    else:
        if can_export:
            csv_text = export_default_csv(df)

    if not can_export:
        st.button("Download Duda Redirect CSV", disabled=True)
        st.caption("Resolve critical issues, or check 'Export despite warnings', to enable download.")
    elif csv_text is not None:
        st.download_button(
            "Download Duda Redirect CSV",
            data=csv_text.encode("utf-8"),
            file_name=filename,
            mime="text/csv",
            type="primary",
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
