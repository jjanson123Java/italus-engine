"""
Project lifecycle service.

This service owns project setup persistence only. It does not call the existing
Italus generation runtime or mutate existing flat data files.
"""

from __future__ import annotations

from typing import Any

from app.projects.project_manifest import (
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_CANON_IN_PROGRESS,
    LIFECYCLE_DRAFT_SETUP,
    LIFECYCLE_READY_FOR_WORKSPACE,
    LIFECYCLE_ACTIVE,
    ProjectManifest,
    utc_now_iso,
)
from app.projects import project_loader
from app.services.budget_service import estimate_project_budget
from app.services.wizard_service import create_initial_wizard_state, resolve_resume_target
from app.services import project_runtime_storage_service


EDITABLE_PROJECT_FIELDS = {
    "project_name",
    "project_kind",
    "series_name",
    "book_count",
    "chapters_per_book",
    "target_words_per_chapter",
    "target_words_per_book",
    "target_total_words",
    "token_budget_total",
    "token_budget_per_generation",
    "genre",
    "subgenre",
    "template_id",
    "engine_id",
    "ai_provider",
}

EDITABLE_LIFECYCLE_STATES = {
    LIFECYCLE_DRAFT_SETUP,
    LIFECYCLE_CANON_IN_PROGRESS,
}


class ProjectStateConflictError(RuntimeError):
    """Raised when a project state blocks the requested lifecycle mutation."""


def create_project(payload: dict[str, Any], *, continue_to_canon: bool = False) -> dict[str, Any]:
    manifest = ProjectManifest.from_payload(payload)
    if continue_to_canon:
        manifest.lifecycle_state = LIFECYCLE_CANON_IN_PROGRESS
    else:
        manifest.lifecycle_state = LIFECYCLE_DRAFT_SETUP

    budget_plan = estimate_project_budget(manifest.to_dict())
    wizard_state = create_initial_wizard_state(
        manifest.project_id,
        continue_to_canon=continue_to_canon,
    )

    project_loader.project_dir(manifest.project_id, create=True)
    project_loader.save_manifest(manifest)
    project_runtime_storage_service.ensure_runtime_storage_for_manifest(manifest)
    project_loader.save_budget_plan(manifest.project_id, budget_plan)
    project_loader.save_wizard_state(manifest.project_id, wizard_state)

    return project_payload(manifest, budget_plan=budget_plan, wizard_state=wizard_state)


def update_project(
    project_id: str,
    payload: dict[str, Any],
    *,
    continue_to_canon: bool = False,
) -> dict[str, Any]:
    """Update an existing setup-stage project without changing its project_id."""

    manifest = project_loader.load_manifest(project_id)
    if manifest.lifecycle_state == LIFECYCLE_ARCHIVED:
        raise ProjectStateConflictError("Archived projects must be restored before editing.")
    if manifest.lifecycle_state not in EDITABLE_LIFECYCLE_STATES:
        raise ProjectStateConflictError(
            f"Project state {manifest.lifecycle_state} cannot be edited by the setup route."
        )

    existing_created_at = manifest.created_at
    existing_project_id = manifest.project_id
    updated_payload = manifest.to_dict()

    for field_name in EDITABLE_PROJECT_FIELDS:
        if field_name in payload and payload[field_name] is not None:
            updated_payload[field_name] = payload[field_name]

    updated_payload["project_id"] = existing_project_id
    updated_payload["created_at"] = existing_created_at
    updated_payload["previous_state_before_archive"] = manifest.previous_state_before_archive

    updated_manifest = ProjectManifest.from_payload(updated_payload)
    updated_manifest.project_id = existing_project_id
    updated_manifest.created_at = existing_created_at
    updated_manifest.previous_state_before_archive = manifest.previous_state_before_archive
    updated_manifest.lifecycle_state = (
        LIFECYCLE_CANON_IN_PROGRESS if continue_to_canon else manifest.lifecycle_state
    )
    updated_manifest.touch()

    budget_plan = estimate_project_budget(updated_manifest.to_dict())
    wizard_state = _updated_wizard_state(
        project_id=existing_project_id,
        current_wizard_state=project_loader.load_wizard_state(existing_project_id),
        lifecycle_state=updated_manifest.lifecycle_state,
        continue_to_canon=continue_to_canon,
    )

    project_loader.save_manifest(updated_manifest)
    project_loader.save_budget_plan(existing_project_id, budget_plan)
    project_loader.save_wizard_state(existing_project_id, wizard_state)

    return project_payload(updated_manifest, budget_plan=budget_plan, wizard_state=wizard_state)


def estimate_budget(payload: dict[str, Any]) -> dict[str, Any]:
    return estimate_project_budget(payload)


