"""
Project-local Story Eligibility and Unlock Requirements evaluator.

Patch 17 owns one deterministic backend rules boundary for explicit story
availability. It reads the derived Canon Index, optional author-supplied
availability boundaries, optional typed Unlock Requirements, and optional
Approved Continuity state.

This service does not select Book Canon, mutate Planner state, infer saga
progression, call a model/provider, generate prose, or establish continuity.
Only Approved Continuity may satisfy event/reveal establishment requirements.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.services import canon_index_service


STORY_ELIGIBILITY_SERVICE_MARKER = "project-story-eligibility-boundary-20260816"
STORY_ELIGIBILITY_SCHEMA_VERSION = "story_eligibility_v1"
UNLOCK_REQUIREMENTS_SCHEMA_VERSION = "unlock_requirements_v1"
APPROVED_CONTINUITY_SCHEMA_VERSION = "approved_continuity_v1"

UNLOCK_REQUIREMENTS_FILENAME = "unlock_requirements.json"
APPROVED_CONTINUITY_FILENAME = "approved_continuity.json"

STATUS_ACTIVE = "ACTIVE"
STATUS_AVAILABLE_TO_ADD = "AVAILABLE_TO_ADD"
STATUS_FUTURE = "FUTURE"
STATUS_RESTRICTED = "RESTRICTED"
STATUS_CANON_INCOMPLETE = "CANON_INCOMPLETE"
STATUS_STRUCTURAL_ERROR = "STRUCTURAL_ERROR"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"

SUPPORTED_REQUESTED_USES = frozenset(
    {
        "book_selection",
        "chapter_selection",
        "reveal",
        "event_placement",
    }
)
SUPPORTED_AVAILABILITY_MODES = frozenset(
    {
        "unrestricted",
        "explicitly_bounded",
        "event_driven",
        "continuity_driven",
    }
)
SUPPORTED_REQUIREMENT_TYPES = frozenset(
    {
        "event_established",
        "reveal_established",
    }
)
SUPPORTED_REQUIREMENT_POLICIES = frozenset({"ALL", "ANY"})


class StoryEligibilityError(RuntimeError):
    """Base error for Story Eligibility operations."""


def unlock_requirements_path(project_id: str) -> Path:
    manifest = project_loader.load_manifest(project_id)
    return unlock_requirements_path_for_context(build_project_context(manifest))


def unlock_requirements_path_for_context(context: ProjectContext) -> Path:
    return context.project_dir / "canon" / UNLOCK_REQUIREMENTS_FILENAME


def approved_continuity_path(project_id: str) -> Path:
    manifest = project_loader.load_manifest(project_id)
    return approved_continuity_path_for_context(build_project_context(manifest))


def approved_continuity_path_for_context(context: ProjectContext) -> Path:
    return context.runtime_data_dir / APPROVED_CONTINUITY_FILENAME


def get_story_eligibility_status(project_id: str) -> dict[str, Any]:
    """Return read-only capability/source status without evaluating a candidate."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    index_status = canon_index_service.get_index_status(project_id)
    unlock_path = unlock_requirements_path_for_context(context)
    continuity_path = approved_continuity_path_for_context(context)

    return {
        "status": "ok",
        "service": STORY_ELIGIBILITY_SERVICE_MARKER,
        "schema_version": STORY_ELIGIBILITY_SCHEMA_VERSION,
        "project_id": project_id,
        "canon_index_state": index_status.get("index_state"),
        "canon_index_fresh": bool(index_status.get("fresh")),
        "unlock_requirements": {
            "present": unlock_path.exists(),
            "path": _relative(unlock_path, context.project_dir),
        },
        "approved_continuity": {
            "present": continuity_path.exists(),
            "path": _relative(continuity_path, context.project_dir),
        },
        "supported_requested_uses": sorted(SUPPORTED_REQUESTED_USES),
        "supported_requirement_types": sorted(SUPPORTED_REQUIREMENT_TYPES),
        "execution_locks": _execution_locks(),
    }


