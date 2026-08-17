"""
Project-local canon validation service.

This service validates author-entered canon and rendered Markdown canon sources
before any future knowledge/control packet generation boundary.

It does not generate packets, build prompts, call providers, validate generated
drafts, write runtime memory, export files, persist drafts, or unlock generation.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import canon_markdown_renderer_service, canon_record_identity_service, canon_reference_service, canon_template_service, project_canon_service


CANON_VALIDATION_SERVICE_MARKER = "project-canon-validation-boundary-20260725"
CANON_VALIDATION_SCHEMA_VERSION = "project_canon_validation_report_v1"
CANON_VALIDATION_REPORT_FILENAME = "canon_validation_report.json"
CANON_SOURCES_DIRNAME = "canon_sources"

STATUS_BLOCKED = "blocked"
STATUS_NOT_READY = "not_ready"
STATUS_READY_FOR_PACKET_GENERATION = "ready_for_packet_generation"


class CanonValidationSectionNotFoundError(ValueError):
    """Raised when a canon section cannot be found in the questionnaire schema."""


def canon_validation_report_path(project_id: str) -> Path:
    """Return the project-local canon validation report path."""

    return project_canon_service.project_canon_dir(project_id, create=True) / CANON_VALIDATION_REPORT_FILENAME


def canon_validation_report_path_for_context(context: ProjectContext) -> Path:
    """Return the validation report path for an existing project context."""

    return project_canon_service.project_canon_dir_for_context(context, create=True) / CANON_VALIDATION_REPORT_FILENAME


def get_canon_validation_status(project_id: str) -> dict[str, Any]:
    """Return read-only project-local canon validation status.

    This function does not create missing canon files and does not write the
    validation report. Use validate_project_canon when a report artifact should
    be written.
    """

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_canon_validation_status_for_context(context, manifest.to_dict())


def get_canon_validation_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return validation status for an existing project context without writes."""

    schema = template_schema or _template_schema_for_context(context, manifest)
    report = _build_validation_report(context, manifest, schema)
    report["report_written"] = False
    return report


def validate_project_canon(project_id: str) -> dict[str, Any]:
    """Validate project-local canon and write canon_validation_report.json."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return validate_project_canon_for_context(context, manifest.to_dict())


def validate_project_canon_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate canon for an existing project context and write the report."""

    schema = template_schema or _template_schema_for_context(context, manifest)
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)
    report = _build_validation_report(context, manifest, schema)
    _write_validation_report(context, report)
    report["report_written"] = True
    report["validation_report_path"] = _relative(canon_validation_report_path_for_context(context), context.project_dir)
    return report


