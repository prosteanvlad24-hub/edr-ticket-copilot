"""Payload disclosures shared by the supported Gemini entry points."""

TICKET_DISCLOSURE = (
    "Destination: Google Gemini. Sends the committed ticket text. Separate asset criticality, offline hours, "
    "endpoint counts, local findings, screenshots, and other case evidence are excluded."
)
EVIDENCE_DISCLOSURE = (
    "Destination: Google Gemini. Sends the committed ticket text, selected prepared screenshot bytes, screenshot IDs "
    "and source labels, and prior AI ticket validation if available. Separate asset criticality, offline hours, "
    "endpoint counts, local findings, filenames, hashes, and other case evidence are excluded."
)
CATALOG_DISCLOSURE = "Destination: Google Gemini. Requests the first page of model metadata. No case data is sent."


def confirm_cli(disclosure):
    """Require a new affirmative response for this one CLI request."""
    print(disclosure)
    if input("Authorize this submission? Type yes to send: ").strip().casefold() != "yes":
        raise RuntimeError("Google Gemini submission canceled.")
