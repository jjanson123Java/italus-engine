from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.services import provider_credential_service
from app.services import provider_model_catalog_service


PROVIDER_CONFIG_SCHEMA_VERSION = "primary33.2.1a-provider-config-v3"
PROVIDER_CATALOG_SCHEMA_VERSION = "primary33.2.1a-provider-catalog-v2"
DEFAULT_SERVICE_TIER = "standard"
DEFAULT_INFERENCE_SCOPE = "global"

DIRECT_PROVIDER_IDS = ("anthropic", "openai")
EXPERIMENTAL_PROVIDER_IDS = ("openrouter",)

_PROVIDER_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "provider_id": "anthropic",
        "label": "Anthropic / Claude",
        "kind": "direct",
        "configuration_enabled": True,
        "execution_enabled": False,
        "pricing_source_url": (
            "https://platform.claude.com/docs/en/about-claude/pricing"
        ),
        "model_source_url": (
            "https://platform.claude.com/docs/en/models/overview"
            "#latest-models-comparison"
        ),
        "model_catalog_status": "curated_direct_catalog_loaded",
    },
    {
        "provider_id": "openai",
        "label": "OpenAI",
        "kind": "direct",
        "configuration_enabled": True,
        "execution_enabled": False,
        "pricing_source_url": (
            "https://openai.com/index/"
            "advancing-the-price-performance-frontier-with-gpt-5-6/"
        ),
        "model_source_url": "https://developers.openai.com/api/docs/models/all",
        "model_catalog_status": "curated_direct_catalog_loaded",
    },
    {
        "provider_id": "openrouter",
        "label": "OpenRouter",
        "kind": "aggregator",
        "configuration_enabled": False,
        "execution_enabled": False,
        "pricing_source_url": "https://openrouter.ai/models",
        "model_source_url": "https://openrouter.ai/models",
        "model_catalog_status": "experimental_disabled",
    },
)


class ProviderConfigError(ValueError):
    """Raised when provider configuration violates the accepted provider/model contract."""


def config_root() -> Path:
    override = str(os.environ.get("ITALUS_CONFIG_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".italus").resolve()


def provider_config_path() -> Path:
    return config_root() / "provider_config.json"


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, path)


def _catalog_entry(provider_id: str) -> dict[str, Any]:
    wanted = str(provider_id or "").strip().lower()
    for item in _PROVIDER_CATALOG:
        if item["provider_id"] == wanted:
            return dict(item)
    raise ProviderConfigError(f"Unsupported provider_id: {provider_id}")


def credential_state(provider_id: str) -> dict[str, Any]:
    try:
        _catalog_entry(provider_id)
    except ProviderConfigError:
        raise
    return provider_credential_service.credential_state(provider_id)


def provider_catalog() -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    for raw in _PROVIDER_CATALOG:
        item = dict(raw)
        provider_id = item["provider_id"]
        item["credential_status"] = credential_state(provider_id)["status"]
        item["models"] = (
            provider_model_catalog_service.list_models(provider_id)
            if item["kind"] == "direct"
            else []
        )
        providers.append(item)

    return {
        "status": "ok",
        "schema_version": PROVIDER_CATALOG_SCHEMA_VERSION,
        "provider_execution_allowed": False,
        "catalog_source_status": {
            "direct_provider_model_catalog_loaded": True,
            "openrouter_model_catalog_loaded": False,
            "openrouter_execution_enabled": False,
            "source": provider_model_catalog_service.source_metadata(),
            "reason": (
                "The curated Anthropic/OpenAI direct-provider catalog is loaded for "
                "configuration. Primary 33.2.1B project preflight can authenticate the "
                "configured account and confirm the exact bound model. Provider execution "
                "remains locked."
            ),
        },
        "providers": providers,
    }


def model_validation(provider_id: str, model_id: str) -> dict[str, Any]:
    entry = _catalog_entry(provider_id)
    cleaned_model = str(model_id or "").strip()
    if not cleaned_model:
        return {
            "status": "missing",
            "accepted": False,
            "model_id": "",
            "display_name": None,
            "catalog_tier": None,
        }

    if entry["kind"] != "direct":
        return {
            "status": "provider_disabled",
            "accepted": False,
            "model_id": cleaned_model,
            "display_name": None,
            "catalog_tier": None,
        }

    model = provider_model_catalog_service.get_model(
        entry["provider_id"],
        cleaned_model,
    )
    if model is None:
        return {
            "status": "legacy_unvalidated",
            "accepted": False,
            "model_id": cleaned_model,
            "display_name": None,
            "catalog_tier": None,
        }

    return {
        "status": "accepted",
        "accepted": True,
        "model_id": cleaned_model,
        "display_name": model["display_name"],
        "catalog_tier": model["catalog_tier"],
        "is_default": bool(model.get("is_default")),
    }


def require_accepted_model_id(provider_id: str, model_id: str) -> dict[str, Any]:
    entry = _catalog_entry(provider_id)
    cleaned_model = str(model_id or "").strip()
    if not cleaned_model:
        raise ProviderConfigError("model_id is required")

    if entry["kind"] != "direct":
        raise ProviderConfigError(
            f"Provider {entry['provider_id']} does not have an enabled direct-model catalog."
        )

    model = provider_model_catalog_service.get_model(
        entry["provider_id"],
        cleaned_model,
    )
    if model is None or not bool(model.get("enabled")) or model.get("status") != "production":
        accepted = ", ".join(
            provider_model_catalog_service.accepted_model_ids(entry["provider_id"])
        )
        raise ProviderConfigError(
            f"model_id is not accepted for {entry['provider_id']}: {cleaned_model}. "
            f"Select one of the curated direct-provider IDs: {accepted}"
        )
    return model


def _default_profile(provider_id: str | None = None) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "model_id": "",
        "service_tier": DEFAULT_SERVICE_TIER,
        "inference_scope": DEFAULT_INFERENCE_SCOPE,
        "updated_at": None,
    }


