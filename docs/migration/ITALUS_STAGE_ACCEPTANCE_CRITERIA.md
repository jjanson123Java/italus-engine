# Italus Stage Acceptance Criteria

**Status:** Active validation artifact  
**Updated:** 2026-07-08  
**Scope:** Acceptance criteria for staged migration. Documentation only.  
**Current phase:** Stage 9 — Runtime Storage Architecture Review  
**Active alignment patch:** `italus_stage9_docs_actual_workflow_alignment_patch`

## Global Acceptance Rules

Every patch must preserve:

- application startup when applicable
- workspace route when applicable
- Project Lifecycle state
- Canon Approval state
- Runtime Readiness Gate Map
- Gate-to-Panel Navigation
- generation lock
- validation lock
- export lock
- provider execution lock unless explicitly in provider execution stage

## Stage 9 Runtime Storage Acceptance

### Runtime Storage Service

Acceptance:

```text
PASS runtime storage service exists.
PASS runtime storage status route exists.
PASS runtime status reports seven-file contract.
PASS runtime_ready remains controlled.
PASS generation_ready remains false.
```

### Auto Initialization

Acceptance:

```text
PASS New Project creation ensures runtime storage.
PASS Workspace bootstrap idempotently ensures runtime storage.
PASS Missing runtime files are created empty.
PASS Existing runtime files are preserved.
PASS Legacy root data is not copied.
PASS Manual initialize route remains absent.
PASS Manual initialize UI remains absent.
```

### Project Writing Memory UI

Acceptance:

```text
PASS Runtime sidebar exposes Project Writing Memory as status/navigation.
PASS Project Writing Memory does not initialize files.
PASS Runtime Folder card renders normally.
PASS [object Object] is absent.
PASS Seven required runtime files render as status cards.
PASS Generation remains locked.
PASS Validation remains locked.
PASS Export remains locked.
```

### Rollback Acceptance

For rolled-back manual initialization patch:

```text
PASS manual initialize route removed.
PASS manual initialize UI/action removed.
PASS rollback restored runtime storage service baseline.
PASS runtime folder created only by the rolled-back verification was removed when safe.
```

## Current Accepted Stage 9 Patch Results

```text
italus_project_runtime_storage_service_patch: accepted
italus_runtime_storage_initialization_patch: rolled back
italus_runtime_storage_auto_initialize_patch: accepted
italus_runtime_storage_status_ui_object_render_fix_patch: browser-accepted
```

## Non-Acceptance Conditions

Reject any patch that:

```text
adds an author-facing button to create runtime JSON files
copies legacy global data into project runtime files
overwrites existing runtime files during ensure/repair
unlocks generation early
calls providers from Project Writing Memory
routes prompt builder to project runtime before adapter design
runs validation against transient provider output
creates export output before export pipeline migration
implements Author Voice during Stage 9 runtime storage patches
```

## Next Stage Acceptance Target

Next recommended patch:

```text
italus_runtime_registry_adapter_design_docs_patch
```

Acceptance target:

```text
Define how project-local runtime reads/writes will be mediated before generation writes are enabled.
Prevent split-brain runtime state between legacy global registry and project-local runtime files.
Keep generation locked.
```

## Browser Validation Rule

For frontend-only UX defects, browser observation may override a stale verifier pattern check when:

```text
the app is visually corrected
the patched source file contains the intended exact correction
no backend state changed
no runtime data was corrupted
generation remains locked
```

Verifier scripts should still be corrected when they produce false negatives.

## Stage 9 Acceptance — Project Runtime Registry Adapter v2

Acceptance requirements:
- The adapter file exists and compiles.
- The adapter does not duplicate the runtime contract in a new service layer.
- The adapter uses the storage service as the contract source.
- The adapter exposes the universal seven-file contract through runtime helpers.
- The adapter rejects unknown runtime file names.
- The adapter does not wire generation, prompt building, validation, export, or provider execution.
- Protected execution files are unchanged.
- Generation remains locked.

---

## Generation Control Lifecycle Acceptance â€” italus_generation_control_lifecycle_contract_patch_v5

Accepted:
- Generation remains locked.
- Provider execution remains locked.
- Prompt builder remains untouched by this patch.
- Runtime adapter remains inert from generation.
- Runtime JSON content is not modified.
- Frontend generation UI is not wired.
- Contract distinguishes pre-draft direction, post-draft clean review, post-draft warning/block, ordered chapter composition, and chapter narrative spine.
- Future patches must use the documented Patch zip / Deploy script / Verify script / Docs script / Rollback script / All artifacts bundle process.

Next acceptance target:
- Project-local control pack boundary patch.


### Project-Local Control Pack Boundary

Acceptance:

``text
PASS canon_packet_service.py exists as inert service boundary.
PASS service reports packet readiness from template/runtime-context-pack metadata.
PASS service does not generate packets.
PASS service does not call providers.
PASS service does not call prompt_builder.py.
PASS service does not write through app/registry.py.
PASS generation, validation, and export remain locked.
``

## ITALUS_CONTROL_PACK_STATUS_ROUTE_PATCH_DEPLOYED_VERIFIED

