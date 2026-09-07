"""
Primary 36A Approved Continuity core.

This service owns the first write authority for Approved Continuity. It accepts
only a terminal AUTHOR_ACCEPT lineage that Primary 35 can classify
deterministically, persists the exact accepted prose/hash, and records explicit
event/reveal establishment without inferring story facts from MODEL output.

Primary 36A introduced the backend write authority. Primary 36C adds the
read-only, integrity-validating document projection used by downstream Story
Eligibility and Chapter Knowledge Pack readers. Workspace integration and
production cutover remain outside this subpatch.
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
import uuid

from app.projects import project_loader
from app.projects.project_context import build_project_context
from app.services import author_review_service, authorship_classification_service


APPROVED_CONTINUITY_SERVICE_MARKER = "primary36a-approved-continuity-core-v1"
APPROVED_CONTINUITY_SCHEMA_VERSION = "approved_continuity_v1"
APPROVED_CONTINUITY_FILENAME = "approved_continuity.json"
WRITE_LOCK_FILENAME = ".approved_continuity.write.lock"
SUPPORTED_ESTABLISHMENT_TYPES = frozenset(
    {"event_established", "reveal_established"}
)
_LOCK_TIMEOUT_SECONDS = 3.0
_LOCK_POLL_SECONDS = 0.05


class ApprovedContinuityError(RuntimeError):
    """Raised when Approved Continuity cannot be committed safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = deepcopy(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": deepcopy(self.details),
        }


def get_approved_continuity_contract() -> dict[str, Any]:
    """Return the bounded Primary 36A ownership contract."""

    return {
        "status": "ok",
        "service": APPROVED_CONTINUITY_SERVICE_MARKER,
        "schema_version": APPROVED_CONTINUITY_SCHEMA_VERSION,
        "storage": f"runtime/{APPROVED_CONTINUITY_FILENAME}",
        "supported_establishment_types": sorted(SUPPORTED_ESTABLISHMENT_TYPES),
        "required_author_review_state": "accepted_pending_approved_continuity",
        "required_terminal_operation": "AUTHOR_ACCEPT",
        "required_classification_state": "classified",
        "authority": {
            "writes_approved_continuity": True,
            "mutates_canon": False,
            "mutates_model_origin": False,
            "mutates_provider_receipt": False,
            "mutates_provider_binding": False,
            "mutates_usage_or_pricing": False,
            "updates_author_voice": False,
            "writes_authorship_ledger": False,
            "calls_provider": False,
        },
    }


