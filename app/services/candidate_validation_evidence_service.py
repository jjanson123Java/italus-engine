"""Read-only evidence extraction for candidate validation reports.

The authoritative validator owns PASS/FAIL/UNKNOWN decisions.  This module
adds exact, version-bound locations for deterministic findings and conservative
related-passage suggestions for rules that still require author judgment.  A
related passage is never promoted into a semantic verdict by this service.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


EVIDENCE_SERVICE_MARKER = "candidate-validation-evidence-v1-20260920"
VERY_SHORT_SENTENCE_MAX_WORDS = 8
VERY_SHORT_SENTENCE_CLUSTER_MINIMUM = 3
MAX_RELATED_PASSAGES = 8

_WORD_RE = re.compile(r"\b[\w\u2019'-]+\b", flags=re.UNICODE)
_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?\u2026]+(?:[\"'\u2019\u201d)]*)?(?=\s|$)")
_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n")
_MARKDOWN_ONLY_RE = re.compile(r"^(?:#{1,6}\s+|[-*_]{3,}\s*$)")

_STOPWORDS = frozenset(
    {
        "a", "about", "after", "all", "an", "and", "any", "are", "as", "at",
        "be", "before", "book", "but", "by", "chapter", "confirm", "current",
        "do", "does", "during", "every", "for", "from", "full", "has", "have",
        "his", "in", "into", "is", "it", "its", "later", "may", "must", "no",
        "not", "of", "on", "only", "or", "other", "present", "required", "rule",
        "should", "than", "that", "the", "their", "this", "to", "use", "with",
    }
)

_CONCEPT_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "age": (
        re.compile(r"\b(?:age|aged)\b", re.IGNORECASE),
        re.compile(r"\b(?:\d{1,4}|[a-z]+(?:-[a-z]+)?)\s+years?\s+old\b", re.IGNORECASE),
        re.compile(r"\bapparent age\b", re.IGNORECASE),
    ),
    "lifespan": (
        re.compile(r"\b(?:lifespan|life span|longevity|immortal|mortal)\b", re.IGNORECASE),
        re.compile(r"\b(?:\d{1,4}|[a-z]+(?:-[a-z]+)?)\s+(?:years?|centuries)\b", re.IGNORECASE),
        re.compile(r"\bcentur(?:y|ies)\b", re.IGNORECASE),
    ),
    "alias": (
        re.compile(r"\b(?:alias|aliases|known as|called|name was|my name is)\b", re.IGNORECASE),
    ),
    "guardian": (re.compile(r"\bguardian(?:s| zero)?\b", re.IGNORECASE),),
    "telepathy": (re.compile(r"\btelepath(?:y|ic|ically)?\b", re.IGNORECASE),),
    "prophecy": (re.compile(r"\b(?:prophecy|prophetic|prophesied|foretold)\b", re.IGNORECASE),),
    "vision": (re.compile(r"\b(?:remote vision|vision|visions)\b", re.IGNORECASE),),
    "fate": (re.compile(r"\b(?:fate|destiny|final end)\b", re.IGNORECASE),),
    "intervention": (re.compile(r"\binterven(?:e|ed|es|tion|tions)\b", re.IGNORECASE),),
    "connection": (
        re.compile(r"\b(?:connection|connected|coupling|linked|bonded)\b", re.IGNORECASE),
    ),
}


def _flatten(value: str) -> str:
    return " ".join(str(value or "").split())


def _paragraph_number(text: str, offset: int) -> int:
    return len(_PARAGRAPH_BREAK_RE.findall(text, 0, max(0, offset))) + 1


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _sentence_spans(text: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    cursor = 0
    sentence_number = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        raw_start = cursor
        raw_end = match.end()
        cursor = raw_end
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        segment = text[raw_start:raw_end]
        leading = len(segment) - len(segment.lstrip())
        trailing = len(segment.rstrip())
        start = raw_start + leading
        end = raw_start + trailing
        if end <= start:
            continue
        sentence_number += 1
        spans.append(
            {
                "sentence_number": sentence_number,
                "paragraph_number": _paragraph_number(text, start),
                "line_number": _line_number(text, start),
                "start_offset": start,
                "end_offset": end,
                "text": text[start:end],
            }
        )

    if cursor < len(text):
        segment = text[cursor:]
        leading = len(segment) - len(segment.lstrip())
        trailing = len(segment.rstrip())
        start = cursor + leading
        end = cursor + trailing
        if end > start:
            sentence_number += 1
            spans.append(
                {
                    "sentence_number": sentence_number,
                    "paragraph_number": _paragraph_number(text, start),
                    "line_number": _line_number(text, start),
                    "start_offset": start,
                    "end_offset": end,
                    "text": text[start:end],
                }
            )
    return spans


def _sentence_for_offset(
    sentences: list[dict[str, Any]],
    offset: int,
) -> dict[str, Any] | None:
    for sentence in sentences:
        if int(sentence["start_offset"]) <= offset < int(sentence["end_offset"]):
            return sentence
    return None


def _evidence_item(
    sentence: dict[str, Any],
    *,
    match_start: int | None = None,
    match_end: int | None = None,
    matched_text: str = "",
    evidence_type: str = "exact_match",
    score: int | None = None,
) -> dict[str, Any]:
    item = {
        "evidence_type": evidence_type,
        "sentence_number": int(sentence["sentence_number"]),
        "paragraph_number": int(sentence["paragraph_number"]),
        "line_number": int(sentence["line_number"]),
        "start_offset": int(
            sentence["start_offset"] if match_start is None else match_start
        ),
        "end_offset": int(
            sentence["end_offset"] if match_end is None else match_end
        ),
        "context_start_offset": int(sentence["start_offset"]),
        "context_end_offset": int(sentence["end_offset"]),
        "matched_text": str(matched_text or ""),
        "excerpt": _flatten(str(sentence["text"])),
    }
    if score is not None:
        item["relevance_score"] = int(score)
    return item


def deterministic_metric_evidence(
    text: str,
    metric_name: str,
) -> list[dict[str, Any]]:
    """Return exact sentence-bound locations for punctuation measurements."""

    needles: tuple[str, ...]
    if metric_name == "em_dashes":
        needles = ("\u2014",)
    elif metric_name == "semicolons":
        needles = (";",)
    elif metric_name == "colons":
        needles = (":",)
    elif metric_name == "ellipses":
        needles = ("\u2026", "...")
    else:
        return []

    sentences = _sentence_spans(text)
    evidence: list[dict[str, Any]] = []
    occupied: set[tuple[int, int]] = set()
    for needle in needles:
        for match in re.finditer(re.escape(needle), text):
            span = (match.start(), match.end())
            if span in occupied:
                continue
            occupied.add(span)
            sentence = _sentence_for_offset(sentences, match.start())
            if sentence is None:
                continue
            evidence.append(
                _evidence_item(
                    sentence,
                    match_start=match.start(),
                    match_end=match.end(),
                    matched_text=match.group(0),
                )
            )
    return sorted(evidence, key=lambda item: int(item["start_offset"]))


def very_short_sentence_diagnostic(text: str) -> dict[str, Any]:
    """Identify short sentences and clusters without claiming a hard failure."""

    sentences = _sentence_spans(text)
    short: list[dict[str, Any]] = []
    short_numbers: set[int] = set()
    for sentence in sentences:
        sentence_text = _flatten(str(sentence["text"]))
        if not sentence_text or _MARKDOWN_ONLY_RE.match(sentence_text):
            continue
        word_count = len(_WORD_RE.findall(sentence_text))
        if word_count > VERY_SHORT_SENTENCE_MAX_WORDS:
            continue
        item = _evidence_item(sentence, evidence_type="short_sentence_candidate")
        item["word_count"] = word_count
        short.append(item)
        short_numbers.add(int(sentence["sentence_number"]))

    cluster_numbers: set[int] = set()
    run: list[int] = []
    for sentence in sentences:
        number = int(sentence["sentence_number"])
        if number in short_numbers:
            run.append(number)
            continue
        if len(run) >= VERY_SHORT_SENTENCE_CLUSTER_MINIMUM:
            cluster_numbers.update(run)
        run = []
    if len(run) >= VERY_SHORT_SENTENCE_CLUSTER_MINIMUM:
        cluster_numbers.update(run)

    for item in short:
        item["clustered"] = int(item["sentence_number"]) in cluster_numbers

    status = "REVIEW" if cluster_numbers else "PASS"
    message = (
        f"Found {len(short)} sentences with {VERY_SHORT_SENTENCE_MAX_WORDS} or fewer "
        f"words; {len(cluster_numbers)} occur in clusters of "
        f"{VERY_SHORT_SENTENCE_CLUSTER_MINIMUM} or more. Short sentences may be "
        "intentional, so this remains an author-review diagnostic."
    )
    return {
        "name": "Very short sentence review",
        "rule_id": "prose.very_short_sentences.review",
        "rule_type": "PROSE_STYLE_DIAGNOSTIC",
        "source_type": "PROSE_RULEBOOK",
        "source_ref": "sentence_architecture",
        "evaluation_mode": "DIAGNOSTIC",
        "severity": "INFO",
        "status": status,
        "passed": status == "PASS",
        "required": False,
        "code": "PROSE_SHORT_SENTENCE_REVIEW" if status == "REVIEW" else "",
        "message": message,
        "instruction": (
            "Review very short sentence clusters for deliberate emphasis, impact, "
            "tension, clarity, or rhythm."
        ),
        "details": {
            "measurement": len(short),
            "threshold": VERY_SHORT_SENTENCE_MAX_WORDS,
            "operator": "words_or_fewer",
            "cluster_minimum": VERY_SHORT_SENTENCE_CLUSTER_MINIMUM,
            "clustered_sentence_count": len(cluster_numbers),
            "evidence": short,
        },
    }


def _stem(token: str) -> str:
    value = token.casefold().replace("\u2019", "'").strip("'-")
    for suffix in ("ingly", "edly", "ations", "ation", "ments", "ment", "ing", "ies", "ed", "es", "s"):
        if len(value) > len(suffix) + 3 and value.endswith(suffix):
            value = value[: -len(suffix)]
            break
    return value


def _instruction_terms(instruction: str) -> set[str]:
    terms = {
        _stem(match.group(0))
        for match in _WORD_RE.finditer(instruction)
        if match.group(0).casefold() not in _STOPWORDS
    }
    return {term for term in terms if len(term) >= 3}


def _instruction_concepts(instruction: str) -> set[str]:
    folded = instruction.casefold()
    return {
        concept
        for concept, patterns in _CONCEPT_PATTERNS.items()
        if concept in folded or any(pattern.search(instruction) for pattern in patterns)
    }


def _sentence_concepts(sentence: str, concepts: Iterable[str]) -> set[str]:
    return {
        concept
        for concept in concepts
        if any(pattern.search(sentence) for pattern in _CONCEPT_PATTERNS[concept])
    }


def related_narrative_evidence(
    text: str,
    instruction: str,
    *,
    limit: int = MAX_RELATED_PASSAGES,
) -> list[dict[str, Any]]:
    """Return conservative related passages for author review.

    This is lexical/conceptual retrieval only.  Results are evidence candidates,
    not proof that the narrative rule passed or failed.
    """

    terms = _instruction_terms(instruction)
    concepts = _instruction_concepts(instruction)
    if not terms and not concepts:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for sentence in _sentence_spans(text):
        sentence_text = str(sentence["text"])
        sentence_terms = {_stem(match.group(0)) for match in _WORD_RE.finditer(sentence_text)}
        overlap = terms & sentence_terms
        concept_hits = _sentence_concepts(sentence_text, concepts)
        proper_name_hits = {
            term for term in overlap if term and term[0].isalpha() and term in terms
        }
        score = len(overlap) + (2 * len(concept_hits)) + len(proper_name_hits)
        if score < 2 or (not overlap and not concept_hits):
            continue
        evidence = _evidence_item(
            sentence,
            evidence_type="related_passage",
            score=score,
        )
        evidence["matched_terms"] = sorted(overlap)
        evidence["matched_concepts"] = sorted(concept_hits)
        scored.append((score, evidence))

    scored.sort(key=lambda pair: (-pair[0], int(pair[1]["start_offset"])))
    return [item for _, item in scored[: max(1, int(limit))]]

