"""
Primary 37A Author Voice provenance eligibility gate.

This service is read-only. It decides whether one accepted generation segment is
eligible to become Author Voice learning evidence. It does not persist Author
Voice, mutate Canon, change Approved Continuity, call a provider, or alter
generation readiness.

Primary 37B will own author-level Author Voice persistence/update mechanics.
Primary 37C may own prompt-consumption integration after the write path is proven.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services import (
    approved_continuity_service,
    author_review_service,
    authorship_classification_service,
)


AUTHOR_VOICE_PROVENANCE_GATE_MARKER = "primary37a-author-voice-provenance-gate-v1"
AUTHOR_VOICE_GATE_SCHEMA_VERSION = "primary37_author_voice_provenance_gate_v1"
AUTHOR_VOICE_GATE_POLICY_VERSION = "author_voice_provenance_policy_v1"

ELIGIBLE_FINAL_SEGMENT_STATES = frozenset(
    {
        "AI_GENERATED_SUBSTANTIVELY_REWRITTEN",
        "AI_GENERATED_REPLACED_BY_AUTHOR",
    }
)
ELIGIBLE_AWARDED_LEVELS = frozenset({3, 4})


class AuthorVoiceProvenanceGateError(RuntimeError):
    """Raised when Author Voice eligibility cannot be evaluated safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code or "AUTHOR_VOICE_GATE_FAILED")
        self.details = deepcopy(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": deepcopy(self.details),
        }


def get_author_voice_provenance_gate_contract() -> dict[str, Any]:
    """Return the bounded Primary 37A ownership and eligibility contract."""

    return {
        "status": "ok",
        "service": AUTHOR_VOICE_PROVENANCE_GATE_MARKER,
        "schema_version": AUTHOR_VOICE_GATE_SCHEMA_VERSION,
        "policy_version": AUTHOR_VOICE_GATE_POLICY_VERSION,
        "eligible_final_segment_states": sorted(ELIGIBLE_FINAL_SEGMENT_STATES),
        "eligible_awarded_levels": sorted(ELIGIBLE_AWARDED_LEVELS),
        "policy": {
            "requires_terminal_author_accept": True,
            "requires_approved_continuity_commit": True,
            "requires_primary35_classification": True,
            "untouched_model_prose_eligible": False,
            "light_model_prose_edit_eligible": False,
            "moderate_model_prose_edit_eligible": False,
            "substantive_author_rewrite_eligible": True,
            "author_replacement_eligible": True,
            "external_author_revision_eligible_for_active_author_voice": False,
            "rejected_text_eligible": False,
            "model_rewrite_acceptance_alone_eligible": False,
        },
        "authority": {
            "evaluates_author_voice_learning_eligibility": True,
            "writes_author_voice": False,
            "updates_author_voice": False,
            "mutates_canon": False,
            "mutates_approved_continuity": False,
            "mutates_provenance": False,
            "writes_authorship_ledger": False,
            "calls_provider": False,
            "changes_generation_readiness": False,
        },
    }


def evaluate_generation_for_author_voice(
    project_id: str,
    generation_id: str,
) -> dict[str, Any]:
    """Evaluate one generation against the Primary 37A provenance policy."""

    project = str(project_id or "").strip()
    generation = str(generation_id or "").strip()
    if not project:
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_PROJECT_REQUIRED",
            "project_id is required.",
        )
    if not generation:
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_GENERATION_REQUIRED",
            "generation_id is required.",
        )

    try:
        review = author_review_service.get_author_review_status(project, generation)
        classification = authorship_classification_service.classify_generation_segment(
            project,
            generation,
        )
        continuity = approved_continuity_service.get_approved_continuity_status(
            project,
            generation,
        )
    except AuthorVoiceProvenanceGateError:
        raise
    except Exception as exc:
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_GATE_EVIDENCE_UNAVAILABLE",
            "Required provenance/acceptance evidence could not be loaded.",
            details={"error": str(exc)},
        ) from exc

    return evaluate_author_voice_eligibility_evidence(
        review=review,
        classification=classification,
        continuity=continuity,
    )


