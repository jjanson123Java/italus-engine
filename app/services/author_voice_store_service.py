"""
Primary 37B author-level Author Voice store and gated sample ingestion.

This service persists only prose that passes the Primary 37A provenance gate.
The store is application/author-level and cross-project. It is not Canon,
Approved Continuity, project planning state, or the Primary 38 authorship ledger.

Primary 37C owns the bounded Author Voice read projection and prompt integration.
"""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
from typing import Any

from app.registry import DATA_DIR
from app.services import (
    approved_continuity_service,
    author_profile_service,
    author_review_service,
    author_voice_provenance_gate_service,
)


AUTHOR_VOICE_STORE_MARKER = "primary37b-author-voice-store-v1"
AUTHOR_VOICE_STORE_SCHEMA_VERSION = "primary37b_author_voice_store_v1"
AUTHOR_VOICE_DB_PATH = DATA_DIR / "author_voice.sqlite3"


class AuthorVoiceStoreError(RuntimeError):
    """Raised when Author Voice persistence cannot be completed safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code or "AUTHOR_VOICE_STORE_FAILED")
        self.details = deepcopy(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": deepcopy(self.details),
        }


def get_author_voice_store_contract() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": AUTHOR_VOICE_STORE_MARKER,
        "schema_version": AUTHOR_VOICE_STORE_SCHEMA_VERSION,
        "scope": "application_author_level_cross_project",
        "storage": {
            "engine": "sqlite3",
            "path": str(AUTHOR_VOICE_DB_PATH),
            "profile_identity_source": "active_author_profile_id",
            "sample_identity": "immutable_project_generation_version_hash_binding",
        },
        "authority": {
            "writes_author_voice_samples": True,
            "writes_author_voice_features": False,
            "reads_author_voice_for_prompt": False,
            "requires_primary37a_eligibility": True,
            "mutates_canon": False,
            "mutates_approved_continuity": False,
            "mutates_provenance": False,
            "writes_authorship_ledger": False,
            "calls_provider": False,
        },
    }


def ensure_author_voice_store() -> dict[str, Any]:
    path = AUTHOR_VOICE_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists()

    try:
        with closing(_connect(path)) as conn:
            if existed:
                # Existing databases are validated read-only before any schema DDL.
                # An unknown or partially compatible database must never be
                # "repaired" implicitly by Primary 37B.
                _validate_existing_schema(conn)
            else:
                _ensure_schema(conn)

            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise AuthorVoiceStoreError(
                    "AUTHOR_VOICE_STORE_INTEGRITY_FAILED",
                    "SQLite integrity check failed.",
                    details={"path": str(path)},
                )
            conn.commit()
    except AuthorVoiceStoreError:
        if not existed:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        if not existed:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_STORE_OPEN_FAILED",
            "Author Voice database could not be created or validated.",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    return {
        "status": "ok",
        "service": AUTHOR_VOICE_STORE_MARKER,
        "schema_version": AUTHOR_VOICE_STORE_SCHEMA_VERSION,
        "path": str(path),
        "created": not existed,
    }


def get_author_voice_store_status(
    author_profile_id: str | None = None,
) -> dict[str, Any]:
    profile_id = _resolve_profile_id(author_profile_id)
    path = AUTHOR_VOICE_DB_PATH
    if not path.exists():
        return {
            "status": "ok",
            "service": AUTHOR_VOICE_STORE_MARKER,
            "schema_version": AUTHOR_VOICE_STORE_SCHEMA_VERSION,
            "present": False,
            "author_profile_id": profile_id,
            "sample_count": 0,
            "project_count": 0,
            "path": str(path),
        }

    try:
        with closing(_connect(path)) as conn:
            _validate_existing_schema(conn)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise AuthorVoiceStoreError(
                    "AUTHOR_VOICE_STORE_INTEGRITY_FAILED",
                    "SQLite integrity check failed.",
                    details={"path": str(path)},
                )
            sample_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM author_voice_samples
                    WHERE author_profile_id = ?
                    """,
                    (profile_id,),
                ).fetchone()[0]
            )
            project_count = int(
                conn.execute(
                    """
                    SELECT COUNT(DISTINCT project_id)
                    FROM author_voice_samples
                    WHERE author_profile_id = ?
                    """,
                    (profile_id,),
                ).fetchone()[0]
            )
    except AuthorVoiceStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_STORE_READ_FAILED",
            "Author Voice store status could not be read safely.",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    return {
        "status": "ok",
        "service": AUTHOR_VOICE_STORE_MARKER,
        "schema_version": AUTHOR_VOICE_STORE_SCHEMA_VERSION,
        "present": True,
        "author_profile_id": profile_id,
        "sample_count": sample_count,
        "project_count": project_count,
        "path": str(path),
    }


