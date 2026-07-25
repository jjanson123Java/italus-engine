from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.projects.project_loader import InvalidProjectIdError, ProjectNotFoundError
from app.services import (
    project_service,
    canon_setup_service,
    canon_action_service,
    workspace_service,
    project_runtime_storage_service,
    canon_packet_service,
    canon_template_service,
    canon_authoring_service,
    canon_markdown_renderer_service,
)


router = APIRouter(tags=["Project"])


class ProjectRequest(BaseModel):
    project_name: str | None = Field(default=None)
    project_kind: str | None = Field(default="single_book")
    series_name: str | None = None
    book_count: int | None = 1
    chapters_per_book: int | None = 40
    target_words_per_chapter: int | None = 4000
    target_words_per_book: int | None = None
    target_total_words: int | None = None
    token_budget_total: int | None = 250000
    token_budget_per_generation: int | None = 8000
    genre: str | None = "historical_epic"
    subgenre: str | None = None
    engine_id: str | None = "italus"
    template_id: str | None = None
    ai_provider: str | None = "claude"
    continue_to_canon: bool = False


class BudgetEstimateRequest(BaseModel):
    book_count: int | None = 1
    chapters_per_book: int | None = 40
    target_words_per_chapter: int | None = 4000
    target_words_per_book: int | None = None
    target_total_words: int | None = None
    token_budget_total: int | None = 250000
    token_budget_per_generation: int | None = 8000


class LegacyProjectRequest(BaseModel):
    project_name: str | None = None
    engine_id: str | None = "italus"
    template_id: str | None = "historical"


class CanonSectionDraftRequest(BaseModel):
    answers: dict[str, Any] | None = Field(default_factory=dict)
    records: dict[str, list[dict[str, Any]]] | None = Field(default_factory=dict)


def _model_to_dict(model: BaseModel, *, exclude_unset: bool = False) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


@router.post("/api/project/estimate-budget")
def estimate_budget(request: BudgetEstimateRequest):
    return {
        "status": "ok",
        "budget_plan": project_service.estimate_budget(_model_to_dict(request)),
    }


@router.post("/api/project/new")
def new_project(request: ProjectRequest):
    payload = _model_to_dict(request)
    return project_service.create_project(
        payload,
        continue_to_canon=request.continue_to_canon,
    )


