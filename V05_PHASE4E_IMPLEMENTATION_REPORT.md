# Phase 4E analyst decisions and release documentation

Phase 4E addresses M4, M5, L1, and L2 on `feature/case-management`. The working tree was clean before implementation. The baseline audit is preserved.

## Decision and lifecycle contract

- **Incident verdict** records an explicit case-level choice of `NOT_ASSESSED`, `MALICIOUS`, `BENIGN`, or `INCONCLUSIVE`. Saving a different verdict appends a snapshot and leaves lifecycle and AI reviews unchanged. The case and version identify the event. The app has no verified actor identity to record.
- **AI assessment quality** rates one saved response as `CORRECT`, `PARTIALLY_CORRECT`, `INCORRECT`, or `NOT_REVIEWED`. The form shows the exact saved output as literal text. Each new rating starts with blank optional reviewer-label and rationale fields and requires an explicit rating choice. The reviewer label is self-entered. A quality rating does not verify evidence, turn an AI conclusion into an analyst conclusion, or set a verdict.
- **Lifecycle** starts in the canonical database status `DRAFT`. Submission advances to `IN_PROGRESS`. Hold, resume, both closure outcomes, reopening, archive, and restore use the existing transition matrix and reason rules. `OPEN` remains unsupported. Archived decisions remain visible, and recording new ones requires restoration. No schema, payload version, migration, or reinterpretation of historical values was introduced.

## Persistence and history

- Decision actions target the saved case and expected row version. They use the existing SQLite write transaction and append-only version mechanism. An identical resubmission does not advance the row. The UI refreshes matching active case metadata while retaining unsaved wizard edits. A stale decision is rejected with a message to review the latest version.
- The repository registers saved AI outputs in the existing assessment table. A successful Gemini request in a saved case registers a fresh assessment even when its text is identical to an earlier response. Registration and the case version commit together after the existing stale-response check. A new assessment starts `NOT_REVIEWED`. No provider identifier is inferred for stored output.
- An unregistered legacy response can be explicitly rated starting from the latest saved snapshot. The review transaction registers it at the new version. Historical snapshots retain their original output and review records as of the version inspected. Responses generated in an unsaved session can be registered when first persisted, while earlier unsaved runs have no case history.
- Newly issued reports use the saved verdict and assessment-quality metadata. Exports keep the existing quality metadata shape and omit optional reviewer labels and rationales. Historical report bytes and immutable snapshots remain untouched.

## Verification

- **Automated suite after the attribution fix:** 46 passed, zero failures, errors, or skips, in 62.983 seconds on Streamlit 1.67.0. The runner used disposable SQLite data, a temporary working directory, and a live-Gemini guard with test-local mocks. Installed companion versions were google-genai 3.5.0, python-dotenv 1.2.4, Pillow 13.0.0, and tldextract 5.4.0. The suite does not certify every version in the declared ranges.
- **Regression coverage:** Verdict and quality independence, immutable history, identical no-op reviews, stale reviews, distinct IDs for identical reruns, legacy schema and output review, unsupported `OPEN`, restoration, keeping the live draft during feedback, and no Gemini call during feedback. The existing Phase 4A–4D tests stayed green.
- **Repository checks:** `git diff --check` passed. The real database, baseline audit, historical snapshots, and issued reports were untouched.

### Reviewer-attribution correction

Pre-commit review found that the rating form initialized the optional label and rationale from the last saved review. Changing only the rating could therefore copy an earlier reviewer's label and reasoning into the new history entry. The form now starts with four visible rating choices, none selected, and blank optional fields. It clears on submission and displays the prior review in a separate read-only section. Submitting without a rating produces a validation message and no version. The repository still receives only the current submission's values and checks the expected case version before appending. The correction changes neither the schema nor prior records.

Two AppTest regressions cover consecutive reviews under different labels, a completely untouched submission, a changed rating with both optional fields left blank, switching cases and responses, and a stale submission after a replacement response was saved. They verify the unchanged incident verdict, review events and assessment IDs, and restore the earlier labels and rationales from their original versions.

## Browser QA

Headless Chrome ran against a loopback-only Streamlit server with disposable case databases and mocked Gemini. The browser saved a benign verdict and a partially correct evidence-reassessment rating with a self-entered reviewer label. SQLite returned both decisions. The historical snapshot showed the earlier verdict, and opening the case restored the evidence step.

An initial combined run clicked Archive before the Reopen rerun had settled. A dedicated lifecycle run waited for the committed version and its rendered header after each action. Hold, Resume, Close Inconclusive, Reopen, Archive, and Restore all passed. The browser showed that archived cases require restoration before recording decisions. The restored case was in progress with its prior verdict and rating intact. Close Resolved was covered by the automated transition tests.

The attribution follow-up verified two consecutive reviews of the same assessment in headless Chrome. The first included a label and rationale. The second started with blank inputs, used a different label, and left the rationale blank. SQLite stored the two reviews in consecutive versions under the same assessment ID, preserved the first review as originally saved, and stored no rationale for the second. The form opened blank again after the second save.

## Remaining limits

- Local SQLite constraints and SHA-256 verification detect ordinary app-level changes or mismatches with stored provenance. The database and its recorded hashes share a trust boundary. They provide no independently authenticated forensic integrity, tamper-proof audit trail, or verified analyst identity.
- The release docs recommend a protected local data directory, backups, and restore verification against a separate database. A fresh dependency installation, full backup drill, and mobile browser matrix were outside this verification.
- Feedback is local and manual. Model attribution is limited to available stored data. No feedback automation, retrieval, training, authentication, or remote deployment was added.

## Changed files

| Files | Role |
| --- | --- |
| `case_repository.py` | Versioned decisions, assessment identities, legacy review registration, and optimistic concurrency. |
| `case_history_ui.py` | Separate analyst forms, saved decisions, versioned display, and report metadata projection. |
| `case_management_ui.py`, `dashboard_v1_2.py` | Register saved Gemini responses within the existing optimistic checkpoint flow. |
| `test_case_repository.py`, `test_case_management_ui.py` | Decision, legacy, lifecycle, draft, and historical-view regressions. |
| `README.md`, `WIZARD.md`, `V05_ARCHITECTURE_PLAN.md` | Local launch, dependencies, storage, consent, testing, lifecycle, and integrity boundaries. |
| `V05_PHASE4E_IMPLEMENTATION_REPORT.md` | Implementation and verification record. |
