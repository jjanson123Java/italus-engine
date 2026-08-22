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
from app.services import (
    canon_authoring_service,
    canon_markdown_renderer_service,
    canon_packet_generation_service,
    canon_packet_service,
    book_plan_service,
    book_knowledge_pack_service,
    book_scope_service,
    chapter_plan_service,
    story_control_service,
    project_runtime_storage_service,
    authorship_provenance_service,
)
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
    provenance_status = authorship_provenance_service.ensure_provenance_storage_for_context(context)
    canon_packet_status = canon_packet_service.get_canon_packet_status_for_context(context, manifest.to_dict())
    project_runtime_context_status = (
        canon_packet_generation_service.get_project_runtime_context_status_for_context(
            context,
            manifest.to_dict(),
        )
    )
    # Workspace shell bootstrap must remain lightweight. Detailed Book/Chapter
    # planning and runtime status is loaded lazily by each authoring surface.
    # Do not reconcile all Book Scopes/Plans/Runtime Contexts merely to render
    # the Dashboard. This avoids hundreds of repeated Canon Index freshness
    # checks on every hard refresh.
    book_plan_status = {
        "status": "available", "valid": False, "lazy_detail": True,
        "message": "Open Book Planner to load current per-book planning status.",
    }
    book_runtime_context_status = {
        "status": "available", "compiler_ready": False, "lazy_detail": True,
        "current_count": 0, "target_count": int(manifest.book_count or 0),
        "message": "Open Book Knowledge Packs to load current compilation status.",
    }
    book_scope_status = {
        "status": "available", "lazy_detail": True,
        "message": "Canon for This Book status loads with Book Planner.",
    }
    chapter_plan_status = {
        "status": "available", "lazy_detail": True,
        "message": "Chapter Plan status loads when Chapter Planner opens.",
    }
    story_control_status = {
        "status": "available", "lazy_detail": True,
        "message": "Story Controls load with Chapter Planner.",
    }
    author_canon_status = canon_authoring_service.get_canon_authoring_status_for_context(
        context,
        manifest.to_dict(),
    )
    canon_markdown_status = canon_markdown_renderer_service.get_canon_markdown_status_for_context(
        context,
        manifest.to_dict(),
    )
    author_summary = _workspace_author_summary(
        author_canon_status,
        canon_markdown_status,
    )

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
        "author_canon_status": author_canon_status,
        "canon_markdown_status": canon_markdown_status,
        "runtime_context": {
            "project": {
                **project_runtime_context_status,
                "enabled": True,
                "approval_status": "not_available",
                "review_enabled": True,
            },
            "book_scope": {
                **book_scope_status,
                "enabled": True,
                "authoring_enabled": not read_only,
                "review_enabled": True,
                "message": (
                    "Canon for This Book is available in the Planner."
                    if not read_only
                    else "Archived projects expose Canon for This Book as read-only."
                ),
            },
            "book_plan": {
                **book_plan_status,
                "enabled": not read_only,
                "authoring_enabled": not read_only,
                "approval_enabled": not read_only,
                "review_enabled": True,
                "message": (
                    "Project-local Book Plan authoring and approval are available."
                    if not read_only
                    else "Archived projects expose the Book Plan as read-only."
                ),
            },
            "chapter_plan": {
                **chapter_plan_status,
                "enabled": not read_only,
                "authoring_enabled": not read_only,
                "review_enabled": True,
                "message": (
                    "Lightweight Chapter Planner and Event Board are available."
                    if not read_only
                    else "Archived projects expose Chapter Plans as read-only."
                ),
            },
            "story_controls": {
                **story_control_status,
                "enabled": not read_only,
                "authoring_enabled": not read_only,
                "review_enabled": True,
                "message": (
                    "Story Controls are available inside Chapter Planner."
                    if not read_only
                    else "Archived projects expose Story Controls as read-only."
                ),
            },
            "provenance": {
                **provenance_status,
                "enabled": True,
                "origin_capture_enabled": bool(
                    provenance_status.get("provenance_capture_ready")
                ),
                "scoring_enabled": False,
                "ledger_enabled": False,
                "message": (
                    "Authorship provenance storage and lineage foundation are ready. "
                    "Scoring, provider wiring, and ledger generation remain locked."
                ),
            },
            "books": {
                **book_runtime_context_status,
                "enabled": True,
                "review_enabled": True,
                "compile_enabled": (
                    not read_only
                    and bool(
                        book_runtime_context_status.get("compiler_ready")
                    )
                ),
                "message": (
                    "Book Runtime Context v2 review is available. Compilation "
                    "requires current approved Book Canon and Book Plan state."
                ),
            },
        },
        "runtime_readiness_gates": _runtime_readiness_gates_payload(runtime_storage_status),
        "summary": {
            **author_summary,
            "canon_packet_count": int(canon_packet_status.get("packet_count") or 0),
            "canon_packet_missing_required_count": int(canon_packet_status.get("missing_required_count") or 0),
            "blocking_requirements": list(wizard_state.get("blocking_requirements") or []),
            # Legacy compatibility fields remain internal during migration.
            "approved_reference_count": _count_status(canon_statuses, "REFERENCE_APPROVED"),
            "required_canon_count": len(wizard_state.get("required_canon_sets") or []),
            "runtime_pack_count": len(runtime_pack_refs),
            "canon_setup_completed": bool(wizard_state.get("canon_setup_completed")),
        },
        "workspace_menu": _workspace_menu(manifest.lifecycle_state, read_only),
        "message": "Workspace bootstrap loaded. Generation runtime not yet migrated.",
    }
    return bootstrap





