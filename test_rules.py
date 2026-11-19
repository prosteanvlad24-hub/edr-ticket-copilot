
from rules_engine import classify_ticket

test_cases = [
    (
        "Microsoft Defender detected malware on Windows 11",
        "malware_detection"
    ),
    (
        "Suspicious PowerShell execution detected",
        "suspicious_execution"
    ),
    (
        "CrowdStrike sensor stopped communicating",
        "agent_offline"
    ),
    (
        "Trellix agent installation failed",
        "installation_failure"
    ),
    (
        "Antivirus signatures are three days out of date",
        "outdated_definitions"
    ),
    (
        "Microsoft Defender detected suspicious activity",
        "suspicious_execution"
    )
]

for description, expected in test_cases:
    result = classify_ticket(description)
    status = "PASS" if result == expected else "FAIL"

    print(f"{status}: {result} (expected: {expected})")

    assert result == expected, (
        f"Classification failed for: {description}"
    )

print("\nAll classification tests passed!")
