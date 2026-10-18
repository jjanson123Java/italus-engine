"""Primary 45D: continuity handoff must preserve chapter N-1, exclude N+."""
from __future__ import annotations
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root / "app/services/chapter_knowledge_pack_service.py").read_text(encoding="utf-8")
tree = ast.parse(source)
target = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == "_bounded_continuity_payload")
predicate = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == "_position_at_or_before")
scope = ast.Module(body=[target,predicate],type_ignores=[])
namespace={"Any":object,"deepcopy":__import__("copy").deepcopy,"_ALLOWED_CONTINUITY_KEYS":("established","knowledge_states","reveal_states")}
exec(compile(ast.fix_missing_locations(scope),str(root/"app/services/chapter_knowledge_pack_service.py"),"exec"),namespace)
f=namespace["_bounded_continuity_payload"]
data={"payload":{"established":[
    {"book_number":1,"chapter_number":1,"type":"event_established","target_ref":"PREVIOUS"},
    {"book_number":1,"chapter_number":2,"type":"event_established","target_ref":"CURRENT"},
    {"book_number":1,"chapter_number":3,"type":"event_established","target_ref":"FUTURE"},
    {"book_number":1,"type":"event_established","target_ref":"MISSING"},
]}}
assert [x["target_ref"] for x in f(data,book_number=1,chapter_number=2)["established"]] == ["PREVIOUS"]
assert f(data,book_number=1,chapter_number=1)["established"] == []
compiler = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=="compile_chapter_knowledge_pack") if any(isinstance(n,ast.FunctionDef) and n.name=="compile_chapter_knowledge_pack" for n in ast.walk(tree)) else None
calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="_bounded_continuity_payload"]
assert len(calls)==1
kwargs={k.arg:k.value for k in calls[0].keywords}
assert isinstance(kwargs["chapter_number"],ast.Name) and kwargs["chapter_number"].id=="chapter_number", "Compiler must pass current chapter; predicate applies strict prior-only cutoff"
print("PRIMARY45D CONTINUITY HANDOFF ALIGNMENT PASS")
