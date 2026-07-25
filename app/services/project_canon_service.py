"""
Project-local author canon storage service.

This service is the storage boundary for future author-facing canon
questionnaire answers. It creates and reads project-local author canon JSON
artifacts only.

It does not render Markdown, generate knowledge/control packs, call prompt
construction, call providers, write runtime memory, or unlock generation.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import canon_template_service


PROJECT_CANON_SERVICE_MARKER = "project-local-author-canon-storage-boundary-20260715"
PROJECT_CANON_SCHEMA_VERSION = "project_author_canon_v1"


def project_canon_dir(project_id: str, *, create: bool = False) -> Path:
    """Return the project-local author canon directory."""

    path = project_loader.project_dir(project_id, create=True) / "canon"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def project_canon_dir_for_context(context: ProjectContext, *, create: bool = False) -> Path:
    """Return the project-local author canon directory for an existing context."""

    path = context.project_dir / "canon"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def author_canon_path(project_id: str) -> Path:
    """Return the project-local author canon JSON path."""

    return project_canon_dir(project_id) / "author_canon.json"


def template_snapshot_path(project_id: str) -> Path:
    """Return the project-local canon template snapshot path."""

    return project_canon_dir(project_id) / "template_snapshot.json"


def canon_completion_path(project_id: str) -> Path:
    """Return the project-local canon completion status path."""

    return project_canon_dir(project_id) / "canon_completion.json"


def author_canon_path_for_context(context: ProjectContext) -> Path:
    """Return the author canon JSON path for an existing context."""

    return project_canon_dir_for_context(context) / "author_canon.json"


def template_snapshot_path_for_context(context: ProjectContext) -> Path:
    """Return the template snapshot JSON path for an existing context."""

    return project_canon_dir_for_context(context) / "template_snapshot.json"


def canon_completion_path_for_context(context: ProjectContext) -> Path:
    """Return the completion status JSON path for an existing context."""

    return project_canon_dir_for_context(context) / "canon_completion.json"


def get_project_canon_status(project_id: str) -> dict[str, Any]:
    """Return read-only project-local author canon storage status."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_project_canon_status_for_context(context, manifest.to_dict())


def get_project_canon_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return compact status for the author canon storage files."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    paths = _paths_for_context(context)
    file_status = {
        key: _file_status(path, context.project_dir)
        for key, path in paths.items()
    }
    completion = _load_json_if_present(paths["canon_completion"], default={})
    author_canon = _load_json_if_present(paths["author_canon"], default={})

    return {
        "status": "ok",
        "service": PROJECT_CANON_SERVICE_MARKER,
        "schema_version": PROJECT_CANON_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": schema.get("template_id"),
        "genre": schema.get("genre"),
        "canon_dir": _relative(project_canon_dir_for_context(context), context.project_dir),
        "files": file_status,
        "author_canon_exists": paths["author_canon"].exists(),
        "template_snapshot_exists": paths["template_snapshot"].exists(),
        "canon_completion_exists": paths["canon_completion"].exists(),
        "section_count": len(schema.get("sections", [])),
        "required_section_count": int(
            schema.get("completion_model", {}).get("required_section_count") or 0
        ),
        "completed_required_section_count": int(
            completion.get("completed_required_section_count") or 0
        ),
        "author_canon_status": author_canon.get("status", "missing"),
        "storage_ready": all(path.exists() for path in paths.values()),
        "execution_locks": _execution_locks(),
    }


def load_author_canon(project_id: str) -> dict[str, Any]:
    """Load project-local author canon JSON.

    Missing files are not created by this function.
    """

    return project_loader.read_json(author_canon_path(project_id), default={})


def ensure_author_canon(project_id: str) -> dict[str, Any]:
    """Ensure project-local author canon storage files exist."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return ensure_author_canon_for_context(context, manifest.to_dict())


def ensure_author_canon_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure author canon, template snapshot, and completion JSON exist.

    Existing files are preserved. Missing files are created with inert draft
    payloads derived from the selected questionnaire schema.
    """

    schema = template_schema or _template_schema_for_manifest(manifest)
    project_canon_dir_for_context(context, create=True)
    paths = _paths_for_context(context)
    created: list[str] = []

    if not paths["author_canon"].exists():
        project_loader.write_json(
            paths["author_canon"],
            build_default_author_canon(context.project_id, manifest, schema),
        )
        created.append("author_canon.json")

    if not paths["template_snapshot"].exists():
        project_loader.write_json(
            paths["template_snapshot"],
            build_template_snapshot(context.project_id, manifest, schema),
        )
        created.append("template_snapshot.json")

    if not paths["canon_completion"].exists():
        project_loader.write_json(
            paths["canon_completion"],
            build_default_canon_completion(context.project_id, manifest, schema),
        )
        created.append("canon_completion.json")

    status = get_project_canon_status_for_context(context, manifest, schema)
    status["created"] = created
    return status


