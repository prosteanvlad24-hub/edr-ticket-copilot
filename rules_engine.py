
import re


_COMMENT_SECTION = re.compile(r"^\s*(?:(?:analyst|operator|reviewer)\s+(?:comments?|notes?)|comments?)\s*(?::|$)", re.I)
_RANSOMWARE_SIGNALS = (
    ("Shadow-copy deletion", re.compile(
        r"\bshadow cop(?:y|ies) (?:deletion|(?:were )?deleted|removal|removed)\b"
        r"|\bdelet(?:e|ed|ing) (?:the )?shadow(?: cop(?:y|ies)|s)\b", re.I)),
    ("Recovery disablement", re.compile(
        r"\b(?:system )?recovery (?:disablement|(?:was )?disabled)\b"
        r"|\bdisabl(?:e|ed|ing) (?:system )?recovery\b|\brecoveryenabled\s+(?:no|false|0)\b", re.I)),
    ("High-volume file renaming or encryption", re.compile(
        r"\b(?:mass|bulk|rapid) (?:file )?(?:renam(?:e|ing)|encryption)\b"
        r"|\b(?:[1-9]\d{2,}|[1-9]\d{0,2}(?:,\d{3})+) files (?:were )?(?:renamed|encrypted)\b", re.I)),
)
_NEGATED_BEFORE = re.compile(
    r"\b(?:no|not|never|without|simulate[ds]?|prevent(?:ed)?|block(?:ed)?)\b[^,;.!?]{0,36}$", re.I,
)
_NEGATED_AFTER = re.compile(r"^\s*(?:was |were )?(?:prevented|blocked|denied|simulated)\b", re.I)


def reported_ticket_text(description: str) -> str:
    """Keep reported telemetry separate from explicitly marked analyst comments."""
    lines = []
    for line in description.splitlines():
        if _COMMENT_SECTION.match(line):
            break
        lines.append(line)
    return "\n".join(lines)


def ransomware_signals(description: str) -> tuple[str, ...]:
    """Identify distinct reported behaviors. One signal alone is not a classification."""
    lines = reported_ticket_text(description).splitlines()
    return tuple(
        label for label, pattern in _RANSOMWARE_SIGNALS
        if any(
            not _NEGATED_BEFORE.search(line[:match.start()])
            and not _NEGATED_AFTER.match(line[match.end():])
            for line in lines for match in pattern.finditer(line)
        )
    )


def classify_ticket(description: str) -> str:
    """
    Classify endpoint security tickets using
    deterministic keyword-based rules.
    """

    text = reported_ticket_text(description).lower()
    if len(ransomware_signals(description)) >= 2:
        return "ransomware_behavior"

    malware_keywords = [
        "malware detected",
        "detected malware",
        "malicious file",
        "malicious executable",
        "trojan detected",
        "ransomware detected",
        "virus detected",
        "quarantined malware",
        "malware detection"
    ]

    suspicious_keywords = [
        "suspicious activity",
        "suspicious execution",
        "suspicious powershell",
        "encoded powershell",
        "unusual process execution",
        "suspicious command",
        "suspicious process",
        "potentially malicious execution"
    ]

    offline_keywords = [
        "offline",
        "not reporting",
        "stopped communicating",
        "not communicating",
        "disconnected"
    ]

    installation_keywords = [
        "installation failed",
        "deployment unsuccessful",
        "failed to install",
        "installation error"
    ]

    update_keywords = [
        "definitions have not updated",
        "signatures are three days out of date",
        "outdated definitions",
        "signature update failed"
    ]

    if any(word in text for word in malware_keywords):
        return "malware_detection"

    if any(word in text for word in suspicious_keywords):
        return "suspicious_execution"

    if any(word in text for word in offline_keywords):
        return "agent_offline"

    if any(word in text for word in installation_keywords):
        return "installation_failure"

    if any(word in text for word in update_keywords):
        return "outdated_definitions"

    return "unknown"


def get_troubleshooting_steps(category: str) -> list[str]:
    """
    Return investigation recommendations
    for the classified incident category.
    """

    troubleshooting = {
        "ransomware_behavior": [
            "Escalate for incident-response triage and validate the alert against endpoint telemetry.",
            "Correlate recovery changes and file operations with process lineage and the incident timeline.",
            "Determine affected hosts, shares, and accounts, and verify backup availability separately.",
            "Preserve relevant evidence and coordinate any containment decision with authorized responders.",
        ],
        "malware_detection": [
            "Review the EDR detection details and alert timeline.",
            "Identify the affected endpoint, user, and file path.",
            "Collect available file hashes and process metadata.",
            "Investigate the process tree and related activity.",
            "Assess containment needs according to the incident response playbook."
        ],

        "suspicious_execution": [
            "Review the suspicious process and its parent process.",
            "Inspect command-line arguments and execution context.",
            "Check PowerShell and relevant Windows event logs.",
            "Investigate related network connections and file activity.",
            "Correlate the activity with other EDR alerts and assess escalation."
        ],

        "agent_offline": [
            "Verify endpoint network connectivity.",
            "Check the EDR agent service status.",
            "Verify connectivity to the management platform.",
            "Check the last successful communication timestamp.",
            "Review agent logs for connectivity errors."
        ],

        "installation_failure": [
            "Check operating system compatibility.",
            "Verify installation permissions.",
            "Review installation logs and error codes.",
            "Check for conflicting security software.",
            "Verify installation package integrity."
        ],

        "outdated_definitions": [
            "Check the last successful definition update.",
            "Verify connectivity to update servers.",
            "Review update-related error messages.",
            "Check available disk space.",
            "Verify update policies."
        ]
    }

    return troubleshooting.get(
        category,
        ["Manual investigation required."]
    )
