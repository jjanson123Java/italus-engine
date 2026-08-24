"""
System prose-generation rulebook boundary.

The rulebook is application-owned prose-mechanics policy. It is not Canon,
Author Voice, Chapter Plan state, or POV state. Chapter Knowledge Pack
compilation embeds this rulebook so later Prompt Builder routing receives the
same deterministic prose-mechanics contract.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
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
