"""
Project-local canon packet generation service.

This service materializes reviewable Markdown knowledge packets from validated,
project-local rendered canon sources.

It does not build prompts, call providers, write runtime memory, modify source
canon, persist generated drafts, export projects, or unlock generation.
"""

from __future__ import annotations

from pathlib import Path
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


class CanonPacketGenerationNotReadyError(RuntimeError):
    """Raised when project canon is not ready for packet generation."""


class CanonPacketSourceMissingError(FileNotFoundError):
    """Raised when a validated rendered canon source cannot be loaded."""


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


def _book_number_from_canon_id(canon_id: str) -> int | None:
    suffix = str(canon_id or "").rsplit("_", 1)[-1]
    if len(suffix) == 2 and suffix.isdigit():
        value = int(suffix)
        return value if value > 0 else None
    return None


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


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
