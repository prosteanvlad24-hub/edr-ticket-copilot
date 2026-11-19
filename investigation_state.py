"""Case data and transitions that survive Streamlit widget cleanup."""

from dataclasses import dataclass, field

from evidence_inputs import evidence_fingerprint, public_validation, screenshot_provenance

MANUAL = "Manual upload"
LAB = "Ticket Lab"


@dataclass(frozen=True)
class Ticket:
    description: str
    criticality: str = "medium"
    offline_hours: int = 48
    affected_endpoints: int = 1
    lab_run: str | None = None
    lab_id: str | None = None

    @property
    def identity(self):
        return self.lab_run, self.lab_id, self.description


DEFAULT_TICKET = Ticket(
    "CrowdStrike Falcon sensor stopped communicating with the management "
    "console 48 hours ago. The affected endpoint runs Windows 11."
)


@dataclass(frozen=True)
class Evidence:
    labels: tuple[str, ...] = ()
    images: tuple[tuple[str, bytes], ...] = ()
    filenames: tuple[str, ...] = ()


@dataclass
class Investigation:
    step: int = 0
    revision: int = 0
    ticket: Ticket = DEFAULT_TICKET
    manual_draft: Ticket = DEFAULT_TICKET
    entry_source: str = "Manual entry"
    results: dict = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    evidence_source: str = MANUAL
    evidence_by_source: dict[str, Evidence] = field(default_factory=dict)
    evidence_errors: dict[str, str] = field(default_factory=dict)
    lab_selection: tuple[str, ...] | None = None
    upload_revision: int = 0
    evidence_revision: int = 0
    consent: str | None = None
    reviewed_fingerprint: str | None = None
    reviewed_evidence: dict | None = None
    reassessment_error: str | None = None

    def commit_ticket(self, ticket: Ticket) -> None:
        if self.ticket.identity != ticket.identity:
            self.revision += 1
            self.results.clear()
            self.errors.clear()
            self.evidence_source = LAB if ticket.lab_id else MANUAL
            self.evidence_by_source.clear()
            self.evidence_errors.clear()
            self.lab_selection = None
            self.upload_revision = 0
            self.invalidate_reassessment()
        elif self.ticket != ticket:
            self.results.pop("triage", None)
            self.errors.pop("triage", None)
        self.ticket = ticket

    @property
    def evidence(self) -> Evidence:
        return self.evidence_by_source.get(self.evidence_source, Evidence())

    def set_evidence_source(self, source: str) -> None:
        if source != self.evidence_source:
            self.evidence_source = source
            self.invalidate_reassessment()

    def set_evidence(self, source: str, evidence: Evidence, error: str | None = None) -> None:
        previous = self.evidence_by_source.get(source, Evidence())
        if source == self.evidence_source and previous != evidence:
            self.invalidate_reassessment()
        self.evidence_by_source[source] = evidence
        if error:
            self.evidence_errors[source] = error
        else:
            self.evidence_errors.pop(source, None)

    def clear_manual_evidence(self) -> None:
        self.set_evidence(MANUAL, Evidence())
        self.upload_revision += 1

    @property
    def prior_validation(self) -> dict | None:
        return public_validation(self.results.get("validation"))

    def save_validation(self, result: dict) -> None:
        previous = self.prior_validation
        self.results["validation"] = public_validation(result)
        if self.prior_validation != previous:
            self.invalidate_reassessment()

    def invalidate_reassessment(self) -> None:
        self.evidence_revision += 1
        self.consent = None
        self.reviewed_fingerprint = None
        self.reviewed_evidence = None
        self.reassessment_error = None

    @property
    def fingerprint(self) -> str | None:
        if not self.evidence.images or self.evidence_source in self.evidence_errors:
            return None
        return evidence_fingerprint(
            self.revision, self.ticket.description, self.evidence_source,
            self.evidence.images, self.prior_validation,
            labels=self.evidence.labels, filenames=self.evidence.filenames,
        )

    @property
    def evidence_provenance(self) -> list[dict]:
        return screenshot_provenance(
            self.evidence.images, self.evidence_source, self.evidence.labels, self.evidence.filenames,
        )

    @property
    def evidence_assessment(self) -> dict | None:
        fingerprint = self.fingerprint
        if fingerprint and fingerprint == self.reviewed_fingerprint:
            return self.reviewed_evidence
        return None
