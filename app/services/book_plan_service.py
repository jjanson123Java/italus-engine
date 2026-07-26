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
from pathlib import Path
import time
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso


BOOK_PLAN_SERVICE_MARKER = "project-book-plan-approval-freshness-20260726"
BOOK_PLAN_SCHEMA_VERSION = "project_book_plan_v1"
BOOK_PLAN_FILENAME = "book_plan.json"

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
            "major_events": {"type": "array[string]", "required": False},
            "required_characters": {"type": "array[string]", "required": False},
            "required_locations": {"type": "array[string]", "required": False},
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
            "approval_basis": "current normalized Book Plan content_hash",
            "fresh_when": "approved_content_hash equals content_hash",
            "invalidation": "any stable content change makes approval outdated",
            "approval_required": "plan validation must be complete",
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
) -> dict[str, Any]:
    """Return a normalized plan without writing when the file is absent."""

    path = _book_plan_path(context)
    if path.exists():
        stored = project_loader.read_json(path)
        plan = _normalize_existing_document(context, manifest, stored)
        exists = True
    else:
        plan = _default_document(context, manifest)
        exists = False

    validation = _validate_plan(plan, int(manifest.get("book_count") or 0))
    plan["status"] = _status_for(validation, exists)
    plan["approval_status"] = _approval_status(plan, validation)
    plan["approval_fresh"] = (
        plan["approval_status"] == APPROVAL_APPROVED
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
        "approval_enabled": bool(validation["valid"]),
        "authoring_enabled": False,
        "book_runtime_context_enabled": False,
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

    normalized_books = _normalize_books(incoming_books, expected_book_count)
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
    }

    content_hash = _content_hash(candidate)
    if content_hash != str(existing.get("content_hash") or ""):
        candidate["revision"] += 1
    candidate["content_hash"] = content_hash

    validation = _validate_plan(candidate, expected_book_count)
    candidate["status"] = _status_for(validation, True)
    candidate["approval_status"] = _approval_status(
        candidate,
        validation,
    )
    candidate["approval_fresh"] = (
        candidate["approval_status"] == APPROVAL_APPROVED
    )

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



def approve_book_plan(project_id: str) -> dict[str, Any]:
    """Approve the current complete Book Plan content hash."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return approve_book_plan_for_context(
        context,
        manifest.to_dict(),
    )


def approve_book_plan_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Persist approval provenance without compiling runtime context."""

    path = _book_plan_path(context)
    if not path.exists():
        raise BookPlanContractError(
            "Book Plan must be saved before approval."
        )

    plan = _normalize_existing_document(
        context,
        manifest,
        project_loader.read_json(path),
    )
    validation = _validate_plan(
        plan,
        int(manifest.get("book_count") or 0),
    )
    if not validation["valid"]:
        raise BookPlanContractError(
            "Book Plan must be complete before approval."
        )

    now = utc_now_iso()
    plan["status"] = _status_for(validation, True)
    plan["approval_status"] = APPROVAL_APPROVED
    plan["approval_fresh"] = True
    plan["approved_revision"] = int(plan.get("revision") or 0)
    plan["approved_content_hash"] = str(
        plan.get("content_hash") or ""
    )
    plan["approved_at"] = now
    plan["updated_at"] = now

    _write_json_atomic(path, _stored_document(plan))

    return {
        "status": "approved",
        "service": BOOK_PLAN_SERVICE_MARKER,
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "project_relative_path": _relative(path, context.project_dir),
        "plan": {
            **plan,
            "validation": validation,
        },
        "execution_locks": _execution_locks(),
    }


def revoke_book_plan_approval(project_id: str) -> dict[str, Any]:
    """Revoke approval while preserving the current plan content."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return revoke_book_plan_approval_for_context(
        context,
        manifest.to_dict(),
    )


def revoke_book_plan_approval_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Clear approval provenance without changing stable plan content."""

    path = _book_plan_path(context)
    if not path.exists():
        raise BookPlanContractError(
            "Book Plan must be saved before approval can be revoked."
        )

    plan = _normalize_existing_document(
        context,
        manifest,
        project_loader.read_json(path),
    )
    validation = _validate_plan(
        plan,
        int(manifest.get("book_count") or 0),
    )
    now = utc_now_iso()
    plan["status"] = _status_for(validation, True)
    plan["approved_revision"] = 0
    plan["approved_content_hash"] = ""
    plan["approved_at"] = ""
    plan["approval_status"] = _approval_status(plan, validation)
    plan["approval_fresh"] = False
    plan["updated_at"] = now

    _write_json_atomic(path, _stored_document(plan))

    return {
        "status": "approval_revoked",
        "service": BOOK_PLAN_SERVICE_MARKER,
        "schema_version": BOOK_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "project_relative_path": _relative(path, context.project_dir),
        "plan": {
            **plan,
            "validation": validation,
        },
        "execution_locks": _execution_locks(),
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
    }


def _normalize_existing_document(
    context: ProjectContext,
    manifest: dict[str, Any],
    stored: Any,
) -> dict[str, Any]:
    if not isinstance(stored, dict):
        raise BookPlanContractError(
            "Stored Book Plan must contain a JSON object."
        )

    expected_book_count = int(manifest.get("book_count") or 0)
    normalized_books = _normalize_books(
        stored.get("books") or [],
        expected_book_count,
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
    }
    calculated = _content_hash(document)
    if not document["content_hash"]:
        document["content_hash"] = calculated
    return document


def _normalize_books(
    books: list[Any],
    expected_book_count: int,
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
        for field in BOOK_LIST_FIELDS:
            normalized[field] = _clean_string_list(raw.get(field))
        by_number[book_number] = normalized

    return [
        by_number.get(book_number, _empty_book(book_number))
        for book_number in range(1, expected_book_count + 1)
    ]


def _validate_plan(
    plan: dict[str, Any],
    expected_book_count: int,
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

        per_book.append(
            {
                "book_number": book_number,
                "complete": complete,
                "missing_fields": missing,
            }
        )

    valid = (
        expected_book_count > 0
        and len(books) == expected_book_count
        and complete_count == expected_book_count
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
