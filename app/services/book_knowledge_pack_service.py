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


def get_book_runtime_context_status(project_id: str) -> dict[str, Any]:
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
    plan_result = book_plan_service.get_book_plan_for_context(
        context,
        manifest,
    )
    plan = plan_result["plan"]
    validation = plan["validation"]
    plan_current = bool(
        not plan_result.get("migration_required")
        and plan.get("schema_version")
        == book_plan_service.BOOK_PLAN_SCHEMA_VERSION
        and validation.get("valid")
        and plan.get("approval_status") == book_plan_service.APPROVAL_APPROVED
        and plan.get("approval_fresh") is True
        and bool(plan.get("approved_content_hash"))
        and plan.get("approved_content_hash") == plan.get("content_hash")
    )

    scope_result = book_scope_service.get_book_scope_for_context(
        context,
        manifest,
    )
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

    targets: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    if plan_result.get("migration_required"):
        blockers.append(
            {
                "code": "book_plan_reference_migration_required",
                "message": "Book Plan stable-reference migration must be completed.",
            }
        )
    if not validation.get("valid"):
        blockers.append(
            {
                "code": "book_plan_incomplete_or_inconsistent",
                "message": (
                    "Book Plan must be complete and consistent with approved Book Canon."
                ),
            }
        )
    if not plan_current:
        blockers.append(
            {
                "code": "book_plan_not_approved",
                "message": "Book Plan approval must be current before compilation.",
            }
        )
    if not author_exists:
        blockers.append(
            {
                "code": "author_canon_missing",
                "message": "Project-local Author Canon is required for Book Runtime Context v2.",
            }
        )
    if not index_current:
        blockers.append(
            {
                "code": "canon_index_not_current",
                "message": "Canon Index must be current before compilation.",
            }
        )

    for book in plan.get("books") or []:
        book_number = int(book.get("book_number") or 0)
        scope_book = scope_books.get(book_number)
        scope_current = bool(
            scope_book
            and scope_book.get("approval_status")
            == book_scope_service.APPROVAL_APPROVED
            and scope_book.get("approval_fresh") is True
            and (scope_book.get("freshness") or {}).get("fresh") is True
            and (scope_book.get("validation") or {}).get("valid") is True
        )
        if not scope_current:
            blockers.append(
                {
                    "code": "book_scope_not_approved",
                    "book_number": book_number,
                    "message": (
                        f"Book {book_number} Canon for This Book must be approved and current."
                    ),
                }
            )
        targets.append(
            _target_status(
                context=context,
                book=book,
                plan=plan,
                scope_book=scope_book or {},
                author_hash=author_hash,
                index_revision=index_revision,
            )
        )

    expected_count = int(manifest.get("book_count") or 0)
    compiler_ready = bool(
        plan_current
        and author_exists
        and index_current
        and expected_count > 0
        and len(targets) == expected_count
        and not blockers
    )

    current_count = sum(
        1 for target in targets if target["status"] == STATUS_CURRENT
    )
    missing_count = sum(
        1 for target in targets if target["status"] == STATUS_MISSING
    )
    outdated_count = sum(
        1 for target in targets if target["status"] == STATUS_OUTDATED
    )

    return {
        "status": (
            STATUS_CURRENT
            if compiler_ready and current_count == len(targets)
            else STATUS_READY
            if compiler_ready
            else STATUS_BLOCKED
        ),
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
            "approved_content_hash": str(plan.get("approved_content_hash") or ""),
            "valid": bool(validation.get("valid")),
        },
        "book_scope": {
            "schema_version": scope_result.get("schema_version"),
            "exists": bool(scope_result.get("exists")),
            "approved_current_count": sum(
                1
                for scope_book in scope_books.values()
                if scope_book.get("approval_status")
                == book_scope_service.APPROVAL_APPROVED
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
            "Book Runtime Context v2 is ready to compile."
            if compiler_ready
            else "Book Runtime Context v2 compilation is blocked."
        ),
    }


