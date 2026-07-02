from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CANON_PACKS_DIR = PROJECT_ROOT / "canon_packs"
DOCS_DIR = PROJECT_ROOT / "docs"

CORE_PACK_PATH = CANON_PACKS_DIR / "ITALUS_KNOWLEDGE_PACK_CORE.txt"
GENERATION_PACK_PATH = CANON_PACKS_DIR / "ITALUS_KNOWLEDGE_PACK_GENERATION.txt"

ARCHITECTURE_MAP_PATH = DOCS_DIR / "italus_saga_architecture_map.txt"
BACKBONE_PATH = DOCS_DIR / "ITALUS_HISTORICAL_EVENT_BACKBONE.txt"
SCENE_MATRIX_PATH = DOCS_DIR / "ITALUS_SCENE_GENERATOR_MATRIX.txt"


@dataclass
class BookCanon:
    book_number: int
    book_id: str
    title: str = ""
    years: str = ""
    primary_guardians_raw: str = ""
    primary_guardians: List[str] = field(default_factory=list)
    guardian_continuity: str = ""
    italus_emotional_stage: str = ""

    # Transition-aware canon fields
    active_guardians: List[dict] = field(default_factory=list)
    transition_guardians: List[dict] = field(default_factory=list)
    handoff_target: str = ""
    book_stage: str = ""
    late_book_stage_trend: str = ""
    guardian_ranges: List[dict] = field(default_factory=list)

    # Compressed prompting context fields
    dominant_guardian_context: List[str] = field(default_factory=list)
    transition_guardian_context: List[str] = field(default_factory=list)
    late_book_stage_context: List[str] = field(default_factory=list)

    # Signal / resonance compressed canon fields
    signal_tier_label: str = ""
    signal_tier_years: str = ""
    signal_allowed_categories: List[str] = field(default_factory=list)
    signal_ceiling_summary: List[str] = field(default_factory=list)

    guardian_signal_phase_context: List[str] = field(default_factory=list)
    resonance_eligibility_summary: List[str] = field(default_factory=list)
    resonance_placement_rules: List[str] = field(default_factory=list)
    signal_density_arc: List[str] = field(default_factory=list)
    book_signal_progression_notes: List[str] = field(default_factory=list)
    
    # --- Book-specific resonance planning fields ---
    resonance_event_budget: int = 0
    resonance_distribution: List[str] = field(default_factory=list)
    resonance_guardian_eligibility: List[str] = field(default_factory=list)
    resonance_transition_constraints: List[str] = field(default_factory=list)

    historical_anchor_events: List[str] = field(default_factory=list)
    travel_route: List[str] = field(default_factory=list)
    book_function: List[str] = field(default_factory=list)

    backbone_rows: List[dict] = field(default_factory=list)
    scene_rows: List[dict] = field(default_factory=list)

    # Row separation for safer compressed canon prompting
    dominant_backbone_rows: List[dict] = field(default_factory=list)
    transition_backbone_rows: List[dict] = field(default_factory=list)
    carryover_backbone_rows: List[dict] = field(default_factory=list)

    dominant_scene_rows: List[dict] = field(default_factory=list)
    transition_scene_rows: List[dict] = field(default_factory=list)
    carryover_scene_rows: List[dict] = field(default_factory=list)

def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def normalize_book_id(book_number: int) -> str:
    return f"BOOK_{book_number:02d}"


def normalize_book_label_variants(book_number: int) -> set[str]:
    return {
        f"Book {book_number}",
        f"BOOK_{book_number}",
        f"BOOK_{book_number:02d}",
    }


def split_guardians(raw: str) -> List[str]:
    if not raw:
        return []
    parts = re.split(r",|/| and ", raw)
    return [p.strip() for p in parts if p.strip()]
    
def split_stage_transition(raw_stage: str) -> tuple[str, str]:
    """
    Split a stage string into:
    - book_stage
    - late_book_stage_trend

    Example:
    'Stage 3 — Detachment, shifting toward Stage 4'
    ->
    ('Stage 3 — Detachment', 'shifting toward Stage 4')
    """
    if not raw_stage:
        return "", ""

    lower_stage = raw_stage.lower()
    marker = "shifting toward"

    if marker in lower_stage:
        idx = lower_stage.index(marker)
        left = raw_stage[:idx].rstrip(" ,;:-")
        right = raw_stage[idx:].strip(" ,;:-")
        return left, right

    return raw_stage.strip(), ""


