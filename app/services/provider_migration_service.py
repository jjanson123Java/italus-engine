"""Gate 38A controlled provider/model migration.

This service is the only migration authority for changing a project provider/model
binding after provider execution or usage has established immutable lineage.

The gate preserves historical binding, pricing, receipt, usage, and MODEL-origin
evidence. It creates a new binding instance only for future provider execution.
It never calls a provider and never requires a dummy credential.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.services import (
    provider_binding_service,
    provider_config_service,
    provider_generation_receipt_service,
    provider_pricing_service,
    provider_usage_service,
)

PROVIDER_MIGRATION_SERVICE_MARKER = "gate38a-controlled-provider-model-migration-v1"
PROVIDER_MIGRATION_SCHEMA_VERSION = "gate38a_provider_model_migration_v1"
MIGRATION_DIRECTORY = "provider_migrations"
HASH_ALGORITHM = "sha256:bytes_v1"
REQUEST_HASH_ALGORITHM = "sha256:canonical_json:utf8_v1"

_EXCLUDED_TREE_NAMES = {
    ".write.lock",
    ".authorship_ledger.write.lock",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProviderMigrationError(RuntimeError):
    """Raised when Gate 38A cannot establish a safe migration."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


class ProviderMigrationConflictError(ProviderMigrationError):
    """Raised when requested migration state conflicts with current lineage."""


def get_provider_migration_contract() -> dict[str, Any]:
    """Return Gate 38A authority and protected boundaries."""

    return {
        "status": "ok",
        "service": PROVIDER_MIGRATION_SERVICE_MARKER,
        "schema_version": PROVIDER_MIGRATION_SCHEMA_VERSION,
        "gate": "38A",
        "purpose": "controlled_provider_model_migration",
        "authority": {
            "changes_future_provider_binding": True,
            "creates_new_binding_instance": True,
            "preserves_previous_binding_snapshot": True,
            "preserves_historical_usage": True,
            "preserves_historical_receipts": True,
            "preserves_historical_pricing_lineage": True,
            "preserves_model_origin_provenance": True,
            "calls_provider": False,
            "requires_live_provider_credential": False,
            "mutates_authorship_ledger": False,
            "mutates_approved_continuity": False,
            "mutates_author_voice": False,
            "mutates_canon": False,
        },
        "preconditions": [
            "project_provider_binding_exists",
            "expected_current_binding_instance_matches",
            "no_active_provider_execution_intent",
            "target_provider_profile_exists",
            "target_model_is_accepted",
            "target_binding_differs_from_current_binding",
            "historical_evidence_is_readable",
        ],
        "history_location": (
            "data/projects/<project_id>/provider_migrations/<migration_id>.json"
        ),
        "idempotency": "idempotency_key_is_project_scoped_and_request_bound",
    }


def migration_root(project_id: str) -> Path:
    project_loader.load_manifest(project_id)
    return project_loader.project_dir(project_id) / MIGRATION_DIRECTORY


def migration_id_for(project_id: str, idempotency_key: str) -> str:
    project = project_loader.validate_project_id(project_id)
    key = _required_text(idempotency_key, "idempotency_key")
    encoded = key.encode("utf-8")
    if len(encoded) > 256:
        raise ProviderMigrationError(
            "IDEMPOTENCY_KEY_TOO_LONG",
            "idempotency_key exceeds the supported 256-byte limit.",
        )
    digest = hashlib.sha256(f"{project}\n{key}".encode("utf-8")).hexdigest()
    return f"migration_{digest[:32]}"


def migration_record_path(project_id: str, migration_id: str) -> Path:
    cleaned = str(migration_id or "").strip().lower()
    if not re.fullmatch(r"migration_[0-9a-f]{32}", cleaned):
        raise ProviderMigrationError(
            "MIGRATION_ID_INVALID",
            "migration_id is invalid.",
        )
    return migration_root(project_id) / f"{cleaned}.json"


