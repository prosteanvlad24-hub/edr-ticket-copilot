# EDR Ticket Copilot v0.5 Architecture and Implementation Plan

## Repository baseline

The working directory and Git root were both `E:/project/EDR-Copilot-v0.4-Analysis-Fixes/edr-ticket-copilot`. `git branch --show-current` returned `feature/case-management`. Before this document was added, `git status --short --branch` returned only `## feature/case-management...origin/feature/case-management`, indicating a clean working tree. The assessment is based on source inspection. Tests were inventoried without execution.

## Existing application

The v0.4 application is a five-step Streamlit wizard covering ticket entry, initial analysis, initial findings, evidence investigation, and a final report. Launch it with `streamlit run dashboard_v1_2.py`. Manual entry and synthetic Ticket Lab imports feed the same investigation workflow. The active case exists in Streamlit session state and can survive widget reruns within that session.

| Files | Responsibilities |
| --- | --- |
| `dashboard_v1_2.py`, `ui_styles.py` | Wizard entry point, navigation, module orchestration, evidence consent, previews, and downloads. |
| `investigation_state.py` | `Ticket`, `Evidence`, and `Investigation` dataclasses. Owns ticket transitions, result invalidation, evidence selection, and reassessment freshness. |
| `rules_engine.py`, `severity_engine.py`, `ioc_engine.py` | Deterministic classification, investigation guidance, severity assessment, and candidate IOC extraction. |
| `ai_engine.py`, `ticket_validator.py`, `evidence_engine.py` | Google Gemini integration using `GEMINI_API_KEY`. Handles preliminary analysis, structured ticket validation, and multimodal evidence reassessment. Local findings and exports remain available after Gemini failures. |
| `evidence_inputs.py` | Validates and prepares screenshot bytes, removes image metadata, generates screenshot IDs and SHA-256 provenance, and fingerprints the reassessment inputs. |
| `ticket_lab.py`, `ticket_lab_inputs.py`, `tickets.json` | Synthetic scenario generation, public Ticket Lab run and evidence loading, and bundled sample tickets. |
| `report_engine_v2.py`, `dashboard_v1_2.py` | Generate Markdown and assemble JSON, respectively. The report is preliminary until the case has a current evidence reassessment. |
| `app.py`, `main.py`, `report_engine.py` | Earlier ticket-processing code, a Python starter script, and the earlier report generator. The current wizard entry point is `dashboard_v1_2.py`. |

## Proposed v0.5 architecture

Target a local, single-analyst deployment. Add a `case_repository.py` module using Python's standard-library `sqlite3` and an explicit mapping between database records and `Investigation`. Keep workflow transitions in the existing state object and use the dashboard to invoke load and save at user-action boundaries. Streamlit session state holds the active case and transient widget values. SQLite holds the durable case data. A configurable database path should point to a writable local directory outside version control.

### SQLite schema

| Table | Proposed columns and constraints |
| --- | --- |
| `cases` | `id TEXT PRIMARY KEY` (generated UUID), `title TEXT NOT NULL`, `status TEXT NOT NULL` constrained to the six lifecycle values below, `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL`, `row_version INTEGER NOT NULL`. Store timestamps in UTC. Index `(status, updated_at)` for the case list. |
| `case_versions` | `case_id TEXT`, `version INTEGER`, `saved_at TEXT NOT NULL`, `event TEXT NOT NULL`, `status TEXT NOT NULL`, `incident_verdict TEXT NOT NULL DEFAULT 'NOT_ASSESSED'`, `payload_version INTEGER NOT NULL`, `state_json TEXT NOT NULL`. Primary key `(case_id, version)` and foreign key to `cases`. The snapshot includes durable wizard state, source references, analysis results, selected evidence, evidence revision, and the completed reassessment and its fingerprint. `cases.row_version` identifies the latest snapshot. |
| `evidence_assets` | `case_id TEXT`, `sha256 TEXT`, `mime_type TEXT NOT NULL`, `byte_count INTEGER NOT NULL`, `image_bytes BLOB NOT NULL`. Primary key `(case_id, sha256)` and foreign key to `cases`. Constrain size to the existing per-image limit and check that the stored byte count matches the BLOB. |
| `case_version_evidence` | `case_id TEXT`, `version INTEGER`, `source TEXT`, `position INTEGER`, `sha256 TEXT NOT NULL`, `screenshot_id TEXT NOT NULL`, `filename TEXT`, `label TEXT`. Primary key `(case_id, version, source, position)` with composite foreign keys to the version and asset. Preserve the image ordering used for screenshot attribution. |
| `analyst_notes` | `id TEXT PRIMARY KEY`, `case_id TEXT NOT NULL`, `version INTEGER NOT NULL`, `author_label TEXT NOT NULL`, `created_at TEXT NOT NULL`, `body TEXT NOT NULL`, `supersedes_note_id TEXT`. Composite foreign key to the case version. Corrections append a note linked to the original within the same case. |
| `case_reports` | `id TEXT PRIMARY KEY`, `case_id TEXT NOT NULL`, `version INTEGER NOT NULL`, `issued_at TEXT NOT NULL`, `report_status TEXT NOT NULL`, `markdown_bytes BLOB NOT NULL`, `json_bytes BLOB NOT NULL`. Composite foreign key to the case version. Store the exact issued artifacts before offering them for download. |
| `ai_assessments`, `ai_assessment_reviews` | Give each saved AI output a stable assessment ID, with a link to its originating case version, module, timestamp, and model identifier when available. Store each manual review as an append-only record linked to the assessment and review-time case version, with reviewer label, UTC timestamp, constrained quality value, and optional rationale. An assessment with no review has quality `NOT_REVIEWED`. |

