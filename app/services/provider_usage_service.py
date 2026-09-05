from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import RLock
from typing import Any

from app.projects import project_loader
from app.services import provider_pricing_service


USAGE_EVENT_SCHEMA_VERSION = "primary33.1-provider-usage-event-v2"
USAGE_SUMMARY_SCHEMA_VERSION = "primary33.1-provider-usage-summary-v2"

_LOCK = RLock()
_LEGACY_UNATTRIBUTED = "legacy_unattributed"


class ProviderUsageError(ValueError):
    """Raised when provider usage data violates the append-only ledger contract."""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _project_usage_root(project_id: str) -> Path:
    project_loader.load_manifest(project_id)
    return project_loader.project_dir(project_id) / "usage"


def usage_events_path(project_id: str) -> Path:
    return _project_usage_root(project_id) / "provider_usage_events.jsonl"


def usage_summary_path(project_id: str) -> Path:
    return _project_usage_root(project_id) / "usage_summary.json"


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, path)


def _empty_summary(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": USAGE_SUMMARY_SCHEMA_VERSION,
        "project_id": project_id,
        "event_count": 0,
        "actual_input_tokens": 0,
        "actual_output_tokens": 0,
        "cache_write_tokens": 0,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
        "cache_read_tokens": 0,
        "actual_cost": "0",
        "currency": None,
        "cumulative_cost_available": False,
        "has_mixed_currency": False,
        "totals_by_currency": {},
        "by_provider_model": {},
        "by_pricing_version": {},
        "by_credential_instance": {},
        "by_binding_instance": {},
        "billing_segments": [],
        "rebuilt_from_ledger": True,
        "historical_costs_recalculated": False,
    }


def _int_field(event: dict[str, Any], key: str) -> int:
    value = event.get(key, 0)
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ProviderUsageError(f"{key} must be an integer") from exc
    if parsed < 0:
        raise ProviderUsageError(f"{key} cannot be negative")
    return parsed


def _decimal_field(event: dict[str, Any], key: str) -> Decimal:
    raw = str(event.get(key, "0") or "0").strip()
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ProviderUsageError(f"{key} must be a decimal number") from exc
    if not value.is_finite():
        raise ProviderUsageError(f"{key} must be finite")
    if value < 0:
        raise ProviderUsageError(f"{key} cannot be negative")
    return value


def _cost_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")



def _rate_decimal(pricing: dict[str, Any], field: str) -> Decimal:
    rates = pricing.get("rates_per_mtok")
    rates = rates if isinstance(rates, dict) else {}
    try:
        value = Decimal(str(rates.get(field, "0") or "0"))
    except InvalidOperation as exc:
        raise ProviderUsageError(
            f"Pricing snapshot rate {field} is not a decimal number"
        ) from exc
    if not value.is_finite() or value < 0:
        raise ProviderUsageError(
            f"Pricing snapshot rate {field} must be a nonnegative finite decimal"
        )
    return value


def _calculate_usage_cost(
    pricing: dict[str, Any],
    *,
    input_tokens: int,
    output_tokens: int,
    cache_write_5m_tokens: int,
    cache_write_1h_tokens: int,
    cache_read_tokens: int,
) -> Decimal:
    million = Decimal("1000000")
    return (
        Decimal(input_tokens) * _rate_decimal(pricing, "input_per_mtok")
        + Decimal(output_tokens) * _rate_decimal(pricing, "output_per_mtok")
        + Decimal(cache_write_5m_tokens)
        * _rate_decimal(pricing, "cache_write_5m_per_mtok")
        + Decimal(cache_write_1h_tokens)
        * _rate_decimal(pricing, "cache_write_1h_per_mtok")
        + Decimal(cache_read_tokens)
        * _rate_decimal(pricing, "cache_read_per_mtok")
    ) / million


def _read_all_events(project_id: str) -> list[dict[str, Any]]:
    path = usage_events_path(project_id)
    events: list[dict[str, Any]] = []
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
                if isinstance(item, dict):
                    events.append(item)
    return events