def get_project(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    return project_payload(
        manifest,
        budget_plan=project_loader.load_budget_plan(project_id),
        wizard_state=project_loader.load_wizard_state(project_id),
    )


def list_projects(state: str | None = None) -> list[dict[str, Any]]:
    requested_state = str(state or "all").lower()
    projects: list[dict[str, Any]] = []

    for project_id in project_loader.list_project_ids():
        manifest = project_loader.load_manifest(project_id)
        include = _include_manifest(manifest.lifecycle_state, requested_state)
        if not include:
            continue

        projects.append(
            project_payload(
                manifest,
                budget_plan=project_loader.load_budget_plan(project_id),
                wizard_state=project_loader.load_wizard_state(project_id),
            )
        )

    return sorted(projects, key=lambda item: item["manifest"].get("updated_at", ""), reverse=True)


def archive_project(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)

    if manifest.lifecycle_state != LIFECYCLE_ARCHIVED:
        manifest.previous_state_before_archive = manifest.lifecycle_state
        manifest.lifecycle_state = LIFECYCLE_ARCHIVED

    archive_state = {
        "project_id": manifest.project_id,
        "archived_at": utc_now_iso(),
        "previous_state_before_archive": manifest.previous_state_before_archive or LIFECYCLE_DRAFT_SETUP,
    }

    project_loader.save_manifest(manifest)
    project_loader.save_archive_state(project_id, archive_state)

    return project_payload(
        manifest,
        budget_plan=project_loader.load_budget_plan(project_id),
        wizard_state=project_loader.load_wizard_state(project_id),
        archive_state=archive_state,
    )


def restore_project(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)

    if manifest.lifecycle_state == LIFECYCLE_ARCHIVED:
        manifest.lifecycle_state = manifest.previous_state_before_archive or LIFECYCLE_DRAFT_SETUP
        manifest.previous_state_before_archive = None
        project_loader.save_manifest(manifest)

    return get_project(project_id)


def delete_project(project_id: str) -> dict[str, Any]:
    """Permanently delete an unfinished project-local project tree."""

    manifest = project_loader.load_manifest(project_id)
    if manifest.lifecycle_state not in EDITABLE_LIFECYCLE_STATES:
        raise ProjectStateConflictError(
            "Only projects still in Draft Setup or Canon Setup in Progress can be deleted."
        )

    project_name = manifest.project_name
    lifecycle_state = manifest.lifecycle_state
    project_loader.delete_project_directory(project_id)

    return {
        "status": "deleted",
        "project_id": project_id,
        "project_name": project_name,
        "lifecycle_state": lifecycle_state,
        "deleted_storage": f"data/projects/{project_id}",
    }


def project_payload(
    manifest: ProjectManifest,
    *,
    budget_plan: dict[str, Any] | None = None,
    wizard_state: dict[str, Any] | None = None,
    archive_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_dict = manifest.to_dict()
    resume = resolve_resume_target(manifest_dict, wizard_state)

    return {
        "project_id": manifest.project_id,
        "status": "ok",
        "manifest": manifest_dict,
        "budget_plan": budget_plan or {},
        "wizard_state": wizard_state or {},
        "archive_state": archive_state or {},
        "resume": resume,
    }


def _updated_wizard_state(
    *,
    project_id: str,
    current_wizard_state: dict[str, Any] | None,
    lifecycle_state: str,
    continue_to_canon: bool,
) -> dict[str, Any]:
    wizard_state = current_wizard_state or create_initial_wizard_state(project_id)

    if continue_to_canon or lifecycle_state == LIFECYCLE_CANON_IN_PROGRESS:
        wizard_state.update(
            {
                "current_phase": "CANON_WIZARD",
                "current_step_id": "genre_template",
                "completed_steps": _with_unique(wizard_state.get("completed_steps", []), "project_metadata"),
                "incomplete_steps": [
                    step
                    for step in _with_unique(wizard_state.get("incomplete_steps", []), "genre_template")
                    if step != "project_metadata"
                ],
                "resume_target": "genre_template",
                "lifecycle_state": LIFECYCLE_CANON_IN_PROGRESS,
            }
        )
    else:
        wizard_state.update(
            {
                "current_phase": "PROJECT_METADATA",
                "current_step_id": "project_metadata",
                "resume_target": "project_metadata",
                "lifecycle_state": LIFECYCLE_DRAFT_SETUP,
            }
        )
        if "project_metadata" not in wizard_state.get("incomplete_steps", []):
            wizard_state["incomplete_steps"] = _with_unique(wizard_state.get("incomplete_steps", []), "project_metadata")

    wizard_state["project_id"] = project_id
    wizard_state["last_saved_at"] = utc_now_iso()
    wizard_state["last_opened_at"] = utc_now_iso()
    wizard_state["can_enter_workspace"] = False
    wizard_state["blocking_requirements"] = _with_unique(wizard_state.get("blocking_requirements", []), "canon_setup")
    wizard_state.setdefault("required_canon_sets", [])
    wizard_state.setdefault("canon_set_statuses", {})
    wizard_state.setdefault("canon_reset_pending", False)
    wizard_state.setdefault("reset_canon_set_ids", [])
    return wizard_state


def _with_unique(values: list[Any], value: Any) -> list[Any]:
    result = []
    for item in values:
        if item not in result:
            result.append(item)
    if value not in result:
        result.append(value)
    return result


def _include_manifest(lifecycle_state: str, requested_state: str) -> bool:
    if requested_state in {"all", ""}:
        return True
    if requested_state == "archived":
        return lifecycle_state == LIFECYCLE_ARCHIVED
    if requested_state == "incomplete":
        return lifecycle_state in {LIFECYCLE_DRAFT_SETUP, LIFECYCLE_CANON_IN_PROGRESS}
    if requested_state == "workspace_ready":
        return lifecycle_state in {LIFECYCLE_READY_FOR_WORKSPACE, LIFECYCLE_ACTIVE}
    if requested_state == "active":
        return lifecycle_state != LIFECYCLE_ARCHIVED
    return lifecycle_state.lower() == requested_state
