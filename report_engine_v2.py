"""Evidence-aware Markdown incident report. No AI/API calls are made here."""
from datetime import datetime, timezone
from typing import Any

from case_repository import AI_MODULES
from investigation_state import LAB
from presentation_safety import (
    AI_EVIDENCE_STATUS_LABEL, AI_UNVERIFIED_NOTICE, SCREENSHOT_ATTRIBUTION_NOTICE,
    markdown_literal as _s, markdown_literal_block,
)


def build_report_exports(case, *, audit=None):
    """Build both export formats from saved inputs without running analysis."""
    evidence = case.evidence_assessment
    provenance = case.evidence_provenance if evidence else []
    triage = case.results.get("triage")
    validation = case.prior_validation
    analysis = case.results.get("ai")
    displayed = audit["displayed_ai_assessments"] if audit is not None else {}
    markdown = generate_investigation_report(
        description=case.ticket.description, rule_result=triage, ioc_result=case.results.get("iocs"),
        ai_analysis=analysis, validation=validation, evidence_assessment=evidence,
        synthetic_evidence=bool(evidence and case.evidence_source == LAB), evidence_provenance=provenance,
        assessment_links=displayed,
    )
    payload = {
        "report_status": "ai_evidence_assessment_unverified" if evidence else "preliminary",
        "analyst_verification_status": "not_recorded",
        "ticket": case.ticket.description,
        "validation": validation,
        "evidence_assessment": evidence,
        "evidence_provenance": provenance,
        "initial_analysis": {
            "rule_based_triage": triage,
            "indicators": case.results.get("iocs"),
            "ai_analysis": analysis,
        },
    }
    if audit is not None:
        payload["case_audit"] = audit
        historical = [row for row in audit["ai_assessment_quality"] if row["scope"] == "historical"]
        markdown += (
            "\n## Case audit metadata\n\n"
            f"- Case ID: {_s(audit['case_id'])}\n- Case version: {_s(audit['version'])}\n"
            f"- Issued (UTC): {_s(audit['issued_at'])}\n- Lifecycle status: {_s(audit['lifecycle_status'])}\n"
            f"- Recorded incident verdict: {_s(audit['incident_verdict'])}\n"
            "\n### Historical AI assessment quality\n\n"
            + _bullet([f"{AI_MODULES.get(row['module'], row['module'])} · {_assessment_summary(row)}" for row in historical],
                      "No historical AI assessment quality records.")
        )
    return markdown, payload


def _assessment_summary(row):
    if row["assessment_id"] is None:
        return f"Unregistered legacy assessment · {row['quality']}"
    reviewed = f" · Review version {row['review_version']}" if row["review_version"] is not None else ""
    return f"Assessment {row['assessment_id']} · Response version {row['assessment_version']} · {row['quality']}{reviewed}"


def _assessment_line(links, module):
    row = links.get(module) if links else None
    return [f"- Recorded assessment quality: {_s(_assessment_summary(row))}"] if row else []


def _bullet(items: Any, empty: str = "Not available") -> str:
    if not items:
        return f"- {empty}\n"
    return "".join(f"- {_s(item)}\n" for item in items)


