"""
Project-local canon packet generation service.

This service materializes reviewable Markdown knowledge packets from validated,
project-local rendered canon sources.

It does not build prompts, call providers, write runtime memory, modify source
canon, persist generated drafts, export projects, or unlock generation.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import re
import time
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import (
    canon_markdown_renderer_service,
    canon_packet_service,
    canon_validation_service,
)
from app.templates.template_registry import (
    SOURCE_DERIVE_FROM_PROJECT_BOOKS,
    SOURCE_GENERATED_FROM_AUTHOR_CANON,
    get_template,
)


CANON_PACKET_GENERATION_SERVICE_MARKER = "project-canon-packet-generation-boundary-20260725"
CANON_PACKET_GENERATION_SCHEMA_VERSION = "project_canon_packet_generation_v1"

STATUS_BLOCKED = "blocked"
STATUS_READY = "ready"
STATUS_GENERATED = "generated"
STATUS_CURRENT = "current"
STATUS_OUTDATED = "outdated"
STATUS_MISSING = "missing"

APPROVAL_NOT_READY = "not_ready"
APPROVAL_REQUIRED = "approval_required"
APPROVAL_APPROVED = "approved"
APPROVAL_OUTDATED = "outdated"

PROJECT_RUNTIME_CONTEXT_SCOPE = "project_runtime_context"
PROJECT_RUNTIME_CONTEXT_CANON_ID = "project_runtime_context"
PROJECT_RUNTIME_CONTEXT_LABEL = "Project Runtime Context"
PROJECT_RUNTIME_CONTEXT_FILENAME = "project_runtime_context.md"
PROJECT_RUNTIME_CONTEXT_APPROVAL_FILENAME = "project_runtime_context.approval.json"


class CanonPacketGenerationNotReadyError(RuntimeError):
    """Raised when project canon is not ready for packet generation."""


class CanonPacketSourceMissingError(FileNotFoundError):
    """Raised when a validated rendered canon source cannot be loaded."""


def get_project_runtime_context_status(project_id: str) -> dict[str, Any]:
    """Return project-runtime-context readiness without creating files."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_project_runtime_context_status_for_context(
        context,
        manifest.to_dict(),
    )


