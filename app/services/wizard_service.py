"""
Wizard state service for project setup and canon setup.

The first backend pass creates durable wizard state only. Canon template
completion and reset behavior are implemented in later controlled phases.
"""

from __future__ import annotations

from typing import Any

from app.projects.project_manifest import (
    LIFECYCLE_CANON_IN_PROGRESS,
    LIFECYCLE_DRAFT_SETUP,
    utc_now_iso,
)


def create_initial_wizard_state(project_id: str, *, continue_to_canon: bool = False) -> dict[str, Any]:
    lifecycle_state = LIFECYCLE_CANON_IN_PROGRESS if continue_to_canon else LIFECYCLE_DRAFT_SETUP
    current_phase = "CANON_WIZARD" if continue_to_canon else "PROJECT_METADATA"
    current_step_id = "genre_template" if continue_to_canon else "project_metadata"

    return {
        "project_id": project_id,
        "current_phase": current_phase,
        "current_step_id": current_step_id,
        "completed_steps": ["project_metadata"] if continue_to_canon else [],
        "incomplete_steps": ["genre_template", "canon_sets"] if continue_to_canon else ["project_metadata"],
        "required_canon_sets": [],
        "canon_set_statuses": {},
        "canon_reset_pending": False,
        "reset_canon_set_ids": [],
        "last_saved_at": utc_now_iso(),
        "last_opened_at": utc_now_iso(),
        "resume_target": current_step_id,
        "can_enter_workspace": False,
        "blocking_requirements": ["canon_setup"],
        "lifecycle_state": lifecycle_state,
    }


def resolve_resume_target(manifest: dict[str, Any], wizard_state: dict[str, Any] | None = None) -> dict[str, Any]:
    wizard_state = wizard_state or {}
    lifecycle_state = manifest.get("lifecycle_state", LIFECYCLE_DRAFT_SETUP)

    if lifecycle_state == "ARCHIVED":
        target = "archived_browser"
    elif lifecycle_state == "DRAFT_SETUP":
        target = wizard_state.get("resume_target") or "project_metadata"
    elif lifecycle_state == "CANON_IN_PROGRESS":
        target = wizard_state.get("resume_target") or "genre_template"
    elif lifecycle_state in {"READY_FOR_WORKSPACE", "ACTIVE"}:
        target = "workspace"
    else:
        target = "project_metadata"

    return {
        "project_id": manifest.get("project_id"),
        "lifecycle_state": lifecycle_state,
        "resume_target": target,
        "can_enter_workspace": lifecycle_state in {"READY_FOR_WORKSPACE", "ACTIVE"},
    }
