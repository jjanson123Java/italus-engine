"""
Primary 36B Approved Continuity integration.

This service connects the verified Primary 36A continuity core to the current
author-review, provenance-classification, generation-request, and Chapter Plan
contracts.

The browser/operator may explicitly confirm only planned event/reveal references.
Project, generation, book/chapter position, accepted prose, lineage, hashes, and
continuity storage remain backend-owned.

Primary 36B does not update Author Voice, write the Primary 38 authorship ledger,
call a provider, or perform production cutover.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from app.services import (
    approved_continuity_service,
    author_review_service,
    authorship_classification_service,
    chapter_plan_service,
    generation_service,
)


APPROVED_CONTINUITY_INTEGRATION_SERVICE_MARKER = (
    "primary36b-approved-continuity-integration-v1"
)
SUPPORTED_ESTABLISHMENT_TYPES = frozenset(
    {"event_established", "reveal_established"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ApprovedContinuityIntegrationError(RuntimeError):
    """Raised when Primary 36B cannot safely expose or execute a continuity commit."""

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

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": deepcopy(self.details),
        }


def get_approved_continuity_integration_contract() -> dict[str, Any]:
    """Return the bounded Primary 36B integration contract."""

    return {
        "status": "ok",
        "service": APPROVED_CONTINUITY_INTEGRATION_SERVICE_MARKER,
        "core_service": approved_continuity_service.APPROVED_CONTINUITY_SERVICE_MARKER,
        "schema_version": approved_continuity_service.APPROVED_CONTINUITY_SCHEMA_VERSION,
        "commit_input": {
            "backend_owned": [
                "project_id",
                "generation_id",
                "book_number",
                "chapter_number",
                "accepted_content",
                "accepted_content_sha256",
                "accepted_version_id",
                "author_accept_event_id",
                "classification_evidence",
            ],
            "author_confirmed": {
                "established": {
                    "allowed_types": sorted(SUPPORTED_ESTABLISHMENT_TYPES),
                    "target_ref_must_be_planned": True,
                }
            },
        },
        "preconditions": [
            "terminal AUTHOR_ACCEPT",
            "Primary 35 classification is classified",
            "current generation request identity matches the immutable generation receipt",
            "current Chapter Plan is valid, fresh, and generation-ready",
        ],
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


def get_generation_approved_continuity_status(
    project_id: str,
    generation_id: str,
) -> dict[str, Any]:
    """Return the read-only Primary 36B status for one generation."""

    core_status = approved_continuity_service.get_approved_continuity_status(
        project_id,
        generation_id,
    )
    if core_status.get("generation_committed") is True:
        return {
            "status": "committed",
            "service": APPROVED_CONTINUITY_INTEGRATION_SERVICE_MARKER,
            "project_id": project_id,
            "generation_id": generation_id,
            "commit_ready": True,
            "idempotent_replay_available": True,
            "approved_continuity": deepcopy(core_status),
            "allowed_establishments": {
                "event_established": [],
                "reveal_established": [],
            },
            "blockers": [],
        }

    try:
        prepared = _prepare_commit_context(project_id, generation_id)
    except ApprovedContinuityIntegrationError as exc:
        return {
            "status": "blocked",
            "service": APPROVED_CONTINUITY_INTEGRATION_SERVICE_MARKER,
            "project_id": project_id,
            "generation_id": generation_id,
            "commit_ready": False,
            "idempotent_replay_available": False,
            "approved_continuity": deepcopy(core_status),
            "allowed_establishments": {
                "event_established": [],
                "reveal_established": [],
            },
            "blockers": [exc.to_detail()],
        }

    return {
        "status": "ready",
        "service": APPROVED_CONTINUITY_INTEGRATION_SERVICE_MARKER,
        "project_id": project_id,
        "generation_id": generation_id,
        "commit_ready": True,
        "idempotent_replay_available": False,
        "book_number": prepared["book_number"],
        "chapter_number": prepared["chapter_number"],
        "accepted_version_id": prepared["accepted_version_id"],
        "accepted_content_sha256": prepared["accepted_content_sha256"],
        "request_content_sha256": prepared["request_content_sha256"],
        "chapter_plan_revision": prepared["chapter_plan_revision"],
        "chapter_plan_sha256": prepared["chapter_plan_sha256"],
        "approved_continuity": deepcopy(core_status),
        "allowed_establishments": deepcopy(prepared["allowed_establishments"]),
        "blockers": [],
    }


def commit_generation_approved_continuity(
    project_id: str,
    generation_id: str,
    *,
    established: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Commit accepted prose using only backend-derived scope and validated refs."""

    prepared = _prepare_commit_context(project_id, generation_id)
    normalized_established = _validate_requested_establishments(
        established or [],
        allowed=prepared["allowed_establishments"],
        book_number=prepared["book_number"],
        chapter_number=prepared["chapter_number"],
    )

    result = approved_continuity_service.commit_approved_continuity(
        project_id,
        generation_id,
        book_number=prepared["book_number"],
        chapter_number=prepared["chapter_number"],
        established=normalized_established,
    )
    return {
        **deepcopy(result),
        "integration_service": APPROVED_CONTINUITY_INTEGRATION_SERVICE_MARKER,
        "request_content_sha256": prepared["request_content_sha256"],
        "chapter_plan_revision": prepared["chapter_plan_revision"],
        "chapter_plan_sha256": prepared["chapter_plan_sha256"],
        "establishment_count": len(normalized_established),
    }