def get_project_runtime_context_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return readiness, artifact freshness, and approval provenance."""

    validation = canon_validation_service.get_canon_validation_status_for_context(
        context,
        manifest,
    )
    validation_ready = bool(validation.get("ready_for_packet_generation"))
    source_files = _validated_source_files(context, validation) if validation_ready else []
    source_documents = [
        {
            "path": path,
            "relative_path": _relative(path, context.project_dir),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in source_files
    ]
    source_set_sha256 = _source_set_sha256(source_documents) if source_documents else ""

    targets = _project_runtime_context_targets(context, manifest)
    enriched_targets = [
        _project_target_status(
            context=context,
            target=target,
            source_set_sha256=source_set_sha256,
            validation_ready=validation_ready,
        )
        for target in targets
    ]
    generated_count = sum(1 for target in enriched_targets if target["exists"])
    current_count = sum(1 for target in enriched_targets if target["status"] == STATUS_CURRENT)
    outdated_count = sum(1 for target in enriched_targets if target["status"] == STATUS_OUTDATED)
    artifact_current = bool(enriched_targets and current_count == len(enriched_targets))

    approval = _read_project_runtime_context_approval(context)
    artifact_sha256 = str(enriched_targets[0].get("sha256") or "") if enriched_targets else ""
    approved_artifact_sha256 = str(approval.get("approved_artifact_sha256") or "")
    approved_source_set_sha256 = str(approval.get("approved_source_set_sha256") or "")

    if approved_artifact_sha256:
        approval_status = (
            APPROVAL_APPROVED
            if artifact_current
            and approved_artifact_sha256 == artifact_sha256
            and approved_source_set_sha256 == source_set_sha256
            else APPROVAL_OUTDATED
        )
    elif artifact_current:
        approval_status = APPROVAL_REQUIRED
    else:
        approval_status = APPROVAL_NOT_READY

    approval_fresh = approval_status == APPROVAL_APPROVED
    status = (
        STATUS_BLOCKED if not validation_ready
        else STATUS_MISSING if generated_count == 0
        else STATUS_OUTDATED if not artifact_current
        else STATUS_CURRENT
    )

    return {
        "status": status,
        "scope": PROJECT_RUNTIME_CONTEXT_SCOPE,
        "service": CANON_PACKET_GENERATION_SERVICE_MARKER,
        "schema_version": CANON_PACKET_GENERATION_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "genre": context.genre,
        "validation_ready": validation_ready,
        "project_runtime_context_generation_enabled": validation_ready,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "runtime_write_enabled": False,
        "target_count": len(enriched_targets),
        "generated_count": generated_count,
        "current_count": current_count,
        "outdated_count": outdated_count,
        "missing_count": len(enriched_targets) - generated_count,
        "artifact_current": artifact_current,
        "source_set_sha256": source_set_sha256,
        "approval_status": approval_status,
        "approval_fresh": approval_fresh,
        "approval_enabled": artifact_current,
        "approved_artifact_sha256": approved_artifact_sha256,
        "approved_source_set_sha256": approved_source_set_sha256,
        "approved_at": str(approval.get("approved_at") or ""),
        "approval_project_relative_path": _relative(
            _project_runtime_context_approval_path(context),
            context.project_dir,
        ),
        "targets": enriched_targets,
        "validation": {
            "status": validation.get("status"),
            "required_sections_complete": validation.get("required_sections_complete"),
            "required_sections_total": validation.get("required_sections_total"),
            "rendered_sources_total": validation.get("rendered_sources_total"),
            "issues": list(validation.get("issues") or []),
            "warnings": list(validation.get("warnings") or []),
        },
        "execution_locks": _execution_locks(),
        "message": (
            "Project Runtime Context is current and approved."
            if approval_fresh
            else "Project Runtime Context is current and requires approval."
            if artifact_current
            else "Project Runtime Context is ready to generate."
            if validation_ready
            else "Project Runtime Context is blocked until required canon and Markdown are current."
        ),
    }


def generate_project_runtime_context(project_id: str) -> dict[str, Any]:
    """Generate only the project-level reviewable runtime-context packet."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return generate_project_runtime_context_for_context(
        context,
        manifest.to_dict(),
    )


