"""Read the public files of a synthetic Ticket Lab run."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from evidence_inputs import MAX_IMAGE_BYTES, MAX_IMAGES, prepare_images

TICKET_ID = re.compile(r"INC-[0-9]{5}")
CRITICALITIES = ("low", "medium", "high", "critical")
MAX_WIDGET_INTEGER = 2**53 - 1


@dataclass(frozen=True)
class LabCase:
    run: str
    ticket_id: str
    description: str
    asset_criticality: str
    offline_hours: int
    affected_endpoints: int
    images: tuple[tuple[str, bytes], ...]


def list_runs(root: Path) -> list[Path]:
    return sorted(
        (
            path for path in root.glob("run_*")
            if not path.is_symlink() and path.is_dir() and (path / "manifest.json").is_file()
        ),
        reverse=True,
    )


def _public_path(run: Path, *parts: str) -> Path:
    path = run.joinpath(*parts)
    if path.resolve() != path:
        raise ValueError("Ticket Lab files must be stored directly inside the run.")
    return path


def _read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return data


def read_catalog(run: Path) -> dict[str, str]:
    catalog = {}
    for entry in _read_tickets(run.resolve()):
        ticket_id = entry["id"]
        title = entry.get("title")
        catalog[ticket_id] = title if isinstance(title, str) else ticket_id
    return catalog


def _read_tickets(run: Path) -> list[dict]:
    entries = _read_object(_public_path(run, "manifest.json")).get("tickets")
    if not isinstance(entries, list):
        raise ValueError("The run manifest must contain a ticket list.")
    ids = set()
    for entry in entries:
        ticket_id = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(ticket_id, str) or not TICKET_ID.fullmatch(ticket_id) or ticket_id in ids:
            raise ValueError("The run manifest contains an invalid or duplicate ticket ID.")
        ids.add(ticket_id)
    return entries


def list_evidence(run: Path, ticket_id: str) -> list[str]:
    if not TICKET_ID.fullmatch(ticket_id):
        raise ValueError("Invalid Ticket Lab ticket ID.")
    run = run.resolve()
    name_pattern = re.compile(re.escape(ticket_id) + r"_[0-9a-f]{6}\.png")
    index = _public_path(run, "evidence_manifest.json")
    directory = _public_path(run, "evidence")
    if index.exists():
        manifest = _read_object(index).get("tickets")
        if not isinstance(manifest, dict):
            raise ValueError("The evidence manifest must contain a ticket map.")
        filenames = manifest.get(ticket_id, [])
        if not isinstance(filenames, list) or any(
            not isinstance(name, str) or not name_pattern.fullmatch(name) for name in filenames
        ):
            raise ValueError("The evidence manifest contains an invalid file name.")
    else:
        # The original CLI wrote neutral screenshot names but had no public index.
        filenames = [path.name for path in directory.glob(f"{ticket_id}_*.png") if name_pattern.fullmatch(path.name)]
    return sorted(set(filenames))


def read_case(run: Path, ticket_id: str, filenames: list[str]) -> LabCase:
    run = run.resolve()
    entries = _read_tickets(run)
    entry = next((item for item in entries if item["id"] == ticket_id), None)
    if entry is None:
        raise ValueError("The selected ticket does not exist in this run.")
    context = entry.get("context")
    if not isinstance(context, dict):
        raise ValueError("The selected ticket is missing its incident context.")
    criticality = context.get("asset_criticality")
    hours = context.get("hours_since_agent")
    endpoints = context.get("affected_endpoints")
    if (
        criticality not in CRITICALITIES
        or type(hours) is not int or not 0 <= hours <= MAX_WIDGET_INTEGER
        or type(endpoints) is not int or not 1 <= endpoints <= MAX_WIDGET_INTEGER
    ):
        raise ValueError("The selected ticket has an invalid incident context.")

    available = set(list_evidence(run, ticket_id))
    if len(filenames) > MAX_IMAGES or len(set(filenames)) != len(filenames) or not available.issuperset(filenames):
        raise ValueError(f"Select up to {MAX_IMAGES} different screenshots for this ticket.")
    description = _public_path(run, "tickets", f"{ticket_id}.txt").read_text(encoding="utf-8").strip()
    if not description:
        raise ValueError("The selected ticket is empty.")
    raw_images = []
    for name in filenames:
        with _public_path(run, "evidence", name).open("rb") as stream:
            raw_images.append((name, stream.read(MAX_IMAGE_BYTES + 1)))
    return LabCase(run.name, ticket_id, description, criticality, hours, endpoints, tuple(prepare_images(raw_images)))
