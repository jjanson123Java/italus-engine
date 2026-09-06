from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.projects.project_loader import InvalidProjectIdError, ProjectNotFoundError
from app.services import (
    project_service,
    project_canon_service,
    canon_setup_service,
    canon_action_service,
    workspace_service,
    project_runtime_storage_service,
    canon_packet_service,
    canon_template_service,
    canon_authoring_service,
    canon_reference_service,
    canon_index_service,
    story_eligibility_service,
    book_scope_service,
    canon_markdown_renderer_service,
    canon_validation_service,
    canon_packet_generation_service,
    book_plan_service,
    book_knowledge_pack_service,
    chapter_knowledge_pack_service,
    chapter_plan_service,
    story_control_service,
    progression_override_service,
    planner_query_service,
    authorship_provenance_service,
    generation_control_service,
    generation_service,
    provider_config_service,
    provider_credential_service,
    provider_binding_service,
    provider_pricing_service,
    provider_usage_service,
    provider_workspace_service,
    provider_preflight_service,
    provider_execution_service,
    validation_service,
    author_review_service,
    planner_reveal_catalog_service,
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


class BookPlanDraftRequest(BaseModel):
    books: list[dict[str, Any]] = Field(default_factory=list)


class StoryEligibilityCandidateRef(BaseModel):
    record_id: str = Field(min_length=1)
    record_type: str | None = None
    label: str | None = None


class StoryEligibilityRequest(BaseModel):
    book_number: int = Field(ge=1)
    chapter_number: int | None = Field(default=None, ge=1)
    candidate_ref: StoryEligibilityCandidateRef
    requested_use: str = Field(default="book_selection")
    selected: bool = False


class BookScopeSelectionRequest(BaseModel):
    record_id: str = Field(min_length=1)
    record_type: str | None = None
    source_class: str = Field(default="master_canon")
    usage_mode: str = Field(default="direct")


class BookScopeDraftRequest(BaseModel):
    selections: list[BookScopeSelectionRequest] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)


class BookScopeAmendmentRequest(BaseModel):
    chapter_number: int = Field(ge=1)
    action: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    source_class: str = Field(default="master_canon")
    usage_mode: str = Field(default="direct")


class ChapterPlanDraftRequest(BaseModel):
    selected_canon_refs: list[dict[str, Any]] = Field(default_factory=list)
    assigned_event_refs: list[dict[str, Any]] = Field(default_factory=list)
    event_placements: list[dict[str, Any]] = Field(default_factory=list)
    generation_kickoff: str = Field(default="")
    pov: list[dict[str, Any]] = Field(default_factory=list)
    pov_type: str = Field(default="")
    pov_omniscient_style: str = Field(default="")
    chapter_objective: str = Field(default="")
    restrictions: list[str] = Field(default_factory=list)
    story_control_refs: list[str] = Field(default_factory=list)
    advanced_sequence: list[Any] = Field(default_factory=list)


class ChapterKnowledgePackCompileRequest(BaseModel):
    prior_ending_context: str = Field(default="", max_length=8000)


class GenerationRequestBuildRequest(BaseModel):
    book_number: int = Field(ge=1)
    chapter_number: int = Field(ge=1)


class ProviderGenerationExecuteRequest(BaseModel):
    """Bounded public input for Primary 33.2.2B provider execution.

    Provider, model, binding, credential, pricing, token usage, cost, and receipt
    identities are deliberately absent because the backend owns them.
    """

    book_number: int = Field(ge=1)
    chapter_number: int = Field(ge=1)

    class Config:
        extra = "forbid"


class AuthorReviewDecisionRequest(BaseModel):
    """Bounded public author-review input for Primary 34.

    The browser may choose only the author action and reviewed text. Actor,
    provenance parentage, validation identity, and continuity authority remain
    backend-owned.
    """

    action: str = Field(min_length=1, max_length=16)
    content: str | None = Field(default=None, max_length=2_000_000)

    class Config:
        extra = "forbid"


class ProgressionOverrideRequest(BaseModel):
    book_number: int = Field(ge=1)
    chapter_number: int = Field(ge=1)
    target_ref: str = Field(min_length=1)
    requested_use: str = Field(default="chapter_selection")
    reason: str = Field(default="", max_length=1000)


class PlannerQueryRequest(BaseModel):
    action: str = Field(min_length=1)
    book_number: int = Field(ge=1)
    chapter_number: int = Field(ge=1)
    query: str = Field(default="")
    record_types: list[str] = Field(default_factory=list)
    include_future: bool = Field(default=False)
    anchor_event_id: str = Field(default="")
    limit: int = Field(default=80, ge=1, le=200)
    author_query: str = Field(default="", max_length=4000)
    minimal_context: dict[str, Any] = Field(default_factory=dict)
    allowed_search_domains: list[str] = Field(default_factory=list)


