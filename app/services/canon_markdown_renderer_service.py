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

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.projects.project_manifest import utc_now_iso
from app.services import canon_template_service, project_canon_service


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
    sources_dir = canon_sources_dir_for_context(context, create=False)
    rendered_files = _existing_markdown_files(sources_dir, context.project_dir)
    completed_sections = _completed_section_ids(schema, completion)

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
        "completed_sections": completed_sections,
        "rendered_files": rendered_files,
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
            rendered_at=utc_now_iso(),
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

    markdown = _render_markdown_document(
        manifest=manifest,
        schema=schema,
        section_schema=section_schema,
        stored_section=_stored_section(author_canon, canonical_section_id),
        rendered_at=utc_now_iso(),
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
        "execution_locks": _execution_locks(),
    }


def _template_schema_for_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
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


def _render_markdown_document(
    *,
    manifest: dict[str, Any],
    schema: dict[str, Any],
    section_schema: dict[str, Any],
    stored_section: dict[str, Any],
    rendered_at: str,
) -> str:
    section_id = str(section_schema.get("section_id") or "")
    lines: list[str] = [
        f"# {_markdown_text(section_schema.get('label') or section_id)}",
        "",
        f"- Project: {_markdown_text(manifest.get('project_name') or manifest.get('project_id') or '')}",
        f"- Project ID: `{_inline_code(manifest.get('project_id') or '')}`",
        f"- Template: `{_inline_code(schema.get('template_id') or '')}`",
        f"- Genre: `{_inline_code(schema.get('genre') or '')}`",
        f"- Section ID: `{_inline_code(section_id)}`",
        f"- Rendered At: `{_inline_code(rendered_at)}`",
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
            lines.extend(_render_record_group(record_schema, stored_records))
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


def _render_record_group(record_schema: dict[str, Any], stored_records: dict[str, Any]) -> list[str]:
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
    field_labels = {
        str(field.get("field_id") or ""): _clean_scalar(field.get("label")) or str(field.get("field_id") or "")
        for field in field_schemas
    }

    for index, row in enumerate(rows, start=1):
        lines.extend([f"#### {index}. {_markdown_text(label)}", ""])
        if not isinstance(row, dict):
            lines.extend([_markdown_text(_clean_scalar(row)), ""])
            continue
        for field_id, field_label in field_labels.items():
            if not field_id:
                continue
            lines.extend(_render_record_field(field_label, row.get(field_id)))
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
