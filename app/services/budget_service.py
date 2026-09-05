"""
Budget estimation service for project setup.

This service is the backend source of truth for planning estimates. It does not
control runtime prompt packing or generation context.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


TOKEN_MULTIPLIER_DEFAULT = 1.3
WARNING_THRESHOLD_DEFAULT = 0.85
PROVIDER_PLANNING_COST_SCHEMA_VERSION = "primary33.1-provider-planning-cost-v1"
_ONE_MTOK = Decimal("1000000")
_PLANNING_COST_QUANTUM = Decimal("0.000001")


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


def estimate_provider_planning_cost(
    budget_plan: dict[str, Any],
    pricing: dict[str, Any],
) -> dict[str, Any]:
    """Return a provider-priced *planning* estimate for generated output only.

    The existing project planning estimate is derived from target prose words, so
    `estimated_tokens_total` represents planned generated-output volume. Primary
    33.1 does not yet have an exact provider request and therefore cannot know
    prompt-input, cache, tool, tax, discount, or provider-rounding charges.

    This function intentionally prices only the planned generated-output tokens
    against the active immutable output rate. It must never be presented as an
    actual provider charge or as the exact pre-generation estimate introduced in
    Primary 33.2.
    """

    try:
        estimated_output_tokens = int(budget_plan.get("estimated_tokens_total") or 0)
    except (TypeError, ValueError):
        estimated_output_tokens = 0
    estimated_output_tokens = max(estimated_output_tokens, 0)

    rates = pricing.get("rates_per_mtok")
    rates = rates if isinstance(rates, dict) else {}
    output_rate = _nonnegative_decimal(
        rates.get("output_per_mtok"),
        "output_per_mtok",
    )
    estimated_cost = (
        Decimal(estimated_output_tokens) / _ONE_MTOK
    ) * output_rate

    return {
        "status": "ok",
        "schema_version": PROVIDER_PLANNING_COST_SCHEMA_VERSION,
        "estimate_kind": "planning_estimate",
        "basis": "planned_generated_output_tokens_only",
        "estimated_generated_output_tokens": estimated_output_tokens,
        "estimated_cost": _decimal_cost_string(estimated_cost),
        "currency": str(pricing.get("currency") or "").strip().upper() or None,
        "pricing_version_id": pricing.get("pricing_version_id"),
        "output_rate_per_mtok": format(output_rate.normalize(), "f"),
        "actual_cost": False,
        "includes_prompt_input": False,
        "includes_cache": False,
        "includes_provider_tools": False,
        "note": (
            "Planning Estimate: generated output only. Prompt input, cache, "
            "provider-tool, tax, discount, and provider-rounding charges are "
            "not included until exact provider accounting is available."
        ),
    }


def _nonnegative_decimal(value: Any, field_name: str) -> Decimal:
    raw = str(value if value is not None else "0").strip() or "0"
    try:
        parsed = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a decimal number") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be a finite nonnegative decimal")
    return parsed


def _decimal_cost_string(value: Decimal) -> str:
    rounded = value.quantize(_PLANNING_COST_QUANTUM)
    normalized = format(rounded.normalize(), "f")
    return "0" if normalized in {"", "-0"} else normalized


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
