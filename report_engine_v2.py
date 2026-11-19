"""Evidence-aware Markdown incident report. No AI/API calls are made here."""
from datetime import datetime, timezone
from typing import Any


def _s(value: Any) -> str:
    return str(value if value is not None else "Not available").replace("\x00", "")


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
) -> str:
    """Build a consolidated report from already completed analyses only."""
    status = "Evidence reviewed" if evidence_assessment else "Preliminary"
    out = [
        "# EDR Ticket Copilot — Investigation Report v2",
        f"Generated (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Report status:** {status}. Analyst verification required.",
        "**Scope:** Only the supplied ticket and previously submitted evidence were considered. No live environment access.",
        "\n## 1. Original Ticket\n",
        _s(description),
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
                out.append(f"- {_s(item.get('algorithm') or 'Unknown algorithm')} `{_s(item.get('value'))}`")
    else:
        out += ["\n## 3. Extracted Indicators\n", "Not run for this ticket."]
    out += ["\n## 4. Gemini Incident Analysis\n", ai_analysis or "Not run for this ticket."]
    if validation:
        out += ["\n## 5. Ticket Intent Validation\n",
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
        out += ["\n### Clarification message to requester\n", _s(validation.get("clarification_message"))]
    else:
        out += ["\n## 5. Ticket Intent Validation\n", "Not run for this ticket."]
    if evidence_assessment:
        e = evidence_assessment
        source = "Synthetic Ticket Lab screenshots" if synthetic_evidence else "Analyst-uploaded screenshots"
        out += ["\n## 6. Screenshot Evidence Reassessment\n",
                f"**Evidence provenance:** {source}; no live console access. Image content and vendor UI labels may be synthetic or inaccurate.",
                f"- Conclusion status: **{_s(e.get('conclusion_status'))}**",
                f"- Original requested action: **{_s(e.get('requested_action_assessment'))}**",
                f"- Model-assessed conclusion: {_s(e.get('conclusion'))}"]
        if evidence_provenance:
            out.append("\n### Screenshot register\n")
            for image in evidence_provenance:
                name = " ".join(_s(image.get("filename") or image.get("label")).splitlines()).replace("`", "'")
                out.append(
                    f"- **{_s(image['id'])}** · {_s(image['source'])} · `{name}` · {_s(image['mime_type'])}"
                    f" · Submitted image SHA256 `{_s(image['sha256'])}`"
                )
        for kind, heading in (
            ("screenshot", "Screenshot observations"),
            ("ticket", "Ticket-reported observations"),
            ("unattributed", "Unattributed model claims"),
        ):
            group = [item for item in e.get("observations", []) if item.get("source_kind", "unattributed") == kind]
            if group:
                out.append(f"\n### {heading}\n")
            for obs in group:
                confidence = f" ({_s(obs.get('confidence'))} confidence)" if kind != "unattributed" else ""
                out.append(f"- **{_s(obs.get('source'))}**{confidence}: {_s(obs.get('observation'))}")
        out += ["\n### Hypotheses — not confirmed facts\n"]
        for h in e.get("hypotheses", []):
            out.append(f"- **{_s(h.get('hypothesis'))}**\n  - Supporting evidence: {_s(h.get('supporting_evidence'))}\n  - Missing evidence: {_s(h.get('missing_evidence'))}")
        if not e.get("hypotheses"):
            out.append("- None")
        out += ["\n### Recommended next steps\n", _bullet(e.get("recommended_next_steps")),
                "\n### Additional evidence requested\n"]
        for item in e.get("next_evidence_requests", []):
            out.append(f"- **{_s(item.get('source'))}** — {_s(item.get('what_to_capture'))}. Reason: {_s(item.get('why'))}")
        if not e.get("next_evidence_requests"):
            out.append("- None")
        out += ["\n### Updated clarification message\n", _s(e.get("clarification_message"))]
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
