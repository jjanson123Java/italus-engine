"""Primary 44 rejection-aware replacement correction context.

The browser may identify only the rejected generation. This service derives the
correction context from backend-owned author-review and validation evidence.
Only deterministic validation failures are promoted into replacement
instructions. MANUAL/SEMANTIC/UNKNOWN rules are never converted into violations.
The rejected prose itself is never copied into the provider prompt.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from app.services import author_review_service


REPLACEMENT_CONTEXT_SERVICE_MARKER = "primary44-replacement-correction-context-v1"
REPLACEMENT_CONTEXT_SCHEMA_VERSION = "replacement_correction_context_v1"
_GENERATION_ID_RE = re.compile(r"^gen_[0-9a-f]{32}$")


class ReplacementGenerationContextError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = str(code)
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": deepcopy(self.details)}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _generation_id(value: Any) -> str:
    generation_id = str(value or "").strip()
    if not _GENERATION_ID_RE.fullmatch(generation_id):
        raise ReplacementGenerationContextError(
            "REPLACEMENT_SOURCE_GENERATION_INVALID",
            "replacement_for_generation_id must be a valid generation identifier.",
        )
    return generation_id


def _failure_projection(item: dict[str, Any]) -> dict[str, Any]:
    details = item.get("details")
    details = details if isinstance(details, dict) else {}
    projected_details = {
        key: details.get(key)
        for key in (
            "metric",
            "measurement",
            "operator",
            "threshold",
            "required_reduction",
        )
        if details.get(key) is not None
    }
    return {
        "rule_id": str(item.get("rule_id") or ""),
        "message": str(item.get("message") or ""),
        "instruction": str(item.get("instruction") or ""),
        "details": projected_details,
    }


def build_replacement_correction_context(
    project_id: str,
    rejected_generation_id: str,
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    """Build trusted, bounded correction evidence for one rejected candidate."""

    generation_id = _generation_id(rejected_generation_id)
    review = author_review_service.get_author_review_status(project_id, generation_id)
    if review.get("terminal") is not True or str(review.get("review_state") or "") != "rejected":
        raise ReplacementGenerationContextError(
            "REPLACEMENT_SOURCE_NOT_REJECTED",
            "Replacement generation requires a terminally rejected source candidate.",
            details={"generation_id": generation_id},
        )

    validation = review.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    validator_context = validation.get("validator_context")
    validator_context = validator_context if isinstance(validator_context, dict) else {}
    source_book = int(validator_context.get("book_number") or 0)
    source_chapter = int(validator_context.get("chapter_number") or 0)
    if source_book != int(book_number) or source_chapter != int(chapter_number):
        raise ReplacementGenerationContextError(
            "REPLACEMENT_SOURCE_POSITION_MISMATCH",
            "Rejected candidate position does not match the requested replacement position.",
            details={
                "generation_id": generation_id,
                "source_book_number": source_book,
                "source_chapter_number": source_chapter,
                "requested_book_number": int(book_number),
                "requested_chapter_number": int(chapter_number),
            },
        )

    terminal = review.get("terminal_event")
    terminal = terminal if isinstance(terminal, dict) else {}
    rejected_content_sha256 = str(review.get("current_content_sha256") or "").lower()
    terminal_after_hash = str(terminal.get("after_hash") or "").lower()
    if (
        str(terminal.get("operation") or "") != "AUTHOR_REJECT"
        or str(terminal.get("source_generation_id") or "") != generation_id
        or not rejected_content_sha256
        or terminal_after_hash != rejected_content_sha256
    ):
        raise ReplacementGenerationContextError(
            "REPLACEMENT_REJECTION_EVIDENCE_INVALID",
            "Rejected candidate lineage is not bound to the exact current rejected content.",
            details={"generation_id": generation_id},
        )

    validated_content_sha256 = str(
        validator_context.get("candidate_content_sha256") or ""
    ).lower()
    if validated_content_sha256 != rejected_content_sha256:
        raise ReplacementGenerationContextError(
            "REPLACEMENT_VALIDATION_CONTENT_MISMATCH",
            "Replacement correction validation is not bound to the exact rejected content.",
            details={
                "generation_id": generation_id,
                "rejected_content_sha256": rejected_content_sha256,
                "validated_content_sha256": validated_content_sha256,
            },
        )

    current_deterministic_failures = [
        _failure_projection(item)
        for item in list(validation.get("content_rules") or [])
        if isinstance(item, dict)
        and str(item.get("evaluation_mode") or "") == "DETERMINISTIC"
        and str(item.get("severity") or "") == "BLOCKER"
        and str(item.get("status") or "") != "PASS"
    ]

    metadata = terminal.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    rejection_validation = metadata.get("rejection_validation")
    rejection_validation = (
        deepcopy(rejection_validation) if isinstance(rejection_validation, dict) else {}
    )
    rejection_failures = rejection_validation.get("deterministic_failures")
    rejection_failures = (
        deepcopy(rejection_failures) if isinstance(rejection_failures, list) else []
    )
    rejection_validated_sha256 = str(
        rejection_validation.get("validated_content_sha256") or ""
    ).lower()
    if rejection_validation and rejection_validated_sha256 != rejected_content_sha256:
        raise ReplacementGenerationContextError(
            "REPLACEMENT_REJECTION_VALIDATION_MISMATCH",
            "Rejection-time validation is not bound to the exact rejected content.",
            details={
                "generation_id": generation_id,
                "rejected_content_sha256": rejected_content_sha256,
                "rejection_validated_content_sha256": rejection_validated_sha256,
            },
        )
    if rejection_validation:
        deterministic_failures = rejection_failures
        deterministic_failure_source = "rejection_time_validation"
    else:
        deterministic_failures = current_deterministic_failures
        deterministic_failure_source = "exact_content_revalidation"

    context = {
        "schema_version": REPLACEMENT_CONTEXT_SCHEMA_VERSION,
        "service": REPLACEMENT_CONTEXT_SERVICE_MARKER,
        "authority": "backend_derived_rejection_correction",
        "source_generation_id": generation_id,
        "source_review_event_id": str(terminal.get("event_id") or ""),
        "source_review_version_id": str(terminal.get("version_id") or ""),
        "book_number": source_book,
        "chapter_number": source_chapter,
        "rejected_content_sha256": rejected_content_sha256,
        "rejection_validation_report_sha256": str(
            metadata.get("validation_report_sha256") or ""
        ),
        "rejection_validation": rejection_validation,
        "current_revalidation": {
            "validation_run_id": str(validation.get("validation_run_id") or ""),
            "validation_result_sha256": str(validation.get("validation_result_sha256") or ""),
            "validation_report_sha256": str(validation.get("validation_report_sha256") or ""),
            "validated_content_version_id": str(
                validator_context.get("current_content_version_id") or ""
            ),
            "validated_content_sha256": str(
                validator_context.get("candidate_content_sha256") or ""
            ),
            "validator_contract_sha256": str(
                validator_context.get("validator_contract_sha256") or ""
            ),
        },
        "deterministic_failures": deterministic_failures,
        "deterministic_failure_count": len(deterministic_failures),
        "deterministic_failure_source": deterministic_failure_source,
        "manual_semantic_rules_promoted": False,
        "rejected_prose_included": False,
        "instructions": [
            (
                "Generate a new draft from the current chapter authority; do not copy, "
                "continue, paraphrase, or repair the rejected prose."
            ),
            (
                "Correct every listed deterministic failure while still obeying the "
                "current generation guardrails."
            ),
            (
                "Do not infer prior canon, narrative, reveal, POV, or Story Control "
                "violations from unresolved MANUAL/SEMANTIC/UNKNOWN validation items."
            ),
        ],
    }
    context["context_sha256"] = _sha256(context)
    return context
