# Italus Migration Patch Plan

**Status:** Active migration plan  
**Updated:** 2026-07-08  
**Scope:** Patch sequencing artifact. Documentation only.  
**Current phase:** Stage 9 — Runtime Storage Architecture Review  
**Active alignment patch:** `italus_stage9_docs_actual_workflow_alignment_patch`

## Current Migration Phase

```text
Stage 9 active — Runtime Storage Architecture Review
```

Stage 8 is complete. Stage 9 is currently migrating Italus from global/legacy runtime state toward project-local runtime storage while generation remains locked.

## Corrected Stage 9 Workflow Decision

Runtime storage initialization is a backend lifecycle responsibility.

```text
New Project creation -> backend prepares project-local runtime storage.
Workspace bootstrap -> backend idempotently ensures/repairs missing runtime files.
Workspace UI -> shows Project Writing Memory status only.
Author -> does not click a button to create placeholder JSON files.
```

The Project Writing Memory item in the Runtime sidebar is a status/navigation entry. It is not an initialization action.

## Validated Current State

```text
italus_project_runtime_storage_service_patch: deployed / validated
italus_runtime_storage_initialization_patch: rolled back
italus_runtime_storage_auto_initialize_patch: deployed / validated
italus_runtime_storage_status_ui_object_render_fix_patch: deployed / browser-confirmed
```

The manual runtime initialization workflow was rejected. It was rolled back because file preparation belongs in New Project creation and workspace bootstrap, not in an author-facing button.

The object render UI patch corrected the visible `[object Object]` defect in the Project Writing Memory panel. Browser validation confirms the runtime folder card now renders as a normal card.

## Runtime Storage Contract

Runtime storage root:

```text
data/projects/<project_id>/runtime/
```

Required files:

```text
books.json
chapters.json
scenes.json
session_state.json
coverage_map.json
book_state.json
chapter_continuity_digests.json
```

Initialization policy:

```text
Create missing files only.
Never overwrite existing runtime content.
Never copy legacy root data.
Never unlock generation.
Never call providers.
Never run validation.
Never export.
```

## Source-of-Truth Matrix

| Runtime State | Current Source | Future Source | Current Stage 9 Behavior | Owner |
|---|---|---|---|---|
| Books | legacy read-only seed/reference | `runtime/books.json` | initialized empty, not written by generation yet | project runtime storage service |
| Chapters | legacy read-only seed/reference | `runtime/chapters.json` | initialized empty, not written by generation yet | project runtime storage service |
| Scenes | legacy read-only seed/reference | `runtime/scenes.json` | initialized empty, not written by generation yet | project runtime storage service |
| Session | legacy read-only seed/reference | `runtime/session_state.json` | initialized empty | project runtime storage service |
| Coverage | legacy read-only seed/reference | `runtime/coverage_map.json` | initialized empty | project runtime storage service |
| Book state | legacy read-only seed/reference | `runtime/book_state.json` | initialized empty | project runtime storage service |
| Chapter digests | legacy read-only seed/reference | `runtime/chapter_continuity_digests.json` | initialized empty | project runtime storage service |

## Completed Stage 9 Patch Sequence

1. `italus_stage9_architecture_control_docs_patch_v4`
   - Locked Stage 9 runtime storage architecture controls.
   - Recorded the seven-file runtime contract.
   - Preserved Author Voice as a future subsystem only.

2. `italus_project_runtime_storage_service_patch`
   - Added runtime storage status service.
   - Added read-only runtime storage status endpoint.
   - Added backend-backed Project Writing Memory status data.
   - Did not create runtime files.

3. `italus_runtime_storage_initialization_patch`
   - Added manual initialization endpoint/UI.
   - **Rolled back.**
   - Reason: author-facing file initialization was the wrong UX and lifecycle boundary.

4. `italus_runtime_storage_auto_initialize_patch`
   - Moved runtime initialization into backend lifecycle.
   - New Project creation ensures runtime storage.
   - Workspace bootstrap idempotently ensures/repairs runtime storage.
   - Manual initialize route and manual initialize UI remain absent.
   - Generation, validation, provider execution, prompt routing, and export remain locked.

5. `italus_runtime_storage_status_ui_object_render_fix_patch`
   - Frontend-only fix.
   - Corrected raw object rendering in the Project Writing Memory panel.
   - `[object Object]` no longer appears.
   - Project Writing Memory remains a status/navigation panel.

## Current Author-Facing UX

Landing page:

```text
Project -> New Project
Tile -> New Project
```

New Project flow:

```text
Author completes modal / wizard.
Backend creates project manifest.
Backend prepares empty project-local runtime storage.
Canon flow proceeds.
Workspace later opens with Project Writing Memory already prepared.
```

Existing Project flow:

```text
Author opens existing project.
Workspace bootstrap ensures missing runtime storage files without overwriting existing data.
Project Writing Memory shows status.
Generation remains locked until later gates pass.
```

Workspace Runtime sidebar:

```text
Project Writing Memory
Memory / Continuity
Validation
Output
```

Only Project Writing Memory is currently a status surface. The other runtime entries remain locked until later migration stages.

## Next Patch Plan

Next recommended phase:

```text
italus_runtime_registry_adapter_design_docs_patch
```

Purpose:

```text
Define the adapter boundary that prevents split-brain runtime state before generation writes are migrated.
```

After that:

```text
italus_project_runtime_registry_adapter_patch
italus_generation_service_boundary_patch
italus_prompt_builder_project_context_routing_patch
italus_provider_execution_contract_patch
italus_project_validation_runtime_patch
italus_project_export_pipeline_patch
italus_generation_unlock_gate_patch
```

## Hard Boundaries

Do not unlock generation until all runtime gates pass.

Do not modify protected runtime execution files without explicit patch approval:

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

Do not implement Author Voice in Stage 9 runtime storage patches.

## Known Documentation Alignment Notes

This patch aligns migration docs with the validated workflow after rollback and corrective deployment.

The previous manual initialization concept is no longer part of the active plan.

## Stage 9 Update — Project Runtime Registry Adapter v2

Patch: `italus_project_runtime_registry_adapter_patch_v2`

Status: planned / deployment validation required.

Purpose:
- Add `app/services/project_runtime_registry_adapter.py` as the controlled project-local runtime JSON read/write boundary.
- Keep the adapter inert from generation, prompt building, validation, export, and provider execution until later migration stages.
- Reuse the existing seven-file runtime contract owned by `app/services/project_runtime_storage_service.py`.
- Avoid adding a separate runtime contract module at this stage.
- Preserve `app/project_runner.py`, `app/prompt_builder.py`, and `app/registry.py` untouched.

Ownership boundary:
- `project_runtime_storage_service.py` creates and repairs the runtime folder and empty JSON containers.
- `project_runtime_registry_adapter.py` validates approved runtime file access and provides explicit load/save helpers for later controlled wiring.

Universal runtime file set:
- `books.json`
- `chapters.json`
- `scenes.json`
- `session_state.json`
- `coverage_map.json`
- `book_state.json`
- `chapter_continuity_digests.json`

Genre policy:
The runtime file contract is universal across genres. Historical fantasy, sci-fi, romance, mystery, and future genres use the same runtime file names. Genre-specific behavior belongs in project manifest, canon, templates, prompt rules, and future voice systems, not in the file contract.

Generation remains locked after this patch.

---

## Generation Control Lifecycle Roadmap â€” italus_generation_control_lifecycle_contract_patch_v5

Status: documented / verified / docs-finalized.

The existing runtime migration path remains valid. The Generation Control Layer is now inserted as a required prerequisite before prompt routing, provider execution, draft validation wiring, author decision UI, or runtime persistence wiring continues.

Approved direction:
- Primary author canon remains source of truth.
- System control files are templates or derived rules, not editable primary canon.
- Project-local knowledge/control packs are derived from approved canon and approved runtime state.
- Provider output is candidate or advisory until normalized and validated.
- Backend validation is authoritative before author approval.
- Single-scene, single-unit chapter, and ordered multi-unit chapter generation must remain supported.
- Multi-unit chapters require author-controlled ordering and a chapter narrative spine.
- Runtime adapter persists approved text only.

Next approved phases:
1. Project-local control pack boundary.
2. Generation result normalization boundary.
3. Draft validation and continuity boundary.
4. Author decision sidebar state model.
5. Prompt builder project-control routing.
6. Provider candidate draft contract.
7. Author-approved runtime persistence wiring.

Locked until later:
- app/project_runner.py
- app/prompt_builder.py
- provider runners
- frontend generation UI
- runtime JSON content writes


## Project-Local Control Pack Boundary

``text
italus_project_local_control_pack_boundary_patch: deployed / verified
``

The service-only boundary records expected project-local canon/control packet readiness. It remains read-only and does not wire generation, providers, prompt construction, validation, export, or approved persistence.

## ITALUS_CONTROL_PACK_STATUS_ROUTE_PATCH_DEPLOYED_VERIFIED

Completed patch: italus_control_pack_status_route_patch

Result:
- Project-local control pack boundary is now exposed through a read-only backend status route.
- No workspace UI wiring was added in this patch.
- No generation or provider execution was enabled.

Next possible phase:
- Review whether workspace bootstrap should include this status payload as locked/read-only readiness data.

## italus_workspace_control_packet_bootstrap_patch

Status: DEPLOYED / VERIFIED

Marker: italus_workspace_control_packet_bootstrap_patch deployed verified

Patch Scope:
- app/services/workspace_service.py only.
- Backend workspace bootstrap payload now includes read-only project-local control packet status.
- No frontend rendering or generation wiring was added.

## italus_workspace_control_packet_readiness_ui_patch

Status: DEPLOYED / VERIFIED

Marker: italus_workspace_control_packet_readiness_ui_patch deployed / verified

Outcome: Workspace now renders control packet readiness as read-only status using existing bootstrap data.