def list_provider_migrations(project_id: str) -> dict[str, Any]:
    """Return immutable Gate 38A migration records for one project."""

    root = migration_root(project_id)
    records: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.glob("migration_*.json")):
            records.append(_read_migration_record(path, project_id=project_id))
    records.sort(
        key=lambda item: (
            str(item.get("created_at") or ""),
            str(item.get("migration_id") or ""),
        )
    )
    return {
        "status": "ok",
        "schema_version": PROVIDER_MIGRATION_SCHEMA_VERSION,
        "project_id": project_loader.validate_project_id(project_id),
        "migration_count": len(records),
        "migrations": records,
    }


def migrate_project_provider_model(
    project_id: str,
    *,
    idempotency_key: str,
    expected_current_binding_instance_id: str,
    target_provider_id: str,
    target_model_id: str,
    service_tier: str | None = None,
    inference_scope: str | None = None,
) -> dict[str, Any]:
    """Perform one controlled post-lineage provider/model migration.

    Historical evidence is fingerprinted before mutation and checked again after
    the binding transition. If post-transition preservation cannot be proven,
    the prior binding is restored and no successful migration record is written.
    """

    project = project_loader.validate_project_id(project_id)
    project_loader.load_manifest(project)
    migration_id = migration_id_for(project, idempotency_key)
    record_path = migration_record_path(project, migration_id)

    target_provider = _required_text(target_provider_id, "target_provider_id").lower()
    target_model = _required_text(target_model_id, "target_model_id")
    expected_binding_id = _required_text(
        expected_current_binding_instance_id,
        "expected_current_binding_instance_id",
    )

    if target_provider not in provider_config_service.DIRECT_PROVIDER_IDS:
        raise ProviderMigrationError(
            "TARGET_PROVIDER_NOT_DIRECT",
            "Gate 38A target provider must be an enabled direct provider.",
            details={"target_provider_id": target_provider},
        )

    profile = provider_config_service.get_provider_profile(target_provider)
    if not isinstance(profile, dict):
        raise ProviderMigrationError(
            "TARGET_PROVIDER_PROFILE_MISSING",
            "Save the target provider profile before controlled migration.",
            details={"target_provider_id": target_provider},
        )

    try:
        provider_config_service.require_accepted_model_id(
            target_provider,
            target_model,
        )
    except provider_config_service.ProviderConfigError as exc:
        raise ProviderMigrationError(
            "TARGET_MODEL_NOT_ACCEPTED",
            "The requested target model is not accepted by the direct-provider catalog.",
            details={
                "target_provider_id": target_provider,
                "target_model_id": target_model,
            },
        ) from exc

    target_tier = (
        str(service_tier).strip().lower()
        if service_tier is not None
        else str(profile.get("service_tier") or "standard").strip().lower()
    )
    target_scope = (
        str(inference_scope).strip().lower()
        if inference_scope is not None
        else str(profile.get("inference_scope") or "global").strip().lower()
    )
    if not target_tier:
        raise ProviderMigrationError("SERVICE_TIER_REQUIRED", "service_tier is required.")
    if not target_scope:
        raise ProviderMigrationError(
            "INFERENCE_SCOPE_REQUIRED",
            "inference_scope is required.",
        )

    request_payload = {
        "project_id": project,
        "expected_current_binding_instance_id": expected_binding_id,
        "target_provider_id": target_provider,
        "target_model_id": target_model,
        "service_tier": target_tier,
        "inference_scope": target_scope,
    }
    request_fingerprint = _canonical_sha256(request_payload)

    with provider_generation_receipt_service.project_execution_state_lock(project):
        if record_path.exists():
            existing = _read_migration_record(record_path, project_id=project)
            if str(existing.get("request_fingerprint") or "") != request_fingerprint:
                raise ProviderMigrationConflictError(
                    "IDEMPOTENCY_CONFLICT",
                    "This idempotency key is already bound to a different migration request.",
                    details={"migration_id": migration_id},
                )
            return {
                "status": "ok",
                "gate": "38A",
                "accepted": True,
                "idempotent_replay": True,
                "migration": existing,
                "binding": provider_binding_service.get_project_provider_binding(project),
            }

        binding_status = provider_binding_service.get_project_provider_binding(project)
        current = binding_status.get("binding")
        if not isinstance(current, dict):
            raise ProviderMigrationError(
                "CURRENT_BINDING_MISSING",
                "A current project provider/model binding is required for Gate 38A.",
            )

        current_binding_id = _required_text(
            current.get("binding_instance_id"),
            "current.binding_instance_id",
        )
        if current_binding_id != expected_binding_id:
            raise ProviderMigrationConflictError(
                "CURRENT_BINDING_CHANGED",
                "The current binding instance does not match the migration precondition.",
                details={
                    "expected_binding_instance_id": expected_binding_id,
                    "actual_binding_instance_id": current_binding_id,
                },
            )

        execution_state = provider_generation_receipt_service.get_project_execution_lock_state(
            project
        )
        if bool(execution_state.get("locked")):
            raise ProviderMigrationConflictError(
                "ACTIVE_EXECUTION_INTENT",
                "Controlled migration is forbidden while provider execution is active or unresolved.",
                details={
                    "active_intent_count": int(
                        execution_state.get("active_intent_count") or 0
                    ),
                    "statuses": dict(execution_state.get("statuses") or {}),
                },
            )

        current_snapshot = {
            "provider_id": str(current.get("provider_id") or "").strip().lower(),
            "model_id": str(current.get("model_id") or "").strip(),
            "service_tier": str(current.get("service_tier") or "standard").strip().lower(),
            "inference_scope": str(current.get("inference_scope") or "global").strip().lower(),
        }
        target_snapshot = {
            "provider_id": target_provider,
            "model_id": target_model,
            "service_tier": target_tier,
            "inference_scope": target_scope,
        }
        if current_snapshot == target_snapshot:
            raise ProviderMigrationError(
                "TARGET_BINDING_UNCHANGED",
                "Gate 38A requires a changed provider/model binding target.",
            )

        historical_before = _capture_historical_evidence(project)
        current_binding_sha256 = _canonical_sha256(current)

        new_binding: dict[str, Any] | None = None
        record_created = False
        try:
            new_binding = provider_binding_service._apply_controlled_migration_binding(
                project,
                target_provider_id=target_provider,
                target_model_id=target_model,
                service_tier=target_tier,
                inference_scope=target_scope,
                expected_current_binding_instance_id=current_binding_id,
                migration_id=migration_id,
            )
            historical_after = _capture_historical_evidence(project)
            if historical_before != historical_after:
                raise ProviderMigrationError(
                    "HISTORICAL_EVIDENCE_CHANGED",
                    "Historical provider/provenance evidence changed during Gate 38A migration.",
                    details={
                        "before": historical_before,
                        "after": historical_after,
                    },
                )

            raw_new_binding = new_binding.get("binding")
            if not isinstance(raw_new_binding, dict):
                raise ProviderMigrationError(
                    "NEW_BINDING_INVALID",
                    "Controlled migration did not return a new binding.",
                )

            new_binding_id = _required_text(
                raw_new_binding.get("binding_instance_id"),
                "new_binding.binding_instance_id",
            )
            if new_binding_id == current_binding_id:
                raise ProviderMigrationError(
                    "NEW_BINDING_LINEAGE_NOT_CREATED",
                    "Controlled migration did not create a new binding instance.",
                )
            if (
                str(raw_new_binding.get("previous_binding_instance_id") or "")
                != current_binding_id
            ):
                raise ProviderMigrationError(
                    "PREVIOUS_BINDING_LINEAGE_MISMATCH",
                    "New binding does not point to the preserved prior binding instance.",
                )

            created_at = _utc_iso()
            record_without_hash = {
                "schema_version": PROVIDER_MIGRATION_SCHEMA_VERSION,
                "service": PROVIDER_MIGRATION_SERVICE_MARKER,
                "gate": "38A",
                "accepted": True,
                "migration_id": migration_id,
                "project_id": project,
                "request_fingerprint": request_fingerprint,
                "idempotency_key_sha256": hashlib.sha256(
                    idempotency_key.encode("utf-8")
                ).hexdigest(),
                "created_at": created_at,
                "from_binding": current,
                "from_binding_sha256": current_binding_sha256,
                "to_binding": raw_new_binding,
                "to_binding_sha256": _canonical_sha256(raw_new_binding),
                "historical_evidence": historical_after,
                "preservation_checks": {
                    "usage_history_unchanged": True,
                    "receipt_history_unchanged": True,
                    "execution_intent_history_unchanged": True,
                    "model_origin_provenance_unchanged": True,
                    "authorship_ledger_unchanged": True,
                    "referenced_pricing_snapshots_resolved": True,
                },
                "execution": {
                    "provider_called": False,
                    "credential_required_for_migration": False,
                    "future_provider_execution_uses_new_binding_instance_id": new_binding_id,
                },
            }
            record = dict(record_without_hash)
            record["record_sha256"] = _canonical_sha256(record_without_hash)
            _write_json_exclusive(record_path, record)
            record_created = True
        except Exception:
            provider_binding_service._restore_binding_after_failed_controlled_migration(
                project,
                expected_current_binding_instance_id=(
                    str((new_binding or {}).get("binding", {}).get("binding_instance_id") or "")
                    or None
                ),
                prior_binding=current,
            )
            if record_created and record_path.exists():
                record_path.unlink()
            raise

        return {
            "status": "ok",
            "gate": "38A",
            "accepted": True,
            "idempotent_replay": False,
            "migration": record,
            "binding": provider_binding_service.get_project_provider_binding(project),
        }


