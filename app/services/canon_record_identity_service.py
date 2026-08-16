"""
Stable internal identity for project-local repeatable Canon records.

This service owns only system-generated identity metadata for repeatable records.
It does not define author-facing Canon fields, relationships, Book Scope,
Planner behavior, generation behavior, or provenance.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5


CANON_RECORD_IDENTITY_SERVICE_MARKER = "canon-record-identity-boundary-20260816"
CANON_RECORD_IDENTITY_VERSION = "canon_record_identity_v1"
INTERNAL_ID_FIELD = "internal_id"

_BACKFILL_NAMESPACE = uuid5(NAMESPACE_URL, "italus:canon-record-identity:v1")

_RECORD_GROUP_PREFIXES = {
    "characters": "char",
    "locations": "loc",
    "events": "evt",
    "life_events": "evt",
    "interactions": "rel",
    "groups": "grp",
    "systems": "sys",
    "clues": "clue",
    "signals": "sig",
    "custom_sections": "rec",
}


class CanonRecordIdentityConflictError(ValueError):
    """Raised when persisted or submitted record identity is ambiguous or mutable."""


def backfill_author_canon_record_identities(
    project_id: str,
    author_canon: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return Canon with deterministic IDs assigned to legacy repeatable records.

    Existing IDs are preserved exactly. Missing IDs use a UUIDv5 derived from
    stable project/section/record-group coordinates and the legacy row ordinal.
    The migration never uses an author-facing name, label, alias, story code, or
    other mutable value as identity input.
    """

    canonical_project_id = str(project_id or "").strip()
    if not canonical_project_id:
        raise CanonRecordIdentityConflictError("Project ID is required for Canon record identity.")

    normalized = deepcopy(author_canon if isinstance(author_canon, dict) else {})
    seen: dict[str, dict[str, Any]] = {}
    assignments: list[dict[str, Any]] = []
    record_count = 0

    sections = normalized.get("sections")
    if not isinstance(sections, dict):
        return normalized, _report(False, 0, 0, [])

    for section_id, section in sections.items():
        if not isinstance(section, dict):
            continue
        records = section.get("records")
        if not isinstance(records, dict):
            continue

        for record_group_id, items in records.items():
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                record_count += 1
                location = {
                    "section_id": str(section_id),
                    "record_group_id": str(record_group_id),
                    "index": index,
                }
                internal_id = _clean_internal_id(item.get(INTERNAL_ID_FIELD))
                if internal_id:
                    _claim_identity(internal_id, location, seen)
                    if item.get(INTERNAL_ID_FIELD) != internal_id:
                        item[INTERNAL_ID_FIELD] = internal_id
                    continue

                internal_id = _deterministic_backfill_id(
                    canonical_project_id,
                    str(section_id),
                    str(record_group_id),
                    index,
                    seen,
                )
                item[INTERNAL_ID_FIELD] = internal_id
                _claim_identity(internal_id, location, seen)
                assignments.append({**location, "internal_id": internal_id})

    return normalized, _report(bool(assignments), record_count, len(seen), assignments)


