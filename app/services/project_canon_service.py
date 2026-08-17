"""
Project-local author canon storage service.

This service is the storage boundary for future author-facing canon
questionnaire answers. It creates and reads project-local author canon JSON
artifacts only.

It does not render Markdown, generate knowledge/control packs, call prompt
construction, call providers, write runtime memory, or unlock generation.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import canon_record_identity_service, canon_reference_service, canon_template_service


PROJECT_CANON_SERVICE_MARKER = "project-local-author-canon-storage-boundary-20260715"
PROJECT_CANON_SCHEMA_VERSION = "project_author_canon_v1"
TEMPLATE_SNAPSHOT_MIGRATION_MARKER = "project-template-snapshot-migration-v1"
TEMPLATE_MIGRATION_REPORT_FILENAME = "template_migration_report.json"
CANON_REFERENCE_MIGRATION_REPORT_FILENAME = "canon_reference_migration_report.json"

LEGACY_TECHNICAL_FIELD_IDS = {"event_id", "item_id", "clue_id"}
NONUNIVERSAL_HISTORICAL_FIELD_IDS = {"event_type", "historical_status"}


class TemplateSnapshotMigrationConflictError(ValueError):
    """Raised when a project template snapshot cannot be upgraded safely."""


def project_canon_dir(project_id: str, *, create: bool = False) -> Path:
    """Return the project-local author canon directory."""

    path = project_loader.project_dir(project_id, create=True) / "canon"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def project_canon_dir_for_context(context: ProjectContext, *, create: bool = False) -> Path:
    """Return the project-local author canon directory for an existing context."""

    path = context.project_dir / "canon"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def author_canon_path(project_id: str) -> Path:
    """Return the project-local author canon JSON path."""

    return project_canon_dir(project_id) / "author_canon.json"


def template_snapshot_path(project_id: str) -> Path:
    """Return the project-local canon template snapshot path."""

    return project_canon_dir(project_id) / "template_snapshot.json"


def canon_completion_path(project_id: str) -> Path:
    """Return the project-local canon completion status path."""

    return project_canon_dir(project_id) / "canon_completion.json"


def author_canon_path_for_context(context: ProjectContext) -> Path:
    """Return the author canon JSON path for an existing context."""

    return project_canon_dir_for_context(context) / "author_canon.json"


def template_snapshot_path_for_context(context: ProjectContext) -> Path:
    """Return the template snapshot JSON path for an existing context."""

    return project_canon_dir_for_context(context) / "template_snapshot.json"


def canon_completion_path_for_context(context: ProjectContext) -> Path:
    """Return the completion status JSON path for an existing context."""

    return project_canon_dir_for_context(context) / "canon_completion.json"


def template_migration_report_path_for_context(context: ProjectContext) -> Path:
    """Return the project-local template migration report path."""

    return project_canon_dir_for_context(context) / TEMPLATE_MIGRATION_REPORT_FILENAME


def canon_reference_migration_report_path_for_context(context: ProjectContext) -> Path:
    """Return the project-local Canon reference migration report path."""

    return project_canon_dir_for_context(context) / CANON_REFERENCE_MIGRATION_REPORT_FILENAME


def effective_template_schema_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return the immutable project snapshot when present.

    Existing projects may contain project-specific modules that are not part of
    the generic genre template. The snapshot is the schema authority after
    project creation. New projects fall back to the active template service.
    """

    snapshot = _load_json_if_present(
        template_snapshot_path_for_context(context),
        default={},
    )
    questionnaire = (
        snapshot.get("questionnaire")
        if isinstance(snapshot.get("questionnaire"), dict)
        else None
    )
    if questionnaire:
        return deepcopy(questionnaire)

    return _template_schema_for_manifest(manifest)


