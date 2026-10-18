"""Exercise the real sidecar field expression from the installed compiler."""
import ast
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app/services/chapter_knowledge_pack_service.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
target = None
for node in ast.walk(tree):
    if isinstance(node, ast.Dict):
        keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
        if "chapter_narrative_source" in keys and "chapter_execution_contract" in keys:
            target = node.values[keys.index("chapter_narrative_source")]
            break
assert target is not None, "No chapter_narrative_source inside actual sidecar constructor"
expression = compile(ast.Expression(body=target), str(SOURCE), "eval")
for project, objective, kickoff in [
    ("test-project-one", "  Opening reveals a changed riverbank.  ", "  Begin with tracks.  "),
    ("test-project-two", "Chapter two begins a new inquiry.", "Open with dialogue."),
    ("no-text-project", "", ""),
]:
    chapter = {"chapter_objective": objective, "generation_kickoff": kickoff}
    status = {"source": {"chapter_plan_sha256": "a" * 64, "chapter_plan_revision": 7}}
    value = eval(expression, {"str": str}, {"chapter": chapter, "status": status})
    assert value["chapter_objective"] == objective.strip(), project
    assert value["generation_kickoff"] == kickoff.strip(), project
    assert value["chapter_plan_sha256"] == "a" * 64
    assert value["chapter_plan_revision"] == 7
    assert "forbidden_future_knowledge" not in value
print("PRIMARY45D NARRATIVE SOURCE SIDECAR PASS")
