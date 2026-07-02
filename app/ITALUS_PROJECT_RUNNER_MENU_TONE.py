"""
ITALUS Project Runner
Interactive + CLI runner for building AI-ready prompts from Italus canon files.

If run with no arguments, shows a text menu.
If run with arguments, behaves like a CLI tool.

New in this version:
- Automatic tone derivation based on:
    * historical event energy
    * Italus emotional stage
    * guardian archetype
- Interactive mode asks whether to use derived defaults
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from app.canon_manifest_loader import (
    get_active_books,
    get_chapters_for_book,
    get_events_for_chapter,
    get_scene_types,
    build_request_defaults_from_event,
)


from app.project_runner import (
    generate_scene_payload,
    get_ai_provider_config,
    save_accepted_scene_payload,
)


ARCH_FILE = "italus_saga_architecture_map.txt"
BACKBONE_FILE = "ITALUS_HISTORICAL_EVENT_BACKBONE.txt"
SCENE_MATRIX_FILE = "ITALUS_SCENE_GENERATOR_MATRIX.txt"


@dataclass
class Book:
    number: int
    title: str = ""
    years: str = ""
    guardians: str = ""
    stage: str = ""
    anchors: List[str] = field(default_factory=list)
    travel_route: List[str] = field(default_factory=list)
    function: List[str] = field(default_factory=list)

    @property
    def first_year(self) -> str:
        return self.years.split("–")[0].strip() if "–" in self.years else self.years.strip()

    @property
    def primary_guardian(self) -> str:
        g = self.guardians.strip()
        if "," in g:
            return g.split(",")[0].strip()
        if "/" in g:
            return g.split("/")[0].strip()
        return g


@dataclass
class Event:
    event_id: str
    year: str
    event: str
    region: str
    book: str
    guardian: str


@dataclass
class Scene:
    scene_id: str
    event_id: str
    year: str
    book: str
    guardian: str
    location: str
    scene_type: str
    historical_character: str
    scene_seed: str


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    return path.read_text(encoding="utf-8", errors="ignore")


def section_lines(block: str, heading: str) -> List[str]:
    pattern = re.compile(rf"{re.escape(heading)}\s*\n(.*?)(?=\n[A-Z][A-Z \-']+\n|\n=+\n|$)", re.DOTALL)
    m = pattern.search(block)
    if not m:
        return []
    lines = [ln.strip() for ln in m.group(1).splitlines()]
    return [ln for ln in lines if ln]


def parse_architecture_map(text: str) -> Dict[int, Book]:
    books: Dict[int, Book] = {}
    matches = list(re.finditer(r"(?m)^BOOK\s+(\d+)\s*$", text))
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else text.find("SERIES STAGE MAP")
        end = end if end != -1 else len(text)
        block = text[start:end]

        number = int(match.group(1))
        title = re.search(r"(?m)^TITLE:\s*(.+)$", block)
        years = re.search(r"(?m)^YEARS:\s*(.+)$", block)
        guardians = re.search(r"(?m)^PRIMARY GUARDIAN[S]?:\s*(.+)$", block)
        stage_lines = section_lines(block, "ITALUS EMOTIONAL STAGE")
        anchor_lines = [ln.lstrip("- ").strip() for ln in section_lines(block, "HISTORICAL ANCHOR EVENTS")]
        route_lines = [ln.lstrip("- ").strip() for ln in section_lines(block, "TRAVEL ROUTE OF ITALUS")]
        function_lines = [ln.lstrip("- ").strip() for ln in section_lines(block, "BOOK FUNCTION")]

        books[number] = Book(
            number=number,
            title=title.group(1).strip() if title else f"Book {number}",
            years=years.group(1).strip() if years else "",
            guardians=guardians.group(1).strip() if guardians else "",
            stage=" ".join(stage_lines).strip(),
            anchors=anchor_lines,
            travel_route=route_lines,
            function=function_lines,
        )
    return books


def parse_backbone(text: str) -> List[Event]:
    events: List[Event] = []
    event_re = re.compile(
        r"(?m)^(\d{3})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$"
    )
    for m in event_re.finditer(text):
        events.append(
            Event(
                event_id=m.group(1).strip(),
                year=m.group(2).strip(),
                event=m.group(3).strip(),
                region=m.group(4).strip(),
                book=m.group(5).strip(),
                guardian=m.group(6).strip(),
            )
        )
    return events


def parse_scene_matrix(text: str) -> List[Scene]:
    scenes: List[Scene] = []
    scene_re = re.compile(
        r"(?m)^(S\d{3})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$"
    )
    for m in scene_re.finditer(text):
        scenes.append(
            Scene(
                scene_id=m.group(1).strip(),
                event_id=m.group(2).strip(),
                year=m.group(3).strip(),
                book=m.group(4).strip(),
                guardian=m.group(5).strip(),
                location=m.group(6).strip(),
                scene_type=m.group(7).strip(),
                historical_character=m.group(8).strip(),
                scene_seed=m.group(9).strip(),
            )
        )
    return scenes


# ---------------------------------------------------------
# Manifest-driven menu helpers
# ---------------------------------------------------------

def manifest_books_menu():
    """
    Display available books from books_manifest.json
    and return the active book records.
    """
    books = get_active_books()

    if not books:
        print("No books found in manifest.")
        return []

    print("\nAvailable Books (Manifest):")
    for idx, book in enumerate(books, start=1):
        print(f"{idx}. {book.get('title')} [{book.get('book_id')}]")

    return books


def manifest_chapters_menu(book_id: str):
    """
    Display chapters for the selected book from books_manifest.json
    and return the chapter records.
    """
    chapters = get_chapters_for_book(book_id)

    if not chapters:
        print("No chapters found for this book in manifest.")
        return []

    print(f"\nAvailable Chapters for {book_id} (Manifest):")
    for idx, chapter in enumerate(chapters, start=1):
        print(f"{idx}. {chapter.get('title')} [{chapter.get('chapter_id')}]")

    return chapters


def manifest_events_menu(book_id: str, chapter_id: str):
    """
    Display events for the selected chapter from events_manifest.json
    and return the event records.
    """
    events = get_events_for_chapter(book_id, chapter_id)

    if not events:
        print("No events found for this chapter in manifest.")
        return []

    print(f"\nAvailable Events for {chapter_id} (Manifest):")
    for idx, event in enumerate(events, start=1):
        print(f"{idx}. {event.get('event_name')} [{event.get('event_id')}]")

    return events


def manifest_scene_types_menu():
    """
    Display available scene types from scene_types_manifest.json
    and return the list.
    """
    scene_types = get_scene_types()

    if not scene_types:
        print("No scene types found in manifest.")
        return []

    print("\nAvailable Scene Types (Manifest):")
    for idx, scene_type in enumerate(scene_types, start=1):
        print(f"{idx}. {scene_type}")

    return scene_types


def manifest_request_defaults(event_id: str) -> dict:
    """
    Build default request fields from the selected manifest event.
    """
    defaults = build_request_defaults_from_event(event_id)

    if not defaults:
        print("No defaults found for selected event.")
        return {}

    return defaults


def book_label(num: int) -> str:
    return f"Book {num}"

def events_for_book(events: List[Event], num: int) -> List[Event]:
    return [e for e in events if e.book == book_label(num)]


def scenes_for_book(scenes: List[Scene], num: int) -> List[Scene]:
    return [s for s in scenes if s.book == book_label(num)]


def find_scene(scenes: List[Scene], scene_id: str) -> Optional[Scene]:
    scene_id = scene_id.strip()
    for s in scenes:
        if s.scene_id.lower() == scene_id.lower():
            return s
    return None


def find_event(events: List[Event], event_id: str) -> Optional[Event]:
    event_id = event_id.strip().zfill(3)
    for e in events:
        if e.event_id == event_id:
            return e
    return None


# ---------------------------------------------------------
# Frontend-safe controller/data helpers
# ---------------------------------------------------------

def get_manifest_books_data() -> list[dict]:
    """
    Return active books as raw data for controller/frontend use.
    """
    return get_active_books()


def get_manifest_chapters_data(book_id: str) -> list[dict]:
    """
    Return active chapters for a selected book as raw data.
    """
    return get_chapters_for_book(book_id)


def get_manifest_events_data(book_id: str, chapter_id: str) -> list[dict]:
    """
    Return active events for a selected book/chapter as raw data.
    """
    return get_events_for_chapter(book_id, chapter_id)


def get_manifest_scene_types_data() -> list[str]:
    """
    Return scene types as raw data.
    """
    return get_scene_types()


def get_manifest_event_defaults_data(event_id: str) -> dict:
    """
    Return event-derived request defaults as raw data.
    """
    return manifest_request_defaults(event_id)
    
    
def build_manifest_generation_request(
    book_id: str,
    chapter_id: str,
    event_id: str,
    scene_type: str,
    ai_provider: str | None = None,
) -> dict:
    """
    Build a frontend-safe generation request from manifest-driven selections.
    """
    defaults = manifest_request_defaults(event_id)

    request = defaults.copy()
    request["book_id"] = book_id
    request["chapter_id"] = chapter_id
    request["event_id"] = event_id
    request["scene_type"] = scene_type

    if ai_provider:
        request["ai_provider"] = ai_provider.strip().lower()

    return request


def get_controller_ai_provider_config() -> dict:
    """
    Controller-safe passthrough for frontend/HTML provider loading.
    """
    return get_ai_provider_config()


def run_controller_generation_request(request: dict) -> dict:
    """
    Controller-safe generation action for frontend/HTML use.
    """
    return generate_scene_payload(request)


def run_controller_save_request(
    request: dict,
    title: str,
    summary: str = "",
    status: str = "canon",
) -> dict:
    """
    Controller-safe save action for frontend/HTML use.
    """
    return save_accepted_scene_payload(
        request=request,
        title=title,
        summary=summary,
        status=status,
    )
    
def run_controller_save(
    request: dict,
    title: str,
    summary: str = "",
    status: str = "canon",
) -> dict:
    """
    Normalized controller save endpoint.

    This wraps the raw project_runner save payload and returns a UI-friendly
    response format expected by the future HTML interface.
    """

    result = run_controller_save_request(
        request=request,
        title=title,
        summary=summary,
        status=status,
    )

    ok = result.get("ok", False)
    data = result.get("data", {})
    ui_status = result.get("ui_status", {})
    errors = result.get("errors", [])

    return {
        "ok": ok,
        "scene_id": data.get("scene_id"),
        "title": data.get("title"),
        "status": data.get("status"),
        "book_id": data.get("book_id"),
        "chapter_id": data.get("chapter_id"),
        "event_id": data.get("event_id"),
        "backup_path": data.get("backup_path"),
        "save_status": ui_status.get("save_status"),
        "save_error": ui_status.get("save_error"),
        "errors": errors,
    }    


def get_controller_selection_context(
    book_id: str = "",
    chapter_id: str = "",
    event_id: str = "",
) -> dict:
    """
    Return frontend-ready dependent selection context.

    This is intended for incremental HTML UI refreshes after a user changes
    book, chapter, or event selections.
    """

    chapters = get_manifest_chapters_data(book_id) if book_id else []
    events = get_manifest_events_data(book_id, chapter_id) if book_id and chapter_id else []
    event_defaults = get_manifest_event_defaults_data(event_id) if event_id else {}

    return {
        "book_id": book_id,
        "chapter_id": chapter_id,
        "event_id": event_id,
        "chapters": chapters,
        "events": events,
        "event_defaults": event_defaults,
    }
    
    


def get_controller_generation_form_context(
    book_id: str = "",
    chapter_id: str = "",
    event_id: str = "",
) -> dict:
    """
    Return frontend-ready form context for the HTML authoring interface.

    This bundles the current manifest and provider data needed to populate
    the generation form without requiring the frontend to call multiple
    controller helpers one-by-one.
    """
    books = get_manifest_books_data()
    chapters = get_manifest_chapters_data(book_id) if book_id else []
    events = get_manifest_events_data(book_id, chapter_id) if book_id and chapter_id else []
    scene_types = get_manifest_scene_types_data()
    event_defaults = get_manifest_event_defaults_data(event_id) if event_id else {}
    provider_config = get_controller_ai_provider_config()

    return {
        "books": books,
        "chapters": chapters,
        "events": events,
        "scene_types": scene_types,
        "event_defaults": event_defaults,
        "provider_config": provider_config,
    }

def run_controller_generation(request: dict) -> dict:
    """
    Normalized controller generation endpoint.

    This wraps the raw project_runner payload and returns a UI-friendly
    response format expected by the future HTML interface.
    """

    result = run_controller_generation_request(request)

    ok = result.get("ok", False)
    data = result.get("data", {})
    meta = result.get("meta", {})
    ui_status = result.get("ui_status", {})
    warnings = result.get("warnings", [])
    errors = result.get("errors", [])

    generated_text = data.get("generated_text", data.get("response", ""))

    ui_state = {
        "provider": ui_status.get("provider", meta.get("ai_provider", "")),
        "provider_status": ui_status.get("provider_status", meta.get("ai_status", "unknown")),
        "provider_error": ui_status.get("provider_error"),
        "author_message": ui_status.get("author_message", meta.get("author_message")),
        "resume_status": ui_status.get("resume_status", meta.get("resume_status")),
        "prompt_mode": ui_status.get("prompt_mode", meta.get("prompt_mode")),
        "has_duplicate_warning": ui_status.get("has_duplicate_warning", False),
        "duplicate_scene_id": ui_status.get("duplicate_scene_id"),
    }

    return {
        "ok": ok,
        "generated_text": generated_text,
        "warnings": warnings,
        "errors": errors,
        "meta": meta,
        "ui_state": ui_state,
        "duplicate_candidate": data.get("duplicate_candidate"),
        "resolved_request": data.get("resolved_request"),
        "candidate_scene_count": data.get("candidate_scene_count", 0),
    }
    
def run_controller_generation_from_selection(
    book_id: str,
    chapter_id: str,
    event_id: str,
    scene_type: str,
    ai_provider: str | None = None,
) -> dict:
    """
    One-shot frontend generation helper.

    Builds a generation request from manifest selections and immediately
    runs the normalized controller generation flow.
    """
    request = build_manifest_generation_request(
        book_id=book_id,
        chapter_id=chapter_id,
        event_id=event_id,
        scene_type=scene_type,
        ai_provider=ai_provider,
    )

    return run_controller_generation(request)    
    

# ----------------------------
# Tone derivation engine
# ----------------------------
def classify_event_energy(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["black death", "plague", "famine", "earthquake", "pandemic", "flu", "disaster", "tsunami"]):
        return "catastrophe"
    if any(k in t for k in ["crusade", "war", "battle", "sack", "invasion", "march on rome", "front", "revolt", "revolution"]):
        return "conflict"
    if any(k in t for k in ["luther", "theses", "galileo", "university", "print", "printing", "enlightenment", "beccaria", "copernicus", "calendar reform"]):
        return "intellectual"
    if any(k in t for k in ["crowned", "kingdom", "treaty", "constitution", "republic", "unification", "capital", "maastricht", "eec", "euro"]):
        return "institutional"
    if any(k in t for k in ["climate", "chernobyl", "satellite", "mapping", "industrialization", "modernization", "conservation"]):
        return "environmental"
    return "historical"


def classify_guardian_archetype(guardian: str) -> str:
    g = guardian.lower()
    if "anselm" in g or "pietro" in g or "domenico" in g:
        return "scholarly"
    if "luca" in g or "elia" in g or "marco" in g or "simonetta" in g:
        return "foundational"
    if "amara" in g or "caterina" in g or "orsolina" in g:
        return "adaptive"
    if "giacomo" in g or "rosa" in g or "theodora" in g:
        return "endurance"
    if "emilio" in g or "agata" in g or "final guardian" in g:
        return "system-aware"
    return "observational"


def normalize_stage(stage: str) -> str:
    s = stage.lower()
    if "curiosity" in s:
        return "curiosity"
    if "observation" in s:
        return "observation"
    if "detachment" in s:
        return "detachment"
    if "weariness" in s:
        return "weariness"
    return "observation"


def derive_tone(event_text: str, stage_text: str, guardian: str) -> str:
    energy = classify_event_energy(event_text)
    stage = normalize_stage(stage_text)
    archetype = classify_guardian_archetype(guardian)

    table = {
        ("catastrophe", "curiosity"): "fear, confusion, and raw discovery",
        ("catastrophe", "observation"): "dread and witness-bearing",
        ("catastrophe", "detachment"): "moral exhaustion and cold observation",
        ("catastrophe", "weariness"): "endurance, grief, and long memory",

        ("conflict", "curiosity"): "danger and awakening",
        ("conflict", "observation"): "uneasy religious or political tension",
        ("conflict", "detachment"): "hard realism and strategic unease",
        ("conflict", "weariness"): "war fatigue and historical burden",

        ("intellectual", "curiosity"): "wonder and first uncertainty",
        ("intellectual", "observation"): "uneasy intellectual tension",
        ("intellectual", "detachment"): "intellectual danger and analytic distance",
        ("intellectual", "weariness"): "weary intelligence and institutional pressure",

        ("institutional", "curiosity"): "new order and unease",
        ("institutional", "observation"): "political tension and measured attention",
        ("institutional", "detachment"): "bureaucratic pressure and quiet suspicion",
        ("institutional", "weariness"): "institutional hardening and loss",

        ("environmental", "curiosity"): "natural unease and widening awareness",
        ("environmental", "observation"): "environmental warning and restraint",
        ("environmental", "detachment"): "cool awareness of systemic change",
        ("environmental", "weariness"): "ecological grief and late recognition",

        ("historical", "curiosity"): "quiet discovery and unease",
        ("historical", "observation"): "grounded historical realism",
        ("historical", "detachment"): "measured distance and historical tension",
        ("historical", "weariness"): "long-view melancholy and restraint",
    }

    base = table.get((energy, stage), "grounded historical realism")

    if archetype == "scholarly" and energy in {"intellectual", "institutional"}:
        return "uneasy intellectual tension"
    if archetype == "endurance" and energy in {"catastrophe", "conflict"}:
        return "endurance under pressure"
    if archetype == "foundational" and stage == "curiosity":
        return "quiet discovery and unease"
    if archetype == "system-aware" and energy in {"institutional", "environmental"}:
        return "system pressure and quiet alarm"

    return base


def build_intro_prompt(book: Book, tone: Optional[str], location: Optional[str], context: Optional[str]) -> str:
    location = location or (book.travel_route[0] if book.travel_route else "Derived from saga architecture map")
    context = context or (book.anchors[0] if book.anchors else "Derived from saga architecture map")
    tone = tone or derive_tone(context, book.stage, book.primary_guardian)
    return f"""Use ITALUS_BOOK_GENERATION_ENGINE.txt in INTRODUCTION / PROLOGUE MODE.

