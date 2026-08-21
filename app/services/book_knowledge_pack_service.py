"""
Book Runtime Context v2 compiler.

Patch 21 compiles one bounded runtime-context artifact per book from:
- approved/current Book Scope ("Canon for This Book");
- approved/current stable-reference Book Plan;
- project-wide global rules from Author Canon; and
- current Canon Index identity/freshness metadata.

It deliberately does not append the entire Project Runtime Context. It does not
construct prompts, call providers, write Approved Continuity, persist generated
prose, export drafts, or unlock generation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import (
    book_plan_service,
    book_scope_service,
    canon_index_service,
)


BOOK_KNOWLEDGE_PACK_SERVICE_MARKER = "project-book-runtime-context-v2-20260816"
BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION = "book_runtime_context_v2"
BOOK_RUNTIME_CONTEXT_SCOPE = "book_runtime_context"
BOOK_RUNTIME_CONTEXT_DIRECTORY = "book_runtime_context"
AUTHOR_CANON_RELATIVE_PATH = Path("canon") / "author_canon.json"

STATUS_BLOCKED = "blocked"
STATUS_READY = "ready"
STATUS_CURRENT = "current"
STATUS_OUTDATED = "outdated"
STATUS_MISSING = "missing"

GLOBAL_REQUIRED_SECTION_IDS = (
    "project_bible",
    "world_bible",
)


class BookKnowledgePackNotReadyError(RuntimeError):
    """Raised when Book Runtime Context v2 cannot be compiled safely."""


class BookKnowledgePackSourceMissingError(RuntimeError):
    """Raised when a required project-local source artifact is unavailable."""


def get_book_runtime_context_status(project_id: str, *, book_number: int | None = None) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_book_runtime_context_status_for_context(
        context,
        manifest.to_dict(),
        book_number=book_number,
    )


def get_book_runtime_context_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int | None = None,
) -> dict[str, Any]:
    """Return per-book Book Knowledge Pack readiness/currentness.

    Patch 31 aligns Book Runtime Context compilation with the per-book approval
    contract introduced by Patch 30F. A completed/approved Book N may compile
    independently; incomplete later books do not block it.
    """
    plan_result = book_plan_service.get_book_plan_for_context(context, manifest)
    plan = plan_result["plan"]
    validation = plan.get("validation") or {}
    validation_by_book = {
        int(item.get("book_number") or 0): item
        for item in validation.get("books") or []
    }
    workflow_by_book = {
        int(item.get("book_number") or 0): item
        for item in plan.get("book_workflow") or []
    }

    scope_result = book_scope_service.get_book_scope_for_context(context, manifest)
    scope_books = {
        int(book.get("book_number") or 0): book
        for book in scope_result["document"]["books"]
    }

    index_status = canon_index_service.ensure_current_index(context.project_id)
    index_current = index_status.get("index_state") == "current"
    index_revision = str(index_status.get("index_content_hash") or "")

    author_path = _author_canon_path(context)
    author_exists = author_path.exists()
    author_hash = _sha256_file(author_path) if author_exists else ""

    global_blockers: list[dict[str, Any]] = []
    if plan_result.get("migration_required"):
        global_blockers.append({
            "code": "book_plan_reference_migration_required",
            "message": "Book Plan stable-reference migration must be completed.",
        })
    if not author_exists:
        global_blockers.append({
            "code": "author_canon_missing",
            "message": "Project-local Author Canon is required for Book Knowledge Pack compilation.",
        })
    if not index_current:
        global_blockers.append({
            "code": "canon_index_not_current",
            "message": "Canon Index must be current before Book Knowledge Pack compilation.",
        })

    requested = int(book_number or 0)
    if requested < 0:
        requested = 0
    targets: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = list(global_blockers)

    for book in plan.get("books") or []:
        number = int(book.get("book_number") or 0)
        if requested and number != requested:
            continue
        scope_book = scope_books.get(number) or {}
        workflow = workflow_by_book.get(number) or {}
        book_validation = validation_by_book.get(number) or {}

        target_blockers: list[dict[str, Any]] = []
        if book_validation.get("complete") is not True:
            target_blockers.append({
                "code": "book_plan_not_complete",
                "book_number": number,
                "message": f"Book {number} Plan must be complete before its Book Knowledge Pack can compile.",
            })
        plan_approved = bool(
            workflow.get("approval_status") == book_plan_service.APPROVAL_APPROVED
            and workflow.get("approval_fresh") is True
            and workflow.get("approved_content_hash")
            and workflow.get("approved_content_hash") == workflow.get("content_hash")
        )
        if not plan_approved:
            target_blockers.append({
                "code": "book_plan_not_approved",
                "book_number": number,
                "message": f"Book {number} Plan approval must be current before its Book Knowledge Pack can compile.",
            })
        scope_current = bool(
            scope_book
            and scope_book.get("approval_status") == book_scope_service.APPROVAL_APPROVED
            and scope_book.get("approval_fresh") is True
            and (scope_book.get("freshness") or {}).get("fresh") is True
            and (scope_book.get("validation") or {}).get("valid") is True
        )
        if not scope_current:
            target_blockers.append({
                "code": "book_scope_not_approved",
                "book_number": number,
                "message": f"Book {number} Book Canon must be approved and current before its Book Knowledge Pack can compile.",
            })

        target_ready = bool(
            not global_blockers
            and book_validation.get("complete") is True
            and plan_approved
            and scope_current
        )
        target = _target_status(
            context=context,
            book=book,
            workflow=workflow,
            scope_book=scope_book,
            author_hash=author_hash,
            index_revision=index_revision,
            compiler_ready=target_ready,
            blockers=target_blockers,
        )
        targets.append(target)
        blockers.extend(target_blockers)

    expected_count = int(manifest.get("book_count") or 0)
    ready_count = sum(1 for target in targets if target.get("compiler_ready") is True)
    current_count = sum(1 for target in targets if target["status"] == STATUS_CURRENT)
    missing_count = sum(1 for target in targets if target["status"] == STATUS_MISSING)
    outdated_count = sum(1 for target in targets if target["status"] == STATUS_OUTDATED)
    compiler_ready = ready_count > 0

    if targets and ready_count > 0 and current_count == ready_count:
        overall_status = STATUS_CURRENT
    elif compiler_ready:
        overall_status = STATUS_READY
    else:
        overall_status = STATUS_BLOCKED

    return {
        "status": overall_status,
        "scope": BOOK_RUNTIME_CONTEXT_SCOPE,
        "service": BOOK_KNOWLEDGE_PACK_SERVICE_MARKER,
        "schema_version": BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "genre": context.genre,
        "requested_book_number": requested or None,
        "compiler_ready": compiler_ready,
        "ready_count": ready_count,
        "book_runtime_context_generation_enabled": compiler_ready,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "runtime_write_enabled": False,
        "planned_book_count": expected_count,
        "target_count": len(targets),
        "current_count": current_count,
        "missing_count": missing_count,
        "outdated_count": outdated_count,
        "book_plan": {
            "schema_version": plan.get("schema_version"),
            "status": plan.get("status"),
            "approval_status": plan.get("approval_status"),
            "approval_fresh": bool(plan.get("approval_fresh")),
            "revision": int(plan.get("revision") or 0),
            "content_hash": str(plan.get("content_hash") or ""),
            "valid": bool(validation.get("valid")),
            "complete_book_count": int(validation.get("complete_book_count") or 0),
        },
        "book_scope": {
            "schema_version": scope_result.get("schema_version"),
            "exists": bool(scope_result.get("exists")),
            "approved_current_count": sum(
                1 for scope_book in scope_books.values()
                if scope_book.get("approval_status") == book_scope_service.APPROVAL_APPROVED
                and scope_book.get("approval_fresh") is True
                and (scope_book.get("freshness") or {}).get("fresh") is True
            ),
        },
        "author_canon": {
            "exists": author_exists,
            "project_relative_path": _relative(author_path, context.project_dir),
            "sha256": author_hash,
        },
        "canon_index": {
            "state": index_status.get("index_state"),
            "revision": index_revision,
        },
        "targets": targets,
        "blockers": blockers,
        "execution_locks": _execution_locks(),
        "message": (
            f"{ready_count} Book Knowledge Pack target(s) are ready/current for compilation."
            if compiler_ready
            else "No Book Knowledge Pack target is currently ready to compile."
        ),
    }


def compile_book_knowledge_packs(
    project_id: str,
    *,
    book_number: int | None = None,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return compile_book_knowledge_packs_for_context(
        context,
        manifest.to_dict(),
        book_number=book_number,
    )


def compile_book_knowledge_packs_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int | None = None,
) -> dict[str, Any]:
    status = get_book_runtime_context_status_for_context(
        context,
        manifest,
        book_number=book_number,
    )
    ready_targets = [
        item for item in status.get("targets") or []
        if item.get("compiler_ready") is True
        and item.get("status") != STATUS_CURRENT
    ]
    if not ready_targets:
        already_current = [
            item for item in status.get("targets") or []
            if item.get("compiler_ready") is True and item.get("status") == STATUS_CURRENT
        ]
        if already_current:
            return {
                "status": "current",
                "scope": BOOK_RUNTIME_CONTEXT_SCOPE,
                "service": BOOK_KNOWLEDGE_PACK_SERVICE_MARKER,
                "schema_version": BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION,
                "project_id": context.project_id,
                "generated_at": utc_now_iso(),
                "generated_count": 0,
                "targets": already_current,
                "execution_locks": _execution_locks(),
                "message": "Requested Book Knowledge Pack target(s) are already current.",
            }
        messages = [
            str(item.get("message") or "")
            for item in status.get("blockers") or []
            if item.get("message")
        ]
        raise BookKnowledgePackNotReadyError(
            " ".join(messages) or "No Book Knowledge Pack target is ready."
        )

    ready_numbers = {int(item.get("book_number") or 0) for item in ready_targets}
    plan_result = book_plan_service.get_book_plan_for_context(context, manifest)
    plan = plan_result["plan"]
    workflow_by_book = {
        int(item.get("book_number") or 0): item
        for item in plan.get("book_workflow") or []
    }
    scope_result = book_scope_service.get_book_scope_for_context(context, manifest)
    scope_books = {
        int(book.get("book_number") or 0): book
        for book in scope_result["document"]["books"]
    }

    author_path = _author_canon_path(context)
    if not author_path.exists():
        raise BookKnowledgePackSourceMissingError("Project-local Author Canon is missing.")
    author_canon = project_loader.read_json(author_path)
    author_hash = _sha256_file(author_path)

    index_status = canon_index_service.ensure_current_index(context.project_id)
    index_revision = str(index_status.get("index_content_hash") or "")
    if index_status.get("index_state") != "current" or not index_revision:
        raise BookKnowledgePackNotReadyError(
            "Canon Index must be current before Book Knowledge Pack compilation."
        )

    records_by_id = _author_record_map(author_canon)
    all_record_ids = set(records_by_id)
    global_rules = _global_required_rules(author_canon)
    full_context_tokens, full_context_basis = _full_context_token_estimate(context, author_canon)
    generated_at = utc_now_iso()
    generated: list[dict[str, Any]] = []

    for book in plan.get("books") or []:
        book_number_value = int(book.get("book_number") or 0)
        if book_number_value not in ready_numbers:
            continue
        scope_book = scope_books.get(book_number_value) or {}
        workflow = workflow_by_book.get(book_number_value) or {}
        selected_ids = [
            str(item.get("record_id") or "")
            for item in scope_book.get("selections") or []
            if item.get("record_id")
        ]
        selected_set = set(selected_ids)
        missing_source_ids = [record_id for record_id in selected_ids if record_id not in records_by_id]
        if missing_source_ids:
            raise BookKnowledgePackSourceMissingError(
                "Book Scope contains Canon IDs missing from Author Canon: " + ", ".join(missing_source_ids)
            )

        bounded_records = [
            _bounded_record_payload(
                records_by_id[record_id],
                selected_ids=selected_set,
                all_record_ids=all_record_ids,
            )
            for record_id in selected_ids
        ]
        if len(bounded_records) != len(selected_ids):
            raise BookKnowledgePackSourceMissingError(
                f"Book {book_number_value} selected Canon inclusion count does not match Book Scope."
            )

        dependency_set = _dependency_set(
            workflow=workflow,
            scope_book=scope_book,
            author_hash=author_hash,
            index_revision=index_revision,
        )
        body = _render_book_body(
            context=context,
            manifest=manifest,
            book=book,
            scope_book=scope_book,
            global_rules=global_rules,
            bounded_records=bounded_records,
        )
        for selected_id in selected_ids:
            if f"`{selected_id}`" not in body:
                raise BookKnowledgePackSourceMissingError(
                    f"Book {book_number_value} selected Canon record {selected_id} was not rendered into the Book Knowledge Pack."
                )

        book_tokens = _estimate_tokens(body)
        token_reduction = max(0, full_context_tokens - book_tokens)
        reduction_pct = round((token_reduction / full_context_tokens) * 100.0, 2) if full_context_tokens > 0 else 0.0
        content = _render_book_runtime_context(
            context=context,
            book=book,
            workflow=workflow,
            scope_book=scope_book,
            author_hash=author_hash,
            index_revision=index_revision,
            dependency_set=dependency_set,
            generated_at=generated_at,
            body=body,
            book_tokens=book_tokens,
            full_context_tokens=full_context_tokens,
            full_context_basis=full_context_basis,
            token_reduction=token_reduction,
            reduction_pct=reduction_pct,
        )

        target_path = _book_runtime_context_path(context, book_number_value)
        _write_text_atomic(target_path, content)
        generated.append({
            "book_number": book_number_value,
            "label": f"Book {book_number_value:02d} Knowledge Pack",
            "project_relative_path": _relative(target_path, context.project_dir),
            "sha256": _sha256_file(target_path),
            "size_bytes": target_path.stat().st_size,
            "status": STATUS_CURRENT,
            "selected_record_count": len(selected_ids),
            "major_event_count": len(book.get("major_events") or []),
            "required_character_count": len(book.get("required_characters") or []),
            "required_location_count": len(book.get("required_locations") or []),
            "source_book_plan_revision": int(workflow.get("revision") or 0),
            "source_book_plan_sha256": str(workflow.get("content_hash") or ""),
            "source_book_scope_revision": int(scope_book.get("revision") or 0),
            "source_book_scope_sha256": str(scope_book.get("content_hash") or ""),
            "source_author_canon_sha256": author_hash,
            "source_canon_index_revision": index_revision,
            "dependency_set_sha256": dependency_set,
            "estimated_tokens": book_tokens,
            "full_context_estimated_tokens": full_context_tokens,
            "estimated_token_reduction": token_reduction,
            "estimated_token_reduction_percent": reduction_pct,
        })

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
            "Book Knowledge Pack artifact(s) compiled from selected Book Canon and the approved per-book Plan. "
            "Required/Major fields remain separate usage obligations; they do not control Canon inclusion."
        ),
    }


def _target_status(
    *,
    context: ProjectContext,
    book: dict[str, Any],
    workflow: dict[str, Any],
    scope_book: dict[str, Any],
    author_hash: str,
    index_revision: str,
    compiler_ready: bool,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    book_number = int(book.get("book_number") or 0)
    path = _book_runtime_context_path(context, book_number)
    exists = path.exists()
    metadata = _read_compiler_metadata(path) if exists else {}
    dependency_set = _dependency_set(
        workflow=workflow,
        scope_book=scope_book,
        author_hash=author_hash,
        index_revision=index_revision,
    )
    current = bool(
        compiler_ready
        and exists
        and metadata.get("schema_version") == BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION
        and metadata.get("book_number") == str(book_number)
        and metadata.get("book_plan_revision") == str(int(workflow.get("revision") or 0))
        and metadata.get("book_plan_sha256") == str(workflow.get("content_hash") or "")
        and metadata.get("book_scope_revision") == str(int(scope_book.get("revision") or 0))
        and metadata.get("book_scope_sha256") == str(scope_book.get("content_hash") or "")
        and metadata.get("author_canon_sha256") == author_hash
        and metadata.get("canon_index_revision") == index_revision
        and metadata.get("dependency_set_sha256") == dependency_set
        and bool(author_hash)
        and bool(index_revision)
    )
    selected_count = len(scope_book.get("selections") or [])
    return {
        "book_number": book_number,
        "label": f"Book {book_number:02d} Knowledge Pack",
        "project_relative_path": _relative(path, context.project_dir),
        "exists": exists,
        "status": STATUS_CURRENT if current else STATUS_OUTDATED if exists else STATUS_MISSING,
        "compiler_ready": bool(compiler_ready),
        "blockers": blockers,
        "sha256": _sha256_file(path) if exists else "",
        "size_bytes": path.stat().st_size if exists else 0,
        "source_book_plan_revision": metadata.get("book_plan_revision", ""),
        "source_book_plan_sha256": metadata.get("book_plan_sha256", ""),
        "source_book_scope_revision": metadata.get("book_scope_revision", ""),
        "source_book_scope_sha256": metadata.get("book_scope_sha256", ""),
        "source_author_canon_sha256": metadata.get("author_canon_sha256", ""),
        "source_canon_index_revision": metadata.get("canon_index_revision", ""),
        "dependency_set_sha256": metadata.get("dependency_set_sha256", ""),
        "selected_record_count": _safe_int(metadata.get("selected_record_count")) if exists else selected_count,
        "estimated_tokens": _safe_int(metadata.get("estimated_tokens")),
        "full_context_estimated_tokens": _safe_int(metadata.get("full_context_estimated_tokens")),
    }


def _dependency_set(
    *,
    workflow: dict[str, Any],
    scope_book: dict[str, Any],
    author_hash: str,
    index_revision: str,
) -> str:
    payload = {
        "book_plan_revision": int(workflow.get("revision") or 0),
        "book_plan_sha256": str(workflow.get("content_hash") or ""),
        "book_scope_revision": int(scope_book.get("revision") or 0),
        "book_scope_sha256": str(scope_book.get("content_hash") or ""),
        "author_canon_sha256": author_hash,
        "canon_index_revision": index_revision,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _author_record_map(author_canon: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(author_canon, dict):
        raise BookKnowledgePackSourceMissingError(
            "Author Canon must contain a JSON object."
        )
    records: dict[str, dict[str, Any]] = {}
    for section in (author_canon.get("sections") or {}).values():
        if not isinstance(section, dict):
            continue
        for group_records in (section.get("records") or {}).values():
            if not isinstance(group_records, list):
                continue
            for record in group_records:
                if not isinstance(record, dict):
                    continue
                record_id = str(record.get("internal_id") or "").strip()
                if record_id:
                    records[record_id] = record
    return records


def _global_required_rules(author_canon: dict[str, Any]) -> list[dict[str, Any]]:
    sections = author_canon.get("sections") or {}
    result: list[dict[str, Any]] = []
    for section_id in GLOBAL_REQUIRED_SECTION_IDS:
        section = sections.get(section_id) or {}
        answers = section.get("answers") if isinstance(section, dict) else {}
        result.append(
            {
                "section_id": section_id,
                "answers": answers if isinstance(answers, dict) else {},
            }
        )
    return result


_OMIT = object()


def _bounded_record_payload(
    record: dict[str, Any],
    *,
    selected_ids: set[str],
    all_record_ids: set[str],
) -> dict[str, Any]:
    bounded = _bounded_value(
        record,
        selected_ids=selected_ids,
        all_record_ids=all_record_ids,
    )
    return bounded if isinstance(bounded, dict) else {}


def _bounded_value(
    value: Any,
    *,
    selected_ids: set[str],
    all_record_ids: set[str],
) -> Any:
    if isinstance(value, str):
        if value in all_record_ids and value not in selected_ids:
            return _OMIT
        return value
    if isinstance(value, list):
        result = []
        for item in value:
            bounded = _bounded_value(
                item,
                selected_ids=selected_ids,
                all_record_ids=all_record_ids,
            )
            if bounded is not _OMIT:
                result.append(bounded)
        return result
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            bounded = _bounded_value(
                item,
                selected_ids=selected_ids,
                all_record_ids=all_record_ids,
            )
            if bounded is not _OMIT:
                result[str(key)] = bounded
        return result
    return value


def _render_book_body(
    *,
    context: ProjectContext,
    manifest: dict[str, Any],
    book: dict[str, Any],
    scope_book: dict[str, Any],
    global_rules: list[dict[str, Any]],
    bounded_records: list[dict[str, Any]],
) -> str:
    book_number = int(book.get("book_number") or 0)
    title = str(book.get("title") or f"Book {book_number}")
    lines = [
        "## Global Required Rules",
        "",
        "> Project-wide rules are included independently of Book Canon selection.",
        "",
    ]
    for section in global_rules:
        lines.extend(
            [
                f"### {section['section_id'].replace('_', ' ').title()}",
                "",
                "```json",
                json.dumps(
                    section["answers"],
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Book Boundary",
            "",
            f"- Book Number: {book_number}",
            f"- Title: {title}",
            f"- Time Span: {book.get('time_span') or ''}",
            f"- Primary Arc: {book.get('primary_arc') or ''}",
            f"- Ending State: {book.get('ending_state') or ''}",
            f"- Handoff To Next Book: {book.get('handoff_to_next_book') or ''}",
            "",
            "### Major Events",
            *_reference_markdown_list(book.get("major_events")),
            "",
            "### Required Characters",
            *_reference_markdown_list(book.get("required_characters")),
            "",
            "### Required Locations",
            *_reference_markdown_list(book.get("required_locations")),
            "",
            "### Allowed Reveals",
            *_text_markdown_list(book.get("allowed_reveals")),
            "",
            "### Forbidden Future Knowledge",
            *_text_markdown_list(book.get("forbidden_future_knowledge")),
            "",
            "## Book Canon Inclusion Contract",
            "",
            "- Every record selected in Book Canon is included in this Book Knowledge Pack.",
            "- Major Events, Required Characters, and Required Locations are stronger usage obligations only.",
            "- A selected Canon record does not need to be marked Required/Major to be included here.",
            "",
            "## Selected Book Canon",
            "",
            (
                f"Selected records: {len(scope_book.get('selections') or [])}. "
                "All selected addressable records are rendered below."
            ),
            "",
        ]
    )

    for record in bounded_records:
        record_id = str(record.get("internal_id") or "")
        label = _record_label(record)
        lines.extend(
            [
                f"### {label}",
                "",
                f"- Record ID: `{record_id}`",
                "",
                "```json",
                json.dumps(
                    record,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Runtime Boundary",
            "",
            "- Unselected addressable Canon records: omitted",
            "- Future-book unselected records: omitted",
            "- Full Project Runtime Context append: disabled",
            "- Prompt Builder: not called",
            "- Provider Execution: disabled",
            "- Approved Continuity writes: disabled",
            "- Generation Unlock: disabled",
            "",
        ]
    )
    return "\n".join(lines)


def _render_book_runtime_context(
    *,
    context: ProjectContext,
    book: dict[str, Any],
    workflow: dict[str, Any],
    scope_book: dict[str, Any],
    author_hash: str,
    index_revision: str,
    dependency_set: str,
    generated_at: str,
    body: str,
    book_tokens: int,
    full_context_tokens: int,
    full_context_basis: str,
    token_reduction: int,
    reduction_pct: float,
) -> str:
    book_number = int(book.get("book_number") or 0)
    title = str(book.get("title") or f"Book {book_number}")
    selected_count = len(scope_book.get("selections") or [])
    lines = [
        f"# Book {book_number:02d} Runtime Context v2 — {title}",
        "",
        "> Derived bounded runtime artifact. Author Canon, approved Book Scope, "
        "and approved Book Plan remain authoritative.",
        "",
        "## Compiler Metadata",
        "",
        f"- Schema Version: `{BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION}`",
        f"- Compiler: `{BOOK_KNOWLEDGE_PACK_SERVICE_MARKER}`",
        f"- Project ID: `{context.project_id}`",
        f"- Book Number: `{book_number}`",
        f"- Generated At: {generated_at}",
        f"- Book Plan Revision: `{int(workflow.get('revision') or 0)}`",
        f"- Book Plan SHA-256: `{workflow.get('content_hash') or ''}`",
        f"- Book Scope Revision: `{int(scope_book.get('revision') or 0)}`",
        f"- Book Scope SHA-256: `{scope_book.get('content_hash') or ''}`",
        f"- Author Canon SHA-256: `{author_hash}`",
        f"- Canon Index Revision: `{index_revision}`",
        f"- Dependency Set SHA-256: `{dependency_set}`",
        f"- Selected Record Count: `{selected_count}`",
        f"- Estimated Tokens: `{book_tokens}`",
        f"- Full Context Estimated Tokens: `{full_context_tokens}`",
        f"- Full Context Estimate Basis: `{full_context_basis}`",
        f"- Estimated Token Reduction: `{token_reduction}`",
        f"- Estimated Token Reduction Percent: `{reduction_pct}`",
        "",
        body.rstrip(),
        "",
        "---",
        "",
        "End of bounded Book Runtime Context v2.",
        "",
    ]
    return "\n".join(lines)


def _full_context_token_estimate(
    context: ProjectContext,
    author_canon: dict[str, Any],
) -> tuple[int, str]:
    legacy_path = context.project_canon_packs_dir / "project_runtime_context.md"
    if legacy_path.exists():
        try:
            return (
                _estimate_tokens(legacy_path.read_text(encoding="utf-8")),
                "project_runtime_context.md",
            )
        except (OSError, UnicodeError):
            pass
    normalized = json.dumps(
        author_canon,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return _estimate_tokens(normalized), "author_canon_json_proxy"


def _estimate_tokens(text: str) -> int:
    # Local deterministic estimate only. No provider/model calls.
    return int(math.ceil(len(text.encode("utf-8")) / 4.0))


def _record_label(record: dict[str, Any]) -> str:
    for key in (
        "display_label",
        "name",
        "event_name",
        "location_name",
        "signal_name",
        "title",
        "label",
        "story_code",
    ):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return str(record.get("internal_id") or "Canon Record")


def _reference_markdown_list(values: Any) -> list[str]:
    items: list[str] = []
    for value in list(values or []):
        if isinstance(value, dict):
            label = str(
                value.get("label")
                or value.get("legacy_label")
                or value.get("record_id")
                or ""
            ).strip()
            record_id = str(value.get("record_id") or "").strip()
            if label:
                items.append(
                    f"- {label}" + (f" (`{record_id}`)" if record_id else "")
                )
        else:
            text = str(value or "").strip()
            if text:
                items.append(f"- {text}")
    return items or ["- None specified"]


def _text_markdown_list(values: Any) -> list[str]:
    items = [
        str(value).strip()
        for value in list(values or [])
        if str(value).strip()
    ]
    return [f"- {item}" for item in items] or ["- None specified"]


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
        "book_scope_revision": r"^- Book Scope Revision: `([^`]+)`$",
        "book_scope_sha256": r"^- Book Scope SHA-256: `([^`]+)`$",
        "author_canon_sha256": r"^- Author Canon SHA-256: `([^`]+)`$",
        "canon_index_revision": r"^- Canon Index Revision: `([^`]+)`$",
        "dependency_set_sha256": r"^- Dependency Set SHA-256: `([^`]+)`$",
        "selected_record_count": r"^- Selected Record Count: `([^`]+)`$",
        "estimated_tokens": r"^- Estimated Tokens: `([^`]+)`$",
        "full_context_estimated_tokens": (
            r"^- Full Context Estimated Tokens: `([^`]+)`$"
        ),
    }
    metadata: dict[str, str] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            metadata[key] = match.group(1)
    return metadata


def _author_canon_path(context: ProjectContext) -> Path:
    return context.project_dir / AUTHOR_CANON_RELATIVE_PATH


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


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _execution_locks() -> dict[str, bool]:
    return {
        "book_runtime_context_compilation_enabled": True,
        "prompt_builder_called": False,
        "provider_called": False,
        "registry_written": False,
        "runtime_written": False,
        "draft_persisted": False,
        "approved_continuity_written": False,
        "generation_unlocked": False,
    }


# Patch 31B: fast per-book readiness used by Chapter Planner guidance.  Actual
# compilation still executes the full Book Knowledge Pack validator/compiler.
def get_book_runtime_context_readiness_fast(project_id: str, *, book_number: int) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    book_number = int(book_number)
    if book_number < 1 or book_number > max(1, int(manifest_obj.book_count or 1)):
        raise ValueError("book_number is outside the project book range")

    plan_path = context.project_dir / book_plan_service.BOOK_PLAN_FILENAME
    scope_path = book_scope_service.book_scope_path_for_context(context)
    plan_doc = project_loader.read_json(plan_path) if plan_path.exists() else {}
    scope_doc = project_loader.read_json(scope_path) if scope_path.exists() else {}
    book = next((item for item in plan_doc.get("books") or [] if int(item.get("book_number") or 0) == book_number), None) or {"book_number": book_number}
    workflow = next((item for item in plan_doc.get("book_workflow") or [] if int(item.get("book_number") or 0) == book_number), None) or {"book_number": book_number}
    scope_book = next((item for item in scope_doc.get("books") or [] if int(item.get("book_number") or 0) == book_number), None) or {"book_number": book_number}

    blockers: list[dict[str, Any]] = []
    plan_approved = bool(
        workflow.get("approval_status") == book_plan_service.APPROVAL_APPROVED
        and workflow.get("approval_fresh") is True
        and workflow.get("approved_content_hash")
        and workflow.get("approved_content_hash") == workflow.get("content_hash")
    )
    if not plan_approved:
        blockers.append({"code": "book_plan_not_approved", "book_number": book_number,
                         "message": f"Book {book_number} Plan approval must be current before its Book Knowledge Pack can compile."})

    index_status = canon_index_service.ensure_current_index(project_id)
    author_path = _author_canon_path(context)
    author_hash = _sha256_file(author_path) if author_path.exists() else ""
    index_revision = str(index_status.get("index_content_hash") or "")
    scope_approved = bool(
        scope_book.get("approval_status") == book_scope_service.APPROVAL_APPROVED
        and scope_book.get("approved_content_hash")
        and scope_book.get("approved_content_hash") == scope_book.get("content_hash")
        and scope_book.get("approved_source_canon_hash") == str(index_status.get("source_author_canon_hash") or index_status.get("source_canon_hash") or scope_book.get("approved_source_canon_hash") or "")
        and scope_book.get("approved_source_index_revision") == index_revision
    )
    # Older current indexes may not surface source_author_canon_hash.  In that
    # case content/index approval equality remains the fast UI precheck; full
    # compilation performs authoritative reconciliation.
    if not scope_approved:
        scope_approved = bool(
            scope_book.get("approval_status") == book_scope_service.APPROVAL_APPROVED
            and scope_book.get("approved_content_hash") == scope_book.get("content_hash")
            and scope_book.get("approved_source_index_revision") == index_revision
        )
    if not scope_approved:
        blockers.append({"code": "book_scope_not_approved", "book_number": book_number,
                         "message": f"Book {book_number} Book Canon must be approved and current before its Book Knowledge Pack can compile."})
    compiler_ready = not blockers and bool(author_hash) and bool(index_revision)
    target = _target_status(
        context=context, book=book, workflow=workflow, scope_book=scope_book,
        author_hash=author_hash, index_revision=index_revision,
        compiler_ready=compiler_ready, blockers=blockers,
    )
    return {
        "status": target["status"], "scope": BOOK_RUNTIME_CONTEXT_SCOPE, "project_id": project_id,
        "requested_book_number": book_number, "compiler_ready": compiler_ready,
        "ready_count": 1 if compiler_ready else 0, "targets": [target], "blockers": blockers,
        "generation_enabled": False, "provider_execution_enabled": False,
    }
