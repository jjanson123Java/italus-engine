"""
Generation Readiness Gate vNEXT.

This service is the single project-local readiness authority for a requested
book/chapter generation position. It evaluates current project-local planning,
runtime-context, Story Control, Chapter Knowledge Pack, and provenance state.

Primary 32 keeps this gate non-executing: it may authorize project-local
prompt/request construction, but it does not call providers, validate generated
drafts, persist accepted prose, write Approved Continuity, or unlock generation.
Downstream migration boundaries remain explicit blockers.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import WORKSPACE_READY_STATES
from app.services import (
    authorship_provenance_service,
    book_knowledge_pack_service,
    book_plan_service,
    book_scope_service,
    canon_index_service,
    canon_packet_generation_service,
    chapter_knowledge_pack_service,
    chapter_plan_service,
    project_runtime_storage_service,
    story_control_service,
)


GENERATION_CONTROL_SERVICE_MARKER = "generation-readiness-gate-vnext-20260817"
GENERATION_CONTROL_SERVICE_VERSION = "generation_readiness_gate_vnext_v1"
GENERATION_READINESS_SCHEMA_VERSION = "generation_readiness_vnext_v1"

# Primary 32 claims only project-local prompt/request construction.
PROMPT_BUILDER_PROJECT_LOCAL_ROUTING_READY = True
PROVIDER_EXECUTION_READY = False
VALIDATOR_READY = False
AUTHOR_REVIEW_PERSISTENCE_READY = False
APPROVED_CONTINUITY_COMMIT_PATH_READY = False

_UPSTREAM_CHECK_NAMES = {
    "project_loaded",
    "workspace_ready_lifecycle",
    "canon_setup_completed",
    "canon_records_normalized",
    "runtime_storage_ready",
    "project_runtime_context_current_approved",
    "book_scope_current_approved",
    "book_plan_current_approved",
    "book_plan_scope_references_resolved",
    "book_runtime_context_current",
    "chapter_plan_current_ready",
    "story_controls_valid",
    "chapter_knowledge_pack_current",
    "prompt_builder_project_local_routing_ready",
    "provenance_capture_ready",
}


def get_generation_control_contract() -> dict[str, Any]:
    """Return readiness dimensions and the currently locked downstream owners."""

    return {
        "status": "ok",
        "service": GENERATION_CONTROL_SERVICE_MARKER,
        "version": GENERATION_CONTROL_SERVICE_VERSION,
        "schema_version": GENERATION_READINESS_SCHEMA_VERSION,
        "position_required": True,
        "readiness_dimensions": [
            "project_loaded",
            "workspace_ready_lifecycle",
            "canon_setup_completed",
            "canon_records_normalized",
            "runtime_storage_ready",
            "project_runtime_context_current_approved",
            "book_scope_current_approved",
            "book_plan_current_approved",
            "book_plan_scope_references_resolved",
            "book_runtime_context_current",
            "chapter_plan_current_ready",
            "story_controls_valid",
            "chapter_knowledge_pack_current",
            "prompt_builder_project_local_routing_ready",
            "provider_execution_ready",
            "validator_ready",
            "provenance_capture_ready",
            "author_review_persistence_ready",
            "approved_continuity_commit_path_ready",
        ],
        "patch_29_locks": {
            "prompt_builder_project_local_routing_ready": True,
            "provider_execution_ready": False,
            "validator_ready": False,
            "author_review_persistence_ready": False,
            "approved_continuity_commit_path_ready": False,
        },
        "message": (
            "Generation Readiness Gate vNEXT is authoritative for readiness "
            "reporting. Provider execution remains locked until downstream "
            "migration owners are complete."
        ),
    }


def get_generation_control_status(
    project_id: str,
    *,
    book_number: int | None = None,
    chapter_number: int | None = None,
) -> dict[str, Any]:
    """Return the read-only Generation Readiness Gate vNEXT status."""

    manifest_obj = project_loader.load_manifest(project_id)
    manifest = manifest_obj.to_dict()
    context = build_project_context(manifest_obj)
    wizard_state = project_loader.load_wizard_state(project_id) or {}
    runtime_storage_status = (
        project_runtime_storage_service.get_runtime_storage_status_for_context(context)
    )

    return get_generation_control_status_for_context(
        context,
        manifest,
        wizard_state=wizard_state,
        runtime_storage_status=runtime_storage_status,
        book_number=book_number,
        chapter_number=chapter_number,
    )


def get_generation_control_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    wizard_state: dict[str, Any] | None = None,
    runtime_storage_status: dict[str, Any] | None = None,
    canon_packet_status: dict[str, Any] | None = None,
    *,
    book_number: int | None = None,
    chapter_number: int | None = None,
) -> dict[str, Any]:
    """Compose the authoritative read-only readiness report.

    ``canon_packet_status`` is retained only for backward call compatibility
    with the previous inert boundary. Patch 29 no longer uses legacy packet
    readiness as a generation authorization condition.
    """

    del canon_packet_status

    manifest_payload = dict(manifest or {})
    wizard_payload = dict(wizard_state or {})
    runtime_status = runtime_storage_status or (
        project_runtime_storage_service.get_runtime_storage_status_for_context(context)
    )

    lifecycle_state = str(manifest_payload.get("lifecycle_state") or "")
    workspace_ready = lifecycle_state in WORKSPACE_READY_STATES
    canon_setup_completed = bool(wizard_payload.get("canon_setup_completed"))
    runtime_storage_ready = bool(
        runtime_status.get("initialized") and runtime_status.get("required_files_present")
    )

    index_status = canon_index_service.get_index_status_for_context(context)
    index_current = bool(
        index_status.get("index_state") == "current"
        and index_status.get("fresh") is True
    )

    project_runtime = (
        canon_packet_generation_service.get_project_runtime_context_status_for_context(
            context,
            manifest_payload,
        )
    )
    project_runtime_ready = bool(
        project_runtime.get("status")
        == canon_packet_generation_service.STATUS_CURRENT
        and project_runtime.get("artifact_current") is True
        and project_runtime.get("approval_status")
        == canon_packet_generation_service.APPROVAL_APPROVED
        and project_runtime.get("approval_fresh") is True
    )

    scope_status = book_scope_service.get_book_scope_status(context.project_id)
    plan_status = book_plan_service.get_book_plan_status_for_context(
        context,
        manifest_payload,
    )
    plan_result = book_plan_service.get_book_plan_for_context(
        context,
        manifest_payload,
    )
    plan_payload = dict(plan_result.get("plan") or {})
    provenance_status = authorship_provenance_service.get_provenance_status_for_context(
        context
    )

    max_book = max(1, int(manifest_payload.get("book_count") or 1))
    max_chapter = max(1, int(manifest_payload.get("chapters_per_book") or 1))
    position_ready = bool(
        isinstance(book_number, int)
        and isinstance(chapter_number, int)
        and 1 <= book_number <= max_book
        and 1 <= chapter_number <= max_chapter
    )

    scope_book: dict[str, Any] | None = None
    runtime_book: dict[str, Any] | None = None
    requested_plan_validation: dict[str, Any] = {}
    requested_plan_workflow: dict[str, Any] = {}
    requested_plan_issues: list[dict[str, Any]] = []
    chapter: dict[str, Any] | None = None
    control_validation: dict[str, Any] = {
        "valid": False,
        "issues": [{"code": "generation_position_missing"}],
        "controls": [],
        "registry_revision": 0,
        "registry_content_hash": "",
    }
    chapter_pack_status: dict[str, Any] = {
        "status": "blocked",
        "compiler_ready": False,
        "pack": {"exists": False, "current": False},
        "blockers": [{"code": "generation_position_missing"}],
    }

    if position_ready:
        scope_book = next(
            (
                item
                for item in scope_status.get("books") or []
                if int(item.get("book_number") or 0) == int(book_number)
            ),
            None,
        )
        requested_plan_validation = next(
            (
                dict(item)
                for item in (plan_payload.get("validation") or {}).get("books") or []
                if int(item.get("book_number") or 0) == int(book_number)
            ),
            {},
        )
        requested_plan_workflow = next(
            (
                dict(item)
                for item in plan_payload.get("book_workflow") or []
                if int(item.get("book_number") or 0) == int(book_number)
            ),
            {},
        )
        requested_plan_issues = [
            deepcopy(item)
            for item in (plan_payload.get("validation") or {}).get("issues") or []
            if not item.get("book_number")
            or int(item.get("book_number") or 0) == int(book_number)
        ]
        if index_current:
            requested_book_runtime = (
                book_knowledge_pack_service.get_book_runtime_context_status_for_context(
                    context,
                    manifest_payload,
                    book_number=int(book_number),
                )
            )
            runtime_book = next(
                (
                    item
                    for item in requested_book_runtime.get("targets") or []
                    if int(item.get("book_number") or 0) == int(book_number)
                ),
                None,
            )
        chapter_result = chapter_plan_service.get_chapter(
            context.project_id,
            book_number=int(book_number),
            chapter_number=int(chapter_number),
        )
        chapter = dict(chapter_result.get("chapter") or {})
        control_validation = story_control_service.validate_story_control_refs(
            context.project_id,
            book_number=int(book_number),
            chapter_number=int(chapter_number),
            control_ids=list(chapter.get("story_control_refs") or []),
        )
        chapter_pack_status = (
            chapter_knowledge_pack_service.get_chapter_knowledge_pack_status_for_context(
                context,
                manifest_payload,
                book_number=int(book_number),
                chapter_number=int(chapter_number),
            )
        )

    scope_ready = bool(
        position_ready
        and scope_book
        and scope_book.get("valid") is True
        and scope_book.get("approval_status") == book_scope_service.APPROVAL_APPROVED
        and scope_book.get("approval_fresh") is True
        and scope_book.get("source_fresh") is True
        and not scope_book.get("reconciliation_required")
    )

    plan_ready = bool(
        position_ready
        and requested_plan_validation.get("complete") is True
        and requested_plan_validation.get("book_scope_approved") is True
        and requested_plan_workflow.get("approval_status")
        == book_plan_service.APPROVAL_APPROVED
        and requested_plan_workflow.get("approval_fresh") is True
        and not plan_status.get("migration_required")
        and bool(requested_plan_workflow.get("approved_content_hash"))
        and requested_plan_workflow.get("approved_content_hash")
        == requested_plan_workflow.get("content_hash")
    )

    references_resolved = bool(
        plan_ready
        and scope_ready
        and not plan_status.get("migration_required")
        and not requested_plan_issues
    )

    runtime_book_ready = bool(
        position_ready
        and runtime_book
        and runtime_book.get("status") == book_knowledge_pack_service.STATUS_CURRENT
        and bool(runtime_book.get("sha256"))
    )

    chapter_ready = bool(
        position_ready
        and chapter
        and chapter.get("lifecycle_state") == chapter_plan_service.CHAPTER_STATUS_COMPLETE
        and (chapter.get("validation") or {}).get("valid") is True
        and (chapter.get("freshness") or {}).get("fresh") is True
        and (chapter.get("generation_readiness") or {}).get("ready") is True
    )

    controls_ready = bool(position_ready and control_validation.get("valid") is True)

    chapter_pack_ready = bool(
        position_ready
        and chapter_pack_status.get("status")
        == chapter_knowledge_pack_service.STATUS_CURRENT
        and chapter_pack_status.get("compiler_ready") is True
        and (chapter_pack_status.get("pack") or {}).get("current") is True
        and bool((chapter_pack_status.get("pack") or {}).get("sha256"))
    )

    provenance_ready = bool(
        provenance_status.get("provenance_capture_ready") is True
        and provenance_status.get("integrity_status") == "ok"
    )

    canon_records_normalized = bool(
        canon_setup_completed
        and index_current
        and not plan_status.get("migration_required")
    )

    checks = [
        _readiness_check(
            "project_loaded",
            True,
            "project_not_loaded",
            "Project manifest and ProjectContext loaded.",
        ),
        _readiness_check(
            "workspace_ready_lifecycle",
            workspace_ready,
            "workspace_lifecycle_not_ready",
            f"Lifecycle state is {lifecycle_state or 'unknown'}.",
        ),
        _readiness_check(
            "canon_setup_completed",
            canon_setup_completed,
            "canon_setup_incomplete",
            (
                "Canon Setup completion is confirmed."
                if canon_setup_completed
                else "Canon Setup completion is not confirmed."
            ),
        ),
        _readiness_check(
            "canon_records_normalized",
            canon_records_normalized,
            "canon_records_not_normalized",
            (
                "Canon Index is current and stable-reference migration is resolved."
                if canon_records_normalized
                else "Canon Index/stable-reference state is not ready for generation."
            ),
            details={
                "index_state": index_status.get("index_state"),
                "index_fresh": bool(index_status.get("fresh")),
                "book_plan_migration_required": bool(
                    plan_status.get("migration_required")
                ),
            },
        ),
        _readiness_check(
            "runtime_storage_ready",
            runtime_storage_ready,
            "runtime_storage_not_ready",
            (
                "Project-local runtime storage is initialized."
                if runtime_storage_ready
                else "Project-local runtime storage is not initialized/current."
            ),
        ),
        _readiness_check(
            "project_runtime_context_current_approved",
            project_runtime_ready,
            "project_runtime_context_not_current_approved",
            (
                "Project Runtime Context is current and approval-fresh."
                if project_runtime_ready
                else "Project Runtime Context must be current and approval-fresh."
            ),
            details={
                "status": project_runtime.get("status"),
                "approval_status": project_runtime.get("approval_status"),
                "approval_fresh": bool(project_runtime.get("approval_fresh")),
            },
        ),
        _readiness_check(
            "book_scope_current_approved",
            scope_ready,
            "book_scope_not_current_approved",
            (
                f"Book {book_number} Canon is current and approved."
                if scope_ready
                else "Requested Book Canon must be valid, current, and approved."
            ),
            details=deepcopy(scope_book or {}),
        ),
        _readiness_check(
            "book_plan_current_approved",
            plan_ready,
            "book_plan_not_current_approved",
            (
                f"Book {book_number} Plan is current and approval-fresh."
                if plan_ready
                else "Requested Book Plan must be complete, current, and approval-fresh."
            ),
            details={
                "book_number": book_number,
                "complete": bool(requested_plan_validation.get("complete")),
                "reference_issue_count": int(
                    requested_plan_validation.get("reference_issue_count") or 0
                ),
                "approval_status": requested_plan_workflow.get("approval_status"),
                "approval_fresh": bool(
                    requested_plan_workflow.get("approval_fresh")
                ),
                "content_hash": str(
                    requested_plan_workflow.get("content_hash") or ""
                ),
                "approved_content_hash": str(
                    requested_plan_workflow.get("approved_content_hash") or ""
                ),
                "migration_required": bool(plan_status.get("migration_required")),
            },
        ),
        _readiness_check(
            "book_plan_scope_references_resolved",
            references_resolved,
            "book_plan_scope_references_unresolved",
            (
                "Book Plan / Book Canon references are resolved."
                if references_resolved
                else "Book Plan / Book Canon reference reconciliation is incomplete."
            ),
            details={"issues": deepcopy(requested_plan_issues)},
        ),
        _readiness_check(
            "book_runtime_context_current",
            runtime_book_ready,
            "book_runtime_context_not_current",
            (
                f"Book {book_number} Runtime Context v2 is current."
                if runtime_book_ready
                else "Requested Book Runtime Context v2 must be compiled and current."
            ),
            details=deepcopy(runtime_book or {}),
        ),
        _readiness_check(
            "chapter_plan_current_ready",
            chapter_ready,
            "chapter_plan_not_current_ready",
            (
                f"Book {book_number}, Chapter {chapter_number} Plan is current and ready."
                if chapter_ready
                else "Requested Chapter Plan must be complete, valid, fresh, and dependency-ready."
            ),
            details=_chapter_readiness_details(chapter),
        ),
        _readiness_check(
            "story_controls_valid",
            controls_ready,
            "story_controls_invalid",
            (
                "Selected Story Controls are valid."
                if controls_ready
                else "Selected Story Controls are invalid or the generation position is unresolved."
            ),
            details={
                "issues": deepcopy(control_validation.get("issues") or []),
                "control_count": len(control_validation.get("controls") or []),
                "registry_revision": int(
                    control_validation.get("registry_revision") or 0
                ),
                "registry_content_hash": str(
                    control_validation.get("registry_content_hash") or ""
                ),
            },
        ),
        _readiness_check(
            "chapter_knowledge_pack_current",
            chapter_pack_ready,
            "chapter_knowledge_pack_not_current",
            (
                "Chapter Knowledge Pack is current."
                if chapter_pack_ready
                else "Chapter Knowledge Pack must be compiled and current."
            ),
            details={
                "status": chapter_pack_status.get("status"),
                "compiler_ready": bool(
                    chapter_pack_status.get("compiler_ready")
                ),
                "pack": deepcopy(chapter_pack_status.get("pack") or {}),
                "blockers": deepcopy(chapter_pack_status.get("blockers") or []),
            },
        ),
        _readiness_check(
            "prompt_builder_project_local_routing_ready",
            PROMPT_BUILDER_PROJECT_LOCAL_ROUTING_READY,
            "prompt_builder_project_local_routing_not_ready",
            "Primary 32 project-local Prompt Builder routing is ready and has no legacy-pack fallback.",
        ),
        _readiness_check(
            "provider_execution_ready",
            PROVIDER_EXECUTION_READY,
            "provider_execution_not_ready",
            "Primary 33.2 provider execution / immutable MODEL-origin wiring is not yet enabled.",
        ),
        _readiness_check(
            "validator_ready",
            VALIDATOR_READY,
            "validator_not_ready",
            "Primary 34 structured validator migration is not yet complete.",
        ),
        _readiness_check(
            "provenance_capture_ready",
            provenance_ready,
            "provenance_capture_not_ready",
            (
                "Immutable provenance capture storage/integrity is ready."
                if provenance_ready
                else "Provenance capture storage/integrity is not ready."
            ),
            details={
                "initialized": bool(provenance_status.get("initialized")),
                "integrity_status": provenance_status.get("integrity_status"),
                "provenance_capture_ready": bool(
                    provenance_status.get("provenance_capture_ready")
                ),
            },
        ),
        _readiness_check(
            "author_review_persistence_ready",
            AUTHOR_REVIEW_PERSISTENCE_READY,
            "author_review_persistence_not_ready",
            "Primary 34 author review/edit/reject persistence is not yet migrated.",
        ),
        _readiness_check(
            "approved_continuity_commit_path_ready",
            APPROVED_CONTINUITY_COMMIT_PATH_READY,
            "approved_continuity_commit_path_not_ready",
            "Primary 36 accepted-prose Approved Continuity commit path is not yet enabled.",
        ),
    ]

    blockers = [
        {
            "code": item["code"],
            "check": item["name"],
            "message": item["message"],
        }
        for item in checks
        if item["required"] and not item["ready"]
    ]
    ready = not blockers
    upstream_checks = [item for item in checks if item["name"] in _UPSTREAM_CHECK_NAMES]
    upstream_ready = bool(upstream_checks) and all(item["ready"] for item in upstream_checks)

    return {
        "status": "ready" if ready else "blocked",
        "service": GENERATION_CONTROL_SERVICE_MARKER,
        "version": GENERATION_CONTROL_SERVICE_VERSION,
        "schema_version": GENERATION_READINESS_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "lifecycle_state": lifecycle_state,
        "requested_position": {
            "book_number": book_number,
            "chapter_number": chapter_number,
            "valid": position_ready,
            "book_count": max_book,
            "chapters_per_book": max_chapter,
        },
        "ready": ready,
        "upstream_ready": upstream_ready,
        "generation_locked": True,
        "provider_execution_locked": True,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": True,
        "draft_validation_enabled": False,
        "approved_persistence_enabled": False,
        "readiness": checks,
        "readiness_summary": {
            "ready_count": sum(1 for item in checks if item["ready"]),
            "total_count": len(checks),
            "blocker_count": len(blockers),
            "upstream_ready": upstream_ready,
            "downstream_pipeline_ready": False,
            "provenance_capture_ready": provenance_ready,
        },
        "blockers": blockers,
        "upstream_blockers": [
            {
                "code": item["code"],
                "check": item["name"],
                "message": item["message"],
            }
            for item in upstream_checks
            if item["required"] and not item["ready"]
        ],
        "blocking_reasons": [item["message"] for item in blockers],
        "dependency_state": {
            "runtime_storage": deepcopy(runtime_status),
            "canon_index": deepcopy(index_status),
            "project_runtime_context": deepcopy(project_runtime),
            "book_scope": deepcopy(scope_book or {}),
            "book_plan": deepcopy(plan_status),
            "book_runtime_context": deepcopy(runtime_book or {}),
            "chapter_plan": _chapter_readiness_details(chapter),
            "story_controls": {
                "valid": bool(control_validation.get("valid")),
                "issues": deepcopy(control_validation.get("issues") or []),
                "registry_revision": int(
                    control_validation.get("registry_revision") or 0
                ),
                "registry_content_hash": str(
                    control_validation.get("registry_content_hash") or ""
                ),
            },
            "chapter_knowledge_pack": deepcopy(chapter_pack_status),
            "provenance": deepcopy(provenance_status),
            "downstream_migration": {
                "prompt_builder_project_local_routing_ready": True,
                "provider_execution_ready": False,
                "validator_ready": False,
                "author_review_persistence_ready": False,
                "approved_continuity_commit_path_ready": False,
            },
        },
        "future_boundaries": {
            "prompt_builder_migration": "primary_32_ready",
            "provider_execution": "primary_33_2_locked",
            "validator_and_author_review": "primary_34_locked",
            "approved_continuity_commit": "primary_36_locked",
        },
        "message": (
            "Generation readiness is satisfied."
            if ready
            else (
                "Upstream project-local generation inputs are ready; downstream "
                "migration boundaries still lock provider execution."
                if upstream_ready
                else "Generation readiness is blocked by project-local dependencies."
            )
        ),
    }


def _readiness_check(
    name: str,
    ready: bool,
    code: str,
    message: str,
    *,
    required: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "required": bool(required),
        "ready": bool(ready),
        "status": "ready" if ready else "blocked",
        "code": code,
        "message": message,
        "details": deepcopy(details or {}),
    }


def _chapter_readiness_details(
    chapter: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(chapter or {})
    return {
        "exists": bool(payload),
        "status": payload.get("status"),
        "lifecycle_state": payload.get("lifecycle_state"),
        "revision": int(payload.get("revision") or 0),
        "content_hash": str(payload.get("content_hash") or ""),
        "validation": deepcopy(payload.get("validation") or {}),
        "freshness": deepcopy(payload.get("freshness") or {}),
        "generation_readiness": deepcopy(
            payload.get("generation_readiness") or {}
        ),
        "story_control_refs": list(payload.get("story_control_refs") or []),
    }
