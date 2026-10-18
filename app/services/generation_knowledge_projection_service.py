"""Reveal-safe provider projection for one exact generation position.

Master/Chapter Knowledge remains authoritative upstream state. This service
creates the only narrative reference text allowed into provider input. It uses
the chapter sidecar's already-bounded execution/reveal contracts and never
copies the raw Chapter Knowledge markdown or full Canon records.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SERVICE_MARKER = "primary45c-reveal-safe-generation-projection-v1"
SCHEMA_VERSION = "generation_knowledge_projection_v1"


class GenerationKnowledgeProjectionError(RuntimeError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_refs(values: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if not isinstance(values, list):
        raise GenerationKnowledgeProjectionError(
            "Chapter reference collection must be a list."
        )
    for item in values:
        if not isinstance(item, dict) or not str(item.get("record_id") or "").strip():
            raise GenerationKnowledgeProjectionError(
                "Chapter reference is missing a valid record identity."
            )
        result.append({
            "record_id": str(item.get("record_id") or ""),
            "record_type": str(item.get("record_type") or ""),
            "label": str(item.get("label") or ""),
        })
    return result


def _safe_story_controls(values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        result.append({
            "control_id": str(item.get("control_id") or ""),
            "control_type": str(item.get("control_type") or ""),
            "knowledge_ceiling": str(item.get("knowledge_ceiling") or ""),
            "instruction": str(item.get("instruction") or ""),
            "allowed_interpretations": [
                str(v) for v in (item.get("allowed_interpretations") or []) if str(v).strip()
            ],
            "certainty": str(item.get("certainty") or ""),
            "presentation": str(item.get("presentation") or ""),
            "narrative_weight": str(item.get("narrative_weight") or ""),
        })
    return result


def _safe_event_sequence(values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in values if isinstance(values, list) else []:
        if not isinstance(item, dict):
            continue
        event = item.get("event_ref") if isinstance(item.get("event_ref"), dict) else {}
        anchor = item.get("anchor_event_ref") if isinstance(item.get("anchor_event_ref"), dict) else {}
        result.append({
            "ordinal": int(item.get("ordinal") or 0),
            "position": str(item.get("position") or ""),
            "chapter_role": str(item.get("chapter_role") or ""),
            "relationship_to_anchor": str(item.get("relationship_to_anchor") or ""),
            "objective": str(item.get("objective") or ""),
            "event": {
                "record_id": str(event.get("record_id") or ""),
                "label": str(event.get("label") or ""),
            },
            "anchor": {
                "record_id": str(anchor.get("record_id") or ""),
                "label": str(anchor.get("label") or ""),
            } if anchor else {},
        })
    return result


def _safe_pov(value: Any) -> dict[str, Any]:
    pov = value if isinstance(value, dict) else {}
    return {
        "configured": pov.get("configured") is True,
        "pov_type": str(pov.get("pov_type") or ""),
        "pov_type_label": str(pov.get("pov_type_label") or ""),
        "narrator_scope": str(pov.get("narrator_scope") or ""),
        "interior_access": str(pov.get("interior_access") or ""),
        "head_hopping": str(pov.get("head_hopping") or ""),
        "omniscient_style": str(pov.get("omniscient_style") or ""),
        "authorized_characters": _safe_refs(pov.get("character_refs") or []),
        "prompt_rules": [
            str(v) for v in (pov.get("prompt_rules") or []) if str(v).strip()
        ],
    }


def _sensitive_literals_from_raw(
    raw_chapter_text: str,
    *,
    subject_labels: list[str],
    chapter_restrictions: list[str],
) -> list[str]:
    """Extract obvious exact age/birth literals only for preflight leak detection.

    The literals never enter provider input; they are local guard material.
    """
    restriction_text = " ".join(chapter_restrictions).lower()
    if not any(term in restriction_text for term in ("exact age", "birth", "born", "lifespan")):
        return []

    labels = [label for label in subject_labels if label]
    lines = raw_chapter_text.splitlines()
    candidates: set[str] = set()
    for line in lines:
        lower = line.lower()
        if labels and not any(label.lower() in lower for label in labels):
            continue
        if not any(term in lower for term in ("born", "age", "years old", "year old", "year-old")):
            continue
        patterns = (
            r"(?i)\b(?:approximately|about|around)?\s*\d{1,3}\s*(?:years?\s*old|year-old)\b",
            r"(?i)\bage\s*:?\s*(?:approximately|about|around)?\s*\d{1,3}\b",
            r"(?i)\bborn\b[^.\n]{0,80}?\b\d{3,4}\s*(?:AD|CE)?\b",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, line):
                token = match.group(0).strip(" -:;,.)(")
                if token:
                    candidates.add(token)
    return sorted(candidates, key=lambda item: (len(item), item.lower()))


def build_projection(
    sidecar: dict[str, Any],
    *,
    raw_chapter_text: str,
    generation_guardrails: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(sidecar, dict):
        raise GenerationKnowledgeProjectionError("Chapter sidecar is required.")
    guardrails = dict(generation_guardrails or {})
    if not guardrails:
        raise GenerationKnowledgeProjectionError("Generation guardrails are required.")

    execution = sidecar.get("chapter_execution_contract")
    execution = execution if isinstance(execution, dict) else {}
    selected_refs = _safe_refs(sidecar.get("selected_canon_refs") or [])
    hidden_names = []
    hidden_presentations = []
    for ref in sidecar.get("selected_canon_refs") or []:
        if not isinstance(ref, dict) or ref.get("hide_name_in_prose") is not True:
            continue
        if ref.get("record_type") != "character":
            raise GenerationKnowledgeProjectionError(
                "Only selected characters may hide canonical names."
            )
        label = str(ref.get("label") or "").strip()
        if not label or len(label) > 200:
            raise GenerationKnowledgeProjectionError(
                "Hidden character has no valid Canon name."
            )
        hidden_names.append(label)
        chapter_alias = ref.get("presentation_name", "")
        overrides = ref.get("event_presentations", {})
        if not isinstance(chapter_alias, str) or len(chapter_alias.strip()) > 80:
            raise GenerationKnowledgeProjectionError("Invalid optional presentation name.")
        if not isinstance(overrides, dict):
            raise GenerationKnowledgeProjectionError("Invalid event presentation mapping.")
        active_event_ids = {
            str((placement.get("event_ref") or {}).get("record_id") or "")
            for placement in sidecar.get("event_placements") or []
            if isinstance(placement, dict)
        }
        event_labels = []
        for event_id, description in overrides.items():
            if (not isinstance(event_id, str) or event_id not in active_event_ids
                    or not isinstance(description, str) or len(description.strip()) > 80):
                raise GenerationKnowledgeProjectionError("Invalid selected-event presentation.")
            if description.strip():
                event_labels.append({"event_id": event_id, "presentation": description.strip()})
        hidden_presentations.append({
            "canonical_name": label,
            "presentation_name": chapter_alias.strip(),
            "event_presentations": event_labels,
        })
    controls = _safe_story_controls(sidecar.get("story_controls") or [])
    # Only compiler-approved, selected, bounded positive facts may cross the
    # provider boundary. A plain selected ID is never disclosure permission.
    safe_chapter_facts: list[dict[str, Any]] = []
    selected_keys = {
        (ref["record_id"], ref["record_type"])
        for ref in selected_refs + _safe_refs(sidecar.get("assigned_event_refs") or [])
    }
    active_control_ids = set(sidecar.get("story_control_refs") or [])
    seen_fact_records: set[str] = set()
    for item in sidecar.get("chapter_safe_canon_facts") or []:
        if not isinstance(item, dict):
            raise GenerationKnowledgeProjectionError("Invalid chapter-safe Canon entry.")
        record_id = str(item.get("record_id") or "")
        record_type = str(item.get("record_type") or "")
        control_id = str(item.get("selected_story_control_id") or "")
        claims = item.get("approved_facts")
        if (
            not record_id or record_id in seen_fact_records
            or (record_id, record_type) not in selected_keys
            or (control_id and control_id not in active_control_ids)
            or not isinstance(claims, list) or not claims or len(claims) > 20
            or any(not isinstance(claim, str) or not claim.strip()
                   or len(claim) > 400 for claim in claims)
        ):
            raise GenerationKnowledgeProjectionError(
                "Chapter-safe Canon facts failed selection and disclosure validation."
            )
        seen_fact_records.add(record_id)
        safe_chapter_facts.append({
            "record_id": record_id,
            "record_type": record_type,
            "approved_facts": list(claims),
        })
    prior = sidecar.get("prior_ending_context")
    prior = prior if isinstance(prior, dict) else {}
    continuity = sidecar.get("continuity")
    continuity = continuity if isinstance(continuity, dict) else {}
    chapter_position = (
        int(sidecar.get("book_number") or 0),
        int(sidecar.get("chapter_number") or 0),
    )
    if chapter_position[0] < 1 or chapter_position[1] < 1:
        raise GenerationKnowledgeProjectionError("Valid chapter position is required.")
    prior_text = str(prior.get("text") or "")
    prior_identity = prior.get("source_identity") or {}
    if not isinstance(prior_identity, dict):
        raise GenerationKnowledgeProjectionError("Prior ending identity must be an object.")
    if prior.get("included") is True:
        if not prior_text or hashlib.sha256(prior_text.encode("utf-8")).hexdigest() != str(prior.get("sha256") or ""):
            raise GenerationKnowledgeProjectionError("Bounded prior ending content hash mismatch.")
        if len(prior_text) != int(prior.get("character_count") or 0) or len(prior_text) > 8000:
            raise GenerationKnowledgeProjectionError("Bounded prior ending length mismatch.")
        if (
            int(prior_identity.get("source_book_number") or 0) != chapter_position[0]
            or int(prior_identity.get("source_chapter_number") or 0) != chapter_position[1] - 1
            or not prior_identity.get("generation_id")
            or not prior_identity.get("version_id")
            or not prior_identity.get("accepted_content_sha256")
        ):
            raise GenerationKnowledgeProjectionError("Prior ending acceptance provenance is invalid.")
    elif prior_text:
        raise GenerationKnowledgeProjectionError("Unannounced prior ending text is forbidden.")
    bounded_state = continuity.get("bounded_state") or {}
    if not isinstance(bounded_state, dict):
        raise GenerationKnowledgeProjectionError("Continuity state must be an object.")
    # The persisted Approved Continuity contract authorizes only established
    # events/reveals. Reject populated unverified state categories rather than
    # forwarding opaque semantic content as provider authority.
    for key in (
        "character_states", "relationship_states", "knowledge_states",
        "event_states", "mission_states", "reveal_states",
    ):
        if bounded_state.get(key) not in (None, [], {}):
            raise GenerationKnowledgeProjectionError(
                f"Unapproved continuity category {key!r} cannot enter provider context."
            )
    safe_continuity: dict[str, Any] = {}
    for key in ("established",):
        entries = bounded_state.get(key) or []
        if not isinstance(entries, list):
            raise GenerationKnowledgeProjectionError(
                f"Continuity field {key!r} must be a chapter-bounded list."
            )
        selected: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise GenerationKnowledgeProjectionError(
                    f"Continuity field {key!r} contains an invalid entry."
                )
            raw_book = entry.get("book_number")
            raw_chapter = entry.get("chapter_number")
            if raw_book in (None, "") or raw_chapter in (None, ""):
                raise GenerationKnowledgeProjectionError(
                    f"Continuity field {key!r} has no explicit chapter position."
                )
            try:
                position = (int(raw_book), int(raw_chapter))
            except (TypeError, ValueError) as exc:
                raise GenerationKnowledgeProjectionError(
                    f"Continuity field {key!r} contains invalid chapter coordinates."
                ) from exc
            if position[0] < 1 or position[1] < 1 or position >= chapter_position:
                raise GenerationKnowledgeProjectionError(
                    f"Continuity field {key!r} is not from an approved prior chapter."
                )
            if key == "established":
                establishment_type = str(entry.get("type") or "")
                target_ref = str(entry.get("target_ref") or "")
                if establishment_type not in ("event_established", "reveal_established") or not target_ref:
                    raise GenerationKnowledgeProjectionError(
                        "Approved Continuity establishment is invalid."
                    )
                # Mirror the four-field Approved Continuity storage schema.
                # Do not forward unrecognized nested metadata to the provider.
                selected.append({
                    "type": establishment_type,
                    "target_ref": target_ref,
                    "book_number": position[0],
                    "chapter_number": position[1],
                })
        safe_continuity[key] = selected

    # Every supported Story Control carries explicit permitted/prohibited claims.
    # An empty permitted list grants no disclosure. Non-reveal controls never
    # acquire implicit reveal authority merely because they are active.
    chapter_disclosures: list[dict[str, Any]] = []
    active_refs = sidecar.get("story_control_refs") or []
    if not isinstance(active_refs, list):
        raise GenerationKnowledgeProjectionError("Invalid chapter Story Control references.")
    active_ids = {str(ref) for ref in active_refs}
    supported_types = {
        "mystery_reveal", "knowledge_change", "relationship_change",
        "availability_change", "escalation_change",
    }
    seen_controls: set[str] = set()
    for raw_control in sidecar.get("story_controls") or []:
        if not isinstance(raw_control, dict):
            raise GenerationKnowledgeProjectionError("Invalid chapter Story Control.")
        control_type = str(raw_control.get("control_type") or "")
        control_id = str(raw_control.get("control_id") or "").strip()
        if control_type not in supported_types:
            raise GenerationKnowledgeProjectionError("Unsupported Story Control type.")
        if not control_id or control_id in seen_controls:
            raise GenerationKnowledgeProjectionError("Missing or duplicate Story Control identity.")
        seen_controls.add(control_id)
        try:
            positioned = (
                int(raw_control.get("book_number") or 0) == chapter_position[0]
                and int(raw_control.get("chapter_number") or 0) == chapter_position[1]
            )
        except (TypeError, ValueError):
            positioned = False
        if (
            control_id not in active_ids
            or not positioned
            or (raw_control.get("protection") or {}).get("eligibility_status") != "ACTIVE"
        ):
            raise GenerationKnowledgeProjectionError(
                "Story Control lacks active chapter-specific authority."
            )
        allowed = raw_control.get("allowed_interpretations")
        forbidden = raw_control.get("forbidden_assertions")
        if (
            not isinstance(allowed, list)
            or not isinstance(forbidden, list)
            or not all(isinstance(v, str) and v.strip() for v in allowed + forbidden)
            or (control_type == "mystery_reveal" and not allowed)
        ):
            raise GenerationKnowledgeProjectionError(
                "Story Control disclosure claims must be explicit and bounded."
            )
        chapter_disclosures.append({
            "control_id": control_id,
            "control_type": control_type,
            "book_number": chapter_position[0],
            "chapter_number": chapter_position[1],
            "permitted_claims": list(allowed),
            "forbidden_claims": list(forbidden),
        })
    if seen_controls != active_ids:
        raise GenerationKnowledgeProjectionError(
            "Active Story Control references disagree with chapter controls."
        )

    # The Chapter Knowledge compiler records these two authored planning fields
    # separately from unrestricted Canon. Preserve their exact source text and
    # the Chapter Plan identity instead of projecting an impoverished event list.
    narrative = sidecar.get("chapter_narrative_source")
    safe_narrative = None
    if narrative is not None:
        if not isinstance(narrative, dict):
            raise GenerationKnowledgeProjectionError(
                "Compiled chapter narrative source must be an object."
            )
        objective = narrative.get("chapter_objective")
        kickoff = narrative.get("generation_kickoff")
        plan_sha = str(narrative.get("chapter_plan_sha256") or "")
        plan_revision = narrative.get("chapter_plan_revision")
        expected_plan_sha = str(
            (sidecar.get("source") or {}).get("chapter_plan_sha256") or ""
        )
        if (
            not isinstance(objective, str) or not objective.strip()
            or not isinstance(kickoff, str) or not kickoff.strip()
            or len(objective) > 12000 or len(kickoff) > 12000
            or not plan_sha or plan_sha != expected_plan_sha
            or isinstance(plan_revision, bool)
            or not isinstance(plan_revision, int)
            or plan_revision < 0
        ):
            raise GenerationKnowledgeProjectionError(
                "Chapter objective/kickoff or their Chapter Plan provenance is invalid."
            )
        safe_narrative = {
            "chapter_objective": objective,
            "generation_kickoff": kickoff,
            "chapter_plan_sha256": plan_sha,
            "chapter_plan_revision": plan_revision,
        }

    projection = {
        "schema_version": SCHEMA_VERSION,
        "service": SERVICE_MARKER,
        "authority": "reveal_safe_provider_reference",
        "project_id": str(sidecar.get("project_id") or ""),
        "book_number": int(sidecar.get("book_number") or 0),
        "chapter_number": int(sidecar.get("chapter_number") or 0),
        "selected_entities": selected_refs,
        "hidden_character_names": hidden_names,
        "hidden_character_presentations": hidden_presentations,
        "chapter_safe_canon_facts": safe_chapter_facts,
        **({"chapter_narrative_brief": safe_narrative} if safe_narrative is not None else {}),
        "chapter_disclosure_authority": chapter_disclosures,
        "story_controls": controls,
        "chapter_execution": {
            "required_participants": _safe_refs(execution.get("required_participant_refs") or []),
            "required_locations": _safe_refs(execution.get("required_location_refs") or []),
            "required_event_sequence": _safe_event_sequence(execution.get("required_event_sequence") or []),
            "pov_contract": _safe_pov(execution.get("pov_contract") or {}),
        },
        "prior_ending_context": {
            "included": prior.get("included") is True,
            "sha256": str(prior.get("sha256") or ""),
            "character_count": int(prior.get("character_count") or 0),
            "text": prior_text if prior.get("included") is True else "",
            "source_identity": {
                "source_book_number": int(prior_identity.get("source_book_number") or 0),
                "source_chapter_number": int(prior_identity.get("source_chapter_number") or 0),
                "generation_id": str(prior_identity.get("generation_id") or ""),
                "version_id": str(prior_identity.get("version_id") or ""),
                "accepted_content_sha256": str(prior_identity.get("accepted_content_sha256") or ""),
            } if prior.get("included") is True else {},
        },
        "approved_continuity": {
            "required": continuity.get("required") is True,
            "approved_through": continuity.get("approved_through"),
            "bounded_state": safe_continuity
            if continuity.get("required") is True else {},
            "source_sha256": str(continuity.get("source_sha256") or ""),
        },
        "source_identity": {
            "chapter_pack_sha256": str(sidecar.get("pack_sha256") or ""),
            "dependency_set_sha256": str(sidecar.get("dependency_set_sha256") or ""),
        },
        "raw_chapter_knowledge_included": False,
        "raw_canon_records_included": False,
    }
    projection["projection_sha256"] = _sha256(projection)

    subject_labels = [
        str((item.get("subject_ref") or {}).get("label") or "")
        for item in (sidecar.get("story_controls") or [])
        if isinstance(item, dict)
    ]
    sensitive = _sensitive_literals_from_raw(
        str(raw_chapter_text or ""),
        subject_labels=subject_labels,
        chapter_restrictions=[
            str(v) for v in (guardrails.get("chapter_restrictions") or [])
        ],
    )
    return {
        "projection": projection,
        "projection_text": _canonical_json(projection),
        "projection_sha256": str(projection["projection_sha256"]),
        "local_sensitive_literals": sensitive,
        "raw_chapter_knowledge_sha256": hashlib.sha256(
            str(raw_chapter_text or "").encode("utf-8")
        ).hexdigest(),
    }


def assert_provider_reference_safe(
    provider_user_text: str,
    *,
    raw_chapter_text: str,
    local_sensitive_literals: list[str],
) -> None:
    text = str(provider_user_text or "")
    raw = str(raw_chapter_text or "")
    if raw and raw in text:
        raise GenerationKnowledgeProjectionError(
            "Raw Chapter Knowledge leaked into provider input."
        )
    for literal in local_sensitive_literals:
        if literal and literal.lower() in text.lower():
            raise GenerationKnowledgeProjectionError(
                f"Forbidden reveal literal leaked into provider reference input: {literal!r}"
            )