def _default_store() -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_CONFIG_SCHEMA_VERSION,
        "last_selected_provider_id": None,
        "profiles": {},
        "provider_execution_allowed": False,
        "updated_at": None,
    }


def _clean_profile(raw: Any, provider_id: str) -> dict[str, Any]:
    profile = _default_profile(provider_id)
    if isinstance(raw, dict):
        for key in ("model_id", "service_tier", "inference_scope", "updated_at"):
            if key in raw:
                profile[key] = raw[key]
    profile["provider_id"] = provider_id
    return profile


def _normalized_store(raw: Any) -> dict[str, Any]:
    store = _default_store()
    if not isinstance(raw, dict):
        return store

    # v2 native store
    if isinstance(raw.get("profiles"), dict):
        profiles: dict[str, dict[str, Any]] = {}
        for provider_id, profile_raw in raw["profiles"].items():
            try:
                entry = _catalog_entry(str(provider_id))
            except ProviderConfigError:
                continue
            profiles[entry["provider_id"]] = _clean_profile(
                profile_raw,
                entry["provider_id"],
            )
        store["profiles"] = profiles
        last_selected = str(raw.get("last_selected_provider_id") or "").strip().lower()
        if last_selected in profiles:
            store["last_selected_provider_id"] = last_selected
        store["updated_at"] = raw.get("updated_at")
        return store

    # Transparent migration view for the original flat v1 file.
    legacy_provider = str(raw.get("provider_id") or "").strip().lower()
    if legacy_provider:
        try:
            entry = _catalog_entry(legacy_provider)
        except ProviderConfigError:
            return store
        profile = _clean_profile(raw, entry["provider_id"])
        store["profiles"] = {entry["provider_id"]: profile}
        store["last_selected_provider_id"] = entry["provider_id"]
        store["updated_at"] = raw.get("updated_at")
    return store


def _load_store() -> dict[str, Any]:
    return _normalized_store(_read_json(provider_config_path(), {}))


def get_provider_profile(provider_id: str) -> dict[str, Any] | None:
    entry = _catalog_entry(provider_id)
    store = _load_store()
    raw = store["profiles"].get(entry["provider_id"])
    if not isinstance(raw, dict):
        return None
    profile = _clean_profile(raw, entry["provider_id"])
    if not str(profile.get("model_id") or "").strip():
        return None
    return {
        **profile,
        "model_validation": model_validation(
            entry["provider_id"],
            str(profile.get("model_id") or ""),
        ),
    }


def list_provider_profiles() -> list[dict[str, Any]]:
    store = _load_store()
    result: list[dict[str, Any]] = []
    for provider_id in sorted(store["profiles"]):
        profile = _clean_profile(store["profiles"][provider_id], provider_id)
        if not str(profile.get("model_id") or "").strip():
            continue
        result.append(
            {
                **profile,
                "model_validation": model_validation(
                    provider_id,
                    str(profile.get("model_id") or ""),
                ),
                "credential": credential_state(provider_id),
            }
        )
    return result


