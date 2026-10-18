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
    "project-local-prompt-builder-primary45c-20261003"
)
PROJECT_LOCAL_PROMPT_SCHEMA_VERSION = "project_local_generation_prompt_v4"
PROVIDER_SYSTEM_SCHEMA_VERSION = "italus_provider_system_authority_v2"


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

    Book and Chapter Knowledge remain upstream lineage authorities, but their raw
    text is intentionally excluded from provider input. The supplied reference is
    a reveal-safe generation projection built from the exact chapter sidecar. Hard chapter
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
        "book/chapter position. They override any conflicting style guidance. "
        "The reference context is a reveal-safe projection. Missing facts are "
        "intentionally withheld and must not be inferred, reconstructed, or invented. Never "
        "reveal, explain, foreshadow, or infer information beyond "
        "affirmatively permitted chapter authority and Story Controls. "
        "Dramatize required_authorized_beats from active Story Controls as concrete "
        "on-page actions or observations when their subject appears; do not replace "
        "scene requirements with later exposition or infer unapproved details. "
        "Execute required events in their stated order and placement, use only "
        "authorized POV/interior access, and obey hard prose limits. Treat "
        "Author Voice only as a soft style preference. Before returning prose, "
        "follow the hard quantitative limits. "
        "Do not include a chapter title, section headings, or decorative scene separators. "
        "Avoid em dashes and colons in narrative prose; use ordinary punctuation. "
        "Return chapter prose only; do not return compliance commentary. If the "
        "hard controls are genuinely contradictory, report the conflict rather "
        "than inventing authority."
    )

    # Provider receives chapter-authorized positive controls only. Full negative
    # authority remains in the compiler sidecar and semantic validator; never
    # serialize validator-only future revelations into the generative channel.
    provider_guardrails = dict(guardrails)
    provider_guardrails.pop("chapter_restrictions", None)
    provider_guardrails.pop("forbidden_future_knowledge", None)
    provider_controls = []
    for item in guardrails.get("story_controls") or []:
        if not isinstance(item, dict):
            raise ValueError("Story Control must be a structured authority record.")
        # Only explicitly approved interpretations are executable scene beats.
        # The free-text instruction can mix approved beats and future secrets.
        allowed = item.get("allowed_interpretations")
        if not isinstance(allowed, list) or not all(
            isinstance(claim, str) and claim.strip() for claim in allowed
        ):
            raise ValueError("Story Control approved claims must be explicit.")
        provider_controls.append({
            **{
                key: value for key, value in item.items()
                if key not in ("forbidden_assertions", "instruction")
            },
            "required_authorized_beats": list(allowed),
        })
    provider_guardrails["story_controls"] = provider_controls
    provider_guardrails["authority_rules"] = [
        "Use only affirmatively chapter-authorized story facts and interpretations.",
        "Do not infer unprovided background, identities, motives, or future developments.",
        "Treat the chapter-specific knowledge ceiling as a hard narrative boundary.",
    ]
    provider_correction = dict(correction)
    if correction:
        failures = []
        for item in correction.get("audited_semantic_failures") or []:
            if not isinstance(item, dict) or not str(item.get("rule_id") or ""):
                raise ValueError("Audited semantic failure identity is invalid.")
            failures.append({
                "rule_id": str(item["rule_id"]),
                "rule_type": str(item.get("rule_type") or ""),
                "message": "Prior draft violated chapter authority; do not extend beyond authorized positive story scope.",
                "semantic_validation_id": str(item.get("semantic_validation_id") or ""),
                "semantic_receipt_sha256": str(item.get("semantic_receipt_sha256") or ""),
            })
        provider_correction["audited_semantic_failures"] = failures
        provider_correction["instructions"] = [
            "Write a new draft using only the current affirmative chapter authority.",
            "Correct measured deterministic prose defects from the rejected source.",
            "Do not use unprovided future-story claims or infer unknown facts.",
        ]
    provider_system = {
        "schema_version": PROVIDER_SYSTEM_SCHEMA_VERSION,
        "authority": "hard_generation_control",
        "precedence": [
            "generation_guardrails",
            "chapter_reference_context",
            "author_voice_style",
        ],
        "directive": directive,
        "generation_guardrails": provider_guardrails,
    }
    if correction:
        provider_system["precedence"] = [
            "generation_guardrails",
            "replacement_correction_context",
            "chapter_reference_context",
            "author_voice_style",
        ]
        provider_system["replacement_correction_context"] = provider_correction

    generation_task = {
        "task": "draft_chapter_prose",
        "target_words": target,
        "output_content_type": "text/plain",
    }
    # Surface compiler-authorized planning text as a directly readable writing
    # assignment. The source-bound reveal-safe projection remains authoritative.
    try:
        projected_reference = _json.loads(chapter_text)
    except _json.JSONDecodeError as exc:
        raise ValueError("Chapter projection must be valid JSON.") from exc
    if not isinstance(projected_reference, dict):
        raise ValueError("Chapter projection must be a JSON object.")
    # The complete validated projection remains internal. A separate provider
    # view omits sensitive negative disclosure descriptions rather than feeding
    # the generator the secrets it is instructed not to disclose.
    provider_reference = dict(projected_reference)
    hidden_names = provider_reference.pop("hidden_character_names", [])
    hidden_presentations = provider_reference.pop("hidden_character_presentations", [])
    if not isinstance(hidden_presentations, list):
        raise ValueError("Invalid hidden-character presentation contract.")
    if (
        not isinstance(hidden_names, list)
        or any(not isinstance(name, str) or not name.strip() or len(name) > 200
               for name in hidden_names)
    ):
        raise ValueError("Invalid selected character name-visibility contract.")
    # Presentation permissions remain internal: provider receives only the
    # approved words, never canonical-name-to-alias identity mappings.
    presentation_replacements = {}
    event_presentation_guidance = []
    optional_general_presentations = []
    required_sequence = (
        (provider_reference.get("chapter_execution") or {}).get("required_event_sequence") or []
    )
    for item in hidden_presentations:
        if not isinstance(item, dict):
            raise ValueError("Invalid hidden-character presentation item.")
        canonical_name = str(item.get("canonical_name") or "").strip()
        if canonical_name not in hidden_names:
            raise ValueError("Presentation belongs to an unselected/visible character.")
        alias = item.get("presentation_name", "")
        overrides = item.get("event_presentations", [])
        if not isinstance(alias, str) or len(alias.strip()) > 80 or not isinstance(overrides, list):
            raise ValueError("Invalid chapter presentation.")
        if alias.strip().casefold() in {name.casefold() for name in hidden_names}:
            raise ValueError("Presentation cannot reproduce a hidden Canon name.")
        # With event-specific overrides, never globalize the chapter alias;
        # the same character may be anonymous under different descriptions.
        presentation_replacements[canonical_name] = (
            alias.strip() if alias.strip() and not overrides else "an unidentified person"
        )
        if alias.strip() and overrides:
            # Mixed chapter/event aliases never globally rewrite event text:
            # that could connect two intentionally separate appearances.
            optional_general_presentations.append(alias.strip())
        for override in overrides:
            if not isinstance(override, dict):
                raise ValueError("Invalid event presentation.")
            event_id = str(override.get("event_id") or "")
            description = str(override.get("presentation") or "").strip()
            if (not description or len(description) > 80
                    or description.casefold() in {name.casefold() for name in hidden_names}):
                raise ValueError("Invalid event-specific presentation label.")
            for index, event in enumerate(required_sequence):
                if str((event.get("event") or {}).get("record_id") or "") == event_id:
                    if any(
                        guidance["event_ordinal"] == index + 1
                        for guidance in event_presentation_guidance
                    ):
                        raise ValueError(
                            "Multiple hidden-character presentations for one event are ambiguous."
                        )
                    event_presentation_guidance.append({
                        "event_ordinal": index + 1,
                        "presentation": description,
                    })
                    break
            else:
                raise ValueError("Event presentation references an unselected event.")
    if optional_general_presentations:
        provider_guardrails["optional_general_presentations"] = optional_general_presentations
        generation_task["optional_general_presentations"] = optional_general_presentations
        provider_guardrails["general_presentation_rule"] = (
            "Use chapter-wide presentation names only where applicable and "
            "not in events with a stricter event-specific description."
        )
    if event_presentation_guidance:
        provider_guardrails["event_presentation_rule"] = (
            "Use the listed descriptions only in their corresponding ordered events. "
            "Do not infer or disclose an identity connection between separate appearances."
        )
        generation_task["event_presentation_rule"] = (
            "Apply each approved description only to its indicated event; "
            "other events use their independently authorized narrative context."
        )
        provider_guardrails["approved_event_presentations"] = event_presentation_guidance
        generation_task["approved_event_presentations"] = event_presentation_guidance
    # Preserve only the projection's positively authorized, selected Canon
    # writing profiles. Do not infer facts from labels or mixed Canon prose.
    canon_profiles = projected_reference.get("chapter_safe_canon_facts") or []
    if not isinstance(canon_profiles, list):
        raise ValueError("Invalid chapter-safe Canon contract.")
    for profile in canon_profiles:
        if not isinstance(profile, dict):
            raise ValueError("Invalid chapter-safe Canon profile.")
        facts = profile.get("approved_facts")
        if (
            not str(profile.get("record_id") or "").strip()
            or not isinstance(facts, list) or not facts
            or not all(isinstance(fact, str) and fact.strip() for fact in facts)
        ):
            raise ValueError("Missing approved chapter-safe Canon facts.")
    # Positive-only profiles are executable writing constraints in both
    # provider channels. They originate in selected, chapter-scoped permissions,
    # never unrestricted Character Bible or mixed Story Control instructions.
    if canon_profiles:
        provider_guardrails["required_authorized_canon_facts"] = canon_profiles
        generation_task["required_authorized_canon_facts"] = canon_profiles
    projected_disclosures = []
    for record in projected_reference.get("chapter_disclosure_authority") or []:
        if not isinstance(record, dict):
            raise ValueError("Invalid chapter disclosure contract.")
        projected_disclosures.append({
            key: value for key, value in record.items()
            if key != "forbidden_claims"
        })
    provider_reference["chapter_disclosure_authority"] = projected_disclosures
    provider_story_controls = []
    for control in projected_reference.get("story_controls") or []:
        if not isinstance(control, dict):
            raise ValueError("Invalid provider Story Control.")
        # The projection's permitted claims are the disclosure ceiling.
        # Do not transmit free-text instructions containing validator-only facts.
        allowed = control.get("allowed_interpretations")
        if not isinstance(allowed, list) or not all(
            isinstance(claim, str) and claim.strip() for claim in allowed
        ):
            raise ValueError("Provider Story Control approved claims must be explicit.")
        provider_story_controls.append({
            **{
                key: value for key, value in control.items()
                if key not in ("forbidden_assertions", "instruction")
            },
            "required_authorized_beats": list(allowed),
        })
    provider_reference["story_controls"] = provider_story_controls
    narrative_brief = projected_reference.get("chapter_narrative_brief")
    if narrative_brief is not None:
        if not isinstance(narrative_brief, dict):
            raise ValueError("Chapter narrative brief must be an object.")
        objective = narrative_brief.get("chapter_objective")
        kickoff = narrative_brief.get("generation_kickoff")
        if not isinstance(objective, str) or not objective.strip() or not isinstance(kickoff, str) or not kickoff.strip():
            raise ValueError("Chapter narrative brief lacks source-authored content.")
        # Free-text author planning is a separate disclosure surface from
        # structured Story Controls. Reject exact protected claims before the
        # provider is contacted; keep the complete claims in validator inputs.
        protected_claims = []
        for restriction in guardrails.get("chapter_restrictions") or []:
            if isinstance(restriction, str) and restriction.strip():
                protected_claims.append(restriction)
            elif isinstance(restriction, dict):
                for key in ("instruction", "forbidden_assertion", "forbidden_claim", "text"):
                    value = restriction.get(key)
                    if isinstance(value, str) and value.strip():
                        protected_claims.append(value)
        for claim in guardrails.get("forbidden_future_knowledge") or []:
            if isinstance(claim, str) and claim.strip():
                protected_claims.append(claim)
            elif isinstance(claim, dict):
                for key in ("claim", "text", "assertion"):
                    value = claim.get(key)
                    if isinstance(value, str) and value.strip():
                        protected_claims.append(value)
        for control in guardrails.get("story_controls") or []:
            if isinstance(control, dict):
                protected_claims.extend(
                    value for value in control.get("forbidden_assertions") or []
                    if isinstance(value, str) and value.strip()
                )
        for disclosure in projected_reference.get("chapter_disclosure_authority") or []:
            if isinstance(disclosure, dict):
                protected_claims.extend(
                    value for value in disclosure.get("forbidden_claims") or []
                    if isinstance(value, str) and value.strip()
                )
        # Compare protected *claims*, not instruction verbs or bare character
        # labels. Canonical token runs detect punctuation/whitespace variations;
        # high-coverage claim token sets also detect reordered wording. This is
        # intentionally conservative lexical protection, not semantic approval.
        import re

        for candidate in (objective, kickoff):
            candidate_tokens = re.findall(r"\w+", candidate.casefold())
            candidate_set = set(candidate_tokens)
            for protected in protected_claims:
                claim_tokens = re.findall(r"\w+", protected.casefold())
                if not claim_tokens:
                    continue
                exact_run = any(
                    candidate_tokens[index:index + len(claim_tokens)] == claim_tokens
                    for index in range(max(0, len(candidate_tokens) - len(claim_tokens) + 1))
                )
                # Block reordered disclosures only when a meaningful majority
                # of a long protected assertion appears in the authored brief.
                # Single words and short generic restrictions cannot authorize
                # a semantic rejection.
                material_tokens = {
                    token for token in claim_tokens
                    if len(token) >= 5 and token not in {
                        "about", "after", "before", "chapter", "could", "should",
                        "there", "their", "these", "those", "which", "would",
                        "never", "reveal", "avoid", "future", "story", "knowledge",
                    }
                }
                reordered_claim = (
                    len(material_tokens) >= 3
                    and len(material_tokens & candidate_set) / len(material_tokens) >= 0.80
                )
                if exact_run or reordered_claim:
                    raise ValueError(
                        "Chapter narrative brief contains validator-only protected disclosure."
                    )
        generation_task["chapter_objective"] = objective
        generation_task["generation_kickoff"] = kickoff
        generation_task["chapter_plan_sha256"] = str(narrative_brief.get("chapter_plan_sha256") or "")
        # The verified assignment has one provider-facing owner: generation_task.
        # Do not also serialize the full source brief into reference_context,
        # where optional free-text metadata can evade the two-field claim check.
        provider_reference.pop("chapter_narrative_brief", None)

    # Directly surface the existing, chapter-authorized execution contract as
    # the writing task rather than leaving chronology and POV buried in JSON.
    # No Canon facts are inferred, invented, or imported from unrestricted text.
    execution = provider_reference.get("chapter_execution")
    # Legacy reveal-safe projections can omit this optional contract entirely.
    # Preserve their single-channel narrative brief. If authority is supplied,
    # it must be complete and valid: never silently discard malformed data.
    if execution is not None:
        if not isinstance(execution, dict):
            raise ValueError("Provider projection has invalid chapter execution authority.")
        events = execution.get("required_event_sequence")
        pov = execution.get("pov_contract")
        if not isinstance(events, list) or not events or not isinstance(pov, dict):
            raise ValueError("Provider projection lacks event and POV authority.")
        generation_task["required_event_sequence"] = events
        generation_task["pov_contract"] = pov
        generation_task["required_participants"] = execution.get("required_participants") or []
        generation_task["required_locations"] = execution.get("required_locations") or []
        generation_task["event_placement_instruction"] = (
            "Follow each event's documented chapter position, role, anchor and "
            "relationship to the mainline. An external historical flashback is "
            "not a mainline character's personal memory unless the chapter "
            "authority explicitly permits that knowledge. Do not change character "
            "ages, identities, species, relationships, dates, or event witnesses "
            "to join separate historical periods. Do not invent any missing facts."
        )

    if correction:
        generation_task["generation_mode"] = "replacement"
        generation_task["replacement_for_generation_id"] = str(
            correction.get("source_generation_id") or ""
        )
        # Use the exact rejected candidate's backend validation evidence to
        # make the replacement's measurable defects explicit.  This is a NEW
        # generation, not an in-place rewrite of an immutable provider receipt.
        measured_corrections = []
        for failure in correction.get("deterministic_failures") or []:
            if not isinstance(failure, dict):
                raise ValueError("Replacement deterministic failure must be an object.")
            details = failure.get("details")
            details = details if isinstance(details, dict) else {}
            metric = str(details.get("metric") or "").strip()
            measurement = details.get("measurement")
            threshold = details.get("threshold")
            operator = str(details.get("operator") or "").strip()
            if not metric:
                # Legacy rule reports can describe a failure without a measured
                # threshold. Preserve the source evidence; never invent a target.
                continue
            if not isinstance(measurement, (int, float)) or isinstance(measurement, bool):
                continue
            if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
                continue
            if operator not in ("<", "<=", ">", ">=", "=="):
                continue
            measured_corrections.append({
                "metric": metric,
                "prior_measurement": measurement,
                "required_operator": operator,
                "required_threshold": threshold,
                "source_generation_id": generation_task["replacement_for_generation_id"],
            })
        if measured_corrections:
            generation_task["measured_prose_corrections"] = measured_corrections
            generation_task["measured_correction_instruction"] = (
                "Produce a fully new chapter draft. Meet every listed numeric "
                "threshold while following the current chapter authority; "
                "the application will measure and revalidate the returned prose."
            )

    prompt = {
        "schema_version": PROJECT_LOCAL_PROMPT_SCHEMA_VERSION,
        "service": PROJECT_LOCAL_PROMPT_BUILDER_MARKER,
        "provider_system": provider_system,
        "reference_context": {
            "authority": "reveal_safe_generation_projection_only",
            "chapter_knowledge": {
                "content_type": "application/json",
                "text": _json.dumps(provider_reference, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                "source_kind": "reveal_safe_generation_projection",
                "raw_chapter_knowledge_included": False,
            },
            "book_knowledge_raw_text_included": False,
        },
        "style_context": {
            "authority": "soft_style_preference_only",
            "author_voice": author_voice_style,
        },
        "generation_task": generation_task,
    }

    # The author's Canon remains unchanged. Suppress selected hidden names from
    # EVERY provider-bound surface, including event labels, free-text kickoff,
    # corrected prompts, profile facts, and nested reference JSON.
    # No canonical name or forbidden-name list is transmitted to the provider.
    if hidden_names:
        import re as _re
        expressions = [
            (
                _re.compile(r"(?<!\w)" + _re.escape(name) + r"(?!\w)", _re.IGNORECASE),
                presentation_replacements.get(name, "an unidentified person"),
            )
            for name in sorted(hidden_names, key=len, reverse=True)
        ]
        pending = [prompt]
        while pending:
            current = pending.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    if isinstance(value, str):
                        for expression, replacement in expressions:
                            value = expression.sub(lambda _match: replacement, value)
                        current[key] = value
                    elif isinstance(value, (dict, list)):
                        pending.append(value)
            elif isinstance(current, list):
                for index, value in enumerate(current):
                    if isinstance(value, str):
                        for expression, replacement in expressions:
                            value = expression.sub(lambda _match: replacement, value)
                        current[index] = value
                    elif isinstance(value, (dict, list)):
                        pending.append(value)

    system_text = provider_system_text(prompt)
    user_text = provider_user_prompt_text(prompt)
    for hidden_name in hidden_names:
        import re as _re
        name_pattern = _re.compile(r"(?<!\w)" + _re.escape(hidden_name) + r"(?!\w)", _re.IGNORECASE)
        if name_pattern.search(system_text) or name_pattern.search(user_text):
            raise ValueError("Hidden character canonical name reached provider request.")
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
