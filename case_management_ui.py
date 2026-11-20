"""Streamlit navigation, case controls, and persistence checkpoints."""

from copy import deepcopy
import json
import sqlite3
from uuid import uuid4

import streamlit as st

from case_history_ui import render_case_history
from case_repository import CaseConflictError, CaseRepository, CaseStatus
from case_serialization import encode_state
from investigation_state import Investigation


WIZARD = "Investigation Wizard"
MANAGEMENT = "Case Management"
_VIEW_KEY = "case_workspace_view"
_EDITABLE = {CaseStatus.DRAFT, CaseStatus.IN_PROGRESS}
_ACTIONS = {
    CaseStatus.DRAFT: (),
    CaseStatus.IN_PROGRESS: (
        ("On Hold", CaseStatus.ON_HOLD),
        ("Close Resolved", CaseStatus.CLOSED_RESOLVED),
        ("Close Inconclusive", CaseStatus.CLOSED_INCONCLUSIVE),
    ),
    CaseStatus.ON_HOLD: (("Resume", CaseStatus.IN_PROGRESS),),
    CaseStatus.CLOSED_RESOLVED: (("Reopen", CaseStatus.IN_PROGRESS),),
    CaseStatus.CLOSED_INCONCLUSIVE: (("Reopen", CaseStatus.IN_PROGRESS),),
    CaseStatus.ARCHIVED: (("Restore", None),),
}


def navigation_view():
    view = st.session_state.setdefault(_VIEW_KEY, WIZARD)
    with st.container(key="edr_operations"):
        st.markdown("#### Operations")
        for label, key, icon in (
            (WIZARD, "nav_wizard", ":material/troubleshoot:"),
            (MANAGEMENT, "nav_management", ":material/folder_open:"),
        ):
            active = view == label
            st.button(
                label, key=key, icon=":material/check:" if active else icon,
                type="primary" if active else "secondary", width="stretch",
                help="Current view" if active else None, on_click=_set_view, args=(label,),
            )
    return view


def _set_view(view):
    st.session_state[_VIEW_KEY] = view


def wizard_key(key):
    namespace = st.session_state.get("case_widget_namespace")
    return f"case_{namespace}_{key}" if namespace else key


def _checkpoint_state(investigation):
    data = encode_state(investigation)
    # Typing a draft is saved explicitly or with the next committed checkpoint.
    data.pop("manual_draft")
    return json.dumps(data, sort_keys=True)


