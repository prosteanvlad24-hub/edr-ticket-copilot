"""Local SQLite persistence and lifecycle rules for investigations."""

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from case_serialization import PAYLOAD_VERSION, decode_state, encode_state
from evidence_inputs import ALLOWED_MIME, MAX_IMAGE_BYTES, MAX_IMAGES
from investigation_state import LAB, MANUAL, Investigation


class CaseStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    CLOSED_RESOLVED = "CLOSED_RESOLVED"
    CLOSED_INCONCLUSIVE = "CLOSED_INCONCLUSIVE"
    ARCHIVED = "ARCHIVED"


class IncidentVerdict(StrEnum):
    MALICIOUS = "MALICIOUS"
    BENIGN = "BENIGN"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_ASSESSED = "NOT_ASSESSED"


class AssessmentQuality(StrEnum):
    CORRECT = "CORRECT"
    PARTIALLY_CORRECT = "PARTIALLY_CORRECT"
    INCORRECT = "INCORRECT"
    NOT_REVIEWED = "NOT_REVIEWED"


_TRANSITIONS = {
    CaseStatus.DRAFT: {CaseStatus.IN_PROGRESS, CaseStatus.ARCHIVED},
    CaseStatus.IN_PROGRESS: {
        CaseStatus.ON_HOLD, CaseStatus.CLOSED_RESOLVED,
        CaseStatus.CLOSED_INCONCLUSIVE, CaseStatus.ARCHIVED,
    },
    CaseStatus.ON_HOLD: {CaseStatus.IN_PROGRESS, CaseStatus.ARCHIVED},
    CaseStatus.CLOSED_RESOLVED: {CaseStatus.IN_PROGRESS, CaseStatus.ARCHIVED},
    CaseStatus.CLOSED_INCONCLUSIVE: {CaseStatus.IN_PROGRESS, CaseStatus.ARCHIVED},
}
_REQUIRES_REASON = {CaseStatus.ON_HOLD, CaseStatus.CLOSED_RESOLVED, CaseStatus.CLOSED_INCONCLUSIVE}


class CaseConflictError(RuntimeError):
    """The requested update was based on an older case version."""


class InvalidTransitionError(ValueError):
    """The requested lifecycle action is unavailable."""


class EvidenceIntegrityError(ValueError):
    """Stored screenshot data or provenance failed verification."""


@dataclass(frozen=True)
class CaseVersion:
    case_id: str
    version: int
    title: str
    status: CaseStatus
    incident_verdict: IncidentVerdict
    created_at: str
    saved_at: str
    event: str
    rationale: str | None


@dataclass(frozen=True)
class SavedCase:
    metadata: CaseVersion
    investigation: Investigation