def evaluate_story_eligibility(
    project_id: str,
    *,
    book_number: int,
    candidate_ref: dict[str, Any],
    requested_use: str,
    chapter_number: int | None = None,
    selected: bool = False,
) -> dict[str, Any]:
    """Evaluate one Canon record using explicit deterministic project state."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return evaluate_story_eligibility_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
        candidate_ref=candidate_ref,
        requested_use=requested_use,
        selected=selected,
    )


def evaluate_story_eligibility_for_context(
    context: ProjectContext,
    *,
    book_number: int,
    candidate_ref: dict[str, Any],
    requested_use: str,
    chapter_number: int | None = None,
    selected: bool = False,
) -> dict[str, Any]:
    """Deterministic evaluator shared by future Scope/Planner/Chapter callers."""

    book_number = _positive_int(book_number)
    chapter_number = _positive_int(chapter_number, allow_none=True)
    use = str(requested_use or "").strip()
    if use not in SUPPORTED_REQUESTED_USES:
        return _decision(
            context,
            status=STATUS_NOT_APPLICABLE,
            available=False,
            selected=selected,
            candidate=None,
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=["unsupported_requested_use"],
            allowed_actions=[],
            author_message="This record does not participate in the requested operation.",
        )

    record_id = str((candidate_ref or {}).get("record_id") or "").strip()
    if not record_id:
        return _decision(
            context,
            status=STATUS_STRUCTURAL_ERROR,
            available=False,
            selected=selected,
            candidate=None,
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=["missing_record_id"],
            allowed_actions=["repair_canon_structure"],
            author_message="The Canon reference is missing its stable record ID.",
        )

    try:
        index_status = canon_index_service.ensure_current_index(context.project_id)
    except canon_index_service.CanonIndexError as exc:
        return _decision(
            context,
            status=STATUS_STRUCTURAL_ERROR,
            available=False,
            selected=selected,
            candidate={"record_id": record_id},
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=["canon_index_unavailable"],
            allowed_actions=["repair_canon_structure"],
            author_message="The Canon Index is not available for deterministic eligibility evaluation.",
            diagnostics={"canon_index_error": str(exc)},
        )

    indexed = canon_index_service.get_record_by_id(context.project_id, record_id)
    if indexed.get("status") != "found":
        return _decision(
            context,
            status=STATUS_STRUCTURAL_ERROR,
            available=False,
            selected=selected,
            candidate={"record_id": record_id},
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=["unknown_record_id"],
            allowed_actions=["repair_canon_structure"],
            author_message="The referenced Canon record does not exist in the current Canon Index.",
            source_index_hash=str(index_status.get("index_content_hash") or ""),
        )

    record = dict(indexed["record"])
    supplied_type = str((candidate_ref or {}).get("record_type") or "").strip()
    indexed_type = str(record.get("record_type") or "").strip()
    if supplied_type and indexed_type and supplied_type != indexed_type:
        return _decision(
            context,
            status=STATUS_STRUCTURAL_ERROR,
            available=False,
            selected=selected,
            candidate=_candidate_payload(record),
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=["record_type_mismatch"],
            allowed_actions=["repair_canon_structure"],
            author_message="The stable Canon reference resolves to a different record type.",
            source_index_hash=str(index_status.get("index_content_hash") or ""),
        )

    unlock_state = _load_unlock_requirements(context)
    if unlock_state["error"]:
        return _decision(
            context,
            status=STATUS_CANON_INCOMPLETE,
            available=False,
            selected=selected,
            candidate=_candidate_payload(record),
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=["unlock_requirements_invalid"],
            allowed_actions=["repair_structured_rules"],
            author_message="Structured Unlock Requirements are invalid and must be repaired.",
            diagnostics={"unlock_requirements_error": unlock_state["error"]},
            source_index_hash=str(index_status.get("index_content_hash") or ""),
        )

    rule = dict(unlock_state["targets"].get(record_id) or {})
    rule_result = _normalize_rule(record, rule)
    if rule_result["error"]:
        return _decision(
            context,
            status=STATUS_CANON_INCOMPLETE,
            available=False,
            selected=selected,
            candidate=_candidate_payload(record),
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=[rule_result["reason_code"]],
            allowed_actions=["repair_structured_rules"],
            author_message=rule_result["author_message"],
            diagnostics={"rule_error": rule_result["error"]},
            source_index_hash=str(index_status.get("index_content_hash") or ""),
        )

    normalized_rule = rule_result["rule"]
    requirements = normalized_rule["requirements"]
    if requirements:
        validation = _validate_requirement_references(context.project_id, requirements)
        if validation["broken"]:
            return _decision(
                context,
                status=STATUS_STRUCTURAL_ERROR,
                available=False,
                selected=selected,
                candidate=_candidate_payload(record),
                requested_use=use,
                book_number=book_number,
                chapter_number=chapter_number,
                reason_codes=["broken_unlock_reference"],
                allowed_actions=["repair_canon_structure"],
                author_message="One or more Unlock Requirements reference missing Canon records.",
                missing_prerequisites=validation["broken"],
                requirements=requirements,
                requirement_policy=normalized_rule["requirement_policy"],
                override_history=normalized_rule["override_history"],
                source_index_hash=str(index_status.get("index_content_hash") or ""),
            )

    earliest_book = normalized_rule["available_from_book"]
    if earliest_book is not None and book_number < earliest_book:
        return _decision(
            context,
            status=STATUS_FUTURE,
            available=False,
            selected=selected,
            candidate=_candidate_payload(record),
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=["available_from_future_book"],
            allowed_actions=[
                "review_availability",
                "request_explicit_override",
                "revise_progression",
            ],
            author_message=f"Available from Book {earliest_book}; current position is Book {book_number}.",
            available_from_book=earliest_book,
            requirements=normalized_rule["requirements"],
            requirement_policy=normalized_rule["requirement_policy"],
            override_history=normalized_rule["override_history"],
            source_index_hash=str(index_status.get("index_content_hash") or ""),
        )

    protected_reveal = normalized_rule["protected_reveal"]
    availability_mode = normalized_rule["availability_mode"]

    if protected_reveal and use == "reveal" and not requirements:
        return _decision(
            context,
            status=STATUS_CANON_INCOMPLETE,
            available=False,
            selected=selected,
            candidate=_candidate_payload(record),
            requested_use=use,
            book_number=book_number,
            chapter_number=chapter_number,
            reason_codes=["protected_reveal_rule_incomplete"],
            allowed_actions=["repair_structured_rules"],
            author_message="The protected reveal has no typed Unlock Requirements.",
            available_from_book=earliest_book,
            requirements=requirements,
            requirement_policy=normalized_rule["requirement_policy"],
            override_history=normalized_rule["override_history"],
            source_index_hash=str(index_status.get("index_content_hash") or ""),
        )

    continuity_required = bool(
        requirements
        or availability_mode == "continuity_driven"
        or (protected_reveal and use == "reveal")
    )

    if continuity_required:
        continuity_state = _load_approved_continuity(context)
        if continuity_state["error"]:
            return _decision(
                context,
                status=STATUS_CANON_INCOMPLETE,
                available=False,
                selected=selected,
                candidate=_candidate_payload(record),
                requested_use=use,
                book_number=book_number,
                chapter_number=chapter_number,
                reason_codes=["approved_continuity_invalid"],
                allowed_actions=["repair_structured_rules"],
                author_message="Approved Continuity is invalid and cannot establish Unlock Requirements.",
                diagnostics={"approved_continuity_error": continuity_state["error"]},
                available_from_book=earliest_book,
                requirements=requirements,
                requirement_policy=normalized_rule["requirement_policy"],
                override_history=normalized_rule["override_history"],
                source_index_hash=str(index_status.get("index_content_hash") or ""),
            )
        if not continuity_state["present"]:
            return _decision(
                context,
                status=STATUS_CANON_INCOMPLETE,
                available=False,
                selected=selected,
                candidate=_candidate_payload(record),
                requested_use=use,
                book_number=book_number,
                chapter_number=chapter_number,
                reason_codes=["approved_continuity_missing"],
                allowed_actions=["establish_approved_continuity"],
                author_message="Approved Continuity is required before these Unlock Requirements can be evaluated.",
                available_from_book=earliest_book,
                requirements=requirements,
                requirement_policy=normalized_rule["requirement_policy"],
                override_history=normalized_rule["override_history"],
                source_index_hash=str(index_status.get("index_content_hash") or ""),
            )

        evaluation = _evaluate_requirements(
            requirements,
            normalized_rule["requirement_policy"],
            continuity_state["established"],
            book_number=book_number,
            chapter_number=chapter_number,
        )
        if requirements and not evaluation["satisfied"]:
            reason_codes = ["unlock_requirements_unmet"]
            if protected_reveal and use == "reveal":
                reason_codes.append("protected_reveal_locked")
            return _decision(
                context,
                status=STATUS_RESTRICTED,
                available=False,
                selected=selected,
                candidate=_candidate_payload(record),
                requested_use=use,
                book_number=book_number,
                chapter_number=chapter_number,
                reason_codes=reason_codes,
                allowed_actions=[
                    "review_missing_requirements",
                    "request_explicit_override",
                    "revise_progression",
                ],
                author_message=_missing_requirements_message(evaluation["missing"]),
                missing_prerequisites=evaluation["missing"],
                completed_prerequisites=evaluation["completed"],
                available_from_book=earliest_book,
                requirements=requirements,
                requirement_policy=normalized_rule["requirement_policy"],
                override_history=normalized_rule["override_history"],
                source_index_hash=str(index_status.get("index_content_hash") or ""),
                source_continuity_revision=continuity_state["revision"],
                source_continuity_hash=continuity_state["content_hash"],
            )

        continuation = {
            "completed_prerequisites": evaluation["completed"],
            "source_continuity_revision": continuity_state["revision"],
            "source_continuity_hash": continuity_state["content_hash"],
        }
    else:
        continuation = {}

    status = STATUS_ACTIVE if selected else STATUS_AVAILABLE_TO_ADD
    return _decision(
        context,
        status=status,
        available=True,
        selected=selected,
        candidate=_candidate_payload(record),
        requested_use=use,
        book_number=book_number,
        chapter_number=chapter_number,
        reason_codes=[],
        allowed_actions=["continue"] if selected else [_available_action(use)],
        author_message=(
            "Active at the current story position."
            if selected
            else "Available under the current explicit story constraints."
        ),
        available_from_book=earliest_book,
        requirements=requirements,
        requirement_policy=normalized_rule["requirement_policy"],
        override_history=normalized_rule["override_history"],
        source_index_hash=str(index_status.get("index_content_hash") or ""),
        **continuation,
    )


def _load_unlock_requirements(context: ProjectContext) -> dict[str, Any]:
    path = unlock_requirements_path_for_context(context)
    if not path.exists():
        return {
            "present": False,
            "targets": {},
            "content_hash": "",
            "error": "",
        }
    try:
        payload = project_loader.read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"present": True, "targets": {}, "content_hash": "", "error": str(exc)}

    if not isinstance(payload, dict):
        return {"present": True, "targets": {}, "content_hash": "", "error": "root must be an object"}
    if payload.get("schema_version") != UNLOCK_REQUIREMENTS_SCHEMA_VERSION:
        return {
            "present": True,
            "targets": {},
            "content_hash": _json_hash(payload),
            "error": f"schema_version must be {UNLOCK_REQUIREMENTS_SCHEMA_VERSION}",
        }
    targets = payload.get("targets", {})
    if not isinstance(targets, dict):
        return {
            "present": True,
            "targets": {},
            "content_hash": _json_hash(payload),
            "error": "targets must be an object keyed by stable record ID",
        }
    return {
        "present": True,
        "targets": targets,
        "content_hash": _json_hash(payload),
        "error": "",
    }


def _load_approved_continuity(context: ProjectContext) -> dict[str, Any]:
    path = approved_continuity_path_for_context(context)
    if not path.exists():
        return {
            "present": False,
            "established": [],
            "revision": "",
            "content_hash": "",
            "error": "",
        }
    try:
        payload = project_loader.read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "present": True,
            "established": [],
            "revision": "",
            "content_hash": "",
            "error": str(exc),
        }

    if not isinstance(payload, dict):
        return {
            "present": True,
            "established": [],
            "revision": "",
            "content_hash": "",
            "error": "root must be an object",
        }
    if payload.get("schema_version") != APPROVED_CONTINUITY_SCHEMA_VERSION:
        return {
            "present": True,
            "established": [],
            "revision": str(payload.get("revision") or ""),
            "content_hash": _json_hash(payload),
            "error": f"schema_version must be {APPROVED_CONTINUITY_SCHEMA_VERSION}",
        }
    established = payload.get("established", [])
    if not isinstance(established, list):
        return {
            "present": True,
            "established": [],
            "revision": str(payload.get("revision") or ""),
            "content_hash": _json_hash(payload),
            "error": "established must be a list",
        }

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(established):
        if not isinstance(item, dict):
            return {
                "present": True,
                "established": [],
                "revision": str(payload.get("revision") or ""),
                "content_hash": _json_hash(payload),
                "error": f"established[{index}] must be an object",
            }
        requirement_type = str(item.get("type") or "").strip()
        target_ref = str(item.get("target_ref") or "").strip()
        if requirement_type not in SUPPORTED_REQUIREMENT_TYPES or not target_ref:
            return {
                "present": True,
                "established": [],
                "revision": str(payload.get("revision") or ""),
                "content_hash": _json_hash(payload),
                "error": f"established[{index}] has unsupported type or missing target_ref",
            }
        normalized.append(
            {
                "type": requirement_type,
                "target_ref": target_ref,
                "book_number": _coerce_optional_positive_int(item.get("book_number")),
                "chapter_number": _coerce_optional_positive_int(item.get("chapter_number")),
            }
        )
    return {
        "present": True,
        "established": normalized,
        "revision": str(payload.get("revision") or ""),
        "content_hash": _json_hash(payload),
        "error": "",
    }


def _normalize_rule(record: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    index_available_raw = record.get("available_from_book")
    index_available = _coerce_optional_positive_int(index_available_raw)
    if index_available_raw not in (None, "") and index_available is None:
        return _rule_error(
            "invalid_available_from_book",
            "Canon Index available_from_book must be a positive integer",
            "The Canon record has an invalid Available From boundary.",
        )
    rule_available_raw = rule.get("available_from_book")
    rule_available = _coerce_optional_positive_int(rule_available_raw)
    if rule_available_raw not in (None, "") and rule_available is None:
        return _rule_error(
            "invalid_available_from_book",
            "available_from_book must be a positive integer",
            "The record has an invalid Available From boundary.",
        )
    if index_available is not None and rule_available is not None and index_available != rule_available:
        return _rule_error(
            "availability_boundary_conflict",
            "unlock rule conflicts with Canon Index available_from_book",
            "Structured Unlock Requirements conflict with the Canon Available From value.",
        )

    available_from_book = index_available if index_available is not None else rule_available
    availability_mode = str(rule.get("availability_mode") or "").strip()
    if not availability_mode:
        if available_from_book is not None:
            availability_mode = "explicitly_bounded"
        elif rule.get("requirements"):
            availability_mode = "event_driven"
        else:
            availability_mode = "unrestricted"
    if availability_mode not in SUPPORTED_AVAILABILITY_MODES:
        return _rule_error(
            "invalid_availability_mode",
            f"unsupported availability_mode: {availability_mode}",
            "The record has an unsupported availability mode.",
        )

    requirements_raw = rule.get("requirements", [])
    if requirements_raw is None:
        requirements_raw = []
    if not isinstance(requirements_raw, list):
        return _rule_error(
            "invalid_unlock_requirements",
            "requirements must be a list",
            "Unlock Requirements must be a structured list.",
        )

    requirements: list[dict[str, Any]] = []
    for index, requirement in enumerate(requirements_raw):
        if not isinstance(requirement, dict):
            return _rule_error(
                "invalid_unlock_requirements",
                f"requirements[{index}] must be an object",
                "One or more Unlock Requirements are malformed.",
            )
        requirement_type = str(requirement.get("type") or "").strip()
        target_ref = str(requirement.get("target_ref") or "").strip()
        if requirement_type not in SUPPORTED_REQUIREMENT_TYPES:
            return _rule_error(
                "unsupported_unlock_requirement_type",
                f"requirements[{index}] type is not supported: {requirement_type}",
                "An Unlock Requirement uses a type that this migration phase does not support.",
            )
        if not target_ref:
            return _rule_error(
                "invalid_unlock_requirements",
                f"requirements[{index}] target_ref is required",
                "An Unlock Requirement is missing its stable Canon reference.",
            )
        requirements.append(
            {
                "type": requirement_type,
                "target_ref": target_ref,
                "label": str(requirement.get("label") or "").strip(),
            }
        )

    policy = str(rule.get("requirement_policy") or "").strip().upper()
    if requirements and not policy:
        return _rule_error(
            "missing_requirement_policy",
            "requirement_policy is required when requirements are present",
            "Unlock Requirements need an explicit ALL or ANY policy.",
        )
    if not policy:
        policy = "ALL"
    if policy not in SUPPORTED_REQUIREMENT_POLICIES:
        return _rule_error(
            "invalid_requirement_policy",
            f"unsupported requirement_policy: {policy}",
            "Unlock Requirements must use an ALL or ANY policy.",
        )

    if availability_mode in {"event_driven", "continuity_driven"} and not requirements:
        return _rule_error(
            "missing_unlock_requirements",
            f"{availability_mode} availability requires typed requirements",
            "The availability mode requires typed Unlock Requirements.",
        )

    protected_reveal = bool(rule.get("protected_reveal", False))
    override_history = rule.get("override_history", [])
    if override_history is None:
        override_history = []
    if not isinstance(override_history, list):
        return _rule_error(
            "invalid_override_history",
            "override_history must be a list",
            "Stored progression override history is malformed.",
        )

    return {
        "error": "",
        "reason_code": "",
        "author_message": "",
        "rule": {
            "availability_mode": availability_mode,
            "available_from_book": available_from_book,
            "requirement_policy": policy,
            "requirements": requirements,
            "protected_reveal": protected_reveal,
            # Patch 17 exposes history but never treats a caller boolean as an
            # override. A later controlled Planner action owns audited writes.
            "override_history": [dict(item) for item in override_history if isinstance(item, dict)],
        },
    }


def _validate_requirement_references(project_id: str, requirements: list[dict[str, Any]]) -> dict[str, Any]:
    broken: list[dict[str, Any]] = []
    for requirement in requirements:
        resolved = canon_index_service.get_record_by_id(project_id, requirement["target_ref"])
        if resolved.get("status") != "found":
            broken.append(
                {
                    **requirement,
                    "state": "BROKEN_REFERENCE",
                }
            )
    return {"broken": broken}


def _evaluate_requirements(
    requirements: list[dict[str, Any]],
    policy: str,
    established: list[dict[str, Any]],
    *,
    book_number: int,
    chapter_number: int | None,
) -> dict[str, Any]:
    established_keys = {
        (item["type"], item["target_ref"])
        for item in established
        if _established_at_or_before(
            item,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    }

    completed: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for requirement in requirements:
        target = completed if (requirement["type"], requirement["target_ref"]) in established_keys else missing
        target.append(
            {
                **requirement,
                "state": "ESTABLISHED" if target is completed else "NOT_ESTABLISHED",
            }
        )

    if not requirements:
        satisfied = True
    elif policy == "ANY":
        satisfied = bool(completed)
    else:
        satisfied = not missing
    return {
        "satisfied": satisfied,
        "completed": completed,
        "missing": missing,
    }


def _established_at_or_before(
    item: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int | None,
) -> bool:
    established_book = item.get("book_number")
    established_chapter = item.get("chapter_number")
    if established_book is None:
        return True
    if established_book < book_number:
        return True
    if established_book > book_number:
        return False
    if chapter_number is None or established_chapter is None:
        return True
    return established_chapter <= chapter_number


def _decision(
    context: ProjectContext,
    *,
    status: str,
    available: bool,
    selected: bool,
    candidate: dict[str, Any] | None,
    requested_use: str,
    book_number: int,
    chapter_number: int | None,
    reason_codes: list[str],
    allowed_actions: list[str],
    author_message: str,
    missing_prerequisites: list[dict[str, Any]] | None = None,
    completed_prerequisites: list[dict[str, Any]] | None = None,
    available_from_book: int | None = None,
    requirements: list[dict[str, Any]] | None = None,
    requirement_policy: str = "ALL",
    override_history: list[dict[str, Any]] | None = None,
    source_index_hash: str = "",
    source_continuity_revision: str = "",
    source_continuity_hash: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "service": STORY_ELIGIBILITY_SERVICE_MARKER,
        "schema_version": STORY_ELIGIBILITY_SCHEMA_VERSION,
        "project_id": context.project_id,
        "available": bool(available),
        "selected": bool(selected),
        "in_book": bool(selected and requested_use == "book_selection"),
        "candidate_ref": candidate,
        "requested_use": requested_use,
        "current_position": {
            "book_number": book_number,
            "chapter_number": chapter_number,
        },
        "available_from_book": available_from_book,
        "requirement_policy": requirement_policy,
        "requirements": list(requirements or []),
        "completed_prerequisites": list(completed_prerequisites or []),
        "missing_prerequisites": list(missing_prerequisites or []),
        "reason_codes": list(reason_codes),
        "allowed_actions": list(allowed_actions),
        "author_message": author_message,
        "override_history": list(override_history or []),
        "override_applied": False,
        "source_index_hash": source_index_hash,
        "source_continuity_revision": source_continuity_revision,
        "source_continuity_hash": source_continuity_hash,
        "execution_locks": _execution_locks(),
        "diagnostics": dict(diagnostics or {}),
    }


def _candidate_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": str(record.get("internal_id") or ""),
        "record_type": str(record.get("record_type") or ""),
        "label": str(record.get("display_label") or ""),
        "record_group_id": str(record.get("record_group_id") or ""),
        "story_code": str(record.get("story_code") or ""),
    }


def _available_action(requested_use: str) -> str:
    return {
        "book_selection": "add_to_book",
        "chapter_selection": "select_for_chapter",
        "reveal": "use_reveal",
        "event_placement": "place_event",
    }.get(requested_use, "continue")


def _missing_requirements_message(missing: list[dict[str, Any]]) -> str:
    count = len(missing)
    if count == 1:
        return "1 Unlock Requirement is not yet established in Approved Continuity."
    return f"{count} Unlock Requirements are not yet established in Approved Continuity."


def _rule_error(reason_code: str, error: str, author_message: str) -> dict[str, Any]:
    return {
        "error": error,
        "reason_code": reason_code,
        "author_message": author_message,
        "rule": {},
    }


def _positive_int(value: Any, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    parsed = _coerce_optional_positive_int(value)
    if parsed is None:
        raise ValueError("book_number/chapter_number must be a positive integer")
    return parsed


def _coerce_optional_positive_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _execution_locks() -> dict[str, bool]:
    return {
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "planner_model_enabled": False,
        "book_scope_mutation_enabled": False,
        "approved_continuity_write_enabled": False,
        "audited_override_write_enabled": False,
    }
