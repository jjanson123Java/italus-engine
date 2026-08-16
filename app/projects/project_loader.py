"""
Project-scoped JSON persistence helpers.

This loader only manages files under data/projects/<project_id>. It does not
migrate or modify the existing Italus flat runtime data files.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.projects.project_manifest import ProjectManifest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_ROOT = PROJECT_ROOT / "data" / "projects"


class ProjectNotFoundError(FileNotFoundError):
    """Raised when a project_id has no project directory or manifest."""


class InvalidProjectIdError(ValueError):
    """Raised when a project_id is unsafe for filesystem resolution."""


def ensure_projects_root() -> Path:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    return PROJECTS_ROOT


def validate_project_id(project_id: str) -> str:
    cleaned = str(project_id or "").strip()
    if not cleaned:
        raise InvalidProjectIdError("project_id is required")
    if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise InvalidProjectIdError("project_id contains illegal path characters")
    return cleaned


def project_dir(project_id: str, *, create: bool = False) -> Path:
    safe_id = validate_project_id(project_id)
    root = ensure_projects_root()
    path = (root / safe_id).resolve()

    if root.resolve() not in path.parents and path != root.resolve():
        raise InvalidProjectIdError("project_id escapes project storage root")

    if create:
        path.mkdir(parents=True, exist_ok=True)

    return path


def delete_project_directory(project_id: str) -> None:
    """Delete one validated project-local storage tree.

    Lifecycle authorization belongs to project_service. This helper only owns
    the filesystem boundary under data/projects/<project_id>.
    """

    path = project_dir(project_id)
    manifest = path / "project_manifest.json"

    if not path.exists() or not manifest.exists():
        raise ProjectNotFoundError(f"Project manifest not found: {project_id}")

    shutil.rmtree(path)

    if path.exists():
        raise OSError(f"Project directory could not be fully removed: {project_id}")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(str(path))

    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def manifest_path(project_id: str) -> Path:
    return project_dir(project_id) / "project_manifest.json"


def wizard_state_path(project_id: str) -> Path:
    return project_dir(project_id) / "wizard_state.json"


def budget_plan_path(project_id: str) -> Path:
    return project_dir(project_id) / "budget_plan.json"


def archive_state_path(project_id: str) -> Path:
    return project_dir(project_id) / "archive_state.json"


def load_manifest(project_id: str) -> ProjectManifest:
    path = manifest_path(project_id)
    if not path.exists():
        raise ProjectNotFoundError(f"Project manifest not found: {project_id}")
    return ProjectManifest.from_dict(read_json(path))


def save_manifest(manifest: ProjectManifest) -> None:
    manifest.touch()
    project_dir(manifest.project_id, create=True)
    write_json(manifest_path(manifest.project_id), manifest.to_dict())


def load_wizard_state(project_id: str) -> dict[str, Any]:
    return read_json(wizard_state_path(project_id), default={})


def save_wizard_state(project_id: str, state: dict[str, Any]) -> None:
    write_json(wizard_state_path(project_id), state)


def load_budget_plan(project_id: str) -> dict[str, Any]:
    return read_json(budget_plan_path(project_id), default={})


def save_budget_plan(project_id: str, plan: dict[str, Any]) -> None:
    write_json(budget_plan_path(project_id), plan)


def save_archive_state(project_id: str, state: dict[str, Any]) -> None:
    write_json(archive_state_path(project_id), state)


def list_project_ids() -> list[str]:
    root = ensure_projects_root()
    project_ids: list[str] = []

    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "project_manifest.json").exists():
            project_ids.append(child.name)

    return project_ids
