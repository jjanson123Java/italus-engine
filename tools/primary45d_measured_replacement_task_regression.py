"""Primary 45D 3C-B1: rejected-draft metrics drive a new prompt without rewriting receipts."""
import copy
import hashlib
import json
from app.prompt_builder import build_project_local_generation_prompt, provider_user_prompt_text

def prompt_for(correction=None):
    projected = {
        "chapter_narrative_brief": {
            "chapter_objective": "Find the newly displaced stone.",
            "generation_kickoff": "Open with the child near the grove.",
            "chapter_plan_sha256": "a" * 64,
        },
        "chapter_disclosure_authority": [],
        "story_controls": [],
    }
    return build_project_local_generation_prompt(
        chapter_knowledge_text=json.dumps(projected),
        generation_guardrails={"story_controls": [], "hard_prose_metrics": {"word_count": {"minimum": 4000}}},
        target_words=4000,
        replacement_correction_context=correction,
    )

def main():
    baseline = prompt_for()
    assert "measured_prose_corrections" not in baseline["generation_task"]
    correction = {
        "source_generation_id": "gen_" + "1" * 32,
        "deterministic_failures": [
            {"rule_id": "word_count", "details": {"metric": "word_count", "measurement": 3028, "operator": ">=", "threshold": 4000}},
            {"rule_id": "em_dashes", "details": {"metric": "em_dashes", "measurement": 23, "operator": "<=", "threshold": 8}},
            {"rule_id": "unknown", "details": {"metric": "unscored", "measurement": "unverified", "operator": "<=", "threshold": 5}},
        ],
        "audited_semantic_failures": [],
    }
    original = copy.deepcopy(correction)
    prompt = prompt_for(correction)
    task = prompt["generation_task"]
    assert task["generation_mode"] == "replacement"
    assert task["replacement_for_generation_id"] == correction["source_generation_id"]
    actual = task["measured_prose_corrections"]
    assert len(actual) == 2, actual
    assert actual[0]["prior_measurement"] == 3028 and actual[0]["required_threshold"] == 4000
    assert actual[1]["prior_measurement"] == 23 and actual[1]["required_threshold"] == 8
    assert all(item["source_generation_id"] == correction["source_generation_id"] for item in actual)
    outgoing = provider_user_prompt_text(prompt)
    assert "measured_prose_corrections" in outgoing
    assert "chapter_objective" in outgoing
    assert correction == original
    assert prompt["provider_user_prompt_sha256"] == hashlib.sha256(outgoing.encode("utf-8")).hexdigest()
    assert "measured_prose_corrections" not in baseline["generation_task"]
    print("PRIMARY45D MEASURED REPLACEMENT TASK PASS")

if __name__ == "__main__":
    main()
