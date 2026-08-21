"""
Bounded local Planner Intent Model adapter.

Patch 26 adds a local-only natural-language intent interpreter for Planner Query.
The adapter is intentionally isolated from prose generation providers and does not
load Canon, Book Runtime Context, prior prose, or continuity. It accepts only the
bounded request constructed by planner_query_service and returns model text.

Configuration is environment-only so enabling the Planner intent model does not
change project story state:

    ITALUS_PLANNER_INTENT_MODEL=<local Ollama model name>
    ITALUS_PLANNER_INTENT_ENDPOINT=http://127.0.0.1:11434/api/generate
    ITALUS_PLANNER_INTENT_TIMEOUT_SECONDS=20

The endpoint must resolve to localhost/loopback. Cloud fallback is not wired in
this patch; Planner Query remains fully deterministic when the local model is not
configured or unavailable.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PLANNER_INTENT_ADAPTER_MARKER = "planner-intent-local-ollama-v1-20260817"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PROFILE = "bounded-planner-intent-v1"

ENV_MODEL = "ITALUS_PLANNER_INTENT_MODEL"
ENV_ENDPOINT = "ITALUS_PLANNER_INTENT_ENDPOINT"
ENV_TIMEOUT = "ITALUS_PLANNER_INTENT_TIMEOUT_SECONDS"
ENV_PROFILE = "ITALUS_PLANNER_INTENT_PROFILE"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class PlannerIntentModelError(RuntimeError):
    """Base error for the bounded Planner Intent transport."""


class PlannerIntentModelUnavailable(PlannerIntentModelError):
    """Raised when the configured local intent model cannot be used."""


class PlannerIntentModelResponseError(PlannerIntentModelError):
    """Raised when the local server response violates the transport contract."""


def get_local_intent_model_status() -> dict[str, Any]:
    model = str(os.getenv(ENV_MODEL, "") or "").strip()
    endpoint = str(os.getenv(ENV_ENDPOINT, DEFAULT_ENDPOINT) or DEFAULT_ENDPOINT).strip()
    profile = str(os.getenv(ENV_PROFILE, DEFAULT_PROFILE) or DEFAULT_PROFILE).strip()
    timeout = _timeout_seconds()

    endpoint_is_local = _is_loopback_endpoint(endpoint)
    configured = bool(model) and endpoint_is_local

    return {
        "adapter": PLANNER_INTENT_ADAPTER_MARKER,
        "provider": "ollama_local",
        "model": model,
        "profile": profile,
        "endpoint": endpoint,
        "timeout_seconds": timeout,
        "configured": configured,
        "endpoint_is_local": endpoint_is_local,
        "cloud_fallback_configured": False,
    }


def generate_json(
    *,
    bounded_request: dict[str, Any],
    system_prompt: str,
) -> dict[str, Any]:
    """Invoke the configured local model with a bounded Planner request."""

    config = _required_config()
    prompt = json.dumps(bounded_request, ensure_ascii=False, separators=(",", ":"))
    raw = _invoke_ollama(
        endpoint=config["endpoint"],
        model=config["model"],
        system_prompt=system_prompt,
        prompt=prompt,
        timeout_seconds=config["timeout_seconds"],
    )
    return {
        "provider": "ollama_local",
        "model": config["model"],
        "profile": config["profile"],
        "raw_output": raw,
        "fallback_used": False,
    }


def repair_json(
    *,
    malformed_output: str,
    output_schema: dict[str, Any],
) -> dict[str, Any]:
    """Perform one bounded JSON repair using only malformed output + schema."""

    config = _required_config()
    system_prompt = (
        "You repair JSON only. Return one JSON object matching the supplied schema. "
        "Do not add story facts, Canon candidates, eligibility decisions, legal/authorization "
        "claims, or explanatory prose."
    )
    repair_payload = {
        "malformed_output": str(malformed_output or ""),
        "output_schema": output_schema,
    }
    prompt = json.dumps(repair_payload, ensure_ascii=False, separators=(",", ":"))
    raw = _invoke_ollama(
        endpoint=config["endpoint"],
        model=config["model"],
        system_prompt=system_prompt,
        prompt=prompt,
        timeout_seconds=config["timeout_seconds"],
    )
    return {
        "provider": "ollama_local",
        "model": config["model"],
        "profile": config["profile"],
        "raw_output": raw,
        "fallback_used": False,
    }


def _required_config() -> dict[str, Any]:
    status = get_local_intent_model_status()
    model = str(status.get("model") or "")
    endpoint = str(status.get("endpoint") or "")

    if not model:
        raise PlannerIntentModelUnavailable(
            f"Planner Intent Model is not configured. Set {ENV_MODEL} to a local Ollama model name."
        )
    if not status.get("endpoint_is_local"):
        raise PlannerIntentModelUnavailable(
            "Planner Intent Model endpoint must use localhost/loopback. "
            "Patch 26 does not send Planner intent data to remote endpoints."
        )
    return {
        "model": model,
        "endpoint": endpoint,
        "profile": str(status.get("profile") or DEFAULT_PROFILE),
        "timeout_seconds": float(status.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
    }


def _invoke_ollama(
    *,
    endpoint: str,
    model: str,
    system_prompt: str,
    prompt: str,
    timeout_seconds: float,
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except (URLError, TimeoutError, OSError) as exc:
        raise PlannerIntentModelUnavailable(
            f"Local Planner Intent Model is unavailable: {exc}"
        ) from exc
    except HTTPError as exc:
        raise PlannerIntentModelUnavailable(
            f"Local Planner Intent Model returned HTTP {exc.code}."
        ) from exc

    try:
        payload_obj = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PlannerIntentModelResponseError(
            "Local Planner Intent Model transport returned invalid JSON."
        ) from exc

    raw = payload_obj.get("response")
    if raw is None and isinstance(payload_obj.get("message"), dict):
        raw = payload_obj["message"].get("content")
    if not isinstance(raw, str) or not raw.strip():
        raise PlannerIntentModelResponseError(
            "Local Planner Intent Model response did not contain model text."
        )
    return raw.strip()


def _timeout_seconds() -> float:
    raw = str(os.getenv(ENV_TIMEOUT, "") or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return min(max(value, 1.0), 120.0)


def _is_loopback_endpoint(endpoint: str) -> bool:
    try:
        parsed = urlparse(endpoint)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return str(parsed.hostname or "").casefold() in _LOOPBACK_HOSTS