def get_workspace_library(project_id: str) -> dict[str, Any]:
    """Return the lazy, read-only author Library projection for one project.

    This boundary reads existing project state only. It does not mutate Canon,
    Book Plan, Chapter Plan, Budget Plan, runtime manuscript state, approvals,
    or generated knowledge packs.
    """

    manifest_obj = project_loader.load_manifest(project_id)
    manifest = manifest_obj.to_dict()
    budget_plan = project_loader.load_budget_plan(project_id) or {}
    context = build_project_context(manifest_obj)
    return _author_library_payload(context, manifest, budget_plan)


def _author_library_payload(
    context,
    manifest: dict[str, Any],
    budget_plan: dict[str, Any],
) -> dict[str, Any]:
    project_dir = context.project_dir
    runtime_dir = context.runtime_data_dir

    template_snapshot = _read_project_json(project_dir / "canon" / "template_snapshot.json", {})
    author_canon = _read_project_json(project_dir / "canon" / "author_canon.json", {})
    book_plan = _read_project_json(project_dir / "book_plan.json", {})
    chapter_plan = _read_project_json(project_dir / "chapter_plan.json", {})
    runtime_books = _read_project_json(runtime_dir / "books.json", [])
    runtime_chapters = _read_project_json(runtime_dir / "chapters.json", [])
    runtime_scenes = _read_project_json(runtime_dir / "scenes.json", [])

    questionnaire = template_snapshot.get("questionnaire") if isinstance(template_snapshot, dict) else {}
    questionnaire = questionnaire if isinstance(questionnaire, dict) else {}
    template_sections = questionnaire.get("sections")
    template_sections = template_sections if isinstance(template_sections, list) else []

    canon_sections = author_canon.get("sections") if isinstance(author_canon, dict) else {}
    canon_sections = canon_sections if isinstance(canon_sections, dict) else {}

    canon_collections: list[dict[str, Any]] = []
    canon_references: list[dict[str, Any]] = []
    governing_sections: list[dict[str, str]] = []

    for section_schema in template_sections:
        if not isinstance(section_schema, dict):
            continue
        section_id = str(section_schema.get("section_id") or "").strip()
        if not section_id:
            continue
        section_label = str(section_schema.get("label") or section_id).strip()
        purpose = str(section_schema.get("purpose") or "").strip()
        guidance = str(section_schema.get("author_guidance") or "").strip()
        section_state = canon_sections.get(section_id) if isinstance(canon_sections, dict) else {}
        section_state = section_state if isinstance(section_state, dict) else {}
        records_state = section_state.get("records")
        records_state = records_state if isinstance(records_state, dict) else {}
        answers_state = section_state.get("answers")
        answers_state = answers_state if isinstance(answers_state, dict) else {}

        if section_id != "project_bible":
            governing_sections.append(
                {
                    "section_id": section_id,
                    "label": section_label,
                    "purpose": purpose,
                }
            )

        record_definitions = section_schema.get("records")
        record_definitions = record_definitions if isinstance(record_definitions, list) else []
        for record_schema in record_definitions:
            if not isinstance(record_schema, dict):
                continue
            record_id = str(record_schema.get("record_id") or "").strip()
            if not record_id:
                continue
            records = records_state.get(record_id)
            records = records if isinstance(records, list) else []
            fields = record_schema.get("fields")
            fields = fields if isinstance(fields, list) else []
            canon_collections.append(
                {
                    "key": f"canon_collection__{section_id}__{record_id}",
                    "section_id": section_id,
                    "record_id": record_id,
                    "label": str(record_schema.get("label") or section_label or record_id),
                    "section_label": section_label,
                    "purpose": purpose,
                    "author_guidance": guidance,
                    "count": len(records),
                    "fields": [
                        {
                            "field_id": str(field.get("field_id") or ""),
                            "label": str(field.get("label") or field.get("field_id") or ""),
                            "field_type": str(field.get("field_type") or ""),
                            "author_hidden": bool(field.get("author_hidden")),
                        }
                        for field in fields
                        if isinstance(field, dict) and field.get("field_id")
                    ],
                    "records": records,
                }
            )

        visible_fields = [
            field
            for field in (section_schema.get("fields") or [])
            if isinstance(field, dict)
            and field.get("field_id")
            and not field.get("author_hidden")
        ]
        if visible_fields or answers_state:
            canon_references.append(
                {
                    "key": f"canon_reference__{section_id}",
                    "section_id": section_id,
                    "label": section_label,
                    "purpose": purpose,
                    "author_guidance": guidance,
                    "fields": [
                        {
                            "field_id": str(field.get("field_id") or ""),
                            "label": str(field.get("label") or field.get("field_id") or ""),
                            "field_type": str(field.get("field_type") or ""),
                        }
                        for field in visible_fields
                    ],
                    "answers": answers_state,
                }
            )

    book_plan_books = book_plan.get("books") if isinstance(book_plan, dict) else []
    book_plan_books = book_plan_books if isinstance(book_plan_books, list) else []
    book_workflow = book_plan.get("book_workflow") if isinstance(book_plan, dict) else []
    book_workflow = book_workflow if isinstance(book_workflow, list) else []
    workflow_by_number = {
        int(item.get("book_number")): item
        for item in book_workflow
        if isinstance(item, dict) and str(item.get("book_number") or "").isdigit()
    }

    chapter_plan_books = chapter_plan.get("books") if isinstance(chapter_plan, dict) else []
    chapter_plan_books = chapter_plan_books if isinstance(chapter_plan_books, list) else []
    chapters_by_book: dict[int, list[dict[str, Any]]] = {}
    flat_chapters: list[dict[str, Any]] = []
    for book_entry in chapter_plan_books:
        if not isinstance(book_entry, dict):
            continue
        try:
            book_number = int(book_entry.get("book_number") or 0)
        except (TypeError, ValueError):
            continue
        chapters = book_entry.get("chapters")
        chapters = chapters if isinstance(chapters, list) else []
        clean_chapters = [item for item in chapters if isinstance(item, dict)]
        chapters_by_book[book_number] = clean_chapters
        flat_chapters.extend(clean_chapters)

    runtime_chapter_records = runtime_chapters if isinstance(runtime_chapters, list) else []
    runtime_scene_records = runtime_scenes if isinstance(runtime_scenes, list) else []
    runtime_book_records = runtime_books if isinstance(runtime_books, list) else []

    expected_books = int(manifest.get("book_count") or len(book_plan_books) or 1)
    chapters_per_book = int(manifest.get("chapters_per_book") or 0)
    plan_by_number = {
        int(item.get("book_number")): item
        for item in book_plan_books
        if isinstance(item, dict) and str(item.get("book_number") or "").isdigit()
    }
    runtime_book_by_number = {
        int(item.get("book_number")): item
        for item in runtime_book_records
        if isinstance(item, dict) and str(item.get("book_number") or "").isdigit()
    }

    book_items: list[dict[str, Any]] = []
    for book_number in range(1, expected_books + 1):
        plan = plan_by_number.get(book_number, {})
        workflow = workflow_by_number.get(book_number, {})
        runtime_book = runtime_book_by_number.get(book_number, {})
        planned_chapters = chapters_by_book.get(book_number, [])
        planned_count = len(planned_chapters)
        chapter_numbers = [
            int(item.get("chapter_number"))
            for item in planned_chapters
            if str(item.get("chapter_number") or "").isdigit()
        ]
        active_chapter = max(chapter_numbers) if chapter_numbers else None
        planning_percent = (
            min(100.0, (planned_count / chapters_per_book) * 100.0)
            if chapters_per_book > 0
            else 0.0
        )
        book_items.append(
            {
                "book_number": book_number,
                "title": str(plan.get("title") or runtime_book.get("title") or f"Book {book_number}"),
                "time_span": str(plan.get("time_span") or ""),
                "planning_status": str(plan.get("status") or workflow.get("approval_status") or "not_planned"),
                "approval_status": str(workflow.get("approval_status") or "not_ready"),
                "approval_fresh": bool(workflow.get("approval_fresh")),
                "planned_chapters": planned_count,
                "target_chapters": chapters_per_book,
                "active_chapter": active_chapter,
                "planning_percent": round(planning_percent, 1),
                "estimated_tokens": int(budget_plan.get("estimated_tokens_per_book") or 0),
                "actual_token_usage_available": False,
            }
        )

    chapter_items: list[dict[str, Any]] = []
    for item in flat_chapters:
        try:
            book_number = int(item.get("book_number") or 0)
            chapter_number = int(item.get("chapter_number") or 0)
        except (TypeError, ValueError):
            continue
        assigned_events = item.get("assigned_event_refs")
        selected_canon = item.get("selected_canon_refs")
        chapter_items.append(
            {
                "book_number": book_number,
                "chapter_number": chapter_number,
                "title": str(item.get("title") or f"Chapter {chapter_number}"),
                "status": str(item.get("status") or "planned"),
                "revision": int(item.get("revision") or 0),
                "event_count": len(assigned_events) if isinstance(assigned_events, list) else 0,
                "canon_count": len(selected_canon) if isinstance(selected_canon, list) else 0,
                "kickoff": str(item.get("generation_kickoff") or ""),
            }
        )

    scene_types: list[str] = []
    if str(manifest.get("genre") or "") == "historical_epic":
        scene_manifest = _read_project_json(
            project_loader.PROJECT_ROOT / "canon_manifests" / "scene_types_manifest.json",
            {},
        )
        candidate_types = scene_manifest.get("scene_types") if isinstance(scene_manifest, dict) else []
        if isinstance(candidate_types, list):
            scene_types = [str(item) for item in candidate_types if str(item).strip()]

    navigation = [
        {"key": "books", "label": "Books", "kind": "universal"},
        {"key": "chapters", "label": "Chapters", "kind": "universal"},
        {"key": "scenes", "label": "Scenes", "kind": "universal"},
    ]
    navigation.extend(
        {
            "key": item["key"],
            "label": item["label"],
            "kind": "canon_collection",
            "count": item["count"],
        }
        for item in canon_collections
    )
    navigation.extend(
        {
            "key": item["key"],
            "label": item["label"],
            "kind": "canon_reference",
        }
        for item in canon_references
        if item.get("section_id") not in {"project_bible"}
    )

    return {
        "schema_version": "workspace_author_library_v1",
        "project_id": str(manifest.get("project_id") or ""),
        "project_name": str(manifest.get("project_name") or "Untitled Project"),
        "template_id": str(manifest.get("template_id") or author_canon.get("template_id") or ""),
        "genre": str(manifest.get("genre") or author_canon.get("genre") or ""),
        "read_only": True,
        "navigation": navigation,
        "universal": {
            "books": {
                "expected_count": expected_books,
                "planned_count": sum(1 for item in book_items if item["planned_chapters"] or item["approval_status"] != "not_ready"),
                "chapters_per_book": chapters_per_book,
                "items": book_items,
            },
            "chapters": {
                "expected_count": expected_books * chapters_per_book,
                "planned_count": len(chapter_items),
                "items": chapter_items,
            },
            "scenes": {
                "count": len(runtime_scene_records),
                "items": runtime_scene_records,
                "planning_context": {
                    "scene_types": scene_types,
                    "governing_canon_sections": governing_sections,
                },
            },
        },
        "canon": {
            "collections": canon_collections,
            "references": canon_references,
        },
        "budget": {
            "token_budget_total": int(budget_plan.get("token_budget_total") or 0),
            "estimated_tokens_per_book": int(budget_plan.get("estimated_tokens_per_book") or 0),
            "estimated_tokens_per_chapter": int(budget_plan.get("estimated_tokens_per_chapter") or 0),
            "actual_usage_available": False,
            "remaining_tokens": None,
        },
    }



