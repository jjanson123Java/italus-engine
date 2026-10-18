from __future__ import annotations

import json

from app import prompt_builder


def build(reference):
    return prompt_builder.build_project_local_generation_prompt(
        chapter_knowledge_text=json.dumps(reference, sort_keys=True),
        generation_guardrails={"authority": "hard_generation_control"},
        target_words=4000,
    )


for project_id, book, chapter in (("test-north", 2, 7), ("test-south", 4, 19)):
    ref = {
        "project_id": project_id,
        "book_number": book,
        "chapter_number": chapter,
        "chapter_narrative_brief": {
            "chapter_objective": f"Objective for {project_id}: scene and dialogue.",
            "generation_kickoff": f"Begin from source events in book {book}.",
            "chapter_plan_sha256": "a" * 64,
            "chapter_plan_revision": 3,
        },
    }
    prompt = build(ref)
    task = prompt["generation_task"]
    assert task["chapter_objective"] == ref["chapter_narrative_brief"]["chapter_objective"]
    assert task["generation_kickoff"] == ref["chapter_narrative_brief"]["generation_kickoff"]
    assert task["chapter_plan_sha256"] == "a" * 64
    system = prompt_builder.provider_system_text(prompt)
    assert "Do not include a chapter title" in system
    assert "Avoid em dashes and colons" in system

legacy = build({"project_id": "legacy"})
assert "chapter_objective" not in legacy["generation_task"]
assert "generation_kickoff" not in legacy["generation_task"]

for invalid in ({"chapter_objective": "a", "generation_kickoff": ""},
                {"chapter_objective": 123, "generation_kickoff": "text"}):
    try:
        build({"chapter_narrative_brief": invalid})
    except ValueError:
        pass
    else:
        raise AssertionError("Missing or malformed authored brief was accepted.")

print("PRIMARY45D EXECUTION BRIEF PASS")
