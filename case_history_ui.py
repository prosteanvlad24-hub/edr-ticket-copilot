"""Read-only audit inspection and explicit note and report actions."""

from collections import Counter
from datetime import datetime, timezone
import json
import sqlite3

import streamlit as st

from case_repository import AI_MODULES, AssessmentQuality, CaseConflictError, CaseStatus, IncidentVerdict
from evidence_inputs import prepare_images, screenshot_provenance
from presentation_safety import (
    AI_EVIDENCE_STATUS_LABEL, AI_UNVERIFIED_NOTICE, SCREENSHOT_ATTRIBUTION_NOTICE, failure_text, record_failure,
)
from report_engine_v2 import build_report_exports


def _post_note(repository, case_id, version, author_key, body_key, correction_key):
    try:
        repository.add_note(
            case_id, version, st.session_state[author_key], st.session_state[body_key],
            supersedes_note_id=st.session_state.get(correction_key),
        )
    except CaseConflictError:
        _notice(case_id, "error", "The saved version changed. Review the latest version before adding the note.")
    except ValueError as exc:
        _notice(case_id, "error", failure_text(record_failure(
            "analyst-note", exc, "Check the author, note content, and selected correction before trying again.",
        )))
    except (OSError, sqlite3.Error, KeyError):
        _notice(case_id, "error", "Could not store the analyst note.")
    else:
        st.session_state[body_key] = ""
        st.session_state[correction_key] = None
        _notice(case_id, "success", f"Analyst note added to version {version}.")


def _issue_report(repository, case_id, version):
    try:
        saved = repository.load(case_id, version=version)
        issued_at = datetime.now(timezone.utc).isoformat()
        investigation = saved.investigation
        displayed_modules = {
            "ai": investigation.results.get("ai"),
            "validation": investigation.prior_validation,
            "evidence": investigation.evidence_assessment,
        }
        outputs = {
            assessment_id: output
            for assessment_id, output in repository.reviewable_outputs(case_id, version).items()
            if displayed_modules[output[0]]
        }
        quality = {
            row["assessment_id"]: {
                key: row[key] for key in ("assessment_id", "assessment_version", "module", "quality", "review_version")
            }
            for row in repository.assessment_quality(case_id, version)
        }
        displayed = {
            module: quality[assessment_id] if registered else {
                "assessment_id": None, "assessment_version": None, "module": module,
                "quality": AssessmentQuality.NOT_REVIEWED.value, "review_version": None,
            }
            for assessment_id, (module, registered, _) in outputs.items()
        }
        audit = {
            "case_id": case_id, "version": version, "issued_at": issued_at,
            "lifecycle_status": saved.metadata.status.value,
            "incident_verdict": saved.metadata.incident_verdict.value,
            "displayed_ai_assessments": displayed,
            "ai_assessment_quality": [
                dict(row, scope="displayed" if assessment_id in outputs else "historical")
                for assessment_id, row in quality.items()
            ],
        }
        markdown, payload = build_report_exports(saved.investigation, audit=audit)
        # The existing SQLite enum is a storage key. New export bytes carry the public trust status.
        storage_status = "evidence_reviewed" if payload["evidence_assessment"] else "preliminary"
        report = repository.issue_report(
            case_id, version, storage_status, markdown.encode("utf-8"),
            json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"), issued_at=issued_at,
        )
    except CaseConflictError:
        _notice(case_id, "error", "The saved version changed. Review the latest version before issuing a report.")
    except (OSError, sqlite3.Error, ValueError, KeyError):
        _notice(case_id, "error", "Could not issue the report. Check that the saved version and evidence can be read.")
    else:
        _notice(case_id, "success", f"Report issued for version {report.version}.")


def _notice(case_id, level, message):
    st.session_state.case_audit_notice = (case_id, level, message)


