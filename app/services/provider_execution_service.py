from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from app.services import (
    authorship_provenance_service,
    generation_service,
    provider_binding_service,
    provider_config_service,
    provider_credential_service,
    provider_direct_generation_service,
    provider_generation_receipt_service,
    provider_preflight_service,
    provider_pricing_service,
    provider_usage_service,
)


PROVIDER_EXECUTION_SERVICE_MARKER = "PRIMARY_33_2_2_PROVIDER_EXECUTION_SERVICE"
PROVIDER_EXECUTION_SCHEMA_VERSION = "primary33.2.2-provider-execution-v1"
PROVIDER_CANDIDATE_SCHEMA_VERSION = "primary33-provider-candidate-v1"
PROVIDER_CANDIDATE_STATE = "generated_pending_author_review"

# Primary 33.2.2B exposes this already-validated execution/receipt engine only
# through the controlled provider generation route. Every execution still runs
# the live provider preflight immediately before the paid provider call.
PROVIDER_EXECUTION_ACTIVATION_READY = True


class ProviderExecutionError(RuntimeError):
    """Raised when provider execution cannot proceed without violating lineage."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        reconciliation_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.details = dict(details or {})
        self.reconciliation_required = bool(reconciliation_required)

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "reconciliation_required": self.reconciliation_required,
            "details": dict(self.details),
        }


def _required_text(payload: dict[str, Any], key: str, code: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ProviderExecutionError(code, f"{key} is required for provider execution.")
    return value


def _current_lineage(project_id: str) -> dict[str, Any]:
    binding_payload = provider_binding_service.get_project_provider_binding(project_id)
    raw_binding = binding_payload.get("binding")
    if not isinstance(raw_binding, dict):
        raise ProviderExecutionError(
            "PROJECT_PROVIDER_NOT_BOUND",
            "Bind a direct provider to this project before provider execution.",
        )

    provider_id = _required_text(raw_binding, "provider_id", "PROVIDER_ID_MISSING").lower()
    model_id = _required_text(raw_binding, "model_id", "MODEL_ID_MISSING")
    binding_instance_id = _required_text(
        raw_binding,
        "binding_instance_id",
        "BINDING_LINEAGE_MISSING",
    )
    service_tier = str(raw_binding.get("service_tier") or "standard").strip().lower()
    inference_scope = str(raw_binding.get("inference_scope") or "global").strip().lower()

    if provider_id not in provider_config_service.DIRECT_PROVIDER_IDS:
        raise ProviderExecutionError(
            "DIRECT_PROVIDER_REQUIRED",
            "Real provider execution is limited to enabled direct providers.",
        )
    try:
        provider_config_service.require_accepted_model_id(provider_id, model_id)
    except provider_config_service.ProviderConfigError as exc:
        raise ProviderExecutionError(
            "MODEL_NOT_ACCEPTED",
            "The exact project model ID is not accepted by the direct-provider catalog.",
        ) from exc

    credential = provider_credential_service.credential_state(provider_id)
    if credential.get("status") != "configured":
        raise ProviderExecutionError(
            "CREDENTIAL_NOT_CONFIGURED",
            "The trusted provider credential is not configured.",
        )
    credential_instance_id = str(
        credential.get("credential_instance_id") or ""
    ).strip()
    if not credential_instance_id:
        raise ProviderExecutionError(
            "CREDENTIAL_LINEAGE_MISSING",
            (
                "Real provider execution requires a tracked credential_instance_id "
                "so the provider usage receipt cannot be detached from the credential used."
            ),
        )

    try:
        pricing_payload = provider_pricing_service.get_current_pricing(
            provider_id=provider_id,
            model_id=model_id,
            service_tier=service_tier,
            inference_scope=inference_scope,
        )
    except provider_pricing_service.ProviderPricingError as exc:
        raise ProviderExecutionError(
            "EFFECTIVE_PRICING_MISSING",
            "Effective immutable pricing is unavailable for the exact project binding.",
        ) from exc

    pricing = pricing_payload.get("pricing")
    if not isinstance(pricing, dict):
        raise ProviderExecutionError(
            "EFFECTIVE_PRICING_MISSING",
            "Effective immutable pricing is unavailable for the exact project binding.",
        )
    pricing_version_id = _required_text(
        pricing,
        "pricing_version_id",
        "PRICING_VERSION_MISSING",
    )
    try:
        pricing_snapshot = provider_pricing_service.get_pricing_version_snapshot(
            pricing_version_id
        )
    except provider_pricing_service.ProviderPricingError as exc:
        raise ProviderExecutionError(
            "PRICING_PROVENANCE_INCOMPLETE",
            "The effective pricing version cannot be resolved immutably.",
        ) from exc
    pricing_version_sha256 = str(
        pricing_snapshot.get("pricing_version_sha256") or ""
    ).strip()
    if not pricing_version_sha256:
        raise ProviderExecutionError(
            "PRICING_PROVENANCE_INCOMPLETE",
            "The effective pricing version has no semantic SHA-256 provenance.",
        )

    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "service_tier": service_tier,
        "inference_scope": inference_scope,
        "binding_instance_id": binding_instance_id,
        "credential_instance_id": credential_instance_id,
        "pricing_version_id": pricing_version_id,
        "pricing_version_sha256": pricing_version_sha256,
    }


def _same_lineage(left: dict[str, Any], right: dict[str, Any]) -> bool:
    keys = (
        "provider_id",
        "model_id",
        "service_tier",
        "inference_scope",
        "binding_instance_id",
        "credential_instance_id",
        "pricing_version_id",
        "pricing_version_sha256",
    )
    return all(str(left.get(key) or "") == str(right.get(key) or "") for key in keys)


def _validate_preflight(
    preflight: dict[str, Any],
    lineage: dict[str, Any],
) -> None:
    if preflight.get("ready") is not True or str(preflight.get("result") or "") != "PASS":
        raise ProviderExecutionError(
            "PROVIDER_SETUP_NOT_READY",
            "Provider setup validation did not pass; provider generation was not attempted.",
            details={
                "blockers": list(preflight.get("blockers") or []),
                "warnings": list(preflight.get("warnings") or []),
            },
        )

    binding = preflight.get("binding")
    credential = preflight.get("credential")
    pricing = preflight.get("pricing")
    binding = binding if isinstance(binding, dict) else {}
    credential = credential if isinstance(credential, dict) else {}
    pricing = pricing if isinstance(pricing, dict) else {}

    comparisons = {
        "provider_id": binding.get("provider_id"),
        "model_id": binding.get("model_id"),
        "service_tier": binding.get("service_tier"),
        "inference_scope": binding.get("inference_scope"),
        "binding_instance_id": binding.get("binding_instance_id"),
        "credential_instance_id": credential.get("credential_instance_id"),
        "pricing_version_id": pricing.get("pricing_version_id"),
        "pricing_version_sha256": pricing.get("pricing_version_sha256"),
    }
    if not _same_lineage(lineage, comparisons):
        raise ProviderExecutionError(
            "PREFLIGHT_LINEAGE_DRIFT",
            (
                "Provider setup validation passed against different binding, credential, "
                "or pricing lineage than the pending generation."
            ),
        )


def _candidate_segment_id(generation_id: str) -> str:
    return f"segment_{generation_id}"


def _ensure_model_origin(
    project_id: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Ensure a completed provider receipt has exactly one immutable MODEL origin."""

    generation_id = _required_text(
        receipt,
        "generation_id",
        "MODEL_ORIGIN_GENERATION_ID_MISSING",
    )
    provider_id = _required_text(
        receipt,
        "provider_id",
        "MODEL_ORIGIN_PROVIDER_MISSING",
    )
    model_id = _required_text(
        receipt,
        "model_id",
        "MODEL_ORIGIN_MODEL_MISSING",
    )
    output_sha256 = _required_text(
        receipt,
        "output_text_sha256",
        "MODEL_ORIGIN_OUTPUT_HASH_MISSING",
    )
    output_text = str(receipt.get("output_text") or "")
    actual_output_sha256 = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
    if actual_output_sha256 != output_sha256:
        raise ProviderExecutionError(
            "MODEL_ORIGIN_OUTPUT_HASH_MISMATCH",
            "The completed provider receipt output does not match its immutable output hash.",
            reconciliation_required=True,
        )

    try:
        book_number = int(receipt.get("book_number") or 0)
        chapter_number = int(receipt.get("chapter_number") or 0)
    except (TypeError, ValueError) as exc:
        raise ProviderExecutionError(
            "MODEL_ORIGIN_POSITION_MISSING",
            "The completed provider receipt does not contain a valid book/chapter position.",
            reconciliation_required=True,
        ) from exc
    if book_number < 1 or chapter_number < 1:
        raise ProviderExecutionError(
            "MODEL_ORIGIN_POSITION_MISSING",
            "The completed provider receipt does not contain a valid book/chapter position.",
            reconciliation_required=True,
        )

    usage_event = receipt.get("usage_event")
    usage_event = usage_event if isinstance(usage_event, dict) else {}
    segment_id = _candidate_segment_id(generation_id)
    metadata = {
        "candidate_schema_version": PROVIDER_CANDIDATE_SCHEMA_VERSION,
        "candidate_state": PROVIDER_CANDIDATE_STATE,
        "request_content_sha256": receipt.get("request_content_sha256"),
        "prompt_sha256": receipt.get("prompt_sha256"),
        "provider_request_id": receipt.get("provider_request_id"),
        "provider_status": receipt.get("provider_status"),
        "stop_reason": receipt.get("stop_reason"),
        "provider_receipt_sha256": receipt.get("receipt_sha256"),
        "output_text_sha256": output_sha256,
        "usage_event_id": usage_event.get("usage_event_id"),
        "binding_instance_id": receipt.get("binding_instance_id"),
        "credential_instance_id": receipt.get("credential_instance_id"),
        "pricing_version_id": receipt.get("pricing_version_id"),
        "pricing_version_sha256": receipt.get("pricing_version_sha256"),
        "author_review_persisted": False,
        "approved_continuity_committed": False,
    }

    try:
        result = authorship_provenance_service.register_origin_snapshot(
            project_id,
            generation_id=generation_id,
            segment_id=segment_id,
            origin_actor=authorship_provenance_service.ACTOR_MODEL,
            content=output_text,
            provider=provider_id,
            provider_model=model_id,
            parent_ids=[],
            book_number=book_number,
            chapter_number=chapter_number,
            metadata=metadata,
        )
    except authorship_provenance_service.AuthorshipProvenanceError as exc:
        raise ProviderExecutionError(
            "MODEL_ORIGIN_RECONCILIATION_REQUIRED",
            (
                "The provider receipt is complete, but immutable MODEL-origin "
                "registration could not be completed. Reuse the same idempotency "
                "key after the provenance state is repaired; do not resend the "
                "provider request."
            ),
            details={"generation_id": generation_id},
            reconciliation_required=True,
        ) from exc

    origin = result.get("origin")
    if not isinstance(origin, dict):
        raise ProviderExecutionError(
            "MODEL_ORIGIN_RECONCILIATION_REQUIRED",
            "Immutable MODEL-origin registration returned no authoritative origin record.",
            details={"generation_id": generation_id},
            reconciliation_required=True,
        )

    origin_metadata = origin.get("metadata")
    metadata_matches = bool(
        isinstance(origin_metadata, dict)
        and origin_metadata == metadata
    )
    immutable_matches = bool(
        str(origin.get("generation_id") or "") == generation_id
        and str(origin.get("segment_id") or "") == segment_id
        and str(origin.get("origin_actor") or "")
        == authorship_provenance_service.ACTOR_MODEL
        and str(origin.get("provider") or "") == provider_id
        and str(origin.get("provider_model") or "") == model_id
        and str(origin.get("content_hash") or "") == output_sha256
        and list(origin.get("parent_ids") or []) == []
        and int(origin.get("book_number") or 0) == book_number
        and int(origin.get("chapter_number") or 0) == chapter_number
        and origin.get("immutable") is True
        and metadata_matches
    )
    if not immutable_matches:
        raise ProviderExecutionError(
            "MODEL_ORIGIN_LINEAGE_MISMATCH",
            "Immutable MODEL-origin lineage does not match the completed provider receipt.",
            details={"generation_id": generation_id},
            reconciliation_required=True,
        )
    return origin


