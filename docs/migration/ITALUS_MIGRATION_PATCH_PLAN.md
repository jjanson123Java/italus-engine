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

