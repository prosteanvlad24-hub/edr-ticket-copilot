"""EDR Ticket Copilot's five-step investigation workspace."""

import json
import os
from pathlib import Path

import streamlit as st

from case_management_ui import MANAGEMENT, CaseWorkspace, navigation_view, wizard_key
from evidence_inputs import MAX_IMAGE_BYTES, MAX_IMAGES, prepare_images
from investigation_state import LAB, MANUAL, Evidence, Investigation, Ticket
from ioc_engine import extract_iocs
from report_engine_v2 import build_report_exports
from rules_engine import classify_ticket, get_troubleshooting_steps, ransomware_signals, reported_ticket_text
from severity_engine import assess_severity, source_reported_severity
from ticket_lab_inputs import list_evidence, list_runs, read_case, read_catalog
from ui_styles import FAVICON, apply_styles, render_metrics, render_progress, render_sidebar_brand, render_stage_heading

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
STEPS = ("Ticket Lab / Ticket Entry", "Initial Analysis", "Initial Findings", "Evidence Investigation", "Final Report")
PROGRESS = ("Ticket entry", "Initial analysis", "Initial findings", "Evidence", "Final report")
STEP_DESCRIPTIONS = (
    "Use a synthetic Ticket Lab incident or enter a ticket from your investigation.",
    "Run ticket validation, rule-based triage, IOC extraction, and AI to build the initial assessment.",
    "Review severity, candidate indicators, unanswered questions, and the evidence to collect next.",
    "Review screenshots and use the available evidence to reassess the initial findings.",
    "Review the investigation outcome and export the report for analyst handoff.",
)
MODULES = {
    "triage": "Rule-based triage & severity",
    "iocs": "IOC extraction",
    "validation": "Ticket validation",
    "ai": "Gemini analysis",
}
SEVERITY_TONE = {"critical": "danger", "high": "danger", "medium": "warning", "low": "success"}


def show_sidebar_status(case, workspace):
    current = workspace.active
    ticket = case.ticket
    save_label, save_color = workspace.save_status(case)
    db_label, db_color = workspace.database_status
    gemini_ready = bool(os.getenv("GEMINI_API_KEY"))
    with st.container(key="edr_active_case", border=True):
        st.markdown("#### Active Case")
        if current:
            st.text(current.title)
        st.caption(f"Incident ID · {ticket.lab_id}" if ticket.lab_id else "Manual ticket")
        with st.container(horizontal=True):
            if current:
                st.badge(current.status.value.replace("_", " ").title(), color="blue")
            st.badge(save_label, color=save_color)
        st.caption(f"{ticket.criticality.title()} asset criticality")
    with st.container(key="edr_system_status", border=True):
        st.markdown("#### System Status")
        st.badge("Local Analysis · Available", color="green")
        st.badge("Gemini · Configured" if gemini_ready else "Gemini · API key required",
                 color="green" if gemini_ready else "gray")
        st.badge(f"Case database · {db_label}", color=db_color)


def show_sample_library():
    with st.expander("Sample ticket library"):
        try:
            samples = json.loads((ROOT / "tickets.json").read_text(encoding="utf-8"))
            if not isinstance(samples, list):
                raise ValueError("Expected a list of sample tickets.")
        except (OSError, ValueError):
            st.info("The sample ticket library is unavailable.")
            return
        for item in samples:
            if not isinstance(item, dict):
                continue
            st.markdown(f"**{item.get('id', 'Sample ticket')} · {item.get('product', 'Unknown product')}**")
            st.write(item.get("description", ""))
            st.caption(f"Category · {item.get('category', 'Unknown')}")