Book: {book.number}
Year: {book.first_year}
Guardian: {book.primary_guardian}
Location: {location}
Historical Context: {context}
Tone: {tone}

Generate the prologue only.
"""


def build_chapter_prompt(book: Book, event: Optional[Event], scene: Optional[Scene], chapter: int, tone: Optional[str]) -> str:
    if scene:
        tone = tone or derive_tone(scene.scene_seed + " " + scene.scene_type, book.stage, scene.guardian)
        return f"""Use ITALUS_BOOK_GENERATION_ENGINE.txt in CHAPTER MODE.

Book: {book.number}
Chapter: {chapter}
Scene ID: {scene.scene_id}
Event ID: {scene.event_id}
Year: {scene.year}
Guardian: {scene.guardian}
Location: {scene.location}
Tone: {tone}

Generate the chapter.
"""
    if event:
        tone = tone or derive_tone(event.event, book.stage, event.guardian)
        return f"""Use ITALUS_BOOK_GENERATION_ENGINE.txt in CHAPTER MODE.

Book: {book.number}
Chapter: {chapter}
Event ID: {event.event_id}
Year: {event.year}
Guardian: {event.guardian}
Location: {event.region}
Historical Context: {event.event}
Tone: {tone}

Generate the chapter.
"""
    raise ValueError("Chapter mode requires either an event or scene.")


def build_book_prompt(book: Book, major_event: Optional[Event], tone: Optional[str], minor_events: List[Event]) -> str:
    major = major_event.event if major_event else (book.anchors[0] if book.anchors else "Derived from saga architecture map")
    tone = tone or derive_tone(major, book.stage, book.primary_guardian)
    minor_text = ", ".join([f"{e.event_id} {e.event}" for e in minor_events[:4]]) if minor_events else "Derived from architecture/backbone"
    return f"""Use ITALUS_BOOK_GENERATION_ENGINE.txt in FULL BOOK MODE.