def _prepare_commit_context(
    project_id: str,
    generation_id: str,
) -> dict[str, Any]:
    project = str(project_id or "").strip()
    generation = str(generation_id or "").strip()
    if not project:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_PROJECT_REQUIRED",
            "project_id is required.",
        )
    if not generation:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_GENERATION_REQUIRED",
            "generation_id is required.",
        )

    try:
        review = author_review_service.get_author_review_status(project, generation)
    except Exception as exc:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_REVIEW_UNAVAILABLE",
            "Author-review evidence could not be loaded.",
            details={"error": str(exc)},
        ) from exc

    if str(review.get("review_state") or "") != "accepted_pending_approved_continuity":
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_AUTHOR_ACCEPT_REQUIRED",
            "Approved Continuity requires accepted_pending_approved_continuity review state.",
            details={"review_state": str(review.get("review_state") or "")},
        )
    terminal = review.get("terminal_event") or {}
    if str(terminal.get("operation") or "") != "AUTHOR_ACCEPT":
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_AUTHOR_ACCEPT_EVENT_REQUIRED",
            "Approved Continuity requires a terminal AUTHOR_ACCEPT event.",
        )

    validation = review.get("validation") or {}
    validator_context = validation.get("validator_context") or {}
    if str(validator_context.get("project_id") or "") != project:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_PROJECT_MISMATCH",
            "Validator context project_id does not match the requested project.",
        )
    if str(validator_context.get("generation_id") or "") != generation:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_GENERATION_MISMATCH",
            "Validator context generation_id does not match the requested generation.",
        )

    try:
        book_number = int(validator_context.get("book_number") or 0)
        chapter_number = int(validator_context.get("chapter_number") or 0)
    except (TypeError, ValueError) as exc:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_POSITION_INVALID",
            "Validator context contains an invalid book/chapter position.",
        ) from exc
    if book_number < 1 or chapter_number < 1:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_POSITION_INVALID",
            "Validator context contains an invalid book/chapter position.",
            details={
                "book_number": book_number,
                "chapter_number": chapter_number,
            },
        )

    accepted_version_id = str(review.get("current_version_id") or "").strip()
    accepted_content_sha256 = str(review.get("current_content_sha256") or "").strip().lower()
    if not accepted_version_id or _SHA256_RE.fullmatch(accepted_content_sha256) is None:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_ACCEPTED_IDENTITY_INVALID",
            "Accepted review version/hash identity is incomplete.",
        )

    try:
        classification = authorship_classification_service.classify_generation_segment(
            project,
            generation,
        )
    except Exception as exc:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_CLASSIFICATION_UNAVAILABLE",
            "Primary 35 classification evidence could not be loaded.",
            details={"error": str(exc)},
        ) from exc

    if str(classification.get("assessment_status") or "") != "classified":
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_CLASSIFICATION_REQUIRED",
            "Primary 35 classification must be complete before continuity commit.",
            details={
                "assessment_status": str(classification.get("assessment_status") or "")
            },
        )
    if str(classification.get("accepted_version_id") or "") != accepted_version_id:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_CLASSIFICATION_VERSION_MISMATCH",
            "Primary 35 accepted_version_id does not match author review.",
        )
    if (
        str(classification.get("accepted_content_sha256") or "").lower()
        != accepted_content_sha256
    ):
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_CLASSIFICATION_HASH_MISMATCH",
            "Primary 35 accepted-content hash does not match author review.",
        )

    receipt_request_sha256 = str(
        validator_context.get("request_content_sha256") or ""
    ).strip().lower()
    if _SHA256_RE.fullmatch(receipt_request_sha256) is None:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_REQUEST_IDENTITY_INVALID",
            "Immutable generation request SHA-256 is missing or invalid.",
        )

    try:
        current_request = generation_service.build_generation_request_envelope(
            project,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except Exception as exc:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_SOURCE_NOT_CURRENT",
            "Current generation source artifacts are not ready for continuity commit.",
            details={"error": str(exc)},
        ) from exc

    current_request_sha256 = str(
        current_request.get("request_content_sha256") or ""
    ).strip().lower()
    if current_request_sha256 != receipt_request_sha256:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_SOURCE_DRIFT",
            "Current generation source identity differs from the immutable generation request.",
            details={
                "receipt_request_content_sha256": receipt_request_sha256,
                "current_request_content_sha256": current_request_sha256,
            },
        )

    try:
        chapter_payload = chapter_plan_service.get_chapter(
            project,
            book_number=book_number,
            chapter_number=chapter_number,
        )
    except Exception as exc:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_CHAPTER_PLAN_UNAVAILABLE",
            "Current Chapter Plan evidence could not be loaded.",
            details={"error": str(exc)},
        ) from exc

    chapter = chapter_payload.get("chapter") or {}
    if (
        str(chapter.get("status") or "") != chapter_plan_service.CHAPTER_STATUS_COMPLETE
        or str(chapter.get("lifecycle_state") or "")
        != chapter_plan_service.CHAPTER_STATUS_COMPLETE
        or (chapter.get("validation") or {}).get("valid") is not True
        or (chapter.get("freshness") or {}).get("fresh") is not True
        or (chapter.get("generation_readiness") or {}).get("ready") is not True
    ):
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_CHAPTER_PLAN_NOT_CURRENT",
            "Current Chapter Plan is not complete, valid, fresh, and generation-ready.",
            details={
                "status": chapter.get("status"),
                "lifecycle_state": chapter.get("lifecycle_state"),
                "validation": deepcopy(chapter.get("validation") or {}),
                "freshness": deepcopy(chapter.get("freshness") or {}),
                "generation_readiness": deepcopy(
                    chapter.get("generation_readiness") or {}
                ),
            },
        )

    chapter_plan_sha256 = str(chapter.get("content_hash") or "").strip().lower()
    if _SHA256_RE.fullmatch(chapter_plan_sha256) is None:
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_CHAPTER_PLAN_HASH_INVALID",
            "Current Chapter Plan content hash is missing or invalid.",
        )

    return {
        "project_id": project,
        "generation_id": generation,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "accepted_version_id": accepted_version_id,
        "accepted_content_sha256": accepted_content_sha256,
        "request_content_sha256": receipt_request_sha256,
        "chapter_plan_revision": int(chapter.get("revision") or 0),
        "chapter_plan_sha256": chapter_plan_sha256,
        "allowed_establishments": _allowed_establishments(chapter),
    }


