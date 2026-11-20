# EDR Ticket Copilot v0.5 Phase 4C implementation report

## Scope and outcome

Phase 4C addresses [H4](V05_RELEASE_READINESS_AUDIT.md#L61) and [M3](V05_RELEASE_READINESS_AUDIT.md#L93). The starting tree was clean on `feature/case-management` at `009fa0f`. The changes distinguish model assessments from analyst verification, render untrusted content literally, and replace raw exception details with safe diagnostic notices.

The implementation retains Phase 4A’s loopback bind and Streamlit 1.67.0 minimum, along with Phase 4B’s single-use authorization, stale-session preflight, and optimistic response publication. It uses the existing SQLite schema and keeps earlier case snapshots and issued report bytes intact. No analyst verification is recorded automatically. Phase 4D was outside scope.

## Trust boundaries and rendering decisions

| Surface | Source and presentation |
| --- | --- |
| Ticket entry, sample library, sidebar identity, and Ticket Lab display | Ticket descriptions, sample labels, and incident values use native text inputs or plain text. The existing application-owned stage and metric HTML escapes substituted values. |
| Initial Findings and Final Report summary | Gemini validation, initial findings, recommendations, evidence requests, and clarification messages are labeled unverified and displayed as text. Local triage is identified separately, and candidate IOCs use literal code display. |
| Screenshot reassessment | The supplied screenshots remain prepared image bytes. Model conclusions, observations, confidence, hypotheses, and evidence requests are plain text or escaped metric values. Hypothesis expander headings come from fixed labels with indexes. A valid screenshot ID establishes attribution. Analysts still need to check the claim against the image. |
| Case History | Stored AI validation, initial output, and evidence reassessment are visibly unverified. Structured snapshot output is shown as literal JSON text. Analyst notes, the recorded incident verdict, and recorded AI assessment quality remain separately labeled. Snapshot and image integrity checks concern stored data integrity. |
| Report preview and new downloads | The wizard uses a literal code preview. New Markdown exports retain an application-owned structure and put dynamic values in indented code blocks or code spans with delimiters longer than embedded backtick runs. JSON retains the original analysis values as data and includes `analyst_verification_status: "not_recorded"`. |
| Issued report history | The display maps the legacy `evidence_reviewed` storage key to **AI evidence assessment included (unverified)**. Downloads return the original bytes, and the issued Markdown preview reads them as literal code. The UI tells users older downloads can contain legacy wording or active Markdown. |
| Failure messages and logs | The wizard shows fixed summaries and opaque diagnostic references. Controlled failure categories include rate limits, access, configuration, connectivity, and unusable data. Logs carry the operation, category, and reference. Provider exception strings, payloads, and traceback details are excluded from those app diagnostics. External file and generation failures, analyst-note errors, and user-facing CLI and driver errors use the same boundary. |

The model’s `Confirmed` value can still be inspected when paired with a recognized screenshot ID. In that case, the UI and report explicitly call it an unverified AI conclusion. Fabricated screenshot IDs remain unattributed. The existing downgrade for a claimed confirmation with no recognized citation remains, with wording limited to the citation check. Incident verdict, AI assessment quality, and lifecycle status remain independent of evidence verification.

New evidence-assessment JSON exports use `ai_evidence_assessment_unverified` for `report_status`. Preliminary reports keep `preliminary`. The pre-existing SQLite enum retains `evidence_reviewed` as an internal storage key to avoid a migration. It does not label new user-facing output.

## Changed files

| Files | Change |
| --- | --- |
| [presentation_safety.py](presentation_safety.py), [investigation_state.py](investigation_state.py) | Shared trust wording, literal Markdown helpers, safe diagnostic generation, and transient failure notices. No persisted state fields changed. |
| [dashboard_v1_2.py](dashboard_v1_2.py), [case_history_ui.py](case_history_ui.py) | Unverified trust labels, literal output, safe diagnostics, and compatible historical-report presentation. |
| [evidence_engine.py](evidence_engine.py), [report_engine_v2.py](report_engine_v2.py) | Citation-only semantics, unverified report status, and inert dynamic Markdown fields. |
| [ai_engine.py](ai_engine.py), [ticket_validator.py](ticket_validator.py), [check_models.py](check_models.py), [drive_streamlit.py](drive_streamlit.py) | Sanitize user-facing exception output from supported command-line entry points. |
| [test_case_management_ui.py](test_case_management_ui.py), [test_inc_27517.py](test_inc_27517.py), [test_ticket_lab_integration.py](test_ticket_lab_integration.py) | Add or update regressions for attribution, prompt injection, literal rendering, diagnostic redaction, and report compatibility. |
| [WIZARD.md](WIZARD.md) | Document report trust and rendering behavior. |
| `V05_PHASE4C_IMPLEMENTATION_REPORT.md` | Record implementation, verification, and remaining QA. |

## Verification and regressions

- **Full automated suite:** 37 passed, 0 failures, 0 errors, 0 skipped on Streamlit **1.67.0**. The tests ran with disposable SQLite data and a live-client guard. The existing Phase 4A and 4B regressions remained green.
- **Attribution and trust:** A mocked `Confirmed` response with a valid screenshot citation and unrelated supporting observation retains the model’s value while the wizard, snapshot view, and reports remain unverified. The fabricated-ID regression checks that an unrecognized citation remains unattributed and the existing downgrade applies. The prompt-injection regression verifies separation between untrusted incident data and fixed instructions.
- **Literal display and reports:** Adversarial ticket and model text included an external image, a misleading link label, raw markup, a code-fence delimiter, and a fake analyst-verification heading. Tests check literal UI presentation, safe Markdown boundaries, the JSON verification flag, and exact preservation of legacy report bytes and prior snapshots. Newly issued reports were also checked through the existing repository path.
- **Diagnostics:** All three mocked Gemini actions returned an HTTP 429 exception containing a synthetic secret and external image URL. Tests checked the safe rate-limit message, matching log reference, and absence of the raw values from application output, diagnostic logs, and restored investigations. Fresh authorization was still required for any retry.
- **Headless Chrome:** With a temporary SQLite database, a loopback-only server, Gemini blocked and external browser traffic intercepted, Findings, Evidence, and Final Report rendered the fixture literally. Chrome showed the unverified labels, found zero active fixture links, images, or frames, and recorded zero fixture-triggered external requests.

## Remaining limitations and manual browser QA

- This phase adds no structured analyst verification workflow. Analyst notes and recorded verdicts are separate records and do not promote a model response to verified.
- Legacy issued exports remain byte-for-byte historical artifacts. The in-app preview is literal. Downloaded legacy Markdown can retain active syntax if opened in another viewer. Downstream consumers of new JSON should account for the clarified evidence-report status value.
- The Chrome check covered desktop wizard views. Manual browser QA should verify narrow-screen wrapping and copyability of long literal output, inspect an older issued report in Case History, and compare its downloaded bytes to the stored original. Rendering new downloads in third-party Markdown viewers and terminal behavior of the optional command-line entry points were outside the browser check.
- Phase 4B’s optional browser-driver checkbox limitation remains separate from the native wizard. Driver interaction was outside this phase. The diagnostic change affects the safe failure text it records.

The real SQLite database, historical issued bytes, and the baseline audit document were left untouched. No live Gemini calls, commits, pushes, merges, or tags were made.