def show_manual_entry(case):
    draft = case.manual_draft
    fields = {
        "ticket_description": draft.description,
        "asset_criticality": draft.criticality,
        "offline_hours": draft.offline_hours,
        "affected_endpoints": draft.affected_endpoints,
    }
    for key, value in fields.items():
        st.session_state.setdefault(wizard_key(key), value)
    with st.container(border=True, key="ticket-editor"):
        st.subheader("Incident description")
        description = st.text_area(
            "Incident description", value=None, key=wizard_key("ticket_description"), height=200,
            label_visibility="collapsed",
            placeholder="Paste an EDR alert, incident note, or support ticket.",
        ) or ""
        st.markdown("**Incident context**")
        left, center, right = st.columns(3)
        criticality = left.selectbox("Asset criticality", ["low", "medium", "high", "critical"], index=None, key=wizard_key("asset_criticality"))
        hours = center.number_input("Hours since agent communication", min_value=0, value=None, key=wizard_key("offline_hours"))
        endpoints = right.number_input("Affected endpoints", min_value=1, value=None, key=wizard_key("affected_endpoints"))
    case.manual_draft = Ticket(
        description.strip(), criticality or draft.criticality,
        draft.offline_hours if hours is None else hours,
        draft.affected_endpoints if endpoints is None else endpoints,
    )
    show_sample_library()
    return bool(case.manual_draft.description)


def show_lab_entry(case, workspace):
    run_key = wizard_key("lab_run")
    with st.container(border=True):
        st.subheader("Generate synthetic tickets")
        left, right = st.columns(2)
        seed = left.number_input("Generator seed", value=42, step=1, key=wizard_key("lab_seed"))
        count = right.number_input("Tickets to generate", min_value=1, max_value=10, value=3, key=wizard_key("lab_count"))
        if st.button("Generate synthetic tickets", key="lab_generate"):
            try:
                from ticket_lab import generate_run

                with st.spinner("Creating synthetic tickets and screenshots..."):
                    run = generate_run(RUNS, count=int(count), seed=int(seed), with_evidence=True)
                st.session_state[run_key] = run.name
            except (ImportError, OSError, TypeError, ValueError) as exc:
                st.error(f"Ticket generation failed. {exc}")

    runs = {run.name: run for run in list_runs(RUNS)}
    if not runs:
        st.info("Generate a run to select a synthetic ticket.")
        return bool(case.ticket.lab_id)
    with st.container(border=True):
        st.subheader("Load a synthetic ticket")
        if st.session_state.get(run_key) not in runs:
            st.session_state[run_key] = case.ticket.lab_run if case.ticket.lab_run in runs else next(iter(runs))
        run = runs[st.selectbox("Synthetic run", list(runs), index=None, key=run_key)]
        try:
            catalog = read_catalog(run)
            if not catalog:
                st.info("This run contains no tickets.")
                return bool(case.ticket.lab_id)
            ids = list(catalog)
            default = ids.index(case.ticket.lab_id) if case.ticket.lab_run == run.name and case.ticket.lab_id in ids else 0
            selected = st.selectbox(
                "Synthetic ticket", ids, index=default, key=wizard_key("lab_ticket_" + run.name),
                format_func=lambda ticket_id: f"{ticket_id} · {catalog[ticket_id]}",
            )
            if st.button("Load into Guided Investigation", key="lab_load"):
                loaded = read_case(run, selected, [])
                case.commit_ticket(Ticket(
                    loaded.description, loaded.asset_criticality, loaded.offline_hours,
                    loaded.affected_endpoints, loaded.run, loaded.ticket_id,
                ))
                if workspace.checkpoint(case):
                    st.rerun()
            if case.ticket.lab_run == run.name and case.ticket.lab_id == selected:
                st.success(f"{selected} loaded")
                st.text_area("Loaded incident description", value=case.ticket.description, disabled=True, height=180)
                show_context(case.ticket)
                return True
        except (ImportError, OSError, ValueError) as exc:
            st.error(f"The synthetic ticket could not be opened. {exc}")
    return False


def show_ticket_entry(case, workspace):
    mode = st.radio("Ticket source", ["Manual entry", LAB], index=int(case.entry_source == LAB), horizontal=True, key=wizard_key("ticket_source_widget"))
    case.entry_source = mode
    return show_lab_entry(case, workspace) if mode == LAB else show_manual_entry(case)