def _post_decision(repository, case_id, version, choice_key, *, assessment_id=None, label_key=None, rationale_key=None):
    try:
        choice = st.session_state[choice_key]
        if assessment_id is None:
            saved = repository.set_incident_verdict(case_id, version, choice)
        else:
            if choice is None:
                _notice(case_id, "error", "Choose an AI assessment quality before saving.")
                return
            saved = repository.review_assessment(
                case_id, version, assessment_id, choice,
                reviewer_label=st.session_state[label_key], rationale=st.session_state[rationale_key],
            )
    except CaseConflictError:
        _notice(case_id, "error", "The saved version changed. Review the latest version before recording a decision.")
    except (OSError, sqlite3.Error, ValueError, KeyError):
        _notice(case_id, "error", "Could not record the analyst decision.")
    else:
        active = st.session_state.get("case_metadata")
        if active is not None and (active.case_id, active.version) == (case_id, version):
            # Decision-only versions preserve the saved wizard payload and the live draft.
            st.session_state.case_metadata = saved
        message = "No decision changes to save." if saved.version == version else f"Analyst decision recorded in version {saved.version}."
        _notice(case_id, "success", message)


def _render_decisions(repository, latest):
    case_id, version = latest.case_id, latest.version
    st.subheader("Analyst decisions")
    st.caption(f"Decisions apply to saved version {version}. Lifecycle, incident verdict, and model quality are independent.")
    st.text(f"Incident verdict · {latest.incident_verdict.value}")
    editable = latest.status != CaseStatus.ARCHIVED
    if not editable:
        st.caption("Restore this case to record analyst decisions.")
    if editable:
        key = f"audit_verdict_{case_id}_{version}"
        with st.form(f"{key}_form", enter_to_submit=False):
            st.selectbox("Incident verdict", list(IncidentVerdict), key=key,
                         index=list(IncidentVerdict).index(latest.incident_verdict))
            st.form_submit_button("Save incident verdict", on_click=_post_decision,
                                  args=(repository, case_id, version, key))
    st.markdown("#### AI assessment quality")
    st.caption("An optional rating of one saved model response. Record a reviewer label only if known. Ratings do not verify evidence or set the incident verdict.")
    try:
        outputs = repository.reviewable_outputs(case_id, version)
        reviews = {row["assessment_id"]: row for row in repository.assessment_quality(case_id, version)}
    except (OSError, sqlite3.Error, ValueError, KeyError):
        st.error("Could not load saved assessments.")
        return
    if not outputs:
        st.caption("This version has no saved AI output to review.")
    for assessment_id, (module, _, output) in outputs.items():
        review = reviews.get(assessment_id, {})
        quality = AssessmentQuality(review.get("quality", AssessmentQuality.NOT_REVIEWED))
        with st.expander(f"{AI_MODULES[module]} · {quality.value}"):
            st.caption(AI_UNVERIFIED_NOTICE)
            st.text(f"Assessment ID · {assessment_id}")
            st.code(output, language=None)
            _render_review_attribution(review)
            if editable:
                key = f"audit_quality_{assessment_id}_{version}"
                label_key, rationale_key = f"{key}_label", f"{key}_rationale"
                with st.form(f"{key}_form", clear_on_submit=True, enter_to_submit=False):
                    st.radio(f"{AI_MODULES[module]} quality", list(AssessmentQuality), key=key, index=None)
                    st.text_input("Reviewer label (optional, self-entered)", key=label_key, max_chars=120)
                    st.text_area("Reason for rating (optional)", key=rationale_key, max_chars=4000)
                    st.form_submit_button("Save AI assessment quality", on_click=_post_decision,
                                          args=(repository, case_id, version, key),
                                          kwargs={"assessment_id": assessment_id, "label_key": label_key,
                                                  "rationale_key": rationale_key})


def _render_review_attribution(review):
    if review.get("review_version") is not None:
        st.markdown("**Previous saved review**")
        st.text(f"Recorded in version {review['review_version']} · {review['reviewed_at']}")
        label = review["reviewer_label"]
        st.text(f"Self-entered reviewer label · {label}" if label else "Reviewer label was not provided.")
        if review["rationale"]:
            st.text(review["rationale"])


