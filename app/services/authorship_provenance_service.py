"""
Project-local authorship provenance storage and lineage foundation.

Patch 28 establishes the provenance domain before provider execution is migrated.
It records immutable origin snapshots and actor-specific transformation lineage.
It does not score authorship, make legal/copyright determinations, call providers,
build prompts, validate prose, approve prose, write Approved Continuity, update
Author Voice, or unlock generation.

Authoritative persistence:
    provenance/origins/*.json        immutable origin snapshots
    provenance/provenance_events.jsonl
                                    append-only transformation/state events

Derived/rebuildable persistence:
    provenance/segment_lineage.json lineage graph/index rebuilt from origins/events

Future chapter scoring/ledger work remains outside this patch.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator
import uuid

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso


AUTHORSHIP_PROVENANCE_SERVICE_MARKER = "project-authorship-provenance-v1-20260817"
PROVENANCE_SCHEMA_VERSION = "authorship_provenance_v1"
ORIGIN_SCHEMA_VERSION = "provenance_origin_v1"
LINEAGE_SCHEMA_VERSION = "provenance_lineage_v1"
EVENT_SCHEMA_VERSION = "provenance_event_v1"
CHAPTER_STATUS_SCHEMA_VERSION = "chapter_provenance_status_v1"

PROVENANCE_DIRECTORY = "provenance"
ORIGINS_DIRECTORY = "origins"
CHAPTER_PROVENANCE_DIRECTORY = "chapter_provenance"
DOMAIN_MANIFEST_FILENAME = "domain_manifest.json"
EVENT_LOG_FILENAME = "provenance_events.jsonl"
LINEAGE_INDEX_FILENAME = "segment_lineage.json"
WRITE_LOCK_FILENAME = ".write.lock"

HASH_ALGORITHM = "sha256:utf8_exact_v1"
LOCK_TIMEOUT_SECONDS = 5.0
STALE_LOCK_SECONDS = 300.0

ACTOR_AUTHOR = "AUTHOR"
ACTOR_MODEL = "MODEL"
ACTOR_SYSTEM_DETERMINISTIC = "SYSTEM_DETERMINISTIC"
ACTOR_EXTERNAL_AUTHOR_ATTESTED = "EXTERNAL_AUTHOR_ATTESTED"

ACTOR_TYPES = frozenset(
    {
        ACTOR_AUTHOR,
        ACTOR_MODEL,
        ACTOR_SYSTEM_DETERMINISTIC,
        ACTOR_EXTERNAL_AUTHOR_ATTESTED,
    }
)

EVENT_TYPES = frozenset(
    {
        "AUTHOR_INSERT",
        "AUTHOR_DELETE",
        "AUTHOR_REPLACE",
        "AUTHOR_MOVE",
        "AUTHOR_SPLIT",
        "AUTHOR_MERGE",
        "AUTHOR_EDIT",
        "MODEL_GENERATE",
        "MODEL_REGENERATE",
        "MODEL_REWRITE",
        "MODEL_COPYEDIT",
        "SYSTEM_FORMAT",
        "SYSTEM_NORMALIZE",
        "AUTHOR_REJECT",
        "AUTHOR_ACCEPT",
    }
)

_STATE_ONLY_OR_STRUCTURAL_EVENTS = frozenset(
    {
        "AUTHOR_MOVE",
        "AUTHOR_REJECT",
        "AUTHOR_ACCEPT",
    }
)


class AuthorshipProvenanceError(RuntimeError):
    """Base error for project-local provenance operations."""


class AuthorshipProvenanceContractError(AuthorshipProvenanceError):
    """Raised when provenance input or persisted state violates the contract."""


class ImmutableOriginConflictError(AuthorshipProvenanceError):
    """Raised when a caller attempts to replace an existing immutable origin."""


class ProvenanceLineageError(AuthorshipProvenanceError):
    """Raised when a lineage graph operation is structurally invalid."""


class ProvenanceWriteLockError(AuthorshipProvenanceError):
    """Raised when provenance storage cannot obtain its bounded write lock."""


def get_provenance_contract() -> dict[str, Any]:
    """Return the Patch-28 provenance vocabulary and locked boundaries."""

    return {
        "status": "ok",
        "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
        "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "origin_schema_version": ORIGIN_SCHEMA_VERSION,
        "lineage_schema_version": LINEAGE_SCHEMA_VERSION,
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "chapter_status_schema_version": CHAPTER_STATUS_SCHEMA_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "actor_types": sorted(ACTOR_TYPES),
        "event_types": sorted(EVENT_TYPES),
        "storage_contract": {
            "domain": f"{PROVENANCE_DIRECTORY}/{DOMAIN_MANIFEST_FILENAME}",
            "origins": f"{PROVENANCE_DIRECTORY}/{ORIGINS_DIRECTORY}/<origin_id>.json",
            "events": f"{PROVENANCE_DIRECTORY}/{EVENT_LOG_FILENAME}",
            "lineage": f"{PROVENANCE_DIRECTORY}/{LINEAGE_INDEX_FILENAME}",
            "chapter_status_shell": (
                f"{PROVENANCE_DIRECTORY}/{CHAPTER_PROVENANCE_DIRECTORY}/"
                "book_<NN>_chapter_<NNN>.json"
            ),
            "origin_mutability": "immutable_create_once",
            "event_mutability": "append_only",
            "lineage_mutability": "derived_rebuildable_index",
        },
        "authority": {
            "records_observed_origin_and_transformation_history": True,
            "scores_authorship": False,
            "declares_legal_copyrightability": False,
            "decides_story_legality": False,
            "writes_approved_continuity": False,
            "updates_author_voice": False,
            "calls_provider": False,
            "unlocks_generation": False,
        },
    }


def provenance_root(project_id: str) -> Path:
    manifest = project_loader.load_manifest(project_id)
    return provenance_root_for_context(build_project_context(manifest))


def provenance_root_for_context(context: ProjectContext) -> Path:
    root = (context.project_dir / PROVENANCE_DIRECTORY).resolve()
    project_dir = context.project_dir.resolve()
    if project_dir not in root.parents:
        raise project_loader.InvalidProjectIdError(
            "provenance path escapes project directory"
        )
    if root.name != PROVENANCE_DIRECTORY:
        raise project_loader.InvalidProjectIdError(
            "provenance path does not target the project provenance directory"
        )
    return root


def ensure_provenance_storage(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return ensure_provenance_storage_for_context(context)


def ensure_provenance_storage_for_context(
    context: ProjectContext,
) -> dict[str, Any]:
    """Create the bounded project-local provenance domain without overwriting evidence."""

    root = provenance_root_for_context(context)
    root.mkdir(parents=True, exist_ok=True)
    (root / ORIGINS_DIRECTORY).mkdir(parents=True, exist_ok=True)
    (root / CHAPTER_PROVENANCE_DIRECTORY).mkdir(parents=True, exist_ok=True)

    manifest_path = root / DOMAIN_MANIFEST_FILENAME
    if manifest_path.exists():
        manifest = _read_json_object(manifest_path, "provenance domain manifest")
        _validate_domain_manifest(context, manifest)
    else:
        _write_json_exclusive(
            manifest_path,
            {
                "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
                "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
                "project_id": context.project_id,
                "created_at": utc_now_iso(),
                "hash_algorithm": HASH_ALGORITHM,
                "actor_types": sorted(ACTOR_TYPES),
                "event_types": sorted(EVENT_TYPES),
                "source_of_truth": {
                    "origins": "immutable_files",
                    "events": "append_only_jsonl",
                    "lineage": "derived_rebuildable_index",
                },
            },
        )

    events_path = root / EVENT_LOG_FILENAME
    if not events_path.exists():
        _write_bytes_exclusive(events_path, b"")

    lineage_path = root / LINEAGE_INDEX_FILENAME
    if not lineage_path.exists():
        _write_json_exclusive(
            lineage_path,
            _empty_lineage_document(context.project_id),
        )

    # Validate authoritative sources first. If only the derived index is stale,
    # rebuild it from immutable origins and append-only events.
    origins = _load_origin_records(context)
    events = _load_event_records(context)
    lineage = _load_lineage_document(context)
    if not _lineage_matches_sources(lineage, origins, events):
        recover_lineage_index_for_context(context)
    else:
        _validate_lineage_document(context, lineage, origins=origins, events=events)

    return get_provenance_status_for_context(context)


def get_provenance_status(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_provenance_status_for_context(context)


def get_provenance_status_for_context(
    context: ProjectContext,
) -> dict[str, Any]:
    """Return read-only provenance-domain readiness and integrity status."""

    root = provenance_root_for_context(context)
    manifest_path = root / DOMAIN_MANIFEST_FILENAME
    event_path = root / EVENT_LOG_FILENAME
    lineage_path = root / LINEAGE_INDEX_FILENAME
    origins_dir = root / ORIGINS_DIRECTORY
    chapter_dir = root / CHAPTER_PROVENANCE_DIRECTORY

    required = {
        "domain_manifest": manifest_path.is_file(),
        "origins_directory": origins_dir.is_dir(),
        "event_log": event_path.is_file(),
        "lineage_index": lineage_path.is_file(),
        "chapter_status_directory": chapter_dir.is_dir(),
    }
    initialized = all(required.values())

    origin_count = 0
    event_count = 0
    version_count = 0
    segment_count = 0
    integrity_status = "not_initialized"
    integrity_error = ""

    if initialized:
        try:
            manifest = _read_json_object(manifest_path, "provenance domain manifest")
            _validate_domain_manifest(context, manifest)
            origins = _load_origin_records(context)
            events = _load_event_records(context)
            lineage = _load_lineage_document(context)
            _validate_lineage_document(
                context,
                lineage,
                origins=origins,
                events=events,
            )
            if not _lineage_matches_sources(lineage, origins, events):
                integrity_status = "recovery_required"
                integrity_error = (
                    "Derived lineage index does not match immutable origin/event sources."
                )
            else:
                integrity_status = "ok"
            origin_count = len(origins)
            event_count = len(events)
            version_count = len(lineage.get("versions") or {})
            segment_count = len(lineage.get("segments") or {})
        except (OSError, ValueError, json.JSONDecodeError, AuthorshipProvenanceError) as exc:
            integrity_status = "error"
            integrity_error = str(exc)

    capture_ready = bool(initialized and integrity_status == "ok")

    return {
        "status": "ok",
        "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
        "project_id": context.project_id,
        "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "storage_root": _relative_project_path(context, root),
        "initialized": initialized,
        "required_storage": required,
        "integrity_status": integrity_status,
        "integrity_error": integrity_error,
        "origin_count": origin_count,
        "event_count": event_count,
        "version_count": version_count,
        "segment_count": segment_count,
        "provenance_capture_ready": capture_ready,
        "provider_origin_wiring_ready": False,
        "review_lineage_wiring_ready": False,
        "chapter_scoring_ready": False,
        "ledger_ready": False,
        "generation_unlocked": False,
        "execution_locks": _execution_locks(),
        "message": (
            "Authorship provenance storage and lineage capture are ready."
            if capture_ready
            else "Authorship provenance storage requires initialization or recovery."
        ),
    }


def get_chapter_provenance_status(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_chapter_provenance_status_for_context(
        context,
        book_number=book_number,
        chapter_number=chapter_number,
    )


def get_chapter_provenance_status_for_context(
    context: ProjectContext,
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    """Return the non-scoring chapter provenance status shell."""

    book = _positive_int(book_number, "book_number")
    chapter = _positive_int(chapter_number, "chapter_number")
    root = provenance_root_for_context(context)
    if not root.exists():
        return {
            "status": "not_initialized",
            "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
            "schema_version": CHAPTER_STATUS_SCHEMA_VERSION,
            "project_id": context.project_id,
            "book_number": book,
            "chapter_number": chapter,
            "tracking_state": "not_started",
            "assessment_status": "not_scored_patch_28",
            "scoring_enabled": False,
            "origin_count": 0,
            "event_count": 0,
            "version_count": 0,
            "accepted_event_count": 0,
            "rejected_event_count": 0,
            "execution_locks": _execution_locks(),
        }

    origins = [
        item
        for item in _load_origin_records(context)
        if _same_position(item, book_number=book, chapter_number=chapter)
    ]
    events = [
        item
        for item in _load_event_records(context)
        if _same_position(item, book_number=book, chapter_number=chapter)
    ]
    lineage = _load_lineage_document(context)
    version_ids = {
        str(item.get("version_id") or "")
        for item in origins + events
        if item.get("version_id")
    }
    versions = [
        deepcopy((lineage.get("versions") or {}).get(version_id))
        for version_id in sorted(version_ids)
        if version_id in (lineage.get("versions") or {})
    ]

    accepted_count = sum(
        1 for item in events if item.get("operation") == "AUTHOR_ACCEPT"
    )
    rejected_count = sum(
        1 for item in events if item.get("operation") == "AUTHOR_REJECT"
    )

    if accepted_count:
        tracking_state = "accepted_pending_assessment"
    elif rejected_count and not origins:
        tracking_state = "rejected_lineage_retained"
    elif rejected_count:
        tracking_state = "tracking_with_rejected_branch"
    elif origins or events:
        tracking_state = "tracking"
    else:
        tracking_state = "not_started"

    return {
        "status": "ok",
        "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
        "schema_version": CHAPTER_STATUS_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book,
        "chapter_number": chapter,
        "tracking_state": tracking_state,
        "assessment_status": "not_scored_patch_28",
        "scoring_enabled": False,
        "origin_count": len(origins),
        "event_count": len(events),
        "version_count": len(versions),
        "accepted_event_count": accepted_count,
        "rejected_event_count": rejected_count,
        "versions": versions,
        "execution_locks": _execution_locks(),
    }


def register_origin_snapshot(
    project_id: str,
    *,
    generation_id: str,
    segment_id: str,
    origin_actor: str,
    content: str,
    provider: str = "",
    provider_model: str = "",
    parent_ids: list[str] | None = None,
    book_number: int | None = None,
    chapter_number: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return register_origin_snapshot_for_context(
        context,
        generation_id=generation_id,
        segment_id=segment_id,
        origin_actor=origin_actor,
        content=content,
        provider=provider,
        provider_model=provider_model,
        parent_ids=parent_ids,
        book_number=book_number,
        chapter_number=chapter_number,
        metadata=metadata,
    )


def register_origin_snapshot_for_context(
    context: ProjectContext,
    *,
    generation_id: str,
    segment_id: str,
    origin_actor: str,
    content: str,
    provider: str = "",
    provider_model: str = "",
    parent_ids: list[str] | None = None,
    book_number: int | None = None,
    chapter_number: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist an immutable origin snapshot and its initial lineage version.

    The same generation_id + segment_id may be retried only when the immutable
    identity and content are identical. A differing retry is rejected.
    """

    generation = _required_identifier(generation_id, "generation_id")
    segment = _required_identifier(segment_id, "segment_id")
    actor = _validate_actor(origin_actor)
    text = _content_text(content)
    provider_name = str(provider or "").strip()
    model_name = str(provider_model or "").strip()
    parents = _clean_id_list(parent_ids or [], "parent_ids")
    position = _position_payload(book_number, chapter_number)
    safe_metadata = _metadata_object(metadata)

    if actor == ACTOR_MODEL and not provider_name:
        raise AuthorshipProvenanceContractError(
            "MODEL origin requires provider."
        )
    if actor != ACTOR_MODEL and (provider_name or model_name):
        raise AuthorshipProvenanceContractError(
            "provider/provider_model are valid only for MODEL origin."
        )

    ensure_provenance_storage_for_context(context)
    root = provenance_root_for_context(context)

    with _provenance_write_lock(root):
        origins = _load_origin_records(context)
        duplicate = next(
            (
                item
                for item in origins
                if str(item.get("generation_id") or "") == generation
                and str(item.get("segment_id") or "") == segment
            ),
            None,
        )
        content_hash = hash_text(text)

        if duplicate is not None:
            immutable_matches = (
                str(duplicate.get("origin_actor") or "") == actor
                and str(duplicate.get("content_hash") or "") == content_hash
                and str(duplicate.get("provider") or "") == provider_name
                and str(duplicate.get("provider_model") or "") == model_name
                and list(duplicate.get("parent_ids") or []) == parents
            )
            if immutable_matches:
                return {
                    "status": "already_registered",
                    "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
                    "project_id": context.project_id,
                    "origin": deepcopy(duplicate),
                    "immutable": True,
                    "execution_locks": _execution_locks(),
                }
            raise ImmutableOriginConflictError(
                "Immutable origin already exists for this generation_id + segment_id."
            )

        lineage = _load_lineage_document(context)
        _validate_parent_versions(lineage, parents)

        origin_id = "origin_" + uuid.uuid4().hex
        version_id = "version_" + uuid.uuid4().hex
        record = {
            "schema_version": ORIGIN_SCHEMA_VERSION,
            "origin_id": origin_id,
            "version_id": version_id,
            "generation_id": generation,
            "segment_id": segment,
            "origin_actor": actor,
            "provider": provider_name,
            "provider_model": model_name,
            "created_at": utc_now_iso(),
            "hash_algorithm": HASH_ALGORITHM,
            "content_hash": content_hash,
            "content": text,
            "parent_ids": parents,
            "book_number": position["book_number"],
            "chapter_number": position["chapter_number"],
            "metadata": safe_metadata,
            "immutable": True,
        }

        origin_path = root / ORIGINS_DIRECTORY / f"{origin_id}.json"
        _write_json_exclusive(origin_path, record)

        try:
            recover_lineage_index_for_context(context)
        except Exception:
            # The immutable origin is authoritative evidence. Never delete it
            # because a rebuildable derived index failed.
            raise

    return {
        "status": "registered",
        "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
        "project_id": context.project_id,
        "origin": deepcopy(record),
        "immutable": True,
        "execution_locks": _execution_locks(),
    }