def show_context(ticket):
    render_metrics(st, [
        ("Asset criticality", ticket.criticality.title(), "accent"),
        ("Hours since communication", ticket.offline_hours, "default"),
        ("Affected endpoints", ticket.affected_endpoints, "default"),
    ], icons=("server", "clock", "display"))


def analyze_triage(ticket):
    category = classify_ticket(ticket.description)
    return {
        "ticket": ticket.description,
        "category": category,
        "steps": get_troubleshooting_steps(category),
        "severity": assess_severity(
            category=category, asset_criticality=ticket.criticality,
            offline_hours=ticket.offline_hours, affected_endpoints=ticket.affected_endpoints,
            source_severity=source_reported_severity(ticket.description),
            ransomware_signals=ransomware_signals(ticket.description),
        ),
        "context": (ticket.criticality, ticket.offline_hours, ticket.affected_endpoints),
    }


def analyze_iocs(ticket):
    return {"ticket": ticket.description, "indicators": extract_iocs(reported_ticket_text(ticket.description))}


def analyze_validation(ticket):
    from ticket_validator import validate_ticket

    return validate_ticket(ticket.description)


def analyze_ai(ticket):
    from ai_engine import analyze_ticket

    return analyze_ticket(ticket.description)


ANALYZERS = {"triage": analyze_triage, "iocs": analyze_iocs, "validation": analyze_validation, "ai": analyze_ai}


def run_modules(case, modules):
    for module in modules:
        try:
            result = ANALYZERS[module](case.ticket)
            if module == "validation":
                case.save_validation(result)
            else:
                case.results[module] = result
            case.errors.pop(module, None)
        except Exception as exc:
            case.errors[module] = str(exc)


def show_module_status(case):
    cards = []
    for key, title in MODULES.items():
        if key in case.errors:
            label, tone = ("Retry failed", "warning") if key in case.results else ("Failed", "danger")
        elif key in case.results:
            label, tone = "Complete", "success"
        else:
            label, tone = "Not run", "default"
        cards.append((title, label, tone))
    render_metrics(st, cards, icons=("layers", "radar", "checklist", "spark"), variant="modules")
    for key, error in case.errors.items():
        st.warning(f"{MODULES[key]} failed. Other modules can still run.")
        with st.expander(f"{MODULES[key]} error details"):
            st.code(error)


def show_initial_analysis(case):
    show_context(case.ticket)
    with st.container(key="initial-actions"):
        full, local = st.columns([1.16, 1])
        run_full = full.button("Run full initial analysis", type="primary", key="full_analysis_button", use_container_width=True)
        run_local = local.button("Run local analysis", key="local_analysis_button", use_container_width=True)
    if run_full:
        with st.spinner("Running local analysis and Gemini checks..."):
            run_modules(case, MODULES)
    if run_local:
        with st.spinner("Running local triage and IOC extraction..."):
            run_modules(case, ("triage", "iocs"))
    st.caption("Full analysis sends the ticket text to Gemini for validation and initial findings.")
    with st.expander("Run individual modules"):
        buttons = {
            "triage": ("Rule-based analysis", "rule_analysis_button"),
            "iocs": ("Extract IOCs", "ioc_extraction_button"),
            "validation": ("Validate ticket request", "guided_validate"),
            "ai": ("Gemini AI analysis", "gemini_analysis_button"),
        }
        for module, (label, key) in buttons.items():
            if st.button(label, key=key):
                with st.spinner(f"Running {MODULES[module]}..."):
                    run_modules(case, (module,))
    with st.container(key="analysis-status"):
        st.subheader("Module status")
        show_module_status(case)


def show_lines(items):
    for item in items:
        st.write("• " + str(item))


def show_evidence_requests(requests):
    for item in requests:
        with st.container(border=True):
            st.write(item.get("source") or "Evidence source")
            st.write(item.get("what_to_capture", ""))
            st.caption(item.get("why", ""))