def _render_notes(notes):
    if not notes:
        st.caption("No analyst notes recorded.")
        return
    for note in notes:
        st.text(f"{note.author_label} · Version {note.version} · {note.created_at}")
        st.text(note.body)
        if note.supersedes_note_id:
            st.text(f"Correction to note {note.supersedes_note_id}")


def _render_note_form(repository, case_id, version, notes):
    if not st.toggle("Add an analyst note", key=f"audit_note_toggle_{case_id}"):
        return
    author_key = f"audit_author_{case_id}"
    body_key = f"audit_body_{case_id}"
    correction_key = f"audit_correction_{case_id}"
    with st.form(f"audit_note_form_{case_id}"):
        st.caption(f"This note will be attached to saved version {version}.")
        st.text_input("Analyst name or label", key=author_key, max_chars=120)
        st.text_area("Analyst note", key=body_key, max_chars=8000)
        if notes:
            labels = {note.id: f"Version {note.version} · {note.author_label} · {note.id}" for note in notes}
            st.selectbox("Correct an earlier note (optional)", list(labels), index=None,
                         key=correction_key, format_func=labels.__getitem__)
        st.form_submit_button("Add analyst note", on_click=_post_note,
                              args=(repository, case_id, version, author_key, body_key, correction_key))


def _render_evidence(case, case_id, version):
    st.markdown("#### Historical evidence")
    if not any(evidence.images for evidence in case.evidence_by_source.values()):
        st.caption("No screenshots were saved in this version.")
        return
    preview = st.toggle("Show screenshot previews", key=f"audit_previews_{case_id}_{version}")
    for source, evidence in case.evidence_by_source.items():
        provenance = screenshot_provenance(evidence.images, source, evidence.labels, evidence.filenames)
        for item, (_, raw) in zip(provenance, evidence.images):
            st.text(f"{item['id']} · {item['source']} · {item['mime_type']} · {len(raw):,} bytes")
            st.text(item["filename"] or item["label"])
            st.code(item["sha256"], language=None)
            if preview:
                try:
                    (mime, image), = prepare_images([(item["id"], raw)])
                    if mime != item["mime_type"]:
                        raise ValueError("Screenshot MIME type mismatch")
                except (ImportError, ValueError):
                    st.warning("Preview unavailable for this stored screenshot.")
                else:
                    st.image(image, width=670)


def _render_snapshot(repository, case_id, version, notes):
    try:
        saved = repository.load(case_id, version=version)
        quality = repository.assessment_quality(case_id, version)
    except (OSError, sqlite3.Error, ValueError, KeyError):
        st.error("This snapshot or its stored evidence could not pass an integrity check.")
        return
    case = saved.investigation
    st.markdown("#### Read-only snapshot")
    st.text(f"{saved.metadata.title} · Version {version} · {saved.metadata.saved_at}")
    st.text(f"Lifecycle status · {saved.metadata.status.value}")
    st.text(f"Incident verdict · {saved.metadata.incident_verdict.value}")
    st.text(f"Saved wizard step · {case.step + 1} of 5")
    st.markdown("**Saved ticket**")
    st.text(case.ticket.description)
    st.text(f"Asset criticality · {case.ticket.criticality} · Offline hours · {case.ticket.offline_hours}"
            f" · Affected endpoints · {case.ticket.affected_endpoints}")
    if case.manual_draft != case.ticket:
        with st.expander("Saved manual draft"):
            st.text(case.manual_draft.description)
    if case.results or case.evidence_assessment:
        with st.expander("Stored analysis outputs"):
            for module, value in case.results.items():
                heading = {"triage": "Local triage", "iocs": "Local IOC extraction", "validation": "AI ticket validation (unverified)",
                           "ai": "AI initial findings (unverified)"}.get(module, "Analysis output")
                st.markdown(f"**{heading}**")
                if module in {"validation", "ai"}:
                    st.caption(AI_UNVERIFIED_NOTICE)
                if isinstance(value, str):
                    st.text(value)
                else:
                    st.code(json.dumps(value, indent=2, ensure_ascii=False), language=None)
            if case.evidence_assessment:
                st.markdown("**AI evidence reassessment (unverified)**")
                st.caption(AI_UNVERIFIED_NOTICE)
                st.caption(SCREENSHOT_ATTRIBUTION_NOTICE)
                st.code(json.dumps(case.evidence_assessment, indent=2, ensure_ascii=False), language=None)
    st.markdown("**AI assessment quality**")
    if quality:
        st.dataframe(quality, hide_index=True)
    else:
        st.caption("No AI assessment quality records were saved for this version.")
    st.markdown("**Analyst notes attached to this version**")
    _render_notes([note for note in notes if note.version == version])
    _render_evidence(case, case_id, version)


