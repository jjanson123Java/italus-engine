"""Generic genre/template-driven Planner sort policy resolver.

Planner presentation order is derived from the active genre/template rather
than hard-coded genre branches in Book Scope. Story Eligibility still owns
whether a Canon record is selected/available/future/restricted; this service
only determines deterministic ordering *within* those eligibility groups.
"""

from __future__ import annotations

import re
from typing import Any

from app.templates.template_registry import get_template


PLANNER_SORT_POLICY_SERVICE_MARKER = "planner-sort-policy-boundary-20260819"
SUPPORTED_SORT_MODES = frozenset({"alphabetical", "chronology", "numeric"})
DEFAULT_SORT_POLICY: dict[str, str] = {
    "within_group": "alphabetical",
    "field": "display_label",
    "direction": "asc",
    "missing": "last",
}


def resolve_sort_policy(
    *,
    template_id: str | None,
    genre: str | None,
    category_key: str,
) -> dict[str, str]:
    """Return one validated sort policy for a Canon planner category.

    Templates may declare ``planner_sorting`` at top level. Categories without
    an explicit declaration inherit the template default; templates with no
    planner sorting metadata use a deterministic alphabetical fallback.
    """

    template = get_template(template_id, genre)
    sorting = template.get("planner_sorting")
    if not isinstance(sorting, dict):
        sorting = {}
    raw_default = sorting.get("default") if isinstance(sorting.get("default"), dict) else {}
    raw_category = sorting.get(str(category_key or ""))
    if not isinstance(raw_category, dict):
        raw_category = {}

    merged = {**DEFAULT_SORT_POLICY, **raw_default, **raw_category}
    mode = str(merged.get("within_group") or "alphabetical").strip().lower()
    if mode not in SUPPORTED_SORT_MODES:
        mode = "alphabetical"
    field = str(merged.get("field") or "display_label").strip() or "display_label"
    direction = str(merged.get("direction") or "asc").strip().lower()
    if direction not in {"asc", "desc"}:
        direction = "asc"
    missing = str(merged.get("missing") or "last").strip().lower()
    if missing not in {"first", "last"}:
        missing = "last"

    return {
        "within_group": mode,
        "field": field,
        "direction": direction,
        "missing": missing,
    }


def within_group_sort_key(policy: dict[str, Any], item: dict[str, Any]) -> tuple[Any, ...]:
    """Return a deterministic sort key for one catalog row.

    The caller remains responsible for Selected/Eligibility grouping. This key
    is intentionally genre-agnostic and consumes only the template policy and
    the record's indexed planner-sort metadata.
    """

    mode = str(policy.get("within_group") or "alphabetical")
    field = str(policy.get("field") or "display_label")
    direction = str(policy.get("direction") or "asc")
    missing = str(policy.get("missing") or "last")
    raw = _field_value(item, field)
    text = " ".join(str(raw or "").split())
    missing_rank = 0 if missing == "first" else 1
    present_rank = 1 - missing_rank
    if not text:
        return (missing_rank, 0, "", str(item.get("record_id") or ""))

    label = str(item.get("label") or "").casefold()
    record_id = str(item.get("record_id") or "")

    if mode == "chronology":
        value = _chronology_value(text)
        if value is None:
            return (missing_rank, 0, text.casefold(), label, record_id)
        if direction == "desc":
            value = -value
        return (present_rank, 0, value, text.casefold(), label, record_id)

    if mode == "numeric":
        value = _numeric_value(text)
        if value is None:
            return (missing_rank, 0, text.casefold(), label, record_id)
        if direction == "desc":
            value = -value
        return (present_rank, 0, value, text.casefold(), label, record_id)

    value = text.casefold()
    if direction == "desc":
        # Deterministic descending text without locale dependencies.
        value = "".join(chr(0x10FFFF - ord(ch)) for ch in value)
    return (present_rank, 0, value, label, record_id)


def _field_value(item: dict[str, Any], field: str) -> Any:
    if field == "display_label":
        return item.get("label") or item.get("display_label")
    if field in item and item.get(field) not in (None, ""):
        return item.get(field)
    metadata = item.get("planner_sort_metadata")
    if isinstance(metadata, dict):
        return metadata.get(field)
    return None


def _numeric_value(text: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _chronology_value(text: str) -> float | None:
    """Parse the first chronology anchor, including common BCE/BC notation."""

    normalized = text.replace("–", "-").replace("—", "-")
    match = re.search(r"(?<!\d)(\d{1,6})(?!\d)", normalized)
    if not match:
        return None
    value = float(match.group(1))
    suffix = normalized[match.end() : match.end() + 8].casefold()
    prefix = normalized[max(0, match.start() - 8) : match.start()].casefold()
    if "bce" in suffix or "bc" in suffix or "bce" in prefix or re.search(r"\bbc\b", prefix):
        value = -value
    return value
