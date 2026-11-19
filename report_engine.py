
from datetime import datetime, timezone


def generate_incident_report(
    description: str,
    rule_result: dict,
    ioc_result: dict,
    ai_analysis: str = None
) -> str:
    """
    Generate a consolidated EDR incident report
    in Markdown format.
    """

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    category = rule_result.get("category", "unknown")
    severity = rule_result.get("severity", {})
    steps = rule_result.get("steps", [])
    context = rule_result.get("context", ("medium", 0, 1))

    asset_criticality, offline_hours, affected_endpoints = context

    indicators = ioc_result.get("indicators", {})

    ipv4 = indicators.get("ipv4", [])
    domains = indicators.get("domains", [])
    urls = indicators.get("urls", [])
    hashes = indicators.get("hashes", {})

    report = [
        "# EDR Incident Investigation Report",
        "",
        f"**Generated:** {timestamp}",
        "**Application:** EDR Ticket Copilot",
        "**Report Type:** Automated Preliminary Assessment",
        "",
        "> This report is generated using automated rules "
        "and optional AI assistance. All findings and "
        "recommendations require human validation.",
        "",
        "---",
        "",
        "## 1. Incident Description",
        "",
        description,
        "",
        "## 2. Incident Context",
        "",
        f"- Asset Criticality: {asset_criticality}",
        f"- Hours Since Agent Communication: {offline_hours}",
        f"- Affected Endpoints: {affected_endpoints}",
        "",
        "## 3. Rule-Based Classification",
        "",
        f"**Predicted Category:** {category}",
        "",
        "## 4. Severity Assessment",
        "",
        f"**Estimated Severity:** {severity.get('severity', 'N/A')}",
        f"**Severity Score:** {severity.get('score', 'N/A')}",
        "",
        "### Severity Reasoning",
        ""
    ]

    reasons = severity.get("reasons", [])

    if reasons:
        for reason in reasons:
            report.append(f"- {reason}")
    else:
        report.append("- No additional reasoning available.")

    report.extend([
        "",
        "## 5. Recommended Troubleshooting Steps",
        ""
    ])

    if steps:
        for index, step in enumerate(steps, start=1):
            report.append(f"{index}. {step}")
    else:
        report.append("No troubleshooting steps available.")

    report.extend([
        "",
        "## 6. Extracted Indicators",
        "",
        "Candidate indicators only. Maliciousness is not confirmed.",
        "",
        "### IPv4 Addresses",
        ""
    ])

    if ipv4:
        for value in ipv4:
            report.append(f"- `{value}`")
    else:
        report.append("None detected.")

    report.extend(["", "### Domains", ""])

    if domains:
        for value in domains:
            report.append(f"- `{value}`")
    else:
        report.append("None detected.")

    report.extend(["", "### URLs", ""])

    if urls:
        for value in urls:
            report.append(f"- `{value}`")
    else:
        report.append("None detected.")

    report.extend(["", "### File Hashes", ""])

    for hash_type in ("MD5", "SHA1", "SHA256"):
        report.append(f"**{hash_type}**")
        report.append("")

        values = hashes.get(hash_type, [])

        if values:
            for value in values:
                report.append(f"- `{value}`")
        else:
            report.append("None detected.")

        report.append("")

    report.extend([
        "## 7. Gemini AI Investigation",
        ""
    ])

    if ai_analysis and ai_analysis.strip():
        report.append(ai_analysis.strip())
    else:
        report.append(
            "AI analysis unavailable or not performed. "
            "The rule-based assessment and extracted "
            "indicators remain available."
        )

    report.extend([
        "",
        "---",
        "",
        "## 8. Analyst Validation",
        "",
        "- [ ] Review incident classification",
        "- [ ] Validate extracted indicators",
        "- [ ] Review severity and asset criticality",
        "- [ ] Verify AI-generated hypotheses",
        "- [ ] Confirm escalation or containment decisions",
        "",
        "**Status:** Pending Human Review",
        ""
    ])

    return "\n".join(report)
