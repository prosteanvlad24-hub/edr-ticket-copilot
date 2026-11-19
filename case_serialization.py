"""Versioned mapping between Investigation and durable case data."""

from evidence_inputs import screenshot_provenance
from investigation_state import Evidence, Investigation, Ticket

PAYLOAD_VERSION = 1


def _ticket_data(ticket):
    return {
        "description": ticket.description,
        "criticality": ticket.criticality,
        "offline_hours": ticket.offline_hours,
        "affected_endpoints": ticket.affected_endpoints,
        "lab_run": ticket.lab_run,
        "lab_id": ticket.lab_id,
    }


def encode_state(case):
    return {
        "step": case.step,
        "revision": case.revision,
        "ticket": _ticket_data(case.ticket),
        "manual_draft": _ticket_data(case.manual_draft),
        "entry_source": case.entry_source,
        "results": case.results,
        "evidence_source": case.evidence_source,
        "evidence_metadata": {
            source: {
                "labels": evidence.labels,
                "filenames": evidence.filenames,
                "provenance": screenshot_provenance(
                    evidence.images, source, evidence.labels, evidence.filenames,
                ),
            }
            for source, evidence in case.evidence_by_source.items()
        },
        "lab_selection": case.lab_selection,
        "evidence_revision": case.evidence_revision,
        "reviewed_fingerprint": case.reviewed_fingerprint if case.evidence_assessment else None,
        "reviewed_evidence": case.evidence_assessment,
    }


def decode_state(version, data, images):
    if version != PAYLOAD_VERSION:
        raise ValueError(f"Unsupported case payload version {version}")
    selection = data["lab_selection"]
    case = Investigation(
        step=data["step"], revision=data["revision"],
        ticket=Ticket(**data["ticket"]), manual_draft=Ticket(**data["manual_draft"]),
        entry_source=data["entry_source"], results=data["results"],
        evidence_source=data["evidence_source"],
        evidence_by_source={
            source: Evidence(tuple(meta["labels"]), tuple(images.get(source, ())), tuple(meta["filenames"]))
            for source, meta in data["evidence_metadata"].items()
        },
        lab_selection=tuple(selection) if selection is not None else None,
        evidence_revision=data["evidence_revision"],
        reviewed_fingerprint=data["reviewed_fingerprint"], reviewed_evidence=data["reviewed_evidence"],
    )
    if case.evidence_assessment is None:
        case.reviewed_fingerprint = None
        case.reviewed_evidence = None
    return case
