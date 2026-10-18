"""Primary 45D F2 lexical free-text disclosure boundary regression."""
import json
from app.prompt_builder import build_project_local_generation_prompt, provider_user_prompt_text

def main():
    brief = {"chapter_narrative_brief": {
        "chapter_objective": "Investigate the clearing and its strange tracks.",
        "generation_kickoff": "Open beside the ancient tree.",
        "chapter_plan_sha256": "a" * 64},
        "chapter_disclosure_authority": [{"control_id": "ctrl",
            "forbidden_claims": ["The concealed guardian possesses an ancient immortal identity."]}],
        "story_controls": []}
    guards = {"chapter_restrictions": ["Never reveal the concealed passage."],
              "forbidden_future_knowledge": ["The ancient forest keeper secretly knows the immortal origin."],
              "story_controls": [{"control_id": "ctrl",
                                  "forbidden_assertions": ["The hidden keeper is the last guardian."]}]}
    def build(b):
        return build_project_local_generation_prompt(
            chapter_knowledge_text=json.dumps(b), generation_guardrails=guards, target_words=4000)
    good = provider_user_prompt_text(build(brief))
    assert "Investigate the clearing" in good
    assert "ancient immortal identity" not in good
    tests = [
        "The concealed guardian, possesses an ancient immortal identity!",
        "An ancient immortal identity belongs to the concealed guardian.",
        "Never, reveal the concealed passage.",
        "The guardian is the hidden keeper, last.",
    ]
    for sentence in tests:
        for field in ("chapter_objective", "generation_kickoff"):
            altered = json.loads(json.dumps(brief))
            altered["chapter_narrative_brief"][field] += " " + sentence
            try:
                build(altered)
            except ValueError as exc:
                assert "protected disclosure" in str(exc), str(exc)
            else:
                raise AssertionError(f"Protected phrasing admitted: {field}: {sentence}")
    print("PRIMARY45D NARRATIVE LEXICAL DISCLOSURE BOUNDARY PASS")

if __name__ == "__main__":
    main()
