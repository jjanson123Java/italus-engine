"""
Stable Canon-to-Canon reference semantics for project-local Author Canon.

This service owns only schema-declared record references. It resolves legacy
human labels to Patch 14 ``internal_id`` values when the match is exact and
unique, validates reference submissions, produces author-facing reference
catalogs, and reports unresolved legacy values without inventing story truth.

It does not own record identity, Canon Index, Planner state, Book Scope,
generation, provider execution, or provenance.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from app.services import canon_record_identity_service


CANON_REFERENCE_SERVICE_MARKER = "canon-reference-hardening-boundary-20260816"
CANON_REFERENCE_SCHEMA_VERSION = "canon_reference_v1"

FIELD_RECORD_REF = "record_ref"
FIELD_RECORD_REF_LIST = "record_ref_list"
REFERENCE_FIELD_TYPES = {FIELD_RECORD_REF, FIELD_RECORD_REF_LIST}

INTERNAL_ID_FIELD = canon_record_identity_service.INTERNAL_ID_FIELD

_INTERNAL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{32}$")
_MULTI_VALUE_SPLIT_RE = re.compile(r"\s*(?:/|;|\||\n|,)\s*")


class CanonReferenceConflictError(ValueError):
    """Raised when a submitted stable Canon reference is invalid or ambiguous."""


def build_reference_catalog(
    author_canon: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    """Return author-facing selectable records keyed by record-group ID.

    Raw stable IDs are returned only as machine option values. Labels remain
    human-facing and are derived from existing author-owned record content.
    """

    entries = _reference_entries(author_canon, schema)
    catalog: dict[str, list[dict[str, str]]] = {}
    for group_id, group_entries in entries.items():
        catalog[group_id] = [
            {
                "record_id": entry["internal_id"],
                "label": entry["display_label"],
            }
            for entry in group_entries
        ]
    return catalog


def migrate_author_canon_references(
    author_canon: dict[str, Any],
    schema: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert resolvable legacy relationship text to stable internal IDs.

    A value is migrated only when every legacy token resolves to exactly one
    allowed record. Any unmatched or ambiguous value is preserved byte-for-byte
    in the returned Canon and is reported for author reconciliation.
    """

    normalized = deepcopy(author_canon if isinstance(author_canon, dict) else {})
    entries = _reference_entries(normalized, schema)
    resolution = _resolution_index(entries)

    migrated_fields = 0
    migrated_values = 0
    unresolved: list[dict[str, Any]] = []

    sections = normalized.get("sections")
    if not isinstance(sections, dict):
        return normalized, _migration_report(False, 0, 0, unresolved)

    for section_schema in _schema_sections(schema):
        section_id = str(section_schema.get("section_id") or "").strip()
        section = sections.get(section_id)
        if not isinstance(section, dict):
            continue
        stored_records = section.get("records")
        if not isinstance(stored_records, dict):
            continue

        for record_schema in _record_schemas(section_schema):
            group_id = str(record_schema.get("record_id") or "").strip()
            rows = stored_records.get(group_id)
            if not isinstance(rows, list):
                continue

            reference_fields = _reference_fields(record_schema)
            if not reference_fields:
                continue

            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                for field_schema in reference_fields:
                    field_id = str(field_schema.get("field_id") or "").strip()
                    if not field_id or field_id not in row:
                        continue

                    original = row.get(field_id)
                    if _is_blank(original):
                        continue

                    migrated, count, reason = _migrate_reference_value(
                        original,
                        field_schema=field_schema,
                        entries=entries,
                        resolution=resolution,
                    )
                    if reason is not None:
                        unresolved.append(
                            {
                                "code": "unresolved_legacy_canon_reference",
                                "section_id": section_id,
                                "record_group_id": group_id,
                                "record_index": index,
                                "field_id": field_id,
                                "field_label": str(field_schema.get("label") or field_id),
                                "legacy_value": deepcopy(original),
                                "reason": reason,
                                "missing_count": 1,
                            }
                        )
                        continue

                    if migrated != original:
                        row[field_id] = migrated
                        migrated_fields += 1
                        migrated_values += count

    return normalized, _migration_report(
        bool(migrated_fields),
        migrated_fields,
        migrated_values,
        unresolved,
    )