def infer_guardian_phase_labels(guardians: List[str], continuity: str) -> tuple[List[dict], List[dict], str, List[dict]]:
    """
    Infer conservative transition-aware guardian metadata from guardian continuity text.

    Returns:
    - active_guardians
    - transition_guardians
    - handoff_target
    - guardian_ranges
    """
    continuity_lower = (continuity or "").lower()
    active_guardians: List[dict] = []
    transition_guardians: List[dict] = []
    guardian_ranges: List[dict] = []
    handoff_target = ""

    if not guardians:
        return active_guardians, transition_guardians, handoff_target, guardian_ranges

    # Single guardian book
    if len(guardians) == 1:
        g = guardians[0]
        active_guardians.append(
            {"name": g, "role": "primary", "phase": "full_book"}
        )
        guardian_ranges.append(
            {"name": g, "range_type": "book_phase", "phase": "full_book"}
        )
        return active_guardians, transition_guardians, handoff_target, guardian_ranges

    # Multi-guardian conservative inference
    first_guardian = guardians[0]
    later_guardians = guardians[1:]

    # Default: first guardian owns early/mid, later guardians own late/transition
    active_guardians.append(
        {"name": first_guardian, "role": "primary", "phase": "early_to_mid"}
    )
    guardian_ranges.append(
        {"name": first_guardian, "range_type": "book_phase", "phase": "early_to_mid"}
    )

    for idx, guardian in enumerate(later_guardians):
        phase = "late"
        role = "transition"

        if "latter half" in continuity_lower:
            phase = "latter_half"
        elif "late portion" in continuity_lower or "late-century transition" in continuity_lower:
            phase = "late"
        elif "overlap" in continuity_lower:
            phase = "mid_to_late"

        active_guardians.append(
            {"name": guardian, "role": role, "phase": phase}
        )
        guardian_ranges.append(
            {"name": guardian, "range_type": "book_phase", "phase": phase}
        )

        transition_guardians.append(
            {
                "from": first_guardian if idx == 0 else later_guardians[idx - 1],
                "to": guardian,
                "timing": phase,
                "status": "handoff_in_progress",
            }
        )

    handoff_target = later_guardians[-1]

    

    return active_guardians, transition_guardians, handoff_target, guardian_ranges
    
def derive_compressed_prompting_context(book: BookCanon) -> None:
    """
    Build conservative, source-grounded context blocks for compressed canon.

    This enforces structure for prompting without inventing unsupported precision.
    """
    dominant_guardian_context: List[str] = []
    transition_guardian_context: List[str] = []
    late_book_stage_context: List[str] = []

    # Dominant guardian context
    if not book.active_guardians:
        dominant_guardian_context.append("No active guardian context available.")
    else:
        dominant = [g for g in book.active_guardians if g.get("role") == "primary"]
        if not dominant:
            dominant = book.active_guardians[:1]

        for g in dominant:
            dominant_guardian_context.append(
                f"{g['name']} is dominant in the {g['phase']} phase of {book.book_id}."
            )

    # Transition guardian context
    if book.transition_guardians:
        for g in book.transition_guardians:
            transition_guardian_context.append(
                f"Transition is allowed from {g['from']} to {g['to']} during the {g['timing']} portion of the book."
            )

    if book.handoff_target:
        transition_guardian_context.append(
            f"The handoff target for {book.book_id} is {book.handoff_target}."
        )

    if book.guardian_continuity:
        transition_guardian_context.append(
            f"Guardian continuity note: {book.guardian_continuity}"
        )

    if not transition_guardian_context:
        transition_guardian_context.append(
            "No guardian transition is defined for this book; treat guardian continuity as stable."
        )

    # Late-book stage context
    if book.book_stage:
        late_book_stage_context.append(
            f"Default stage context for this book: {book.book_stage}."
        )

    if book.late_book_stage_trend:
        late_book_stage_context.append(
            f"Late-book stage trend: {book.late_book_stage_trend}."
        )
        late_book_stage_context.append(
            "Apply the late-book stage trend only when generating later-book or transition-aware material."
        )
    else:
        late_book_stage_context.append(
            "No late-book stage shift is defined; keep stage treatment stable across the book unless scene canon requires otherwise."
        )

    book.dominant_guardian_context = dominant_guardian_context
    book.transition_guardian_context = transition_guardian_context
    book.late_book_stage_context = late_book_stage_context

    
