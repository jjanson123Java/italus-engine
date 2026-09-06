"""
Primary 34 structured generation-candidate validation boundary.

This service validates the immutable provider receipt + MODEL-origin candidate
before author review. It is deterministic and read-only. It does not call a
provider, mutate Canon/runtime state, persist review decisions, write Approved
Continuity, score authorship, or make legal/copyright determinations.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from app.services import (
    authorship_provenance_service,
    provider_generation_receipt_service,
)


VALIDATION_SERVICE_MARKER = "primary34-structured-candidate-validator-v1"
VALIDATION_SCHEMA_VERSION = "primary34_candidate_validation_v1"
VALIDATION_CONTEXT_SCHEMA_VERSION = "primary34_validator_context_v1"
CANDIDATE_READY_STATE = "draft_ready_for_review"
CANDIDATE_BLOCKED_STATE = "draft_blocked"


class CandidateValidationError(RuntimeError):
    """Raised when a candidate cannot be resolved into a trustworthy review context."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code or "CANDIDATE_VALIDATION_FAILED")
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": deepcopy(self.details),
        }


def _required_generation_id(value: Any) -> str:
    generation_id = str(value or "").strip()
    if not generation_id:
        raise CandidateValidationError(
            "GENERATION_ID_REQUIRED",
            "generation_id is required.",
        )
    if any(ch in generation_id for ch in ("/", "\\", "\x00", "\r", "\n", "\t")):
        raise CandidateValidationError(
            "GENERATION_ID_INVALID",
            "generation_id contains illegal characters.",
        )
    if len(generation_id) > 200:
        raise CandidateValidationError(
            "GENERATION_ID_INVALID",
            "generation_id is too long.",
        )
    return generation_id


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _check(
    name: str,
    passed: bool,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "required": True,
        "code": "" if passed else code,
        "message": message,
        "details": deepcopy(details or {}),
    }


