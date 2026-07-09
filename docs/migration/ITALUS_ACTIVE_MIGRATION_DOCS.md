# Italus Active Migration Documentation Set

**Status:** Active control index  
**Patch:** `italus_migration_docs_cleanup_active_set_patch`  
**Scope:** Documentation routing. No application runtime behavior.

## Purpose

This file identifies which migration documents are active for patch planning and which documents are historical references.

Future Morpheus patch planning should use the active set below before consulting archived historical files.

## Active Patch-Planning Documents

- `docs/migration/ITALUS_MIGRATION_PATCH_PLAN.md`
- `docs/migration/ITALUS_PATCH_HISTORY.md`
- `docs/migration/ITALUS_RUNTIME_MIGRATION_CHECKLIST.md`
- `docs/migration/ITALUS_STAGE_ACCEPTANCE_CRITERIA.md`
- `docs/migration/ITALUS_GENERATION_CONTROL_LIFECYCLE.md`

## Historical / Archived Documents

These files are historical references only and must not drive active patch selection:

- `docs/migration/archive/ITALUS_STAGE9_RUNTIME_STORAGE_ARCHITECTURE.md`
- `docs/migration/archive/ITALUS_WORKSPACE_NAVIGATION_GUIDE.md`

## Current Architecture Direction

The active roadmap is now controlled by the Generation Control Lifecycle. The next application patches must follow this order:

1. Application patch zip contains backend/frontend/runtime code changes only.
2. Deploy script applies application changes.
3. Verify script validates the application patch.
4. Docs script finalizes migration docs after approval.
5. Rollback script restores the application patch if needed.

Docs-only architecture patches are allowed only when explicitly declared as docs-only before build.
