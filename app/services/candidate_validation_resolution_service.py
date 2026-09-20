"""
Append-only author resolution records for candidate validation rules.

These records do not define validation truth. They record an author's explicit
resolution of MANUAL/SEMANTIC_REQUIRED rules for one exact candidate content
version and validator contract. Deterministic or integrity failures are never
overridable through this service.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator

from app.projects import project_loader


VALIDATION_RESOLUTION_SERVICE_MARKER = (
    "candidate-validation-author-resolution-v1-20260919"
)
VALIDATION_RESOLUTION_SCHEMA_VERSION = "candidate_validation_resolution_v1"
RESOLUTION_FILENAME = "candidate_validation_resolutions.jsonl"
RESOLUTION_LOCK_FILENAME = ".candidate_validation_resolutions.lock"
LOCK_TIMEOUT_SECONDS = 5.0
STALE_LOCK_SECONDS = 300.0
AUTHOR_CONFIRMED_COMPLIANT = "author_confirmed_compliant"


class CandidateValidationResolutionError(RuntimeError):
    """Raised when a validation-rule resolution cannot be recorded safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _required_text(value: Any, field_name: str, *, maximum: int = 512) -> str:
    text = str(value or "").strip()
    if not text:
        raise CandidateValidationResolutionError(f"{field_name} is required")
    if len(text) > maximum:
        raise CandidateValidationResolutionError(
            f"{field_name} exceeds the maximum length of {maximum}"
        )
    if any(ch in text for ch in ("\x00", "\r", "\n", "\t")):
        raise CandidateValidationResolutionError(
            f"{field_name} contains unsupported control characters"
        )
    return text


def _required_sha256(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name, maximum=64).lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CandidateValidationResolutionError(
            f"{field_name} must be a SHA-256 hex digest"
        )
    return text


def _note(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) < 3:
        raise CandidateValidationResolutionError(
            "resolution note must contain at least 3 characters"
        )
    if len(text) > 2000:
        raise CandidateValidationResolutionError(
            "resolution note exceeds the maximum length of 2000"
        )
    return text


def _paths(project_id: str) -> tuple[Path, Path]:
    project_loader.load_manifest(project_id)
    root = project_loader.project_dir(project_id).resolve()
    provenance = (root / "provenance").resolve()
    if root not in provenance.parents:
        raise CandidateValidationResolutionError(
            "validation resolution path escapes the project root"
        )
    provenance.mkdir(parents=True, exist_ok=True)
    return provenance / RESOLUTION_FILENAME, provenance / RESOLUTION_LOCK_FILENAME


@contextmanager
def _write_lock(lock_path: Path) -> Iterator[None]:
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fd = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            try:
                os.write(fd, _utc_now().encode("ascii", errors="ignore"))
            finally:
                os.close(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > STALE_LOCK_SECONDS:
                    lock_path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise CandidateValidationResolutionError(
                    "candidate validation resolution store is busy"
                )
            time.sleep(0.05)

    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        for line_number, raw in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(),
            start=1,
        ):
            if not raw.strip():
                continue
            item = json.loads(raw)
            if not isinstance(item, dict):
                raise CandidateValidationResolutionError(
                    f"validation resolution record {line_number} is not an object"
                )
            records.append(item)
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateValidationResolutionError(
            "candidate validation resolution store is unreadable"
        ) from exc
    return records


def get_author_resolutions(
    project_id: str,
    generation_id: str,
    *,
    content_version_id: str,
    content_sha256: str,
    validator_contract_sha256: str,
) -> list[dict[str, Any]]:
    """Return author resolutions bound to one exact content + contract identity."""

    project = project_loader.validate_project_id(project_id)
    generation = _required_text(generation_id, "generation_id", maximum=200)
    version = _required_text(content_version_id, "content_version_id", maximum=256)
    content_hash = _required_sha256(content_sha256, "content_sha256")
    contract_hash = _required_sha256(
        validator_contract_sha256,
        "validator_contract_sha256",
    )
    path, _ = _paths(project)

    matched: list[dict[str, Any]] = []
    for record in _load_records(path):
        if (
            str(record.get("project_id") or "") == project
            and str(record.get("generation_id") or "") == generation
            and str(record.get("content_version_id") or "") == version
            and str(record.get("content_sha256") or "") == content_hash
            and str(record.get("validator_contract_sha256") or "")
            == contract_hash
        ):
            matched.append(deepcopy(record))
    return matched


def record_author_resolution(
    project_id: str,
    generation_id: str,
    *,
    content_version_id: str,
    content_sha256: str,
    validator_contract_sha256: str,
    rule_id: str,
    rule_type: str,
    rule_instruction: str,
    validation_run_id: str,
    note: str,
) -> dict[str, Any]:
    """Append one immutable author resolution for an exact unresolved rule."""

    project = project_loader.validate_project_id(project_id)
    generation = _required_text(generation_id, "generation_id", maximum=200)
    version = _required_text(content_version_id, "content_version_id", maximum=256)
    content_hash = _required_sha256(content_sha256, "content_sha256")
    contract_hash = _required_sha256(
        validator_contract_sha256,
        "validator_contract_sha256",
    )
    rule = _required_text(rule_id, "rule_id", maximum=256)
    rule_kind = _required_text(rule_type, "rule_type", maximum=128)
    instruction = str(rule_instruction or "").strip()
    if not instruction:
        raise CandidateValidationResolutionError("rule_instruction is required")
    if len(instruction) > 12000:
        raise CandidateValidationResolutionError(
            "rule_instruction exceeds the maximum length of 12000"
        )
    run_id = _required_text(validation_run_id, "validation_run_id", maximum=256)
    author_note = _note(note)

    identity = {
        "project_id": project,
        "generation_id": generation,
        "content_version_id": version,
        "content_sha256": content_hash,
        "validator_contract_sha256": contract_hash,
        "rule_id": rule,
        "decision": AUTHOR_CONFIRMED_COMPLIANT,
    }
    resolution_id = "validation_resolution_" + _sha256(identity)[:32]
    payload = {
        "schema_version": VALIDATION_RESOLUTION_SCHEMA_VERSION,
        "service": VALIDATION_RESOLUTION_SERVICE_MARKER,
        "resolution_id": resolution_id,
        **identity,
        "rule_type": rule_kind,
        "rule_instruction": instruction,
        "validation_run_id_at_resolution": run_id,
        "author_note": author_note,
        "created_at": _utc_now(),
    }
    payload["record_sha256"] = _sha256(payload)

    path, lock_path = _paths(project)
    with _write_lock(lock_path):
        existing_records = _load_records(path)
        existing = next(
            (
                item
                for item in existing_records
                if str(item.get("resolution_id") or "") == resolution_id
            ),
            None,
        )
        if existing is not None:
            comparable_existing = deepcopy(existing)
            comparable_new = deepcopy(payload)
            comparable_existing.pop("created_at", None)
            comparable_existing.pop("record_sha256", None)
            comparable_new.pop("created_at", None)
            comparable_new.pop("record_sha256", None)
            if comparable_existing == comparable_new:
                return {
                    "status": "already_recorded",
                    "recorded": False,
                    "resolution": deepcopy(existing),
                }
            raise CandidateValidationResolutionError(
                "an immutable author resolution already exists for this exact rule/content identity"
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    return {
        "status": "recorded",
        "recorded": True,
        "resolution": deepcopy(payload),
    }