def approved_continuity_path(project_id: str) -> Path:
    """Resolve the project-local Approved Continuity file."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    path = (context.runtime_data_dir / APPROVED_CONTINUITY_FILENAME).resolve()
    project_dir = context.project_dir.resolve()
    if project_dir not in path.parents:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_PATH_ESCAPE",
            "Approved Continuity path escapes the project directory.",
        )
    return path


def get_approved_continuity_status(
    project_id: str,
    generation_id: str | None = None,
) -> dict[str, Any]:
    """Return current Approved Continuity state without mutating it."""

    path = approved_continuity_path(project_id)
    document = _load_document(path, project_id=project_id)
    generation = str(generation_id or "").strip()
    matching = None
    if generation:
        matching = next(
            (
                deepcopy(item)
                for item in document.get("commits", [])
                if str(item.get("generation_id") or "") == generation
            ),
            None,
        )
    return {
        "status": "ok",
        "service": APPROVED_CONTINUITY_SERVICE_MARKER,
        "schema_version": APPROVED_CONTINUITY_SCHEMA_VERSION,
        "project_id": project_id,
        "present": path.exists(),
        "revision": int(document.get("revision") or 0),
        "content_hash": str(document.get("content_hash") or ""),
        "approved_through": deepcopy(document.get("approved_through")),
        "commit_count": len(document.get("commits", [])),
        "generation_id": generation or None,
        "generation_committed": matching is not None if generation else None,
        "generation_commit": matching,
        "path": str(path),
    }



def read_approved_continuity_document(project_id: str) -> dict[str, Any]:
    """Return the integrity-validated Approved Continuity document.

    This is the only public downstream reader for the complete continuity
    document. It performs the same schema, project, commit-lineage, and
    content-hash validation used by the write path before returning a deep
    copy. Missing state is represented by the valid empty document.
    """

    project = str(project_id or "").strip()
    if not project:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_PROJECT_REQUIRED",
            "project_id is required.",
        )
    path = approved_continuity_path(project)
    document = _load_document(path, project_id=project)
    return {
        "status": "ok",
        "service": APPROVED_CONTINUITY_SERVICE_MARKER,
        "schema_version": APPROVED_CONTINUITY_SCHEMA_VERSION,
        "project_id": project,
        "present": path.exists(),
        "revision": int(document.get("revision") or 0),
        "content_hash": str(document.get("content_hash") or ""),
        "approved_through": deepcopy(document.get("approved_through")),
        "document": deepcopy(document),
        "path": str(path),
    }


def commit_approved_continuity(
    project_id: str,
    generation_id: str,
    *,
    book_number: int,
    chapter_number: int,
    established: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Commit exact author-accepted prose to project-local Approved Continuity.

    No prose interpretation is performed here. Callers may provide explicit
    event/reveal establishment records, which are schema-validated and bound to
    this exact book/chapter commit.
    """

    project = str(project_id or "").strip()
    generation = str(generation_id or "").strip()
    if not project:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_PROJECT_REQUIRED",
            "project_id is required.",
        )
    if not generation:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_GENERATION_REQUIRED",
            "generation_id is required.",
        )
    book = _positive_int(book_number, field="book_number")
    chapter = _positive_int(chapter_number, field="chapter_number")
    normalized_established = _normalize_established(
        established or [],
        book_number=book,
        chapter_number=chapter,
    )

    evidence = _accepted_evidence(project, generation)
    fingerprint_material = {
        "project_id": project,
        "generation_id": generation,
        "segment_id": evidence["segment_id"],
        "accepted_version_id": evidence["accepted_version_id"],
        "accepted_content_sha256": evidence["accepted_content_sha256"],
        "book_number": book,
        "chapter_number": chapter,
        "established": normalized_established,
    }
    commit_id = "ac_" + _json_sha256(fingerprint_material)[:40]
    path = approved_continuity_path(project)

    with _write_lock(path):
        document = _load_document(path, project_id=project)
        existing = next(
            (
                item
                for item in document.get("commits", [])
                if str(item.get("generation_id") or "") == generation
            ),
            None,
        )
        if existing is not None:
            if str(existing.get("commit_id") or "") == commit_id:
                return {
                    "status": "ok",
                    "service": APPROVED_CONTINUITY_SERVICE_MARKER,
                    "schema_version": APPROVED_CONTINUITY_SCHEMA_VERSION,
                    "project_id": project,
                    "generation_id": generation,
                    "approved_continuity_committed": True,
                    "idempotent_replay": True,
                    "commit": deepcopy(existing),
                    "document": deepcopy(document),
                }
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_GENERATION_CONFLICT",
                "generation_id already has a different Approved Continuity commit.",
                details={
                    "generation_id": generation,
                    "existing_commit_id": str(existing.get("commit_id") or ""),
                    "requested_commit_id": commit_id,
                },
            )

        now = _utc_now()
        commit_record = {
            "commit_id": commit_id,
            "project_id": project,
            "generation_id": generation,
            "segment_id": evidence["segment_id"],
            "book_number": book,
            "chapter_number": chapter,
            "accepted_version_id": evidence["accepted_version_id"],
            "accepted_content_sha256": evidence["accepted_content_sha256"],
            "accepted_content": evidence["accepted_content"],
            "author_accept_event_id": evidence["author_accept_event_id"],
            "author_accept_after_hash": evidence["author_accept_after_hash"],
            "classification_evidence": deepcopy(evidence["classification_evidence"]),
            "established": normalized_established,
            "previous_document_content_hash": str(document.get("content_hash") or ""),
            "committed_at": now,
        }

        commits = [deepcopy(item) for item in document.get("commits", [])]
        commits.append(commit_record)
        aggregate_established = _merge_established(
            document.get("established", []),
            normalized_established,
        )
        approved_through = _max_progression(
            document.get("approved_through"),
            {"book_number": book, "chapter_number": chapter},
        )

        updated = {
            "schema_version": APPROVED_CONTINUITY_SCHEMA_VERSION,
            "project_id": project,
            "revision": int(document.get("revision") or 0) + 1,
            "updated_at": now,
            "approved_through": approved_through,
            "established": aggregate_established,
            "commits": commits,
        }
        updated["content_hash"] = _document_hash(updated)
        _write_json_atomic(path, updated)
        persisted = _load_document(path, project_id=project)
        persisted_commit = next(
            (
                item
                for item in persisted.get("commits", [])
                if str(item.get("commit_id") or "") == commit_id
            ),
            None,
        )
        if persisted_commit is None:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_POSTWRITE_MISSING",
                "Approved Continuity write completed but the commit cannot be reloaded.",
            )

    return {
        "status": "ok",
        "service": APPROVED_CONTINUITY_SERVICE_MARKER,
        "schema_version": APPROVED_CONTINUITY_SCHEMA_VERSION,
        "project_id": project,
        "generation_id": generation,
        "approved_continuity_committed": True,
        "idempotent_replay": False,
        "commit": deepcopy(persisted_commit),
        "document": deepcopy(persisted),
    }