def _verify_canon_reference_migration_persistence(
    context: ProjectContext,
    *,
    expected_template_version: str,
) -> dict[str, Any]:
    """Re-read Patch 15 migration artifacts and verify they were durably written."""

    snapshot_path = template_snapshot_path_for_context(context)
    template_report_path = template_migration_report_path_for_context(context)
    reference_report_path = canon_reference_migration_report_path_for_context(context)

    snapshot = _load_json_if_present(snapshot_path, default={})
    questionnaire = (
        snapshot.get("questionnaire")
        if isinstance(snapshot.get("questionnaire"), dict)
        else {}
    )
    persisted_version = str(questionnaire.get("version") or "").strip()

    template_report = _load_json_if_present(template_report_path, default={})
    reference_report = _load_json_if_present(reference_report_path, default={})

    snapshot_verified = bool(
        snapshot_path.exists()
        and persisted_version == expected_template_version
    )
    template_report_verified = bool(
        template_report_path.exists()
        and str(template_report.get("project_id") or "").strip() == context.project_id
        and str(template_report.get("to_template_version") or "").strip()
        == expected_template_version
    )
    reference_report_verified = bool(
        reference_report_path.exists()
        and str(reference_report.get("status") or "").strip() == "ok"
        and str(reference_report.get("service") or "").strip()
        == canon_reference_service.CANON_REFERENCE_SERVICE_MARKER
        and str(reference_report.get("schema_version") or "").strip()
        == canon_reference_service.CANON_REFERENCE_SCHEMA_VERSION
        and str(reference_report.get("project_id") or "").strip() == context.project_id
        and reference_report.get("author_truth_invented") is False
    )

    archive_verified = True
    archive_relative = str(reference_report.get("archive_path") or "").strip()
    if bool(reference_report.get("author_canon_modified")):
        archive_verified = bool(
            archive_relative
            and (context.project_dir / archive_relative).exists()
        )

    verified = bool(
        snapshot_verified
        and template_report_verified
        and reference_report_verified
        and archive_verified
    )

    return {
        "verified": verified,
        "snapshot_verified": snapshot_verified,
        "template_report_verified": template_report_verified,
        "reference_report_verified": reference_report_verified,
        "author_archive_verified": archive_verified,
        "expected_template_version": expected_template_version,
        "persisted_template_version": persisted_version or None,
        "template_snapshot_path": _relative(snapshot_path, context.project_dir),
        "template_migration_report_path": _relative(template_report_path, context.project_dir),
        "reference_migration_report_path": _relative(reference_report_path, context.project_dir),
    }


def get_template_snapshot_migration_status(project_id: str) -> dict[str, Any]:
    """Return read-only template snapshot migration status for one project."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_template_snapshot_migration_status_for_context(context, manifest.to_dict())


def get_template_snapshot_migration_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compare the project-local snapshot with the active template and persisted migration state."""

    snapshot_path = template_snapshot_path_for_context(context)
    snapshot = _load_json_if_present(snapshot_path, default={})
    questionnaire = (
        snapshot.get("questionnaire")
        if isinstance(snapshot.get("questionnaire"), dict)
        else {}
    )
    active = _template_schema_for_manifest(manifest)

    current_template_id = str(
        questionnaire.get("template_id")
        or snapshot.get("template_id")
        or ""
    ).strip()
    active_template_id = str(active.get("template_id") or "").strip()
    current_version = str(questionnaire.get("version") or "").strip()
    active_version = str(active.get("version") or "").strip()
    template_conflict = bool(
        current_template_id
        and active_template_id
        and current_template_id != active_template_id
    )

    report = _load_json_if_present(
        template_migration_report_path_for_context(context),
        default={},
    )
    reference_report = _load_json_if_present(
        canon_reference_migration_report_path_for_context(context),
        default={},
    )
    reconciliation = (
        report.get("reconciliation_required")
        if isinstance(report.get("reconciliation_required"), list)
        else []
    )

    persistence = _verify_canon_reference_migration_persistence(
        context,
        expected_template_version=active_version,
    )
    version_migration_required = bool(
        snapshot_path.exists()
        and not template_conflict
        and current_version != active_version
    )
    persistence_conflict = bool(
        snapshot_path.exists()
        and not template_conflict
        and current_version == active_version
        and active_version
        and not persistence["verified"]
    )

    return {
        "status": "conflict" if (template_conflict or persistence_conflict) else "ok",
        "service": TEMPLATE_SNAPSHOT_MIGRATION_MARKER,
        "project_id": context.project_id,
        "snapshot_exists": snapshot_path.exists(),
        "current_template_id": current_template_id or None,
        "active_template_id": active_template_id or None,
        "current_template_version": current_version or None,
        "active_template_version": active_version or None,
        "migration_required": version_migration_required,
        "can_migrate": bool(
            snapshot_path.exists()
            and not template_conflict
            and current_version != active_version
        ),
        "template_conflict": template_conflict,
        "persistence_conflict": persistence_conflict,
        "persistence_verified": bool(persistence["verified"]),
        "persistence": deepcopy(persistence),
        "reconciliation_required": deepcopy(reconciliation),
        "reference_migration": deepcopy(reference_report),
        "execution_locks": _execution_locks(),
    }