def _capture_historical_evidence(project_id: str) -> dict[str, Any]:
    project_dir = project_loader.project_dir(project_id)
    usage_root = project_dir / "usage"
    provenance_root = project_dir / "provenance"

    usage_events = provider_usage_service.usage_events_path(project_id)
    usage_summary = provider_usage_service.usage_summary_path(project_id)
    receipts = usage_root / "provider_generation_receipts"
    intents = usage_root / "provider_execution_intents"

    pricing_refs = _referenced_pricing_snapshots(project_id, usage_events, receipts)

    return {
        "hash_algorithm": HASH_ALGORITHM,
        "usage_events": _path_fingerprint(usage_events),
        "usage_summary": _path_fingerprint(usage_summary),
        "provider_generation_receipts": _tree_fingerprint(receipts),
        "provider_execution_intents": _tree_fingerprint(intents),
        "provenance_tree": _tree_fingerprint(provenance_root),
        "referenced_pricing_versions": pricing_refs,
    }


def _referenced_pricing_snapshots(
    project_id: str,
    usage_events_path: Path,
    receipts_root: Path,
) -> list[dict[str, str]]:
    referenced: dict[str, str | None] = {}

    if usage_events_path.exists():
        with usage_events_path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, 1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ProviderMigrationError(
                        "USAGE_HISTORY_INVALID",
                        "Historical usage ledger contains invalid JSON.",
                        details={"line_number": line_number},
                    ) from exc
                if not isinstance(item, dict):
                    raise ProviderMigrationError(
                        "USAGE_HISTORY_INVALID",
                        "Historical usage ledger contains a non-object event.",
                        details={"line_number": line_number},
                    )
                _remember_pricing_reference(referenced, item)

    if receipts_root.exists():
        for path in sorted(receipts_root.glob("gen_*.json")):
            try:
                item = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProviderMigrationError(
                    "RECEIPT_HISTORY_INVALID",
                    "Historical provider receipt cannot be read.",
                    details={"path": path.name},
                ) from exc
            if not isinstance(item, dict):
                raise ProviderMigrationError(
                    "RECEIPT_HISTORY_INVALID",
                    "Historical provider receipt is not an object.",
                    details={"path": path.name},
                )
            _remember_pricing_reference(referenced, item)

    resolved: list[dict[str, str]] = []
    for version_id in sorted(referenced):
        expected_sha = referenced[version_id]
        try:
            snapshot = provider_pricing_service.get_pricing_version_snapshot(version_id)
        except provider_pricing_service.ProviderPricingError as exc:
            raise ProviderMigrationError(
                "HISTORICAL_PRICING_MISSING",
                "A pricing version referenced by historical usage/receipt evidence is unavailable.",
                details={"pricing_version_id": version_id},
            ) from exc
        actual_sha = str(snapshot.get("pricing_version_sha256") or "").strip().lower()
        if not _SHA256_RE.fullmatch(actual_sha):
            raise ProviderMigrationError(
                "HISTORICAL_PRICING_INVALID",
                "A historical pricing snapshot has no valid semantic SHA-256.",
                details={"pricing_version_id": version_id},
            )
        if expected_sha and expected_sha != actual_sha:
            raise ProviderMigrationError(
                "HISTORICAL_PRICING_HASH_MISMATCH",
                "Historical usage/receipt pricing lineage does not match its immutable pricing snapshot.",
                details={
                    "pricing_version_id": version_id,
                    "expected_sha256": expected_sha,
                    "actual_sha256": actual_sha,
                },
            )
        resolved.append(
            {
                "pricing_version_id": version_id,
                "pricing_version_sha256": actual_sha,
            }
        )
    return resolved