def _accepted_evidence(project_id: str, generation_id: str) -> dict[str, Any]:
    try:
        review = author_review_service.get_author_review_status(project_id, generation_id)
    except Exception as exc:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_REVIEW_UNAVAILABLE",
            "Author-review evidence could not be loaded.",
            details={"error": str(exc)},
        ) from exc

    if str(review.get("review_state") or "") != "accepted_pending_approved_continuity":
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_AUTHOR_ACCEPT_REQUIRED",
            "Approved Continuity requires accepted_pending_approved_continuity review state.",
            details={"review_state": str(review.get("review_state") or "")},
        )

    terminal = deepcopy(review.get("terminal_event") or {})
    if str(terminal.get("operation") or "") != "AUTHOR_ACCEPT":
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_AUTHOR_ACCEPT_EVENT_REQUIRED",
            "Accepted review state is not backed by AUTHOR_ACCEPT.",
        )

    accepted_version_id = str(review.get("current_version_id") or "").strip()
    accepted_content = str(review.get("current_content") or "")
    accepted_sha256 = _sha256_text(accepted_content)
    if not accepted_version_id:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_ACCEPTED_VERSION_MISSING",
            "Accepted review has no durable version_id.",
        )
    if accepted_sha256 != str(review.get("current_content_sha256") or ""):
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_ACCEPTED_HASH_MISMATCH",
            "Accepted review content does not match its recorded SHA-256.",
        )
    if str(terminal.get("version_id") or "") != accepted_version_id:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_TERMINAL_VERSION_MISMATCH",
            "AUTHOR_ACCEPT version does not match the current accepted version.",
        )
    if str(terminal.get("after_hash") or "") != accepted_sha256:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_TERMINAL_HASH_MISMATCH",
            "AUTHOR_ACCEPT hash does not match the accepted prose.",
        )

    try:
        classification = authorship_classification_service.classify_generation_segment(
            project_id,
            generation_id,
        )
    except Exception as exc:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_CLASSIFICATION_UNAVAILABLE",
            "Primary 35 classification evidence could not be loaded.",
            details={"error": str(exc)},
        ) from exc

    if str(classification.get("assessment_status") or "") != "classified":
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_CLASSIFICATION_REQUIRED",
            "Approved Continuity requires a completed Primary 35 classification.",
            details={
                "assessment_status": str(classification.get("assessment_status") or "")
            },
        )
    if str(classification.get("accepted_version_id") or "") != accepted_version_id:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_CLASSIFICATION_VERSION_MISMATCH",
            "Primary 35 accepted_version_id does not match author review.",
        )
    if str(classification.get("accepted_content_sha256") or "") != accepted_sha256:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_CLASSIFICATION_HASH_MISMATCH",
            "Primary 35 accepted-content hash does not match author review.",
        )

    segment_id = str(classification.get("segment_id") or "").strip()
    if not segment_id:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_SEGMENT_MISSING",
            "Primary 35 classification has no segment_id.",
        )

    terminal_event_id = str(terminal.get("event_id") or "").strip()
    if not terminal_event_id:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_AUTHOR_ACCEPT_EVENT_ID_MISSING",
            "AUTHOR_ACCEPT event has no durable event_id.",
        )

    return {
        "segment_id": segment_id,
        "accepted_version_id": accepted_version_id,
        "accepted_content": accepted_content,
        "accepted_content_sha256": accepted_sha256,
        "author_accept_event_id": terminal_event_id,
        "author_accept_after_hash": str(terminal.get("after_hash") or ""),
        "classification_evidence": {
            "service": str(classification.get("service") or ""),
            "schema_version": str(classification.get("schema_version") or ""),
            "assessment_status": str(classification.get("assessment_status") or ""),
            "final_segment_state": deepcopy(classification.get("final_segment_state")),
            "hccs": deepcopy(classification.get("hccs")),
            "accepted_version_id": accepted_version_id,
            "accepted_content_sha256": accepted_sha256,
            "evidence_confidence": deepcopy(classification.get("evidence_confidence")),
            "awarded_level": deepcopy(classification.get("awarded_level")),
        },
    }


