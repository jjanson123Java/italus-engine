"""Primary 45D: the existing execution method must reject replacement identity collisions pre-spend."""
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "app/services/provider_execution_service.py").read_text(encoding="utf-8")
module = ast.parse(source)
func = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "execute_provider_generation")
assign_idx = next(i for i,node in enumerate(func.body) if isinstance(node, ast.Assign) and any(isinstance(t,ast.Name) and t.id=="generation_id" for t in node.targets))
gate = func.body[assign_idx+1]
assert isinstance(gate,ast.If) and isinstance(gate.test,ast.Name) and gate.test.id=="replacement_enabled"
assert any(isinstance(node,ast.Raise) for node in ast.walk(gate))
call_idx = next(i for i,node in enumerate(func.body) if isinstance(node, ast.Try) and any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="get_receipt" for n in ast.walk(node)))
assert assign_idx + 1 < call_idx, "identity gate must execute before receipt lookup"
class Error(Exception):
    def __init__(self, code, message):
        self.code=code
        super().__init__(message)
ns={"ProviderExecutionError":Error}
compiled=compile(ast.fix_missing_locations(ast.Module(body=[gate],type_ignores=[])),"<replacement_guard>","exec")
def check(enabled, target, source_id, context_id, source_input, expect_error):
    scope=dict(ns,replacement_enabled=enabled,generation_id=target,replacement_source_generation_id=source_id,replacement_context={"context_sha256":context_id} if context_id else None,replacement_context_sha256=context_id,replacement_source=source_input)
    caught=None
    try:exec(compiled,scope)
    except Error as exc:caught=exc.code
    assert caught==expect_error, (scope,caught,expect_error)
check(False,"gen_one","", "", "",None)
check(True,"gen_new","gen_old","a"*64,"gen_old",None)
check(True,"gen_old","gen_old","a"*64,"gen_old","REPLACEMENT_EXECUTION_IDENTITY_CONFLICT")
check(True,"gen_new","gen_old","a"*64,"gen_wrong","REPLACEMENT_EXECUTION_IDENTITY_CONFLICT")
check(True,"gen_new","gen_old","","gen_old","REPLACEMENT_EXECUTION_IDENTITY_CONFLICT")
print("PRIMARY45D REPLACEMENT TRANSACTION IDENTITY GATE PASS")
