import base64
from contextlib import closing
from datetime import datetime
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import case_repository
from case_repository import (
    AssessmentQuality, CaseConflictError, CaseRepository, CaseStatus,
    EvidenceIntegrityError, IncidentVerdict, InvalidTransitionError,
)
from investigation_state import LAB, MANUAL, Evidence, Investigation, Ticket


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0CYAAAAASUVORK5CYII="
)


class CaseRepositoryTest(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "cases.sqlite3"
        self.repository = CaseRepository(self.path)
        self.repository.initialize()

    def move(self, case, status):
        return self.repository.transition(case.metadata.case_id, case.metadata.version, status, rationale="Analyst decision")

    def test_explicit_decisions_are_independent_versioned_and_optimistic(self):
        case = self.repository.create("Decisions", Investigation(results={"ai": "Saved assessment"}))
        case_id = case.metadata.case_id
        output_id, = self.repository.reviewable_outputs(case_id, 1)
        verdict = self.repository.set_incident_verdict(case_id, 1, IncidentVerdict.BENIGN)
        self.assertEqual(CaseStatus.DRAFT, verdict.status)
        self.assertEqual(AssessmentQuality.NOT_REVIEWED, self.repository.assessment_quality(case_id, 2)[0]["quality"])
        with self.assertRaises(CaseConflictError):
            self.repository.review_assessment(case_id, 1, output_id, AssessmentQuality.CORRECT)
        reviewed = self.repository.review_assessment(case_id, 2, output_id, AssessmentQuality.PARTIALLY_CORRECT,
                                                      reviewer_label=" Analyst label ", rationale=" Limited support ")
        self.assertEqual(IncidentVerdict.BENIGN, reviewed.incident_verdict)
        self.assertEqual(CaseStatus.DRAFT, reviewed.status)
        self.assertEqual(reviewed, self.repository.review_assessment(
            case_id, 3, output_id, AssessmentQuality.PARTIALLY_CORRECT, reviewer_label="Analyst label",
            rationale="Limited support",
        ))
        reviews = self.repository.assessment_quality(case_id, 3)
        self.assertEqual(("Analyst label", "Limited support"), (reviews[0]["reviewer_label"], reviews[0]["rationale"]))
        self.assertEqual(AssessmentQuality.NOT_REVIEWED, self.repository.assessment_quality(case_id, 1)[0]["quality"])
        self.assertEqual(case, self.repository.load(case_id, version=1))

        # A new successful run gets a fresh identity even if its bytes are identical.
        repeated = self.repository.save(case_id, 3, case.investigation, ai_module="ai")
        second_id, = self.repository.reviewable_outputs(case_id, repeated.metadata.version)
        self.assertNotEqual(output_id, second_id)
        self.assertEqual([AssessmentQuality.PARTIALLY_CORRECT, AssessmentQuality.NOT_REVIEWED],
                         [row["quality"] for row in self.repository.assessment_quality(case_id, 4)])
        with self.assertRaises(ValueError):
            self.repository.review_assessment(case_id, 4, output_id, AssessmentQuality.CORRECT)
        active = self.move(repeated, CaseStatus.IN_PROGRESS)
        closed = self.move(active, CaseStatus.CLOSED_INCONCLUSIVE)
        self.assertEqual(IncidentVerdict.BENIGN, closed.metadata.incident_verdict)
        archived = self.move(closed, CaseStatus.ARCHIVED)
        with self.assertRaises(InvalidTransitionError):
            self.repository.set_incident_verdict(case_id, archived.metadata.version, IncidentVerdict.MALICIOUS)
        self.assertEqual(CaseStatus.CLOSED_INCONCLUSIVE, self.move(archived, CaseStatus.CLOSED_INCONCLUSIVE).metadata.status)

    def test_legacy_schema_and_snapshot_stay_readable_when_rating_saved_output(self):
        # Construct a pre-Phase 4E snapshot with output but no assessment registration.
        with patch.object(CaseRepository, "_register_outputs"):
            old = self.repository.create("Legacy", Investigation(results={"ai": "Legacy response"}))
        case_id = old.metadata.case_id
        self.repository.initialize()
        with self.assertRaises(ValueError):
            self.repository.transition(case_id, 1, "OPEN")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(1, db.execute("PRAGMA user_version").fetchone()[0])
        assessment_id, = self.repository.reviewable_outputs(case_id, 1)
        self.assertEqual([], self.repository.assessment_quality(case_id, 1))
        review = self.repository.review_assessment(case_id, 1, assessment_id, AssessmentQuality.INCORRECT)
        self.assertEqual(2, review.version)
        self.assertEqual(old, self.repository.load(case_id, version=1))
        self.assertEqual([], self.repository.assessment_quality(case_id, 1))
        saved, = self.repository.assessment_quality(case_id, 2)
        self.assertEqual(assessment_id, saved["assessment_id"])
        self.assertEqual("", saved["reviewer_label"])
        self.assertEqual(AssessmentQuality.INCORRECT, saved["quality"])

    def test_initialization_and_migration_rollback(self):
        case = self.repository.create("Migration baseline")
        self.repository.initialize()
        self.assertEqual(case.metadata, self.repository.load(case.metadata.case_id).metadata)

        def broken_migration(db):
            db.execute("CREATE TABLE partial_migration (id INTEGER)")
            raise RuntimeError("migration failed")

        with patch.object(case_repository, "_MIGRATIONS", (*case_repository._MIGRATIONS, broken_migration)):
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                self.repository.initialize()
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(1, db.execute("PRAGMA user_version").fetchone()[0])
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='partial_migration'").fetchone())
            db.execute("PRAGMA user_version = 99")
        with self.assertRaisesRegex(ValueError, "Unsupported SQLite schema version 99"):
            self.repository.initialize()

    def test_persistence_and_noop_save(self):
        ticket = Ticket("EDR sensor offline", "high", 6, 2, "run", "INC-123")
        state = Investigation(step=3, ticket=ticket, lab_selection=("first.png",))
        state.results["triage"] = {"score": 42}
        state.errors["ai"] = "temporary network error"
        state.consent = "transient"
        case = self.repository.create(" Offline sensor ", state)
        other = self.repository.create("Another case")
        reopened = CaseRepository(self.path).load(case.metadata.case_id)
        self.assertNotEqual(case.metadata.case_id, other.metadata.case_id)
        self.assertEqual(CaseStatus.DRAFT, reopened.metadata.status)
        self.assertEqual(IncidentVerdict.NOT_ASSESSED, reopened.metadata.incident_verdict)
        self.assertEqual("Offline sensor", reopened.metadata.title)
        self.assertEqual(0, datetime.fromisoformat(reopened.metadata.created_at).utcoffset().total_seconds())
        self.assertEqual(ticket, reopened.investigation.ticket)
        self.assertEqual(3, reopened.investigation.step)
        self.assertEqual(("first.png",), reopened.investigation.lab_selection)
        self.assertEqual(state.results, reopened.investigation.results)
        self.assertIsNone(reopened.investigation.consent)
        self.assertEqual({}, reopened.investigation.errors)
        no_op = self.repository.save(case.metadata.case_id, 1, state)
        self.assertEqual(1, no_op.metadata.version)

    def test_complete_transition_matrix(self):
        progress = CaseStatus.IN_PROGRESS
        archived = CaseStatus.ARCHIVED
        expected = {
            CaseStatus.DRAFT: {progress, archived},
            progress: {CaseStatus.ON_HOLD, CaseStatus.CLOSED_RESOLVED, CaseStatus.CLOSED_INCONCLUSIVE, archived},
            CaseStatus.ON_HOLD: {progress, archived},
            CaseStatus.CLOSED_RESOLVED: {progress, archived},
            CaseStatus.CLOSED_INCONCLUSIVE: {progress, archived},
        }
        for source in expected:
            for target in CaseStatus:
                with self.subTest(source=source, target=target):
                    case = self.repository.create("Transition matrix")
                    if source != CaseStatus.DRAFT:
                        case = self.move(case, progress)
                    if case.metadata.status != source:
                        case = self.move(case, source)
                    if target in expected[source]:
                        self.assertEqual(target, self.move(case, target).metadata.status)
                    else:
                        with self.assertRaises(InvalidTransitionError):
                            self.move(case, target)
                        self.assertEqual(case.metadata, self.repository.load(case.metadata.case_id).metadata)

    def test_archive_restores_only_the_previous_status(self):
        for source in set(CaseStatus) - {CaseStatus.ARCHIVED}:
            with self.subTest(source=source):
                case = self.repository.create("Archive restoration")
                if source != CaseStatus.DRAFT:
                    case = self.move(case, CaseStatus.IN_PROGRESS)
                if source != case.metadata.status:
                    case = self.move(case, source)
                archived = self.move(case, CaseStatus.ARCHIVED)
                self.assertIn(archived.metadata, self.repository.list_cases(archived=True))
                self.assertNotIn(archived.metadata, self.repository.list_cases())
                for target in set(CaseStatus) - {source}:
                    with self.assertRaises(InvalidTransitionError):
                        self.move(archived, target)
                restored = self.move(archived, source)
                self.assertEqual(source, restored.metadata.status)

    def test_closure_and_reopening_preserve_all_verdicts(self):
        for verdict in IncidentVerdict:
            for outcome in (CaseStatus.CLOSED_RESOLVED, CaseStatus.CLOSED_INCONCLUSIVE):
                with self.subTest(verdict=verdict, outcome=outcome):
                    case = self.move(self.repository.create("Closure"), CaseStatus.IN_PROGRESS)
                    case_id = case.metadata.case_id
                    case = self.repository.save(case_id, case.metadata.version, case.investigation, incident_verdict=verdict)
                    with self.assertRaises(InvalidTransitionError):
                        self.repository.transition(case_id, case.metadata.version, outcome)
                    closed = self.move(case, outcome)
                    reopened = self.move(closed, CaseStatus.IN_PROGRESS)
                    self.assertEqual(verdict, closed.metadata.incident_verdict)
                    self.assertEqual(verdict, reopened.metadata.incident_verdict)
                    self.assertEqual(closed.metadata, self.repository.load(case_id, version=closed.metadata.version).metadata)

    def test_history_is_immutable_and_assessment_quality_is_independent(self):
        case = self.repository.create("History")
        case_id = case.metadata.case_id
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("INSERT INTO analyst_notes VALUES (?, ?, 1, ?, ?, ?, NULL)",
                       ("note", case_id, "Analyst", case.metadata.saved_at, "Original note"))
            db.execute("INSERT INTO case_reports VALUES (?, ?, 1, ?, ?, ?, ?)",
                       ("report", case_id, case.metadata.saved_at, "preliminary", b"# Report", b"{}"))
            db.execute("INSERT INTO ai_assessments VALUES (?, ?, 1, ?, ?, NULL, ?)",
                       ("assessment", case_id, "ai", case.metadata.saved_at, '"finding"'))
            db.execute("INSERT INTO ai_assessment_reviews VALUES (?, ?, 1, ?, ?, ?, ?, NULL)",
                       ("review", case_id, "assessment", "Analyst", case.metadata.saved_at, AssessmentQuality.INCORRECT))

        active = self.move(case, CaseStatus.IN_PROGRESS)
        held = self.move(active, CaseStatus.ON_HOLD)
        resumed = self.move(held, CaseStatus.IN_PROGRESS)
        closed = self.move(resumed, CaseStatus.CLOSED_INCONCLUSIVE)
        reopened = self.move(closed, CaseStatus.IN_PROGRESS)
        history = self.repository.history(case_id)
        self.assertEqual(list(range(1, 7)), [entry.version for entry in history])
        self.assertEqual(case.metadata, history[0])
        self.assertEqual(closed.metadata, history[-2])
        self.assertEqual(reopened.metadata, history[-1])
        self.assertEqual(IncidentVerdict.NOT_ASSESSED, reopened.metadata.incident_verdict)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(("Original note", case.metadata.saved_at), db.execute("SELECT body, created_at FROM analyst_notes").fetchone())
            self.assertEqual((b"# Report", b"{}", case.metadata.saved_at), db.execute("SELECT markdown_bytes, json_bytes, issued_at FROM case_reports").fetchone())
            self.assertEqual((AssessmentQuality.INCORRECT,), db.execute("SELECT quality FROM ai_assessment_reviews").fetchone())
            for statement in (
                "UPDATE case_versions SET saved_at = 'changed'", "DELETE FROM case_versions",
                "UPDATE analyst_notes SET body = 'changed'", "DELETE FROM case_reports",
                "UPDATE ai_assessment_reviews SET quality = 'CORRECT'",
            ):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    db.execute(statement)
            db.execute("INSERT INTO ai_assessment_reviews VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                       ("later-review", case_id, reopened.metadata.version, "assessment", "Analyst",
                        reopened.metadata.saved_at, AssessmentQuality.PARTIALLY_CORRECT))
        self.assertEqual(AssessmentQuality.INCORRECT, self.repository.assessment_quality(case_id, 1)[0]["quality"])
        self.assertEqual(AssessmentQuality.PARTIALLY_CORRECT,
                         self.repository.assessment_quality(case_id, reopened.metadata.version)[0]["quality"])

    def test_evidence_round_trip_and_integrity(self):
        state = Investigation()
        image = ("image/png", PNG)
        state.set_evidence(MANUAL, Evidence(("Visible label",), (image, image), ("first.png", "second.png")))
        state.set_evidence(LAB, Evidence(images=(image,)))
        state.consent = state.reviewed_fingerprint = state.fingerprint
        state.reviewed_evidence = {"assessment": "Completed"}
        case = self.repository.create("Evidence", state)
        case_id = case.metadata.case_id
        loaded = self.repository.load(case_id).investigation
        self.assertEqual(state.evidence_by_source, loaded.evidence_by_source)
        self.assertEqual(state.evidence_assessment, loaded.evidence_assessment)
        self.assertIsNone(loaded.consent)
        self.assertEqual(["E01", "E02"], [item["id"] for item in loaded.evidence_provenance])
        digest = hashlib.sha256(PNG).hexdigest()
        self.assertEqual([digest, digest], [item["sha256"] for item in loaded.evidence_provenance])
        active = self.move(case, CaseStatus.IN_PROGRESS)
        loaded.clear_manual_evidence()
        saved = self.repository.save(case_id, active.metadata.version, loaded)
        self.assertIsNone(saved.investigation.evidence_assessment)
        self.assertEqual(state.evidence_by_source, self.repository.load(case_id, version=1).investigation.evidence_by_source)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM evidence_assets").fetchone()[0])
            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                db.execute("UPDATE evidence_assets SET image_bytes = ?", (b"x" * len(PNG),))
            db.execute("DROP TRIGGER immutable_evidence_assets_UPDATE")
            db.execute("UPDATE evidence_assets SET image_bytes = ?", (b"x" * len(PNG),))
        with self.assertRaises(EvidenceIntegrityError):
            self.repository.load(case_id, version=1)

    def test_stale_write_and_transition_are_rejected(self):
        case = self.repository.create("Concurrency")
        case_id = case.metadata.case_id
        second_repository = CaseRepository(self.path)
        stale = second_repository.load(case_id)
        moved = self.move(case, CaseStatus.IN_PROGRESS)
        stale.investigation.step = 2
        with self.assertRaises(CaseConflictError):
            second_repository.save(case_id, stale.metadata.version, stale.investigation)
        with self.assertRaises(CaseConflictError):
            second_repository.transition(case_id, stale.metadata.version, CaseStatus.ARCHIVED)
        self.assertEqual(moved.metadata, second_repository.load(case_id).metadata)

    def test_evidence_link_failure_rolls_back_entire_save(self):
        case = self.repository.create("Rollback")
        case_id = case.metadata.case_id
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TRIGGER reject_evidence BEFORE INSERT ON case_version_evidence
                          BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
        case.investigation.set_evidence(MANUAL, Evidence(images=(("image/png", PNG),)))
        with self.assertRaisesRegex(sqlite3.IntegrityError, "injected failure"):
            self.repository.save(case_id, 1, case.investigation, incident_verdict=IncidentVerdict.BENIGN)
        self.assertEqual([case.metadata], self.repository.history(case_id))
        self.assertEqual(case.metadata, self.repository.load(case_id).metadata)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM evidence_assets").fetchone()[0])

    def test_notes_and_issued_reports_are_versioned_without_rewriting_snapshots(self):
        case = self.repository.create("Audit")
        other = self.repository.create("Other audit")
        case_id = case.metadata.case_id
        note = self.repository.add_note(case_id, 1, "Analyst", "Original note")
        original = self.repository.issue_report(case_id, 1, "preliminary", b"# Original\r\n", b'{"original":true}')
        self.assertEqual([case.metadata], self.repository.history(case_id))
        active = self.move(case, CaseStatus.IN_PROGRESS)
        with self.assertRaises(CaseConflictError):
            self.repository.add_note(case_id, 1, "Analyst", "Stale note")
        with self.assertRaises(CaseConflictError):
            self.repository.issue_report(case_id, 1, "preliminary", b"stale", b"{}")
        with self.assertRaises(ValueError):
            self.repository.add_note(other.metadata.case_id, 1, "Analyst", "Invalid correction", supersedes_note_id=note.id)
        with self.assertRaises(KeyError):
            self.repository.get_report(other.metadata.case_id, original.id)
        correction = self.repository.add_note(case_id, 2, "Analyst", "New finding", supersedes_note_id=note.id)
        later = self.repository.issue_report(case_id, 2, "preliminary", b"# Second", b"{}")
        self.assertEqual([note, correction], self.repository.list_notes(case_id))
        self.assertEqual([original, later], self.repository.list_reports(case_id))
        issued = self.repository.get_report(case_id, original.id)
        self.assertEqual(original, issued.metadata)
        self.assertEqual(b"# Original\r\n", issued.markdown_bytes)
        self.assertEqual(b'{"original":true}', issued.json_bytes)
        self.assertEqual([case.metadata, active.metadata], self.repository.history(case_id))
        with closing(sqlite3.connect(self.path)) as db, db:
            for sql in ("DELETE FROM analyst_notes", "UPDATE case_reports SET json_bytes = X'00'"):
                with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                    db.execute(sql)