def _load_document(path: Path, *, project_id: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": APPROVED_CONTINUITY_SCHEMA_VERSION,
            "project_id": project_id,
            "revision": 0,
            "approved_through": None,
            "established": [],
            "commits": [],
            "content_hash": "",
        }

    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_DOCUMENT_INVALID",
            "Approved Continuity document cannot be read.",
            details={"error": str(exc)},
        ) from exc

    if not isinstance(payload, dict):
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_DOCUMENT_INVALID",
            "Approved Continuity root must be an object.",
        )
    if payload.get("schema_version") != APPROVED_CONTINUITY_SCHEMA_VERSION:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_SCHEMA_MISMATCH",
            f"schema_version must be {APPROVED_CONTINUITY_SCHEMA_VERSION}.",
        )
    stored_project = str(payload.get("project_id") or "").strip()
    if stored_project and stored_project != project_id:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_PROJECT_MISMATCH",
            "Approved Continuity document belongs to another project.",
        )

    commits = payload.get("commits", [])
    established = payload.get("established", [])
    if not isinstance(commits, list) or not isinstance(established, list):
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_DOCUMENT_INVALID",
            "commits and established must be lists.",
        )
    _validate_existing_commits(commits)
    _normalize_established_records(established)

    stored_hash = str(payload.get("content_hash") or "").strip()
    if commits and not stored_hash:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_INTEGRITY_MISSING",
            "Primary 36 Approved Continuity commits require content_hash integrity.",
        )
    if stored_hash and stored_hash != _document_hash(payload):
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_INTEGRITY_MISMATCH",
            "Approved Continuity content_hash does not match persisted content.",
        )
    revision = payload.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_REVISION_INVALID",
            "revision must be a non-negative integer.",
        )
    _validate_document_projection(payload)
    return deepcopy(payload)