def _model_origin_for(
    project_id: str,
    *,
    generation_id: str,
    segment_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    records = authorship_provenance_service.get_segment_lineage_records(
        project_id,
        generation_id=generation_id,
        segment_id=segment_id,
    )
    origins = list(records.get("origins") or [])
    exact = [
        item
        for item in origins
        if str(item.get("generation_id") or "") == generation_id
        and str(item.get("segment_id") or "") == segment_id
        and str(item.get("origin_actor") or "")
        == authorship_provenance_service.ACTOR_MODEL
    ]
    return (deepcopy(exact[0]) if len(exact) == 1 else None, records)


def validate_generation_candidate(
    project_id: str,
    generation_id: str,
) -> dict[str, Any]:
    """Return the deterministic Primary 34 validator context for one candidate."""

    generation = _required_generation_id(generation_id)

    try:
        receipt = provider_generation_receipt_service.get_receipt(
            project_id,
            generation,
        )
    except provider_generation_receipt_service.ProviderGenerationReceiptError as exc:
        raise CandidateValidationError(
            "PROVIDER_RECEIPT_INVALID",
            str(exc),
            details={"generation_id": generation},
        ) from exc

    if receipt is None:
        raise CandidateValidationError(
            "PROVIDER_RECEIPT_NOT_FOUND",
            "No immutable provider receipt exists for this generation.",
            details={"generation_id": generation},
        )

    output_text = str(receipt.get("output_text") or "")
    output_sha256 = str(receipt.get("output_text_sha256") or "").strip().lower()
    actual_output_sha256 = hashlib.sha256(output_text.encode("utf-8")).hexdigest()

    try:
        book_number = int(receipt.get("book_number") or 0)
        chapter_number = int(receipt.get("chapter_number") or 0)
    except (TypeError, ValueError) as exc:
        raise CandidateValidationError(
            "CANDIDATE_POSITION_INVALID",
            "Provider receipt book/chapter position is invalid.",
            details={"generation_id": generation},
        ) from exc

    segment_id = f"segment_{generation}"
    origin, lineage_records = _model_origin_for(
        project_id,
        generation_id=generation,
        segment_id=segment_id,
    )

    origin_metadata = (
        deepcopy(origin.get("metadata") or {})
        if isinstance(origin, dict)
        else {}
    )
    usage_event = receipt.get("usage_event")
    usage_event = usage_event if isinstance(usage_event, dict) else {}

    checks = [
        _check(
            "provider_receipt_output_hash",
            bool(re.fullmatch(r"[0-9a-f]{64}", output_sha256))
            and output_sha256 == actual_output_sha256,
            "PROVIDER_RECEIPT_OUTPUT_HASH_MISMATCH",
            "Provider receipt output matches its immutable SHA-256.",
        ),
        _check(
            "candidate_position",
            book_number >= 1 and chapter_number >= 1,
            "CANDIDATE_POSITION_INVALID",
            "Provider candidate has a valid book/chapter position.",
            details={
                "book_number": book_number,
                "chapter_number": chapter_number,
            },
        ),
        _check(
            "model_origin_exactly_one",
            origin is not None,
            "MODEL_ORIGIN_NOT_UNIQUE",
            "Exactly one immutable MODEL origin exists for the generation candidate.",
            details={
                "matching_origin_count": sum(
                    1
                    for item in (lineage_records.get("origins") or [])
                    if str(item.get("generation_id") or "") == generation
                    and str(item.get("segment_id") or "") == segment_id
                    and str(item.get("origin_actor") or "")
                    == authorship_provenance_service.ACTOR_MODEL
                ),
            },
        ),
        _check(
            "model_origin_content_hash",
            bool(origin)
            and str(origin.get("content_hash") or "") == output_sha256,
            "MODEL_ORIGIN_CONTENT_HASH_MISMATCH",
            "MODEL origin content SHA-256 matches the immutable provider receipt.",
        ),
        _check(
            "model_origin_content",
            bool(origin)
            and str(origin.get("content") or "") == output_text,
            "MODEL_ORIGIN_CONTENT_MISMATCH",
            "MODEL origin content matches the immutable provider receipt.",
        ),
        _check(
            "model_origin_position",
            bool(origin)
            and int(origin.get("book_number") or 0) == book_number
            and int(origin.get("chapter_number") or 0) == chapter_number,
            "MODEL_ORIGIN_POSITION_MISMATCH",
            "MODEL origin book/chapter position matches the provider receipt.",
        ),
        _check(
            "model_origin_provider_identity",
            bool(origin)
            and str(origin.get("provider") or "") == str(receipt.get("provider_id") or "")
            and str(origin.get("provider_model") or "") == str(receipt.get("model_id") or ""),
            "MODEL_ORIGIN_PROVIDER_IDENTITY_MISMATCH",
            "MODEL origin provider/model identity matches the immutable provider receipt.",
        ),
        _check(
            "model_origin_candidate_state",
            bool(origin)
            and origin_metadata.get("candidate_schema_version")
            == "primary33-provider-candidate-v1"
            and origin_metadata.get("candidate_state")
            == "generated_pending_author_review"
            and origin_metadata.get("author_review_persisted") is False,
            "MODEL_ORIGIN_CANDIDATE_STATE_MISMATCH",
            "MODEL origin remains a Primary 33 candidate pending author review.",
        ),
        _check(
            "model_origin_immutable",
            bool(origin)
            and origin.get("immutable") is True
            and list(origin.get("parent_ids") or []) == [],
            "MODEL_ORIGIN_IMMUTABILITY_MISMATCH",
            "MODEL origin remains immutable and parentless.",
        ),
        _check(
            "receipt_lineage_binding",
            bool(origin)
            and origin_metadata.get("provider_receipt_sha256")
            == receipt.get("receipt_sha256")
            and origin_metadata.get("request_content_sha256")
            == receipt.get("request_content_sha256")
            and origin_metadata.get("prompt_sha256")
            == receipt.get("prompt_sha256")
            and origin_metadata.get("binding_instance_id")
            == receipt.get("binding_instance_id")
            and origin_metadata.get("credential_instance_id")
            == receipt.get("credential_instance_id")
            and origin_metadata.get("pricing_version_id")
            == receipt.get("pricing_version_id")
            and origin_metadata.get("pricing_version_sha256")
            == receipt.get("pricing_version_sha256")
            and origin_metadata.get("usage_event_id")
            == usage_event.get("usage_event_id"),
            "MODEL_ORIGIN_RECEIPT_LINEAGE_MISMATCH",
            "MODEL origin metadata is bound to the exact immutable receipt lineage.",
        ),
        _check(
            "approved_continuity_not_committed",
            receipt.get("approved_continuity_committed") is False
            and origin_metadata.get("approved_continuity_committed") is False,
            "APPROVED_CONTINUITY_BOUNDARY_VIOLATION",
            "Candidate has not been committed to Approved Continuity.",
        ),
    ]

    blocking = [item for item in checks if item["required"] and not item["passed"]]
    ready = not blocking

    model_origin_version_id = (
        str(origin.get("version_id") or "") if isinstance(origin, dict) else ""
    )
    model_origin_id = (
        str(origin.get("origin_id") or "") if isinstance(origin, dict) else ""
    )

    validator_context = {
        "schema_version": VALIDATION_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generation_id": generation,
        "segment_id": segment_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "candidate_content_sha256": output_sha256,
        "model_origin_id": model_origin_id,
        "model_origin_version_id": model_origin_version_id,
        "provider_receipt_sha256": receipt.get("receipt_sha256"),
        "request_content_sha256": receipt.get("request_content_sha256"),
        "prompt_sha256": receipt.get("prompt_sha256"),
        "provider_id": receipt.get("provider_id"),
        "model_id": receipt.get("model_id"),
        "binding_instance_id": receipt.get("binding_instance_id"),
        "credential_instance_id": receipt.get("credential_instance_id"),
        "pricing_version_id": receipt.get("pricing_version_id"),
        "pricing_version_sha256": receipt.get("pricing_version_sha256"),
        "usage_event_id": usage_event.get("usage_event_id"),
    }
    validator_context["context_sha256"] = _canonical_sha256(validator_context)

    report = {
        "status": "ok",
        "service": VALIDATION_SERVICE_MARKER,
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "project_id": project_id,
        "generation_id": generation,
        "review_state": (
            CANDIDATE_READY_STATE if ready else CANDIDATE_BLOCKED_STATE
        ),
        "ready_for_author_review": ready,
        "checks": checks,
        "blockers": [
            {
                "code": item["code"],
                "check": item["name"],
                "message": item["message"],
            }
            for item in blocking
        ],
        "validator_context": validator_context,
        "candidate": {
            "segment_id": segment_id,
            "model_origin_id": model_origin_id,
            "model_origin_version_id": model_origin_version_id,
            "content_type": "text/plain",
            "text": output_text,
            "sha256": output_sha256,
        },
        "review_actions": ["accept", "edit", "reject"] if ready else [],
        "authority": {
            "provider_output_is_candidate_only": True,
            "backend_validation_authoritative_for_review_gate": True,
            "writes_author_review": False,
            "writes_approved_continuity": False,
            "mutates_canon": False,
            "mutates_runtime_story_state": False,
            "calls_provider": False,
        },
    }
    report["validation_report_sha256"] = _canonical_sha256(report)
    return report