def _receipt_response(
    receipt: dict[str, Any],
    *,
    model_origin: dict[str, Any],
    idempotent_replay: bool,
) -> dict[str, Any]:
    usage_event = receipt.get("usage_event")
    usage_event = usage_event if isinstance(usage_event, dict) else {}
    return {
        "status": "ok",
        "service": PROVIDER_EXECUTION_SERVICE_MARKER,
        "schema_version": PROVIDER_EXECUTION_SCHEMA_VERSION,
        "generation_id": receipt.get("generation_id"),
        "idempotent_replay": bool(idempotent_replay),
        "candidate": {
            "schema_version": PROVIDER_CANDIDATE_SCHEMA_VERSION,
            "state": PROVIDER_CANDIDATE_STATE,
            "segment_id": model_origin.get("segment_id"),
            "origin_id": model_origin.get("origin_id"),
            "version_id": model_origin.get("version_id"),
            "origin_actor": model_origin.get("origin_actor"),
            "immutable_origin_recorded": True,
            "author_review_persisted": False,
            "approved_continuity_committed": False,
        },
        "draft": {
            "content_type": "text/plain",
            "text": str(receipt.get("output_text") or ""),
            "sha256": receipt.get("output_text_sha256"),
        },
        "provider": {
            "provider_id": receipt.get("provider_id"),
            "model_id": receipt.get("model_id"),
            "provider_request_id": receipt.get("provider_request_id"),
            "provider_status": receipt.get("provider_status"),
            "stop_reason": receipt.get("stop_reason"),
        },
        "lineage": {
            "binding_instance_id": receipt.get("binding_instance_id"),
            "credential_instance_id": receipt.get("credential_instance_id"),
            "pricing_version_id": receipt.get("pricing_version_id"),
            "pricing_version_sha256": receipt.get("pricing_version_sha256"),
            "request_content_sha256": receipt.get("request_content_sha256"),
            "prompt_sha256": receipt.get("prompt_sha256"),
            "receipt_sha256": receipt.get("receipt_sha256"),
            "model_origin_id": model_origin.get("origin_id"),
            "model_origin_version_id": model_origin.get("version_id"),
            "model_origin_content_sha256": model_origin.get("content_hash"),
        },
        "usage": {
            "actual_input_tokens": usage_event.get("actual_input_tokens"),
            "actual_output_tokens": usage_event.get("actual_output_tokens"),
            "cache_write_5m_tokens": usage_event.get("cache_write_5m_tokens"),
            "cache_write_1h_tokens": usage_event.get("cache_write_1h_tokens"),
            "cache_read_tokens": usage_event.get("cache_read_tokens"),
            "currency": usage_event.get("currency"),
            "actual_cost": usage_event.get("actual_cost"),
            "usage_event_id": usage_event.get("usage_event_id"),
        },
        "persistence": {
            "provider_receipt_recorded": True,
            "usage_recorded": True,
            "model_origin_recorded": True,
            "author_review_persisted": False,
            "approved_continuity_committed": False,
        },
    }


