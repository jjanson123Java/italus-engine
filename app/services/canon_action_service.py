"""
Canon action service.

Owns author-facing canon setup actions. This layer mutates only project-scoped
wizard/manifest state. It does not modify legacy root canon files and does not
call generation runtime or LLM providers.
"""

from __future__ import annotations

from typing import Any

from app.projects import project_loader
from app.projects.project_manifest import (
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_CANON_IN_PROGRESS,
    LIFECYCLE_DRAFT_SETUP,
    LIFECYCLE_READY_FOR_WORKSPACE,
    utc_now_iso,
)
from app.services import (
    canon_authoring_service,
    canon_setup_service,
    canon_validation_service,
)


REFERENCE_DETECTED = "REFERENCE_DETECTED"
REFERENCE_APPROVED = "REFERENCE_APPROVED"
PROJECT_LOCAL_DETECTED = "PROJECT_LOCAL_DETECTED"
PROJECT_LOCAL_APPROVED = "PROJECT_LOCAL_APPROVED"
GENERATED = "GENERATED"
APPROVED = "APPROVED"
LOCKED = "LOCKED"
OPTIONAL = "OPTIONAL"

APPROVABLE_REFERENCE_STATUSES = {
    REFERENCE_DETECTED,
    REFERENCE_APPROVED,
}

ACCEPTED_COMPLETION_STATUSES = {
    REFERENCE_APPROVED,
    PROJECT_LOCAL_APPROVED,
    GENERATED,
    APPROVED,
    LOCKED,
    OPTIONAL,
}


class CanonActionConflictError(RuntimeError):
    """Raised when lifecycle state or canon status blocks an action."""


class CanonItemNotFoundError(KeyError):
    """Raised when a canon_id is not part of the resolved project template."""


def approve_reference(project_id: str, canon_id: str) -> dict[str, Any]:
    """Approve one detected reference canon item for this project.

    Runtime knowledge packs are approved as reference packs: compressed,
    generated support artifacts used for prompt-size control. They are not
    recorded as primary authored canon.
    """

    manifest = project_loader.load_manifest(project_id)
    _assert_can_edit_canon(manifest.lifecycle_state)

    setup = canon_setup_service.get_canon_setup(project_id)
    item = _find_canon_item(setup, canon_id)
    wizard_status = _current_status(setup, canon_id, item)

    if wizard_status not in APPROVABLE_REFERENCE_STATUSES:
        raise CanonActionConflictError(
            f"Canon item {canon_id} has status {wizard_status}; expected {REFERENCE_DETECTED}."
        )

    wizard_state = dict(setup.get("wizard_state") or {})
    statuses = dict(wizard_state.get("canon_set_statuses") or {})
    statuses[canon_id] = REFERENCE_APPROVED
    wizard_state["canon_set_statuses"] = statuses

    approved_refs = dict(wizard_state.get("approved_canon_refs") or {})
    approved_refs[canon_id] = {
        "approved_at": utc_now_iso(),
        "approval_type": _approval_type_for_item(item),
        "role": item.get("role"),
        "source_strategy": item.get("source_strategy"),
        "source_files": item.get("source_files", []),
    }
    wizard_state["approved_canon_refs"] = approved_refs
    wizard_state["last_saved_at"] = utc_now_iso()

    project_loader.save_wizard_state(project_id, wizard_state)
    return _with_message(
        canon_setup_service.get_canon_setup(project_id),
        f"Approved reference canon item: {canon_id}.",
    )


def approve_all_references(project_id: str) -> dict[str, Any]:
    """Approve every detected reference canon item in the current setup."""

    manifest = project_loader.load_manifest(project_id)
    _assert_can_edit_canon(manifest.lifecycle_state)

    setup = canon_setup_service.get_canon_setup(project_id)
    wizard_state = dict(setup.get("wizard_state") or {})
    statuses = dict(wizard_state.get("canon_set_statuses") or {})
    approved_refs = dict(wizard_state.get("approved_canon_refs") or {})

    approved_count = 0
    now = utc_now_iso()

    for item in _iter_canon_items(setup):
        canon_id = item["canon_id"]
        wizard_status = _current_status(setup, canon_id, item)
        if wizard_status in APPROVABLE_REFERENCE_STATUSES:
            statuses[canon_id] = REFERENCE_APPROVED
            approved_refs[canon_id] = {
                "approved_at": now,
                "approval_type": _approval_type_for_item(item),
                "role": item.get("role"),
                "source_strategy": item.get("source_strategy"),
                "source_files": item.get("source_files", []),
            }
            approved_count += 1

    wizard_state["canon_set_statuses"] = statuses
    wizard_state["approved_canon_refs"] = approved_refs
    wizard_state["last_saved_at"] = now
    project_loader.save_wizard_state(project_id, wizard_state)

    return _with_message(
        canon_setup_service.get_canon_setup(project_id),
        f"Approved {approved_count} detected reference canon item(s).",
    )


