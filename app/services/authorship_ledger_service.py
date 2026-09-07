"""
Primary 38 durable Authorship Provenance Ledger.

The ledger is a project-local, integrity-checked projection of prose that has
already entered Approved Continuity. It binds each accepted manuscript segment
to its immutable provenance lineage and persisted Primary 35 classification,
then derives deterministic book/project manuscript hashes.

This service does not decide legal authorship, copyrightability, ownership, or
publisher policy. It does not write Approved Continuity, Author Voice, Canon,
provider state, usage, pricing, or MODEL-origin evidence and never calls a
provider.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Iterator
import uuid

from app.services import (
    approved_continuity_service,
    authorship_provenance_service,
)


AUTHORSHIP_LEDGER_SERVICE_MARKER = "primary38-authorship-provenance-ledger-v1"
AUTHORSHIP_LEDGER_SCHEMA_VERSION = "primary38_authorship_provenance_ledger_v1"
AUTHORSHIP_LEDGER_FILENAME = "authorship_ledger.json"
AUTHORSHIP_LEDGER_WRITE_LOCK_FILENAME = ".authorship_ledger.write.lock"
MANUSCRIPT_HASH_ALGORITHM = (
    "sha256:canonical_json:[book_number,chapter_number,accepted_content]:utf8_v1"
)
LEDGER_HASH_ALGORITHM = "sha256:canonical_json:utf8_v1"
LEDGER_DISCLAIMER = (
    "This ledger records Italus provenance evidence and internal classification "
    "controls. It is not a legal determination of authorship, copyright ownership, "
    "copyrightability, or publisher/marketplace policy compliance."
)

_LOCK_TIMEOUT_SECONDS = 3.0
_LOCK_POLL_SECONDS = 0.05
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AuthorshipLedgerError(RuntimeError):
    """Raised when the Primary 38 ledger cannot be compiled or persisted safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "AUTHORSHIP_LEDGER_FAILED")
        self.message = str(message)
        self.details = deepcopy(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": deepcopy(self.details),
        }


def get_authorship_ledger_contract() -> dict[str, Any]:
    """Return the bounded Primary 38 ownership and persistence contract."""

    return {
        "status": "ok",
        "service": AUTHORSHIP_LEDGER_SERVICE_MARKER,
        "schema_version": AUTHORSHIP_LEDGER_SCHEMA_VERSION,
        "storage": f"provenance/{AUTHORSHIP_LEDGER_FILENAME}",
        "source_of_truth": {
            "accepted_manuscript": "Primary 36 Approved Continuity",
            "lineage": "Primary 28 immutable origins + append-only provenance events",
            "classification": "Primary 35 classification evidence persisted by Approved Continuity",
        },
        "manuscript_hash_algorithm": MANUSCRIPT_HASH_ALGORITHM,
        "ledger_hash_algorithm": LEDGER_HASH_ALGORITHM,
        "entry_scope": "approved_continuity_commits_only",
        "rejected_or_uncommitted_text_in_manuscript_ledger": False,
        "disclaimer": LEDGER_DISCLAIMER,
        "authority": {
            "writes_authorship_ledger": True,
            "aggregates_book_wide_provenance": True,
            "derives_manuscript_hashes": True,
            "records_internal_classification_evidence": True,
            "makes_legal_authorship_determination": False,
            "writes_approved_continuity": False,
            "mutates_canon": False,
            "mutates_runtime_story_state": False,
            "mutates_model_origin": False,
            "mutates_provider_receipt": False,
            "mutates_provider_binding": False,
            "mutates_usage_or_pricing": False,
            "updates_author_voice": False,
            "calls_provider": False,
            "implements_gate_38a": False,
        },
    }


def authorship_ledger_path(project_id: str) -> Path:
    """Return the project-local Primary 38 ledger path."""

    root = authorship_provenance_service.provenance_root(project_id).resolve()
    path = (root / AUTHORSHIP_LEDGER_FILENAME).resolve()
    if root not in path.parents:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_PATH_ESCAPE",
            "Authorship ledger path escapes the provenance directory.",
        )
    return path


