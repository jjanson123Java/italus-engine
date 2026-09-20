"""
Immutable per-generation validator-sidecar snapshot boundary.

This service freezes the exact validator_sidecar that was already bound into
the provider-neutral generation request through the Chapter Knowledge sidecar
SHA. It does not build a second validation truth source, call providers, mutate
Canon/runtime state, or decide whether prose is acceptable.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from app.projects import project_loader


VALIDATION_CONTRACT_SNAPSHOT_SCHEMA_VERSION = (
    "candidate_validation_contract_snapshot_v1"
)
VALIDATION_CONTRACT_SNAPSHOT_DIRECTORY = (
    Path("provenance") / "generation_validation_contracts"
)
_GENERATION_ID_RE = re.compile(r"^gen_[0-9a-f]{32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CandidateValidationContractError(RuntimeError):
    """Raised when exact validator-sidecar lineage cannot be proven."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _generation_id(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not _GENERATION_ID_RE.fullmatch(cleaned):
        raise CandidateValidationContractError("generation_id is invalid")
    return cleaned


def _validated_position(value: Any, name: str) -> int:
    if isinstance(value, bool):
        parsed = 0
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
    if parsed < 1:
        raise CandidateValidationContractError(f"{name} must be a positive integer")
    return parsed


def _project_relative_file(project_id: str, relative_path: str) -> tuple[Path, str]:
    project_loader.load_manifest(project_id)
    project_root = project_loader.project_dir(project_id).resolve()
    clean = str(relative_path or "").replace("\\", "/").lstrip("/")
    if not clean:
        raise CandidateValidationContractError(
            "Chapter Knowledge validator sidecar path is missing"
        )

    candidate = (project_root / clean).resolve()
    if candidate != project_root and project_root not in candidate.parents:
        raise CandidateValidationContractError(
            "Chapter Knowledge validator sidecar path escapes the project root"
        )
    if not candidate.is_file():
        raise CandidateValidationContractError(
            "Chapter Knowledge validator sidecar file is missing"
        )
    return candidate, candidate.relative_to(project_root).as_posix()


def _snapshot_path(project_id: str, generation_id: str) -> Path:
    project_loader.load_manifest(project_id)
    return (
        project_loader.project_dir(project_id)
        / VALIDATION_CONTRACT_SNAPSHOT_DIRECTORY
        / f"{_generation_id(generation_id)}.json"
    )