def derive_signal_tier(book_number: int) -> tuple[str, str, List[str], List[str]]:
    if 1 <= book_number <= 2:
        return (
            "TIER 1 — TOUCH AND PRESSURE ERA",
            "Books 1–2",
            [
                "touch-contact pressure",
                "weight shift through contact",
                "presence/danger sensing only",
            ],
            [
                "No resin, no needle vocabulary, no soil chemistry, no root-network interpretation.",
                "No deliberate two-way communication.",
                "Resonance is heavily restricted and must not function as language or prophecy.",
            ],
        )

    if 3 <= book_number <= 5:
        return (
            "TIER 2 — RESIN AND NEEDLE ERA",
            "Books 3–5",
            [
                "touch-contact pressure",
                "resin expression",
                "needle movement",
                "limited pattern recognition",
            ],
            [
                "Signal literacy expands beyond touch but remains partial.",
                "No full chemistry/root-network fluency.",
                "Resonance remains constrained by guardian service duration and canon placement law.",
            ],
        )

    if 6 <= book_number <= 7:
        return (
            "TIER 3 — SOIL CHEMISTRY ERA",
            "Books 6–7",
            [
                "touch-contact pressure",
                "resin expression",
                "needle movement",
                "soil chemistry response",
                "root-network sensory awareness",
            ],
            [
                "Signal interpretation is advanced but still not limitless.",
                "Use full environmental sensing carefully and historically.",
                "Resonance is allowed only when guardian phase and book law both permit it.",
            ],
        )

    return (
        "TIER 4 — FULL VOCABULARY ERA",
        "Books 8–11",
        [
            "touch-contact pressure",
            "resin expression",
            "needle movement",
            "soil chemistry response",
            "root-network sensory awareness",
            "full signal lexicon access",
        ],
        [
            "Full signal vocabulary is available in this era.",
            "Resonance remains bounded by placement law and guardian eligibility.",
            "Signals still cannot become speech, prophecy, or unrestricted exposition.",
        ],
    )


def derive_signal_and_resonance_context(book: BookCanon) -> None:
    tier_label, tier_years, allowed_categories, ceiling_summary = derive_signal_tier(book.book_number)

    book.signal_tier_label = tier_label
    book.signal_tier_years = tier_years
    book.signal_allowed_categories = allowed_categories
    book.signal_ceiling_summary = ceiling_summary

    book.guardian_signal_phase_context = [
        "Guardian signal understanding should evolve gradually across the book."
    ]

    book.resonance_eligibility_summary = [
        "Resonance must remain rare and historically grounded."
    ]

    book.resonance_placement_rules = [
        "No more than three resonance events in a full book.",
        "Events should follow early / mid / late structure.",
        "Resonance cannot function as speech or prophecy."
    ]

    book.signal_density_arc = [
        "Opening chapters: sparse signals.",
        "Mid-book: signals increase with historical pressure.",
        "Late-book: escalation only if canon permits."
    ]

    book.book_signal_progression_notes = [
        "Signal literacy should evolve slowly across the saga."
    ]


def section_lines(block: str, heading: str) -> List[str]:
    pattern = re.compile(
        rf"{re.escape(heading)}\s*\n(.*?)(?=\n[A-Z][A-Z \-']+\n|\n=+\n|$)",
        re.DOTALL,
    )
    m = pattern.search(block)
    if not m:
        return []
    lines = [ln.strip() for ln in m.group(1).splitlines()]
    return [ln for ln in lines if ln]