def get_authorship_ledger_status(project_id: str) -> dict[str, Any]:
    """Return ledger integrity/freshness without mutating project state."""

    project = _required_id(project_id, "project_id")
    path = authorship_ledger_path(project)
    if not path.exists():
        return {
            "status": "ok",
            "service": AUTHORSHIP_LEDGER_SERVICE_MARKER,
            "schema_version": AUTHORSHIP_LEDGER_SCHEMA_VERSION,
            "project_id": project,
            "present": False,
            "integrity_status": "not_built",
            "current": False,
            "stale": False,
            "ledger_revision": 0,
            "entry_count": 0,
            "book_count": 0,
            "manuscript_sha256": "",
            "path": str(path),
            "disclaimer": LEDGER_DISCLAIMER,
        }

    ledger = _load_ledger(path, project_id=project)
    try:
        source = _compile_source(project)
    except Exception as exc:
        return {
            "status": "ok",
            "service": AUTHORSHIP_LEDGER_SERVICE_MARKER,
            "schema_version": AUTHORSHIP_LEDGER_SCHEMA_VERSION,
            "project_id": project,
            "present": True,
            "integrity_status": "ok",
            "current": False,
            "stale": True,
            "source_status": "unavailable",
            "source_error": str(exc),
            "ledger_revision": int(ledger.get("ledger_revision") or 0),
            "entry_count": len(ledger.get("entries") or []),
            "book_count": len(ledger.get("books") or []),
            "manuscript_sha256": str(ledger.get("manuscript_sha256") or ""),
            "source_fingerprint": str(ledger.get("source_fingerprint") or ""),
            "content_hash": str(ledger.get("content_hash") or ""),
            "path": str(path),
            "disclaimer": LEDGER_DISCLAIMER,
        }

    current = str(ledger.get("source_fingerprint") or "") == source["source_fingerprint"]
    return {
        "status": "ok",
        "service": AUTHORSHIP_LEDGER_SERVICE_MARKER,
        "schema_version": AUTHORSHIP_LEDGER_SCHEMA_VERSION,
        "project_id": project,
        "present": True,
        "integrity_status": "ok",
        "current": current,
        "stale": not current,
        "source_status": "ok",
        "ledger_revision": int(ledger.get("ledger_revision") or 0),
        "entry_count": len(ledger.get("entries") or []),
        "book_count": len(ledger.get("books") or []),
        "manuscript_sha256": str(ledger.get("manuscript_sha256") or ""),
        "source_fingerprint": str(ledger.get("source_fingerprint") or ""),
        "current_source_fingerprint": source["source_fingerprint"],
        "content_hash": str(ledger.get("content_hash") or ""),
        "path": str(path),
        "disclaimer": LEDGER_DISCLAIMER,
    }


def read_authorship_ledger(project_id: str) -> dict[str, Any]:
    """Return the persisted ledger and whether it matches current accepted evidence."""

    project = _required_id(project_id, "project_id")
    path = authorship_ledger_path(project)
    if not path.exists():
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_NOT_BUILT",
            "Authorship ledger has not been built for this project.",
            details={"project_id": project},
        )
    ledger = _load_ledger(path, project_id=project)
    source = _compile_source(project)
    current = str(ledger.get("source_fingerprint") or "") == source["source_fingerprint"]
    return {
        "status": "ok",
        "service": AUTHORSHIP_LEDGER_SERVICE_MARKER,
        "schema_version": AUTHORSHIP_LEDGER_SCHEMA_VERSION,
        "project_id": project,
        "current": current,
        "stale": not current,
        "ledger": deepcopy(ledger),
        "path": str(path),
    }


