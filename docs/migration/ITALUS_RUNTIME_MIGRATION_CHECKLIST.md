# Italus Runtime Migration Checklist

**Status:** Active migration control artifact  
**Updated:** 2026-07-08  
**Scope:** Documentation only. No application runtime behavior.  
**Current phase:** Stage 9 — Runtime Storage Architecture Review  
**Active alignment patch:** `italus_stage9_docs_actual_workflow_alignment_patch`

## Purpose

This checklist controls the staged migration from legacy/global runtime state to project-local runtime state.

## Stage 9 Current Decision

```text
Runtime storage initialization is automatic backend lifecycle behavior.
It is not an author-facing workspace action.
```

## Runtime Storage Lifecycle Checklist

### Project Creation

- [x] New Project creation creates project manifest.
- [x] New Project creation ensures project runtime storage.
- [x] Runtime files are initialized as empty project-local containers.
- [x] Legacy root data is not copied.
- [x] Generation remains locked after runtime storage initialization.
- [x] Provider execution remains locked.
- [x] Validation remains locked.
- [x] Export remains locked.

### Workspace Bootstrap

- [x] Workspace bootstrap returns runtime storage status.
- [x] Workspace bootstrap idempotently ensures missing runtime storage files.
- [x] Existing runtime files are preserved.
- [x] Missing files are repaired without overwriting existing content.
- [x] Runtime storage readiness does not equal generation readiness.

### Workspace UI

- [x] Runtime sidebar exposes `Project Writing Memory`.
- [x] Project Writing Memory is status/navigation only.
- [x] Manual `Initialize Writing Memory` button is absent.
- [x] Manual `runtime-storage/initialize` action is absent.
- [x] `[object Object]` no longer appears in Project Writing Memory.
- [x] Runtime Folder renders as a normal status card.
- [x] Books, Chapters, Scenes, Writing Session, Continuity Coverage, Book State, and Chapter Continuity Digests render as status cards.

## Required Runtime File Contract

- [x] `books.json`
- [x] `chapters.json`
- [x] `scenes.json`
- [x] `session_state.json`
- [x] `coverage_map.json`
- [x] `book_state.json`
- [x] `chapter_continuity_digests.json`

## Rejected / Rolled Back Behavior

- [x] Manual runtime initialization patch rolled back.
- [x] Manual initialize route removed.
- [x] Manual initialize UI removed.
- [x] Author-facing file creation workflow rejected.

Reason:

```text
Authors should not create infrastructure placeholder JSON files.
Runtime storage is a backend lifecycle responsibility.
```

## Remaining Locked Gates

- [ ] Runtime registry adapter designed.
- [ ] Runtime registry adapter implemented.
- [ ] Generation service boundary uses project-local runtime storage.
- [ ] Prompt builder routes through ProjectContext.
- [ ] Provider execution contract is project-scoped.
- [ ] Validation runtime reads project-local output.
- [ ] Export pipeline reads project-local output.
- [ ] Generation unlock gate verifies all required runtime and validation gates.

## Protected Files

Do not patch without explicit stage approval:

```text
app/project_runner.py
app/prompt_builder.py
app/registry.py
app/coverage.py
app/post_generation_canon_validator.py
app/ai_runner.py
app/claude_runner.py
app/openai_runner.py
app/novelcraft_runner.py
```

## Future Subsystems

Author Voice remains future scope. It is not part of the runtime storage initialization workflow.

## Stage 9 Checklist — Runtime Registry Adapter v2

- [ ] `app/services/project_runtime_registry_adapter.py` exists.
- [ ] Adapter reuses `project_runtime_storage_service.runtime_file_names()`.
- [ ] Adapter reuses `project_runtime_storage_service.EMPTY_RUNTIME_PAYLOADS`.
- [ ] Adapter validates approved runtime file names.
- [ ] Adapter rejects unknown runtime file names.
- [ ] Adapter returns deep-copied default payloads.
- [ ] Adapter resolves paths through `ProjectContext.runtime_data_dir`.
- [ ] Adapter remains inert from generation and prompt execution.
- [ ] `app/project_runner.py` remains untouched.
- [ ] `app/prompt_builder.py` remains untouched.
- [ ] `app/registry.py` remains untouched.

---

## Generation Control Lifecycle Checklist â€” italus_generation_control_lifecycle_contract_patch_v5

- [x] Generation Control Lifecycle contract documented.
- [x] Patch artifact process restored with separate docs script.
- [x] Existing runtime migration path preserved.
- [x] Project-local control pack boundary identified.
- [x] Provider/backend result normalization boundary identified.
- [x] Ordered chapter composition model identified.
- [x] Chapter narrative spine requirement identified.
- [x] Draft validation boundary identified.
- [x] Author approval boundary identified.
- [ ] Project-local control pack implementation built.
- [ ] Generation result normalizer implemented.
- [ ] Draft validation and continuity services wired.
- [ ] Author decision sidebar implemented.
- [ ] Prompt builder routed to project-local packs.
- [ ] Provider draft contract implemented.
- [ ] Approved-text persistence wired through runtime adapter.


### Project-Local Control Pack Boundary

