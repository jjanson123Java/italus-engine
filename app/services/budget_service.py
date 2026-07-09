"""
Budget estimation service for project setup.

This service is the backend source of truth for planning estimates. It does not
control runtime prompt packing or generation context.
"""

from __future__ import annotations

from typing import Any


TOKEN_MULTIPLIER_DEFAULT = 1.3
WARNING_THRESHOLD_DEFAULT = 0.85


def estimate_project_budget(
    payload: dict[str, Any],
    *,
    token_multiplier: float = TOKEN_MULTIPLIER_DEFAULT,
    warning_threshold: float = WARNING_THRESHOLD_DEFAULT,
) -> dict[str, Any]:
    book_count = _positive_int(payload.get("book_count"), 1)
    chapters_per_book = _positive_int(payload.get("chapters_per_book"), 40)
    target_words_per_chapter = _positive_int(payload.get("target_words_per_chapter"), 4000)
    token_budget_total = _positive_int(payload.get("token_budget_total"), 250000)
    token_budget_per_generation = _positive_int(payload.get("token_budget_per_generation"), 8000)

    target_words_per_book = _positive_int(
        payload.get("target_words_per_book"),
        chapters_per_book * target_words_per_chapter,
    )
    target_total_words = _positive_int(
        payload.get("target_total_words"),
        book_count * target_words_per_book,
    )

    estimated_tokens_per_chapter = _ceil_tokens(target_words_per_chapter, token_multiplier)
    estimated_tokens_per_book = _ceil_tokens(target_words_per_book, token_multiplier)
    estimated_tokens_total = _ceil_tokens(target_total_words, token_multiplier)
    estimated_generation_passes_required = max(
        1,
        _ceil_div(estimated_tokens_total, token_budget_per_generation),
    )

    status = "OK"
    if estimated_tokens_total > token_budget_total:
        status = "EXCEEDS_BUDGET"
    elif estimated_tokens_total >= int(token_budget_total * warning_threshold):
        status = "WARNING"

    return {
        "book_count": book_count,
        "chapters_per_book": chapters_per_book,
        "target_words_per_chapter": target_words_per_chapter,
        "target_words_per_book": target_words_per_book,
        "target_total_words": target_total_words,
        "token_budget_total": token_budget_total,
        "token_budget_per_generation": token_budget_per_generation,
        "token_multiplier": token_multiplier,
        "warning_threshold": warning_threshold,
        "estimated_words_per_book": target_words_per_book,
        "estimated_words_total": target_total_words,
        "estimated_tokens_per_book": estimated_tokens_per_book,
        "estimated_tokens_total": estimated_tokens_total,
        "estimated_tokens_per_chapter": estimated_tokens_per_chapter,
        "estimated_generation_passes_required": estimated_generation_passes_required,
        "token_budget_status": status,
        "recommendations": _recommendations(status),
    }


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _ceil_tokens(words: int, multiplier: float) -> int:
    return int((words * multiplier) + 0.999999)


def _ceil_div(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 1
    return -(-numerator // denominator)


def _recommendations(status: str) -> list[str]:
    if status == "OK":
        return []
    if status == "WARNING":
        return [
            "Review chapter word targets before continuing.",
            "Consider increasing the total token budget or lowering target words per chapter.",
        ]
    return [
        "Increase token_budget_total.",
        "Reduce book_count, chapters_per_book, or target_words_per_chapter.",
        "Review token_budget_per_generation before canon setup.",
    ]
