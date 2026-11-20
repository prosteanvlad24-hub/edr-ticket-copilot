# Phase 4D investigation data protection

## Status

Implementation is in the working tree on `feature/case-management`. The working tree was clean at the start of Phase 4D. The follow-up corrected the two AppTest interaction errors and removed the Streamlit widget-state warning. The full automated suite passes.

## Case replacement

- `case_management_ui.py` compares the live investigation's durable checkpoint and manual draft with the saved baseline, or with a default investigation when no case is open. Opening a case or requesting a New Case proceeds directly if the current investigation is clean. A dirty investigation records the intended operation and displays Save, Discard, and Cancel. Lifecycle and history controls are hidden while that decision is pending.
- Save persists the current investigation before opening or creating the destination. An investigation without a saved case requires a separate title. A stale write or storage failure cancels the switch and keeps the live draft. If saving succeeds but the destination later fails to open or create, the current investigation remains selected and saved. These are separate repository operations.
- Discard applies only to the explicit replacement request. Cancel clears that request and keeps the current investigation. Returning to the wizard also clears the pending request. Reloading a stale case with local edits requires an explicit discard. Successful activation rotates the widget namespace and drops any pending Gemini intent. Gemini's existing request and response version checks are unchanged.
- `dashboard_v1_2.py` captures manual draft fields in widget callbacks so changes sent in the same run as sidebar navigation reach the durable in-session investigation.

## Ticket Lab evidence replacement

- `dashboard_v1_2.py` uses the existing public Ticket Lab reader to load the complete candidate. The reader checks manifest and ticket data, filenames, and image limits and decodes the screenshots. The accepted selection and evidence are updated only after the read succeeds. Changing the evidence source to Ticket Lab also loads the candidate before activating that source.
- On failure, the picker restores the accepted selection where the options still contain it. The warning is transient and sanitized. The existing screenshot bytes, provenance, fingerprint, and reassessment remain available. The failed attempt does not change the encoded checkpoint or create a new SQLite version. A successful replacement follows the existing reassessment invalidation and checkpoint behavior.
- No schema, repository, serialization, deployment, or baseline audit changes were made. The test database was disposable, and a guard rejected live Gemini client creation while test-local mocks supplied responses. The real database, historical reports, and immutable snapshots were left untouched. The full test discovery did refresh the pre-existing, Git-ignored `EDR_Incident_Report_Test.md` fixture output through an existing test.

## Automated verification

The follow-up full suite on Streamlit **1.67.0** ran **41 tests in 48.740 seconds**. **41 passed, 0 errors, 0 failures, 0 skipped.** The run used disposable SQLite data, a guard against live Gemini and a temporary working directory for generated test output. `git diff --check` passed.

| Scenario | Result |
| --- | --- |
| Dirty Open Case waits for a decision, Cancel keeps the draft, and Save advances only the original case before opening the destination | Passed |
| Explicit Discard isolates drafts and clears prior Gemini consent when reopening evidence | Passed |
| Concurrent update rejects a pending switch save, retains the dirty draft, and requires explicit discard to reload | Passed |
| Missing, corrupt, malformed, and unreadable candidate evidence retains the live selection, reassessment, and saved version. A later valid replacement advances exactly one version | Passed. The widget-state warning did not recur |
| Dirty New Case with Cancel, Save and Discard | Passed |
| Simulated storage failure prevents creating the requested New Case and preserves the old draft | Passed |
| Existing lifecycle, report history, evidence restoration, localhost configuration, Gemini consent, and safe rendering regressions | Passed |

## Root causes and fixes

- **New Case test errors.** The initial suite had 39 passes and two AppTest errors. In both errored tests, setting the title queued an input change, and the test clicked the button on the previous page snapshot while it was still disabled. The interaction sequence now submits the title and reruns the app before clicking. The original storage and navigation assertions remain in place. No production change was needed for New Case.
- **Ticket Lab rollback warning.** The callback restored the accepted value in session state while the widget also declared a nonempty default. Streamlit flagged the two initialization sources. The original data-preservation assertions passed, so the warning did not indicate a SQLite or evidence-consistency failure. The picker and source radio now initialize their keys through session state alone. On failure, the callback can restore the accepted selection without a competing widget default. The regression asserts that the application warning remains visible and Streamlit's session-state warning is absent.

## Headless Chrome verification

Chrome drove the actual Streamlit 1.67.0 server on `127.0.0.1` with a temporary database and synthetic Ticket Lab run. Gemini was mocked at client construction. The browser made no submission.

- **New Case and Save, Discard, Cancel.** Cancel created no destination. Save persisted the original draft under its own title before entering the new case. Discard entered the destination without saving the abandoned edit. The database was checked after each decision.
- **Failed and stale saves.** A launcher-injected storage error kept the current draft and prevented creation of the destination. A competing repository write after the prompt opened caused the stale save to fail visibly, kept the unsaved text available in the wizard, and left the competing write intact. The competing write was driven through the repository for repeatability.
- **Open Case and Gemini authorization.** The browser opened a saved case at the evidence step, checked its authorization box without submitting, navigated away and reopened the case. The box was clear on reentry. AppTest separately covered switching to a different case and back and the dirty Open Case Save/Cancel flow.
- **Invalid Ticket Lab evidence.** Chrome selected a missing screenshot alongside the saved screenshot. The application showed its sanitized warning, restored the selection, kept the reassessment visible, and left the saved case at the same row version. The server did not log the Streamlit initialization warning.

Browser checks used a desktop viewport. Narrow-screen layout, a complete keyboard-only decision flow, and two independent browser windows were outside this run. The browser exercised a missing file while Ticket Lab was active. The automated checks covered corrupt, malformed, and unreadable candidates, and verified that a later valid replacement advances one version.

## Changed files

- `case_management_ui.py` for dirty-state detection, confirmation, and safe activation.
- `dashboard_v1_2.py` for draft capture and validated evidence replacement.
- `test_case_management_ui.py` for the Phase 4D regressions and explicit discard expectations.
- `V05_PHASE4D_IMPLEMENTATION_REPORT.md` for this report.