def show_severity(severity):
    source = severity.get("source_severity") or "Not stated"
    heuristic = severity.get("severity", "Unknown")
    priority = severity.get("recommended_priority", heuristic)
    render_metrics(st, [
        ("Source-reported severity", source, SEVERITY_TONE.get(source.lower(), "default")),
        ("Heuristic severity", heuristic, SEVERITY_TONE.get(heuristic.lower(), "default")),
        ("Recommended investigation priority", priority, SEVERITY_TONE.get(priority.lower(), "default")),
        ("Heuristic score", severity.get("score", "Unknown"), "default"),
    ])
    if severity.get("major_disagreement"):
        st.warning(f"Major severity disagreement. The source reports {source} and the heuristic is {heuristic}.")
    st.caption(severity.get("priority_rationale", "Investigation priority requires analyst confirmation."))


def show_initial_findings(case):
    show_module_status(case)
    if not case.results:
        st.info("Use Back to run an analysis, or continue to investigate screenshots.")
        return

    triage = case.results.get("triage")
    if triage:
        severity = triage["severity"]
        show_severity(severity)
        st.caption("Classification · " + triage["category"].replace("_", " ").title())
        with st.expander("Severity rationale and troubleshooting"):
            show_lines(severity.get("reasons", []))
            show_lines(triage.get("steps", []))

    validation = case.prior_validation
    if validation:
        with st.container(border=True, key="analysis-detail"):
            st.subheader("Ticket assessment")
            render_metrics(st, [("Product", validation.get("product", "Unknown"), "default"),
                                ("Request quality", validation.get("assessment", "Unknown"), "accent")])
            st.markdown("**Reported issue**")
            st.write(validation.get("reported_issue", ""))
            st.markdown("**Requested action**")
            st.write(validation.get("requested_action", ""))
            st.write(validation.get("reasoning", ""))
            st.markdown("**Missing information**")
            missing = validation.get("missing_information")
            if missing:
                show_lines(missing)
            else:
                st.caption("None identified.")
            st.markdown("**Recommended evidence**")
            requests = validation.get("evidence_requests")
            if requests:
                show_evidence_requests(requests)
            else:
                st.caption("No additional evidence requested.")
            with st.expander("Suggested clarification to requester"):
                st.write(validation.get("clarification_message", ""))

    if case.results.get("iocs"):
        indicators = case.results["iocs"]["indicators"]
        hashes = indicators.get("hashes", {})
        st.subheader("Detected indicators")
        st.caption("Candidate indicators require verification.")
        groups = [("IPv4", indicators.get("ipv4", [])), ("Domains", indicators.get("domains", [])),
                  ("URLs", indicators.get("urls", [])), *[(kind, values) for kind, values in hashes.items()]]
        for name, values in groups:
            with st.expander(f"{name} · {len(values)}"):
                if values:
                    st.code("\n".join(values))
                else:
                    st.caption("None detected.")
        partials = indicators.get("partial_hashes", [])
        with st.expander(f"Partial hashes · {len(partials)}"):
            if partials:
                st.caption("Incomplete digests require the full value for matching.")
                st.code("\n".join(f"{item['algorithm'] or 'Unknown algorithm'}  {item['value']}" for item in partials))
            else:
                st.caption("None detected.")

    if case.results.get("ai"):
        with st.container(border=True, key="initial-ai-findings"):
            st.subheader("Gemini initial findings")
            st.markdown(case.results["ai"])


