"""
Generation control status service.

This service is an inert migration boundary for future generation readiness.
It reports why generation remains locked and which prerequisites are present.

It does not generate content, build prompts, call providers, validate drafts,
persist drafts, write runtime memory, export files, or unlock generation.
"""

from __future__ import annotations

from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import WORKSPACE_READY_STATES
from app.services import canon_packet_service, project_runtime_storage_service


GENERATION_CONTROL_SERVICE_MARKER = "generation-control-boundary-20260714"
GENERATION_CONTROL_SERVICE_VERSION = "stage10_inert_generation_control_status_v1"


def get_generation_control_status(project_id: str) -> dict[str, Any]:
    """Return read-only generation control status for an existing project.

    The project manifest and wizard state are loaded to evaluate readiness.
    No generation files are imported or called.
    """

    manifest = project_loader.load_manifest(project_id)
    manifest_payload = manifest.to_dict()
    wizard_state = project_loader.load_wizard_state(project_id)
    context = build_project_context(manifest)

    runtime_storage_status = project_runtime_storage_service.get_runtime_storage_status_for_context(context)
    packet_status = canon_packet_service.get_canon_packet_status_for_context(context, manifest_payload)

    return get_generation_control_status_for_context(
        context,
        manifest_payload,
        wizard_state=wizard_state,
        runtime_storage_status=runtime_storage_status,
        canon_packet_status=packet_status,
    )


def get_generation_control_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    wizard_state: dict[str, Any] | None = None,
    runtime_storage_status: dict[str, Any] | None = None,
    canon_packet_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a compact locked generation-control status payload.

    This function accepts preloaded status payloads so future workspace bootstrap
    code can compose the status without reloading project files.
    """

    manifest_payload = dict(manifest or {})
    wizard_payload = dict(wizard_state or {})
    runtime_status = runtime_storage_status or project_runtime_storage_service.get_runtime_storage_status_for_context(context)
    packet_status = canon_packet_status or canon_packet_service.get_canon_packet_status_for_context(
        context,
        manifest_payload,
    )

    lifecycle_state = str(manifest_payload.get("lifecycle_state") or "")
    workspace_ready_lifecycle = lifecycle_state in WORKSPACE_READY_STATES
    canon_setup_completed = bool(wizard_payload.get("canon_setup_completed"))
    runtime_storage_ready = bool(
        runtime_status.get("initialized")
        or runtime_status.get("required_files_present")
    )
    canon_packets_ready = bool(packet_status.get("packet_ready"))

    readiness_checks = [
        _readiness_check(
            "project_loaded",
            True,
            "Project manifest loaded.",
        ),
        _readiness_check(
            "workspace_ready_lifecycle",
            workspace_ready_lifecycle,
            f"Lifecycle state is {lifecycle_state or 'unknown'}.",
        ),
        _readiness_check(
            "canon_setup_completed",
            canon_setup_completed,
            "Canon setup completion flag is present." if canon_setup_completed else "Canon setup is incomplete or not confirmed.",
        ),
        _readiness_check(
            "runtime_storage_ready",
            runtime_storage_ready,
            "Project-local runtime storage contract is present." if runtime_storage_ready else "Project-local runtime storage is not ready.",
        ),
        _readiness_check(
            "canon_packet_status_loaded",
            packet_status.get("status") == "ok",
            "Project-local control packet status loaded.",
        ),
        _readiness_check(
            "canon_packets_ready",
            canon_packets_ready,
            "Required project-local control packets are present." if canon_packets_ready else "Required project-local control packets are missing.",
        ),
    ]

    blocking_reasons = _blocking_reasons(
        workspace_ready_lifecycle=workspace_ready_lifecycle,
        canon_setup_completed=canon_setup_completed,
        runtime_storage_ready=runtime_storage_ready,
        canon_packets_ready=canon_packets_ready,
        packet_status=packet_status,
    )

    return {
        "status": "ok",
        "service": GENERATION_CONTROL_SERVICE_MARKER,
        "version": GENERATION_CONTROL_SERVICE_VERSION,
        "project_id": context.project_id,
        "template_id": context.template_id,
        "lifecycle_state": lifecycle_state,
        "generation_locked": True,
        "provider_execution_locked": True,
        "prompt_builder_locked": True,
        "draft_validation_locked": True,
        "approved_persistence_locked": True,
        "export_locked": True,
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "draft_validation_enabled": False,
        "approved_persistence_enabled": False,
        "export_enabled": False,
        "readiness": readiness_checks,
        "readiness_summary": {
            "ready_count": sum(1 for item in readiness_checks if item["ready"]),
            "total_count": len(readiness_checks),
            "workspace_ready_lifecycle": workspace_ready_lifecycle,
            "canon_setup_completed": canon_setup_completed,
            "runtime_storage_ready": runtime_storage_ready,
            "canon_packets_ready": canon_packets_ready,
            "canon_packet_missing_required_count": int(packet_status.get("missing_required_count") or 0),
        },
        "blocking_reasons": blocking_reasons,
        "future_boundaries": {
            "generation_service": "locked",
            "prompt_context_assembly": "locked",
            "provider_execution": "locked",
            "candidate_draft_validation": "locked",
            "author_accept_edit_reject": "locked",
            "approved_runtime_persistence": "locked",
            "export_pipeline": "locked",
        },
        "message": "Generation control status loaded. Generation remains locked during migration.",
    }


def _readiness_check(name: str, ready: bool, message: str) -> dict[str, Any]:
    return {
        "name": name,
        "ready": bool(ready),
        "status": "ready" if ready else "blocked",
        "message": message,
    }


def _blocking_reasons(
    *,
    workspace_ready_lifecycle: bool,
    canon_setup_completed: bool,
    runtime_storage_ready: bool,
    canon_packets_ready: bool,
    packet_status: dict[str, Any],
) -> list[str]:
    reasons = [
        "generation execution is locked during migration",
        "provider execution is locked",
        "prompt builder is locked",
        "candidate draft validation is not wired",
        "author accept/edit/reject workflow is not wired",
        "approved persistence is locked",
        "export is locked",
    ]

    if not workspace_ready_lifecycle:
        reasons.append("project is not ready for workspace")
    if not canon_setup_completed:
        reasons.append("canon setup is incomplete")
    if not runtime_storage_ready:
        reasons.append("runtime storage is not ready")
    if not canon_packets_ready:
        missing_count = int(packet_status.get("missing_required_count") or 0)
        if missing_count:
            reasons.append(f"{missing_count} required control packet(s) are missing")
        else:
            reasons.append("required control packets are missing")

    return reasons