def migrate_template_snapshot(project_id: str) -> dict[str, Any]:
    """Upgrade the project-local template snapshot without changing author story values."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return migrate_template_snapshot_for_context(context, manifest.to_dict())


def migrate_template_snapshot_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Upgrade the project snapshot and migrate declared Canon references safely."""

    project_canon_dir_for_context(context, create=True)
    paths = _paths_for_context(context)
    if not paths["template_snapshot"].exists():
        raise TemplateSnapshotMigrationConflictError(
            "Project template snapshot is missing. Initialize Canon Setup before migration."
        )

    snapshot = _load_json_if_present(paths["template_snapshot"], default={})
    current = (
        snapshot.get("questionnaire")
        if isinstance(snapshot.get("questionnaire"), dict)
        else {}
    )
    if not current:
        raise TemplateSnapshotMigrationConflictError(
            "Project template snapshot does not contain a questionnaire schema."
        )

    active = _template_schema_for_manifest(manifest)
    current_template_id = str(
        current.get("template_id") or snapshot.get("template_id") or ""
    ).strip()
    active_template_id = str(active.get("template_id") or "").strip()
    if current_template_id and active_template_id and current_template_id != active_template_id:
        raise TemplateSnapshotMigrationConflictError(
            "Project template snapshot does not match the manifest template."
        )

    current_version = str(current.get("version") or "").strip()
    active_version = str(active.get("version") or "").strip()
    if current_version == active_version:
        status = get_template_snapshot_migration_status_for_context(context, manifest)
        if not status.get("persistence_verified"):
            raise TemplateSnapshotMigrationConflictError(
                "Project template version is current but Patch 15 persistence artifacts are incomplete. "
                "Restore the pre-migration project state before retrying the upgrade."
            )
        status["migrated"] = False
        status["message"] = "Project template snapshot is already current and persistence is verified."
        return status

    migrated_questionnaire = _merge_questionnaire_for_migration(
        current=current,
        active=active,
        active_template_id=active_template_id,
    )

    # Patch 14 stable record identity is a hard prerequisite for Patch 15.
    backfill_existing_canon_record_identities(context.project_id)
    author_canon = _load_json_if_present(paths["author_canon"], default={})
    migrated_author_canon, reference_summary = canon_reference_service.migrate_author_canon_references(
        author_canon,
        migrated_questionnaire,
    )

    reconciliation = _migration_reconciliation_summary(
        active=active,
        author_canon=migrated_author_canon,
    )
    reference_reconciliation = [
        {
            "reconciliation_type": "canon_reference",
            **deepcopy(item),
        }
        for item in reference_summary.get("unresolved", [])
        if isinstance(item, dict)
    ]
    combined_reconciliation = [*reconciliation, *reference_reconciliation]

    archive_path = _template_snapshot_archive_path(
        context,
        current_version=current_version or "unknown",
        active_version=active_version or "unknown",
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if not archive_path.exists():
        project_loader.write_json(archive_path, snapshot)

    author_archive_path = _canon_reference_author_archive_path(context)
    if reference_summary.get("changed"):
        author_archive_path.parent.mkdir(parents=True, exist_ok=True)
        if not author_archive_path.exists():
            project_loader.write_json(author_archive_path, author_canon)
        project_loader.write_json(paths["author_canon"], migrated_author_canon)

    now = utc_now_iso()
    migrated_snapshot = deepcopy(snapshot)
    migrated_snapshot["template_id"] = active.get("template_id") or snapshot.get("template_id")
    migrated_snapshot["genre"] = active.get("genre") or snapshot.get("genre")
    migrated_snapshot["questionnaire"] = migrated_questionnaire
    metadata = dict(migrated_snapshot.get("metadata") or {})
    metadata.setdefault("created_at", now)
    metadata["updated_at"] = now
    metadata["template_migration"] = {
        "marker": TEMPLATE_SNAPSHOT_MIGRATION_MARKER,
        "from_template_version": current_version or None,
        "to_template_version": active_version or None,
        "migrated_at": now,
        "archive_path": _relative(archive_path, context.project_dir),
    }
    migrated_snapshot["metadata"] = metadata
    migrated_snapshot["execution_locks"] = _execution_locks()

    reference_report = {
        "status": "ok",
        "service": canon_reference_service.CANON_REFERENCE_SERVICE_MARKER,
        "schema_version": canon_reference_service.CANON_REFERENCE_SCHEMA_VERSION,
        "project_id": context.project_id,
        "migrated_at": now,
        "author_canon_modified": bool(reference_summary.get("changed")),
        "author_story_content_modified": False,
        "author_truth_invented": False,
        "archive_path": (
            _relative(author_archive_path, context.project_dir)
            if reference_summary.get("changed")
            else None
        ),
        "migrated_reference_field_count": int(
            reference_summary.get("migrated_reference_field_count") or 0
        ),
        "migrated_reference_value_count": int(
            reference_summary.get("migrated_reference_value_count") or 0
        ),
        "unresolved_count": int(reference_summary.get("unresolved_count") or 0),
        "unresolved": deepcopy(reference_summary.get("unresolved") or []),
        "execution_locks": _execution_locks(),
    }

    report = {
        "migration_marker": TEMPLATE_SNAPSHOT_MIGRATION_MARKER,
        "project_id": context.project_id,
        "template_id": active_template_id,
        "from_template_version": current_version or None,
        "to_template_version": active_version or None,
        "migrated_at": now,
        "archive_path": _relative(archive_path, context.project_dir),
        "author_canon_modified": bool(reference_summary.get("changed")),
        "author_story_content_modified": False,
        "reference_migration": deepcopy(reference_report),
        "reconciliation_required": combined_reconciliation,
        "reconciliation_required_count": (
            sum(int(item.get("missing_count") or 0) for item in reconciliation)
            + len(reference_reconciliation)
        ),
        "execution_locks": _execution_locks(),
    }

    previous_template_report_path = template_migration_report_path_for_context(context)
    previous_template_report_archive = _canon_reference_previous_template_report_archive_path(context)
    if previous_template_report_path.exists() and not previous_template_report_archive.exists():
        previous_template_report_archive.parent.mkdir(parents=True, exist_ok=True)
        project_loader.write_json(
            previous_template_report_archive,
            _load_json_if_present(previous_template_report_path, default={}),
        )

    project_loader.write_json(paths["template_snapshot"], migrated_snapshot)
    project_loader.write_json(
        previous_template_report_path,
        report,
    )
    project_loader.write_json(
        canon_reference_migration_report_path_for_context(context),
        reference_report,
    )

    persistence = _verify_canon_reference_migration_persistence(
        context,
        expected_template_version=active_version,
    )
    if not persistence["verified"]:
        raise TemplateSnapshotMigrationConflictError(
            "Canon template migration wrote project files but persistence verification failed."
        )

    return {
        "status": "ok",
        "service": TEMPLATE_SNAPSHOT_MIGRATION_MARKER,
        "project_id": context.project_id,
        "migrated": True,
        "persistence_verified": True,
        "persistence": deepcopy(persistence),
        "from_template_version": current_version or None,
        "to_template_version": active_version or None,
        "archive_path": report["archive_path"],
        "author_canon_modified": bool(reference_summary.get("changed")),
        "author_story_content_modified": False,
        "reference_migration": deepcopy(reference_report),
        "reconciliation_required": deepcopy(combined_reconciliation),
        "reconciliation_required_count": report["reconciliation_required_count"],
        "execution_locks": _execution_locks(),
    }

def get_project_canon_status(project_id: str) -> dict[str, Any]:
    """Return read-only project-local author canon storage status."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_project_canon_status_for_context(context, manifest.to_dict())


def get_project_canon_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return compact status for the author canon storage files."""

    schema = template_schema or effective_template_schema_for_context(context, manifest)
    paths = _paths_for_context(context)
    file_status = {
        key: _file_status(path, context.project_dir)
        for key, path in paths.items()
    }
    completion = _load_json_if_present(paths["canon_completion"], default={})
    author_canon = _load_json_if_present(paths["author_canon"], default={})

    return {
        "status": "ok",
        "service": PROJECT_CANON_SERVICE_MARKER,
        "schema_version": PROJECT_CANON_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": schema.get("template_id"),
        "genre": schema.get("genre"),
        "canon_dir": _relative(project_canon_dir_for_context(context), context.project_dir),
        "files": file_status,
        "author_canon_exists": paths["author_canon"].exists(),
        "template_snapshot_exists": paths["template_snapshot"].exists(),
        "canon_completion_exists": paths["canon_completion"].exists(),
        "section_count": len(schema.get("sections", [])),
        "required_section_count": int(
            schema.get("completion_model", {}).get("required_section_count") or 0
        ),
        "completed_required_section_count": int(
            completion.get("completed_required_section_count") or 0
        ),
        "author_canon_status": author_canon.get("status", "missing"),
        "storage_ready": all(path.exists() for path in paths.values()),
        "execution_locks": _execution_locks(),
    }


def load_author_canon(project_id: str) -> dict[str, Any]:
    """Load project-local author canon JSON.

    Missing files are not created by this function.
    """

    return project_loader.read_json(author_canon_path(project_id), default={})


def ensure_author_canon(project_id: str) -> dict[str, Any]:
    """Ensure project-local author canon storage files exist."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return ensure_author_canon_for_context(context, manifest.to_dict())


def backfill_existing_canon_record_identities(project_id: str) -> dict[str, Any]:
    """Backfill hidden record identities in an existing author_canon.json only.

    No missing Canon files are created by this migration helper.
    """

    context = build_project_context(project_loader.load_manifest(project_id))
    path = author_canon_path_for_context(context)
    if not path.exists():
        return {
            "service": canon_record_identity_service.CANON_RECORD_IDENTITY_SERVICE_MARKER,
            "identity_version": canon_record_identity_service.CANON_RECORD_IDENTITY_VERSION,
            "identity_field": canon_record_identity_service.INTERNAL_ID_FIELD,
            "changed": False,
            "record_count": 0,
            "unique_identity_count": 0,
            "assigned_count": 0,
            "assignments": [],
            "author_canon_exists": False,
        }

    author_canon = project_loader.read_json(path, default={})
    normalized, report = canon_record_identity_service.backfill_author_canon_record_identities(
        context.project_id,
        author_canon if isinstance(author_canon, dict) else {},
    )
    if report["changed"]:
        project_loader.write_json(path, normalized)
    report["author_canon_exists"] = True
    return report


def ensure_author_canon_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure author canon, template snapshot, and completion JSON exist.

    Existing files are preserved. Missing files are created with inert draft
    payloads derived from the selected questionnaire schema.
    """

    schema = template_schema or effective_template_schema_for_context(context, manifest)
    project_canon_dir_for_context(context, create=True)
    paths = _paths_for_context(context)
    created: list[str] = []

    if not paths["author_canon"].exists():
        project_loader.write_json(
            paths["author_canon"],
            build_default_author_canon(context.project_id, manifest, schema),
        )
        created.append("author_canon.json")

    author_canon = _load_json_if_present(paths["author_canon"], default={})
    author_canon, identity_report = canon_record_identity_service.backfill_author_canon_record_identities(
        context.project_id,
        author_canon,
    )
    if identity_report["changed"]:
        project_loader.write_json(paths["author_canon"], author_canon)

    if not paths["template_snapshot"].exists():
        project_loader.write_json(
            paths["template_snapshot"],
            build_template_snapshot(context.project_id, manifest, schema),
        )
        created.append("template_snapshot.json")

    if not paths["canon_completion"].exists():
        project_loader.write_json(
            paths["canon_completion"],
            build_default_canon_completion(context.project_id, manifest, schema),
        )
        created.append("canon_completion.json")

    status = get_project_canon_status_for_context(context, manifest, schema)
    status["created"] = created
    status["record_identity"] = identity_report
    return status


def save_author_canon(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Save a complete author canon payload to the project-local canon store.

    This is a storage operation only. It does not render Markdown, generate
    packets, or write runtime memory.
    """

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    project_canon_dir_for_context(context, create=True)

    normalized = deepcopy(payload or {})
    now = utc_now_iso()
    normalized.setdefault("schema_version", PROJECT_CANON_SCHEMA_VERSION)
    normalized["project_id"] = context.project_id
    normalized.setdefault("template_id", manifest.template_id)
    normalized.setdefault("genre", manifest.genre)
    normalized.setdefault("status", "draft")
    normalized.setdefault("sections", {})
    metadata = dict(normalized.get("metadata") or {})
    metadata.setdefault("created_at", now)
    metadata["updated_at"] = now
    metadata["source"] = PROJECT_CANON_SERVICE_MARKER
    normalized["metadata"] = metadata

    project_loader.write_json(author_canon_path_for_context(context), normalized)
    return normalized


def build_default_author_canon(
    project_id: str,
    manifest: dict[str, Any] | None = None,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an empty draft author canon payload from a questionnaire schema."""

    manifest_dict = dict(manifest or {})
    schema = template_schema or _template_schema_for_manifest(manifest_dict)
    now = utc_now_iso()
    sections: dict[str, Any] = {}

    for section in schema.get("sections", []):
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        sections[section_id] = {
            "section_id": section_id,
            "status": "not_started",
            "answers": {},
            "records": [],
            "updated_at": None,
        }

    return {
        "schema_version": PROJECT_CANON_SCHEMA_VERSION,
        "project_id": project_id,
        "template_id": schema.get("template_id") or manifest_dict.get("template_id"),
        "genre": schema.get("genre") or manifest_dict.get("genre"),
        "status": "draft",
        "sections": sections,
        "metadata": {
            "created_at": now,
            "updated_at": now,
            "source": PROJECT_CANON_SERVICE_MARKER,
        },
        "execution_locks": _execution_locks(),
    }


def build_template_snapshot(
    project_id: str,
    manifest: dict[str, Any] | None = None,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a project-local snapshot of the selected questionnaire schema."""

    manifest_dict = dict(manifest or {})
    schema = template_schema or _template_schema_for_manifest(manifest_dict)
    return {
        "schema_version": PROJECT_CANON_SCHEMA_VERSION,
        "project_id": project_id,
        "template_id": schema.get("template_id") or manifest_dict.get("template_id"),
        "genre": schema.get("genre") or manifest_dict.get("genre"),
        "questionnaire": deepcopy(schema),
        "metadata": {
            "created_at": utc_now_iso(),
            "source": PROJECT_CANON_SERVICE_MARKER,
        },
        "execution_locks": _execution_locks(),
    }


def build_default_canon_completion(
    project_id: str,
    manifest: dict[str, Any] | None = None,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an empty completion payload for the selected questionnaire schema."""

    manifest_dict = dict(manifest or {})
    schema = template_schema or _template_schema_for_manifest(manifest_dict)
    section_status: dict[str, Any] = {}
    required_count = 0

    for section in schema.get("sections", []):
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        required = bool(section.get("required"))
        if required:
            required_count += 1
        section_status[section_id] = {
            "section_id": section_id,
            "required": required,
            "status": "not_started",
            "missing_required_fields": _required_field_ids(section),
        }

    return {
        "schema_version": PROJECT_CANON_SCHEMA_VERSION,
        "project_id": project_id,
        "template_id": schema.get("template_id") or manifest_dict.get("template_id"),
        "genre": schema.get("genre") or manifest_dict.get("genre"),
        "required_section_count": required_count,
        "completed_required_section_count": 0,
        "section_status": section_status,
        "metadata": {
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "source": PROJECT_CANON_SERVICE_MARKER,
        },
        "execution_locks": _execution_locks(),
    }


def _merge_questionnaire_for_migration(
    *,
    current: dict[str, Any],
    active: dict[str, Any],
    active_template_id: str,
) -> dict[str, Any]:
    """Merge the active interface into a project snapshot without dropping project-specific schema."""

    merged = deepcopy(current)
    for key, value in active.items():
        if key == "sections":
            continue
        merged[key] = deepcopy(value)

    current_sections = {
        str(section.get("section_id") or ""): section
        for section in current.get("sections", [])
        if isinstance(section, dict) and section.get("section_id")
    }
    active_sections = [
        section
        for section in active.get("sections", [])
        if isinstance(section, dict) and section.get("section_id")
    ]

    merged_sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for active_section in active_sections:
        section_id = str(active_section.get("section_id"))
        current_section = current_sections.get(section_id)
        if current_section:
            merged_sections.append(
                _merge_section_schema_for_migration(
                    current_section=current_section,
                    active_section=active_section,
                    active_template_id=active_template_id,
                )
            )
        else:
            merged_sections.append(
                _existing_project_safe_schema(deepcopy(active_section))
            )
        seen.add(section_id)

    for current_section in current.get("sections", []):
        if not isinstance(current_section, dict):
            continue
        section_id = str(current_section.get("section_id") or "")
        if section_id and section_id not in seen:
            merged_sections.append(deepcopy(current_section))

    merged["sections"] = merged_sections
    _refresh_questionnaire_completion_metadata(merged)
    return merged


def _merge_section_schema_for_migration(
    *,
    current_section: dict[str, Any],
    active_section: dict[str, Any],
    active_template_id: str,
) -> dict[str, Any]:
    merged = deepcopy(current_section)
    for key, value in active_section.items():
        if key in {"fields", "records"}:
            continue
        merged[key] = deepcopy(value)

    merged["fields"] = _merge_field_schemas_for_migration(
        current_fields=current_section.get("fields", []),
        active_fields=active_section.get("fields", []),
        active_template_id=active_template_id,
        section_id=str(active_section.get("section_id") or ""),
        record_id=None,
    )

    current_records = {
        str(record.get("record_id") or ""): record
        for record in current_section.get("records", [])
        if isinstance(record, dict) and record.get("record_id")
    }
    merged_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for active_record in active_section.get("records", []):
        if not isinstance(active_record, dict) or not active_record.get("record_id"):
            continue
        record_id = str(active_record.get("record_id"))
        current_record = current_records.get(record_id)
        if current_record:
            merged_record = deepcopy(current_record)
            for key, value in active_record.items():
                if key == "fields":
                    continue
                merged_record[key] = deepcopy(value)
            merged_record["fields"] = _merge_field_schemas_for_migration(
                current_fields=current_record.get("fields", []),
                active_fields=active_record.get("fields", []),
                active_template_id=active_template_id,
                section_id=str(active_section.get("section_id") or ""),
                record_id=record_id,
            )
        else:
            merged_record = _existing_project_safe_schema(deepcopy(active_record))
        merged_records.append(merged_record)
        seen.add(record_id)

    for current_record in current_section.get("records", []):
        if not isinstance(current_record, dict):
            continue
        record_id = str(current_record.get("record_id") or "")
        if record_id and record_id not in seen:
            merged_records.append(deepcopy(current_record))

    merged["records"] = merged_records
    return merged


def _merge_field_schemas_for_migration(
    *,
    current_fields: Any,
    active_fields: Any,
    active_template_id: str,
    section_id: str,
    record_id: str | None,
) -> list[dict[str, Any]]:
    current_list = [field for field in current_fields if isinstance(field, dict)]
    active_list = [field for field in active_fields if isinstance(field, dict)]
    current_by_id = {
        str(field.get("field_id") or ""): field
        for field in current_list
        if field.get("field_id")
    }
    active_ids: set[str] = set()
    merged: list[dict[str, Any]] = []

    for active_field in active_list:
        field_id = str(active_field.get("field_id") or "")
        if not field_id:
            continue
        field = deepcopy(active_field)
        if field.get("migration_existing_optional"):
            field["required"] = False
        merged.append(field)
        active_ids.add(field_id)

    for current_field in current_list:
        field_id = str(current_field.get("field_id") or "")
        if not field_id or field_id in active_ids:
            continue
        field = deepcopy(current_field)

        hide_legacy_historical = (
            active_template_id != "historical_epic"
            and section_id == "timeline_event_ledger"
            and record_id == "events"
            and field_id in NONUNIVERSAL_HISTORICAL_FIELD_IDS
        )
        if field_id in LEGACY_TECHNICAL_FIELD_IDS or hide_legacy_historical:
            field["required"] = False
            field["author_hidden"] = True
            field["legacy_compatibility"] = True

        merged.append(field)

    return merged


def _existing_project_safe_schema(value: Any) -> Any:
    """Downgrade only explicitly marked new fields that must not invalidate existing Canon Setup."""

    if isinstance(value, list):
        return [_existing_project_safe_schema(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)

    result = {
        key: _existing_project_safe_schema(item)
        for key, item in value.items()
    }
    if result.get("migration_existing_optional"):
        result["required"] = False
    return result


def _refresh_questionnaire_completion_metadata(schema: dict[str, Any]) -> None:
    required_sections = 0
    required_fields = 0
    repeatable_records = 0
    for section in schema.get("sections", []):
        if not isinstance(section, dict):
            continue
        if section.get("required"):
            required_sections += 1
        for field in section.get("fields", []):
            if isinstance(field, dict) and field.get("required"):
                required_fields += 1
        for record in section.get("records", []):
            if not isinstance(record, dict):
                continue
            repeatable_records += 1
            for field in record.get("fields", []):
                if isinstance(field, dict) and field.get("required"):
                    required_fields += 1

    schema["completion_model"] = {
        "section_count": len(schema.get("sections", [])),
        "required_section_count": required_sections,
        "required_field_count": required_fields,
        "repeatable_record_count": repeatable_records,
        "completion_rule": "all_required_sections_complete_and_required_fields_answered",
    }


def _migration_reconciliation_summary(
    *,
    active: dict[str, Any],
    author_canon: dict[str, Any],
) -> list[dict[str, Any]]:
    """Report new semantic fields that cannot be safely inferred from existing author content."""

    stored_sections = (
        author_canon.get("sections")
        if isinstance(author_canon.get("sections"), dict)
        else {}
    )
    result: list[dict[str, Any]] = []

    for section in active.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or "")
        stored_section = (
            stored_sections.get(section_id)
            if isinstance(stored_sections, dict)
            else {}
        )
        stored_records = (
            stored_section.get("records")
            if isinstance(stored_section, dict)
            and isinstance(stored_section.get("records"), dict)
            else {}
        )

        for record in section.get("records", []):
            if not isinstance(record, dict):
                continue
            record_id = str(record.get("record_id") or "")
            rows = (
                stored_records.get(record_id)
                if isinstance(stored_records, dict)
                else []
            )
            rows = rows if isinstance(rows, list) else []
            for field in record.get("fields", []):
                if not isinstance(field, dict) or not field.get("migration_reconciliation"):
                    continue
                field_id = str(field.get("field_id") or "")
                missing_count = sum(
                    1
                    for row in rows
                    if isinstance(row, dict) and _is_blank_value(row.get(field_id))
                )
                if missing_count:
                    result.append(
                        {
                            "section_id": section_id,
                            "record_id": record_id,
                            "field_id": field_id,
                            "field_label": field.get("label") or field_id,
                            "missing_count": missing_count,
                            "blocking": False,
                            "reason": "Author-owned semantic value cannot be inferred safely.",
                        }
                    )

    return result


def _is_blank_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _canon_reference_author_archive_path(context: ProjectContext) -> Path:
    return (
        project_canon_dir_for_context(context, create=True)
        / "archive"
        / "author_canon_before_canon_reference_hardening_v1.json"
    )


def _canon_reference_previous_template_report_archive_path(context: ProjectContext) -> Path:
    return (
        project_canon_dir_for_context(context, create=True)
        / "archive"
        / "template_migration_report_before_canon_reference_hardening_v1.json"
    )


def _template_snapshot_archive_path(
    context: ProjectContext,
    *,
    current_version: str,
    active_version: str,
) -> Path:
    source = _safe_filename_fragment(current_version)
    target = _safe_filename_fragment(active_version)
    return (
        project_canon_dir_for_context(context, create=True)
        / "archive"
        / f"template_snapshot_{source}_before_{target}.json"
    )


def _safe_filename_fragment(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(value or "")
    )
    return cleaned.strip("_") or "unknown"


def _template_schema_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return canon_template_service.get_canon_questionnaire_template(
        manifest.get("template_id"),
        manifest.get("genre"),
    )


def _paths_for_context(context: ProjectContext) -> dict[str, Path]:
    return {
        "author_canon": author_canon_path_for_context(context),
        "template_snapshot": template_snapshot_path_for_context(context),
        "canon_completion": canon_completion_path_for_context(context),
    }


def _file_status(path: Path, project_dir: Path) -> dict[str, Any]:
    return {
        "exists": path.exists(),
        "relative_path": _relative(path, project_dir),
    }


def _load_json_if_present(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default)
    data = project_loader.read_json(path, default=default)
    return data if isinstance(data, dict) else deepcopy(default)


def _required_field_ids(section: dict[str, Any]) -> list[str]:
    required: list[str] = []

    for field in section.get("fields", []):
        if field.get("required"):
            required.append(str(field.get("field_id")))

    for record in section.get("records", []):
        if record.get("required"):
            record_id = str(record.get("record_id") or "record")
            for field in record.get("fields", []):
                if field.get("required"):
                    required.append(f"{record_id}.{field.get('field_id')}")

    return required


def _relative(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def _execution_locks() -> dict[str, bool]:
    return {
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "draft_validation_enabled": False,
        "approved_persistence_enabled": False,
        "export_enabled": False,
    }
