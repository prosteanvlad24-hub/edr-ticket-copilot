
import re


_LEVELS = {name: rank for rank, name in enumerate(("Informational", "Low", "Medium", "High", "Critical"))}
_SOURCE_SEVERITY = re.compile(
    r"^\s*(?:(?:source(?:[- ]reported)?|alert|reported|edr)\s+)?severity\s*[:=]\s*"
    r"(critical|high|medium|low|informational|info)\s*$", re.I,
)


def source_reported_severity(description: str) -> str | None:
    """Read structured source severity from the ticket header only."""
    levels = []
    for line in description.strip().splitlines():
        if not line.strip() or re.match(r"^\s*(?:analyst|operator|reviewer|comments?|observations|timeline|process tree)\b", line, re.I):
            break
        if match := _SOURCE_SEVERITY.fullmatch(line):
            severity = match.group(1).title()
            levels.append("Informational" if severity == "Info" else severity)
    return max(levels, key=_LEVELS.get, default=None)


def assess_severity(
    category: str,
    asset_criticality: str = "medium",
    offline_hours: int = 0,
    affected_endpoints: int = 1,
    *,
    source_severity: str | None = None,
    ransomware_signals: tuple[str, ...] = (),
) -> dict:
    """
    Estimate ticket severity using deterministic rules.
    Intended for triage support, not automatic escalation.
    """

    category_scores = {
        "ransomware_behavior": 4,
        "malware_detection": 3,
        "suspicious_execution": 3,
        "agent_offline": 2,
        "installation_failure": 1,
        "outdated_definitions": 2,
        "unknown": 1
    }


    score = category_scores.get(category, 1)
    reasons = [f"Classification {category.replace('_', ' ')} (+{score})."]
    for behavior in dict.fromkeys(ransomware_signals):
        score += 1
        reasons.append(f"Ticket reports {behavior.lower()} (+1).")

    asset_scores = {
        "low": 0,
        "medium": 1,
        "high": 2,
        "critical": 3
    }

    asset_score = asset_scores.get(asset_criticality, 1)
    score += asset_score
    reasons.append(f"Affected asset criticality {asset_criticality} (+{asset_score}).")

    if category == "agent_offline":
        if offline_hours >= 48:
            score += 2
            reasons.append(
                f"EDR agent offline for {offline_hours} hours."
            )
        elif offline_hours >= 24:
            score += 1
            reasons.append(
                f"EDR agent offline for {offline_hours} hours."
            )

    if affected_endpoints >= 10:
        score += 3
        reasons.append(
            f"{affected_endpoints} endpoints affected."
        )
    elif affected_endpoints >= 3:
        score += 1
        reasons.append(
            f"{affected_endpoints} endpoints affected."
        )

    if score >= 8:
        severity = "Critical"
    elif score >= 6:
        severity = "High"
    elif score >= 4:
        severity = "Medium"
    else:
        severity = "Low"

    source_level = (source_severity or "").title()
    if source_level not in _LEVELS:
        source_level = None
    priority = max((source_level, severity), key=lambda level: _LEVELS.get(level, -1))
    major_disagreement = source_level is not None and abs(_LEVELS[source_level] - _LEVELS[severity]) >= 2
    if source_level and _LEVELS[source_level] > _LEVELS[severity]:
        priority_rationale = "Retain the higher source rating for investigation until an analyst reconciles the evidence."
    elif source_level == severity:
        priority_rationale = "The source rating and independent heuristic support this investigation priority."
    else:
        priority_rationale = "The independent heuristic supports this investigation priority."

    return {
        "severity": severity,
        "score": score,
        "reasons": reasons,
        "source_severity": source_level,
        "recommended_priority": priority,
        "major_disagreement": major_disagreement,
        "priority_rationale": priority_rationale,
    }