def generate_investigation_report(
    description: str,
    rule_result: dict | None = None,
    ioc_result: dict | None = None,
    ai_analysis: str | None = None,
    validation: dict | None = None,
    evidence_assessment: dict | None = None,
    *,
    synthetic_evidence: bool = False,
    evidence_provenance: list[dict] | tuple[dict, ...] = (),
    assessment_links: dict | None = None,
) -> str:
    """Build a consolidated report from already completed analyses only."""
    status = AI_EVIDENCE_STATUS_LABEL if evidence_assessment else "Preliminary"
    out = [
        "# EDR Ticket Copilot — Investigation Report v2",
        f"Generated (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Report status:** {status}.",
        "**Analyst verification:** Not recorded. Treat AI output as unverified and review claims independently.",
        "**Scope:** Only the supplied ticket and previously submitted evidence were considered. No live environment access.",
        "\n## 1. Original Ticket\n",
        markdown_literal_block(description),
    ]
    if rule_result:
        sev = rule_result.get("severity") or {}
        out += ["\n## 2. Rule-Based Triage\n",
                f"- Classification: **{_s(rule_result.get('category', 'unknown'))}**",
                f"- Source-reported severity: **{_s(sev.get('source_severity') or 'Not stated')}**",
                f"- Heuristic severity: **{_s(sev.get('severity', 'N/A'))}** (score {_s(sev.get('score', 'N/A'))})",
                f"- Recommended investigation priority: **{_s(sev.get('recommended_priority', sev.get('severity')))}**"]
        if sev.get("major_disagreement"):
            out.append("- **Major severity disagreement.** Reconcile the source rating and heuristic during analyst review.")
        if sev.get("priority_rationale"):
            out.append(f"- {_s(sev['priority_rationale'])}")
        out += ["\n### Severity rationale\n", _bullet(sev.get("reasons")),
                "\n### Recommended troubleshooting\n", _bullet(rule_result.get("steps"))]
    else:
        out += ["\n## 2. Rule-Based Triage\n", "Not run for this ticket."]
    if ioc_result:
        iocs = ioc_result.get("indicators") or {}
        hashes = iocs.get("hashes") or {}
        out += ["\n## 3. Extracted Indicators\n",
                "Candidate indicators only; no maliciousness verdict or reputation lookup was performed."]
        for key, label in (("ipv4", "IPv4"), ("domains", "Domains"), ("urls", "URLs")):
            out += [f"\n### {label}\n", _bullet(iocs.get(key))]
        for kind in ("MD5", "SHA1", "SHA256"):
            out += [f"\n### {kind}\n", _bullet(hashes.get(kind))]
        partials = iocs.get("partial_hashes", [])
        if partials:
            out += ["\n### Partial hashes\n", "Incomplete digests require the full value for matching."]
            for item in partials:
                out.append(f"- {_s(item.get('algorithm') or 'Unknown algorithm')} {_s(item.get('value'))}")
    else:
        out += ["\n## 3. Extracted Indicators\n", "Not run for this ticket."]
    out += ["\n## 4. Gemini Incident Analysis\n"]
    out += [AI_UNVERIFIED_NOTICE, *_assessment_line(assessment_links, "ai"),
            markdown_literal_block(ai_analysis)] if ai_analysis else ["Not run for this ticket."]
    if validation:
        out += ["\n## 5. Ticket Intent Validation\n",
                AI_UNVERIFIED_NOTICE,
                *_assessment_line(assessment_links, "validation"),
                f"- Product: {_s(validation.get('product'))}",
                f"- Request quality: **{_s(validation.get('assessment'))}**",
                f"- Reported issue: {_s(validation.get('reported_issue'))}",
                f"- Requested action: {_s(validation.get('requested_action'))}",
                f"- AI reasoning: {_s(validation.get('reasoning'))}",
                "\n### Missing information\n", _bullet(validation.get("missing_information")),
                "\n### Initial evidence requests\n"]
        for item in validation.get("evidence_requests", []):
            out.append(f"- **{_s(item.get('source'))}** — {_s(item.get('what_to_capture'))}. Reason: {_s(item.get('why'))}")
        if not validation.get("evidence_requests"):
            out.append("- None requested")
        out += ["\n### Clarification message to requester\n", markdown_literal_block(validation.get("clarification_message"))]
    else:
        out += ["\n## 5. Ticket Intent Validation\n", "Not run for this ticket."]
    if evidence_assessment:
        e = evidence_assessment
        source = "Synthetic Ticket Lab screenshots" if synthetic_evidence else "Analyst-uploaded screenshots"
        out += ["\n## 6. Screenshot Evidence Reassessment\n",
                AI_UNVERIFIED_NOTICE,
                *_assessment_line(assessment_links, "evidence"),
                SCREENSHOT_ATTRIBUTION_NOTICE,
                f"**Evidence provenance:** {source}; no live console access. Image content and vendor UI labels may be synthetic or inaccurate.",
                f"- AI conclusion status (unverified): {_s(e.get('conclusion_status'))}",
                f"- AI assessment of requested action: {_s(e.get('requested_action_assessment'))}",
                f"- AI-generated conclusion: {_s(e.get('conclusion'))}"]
        if evidence_provenance:
            out.append("\n### Screenshot register\n")
            for image in evidence_provenance:
                name = _s(image.get("filename") or image.get("label"))
                out.append(
                    f"- **{_s(image['id'])}** · {_s(image['source'])} · {name} · {_s(image['mime_type'])}"
                    f" · Submitted image SHA256 {_s(image['sha256'])}"
                )
        for kind, heading in (
            ("screenshot", "AI observations attributed to screenshots"),
            ("ticket", "AI observations attributed to the ticket"),
            ("unattributed", "Unattributed model claims"),
        ):
            group = [item for item in e.get("observations", []) if item.get("source_kind", "unattributed") == kind]
            if group:
                out.append(f"\n### {heading}\n")
            for obs in group:
                confidence = f" ({_s(obs.get('confidence'))} model confidence)" if kind != "unattributed" else ""
                out.append(f"- **{_s(obs.get('source'))}**{confidence}: {_s(obs.get('observation'))}")
        out += ["\n### AI hypotheses to verify\n"]
        for h in e.get("hypotheses", []):
            out.append(f"- **{_s(h.get('hypothesis'))}**\n  - Model-cited support: {_s(h.get('supporting_evidence'))}\n  - Missing evidence: {_s(h.get('missing_evidence'))}")
        if not e.get("hypotheses"):
            out.append("- None")
        out += ["\n### Recommended next steps\n", _bullet(e.get("recommended_next_steps")),
                "\n### Additional evidence requested\n"]
        for item in e.get("next_evidence_requests", []):
            out.append(f"- **{_s(item.get('source'))}** — {_s(item.get('what_to_capture'))}. Reason: {_s(item.get('why'))}")
        if not e.get("next_evidence_requests"):
            out.append("- None")
        out += ["\n### Updated clarification message\n", markdown_literal_block(e.get("clarification_message"))]
    else:
        out += ["\n## 6. Screenshot Evidence Reassessment\n", "Not run for this ticket."]
    out += ["\n## 7. Analyst Verification Checklist\n",
            "- [ ] Confirm ticket identity, endpoint and asset context.",
            "- [ ] Verify timestamps and whether screenshots refer to the same endpoint and time period.",
            "- [ ] Verify any vendor-specific commands, event IDs and UI paths against authoritative documentation.",
            "- [ ] Distinguish observed evidence from hypotheses and root-cause claims.",
            "- [ ] Confirm remediation authorization before making environment changes.",
            "- [ ] Redact confidential data before sharing or exporting the report.",
            "\n*Generated by EDR Ticket Copilot. This report does not certify a security incident or its root cause.*"]
    return "\n\n".join(out) + "\n"


if __name__ == "__main__":
    demo = generate_investigation_report("Synthetic example", validation={"product": "unknown", "assessment": "Needs Clarification"})
    assert "Ticket Intent Validation" in demo
    print("Report v2 smoke test passed.")
