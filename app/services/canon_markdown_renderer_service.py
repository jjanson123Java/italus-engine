"""
Project-local canon Markdown renderer service.

This service renders completed author canon questionnaire sections into
project-local Markdown source files. The rendered files are an intermediate
canon source boundary only.

It does not generate knowledge/control packs, call prompt construction, call
providers, write runtime memory, or unlock generation.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import hashlib
import json
import re

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import canon_record_identity_service, canon_reference_service, canon_template_service, project_canon_service


CANON_MARKDOWN_RENDERER_SERVICE_MARKER = "project-canon-markdown-renderer-boundary-20260715"
CANON_MARKDOWN_RENDERER_SCHEMA_VERSION = "project_canon_markdown_renderer_v1"
CANON_SOURCES_DIRNAME = "canon_sources"


class CanonMarkdownSectionNotFoundError(ValueError):
    """Raised when a canon section cannot be found in the template schema."""


class CanonMarkdownSectionNotCompleteError(ValueError):
    """Raised when a section is not complete enough to render."""


def canon_sources_dir(project_id: str, *, create: bool = False) -> Path:
    """Return the project-local rendered canon sources directory."""

    path = project_canon_service.project_canon_dir(project_id, create=True) / CANON_SOURCES_DIRNAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def canon_sources_dir_for_context(context: ProjectContext, *, create: bool = False) -> Path:
    """Return the rendered canon sources directory for an existing context."""

    path = project_canon_service.project_canon_dir_for_context(context, create=True) / CANON_SOURCES_DIRNAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def canon_section_content_hash(stored_section: dict[str, Any]) -> str:
    """Return a stable hash of author-owned section content.

    Workflow-only fields are excluded so reopening or completing a section does
    not make unchanged canon content stale.
    """

    content = {
        "section_id": stored_section.get("section_id"),
        "answers": stored_section.get("answers") or {},
        "records": canon_record_identity_service.strip_record_identity_metadata(
            stored_section.get("records") or {}
        ),
    }
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def markdown_source_freshness(
    path: Path,
    *,
    manifest: dict[str, Any],
    schema: dict[str, Any],
    section_schema: dict[str, Any],
    stored_section: dict[str, Any],
    section_status: str,
) -> dict[str, Any]:
    """Determine whether a Markdown file represents current section content."""

    current_hash = canon_section_content_hash(stored_section)
    if not path.exists() or not path.is_file():
        return {
            "exists": False,
            "freshness_verified": True,
            "content_matches": False,
            "rendered_from_hash": "",
            "current_content_hash": current_hash,
            "verification_method": "missing_file",
            "render_status": (
                "ready_to_render"
                if section_status == "complete"
                else "not_rendered"
            ),
            "action_required": True,
        }

    markdown = path.read_text(encoding="utf-8")
    hash_match = re.search(
        r"^- Source Content SHA-256: `([0-9a-f]{64})`\s*$",
        markdown,
        re.MULTILINE,
    )

    schema_version = str(schema.get("version") or "").strip()
    requires_schema_version = schema_version == canon_template_service.CANON_TEMPLATE_SERVICE_VERSION
    schema_version_match = re.search(
        r"^- Template Schema Version: `([^`]*)`\s*$",
        markdown,
        re.MULTILINE,
    )

    if hash_match:
        rendered_hash = hash_match.group(1)
        rendered_schema_version = (
            schema_version_match.group(1).strip()
            if schema_version_match
            else ""
        )
        content_matches = (
            rendered_hash == current_hash
            and (
                not requires_schema_version
                or rendered_schema_version == schema_version
            )
        )
        verification_method = (
            "embedded_sha256_and_template_version"
            if requires_schema_version
            else "embedded_sha256"
        )
        freshness_verified = True
    else:
        rendered_hash = ""
        rendered_at_match = re.search(
            r"^- Rendered At: `([^`]*)`\s*$",
            markdown,
            re.MULTILINE,
        )
        rendered_at = rendered_at_match.group(1) if rendered_at_match else ""
        expected_legacy = _render_markdown_document(
            manifest=manifest,
            schema=schema,
            section_schema=section_schema,
            stored_section=stored_section,
            reference_catalog={},
            rendered_at=rendered_at,
            source_content_hash=None,
        )
        content_matches = bool(rendered_at) and markdown == expected_legacy
        verification_method = "legacy_exact_content"
        freshness_verified = True

    if section_status == "complete":
        render_status = "current" if content_matches else "ready_to_render"
    elif content_matches:
        render_status = "review_in_progress"
    else:
        render_status = "update_required"

    return {
        "exists": True,
        "freshness_verified": freshness_verified,
        "content_matches": content_matches,
        "rendered_from_hash": rendered_hash,
        "current_content_hash": current_hash,
        "verification_method": verification_method,
        "render_status": render_status,
        "action_required": render_status != "current",
    }


def get_canon_markdown_status(project_id: str) -> dict[str, Any]:
    """Return read-only status for rendered project-local canon Markdown sources."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_canon_markdown_status_for_context(context, manifest.to_dict())


