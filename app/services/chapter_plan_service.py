"""
Project-local Chapter Plan + Event Board planning state.

Patch 22 owns lightweight chapter planning at:

    data/projects/<project_id>/chapter_plan.json

It stores author planning intent only. It does not generate prose, write Approved
Continuity, mutate Author Canon, mutate Book Scope, mutate Book Plan, or call a
model/provider.

The default planning contract is deliberately small: selected Book Canon,
assigned events, and an optional Generation Kickoff. POV, objective,
restrictions, Story Controls, event placements, and advanced sequence are
optional.
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
from app.services import (
    book_plan_service,
    book_scope_service,
    canon_index_service,
    story_eligibility_service,
    story_control_service,
)


CHAPTER_PLAN_SERVICE_MARKER = "project-chapter-plan-event-board-20260816"
CHAPTER_PLAN_SCHEMA_VERSION = "project_chapter_plan_v1"
CHAPTER_PLAN_FILENAME = "chapter_plan.json"

CHAPTER_STATUS_DRAFT = "draft"
CHAPTER_STATUS_COMPLETE = "complete"
CHAPTER_STATUS_OUTDATED = "outdated"
CHAPTER_STATUS_RECONCILIATION_REQUIRED = "reconciliation_required"

PLACEMENT_POSITIONS = frozenset(
    {
        "opening",
        "early",
        "middle",
        "late",
        "ending",
        "after_break",
        "flexible",
    }
)

EVENT_RELATIONSHIP_TYPES = frozenset(
    {
        "follows",
        "precedes",
        "same_anchor",
        "parallel_reaction",
        "alternate_perspective",
        "caused_by",
        "consequence_of",
    }
)


class ChapterPlanError(RuntimeError):
    """Base error for Chapter Plan operations."""


class ChapterPlanContractError(ChapterPlanError):
    """Raised when Chapter Plan input violates the persisted contract."""


class ChapterPlanStateConflictError(ChapterPlanError):
    """Raised when current planning dependencies make a mutation unsafe."""


def chapter_plan_path(project_id: str) -> Path:
    manifest = project_loader.load_manifest(project_id)
    return chapter_plan_path_for_context(build_project_context(manifest))


def chapter_plan_path_for_context(context: ProjectContext) -> Path:
    return context.project_dir / CHAPTER_PLAN_FILENAME


def get_chapter_plan_contract() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": CHAPTER_PLAN_SERVICE_MARKER,
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "document": {
            "filename": CHAPTER_PLAN_FILENAME,
            "storage_scope": "project_local",
            "chapter_status_values": [
                CHAPTER_STATUS_DRAFT,
                CHAPTER_STATUS_COMPLETE,
                CHAPTER_STATUS_OUTDATED,
                CHAPTER_STATUS_RECONCILIATION_REQUIRED,
            ],
        },
        "required_by_default": [
            "book_number",
            "chapter_number",
        ],
        "author_fields": {
            "selected_canon_refs": "optional stable Book Canon references",
            "assigned_event_refs": "optional stable event references",
            "event_placements": "optional lightweight placement hints",
            "generation_kickoff": "optional small starting instruction",
            "pov": "optional stable character references",
            "chapter_objective": "optional author text",
            "restrictions": "optional author text list",
            "story_control_refs": "optional Story Control IDs; registry is introduced in Patch 24",
            "advanced_sequence": "optional advanced author-authored sequence",
        },
        "placement_positions": sorted(PLACEMENT_POSITIONS),
        "event_relationship_types": sorted(EVENT_RELATIONSHIP_TYPES),
        "dependencies": {
            "book_scope": "selected references must be in Canon for This Book",
            "book_plan": "revision/hash snapshotted; approval is a readiness gate",
            "approved_continuity": "revision reserved for later continuity integration",
        },
        "capabilities": {
            "persistent_chapter_plan": True,
            "event_board": True,
            "related_event_traversal": True,
            "story_controls": False,
            "prospective_book_scope_amendment": False,
            "chapter_knowledge_pack": False,
            "generation": False,
        },
        "execution_locks": _execution_locks(),
    }


def get_chapter_plan(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_chapter_plan_for_context(context, manifest.to_dict())


def get_chapter_plan_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    path = chapter_plan_path_for_context(context)
    exists = path.exists()
    if exists:
        stored = project_loader.read_json(path)
        document = _normalize_existing_document(context, manifest, stored)
    else:
        document = _default_document(context, manifest)

    decorated_books = []
    for book in document["books"]:
        decorated_chapters = [
            _decorate_chapter(
                context,
                manifest,
                book_number=int(book["book_number"]),
                chapter=chapter,
                exists=exists,
            )
            for chapter in book["chapters"]
        ]
        decorated_books.append(
            {
                "book_number": int(book["book_number"]),
                "chapters": decorated_chapters,
            }
        )

    return {
        "status": "ok",
        "service": CHAPTER_PLAN_SERVICE_MARKER,
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "exists": exists,
        "project_relative_path": _relative(path, context.project_dir),
        "document": {
            **document,
            "books": decorated_books,
        },
        "execution_locks": _execution_locks(),
    }


def get_chapter_plan_status(project_id: str) -> dict[str, Any]:
    result = get_chapter_plan(project_id)
    chapters = [
        chapter
        for book in result["document"]["books"]
        for chapter in book["chapters"]
    ]
    return {
        "status": "ok",
        "service": CHAPTER_PLAN_SERVICE_MARKER,
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "project_id": project_id,
        "exists": result["exists"],
        "project_relative_path": result["project_relative_path"],
        "planned_chapter_count": len(chapters),
        "complete_chapter_count": sum(
            1
            for chapter in chapters
            if chapter.get("lifecycle_state") == CHAPTER_STATUS_COMPLETE
        ),
        "outdated_chapter_count": sum(
            1
            for chapter in chapters
            if chapter.get("lifecycle_state") == CHAPTER_STATUS_OUTDATED
        ),
        "reconciliation_required_count": sum(
            1
            for chapter in chapters
            if chapter.get("lifecycle_state")
            == CHAPTER_STATUS_RECONCILIATION_REQUIRED
        ),
        "generation_enabled": False,
        "execution_locks": _execution_locks(),
    }


def get_chapter(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    result = get_chapter_plan(project_id)
    manifest = project_loader.load_manifest(project_id).to_dict()
    _validate_position(manifest, book_number, chapter_number)
    book = _book_by_number(result["document"]["books"], book_number)
    chapter = _chapter_by_number(book["chapters"], chapter_number)
    if chapter is None:
        chapter = _decorate_chapter(
            build_project_context(project_loader.load_manifest(project_id)),
            manifest,
            book_number=book_number,
            chapter=_empty_chapter(book_number, chapter_number),
            exists=result["exists"],
        )
    return {
        "status": "ok",
        "service": CHAPTER_PLAN_SERVICE_MARKER,
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "project_id": project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "chapter": chapter,
        "execution_locks": _execution_locks(),
    }


def save_chapter_draft(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return save_chapter_draft_for_context(
        context,
        manifest_obj.to_dict(),
        book_number=book_number,
        chapter_number=chapter_number,
        payload=payload,
    )


def save_chapter_draft_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ChapterPlanContractError("Chapter Plan payload must be an object.")

    _validate_position(manifest, book_number, chapter_number)
    dependency = _dependency_snapshot(context, manifest, book_number, chapter_number)
    if dependency["book_scope_reconciliation_required"]:
        raise ChapterPlanStateConflictError(
            "Canon for This Book requires reconciliation before Chapter Plan changes."
        )

    allowed_ids = set(dependency["scope_selection_ids"])
    selected_canon_refs = _normalize_record_refs(
        context,
        payload.get("selected_canon_refs", []),
        field_name="selected_canon_refs",
        allowed_ids=allowed_ids,
        required_group=None,
    )
    assigned_event_refs = _normalize_record_refs(
        context,
        payload.get("assigned_event_refs", []),
        field_name="assigned_event_refs",
        allowed_ids=allowed_ids,
        required_group="events",
    )
    pov = _normalize_record_refs(
        context,
        payload.get("pov", []),
        field_name="pov",
        allowed_ids=allowed_ids,
        required_group="characters",
    )

    event_placements = _normalize_event_placements(
        context,
        payload.get("event_placements", []),
        allowed_ids=allowed_ids,
        assigned_event_ids={
            item["record_id"] for item in assigned_event_refs
        },
    )
    generation_kickoff = _clean_text(payload.get("generation_kickoff"))
    chapter_objective = _clean_text(payload.get("chapter_objective"))
    restrictions = _clean_string_list(payload.get("restrictions", []), "restrictions")
    story_control_refs = _clean_string_list(
        payload.get("story_control_refs", []),
        "story_control_refs",
    )
    story_control_validation = story_control_service.validate_story_control_refs(
        context.project_id,
        book_number=book_number,
        chapter_number=chapter_number,
        control_ids=story_control_refs,
    )
    if not story_control_validation["valid"]:
        raise ChapterPlanStateConflictError(
            "Chapter Plan Story Controls are invalid: "
            + "; ".join(
                str(issue.get("message") or issue.get("code") or "")
                for issue in story_control_validation["issues"]
            )
        )
    advanced_sequence = _normalize_advanced_sequence(
        payload.get("advanced_sequence", [])
    )

    path = chapter_plan_path_for_context(context)
    if path.exists():
        document = _normalize_existing_document(
            context,
            manifest,
            project_loader.read_json(path),
        )
    else:
        document = _default_document(context, manifest)

    book = _book_by_number(document["books"], book_number)
    current = _chapter_by_number(book["chapters"], chapter_number)
    if current is None:
        current = _empty_chapter(book_number, chapter_number)
        book["chapters"].append(current)
        book["chapters"].sort(key=lambda item: int(item["chapter_number"]))

    candidate = {
        **deepcopy(current),
        "book_number": book_number,
        "chapter_number": chapter_number,
        "book_scope_revision": dependency["book_scope_revision"],
        "book_scope_hash": dependency["book_scope_hash"],
        "book_plan_revision": dependency["book_plan_revision"],
        "book_plan_hash": dependency["book_plan_hash"],
        "continuity_revision": dependency["continuity_revision"],
        "selected_canon_refs": selected_canon_refs,
        "assigned_event_refs": assigned_event_refs,
        "event_placements": event_placements,
        "generation_kickoff": generation_kickoff,
        "pov": pov,
        "chapter_objective": chapter_objective,
        "restrictions": restrictions,
        "story_control_refs": story_control_refs,
        "advanced_sequence": advanced_sequence,
    }
    candidate_hash = _content_hash(candidate)
    revision = int(current.get("revision") or 0)
    if candidate_hash != str(current.get("content_hash") or ""):
        revision += 1

    now = utc_now_iso()
    current.update(
        {
            **candidate,
            "status": CHAPTER_STATUS_COMPLETE
            if _has_planning_content(candidate)
            else CHAPTER_STATUS_DRAFT,
            "revision": revision,
            "content_hash": candidate_hash,
            "created_at": str(current.get("created_at") or now),
            "updated_at": now,
        }
    )
    document["updated_at"] = now
    if not document.get("created_at"):
        document["created_at"] = now

    _write_json_atomic(path, _stored_document(document))
    return {
        "status": "saved",
        "service": CHAPTER_PLAN_SERVICE_MARKER,
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "chapter_plan": get_chapter_plan_for_context(context, manifest),
        "execution_locks": _execution_locks(),
    }


def get_event_candidates(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    anchor_event_id: str = "",
    query: str = "",
) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    manifest = manifest_obj.to_dict()
    context = build_project_context(manifest_obj)
    _validate_position(manifest, book_number, chapter_number)

    scope = book_scope_service.get_book_scope_for_context(
        context,
        manifest,
    )
    scope_book = _book_by_number(scope["document"]["books"], book_number)
    selected_ids = {
        str(item.get("record_id") or "")
        for item in scope_book.get("selections") or []
        if str(item.get("record_id") or "")
    }

    plan_result = get_chapter_plan_for_context(context, manifest)
    book = _book_by_number(plan_result["document"]["books"], book_number)
    chapter = _chapter_by_number(book["chapters"], chapter_number)
    assigned_ids = {
        str(item.get("record_id") or "")
        for item in (chapter or {}).get("assigned_event_refs") or []
    }

    relation_map: dict[str, list[dict[str, Any]]] = {}
    related_ids: set[str] = set()
    anchor = str(anchor_event_id or "").strip()
    if anchor:
        anchor_record = canon_index_service.get_record_by_id(project_id, anchor)
        if anchor_record.get("status") != "found":
            raise ChapterPlanContractError(
                "anchor_event_id does not resolve in the current Canon Index."
            )
        anchor_row = dict(anchor_record["record"])
        if str(anchor_row.get("record_group_id") or "") != "events":
            raise ChapterPlanContractError("anchor_event_id must reference an event.")

        relation_result = canon_index_service.relationships_for_record(
            project_id,
            anchor,
            direction="both",
            relationship_types=EVENT_RELATIONSHIP_TYPES,
        )
        for edge in relation_result.get("relationships") or []:
            related_id = (
                str(edge.get("target_internal_id") or "")
                if edge.get("direction") == "outgoing"
                else str(edge.get("source_internal_id") or "")
            )
            if not related_id:
                continue
            related_ids.add(related_id)
            relation_map.setdefault(related_id, []).append(
                {
                    "relationship_type": str(edge.get("relationship_type") or ""),
                    "direction": str(edge.get("direction") or ""),
                }
            )

    rows = canon_index_service.list_records(
        project_id,
        record_types=["event"],
    )["results"]
    q = _normalize_search(query)
    candidates = []
    for row in rows:
        record_id = str(row.get("internal_id") or "")
        if anchor and record_id not in related_ids and record_id != anchor:
            continue
        if q and q not in _normalize_search(
            " ".join(
                [
                    str(row.get("display_label") or ""),
                    str(row.get("summary") or ""),
                    " ".join(row.get("aliases") or []),
                ]
            )
        ):
            continue
        selected = record_id in selected_ids
        decision = story_eligibility_service.evaluate_story_eligibility(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            candidate_ref={
                "record_id": record_id,
                "record_type": str(row.get("record_type") or ""),
                "label": str(row.get("display_label") or ""),
            },
            requested_use="event_placement",
            selected=selected,
        )
        candidates.append(
            {
                "record_id": record_id,
                "record_type": str(row.get("record_type") or ""),
                "record_group_id": str(row.get("record_group_id") or ""),
                "label": str(row.get("display_label") or ""),
                "summary": str(row.get("summary") or ""),
                "in_book_scope": selected,
                "assigned_to_chapter": record_id in assigned_ids,
                "eligibility": decision,
                "relationships_to_anchor": relation_map.get(record_id, []),
                "allowed_actions": (
                    ["assign_to_chapter", "place_event"]
                    if selected and bool(decision.get("available"))
                    else (
                        ["add_to_book_later"]
                        if bool(decision.get("available"))
                        else list(decision.get("allowed_actions") or [])
                    )
                ),
            }
        )

    candidates.sort(
        key=lambda item: (
            0 if item["assigned_to_chapter"] else 1,
            0 if item["in_book_scope"] else 1,
            item["label"].casefold(),
            item["record_id"],
        )
    )
    return {
        "status": "ok",
        "service": CHAPTER_PLAN_SERVICE_MARKER,
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "project_id": project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "anchor_event_id": anchor,
        "query": str(query or ""),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "execution_locks": _execution_locks(),
    }


def _default_document(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "books": [
            {
                "book_number": book_number,
                "chapters": [],
            }
            for book_number in range(1, _book_count(manifest) + 1)
        ],
        "created_at": "",
        "updated_at": "",
    }


def _empty_chapter(book_number: int, chapter_number: int) -> dict[str, Any]:
    return {
        "book_number": int(book_number),
        "chapter_number": int(chapter_number),
        "status": CHAPTER_STATUS_DRAFT,
        "revision": 0,
        "content_hash": "",
        "book_scope_revision": 0,
        "book_scope_hash": "",
        "book_plan_revision": 0,
        "book_plan_hash": "",
        "continuity_revision": "",
        "selected_canon_refs": [],
        "assigned_event_refs": [],
        "event_placements": [],
        "generation_kickoff": "",
        "pov": [],
        "chapter_objective": "",
        "restrictions": [],
        "story_control_refs": [],
        "advanced_sequence": [],
        "created_at": "",
        "updated_at": "",
    }


def _normalize_existing_document(
    context: ProjectContext,
    manifest: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ChapterPlanContractError("Chapter Plan root must be an object.")
    schema = str(raw.get("schema_version") or "")
    if schema != CHAPTER_PLAN_SCHEMA_VERSION:
        raise ChapterPlanContractError(
            f"Chapter Plan schema must be {CHAPTER_PLAN_SCHEMA_VERSION}."
        )
    if str(raw.get("project_id") or "") != context.project_id:
        raise ChapterPlanContractError(
            "Chapter Plan project_id does not match the active project."
        )

    raw_books = raw.get("books", [])
    if not isinstance(raw_books, list):
        raise ChapterPlanContractError("Chapter Plan books must be an array.")

    expected_books = _book_count(manifest)
    by_number: dict[int, dict[str, Any]] = {}
    for raw_book in raw_books:
        if not isinstance(raw_book, dict):
            raise ChapterPlanContractError("Chapter Plan books must contain objects.")
        book_number = int(raw_book.get("book_number") or 0)
        if book_number < 1 or book_number > expected_books:
            raise ChapterPlanContractError(
                f"Chapter Plan contains invalid book_number {book_number}."
            )
        if book_number in by_number:
            raise ChapterPlanContractError(
                f"Chapter Plan contains duplicate book_number {book_number}."
            )
        raw_chapters = raw_book.get("chapters", [])
        if not isinstance(raw_chapters, list):
            raise ChapterPlanContractError(
                f"Book {book_number} chapters must be an array."
            )
        chapters = []
        seen: set[int] = set()
        for raw_chapter in raw_chapters:
            if not isinstance(raw_chapter, dict):
                raise ChapterPlanContractError(
                    f"Book {book_number} chapters must contain objects."
                )
            chapter_number = int(raw_chapter.get("chapter_number") or 0)
            _validate_position(manifest, book_number, chapter_number)
            if chapter_number in seen:
                raise ChapterPlanContractError(
                    f"Book {book_number} contains duplicate chapter {chapter_number}."
                )
            seen.add(chapter_number)
            normalized = _empty_chapter(book_number, chapter_number)
            normalized.update(
                {
                    "status": str(
                        raw_chapter.get("status") or CHAPTER_STATUS_DRAFT
                    ),
                    "revision": int(raw_chapter.get("revision") or 0),
                    "content_hash": str(raw_chapter.get("content_hash") or ""),
                    "book_scope_revision": int(
                        raw_chapter.get("book_scope_revision") or 0
                    ),
                    "book_scope_hash": str(
                        raw_chapter.get("book_scope_hash") or ""
                    ),
                    "book_plan_revision": int(
                        raw_chapter.get("book_plan_revision") or 0
                    ),
                    "book_plan_hash": str(
                        raw_chapter.get("book_plan_hash") or ""
                    ),
                    "continuity_revision": str(
                        raw_chapter.get("continuity_revision") or ""
                    ),
                    "selected_canon_refs": _normalize_stored_refs(
                        raw_chapter.get("selected_canon_refs", [])
                    ),
                    "assigned_event_refs": _normalize_stored_refs(
                        raw_chapter.get("assigned_event_refs", [])
                    ),
                    "event_placements": deepcopy(
                        raw_chapter.get("event_placements") or []
                    ),
                    "generation_kickoff": _clean_text(
                        raw_chapter.get("generation_kickoff")
                    ),
                    "pov": _normalize_stored_refs(raw_chapter.get("pov", [])),
                    "chapter_objective": _clean_text(
                        raw_chapter.get("chapter_objective")
                    ),
                    "restrictions": _clean_string_list(
                        raw_chapter.get("restrictions", []),
                        "restrictions",
                    ),
                    "story_control_refs": _clean_string_list(
                        raw_chapter.get("story_control_refs", []),
                        "story_control_refs",
                    ),
                    "advanced_sequence": _normalize_advanced_sequence(
                        raw_chapter.get("advanced_sequence", [])
                    ),
                    "created_at": str(raw_chapter.get("created_at") or ""),
                    "updated_at": str(raw_chapter.get("updated_at") or ""),
                }
            )
            chapters.append(normalized)
        chapters.sort(key=lambda item: int(item["chapter_number"]))
        by_number[book_number] = {
            "book_number": book_number,
            "chapters": chapters,
        }

    books = [
        by_number.get(
            book_number,
            {"book_number": book_number, "chapters": []},
        )
        for book_number in range(1, expected_books + 1)
    ]
    return {
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "project_id": context.project_id,
        "books": books,
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def _decorate_chapter(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
    chapter: dict[str, Any],
    exists: bool,
) -> dict[str, Any]:
    dependency = _dependency_snapshot(
        context,
        manifest,
        book_number,
        int(chapter.get("chapter_number") or 1),
    )
    current_scope_ids = set(dependency["scope_selection_ids"])
    issues: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    hard_conflict = False

    for field_name in ("selected_canon_refs", "assigned_event_refs", "pov"):
        for ref in chapter.get(field_name) or []:
            record_id = str(ref.get("record_id") or "")
            indexed = canon_index_service.get_record_by_id(
                context.project_id,
                record_id,
            )
            if indexed.get("status") != "found":
                hard_conflict = True
                issues.append(
                    {
                        "code": "chapter_reference_missing",
                        "field": field_name,
                        "record_id": record_id,
                        "message": "A Chapter Plan stable reference no longer exists.",
                    }
                )
                continue
            if record_id not in current_scope_ids:
                hard_conflict = True
                issues.append(
                    {
                        "code": "chapter_reference_outside_book_scope",
                        "field": field_name,
                        "record_id": record_id,
                        "message": "A Chapter Plan reference is no longer in Canon for This Book.",
                    }
                )

    control_validation = story_control_service.validate_story_control_refs(
        context.project_id,
        book_number=book_number,
        chapter_number=int(chapter.get("chapter_number") or 1),
        control_ids=list(chapter.get("story_control_refs") or []),
    )
    if not control_validation["valid"]:
        hard_conflict = True
        issues.extend(deepcopy(control_validation["issues"]))

    calculated_hash = _content_hash(chapter)
    stored_hash = str(chapter.get("content_hash") or "")
    if stored_hash and calculated_hash != stored_hash:
        hard_conflict = True
        issues.append(
            {
                "code": "chapter_content_hash_mismatch",
                "message": "Stored Chapter Plan content hash does not match current content.",
            }
        )

    scope_changed = bool(
        int(chapter.get("book_scope_revision") or 0)
        != dependency["book_scope_revision"]
        or str(chapter.get("book_scope_hash") or "")
        != dependency["book_scope_hash"]
    )
    plan_changed = bool(
        int(chapter.get("book_plan_revision") or 0)
        != dependency["book_plan_revision"]
        or str(chapter.get("book_plan_hash") or "")
        != dependency["book_plan_hash"]
    )
    if scope_changed:
        changes.append(
            {
                "code": "book_scope_changed",
                "saved_revision": int(chapter.get("book_scope_revision") or 0),
                "current_revision": dependency["book_scope_revision"],
            }
        )
    if plan_changed:
        changes.append(
            {
                "code": "book_plan_changed",
                "saved_revision": int(chapter.get("book_plan_revision") or 0),
                "current_revision": dependency["book_plan_revision"],
            }
        )

    ready = bool(
        dependency["book_scope_approved"]
        and dependency["book_plan_approved"]
        and not hard_conflict
        and not scope_changed
        and not plan_changed
    )
    has_content = _has_planning_content(chapter)
    if hard_conflict:
        lifecycle = CHAPTER_STATUS_RECONCILIATION_REQUIRED
    elif (scope_changed or plan_changed) and has_content:
        lifecycle = CHAPTER_STATUS_OUTDATED
    elif has_content:
        lifecycle = CHAPTER_STATUS_COMPLETE
    else:
        lifecycle = CHAPTER_STATUS_DRAFT

    return {
        **deepcopy(chapter),
        "status": CHAPTER_STATUS_COMPLETE if has_content else CHAPTER_STATUS_DRAFT,
        "lifecycle_state": lifecycle,
        "validation": {
            "valid": not hard_conflict,
            "issues": issues,
        },
        "freshness": {
            "fresh": not scope_changed and not plan_changed and not hard_conflict,
            "changes": changes,
            "book_scope_approved": dependency["book_scope_approved"],
            "book_plan_approved": dependency["book_plan_approved"],
        },
        "generation_readiness": {
            "ready": ready,
            "generation_enabled": False,
            "reason": (
                "Planning dependencies are current; generation remains locked."
                if ready
                else "Chapter planning dependencies are not yet fully approved/current."
            ),
        },
    }


def _dependency_snapshot(
    context: ProjectContext,
    manifest: dict[str, Any],
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    scope_result = book_scope_service.get_book_scope_for_context(
        context,
        manifest,
    )
    scope_book = _book_by_number(scope_result["document"]["books"], book_number)
    effective_scope = book_scope_service.effective_book_scope_selections_for_context(
        context,
        manifest,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    scope_ids = list(effective_scope.get("selection_ids") or [])

    plan_result = book_plan_service.get_book_plan_for_context(context, manifest)
    plan = plan_result["plan"]

    return {
        "book_scope_revision": int(
            effective_scope.get("effective_revision")
            if effective_scope.get("effective_revision") is not None
            else scope_book.get("revision") or 0
        ),
        "book_scope_hash": str(
            effective_scope.get("effective_content_hash")
            or scope_book.get("content_hash")
            or ""
        ),
        "book_scope_approved": bool(
            effective_scope.get("effective_approval_fresh")
            if "effective_approval_fresh" in effective_scope
            else scope_book.get("approval_fresh")
        ),
        "book_scope_reconciliation_required": bool(
            scope_book.get("freshness", {}).get("reconciliation_required")
        ),
        "scope_selection_ids": scope_ids,
        "book_plan_revision": int(plan.get("revision") or 0),
        "book_plan_hash": str(plan.get("content_hash") or ""),
        "book_plan_approved": bool(plan.get("approval_fresh")),
        "continuity_revision": "",
    }


def _normalize_record_refs(
    context: ProjectContext,
    raw: Any,
    *,
    field_name: str,
    allowed_ids: set[str],
    required_group: str | None,
) -> list[dict[str, Any]]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ChapterPlanContractError(f"{field_name} must be an array.")

    refs = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            record_id = item.strip()
        elif isinstance(item, dict):
            record_id = str(item.get("record_id") or "").strip()
        else:
            raise ChapterPlanContractError(
                f"{field_name} must contain stable-reference objects."
            )
        if not record_id:
            raise ChapterPlanContractError(
                f"{field_name} contains a reference without record_id."
            )
        if record_id in seen:
            continue
        if record_id not in allowed_ids:
            raise ChapterPlanStateConflictError(
                f"{field_name} record {record_id} is not in Canon for This Book."
            )
        indexed = canon_index_service.get_record_by_id(
            context.project_id,
            record_id,
        )
        if indexed.get("status") != "found":
            raise ChapterPlanStateConflictError(
                f"{field_name} record {record_id} does not exist in the Canon Index."
            )
        row = dict(indexed["record"])
        if required_group and str(row.get("record_group_id") or "") != required_group:
            raise ChapterPlanContractError(
                f"{field_name} record {record_id} must belong to {required_group}."
            )
        refs.append(
            {
                "record_id": record_id,
                "record_type": str(row.get("record_type") or ""),
                "label": str(row.get("display_label") or ""),
                "source_record_hash": str(row.get("source_hash") or ""),
            }
        )
        seen.add(record_id)
    refs.sort(key=lambda item: item["record_id"])
    return refs


def _normalize_stored_refs(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ChapterPlanContractError("Stored Chapter Plan references must be arrays.")
    refs = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ChapterPlanContractError(
                "Stored Chapter Plan references must contain objects."
            )
        record_id = str(item.get("record_id") or "").strip()
        if not record_id:
            raise ChapterPlanContractError(
                "Stored Chapter Plan reference is missing record_id."
            )
        if record_id in seen:
            continue
        refs.append(
            {
                "record_id": record_id,
                "record_type": str(item.get("record_type") or "").strip(),
                "label": str(item.get("label") or "").strip(),
                "source_record_hash": str(
                    item.get("source_record_hash") or ""
                ).strip(),
            }
        )
        seen.add(record_id)
    refs.sort(key=lambda item: item["record_id"])
    return refs


def _normalize_event_placements(
    context: ProjectContext,
    raw: Any,
    *,
    allowed_ids: set[str],
    assigned_event_ids: set[str],
) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ChapterPlanContractError("event_placements must be an array.")

    placements = []
    for ordinal, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ChapterPlanContractError(
                "event_placements must contain objects."
            )
        event_ref = _single_ref(
            context,
            item.get("event_ref"),
            field_name="event_placements.event_ref",
            allowed_ids=allowed_ids,
            required_group="events",
        )
        event_id = event_ref["record_id"]
        if assigned_event_ids and event_id not in assigned_event_ids:
            raise ChapterPlanContractError(
                "Every placed event must also appear in assigned_event_refs."
            )

        position = str(item.get("position") or "flexible").strip().lower()
        if position not in PLACEMENT_POSITIONS:
            raise ChapterPlanContractError(
                f"Unsupported event placement position: {position}."
            )
        relationship = str(
            item.get("relationship_to_anchor") or ""
        ).strip().lower()
        if relationship and relationship not in EVENT_RELATIONSHIP_TYPES:
            raise ChapterPlanContractError(
                f"Unsupported event relationship: {relationship}."
            )

        anchor_ref = None
        if item.get("anchor_event_ref"):
            anchor_ref = _single_ref(
                context,
                item.get("anchor_event_ref"),
                field_name="event_placements.anchor_event_ref",
                allowed_ids=allowed_ids,
                required_group="events",
            )

        placements.append(
            {
                "event_ref": event_ref,
                "position": position,
                "relationship_to_anchor": relationship,
                "anchor_event_ref": anchor_ref,
                "ordinal": ordinal,
            }
        )
    return placements


def _single_ref(
    context: ProjectContext,
    raw: Any,
    *,
    field_name: str,
    allowed_ids: set[str],
    required_group: str | None,
) -> dict[str, Any]:
    refs = _normalize_record_refs(
        context,
        [raw] if raw is not None else [],
        field_name=field_name,
        allowed_ids=allowed_ids,
        required_group=required_group,
    )
    if len(refs) != 1:
        raise ChapterPlanContractError(f"{field_name} must contain one stable reference.")
    return refs[0]


def _normalize_advanced_sequence(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ChapterPlanContractError("advanced_sequence must be an array.")
    normalized = []
    for item in raw:
        if isinstance(item, str):
            value = item.strip()
            if value:
                normalized.append(value)
        elif isinstance(item, dict):
            normalized.append(deepcopy(item))
        else:
            raise ChapterPlanContractError(
                "advanced_sequence entries must be strings or objects."
            )
    return normalized


def _content_hash(chapter: dict[str, Any]) -> str:
    payload = {
        "book_number": int(chapter.get("book_number") or 0),
        "chapter_number": int(chapter.get("chapter_number") or 0),
        "selected_canon_refs": _stable_ref_ids(
            chapter.get("selected_canon_refs") or []
        ),
        "assigned_event_refs": _stable_ref_ids(
            chapter.get("assigned_event_refs") or []
        ),
        "event_placements": [
            {
                "event_id": str(
                    (item.get("event_ref") or {}).get("record_id") or ""
                ),
                "position": str(item.get("position") or ""),
                "relationship_to_anchor": str(
                    item.get("relationship_to_anchor") or ""
                ),
                "anchor_event_id": str(
                    (item.get("anchor_event_ref") or {}).get("record_id") or ""
                ),
                "ordinal": int(item.get("ordinal") or 0),
            }
            for item in chapter.get("event_placements") or []
        ],
        "generation_kickoff": _clean_text(
            chapter.get("generation_kickoff")
        ),
        "pov": _stable_ref_ids(chapter.get("pov") or []),
        "chapter_objective": _clean_text(chapter.get("chapter_objective")),
        "restrictions": list(chapter.get("restrictions") or []),
        "story_control_refs": list(chapter.get("story_control_refs") or []),
        "advanced_sequence": deepcopy(chapter.get("advanced_sequence") or []),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_ref_ids(items: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(item.get("record_id") or "")
            for item in items
            if str(item.get("record_id") or "")
        }
    )


def _has_planning_content(chapter: dict[str, Any]) -> bool:
    return bool(
        chapter.get("selected_canon_refs")
        or chapter.get("assigned_event_refs")
        or _clean_text(chapter.get("generation_kickoff"))
        or chapter.get("pov")
        or _clean_text(chapter.get("chapter_objective"))
        or chapter.get("restrictions")
        or chapter.get("story_control_refs")
        or chapter.get("advanced_sequence")
    )


def _stored_document(document: dict[str, Any]) -> dict[str, Any]:
    books = []
    for book in document.get("books") or []:
        chapters = []
        for chapter in book.get("chapters") or []:
            chapters.append(
                {
                    key: deepcopy(chapter.get(key))
                    for key in (
                        "book_number",
                        "chapter_number",
                        "status",
                        "revision",
                        "content_hash",
                        "book_scope_revision",
                        "book_scope_hash",
                        "book_plan_revision",
                        "book_plan_hash",
                        "continuity_revision",
                        "selected_canon_refs",
                        "assigned_event_refs",
                        "event_placements",
                        "generation_kickoff",
                        "pov",
                        "chapter_objective",
                        "restrictions",
                        "story_control_refs",
                        "advanced_sequence",
                        "created_at",
                        "updated_at",
                    )
                }
            )
        books.append(
            {
                "book_number": int(book.get("book_number") or 0),
                "chapters": chapters,
            }
        )
    return {
        "schema_version": CHAPTER_PLAN_SCHEMA_VERSION,
        "project_id": str(document.get("project_id") or ""),
        "books": books,
        "created_at": str(document.get("created_at") or ""),
        "updated_at": str(document.get("updated_at") or ""),
    }


def _book_by_number(
    books: list[dict[str, Any]],
    book_number: int,
) -> dict[str, Any]:
    for book in books:
        if int(book.get("book_number") or 0) == int(book_number):
            return book
    raise ChapterPlanContractError(f"Book {book_number} is missing from planning state.")


def _chapter_by_number(
    chapters: list[dict[str, Any]],
    chapter_number: int,
) -> dict[str, Any] | None:
    for chapter in chapters:
        if int(chapter.get("chapter_number") or 0) == int(chapter_number):
            return chapter
    return None


def _validate_position(
    manifest: dict[str, Any],
    book_number: int,
    chapter_number: int,
) -> None:
    book_count = _book_count(manifest)
    chapters_per_book = _chapters_per_book(manifest)
    try:
        book_number = int(book_number)
        chapter_number = int(chapter_number)
    except (TypeError, ValueError) as exc:
        raise ChapterPlanContractError(
            "book_number and chapter_number must be integers."
        ) from exc
    if book_number < 1 or book_number > book_count:
        raise ChapterPlanContractError(
            f"book_number must be between 1 and {book_count}."
        )
    if chapter_number < 1 or chapter_number > chapters_per_book:
        raise ChapterPlanContractError(
            f"chapter_number must be between 1 and {chapters_per_book}."
        )


def _book_count(manifest: dict[str, Any]) -> int:
    return max(1, int(manifest.get("book_count") or 1))


def _chapters_per_book(manifest: dict[str, Any]) -> int:
    return max(1, int(manifest.get("chapters_per_book") or 1))


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_string_list(raw: Any, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ChapterPlanContractError(f"{field_name} must be an array.")
    values = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    return values


def _normalize_search(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, path)


def _execution_locks() -> dict[str, bool]:
    return {
        "generation": True,
        "provider_execution": True,
        "approved_continuity_writes": True,
        "master_canon_mutation": True,
        "book_scope_mutation": True,
        "book_plan_mutation": True,
    }
