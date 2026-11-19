
import json
from pathlib import Path


def classify_ticket(description):
    description = description.lower()

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

    if any(word in description for word in offline_keywords):
        return "agent_offline"

    elif any(word in description for word in installation_keywords):
        return "installation_failure"

    elif any(word in description for word in update_keywords):
        return "outdated_definitions"

    else:
        return "unknown"


file_path = Path(__file__).with_name("tickets.json")

with open(file_path, "r", encoding="utf-8") as file:
    tickets = json.load(file)

correct_predictions = 0

print("=== EDR Ticket Copilot ===")

for ticket in tickets:
    predicted = classify_ticket(ticket["description"])
    expected = ticket["category"]

    print("-------------------------")
    print("Ticket:", ticket["id"])
    print("Expected:", expected)
    print("Predicted:", predicted)

    if predicted == expected:
        correct_predictions += 1
        print("Result: CORRECT")
    else:
        print("Result: INCORRECT")

accuracy = correct_predictions / len(tickets) * 100

print("-------------------------")
print("Total tickets:", len(tickets))
print("Correct predictions:", correct_predictions)
print(f"Accuracy: {accuracy:.2f}%")