def compile_book_knowledge_packs(project_id: str) -> dict[str, Any]:
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
    status = get_book_runtime_context_status_for_context(context, manifest)
    if not status["compiler_ready"]:
        messages = [
            str(item.get("message") or "")
            for item in status.get("blockers") or []
            if item.get("message")
        ]
        raise BookKnowledgePackNotReadyError(
            " ".join(messages) or "Book Runtime Context v2 is not ready."
        )

    plan_result = book_plan_service.get_book_plan_for_context(context, manifest)
    plan = plan_result["plan"]
    scope_result = book_scope_service.get_book_scope_for_context(context, manifest)
    scope_books = {
        int(book.get("book_number") or 0): book
        for book in scope_result["document"]["books"]
    }

    author_path = _author_canon_path(context)
    if not author_path.exists():
        raise BookKnowledgePackSourceMissingError(
            "Project-local Author Canon is missing."
        )
    author_canon = project_loader.read_json(author_path)
    author_hash = _sha256_file(author_path)

    index_status = canon_index_service.ensure_current_index(context.project_id)
    index_revision = str(index_status.get("index_content_hash") or "")
    if index_status.get("index_state") != "current" or not index_revision:
        raise BookKnowledgePackNotReadyError(
            "Canon Index must be current before Book Runtime Context v2 compilation."
        )

    records_by_id = _author_record_map(author_canon)
    all_record_ids = set(records_by_id)
    global_rules = _global_required_rules(author_canon)
    full_context_tokens, full_context_basis = _full_context_token_estimate(
        context,
        author_canon,
    )

    generated_at = utc_now_iso()
    generated: list[dict[str, Any]] = []

    for book in plan.get("books") or []:
        book_number = int(book.get("book_number") or 0)
        scope_book = scope_books.get(book_number) or {}
        selected_ids = [
            str(item.get("record_id") or "")
            for item in scope_book.get("selections") or []
            if item.get("record_id")
        ]
        selected_set = set(selected_ids)

        missing_source_ids = [
            record_id
            for record_id in selected_ids
            if record_id not in records_by_id
        ]
        if missing_source_ids:
            raise BookKnowledgePackSourceMissingError(
                "Book Scope contains Canon IDs missing from Author Canon: "
                + ", ".join(missing_source_ids)
            )

        bounded_records = [
            _bounded_record_payload(
                records_by_id[record_id],
                selected_ids=selected_set,
                all_record_ids=all_record_ids,
            )
            for record_id in selected_ids
        ]

        dependency_set = _dependency_set(
            plan=plan,
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
        book_tokens = _estimate_tokens(body)
        token_reduction = max(0, full_context_tokens - book_tokens)
        reduction_pct = (
            round((token_reduction / full_context_tokens) * 100.0, 2)
            if full_context_tokens > 0
            else 0.0
        )
        content = _render_book_runtime_context(
            context=context,
            book=book,
            plan=plan,
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

        target_path = _book_runtime_context_path(context, book_number)
        _write_text_atomic(target_path, content)

        generated.append(
            {
                "book_number": book_number,
                "label": f"Book {book_number:02d} Runtime Context v2",
                "project_relative_path": _relative(
                    target_path,
                    context.project_dir,
                ),
                "sha256": _sha256_file(target_path),
                "size_bytes": target_path.stat().st_size,
                "status": STATUS_CURRENT,
                "selected_record_count": len(selected_ids),
                "source_book_plan_revision": int(plan.get("revision") or 0),
                "source_book_plan_sha256": str(plan.get("content_hash") or ""),
                "source_book_scope_revision": int(scope_book.get("revision") or 0),
                "source_book_scope_sha256": str(scope_book.get("content_hash") or ""),
                "source_author_canon_sha256": author_hash,
                "source_canon_index_revision": index_revision,
                "dependency_set_sha256": dependency_set,
                "estimated_tokens": book_tokens,
                "full_context_estimated_tokens": full_context_tokens,
                "estimated_token_reduction": token_reduction,
                "estimated_token_reduction_percent": reduction_pct,
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
            "Book Runtime Context v2 artifacts compiled from bounded Book Canon. "
            "Prompt, provider, continuity, and generation boundaries remain locked."
        ),
    }


def _target_status(
    *,
    context: ProjectContext,
    book: dict[str, Any],
    plan: dict[str, Any],
    scope_book: dict[str, Any],
    author_hash: str,
    index_revision: str,
) -> dict[str, Any]:
    book_number = int(book.get("book_number") or 0)
    path = _book_runtime_context_path(context, book_number)
    exists = path.exists()
    metadata = _read_compiler_metadata(path) if exists else {}
    dependency_set = _dependency_set(
        plan=plan,
        scope_book=scope_book,
        author_hash=author_hash,
        index_revision=index_revision,
    )

    current = bool(
        exists
        and metadata.get("schema_version") == BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION
        and metadata.get("book_number") == str(book_number)
        and metadata.get("book_plan_revision")
        == str(int(plan.get("revision") or 0))
        and metadata.get("book_plan_sha256")
        == str(plan.get("content_hash") or "")
        and metadata.get("book_scope_revision")
        == str(int(scope_book.get("revision") or 0))
        and metadata.get("book_scope_sha256")
        == str(scope_book.get("content_hash") or "")
        and metadata.get("author_canon_sha256") == author_hash
        and metadata.get("canon_index_revision") == index_revision
        and metadata.get("dependency_set_sha256") == dependency_set
        and bool(author_hash)
        and bool(index_revision)
    )

    return {
        "book_number": book_number,
        "label": f"Book {book_number:02d} Runtime Context v2",
        "project_relative_path": _relative(path, context.project_dir),
        "exists": exists,
        "status": (
            STATUS_CURRENT
            if current
            else STATUS_OUTDATED
            if exists
            else STATUS_MISSING
        ),
        "sha256": _sha256_file(path) if exists else "",
        "size_bytes": path.stat().st_size if exists else 0,
        "source_book_plan_revision": metadata.get("book_plan_revision", ""),
        "source_book_plan_sha256": metadata.get("book_plan_sha256", ""),
        "source_book_scope_revision": metadata.get("book_scope_revision", ""),
        "source_book_scope_sha256": metadata.get("book_scope_sha256", ""),
        "source_author_canon_sha256": metadata.get("author_canon_sha256", ""),
        "source_canon_index_revision": metadata.get("canon_index_revision", ""),
        "dependency_set_sha256": metadata.get("dependency_set_sha256", ""),
        "selected_record_count": _safe_int(
            metadata.get("selected_record_count")
        ),
        "estimated_tokens": _safe_int(metadata.get("estimated_tokens")),
        "full_context_estimated_tokens": _safe_int(
            metadata.get("full_context_estimated_tokens")
        ),
    }


def _dependency_set(
    *,
    plan: dict[str, Any],
    scope_book: dict[str, Any],
    author_hash: str,
    index_revision: str,
) -> str:
    payload = {
        "book_plan_revision": int(plan.get("revision") or 0),
        "book_plan_sha256": str(plan.get("content_hash") or ""),
        "book_scope_revision": int(scope_book.get("revision") or 0),
        "book_scope_sha256": str(scope_book.get("content_hash") or ""),
        "author_canon_sha256": author_hash,
        "canon_index_revision": index_revision,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
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
            "## Selected Book Canon",
            "",
            (
                f"Selected records: {len(scope_book.get('selections') or [])}. "
                "Only these addressable records are rendered below."
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
    plan: dict[str, Any],
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
        f"- Book Plan Revision: `{int(plan.get('revision') or 0)}`",
        f"- Book Plan SHA-256: `{plan.get('content_hash') or ''}`",
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