def load_lab_evidence(case):
    run = RUNS / case.ticket.lab_run
    try:
        options = list_evidence(run, case.ticket.lab_id)
    except (ImportError, OSError, ValueError) as exc:
        if case.evidence.images:
            st.caption("Showing saved screenshots. The original Ticket Lab files are unavailable.")
        else:
            case.set_evidence(LAB, Evidence(), str(exc))
        return
    try:
        if case.evidence.images and not set(case.lab_selection or ()).issubset(options):
            st.caption("Showing saved screenshots. The original Ticket Lab files are unavailable.")
            return
        if not options:
            st.caption("This synthetic run contains no screenshots for the selected ticket.")
        default = options[:1] if case.lab_selection is None else [name for name in case.lab_selection if name in options]
        selected = tuple(st.multiselect(
            "Synthetic screenshots", options, default=default, max_selections=MAX_IMAGES,
            key=wizard_key(f"wizard_lab_images_{case.revision}"),
            format_func=lambda name: f"Screenshot {options.index(name) + 1}",
        ))
        if selected != case.lab_selection or LAB in case.evidence_errors:
            case.lab_selection = selected
            loaded = read_case(run, case.ticket.lab_id, list(selected))
            labels = tuple(f"Screenshot {options.index(name) + 1}" for name in selected)
            case.set_evidence(LAB, Evidence(labels, loaded.images, selected))
    except (ImportError, OSError, ValueError) as exc:
        case.set_evidence(LAB, Evidence(), str(exc))


def capture_uploads(case, key):
    files = st.session_state.get(key) or []
    try:
        if len(files) > MAX_IMAGES:
            raise ValueError(f"Select no more than {MAX_IMAGES} screenshots.")
        if any(not 0 < item.size <= MAX_IMAGE_BYTES for item in files):
            raise ValueError("Each screenshot must be nonempty and at most 8 MiB.")
        images = prepare_images([(item.name, item.getvalue()) for item in files])
        names = tuple(item.name.replace("\\", "/").rsplit("/", 1)[-1] for item in files)
        case.set_evidence(MANUAL, Evidence(names, tuple(images), names))
    except (ImportError, ValueError) as exc:
        case.set_evidence(MANUAL, Evidence(), str(exc))


def show_evidence_assessment(result, provenance):
    with st.container(border=True, key="evidence-assessment"):
        st.subheader("Evidence reassessment")
        render_metrics(st, [
            ("Conclusion status", result.get("conclusion_status", "Unknown"), "accent"),
            ("Requested action", result.get("requested_action_assessment", "Unknown"), "default"),
        ])
        st.markdown("**Analyst review of the model assessment**")
        st.write(result.get("conclusion", ""))
        if provenance:
            with st.expander("Screenshot provenance"):
                for screenshot in provenance:
                    st.caption(f"{screenshot['id']} · {screenshot['source']} · {screenshot['mime_type']}")
                    st.text(screenshot["filename"] or screenshot["label"])
                    st.code(screenshot["sha256"], language=None)
        observations = result.get("observations", [])
        for kind, heading in (
            ("screenshot", "Screenshot observations"),
            ("ticket", "Ticket-reported observations"),
            ("unattributed", "Unattributed model claims"),
        ):
            group = [item for item in observations if item.get("source_kind", "unattributed") == kind]
            if group:
                st.markdown(f"**{heading}**")
            for item in group:
                if kind != "unattributed":
                    st.caption(f"{item.get('source', 'Evidence')} · {item.get('confidence', 'Unknown')} confidence")
                st.write(item.get("observation", ""))
        hypotheses = result.get("hypotheses", [])
        if hypotheses:
            st.markdown("**Hypotheses to validate**")
        for item in hypotheses:
            with st.expander(item.get("hypothesis", "Hypothesis")):
                st.write("Supporting evidence", item.get("supporting_evidence", ""))
                st.write("Missing evidence", item.get("missing_evidence", ""))
        if result.get("recommended_next_steps"):
            st.markdown("**Recommended next steps**")
            show_lines(result["recommended_next_steps"])
        if result.get("next_evidence_requests"):
            st.markdown("**Further evidence requested**")
            show_evidence_requests(result["next_evidence_requests"])
        if result.get("clarification_message"):
            with st.expander("Updated clarification message"):
                st.write(result["clarification_message"])


