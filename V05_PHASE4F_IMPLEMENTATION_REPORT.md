# Phase 4F final audit remediation

Phase 4F addresses the three additional findings from the final v0.5 audit. Work started on the clean `feature/case-management` branch at `ce40048`. The baseline audit, schema, production database, and existing issued artifacts were preserved.

## Findings and changes

| Finding | Root cause | Remediation |
| --- | --- | --- |
| Medium · Rejected manual evidence clears the current investigation | The upload exception handler set an empty manual evidence record. The state setter invalidated the reassessment, and the next checkpoint persisted the cleared evidence. | Validate and prepare the full candidate before changing the accepted evidence. Keep a sanitized failure notice in transient uploader state. An empty uploader leaves accepted evidence in place. **Clear uploaded screenshots** remains the explicit removal action. |
| Medium · An issued report can show an older rating beside a newer response | Issuance passed the case's assessment ledger to the exporter without identifying which registered response was displayed. | Resolve the displayed assessment IDs from the exact saved version used for issuance. Markdown puts the ID, response version, quality, and review version beside the corresponding output and places superseded records in a historical section. JSON adds a module-keyed `displayed_ai_assessments` map and a `scope` field on existing ledger rows. A displayed legacy output without a registered assessment has a null ID and explicit `NOT_REVIEWED` status. Earlier issued bytes are served unchanged. |
| Low · Read-only navigation creates a false dirty prompt | The wizard wrote the viewing step into the persisted investigation object even when editing was disabled. | Keep read-only viewing position in the case's transient widget namespace. Editable wizard progress still checkpoints. Case activation clears the old namespace. Existing dirty detection still sees genuine unsaved state from before a conflict. |

## Regression coverage

- Manual evidence tests reject a bad upload and a mixed batch, preserve accepted bytes, provenance, saved reassessment and row version, then verify a successful replacement and an explicit clear. A Pillow-generated PNG provides the valid candidate.
- Report tests issue a report with two distinct assessment IDs for identical response text. They verify that Markdown and JSON show the current response as `NOT_REVIEWED`, the earlier `CORRECT` rating as historical, and the old report remains byte-exact.
- Navigation tests exercise archived Next and Back, switching without a prompt, removal of the transient step on activation, and re-opening at the saved step. The stale-session regression confirms that read-only movement does not mutate the draft's persisted step and that genuine edits still require a decision before replacement.

## Verification results

- The final full suite passed **49 of 49 tests** on Streamlit **1.67.0** in 100.931 seconds, with zero failures, errors, or skips. The runner used a temporary working directory and disposable SQLite data. A live-Gemini guard and the existing test mocks covered provider paths. Initial failures traced to a PNG fixture with a bad checksum and AppTest retaining a formatted case-picker value after switching. The final tests used a generated PNG, asserted removal of the old viewing key, and reopened the archived case in a fresh session.
- **Chrome manual evidence:** The browser submitted a malformed PNG. The warning appeared, the original screenshot and reassessment stayed visible, and the database record remained byte-for-byte equivalent. A browser attempt to add a valid file while the bad file remained queued correctly rejected the mixed batch. Valid replacement and explicit removal passed in AppTest.
- **Chrome report issuance:** The browser issued a report after an older `CORRECT` response had been replaced. Inspection of the resulting SQLite artifacts confirmed the current ID and `NOT_REVIEWED` rating in both formats, isolation of the older rating in history, and exact preservation of the earlier issued Markdown.
- **Chrome archived navigation:** A fresh session opened the archived case, advanced from wizard step 2 to step 3, then opened another case without a dirty prompt. The archived snapshot and row version remained unchanged.
- `git diff --check` passed. Browser runs used a loopback-only server, a disposable database, and mocked Gemini. No live calls or Git history changes occurred.

## Changed files

- `dashboard_v1_2.py` for transactional manual evidence replacement in session state and transient read-only wizard navigation.
- `case_history_ui.py` and `report_engine_v2.py` for version-specific report linkage and separate historical ratings.
- `test_case_management_ui.py` for the focused regressions.
- `V05_PHASE4F_IMPLEMENTATION_REPORT.md` for this record.

## Remaining limits

- Browser QA uses desktop headless Chrome and synthetic data. Mobile layout, other browsers, live Gemini, and third-party Markdown viewer behavior are outside the run.
- Rejected files can remain visible in the browser uploader queue until removed. The accepted evidence preview and warning describe the active investigation state.
- Existing issued reports retain their original content. Legacy outputs without a registered assessment remain unreviewed until the analyst explicitly records a review.
