from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.services import (
    provider_binding_service,
    provider_config_service,
    provider_credential_service,
    provider_pricing_service,
)


PROVIDER_PREFLIGHT_SCHEMA_VERSION = "primary33.2.1b-provider-preflight-v1"
DEFAULT_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 256 * 1024

_PROVIDER_MODEL_ENDPOINTS = {
    "anthropic": "https://api.anthropic.com/v1/models/{model_id}",
    "openai": "https://api.openai.com/v1/models/{model_id}",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check(
    check_id: str,
    *,
    status: str,
    code: str,
    message: str,
    blocking: bool = False,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": status,
        "code": code,
        "message": message,
        "blocking": bool(blocking),
    }


def _safe_request_id(headers: Any) -> str | None:
    if headers is None:
        return None
    for name in ("request-id", "x-request-id", "x-amzn-requestid"):
        value = str(headers.get(name) or "").strip()
        if value:
            return value[:256]
    return None


def _provider_probe_failure(
    *,
    provider_id: str,
    model_id: str,
    code: str,
    message: str,
    http_status: int | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "provider_id": provider_id,
        "requested_model_id": model_id,
        "returned_model_id": None,
        "http_status": http_status,
        "request_id": request_id,
        "code": code,
        "message": message,
    }


def _provider_model_probe(
    provider_id: str,
    model_id: str,
    api_key: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    provider = str(provider_id or "").strip().lower()
    model = str(model_id or "").strip()
    secret = str(api_key or "").strip()

    endpoint_template = _PROVIDER_MODEL_ENDPOINTS.get(provider)
    if endpoint_template is None:
        return _provider_probe_failure(
            provider_id=provider,
            model_id=model,
            code="PROVIDER_UNSUPPORTED",
            message="The bound provider does not have a direct-provider preflight adapter.",
        )
    if not model:
        return _provider_probe_failure(
            provider_id=provider,
            model_id=model,
            code="MODEL_ID_MISSING",
            message="The project binding does not contain an exact model ID.",
        )
    if not secret:
        return _provider_probe_failure(
            provider_id=provider,
            model_id=model,
            code="CREDENTIAL_MISSING",
            message="No provider credential could be resolved by the trusted backend.",
        )

    url = endpoint_template.format(model_id=quote(model, safe=""))
    headers = {
        "Accept": "application/json",
        "User-Agent": "Italus/Primary33.2.1B",
    }
    if provider == "anthropic":
        headers["x-api-key"] = secret
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {secret}"

    request = Request(url, headers=headers, method="GET")

    try:
        with urlopen(request, timeout=float(timeout_seconds)) as response:
            status = int(getattr(response, "status", 200) or 200)
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            request_id = _safe_request_id(getattr(response, "headers", None))
    except HTTPError as exc:
        status = int(getattr(exc, "code", 0) or 0)
        request_id = _safe_request_id(getattr(exc, "headers", None))
        if status in {401, 403}:
            code = "AUTHENTICATION_FAILED"
            message = "The provider rejected the configured credential."
        elif status == 404:
            code = "MODEL_NOT_AVAILABLE"
            message = "The provider did not expose the bound exact model ID to this credential."
        elif status == 429:
            code = "PROVIDER_RATE_LIMITED"
            message = "The provider rate-limited the model metadata preflight."
        elif status >= 500:
            code = "PROVIDER_UNAVAILABLE"
            message = "The provider model metadata service is temporarily unavailable."
        else:
            code = "PROVIDER_PREFLIGHT_HTTP_ERROR"
            message = "The provider model metadata preflight returned an unexpected HTTP error."
        return _provider_probe_failure(
            provider_id=provider,
            model_id=model,
            code=code,
            message=message,
            http_status=status or None,
            request_id=request_id,
        )
    except (URLError, TimeoutError, OSError) as exc:
        reason = "timeout" if isinstance(exc, TimeoutError) else "network"
        return _provider_probe_failure(
            provider_id=provider,
            model_id=model,
            code="PROVIDER_UNREACHABLE",
            message=f"The provider model metadata preflight could not complete ({reason} failure).",
        )

    if status < 200 or status >= 300:
        return _provider_probe_failure(
            provider_id=provider,
            model_id=model,
            code="PROVIDER_PREFLIGHT_HTTP_ERROR",
            message="The provider model metadata preflight did not return a successful HTTP response.",
            http_status=status,
            request_id=request_id,
        )

    if len(body) > _MAX_RESPONSE_BYTES:
        return _provider_probe_failure(
            provider_id=provider,
            model_id=model,
            code="PROVIDER_RESPONSE_TOO_LARGE",
            message="The provider model metadata response exceeded the bounded preflight size.",
            http_status=status,
            request_id=request_id,
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _provider_probe_failure(
            provider_id=provider,
            model_id=model,
            code="PROVIDER_RESPONSE_INVALID",
            message="The provider model metadata response was not valid JSON.",
            http_status=status,
            request_id=request_id,
        )

    returned_model_id = (
        str(payload.get("id") or "").strip()
        if isinstance(payload, dict)
        else ""
    )
    if returned_model_id != model:
        return {
            **_provider_probe_failure(
                provider_id=provider,
                model_id=model,
                code="MODEL_IDENTITY_MISMATCH",
                message=(
                    "The provider authenticated the request but returned a different model ID. "
                    "Italus will not substitute aliases or another model for the project binding."
                ),
                http_status=status,
                request_id=request_id,
            ),
            "returned_model_id": returned_model_id or None,
        }

    safe_model_metadata: dict[str, Any] = {
        "id": returned_model_id,
    }
    if isinstance(payload, dict):
        for key in ("display_name", "owned_by", "shutdown_date", "max_input_tokens", "max_tokens"):
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_model_metadata[key] = value

    return {
        "status": "pass",
        "provider_id": provider,
        "requested_model_id": model,
        "returned_model_id": returned_model_id,
        "http_status": status,
        "request_id": request_id,
        "code": "PROVIDER_MODEL_CONFIRMED",
        "message": "Provider authentication succeeded and the exact bound model is available.",
        "model": safe_model_metadata,
    }


def _finalize(
    *,
    project_id: str,
    checked_at: str,
    checks: list[dict[str, Any]],
    binding: dict[str, Any] | None,
    credential: dict[str, Any] | None,
    pricing: dict[str, Any] | None,
    pricing_freshness: dict[str, Any] | None,
    pricing_version_sha256: str | None,
    provider_probe: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers = [item for item in checks if bool(item.get("blocking"))]
    warnings = [item for item in checks if item.get("status") == "warning"]
    ready = not blockers
    return {
        "status": "ok",
        "schema_version": PROVIDER_PREFLIGHT_SCHEMA_VERSION,
        "project_id": project_id,
        "checked_at": checked_at,
        "ready": ready,
        "result": "PASS" if ready else "BLOCKED",
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "binding": (
            {
                "provider_id": binding.get("provider_id"),
                "model_id": binding.get("model_id"),
                "service_tier": binding.get("service_tier"),
                "inference_scope": binding.get("inference_scope"),
                "binding_instance_id": binding.get("binding_instance_id"),
            }
            if isinstance(binding, dict)
            else None
        ),
        "credential": (
            {
                "status": credential.get("status"),
                "source": credential.get("source"),
                "credential_instance_id": credential.get("credential_instance_id"),
                "lineage_status": credential.get("lineage_status"),
            }
            if isinstance(credential, dict)
            else None
        ),
        "pricing": (
            {
                "pricing_version_id": pricing.get("pricing_version_id"),
                "pricing_version_sha256": pricing_version_sha256,
                "currency": pricing.get("currency"),
                "effective_from": pricing.get("effective_from"),
                "verified_at": pricing.get("verified_at"),
                "source_url": pricing.get("source_url"),
            }
            if isinstance(pricing, dict)
            else None
        ),
        "pricing_freshness": pricing_freshness,
        "provider_probe": provider_probe,
        "execution": {
            "provider_execution_allowed": False,
            "generation_attempted": False,
            "usage_recorded": False,
            "reason": (
                "Primary 33.2.1B preflight validates configuration, credential authentication, "
                "exact model availability, and pricing only. Real provider generation remains locked."
            ),
        },
    }


def run_project_provider_preflight(
    project_id: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the non-generating project/provider preflight.

    The provider call is limited to the provider's model metadata endpoint. This
    function does not write project state, record usage, execute generation, or
    return provider credential plaintext.
    """

    checked_at = _utc_iso()
    checks: list[dict[str, Any]] = []
    binding: dict[str, Any] | None = None
    credential: dict[str, Any] | None = None
    pricing: dict[str, Any] | None = None
    pricing_freshness: dict[str, Any] | None = None
    pricing_version_sha256: str | None = None
    provider_probe: dict[str, Any] | None = None

    binding_payload = provider_binding_service.get_project_provider_binding(project_id)
    raw_binding = binding_payload.get("binding")
    binding = raw_binding if isinstance(raw_binding, dict) else None
    if binding is None:
        checks.append(
            _check(
                "project_binding",
                status="blocked",
                code="PROJECT_PROVIDER_NOT_BOUND",
                message="Bind a saved direct-provider profile to this project before preflight.",
                blocking=True,
            )
        )
        return _finalize(
            project_id=project_id,
            checked_at=checked_at,
            checks=checks,
            binding=None,
            credential=None,
            pricing=None,
            pricing_freshness=None,
            pricing_version_sha256=None,
            provider_probe=None,
        )

    provider_id = str(binding.get("provider_id") or "").strip().lower()
    model_id = str(binding.get("model_id") or "").strip()
    service_tier = str(binding.get("service_tier") or "standard").strip().lower()
    inference_scope = str(binding.get("inference_scope") or "global").strip().lower()
    binding_instance_id = str(binding.get("binding_instance_id") or "").strip()

    if provider_id not in provider_config_service.DIRECT_PROVIDER_IDS:
        checks.append(
            _check(
                "project_binding",
                status="blocked",
                code="DIRECT_PROVIDER_REQUIRED",
                message="The project must use an enabled direct provider for this preflight.",
                blocking=True,
            )
        )
    elif not binding_instance_id:
        checks.append(
            _check(
                "project_binding",
                status="blocked",
                code="BINDING_LINEAGE_MISSING",
                message="The project provider binding is missing its binding-instance lineage.",
                blocking=True,
            )
        )
    else:
        checks.append(
            _check(
                "project_binding",
                status="pass",
                code="PROJECT_BINDING_READY",
                message="Project provider binding and binding-instance lineage are present.",
            )
        )

    profile = provider_config_service.get_provider_profile(provider_id) if provider_id else None
    if profile is None:
        checks.append(
            _check(
                "provider_profile",
                status="blocked",
                code="PROVIDER_PROFILE_MISSING",
                message="The bound provider profile no longer exists.",
                blocking=True,
            )
        )
    else:
        checks.append(
            _check(
                "provider_profile",
                status="pass",
                code="PROVIDER_PROFILE_READY",
                message="The reusable provider profile is present.",
            )
        )

    try:
        provider_config_service.require_accepted_model_id(provider_id, model_id)
    except provider_config_service.ProviderConfigError:
        checks.append(
            _check(
                "model_catalog",
                status="blocked",
                code="MODEL_NOT_ACCEPTED",
                message="The exact project model ID is not accepted by the direct-provider catalog.",
                blocking=True,
            )
        )
    else:
        checks.append(
            _check(
                "model_catalog",
                status="pass",
                code="MODEL_ACCEPTED",
                message="The exact project model ID is accepted by the direct-provider catalog.",
            )
        )

    try:
        credential = provider_credential_service.credential_state(provider_id)
    except provider_credential_service.ProviderCredentialError:
        credential = None
    if not isinstance(credential, dict) or credential.get("status") != "configured":
        checks.append(
            _check(
                "credential",
                status="blocked",
                code="CREDENTIAL_NOT_CONFIGURED",
                message="The trusted credential backend does not report a configured provider credential.",
                blocking=True,
            )
        )
    else:
        checks.append(
            _check(
                "credential",
                status="pass",
                code="CREDENTIAL_CONFIGURED",
                message="The trusted backend reports a configured provider credential.",
            )
        )

    try:
        pricing_payload = provider_pricing_service.get_current_pricing(
            provider_id=provider_id,
            model_id=model_id,
            service_tier=service_tier,
            inference_scope=inference_scope,
        )
    except provider_pricing_service.ProviderPricingError:
        pricing_payload = {}

    raw_pricing = pricing_payload.get("pricing") if isinstance(pricing_payload, dict) else None
    pricing = raw_pricing if isinstance(raw_pricing, dict) else None
    pricing_freshness = (
        pricing_payload.get("freshness")
        if isinstance(pricing_payload, dict) and isinstance(pricing_payload.get("freshness"), dict)
        else None
    )

    if pricing is None:
        checks.append(
            _check(
                "pricing",
                status="blocked",
                code="EFFECTIVE_PRICING_MISSING",
                message="No effective immutable pricing version exists for the exact project provider/model/tier/scope.",
                blocking=True,
            )
        )
    else:
        version_id = str(pricing.get("pricing_version_id") or "").strip()
        try:
            snapshot = provider_pricing_service.get_pricing_version_snapshot(version_id)
            pricing_version_sha256 = str(snapshot.get("pricing_version_sha256") or "").strip() or None
        except provider_pricing_service.ProviderPricingError:
            pricing_version_sha256 = None

        if not version_id or not pricing_version_sha256:
            checks.append(
                _check(
                    "pricing",
                    status="blocked",
                    code="PRICING_PROVENANCE_INCOMPLETE",
                    message="The effective pricing version is missing immutable pricing provenance.",
                    blocking=True,
                )
            )
        else:
            checks.append(
                _check(
                    "pricing",
                    status="pass",
                    code="EFFECTIVE_PRICING_READY",
                    message="An effective immutable pricing version and integrity hash are available.",
                )
            )

        freshness_status = str((pricing_freshness or {}).get("status") or "").strip()
        if freshness_status == "SOURCE_MISSING":
            checks.append(
                _check(
                    "pricing_freshness",
                    status="blocked",
                    code="PRICING_SOURCE_MISSING",
                    message="The effective pricing version has no official pricing source.",
                    blocking=True,
                )
            )
        elif freshness_status == "REVIEW_RECOMMENDED":
            checks.append(
                _check(
                    "pricing_freshness",
                    status="warning",
                    code="PRICING_REVIEW_RECOMMENDED",
                    message=str((pricing_freshness or {}).get("message") or "Pricing review is recommended."),
                )
            )
        else:
            checks.append(
                _check(
                    "pricing_freshness",
                    status="pass",
                    code="PRICING_FRESHNESS_ACCEPTABLE",
                    message=str((pricing_freshness or {}).get("message") or "Pricing freshness policy is satisfied."),
                )
            )

    if any(bool(item.get("blocking")) for item in checks):
        return _finalize(
            project_id=project_id,
            checked_at=checked_at,
            checks=checks,
            binding=binding,
            credential=credential,
            pricing=pricing,
            pricing_freshness=pricing_freshness,
            pricing_version_sha256=pricing_version_sha256,
            provider_probe=None,
        )

    try:
        api_key = provider_credential_service.resolve_api_key(provider_id)
    except provider_credential_service.ProviderCredentialError:
        api_key = None

    if not api_key:
        checks.append(
            _check(
                "credential_resolution",
                status="blocked",
                code="CREDENTIAL_RESOLUTION_FAILED",
                message="The trusted credential backend could not resolve the configured credential.",
                blocking=True,
            )
        )
        return _finalize(
            project_id=project_id,
            checked_at=checked_at,
            checks=checks,
            binding=binding,
            credential=credential,
            pricing=pricing,
            pricing_freshness=pricing_freshness,
            pricing_version_sha256=pricing_version_sha256,
            provider_probe=None,
        )

    checks.append(
        _check(
            "credential_resolution",
            status="pass",
            code="CREDENTIAL_RESOLVED_BACKEND_ONLY",
            message="The trusted backend resolved the credential for server-side preflight only.",
        )
    )

    provider_probe = _provider_model_probe(
        provider_id,
        model_id,
        api_key,
        timeout_seconds=timeout_seconds,
    )
    if provider_probe.get("status") == "pass":
        checks.append(
            _check(
                "provider_auth_model",
                status="pass",
                code="PROVIDER_AUTH_MODEL_CONFIRMED",
                message="Provider authentication succeeded and the exact project model is available.",
            )
        )
    else:
        checks.append(
            _check(
                "provider_auth_model",
                status="blocked",
                code=str(provider_probe.get("code") or "PROVIDER_PREFLIGHT_FAILED"),
                message=str(provider_probe.get("message") or "Provider authentication/model preflight failed."),
                blocking=True,
            )
        )

    return _finalize(
        project_id=project_id,
        checked_at=checked_at,
        checks=checks,
        binding=binding,
        credential=credential,
        pricing=pricing,
        pricing_freshness=pricing_freshness,
        pricing_version_sha256=pricing_version_sha256,
        provider_probe=provider_probe,
    )
