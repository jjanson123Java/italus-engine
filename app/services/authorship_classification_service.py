"""
Primary 35 deterministic provenance classification and HCCS boundary.

This service classifies one provider-generation segment from immutable MODEL origin
and Primary 34 author-review lineage. HCCS is an internal provenance score. It is
not a percentage of legal human authorship and this service makes no copyright,
ownership, publisher-policy, Canon, continuity, or Author Voice determination.

Classification is read-only and recomputable. Durable book/chapter provenance
ledger persistence remains Primary 38.
"""

from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
import hashlib
import math
import re
from typing import Any

from app.services import author_review_service, authorship_provenance_service


AUTHORSHIP_CLASSIFICATION_SERVICE_MARKER = "primary35-provenance-classification-v1"
CLASSIFICATION_SCHEMA_VERSION = "primary35_provenance_classification_v1"
SCORING_MODEL_VERSION = "hccs_v1"
SCORING_CONSTANTS_VERSION = "hccs_constants_v1"

HCCS_WEIGHTS = {
    "expressive_prose_authorship": 40.0,
    "narrative_structural_authorship": 20.0,
    "canon_creative_architecture": 15.0,
    "substantive_revision_intervention": 15.0,
    "author_voice_rulebook_contribution": 5.0,
    "final_creative_control": 5.0,
}

LEVELS = {
    1: "AI Generated",
    2: "AI Generated - Human Directed",
    3: "Human Modified - AI Assisted Drafting",
    4: "Human Authored - AI Assisted",
}

SCORE_BANDS = {
    1: {"minimum": 0.0, "maximum": 24.999},
    2: {"minimum": 25.0, "maximum": 49.999},
    3: {"minimum": 50.0, "maximum": 74.999},
    4: {"minimum": 75.0, "maximum": 100.0},
}

GATE_THRESHOLDS = {
    "level_3": {
        "hccs_minimum": 50.0,
        "expressive_minimum": 0.50,
        "requires_substantive_human_revision": True,
    },
    "level_4": {
        "hccs_minimum": 75.0,
        "expressive_minimum": 0.80,
        "narrative_structural_minimum": 0.60,
        "maximum_retained_model_expression": 0.35,
        "minimum_evidence_confidence": "HIGH",
    },
}

CHANGE_THRESHOLDS = {
    "light_maximum": 0.20,
    "moderate_maximum": 0.55,
    "replacement_minimum": 0.80,
    "replacement_maximum_model_retention": 0.20,
    "boundary_margin_hccs_points": 2.0,
}

ANTI_SKEW_RULES = (
    "edit_count_does_not_earn_points",
    "repeated_saves_do_not_multiply_authorship_evidence",
    "mechanical_punctuation_or_whitespace_changes_receive_near_zero_expressive_credit",
    "acceptance_alone_receives_only_final_control_credit",
    "model_to_model_rewriting_receives_no_human_expressive_credit",
    "author_rulebook_triggered_model_rewrite_remains_model_actor",
    "final_segment_state_is_scored_once_from_meaningful_lineage_not_event_count",
)

SEGMENT_STATES = frozenset(
    {
        "AI_GENERATED_UNMODIFIED",
        "AI_GENERATED_LIGHTLY_EDITED",
        "AI_GENERATED_MODERATELY_REVISED",
        "AI_GENERATED_SUBSTANTIVELY_REWRITTEN",
        "AI_GENERATED_REPLACED_BY_AUTHOR",
        "AUTHOR_ORIGINAL",
        "AUTHOR_ORIGINAL_AI_ASSISTED",
        "MIXED_ORIGIN",
        "EXTERNAL_AUTHOR_REVISION",
    }
)

_STRUCTURAL_AUTHOR_OPERATIONS = frozenset(
    {"AUTHOR_MOVE", "AUTHOR_SPLIT", "AUTHOR_MERGE"}
)
_AUTHOR_CONTENT_OPERATIONS = frozenset(
    {
        "AUTHOR_INSERT",
        "AUTHOR_DELETE",
        "AUTHOR_REPLACE",
        "AUTHOR_EDIT",
        "AUTHOR_SPLIT",
        "AUTHOR_MERGE",
    }
)
_MODEL_CONTENT_OPERATIONS = frozenset(
    {"MODEL_GENERATE", "MODEL_REGENERATE", "MODEL_REWRITE", "MODEL_COPYEDIT"}
)


