from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class ResonanceFinding:
    paragraph_index: int
    excerpt: str
    score: int


@dataclass
class ResonanceValidationResult:
    is_valid: bool
    resonance_count: int
    max_allowed: int = 3
    findings: list[ResonanceFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def normalize(value: str) -> str:
    return value.strip().lower()


def tones_similar(a: str, b: str) -> bool:
    a = normalize(a)
    b = normalize(b)
    if a == b:
        return True
    near_pairs = {
        ("intellectual tension", "intellectual danger"),
        ("uneasy intellectual tension", "intellectual tension"),
        ("intellectual aftermath", "travel reflection")
    }
    return (a, b) in near_pairs or (b, a) in near_pairs

EXPLICIT_RESONANCE_MARKERS = [
    "MEMORY RESONANCE EVENT",
    "[MEMORY_RESONANCE]",
    "[[RESONANCE_START]]",
    "[[RESONANCE_END]]",
]

RESONANCE_MEMORY_WORDS = {
    "memory",
    "memories",
    "remember",
    "remembered",
    "remembering",
    "echo",
    "echoes",
    "past",
    "what had been",
    "ancestral",
    "centuries",
    "century",
}

RESONANCE_SIGNAL_WORDS = {
    "resonance",
    "resonant",
    "signal",
    "signals",
    "pulse",
    "pulses",
    "pressure",
    "weight",
    "touch",
    "resin",
    "needle",
    "root",
    "roots",
    "soil",
    "sap",
    "shiver",
    "shudder",
    "tremor",
    "hum",
    "thrum",
}

RESONANCE_EMBODIED_WORDS = {
    "hand",
    "hands",
    "palm",
    "skin",
    "fingers",
    "contact",
    "against the bark",
    "against bark",
    "beneath his palm",
    "beneath her palm",
    "under his hand",
    "under her hand",
    "through the bark",
    "through the roots",
}

FORBIDDEN_RESONANCE_WORDS = {
    "prophecy",
    "prophesied",
    "foretold",
    "future",
    "prediction",
    "voice",
    "voices",
    "spoke",
    "spoken",
    "whispered",
    "whisper",
    "said",
    "told him",
    "told her",
}


def find_exact_duplicate(request: dict, scenes: list):
    for s in scenes:
        if s.get("status") != "canon":
            continue

        # Prefer canonical event_id matching when available
        if s.get("event_id") and request.get("event_id"):
            same_event = s["event_id"] == request["event_id"]
        else:
            same_event = normalize(s.get("event_name", "")) == normalize(request.get("event_name", ""))

        same = (
            s.get("year") == request.get("year") and
            same_event and
            normalize(s.get("guardian", "")) == normalize(request.get("guardian", "")) and
            normalize(s.get("location", "")) == normalize(request.get("location", "")) and
            normalize(s.get("scene_type", "")) == normalize(request.get("scene_type", "")) and
            tones_similar(s.get("tone", ""), request.get("tone", ""))
        )

        if same:
            return s

    return None


def find_event_scenes(event_name: str, scenes: list, event_id: str = None):
    matches = []

    for s in scenes:
        if s.get("status") != "canon":
            continue

        if event_id and s.get("event_id") == event_id:
            matches.append(s)
        elif normalize(s.get("event_name", "")) == normalize(event_name):
            matches.append(s)

    return matches
    
def _split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in text.split("\n\n")]
    return [p for p in parts if p]


def _excerpt(paragraph: str, limit: int = 240) -> str:
    flattened = " ".join(paragraph.split())
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3] + "..."


def _score_resonance_paragraph(paragraph: str) -> int:
    p = normalize(paragraph)

    score = 0

    for marker in EXPLICIT_RESONANCE_MARKERS:
        if marker.lower() in p:
            score += 10

    memory_hits = sum(1 for token in RESONANCE_MEMORY_WORDS if token in p)
    signal_hits = sum(1 for token in RESONANCE_SIGNAL_WORDS if token in p)
    embodied_hits = sum(1 for token in RESONANCE_EMBODIED_WORDS if token in p)

    if memory_hits >= 1:
        score += 1
    if signal_hits >= 2:
        score += 1
    if embodied_hits >= 1:
        score += 1

    if memory_hits >= 1 and signal_hits >= 2 and embodied_hits >= 1:
        score += 2

    return score


def _paragraph_looks_like_resonance(paragraph: str) -> bool:
    return _score_resonance_paragraph(paragraph) >= 4


def validate_resonance_law(text: str, max_allowed: int = 3) -> ResonanceValidationResult:
    result = ResonanceValidationResult(
        is_valid=True,
        resonance_count=0,
        max_allowed=max_allowed,
    )

    paragraphs = _split_paragraphs(text)

    for idx, paragraph in enumerate(paragraphs):
        if _paragraph_looks_like_resonance(paragraph):
            result.findings.append(
                ResonanceFinding(
                    paragraph_index=idx,
                    excerpt=_excerpt(paragraph),
                    score=_score_resonance_paragraph(paragraph),
                )
            )

    result.resonance_count = len(result.findings)

    normalized_text = normalize(text)
    for forbidden in FORBIDDEN_RESONANCE_WORDS:
        if forbidden in normalized_text:
            result.errors.append(f"Forbidden resonance behavior detected: '{forbidden}'")

    if result.resonance_count > max_allowed:
        result.errors.append(
            f"Resonance law violation: found {result.resonance_count} resonance events, maximum allowed is {max_allowed}."
        )

    result.is_valid = len(result.errors) == 0
    return result


def format_resonance_validation_report(result: ResonanceValidationResult) -> str:
    lines: list[str] = []
    lines.append("POST-GENERATION RESONANCE VALIDATION")
    lines.append(f"Valid: {'YES' if result.is_valid else 'NO'}")
    lines.append(f"Detected Resonance Events: {result.resonance_count}")
    lines.append(f"Maximum Allowed: {result.max_allowed}")

    if result.findings:
        lines.append("")
        lines.append("Detected Resonance Findings:")
        for idx, finding in enumerate(result.findings, start=1):
            lines.append(
                f"{idx}. paragraph={finding.paragraph_index} score={finding.score} excerpt={finding.excerpt}"
            )

    if result.errors:
        lines.append("")
        lines.append("Errors:")
        for err in result.errors:
            lines.append(f"- {err}")

    return "\n".join(lines)