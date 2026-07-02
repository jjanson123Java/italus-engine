from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
CANON_PACKS_DIR = PROJECT_ROOT / "canon_packs"

ARCH_PATH = DOCS_DIR / "italus_saga_architecture_map.txt"
BACKBONE_PATH = DOCS_DIR / "ITALUS_HISTORICAL_EVENT_BACKBONE.txt"
SCENE_MATRIX_PATH = DOCS_DIR / "ITALUS_SCENE_GENERATOR_MATRIX.txt"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def section_lines(block: str, heading: str) -> list[str]:
    pattern = re.compile(
        rf"{re.escape(heading)}\s*\n(.*?)(?=\n[A-Z][A-Z \-']+\n|\n=+\n|$)",
        re.DOTALL,
    )
    m = pattern.search(block)
    if not m:
        return []
    lines = [ln.strip() for ln in m.group(1).splitlines()]
    return [ln for ln in lines if ln]


def parse_architecture_books(text: str) -> dict[int, dict]:
    books: dict[int, dict] = {}
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
        continuity = re.search(r"(?m)^GUARDIAN CONTINUITY:\s*(.+)$", block)

        stage = " ".join(section_lines(block, "ITALUS EMOTIONAL STAGE")).strip()
        anchors = [ln.lstrip("- ").strip() for ln in section_lines(block, "HISTORICAL ANCHOR EVENTS")]
        route = [ln.lstrip("- ").strip() for ln in section_lines(block, "TRAVEL ROUTE OF ITALUS")]
        function = [ln.lstrip("- ").strip() for ln in section_lines(block, "BOOK FUNCTION")]

        books[number] = {
            "title": title.group(1).strip() if title else "",
            "years": years.group(1).strip() if years else "",
            "guardians": guardians.group(1).strip() if guardians else "",
            "continuity": continuity.group(1).strip() if continuity else "",
            "stage": stage,
            "anchors": anchors,
            "route": route,
            "function": function,
        }
    return books

def normalize_book_label_variants(book_number: int) -> set[str]:
    return {
        f"Book {book_number}",
        f"BOOK_{book_number}",
        f"BOOK_{book_number:02d}",
    }


def split_guardians(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r",|/| and ", raw)
    return [p.strip() for p in parts if p.strip()]


def parse_backbone_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    event_re = re.compile(
        r"(?m)^(\d{3})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$"
    )

    for m in event_re.finditer(text):
        rows.append(
            {
                "event_id": m.group(1).strip(),
                "year": m.group(2).strip(),
                "event_name": m.group(3).strip(),
                "region": m.group(4).strip(),
                "book_label": m.group(5).strip(),
                "guardian": m.group(6).strip(),
            }
        )

    return rows


def parse_scene_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    scene_re = re.compile(
        r"(?m)^(S\d{3})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$"
    )

    for m in scene_re.finditer(text):
        rows.append(
            {
                "scene_id": m.group(1).strip(),
                "event_id": m.group(2).strip(),
                "year": m.group(3).strip(),
                "book_label": m.group(4).strip(),
                "guardian": m.group(5).strip(),
                "location": m.group(6).strip(),
                "scene_type": m.group(7).strip(),
                "historical_character": m.group(8).strip(),
                "scene_seed": m.group(9).strip(),
            }
        )

    return rows


def expected_signal_tier(book_number: int) -> str:
    if 1 <= book_number <= 2:
        return "TIER 1"
    if 3 <= book_number <= 5:
        return "TIER 2"
    if 6 <= book_number <= 7:
        return "TIER 3"
    return "TIER 4"

def expected_resonance_budget(book_number: int) -> int:
    if book_number in {1, 2}:
        return 1
    if book_number in {3, 4, 5}:
        return 2
    return 3


def expected_resonance_distribution(book_number: int) -> list[str]:
    if book_number in {1, 2}:
        return ["late"]
    if book_number in {3, 4, 5}:
        return ["mid", "late"]
    return ["early", "mid", "late"]