def _validate_document_projection(payload: dict[str, Any]) -> None:
    """Verify aggregate continuity state is derived only from persisted commits."""

    commits = payload.get("commits") or []
    revision = int(payload.get("revision") or 0)
    if revision != len(commits):
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_REVISION_MISMATCH",
            "Approved Continuity revision must equal the number of committed generations.",
            details={"revision": revision, "commit_count": len(commits)},
        )

    expected_established: list[dict[str, Any]] = []
    expected_through: dict[str, int] | None = None
    for index, item in enumerate(commits):
        book = _positive_int(
            item.get("book_number"),
            field=f"commits[{index}].book_number",
        )
        chapter = _positive_int(
            item.get("chapter_number"),
            field=f"commits[{index}].chapter_number",
        )
        raw_established = item.get("established", [])
        if not isinstance(raw_established, list):
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_COMMIT_INVALID",
                f"commits[{index}].established must be a list.",
            )
        normalized_commit = _normalize_established(
            raw_established,
            book_number=book,
            chapter_number=chapter,
        )
        if normalized_commit != raw_established:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_COMMIT_ESTABLISHMENT_MISMATCH",
                f"commits[{index}].established is not canonical for its book/chapter.",
            )
        expected_established = _merge_established(
            expected_established,
            normalized_commit,
        )
        expected_through = _max_progression(
            expected_through,
            {"book_number": book, "chapter_number": chapter},
        )

    actual_established = _normalize_established_records(
        payload.get("established") or []
    )
    if actual_established != expected_established:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_AGGREGATE_MISMATCH",
            "Approved Continuity established state is not the exact aggregate of commits.",
        )

    actual_through = payload.get("approved_through")
    if expected_through is None:
        if actual_through is not None:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_PROGRESS_MISMATCH",
                "Approved Continuity cannot advance without a persisted accepted commit.",
            )
    else:
        if not isinstance(actual_through, dict):
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_PROGRESS_MISMATCH",
                "approved_through must be present when accepted commits exist.",
            )
        normalized_through = {
            "book_number": _positive_int(
                actual_through.get("book_number"),
                field="approved_through.book_number",
            ),
            "chapter_number": _positive_int(
                actual_through.get("chapter_number"),
                field="approved_through.chapter_number",
            ),
        }
        if normalized_through != expected_through:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_PROGRESS_MISMATCH",
                "approved_through is not the exact maximum progression of accepted commits.",
                details={
                    "expected": expected_through,
                    "actual": normalized_through,
                },
            )


def _validate_existing_commits(commits: list[Any]) -> None:
    ids: set[str] = set()
    generations: set[str] = set()
    for index, item in enumerate(commits):
        if not isinstance(item, dict):
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_COMMIT_INVALID",
                f"commits[{index}] must be an object.",
            )
        commit_id = str(item.get("commit_id") or "").strip()
        generation_id = str(item.get("generation_id") or "").strip()
        accepted_version_id = str(item.get("accepted_version_id") or "").strip()
        accepted_sha = str(item.get("accepted_content_sha256") or "").strip()
        accepted_content = str(item.get("accepted_content") or "")
        if not commit_id or not generation_id or not accepted_version_id:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_COMMIT_INVALID",
                f"commits[{index}] is missing identity fields.",
            )
        if accepted_sha != _sha256_text(accepted_content):
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_COMMIT_HASH_MISMATCH",
                f"commits[{index}] accepted prose hash is invalid.",
            )
        if commit_id in ids or generation_id in generations:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_COMMIT_DUPLICATE",
                "Approved Continuity contains duplicate commit or generation identity.",
            )
        ids.add(commit_id)
        generations.add(generation_id)


