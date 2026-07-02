from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = PROJECT_ROOT / "canon_manifests"


def load_json_file(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_path(filename: str) -> Path:
    return MANIFEST_DIR / filename


def load_series_manifest() -> dict:
    return load_json_file(manifest_path("series_manifest.json"), {})


def load_books_manifest() -> dict:
    return load_json_file(manifest_path("books_manifest.json"), {"books": []})


def load_events_manifest() -> dict:
    return load_json_file(manifest_path("events_manifest.json"), {"events": []})


def load_scene_types_manifest() -> dict:
    return load_json_file(manifest_path("scene_types_manifest.json"), {"scene_types": []})


def load_pack_manifest() -> dict:
    return load_json_file(manifest_path("pack_manifest.json"), {})


def get_active_books() -> List[dict]:
    books_manifest = load_books_manifest()
    return [
        book for book in books_manifest.get("books", [])
        if book.get("status", "active") == "active"
    ]


def get_book(book_id: str) -> Optional[dict]:
    for book in get_active_books():
        if book.get("book_id") == book_id:
            return book
    return None


def get_chapters_for_book(book_id: str) -> List[dict]:
    book = get_book(book_id)
    if not book:
        return []
    return [
        chapter for chapter in book.get("chapters", [])
        if chapter.get("status", "active") == "active"
    ]


def get_active_events() -> List[dict]:
    events_manifest = load_events_manifest()
    return [
        event for event in events_manifest.get("events", [])
        if event.get("status", "active") == "active"
    ]


def get_events_for_book(book_id: str) -> List[dict]:
    return [
        event for event in get_active_events()
        if event.get("book_id") == book_id
    ]


def get_events_for_chapter(book_id: str, chapter_id: str) -> List[dict]:
    return [
        event for event in get_active_events()
        if event.get("book_id") == book_id and event.get("chapter_id") == chapter_id
    ]


def get_event(event_id: str) -> Optional[dict]:
    for event in get_active_events():
        if event.get("event_id") == event_id:
            return event
    return None


def get_scene_types() -> List[str]:
    scene_manifest = load_scene_types_manifest()
    return scene_manifest.get("scene_types", [])


def get_pack_paths() -> dict:
    return load_pack_manifest()


def get_book_pack_path(book_id: str) -> str:
    pack_manifest = get_pack_paths()
    return pack_manifest.get("book_packs", {}).get(book_id, "")


def build_request_defaults_from_event(event_id: str) -> dict:
    event = get_event(event_id)
    if not event:
        return {}

    guardian_defaults = event.get("guardian_defaults", [])
    location_defaults = event.get("location_defaults", [])

    return {
        "book_id": event.get("book_id", ""),
        "chapter_id": event.get("chapter_id", ""),
        "event_id": event.get("event_id", ""),
        "event_name": event.get("event_name", ""),
        "year": event.get("year", ""),
        "guardian": guardian_defaults[0] if guardian_defaults else "",
        "location": location_defaults[0] if location_defaults else "",
        "historical_context": event.get("historical_context", "")
    }