
from severity_engine import assess_severity

scenarios = [
    ("Workstation offline", "agent_offline", "medium", 48, 1),
    ("Critical server offline", "agent_offline", "critical", 48, 1),
    ("Multiple endpoints offline", "agent_offline", "high", 48, 15),
    ("Installation failure", "installation_failure", "low", 0, 1),
]

for name, category, criticality, hours, endpoints in scenarios:
    result = assess_severity(
        category=category,
        asset_criticality=criticality,
        offline_hours=hours,
        affected_endpoints=endpoints
    )

    print(f"\nScenario: {name}")
    print(f"Severity: {result['severity']}")
    print(f"Score: {result['score']}")
    print(f"Reasons: {result['reasons']}")
