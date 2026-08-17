"""
Project-local canon authoring workflow service.

This service coordinates future author-facing canon questionnaire work. It
loads questionnaire schemas, ensures project-local author canon storage, saves
section drafts, marks sections complete when required data is present, and
reopens completed sections.

It does not render Markdown, generate knowledge/control packs, call prompt
construction, call providers, write runtime memory, or unlock generation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import canon_record_identity_service, canon_reference_service, canon_template_service, project_canon_service


CANON_AUTHORING_SERVICE_MARKER = "project-canon-authoring-workflow-boundary-20260715"
CANON_AUTHORING_SCHEMA_VERSION = "project_canon_authoring_workflow_v1"


class CanonSectionNotFoundError(ValueError):
    """Raised when a canon questionnaire section does not exist."""


class CanonSectionIncompleteError(ValueError):
    """Raised when a section cannot be marked complete."""


CanonRecordIdentityConflictError = canon_record_identity_service.CanonRecordIdentityConflictError
CanonReferenceConflictError = canon_reference_service.CanonReferenceConflictError


def get_canon_authoring_status(project_id: str) -> dict[str, Any]:
    """Return project-local canon authoring workflow status."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_canon_authoring_status_for_context(context, manifest.to_dict())


def get_canon_authoring_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return authoring status for an existing project context."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    author_canon = _load_author_canon_for_context(context)
    completion = _load_completion_for_context(context)
    section_status = completion.get("section_status") or {}

    required_count = int(completion.get("required_section_count") or 0)
    completed_required_count = int(completion.get("completed_required_section_count") or 0)

    return {
        "status": "ok",
        "service": CANON_AUTHORING_SERVICE_MARKER,
        "schema_version": CANON_AUTHORING_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": schema.get("template_id"),
        "genre": schema.get("genre"),
        "author_canon_status": author_canon.get("status", "draft"),
        "section_count": len(schema.get("sections", [])),
        "required_section_count": required_count,
        "completed_required_section_count": completed_required_count,
        "all_required_sections_complete": required_count > 0 and completed_required_count >= required_count,
        "template_migration": project_canon_service.get_template_snapshot_migration_status_for_context(
            context,
            manifest,
        ),
        "sections": [
            _section_summary(
                section,
                section_status.get(str(section.get("section_id") or ""), {}),
                _stored_section(author_canon, str(section.get("section_id") or "")),
            )
            for section in schema.get("sections", [])
            if section.get("section_id")
        ],
        "execution_locks": _execution_locks(),
    }


def get_canon_section(project_id: str, section_id: str) -> dict[str, Any]:
    """Return a single canon authoring section with saved draft data."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    schema = _template_schema_for_manifest(manifest.to_dict())
    return get_canon_section_for_context(context, manifest.to_dict(), section_id, schema)


def get_canon_section_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    section_id: str,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a canon section for an existing project context."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    section_schema = _section_schema(schema, section_id)
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    author_canon = _load_author_canon_for_context(context)
    completion = _load_completion_for_context(context)
    stored_section = _stored_section(author_canon, section_schema["section_id"])
    completion_record = dict(
        (completion.get("section_status") or {}).get(section_schema["section_id"], {})
    )
    completion_record["missing_required_fields"] = _missing_required_fields(
        section_schema,
        stored_section,
    )

    return {
        "status": "ok",
        "service": CANON_AUTHORING_SERVICE_MARKER,
        "project_id": context.project_id,
        "template_id": schema.get("template_id"),
        "genre": schema.get("genre"),
        "section": {
            "schema": deepcopy(section_schema),
            "data": deepcopy(stored_section),
            "completion": deepcopy(completion_record),
        },
        "reference_catalog": canon_reference_service.build_reference_catalog(author_canon, schema),
        "execution_locks": _execution_locks(),
    }


def save_canon_section_draft(project_id: str, section_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Save draft answers for one canon section.

    The payload may contain "answers" and "records". Existing section data is
    replaced for the selected section only.
    """

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    schema = _template_schema_for_manifest(manifest.to_dict())
    return save_canon_section_draft_for_context(context, manifest.to_dict(), section_id, payload, schema)


