# Italus Patch History

**Status:** Active migration history  
**Updated:** 2026-07-08  
**Scope:** Patch history artifact. Documentation only.  
**Current phase:** Stage 9 — Runtime Storage Architecture Review  
**Active alignment patch:** `italus_stage9_docs_actual_workflow_alignment_patch`

## Current State

```text
Stage 9 active — Runtime Storage Architecture Review
Runtime storage auto-initialization validated
Project Writing Memory status UI visible
Generation locked
Validation locked
Export locked
```

## Validated Active Milestones

- Project lifecycle flow
- Canon setup / approval
- Workspace bootstrap
- Runtime Readiness Gate Map
- Gate-to-Panel Navigation v2
- Migration stage documentation artifacts
- Provider Configuration Status Panel
- Provider Author View
- Provider Author Language Cleanup
- Runtime Storage Preview
- Runtime Storage Author UX
- Validation / Export Readiness Panels
- Validation / Export Contrast Fix
- Stage 8 Docs Alignment
- Stage 9 Architecture Control Docs v4
- Project Runtime Storage Service
- Runtime Storage Auto Initialization
- Project Writing Memory object-render UI fix

## Stage 9 Patch History

### `italus_stage9_architecture_control_docs_patch_v4`

Status:

```text
VALIDATED
```

Summary:

```text
Recorded Stage 9 runtime storage architecture controls and seven-file runtime contract.
```

### `italus_project_runtime_storage_service_patch`

Status:

```text
VALIDATED
```

Summary:

```text
Added backend runtime storage status service and status route.
Added Project Writing Memory status payload.
Did not create runtime files.
Did not unlock generation.
```

### `italus_runtime_storage_initialization_patch`

Status:

```text
ROLLED BACK
```

Summary:

```text
Introduced manual runtime initialization behavior.
Rollback was approved because authors should not initialize infrastructure files from the workspace UI.
Runtime file creation belongs in New Project creation and workspace bootstrap.
```

Rollback result:

```text
Manual initialize route removed.
Manual initialize UI/action removed.
Runtime folder created by live verification removed.
Runtime storage service baseline preserved.
```

### `italus_runtime_storage_auto_initialize_patch`

Status:

```text
VALIDATED
```

Summary:

```text
Moved runtime storage initialization into backend lifecycle.
New Project creation ensures runtime storage.
Workspace bootstrap idempotently ensures/repairs runtime storage.
Manual initialize route remains absent.
Manual initialize wording/action remains absent.
Project Writing Memory is status navigation only.
```

Validation highlights:

```text
Runtime folder auto-created during live workspace bootstrap.
Seven empty runtime JSON files created.
Existing runtime files preserved.
Generation remains locked.
Validation remains locked.
Export remains locked.
```

### `italus_runtime_storage_status_ui_object_render_fix_patch`

Status:

```text
DEPLOYED / BROWSER-CONFIRMED
```

Summary:

```text
Fixed frontend rendering defect where the Project Writing Memory panel displayed [object Object].
Runtime Folder now renders as a normal status card.
No backend lifecycle behavior changed.
```

Validation note:

```text
Browser confirms [object Object] is gone.
A verifier script false-negative was observed against a renderer-pattern check.
Application state is accepted; verifier script may need future correction if retained.
```

## Current User-Facing Runtime Navigation

Workspace Runtime sidebar includes:

```text
Project Writing Memory
Memory / Continuity
Validation
Output
```

Project Writing Memory is a status panel only. It does not create files and does not unlock generation.

## Current Runtime Files

Runtime storage root:

```text
data/projects/<project_id>/runtime/
```

Required empty containers:

```text
books.json
chapters.json
scenes.json
session_state.json
coverage_map.json
book_state.json
chapter_continuity_digests.json
```

## Next Planned Patch

```text
italus_runtime_registry_adapter_design_docs_patch
```

Reason:

```text
Before generation can write to project-local runtime files, the registry adapter boundary must be designed to prevent split-brain reads/writes.
```

## italus_project_runtime_registry_adapter_patch_v2

Status: planned / deployment validation required.

