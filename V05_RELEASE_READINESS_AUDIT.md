# EDR Ticket Copilot v0.5 release readiness audit

## Executive summary

**Recommendation: NO-GO for a public v0.5 release.** The SQLite foundation passed targeted, file-free checks. The release blockers are the default network exposure of a single-analyst app, an incompatible advertised Streamlit minimum, and gaps in Gemini submission consent and evidence-verification language. Two routine UI actions can also lose current investigation work.

The audit verified a clean working tree on `feature/case-management` at `178d066` before and after inspection. It reviewed all three commits after `v0.4.0`: `62ad4bb` for SQLite persistence, `23df818` for the case-management workspace, and `178d066` for history and audit. The audit changed and created no files, made no live Gemini calls, accessed no secret values, and left the real database untouched. This document records the prior audit without rerunning it.

### What passed

- **Persistence and audit integrity.** The repository initializes SQLite transactionally, enables foreign keys on its connections, checks expected row versions, and uses immutable version rows with separate append-only notes and reports. Evidence reads verify the stored bytes against their SHA-256 and snapshot provenance. Serialization excludes outbound consent and restores a reassessment only when its fingerprint matches. [Schema protections](case_repository.py#L196) · [Transactions](case_repository.py#L221) · [Evidence loading](case_repository.py#L262) · [Serialization](case_serialization.py#L20)
- **Lifecycle.** The implemented matrix matches the architecture plan. `DRAFT` can move to `IN_PROGRESS`. `IN_PROGRESS` can move to `ON_HOLD` or either closure. `ON_HOLD` and either closure can return to `IN_PROGRESS`. All non-archived statuses can be archived, and restoration returns to the immediate prior status. Hold, closure, and reopening require reasons. The audit request names `OPEN`, which the implementation rejects. That discrepancy needs an explicit release decision. [Status enum](case_repository.py#L19) · [Transition implementation](case_repository.py#L481) · [Architecture plan](V05_ARCHITECTURE_PLAN.md#L42)
- **Read-only verification.** The existing rule, severity, and IOC examples ran without file writes. Synthetic in-memory SQLite checks passed for evidence provenance, valid and invalid transitions, restore and reopen, stale writes, snapshot update rejection, exact issued-report bytes, and note corrections. The full discovery suite was skipped because it creates SQLite and Ticket Lab fixtures and writes a sample report during discovery. Browser behavior, dependency compatibility beyond source inspection, and real Gemini behavior remain unverified in this audit. [Repository fixtures](test_case_repository.py#L26) · [Ticket Lab fixtures](test_ticket_lab_integration.py#L65) · [Sample report write](test_report.py#L41)

## Findings

| Severity | Count |
| --- | ---: |
| Critical | 0 |
| High | 4 |
| Medium | 5 |
| Low | 2 |
| **Total** | **11** |

### Critical

No Critical findings were confirmed within the read-only scope. The network exposure in H1 is a release blocker. Actual remote reachability depends on host networking, firewall, and deployment configuration.

### High

#### H1. The documented launch does not enforce the single-analyst trust boundary

**Evidence status:** Confirmed configuration gap with conditional exposure.

**Reproduction scenario and impact.** Start the app with the README command on a machine whose firewall admits the Streamlit port. The checked-in configuration leaves the bind address unset. The reviewed Streamlit runtime falls back to a wildcard bind, and Case Management queries the shared database without login or case-level authorization. A reachable browser session could access persisted tickets, screenshots, notes, reports, and case actions. The audit did not attempt a remote connection.

**Recommended fix and regression test.** Bind to loopback by default and document local-only use. Require authentication and authorization before supporting remote or shared deployment. In isolated CI, verify the documented launch binds only to loopback and that a synthetic case is unavailable from another interface.

**References:** [README.md:108](README.md#L108) · [.streamlit/config.toml:2](.streamlit/config.toml#L2) · [case_management_ui.py:217](case_management_ui.py#L217) · [Streamlit server address configuration](https://github.com/streamlit/streamlit/blob/1.67.0/lib/streamlit/config.py#L970)

#### H2. The advertised Streamlit minimum cannot render the startup sidebar

**Evidence status:** Confirmed from the dependency declaration and upstream source.

**Reproduction scenario and impact.** Install the allowed minimum, Streamlit `1.49.0`, and launch the wizard. The first navigation container uses `gap="xsmall"`, which is outside the supported values in that release. An environment satisfying the dependency file can fail before rendering the wizard.

**Recommended fix and regression test.** Raise the minimum to the lowest version verified against the complete app, or use APIs supported by the declared minimum. Run startup, navigation, evidence, and audit smoke tests at both the minimum and the release-resolved version.

**References:** [requirements.txt:1](requirements.txt#L1) · [case_management_ui.py:33](case_management_ui.py#L33) · [Streamlit 1.49.0 container source](https://github.com/streamlit/streamlit/blob/1.49.0/lib/streamlit/elements/layouts.py#L153)

#### H3. Screenshot authorization is reusable and stale sessions can send before conflict detection

**Evidence status:** Confirmed control gaps.

**Reproduction scenario and impact.** Authorize and analyze a screenshot, then click **Analyze Evidence & Reassess** again with the same fingerprint. The checkbox remains authorized, contrary to the plan’s fresh acknowledgment requirement. In two sessions, a stale session can also send inputs after another session changes the case. The row-version conflict protects the subsequent SQLite write, after the outbound transfer has occurred. Individual ticket-validation and Gemini analysis actions have weaker payload disclosure than screenshot reassessment.

**Recommended fix and regression test.** Consume screenshot authorization for each send attempt, show the destination and payload scope at every Gemini action, and check the expected case version before sending and again before saving the response. With a mocked client, verify zero sends on rerun, a second click without fresh consent, and an action against an already-stale case. Verify that a mid-request change rejects the response at save time.

**References:** [dashboard_v1_2.py:245](dashboard_v1_2.py#L245) · [dashboard_v1_2.py:499](dashboard_v1_2.py#L499) · [dashboard_v1_2.py:660](dashboard_v1_2.py#L660) · [V05_ARCHITECTURE_PLAN.md:69](V05_ARCHITECTURE_PLAN.md#L69)

#### H4. A valid screenshot citation can make an unsupported AI conclusion look verified

**Evidence status:** Confirmed validation gap.

**Reproduction scenario and impact.** A mocked response returns `Confirmed` and cites a real screenshot ID in an observation unrelated to its conclusion. The app checks that the ID exists and retains `Confirmed`. Any current reassessment also qualifies the report as `Evidence reviewed`, without an analyst verification event. Screenshot IDs establish attribution. They cannot establish that the cited image supports the claim.

**Recommended fix and regression test.** Label these claims as model assessments and reserve verification language for an explicit analyst action. Keep source attribution and hypotheses separate. Test a real ID paired with unrelated support, fabricated IDs, and prompt-injection text in screenshots. Verify the UI and report keep each case visibly unverified until an analyst signs off.

**References:** [evidence_engine.py:110](evidence_engine.py#L110) · [dashboard_v1_2.py:415](dashboard_v1_2.py#L415) · [report_engine_v2.py:8](report_engine_v2.py#L8)

### Medium

#### M1. Opening or creating another case discards unsaved edits

**Evidence status:** Confirmed by the activation path.

**Reproduction scenario and impact.** Edit a ticket draft without saving, switch to Case Management, then choose **Open Case** or **New Case**. Activation replaces the investigation object and its widget state. The sidebar signals unsaved changes but the switch offers no save or discard decision.

**Recommended fix and regression test.** Gate case replacement with Save, Discard, and Cancel. Test switching and creating with a dirty draft, including a stale save during the switch.

**References:** [case_management_ui.py:92](case_management_ui.py#L92) · [case_management_ui.py:112](case_management_ui.py#L112) · [case_management_ui.py:256](case_management_ui.py#L256)

#### M2. A failed Ticket Lab evidence selection can clear the last good evidence in the current version

**Evidence status:** Confirmed by the selection and save paths.

**Reproduction scenario and impact.** Open a saved case with valid screenshots and select a different file still listed in the manifest but missing or invalid on disk. The code commits the selection before loading and replaces the evidence with an empty record on failure. That invalidates the reassessment and can trigger a checkpoint. Prior versions remain intact, but the current case loses usable evidence.

**Recommended fix and regression test.** Read and validate the complete replacement before changing the selection or evidence. Test missing, malformed, and unreadable replacements and assert that the last good evidence, reassessment, and row version survive.

**References:** [dashboard_v1_2.py:370](dashboard_v1_2.py#L370) · [dashboard_v1_2.py:660](dashboard_v1_2.py#L660) · [investigation_state.py:83](investigation_state.py#L83)

#### M3. Untrusted strings reach Markdown renderers and raw provider errors reach the UI

**Evidence status:** Confirmed data paths with unverified disclosure impact.

**Reproduction scenario and impact.** Inject a benign formatting fixture into mocked model output, or return an exception containing a synthetic sensitive marker. Model results and generated reports reach Markdown rendering, and exception strings reach on-screen details. Misleading links and remote content requests are browser risks that were not exercised. No secret exposure was observed.

**Recommended fix and regression test.** Render untrusted fields as plain text or allowlist safe Markdown without external resources. Show sanitized errors and diagnostic IDs. Test external images and links using an isolated browser with network interception, and verify fake secrets never reach the UI, reports, or logs.

**References:** [dashboard_v1_2.py:215](dashboard_v1_2.py#L215) · [dashboard_v1_2.py:365](dashboard_v1_2.py#L365) · [dashboard_v1_2.py:518](dashboard_v1_2.py#L518) · [dashboard_v1_2.py:553](dashboard_v1_2.py#L553)

#### M4. Incident verdict and AI quality are separate in storage, but normal workflows cannot record both

**Evidence status:** Confirmed feature gap against the plan.

**Reproduction scenario and impact.** Complete an investigation and issue a report entirely through the UI. The case keeps `NOT_ASSESSED` unless an external caller sets the verdict. The wizard stores model output in snapshots, while the audit view reads quality from separate assessment and review tables. There is no normal workflow to register and rate that exact output.

**Recommended fix and regression test.** Add explicit analyst verdict and assessment-review actions, or mark the omitted workflows out of scope for this release. Test that changing a verdict leaves lifecycle unchanged, that reviews bind to a stable assessment ID, and that a newer assessment starts unreviewed.

**References:** [case_management_ui.py:273](case_management_ui.py#L273) · [case_repository.py:427](case_repository.py#L427) · [case_repository.py:462](case_repository.py#L462) · [V05_ARCHITECTURE_PLAN.md:79](V05_ARCHITECTURE_PLAN.md#L79)

#### M5. `OPEN` and `DRAFT` are an unresolved lifecycle contract

**Evidence status:** Confirmed mismatch.

**Reproduction scenario and impact.** A caller or release checklist uses `OPEN` as the initial status. The enum rejects it and the database creates `DRAFT`. Current transitions work under the checked-in plan, but consumers expecting `OPEN` cannot use that contract.

**Recommended fix and regression test.** Confirm the canonical lifecycle before release. If adopting `OPEN`, define its meaning and migrate existing rows without rewriting historical conclusions. If keeping `DRAFT`, align release acceptance and documentation. Run the transition matrix and an existing-database compatibility test against the agreed contract.

**References:** [case_repository.py:19](case_repository.py#L19) · [case_repository.py:331](case_repository.py#L331) · [V05_ARCHITECTURE_PLAN.md:42](V05_ARCHITECTURE_PLAN.md#L42)

### Low

#### L1. Release instructions omit v0.5 storage and test behavior

**Evidence status:** Confirmed documentation gap.

**Reproduction scenario and impact.** Follow the README to install, run, and test. It still identifies v0.4.0 and 11 tests, omits `EDR_CASE_DB_PATH` and report issuance, and recommends discovery without mentioning the generated sample report. The default per-user SQLite path and ignore rules reduce accidental commits, while operating-system permissions, encryption, and backup handling remain deployment responsibilities.

**Recommended fix and regression test.** Document the verified dependency range, local-only launch, database path and permissions, archive versus deletion, report issuance, and isolated test procedure. Run the instructions from a fresh checkout with no Gemini key and a disposable database.

**References:** [README.md:124](README.md#L124) · [case_repository.py:114](case_repository.py#L114) · [.gitignore:28](.gitignore#L28) · [test_report.py:41](test_report.py#L41)

#### L2. Snapshot integrity protects against ordinary app edits. Tamper evidence is unverified and outside the current design

**Evidence status:** Confirmed design boundary. Independent tamper evidence and authenticated authorship are unverified.

**Reproduction scenario and impact.** Restore a database from a backup whose integrity or provenance is unknown. Screenshot checks can detect mismatches against recorded hashes, but those hashes and records share the same trust boundary. Analyst labels are self-entered. The audit trail is useful for local workflow history and should not be represented as independent forensic proof.

**Recommended fix and regression test.** Document the trust boundary and backup-verification procedure. Test rejecting corrupted evidence and restoring a verified backup. Add externally anchored signatures and authenticated identities only if forensic attestation becomes a release requirement.

**References:** [case_repository.py:196](case_repository.py#L196) · [case_repository.py:262](case_repository.py#L262) · [case_history_ui.py:71](case_history_ui.py#L71)

## Top five fixes and ordered remediation

1. **Enforce loopback-only launch** and document the SQLite and backup trust boundary. **H1**
2. **Correct the Streamlit minimum** and verify a fresh installation against it. **H2**
3. **Make Gemini authorization per submission** and block sends from already-stale sessions. **H3**
4. **Separate model assertions from analyst verification** and constrain untrusted rendering and error output. **H4, M3**
5. **Protect active investigation work** during case switches and failed evidence replacement. **M1, M2**

Then resolve the lifecycle naming and verdict/review scope, update the release instructions, and run the full suite plus browser QA against the release candidate.

## Missing automated tests and manual browser QA

- **Automated tests.** Add the two-session Gemini tests, case-switch and failed-image replacement tests, dependency-boundary startup tests, and isolated launch-binding checks above. Add an upgrade test against a populated SQLite fixture and a concurrent audit-write test that confirms notes and issued reports attach to the intended saved version.
- **Desktop and mobile browser.** At phone and desktop widths, verify drawer access, keyboard focus, active-view indication, table scrolling, screenshot previews, and downloads with the sidebar collapsed. Check that status and validation errors are understandable without relying on color.
- **Regression walkthrough.** With a disposable database and mocked Gemini, complete manual and Ticket Lab cases through all five stages. Hold, resume, close both ways, reopen, archive, and restore. Compare older report downloads byte-for-byte, and verify history inspection preserves the current draft, step, and version.

## Known limitations and release blockers

- **Release blockers.** H1 through H4 are the basis for the public-release NO-GO recommendation. M1 and M2 are priority investigation-data preservation fixes. M4 and M5 require release-scope decisions before acceptance criteria are finalized.
- **Verification limits.** The file-free checks do not establish full-suite, end-to-end browser, firewall, or live provider behavior. Dependency compatibility was checked using source for the advertised minimum. The audit did not install or run that minimum. Browser-mediated external requests and disclosure from real provider errors were not exercised.
- **Deployment limits.** The reviewed design is for a trusted single-analyst environment. Database encryption, backup integrity, and authenticated attribution rely on deployment controls or future requirements, as described in L1 and L2.

Implementation awaits explicit approval.