def save_author_canon(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Save a complete author canon payload to the project-local canon store.

    This is a storage operation only. It does not render Markdown, generate
    packets, or write runtime memory.
    """

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    project_canon_dir_for_context(context, create=True)

    normalized = deepcopy(payload or {})
    now = utc_now_iso()
    normalized.setdefault("schema_version", PROJECT_CANON_SCHEMA_VERSION)
    normalized["project_id"] = context.project_id
    normalized.setdefault("template_id", manifest.template_id)
    normalized.setdefault("genre", manifest.genre)
    normalized.setdefault("status", "draft")
    normalized.setdefault("sections", {})
    metadata = dict(normalized.get("metadata") or {})
    metadata.setdefault("created_at", now)
    metadata["updated_at"] = now
    metadata["source"] = PROJECT_CANON_SERVICE_MARKER
    normalized["metadata"] = metadata

    project_loader.write_json(author_canon_path_for_context(context), normalized)
    return normalized


def build_default_author_canon(
    project_id: str,
    manifest: dict[str, Any] | None = None,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an empty draft author canon payload from a questionnaire schema."""

    manifest_dict = dict(manifest or {})
    schema = template_schema or _template_schema_for_manifest(manifest_dict)
    now = utc_now_iso()
    sections: dict[str, Any] = {}

    for section in schema.get("sections", []):
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        sections[section_id] = {
            "section_id": section_id,
            "status": "not_started",
            "answers": {},
            "records": [],
            "updated_at": None,
        }

    return {
        "schema_version": PROJECT_CANON_SCHEMA_VERSION,
        "project_id": project_id,
        "template_id": schema.get("template_id") or manifest_dict.get("template_id"),
        "genre": schema.get("genre") or manifest_dict.get("genre"),
        "status": "draft",
        "sections": sections,
        "metadata": {
            "created_at": now,
            "updated_at": now,
            "source": PROJECT_CANON_SERVICE_MARKER,
        },
        "execution_locks": _execution_locks(),
    }


def build_template_snapshot(
    project_id: str,
    manifest: dict[str, Any] | None = None,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a project-local snapshot of the selected questionnaire schema."""

    manifest_dict = dict(manifest or {})
    schema = template_schema or _template_schema_for_manifest(manifest_dict)
    return {
        "schema_version": PROJECT_CANON_SCHEMA_VERSION,
        "project_id": project_id,
        "template_id": schema.get("template_id") or manifest_dict.get("template_id"),
        "genre": schema.get("genre") or manifest_dict.get("genre"),
        "questionnaire": deepcopy(schema),
        "metadata": {
            "created_at": utc_now_iso(),
            "source": PROJECT_CANON_SERVICE_MARKER,
        },
        "execution_locks": _execution_locks(),
    }


def build_default_canon_completion(
    project_id: str,
    manifest: dict[str, Any] | None = None,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an empty completion payload for the selected questionnaire schema."""

    manifest_dict = dict(manifest or {})
    schema = template_schema or _template_schema_for_manifest(manifest_dict)
    section_status: dict[str, Any] = {}
    required_count = 0

    for section in schema.get("sections", []):
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        required = bool(section.get("required"))
        if required:
            required_count += 1
        section_status[section_id] = {
            "section_id": section_id,
            "required": required,
            "status": "not_started",
            "missing_required_fields": _required_field_ids(section),
        }

    return {
        "schema_version": PROJECT_CANON_SCHEMA_VERSION,
        "project_id": project_id,
        "template_id": schema.get("template_id") or manifest_dict.get("template_id"),
        "genre": schema.get("genre") or manifest_dict.get("genre"),
        "required_section_count": required_count,
        "completed_required_section_count": 0,
        "section_status": section_status,
        "metadata": {
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "source": PROJECT_CANON_SERVICE_MARKER,
        },
        "execution_locks": _execution_locks(),
    }


def _template_schema_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return canon_template_service.get_canon_questionnaire_template(
        manifest.get("template_id"),
        manifest.get("genre"),
    )


def _paths_for_context(context: ProjectContext) -> dict[str, Path]:
    return {
        "author_canon": author_canon_path_for_context(context),
        "template_snapshot": template_snapshot_path_for_context(context),
        "canon_completion": canon_completion_path_for_context(context),
    }


def _file_status(path: Path, project_dir: Path) -> dict[str, Any]:
    return {
        "exists": path.exists(),
        "relative_path": _relative(path, project_dir),
    }


def _load_json_if_present(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default)
    data = project_loader.read_json(path, default=default)
    return data if isinstance(data, dict) else deepcopy(default)


def _required_field_ids(section: dict[str, Any]) -> list[str]:
    required: list[str] = []

    for field in section.get("fields", []):
        if field.get("required"):
            required.append(str(field.get("field_id")))

    for record in section.get("records", []):
        if record.get("required"):
            record_id = str(record.get("record_id") or "record")
            for field in record.get("fields", []):
                if field.get("required"):
                    required.append(f"{record_id}.{field.get('field_id')}")

    return required


def _relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def _execution_locks() -> dict[str, bool]:
    return {
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "draft_validation_enabled": False,
        "approved_persistence_enabled": False,
        "export_enabled": False,
    }
