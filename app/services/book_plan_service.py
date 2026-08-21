"""
Project-local Book Plan data contract.

This service owns the versioned Book Plan JSON document stored at:

    data/projects/<project_id>/book_plan.json

It defines draft persistence, stable content hashing, revision tracking, and
structural validation. It does not approve plans, compile book runtime context,
construct prompts, call providers, write runtime memory, persist generated
drafts, or unlock generation.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path
import time
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import book_scope_service, canon_index_service


BOOK_PLAN_SERVICE_MARKER = "project-book-plan-stable-ref-consistency-20260816"
BOOK_PLAN_SCHEMA_VERSION = "project_book_plan_v3_per_book_approval"
PREVIOUS_BOOK_PLAN_SCHEMA_VERSION = "project_book_plan_v2_stable_refs"
LEGACY_BOOK_PLAN_SCHEMA_VERSION = "project_book_plan_v1"
BOOK_PLAN_FILENAME = "book_plan.json"
BOOK_PLAN_MIGRATION_REPORT_FILENAME = "book_plan_reference_migration_report.json"

BOOK_REFERENCE_FIELDS = {
    "major_events": "events",
    "required_characters": "characters",
    "required_locations": "locations",
}
BOOK_TEXT_LIST_FIELDS = (
    "allowed_reveals",
    "forbidden_future_knowledge",
)

STATUS_NOT_STARTED = "not_started"
STATUS_DRAFT = "draft"
STATUS_COMPLETE = "complete"

APPROVAL_NOT_READY = "not_ready"
APPROVAL_REQUIRED = "approval_required"
APPROVAL_APPROVED = "approved"
APPROVAL_OUTDATED = "outdated"

BOOK_REQUIRED_TEXT_FIELDS = (
    "title",
    "time_span",
    "primary_arc",
    "ending_state",
)
BOOK_LIST_FIELDS = (
    "major_events",
    "required_characters",
    "required_locations",
    "allowed_reveals",
    "forbidden_future_knowledge",
)


class BookPlanContractError(ValueError):
    """Raised when a Book Plan payload violates the data contract."""


class BookPlanReferenceConflictError(BookPlanContractError):
    """Raised when an author-facing label cannot resolve to one stable Canon ID."""


def get_book_plan_contract() -> dict[str, Any]:
    """Return the stable, provider-free Book Plan schema contract."""

    return {
        "status": "ok",
        "service": BOOK_PLAN_SERVICE_MARKER,
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "document": {
            "filename": BOOK_PLAN_FILENAME,
            "storage_scope": "project_local",
            "status_values": [
                STATUS_NOT_STARTED,
                STATUS_DRAFT,
                STATUS_COMPLETE,
            ],
            "approval_values": [
                APPROVAL_NOT_READY,
                APPROVAL_REQUIRED,
                APPROVAL_APPROVED,
                APPROVAL_OUTDATED,
            ],
        },
        "book_fields": {
            "book_number": {
                "type": "integer",
                "required": True,
                "minimum": 1,
            },
            "title": {"type": "string", "required": True},
            "time_span": {"type": "string", "required": True},
            "primary_arc": {"type": "string", "required": True},
            "major_events": {"type": "array[record_ref]", "required": False},
            "required_characters": {"type": "array[record_ref]", "required": False},
            "required_locations": {"type": "array[record_ref]", "required": False},
            "ending_state": {"type": "string", "required": True},
            "handoff_to_next_book": {
                "type": "string",
                "required_for": "all_non_final_books",
            },
            "allowed_reveals": {"type": "array[string]", "required": False},
            "forbidden_future_knowledge": {
                "type": "array[string]",
                "required": False,
            },
            "notes": {"type": "string", "required": False},
        },
        "reference_contract": {
            "identity": "record_id",
            "author_input": "exact label or alias may be resolved only when unique",
            "unresolved_legacy": "preserved explicitly; never guessed",
            "book_scope_consistency": (
                "major_events, required_characters, and required_locations "
                "must be selected in the approved current Book Scope for that book"
            ),
        },
        "migration_contract": {
            "from_schema": LEGACY_BOOK_PLAN_SCHEMA_VERSION,
            "to_schema": BOOK_PLAN_SCHEMA_VERSION,
            "report_filename": BOOK_PLAN_MIGRATION_REPORT_FILENAME,
            "author_truth_invented": False,
        },
        "revision_contract": {
            "revision": "increments only when stable plan content changes",
            "content_hash": "sha256 of normalized project_id, book_count, and books",
            "workflow_fields_excluded_from_hash": [
                "status",
                "approval_status",
                "created_at",
                "updated_at",
                "revision",
                "content_hash",
                "approved_content_hash",
                "approved_revision",
                "approved_at",
            ],
        },
        "approval_contract": {
            "approval_basis": "current normalized per-book content_hash",
            "fresh_when": "per-book approved_content_hash equals per-book content_hash and Book Scope remains approved/current",
            "invalidation": "stable content change invalidates only the changed book approval",
            "approval_required": "the selected book must be complete/valid and its Book Scope approved/current",
        },
        "execution_locks": _execution_locks(),
    }


def get_book_plan(project_id: str) -> dict[str, Any]:
    """Return the saved Book Plan or a non-persisted default document."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_book_plan_for_context(context, manifest.to_dict())