- [x] italus_project_local_control_pack_boundary_patch service file exists.
- [x] Service reports expected packet status without generating files.
- [x] Generation remains locked.
- [x] Provider execution remains locked.
- [x] prompt_builder.py remains unwired.
- [x] app/registry.py remains unwritten by this boundary.

## ITALUS_CONTROL_PACK_STATUS_ROUTE_PATCH_DEPLOYED_VERIFIED

- [x] app/services/canon_packet_service.py exists as inert service boundary.
- [x] app/api/routes/project.py exposes read-only canon/control packet status route.
- [x] Route does not create packet files.
- [x] Route does not call providers.
- [x] Route does not call prompt_builder.py.
- [x] Route does not write through app/registry.py.
- [x] Route does not unlock generation, validation, or export.

## Runtime Migration Checklist Update

Marker: italus_workspace_control_packet_bootstrap_patch deployed verified

- [x] Workspace bootstrap includes read-only canon_packet_status.
- [x] Bootstrap summary includes canon_packet_count.
- [x] Bootstrap summary includes canon_packet_missing_required_count.
- [x] Generation remains locked.
- [x] Provider execution remains locked.

## italus_workspace_control_packet_readiness_ui_patch

Status: COMPLETE

Marker: italus_workspace_control_packet_readiness_ui_patch deployed / verified

- [x] Dashboard shows control packet count.
- [x] Readiness gates show control packet status.
- [x] Runtime/control pack panels show project-local packet readiness.
- [x] Generation remains locked.

- [x] Generation control status service boundary added as read-only and locked.
- [ ] Generation control status API route.
- [ ] Generation control status workspace bootstrap payload.
- [ ] Generation control locked UI display.

- [x] italus_canon_template_questionnaire_service_patch â€” read-only canon questionnaire schema service added.
  - [x] Universal canon sections defined.
  - [x] Historical Epic / Historical Fantasy questionnaire guided by current Italus canon.
  - [x] Starter expandable questionnaires defined for fantasy, science fiction, mystery/thriller, memoir, and custom.
  - [x] Generation, providers, prompt builder, registry writes, validation/export, and draft persistence remain locked.

- [x] Expose canon questionnaire templates through read-only API routes.
- [ ] Build project-local author canon storage.
- [ ] Build canon authoring API for saving section drafts.
- [ ] Build canon workbook frontend.

## italus_project_canon_storage_service_patch - DEPLOYED / VERIFIED
- [x] Project-local author canon storage service exists.
- [x] Service compiles.
- [x] Service uses questionnaire schema data.
- [x] Service writes only data/projects/<project_id>/canon/*.json.
- [x] No runtime writes, no packet generation, no protected generation imports.

## Checklist Update: Canon Authoring Workflow Service
- [x] Canon questionnaire template service exists.
- [x] Canon questionnaire routes exist.
- [x] Project-local author canon storage service exists.
- [x] Canon authoring workflow service exists.
- [ ] Canon authoring API routes.
- [ ] Frontend Canon Workbook forms.
- [ ] Markdown rendering of author canon.
- [ ] Knowledge/control packet generation from completed author canon.

## Canon Authoring API Route Boundary - VERIFIED
- GET /api/project/{project_id}/canon/authoring.
- GET /api/project/{project_id}/canon/section/{section_id}.
- POST /api/project/{project_id}/canon/section/{section_id}.
- POST /api/project/{project_id}/canon/section/{section_id}/complete.
- POST /api/project/{project_id}/canon/section/{section_id}/reopen.
- Allowed writes remain limited to project-local author canon JSON files through service boundaries.

- [x] Frontend Canon Workbook shell displays authoring status read-only.
- [x] Canon Workbook script is loaded before project lifecycle controller.
- [x] Canon setup modal contains a Canon Workbook shell container.
- [x] Canon Workbook shell calls GET /api/project/project_id/canon/authoring.
- [x] No save, complete, reopen, Markdown rendering, or generation controls were added.

PATCH: italus_canon_workbook_section_editor_patch
Scope: frontend Canon Workbook section editor.
Files: frontend/js/canon_authoring.js.
Adds: open section, load section schema, save draft, mark complete, reopen section.
Boundary: uses existing canon authoring API routes only.
Still locked: generation, providers, prompt builder, runtime writes, Markdown rendering, validation/export.

## italus_canon_markdown_renderer_service_patch
- Confirmed renderer output path is project-local canon/canon_sources only.
- Runtime memory files remain locked and untouched.
- Knowledge/control packet generation remains deferred.

## italus_canon_markdown_renderer_api_route_patch - 2026-07-15
- [x] Markdown renderer API routes deployed.
- [x] Renderer route boundary avoids generation, providers, prompt_builder, registry, runtime writes, and packet generation.
- [ ] Frontend render controls are deferred.
- [ ] Canon validation service is deferred.

- [x] italus_canon_markdown_frontend_controls_patch
  - Frontend Markdown render controls connected to existing renderer API routes.
  - No runtime memory or generation execution was introduced.

- [x] italus_canon_workbook_field_layout_patch
  - Field labels and controls render as vertical authoring blocks.
  - No backend, runtime, provider, or generation wiring changed.

- [x] italus_canon_validation_service_patch - canon validation report can be written project-locally without unlocking generation.