def get_usage_ledger_event_count(project_id: str) -> int:
    """Return fail-closed usage evidence from the append-only project ledger.

    The summary file is rebuildable and can be absent or stale after an
    interrupted write. Binding protection must therefore treat every non-empty
    ledger record as evidence that provider usage has begun, even if a record
    is malformed and cannot yet be rebuilt into the summary.
    """

    path = usage_events_path(project_id)
    if not path.exists():
        return 0

    with _LOCK:
        with path.open("r", encoding="utf-8-sig") as handle:
            return sum(1 for line in handle if line.strip())


def list_usage_events(project_id: str, *, limit: int = 100) -> dict[str, Any]:
    safe_limit = min(max(int(limit), 1), 500)
    events = _read_all_events(project_id)
    return {
        "status": "ok",
        "project_id": project_id,
        "events": events[-safe_limit:],
    }


def get_usage_summary(project_id: str) -> dict[str, Any]:
    """Return the derived usage summary, rebuilding it from the ledger when safe.

    The append-only provider usage ledger is authoritative. The summary is a
    rebuildable projection and may be missing or stale after an interrupted
    write. Reads therefore reconcile the summary against valid ledger records
    instead of treating a missing/stale summary as zero usage.

    If the non-empty ledger record count differs from the number of parseable
    mapping records, the ledger itself is inconsistent. In that state this
    read path fails closed rather than returning a partial or misleading
    summary. Likewise, a summary that claims more events than the authoritative
    ledger is rejected instead of silently reducing historical usage.
    """

    path = usage_summary_path(project_id)

    with _LOCK:
        raw_ledger_count = get_usage_ledger_event_count(project_id)
        parsed_ledger_count = len(_read_all_events(project_id))

        if raw_ledger_count != parsed_ledger_count:
            raise ProviderUsageError(
                "Provider usage ledger integrity check failed: one or more "
                "non-empty ledger records are not valid usage-event mappings. "
                "Refusing to return a partial usage summary."
            )

        if not path.exists():
            if parsed_ledger_count > 0:
                return rebuild_usage_summary(project_id)
            return {
                "status": "ok",
                "summary": _empty_summary(project_id),
            }

        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return rebuild_usage_summary(project_id)

        if not isinstance(payload, dict):
            return rebuild_usage_summary(project_id)

        if payload.get("schema_version") != USAGE_SUMMARY_SCHEMA_VERSION:
            return rebuild_usage_summary(project_id)

        try:
            summary_event_count = int(payload.get("event_count", 0) or 0)
        except (TypeError, ValueError):
            return rebuild_usage_summary(project_id)

        if summary_event_count < parsed_ledger_count:
            return rebuild_usage_summary(project_id)

        if summary_event_count > parsed_ledger_count:
            raise ProviderUsageError(
                "Provider usage summary reports more events than the "
                "authoritative append-only ledger. Refusing to discard "
                "historical usage implicitly."
            )

        return {
            "status": "ok",
            "summary": payload,
        }


def _new_bucket(**identity: Any) -> dict[str, Any]:
    return {
        **identity,
        "event_count": 0,
        "actual_input_tokens": 0,
        "actual_output_tokens": 0,
        "cache_write_tokens": 0,
        "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0,
        "cache_read_tokens": 0,
        "actual_cost": "0",
        "currency": None,
        "cumulative_cost_available": False,
        "has_mixed_currency": False,
        "totals_by_currency": {},
    }


def _add_currency_cost(
    container: dict[str, Any],
    currency: str | None,
    cost: Decimal,
) -> None:
    code = str(currency or "").strip().upper() or "UNSPECIFIED"
    totals = container.setdefault("totals_by_currency", {})
    bucket = totals.setdefault(
        code,
        {
            "currency": code,
            "event_count": 0,
            "actual_cost": "0",
        },
    )
    bucket["event_count"] += 1
    bucket_cost = Decimal(str(bucket["actual_cost"])) + cost
    bucket["actual_cost"] = _cost_string(bucket_cost)



def _accumulate_usage(
    bucket: dict[str, Any],
    *,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int,
    cache_write_5m_tokens: int,
    cache_write_1h_tokens: int,
    cache_read_tokens: int,
    currency: str | None,
    cost: Decimal,
) -> None:
    bucket["event_count"] += 1
    bucket["actual_input_tokens"] += input_tokens
    bucket["actual_output_tokens"] += output_tokens
    bucket["cache_write_tokens"] += cache_write_tokens
    bucket["cache_write_5m_tokens"] += cache_write_5m_tokens
    bucket["cache_write_1h_tokens"] += cache_write_1h_tokens
    bucket["cache_read_tokens"] += cache_read_tokens
    _add_currency_cost(bucket, currency, cost)