Enable foreign key enforcement on every connection. Save case metadata, the new snapshot, and any evidence links in one transaction. Use parameterized SQL and a bounded busy timeout. Keep write transactions short and use the expected `row_version` in the update so a stale tab receives a conflict with an option to reload. Calls to Gemini happen outside write transactions. Attach the result only after checking the case version and relevant input fingerprint.

### Case lifecycle

Manual entry and Ticket Lab imports start in `DRAFT` with a new internal case ID. Retain Ticket Lab run and ticket IDs as provenance. Apply the same transition rules in the wizard and repository.

`DRAFT` is the canonical stored initial status for v0.5. The term `OPEN` in the baseline audit request does not add a lifecycle state or alias. Phase 4E leaves stored statuses and schema version unchanged.

| Current status | Allowed next status and action |
| --- | --- |
| `DRAFT` | `IN_PROGRESS` on ticket submission, or `ARCHIVED` on archive. |
| `IN_PROGRESS` | `ON_HOLD` on pause, `CLOSED_RESOLVED` when the analyst confirms resolution, `CLOSED_INCONCLUSIVE` when the analyst ends the investigation without confirming resolution, or `ARCHIVED` on archive. |
| `ON_HOLD` | `IN_PROGRESS` on resume, or `ARCHIVED` on archive. Resume before closing. |
| `CLOSED_RESOLVED` | `IN_PROGRESS` on explicit reopen, or `ARCHIVED` on archive. |
| `CLOSED_INCONCLUSIVE` | `IN_PROGRESS` on explicit reopen, or `ARCHIVED` on archive. |
| `ARCHIVED` | Restore only to the status recorded immediately before archive. Apply the restored status's normal rules thereafter. |

Reject all other transitions. Record each transition as a new version with its UTC timestamp, action, and analyst rationale for hold, closure, and reopening. Viewing a case leaves its status intact. Resume and reopen load the saved wizard state and retain prior notes, evidence, and issued reports. Save committed wizard changes and skip identical saves on rerun. Closed and archived cases remain available for historical review.

### Lifecycle, verdict, and AI quality

| Concept | Values and ownership |
| --- | --- |
| Case lifecycle | `DRAFT`, `IN_PROGRESS`, `ON_HOLD`, `CLOSED_RESOLVED`, `CLOSED_INCONCLUSIVE`, `ARCHIVED`. The analyst controls work state and explicitly chooses the closure outcome. |
| Incident verdict | `MALICIOUS`, `BENIGN`, `INCONCLUSIVE`, `NOT_ASSESSED`. The analyst records a verdict independently in the case snapshot. |
| AI assessment quality | `CORRECT`, `PARTIALLY_CORRECT`, `INCORRECT`, `NOT_REVIEWED`. The analyst rates a particular saved AI output. A later Gemini run gets its own assessment ID and review state. |

Closure preserves both the incident verdict and AI review records. A case can close as `CLOSED_INCONCLUSIVE` with a `MALICIOUS` verdict if malicious activity was confirmed but resolution remains unverified. A resolved case can carry a `BENIGN` verdict. Cases whose verdict remains `NOT_ASSESSED` can also be closed. Reopening, resuming, and archiving likewise preserve the independently recorded values.

### Evidence storage and reassessment

Persist the prepared screenshot bytes already produced by `prepare_images`, along with their MIME type, original filename or label, source, order, app-generated screenshot ID, and SHA-256. Keep the current limit of three PNG, JPEG, or WebP screenshots per selection and 8 MiB per image. Deduplicate identical prepared bytes within each case while retaining distinct provenance links. Saving the bytes makes historical cases reproducible if a Ticket Lab run is moved or removed. The recorded digest identifies the prepared image that the app reviewed.

