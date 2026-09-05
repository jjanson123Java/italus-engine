from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse

from app.services import provider_config_service, provider_model_catalog_service


PRICING_SCHEMA_VERSION = "primary33.1-provider-pricing-v1"
PRICING_HISTORY_SCHEMA_VERSION = "primary33.1-provider-pricing-history-v1"
PRICING_POLICY_SCHEMA_VERSION = "primary33.1-provider-pricing-policy-v1"
PRICING_LIFECYCLE_SCHEMA_VERSION = "primary33.2.1a3-pricing-lifecycle-v1"
PRICING_FRESHNESS_THRESHOLD_DAYS_DEFAULT = 30
PRICING_FRESHNESS_THRESHOLD_DAYS_MIN = 1
PRICING_FRESHNESS_THRESHOLD_DAYS_MAX = 3650

_LOCK = RLock()
_RATE_FIELDS = (
    "input_per_mtok",
    "output_per_mtok",
    "cache_write_5m_per_mtok",
    "cache_write_1h_per_mtok",
    "cache_read_per_mtok",
)


class ProviderPricingError(ValueError):
    """Raised when pricing data violates the immutable Primary 33.1 contract."""


def _utc_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def pricing_root() -> Path:
    return provider_config_service.config_root() / "provider_pricing"


def versions_dir() -> Path:
    return pricing_root() / "versions"


def history_path() -> Path:
    return pricing_root() / "history.jsonl"


def active_index_path() -> Path:
    return pricing_root() / "active_index.json"


def pricing_policy_path() -> Path:
    return pricing_root() / "policy.json"


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


def _freshness_threshold_days(value: Any) -> int:
    if isinstance(value, bool):
        raise ProviderPricingError("freshness_threshold_days must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ProviderPricingError("freshness_threshold_days must be an integer") from exc
    if not (
        PRICING_FRESHNESS_THRESHOLD_DAYS_MIN
        <= parsed
        <= PRICING_FRESHNESS_THRESHOLD_DAYS_MAX
    ):
        raise ProviderPricingError(
            "freshness_threshold_days must be between "
            f"{PRICING_FRESHNESS_THRESHOLD_DAYS_MIN} and "
            f"{PRICING_FRESHNESS_THRESHOLD_DAYS_MAX}"
        )
    return parsed


def get_pricing_policy() -> dict[str, Any]:
    path = pricing_policy_path()
    raw = _read_json(path, {})
    configured = isinstance(raw, dict) and "freshness_threshold_days" in raw
    try:
        threshold = _freshness_threshold_days(
            raw.get("freshness_threshold_days")
            if isinstance(raw, dict) and configured
            else PRICING_FRESHNESS_THRESHOLD_DAYS_DEFAULT
        )
    except ProviderPricingError:
        threshold = PRICING_FRESHNESS_THRESHOLD_DAYS_DEFAULT
        configured = False

    return {
        "status": "ok",
        "policy": {
            "schema_version": PRICING_POLICY_SCHEMA_VERSION,
            "freshness_threshold_days": threshold,
            "configured": configured,
            "updated_at": raw.get("updated_at") if isinstance(raw, dict) else None,
        },
    }


def save_pricing_policy(*, freshness_threshold_days: Any) -> dict[str, Any]:
    threshold = _freshness_threshold_days(freshness_threshold_days)
    payload = {
        "schema_version": PRICING_POLICY_SCHEMA_VERSION,
        "freshness_threshold_days": threshold,
        "updated_at": _utc_iso(),
    }
    with _LOCK:
        _write_json_atomic(pricing_policy_path(), payload)
    return get_pricing_policy()


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded + "\n")