Book: {book.number}
Title: {book.title}
Years: {book.years}
Guardian: {book.guardians}
Major Event: {major}
Minor Events: {minor_text}
Tone: {tone}

Generate the full 10-chapter outline and required appendices.
"""


def load_data(root: Path):
    docs_dir = root / "docs"
    books = parse_architecture_map(read_text(docs_dir / ARCH_FILE))
    events = parse_backbone(read_text(docs_dir / BACKBONE_FILE))
    scenes = parse_scene_matrix(read_text(docs_dir / SCENE_MATRIX_FILE))
    return books, events, scenes


def print_books(books: Dict[int, Book]) -> None:
    print("\nAvailable Books")
    print("-" * 80)
    for num in sorted(books):
        b = books[num]
        print(f"{num:>2} | {b.title} | {b.years} | Guardian(s): {b.guardians}")
    print()


def print_events(events: List[Event], book_num: int) -> None:
    print(f"\nEvents for Book {book_num}")
    print("-" * 80)
    for e in events_for_book(events, book_num):
        print(f"{e.event_id} | {e.year} | {e.event} | {e.region} | {e.guardian}")
    print()


def print_scenes(scenes: List[Scene], book_num: int) -> None:
    print(f"\nScenes for Book {book_num}")
    print("-" * 80)
    for s in scenes_for_book(scenes, book_num):
        print(f"{s.scene_id} | Event {s.event_id} | {s.year} | {s.guardian} | {s.location} | {s.scene_type}")
    print()


def save_optional(prompt: str) -> None:
    choice = input("Save prompt to file? (y/N): ").strip().lower()
    if choice == "y":
        name = input("Enter output filename [generated_prompt.txt]: ").strip() or "generated_prompt.txt"
        Path(name).write_text(prompt, encoding="utf-8")
        print(f"Saved to {name}\n")


def yes_no(prompt: str, default_yes: bool = True) -> bool:
    suffix = " [Y/n]: " if default_yes else " [y/N]: "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return default_yes
    return ans in {"y", "yes"}


def interactive_menu(root: Path) -> int:
    try:
        books, events, scenes = load_data(root)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    while True:
        print("=" * 70)
        print("ITALUS PROJECT RUNNER")
        print("=" * 70)
        print("1. List books")
        print("2. List events for a book")
        print("3. List scenes for a book")
        print("4. Generate intro / prologue prompt")
        print("5. Generate chapter prompt from event")
        print("6. Generate chapter prompt from scene ID")
        print("7. Generate full book prompt")
        print("8. Manifest authoring flow (NEW)")
        print("0. Exit")

        choice = input("Select an option: ").strip()

        if choice == "0":
            print("Exiting.")
            return 0

        elif choice == "1":
            print_books(books)

        elif choice == "2":
            print_books(books)
            book_num = int(input("Enter book number: ").strip())
            print_events(events, book_num)

        elif choice == "3":
            print_books(books)
            book_num = int(input("Enter book number: ").strip())
            print_scenes(scenes, book_num)

        elif choice == "4":
            print_books(books)
            book_num = int(input("Enter book number: ").strip())
            book = books[book_num]
            auto_location = book.travel_route[0] if book.travel_route else "Derived from saga architecture map"
            auto_context = book.anchors[0] if book.anchors else "Derived from saga architecture map"
            auto_tone = derive_tone(auto_context, book.stage, book.primary_guardian)

            print("\nDerived defaults")
            print(f"Year: {book.first_year}")
            print(f"Guardian: {book.primary_guardian}")
            print(f"Location: {auto_location}")
            print(f"Historical Context: {auto_context}")
            print(f"Tone: {auto_tone}\n")

            if yes_no("Use derived defaults?", True):
                prompt = build_intro_prompt(book, auto_tone, auto_location, auto_context)
            else:
                tone = input(f"Enter tone [{auto_tone}]: ").strip() or auto_tone
                location = input(f"Override location? [{auto_location}]: ").strip() or auto_location
                context = input(f"Override historical context? [{auto_context}]: ").strip() or auto_context
                prompt = build_intro_prompt(book, tone, location, context)

            print("\n" + prompt)
            save_optional(prompt)

        elif choice == "5":
            print_books(books)
            book_num = int(input("Enter book number: ").strip())
            print_events(events, book_num)
            event_id = input("Enter Event ID (e.g. 038): ").strip()
            chapter = int(input("Enter chapter number: ").strip())
            event = find_event(events, event_id)
            if not event:
                print("Event not found.\n")
                continue
            auto_tone = derive_tone(event.event, books[book_num].stage, event.guardian)
            print(f"Derived tone: {auto_tone}")
            tone = auto_tone if yes_no("Use derived tone?", True) else (input(f"Enter tone [{auto_tone}]: ").strip() or auto_tone)
            prompt = build_chapter_prompt(books[book_num], event, None, chapter, tone)
            print("\n" + prompt)
            save_optional(prompt)

        elif choice == "6":
            print_books(books)
            book_num = int(input("Enter book number: ").strip())
            print_scenes(scenes, book_num)
            scene_id = input("Enter Scene ID (e.g. S051): ").strip()
            chapter = int(input("Enter chapter number: ").strip())
            scene = find_scene(scenes, scene_id)
            if not scene:
                print("Scene not found.\n")
                continue
            auto_tone = derive_tone(scene.scene_seed + " " + scene.scene_type, books[book_num].stage, scene.guardian)
            print(f"Derived tone: {auto_tone}")
            tone = auto_tone if yes_no("Use derived tone?", True) else (input(f"Enter tone [{auto_tone}]: ").strip() or auto_tone)
            prompt = build_chapter_prompt(books[book_num], None, scene, chapter, tone)
            print("\n" + prompt)
            save_optional(prompt)

        elif choice == "7":
            print_books(books)
            book_num = int(input("Enter book number: ").strip())
            print_events(events, book_num)
            event_id = input("Enter major Event ID [press Enter to auto-fill from architecture]: ").strip() or None
            major_event = find_event(events, event_id) if event_id else None
            auto_major = major_event.event if major_event else (books[book_num].anchors[0] if books[book_num].anchors else "Derived from architecture map")
            auto_tone = derive_tone(auto_major, books[book_num].stage, books[book_num].primary_guardian)
            print(f"Derived tone: {auto_tone}")
            tone = auto_tone if yes_no("Use derived tone?", True) else (input(f"Enter tone [{auto_tone}]: ").strip() or auto_tone)
            prompt = build_book_prompt(books[book_num], major_event, tone, events_for_book(events, book_num))
            print("\n" + prompt)
            save_optional(prompt)
            
        elif choice == "8":

            # -------------------------------
            # Manifest-driven authoring flow
            # -------------------------------

            books = manifest_books_menu()
            if not books:
                continue

            bidx = int(input("Select book number: ").strip()) - 1
            if bidx < 0 or bidx >= len(books):
                print("Invalid selection\n")
                continue

            book = books[bidx]
            book_id = book["book_id"]

            chapters = manifest_chapters_menu(book_id)
            if not chapters:
                continue

            cidx = int(input("Select chapter number: ").strip()) - 1
            if cidx < 0 or cidx >= len(chapters):
                print("Invalid selection\n")
                continue

            chapter = chapters[cidx]
            chapter_id = chapter["chapter_id"]

            events = manifest_events_menu(book_id, chapter_id)
            if not events:
                continue

            eidx = int(input("Select event number: ").strip()) - 1
            if eidx < 0 or eidx >= len(events):
                print("Invalid selection\n")
                continue

            event = events[eidx]

            scene_types = manifest_scene_types_menu()
            if not scene_types:
                continue

            sidx = int(input("Select scene type: ").strip()) - 1
            if sidx < 0 or sidx >= len(scene_types):
                print("Invalid selection\n")
                continue

            scene_type = scene_types[sidx]

            defaults = manifest_request_defaults(event["event_id"])

            print("\nGenerated request defaults\n")
            for k, v in defaults.items():
                print(f"{k}: {v}")

            print("\nSelected Scene Type:", scene_type)

            request = defaults.copy()
            request["scene_type"] = scene_type
            request["book_id"] = book_id
            request["chapter_id"] = chapter_id
            request["event_id"] = event["event_id"]

            provider_config = get_ai_provider_config()
            default_provider = provider_config.get("default_provider", "claude")
            providers = provider_config.get("providers", [])

            print("\nAvailable AI Providers\n")
            for provider in providers:
                status_text = "available" if provider["implemented"] else "not implemented"
                default_marker = " [default]" if provider["provider_id"] == default_provider else ""
                print(f"- {provider['provider_id']} ({provider['label']}) [{status_text}]{default_marker}")

            provider_override = input(
                f"AI provider override [press Enter for default: {default_provider}]: "
            ).strip().lower()
            
            if provider_override:
                request["ai_provider"] = provider_override

            print("\nSending request to project_runner...\n")

            generation_result = generate_scene_payload(request)

            payload_ok = generation_result.get("ok", False)
            data = generation_result.get("data", {})
            meta = generation_result.get("meta", {})
            ui_status = generation_result.get("ui_status", {})
            errors = generation_result.get("errors", [])

            generated_text = data.get("generated_text", data.get("response", ""))
            duplicate_candidate = data.get("duplicate_candidate")
            resolved_request = data.get("resolved_request", {})
            candidate_scene_count = data.get("candidate_scene_count", 0)

            ai_provider = ui_status.get("provider", meta.get("ai_provider", ""))
            ai_status = ui_status.get("provider_status", meta.get("ai_status", "unknown"))
            author_message = ui_status.get("author_message", meta.get("author_message"))
            resume_status = ui_status.get("resume_status", meta.get("resume_status"))
            prompt_mode = ui_status.get("prompt_mode", meta.get("prompt_mode"))

            ai_error = ui_status.get("provider_error")
            if ai_error is None and errors:
                ai_error = errors[0]

            if author_message:
                print("\n=== AUTHOR CONTEXT ===")
                print(author_message)

            if ui_status.get("has_duplicate_warning"):
                print("\n=== DUPLICATE WARNING ===")
                print(f"Possible duplicate scene: {ui_status.get('duplicate_scene_id', 'unknown')}")

            if ai_status != "ok":
                print("\n=== AI STATUS ===")
                print(f"Provider: {ai_provider}")
                print(f"Status: {ai_status}")
                if ai_error:
                    print(f"Error: {ai_error}")

            print("\nGenerated Output\n")
            print(generated_text)
            print()
            
            save_choice = input("Accept and save this scene? [y/N]: ").strip().lower()

            if save_choice in {"y", "yes"}:
                scene_title = input("Scene title: ").strip()
                if not scene_title:
                    scene_title = f"{request.get('scene_type', 'Scene').title()} - {request.get('event_name', 'Untitled Event')}"

                scene_summary = input("Optional summary [press Enter to auto-generate]: ").strip()

                save_result = save_accepted_scene_payload(
                    request=request,
                    title=scene_title,
                    summary=scene_summary,
                    status="canon",
                )

                save_ok = save_result.get("ok", False)
                save_data = save_result.get("data", {})
                save_ui_status = save_result.get("ui_status", {})
                save_errors = save_result.get("errors", [])

                if save_ok:
                    print("\n=== SAVE SUCCESS ===")
                    print(f"Scene ID: {save_data.get('scene_id', 'unknown')}")
                    print(f"Title: {save_data.get('title', 'unknown')}")
                    print(f"Backup: {save_data.get('backup_path', 'unknown')}")
                else:
                    print("\n=== SAVE FAILED ===")
                    print(f"Status: {save_ui_status.get('save_status', 'unknown')}")
                    if save_ui_status.get("save_error"):
                        print(f"Error: {save_ui_status.get('save_error')}")
                    elif save_errors:
                        print(f"Error: {save_errors[0]}")
                print()

        else:
            print("Invalid selection.\n")


def cli_mode(argv: List[str], root: Path) -> int:
    parser = argparse.ArgumentParser(description="ITALUS Project Runner")
    parser.add_argument("--root", help="Path to ITALUS_MASTER_FOLDER", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-books", help="List all books")

    p_events = sub.add_parser("list-events", help="List events for a specific book")
    p_events.add_argument("--book", type=int, required=True)

    p_scenes = sub.add_parser("list-scenes", help="List scenes for a specific book")
    p_scenes.add_argument("--book", type=int, required=True)

    p_prompt = sub.add_parser("make-prompt", help="Build a Claude-ready prompt")
    p_prompt.add_argument("--mode", choices=["intro", "chapter", "book"], required=True)
    p_prompt.add_argument("--book", type=int, required=True)
    p_prompt.add_argument("--tone", default=None)
    p_prompt.add_argument("--location", default=None)
    p_prompt.add_argument("--context", default=None)
    p_prompt.add_argument("--chapter", type=int, default=1)
    p_prompt.add_argument("--event-id", default=None)
    p_prompt.add_argument("--scene-id", default=None)
    p_prompt.add_argument("--out", default=None)

    args = parser.parse_args(argv)
    books, events, scenes = load_data(root)

    if args.command == "list-books":
        print_books(books)
        return 0
    if args.command == "list-events":
        print_events(events, args.book)
        return 0
    if args.command == "list-scenes":
        print_scenes(scenes, args.book)
        return 0
    if args.command == "make-prompt":
        if args.mode == "intro":
            prompt = build_intro_prompt(books[args.book], args.tone, args.location, args.context)
        elif args.mode == "chapter":
            event = find_event(events, args.event_id) if args.event_id else None
            scene = find_scene(scenes, args.scene_id) if args.scene_id else None
            if not event and not scene:
                print("Chapter mode requires --event-id or --scene-id", file=sys.stderr)
                return 1
            prompt = build_chapter_prompt(books[args.book], event, scene, args.chapter, args.tone)
        else:
            major_event = find_event(events, args.event_id) if args.event_id else None
            prompt = build_book_prompt(books[args.book], major_event, args.tone, events_for_book(events, args.book))

        print(prompt)
        if args.out:
            Path(args.out).write_text(prompt, encoding="utf-8")
            print(f"\n[Saved prompt to {args.out}]")
        return 0
    return 0


def main() -> int:
    root = Path.cwd().resolve()

    if len(sys.argv) == 1:
        return interactive_menu(root)

    try:
        return cli_mode(sys.argv[1:], root)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