Restore completed reassessments only if the reconstructed fingerprint matches the saved assessment. Preserve the existing invalidation behavior for ticket, evidence, and prior-validation changes. Reset outbound consent on reload and require a fresh acknowledgement for each subsequent Gemini submission. Treat image text, ticket content, filenames, and model responses as untrusted data throughout rendering, analysis, and export.

### Version history and reports

Use append-only snapshots for committed changes. Record the event that produced each version, such as ticket update, analysis completion, evidence selection, or case closure. Keep the database row version separate from the existing investigation and evidence revisions. Use SQLite `PRAGMA user_version` for database migrations and `payload_version` for evolving snapshot formats. Migrations should run transactionally, preserve earlier snapshots, and report unsupported newer formats clearly.

Generate Markdown and JSON from the loaded case version through the existing export paths. Include case ID, version, issuance timestamp, lifecycle status, incident verdict, and any applicable AI quality labels as distinct fields. Keep preliminary and evidence-reviewed report status independent of closure. Issue both formats as one immutable record. Historical downloads read the saved bytes and original timestamp. Reopening, notes, fresh evidence, and subsequent closure append records while preserving prior versions and their evidence, reports, notes, and timestamps. Enforce historical immutability in the repository and with SQLite protections against ordinary updates and deletes.

### Future analyst feedback and case memory

Stable case, snapshot, assessment, and evidence IDs provide provenance for future case memory. Manual reviews capture quality and rationale against the exact output the analyst saw. Future reuse should use analyst-approved, redacted material and follow the applicable access and retention rules. v0.5 scope ends at manual feedback capture and historical inspection. Retrieval-augmented generation, model training, and feedback automation are deferred.

Case Management records explicit verdict changes and optional output ratings as distinct events on new snapshots. Rating labels are self-entered and optional. Saved model runs are registered with the snapshot containing the output. A legacy output without an assessment row can be reviewed from the latest saved snapshot. Its first explicit rating registers it on the new review version without backfilling earlier history or inventing model metadata.

### Security and retention

- Keep the database and any SQLite sidecar or backup files in a directory accessible only to the analyst account. Use the host's encryption and backup controls for sensitive data at rest. Keep Gemini credentials in the existing environment-based configuration and out of persisted state and reports.
- Treat archive as a lifecycle status. Before rollout with real incident data, define retention for case history, screenshots, SQLite sidecars, and backups. A separate purge workflow can enforce that policy across historical versions and evidence.
- Keep the existing Gemini submission boundaries and evidence review UI. Avoid persisting transient exception strings, widget state, or authorization checkboxes. Limit the v0.5 deployment to a trusted local environment. Shared analyst access would require authentication, per-case authorization, and a deployment-specific storage review.

## Implementation sequence and verification

1. Add schema initialization, migrations, explicit state serialization, and transactional repository operations. Test with temporary databases for schema upgrades, round-trip fidelity, case isolation, version order, stale-write rejection, and rollback after a failed evidence insert.
2. Add case controls to the wizard. Use a table-driven repository test for every allowed and rejected transition, including archive restoration, reopening from both closure statuses, and resuming from `ON_HOLD`. Use Streamlit `AppTest` to verify restored progress, available actions by status, case switching, and rerun idempotency.
3. Integrate prepared screenshots and assessments. Test evidence ordering, hash and provenance round trips, deduplication, reopening after Ticket Lab source removal, fingerprint invalidation, and renewed consent. Use mocked Gemini clients to verify that a response cannot be applied after another session changes the inputs.
4. Test that closure preserves all four verdict values and existing AI reviews, including resolved benign cases and inconclusive closures with a malicious verdict. Verify that changing a verdict or manually rating an assessment leaves lifecycle status intact and that a fresh assessment starts unreviewed. Verify that report status remains independent of lifecycle.
5. Test that hold, resume, closure, reopen, archive, restore, and subsequent edits preserve prior snapshots, screenshot bytes and provenance, issued report bytes, original UTC timestamps, and notes. Verify that note corrections and review revisions preserve their predecessors and that the database rejects ordinary history updates and deletes. Run `python -m unittest discover -v` and check the script-style examples separately as appropriate.

The existing baseline includes 11 discoverable tests in `test_inc_27517.py` and `test_ticket_lab_integration.py`. They cover regression triage, IOC handling, image preparation, screenshot attribution, stale reassessment, wizard handoff, consent, exports, and Gemini failure. `test_rules.py`, `test_severity.py`, `test_ioc.py`, and `test_report.py` are script-style examples.

Implementation is pending approval. This document records the proposed design.
