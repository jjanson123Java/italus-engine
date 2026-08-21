"""Project-local author-facing mystery/reveal planning catalog.

The catalog is planning metadata, not Master Canon. It gives the Chapter Planner
human-readable reveal threads and suggested control defaults while Story Control
and Story Eligibility remain the legality authorities.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.projects.project_context import build_project_context

SERVICE_MARKER = "project-planner-reveal-catalog-20260818"
SCHEMA_VERSION = "planner_reveal_catalog_v1"
FILENAME = "planner_reveal_catalog.json"


def catalog_path(project_id: str) -> Path:
    manifest = project_loader.load_manifest(project_id)
    return build_project_context(manifest).project_dir / FILENAME


def get_reveal_catalog(
    project_id: str,
    *,
    book_number: int | None = None,
) -> dict[str, Any]:
    path = catalog_path(project_id)
    if not path.exists():
        return {
            "status": "ok",
            "service": SERVICE_MARKER,
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "exists": False,
            "threads": [],
        }
    data = project_loader.read_json(path, default={})
    threads = list(data.get("threads") or []) if isinstance(data, dict) else []
    if book_number is not None:
        number = int(book_number)
        threads = [
            item for item in threads
            if number in {int(value) for value in (item.get("eligible_books") or []) if str(value).isdigit()}
        ]
    return {
        "status": "ok",
        "service": SERVICE_MARKER,
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "exists": True,
        "threads": threads,
    }
