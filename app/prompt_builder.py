"""Project-local provider prompt construction for the active Italus runtime.

Primary 41 permanently retired the pre-migration root-canon prompt builder and
legacy runner chain. Primary 42 bounds the provider-facing chapter request and
promotes hard chapter controls into provider system authority.
"""

from __future__ import annotations

import hashlib as _hashlib
import json as _json
from typing import Any


PROJECT_LOCAL_PROMPT_BUILDER_MARKER = (
    "project-local-prompt-builder-primary42-20260920"
)
PROJECT_LOCAL_PROMPT_SCHEMA_VERSION = "project_local_generation_prompt_v3"
PROVIDER_SYSTEM_SCHEMA_VERSION = "italus_provider_system_authority_v1"


def _canonical_json(value: Any) -> str:
    return _json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonicalize_project_local_generation_prompt(prompt: dict) -> str:
    """Return the deterministic provider-neutral prompt serialization."""

    canonical_payload = {
        "schema_version": prompt.get("schema_version"),
        "provider_system": prompt.get("provider_system"),
        "reference_context": prompt.get("reference_context"),
        "generation_task": prompt.get("generation_task"),
    }
    if "style_context" in prompt:
        canonical_payload["style_context"] = prompt.get("style_context")
    return _canonical_json(canonical_payload)


def provider_system_text(prompt: dict) -> str:
    """Render the exact hard-authority provider system instruction."""

    provider_system = prompt.get("provider_system")
    if not isinstance(provider_system, dict):
        raise ValueError("provider_system must be present")
    directive = str(provider_system.get("directive") or "").strip()
    guardrails = provider_system.get("generation_guardrails")
    if not directive:
        raise ValueError("provider_system.directive must not be empty")
    if not isinstance(guardrails, dict) or not guardrails:
        raise ValueError("provider_system.generation_guardrails must not be empty")
    rendered = (
        directive
        + "\n\nGENERATION_GUARDRAILS_JSON\n"
        + _canonical_json(guardrails)
    )
    correction = provider_system.get("replacement_correction_context")
    if isinstance(correction, dict) and correction:
        rendered += (
            "\n\nREPLACEMENT_CORRECTION_CONTEXT_JSON\n"
            + _canonical_json(correction)
        )
    return rendered


def provider_user_prompt_text(prompt: dict) -> str:
    """Render the exact provider user message without duplicating system authority."""

    payload = {
        "schema_version": prompt.get("schema_version"),
        "service": prompt.get("service"),
        "reference_context": prompt.get("reference_context"),
        "style_context": prompt.get("style_context"),
        "generation_task": prompt.get("generation_task"),
    }
    return _canonical_json(payload)


def build_project_local_generation_prompt(
    *,
    chapter_knowledge_text: str,
    generation_guardrails: dict,
    target_words: int,
    author_voice_projection: dict | None = None,
    replacement_correction_context: dict | None = None,
) -> dict:
    """Build one bounded chapter prompt with explicit provider system authority.

    The full Book Knowledge artifact remains an upstream lineage dependency of
    Chapter Knowledge, but its raw text is intentionally excluded from provider
    input. Chapter Knowledge is the bounded narrative reference. Hard chapter
    restrictions, reveal boundaries, Story Controls, execution requirements,
    POV rules, and quantitative prose limits are repeated under provider system
    authority so they outrank reference material and style preferences.
    """

    chapter_text = str(chapter_knowledge_text or "")
    target = int(target_words or 0)
    guardrails = dict(generation_guardrails or {})
    correction = dict(replacement_correction_context or {})

    if not chapter_text.strip():
        raise ValueError("chapter_knowledge_text must not be empty")
    if not guardrails:
        raise ValueError("generation_guardrails must not be empty")
    if target <= 0:
        raise ValueError("target_words must be a positive integer")

    from app.services import author_voice_projection_service

    author_voice_style = (
        author_voice_projection_service.prompt_safe_author_voice_style_context(
            author_voice_projection
        )
    )

    directive = (
        "You are generating prose for the Italus application. The following "
        "generation guardrails are hard system-level constraints for this exact "
        "book/chapter position. They override any conflicting or broader fact "
        "that may appear in reference material or style guidance. The presence "
        "of a fact in reference material does not authorize disclosure. Never "
        "reveal, explain, foreshadow, or infer information prohibited by "
        "chapter_restrictions, forbidden_future_knowledge, or Story Controls. "
        "Execute required events in their stated order and placement, use only "
        "authorized POV/interior access, and obey hard prose limits. Treat "
        "Author Voice only as a soft style preference. Before returning prose, "
        "self-check the hard quantitative limits and revise any violation. "
        "Return chapter prose only; do not return compliance commentary. If the "
        "hard controls are genuinely contradictory, report the conflict rather "
        "than inventing authority."
    )

    provider_system = {
        "schema_version": PROVIDER_SYSTEM_SCHEMA_VERSION,
        "authority": "hard_generation_control",
        "precedence": [
            "generation_guardrails",
            "chapter_reference_context",
            "author_voice_style",
        ],
        "directive": directive,
        "generation_guardrails": guardrails,
    }
    if correction:
        provider_system["precedence"] = [
            "generation_guardrails",
            "replacement_correction_context",
            "chapter_reference_context",
            "author_voice_style",
        ]
        provider_system["replacement_correction_context"] = correction

    generation_task = {
        "task": "draft_chapter_prose",
        "target_words": target,
        "output_content_type": "text/plain",
    }
    if correction:
        generation_task["generation_mode"] = "replacement"
        generation_task["replacement_for_generation_id"] = str(
            correction.get("source_generation_id") or ""
        )

    prompt = {
        "schema_version": PROJECT_LOCAL_PROMPT_SCHEMA_VERSION,
        "service": PROJECT_LOCAL_PROMPT_BUILDER_MARKER,
        "provider_system": provider_system,
        "reference_context": {
            "authority": "bounded_chapter_reference_only",
            "chapter_knowledge": {
                "content_type": "text/markdown",
                "text": chapter_text,
            },
            "book_knowledge_raw_text_included": False,
        },
        "style_context": {
            "authority": "soft_style_preference_only",
            "author_voice": author_voice_style,
        },
        "generation_task": generation_task,
    }

    system_text = provider_system_text(prompt)
    user_text = provider_user_prompt_text(prompt)
    canonical = canonicalize_project_local_generation_prompt(prompt)

    prompt["provider_system_sha256"] = _hashlib.sha256(
        system_text.encode("utf-8")
    ).hexdigest()
    prompt["provider_user_prompt_sha256"] = _hashlib.sha256(
        user_text.encode("utf-8")
    ).hexdigest()
    prompt["prompt_sha256"] = _hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    return prompt