@router.patch("/api/project/{project_id}")
def update_project(project_id: str, request: ProjectRequest):
    try:
        payload = _model_to_dict(request, exclude_unset=True)
        return project_service.update_project(
            project_id,
            payload,
            continue_to_canon=request.continue_to_canon,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except project_service.ProjectStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/projects")
def list_projects(state: str | None = Query(default=None)):
    return {
        "status": "ok",
        "state": state or "all",
        "projects": project_service.list_projects(state),
    }


@router.get("/api/project/{project_id}")
def get_project(project_id: str):
    try:
        return project_service.get_project(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/archive")
def archive_project(project_id: str):
    try:
        return project_service.archive_project(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/restore")
def restore_project(project_id: str):
    try:
        return project_service.restore_project(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc




@router.get("/api/project/{project_id}/workspace/bootstrap")
def get_workspace_bootstrap(project_id: str):
    try:
        return workspace_service.get_workspace_bootstrap(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except workspace_service.WorkspaceAccessConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/canon-packets/status")
def get_canon_packet_status(project_id: str):
    """Return read-only project-local canon/control packet status.

    This route does not create packet files, generate content, call providers,
    call prompt_builder, validate drafts, persist output, export files, or
    unlock generation.
    """
    try:
        return canon_packet_service.get_canon_packet_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc



@router.get("/api/project/{project_id}/runtime-storage/status")
def get_runtime_storage_status(project_id: str):
    """Return read-only project runtime storage status.

    This route does not create runtime folders, initialize files, migrate data,
    run generation, call providers, validate output, or export files.
    """
    try:
        return project_runtime_storage_service.get_runtime_storage_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/templates")
def list_templates():
    return canon_setup_service.available_templates()


@router.get("/api/templates/canon-questionnaires")
def list_canon_questionnaire_templates():
    """Return read-only canon-building questionnaire templates.

    This route exposes schema metadata only. It does not save author answers,
    create project canon files, generate knowledge packs, call providers,
    call prompt_builder, write runtime memory, or unlock generation.
    """
    return {
        "status": "ok",
        "templates": canon_template_service.list_canon_questionnaire_templates(),
    }


@router.get("/api/templates/base/canon-questionnaire")
def get_base_canon_questionnaire_template():
    """Return the universal base canon questionnaire schema."""
    return {
        "status": "ok",
        "template": canon_template_service.get_base_canon_questionnaire_template(),
    }


@router.get("/api/templates/{template_id}/canon-questionnaire")
def get_canon_questionnaire_template(template_id: str):
    """Return a read-only canon-building questionnaire for one template."""
    return {
        "status": "ok",
        "template": canon_template_service.get_canon_questionnaire_template(template_id),
    }


@router.get("/api/project/{project_id}/canon/setup")
def get_canon_setup(project_id: str):
    try:
        return canon_setup_service.get_canon_setup(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/canon/authoring")
def get_canon_authoring_status(project_id: str):
    """Return project-local canon authoring workflow status.

    This route does not generate content, render knowledge packs, call
    providers, call prompt_builder, write runtime memory, or unlock generation.
    """
    try:
        return canon_authoring_service.get_canon_authoring_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/canon/section/{section_id}")
def get_canon_section(project_id: str, section_id: str):
    """Return one canon questionnaire section and the saved project-local draft."""
    try:
        return canon_authoring_service.get_canon_section(project_id, section_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_authoring_service.CanonSectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/section/{section_id}")
def save_canon_section_draft(project_id: str, section_id: str, request: CanonSectionDraftRequest):
    """Save project-local author canon draft data for one section.

    This writes only project-local author canon files under data/projects and
    does not write runtime memory or generated packs.
    """
    try:
        return canon_authoring_service.save_canon_section_draft(
            project_id,
            section_id,
            _model_to_dict(request),
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_authoring_service.CanonSectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/section/{section_id}/complete")
def mark_canon_section_complete(project_id: str, section_id: str):
    """Mark one canon section complete when required fields are present."""
    try:
        return canon_authoring_service.mark_canon_section_complete(project_id, section_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_authoring_service.CanonSectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/section/{section_id}/reopen")
def reopen_canon_section(project_id: str, section_id: str):
    """Reopen a completed canon section for further author edits."""
    try:
        return canon_authoring_service.reopen_canon_section(project_id, section_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_authoring_service.CanonSectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/canon/markdown")
def get_canon_markdown_status(project_id: str):
    """Return project-local canon Markdown rendering status.

    This route does not generate knowledge packs, call providers, call
    prompt_builder, write runtime memory, or unlock generation.
    """
    try:
        return canon_markdown_renderer_service.get_canon_markdown_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/markdown/render")
def render_completed_canon_sources(project_id: str):
    """Render completed author canon sections into project-local Markdown sources."""
    try:
        return canon_markdown_renderer_service.render_completed_canon_sources(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/markdown/section/{section_id}")
def render_canon_section_markdown(project_id: str, section_id: str):
    """Render one completed author canon section into a project-local Markdown source."""
    try:
        return canon_markdown_renderer_service.render_section_markdown(project_id, section_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_markdown_renderer_service.CanonMarkdownSectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_markdown_renderer_service.CanonMarkdownSectionNotCompleteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/initialize")
def initialize_canon_setup(project_id: str):
    try:
        return canon_setup_service.initialize_canon_setup(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_setup_service.CanonSetupConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/confirm-template")
def confirm_canon_template(project_id: str):
    try:
        return canon_setup_service.confirm_genre_template(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_setup_service.CanonSetupConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/genre-template")
def confirm_genre_template_legacy(project_id: str):
    return confirm_canon_template(project_id)


@router.post("/api/project/{project_id}/canon/{canon_id}/approve-reference")
def approve_reference_canon(project_id: str, canon_id: str):
    try:
        return canon_action_service.approve_reference(project_id, canon_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_action_service.CanonItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_action_service.CanonActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/approve-all-references")
def approve_all_reference_canon(project_id: str):
    try:
        return canon_action_service.approve_all_references(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_action_service.CanonActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/complete")
def complete_canon_setup(project_id: str):
    try:
        return canon_action_service.complete_canon_setup(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_action_service.CanonActionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/open")
def open_project(request: LegacyProjectRequest):
    return {
        "status": "ok",
        "action": "open_project",
        "projects": project_service.list_projects("active"),
        "legacy_request": _model_to_dict(request),
    }


@router.post("/api/project/archive")
def open_archive(request: LegacyProjectRequest):
    return {
        "status": "ok",
        "action": "open_archive",
        "projects": project_service.list_projects("archived"),
        "legacy_request": _model_to_dict(request),
    }
