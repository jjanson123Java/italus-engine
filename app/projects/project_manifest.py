"""
Project manifest model for project-scoped lifecycle state.

This module is intentionally independent from the existing Italus generation
runtime. It describes the project shell used before workspace entry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import re


LIFECYCLE_DRAFT_SETUP = "DRAFT_SETUP"
LIFECYCLE_CANON_IN_PROGRESS = "CANON_IN_PROGRESS"
LIFECYCLE_READY_FOR_WORKSPACE = "READY_FOR_WORKSPACE"
LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_ARCHIVED = "ARCHIVED"

ACTIVE_STATES = {
    LIFECYCLE_DRAFT_SETUP,
    LIFECYCLE_CANON_IN_PROGRESS,
    LIFECYCLE_READY_FOR_WORKSPACE,
    LIFECYCLE_ACTIVE,
}

INCOMPLETE_STATES = {
    LIFECYCLE_DRAFT_SETUP,
    LIFECYCLE_CANON_IN_PROGRESS,
}

WORKSPACE_READY_STATES = {
    LIFECYCLE_READY_FOR_WORKSPACE,
    LIFECYCLE_ACTIVE,
}

ALL_LIFECYCLE_STATES = ACTIVE_STATES | {LIFECYCLE_ARCHIVED}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify_project_name(project_name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", project_name.strip().lower()).strip("-")
    return cleaned or "untitled-project"


def generate_project_id(project_name: str) -> str:
    return f"{slugify_project_name(project_name)}-{uuid4().hex[:8]}"


@dataclass
class ProjectManifest:
    project_id: str
    project_name: str
    project_kind: str = "single_book"
    series_name: str | None = None
    book_count: int = 1
    chapters_per_book: int = 40
    target_words_per_chapter: int = 4000
    target_words_per_book: int = 160000
    target_total_words: int = 160000
    token_budget_total: int = 250000
    token_budget_per_generation: int = 8000
    genre: str = "historical_epic"
    subgenre: str | None = None
    template_id: str = "historical_epic"
    engine_id: str = "italus"
    ai_provider: str = "claude"
    lifecycle_state: str = LIFECYCLE_DRAFT_SETUP
    previous_state_before_archive: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ProjectManifest":
        project_name = str(payload.get("project_name") or "Untitled Project").strip() or "Untitled Project"
        book_count = _positive_int(payload.get("book_count"), 1)
        chapters_per_book = _positive_int(payload.get("chapters_per_book"), 40)
        target_words_per_chapter = _positive_int(payload.get("target_words_per_chapter"), 4000)
        target_words_per_book = _positive_int(
            payload.get("target_words_per_book"),
            chapters_per_book * target_words_per_chapter,
        )
        target_total_words = _positive_int(
            payload.get("target_total_words"),
            book_count * target_words_per_book,
        )

        return cls(
            project_id=str(payload.get("project_id") or generate_project_id(project_name)),
            project_name=project_name,
            project_kind=str(payload.get("project_kind") or "single_book"),
            series_name=payload.get("series_name"),
            book_count=book_count,
            chapters_per_book=chapters_per_book,
            target_words_per_chapter=target_words_per_chapter,
            target_words_per_book=target_words_per_book,
            target_total_words=target_total_words,
            token_budget_total=_positive_int(payload.get("token_budget_total"), 250000),
            token_budget_per_generation=_positive_int(payload.get("token_budget_per_generation"), 8000),
            genre=str(payload.get("genre") or "historical_epic"),
            subgenre=payload.get("subgenre"),
            template_id=str(payload.get("template_id") or payload.get("genre") or "historical_epic"),
            engine_id=str(payload.get("engine_id") or "italus"),
            ai_provider=str(payload.get("ai_provider") or "claude"),
            lifecycle_state=_normalize_lifecycle_state(payload.get("lifecycle_state")),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectManifest":
        normalized = dict(data)
        normalized["lifecycle_state"] = _normalize_lifecycle_state(normalized.get("lifecycle_state"))
        return cls(**normalized)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalize_lifecycle_state(value: Any) -> str:
    state = str(value or LIFECYCLE_DRAFT_SETUP).upper()
    return state if state in ALL_LIFECYCLE_STATES else LIFECYCLE_DRAFT_SETUP