def _render_reports(repository, case_id, version, reports):
    st.subheader("Issued reports")
    if reports:
        statuses = {"preliminary": "Preliminary", "evidence_reviewed": AI_EVIDENCE_STATUS_LABEL}
        titles = {report.id: f"Version {report.version} · {statuses[report.report_status]} · "
                  f"{report.issued_at} · {report.id[:8]}" for report in reports}
        report_id = st.selectbox("Issued report", list(titles), index=None,
                                 key=f"audit_report_{case_id}", format_func=titles.__getitem__)
        if report_id is not None:
            try:
                report = repository.get_report(case_id, report_id)
            except (OSError, sqlite3.Error, KeyError):
                st.error("Could not retrieve the issued report.")
            else:
                file_stem = f"EDR_Report_v{report.metadata.version}_{report_id}"
                st.caption("Downloads preserve the issued bytes. Older reports may contain legacy wording and active Markdown. Use the plain-text preview for inspection.")
                with st.container(horizontal=True):
                    st.download_button("Download issued Markdown", report.markdown_bytes, f"{file_stem}.md",
                                       "text/markdown", key=f"audit_md_{report_id}", on_click="ignore")
                    st.download_button("Download issued JSON", report.json_bytes, f"{file_stem}.json",
                                       "application/json", key=f"audit_json_{report_id}", on_click="ignore")
                with st.expander("Issued Markdown preview"):
                    st.code(report.markdown_bytes.decode("utf-8", errors="replace"), language=None)
    else:
        st.caption("No reports have been issued for this case.")
    st.button(f"Issue report for saved version {version}", key=f"audit_issue_{case_id}",
              on_click=_issue_report, args=(repository, case_id, version))


def render_case_history(repository, case_id):
    st.subheader("Case History")
    try:
        versions = repository.history(case_id)
        notes = repository.list_notes(case_id)
        reports = repository.list_reports(case_id)
    except (OSError, sqlite3.Error, ValueError, KeyError):
        st.error("Could not read the selected case’s audit history.")
        return
    latest = versions[-1]
    st.text(f"{latest.title} · {case_id}")
    notice = st.session_state.pop("case_audit_notice", None)
    if notice and notice[0] == case_id:
        (st.success if notice[1] == "success" else st.error)(notice[2])
    _render_decisions(repository, latest)
    note_counts = Counter(note.version for note in notes)
    st.dataframe([
        {"Version": entry.version, "Saved (UTC)": entry.saved_at, "Lifecycle status": entry.status.value,
         "Incident verdict": entry.incident_verdict.value, "Event": entry.event,
         "Transition reason": entry.rationale or "", "Analyst notes": note_counts[entry.version]}
        for entry in versions
    ], hide_index=True)
    version = st.selectbox("Inspect a saved version", [item.version for item in versions], index=None,
                           format_func=lambda number: f"Version {number}", key=f"audit_version_{case_id}")
    if version is not None:
        _render_snapshot(repository, case_id, version, notes)
    with st.expander("Analyst note history"):
        _render_notes(notes)
    _render_note_form(repository, case_id, latest.version, notes)
    _render_reports(repository, case_id, latest.version, reports)