def reconcile_section_record_identities(
    project_id: str,
    section_id: str,
    author_canon: dict[str, Any],
    incoming_records: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Preserve existing IDs and generate IDs for newly submitted records.

    Submitted IDs must already belong to the same section and record group.
    Rows without an ID preserve the identity at the same legacy ordinal when
    that identity has not already been claimed; otherwise a new ID is created.
    This compatibility fallback supports a stale pre-Patch-14 browser without
    deriving identity from mutable author text.
    """

    canonical_project_id = str(project_id or "").strip()
    canonical_section_id = str(section_id or "").strip()
    if not canonical_project_id or not canonical_section_id:
        raise CanonRecordIdentityConflictError("Project and section IDs are required for Canon record identity.")

    normalized_existing, _ = backfill_author_canon_record_identities(
        canonical_project_id,
        author_canon,
    )
    owners = _identity_owners(normalized_existing)
    existing_section = _stored_section_records(normalized_existing, canonical_section_id)

    result: dict[str, list[dict[str, Any]]] = {}
    submitted_ids: set[str] = set()
    used_ids: set[str] = set(owners)

    for record_group_id, items in (incoming_records or {}).items():
        group_id = str(record_group_id)
        if not isinstance(items, list):
            result[group_id] = []
            continue

        existing_items = existing_section.get(group_id)
        if not isinstance(existing_items, list):
            existing_items = []

        normalized_items: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            normalized_item = deepcopy(item)
            internal_id = _clean_internal_id(normalized_item.get(INTERNAL_ID_FIELD))

            if internal_id:
                owner = owners.get(internal_id)
                if owner is None:
                    raise CanonRecordIdentityConflictError(
                        f"Unknown Canon record identity submitted: {internal_id}"
                    )
                if (
                    owner["section_id"] != canonical_section_id
                    or owner["record_group_id"] != group_id
                ):
                    raise CanonRecordIdentityConflictError(
                        f"Canon record identity cannot move between record groups: {internal_id}"
                    )
            else:
                fallback_id = _existing_identity_at_index(existing_items, index)
                if fallback_id and fallback_id not in submitted_ids:
                    internal_id = fallback_id
                else:
                    internal_id = _new_internal_id(group_id, used_ids)

            if internal_id in submitted_ids:
                raise CanonRecordIdentityConflictError(
                    f"Duplicate Canon record identity submitted: {internal_id}"
                )

            normalized_item[INTERNAL_ID_FIELD] = internal_id
            submitted_ids.add(internal_id)
            used_ids.add(internal_id)
            normalized_items.append(normalized_item)

        result[group_id] = normalized_items

    return result


def record_identity_findings(author_canon: dict[str, Any]) -> list[dict[str, Any]]:
    """Return missing/duplicate identity findings without mutating Canon."""

    findings: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    sections = author_canon.get("sections") if isinstance(author_canon, dict) else {}
    if not isinstance(sections, dict):
        return findings

    for section_id, section in sections.items():
        if not isinstance(section, dict):
            continue
        records = section.get("records")
        if not isinstance(records, dict):
            continue
        for record_group_id, items in records.items():
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                location = {
                    "section_id": str(section_id),
                    "record_group_id": str(record_group_id),
                    "index": index,
                }
                internal_id = _clean_internal_id(item.get(INTERNAL_ID_FIELD))
                if not internal_id:
                    findings.append(
                        {
                            "code": "missing_canon_record_identity",
                            "message": "Repeatable Canon record is missing its system identity.",
                            "details": location,
                        }
                    )
                    continue
                prior = seen.get(internal_id)
                if prior is not None:
                    findings.append(
                        {
                            "code": "duplicate_canon_record_identity",
                            "message": "Repeatable Canon records share the same system identity.",
                            "details": {
                                **location,
                                "internal_id": internal_id,
                                "first_occurrence": prior,
                            },
                        }
                    )
                    continue
                seen[internal_id] = location

    return findings


def strip_record_identity_metadata(value: Any) -> Any:
    """Deep-copy record content while removing system-only identity keys."""

    if isinstance(value, list):
        return [strip_record_identity_metadata(item) for item in value]
    if isinstance(value, dict):
        return {
            key: strip_record_identity_metadata(item)
            for key, item in value.items()
            if key != INTERNAL_ID_FIELD
        }
    return deepcopy(value)


def _report(
    changed: bool,
    record_count: int,
    unique_identity_count: int,
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "service": CANON_RECORD_IDENTITY_SERVICE_MARKER,
        "identity_version": CANON_RECORD_IDENTITY_VERSION,
        "identity_field": INTERNAL_ID_FIELD,
        "changed": bool(changed),
        "record_count": int(record_count),
        "unique_identity_count": int(unique_identity_count),
        "assigned_count": len(assignments),
        "assignments": assignments,
    }


def _clean_internal_id(value: Any) -> str:
    return str(value or "").strip()


def _record_prefix(record_group_id: str) -> str:
    return _RECORD_GROUP_PREFIXES.get(str(record_group_id or "").strip(), "rec")


def _deterministic_backfill_id(
    project_id: str,
    section_id: str,
    record_group_id: str,
    index: int,
    seen: dict[str, dict[str, Any]],
) -> str:
    prefix = _record_prefix(record_group_id)
    salt = 0
    while True:
        material = f"{project_id}|{section_id}|{record_group_id}|{index}|{salt}"
        candidate = f"{prefix}_{uuid5(_BACKFILL_NAMESPACE, material).hex}"
        if candidate not in seen:
            return candidate
        salt += 1


def _new_internal_id(record_group_id: str, used_ids: set[str]) -> str:
    prefix = _record_prefix(record_group_id)
    while True:
        candidate = f"{prefix}_{uuid4().hex}"
        if candidate not in used_ids:
            return candidate


def _claim_identity(
    internal_id: str,
    location: dict[str, Any],
    seen: dict[str, dict[str, Any]],
) -> None:
    prior = seen.get(internal_id)
    if prior is not None:
        raise CanonRecordIdentityConflictError(
            "Duplicate Canon record identity "
            f"{internal_id}: {prior} and {location}"
        )
    seen[internal_id] = location


def _identity_owners(author_canon: dict[str, Any]) -> dict[str, dict[str, Any]]:
    owners: dict[str, dict[str, Any]] = {}
    sections = author_canon.get("sections") if isinstance(author_canon, dict) else {}
    if not isinstance(sections, dict):
        return owners

    for section_id, section in sections.items():
        if not isinstance(section, dict):
            continue
        records = section.get("records")
        if not isinstance(records, dict):
            continue
        for record_group_id, items in records.items():
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                internal_id = _clean_internal_id(item.get(INTERNAL_ID_FIELD))
                if not internal_id:
                    continue
                location = {
                    "section_id": str(section_id),
                    "record_group_id": str(record_group_id),
                    "index": index,
                }
                _claim_identity(internal_id, location, owners)

    return owners


def _stored_section_records(
    author_canon: dict[str, Any],
    section_id: str,
) -> dict[str, list[dict[str, Any]]]:
    sections = author_canon.get("sections")
    if not isinstance(sections, dict):
        return {}
    section = sections.get(section_id)
    if not isinstance(section, dict):
        return {}
    records = section.get("records")
    return records if isinstance(records, dict) else {}


def _existing_identity_at_index(items: list[Any], index: int) -> str:
    if index < 0 or index >= len(items):
        return ""
    item = items[index]
    if not isinstance(item, dict):
        return ""
    return _clean_internal_id(item.get(INTERNAL_ID_FIELD))