def _remember_pricing_reference(
    referenced: dict[str, str | None],
    payload: dict[str, Any],
) -> None:
    version_id = str(payload.get("pricing_version_id") or "").strip()
    if not version_id:
        return
    raw_sha = str(payload.get("pricing_version_sha256") or "").strip().lower()
    expected_sha = raw_sha if _SHA256_RE.fullmatch(raw_sha) else None
    prior = referenced.get(version_id)
    if prior and expected_sha and prior != expected_sha:
        raise ProviderMigrationError(
            "HISTORICAL_PRICING_REFERENCE_CONFLICT",
            "Historical evidence contains conflicting hashes for one pricing version.",
            details={"pricing_version_id": version_id},
        )
    referenced[version_id] = prior or expected_sha


def _path_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "sha256": None, "size": 0}
    if not path.is_file():
        raise ProviderMigrationError(
            "HISTORY_PATH_INVALID",
            "Historical evidence path is not a file.",
            details={"path": str(path)},
        )
    data = path.read_bytes()
    return {
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def _tree_fingerprint(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {
            "exists": False,
            "file_count": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }
    if not root.is_dir():
        raise ProviderMigrationError(
            "HISTORY_TREE_INVALID",
            "Historical evidence root is not a directory.",
            details={"path": str(root)},
        )

    records: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in _EXCLUDED_TREE_NAMES or path.name.endswith(".tmp"):
            continue
        data = path.read_bytes()
        records.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    return {
        "exists": True,
        "file_count": len(records),
        "sha256": _canonical_sha256(records),
    }


def _read_migration_record(path: Path, *, project_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderMigrationError(
            "MIGRATION_RECORD_INVALID",
            "Gate 38A migration record cannot be read.",
            details={"path": path.name},
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderMigrationError(
            "MIGRATION_RECORD_INVALID",
            "Gate 38A migration record is not an object.",
            details={"path": path.name},
        )
    if payload.get("schema_version") != PROVIDER_MIGRATION_SCHEMA_VERSION:
        raise ProviderMigrationError(
            "MIGRATION_RECORD_SCHEMA_UNSUPPORTED",
            "Gate 38A migration record schema is unsupported.",
            details={"path": path.name},
        )
    if str(payload.get("project_id") or "") != project_loader.validate_project_id(project_id):
        raise ProviderMigrationError(
            "MIGRATION_RECORD_PROJECT_MISMATCH",
            "Gate 38A migration record project identity mismatch.",
            details={"path": path.name},
        )
    stored_hash = str(payload.get("record_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(stored_hash):
        raise ProviderMigrationError(
            "MIGRATION_RECORD_HASH_INVALID",
            "Gate 38A migration record hash is invalid.",
            details={"path": path.name},
        )
    content = dict(payload)
    content.pop("record_sha256", None)
    if _canonical_sha256(content) != stored_hash:
        raise ProviderMigrationError(
            "MIGRATION_RECORD_HASH_MISMATCH",
            "Gate 38A migration record integrity check failed.",
            details={"path": path.name},
        )
    return payload


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ProviderMigrationConflictError(
            "MIGRATION_RECORD_ALREADY_EXISTS",
            "Gate 38A migration record already exists.",
            details={"path": path.name},
        ) from exc


def _canonical_sha256(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _required_text(value: Any, field: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ProviderMigrationError(
            "REQUIRED_FIELD_MISSING",
            f"{field} is required.",
            details={"field": field},
        )
    return cleaned


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