Acceptance criteria:
- GET /api/project/{project_id}/canon-packets/status is registered.
- Existing workspace bootstrap and runtime-storage status routes continue to import and compile.
- Returned service status remains read-only and locked.
- No protected execution files are modified.

## Acceptance Criteria — Workspace Control Packet Bootstrap

Marker: italus_workspace_control_packet_bootstrap_patch deployed verified

Accepted when:
- Workspace bootstrap returns canon_packet_status.
- canon_packet_status reports execution locks as false.
- Bootstrap summary returns canon packet counts.
- No provider, prompt_builder, registry, generation, validation, or export path is wired.

## Acceptance: italus_workspace_control_packet_readiness_ui_patch

Status: ACCEPTED AFTER DEPLOY / VERIFY

Marker: italus_workspace_control_packet_readiness_ui_patch deployed / verified

Acceptance criteria:
- Workspace JavaScript passes syntax validation where Node is available.
- Control packet readiness appears using existing bootstrap data.
- No generation, provider, prompt builder, registry, validation, export, or draft persistence wiring is introduced.

## Generation Control Status Service Acceptance

Accepted when:
- app/services/generation_control_service.py compiles.
- The service returns generation_locked true.
- generation_enabled, provider_execution_enabled, prompt_builder_enabled, draft_validation_enabled, approved_persistence_enabled, and export_enabled remain false.
- No protected generation modules are imported.
- No API route, frontend UI, provider call, prompt builder call, validation unlock, export unlock, or runtime persistence is added in this patch.

## Acceptance Criteria â€” italus_canon_template_questionnaire_service_patch

Accepted when:
- `app/services/canon_template_service.py` compiles.
- Template catalog loads.
- Historical Epic / Historical Fantasy questionnaire includes Italus-guided sections.
- All execution lock flags remain false.
- No protected generation imports are present.
- No project data or runtime memory is written by the service.

## Acceptance: Canon Questionnaire API Route
- PASS when questionnaire routes are registered.
- PASS when historical_epic, fantasy_epic, science_fiction, mystery_thriller, memoir, and custom templates load.
- PASS when execution locks remain false.
- FAIL if the route saves author answers, writes runtime memory, calls providers, calls prompt_builder, or unlocks generation.

## italus_project_canon_storage_service_patch - DEPLOYED / VERIFIED
- PASS: project_canon_service.py creates the author canon storage boundary.
- PASS: author_canon.json, template_snapshot.json, and canon_completion.json are project-local.
- PASS: generation and provider execution remain locked.
- PASS: no protected execution files are touched.

## Acceptance Criteria: Canon Authoring Workflow Service
- The application contains app/services/canon_authoring_service.py.
- The service imports no protected generation modules.
- The service can load authoring status.
- The service can save a section draft.
- The service blocks section completion when required fields are missing.
- The service can mark a complete section as complete when required fields are present.
- The service can reopen a completed section.
- The service does not write runtime files.
- The service does not create canon_packs artifacts.
- The service does not call providers, prompt_builder, registry, or generation execution.

## Acceptance Criteria - Canon Authoring API Route Boundary
- Route import passes.
- Expected authoring routes are registered.
- Protected generation imports remain absent.
- Runtime files are not written by route registration.
- Knowledge/control packs are not generated.
- Generation remains locked.

## Acceptance: Canon Workbook frontend shell
- Canon setup modal still renders existing canon setup groups.
- Canon Workbook shell renders authoring section status from the API.
- No author canon answers are saved by this patch.
- No Markdown canon sources or knowledge/control packets are generated.
- Generation, provider execution, prompt builder, registry writes, validation, and export remain locked.

PATCH: italus_canon_workbook_section_editor_patch
Scope: frontend Canon Workbook section editor.
Files: frontend/js/canon_authoring.js.
Adds: open section, load section schema, save draft, mark complete, reopen section.
Boundary: uses existing canon authoring API routes only.
Still locked: generation, providers, prompt builder, runtime writes, Markdown rendering, validation/export.

## italus_canon_markdown_renderer_service_patch
- Acceptance requires Python compile pass, AST protected-import guard pass, and smoke render of completed sections only.
- Verifier must reject runtime and canon_packs side effects.
- Markdown source rendering does not unlock generation or export.

## italus_canon_markdown_renderer_api_route_patch - 2026-07-15
- Acceptance: route import succeeds and Markdown renderer routes are registered.
- Acceptance: routes call canon_markdown_renderer_service only for Markdown rendering operations.
- Acceptance: no protected generation imports are introduced.
- Acceptance: no frontend, runtime, or packet generation files are modified.

### Acceptance: italus_canon_markdown_frontend_controls_patch
- Canon Workbook Markdown status panel appears in frontend.
- Render Completed Sections calls the bounded Markdown renderer API.
- Completed section editor exposes Render Section Markdown only when complete.
- Generation remains locked.

### Acceptance: italus_canon_workbook_field_layout_patch
- Canon Workbook fields are readable and aligned.
- Textareas support paragraph-level canon entry.
- Save Draft, Mark Complete, Reopen, and Render Section Markdown behavior remains unchanged.
- Generation remains locked.

- italus_canon_validation_service_patch: PASS when service compiles, smoke validation writes only canon_validation_report.json, and execution locks remain false.

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
