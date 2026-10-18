"""Stage 1 negative regression: sensitive literals in either provider channel fail closed."""
from __future__ import annotations

import ast
from pathlib import Path

from app.services.generation_knowledge_projection_service import (
    GenerationKnowledgeProjectionError,
    assert_provider_reference_safe,
)

SENSITIVE = "born in 1042 CE"
RAW = "In the forbidden future, Farovald was born in 1042 CE."


def check(value: str, expect_block: bool) -> None:
    blocked = False
    try:
        assert_provider_reference_safe(
            value,
            raw_chapter_text=RAW,
            local_sensitive_literals=[SENSITIVE],
        )
    except GenerationKnowledgeProjectionError:
        blocked = True
    assert blocked == expect_block, (value, blocked, expect_block)


def main() -> None:
    # Test both possible prompt channels and non-sensitive authorized content.
    check("Authorized POV and event sequence", False)
    check("USER: " + SENSITIVE, True)
    check("SYSTEM: forbidden_future_knowledge: " + SENSITIVE, True)
    check("SYSTEM: not disclosed\\nUSER: authorized reference", False)

    # Verify the live request builder actually passes both channels to the gate.
    module = ast.parse(
        (Path(__file__).resolve().parents[1] / "app/services/generation_service.py").read_text(encoding="utf-8")
    )
    calls = [
        node for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "assert_provider_reference_safe"
    ]
    assert len(calls) == 1, "Expected exactly one original pre-spend safety gate"
    first_arg = ast.unparse(calls[0].args[0])
    assert "provider_system_text" in first_arg and "provider_user_text" in first_arg, first_arg
    print("PRIMARY45D FULL PROVIDER CHANNEL REVEAL PASS")


if __name__ == "__main__":
    main()
