"""
Workspace bootstrap service.

This service loads project-scoped workspace state for the browser shell. It is
read-only by design and must not call the generation runtime, prompt builder,
provider runners, validators, or LLM services.
"""

from __future__ import annotations

from typing import Any

from app.projects import project_loader
from app.projects.project_context import build_project_context
from app.services import canon_packet_service, project_runtime_storage_service
from app.projects.project_manifest import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_CANON_IN_PROGRESS,
    LIFECYCLE_DRAFT_SETUP,
    LIFECYCLE_READY_FOR_WORKSPACE,
)


class WorkspaceAccessConflictError(RuntimeError):
    """Raised when a project cannot enter the workspace shell."""


def get_workspace_bootstrap(project_id: str) -> dict[str, Any]:
    """Return a read-only workspace bootstrap payload for a project.

    This is intentionally a state-loading boundary. It does not trigger
    generation, validation, canon mutation, or project runtime migration.
    """

    manifest = project_loader.load_manifest(project_id)
    budget_plan = project_loader.load_budget_plan(project_id)
    wizard_state = project_loader.load_wizard_state(project_id) or {}
    context = build_project_context(manifest)
    runtime_storage_status = project_runtime_storage_service.ensure_runtime_storage_for_context(context)
    canon_packet_status = canon_packet_service.get_canon_packet_status_for_context(context, manifest.to_dict())

    can_enter_workspace = bool(wizard_state.get("can_enter_workspace"))
    if manifest.lifecycle_state not in {LIFECYCLE_READY_FOR_WORKSPACE, LIFECYCLE_ACTIVE} and not can_enter_workspace:
        raise WorkspaceAccessConflictError(
            f"Project state {manifest.lifecycle_state} cannot enter workspace. "
            "Complete setup and canon approval first."
        )

    read_only = manifest.lifecycle_state == LIFECYCLE_ARCHIVED
    approved_refs = dict(wizard_state.get("approved_canon_refs") or {})
    canon_statuses = dict(wizard_state.get("canon_set_statuses") or {})
    runtime_pack_refs = {
        canon_id: data
        for canon_id, data in approved_refs.items()
        if isinstance(data, dict) and data.get("role") == "runtime_context_pack"
    }

    bootstrap = {
        "status": "ok",
        "project_id": project_id,
        "can_enter_workspace": can_enter_workspace or manifest.lifecycle_state in {
            LIFECYCLE_READY_FOR_WORKSPACE,
            LIFECYCLE_ACTIVE,
        },
        "read_only": read_only,
        "runtime_ready": False,
        "generation_enabled": False,
        "validation_enabled": False,
        "exports_enabled": False,
        "manifest": manifest.to_dict(),
        "budget_plan": budget_plan,
        "wizard_state": wizard_state,
        "approved_canon_refs": approved_refs,
        "project_context": _context_payload(context),
        "runtime_storage": runtime_storage_status,
        "canon_packet_status": canon_packet_status,
        "read_only_data": _read_only_data_payload(),
        "runtime_readiness_gates": _runtime_readiness_gates_payload(runtime_storage_status),
        "summary": {
            "approved_reference_count": _count_status(canon_statuses, "REFERENCE_APPROVED"),
            "required_canon_count": len(wizard_state.get("required_canon_sets") or []),
            "runtime_pack_count": len(runtime_pack_refs),
            "canon_packet_count": int(canon_packet_status.get("packet_count") or 0),
            "canon_packet_missing_required_count": int(canon_packet_status.get("missing_required_count") or 0),
            "canon_setup_completed": bool(wizard_state.get("canon_setup_completed")),
            "blocking_requirements": list(wizard_state.get("blocking_requirements") or []),
        },
        "workspace_menu": _workspace_menu(manifest.lifecycle_state, read_only),
        "message": "Workspace bootstrap loaded. Generation runtime not yet migrated.",
    }
    return bootstrap



def _read_only_data_payload() -> dict[str, Any]:
    """Load legacy root data for read-only workspace browsing.

    This exposes existing JSON artifacts without calling generation, validation,
    prompt construction, provider runners, or project runtime migration.
    """

    books = _read_legacy_json("books.json", [])
    chapters = _read_legacy_json("chapters.json", [])
    events = _read_legacy_json("event_index.json", [])
    scenes = _read_legacy_json("scenes.json", [])
    coverage_map = _read_legacy_json("coverage_map.json", {})
    continuity_digests = _read_legacy_json("chapter_continuity_digests.json", {})

    characters = _character_index(books, chapters, events, scenes)
    coverage_events = coverage_map.get("events") if isinstance(coverage_map, dict) else {}

    return {
        "marker": "workspace-readonly-data-20260707",
        "source_mode": "legacy_root_read_only",
        "runtime_migration_status": "not_migrated",
        "books": {
            "count": len(books) if isinstance(books, list) else 0,
            "sample": _sample_records(books, ["book_id", "book_number", "title", "status"], 8),
        },
        "chapters": {
            "count": len(chapters) if isinstance(chapters, list) else 0,
            "sample": _sample_records(
                chapters,
                ["chapter_id", "book_id", "chapter_number", "title", "event_name", "status"],
                8,
            ),
        },
        "events": {
            "count": len(events) if isinstance(events, list) else 0,
            "sample": _sample_records(
                events,
                ["event_id", "year_label", "event_name", "book_id", "region"],
                8,
            ),
        },
        "scenes": {
            "count": len(scenes) if isinstance(scenes, list) else 0,
            "sample": _sample_records(
                scenes,
                ["scene_id", "book_id", "chapter_id", "title", "event_name", "status"],
                8,
            ),
        },
        "characters": {
            "count": len(characters),
            "sample": characters[:12],
        },
        "continuity": {
            "digest_count": len(continuity_digests) if isinstance(continuity_digests, dict) else 0,
        },
        "coverage": {
            "event_count": len(coverage_events) if isinstance(coverage_events, dict) else 0,
            "sample": _coverage_sample(coverage_events, 6),
        },
    }


