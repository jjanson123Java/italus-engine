"""Primary 45D: completed failed-prose candidates remain reviewable, not acceptable.

No live provider calls, no project-data writes, and no synthetic Canon.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.services import (
    generation_quality_gate_service as quality,
    prose_rulebook_service,
    provider_execution_service as execution,
)

ROOT = Path(__file__).resolve().parents[1]


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print("PASS:", label)


def report_for(text: str, reason: str) -> dict:
    return quality.evaluate_output(
        text,
        stop_reason=reason,
        hard_prose_metrics=prose_rulebook_service.QUANTITATIVE_METRICS,
    )


def receipt_for(text: str, reason: str) -> dict:
    return {
        "generation_id": "gen_test_author_review_00001",
        "output_text": text,
        "output_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "stop_reason": reason,
        "generation_quality_gate": report_for(text, reason),
        "usage_event": {"usage_event_id": "usage_test_author_review_00001"},
        "provider_id": "anthropic",
        "model_id": "test-model",
    }


def expect_incomplete_blocked(receipt: dict) -> None:
    try:
        execution._quality_gate_receipt(
            receipt,
            hard_prose_metrics=prose_rulebook_service.QUANTITATIVE_METRICS,
        )
    except execution.ProviderExecutionError as exc:
        check("incomplete output blocked before origin", exc.code == "INCOMPLETE_PROVIDER_OUTPUT"
              or exc.code == "GENERATION_QUALITY_FAILED")
        return
    raise AssertionError("Incomplete or empty provider output unexpectedly reviewable")


def run() -> int:
    failed_text = " ".join(["a"] * 500) + " : : : : : : — — — — — — — — —"
    failed = receipt_for(failed_text, "end_turn")
    metrics = failed["generation_quality_gate"]["deterministic_metrics"]
    check("completed prose violates quantitative rules",
          failed["generation_quality_gate"]["passed"] is False
          and metrics["word_count"]["passed"] is False)
    gate = execution._quality_gate_receipt(
        failed, hard_prose_metrics=prose_rulebook_service.QUANTITATIVE_METRICS
    )
    check("completed metric-only failure is reviewable", gate["passed"] is False
          and all(b["code"] == "DETERMINISTIC_PROSE_FAILURE" for b in gate["blockers"]))
    response = execution._receipt_response(
        failed,
        model_origin={
            "segment_id": "segment_test",
            "origin_id": "origin_test",
            "version_id": "version_test",
            "origin_actor": "MODEL",
            "content_hash": failed["output_text_sha256"],
        },
        idempotent_replay=True,
    )
    check("replayed completed failure retains exact prose and generation identity",
          response["generation_id"] == failed["generation_id"]
          and response["draft"]["text"] == failed_text
          and response["draft"]["sha256"] == failed["output_text_sha256"]
          and response["generation_quality_gate"]["passed"] is False)
    expect_incomplete_blocked(receipt_for(failed_text, "max_tokens"))
    expect_incomplete_blocked(receipt_for("", "end_turn"))
    passed = receipt_for(" ".join(["word"] * 4000), "end_turn")
    check("compliant chapter still passes original gate",
          execution._quality_gate_receipt(
              passed, hard_prose_metrics=prose_rulebook_service.QUANTITATIVE_METRICS
          )["passed"] is True)
    execution_text = (ROOT / "app/services/provider_execution_service.py").read_text(encoding="utf-8")
    validation_text = (ROOT / "app/services/validation_service.py").read_text(encoding="utf-8")
    workspace_text = (ROOT / "frontend/workspace.js").read_text(encoding="utf-8")
    check("usage indicates only completed prose is promoted",
          '"candidate_promoted_to_author_review": bool(' in execution_text
          and '"generation_quality_gate": quality_gate_report' in execution_text)
    check("validator keeps review and acceptance separate",
          '"ready_for_author_review": reviewable' in validation_text
          and 'acceptable = bool(reviewable and not content_blocking)' in validation_text
          and '"provider_generation_quality_gate": deepcopy(' in validation_text)
    check("author review exposes invalid complete prose and retains acceptance guard",
          "event.candidate_promoted_to_author_review === true" in workspace_text
          and "Generated prose needs correction:" in workspace_text
          and "!acceptanceReady" in workspace_text
          and "Save & Revalidate" in workspace_text)
    check("opt-in diagnostics log hashes, usage and metrics but not raw prompts",
          'ITALUS_GENERATION_DIAGNOSTICS' in execution_text
          and '"prompt_sha256": prompt_sha256' in execution_text
          and '"failed_metrics": sorted(' in execution_text
          and 'json.dumps(diagnostic, sort_keys=True)' in execution_text)
    print("PRIMARY45D FAILED DRAFT AUTHOR REVIEW PASS")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