def build_authorship_ledger(project_id: str) -> dict[str, Any]:
    """Compile and persist the current project-wide authorship ledger.

    An exact source replay is idempotent. A changed Approved Continuity or
    accepted-lineage fingerprint creates the next ledger revision.
    """

    project = _required_id(project_id, "project_id")
    provenance_status = authorship_provenance_service.get_provenance_status(project)
    if provenance_status.get("initialized") is not True:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_PROVENANCE_NOT_INITIALIZED",
            "Primary 38 requires initialized project provenance storage.",
        )
    if str(provenance_status.get("integrity_status") or "") != "ok":
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_PROVENANCE_INTEGRITY_REQUIRED",
            "Primary 38 requires integrity-valid provenance storage.",
            details={
                "integrity_status": provenance_status.get("integrity_status"),
                "integrity_error": provenance_status.get("integrity_error"),
            },
        )

    source = _compile_source(project)
    path = authorship_ledger_path(project)

    with _write_lock(path):
        existing = _load_ledger(path, project_id=project) if path.exists() else None
        if (
            existing is not None
            and str(existing.get("source_fingerprint") or "")
            == source["source_fingerprint"]
        ):
            return {
                "status": "ok",
                "service": AUTHORSHIP_LEDGER_SERVICE_MARKER,
                "schema_version": AUTHORSHIP_LEDGER_SCHEMA_VERSION,
                "project_id": project,
                "ledger_built": True,
                "idempotent_replay": True,
                "ledger_revision": int(existing.get("ledger_revision") or 0),
                "entry_count": len(existing.get("entries") or []),
                "book_count": len(existing.get("books") or []),
                "manuscript_sha256": str(existing.get("manuscript_sha256") or ""),
                "source_fingerprint": str(existing.get("source_fingerprint") or ""),
                "content_hash": str(existing.get("content_hash") or ""),
                "ledger": deepcopy(existing),
                "path": str(path),
            }

        revision = 1
        previous_hash = ""
        if existing is not None:
            revision = int(existing.get("ledger_revision") or 0) + 1
            previous_hash = str(existing.get("content_hash") or "")

        ledger = {
            "schema_version": AUTHORSHIP_LEDGER_SCHEMA_VERSION,
            "service": AUTHORSHIP_LEDGER_SERVICE_MARKER,
            "project_id": project,
            "ledger_revision": revision,
            "generated_at": _utc_now(),
            "previous_ledger_content_hash": previous_hash,
            "source_fingerprint": source["source_fingerprint"],
            "source_approved_continuity": deepcopy(source["source_approved_continuity"]),
            "entry_scope": "approved_continuity_commits_only",
            "entry_count": len(source["entries"]),
            "book_count": len(source["books"]),
            "entries": deepcopy(source["entries"]),
            "books": deepcopy(source["books"]),
            "classification_summary": deepcopy(source["classification_summary"]),
            "manuscript_hash_algorithm": MANUSCRIPT_HASH_ALGORITHM,
            "manuscript_sha256": source["manuscript_sha256"],
            "disclaimer": LEDGER_DISCLAIMER,
            "authority": deepcopy(get_authorship_ledger_contract()["authority"]),
        }
        ledger["content_hash"] = _ledger_content_hash(ledger)
        _write_json_atomic(path, ledger)
        persisted = _load_ledger(path, project_id=project)

    return {
        "status": "ok",
        "service": AUTHORSHIP_LEDGER_SERVICE_MARKER,
        "schema_version": AUTHORSHIP_LEDGER_SCHEMA_VERSION,
        "project_id": project,
        "ledger_built": True,
        "idempotent_replay": False,
        "ledger_revision": int(persisted.get("ledger_revision") or 0),
        "entry_count": len(persisted.get("entries") or []),
        "book_count": len(persisted.get("books") or []),
        "manuscript_sha256": str(persisted.get("manuscript_sha256") or ""),
        "source_fingerprint": str(persisted.get("source_fingerprint") or ""),
        "content_hash": str(persisted.get("content_hash") or ""),
        "ledger": deepcopy(persisted),
        "path": str(path),
    }


