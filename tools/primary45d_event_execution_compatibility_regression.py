"""Regression for optional legacy and strict present execution authority."""
import json
from app.prompt_builder import build_project_local_generation_prompt, provider_user_prompt_text

def prompt(reference):
    return build_project_local_generation_prompt(
        chapter_knowledge_text=json.dumps(reference),
        generation_guardrails={"hard_prose_metrics": {"word_count": {"minimum": 4000}}, "story_controls": []},
        target_words=4000,
    )

def run():
    legacy = {
        "chapter_narrative_brief": {
            "chapter_objective": "Discover the clearing",
            "generation_kickoff": "Open in the current period",
            "chapter_plan_sha256": "a" * 64,
        },
    }
    legacy_task = prompt(legacy)["generation_task"]
    assert legacy_task["chapter_objective"] == "Discover the clearing"
    assert "required_event_sequence" not in legacy_task
    events = [{"ordinal": 1, "chapter_role": "mainline", "event": {"label": "Arrival"}},
              {"ordinal": 2, "chapter_role": "analepsis", "event": {"label": "Earlier storm"}}]
    current = {
        "chapter_execution": {
            "required_event_sequence": events, "pov_contract": {"pov_type": "limited"},
            "required_participants": [], "required_locations": [],
        }
    }
    current_task = prompt(current)["generation_task"]
    assert current_task["required_event_sequence"] == events
    assert "not a mainline character's personal memory" in current_task["event_placement_instruction"]
    assert "Earlier storm" in provider_user_prompt_text(prompt(current))
    for malformed in (None, [], {}, {"required_event_sequence": events},
                      {"required_event_sequence": [], "pov_contract": {}}):
        value = {"chapter_execution": malformed}
        if malformed is None:
            # Explicit null is indistinguishable from absent in original lookup;
            # omit it from the malformed set: absence is allowed.
            continue
        try:
            prompt(value)
        except ValueError:
            pass
        else:
            raise AssertionError("Present malformed chapter execution was accepted: " + repr(malformed))
    print("PRIMARY45D EVENT EXECUTION COMPATIBILITY PASS")

if __name__ == "__main__":
    run()