def save_canon_section_draft_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    section_id: str,
    payload: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Save draft section data for an existing project context."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    section_schema = _section_schema(schema, section_id)
    canonical_section_id = section_schema["section_id"]
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    author_canon = _load_author_canon_for_context(context)
    completion = _load_completion_for_context(context)
    now = utc_now_iso()

    sections = dict(author_canon.get("sections") or {})
    incoming = payload or {}
    cleaned_records = _clean_records(incoming.get("records"))
    normalized_records = canon_record_identity_service.reconcile_section_record_identities(
        context.project_id,
        canonical_section_id,
        author_canon,
        cleaned_records,
    )
    normalized_records = canon_reference_service.normalize_section_references_for_save(
        section_id=canonical_section_id,
        section_schema=section_schema,
        submitted_records=normalized_records,
        author_canon=author_canon,
        schema=schema,
    )
    normalized_section = {
        "section_id": canonical_section_id,
        "status": "draft",
        "answers": _clean_mapping(incoming.get("answers")),
        "records": normalized_records,
        "updated_at": now,
    }
    sections[canonical_section_id] = normalized_section
    author_canon["sections"] = sections
    author_canon["status"] = "draft"
    _touch_metadata(author_canon, now)

    missing = _missing_required_fields(section_schema, normalized_section)
    completion = _set_completion_record(
        completion,
        section_schema,
        status="draft",
        missing_required_fields=missing,
        updated_at=now,
    )
    completion = _recalculate_completion(schema, completion)
    _touch_metadata(completion, now)

    project_loader.write_json(project_canon_service.author_canon_path_for_context(context), author_canon)
    project_loader.write_json(project_canon_service.canon_completion_path_for_context(context), completion)

    return {
        "status": "ok",
        "service": CANON_AUTHORING_SERVICE_MARKER,
        "project_id": context.project_id,
        "section_id": canonical_section_id,
        "section_status": "draft",
        "missing_required_fields": missing,
        "section": deepcopy(normalized_section),
        "completion": _completion_summary(completion),
        "execution_locks": _execution_locks(),
    }


def revalidate_canon_completion(project_id: str) -> dict[str, Any]:
    """Revalidate Canon Setup completion against the current project template snapshot."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    schema = _template_schema_for_manifest(manifest.to_dict())
    return revalidate_canon_completion_for_context(
        context,
        manifest.to_dict(),
        schema,
    )


def revalidate_canon_completion_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Revalidate completion metadata without changing author-entered canon values."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    author_canon = _load_author_canon_for_context(context)
    completion = _load_completion_for_context(context)
    previous_status = dict(completion.get("section_status") or {})
    now = utc_now_iso()

    for section_schema in schema.get("sections", []):
        if not isinstance(section_schema, dict):
            continue
        section_id = str(section_schema.get("section_id") or "").strip()
        if not section_id:
            continue

        stored = _stored_section(author_canon, section_id)
        missing = _missing_required_fields(section_schema, stored)
        prior = dict(previous_status.get(section_id) or {})
        prior_status = str(prior.get("status") or stored.get("status") or "not_started")

        if prior_status == "complete":
            status = "complete" if not missing else "blocked"
        elif prior_status == "blocked":
            status = "draft" if not missing else "blocked"
        elif prior_status in {"draft", "not_started"}:
            status = prior_status
        else:
            status = "draft" if stored.get("status") == "draft" else "not_started"

        completion = _set_completion_record(
            completion,
            section_schema,
            status=status,
            missing_required_fields=missing,
            updated_at=now,
        )

    completion = _recalculate_completion(schema, completion)
    _touch_metadata(completion, now)
    project_loader.write_json(
        project_canon_service.canon_completion_path_for_context(context),
        completion,
    )

    return {
        "status": "ok",
        "service": CANON_AUTHORING_SERVICE_MARKER,
        "project_id": context.project_id,
        "template_version": schema.get("version"),
        "completion": _completion_summary(completion),
        "sections": deepcopy(completion.get("section_status") or {}),
        "author_canon_modified": False,
        "execution_locks": _execution_locks(),
    }


def mark_canon_section_complete(project_id: str, section_id: str) -> dict[str, Any]:
    """Mark a canon section complete if required fields are present."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    schema = _template_schema_for_manifest(manifest.to_dict())
    return mark_canon_section_complete_for_context(context, manifest.to_dict(), section_id, schema)


