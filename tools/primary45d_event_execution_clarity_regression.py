"""Behavioral check: event placement is explicit and no factual claims are invented."""
import importlib.util
import json
import pathlib
import sys
import types

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app import prompt_builder
from app.services import author_voice_projection_service

def run():
    events = [
        {"ordinal": 1, "position": "opening", "chapter_role": "mainline", "event": {"label": "Discovery"}},
        {"ordinal": 2, "position": "brief", "chapter_role": "analepsis", "event": {"label": "Historical storm"}},
    ]
    reference = {
        "authority": "reveal_safe_provider_reference",
        "chapter_execution": {
            "required_event_sequence": events,
            "pov_contract": {"pov_type": "third_person_limited", "authorized_characters": [{"label": "Character A"}]},
            "required_participants": [{"record_id": "a", "label": "Character A"}],
            "required_locations": [{"record_id": "l", "label": "Location B"}],
        },
        "chapter_narrative_brief": {"chapter_objective": "Current scene", "generation_kickoff": "Opening event", "chapter_plan_sha256": "abc"},
    }
    rules = {"hard_prose_metrics": {"word_count": {"minimum": 4000}}, "story_controls": []}
    result = prompt_builder.build_project_local_generation_prompt(
        chapter_knowledge_text=json.dumps(reference),
        generation_guardrails=rules,
        target_words=4000,
    )
    task = result["generation_task"]
    assert task["required_event_sequence"] == events
    assert task["pov_contract"] == reference["chapter_execution"]["pov_contract"]
    assert task["required_participants"] == reference["chapter_execution"]["required_participants"]
    assert "not a mainline character's personal memory" in task["event_placement_instruction"]
    assert "Do not change character" in task["event_placement_instruction"]
    assert task["chapter_objective"] == "Current scene"
    assert "Historical storm" in prompt_builder.provider_user_prompt_text(result)
    bad = dict(reference)
    bad["chapter_execution"] = {"required_event_sequence": [], "pov_contract": {}}
    try:
        prompt_builder.build_project_local_generation_prompt(
            chapter_knowledge_text=json.dumps(bad), generation_guardrails=rules, target_words=4000
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Missing execution contract must fail closed")
    print("PRIMARY45D EVENT EXECUTION CLARITY PASS")

if __name__ == "__main__":
    run()