def _finalize_cost_view(bucket: dict[str, Any]) -> None:
    totals = bucket.get("totals_by_currency")
    totals = totals if isinstance(totals, dict) else {}
    currencies = sorted(totals)

    if len(currencies) == 1:
        currency = currencies[0]
        bucket["currency"] = currency
        bucket["actual_cost"] = str(totals[currency]["actual_cost"])
        bucket["cumulative_cost_available"] = currency != "UNSPECIFIED"
        bucket["has_mixed_currency"] = False
        return

    if len(currencies) > 1:
        bucket["currency"] = "MIXED"
        bucket["actual_cost"] = None
        bucket["cumulative_cost_available"] = False
        bucket["has_mixed_currency"] = True
        return

    bucket["currency"] = None
    bucket["actual_cost"] = "0"
    bucket["cumulative_cost_available"] = False
    bucket["has_mixed_currency"] = False


def _event_identity(event: dict[str, Any], key: str) -> str:
    value = str(event.get(key) or "").strip()
    return value or _LEGACY_UNATTRIBUTED


def _snapshot_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = event.get("pricing_snapshot")
    return snapshot if isinstance(snapshot, dict) else None


def rebuild_usage_summary(project_id: str) -> dict[str, Any]:
    events = _read_all_events(project_id)
    summary = _empty_summary(project_id)
    segment_buckets: dict[str, dict[str, Any]] = {}

    for event in events:
        provider = str(event.get("provider_id") or "").strip()
        model = str(event.get("model_id") or "").strip()
        if not provider or not model:
            continue

        input_tokens = _int_field(event, "actual_input_tokens")
        output_tokens = _int_field(event, "actual_output_tokens")
        if (
            "cache_write_5m_tokens" in event
            or "cache_write_1h_tokens" in event
        ):
            cache_write_5m_tokens = _int_field(event, "cache_write_5m_tokens")
            cache_write_1h_tokens = _int_field(event, "cache_write_1h_tokens")
            cache_write_tokens = (
                cache_write_5m_tokens + cache_write_1h_tokens
            )
        else:
            cache_write_5m_tokens = 0
            cache_write_1h_tokens = 0
            cache_write_tokens = _int_field(event, "cache_write_tokens")
        cache_read_tokens = _int_field(event, "cache_read_tokens")
        cost = _decimal_field(event, "actual_cost")
        event_currency = str(event.get("currency") or "").strip().upper() or None
        pricing_version_id = _event_identity(event, "pricing_version_id")
        credential_instance_id = _event_identity(event, "credential_instance_id")
        binding_instance_id = _event_identity(event, "binding_instance_id")
        pricing_snapshot = _snapshot_from_event(event)
        pricing_hash = str(event.get("pricing_version_sha256") or "").strip() or None
        recorded_at = str(event.get("recorded_at") or "").strip() or None

        summary["event_count"] += 1
        summary["actual_input_tokens"] += input_tokens
        summary["actual_output_tokens"] += output_tokens
        summary["cache_write_tokens"] += cache_write_tokens
        summary["cache_write_5m_tokens"] += cache_write_5m_tokens
        summary["cache_write_1h_tokens"] += cache_write_1h_tokens
        summary["cache_read_tokens"] += cache_read_tokens
        _add_currency_cost(summary, event_currency, cost)

        provider_model_key = f"{provider}|{model}"
        provider_bucket = summary["by_provider_model"].setdefault(
            provider_model_key,
            _new_bucket(
                provider_id=provider,
                model_id=model,
            ),
        )
        _accumulate_usage(
            provider_bucket,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_write_5m_tokens=cache_write_5m_tokens,
            cache_write_1h_tokens=cache_write_1h_tokens,
            cache_read_tokens=cache_read_tokens,
            currency=event_currency,
            cost=cost,
        )

        pricing_bucket = summary["by_pricing_version"].setdefault(
            pricing_version_id,
            _new_bucket(
                pricing_version_id=pricing_version_id,
                provider_id=provider,
                model_id=model,
                pricing_version_sha256=pricing_hash,
                pricing_snapshot=pricing_snapshot,
            ),
        )
        _accumulate_usage(
            pricing_bucket,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_write_5m_tokens=cache_write_5m_tokens,
            cache_write_1h_tokens=cache_write_1h_tokens,
            cache_read_tokens=cache_read_tokens,
            currency=event_currency,
            cost=cost,
        )

        credential_bucket = summary["by_credential_instance"].setdefault(
            credential_instance_id,
            _new_bucket(
                credential_instance_id=credential_instance_id,
            ),
        )
        _accumulate_usage(
            credential_bucket,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_write_5m_tokens=cache_write_5m_tokens,
            cache_write_1h_tokens=cache_write_1h_tokens,
            cache_read_tokens=cache_read_tokens,
            currency=event_currency,
            cost=cost,
        )

        binding_bucket = summary["by_binding_instance"].setdefault(
            binding_instance_id,
            _new_bucket(
                binding_instance_id=binding_instance_id,
            ),
        )
        _accumulate_usage(
            binding_bucket,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_write_5m_tokens=cache_write_5m_tokens,
            cache_write_1h_tokens=cache_write_1h_tokens,
            cache_read_tokens=cache_read_tokens,
            currency=event_currency,
            cost=cost,
        )

        segment_key = "|".join(
            (
                provider,
                model,
                pricing_version_id,
                credential_instance_id,
                binding_instance_id,
                event_currency or "UNSPECIFIED",
            )
        )
        segment = segment_buckets.setdefault(
            segment_key,
            _new_bucket(
                provider_id=provider,
                model_id=model,
                pricing_version_id=pricing_version_id,
                pricing_version_sha256=pricing_hash,
                pricing_snapshot=pricing_snapshot,
                credential_instance_id=credential_instance_id,
                binding_instance_id=binding_instance_id,
                first_recorded_at=recorded_at,
                last_recorded_at=recorded_at,
            ),
        )
        if recorded_at:
            first_recorded_at = str(segment.get("first_recorded_at") or "").strip()
            last_recorded_at = str(segment.get("last_recorded_at") or "").strip()
            if not first_recorded_at or recorded_at < first_recorded_at:
                segment["first_recorded_at"] = recorded_at
            if not last_recorded_at or recorded_at > last_recorded_at:
                segment["last_recorded_at"] = recorded_at

        _accumulate_usage(
            segment,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_write_5m_tokens=cache_write_5m_tokens,
            cache_write_1h_tokens=cache_write_1h_tokens,
            cache_read_tokens=cache_read_tokens,
            currency=event_currency,
            cost=cost,
        )

    _finalize_cost_view(summary)
    for collection_name in (
        "by_provider_model",
        "by_pricing_version",
        "by_credential_instance",
        "by_binding_instance",
    ):
        for bucket in summary[collection_name].values():
            _finalize_cost_view(bucket)

    segments = list(segment_buckets.values())
    for segment in segments:
        _finalize_cost_view(segment)
    segments.sort(
        key=lambda item: (
            str(item.get("first_recorded_at") or ""),
            str(item.get("provider_id") or ""),
            str(item.get("model_id") or ""),
            str(item.get("pricing_version_id") or ""),
        )
    )
    summary["billing_segments"] = segments

    _write_json_atomic(usage_summary_path(project_id), summary)
    return {
        "status": "ok",
        "summary": summary,
    }