def generate_project_runtime_context_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Generate project context only; book packet generation is excluded."""

    validation = canon_validation_service.get_canon_validation_status_for_context(
        context,
        manifest,
    )
    if not validation.get("ready_for_packet_generation"):
        raise CanonPacketGenerationNotReadyError(
            "Project Runtime Context is not ready. Complete required canon "
            "sections and verify current rendered Markdown before generation."
        )

    source_files = _validated_source_files(context, validation)
    source_documents = [
        {
            "path": path,
            "relative_path": _relative(path, context.project_dir),
            "content": _read_source(path),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in source_files
    ]
    targets = _project_runtime_context_targets(context, manifest)
    if not targets:
        raise CanonPacketSourceMissingError(
            "No project-level runtime-context target is configured."
        )

    source_set_sha256 = _source_set_sha256(source_documents)
    generated_at = utc_now_iso()
    generated: list[dict[str, Any]] = []

    for target in targets:
        if target.get("book_number") is not None:
            raise RuntimeError(
                "Book packet target reached the project runtime-context boundary."
            )

        path = context.project_dir / target["project_relative_path"]
        packet = _render_packet(
            context=context,
            manifest=manifest,
            target=target,
            source_documents=source_documents,
            generated_at=generated_at,
            source_set_sha256=source_set_sha256,
        )
        _write_text_atomic(path, packet)
        generated.append(
            {
                **target,
                "exists": True,
                "status": STATUS_GENERATED,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )

    return {
        "status": STATUS_GENERATED,
        "scope": PROJECT_RUNTIME_CONTEXT_SCOPE,
        "service": CANON_PACKET_GENERATION_SERVICE_MARKER,
        "schema_version": CANON_PACKET_GENERATION_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "genre": context.genre,
        "generated_at": generated_at,
        "source_count": len(source_documents),
        "source_set_sha256": source_set_sha256,
        "approval_status": APPROVAL_REQUIRED,
        "approval_fresh": False,
        "sources": [
            {
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            }
            for item in source_documents
        ],
        "generated_count": len(generated),
        "generated_packets": generated,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "runtime_write_enabled": False,
        "message": (
            "Project Runtime Context generated for author review. "
            "Book packs and generation remain locked."
        ),
        "execution_locks": _execution_locks(),
    }


def _project_runtime_context_targets(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return project-only packet targets and synthesize one for legacy templates."""

    targets = [
        target
        for target in _generation_targets(context, manifest)
        if target.get("source_strategy") == SOURCE_GENERATED_FROM_AUTHOR_CANON
        and target.get("book_number") is None
    ]
    if targets:
        return targets

    path = context.project_canon_packs_dir / PROJECT_RUNTIME_CONTEXT_FILENAME
    return [
        {
            "canon_id": PROJECT_RUNTIME_CONTEXT_CANON_ID,
            "label": PROJECT_RUNTIME_CONTEXT_LABEL,
            "source_strategy": SOURCE_GENERATED_FROM_AUTHOR_CANON,
            "relative_path": _relative(path, context.project_root),
            "project_relative_path": _relative(path, context.project_dir),
            "book_number": None,
            "exists": path.exists(),
            "status": STATUS_READY if path.exists() else "missing",
        }
    ]


def get_canon_packet_generation_status(project_id: str) -> dict[str, Any]:
    """Return read-only packet-generation readiness and target status."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_canon_packet_generation_status_for_context(
        context,
        manifest.to_dict(),
    )


def get_canon_packet_generation_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return packet-generation status without creating or modifying files."""

    validation = canon_validation_service.get_canon_validation_status_for_context(
        context,
        manifest,
    )
    targets = _generation_targets(context, manifest)
    generated_count = sum(1 for target in targets if target["exists"])
    validation_ready = bool(validation.get("ready_for_packet_generation"))

    return {
        "status": STATUS_READY if validation_ready else STATUS_BLOCKED,
        "service": CANON_PACKET_GENERATION_SERVICE_MARKER,
        "schema_version": CANON_PACKET_GENERATION_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "genre": context.genre,
        "validation_ready": validation_ready,
        "packet_generation_enabled": validation_ready,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "runtime_write_enabled": False,
        "target_count": len(targets),
        "generated_count": generated_count,
        "missing_count": len(targets) - generated_count,
        "targets": targets,
        "validation": {
            "status": validation.get("status"),
            "required_sections_complete": validation.get("required_sections_complete"),
            "required_sections_total": validation.get("required_sections_total"),
            "rendered_sources_total": validation.get("rendered_sources_total"),
            "issues": list(validation.get("issues") or []),
            "warnings": list(validation.get("warnings") or []),
        },
        "execution_locks": _execution_locks(),
    }