def show_screenshots(case):
    if case.evidence_source in case.evidence_errors:
        st.warning(case.evidence_errors[case.evidence_source])
    if case.evidence.images:
        st.markdown("**Review selected screenshots**")
        for screenshot, (_, data) in zip(case.evidence_provenance, case.evidence.images):
            st.caption(f"{screenshot['id']} · {screenshot['source']}")
            st.text(screenshot["filename"] or screenshot["label"])
            st.image(data, width=670)


def show_evidence_investigation(case, workspace):
    if case.ticket.lab_id:
        source = st.radio(
            "Evidence source", [LAB, MANUAL], index=int(case.evidence_source == MANUAL),
            horizontal=True, key=wizard_key(f"wizard_evidence_source_{case.revision}"),
        )
        case.set_evidence_source(source)

    with st.container(border=True):
        st.subheader("Screenshots")
        st.caption("Review up to 3 PNG, JPEG, or WebP images, each up to 8 MiB. Redact sensitive content before submitting.")
        if case.evidence_source == LAB:
            load_lab_evidence(case)
        else:
            key = wizard_key(f"guided_evidence_upload_{case.revision}_{case.upload_revision}")
            st.file_uploader(
                "Evidence screenshots", type=["png", "jpg", "jpeg", "webp"],
                accept_multiple_files=True, key=key, on_change=capture_uploads, args=(case, key),
            )
            if case.evidence.images or MANUAL in case.evidence_errors:
                if st.button("Clear uploaded screenshots", key="wizard_clear_uploads"):
                    case.clear_manual_evidence()
                    if workspace.checkpoint(case):
                        st.rerun()
        show_screenshots(case)

    fingerprint = case.fingerprint
    consent = st.checkbox(
        "I have reviewed the screenshots and authorize sending them, the ticket, and any prior validation to Gemini.",
        value=bool(fingerprint and case.consent == fingerprint), disabled=not fingerprint,
        key=wizard_key(f"guided_consent_{case.revision}_{case.evidence_revision}"),
    )
    case.consent = fingerprint if consent else None
    if st.button("Analyze Evidence & Reassess", type="primary", key="guided_analyze_evidence", disabled=not case.consent):
        try:
            from evidence_engine import analyze_evidence

            with st.spinner("Gemini is reassessing the investigation..."):
                result = analyze_evidence(
                    case.ticket.description, list(case.evidence.images), case.prior_validation,
                    evidence_source=case.evidence_source,
                )
            case.reviewed_fingerprint = fingerprint
            case.reviewed_evidence = result
            case.reassessment_error = None
        except Exception as exc:
            case.reassessment_error = str(exc)

    if case.reassessment_error:
        st.error("Evidence reassessment failed. You can retry or continue to the report.")
        with st.expander("Reassessment error details"):
            st.code(case.reassessment_error)
    if case.evidence_assessment:
        show_evidence_assessment(case.evidence_assessment, case.evidence_provenance)


def show_final_report(case):
    evidence = case.evidence_assessment
    provenance = case.evidence_provenance if evidence else []
    status = "Evidence reviewed" if evidence else "Preliminary"
    render_metrics(st, [
        ("Report status", status, "success" if evidence else "warning"),
        ("Incident", case.ticket.lab_id or "Manual ticket", "default"),
        ("Initial modules completed", f"{len(case.results)} / {len(MODULES)}", "accent"),
    ])
    if evidence:
        show_evidence_assessment(evidence, provenance)
    else:
        st.info("Preliminary report. No current screenshot reassessment is included.")
    triage = case.results.get("triage")
    validation = case.prior_validation
    analysis = case.results.get("ai")
    if triage or validation or analysis:
        st.subheader("Initial investigation summary")
        if triage:
            st.write("Classification", triage["category"].replace("_", " ").title())
            show_severity(triage["severity"])
        if validation:
            st.write(validation.get("reported_issue", ""))
        if analysis:
            with st.expander("Initial Gemini findings"):
                with st.container(key="report-copy"):
                    st.markdown(analysis)
        if not evidence and triage and triage["steps"]:
            st.markdown("**Recommended next steps**")
            show_lines(triage["steps"])
    markdown, payload = build_report_exports(case)
    left, right = st.columns(2)
    with left:
        st.download_button(
            "Download Markdown report", data=markdown, file_name="EDR_Investigation_Report_v2.md",
            mime="text/markdown", key="download_full_report_v2", on_click="ignore",
        )
    with right:
        st.download_button(
            "Download JSON report", data=json.dumps(payload, indent=2, ensure_ascii=False),
            file_name="EDR_Guided_Investigation.json", mime="application/json", key="guided_download", on_click="ignore",
        )
    with st.expander("Full report preview"):
        with st.container(key="full-report-copy"):
            st.markdown(markdown)