def record_lineage_event(
    project_id: str,
    *,
    segment_id: str,
    actor: str,
    operation: str,
    content_after: str,
    parent_version_ids: list[str],
    content_before: str | None = None,
    source_generation_id: str = "",
    book_number: int | None = None,
    chapter_number: int | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    version_id: str | None = None,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return record_lineage_event_for_context(
        context,
        segment_id=segment_id,
        actor=actor,
        operation=operation,
        content_after=content_after,
        parent_version_ids=parent_version_ids,
        content_before=content_before,
        source_generation_id=source_generation_id,
        book_number=book_number,
        chapter_number=chapter_number,
        metadata=metadata,
        event_id=event_id,
        version_id=version_id,
    )


def record_lineage_event_for_context(
    context: ProjectContext,
    *,
    segment_id: str,
    actor: str,
    operation: str,
    content_after: str,
    parent_version_ids: list[str],
    content_before: str | None = None,
    source_generation_id: str = "",
    book_number: int | None = None,
    chapter_number: int | None = None,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    version_id: str | None = None,
) -> dict[str, Any]:
    """Append one actor-specific provenance event and rebuild the lineage index."""

    segment = _required_identifier(segment_id, "segment_id")
    actor_value = _validate_actor(actor)
    operation_value = _validate_operation(operation)
    _validate_actor_operation(actor_value, operation_value)
    parents = _clean_id_list(parent_version_ids, "parent_version_ids")
    if not parents:
        raise AuthorshipProvenanceContractError(
            "parent_version_ids is required for lineage events; "
            "use register_origin_snapshot() to create an origin."
        )
    after_text = _content_text(content_after)
    safe_metadata = _metadata_object(metadata)
    position = _position_payload(book_number, chapter_number)

    ensure_provenance_storage_for_context(context)
    root = provenance_root_for_context(context)

    with _provenance_write_lock(root):
        lineage = _load_lineage_document(context)
        parent_versions = _validate_parent_versions(lineage, parents)

        parent_before_hash = _before_hash_from_parents(parent_versions)
        if content_before is not None:
            supplied_before_hash = hash_text(_content_text(content_before))
            if supplied_before_hash != parent_before_hash:
                raise ProvenanceLineageError(
                    "content_before does not match the recorded parent lineage."
                )
        before_hash = parent_before_hash
        after_hash = hash_text(after_text)

        if (
            before_hash == after_hash
            and operation_value not in _STATE_ONLY_OR_STRUCTURAL_EVENTS
        ):
            return {
                "status": "no_op",
                "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
                "project_id": context.project_id,
                "segment_id": segment,
                "actor": actor_value,
                "operation": operation_value,
                "before_hash": before_hash,
                "after_hash": after_hash,
                "event_recorded": False,
                "reason": "content hash unchanged; repeated save is not authorship evidence",
                "execution_locks": _execution_locks(),
            }

        supplied_event_id = (
            _required_identifier(event_id, "event_id")
            if event_id is not None
            else "event_" + uuid.uuid4().hex
        )
        supplied_version_id = (
            _required_identifier(version_id, "version_id")
            if version_id is not None
            else "version_" + uuid.uuid4().hex
        )

        existing_events = _load_event_records(context)
        existing_event = next(
            (
                item
                for item in existing_events
                if str(item.get("event_id") or "") == supplied_event_id
            ),
            None,
        )
        if existing_event is not None:
            if (
                str(existing_event.get("version_id") or "") == supplied_version_id
                and str(existing_event.get("segment_id") or "") == segment
                and str(existing_event.get("actor") or "") == actor_value
                and str(existing_event.get("operation") or "") == operation_value
                and list(existing_event.get("parent_version_ids") or []) == parents
                and str(existing_event.get("after_hash") or "") == after_hash
            ):
                return {
                    "status": "already_recorded",
                    "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
                    "project_id": context.project_id,
                    "event": deepcopy(existing_event),
                    "event_recorded": False,
                    "execution_locks": _execution_locks(),
                }
            raise ProvenanceLineageError(
                f"event_id already exists with different immutable evidence: {supplied_event_id}"
            )

        if supplied_version_id in (lineage.get("versions") or {}):
            raise ProvenanceLineageError(
                f"version_id already exists: {supplied_version_id}"
            )

        event = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": supplied_event_id,
            "version_id": supplied_version_id,
            "segment_id": segment,
            "parent_version_ids": parents,
            "actor": actor_value,
            "operation": operation_value,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "hash_algorithm": HASH_ALGORITHM,
            "timestamp": utc_now_iso(),
            "source_generation_id": str(source_generation_id or "").strip(),
            "book_number": position["book_number"],
            "chapter_number": position["chapter_number"],
            "metadata": safe_metadata,
        }

        _append_jsonl(root / EVENT_LOG_FILENAME, event)
        try:
            recover_lineage_index_for_context(context)
        except Exception:
            # The append-only event log is authoritative and intentionally
            # retained. Recovery can rebuild the derived graph later.
            raise

    return {
        "status": "recorded",
        "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
        "project_id": context.project_id,
        "event": deepcopy(event),
        "event_recorded": True,
        "execution_locks": _execution_locks(),
    }


