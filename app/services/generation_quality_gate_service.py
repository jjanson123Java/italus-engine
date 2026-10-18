"""Fail-closed post-provider generation quality gate."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services import prose_rulebook_service


SERVICE_MARKER = "primary45c-generation-quality-gate-v1"
SCHEMA_VERSION = "generation_quality_gate_v1"

_TRUNCATION_REASONS = frozenset({
    "max_tokens",
    "max_output_tokens",
    "length",
    "token_limit",
})


class GenerationQualityGateError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def evaluate_output(
    output_text: str,
    *,
    stop_reason: str | None,
    hard_prose_metrics: dict[str, Any],
) -> dict[str, Any]:
    text = str(output_text or "")
    reason = str(stop_reason or "").strip().lower()
    blockers: list[dict[str, Any]] = []

    if not text.strip():
        blockers.append({
            "code": "EMPTY_PROVIDER_OUTPUT",
            "message": "Provider returned empty generation output.",
        })

    if reason in _TRUNCATION_REASONS:
        blockers.append({
            "code": "INCOMPLETE_PROVIDER_OUTPUT",
            "message": f"Provider stopped because of output limit: {reason}.",
            "stop_reason": reason,
        })

    try:
        metric_results = prose_rulebook_service.evaluate_deterministic_metrics(
            text,
            dict(hard_prose_metrics or {}),
        )
    except prose_rulebook_service.ProseRulebookError as exc:
        raise GenerationQualityGateError(
            "GENERATION_QUALITY_CONTRACT_INVALID",
            str(exc),
        ) from exc

    for name, result in metric_results.items():
        if result.get("passed") is not True:
            blockers.append({
                "code": "DETERMINISTIC_PROSE_FAILURE",
                "metric": name,
                "message": str(result.get("message") or ""),
                "measurement": result.get("measurement"),
                "operator": result.get("operator"),
                "threshold": result.get("threshold"),
            })

    return {
        "schema_version": SCHEMA_VERSION,
        "service": SERVICE_MARKER,
        "passed": not blockers,
        "stop_reason": reason,
        "deterministic_metrics": deepcopy(metric_results),
        "blockers": blockers,
    }


def require_pass(report: dict[str, Any]) -> None:
    if report.get("passed") is True:
        return
    blockers = list(report.get("blockers") or [])
    codes = [str(item.get("code") or "") for item in blockers if isinstance(item, dict)]
    code = "INCOMPLETE_PROVIDER_OUTPUT" if "INCOMPLETE_PROVIDER_OUTPUT" in codes else "GENERATION_QUALITY_FAILED"
    raise GenerationQualityGateError(
        code,
        "Provider output failed the generation quality gate and was not promoted to author review.",
        details={"quality_gate": deepcopy(report)},
    )