def validate_section(project_id: str, section_id: str) -> dict[str, Any]:
    """Validate one project-local canon section without writing reports."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    schema = _template_schema_for_context(context, manifest.to_dict())
    return validate_section_for_context(context, manifest.to_dict(), section_id, schema)


def validate_section_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    section_id: str,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one canon section for an existing project context."""

    schema = template_schema or _template_schema_for_context(context, manifest)
    section_schema = _section_schema(schema, section_id)
    paths = _canon_paths_for_context(context)
    author_canon = _load_json_if_present(paths["author_canon"], default={})
    completion = _load_json_if_present(paths["canon_completion"], default={})
    section_record = _completion_record(completion, section_id)
    stored_section = _stored_section(author_canon, section_id)
    missing_required_fields = _missing_required_fields(section_schema, stored_section)
    completed = section_record.get("status") == "complete" and not missing_required_fields
    expected_markdown = _expected_markdown_file(schema, section_id)
    markdown_path = _canon_sources_dir_for_context(context) / expected_markdown
    markdown_status = _markdown_file_status(markdown_path, context.project_dir)

    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if bool(section_schema.get("required")) and not completed:
        issues.append(
            _issue(
                "section_incomplete",
                f"Required section is not complete: {section_id}",
                section_id=section_id,
                severity="not_ready",
            )
        )
    if section_record.get("status") == "complete" and missing_required_fields:
        issues.append(
            _issue(
                "completed_section_missing_required_fields",
                f"Completed section has missing required fields: {section_id}",
                section_id=section_id,
                details={"missing_required_fields": missing_required_fields},
                severity="blocking",
            )
        )
    if completed and not markdown_status["exists"]:
        warnings.append(
            _issue(
                "completed_section_missing_markdown",
                f"Completed section has no rendered Markdown source: {section_id}",
                section_id=section_id,
                details={"expected_file": expected_markdown},
                severity="warning",
            )
        )
    if markdown_status["exists"] and markdown_status["size_bytes"] <= 0:
        issues.append(
            _issue(
                "empty_markdown_source",
                f"Rendered Markdown source is empty: {expected_markdown}",
                section_id=section_id,
                severity="blocking",
            )
        )

    return {
        "status": STATUS_READY_FOR_PACKET_GENERATION if not issues and completed and markdown_status["exists"] else STATUS_NOT_READY,
        "service": CANON_VALIDATION_SERVICE_MARKER,
        "schema_version": CANON_VALIDATION_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": schema.get("template_id"),
        "genre": schema.get("genre"),
        "section_id": section_id,
        "label": section_schema.get("label"),
        "required": bool(section_schema.get("required")),
        "completion_status": section_record.get("status", "not_started"),
        "missing_required_fields": missing_required_fields,
        "expected_markdown_file": expected_markdown,
        "markdown_file": markdown_status,
        "issues": issues,
        "warnings": warnings,
        "locks": _locks(),
        "execution_locks": _execution_locks(),
    }