Next gated phase: continue frontend readiness display only, or stop for project state snapshot before any generation-control design.

## Generation Control Status Service

The first Generation Control Layer patch adds an inert service boundary at app/services/generation_control_service.py. It reports generation lock state, readiness inputs, and blocking reasons only. It does not expose an API route or wire generation execution.

## Current Patch: italus_canon_template_questionnaire_service_patch

Purpose:
Create an inert Canon Template Questionnaire Service so future author-facing canon forms can be generated from structured genre schemas.

Scope:
- Backend service boundary only.
- No API route.
- No frontend.
- No author answer persistence.
- No generated packet creation.
- No generation or provider execution.

## Completed: Canon Questionnaire API Route
- The canon questionnaire service is now exposed through read-only API routes.
- Frontend canon workbook and author answer storage remain future phases.

## italus_project_canon_storage_service_patch - DEPLOYED / VERIFIED
- Added project-local author canon storage service boundary.
- Target: app/services/project_canon_service.py.
- Scope: backend storage boundary only; no API route, no frontend, no Markdown rendering, no generation.

## Completed Patch: italus_canon_authoring_workflow_service_patch
- Added backend workflow boundary for project-local author canon section operations.
- The service coordinates questionnaire schema and project-local author canon storage.
- Supported service actions: authoring status, section load, save draft, mark complete, reopen section.
- Next planned layer: read-only/API authoring routes after patch review.

## Current Patch: italus_canon_authoring_api_route_patch
- Status: DEPLOYED / VERIFIED.
- Primary file: app/api/routes/project.py.
- Purpose: expose the validated canon authoring workflow service through bounded API routes.
- Next step: design frontend Canon Workbook only after API behavior is confirmed.

## Next migration checkpoint: Canon Workbook frontend shell
- Status: deployed and verified.
- Patch: italus_canon_workbook_frontend_shell_patch.
- Scope: frontend read-only Canon Workbook shell.
- Next: build a controlled section editor/save UI only after this shell is verified.

PATCH: italus_canon_workbook_section_editor_patch
Scope: frontend Canon Workbook section editor.
Files: frontend/js/canon_authoring.js.
Adds: open section, load section schema, save draft, mark complete, reopen section.
Boundary: uses existing canon authoring API routes only.
Still locked: generation, providers, prompt builder, runtime writes, Markdown rendering, validation/export.

## italus_canon_markdown_renderer_service_patch
- Completed backend Markdown renderer service boundary for completed author canon sections.
- Next planned boundary remains validation/API exposure after renderer verification.
- Generation remains locked.

## italus_canon_markdown_renderer_api_route_patch - 2026-07-15
- Completed: Markdown renderer API route boundary.
- Next: frontend render/status controls or canon validation service after route verification.
- Guard: generation remains locked and packet generation remains deferred.

### Completed: italus_canon_markdown_frontend_controls_patch
- Canon Workbook can now display Markdown source status.
- Authors can request rendering for all completed canon sections or one completed section.
- Next planned layer remains canon validation service after manual frontend validation.

- italus_canon_workbook_field_layout_patch
  - Adds CSS for project-local Canon Workbook field layout.
  - Preserves existing authoring, Markdown rendering, and generation lock behavior.

- COMPLETED: italus_canon_validation_service_patch - backend canon validation service boundary.

PATCH RECORD: italus_canon_validation_api_routes_patch
- Target: app/api/routes/project.py
- Scope: Canon validation API status, full validation, and section validation routes.
- Safety: No frontend, provider, prompt builder, registry, runtime, or packet generation changes.
- Validation: Python compile, exact route checks, service delegation checks, and protected import guard.

- italus_canon_validation_frontend_status_patch: adds Canon Workbook validation status and run controls; no generation unlock.

PATCH RECORD: italus_canon_setup_ux_patch
- Targets: frontend/js/canon_authoring.js and frontend/styles.css
- Scope: Canon Setup workspace sizing, single scroll surface, visible validation progress, and active section reveal/focus.
- Safety: Preserves existing canon authoring, Markdown, validation, storage, and generation lock behavior.
- Validation: Node syntax check, exact UI markers, and protected execution marker guard.

PATCH RECORD: italus_canon_setup_ux_correction_patch
- Targets: frontend/js/canon_authoring.js and frontend/styles.css
- Scope: hidden modal isolation, full-screen Canon Setup, readable validation progress, concise validation findings, and Save Draft return-to-section-list behavior.
- Safety: Preserves existing project lifecycle, canon authoring, Markdown, validation, storage, and generation lock behavior.

PATCH RECORD: italus_canon_packet_generation_service_patch
- Target: app/services/canon_packet_generation_service.py
- Scope: Generate reviewable project-local Markdown canon packets from validated rendered canon sources.
- Gate: Packet generation is blocked until canon validation reports ready_for_packet_generation.
- Safety: No prompt building, provider calls, registry writes, runtime writes, draft persistence, or generation unlock.
