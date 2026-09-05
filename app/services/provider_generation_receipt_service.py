from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.services import provider_usage_service


RECEIPT_SCHEMA_VERSION = "primary33.2.2-provider-generation-receipt-v1"
EXECUTION_INTENT_SCHEMA_VERSION = "primary33.2.2-provider-execution-intent-v1"
_ID_RE = re.compile(r"^gen_[0-9a-f]{32}$")


class ProviderGenerationReceiptError(RuntimeError):
    """Raised when immutable provider-generation receipt state is inconsistent."""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def generation_id_for(project_id: str, idempotency_key: str) -> str:
    project = project_loader.validate_project_id(project_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise ProviderGenerationReceiptError("idempotency_key is required")
    encoded = key.encode("utf-8")
    if len(encoded) > 256:
        raise ProviderGenerationReceiptError(
            "idempotency_key exceeds the supported 256-byte limit"
        )
    digest = hashlib.sha256(f"{project}\n{key}".encode("utf-8")).hexdigest()
    return f"gen_{digest[:32]}"


def _generation_id(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(cleaned):
        raise ProviderGenerationReceiptError("generation_id is invalid")
    return cleaned


def _usage_root(project_id: str) -> Path:
    project_loader.load_manifest(project_id)
    return project_loader.project_dir(project_id) / "usage"


def execution_intent_path(project_id: str, generation_id: str) -> Path:
    return _usage_root(project_id) / "provider_execution_intents" / (
        _generation_id(generation_id) + ".json"
    )


def generation_receipt_path(project_id: str, generation_id: str) -> Path:
    return _usage_root(project_id) / "provider_generation_receipts" / (
        _generation_id(generation_id) + ".json"
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderGenerationReceiptError(
            f"Provider execution state is unreadable: {path.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProviderGenerationReceiptError(
            f"Provider execution state is invalid: {path.name}"
        )
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


_PROJECT_EXECUTION_LOCKS_GUARD = threading.Lock()
_PROJECT_EXECUTION_LOCKS: dict[str, threading.RLock] = {}
_ACTIVE_EXECUTION_INTENT_STATUSES = {
    "provider_call_pending",
    "reconciliation_required",
}


def _project_execution_lock(project_id: str) -> threading.RLock:
    project = project_loader.validate_project_id(project_id)
    with _PROJECT_EXECUTION_LOCKS_GUARD:
        lock = _PROJECT_EXECUTION_LOCKS.get(project)
        if lock is None:
            lock = threading.RLock()
            _PROJECT_EXECUTION_LOCKS[project] = lock
        return lock


@contextmanager
def project_execution_state_lock(project_id: str):
    """Serialize binding mutation decisions with durable execution-intent changes.

    The durable intent files remain the source of truth across process restarts.
    This lock closes the in-process TOCTOU window between checking those files
    and creating/removing an intent or mutating a project binding.
    """

    lock = _project_execution_lock(project_id)
    with lock:
        yield


def get_project_execution_lock_state(project_id: str) -> dict[str, Any]:
    """Return fail-closed durable execution-intent lock state for one project."""

    project = project_loader.validate_project_id(project_id)
    with project_execution_state_lock(project):
        root = _usage_root(project) / "provider_execution_intents"
        if not root.exists():
            return {
                "locked": False,
                "active_intent_count": 0,
                "statuses": {},
            }
        if not root.is_dir():
            raise ProviderGenerationReceiptError(
                "Provider execution-intent state is invalid for this project."
            )

        active: list[dict[str, Any]] = []
        statuses: dict[str, int] = {}
        for path in sorted(root.glob("*.json")):
            payload = _read_json(path)
            if payload is None:
                continue
            if payload.get("schema_version") != EXECUTION_INTENT_SCHEMA_VERSION:
                raise ProviderGenerationReceiptError(
                    "Provider execution intent schema is not supported."
                )
            if str(payload.get("project_id") or "") != project:
                raise ProviderGenerationReceiptError(
                    "Provider execution intent project identity mismatch."
                )
            generation_id = _generation_id(str(payload.get("generation_id") or ""))
            if path.stem != generation_id:
                raise ProviderGenerationReceiptError(
                    "Provider execution intent generation identity mismatch."
                )
            identity = payload.get("identity")
            if not isinstance(identity, dict):
                raise ProviderGenerationReceiptError(
                    "Provider execution intent identity is missing or invalid."
                )
            if str(identity.get("project_id") or "") != project:
                raise ProviderGenerationReceiptError(
                    "Provider execution intent embedded project identity mismatch."
                )
            if str(identity.get("generation_id") or "") != generation_id:
                raise ProviderGenerationReceiptError(
                    "Provider execution intent embedded generation identity mismatch."
                )

            status = str(payload.get("status") or "").strip()
            if status not in _ACTIVE_EXECUTION_INTENT_STATUSES:
                raise ProviderGenerationReceiptError(
                    "Provider execution intent status is not recognized."
                )
            statuses[status] = statuses.get(status, 0) + 1
            active.append(payload)

        return {
            "locked": bool(active),
            "active_intent_count": len(active),
            "statuses": statuses,
        }


def execution_fingerprint(identity: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def get_receipt(project_id: str, generation_id: str) -> dict[str, Any] | None:
    payload = _read_json(generation_receipt_path(project_id, generation_id))
    if payload is None:
        return None
    if payload.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ProviderGenerationReceiptError(
            "Provider generation receipt schema is not supported."
        )
    if str(payload.get("project_id") or "") != project_loader.validate_project_id(project_id):
        raise ProviderGenerationReceiptError(
            "Provider generation receipt project identity mismatch."
        )
    if str(payload.get("generation_id") or "") != _generation_id(generation_id):
        raise ProviderGenerationReceiptError(
            "Provider generation receipt generation identity mismatch."
        )

    stored_digest = str(payload.get("receipt_sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", stored_digest):
        raise ProviderGenerationReceiptError(
            "Provider generation receipt SHA-256 is missing or invalid."
        )
    canonical_payload = dict(payload)
    canonical_payload.pop("receipt_sha256", None)
    calculated_digest = hashlib.sha256(
        _canonical_json(canonical_payload).encode("utf-8")
    ).hexdigest()
    if calculated_digest != stored_digest:
        raise ProviderGenerationReceiptError(
            "Provider generation receipt integrity check failed."
        )
    return payload


def find_usage_event_for_generation(
    project_id: str,
    generation_id: str,
) -> dict[str, Any] | None:
    gid = _generation_id(generation_id)
    path = provider_usage_service.usage_events_path(project_id)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(item, dict)
                and str(item.get("generation_id") or "").strip() == gid
            ):
                return item
    return None


def begin_execution(
    project_id: str,
    generation_id: str,
    *,
    fingerprint: str,
    identity: dict[str, Any],
) -> dict[str, Any]:
    gid = _generation_id(generation_id)
    expected = str(fingerprint or "").strip()
    if not expected:
        raise ProviderGenerationReceiptError("execution fingerprint is required")

    with project_execution_state_lock(project_id):
        receipt = get_receipt(project_id, gid)
        if receipt is not None:
            if str(receipt.get("execution_fingerprint") or "") != expected:
                raise ProviderGenerationReceiptError(
                    "idempotency_key was reused for a different provider execution identity"
                )
            return {
                "status": "completed",
                "receipt": receipt,
            }

        existing_usage = find_usage_event_for_generation(project_id, gid)
        if existing_usage is not None:
            raise ProviderGenerationReceiptError(
                "Usage exists for this generation but its immutable provider receipt is missing. "
                "Automatic provider replay is blocked until the execution is reconciled."
            )

        path = execution_intent_path(project_id, gid)
        current = _read_json(path)
        if current is not None:
            if str(current.get("execution_fingerprint") or "") != expected:
                raise ProviderGenerationReceiptError(
                    "idempotency_key was reused for a different provider execution identity"
                )
            return {
                "status": "reconciliation_required",
                "intent": current,
            }

        now = _utc_iso()
        payload = {
            "schema_version": EXECUTION_INTENT_SCHEMA_VERSION,
            "project_id": project_loader.validate_project_id(project_id),
            "generation_id": gid,
            "execution_fingerprint": expected,
            "status": "provider_call_pending",
            "created_at": now,
            "updated_at": now,
            "identity": dict(identity),
        }
        _write_json_atomic(path, payload)
        return {
            "status": "started",
            "intent": payload,
        }

def release_execution_intent(
    project_id: str,
    generation_id: str,
    *,
    fingerprint: str,
) -> None:
    with project_execution_state_lock(project_id):
        path = execution_intent_path(project_id, generation_id)
        current = _read_json(path)
        if current is None:
            return
        if str(current.get("execution_fingerprint") or "") != str(fingerprint or ""):
            raise ProviderGenerationReceiptError(
                "Refusing to release a provider execution intent with a different fingerprint."
            )
        path.unlink()


def mark_reconciliation_required(
    project_id: str,
    generation_id: str,
    *,
    fingerprint: str,
    code: str,
    message: str,
    provider_request_id: str | None = None,
) -> dict[str, Any]:
    with project_execution_state_lock(project_id):
        path = execution_intent_path(project_id, generation_id)
        current = _read_json(path)
        if current is None:
            raise ProviderGenerationReceiptError(
                "Provider execution intent is missing during reconciliation marking."
            )
        if str(current.get("execution_fingerprint") or "") != str(fingerprint or ""):
            raise ProviderGenerationReceiptError(
                "Provider execution intent fingerprint changed unexpectedly."
            )
        current = dict(current)
        current["status"] = "reconciliation_required"
        current["updated_at"] = _utc_iso()
        current["reconciliation"] = {
            "code": str(code or "PROVIDER_EXECUTION_RECONCILIATION_REQUIRED"),
            "message": str(message or "Provider execution requires reconciliation."),
            "provider_request_id": str(provider_request_id or "").strip() or None,
        }
        _write_json_atomic(path, current)
        return current


def write_receipt_once(
    project_id: str,
    generation_id: str,
    *,
    fingerprint: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    gid = _generation_id(generation_id)
    expected = str(fingerprint or "").strip()

    with project_execution_state_lock(project_id):
        existing = get_receipt(project_id, gid)
        if existing is not None:
            if str(existing.get("execution_fingerprint") or "") != expected:
                raise ProviderGenerationReceiptError(
                    "Existing provider generation receipt has a different execution fingerprint."
                )
            return existing

        intent_path = execution_intent_path(project_id, gid)
        intent = _read_json(intent_path)
        if intent is None:
            raise ProviderGenerationReceiptError(
                "Provider execution intent is missing before receipt commit."
            )
        if str(intent.get("execution_fingerprint") or "") != expected:
            raise ProviderGenerationReceiptError(
                "Provider execution intent fingerprint changed before receipt commit."
            )

        payload = dict(receipt)
        payload.update(
            {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "project_id": project_loader.validate_project_id(project_id),
                "generation_id": gid,
                "execution_fingerprint": expected,
                "recorded_at": str(payload.get("recorded_at") or _utc_iso()),
            }
        )
        payload.pop("receipt_sha256", None)
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        payload["receipt_sha256"] = digest

        receipt_path = generation_receipt_path(project_id, gid)
        if receipt_path.exists():
            raise ProviderGenerationReceiptError(
                "Provider generation receipt already exists unexpectedly."
            )
        _write_json_atomic(receipt_path, payload)

        try:
            intent_path.unlink()
        except FileNotFoundError:
            pass
        return payload