def _normalized_usage_event_for_compare(event: dict[str, Any]) -> dict[str, Any]:
    copy = dict(event)
    copy.pop("recorded_at", None)
    return copy



def append_usage_event(project_id: str, event: dict[str, Any]) -> dict[str, Any]:
    """Append one authoritative provider usage event.

    Primary 33.1 creates this foundation but exposes no API route that calls it.
    Primary 33.2 may call it only after credential/binding lineage, immutable
    pricing provenance, provider execution, and final usage are authoritative.

    The event cost is calculated here from final usage counts and the immutable
    pricing snapshot. A caller-supplied actual_cost is accepted only when it
    exactly matches that calculation.
    """
    if not isinstance(event, dict):
        raise ProviderUsageError("usage event must be a mapping")

    required = (
        "usage_event_id",
        "generation_id",
        "provider_id",
        "model_id",
        "pricing_version_id",
        "credential_instance_id",
        "binding_instance_id",
    )
    cleaned = dict(event)
    for key in required:
        value = str(cleaned.get(key) or "").strip()
        if not value:
            raise ProviderUsageError(f"{key} is required")
        cleaned[key] = value

    cleaned["provider_id"] = cleaned["provider_id"].lower()
    cleaned["schema_version"] = USAGE_EVENT_SCHEMA_VERSION

    cleaned["actual_input_tokens"] = _int_field(
        cleaned, "actual_input_tokens"
    )
    cleaned["actual_output_tokens"] = _int_field(
        cleaned, "actual_output_tokens"
    )
    cleaned["cache_write_5m_tokens"] = _int_field(
        cleaned, "cache_write_5m_tokens"
    )
    cleaned["cache_write_1h_tokens"] = _int_field(
        cleaned, "cache_write_1h_tokens"
    )
    cleaned["cache_write_tokens"] = (
        cleaned["cache_write_5m_tokens"]
        + cleaned["cache_write_1h_tokens"]
    )
    cleaned["cache_read_tokens"] = _int_field(
        cleaned, "cache_read_tokens"
    )

    try:
        pricing_payload = provider_pricing_service.get_pricing_version_snapshot(
            cleaned["pricing_version_id"]
        )
    except provider_pricing_service.ProviderPricingError as exc:
        raise ProviderUsageError(str(exc)) from exc

    pricing = pricing_payload["pricing"]
    if (
        str(pricing.get("provider_id") or "").strip().lower()
        != cleaned["provider_id"]
    ):
        raise ProviderUsageError(
            "pricing_version_id provider does not match usage provider_id"
        )
    if str(pricing.get("model_id") or "").strip() != cleaned["model_id"]:
        raise ProviderUsageError(
            "pricing_version_id model does not match usage model_id"
        )

    cleaned["service_tier"] = str(
        pricing.get("service_tier") or ""
    ).strip()
    cleaned["inference_scope"] = str(
        pricing.get("inference_scope") or ""
    ).strip()
    cleaned["currency"] = str(
        pricing.get("currency") or ""
    ).strip().upper()
    if not cleaned["currency"]:
        raise ProviderUsageError(
            "pricing_version_id does not define a billing currency"
        )

    calculated_cost = _calculate_usage_cost(
        pricing,
        input_tokens=cleaned["actual_input_tokens"],
        output_tokens=cleaned["actual_output_tokens"],
        cache_write_5m_tokens=cleaned["cache_write_5m_tokens"],
        cache_write_1h_tokens=cleaned["cache_write_1h_tokens"],
        cache_read_tokens=cleaned["cache_read_tokens"],
    )
    supplied_cost = str(cleaned.get("actual_cost") or "").strip()
    if supplied_cost:
        supplied = _decimal_field(cleaned, "actual_cost")
        if supplied != calculated_cost:
            raise ProviderUsageError(
                "actual_cost does not match the immutable pricing snapshot calculation"
            )

    cleaned["actual_cost"] = _cost_string(calculated_cost)
    cleaned["cost_basis"] = "immutable_pricing_snapshot_calculation"
    cleaned["provider_invoice_reconciled"] = False
    cleaned["pricing_version_sha256"] = pricing_payload[
        "pricing_version_sha256"
    ]
    cleaned["pricing_snapshot"] = pricing

    supplied_recorded_at = str(cleaned.get("recorded_at") or "").strip()
    if supplied_recorded_at:
        cleaned["recorded_at"] = supplied_recorded_at
    else:
        cleaned.pop("recorded_at", None)

    path = usage_events_path(project_id)
    with _LOCK:
        existing = _read_all_events(project_id)
        for current in existing:
            if current.get("usage_event_id") != cleaned["usage_event_id"]:
                continue
            if (
                _normalized_usage_event_for_compare(current)
                == _normalized_usage_event_for_compare(cleaned)
            ):
                return {
                    "status": "ok",
                    "idempotent_replay": True,
                    "event": current,
                }
            raise ProviderUsageError(
                "usage_event_id already exists with different content"
            )

        if "recorded_at" not in cleaned:
            cleaned["recorded_at"] = _utc_iso()

        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            cleaned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded + "\n")

        summary = rebuild_usage_summary(project_id)["summary"]

    return {
        "status": "ok",
        "idempotent_replay": False,
        "event": cleaned,
        "summary": summary,
    }
