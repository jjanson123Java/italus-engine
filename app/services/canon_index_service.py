"""
Project-local derived Canon Index.

Patch 16 owns deterministic retrieval state derived from normalized Author Canon.
Master/Author Canon remains the source of truth. This service never mutates Canon,
Planner state, Book Scope, continuity, generation state, or provenance.

The index is rebuilt atomically from project-local Canon JSON and is considered
fresh only when its recorded source hashes match the current Author Canon and
template snapshot.
"""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.services import canon_record_identity_service, canon_reference_service


CANON_INDEX_SERVICE_MARKER = "project-canon-index-boundary-20260816"
CANON_INDEX_SCHEMA_VERSION = "canon_index_v3"
CANON_INDEX_FILENAME = "canon_index.sqlite3"

INTERNAL_ID_FIELD = canon_record_identity_service.INTERNAL_ID_FIELD
_REFERENCE_FIELD_TYPES = {
    canon_reference_service.FIELD_RECORD_REF,
    canon_reference_service.FIELD_RECORD_REF_LIST,
}

EVENT_RELATIONSHIP_TYPES = frozenset(
    {
        "follows",
        "precedes",
        "same_anchor",
        "parallel_reaction",
        "alternate_perspective",
        "caused_by",
        "consequence_of",
    }
)

_RECORD_TYPE_BY_GROUP = {
    "characters": "character",
    "locations": "location",
    "events": "event",
    "life_events": "life_event",
    "interactions": "interaction",
    "signals": "signal",
    "clues": "clue",
    "systems": "system",
    "groups": "group",
    "custom_sections": "custom_section",
}

_SUMMARY_FIELDS = (
    "summary",
    "event_summary",
    "description",
    "canon_content",
    "purpose",
    "role",
    "allowed_scope",
    "meaning",
    "capabilities",
    "powers_or_capabilities",
    "continuity_notes",
)

_ALIAS_FIELDS = ("aliases", "story_code", "event_id", "code")
_INTERNAL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{32}$")


class CanonIndexError(RuntimeError):
    """Base error for Canon Index operations."""


class CanonIndexNotReadyError(CanonIndexError):
    """Raised when source Canon cannot safely produce an index."""


class CanonIndexIntegrityError(CanonIndexError):
    """Raised when stable identity or index invariants are violated."""


def canon_index_path(project_id: str) -> Path:
    """Return the project-local derived Canon Index path."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return canon_index_path_for_context(context)


def canon_index_path_for_context(context: ProjectContext) -> Path:
    return context.project_dir / "canon" / CANON_INDEX_FILENAME


def get_index_status(project_id: str) -> dict[str, Any]:
    """Return missing/current/stale/corrupt status without rebuilding."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return get_index_status_for_context(context)


def get_index_status_for_context(context: ProjectContext) -> dict[str, Any]:
    index_path = canon_index_path_for_context(context)
    source = _load_index_source(context)

    base = {
        "status": "ok",
        "service": CANON_INDEX_SERVICE_MARKER,
        "schema_version": CANON_INDEX_SCHEMA_VERSION,
        "project_id": context.project_id,
        "index_path": _relative(index_path, context.project_dir),
        "source_hashes": source["hashes"],
        "execution_locks": _execution_locks(),
    }

    if not index_path.exists():
        return {
            **base,
            "index_state": "missing",
            "fresh": False,
            "rebuild_required": True,
            "counts": _empty_counts(),
            "index_content_hash": "",
        }

    try:
        metadata = _read_metadata(index_path)
        counts = _read_counts(index_path)
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        return {
            **base,
            "index_state": "corrupt",
            "fresh": False,
            "rebuild_required": True,
            "counts": _empty_counts(),
            "index_content_hash": "",
            "error": str(exc),
        }

    schema_current = metadata.get("schema_version") == CANON_INDEX_SCHEMA_VERSION
    source_current = metadata.get("source_set_sha256") == source["hashes"]["source_set_sha256"]
    project_current = metadata.get("project_id") == context.project_id
    fresh = bool(schema_current and source_current and project_current)

    return {
        **base,
        "index_state": "current" if fresh else "stale",
        "fresh": fresh,
        "rebuild_required": not fresh,
        "counts": counts,
        "index_content_hash": metadata.get("index_content_hash", ""),
        "indexed_source_hashes": {
            "author_canon_sha256": metadata.get("author_canon_sha256", ""),
            "template_snapshot_sha256": metadata.get("template_snapshot_sha256", ""),
            "source_set_sha256": metadata.get("source_set_sha256", ""),
        },
    }