def _clean_text(value: Any, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ProviderPricingError(f"{field_name} is required")
    return cleaned


def _rate_string(value: Any, field_name: str) -> str:
    raw = str(value if value is not None else "").strip()
    if not raw:
        raw = "0"
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ProviderPricingError(f"{field_name} must be a decimal number") from exc
    if not amount.is_finite():
        raise ProviderPricingError(f"{field_name} must be finite")
    if amount < 0:
        raise ProviderPricingError(f"{field_name} cannot be negative")
    normalized = format(amount.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized




def _validate_iso_timestamp(value: Any, field_name: str) -> str:
    cleaned = _clean_text(value, field_name)
    candidate = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ProviderPricingError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ProviderPricingError(f"{field_name} must include a timezone")
    return cleaned


def _parse_iso_utc(value: Any, field_name: str = "timestamp") -> datetime:
    cleaned = _clean_text(value, field_name)
    candidate = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ProviderPricingError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ProviderPricingError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _as_of_utc(as_of: Any | None = None) -> datetime:
    if as_of is None:
        return datetime.now(timezone.utc)
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            raise ProviderPricingError("as_of must include a timezone")
        return as_of.astimezone(timezone.utc)
    return _parse_iso_utc(as_of, "as_of")


def _validate_source_url(source_url: str) -> str:
    cleaned = _clean_text(source_url, "source_url")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderPricingError("source_url must be an http(s) URL")
    return cleaned


def _pricing_key(provider_id: str, model_id: str, service_tier: str, inference_scope: str) -> str:
    return "|".join(
        part.strip().lower()
        for part in (provider_id, model_id, service_tier, inference_scope)
    )


def _version_id(canonical_payload: dict[str, Any], created_at: str) -> str:
    material = json.dumps(
        {"created_at": created_at, "pricing": canonical_payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "pricing_" + hashlib.sha256(material).hexdigest()[:20]


def _version_records_for_key(
    *,
    provider_id: str,
    model_id: str,
    service_tier: str,
    inference_scope: str,
) -> list[dict[str, Any]]:
    provider = str(provider_id or "").strip().lower()
    model = str(model_id or "").strip()
    tier = str(service_tier or "").strip().lower()
    scope = str(inference_scope or "").strip().lower()
    records: list[dict[str, Any]] = []
    root = versions_dir()
    if not root.exists():
        return records
    for path in root.glob("pricing_*.json"):
        data = _read_json(path, None)
        if not isinstance(data, dict):
            continue
        if str(data.get("provider_id") or "").strip().lower() != provider:
            continue
        if str(data.get("model_id") or "").strip() != model:
            continue
        if str(data.get("service_tier") or "").strip().lower() != tier:
            continue
        if str(data.get("inference_scope") or "").strip().lower() != scope:
            continue
        try:
            _parse_iso_utc(data.get("effective_from"), "effective_from")
        except ProviderPricingError:
            continue
        records.append(data)
    return records


def _version_order(record: dict[str, Any]) -> tuple[datetime, datetime, str]:
    effective = _parse_iso_utc(record.get("effective_from"), "effective_from")
    created_raw = str(record.get("created_at") or record.get("effective_from") or "")
    try:
        created = _parse_iso_utc(created_raw, "created_at")
    except ProviderPricingError:
        created = effective
    return effective, created, str(record.get("pricing_version_id") or "")


def _resolve_pricing_lifecycle(
    *,
    provider_id: str,
    model_id: str,
    service_tier: str,
    inference_scope: str,
    as_of: Any | None = None,
) -> dict[str, Any]:
    moment = _as_of_utc(as_of)
    records = _version_records_for_key(
        provider_id=provider_id,
        model_id=model_id,
        service_tier=service_tier,
        inference_scope=inference_scope,
    )
    applicable = [
        record
        for record in records
        if _parse_iso_utc(record.get("effective_from"), "effective_from") <= moment
    ]
    future = [
        record
        for record in records
        if _parse_iso_utc(record.get("effective_from"), "effective_from") > moment
    ]
    applicable.sort(key=_version_order)
    future.sort(key=_version_order)

    current = applicable[-1] if applicable else None
    current_id = str((current or {}).get("pricing_version_id") or "")
    retired = [
        record
        for record in reversed(applicable)
        if str(record.get("pricing_version_id") or "") != current_id
    ]

    versions: list[dict[str, Any]] = []
    for record in sorted(records, key=_version_order, reverse=True):
        version_id = str(record.get("pricing_version_id") or "")
        if version_id == current_id:
            lifecycle_status = "CURRENT"
        elif _parse_iso_utc(record.get("effective_from"), "effective_from") > moment:
            lifecycle_status = "SCHEDULED"
        else:
            lifecycle_status = "RETIRED"
        versions.append({**record, "lifecycle_status": lifecycle_status})

    return {
        "schema_version": PRICING_LIFECYCLE_SCHEMA_VERSION,
        "as_of": moment.isoformat().replace("+00:00", "Z"),
        "current": current,
        "scheduled": future,
        "next_scheduled": future[0] if future else None,
        "retired": retired,
        "versions": versions,
    }


def _sync_active_index_for_key(
    *,
    provider_id: str,
    model_id: str,
    service_tier: str,
    inference_scope: str,
) -> None:
    """Keep the legacy active index aligned with the effective-dated resolver."""
    key = _pricing_key(provider_id, model_id, service_tier, inference_scope)
    lifecycle = _resolve_pricing_lifecycle(
        provider_id=provider_id,
        model_id=model_id,
        service_tier=service_tier,
        inference_scope=inference_scope,
    )
    current = lifecycle.get("current")
    active = _read_json(active_index_path(), {})
    if not isinstance(active, dict):
        active = {}
    if isinstance(current, dict) and current.get("pricing_version_id"):
        active[key] = current["pricing_version_id"]
    else:
        active.pop(key, None)
    _write_json_atomic(active_index_path(), active)


def _validate_catalog_model(provider_id: str, model_id: str) -> None:
    model = provider_model_catalog_service.get_model(provider_id, model_id)
    if not model or not bool(model.get("enabled")) or str(model.get("status") or "") != "production":
        raise ProviderPricingError(
            f"Pricing can only be saved for an accepted direct-provider model_id: {model_id}"
        )


def save_pricing_version(
    *,
    provider_id: str,
    model_id: str,
    service_tier: str,
    inference_scope: str,
    currency: str,
    input_per_mtok: Any,
    output_per_mtok: Any,
    cache_write_5m_per_mtok: Any = "0",
    cache_write_1h_per_mtok: Any = "0",
    cache_read_per_mtok: Any = "0",
    effective_from: str,
    verified_at: str,
    source_url: str,
    notes: str = "",
) -> dict[str, Any]:
    catalog = provider_config_service.provider_catalog()
    enabled_ids = {
        item["provider_id"]
        for item in catalog["providers"]
        if bool(item["configuration_enabled"])
    }

    provider = _clean_text(provider_id, "provider_id").lower()
    if provider not in enabled_ids:
        raise ProviderPricingError(
            f"Pricing activation is disabled for provider_id: {provider}"
        )

    cleaned_model_id = _clean_text(model_id, "model_id")
    _validate_catalog_model(provider, cleaned_model_id)

    payload: dict[str, Any] = {
        "schema_version": PRICING_SCHEMA_VERSION,
        "provider_id": provider,
        "model_id": cleaned_model_id,
        "service_tier": _clean_text(service_tier, "service_tier").lower(),
        "inference_scope": _clean_text(inference_scope, "inference_scope").lower(),
        "currency": _clean_text(currency, "currency").upper(),
        "rates_per_mtok": {
            "input_per_mtok": _rate_string(input_per_mtok, "input_per_mtok"),
            "output_per_mtok": _rate_string(output_per_mtok, "output_per_mtok"),
            "cache_write_5m_per_mtok": _rate_string(
                cache_write_5m_per_mtok, "cache_write_5m_per_mtok"
            ),
            "cache_write_1h_per_mtok": _rate_string(
                cache_write_1h_per_mtok, "cache_write_1h_per_mtok"
            ),
            "cache_read_per_mtok": _rate_string(
                cache_read_per_mtok, "cache_read_per_mtok"
            ),
        },
        "effective_from": _validate_iso_timestamp(effective_from, "effective_from"),
        "verified_at": _validate_iso_timestamp(verified_at, "verified_at"),
        "source_url": _validate_source_url(source_url),
        "notes": str(notes or "").strip(),
    }

    created_at = _utc_iso()
    version_id = _version_id(payload, created_at)
    record = {
        **payload,
        "pricing_version_id": version_id,
        "created_at": created_at,
        "immutable": True,
    }

    version_path = versions_dir() / f"{version_id}.json"
    key = _pricing_key(
        record["provider_id"],
        record["model_id"],
        record["service_tier"],
        record["inference_scope"],
    )

    with _LOCK:
        if version_path.exists():
            raise ProviderPricingError(
                f"Pricing version collision; refusing to overwrite {version_id}"
            )

        _write_json_atomic(version_path, record)

        history_record = {
            "schema_version": PRICING_HISTORY_SCHEMA_VERSION,
            "pricing_version_id": version_id,
            "provider_id": record["provider_id"],
            "model_id": record["model_id"],
            "service_tier": record["service_tier"],
            "inference_scope": record["inference_scope"],
            "effective_from": record["effective_from"],
            "verified_at": record["verified_at"],
            "source_url": record["source_url"],
            "created_at": created_at,
        }
        _append_jsonl(history_path(), history_record)

        _sync_active_index_for_key(
            provider_id=record["provider_id"],
            model_id=record["model_id"],
            service_tier=record["service_tier"],
            inference_scope=record["inference_scope"],
        )

    lifecycle = _resolve_pricing_lifecycle(
        provider_id=record["provider_id"],
        model_id=record["model_id"],
        service_tier=record["service_tier"],
        inference_scope=record["inference_scope"],
    )
    saved_status = next(
        (
            item.get("lifecycle_status")
            for item in lifecycle["versions"]
            if item.get("pricing_version_id") == version_id
        ),
        "RETIRED",
    )
    return {
        "status": "ok",
        "pricing": record,
        "lifecycle_status": saved_status,
        "current_pricing": lifecycle["current"],
        "next_scheduled_pricing": lifecycle["next_scheduled"],
    }


def _load_version(version_id: str) -> dict[str, Any] | None:
    cleaned = str(version_id or "").strip()
    if not cleaned.startswith("pricing_") or "/" in cleaned or "\\" in cleaned:
        return None
    path = versions_dir() / f"{cleaned}.json"
    data = _read_json(path, None)
    return data if isinstance(data, dict) else None


def get_pricing_version_snapshot(pricing_version_id: str) -> dict[str, Any]:
    """Return one immutable pricing version plus a semantic SHA-256 digest."""
    pricing = _load_version(pricing_version_id)
    if pricing is None:
        raise ProviderPricingError(
            f"Unknown pricing_version_id: {pricing_version_id}"
        )
    canonical = json.dumps(
        pricing,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "status": "ok",
        "pricing": pricing,
        "pricing_version_sha256": hashlib.sha256(canonical).hexdigest(),
    }



def pricing_freshness_status(
    pricing: dict[str, Any] | None,
    *,
    threshold_days: int | None = None,
) -> dict[str, Any]:
    threshold = _freshness_threshold_days(
        threshold_days
        if threshold_days is not None
        else get_pricing_policy()["policy"]["freshness_threshold_days"]
    )

    if not isinstance(pricing, dict):
        return {
            "status": "MODEL_PRICE_MISSING",
            "age_days": None,
            "threshold_days": threshold,
            "warning": True,
            "message": "No active pricing version is configured for this provider/model/tier.",
        }

    if not str(pricing.get("source_url") or "").strip():
        return {
            "status": "SOURCE_MISSING",
            "age_days": None,
            "threshold_days": threshold,
            "warning": True,
            "message": "The active pricing version does not have an official source URL.",
        }

    raw_verified = str(pricing.get("verified_at") or "").strip()
    candidate = raw_verified[:-1] + "+00:00" if raw_verified.endswith("Z") else raw_verified
    try:
        verified = datetime.fromisoformat(candidate)
    except ValueError:
        verified = None

    if verified is None or verified.tzinfo is None:
        return {
            "status": "REVIEW_RECOMMENDED",
            "age_days": None,
            "threshold_days": threshold,
            "warning": True,
            "message": "Pricing verification date is unavailable or invalid; review the official pricing source.",
        }

    age_seconds = max(
        (datetime.now(timezone.utc) - verified.astimezone(timezone.utc)).total_seconds(),
        0,
    )
    age_days = int(age_seconds // 86400)
    if age_days > threshold:
        return {
            "status": "REVIEW_RECOMMENDED",
            "age_days": age_days,
            "threshold_days": threshold,
            "warning": True,
            "message": (
                f"Pricing was verified {age_days} days ago, beyond the "
                f"{threshold}-day review threshold."
            ),
        }

    return {
        "status": "CURRENT",
        "age_days": age_days,
        "threshold_days": threshold,
        "warning": False,
        "message": f"Pricing was verified {age_days} days ago.",
    }


def get_effective_pricing(
    *,
    provider_id: str,
    model_id: str,
    service_tier: str,
    inference_scope: str,
    as_of: Any | None = None,
) -> dict[str, Any]:
    lifecycle = _resolve_pricing_lifecycle(
        provider_id=provider_id,
        model_id=model_id,
        service_tier=service_tier,
        inference_scope=inference_scope,
        as_of=as_of,
    )
    pricing = lifecycle["current"]
    policy = get_pricing_policy()["policy"]
    freshness = pricing_freshness_status(
        pricing,
        threshold_days=int(policy["freshness_threshold_days"]),
    )
    return {
        "status": "ok",
        "pricing": pricing,
        "next_scheduled_pricing": lifecycle["next_scheduled"],
        "policy": policy,
        "freshness": freshness,
        "as_of": lifecycle["as_of"],
    }


def get_current_pricing(
    *,
    provider_id: str,
    model_id: str,
    service_tier: str,
    inference_scope: str,
) -> dict[str, Any]:
    return get_effective_pricing(
        provider_id=provider_id,
        model_id=model_id,
        service_tier=service_tier,
        inference_scope=inference_scope,
    )


def get_pricing_registry(
    *,
    provider_id: str,
    service_tier: str = "standard",
    inference_scope: str = "global",
    as_of: Any | None = None,
) -> dict[str, Any]:
    provider = _clean_text(provider_id, "provider_id").lower()
    tier = _clean_text(service_tier, "service_tier").lower()
    scope = _clean_text(inference_scope, "inference_scope").lower()
    models = provider_model_catalog_service.list_models(provider)
    accepted_models = [
        model
        for model in models
        if bool(model.get("enabled")) and str(model.get("status") or "") == "production"
    ]
    if not accepted_models:
        raise ProviderPricingError(
            f"Pricing registry is unavailable for provider_id: {provider}"
        )

    moment = _as_of_utc(as_of)
    rows: list[dict[str, Any]] = []
    policy = get_pricing_policy()["policy"]
    for model in accepted_models:
        model_id = str(model.get("model_id") or "")
        lifecycle = _resolve_pricing_lifecycle(
            provider_id=provider,
            model_id=model_id,
            service_tier=tier,
            inference_scope=scope,
            as_of=moment,
        )
        current = lifecycle["current"]
        next_scheduled = lifecycle["next_scheduled"]
        if current:
            registry_status = "CURRENT"
        elif next_scheduled:
            registry_status = "SCHEDULED_ONLY"
        else:
            registry_status = "MISSING"
        rows.append(
            {
                "provider_id": provider,
                "model_id": model_id,
                "display_name": model.get("display_name") or model_id,
                "catalog_tier": model.get("catalog_tier"),
                "service_tier": tier,
                "inference_scope": scope,
                "registry_status": registry_status,
                "current_pricing": current,
                "current_freshness": pricing_freshness_status(
                    current,
                    threshold_days=int(policy["freshness_threshold_days"]),
                ),
                "next_scheduled_pricing": next_scheduled,
                "scheduled_versions": lifecycle["scheduled"],
                "retired_versions": lifecycle["retired"],
                "versions": lifecycle["versions"],
            }
        )

    return {
        "status": "ok",
        "schema_version": PRICING_LIFECYCLE_SCHEMA_VERSION,
        "provider_id": provider,
        "service_tier": tier,
        "inference_scope": scope,
        "as_of": moment.isoformat().replace("+00:00", "Z"),
        "policy": policy,
        "models": rows,
    }


def list_pricing_history(
    *,
    provider_id: str | None = None,
    model_id: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    safe_limit = min(max(int(limit), 1), 500)
    records: list[dict[str, Any]] = []
    path = history_path()
    if path.exists():
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(item, dict):
                    continue
                if provider_id and item.get("provider_id") != str(provider_id).strip().lower():
                    continue
                if model_id and item.get("model_id") != str(model_id).strip():
                    continue
                records.append(item)
    records = records[-safe_limit:]
    records.reverse()
    return {
        "status": "ok",
        "history": records,
    }
