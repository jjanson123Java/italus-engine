"""Behavioral Stage 1 regression: verify anchored event authority and provider projection."""
from __future__ import annotations
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app/services/generation_service.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_build_generation_guardrails"]
assert len(nodes) == 1, "Expected exact existing generation guardrails owner"
namespace = {"Any": object}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), namespace)
sidecar = {
    "book_number":1, "chapter_number":2,
    "chapter_execution_contract":{
        "required_event_sequence":[{
            "ordinal":1, "position":"opening", "chapter_role":"required",
            "relationship_to_anchor":"after", "objective":"Continue the approved sequence",
            "event_ref":{"record_id":"event-2","record_type":"event","label":"Authorized event"},
            "anchor_event_ref":{"record_id":"event-1","record_type":"event","label":"Prior anchor"},
        }],
        "required_participant_refs":[], "required_location_refs":[], "pov_contract":{},
    },
    "validator_sidecar":{}, "story_controls":[],
}
hard = namespace["_build_generation_guardrails"](sidecar)
event = hard["required_event_sequence"][0]
assert event["event_ref"]["record_id"] == "event-2"
assert event["anchor_event_ref"]["record_id"] == "event-1", "Anchor lost in hard provider authority"
assert event["anchor_event_ref"]["label"] == "Prior anchor"

# Exercise the actual projection owner with schema-shaped sidecar data.
sys.path.insert(0, str(ROOT))
from app.services import generation_knowledge_projection_service as projection
safe = projection.build_projection(
    sidecar, raw_chapter_text="", generation_guardrails=hard
)["projection"]
projected_event = safe["chapter_execution"]["required_event_sequence"][0]
assert projected_event["anchor"]["record_id"] == event["anchor_event_ref"]["record_id"]
assert projected_event["anchor"]["label"] == event["anchor_event_ref"]["label"]

# Existing projection must reject unsupported continuity categories before provider spend.
unsafe = dict(sidecar)
unsafe["continuity"] = {"required":True,"bounded_state":{"reveal_states":[
    {"book_number":1,"chapter_number":1,"future_reveal":"forbidden"}]}}
try:
    projection.build_projection(unsafe, raw_chapter_text="", generation_guardrails=hard)
except projection.GenerationKnowledgeProjectionError:
    pass
else:
    raise AssertionError("Unsupported reveal state reached provider authority")
print("PRIMARY45D STAGE1 BEHAVIORAL AUTHORITY PASS")