Scope:
- Added `app/services/project_runtime_registry_adapter.py`.
- Updated migration documentation to record the adapter boundary.

Decision:
- The adapter does not create runtime files.
- Runtime file creation remains owned by `project_runtime_storage_service.py`.
- The adapter reuses the storage service contract and provides controlled read/write helpers for future runtime migration.
- The adapter is inert from `project_runner.py`, `prompt_builder.py`, and `app/registry.py`.

Validation required:
- Adapter imports and compiles.
- Adapter exposes the approved contract through `runtime_file_names()`.
- Unknown runtime file names are rejected.
- Default payloads are deep-copied from storage service defaults.
- Protected execution files remain untouched.

---

## italus_generation_control_lifecycle_contract_patch_v5

Status: deployed / verified / docs-finalized.

Summary:
- Added `docs/migration/ITALUS_GENERATION_CONTROL_LIFECYCLE.md`.
- Reconciled the existing patch roadmap with the new Generation Control Layer.
- Preserved runtime adapter as approved-text persistence boundary.
- Preserved generation lock and protected runtime execution boundaries.
- Confirmed the patch process includes Patch zip, Deploy script, Verify script, Docs script, Rollback script, and All artifacts bundle.


### italus_project_local_control_pack_boundary_patch

Status:

``text
DEPLOYED / VERIFIED
``

Summary:

``text
Added inert project-local canon/control packet service boundary in app/services/canon_packet_service.py.
The patch reports expected project-local runtime/control pack readiness without generating packs, calling providers, calling prompt_builder.py, writing app/registry.py, or unlocking generation.
``

## ITALUS_CONTROL_PACK_STATUS_ROUTE_PATCH_DEPLOYED_VERIFIED

Patch: italus_control_pack_status_route_patch

Status: DEPLOYED / VERIFIED

Summary:
- Added a read-only API route for project-local canon/control packet status.
- Route: GET /api/project/{project_id}/canon-packets/status
- The route delegates to app/services/canon_packet_service.py.
- Generation, provider execution, prompt_builder, registry writes, validation, export, and draft persistence remain locked.

## italus_workspace_control_packet_bootstrap_patch

Status: DEPLOYED / VERIFIED

Marker: italus_workspace_control_packet_bootstrap_patch deployed verified

Summary:
- Added read-only canon_packet_status to workspace bootstrap payload.
- Added compact canon packet counts to bootstrap summary.
- Preserved generation, validation, export, provider, prompt_builder, and registry locks.

## italus_workspace_control_packet_readiness_ui_patch

Status: DEPLOYED / VERIFIED

Marker: italus_workspace_control_packet_readiness_ui_patch deployed / verified

- Added read-only workspace display of project-local control packet readiness.
- Used existing workspace bootstrap canon_packet_status payload.
- Did not wire generation, providers, prompt builder, registry writes, validation, export, or draft persistence.

## italus_generation_control_status_service_patch

Status: deployed / verified

Scope:
- Added app/services/generation_control_service.py as an inert read-only Generation Control Status Service.
- No API route, workspace bootstrap wiring, frontend UI, provider calls, prompt builder calls, draft validation, approved persistence, validation unlock, or export unlock.

Controls:
- generation_enabled remains false.
- provider_execution_enabled remains false.
- prompt_builder_enabled remains false.
- draft_validation_enabled remains false.
- approved_persistence_enabled remains false.
- export_enabled remains false.

Marker: italus_generation_control_status_service_patch deployed / verified

## italus_canon_template_questionnaire_service_patch

Status: DEPLOYED / VERIFIED

Summary:
- Added `app/services/canon_template_service.py`.
- Introduced a read-only canon-building questionnaire boundary for genre templates.
- Added universal canon sections and expandable genre-specific questionnaire schemas.
- Historical Epic / Historical Fantasy is guided by current Italus canon structures.
- No author answer storage, frontend rendering, generation, providers, prompt builder, registry writes, runtime persistence, validation unlock, or export unlock were added.