def normalize_section_references_for_save(
    *,
    section_id: str,
    section_schema: dict[str, Any],
    submitted_records: dict[str, list[dict[str, Any]]],
    author_canon: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Validate selector submissions while preserving unresolved legacy text.

    New/changed reference values must be known stable IDs. An unresolved legacy
    value created by migration may be submitted only unchanged; it cannot be
    edited into different free text through the selector surface.
    """

    result = deepcopy(submitted_records if isinstance(submitted_records, dict) else {})
    entries = _reference_entries(author_canon, schema)
    known_by_group = {
        group_id: {entry["internal_id"] for entry in group_entries}
        for group_id, group_entries in entries.items()
    }
    existing_rows = _stored_section_records(author_canon, section_id)

    for record_schema in _record_schemas(section_schema):
        group_id = str(record_schema.get("record_id") or "").strip()
        rows = result.get(group_id)
        if not isinstance(rows, list):
            continue
        existing_group_rows = existing_rows.get(group_id)
        if not isinstance(existing_group_rows, list):
            existing_group_rows = []
        existing_by_id = {
            str(row.get(INTERNAL_ID_FIELD) or "").strip(): row
            for row in existing_group_rows
            if isinstance(row, dict) and str(row.get(INTERNAL_ID_FIELD) or "").strip()
        }

        for row in rows:
            if not isinstance(row, dict):
                continue
            internal_id = str(row.get(INTERNAL_ID_FIELD) or "").strip()
            existing_row = existing_by_id.get(internal_id, {})
            for field_schema in _reference_fields(record_schema):
                field_id = str(field_schema.get("field_id") or "").strip()
                if not field_id:
                    continue
                submitted_value = row.get(field_id)
                existing_value = existing_row.get(field_id) if isinstance(existing_row, dict) else None
                row[field_id] = _normalize_submitted_value(
                    submitted_value,
                    existing_value=existing_value,
                    field_schema=field_schema,
                    known_by_group=known_by_group,
                )
    return result


def reference_validation_findings(
    author_canon: dict[str, Any],
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return blocking invalid-ID findings and warnings for unresolved legacy text."""

    findings: list[dict[str, Any]] = []
    entries = _reference_entries(author_canon, schema)
    known_by_group = {
        group_id: {entry["internal_id"] for entry in group_entries}
        for group_id, group_entries in entries.items()
    }

    sections = author_canon.get("sections") if isinstance(author_canon, dict) else {}
    if not isinstance(sections, dict):
        return findings

    for section_schema in _schema_sections(schema):
        section_id = str(section_schema.get("section_id") or "").strip()
        section = sections.get(section_id)
        if not isinstance(section, dict):
            continue
        stored_records = section.get("records")
        if not isinstance(stored_records, dict):
            continue

        for record_schema in _record_schemas(section_schema):
            group_id = str(record_schema.get("record_id") or "").strip()
            rows = stored_records.get(group_id)
            if not isinstance(rows, list):
                continue

            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                for field_schema in _reference_fields(record_schema):
                    field_id = str(field_schema.get("field_id") or "").strip()
                    value = row.get(field_id)
                    if _is_blank(value):
                        continue

                    unknown_ids, legacy_values = _classify_reference_values(
                        value,
                        field_schema=field_schema,
                        known_by_group=known_by_group,
                    )
                    if unknown_ids:
                        findings.append(
                            {
                                "code": "invalid_canon_reference",
                                "severity": "error",
                                "message": "Canon relationship contains an unknown system reference.",
                                "section_id": section_id,
                                "record_group_id": group_id,
                                "record_index": index,
                                "field_id": field_id,
                                "details": {"unknown_reference_count": len(unknown_ids)},
                            }
                        )
                    if legacy_values:
                        findings.append(
                            {
                                "code": "unresolved_legacy_canon_reference",
                                "severity": "warning",
                                "message": "Legacy relationship text still needs author reconciliation.",
                                "section_id": section_id,
                                "record_group_id": group_id,
                                "record_index": index,
                                "field_id": field_id,
                                "details": {"legacy_value": deepcopy(value)},
                            }
                        )
    return findings


def resolve_reference_display(
    value: Any,
    *,
    field_schema: dict[str, Any],
    catalog: dict[str, list[dict[str, str]]],
) -> str:
    """Render stable IDs as author-facing labels without leaking raw IDs."""

    label_by_id: dict[str, str] = {}
    for group_id in _reference_targets(field_schema):
        for item in catalog.get(group_id, []):
            if not isinstance(item, dict):
                continue
            internal_id = str(item.get("record_id") or "").strip()
            if internal_id:
                label_by_id[internal_id] = str(item.get("label") or "Canon record")

    values = value if isinstance(value, list) else [value]
    rendered: list[str] = []
    for item in values:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        if cleaned in label_by_id:
            rendered.append(label_by_id[cleaned])
        elif _looks_like_internal_id(cleaned):
            rendered.append("Unresolved Canon reference")
        else:
            rendered.append(cleaned)
    return ", ".join(rendered)


def _reference_entries(
    author_canon: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    entries: dict[str, list[dict[str, Any]]] = {}
    sections = author_canon.get("sections") if isinstance(author_canon, dict) else {}
    if not isinstance(sections, dict):
        return entries

    for section_schema in _schema_sections(schema):
        section_id = str(section_schema.get("section_id") or "").strip()
        section = sections.get(section_id)
        if not isinstance(section, dict):
            continue
        stored_records = section.get("records")
        if not isinstance(stored_records, dict):
            continue

        for record_schema in _record_schemas(section_schema):
            group_id = str(record_schema.get("record_id") or "").strip()
            if not group_id:
                continue
            rows = stored_records.get(group_id)
            if not isinstance(rows, list):
                continue
            group_entries = entries.setdefault(group_id, [])
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                internal_id = str(row.get(INTERNAL_ID_FIELD) or "").strip()
                if not internal_id:
                    continue
                match_values = _match_values(group_id, row)
                group_entries.append(
                    {
                        "internal_id": internal_id,
                        "display_label": _display_label(group_id, row, index),
                        "match_values": match_values,
                    }
                )
    return entries


def _resolution_index(
    entries: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, set[str]]]:
    result: dict[str, dict[str, set[str]]] = {}
    for group_id, group_entries in entries.items():
        group_index: dict[str, set[str]] = {}
        for entry in group_entries:
            internal_id = str(entry.get("internal_id") or "").strip()
            for raw in entry.get("match_values", []):
                key = _match_key(raw)
                if not key:
                    continue
                group_index.setdefault(key, set()).add(internal_id)
        result[group_id] = group_index
    return result


def _migrate_reference_value(
    value: Any,
    *,
    field_schema: dict[str, Any],
    entries: dict[str, list[dict[str, Any]]],
    resolution: dict[str, dict[str, set[str]]],
) -> tuple[Any, int, str | None]:
    targets = _reference_targets(field_schema)
    known_ids = {
        entry["internal_id"]
        for target in targets
        for entry in entries.get(target, [])
    }

    field_type = str(field_schema.get("field_type") or "")
    if field_type == FIELD_RECORD_REF:
        cleaned = str(value or "").strip()
        if not cleaned:
            return "", 0, None
        if cleaned in known_ids:
            return cleaned, 0, None
        resolved, reason = _resolve_legacy_token(cleaned, targets, resolution)
        return (resolved, 1, None) if resolved else (deepcopy(value), 0, reason)

    if field_type != FIELD_RECORD_REF_LIST:
        return deepcopy(value), 0, "unsupported_reference_field_type"

    original = deepcopy(value)
    raw_values = value if isinstance(value, list) else [value]
    cleaned_values = [str(item or "").strip() for item in raw_values if str(item or "").strip()]
    if not cleaned_values:
        return [], 0, None
    if all(item in known_ids for item in cleaned_values):
        return _dedupe(cleaned_values), 0, None

    tokens: list[str] = []
    for item in cleaned_values:
        if item in known_ids:
            tokens.append(item)
            continue
        exact, exact_reason = _resolve_legacy_token(item, targets, resolution)
        if exact:
            tokens.append(exact)
            continue

        split = [part for part in _MULTI_VALUE_SPLIT_RE.split(item) if part]
        if len(split) <= 1:
            return original, 0, exact_reason

        resolved_split: list[str] = []
        for part in split:
            resolved, reason = _resolve_legacy_token(part, targets, resolution)
            if not resolved:
                return original, 0, reason
            resolved_split.append(resolved)
        tokens.extend(resolved_split)

    return _dedupe(tokens), len(_dedupe(tokens)), None


def _resolve_legacy_token(
    token: str,
    targets: list[str],
    resolution: dict[str, dict[str, set[str]]],
) -> tuple[str | None, str]:
    key = _match_key(token)
    if not key:
        return None, "empty_reference"
    matches: set[str] = set()
    for target in targets:
        matches.update(resolution.get(target, {}).get(key, set()))
    if len(matches) == 1:
        return next(iter(matches)), ""
    if len(matches) > 1:
        return None, "ambiguous_legacy_label"
    return None, "unmatched_legacy_label"


def _normalize_submitted_value(
    submitted_value: Any,
    *,
    existing_value: Any,
    field_schema: dict[str, Any],
    known_by_group: dict[str, set[str]],
) -> Any:
    targets = _reference_targets(field_schema)
    known_ids = set().union(*(known_by_group.get(group_id, set()) for group_id in targets))
    field_type = str(field_schema.get("field_type") or "")

    if field_type == FIELD_RECORD_REF:
        cleaned = str(submitted_value or "").strip()
        if not cleaned:
            return ""
        if cleaned in known_ids:
            return cleaned
        if _same_legacy_value(submitted_value, existing_value):
            return deepcopy(existing_value)
        raise CanonReferenceConflictError(
            "Canon relationship selector submitted an unknown record reference."
        )

    if field_type == FIELD_RECORD_REF_LIST:
        values = submitted_value if isinstance(submitted_value, list) else [submitted_value]
        cleaned = [str(item or "").strip() for item in values if str(item or "").strip()]
        if not cleaned:
            return []
        if all(item in known_ids for item in cleaned):
            return _dedupe(cleaned)
        if _same_legacy_value(submitted_value, existing_value):
            return deepcopy(existing_value)
        raise CanonReferenceConflictError(
            "Canon relationship selector submitted an unknown record reference."
        )

    return deepcopy(submitted_value)


def _same_legacy_value(submitted: Any, existing: Any) -> bool:
    if submitted == existing:
        return True
    if isinstance(existing, str) and isinstance(submitted, list) and len(submitted) == 1:
        return str(submitted[0]) == existing
    if isinstance(submitted, str) and isinstance(existing, list) and len(existing) == 1:
        return submitted == str(existing[0])
    return False


def _classify_reference_values(
    value: Any,
    *,
    field_schema: dict[str, Any],
    known_by_group: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    targets = _reference_targets(field_schema)
    known_ids = set().union(*(known_by_group.get(group_id, set()) for group_id in targets))
    values = value if isinstance(value, list) else [value]
    unknown_ids: list[str] = []
    legacy: list[str] = []
    for item in values:
        cleaned = str(item or "").strip()
        if not cleaned or cleaned in known_ids:
            continue
        if _looks_like_internal_id(cleaned):
            unknown_ids.append(cleaned)
        else:
            legacy.append(cleaned)
    return unknown_ids, legacy


def _reference_fields(record_schema: dict[str, Any]) -> list[dict[str, Any]]:
    fields = record_schema.get("fields")
    if not isinstance(fields, list):
        return []
    return [
        field
        for field in fields
        if isinstance(field, dict)
        and str(field.get("field_type") or "") in REFERENCE_FIELD_TYPES
    ]


def _reference_targets(field_schema: dict[str, Any]) -> list[str]:
    targets = field_schema.get("reference_targets")
    if not isinstance(targets, list):
        return []
    return [str(item).strip() for item in targets if str(item).strip()]


def _schema_sections(schema: dict[str, Any]) -> list[dict[str, Any]]:
    sections = schema.get("sections") if isinstance(schema, dict) else []
    return [item for item in sections if isinstance(item, dict)] if isinstance(sections, list) else []


def _record_schemas(section_schema: dict[str, Any]) -> list[dict[str, Any]]:
    records = section_schema.get("records")
    return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []


def _stored_section_records(
    author_canon: dict[str, Any],
    section_id: str,
) -> dict[str, list[dict[str, Any]]]:
    sections = author_canon.get("sections") if isinstance(author_canon, dict) else {}
    section = sections.get(section_id) if isinstance(sections, dict) else {}
    records = section.get("records") if isinstance(section, dict) else {}
    return records if isinstance(records, dict) else {}


def _match_values(group_id: str, row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    preferred = {
        "characters": ["name", "aliases"],
        "locations": ["name"],
        "events": ["story_code", "date_or_sequence", "event_summary"],
        "life_events": ["story_code", "date_or_sequence", "event_summary"],
    }.get(group_id, ["name", "label", "title", "story_code", "code"])

    for field_id in preferred:
        raw = row.get(field_id)
        if _is_blank(raw):
            continue
        if field_id == "aliases":
            values.extend(_alias_values(raw))
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item or "").strip())
        else:
            values.append(str(raw))
    return _dedupe_text(values)


def _alias_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [
        part.strip()
        for part in re.split(r"\s*(?:,|;|\||\n)\s*", text)
        if part.strip()
    ]


def _display_label(group_id: str, row: dict[str, Any], index: int) -> str:
    candidates = {
        "characters": ["name", "aliases"],
        "locations": ["name", "region"],
        "events": ["story_code", "date_or_sequence", "event_summary"],
        "life_events": ["story_code", "date_or_sequence", "event_summary"],
    }.get(group_id, ["name", "label", "title", "story_code", "code"])
    for field_id in candidates:
        value = row.get(field_id)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if str(item or "").strip())
        cleaned = str(value or "").strip()
        if cleaned:
            if len(cleaned) > 120:
                cleaned = cleaned[:117].rstrip() + "..."
            return cleaned
    return f"{_humanize(group_id)} {index + 1}"


def _humanize(value: str) -> str:
    return str(value or "record").replace("_", " ").strip().title()


def _match_key(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dedupe_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        key = _match_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _looks_like_internal_id(value: str) -> bool:
    return bool(_INTERNAL_ID_RE.fullmatch(str(value or "").strip()))


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _migration_report(
    changed: bool,
    migrated_field_count: int,
    migrated_value_count: int,
    unresolved: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "service": CANON_REFERENCE_SERVICE_MARKER,
        "schema_version": CANON_REFERENCE_SCHEMA_VERSION,
        "changed": bool(changed),
        "migrated_reference_field_count": int(migrated_field_count),
        "migrated_reference_value_count": int(migrated_value_count),
        "unresolved_count": len(unresolved),
        "unresolved": deepcopy(unresolved),
        "author_story_content_modified": False,
        "author_truth_invented": False,
    }
