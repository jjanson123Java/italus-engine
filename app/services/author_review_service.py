"""
Primary 34 author-review persistence boundary.

Author review is persisted as append-only provenance lineage. Review-owned
AUTHOR_EDIT / AUTHOR_ACCEPT / AUTHOR_REJECT events include content_after so the
reviewed text is recoverable without changing immutable MODEL-origin records.

This service does not write Approved Continuity, Canon, runtime story state,
Author Voice, provider receipts, usage, pricing, or provider bindings.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

from app.services import (
    authorship_provenance_service,
    candidate_validation_resolution_service,
    validation_service,
)


AUTHOR_REVIEW_SERVICE_MARKER = "primary34-author-review-v1"
AUTHOR_REVIEW_SCHEMA_VERSION = "primary34_author_review_v1"

ACTION_ACCEPT = "accept"
ACTION_EDIT = "edit"
ACTION_REJECT = "reject"
ACTIONS = frozenset({ACTION_ACCEPT, ACTION_EDIT, ACTION_REJECT})

_TERMINAL_OPERATIONS = frozenset({"AUTHOR_ACCEPT", "AUTHOR_REJECT"})
_TRUSTED_TRANSFORMATIONS = {
    authorship_provenance_service.ACTOR_MODEL: frozenset(
        {"MODEL_REWRITE", "MODEL_COPYEDIT"}
    ),
    authorship_provenance_service.ACTOR_SYSTEM_DETERMINISTIC: frozenset(
        {"SYSTEM_FORMAT", "SYSTEM_NORMALIZE"}
    ),
}


class AuthorReviewError(RuntimeError):
    """Raised when an author-review transition violates the Primary 34 contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = str(code or "AUTHOR_REVIEW_FAILED")
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": deepcopy(self.details),
        }


def _content(value: Any, field_name: str = "content") -> str:
    if not isinstance(value, str):
        raise AuthorReviewError(
            "AUTHOR_REVIEW_CONTENT_REQUIRED",
            f"{field_name} must be text.",
        )
    if not value.strip():
        raise AuthorReviewError(
            "AUTHOR_REVIEW_CONTENT_REQUIRED",
            f"{field_name} must not be empty.",
        )
    return value


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _event_identity(
    *,
    project_id: str,
    generation_id: str,
    actor: str,
    operation: str,
    parent_version_id: str,
    content_sha256: str,
) -> tuple[str, str]:
    raw = "\x1f".join(
        [
            project_id,
            generation_id,
            actor,
            operation,
            parent_version_id,
            content_sha256,
        ]
    )
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"review_event_{suffix}", f"review_version_{suffix}"


def _records(
    project_id: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    ctx = validation.get("validator_context") or {}
    return authorship_provenance_service.get_segment_lineage_records(
        project_id,
        generation_id=str(validation.get("generation_id") or ""),
        segment_id=str(ctx.get("segment_id") or ""),
    )


def _tips(records: dict[str, Any]) -> list[dict[str, Any]]:
    versions = dict(records.get("versions") or {})
    if not versions:
        return []
    parent_ids = {
        parent
        for version in versions.values()
        for parent in (version.get("parent_version_ids") or [])
    }
    return [
        deepcopy(version)
        for version_id, version in versions.items()
        if version_id not in parent_ids
    ]


def _event_by_version(
    records: dict[str, Any],
    version_id: str,
) -> dict[str, Any] | None:
    for event in records.get("events") or []:
        if str(event.get("version_id") or "") == version_id:
            return deepcopy(event)
    return None


def _origin_by_version(
    records: dict[str, Any],
    version_id: str,
) -> dict[str, Any] | None:
    for origin in records.get("origins") or []:
        if str(origin.get("version_id") or "") == version_id:
            return deepcopy(origin)
    return None


def _head(records: dict[str, Any]) -> tuple[dict[str, Any], str]:
    tips = _tips(records)
    if len(tips) != 1:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_LINEAGE_AMBIGUOUS",
            "Candidate review lineage must have exactly one current tip.",
            details={"tip_count": len(tips)},
        )
    tip = tips[0]
    version_id = str(tip.get("version_id") or "")
    origin = _origin_by_version(records, version_id)
    if origin is not None:
        return tip, _content(origin.get("content"), "origin content")
    event = _event_by_version(records, version_id)
    if event is None:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_LINEAGE_CONTENT_MISSING",
            "Current review lineage tip has no authoritative event record.",
        )
    if "content_after" not in event:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_LINEAGE_CONTENT_MISSING",
            "Current review lineage tip predates recoverable Primary 34 review content.",
            details={"version_id": version_id},
        )
    return tip, _content(event.get("content_after"), "review content")


