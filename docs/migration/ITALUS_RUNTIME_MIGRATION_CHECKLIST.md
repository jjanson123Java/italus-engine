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

