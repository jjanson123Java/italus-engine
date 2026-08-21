"""
Project-local auditable progression override registry.

Patch 27 owns a narrow author action for position-specific early use of a
Canon target that is FUTURE or RESTRICTED under Story Eligibility. The
override authorizes use only at the recorded planning position and requested
use. It never changes Master Canon, rewrites Available From, marks an
Unlock Requirement established, or writes Approved Continuity.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import chapter_plan_service, story_eligibility_service


PROGRESSION_OVERRIDE_SERVICE_MARKER = "project-progression-override-v1-20260817"
PROGRESSION_OVERRIDE_SCHEMA_VERSION = "progression_overrides_v1"
PROGRESSION_OVERRIDE_FILENAME = "progression_overrides.json"
OVERRIDE_TYPE_ONE_TIME = "one_time"
AUTHOR_ACTION_AUTHORIZE_EARLY_USE = "authorize_early_use"


class ProgressionOverrideError(RuntimeError):
    """Base error for progression override operations."""


class ProgressionOverrideConflictError(ProgressionOverrideError):
    """Raised when the requested override does not target an overridable conflict."""


class ProgressionOverrideContractError(ProgressionOverrideError):
    """Raised when persisted override state is malformed."""


def progression_override_path(project_id: str) -> Path:
    manifest = project_loader.load_manifest(project_id)
    return progression_override_path_for_context(build_project_context(manifest))


def progression_override_path_for_context(context: ProjectContext) -> Path:
    return context.project_dir / PROGRESSION_OVERRIDE_FILENAME


def get_progression_overrides(
    project_id: str,
    *,
    target_ref: str | None = None,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_progression_overrides_for_context(
        context,
        target_ref=target_ref,
    )


def get_progression_overrides_for_context(
    context: ProjectContext,
    *,
    target_ref: str | None = None,
) -> dict[str, Any]:
    state = _load_document(context)
    if state["error"]:
        raise ProgressionOverrideContractError(state["error"])
    target = str(target_ref or "").strip()
    overrides = [
        deepcopy(item)
        for item in state["document"]["overrides"]
        if not target or str((item.get("target_ref") or {}).get("record_id") or "") == target
    ]
    return {
        "status": "ok",
        "service": PROGRESSION_OVERRIDE_SERVICE_MARKER,
        "schema_version": PROGRESSION_OVERRIDE_SCHEMA_VERSION,
        "project_id": context.project_id,
        "revision": int(state["document"].get("revision") or 0),
        "content_hash": str(state["document"].get("content_hash") or ""),
        "override_count": len(overrides),
        "overrides": overrides,
        "execution_locks": _execution_locks(),
    }


def authorize_early_use(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    target_ref: str,
    requested_use: str,
    reason: str = "",
) -> dict[str, Any]:
    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    return authorize_early_use_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
        target_ref=target_ref,
        requested_use=requested_use,
        reason=reason,
    )


def authorize_early_use_for_context(
    context: ProjectContext,
    *,
    book_number: int,
    chapter_number: int,
    target_ref: str,
    requested_use: str,
    reason: str = "",
) -> dict[str, Any]:
    book_number = _positive_int(book_number, "book_number")
    chapter_number = _positive_int(chapter_number, "chapter_number")
    record_id = str(target_ref or "").strip()
    if not record_id:
        raise ProgressionOverrideContractError("target_ref is required.")
    use = str(requested_use or "").strip()
    if use not in story_eligibility_service.SUPPORTED_REQUESTED_USES:
        raise ProgressionOverrideContractError(
            f"requested_use must be one of: {', '.join(sorted(story_eligibility_service.SUPPORTED_REQUESTED_USES))}."
        )

    # The current Chapter Plan is the audit anchor. An override cannot be
    # recorded against stale or structurally invalid planning state.
    chapter_result = chapter_plan_service.get_chapter(
        context.project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    chapter = chapter_result["chapter"]
    validation = chapter.get("validation") or {}
    freshness = chapter.get("freshness") or {}
    if not validation.get("valid"):
        raise ProgressionOverrideConflictError(
            "Chapter Plan must be structurally valid before authorizing early use."
        )
    if not freshness.get("fresh"):
        raise ProgressionOverrideConflictError(
            "Chapter Plan must be current before authorizing early use."
        )

    state = _load_document(context)
    if state["error"]:
        raise ProgressionOverrideContractError(state["error"])
    document = deepcopy(state["document"])

    # Idempotency is checked before Story Eligibility because a previously
    # persisted override makes the shared evaluator return AVAILABLE.
    for existing in document["overrides"]:
        if (
            existing.get("active") is True
            and str((existing.get("target_ref") or {}).get("record_id") or "") == record_id
            and int((existing.get("current_position") or {}).get("book_number") or 0) == book_number
            and int((existing.get("current_position") or {}).get("chapter_number") or 0) == chapter_number
            and str(existing.get("requested_use") or "") == use
        ):
            return {
                "status": "already_authorized",
                "service": PROGRESSION_OVERRIDE_SERVICE_MARKER,
                "schema_version": PROGRESSION_OVERRIDE_SCHEMA_VERSION,
                "project_id": context.project_id,
                "override": deepcopy(existing),
                "revision": int(document.get("revision") or 0),
                "content_hash": str(document.get("content_hash") or ""),
                "execution_locks": _execution_locks(),
            }

    decision = story_eligibility_service.evaluate_story_eligibility_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
        candidate_ref={"record_id": record_id},
        requested_use=use,
        selected=True,
    )

    overridable = (
        decision.get("status") in {
            story_eligibility_service.STATUS_FUTURE,
            story_eligibility_service.STATUS_RESTRICTED,
        }
        or (
            decision.get("status") == story_eligibility_service.STATUS_CANON_INCOMPLETE
            and "approved_continuity_missing" in (decision.get("reason_codes") or [])
            and bool(decision.get("requirements"))
        )
    )
    if not overridable:
        raise ProgressionOverrideConflictError(
            "Story Eligibility did not return an overridable progression conflict."
        )
    if "request_explicit_override" not in (decision.get("allowed_actions") or []):
        # Missing Approved Continuity is still position-overridable when typed
        # requirements exist, even before the future Patch 34 writer exists.
        if not (
            "approved_continuity_missing" in (decision.get("reason_codes") or [])
            and bool(decision.get("requirements"))
        ):
            raise ProgressionOverrideConflictError(
                "Story Eligibility does not permit an explicit override for this state."
            )

    missing_snapshot = deepcopy(decision.get("missing_prerequisites") or [])
    if not missing_snapshot:
        missing_snapshot = [
            {
                "type": str(item.get("type") or ""),
                "target_ref": str(item.get("target_ref") or ""),
                "label": str(item.get("label") or ""),
                "state": "NOT_ESTABLISHED",
            }
            for item in decision.get("requirements") or []
        ]

    candidate = decision.get("candidate_ref") or {}
    record = {
        "override_id": "progression_override_" + uuid.uuid4().hex,
        "override_type": OVERRIDE_TYPE_ONE_TIME,
        "target_ref": {
            "record_id": record_id,
            "record_type": str(candidate.get("record_type") or ""),
            "label": str(candidate.get("label") or candidate.get("display_label") or ""),
        },
        "requested_use": use,
        "original_available_from_book": decision.get("available_from_book"),
        "current_position": {
            "book_number": book_number,
            "chapter_number": chapter_number,
        },
        "missing_requirement_snapshot": missing_snapshot,
        "completed_requirement_snapshot": deepcopy(
            decision.get("completed_prerequisites") or []
        ),
        "eligibility_status_before_override": str(decision.get("status") or ""),
        "eligibility_reason_codes_before_override": list(
            decision.get("reason_codes") or []
        ),
        "source_continuity_revision": str(
            decision.get("source_continuity_revision") or ""
        ),
        "source_continuity_hash": str(
            decision.get("source_continuity_hash") or ""
        ),
        "source_index_hash": str(decision.get("source_index_hash") or ""),
        "source_chapter_plan_revision": int(chapter.get("revision") or 0),
        "source_chapter_plan_hash": str(chapter.get("content_hash") or ""),
        "author_action": AUTHOR_ACTION_AUTHORIZE_EARLY_USE,
        "author_reason": str(reason or "").strip(),
        "created_at": utc_now_iso(),
        "active": True,
        "establishes_continuity": False,
    }

    document["overrides"].append(record)
    document["revision"] = int(document.get("revision") or 0) + 1
    document["updated_at"] = utc_now_iso()
    document["content_hash"] = _document_content_hash(document)
    _write_json_atomic(progression_override_path_for_context(context), document)

    # Re-evaluate through Story Eligibility after persistence. This proves that
    # the shared rules owner, not this service, grants the resulting availability.
    post_decision = story_eligibility_service.evaluate_story_eligibility_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
        candidate_ref={"record_id": record_id},
        requested_use=use,
        selected=True,
    )
    if not post_decision.get("override_applied") or not post_decision.get("available"):
        raise ProgressionOverrideConflictError(
            "Override persisted but Story Eligibility did not recognize it."
        )

    return {
        "status": "authorized",
        "service": PROGRESSION_OVERRIDE_SERVICE_MARKER,
        "schema_version": PROGRESSION_OVERRIDE_SCHEMA_VERSION,
        "project_id": context.project_id,
        "override": deepcopy(record),
        "revision": int(document["revision"]),
        "content_hash": str(document["content_hash"]),
        "eligibility": post_decision,
        "execution_locks": _execution_locks(),
    }


def _load_document(context: ProjectContext) -> dict[str, Any]:
    path = progression_override_path_for_context(context)
    if not path.exists():
        document = {
            "schema_version": PROGRESSION_OVERRIDE_SCHEMA_VERSION,
            "project_id": context.project_id,
            "revision": 0,
            "content_hash": "",
            "updated_at": "",
            "overrides": [],
        }
        document["content_hash"] = _document_content_hash(document)
        return {"document": document, "error": ""}

    try:
        payload = project_loader.read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"document": {}, "error": str(exc)}
    if not isinstance(payload, dict):
        return {"document": {}, "error": "Progression override root must be an object."}
    if payload.get("schema_version") != PROGRESSION_OVERRIDE_SCHEMA_VERSION:
        return {
            "document": {},
            "error": f"schema_version must be {PROGRESSION_OVERRIDE_SCHEMA_VERSION}",
        }
    if str(payload.get("project_id") or "") != context.project_id:
        return {"document": {}, "error": "project_id does not match current project."}
    try:
        revision = int(payload.get("revision") or 0)
    except (TypeError, ValueError):
        return {"document": {}, "error": "revision must be an integer."}
    if revision < 0:
        return {"document": {}, "error": "revision must not be negative."}
    overrides = payload.get("overrides")
    if not isinstance(overrides, list):
        return {"document": {}, "error": "overrides must be a list."}
    for index, item in enumerate(overrides):
        error = _validate_override_record(item, index=index)
        if error:
            return {"document": {}, "error": error}
    expected = _document_content_hash(payload)
    supplied_hash = str(payload.get("content_hash") or "")
    if not supplied_hash:
        return {"document": {}, "error": "content_hash is required for persisted progression overrides."}
    if supplied_hash != expected:
        return {"document": {}, "error": "content_hash does not match progression override content."}
    normalized = deepcopy(payload)
    normalized["revision"] = revision
    normalized["content_hash"] = expected
    return {"document": normalized, "error": ""}


def _validate_override_record(item: Any, *, index: int) -> str:
    prefix = f"overrides[{index}]"
    if not isinstance(item, dict):
        return f"{prefix} must be an object."
    target = item.get("target_ref")
    if not isinstance(target, dict) or not str(target.get("record_id") or "").strip():
        return f"{prefix}.target_ref.record_id is required."
    position = item.get("current_position")
    if not isinstance(position, dict):
        return f"{prefix}.current_position is required."
    try:
        if int(position.get("book_number") or 0) < 1:
            return f"{prefix}.current_position.book_number must be positive."
        if int(position.get("chapter_number") or 0) < 1:
            return f"{prefix}.current_position.chapter_number must be positive."
    except (TypeError, ValueError):
        return f"{prefix}.current_position must use integer values."
    use = str(item.get("requested_use") or "")
    if use not in story_eligibility_service.SUPPORTED_REQUESTED_USES:
        return f"{prefix}.requested_use is unsupported."
    if str(item.get("override_id") or "").strip() == "":
        return f"{prefix}.override_id is required."
    if str(item.get("override_type") or "") != OVERRIDE_TYPE_ONE_TIME:
        return f"{prefix}.override_type must be {OVERRIDE_TYPE_ONE_TIME}."
    if str(item.get("author_action") or "") != AUTHOR_ACTION_AUTHORIZE_EARLY_USE:
        return f"{prefix}.author_action must be {AUTHOR_ACTION_AUTHORIZE_EARLY_USE}."
    if not str(item.get("created_at") or "").strip():
        return f"{prefix}.created_at is required."
    if not str(item.get("source_chapter_plan_hash") or "").strip():
        return f"{prefix}.source_chapter_plan_hash is required."
    if item.get("active") not in (True, False):
        return f"{prefix}.active must be boolean."
    if item.get("establishes_continuity") is not False:
        return f"{prefix}.establishes_continuity must be false."
    missing = item.get("missing_requirement_snapshot", [])
    completed = item.get("completed_requirement_snapshot", [])
    if not isinstance(missing, list) or not isinstance(completed, list):
        return f"{prefix} requirement snapshots must be lists."
    return ""


def _document_content_hash(payload: dict[str, Any]) -> str:
    normalized = deepcopy(payload)
    normalized.pop("content_hash", None)
    normalized.pop("updated_at", None)
    return hashlib.sha256(
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _positive_int(value: Any, field_name: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ProgressionOverrideContractError(
            f"{field_name} must be an integer."
        ) from exc
    if result < 1:
        raise ProgressionOverrideContractError(
            f"{field_name} must be a positive integer."
        )
    return result


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _execution_locks() -> dict[str, bool]:
    return {
        "master_canon_mutation": True,
        "book_scope_mutation": True,
        "chapter_plan_mutation": True,
        "approved_continuity_writes": True,
        "requirement_establishment": True,
        "generation": True,
        "provider_execution": True,
        "prompt_builder": True,
    }