class CaseWorkspace:
    def __init__(self):
        self.repository = CaseRepository()
        self.error = None
        self.available = True
        if self.repository.path.exists():
            try:
                if st.session_state.get("case_db_initialized") != self.repository.path:
                    self.repository.initialize()
                    st.session_state.case_db_initialized = self.repository.path
            except (OSError, sqlite3.Error, ValueError):
                self.available = False
                self.error = "Case storage is unavailable. Check the configured database path and permissions."

    @property
    def active(self):
        return st.session_state.get("case_metadata")

    @property
    def editable(self):
        return self.active is None or (self.active.status in _EDITABLE and not self.conflicted)

    @property
    def conflicted(self):
        return st.session_state.get("case_conflict", False)

    def save_status(self, investigation):
        if self.conflicted:
            return "Save conflict", "red"
        if self.active is None:
            return "Unsaved session", "gray"
        if self.editable and (
            investigation.manual_draft != st.session_state.get("case_saved_draft", investigation.manual_draft)
            or st.session_state.get("case_unsaved_checkpoint", False)
        ):
            return "Unsaved changes", "orange"
        return "Saved", "green"

    @property
    def database_status(self):
        if not self.available:
            return "Unavailable", "red"
        if st.session_state.get("case_db_initialized") == self.repository.path and self.repository.path.is_file():
            return "Available", "green"
        return "Not initialized", "gray"

    def _activate(self, saved, *, open_wizard=False):
        old_namespace = st.session_state.get("case_widget_namespace")
        if old_namespace:
            for key in list(st.session_state):
                if key.startswith(f"case_{old_namespace}_"):
                    del st.session_state[key]
        st.session_state.case_widget_namespace = uuid4().hex
        st.session_state.investigation = saved.investigation
        st.session_state.case_metadata = saved.metadata
        st.session_state.case_checkpoint = _checkpoint_state(saved.investigation)
        st.session_state.case_saved_draft = saved.investigation.manual_draft
        st.session_state.case_unsaved_checkpoint = False
        st.session_state.case_conflict = False
        if open_wizard:
            _set_view(WIZARD)
        st.rerun()

    def checkpoint(self, investigation, *, explicit=False, submit=False):
        if self.active is None:
            return True
        if not self.editable:
            return False
        state = _checkpoint_state(investigation)
        pending = state != st.session_state.case_checkpoint
        st.session_state.case_unsaved_checkpoint = pending
        if not self.available:
            return False
        if not (explicit or submit or pending):
            return True
        try:
            if submit and self.active.status == CaseStatus.DRAFT:
                saved = self.repository.transition(
                    self.active.case_id, self.active.version, CaseStatus.IN_PROGRESS,
                    investigation=investigation,
                )
            else:
                saved = self.repository.save(self.active.case_id, self.active.version, investigation)
        except CaseConflictError:
            st.session_state.case_conflict = True
            st.rerun()
        except (OSError, sqlite3.Error, ValueError, KeyError):
            self.error = "Could not save this case. Your changes are still in this session."
            return False
        # Keep the live object so transient errors, uploads, and current consent survive ordinary saves.
        st.session_state.case_metadata = saved.metadata
        st.session_state.case_checkpoint = state
        st.session_state.case_saved_draft = saved.investigation.manual_draft
        st.session_state.case_unsaved_checkpoint = False
        return True

    def check_gemini_version(self):
        current = self.active
        if current is not None:
            if not self.available:
                raise RuntimeError("Case storage is unavailable. No data was sent to Google Gemini.")
            try:
                self.repository.require_current_version(current.case_id, current.version)
            except CaseConflictError:
                st.session_state.case_conflict = True
                st.rerun()

    def save_gemini_result(self, investigation, apply_result):
        if self.active is not None:
            candidate = deepcopy(investigation)
            apply_result(candidate)
            if not self.checkpoint(candidate, explicit=True):
                self.error = "Could not save the Google Gemini response. The response was discarded."
                return
        apply_result(investigation)
        st.rerun()

    def _transition(self, label, target, rationale, investigation):
        if label in {"On Hold", "Close Resolved", "Close Inconclusive", "Reopen"} and not rationale.strip():
            self.error = "Enter a reason for the status change."
            return
        if self.active.status in _EDITABLE and not self.checkpoint(investigation, explicit=True):
            return
        current = self.active
        try:
            if target is None:
                target = self.repository.history(current.case_id)[current.version - 2].status
            saved = self.repository.transition(current.case_id, current.version, target, rationale=rationale)
        except CaseConflictError:
            st.session_state.case_conflict = True
            st.rerun()
        except (OSError, sqlite3.Error, ValueError, KeyError):
            self.error = "Could not change the case status. Open the latest saved case and retry."
        else:
            self._activate(saved)

    def _show_messages(self):
        if self.conflicted:
            st.error("Another session changed this case. Your changes were not saved. Use Open Case in Case Management to load the latest version and replace your local edits.")
        if self.error:
            st.error(self.error)

    def render_wizard_header(self, investigation):
        current = self.active
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            if current:
                st.text(f"{current.title} · {current.status.value} · Version {current.version}")
                if st.button("Save Case", key="case_save", disabled=not self.editable or not self.available):
                    if self.checkpoint(investigation, explicit=True):
                        st.session_state.case_saved_version = self.active.version
                        st.rerun()
            else:
                st.caption("No saved case open")
            st.button(MANAGEMENT, key="wizard_case_management", on_click=_set_view, args=(MANAGEMENT,))
        if (version := st.session_state.pop("case_saved_version", None)) is not None:
            st.toast(f"Saved version {version}.")
        self._show_messages()

    def render_management(self, investigation):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.header(MANAGEMENT)
            st.button("Back to Investigation Wizard", icon=":material/arrow_back:", key="management_back",
                      on_click=_set_view, args=(WIZARD,))
        if self.available:
            selected = self._render_case_list()
            if self.active is not None:
                self._render_lifecycle(investigation)
            audit_case_id = selected or (self.active.case_id if self.active is not None else None)
            if self.available and audit_case_id is not None:
                render_case_history(self.repository, audit_case_id)
        self._show_messages()

    def _render_case_list(self):
        try:
            exists = self.repository.path.exists()
            active = self.repository.list_cases() if exists else []
            archived = self.repository.list_cases(archived=True) if exists else []
        except (OSError, sqlite3.Error, ValueError):
            self.error = "Could not read the case list."
            self.available = False
            active, archived = [], []
        with st.container(horizontal=True, gap="large"):
            st.metric("Total cases", len(active) + len(archived))
            st.metric("Active cases", len(active))
            st.metric("Archived cases", len(archived))

        search_col, status_col = st.columns([2, 1])
        search = search_col.text_input("Search by case title or ID", key="case_search").strip().casefold()
        status = status_col.selectbox(
            "Status filter", ["Active cases", "All statuses", *(state.value for state in CaseStatus)],
            key="case_status_filter",
        )
        rows = active if status == "Active cases" else sorted(
            (*active, *archived), key=lambda row: (row.saved_at, row.case_id), reverse=True,
        )
        if status not in {"Active cases", "All statuses"}:
            rows = [row for row in rows if row.status.value == status]
        rows = [row for row in rows if search in row.title.casefold() or search in row.case_id.casefold()]
        if rows:
            st.dataframe([
                {"Case ID": row.case_id, "Title": row.title, "Status": row.status.value, "Last update (UTC)": row.saved_at}
                for row in rows
            ], hide_index=True)
        else:
            st.caption("No cases match the selected filters.")
        titles = {row.case_id: row.title for row in rows}
        picker, opener = st.columns([3, 1], vertical_alignment="bottom")
        selected = picker.selectbox(
            "Saved case", list(titles), index=None, key="case_selected",
            format_func=lambda case_id: f"{titles[case_id]} · {case_id}",
        )
        if opener.button("Open Case", key="case_open", disabled=selected is None):
            try:
                self._activate(self.repository.load(selected), open_wizard=True)
            except (OSError, sqlite3.Error, ValueError, KeyError):
                self.error = "Could not open the selected case."

        title_col, new_col = st.columns([3, 1], vertical_alignment="bottom")
        title = title_col.text_input("New case title", key=wizard_key("new_case_title"))
        if new_col.button("New Case", key="case_new", disabled=not title.strip()):
            try:
                self.repository.initialize()
                st.session_state.case_db_initialized = self.repository.path
                self._activate(self.repository.create(title, Investigation()), open_wizard=True)
            except (OSError, sqlite3.Error, ValueError):
                self.error = "Could not create the case. Check the configured database path and permissions."
        return selected

    def _render_lifecycle(self, investigation):
        current = self.active
        st.subheader("Active case actions")
        st.text(f"{current.title} · {current.status.value} · Version {current.version}")
        actions = _ACTIONS[current.status]
        if current.status != CaseStatus.ARCHIVED:
            actions = (*actions, ("Archive", CaseStatus.ARCHIVED))
        rationale = ""
        if current.status in {CaseStatus.IN_PROGRESS, CaseStatus.CLOSED_RESOLVED, CaseStatus.CLOSED_INCONCLUSIVE}:
            rationale = st.text_input("Status change reason", key=wizard_key("status_reason"), disabled=self.conflicted)
        with st.container(horizontal=True):
            for label, target in actions:
                if st.button(label, key=f"case_action_{label}", disabled=self.conflicted):
                    self._transition(label, target, rationale, investigation)
