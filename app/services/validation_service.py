"""
Structured generation-candidate validation and author-acceptance gate.

Integrity validation remains bound to the immutable provider receipt and MODEL
origin. Content validation is bound to the exact current substantive lineage
version and the exact validator_sidecar used for the generation. Deterministic
rules are enforced directly; narrative rules remain explicit MANUAL/SEMANTIC
requirements until an audited author resolution exists.

This service is read-only. It does not call providers, write review decisions,
write Approved Continuity, mutate Canon/runtime story state, or update Author
Voice.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from app.services import (
    authorship_provenance_service,
    candidate_validation_evidence_service,
    candidate_validation_contract_service,
    candidate_validation_resolution_service,
    candidate_semantic_validation_store_service,
    chapter_knowledge_pack_service,
    prose_rulebook_service,
    provider_generation_receipt_service,
)


VALIDATION_SERVICE_MARKER = "candidate-validator-v3-primary45-20260920"
VALIDATION_SCHEMA_VERSION = "candidate_validation_v3"
VALIDATION_CONTEXT_SCHEMA_VERSION = "candidate_validator_context_v2"
VALIDATION_EVALUATOR_VERSION = "candidate_content_evaluator_v2_semantic"

VALIDATION_STATE_INTEGRITY_BLOCKED = "integrity_blocked"
VALIDATION_STATE_CONTENT_FAILED = "content_failed"
VALIDATION_STATE_SEMANTIC_UNRESOLVED = "semantic_unresolved"
VALIDATION_STATE_ACCEPTANCE_READY = "acceptance_ready"

CANDIDATE_READY_STATE = "draft_ready_for_review"
CANDIDATE_BLOCKED_STATE = "draft_blocked"

_TERMINAL_OPERATIONS = frozenset({"AUTHOR_ACCEPT", "AUTHOR_REJECT"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _integrity_check(
    name: str,
    passed: bool,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "rule_id": f"integrity.{name}",
        "rule_type": "INTEGRITY",
        "source_type": "PROVIDER_PROVENANCE",
        "source_ref": "",
        "evaluation_mode": "DETERMINISTIC",
        "severity": "BLOCKER",
        "status": "PASS" if passed else "FAIL",
        "passed": bool(passed),
        "required": True,
        "code": "" if passed else code,
        "message": message,
        "instruction": message,
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


def _event_by_version(
    records: dict[str, Any],
    version_id: str,
) -> dict[str, Any] | None:
    for event in records.get("events") or []:
        if str(event.get("version_id") or "") == version_id:
            return deepcopy(event)
    return None


def _origin_by_version(
    records: dict[str, Any],
    version_id: str,
) -> dict[str, Any] | None:
    for origin in records.get("origins") or []:
        if str(origin.get("version_id") or "") == version_id:
            return deepcopy(origin)
    return None


def _version_content(
    records: dict[str, Any],
    version_id: str,
) -> tuple[str, str]:
    origin = _origin_by_version(records, version_id)
    if origin is not None:
        content = origin.get("content")
        if not isinstance(content, str) or not content.strip():
            raise CandidateValidationError(
                "CANDIDATE_LINEAGE_CONTENT_MISSING",
                "Current MODEL lineage version has no recoverable content.",
                details={"version_id": version_id},
            )
        return content, str(origin.get("origin_actor") or "MODEL")

    event = _event_by_version(records, version_id)
    if event is None or "content_after" not in event:
        raise CandidateValidationError(
            "CANDIDATE_LINEAGE_CONTENT_MISSING",
            "Current lineage version has no recoverable content.",
            details={"version_id": version_id},
        )
    content = event.get("content_after")
    if not isinstance(content, str) or not content.strip():
        raise CandidateValidationError(
            "CANDIDATE_LINEAGE_CONTENT_MISSING",
            "Current lineage version content is empty.",
            details={"version_id": version_id},
        )
    return content, str(event.get("actor") or "")


def _current_substantive_content(
    records: dict[str, Any],
) -> dict[str, Any]:
    versions = dict(records.get("versions") or {})
    if not versions:
        raise CandidateValidationError(
            "CANDIDATE_LINEAGE_MISSING",
            "Candidate provenance lineage has no versions.",
        )

    parent_ids = {
        str(parent)
        for version in versions.values()
        for parent in (version.get("parent_version_ids") or [])
        if str(parent or "")
    }
    tips = [
        str(version_id)
        for version_id in versions
        if str(version_id) not in parent_ids
    ]
    if len(tips) != 1:
        raise CandidateValidationError(
            "CANDIDATE_LINEAGE_AMBIGUOUS",
            "Candidate lineage must have exactly one current tip.",
            details={"tip_count": len(tips)},
        )

    lineage_tip_version_id = tips[0]
    validation_version_id = lineage_tip_version_id
    terminal_operation = ""
    tip_event = _event_by_version(records, lineage_tip_version_id)
    if (
        tip_event is not None
        and str(tip_event.get("operation") or "") in _TERMINAL_OPERATIONS
    ):
        parents = [
            str(item)
            for item in (tip_event.get("parent_version_ids") or [])
            if str(item or "")
        ]
        if len(parents) != 1 or parents[0] not in versions:
            raise CandidateValidationError(
                "CANDIDATE_TERMINAL_PARENT_INVALID",
                "Terminal review event does not identify one substantive parent version.",
                details={"version_id": lineage_tip_version_id},
            )
        terminal_operation = str(tip_event.get("operation") or "")
        validation_version_id = parents[0]

    content, actor = _version_content(records, validation_version_id)
    return {
        "lineage_tip_version_id": lineage_tip_version_id,
        "content_version_id": validation_version_id,
        "content": content,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content_actor": actor,
        "terminal_operation": terminal_operation,
    }


def _resolved_rule_map(
    project_id: str,
    generation_id: str,
    *,
    content_version_id: str,
    content_sha256: str,
    validator_contract_sha256: str,
) -> dict[str, dict[str, Any]]:
    try:
        resolutions = candidate_validation_resolution_service.get_author_resolutions(
            project_id,
            generation_id,
            content_version_id=content_version_id,
            content_sha256=content_sha256,
            validator_contract_sha256=validator_contract_sha256,
        )
    except candidate_validation_resolution_service.CandidateValidationResolutionError as exc:
        raise CandidateValidationError(
            "VALIDATION_RESOLUTION_STORE_INVALID",
            str(exc),
        ) from exc

    result: dict[str, dict[str, Any]] = {}
    for item in resolutions:
        rule_id = str(item.get("rule_id") or "")
        if not rule_id:
            continue
        if rule_id in result:
            raise CandidateValidationError(
                "VALIDATION_RESOLUTION_DUPLICATE",
                "Multiple author resolutions exist for the same exact rule/content identity.",
                details={"rule_id": rule_id},
            )
        result[rule_id] = deepcopy(item)
    return result


def _content_rule_results(
    validator_sidecar: dict[str, Any],
    *,
    current_content: str,
    resolutions: dict[str, dict[str, Any]],
    semantic_verdicts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    embedded = validator_sidecar.get("validation_rules")
    if isinstance(embedded, list):
        rules = [deepcopy(item) for item in embedded if isinstance(item, dict)]
    else:
        rules = chapter_knowledge_pack_service.build_candidate_validation_rules(
            validator_sidecar
        )

    prose = validator_sidecar.get("prose_rulebook")
    prose = prose if isinstance(prose, dict) else {}
    metrics = prose.get("quantitative_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}

    try:
        deterministic_metrics = prose_rulebook_service.evaluate_deterministic_metrics(
            current_content,
            metrics,
        )
    except prose_rulebook_service.ProseRulebookError as exc:
        raise CandidateValidationError(
            "PROSE_RULEBOOK_EVALUATION_FAILED",
            str(exc),
        ) from exc

    results: list[dict[str, Any]] = []
    for rule in rules:
        rule_id = str(rule.get("rule_id") or "").strip()
        if not rule_id:
            raise CandidateValidationError(
                "VALIDATION_RULE_ID_MISSING",
                "Validator contract contains a rule without rule_id.",
            )
        mode = str(rule.get("evaluation_mode") or "").strip().upper()
        severity = str(rule.get("severity") or "").strip().upper() or "BLOCKER"
        rule_type = str(rule.get("rule_type") or "").strip()
        instruction = str(rule.get("instruction") or "").strip()
        parameters = rule.get("parameters")
        parameters = deepcopy(parameters) if isinstance(parameters, dict) else {}

        status = "UNKNOWN"
        passed = False
        code = "VALIDATION_RULE_UNRESOLVED"
        message = instruction or "Validation rule requires resolution."
        details: dict[str, Any] = {}
        resolution: dict[str, Any] | None = None

        if mode == "DETERMINISTIC":
            if rule_type != "PROSE_QUANTITATIVE_METRIC":
                status = "UNKNOWN"
                code = "DETERMINISTIC_RULE_UNSUPPORTED"
                message = (
                    "Deterministic rule type is not supported by this evaluator."
                )
            else:
                metric_name = str(parameters.get("metric") or "")
                result = deterministic_metrics.get(metric_name)
                if not isinstance(result, dict):
                    raise CandidateValidationError(
                        "DETERMINISTIC_METRIC_RESULT_MISSING",
                        "Deterministic prose metric result is missing.",
                        details={"rule_id": rule_id, "metric": metric_name},
                    )
                passed = result.get("passed") is True
                status = "PASS" if passed else "FAIL"
                code = "" if passed else "PROSE_RULE_HARD_LIMIT_FAILED"
                message = str(result.get("message") or instruction)
                details = deepcopy(result)
                evidence = (
                    candidate_validation_evidence_service.deterministic_metric_evidence(
                        current_content,
                        metric_name,
                    )
                )
                if evidence:
                    details["evidence"] = evidence
                if not passed and str(result.get("operator") or "") == "hard_maximum":
                    details["required_reduction"] = max(
                        0,
                        int(result.get("measurement") or 0)
                        - int(result.get("threshold") or 0),
                    )
        elif mode in {"MANUAL", "SEMANTIC"}:
            resolution = resolutions.get(rule_id)
            semantic_verdict = semantic_verdicts.get(rule_id)
            if (
                isinstance(resolution, dict)
                and str(resolution.get("decision") or "")
                == candidate_validation_resolution_service.AUTHOR_CONFIRMED_COMPLIANT
            ):
                passed = True
                status = "PASS"
                code = ""
                message = (
                    "Author explicitly confirmed this rule for the exact current "
                    "content version."
                )
                details = {
                    "resolution_authority": "author_confirmed_compliant",
                    "semantic_verdict_produced": False,
                }
            elif isinstance(semantic_verdict, dict):
                verdict = str(semantic_verdict.get("verdict") or "").upper()
                rationale = str(semantic_verdict.get("rationale") or "")
                evidence_excerpts = [
                    str(value)
                    for value in (semantic_verdict.get("evidence_excerpts") or [])
                    if str(value)
                ]
                if verdict == "PASS":
                    passed = True
                    status = "PASS"
                    code = ""
                    message = rationale or "Audited semantic validation passed this rule."
                elif verdict == "FAIL":
                    passed = False
                    status = "FAIL"
                    code = "SEMANTIC_VALIDATION_FAILED"
                    message = rationale or "Audited semantic validation found a rule violation."
                else:
                    passed = False
                    status = "UNKNOWN"
                    code = "SEMANTIC_VALIDATION_UNRESOLVED"
                    message = rationale or (
                        "Audited semantic validation could not resolve this rule reliably."
                    )
                semantic_evidence = []
                for excerpt in evidence_excerpts:
                    start_offset = current_content.find(excerpt)
                    if start_offset < 0:
                        continue
                    end_offset = start_offset + len(excerpt)
                    context_start = max(0, start_offset - 160)
                    context_end = min(len(current_content), end_offset + 160)
                    semantic_evidence.append(
                        {
                            "evidence_type": "audited_semantic_exact_excerpt",
                            "start_offset": start_offset,
                            "end_offset": end_offset,
                            "context_start_offset": context_start,
                            "context_end_offset": context_end,
                            "matched_text": excerpt,
                            "excerpt": current_content[context_start:context_end],
                        }
                    )
                details = {
                    "semantic_verdict_produced": True,
                    "semantic_verdict": verdict or "UNKNOWN",
                    "semantic_rationale": rationale,
                    "semantic_evidence_excerpts": evidence_excerpts,
                    "evidence": semantic_evidence,
                    "evidence_assessment": "audited_semantic_exact_excerpt",
                    "semantic_validation_id": str(
                        semantic_verdict.get("semantic_validation_id") or ""
                    ),
                    "provider_id": str(semantic_verdict.get("provider_id") or ""),
                    "model_id": str(semantic_verdict.get("model_id") or ""),
                    "evidence_notice": (
                        "Semantic FAIL evidence is required to be an exact substring of "
                        "the candidate. PASS/UNKNOWN remain bounded to the audited provider "
                        "receipt for this exact content and validator contract."
                    ),
                }
            else:
                status = "UNKNOWN"
                code = (
                    "MANUAL_VALIDATION_REQUIRED"
                    if mode == "MANUAL"
                    else "SEMANTIC_VALIDATION_UNRESOLVED"
                )
                message = instruction or (
                    "Narrative validation requires explicit author resolution."
                )
                related = candidate_validation_evidence_service.related_narrative_evidence(
                    current_content,
                    instruction,
                )
                details = {
                    "evidence": related,
                    "evidence_assessment": "related_passages_only",
                    "semantic_verdict_produced": False,
                    "evidence_notice": (
                        "Related passages are retrieval aids for author review; they do "
                        "not prove that this narrative rule passed or failed."
                    ),
                }
        else:
            status = "UNKNOWN"
            code = "VALIDATION_MODE_UNSUPPORTED"
            message = "Validator contract contains an unsupported evaluation mode."

        result_item = {
            "name": rule_id,
            "rule_id": rule_id,
            "rule_type": rule_type,
            "source_type": str(rule.get("source_type") or ""),
            "source_ref": str(rule.get("source_ref") or ""),
            "evaluation_mode": mode or "UNKNOWN",
            "severity": severity,
            "status": status,
            "passed": passed,
            "required": severity == "BLOCKER",
            "code": code,
            "message": message,
            "instruction": instruction,
            "details": details,
        }
        if resolution is not None:
            result_item["resolution"] = {
                "resolution_id": str(resolution.get("resolution_id") or ""),
                "decision": str(resolution.get("decision") or ""),
                "author_note": str(resolution.get("author_note") or ""),
                "created_at": str(resolution.get("created_at") or ""),
            }
        results.append(result_item)
    return results


def validate_generation_candidate(
    project_id: str,
    generation_id: str,
) -> dict[str, Any]:
    """Return validation for the exact current substantive candidate version."""

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

    integrity_checks = [
        _integrity_check(
            "provider_receipt_output_hash",
            bool(_SHA256_RE.fullmatch(output_sha256))
            and output_sha256 == actual_output_sha256,
            "PROVIDER_RECEIPT_OUTPUT_HASH_MISMATCH",
            "Provider receipt output matches its immutable SHA-256.",
        ),
        _integrity_check(
            "candidate_position",
            book_number >= 1 and chapter_number >= 1,
            "CANDIDATE_POSITION_INVALID",
            "Provider candidate has a valid book/chapter position.",
            details={
                "book_number": book_number,
                "chapter_number": chapter_number,
            },
        ),
        _integrity_check(
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
        _integrity_check(
            "model_origin_content_hash",
            bool(origin)
            and str(origin.get("content_hash") or "") == output_sha256,
            "MODEL_ORIGIN_CONTENT_HASH_MISMATCH",
            "MODEL origin content SHA-256 matches the immutable provider receipt.",
        ),
        _integrity_check(
            "model_origin_content",
            bool(origin)
            and str(origin.get("content") or "") == output_text,
            "MODEL_ORIGIN_CONTENT_MISMATCH",
            "MODEL origin content matches the immutable provider receipt.",
        ),
        _integrity_check(
            "model_origin_position",
            bool(origin)
            and int(origin.get("book_number") or 0) == book_number
            and int(origin.get("chapter_number") or 0) == chapter_number,
            "MODEL_ORIGIN_POSITION_MISMATCH",
            "MODEL origin book/chapter position matches the provider receipt.",
        ),
        _integrity_check(
            "model_origin_provider_identity",
            bool(origin)
            and str(origin.get("provider") or "")
            == str(receipt.get("provider_id") or "")
            and str(origin.get("provider_model") or "")
            == str(receipt.get("model_id") or ""),
            "MODEL_ORIGIN_PROVIDER_IDENTITY_MISMATCH",
            "MODEL origin provider/model identity matches the immutable provider receipt.",
        ),
        _integrity_check(
            "model_origin_candidate_state",
            bool(origin)
            and origin_metadata.get("candidate_schema_version")
            == "primary33-provider-candidate-v1"
            and origin_metadata.get("candidate_state")
            == "generated_pending_author_review"
            and origin_metadata.get("author_review_persisted") is False,
            "MODEL_ORIGIN_CANDIDATE_STATE_MISMATCH",
            "MODEL origin remains a provider candidate pending author review.",
        ),
        _integrity_check(
            "model_origin_immutable",
            bool(origin)
            and origin.get("immutable") is True
            and list(origin.get("parent_ids") or []) == [],
            "MODEL_ORIGIN_IMMUTABILITY_MISMATCH",
            "MODEL origin remains immutable and parentless.",
        ),
        _integrity_check(
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
        _integrity_check(
            "approved_continuity_not_committed",
            receipt.get("approved_continuity_committed") is False
            and origin_metadata.get("approved_continuity_committed") is False,
            "APPROVED_CONTINUITY_BOUNDARY_VIOLATION",
            "Candidate has not been committed to Approved Continuity by provider execution.",
        ),
    ]

    integrity_blocking = [
        item
        for item in integrity_checks
        if item["required"] and item["status"] != "PASS"
    ]
    reviewable = not integrity_blocking

    model_origin_version_id = (
        str(origin.get("version_id") or "") if isinstance(origin, dict) else ""
    )
    model_origin_id = (
        str(origin.get("origin_id") or "") if isinstance(origin, dict) else ""
    )

    current = _current_substantive_content(lineage_records)
    current_version_id = str(current["content_version_id"])
    current_content = str(current["content"])
    current_content_sha256 = str(current["content_sha256"])

    contract: dict[str, Any] | None = None
    contract_error = ""
    try:
        contract = (
            candidate_validation_contract_service.resolve_generation_validator_contract(
                project_id,
                generation,
                receipt=receipt,
            )
        )
    except candidate_validation_contract_service.CandidateValidationContractError as exc:
        contract_error = str(exc)

    content_rules: list[dict[str, Any]] = []
    contract_blocker: dict[str, Any] | None = None
    validator_contract_sha256 = ""
    validator_sidecar_sha256 = ""
    validator_snapshot_sha256 = ""
    contract_resolution_mode = "unresolved"

    if contract is None:
        contract_blocker = {
            "name": "validation_contract",
            "rule_id": "contract.exact_generation_validator_sidecar",
            "rule_type": "VALIDATION_CONTRACT_IDENTITY",
            "source_type": "GENERATION_PROVENANCE",
            "source_ref": "",
            "evaluation_mode": "DETERMINISTIC",
            "severity": "BLOCKER",
            "status": "FAIL",
            "passed": False,
            "required": True,
            "code": "VALIDATION_CONTRACT_UNRESOLVED",
            "message": (
                "The exact validator contract for this generation cannot be proven. "
                + contract_error
            ).strip(),
            "instruction": "Resolve the exact generation validator contract.",
            "details": {},
        }
    else:
        validator_contract_sha256 = str(
            contract.get("validator_contract_sha256") or ""
        ).lower()
        validator_sidecar_sha256 = str(
            contract.get("validator_sidecar_sha256") or ""
        ).lower()
        validator_snapshot_sha256 = str(
            contract.get("validator_snapshot_sha256") or ""
        ).lower()
        contract_resolution_mode = str(
            contract.get("resolution_mode") or "unresolved"
        )
        sidecar = contract.get("validator_sidecar")
        sidecar = sidecar if isinstance(sidecar, dict) else {}
        resolutions = _resolved_rule_map(
            project_id,
            generation,
            content_version_id=current_version_id,
            content_sha256=current_content_sha256,
            validator_contract_sha256=validator_contract_sha256,
        )
        try:
            semantic_verdicts = (
                candidate_semantic_validation_store_service.exact_verdict_map(
                    project_id,
                    generation,
                    content_sha256=current_content_sha256,
                    validator_contract_sha256=validator_contract_sha256,
                )
            )
        except candidate_semantic_validation_store_service.CandidateSemanticValidationStoreError as exc:
            raise CandidateValidationError(
                "SEMANTIC_VALIDATION_RECEIPT_INVALID",
                str(exc),
            ) from exc
        content_rules = _content_rule_results(
            sidecar,
            current_content=current_content,
            resolutions=resolutions,
            semantic_verdicts=semantic_verdicts,
        )

    diagnostic_checks = [
        candidate_validation_evidence_service.very_short_sentence_diagnostic(
            current_content
        )
    ]

    all_checks = list(integrity_checks)
    if contract_blocker is not None:
        all_checks.append(contract_blocker)
    all_checks.extend(content_rules)

    deterministic_failures = [
        item
        for item in content_rules
        if item.get("severity") == "BLOCKER"
        and item.get("evaluation_mode") == "DETERMINISTIC"
        and item.get("status") != "PASS"
    ]
    unresolved_narrative = [
        item
        for item in content_rules
        if item.get("severity") == "BLOCKER"
        and item.get("evaluation_mode") in {"MANUAL", "SEMANTIC"}
        and item.get("status") != "PASS"
    ]
    semantic_failures = [
        item
        for item in unresolved_narrative
        if item.get("status") == "FAIL"
        and bool((item.get("details") or {}).get("semantic_verdict_produced"))
    ]
    unsupported_blockers = [
        item
        for item in content_rules
        if item.get("severity") == "BLOCKER"
        and item.get("evaluation_mode") not in {"DETERMINISTIC", "MANUAL", "SEMANTIC"}
        and item.get("status") != "PASS"
    ]
    content_blocking = []
    if contract_blocker is not None:
        content_blocking.append(contract_blocker)
    content_blocking.extend(deterministic_failures)
    content_blocking.extend(unresolved_narrative)
    content_blocking.extend(unsupported_blockers)

    acceptable = bool(reviewable and not content_blocking)
    if integrity_blocking:
        validation_state = VALIDATION_STATE_INTEGRITY_BLOCKED
    elif (
        deterministic_failures
        or semantic_failures
        or contract_blocker is not None
        or unsupported_blockers
    ):
        validation_state = VALIDATION_STATE_CONTENT_FAILED
    elif unresolved_narrative:
        validation_state = VALIDATION_STATE_SEMANTIC_UNRESOLVED
    else:
        validation_state = VALIDATION_STATE_ACCEPTANCE_READY

    validator_context = {
        "schema_version": VALIDATION_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "generation_id": generation,
        "segment_id": segment_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "model_candidate_content_sha256": output_sha256,
        "candidate_content_sha256": current_content_sha256,
        "current_content_version_id": current_version_id,
        "lineage_tip_version_id": str(current["lineage_tip_version_id"]),
        "current_content_actor": str(current["content_actor"]),
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
        "validator_sidecar_sha256": validator_sidecar_sha256,
        "validator_contract_sha256": validator_contract_sha256,
        "validator_snapshot_sha256": validator_snapshot_sha256,
        "validator_contract_resolution_mode": contract_resolution_mode,
    }
    validator_context["context_sha256"] = _canonical_sha256(validator_context)

    run_identity = {
        "evaluator_version": VALIDATION_EVALUATOR_VERSION,
        "generation_id": generation,
        "content_version_id": current_version_id,
        "content_sha256": current_content_sha256,
        "validator_contract_sha256": validator_contract_sha256,
        "integrity": [
            {
                "rule_id": item["rule_id"],
                "status": item["status"],
                "code": item["code"],
            }
            for item in integrity_checks
        ],
        "content_rules": [
            {
                "rule_id": item["rule_id"],
                "status": item["status"],
                "code": item["code"],
                "resolution_id": str(
                    (item.get("resolution") or {}).get("resolution_id") or ""
                ),
            }
            for item in content_rules
        ],
        "contract_blocker": (
            str(contract_blocker.get("code") or "")
            if contract_blocker is not None
            else ""
        ),
    }
    validation_result_sha256 = _canonical_sha256(run_identity)
    validation_run_id = "validation_run_" + validation_result_sha256[:32]

    blockers = [
        {
            "code": str(item.get("code") or "VALIDATION_BLOCKER"),
            "check": str(item.get("name") or item.get("rule_id") or ""),
            "rule_id": str(item.get("rule_id") or ""),
            "message": str(item.get("message") or ""),
            "evaluation_mode": str(item.get("evaluation_mode") or ""),
        }
        for item in (integrity_blocking + content_blocking)
    ]

    review_actions: list[str] = []
    if reviewable:
        review_actions.extend(["edit", "reject"])
        if acceptable:
            review_actions.insert(0, "accept")

    report = {
        "status": "ok",
        "service": VALIDATION_SERVICE_MARKER,
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "evaluator_version": VALIDATION_EVALUATOR_VERSION,
        "project_id": project_id,
        "generation_id": generation,
        "review_state": (
            CANDIDATE_READY_STATE if reviewable else CANDIDATE_BLOCKED_STATE
        ),
        "validation_state": validation_state,
        "ready_for_author_review": reviewable,
        "reviewable": reviewable,
        "acceptable_for_author_acceptance": acceptable,
        "checks": all_checks,
        "diagnostic_checks": diagnostic_checks,
        "integrity_checks": integrity_checks,
        "content_rules": content_rules,
        "manual_resolution_required": [
            deepcopy(item)
            for item in unresolved_narrative
        ],
        "blockers": blockers,
        "validator_context": validator_context,
        "validation_run_id": validation_run_id,
        "validation_result_sha256": validation_result_sha256,
        "candidate": {
            "segment_id": segment_id,
            "model_origin_id": model_origin_id,
            "model_origin_version_id": model_origin_version_id,
            "current_content_version_id": current_version_id,
            "lineage_tip_version_id": str(current["lineage_tip_version_id"]),
            "content_actor": str(current["content_actor"]),
            "terminal_operation": str(current["terminal_operation"]),
            "content_type": "text/plain",
            "text": current_content,
            "sha256": current_content_sha256,
            "model_output_sha256": output_sha256,
        },
        "review_actions": review_actions,
        "authority": {
            "provider_output_is_candidate_only": True,
            "backend_validation_authoritative_for_review_gate": True,
            "author_resolution_required_for_manual_narrative_rules": True,
            "semantic_model_available": True,
            "semantic_model_required": False,
            "semantic_model_is_author_triggered_billable_call": True,
            "writes_author_review": False,
            "writes_approved_continuity": False,
            "mutates_canon": False,
            "mutates_runtime_story_state": False,
            "calls_provider": False,
            "global_canon_compliance_claimed": False,
            "bounded_generation_contract_only": True,
            "related_passages_are_semantic_verdicts": False,
        },
        "evidence": {
            "service": candidate_validation_evidence_service.EVIDENCE_SERVICE_MARKER,
            "exact_offsets_bound_to_candidate_sha256": current_content_sha256,
            "deterministic_evidence_authoritative": True,
            "narrative_related_passages_are_review_aids_only": True,
        },
    }
    report["validation_report_sha256"] = _canonical_sha256(report)
    return report
