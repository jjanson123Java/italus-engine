from __future__ import annotations

import hashlib
import json

from app import prompt_builder


for project_id, book, chapter in (("project-alpine", 2, 3), ("project-maritime", 7, 13)):
    secret = f"UNRELEASED_SECRET_{project_id}_NOBODY_KNOWS"
    record = {
        "project_id": project_id,
        "book_number": book,
        "chapter_number": chapter,
        "chapter_disclosure_authority": [{
            "control_id": "control-safe",
            "control_type": "mystery_reveal",
            "book_number": book,
            "chapter_number": chapter,
            "permitted_claims": ["The traveler wears a blue coat."],
            "forbidden_claims": [secret],
        }],
        "story_controls": [{
            "control_id": "control-safe",
            "control_type": "mystery_reveal",
            "instruction": f"Keep the protected fact hidden: {secret}",
            "knowledge_ceiling": "Only the blue coat is known.",
            "allowed_interpretations": ["The traveler wears a blue coat."],
        }],
    }
    original = json.loads(json.dumps(record))
    guardrails = {
        "authority": "hard_generation_control",
        "chapter_restrictions": [secret],
        "forbidden_future_knowledge": [secret],
        "story_controls": [{
            "control_id": "control-safe",
            "control_type": "mystery_reveal",
            "instruction": f"Do not expose {secret}",
            "forbidden_assertions": [secret],
            "allowed_interpretations": ["The traveler wears a blue coat."],
            "knowledge_ceiling": "Only the blue coat is known.",
        }],
        "authority_rules": [f"Never say {secret}"],
        "hard_prose_metrics": {"word_count": {"minimum": 4000}},
    }
    correction = {
        "source_generation_id": "gen_prior",
        "audited_semantic_failures": [{
            "rule_id": "rule-11",
            "rule_type": "FORBIDDEN_FUTURE_KNOWLEDGE",
            "instruction": f"Do not reveal {secret}",
            "message": f"Earlier model disclosed {secret}",
            "semantic_validation_id": "semval-11",
            "semantic_receipt_sha256": "a" * 64,
        }],
        "instructions": [f"Do not mention {secret}"],
    }
    prompt = prompt_builder.build_project_local_generation_prompt(
        chapter_knowledge_text=json.dumps(record),
        generation_guardrails=guardrails,
        replacement_correction_context=correction,
        target_words=4000,
    )
    system = prompt_builder.provider_system_text(prompt)
    user = prompt_builder.provider_user_prompt_text(prompt)
    assert secret not in system and secret not in user
    assert "The traveler wears a blue coat." in user
    assert "Only the blue coat is known." in system
    assert record == original
    assert guardrails["forbidden_future_knowledge"] == [secret]
    assert correction["audited_semantic_failures"][0]["instruction"].endswith(secret)
    assert prompt["provider_system_sha256"] == hashlib.sha256(system.encode("utf-8")).hexdigest()
    assert prompt["provider_user_prompt_sha256"] == hashlib.sha256(user.encode("utf-8")).hexdigest()

print("PRIMARY45D GENERATOR DISCLOSURE SEPARATION PASS")