class StoryControlDraftRequest(BaseModel):
    control_id: str | None = None
    book_number: int = Field(ge=1)
    chapter_number: int = Field(ge=1)
    control_type: str = Field(min_length=1)
    subject_ref: dict[str, Any] | None = None
    instruction: str = Field(default="")
    certainty: str = Field(default="supported_evidence")
    presentation: str = Field(default="other")
    narrative_weight: str = Field(default="brief_clue")
    who_learns: list[str] = Field(default_factory=list)
    effective_point: str = Field(default="current_unit")
    knowledge_ceiling: str = Field(default="inherit")
    allowed_interpretations: list[str] = Field(default_factory=list)
    forbidden_assertions: list[str] = Field(default_factory=list)
    persistence: str = Field(default="chapter_local")
    notes: str = Field(default="")


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


@router.delete("/api/project/{project_id}")
def delete_project(project_id: str):
    """Permanently delete an unfinished project and its project-local files."""
    try:
        return project_service.delete_project(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except project_service.ProjectStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/api/project/{project_id}/workspace/library")
def get_workspace_library(project_id: str):
    """Return the lazy, read-only author Library projection."""

    try:
        return workspace_service.get_workspace_library(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except workspace_service.WorkspaceAccessConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/book-plan/contract")
def get_book_plan_contract():
    """Return the stable project-local Book Plan data contract."""

    return book_plan_service.get_book_plan_contract()


@router.get("/api/project/{project_id}/book-plan/status")
def get_book_plan_status(project_id: str):
    """Return compact Book Plan persistence and validation state."""

    try:
        return book_plan_service.get_book_plan_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_plan_service.BookPlanContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/book-plan/migration")
def get_book_plan_migration_status(project_id: str):
    """Return stable-reference migration status for the project Book Plan."""
    try:
        return book_plan_service.get_book_plan_migration_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_plan_service.BookPlanContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/book-plan/migrate-references")
def migrate_book_plan_references(project_id: str):
    """Explicitly migrate legacy label references to stable Canon IDs."""
    try:
        return book_plan_service.migrate_book_plan_references(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_plan_service.BookPlanContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/book-plan")
def get_book_plan(project_id: str):
    """Return the saved Book Plan or a non-persisted default document."""

    try:
        return book_plan_service.get_book_plan(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_plan_service.BookPlanContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/api/project/{project_id}/book-plan")
def save_book_plan_draft(
    project_id: str,
    request: BookPlanDraftRequest,
):
    """Persist project-local Book Plan draft data only."""

    try:
        return book_plan_service.save_book_plan_draft(
            project_id,
            _model_to_dict(request),
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_plan_service.BookPlanContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/book-plan/approve")
def approve_book_plan(
    project_id: str,
    book_number: int = Query(..., ge=1),
):
    """Approve one complete/current Book Plan entry."""

    try:
        return book_plan_service.approve_book_plan(project_id, book_number)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_plan_service.BookPlanContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/book-plan/revoke")
def revoke_book_plan_approval(
    project_id: str,
    book_number: int = Query(..., ge=1),
):
    """Revoke one Book Plan approval without changing plan content."""

    try:
        return book_plan_service.revoke_book_plan_approval(project_id, book_number)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_plan_service.BookPlanContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/runtime-context/project/approve")
def approve_project_runtime_context(project_id: str):
    try:
        return canon_packet_generation_service.approve_project_runtime_context(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_packet_generation_service.CanonPacketGenerationNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/runtime-context/project/revoke")
def revoke_project_runtime_context_approval(project_id: str):
    try:
        return canon_packet_generation_service.revoke_project_runtime_context_approval(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/runtime-context/books/status")
def get_book_runtime_context_status(
    project_id: str,
    book_number: int | None = Query(default=None, ge=1),
):
    """Return per-book Book Knowledge Pack readiness without writing files."""

    try:
        return book_knowledge_pack_service.get_book_runtime_context_status(
            project_id,
            book_number=book_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_plan_service.BookPlanContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/runtime-context/books/generate")
def compile_book_runtime_context(
    project_id: str,
    book_number: int | None = Query(default=None, ge=1),
):
    """Compile ready/current Book Knowledge Pack targets only.

    A completed approved book may compile independently of later incomplete
    books. This route does not construct prompts, call providers, write
    continuity, persist generated prose, or unlock generation.
    """

    try:
        return book_knowledge_pack_service.compile_book_knowledge_packs(
            project_id,
            book_number=book_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        book_plan_service.BookPlanContractError,
        book_knowledge_pack_service.BookKnowledgePackNotReadyError,
        book_knowledge_pack_service.BookKnowledgePackSourceMissingError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/api/project/{project_id}/chapter-knowledge-pack/{book_number}/{chapter_number}/status"
)
def get_chapter_knowledge_pack_status(
    project_id: str,
    book_number: int,
    chapter_number: int,
):
    """Return bounded Chapter Knowledge Pack readiness without writing derived files."""
    try:
        return chapter_knowledge_pack_service.get_chapter_knowledge_pack_status(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        chapter_plan_service.ChapterPlanError,
        story_control_service.StoryControlError,
        progression_override_service.ProgressionOverrideError,
        chapter_knowledge_pack_service.ChapterKnowledgePackError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/project/{project_id}/chapter-knowledge-pack/{book_number}/{chapter_number}/generate"
)
def compile_chapter_knowledge_pack(
    project_id: str,
    book_number: int,
    chapter_number: int,
    request: ChapterKnowledgePackCompileRequest,
):
    """Compile a bounded Chapter Knowledge Pack; generation/provider execution remains locked."""
    try:
        return chapter_knowledge_pack_service.compile_chapter_knowledge_pack(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            prior_ending_context=request.prior_ending_context,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        chapter_plan_service.ChapterPlanError,
        story_control_service.StoryControlError,
        progression_override_service.ProgressionOverrideError,
        chapter_knowledge_pack_service.ChapterKnowledgePackError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/progression-overrides")
def get_progression_overrides(
    project_id: str,
    target_ref: str = Query(default=""),
):
    """Return auditable one-time progression overrides; no Canon/continuity mutation."""
    try:
        return progression_override_service.get_progression_overrides(
            project_id,
            target_ref=target_ref or None,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except progression_override_service.ProgressionOverrideError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/progression-overrides/authorize")
def authorize_progression_override(
    project_id: str,
    request: ProgressionOverrideRequest,
):
    """Authorize explicit position-specific early use without establishing continuity."""
    try:
        return progression_override_service.authorize_early_use(
            project_id,
            book_number=request.book_number,
            chapter_number=request.chapter_number,
            target_ref=request.target_ref,
            requested_use=request.requested_use,
            reason=request.reason,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except progression_override_service.ProgressionOverrideContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except progression_override_service.ProgressionOverrideConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except progression_override_service.ProgressionOverrideError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/chapter-plan/contract")
def get_chapter_plan_contract():
    """Return the lightweight Chapter Plan/Event Board contract."""
    return chapter_plan_service.get_chapter_plan_contract()


@router.get("/api/project/{project_id}/chapter-plan/status")
def get_chapter_plan_status(project_id: str):
    """Return compact Chapter Plan status without creating planning state."""
    try:
        return chapter_plan_service.get_chapter_plan_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except chapter_plan_service.ChapterPlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/chapter-plan")
def get_chapter_plan(project_id: str):
    """Return saved Chapter Plan or non-persisted defaults."""
    try:
        return chapter_plan_service.get_chapter_plan(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except chapter_plan_service.ChapterPlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/chapter-plan/{book_number}/{chapter_number}")
def get_chapter_plan_chapter(
    project_id: str,
    book_number: int,
    chapter_number: int,
):
    """Return one Chapter Planner record by book/chapter position."""
    try:
        return chapter_plan_service.get_chapter(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except chapter_plan_service.ChapterPlanContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except chapter_plan_service.ChapterPlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/api/project/{project_id}/chapter-plan/{book_number}/{chapter_number}")
def save_chapter_plan_chapter(
    project_id: str,
    book_number: int,
    chapter_number: int,
    request: ChapterPlanDraftRequest,
):
    """Persist one lightweight Chapter Plan draft."""
    try:
        return chapter_plan_service.save_chapter_draft(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            payload=_model_to_dict(request),
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except chapter_plan_service.ChapterPlanContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except chapter_plan_service.ChapterPlanStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/chapter-plan/{book_number}/{chapter_number}/event-candidates")
def get_chapter_event_candidates(
    project_id: str,
    book_number: int,
    chapter_number: int,
    anchor_event_id: str = Query(default=""),
    query: str = Query(default=""),
):
    """Return deterministic event candidates/relationships for the Event Board."""
    try:
        return chapter_plan_service.get_event_candidates(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            anchor_event_id=anchor_event_id,
            query=query,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except chapter_plan_service.ChapterPlanContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except chapter_plan_service.ChapterPlanError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/planner-reveal-catalog")
def get_planner_reveal_catalog(
    project_id: str,
    book_number: int | None = Query(default=None, ge=1),
):
    """Return project-local author-facing mystery/reveal planning threads."""
    try:
        return planner_reveal_catalog_service.get_reveal_catalog(
            project_id,
            book_number=book_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc



@router.get("/api/project/planner-query/contract")
def get_planner_query_contract():
    """Return the deterministic Planner Query boundary contract."""
    return planner_query_service.get_planner_query_contract()


@router.post("/api/project/{project_id}/planner-query")
def run_planner_query(project_id: str, request: PlannerQueryRequest):
    """Run deterministic discovery or the bounded local Planner Intent Model."""
    try:
        return planner_query_service.execute_planner_query(
            project_id,
            action=request.action,
            book_number=request.book_number,
            chapter_number=request.chapter_number,
            query=request.query,
            record_types=request.record_types,
            include_future=request.include_future,
            anchor_event_id=request.anchor_event_id,
            limit=request.limit,
            author_query=request.author_query,
            minimal_context=request.minimal_context,
            allowed_search_domains=request.allowed_search_domains,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except planner_query_service.PlannerQueryContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except planner_query_service.PlannerQueryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/provenance/contract")
def get_authorship_provenance_contract():
    """Return the Patch-28 provenance actor/event/storage contract."""
    return authorship_provenance_service.get_provenance_contract()


@router.post("/api/project/{project_id}/provenance/initialize")
def initialize_authorship_provenance(project_id: str):
    """Ensure project-local provenance storage; no provider/review execution."""
    try:
        return authorship_provenance_service.ensure_provenance_storage(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except authorship_provenance_service.AuthorshipProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/provenance/status")
def get_authorship_provenance_status(project_id: str):
    """Return provenance storage/lineage readiness without creating evidence."""
    try:
        return authorship_provenance_service.get_provenance_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except authorship_provenance_service.AuthorshipProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/api/project/{project_id}/provenance/chapter/{book_number}/{chapter_number}/status"
)
def get_chapter_authorship_provenance_status(
    project_id: str,
    book_number: int,
    chapter_number: int,
):
    """Return the non-scoring chapter provenance status shell."""
    try:
        return authorship_provenance_service.get_chapter_provenance_status(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except authorship_provenance_service.AuthorshipProvenanceContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except authorship_provenance_service.AuthorshipProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/generation-readiness")
def get_generation_readiness(
    project_id: str,
    book_number: int = Query(..., ge=1),
    chapter_number: int = Query(..., ge=1),
):
    """Return the authoritative Patch-29 generation readiness gate status."""

    try:
        return generation_control_service.get_generation_control_status(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/generation-request/build")
def build_generation_request(
    project_id: str,
    request: GenerationRequestBuildRequest,
):
    """Build a provider-neutral Primary-32 request without executing it."""

    try:
        return generation_service.build_generation_request_envelope(
            project_id,
            book_number=request.book_number,
            chapter_number=request.chapter_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except generation_service.GenerationRequestBuildError as exc:
        status_code = 422 if exc.code == "request_scope_invalid" else 409
        raise HTTPException(status_code=status_code, detail=exc.to_detail()) from exc


@router.get("/api/project/{project_id}/runtime-context/project/status")
def get_project_runtime_context_status(project_id: str):
    """Return project-level runtime-context readiness without writing files."""

    try:
        return canon_packet_generation_service.get_project_runtime_context_status(
            project_id
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/runtime-context/project/generate")
def generate_project_runtime_context(project_id: str):
    """Generate only the project-level reviewable runtime-context artifact.

    This route excludes book packs and does not call prompt construction,
    providers, runtime memory, draft persistence, validation runtime, exports,
    or generation unlock behavior.
    """

    try:
        return canon_packet_generation_service.generate_project_runtime_context(
            project_id
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        canon_packet_generation_service.CanonPacketGenerationNotReadyError,
        canon_packet_generation_service.CanonPacketSourceMissingError,
    ) as exc:
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


@router.get("/api/project/{project_id}/canon/template-migration")
def get_canon_template_migration_status(project_id: str):
    """Return read-only project template snapshot migration status."""
    try:
        return project_canon_service.get_template_snapshot_migration_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/template-migration")
def migrate_canon_template_snapshot(project_id: str):
    """Upgrade the project-local template snapshot without inventing or rewriting story truth."""
    try:
        migration = project_canon_service.migrate_template_snapshot(project_id)
        completion = canon_authoring_service.revalidate_canon_completion(project_id)
        validation = canon_validation_service.validate_project_canon(project_id)
        return {
            "status": "ok",
            "project_id": project_id,
            "migration": migration,
            "completion": completion,
            "validation": validation,
            "execution_locks": migration.get("execution_locks", {}),
        }
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except project_canon_service.TemplateSnapshotMigrationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/canon/index")
def get_canon_index_status(project_id: str):
    """Return project-local derived Canon Index freshness/status."""
    try:
        return canon_index_service.get_index_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_index_service.CanonIndexError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/index/rebuild")
def rebuild_canon_index(project_id: str):
    """Rebuild project-local derived Canon Index from current Author Canon."""
    try:
        return canon_index_service.rebuild_index(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_index_service.CanonIndexError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/story-eligibility")
def get_story_eligibility_status(project_id: str):
    """Return Story Eligibility source/readiness status without mutating state."""
    try:
        return story_eligibility_service.get_story_eligibility_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except story_eligibility_service.StoryEligibilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/story-eligibility/evaluate")
def evaluate_story_eligibility(project_id: str, request: StoryEligibilityRequest):
    """Evaluate one stable Canon record under explicit current story constraints."""
    try:
        return story_eligibility_service.evaluate_story_eligibility(
            project_id,
            book_number=request.book_number,
            chapter_number=request.chapter_number,
            candidate_ref=_model_to_dict(request.candidate_ref),
            requested_use=request.requested_use,
            selected=request.selected,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (story_eligibility_service.StoryEligibilityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/book-scope/contract")
def get_book_scope_contract():
    """Return the project-local Book Scope backend contract."""
    return book_scope_service.get_book_scope_contract()


@router.get("/api/project/{project_id}/book-scope/status")
def get_book_scope_status(project_id: str):
    """Return compact per-book Book Scope lifecycle/freshness state."""
    try:
        return book_scope_service.get_book_scope_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/book-scope/catalog")
def get_book_scope_catalog(
    project_id: str,
    book_number: int = Query(ge=1),
    include_future: bool = Query(default=False),
    query: str = Query(default=""),
    record_type: str | None = Query(default=None),
):
    """Return categorized Canon choices with current Story Eligibility states."""
    try:
        return book_scope_service.get_book_scope_catalog(
            project_id,
            book_number=book_number,
            include_future=include_future,
            query=query,
            record_type=record_type,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except book_scope_service.BookScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/book-scope")
def get_book_scope(project_id: str):
    """Return the saved Book Scope or non-persisted defaults for all books."""
    try:
        return book_scope_service.get_book_scope(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/api/project/{project_id}/book-scope/{book_number}")
def save_book_scope_draft(
    project_id: str,
    book_number: int,
    request: BookScopeDraftRequest,
):
    """Persist one Book Scope draft using stable Canon record references."""
    try:
        return book_scope_service.save_book_scope_draft(
            project_id,
            book_number=book_number,
            payload=_model_to_dict(request),
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except book_scope_service.BookScopeStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/book-scope/{book_number}/approve")
def approve_book_scope(project_id: str, book_number: int):
    """Approve one current, valid Book Scope revision and source snapshot."""
    try:
        return book_scope_service.approve_book_scope(
            project_id,
            book_number=book_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/book-scope/{book_number}/revoke")
def revoke_book_scope_approval(project_id: str, book_number: int):
    """Revoke one Book Scope approval without changing selections."""
    try:
        return book_scope_service.revoke_book_scope_approval(
            project_id,
            book_number=book_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/book-scope/{book_number}/effective")
def get_effective_book_scope(
    project_id: str,
    book_number: int,
    chapter_number: int = Query(ge=1),
):
    """Return Book Canon selections effective at one chapter boundary."""
    try:
        return book_scope_service.effective_book_scope_selections(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except book_scope_service.BookScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/book-scope/{book_number}/chapter-snapshot")
def get_book_scope_chapter_snapshot(
    project_id: str,
    book_number: int,
    chapter_number: int = Query(ge=1),
):
    """Return a lightweight read-only Book Scope snapshot for Chapter Planner."""
    try:
        return book_scope_service.get_chapter_scope_snapshot(
            project_id, book_number=book_number, chapter_number=chapter_number
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/runtime-context/books/{book_number}/readiness-fast")
def get_book_runtime_context_readiness_fast(project_id: str, book_number: int):
    """Return fast per-book readiness for Chapter Planner guidance."""
    try:
        return book_knowledge_pack_service.get_book_runtime_context_readiness_fast(
            project_id, book_number=book_number
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, book_knowledge_pack_service.BookKnowledgePackNotReadyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/book-scope/{book_number}/amend")
def amend_book_scope(
    project_id: str,
    book_number: int,
    request: BookScopeAmendmentRequest,
):
    """Apply one audited prospective Add/Remove to Canon for This Book."""
    payload = _model_to_dict(request)
    try:
        return book_scope_service.amend_book_scope(
            project_id,
            book_number=book_number,
            chapter_number=int(payload["chapter_number"]),
            action=str(payload["action"]),
            record_id=str(payload["record_id"]),
            source_class=str(payload.get("source_class") or "master_canon"),
            usage_mode=str(payload.get("usage_mode") or "direct"),
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except book_scope_service.BookScopeContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except book_scope_service.BookScopeStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/story-controls/contract")
def get_story_control_contract():
    """Return the Story Control Registry authoring contract."""
    return story_control_service.get_story_control_contract()


@router.get("/api/project/{project_id}/story-controls/status")
def get_story_control_status(project_id: str):
    try:
        return story_control_service.get_story_control_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except story_control_service.StoryControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/project/{project_id}/story-controls")
def get_story_controls(
    project_id: str,
    book_number: int | None = Query(default=None, ge=1),
    chapter_number: int | None = Query(default=None, ge=1),
):
    try:
        return story_control_service.get_story_controls(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except story_control_service.StoryControlContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except story_control_service.StoryControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/story-controls")
def save_story_control(
    project_id: str,
    request: StoryControlDraftRequest,
):
    try:
        return story_control_service.save_story_control(
            project_id,
            _model_to_dict(request),
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except story_control_service.StoryControlContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except story_control_service.StoryControlStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/project/{project_id}/story-controls/{control_id}")
def delete_story_control(
    project_id: str,
    control_id: str,
):
    try:
        return story_control_service.delete_story_control(
            project_id,
            control_id,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except story_control_service.StoryControlContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except story_control_service.StoryControlStateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    except (
        canon_authoring_service.CanonRecordIdentityConflictError,
        canon_reference_service.CanonReferenceConflictError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/api/project/{project_id}/canon/validation")
def get_canon_validation_status(project_id: str):
    """Return read-only project-local canon validation status."""
    try:
        return canon_validation_service.get_canon_validation_status(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/validation/run")
def run_canon_validation(project_id: str):
    """Validate project-local canon and write the validation report."""
    try:
        return canon_validation_service.validate_project_canon(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/project/{project_id}/canon/validation/section/{section_id}")
def validate_canon_section(project_id: str, section_id: str):
    """Validate one project-local canon section without writing a report."""
    try:
        return canon_validation_service.validate_section(project_id, section_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except canon_validation_service.CanonValidationSectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


class ProviderConfigSaveRequest(BaseModel):
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    service_tier: str = Field(default="standard", min_length=1)
    inference_scope: str = Field(default="global", min_length=1)


class ProviderCredentialSaveRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=2048)


class ProviderProjectBindingRequest(BaseModel):
    provider_id: str = Field(min_length=1)


class ProviderProjectModelRequest(BaseModel):
    model_id: str = Field(min_length=1)


class ProviderPricingVersionRequest(BaseModel):
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    service_tier: str = Field(default="standard", min_length=1)
    inference_scope: str = Field(default="global", min_length=1)
    currency: str = Field(default="USD", min_length=1)
    input_per_mtok: str = Field(min_length=1)
    output_per_mtok: str = Field(min_length=1)
    cache_write_5m_per_mtok: str = Field(default="0")
    cache_write_1h_per_mtok: str = Field(default="0")
    cache_read_per_mtok: str = Field(default="0")
    effective_from: str = Field(min_length=1)
    verified_at: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    notes: str = Field(default="")


class ProviderPricingPolicyRequest(BaseModel):
    freshness_threshold_days: int = Field(ge=1, le=3650)


@router.get("/api/provider/catalog")
def get_provider_catalog():
    """Return the Primary 33.1 provider catalog without secrets or execution."""
    return provider_config_service.provider_catalog()


@router.get("/api/provider/config")
def get_provider_config(
    provider_id: str | None = Query(default=None),
):
    """Return one non-secret provider profile plus all configured profile summaries."""
    try:
        return provider_config_service.get_provider_config(provider_id)
    except provider_config_service.ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/provider/config")
def save_provider_config(request: ProviderConfigSaveRequest):
    """Persist one non-secret provider/model profile.

    Multiple providers may be configured simultaneously. API credentials are
    resolved by the backend secure credential abstraction and are never
    returned to the browser.
    """
    try:
        return provider_config_service.save_provider_config(
            **_model_to_dict(request)
        )
    except provider_config_service.ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/provider/profiles")
def get_provider_profiles():
    """Return saved provider profiles with project associations and credential state."""
    profiles = provider_config_service.list_provider_profiles()
    associations = provider_binding_service.list_provider_profile_associations()

    by_provider: dict[str, list[dict[str, Any]]] = {}
    for association in associations:
        provider_id = str(association.get("provider_id") or "").strip().lower()
        if provider_id:
            by_provider.setdefault(provider_id, []).append(association)

    result: list[dict[str, Any]] = []
    for profile in profiles:
        provider_id = str(profile.get("provider_id") or "").strip().lower()
        linked = by_provider.get(provider_id, [])
        result.append(
            {
                **profile,
                "associations": linked,
                "association_count": len(linked),
                "can_delete": len(linked) == 0,
            }
        )

    return {
        "status": "ok",
        "schema_version": "primary33.1-provider-profile-inventory-v1",
        "profiles": result,
        "provider_execution_allowed": False,
    }


@router.delete("/api/provider/config/{provider_id}")
def delete_provider_profile(provider_id: str):
    """Delete one saved provider/model profile only after all project bindings are removed."""
    try:
        associations = provider_binding_service.list_provider_profile_associations(provider_id)
        if associations:
            project_names = ", ".join(
                str(item.get("project_name") or item.get("project_id") or "project")
                for item in associations
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    "Disassociate this provider profile from every project before deleting it. "
                    f"Still associated with: {project_names}."
                ),
            )
        return provider_config_service.delete_provider_profile(provider_id)
    except provider_config_service.ProviderConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_local_provider_credential_admin(request: Request) -> None:
    client_host = str(request.client.host if request.client else "").strip().lower()
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(
            status_code=403,
            detail=(
                "Interactive provider credential management is restricted to the local Italus application."
            ),
        )
    if not provider_credential_service.interactive_management_available():
        raise HTTPException(
            status_code=409,
            detail=(
                "Interactive provider credential management is unavailable for the trusted "
                "credential backend selected by this deployment."
            ),
        )


@router.get("/api/provider/credentials/status")
def get_provider_credential_status():
    """Return provider credential state only; never return secret values."""
    return provider_credential_service.credential_states()


@router.put("/api/provider/credentials/{provider_id}")
def save_provider_credential(
    provider_id: str,
    request_payload: ProviderCredentialSaveRequest,
    request: Request,
):
    """Store one provider key using the trusted local secure credential backend."""
    _require_local_provider_credential_admin(request)
    try:
        return provider_credential_service.save_api_key(
            provider_id,
            request_payload.api_key,
        )
    except provider_credential_service.ProviderCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/provider/credentials/{provider_id}")
def delete_provider_credential(
    provider_id: str,
    request: Request,
):
    """Delete only an Italus-managed local credential; external secrets are untouched."""
    _require_local_provider_credential_admin(request)
    try:
        return provider_credential_service.delete_stored_api_key(provider_id)
    except provider_credential_service.ProviderCredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/provider/projects/{project_id}/binding")
def get_project_provider_binding(project_id: str):
    """Return the project-local provider/model binding and lock state."""
    try:
        return provider_binding_service.get_project_provider_binding(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except provider_binding_service.ProviderBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/provider/projects/{project_id}/workspace-summary")
def get_project_provider_workspace_summary(
    project_id: str,
    response: Response,
):
    """Return the read-only Provider 33.1 projection used by Workspace."""
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    try:
        return provider_workspace_service.get_project_provider_workspace_summary(
            project_id
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        provider_binding_service.ProviderBindingError,
        provider_pricing_service.ProviderPricingError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/provider/projects/{project_id}/binding")
def save_project_provider_binding(
    project_id: str,
    request: ProviderProjectBindingRequest,
):
    """Bind one saved provider/model profile to one project.

    The binding may be corrected before provider usage begins. Once any
    provider usage exists for the project, provider/model switching is rejected.
    """
    try:
        return provider_binding_service.save_project_provider_binding(
            project_id,
            provider_id=request.provider_id,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except provider_binding_service.ProviderBindingLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (
        provider_binding_service.ProviderBindingError,
        provider_config_service.ProviderConfigError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/provider/projects/{project_id}/model")
def save_project_provider_model(
    project_id: str,
    request: ProviderProjectModelRequest,
):
    """Change only the project-effective model for the currently bound provider.

    Provider Settings remains unchanged. The model must be accepted by the
    bound provider's curated direct-model catalog. Post-usage changes remain
    locked until the controlled migration phase.
    """
    try:
        return provider_binding_service.save_project_model_override(
            project_id,
            model_id=request.model_id,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except provider_binding_service.ProviderBindingLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (
        provider_binding_service.ProviderBindingError,
        provider_config_service.ProviderConfigError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/provider/projects/{project_id}/binding")
def delete_project_provider_binding(project_id: str):
    """Disassociate a provider profile without deleting the project."""
    try:
        return provider_binding_service.delete_project_provider_binding(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except provider_binding_service.ProviderBindingLockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except provider_binding_service.ProviderBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/provider/pricing/policy")
def get_provider_pricing_policy():
    """Return the application-global pricing freshness warning policy."""
    return provider_pricing_service.get_pricing_policy()


@router.put("/api/provider/pricing/policy")
def save_provider_pricing_policy(request: ProviderPricingPolicyRequest):
    """Persist the application-global pricing freshness warning threshold."""
    try:
        return provider_pricing_service.save_pricing_policy(
            freshness_threshold_days=request.freshness_threshold_days,
        )
    except provider_pricing_service.ProviderPricingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/provider/pricing/current")
def get_current_provider_pricing(
    provider_id: str = Query(min_length=1),
    model_id: str = Query(min_length=1),
    service_tier: str = Query(default="standard", min_length=1),
    inference_scope: str = Query(default="global", min_length=1),
):
    """Return the immutable pricing version effective now for one provider/model key."""
    return provider_pricing_service.get_current_pricing(
        provider_id=provider_id,
        model_id=model_id,
        service_tier=service_tier,
        inference_scope=inference_scope,
    )


@router.post("/api/provider/pricing/versions")
def save_provider_pricing_version(request: ProviderPricingVersionRequest):
    """Create a new immutable pricing version without rewriting prior price history."""
    try:
        return provider_pricing_service.save_pricing_version(
            **_model_to_dict(request)
        )
    except provider_pricing_service.ProviderPricingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/provider/pricing/registry")
def get_provider_pricing_registry(
    provider_id: str = Query(min_length=1),
    service_tier: str = Query(default="standard", min_length=1),
    inference_scope: str = Query(default="global", min_length=1),
):
    """Return current, scheduled, and retired immutable pricing by catalog model."""
    try:
        return provider_pricing_service.get_pricing_registry(
            provider_id=provider_id,
            service_tier=service_tier,
            inference_scope=inference_scope,
        )
    except provider_pricing_service.ProviderPricingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/provider/pricing/history")
def get_provider_pricing_history(
    provider_id: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Return append-only pricing history metadata."""
    return provider_pricing_service.list_pricing_history(
        provider_id=provider_id,
        model_id=model_id,
        limit=limit,
    )


@router.post("/api/provider/projects/{project_id}/preflight")
def run_project_provider_preflight(project_id: str):
    """Run the non-generating provider authentication/model/pricing preflight.

    The backend may contact the bound direct provider's model metadata endpoint.
    It never returns credential plaintext, records provider usage, or enables
    generation.
    """
    try:
        return provider_preflight_service.run_project_provider_preflight(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        provider_binding_service.ProviderBindingError,
        provider_config_service.ProviderConfigError,
        provider_credential_service.ProviderCredentialError,
        provider_pricing_service.ProviderPricingError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _provider_execution_http_status(exc: provider_execution_service.ProviderExecutionError) -> int:
    """Map safe provider-execution failures to stable HTTP status classes."""
    if exc.reconciliation_required:
        return 409

    code = str(exc.code or "")
    if code in {"request_scope_invalid", "PROVIDER_REQUEST_REJECTED"}:
        return 422
    if code == "PROVIDER_RATE_LIMITED":
        return 429
    if code == "PROVIDER_UNAVAILABLE":
        return 503
    if code == "PROVIDER_REQUEST_FAILED":
        return 502
    if code == "PROVIDER_EXECUTION_ACTIVATION_LOCKED":
        return 503
    return 409


@router.post("/api/provider/projects/{project_id}/generation/execute")
def execute_project_provider_generation(
    project_id: str,
    payload: ProviderGenerationExecuteRequest,
    http_request: Request,
):
    """Execute one controlled provider generation with server-owned lineage.

    The caller supplies only the project position and an Idempotency-Key header.
    Provider/model/credential/pricing/usage/cost identities are resolved and
    committed exclusively by the backend execution service.
    """
    idempotency_key = str(http_request.headers.get("Idempotency-Key") or "").strip()
    if not idempotency_key:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Idempotency-Key header is required for provider generation.",
            },
        )
    if len(idempotency_key.encode("utf-8")) > 256:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "IDEMPOTENCY_KEY_TOO_LONG",
                "message": "Idempotency-Key must not exceed 256 UTF-8 bytes.",
            },
        )

    try:
        return provider_execution_service.execute_provider_generation(
            project_id,
            book_number=payload.book_number,
            chapter_number=payload.chapter_number,
            idempotency_key=idempotency_key,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except provider_execution_service.ProviderExecutionError as exc:
        raise HTTPException(
            status_code=_provider_execution_http_status(exc),
            detail=exc.to_detail(),
        ) from exc


@router.get(
    "/api/provider/projects/{project_id}/generation/{generation_id}/validation"
)
def validate_project_provider_generation_candidate(
    project_id: str,
    generation_id: str,
):
    """Return the read-only Primary 34 structured validator context."""

    try:
        return validation_service.validate_generation_candidate(
            project_id,
            generation_id,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except validation_service.CandidateValidationError as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail()) from exc


@router.get(
    "/api/provider/projects/{project_id}/generation/{generation_id}/review"
)
def get_project_provider_generation_review(
    project_id: str,
    generation_id: str,
):
    """Return current Primary 34 author-review state without mutating evidence."""

    try:
        return author_review_service.get_author_review_status(
            project_id,
            generation_id,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except validation_service.CandidateValidationError as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail()) from exc
    except author_review_service.AuthorReviewError as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail()) from exc


@router.post(
    "/api/provider/projects/{project_id}/generation/{generation_id}/review"
)
def record_project_provider_generation_review(
    project_id: str,
    generation_id: str,
    payload: AuthorReviewDecisionRequest,
):
    """Persist one backend-owned author review transition.

    This route may append author-review provenance only. It cannot write
    Approved Continuity, Canon, runtime story state, provider receipts, or usage.
    """

    try:
        return author_review_service.record_author_review(
            project_id,
            generation_id,
            action=payload.action,
            content=payload.content,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except validation_service.CandidateValidationError as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail()) from exc
    except author_review_service.AuthorReviewError as exc:
        status_code = (
            422
            if exc.code
            in {
                "AUTHOR_REVIEW_ACTION_INVALID",
                "AUTHOR_REVIEW_CONTENT_REQUIRED",
                "AUTHOR_REVIEW_REJECT_CONTENT_MISMATCH",
            }
            else 409
        )
        raise HTTPException(status_code=status_code, detail=exc.to_detail()) from exc


@router.get("/api/provider/projects/{project_id}/usage/summary")
def get_provider_usage_summary(project_id: str):
    """Return the rebuildable provider-usage summary for one project."""
    try:
        return provider_usage_service.get_usage_summary(project_id)
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/provider/projects/{project_id}/usage/events")
def get_provider_usage_events(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Return provider usage events without exposing a browser write surface."""
    try:
        return provider_usage_service.list_usage_events(
            project_id,
            limit=limit,
        )
    except (ProjectNotFoundError, InvalidProjectIdError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
