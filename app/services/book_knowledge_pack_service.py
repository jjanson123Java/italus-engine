"""
Project-local Book Knowledge Pack compiler.

This service compiles one deterministic Markdown runtime-context artifact per
book from:

1. the current project-level runtime-context artifact; and
2. the current approved, fresh Book Plan entry for that book.

It does not construct prompts, call providers, write runtime memory, persist
generated prose, export drafts, or unlock generation.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import time
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import book_plan_service, canon_packet_generation_service


BOOK_KNOWLEDGE_PACK_SERVICE_MARKER = (
    "project-book-knowledge-pack-compiler-20260726"
)
BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION = "book_runtime_context_v1"
BOOK_RUNTIME_CONTEXT_SCOPE = "book_runtime_context"
BOOK_RUNTIME_CONTEXT_DIRECTORY = "book_runtime_context"
PROJECT_RUNTIME_CONTEXT_FILENAME = "project_runtime_context.md"

STATUS_BLOCKED = "blocked"
STATUS_READY = "ready"
STATUS_CURRENT = "current"
STATUS_OUTDATED = "outdated"
STATUS_MISSING = "missing"


class BookKnowledgePackNotReadyError(RuntimeError):
    """Raised when Book Runtime Context cannot be compiled safely."""


class BookKnowledgePackSourceMissingError(RuntimeError):
    """Raised when an approved source artifact is unavailable."""


def get_book_runtime_context_status(project_id: str) -> dict[str, Any]:
    """Return compiler readiness and target freshness without writing files."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_book_runtime_context_status_for_context(
        context,
        manifest.to_dict(),
    )


def get_book_runtime_context_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return status for all project-local Book Runtime Context targets."""

    plan_result = book_plan_service.get_book_plan_for_context(
        context,
        manifest,
    )
    plan = plan_result["plan"]
    validation = plan["validation"]

    plan_approved = (
        plan.get("approval_status") == book_plan_service.APPROVAL_APPROVED
        and plan.get("approval_fresh") is True
        and bool(plan.get("approved_content_hash"))
        and plan.get("approved_content_hash") == plan.get("content_hash")
    )

    project_context_status = (
        canon_packet_generation_service
        .get_project_runtime_context_status_for_context(context, manifest)
    )
    project_context_path = _project_runtime_context_path(context)
    project_context_exists = project_context_path.exists()
    project_context_hash = (
        _sha256_file(project_context_path)
        if project_context_exists
        else ""
    )
    project_context_approved = (
        project_context_status.get("approval_status")
        == canon_packet_generation_service.APPROVAL_APPROVED
        and project_context_status.get("approval_fresh") is True
    )

    targets = [
        _target_status(
            context=context,
            book=book,
            plan=plan,
            project_context_hash=project_context_hash,
        )
        for book in plan.get("books") or []
    ]

    current_count = sum(
        1 for target in targets if target["status"] == STATUS_CURRENT
    )
    missing_count = sum(
        1 for target in targets if target["status"] == STATUS_MISSING
    )
    outdated_count = sum(
        1 for target in targets if target["status"] == STATUS_OUTDATED
    )

    compiler_ready = bool(
        validation.get("valid")
        and plan_approved
        and project_context_exists
        and project_context_approved
        and len(targets) == int(manifest.get("book_count") or 0)
        and len(targets) > 0
    )

    blockers: list[dict[str, Any]] = []
    if not validation.get("valid"):
        blockers.append(
            {
                "code": "book_plan_incomplete",
                "message": "Book Plan must be complete before compilation.",
            }
        )
    if not plan_approved:
        blockers.append(
            {
                "code": "book_plan_not_approved",
                "message": (
                    "Book Plan approval must be current before compilation."
                ),
            }
        )
    if not project_context_exists:
        blockers.append(
            {
                "code": "project_runtime_context_missing",
                "message": "Project Runtime Context must exist before book compilation.",
            }
        )
    elif not project_context_approved:
        blockers.append(
            {
                "code": "project_runtime_context_not_approved",
                "message": "Project Runtime Context approval must be current before book compilation.",
            }
        )

    status = STATUS_READY if compiler_ready else STATUS_BLOCKED
    if compiler_ready and current_count == len(targets):
        status = STATUS_CURRENT

    return {
        "status": status,
        "scope": BOOK_RUNTIME_CONTEXT_SCOPE,
        "service": BOOK_KNOWLEDGE_PACK_SERVICE_MARKER,
        "schema_version": BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "genre": context.genre,
        "compiler_ready": compiler_ready,
        "book_runtime_context_generation_enabled": compiler_ready,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "runtime_write_enabled": False,
        "planned_book_count": int(manifest.get("book_count") or 0),
        "target_count": len(targets),
        "current_count": current_count,
        "missing_count": missing_count,
        "outdated_count": outdated_count,
        "book_plan": {
            "status": plan.get("status"),
            "approval_status": plan.get("approval_status"),
            "approval_fresh": bool(plan.get("approval_fresh")),
            "revision": int(plan.get("revision") or 0),
            "content_hash": str(plan.get("content_hash") or ""),
            "approved_content_hash": str(
                plan.get("approved_content_hash") or ""
            ),
            "valid": bool(validation.get("valid")),
        },
        "project_runtime_context": {
            "exists": project_context_exists,
            "project_relative_path": _relative(
                project_context_path,
                context.project_dir,
            ),
            "sha256": project_context_hash,
            "approval_status": project_context_status.get("approval_status"),
            "approval_fresh": bool(project_context_status.get("approval_fresh")),
        },
        "targets": targets,
        "blockers": blockers,
        "execution_locks": _execution_locks(),
        "message": (
            "Book Runtime Context is ready to compile."
            if compiler_ready
            else "Book Runtime Context compilation is blocked."
        ),
    }


def compile_book_knowledge_packs(project_id: str) -> dict[str, Any]:
    """Compile one deterministic project-local artifact per approved book."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return compile_book_knowledge_packs_for_context(
        context,
        manifest.to_dict(),
    )