class AuthorshipClassificationError(RuntimeError):
    """Raised when accepted lineage cannot be classified deterministically."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code or "AUTHORSHIP_CLASSIFICATION_FAILED")
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": deepcopy(self.details),
        }


def get_classification_contract() -> dict[str, Any]:
    """Return the versioned Primary 35 scoring/classification contract."""

    return {
        "status": "ok",
        "service": AUTHORSHIP_CLASSIFICATION_SERVICE_MARKER,
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "scoring_model_version": SCORING_MODEL_VERSION,
        "scoring_constants_version": SCORING_CONSTANTS_VERSION,
        "hccs_formula": "40E + 20N + 15C + 15R + 5V + 5F",
        "hccs_weights": deepcopy(HCCS_WEIGHTS),
        "score_bands": deepcopy(SCORE_BANDS),
        "gate_thresholds": deepcopy(GATE_THRESHOLDS),
        "change_thresholds": deepcopy(CHANGE_THRESHOLDS),
        "segment_states": sorted(SEGMENT_STATES),
        "anti_skew_rules": list(ANTI_SKEW_RULES),
        "authority": {
            "segment_provenance_classification": True,
            "hccs_internal_provenance_metric": True,
            "hccs_is_legal_authorship_percentage": False,
            "evidence_confidence_separate_from_hccs": True,
            "writes_provenance_evidence": False,
            "writes_approved_continuity": False,
            "mutates_canon": False,
            "mutates_runtime_story_state": False,
            "updates_author_voice": False,
            "calls_provider": False,
            "writes_authorship_ledger": False,
        },
        "deferred_dimensions": {
            "canon_creative_architecture": (
                "No segment-local Canon contribution credit is inferred without "
                "explicit provenance evidence."
            ),
            "author_voice_rulebook_contribution": (
                "Author Voice provenance gating is Primary 37; no Primary 35 "
                "segment score infers this dimension."
            ),
            "book_or_chapter_aggregation": (
                "Durable aggregation and final manuscript ledger are Primary 38."
            ),
        },
        "disclaimer": (
            "HCCS and provenance levels are Italus internal provenance controls. "
            "They are not legal copyright, ownership, or publisher-policy conclusions."
        ),
    }


def classify_generation_segment(
    project_id: str,
    generation_id: str,
) -> dict[str, Any]:
    """Classify one provider-generation segment from current immutable lineage."""

    review = author_review_service.get_author_review_status(project_id, generation_id)
    validation = deepcopy(review.get("validation") or {})
    validator_context = deepcopy(validation.get("validator_context") or {})
    segment_id = str(validator_context.get("segment_id") or "").strip()
    if not segment_id:
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_SEGMENT_MISSING",
            "Validated generation candidate has no segment_id.",
        )

    records = authorship_provenance_service.get_segment_lineage_records(
        project_id,
        generation_id=str(generation_id or "").strip(),
        segment_id=segment_id,
    )
    _validate_record_integrity(records)

    base = _base_payload(
        project_id=project_id,
        generation_id=str(generation_id or "").strip(),
        segment_id=segment_id,
        validation=validation,
        review=review,
    )

    review_state = str(review.get("review_state") or "")
    if review_state == "rejected":
        return {
            **base,
            "assessment_status": "rejected_not_scored",
            "final_segment_state": None,
            "hccs": None,
            "candidate_level": None,
            "awarded_level": None,
            "evidence_confidence": _confidence_payload(records),
            "message": (
                "Rejected candidates retain lineage evidence but do not receive "
                "an accepted-segment HCCS classification."
            ),
        }

    if review_state != "accepted_pending_approved_continuity":
        return {
            **base,
            "assessment_status": "pending_author_acceptance",
            "final_segment_state": None,
            "hccs": None,
            "candidate_level": None,
            "awarded_level": None,
            "evidence_confidence": _confidence_payload(records),
            "message": (
                "HCCS classification is deferred until the author records a terminal "
                "accept decision. Approved Continuity remains separate and locked."
            ),
        }

    terminal_event = deepcopy(review.get("terminal_event") or {})
    if str(terminal_event.get("operation") or "") != "AUTHOR_ACCEPT":
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_ACCEPTANCE_MISSING",
            "Accepted review state is not backed by one AUTHOR_ACCEPT event.",
        )

    chain = _accepted_chain(records, terminal_event)
    origin = _model_origin(records)
    accepted_content = str(review.get("current_content") or "")
    accepted_sha256 = _sha256(accepted_content)
    if accepted_sha256 != str(review.get("current_content_sha256") or ""):
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_ACCEPTED_HASH_MISMATCH",
            "Accepted review content does not match its recorded SHA-256.",
        )

    model_baseline, human_events, external_revision = _human_expression_baseline(
        chain,
        origin=origin,
        accepted_content=accepted_content,
    )
    metrics = _change_metrics(model_baseline, accepted_content)
    structural = _structural_evidence(
        model_baseline,
        accepted_content,
        human_events,
    )
    final_state = _segment_state(
        metrics,
        human_events=human_events,
        external_revision=external_revision,
    )
    components = _hccs_components(
        final_state=final_state,
        metrics=metrics,
        structural=structural,
        accepted=True,
    )
    hccs = _hccs(components)
    confidence = _confidence_payload(records)
    candidate_level = _candidate_level(hccs)
    gates = _level_gates(
        hccs=hccs,
        components=components,
        metrics=metrics,
        final_state=final_state,
        confidence=confidence,
    )
    awarded_level = _awarded_level(hccs, gates)
    margin = _boundary_margin(hccs)

    return {
        **base,
        "assessment_status": "classified",
        "final_segment_state": final_state,
        "accepted_version_id": str(review.get("current_version_id") or ""),
        "accepted_content_sha256": accepted_sha256,
        "model_expression_baseline_sha256": _sha256(model_baseline),
        "hccs": hccs,
        "hccs_components": components,
        "change_evidence": {
            **metrics,
            **structural,
            "human_lineage_event_count_observed": len(human_events),
            "event_count_used_as_direct_score_input": False,
        },
        "candidate_level": _level_payload(candidate_level),
        "awarded_level": _level_payload(awarded_level),
        "level_gates": gates,
        "boundary_margin": margin,
        "evidence_confidence": confidence,
        "anti_skew": {
            "rules_applied": list(ANTI_SKEW_RULES),
            "repeated_edits_multiply_credit": False,
            "score_uses_final_meaningful_transformation": True,
        },
        "dimension_evidence": {
            "E": "deterministic final human-vs-latest-MODEL expression change",
            "N": "deterministic paragraph/sentence structure plus explicit structural author operations",
            "C": "not observed in this segment lineage; 0.0",
            "R": "final meaningful human transformation with saturation; edit count excluded",
            "V": "Primary 37 evidence unavailable; 0.0",
            "F": "terminal AUTHOR_ACCEPT recorded; 1.0",
        },
        "message": (
            "Primary 35 segment provenance classification is computed from immutable "
            "lineage. Approved Continuity remains locked for Primary 36."
        ),
    }


def _base_payload(
    *,
    project_id: str,
    generation_id: str,
    segment_id: str,
    validation: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": AUTHORSHIP_CLASSIFICATION_SERVICE_MARKER,
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "scoring_model_version": SCORING_MODEL_VERSION,
        "scoring_constants_version": SCORING_CONSTANTS_VERSION,
        "project_id": project_id,
        "generation_id": generation_id,
        "segment_id": segment_id,
        "review_state": str(review.get("review_state") or ""),
        "validation_report_sha256": validation.get("validation_report_sha256"),
        "approved_continuity_committed": False,
        "authority": deepcopy(get_classification_contract()["authority"]),
        "disclaimer": get_classification_contract()["disclaimer"],
    }


def _validate_record_integrity(records: dict[str, Any]) -> None:
    origins = list(records.get("origins") or [])
    events = list(records.get("events") or [])
    versions = dict(records.get("versions") or {})

    if len(origins) != 1:
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_MODEL_ORIGIN_NOT_UNIQUE",
            "Classification requires exactly one immutable MODEL origin.",
            details={"origin_count": len(origins)},
        )
    origin = origins[0]
    if str(origin.get("origin_actor") or "") != authorship_provenance_service.ACTOR_MODEL:
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_MODEL_ORIGIN_REQUIRED",
            "Provider candidate classification requires a MODEL origin.",
        )
    if origin.get("immutable") is not True:
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_ORIGIN_MUTABILITY_INVALID",
            "MODEL origin must remain immutable.",
        )
    origin_content = str(origin.get("content") or "")
    if _sha256(origin_content) != str(origin.get("content_hash") or ""):
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_ORIGIN_HASH_MISMATCH",
            "MODEL-origin content no longer matches its immutable SHA-256.",
        )

    for version_id, version in versions.items():
        if str(version.get("version_id") or "") != str(version_id):
            raise AuthorshipClassificationError(
                "PROVENANCE_CLASSIFICATION_VERSION_ID_MISMATCH",
                "Lineage version identity is inconsistent.",
                details={"version_id": version_id},
            )
        for parent in version.get("parent_version_ids") or []:
            if parent not in versions:
                raise AuthorshipClassificationError(
                    "PROVENANCE_CLASSIFICATION_PARENT_MISSING",
                    "Lineage references an unknown parent version.",
                    details={"version_id": version_id, "parent_version_id": parent},
                )

    for event in events:
        if "content_after" in event:
            actual = _sha256(str(event.get("content_after") or ""))
            if actual != str(event.get("after_hash") or ""):
                raise AuthorshipClassificationError(
                    "PROVENANCE_CLASSIFICATION_EVENT_HASH_MISMATCH",
                    "Persisted review content does not match its lineage SHA-256.",
                    details={"event_id": event.get("event_id")},
                )


def _model_origin(records: dict[str, Any]) -> dict[str, Any]:
    origins = list(records.get("origins") or [])
    exact = [
        item
        for item in origins
        if str(item.get("origin_actor") or "")
        == authorship_provenance_service.ACTOR_MODEL
    ]
    if len(exact) != 1:
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_MODEL_ORIGIN_NOT_UNIQUE",
            "Classification requires exactly one immutable MODEL origin.",
            details={"matching_origin_count": len(exact)},
        )
    return deepcopy(exact[0])


def _accepted_chain(
    records: dict[str, Any],
    terminal_event: dict[str, Any],
) -> list[dict[str, Any]]:
    versions = dict(records.get("versions") or {})
    event_by_version = {
        str(event.get("version_id") or ""): deepcopy(event)
        for event in (records.get("events") or [])
    }
    origin_by_version = {
        str(origin.get("version_id") or ""): deepcopy(origin)
        for origin in (records.get("origins") or [])
    }
    current_id = str(terminal_event.get("version_id") or "")
    if current_id not in versions:
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_ACCEPTED_VERSION_MISSING",
            "AUTHOR_ACCEPT version is absent from the lineage index.",
        )

    reversed_chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    while current_id:
        if current_id in seen:
            raise AuthorshipClassificationError(
                "PROVENANCE_CLASSIFICATION_LINEAGE_CYCLE",
                "Accepted lineage contains a cycle.",
            )
        seen.add(current_id)
        version = versions.get(current_id)
        if not isinstance(version, dict):
            raise AuthorshipClassificationError(
                "PROVENANCE_CLASSIFICATION_VERSION_MISSING",
                "Accepted lineage references a missing version.",
                details={"version_id": current_id},
            )
        parents = list(version.get("parent_version_ids") or [])
        source = event_by_version.get(current_id) or origin_by_version.get(current_id)
        if source is None:
            raise AuthorshipClassificationError(
                "PROVENANCE_CLASSIFICATION_SOURCE_MISSING",
                "Lineage version has no authoritative origin/event source.",
                details={"version_id": current_id},
            )
        reversed_chain.append(
            {
                "version": deepcopy(version),
                "source": deepcopy(source),
                "kind": "event" if current_id in event_by_version else "origin",
            }
        )
        if not parents:
            break
        if len(parents) != 1:
            raise AuthorshipClassificationError(
                "PROVENANCE_CLASSIFICATION_COMPLEX_LINEAGE_UNSUPPORTED",
                "Primary 35 provider-segment scoring requires one deterministic accepted ancestry path.",
                details={"version_id": current_id, "parent_count": len(parents)},
            )
        current_id = str(parents[0])

    chain = list(reversed(reversed_chain))
    if not chain or chain[0]["kind"] != "origin":
        raise AuthorshipClassificationError(
            "PROVENANCE_CLASSIFICATION_ORIGIN_PATH_MISSING",
            "Accepted ancestry does not terminate at an immutable origin.",
        )
    return chain


def _human_expression_baseline(
    chain: list[dict[str, Any]],
    *,
    origin: dict[str, Any],
    accepted_content: str,
) -> tuple[str, list[dict[str, Any]], bool]:
    model_baseline = str(origin.get("content") or "")
    human_events: list[dict[str, Any]] = []
    external_revision = False

    for node in chain[1:]:
        if node["kind"] != "event":
            continue
        event = node["source"]
        actor = str(event.get("actor") or "")
        operation = str(event.get("operation") or "")

        if actor == authorship_provenance_service.ACTOR_MODEL:
            if operation in _MODEL_CONTENT_OPERATIONS:
                if "content_after" not in event:
                    raise AuthorshipClassificationError(
                        "PROVENANCE_CLASSIFICATION_MODEL_CONTENT_MISSING",
                        "MODEL transformation lacks recoverable content; human credit cannot be isolated.",
                        details={"event_id": event.get("event_id")},
                    )
                model_baseline = str(event.get("content_after") or "")
                human_events = []
                external_revision = False
            continue

        if actor == authorship_provenance_service.ACTOR_AUTHOR:
            if operation in _AUTHOR_CONTENT_OPERATIONS:
                human_events.append(deepcopy(event))
            continue

        if actor == authorship_provenance_service.ACTOR_EXTERNAL_AUTHOR_ATTESTED:
            human_events.append(deepcopy(event))
            external_revision = True

    if _sha256(accepted_content) == _sha256(model_baseline):
        human_events = []
        external_revision = False

    return model_baseline, human_events, external_revision


def _change_metrics(before: str, after: str) -> dict[str, Any]:
    if before == after:
        return {
            "token_similarity": 1.0,
            "meaningful_change_ratio": 0.0,
            "retained_model_expression": 1.0,
            "author_addition_ratio": 0.0,
            "mechanical_only": False,
        }

    before_tokens = _word_tokens(before)
    after_tokens = _word_tokens(after)
    matcher = SequenceMatcher(None, before_tokens, after_tokens, autojunk=False)
    ratio = _clamp(matcher.ratio())
    retained = 0
    inserted = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            retained += i2 - i1
        elif tag in {"insert", "replace"}:
            inserted += j2 - j1

    retained_ratio = (
        _clamp(retained / max(1, len(before_tokens))) if before_tokens else 0.0
    )
    addition_ratio = (
        _clamp(inserted / max(1, len(after_tokens))) if after_tokens else 0.0
    )
    mechanical_only = _mechanical_signature(before) == _mechanical_signature(after)

    return {
        "token_similarity": round(ratio, 6),
        "meaningful_change_ratio": round(0.0 if mechanical_only else 1.0 - ratio, 6),
        "retained_model_expression": round(retained_ratio, 6),
        "author_addition_ratio": round(addition_ratio, 6),
        "mechanical_only": bool(mechanical_only),
    }


def _structural_evidence(
    before: str,
    after: str,
    human_events: list[dict[str, Any]],
) -> dict[str, Any]:
    before_paragraphs = _paragraphs(before)
    after_paragraphs = _paragraphs(after)
    before_sentences = _sentences(before)
    after_sentences = _sentences(after)

    paragraph_delta = _count_delta(len(before_paragraphs), len(after_paragraphs))
    sentence_delta = _count_delta(len(before_sentences), len(after_sentences))
    shape_signal = _clamp((0.60 * paragraph_delta) + (0.40 * sentence_delta))
    structural_ops = sorted(
        {
            str(event.get("operation") or "")
            for event in human_events
            if str(event.get("operation") or "") in _STRUCTURAL_AUTHOR_OPERATIONS
        }
    )
    explicit_signal = 0.75 if structural_ops else 0.0
    signal = _clamp(max(shape_signal, explicit_signal))

    return {
        "structural_change_ratio": round(signal, 6),
        "paragraph_count_before": len(before_paragraphs),
        "paragraph_count_after": len(after_paragraphs),
        "sentence_count_before": len(before_sentences),
        "sentence_count_after": len(after_sentences),
        "explicit_structural_author_operations": structural_ops,
        "semantic_narrative_classifier_used": False,
    }


def _segment_state(
    metrics: dict[str, Any],
    *,
    human_events: list[dict[str, Any]],
    external_revision: bool,
) -> str:
    if external_revision:
        return "EXTERNAL_AUTHOR_REVISION"

    change = float(metrics["meaningful_change_ratio"])
    retained = float(metrics["retained_model_expression"])
    mechanical = bool(metrics["mechanical_only"])

    if not human_events:
        return "AI_GENERATED_UNMODIFIED"
    if mechanical:
        return "AI_GENERATED_LIGHTLY_EDITED"
    if change <= 0.0:
        return "AI_GENERATED_UNMODIFIED"
    if (
        change >= CHANGE_THRESHOLDS["replacement_minimum"]
        and retained <= CHANGE_THRESHOLDS["replacement_maximum_model_retention"]
    ):
        return "AI_GENERATED_REPLACED_BY_AUTHOR"
    if change <= CHANGE_THRESHOLDS["light_maximum"]:
        return "AI_GENERATED_LIGHTLY_EDITED"
    if change <= CHANGE_THRESHOLDS["moderate_maximum"]:
        return "AI_GENERATED_MODERATELY_REVISED"
    return "AI_GENERATED_SUBSTANTIVELY_REWRITTEN"


def _hccs_components(
    *,
    final_state: str,
    metrics: dict[str, Any],
    structural: dict[str, Any],
    accepted: bool,
) -> dict[str, float]:
    change = float(metrics["meaningful_change_ratio"])
    mechanical = bool(metrics["mechanical_only"])

    if final_state == "AI_GENERATED_UNMODIFIED":
        expressive = 0.0
        revision = 0.0
    elif mechanical:
        expressive = 0.02
        revision = 0.02
    elif final_state == "AI_GENERATED_LIGHTLY_EDITED":
        expressive = _scale(change, 0.0, 0.20, 0.10, 0.25)
        revision = _clamp(math.sqrt(change))
    elif final_state == "AI_GENERATED_MODERATELY_REVISED":
        expressive = _scale(change, 0.20, 0.55, 0.35, 0.65)
        revision = _clamp(math.sqrt(change))
    elif final_state == "AI_GENERATED_REPLACED_BY_AUTHOR":
        expressive = 0.95
        revision = 1.0
    elif final_state == "EXTERNAL_AUTHOR_REVISION":
        expressive = _scale(change, 0.0, 1.0, 0.10, 0.90)
        revision = _clamp(math.sqrt(change))
    else:
        expressive = _scale(change, 0.55, 1.0, 0.65, 0.85)
        revision = _clamp(math.sqrt(change))

    return {
        "E": round(_clamp(expressive), 6),
        "N": round(_clamp(float(structural["structural_change_ratio"])), 6),
        "C": 0.0,
        "R": round(_clamp(revision), 6),
        "V": 0.0,
        "F": 1.0 if accepted else 0.0,
    }


def _hccs(components: dict[str, float]) -> float:
    score = (
        HCCS_WEIGHTS["expressive_prose_authorship"] * components["E"]
        + HCCS_WEIGHTS["narrative_structural_authorship"] * components["N"]
        + HCCS_WEIGHTS["canon_creative_architecture"] * components["C"]
        + HCCS_WEIGHTS["substantive_revision_intervention"] * components["R"]
        + HCCS_WEIGHTS["author_voice_rulebook_contribution"] * components["V"]
        + HCCS_WEIGHTS["final_creative_control"] * components["F"]
    )
    return round(max(0.0, min(100.0, score)), 2)


def _candidate_level(hccs: float) -> int:
    if hccs >= 75.0:
        return 4
    if hccs >= 50.0:
        return 3
    if hccs >= 25.0:
        return 2
    return 1


def _level_gates(
    *,
    hccs: float,
    components: dict[str, float],
    metrics: dict[str, Any],
    final_state: str,
    confidence: dict[str, Any],
) -> dict[str, Any]:
    substantive_states = {
        "AI_GENERATED_SUBSTANTIVELY_REWRITTEN",
        "AI_GENERATED_REPLACED_BY_AUTHOR",
        "AUTHOR_ORIGINAL",
        "AUTHOR_ORIGINAL_AI_ASSISTED",
        "EXTERNAL_AUTHOR_REVISION",
    }
    level_3_checks = {
        "hccs_minimum": hccs >= GATE_THRESHOLDS["level_3"]["hccs_minimum"],
        "expressive_minimum": (
            components["E"] >= GATE_THRESHOLDS["level_3"]["expressive_minimum"]
        ),
        "substantive_human_revision": final_state in substantive_states,
    }
    level_4_checks = {
        "hccs_minimum": hccs >= GATE_THRESHOLDS["level_4"]["hccs_minimum"],
        "expressive_minimum": (
            components["E"] >= GATE_THRESHOLDS["level_4"]["expressive_minimum"]
        ),
        "narrative_structural_minimum": (
            components["N"]
            >= GATE_THRESHOLDS["level_4"]["narrative_structural_minimum"]
        ),
        "model_expression_not_dominant": (
            float(metrics["retained_model_expression"])
            <= GATE_THRESHOLDS["level_4"]["maximum_retained_model_expression"]
        ),
        "evidence_confidence": (
            str(confidence.get("level") or "")
            == GATE_THRESHOLDS["level_4"]["minimum_evidence_confidence"]
        ),
    }
    return {
        "level_3": {
            "passed": all(level_3_checks.values()),
            "checks": level_3_checks,
        },
        "level_4": {
            "passed": all(level_4_checks.values()),
            "checks": level_4_checks,
        },
    }


def _awarded_level(hccs: float, gates: dict[str, Any]) -> int:
    candidate = _candidate_level(hccs)
    if candidate >= 4 and bool((gates.get("level_4") or {}).get("passed")):
        return 4
    if candidate >= 3 and bool((gates.get("level_3") or {}).get("passed")):
        return 3
    if hccs >= 25.0:
        return 2
    return 1


def _level_payload(level: int) -> dict[str, Any]:
    return {"level": int(level), "label": LEVELS[int(level)]}


def _boundary_margin(hccs: float) -> dict[str, Any]:
    margin = float(CHANGE_THRESHOLDS["boundary_margin_hccs_points"])
    nearest = min((25.0, 50.0, 75.0), key=lambda value: abs(value - hccs))
    distance = abs(nearest - hccs)
    return {
        "near_boundary": bool(distance <= margin),
        "nearest_boundary": nearest,
        "distance_points": round(distance, 2),
        "margin_points": margin,
        "interpretation": (
            "candidate_margin"
            if distance <= margin
            else "not_near_scoring_boundary"
        ),
    }


def _confidence_payload(records: dict[str, Any]) -> dict[str, Any]:
    events = list(records.get("events") or [])
    external = any(
        str(event.get("actor") or "")
        == authorship_provenance_service.ACTOR_EXTERNAL_AUTHOR_ATTESTED
        for event in events
    )
    missing_event_content = [
        str(event.get("event_id") or "")
        for event in events
        if str(event.get("operation") or "")
        in (_AUTHOR_CONTENT_OPERATIONS | _MODEL_CONTENT_OPERATIONS)
        and "content_after" not in event
    ]

    if missing_event_content:
        level = "LOW"
    elif external:
        level = "MEDIUM"
    else:
        level = "HIGH"

    return {
        "level": level,
        "separate_from_hccs": True,
        "complete_observed_lineage": not bool(missing_event_content),
        "external_revision_observed_outside_italus": external,
        "missing_recoverable_content_event_ids": missing_event_content,
        "source_hash_integrity_checked": True,
        "author_attestation_is_observation_equivalent": False,
    }


def _word_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_']+", str(text or "").lower())


def _mechanical_signature(text: str) -> tuple[str, ...]:
    return tuple(_word_tokens(text))


def _paragraphs(text: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?:\r?\n){2,}", str(text or "").strip())
        if item.strip()
    ]


def _sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if not cleaned:
        return []
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", cleaned)
        if item.strip()
    ]


def _count_delta(before: int, after: int) -> float:
    if before == after:
        return 0.0
    return _clamp(abs(after - before) / max(1, before, after))


def _scale(
    value: float,
    in_minimum: float,
    in_maximum: float,
    out_minimum: float,
    out_maximum: float,
) -> float:
    if in_maximum <= in_minimum:
        return out_maximum
    position = _clamp((value - in_minimum) / (in_maximum - in_minimum))
    return out_minimum + ((out_maximum - out_minimum) * position)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _sha256(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()
