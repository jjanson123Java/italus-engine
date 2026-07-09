"""
Project-local runtime storage service.

This service is the Stage 9 storage boundary for Italus project runtime files.
It owns safe creation of empty project-local runtime containers during backend
project lifecycle events. It never copies legacy data, runs generation, calls
providers, validates output, or exports files.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context


RUNTIME_STORAGE_MARKER = "project-runtime-storage-service-20260708"

RUNTIME_STORAGE_AUTO_INIT_MARKER = "runtime-storage-auto-initialize-20260708"

EMPTY_RUNTIME_PAYLOADS: dict[str, Any] = {
    "books.json": [],
    "chapters.json": [],
    "scenes.json": [],
    "session_state.json": {},
    "coverage_map.json": {},
    "book_state.json": {},
    "chapter_continuity_digests.json": [],
}


RUNTIME_FILE_CONTRACT: tuple[dict[str, str], ...] = (
    {
        "file_name": "books.json",
        "label": "Books",
        "role": "author_facing",
        "description": "Project-local generated book-level manuscript records.",
    },
    {
        "file_name": "chapters.json",
        "label": "Chapters",
        "role": "author_facing",
        "description": "Project-local generated chapter records.",
    },
    {
        "file_name": "scenes.json",
        "label": "Scenes",
        "role": "author_facing",
        "description": "Project-local generated scene text and scene metadata.",
    },
    {
        "file_name": "session_state.json",
        "label": "Writing Session",
        "role": "author_facing",
        "description": "Project-local resumable writing session state.",
    },
    {
        "file_name": "coverage_map.json",
        "label": "Continuity Coverage",
        "role": "author_facing",
        "description": "Project-local continuity and coverage tracking.",
    },
    {
        "file_name": "book_state.json",
        "label": "Book State",
        "role": "internal_continuity",
        "description": "Internal project-local book generation state.",
    },
    {
        "file_name": "chapter_continuity_digests.json",
        "label": "Chapter Continuity Digests",
        "role": "internal_continuity",
        "description": "Internal project-local continuity digests used by later runtime migration stages.",
    },
)


@dataclass(frozen=True)
class RuntimeFileStatus:
    file_name: str
    label: str
    role: str
    relative_path: str
    exists: bool
    status: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "label": self.label,
            "role": self.role,
            "relative_path": self.relative_path,
            "exists": self.exists,
            "status": self.status,
            "description": self.description,
        }


def get_runtime_storage_status(project_id: str) -> dict[str, Any]:
    """Return project runtime storage status for an existing project.

    The function loads the project manifest and resolves ProjectContext. It does
    not create runtime files when called directly.
    """

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_runtime_storage_status_for_context(context)


def ensure_runtime_storage(project_id: str) -> dict[str, Any]:
    """Ensure empty project-local runtime containers exist for a project.

    This is idempotent. It creates the runtime directory and missing required
    JSON files only. It never overwrites existing runtime files and never copies
    legacy root data.
    """

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return ensure_runtime_storage_for_context(context)


def ensure_runtime_storage_for_manifest(manifest: Any) -> dict[str, Any]:
    """Ensure runtime storage for a manifest object already loaded by a caller."""

    context = build_project_context(manifest)
    return ensure_runtime_storage_for_context(context)


def ensure_runtime_storage_for_context(context: ProjectContext) -> dict[str, Any]:
    """Create missing empty runtime files without overwriting existing content."""

    runtime_dir = _validated_runtime_dir(context)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    created_files: list[str] = []
    existing_files: list[str] = []

    for spec in RUNTIME_FILE_CONTRACT:
        file_name = spec["file_name"]
        file_path = runtime_dir / file_name

        if file_path.exists():
            existing_files.append(file_name)
            continue

        payload = EMPTY_RUNTIME_PAYLOADS[file_name]
        file_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        created_files.append(file_name)

    status = get_runtime_storage_status_for_context(context)
    status["auto_initialization"] = {
        "marker": RUNTIME_STORAGE_AUTO_INIT_MARKER,
        "created_files": created_files,
        "existing_files": existing_files,
        "policy": "create_missing_empty_runtime_files_only",
        "legacy_copy": "never",
    }
    return status


def get_runtime_storage_status_for_context(context: ProjectContext) -> dict[str, Any]:
    """Return a read-only status payload for the project-local runtime folder."""

    runtime_dir = _validated_runtime_dir(context)
    runtime_dir_exists = runtime_dir.exists() and runtime_dir.is_dir()
    file_statuses = [_runtime_file_status(context, spec) for spec in RUNTIME_FILE_CONTRACT]
    required_files_present = all(item.exists for item in file_statuses)
    initialized = bool(runtime_dir_exists and required_files_present)

    return {
        "marker": RUNTIME_STORAGE_MARKER,
        "project_id": context.project_id,
        "runtime_root": _relative(runtime_dir),
        "runtime_root_exists": runtime_dir_exists,
        "status": "initialized" if initialized else "not_initialized",
        "initialized": initialized,
        "runtime_ready": False,
        "generation_ready": False,
        "creates_runtime_files": True,
        "auto_initialization_marker": RUNTIME_STORAGE_AUTO_INIT_MARKER,
        "migration_policy": "auto_ensure_empty_project_runtime_no_legacy_copy",
        "legacy_source_mode": "legacy_root_read_only",
        "file_contract_version": "stage9_seven_file_contract",
        "required_file_count": len(RUNTIME_FILE_CONTRACT),
        "required_files_present": required_files_present,
        "files": [item.to_dict() for item in file_statuses],
        "locked_actions": {
            "create_runtime_folder": "auto_ensured_by_project_creation_and_workspace_bootstrap",
            "copy_legacy_data": "blocked_until_migration_design",
            "save_generated_scenes": "blocked_until_generation_storage_migration",
            "enable_generation": "blocked_until_all_runtime_gates_pass",
        },
        "message": (
            "Project runtime storage is owned by the backend lifecycle. "
            "New projects and workspace bootstrap ensure empty project-local runtime files without copying legacy data."
        ),
    }


def runtime_file_names() -> list[str]:
    """Return the allowlisted runtime file names for future storage patches."""

    return [spec["file_name"] for spec in RUNTIME_FILE_CONTRACT]


def _runtime_file_status(context: ProjectContext, spec: dict[str, str]) -> RuntimeFileStatus:
    runtime_dir = _validated_runtime_dir(context)
    file_path = runtime_dir / spec["file_name"]
    exists = file_path.exists() and file_path.is_file()
    return RuntimeFileStatus(
        file_name=spec["file_name"],
        label=spec["label"],
        role=spec["role"],
        relative_path=_relative(file_path),
        exists=exists,
        status="present" if exists else "not_created",
        description=spec["description"],
    )


def _validated_runtime_dir(context: ProjectContext) -> Path:
    runtime_dir = context.runtime_data_dir.resolve()
    project_dir = context.project_dir.resolve()

    if project_dir not in runtime_dir.parents:
        raise project_loader.InvalidProjectIdError("runtime path escapes project directory")

    expected_name = "runtime"
    if runtime_dir.name != expected_name:
        raise project_loader.InvalidProjectIdError("runtime path does not target project runtime directory")

    return runtime_dir


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(project_loader.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
