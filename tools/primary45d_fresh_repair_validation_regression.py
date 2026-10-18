"""Behavioral regression for candidate repair-source lineage gate (no provider calls)."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
import textwrap
from unittest.mock import patch

from app.services import provider_generation_receipt_service

source = (Path(__file__).resolve().parents[1] / "app/services/validation_service.py").read_text(encoding="utf-8")
tree = ast.parse(source)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "validate_generation_candidate")
method = ast.get_source_segment(source, fn)
assert method is not None
begin = source.index("    repair_source_id = ", fn.lineno and sum(len(x) + 1 for x in source.splitlines()[:fn.lineno - 1]))
end = source.index("    integrity_checks = [", begin)
actual_gate = source[begin:end]
# Execute the exact gate from the owning production method with synthetic immutable receipts.
runner = "def run(receipt, generation, project_id, book_number, chapter_number):\n" + actual_gate + "    return repair_source_id, repair_source_error\n"
scope = {
    "re": re,
    "hashlib": hashlib,
    "provider_generation_receipt_service": provider_generation_receipt_service,
}
exec(compile(runner, "<existing-validation-repair-gate>", "exec"), scope)
run = scope["run"]

source_id = "gen_" + "a" * 32
repair_id = "gen_" + "b" * 32
text = "Original failed chapter."
source_receipt = {
    "book_number": 2, "chapter_number": 3, "output_text": text,
    "output_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    "generation_quality_gate": {
        "passed": False, "blockers": [{"code": "DETERMINISTIC_PROSE_FAILURE", "metric": "word_count"}]
    },
}
repair_receipt = {"repair_for_generation_id": source_id}
with patch.object(provider_generation_receipt_service, "get_receipt", return_value=source_receipt):
    assert run(repair_receipt, repair_id, "synthetic-project", 2, 3) == (source_id, "")
with patch.object(provider_generation_receipt_service, "get_receipt", return_value=None):
    assert run(repair_receipt, repair_id, "synthetic-project", 2, 3)[1] == "REPAIR_SOURCE_RECEIPT_MISSING"
with patch.object(provider_generation_receipt_service, "get_receipt", return_value={**source_receipt, "repair_for_generation_id": repair_id}):
    assert run(repair_receipt, repair_id, "synthetic-project", 2, 3)[1] == "REPAIR_SOURCE_LINEAGE_MISMATCH"
with patch.object(provider_generation_receipt_service, "get_receipt", return_value={**source_receipt, "chapter_number": 4}):
    assert run(repair_receipt, repair_id, "synthetic-project", 2, 3)[1] == "REPAIR_SOURCE_LINEAGE_MISMATCH"
with patch.object(provider_generation_receipt_service, "get_receipt", return_value={**source_receipt, "output_text_sha256": "0" * 64}):
    assert run(repair_receipt, repair_id, "synthetic-project", 2, 3)[1] == "REPAIR_SOURCE_CONTENT_HASH_MISMATCH"
with patch.object(provider_generation_receipt_service, "get_receipt", return_value={**source_receipt, "generation_quality_gate": {"passed": True, "blockers": []}}):
    assert run(repair_receipt, repair_id, "synthetic-project", 2, 3)[1] == "REPAIR_SOURCE_NOT_DETERMINISTIC_FAILURE"
with patch.object(provider_generation_receipt_service, "get_receipt", side_effect=AssertionError("should not fetch source")):
    assert run({"repair_for_generation_id": repair_id}, repair_id, "synthetic-project", 2, 3)[1] == "REPAIR_SOURCE_IDENTITY_INVALID"
    assert run({}, repair_id, "synthetic-project", 2, 3) == ("", "")
assert "repair_source_lineage" in method
assert method.index("repair_source_lineage") < method.index("integrity_blocking")
assert '"repair_for_generation_id": repair_source_id or None' in method
print("PRIMARY45D FRESH REPAIR VALIDATION PASS")