def rebuild_index(project_id: str) -> dict[str, Any]:
    """Atomically rebuild derived index content from project-local Author Canon."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return rebuild_index_for_context(context)


def rebuild_index_for_context(context: ProjectContext) -> dict[str, Any]:
    source = _load_index_source(context)
    rows = _build_index_rows(
        author_canon=source["author_canon"],
        schema=source["schema"],
    )
    logical_content_hash = _index_content_hash(rows)

    index_path = canon_index_path_for_context(context)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = index_path.with_name(f".{index_path.name}.{os.getpid()}.tmp")
    if temp_path.exists():
        temp_path.unlink()

    metadata = {
        "service": CANON_INDEX_SERVICE_MARKER,
        "schema_version": CANON_INDEX_SCHEMA_VERSION,
        "project_id": context.project_id,
        "template_version": str(source["schema"].get("version") or ""),
        "author_canon_sha256": source["hashes"]["author_canon_sha256"],
        "template_snapshot_sha256": source["hashes"]["template_snapshot_sha256"],
        "source_set_sha256": source["hashes"]["source_set_sha256"],
        "index_content_hash": logical_content_hash,
        "entity_count": str(len(rows["entities"])),
        "alias_count": str(len(rows["aliases"])),
        "relationship_count": str(len(rows["relationships"])),
        "dependency_count": str(len(rows["dependencies"])),
        "issue_count": str(len(rows["issues"])),
    }

    try:
        with closing(sqlite3.connect(temp_path)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            _create_schema(conn)
            _insert_rows(conn, rows, metadata)
            conn.commit()
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise CanonIndexIntegrityError(
                    f"SQLite integrity check failed: {integrity[0] if integrity else 'unknown'}"
                )
        os.replace(temp_path, index_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    status = get_index_status_for_context(context)
    if status.get("fresh") is not True:
        raise CanonIndexIntegrityError("Canon Index rebuild did not produce fresh derived state.")
    if status.get("index_content_hash") != logical_content_hash:
        raise CanonIndexIntegrityError("Canon Index logical content hash changed during persistence.")
    status["rebuilt"] = True
    return status


def ensure_current_index(project_id: str) -> dict[str, Any]:
    """Return a current index, rebuilding missing/stale derived state."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    status = get_index_status_for_context(context)
    if status.get("fresh") is True:
        status["rebuilt"] = False
        return status
    return rebuild_index_for_context(context)


