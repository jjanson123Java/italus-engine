from __future__ import annotations

from copy import deepcopy
from typing import Any


MODEL_CATALOG_SCHEMA_VERSION = "primary33.2.1a-direct-model-catalog-v1"
SOURCE_ARTIFACT_NAME = "ITALUS_PROVIDER_MODEL_IDS (1).md"
SOURCE_ARTIFACT_SHA256 = "7b2ef5cac7d63925adfed86e5edcb6cc3835c9ecee26770befea4d99a1cfbfb3"
SOURCE_REFERENCE_DATE = "2026-09-02"
PRICING_CHECKED_DATE = "2026-09-03"
CATALOG_EFFECTIVE_FROM = "2026-09-03T00:00:00Z"
CATALOG_VERIFIED_AT = "2026-09-03T00:00:00Z"

_PROVIDER_SOURCES: dict[str, dict[str, str]] = {
    "anthropic": {
        "model_source_url": (
            "https://platform.claude.com/docs/en/models/overview"
            "#latest-models-comparison"
        ),
        "pricing_source_url": (
            "https://platform.claude.com/docs/en/about-claude/pricing"
        ),
    },
    "openai": {
        "model_source_url": "https://developers.openai.com/api/docs/models/all",
        "pricing_source_url": (
            "https://openai.com/index/"
            "advancing-the-price-performance-frontier-with-gpt-5-6/"
        ),
    },
}


def _pricing_reference(
    *,
    provider_id: str,
    input_per_mtok: str,
    output_per_mtok: str,
    cache_read_per_mtok: str,
    cache_write_5m_per_mtok: str = "0",
    cache_write_1h_per_mtok: str = "0",
    not_applicable_fields: tuple[str, ...] = (),
    additional_terms: dict[str, Any] | None = None,
    notes: str,
) -> dict[str, Any]:
    return {
        "currency": "USD",
        "service_tier": "standard",
        "inference_scope": "global",
        "effective_from": CATALOG_EFFECTIVE_FROM,
        "verified_at": CATALOG_VERIFIED_AT,
        "source_url": _PROVIDER_SOURCES[provider_id]["pricing_source_url"],
        "registry_rates_per_mtok": {
            "input_per_mtok": input_per_mtok,
            "output_per_mtok": output_per_mtok,
            "cache_write_5m_per_mtok": cache_write_5m_per_mtok,
            "cache_write_1h_per_mtok": cache_write_1h_per_mtok,
            "cache_read_per_mtok": cache_read_per_mtok,
        },
        "not_applicable_registry_fields": list(not_applicable_fields),
        "additional_terms": deepcopy(additional_terms or {}),
        "notes": notes,
        "source_artifact": SOURCE_ARTIFACT_NAME,
        "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
        "pricing_checked_date": PRICING_CHECKED_DATE,
    }


