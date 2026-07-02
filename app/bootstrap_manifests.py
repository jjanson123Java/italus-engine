from __future__ import annotations

import json
import re
from pathlib import Path

from app.ITALUS_PROJECT_RUNNER_MENU_TONE import (
    ARCH_FILE,
    BACKBONE_FILE,
    read_text,
    parse_architecture_map,
    parse_backbone,
)
from app.canon_manifest_loader import MANIFEST_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"



def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
def normalize_book_number(value) -> int:
    """
    Normalize legacy book values like:
    1, "1", "Book 1", "BOOK 1"
    into integer 1.
    """
    if isinstance(value, int):
        return value

    text = str(value).strip()
    match = re.search(r"(\d+)", text)
    if not match:
        raise ValueError(f"Could not extract book number from value: {value!r}")

    return int(match.group(1))
    
def build_event_chapter_map(events: list) -> dict:
    """
    Build a synthetic but consistent chapter map:
    each event in a book becomes the next chapter in that book.
    """
    chapter_map = {}
    per_book_counts = {}

    for event in events:
        book_num = normalize_book_number(event.book)
        book_id = f"BOOK_{book_num:02d}"
        event_id = str(event.event_id).strip()

        per_book_counts.setdefault(book_id, 0)
        per_book_counts[book_id] += 1

        chapter_number = per_book_counts[book_id]
        chapter_id = f"{book_id}_CH_{chapter_number:02d}"

        chapter_map[(book_id, event_id)] = {
            "chapter_id": chapter_id,
            "chapter_number": chapter_number,
            "title": f"Chapter {chapter_number}",
            "event_id": event_id,
            "event_name": getattr(event, "event", ""),
        }

    return chapter_map


def build_book_chapters_from_event_map(book_id: str, chapter_map: dict) -> list:
    """
    Return ordered chapter records for a book from the synthetic chapter map.
    """
    chapters = [
        value for (mapped_book_id, _event_id), value in chapter_map.items()
        if mapped_book_id == book_id
    ]

    chapters = sorted(chapters, key=lambda ch: ch["chapter_number"])

    seen = set()
    unique_chapters = []
    for chapter in chapters:
        chapter_id = chapter["chapter_id"]
        if chapter_id in seen:
            continue
        seen.add(chapter_id)

        unique_chapters.append(
            {
                "chapter_id": chapter["chapter_id"],
                "chapter_number": chapter["chapter_number"],
                "title": chapter["title"],
                "status": "active",
            }
        )

    return unique_chapters


def build_books_manifest(books: dict, chapter_map: dict) -> dict:
    manifest_books = []

    for num in sorted(books, key=lambda x: normalize_book_number(x)):
        book = books[num]

        book_num = normalize_book_number(book.number)
        book_id = f"BOOK_{book_num:02d}"

        chapters = build_book_chapters_from_event_map(book_id, chapter_map)

        if not chapters:
            chapters = [
                {
                    "chapter_id": f"{book_id}_CH_01",
                    "chapter_number": 1,
                    "title": "Chapter 1",
                    "status": "active",
                }
            ]
        manifest_books.append(
            {
                "book_id": book_id,
                "book_number": book_num,
                "title": book.title,
                "years": getattr(book, "years", ""),
                "primary_guardians": [g.strip() for g in str(getattr(book, "guardians", "")).split(",") if g.strip()],
                "status": "active",
                "chapters": chapters,
            }
        )

    return {"books": manifest_books}


def build_events_manifest(events: list, chapter_map: dict) -> dict:
    manifest_events = []

    for event in events:
        book_num = normalize_book_number(event.book)
        book_id = f"BOOK_{book_num:02d}"

        mapped = chapter_map.get((book_id, str(event.event_id).strip()))
        if mapped:
            chapter_id = mapped["chapter_id"]
        else:
            chapter_id = f"{book_id}_CH_01"

        guardian_defaults = []
        if getattr(event, "guardian", ""):
            guardian_defaults = [event.guardian]

        location_defaults = []
        if getattr(event, "region", ""):
            location_defaults = [event.region]

        manifest_events.append(
            {
                "event_id": event.event_id,
                "event_name": event.event,
                "book_id": book_id,
                "chapter_id": chapter_id,
                "year": getattr(event, "year", ""),
                "guardian_defaults": guardian_defaults,
                "location_defaults": location_defaults,
                "historical_context": event.event,
                "status": "active",
            }
        )

    return {"events": manifest_events}


def build_series_manifest(books_manifest: dict) -> dict:
    books = books_manifest.get("books", [])
    active_book_ids = [b["book_id"] for b in books if b.get("status") == "active"]
    default_book_id = active_book_ids[0] if active_book_ids else ""

    return {
        "series_id": "ITALUS",
        "series_title": "The Italus Saga",
        "version": "1.0",
        "active": True,
        "active_books": active_book_ids,
        "default_book_id": default_book_id,
        "default_scene_types_manifest": "scene_types_manifest.json",
        "default_books_manifest": "books_manifest.json",
        "default_events_manifest": "events_manifest.json",
        "default_pack_manifest": "pack_manifest.json",
    }


def build_pack_manifest(books_manifest: dict) -> dict:
    book_packs = {}

    for book in books_manifest.get("books", []):
        book_id = book["book_id"]
        book_packs[book_id] = f"canon_packs/ITALUS_KNOWLEDGE_PACK_{book_id}.txt"

    return {
        "core_pack": "canon_packs/ITALUS_KNOWLEDGE_PACK_CORE.txt",
        "generation_pack": "canon_packs/ITALUS_KNOWLEDGE_PACK_GENERATION.txt",
        "book_packs": book_packs,
    }


def bootstrap_from_root():
    books = parse_architecture_map(read_text(DOCS_DIR / ARCH_FILE))
    events = parse_backbone(read_text(DOCS_DIR / BACKBONE_FILE))
    chapter_map = build_event_chapter_map(events)

    books_manifest = build_books_manifest(books, chapter_map)
    events_manifest = build_events_manifest(events, chapter_map)
    series_manifest = build_series_manifest(books_manifest)
    pack_manifest = build_pack_manifest(books_manifest)

    save_json(MANIFEST_DIR / "books_manifest.json", books_manifest)
    save_json(MANIFEST_DIR / "events_manifest.json", events_manifest)
    save_json(MANIFEST_DIR / "series_manifest.json", series_manifest)
    save_json(MANIFEST_DIR / "pack_manifest.json", pack_manifest)

    print("Manifest bootstrap complete.")
    print(f"Books written: {len(books_manifest.get('books', []))}")
    print(f"Events written: {len(events_manifest.get('events', []))}")

if __name__ == "__main__":
    bootstrap_from_root()