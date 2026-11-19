
from report_engine import generate_incident_report
from rules_engine import classify_ticket, get_troubleshooting_steps
from severity_engine import assess_severity
from ioc_engine import extract_iocs


description = (
    "Microsoft Defender detected suspicious PowerShell "
    "execution on endpoint 192.168.1.50. "
    "Connection attempted to suspicious-example.com. "
    "URL: https://suspicious-example.com/payload.exe "
    "MD5: d41d8cd98f00b204e9800998ecf8427e"
)

category = classify_ticket(description)

rule_result = {
    "category": category,
    "steps": get_troubleshooting_steps(category),
    "severity": assess_severity(
        category=category,
        asset_criticality="medium",
        offline_hours=0,
        affected_endpoints=1
    ),
    "context": ("medium", 0, 1)
}

ioc_result = {
    "indicators": extract_iocs(description)
}

report = generate_incident_report(
    description=description,
    rule_result=rule_result,
    ioc_result=ioc_result,
    ai_analysis=None
)

with open(
    "EDR_Incident_Report_Test.md",
    "w",
    encoding="utf-8"
) as file:
    file.write(report)

assert "# EDR Incident Investigation Report" in report
assert "suspicious_execution" in report
assert "192.168.1.50" in report
assert "suspicious-example.com" in report
assert "Pending Human Review" in report

print("PASS: Full incident report generated successfully!")
print("File: EDR_Incident_Report_Test.md")