def _compile_source(project_id: str) -> dict[str, Any]:
    """Compile deterministic ledger source material without writing."""

    projection = approved_continuity_service.read_approved_continuity_document(project_id)
    document = deepcopy(projection.get("document") or {})
    commits = list(document.get("commits") or [])
    entries: list[dict[str, Any]] = []
    manuscript_material: list[dict[str, Any]] = []

    for index, commit in enumerate(commits):
        entry, manuscript_item = _compile_entry(
            project_id,
            commit=commit,
            continuity_index=index,
        )
        entries.append(entry)
        manuscript_material.append(manuscript_item)

    ordering = sorted(
        range(len(entries)),
        key=lambda idx: (
            int(entries[idx]["book_number"]),
            int(entries[idx]["chapter_number"]),
            int(entries[idx]["continuity_index"]),
        ),
    )
    ordered_entries = [deepcopy(entries[idx]) for idx in ordering]
    ordered_material = [deepcopy(manuscript_material[idx]) for idx in ordering]

    books = _build_book_summaries(ordered_entries, ordered_material)
    classification_summary = _classification_summary(ordered_entries)
    manuscript_sha256 = _json_sha256(ordered_material)
    source_approved_continuity = {
        "service": str(projection.get("service") or ""),
        "schema_version": str(projection.get("schema_version") or ""),
        "revision": int(projection.get("revision") or 0),
        "content_hash": str(projection.get("content_hash") or ""),
        "commit_count": len(commits),
    }
    source_fingerprint = _json_sha256(
        {
            "project_id": project_id,
            "approved_continuity": source_approved_continuity,
            "entry_evidence": [
                {
                    "entry_id": item["entry_id"],
                    "accepted_content_sha256": item["accepted_content_sha256"],
                    "lineage_evidence_sha256": item["lineage_evidence_sha256"],
                    "classification_evidence_sha256": item[
                        "classification_evidence_sha256"
                    ],
                }
                for item in ordered_entries
            ],
            "manuscript_sha256": manuscript_sha256,
        }
    )

    return {
        "entries": ordered_entries,
        "books": books,
        "classification_summary": classification_summary,
        "manuscript_sha256": manuscript_sha256,
        "source_approved_continuity": source_approved_continuity,
        "source_fingerprint": source_fingerprint,
    }


def _compile_entry(
    project_id: str,
    *,
    commit: Any,
    continuity_index: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(commit, dict):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_CONTINUITY_COMMIT_INVALID",
            "Approved Continuity contains a non-object commit.",
            details={"continuity_index": continuity_index},
        )

    commit_id = _required_id(commit.get("commit_id"), "commit_id")
    generation_id = _required_id(commit.get("generation_id"), "generation_id")
    segment_id = _required_id(commit.get("segment_id"), "segment_id")
    accepted_version_id = _required_id(
        commit.get("accepted_version_id"),
        "accepted_version_id",
    )
    author_accept_event_id = _required_id(
        commit.get("author_accept_event_id"),
        "author_accept_event_id",
    )
    book_number = _positive_int(commit.get("book_number"), "book_number")
    chapter_number = _positive_int(commit.get("chapter_number"), "chapter_number")
    accepted_content = str(commit.get("accepted_content") or "")
    accepted_sha256 = _required_sha256(
        commit.get("accepted_content_sha256"),
        "accepted_content_sha256",
    )
    if _sha256_text(accepted_content) != accepted_sha256:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_ACCEPTED_CONTENT_HASH_MISMATCH",
            "Approved Continuity accepted prose does not match its SHA-256.",
            details={"commit_id": commit_id},
        )
    author_accept_after_hash = _required_sha256(
        commit.get("author_accept_after_hash"),
        "author_accept_after_hash",
    )
    if author_accept_after_hash != accepted_sha256:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_AUTHOR_ACCEPT_HASH_MISMATCH",
            "AUTHOR_ACCEPT hash does not match the accepted manuscript prose.",
            details={"commit_id": commit_id},
        )

    classification = _classification_evidence(
        commit.get("classification_evidence"),
        accepted_version_id=accepted_version_id,
        accepted_content_sha256=accepted_sha256,
        commit_id=commit_id,
    )
    lineage = authorship_provenance_service.get_segment_lineage_records(
        project_id,
        generation_id=generation_id,
        segment_id=segment_id,
    )
    lineage_evidence = _lineage_evidence(
        lineage,
        generation_id=generation_id,
        segment_id=segment_id,
        accepted_version_id=accepted_version_id,
        accepted_content_sha256=accepted_sha256,
        author_accept_event_id=author_accept_event_id,
        commit_id=commit_id,
    )

    identity = {
        "project_id": project_id,
        "commit_id": commit_id,
        "generation_id": generation_id,
        "segment_id": segment_id,
        "accepted_version_id": accepted_version_id,
        "accepted_content_sha256": accepted_sha256,
    }
    entry_id = "ledger_entry_" + _json_sha256(identity)[:40]
    classification_digest = _json_sha256(classification)
    lineage_digest = _json_sha256(lineage_evidence)

    entry = {
        "entry_id": entry_id,
        "continuity_index": int(continuity_index),
        "continuity_commit_id": commit_id,
        "generation_id": generation_id,
        "segment_id": segment_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "accepted_version_id": accepted_version_id,
        "accepted_content_sha256": accepted_sha256,
        "accepted_character_count": len(accepted_content),
        "author_accept_event_id": author_accept_event_id,
        "classification": classification,
        "classification_evidence_sha256": classification_digest,
        "origin_evidence": lineage_evidence["origin"],
        "lineage_event_count": len(lineage_evidence["events"]),
        "lineage_events": lineage_evidence["events"],
        "lineage_evidence_sha256": lineage_digest,
    }
    manuscript_item = {
        "book_number": book_number,
        "chapter_number": chapter_number,
        "accepted_content": accepted_content,
    }
    return entry, manuscript_item