def complete_canon_setup(project_id: str) -> dict[str, Any]:
    """Mark canon setup complete when all required canon items are accepted."""

    manifest = project_loader.load_manifest(project_id)
    _assert_can_edit_canon(manifest.lifecycle_state)

    authoring_status = canon_authoring_service.get_canon_authoring_status(
        project_id
    )
    if not authoring_status.get("all_required_sections_complete"):
        completed = int(
            authoring_status.get("completed_required_section_count") or 0
        )
        required = int(
            authoring_status.get("required_section_count") or 0
        )
        incomplete_sections = [
            str(section.get("section_id") or "")
            for section in authoring_status.get("sections") or []
            if section.get("required") and not section.get("complete")
        ]
        detail = ", ".join(
            section_id
            for section_id in incomplete_sections
            if section_id
        )
        suffix = f": {detail}" if detail else ""
        raise CanonActionConflictError(
            "Canon setup cannot complete until all required author-facing "
            f"sections are complete ({completed}/{required}){suffix}."
        )

    validation = canon_validation_service.get_canon_validation_status(
        project_id
    )
    if not validation.get("ready_for_packet_generation"):
        missing_sections = [
            str(item.get("section_id") or "")
            for item in validation.get("missing_required_sections") or []
            if item.get("section_id")
        ]
        missing_sources = [
            str(
                item.get("section_id")
                or item.get("expected_file")
                or ""
            )
            for item in validation.get("missing_rendered_sources") or []
            if (
                item.get("section_id")
                or item.get("expected_file")
            )
        ]
        issue_codes = [
            str(item.get("code") or "")
            for item in validation.get("issues") or []
            if item.get("code")
        ]
        blockers = _unique(
            missing_sections + missing_sources + issue_codes
        )
        detail = ", ".join(blockers)
        suffix = f": {detail}" if detail else ""
        raise CanonActionConflictError(
            "Canon setup cannot complete until required project-local "
            f"canon and Markdown sources are current{suffix}."
        )

    setup = canon_setup_service.get_canon_setup(project_id)
    wizard_state = dict(setup.get("wizard_state") or {})

    now = utc_now_iso()
    completed_steps = _unique(list(wizard_state.get("completed_steps") or []) + ["canon_groups", "canon_setup"])
    incomplete_steps = [
        step for step in list(wizard_state.get("incomplete_steps") or [])
        if step not in {"canon_groups", "canon_setup"}
    ]
    blocking_requirements = [
        item for item in list(wizard_state.get("blocking_requirements") or [])
        if item != "canon_setup"
    ]

    wizard_state.update(
        {
            "current_phase": "WORKSPACE_GATE",
            "current_step_id": "workspace",
            "completed_steps": completed_steps,
            "incomplete_steps": incomplete_steps,
            "resume_target": "workspace",
            "can_enter_workspace": True,
            "blocking_requirements": blocking_requirements,
            "lifecycle_state": LIFECYCLE_READY_FOR_WORKSPACE,
            "canon_setup_completed": True,
            "canon_setup_completed_at": now,
            "last_saved_at": now,
            "last_opened_at": now,
        }
    )

    manifest.lifecycle_state = LIFECYCLE_READY_FOR_WORKSPACE
    manifest.touch()

    project_loader.save_manifest(manifest)
    project_loader.save_wizard_state(project_id, wizard_state)

    payload = canon_setup_service.get_canon_setup(project_id)
    payload["message"] = "Canon setup complete. Project is ready for workspace entry."
    return payload


def _assert_can_edit_canon(lifecycle_state: str) -> None:
    if lifecycle_state == LIFECYCLE_ARCHIVED:
        raise CanonActionConflictError("Archived projects must be restored before canon actions.")
    if lifecycle_state not in {LIFECYCLE_DRAFT_SETUP, LIFECYCLE_CANON_IN_PROGRESS}:
        raise CanonActionConflictError(
            f"Project state {lifecycle_state} cannot perform canon setup actions."
        )


def _iter_canon_items(setup: dict[str, Any]):
    for group in setup.get("canon_groups") or []:
        for item in group.get("items") or []:
            yield item


def _find_canon_item(setup: dict[str, Any], canon_id: str) -> dict[str, Any]:
    for item in _iter_canon_items(setup):
        if item.get("canon_id") == canon_id:
            return item
    raise CanonItemNotFoundError(f"Canon item not found: {canon_id}")


def _current_status(setup: dict[str, Any], canon_id: str, item: dict[str, Any]) -> str:
    wizard_state = setup.get("wizard_state") or {}
    statuses = wizard_state.get("canon_set_statuses") or {}
    return str(statuses.get(canon_id) or item.get("wizard_status") or item.get("status") or "UNKNOWN")


def _approval_type_for_item(item: dict[str, Any]) -> str:
    if item.get("role") == "runtime_context_pack":
        return "reference_runtime_pack"
    return "reference_canon"


def _with_message(payload: dict[str, Any], message: str) -> dict[str, Any]:
    payload["message"] = message
    return payload


def _unique(values: list[Any]) -> list[Any]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
