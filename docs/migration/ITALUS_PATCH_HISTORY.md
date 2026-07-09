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