def _classification_evidence(
    value: Any,
    *,
    accepted_version_id: str,
    accepted_content_sha256: str,
    commit_id: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_CLASSIFICATION_REQUIRED",
            "Approved Continuity commit lacks Primary 35 classification evidence.",
            details={"commit_id": commit_id},
        )
    if str(value.get("assessment_status") or "") != "classified":
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_CLASSIFICATION_NOT_FINAL",
            "Ledger entries require classified Primary 35 evidence.",
            details={"commit_id": commit_id},
        )
    if str(value.get("accepted_version_id") or "") != accepted_version_id:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_CLASSIFICATION_VERSION_MISMATCH",
            "Classification accepted_version_id does not match Approved Continuity.",
            details={"commit_id": commit_id},
        )
    classification_hash = _required_sha256(
        value.get("accepted_content_sha256"),
        "classification accepted_content_sha256",
    )
    if classification_hash != accepted_content_sha256:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_CLASSIFICATION_HASH_MISMATCH",
            "Classification accepted-content hash does not match Approved Continuity.",
            details={"commit_id": commit_id},
        )

    final_state = str(value.get("final_segment_state") or "").strip()
    if not final_state:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_CLASSIFICATION_STATE_REQUIRED",
            "Classified ledger entry has no final_segment_state.",
            details={"commit_id": commit_id},
        )
    hccs = value.get("hccs")
    if isinstance(hccs, bool) or not isinstance(hccs, (int, float)):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_HCCS_INVALID",
            "Classified ledger entry has an invalid HCCS value.",
            details={"commit_id": commit_id},
        )
    if float(hccs) < 0.0 or float(hccs) > 100.0:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_HCCS_INVALID",
            "Classified ledger entry HCCS is outside 0-100.",
            details={"commit_id": commit_id},
        )

    service = _required_id(value.get("service"), "classification service")
    schema_version = _required_id(
        value.get("schema_version"),
        "classification schema_version",
    )
    return {
        "service": service,
        "schema_version": schema_version,
        "assessment_status": "classified",
        "final_segment_state": final_state,
        "hccs": float(hccs),
        "accepted_version_id": accepted_version_id,
        "accepted_content_sha256": accepted_content_sha256,
        "evidence_confidence": deepcopy(value.get("evidence_confidence")),
        "awarded_level": deepcopy(value.get("awarded_level")),
    }