def generate_canon_packets(project_id: str) -> dict[str, Any]:
    """Generate reviewable project-local canon packets from validated sources."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return generate_canon_packets_for_context(context, manifest.to_dict())


def generate_canon_packets_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Generate project and book knowledge packets for an existing context."""

    validation = canon_validation_service.get_canon_validation_status_for_context(
        context,
        manifest,
    )
    if not validation.get("ready_for_packet_generation"):
        raise CanonPacketGenerationNotReadyError(
            "Project canon is not ready for packet generation. "
            "Complete required canon sections, render their Markdown sources, "
            "and run validation before generating packets."
        )

    source_files = _validated_source_files(context, validation)
    source_documents = [
        {
            "path": path,
            "relative_path": _relative(path, context.project_dir),
            "content": _read_source(path),
        }
        for path in source_files
    ]
    targets = _generation_targets(context, manifest)

    generated: list[dict[str, Any]] = []
    generated_at = utc_now_iso()
    for target in targets:
        path = context.project_dir / target["project_relative_path"]
        packet = _render_packet(
            context=context,
            manifest=manifest,
            target=target,
            source_documents=source_documents,
            generated_at=generated_at,
        )
        _write_text_atomic(path, packet)
        generated.append(
            {
                **target,
                "exists": True,
                "status": STATUS_GENERATED,
                "size_bytes": path.stat().st_size,
            }
        )

    return {
        "status": STATUS_GENERATED,
        "service": CANON_PACKET_GENERATION_SERVICE_MARKER,
        "schema_version": CANON_PACKET_GENERATION_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "genre": context.genre,
        "generated_at": generated_at,
        "source_count": len(source_documents),
        "generated_count": len(generated),
        "generated_packets": generated,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "runtime_write_enabled": False,
        "message": "Reviewable project-local canon packets generated. Generation remains locked.",
        "execution_locks": _execution_locks(),
    }


def _generation_targets(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    template = get_template(context.template_id, context.genre)
    statuses = canon_packet_service.iter_canon_packet_statuses(
        context,
        template,
        manifest,
    )
    allowed_strategies = {
        SOURCE_GENERATED_FROM_AUTHOR_CANON,
        SOURCE_DERIVE_FROM_PROJECT_BOOKS,
    }

    targets: list[dict[str, Any]] = []
    for status in statuses:
        if status.source_strategy not in allowed_strategies:
            continue

        path = context.project_root / status.relative_path
        project_relative = _relative(path, context.project_dir)
        if project_relative.startswith("../"):
            continue

        book_number = _book_number_from_canon_id(status.canon_id)
        targets.append(
            {
                "canon_id": status.canon_id,
                "label": status.label,
                "source_strategy": status.source_strategy,
                "relative_path": status.relative_path,
                "project_relative_path": project_relative,
                "book_number": book_number,
                "exists": path.exists(),
                "status": STATUS_READY if path.exists() else "missing",
            }
        )

    return targets


def _validated_source_files(
    context: ProjectContext,
    validation: dict[str, Any],
) -> list[Path]:
    sources_dir = canon_markdown_renderer_service.canon_sources_dir_for_context(
        context,
        create=False,
    )
    section_results = list(validation.get("sections") or [])
    paths: list[Path] = []

    for item in section_results:
        markdown_file = item.get("markdown_file") if isinstance(item, dict) else {}
        if not isinstance(markdown_file, dict) or not markdown_file.get("exists"):
            continue
        relative = str(markdown_file.get("relative_path") or "").strip()
        if not relative:
            continue
        path = context.project_dir / relative
        if not path.exists() or not path.is_file():
            raise CanonPacketSourceMissingError(
                f"Validated canon source is missing: {_relative(path, context.project_dir)}"
            )
        paths.append(path)

    if not paths:
        paths = sorted(sources_dir.glob("*.md"))

    if not paths:
        raise CanonPacketSourceMissingError(
            "No rendered project-local canon Markdown sources are available."
        )

    return sorted(set(paths), key=lambda item: item.name.lower())


def _read_source(path: Path) -> str:
    content = path.read_text(encoding="utf-8-sig").strip()
    if not content:
        raise CanonPacketSourceMissingError(f"Rendered canon source is empty: {path.name}")
    return content


def _render_packet(
    *,
    context: ProjectContext,
    manifest: dict[str, Any],
    target: dict[str, Any],
    source_documents: list[dict[str, Any]],
    generated_at: str,
    source_set_sha256: str,
) -> str:
    title = target["label"]
    book_number = target.get("book_number")
    scope = f"Book {book_number:02d}" if isinstance(book_number, int) else "Project"

    lines = [
        f"# {title}",
        "",
        "> Derived review artifact. Source canon remains authoritative.",
        "",
        "## Packet Metadata",
        "",
        f"- Project ID: `{context.project_id}`",
        f"- Project: {manifest.get('project_name') or context.project_id}",
        f"- Template: `{context.template_id}`",
        f"- Genre: {context.genre}",
        f"- Scope: {scope}",
        f"- Generated At: {generated_at}",
        f"- Source Documents: {len(source_documents)}",
        f"- Source Set SHA-256: `{source_set_sha256}`",
        "- Provider Execution: disabled",
        "- Runtime Writes: disabled",
        "- Generation Unlock: disabled",
        "",
        "## Source Index",
        "",
    ]

    for index, document in enumerate(source_documents, start=1):
        lines.append(f"{index}. `{document['relative_path']}`")

    for document in source_documents:
        lines.extend(
            [
                "",
                "---",
                "",
                f"## Source: {document['relative_path']}",
                "",
                document["content"],
            ]
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "End of derived canon packet.",
            "",
        ]
    )
    return "\n".join(lines)