def _build_validation_report(
    context: ProjectContext,
    manifest: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    paths = _canon_paths_for_context(context)
    file_status = {
        name: _file_status(path, context.project_dir)
        for name, path in paths.items()
    }

    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    author_canon = _load_json_with_issue(
        paths["author_canon"],
        "author_canon",
        issues,
    )
    completion = _load_json_with_issue(
        paths["canon_completion"],
        "canon_completion",
        issues,
    )
    template_snapshot = _load_json_with_issue(
        paths["template_snapshot"],
        "template_snapshot",
        issues,
    )

    _validate_storage_identity(context, schema, author_canon, completion, template_snapshot, issues, warnings)

    for finding in canon_reference_service.reference_validation_findings(author_canon, schema):
        severity = str(finding.get("severity") or "warning")
        normalized_finding = deepcopy(finding)
        normalized_finding["severity"] = "blocking" if severity == "error" else "warning"
        if severity == "error":
            issues.append(normalized_finding)
        else:
            warnings.append(normalized_finding)

    section_results = [
        _section_validation(context, manifest, schema, author_canon, completion, section)
        for section in schema.get("sections", [])
        if section.get("section_id")
    ]

    for result in section_results:
        issues.extend(result.get("issues") or [])
        warnings.extend(result.get("warnings") or [])

    required_sections = [
        result for result in section_results if result.get("required")
    ]
    completed_required = [
        result for result in required_sections if result.get("complete")
    ]
    missing_required_sections = [
        {
            "section_id": result.get("section_id"),
            "label": result.get("label"),
            "missing_required_fields": result.get("missing_required_fields", []),
        }
        for result in required_sections
        if not result.get("complete")
    ]
    rendered_sources = [
        result
        for result in section_results
        if result.get("complete")
        and result.get("markdown_file", {}).get("exists")
        and result.get("markdown_file", {}).get("render_status") == "current"
        and result.get("markdown_file", {}).get("freshness_verified") is True
    ]
    missing_rendered_sources = [
        {
            "section_id": result.get("section_id"),
            "label": result.get("label"),
            "expected_file": result.get("expected_markdown_file"),
        }
        for result in section_results
        if result.get("complete")
        and (
            not result.get("markdown_file", {}).get("exists")
            or result.get("markdown_file", {}).get("render_status") != "current"
            or result.get("markdown_file", {}).get("freshness_verified") is not True
        )
    ]

    status = _status_from_findings(
        issues=issues,
        missing_required_sections=missing_required_sections,
        missing_rendered_sources=missing_rendered_sources,
    )

    return {
        "status": status,
        "service": CANON_VALIDATION_SERVICE_MARKER,
        "schema_version": CANON_VALIDATION_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": schema.get("template_id") or manifest.get("template_id"),
        "genre": schema.get("genre") or manifest.get("genre"),
        "ready_for_packet_generation": status == STATUS_READY_FOR_PACKET_GENERATION,
        "required_sections_total": len(required_sections),
        "required_sections_complete": len(completed_required),
        "rendered_sources_total": len(rendered_sources),
        "missing_required_sections": missing_required_sections,
        "missing_rendered_sources": missing_rendered_sources,
        "sections": section_results,
        "files": file_status,
        "issues": issues,
        "warnings": warnings,
        "locks": _locks(),
        "execution_locks": _execution_locks(),
        "metadata": {
            "validated_at": utc_now_iso(),
            "source": CANON_VALIDATION_SERVICE_MARKER,
        },
    }


def _section_validation(
    context: ProjectContext,
    manifest: dict[str, Any],
    schema: dict[str, Any],
    author_canon: dict[str, Any],
    completion: dict[str, Any],
    section_schema: dict[str, Any],
) -> dict[str, Any]:
    section_id = str(section_schema.get("section_id") or "").strip()
    section_record = _completion_record(completion, section_id)
    stored_section = _stored_section(author_canon, section_id)
    missing_required_fields = _missing_required_fields(section_schema, stored_section)
    completion_status = str(section_record.get("status") or "not_started")
    complete = completion_status == "complete" and not missing_required_fields
    expected_markdown = _expected_markdown_file(schema, section_id)
    markdown_path = _canon_sources_dir_for_context(context) / expected_markdown
    markdown_status = _markdown_file_status(markdown_path, context.project_dir)
    freshness = canon_markdown_renderer_service.markdown_source_freshness(
        markdown_path,
        manifest=manifest,
        schema=schema,
        section_schema=section_schema,
        stored_section=stored_section,
        section_status=completion_status,
    )
    markdown_status.update(freshness)

    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if bool(section_schema.get("required")) and not complete:
        issues.append(
            _issue(
                "required_section_not_complete",
                f"Required section is not complete: {section_id}",
                section_id=section_id,
                details={"completion_status": completion_status, "missing_required_fields": missing_required_fields},
                severity="not_ready",
            )
        )

    if completion_status == "complete" and missing_required_fields:
        issues.append(
            _issue(
                "complete_section_missing_required_fields",
                f"Complete section has missing required fields: {section_id}",
                section_id=section_id,
                details={"missing_required_fields": missing_required_fields},
                severity="blocking",
            )
        )

    if complete and not markdown_status["exists"]:
        warnings.append(
            _issue(
                "missing_rendered_markdown_source",
                f"Completed section is missing rendered Markdown source: {section_id}",
                section_id=section_id,
                details={"expected_file": expected_markdown},
                severity="warning",
            )
        )
    elif complete and markdown_status.get("render_status") != "current":
        warnings.append(
            _issue(
                "outdated_rendered_markdown_source",
                f"Completed section requires an updated Markdown render: {section_id}",
                section_id=section_id,
                details={
                    "expected_file": expected_markdown,
                    "verification_method": markdown_status.get("verification_method"),
                },
                severity="warning",
            )
        )

    if markdown_status["exists"] and markdown_status["size_bytes"] <= 0:
        issues.append(
            _issue(
                "empty_rendered_markdown_source",
                f"Rendered Markdown source is empty: {expected_markdown}",
                section_id=section_id,
                severity="blocking",
            )
        )

    return {
        "section_id": section_id,
        "label": section_schema.get("label"),
        "required": bool(section_schema.get("required")),
        "completion_status": completion_status,
        "complete": complete,
        "missing_required_fields": missing_required_fields,
        "expected_markdown_file": expected_markdown,
        "markdown_file": markdown_status,
        "issues": issues,
        "warnings": warnings,
    }


def _template_schema_for_context(context: ProjectContext, manifest: dict[str, Any]) -> dict[str, Any]:
    """Use the immutable project questionnaire snapshot when present."""
    return project_canon_service.effective_template_schema_for_context(
        context,
        manifest,
    )


def _validate_storage_identity(
    context: ProjectContext,
    schema: dict[str, Any],
    author_canon: dict[str, Any],
    completion: dict[str, Any],
    template_snapshot: dict[str, Any],
    issues: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    for label, payload in (
        ("author_canon", author_canon),
        ("canon_completion", completion),
        ("template_snapshot", template_snapshot),
    ):
        if not payload:
            continue
        project_id = str(payload.get("project_id") or "").strip()
        if project_id and project_id != context.project_id:
            issues.append(
                _issue(
                    "project_id_mismatch",
                    f"{label} project_id does not match active project.",
                    details={"file_project_id": project_id, "active_project_id": context.project_id},
                    severity="blocking",
                )
            )

    for finding in canon_record_identity_service.record_identity_findings(author_canon):
        issues.append(
            _issue(
                finding["code"],
                finding["message"],
                details=finding.get("details") or {},
                severity="blocking",
            )
        )

    snapshot_questionnaire = template_snapshot.get("questionnaire") if isinstance(template_snapshot.get("questionnaire"), dict) else {}
    snapshot_template_id = snapshot_questionnaire.get("template_id") or template_snapshot.get("template_id")
    if snapshot_template_id and snapshot_template_id != schema.get("template_id"):
        warnings.append(
            _issue(
                "template_snapshot_mismatch",
                "Template snapshot id differs from active questionnaire schema.",
                details={"snapshot_template_id": snapshot_template_id, "schema_template_id": schema.get("template_id")},
                severity="warning",
            )
        )


def _canon_paths_for_context(context: ProjectContext) -> dict[str, Path]:
    return {
        "author_canon": project_canon_service.author_canon_path_for_context(context),
        "template_snapshot": project_canon_service.template_snapshot_path_for_context(context),
        "canon_completion": project_canon_service.canon_completion_path_for_context(context),
    }


def _canon_sources_dir_for_context(context: ProjectContext) -> Path:
    return project_canon_service.project_canon_dir_for_context(context) / CANON_SOURCES_DIRNAME


def _write_validation_report(context: ProjectContext, report: dict[str, Any]) -> None:
    path = canon_validation_report_path_for_context(context)
    project_loader.write_json(path, report)


def _load_json_with_issue(
    path: Path,
    label: str,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    if not path.exists():
        issues.append(
            _issue(
                "missing_required_canon_file",
                f"Missing required canon file: {label}",
                details={"path": path.name},
                severity="blocking",
            )
        )
        return {}
    try:
        data = project_loader.read_json(path, default={})
    except Exception as exc:  # noqa: BLE001 - validation report must capture malformed JSON safely.
        issues.append(
            _issue(
                "invalid_json",
                f"Invalid JSON in canon file: {label}",
                details={"path": path.name, "error": str(exc)},
                severity="blocking",
            )
        )
        return {}
    if not isinstance(data, dict):
        issues.append(
            _issue(
                "invalid_json_shape",
                f"Canon file must contain a JSON object: {label}",
                details={"path": path.name},
                severity="blocking",
            )
        )
        return {}
    return data


def _load_json_if_present(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return deepcopy(default)
    data = project_loader.read_json(path, default=default)
    return data if isinstance(data, dict) else deepcopy(default)


def _file_status(path: Path, project_dir: Path) -> dict[str, Any]:
    return {
        "exists": path.exists(),
        "relative_path": _relative(path, project_dir),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
    }


def _section_schema(schema: dict[str, Any], section_id: str) -> dict[str, Any]:
    target = str(section_id or "").strip()
    for section in schema.get("sections", []):
        if str(section.get("section_id") or "").strip() == target:
            return deepcopy(section)
    raise CanonValidationSectionNotFoundError(f"Unknown canon questionnaire section: {section_id}")


def _completion_record(completion: dict[str, Any], section_id: str) -> dict[str, Any]:
    status = completion.get("section_status") if isinstance(completion.get("section_status"), dict) else {}
    record = status.get(section_id) if isinstance(status, dict) else {}
    return deepcopy(record) if isinstance(record, dict) else {}


def _stored_section(author_canon: dict[str, Any], section_id: str) -> dict[str, Any]:
    sections = author_canon.get("sections") if isinstance(author_canon.get("sections"), dict) else {}
    stored = sections.get(section_id) if isinstance(sections, dict) else {}
    if not isinstance(stored, dict):
        return {"section_id": section_id, "answers": {}, "records": {}}
    return deepcopy(stored)


def _missing_required_fields(section_schema: dict[str, Any], stored_section: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    answers = stored_section.get("answers") if isinstance(stored_section.get("answers"), dict) else {}
    records = stored_section.get("records") if isinstance(stored_section.get("records"), dict) else {}

    for field in section_schema.get("fields", []):
        field_id = str(field.get("field_id") or "").strip()
        if not field_id or not field.get("required"):
            continue
        if _is_blank(answers.get(field_id)):
            missing.append(field_id)

    for record_schema in section_schema.get("records", []):
        record_id = str(record_schema.get("record_id") or "").strip()
        if not record_id:
            continue
        required_fields = [
            str(field.get("field_id") or "").strip()
            for field in record_schema.get("fields", [])
            if field.get("required") and str(field.get("field_id") or "").strip()
        ]
        rows = records.get(record_id) if isinstance(records, dict) else []
        if not isinstance(rows, list):
            rows = []
        required_record = bool(record_schema.get("required"))
        meaningful_rows = [row for row in rows if isinstance(row, dict) and not _record_is_blank(row)]
        if required_record and not meaningful_rows:
            for field_id in required_fields:
                missing.append(f"{record_id}.{field_id}")
            continue
        for index, row in enumerate(meaningful_rows):
            for field_id in required_fields:
                if _is_blank(row.get(field_id)):
                    missing.append(f"{record_id}[{index}].{field_id}")

    return _unique(missing)


def _expected_markdown_file(schema: dict[str, Any], section_id: str) -> str:
    for index, section in enumerate(schema.get("sections", []), start=1):
        if str(section.get("section_id") or "").strip() == section_id:
            return _section_filename(index, section_id)
    return _section_filename(0, section_id)


def _markdown_file_status(path: Path, project_dir: Path) -> dict[str, Any]:
    return {
        "exists": path.exists(),
        "relative_path": _relative(path, project_dir),
        "size_bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
    }


def _section_filename(index: int, section_id: str) -> str:
    safe_id = _safe_filename(section_id)
    if index <= 0:
        return f"000_{safe_id}.md"
    return f"{index:03d}_{safe_id}.md"


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "section"


def _record_is_blank(record: dict[str, Any]) -> bool:
    return all(_is_blank(value) for value in record.values())


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


def _status_from_findings(
    *,
    issues: list[dict[str, Any]],
    missing_required_sections: list[dict[str, Any]],
    missing_rendered_sources: list[dict[str, Any]],
) -> str:
    if any(issue.get("severity") == "blocking" for issue in issues):
        return STATUS_BLOCKED
    if missing_required_sections or missing_rendered_sources:
        return STATUS_NOT_READY
    return STATUS_READY_FOR_PACKET_GENERATION


def _issue(
    code: str,
    message: str,
    *,
    section_id: str | None = None,
    details: dict[str, Any] | None = None,
    severity: str = "blocking",
) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "code": code,
        "message": message,
        "severity": severity,
    }
    if section_id:
        issue["section_id"] = section_id
    if details:
        issue["details"] = details
    return issue


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _locks() -> dict[str, bool]:
    return {
        "generation_unlocked": False,
        "provider_calls_allowed": False,
        "runtime_writes_allowed": False,
        "packet_generation_allowed": False,
    }


def _execution_locks() -> dict[str, bool]:
    return {
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "draft_validation_enabled": False,
        "approved_persistence_enabled": False,
        "export_enabled": False,
    }