def mark_canon_section_complete_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    section_id: str,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark a canon section complete for an existing project context."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    section_schema = _section_schema(schema, section_id)
    canonical_section_id = section_schema["section_id"]
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    author_canon = _load_author_canon_for_context(context)
    completion = _load_completion_for_context(context)
    stored = _stored_section(author_canon, canonical_section_id)
    missing = _missing_required_fields(section_schema, stored)

    if missing:
        completion = _set_completion_record(
            completion,
            section_schema,
            status="blocked",
            missing_required_fields=missing,
            updated_at=utc_now_iso(),
        )
        completion = _recalculate_completion(schema, completion)
        project_loader.write_json(project_canon_service.canon_completion_path_for_context(context), completion)
        return {
            "status": "blocked",
            "service": CANON_AUTHORING_SERVICE_MARKER,
            "project_id": context.project_id,
            "section_id": canonical_section_id,
            "message": "Section has missing required fields.",
            "missing_required_fields": missing,
            "completion": _completion_summary(completion),
            "execution_locks": _execution_locks(),
        }

    now = utc_now_iso()
    stored["status"] = "complete"
    stored["updated_at"] = now
    author_canon.setdefault("sections", {})[canonical_section_id] = stored
    _touch_metadata(author_canon, now)

    completion = _set_completion_record(
        completion,
        section_schema,
        status="complete",
        missing_required_fields=[],
        updated_at=now,
    )
    completion = _recalculate_completion(schema, completion)
    _touch_metadata(completion, now)

    project_loader.write_json(project_canon_service.author_canon_path_for_context(context), author_canon)
    project_loader.write_json(project_canon_service.canon_completion_path_for_context(context), completion)

    return {
        "status": "ok",
        "service": CANON_AUTHORING_SERVICE_MARKER,
        "project_id": context.project_id,
        "section_id": canonical_section_id,
        "section_status": "complete",
        "missing_required_fields": [],
        "completion": _completion_summary(completion),
        "execution_locks": _execution_locks(),
    }