def ingest_generation_for_author_voice(
    project_id: str,
    generation_id: str,
) -> dict[str, Any]:
    project = _required_id(project_id, "project_id")
    generation = _required_id(generation_id, "generation_id")

    try:
        gate = author_voice_provenance_gate_service.evaluate_generation_for_author_voice(
            project,
            generation,
        )
    except author_voice_provenance_gate_service.AuthorVoiceProvenanceGateError as exc:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_FAILED",
            "Primary 37A eligibility could not be established.",
            details=exc.to_detail(),
        ) from exc

    if gate.get("eligible_for_author_voice_learning") is not True:
        return {
            "status": "ok",
            "service": AUTHOR_VOICE_STORE_MARKER,
            "schema_version": AUTHOR_VOICE_STORE_SCHEMA_VERSION,
            "project_id": project,
            "generation_id": generation,
            "eligible_for_author_voice_learning": False,
            "sample_written": False,
            "idempotent_replay": False,
            "reason_codes": list(gate.get("reason_codes") or []),
        }

    review = _load_review(project, generation)
    continuity = _load_continuity(project, generation)
    profile_id = _resolve_profile_id(None)
    sample = _build_sample(
        profile_id=profile_id,
        project_id=project,
        generation_id=generation,
        gate=gate,
        review=review,
        continuity=continuity,
    )

    ensure_author_voice_store()
    path = AUTHOR_VOICE_DB_PATH

    try:
        with closing(_connect(path)) as conn:
            _validate_existing_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            now = _utc_now()

            conn.execute(
                """
                INSERT OR IGNORE INTO author_voice_profiles (
                    profile_id, created_at, updated_at
                ) VALUES (?, ?, ?)
                """,
                (profile_id, now, now),
            )
            conn.execute(
                "UPDATE author_voice_profiles SET updated_at = ? WHERE profile_id = ?",
                (now, profile_id),
            )

            existing = conn.execute(
                """
                SELECT *
                FROM author_voice_samples
                WHERE project_id = ? AND generation_id = ?
                """,
                (project, generation),
            ).fetchone()

            if existing is not None:
                _assert_idempotent_existing(existing, sample)
                conn.commit()
                return _ingestion_result(
                    sample,
                    sample_written=False,
                    idempotent_replay=True,
                )

            conn.execute(
                """
                INSERT INTO author_voice_samples (
                    sample_id,
                    author_profile_id,
                    project_id,
                    generation_id,
                    accepted_version_id,
                    accepted_content_sha256,
                    accepted_content,
                    author_accept_event_id,
                    approved_continuity_commit_id,
                    final_segment_state,
                    awarded_level,
                    provenance_gate_service,
                    provenance_gate_schema_version,
                    provenance_gate_policy_version,
                    ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample["sample_id"],
                    sample["author_profile_id"],
                    sample["project_id"],
                    sample["generation_id"],
                    sample["accepted_version_id"],
                    sample["accepted_content_sha256"],
                    sample["accepted_content"],
                    sample["author_accept_event_id"],
                    sample["approved_continuity_commit_id"],
                    sample["final_segment_state"],
                    sample["awarded_level"],
                    sample["provenance_gate_service"],
                    sample["provenance_gate_schema_version"],
                    sample["provenance_gate_policy_version"],
                    now,
                ),
            )
            conn.commit()
    except AuthorVoiceStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_SAMPLE_WRITE_FAILED",
            "Eligible Author Voice evidence could not be persisted.",
            details={
                "project_id": project,
                "generation_id": generation,
                "path": str(path),
                "error": str(exc),
            },
        ) from exc

    return _ingestion_result(
        sample,
        sample_written=True,
        idempotent_replay=False,
    )


def list_author_voice_samples(
    author_profile_id: str | None = None,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    profile_id = _resolve_profile_id(author_profile_id)
    if not isinstance(limit, int) or limit < 1 or limit > 1000:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_SAMPLE_LIMIT_INVALID",
            "limit must be an integer from 1 through 1000.",
        )

    path = AUTHOR_VOICE_DB_PATH
    if not path.exists():
        return []

    try:
        with closing(_connect(path)) as conn:
            _validate_existing_schema(conn)
            rows = conn.execute(
                """
                SELECT *
                FROM author_voice_samples
                WHERE author_profile_id = ?
                ORDER BY ingested_at ASC, sample_id ASC
                LIMIT ?
                """,
                (profile_id, limit),
            ).fetchall()
    except AuthorVoiceStoreError:
        raise
    except (sqlite3.DatabaseError, OSError) as exc:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_SAMPLE_READ_FAILED",
            "Author Voice samples could not be read safely.",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    return [_row_to_sample(row) for row in rows]


def _load_review(project_id: str, generation_id: str) -> dict[str, Any]:
    try:
        review = author_review_service.get_author_review_status(project_id, generation_id)
    except Exception as exc:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_REVIEW_UNAVAILABLE",
            "Accepted author-review evidence could not be reloaded.",
            details={"error": str(exc)},
        ) from exc
    if not isinstance(review, dict):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_REVIEW_INVALID",
            "Author-review evidence must be an object.",
        )
    return review


def _load_continuity(project_id: str, generation_id: str) -> dict[str, Any]:
    try:
        continuity = approved_continuity_service.get_approved_continuity_status(
            project_id,
            generation_id,
        )
    except Exception as exc:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_UNAVAILABLE",
            "Approved Continuity evidence could not be reloaded.",
            details={"error": str(exc)},
        ) from exc
    if not isinstance(continuity, dict):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_INVALID",
            "Approved Continuity evidence must be an object.",
        )
    return continuity


def _build_sample(
    *,
    profile_id: str,
    project_id: str,
    generation_id: str,
    gate: dict[str, Any],
    review: dict[str, Any],
    continuity: dict[str, Any],
) -> dict[str, Any]:
    if str(gate.get("service") or "") != (
        author_voice_provenance_gate_service.AUTHOR_VOICE_PROVENANCE_GATE_MARKER
    ):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_SERVICE_MISMATCH",
            "Author Voice evidence did not come from the accepted Primary 37A gate.",
        )
    if str(gate.get("schema_version") or "") != (
        author_voice_provenance_gate_service.AUTHOR_VOICE_GATE_SCHEMA_VERSION
    ):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_SCHEMA_MISMATCH",
            "Author Voice gate schema version is unsupported.",
        )
    if str(gate.get("policy_version") or "") != (
        author_voice_provenance_gate_service.AUTHOR_VOICE_GATE_POLICY_VERSION
    ):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_POLICY_MISMATCH",
            "Author Voice gate policy version is unsupported.",
        )
    if str(gate.get("project_id") or "").strip() != project_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_PROJECT_MISMATCH",
            "Primary 37A project identity does not match the ingestion request.",
        )
    if str(gate.get("generation_id") or "").strip() != generation_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_GENERATION_MISMATCH",
            "Primary 37A generation identity does not match the ingestion request.",
        )
    if str(review.get("project_id") or "").strip() != project_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_REVIEW_PROJECT_MISMATCH",
            "Author-review project identity does not match the ingestion request.",
        )
    if str(review.get("generation_id") or "").strip() != generation_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_REVIEW_GENERATION_MISMATCH",
            "Author-review generation identity does not match the ingestion request.",
        )
    if str(continuity.get("project_id") or "").strip() != project_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_PROJECT_MISMATCH",
            "Approved Continuity project identity does not match the ingestion request.",
        )
    continuity_generation = str(continuity.get("generation_id") or "").strip()
    if continuity_generation and continuity_generation != generation_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_GENERATION_MISMATCH",
            "Approved Continuity generation identity does not match the ingestion request.",
        )

    evidence = gate.get("evidence") or {}
    if evidence.get("approved_continuity_committed") is not True:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_CONTINUITY_REQUIRED",
            "Primary 37A evidence no longer proves an Approved Continuity commit.",
        )
    if str(evidence.get("review_state") or "") != "accepted_pending_approved_continuity":
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_REVIEW_STATE_INVALID",
            "Primary 37A evidence no longer proves terminal author acceptance.",
        )
    if str(evidence.get("terminal_operation") or "") != "AUTHOR_ACCEPT":
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_AUTHOR_ACCEPT_REQUIRED",
            "Primary 37A evidence no longer proves terminal AUTHOR_ACCEPT.",
        )
    if str(evidence.get("classification_status") or "") != "classified":
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_GATE_CLASSIFICATION_REQUIRED",
            "Primary 37A evidence no longer proves completed classification.",
        )
    accepted_version_id = _required_id(
        evidence.get("accepted_version_id"),
        "accepted_version_id",
    )
    accepted_sha256 = _required_sha256(
        evidence.get("accepted_content_sha256"),
        "accepted_content_sha256",
    )

    review_version_id = _required_id(
        review.get("current_version_id"),
        "review.current_version_id",
    )
    accepted_content = str(review.get("current_content") or "")
    if not accepted_content:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_ACCEPTED_CONTENT_REQUIRED",
            "Eligible Author Voice evidence requires accepted prose content.",
        )
    review_sha256 = _sha256_text(accepted_content)
    declared_review_sha256 = _required_sha256(
        review.get("current_content_sha256"),
        "review.current_content_sha256",
    )

    if review_version_id != accepted_version_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_REVIEW_VERSION_MISMATCH",
            "Author-review version no longer matches the Primary 37A eligibility evidence.",
        )
    if review_sha256 != declared_review_sha256 or review_sha256 != accepted_sha256:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_REVIEW_HASH_MISMATCH",
            "Author-review content no longer matches the Primary 37A eligibility evidence.",
        )

    terminal = review.get("terminal_event") or {}
    if str(terminal.get("operation") or "") != "AUTHOR_ACCEPT":
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_AUTHOR_ACCEPT_REQUIRED",
            "Eligible Author Voice evidence requires a terminal AUTHOR_ACCEPT event.",
        )
    author_accept_event_id = _required_id(
        terminal.get("event_id"),
        "author_accept_event_id",
    )

    if continuity.get("generation_committed") is not True:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_COMMIT_REQUIRED",
            "Author Voice ingestion requires an Approved Continuity commit.",
        )
    continuity_commit = continuity.get("generation_commit") or {}
    if str(continuity_commit.get("accepted_version_id") or "") != accepted_version_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_VERSION_MISMATCH",
            "Approved Continuity version does not match Author Voice evidence.",
        )
    if str(continuity_commit.get("accepted_content_sha256") or "").lower() != accepted_sha256:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_HASH_MISMATCH",
            "Approved Continuity content hash does not match Author Voice evidence.",
        )
    continuity_content = str(continuity_commit.get("accepted_content") or "")
    if continuity_content:
        if _sha256_text(continuity_content) != accepted_sha256:
            raise AuthorVoiceStoreError(
                "AUTHOR_VOICE_CONTINUITY_CONTENT_MISMATCH",
                "Approved Continuity prose no longer matches its accepted hash.",
            )
        if continuity_content != accepted_content:
            raise AuthorVoiceStoreError(
                "AUTHOR_VOICE_CONTINUITY_PROSE_MISMATCH",
                "Approved Continuity prose does not match the accepted author-review prose.",
            )
    continuity_accept_event_id = str(
        continuity_commit.get("author_accept_event_id") or ""
    ).strip()
    if continuity_accept_event_id and continuity_accept_event_id != author_accept_event_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_ACCEPT_EVENT_MISMATCH",
            "Approved Continuity AUTHOR_ACCEPT identity does not match author review.",
        )
    if str(continuity_commit.get("project_id") or project_id).strip() != project_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_COMMIT_PROJECT_MISMATCH",
            "Approved Continuity commit project identity does not match.",
        )
    if str(continuity_commit.get("generation_id") or generation_id).strip() != generation_id:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_CONTINUITY_COMMIT_GENERATION_MISMATCH",
            "Approved Continuity commit generation identity does not match.",
        )
    approved_continuity_commit_id = _required_id(
        continuity_commit.get("commit_id"),
        "approved_continuity_commit_id",
    )

    final_segment_state = _required_id(
        evidence.get("final_segment_state"),
        "final_segment_state",
    )
    if final_segment_state not in (
        author_voice_provenance_gate_service.ELIGIBLE_FINAL_SEGMENT_STATES
    ):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_FINAL_STATE_INELIGIBLE",
            "Final segment state is outside the Primary 37A Author Voice gate.",
        )
    try:
        awarded_level = int(evidence.get("awarded_level"))
    except (TypeError, ValueError) as exc:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_AWARDED_LEVEL_INVALID",
            "Eligible Author Voice evidence requires a numeric awarded provenance level.",
        ) from exc
    if awarded_level not in author_voice_provenance_gate_service.ELIGIBLE_AWARDED_LEVELS:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_AWARDED_LEVEL_INELIGIBLE",
            "Awarded provenance level is outside the Primary 37A Author Voice gate.",
        )

    sample_id = _sample_id(
        profile_id=profile_id,
        project_id=project_id,
        generation_id=generation_id,
        accepted_version_id=accepted_version_id,
        accepted_content_sha256=accepted_sha256,
    )
    return {
        "sample_id": sample_id,
        "author_profile_id": profile_id,
        "project_id": project_id,
        "generation_id": generation_id,
        "accepted_version_id": accepted_version_id,
        "accepted_content_sha256": accepted_sha256,
        "accepted_content": accepted_content,
        "author_accept_event_id": author_accept_event_id,
        "approved_continuity_commit_id": approved_continuity_commit_id,
        "final_segment_state": final_segment_state,
        "awarded_level": awarded_level,
        "provenance_gate_service": str(gate.get("service") or ""),
        "provenance_gate_schema_version": str(gate.get("schema_version") or ""),
        "provenance_gate_policy_version": str(gate.get("policy_version") or ""),
    }


def _ingestion_result(
    sample: dict[str, Any],
    *,
    sample_written: bool,
    idempotent_replay: bool,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": AUTHOR_VOICE_STORE_MARKER,
        "schema_version": AUTHOR_VOICE_STORE_SCHEMA_VERSION,
        "project_id": sample["project_id"],
        "generation_id": sample["generation_id"],
        "author_profile_id": sample["author_profile_id"],
        "eligible_for_author_voice_learning": True,
        "sample_written": sample_written,
        "idempotent_replay": idempotent_replay,
        "sample": {
            "sample_id": sample["sample_id"],
            "accepted_version_id": sample["accepted_version_id"],
            "accepted_content_sha256": sample["accepted_content_sha256"],
            "author_accept_event_id": sample["author_accept_event_id"],
            "approved_continuity_commit_id": sample["approved_continuity_commit_id"],
            "final_segment_state": sample["final_segment_state"],
            "awarded_level": sample["awarded_level"],
        },
    }


def _resolve_profile_id(author_profile_id: str | None) -> str:
    if author_profile_id is not None:
        return _required_id(author_profile_id, "author_profile_id")
    try:
        profile_state = author_profile_service.get_author_profile()
    except Exception as exc:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_PROFILE_UNAVAILABLE",
            "Active Author Profile identity could not be loaded.",
            details={"error": str(exc)},
        ) from exc
    return _required_id(
        profile_state.get("active_profile_id"),
        "active_author_profile_id",
    )


def _sample_id(
    *,
    profile_id: str,
    project_id: str,
    generation_id: str,
    accepted_version_id: str,
    accepted_content_sha256: str,
) -> str:
    material = "\0".join(
        (
            profile_id,
            project_id,
            generation_id,
            accepted_version_id,
            accepted_content_sha256,
        )
    )
    return "avs_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def _assert_idempotent_existing(
    existing: sqlite3.Row,
    requested: dict[str, Any],
) -> None:
    immutable_fields = (
        "sample_id",
        "author_profile_id",
        "project_id",
        "generation_id",
        "accepted_version_id",
        "accepted_content_sha256",
        "accepted_content",
        "author_accept_event_id",
        "approved_continuity_commit_id",
        "final_segment_state",
        "awarded_level",
        "provenance_gate_service",
        "provenance_gate_schema_version",
        "provenance_gate_policy_version",
    )
    for field in immutable_fields:
        if existing[field] != requested[field]:
            raise AuthorVoiceStoreError(
                "AUTHOR_VOICE_SAMPLE_CONFLICT",
                "generation_id is already bound to different Author Voice evidence.",
                details={
                    "project_id": requested["project_id"],
                    "generation_id": requested["generation_id"],
                    "field": field,
                },
            )


def _row_to_sample(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "sample_id": row["sample_id"],
        "author_profile_id": row["author_profile_id"],
        "project_id": row["project_id"],
        "generation_id": row["generation_id"],
        "accepted_version_id": row["accepted_version_id"],
        "accepted_content_sha256": row["accepted_content_sha256"],
        "accepted_content": row["accepted_content"],
        "author_accept_event_id": row["author_accept_event_id"],
        "approved_continuity_commit_id": row["approved_continuity_commit_id"],
        "final_segment_state": row["final_segment_state"],
        "awarded_level": int(row["awarded_level"]),
        "provenance_gate_service": row["provenance_gate_service"],
        "provenance_gate_schema_version": row["provenance_gate_schema_version"],
        "provenance_gate_policy_version": row["provenance_gate_policy_version"],
        "ingested_at": row["ingested_at"],
    }


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS author_voice_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS author_voice_profiles (
            profile_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS author_voice_samples (
            sample_id TEXT PRIMARY KEY,
            author_profile_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            generation_id TEXT NOT NULL,
            accepted_version_id TEXT NOT NULL,
            accepted_content_sha256 TEXT NOT NULL,
            accepted_content TEXT NOT NULL,
            author_accept_event_id TEXT NOT NULL,
            approved_continuity_commit_id TEXT NOT NULL,
            final_segment_state TEXT NOT NULL,
            awarded_level INTEGER NOT NULL CHECK (awarded_level IN (3, 4)),
            provenance_gate_service TEXT NOT NULL,
            provenance_gate_schema_version TEXT NOT NULL,
            provenance_gate_policy_version TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            FOREIGN KEY (author_profile_id)
                REFERENCES author_voice_profiles(profile_id),
            UNIQUE (project_id, generation_id)
        );

        CREATE INDEX IF NOT EXISTS idx_author_voice_samples_profile
            ON author_voice_samples(author_profile_id, ingested_at, sample_id);

        CREATE INDEX IF NOT EXISTS idx_author_voice_samples_project
            ON author_voice_samples(project_id, generation_id);
        """
    )

    row = conn.execute(
        "SELECT value FROM author_voice_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO author_voice_meta(key, value) VALUES('schema_version', ?)",
            (AUTHOR_VOICE_STORE_SCHEMA_VERSION,),
        )
        conn.execute(
            "INSERT INTO author_voice_meta(key, value) VALUES('service', ?)",
            (AUTHOR_VOICE_STORE_MARKER,),
        )
        return

    if str(row["value"]) != AUTHOR_VOICE_STORE_SCHEMA_VERSION:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_STORE_SCHEMA_MISMATCH",
            "Author Voice database schema version is unsupported.",
            details={
                "expected": AUTHOR_VOICE_STORE_SCHEMA_VERSION,
                "actual": str(row["value"]),
            },
        )