def _read_snapshot(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateValidationContractError(
            f"Validation contract snapshot is unreadable: {path.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise CandidateValidationContractError(
            f"Validation contract snapshot is invalid: {path.name}"
        )
    return payload


def _validate_snapshot(
    project_id: str,
    generation_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    project = project_loader.validate_project_id(project_id)
    generation = _generation_id(generation_id)

    if (
        payload.get("schema_version")
        != VALIDATION_CONTRACT_SNAPSHOT_SCHEMA_VERSION
    ):
        raise CandidateValidationContractError(
            "Validation contract snapshot schema is not supported"
        )
    if str(payload.get("project_id") or "") != project:
        raise CandidateValidationContractError(
            "Validation contract snapshot project identity mismatch"
        )
    if str(payload.get("generation_id") or "") != generation:
        raise CandidateValidationContractError(
            "Validation contract snapshot generation identity mismatch"
        )

    contract = payload.get("validator_sidecar")
    if not isinstance(contract, dict):
        raise CandidateValidationContractError(
            "Validation contract snapshot is missing validator_sidecar"
        )
    contract_sha256 = str(
        payload.get("validator_contract_sha256") or ""
    ).strip().lower()
    if (
        not _SHA256_RE.fullmatch(contract_sha256)
        or contract_sha256 != _canonical_sha256(contract)
    ):
        raise CandidateValidationContractError(
            "Validation contract snapshot validator-sidecar integrity check failed"
        )

    stored_snapshot_sha256 = str(
        payload.get("snapshot_sha256") or ""
    ).strip().lower()
    canonical_payload = deepcopy(payload)
    canonical_payload.pop("snapshot_sha256", None)
    actual_snapshot_sha256 = _canonical_sha256(canonical_payload)
    if (
        not _SHA256_RE.fullmatch(stored_snapshot_sha256)
        or stored_snapshot_sha256 != actual_snapshot_sha256
    ):
        raise CandidateValidationContractError(
            "Validation contract snapshot integrity check failed"
        )

    source = payload.get("source_sidecar")
    if not isinstance(source, dict):
        raise CandidateValidationContractError(
            "Validation contract snapshot source identity is missing"
        )
    source_sha256 = str(source.get("sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(source_sha256):
        raise CandidateValidationContractError(
            "Validation contract snapshot source SHA-256 is invalid"
        )

    return deepcopy(payload)


def get_generation_validator_contract_snapshot(
    project_id: str,
    generation_id: str,
) -> dict[str, Any] | None:
    """Return one verified immutable snapshot, or None when none exists."""

    path = _snapshot_path(project_id, generation_id)
    if not path.exists():
        return None
    return _validate_snapshot(
        project_id,
        generation_id,
        _read_snapshot(path),
    )


def snapshot_generation_validator_contract(
    project_id: str,
    generation_id: str,
    *,
    book_number: int,
    chapter_number: int,
    source_artifacts: dict[str, Any],
) -> dict[str, Any]:
    """Freeze the exact validator_sidecar already named by a generation request.

    The request's full Chapter Knowledge sidecar SHA is the authority. The file
    is re-hashed before any snapshot is written so a changed/rebuilt sidecar
    cannot be silently attached to an older request identity.
    """

    project = project_loader.validate_project_id(project_id)
    generation = _generation_id(generation_id)
    book = _validated_position(book_number, "book_number")
    chapter = _validated_position(chapter_number, "chapter_number")

    if not isinstance(source_artifacts, dict):
        raise CandidateValidationContractError(
            "Generation request source_artifacts are missing"
        )
    chapter_source = source_artifacts.get("chapter_knowledge")
    if not isinstance(chapter_source, dict):
        raise CandidateValidationContractError(
            "Generation request Chapter Knowledge source identity is missing"
        )

    expected_source_sha256 = str(
        chapter_source.get("sidecar_sha256") or ""
    ).strip().lower()
    if not _SHA256_RE.fullmatch(expected_source_sha256):
        raise CandidateValidationContractError(
            "Generation request Chapter Knowledge sidecar SHA-256 is invalid"
        )

    source_path, source_relative_path = _project_relative_file(
        project,
        str(chapter_source.get("sidecar_project_relative_path") or ""),
    )
    source_bytes = source_path.read_bytes()
    actual_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if actual_source_sha256 != expected_source_sha256:
        raise CandidateValidationContractError(
            "Chapter Knowledge validator sidecar changed after request construction"
        )

    try:
        source_payload = json.loads(source_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateValidationContractError(
            "Chapter Knowledge validator sidecar is unreadable"
        ) from exc
    if not isinstance(source_payload, dict):
        raise CandidateValidationContractError(
            "Chapter Knowledge validator sidecar root must be an object"
        )

    validator_sidecar = source_payload.get("validator_sidecar")
    if not isinstance(validator_sidecar, dict):
        raise CandidateValidationContractError(
            "Chapter Knowledge sidecar does not contain validator_sidecar"
        )

    snapshot_relative_path = (
        VALIDATION_CONTRACT_SNAPSHOT_DIRECTORY / f"{generation}.json"
    ).as_posix()
    payload = {
        "schema_version": VALIDATION_CONTRACT_SNAPSHOT_SCHEMA_VERSION,
        "project_id": project,
        "generation_id": generation,
        "book_number": book,
        "chapter_number": chapter,
        "snapshot_project_relative_path": snapshot_relative_path,
        "source_sidecar": {
            "project_relative_path": source_relative_path,
            "sha256": actual_source_sha256,
            "schema_version": str(source_payload.get("schema_version") or ""),
        },
        "validator_contract_sha256": _canonical_sha256(validator_sidecar),
        "validator_sidecar": deepcopy(validator_sidecar),
    }
    payload["snapshot_sha256"] = _canonical_sha256(payload)

    path = _snapshot_path(project, generation)
    if path.exists():
        existing = _validate_snapshot(project, generation, _read_snapshot(path))
        if existing != payload:
            raise CandidateValidationContractError(
                "Existing validation contract snapshot does not match this generation request"
            )
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass

    return _validate_snapshot(project, generation, _read_snapshot(path))

def resolve_generation_validator_contract(
    project_id: str,
    generation_id: str,
    *,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Resolve the exact validator contract for one completed generation.

    New generations use the immutable Patch-1 snapshot. A legacy generation may
    use the current Chapter Knowledge sidecar only when rebuilding the complete
    provider-neutral request reproduces both immutable receipt hashes exactly.
    This legacy path is read-only and never creates a retrospective snapshot.
    """

    project = project_loader.validate_project_id(project_id)
    generation = _generation_id(generation_id)
    if not isinstance(receipt, dict):
        raise CandidateValidationContractError("provider receipt is required")

    snapshot = get_generation_validator_contract_snapshot(project, generation)
    receipt_contract_fields = {
        "validator_sidecar_sha256": str(
            receipt.get("validator_sidecar_sha256") or ""
        ).strip().lower(),
        "validator_contract_sha256": str(
            receipt.get("validator_contract_sha256") or ""
        ).strip().lower(),
        "validator_snapshot_sha256": str(
            receipt.get("validator_snapshot_sha256") or ""
        ).strip().lower(),
        "validator_snapshot_project_relative_path": str(
            receipt.get("validator_snapshot_project_relative_path") or ""
        ).strip(),
    }
    receipt_has_contract = any(receipt_contract_fields.values())

    if snapshot is not None:
        if not all(receipt_contract_fields.values()):
            raise CandidateValidationContractError(
                "Provider receipt is missing validator-contract snapshot lineage"
            )
        source = snapshot.get("source_sidecar")
        source = source if isinstance(source, dict) else {}
        expected = {
            "validator_sidecar_sha256": str(source.get("sha256") or "").lower(),
            "validator_contract_sha256": str(
                snapshot.get("validator_contract_sha256") or ""
            ).lower(),
            "validator_snapshot_sha256": str(
                snapshot.get("snapshot_sha256") or ""
            ).lower(),
            "validator_snapshot_project_relative_path": str(
                snapshot.get("snapshot_project_relative_path") or ""
            ),
        }
        if receipt_contract_fields != expected:
            raise CandidateValidationContractError(
                "Provider receipt validator-contract lineage does not match the immutable snapshot"
            )
        return {
            "status": "resolved",
            "resolution_mode": "immutable_generation_snapshot",
            "project_id": project,
            "generation_id": generation,
            "book_number": int(snapshot.get("book_number") or 0),
            "chapter_number": int(snapshot.get("chapter_number") or 0),
            "validator_sidecar_sha256": expected["validator_sidecar_sha256"],
            "validator_contract_sha256": expected["validator_contract_sha256"],
            "validator_snapshot_sha256": expected["validator_snapshot_sha256"],
            "validator_snapshot_project_relative_path": expected[
                "validator_snapshot_project_relative_path"
            ],
            "validator_sidecar": deepcopy(snapshot.get("validator_sidecar") or {}),
            "historical_contract_proven": True,
        }

    if receipt_has_contract:
        raise CandidateValidationContractError(
            "Provider receipt names a validator-contract snapshot that is missing"
        )

    try:
        book_number = _validated_position(receipt.get("book_number"), "book_number")
        chapter_number = _validated_position(
            receipt.get("chapter_number"),
            "chapter_number",
        )
    except CandidateValidationContractError:
        raise

    # Local import avoids making generation construction part of the Patch-1
    # snapshot write path and preserves the provider-execution dependency graph.
    from app.services import generation_service

    try:
        envelope = generation_service.build_generation_request_envelope(
            project,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except generation_service.GenerationRequestBuildError as exc:
        raise CandidateValidationContractError(
            "Legacy validation contract cannot be reconstructed from current generation inputs"
        ) from exc

    request_sha256 = str(envelope.get("request_content_sha256") or "").lower()
    prompt = envelope.get("prompt")
    prompt = prompt if isinstance(prompt, dict) else {}
    prompt_sha256 = str(prompt.get("prompt_sha256") or "").lower()
    if (
        request_sha256 != str(receipt.get("request_content_sha256") or "").lower()
        or prompt_sha256 != str(receipt.get("prompt_sha256") or "").lower()
    ):
        raise CandidateValidationContractError(
            "Legacy generation inputs no longer reproduce the immutable request and prompt hashes"
        )

    source_artifacts = envelope.get("source_artifacts")
    source_artifacts = (
        source_artifacts if isinstance(source_artifacts, dict) else {}
    )
    chapter_source = source_artifacts.get("chapter_knowledge")
    chapter_source = chapter_source if isinstance(chapter_source, dict) else {}
    expected_source_sha256 = str(
        chapter_source.get("sidecar_sha256") or ""
    ).strip().lower()
    if not _SHA256_RE.fullmatch(expected_source_sha256):
        raise CandidateValidationContractError(
            "Reconstructed Chapter Knowledge sidecar SHA-256 is invalid"
        )

    source_path, source_relative_path = _project_relative_file(
        project,
        str(chapter_source.get("sidecar_project_relative_path") or ""),
    )
    source_bytes = source_path.read_bytes()
    actual_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if actual_source_sha256 != expected_source_sha256:
        raise CandidateValidationContractError(
            "Reconstructed Chapter Knowledge sidecar does not match its request identity"
        )
    try:
        source_payload = json.loads(source_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateValidationContractError(
            "Reconstructed Chapter Knowledge sidecar is unreadable"
        ) from exc
    validator_sidecar = source_payload.get("validator_sidecar")
    if not isinstance(validator_sidecar, dict):
        raise CandidateValidationContractError(
            "Reconstructed Chapter Knowledge sidecar has no validator_sidecar"
        )

    return {
        "status": "resolved",
        "resolution_mode": "legacy_reconstructed_exact_request_match",
        "project_id": project,
        "generation_id": generation,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "validator_sidecar_sha256": actual_source_sha256,
        "validator_contract_sha256": _canonical_sha256(validator_sidecar),
        "validator_snapshot_sha256": "",
        "validator_snapshot_project_relative_path": "",
        "validator_sidecar": deepcopy(validator_sidecar),
        "source_sidecar_project_relative_path": source_relative_path,
        "historical_contract_proven": True,
    }