def parse_architecture_map(text: str) -> Dict[int, BookCanon]:
    books: Dict[int, BookCanon] = {}

    matches = list(re.finditer(r"(?m)^BOOK\s+(\d+)\s*$", text))
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else text.find("SERIES STAGE MAP")
        end = end if end != -1 else len(text)
        block = text[start:end]

        number = int(match.group(1))
        book_id = normalize_book_id(number)

        title = re.search(r"(?m)^TITLE:\s*(.+)$", block)
        years = re.search(r"(?m)^YEARS:\s*(.+)$", block)
        guardians = re.search(r"(?m)^PRIMARY GUARDIAN[S]?:\s*(.+)$", block)
        continuity = re.search(r"(?m)^GUARDIAN CONTINUITY:\s*(.+)$", block)

        stage_lines = section_lines(block, "ITALUS EMOTIONAL STAGE")
        anchor_lines = [ln.lstrip("- ").strip() for ln in section_lines(block, "HISTORICAL ANCHOR EVENTS")]
        route_lines = [ln.lstrip("- ").strip() for ln in section_lines(block, "TRAVEL ROUTE OF ITALUS")]
        function_lines = [ln.lstrip("- ").strip() for ln in section_lines(block, "BOOK FUNCTION")]

        raw_guardians = guardians.group(1).strip() if guardians else ""

        parsed_guardians = split_guardians(raw_guardians)
        parsed_continuity = continuity.group(1).strip() if continuity else ""
        parsed_stage = " ".join(stage_lines).strip()

        book_stage, late_book_stage_trend = split_stage_transition(parsed_stage)
        active_guardians, transition_guardians, handoff_target, guardian_ranges = infer_guardian_phase_labels(
            parsed_guardians,
            parsed_continuity,
        )

        book = BookCanon(
            book_number=number,
            book_id=book_id,
            title=title.group(1).strip() if title else f"Book {number}",
            years=years.group(1).strip() if years else "",
            primary_guardians_raw=raw_guardians,
            primary_guardians=parsed_guardians,
            guardian_continuity=parsed_continuity,
            italus_emotional_stage=parsed_stage,

            active_guardians=active_guardians,
            transition_guardians=transition_guardians,
            handoff_target=handoff_target,
            book_stage=book_stage,
            late_book_stage_trend=late_book_stage_trend,
            guardian_ranges=guardian_ranges,

            historical_anchor_events=anchor_lines,
            travel_route=route_lines,
            book_function=function_lines,
        )

        derive_compressed_prompting_context(book)
        derive_signal_and_resonance_context(book)
        books[number] = book

    return books


def parse_backbone(text: str) -> List[dict]:
    rows: List[dict] = []
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


def parse_scene_matrix(text: str) -> List[dict]:
    rows: List[dict] = []
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


def attach_backbone_rows(books: Dict[int, BookCanon], backbone_rows: List[dict]) -> None:
    for book_number, book in books.items():
        labels = normalize_book_label_variants(book_number)
        book.backbone_rows = [row for row in backbone_rows if row.get("book_label") in labels]


def attach_scene_rows(books: Dict[int, BookCanon], scene_rows: List[dict]) -> None:
    for book_number, book in books.items():
        labels = normalize_book_label_variants(book_number)
        book.scene_rows = [row for row in scene_rows if row.get("book_label") in labels]
        
def get_dominant_guardian_names(book: BookCanon) -> List[str]:
    dominant_names = [g["name"] for g in book.active_guardians if g.get("role") == "primary"]
    if dominant_names:
        return dominant_names

    if book.primary_guardians:
        return [book.primary_guardians[0]]

    return []


def get_transition_guardian_names(book: BookCanon) -> List[str]:
    names = [g["name"] for g in book.active_guardians if g.get("role") == "transition"]

    for tg in book.transition_guardians:
        if tg.get("to"):
            names.append(tg["to"])

    deduped: List[str] = []
    for name in names:
        if name and name not in deduped:
            deduped.append(name)

    return deduped


def row_mentions_multiple_guardians(guardian_value: str) -> bool:
    if not guardian_value:
        return False
    lowered = guardian_value.lower()
    return "/" in guardian_value or "," in guardian_value or " and " in lowered