def _normalize_established(
    records: list[dict[str, Any]],
    *,
    book_number: int,
    chapter_number: int,
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_ESTABLISHED_INVALID",
            "established must be a list.",
        )
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_ESTABLISHED_INVALID",
                f"established[{index}] must be an object.",
            )
        requirement_type = str(item.get("type") or "").strip()
        target_ref = str(item.get("target_ref") or "").strip()
        if requirement_type not in SUPPORTED_ESTABLISHMENT_TYPES or not target_ref:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_ESTABLISHED_INVALID",
                f"established[{index}] has unsupported type or missing target_ref.",
            )
        item_book = _positive_int(
            item.get("book_number", book_number),
            field=f"established[{index}].book_number",
        )
        item_chapter = _positive_int(
            item.get("chapter_number", chapter_number),
            field=f"established[{index}].chapter_number",
        )
        if item_book != book_number or item_chapter != chapter_number:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_ESTABLISHED_SCOPE_MISMATCH",
                "An establishment record must be bound to the committing book/chapter.",
                details={
                    "index": index,
                    "book_number": item_book,
                    "chapter_number": item_chapter,
                },
            )
        key = (requirement_type, target_ref, item_book, item_chapter)
        if key not in seen:
            seen.add(key)
            normalized.append(
                {
                    "type": requirement_type,
                    "target_ref": target_ref,
                    "book_number": item_book,
                    "chapter_number": item_chapter,
                }
            )
    normalized.sort(
        key=lambda item: (
            int(item["book_number"]),
            int(item["chapter_number"]),
            str(item["type"]),
            str(item["target_ref"]),
        )
    )
    return normalized


def _normalize_established_records(records: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_ESTABLISHED_INVALID",
                f"established[{index}] must be an object.",
            )
        requirement_type = str(item.get("type") or "").strip()
        target_ref = str(item.get("target_ref") or "").strip()
        book = _positive_int(item.get("book_number"), field=f"established[{index}].book_number")
        chapter = _positive_int(
            item.get("chapter_number"),
            field=f"established[{index}].chapter_number",
        )
        if requirement_type not in SUPPORTED_ESTABLISHMENT_TYPES or not target_ref:
            raise ApprovedContinuityError(
                "APPROVED_CONTINUITY_ESTABLISHED_INVALID",
                f"established[{index}] has unsupported type or missing target_ref.",
            )
        normalized.append(
            {
                "type": requirement_type,
                "target_ref": target_ref,
                "book_number": book,
                "chapter_number": chapter,
            }
        )
    return normalized


def _merge_established(
    existing: list[Any],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_existing = _normalize_established_records(existing)
    merged: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for item in normalized_existing + incoming:
        key = (
            str(item["type"]),
            str(item["target_ref"]),
            int(item["book_number"]),
            int(item["chapter_number"]),
        )
        merged[key] = deepcopy(item)
    return [
        merged[key]
        for key in sorted(
            merged,
            key=lambda value: (value[2], value[3], value[0], value[1]),
        )
    ]


def _max_progression(
    current: Any,
    incoming: dict[str, int],
) -> dict[str, int]:
    incoming_pair = (int(incoming["book_number"]), int(incoming["chapter_number"]))
    if not isinstance(current, dict):
        return deepcopy(incoming)
    try:
        current_pair = (
            _positive_int(current.get("book_number"), field="approved_through.book_number"),
            _positive_int(
                current.get("chapter_number"),
                field="approved_through.chapter_number",
            ),
        )
    except ApprovedContinuityError:
        raise
    if current_pair >= incoming_pair:
        return {
            "book_number": current_pair[0],
            "chapter_number": current_pair[1],
        }
    return deepcopy(incoming)


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_SCOPE_INVALID",
            f"{field} must be a positive integer.",
        )
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_SCOPE_INVALID",
            f"{field} must be a positive integer.",
        ) from exc
    if number <= 0:
        raise ApprovedContinuityError(
            "APPROVED_CONTINUITY_SCOPE_INVALID",
            f"{field} must be a positive integer.",
        )
    return number


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _document_hash(payload: dict[str, Any]) -> str:
    normalized = deepcopy(payload)
    normalized.pop("content_hash", None)
    return _json_sha256(normalized)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def _write_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(WRITE_LOCK_FILENAME)
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ApprovedContinuityError(
                    "APPROVED_CONTINUITY_WRITE_LOCKED",
                    "Approved Continuity is locked by another writer.",
                )
            time.sleep(_LOCK_POLL_SECONDS)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii", errors="ignore"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    data = (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n"
    )
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)
