"""Exercise the case controls through the existing Streamlit entry point."""

import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
import streamlit as st
from streamlit.testing.v1 import AppTest

from case_management_ui import MANAGEMENT, WIZARD
from case_repository import CaseRepository, CaseStatus, IncidentVerdict
from investigation_state import LAB, MANUAL, Evidence, Investigation, Ticket
from test_case_repository import PNG


APP = Path(__file__).with_name("dashboard_v1_2.py")


class CaseManagementUITest(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / "cases.sqlite3"
        self.enterContext(patch.dict(os.environ, {"EDR_CASE_DB_PATH": str(self.path)}))
        self.repository = CaseRepository(self.path)
        self.repository.initialize()

    def run_app(self, app):
        app.run(timeout=15)
        self.assertFalse(app.exception, list(app.exception))
        return app

    def start(self):
        return self.run_app(AppTest.from_file(str(APP)))

    def click(self, app, key):
        app.button(key=key).click()
        self.run_app(app)

    def widget(self, app, widget_type, suffix):
        widgets = getattr(app, widget_type)
        return next(widget for widget in widgets if widget.key and widget.key.endswith(suffix))

    def open_case(self, app, case_id):
        self.go_to(app, MANAGEMENT)
        app.selectbox(key="case_selected").select(case_id)
        self.run_app(app)
        self.click(app, "case_open")
        self.assertEqual(WIZARD, app.session_state["case_workspace_view"])

    def go_to(self, app, view):
        if app.session_state["case_workspace_view"] != view:
            key = "nav_wizard" if view == WIZARD else "nav_management"
            app.sidebar.button(key=key).click()
            self.run_app(app)

    def test_compatible_sidebar_renders_on_startup_and_for_saved_case(self):
        app = self.start()
        self.assertEqual("primary", app.sidebar.button(key="nav_wizard").proto.type)
        badges = [item.value for item in app.sidebar.markdown]
        self.assertIn(":gray-badge[Unsaved session]", badges)
        self.assertIn(":green-badge[Case database · Available]", badges)
        case = self.repository.create("Compatibility check")
        self.open_case(app, case.metadata.case_id)
        badges = [item.value for item in app.sidebar.markdown]
        self.assertIn(":blue-badge[Draft]", badges)
        self.assertIn(":green-badge[Saved]", badges)
        self.assertEqual(case.metadata, self.repository.load(case.metadata.case_id).metadata)

    def test_new_save_and_open_restores_wizard_progress_without_rerun_versions(self):
        app = self.start()
        self.assertEqual(WIZARD, app.session_state["case_workspace_view"])
        self.assertEqual("primary", app.sidebar.button(key="nav_wizard").proto.type)
        self.assertFalse(app.dataframe)
        self.click(app, "wizard_case_management")
        self.assertEqual(MANAGEMENT, app.session_state["case_workspace_view"])
        self.assertEqual("primary", app.sidebar.button(key="nav_management").proto.type)
        self.widget(app, "text_input", "new_case_title").set_value("Offline workstation")
        self.run_app(app)
        self.click(app, "case_new")
        case = self.repository.list_cases()[0]
        self.assertEqual(CaseStatus.DRAFT, case.status)
        self.assertEqual(WIZARD, app.session_state["case_workspace_view"])
        self.assertTrue(any("Offline workstation · DRAFT · Version 1" in item.value for item in app.text))

        self.widget(app, "text_area", "ticket_description").set_value("A unique offline workstation")
        self.run_app(app)
        self.assertEqual(1, self.repository.load(case.case_id).metadata.version)
        self.click(app, "case_save")
        self.assertEqual("A unique offline workstation", self.repository.load(case.case_id).investigation.manual_draft.description)
        self.click(app, "wizard_next")
        submitted = self.repository.load(case.case_id)
        self.assertEqual(3, submitted.metadata.version)
        self.assertEqual(CaseStatus.IN_PROGRESS, submitted.metadata.status)
        self.assertEqual(1, submitted.investigation.step)
        self.click(app, "local_analysis_button")
        self.click(app, "wizard_next")
        saved = self.repository.load(case.case_id)
        self.assertEqual(2, saved.investigation.step)
        self.assertIn("triage", saved.investigation.results)

        fresh = self.start()
        self.open_case(fresh, case.case_id)
        self.assertEqual(2, fresh.session_state["investigation"].step)
        self.assertIn("triage", fresh.session_state["investigation"].results)
        self.run_app(fresh)
        self.click(fresh, "case_save")
        self.assertEqual(saved.metadata, self.repository.load(case.case_id).metadata)

    def test_lifecycle_actions_and_archive_filter(self):
        case = self.repository.create("Lifecycle")
        case_id = case.metadata.case_id
        app = self.start()
        self.open_case(app, case_id)
        self.click(app, "wizard_next")
        self.go_to(app, MANAGEMENT)
        self.click(app, "case_action_On Hold")
        self.assertTrue(any("Enter a reason" in item.value for item in app.error))
        for label, status in (
            ("On Hold", CaseStatus.ON_HOLD), ("Resume", CaseStatus.IN_PROGRESS),
            ("Close Inconclusive", CaseStatus.CLOSED_INCONCLUSIVE), ("Reopen", CaseStatus.IN_PROGRESS),
            ("Close Resolved", CaseStatus.CLOSED_RESOLVED), ("Reopen", CaseStatus.IN_PROGRESS),
            ("Archive", CaseStatus.ARCHIVED),
        ):
            with self.subTest(action=label):
                if label not in {"Resume", "Archive"}:
                    self.widget(app, "text_input", "status_reason").set_value("Analyst decision")
                self.click(app, f"case_action_{label}")
                current = self.repository.load(case_id)
                self.assertEqual(status, current.metadata.status)
                self.assertEqual(IncidentVerdict.NOT_ASSESSED, current.metadata.incident_verdict)
                if status in {CaseStatus.ON_HOLD, CaseStatus.CLOSED_INCONCLUSIVE, CaseStatus.CLOSED_RESOLVED}:
                    self.go_to(app, WIZARD)
                    self.assertNotIn("local_analysis_button", [button.key for button in app.button])
                    self.assertTrue(app.button(key="case_save").disabled)
                    self.go_to(app, MANAGEMENT)
        self.assertFalse(any("Case ID" in item.value for item in app.dataframe))
        app.selectbox(key="case_status_filter").select("ARCHIVED")
        self.run_app(app)
        self.assertEqual(case_id, app.dataframe[0].value.iloc[0]["Case ID"])
        self.assertEqual("ARCHIVED", app.dataframe[0].value.iloc[0]["Status"])
        self.click(app, "case_action_Restore")
        self.assertEqual(CaseStatus.IN_PROGRESS, self.repository.load(case_id).metadata.status)

    def test_search_filter_and_summary_counts(self):
        draft = self.repository.create("Offline workstation")
        archived = self.repository.create("Archive example")
        self.repository.transition(archived.metadata.case_id, 1, CaseStatus.ARCHIVED)
        app = self.start()
        self.go_to(app, MANAGEMENT)
        self.assertEqual({"Total cases": "2", "Active cases": "1", "Archived cases": "1"},
                         {item.label: item.value for item in app.metric})
        app.selectbox(key="case_status_filter").select("All statuses")
        app.text_input(key="case_search").set_value("OFFLINE")
        self.run_app(app)
        self.assertEqual([draft.metadata.case_id], app.dataframe[0].value["Case ID"].tolist())
        app.text_input(key="case_search").set_value(archived.metadata.case_id[:8])
        self.run_app(app)
        self.assertEqual([archived.metadata.case_id], app.dataframe[0].value["Case ID"].tolist())
        app.selectbox(key="case_status_filter").select("DRAFT")
        self.run_app(app)
        self.assertFalse(app.dataframe)
        self.assertTrue(app.button(key="case_open").disabled)

    def test_view_switch_preserves_active_draft_and_skips_new_versions(self):
        saved = self.repository.create("Continuity")
        app = self.start()
        self.open_case(app, saved.metadata.case_id)
        draft = self.widget(app, "text_area", "ticket_description")
        draft.set_value("Unsubmitted live draft")
        self.run_app(app)
        self.assertIn(":orange-badge[Unsaved changes]", [item.value for item in app.sidebar.markdown])
        self.go_to(app, MANAGEMENT)
        self.assertFalse(app.text_area)
        self.assertIn(":orange-badge[Unsaved changes]", [item.value for item in app.sidebar.markdown])
        self.click(app, "management_back")
        self.assertEqual("Unsubmitted live draft", self.widget(app, "text_area", "ticket_description").value)
        self.run_app(app)
        self.assertEqual(saved.metadata, self.repository.load(saved.metadata.case_id).metadata)
        self.click(app, "case_save")
        self.assertIn(":green-badge[Saved]", [item.value for item in app.sidebar.markdown])

    def test_switching_cases_isolates_edits_and_clears_evidence_consent(self):
        state = Investigation(step=3)
        image = ("image/png", PNG)
        state.set_evidence(MANUAL, Evidence(images=(image,), filenames=("capture.png",)))
        evidence = self.repository.create("With evidence", state)
        other = self.repository.create("Other", Investigation(manual_draft=Ticket("Other case draft")))
        app = self.start()
        with patch("evidence_engine.analyze_evidence") as send:
            self.open_case(app, evidence.metadata.case_id)
            consent = next(item for item in app.checkbox if "guided_consent" in item.key)
            first_consent_key = consent.key
            self.assertFalse(consent.value)
            consent.check()
            self.run_app(app)
            self.go_to(app, MANAGEMENT)
            self.go_to(app, WIZARD)
            self.assertTrue(app.checkbox(key=first_consent_key).value)
            self.assertEqual(1, self.repository.load(evidence.metadata.case_id).metadata.version)
            self.open_case(app, other.metadata.case_id)
            draft = self.widget(app, "text_area", "ticket_description")
            self.assertEqual("Other case draft", draft.value)
            draft.set_value("Unsaved edits")
            self.run_app(app)
            self.open_case(app, evidence.metadata.case_id)
            consent = next(item for item in app.checkbox if "guided_consent" in item.key)
            self.assertNotEqual(first_consent_key, consent.key)
            self.assertFalse(consent.value)
            self.assertTrue(app.button(key="guided_analyze_evidence").disabled)
            self.assertEqual(state.evidence_provenance, app.session_state["investigation"].evidence_provenance)
            self.open_case(app, other.metadata.case_id)
            self.assertEqual("Other case draft", self.widget(app, "text_area", "ticket_description").value)
            send.assert_not_called()

    def test_saved_lab_screenshot_survives_missing_source(self):
        state = Investigation(step=3, ticket=Ticket("Synthetic case", lab_run="missing-run", lab_id="INC-12345"))
        state.set_evidence_source(LAB)
        state.lab_selection = ("INC-12345_abcdef.png",)
        state.set_evidence(LAB, Evidence(images=(("image/png", PNG),), filenames=state.lab_selection))
        saved = self.repository.create("Synthetic", state)
        app = self.start()
        self.open_case(app, saved.metadata.case_id)
        self.assertEqual(state.evidence_provenance, app.session_state["investigation"].evidence_provenance)
        self.assertEqual(saved.metadata, self.repository.load(saved.metadata.case_id).metadata)

    def test_stale_save_is_visible_and_reload_restores_latest(self):
        case = self.repository.create("Concurrency")
        case_id = case.metadata.case_id
        app = self.start()
        self.open_case(app, case_id)
        latest = self.repository.transition(case_id, 1, CaseStatus.IN_PROGRESS)
        self.widget(app, "text_area", "ticket_description").set_value("Stale edit")
        self.click(app, "case_save")
        self.assertTrue(any("Another session changed" in alert.value for alert in app.error))
        self.assertEqual(latest.metadata, self.repository.load(case_id).metadata)
        self.assertTrue(app.button(key="case_save").disabled)
        self.open_case(app, case_id)
        self.assertFalse(app.error)
        self.assertEqual(latest.investigation.manual_draft.description, self.widget(app, "text_area", "ticket_description").value)

    def test_history_inspection_preserves_live_case_and_never_calls_gemini(self):
        live = self.repository.create("Live case")
        previous = Investigation(ticket=Ticket("Historical ticket"), results={"ai": "Saved AI conclusion"})
        with io.BytesIO() as buffer:
            Image.new("RGB", (16, 16), "navy").save(buffer, format="PNG")
            valid_png = buffer.getvalue()
        previous.set_evidence(MANUAL, Evidence(
            images=(("image/png", valid_png), ("image/png", PNG)), filenames=("history.png", "invalid.png"),
        ))
        historical = self.repository.create("Historical case", previous)
        case_id = historical.metadata.case_id
        active = self.repository.transition(case_id, 1, CaseStatus.IN_PROGRESS)
        held = self.repository.transition(case_id, active.metadata.version, CaseStatus.ON_HOLD, rationale="Waiting for logs")
        before = self.repository.history(case_id)
        app = self.start()
        self.open_case(app, live.metadata.case_id)
        self.widget(app, "text_area", "ticket_description").set_value("Live unsaved draft")
        self.run_app(app)
        self.go_to(app, MANAGEMENT)
        app.selectbox(key="case_selected").select(case_id)
        self.run_app(app)
        self.assertEqual([1, 2, 3], app.dataframe[1].value["Version"].tolist())
        self.assertEqual("Waiting for logs", app.dataframe[1].value.iloc[-1]["Transition reason"])
        with patch("ai_engine.analyze_ticket") as ai, patch("evidence_engine.analyze_evidence") as evidence, \
                patch("ticket_validator.validate_ticket") as validation, patch("case_history_ui.build_report_exports") as build:
            app.selectbox(key=f"audit_version_{case_id}").select(1)
            self.run_app(app)
            self.assertIn("Historical ticket", [item.value for item in app.text])
            self.assertIn("Saved AI conclusion", [item.value for item in app.text])
            self.assertIn(hashlib.sha256(valid_png).hexdigest(), [item.value for item in app.code])
            self.assertTrue(any(item.value.startswith("E01 ·") for item in app.text))
            self.assertIn("No reports have been issued for this case.", [item.value for item in app.caption])
            app.toggle(key=f"audit_previews_{case_id}_1").set_value(True)
            with patch.object(st, "image", wraps=st.image) as show_image:
                self.run_app(app)
                show_image.assert_called_once()
            self.assertTrue(any("Preview unavailable" in warning.value for warning in app.warning))
            self.run_app(app)
            for endpoint in (ai, evidence, validation, build):
                endpoint.assert_not_called()
        self.assertEqual(before, self.repository.history(case_id))
        self.assertEqual(held.metadata, self.repository.load(case_id).metadata)
        self.assertEqual([], self.repository.list_reports(case_id))
        self.click(app, "management_back")
        self.assertEqual(live.metadata, app.session_state["case_metadata"])
        self.assertEqual("Live unsaved draft", self.widget(app, "text_area", "ticket_description").value)

    def test_add_note_and_download_exact_issued_report(self):
        case = self.repository.create("Audit records", Investigation(ticket=Ticket("Report source")))
        case_id = case.metadata.case_id
        app = self.start()
        self.go_to(app, MANAGEMENT)
        app.selectbox(key="case_selected").select(case_id)
        self.run_app(app)
        app.toggle(key=f"audit_note_toggle_{case_id}").set_value(True)
        self.run_app(app)
        app.text_input(key=f"audit_author_{case_id}").set_value("Analyst A")
        app.text_area(key=f"audit_body_{case_id}").set_value("Manually verified the ticket")
        next(button for button in app.button if button.label == "Add analyst note").click()
        self.run_app(app)
        note, = self.repository.list_notes(case_id)
        self.assertEqual(("Analyst A", "Manually verified the ticket", 1), (note.author_label, note.body, note.version))
        self.assertIn("Manually verified the ticket", [item.value for item in app.text])
        self.click(app, f"audit_issue_{case_id}")
        stored, = self.repository.list_reports(case_id)
        report = self.repository.get_report(case_id, stored.id)
        self.assertIn(b"Report source", report.markdown_bytes)
        fields = json.loads(report.json_bytes)["case_audit"]
        self.assertEqual(stored.issued_at, fields["issued_at"])
        self.assertEqual("DRAFT", fields["lifecycle_status"])
        self.assertEqual("NOT_ASSESSED", fields["incident_verdict"])
        self.assertEqual([], fields["ai_assessment_quality"])
        self.repository.transition(case_id, 1, CaseStatus.IN_PROGRESS)
        with patch("case_history_ui.build_report_exports") as build, patch.object(st, "download_button", wraps=st.download_button) as download:
            app.selectbox(key=f"audit_report_{case_id}").select(stored.id)
            self.run_app(app)
            build.assert_not_called()
            self.assertEqual([report.markdown_bytes, report.json_bytes], [call.args[1] for call in download.call_args_list])
        self.assertEqual([1, 2], [entry.version for entry in self.repository.history(case_id)])
        self.assertEqual([stored], self.repository.list_reports(case_id))