def _workspace_author_summary(
    author_status: dict[str, Any],
    markdown_status: dict[str, Any],
) -> dict[str, Any]:
    """Return project-local author canon readiness for workspace presentation."""

    markdown_by_section = {
        str(item.get("section_id") or ""): item
        for item in markdown_status.get("rendered_files") or []
        if item.get("section_id")
    }

    attention_sections: list[dict[str, Any]] = []

    for section in author_status.get("sections") or []:
        section_id = str(section.get("section_id") or "")
        if not section_id:
            continue

        markdown = markdown_by_section.get(section_id, {})
        complete = (
            str(section.get("status") or "") == "complete"
            and not section.get("missing_required_fields")
        )
        markdown_current = (
            markdown.get("render_status") == "current"
            and markdown.get("freshness_verified") is True
        )

        if not complete or not markdown_current:
            attention_sections.append(
                {
                    "section_id": section_id,
                    "label": section.get("label") or section_id,
                    "complete": complete,
                    "markdown_current": markdown_current,
                }
            )

    return {
        "author_section_count": int(author_status.get("section_count") or 0),
        "required_author_section_count": int(
            author_status.get("required_section_count") or 0
        ),
        "completed_required_author_section_count": int(
            author_status.get("completed_required_section_count") or 0
        ),
        "all_required_author_sections_complete": bool(
            author_status.get("all_required_sections_complete")
        ),
        "current_markdown_source_count": int(
            markdown_status.get("current_rendered_file_count") or 0
        ),
        "attention_required_section_count": len(attention_sections),
        "attention_required_sections": attention_sections,
    }




def _read_project_json(path, default: Any) -> Any:
    try:
        return project_loader.read_json(path, default=default)
    except Exception:
        return default


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
            "label": "Canon & Runtime Context",
            "items": [
                _enabled_item("author_canon", "Author Canon"),
                _enabled_item(
                    "project_runtime_context",
                    "Project Runtime Context",
                ),
                (
                    _disabled_item(
                        "book_canon",
                        "Canon for This Book",
                        "Archived projects expose Canon for This Book as read-only.",
                    )
                    if read_only
                    else _enabled_item("book_canon", "Canon for This Book")
                ),
                (
                    _disabled_item(
                        "book_plan",
                        "Book Planner",
                        "Archived projects expose the Book Planner as read-only.",
                    )
                    if read_only
                    else _enabled_item("book_plan", "Book Planner")
                ),
                (
                    _disabled_item(
                        "chapter_planner",
                        "Chapter Planner",
                        "Archived projects expose Chapter Plans as read-only.",
                    )
                    if read_only
                    else _enabled_item("chapter_planner", "Chapter Planner")
                ),
                _enabled_item(
                    "book_runtime_context",
                    "Book Runtime Context",
                ),
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