def classify_rows_for_book(book: BookCanon) -> None:
    """
    Split linked backbone rows and scene rows into:
    - dominant
    - transition
    - carryover

    This preserves Italus guardian terminology while making compressed canon
    safer for AI prompting.
    """
    dominant_names = set(get_dominant_guardian_names(book))
    transition_names = set(get_transition_guardian_names(book))

    def classify_row(row: dict) -> str:
        guardian_value = (row.get("guardian") or "").strip()

        # Explicit overlap / handoff rows are transition rows
        if row_mentions_multiple_guardians(guardian_value):
            return "transition"

        # Exact guardian match rules
        if guardian_value in dominant_names:
            return "dominant"

        if guardian_value in transition_names:
            return "transition"

        # Any other guardian in the same book pack is carryover context
        if guardian_value:
            return "carryover"

        return "carryover"

    dominant_backbone: List[dict] = []
    transition_backbone: List[dict] = []
    carryover_backbone: List[dict] = []

    for row in book.backbone_rows:
        kind = classify_row(row)
        if kind == "dominant":
            dominant_backbone.append(row)
        elif kind == "transition":
            transition_backbone.append(row)
        else:
            carryover_backbone.append(row)

    dominant_scene: List[dict] = []
    transition_scene: List[dict] = []
    carryover_scene: List[dict] = []

    for row in book.scene_rows:
        kind = classify_row(row)
        if kind == "dominant":
            dominant_scene.append(row)
        elif kind == "transition":
            transition_scene.append(row)
        else:
            carryover_scene.append(row)

    book.dominant_backbone_rows = dominant_backbone
    book.transition_backbone_rows = transition_backbone
    book.carryover_backbone_rows = carryover_backbone

    book.dominant_scene_rows = dominant_scene
    book.transition_scene_rows = transition_scene
    book.carryover_scene_rows = carryover_scene


def derive_resonance_plan_for_book(book: BookCanon) -> None:
    tier_label = (book.signal_tier_label or "").upper()
    continuity = (book.guardian_continuity or "").lower()
    stage_trend = (book.late_book_stage_trend or "").lower()

    # Default values
    book.resonance_event_budget = 1
    book.resonance_distribution = ["late"]
    book.resonance_guardian_eligibility = []
    book.resonance_transition_constraints = []

    # Book-specific resonance budgets
    if book.book_number == 1:
        book.resonance_event_budget = 1
        book.resonance_distribution = ["late"]

    elif book.book_number == 2:
        book.resonance_event_budget = 1
        book.resonance_distribution = ["late"]

    elif book.book_number in {3, 4, 5}:
        book.resonance_event_budget = 2
        book.resonance_distribution = ["mid", "late"]

    elif book.book_number in {6, 7}:
        book.resonance_event_budget = 3
        book.resonance_distribution = ["early", "mid", "late"]

    elif book.book_number in {8, 9, 10, 11}:
        book.resonance_event_budget = 3
        book.resonance_distribution = ["early", "mid", "late"]

    # Guardian eligibility
    eligible: List[str] = []

    for g in book.active_guardians:
        name = g.get("name") if isinstance(g, dict) else ""
        phase = g.get("phase") if isinstance(g, dict) else ""

        if not name:
            continue

        if book.book_number <= 2:
            if phase in {"full_book", "late"}:
                eligible.append(name)

        elif book.book_number <= 5:
            if phase in {"full_book", "early_to_mid", "late", "latter_half", "mid_to_late"}:
                eligible.append(name)

        else:
            eligible.append(name)

    # Deduplicate while preserving order
    deduped: List[str] = []
    for name in eligible:
        if name not in deduped:
            deduped.append(name)

    book.resonance_guardian_eligibility = deduped

    # Transition constraints
    if book.transition_guardians:
        book.resonance_transition_constraints.append(
            "Resonance during guardian transition must be weakened or partial."
        )
        book.resonance_transition_constraints.append(
            "Full resonance events should occur before or after the transition window."
        )

    if "ends in this book" in continuity:
        book.resonance_transition_constraints.append(
            "Do not cluster resonance at the terminal handoff; preserve emotional spacing."
        )

    if "shifting toward" in stage_trend:
        book.resonance_transition_constraints.append(
            "Late-book resonance may intensify only in alignment with the stage shift."
        )

    # Tier-specific clarifiers
    if "TIER 1" in tier_label:
        book.resonance_transition_constraints.append(
            "Tier 1 books must keep resonance sparse, non-linguistic, and late-weighted."
        )

    elif "TIER 2" in tier_label:
        book.resonance_transition_constraints.append(
            "Tier 2 books may deepen resonance, but not to full fluency."
        )

    elif "TIER 3" in tier_label:
        book.resonance_transition_constraints.append(
            "Tier 3 books may use full early/mid/late structure if historically justified."
        )

    elif "TIER 4" in tier_label:
        book.resonance_transition_constraints.append(
            "Tier 4 books may use the fullest resonance range, but still never exceed three events."
        )

