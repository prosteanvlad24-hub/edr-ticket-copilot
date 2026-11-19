"""Exercise the Ticket Lab handoff and screenshot consent with an offline Gemini client."""

import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from google import genai
from PIL import Image
import streamlit as st
from streamlit.testing.v1 import AppTest

from evidence_inputs import MAX_IMAGE_BYTES, prepare_images
from investigation_state import MANUAL, Evidence, Investigation
from ticket_lab import generate_run
from ticket_lab_inputs import list_evidence, read_case, read_catalog
from ui_styles import theme_config

PROJECT = Path(__file__).resolve().parent
PRIVATE_MARKER = "PRIVATE_LAB_GRADER_DATA_5a92c8"
VALIDATION = {
    "product": "unknown",
    "reported_issue": "Synthetic sensor gap",
    "requested_action": "Check agent health",
    "assessment": "Needs Clarification",
    "reasoning": "No agent telemetry supplied",
    "missing_information": [],
    "evidence_requests": [{
        "source": "Endpoint console", "what_to_capture": "Agent status", "why": "Inspect visibility",
        "grader_comment": PRIVATE_MARKER,
    }],
    "clarification_message": "Please share the observed agent status.",
    "answer_key": PRIVATE_MARKER,
}
ASSESSMENT = {
    "product": "unknown",
    "reported_issue": "Synthetic sensor gap",
    "requested_action": "Check agent health",
    "observations": [],
    "hypotheses": [],
    "requested_action_assessment": "Needs Clarification",
    "conclusion_status": "Insufficient Evidence",
    "conclusion": "Offline evidence assessment",
    "next_evidence_requests": [],
    "recommended_next_steps": [],
    "clarification_message": "Please confirm which device this evidence refers to.",
}


def jpeg_with_exif():
    exif = Image.Exif()
    exif[0x010E] = PRIVATE_MARKER
    with io.BytesIO() as buffer:
        Image.new("RGB", (120, 60), "blue").save(buffer, format="JPEG", exif=exif)
        return buffer.getvalue()


class TicketLabIntegrationTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def test_public_loader_supports_old_runs_without_answer_keys(self):
        run = generate_run(self.root, count=1, seed=14, with_evidence=True)
        ticket_id = next(iter(read_catalog(run)))
        filenames = list_evidence(run, ticket_id)
        self.assertEqual(5, len(filenames))
        for name in ("answer_key.json", "evidence_key.json", "evidence_manifest.json"):
            (run / name).unlink()
        self.assertEqual(filenames, list_evidence(run, ticket_id))
        case = read_case(run, ticket_id, filenames[:2])
        self.assertEqual(ticket_id, case.ticket_id)
        self.assertIn(ticket_id, case.description)
        self.assertEqual(2, len(case.images))
        with self.assertRaises(ValueError):
            read_case(run, ticket_id, ["../../answer_key.json"])

    def test_image_validation_and_metadata_removal(self):
        jpeg = jpeg_with_exif()
        for name, content in [
            ("empty.png", b""), ("disguised.png", b"not an image"),
            ("large.png", b"x" * (MAX_IMAGE_BYTES + 1)),
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                prepare_images([(name, content)])
        with self.assertRaises(ValueError):
            prepare_images([("case.jpg", jpeg)] * 4)
        mime, payload = prepare_images([("case.jpg", jpeg)])[0]
        self.assertEqual("image/jpeg", mime)
        self.assertNotIn(PRIVATE_MARKER.encode(), payload)
        with Image.open(io.BytesIO(payload)) as image:
            self.assertFalse(image.getexif())
            self.assertEqual((120, 60), image.size)

    def test_prior_validation_change_invalidates_evidence_review(self):
        case = Investigation()
        image = prepare_images([("manual.jpg", jpeg_with_exif())])[0]
        case.set_evidence(MANUAL, Evidence(("manual.jpg",), (image,)))
        case.save_validation(VALIDATION)
        case.consent = case.reviewed_fingerprint = case.fingerprint
        case.reviewed_evidence = ASSESSMENT
        self.assertEqual(ASSESSMENT, case.evidence_assessment)
        case.save_validation({**VALIDATION, "requested_action": "Verify software inventory"})
        self.assertIsNone(case.consent)
        self.assertIsNone(case.evidence_assessment)
        self.assertEqual((image,), case.evidence.images)

    def test_native_theme_matches_design_tokens(self):
        self.assertEqual(theme_config(), (PROJECT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))

    def create_app(self):
        for name in ("dashboard_v1_2.py", "tickets.json"):
            shutil.copyfile(PROJECT / name, self.root / name)
        return AppTest.from_file(str(self.root / "dashboard_v1_2.py"), default_timeout=20).run()

    def navigate(self, app, title, key="wizard_next"):
        app.button(key=key).click().run()
        self.assertEqual([], list(app.exception))
        self.assertEqual([title], [item.value for item in app.title])

    def test_streamlit_handoff_consent_and_exports(self):
        calls = []

        def respond(*, model, contents, config):
            calls.append((contents, config))
            if isinstance(contents, list):
                text = json.dumps(ASSESSMENT)
            elif config.response_mime_type == "application/json":
                text = json.dumps(VALIDATION)
            else:
                text = "## Initial analysis\nCheck the reported sensor gap."
            return SimpleNamespace(text=text)

        client = SimpleNamespace(models=SimpleNamespace(generate_content=respond), close=lambda: None)
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "offline-test"}),
            patch.object(genai, "Client", return_value=client),
            patch.object(st, "download_button", wraps=st.download_button) as downloads,
        ):
            app = self.create_app()
            app.text_area(key="ticket_description").set_value("Manual investigator notes").run()
            app.number_input(key="offline_hours").set_value(14).run()
            self.navigate(app, "Initial Analysis")
            app.button(key="local_analysis_button").click().run()
            self.assertEqual({"triage", "iocs"}, set(app.session_state["investigation"].results))
            self.assertEqual([], calls)
            self.navigate(app, "Ticket Lab / Ticket Entry", "wizard_back")
            self.assertEqual("Manual investigator notes", app.text_area(key="ticket_description").value)
            self.assertEqual(14, app.number_input(key="offline_hours").value)
            app.radio(key="ticket_source_widget").set_value("Ticket Lab").run()
            app.button(key="lab_generate").click().run()
            run = next((self.root / "runs").glob("run_*"))
            for name in ("answer_key.json", "evidence_key.json"):
                key_path = run / name
                data = json.loads(key_path.read_text(encoding="utf-8"))
                data["grader_only"] = PRIVATE_MARKER
                key_path.write_text(json.dumps(data), encoding="utf-8")
            app.button(key="lab_load").click().run()
            case = app.session_state["investigation"]
            ticket = case.ticket
            self.assertIn(ticket.lab_id, ticket.description)
            self.assertEqual({}, case.results)
            self.assertEqual([], calls)

            self.navigate(app, "Initial Analysis")
            app.button(key="full_analysis_button").click().run()
            self.assertEqual(2, len(calls))
            self.assertEqual({"triage", "iocs", "validation", "ai"}, set(case.results))
            self.navigate(app, "Initial Findings")
            self.navigate(app, "Evidence Investigation")
            self.assertEqual(1, len(app.get("image")))
            self.assertTrue(app.button(key="guided_analyze_evidence").proto.disabled)
            self.assertEqual(2, len(calls))

            app.checkbox[0].check().run()
            app.button(key="guided_analyze_evidence").click().run()
            self.assertEqual(3, len(calls))
            parts, _ = calls[-1]
            self.assertIn(ticket.lab_id, parts[0].text)
            self.assertIn(VALIDATION["clarification_message"], parts[0].text)
            self.assertEqual(case.evidence.images[0][1], parts[1].inline_data.data)
            for contents, config in calls:
                self.assertNotIn(PRIVATE_MARKER, repr((contents, config)))

            downloads.reset_mock()
            self.navigate(app, "Final Report")
            exports = {call.kwargs["key"]: call.kwargs["data"] for call in downloads.call_args_list}
            self.assertIn("Synthetic Ticket Lab screenshots", exports["download_full_report_v2"])
            reviewed = json.loads(exports["guided_download"])
            self.assertEqual("evidence_reviewed", reviewed["report_status"])
            self.assertEqual(ASSESSMENT, reviewed["evidence_assessment"])
            self.assertNotIn(PRIVATE_MARKER, repr(exports))
            self.navigate(app, "Evidence Investigation", "wizard_back")
            self.assertTrue(app.checkbox[0].value)
            self.assertEqual(1, len(app.get("image")))

            other_image = list_evidence(run, ticket.lab_id)[1]
            app.multiselect[0].set_value([other_image]).run()
            self.assertEqual(ticket, case.ticket)
            self.assertIsNone(case.evidence_assessment)
            self.assertFalse(app.checkbox[0].value)
            self.assertTrue(app.button(key="guided_analyze_evidence").proto.disabled)
            downloads.reset_mock()
            self.navigate(app, "Final Report", "wizard_skip_evidence")
            exports = {call.kwargs["key"]: call.kwargs["data"] for call in downloads.call_args_list}
            self.assertIn("**Report status:** Preliminary", exports["download_full_report_v2"])
            self.assertNotIn(ASSESSMENT["conclusion"], exports["download_full_report_v2"])
            preliminary = json.loads(exports["guided_download"])
            self.assertEqual("preliminary", preliminary["report_status"])
            self.assertIsNone(preliminary["evidence_assessment"])
            self.assertEqual(3, len(calls))

            for title in ("Evidence Investigation", "Initial Findings", "Initial Analysis", "Ticket Lab / Ticket Entry"):
                self.navigate(app, title, "wizard_back")
            app.radio(key="ticket_source_widget").set_value("Manual entry").run()
            self.assertEqual("Manual investigator notes", app.text_area(key="ticket_description").value)
            self.navigate(app, "Initial Analysis")
            self.assertEqual({}, case.results)
            self.assertEqual({}, case.evidence_by_source)
            self.assertEqual(3, len(calls))
            self.navigate(app, "Initial Findings")
            self.navigate(app, "Evidence Investigation")
            uploader = app.get("file_uploader")[0]
            if hasattr(uploader, "upload"):
                uploader.upload("manual.jpg", jpeg_with_exif(), "image/jpeg").run()
                self.assertEqual(1, len(app.get("image")))
                self.navigate(app, "Initial Findings", "wizard_back")
                self.navigate(app, "Evidence Investigation")
                self.assertEqual(1, len(app.get("image")))
                app.checkbox[0].check().run()
                app.button(key="guided_analyze_evidence").click().run()
                self.assertEqual(4, len(calls))
                manual_parts, _ = calls[-1]
                self.assertIn("Manual investigator notes", manual_parts[0].text)
                self.assertNotIn(PRIVATE_MARKER.encode(), manual_parts[1].inline_data.data)
                downloads.reset_mock()
                self.navigate(app, "Final Report")
                manual_report = next(
                    call.kwargs["data"] for call in downloads.call_args_list
                    if call.kwargs["key"] == "download_full_report_v2"
                )
                self.assertIn("Analyst-uploaded screenshots", manual_report)

    def test_gemini_failure_allows_local_findings_and_export(self):
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "offline-test"}),
            patch.object(genai, "Client", side_effect=ConnectionError("Offline provider")) as client,
        ):
            app = self.create_app()
            self.navigate(app, "Initial Analysis")
            app.button(key="full_analysis_button").click().run()
            case = app.session_state["investigation"]
            self.assertEqual({"validation", "ai"}, set(case.errors))
            self.assertEqual({"triage", "iocs"}, set(case.results))
            self.navigate(app, "Initial Findings")
            self.navigate(app, "Evidence Investigation")
            self.navigate(app, "Final Report", "wizard_skip_evidence")
            self.assertEqual(2, len(app.get("download_button")))
            self.assertEqual(2, client.call_count)


if __name__ == "__main__":
    unittest.main()
