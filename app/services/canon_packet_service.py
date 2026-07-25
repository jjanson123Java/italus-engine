"""
Project-local canon/control packet service.

This service is an inert boundary for future project-local control and runtime
knowledge packs. It reports expected packet locations and readiness only.

It does not generate packets, call prompt construction, call providers, call
validators, write runtime state, or unlock generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.templates.template_registry import get_template


CANON_PACKET_SERVICE_MARKER = "project-local-control-pack-boundary-20260714"
CANON_PACKET_SERVICE_VERSION = "stage9_project_local_control_pack_boundary_v1"

RUNTIME_CONTEXT_PACK_ROLE = "runtime_context_pack"
SOURCE_DERIVE_FROM_PROJECT_BOOKS = "derive_from_project_books"


@dataclass(frozen=True)
class CanonPacketStatus:
    canon_id: str
    label: str
    role: str
    source_strategy: str
    relative_path: str
    exists: bool
    status: str
    required: bool
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "canon_id": self.canon_id,
            "label": self.label,
            "role": self.role,
            "source_strategy": self.source_strategy,
            "relative_path": self.relative_path,
            "exists": self.exists,
            "status": self.status,
            "required": self.required,
            "description": self.description,
        }


def get_canon_packet_status(project_id: str) -> dict[str, Any]:
    """Return read-only project-local canon/control packet status.

    The project manifest is loaded to resolve ProjectContext and template
    configuration. This function does not create packet files and does not
    mutate project runtime storage.
    """

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    manifest_dict = manifest.to_dict() if hasattr(manifest, "to_dict") else dict(manifest)
    return get_canon_packet_status_for_context(context, manifest_dict)


def get_canon_packet_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return packet readiness for an already resolved ProjectContext.

    Packet paths are resolved under the project-local project directory even
    when template seed files are legacy references. This keeps the boundary
    ready for future project-local control-pack materialization without reading
    or copying legacy global packs.
    """

    manifest_payload = dict(manifest or {})
    template = get_template(context.template_id, context.genre)
    packet_statuses = [
        status.to_dict()
        for status in iter_canon_packet_statuses(context, template, manifest_payload)
    ]

    missing_required = [
        item["canon_id"]
        for item in packet_statuses
        if item["required"] and item["status"] != "ready"
    ]

    return {
        "status": "ok",
        "service": CANON_PACKET_SERVICE_MARKER,
        "version": CANON_PACKET_SERVICE_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "storage_mode": context.storage_mode,
        "packet_ready": not missing_required,
        "generation_enabled": False,
        "validation_enabled": False,
        "exports_enabled": False,
        "provider_execution_enabled": False,
        "packet_count": len(packet_statuses),
        "missing_required_count": len(missing_required),
        "missing_required": missing_required,
        "packets": packet_statuses,
        "message": "Project-local control packet boundary loaded. Generation remains locked.",
    }


def iter_canon_packet_statuses(
    context: ProjectContext,
    template: dict[str, Any],
    manifest: dict[str, Any] | None = None,
) -> tuple[CanonPacketStatus, ...]:
    """Return the project-local runtime/control packet contract from a template."""

    manifest_payload = dict(manifest or {})
    statuses: list[CanonPacketStatus] = []

    for group in template.get("canon_groups") or []:
        for item in group.get("items") or []:
            if item.get("role") != RUNTIME_CONTEXT_PACK_ROLE:
                continue

            statuses.extend(_statuses_for_packet_item(context, item, manifest_payload))

    return tuple(statuses)


def _statuses_for_packet_item(
    context: ProjectContext,
    item: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[CanonPacketStatus, ...]:
    source_strategy = str(item.get("source_strategy") or "")
    if source_strategy == SOURCE_DERIVE_FROM_PROJECT_BOOKS:
        return _book_packet_statuses(context, item, manifest)

    source_files = item.get("source_files") or []
    statuses = [
        _packet_status(context, item, str(relative_path), source_strategy)
        for relative_path in source_files
        if str(relative_path).strip()
    ]
    return tuple(statuses)


def _book_packet_statuses(
    context: ProjectContext,
    item: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[CanonPacketStatus, ...]:
    file_pattern = str(item.get("file_pattern") or "").strip()
    if not file_pattern:
        return tuple()

    book_count = _positive_int(manifest.get("book_count"), default=1)
    statuses: list[CanonPacketStatus] = []

    for book_number in range(1, book_count + 1):
        relative_path = file_pattern.format(book_number=book_number)
        derived_item = dict(item)
        derived_item["canon_id"] = f"{item.get('canon_id')}_{book_number:02d}"
        derived_item["label"] = f"{item.get('label') or 'Book Knowledge Pack'} {book_number:02d}"
        statuses.append(
            _packet_status(
                context,
                derived_item,
                relative_path,
                str(item.get("source_strategy") or ""),
            )
        )

    return tuple(statuses)


def _packet_status(
    context: ProjectContext,
    item: dict[str, Any],
    relative_path: str,
    source_strategy: str,
) -> CanonPacketStatus:
    clean_path = _clean_relative_path(relative_path)
    packet_path = context.project_dir / clean_path
    exists = packet_path.exists()

    return CanonPacketStatus(
        canon_id=str(item.get("canon_id") or clean_path),
        label=str(item.get("label") or item.get("canon_id") or clean_path),
        role=str(item.get("role") or RUNTIME_CONTEXT_PACK_ROLE),
        source_strategy=source_strategy,
        relative_path=_relative(context.project_root, packet_path),
        exists=exists,
        status="ready" if exists else "missing",
        required=bool(item.get("required")),
        description="Project-local packet exists." if exists else "Project-local packet has not been generated.",
    )


def _clean_relative_path(relative_path: str) -> Path:
    clean_path = relative_path.replace("\\\\", "/").replace("\\", "/").lstrip("/")
    parts = [part for part in clean_path.split("/") if part not in {"", ".", ".."}]
    return Path(*parts)


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