def get_canon_markdown_status_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return Markdown render status for an existing project context."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    completion = _load_completion_for_context(context)
    author_canon = _load_author_canon_for_context(context)
    sources_dir = canon_sources_dir_for_context(context, create=False)
    rendered_files = _classified_markdown_files(
        schema,
        completion,
        author_canon,
        sources_dir,
        context.project_dir,
        manifest,
    )
    completed_sections = _completed_section_ids(schema, completion)
    current_files = [
        item for item in rendered_files
        if item.get("render_status") == "current"
        and item.get("freshness_verified") is True
    ]
    action_required_files = [
        item for item in rendered_files if item.get("action_required") is True
    ]

    return {
        "status": "ok",
        "service": CANON_MARKDOWN_RENDERER_SERVICE_MARKER,
        "schema_version": CANON_MARKDOWN_RENDERER_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": schema.get("template_id"),
        "genre": schema.get("genre"),
        "canon_sources_dir": _relative(sources_dir, context.project_dir),
        "completed_section_count": len(completed_sections),
        "rendered_file_count": len(rendered_files),
        "current_rendered_file_count": len(current_files),
        "stale_rendered_file_count": len(action_required_files),
        "action_required_file_count": len(action_required_files),
        "completed_sections": completed_sections,
        "rendered_files": rendered_files,
        "current_rendered_files": current_files,
        "stale_rendered_files": action_required_files,
        "action_required_files": action_required_files,
        "execution_locks": _execution_locks(),
    }


def render_completed_canon_sources(project_id: str) -> dict[str, Any]:
    """Render Markdown files for every completed author canon section."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    schema = _template_schema_for_manifest(manifest.to_dict())
    return render_completed_canon_sources_for_context(context, manifest.to_dict(), schema)


def render_completed_canon_sources_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render completed canon sources for an existing project context."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    author_canon = _load_author_canon_for_context(context)
    completion = _load_completion_for_context(context)
    reference_catalog = canon_reference_service.build_reference_catalog(author_canon, schema)
    output_dir = canon_sources_dir_for_context(context, create=True)

    rendered_files: list[dict[str, Any]] = []
    skipped_sections: list[dict[str, Any]] = []

    for index, section_schema in enumerate(schema.get("sections", []), start=1):
        section_id = str(section_schema.get("section_id") or "").strip()
        if not section_id:
            continue
        completion_record = _completion_record(completion, section_id)
        if completion_record.get("status") != "complete" or completion_record.get("missing_required_fields"):
            skipped_sections.append(
                {
                    "section_id": section_id,
                    "reason": "section_not_complete",
                    "status": completion_record.get("status", "not_started"),
                }
            )
            continue

        stored_section = _stored_section(author_canon, section_id)
        markdown = _render_markdown_document(
            manifest=manifest,
            schema=schema,
            section_schema=section_schema,
            stored_section=stored_section,
            reference_catalog=reference_catalog,
            rendered_at=utc_now_iso(),
            source_content_hash=None,
        )
        filename = _section_filename(index, section_id)
        path = output_dir / filename
        _write_text(path, markdown)
        rendered_files.append(
            {
                "section_id": section_id,
                "path": _relative(path, context.project_dir),
                "filename": filename,
            }
        )

    return {
        "status": "ok",
        "service": CANON_MARKDOWN_RENDERER_SERVICE_MARKER,
        "schema_version": CANON_MARKDOWN_RENDERER_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": schema.get("template_id"),
        "genre": schema.get("genre"),
        "canon_sources_dir": _relative(output_dir, context.project_dir),
        "rendered_file_count": len(rendered_files),
        "rendered_files": rendered_files,
        "skipped_sections": skipped_sections,
        "execution_locks": _execution_locks(),
    }


def render_section_markdown(project_id: str, section_id: str) -> dict[str, Any]:
    """Render one completed author canon section to a project-local Markdown file."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    schema = _template_schema_for_manifest(manifest.to_dict())
    return render_section_markdown_for_context(context, manifest.to_dict(), section_id, schema)