def approve_project_runtime_context(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return approve_project_runtime_context_for_context(context, manifest.to_dict())


def approve_project_runtime_context_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    status = get_project_runtime_context_status_for_context(context, manifest)
    if not status.get("artifact_current"):
        raise CanonPacketGenerationNotReadyError(
            "Project Runtime Context must be current before approval."
        )
    target = status["targets"][0]
    approval = {
        "schema_version": "project_runtime_context_approval_v1",
        "project_id": context.project_id,
        "approved_at": utc_now_iso(),
        "approved_artifact_sha256": target["sha256"],
        "approved_source_set_sha256": status["source_set_sha256"],
    }
    _write_json_atomic(_project_runtime_context_approval_path(context), approval)
    return get_project_runtime_context_status_for_context(context, manifest)


def revoke_project_runtime_context_approval(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    path = _project_runtime_context_approval_path(context)
    if path.exists():
        path.unlink()
    return get_project_runtime_context_status_for_context(context, manifest.to_dict())


def _project_target_status(
    *,
    context: ProjectContext,
    target: dict[str, Any],
    source_set_sha256: str,
    validation_ready: bool,
) -> dict[str, Any]:
    path = context.project_dir / target["project_relative_path"]
    exists = path.exists()
    artifact_sha256 = _sha256_file(path) if exists else ""
    embedded_source_sha256 = _read_source_set_sha256(path) if exists else ""
    current = bool(
        exists and validation_ready and source_set_sha256
        and embedded_source_sha256 == source_set_sha256
    )
    return {
        **target,
        "exists": exists,
        "status": STATUS_CURRENT if current else STATUS_OUTDATED if exists else STATUS_MISSING,
        "sha256": artifact_sha256,
        "size_bytes": path.stat().st_size if exists else 0,
        "source_set_sha256": embedded_source_sha256,
    }


def _source_set_sha256(source_documents: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "relative_path": str(item["relative_path"]),
            "sha256": str(item["sha256"]),
        }
        for item in sorted(source_documents, key=lambda item: str(item["relative_path"]))
    ]
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_source_set_sha256(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    match = re.search(r"^- Source Set SHA-256: `([^`]+)`$", text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def _project_runtime_context_approval_path(context: ProjectContext) -> Path:
    return context.project_canon_packs_dir / PROJECT_RUNTIME_CONTEXT_APPROVAL_FILENAME


def _read_project_runtime_context_approval(context: ProjectContext) -> dict[str, Any]:
    path = _project_runtime_context_approval_path(context)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temporary.exists():
            temporary.unlink()

def _book_number_from_canon_id(canon_id: str) -> int | None:
    suffix = str(canon_id or "").rsplit("_", 1)[-1]
    if len(suffix) == 2 and suffix.isdigit():
        value = int(suffix)
        return value if value > 0 else None
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if temporary.exists():
            temporary.unlink()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _execution_locks() -> dict[str, bool]:
    return {
        "prompt_builder_called": False,
        "provider_called": False,
        "registry_written": False,
        "runtime_written": False,
        "draft_persisted": False,
        "generation_unlocked": False,
    }