def _terminal_event(records: dict[str, Any]) -> dict[str, Any] | None:
    terminals = [
        deepcopy(event)
        for event in (records.get("events") or [])
        if str(event.get("operation") or "") in _TERMINAL_OPERATIONS
    ]
    if len(terminals) > 1:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_TERMINAL_CONFLICT",
            "Multiple terminal author-review decisions exist for this candidate.",
            details={"terminal_count": len(terminals)},
        )
    return terminals[0] if terminals else None


def _record_event(
    project_id: str,
    *,
    validation: dict[str, Any],
    parent_version_id: str,
    actor: str,
    operation: str,
    content_after: str,
    review_action: str,
) -> dict[str, Any]:
    generation_id = str(validation.get("generation_id") or "")
    ctx = validation.get("validator_context") or {}
    content_sha256 = _digest(content_after)
    event_id, version_id = _event_identity(
        project_id=project_id,
        generation_id=generation_id,
        actor=actor,
        operation=operation,
        parent_version_id=parent_version_id,
        content_sha256=content_sha256,
    )
    metadata = {
        "review_schema_version": AUTHOR_REVIEW_SCHEMA_VERSION,
        "validation_schema_version": validation.get("schema_version"),
        "validation_report_sha256": validation.get("validation_report_sha256"),
        "validator_context_sha256": ctx.get("context_sha256"),
        "review_action": review_action,
        "approved_continuity_committed": False,
    }
    if operation == "AUTHOR_REJECT":
        deterministic_failures = []
        for item in list(validation.get("content_rules") or []):
            if not isinstance(item, dict):
                continue
            if (
                str(item.get("evaluation_mode") or "") != "DETERMINISTIC"
                or str(item.get("severity") or "") != "BLOCKER"
                or str(item.get("status") or "") == "PASS"
            ):
                continue
            details = item.get("details")
            details = details if isinstance(details, dict) else {}
            deterministic_failures.append(
                {
                    "rule_id": str(item.get("rule_id") or ""),
                    "message": str(item.get("message") or ""),
                    "instruction": str(item.get("instruction") or ""),
                    "details": {
                        key: details.get(key)
                        for key in (
                            "metric",
                            "measurement",
                            "operator",
                            "threshold",
                            "required_reduction",
                        )
                        if details.get(key) is not None
                    },
                }
            )
        metadata["rejection_validation"] = {
            "validation_run_id": str(validation.get("validation_run_id") or ""),
            "validation_result_sha256": str(
                validation.get("validation_result_sha256") or ""
            ),
            "validated_content_version_id": str(
                ctx.get("current_content_version_id") or ""
            ),
            "validated_content_sha256": str(
                ctx.get("candidate_content_sha256") or ""
            ),
            "validator_contract_sha256": str(
                ctx.get("validator_contract_sha256") or ""
            ),
            "deterministic_failures": deterministic_failures,
        }
    if operation == "AUTHOR_ACCEPT":
        metadata["acceptance_validation"] = {
            "validation_run_id": str(validation.get("validation_run_id") or ""),
            "validation_result_sha256": str(
                validation.get("validation_result_sha256") or ""
            ),
            "validated_content_version_id": str(
                ctx.get("current_content_version_id") or ""
            ),
            "validated_content_sha256": str(
                ctx.get("candidate_content_sha256") or ""
            ),
            "validator_contract_sha256": str(
                ctx.get("validator_contract_sha256") or ""
            ),
        }
    try:
        return authorship_provenance_service.record_lineage_event(
            project_id,
            segment_id=str(ctx.get("segment_id") or ""),
            actor=actor,
            operation=operation,
            content_after=content_after,
            parent_version_ids=[parent_version_id],
            source_generation_id=generation_id,
            book_number=int(ctx.get("book_number") or 0),
            chapter_number=int(ctx.get("chapter_number") or 0),
            metadata=metadata,
            event_id=event_id,
            version_id=version_id,
            persist_content_after=True,
        )
    except authorship_provenance_service.AuthorshipProvenanceError as exc:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_PROVENANCE_WRITE_FAILED",
            str(exc),
            details={
                "generation_id": generation_id,
                "operation": operation,
            },
        ) from exc