def default_database_path():
    configured = os.getenv("EDR_CASE_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    base = os.getenv("LOCALAPPDATA") if os.name == "nt" else os.getenv("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "edr-ticket-copilot" / "cases.sqlite3"


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _choices(values):
    return ", ".join(repr(value.value if isinstance(value, StrEnum) else value) for value in sorted(values))


def _initial_schema(db):
    statuses = _choices(CaseStatus)
    statements = (
        f"""CREATE TABLE cases (
            id TEXT PRIMARY KEY NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ({statuses})),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            row_version INTEGER NOT NULL CHECK (row_version >= 1)
        )""",
        "CREATE INDEX cases_status_updated ON cases (status, updated_at)",
        f"""CREATE TABLE case_versions (
            case_id TEXT NOT NULL REFERENCES cases(id), version INTEGER NOT NULL,
            saved_at TEXT NOT NULL, event TEXT NOT NULL, rationale TEXT,
            title TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ({statuses})),
            incident_verdict TEXT NOT NULL DEFAULT 'NOT_ASSESSED'
                CHECK (incident_verdict IN ({_choices(IncidentVerdict)})),
            payload_version INTEGER NOT NULL, state_json TEXT NOT NULL,
            PRIMARY KEY (case_id, version)
        )""",
        f"""CREATE TABLE evidence_assets (
            case_id TEXT NOT NULL REFERENCES cases(id), sha256 TEXT NOT NULL,
            mime_type TEXT NOT NULL CHECK (mime_type IN ({_choices(ALLOWED_MIME)})),
            byte_count INTEGER NOT NULL CHECK (byte_count BETWEEN 1 AND {MAX_IMAGE_BYTES}),
            image_bytes BLOB NOT NULL CHECK (typeof(image_bytes) = 'blob' AND length(image_bytes) = byte_count),
            PRIMARY KEY (case_id, sha256)
        )""",
        f"""CREATE TABLE case_version_evidence (
            case_id TEXT NOT NULL, version INTEGER NOT NULL,
            source TEXT NOT NULL CHECK (source IN ({_choices((LAB, MANUAL))})),
            position INTEGER NOT NULL CHECK (position BETWEEN 0 AND {MAX_IMAGES - 1}),
            sha256 TEXT NOT NULL, screenshot_id TEXT NOT NULL, filename TEXT, label TEXT NOT NULL,
            PRIMARY KEY (case_id, version, source, position),
            FOREIGN KEY (case_id, version) REFERENCES case_versions(case_id, version),
            FOREIGN KEY (case_id, sha256) REFERENCES evidence_assets(case_id, sha256)
        )""",
        """CREATE TABLE analyst_notes (
            id TEXT PRIMARY KEY NOT NULL, case_id TEXT NOT NULL, version INTEGER NOT NULL,
            author_label TEXT NOT NULL, created_at TEXT NOT NULL, body TEXT NOT NULL,
            supersedes_note_id TEXT, UNIQUE (case_id, id),
            FOREIGN KEY (case_id, version) REFERENCES case_versions(case_id, version),
            FOREIGN KEY (case_id, supersedes_note_id) REFERENCES analyst_notes(case_id, id)
        )""",
        """CREATE TABLE case_reports (
            id TEXT PRIMARY KEY NOT NULL, case_id TEXT NOT NULL, version INTEGER NOT NULL,
            issued_at TEXT NOT NULL, report_status TEXT NOT NULL
                CHECK (report_status IN ('preliminary', 'evidence_reviewed')),
            markdown_bytes BLOB NOT NULL, json_bytes BLOB NOT NULL,
            FOREIGN KEY (case_id, version) REFERENCES case_versions(case_id, version)
        )""",
        """CREATE TABLE ai_assessments (
            id TEXT PRIMARY KEY NOT NULL, case_id TEXT NOT NULL, version INTEGER NOT NULL,
            module TEXT NOT NULL, created_at TEXT NOT NULL, model_identifier TEXT,
            output_json TEXT NOT NULL, UNIQUE (case_id, id),
            FOREIGN KEY (case_id, version) REFERENCES case_versions(case_id, version)
        )""",
        f"""CREATE TABLE ai_assessment_reviews (
            id TEXT PRIMARY KEY NOT NULL, case_id TEXT NOT NULL, version INTEGER NOT NULL,
            assessment_id TEXT NOT NULL, reviewer_label TEXT NOT NULL, created_at TEXT NOT NULL,
            quality TEXT NOT NULL CHECK (quality IN ({_choices(AssessmentQuality)})), rationale TEXT,
            FOREIGN KEY (case_id, version) REFERENCES case_versions(case_id, version),
            FOREIGN KEY (case_id, assessment_id) REFERENCES ai_assessments(case_id, id)
        )""",
    )
    for statement in statements:
        db.execute(statement)

    db.execute("""CREATE TRIGGER immutable_case_identity BEFORE UPDATE OF id, created_at ON cases
        BEGIN SELECT RAISE(ABORT, 'case identity is immutable'); END""")
    db.execute("""CREATE TRIGGER evidence_only_on_current_version BEFORE INSERT ON case_version_evidence
        WHEN NEW.version != (SELECT row_version FROM cases WHERE id = NEW.case_id)
        BEGIN SELECT RAISE(ABORT, 'case history is immutable'); END""")
    for table in (
        "case_versions", "evidence_assets", "case_version_evidence", "analyst_notes",
        "case_reports", "ai_assessments", "ai_assessment_reviews",
    ):
        for operation in ("UPDATE", "DELETE"):
            db.execute(f"""CREATE TRIGGER immutable_{table}_{operation}
                BEFORE {operation} ON {table}
                BEGIN SELECT RAISE(ABORT, 'case history is immutable'); END""")


_MIGRATIONS = (_initial_schema,)


class CaseRepository:
    """Persist snapshots using short transactions and explicit expected versions."""

    def __init__(self, path=None):
        self.path = Path(path).expanduser().resolve() if path is not None else default_database_path().resolve()

    @contextmanager
    def _transaction(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA recursive_triggers = ON")
            with db:
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(write=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > len(_MIGRATIONS):
                raise ValueError(f"Unsupported SQLite schema version {version}")
            for index in range(version, len(_MIGRATIONS)):
                _MIGRATIONS[index](db)
                db.execute(f"PRAGMA user_version = {index + 1}")

    @staticmethod
    def _row(db, case_id, version=None):
        row = db.execute(
            """SELECT v.*, c.created_at FROM cases c JOIN case_versions v ON v.case_id = c.id
               WHERE c.id = ? AND v.version = COALESCE(?, c.row_version)""",
            (case_id, version),
        ).fetchone()
        if row is None:
            raise KeyError((case_id, version))
        return row

    @staticmethod
    def _metadata(row):
        return CaseVersion(
            row["case_id"], row["version"], row["title"], CaseStatus(row["status"]),
            IncidentVerdict(row["incident_verdict"]), row["created_at"], row["saved_at"],
            row["event"], row["rationale"],
        )

    def _load(self, db, row):
        if row["payload_version"] != PAYLOAD_VERSION:
            raise ValueError(f"Unsupported case payload version {row['payload_version']}")
        images = defaultdict(list)
        data = json.loads(row["state_json"])
        links = db.execute(
            """SELECT e.*, a.image_bytes, a.mime_type, a.byte_count
               FROM case_version_evidence e JOIN evidence_assets a USING (case_id, sha256)
               WHERE e.case_id = ? AND e.version = ? ORDER BY e.source, e.position""",
            (row["case_id"], row["version"]),
        )
        for link in links:
            raw = link["image_bytes"]
            source = link["source"]
            index = len(images[source])
            meta = data["evidence_metadata"].get(source, {})
            provenance = meta.get("provenance", [])
            if (
                index >= len(provenance) or link["position"] != index
                or any(link[column] != provenance[index][key] for column, key in (
                    ("screenshot_id", "id"), ("label", "label"), ("filename", "filename"),
                    ("mime_type", "mime_type"), ("sha256", "sha256"),
                ))
                or len(raw) != link["byte_count"] or hashlib.sha256(raw).hexdigest() != link["sha256"]
            ):
                raise EvidenceIntegrityError(f"Invalid evidence in case {row['case_id']} version {row['version']}")
            images[source].append((link["mime_type"], raw))
        if any(len(images[source]) != len(meta["provenance"]) for source, meta in data["evidence_metadata"].items()):
            raise EvidenceIntegrityError("Missing screenshot links in saved case version")
        return SavedCase(self._metadata(row), decode_state(row["payload_version"], data, images))

    @staticmethod
    def _write_version(db, metadata, investigation):
        for source, evidence in investigation.evidence_by_source.items():
            if source not in (LAB, MANUAL) or len(evidence.images) > MAX_IMAGES:
                raise ValueError("Unsupported screenshot source or count")
            for mime, raw in evidence.images:
                if mime not in ALLOWED_MIME or not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_IMAGE_BYTES:
                    raise ValueError("Expected prepared screenshot bytes within the configured limits")
        state = encode_state(investigation)
        db.execute(
            """INSERT INTO case_versions
               (case_id, version, saved_at, event, rationale, title, status, incident_verdict, payload_version, state_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (metadata.case_id, metadata.version, metadata.saved_at, metadata.event, metadata.rationale,
             metadata.title, metadata.status, metadata.incident_verdict, PAYLOAD_VERSION,
             json.dumps(state, ensure_ascii=False, allow_nan=False)),
        )
        for source, evidence in investigation.evidence_by_source.items():
            for position, (mime, raw) in enumerate(evidence.images):
                provenance = state["evidence_metadata"][source]["provenance"][position]
                digest = provenance["sha256"]
                db.execute(
                    """INSERT INTO evidence_assets VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT (case_id, sha256) DO NOTHING""",
                    (metadata.case_id, digest, mime, len(raw), raw),
                )
                existing = db.execute(
                    "SELECT mime_type, image_bytes FROM evidence_assets WHERE case_id = ? AND sha256 = ?",
                    (metadata.case_id, digest),
                ).fetchone()
                if tuple(existing) != (mime, raw):
                    raise EvidenceIntegrityError("Existing screenshot does not match its SHA-256 provenance")
                db.execute(
                    "INSERT INTO case_version_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (metadata.case_id, metadata.version, source, position, digest,
                     provenance["id"], provenance["filename"], provenance["label"]),
                )

    def create(self, title, investigation=None):
        title = title.strip()
        if not title:
            raise ValueError("A case title is required")
        case_id, now = str(uuid4()), _timestamp()
        metadata = CaseVersion(case_id, 1, title, CaseStatus.DRAFT, IncidentVerdict.NOT_ASSESSED, now, now, "create", None)
        with self._transaction(write=True) as db:
            db.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?)", (case_id, title, metadata.status, now, now, 1))
            self._write_version(db, metadata, investigation if investigation is not None else Investigation())
            return self._load(db, self._row(db, case_id))

    def load(self, case_id, *, version=None):
        with self._transaction() as db:
            return self._load(db, self._row(db, case_id, version))

    def list_cases(self, *, archived=False):
        with self._transaction() as db:
            rows = db.execute(
                """SELECT v.*, c.created_at FROM cases c JOIN case_versions v
                     ON v.case_id = c.id AND v.version = c.row_version
                   WHERE (c.status = 'ARCHIVED') = ? ORDER BY c.updated_at DESC, c.id""",
                (archived,),
            )
            return [self._metadata(row) for row in rows]

    def history(self, case_id):
        with self._transaction() as db:
            self._row(db, case_id)
            rows = db.execute(
                """SELECT v.*, c.created_at FROM case_versions v JOIN cases c ON c.id = v.case_id
                   WHERE v.case_id = ? ORDER BY v.version""", (case_id,),
            )
            return [self._metadata(row) for row in rows]

    @staticmethod
    def _check_version(row, expected_version):
        if row["version"] != expected_version:
            raise CaseConflictError(f"Expected version {expected_version}, found {row['version']}")

    def _advance(self, db, previous, state, status, verdict, event, rationale=None):
        case_id, version = previous["case_id"], previous["version"]
        now = _timestamp()
        updated = db.execute(
            "UPDATE cases SET status = ?, updated_at = ?, row_version = ? WHERE id = ? AND row_version = ?",
            (status, now, version + 1, case_id, version),
        )
        if updated.rowcount != 1:
            raise CaseConflictError(f"Case {case_id} changed while saving")
        metadata = CaseVersion(case_id, version + 1, previous["title"], status, verdict,
                               previous["created_at"], now, event, rationale)
        self._write_version(db, metadata, state)
        return self._load(db, self._row(db, case_id))

    def save(self, case_id, expected_version, investigation, *, incident_verdict=None):
        with self._transaction(write=True) as db:
            previous = self._row(db, case_id)
            self._check_version(previous, expected_version)
            current = self._load(db, previous)
            status = current.metadata.status
            if status not in (CaseStatus.DRAFT, CaseStatus.IN_PROGRESS):
                raise InvalidTransitionError("Resume, reopen, or restore the case before saving edits")
            verdict = current.metadata.incident_verdict if incident_verdict is None else IncidentVerdict(incident_verdict)
            # Compare JSON representations to account for tuple/list normalization on load.
            if (
                verdict == current.metadata.incident_verdict
                and investigation.evidence_by_source == current.investigation.evidence_by_source
                and json.dumps(encode_state(investigation), sort_keys=True)
                == json.dumps(encode_state(current.investigation), sort_keys=True)
            ):
                return current
            return self._advance(db, previous, investigation, status, verdict, "save")

    def transition(self, case_id, expected_version, status, *, rationale=None, investigation=None):
        target = CaseStatus(status)
        rationale = rationale.strip() if rationale is not None else None
        with self._transaction(write=True) as db:
            previous = self._row(db, case_id)
            self._check_version(previous, expected_version)
            current = CaseStatus(previous["status"])
            if current == CaseStatus.ARCHIVED:
                allowed = {CaseStatus(self._row(db, case_id, expected_version - 1)["status"])}
            else:
                allowed = _TRANSITIONS[current]
            if target not in allowed:
                raise InvalidTransitionError(f"Cannot transition from {current} to {target}")
            if investigation is not None and (current, target) != (CaseStatus.DRAFT, CaseStatus.IN_PROGRESS):
                raise InvalidTransitionError("Investigation edits can accompany draft submission only")
            reopening = current in (CaseStatus.CLOSED_RESOLVED, CaseStatus.CLOSED_INCONCLUSIVE) and target == CaseStatus.IN_PROGRESS
            if current != CaseStatus.ARCHIVED and (target in _REQUIRES_REASON or reopening) and not rationale:
                raise InvalidTransitionError("An analyst rationale is required for this transition")
            return self._advance(
                db, previous, investigation if investigation is not None else self._load(db, previous).investigation,
                target, IncidentVerdict(previous["incident_verdict"]), "transition", rationale,
            )