_MODELS: dict[str, tuple[dict[str, Any], ...]] = {
    "anthropic": (
        {
            "display_name": "Claude Opus 5",
            "model_id": "claude-opus-5",
            "catalog_tier": "premium",
            "status": "production",
            "capabilities": ["text_generation", "reasoning"],
            "enabled": True,
            "is_default": False,
            "recommended_use": "Complex generation and high-quality revision",
            "pricing_reference": _pricing_reference(
                provider_id="anthropic",
                input_per_mtok="5",
                output_per_mtok="25",
                cache_write_5m_per_mtok="6.25",
                cache_write_1h_per_mtok="10",
                cache_read_per_mtok="0.5",
                additional_terms={
                    "batch_input_per_mtok": "2.5",
                    "batch_output_per_mtok": "12.5",
                    "fast_mode_input_per_mtok": "10",
                    "fast_mode_output_per_mtok": "50",
                },
                notes=(
                    "Curated Primary 33.2.1A reference. Anthropic standard synchronous "
                    "list pricing checked 2026-09-03. Batch and fast-mode rates are "
                    "reference metadata only and are not enabled execution modes."
                ),
            ),
        },
        {
            "display_name": "Claude Sonnet 5",
            "model_id": "claude-sonnet-5",
            "catalog_tier": "balanced",
            "status": "production",
            "capabilities": ["text_generation", "reasoning"],
            "enabled": True,
            "is_default": True,
            "recommended_use": "Default Anthropic model",
            "pricing_reference": _pricing_reference(
                provider_id="anthropic",
                input_per_mtok="2",
                output_per_mtok="10",
                cache_write_5m_per_mtok="2.5",
                cache_write_1h_per_mtok="4",
                cache_read_per_mtok="0.2",
                additional_terms={
                    "batch_input_per_mtok": "1",
                    "batch_output_per_mtok": "5",
                },
                notes=(
                    "Curated Primary 33.2.1A reference. Anthropic standard synchronous "
                    "list pricing checked 2026-09-03. The supplied reference states the "
                    "previously scheduled 2026-09-01 price increase was cancelled."
                ),
            ),
        },
        {
            "display_name": "Claude Haiku 4.5",
            "model_id": "claude-haiku-4-5-20251001",
            "catalog_tier": "economy",
            "status": "production",
            "capabilities": ["text_generation", "reasoning"],
            "enabled": True,
            "is_default": False,
            "recommended_use": "Fast, lower-cost operations",
            "pricing_reference": _pricing_reference(
                provider_id="anthropic",
                input_per_mtok="1",
                output_per_mtok="5",
                cache_write_5m_per_mtok="1.25",
                cache_write_1h_per_mtok="2",
                cache_read_per_mtok="0.1",
                additional_terms={
                    "batch_input_per_mtok": "0.5",
                    "batch_output_per_mtok": "2.5",
                },
                notes=(
                    "Curated Primary 33.2.1A reference. Anthropic standard synchronous "
                    "list pricing checked 2026-09-03. Batch pricing is retained as "
                    "reference metadata only."
                ),
            ),
        },
    ),
    "openai": (
        {
            "display_name": "GPT-5.6 Sol",
            "model_id": "gpt-5.6-sol",
            "catalog_tier": "premium",
            "status": "production",
            "capabilities": ["text_generation", "reasoning"],
            "enabled": True,
            "is_default": False,
            "recommended_use": "Highest-quality generation and reasoning",
            "pricing_reference": _pricing_reference(
                provider_id="openai",
                input_per_mtok="5",
                output_per_mtok="30",
                cache_read_per_mtok="0.5",
                not_applicable_fields=(
                    "cache_write_5m_per_mtok",
                    "cache_write_1h_per_mtok",
                ),
                additional_terms={
                    "cache_write_multiplier": "1.25",
                    "long_context_threshold_tokens": 272000,
                    "long_context_input_multiplier": "2",
                    "long_context_output_multiplier": "1.5",
                    "batch_or_flex_multiplier": "0.5",
                    "regional_processing_multiplier": "1.1",
                },
                notes=(
                    "Curated Primary 33.2.1A reference. OpenAI standard synchronous list "
                    "pricing checked 2026-09-03. The existing immutable registry's 5m/1h "
                    "cache-write fields are Anthropic-specific and are not applicable to "
                    "OpenAI; OpenAI cache-write and long-context modifiers are retained in "
                    "catalog metadata for the later execution/cost adapter."
                ),
            ),
        },
        {
            "display_name": "GPT-5.6 Terra",
            "model_id": "gpt-5.6-terra",
            "catalog_tier": "balanced",
            "status": "production",
            "capabilities": ["text_generation", "reasoning"],
            "enabled": True,
            "is_default": True,
            "recommended_use": "Default OpenAI model",
            "pricing_reference": _pricing_reference(
                provider_id="openai",
                input_per_mtok="2",
                output_per_mtok="12",
                cache_read_per_mtok="0.2",
                not_applicable_fields=(
                    "cache_write_5m_per_mtok",
                    "cache_write_1h_per_mtok",
                ),
                additional_terms={
                    "cache_write_multiplier": "1.25",
                    "long_context_threshold_tokens": 272000,
                    "long_context_input_multiplier": "2",
                    "long_context_output_multiplier": "1.5",
                    "batch_or_flex_multiplier": "0.5",
                    "regional_processing_multiplier": "1.1",
                },
                notes=(
                    "Curated Primary 33.2.1A reference. OpenAI standard synchronous list "
                    "pricing checked 2026-09-03. The supplied reference records the "
                    "2026-07-30 Terra price cut. OpenAI cache-write and long-context "
                    "modifiers remain catalog metadata until execution/cost integration."
                ),
            ),
        },
        {
            "display_name": "GPT-5.6 Luna",
            "model_id": "gpt-5.6-luna",
            "catalog_tier": "economy",
            "status": "production",
            "capabilities": ["text_generation", "reasoning"],
            "enabled": True,
            "is_default": False,
            "recommended_use": "High-volume, lower-cost operations",
            "pricing_reference": _pricing_reference(
                provider_id="openai",
                input_per_mtok="0.2",
                output_per_mtok="1.2",
                cache_read_per_mtok="0.02",
                not_applicable_fields=(
                    "cache_write_5m_per_mtok",
                    "cache_write_1h_per_mtok",
                ),
                additional_terms={
                    "cache_write_multiplier": "1.25",
                    "long_context_threshold_tokens": 272000,
                    "long_context_input_multiplier": "2",
                    "long_context_output_multiplier": "1.5",
                    "batch_or_flex_multiplier": "0.5",
                    "regional_processing_multiplier": "1.1",
                },
                notes=(
                    "Curated Primary 33.2.1A reference. OpenAI standard synchronous list "
                    "pricing checked 2026-09-03. The supplied reference records the "
                    "2026-07-30 Luna price cut. OpenAI cache-write and long-context "
                    "modifiers remain catalog metadata until execution/cost integration."
                ),
            ),
        },
    ),
}


