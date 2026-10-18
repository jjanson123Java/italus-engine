"""Primary 45D F3: one checked narrative assignment, no second free-text surface."""
import json
from app.prompt_builder import build_project_local_generation_prompt, provider_user_prompt_text

def run():
    brief = {
        "chapter_narrative_brief": {
            "chapter_objective": "Explore the boundary of the clearing.",
            "generation_kickoff": "Open with the child following tracks.",
            "chapter_plan_sha256": "a" * 64,
            "chapter_plan_revision": 3,
            "uncontrolled_extra_text": "SOURCE_ONLY_SENTINEL_NOT_AUTHORIZED_FOR_PROVIDER",
        },
        "chapter_disclosure_authority": [{"control_id": "one", "forbidden_claims": ["SECRET_FORBIDDEN_CLAIM"]}],
        "story_controls": [{"control_id": "one", "forbidden_assertions": ["SECRET_FORBIDDEN_CLAIM"], "knowledge_ceiling": "current chapter only"}],
    }
    guardrails = {"chapter_restrictions": ["SECRET_FORBIDDEN_CLAIM"],
                  "forbidden_future_knowledge": ["SECRET_FORBIDDEN_CLAIM"],
                  "story_controls": []}
    original = json.loads(json.dumps(brief))
    prompt = build_project_local_generation_prompt(
        chapter_knowledge_text=json.dumps(brief),
        generation_guardrails=guardrails, target_words=4000)
    outgoing = provider_user_prompt_text(prompt)
    task = prompt["generation_task"]
    assert task["chapter_objective"] == original["chapter_narrative_brief"]["chapter_objective"]
    assert task["generation_kickoff"] == original["chapter_narrative_brief"]["generation_kickoff"]
    assert task["chapter_plan_sha256"] == "a" * 64
    assert "chapter_narrative_brief" not in json.loads(prompt["reference_context"]["chapter_knowledge"]["text"])
    assert "SOURCE_ONLY_SENTINEL" not in outgoing
    assert "SECRET_FORBIDDEN_CLAIM" not in outgoing
    assert "current chapter only" in outgoing
    assert brief == original
    print("PRIMARY45D NARRATIVE SINGLE CHANNEL PASS")

if __name__ == "__main__":
    run()
