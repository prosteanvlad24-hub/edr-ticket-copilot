"""Presentation boundaries for untrusted content and external failures."""

from dataclasses import dataclass
import logging
import re
from uuid import uuid4


AI_UNVERIFIED_NOTICE = "AI-generated assessment. Analyst verification has not been recorded."
SCREENSHOT_ATTRIBUTION_NOTICE = "A screenshot ID identifies the cited source. Verify each claim against the original evidence."
AI_EVIDENCE_STATUS_LABEL = "AI evidence assessment included (unverified)"

_LOG = logging.getLogger("edr.diagnostics")
_PROVIDER_ERRORS = {
    400: ("invalid_request", "Google Gemini rejected the request."),
    401: ("provider_access", "Check the Google Gemini configuration and permissions."),
    403: ("provider_access", "Check the Google Gemini configuration and permissions."),
    404: ("model_unavailable", "The configured Google Gemini model is unavailable."),
    429: ("rate_limit", "Google Gemini is rate-limiting requests. Wait before authorizing a retry."),
}


@dataclass(frozen=True)
class FailureNotice:
    message: str
    reference: str


def record_failure(operation, error, summary, *, provider=False):
    """Log a fixed operation and category. Exception text never crosses this boundary."""
    category, message = "operation_failed", summary
    if isinstance(error, TimeoutError):
        category = "timeout"
        if provider:
            message = "The Google Gemini request timed out."
    elif isinstance(error, ConnectionError):
        category = "connection"
        if provider:
            message = "Could not connect to Google Gemini."
    elif provider:
        code = getattr(error, "code", None)
        if type(code) is int:
            if 500 <= code <= 599:
                category, message = "provider_unavailable", "Google Gemini is temporarily unavailable."
            else:
                category, message = _PROVIDER_ERRORS.get(code, (category, message))
        elif isinstance(error, ValueError):
            category, message = "invalid_data", "The request or the Google Gemini response could not be processed."
    reference = uuid4().hex[:10]
    _LOG.warning("Operation %s failed [%s]; reference %s", operation, category, reference)
    return FailureNotice(message, reference)


def failure_text(notice):
    if isinstance(notice, FailureNotice):
        return f"{notice.message} Diagnostic reference: {notice.reference}."
    return "Diagnostic details are unavailable."


def _literal_text(value):
    return str(value if value is not None else "Not available").replace("\x00", "")


def markdown_literal(value):
    """Put a single-line value inside a CommonMark code span of safe length."""
    text = " ".join(_literal_text(value).splitlines()).strip() or "Not available"
    size = max((len(run) for run in re.findall(r"`+", text)), default=0) + 1
    fence = "`" * size
    return f"{fence} {text} {fence}"


def markdown_literal_block(value):
    """Keep every dynamic line in an indented code block."""
    lines = _literal_text(value).splitlines() or ["Not available"]
    return "\n".join(f"    {line}" for line in lines)