def recover_lineage_index(project_id: str) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return recover_lineage_index_for_context(context)


def recover_lineage_index_for_context(
    context: ProjectContext,
) -> dict[str, Any]:
    """Rebuild the derived lineage graph from immutable origins + append-only events."""

    root = provenance_root_for_context(context)
    if not root.exists():
        raise AuthorshipProvenanceContractError(
            "provenance storage is not initialized."
        )
    origins = _load_origin_records(context)
    events = _load_event_records(context)
    document = _build_lineage_document(
        context,
        origins=origins,
        events=events,
    )
    _write_json_atomic(root / LINEAGE_INDEX_FILENAME, document)
    return {
        "status": "rebuilt",
        "service": AUTHORSHIP_PROVENANCE_SERVICE_MARKER,
        "project_id": context.project_id,
        "origin_count": len(origins),
        "event_count": len(events),
        "version_count": len(document["versions"]),
        "segment_count": len(document["segments"]),
        "lineage_hash": document["content_hash"],
    }


def hash_text(content: str) -> str:
    text = _content_text(content)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_lineage_document(
    context: ProjectContext,
    *,
    origins: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a DAG index without assuming that all origins precede all events.

    A regeneration origin may branch from an earlier transformation version, so
    parent resolution is topological across both immutable origins and events.
    """

    versions: dict[str, dict[str, Any]] = {}
    segments: dict[str, dict[str, Any]] = {}
    pending: dict[str, dict[str, Any]] = {}

    for origin in origins:
        _validate_origin_record(context, origin)
        version_id = str(origin["version_id"])
        if version_id in pending:
            raise ProvenanceLineageError(
                f"Duplicate provenance version_id: {version_id}"
            )
        pending[version_id] = {
            "kind": "origin",
            "sort_key": (
                str(origin.get("created_at") or ""),
                str(origin.get("origin_id") or ""),
            ),
            "source": origin,
            "parent_version_ids": list(origin.get("parent_ids") or []),
        }

    for sequence, event in enumerate(events):
        _validate_event_record(context, event)
        version_id = str(event["version_id"])
        if version_id in pending:
            raise ProvenanceLineageError(
                f"Duplicate provenance version_id: {version_id}"
            )
        pending[version_id] = {
            "kind": "event",
            "sort_key": (
                str(event.get("timestamp") or ""),
                f"{sequence:012d}",
                str(event.get("event_id") or ""),
            ),
            "source": event,
            "parent_version_ids": list(event.get("parent_version_ids") or []),
        }

    all_version_ids = set(pending)
    for version_id, node in pending.items():
        missing = [
            parent
            for parent in node["parent_version_ids"]
            if parent not in all_version_ids
        ]
        if missing:
            raise ProvenanceLineageError(
                f"Version {version_id} references unknown parent version(s): "
                + ", ".join(missing)
            )

    unresolved = dict(pending)
    while unresolved:
        ready = [
            (version_id, node)
            for version_id, node in unresolved.items()
            if all(parent in versions for parent in node["parent_version_ids"])
        ]
        if not ready:
            raise ProvenanceLineageError(
                "Provenance lineage contains a cycle or unresolvable parent dependency."
            )

        for version_id, node in sorted(
            ready,
            key=lambda item: (item[1]["sort_key"], item[0]),
        ):
            source = node["source"]
            parents = list(node["parent_version_ids"])

            if node["kind"] == "origin":
                segment_id = str(source["segment_id"])
                version = {
                    "version_id": version_id,
                    "segment_id": segment_id,
                    "parent_version_ids": parents,
                    "actor": str(source["origin_actor"]),
                    "operation": "ORIGIN_CAPTURE",
                    "before_hash": _before_hash_from_parent_ids(
                        versions,
                        parents,
                    ),
                    "after_hash": str(source["content_hash"]),
                    "timestamp": str(source["created_at"]),
                    "source_generation_id": str(source["generation_id"]),
                    "origin_id": str(source["origin_id"]),
                    "book_number": source.get("book_number"),
                    "chapter_number": source.get("chapter_number"),
                }
                versions[version_id] = version
                _append_segment_version(
                    segments,
                    segment_id,
                    version_id,
                    origin_id=str(source["origin_id"]),
                )
            else:
                segment_id = str(source["segment_id"])
                expected_before_hash = _before_hash_from_parent_ids(
                    versions,
                    parents,
                )
                recorded_before_hash = str(source["before_hash"])
                # For one-parent transformations, before_hash must match the
                # recorded parent state. For multi-parent merge/recombine
                # operations, the canonical combined-parent hash is required.
                if recorded_before_hash != expected_before_hash:
                    raise ProvenanceLineageError(
                        f"Event {source['event_id']} before_hash does not match parent lineage."
                    )
                version = {
                    "version_id": version_id,
                    "segment_id": segment_id,
                    "parent_version_ids": parents,
                    "actor": str(source["actor"]),
                    "operation": str(source["operation"]),
                    "before_hash": recorded_before_hash,
                    "after_hash": str(source["after_hash"]),
                    "timestamp": str(source["timestamp"]),
                    "source_generation_id": str(
                        source.get("source_generation_id") or ""
                    ),
                    "event_id": str(source["event_id"]),
                    "book_number": source.get("book_number"),
                    "chapter_number": source.get("chapter_number"),
                }
                versions[version_id] = version
                _append_segment_version(
                    segments,
                    segment_id,
                    version_id,
                )

            unresolved.pop(version_id)

    payload = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "project_id": context.project_id,
        "hash_algorithm": HASH_ALGORITHM,
        "source_origin_count": len(origins),
        "source_event_count": len(events),
        "versions": versions,
        "segments": segments,
    }
    payload["content_hash"] = _hash_canonical_json(payload)
    return payload


def _append_segment_version(
    segments: dict[str, dict[str, Any]],
    segment_id: str,
    version_id: str,
    *,
    origin_id: str = "",
) -> None:
    entry = segments.setdefault(
        segment_id,
        {
            "segment_id": segment_id,
            "version_ids": [],
            "origin_ids": [],
        },
    )
    entry["version_ids"].append(version_id)
    if origin_id:
        entry["origin_ids"].append(origin_id)


def _validate_domain_manifest(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> None:
    if manifest.get("provenance_schema_version") != PROVENANCE_SCHEMA_VERSION:
        raise AuthorshipProvenanceContractError(
            "Unsupported provenance domain schema."
        )
    if str(manifest.get("project_id") or "") != context.project_id:
        raise AuthorshipProvenanceContractError(
            "Provenance domain project_id does not match current project."
        )
    if str(manifest.get("hash_algorithm") or "") != HASH_ALGORITHM:
        raise AuthorshipProvenanceContractError(
            "Unsupported provenance hash algorithm."
        )


def _validate_origin_record(
    context: ProjectContext,
    record: dict[str, Any],
) -> None:
    if record.get("schema_version") != ORIGIN_SCHEMA_VERSION:
        raise AuthorshipProvenanceContractError(
            "Unsupported immutable origin schema."
        )
    _required_identifier(record.get("origin_id"), "origin_id")
    _required_identifier(record.get("version_id"), "version_id")
    _required_identifier(record.get("generation_id"), "generation_id")
    _required_identifier(record.get("segment_id"), "segment_id")
    _validate_actor(record.get("origin_actor"))
    if record.get("immutable") is not True:
        raise AuthorshipProvenanceContractError(
            "Origin record is missing immutable=true."
        )
    content = _content_text(record.get("content"))
    if str(record.get("content_hash") or "") != hash_text(content):
        raise AuthorshipProvenanceContractError(
            f"Origin content hash mismatch: {record.get('origin_id')}"
        )
    _clean_id_list(record.get("parent_ids") or [], "parent_ids")
    _optional_position(record.get("book_number"), "book_number")
    _optional_position(record.get("chapter_number"), "chapter_number")


def _validate_event_record(
    context: ProjectContext,
    event: dict[str, Any],
) -> None:
    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise AuthorshipProvenanceContractError(
            "Unsupported provenance event schema."
        )
    _required_identifier(event.get("event_id"), "event_id")
    _required_identifier(event.get("version_id"), "version_id")
    _required_identifier(event.get("segment_id"), "segment_id")
    actor = _validate_actor(event.get("actor"))
    operation = _validate_operation(event.get("operation"))
    _validate_actor_operation(actor, operation)
    parents = _clean_id_list(
        event.get("parent_version_ids") or [],
        "parent_version_ids",
    )
    if not parents:
        raise AuthorshipProvenanceContractError(
            "Persisted provenance event is missing parent_version_ids."
        )
    for field in ("before_hash", "after_hash"):
        value = str(event.get(field) or "")
        if not re_full_sha256(value):
            raise AuthorshipProvenanceContractError(
                f"Persisted provenance event has invalid {field}."
            )
    _optional_position(event.get("book_number"), "book_number")
    _optional_position(event.get("chapter_number"), "chapter_number")


def _validate_lineage_document(
    context: ProjectContext,
    lineage: dict[str, Any],
    *,
    origins: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    if lineage.get("schema_version") != LINEAGE_SCHEMA_VERSION:
        raise AuthorshipProvenanceContractError(
            "Unsupported provenance lineage schema."
        )
    if str(lineage.get("project_id") or "") != context.project_id:
        raise AuthorshipProvenanceContractError(
            "Provenance lineage project_id does not match current project."
        )
    stored_hash = str(lineage.get("content_hash") or "")
    without_hash = deepcopy(lineage)
    without_hash.pop("content_hash", None)
    expected_hash = _hash_canonical_json(without_hash)
    if stored_hash != expected_hash:
        raise AuthorshipProvenanceContractError(
            "Provenance lineage content hash mismatch."
        )

    versions = lineage.get("versions")
    segments = lineage.get("segments")
    if not isinstance(versions, dict) or not isinstance(segments, dict):
        raise AuthorshipProvenanceContractError(
            "Provenance lineage versions/segments must be objects."
        )

    for version_id, version in versions.items():
        if str(version.get("version_id") or "") != str(version_id):
            raise AuthorshipProvenanceContractError(
                f"Lineage version key mismatch: {version_id}"
            )
        for parent_id in version.get("parent_version_ids") or []:
            if parent_id not in versions:
                raise ProvenanceLineageError(
                    f"Lineage version references unknown parent: {parent_id}"
                )

    if int(lineage.get("source_origin_count") or 0) != len(origins):
        return
    if int(lineage.get("source_event_count") or 0) != len(events):
        return


def _lineage_matches_sources(
    lineage: dict[str, Any],
    origins: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> bool:
    if int(lineage.get("source_origin_count") or 0) != len(origins):
        return False
    if int(lineage.get("source_event_count") or 0) != len(events):
        return False
    expected_version_ids = {
        str(item.get("version_id") or "")
        for item in origins + events
        if item.get("version_id")
    }
    actual_version_ids = set((lineage.get("versions") or {}).keys())
    return expected_version_ids == actual_version_ids


def _load_origin_records(
    context: ProjectContext,
) -> list[dict[str, Any]]:
    root = provenance_root_for_context(context)
    origins_dir = root / ORIGINS_DIRECTORY
    if not origins_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(origins_dir.glob("origin_*.json")):
        record = _read_json_object(path, f"origin snapshot {path.name}")
        _validate_origin_record(context, record)
        records.append(record)
    return records


def _load_event_records(
    context: ProjectContext,
) -> list[dict[str, Any]]:
    path = provenance_root_for_context(context) / EVENT_LOG_FILENAME
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise AuthorshipProvenanceContractError(
                    f"Malformed provenance event log line {line_number}."
                ) from exc
            if not isinstance(event, dict):
                raise AuthorshipProvenanceContractError(
                    f"Provenance event log line {line_number} is not an object."
                )
            _validate_event_record(context, event)
            events.append(event)

    seen_events: set[str] = set()
    seen_versions: set[str] = set()
    for event in events:
        event_id = str(event["event_id"])
        version_id = str(event["version_id"])
        if event_id in seen_events:
            raise ProvenanceLineageError(
                f"Duplicate provenance event_id: {event_id}"
            )
        if version_id in seen_versions:
            raise ProvenanceLineageError(
                f"Duplicate provenance event version_id: {version_id}"
            )
        seen_events.add(event_id)
        seen_versions.add(version_id)
    return events


def _load_lineage_document(
    context: ProjectContext,
) -> dict[str, Any]:
    path = provenance_root_for_context(context) / LINEAGE_INDEX_FILENAME
    if not path.exists():
        return _empty_lineage_document(context.project_id)
    document = _read_json_object(path, "provenance lineage index")
    # Full source-aware validation is performed by callers once origins/events
    # are loaded. This local check prevents malformed shape from being used.
    if document.get("schema_version") != LINEAGE_SCHEMA_VERSION:
        raise AuthorshipProvenanceContractError(
            "Unsupported provenance lineage schema."
        )
    if str(document.get("project_id") or "") != context.project_id:
        raise AuthorshipProvenanceContractError(
            "Provenance lineage project_id does not match current project."
        )
    return document


def _empty_lineage_document(project_id: str) -> dict[str, Any]:
    payload = {
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "project_id": project_id,
        "hash_algorithm": HASH_ALGORITHM,
        "source_origin_count": 0,
        "source_event_count": 0,
        "versions": {},
        "segments": {},
    }
    payload["content_hash"] = _hash_canonical_json(payload)
    return payload


def _validate_parent_versions(
    lineage: dict[str, Any],
    parent_version_ids: list[str],
) -> list[dict[str, Any]]:
    versions = lineage.get("versions") or {}
    missing = [item for item in parent_version_ids if item not in versions]
    if missing:
        raise ProvenanceLineageError(
            "Unknown parent version(s): " + ", ".join(missing)
        )
    return [deepcopy(versions[item]) for item in parent_version_ids]


def _before_hash_from_parents(
    parent_versions: list[dict[str, Any]],
) -> str:
    if not parent_versions:
        return hash_text("")
    if len(parent_versions) == 1:
        return str(parent_versions[0].get("after_hash") or hash_text(""))
    return _hash_canonical_json(
        [str(item.get("after_hash") or "") for item in parent_versions]
    )


def _before_hash_from_parent_ids(
    versions: dict[str, dict[str, Any]],
    parent_ids: list[str],
) -> str:
    if not parent_ids:
        return hash_text("")
    parents = [versions[parent] for parent in parent_ids]
    return _before_hash_from_parents(parents)


def _validate_actor(value: Any) -> str:
    actor = str(value or "").strip().upper()
    if actor not in ACTOR_TYPES:
        raise AuthorshipProvenanceContractError(
            "actor must be one of: " + ", ".join(sorted(ACTOR_TYPES))
        )
    return actor


def _validate_operation(value: Any) -> str:
    operation = str(value or "").strip().upper()
    if operation not in EVENT_TYPES:
        raise AuthorshipProvenanceContractError(
            "operation must be one of: " + ", ".join(sorted(EVENT_TYPES))
        )
    return operation


def _validate_actor_operation(actor: str, operation: str) -> None:
    if operation.startswith("MODEL_") and actor != ACTOR_MODEL:
        raise AuthorshipProvenanceContractError(
            f"{operation} requires actor MODEL."
        )
    if operation.startswith("SYSTEM_") and actor != ACTOR_SYSTEM_DETERMINISTIC:
        raise AuthorshipProvenanceContractError(
            f"{operation} requires actor SYSTEM_DETERMINISTIC."
        )
    if operation in {"AUTHOR_ACCEPT", "AUTHOR_REJECT"} and actor != ACTOR_AUTHOR:
        raise AuthorshipProvenanceContractError(
            f"{operation} requires actor AUTHOR."
        )
    if (
        operation.startswith("AUTHOR_")
        and operation not in {"AUTHOR_ACCEPT", "AUTHOR_REJECT"}
        and actor not in {ACTOR_AUTHOR, ACTOR_EXTERNAL_AUTHOR_ATTESTED}
    ):
        raise AuthorshipProvenanceContractError(
            f"{operation} requires actor AUTHOR or EXTERNAL_AUTHOR_ATTESTED."
        )


def _required_identifier(value: Any, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise AuthorshipProvenanceContractError(
            f"{field_name} is required."
        )
    if any(ch in cleaned for ch in ("/", "\\", "\x00", "\r", "\n", "\t")):
        raise AuthorshipProvenanceContractError(
            f"{field_name} contains illegal characters."
        )
    if len(cleaned) > 200:
        raise AuthorshipProvenanceContractError(
            f"{field_name} is too long."
        )
    return cleaned


def _clean_id_list(values: Any, field_name: str) -> list[str]:
    if not isinstance(values, list):
        raise AuthorshipProvenanceContractError(
            f"{field_name} must be an array."
        )
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _required_identifier(value, field_name)
        if cleaned in seen:
            raise AuthorshipProvenanceContractError(
                f"{field_name} contains duplicate ID: {cleaned}"
            )
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _content_text(value: Any) -> str:
    if not isinstance(value, str):
        raise AuthorshipProvenanceContractError(
            "provenance content must be a string."
        )
    return value


def _metadata_object(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AuthorshipProvenanceContractError(
            "metadata must be an object."
        )
    # Force JSON-serializability and detach caller-owned mutable values.
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise AuthorshipProvenanceContractError(
            "metadata must contain JSON-serializable values."
        ) from exc


def _position_payload(
    book_number: int | None,
    chapter_number: int | None,
) -> dict[str, int | None]:
    book = _optional_position(book_number, "book_number")
    chapter = _optional_position(chapter_number, "chapter_number")
    if chapter is not None and book is None:
        raise AuthorshipProvenanceContractError(
            "chapter_number requires book_number."
        )
    return {
        "book_number": book,
        "chapter_number": chapter,
    }


def _positive_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AuthorshipProvenanceContractError(
            f"{field_name} must be a positive integer."
        ) from exc
    if number < 1:
        raise AuthorshipProvenanceContractError(
            f"{field_name} must be a positive integer."
        )
    return number


def _optional_position(value: Any, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    return _positive_int(value, field_name)


def _same_position(
    record: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
) -> bool:
    return (
        int(record.get("book_number") or 0) == book_number
        and int(record.get("chapter_number") or 0) == chapter_number
    )


def _hash_canonical_json(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def re_full_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorshipProvenanceContractError(
            f"Could not read {label}: {path.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise AuthorshipProvenanceContractError(
            f"{label} must contain a JSON object."
        )
    return payload


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(serialized + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    data = (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    _write_bytes_exclusive(path, data)


def _write_bytes_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(path), flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


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


@contextmanager
def _provenance_write_lock(root: Path) -> Iterator[None]:
    lock_path = root / WRITE_LOCK_FILENAME
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS

    while True:
        try:
            fd = os.open(
                str(lock_path),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                payload = (
                    f"pid={os.getpid()}\n"
                    f"created_at={utc_now_iso()}\n"
                ).encode("utf-8")
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            break
        except FileExistsError:
            try:
                age = max(0.0, time.time() - lock_path.stat().st_mtime)
            except FileNotFoundError:
                continue
            if age > STALE_LOCK_SECONDS:
                try:
                    lock_path.unlink()
                    continue
                except FileNotFoundError:
                    continue
            if time.monotonic() >= deadline:
                raise ProvenanceWriteLockError(
                    "Provenance write lock is busy. Retry after the active provenance write completes."
                )
            time.sleep(0.05)

    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _relative_project_path(
    context: ProjectContext,
    path: Path,
) -> str:
    try:
        return str(path.relative_to(context.project_dir)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _execution_locks() -> dict[str, bool]:
    return {
        "authorship_scoring_locked": True,
        "ledger_locked": True,
        "provider_execution_locked": True,
        "prompt_builder_locked": True,
        "validator_review_wiring_locked": True,
        "approved_continuity_write_locked": True,
        "author_voice_update_locked": True,
        "generation_unlock_locked": True,
    }
