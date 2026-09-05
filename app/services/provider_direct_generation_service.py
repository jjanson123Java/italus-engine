from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable


DIRECT_GENERATION_SCHEMA_VERSION = "primary33.2.2-direct-provider-generation-v1"
DEFAULT_TIMEOUT_SECONDS = 180.0
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ProviderDirectGenerationError(RuntimeError):
    """Raised when a direct provider generation cannot be completed safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider_id: str,
        http_status: int | None = None,
        request_id: str | None = None,
        reconciliation_required: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.provider_id = str(provider_id)
        self.http_status = http_status
        self.request_id = request_id
        self.reconciliation_required = bool(reconciliation_required)
        self.details = dict(details or {})

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "provider_id": self.provider_id,
            "http_status": self.http_status,
            "request_id": self.request_id,
            "reconciliation_required": self.reconciliation_required,
            "details": dict(self.details),
        }


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_json_response(response: Any) -> dict[str, Any]:
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Provider response exceeds the supported response size.")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Provider response must be a JSON object.")
    return payload


def _header_value(headers: Any, *names: str) -> str | None:
    for name in names:
        try:
            value = headers.get(name)
        except AttributeError:
            value = None
        cleaned = str(value or "").strip()
        if cleaned:
            return cleaned
    return None


def _nonnegative_int(
    value: Any,
    field: str,
    *,
    provider_id: str,
    request_id: str | None,
) -> int:
    if isinstance(value, bool):
        raise ProviderDirectGenerationError(
            "PROVIDER_USAGE_INVALID",
            f"Provider usage field {field} is invalid.",
            provider_id=provider_id,
            request_id=request_id,
            reconciliation_required=True,
        )
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ProviderDirectGenerationError(
            "PROVIDER_USAGE_INVALID",
            f"Provider usage field {field} is missing or invalid.",
            provider_id=provider_id,
            request_id=request_id,
            reconciliation_required=True,
        ) from exc
    if number < 0:
        raise ProviderDirectGenerationError(
            "PROVIDER_USAGE_INVALID",
            f"Provider usage field {field} cannot be negative.",
            provider_id=provider_id,
            request_id=request_id,
            reconciliation_required=True,
        )
    return number


def _extract_openai_output(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if str(block.get("type") or "") != "output_text":
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
    if parts:
        return "".join(parts)
    top_level = payload.get("output_text")
    return top_level if isinstance(top_level, str) else ""


def _openai_usage(
    payload: dict[str, Any],
    *,
    request_id: str | None,
) -> dict[str, int]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ProviderDirectGenerationError(
            "PROVIDER_USAGE_MISSING",
            "OpenAI returned a response without authoritative usage data.",
            provider_id="openai",
            request_id=request_id,
            reconciliation_required=True,
        )
    total_input = _nonnegative_int(
        usage.get("input_tokens"),
        "input_tokens",
        provider_id="openai",
        request_id=request_id,
    )
    output_tokens = _nonnegative_int(
        usage.get("output_tokens"),
        "output_tokens",
        provider_id="openai",
        request_id=request_id,
    )
    input_details = usage.get("input_tokens_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    cached_tokens = _nonnegative_int(
        input_details.get("cached_tokens", 0),
        "input_tokens_details.cached_tokens",
        provider_id="openai",
        request_id=request_id,
    )
    if cached_tokens > total_input:
        raise ProviderDirectGenerationError(
            "PROVIDER_USAGE_INVALID",
            "OpenAI cached input tokens exceed total input tokens.",
            provider_id="openai",
            request_id=request_id,
            reconciliation_required=True,
        )
    return {
        "actual_input_tokens": total_input - cached_tokens,
        "actual_output_tokens": output_tokens,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
        "cache_read_tokens": cached_tokens,
    }


def _anthropic_usage(
    payload: dict[str, Any],
    *,
    request_id: str | None,
) -> dict[str, int]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ProviderDirectGenerationError(
            "PROVIDER_USAGE_MISSING",
            "Anthropic returned a response without authoritative usage data.",
            provider_id="anthropic",
            request_id=request_id,
            reconciliation_required=True,
        )

    input_tokens = _nonnegative_int(
        usage.get("input_tokens"),
        "input_tokens",
        provider_id="anthropic",
        request_id=request_id,
    )
    output_tokens = _nonnegative_int(
        usage.get("output_tokens"),
        "output_tokens",
        provider_id="anthropic",
        request_id=request_id,
    )
    cache_read = _nonnegative_int(
        usage.get("cache_read_input_tokens", 0),
        "cache_read_input_tokens",
        provider_id="anthropic",
        request_id=request_id,
    )
    cache_creation_total = _nonnegative_int(
        usage.get("cache_creation_input_tokens", 0),
        "cache_creation_input_tokens",
        provider_id="anthropic",
        request_id=request_id,
    )

    cache_creation = usage.get("cache_creation")
    cache_creation = cache_creation if isinstance(cache_creation, dict) else {}
    cache_write_5m = _nonnegative_int(
        cache_creation.get("ephemeral_5m_input_tokens", 0),
        "cache_creation.ephemeral_5m_input_tokens",
        provider_id="anthropic",
        request_id=request_id,
    )
    cache_write_1h = _nonnegative_int(
        cache_creation.get("ephemeral_1h_input_tokens", 0),
        "cache_creation.ephemeral_1h_input_tokens",
        provider_id="anthropic",
        request_id=request_id,
    )

    split_total = cache_write_5m + cache_write_1h
    if cache_creation_total and split_total != cache_creation_total:
        raise ProviderDirectGenerationError(
            "PROVIDER_USAGE_CACHE_DETAIL_AMBIGUOUS",
            (
                "Anthropic reported cache-creation usage without an exact "
                "5-minute/1-hour split required by the configured pricing contract."
            ),
            provider_id="anthropic",
            request_id=request_id,
            reconciliation_required=True,
            details={
                "cache_creation_input_tokens": cache_creation_total,
                "split_cache_creation_input_tokens": split_total,
            },
        )

    return {
        "actual_input_tokens": input_tokens,
        "actual_output_tokens": output_tokens,
        "cache_write_5m_tokens": cache_write_5m,
        "cache_write_1h_tokens": cache_write_1h,
        "cache_read_tokens": cache_read,
    }


def _http_failure(
    provider_id: str,
    status: int,
    *,
    request_id: str | None,
) -> ProviderDirectGenerationError:
    if status in (401, 403):
        code = "AUTHENTICATION_FAILED"
        message = "The provider rejected the configured credential."
    elif status == 404:
        code = "MODEL_NOT_AVAILABLE"
        message = "The exact configured provider model is not available."
    elif status == 429:
        code = "PROVIDER_RATE_LIMITED"
        message = "The provider rate-limited the generation request."
    elif status >= 500:
        code = "PROVIDER_UNAVAILABLE"
        message = "The provider generation service is temporarily unavailable."
    elif status == 400:
        code = "PROVIDER_REQUEST_REJECTED"
        message = "The provider rejected the generation request."
    else:
        code = "PROVIDER_REQUEST_FAILED"
        message = f"The provider generation request failed with HTTP {status}."
    return ProviderDirectGenerationError(
        code,
        message,
        provider_id=provider_id,
        http_status=status,
        request_id=request_id,
        reconciliation_required=False,
    )


def _post_json(
    *,
    provider_id: str,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_seconds: float,
    opener: Callable[..., Any],
) -> tuple[dict[str, Any], int, str | None]:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers=headers,
        method="POST",
    )
    try:
        response = opener(request, timeout=float(timeout_seconds))
        try:
            status = int(getattr(response, "status", 200) or 200)
            request_id = _header_value(
                getattr(response, "headers", None),
                "x-request-id",
                "request-id",
            )
            if status < 200 or status >= 300:
                raise _http_failure(
                    provider_id,
                    status,
                    request_id=request_id,
                )
            try:
                payload = _bounded_json_response(response)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ProviderDirectGenerationError(
                    "PROVIDER_RESPONSE_INVALID",
                    "The provider returned an invalid or oversized generation response.",
                    provider_id=provider_id,
                    http_status=status,
                    request_id=request_id,
                    reconciliation_required=True,
                ) from exc
            return payload, status, request_id
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
    except urllib.error.HTTPError as exc:
        request_id = _header_value(
            getattr(exc, "headers", None),
            "x-request-id",
            "request-id",
        )
        raise _http_failure(
            provider_id,
            int(exc.code),
            request_id=request_id,
        ) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise ProviderDirectGenerationError(
            "PROVIDER_NETWORK_AMBIGUOUS",
            (
                "The provider generation request did not complete with a reliable "
                "HTTP response. Automatic replay is blocked until the attempt is reconciled."
            ),
            provider_id=provider_id,
            reconciliation_required=True,
        ) from exc


def _openai_generate(
    *,
    model_id: str,
    prompt_text: str,
    max_output_tokens: int,
    api_key: str,
    timeout_seconds: float,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    payload, status, header_request_id = _post_json(
        provider_id="openai",
        url=OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        body={
            "model": model_id,
            "input": prompt_text,
            "max_output_tokens": int(max_output_tokens),
            "store": False,
        },
        timeout_seconds=timeout_seconds,
        opener=opener,
    )
    response_id = str(payload.get("id") or header_request_id or "").strip() or None
    returned_model = str(payload.get("model") or "").strip() or None
    usage = _openai_usage(payload, request_id=response_id)
    return {
        "schema_version": DIRECT_GENERATION_SCHEMA_VERSION,
        "provider_id": "openai",
        "requested_model_id": model_id,
        "returned_model_id": returned_model,
        "provider_request_id": response_id,
        "http_status": status,
        "provider_status": str(payload.get("status") or "completed"),
        "stop_reason": (
            str((payload.get("incomplete_details") or {}).get("reason") or "")
            if isinstance(payload.get("incomplete_details"), dict)
            else None
        ) or None,
        "output_text": _extract_openai_output(payload),
        "usage": usage,
        "received_at": _utc_iso(),
    }


def _anthropic_generate(
    *,
    model_id: str,
    prompt_text: str,
    max_output_tokens: int,
    api_key: str,
    timeout_seconds: float,
    opener: Callable[..., Any],
) -> dict[str, Any]:
    payload, status, header_request_id = _post_json(
        provider_id="anthropic",
        url=ANTHROPIC_MESSAGES_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        body={
            "model": model_id,
            "max_tokens": int(max_output_tokens),
            "messages": [{"role": "user", "content": prompt_text}],
        },
        timeout_seconds=timeout_seconds,
        opener=opener,
    )
    response_id = str(payload.get("id") or header_request_id or "").strip() or None
    returned_model = str(payload.get("model") or "").strip() or None
    content = payload.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if (
                isinstance(block, dict)
                and str(block.get("type") or "") == "text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
    usage = _anthropic_usage(payload, request_id=response_id)
    return {
        "schema_version": DIRECT_GENERATION_SCHEMA_VERSION,
        "provider_id": "anthropic",
        "requested_model_id": model_id,
        "returned_model_id": returned_model,
        "provider_request_id": response_id,
        "http_status": status,
        "provider_status": "completed",
        "stop_reason": str(payload.get("stop_reason") or "").strip() or None,
        "output_text": "".join(parts),
        "usage": usage,
        "received_at": _utc_iso(),
    }


def execute_direct_generation(
    *,
    provider_id: str,
    model_id: str,
    prompt_text: str,
    max_output_tokens: int,
    api_key: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Execute one direct-provider text generation request.

    The caller owns project binding, credential lineage, pricing lineage, receipt
    persistence, and usage-ledger commitment. This function owns only the fixed
    direct-provider HTTP contract and provider-authoritative response parsing.
    """
    provider = str(provider_id or "").strip().lower()
    model = str(model_id or "").strip()
    prompt = str(prompt_text or "")
    secret = str(api_key or "").strip()

    if provider not in {"openai", "anthropic"}:
        raise ProviderDirectGenerationError(
            "DIRECT_PROVIDER_REQUIRED",
            "Real provider execution is limited to enabled direct providers.",
            provider_id=provider or "unknown",
        )
    if not model:
        raise ProviderDirectGenerationError(
            "MODEL_ID_REQUIRED",
            "An exact provider model ID is required.",
            provider_id=provider,
        )
    if not prompt:
        raise ProviderDirectGenerationError(
            "PROMPT_REQUIRED",
            "The provider generation prompt must not be empty.",
            provider_id=provider,
        )
    if not secret:
        raise ProviderDirectGenerationError(
            "CREDENTIAL_REQUIRED",
            "A backend-resolved provider credential is required.",
            provider_id=provider,
        )
    if isinstance(max_output_tokens, bool) or int(max_output_tokens) <= 0:
        raise ProviderDirectGenerationError(
            "OUTPUT_TOKEN_LIMIT_INVALID",
            "max_output_tokens must be a positive integer.",
            provider_id=provider,
        )
    if float(timeout_seconds) <= 0:
        raise ProviderDirectGenerationError(
            "TIMEOUT_INVALID",
            "timeout_seconds must be positive.",
            provider_id=provider,
        )

    call = opener or urllib.request.urlopen
    if provider == "openai":
        return _openai_generate(
            model_id=model,
            prompt_text=prompt,
            max_output_tokens=int(max_output_tokens),
            api_key=secret,
            timeout_seconds=float(timeout_seconds),
            opener=call,
        )
    return _anthropic_generate(
        model_id=model,
        prompt_text=prompt,
        max_output_tokens=int(max_output_tokens),
        api_key=secret,
        timeout_seconds=float(timeout_seconds),
        opener=call,
    )
