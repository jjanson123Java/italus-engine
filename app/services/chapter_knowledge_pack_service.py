"""
Project-local Chapter Knowledge Pack compiler.

Patch 27 owns the final bounded chapter context used by later Prompt Builder and
validator migration. It compiles derived artifacts only. It does not construct
provider prompts, call providers, write Approved Continuity, approve prose, or
unlock generation.

Chapter 1:
    Book Canon boundary + current chapter selections/events + kickoff.

Chapter N > 1:
    Book Canon boundary + Approved Continuity through N-1 + current chapter
    selections/event placements + optional bounded previous-ending context +
    kickoff.

Unlock Requirement decisions are delegated to Story Eligibility. Audited
progression overrides may authorize position-specific early use, but they never
establish continuity.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import (
    book_knowledge_pack_service,
    book_plan_service,
    canon_index_service,
    chapter_plan_service,
    progression_override_service,
    story_control_service,
    story_eligibility_service,
)


CHAPTER_KNOWLEDGE_PACK_SERVICE_MARKER = "project-chapter-knowledge-pack-v2-execution-contract-20260819"
CHAPTER_KNOWLEDGE_PACK_SCHEMA_VERSION = "chapter_knowledge_pack_v2"
CHAPTER_KNOWLEDGE_PACK_DIRECTORY = "chapter_knowledge_pack"
AUTHOR_CANON_RELATIVE_PATH = Path("canon") / "author_canon.json"

STATUS_BLOCKED = "blocked"
STATUS_READY = "ready"
STATUS_CURRENT = "current"
STATUS_OUTDATED = "outdated"
STATUS_MISSING = "missing"

MAX_PRIOR_ENDING_CHARS = 8000
GLOBAL_REQUIRED_SECTION_IDS = ("project_bible", "world_bible")
_ALLOWED_CONTINUITY_KEYS = (
    "established",
    "character_states",
    "relationship_states",
    "knowledge_states",
    "event_states",
    "mission_states",
    "reveal_states",
)


class ChapterKnowledgePackError(RuntimeError):
    """Base error for Chapter Knowledge Pack operations."""


class ChapterKnowledgePackNotReadyError(ChapterKnowledgePackError):
    """Raised when current project-local inputs cannot safely compile a pack."""


class ChapterKnowledgePackSourceMissingError(ChapterKnowledgePackError):
    """Raised when a required project-local source artifact is unavailable."""


def get_chapter_knowledge_pack_status(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return get_chapter_knowledge_pack_status_for_context(
        context,
        manifest_obj.to_dict(),
        book_number=book_number,
        chapter_number=chapter_number,
    )


def get_chapter_knowledge_pack_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    book_number = _positive_position(
        book_number,
        "book_number",
        maximum=max(1, int(manifest.get("book_count") or 1)),
    )
    chapter_number = _positive_position(
        chapter_number,
        "chapter_number",
        maximum=max(1, int(manifest.get("chapters_per_book") or 1)),
    )

    blockers: list[dict[str, Any]] = []

    # Fast-path the common pre-Patch-31 state: if this book's runtime-context
    # artifact does not exist yet, there is no reason to evaluate the full
    # series-wide Book Runtime Context status merely to discover that it is
    # missing. Preserve fail-closed behavior by falling back to the full status
    # evaluation whenever an artifact does exist and currentness must be proven.
    book_runtime_path = (
        context.project_canon_packs_dir
        / book_knowledge_pack_service.BOOK_RUNTIME_CONTEXT_DIRECTORY
        / f"book_{book_number:02d}.md"
    )
    if book_runtime_path.exists():
        book_status = book_knowledge_pack_service.get_book_runtime_context_status_for_context(
            context,
            manifest,
            book_number=book_number,
        )
        book_target = next(
            (
                item
                for item in book_status.get("targets") or []
                if int(item.get("book_number") or 0) == book_number
            ),
            None,
        )
    else:
        index_status = canon_index_service.ensure_current_index(context.project_id)
        book_status = {
            "canon_index": {
                "revision": str(index_status.get("index_content_hash") or ""),
            }
        }
        book_target = {
            "book_number": book_number,
            "status": book_knowledge_pack_service.STATUS_MISSING,
            "project_relative_path": str(
                book_runtime_path.relative_to(context.project_dir)
            ).replace("\\", "/"),
            "sha256": "",
        }
    if not book_target or book_target.get("status") != book_knowledge_pack_service.STATUS_CURRENT:
        blockers.append(
            {
                "code": "book_runtime_context_not_current",
                "message": (
                    f"Book {book_number} Runtime Context v2 must be compiled and current."
                ),
            }
        )

    chapter_result = chapter_plan_service.get_chapter_for_context(
        context,
        manifest,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    chapter = chapter_result["chapter"]
    chapter_valid = bool((chapter.get("validation") or {}).get("valid"))
    chapter_fresh = bool((chapter.get("freshness") or {}).get("fresh"))
    chapter_ready = bool((chapter.get("generation_readiness") or {}).get("ready"))
    chapter_has_content = str(chapter.get("lifecycle_state") or "") == chapter_plan_service.CHAPTER_STATUS_COMPLETE
    if not chapter_valid:
        blockers.append(
            {
                "code": "chapter_plan_invalid",
                "message": "Chapter Plan has unresolved stable-reference or Story Control issues.",
            }
        )
    if not chapter_fresh:
        blockers.append(
            {
                "code": "chapter_plan_outdated",
                "message": "Chapter Plan is outdated against current Book Canon or Book Plan.",
            }
        )
    if not chapter_ready:
        blockers.append(
            {
                "code": "chapter_plan_dependencies_not_ready",
                "message": "Chapter Plan dependencies are not approved/current.",
            }
        )
    if not chapter_has_content:
        blockers.append(
            {
                "code": "chapter_plan_not_complete",
                "message": (
                    "Save a lightweight Chapter Plan before compiling the Chapter Knowledge Pack. "
                    "A rigid beat sheet is not required."
                ),
            }
        )

    control_validation = story_control_service.validate_story_control_refs(
        context.project_id,
        book_number=book_number,
        chapter_number=chapter_number,
        control_ids=list(chapter.get("story_control_refs") or []),
    )
    if not control_validation.get("valid"):
        blockers.append(
            {
                "code": "story_controls_invalid",
                "message": "One or more selected Story Controls are invalid.",
                "issues": deepcopy(control_validation.get("issues") or []),
            }
        )

    continuity = _load_approved_continuity(context)
    if continuity["error"]:
        blockers.append(
            {
                "code": "approved_continuity_invalid",
                "message": "Approved Continuity is invalid.",
                "detail": continuity["error"],
            }
        )
    if chapter_number > 1:
        if not continuity["present"]:
            blockers.append(
                {
                    "code": "approved_continuity_missing",
                    "message": (
                        f"Chapter {chapter_number} requires Approved Continuity through Chapter "
                        f"{chapter_number - 1}."
                    ),
                }
            )
        elif not _coverage_reaches(
            continuity.get("approved_through"),
            book_number=book_number,
            chapter_number=chapter_number - 1,
        ):
            blockers.append(
                {
                    "code": "approved_continuity_coverage_incomplete",
                    "message": (
                        f"Approved Continuity must explicitly cover through Book {book_number}, "
                        f"Chapter {chapter_number - 1}."
                    ),
                    "approved_through": deepcopy(continuity.get("approved_through")),
                }
            )

    unlock_evaluations = _evaluate_selected_targets(
        context.project_id,
        chapter,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    for item in unlock_evaluations:
        decision = item["decision"]
        if decision.get("available") is True:
            continue
        blockers.append(
            {
                "code": "selected_target_not_eligible",
                "record_id": item["record_id"],
                "label": item["label"],
                "requested_use": item["requested_use"],
                "status": decision.get("status"),
                "message": decision.get("author_message") or "Selected Canon is not eligible.",
                "missing_prerequisites": deepcopy(
                    decision.get("missing_prerequisites") or []
                ),
                "allowed_actions": deepcopy(decision.get("allowed_actions") or []),
            }
        )

    override_state = progression_override_service.get_progression_overrides_for_context(
        context,
        target_ref=None,
    )

    source = {
        "book_runtime_context_sha256": str((book_target or {}).get("sha256") or ""),
        "book_runtime_context_path": str(
            (book_target or {}).get("project_relative_path") or ""
        ),
        "chapter_plan_revision": int(chapter.get("revision") or 0),
        "chapter_plan_sha256": str(chapter.get("content_hash") or ""),
        "story_control_revision": int(control_validation.get("registry_revision") or 0),
        "story_control_sha256": str(control_validation.get("registry_content_hash") or ""),
        "approved_continuity_revision": str(continuity.get("revision") or ""),
        "approved_continuity_sha256": str(continuity.get("content_hash") or ""),
        "approved_continuity_through": deepcopy(continuity.get("approved_through")),
        "progression_override_revision": int(override_state.get("revision") or 0),
        "progression_override_sha256": str(override_state.get("content_hash") or ""),
        "canon_index_revision": str(
            (book_status.get("canon_index") or {}).get("revision") or ""
        ),
    }
    dependency_hash = _json_hash(source)

    pack_path = chapter_knowledge_pack_path_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    sidecar_path = chapter_knowledge_pack_sidecar_path_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    exists = pack_path.exists() and sidecar_path.exists()
    sidecar = _read_sidecar(sidecar_path) if sidecar_path.exists() else {}
    current = bool(
        exists
        and sidecar.get("schema_version") == CHAPTER_KNOWLEDGE_PACK_SCHEMA_VERSION
        and sidecar.get("project_id") == context.project_id
        and int(sidecar.get("book_number") or 0) == book_number
        and int(sidecar.get("chapter_number") or 0) == chapter_number
        and sidecar.get("dependency_set_sha256") == dependency_hash
        and str(sidecar.get("pack_sha256") or "") == _sha256_file(pack_path)
    )

    compiler_ready = not blockers

    # Freshness and compiler readiness are distinct states.
    # A previously compiled artifact whose dependency hash no longer matches
    # must remain OUTDATED even when every current dependency is healthy enough
    # to compile a replacement. READY is reserved for a chapter that has no
    # compiled artifact yet and is ready for its first compile.
    status = (
        STATUS_CURRENT
        if compiler_ready and current
        else STATUS_OUTDATED
        if exists
        else STATUS_READY
        if compiler_ready
        else STATUS_BLOCKED
    )

    recovery_selected = deepcopy(sidecar.get("selected_canon_refs") or [])
    recovery_events = deepcopy(sidecar.get("assigned_event_refs") or [])
    recovery_placements = deepcopy(sidecar.get("event_placements") or [])
    recovery_available = bool(
        exists
        and not current
        and (recovery_selected or recovery_events or recovery_placements)
    )
    recovery_snapshot = {
        "available": recovery_available,
        "source_chapter_plan_revision": int(
            ((sidecar.get("source") or {}).get("chapter_plan_revision")) or 0
        ),
        "source_chapter_plan_sha256": str(
            ((sidecar.get("source") or {}).get("chapter_plan_sha256")) or ""
        ),
        "selected_canon_count": len(recovery_selected),
        "assigned_event_count": len(recovery_events),
        "selected_canon_refs": recovery_selected if recovery_available else [],
        "assigned_event_refs": recovery_events if recovery_available else [],
        "event_placements": recovery_placements if recovery_available else [],
    }

    return {
        "status": status,
        "service": CHAPTER_KNOWLEDGE_PACK_SERVICE_MARKER,
        "schema_version": CHAPTER_KNOWLEDGE_PACK_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "mode": "chapter_1" if chapter_number == 1 else "continuity_driven",
        "compiler_ready": compiler_ready,
        "chapter_knowledge_pack_generation_enabled": compiler_ready,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "approved_continuity_write_enabled": False,
        "pack": {
            "exists": pack_path.exists(),
            "current": current,
            "project_relative_path": _relative(pack_path, context.project_dir),
            "sha256": _sha256_file(pack_path) if pack_path.exists() else "",
            "sidecar_project_relative_path": _relative(sidecar_path, context.project_dir),
            "sidecar_sha256": _sha256_file(sidecar_path) if sidecar_path.exists() else "",
        },
        "source": source,
        "dependency_set_sha256": dependency_hash,
        "unlock_evaluations": unlock_evaluations,
        "token_accounting": deepcopy(sidecar.get("token_accounting") or {}),
        "recovery_snapshot": recovery_snapshot,
        "blockers": blockers,
        "execution_locks": _execution_locks(),
        "message": (
            "Chapter Knowledge Pack is current."
            if current and compiler_ready
            else "Chapter Knowledge Pack is outdated and ready to recompile."
            if exists and compiler_ready
            else "Chapter Knowledge Pack is outdated and compilation is blocked."
            if exists
            else "Chapter Knowledge Pack is ready to compile."
            if compiler_ready
            else "Chapter Knowledge Pack compilation is blocked."
        ),
    }


def compile_chapter_knowledge_pack(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    prior_ending_context: str = "",
) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return compile_chapter_knowledge_pack_for_context(
        context,
        manifest_obj.to_dict(),
        book_number=book_number,
        chapter_number=chapter_number,
        prior_ending_context=prior_ending_context,
    )


def compile_chapter_knowledge_pack_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
    prior_ending_context: str = "",
) -> dict[str, Any]:
    status = get_chapter_knowledge_pack_status_for_context(
        context,
        manifest,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    if not status["compiler_ready"]:
        messages = [
            str(item.get("message") or "")
            for item in status.get("blockers") or []
            if item.get("message")
        ]
        raise ChapterKnowledgePackNotReadyError(
            " ".join(messages) or "Chapter Knowledge Pack is not ready."
        )

    chapter = chapter_plan_service.get_chapter(
        context.project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    )["chapter"]

    author_path = context.project_dir / AUTHOR_CANON_RELATIVE_PATH
    if not author_path.exists():
        raise ChapterKnowledgePackSourceMissingError(
            "Project-local Author Canon is missing."
        )
    author_canon = project_loader.read_json(author_path)
    records_by_id = _author_record_map(author_canon)
    all_record_ids = set(records_by_id)

    selected_ids = _ordered_selected_ids(chapter)
    missing_ids = [record_id for record_id in selected_ids if record_id not in records_by_id]
    if missing_ids:
        raise ChapterKnowledgePackSourceMissingError(
            "Chapter Plan references Canon IDs missing from Author Canon: "
            + ", ".join(missing_ids)
        )

    selected_set = set(selected_ids)
    bounded_records = [
        _bounded_record_payload(
            records_by_id[record_id],
            selected_ids=selected_set,
            all_record_ids=all_record_ids,
        )
        for record_id in selected_ids
    ]
    chapter_execution_contract = _build_chapter_execution_contract(chapter)

    plan = book_plan_service.get_book_plan_for_context(context, manifest)["plan"]
    book = next(
        (
            item
            for item in plan.get("books") or []
            if int(item.get("book_number") or 0) == int(book_number)
        ),
        None,
    )
    if not book:
        raise ChapterKnowledgePackSourceMissingError(
            f"Book Plan does not contain Book {book_number}."
        )

    controls = story_control_service.validate_story_control_refs(
        context.project_id,
        book_number=book_number,
        chapter_number=chapter_number,
        control_ids=list(chapter.get("story_control_refs") or []),
    )["controls"]

    continuity = _load_approved_continuity(context)
    continuity_payload = (
        _bounded_continuity_payload(
            continuity,
            book_number=book_number,
            chapter_number=max(0, chapter_number - 1),
        )
        if chapter_number > 1
        else {}
    )

    prior_ending = _bounded_prior_ending(prior_ending_context)
    unlock_evaluations = deepcopy(status["unlock_evaluations"])
    generated_at = utc_now_iso()

    body = _render_chapter_body(
        book=book,
        chapter=chapter,
        global_rules=_global_required_rules(author_canon),
        bounded_records=bounded_records,
        controls=controls,
        continuity_payload=continuity_payload,
        prior_ending_context=prior_ending,
        unlock_evaluations=unlock_evaluations,
        chapter_execution_contract=chapter_execution_contract,
    )
    pack_tokens = _estimate_tokens(body)
    book_tokens = int(
        next(
            (
                item.get("estimated_tokens") or 0
                for item in book_knowledge_pack_service.get_book_runtime_context_status_for_context(
                    context,
                    manifest,
                ).get("targets") or []
                if int(item.get("book_number") or 0) == int(book_number)
            ),
            0,
        )
        or 0
    )
    full_tokens = int(
        next(
            (
                item.get("full_context_estimated_tokens") or 0
                for item in book_knowledge_pack_service.get_book_runtime_context_status_for_context(
                    context,
                    manifest,
                ).get("targets") or []
                if int(item.get("book_number") or 0) == int(book_number)
            ),
            0,
        )
        or 0
    )

    pack_path = chapter_knowledge_pack_path_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    sidecar_path = chapter_knowledge_pack_sidecar_path_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
    )

    content = _render_chapter_pack(
        context=context,
        book=book,
        chapter=chapter,
        generated_at=generated_at,
        source=status["source"],
        dependency_hash=status["dependency_set_sha256"],
        body=body,
        pack_tokens=pack_tokens,
        book_tokens=book_tokens,
        full_tokens=full_tokens,
    )
    _write_text_atomic(pack_path, content)
    pack_sha = _sha256_file(pack_path)

    sidecar = {
        "schema_version": CHAPTER_KNOWLEDGE_PACK_SCHEMA_VERSION,
        "service": CHAPTER_KNOWLEDGE_PACK_SERVICE_MARKER,
        "project_id": context.project_id,
        "book_number": int(book_number),
        "chapter_number": int(chapter_number),
        "mode": "chapter_1" if int(chapter_number) == 1 else "continuity_driven",
        "generated_at": generated_at,
        "dependency_set_sha256": status["dependency_set_sha256"],
        "pack_project_relative_path": _relative(pack_path, context.project_dir),
        "pack_sha256": pack_sha,
        "source": deepcopy(status["source"]),
        "selected_canon_refs": deepcopy(chapter.get("selected_canon_refs") or []),
        "assigned_event_refs": deepcopy(chapter.get("assigned_event_refs") or []),
        "event_placements": deepcopy(chapter.get("event_placements") or []),
        "chapter_event_sequence": deepcopy(chapter.get("event_placements") or []),
        "chapter_execution_contract": deepcopy(chapter_execution_contract),
        "story_control_refs": list(chapter.get("story_control_refs") or []),
        "story_controls": deepcopy(controls),
        "unlock_evaluations": unlock_evaluations,
        "continuity": {
            "required": int(chapter_number) > 1,
            "source_revision": str(continuity.get("revision") or ""),
            "source_sha256": str(continuity.get("content_hash") or ""),
            "approved_through": deepcopy(continuity.get("approved_through")),
            "bounded_state": continuity_payload,
        },
        "prior_ending_context": {
            "included": bool(prior_ending),
            "sha256": _text_hash(prior_ending) if prior_ending else "",
            "character_count": len(prior_ending),
        },
        "validator_sidecar": {
            "selected_record_ids": selected_ids,
            "chapter_execution_contract": deepcopy(chapter_execution_contract),
            "event_placements": deepcopy(chapter.get("event_placements") or []),
            "chapter_restrictions": deepcopy(chapter.get("restrictions") or []),
            "allowed_reveals": deepcopy(book.get("allowed_reveals") or []),
            "forbidden_future_knowledge": deepcopy(
                book.get("forbidden_future_knowledge") or []
            ),
            "story_controls": deepcopy(controls),
            "unlock_evaluations": unlock_evaluations,
            "approved_continuity_source_revision": str(
                continuity.get("revision") or ""
            ),
            "approved_continuity_source_sha256": str(
                continuity.get("content_hash") or ""
            ),
        },
        "token_accounting": {
            "full_project_runtime_context_estimated_tokens": full_tokens,
            "book_runtime_context_estimated_tokens": book_tokens,
            "chapter_knowledge_pack_estimated_tokens": pack_tokens,
            "reduction_from_book_runtime_context": max(0, book_tokens - pack_tokens),
            "reduction_from_book_runtime_context_percent": (
                round(((book_tokens - pack_tokens) / book_tokens) * 100.0, 2)
                if book_tokens > 0
                else 0.0
            ),
            "reduction_from_full_project_runtime_context": max(
                0, full_tokens - pack_tokens
            ),
            "reduction_from_full_project_runtime_context_percent": (
                round(((full_tokens - pack_tokens) / full_tokens) * 100.0, 2)
                if full_tokens > 0
                else 0.0
            ),
        },
        "execution_locks": _execution_locks(),
    }
    _write_json_atomic(sidecar_path, sidecar)

    return {
        "status": "compiled",
        "service": CHAPTER_KNOWLEDGE_PACK_SERVICE_MARKER,
        "schema_version": CHAPTER_KNOWLEDGE_PACK_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": int(book_number),
        "chapter_number": int(chapter_number),
        "mode": sidecar["mode"],
        "pack": {
            "project_relative_path": _relative(pack_path, context.project_dir),
            "sha256": pack_sha,
            "size_bytes": pack_path.stat().st_size,
            "sidecar_project_relative_path": _relative(
                sidecar_path, context.project_dir
            ),
            "sidecar_sha256": _sha256_file(sidecar_path),
        },
        "token_accounting": sidecar["token_accounting"],
        "unlock_evaluations": unlock_evaluations,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "approved_continuity_write_enabled": False,
        "execution_locks": _execution_locks(),
        "message": (
            "Chapter Knowledge Pack compiled. Prompt Builder/provider execution and "
            "Approved Continuity writes remain locked."
        ),
    }


def chapter_knowledge_pack_path_for_context(
    context: ProjectContext,
    *,
    book_number: int,
    chapter_number: int,
) -> Path:
    return (
        context.project_canon_packs_dir
        / CHAPTER_KNOWLEDGE_PACK_DIRECTORY
        / f"book_{int(book_number):02d}_chapter_{int(chapter_number):03d}.md"
    )


def chapter_knowledge_pack_sidecar_path_for_context(
    context: ProjectContext,
    *,
    book_number: int,
    chapter_number: int,
) -> Path:
    return (
        context.project_canon_packs_dir
        / CHAPTER_KNOWLEDGE_PACK_DIRECTORY
        / f"book_{int(book_number):02d}_chapter_{int(chapter_number):03d}.json"
    )


def _evaluate_selected_targets(
    project_id: str,
    chapter: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
) -> list[dict[str, Any]]:
    ordered: list[tuple[str, dict[str, Any]]] = []
    assigned_ids = {
        str(ref.get("record_id") or "")
        for ref in chapter.get("assigned_event_refs") or []
        if ref.get("record_id")
    }
    seen: set[str] = set()
    for ref in list(chapter.get("assigned_event_refs") or []) + list(
        chapter.get("selected_canon_refs") or []
    ):
        record_id = str(ref.get("record_id") or "").strip()
        if not record_id or record_id in seen:
            continue
        seen.add(record_id)
        requested_use = (
            "event_placement" if record_id in assigned_ids else "chapter_selection"
        )
        ordered.append((requested_use, ref))

    result = []
    for requested_use, ref in ordered:
        decision = story_eligibility_service.evaluate_story_eligibility(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            candidate_ref={
                "record_id": str(ref.get("record_id") or ""),
                "record_type": str(ref.get("record_type") or ""),
                "label": str(ref.get("label") or ""),
            },
            requested_use=requested_use,
            selected=True,
        )
        candidate = decision.get("candidate_ref") or {}
        result.append(
            {
                "record_id": str(ref.get("record_id") or ""),
                "record_type": str(
                    candidate.get("record_type") or ref.get("record_type") or ""
                ),
                "label": str(candidate.get("label") or ref.get("label") or ""),
                "requested_use": requested_use,
                "decision": decision,
            }
        )
    return result


def _load_approved_continuity(context: ProjectContext) -> dict[str, Any]:
    path = story_eligibility_service.approved_continuity_path_for_context(context)
    if not path.exists():
        return {
            "present": False,
            "revision": "",
            "content_hash": "",
            "approved_through": None,
            "payload": {},
            "error": "",
        }
    try:
        payload = project_loader.read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "present": True,
            "revision": "",
            "content_hash": "",
            "approved_through": None,
            "payload": {},
            "error": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "present": True,
            "revision": "",
            "content_hash": "",
            "approved_through": None,
            "payload": {},
            "error": "root must be an object",
        }
    if payload.get("schema_version") != story_eligibility_service.APPROVED_CONTINUITY_SCHEMA_VERSION:
        return {
            "present": True,
            "revision": str(payload.get("revision") or ""),
            "content_hash": _json_hash(payload),
            "approved_through": None,
            "payload": payload,
            "error": (
                "schema_version must be "
                f"{story_eligibility_service.APPROVED_CONTINUITY_SCHEMA_VERSION}"
            ),
        }
    approved_through = payload.get("approved_through")
    if approved_through is not None and not isinstance(approved_through, dict):
        return {
            "present": True,
            "revision": str(payload.get("revision") or ""),
            "content_hash": _json_hash(payload),
            "approved_through": None,
            "payload": payload,
            "error": "approved_through must be an object when present",
        }
    return {
        "present": True,
        "revision": str(payload.get("revision") or ""),
        "content_hash": _json_hash(payload),
        "approved_through": deepcopy(approved_through),
        "payload": payload,
        "error": "",
    }


def _coverage_reaches(
    approved_through: dict[str, Any] | None,
    *,
    book_number: int,
    chapter_number: int,
) -> bool:
    if chapter_number <= 0:
        return True
    if not isinstance(approved_through, dict):
        return False
    try:
        approved_book = int(approved_through.get("book_number") or 0)
        approved_chapter = int(approved_through.get("chapter_number") or 0)
    except (TypeError, ValueError):
        return False
    return (approved_book, approved_chapter) >= (int(book_number), int(chapter_number))


def _bounded_continuity_payload(
    continuity: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    payload = continuity.get("payload") or {}
    result: dict[str, Any] = {
        "approved_through": deepcopy(continuity.get("approved_through")),
        "revision": str(continuity.get("revision") or ""),
    }
    for key in _ALLOWED_CONTINUITY_KEYS:
        value = payload.get(key)
        if key == "established" and isinstance(value, list):
            result[key] = [
                deepcopy(item)
                for item in value
                if isinstance(item, dict)
                and _position_at_or_before(
                    item,
                    book_number=book_number,
                    chapter_number=chapter_number,
                )
            ]
        elif isinstance(value, (list, dict)):
            result[key] = deepcopy(value)
    return result


def _position_at_or_before(
    item: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
) -> bool:
    raw_book = item.get("book_number")
    raw_chapter = item.get("chapter_number")
    if raw_book in (None, ""):
        return True
    try:
        item_book = int(raw_book)
    except (TypeError, ValueError):
        return False
    if item_book < book_number:
        return True
    if item_book > book_number:
        return False
    if raw_chapter in (None, ""):
        return True
    try:
        return int(raw_chapter) <= int(chapter_number)
    except (TypeError, ValueError):
        return False


def _ordered_selected_ids(chapter: dict[str, Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for field in ("selected_canon_refs", "assigned_event_refs", "pov"):
        for ref in chapter.get(field) or []:
            record_id = str(ref.get("record_id") or "").strip()
            if record_id and record_id not in seen:
                seen.add(record_id)
                ordered.append(record_id)
    return ordered


def _author_record_map(author_canon: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(author_canon, dict):
        raise ChapterKnowledgePackSourceMissingError(
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


def _stable_ref_payload(ref: Any) -> dict[str, str]:
    if not isinstance(ref, dict):
        return {}
    record_id = str(ref.get("record_id") or "").strip()
    if not record_id:
        return {}
    return {
        "record_id": record_id,
        "record_type": str(ref.get("record_type") or "").strip(),
        "label": str(ref.get("label") or record_id).strip(),
    }


def _dedupe_refs(refs: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for ref in refs:
        record_id = str(ref.get("record_id") or "").strip()
        if not record_id or record_id in seen:
            continue
        seen.add(record_id)
        result.append(ref)
    return result


def _build_chapter_execution_contract(chapter: dict[str, Any]) -> dict[str, Any]:
    """Derive prompt-facing chapter obligations from author-owned Chapter Plan state.

    This is intentionally derived state. It does not mutate Chapter Plan and it does
    not depend on Book Plan ``required_*`` fields. A record selected at chapter scope
    is an execution obligation for that chapter; Book-level Required remains a
    separate book-completion constraint.
    """

    selected_refs = [
        ref
        for raw in chapter.get("selected_canon_refs") or []
        if (ref := _stable_ref_payload(raw))
    ]
    pov_refs = [
        ref
        for raw in chapter.get("pov") or []
        if (ref := _stable_ref_payload(raw))
    ]
    assigned_event_refs = [
        ref
        for raw in chapter.get("assigned_event_refs") or []
        if (ref := _stable_ref_payload(raw))
    ]

    participants = [
        ref for ref in selected_refs if ref.get("record_type") == "character"
    ]
    participants.extend(pov_refs)
    participants = _dedupe_refs(participants)

    locations = _dedupe_refs(
        [ref for ref in selected_refs if ref.get("record_type") == "location"]
    )

    placed_events: list[dict[str, Any]] = []
    placed_ids: set[str] = set()
    for ordinal, placement in enumerate(chapter.get("event_placements") or [], start=1):
        if not isinstance(placement, dict):
            continue
        event_ref = _stable_ref_payload(placement.get("event_ref"))
        if not event_ref:
            continue
        record_id = event_ref["record_id"]
        if record_id in placed_ids:
            continue
        placed_ids.add(record_id)
        anchor_ref = _stable_ref_payload(placement.get("anchor_event_ref"))
        placed_events.append(
            {
                "ordinal": ordinal,
                "event_ref": event_ref,
                "chapter_role": str(placement.get("chapter_role") or "").strip(),
                "position": str(placement.get("position") or "flexible").strip(),
                "relationship_to_anchor": str(
                    placement.get("relationship_to_anchor") or ""
                ).strip(),
                "anchor_event_ref": anchor_ref,
                "objective": str(placement.get("objective") or "").strip(),
            }
        )

    # Assigned events remain required chapter beats even if the author has not yet
    # supplied a placement row. They follow explicitly placed events in assignment
    # order and are marked unplaced so Prompt Builder can preserve the obligation.
    next_ordinal = len(placed_events) + 1
    for event_ref in assigned_event_refs:
        if event_ref["record_id"] in placed_ids:
            continue
        placed_ids.add(event_ref["record_id"])
        placed_events.append(
            {
                "ordinal": next_ordinal,
                "event_ref": event_ref,
                "chapter_role": "",
                "position": "flexible",
                "relationship_to_anchor": "",
                "anchor_event_ref": {},
                "objective": "",
            }
        )
        next_ordinal += 1

    assigned_ids = {ref["record_id"] for ref in assigned_event_refs}
    assigned_ids.update(placed_ids)
    additional = _dedupe_refs(
        [
            ref
            for ref in selected_refs
            if ref.get("record_type") not in {"character", "location", "event"}
            and ref["record_id"] not in assigned_ids
        ]
    )

    return {
        "contract_version": "chapter_execution_contract_v1",
        "semantics": {
            "book_selection": (
                "Selected for Book controls downstream availability and does not by "
                "itself create a chapter-use obligation."
            ),
            "chapter_selection": (
                "Author-selected chapter records are execution obligations for this "
                "chapter. They must be represented where their type and placement apply."
            ),
            "book_required": (
                "Book Plan Required/Major fields are separate optional book-completion "
                "constraints and are not prerequisites for chapter participation."
            ),
        },
        "required_participant_refs": participants,
        "required_location_refs": locations,
        "required_event_sequence": placed_events,
        "required_additional_canon_refs": additional,
        "pov_refs": _dedupe_refs(pov_refs),
    }


def _render_chapter_body(
    *,
    book: dict[str, Any],
    chapter: dict[str, Any],
    global_rules: list[dict[str, Any]],
    bounded_records: list[dict[str, Any]],
    controls: list[dict[str, Any]],
    continuity_payload: dict[str, Any],
    prior_ending_context: str,
    unlock_evaluations: list[dict[str, Any]],
    chapter_execution_contract: dict[str, Any],
) -> str:
    lines = [
        "## Book Boundary",
        "",
        f"- Book Number: {int(book.get('book_number') or 0)}",
        f"- Title: {book.get('title') or ''}",
        f"- Primary Arc: {book.get('primary_arc') or ''}",
        f"- Ending State: {book.get('ending_state') or ''}",
        "",
        "### Allowed Reveals",
        *_text_markdown_list(book.get("allowed_reveals")),
        "",
        "### Forbidden Future Knowledge",
        *_text_markdown_list(book.get("forbidden_future_knowledge")),
        "",
        "## Chapter Execution Contract",
        "",
        (
            "> Author-selected chapter elements below are execution obligations for this "
            "chapter. Book-level Required/Major fields are separate optional book-completion "
            "constraints and are not prerequisites for chapter participation."
        ),
        "",
        "### Required Chapter Participants",
    ]
    participants = chapter_execution_contract.get("required_participant_refs") or []
    if participants:
        lines.extend([f"- {ref.get('label') or ref.get('record_id')}" for ref in participants])
    else:
        lines.append("- None")

    lines.extend(["", "### POV Constraint"])
    pov_refs = chapter_execution_contract.get("pov_refs") or []
    if pov_refs:
        lines.extend([f"- {ref.get('label') or ref.get('record_id')}" for ref in pov_refs])
    else:
        lines.append("- None")

    lines.extend(["", "### Required Chapter Locations"])
    required_locations = chapter_execution_contract.get("required_location_refs") or []
    if required_locations:
        lines.extend([f"- {ref.get('label') or ref.get('record_id')}" for ref in required_locations])
    else:
        lines.append("- None")

    lines.extend(["", "### Required Chapter Event Sequence"])
    event_sequence = chapter_execution_contract.get("required_event_sequence") or []
    if event_sequence:
        for item in event_sequence:
            event_ref = item.get("event_ref") or {}
            label = str(event_ref.get("label") or event_ref.get("record_id") or "Event")
            details = []
            role = str(item.get("chapter_role") or "").replace("_", " ").title()
            position = str(item.get("position") or "flexible").replace("_", " ").title()
            relationship = str(item.get("relationship_to_anchor") or "").replace("_", " ").title()
            anchor_ref = item.get("anchor_event_ref") or {}
            anchor_label = str(anchor_ref.get("label") or anchor_ref.get("record_id") or "")
            if role:
                details.append(f"Role: {role}")
            if position:
                details.append(f"Placement: {position}")
            if relationship:
                relation_text = relationship
                if anchor_label:
                    relation_text += f" {anchor_label}"
                details.append(f"Relationship: {relation_text}")
            suffix = f" — {' | '.join(details)}" if details else ""
            lines.append(f"{int(item.get('ordinal') or 0)}. {label}{suffix}")
            objective = str(item.get("objective") or "").strip()
            if objective:
                lines.append(f"   - Objective: {objective}")
    else:
        lines.append("- None")

    lines.extend(["", "### Required Additional Chapter Canon"])
    additional = chapter_execution_contract.get("required_additional_canon_refs") or []
    if additional:
        lines.extend([f"- {ref.get('label') or ref.get('record_id')}" for ref in additional])
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Global Required Rules",
            "",
        ]
    )
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
            "## Current Chapter Plan",
            "",
            f"- Chapter Number: {int(chapter.get('chapter_number') or 0)}",
            f"- Generation Kickoff: {chapter.get('generation_kickoff') or ''}",
            f"- Chapter Objective: {chapter.get('chapter_objective') or ''}",
            "",
            "### Restrictions",
            *_text_markdown_list(chapter.get("restrictions")),
            "",
            "### Event Placements",
        ]
    )
    for index, placement in enumerate(chapter.get("event_placements") or [], start=1):
        event_ref = placement.get("event_ref") or {}
        label = str(event_ref.get("label") or event_ref.get("record_id") or "Event")
        position = str(placement.get("position") or "flexible").replace("_", " ").title()
        role = str(placement.get("chapter_role") or "").replace("_", " ").title()
        relationship = str(placement.get("relationship_to_anchor") or "").replace("_", " ").title()
        anchor = placement.get("anchor_event_ref") or {}
        anchor_label = str(anchor.get("label") or anchor.get("record_id") or "")
        objective = str(placement.get("objective") or "").strip()
        details = [position]
        if role:
            details.append(f"Role: {role}")
        if relationship:
            relation_text = relationship
            if anchor_label:
                relation_text += f" {anchor_label}"
            details.append(f"Relationship: {relation_text}")
        lines.append(f"{index}. {label} — " + " | ".join(details))
        if objective:
            lines.append(f"   - Objective: {objective}")
    if not (chapter.get("event_placements") or []):
        lines.append("- None")

    lines.extend(["", "## Selected Chapter Canon", ""])
    for record in bounded_records:
        label = _record_label(record)
        lines.extend(
            [
                f"### {label}",
                "",
                f"- Record ID: `{record.get('internal_id') or ''}`",
                "",
                "```json",
                json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True),
                "```",
                "",
            ]
        )
    if not bounded_records:
        lines.extend(["No explicit Chapter Canon records selected.", ""])

    lines.extend(["## Story Controls", ""])
    if controls:
        for control in controls:
            lines.extend(
                [
                    f"### {str(control.get('control_type') or 'Story Control').replace('_', ' ').title()}",
                    f"- Subject: {((control.get('subject_ref') or {}).get('label') or '')}",
                    f"- Required Beat: {control.get('instruction') or ''}",
                    f"- Certainty: {str(control.get('certainty') or '').replace('_', ' ').title()}",
                    f"- Presentation: {str(control.get('presentation') or '').replace('_', ' ').title()}",
                    f"- Narrative Weight: {str(control.get('narrative_weight') or '').replace('_', ' ').title()}",
                    "",
                    "Forbidden assertions:",
                    *_text_markdown_list(control.get("forbidden_assertions")),
                    "",
                ]
            )
    else:
        lines.extend(["- None", ""])

    lines.extend(["## Approved Continuity", ""])
    if continuity_payload:
        lines.extend(
            [
                "```json",
                json.dumps(
                    continuity_payload,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "```",
                "",
            ]
        )
    else:
        lines.extend(["- Chapter 1: no prior Approved Continuity required.", ""])

    if prior_ending_context:
        lines.extend(
            [
                "## Bounded Prior-Chapter Ending Context",
                "",
                prior_ending_context,
                "",
            ]
        )

    lines.extend(["## Unlock Evaluation", ""])
    for item in unlock_evaluations:
        decision = item["decision"]
        lines.extend(
            [
                f"### {item['label'] or item['record_id']}",
                f"- Requested Use: {item['requested_use']}",
                f"- Status: {decision.get('status') or ''}",
                f"- Available: {bool(decision.get('available'))}",
                f"- Override Applied: {bool(decision.get('override_applied'))}",
                f"- Message: {decision.get('author_message') or ''}",
                "",
            ]
        )
    if not unlock_evaluations:
        lines.extend(["- No selected targets require evaluation.", ""])

    lines.extend(
        [
            "## Runtime Boundary",
            "",
            "- Full Project Runtime Context: omitted",
            "- Unselected Book Canon records: omitted",
            "- All previous chapter prose: omitted",
            "- Hidden validator-only truth: omitted from prose-facing pack",
            "- Prompt Builder: not called",
            "- Provider Execution: disabled",
            "- Approved Continuity writes: disabled",
            "- Generation Unlock: disabled",
            "",
        ]
    )
    return "\n".join(lines)


def _render_chapter_pack(
    *,
    context: ProjectContext,
    book: dict[str, Any],
    chapter: dict[str, Any],
    generated_at: str,
    source: dict[str, Any],
    dependency_hash: str,
    body: str,
    pack_tokens: int,
    book_tokens: int,
    full_tokens: int,
) -> str:
    book_number = int(book.get("book_number") or 0)
    chapter_number = int(chapter.get("chapter_number") or 0)
    return "\n".join(
        [
            f"# Book {book_number:02d} Chapter {chapter_number:03d} Knowledge Pack",
            "",
            "> Derived bounded chapter artifact. Author Canon, Book Scope, Book Plan, "
            "Chapter Plan, Story Controls, and Approved Continuity remain authoritative.",
            "",
            "## Compiler Metadata",
            "",
            f"- Schema Version: `{CHAPTER_KNOWLEDGE_PACK_SCHEMA_VERSION}`",
            f"- Compiler: `{CHAPTER_KNOWLEDGE_PACK_SERVICE_MARKER}`",
            f"- Project ID: `{context.project_id}`",
            f"- Book Number: `{book_number}`",
            f"- Chapter Number: `{chapter_number}`",
            f"- Generated At: {generated_at}",
            f"- Dependency Set SHA-256: `{dependency_hash}`",
            f"- Book Runtime Context SHA-256: `{source.get('book_runtime_context_sha256') or ''}`",
            f"- Chapter Plan Revision: `{source.get('chapter_plan_revision') or 0}`",
            f"- Chapter Plan SHA-256: `{source.get('chapter_plan_sha256') or ''}`",
            f"- Story Control Revision: `{source.get('story_control_revision') or 0}`",
            f"- Story Control SHA-256: `{source.get('story_control_sha256') or ''}`",
            f"- Approved Continuity Revision: `{source.get('approved_continuity_revision') or ''}`",
            f"- Approved Continuity SHA-256: `{source.get('approved_continuity_sha256') or ''}`",
            f"- Progression Override Revision: `{source.get('progression_override_revision') or 0}`",
            f"- Progression Override SHA-256: `{source.get('progression_override_sha256') or ''}`",
            f"- Estimated Tokens: `{pack_tokens}`",
            f"- Book Runtime Context Estimated Tokens: `{book_tokens}`",
            f"- Full Project Runtime Context Estimated Tokens: `{full_tokens}`",
            "",
            body.rstrip(),
            "",
            "---",
            "",
            "End of bounded Chapter Knowledge Pack.",
            "",
        ]
    )


def _bounded_prior_ending(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > MAX_PRIOR_ENDING_CHARS:
        return text[-MAX_PRIOR_ENDING_CHARS:]
    return text


def _record_label(record: dict[str, Any]) -> str:
    for key in ("name", "title", "label", "display_label"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return str(record.get("internal_id") or "Canon Record")


def _text_markdown_list(values: Any) -> list[str]:
    items = [str(item).strip() for item in (values or []) if str(item).strip()]
    return [f"- {item}" for item in items] or ["- None"]


def _estimate_tokens(text: str) -> int:
    return int(math.ceil(len(text or "") / 4.0))


def _positive_position(value: Any, field_name: str, *, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ChapterKnowledgePackError(f"{field_name} must be an integer.") from exc
    if result < 1 or result > maximum:
        raise ChapterKnowledgePackError(
            f"{field_name} must be between 1 and {maximum}."
        )
    return result


def _read_sidecar(path: Path) -> dict[str, Any]:
    try:
        payload = project_loader.read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_hash(payload: Any) -> str:
    data = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
    )


def _relative(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _execution_locks() -> dict[str, bool]:
    return {
        "prompt_builder_enabled": False,
        "provider_execution_enabled": False,
        "generation_enabled": False,
        "approved_continuity_write_enabled": False,
        "runtime_memory_write_enabled": False,
        "master_canon_mutation_enabled": False,
    }
