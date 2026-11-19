"""Prepare the analyst-visible inputs shared by both screenshot sources."""

import hashlib
import io
import json

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
ALLOWED_MIME = frozenset(IMAGE_TYPES.values())
VALIDATION_TEXT_FIELDS = (
    "product", "reported_issue", "requested_action", "assessment",
    "reasoning", "clarification_message",
)
EVIDENCE_REQUEST_FIELDS = ("source", "what_to_capture", "why")


def public_validation(validation: dict | None) -> dict | None:
    """Copy the validation fields the screenshot model is allowed to receive."""
    if validation is None:
        return None
    result = {
        field: validation[field] for field in VALIDATION_TEXT_FIELDS
        if isinstance(validation.get(field), str)
    }
    missing = validation.get("missing_information")
    if isinstance(missing, list):
        result["missing_information"] = [item for item in missing if isinstance(item, str)]
    requests = validation.get("evidence_requests")
    if isinstance(requests, list):
        result["evidence_requests"] = [
            {field: item[field] for field in EVIDENCE_REQUEST_FIELDS}
            for item in requests[:3]
            if isinstance(item, dict) and all(
                isinstance(item.get(field), str) for field in EVIDENCE_REQUEST_FIELDS
            )
        ]
    return result


def prepare_images(images: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Verify, orient, and re-encode screenshots using only visible image data."""
    if len(images) > MAX_IMAGES:
        raise ValueError(f"Select no more than {MAX_IMAGES} screenshots.")
    if not images:
        return []

    from PIL import Image, ImageOps, ImageSequence

    prepared = []
    for name, raw in images:
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(f"{name}: each screenshot must be nonempty and at most 8 MiB.")
        try:
            with Image.open(io.BytesIO(raw), formats=tuple(IMAGE_TYPES)) as source:
                if Image.MAX_IMAGE_PIXELS and source.width * source.height > Image.MAX_IMAGE_PIXELS:
                    raise ValueError("image dimensions exceed the decoder limit")
                image_format = source.format
                source.verify()
            with Image.open(io.BytesIO(raw), formats=(image_format,)) as source:
                frame_pixels = source.width * source.height * getattr(source, "n_frames", 1)
                if Image.MAX_IMAGE_PIXELS and frame_pixels > Image.MAX_IMAGE_PIXELS:
                    raise ValueError("image sequence exceeds the decoder limit")
                options = {"quality": 95} if image_format == "JPEG" else {}
                frames = []
                durations = []
                for frame in ImageSequence.Iterator(source):
                    oriented = ImageOps.exif_transpose(frame)
                    if "transparency" in oriented.info:
                        oriented = oriented.convert("RGBA")
                    oriented.info.clear()
                    frames.append(oriented)
                    durations.append(frame.info.get("duration", 0))
                if len(frames) > 1:
                    options.update(
                        save_all=True, append_images=frames[1:],
                        duration=durations, loop=source.info.get("loop", 0),
                    )
                with io.BytesIO() as buffer:
                    frames[0].save(buffer, format=image_format, **options)
                    payload = buffer.getvalue()
        except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError(f"{name}: could not decode a valid PNG, JPEG, or WebP screenshot.") from exc
        if len(payload) > MAX_IMAGE_BYTES:
            raise ValueError(f"{name}: the prepared screenshot exceeds 8 MiB.")
        prepared.append((IMAGE_TYPES[image_format], payload))
    return prepared


def screenshot_provenance(images, source, labels=(), filenames=()):
    """Identify each submitted image using the prepared bytes, in submission order."""
    return [
        {
            "id": f"E{index + 1:02d}",
            "source": "Ticket Lab" if source == "Ticket Lab" else "Analyst upload",
            "label": labels[index] if index < len(labels) else f"Screenshot {index + 1}",
            "filename": filenames[index] if index < len(filenames) else None,
            "mime_type": mime,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        for index, (mime, raw) in enumerate(images)
    ]


def evidence_fingerprint(case_revision, ticket, source, images, previous_validation, *, labels=(), filenames=()):
    """Bind consent and results to the exact case and model inputs."""
    payload = {
        "case_revision": case_revision,
        "ticket": ticket,
        "source": source,
        "previous_validation": previous_validation,
        "images": screenshot_provenance(images, source, labels, filenames),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