def execute_provider_generation(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    idempotency_key: str,
    timeout_seconds: float = provider_direct_generation_service.DEFAULT_TIMEOUT_SECONDS,
    direct_executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one provider-backed Primary 32 request with immutable lineage.

    Primary 33.2.2B activates this engine only for the controlled provider
    generation route. The execution path remains fail-closed behind live
    provider preflight, immutable lineage, idempotency, receipt, and usage gates.
    """
    if PROVIDER_EXECUTION_ACTIVATION_READY is not True:
        raise ProviderExecutionError(
            "PROVIDER_EXECUTION_ACTIVATION_LOCKED",
            (
                "Primary 33.2.2 provider execution code is installed but production "
                "activation remains locked pending regression and live-provider acceptance."
            ),
        )

    try:
        envelope = generation_service.build_generation_request_envelope(
            project_id,
            book_number=int(book_number),
            chapter_number=int(chapter_number),
        )
    except generation_service.GenerationRequestBuildError as exc:
        raise ProviderExecutionError(
            exc.code,
            str(exc),
            details=dict(exc.details or {}),
        ) from exc

    request_content_sha256 = _required_text(
        envelope,
        "request_content_sha256",
        "REQUEST_IDENTITY_MISSING",
    )
    prompt = envelope.get("prompt")
    prompt = prompt if isinstance(prompt, dict) else {}
    prompt_sha256 = _required_text(prompt, "prompt_sha256", "PROMPT_IDENTITY_MISSING")
    prompt_text = json.dumps(
        prompt,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    target_output = envelope.get("target_output")
    target_output = target_output if isinstance(target_output, dict) else {}
    try:
        max_output_tokens = int(target_output.get("requested_output_token_ceiling"))
    except (TypeError, ValueError) as exc:
        raise ProviderExecutionError(
            "OUTPUT_TOKEN_LIMIT_MISSING",
            "The provider-neutral request does not define an output token ceiling.",
        ) from exc
    if max_output_tokens <= 0:
        raise ProviderExecutionError(
            "OUTPUT_TOKEN_LIMIT_MISSING",
            "The provider-neutral request output token ceiling must be positive.",
        )

    generation_id = provider_generation_receipt_service.generation_id_for(
        project_id,
        idempotency_key,
    )

    # A completed receipt is authoritative for idempotent replay. Replaying a
    # completed generation must not require the provider to be online, the
    # credential to remain unchanged, or the same pricing version to still be
    # current. Only the stable provider-neutral request identity must match.
    try:
        existing_receipt = provider_generation_receipt_service.get_receipt(
            project_id,
            generation_id,
        )
    except provider_generation_receipt_service.ProviderGenerationReceiptError as exc:
        raise ProviderExecutionError(
            "EXECUTION_RECONCILIATION_REQUIRED",
            str(exc),
            reconciliation_required=True,
        ) from exc
    if existing_receipt is not None:
        if (
            str(existing_receipt.get("request_content_sha256") or "")
            != request_content_sha256
            or str(existing_receipt.get("prompt_sha256") or "") != prompt_sha256
            or int(existing_receipt.get("book_number") or 0) != int(book_number)
            or int(existing_receipt.get("chapter_number") or 0) != int(chapter_number)
        ):
            raise ProviderExecutionError(
                "IDEMPOTENCY_KEY_CONFLICT",
                (
                    "The idempotency key already belongs to a different provider-neutral "
                    "generation request."
                ),
                reconciliation_required=True,
            )
        usage_event = existing_receipt.get("usage_event")
        if not isinstance(usage_event, dict):
            raise ProviderExecutionError(
                "RECEIPT_USAGE_MISSING",
                "The immutable provider receipt is missing its committed usage event.",
                reconciliation_required=True,
            )
        try:
            provider_usage_service.append_usage_event(project_id, usage_event)
        except provider_usage_service.ProviderUsageError as exc:
            raise ProviderExecutionError(
                "RECEIPT_USAGE_RECONCILIATION_FAILED",
                str(exc),
                reconciliation_required=True,
            ) from exc
        model_origin = _ensure_model_origin(project_id, existing_receipt)
        return _receipt_response(
            existing_receipt,
            model_origin=model_origin,
            idempotent_replay=True,
        )

    lineage = _current_lineage(project_id)

    preflight = provider_preflight_service.run_project_provider_preflight(
        project_id,
        timeout_seconds=min(float(timeout_seconds), 30.0),
    )
    _validate_preflight(preflight, lineage)

    # Detect any local state change between the provider metadata preflight and
    # execution intent creation.
    current = _current_lineage(project_id)
    if not _same_lineage(lineage, current):
        raise ProviderExecutionError(
            "EXECUTION_LINEAGE_DRIFT",
            "Provider binding, credential, or pricing lineage changed after preflight.",
        )

    identity = {
        "project_id": project_id,
        "generation_id": generation_id,
        "request_content_sha256": request_content_sha256,
        "prompt_sha256": prompt_sha256,
        "book_number": int(book_number),
        "chapter_number": int(chapter_number),
        **lineage,
    }
    fingerprint = provider_generation_receipt_service.execution_fingerprint(identity)

    try:
        started = provider_generation_receipt_service.begin_execution(
            project_id,
            generation_id,
            fingerprint=fingerprint,
            identity=identity,
        )
    except provider_generation_receipt_service.ProviderGenerationReceiptError as exc:
        raise ProviderExecutionError(
            "EXECUTION_RECONCILIATION_REQUIRED",
            str(exc),
            reconciliation_required=True,
        ) from exc

    if started.get("status") == "completed":
        receipt = started["receipt"]
        usage_event = receipt.get("usage_event")
        if not isinstance(usage_event, dict):
            raise ProviderExecutionError(
                "RECEIPT_USAGE_MISSING",
                "The immutable provider receipt is missing its committed usage event.",
                reconciliation_required=True,
            )
        try:
            provider_usage_service.append_usage_event(project_id, usage_event)
        except provider_usage_service.ProviderUsageError as exc:
            raise ProviderExecutionError(
                "RECEIPT_USAGE_RECONCILIATION_FAILED",
                str(exc),
                reconciliation_required=True,
            ) from exc
        model_origin = _ensure_model_origin(project_id, receipt)
        return _receipt_response(
            receipt,
            model_origin=model_origin,
            idempotent_replay=True,
        )

    if started.get("status") != "started":
        raise ProviderExecutionError(
            "EXECUTION_RECONCILIATION_REQUIRED",
            (
                "A prior provider execution attempt with this idempotency key has "
                "no complete immutable receipt. Automatic provider replay is blocked."
            ),
            details={"intent": started.get("intent")},
            reconciliation_required=True,
        )

    try:
        api_key = provider_credential_service.resolve_api_key(lineage["provider_id"])
    except provider_credential_service.ProviderCredentialError as exc:
        provider_generation_receipt_service.release_execution_intent(
            project_id,
            generation_id,
            fingerprint=fingerprint,
        )
        raise ProviderExecutionError(
            "CREDENTIAL_RESOLUTION_FAILED",
            "The backend credential could not be resolved for provider execution.",
        ) from exc
    if not api_key:
        provider_generation_receipt_service.release_execution_intent(
            project_id,
            generation_id,
            fingerprint=fingerprint,
        )
        raise ProviderExecutionError(
            "CREDENTIAL_RESOLUTION_FAILED",
            "The backend credential could not be resolved for provider execution.",
        )

    post_resolution = _current_lineage(project_id)
    if not _same_lineage(lineage, post_resolution):
        provider_generation_receipt_service.release_execution_intent(
            project_id,
            generation_id,
            fingerprint=fingerprint,
        )
        raise ProviderExecutionError(
            "EXECUTION_LINEAGE_DRIFT",
            "Provider binding, credential, or pricing lineage changed during credential resolution.",
        )

    executor = direct_executor or provider_direct_generation_service.execute_direct_generation
    try:
        provider_result = executor(
            provider_id=lineage["provider_id"],
            model_id=lineage["model_id"],
            prompt_text=prompt_text,
            max_output_tokens=max_output_tokens,
            api_key=api_key,
            timeout_seconds=float(timeout_seconds),
        )
    except provider_direct_generation_service.ProviderDirectGenerationError as exc:
        if exc.reconciliation_required:
            provider_generation_receipt_service.mark_reconciliation_required(
                project_id,
                generation_id,
                fingerprint=fingerprint,
                code=exc.code,
                message=str(exc),
                provider_request_id=exc.request_id,
            )
        else:
            provider_generation_receipt_service.release_execution_intent(
                project_id,
                generation_id,
                fingerprint=fingerprint,
            )
        raise ProviderExecutionError(
            exc.code,
            str(exc),
            details=exc.to_safe_dict(),
            reconciliation_required=exc.reconciliation_required,
        ) from exc
    finally:
        # Never retain the provider credential in an application result structure.
        api_key = None

    returned_model = str(provider_result.get("returned_model_id") or "").strip()
    if returned_model and returned_model != lineage["model_id"]:
        provider_generation_receipt_service.mark_reconciliation_required(
            project_id,
            generation_id,
            fingerprint=fingerprint,
            code="MODEL_IDENTITY_MISMATCH",
            message=(
                "The provider generation response identified a different model than "
                "the exact project binding. Billing reconciliation is required."
            ),
            provider_request_id=str(
                provider_result.get("provider_request_id") or ""
            ).strip()
            or None,
        )
        raise ProviderExecutionError(
            "MODEL_IDENTITY_MISMATCH",
            "The provider returned a different model identity than the project binding.",
            reconciliation_required=True,
        )

    usage = provider_result.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    usage_event_id = f"usage_{generation_id[4:]}"
    usage_event = {
        "usage_event_id": usage_event_id,
        "generation_id": generation_id,
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
        "provider_request_id": (
            str(provider_result.get("provider_request_id") or "").strip() or None
        ),
        "provider_status": str(provider_result.get("provider_status") or "").strip(),
        "provider_stop_reason": (
            str(provider_result.get("stop_reason") or "").strip() or None
        ),
        "request_content_sha256": request_content_sha256,
        "prompt_sha256": prompt_sha256,
        "provider_execution_schema_version": PROVIDER_EXECUTION_SCHEMA_VERSION,
    }

    try:
        usage_result = provider_usage_service.append_usage_event(
            project_id,
            usage_event,
        )
    except provider_usage_service.ProviderUsageError as exc:
        provider_generation_receipt_service.mark_reconciliation_required(
            project_id,
            generation_id,
            fingerprint=fingerprint,
            code="USAGE_LEDGER_COMMIT_FAILED",
            message=(
                "The provider returned authoritative usage but the immutable usage "
                "ledger could not commit it. Automatic provider replay is blocked."
            ),
            provider_request_id=str(
                provider_result.get("provider_request_id") or ""
            ).strip()
            or None,
        )
        raise ProviderExecutionError(
            "USAGE_LEDGER_COMMIT_FAILED",
            str(exc),
            reconciliation_required=True,
        ) from exc

    committed_event = usage_result.get("event")
    if not isinstance(committed_event, dict):
        raise ProviderExecutionError(
            "USAGE_LEDGER_COMMIT_INVALID",
            "The usage ledger did not return the committed usage event.",
            reconciliation_required=True,
        )
    if (
        str(committed_event.get("binding_instance_id") or "")
        != lineage["binding_instance_id"]
        or str(committed_event.get("credential_instance_id") or "")
        != lineage["credential_instance_id"]
        or str(committed_event.get("pricing_version_id") or "")
        != lineage["pricing_version_id"]
        or str(committed_event.get("pricing_version_sha256") or "")
        != lineage["pricing_version_sha256"]
        or str(committed_event.get("provider_id") or "")
        != lineage["provider_id"]
        or str(committed_event.get("model_id") or "")
        != lineage["model_id"]
    ):
        provider_generation_receipt_service.mark_reconciliation_required(
            project_id,
            generation_id,
            fingerprint=fingerprint,
            code="USAGE_LINEAGE_MISMATCH",
            message="Committed usage lineage does not match the provider execution snapshot.",
            provider_request_id=str(
                provider_result.get("provider_request_id") or ""
            ).strip()
            or None,
        )
        raise ProviderExecutionError(
            "USAGE_LINEAGE_MISMATCH",
            "Committed usage lineage does not match the provider execution snapshot.",
            reconciliation_required=True,
        )

    output_text = str(provider_result.get("output_text") or "")

    receipt_payload = {
        "provider_id": lineage["provider_id"],
        "model_id": lineage["model_id"],
        "service_tier": lineage["service_tier"],
        "inference_scope": lineage["inference_scope"],
        "binding_instance_id": lineage["binding_instance_id"],
        "credential_instance_id": lineage["credential_instance_id"],
        "pricing_version_id": lineage["pricing_version_id"],
        "pricing_version_sha256": lineage["pricing_version_sha256"],
        "request_content_sha256": request_content_sha256,
        "prompt_sha256": prompt_sha256,
        "book_number": int(book_number),
        "chapter_number": int(chapter_number),
        "provider_request_id": (
            str(provider_result.get("provider_request_id") or "").strip() or None
        ),
        "provider_status": str(provider_result.get("provider_status") or "").strip(),
        "stop_reason": (
            str(provider_result.get("stop_reason") or "").strip() or None
        ),
        "provider_received_at": provider_result.get("received_at"),
        "output_content_type": "text/plain",
        "output_text": output_text,
        "output_text_sha256": hashlib.sha256(
            output_text.encode("utf-8")
        ).hexdigest(),
        "usage_event": committed_event,
        "author_review_persisted": False,
        "approved_continuity_committed": False,
    }
    try:
        receipt = provider_generation_receipt_service.write_receipt_once(
            project_id,
            generation_id,
            fingerprint=fingerprint,
            receipt=receipt_payload,
        )
    except provider_generation_receipt_service.ProviderGenerationReceiptError as exc:
        raise ProviderExecutionError(
            "PROVIDER_RECEIPT_COMMIT_FAILED",
            str(exc),
            reconciliation_required=True,
        ) from exc

    model_origin = _ensure_model_origin(project_id, receipt)
    return _receipt_response(
        receipt,
        model_origin=model_origin,
        idempotent_replay=False,
    )