def compile_book_knowledge_packs_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compile all approved Book Plan entries without runtime execution."""

    status = get_book_runtime_context_status_for_context(
        context,
        manifest,
    )
    if not status["compiler_ready"]:
        blocker_messages = [
            str(item.get("message") or "")
            for item in status.get("blockers") or []
        ]
        raise BookKnowledgePackNotReadyError(
            " ".join(blocker_messages)
            or "Book Runtime Context is not ready to compile."
        )

    plan_result = book_plan_service.get_book_plan_for_context(
        context,
        manifest,
    )
    plan = plan_result["plan"]

    project_context_path = _project_runtime_context_path(context)
    if not project_context_path.exists():
        raise BookKnowledgePackSourceMissingError(
            "Project Runtime Context artifact is missing."
        )

    project_context_content = project_context_path.read_text(
        encoding="utf-8"
    )
    project_context_hash = _sha256_file(project_context_path)
    generated_at = utc_now_iso()
    generated: list[dict[str, Any]] = []

    for book in plan.get("books") or []:
        book_number = int(book.get("book_number") or 0)
        if book_number < 1:
            raise BookKnowledgePackNotReadyError(
                "Book Plan contains an invalid book_number."
            )

        target_path = _book_runtime_context_path(
            context,
            book_number,
        )
        content = _render_book_runtime_context(
            context=context,
            manifest=manifest,
            plan=plan,
            book=book,
            project_context_content=project_context_content,
            project_context_hash=project_context_hash,
            generated_at=generated_at,
        )
        _write_text_atomic(target_path, content)

        generated.append(
            {
                "book_number": book_number,
                "label": f"Book {book_number:02d} Runtime Context",
                "project_relative_path": _relative(
                    target_path,
                    context.project_dir,
                ),
                "sha256": _sha256_file(target_path),
                "size_bytes": target_path.stat().st_size,
                "status": STATUS_CURRENT,
                "source_book_plan_revision": int(
                    plan.get("revision") or 0
                ),
                "source_book_plan_sha256": str(
                    plan.get("content_hash") or ""
                ),
                "source_project_runtime_context_sha256": (
                    project_context_hash
                ),
            }
        )

    return {
        "status": "compiled",
        "scope": BOOK_RUNTIME_CONTEXT_SCOPE,
        "service": BOOK_KNOWLEDGE_PACK_SERVICE_MARKER,
        "schema_version": BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION,
        "project_id": context.project_id,
        "generated_at": generated_at,
        "generated_count": len(generated),
        "targets": generated,
        "execution_locks": _execution_locks(),
        "message": (
            "Book Runtime Context artifacts compiled. "
            "Prompt, provider, runtime, and generation boundaries remain locked."
        ),
    }


def _target_status(
    *,
    context: ProjectContext,
    book: dict[str, Any],
    plan: dict[str, Any],
    project_context_hash: str,
) -> dict[str, Any]:
    book_number = int(book.get("book_number") or 0)
    path = _book_runtime_context_path(context, book_number)
    exists = path.exists()

    metadata = _read_compiler_metadata(path) if exists else {}
    expected_plan_hash = str(plan.get("content_hash") or "")
    expected_revision = int(plan.get("revision") or 0)

    current = bool(
        exists
        and metadata.get("schema_version")
        == BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION
        and metadata.get("book_number") == str(book_number)
        and metadata.get("book_plan_revision")
        == str(expected_revision)
        and metadata.get("book_plan_sha256") == expected_plan_hash
        and metadata.get("project_runtime_context_sha256")
        == project_context_hash
        and bool(project_context_hash)
    )

    status = (
        STATUS_CURRENT
        if current
        else STATUS_OUTDATED
        if exists
        else STATUS_MISSING
    )

    return {
        "book_number": book_number,
        "label": f"Book {book_number:02d} Runtime Context",
        "project_relative_path": _relative(path, context.project_dir),
        "exists": exists,
        "status": status,
        "sha256": _sha256_file(path) if exists else "",
        "size_bytes": path.stat().st_size if exists else 0,
        "source_book_plan_revision": metadata.get(
            "book_plan_revision",
            "",
        ),
        "source_book_plan_sha256": metadata.get(
            "book_plan_sha256",
            "",
        ),
        "source_project_runtime_context_sha256": metadata.get(
            "project_runtime_context_sha256",
            "",
        ),
    }


def _render_book_runtime_context(
    *,
    context: ProjectContext,
    manifest: dict[str, Any],
    plan: dict[str, Any],
    book: dict[str, Any],
    project_context_content: str,
    project_context_hash: str,
    generated_at: str,
) -> str:
    book_number = int(book["book_number"])
    title = str(book.get("title") or f"Book {book_number}")

    lines = [
        f"# Book {book_number:02d} Runtime Context — {title}",
        "",
        "> Derived review artifact. Author Canon, Project Runtime Context, "
        "and the approved Book Plan remain authoritative.",
        "",
        "## Compiler Metadata",
        "",
        f"- Schema Version: `{BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION}`",
        f"- Compiler: `{BOOK_KNOWLEDGE_PACK_SERVICE_MARKER}`",
        f"- Project ID: `{context.project_id}`",
        f"- Book Number: `{book_number}`",
        f"- Generated At: {generated_at}",
        f"- Book Plan Revision: `{int(plan.get('revision') or 0)}`",
        f"- Book Plan SHA-256: `{plan.get('content_hash') or ''}`",
        (
            "- Project Runtime Context SHA-256: "
            f"`{project_context_hash}`"
        ),
        "- Prompt Builder: not called",
        "- Provider Execution: disabled",
        "- Runtime Writes: disabled",
        "- Generation Unlock: disabled",
        "",
        "## Book Boundary",
        "",
        f"- Title: {title}",
        f"- Time Span: {book.get('time_span') or ''}",
        f"- Primary Arc: {book.get('primary_arc') or ''}",
        f"- Ending State: {book.get('ending_state') or ''}",
        (
            "- Handoff To Next Book: "
            f"{book.get('handoff_to_next_book') or ''}"
        ),
        "",
        "## Major Events",
        "",
        *_markdown_list(book.get("major_events")),
        "",
        "## Required Characters",
        "",
        *_markdown_list(book.get("required_characters")),
        "",
        "## Required Locations",
        "",
        *_markdown_list(book.get("required_locations")),
        "",
        "## Allowed Reveals",
        "",
        *_markdown_list(book.get("allowed_reveals")),
        "",
        "## Forbidden Future Knowledge",
        "",
        *_markdown_list(book.get("forbidden_future_knowledge")),
        "",
        "## Author Notes",
        "",
        str(book.get("notes") or ""),
        "",
        "---",
        "",
        "## Project Runtime Context",
        "",
        project_context_content.rstrip(),
        "",
        "---",
        "",
        "End of derived Book Runtime Context.",
        "",
    ]
    return "\n".join(lines)


def _read_compiler_metadata(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}

    patterns = {
        "schema_version": r"^- Schema Version: `([^`]+)`$",
        "book_number": r"^- Book Number: `([^`]+)`$",
        "book_plan_revision": r"^- Book Plan Revision: `([^`]+)`$",
        "book_plan_sha256": r"^- Book Plan SHA-256: `([^`]+)`$",
        "project_runtime_context_sha256": (
            r"^- Project Runtime Context SHA-256: `([^`]+)`$"
        ),
    }
    metadata: dict[str, str] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            metadata[key] = match.group(1)
    return metadata


def _markdown_list(values: Any) -> list[str]:
    items = [
        str(value).strip()
        for value in list(values or [])
        if str(value).strip()
    ]
    return [f"- {item}" for item in items] or ["- None specified"]


def _project_runtime_context_path(context: ProjectContext) -> Path:
    return context.project_canon_packs_dir / PROJECT_RUNTIME_CONTEXT_FILENAME


def _book_runtime_context_path(
    context: ProjectContext,
    book_number: int,
) -> Path:
    return (
        context.project_canon_packs_dir
        / BOOK_RUNTIME_CONTEXT_DIRECTORY
        / f"book_{book_number:02d}.md"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    """Write text atomically with bounded retry for transient Windows locks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")

    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        last_error: PermissionError | None = None
        for attempt in range(6):
            try:
                temporary.replace(path)
                return
            except PermissionError as exc:
                last_error = exc
                if attempt == 5:
                    break
                time.sleep(0.05 * (attempt + 1))

        assert last_error is not None
        raise last_error
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
        "book_runtime_context_compilation_enabled": True,
        "prompt_builder_called": False,
        "provider_called": False,
        "registry_written": False,
        "runtime_written": False,
        "draft_persisted": False,
        "generation_unlocked": False,
    }