def navigate(case, entry_ready, workspace):
    with st.container(key="wizard-navigation"):
        back, skip, next_step = st.columns(3)
        if back.button("Back", key="wizard_back", disabled=case.step == 0, width="stretch"):
            case.step -= 1
            return True
        if case.step == 3 and not case.evidence_assessment:
            if skip.button("Skip evidence", key="wizard_skip_evidence", width="stretch"):
                case.step = 4
                return True
        if case.step < len(STEPS) - 1 and next_step.button(
            "Next", key="wizard_next", type="secondary" if case.step == 3 and not case.evidence_assessment else "primary",
            disabled=case.step == 0 and not entry_ready, width="stretch",
        ):
            if workspace.editable and case.step == 0 and case.entry_source == "Manual entry":
                case.commit_ticket(case.manual_draft)
            case.step += 1
            return True
    return False


def main():
    st.set_page_config(
        page_title="EDR Ticket Copilot", page_icon=str(FAVICON) if FAVICON.is_file() else None,
        layout="wide", initial_sidebar_state="auto",
    )
    apply_styles(st)
    if not os.getenv("GEMINI_API_KEY"):
        try:
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env")
        except (ImportError, OSError):
            pass
    if "investigation" not in st.session_state:
        st.session_state["investigation"] = Investigation()
    case = st.session_state["investigation"]
    workspace = CaseWorkspace()
    with st.sidebar:
        render_sidebar_brand(st)
        view = navigation_view()
        sidebar_status = st.container()
    if view == MANAGEMENT:
        workspace.render_management(case)
    else:
        render_wizard(case, workspace)
    with sidebar_status:
        show_sidebar_status(case, workspace)


def render_wizard(case, workspace):
    controls = st.container()
    render_progress(st, PROGRESS, case.step)
    render_stage_heading(
        st, case.ticket.lab_id, STEPS[case.step], STEP_DESCRIPTIONS[case.step], case.step + 1, len(STEPS),
    )

    entry_ready = True
    if workspace.active and not workspace.editable:
        st.caption("Read-only case view")
    if case.step == 0:
        if workspace.editable:
            entry_ready = show_ticket_entry(case, workspace)
        else:
            ticket = case.manual_draft if workspace.conflicted and case.entry_source == "Manual entry" else case.ticket
            st.text(ticket.description)
            show_context(case.ticket)
    elif case.step == 1:
        if workspace.editable:
            show_initial_analysis(case)
        else:
            show_module_status(case)
    elif case.step == 2:
        show_initial_findings(case)
    elif case.step == 3:
        if workspace.editable:
            show_evidence_investigation(case, workspace)
        else:
            show_screenshots(case)
            if case.evidence_assessment:
                show_evidence_assessment(case.evidence_assessment, case.evidence_provenance)
    else:
        show_final_report(case)
    previous_step = case.step
    moved = navigate(case, entry_ready, workspace)
    saved = not workspace.editable or workspace.checkpoint(case, submit=moved and previous_step == 0)
    if moved and saved:
        st.rerun()
    with controls:
        workspace.render_wizard_header(case)


main()