def source_metadata() -> dict[str, Any]:
    return {
        "schema_version": MODEL_CATALOG_SCHEMA_VERSION,
        "source_artifact": SOURCE_ARTIFACT_NAME,
        "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
        "reference_date": SOURCE_REFERENCE_DATE,
        "pricing_checked_date": PRICING_CHECKED_DATE,
    }


def provider_source_metadata(provider_id: str) -> dict[str, str]:
    provider = str(provider_id or "").strip().lower()
    source = _PROVIDER_SOURCES.get(provider)
    if source is None:
        return {}
    return deepcopy(source)


def list_models(provider_id: str) -> list[dict[str, Any]]:
    provider = str(provider_id or "").strip().lower()
    return deepcopy(list(_MODELS.get(provider, ())))


def get_model(provider_id: str, model_id: str) -> dict[str, Any] | None:
    provider = str(provider_id or "").strip().lower()
    wanted = str(model_id or "").strip()
    for model in _MODELS.get(provider, ()):
        if model["model_id"] == wanted:
            result = deepcopy(model)
            result["provider_id"] = provider
            result.update(provider_source_metadata(provider))
            return result
    return None


def default_model(provider_id: str) -> dict[str, Any] | None:
    provider = str(provider_id or "").strip().lower()
    for model in _MODELS.get(provider, ()):
        if bool(model.get("is_default")) and bool(model.get("enabled")):
            result = deepcopy(model)
            result["provider_id"] = provider
            result.update(provider_source_metadata(provider))
            return result
    return None


def accepted_model_ids(provider_id: str) -> tuple[str, ...]:
    return tuple(
        model["model_id"]
        for model in _MODELS.get(str(provider_id or "").strip().lower(), ())
        if bool(model.get("enabled")) and model.get("status") == "production"
    )
