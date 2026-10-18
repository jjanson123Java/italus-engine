"""Primary 45D narrative free-text literal disclosure gate behavioral contract."""
import json
from app.prompt_builder import build_project_local_generation_prompt, provider_user_prompt_text

def run():
    brief = {"chapter_narrative_brief": {"chapter_objective": "Investigate the clearing.", "generation_kickoff": "Open beside the tree.", "chapter_plan_sha256": "a"*64}, "chapter_disclosure_authority": [{"control_id":"ctrl","forbidden_claims":["The sealed identity is the future guardian."]}], "story_controls":[]}
    guards = {"chapter_restrictions":["Do not reveal the hidden key."],"forbidden_future_knowledge":["Future keeper is immortal."],"story_controls":[{"control_id":"ctrl","forbidden_assertions":["Forbidden storm origin."]}]}
    prompt = build_project_local_generation_prompt(chapter_knowledge_text=json.dumps(brief), generation_guardrails=guards, target_words=4000)
    output = provider_user_prompt_text(prompt)
    assert "Investigate the clearing." in output and "Open beside the tree." in output
    assert "Future keeper is immortal." not in output
    for bad in ("The sealed identity is the future guardian.", "Do not reveal the hidden key.", "Future keeper is immortal.", "Forbidden storm origin."):
        for field in ("chapter_objective", "generation_kickoff"):
            test = json.loads(json.dumps(brief))
            test["chapter_narrative_brief"][field] += " "+bad
            try:
                build_project_local_generation_prompt(chapter_knowledge_text=json.dumps(test),generation_guardrails=guards,target_words=4000)
            except ValueError as exc:
                assert "protected disclosure" in str(exc), str(exc)
            else:
                raise AssertionError(f"Protected claim crossed via {field}")
    print("PRIMARY45D NARRATIVE LITERAL DISCLOSURE GATE PASS")

if __name__=="__main__":
    run()