def get_provider_config(provider_id: str | None = None) -> dict[str, Any]:
    store = _load_store()
    selected = str(provider_id or "").strip().lower()
    if selected:
        entry = _catalog_entry(selected)
        selected = entry["provider_id"]
    else:
        selected = str(store.get("last_selected_provider_id") or "").strip().lower()

    config = _default_profile(selected or None)
    credential = None
    pricing_source_url = None

    if selected:
        entry = _catalog_entry(selected)
        stored_profile = store["profiles"].get(selected)
        if isinstance(stored_profile, dict):
            config = _clean_profile(stored_profile, selected)
        credential = credential_state(selected)
        pricing_source_url = entry["pricing_source_url"]

    return {
        "status": "ok",
        "schema_version": PROVIDER_CONFIG_SCHEMA_VERSION,
        "config": config,
        "configured_profiles": list_provider_profiles(),
        "credential": credential,
        "model_validation": (
            model_validation(selected, str(config.get("model_id") or ""))
            if selected
            else {
                "status": "missing",
                "accepted": False,
                "model_id": "",
                "display_name": None,
                "catalog_tier": None,
            }
        ),
        "pricing_source_url": pricing_source_url,
        "execution": {
            "provider_execution_allowed": False,
            "reason": "Primary 33.2.1B preflight is available for bound projects; real provider generation remains locked until the later execution gate.",
        },
    }


def save_provider_config(
    *,
    provider_id: str,
    model_id: str,
    service_tier: str = DEFAULT_SERVICE_TIER,
    inference_scope: str = DEFAULT_INFERENCE_SCOPE,
) -> dict[str, Any]:
    entry = _catalog_entry(provider_id)
    if not bool(entry["configuration_enabled"]):
        raise ProviderConfigError(
            f"Provider {entry['provider_id']} is disabled and cannot be activated in Primary 33.2.1A."
        )

    cleaned_model = str(model_id or "").strip()
    require_accepted_model_id(entry["provider_id"], cleaned_model)

    cleaned_tier = str(service_tier or "").strip().lower()
    if not cleaned_tier:
        raise ProviderConfigError("service_tier is required")

    cleaned_scope = str(inference_scope or "").strip().lower()
    if not cleaned_scope:
        raise ProviderConfigError("inference_scope is required")

    now = _utc_iso()
    profile = {
        "provider_id": entry["provider_id"],
        "model_id": cleaned_model,
        "service_tier": cleaned_tier,
        "inference_scope": cleaned_scope,
        "updated_at": now,
    }

    store = _load_store()
    store["schema_version"] = PROVIDER_CONFIG_SCHEMA_VERSION
    store["profiles"][entry["provider_id"]] = profile
    store["last_selected_provider_id"] = entry["provider_id"]
    store["provider_execution_allowed"] = False
    store["updated_at"] = now
    _write_json_atomic(provider_config_path(), store)

    return get_provider_config(entry["provider_id"])



def delete_provider_profile(provider_id: str) -> dict[str, Any]:
    """Delete one saved provider/model profile and its Italus-managed credential.

    Project-association safety is enforced by the API caller before this
    function is invoked. Project content, immutable pricing history, and usage
    history are intentionally preserved.

    If removal of an Italus-managed credential fails after the profile-store
    update, the exact prior provider-config store is restored before the error
    is returned. Environment-managed credentials are external to Italus and
    are never deleted here.
    """
    entry = _catalog_entry(provider_id)
    store = _load_store()
    provider = entry["provider_id"]

    if provider not in store["profiles"]:
        raise ProviderConfigError(f"No saved provider profile exists for {provider}.")

    credential_before = provider_credential_service.credential_state(provider)
    updated_store = {
        **store,
        "profiles": dict(store["profiles"]),
    }
    del updated_store["profiles"][provider]

    if str(updated_store.get("last_selected_provider_id") or "") == provider:
        remaining = sorted(updated_store["profiles"])
        updated_store["last_selected_provider_id"] = remaining[0] if remaining else None

    updated_store["updated_at"] = _utc_iso()
    updated_store["provider_execution_allowed"] = False
    _write_json_atomic(provider_config_path(), updated_store)

    credential_deleted = False
    deleted_credential_instance_id = None
    try:
        if bool(credential_before.get("managed_by_application")):
            credential_result = provider_credential_service.delete_stored_api_key(provider)
            credential_deleted = True
            deleted_credential_instance_id = credential_result.get(
                "deleted_credential_instance_id"
            )
    except provider_credential_service.ProviderCredentialError as exc:
        _write_json_atomic(provider_config_path(), store)
        raise ProviderConfigError(
            "Provider profile deletion was rolled back because Italus could not remove "
            "the stored API key. No profile deletion was kept."
        ) from exc

    external_credential_preserved = (
        str(credential_before.get("source") or "") == "environment"
    )

    return {
        "status": "ok",
        "deleted_provider_id": provider,
        "credential_deleted": credential_deleted,
        "deleted_credential_instance_id": deleted_credential_instance_id,
        "external_credential_preserved": external_credential_preserved,
        "credential": provider_credential_service.credential_state(provider),
        "config": get_provider_config(),
    }
