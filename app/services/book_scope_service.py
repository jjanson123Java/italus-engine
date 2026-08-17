"""
Project-local Book Scope / Canon-for-This-Book backend.

Patch 18 owns persisted author selection of established Canon records for each
book. It reads the Patch 16 Canon Index and Patch 17 Story Eligibility service,
but it does not mutate Author Canon, Approved Continuity, Book Plan, Chapter
Plan, runtime context, generation state, or provenance.

Direct selection changes after approval are intentionally blocked here.
Prospective amendment/audit semantics belong to the later Scope Amendment
patch.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import canon_index_service, story_eligibility_service


BOOK_SCOPE_SERVICE_MARKER = "project-book-scope-backend-20260816"
BOOK_SCOPE_SCHEMA_VERSION = "project_book_scope_v1"
BOOK_SCOPE_FILENAME = "book_scope.json"

STATUS_NOT_STARTED = "NOT_STARTED"
STATUS_DRAFT = "DRAFT"
STATUS_COMPLETE = "COMPLETE"
STATUS_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
STATUS_APPROVED = "APPROVED"
STATUS_OUTDATED = "OUTDATED"
STATUS_RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"

APPROVAL_NOT_READY = "not_ready"
APPROVAL_REQUIRED = "approval_required"
APPROVAL_APPROVED = "approved"
APPROVAL_OUTDATED = "outdated"
APPROVAL_RECONCILIATION_REQUIRED = "reconciliation_required"

SUPPORTED_SOURCE_CLASSES = frozenset(
    {
        "master_canon",
        "approved_prior_continuity",
    }
)
SUPPORTED_USAGE_MODES = frozenset(
    {
        "direct",
        "indirect",
        "foreshadow_only",
    }
)
CURRENTLY_SELECTABLE_SOURCE_CLASSES = frozenset({"master_canon"})


class BookScopeError(RuntimeError):
    """Base error for Book Scope operations."""


class BookScopeContractError(BookScopeError):
    """Raised when a Book Scope payload violates the persisted contract."""


class BookScopeStateConflictError(BookScopeError):
    """Raised when a requested mutation violates the current lifecycle."""


def book_scope_path(project_id: str) -> Path:
    manifest = project_loader.load_manifest(project_id)
    return book_scope_path_for_context(build_project_context(manifest))


def book_scope_path_for_context(context: ProjectContext) -> Path:
    return context.project_dir / BOOK_SCOPE_FILENAME


def get_book_scope_contract() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "document": {
            "filename": BOOK_SCOPE_FILENAME,
            "storage_scope": "project_local",
            "lifecycle_states": [
                STATUS_NOT_STARTED,
                STATUS_DRAFT,
                STATUS_COMPLETE,
                STATUS_APPROVAL_REQUIRED,
                STATUS_APPROVED,
                STATUS_OUTDATED,
                STATUS_RECONCILIATION_REQUIRED,
            ],
            "source_classes": sorted(SUPPORTED_SOURCE_CLASSES),
            "currently_selectable_source_classes": sorted(
                CURRENTLY_SELECTABLE_SOURCE_CLASSES
            ),
            "usage_modes": sorted(SUPPORTED_USAGE_MODES),
        },
        "selection": {
            "identity": "record_id",
            "record_type": "refreshed from Canon Index",
            "label": "human snapshot refreshed on draft save",
            "source_class_default": "master_canon",
            "usage_mode_default": "direct",
        },
        "freshness": {
            "source_canon_hash": "Author Canon SHA-256 from current Canon Index source set",
            "source_index_revision": "Canon Index logical content hash",
            "selected_record_source_hash": "per-record Canon source hash snapshot",
            "approval_requires_current_sources": True,
            "automatic_selection_discard": False,
        },
        "capabilities": {
            "catalog": True,
            "draft_save": True,
            "approval": True,
            "revoke_approval": True,
            "workspace_ui": False,
            "approved_prior_continuity_catalog": False,
            "prospective_amendment": True,
            "book_plan_consistency": False,
            "generation": False,
        },
        "execution_locks": _execution_locks(),
    }


def get_book_scope(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_book_scope_for_context(context, manifest.to_dict())


def get_book_scope_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    expected_book_count = _book_count(manifest)
    index_status = canon_index_service.ensure_current_index(context.project_id)
    path = book_scope_path_for_context(context)
    exists = path.exists()

    if exists:
        stored = project_loader.read_json(path)
        document = _normalize_existing_document(
            context,
            manifest,
            stored,
            index_status=index_status,
        )
    else:
        document = _default_document(
            context,
            manifest,
            index_status=index_status,
        )

    decorated_books = [
        _decorate_book(
            context,
            book,
            index_status=index_status,
            exists=exists,
        )
        for book in document["books"]
    ]

    return {
        "status": "ok",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "project_id": context.project_id,
        "exists": exists,
        "project_relative_path": _relative(path, context.project_dir),
        "book_count": expected_book_count,
        "document": {
            **document,
            "books": decorated_books,
        },
        "execution_locks": _execution_locks(),
    }


def get_book_scope_status(project_id: str) -> dict[str, Any]:
    result = get_book_scope(project_id)
    books = result["document"]["books"]
    return {
        "status": "ok",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "project_id": project_id,
        "exists": result["exists"],
        "project_relative_path": result["project_relative_path"],
        "book_count": result["book_count"],
        "books": [
            {
                "book_number": book["book_number"],
                "lifecycle_state": book["lifecycle_state"],
                "status": book["status"],
                "revision": book["revision"],
                "content_hash": book["content_hash"],
                "selection_count": len(book["selections"]),
                "valid": book["validation"]["valid"],
                "approval_status": book["approval_status"],
                "approval_fresh": book["approval_fresh"],
                "approved_revision": book["approved_revision"],
                "approved_content_hash": book["approved_content_hash"],
                "approved_at": book["approved_at"],
                "source_fresh": book["freshness"]["fresh"],
                "reconciliation_required": book["freshness"][
                    "reconciliation_required"
                ],
                "issue_count": len(book["validation"]["issues"]),
            }
            for book in books
        ],
        "execution_locks": _execution_locks(),
    }


def get_book_scope_catalog(
    project_id: str,
    *,
    book_number: int,
    include_future: bool = False,
    query: str = "",
    record_type: str | None = None,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    manifest_dict = manifest.to_dict()
    book_number = _validate_book_number(book_number, _book_count(manifest_dict))

    scope = get_book_scope_for_context(context, manifest_dict)
    scope_book = _book_by_number(scope["document"]["books"], book_number)
    selected_ids = {
        str(item.get("record_id") or "")
        for item in scope_book.get("selections") or []
    }

    listed = canon_index_service.list_records(
        project_id,
        record_types=[record_type] if record_type else None,
        limit=5000,
    )
    needle = _search_text(query)
    categories: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, int] = {}
    hidden_counts: dict[str, int] = {}

    for record in listed["results"]:
        if needle and not _record_matches(record, needle):
            continue

        record_id = str(record.get("internal_id") or "")
        selected = record_id in selected_ids
        decision = story_eligibility_service.evaluate_story_eligibility(
            project_id,
            book_number=book_number,
            candidate_ref={
                "record_id": record_id,
                "record_type": str(record.get("record_type") or ""),
                "label": str(record.get("display_label") or ""),
            },
            requested_use="book_selection",
            selected=selected,
        )
        decision_status = str(decision.get("status") or "")
        status_counts[decision_status] = status_counts.get(decision_status, 0) + 1

        visible = (
            selected
            or include_future
            or decision_status
            in {
                story_eligibility_service.STATUS_ACTIVE,
                story_eligibility_service.STATUS_AVAILABLE_TO_ADD,
            }
        )
        if not visible:
            hidden_counts[decision_status] = hidden_counts.get(decision_status, 0) + 1
            continue

        category_key = str(
            record.get("record_group_id")
            or record.get("record_type")
            or "other"
        )
        category = categories.setdefault(
            category_key,
            {
                "category_key": category_key,
                "record_type_counts": {},
                "items": [],
            },
        )
        record_type_value = str(record.get("record_type") or "")
        category["record_type_counts"][record_type_value] = (
            category["record_type_counts"].get(record_type_value, 0) + 1
        )
        category["items"].append(
            {
                "record_id": record_id,
                "record_type": record_type_value,
                "record_group_id": str(record.get("record_group_id") or ""),
                "label": str(record.get("display_label") or ""),
                "aliases": list(record.get("aliases") or []),
                "story_code": str(record.get("story_code") or ""),
                "narrative_type": str(record.get("narrative_type") or ""),
                "summary": str(record.get("summary") or ""),
                "selected": selected,
                "source_class": "master_canon",
                "eligibility": decision,
            }
        )

    ordered_categories = []
    for key in sorted(categories):
        category = categories[key]
        category["items"].sort(
            key=lambda item: (
                str(item["label"]).casefold(),
                str(item["record_id"]),
            )
        )
        category["total"] = len(category["items"])
        category["selected_count"] = sum(
            1 for item in category["items"] if item["selected"]
        )
        ordered_categories.append(category)

    index_status = canon_index_service.get_index_status(project_id)
    return {
        "status": "ok",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "project_id": project_id,
        "book_number": book_number,
        "query": query,
        "record_type": record_type or "",
        "include_future": bool(include_future),
        "selected_count": len(selected_ids),
        "status_counts": dict(sorted(status_counts.items())),
        "hidden_status_counts": dict(sorted(hidden_counts.items())),
        "categories": ordered_categories,
        "source_canon_hash": _source_canon_hash(index_status),
        "source_index_revision": _source_index_revision(index_status),
        "execution_locks": _execution_locks(),
    }


def save_book_scope_draft(
    project_id: str,
    *,
    book_number: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return save_book_scope_draft_for_context(
        context,
        manifest.to_dict(),
        book_number=book_number,
        payload=payload,
    )


def save_book_scope_draft_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BookScopeContractError("Book Scope payload must be an object.")

    expected_book_count = _book_count(manifest)
    book_number = _validate_book_number(book_number, expected_book_count)
    index_status = canon_index_service.ensure_current_index(context.project_id)

    incoming_selections = payload.get("selections", [])
    if not isinstance(incoming_selections, list):
        raise BookScopeContractError("selections must be an array.")
    constraints = payload.get("constraints", {})
    if constraints is None:
        constraints = {}
    if not isinstance(constraints, dict):
        raise BookScopeContractError("constraints must be an object.")

    normalized_selections = _normalize_submitted_selections(
        context,
        book_number=book_number,
        selections=incoming_selections,
    )

    path = book_scope_path_for_context(context)
    if path.exists():
        document = _normalize_existing_document(
            context,
            manifest,
            project_loader.read_json(path),
            index_status=index_status,
        )
    else:
        document = _default_document(
            context,
            manifest,
            index_status=index_status,
        )

    current = _book_by_number(document["books"], book_number)
    candidate_content = _content_hash_for_book(
        {
            "book_number": book_number,
            "selections": normalized_selections,
            "constraints": deepcopy(constraints),
        }
    )
    approved_hash = str(current.get("approved_content_hash") or "")
    if approved_hash and candidate_content != approved_hash:
        raise BookScopeStateConflictError(
            "Approved Book Scope selections cannot be changed directly. "
            "Prospective Book Scope amendment support is not enabled in Patch 18."
        )

    now = utc_now_iso()
    revision = int(current.get("revision") or 0)
    if candidate_content != str(current.get("content_hash") or ""):
        revision += 1

    current.update(
        {
            "status": STATUS_COMPLETE if normalized_selections else STATUS_DRAFT,
            "revision": revision,
            "content_hash": candidate_content,
            "source_canon_hash": _source_canon_hash(index_status),
            "source_index_revision": _source_index_revision(index_status),
            "selections": normalized_selections,
            "constraints": deepcopy(constraints),
            "updated_at": now,
        }
    )
    if not current.get("created_at"):
        current["created_at"] = now
    document["updated_at"] = now
    if not document.get("created_at"):
        document["created_at"] = now

    _write_json_atomic(path, _stored_document(document))
    return {
        "status": "saved",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "book_scope": get_book_scope_for_context(context, manifest),
        "execution_locks": _execution_locks(),
    }



def amend_book_scope(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    action: str,
    record_id: str,
    source_class: str = "master_canon",
    usage_mode: str = "direct",
) -> dict[str, Any]:
    """Apply one explicit prospective Book Canon amendment.

    The author action is audited and effective from the supplied chapter.
    Existing approved earlier chapters are not rewritten. The amended Scope
    becomes OUTDATED until explicitly re-approved.
    """

    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return amend_book_scope_for_context(
        context,
        manifest_obj.to_dict(),
        book_number=book_number,
        chapter_number=chapter_number,
        action=action,
        record_id=record_id,
        source_class=source_class,
        usage_mode=usage_mode,
    )


def amend_book_scope_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
    action: str,
    record_id: str,
    source_class: str = "master_canon",
    usage_mode: str = "direct",
) -> dict[str, Any]:
    expected_book_count = _book_count(manifest)
    book_number = _validate_book_number(book_number, expected_book_count)
    chapters_per_book = max(1, int(manifest.get("chapters_per_book") or 1))
    try:
        chapter_number = int(chapter_number)
    except (TypeError, ValueError) as exc:
        raise BookScopeContractError("chapter_number must be an integer.") from exc
    if chapter_number < 1 or chapter_number > chapters_per_book:
        raise BookScopeContractError(
            f"chapter_number must be between 1 and {chapters_per_book}."
        )

    action = str(action or "").strip().lower()
    if action not in {"add", "remove"}:
        raise BookScopeContractError("Book Scope amendment action must be add or remove.")
    record_id = str(record_id or "").strip()
    if not record_id:
        raise BookScopeContractError("Book Scope amendment requires record_id.")

    index_status = canon_index_service.ensure_current_index(context.project_id)
    path = book_scope_path_for_context(context)
    if not path.exists():
        raise BookScopeStateConflictError(
            "Prospective amendment requires an existing approved Book Scope."
        )

    document = _normalize_existing_document(
        context,
        manifest,
        project_loader.read_json(path),
        index_status=index_status,
    )
    current = _book_by_number(document["books"], book_number)
    decorated = _decorate_book(
        context,
        current,
        index_status=index_status,
        exists=True,
    )
    if not decorated.get("approval_fresh"):
        raise BookScopeStateConflictError(
            "Prospective amendment requires a current approved Book Scope. "
            "Resolve/reapprove the current Scope before amending it."
        )

    selections = [deepcopy(item) for item in current.get("selections") or []]
    by_id = {
        str(item.get("record_id") or ""): item
        for item in selections
        if str(item.get("record_id") or "")
    }

    if action == "add":
        if record_id in by_id:
            raise BookScopeStateConflictError(
                "The Canon record is already selected for this book."
            )
        indexed = canon_index_service.get_record_by_id(
            context.project_id,
            record_id,
        )
        if indexed.get("status") != "found":
            raise BookScopeContractError(
                "Prospective Add to Book record does not exist in the Canon Index."
            )
        indexed_record = dict(indexed["record"])
        decision = story_eligibility_service.evaluate_story_eligibility(
            context.project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            candidate_ref={
                "record_id": record_id,
                "record_type": str(indexed_record.get("record_type") or ""),
                "label": str(indexed_record.get("display_label") or ""),
            },
            requested_use="chapter_selection",
            selected=False,
        )
        if decision.get("status") not in {
            story_eligibility_service.STATUS_AVAILABLE_TO_ADD,
            story_eligibility_service.STATUS_ACTIVE,
        }:
            raise BookScopeStateConflictError(
                "Prospective Add to Book is blocked by current Story Eligibility: "
                f"{decision.get('status')}. {decision.get('author_message') or ''}".strip()
            )
        normalized = _normalize_submitted_selections(
            context,
            book_number=book_number,
            selections=[
                {
                    "record_id": record_id,
                    "source_class": source_class,
                    "usage_mode": usage_mode,
                }
            ],
        )
        record_snapshot = normalized[0]
        selections.append(record_snapshot)
        selections.sort(key=lambda item: str(item.get("record_id") or ""))
    else:
        if record_id not in by_id:
            raise BookScopeStateConflictError(
                "The Canon record is not currently selected for this book."
            )
        record_snapshot = deepcopy(by_id[record_id])
        decision = story_eligibility_service.evaluate_story_eligibility(
            context.project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            candidate_ref={
                "record_id": record_id,
                "record_type": str(record_snapshot.get("record_type") or ""),
                "label": str(record_snapshot.get("label") or ""),
            },
            requested_use="chapter_selection",
            selected=True,
        )
        selections = [
            item
            for item in selections
            if str(item.get("record_id") or "") != record_id
        ]

    prior_revision = int(current.get("revision") or 0)
    prior_hash = str(current.get("content_hash") or "")
    candidate_hash = _content_hash_for_book(
        {
            "book_number": book_number,
            "selections": selections,
            "constraints": deepcopy(current.get("constraints") or {}),
        }
    )
    now = utc_now_iso()
    amendment = {
        "amendment_id": f"book-canon-amend-{uuid4().hex[:16]}",
        "book_number": book_number,
        "effective_from": {"chapter_number": chapter_number},
        "action": action,
        "record": deepcopy(record_snapshot),
        "availability_snapshot": deepcopy(decision),
        "prior_revision": prior_revision,
        "prior_content_hash": prior_hash,
        "resulting_revision": prior_revision + 1,
        "resulting_content_hash": candidate_hash,
        "bounded_invalidation": {
            "from_chapter": chapter_number,
            "preserve_prior_chapters": True,
            "book_plan_auto_expand": False,
            "derived_contexts": [
                "book_runtime_context",
                "future_chapter_knowledge_packs",
            ],
        },
        "created_at": now,
    }

    amendments = list(current.get("amendments") or [])
    amendments.append(amendment)
    current.update(
        {
            "status": STATUS_COMPLETE if selections else STATUS_DRAFT,
            "revision": prior_revision + 1,
            "content_hash": candidate_hash,
            "source_canon_hash": _source_canon_hash(index_status),
            "source_index_revision": _source_index_revision(index_status),
            "selections": selections,
            "amendments": amendments,
            "updated_at": now,
        }
    )
    document["updated_at"] = now
    _write_json_atomic(path, _stored_document(document))

    return {
        "status": "amended",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "amendment": amendment,
        "book_scope": get_book_scope_for_context(context, manifest),
        "invalidation": deepcopy(amendment["bounded_invalidation"]),
        "execution_locks": _execution_locks(),
    }


def effective_book_scope_selections(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    """Return Book Scope selections effective at one chapter position."""

    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return effective_book_scope_selections_for_context(
        context,
        manifest_obj.to_dict(),
        book_number=book_number,
        chapter_number=chapter_number,
    )


def effective_book_scope_selections_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    book_number = _validate_book_number(book_number, _book_count(manifest))
    chapters_per_book = max(1, int(manifest.get("chapters_per_book") or 1))
    chapter_number = int(chapter_number)
    if chapter_number < 1 or chapter_number > chapters_per_book:
        raise BookScopeContractError(
            f"chapter_number must be between 1 and {chapters_per_book}."
        )

    result = get_book_scope_for_context(context, manifest)
    book = _book_by_number(result["document"]["books"], book_number)
    effective = {
        str(item.get("record_id") or ""): deepcopy(item)
        for item in book.get("selections") or []
        if str(item.get("record_id") or "")
    }

    # Current selections reflect all amendments. Rewind amendments that have
    # not yet become effective at the requested chapter.
    for amendment in reversed(list(book.get("amendments") or [])):
        if not isinstance(amendment, dict):
            continue
        effective_from = int(
            ((amendment.get("effective_from") or {}).get("chapter_number") or 1)
        )
        if effective_from <= chapter_number:
            continue
        record = amendment.get("record") or {}
        record_id = str(record.get("record_id") or "")
        if not record_id:
            continue
        if str(amendment.get("action") or "") == "add":
            effective.pop(record_id, None)
        elif str(amendment.get("action") or "") == "remove":
            effective[record_id] = deepcopy(record)

    selections = sorted(
        effective.values(),
        key=lambda item: str(item.get("record_id") or ""),
    )
    later_amendments = [
        amendment
        for amendment in book.get("amendments") or []
        if isinstance(amendment, dict)
        and int(((amendment.get("effective_from") or {}).get("chapter_number") or 1))
        > chapter_number
    ]
    effective_revision = max(
        0,
        int(book.get("revision") or 0) - len(later_amendments),
    )
    effective_hash = _content_hash_for_book(
        {
            "book_number": book_number,
            "selections": selections,
            "constraints": deepcopy(book.get("constraints") or {}),
        }
    )
    freshness = book.get("freshness") or {}
    approved_sources_current = bool(
        str(book.get("approved_source_canon_hash") or "")
        == str(freshness.get("source_canon_hash") or "")
        and str(book.get("approved_source_index_revision") or "")
        == str(freshness.get("source_index_revision") or "")
    )
    effective_approval_fresh = bool(
        str(book.get("approved_content_hash") or "")
        and str(book.get("approved_content_hash") or "") == effective_hash
        and approved_sources_current
    )
    return {
        "status": "ok",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "scope_revision": int(book.get("revision") or 0),
        "scope_content_hash": str(book.get("content_hash") or ""),
        "effective_revision": effective_revision,
        "effective_content_hash": effective_hash,
        "approval_fresh": bool(book.get("approval_fresh")),
        "effective_approval_fresh": effective_approval_fresh,
        "selections": selections,
        "selection_ids": [
            str(item.get("record_id") or "")
            for item in selections
        ],
        "execution_locks": _execution_locks(),
    }


def approve_book_scope(project_id: str, *, book_number: int) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    manifest_dict = manifest.to_dict()
    expected_book_count = _book_count(manifest_dict)
    book_number = _validate_book_number(book_number, expected_book_count)
    path = book_scope_path_for_context(context)
    if not path.exists():
        raise BookScopeStateConflictError(
            "Book Scope must be saved before approval."
        )

    current_result = get_book_scope_for_context(context, manifest_dict)
    current = _book_by_number(current_result["document"]["books"], book_number)
    if not current["validation"]["valid"]:
        raise BookScopeStateConflictError(
            "Book Scope must contain only current, structurally valid selections before approval."
        )
    if not current["freshness"]["fresh"]:
        raise BookScopeStateConflictError(
            "Book Scope sources changed after the draft was saved. "
            "Review and save the current selections before approval."
        )

    index_status = canon_index_service.get_index_status(project_id)
    document = _normalize_existing_document(
        context,
        manifest_dict,
        project_loader.read_json(path),
        index_status=index_status,
    )
    book = _book_by_number(document["books"], book_number)
    now = utc_now_iso()
    book["status"] = STATUS_COMPLETE
    book["approval_status"] = APPROVAL_APPROVED
    book["approved_revision"] = int(book.get("revision") or 0)
    book["approved_content_hash"] = str(book.get("content_hash") or "")
    book["approved_source_canon_hash"] = _source_canon_hash(index_status)
    book["approved_source_index_revision"] = _source_index_revision(index_status)
    book["approved_at"] = now
    book["updated_at"] = now
    document["updated_at"] = now
    _write_json_atomic(path, _stored_document(document))

    return {
        "status": "approved",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "project_id": project_id,
        "book_number": book_number,
        "book_scope": get_book_scope_for_context(context, manifest_dict),
        "execution_locks": _execution_locks(),
    }


def revoke_book_scope_approval(
    project_id: str,
    *,
    book_number: int,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    manifest_dict = manifest.to_dict()
    expected_book_count = _book_count(manifest_dict)
    book_number = _validate_book_number(book_number, expected_book_count)
    path = book_scope_path_for_context(context)
    if not path.exists():
        raise BookScopeStateConflictError(
            "Book Scope must be saved before approval can be revoked."
        )

    index_status = canon_index_service.get_index_status(project_id)
    document = _normalize_existing_document(
        context,
        manifest_dict,
        project_loader.read_json(path),
        index_status=index_status,
    )
    book = _book_by_number(document["books"], book_number)
    now = utc_now_iso()
    book["approval_status"] = (
        APPROVAL_REQUIRED if book.get("selections") else APPROVAL_NOT_READY
    )
    book["approved_revision"] = 0
    book["approved_content_hash"] = ""
    book["approved_source_canon_hash"] = ""
    book["approved_source_index_revision"] = ""
    book["approved_at"] = ""
    book["updated_at"] = now
    document["updated_at"] = now
    _write_json_atomic(path, _stored_document(document))

    return {
        "status": "revoked",
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "project_id": project_id,
        "book_number": book_number,
        "book_scope": get_book_scope_for_context(context, manifest_dict),
        "execution_locks": _execution_locks(),
    }


def _default_document(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    index_status: dict[str, Any],
) -> dict[str, Any]:
    count = _book_count(manifest)
    return {
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "project_id": context.project_id,
        "book_count": count,
        "created_at": "",
        "updated_at": "",
        "books": [
            _empty_book(number, index_status=index_status)
            for number in range(1, count + 1)
        ],
    }


def _empty_book(
    book_number: int,
    *,
    index_status: dict[str, Any],
) -> dict[str, Any]:
    return {
        "book_number": book_number,
        "status": STATUS_NOT_STARTED,
        "revision": 0,
        "content_hash": _content_hash_for_book(
            {
                "book_number": book_number,
                "selections": [],
                "constraints": {},
            }
        ),
        "approved_revision": 0,
        "approved_content_hash": "",
        "approved_source_canon_hash": "",
        "approved_source_index_revision": "",
        "approved_at": "",
        "approval_status": APPROVAL_NOT_READY,
        "source_canon_hash": _source_canon_hash(index_status),
        "source_index_revision": _source_index_revision(index_status),
        "selections": [],
        "constraints": {},
        "amendments": [],
        "created_at": "",
        "updated_at": "",
    }


def _normalize_existing_document(
    context: ProjectContext,
    manifest: dict[str, Any],
    stored: Any,
    *,
    index_status: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(stored, dict):
        raise BookScopeContractError(
            "Stored Book Scope must contain a JSON object."
        )
    if str(stored.get("schema_version") or "") != BOOK_SCOPE_SCHEMA_VERSION:
        raise BookScopeContractError(
            f"Stored Book Scope schema_version must be {BOOK_SCOPE_SCHEMA_VERSION}."
        )
    stored_project_id = str(stored.get("project_id") or "")
    if stored_project_id and stored_project_id != context.project_id:
        raise BookScopeContractError(
            "Stored Book Scope project_id does not match the active project."
        )

    count = _book_count(manifest)
    by_number: dict[int, dict[str, Any]] = {}
    raw_books = stored.get("books", [])
    if not isinstance(raw_books, list):
        raise BookScopeContractError("Stored Book Scope books must be an array.")
    for raw in raw_books:
        if not isinstance(raw, dict):
            raise BookScopeContractError(
                "Stored Book Scope book entries must be objects."
            )
        number = _validate_book_number(raw.get("book_number"), count)
        if number in by_number:
            raise BookScopeContractError(
                f"Stored Book Scope contains duplicate Book {number}."
            )
        by_number[number] = _normalize_stored_book(
            raw,
            book_number=number,
            index_status=index_status,
        )

    return {
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "project_id": context.project_id,
        "book_count": count,
        "created_at": str(stored.get("created_at") or ""),
        "updated_at": str(stored.get("updated_at") or ""),
        "books": [
            by_number.get(number)
            or _empty_book(number, index_status=index_status)
            for number in range(1, count + 1)
        ],
    }


def _normalize_stored_book(
    raw: dict[str, Any],
    *,
    book_number: int,
    index_status: dict[str, Any],
) -> dict[str, Any]:
    selections = raw.get("selections", [])
    if not isinstance(selections, list):
        raise BookScopeContractError(
            f"Book {book_number} selections must be an array."
        )
    normalized_selections = []
    seen: set[str] = set()
    for item in selections:
        if not isinstance(item, dict):
            raise BookScopeContractError(
                f"Book {book_number} selections must contain objects."
            )
        record_id = str(item.get("record_id") or "").strip()
        if not record_id:
            raise BookScopeContractError(
                f"Book {book_number} contains a selection without record_id."
            )
        if record_id in seen:
            raise BookScopeContractError(
                f"Book {book_number} contains duplicate selection {record_id}."
            )
        seen.add(record_id)
        normalized_selections.append(
            {
                "record_id": record_id,
                "record_type": str(item.get("record_type") or "").strip(),
                "label": str(item.get("label") or "").strip(),
                "source_class": str(
                    item.get("source_class") or "master_canon"
                ).strip(),
                "usage_mode": str(item.get("usage_mode") or "direct").strip(),
                "source_record_hash": str(
                    item.get("source_record_hash") or ""
                ).strip(),
            }
        )

    constraints = raw.get("constraints", {})
    if not isinstance(constraints, dict):
        raise BookScopeContractError(
            f"Book {book_number} constraints must be an object."
        )
    amendments = raw.get("amendments", [])
    if not isinstance(amendments, list):
        raise BookScopeContractError(
            f"Book {book_number} amendments must be an array."
        )

    calculated = _content_hash_for_book(
        {
            "book_number": book_number,
            "selections": normalized_selections,
            "constraints": constraints,
        }
    )
    stored_hash = str(raw.get("content_hash") or "")
    return {
        "book_number": book_number,
        "status": str(raw.get("status") or STATUS_DRAFT),
        "revision": int(raw.get("revision") or 0),
        "content_hash": stored_hash or calculated,
        "approved_revision": int(raw.get("approved_revision") or 0),
        "approved_content_hash": str(
            raw.get("approved_content_hash") or ""
        ),
        "approved_source_canon_hash": str(
            raw.get("approved_source_canon_hash") or ""
        ),
        "approved_source_index_revision": str(
            raw.get("approved_source_index_revision") or ""
        ),
        "approved_at": str(raw.get("approved_at") or ""),
        "approval_status": str(
            raw.get("approval_status") or APPROVAL_NOT_READY
        ),
        "source_canon_hash": str(
            raw.get("source_canon_hash")
            or _source_canon_hash(index_status)
        ),
        "source_index_revision": str(
            raw.get("source_index_revision")
            or _source_index_revision(index_status)
        ),
        "selections": normalized_selections,
        "constraints": deepcopy(constraints),
        "amendments": deepcopy(amendments),
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def _normalize_submitted_selections(
    context: ProjectContext,
    *,
    book_number: int,
    selections: list[Any],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, item in enumerate(selections):
        if not isinstance(item, dict):
            raise BookScopeContractError(
                f"selections[{index}] must be an object."
            )
        record_id = str(item.get("record_id") or "").strip()
        if not record_id:
            raise BookScopeContractError(
                f"selections[{index}].record_id is required."
            )
        if record_id in seen:
            raise BookScopeContractError(
                f"Duplicate Book Scope selection: {record_id}."
            )
        seen.add(record_id)

        source_class = str(
            item.get("source_class") or "master_canon"
        ).strip()
        if source_class not in SUPPORTED_SOURCE_CLASSES:
            raise BookScopeContractError(
                f"Unsupported source_class for {record_id}: {source_class}."
            )
        if source_class not in CURRENTLY_SELECTABLE_SOURCE_CLASSES:
            raise BookScopeContractError(
                "approved_prior_continuity is reserved by the v1 contract, "
                "but a continuity-derived Book Scope catalog is not yet enabled."
            )

        usage_mode = str(item.get("usage_mode") or "direct").strip()
        if usage_mode not in SUPPORTED_USAGE_MODES:
            raise BookScopeContractError(
                f"Unsupported usage_mode for {record_id}: {usage_mode}."
            )

        indexed = canon_index_service.get_record_by_id(
            context.project_id,
            record_id,
        )
        if indexed.get("status") != "found":
            raise BookScopeContractError(
                f"Book Scope selection does not resolve in Canon Index: {record_id}."
            )
        record = dict(indexed["record"])

        supplied_type = str(item.get("record_type") or "").strip()
        current_type = str(record.get("record_type") or "").strip()
        if supplied_type and supplied_type != current_type:
            raise BookScopeContractError(
                f"Book Scope record_type mismatch for {record_id}."
            )

        decision = story_eligibility_service.evaluate_story_eligibility(
            context.project_id,
            book_number=book_number,
            candidate_ref={
                "record_id": record_id,
                "record_type": current_type,
                "label": str(record.get("display_label") or ""),
            },
            requested_use="book_selection",
            selected=True,
        )
        if decision.get("status") != story_eligibility_service.STATUS_ACTIVE:
            raise BookScopeContractError(
                "Book Scope selection is not currently legal: "
                f"{record_id} -> {decision.get('status')} "
                f"({decision.get('author_message') or 'no reason supplied'})."
            )

        normalized.append(
            {
                "record_id": record_id,
                "record_type": current_type,
                "label": str(record.get("display_label") or ""),
                "source_class": source_class,
                "usage_mode": usage_mode,
                "source_record_hash": str(record.get("source_hash") or ""),
            }
        )

    normalized.sort(key=lambda item: item["record_id"])
    return normalized


def _decorate_book(
    context: ProjectContext,
    book: dict[str, Any],
    *,
    index_status: dict[str, Any],
    exists: bool,
) -> dict[str, Any]:
    reconciliation = _reconcile_book(
        context,
        book,
        index_status=index_status,
    )
    selections = list(book.get("selections") or [])
    calculated_hash = _content_hash_for_book(book)
    hash_matches = calculated_hash == str(book.get("content_hash") or "")
    issues = list(reconciliation["issues"])
    if not hash_matches:
        issues.append(
            {
                "code": "scope_content_hash_mismatch",
                "message": "Stored Book Scope content hash does not match its stable selection content.",
            }
        )

    valid = bool(selections) and not issues
    approved_hash = str(book.get("approved_content_hash") or "")
    content_hash = str(book.get("content_hash") or "")
    approved_sources_current = bool(
        approved_hash
        and str(book.get("approved_source_canon_hash") or "")
        == _source_canon_hash(index_status)
        and str(book.get("approved_source_index_revision") or "")
        == _source_index_revision(index_status)
    )

    if reconciliation["reconciliation_required"] or not hash_matches:
        approval_status = APPROVAL_RECONCILIATION_REQUIRED
    elif approved_hash:
        if (
            approved_hash != content_hash
            or not approved_sources_current
            or reconciliation["source_changed"]
        ):
            approval_status = APPROVAL_OUTDATED
        else:
            approval_status = APPROVAL_APPROVED
    elif valid:
        approval_status = APPROVAL_REQUIRED
    else:
        approval_status = APPROVAL_NOT_READY

    if reconciliation["reconciliation_required"] or not hash_matches:
        lifecycle = STATUS_RECONCILIATION_REQUIRED
    elif approval_status == APPROVAL_APPROVED:
        lifecycle = STATUS_APPROVED
    elif approval_status == APPROVAL_OUTDATED:
        lifecycle = STATUS_OUTDATED
    elif valid:
        lifecycle = STATUS_APPROVAL_REQUIRED
    elif exists and (int(book.get("revision") or 0) > 0 or selections):
        lifecycle = STATUS_DRAFT
    else:
        lifecycle = STATUS_NOT_STARTED

    return {
        **deepcopy(book),
        "status": (
            STATUS_COMPLETE
            if valid
            else (
                STATUS_DRAFT
                if exists and (int(book.get("revision") or 0) > 0 or selections)
                else STATUS_NOT_STARTED
            )
        ),
        "lifecycle_state": lifecycle,
        "approval_status": approval_status,
        "approval_fresh": approval_status == APPROVAL_APPROVED,
        "validation": {
            "valid": valid,
            "selection_count": len(selections),
            "issues": issues,
        },
        "freshness": reconciliation,
    }


def _reconcile_book(
    context: ProjectContext,
    book: dict[str, Any],
    *,
    index_status: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    source_canon_current = _source_canon_hash(index_status)
    source_index_current = _source_index_revision(index_status)
    source_changed = bool(
        str(book.get("source_canon_hash") or "") != source_canon_current
        or str(book.get("source_index_revision") or "") != source_index_current
    )
    hard_conflict = False

    for selection in book.get("selections") or []:
        record_id = str(selection.get("record_id") or "")
        indexed = canon_index_service.get_record_by_id(
            context.project_id,
            record_id,
        )
        if indexed.get("status") != "found":
            hard_conflict = True
            issues.append(
                {
                    "code": "selected_record_missing",
                    "record_id": record_id,
                    "message": "Selected Canon record no longer exists in the current Canon Index.",
                }
            )
            continue

        record = dict(indexed["record"])
        current_type = str(record.get("record_type") or "")
        if (
            str(selection.get("record_type") or "")
            and str(selection.get("record_type") or "") != current_type
        ):
            hard_conflict = True
            issues.append(
                {
                    "code": "selected_record_type_changed",
                    "record_id": record_id,
                    "message": "Selected stable ID resolves to a different record type.",
                }
            )

        current_label = str(record.get("display_label") or "")
        saved_label = str(selection.get("label") or "")
        if saved_label != current_label:
            changes.append(
                {
                    "code": "label_changed",
                    "record_id": record_id,
                    "saved_label": saved_label,
                    "current_label": current_label,
                }
            )

        current_source_hash = str(record.get("source_hash") or "")
        saved_source_hash = str(selection.get("source_record_hash") or "")
        if saved_source_hash and saved_source_hash != current_source_hash:
            changes.append(
                {
                    "code": "record_content_changed",
                    "record_id": record_id,
                    "saved_source_hash": saved_source_hash,
                    "current_source_hash": current_source_hash,
                }
            )

        decision = story_eligibility_service.evaluate_story_eligibility(
            context.project_id,
            book_number=int(book.get("book_number") or 0),
            candidate_ref={
                "record_id": record_id,
                "record_type": current_type,
                "label": current_label,
            },
            requested_use="book_selection",
            selected=True,
        )
        if decision.get("status") != story_eligibility_service.STATUS_ACTIVE:
            hard_conflict = True
            issues.append(
                {
                    "code": "eligibility_conflict",
                    "record_id": record_id,
                    "eligibility_status": str(decision.get("status") or ""),
                    "reason_codes": list(decision.get("reason_codes") or []),
                    "message": str(decision.get("author_message") or ""),
                }
            )

    if source_changed:
        changes.append(
            {
                "code": "scope_source_changed",
                "saved_source_canon_hash": str(
                    book.get("source_canon_hash") or ""
                ),
                "current_source_canon_hash": source_canon_current,
                "saved_source_index_revision": str(
                    book.get("source_index_revision") or ""
                ),
                "current_source_index_revision": source_index_current,
            }
        )

    fresh = not source_changed and not hard_conflict
    return {
        "fresh": fresh,
        "source_changed": source_changed,
        "reconciliation_required": hard_conflict,
        "source_canon_hash": source_canon_current,
        "source_index_revision": source_index_current,
        "changes": changes,
        "issues": issues,
    }


def _stored_document(document: dict[str, Any]) -> dict[str, Any]:
    stored_books = []
    for book in document.get("books") or []:
        stored_books.append(
            {
                key: deepcopy(book.get(key))
                for key in (
                    "book_number",
                    "status",
                    "revision",
                    "content_hash",
                    "approved_revision",
                    "approved_content_hash",
                    "approved_source_canon_hash",
                    "approved_source_index_revision",
                    "approved_at",
                    "approval_status",
                    "source_canon_hash",
                    "source_index_revision",
                    "selections",
                    "constraints",
                    "amendments",
                    "created_at",
                    "updated_at",
                )
            }
        )
    return {
        "schema_version": BOOK_SCOPE_SCHEMA_VERSION,
        "service": BOOK_SCOPE_SERVICE_MARKER,
        "project_id": str(document.get("project_id") or ""),
        "book_count": int(document.get("book_count") or 0),
        "created_at": str(document.get("created_at") or ""),
        "updated_at": str(document.get("updated_at") or ""),
        "books": stored_books,
    }


def _content_hash_for_book(book: dict[str, Any]) -> str:
    stable_selections = []
    for item in book.get("selections") or []:
        stable_selections.append(
            {
                "record_id": str(item.get("record_id") or ""),
                "record_type": str(item.get("record_type") or ""),
                "source_class": str(
                    item.get("source_class") or "master_canon"
                ),
                "usage_mode": str(item.get("usage_mode") or "direct"),
            }
        )
    stable_selections.sort(key=lambda item: item["record_id"])
    payload = {
        "book_number": int(book.get("book_number") or 0),
        "selections": stable_selections,
        "constraints": deepcopy(book.get("constraints") or {}),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _book_count(manifest: dict[str, Any]) -> int:
    count = int(manifest.get("book_count") or 0)
    if count < 1:
        raise BookScopeContractError(
            "Project manifest book_count must be at least 1."
        )
    return count


def _validate_book_number(value: Any, book_count: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise BookScopeContractError("book_number must be an integer.") from exc
    if number < 1 or number > book_count:
        raise BookScopeContractError(
            f"book_number must be between 1 and {book_count}."
        )
    return number


def _book_by_number(books: list[dict[str, Any]], book_number: int) -> dict[str, Any]:
    for book in books:
        if int(book.get("book_number") or 0) == book_number:
            return book
    raise BookScopeContractError(f"Book Scope is missing Book {book_number}.")


def _source_canon_hash(index_status: dict[str, Any]) -> str:
    return str(
        (index_status.get("source_hashes") or {}).get("author_canon_sha256")
        or (index_status.get("indexed_source_hashes") or {}).get(
            "author_canon_sha256"
        )
        or ""
    )


def _source_index_revision(index_status: dict[str, Any]) -> str:
    return str(index_status.get("index_content_hash") or "")


def _search_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _record_matches(record: dict[str, Any], needle: str) -> bool:
    haystack = " ".join(
        [
            str(record.get("display_label") or ""),
            str(record.get("story_code") or ""),
            str(record.get("summary") or ""),
            " ".join(str(value) for value in record.get("aliases") or []),
        ]
    )
    return needle in _search_text(haystack)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
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
        "book_scope_backend_enabled": True,
        "book_scope_workspace_ui_enabled": False,
        "scope_amendment_enabled": True,
        "book_plan_consistency_enabled": False,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "planner_model_enabled": False,
    }