def _lineage_evidence(
    records: Any,
    *,
    generation_id: str,
    segment_id: str,
    accepted_version_id: str,
    accepted_content_sha256: str,
    author_accept_event_id: str,
    commit_id: str,
) -> dict[str, Any]:
    if not isinstance(records, dict) or str(records.get("status") or "") != "ok":
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_LINEAGE_UNAVAILABLE",
            "Accepted manuscript lineage cannot be loaded.",
            details={"commit_id": commit_id},
        )

    origins = list(records.get("origins") or [])
    if len(origins) != 1 or not isinstance(origins[0], dict):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_ORIGIN_NOT_UNIQUE",
            "Each accepted ledger entry requires exactly one immutable origin.",
            details={"commit_id": commit_id, "origin_count": len(origins)},
        )
    origin = origins[0]
    if str(origin.get("generation_id") or "") != generation_id:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_ORIGIN_GENERATION_MISMATCH",
            "Origin generation_id does not match Approved Continuity.",
            details={"commit_id": commit_id},
        )
    if str(origin.get("segment_id") or "") != segment_id:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_ORIGIN_SEGMENT_MISMATCH",
            "Origin segment_id does not match Approved Continuity.",
            details={"commit_id": commit_id},
        )
    if origin.get("immutable") is not True:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_ORIGIN_NOT_IMMUTABLE",
            "Ledger evidence requires an immutable origin snapshot.",
            details={"commit_id": commit_id},
        )
    origin_content = str(origin.get("content") or "")
    origin_content_hash = _required_sha256(
        origin.get("content_hash"),
        "origin content_hash",
    )
    if _sha256_text(origin_content) != origin_content_hash:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_ORIGIN_HASH_MISMATCH",
            "Immutable origin content does not match its provenance SHA-256.",
            details={"commit_id": commit_id},
        )

    events = list(records.get("events") or [])
    terminal = next(
        (
            event
            for event in events
            if isinstance(event, dict)
            and str(event.get("event_id") or "") == author_accept_event_id
        ),
        None,
    )
    if terminal is None:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_AUTHOR_ACCEPT_EVENT_MISSING",
            "Approved Continuity references an AUTHOR_ACCEPT event absent from provenance.",
            details={"commit_id": commit_id},
        )
    if str(terminal.get("operation") or "") != "AUTHOR_ACCEPT":
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_TERMINAL_OPERATION_INVALID",
            "Referenced terminal provenance event is not AUTHOR_ACCEPT.",
            details={"commit_id": commit_id},
        )
    if str(terminal.get("version_id") or "") != accepted_version_id:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_TERMINAL_VERSION_MISMATCH",
            "AUTHOR_ACCEPT version does not match Approved Continuity.",
            details={"commit_id": commit_id},
        )
    terminal_hash = _required_sha256(
        terminal.get("after_hash"),
        "AUTHOR_ACCEPT after_hash",
    )
    if terminal_hash != accepted_content_sha256:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_TERMINAL_HASH_MISMATCH",
            "AUTHOR_ACCEPT hash does not match Approved Continuity.",
            details={"commit_id": commit_id},
        )

    origin_evidence = {
        "origin_id": _required_id(origin.get("origin_id"), "origin_id"),
        "version_id": _required_id(origin.get("version_id"), "origin version_id"),
        "origin_actor": _required_id(origin.get("origin_actor"), "origin_actor"),
        "provider": str(origin.get("provider") or ""),
        "provider_model": str(origin.get("provider_model") or ""),
        "content_hash": origin_content_hash,
        "immutable": True,
    }
    sanitized_events: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise AuthorshipLedgerError(
                "AUTHORSHIP_LEDGER_EVENT_INVALID",
                "Provenance contains a non-object event.",
                details={"commit_id": commit_id, "event_index": index},
            )
        event_id = _required_id(event.get("event_id"), "event_id")
        version_id = _required_id(event.get("version_id"), "event version_id")
        actor = _required_id(event.get("actor"), "event actor")
        operation = _required_id(event.get("operation"), "event operation")
        after_hash = _required_sha256(event.get("after_hash"), "event after_hash")
        content_after = event.get("content_after")
        if content_after is not None and _sha256_text(str(content_after)) != after_hash:
            raise AuthorshipLedgerError(
                "AUTHORSHIP_LEDGER_EVENT_HASH_MISMATCH",
                "Persisted provenance event content does not match after_hash.",
                details={"commit_id": commit_id, "event_id": event_id},
            )
        parent_ids = [
            str(item)
            for item in (event.get("parent_version_ids") or [])
            if str(item).strip()
        ]
        sanitized_events.append(
            {
                "event_id": event_id,
                "version_id": version_id,
                "actor": actor,
                "operation": operation,
                "parent_version_ids": parent_ids,
                "before_hash": str(event.get("before_hash") or ""),
                "after_hash": after_hash,
                "source_generation_id": str(event.get("source_generation_id") or ""),
            }
        )

    return {
        "origin": origin_evidence,
        "events": sanitized_events,
    }


