"""Read-only audit inspection and explicit note and report actions."""

from collections import Counter
from datetime import datetime, timezone
import json
import sqlite3

import streamlit as st

from case_repository import CaseConflictError
from evidence_inputs import prepare_images, screenshot_provenance
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
        _notice(case_id, "error", str(exc))
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
        audit = {
            "case_id": case_id, "version": version, "issued_at": issued_at,
            "lifecycle_status": saved.metadata.status.value,
            "incident_verdict": saved.metadata.incident_verdict.value,
            "ai_assessment_quality": repository.assessment_quality(case_id, version),
        }
        markdown, payload = build_report_exports(saved.investigation, audit=audit)
        report = repository.issue_report(
            case_id, version, payload["report_status"], markdown.encode("utf-8"),
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


def _render_notes(notes):
    if not notes:
        st.caption("No analyst notes recorded.")
        return
    for note in notes:
        st.text(f"{note.author_label} · Version {note.version} · {note.created_at}")
        st.text(note.body)
        if note.supersedes_note_id:
            st.caption(f"Correction to note {note.supersedes_note_id}")


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
        st.error("This snapshot or its evidence could not be verified.")
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
                heading = {"triage": "Local triage", "iocs": "Local IOC extraction", "validation": "AI ticket validation",
                           "ai": "AI initial findings"}.get(module, "Analysis output")
                st.markdown(f"**{heading}**")
                st.text(value) if isinstance(value, str) else st.json(value, expanded=False)
            if case.evidence_assessment:
                st.markdown("**AI evidence reassessment**")
                st.json(case.evidence_assessment, expanded=False)
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
        titles = {report.id: f"Version {report.version} · {report.report_status.replace('_', ' ')} · "
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
    note_counts = Counter(note.version for note in notes)
    st.dataframe([
        {"Version": entry.version, "Saved (UTC)": entry.saved_at, "Lifecycle status": entry.status.value,
         "Event": entry.event, "Transition reason": entry.rationale or "", "Analyst notes": note_counts[entry.version]}
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