## italus_canon_questionnaire_api_route_patch - DEPLOYED / VERIFIED
- Exposed read-only canon questionnaire template routes.
- Added GET /api/templates/canon-questionnaires.
- Added GET /api/templates/base/canon-questionnaire.
- Added GET /api/templates/{template_id}/canon-questionnaire.
- No author answers are saved.
- No project canon files are created.
- No generation, provider, prompt_builder, registry, validation, export, or runtime write behavior was introduced.

## italus_project_canon_storage_service_patch - DEPLOYED / VERIFIED
- Deployed and verified project-local author canon storage boundary.
- Creates author_canon.json, template_snapshot.json, and canon_completion.json only when service is explicitly called.
- Preserves generation, provider execution, prompt builder, registry writes, validation, export, and draft persistence locks.

## italus_canon_authoring_workflow_service_patch - DEPLOYED / VERIFIED
- Status: DEPLOYED / VERIFIED
- Scope: Added inert backend canon authoring workflow service.
- Primary file: app/services/canon_authoring_service.py
- Behavior: section status loads, draft save works, incomplete required fields block completion, complete and reopen flows are supported.
- Controls: no routes, no frontend, no Markdown rendering, no knowledge packet generation, no runtime writes, no provider calls, no prompt_builder calls, no registry writes, no generation unlock.

## italus_canon_authoring_api_route_patch - DEPLOYED / VERIFIED
- Exposed project-local canon authoring workflow routes.
- Added section draft, complete, reopen, and authoring status API boundaries.
- Route layer delegates to canon_authoring_service only.
- No frontend, Markdown rendering, knowledge pack generation, provider calls, prompt builder calls, runtime writes, or generation unlocks were introduced.

## italus_canon_workbook_frontend_shell_patch - DEPLOYED / VERIFIED
- Added frontend Canon Workbook shell for read-only canon authoring status.
- Added frontend/js/canon_authoring.js.
- Updated frontend/index.html to load canon_authoring.js before project_lifecycle.js.
- Updated project lifecycle canon setup rendering to include the Canon Workbook shell container.
- No author answer saving, Markdown rendering, packet generation, provider execution, or generation unlock was introduced.

PATCH: italus_canon_workbook_section_editor_patch
Scope: frontend Canon Workbook section editor.
Files: frontend/js/canon_authoring.js.
Adds: open section, load section schema, save draft, mark complete, reopen section.
Boundary: uses existing canon authoring API routes only.
Still locked: generation, providers, prompt builder, runtime writes, Markdown rendering, validation/export.

## italus_canon_markdown_renderer_service_patch
- Adds app/services/canon_markdown_renderer_service.py as an inert project-local Markdown source renderer.
- Renders completed author canon sections only into data/projects/<project_id>/canon/canon_sources/*.md.
- Does not create knowledge packs, control packets, runtime memory, generated drafts, exports, providers, prompt builder calls, or registry writes.

## italus_canon_markdown_renderer_api_route_patch - 2026-07-15
- Added bounded Markdown renderer API routes in app/api/routes/project.py.
- Exposed renderer status, render-all-completed, and render-single-section actions.
- Writes remain limited to project-local canon_sources Markdown files through the renderer service.
- No frontend, packet generation, runtime memory, provider, prompt_builder, registry, or generation unlock changes.

## Patch: italus_canon_markdown_frontend_controls_patch
- Added frontend Canon Workbook controls for Markdown renderer status and render actions.
- Scope: frontend/js/canon_authoring.js only.
- Backend, generation, providers, prompt builder, registry, runtime memory, validation, export, and packet generation remain locked.

### italus_canon_workbook_field_layout_patch
- Added Canon Workbook field layout styling.
- Canon section labels now align above their inputs.
- Long-form canon fields now use larger textarea presentation through existing markup hooks.
- Scope limited to frontend/styles.css.

## MORPHEUS PATCH RECORD: italus_canon_validation_service_patch
- Added backend-only project-local canon validation service.
- Added validation report boundary at data/projects/<project_id>/canon/canon_validation_report.json.
- Preserved generation, provider, prompt-builder, runtime-write, and packet-generation locks.

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