def _runtime_readiness_gates_payload(runtime_storage_status: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Return read-only runtime readiness gates for the workspace.

    These gates are descriptive only. They do not trigger generation, validation,
    prompt construction, provider runners, canon mutation, or runtime migration.
    """

    runtime_status = (runtime_storage_status or {}).get("status") or "not_initialized"
    runtime_root = (runtime_storage_status or {}).get("runtime_root") or "data/projects/<project_id>/runtime/"

    return [
        {
            "id": "project_lifecycle",
            "label": "Project Lifecycle",
            "status": "ready",
            "owner": "workspace service",
            "reason": "Project setup and canon approval allow workspace access.",
            "next_step": "Keep workspace in read-only mode until runtime storage is migrated.",
        },
        {
            "id": "canon_approval",
            "label": "Canon Approval",
            "status": "ready",
            "owner": "canon setup",
            "reason": "Required canon references are approved for workspace use.",
            "next_step": "Preserve approved references as read-only runtime context.",
        },
        {
            "id": "runtime_storage",
            "label": "Project-local Runtime Storage",
            "status": "ready" if runtime_status == "initialized" else "blocked",
            "owner": "runtime storage service",
            "reason": f"Project runtime storage status is {runtime_status}; target is {runtime_root}.",
            "next_step": "Keep generation locked until prompt routing, provider execution, validation, and export gates pass.",
        },
        {
            "id": "prompt_routing",
            "label": "Prompt Builder Routing",
            "status": "locked",
            "owner": "prompt builder",
            "reason": "Prompt construction is protected and has not been routed through ProjectContext.",
            "next_step": "Introduce a generation service boundary before touching prompt_builder.py.",
        },
        {
            "id": "provider_execution",
            "label": "AI Provider Execution",
            "status": "locked",
            "owner": "provider layer",
            "reason": "Provider runners remain protected and are not called from workspace.",
            "next_step": "Define provider configuration, timeout, logging, and error handling contracts.",
        },
        {
            "id": "validation_runtime",
            "label": "Validation Runtime",
            "status": "blocked",
            "owner": "validation service",
            "reason": "Validation service is not wired to workspace execution.",
            "next_step": "Design validation_service integration after generation storage boundaries exist.",
        },
        {
            "id": "export_pipeline",
            "label": "Export Pipeline",
            "status": "blocked",
            "owner": "export workflow",
            "reason": "Export output is not implemented for workspace projects.",
            "next_step": "Define export formats and persistence after manuscript state is project-local.",
        },
        {
            "id": "generation_unlock",
            "label": "Generation Unlock",
            "status": "locked",
            "owner": "project control",
            "reason": "Generation must remain disabled until all runtime gates are resolved.",
            "next_step": "Enable generation only after storage, prompt routing, provider, and validation gates pass.",
        },
    ]


def _read_legacy_json(filename: str, default: Any) -> Any:
    path = project_loader.PROJECT_ROOT / "data" / filename
    try:
        return project_loader.read_json(path, default=default)
    except Exception:
        return default


def _sample_records(records: Any, fields: list[str], limit: int) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []

    sample: list[dict[str, Any]] = []
    for record in records[:limit]:
        if not isinstance(record, dict):
            continue
        sample.append({field: record.get(field) for field in fields if field in record})
    return sample


def _character_index(books: Any, chapters: Any, events: Any, scenes: Any) -> list[dict[str, Any]]:
    names: dict[str, dict[str, Any]] = {}

    def add_name(name: Any, source: str) -> None:
        clean = str(name or "").strip()
        if not clean:
            return
        entry = names.setdefault(clean, {"name": clean, "sources": set()})
        entry["sources"].add(source)

    for book in books if isinstance(books, list) else []:
        if isinstance(book, dict):
            for guardian in book.get("primary_guardians") or []:
                add_name(guardian, "book_guardian")

    for chapter in chapters if isinstance(chapters, list) else []:
        if isinstance(chapter, dict):
            add_name(chapter.get("guardian"), "chapter_guardian")

    for event in events if isinstance(events, list) else []:
        if isinstance(event, dict):
            for guardian in event.get("active_guardians") or []:
                add_name(guardian, "event_guardian")

    for scene in scenes if isinstance(scenes, list) else []:
        if isinstance(scene, dict):
            add_name(scene.get("guardian"), "scene_guardian")
            for character in scene.get("characters_present") or []:
                add_name(character, "scene_character")

    return [
        {"name": name, "sources": sorted(data["sources"])}
        for name, data in sorted(names.items(), key=lambda item: item[0].lower())
    ]


def _coverage_sample(coverage_events: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(coverage_events, dict):
        return []

    sample: list[dict[str, Any]] = []
    for event_name, payload in list(coverage_events.items())[:limit]:
        if not isinstance(payload, dict):
            continue
        sample.append(
            {
                "event_name": event_name,
                "scene_count": payload.get("scene_count", 0),
                "locations_used": len(payload.get("locations_used") or []),
                "povs_used": len(payload.get("povs_used") or []),
            }
        )
    return sample


def _workspace_menu(lifecycle_state: str, read_only: bool) -> list[dict[str, Any]]:
    generation_reason = "Generation runtime is not yet project-context-aware."
    validation_reason = "Validation runtime is not yet project-context-aware."
    export_reason = "Exports are not implemented in the workspace bootstrap phase."

    return [
        {
            "group_id": "project",
            "label": "Project",
            "items": [
                _enabled_item("dashboard", "Dashboard"),
                _enabled_item("manuscript_plan", "Manuscript Plan"),
                _enabled_item("budget_plan", "Budget Plan"),
            ],
        },
        {
            "group_id": "library",
            "label": "Library",
            "items": [
                _enabled_item("books", "Books"),
                _enabled_item("chapters", "Chapters"),
                _enabled_item("events", "Events"),
                _enabled_item("scenes", "Scenes"),
                _enabled_item("characters", "Characters"),
            ],
        },
        {
            "group_id": "canon",
            "label": "Canon",
            "items": [
                _enabled_item("canon_dashboard", "Canon Dashboard"),
                _enabled_item("world_canon", "World Canon"),
                _enabled_item("character_canon", "Character Canon"),
                _enabled_item("story_flow", "Story Flow / Saga Canon"),
                _enabled_item("timeline_backbone", "Timeline / Event Backbone"),
                _enabled_item("continuity_rules", "Continuity Rules"),
            ],
        },
        {
            "group_id": "runtime_packs",
            "label": "Runtime Packs",
            "items": [
                _enabled_item("core_pack", "Core Pack"),
                _enabled_item("generation_pack", "Generation Pack"),
                _enabled_item("book_packs", "Book Packs"),
            ],
        },
        {
            "group_id": "runtime",
            "label": "Runtime",
            "items": [
                _enabled_item("runtime_storage_preview", "Project Writing Memory"),
                _disabled_item("memory_continuity", "Memory / Continuity", "Continuity memory is not yet project-scoped."),
                _disabled_item("validation", "Validation", validation_reason),
                _disabled_item("output", "Output", "Generation output is disabled until runtime migration."),
            ],
        },
        {
            "group_id": "project_control",
            "label": "Project Control",
            "items": [
                _enabled_item("settings", "Settings"),
                _enabled_item("archive", "Archive") if not read_only else _disabled_item("archive", "Archive", "Archived projects are read-only."),
            ],
        },
        {
            "group_id": "actions",
            "label": "Disabled Runtime Actions",
            "items": [
                _disabled_item("generation", "Generation", generation_reason),
                _disabled_item("validation_runtime", "Validation Runtime", validation_reason),
                _disabled_item("exports", "Exports", export_reason),
            ],
        },
    ]


def _enabled_item(menu_id: str, label: str) -> dict[str, Any]:
    return {"menu_id": menu_id, "label": label, "enabled": True}


def _disabled_item(menu_id: str, label: str, reason: str) -> dict[str, Any]:
    return {
        "menu_id": menu_id,
        "label": label,
        "enabled": False,
        "disabled_reason": reason,
    }


def _count_status(statuses: dict[str, Any], expected_status: str) -> int:
    return sum(1 for value in statuses.values() if value == expected_status)


def _context_payload(context: Any) -> dict[str, Any]:
    return {
        "template_id": context.template_id,
        "genre": context.genre,
        "project_code": context.project_code,
        "storage_mode": context.storage_mode,
        "seed_mode": context.seed_mode,
        "project_canon_sources": _relative(context.project_canon_sources_dir),
        "project_canon_packs": _relative(context.project_canon_packs_dir),
        "project_canon_manifests": _relative(context.project_canon_manifests_dir),
        "project_canon_generated": _relative(context.project_canon_generated_dir),
        "runtime_data_dir": _relative(context.runtime_data_dir),
        "legacy_canon_sources": _relative(context.legacy_canon_sources_dir),
        "legacy_canon_packs": _relative(context.legacy_canon_packs_dir),
        "legacy_canon_manifests": _relative(context.legacy_canon_manifests_dir),
    }


def _relative(path: Any) -> str:
    try:
        return str(path.relative_to(project_loader.PROJECT_ROOT))
    except ValueError:
        return str(path)