def get_book_plan_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    scope_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a normalized plan without writing when the file is absent."""

    path = _book_plan_path(context)
    migration_required = False
    migration_summary: dict[str, Any] = {
        "required": False,
        "source_schema_version": "",
        "resolved_count": 0,
        "unresolved_count": 0,
    }
    if path.exists():
        stored = project_loader.read_json(path)
        source_schema = str(stored.get("schema_version") or LEGACY_BOOK_PLAN_SCHEMA_VERSION)
        migration_required = source_schema not in {BOOK_PLAN_SCHEMA_VERSION, PREVIOUS_BOOK_PLAN_SCHEMA_VERSION}
        stats = {"resolved_count": 0, "unresolved_count": 0, "unresolved": []}
        plan = _normalize_existing_document(
            context,
            manifest,
            stored,
            migration_stats=stats,
        )
        migration_summary = {
            "required": migration_required,
            "source_schema_version": source_schema,
            **stats,
        }
        exists = True
    else:
        plan = _default_document(context, manifest)
        exists = False

    validation = _validate_plan(
        context,
        plan,
        int(manifest.get("book_count") or 0),
        scope_result=scope_result,
        manifest=manifest,
    )
    _decorate_book_workflow(plan, validation)
    plan["status"] = _status_for(validation, exists)
    plan["approval_status"] = _aggregate_approval_status(plan)
    plan["approval_fresh"] = bool(
        plan.get("book_workflow")
        and all(item.get("approval_fresh") is True for item in plan["book_workflow"])
    )
    plan["validation"] = validation

    return {
        "status": "ok",
        "service": BOOK_PLAN_SERVICE_MARKER,
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "exists": exists,
        "project_relative_path": _relative(path, context.project_dir),
        "plan": plan,
        "migration_required": migration_required,
        "migration": migration_summary,
        "execution_locks": _execution_locks(),
    }


def get_book_plan_status(project_id: str) -> dict[str, Any]:
    """Return compact Book Plan persistence and validation status."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_book_plan_status_for_context(context, manifest.to_dict())


def get_book_plan_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return compact status without mutating project files."""

    result = get_book_plan_for_context(context, manifest)
    plan = result["plan"]
    validation = plan["validation"]

    return {
        "status": plan["status"],
        "service": BOOK_PLAN_SERVICE_MARKER,
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "exists": result["exists"],
        "project_relative_path": result["project_relative_path"],
        "revision": int(plan.get("revision") or 0),
        "content_hash": str(plan.get("content_hash") or ""),
        "expected_book_count": validation["expected_book_count"],
        "planned_book_count": validation["planned_book_count"],
        "complete_book_count": validation["complete_book_count"],
        "valid": validation["valid"],
        "approval_status": str(
            plan.get("approval_status") or APPROVAL_NOT_READY
        ),
        "approval_fresh": bool(plan.get("approval_fresh")),
        "approved_revision": int(plan.get("approved_revision") or 0),
        "approved_content_hash": str(
            plan.get("approved_content_hash") or ""
        ),
        "approved_at": str(plan.get("approved_at") or ""),
        "approval_enabled": bool(validation["valid"] and not result["migration_required"]),
        "authoring_enabled": True,
        "book_runtime_context_enabled": False,
        "migration_required": bool(result["migration_required"]),
        "migration": deepcopy(result["migration"]),
        "issues": deepcopy(validation["issues"]),
        "execution_locks": _execution_locks(),
    }


def save_book_plan_draft(
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist a normalized project-local Book Plan draft."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return save_book_plan_draft_for_context(
        context,
        manifest.to_dict(),
        payload,
    )


def save_book_plan_draft_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist draft content atomically and increment revision on change."""

    if not isinstance(payload, dict):
        raise BookPlanContractError("Book Plan payload must be an object.")

    expected_book_count = int(manifest.get("book_count") or 0)
    if expected_book_count < 1:
        raise BookPlanContractError(
            "Project manifest book_count must be at least 1."
        )

    incoming_books = payload.get("books")
    if incoming_books is None:
        incoming_books = []
    if not isinstance(incoming_books, list):
        raise BookPlanContractError("books must be an array.")

    normalized_books = _normalize_books(
        context,
        incoming_books,
        expected_book_count,
        strict_new=True,
    )
    path = _book_plan_path(context)
    existing = (
        _normalize_existing_document(
            context,
            manifest,
            project_loader.read_json(path),
        )
        if path.exists()
        else _default_document(context, manifest)
    )

    now = utc_now_iso()
    candidate = {
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "service": BOOK_PLAN_SERVICE_MARKER,
        "project_id": context.project_id,
        "template_id": str(manifest.get("template_id") or ""),
        "genre": str(manifest.get("genre") or ""),
        "book_count": expected_book_count,
        "status": STATUS_DRAFT,
        "approval_status": APPROVAL_NOT_READY,
        "revision": int(existing.get("revision") or 0),
        "content_hash": "",
        "approved_revision": int(
            existing.get("approved_revision") or 0
        ),
        "approved_content_hash": str(
            existing.get("approved_content_hash") or ""
        ),
        "approved_at": str(existing.get("approved_at") or ""),
        "created_at": str(existing.get("created_at") or now),
        "updated_at": now,
        "books": normalized_books,
        "book_workflow": _merge_book_workflow(existing, normalized_books),
    }

    content_hash = _content_hash(candidate)
    if content_hash != str(existing.get("content_hash") or ""):
        candidate["revision"] += 1
    candidate["content_hash"] = content_hash

    validation = _validate_plan(context, candidate, expected_book_count)
    _decorate_book_workflow(candidate, validation)
    candidate["status"] = _status_for(validation, True)
    candidate["approval_status"] = _aggregate_approval_status(candidate)
    candidate["approval_fresh"] = bool(
        candidate.get("book_workflow")
        and all(item.get("approval_fresh") is True for item in candidate["book_workflow"])
    )
    _sync_legacy_aggregate_approval_fields(candidate)

    _write_json_atomic(path, _stored_document(candidate))

    return {
        "status": "saved",
        "service": BOOK_PLAN_SERVICE_MARKER,
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "project_relative_path": _relative(path, context.project_dir),
        "plan": {
            **candidate,
            "validation": validation,
        },
        "execution_locks": _execution_locks(),
    }



