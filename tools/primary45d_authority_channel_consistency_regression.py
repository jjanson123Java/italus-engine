"""Regression for direct pre-spend authority-channel consistency checks."""
import ast
from pathlib import Path

target = Path(__file__).resolve().parents[1] / "app/services/generation_service.py"
tree = ast.parse(target.read_text(encoding="utf-8"))
method = next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "build_generation_request_envelope")
checks = {"story_control_authority_mismatch", "event_sequence_authority_mismatch", "pov_authority_mismatch"}
actual = {node.value for node in ast.walk(method) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
assert checks.issubset(actual), f"Missing authority checks: {checks - actual}"
assert sum(1 for node in ast.walk(method) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "build_project_local_generation_prompt") == 1
print("PRIMARY45D AUTHORITY CHANNEL CONSISTENCY PASS")
