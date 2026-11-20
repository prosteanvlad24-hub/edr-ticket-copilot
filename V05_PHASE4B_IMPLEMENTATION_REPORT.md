# EDR Ticket Copilot v0.5 Phase 4B implementation report

## Scope and status

Phase 4B addresses H3 in the [release readiness audit](V05_RELEASE_READINESS_AUDIT.md#L51). The starting tree was clean on `feature/case-management` at `7906d3c`. The implementation adds fresh authorization and version checks to the supported Google Gemini paths. It uses the existing schema, row-version checks, investigation data, and snapshot format. H4 and Phase 4C remain outside this change.

The full automated suite passed on Streamlit 1.67.0 with a disposable database and mocked Google Gemini clients. The initial Chrome attempt stopped before app startup because of a launcher quoting error. The [browser QA addendum](#browser-qa-addendum) records the successful rerun of the native wizard and a confirmed limitation in the optional browser driver.

## Authorization state machine

1. **Awaiting authorization.** Each eligible action renders its own unchecked confirmation and submit button. The form identifies Google Gemini and the categories included in that action’s outbound request. A new render uses a new widget identity. Local analysis runs separately.
2. **Submitted.** The form callback captures the submitted checkbox and the scope shown when the form rendered. The scope contains the action, a digest of the ticket text or the existing evidence fingerprint, and the active saved case ID and row version if available. For screenshots, the fingerprint covers the selected evidence, ticket, and prior validation.
3. **Consumed.** The entry point removes the attempt from Streamlit session state before rendering any view. Only a true confirmation whose action and scope still match can enter the provider path. Submitting unchecked or submitting after the payload or saved scope has changed calls no provider. Navigation and unrelated reruns cannot carry the previous confirmation into a new form. Authorization is transient and excluded from SQLite and report exports.
4. **Checked and attempted.** The provider engine calls the authorization callback immediately before its `generate_content` invocation. Each engine makes one SDK generation attempt with retries configured to one attempt and no automatic fallback across models. The confirmation is spent even if payload validation, SQLite preflight, client setup, the provider, or response decoding fails. A retry requires a new confirmation.
5. **Published or discarded.** A successful saved-case response passes the repository’s optimistic save before it updates the live investigation. An unsaved session applies the response to its in-memory investigation and has no SQLite row to check.

The earlier full-analysis button combined local analysis with two Gemini submissions. Step 2 now exposes local analysis, ticket validation, and initial Gemini analysis separately so the analyst can authorize each outbound submission. Step 4 retains screenshot review before the evidence submission form.

## Gemini call paths and disclosures

| Entry point | Payload shown to the analyst | Authorization behavior |
| --- | --- | --- |
| Step 2 **Validate ticket request** | Committed ticket text. Separate asset criticality, offline hours, endpoint count, local findings, screenshots, and other case evidence are excluded. | Individual form, one structured validation request. |
| Step 2 **Gemini AI analysis** | Committed ticket text, with the same exclusions as validation. | Individual form, one initial analysis request. |
| Step 4 **Analyze Evidence & Reassess** | Committed ticket text, selected prepared screenshot bytes, application-assigned screenshot IDs and source labels, and prior AI ticket validation when present. Separate asset context, local findings, filenames, hashes, and other evidence are excluded. | Individual form bound to the screenshot fingerprint. Evidence must be available for submission. |
| `ai_engine.py` and `ticket_validator.py` sample commands | Sample ticket text under the ticket disclosure. | Terminal confirmation for the single request. Programmatic engine callers provide an authorization callback. |
| `evidence_engine.py` library API | Prepared screenshots, ticket text, screenshot IDs and source labels, and public prior validation where present. | Requires the caller’s authorization callback. Its module entry point prints guidance. |
| `check_models.py` | Google Gemini model catalog metadata on the first page. The command sends no case data. | Terminal confirmation before the first-page lookup. Reading the returned page avoids automatic pagination. |
| `drive_streamlit.py` | The current wizard form’s own disclosure, shown to the operator at the terminal. | Prompts before each form submission. The driver targets the current five-step wizard. |

Local rules, IOC extraction, case history, restores, reports, and synthetic Ticket Lab generation contain no built-in Gemini submission path. Ticket Lab’s optional shell analyzer delegates to an operator-supplied program. Its behavior is outside the wizard consent boundary. Local legacy dashboard copies are ignored by Git and outside supported entry points. The engines require an authorization callback, so old calls without that argument fail before sending.

## Saved-case concurrency and state preservation

- The form is bound to the saved identity and version visible when it rendered. Local checkpoints can save changed inputs before subsequent forms are rendered. The repository preflight then reads the current SQLite row version immediately before the SDK submission. A stale or missing case enters the existing conflict flow and sends no case data. Database read failures also prevent submission.
- The preflight transaction ends before the network request. The app holds no database write lock across an external call. On response, it applies changes to a copy and submits that copy through the existing expected-version checkpoint. Only a successful checkpoint updates the live investigation. A concurrent edit rejects publication without replacing the newer row, the prior snapshot, or the live session’s previous findings and evidence.
- Successful response handling keeps existing validation and evidence-fingerprint invalidation rules. A successful no-op still goes through the expected-version check. Provider errors remain transient, and the existing local analysis and report paths remain available.

## Files changed

| File | Change |
| --- | --- |
| [dashboard_v1_2.py](dashboard_v1_2.py) | Action-specific forms, per-render identities, scope validation, intent consumption, and separate local and remote actions. |
| [case_management_ui.py](case_management_ui.py) | Saved-case preflight and staged response publication via the existing checkpoint. |
| [case_repository.py](case_repository.py) | Read-only current-version assertion using the existing `cases.row_version`. |
| [gemini_authorization.py](gemini_authorization.py) | Shared payload disclosures and interactive terminal confirmation. |
| [ai_engine.py](ai_engine.py), [ticket_validator.py](ticket_validator.py), [evidence_engine.py](evidence_engine.py) | Require an authorization callback at the provider boundary and make one generation attempt. |
| [check_models.py](check_models.py) | Disclose metadata lookup scope, prompt, and read only the returned first page. |
| [drive_streamlit.py](drive_streamlit.py) | Use separate wizard forms and require operator confirmation per send. |
| [WIZARD.md](WIZARD.md) | Explain separate actions, retry confirmation, and the driver workflow. |
| [test_case_management_ui.py](test_case_management_ui.py), [test_ticket_lab_integration.py](test_ticket_lab_integration.py), [test_inc_27517.py](test_inc_27517.py) | Add mocked consent and concurrency regressions and migrate existing workflow tests to the new forms. |
| `V05_PHASE4B_IMPLEMENTATION_REPORT.md` | Record implementation and validation. |

## Test coverage and results

- The four new AppTest cases exercise **all three** wizard Gemini actions. They check that an unchecked form, an unrelated rerun, or a repeat without fresh confirmation produces zero new sends. They compare disclosures with the intercepted request data, including screenshot bytes, prior validation, and evidence IDs. Mocked provider rate-limit errors prove authorization is consumed and no fallback sends occur. Concurrent tests assert zero sends for an already-stale session and reject both live and durable publication when the case is modified inside the mocked provider request.
- Existing tests still cover synthetic and manual evidence, consent isolation on case switching, local analysis after provider failures, evidence provenance, report downloads, lifecycle, stale writes, and immutable history. Provider clients were mocked or blocked and test artifacts were confined to disposable directories.
- **Full suite:** 36 passed, 0 failures, 0 errors, 0 skipped, using the project’s Streamlit **1.67.0** environment. Python source parsing and `git diff --check` also passed.
- **Initial Chrome smoke attempt:** The temporary mock-server launcher interpolated a newline into its nested Python command string and failed with `SyntaxError: unterminated string literal` before the server started. The later browser checks are recorded below.

## Remaining limitations

- A case can change between the preflight read and actual transport dispatch. The app detects an intervening change at optimistic save time and discards the result. It cannot retract a request that has already left the host.
- Each attempt uses the previously preferred Gemini model. An unavailable model or provider failure requires the analyst to authorize a retry. Automatic fallback would require a separate authorization path for each additional submission.
- The CLI entry points and live model catalog remain unverified end to end. The optional browser driver’s checkbox activation limitation is documented below. Verification uses mocked provider calls.
- Consent is intentionally transient. This phase adds no persisted approval history, schema migration, model-output verification, or change to the case lifecycle.

The real SQLite database and audit baseline were left untouched. No live Gemini calls, commits, pushes, merges, or tags were made.

## Browser QA addendum

The test harness replaced the nested launcher command with a syntax-checked Python file in a temporary directory. The launcher ran the project’s Streamlit 1.67.0 environment against a disposable SQLite database and replaced the Google Gemini client with a deterministic mock. Windows socket inspection confirmed `127.0.0.1` was the only listener on each test port. Headless Chrome used synthetic ticket text and a generated PNG, with non-loopback browser requests blocked. This verification changed no application, configuration, dependency, or test-suite files.

| Check | Result |
| --- | --- |
| Ticket validation | Passed. The form visibly disclosed Google Gemini, committed ticket text, and excluded context and evidence. The intercepted payload contained only `ticket_description`. |
| Initial AI analysis | Passed. The form showed the same ticket-only disclosure, and the intercepted payload contained only `ticket_description`. |
| Screenshot reassessment | Passed. The form disclosed the committed ticket, selected prepared screenshot bytes, screenshot IDs and source labels, and prior AI validation when available. The intercepted request contained one PNG, the ticket, application-assigned ID and source, and prior validation. |
| Fresh authorization on each action | Passed for all three. A submit with the checkbox clear made zero calls. A confirmed success and a confirmed simulated HTTP 429 each made exactly one mocked call. Both outcomes reset the checkbox. An unchecked repeat made zero additional calls. The combined three-action flow made six mocked calls. |
| Open and reload | Passed. A hard reload followed by opening the saved case restored the screenshot and saved reassessment with consent clear. Checking consent without submitting, then leaving and reopening the case, also cleared it. Neither path called the mock. |
| Concurrent browser sessions | Passed for screenshot reassessment in two separate Chrome contexts. Both opened the same saved version. The first context advanced to Final Report and saved a newer version. The second context confirmed and submitted its older evidence form, received the version-conflict message, and made zero mock calls. The first context’s newer version remained current. |
| View continuity | Passed. The wizard, Case Management, and a read-only history snapshot were accessible. Returning from history restored the saved Final Report step. History inspection created no case version and made no provider calls. |
| Full automated suite rerun | **36 passed, 0 failures, 0 errors, 0 skipped** on Streamlit 1.67.0. The automated suite also covers stale preflight and changes during a request for all three Gemini actions. |

### Confirmed browser-driver limitation

The optional `submit_gemini` helper in `drive_streamlit.py` timed out after terminal confirmation because Playwright’s direct checkbox `.check()` clicked the underlying input and Streamlit’s visible label intercepted the pointer event. The helper stopped before the provider mock recorded any call. Clicking the visible label in the native Chrome wizard worked. This QA pass records the driver defect for review and leaves its source unchanged. [drive_streamlit.py:50–56](drive_streamlit.py#L50-L56)

The two-session browser check exercised an already-stale evidence form. Changes during an in-flight request were verified through mocked AppTest, and the live provider, standalone CLI, and other browsers were outside this QA run. The real SQLite database and audit baseline were left untouched. No commit, push, merge, or tag was made, and Phase 4C was not started.