def get_author_review_status(
    project_id: str,
    generation_id: str,
) -> dict[str, Any]:
    validation = validation_service.validate_generation_candidate(
        project_id,
        generation_id,
    )
    records = _records(project_id, validation)
    terminal = _terminal_event(records)

    if not records.get("versions"):
        current_text = str((validation.get("candidate") or {}).get("text") or "")
        current_version_id = str(
            (validation.get("candidate") or {}).get("model_origin_version_id") or ""
        )
    else:
        head, current_text = _head(records)
        current_version_id = str(head.get("version_id") or "")

    if terminal is not None:
        operation = str(terminal.get("operation") or "")
        review_state = (
            "accepted_pending_approved_continuity"
            if operation == "AUTHOR_ACCEPT"
            else "rejected"
        )
    elif validation.get("reviewable") is True:
        review_state = "pending_author_review"
    else:
        review_state = "blocked"

    return {
        "status": "ok",
        "service": AUTHOR_REVIEW_SERVICE_MARKER,
        "schema_version": AUTHOR_REVIEW_SCHEMA_VERSION,
        "project_id": project_id,
        "generation_id": generation_id,
        "review_state": review_state,
        "terminal": terminal is not None,
        "current_version_id": current_version_id,
        "current_content": current_text,
        "current_content_sha256": _digest(current_text) if current_text else "",
        "validation": deepcopy(validation),
        "terminal_event": deepcopy(terminal),
        "approved_continuity_committed": False,
        "authority": {
            "persists_author_review": True,
            "writes_approved_continuity": False,
            "mutates_canon": False,
            "mutates_runtime_story_state": False,
            "updates_author_voice": False,
            "calls_provider": False,
        },
    }


