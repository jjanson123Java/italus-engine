"""Primary 45D controlled repair execution negative and lineage tests; no provider spend."""
from __future__ import annotations

import hashlib
from unittest.mock import patch
from app.services import replacement_generation_context_service as rc
from app.services import provider_execution_service as pe
from app.services import generation_service as gs
from app.services import provider_generation_receipt_service as receipts

SOURCE = "gen_" + "a" * 32
TEXT = "Measured original draft."
HASH = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
REPORT = {
    "passed": False,
    "blockers": [{"code": "DETERMINISTIC_PROSE_FAILURE", "metric": "word_count",
                  "measurement": 3, "operator": ">=", "threshold": 4000}],
}
RECEIPT = {"book_number": 2, "chapter_number": 3, "output_text": TEXT,
           "output_text_sha256": HASH, "generation_quality_gate": REPORT,
           "validator_sidecar_sha256": "e" * 64,
           "request_content_sha256": "f" * 64, "stop_reason": "end_turn"}

with patch.object(receipts, "get_receipt", return_value=RECEIPT):
    ctx = rc.build_replacement_correction_context(
        "synthetic-project", SOURCE, book_number=2, chapter_number=3,
        repair_from_quality_receipt=True,
    )
    assert ctx["authority"] == "backend_derived_mechanical_repair"
    assert ctx["source_generation_id"] == SOURCE
    assert ctx["rejected_prose_included"] is False
    assert ctx["deterministic_failure_count"] == 1
    assert ctx["audited_semantic_failure_count"] == 0
    assert ctx["context_sha256"] == rc._sha256({k:v for k,v in ctx.items() if k != "context_sha256"})

with patch.object(receipts, "get_receipt", return_value={**RECEIPT, "repair_for_generation_id": SOURCE}):
    try:
        rc.build_replacement_correction_context(
            "synthetic-project", SOURCE, book_number=2, chapter_number=3,
            repair_from_quality_receipt=True,
        )
        raise AssertionError("Nested repair was not blocked")
    except rc.ReplacementGenerationContextError as exc:
        assert exc.code == "REPAIR_SOURCE_NOT_ELIGIBLE"

with patch.object(receipts, "get_receipt", return_value={**RECEIPT, "output_text_sha256": "0"*64}):
    try:
        rc.build_replacement_correction_context(
            "synthetic-project", SOURCE, book_number=2, chapter_number=3,
            repair_from_quality_receipt=True,
        )
        raise AssertionError("Tampered source was not blocked")
    except rc.ReplacementGenerationContextError as exc:
        assert exc.code == "REPAIR_SOURCE_NOT_ELIGIBLE"

# The completed repair transaction must be a separate provider request:
# its envelope contains the bound correction identity rather than the source ID.
replacement = gs._replacement_request_identity(ctx, book_number=2, chapter_number=3)
assert replacement["enabled"] is True
assert replacement["source_generation_id"] == SOURCE
assert replacement["context_sha256"] == ctx["context_sha256"]

# Both modes together must fail before any provider/spend/receipt operation.
try:
    pe.execute_provider_generation(
        "synthetic-project", book_number=2, chapter_number=3,
        idempotency_key="caller-key", repair_for_generation_id=SOURCE,
        replacement_for_generation_id=SOURCE,
    )
    raise AssertionError("Conflicting repair and replacement unexpectedly allowed")
except pe.ProviderExecutionError as exc:
    assert exc.code == "REPAIR_REPLACEMENT_MODE_CONFLICT"

# Calling explicit repair mode cannot fall back to a normal generation.
with patch.object(rc, "build_replacement_correction_context", side_effect=rc.ReplacementGenerationContextError(
    "REPAIR_SOURCE_NOT_ELIGIBLE", "Synthetic disallowed source"
)), patch.object(pe.generation_service, "build_generation_request_envelope", side_effect=AssertionError("provider build reached")):
    try:
        pe.execute_provider_generation(
            "synthetic-project", book_number=2, chapter_number=3,
            idempotency_key="attacker-controlled-key",
            repair_for_generation_id=SOURCE,
        )
        raise AssertionError("Ineligible source bypassed repair gate")
    except pe.ProviderExecutionError as exc:
        assert exc.code == "REPAIR_SOURCE_NOT_ELIGIBLE"

print("PRIMARY45D CONTROLLED REPAIR EXECUTION PASS")