def render_section_markdown_for_context(
    context: ProjectContext,
    manifest: dict[str, Any],
    section_id: str,
    template_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render one completed section for an existing project context."""

    schema = template_schema or _template_schema_for_manifest(manifest)
    project_canon_service.ensure_author_canon_for_context(context, manifest, schema)

    section_schema, index = _section_schema_with_index(schema, section_id)
    canonical_section_id = str(section_schema.get("section_id"))
    author_canon = _load_author_canon_for_context(context)
    completion = _load_completion_for_context(context)
    completion_record = _completion_record(completion, canonical_section_id)

    if completion_record.get("status") != "complete" or completion_record.get("missing_required_fields"):
        raise CanonMarkdownSectionNotCompleteError(
            f"Canon section is not complete and cannot be rendered: {canonical_section_id}"
        )

    stored_section = _stored_section(author_canon, canonical_section_id)
    source_content_hash = canon_section_content_hash(stored_section)
    reference_catalog = canon_reference_service.build_reference_catalog(author_canon, schema)
    markdown = _render_markdown_document(
        manifest=manifest,
        schema=schema,
        section_schema=section_schema,
        stored_section=stored_section,
        reference_catalog=reference_catalog,
        rendered_at=utc_now_iso(),
        source_content_hash=source_content_hash,
    )
    output_dir = canon_sources_dir_for_context(context, create=True)
    filename = _section_filename(index, canonical_section_id)
    path = output_dir / filename
    _write_text(path, markdown)

    return {
        "status": "ok",
        "service": CANON_MARKDOWN_RENDERER_SERVICE_MARKER,
        "schema_version": CANON_MARKDOWN_RENDERER_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_id": schema.get("template_id"),
        "genre": schema.get("genre"),
        "section_id": canonical_section_id,
        "path": _relative(path, context.project_dir),
        "filename": filename,
        "source_content_hash": source_content_hash,
        "freshness_verified": True,
        "render_status": "current",
        "action_required": False,
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


def _section_schema_with_index(schema: dict[str, Any], section_id: str) -> tuple[dict[str, Any], int]:
    wanted = str(section_id or "").strip()
    for index, section in enumerate(schema.get("sections", []), start=1):
        if str(section.get("section_id") or "").strip() == wanted:
            return deepcopy(section), index
    raise CanonMarkdownSectionNotFoundError(f"Unknown canon section: {section_id}")


def _completion_record(completion: dict[str, Any], section_id: str) -> dict[str, Any]:
    records = completion.get("section_status") if isinstance(completion.get("section_status"), dict) else {}
    record = records.get(section_id) if isinstance(records, dict) else {}
    return record if isinstance(record, dict) else {}


def _completed_section_ids(schema: dict[str, Any], completion: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for section in schema.get("sections", []):
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        record = _completion_record(completion, section_id)
        if record.get("status") == "complete" and not record.get("missing_required_fields"):
            result.append(section_id)
    return result


def _stored_section(author_canon: dict[str, Any], section_id: str) -> dict[str, Any]:
    sections = author_canon.get("sections") if isinstance(author_canon.get("sections"), dict) else {}
    stored = sections.get(section_id) if isinstance(sections, dict) else {}
    if not isinstance(stored, dict):
        return {"section_id": section_id, "answers": {}, "records": {}}
    return deepcopy(stored)


def _existing_markdown_files(sources_dir: Path, project_dir: Path) -> list[dict[str, Any]]:
    if not sources_dir.exists():
        return []
    files: list[dict[str, Any]] = []
    for path in sorted(sources_dir.glob("*.md")):
        if not path.is_file():
            continue
        files.append(
            {
                "filename": path.name,
                "path": _relative(path, project_dir),
                "size_bytes": path.stat().st_size,
            }
        )
    return files


def _classified_markdown_files(
    schema: dict[str, Any],
    completion: dict[str, Any],
    author_canon: dict[str, Any],
    sources_dir: Path,
    project_dir: Path,
    manifest: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Classify stored Markdown through deterministic content verification."""

    manifest = manifest or {}
    existing = {
        item["filename"]: item
        for item in _existing_markdown_files(sources_dir, project_dir)
    }
    stored_sections = (
        author_canon.get("sections")
        if isinstance(author_canon.get("sections"), dict)
        else {}
    )
    result: list[dict[str, Any]] = []
    known_filenames: set[str] = set()

    for index, section in enumerate(schema.get("sections", []), start=1):
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue

        filename = _section_filename(index, section_id)
        known_filenames.add(filename)
        item = existing.get(filename)
        if not item:
            continue

        completion_record = _completion_record(completion, section_id)
        stored_section = (
            stored_sections.get(section_id)
            if isinstance(stored_sections, dict)
            else {}
        )
        stored_section = (
            stored_section
            if isinstance(stored_section, dict)
            else {"section_id": section_id, "answers": {}, "records": {}}
        )
        section_status = str(
            completion_record.get("status")
            or stored_section.get("status")
            or "not_started"
        )

        freshness = markdown_source_freshness(
            sources_dir / filename,
            manifest=manifest,
            schema=schema,
            section_schema=section,
            stored_section=stored_section,
            section_status=section_status,
        )

        classified = dict(item)
        classified.update(freshness)
        classified.update(
            {
                "section_id": section_id,
                "section_label": section.get("label") or section_id,
                "section_status": section_status,
            }
        )
        result.append(classified)

    for filename, item in existing.items():
        if filename in known_filenames:
            continue
        classified = dict(item)
        classified.update(
            {
                "section_id": "",
                "section_label": "Unmapped source",
                "section_status": "unknown",
                "freshness_verified": False,
                "content_matches": False,
                "render_status": "verification_required",
                "action_required": True,
                "verification_method": "unmapped_file",
            }
        )
        result.append(classified)

    return result

def _render_markdown_document(
    *,
    manifest: dict[str, Any],
    schema: dict[str, Any],
    section_schema: dict[str, Any],
    stored_section: dict[str, Any],
    reference_catalog: dict[str, list[dict[str, str]]],
    rendered_at: str,
    source_content_hash: str | None,
) -> str:
    section_id = str(section_schema.get("section_id") or "")
    lines: list[str] = [
        f"# {_markdown_text(section_schema.get('label') or section_id)}",
        "",
        f"- Project: {_markdown_text(manifest.get('project_name') or manifest.get('project_id') or '')}",
        f"- Project ID: `{_inline_code(manifest.get('project_id') or '')}`",
        f"- Template: `{_inline_code(schema.get('template_id') or '')}`",
        f"- Template Schema Version: `{_inline_code(schema.get('version') or '')}`",
        f"- Genre: `{_inline_code(schema.get('genre') or '')}`",
        f"- Section ID: `{_inline_code(section_id)}`",
        f"- Rendered At: `{_inline_code(rendered_at)}`",
        *(
            [f"- Source Content SHA-256: `{_inline_code(source_content_hash)}`"]
            if source_content_hash
            else []
        ),
        f"- Source: `{CANON_MARKDOWN_RENDERER_SERVICE_MARKER}`",
        "",
    ]

    purpose = _clean_scalar(section_schema.get("purpose"))
    if purpose:
        lines.extend(["## Purpose", "", _markdown_text(purpose), ""])

    guidance = _clean_scalar(section_schema.get("author_guidance"))
    if guidance:
        lines.extend(["## Author Guidance", "", _markdown_text(guidance), ""])

    lines.extend(["## Fields", ""])
    answers = stored_section.get("answers") if isinstance(stored_section.get("answers"), dict) else {}
    fields = section_schema.get("fields") if isinstance(section_schema.get("fields"), list) else []
    if fields:
        for field in fields:
            if field.get("author_hidden"):
                continue
            field_id = str(field.get("field_id") or "").strip()
            if not field_id:
                continue
            label = _clean_scalar(field.get("label")) or field_id
            value = answers.get(field_id) if isinstance(answers, dict) else None
            lines.extend(_render_field(label, value))
    else:
        lines.extend(["No direct fields defined for this section.", ""])

    records = section_schema.get("records") if isinstance(section_schema.get("records"), list) else []
    if records:
        lines.extend(["## Records", ""])
        stored_records = stored_section.get("records") if isinstance(stored_section.get("records"), dict) else {}
        for record_schema in records:
            lines.extend(_render_record_group(record_schema, stored_records, reference_catalog))
    else:
        lines.extend(["## Records", "", "No record groups defined for this section.", ""])

    lines.extend(
        [
            "---",
            "",
            "Renderer boundary: project-local Markdown source only. This file is not a knowledge pack, control packet, runtime memory, generated draft, or export artifact.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_field(label: str, value: Any) -> list[str]:
    lines = [f"### {_markdown_text(label)}", ""]
    if _is_blank(value):
        lines.extend(["_No answer provided._", ""])
        return lines

    if isinstance(value, list):
        for item in value:
            lines.append(f"- {_markdown_text(_clean_scalar(item))}")
        lines.append("")
        return lines

    if isinstance(value, dict):
        for key, item in value.items():
            lines.append(f"- **{_markdown_text(str(key))}:** {_markdown_text(_clean_scalar(item))}")
        lines.append("")
        return lines

    lines.extend([_markdown_text(_clean_scalar(value)), ""])
    return lines


def _render_record_group(
    record_schema: dict[str, Any],
    stored_records: dict[str, Any],
    reference_catalog: dict[str, list[dict[str, str]]],
) -> list[str]:
    record_id = str(record_schema.get("record_id") or "").strip()
    label = _clean_scalar(record_schema.get("label")) or record_id or "Record Group"
    rows = stored_records.get(record_id) if isinstance(stored_records, dict) else []
    if not isinstance(rows, list):
        rows = []

    lines = [f"### {_markdown_text(label)}", ""]
    if not rows:
        lines.extend(["_No records provided._", ""])
        return lines

    field_schemas = record_schema.get("fields") if isinstance(record_schema.get("fields"), list) else []
    visible_fields = {
        str(field.get("field_id") or ""): field
        for field in field_schemas
        if not field.get("author_hidden") and field.get("field_id")
    }

    for index, row in enumerate(rows, start=1):
        lines.extend([f"#### {index}. {_markdown_text(label)}", ""])
        if not isinstance(row, dict):
            lines.extend([_markdown_text(_clean_scalar(row)), ""])
            continue
        for field_id, field_schema in visible_fields.items():
            field_label = _clean_scalar(field_schema.get("label")) or field_id
            value = row.get(field_id)
            if field_schema.get("field_type") in canon_reference_service.REFERENCE_FIELD_TYPES:
                value = canon_reference_service.resolve_reference_display(
                    value,
                    field_schema=field_schema,
                    catalog=reference_catalog,
                )
            lines.extend(_render_record_field(field_label, value))
    return lines

def _render_record_field(label: str, value: Any) -> list[str]:
    if _is_blank(value):
        return [f"- **{_markdown_text(label)}:** _No answer provided._"]
    return [f"- **{_markdown_text(label)}:** {_markdown_text(_clean_scalar(value))}"]


def _section_filename(index: int, section_id: str) -> str:
    safe_id = _safe_filename(section_id)
    return f"{index:03d}_{safe_id}.md"


def _safe_filename(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "section"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    return str(value).strip()


def _markdown_text(value: Any) -> str:
    text = _clean_scalar(value)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _inline_code(value: Any) -> str:
    return _clean_scalar(value).replace("`", "")


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _execution_locks() -> dict[str, bool]:
    return {
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "draft_validation_enabled": False,
        "approved_persistence_enabled": False,
        "export_enabled": False,
    }
