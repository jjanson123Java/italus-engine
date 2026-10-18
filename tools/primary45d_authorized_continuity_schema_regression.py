"""Primary 45D authorized continuity schema negative regression."""
from __future__ import annotations
import copy
from app.services import generation_knowledge_projection_service as projection

def run():
    sidecar = {
        "project_id": "p", "book_number": 1, "chapter_number": 2,
        "chapter_execution_contract": {}, "story_controls": [],
        "continuity": {"required": True, "bounded_state": {
            "established": [{"type": "reveal_established", "target_ref": "r1",
                             "book_number": 1, "chapter_number": 1,
                             "future_reveal": "DO_NOT_SEND"}]}},
    }
    result = projection.build_projection(sidecar, raw_chapter_text="",
                                         generation_guardrails={"chapter_restrictions": ["no future reveals"]})
    text = result["projection_text"]
    assert "DO_NOT_SEND" not in text
    assert '"target_ref":"r1"' in text
    for field in ("character_states", "relationship_states", "knowledge_states",
                  "event_states", "mission_states", "reveal_states"):
        unsafe = copy.deepcopy(sidecar)
        unsafe["continuity"]["bounded_state"][field] = [
            {"book_number": 1, "chapter_number": 1, "future_reveal": "DO_NOT_SEND"}]
        try:
            projection.build_projection(unsafe, raw_chapter_text="",
                                        generation_guardrails={"chapter_restrictions": ["no future reveals"]})
        except projection.GenerationKnowledgeProjectionError:
            pass
        else:
            raise AssertionError(f"Unapproved field {field} reached provider projection")
    print("PRIMARY45D AUTHORIZED CONTINUITY SCHEMA PASS")

if __name__ == "__main__":
    run()