def build_core_summary(book: BookCanon) -> str:
    active_guardian_names = ", ".join(g["name"] for g in book.active_guardians) if book.active_guardians else "- none"
    transition_pairs = (
        ", ".join(f"{g['from']}→{g['to']} ({g['timing']})" for g in book.transition_guardians)
        if book.transition_guardians else "- none"
    )
    guardian_ranges = (
        ", ".join(f"{g['name']} [{g['phase']}]" for g in book.guardian_ranges)
        if book.guardian_ranges else "- none"
    )

    lines = [
        f"Book ID: {book.book_id}",
        f"Title: {book.title}",
        f"Years: {book.years}",
        f"Primary Guardians: {', '.join(book.primary_guardians) if book.primary_guardians else '- none'}",
        f"Active Guardians: {active_guardian_names}",
        f"Transition Guardians: {transition_pairs}",
        f"Handoff Target: {book.handoff_target or '- none'}",
        f"Guardian Ranges: {guardian_ranges}",
        f"Guardian Continuity: {book.guardian_continuity or '- none'}",
        f"Book Stage: {book.book_stage or '- none'}",
        f"Late Book Stage Trend: {book.late_book_stage_trend or '- none'}",
        f"Italus Emotional Stage: {book.italus_emotional_stage or '- none'}",
        f"Dominant Guardian Context Count: {len(book.dominant_guardian_context)}",
        f"Transition Guardian Context Count: {len(book.transition_guardian_context)}",
        f"Late Book Stage Context Count: {len(book.late_book_stage_context)}",
        f"Signal Tier: {book.signal_tier_label or '- none'}",
        f"Signal Allowed Category Count: {len(book.signal_allowed_categories)}",
        f"Signal Ceiling Summary Count: {len(book.signal_ceiling_summary)}",
        f"Guardian Signal Phase Context Count: {len(book.guardian_signal_phase_context)}",
        f"Resonance Eligibility Summary Count: {len(book.resonance_eligibility_summary)}",
        f"Resonance Placement Rule Count: {len(book.resonance_placement_rules)}",
        f"Signal Density Arc Count: {len(book.signal_density_arc)}",
        f"Book Signal Progression Note Count: {len(book.book_signal_progression_notes)}",
        f"Resonance Event Budget: {book.resonance_event_budget}",
        f"Resonance Distribution Count: {len(book.resonance_distribution)}",
        f"Resonance Guardian Eligibility Count: {len(book.resonance_guardian_eligibility)}",
        f"Resonance Transition Constraint Count: {len(book.resonance_transition_constraints)}",
        f"Dominant Backbone Row Count: {len(book.dominant_backbone_rows)}",
        f"Transition Backbone Row Count: {len(book.transition_backbone_rows)}",
        f"Carryover Backbone Row Count: {len(book.carryover_backbone_rows)}",
        f"Dominant Scene Row Count: {len(book.dominant_scene_rows)}",
        f"Transition Scene Row Count: {len(book.transition_scene_rows)}",
        f"Carryover Scene Row Count: {len(book.carryover_scene_rows)}",
    ]
    return "\n".join(lines)


