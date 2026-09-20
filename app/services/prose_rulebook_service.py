"""
System prose-generation rulebook boundary.

The rulebook is application-owned prose-mechanics policy. It is not Canon,
Author Voice, Chapter Plan state, or POV state. Chapter Knowledge Pack
compilation embeds this rulebook so later Prompt Builder routing and candidate
validation receive the same deterministic prose-mechanics contract.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any


PROSE_RULEBOOK_SERVICE_MARKER = "system-prose-generation-rulebook-20260823"
PROSE_RULEBOOK_VERSION = "1.1"
PROSE_RULEBOOK_FILENAME = "generic_prose_generation_rulebook_v1_1.md"
PROSE_RULEBOOK_PATH = (
    Path(__file__).resolve().parents[1] / "rules" / PROSE_RULEBOOK_FILENAME
)

QUANTITATIVE_METRICS = {
    "word_count": {
        "minimum": 4000,
        "hard_fail_below_minimum": True,
    },
    "em_dashes": {
        "preferred_minimum": 0,
        "preferred_maximum": 6,
        "hard_maximum": 8,
    },
    "semicolons": {
        "preferred_minimum": 0,
        "preferred_maximum": 10,
        "hard_maximum": 15,
    },
    "colons": {
        "hard_maximum": 3,
    },
    "ellipses": {
        "hard_maximum": 4,
        "must_be_narratively_justified": True,
    },
    "similes": {
        "hard_maximum": 12,
    },
}

DETERMINISTIC_METRICS = frozenset(
    {
        "word_count",
        "em_dashes",
        "semicolons",
        "colons",
        "ellipses",
    }
)
MANUAL_METRICS = frozenset({"similes"})
_WORD_RE = re.compile(r"\b[\w\u2019'-]+\b", flags=re.UNICODE)


class ProseRulebookError(RuntimeError):
    """Raised when the application-owned prose rulebook cannot be loaded."""


def get_prose_rulebook_contract() -> dict[str, Any]:
    """Return the immutable application-owned prose rulebook contract."""

    if not PROSE_RULEBOOK_PATH.exists():
        raise ProseRulebookError(
            f"Prose generation rulebook is missing: {PROSE_RULEBOOK_PATH}"
        )

    text = PROSE_RULEBOOK_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise ProseRulebookError("Prose generation rulebook is empty.")

    return {
        "service": PROSE_RULEBOOK_SERVICE_MARKER,
        "version": PROSE_RULEBOOK_VERSION,
        "filename": PROSE_RULEBOOK_FILENAME,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "quantitative_metrics": QUANTITATIVE_METRICS,
        "prompt_text": text,
    }


def measure_prose(text: str) -> dict[str, int]:
    """Return the single application-owned deterministic prose measurements.

    Word counting intentionally matches the candidate-validation migration
    baseline: word-like tokens may contain apostrophes/hyphens, while
    punctuation limits count literal punctuation marks in the exact text.
    """

    if not isinstance(text, str):
        raise ProseRulebookError("Prose candidate must be text.")

    return {
        "word_count": len(_WORD_RE.findall(text)),
        "em_dashes": text.count("\u2014"),
        "semicolons": text.count(";"),
        "colons": text.count(":"),
        "ellipses": text.count("\u2026") + text.count("..."),
    }


def deterministic_metric_result(
    metric_name: str,
    measurement: int,
    metric_contract: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one deterministic metric against its embedded contract."""

    name = str(metric_name or "").strip()
    if name not in DETERMINISTIC_METRICS:
        raise ProseRulebookError(
            f"Metric is not deterministically evaluable: {name or '<missing>'}"
        )
    if not isinstance(metric_contract, dict):
        raise ProseRulebookError(f"Metric contract is invalid: {name}")

    if name == "word_count":
        minimum = int(metric_contract.get("minimum") or 0)
        if minimum < 1:
            raise ProseRulebookError("word_count minimum is missing or invalid")
        passed = int(measurement) >= minimum
        return {
            "metric": name,
            "measurement": int(measurement),
            "operator": "minimum",
            "threshold": minimum,
            "passed": passed,
            "message": (
                f"Word count is {int(measurement)}; minimum is {minimum}."
            ),
        }

    hard_maximum = metric_contract.get("hard_maximum")
    try:
        maximum = int(hard_maximum)
    except (TypeError, ValueError) as exc:
        raise ProseRulebookError(
            f"{name} hard_maximum is missing or invalid"
        ) from exc
    if maximum < 0:
        raise ProseRulebookError(f"{name} hard_maximum is invalid")

    passed = int(measurement) <= maximum
    return {
        "metric": name,
        "measurement": int(measurement),
        "operator": "hard_maximum",
        "threshold": maximum,
        "passed": passed,
        "message": (
            f"{name.replace('_', ' ').title()} count is {int(measurement)}; "
            f"hard maximum is {maximum}."
        ),
    }


def evaluate_deterministic_metrics(
    text: str,
    metrics_contract: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Evaluate every supported deterministic metric in one exact candidate."""

    if not isinstance(metrics_contract, dict):
        raise ProseRulebookError("quantitative_metrics contract is invalid")

    measurements = measure_prose(text)
    results: dict[str, dict[str, Any]] = {}
    for name in sorted(DETERMINISTIC_METRICS):
        contract = metrics_contract.get(name)
        if not isinstance(contract, dict):
            raise ProseRulebookError(
                f"quantitative_metrics is missing deterministic metric: {name}"
            )
        results[name] = deterministic_metric_result(
            name,
            measurements[name],
            contract,
        )
    return results
