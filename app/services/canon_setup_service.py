"""
Canon setup service.

Resolves genre/template canon architecture for a project. This service preserves
legacy Italus canon files as seed/reference assets and prepares project-local
canon workspace directories without touching generation runtime modules.
"""

from __future__ import annotations

from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context, resolve_relative_path
from app.projects.project_manifest import (
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_CANON_IN_PROGRESS,
    LIFECYCLE_DRAFT_SETUP,
    utc_now_iso,
)
from app.services import canon_validation_service, project_canon_service
from app.templates.template_registry import (
    SOURCE_DERIVE_FROM_PROJECT_BOOKS,
    SOURCE_GENERATED_FROM_AUTHOR_CANON,
    SOURCE_PROJECT_LOCAL_FILE,
    get_template,
    list_templates,
)


class CanonSetupConflictError(RuntimeError):
    """Raised when project lifecycle state blocks a canon setup mutation."""


def available_templates() -> dict[str, Any]:
    return {
        "status": "ok",
        "templates": list_templates(),
    }


def get_canon_setup(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    if manifest.lifecycle_state in {LIFECYCLE_DRAFT_SETUP, LIFECYCLE_CANON_IN_PROGRESS}:
        context.ensure_project_canon_dirs()
    template = get_template(context.template_id, manifest.genre)
    wizard_state = project_loader.load_wizard_state(project_id) or {}

    setup = _resolved_setup_payload(
        manifest=manifest,
        context=context,
        template=template,
        wizard_state=wizard_state,
    )
    author_schema = project_canon_service.effective_template_schema_for_context(
        context,
        manifest.to_dict(),
    )
    author_sections = author_schema.get("sections") or []
    validation_status = canon_validation_service.get_canon_validation_status_for_context(
        context,
        manifest.to_dict(),
        author_schema,
    )
    attention_sections = [
        section
        for section in validation_status.get("sections", [])
        if (
            not section.get("complete")
            or section.get("markdown_file", {}).get("render_status") != "current"
            or section.get("markdown_file", {}).get("freshness_verified") is not True
        )
    ]
    required_sections_total = int(
        validation_status.get("required_sections_total") or 0
    )
    required_sections_complete = int(
        validation_status.get("required_sections_complete") or 0
    )
    all_required_author_sections_complete = (
        required_sections_total > 0
        and required_sections_complete == required_sections_total
    )

    return {
        "status": "ok",
        "project_id": project_id,
        "read_only": manifest.lifecycle_state == LIFECYCLE_ARCHIVED,
        "can_edit": manifest.lifecycle_state in {LIFECYCLE_DRAFT_SETUP, LIFECYCLE_CANON_IN_PROGRESS},
        "manifest": manifest.to_dict(),
        "template": {
            "template_id": template["template_id"],
            "genre": template["genre"],
            "label": template["label"],
            "description": template["description"],
            "seed_mode": template.get("seed_mode"),
            "project_storage_mode": template.get("project_storage_mode"),
        },
        "project_context": _context_payload(context),
        "canon_groups": setup["canon_groups"],
        "summary": {
            **setup["summary"],
            "author_section_count": len(author_sections),
            "required_author_section_count": sum(
                1 for section in author_sections if section.get("required")
            ),
            "completed_required_author_section_count": required_sections_complete,
            "all_required_author_sections_complete": all_required_author_sections_complete,
            "canon_sources_ready_for_setup_completion": bool(
                validation_status.get("ready_for_packet_generation")
            ),
            "attention_required_section_count": len(attention_sections),
            "attention_required_sections": [
                {
                    "section_id": section.get("section_id"),
                    "label": section.get("label") or section.get("section_id"),
                }
                for section in attention_sections
            ],
        },
        "wizard_state": wizard_state,
    }


def initialize_canon_setup(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    if manifest.lifecycle_state == LIFECYCLE_ARCHIVED:
        raise CanonSetupConflictError("Archived projects must be restored before canon setup.")
    if manifest.lifecycle_state not in {LIFECYCLE_DRAFT_SETUP, LIFECYCLE_CANON_IN_PROGRESS}:
        raise CanonSetupConflictError(
            f"Project state {manifest.lifecycle_state} cannot enter canon setup."
        )

    context = build_project_context(manifest)
    context.ensure_project_canon_dirs()

    if manifest.lifecycle_state == LIFECYCLE_DRAFT_SETUP:
        manifest.lifecycle_state = LIFECYCLE_CANON_IN_PROGRESS
        manifest.touch()
        project_loader.save_manifest(manifest)

    template = get_template(context.template_id, manifest.genre)
    setup_state = _canon_wizard_state(
        project_id=project_id,
        existing_state=project_loader.load_wizard_state(project_id),
        manifest=manifest,
        context=context,
        template=template,
        resume_target="genre_template",
        completed_genre_template=False,
    )
    project_loader.save_wizard_state(project_id, setup_state)

    return get_canon_setup(project_id)


def confirm_genre_template(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    if manifest.lifecycle_state == LIFECYCLE_ARCHIVED:
        raise CanonSetupConflictError("Archived projects must be restored before canon setup.")
    if manifest.lifecycle_state not in {LIFECYCLE_DRAFT_SETUP, LIFECYCLE_CANON_IN_PROGRESS}:
        raise CanonSetupConflictError(
            f"Project state {manifest.lifecycle_state} cannot confirm canon template."
        )

    context = build_project_context(manifest)
    context.ensure_project_canon_dirs()

    if manifest.lifecycle_state == LIFECYCLE_DRAFT_SETUP:
        manifest.lifecycle_state = LIFECYCLE_CANON_IN_PROGRESS
        manifest.touch()
        project_loader.save_manifest(manifest)

    template = get_template(context.template_id, manifest.genre)
    setup_state = _canon_wizard_state(
        project_id=project_id,
        existing_state=project_loader.load_wizard_state(project_id),
        manifest=manifest,
        context=context,
        template=template,
        resume_target="canon_groups",
        completed_genre_template=True,
    )
    project_loader.save_wizard_state(project_id, setup_state)

    payload = get_canon_setup(project_id)
    payload["message"] = "Genre template confirmed. Canon groups are ready for review."
    return payload


def _resolved_setup_payload(
    *,
    manifest: Any,
    context: ProjectContext,
    template: dict[str, Any],
    wizard_state: dict[str, Any],
) -> dict[str, Any]:
    canon_groups = []
    detected_count = 0
    missing_count = 0
    generated_count = 0
    editable_count = 0

    for group in template.get("canon_groups", []):
        resolved_items = []
        for item in group.get("items", []):
            resolved_item = _resolve_item(item, manifest, context)
            resolved_items.append(resolved_item)

            if resolved_item["editable"]:
                editable_count += 1
            if resolved_item["status"] == "DETECTED":
                detected_count += 1
            elif resolved_item["status"] == "MISSING":
                missing_count += 1
            elif resolved_item["status"] == "GENERATED_PENDING":
                generated_count += 1

        group_status = "DETECTED"
        if any(item["status"] == "MISSING" and item["required"] for item in resolved_items):
            group_status = "MISSING_REQUIRED"
        elif any(item["status"] == "GENERATED_PENDING" for item in resolved_items):
            group_status = "GENERATED_PENDING"

        canon_groups.append(
            {
                "group_id": group["group_id"],
                "label": group["label"],
                "author_action": group.get("author_action"),
                "description": group.get("description", ""),
                "status": group_status,
                "items": resolved_items,
            }
        )

    return {
        "canon_groups": canon_groups,
        "summary": {
            "group_count": len(canon_groups),
            "detected_items": detected_count,
            "missing_items": missing_count,
            "generated_pending_items": generated_count,
            "editable_items": editable_count,
            "resume_target": wizard_state.get("resume_target", "genre_template"),
        },
    }


def _resolve_item(item: dict[str, Any], manifest: Any, context: ProjectContext) -> dict[str, Any]:
    source_strategy = item.get("source_strategy") or SOURCE_PROJECT_LOCAL_FILE
    source_files = _expand_source_files(item, manifest, context)
    resolved_files = []

    for relative_path in source_files:
        prefer_project_local = source_strategy != "legacy_root_reference"
        resolved_path, storage_scope = resolve_relative_path(
            context,
            relative_path,
            prefer_project_local=prefer_project_local,
        )
        exists = resolved_path.exists()
        resolved_files.append(
            {
                "relative_path": relative_path,
                "storage_scope": storage_scope,
                "exists": exists,
                "display_path": str(resolved_path.relative_to(context.project_root))
                if resolved_path.is_relative_to(context.project_root)
                else str(resolved_path),
            }
        )

    if source_strategy == SOURCE_GENERATED_FROM_AUTHOR_CANON:
        status = "GENERATED_PENDING"
    elif resolved_files and all(file_info["exists"] for file_info in resolved_files):
        status = "DETECTED"
    elif not resolved_files and not item.get("required", True):
        status = "OPTIONAL"
    else:
        status = "MISSING"

    wizard_status = _wizard_status_for_resolved_item(
        status=status,
        source_strategy=source_strategy,
        resolved_files=resolved_files,
    )

    return {
        "canon_id": item["canon_id"],
        "label": item["label"],
        "role": item.get("role", "primary_canon"),
        "editable": bool(item.get("editable", False)),
        "required": bool(item.get("required", True)),
        "source_strategy": source_strategy,
        "status": status,
        "wizard_status": wizard_status,
        "source_files": resolved_files,
    }


def _expand_source_files(item: dict[str, Any], manifest: Any, context: ProjectContext) -> list[str]:
    source_strategy = item.get("source_strategy")
    if source_strategy == SOURCE_DERIVE_FROM_PROJECT_BOOKS:
        book_count = _positive_int(getattr(manifest, "book_count", None), 1)
        pattern = item.get("file_pattern", "canon_packs/book_{book_number:02d}_knowledge_pack.md")
        return [pattern.format(book_number=index, project_code=context.project_code) for index in range(1, book_count + 1)]

    return list(item.get("source_files") or [])


def _canon_wizard_state(
    *,
    project_id: str,
    existing_state: dict[str, Any] | None,
    manifest: Any,
    context: ProjectContext,
    template: dict[str, Any],
    resume_target: str,
    completed_genre_template: bool,
) -> dict[str, Any]:
    now = utc_now_iso()
    state = existing_state or {}
    completed_steps = list(state.get("completed_steps") or [])
    incomplete_steps = list(state.get("incomplete_steps") or [])

    if "project_metadata" not in completed_steps:
        completed_steps.append("project_metadata")

    if completed_genre_template:
        if "genre_template" not in completed_steps:
            completed_steps.append("genre_template")
        incomplete_steps = [step for step in incomplete_steps if step != "genre_template"]
        if "canon_groups" not in incomplete_steps:
            incomplete_steps.append("canon_groups")
    elif "genre_template" not in incomplete_steps:
        incomplete_steps.append("genre_template")

    setup = _resolved_setup_payload(
        manifest=manifest,
        context=context,
        template=template,
        wizard_state=state,
    )
    existing_statuses = dict(state.get("canon_set_statuses") or {})
    canon_set_statuses: dict[str, str] = {}
    canon_group_statuses: dict[str, str] = {}

    for group in setup.get("canon_groups", []):
        canon_group_statuses[group["group_id"]] = group.get("status", "UNKNOWN")
        for item in group.get("items", []):
            canon_id = item["canon_id"]
            canon_set_statuses[canon_id] = _merge_wizard_status(
                existing_statuses.get(canon_id),
                item.get("wizard_status") or item.get("status") or "UNKNOWN",
            )

    state.update(
        {
            "project_id": project_id,
            "current_phase": "CANON_WIZARD",
            "current_step_id": resume_target,
            "completed_steps": completed_steps,
            "incomplete_steps": incomplete_steps,
            "resume_target": resume_target,
            "can_enter_workspace": False,
            "blocking_requirements": _with_unique(state.get("blocking_requirements", []), "canon_setup"),
            "lifecycle_state": LIFECYCLE_CANON_IN_PROGRESS,
            "canon_groups_initialized": True,
            "canon_workspace_initialized": True,
            "required_canon_sets": list(canon_set_statuses.keys()),
            "canon_group_statuses": canon_group_statuses,
            "canon_set_statuses": canon_set_statuses,
            "last_saved_at": now,
            "last_opened_at": now,
        }
    )
    state.setdefault("canon_reset_pending", False)
    state.setdefault("reset_canon_set_ids", [])
    return state


def _wizard_status_for_resolved_item(
    *,
    status: str,
    source_strategy: str,
    resolved_files: list[dict[str, Any]],
) -> str:
    if status == "GENERATED_PENDING":
        return "GENERATED_PENDING"
    if status == "MISSING":
        return "MISSING"
    if status == "OPTIONAL":
        return "OPTIONAL"

    if status == "DETECTED":
        storage_scopes = {file_info.get("storage_scope") for file_info in resolved_files}
        if "legacy_root_reference" in storage_scopes or source_strategy == "legacy_root_reference":
            return "REFERENCE_DETECTED"
        if "project_local" in storage_scopes:
            return "PROJECT_LOCAL_DETECTED"
        return "DETECTED"

    return status or "UNKNOWN"


def _merge_wizard_status(existing_status: Any, resolved_status: str) -> str:
    preserved_review_states = {
        "APPROVED",
        "REFERENCE_APPROVED",
        "PROJECT_LOCAL_APPROVED",
        "GENERATED",
        "NEEDS_REVIEW",
        "READY",
        "LOCKED",
        "RESET_PENDING",
    }
    if existing_status in preserved_review_states:
        return str(existing_status)
    return resolved_status


def _context_payload(context: ProjectContext) -> dict[str, Any]:
    return {
        "template_id": context.template_id,
        "genre": context.genre,
        "project_code": context.project_code,
        "storage_mode": context.storage_mode,
        "seed_mode": context.seed_mode,
        "project_canon_sources": _relative(context, context.project_canon_sources_dir),
        "project_canon_packs": _relative(context, context.project_canon_packs_dir),
        "project_canon_manifests": _relative(context, context.project_canon_manifests_dir),
        "project_canon_generated": _relative(context, context.project_canon_generated_dir),
        "legacy_canon_sources": _relative(context, context.legacy_canon_sources_dir),
        "legacy_canon_packs": _relative(context, context.legacy_canon_packs_dir),
        "legacy_canon_manifests": _relative(context, context.legacy_canon_manifests_dir),
    }


def _relative(context: ProjectContext, path: Any) -> str:
    path = path if hasattr(path, "relative_to") else context.project_root / str(path)
    try:
        return str(path.relative_to(context.project_root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _with_unique(values: list[Any], value: Any) -> list[Any]:
    result = []
    for item in values:
        if item not in result:
            result.append(item)
    if value not in result:
        result.append(value)
    return result
