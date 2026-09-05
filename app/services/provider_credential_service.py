from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services import provider_credential_backends


CREDENTIAL_SCHEMA_VERSION = "primary33.2.0-provider-credential-v3"
CREDENTIAL_METADATA_SCHEMA_VERSION = "primary33.2.0-provider-credential-metadata-v2"
SUPPORTED_PROVIDER_IDS = ("anthropic", "openai", "openrouter")


class ProviderCredentialError(ValueError):
    """Raised when secure provider credential management cannot be completed."""


def _provider_id(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned not in SUPPORTED_PROVIDER_IDS:
        raise ProviderCredentialError(f"Unsupported provider_id: {value}")
    return cleaned


def _config_root() -> Path:
    override = str(os.environ.get("ITALUS_CONFIG_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".italus").resolve()


def credential_root() -> Path:
    return _config_root() / "credentials"


def _credential_metadata_path(provider_id: str) -> Path:
    return credential_root() / f"{_provider_id(provider_id)}.metadata.json"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _read_credential_metadata(provider_id: str) -> dict[str, Any] | None:
    path = _credential_metadata_path(provider_id)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("provider_id") or "").strip().lower() != _provider_id(provider_id):
        return None
    credential_instance_id = str(payload.get("credential_instance_id") or "").strip()
    return payload if credential_instance_id else None


def _active_store() -> provider_credential_backends.CredentialStore:
    return provider_credential_backends.active_credential_store()


def _store_error(exc: Exception) -> ProviderCredentialError:
    return ProviderCredentialError(str(exc) or "The secure credential backend is unavailable.")


def interactive_management_available() -> bool:
    """Return whether the selected trusted backend supports local credential management."""
    store = _active_store()
    return bool(store.available() and store.interactive_management_available)


def credential_state(provider_id: str) -> dict[str, Any]:
    provider = _provider_id(provider_id)
    store = _active_store()
    interactive = bool(store.available() and store.interactive_management_available)

    if not store.available():
        return {
            "provider_id": provider,
            "status": "unavailable",
            "source": None,
            "managed_by_application": False,
            "interactive_management_available": False,
            "credential_instance_id": None,
            "lineage_status": "unavailable",
        }

    try:
        secret = store.read(provider)
    except provider_credential_backends.CredentialBackendError:
        metadata = _read_credential_metadata(provider)
        return {
            "provider_id": provider,
            "status": "unreadable",
            "source": store.source,
            "managed_by_application": bool(store.managed_by_application),
            "interactive_management_available": interactive,
            "credential_instance_id": (
                str(metadata.get("credential_instance_id") or "")
                if metadata and store.managed_by_application
                else None
            ),
            "lineage_status": (
                "tracked"
                if metadata and store.managed_by_application
                else "external_identity_unavailable"
                if not store.managed_by_application
                else "legacy_metadata_missing"
            ),
        }

    if secret:
        if not store.managed_by_application:
            return {
                "provider_id": provider,
                "status": "configured",
                "source": store.source,
                "managed_by_application": False,
                "interactive_management_available": False,
                "credential_instance_id": None,
                "lineage_status": "external_identity_unavailable",
            }

        metadata = _read_credential_metadata(provider)
        return {
            "provider_id": provider,
            "status": "configured",
            "source": store.source,
            "managed_by_application": True,
            "interactive_management_available": interactive,
            "credential_instance_id": (
                str(metadata.get("credential_instance_id") or "")
                if metadata
                else None
            ),
            "lineage_status": "tracked" if metadata else "legacy_metadata_missing",
        }

    return {
        "provider_id": provider,
        "status": "missing",
        "source": store.source if not store.managed_by_application else None,
        "managed_by_application": False,
        "interactive_management_available": interactive,
        "credential_instance_id": None,
        "lineage_status": "missing",
    }


def credential_states() -> dict[str, Any]:
    return {
        "status": "ok",
        "schema_version": CREDENTIAL_SCHEMA_VERSION,
        "credentials": [
            credential_state(provider_id)
            for provider_id in SUPPORTED_PROVIDER_IDS
        ],
    }


def _restore_store_secret(
    store: provider_credential_backends.CredentialStore,
    provider_id: str,
    previous_secret: str | None,
) -> None:
    if previous_secret is None:
        store.delete(provider_id)
    else:
        store.write(provider_id, previous_secret)


def save_api_key(provider_id: str, api_key: str) -> dict[str, Any]:
    provider = _provider_id(provider_id)
    store = _active_store()

    if not store.available():
        raise ProviderCredentialError(
            "The trusted credential backend is unavailable. Italus will not fall back "
            "to plaintext or to another credential source."
        )
    if not store.managed_by_application or not store.interactive_management_available:
        raise ProviderCredentialError(
            "Interactive API-key storage is unavailable in this deployment. "
            "Configure the selected deployment credential source outside Italus."
        )

    secret = str(api_key or "").strip()
    if len(secret) < 8:
        raise ProviderCredentialError("API key is too short")
    encoded = secret.encode("utf-8")
    if len(encoded) > 2048:
        raise ProviderCredentialError("API key exceeds the supported secure-store size")

    try:
        previous_secret = store.read(provider)
    except provider_credential_backends.CredentialBackendError as exc:
        raise _store_error(exc) from exc

    metadata_path = _credential_metadata_path(provider)
    previous_metadata = metadata_path.read_bytes() if metadata_path.exists() else None

    now = _utc_iso()
    credential_instance_id = f"cred_{uuid.uuid4().hex}"
    metadata = {
        "schema_version": CREDENTIAL_METADATA_SCHEMA_VERSION,
        "provider_id": provider,
        "credential_instance_id": credential_instance_id,
        "source": store.source,
        "created_at": now,
        "updated_at": now,
    }

    try:
        store.write(provider, secret)
        _write_json_atomic(metadata_path, metadata)
    except (OSError, provider_credential_backends.CredentialBackendError) as exc:
        try:
            _restore_store_secret(store, provider, previous_secret)
            if previous_metadata is None:
                if metadata_path.exists():
                    metadata_path.unlink()
            else:
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = metadata_path.with_name(metadata_path.name + ".restore.tmp")
                temporary.write_bytes(previous_metadata)
                os.replace(temporary, metadata_path)
        except (OSError, provider_credential_backends.CredentialBackendError) as rollback_exc:
            raise ProviderCredentialError(
                "Credential save failed and the previous secure-store state could not be restored."
            ) from rollback_exc
        raise ProviderCredentialError(
            "Credential save failed; the previous secure-store state was restored."
        ) from exc

    return {
        "status": "ok",
        "credential": credential_state(provider),
    }


def delete_stored_api_key(provider_id: str) -> dict[str, Any]:
    provider = _provider_id(provider_id)
    store = _active_store()

    if not store.available():
        raise ProviderCredentialError(
            "The trusted credential backend is unavailable. Italus will not fall back "
            "to another credential source."
        )
    if not store.managed_by_application:
        raise ProviderCredentialError(
            "This provider credential is managed outside Italus and cannot be removed by Italus."
        )

    previous_state = credential_state(provider)
    try:
        previous_secret = store.read(provider)
    except provider_credential_backends.CredentialBackendError as exc:
        raise _store_error(exc) from exc

    metadata_path = _credential_metadata_path(provider)
    previous_metadata = metadata_path.read_bytes() if metadata_path.exists() else None

    try:
        store.delete(provider)
        if metadata_path.exists():
            metadata_path.unlink()
    except (OSError, provider_credential_backends.CredentialBackendError) as exc:
        try:
            _restore_store_secret(store, provider, previous_secret)
            if previous_metadata is not None:
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = metadata_path.with_name(metadata_path.name + ".restore.tmp")
                temporary.write_bytes(previous_metadata)
                os.replace(temporary, metadata_path)
        except (OSError, provider_credential_backends.CredentialBackendError) as rollback_exc:
            raise ProviderCredentialError(
                "Credential removal failed and the previous secure-store state could not be restored."
            ) from rollback_exc
        raise ProviderCredentialError(
            "Credential removal failed; the previous secure-store state was restored."
        ) from exc

    return {
        "status": "ok",
        "deleted_credential_instance_id": previous_state.get("credential_instance_id"),
        "credential": credential_state(provider),
    }


def resolve_api_key(provider_id: str) -> str | None:
    """Resolve a provider secret for backend-only provider adapters.

    The selected deployment backend is authoritative. No cross-backend fallback is
    attempted, and no API route returns this value to the browser.
    """
    provider = _provider_id(provider_id)
    store = _active_store()
    if not store.available():
        raise ProviderCredentialError(
            "The trusted credential backend is unavailable. Provider credential "
            "resolution is fail-closed."
        )
    try:
        secret = store.read(provider)
    except provider_credential_backends.CredentialBackendError as exc:
        raise _store_error(exc) from exc
    return str(secret or "").strip() or None