def extract_section_block(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"{re.escape(heading)}\s*\n(.*?)(?=\n[A-Z][A-Z \-']+\n|\n=+\n|$)",
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        return ""
    return m.group(1).strip()


def book_pack_path(book_number: int) -> Path:
    return CANON_PACKS_DIR / f"ITALUS_KNOWLEDGE_PACK_BOOK_{book_number:02d}.txt"


def assert_contains(label: str, haystack: str, needle: str, errors: list[str]) -> None:
    if needle and needle not in haystack:
        errors.append(f"{label}: missing expected text -> {needle}")

def verify_required_pack_sections(text: str, errors: list[str]) -> None:
    required_sections = [
        "BACKBONE EVENTS LINKED TO THIS BOOK",
        "SCENE MATRIX ENTRIES LINKED TO THIS BOOK",
        "SIGNAL TIER",
        "SIGNAL TIER RANGE",
        "ALLOWED SIGNAL CATEGORIES",
        "SIGNAL CEILING SUMMARY",
        "GUARDIAN SIGNAL PHASE CONTEXT",
        "RESONANCE ELIGIBILITY SUMMARY",
        "RESONANCE PLACEMENT RULES",
        "WITHIN-BOOK SIGNAL DENSITY ARC",
        "BOOK SIGNAL PROGRESSION NOTES",
        "BOOK RESONANCE PLAN",
        "RESONANCE EVENT BUDGET",
        "RESONANCE DISTRIBUTION",
        "RESONANCE GUARDIAN ELIGIBILITY",
        "RESONANCE TRANSITION CONSTRAINTS",
    ]

    for section in required_sections:
        if section not in text:
            errors.append(f"missing section: {section}")

def verify_pack_signal_tier(book_number: int, text: str, errors: list[str]) -> None:
    expected = expected_signal_tier(book_number)
    block = extract_section_block(text, "SIGNAL TIER")
    if not block:
        errors.append("missing SIGNAL TIER content")
        return

    if expected not in block:
        errors.append(f"signal tier mismatch: expected {expected}")
        


def verify_pack_resonance_budget(book_number: int, text: str, errors: list[str]) -> None:
    expected = str(expected_resonance_budget(book_number))
    block = extract_section_block(text, "RESONANCE EVENT BUDGET")
    if not block:
        errors.append("missing RESONANCE EVENT BUDGET content")
        return

    if expected not in block:
        errors.append(f"resonance event budget mismatch: expected {expected}")


def verify_pack_resonance_distribution(book_number: int, text: str, errors: list[str]) -> None:
    expected_items = expected_resonance_distribution(book_number)
    block = extract_section_block(text, "RESONANCE DISTRIBUTION")
    if not block:
        errors.append("missing RESONANCE DISTRIBUTION content")
        return

    for item in expected_items:
        if item not in block:
            errors.append(f"resonance distribution mismatch: missing {item}")


def verify_pack_resonance_guardian_eligibility(expected: dict, text: str, errors: list[str]) -> None:
    block = extract_section_block(text, "RESONANCE GUARDIAN ELIGIBILITY")
    if not block:
        errors.append("missing RESONANCE GUARDIAN ELIGIBILITY content")
        return

    expected_guardians = split_guardians(expected["guardians"])
    if expected_guardians and block.strip() == "- none":
        errors.append("resonance guardian eligibility is empty")

    found_any = False
    for guardian in expected_guardians:
        if guardian in block:
            found_any = True
            break

    if expected_guardians and not found_any:
        errors.append("resonance guardian eligibility missing expected guardian names")


def verify_pack_resonance_transition_constraints(expected: dict, text: str, errors: list[str]) -> None:
    block = extract_section_block(text, "RESONANCE TRANSITION CONSTRAINTS")
    if not block:
        errors.append("missing RESONANCE TRANSITION CONSTRAINTS content")
        return

    continuity = (expected["continuity"] or "").lower()

    if "transition" in continuity or "latter half" in continuity or "late portion" in continuity or "ends in this book" in continuity:
        if block.strip() == "- none":
            errors.append("resonance transition constraints missing for transition-aware book")


def verify_pack_backbone_alignment(book_number: int, text: str, backbone_rows: list[dict], errors: list[str]) -> None:
    labels = normalize_book_label_variants(book_number)
    expected_rows = [row for row in backbone_rows if row.get("book_label") in labels]

    block = extract_section_block(text, "BACKBONE EVENTS LINKED TO THIS BOOK")
    if expected_rows and not block:
        errors.append("missing backbone rows block")
        return

    for row in expected_rows:
        needle = f"{row['event_id']} | {row['year']} | {row['event_name']} | {row['region']} | {row['guardian']}"
        if needle not in block:
            errors.append(f"missing backbone row: {row['event_id']}")


def verify_pack_scene_alignment(book_number: int, text: str, scene_rows: list[dict], errors: list[str]) -> None:
    labels = normalize_book_label_variants(book_number)
    expected_rows = [row for row in scene_rows if row.get("book_label") in labels]

    block = extract_section_block(text, "SCENE MATRIX ENTRIES LINKED TO THIS BOOK")
    if expected_rows and not block:
        errors.append("missing scene rows block")
        return

    for row in expected_rows:
        needle = (
            f"{row['scene_id']} | Event {row['event_id']} | {row['year']} | "
            f"{row['guardian']} | {row['location']} | {row['scene_type']} | "
            f"{row['historical_character']} | {row['scene_seed']}"
        )
        if needle not in block:
            errors.append(f"missing scene row: {row['scene_id']}")


def verify_pack_guardian_alignment(
    book_number: int,
    expected: dict,
    text: str,
    scene_rows: list[dict],
    errors: list[str],
) -> None:
    labels = normalize_book_label_variants(book_number)
    allowed_guardians = set(split_guardians(expected["guardians"]))
    book_scene_rows = [row for row in scene_rows if row.get("book_label") in labels]

    dominant_block = extract_section_block(text, "DOMINANT GUARDIAN SCENE ROWS")
    transition_block = extract_section_block(text, "TRANSITION SCENE ROWS")
    carryover_block = extract_section_block(text, "CARRYOVER SCENE ROWS")

    for row in book_scene_rows:
        scene_id = row["scene_id"]
        scene_guardians = split_guardians(row.get("guardian", ""))

        in_dominant = scene_id in dominant_block
        in_transition = scene_id in transition_block
        in_carryover = scene_id in carryover_block

        # Only dominant rows must be restricted to the book's architecture guardian set.
        if in_dominant:
            for guardian in scene_guardians:
                if guardian and guardian not in allowed_guardians:
                    errors.append(
                        f"dominant scene guardian not in architecture guardians: {scene_id} -> {guardian}"
                    )

        # Transition and carryover rows are allowed to contain predecessor/successor guardians.
        elif in_transition or in_carryover:
            continue

        # If the row is in the pack but not classified into one of the row buckets, flag it.
        else:
            errors.append(f"scene row not found in classified scene sections: {scene_id}")

def verify_cross_source_coverage(backbone_rows: list[dict], scene_rows: list[dict]) -> list[str]:
    errors: list[str] = []

    backbone_event_ids = {row["event_id"] for row in backbone_rows}
    scene_event_ids = {row["event_id"] for row in scene_rows}

    for event_id in sorted(backbone_event_ids):
        if event_id not in scene_event_ids:
            errors.append(f"backbone event without scene coverage: {event_id}")

    for row in scene_rows:
        if row["event_id"] not in backbone_event_ids:
            errors.append(f"scene references unknown event: {row['scene_id']} -> {row['event_id']}")

    return errors


def verify_book_pack(
    book_number: int,
    expected: dict,
    backbone_rows: list[dict],
    scene_rows: list[dict],
) -> list[str]:
    errors: list[str] = []
    path = book_pack_path(book_number)

    if not path.exists():
        return [f"missing file: {path.name}"]

    text = read_text(path)

    assert_contains("TITLE", text, expected["title"], errors)
    assert_contains("YEARS", text, expected["years"], errors)
    assert_contains("GUARDIANS", text, expected["guardians"], errors)
    assert_contains("GUARDIAN CONTINUITY", text, expected["continuity"], errors)
    assert_contains("ITALUS EMOTIONAL STAGE", text, expected["stage"], errors)

    for item in expected["anchors"]:
        assert_contains("ANCHOR", text, item, errors)

    for item in expected["route"]:
        assert_contains("TRAVEL ROUTE", text, item, errors)

    for item in expected["function"]:
        assert_contains("BOOK FUNCTION", text, item, errors)

    verify_required_pack_sections(text, errors)
    verify_pack_signal_tier(book_number, text, errors)
    verify_pack_resonance_budget(book_number, text, errors)
    verify_pack_resonance_distribution(book_number, text, errors)
    verify_pack_resonance_guardian_eligibility(expected, text, errors)
    verify_pack_resonance_transition_constraints(expected, text, errors)
    verify_pack_backbone_alignment(book_number, text, backbone_rows, errors)
    verify_pack_scene_alignment(book_number, text, scene_rows, errors)
    verify_pack_guardian_alignment(book_number, expected, text, scene_rows, errors)

    return errors


def main() -> int:
    arch_text = read_text(ARCH_PATH)
    backbone_text = read_text(BACKBONE_PATH)
    scene_text = read_text(SCENE_MATRIX_PATH)

    books = parse_architecture_books(arch_text)
    backbone_rows = parse_backbone_rows(backbone_text)
    scene_rows = parse_scene_rows(scene_text)

    total_errors = 0

    print("Verifying generated book canon packs...\n")
    print("Checks: architecture fields, signal tiers, resonance plan, backbone rows, scene rows, guardian alignment.\n")
    
    for book_number in sorted(books):
        errors = verify_book_pack(
            book_number,
            books[book_number],
            backbone_rows,
            scene_rows,
        )
        if errors:
            total_errors += len(errors)
            print(f"BOOK_{book_number:02d}: FAIL")
            for err in errors:
                print(f"  - {err}")
        else:
            print(f"BOOK_{book_number:02d}: PASS")

    cross_source_errors = verify_cross_source_coverage(backbone_rows, scene_rows)

    print()
    if cross_source_errors:
        total_errors += len(cross_source_errors)
        print("Cross-source continuity: FAIL")
        for err in cross_source_errors:
            print(f"  - {err}")
    else:
        print("Cross-source continuity: PASS")

    print()
    if total_errors:
        print(f"Verification finished with {total_errors} issue(s).")
        return 1

    print("All generated book canon packs passed continuity validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())