def get_record_by_id(project_id: str, internal_id: str) -> dict[str, Any]:
    """Return one Canon Index entity by immutable stable record ID."""

    ensure_current_index(project_id)
    index_path = canon_index_path(project_id)
    record_id = str(internal_id or "").strip()
    if not record_id:
        return {
            "status": "missing",
            "service": CANON_INDEX_SERVICE_MARKER,
            "project_id": project_id,
            "record": None,
        }

    with closing(sqlite3.connect(index_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT
                internal_id,
                record_type,
                record_group_id,
                display_label,
                source_section_id,
                source_revision,
                source_hash,
                summary,
                available_from_book,
                date_or_sequence,
                story_code,
                narrative_type,
                story_phase,
                escalation_metadata_json,
                planner_sort_metadata_json
            FROM canon_entities
            WHERE internal_id = ?
            """,
            (record_id,),
        ).fetchone()

    return {
        "status": "found" if row is not None else "missing",
        "service": CANON_INDEX_SERVICE_MARKER,
        "project_id": project_id,
        "record": _decorate_index_row(dict(row)) if row is not None else None,
    }



def list_records(
    project_id: str,
    *,
    record_types: Iterable[str] | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    """Return deterministic Canon Index catalog rows for bounded planning readers.

    Retrieval only. This does not evaluate Story Eligibility, mutate Book Scope,
    modify Canon, or call a model/provider.
    """

    ensure_current_index(project_id)
    index_path = canon_index_path(project_id)
    safe_limit = max(1, min(int(limit or 5000), 10000))
    type_values = sorted(
        {
            str(value).strip()
            for value in (record_types or [])
            if str(value).strip()
        }
    )

    type_clause = ""
    params: list[Any] = []
    if type_values:
        placeholders = ", ".join("?" for _ in type_values)
        type_clause = f"WHERE record_type IN ({placeholders})"
        params.extend(type_values)

    sql = f"""
        SELECT
            internal_id,
            record_type,
            record_group_id,
            display_label,
            source_section_id,
            source_revision,
            source_hash,
            summary,
            available_from_book,
            date_or_sequence,
            story_code,
            narrative_type,
            story_phase,
            escalation_metadata_json,
            planner_sort_metadata_json
        FROM canon_entities
        {type_clause}
        ORDER BY record_group_id, normalized_label, internal_id
        LIMIT ?
    """
    params.append(safe_limit)

    with closing(sqlite3.connect(index_path)) as conn:
        conn.row_factory = sqlite3.Row
        entity_rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        ids = [row["internal_id"] for row in entity_rows]
        aliases_by_id: dict[str, list[str]] = {record_id: [] for record_id in ids}
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            alias_rows = conn.execute(
                f"""
                SELECT internal_id, alias
                FROM canon_aliases
                WHERE internal_id IN ({placeholders})
                ORDER BY internal_id, normalized_alias, alias
                """,
                ids,
            ).fetchall()
            for row in alias_rows:
                aliases_by_id[str(row["internal_id"])].append(str(row["alias"]))

    for row in entity_rows:
        row["aliases"] = aliases_by_id.get(str(row["internal_id"]), [])
        _decorate_index_row(row)

    return {
        "status": "ok",
        "service": CANON_INDEX_SERVICE_MARKER,
        "project_id": project_id,
        "record_types": type_values,
        "result_count": len(entity_rows),
        "results": entity_rows,
    }


def list_records_current(
    project_id: str,
    *,
    record_types: Iterable[str] | None = None,
    limit: int = 5000,
) -> dict[str, Any]:
    """Return rows from an already-current Canon Index without rechecking freshness.

    Bulk planner callers must call ensure_current_index() once before using this
    helper. It intentionally performs retrieval only.
    """

    index_path = canon_index_path(project_id)
    if not index_path.exists():
        raise CanonIndexError("Canon Index is not available; call ensure_current_index first.")
    safe_limit = max(1, min(int(limit or 5000), 10000))
    type_values = sorted(
        {str(value).strip() for value in (record_types or []) if str(value).strip()}
    )
    type_clause = ""
    params: list[Any] = []
    if type_values:
        placeholders = ", ".join("?" for _ in type_values)
        type_clause = f"WHERE record_type IN ({placeholders})"
        params.extend(type_values)
    sql = f"""
        SELECT
            internal_id, record_type, record_group_id, display_label,
            source_section_id, source_revision, source_hash, summary,
            available_from_book, date_or_sequence, story_code, narrative_type,
            story_phase, escalation_metadata_json, planner_sort_metadata_json
        FROM canon_entities
        {type_clause}
        ORDER BY record_group_id, normalized_label, internal_id
        LIMIT ?
    """
    params.append(safe_limit)
    with closing(sqlite3.connect(index_path)) as conn:
        conn.row_factory = sqlite3.Row
        entity_rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        ids = [row["internal_id"] for row in entity_rows]
        aliases_by_id: dict[str, list[str]] = {record_id: [] for record_id in ids}
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            alias_rows = conn.execute(
                f"""
                SELECT internal_id, alias
                FROM canon_aliases
                WHERE internal_id IN ({placeholders})
                ORDER BY internal_id, normalized_alias, alias
                """,
                ids,
            ).fetchall()
            for row in alias_rows:
                aliases_by_id[str(row["internal_id"])].append(str(row["alias"]))
    for row in entity_rows:
        row["aliases"] = aliases_by_id.get(str(row["internal_id"]), [])
        _decorate_index_row(row)
    return {
        "status": "ok",
        "service": CANON_INDEX_SERVICE_MARKER,
        "project_id": project_id,
        "record_types": type_values,
        "result_count": len(entity_rows),
        "results": entity_rows,
    }


def resolve_record_key(
    project_id: str,
    value: str,
    *,
    record_group_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an exact label/alias without silently choosing ambiguity."""

    ensure_current_index(project_id)
    index_path = canon_index_path(project_id)
    normalized = _normalize_search_text(value)
    if not normalized:
        return {"status": "missing", "query": value, "candidates": []}

    with closing(sqlite3.connect(index_path)) as conn:
        conn.row_factory = sqlite3.Row
        params: list[Any] = [normalized, normalized]
        group_clause = ""
        if record_group_id:
            group_clause = " AND e.record_group_id = ?"
            params.append(str(record_group_id))

        rows = conn.execute(
            f"""
            SELECT DISTINCT
                e.internal_id,
                e.record_type,
                e.record_group_id,
                e.display_label,
                e.source_section_id
            FROM canon_entities e
            LEFT JOIN canon_aliases a ON a.internal_id = e.internal_id
            WHERE (e.normalized_label = ? OR a.normalized_alias = ?)
            {group_clause}
            ORDER BY e.internal_id
            """,
            params,
        ).fetchall()

    candidates = [dict(row) for row in rows]
    if not candidates:
        status = "missing"
    elif len(candidates) == 1:
        status = "unique"
    else:
        status = "ambiguous"
    return {"status": status, "query": value, "candidates": candidates}


def search_index(
    project_id: str,
    query: str,
    *,
    record_types: Iterable[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Deterministic structured label/alias/summary lookup.

    This is retrieval only. It performs no Story Eligibility, Planner intent,
    Scope mutation, or provider/model call.
    """

    ensure_current_index(project_id)
    index_path = canon_index_path(project_id)
    normalized = _normalize_search_text(query)
    if not normalized:
        return {
            "status": "ok",
            "service": CANON_INDEX_SERVICE_MARKER,
            "query": query,
            "results": [],
        }

    safe_limit = max(1, min(int(limit or 50), 200))
    type_values = sorted({str(value).strip() for value in (record_types or []) if str(value).strip()})
    escaped = _escape_like(normalized)
    prefix = escaped + "%"
    contains = "%" + escaped + "%"

    type_clause = ""
    type_params: list[Any] = []
    if type_values:
        placeholders = ", ".join("?" for _ in type_values)
        type_clause = f" AND e.record_type IN ({placeholders})"
        type_params = type_values

    sql = f"""
        WITH matches AS (
            SELECT e.internal_id, 0 AS rank
            FROM canon_entities e
            WHERE e.normalized_label = ? {type_clause}
            UNION ALL
            SELECT e.internal_id, 1 AS rank
            FROM canon_entities e
            JOIN canon_aliases a ON a.internal_id = e.internal_id
            WHERE a.normalized_alias = ? {type_clause}
            UNION ALL
            SELECT e.internal_id, 2 AS rank
            FROM canon_entities e
            WHERE e.normalized_label LIKE ? ESCAPE '\\' {type_clause}
            UNION ALL
            SELECT e.internal_id, 3 AS rank
            FROM canon_entities e
            JOIN canon_aliases a ON a.internal_id = e.internal_id
            WHERE a.normalized_alias LIKE ? ESCAPE '\\' {type_clause}
            UNION ALL
            SELECT e.internal_id, 4 AS rank
            FROM canon_entities e
            WHERE e.normalized_label LIKE ? ESCAPE '\\'
               OR e.normalized_summary LIKE ? ESCAPE '\\'
               {type_clause}
            UNION ALL
            SELECT e.internal_id, 5 AS rank
            FROM canon_entities e
            JOIN canon_aliases a ON a.internal_id = e.internal_id
            WHERE a.normalized_alias LIKE ? ESCAPE '\\' {type_clause}
        ),
        ranked AS (
            SELECT internal_id, MIN(rank) AS rank
            FROM matches
            GROUP BY internal_id
        )
        SELECT
            e.internal_id,
            e.record_type,
            e.record_group_id,
            e.display_label,
            e.source_section_id,
            e.summary,
            e.available_from_book,
            e.story_code,
            e.narrative_type,
            ranked.rank
        FROM ranked
        JOIN canon_entities e ON e.internal_id = ranked.internal_id
        ORDER BY ranked.rank, e.normalized_label, e.internal_id
        LIMIT ?
    """

    params: list[Any] = []
    for values in [
        [normalized],
        [normalized],
        [prefix],
        [prefix],
        [contains, contains],
        [contains],
    ]:
        params.extend(values)
        params.extend(type_params)
    params.append(safe_limit)

    with closing(sqlite3.connect(index_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    return {
        "status": "ok",
        "service": CANON_INDEX_SERVICE_MARKER,
        "query": query,
        "results": [dict(row) for row in rows],
    }


def relationships_for_record(
    project_id: str,
    internal_id: str,
    *,
    direction: str = "both",
    relationship_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return deterministic ID-backed relationship edges for one Canon record."""

    if direction not in {"outgoing", "incoming", "both"}:
        raise ValueError("direction must be outgoing, incoming, or both")

    ensure_current_index(project_id)
    index_path = canon_index_path(project_id)
    types = sorted({str(value).strip() for value in (relationship_types or []) if str(value).strip()})
    type_clause = ""
    type_params: list[Any] = []
    if types:
        placeholders = ", ".join("?" for _ in types)
        type_clause = f" AND r.relationship_type IN ({placeholders})"
        type_params = types

    queries: list[tuple[str, list[Any]]] = []
    if direction in {"outgoing", "both"}:
        queries.append(
            (
                f"""
                SELECT
                    'outgoing' AS direction,
                    r.source_internal_id,
                    r.relationship_type,
                    r.target_internal_id,
                    r.source_section_id,
                    r.source_record_group_id,
                    r.source_field_id,
                    r.ordinal,
                    target.display_label AS related_display_label,
                    target.record_type AS related_record_type
                FROM canon_relationships r
                JOIN canon_entities target ON target.internal_id = r.target_internal_id
                WHERE r.source_internal_id = ? {type_clause}
                """,
                [internal_id, *type_params],
            )
        )
    if direction in {"incoming", "both"}:
        queries.append(
            (
                f"""
                SELECT
                    'incoming' AS direction,
                    r.source_internal_id,
                    r.relationship_type,
                    r.target_internal_id,
                    r.source_section_id,
                    r.source_record_group_id,
                    r.source_field_id,
                    r.ordinal,
                    source.display_label AS related_display_label,
                    source.record_type AS related_record_type
                FROM canon_relationships r
                JOIN canon_entities source ON source.internal_id = r.source_internal_id
                WHERE r.target_internal_id = ? {type_clause}
                """,
                [internal_id, *type_params],
            )
        )

    edges: list[dict[str, Any]] = []
    with closing(sqlite3.connect(index_path)) as conn:
        conn.row_factory = sqlite3.Row
        for sql, params in queries:
            edges.extend(dict(row) for row in conn.execute(sql, params).fetchall())

    edges.sort(
        key=lambda item: (
            str(item["direction"]),
            str(item["relationship_type"]),
            int(item["ordinal"]),
            str(item["source_internal_id"]),
            str(item["target_internal_id"]),
        )
    )
    return {
        "status": "ok",
        "service": CANON_INDEX_SERVICE_MARKER,
        "project_id": project_id,
        "internal_id": internal_id,
        "direction": direction,
        "relationships": edges,
    }


def index_issues(project_id: str) -> dict[str, Any]:
    """Return non-authoritative indexing diagnostics such as unresolved legacy refs."""

    ensure_current_index(project_id)
    index_path = canon_index_path(project_id)
    with closing(sqlite3.connect(index_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                code,
                source_internal_id,
                source_section_id,
                source_record_group_id,
                source_field_id,
                raw_value,
                reason
            FROM canon_index_issues
            ORDER BY source_section_id, source_record_group_id, source_internal_id, source_field_id, raw_value
            """
        ).fetchall()
    return {
        "status": "ok",
        "service": CANON_INDEX_SERVICE_MARKER,
        "project_id": project_id,
        "issues": [dict(row) for row in rows],
    }


def _load_index_source(context: ProjectContext) -> dict[str, Any]:
    canon_dir = context.project_dir / "canon"
    author_path = canon_dir / "author_canon.json"
    snapshot_path = canon_dir / "template_snapshot.json"

    if not author_path.exists():
        raise CanonIndexNotReadyError(
            f"Author Canon does not exist for project {context.project_id}."
        )
    if not snapshot_path.exists():
        raise CanonIndexNotReadyError(
            f"Template snapshot does not exist for project {context.project_id}."
        )

    author_canon = project_loader.read_json(author_path, default={})
    snapshot = project_loader.read_json(snapshot_path, default={})
    schema = snapshot.get("questionnaire") if isinstance(snapshot, dict) else None
    if not isinstance(author_canon, dict) or not isinstance(schema, dict):
        raise CanonIndexNotReadyError(
            f"Project {context.project_id} does not have valid Author Canon/template source."
        )

    identity_findings = canon_record_identity_service.record_identity_findings(author_canon)
    if identity_findings:
        raise CanonIndexIntegrityError(
            "Stable Canon record identity validation failed; Canon Index rebuild refused."
        )

    author_hash = _canonical_json_hash(author_canon)
    template_hash = _canonical_json_hash(schema)
    source_set_hash = _canonical_json_hash(
        {
            "project_id": context.project_id,
            "author_canon_sha256": author_hash,
            "template_snapshot_sha256": template_hash,
        }
    )
    return {
        "author_canon": author_canon,
        "schema": schema,
        "hashes": {
            "author_canon_sha256": author_hash,
            "template_snapshot_sha256": template_hash,
            "source_set_sha256": source_set_hash,
        },
    }


def _build_index_rows(
    *,
    author_canon: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    sections = author_canon.get("sections")
    if not isinstance(sections, dict):
        sections = {}

    catalog = canon_reference_service.build_reference_catalog(author_canon, schema)
    display_by_id = {
        str(entry.get("record_id") or ""): str(entry.get("label") or "")
        for entries in catalog.values()
        for entry in entries
        if str(entry.get("record_id") or "").strip()
    }

    entities: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    owners: dict[str, tuple[str, str, int]] = {}
    reference_specs = _reference_specs(schema)

    source_revision = str((author_canon.get("metadata") or {}).get("updated_at") or "")

    for section_schema in _schema_sections(schema):
        section_id = str(section_schema.get("section_id") or "").strip()
        stored_section = sections.get(section_id)
        if not isinstance(stored_section, dict):
            continue
        stored_records = stored_section.get("records")
        if not isinstance(stored_records, dict):
            continue

        for record_schema in _record_schemas(section_schema):
            group_id = str(record_schema.get("record_id") or "").strip()
            if not group_id:
                continue
            rows = stored_records.get(group_id)
            if not isinstance(rows, list):
                continue

            field_specs = reference_specs.get((section_id, group_id), {})
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                internal_id = str(row.get(INTERNAL_ID_FIELD) or "").strip()
                if not internal_id:
                    raise CanonIndexIntegrityError(
                        f"Missing internal_id in {section_id}.{group_id}[{index}]."
                    )
                if internal_id in owners:
                    prior = owners[internal_id]
                    raise CanonIndexIntegrityError(
                        f"Duplicate internal_id {internal_id} in "
                        f"{section_id}.{group_id}[{index}] and {prior[0]}.{prior[1]}[{prior[2]}]."
                    )
                owners[internal_id] = (section_id, group_id, index)

                display_label = display_by_id.get(internal_id) or internal_id
                summary = _summary_for_record(row)
                entity = {
                    "internal_id": internal_id,
                    "record_type": _RECORD_TYPE_BY_GROUP.get(group_id, group_id),
                    "record_group_id": group_id,
                    "display_label": display_label,
                    "normalized_label": _normalize_search_text(display_label),
                    "source_section_id": section_id,
                    "source_revision": source_revision,
                    "source_hash": _canonical_json_hash(
                        {
                            "section_id": section_id,
                            "record_group_id": group_id,
                            "record": row,
                        }
                    ),
                    "summary": summary,
                    "normalized_summary": _normalize_search_text(summary),
                    "available_from_book": _clean_scalar(row.get("available_from_book")),
                    "date_or_sequence": _clean_scalar(row.get("date_or_sequence")),
                    "story_code": _clean_scalar(row.get("story_code")),
                    "narrative_type": _clean_scalar(row.get("narrative_type")),
                    "story_phase": _clean_scalar(row.get("story_phase")),
                    "escalation_metadata_json": _stable_json_string(
                        row.get("escalation_metadata")
                        if isinstance(row.get("escalation_metadata"), (dict, list))
                        else {}
                    ),
                    "planner_sort_metadata_json": _stable_json_string(
                        _planner_sort_metadata(row)
                    ),
                }
                entities.append(entity)

                for alias in _aliases_for_record(row, display_label):
                    aliases.append(
                        {
                            "internal_id": internal_id,
                            "alias": alias,
                            "normalized_alias": _normalize_search_text(alias),
                        }
                    )

                for field_id, spec in field_specs.items():
                    raw_value = row.get(field_id)
                    if _is_blank(raw_value):
                        continue
                    values = raw_value if isinstance(raw_value, list) else [raw_value]
                    for ordinal, raw_target in enumerate(values):
                        target_id = str(raw_target or "").strip()
                        if _INTERNAL_ID_RE.fullmatch(target_id):
                            relationships.append(
                                {
                                    "source_internal_id": internal_id,
                                    "relationship_type": field_id,
                                    "target_internal_id": target_id,
                                    "target_record_group_id": ",".join(spec["reference_targets"]),
                                    "source_section_id": section_id,
                                    "source_record_group_id": group_id,
                                    "source_field_id": field_id,
                                    "ordinal": ordinal,
                                }
                            )
                        else:
                            issues.append(
                                {
                                    "code": "unresolved_schema_reference",
                                    "source_internal_id": internal_id,
                                    "source_section_id": section_id,
                                    "source_record_group_id": group_id,
                                    "source_field_id": field_id,
                                    "raw_value": _stable_json_string(raw_target),
                                    "reason": "reference_value_is_not_internal_id",
                                }
                            )

    entity_ids = {item["internal_id"] for item in entities}
    valid_relationships: list[dict[str, Any]] = []
    for edge in relationships:
        if edge["target_internal_id"] not in entity_ids:
            issues.append(
                {
                    "code": "missing_relationship_target",
                    "source_internal_id": edge["source_internal_id"],
                    "source_section_id": edge["source_section_id"],
                    "source_record_group_id": edge["source_record_group_id"],
                    "source_field_id": edge["source_field_id"],
                    "raw_value": _stable_json_string(edge["target_internal_id"]),
                    "reason": "target_internal_id_not_found",
                }
            )
            continue
        valid_relationships.append(edge)

    entities.sort(key=lambda item: item["internal_id"])
    aliases = _dedupe_dict_rows(
        aliases,
        key=lambda item: (item["internal_id"], item["normalized_alias"]),
    )
    aliases.sort(key=lambda item: (item["internal_id"], item["normalized_alias"], item["alias"]))
    valid_relationships.sort(
        key=lambda item: (
            item["source_internal_id"],
            item["relationship_type"],
            int(item["ordinal"]),
            item["target_internal_id"],
        )
    )
    issues.sort(
        key=lambda item: (
            item["source_section_id"],
            item["source_record_group_id"],
            item["source_internal_id"],
            item["source_field_id"],
            item["raw_value"],
        )
    )

    return {
        "entities": entities,
        "aliases": aliases,
        "relationships": valid_relationships,
        "dependencies": dependencies,
        "issues": issues,
    }


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE canon_index_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE canon_entities (
            internal_id TEXT PRIMARY KEY,
            record_type TEXT NOT NULL,
            record_group_id TEXT NOT NULL,
            display_label TEXT NOT NULL,
            normalized_label TEXT NOT NULL,
            source_section_id TEXT NOT NULL,
            source_revision TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            summary TEXT NOT NULL,
            normalized_summary TEXT NOT NULL,
            available_from_book TEXT NOT NULL,
            date_or_sequence TEXT NOT NULL,
            story_code TEXT NOT NULL,
            narrative_type TEXT NOT NULL,
            story_phase TEXT NOT NULL,
            escalation_metadata_json TEXT NOT NULL,
            planner_sort_metadata_json TEXT NOT NULL
        );

        CREATE INDEX idx_canon_entities_normalized_label
            ON canon_entities(normalized_label);
        CREATE INDEX idx_canon_entities_record_type
            ON canon_entities(record_type);
        CREATE INDEX idx_canon_entities_group
            ON canon_entities(record_group_id);

        CREATE TABLE canon_aliases (
            internal_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            PRIMARY KEY (internal_id, normalized_alias),
            FOREIGN KEY (internal_id) REFERENCES canon_entities(internal_id) ON DELETE CASCADE
        );

        CREATE INDEX idx_canon_aliases_normalized_alias
            ON canon_aliases(normalized_alias);

        CREATE TABLE canon_relationships (
            source_internal_id TEXT NOT NULL,
            relationship_type TEXT NOT NULL,
            target_internal_id TEXT NOT NULL,
            target_record_group_id TEXT NOT NULL,
            source_section_id TEXT NOT NULL,
            source_record_group_id TEXT NOT NULL,
            source_field_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            PRIMARY KEY (
                source_internal_id,
                relationship_type,
                target_internal_id,
                source_field_id,
                ordinal
            ),
            FOREIGN KEY (source_internal_id) REFERENCES canon_entities(internal_id) ON DELETE CASCADE,
            FOREIGN KEY (target_internal_id) REFERENCES canon_entities(internal_id) ON DELETE CASCADE
        );

        CREATE INDEX idx_canon_relationships_source
            ON canon_relationships(source_internal_id, relationship_type);
        CREATE INDEX idx_canon_relationships_target
            ON canon_relationships(target_internal_id, relationship_type);

        CREATE TABLE canon_dependencies (
            source_internal_id TEXT NOT NULL,
            dependency_type TEXT NOT NULL,
            target_internal_id TEXT NOT NULL,
            source_field_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            PRIMARY KEY (
                source_internal_id,
                dependency_type,
                target_internal_id,
                source_field_id,
                ordinal
            ),
            FOREIGN KEY (source_internal_id) REFERENCES canon_entities(internal_id) ON DELETE CASCADE,
            FOREIGN KEY (target_internal_id) REFERENCES canon_entities(internal_id) ON DELETE CASCADE
        );

        CREATE TABLE canon_index_issues (
            issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            source_internal_id TEXT NOT NULL,
            source_section_id TEXT NOT NULL,
            source_record_group_id TEXT NOT NULL,
            source_field_id TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            reason TEXT NOT NULL
        );
        """
    )


def _insert_rows(
    conn: sqlite3.Connection,
    rows: dict[str, list[dict[str, Any]]],
    metadata: dict[str, str],
) -> None:
    conn.executemany(
        """
        INSERT INTO canon_entities (
            internal_id, record_type, record_group_id, display_label,
            normalized_label, source_section_id, source_revision, source_hash,
            summary, normalized_summary, available_from_book, date_or_sequence, story_code,
            narrative_type, story_phase, escalation_metadata_json, planner_sort_metadata_json
        ) VALUES (
            :internal_id, :record_type, :record_group_id, :display_label,
            :normalized_label, :source_section_id, :source_revision, :source_hash,
            :summary, :normalized_summary, :available_from_book, :date_or_sequence, :story_code,
            :narrative_type, :story_phase, :escalation_metadata_json, :planner_sort_metadata_json
        )
        """,
        rows["entities"],
    )
    conn.executemany(
        """
        INSERT INTO canon_aliases (internal_id, alias, normalized_alias)
        VALUES (:internal_id, :alias, :normalized_alias)
        """,
        rows["aliases"],
    )
    conn.executemany(
        """
        INSERT INTO canon_relationships (
            source_internal_id, relationship_type, target_internal_id,
            target_record_group_id, source_section_id, source_record_group_id,
            source_field_id, ordinal
        ) VALUES (
            :source_internal_id, :relationship_type, :target_internal_id,
            :target_record_group_id, :source_section_id, :source_record_group_id,
            :source_field_id, :ordinal
        )
        """,
        rows["relationships"],
    )
    conn.executemany(
        """
        INSERT INTO canon_dependencies (
            source_internal_id, dependency_type, target_internal_id,
            source_field_id, ordinal
        ) VALUES (
            :source_internal_id, :dependency_type, :target_internal_id,
            :source_field_id, :ordinal
        )
        """,
        rows["dependencies"],
    )
    conn.executemany(
        """
        INSERT INTO canon_index_issues (
            code, source_internal_id, source_section_id, source_record_group_id,
            source_field_id, raw_value, reason
        ) VALUES (
            :code, :source_internal_id, :source_section_id, :source_record_group_id,
            :source_field_id, :raw_value, :reason
        )
        """,
        rows["issues"],
    )
    conn.executemany(
        "INSERT INTO canon_index_metadata (key, value) VALUES (?, ?)",
        sorted((str(key), str(value)) for key, value in metadata.items()),
    )


def _read_metadata(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute(
            "SELECT key, value FROM canon_index_metadata ORDER BY key"
        ).fetchall()
    return {str(key): str(value) for key, value in rows}


def _read_counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as conn:
        return {
            "entities": int(conn.execute("SELECT COUNT(*) FROM canon_entities").fetchone()[0]),
            "aliases": int(conn.execute("SELECT COUNT(*) FROM canon_aliases").fetchone()[0]),
            "relationships": int(
                conn.execute("SELECT COUNT(*) FROM canon_relationships").fetchone()[0]
            ),
            "dependencies": int(
                conn.execute("SELECT COUNT(*) FROM canon_dependencies").fetchone()[0]
            ),
            "issues": int(conn.execute("SELECT COUNT(*) FROM canon_index_issues").fetchone()[0]),
        }


def _empty_counts() -> dict[str, int]:
    return {
        "entities": 0,
        "aliases": 0,
        "relationships": 0,
        "dependencies": 0,
        "issues": 0,
    }


def _index_content_hash(rows: dict[str, list[dict[str, Any]]]) -> str:
    return _canonical_json_hash(
        {
            "schema_version": CANON_INDEX_SCHEMA_VERSION,
            "entities": rows["entities"],
            "aliases": rows["aliases"],
            "relationships": rows["relationships"],
            "dependencies": rows["dependencies"],
            "issues": rows["issues"],
        }
    )


def _reference_specs(
    schema: dict[str, Any],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    result: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for section in _schema_sections(schema):
        section_id = str(section.get("section_id") or "").strip()
        for record_schema in _record_schemas(section):
            group_id = str(record_schema.get("record_id") or "").strip()
            fields: dict[str, dict[str, Any]] = {}
            for field in record_schema.get("fields", []):
                if not isinstance(field, dict):
                    continue
                if str(field.get("field_type") or "").strip() not in _REFERENCE_FIELD_TYPES:
                    continue
                field_id = str(field.get("field_id") or "").strip()
                targets = [
                    str(value).strip()
                    for value in (field.get("reference_targets") or [])
                    if str(value).strip()
                ]
                if field_id:
                    fields[field_id] = {"reference_targets": targets}
            result[(section_id, group_id)] = fields
    return result


def _schema_sections(schema: dict[str, Any]) -> list[dict[str, Any]]:
    value = schema.get("sections") if isinstance(schema, dict) else []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _record_schemas(section_schema: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("record_schemas", "records", "record_groups"):
        value = section_schema.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _summary_for_record(row: dict[str, Any]) -> str:
    for field_id in _SUMMARY_FIELDS:
        value = row.get(field_id)
        if isinstance(value, list):
            value = "; ".join(str(item) for item in value if str(item or "").strip())
        cleaned = " ".join(str(value or "").split())
        if cleaned:
            return cleaned[:1000]
    return ""


def _aliases_for_record(row: dict[str, Any], display_label: str) -> list[str]:
    values: list[str] = []
    for field_id in _ALIAS_FIELDS:
        raw = row.get(field_id)
        if _is_blank(raw):
            continue
        if field_id == "aliases":
            values.extend(_parse_alias_field(raw))
        elif isinstance(raw, list):
            values.extend(_clean_scalar(item) for item in raw)
        else:
            values.append(_clean_scalar(raw))

    result: list[str] = []
    seen: set[str] = set()
    label_key = _normalize_search_text(display_label)
    for value in values:
        cleaned = " ".join(str(value or "").split())
        if not cleaned or len(cleaned) > 120:
            continue
        key = _normalize_search_text(cleaned)
        if not key or key == label_key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _parse_alias_field(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean_scalar(item) for item in value if _clean_scalar(item)]

    text = str(value or "").strip()
    if not text:
        return []

    parts: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            break
        if stripped.endswith(":") and len(stripped) <= 80:
            continue
        stripped = re.sub(r"^[\-\*\u2022]\s*", "", stripped)
        for part in re.split(r"\s*(?:,|;|\|)\s*", stripped):
            cleaned = part.strip()
            if cleaned:
                parts.append(cleaned)
    return parts


def _planner_sort_metadata(row: dict[str, Any]) -> dict[str, str]:
    """Preserve scalar Canon fields needed by genre/template planner policies.

    The Canon Index remains derived state. Storing scalar sort metadata keeps
    future genre sort policies data-driven without adding one SQL column or one
    Book Scope code branch for every genre-specific field.
    """

    metadata: dict[str, str] = {}
    for key, value in row.items():
        if key == INTERNAL_ID_FIELD or isinstance(value, (dict, list)) or value is None:
            continue
        cleaned = _clean_scalar(value)
        if cleaned:
            metadata[str(key)] = cleaned
    return metadata


def _decorate_index_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("planner_sort_metadata_json")
    metadata: dict[str, Any] = {}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                metadata = parsed
        except json.JSONDecodeError:
            metadata = {}
    row["planner_sort_metadata"] = metadata
    row.pop("planner_sort_metadata_json", None)
    return row


def _clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _stable_json_string(value)
    return " ".join(str(value).split())


def _normalize_search_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json_string(value).encode("utf-8")).hexdigest()


def _stable_json_string(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _dedupe_dict_rows(
    rows: list[dict[str, Any]],
    *,
    key: Any,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for row in rows:
        row_key = key(row)
        if row_key in seen:
            continue
        seen.add(row_key)
        result.append(row)
    return result


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def _relative(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def _execution_locks() -> dict[str, bool]:
    return {
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "planner_model_enabled": False,
        "story_eligibility_enabled": True,
    }