def approve_book_plan(project_id: str, book_number: int) -> dict[str, Any]:
    """Approve one current, complete Book Plan entry."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return approve_book_plan_for_context(
        context,
        manifest.to_dict(),
        book_number=book_number,
    )


def approve_book_plan_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
) -> dict[str, Any]:
    """Persist per-book approval provenance without compiling runtime context."""

    path = _book_plan_path(context)
    if not path.exists():
        raise BookPlanContractError("Book Plan must be saved before approval.")

    expected_book_count = int(manifest.get("book_count") or 0)
    if book_number < 1 or book_number > expected_book_count:
        raise BookPlanContractError(
            f"book_number {book_number} is outside 1..{expected_book_count}."
        )

    stored = project_loader.read_json(path)
    source_schema = str(stored.get("schema_version") or LEGACY_BOOK_PLAN_SCHEMA_VERSION)
    if source_schema not in {BOOK_PLAN_SCHEMA_VERSION, PREVIOUS_BOOK_PLAN_SCHEMA_VERSION}:
        raise BookPlanContractError(
            "Book Plan stable-reference migration must be completed before approval."
        )

    plan = _normalize_existing_document(context, manifest, stored)
    validation = _validate_plan(context, plan, expected_book_count)
    _decorate_book_workflow(plan, validation)
    book_validation = _book_validation(validation, book_number)
    if not book_validation or not book_validation.get("complete"):
        raise BookPlanContractError(
            f"Book {book_number} Plan must be complete and valid before approval."
        )
    if book_validation.get("book_scope_approved") is not True:
        raise BookPlanContractError(
            f"Book {book_number} Book Scope must be approved and current before Book Plan approval."
        )

    workflow = get_book_workflow(plan, book_number)
    now = utc_now_iso()
    workflow["approval_status"] = APPROVAL_APPROVED
    workflow["approval_fresh"] = True
    workflow["approved_revision"] = int(workflow.get("revision") or 0)
    workflow["approved_content_hash"] = str(workflow.get("content_hash") or "")
    workflow["approved_at"] = now

    plan["schema_version"] = BOOK_PLAN_SCHEMA_VERSION
    plan["status"] = _status_for(validation, True)
    plan["approval_status"] = _aggregate_approval_status(plan)
    plan["approval_fresh"] = bool(
        plan.get("book_workflow")
        and all(item.get("approval_fresh") is True for item in plan["book_workflow"])
    )
    plan["updated_at"] = now
    _sync_legacy_aggregate_approval_fields(plan)

    _write_json_atomic(path, _stored_document(plan))

    return {
        "status": "approved",
        "service": BOOK_PLAN_SERVICE_MARKER,
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "project_relative_path": _relative(path, context.project_dir),
        "plan": {**plan, "validation": validation},
        "book_approval": deepcopy(workflow),
        "execution_locks": _execution_locks(),
    }


def revoke_book_plan_approval(project_id: str, book_number: int) -> dict[str, Any]:
    """Revoke one Book Plan approval while preserving plan content."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return revoke_book_plan_approval_for_context(
        context,
        manifest.to_dict(),
        book_number=book_number,
    )


def revoke_book_plan_approval_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
) -> dict[str, Any]:
    path = _book_plan_path(context)
    if not path.exists():
        raise BookPlanContractError(
            "Book Plan must be saved before approval can be revoked."
        )

    expected_book_count = int(manifest.get("book_count") or 0)
    if book_number < 1 or book_number > expected_book_count:
        raise BookPlanContractError(
            f"book_number {book_number} is outside 1..{expected_book_count}."
        )

    plan = _normalize_existing_document(
        context, manifest, project_loader.read_json(path)
    )
    validation = _validate_plan(context, plan, expected_book_count)
    _decorate_book_workflow(plan, validation)
    workflow = get_book_workflow(plan, book_number)
    now = utc_now_iso()
    workflow["approved_revision"] = 0
    workflow["approved_content_hash"] = ""
    workflow["approved_at"] = ""
    workflow["approval_fresh"] = False
    workflow["approval_status"] = (
        APPROVAL_REQUIRED
        if (_book_validation(validation, book_number) or {}).get("complete")
        and (_book_validation(validation, book_number) or {}).get("book_scope_approved") is True
        else APPROVAL_NOT_READY
    )

    plan["schema_version"] = BOOK_PLAN_SCHEMA_VERSION
    plan["status"] = _status_for(validation, True)
    plan["approval_status"] = _aggregate_approval_status(plan)
    plan["approval_fresh"] = bool(
        plan.get("book_workflow")
        and all(item.get("approval_fresh") is True for item in plan["book_workflow"])
    )
    plan["updated_at"] = now
    _sync_legacy_aggregate_approval_fields(plan)
    _write_json_atomic(path, _stored_document(plan))

    return {
        "status": "approval_revoked",
        "service": BOOK_PLAN_SERVICE_MARKER,
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "project_relative_path": _relative(path, context.project_dir),
        "plan": {**plan, "validation": validation},
        "book_approval": deepcopy(workflow),
        "execution_locks": _execution_locks(),
    }