def record_author_review(
    project_id: str,
    generation_id: str,
    *,
    action: str,
    content: str | None = None,
) -> dict[str, Any]:
    action_value = str(action or "").strip().lower()
    if action_value not in ACTIONS:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_ACTION_INVALID",
            "action must be one of: accept, edit, reject.",
        )

    validation = validation_service.validate_generation_candidate(
        project_id,
        generation_id,
    )
    if validation.get("reviewable") is not True:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_VALIDATION_BLOCKED",
            "Candidate integrity is blocked and cannot enter author review.",
            details={"blockers": deepcopy(validation.get("blockers") or [])},
        )

    records = _records(project_id, validation)
    terminal = _terminal_event(records)

    head, current_text = _head(records)
    parent_version_id = str(head.get("version_id") or "")
    desired_text = current_text if content is None else _content(content)

    if terminal is not None:
        terminal_operation = str(terminal.get("operation") or "")
        expected_operation = (
            "AUTHOR_ACCEPT" if action_value == ACTION_ACCEPT
            else "AUTHOR_REJECT" if action_value == ACTION_REJECT
            else "AUTHOR_EDIT"
        )
        terminal_hash = str(terminal.get("after_hash") or "")
        if (
            terminal_operation == expected_operation
            and terminal_hash == _digest(desired_text)
        ):
            status = get_author_review_status(project_id, generation_id)
            status["idempotent_replay"] = True
            return status
        raise AuthorReviewError(
            "AUTHOR_REVIEW_ALREADY_FINALIZED",
            "Candidate already has a different terminal author-review decision.",
            details={
                "operation": terminal_operation,
                "after_hash": terminal_hash,
            },
        )

    if action_value == ACTION_EDIT:
        desired_text = _content(content)
        if _digest(desired_text) == _digest(current_text):
            status = get_author_review_status(project_id, generation_id)
            status["review_write"] = "no_op"
            return status
        result = _record_event(
            project_id,
            validation=validation,
            parent_version_id=parent_version_id,
            actor=authorship_provenance_service.ACTOR_AUTHOR,
            operation="AUTHOR_EDIT",
            content_after=desired_text,
            review_action=ACTION_EDIT,
        )
        status = get_author_review_status(project_id, generation_id)
        status["review_write"] = result.get("status")
        return status

    if action_value == ACTION_REJECT:
        if content is not None and _digest(desired_text) != _digest(current_text):
            raise AuthorReviewError(
                "AUTHOR_REVIEW_REJECT_CONTENT_MISMATCH",
                "Reject cannot silently replace the current candidate content.",
            )
        result = _record_event(
            project_id,
            validation=validation,
            parent_version_id=parent_version_id,
            actor=authorship_provenance_service.ACTOR_AUTHOR,
            operation="AUTHOR_REJECT",
            content_after=current_text,
            review_action=ACTION_REJECT,
        )
        status = get_author_review_status(project_id, generation_id)
        status["review_write"] = result.get("status")
        return status

    # ACCEPT is allowed only for the exact already-saved lineage version that
    # produced the current acceptance-grade validation result.
    if _digest(desired_text) != _digest(current_text):
        raise AuthorReviewError(
            "AUTHOR_REVIEW_ACCEPT_REQUIRES_SAVED_VERSION",
            "Save the edited draft first, then validate and resolve that exact version before accepting it.",
        )

    ctx = validation.get("validator_context") or {}
    validated_version_id = str(ctx.get("current_content_version_id") or "")
    validated_content_sha256 = str(ctx.get("candidate_content_sha256") or "")
    if (
        validated_version_id != parent_version_id
        or validated_content_sha256 != _digest(current_text)
    ):
        raise AuthorReviewError(
            "AUTHOR_REVIEW_VALIDATION_STALE",
            "Current lineage content does not match the validation result. Reload and validate the current draft.",
            details={
                "current_version_id": parent_version_id,
                "validated_version_id": validated_version_id,
            },
        )
    if validation.get("acceptable_for_author_acceptance") is not True:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_ACCEPTANCE_BLOCKED",
            "Current draft is reviewable but not acceptance-ready.",
            details={
                "validation_state": validation.get("validation_state"),
                "blockers": deepcopy(validation.get("blockers") or []),
                "manual_resolution_required": deepcopy(
                    validation.get("manual_resolution_required") or []
                ),
            },
        )

    result = _record_event(
        project_id,
        validation=validation,
        parent_version_id=parent_version_id,
        actor=authorship_provenance_service.ACTOR_AUTHOR,
        operation="AUTHOR_ACCEPT",
        content_after=desired_text,
        review_action=ACTION_ACCEPT,
    )
    status = get_author_review_status(project_id, generation_id)
    status["review_write"] = result.get("status")
    return status