def evaluate_author_voice_eligibility_evidence(
    *,
    review: dict[str, Any],
    classification: dict[str, Any],
    continuity: dict[str, Any],
) -> dict[str, Any]:
    """Pure deterministic eligibility decision over existing accepted evidence."""

    if not isinstance(review, dict):
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_REVIEW_EVIDENCE_INVALID",
            "Author review evidence must be an object.",
        )
    if not isinstance(classification, dict):
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_CLASSIFICATION_EVIDENCE_INVALID",
            "Authorship classification evidence must be an object.",
        )
    if not isinstance(continuity, dict):
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_CONTINUITY_EVIDENCE_INVALID",
            "Approved Continuity evidence must be an object.",
        )

    project_id = str(review.get("project_id") or "").strip()
    generation_id = str(review.get("generation_id") or "").strip()
    if not project_id or not generation_id:
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_EVIDENCE_IDENTITY_MISSING",
            "Author review evidence requires project_id and generation_id.",
        )

    if str(classification.get("project_id") or "").strip() != project_id:
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_CLASSIFICATION_PROJECT_MISMATCH",
            "Classification project_id does not match author review.",
        )
    if str(classification.get("generation_id") or "").strip() != generation_id:
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_CLASSIFICATION_GENERATION_MISMATCH",
            "Classification generation_id does not match author review.",
        )
    if str(continuity.get("project_id") or "").strip() != project_id:
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_CONTINUITY_PROJECT_MISMATCH",
            "Approved Continuity project_id does not match author review.",
        )
    continuity_generation = str(continuity.get("generation_id") or "").strip()
    if continuity_generation and continuity_generation != generation_id:
        raise AuthorVoiceProvenanceGateError(
            "AUTHOR_VOICE_CONTINUITY_GENERATION_MISMATCH",
            "Approved Continuity generation_id does not match author review.",
        )

    terminal = review.get("terminal_event") or {}
    terminal_operation = str(terminal.get("operation") or "").strip()
    review_state = str(review.get("review_state") or "").strip()
    accepted_version_id = str(review.get("current_version_id") or "").strip()
    accepted_content_sha256 = str(review.get("current_content_sha256") or "").strip().lower()

    reasons: list[str] = []

    if review_state != "accepted_pending_approved_continuity":
        reasons.append("review_not_author_accepted")
    if terminal_operation != "AUTHOR_ACCEPT":
        reasons.append("terminal_author_accept_missing")

    if classification.get("assessment_status") != "classified":
        reasons.append("primary35_classification_not_complete")

    classification_version = str(
        classification.get("accepted_version_id") or ""
    ).strip()
    classification_hash = str(
        classification.get("accepted_content_sha256") or ""
    ).strip().lower()
    if accepted_version_id and classification_version != accepted_version_id:
        reasons.append("classification_version_mismatch")
    if accepted_content_sha256 and classification_hash != accepted_content_sha256:
        reasons.append("classification_content_hash_mismatch")

    if continuity.get("generation_committed") is not True:
        reasons.append("approved_continuity_not_committed")

    continuity_commit = continuity.get("generation_commit") or {}
    continuity_version = str(
        continuity_commit.get("accepted_version_id") or ""
    ).strip()
    continuity_hash = str(
        continuity_commit.get("accepted_content_sha256") or ""
    ).strip().lower()
    if continuity.get("generation_committed") is True:
        if accepted_version_id and continuity_version != accepted_version_id:
            reasons.append("approved_continuity_version_mismatch")
        if accepted_content_sha256 and continuity_hash != accepted_content_sha256:
            reasons.append("approved_continuity_content_hash_mismatch")

    final_state = str(classification.get("final_segment_state") or "").strip()
    if final_state not in ELIGIBLE_FINAL_SEGMENT_STATES:
        reasons.append("segment_not_substantively_author_rewritten")

    awarded = classification.get("awarded_level") or {}
    try:
        awarded_level = int(awarded.get("level"))
    except (TypeError, ValueError):
        awarded_level = 0
    if awarded_level not in ELIGIBLE_AWARDED_LEVELS:
        reasons.append("awarded_provenance_level_below_voice_gate")

    if final_state == "EXTERNAL_AUTHOR_REVISION":
        reasons.append("external_author_revision_not_active_author_voice")

    eligible = not reasons
    return {
        "status": "ok",
        "service": AUTHOR_VOICE_PROVENANCE_GATE_MARKER,
        "schema_version": AUTHOR_VOICE_GATE_SCHEMA_VERSION,
        "policy_version": AUTHOR_VOICE_GATE_POLICY_VERSION,
        "project_id": project_id,
        "generation_id": generation_id,
        "eligible_for_author_voice_learning": eligible,
        "decision": "eligible" if eligible else "ineligible",
        "reason_codes": reasons,
        "evidence": {
            "accepted_version_id": accepted_version_id or None,
            "accepted_content_sha256": accepted_content_sha256 or None,
            "review_state": review_state,
            "terminal_operation": terminal_operation or None,
            "classification_status": classification.get("assessment_status"),
            "final_segment_state": final_state or None,
            "awarded_level": awarded_level or None,
            "approved_continuity_committed": (
                continuity.get("generation_committed") is True
            ),
        },
        "authority": deepcopy(
            get_author_voice_provenance_gate_contract()["authority"]
        ),
    }
