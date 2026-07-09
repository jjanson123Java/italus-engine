"""
Project context resolution.

This adapter is the boundary between the new project lifecycle storage and the
legacy Italus root-level canon/runtime files. It does not rewrite the existing
generation runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.templates.template_registry import get_template, normalize_template_id


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    template_id: str
    genre: str
    project_code: str
    storage_mode: str
    seed_mode: str
    project_root: Path
    project_dir: Path
    project_canon_sources_dir: Path
    project_canon_packs_dir: Path
    project_canon_manifests_dir: Path
    project_canon_generated_dir: Path
    legacy_canon_sources_dir: Path
    legacy_canon_packs_dir: Path
    legacy_canon_manifests_dir: Path
    runtime_data_dir: Path

    def ensure_project_canon_dirs(self) -> None:
        """Create the project-local canon workspace without moving legacy canon files."""
        for path in (
            self.project_canon_sources_dir,
            self.project_canon_packs_dir,
            self.project_canon_manifests_dir,
            self.project_canon_generated_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
            gitkeep = path / ".gitkeep"
            if not gitkeep.exists():
                gitkeep.write_text("", encoding="utf-8")


def build_project_context(manifest: Any) -> ProjectContext:
    manifest_dict = manifest.to_dict() if hasattr(manifest, "to_dict") else dict(manifest)
    template_id = normalize_template_id(
        manifest_dict.get("template_id"),
        manifest_dict.get("genre"),
    )
    template = get_template(template_id, manifest_dict.get("genre"))
    project_code = str(template.get("project_code") or _project_code_from_id(manifest_dict["project_id"]))

    project_dir = project_loader.project_dir(manifest_dict["project_id"], create=True)
    project_root = project_loader.PROJECT_ROOT

    return ProjectContext(
        project_id=manifest_dict["project_id"],
        template_id=template_id,
        genre=str(manifest_dict.get("genre") or template.get("genre") or template_id),
        project_code=project_code,
        storage_mode=str(template.get("project_storage_mode") or "project_local"),
        seed_mode=str(template.get("seed_mode") or "blank_project_local"),
        project_root=project_root,
        project_dir=project_dir,
        project_canon_sources_dir=project_dir / "canon_sources",
        project_canon_packs_dir=project_dir / "canon_packs",
        project_canon_manifests_dir=project_dir / "canon_manifests",
        project_canon_generated_dir=project_dir / "canon_generated",
        legacy_canon_sources_dir=project_root / "canon_sources",
        legacy_canon_packs_dir=project_root / "canon_packs",
        legacy_canon_manifests_dir=project_root / "canon_manifests",
        runtime_data_dir=project_dir / "runtime",
    )


def resolve_relative_path(context: ProjectContext, relative_path: str, *, prefer_project_local: bool = True) -> tuple[Path, str]:
    """Resolve a canon path while preserving legacy seed reference mode."""

    clean_path = relative_path.replace("\\", "/").lstrip("/")
    project_candidate = context.project_dir / clean_path
    legacy_candidate = context.project_root / clean_path

    if prefer_project_local and project_candidate.exists():
        return project_candidate, "project_local"

    if context.seed_mode == "legacy_root_reference" and legacy_candidate.exists():
        return legacy_candidate, "legacy_root_reference"

    if prefer_project_local:
        return project_candidate, "project_local"

    return legacy_candidate, "legacy_root_reference"


def _project_code_from_id(project_id: str) -> str:
    prefix = project_id.split("-", 1)[0] if project_id else "PROJECT"
    return "".join(ch for ch in prefix.upper() if ch.isalnum()) or "PROJECT"
