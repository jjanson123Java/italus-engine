"""Primary 45 explicit provider-backed semantic validation execution."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Callable

from app.services import (
    candidate_semantic_validation_store_service,
    provider_credential_service,
    provider_direct_generation_service,
    provider_execution_service,
    provider_preflight_service,
    provider_usage_service,
    validation_service,
)

SEMANTIC_EXECUTION_MARKER = "primary45-semantic-validation-execution-v1"
SEMANTIC_EXECUTION_SCHEMA_VERSION = "candidate_semantic_validation_execution_v1"
MAX_OUTPUT_TOKENS = 3500
_ELIGIBLE_MODES = {"MANUAL", "SEMANTIC"}
_VERDICTS = {"PASS", "FAIL", "UNKNOWN"}


class CandidateSemanticValidationExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = str(code)
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": deepcopy(self.details)}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _eligible_rules(validation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": str(item.get("rule_id") or ""),
            "rule_type": str(item.get("rule_type") or ""),
            "evaluation_mode": str(item.get("evaluation_mode") or ""),
            "instruction": str(item.get("instruction") or item.get("message") or ""),
            "parameters": deepcopy(item.get("parameters") or {}),
        }
        for item in list(validation.get("content_rules") or [])
        if isinstance(item, dict)
        and str(item.get("evaluation_mode") or "").upper() in _ELIGIBLE_MODES
        and str(item.get("status") or "").upper() == "UNKNOWN"
        and str(item.get("rule_id") or "").strip()
    ]


def build_semantic_provider_input(validation: dict[str, Any]) -> dict[str, Any]:
    context = validation.get("validator_context")
    context = context if isinstance(context, dict) else {}
    candidate = validation.get("candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    rules = _eligible_rules(validation)
    if not rules:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_RULES_NOT_REQUIRED",
            "This exact saved candidate has no unresolved narrative rules eligible for semantic validation.",
        )
    content = str(candidate.get("text") or "")
    if not content:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_CANDIDATE_EMPTY",
            "The exact saved candidate text is empty.",
        )
    system = (
        "You are an audited semantic validator for the Italus application. Evaluate only "
        "the supplied candidate text against each supplied rule. Do not invent Canon or "
        "requirements. Related passages or plausible interpretation are not proof. Return "
        "strict JSON only with schema_version='italus_semantic_verdict_v1' and verdicts. "
        "Each requested rule_id must appear exactly once. verdict must be PASS, FAIL, or "
        "UNKNOWN. Use FAIL only when the supplied candidate text itself provides sufficient "
        "evidence of violation; every FAIL must include at least one verbatim evidence excerpt "
        "copied from the candidate. Use PASS only when the whole supplied text is sufficient "
        "to establish compliance. Use UNKNOWN whenever the rule cannot be decided reliably "
        "from the supplied text and rule contract. Do not treat absence of unrelated evidence "
        "as proof. Do not output markdown or commentary outside JSON."
    )
    prompt = {
        "schema_version": "italus_semantic_validation_request_v1",
        "generation_id": str(validation.get("generation_id") or ""),
        "content_version_id": str(context.get("current_content_version_id") or ""),
        "content_sha256": str(context.get("candidate_content_sha256") or ""),
        "validator_contract_sha256": str(context.get("validator_contract_sha256") or ""),
        "rules": rules,
        "candidate_text": content,
        "response_contract": {
            "schema_version": "italus_semantic_verdict_v1",
            "verdicts": [
                {
                    "rule_id": "<exact requested rule_id>",
                    "verdict": "PASS|FAIL|UNKNOWN",
                    "rationale": "<brief explanation>",
                    "evidence_excerpts": ["<verbatim candidate excerpt; required for FAIL>"],
                }
            ],
        },
    }
    user = _canonical_json(prompt)
    return {
        "system_text": system,
        "user_text": user,
        "system_sha256": _sha256_text(system),
        "user_sha256": _sha256_text(user),
        "rules": rules,
    }


def _extract_json(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_PROVIDER_OUTPUT_INVALID",
            "Semantic validator provider output was not valid JSON.",
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "italus_semantic_verdict_v1":
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_PROVIDER_OUTPUT_INVALID",
            "Semantic validator output schema is invalid.",
        )
    return payload


def validate_provider_verdicts(
    provider_output_text: str,
    *,
    requested_rules: list[dict[str, Any]],
    candidate_text: str,
) -> list[dict[str, Any]]:
    payload = _extract_json(provider_output_text)
    items = payload.get("verdicts")
    if not isinstance(items, list):
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_PROVIDER_OUTPUT_INVALID",
            "Semantic validator output verdicts must be a list.",
        )
    expected = [str(item.get("rule_id") or "") for item in requested_rules]
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            raise CandidateSemanticValidationExecutionError(
                "SEMANTIC_PROVIDER_OUTPUT_INVALID",
                "Semantic validator verdict entries must be objects.",
            )
        rule_id = str(raw.get("rule_id") or "").strip()
        if rule_id not in expected or rule_id in seen:
            raise CandidateSemanticValidationExecutionError(
                "SEMANTIC_PROVIDER_OUTPUT_INVALID",
                "Semantic validator returned missing, duplicate, or unexpected rule identity.",
            )
        seen.add(rule_id)
        verdict = str(raw.get("verdict") or "").strip().upper()
        if verdict not in _VERDICTS:
            raise CandidateSemanticValidationExecutionError(
                "SEMANTIC_PROVIDER_OUTPUT_INVALID",
                f"Semantic validator returned invalid verdict for {rule_id}.",
            )
        rationale = str(raw.get("rationale") or "").strip()
        if not rationale or len(rationale) > 3000:
            raise CandidateSemanticValidationExecutionError(
                "SEMANTIC_PROVIDER_OUTPUT_INVALID",
                f"Semantic validator rationale is invalid for {rule_id}.",
            )
        excerpts_raw = raw.get("evidence_excerpts")
        excerpts_raw = excerpts_raw if isinstance(excerpts_raw, list) else []
        excerpts: list[str] = []
        for value in excerpts_raw[:5]:
            excerpt = str(value or "").strip()
            if not excerpt or len(excerpt) > 800:
                continue
            if excerpt not in candidate_text:
                raise CandidateSemanticValidationExecutionError(
                    "SEMANTIC_EVIDENCE_NOT_EXACT",
                    f"Semantic validator evidence for {rule_id} is not an exact candidate substring.",
                )
            excerpts.append(excerpt)
        if verdict == "FAIL" and not excerpts:
            raise CandidateSemanticValidationExecutionError(
                "SEMANTIC_FAIL_EVIDENCE_REQUIRED",
                f"Semantic validator FAIL for {rule_id} lacks exact candidate evidence.",
            )
        cleaned.append({
            "rule_id": rule_id,
            "verdict": verdict,
            "rationale": rationale,
            "evidence_excerpts": excerpts,
        })
    if set(seen) != set(expected):
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_PROVIDER_OUTPUT_INVALID",
            "Semantic validator did not return exactly one verdict for every requested rule.",
        )
    order = {rule_id: index for index, rule_id in enumerate(expected)}
    cleaned.sort(key=lambda item: order[item["rule_id"]])
    return cleaned


def execute_semantic_validation(
    project_id: str,
    generation_id: str,
    *,
    idempotency_key: str,
    timeout_seconds: float = provider_direct_generation_service.DEFAULT_TIMEOUT_SECONDS,
    direct_executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validation = validation_service.validate_generation_candidate(project_id, generation_id)
    context = validation.get("validator_context") or {}
    if validation.get("reviewable") is not True:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_VALIDATION_NOT_REVIEWABLE",
            "Semantic validation requires an integrity-clean reviewable candidate.",
        )
    content_sha = str(context.get("candidate_content_sha256") or "").lower()
    contract_sha = str(context.get("validator_contract_sha256") or "").lower()
    content_version_id = str(context.get("current_content_version_id") or "")
    if not content_sha or not contract_sha or not content_version_id:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_VALIDATION_IDENTITY_MISSING",
            "Candidate semantic-validation identity is incomplete.",
        )

    provider_input = build_semantic_provider_input(validation)
    sem_id = candidate_semantic_validation_store_service.semantic_validation_id_for(
        project_id,
        generation_id,
        content_sha256=content_sha,
        validator_contract_sha256=contract_sha,
        idempotency_key=idempotency_key,
    )

    existing_receipt = candidate_semantic_validation_store_service.get_receipt(
        project_id, sem_id
    )
    if existing_receipt is not None:
        return {
            "status": "ok",
            "service": SEMANTIC_EXECUTION_MARKER,
            "schema_version": SEMANTIC_EXECUTION_SCHEMA_VERSION,
            "idempotent_replay": True,
            "semantic_validation_id": sem_id,
            "generation_id": generation_id,
            "verdicts": deepcopy(existing_receipt.get("verdicts") or []),
            "usage": deepcopy(existing_receipt.get("usage_event") or {}),
        }

    try:
        lineage = provider_execution_service._current_lineage(project_id)
        preflight = provider_preflight_service.run_project_provider_preflight(
            project_id,
            timeout_seconds=timeout_seconds,
        )
        provider_execution_service._validate_preflight(preflight, lineage)
    except provider_execution_service.ProviderExecutionError as exc:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_PROVIDER_SETUP_NOT_READY",
            str(exc),
            details=dict(exc.details or {}),
        ) from exc

    try:
        api_key = provider_credential_service.resolve_api_key(lineage["provider_id"])
    except Exception as exc:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_CREDENTIAL_RESOLUTION_FAILED",
            "The backend credential could not be resolved for semantic validation.",
        ) from exc
    if not api_key:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_CREDENTIAL_RESOLUTION_FAILED",
            "The backend credential could not be resolved for semantic validation.",
        )

    identity = {
        "schema_version": SEMANTIC_EXECUTION_SCHEMA_VERSION,
        "semantic_validation_id": sem_id,
        "project_id": project_id,
        "generation_id": generation_id,
        "content_version_id": content_version_id,
        "content_sha256": content_sha,
        "validator_contract_sha256": contract_sha,
        "provider_id": lineage["provider_id"],
        "model_id": lineage["model_id"],
        "binding_instance_id": lineage["binding_instance_id"],
        "credential_instance_id": lineage["credential_instance_id"],
        "pricing_version_id": lineage["pricing_version_id"],
        "pricing_version_sha256": lineage["pricing_version_sha256"],
        "provider_system_sha256": provider_input["system_sha256"],
        "provider_user_prompt_sha256": provider_input["user_sha256"],
    }

    try:
        started = candidate_semantic_validation_store_service.begin_intent(
            project_id, sem_id, identity
        )
    except candidate_semantic_validation_store_service.CandidateSemanticValidationStoreError as exc:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_VALIDATION_STATE_INVALID",
            str(exc),
        ) from exc
    if started.get("status") == "completed":
        receipt = started["receipt"]
        return {
            "status": "ok",
            "service": SEMANTIC_EXECUTION_MARKER,
            "schema_version": SEMANTIC_EXECUTION_SCHEMA_VERSION,
            "idempotent_replay": True,
            "semantic_validation_id": sem_id,
            "generation_id": generation_id,
            "verdicts": deepcopy(receipt.get("verdicts") or []),
            "usage": deepcopy(receipt.get("usage_event") or {}),
        }
    if started.get("status") != "started":
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_VALIDATION_IN_PROGRESS",
            "This semantic validation idempotency key already has an execution in progress.",
        )

    executor = direct_executor or provider_direct_generation_service.execute_direct_generation
    try:
        provider_result = executor(
            provider_id=lineage["provider_id"],
            model_id=lineage["model_id"],
            system_text=provider_input["system_text"],
            prompt_text=provider_input["user_text"],
            max_output_tokens=MAX_OUTPUT_TOKENS,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    except provider_direct_generation_service.ProviderDirectGenerationError as exc:
        candidate_semantic_validation_store_service.release_intent(
            project_id, sem_id
        )
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_PROVIDER_EXECUTION_FAILED",
            str(exc),
        ) from exc

    returned_model = str(provider_result.get("returned_model_id") or "").strip()
    if returned_model and returned_model != lineage["model_id"]:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_MODEL_IDENTITY_MISMATCH",
            "Semantic validator returned a different model identity than the project binding.",
        )

    candidate_text = str((validation.get("candidate") or {}).get("text") or "")
    verdicts = validate_provider_verdicts(
        str(provider_result.get("output_text") or ""),
        requested_rules=provider_input["rules"],
        candidate_text=candidate_text,
    )
    usage = provider_result.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    usage_event = {
        "usage_event_id": f"usage_{sem_id}",
        "generation_id": generation_id,
        "operation_kind": "semantic_validation",
        "semantic_validation_id": sem_id,
        "provider_id": lineage["provider_id"],
        "model_id": lineage["model_id"],
        "pricing_version_id": lineage["pricing_version_id"],
        "credential_instance_id": lineage["credential_instance_id"],
        "binding_instance_id": lineage["binding_instance_id"],
        "actual_input_tokens": usage.get("actual_input_tokens"),
        "actual_output_tokens": usage.get("actual_output_tokens"),
        "cache_write_5m_tokens": usage.get("cache_write_5m_tokens", 0),
        "cache_write_1h_tokens": usage.get("cache_write_1h_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_tokens", 0),
        "provider_request_id": str(provider_result.get("provider_request_id") or "").strip() or None,
        "provider_status": str(provider_result.get("provider_status") or "").strip(),
        "provider_stop_reason": str(provider_result.get("stop_reason") or "").strip() or None,
        "provider_system_sha256": provider_input["system_sha256"],
        "provider_user_prompt_sha256": provider_input["user_sha256"],
    }
    try:
        usage_result = provider_usage_service.append_usage_event(project_id, usage_event)
    except provider_usage_service.ProviderUsageError as exc:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_USAGE_LEDGER_COMMIT_FAILED",
            str(exc),
            details={"semantic_validation_id": sem_id, "reconciliation_required": True},
        ) from exc

    committed_usage = usage_result.get("event")
    committed_usage = committed_usage if isinstance(committed_usage, dict) else usage_event
    try:
        receipt = candidate_semantic_validation_store_service.complete(
            project_id,
            sem_id,
            {
            **identity,
            "provider_request_id": provider_result.get("provider_request_id"),
            "provider_status": provider_result.get("provider_status"),
            "provider_stop_reason": provider_result.get("stop_reason"),
            "provider_output_sha256": _sha256_text(str(provider_result.get("output_text") or "")),
            "verdicts": verdicts,
            "usage_event": committed_usage,
            "authority": {
                "semantic_provider_verdicts_are_bounded_to_exact_content": True,
                "related_passages_are_semantic_verdicts": False,
                "unknown_requires_author_resolution_or_edit": True,
                "writes_canon": False,
                "writes_approved_continuity": False,
            },
            },
        )
    except candidate_semantic_validation_store_service.CandidateSemanticValidationStoreError as exc:
        raise CandidateSemanticValidationExecutionError(
            "SEMANTIC_RECEIPT_COMMIT_FAILED",
            str(exc),
            details={"semantic_validation_id": sem_id, "reconciliation_required": True},
        ) from exc
    return {
        "status": "ok",
        "service": SEMANTIC_EXECUTION_MARKER,
        "schema_version": SEMANTIC_EXECUTION_SCHEMA_VERSION,
        "idempotent_replay": False,
        "semantic_validation_id": sem_id,
        "generation_id": generation_id,
        "verdicts": deepcopy(receipt.get("verdicts") or []),
        "usage": deepcopy(receipt.get("usage_event") or {}),
    }
