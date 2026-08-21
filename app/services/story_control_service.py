"""
Project-local Story Control Registry.

Patch 24 stores explicit author controls independently from Master Canon at:

    data/projects/<project_id>/story_controls.json

It provides deterministic structural/protection validation for the currently
available planning rules. It does not write Master Canon, Approved Continuity,
generated prose, provider state, or provenance.

Free-text semantic interpretation remains deliberately bounded until the later
Planner Intent Model patch. This service catches only explicit structured
protection conflicts and a narrow set of obvious certainty-strength phrases;
it never claims complete natural-language interpretation.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import (
    book_scope_service,
    canon_index_service,
    story_eligibility_service,
)


STORY_CONTROL_SERVICE_MARKER = "project-story-control-registry-ui-20260816"
STORY_CONTROL_SCHEMA_VERSION = "project_story_controls_v1"
STORY_CONTROL_FILENAME = "story_controls.json"

CONTROL_TYPES = frozenset(
    {
        "mystery_reveal",
        "knowledge_change",
        "relationship_change",
        "availability_change",
        "escalation_change",
    }
)

CERTAINTY_VALUES = (
    "hint",
    "suspicion",
    "supported_evidence",
    "corroborated_fact",
    "objective_truth",
)
CERTAINTY_RANK = {
    value: index
    for index, value in enumerate(CERTAINTY_VALUES)
}

PRESENTATION_VALUES = frozenset(
    {
        "foreshadowing",
        "memory_fragment",
        "physical_artifact",
        "technical_record",
        "testimony",
        "visual_clue",
        "dialogue",
        "other",
    }
)

NARRATIVE_WEIGHT_VALUES = frozenset(
    {
        "brief_clue",
        "short_reveal_beat",
        "major_scene_beat",
    }
)

EFFECTIVE_POINT_VALUES = frozenset(
    {
        "current_unit",
        "end_of_chapter",
        "from_this_point_forward",
    }
)

PERSISTENCE_VALUES = frozenset(
    {
        "scene_local",
        "chapter_local",
        "persistent_state_change",
    }
)

LIFECYCLE_VALUES = (
    "PLANNED",
    "GENERATED",
    "VALIDATED",
    "APPROVED",
)

_OBVIOUS_STRENGTH_PATTERNS = (
    (
        "objective_truth",
        (
            r"\bincontrovertible proof\b",
            r"\bdefinitive proof\b",
            r"\bobjective truth\b",
            r"\bproves? conclusively\b",
            r"\bconfirmed as fact\b",
            r"\bwithout any doubt\b",
        ),
    ),
    (
        "corroborated_fact",
        (
            r"\bcorroborated\b",
            r"\bindependent confirmation\b",
            r"\bmultiple sources confirm\b",
        ),
    ),
)


class StoryControlError(RuntimeError):
    """Base error for Story Control operations."""


class StoryControlContractError(StoryControlError):
    """Raised when a Story Control payload violates the persisted contract."""


class StoryControlStateConflictError(StoryControlError):
    """Raised when a control cannot safely change in its current lifecycle."""


def story_controls_path(project_id: str) -> Path:
    manifest = project_loader.load_manifest(project_id)
    return story_controls_path_for_context(build_project_context(manifest))


def story_controls_path_for_context(context: ProjectContext) -> Path:
    return context.project_dir / STORY_CONTROL_FILENAME


def get_story_control_contract() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": STORY_CONTROL_SERVICE_MARKER,
        "schema_version": STORY_CONTROL_SCHEMA_VERSION,
        "document": {
            "filename": STORY_CONTROL_FILENAME,
            "storage_scope": "project_local",
        },
        "control_types": sorted(CONTROL_TYPES),
        "certainty_values": list(CERTAINTY_VALUES),
        "presentation_values": sorted(PRESENTATION_VALUES),
        "narrative_weight_values": sorted(NARRATIVE_WEIGHT_VALUES),
        "effective_point_values": sorted(EFFECTIVE_POINT_VALUES),
        "persistence_values": sorted(PERSISTENCE_VALUES),
        "lifecycle_values": list(LIFECYCLE_VALUES),
        "semantic_validation": {
            "mode": "structured_protection_plus_obvious_strength_guard",
            "complete_free_text_interpretation": False,
            "planner_intent_model_required_for_full_semantics": True,
        },
        "capabilities": {
            "registry": True,
            "chapter_planner_ui": True,
            "protected_story_rule_check": True,
            "certainty_strength_guard": True,
            "master_canon_mutation": False,
            "approved_continuity_write": False,
            "generation": False,
        },
        "execution_locks": _execution_locks(),
    }


def get_story_controls(
    project_id: str,
    *,
    book_number: int | None = None,
    chapter_number: int | None = None,
) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return get_story_controls_for_context(
        context,
        manifest_obj.to_dict(),
        book_number=book_number,
        chapter_number=chapter_number,
    )


def get_story_controls_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int | None = None,
    chapter_number: int | None = None,
) -> dict[str, Any]:
    path = story_controls_path_for_context(context)
    exists = path.exists()
    if exists:
        document = _normalize_document(
            context,
            manifest,
            project_loader.read_json(path),
        )
    else:
        document = _default_document(context)

    controls = []
    for control in document["controls"]:
        if book_number is not None and int(control["book_number"]) != int(book_number):
            continue
        if chapter_number is not None and int(control["chapter_number"]) != int(chapter_number):
            continue
        controls.append(_decorate_control(context, manifest, control))

    return {
        "status": "ok",
        "service": STORY_CONTROL_SERVICE_MARKER,
        "schema_version": STORY_CONTROL_SCHEMA_VERSION,
        "project_id": context.project_id,
        "exists": exists,
        "project_relative_path": _relative(path, context.project_dir),
        "revision": int(document.get("revision") or 0),
        "content_hash": str(document.get("content_hash") or ""),
        "control_count": len(controls),
        "controls": controls,
        "execution_locks": _execution_locks(),
    }


def get_story_control_status(project_id: str) -> dict[str, Any]:
    result = get_story_controls(project_id)
    controls = result["controls"]
    return {
        "status": "ok",
        "service": STORY_CONTROL_SERVICE_MARKER,
        "schema_version": STORY_CONTROL_SCHEMA_VERSION,
        "project_id": project_id,
        "exists": result["exists"],
        "project_relative_path": result["project_relative_path"],
        "revision": result["revision"],
        "content_hash": result["content_hash"],
        "control_count": len(controls),
        "planned_count": sum(
            1 for control in controls if control.get("status") == "PLANNED"
        ),
        "invalid_count": sum(
            1
            for control in controls
            if not bool((control.get("validation") or {}).get("valid"))
        ),
        "approved_continuity_write_enabled": False,
        "generation_enabled": False,
        "execution_locks": _execution_locks(),
    }


def save_story_control(
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return save_story_control_for_context(
        context,
        manifest_obj.to_dict(),
        payload,
    )


def save_story_control_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise StoryControlContractError("Story Control payload must be an object.")

    book_number = _positive_position(
        payload.get("book_number"),
        "book_number",
        maximum=max(1, int(manifest.get("book_count") or 1)),
    )
    chapter_number = _positive_position(
        payload.get("chapter_number"),
        "chapter_number",
        maximum=max(1, int(manifest.get("chapters_per_book") or 1)),
    )

    control_id = str(payload.get("control_id") or "").strip()
    path = story_controls_path_for_context(context)
    if path.exists():
        document = _normalize_document(
            context,
            manifest,
            project_loader.read_json(path),
        )
    else:
        document = _default_document(context)

    existing = None
    if control_id:
        existing = next(
            (
                item
                for item in document["controls"]
                if str(item.get("control_id") or "") == control_id
            ),
            None,
        )
        if existing is None:
            raise StoryControlContractError(
                "control_id does not exist in the current Story Control Registry."
            )
        if str(existing.get("status") or "PLANNED") != "PLANNED":
            raise StoryControlStateConflictError(
                "Only PLANNED Story Controls may be edited before generation migration."
            )
    else:
        control_id = f"story-control-{uuid4().hex[:16]}"

    control_type = _enum(
        payload.get("control_type"),
        CONTROL_TYPES,
        "control_type",
    )
    certainty = _enum(
        payload.get("certainty") or "supported_evidence",
        set(CERTAINTY_VALUES),
        "certainty",
    )
    presentation = _enum(
        payload.get("presentation") or "other",
        PRESENTATION_VALUES,
        "presentation",
    )
    narrative_weight = _enum(
        payload.get("narrative_weight") or "brief_clue",
        NARRATIVE_WEIGHT_VALUES,
        "narrative_weight",
    )
    effective_point = _enum(
        payload.get("effective_point") or "current_unit",
        EFFECTIVE_POINT_VALUES,
        "effective_point",
    )
    persistence = _enum(
        payload.get("persistence") or "chapter_local",
        PERSISTENCE_VALUES,
        "persistence",
    )

    subject_ref = _normalize_subject_ref(
        context,
        manifest,
        book_number=book_number,
        chapter_number=chapter_number,
        raw=payload.get("subject_ref"),
    )

    control = {
        "control_id": control_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "status": "PLANNED",
        "control_type": control_type,
        "subject_ref": subject_ref,
        "instruction": _text(payload.get("instruction")),
        "certainty": certainty,
        "presentation": presentation,
        "narrative_weight": narrative_weight,
        "who_learns": _string_list(payload.get("who_learns", []), "who_learns"),
        "effective_point": effective_point,
        "knowledge_ceiling": _text(payload.get("knowledge_ceiling")) or "inherit",
        "allowed_interpretations": _string_list(
            payload.get("allowed_interpretations", []),
            "allowed_interpretations",
        ),
        "forbidden_assertions": _string_list(
            payload.get("forbidden_assertions", []),
            "forbidden_assertions",
        ),
        "persistence": persistence,
        "notes": _text(payload.get("notes")),
        "created_at": str((existing or {}).get("created_at") or utc_now_iso()),
        "updated_at": utc_now_iso(),
    }
    decorated = _decorate_control(context, manifest, control)
    control["validation_snapshot"] = deepcopy(decorated["validation"])
    control["protection_snapshot"] = deepcopy(decorated["protection"])
    control["semantic_guard_snapshot"] = deepcopy(decorated["semantic_guard"])

    if existing is None:
        document["controls"].append(control)
    else:
        index = document["controls"].index(existing)
        document["controls"][index] = control

    document["controls"].sort(
        key=lambda item: (
            int(item.get("book_number") or 0),
            int(item.get("chapter_number") or 0),
            str(item.get("control_id") or ""),
        )
    )
    document["revision"] = int(document.get("revision") or 0) + 1
    document["content_hash"] = _content_hash(document["controls"])
    now = utc_now_iso()
    document["updated_at"] = now
    if not document.get("created_at"):
        document["created_at"] = now
    _write_json_atomic(path, _stored_document(document))

    result = get_story_controls_for_context(
        context,
        manifest,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    saved = next(
        item
        for item in result["controls"]
        if item["control_id"] == control_id
    )
    return {
        "status": "saved",
        "service": STORY_CONTROL_SERVICE_MARKER,
        "schema_version": STORY_CONTROL_SCHEMA_VERSION,
        "project_id": context.project_id,
        "control": saved,
        "registry_revision": result["revision"],
        "registry_content_hash": result["content_hash"],
        "execution_locks": _execution_locks(),
    }


def delete_story_control(
    project_id: str,
    control_id: str,
) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return delete_story_control_for_context(
        context,
        manifest_obj.to_dict(),
        control_id=control_id,
    )


def delete_story_control_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    control_id: str,
) -> dict[str, Any]:
    normalized_id = str(control_id or "").strip()
    if not normalized_id:
        raise StoryControlContractError("control_id is required.")

    path = story_controls_path_for_context(context)
    if not path.exists():
        raise StoryControlContractError(
            "Story Control Registry does not exist for this project."
        )

    document = _normalize_document(
        context,
        manifest,
        project_loader.read_json(path),
    )
    existing = next(
        (
            item
            for item in document["controls"]
            if str(item.get("control_id") or "") == normalized_id
        ),
        None,
    )
    if existing is None:
        raise StoryControlContractError(
            "control_id does not exist in the current Story Control Registry."
        )
    if str(existing.get("status") or "PLANNED") != "PLANNED":
        raise StoryControlStateConflictError(
            "Only PLANNED Story Controls may be deleted before generation migration."
        )

    references = _saved_chapter_plan_references(context, normalized_id)
    if references:
        locations = ", ".join(
            f"Book {item['book_number']} Chapter {item['chapter_number']}"
            for item in references
        )
        raise StoryControlStateConflictError(
            "Story Control is still referenced by a saved Chapter Plan. "
            f"Detach it and save the Chapter Plan before deleting it: {locations}."
        )

    document["controls"] = [
        item
        for item in document["controls"]
        if str(item.get("control_id") or "") != normalized_id
    ]
    document["revision"] = int(document.get("revision") or 0) + 1
    document["content_hash"] = _content_hash(document["controls"])
    document["updated_at"] = utc_now_iso()
    _write_json_atomic(path, _stored_document(document))

    return {
        "status": "deleted",
        "service": STORY_CONTROL_SERVICE_MARKER,
        "schema_version": STORY_CONTROL_SCHEMA_VERSION,
        "project_id": context.project_id,
        "control_id": normalized_id,
        "registry_revision": int(document["revision"]),
        "registry_content_hash": str(document["content_hash"]),
        "execution_locks": _execution_locks(),
    }


def _saved_chapter_plan_references(
    context: ProjectContext,
    control_id: str,
) -> list[dict[str, int]]:
    path = context.project_dir / "chapter_plan.json"
    if not path.exists():
        return []

    stored = project_loader.read_json(path)
    references: list[dict[str, int]] = []
    for book in stored.get("books") or []:
        if not isinstance(book, dict):
            continue
        book_number = int(book.get("book_number") or 0)
        for chapter in book.get("chapters") or []:
            if not isinstance(chapter, dict):
                continue
            refs = {
                str(value or "").strip()
                for value in chapter.get("story_control_refs") or []
                if str(value or "").strip()
            }
            if control_id in refs:
                references.append(
                    {
                        "book_number": book_number,
                        "chapter_number": int(chapter.get("chapter_number") or 0),
                    }
                )
    return references


def validate_story_control_refs(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    control_ids: list[str],
) -> dict[str, Any]:
    result = get_story_controls(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    by_id = {
        str(item.get("control_id") or ""): item
        for item in result["controls"]
    }
    issues = []
    resolved = []
    for control_id in control_ids:
        value = str(control_id or "").strip()
        control = by_id.get(value)
        if control is None:
            issues.append(
                {
                    "code": "story_control_missing",
                    "control_id": value,
                    "message": "Story Control does not exist for this chapter.",
                }
            )
            continue
        if not bool((control.get("validation") or {}).get("valid")):
            issues.append(
                {
                    "code": "story_control_invalid",
                    "control_id": value,
                    "message": "Story Control has unresolved protection/contract issues.",
                }
            )
            continue
        resolved.append(control)
    return {
        "valid": not issues,
        "issues": issues,
        "controls": resolved,
        "registry_revision": result["revision"],
        "registry_content_hash": result["content_hash"],
    }


def _default_document(context: ProjectContext) -> dict[str, Any]:
    return {
        "schema_version": STORY_CONTROL_SCHEMA_VERSION,
        "project_id": context.project_id,
        "revision": 0,
        "content_hash": _content_hash([]),
        "controls": [],
        "created_at": "",
        "updated_at": "",
    }


def _normalize_document(
    context: ProjectContext,
    manifest: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise StoryControlContractError("Story Control Registry root must be an object.")
    if str(raw.get("schema_version") or "") != STORY_CONTROL_SCHEMA_VERSION:
        raise StoryControlContractError(
            f"Story Control Registry schema must be {STORY_CONTROL_SCHEMA_VERSION}."
        )
    if str(raw.get("project_id") or "") != context.project_id:
        raise StoryControlContractError(
            "Story Control Registry project_id does not match the active project."
        )
    controls_raw = raw.get("controls", [])
    if not isinstance(controls_raw, list):
        raise StoryControlContractError("Story Control Registry controls must be an array.")

    controls = []
    seen: set[str] = set()
    for item in controls_raw:
        if not isinstance(item, dict):
            raise StoryControlContractError("Story Controls must be objects.")
        control_id = str(item.get("control_id") or "").strip()
        if not control_id or control_id in seen:
            raise StoryControlContractError(
                "Story Control IDs must be present and unique."
            )
        seen.add(control_id)
        book_number = _positive_position(
            item.get("book_number"),
            "book_number",
            maximum=max(1, int(manifest.get("book_count") or 1)),
        )
        chapter_number = _positive_position(
            item.get("chapter_number"),
            "chapter_number",
            maximum=max(1, int(manifest.get("chapters_per_book") or 1)),
        )
        controls.append(
            {
                "control_id": control_id,
                "book_number": book_number,
                "chapter_number": chapter_number,
                "status": str(item.get("status") or "PLANNED"),
                "control_type": _enum(item.get("control_type"), CONTROL_TYPES, "control_type"),
                "subject_ref": deepcopy(item.get("subject_ref")) if isinstance(item.get("subject_ref"), dict) else None,
                "instruction": _text(item.get("instruction")),
                "certainty": _enum(item.get("certainty") or "supported_evidence", set(CERTAINTY_VALUES), "certainty"),
                "presentation": _enum(item.get("presentation") or "other", PRESENTATION_VALUES, "presentation"),
                "narrative_weight": _enum(item.get("narrative_weight") or "brief_clue", NARRATIVE_WEIGHT_VALUES, "narrative_weight"),
                "who_learns": _string_list(item.get("who_learns", []), "who_learns"),
                "effective_point": _enum(item.get("effective_point") or "current_unit", EFFECTIVE_POINT_VALUES, "effective_point"),
                "knowledge_ceiling": _text(item.get("knowledge_ceiling")) or "inherit",
                "allowed_interpretations": _string_list(item.get("allowed_interpretations", []), "allowed_interpretations"),
                "forbidden_assertions": _string_list(item.get("forbidden_assertions", []), "forbidden_assertions"),
                "persistence": _enum(item.get("persistence") or "chapter_local", PERSISTENCE_VALUES, "persistence"),
                "notes": _text(item.get("notes")),
                "validation_snapshot": deepcopy(item.get("validation_snapshot") or {}),
                "protection_snapshot": deepcopy(item.get("protection_snapshot") or {}),
                "semantic_guard_snapshot": deepcopy(item.get("semantic_guard_snapshot") or {}),
                "created_at": str(item.get("created_at") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
        )

    calculated = _content_hash(controls)
    stored_hash = str(raw.get("content_hash") or "")
    if stored_hash and stored_hash != calculated:
        raise StoryControlContractError(
            "Story Control Registry content hash does not match stored controls."
        )
    return {
        "schema_version": STORY_CONTROL_SCHEMA_VERSION,
        "project_id": context.project_id,
        "revision": int(raw.get("revision") or 0),
        "content_hash": stored_hash or calculated,
        "controls": controls,
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def _decorate_control(
    context: ProjectContext,
    manifest: dict[str, Any],
    control: dict[str, Any],
) -> dict[str, Any]:
    issues = []
    protection = {
        "checked": False,
        "eligibility_status": "",
        "reason_codes": [],
        "message": "",
    }

    instruction = _text(control.get("instruction"))
    if not instruction:
        issues.append(
            {
                "code": "instruction_required",
                "message": "Story Control requires an explicit author instruction.",
            }
        )

    subject_ref = control.get("subject_ref")
    if subject_ref:
        record_id = str(subject_ref.get("record_id") or "")
        effective_scope = book_scope_service.effective_book_scope_selections_for_context(
            context,
            manifest,
            book_number=int(control["book_number"]),
            chapter_number=int(control["chapter_number"]),
        )
        if record_id not in set(effective_scope.get("selection_ids") or []):
            issues.append(
                {
                    "code": "subject_outside_effective_book_scope",
                    "record_id": record_id,
                    "message": "Story Control subject is not in Canon for This Book at this chapter.",
                }
            )
        indexed = canon_index_service.get_record_by_id(
            context.project_id,
            record_id,
        )
        if indexed.get("status") != "found":
            issues.append(
                {
                    "code": "subject_record_missing",
                    "record_id": record_id,
                    "message": "Story Control subject no longer exists in the Canon Index.",
                }
            )
        else:
            row = dict(indexed["record"])
            requested_use = (
                "reveal"
                if str(control.get("control_type") or "") == "mystery_reveal"
                else "chapter_selection"
            )
            decision = story_eligibility_service.evaluate_story_eligibility(
                context.project_id,
                book_number=int(control["book_number"]),
                chapter_number=int(control["chapter_number"]),
                candidate_ref={
                    "record_id": record_id,
                    "record_type": str(row.get("record_type") or ""),
                    "label": str(row.get("display_label") or ""),
                },
                requested_use=requested_use,
                selected=True,
            )
            protection = {
                "checked": True,
                "eligibility_status": str(decision.get("status") or ""),
                "reason_codes": list(decision.get("reason_codes") or []),
                "message": str(decision.get("author_message") or ""),
            }
            if decision.get("status") != story_eligibility_service.STATUS_ACTIVE:
                issues.append(
                    {
                        "code": "protected_story_conflict",
                        "record_id": record_id,
                        "eligibility_status": str(decision.get("status") or ""),
                        "reason_codes": list(decision.get("reason_codes") or []),
                        "message": str(decision.get("author_message") or "Story Control conflicts with protected story rules."),
                    }
                )

    semantic_guard = _certainty_guard(
        instruction,
        str(control.get("certainty") or "supported_evidence"),
    )
    if semantic_guard["mismatch"]:
        issues.append(
            {
                "code": "certainty_instruction_mismatch",
                "message": semantic_guard["message"],
            }
        )

    return {
        **deepcopy(control),
        "validation": {
            "valid": not issues,
            "issues": issues,
        },
        "protection": protection,
        "semantic_guard": semantic_guard,
    }


def _normalize_subject_ref(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
    raw: Any,
) -> dict[str, Any] | None:
    if raw in (None, "", {}):
        return None
    if isinstance(raw, str):
        record_id = raw.strip()
    elif isinstance(raw, dict):
        record_id = str(raw.get("record_id") or "").strip()
    else:
        raise StoryControlContractError("subject_ref must be a stable-reference object.")
    if not record_id:
        return None
    indexed = canon_index_service.get_record_by_id(context.project_id, record_id)
    if indexed.get("status") != "found":
        raise StoryControlContractError(
            "Story Control subject_ref does not resolve in the Canon Index."
        )
    row = dict(indexed["record"])
    return {
        "record_id": record_id,
        "record_type": str(row.get("record_type") or ""),
        "label": str(row.get("display_label") or ""),
        "source_record_hash": str(row.get("source_hash") or ""),
    }


def _certainty_guard(instruction: str, certainty: str) -> dict[str, Any]:
    normalized = " ".join(str(instruction or "").casefold().split())
    chosen_rank = CERTAINTY_RANK.get(certainty, CERTAINTY_RANK["supported_evidence"])
    required = ""
    matched_phrase = ""
    for required_certainty, patterns in _OBVIOUS_STRENGTH_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if match:
                required = required_certainty
                matched_phrase = match.group(0)
                break
        if required:
            break

    mismatch = bool(
        required
        and CERTAINTY_RANK[required] > chosen_rank
    )
    return {
        "mode": "deterministic_obvious_mismatch_only",
        "complete_semantic_interpretation": False,
        "mismatch": mismatch,
        "chosen_certainty": certainty,
        "minimum_obvious_certainty": required,
        "matched_phrase": matched_phrase,
        "message": (
            f"Instruction language implies at least {required}, but certainty is {certainty}."
            if mismatch
            else "No obvious certainty-strength conflict detected; full semantic interpretation is deferred."
        ),
    }


def _stored_document(document: dict[str, Any]) -> dict[str, Any]:
    controls = []
    for control in document.get("controls") or []:
        controls.append(
            {
                key: deepcopy(control.get(key))
                for key in (
                    "control_id",
                    "book_number",
                    "chapter_number",
                    "status",
                    "control_type",
                    "subject_ref",
                    "instruction",
                    "certainty",
                    "presentation",
                    "narrative_weight",
                    "who_learns",
                    "effective_point",
                    "knowledge_ceiling",
                    "allowed_interpretations",
                    "forbidden_assertions",
                    "persistence",
                    "notes",
                    "validation_snapshot",
                    "protection_snapshot",
                    "semantic_guard_snapshot",
                    "created_at",
                    "updated_at",
                )
            }
        )
    return {
        "schema_version": STORY_CONTROL_SCHEMA_VERSION,
        "project_id": str(document.get("project_id") or ""),
        "revision": int(document.get("revision") or 0),
        "content_hash": _content_hash(controls),
        "controls": controls,
        "created_at": str(document.get("created_at") or ""),
        "updated_at": str(document.get("updated_at") or ""),
    }


def _content_hash(controls: list[dict[str, Any]]) -> str:
    stable = []
    for control in controls:
        stable.append(
            {
                "control_id": str(control.get("control_id") or ""),
                "book_number": int(control.get("book_number") or 0),
                "chapter_number": int(control.get("chapter_number") or 0),
                "status": str(control.get("status") or "PLANNED"),
                "control_type": str(control.get("control_type") or ""),
                "subject_id": str((control.get("subject_ref") or {}).get("record_id") or ""),
                "instruction": _text(control.get("instruction")),
                "certainty": str(control.get("certainty") or ""),
                "presentation": str(control.get("presentation") or ""),
                "narrative_weight": str(control.get("narrative_weight") or ""),
                "who_learns": list(control.get("who_learns") or []),
                "effective_point": str(control.get("effective_point") or ""),
                "knowledge_ceiling": _text(control.get("knowledge_ceiling")),
                "allowed_interpretations": list(control.get("allowed_interpretations") or []),
                "forbidden_assertions": list(control.get("forbidden_assertions") or []),
                "persistence": str(control.get("persistence") or ""),
                "notes": _text(control.get("notes")),
            }
        )
    stable.sort(key=lambda item: item["control_id"])
    encoded = json.dumps(
        stable,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _enum(value: Any, allowed: set[str] | frozenset[str], field_name: str) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    if normalized not in allowed:
        raise StoryControlContractError(
            f"{field_name} must be one of: {', '.join(sorted(allowed))}."
        )
    return normalized


def _positive_position(value: Any, field_name: str, *, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise StoryControlContractError(f"{field_name} must be an integer.") from exc
    if parsed < 1 or parsed > maximum:
        raise StoryControlContractError(
            f"{field_name} must be between 1 and {maximum}."
        )
    return parsed


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(raw: Any, field_name: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise StoryControlContractError(f"{field_name} must be an array.")
    values = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    return values


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
        "automatic_status_advance": True,
        "full_semantic_intent_model": True,
    }
