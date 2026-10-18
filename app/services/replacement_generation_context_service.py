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

from app.services import (
    author_review_service,
    candidate_semantic_validation_store_service,
)


REPLACEMENT_CONTEXT_SERVICE_MARKER = "primary45c-replacement-correction-context-v2"
REPLACEMENT_CONTEXT_SCHEMA_VERSION = "replacement_correction_context_v2"
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



def _audited_semantic_failures(
    project_id: str,
    generation_id: str,
    *,
    rejected_content_sha256: str,
    validator_contract_sha256: str,
    validation: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    exact_receipts = [
        receipt
        for receipt in candidate_semantic_validation_store_service.receipts_for_generation(
            project_id, generation_id
        )
        if str(receipt.get("content_sha256") or "").lower() == rejected_content_sha256
        and str(receipt.get("validator_contract_sha256") or "").lower()
        == validator_contract_sha256
        and isinstance(receipt.get("verdicts"), list)
        and bool(receipt.get("verdicts"))
    ]
    if not exact_receipts:
        return [], []

    rule_map = {
        str(item.get("rule_id") or ""): item
        for item in (validation.get("content_rules") or [])
        if isinstance(item, dict)
    }
    observed: dict[str, set[str]] = {}
    fail_sources: dict[str, dict[str, Any]] = {}
    for receipt in exact_receipts:
        for verdict in receipt.get("verdicts") or []:
            if not isinstance(verdict, dict):
                continue
            rule_id = str(verdict.get("rule_id") or "")
            verdict_value = str(verdict.get("verdict") or "")
            if not rule_id or verdict_value not in {"PASS", "FAIL", "UNKNOWN"}:
                continue
            observed.setdefault(rule_id, set()).add(verdict_value)
            if verdict_value == "FAIL":
                fail_sources[rule_id] = receipt

    failures: list[dict[str, Any]] = []
    for rule_id in sorted(observed):
        # Conflicting semantic verdicts are not promoted into generation authority.
        if observed[rule_id] != {"FAIL"}:
            continue
        rule = rule_map.get(rule_id) or {}
        receipt = fail_sources.get(rule_id) or {}
        failures.append({
            "rule_id": rule_id,
            "rule_type": str(rule.get("rule_type") or ""),
            "message": "Prior rejected draft failed this audited semantic rule.",
            "instruction": str(rule.get("instruction") or ""),
            "semantic_validation_id": str(receipt.get("semantic_validation_id") or ""),
            "semantic_receipt_sha256": str(receipt.get("receipt_sha256") or ""),
        })
    return failures, [
        str(receipt.get("semantic_validation_id") or "") for receipt in exact_receipts
    ]


def build_replacement_correction_context(
    project_id: str,
    rejected_generation_id: str,
    *,
    book_number: int,
    chapter_number: int,
    repair_from_quality_receipt: bool = False,
) -> dict[str, Any]:
    """Build trusted correction evidence for author rejection or bounded mechanical repair."""

    generation_id = _generation_id(rejected_generation_id)
    if repair_from_quality_receipt:
        # This is not an author-rejected replacement. The provider receipt is
        # the only authority for a completed, mechanically failed source.
        from app.services import provider_generation_receipt_service

        receipt = provider_generation_receipt_service.get_receipt(project_id, generation_id)
        if not isinstance(receipt, dict):
            raise ReplacementGenerationContextError(
                "REPAIR_SOURCE_RECEIPT_MISSING", "A committed provider receipt is required."
            )
        if (
            int(receipt.get("book_number") or 0) != int(book_number)
            or int(receipt.get("chapter_number") or 0) != int(chapter_number)
        ):
            raise ReplacementGenerationContextError(
                "REPAIR_SOURCE_POSITION_MISMATCH", "Repair source is not the requested chapter."
            )
        text = str(receipt.get("output_text") or "")
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        report = receipt.get("generation_quality_gate")
        blockers = (report or {}).get("blockers") if isinstance(report, dict) else None
        if (
            not text.strip()
            or text_hash != str(receipt.get("output_text_sha256") or "").lower()
            or not isinstance(blockers, list)
            or not blockers
            or report.get("passed") is not False
            or any(
                not isinstance(item, dict) or item.get("code") != "DETERMINISTIC_PROSE_FAILURE"
                for item in blockers
            )
            or str(receipt.get("stop_reason") or "").lower()
            in {"max_tokens", "max_output_tokens", "length", "token_limit"}
            or receipt.get("repair_for_generation_id")
        ):
            raise ReplacementGenerationContextError(
                "REPAIR_SOURCE_NOT_ELIGIBLE",
                "Only an original, completed provider draft with deterministic failures can be repaired.",
            )
        failures = [
            {
                "rule_id": "prose." + str(item.get("metric") or ""),
                "message": str(item.get("message") or ""),
                "instruction": "Meet the exact deterministic prose limit.",
                "details": {
                    key: item[key]
                    for key in ("metric", "measurement", "operator", "threshold")
                    if key in item
                },
            }
            for item in blockers
        ]
        context = {
            "schema_version": REPLACEMENT_CONTEXT_SCHEMA_VERSION,
            "service": REPLACEMENT_CONTEXT_SERVICE_MARKER,
            "authority": "backend_derived_mechanical_repair",
            "source_generation_id": generation_id,
            "source_review_event_id": "",
            "source_review_version_id": "",
            "book_number": int(book_number),
            "chapter_number": int(chapter_number),
            "rejected_content_sha256": text_hash,
            "source_validator_sidecar_sha256": str(receipt.get("validator_sidecar_sha256") or ""),
            "source_request_content_sha256": str(receipt.get("request_content_sha256") or ""),
            "deterministic_failures": failures,
            "deterministic_failure_count": len(failures),
            "deterministic_failure_source": "committed_provider_quality_receipt",
            "audited_semantic_failures": [],
            "audited_semantic_failure_count": 0,
            "semantic_receipt_ids_considered": [],
            "manual_semantic_rules_promoted": False,
            "unknown_semantic_rules_promoted": False,
            "rejected_prose_included": False,
            "instructions": [
                "Generate a new independent draft from current authorized chapter guidance.",
                "Correct every measured prose failure without reusing the original prose.",
                "Do not infer any semantic failure from deterministic measurement alone.",
            ],
        }
        context["context_sha256"] = _sha256(context)
        return context

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

    validator_contract_sha256 = str(
        validator_context.get("validator_contract_sha256") or ""
    ).lower()
    semantic_failures, semantic_receipt_ids = _audited_semantic_failures(
        project_id,
        generation_id,
        rejected_content_sha256=rejected_content_sha256,
        validator_contract_sha256=validator_contract_sha256,
        validation=validation,
    )

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
        "audited_semantic_failures": semantic_failures,
        "audited_semantic_failure_count": len(semantic_failures),
        "semantic_receipt_ids_considered": semantic_receipt_ids,
        "manual_semantic_rules_promoted": bool(semantic_failures),
        "unknown_semantic_rules_promoted": False,
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
                "Do not repeat any listed audited semantic failure. These FAIL verdicts "
                "were bound to the exact rejected content and validator contract."
            ),
            (
                "Do not infer violations from UNKNOWN semantic items. UNKNOWN remains "
                "unpromoted and the rejected prose itself is not included."
            ),
        ],
    }
    context["context_sha256"] = _sha256(context)
    return context
