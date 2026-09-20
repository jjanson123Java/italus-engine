"""Immutable audited semantic-validation receipts for one exact candidate version."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from app.projects import project_loader

SEMANTIC_STORE_MARKER = "primary45-semantic-validation-store-v1"
SEMANTIC_RECEIPT_SCHEMA_VERSION = "candidate_semantic_validation_receipt_v1"
SEMANTIC_INTENT_SCHEMA_VERSION = "candidate_semantic_validation_intent_v1"
_ID_RE = re.compile(r"^semval_[0-9a-f]{32}$")


class CandidateSemanticValidationStoreError(RuntimeError):
    pass


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def semantic_validation_id_for(
    project_id: str,
    generation_id: str,
    *,
    content_sha256: str,
    validator_contract_sha256: str,
    idempotency_key: str,
) -> str:
    project = project_loader.validate_project_id(project_id)
    key = str(idempotency_key or "").strip()
    if not key:
        raise CandidateSemanticValidationStoreError("idempotency_key is required")
    if len(key.encode("utf-8")) > 256:
        raise CandidateSemanticValidationStoreError("idempotency_key exceeds 256 UTF-8 bytes")
    identity = {
        "project_id": project,
        "generation_id": str(generation_id or "").strip(),
        "content_sha256": str(content_sha256 or "").strip().lower(),
        "validator_contract_sha256": str(validator_contract_sha256 or "").strip().lower(),
        "idempotency_key": key,
    }
    return "semval_" + _sha256(identity)[:32]


def _safe_id(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(cleaned):
        raise CandidateSemanticValidationStoreError("semantic_validation_id is invalid")
    return cleaned


def _root(project_id: str) -> Path:
    project_loader.load_manifest(project_id)
    return project_loader.project_dir(project_id) / "usage"


def receipt_path(project_id: str, semantic_validation_id: str) -> Path:
    return _root(project_id) / "semantic_validation_receipts" / f"{_safe_id(semantic_validation_id)}.json"


def intent_path(project_id: str, semantic_validation_id: str) -> Path:
    return _root(project_id) / "semantic_validation_intents" / f"{_safe_id(semantic_validation_id)}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateSemanticValidationStoreError(f"Semantic validation state is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise CandidateSemanticValidationStoreError(f"Semantic validation state is invalid: {path.name}")
    return value


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp, path)


def get_receipt(project_id: str, semantic_validation_id: str) -> dict[str, Any] | None:
    payload = _read_json(receipt_path(project_id, semantic_validation_id))
    if payload is None:
        return None
    if payload.get("schema_version") != SEMANTIC_RECEIPT_SCHEMA_VERSION:
        raise CandidateSemanticValidationStoreError("Semantic validation receipt schema is not supported")
    expected = str(payload.get("receipt_sha256") or "").strip().lower()
    comparable = deepcopy(payload)
    comparable.pop("receipt_sha256", None)
    actual = _sha256(comparable)
    if expected != actual:
        raise CandidateSemanticValidationStoreError("Semantic validation receipt SHA-256 mismatch")
    return payload


def begin_intent(project_id: str, semantic_validation_id: str, identity: dict[str, Any]) -> dict[str, Any]:
    sem_id = _safe_id(semantic_validation_id)
    existing_receipt = get_receipt(project_id, sem_id)
    if existing_receipt is not None:
        return {"status": "completed", "receipt": existing_receipt}

    path = intent_path(project_id, sem_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SEMANTIC_INTENT_SCHEMA_VERSION,
        "service": SEMANTIC_STORE_MARKER,
        "semantic_validation_id": sem_id,
        "project_id": project_loader.validate_project_id(project_id),
        "identity": deepcopy(identity),
        "identity_sha256": _sha256(identity),
        "created_at": _utc_iso(),
        "status": "provider_call_pending",
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        current = _read_json(path)
        if current and str(current.get("identity_sha256") or "") == payload["identity_sha256"]:
            return {"status": "in_progress", "intent": current}
        raise CandidateSemanticValidationStoreError("Semantic validation intent already exists with different identity")
    try:
        os.write(fd, encoded.encode("utf-8"))
    finally:
        os.close(fd)
    return {"status": "started", "intent": payload}


def release_intent(project_id: str, semantic_validation_id: str) -> None:
    path = intent_path(project_id, semantic_validation_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def complete(
    project_id: str,
    semantic_validation_id: str,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    sem_id = _safe_id(semantic_validation_id)
    path = intent_path(project_id, sem_id)
    intent = _read_json(path)
    if intent is None:
        raise CandidateSemanticValidationStoreError("Semantic validation execution intent is missing")
    payload = deepcopy(receipt)
    payload["schema_version"] = SEMANTIC_RECEIPT_SCHEMA_VERSION
    payload["service"] = SEMANTIC_STORE_MARKER
    payload["semantic_validation_id"] = sem_id
    payload["completed_at"] = _utc_iso()
    payload["receipt_sha256"] = _sha256(payload)
    _write_json_atomic(receipt_path(project_id, sem_id), payload)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return payload


def latest_exact_receipt(
    project_id: str,
    generation_id: str,
    *,
    content_sha256: str,
    validator_contract_sha256: str,
) -> dict[str, Any] | None:
    root = _root(project_id) / "semantic_validation_receipts"
    if not root.exists():
        return None
    matches: list[dict[str, Any]] = []
    for path in sorted(root.glob("semval_*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        if (
            str(payload.get("generation_id") or "") == str(generation_id or "")
            and str(payload.get("content_sha256") or "").lower() == str(content_sha256 or "").lower()
            and str(payload.get("validator_contract_sha256") or "").lower()
            == str(validator_contract_sha256 or "").lower()
        ):
            expected = str(payload.get("receipt_sha256") or "").strip().lower()
            comparable = deepcopy(payload)
            comparable.pop("receipt_sha256", None)
            if expected != _sha256(comparable):
                raise CandidateSemanticValidationStoreError("Semantic validation receipt SHA-256 mismatch")
            matches.append(payload)
    if not matches:
        return None
    matches.sort(key=lambda item: (str(item.get("completed_at") or ""), str(item.get("semantic_validation_id") or "")))
    return deepcopy(matches[-1])


def exact_verdict_map(
    project_id: str,
    generation_id: str,
    *,
    content_sha256: str,
    validator_contract_sha256: str,
) -> dict[str, dict[str, Any]]:
    root = _root(project_id) / "semantic_validation_receipts"
    if not root.exists():
        return {}

    matches: list[dict[str, Any]] = []
    for path in sorted(root.glob("semval_*.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        if (
            str(payload.get("generation_id") or "") == str(generation_id or "")
            and str(payload.get("content_sha256") or "").lower()
            == str(content_sha256 or "").lower()
            and str(payload.get("validator_contract_sha256") or "").lower()
            == str(validator_contract_sha256 or "").lower()
        ):
            expected = str(payload.get("receipt_sha256") or "").strip().lower()
            comparable = deepcopy(payload)
            comparable.pop("receipt_sha256", None)
            if expected != _sha256(comparable):
                raise CandidateSemanticValidationStoreError(
                    "Semantic validation receipt SHA-256 mismatch"
                )
            matches.append(payload)

    matches.sort(
        key=lambda item: (
            str(item.get("completed_at") or ""),
            str(item.get("semantic_validation_id") or ""),
        )
    )
    result: dict[str, dict[str, Any]] = {}
    for receipt in matches:
        verdicts = receipt.get("verdicts")
        verdicts = verdicts if isinstance(verdicts, list) else []
        for item in verdicts:
            if not isinstance(item, dict):
                continue
            rule_id = str(item.get("rule_id") or "")
            if not rule_id:
                continue
            enriched = deepcopy(item)
            enriched["semantic_validation_id"] = str(
                receipt.get("semantic_validation_id") or ""
            )
            enriched["provider_id"] = str(receipt.get("provider_id") or "")
            enriched["model_id"] = str(receipt.get("model_id") or "")
            enriched["receipt_sha256"] = str(receipt.get("receipt_sha256") or "")
            result[rule_id] = enriched
    return result
