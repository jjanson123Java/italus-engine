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