def record_author_validation_resolutions(
    project_id: str,
    generation_id: str,
    *,
    rule_ids: list[str],
    note: str,
) -> dict[str, Any]:
    """Record explicit author decisions for unresolved narrative rules.

    Resolutions bind to the exact current substantive lineage version, content
    SHA-256, validator contract, and validation run. They cannot resolve
    deterministic or integrity failures.
    """

    validation = validation_service.validate_generation_candidate(
        project_id,
        generation_id,
    )
    if validation.get("reviewable") is not True:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_VALIDATION_BLOCKED",
            "Candidate integrity is blocked and narrative rules cannot be resolved.",
            details={"blockers": deepcopy(validation.get("blockers") or [])},
        )

    records = _records(project_id, validation)
    if _terminal_event(records) is not None:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_ALREADY_FINALIZED",
            "Validation rules cannot be resolved after terminal author review.",
        )

    head, current_text = _head(records)
    current_version_id = str(head.get("version_id") or "")
    current_content_sha256 = _digest(current_text)
    ctx = validation.get("validator_context") or {}
    if (
        str(ctx.get("current_content_version_id") or "") != current_version_id
        or str(ctx.get("candidate_content_sha256") or "") != current_content_sha256
    ):
        raise AuthorReviewError(
            "AUTHOR_REVIEW_VALIDATION_STALE",
            "Current lineage content does not match the validation result.",
        )

    requested = []
    seen: set[str] = set()
    for value in rule_ids or []:
        rule_id = str(value or "").strip()
        if not rule_id or rule_id in seen:
            continue
        seen.add(rule_id)
        requested.append(rule_id)
    if not requested:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_RESOLUTION_RULE_REQUIRED",
            "Select at least one unresolved MANUAL/SEMANTIC rule.",
        )

    unresolved = {
        str(item.get("rule_id") or ""): item
        for item in (validation.get("manual_resolution_required") or [])
        if str(item.get("rule_id") or "")
    }
    invalid = [rule_id for rule_id in requested if rule_id not in unresolved]
    if invalid:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_RESOLUTION_RULE_INVALID",
            "Only unresolved MANUAL/SEMANTIC rules for the exact current content may be resolved.",
            details={"rule_ids": invalid},
        )

    contract_sha256 = str(ctx.get("validator_contract_sha256") or "")
    validation_run_id = str(validation.get("validation_run_id") or "")
    if not contract_sha256 or not validation_run_id:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_RESOLUTION_IDENTITY_MISSING",
            "Validation contract/run identity is incomplete.",
        )

    results: list[dict[str, Any]] = []
    for rule_id in requested:
        rule = unresolved[rule_id]
        try:
            result = candidate_validation_resolution_service.record_author_resolution(
                project_id,
                generation_id,
                content_version_id=current_version_id,
                content_sha256=current_content_sha256,
                validator_contract_sha256=contract_sha256,
                rule_id=rule_id,
                rule_type=str(rule.get("rule_type") or ""),
                rule_instruction=str(rule.get("instruction") or rule.get("message") or ""),
                validation_run_id=validation_run_id,
                note=note,
            )
        except candidate_validation_resolution_service.CandidateValidationResolutionError as exc:
            raise AuthorReviewError(
                "AUTHOR_REVIEW_RESOLUTION_WRITE_FAILED",
                str(exc),
                details={"rule_id": rule_id},
            ) from exc
        results.append(result)

    status = get_author_review_status(project_id, generation_id)
    status["resolution_write"] = {
        "requested_rule_ids": requested,
        "recorded_count": sum(1 for item in results if item.get("recorded") is True),
        "results": results,
    }
    return status


def record_trusted_review_transformation(
    project_id: str,
    generation_id: str,
    *,
    actor: str,
    operation: str,
    content_after: str,
) -> dict[str, Any]:
    """Persist a trusted backend MODEL/SYSTEM review transformation.

    This method is intentionally not exposed as a public API route. It exists so
    backend-owned rewrite/normalization steps can preserve actor-specific lineage
    without allowing a browser caller to impersonate MODEL or SYSTEM actors.
    """

    actor_value = str(actor or "").strip().upper()
    operation_value = str(operation or "").strip().upper()
    if operation_value not in _TRUSTED_TRANSFORMATIONS.get(actor_value, frozenset()):
        raise AuthorReviewError(
            "TRUSTED_REVIEW_TRANSFORMATION_INVALID",
            "actor/operation is not an allowed trusted review transformation.",
        )

    validation = validation_service.validate_generation_candidate(
        project_id,
        generation_id,
    )
    if validation.get("reviewable") is not True:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_VALIDATION_BLOCKED",
            "Candidate integrity is blocked by structured validation.",
        )
    records = _records(project_id, validation)
    if _terminal_event(records) is not None:
        raise AuthorReviewError(
            "AUTHOR_REVIEW_ALREADY_FINALIZED",
            "Trusted transformations are blocked after terminal author review.",
        )
    head, current_text = _head(records)
    desired_text = _content(content_after)
    if _digest(desired_text) == _digest(current_text):
        return get_author_review_status(project_id, generation_id)

    result = _record_event(
        project_id,
        validation=validation,
        parent_version_id=str(head.get("version_id") or ""),
        actor=actor_value,
        operation=operation_value,
        content_after=desired_text,
        review_action="trusted_transformation",
    )
    status = get_author_review_status(project_id, generation_id)
    status["review_write"] = result.get("status")
    return status