def _allowed_establishments(chapter: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    event_refs: dict[str, dict[str, str]] = {}
    for item in chapter.get("assigned_event_refs") or []:
        if not isinstance(item, dict):
            continue
        record_id = str(item.get("record_id") or "").strip()
        if not record_id:
            continue
        event_refs[record_id] = {
            "target_ref": record_id,
            "label": str(item.get("label") or ""),
        }

    reveal_refs: dict[str, dict[str, str]] = {}
    for placement in chapter.get("event_placements") or []:
        if not isinstance(placement, dict):
            continue
        if str(placement.get("chapter_role") or "").strip().lower() != "reveal":
            continue
        event_ref = placement.get("event_ref") or {}
        if not isinstance(event_ref, dict):
            continue
        record_id = str(event_ref.get("record_id") or "").strip()
        if not record_id or record_id not in event_refs:
            continue
        reveal_refs[record_id] = deepcopy(event_refs[record_id])

    return {
        "event_established": [event_refs[key] for key in sorted(event_refs)],
        "reveal_established": [reveal_refs[key] for key in sorted(reveal_refs)],
    }


def _validate_requested_establishments(
    records: list[dict[str, Any]],
    *,
    allowed: dict[str, list[dict[str, str]]],
    book_number: int,
    chapter_number: int,
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        raise ApprovedContinuityIntegrationError(
            "APPROVED_CONTINUITY_ESTABLISHED_INVALID",
            "established must be a list.",
        )

    allowed_ids = {
        kind: {
            str(item.get("target_ref") or "")
            for item in entries
            if isinstance(item, dict) and str(item.get("target_ref") or "")
        }
        for kind, entries in allowed.items()
    }
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ApprovedContinuityIntegrationError(
                "APPROVED_CONTINUITY_ESTABLISHED_INVALID",
                f"established[{index}] must be an object.",
            )
        requirement_type = str(item.get("type") or "").strip()
        target_ref = str(item.get("target_ref") or "").strip()
        if requirement_type not in SUPPORTED_ESTABLISHMENT_TYPES or not target_ref:
            raise ApprovedContinuityIntegrationError(
                "APPROVED_CONTINUITY_ESTABLISHED_INVALID",
                f"established[{index}] has unsupported type or missing target_ref.",
            )
        if target_ref not in allowed_ids.get(requirement_type, set()):
            raise ApprovedContinuityIntegrationError(
                "APPROVED_CONTINUITY_ESTABLISHMENT_NOT_PLANNED",
                "Requested continuity establishment is not authorized by the current Chapter Plan.",
                details={
                    "index": index,
                    "type": requirement_type,
                    "target_ref": target_ref,
                },
            )
        key = (requirement_type, target_ref)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "type": requirement_type,
                "target_ref": target_ref,
                "book_number": book_number,
                "chapter_number": chapter_number,
            }
        )

    normalized.sort(key=lambda item: (item["type"], item["target_ref"]))
    return normalized