def build_generation_summary(book: BookCanon) -> str:
    scene_types = sorted({row["scene_type"] for row in book.scene_rows if row.get("scene_type")})
    lines = [
        f"Book ID: {book.book_id}",
        f"Historical Anchor Count: {len(book.historical_anchor_events)}",
        f"Backbone Event Count: {len(book.backbone_rows)}",
        f"Scene Matrix Entry Count: {len(book.scene_rows)}",
        f"Scene Types: {', '.join(scene_types) if scene_types else '- none'}",
    ]
    return "\n".join(lines)


def format_backbone_rows(rows: List[dict]) -> str:
    if not rows:
        return "- none"
    return "\n".join(
        f"- {row['event_id']} | {row['year']} | {row['event_name']} | {row['region']} | {row['guardian']}"
        for row in rows
    )


def format_scene_rows(rows: List[dict]) -> str:
    if not rows:
        return "- none"
    return "\n".join(
        f"- {row['scene_id']} | Event {row['event_id']} | {row['year']} | "
        f"{row['guardian']} | {row['location']} | {row['scene_type']} | "
        f"{row['historical_character']} | {row['scene_seed']}"
        for row in rows
    )


def format_list_block(items: List[str]) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {item}" for item in items)


def build_book_pack_text(book: BookCanon, core_text: str, generation_text: str) -> str:
    """
    Phase 2 conservative book canon pack.

    This is a structured compressed pack, not a full semantic extraction yet.
    It provides book-specific canon fields plus source-linked summaries that
    project_runner/prompt_builder can load immediately.
    """

    core_summary = build_core_summary(book)
    generation_summary = build_generation_summary(book)

    content = f"""ITALUS KNOWLEDGE PACK — {book.book_id}

PURPOSE
This file is the book-specific canon pack for {book.book_id}.
It is generated by canon_bootstrap_book_builder.py from the master canon sources.

BOOK ID
{book.book_id}

TITLE
{book.title or "- none"}

YEARS
{book.years or "- none"}

PRIMARY GUARDIANS
{", ".join(book.primary_guardians) if book.primary_guardians else "- none"}

ACTIVE GUARDIANS
{format_list_block([f"{g['name']} | role={g['role']} | phase={g['phase']}" for g in book.active_guardians])}

TRANSITION GUARDIANS
{format_list_block([f"{g['from']} -> {g['to']} | timing={g['timing']} | status={g['status']}" for g in book.transition_guardians])}

HANDOFF TARGET
{book.handoff_target or "- none"}

GUARDIAN RANGES
{format_list_block([f"{g['name']} | {g['range_type']} | {g['phase']}" for g in book.guardian_ranges])}

GUARDIAN CONTINUITY
{book.guardian_continuity or "- none"}

BOOK STAGE
{book.book_stage or "- none"}

LATE BOOK STAGE TREND
{book.late_book_stage_trend or "- none"}

ITALUS EMOTIONAL STAGE
{book.italus_emotional_stage or "- none"}

DOMINANT GUARDIAN CONTEXT
{format_list_block(book.dominant_guardian_context)}

TRANSITION GUARDIAN CONTEXT
{format_list_block(book.transition_guardian_context)}

LATE BOOK STAGE CONTEXT
{format_list_block(book.late_book_stage_context)}

SIGNAL TIER
{book.signal_tier_label or "- none"}

SIGNAL TIER RANGE
{book.signal_tier_years or "- none"}

ALLOWED SIGNAL CATEGORIES
{format_list_block(book.signal_allowed_categories)}

SIGNAL CEILING SUMMARY
{format_list_block(book.signal_ceiling_summary)}

GUARDIAN SIGNAL PHASE CONTEXT
{format_list_block(book.guardian_signal_phase_context)}

RESONANCE ELIGIBILITY SUMMARY
{format_list_block(book.resonance_eligibility_summary)}

RESONANCE PLACEMENT RULES
{format_list_block(book.resonance_placement_rules)}

WITHIN-BOOK SIGNAL DENSITY ARC
{format_list_block(book.signal_density_arc)}

BOOK SIGNAL PROGRESSION NOTES
{format_list_block(book.book_signal_progression_notes)}

BOOK RESONANCE PLAN

RESONANCE EVENT BUDGET
{book.resonance_event_budget}

RESONANCE DISTRIBUTION
{format_list_block(book.resonance_distribution)}

RESONANCE GUARDIAN ELIGIBILITY
{format_list_block(book.resonance_guardian_eligibility)}

RESONANCE TRANSITION CONSTRAINTS
{format_list_block(book.resonance_transition_constraints)}

HISTORICAL ANCHOR EVENTS
{format_list_block(book.historical_anchor_events)}

TRAVEL ROUTE OF ITALUS
{format_list_block(book.travel_route)}

BOOK FUNCTION
{format_list_block(book.book_function)}

BACKBONE EVENTS LINKED TO THIS BOOK
{format_backbone_rows(book.backbone_rows)}

DOMINANT GUARDIAN BACKBONE ROWS
{format_backbone_rows(book.dominant_backbone_rows)}

TRANSITION BACKBONE ROWS
{format_backbone_rows(book.transition_backbone_rows)}

CARRYOVER BACKBONE ROWS
{format_backbone_rows(book.carryover_backbone_rows)}

SCENE MATRIX ENTRIES LINKED TO THIS BOOK
{format_scene_rows(book.scene_rows)}

DOMINANT GUARDIAN SCENE ROWS
{format_scene_rows(book.dominant_scene_rows)}

TRANSITION SCENE ROWS
{format_scene_rows(book.transition_scene_rows)}

CARRYOVER SCENE ROWS
{format_scene_rows(book.carryover_scene_rows)}

CORE PACK BOOK SUMMARY
{core_summary}

GENERATION PACK BOOK SUMMARY
{generation_summary}

SOURCE FILES
- {ARCHITECTURE_MAP_PATH.name}
- {BACKBONE_PATH.name}
- {SCENE_MATRIX_PATH.name}
- {CORE_PACK_PATH.name}
- {GENERATION_PACK_PATH.name}

CANON NOTE
This is a compressed book-specific pack for engine use in Phase 2.
It does not replace the master core pack or generation pack.
If this file conflicts with master canon, master canon wins.
"""
    return content.strip() + "\n"