def _build_book_summaries(
    entries: list[dict[str, Any]],
    manuscript_material: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_book: dict[int, list[int]] = {}
    for index, entry in enumerate(entries):
        by_book.setdefault(int(entry["book_number"]), []).append(index)

    summaries: list[dict[str, Any]] = []
    for book_number in sorted(by_book):
        indexes = by_book[book_number]
        book_entries = [entries[index] for index in indexes]
        book_material = [manuscript_material[index] for index in indexes]
        summaries.append(
            {
                "book_number": book_number,
                "entry_count": len(book_entries),
                "chapter_numbers": sorted(
                    {int(item["chapter_number"]) for item in book_entries}
                ),
                "manuscript_sha256": _json_sha256(book_material),
                "classification_summary": _classification_summary(book_entries),
            }
        )
    return summaries


def _classification_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    states: dict[str, int] = {}
    levels: dict[str, int] = {}
    for entry in entries:
        classification = entry.get("classification") or {}
        state = str(classification.get("final_segment_state") or "")
        states[state] = states.get(state, 0) + 1
        awarded = classification.get("awarded_level")
        level_key = _awarded_level_key(awarded)
        levels[level_key] = levels.get(level_key, 0) + 1
    return {
        "classified_entry_count": len(entries),
        "final_segment_state_counts": dict(sorted(states.items())),
        "awarded_level_counts": dict(sorted(levels.items())),
        "hccs_aggregation": "none; per-entry HCCS retained as internal provenance evidence",
    }


def _awarded_level_key(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("level", "number", "value"):
            raw = value.get(key)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        name = str(value.get("name") or "").strip()
        if name:
            return name
    if value is None:
        return "none"
    text = str(value).strip()
    return text or "none"


def _load_ledger(path: Path, *, project_id: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_DOCUMENT_INVALID",
            "Authorship ledger cannot be read.",
            details={"error": str(exc)},
        ) from exc
    if not isinstance(payload, dict):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_DOCUMENT_INVALID",
            "Authorship ledger root must be an object.",
        )
    if payload.get("schema_version") != AUTHORSHIP_LEDGER_SCHEMA_VERSION:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_SCHEMA_MISMATCH",
            f"schema_version must be {AUTHORSHIP_LEDGER_SCHEMA_VERSION}.",
        )
    if str(payload.get("service") or "") != AUTHORSHIP_LEDGER_SERVICE_MARKER:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_SERVICE_MISMATCH",
            "Authorship ledger service marker is invalid.",
        )
    if str(payload.get("project_id") or "") != project_id:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_PROJECT_MISMATCH",
            "Authorship ledger belongs to another project.",
        )
    revision = payload.get("ledger_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_REVISION_INVALID",
            "ledger_revision must be a positive integer.",
        )
    entries = payload.get("entries")
    books = payload.get("books")
    if not isinstance(entries, list) or not isinstance(books, list):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_DOCUMENT_INVALID",
            "entries and books must be lists.",
        )
    if int(payload.get("entry_count") or 0) != len(entries):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_ENTRY_COUNT_MISMATCH",
            "entry_count does not match persisted entries.",
        )
    if int(payload.get("book_count") or 0) != len(books):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_BOOK_COUNT_MISMATCH",
            "book_count does not match persisted books.",
        )
    _required_sha256(payload.get("source_fingerprint"), "source_fingerprint")
    _required_sha256(payload.get("manuscript_sha256"), "manuscript_sha256")
    stored_hash = _required_sha256(payload.get("content_hash"), "content_hash")
    actual_hash = _ledger_content_hash(payload)
    if stored_hash != actual_hash:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_INTEGRITY_MISMATCH",
            "Authorship ledger content_hash does not match persisted content.",
        )
    return deepcopy(payload)


def _ledger_content_hash(payload: dict[str, Any]) -> str:
    normalized = deepcopy(payload)
    normalized.pop("content_hash", None)
    return _json_sha256(normalized)


def _json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required_id(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_IDENTITY_REQUIRED",
            f"{field} is required.",
        )
    return text


def _required_sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(text) is None:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_SHA256_INVALID",
            f"{field} must be a lowercase SHA-256 value.",
        )
    return text


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_POSITION_INVALID",
            f"{field} must be a positive integer.",
        )
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_POSITION_INVALID",
            f"{field} must be a positive integer.",
        ) from exc
    if number < 1:
        raise AuthorshipLedgerError(
            "AUTHORSHIP_LEDGER_POSITION_INVALID",
            f"{field} must be a positive integer.",
        )
    return number


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@contextmanager
def _write_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(AUTHORSHIP_LEDGER_WRITE_LOCK_FILENAME)
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
                raise AuthorshipLedgerError(
                    "AUTHORSHIP_LEDGER_WRITE_LOCKED",
                    "Authorship ledger is locked by another writer.",
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
    data = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)