def reopen_canon_section(project_id: str, section_id: str) -> dict[str, Any]:
    """Reopen a completed canon section for editing."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    schema = _template_schema_for_manifest(manifest.to_dict())
    return reopen_canon_section_for_context(context, manifest.to_dict(), section_id, schema)


def reopen_canon_section_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    section_id: str,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reopen a canon section for an existing project context."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    section_schema = _section_schema(schema, section_id)
    canonical_section_id = section_schema["section_id"]
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    author_canon = _load_author_canon_for_context(context)
    completion = _load_completion_for_context(context)
    stored = _stored_section(author_canon, canonical_section_id)
    now = utc_now_iso()

    stored["status"] = "draft"
    stored["updated_at"] = now
    author_canon.setdefault("sections", {})[canonical_section_id] = stored
    _touch_metadata(author_canon, now)

    missing = _missing_required_fields(section_schema, stored)
    completion = _set_completion_record(
        completion,
        section_schema,
        status="draft",
        missing_required_fields=missing,
        updated_at=now,
    )
    completion = _recalculate_completion(schema, completion)
    _touch_metadata(completion, now)

    project_loader.write_json(project_canon_service.author_canon_path_for_context(context), author_canon)
    project_loader.write_json(project_canon_service.canon_completion_path_for_context(context), completion)

    return {
        "status": "ok",
        "service": CANON_AUTHORING_SERVICE_MARKER,
        "project_id": context.project_id,
        "section_id": canonical_section_id,
        "section_status": "draft",
        "missing_required_fields": missing,
        "completion": _completion_summary(completion),
        "execution_locks": _execution_locks(),
    }


def _template_schema_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    project_id = str(manifest.get("project_id") or "").strip()
    if project_id:
        context = build_project_context(project_loader.load_manifest(project_id))
        return project_canon_service.effective_template_schema_for_context(
            context,
            manifest,
        )
    return canon_template_service.get_canon_questionnaire_template(
        manifest.get("template_id"),
        manifest.get("genre"),
    )


def _load_author_canon_for_context(context: ProjectContext) -> dict[str, Any]:
    data = project_loader.read_json(project_canon_service.author_canon_path_for_context(context), default={})
    return data if isinstance(data, dict) else {}


def _load_completion_for_context(context: ProjectContext) -> dict[str, Any]:
    data = project_loader.read_json(project_canon_service.canon_completion_path_for_context(context), default={})
    return data if isinstance(data, dict) else {}


def _section_schema(schema: dict[str, Any], section_id: str) -> dict[str, Any]:
    wanted = str(section_id or "").strip()
    for section in schema.get("sections", []):
        if str(section.get("section_id") or "").strip() == wanted:
            return deepcopy(section)
    raise CanonSectionNotFoundError(f"Unknown canon section: {section_id}")


def _stored_section(author_canon: dict[str, Any], section_id: str) -> dict[str, Any]:
    sections = author_canon.setdefault("sections", {})
    stored = sections.get(section_id)
    if not isinstance(stored, dict):
        stored = {
            "section_id": section_id,
            "status": "not_started",
            "answers": {},
            "records": {},
            "updated_at": None,
        }
        sections[section_id] = stored

    if not isinstance(stored.get("answers"), dict):
        stored["answers"] = {}
    if not isinstance(stored.get("records"), dict):
        stored["records"] = {}
    stored.setdefault("section_id", section_id)
    stored.setdefault("status", "not_started")
    stored.setdefault("updated_at", None)
    return stored


def _required_field_ids(section_schema: dict[str, Any]) -> list[str]:
    required: list[str] = []

    for field in section_schema.get("fields", []):
        if field.get("required"):
            required.append(str(field.get("field_id")))

    for record in section_schema.get("records", []):
        if record.get("required"):
            record_id = str(record.get("record_id") or "record")
            min_items = int(record.get("min_items") or 0)
            if min_items > 0:
                required.append(f"{record_id}.__min_items__")
            for field in record.get("fields", []):
                if field.get("required"):
                    required.append(f"{record_id}.{field.get('field_id')}")

    return required


def _missing_required_fields(section_schema: dict[str, Any], section_data: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    answers = section_data.get("answers") if isinstance(section_data.get("answers"), dict) else {}
    records = section_data.get("records") if isinstance(section_data.get("records"), dict) else {}

    for field in section_schema.get("fields", []):
        if not field.get("required"):
            continue
        field_id = str(field.get("field_id") or "").strip()
        if field_id and _is_blank(answers.get(field_id)):
            missing.append(field_id)

    for record_schema in section_schema.get("records", []):
        if not record_schema.get("required"):
            continue
        record_id = str(record_schema.get("record_id") or "record")
        items = records.get(record_id)
        if not isinstance(items, list):
            items = []
        min_items = int(record_schema.get("min_items") or 0)
        if min_items > 0 and len(items) < min_items:
            missing.append(f"{record_id}.__min_items__")
        required_record_fields = [
            str(field.get("field_id") or "").strip()
            for field in record_schema.get("fields", [])
            if field.get("required") and str(field.get("field_id") or "").strip()
        ]
        if required_record_fields:
            if not items:
                for field_id in required_record_fields:
                    missing.append(f"{record_id}.{field_id}")
            else:
                for index, item in enumerate(items):
                    item_dict = item if isinstance(item, dict) else {}
                    for field_id in required_record_fields:
                        if _is_blank(item_dict.get(field_id)):
                            missing.append(f"{record_id}[{index}].{field_id}")

    return _unique(missing)


def _clean_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): deepcopy(val) for key, val in value.items()}


def _clean_records(value: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for key, records in value.items():
        record_id = str(key)
        if not isinstance(records, list):
            cleaned[record_id] = []
            continue
        cleaned[record_id] = [
            deepcopy(record)
            for record in records
            if isinstance(record, dict)
        ]
    return cleaned


def _set_completion_record(
    completion: dict[str, Any],
    section_schema: dict[str, Any],
    *,
    status: str,
    missing_required_fields: list[str],
    updated_at: str,
) -> dict[str, Any]:
    section_id = str(section_schema.get("section_id"))
    section_status = dict(completion.get("section_status") or {})
    section_status[section_id] = {
        "section_id": section_id,
        "required": bool(section_schema.get("required")),
        "status": status,
        "missing_required_fields": list(missing_required_fields),
        "updated_at": updated_at,
    }
    completion["section_status"] = section_status
    return completion


def _recalculate_completion(schema: dict[str, Any], completion: dict[str, Any]) -> dict[str, Any]:
    section_status = dict(completion.get("section_status") or {})
    required_count = 0
    completed_required_count = 0

    for section in schema.get("sections", []):
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        required = bool(section.get("required"))
        record = dict(section_status.get(section_id) or {})
        if not record:
            record = {
                "section_id": section_id,
                "required": required,
                "status": "not_started",
                "missing_required_fields": _required_field_ids(section),
            }
        record["required"] = required
        section_status[section_id] = record
        if required:
            required_count += 1
            if record.get("status") == "complete" and not record.get("missing_required_fields"):
                completed_required_count += 1

    completion["required_section_count"] = required_count
    completion["completed_required_section_count"] = completed_required_count
    completion["section_status"] = section_status
    completion["all_required_sections_complete"] = required_count > 0 and completed_required_count >= required_count
    completion.setdefault("schema_version", CANON_AUTHORING_SCHEMA_VERSION)
    completion.setdefault("execution_locks", _execution_locks())
    return completion


def _completion_summary(completion: dict[str, Any]) -> dict[str, Any]:
    required_count = int(completion.get("required_section_count") or 0)
    completed_count = int(completion.get("completed_required_section_count") or 0)
    return {
        "required_section_count": required_count,
        "completed_required_section_count": completed_count,
        "all_required_sections_complete": required_count > 0 and completed_count >= required_count,
    }


def _section_summary(
    section: dict[str, Any],
    completion_record: dict[str, Any],
    stored_section: dict[str, Any],
) -> dict[str, Any]:
    missing_required_fields = _missing_required_fields(section, stored_section)

    return {
        "section_id": section.get("section_id"),
        "label": section.get("label"),
        "required": bool(section.get("required")),
        "status": completion_record.get("status", stored_section.get("status", "not_started")),
        "missing_required_fields": missing_required_fields,
        "field_count": len(section.get("fields", [])),
        "record_count": len(section.get("records", [])),
    }


def _touch_metadata(payload: dict[str, Any], timestamp: str) -> None:
    metadata = dict(payload.get("metadata") or {})
    metadata.setdefault("created_at", timestamp)
    metadata["updated_at"] = timestamp
    metadata["source"] = CANON_AUTHORING_SERVICE_MARKER
    payload["metadata"] = metadata


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _execution_locks() -> dict[str, bool]:
    return {
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "draft_validation_enabled": False,
        "approved_persistence_enabled": False,
        "export_enabled": False,
    }