def get_book_pack_output_path(book_number: int) -> Path:
    return CANON_PACKS_DIR / f"ITALUS_KNOWLEDGE_PACK_BOOK_{book_number:02d}.txt"


def build_book_packs() -> Dict[int, str]:
    architecture_text = read_text(ARCHITECTURE_MAP_PATH)
    backbone_text = read_text(BACKBONE_PATH)
    scene_matrix_text = read_text(SCENE_MATRIX_PATH)
    core_text = read_text(CORE_PACK_PATH)
    generation_text = read_text(GENERATION_PACK_PATH)

    books = parse_architecture_map(architecture_text)
    if not books:
        raise RuntimeError("No books parsed from architecture map.")

    backbone_rows = parse_backbone(backbone_text)
    scene_rows = parse_scene_matrix(scene_matrix_text)

    attach_backbone_rows(books, backbone_rows)
    attach_scene_rows(books, scene_rows)

    for _, book in sorted(books.items()):
        classify_rows_for_book(book)
        derive_resonance_plan_for_book(book)


    outputs: Dict[int, str] = {}
    for book_number, book in sorted(books.items()):
        if not book.backbone_rows and not book.scene_rows:
            print(f"WARNING: {book.book_id} has no linked canon rows.")

        outputs[book_number] = build_book_pack_text(book, core_text, generation_text)

    return outputs


def write_book_packs(outputs: Dict[int, str]) -> List[Path]:
    written_paths: List[Path] = []
    CANON_PACKS_DIR.mkdir(parents=True, exist_ok=True)

    for book_number, content in sorted(outputs.items()):
        path = get_book_pack_output_path(book_number)
        write_text(path, content)
        written_paths.append(path)

    return written_paths


def build_and_write_book_packs() -> List[Path]:
    outputs = build_book_packs()
    return write_book_packs(outputs)


def main() -> int:
    written_paths = build_and_write_book_packs()

    print("Book canon pack generation complete.\n")
    print(f"Output directory: {CANON_PACKS_DIR}\n")
    print("Generated files:")
    for path in written_paths:
        print(f"- {path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())