def migrate_book_plan_references(project_id: str) -> dict[str, Any]:
    """Explicitly migrate a stored v1 Book Plan to stable reference-backed v2."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    path = _book_plan_path(context)
    if not path.exists():
        return {
            "status": "not_required",
            "service": BOOK_PLAN_SERVICE_MARKER,
            "schema_version": BOOK_PLAN_SCHEMA_VERSION,
            "project_id": context.project_id,
            "reason": "Book Plan has not been created.",
        }

    stored = project_loader.read_json(path)
    source_schema = str(
        stored.get("schema_version") or LEGACY_BOOK_PLAN_SCHEMA_VERSION
    )
    if source_schema == BOOK_PLAN_SCHEMA_VERSION:
        return {
            "status": "not_required",
            "service": BOOK_PLAN_SERVICE_MARKER,
            "schema_version": BOOK_PLAN_SCHEMA_VERSION,
            "project_id": context.project_id,
            "reason": "Book Plan already uses stable references.",
        }
    if source_schema not in {LEGACY_BOOK_PLAN_SCHEMA_VERSION, PREVIOUS_BOOK_PLAN_SCHEMA_VERSION}:
        raise BookPlanContractError(
            f"Unsupported Book Plan schema for migration: {source_schema}."
        )

    stats: dict[str, Any] = {
        "resolved_count": 0,
        "unresolved_count": 0,
        "unresolved": [],
    }
    migrated = _normalize_existing_document(
        context,
        manifest.to_dict(),
        stored,
        migration_stats=stats,
    )
    old_hash = str(stored.get("content_hash") or "")
    migrated_hash = _content_hash(migrated)
    if migrated_hash != old_hash:
        migrated["revision"] = int(stored.get("revision") or 0) + 1
    migrated["content_hash"] = migrated_hash
    migrated["updated_at"] = utc_now_iso()

    archive_dir = context.project_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "book_plan_before_stable_refs_v1.json"
    if not archive_path.exists():
        _write_json_atomic(archive_path, stored)

    _write_json_atomic(path, _stored_document(migrated))
    report = {
        "status": "migrated",
        "service": BOOK_PLAN_SERVICE_MARKER,
        "from_schema_version": source_schema,
        "to_schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "resolved_count": int(stats["resolved_count"]),
        "unresolved_count": int(stats["unresolved_count"]),
        "unresolved": deepcopy(stats["unresolved"]),
        "author_truth_invented": False,
        "archive_path": _relative(archive_path, context.project_dir),
        "book_plan_revision": int(migrated.get("revision") or 0),
        "book_plan_content_hash": migrated_hash,
        "approval_preserved_as_provenance": bool(
            stored.get("approved_content_hash")
        ),
        "approval_fresh": False,
    }
    _write_json_atomic(
        context.project_dir / BOOK_PLAN_MIGRATION_REPORT_FILENAME,
        report,
    )
    return report


def get_book_plan_migration_status(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    path = _book_plan_path(context)
    if not path.exists():
        return {
            "status": "not_required",
            "project_id": context.project_id,
            "migration_required": False,
            "current_schema_version": "",
            "target_schema_version": BOOK_PLAN_SCHEMA_VERSION,
        }
    stored = project_loader.read_json(path)
    current = str(
        stored.get("schema_version") or LEGACY_BOOK_PLAN_SCHEMA_VERSION
    )
    compatible_upgrade = current == PREVIOUS_BOOK_PLAN_SCHEMA_VERSION
    return {
        "status": "compatible_upgrade" if compatible_upgrade else ("migration_required" if current != BOOK_PLAN_SCHEMA_VERSION else "current"),
        "project_id": context.project_id,
        "migration_required": current not in {BOOK_PLAN_SCHEMA_VERSION, PREVIOUS_BOOK_PLAN_SCHEMA_VERSION},
        "compatible_upgrade": compatible_upgrade,
        "current_schema_version": current,
        "target_schema_version": BOOK_PLAN_SCHEMA_VERSION,
    }



def _default_document(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    book_count = int(manifest.get("book_count") or 0)
    return {
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "service": BOOK_PLAN_SERVICE_MARKER,
        "project_id": context.project_id,
        "template_id": str(manifest.get("template_id") or ""),
        "genre": str(manifest.get("genre") or ""),
        "book_count": book_count,
        "status": STATUS_NOT_STARTED,
        "approval_status": APPROVAL_NOT_READY,
        "approval_fresh": False,
        "revision": 0,
        "content_hash": "",
        "approved_revision": 0,
        "approved_content_hash": "",
        "approved_at": "",
        "created_at": "",
        "updated_at": "",
        "books": [
            _empty_book(book_number)
            for book_number in range(1, book_count + 1)
        ],
        "book_workflow": [
            _empty_book_workflow(book_number, _book_content_hash(_empty_book(book_number)))
            for book_number in range(1, book_count + 1)
        ],
    }


def _normalize_existing_document(
    context: ProjectContext,
    manifest: dict[str, Any],
    stored: Any,
    *,
    migration_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(stored, dict):
        raise BookPlanContractError(
            "Stored Book Plan must contain a JSON object."
        )

    expected_book_count = int(manifest.get("book_count") or 0)
    source_schema = str(stored.get("schema_version") or LEGACY_BOOK_PLAN_SCHEMA_VERSION)
    normalized_books = _normalize_books(
        context,
        stored.get("books") or [],
        expected_book_count,
        strict_new=False,
        legacy_mode=source_schema == LEGACY_BOOK_PLAN_SCHEMA_VERSION,
        migration_stats=migration_stats,
    )
    normalized_workflow = _normalize_book_workflow(
        stored,
        normalized_books,
        source_schema=source_schema,
    )
    document = {
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "service": BOOK_PLAN_SERVICE_MARKER,
        "project_id": context.project_id,
        "template_id": str(manifest.get("template_id") or ""),
        "genre": str(manifest.get("genre") or ""),
        "book_count": expected_book_count,
        "status": str(stored.get("status") or STATUS_DRAFT),
        "approval_status": str(
            stored.get("approval_status") or APPROVAL_NOT_READY
        ),
        "approval_fresh": False,
        "revision": int(stored.get("revision") or 0),
        "content_hash": str(stored.get("content_hash") or ""),
        "approved_revision": int(
            stored.get("approved_revision") or 0
        ),
        "approved_content_hash": str(
            stored.get("approved_content_hash") or ""
        ),
        "approved_at": str(stored.get("approved_at") or ""),
        "created_at": str(stored.get("created_at") or ""),
        "updated_at": str(stored.get("updated_at") or ""),
        "books": normalized_books,
        "book_workflow": normalized_workflow,
    }
    calculated = _content_hash(document)
    if not document["content_hash"]:
        document["content_hash"] = calculated
    return document


def _normalize_books(
    context: ProjectContext,
    books: list[Any],
    expected_book_count: int,
    *,
    strict_new: bool,
    legacy_mode: bool = False,
    migration_stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_number: dict[int, dict[str, Any]] = {}

    for raw in books:
        if not isinstance(raw, dict):
            raise BookPlanContractError(
                "Each Book Plan entry must be an object."
            )

        try:
            book_number = int(raw.get("book_number"))
        except (TypeError, ValueError) as exc:
            raise BookPlanContractError(
                "Each book requires an integer book_number."
            ) from exc

        if book_number < 1 or book_number > expected_book_count:
            raise BookPlanContractError(
                f"book_number {book_number} is outside 1..{expected_book_count}."
            )
        if book_number in by_number:
            raise BookPlanContractError(
                f"Duplicate book_number: {book_number}."
            )

        normalized = _empty_book(book_number)
        for field in BOOK_REQUIRED_TEXT_FIELDS:
            normalized[field] = _clean_text(raw.get(field))
        normalized["handoff_to_next_book"] = _clean_text(
            raw.get("handoff_to_next_book")
        )
        normalized["notes"] = _clean_text(raw.get("notes"))
        for field, group_id in BOOK_REFERENCE_FIELDS.items():
            normalized[field] = _normalize_reference_list(
                context,
                raw.get(field),
                field=field,
                record_group_id=group_id,
                strict_new=strict_new,
                legacy_mode=legacy_mode,
                migration_stats=migration_stats,
            )
        for field in BOOK_TEXT_LIST_FIELDS:
            normalized[field] = _clean_string_list(raw.get(field))
        by_number[book_number] = normalized

    return [
        by_number.get(book_number, _empty_book(book_number))
        for book_number in range(1, expected_book_count + 1)
    ]


def _validate_plan(
    context: ProjectContext,
    plan: dict[str, Any],
    expected_book_count: int,
    *,
    scope_result: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    books = list(plan.get("books") or [])
    issues: list[dict[str, Any]] = []
    complete_count = 0

    if len(books) != expected_book_count:
        issues.append(
            {
                "code": "book_count_mismatch",
                "message": (
                    f"Expected {expected_book_count} books; "
                    f"found {len(books)}."
                ),
            }
        )

    if scope_result is None:
        scope_result = book_scope_service.get_book_scope_for_context(
            context,
            manifest or project_loader.load_manifest(context.project_id).to_dict(),
        )
    scope_by_book = {
        int(item.get("book_number") or 0): item
        for item in (scope_result.get("document") or {}).get("books", [])
    }

    per_book: list[dict[str, Any]] = []
    for book in books:
        book_number = int(book.get("book_number") or 0)
        missing = [
            field
            for field in BOOK_REQUIRED_TEXT_FIELDS
            if not _clean_text(book.get(field))
        ]
        if (
            0 < book_number < expected_book_count
            and not _clean_text(book.get("handoff_to_next_book"))
        ):
            missing.append("handoff_to_next_book")

        complete = not missing
        if complete:
            complete_count += 1
        else:
            issues.append(
                {
                    "code": "book_incomplete",
                    "book_number": book_number,
                    "missing_fields": missing,
                    "message": (
                        f"Book {book_number} is missing required planning fields."
                    ),
                }
            )

        scope_book = scope_by_book.get(book_number)
        reference_issues = _validate_book_references(
            context,
            book,
            book_number=book_number,
            scope_book=scope_book,
        )
        time_span_issues = _validate_time_span_against_scope(
            context,
            book,
            book_number=book_number,
            scope_book=scope_book,
        )
        issues.extend(reference_issues)
        issues.extend(time_span_issues)

        scope_approved = bool(
            scope_book
            and scope_book.get("approval_status") == book_scope_service.APPROVAL_APPROVED
            and scope_book.get("approval_fresh") is True
        )
        per_book.append(
            {
                "book_number": book_number,
                "complete": complete and not reference_issues and not time_span_issues,
                "missing_fields": missing,
                "reference_issue_count": len(reference_issues),
                "time_span_issue_count": len(time_span_issues),
                "book_scope_approved": scope_approved,
            }
        )

    valid = (
        expected_book_count > 0
        and len(books) == expected_book_count
        and complete_count == expected_book_count
        and not issues
    )
    return {
        "valid": valid,
        "expected_book_count": expected_book_count,
        "planned_book_count": len(books),
        "complete_book_count": complete_count,
        "issues": issues,
        "books": per_book,
    }


def _status_for(
    validation: dict[str, Any],
    exists: bool,
) -> str:
    if not exists:
        return STATUS_NOT_STARTED
    if validation.get("valid"):
        return STATUS_COMPLETE
    return STATUS_DRAFT



def _book_content_hash(book: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in book.items()
        if key in {
            "book_number", "title", "time_span", "primary_arc", "major_events",
            "required_characters", "required_locations", "ending_state",
            "handoff_to_next_book", "allowed_reveals",
            "forbidden_future_knowledge", "notes",
        }
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _book_has_content(book: dict[str, Any]) -> bool:
    for key, value in book.items():
        if key == "book_number":
            continue
        if isinstance(value, list) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _empty_book_workflow(book_number: int, content_hash: str) -> dict[str, Any]:
    return {
        "book_number": book_number,
        "revision": 0,
        "content_hash": content_hash,
        "approval_status": APPROVAL_NOT_READY,
        "approval_fresh": False,
        "approved_revision": 0,
        "approved_content_hash": "",
        "approved_at": "",
    }


def _normalize_book_workflow(
    stored: dict[str, Any],
    books: list[dict[str, Any]],
    *,
    source_schema: str,
) -> list[dict[str, Any]]:
    raw_by_number = {
        int(item.get("book_number") or 0): item
        for item in (stored.get("book_workflow") or [])
        if isinstance(item, dict) and int(item.get("book_number") or 0) > 0
    }
    legacy_globally_approved = bool(
        source_schema == PREVIOUS_BOOK_PLAN_SCHEMA_VERSION
        and stored.get("approval_status") == APPROVAL_APPROVED
        and stored.get("approved_content_hash")
        and stored.get("approved_content_hash") == stored.get("content_hash")
    )
    result = []
    for book in books:
        number = int(book.get("book_number") or 0)
        current_hash = _book_content_hash(book)
        raw = raw_by_number.get(number) or {}
        revision = int(raw.get("revision") or (1 if _book_has_content(book) else 0))
        approved_hash = str(raw.get("approved_content_hash") or "")
        approved_revision = int(raw.get("approved_revision") or 0)
        approved_at = str(raw.get("approved_at") or "")
        if legacy_globally_approved and not approved_hash:
            approved_hash = current_hash
            approved_revision = revision
            approved_at = str(stored.get("approved_at") or "")
        result.append({
            "book_number": number,
            "revision": revision,
            "content_hash": current_hash,
            "approval_status": str(raw.get("approval_status") or APPROVAL_NOT_READY),
            "approval_fresh": False,
            "approved_revision": approved_revision,
            "approved_content_hash": approved_hash,
            "approved_at": approved_at,
        })
    return result


def _merge_book_workflow(existing: dict[str, Any], books: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_by_number = {
        int(item.get("book_number") or 0): item
        for item in (existing.get("book_workflow") or [])
        if isinstance(item, dict)
    }
    result = []
    for book in books:
        number = int(book.get("book_number") or 0)
        current_hash = _book_content_hash(book)
        prior = deepcopy(existing_by_number.get(number) or _empty_book_workflow(number, current_hash))
        prior_hash = str(prior.get("content_hash") or "")
        revision = int(prior.get("revision") or 0)
        if prior_hash != current_hash:
            revision += 1
        prior["book_number"] = number
        prior["revision"] = revision
        prior["content_hash"] = current_hash
        prior.setdefault("approved_revision", 0)
        prior.setdefault("approved_content_hash", "")
        prior.setdefault("approved_at", "")
        result.append(prior)
    return result


def _book_validation(validation: dict[str, Any], book_number: int) -> dict[str, Any] | None:
    return next(
        (item for item in validation.get("books") or [] if int(item.get("book_number") or 0) == int(book_number)),
        None,
    )


def get_book_workflow(plan: dict[str, Any], book_number: int) -> dict[str, Any]:
    workflow = next(
        (item for item in plan.get("book_workflow") or [] if int(item.get("book_number") or 0) == int(book_number)),
        None,
    )
    if workflow is None:
        raise BookPlanContractError(f"Book {book_number} has no Book Plan workflow state.")
    return workflow


def _decorate_book_workflow(plan: dict[str, Any], validation: dict[str, Any]) -> None:
    for workflow in plan.get("book_workflow") or []:
        number = int(workflow.get("book_number") or 0)
        book_validation = _book_validation(validation, number) or {}
        complete = bool(book_validation.get("complete"))
        scope_approved = book_validation.get("book_scope_approved") is True
        current_hash = str(workflow.get("content_hash") or "")
        approved_hash = str(workflow.get("approved_content_hash") or "")
        hash_fresh = bool(approved_hash and current_hash and approved_hash == current_hash)
        approval_fresh = bool(hash_fresh and complete and scope_approved)
        workflow["approval_fresh"] = approval_fresh
        if approved_hash:
            workflow["approval_status"] = APPROVAL_APPROVED if approval_fresh else APPROVAL_OUTDATED
        elif complete and scope_approved:
            workflow["approval_status"] = APPROVAL_REQUIRED
        else:
            workflow["approval_status"] = APPROVAL_NOT_READY


def _aggregate_approval_status(plan: dict[str, Any]) -> str:
    workflow = list(plan.get("book_workflow") or [])
    if workflow and all(item.get("approval_fresh") is True for item in workflow):
        return APPROVAL_APPROVED
    if any(item.get("approval_status") == APPROVAL_OUTDATED for item in workflow):
        return APPROVAL_OUTDATED
    if workflow and all(item.get("approval_status") in {APPROVAL_APPROVED, APPROVAL_REQUIRED} for item in workflow):
        return APPROVAL_REQUIRED
    return APPROVAL_NOT_READY


def _sync_legacy_aggregate_approval_fields(plan: dict[str, Any]) -> None:
    if plan.get("approval_fresh") is True:
        plan["approved_revision"] = int(plan.get("revision") or 0)
        plan["approved_content_hash"] = str(plan.get("content_hash") or "")
        plan["approved_at"] = max(
            (str(item.get("approved_at") or "") for item in plan.get("book_workflow") or []),
            default="",
        )
    else:
        plan["approved_revision"] = 0
        plan["approved_content_hash"] = ""
        plan["approved_at"] = ""


def _approval_status(
    plan: dict[str, Any],
    validation: dict[str, Any],
) -> str:
    approved_hash = str(plan.get("approved_content_hash") or "")
    current_hash = str(plan.get("content_hash") or "")

    if approved_hash:
        if current_hash and approved_hash == current_hash:
            return APPROVAL_APPROVED
        return APPROVAL_OUTDATED
    if validation.get("valid"):
        return APPROVAL_REQUIRED
    return APPROVAL_NOT_READY


def _stored_document(plan: dict[str, Any]) -> dict[str, Any]:
    """Remove derived response-only fields before persistence."""

    stored = dict(plan)
    stored.pop("validation", None)
    stored.pop("approval_fresh", None)
    return stored

def _content_hash(plan: dict[str, Any]) -> str:
    payload = {
        "project_id": str(plan.get("project_id") or ""),
        "book_count": int(plan.get("book_count") or 0),
        "books": plan.get("books") or [],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _empty_book(book_number: int) -> dict[str, Any]:
    return {
        "book_number": book_number,
        "title": "",
        "time_span": "",
        "primary_arc": "",
        "major_events": [],
        "required_characters": [],
        "required_locations": [],
        "ending_state": "",
        "handoff_to_next_book": "",
        "allowed_reveals": [],
        "forbidden_future_knowledge": [],
        "notes": "",
    }


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BookPlanContractError("Book Plan list fields must be arrays.")
    cleaned: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned



def _normalize_reference_list(
    context: ProjectContext,
    value: Any,
    *,
    field: str,
    record_group_id: str,
    strict_new: bool,
    legacy_mode: bool,
    migration_stats: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise BookPlanContractError(f"{field} must be an array.")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        ref = _normalize_reference_value(
            context,
            item,
            field=field,
            record_group_id=record_group_id,
            strict_new=strict_new,
            legacy_mode=legacy_mode,
            migration_stats=migration_stats,
        )
        identity = str(ref.get("record_id") or "")
        if not identity:
            identity = "legacy:" + str(ref.get("legacy_label") or "").casefold()
        if identity and identity not in seen:
            normalized.append(ref)
            seen.add(identity)
    return normalized


def _normalize_reference_value(
    context: ProjectContext,
    value: Any,
    *,
    field: str,
    record_group_id: str,
    strict_new: bool,
    legacy_mode: bool,
    migration_stats: dict[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(value, dict):
        record_id = _clean_text(value.get("record_id"))
        if record_id:
            found = canon_index_service.get_record_by_id(
                context.project_id,
                record_id,
            )
            record = found.get("record") if found.get("status") == "found" else None
            if not record:
                if strict_new:
                    raise BookPlanReferenceConflictError(
                        f"{field} references unknown Canon ID {record_id}."
                    )
                return {
                    "record_id": record_id,
                    "record_type": _clean_text(value.get("record_type")),
                    "label": _clean_text(value.get("label")),
                    "resolution_status": "missing",
                }
            if str(record.get("record_group_id") or "") != record_group_id:
                raise BookPlanReferenceConflictError(
                    f"{field} reference {record_id} is not a {record_group_id} record."
                )
            return {
                "record_id": record_id,
                "record_type": str(record.get("record_type") or ""),
                "label": str(record.get("display_label") or record_id),
                "resolution_status": "resolved",
            }

        legacy_label = _clean_text(
            value.get("legacy_label") or value.get("label")
        )
        if legacy_label and not strict_new:
            return {
                "legacy_label": legacy_label,
                "record_type": _clean_text(value.get("record_type")),
                "resolution_status": "unresolved",
            }
        value = legacy_label

    label = _clean_text(value)
    if not label:
        raise BookPlanReferenceConflictError(
            f"{field} contains an empty Canon reference."
        )

    resolution = canon_index_service.resolve_record_key(
        context.project_id,
        label,
        record_group_id=record_group_id,
    )
    candidates = list(resolution.get("candidates") or [])
    if resolution.get("status") == "unique" and len(candidates) == 1:
        record = candidates[0]
        if migration_stats is not None and legacy_mode:
            migration_stats["resolved_count"] = (
                int(migration_stats.get("resolved_count") or 0) + 1
            )
        return {
            "record_id": str(record.get("internal_id") or ""),
            "record_type": str(record.get("record_type") or ""),
            "label": str(record.get("display_label") or label),
            "resolution_status": "resolved",
        }

    if strict_new:
        raise BookPlanReferenceConflictError(
            f"{field} value {label!r} is {resolution.get('status')}; "
            "select one exact Canon record."
        )

    if migration_stats is not None and legacy_mode:
        migration_stats["unresolved_count"] = (
            int(migration_stats.get("unresolved_count") or 0) + 1
        )
        migration_stats.setdefault("unresolved", []).append(
            {
                "field": field,
                "legacy_label": label,
                "resolution_status": str(resolution.get("status") or "missing"),
                "candidate_ids": [
                    str(candidate.get("internal_id") or "")
                    for candidate in candidates
                ],
            }
        )
    return {
        "legacy_label": label,
        "record_type": "",
        "resolution_status": str(resolution.get("status") or "missing"),
    }


def _validate_book_references(
    context: ProjectContext,
    book: dict[str, Any],
    *,
    book_number: int,
    scope_book: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    referenced_ids: list[tuple[str, str]] = []

    for field in BOOK_REFERENCE_FIELDS:
        for ref in book.get(field) or []:
            record_id = _clean_text(ref.get("record_id")) if isinstance(ref, dict) else ""
            if not record_id:
                issues.append(
                    {
                        "code": "unresolved_book_plan_reference",
                        "book_number": book_number,
                        "field": field,
                        "legacy_label": (
                            _clean_text(ref.get("legacy_label"))
                            if isinstance(ref, dict)
                            else _clean_text(ref)
                        ),
                        "message": (
                            f"Book {book_number} {field} contains an unresolved "
                            "legacy Canon reference."
                        ),
                    }
                )
                continue
            referenced_ids.append((field, record_id))

    if not referenced_ids:
        return issues

    if scope_book is None:
        scope = book_scope_service.get_book_scope_for_context(
            context,
            project_loader.load_manifest(context.project_id).to_dict(),
        )
        scope_book = next(
            (
                item
                for item in scope["document"]["books"]
                if int(item.get("book_number") or 0) == book_number
            ),
            None,
        )
    if not scope_book:
        issues.append(
            {
                "code": "book_scope_missing",
                "book_number": book_number,
                "message": f"Book {book_number} has no Book Scope state.",
            }
        )
        return issues

    approved = (
        scope_book.get("approval_status") == book_scope_service.APPROVAL_APPROVED
        and scope_book.get("approval_fresh") is True
    )
    selected_ids = {
        str(item.get("record_id") or "")
        for item in scope_book.get("selections") or []
        if item.get("record_id")
    }
    if not approved:
        issues.append(
            {
                "code": "book_scope_not_approved",
                "book_number": book_number,
                "message": (
                    f"Book {book_number} Book Scope must be approved and current "
                    "before reference-backed Book Plan requirements are valid."
                ),
            }
        )

    for field, record_id in referenced_ids:
        if record_id not in selected_ids:
            issues.append(
                {
                    "code": "book_scope_dependency_conflict",
                    "book_number": book_number,
                    "field": field,
                    "record_id": record_id,
                    "message": (
                        f"Book {book_number} {field} references {record_id}, "
                        "which is not selected in Canon for This Book."
                    ),
                }
            )
    return issues



def _parse_time_span_years(value: Any) -> tuple[int, int] | None:
    """Parse an explicit author-entered year/range without restricting free-form genres."""

    years = [int(match) for match in re.findall(r"(?<!\d)(\d{3,4})(?!\d)", _clean_text(value))]
    if not years:
        return None
    if len(years) == 1:
        return years[0], years[0]
    return min(years), max(years)


def _record_years(value: Any) -> list[int]:
    return [int(match) for match in re.findall(r"(?<!\d)(\d{3,4})(?!\d)", _clean_text(value))]


def _validate_time_span_against_scope(
    context: ProjectContext,
    book: dict[str, Any],
    *,
    book_number: int,
    scope_book: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Validate explicit date ranges against dated events selected into Book Canon.

    Free-form time-span text remains legal for genres without parseable dates. When
    the author supplies a recognizable year or year range, selected dated Canon
    events must fall inside that range.
    """

    parsed = _parse_time_span_years(book.get("time_span"))
    if parsed is None or not scope_book:
        return []

    start_year, end_year = parsed
    issues: list[dict[str, Any]] = []
    for selection in scope_book.get("selections") or []:
        if str(selection.get("record_type") or "").lower() != "event":
            continue
        record_id = _clean_text(selection.get("record_id"))
        if not record_id:
            continue
        found = canon_index_service.get_record_by_id(context.project_id, record_id)
        record = found.get("record") if found.get("status") == "found" else None
        if not record:
            continue
        years = _record_years(record.get("date_or_sequence"))
        if not years:
            continue
        outside = [year for year in years if year < start_year or year > end_year]
        if not outside:
            continue
        issues.append(
            {
                "code": "time_span_canon_conflict",
                "book_number": book_number,
                "field": "time_span",
                "record_id": record_id,
                "event_date_or_sequence": str(record.get("date_or_sequence") or ""),
                "message": (
                    f"Book {book_number} Time Span {book.get('time_span')!r} excludes "
                    f"selected Canon event {record.get('display_label') or record_id}."
                ),
            }
        )
    return issues


def _book_plan_path(context: ProjectContext) -> Path:
    return context.project_dir / BOOK_PLAN_FILENAME


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically with bounded retry for transient Windows locks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")

    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
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


def _execution_locks() -> dict[str, bool]:
    return {
        "approval_workflow_enabled": True,
        "book_pack_generated": False,
        "prompt_builder_called": False,
        "provider_called": False,
        "runtime_written": False,
        "draft_persisted": False,
        "generation_unlocked": False,
    }