def _validate_existing_schema(conn: sqlite3.Connection) -> None:
    if not _has_table(conn, "author_voice_meta"):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_STORE_SCHEMA_MISSING",
            "Author Voice database schema marker is missing.",
        )
    row = conn.execute(
        "SELECT value FROM author_voice_meta WHERE key = 'schema_version'"
    ).fetchone()
    actual = str(row["value"]) if row is not None else ""
    if actual != AUTHOR_VOICE_STORE_SCHEMA_VERSION:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_STORE_SCHEMA_MISMATCH",
            "Author Voice database schema version is unsupported.",
            details={
                "expected": AUTHOR_VOICE_STORE_SCHEMA_VERSION,
                "actual": actual,
            },
        )
    service_row = conn.execute(
        "SELECT value FROM author_voice_meta WHERE key = 'service'"
    ).fetchone()
    service_actual = str(service_row["value"]) if service_row is not None else ""
    if service_actual != AUTHOR_VOICE_STORE_MARKER:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_STORE_SERVICE_MISMATCH",
            "Author Voice database service marker is unsupported.",
            details={
                "expected": AUTHOR_VOICE_STORE_MARKER,
                "actual": service_actual,
            },
        )

    required_tables = {"author_voice_profiles", "author_voice_samples"}
    missing = sorted(table for table in required_tables if not _has_table(conn, table))
    if missing:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_STORE_TABLE_MISSING",
            "Author Voice database is missing required tables.",
            details={"missing": missing},
        )

    required_columns = {
        "author_voice_profiles": {
            "profile_id",
            "created_at",
            "updated_at",
        },
        "author_voice_samples": {
            "sample_id",
            "author_profile_id",
            "project_id",
            "generation_id",
            "accepted_version_id",
            "accepted_content_sha256",
            "accepted_content",
            "author_accept_event_id",
            "approved_continuity_commit_id",
            "final_segment_state",
            "awarded_level",
            "provenance_gate_service",
            "provenance_gate_schema_version",
            "provenance_gate_policy_version",
            "ingested_at",
        },
    }
    for table_name, expected_columns in required_columns.items():
        actual_columns = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        missing_columns = sorted(expected_columns - actual_columns)
        if missing_columns:
            raise AuthorVoiceStoreError(
                "AUTHOR_VOICE_STORE_COLUMN_MISSING",
                "Author Voice database is missing required schema columns.",
                details={
                    "table": table_name,
                    "missing": missing_columns,
                },
            )


def _has_table(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _required_id(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_ID_REQUIRED",
            f"{field_name} is required.",
            details={"field": field_name},
        )
    if len(normalized) > 500 or any(ord(ch) < 32 for ch in normalized):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_ID_INVALID",
            f"{field_name} is invalid.",
            details={"field": field_name},
        )
    return normalized


def _required_sha256(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise AuthorVoiceStoreError(
            "AUTHOR_VOICE_SHA256_INVALID",
            f"{field_name} must be a lowercase SHA-256 digest.",
            details={"field": field_name},
        )
    return normalized


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
