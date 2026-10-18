"""Verify immutable receipt quality is measured afresh, never trusted blindly."""
from __future__ import annotations
from app.services import provider_execution_service as execution
from app.services import generation_quality_gate_service as gate

from app.services import prose_rulebook_service
LIMITS = dict(prose_rulebook_service.QUANTITATIVE_METRICS)
LIMITS["word_count"] = {"minimum": 4, "hard_fail_below_minimum": True}
DRAFT = "one two three four five"
REPORT = gate.evaluate_output(DRAFT, stop_reason="end_turn", hard_prose_metrics=LIMITS)
receipt = {"output_text": DRAFT, "stop_reason": "end_turn", "generation_quality_gate": REPORT}
assert execution._quality_gate_receipt(receipt, hard_prose_metrics=LIMITS) == REPORT
assert receipt["generation_quality_gate"] == REPORT

bad_receipt = dict(receipt)
bad_receipt["generation_quality_gate"] = {**REPORT, "passed": False}
try:
    execution._quality_gate_receipt(bad_receipt, hard_prose_metrics=LIMITS)
except execution.ProviderExecutionError as exc:
    assert exc.code == "GENERATION_QUALITY_RECEIPT_DRIFT", exc.code
else:
    raise AssertionError("A stale stored quality gate was trusted.")

unmeasured = {"output_text": DRAFT, "stop_reason": "end_turn"}
assert execution._quality_gate_receipt(unmeasured, hard_prose_metrics=LIMITS) == REPORT
print("PRIMARY45D QUALITY RECEIPT REVALIDATION PASS")
