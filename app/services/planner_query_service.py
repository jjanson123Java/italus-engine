from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Iterable
from uuid import uuid4

from app.projects import project_loader
from app.projects.project_context import build_project_context
from app.services import (
    book_scope_service,
    canon_index_service,
    chapter_plan_service,
    planner_intent_model_adapter,
    story_eligibility_service,
)

PLANNER_QUERY_SERVICE_MARKER = "planner-query-deterministic-v1-20260817"
PLANNER_QUERY_SCHEMA_VERSION = "planner_query_deterministic_v1"
PLANNER_INTENT_MODEL_MARKER = "planner-query-intent-model-v1-20260817"
PLANNER_INTENT_REQUEST_SCHEMA_VERSION = "planner_query_request_v1"
PLANNER_INTENT_SCHEMA_VERSION = "planner_query_intent_v1"
PLANNER_INTENT_SYSTEM_PROMPT_VERSION = "planner-intent-system-v1-20260817"
PLANNER_QUERY_DIAGNOSTIC_FILENAME = "planner_query_diagnostics.jsonl"

ACTION_FIND_MORE_CANON = "find_more_canon"
ACTION_RELATED_EVENTS = "related_events"
ACTION_POSSIBLE_NEXT_DIRECTIONS = "possible_next_directions"
ACTION_INTERPRET_INTENT = "interpret_intent"
PROHIBITED_MODEL_AUTHORITY_FIELDS = frozenset(
    {
        "eligible",
        "legal",
        "authorized",
        "override",
        "add_to_scope",
        "canon_compatible",
    }
)
SUPPORTED_ACTIONS = frozenset(
    {
        ACTION_FIND_MORE_CANON,
        ACTION_RELATED_EVENTS,
        ACTION_POSSIBLE_NEXT_DIRECTIONS,
    }
)
EVENT_RELATIONSHIP_TYPES = frozenset(chapter_plan_service.EVENT_RELATIONSHIP_TYPES)
VISIBLE_CURRENT_STATUSES = frozenset(
    {
        story_eligibility_service.STATUS_ACTIVE,
        story_eligibility_service.STATUS_AVAILABLE_TO_ADD,
    }
)


class PlannerQueryError(RuntimeError):
    """Base error for deterministic Planner Query operations."""


class PlannerQueryContractError(PlannerQueryError):
    """Raised when a Planner Query request violates the deterministic contract."""


def get_planner_query_contract() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": PLANNER_QUERY_SERVICE_MARKER,
        "schema_version": PLANNER_QUERY_SCHEMA_VERSION,
        "supported_actions": sorted(SUPPORTED_ACTIONS),
        "intent_action": ACTION_INTERPRET_INTENT,
        "event_relationship_types": sorted(EVENT_RELATIONSHIP_TYPES),
        "model_required": False,
        "intent_model": {
            "marker": PLANNER_INTENT_MODEL_MARKER,
            "request_schema_version": PLANNER_INTENT_REQUEST_SCHEMA_VERSION,
            "intent_schema_version": PLANNER_INTENT_SCHEMA_VERSION,
            "system_prompt_version": PLANNER_INTENT_SYSTEM_PROMPT_VERSION,
            "local_status": planner_intent_model_adapter.get_local_intent_model_status(),
            "cloud_fallback_implemented": False,
            "deterministic_actions_remain_available_without_model": True,
        },
        "authority": {
            "candidate_source": "canon_index",
            "availability_owner": "story_eligibility_service",
            "author_confirms_direction": True,
            "model_may_authorize_eligibility": False,
            "model_may_invent_canon": False,
            "may_mutate_book_scope": False,
            "may_mutate_chapter_plan": False,
            "may_mutate_master_canon": False,
            "may_write_approved_continuity": False,
        },
        "execution_locks": _execution_locks(),
    }


def execute_planner_query(
    project_id: str,
    *,
    action: str,
    book_number: int,
    chapter_number: int,
    query: str = "",
    record_types: Iterable[str] | None = None,
    include_future: bool = False,
    anchor_event_id: str = "",
    limit: int = 80,
    author_query: str = "",
    minimal_context: dict[str, Any] | None = None,
    allowed_search_domains: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Route deterministic Planner actions or one bounded intent-model request."""

    normalized_action = str(action or "").strip().lower()
    if normalized_action in SUPPORTED_ACTIONS:
        return execute_deterministic_planner_query(
            project_id,
            action=normalized_action,
            book_number=book_number,
            chapter_number=chapter_number,
            query=query,
            record_types=record_types,
            include_future=include_future,
            anchor_event_id=anchor_event_id,
            limit=limit,
        )
    if normalized_action != ACTION_INTERPRET_INTENT:
        raise PlannerQueryContractError(
            f"Unsupported Planner Query action: {normalized_action or '<blank>'}."
        )
    return _execute_intent_planner_query(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
        author_query=author_query or query,
        minimal_context=minimal_context or {},
        allowed_search_domains=allowed_search_domains or record_types or [],
        include_future=bool(include_future),
        limit=_bounded_limit(limit),
    )


def execute_deterministic_planner_query(
    project_id: str,
    *,
    action: str,
    book_number: int,
    chapter_number: int,
    query: str = "",
    record_types: Iterable[str] | None = None,
    include_future: bool = False,
    anchor_event_id: str = "",
    limit: int = 80,
) -> dict[str, Any]:
    """Execute one bounded Planner query without an LLM or project-state mutation."""

    normalized_action = str(action or "").strip().lower()
    if normalized_action not in SUPPORTED_ACTIONS:
        raise PlannerQueryContractError(
            f"Unsupported deterministic Planner Query action: {normalized_action or '<blank>'}."
        )

    manifest = project_loader.load_manifest(project_id).to_dict()
    book_number, chapter_number = _validate_position(
        manifest,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    safe_limit = _bounded_limit(limit)

    if normalized_action == ACTION_FIND_MORE_CANON:
        return _find_more_canon(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            query=query,
            record_types=record_types,
            include_future=bool(include_future),
            limit=safe_limit,
        )

    return _related_event_candidates(
        project_id,
        action=normalized_action,
        book_number=book_number,
        chapter_number=chapter_number,
        query=query,
        include_future=bool(include_future),
        anchor_event_id=anchor_event_id,
        limit=safe_limit,
    )



def _execute_intent_planner_query(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    author_query: str,
    minimal_context: dict[str, Any],
    allowed_search_domains: Iterable[str],
    include_future: bool,
    limit: int,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id).to_dict()
    book_number, chapter_number = _validate_position(
        manifest,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    query_text = str(author_query or "").strip()
    if not query_text:
        raise PlannerQueryContractError("author_query is required for interpret_intent.")

    query_id = f"pq_{uuid4().hex}"
    bounded_request = _build_intent_request(
        query_id=query_id,
        project_id=project_id,
        book_number=book_number,
        chapter_number=chapter_number,
        author_query=query_text,
        minimal_context=minimal_context,
        allowed_search_domains=allowed_search_domains,
    )
    input_hash = _stable_json_hash(bounded_request)
    model_status = planner_intent_model_adapter.get_local_intent_model_status()
    raw_output = ""
    repair_used = False
    provider = str(model_status.get("provider") or "ollama_local")
    model = str(model_status.get("model") or "")
    profile = str(model_status.get("profile") or "")

    try:
        first = planner_intent_model_adapter.generate_json(
            bounded_request=bounded_request,
            system_prompt=_intent_system_prompt(query_id),
        )
        raw_output = str(first.get("raw_output") or "")
        provider = str(first.get("provider") or provider)
        model = str(first.get("model") or model)
        profile = str(first.get("profile") or profile)
    except planner_intent_model_adapter.PlannerIntentModelUnavailable as exc:
        diagnostic = _intent_diagnostic(
            query_id=query_id,
            provider=provider,
            model=model,
            profile=profile,
            input_hash=input_hash,
            output_hash="",
            confidence=0.0,
            status="model_unavailable",
            repair_used=False,
            fallback_used=False,
        )
        _append_intent_diagnostic(project_id, diagnostic)
        return _intent_failure_response(
            project_id,
            query_id=query_id,
            book_number=book_number,
            chapter_number=chapter_number,
            author_query=query_text,
            status="model_unavailable",
            message=str(exc),
            diagnostic=diagnostic,
        )
    except planner_intent_model_adapter.PlannerIntentModelError as exc:
        diagnostic = _intent_diagnostic(
            query_id=query_id,
            provider=provider,
            model=model,
            profile=profile,
            input_hash=input_hash,
            output_hash="",
            confidence=0.0,
            status="model_error",
            repair_used=False,
            fallback_used=False,
        )
        _append_intent_diagnostic(project_id, diagnostic)
        return _intent_failure_response(
            project_id,
            query_id=query_id,
            book_number=book_number,
            chapter_number=chapter_number,
            author_query=query_text,
            status="model_error",
            message=str(exc),
            diagnostic=diagnostic,
        )

    parsed, validation_error = _parse_intent_output(raw_output, expected_query_id=query_id)
    if validation_error:
        repair_used = True
        try:
            repaired = planner_intent_model_adapter.repair_json(
                malformed_output=raw_output,
                output_schema=_intent_output_schema(query_id),
            )
            raw_output = str(repaired.get("raw_output") or "")
            provider = str(repaired.get("provider") or provider)
            model = str(repaired.get("model") or model)
            profile = str(repaired.get("profile") or profile)
            parsed, validation_error = _parse_intent_output(
                raw_output,
                expected_query_id=query_id,
            )
        except planner_intent_model_adapter.PlannerIntentModelError as exc:
            validation_error = f"Repair attempt failed: {exc}"

    output_hash = hashlib.sha256(raw_output.encode("utf-8")).hexdigest() if raw_output else ""
    if validation_error or parsed is None:
        diagnostic = _intent_diagnostic(
            query_id=query_id,
            provider=provider,
            model=model,
            profile=profile,
            input_hash=input_hash,
            output_hash=output_hash,
            confidence=0.0,
            status="invalid_model_output",
            repair_used=repair_used,
            fallback_used=False,
        )
        _append_intent_diagnostic(project_id, diagnostic)
        return _intent_failure_response(
            project_id,
            query_id=query_id,
            book_number=book_number,
            chapter_number=chapter_number,
            author_query=query_text,
            status="invalid_model_output",
            message=str(validation_error or "Planner Intent Model output is invalid."),
            diagnostic=diagnostic,
        )

    intent = dict(parsed["intent"])
    confidence = float(parsed["confidence"])
    ambiguities = list(parsed["ambiguities"])
    discarded_authority_fields = list(parsed["discarded_authority_fields"])

    if ambiguities:
        diagnostic = _intent_diagnostic(
            query_id=query_id,
            provider=provider,
            model=model,
            profile=profile,
            input_hash=input_hash,
            output_hash=output_hash,
            confidence=confidence,
            status="clarification_required",
            repair_used=repair_used,
            fallback_used=False,
        )
        _append_intent_diagnostic(project_id, diagnostic)
        return {
            "status": "clarification_required",
            "service": PLANNER_QUERY_SERVICE_MARKER,
            "intent_model": PLANNER_INTENT_MODEL_MARKER,
            "schema_version": PLANNER_INTENT_REQUEST_SCHEMA_VERSION,
            "intent_schema_version": PLANNER_INTENT_SCHEMA_VERSION,
            "routing": "model_intent",
            "model_used": True,
            "query_id": query_id,
            "project_id": project_id,
            "book_number": book_number,
            "chapter_number": chapter_number,
            "author_query": query_text,
            "intent": intent,
            "confidence": confidence,
            "ambiguities": ambiguities,
            "clarification_choices": ambiguities,
            "results": [],
            "result_count": 0,
            "discarded_model_authority_fields": discarded_authority_fields,
            "deterministic_actions_available": True,
            "author_confirmation_required": True,
            "diagnostic": diagnostic,
            "execution_locks": _execution_locks(),
        }

    retrieval = _retrieve_from_intent(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
        intent=intent,
        allowed_search_domains=bounded_request["allowed_search_domains"],
        include_future=include_future,
        limit=limit,
    )
    diagnostic = _intent_diagnostic(
        query_id=query_id,
        provider=provider,
        model=model,
        profile=profile,
        input_hash=input_hash,
        output_hash=output_hash,
        confidence=confidence,
        status="ok",
        repair_used=repair_used,
        fallback_used=False,
    )
    _append_intent_diagnostic(project_id, diagnostic)

    return {
        "status": "ok",
        "service": PLANNER_QUERY_SERVICE_MARKER,
        "intent_model": PLANNER_INTENT_MODEL_MARKER,
        "schema_version": PLANNER_INTENT_REQUEST_SCHEMA_VERSION,
        "intent_schema_version": PLANNER_INTENT_SCHEMA_VERSION,
        "routing": "model_intent_then_deterministic_retrieval",
        "model_used": True,
        "query_id": query_id,
        "project_id": project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "author_query": query_text,
        "intent": intent,
        "confidence": confidence,
        "ambiguities": [],
        "discarded_model_authority_fields": discarded_authority_fields,
        "result_count": len(retrieval["results"]),
        "results": retrieval["results"],
        "categories": retrieval["categories"],
        "status_counts": retrieval["status_counts"],
        "hidden_counts": retrieval["hidden_counts"],
        "source_index_hash": retrieval["source_index_hash"],
        "author_confirmation_required": True,
        "deterministic_actions_available": True,
        "diagnostic": diagnostic,
        "execution_locks": _execution_locks(),
    }


def _build_intent_request(
    *,
    query_id: str,
    project_id: str,
    book_number: int,
    chapter_number: int,
    author_query: str,
    minimal_context: dict[str, Any],
    allowed_search_domains: Iterable[str],
) -> dict[str, Any]:
    safe_context = _sanitize_minimal_context(minimal_context)
    domains = _normalize_record_types(allowed_search_domains)
    return {
        "schema_version": PLANNER_INTENT_REQUEST_SCHEMA_VERSION,
        "query_id": query_id,
        "project_id": project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "author_query": author_query,
        "minimal_context": safe_context,
        "allowed_search_domains": domains,
        "intent_schema_version": PLANNER_INTENT_SCHEMA_VERSION,
    }


def _sanitize_minimal_context(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlannerQueryContractError("minimal_context must be an object.")

    def _text(name: str) -> str:
        return str(value.get(name) or "").strip()[:2000]

    def _refs(name: str, *, limit: int = 20) -> list[dict[str, str]]:
        raw = value.get(name) or []
        if not isinstance(raw, list):
            return []
        refs: list[dict[str, str]] = []
        for item in raw[:limit]:
            if not isinstance(item, dict):
                continue
            record_id = str(item.get("record_id") or "").strip()
            label = str(item.get("label") or item.get("display_name") or "").strip()
            if record_id or label:
                refs.append({"record_id": record_id, "label": label[:300]})
        return refs

    opportunity = value.get("active_story_opportunity")
    safe_opportunity = None
    if isinstance(opportunity, dict):
        record_id = str(opportunity.get("record_id") or "").strip()
        label = str(opportunity.get("label") or opportunity.get("display_name") or "").strip()
        if record_id or label:
            safe_opportunity = {"record_id": record_id, "label": label[:300]}

    return {
        "chapter_goal": _text("chapter_goal"),
        "chapter_conflict": _text("chapter_conflict"),
        "current_pov": _refs("current_pov"),
        "active_locations": _refs("active_locations"),
        "active_story_opportunity": safe_opportunity,
        "story_phase": _text("story_phase"),
        "current_escalation_envelope": _text("current_escalation_envelope"),
    }


def _intent_system_prompt(query_id: str) -> str:
    return (
        "You are the bounded Italus Planner Query Intent Model. Interpret only the supplied "
        "author request and minimal context. Return JSON only. Do not invent Canon records, "
        "story facts, eligibility, legality, authorization, Book Canon membership, event truth, "
        "or chapter placement. Do not return eligible, legal, authorized, override, add_to_scope, "
        "or canon_compatible as authoritative fields. If meaning is materially ambiguous, return "
        "concise ambiguity questions/choices instead of guessing. The query_id must be "
        f"{query_id}. Output must match planner_query_intent_v1."
    )


def _intent_output_schema(query_id: str) -> dict[str, Any]:
    return {
        "schema_version": PLANNER_INTENT_SCHEMA_VERSION,
        "query_id": query_id,
        "intent": {
            "requested_record_types": ["string"],
            "desired_capabilities": ["string"],
            "desired_roles": ["string"],
            "undesired_roles": ["string"],
            "story_function": "string",
            "location_constraints": ["string"],
            "relationship_constraints": ["string"],
            "desired_escalation": "string",
            "include_out_of_scope": True,
            "include_locked": False,
        },
        "confidence": "number between 0 and 1",
        "ambiguities": [
            {
                "question": "string",
                "choices": ["string"],
            }
        ],
    }


def _parse_intent_output(
    raw_output: str,
    *,
    expected_query_id: str,
) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = json.loads(str(raw_output or ""))
    except json.JSONDecodeError as exc:
        return None, f"Planner Intent Model returned invalid JSON: {exc.msg}."

    if not isinstance(payload, dict):
        return None, "Planner Intent Model output must be one JSON object."
    if str(payload.get("schema_version") or "") != PLANNER_INTENT_SCHEMA_VERSION:
        return None, "Planner Intent Model returned the wrong schema_version."
    if str(payload.get("query_id") or "") != expected_query_id:
        return None, "Planner Intent Model returned the wrong query_id."

    raw_intent = payload.get("intent")
    if not isinstance(raw_intent, dict):
        return None, "Planner Intent Model intent must be an object."

    discarded = sorted(
        {
            key
            for key in set(payload) | set(raw_intent)
            if str(key).casefold() in PROHIBITED_MODEL_AUTHORITY_FIELDS
        }
    )

    list_fields = (
        "requested_record_types",
        "desired_capabilities",
        "desired_roles",
        "undesired_roles",
        "location_constraints",
        "relationship_constraints",
    )
    intent: dict[str, Any] = {}
    for field in list_fields:
        value = raw_intent.get(field, [])
        if not isinstance(value, list):
            return None, f"Planner Intent Model field {field} must be an array."
        intent[field] = _bounded_string_list(value, limit=20)

    intent["story_function"] = str(raw_intent.get("story_function") or "").strip()[:1000]
    intent["desired_escalation"] = str(raw_intent.get("desired_escalation") or "").strip()[:300]
    include_out_of_scope = raw_intent.get("include_out_of_scope", True)
    include_locked = raw_intent.get("include_locked", False)
    if not isinstance(include_out_of_scope, bool) or not isinstance(include_locked, bool):
        return None, "Planner Intent Model include flags must be booleans."
    intent["include_out_of_scope"] = include_out_of_scope
    intent["include_locked"] = include_locked

    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        return None, "Planner Intent Model confidence must be numeric."
    if confidence < 0.0 or confidence > 1.0:
        return None, "Planner Intent Model confidence must be between 0 and 1."

    raw_ambiguities = payload.get("ambiguities", [])
    if not isinstance(raw_ambiguities, list):
        return None, "Planner Intent Model ambiguities must be an array."
    ambiguities = _normalize_ambiguities(raw_ambiguities)

    return {
        "intent": intent,
        "confidence": confidence,
        "ambiguities": ambiguities,
        "discarded_authority_fields": discarded,
    }, ""


def _normalize_ambiguities(values: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in values[:10]:
        if isinstance(value, str):
            question = value.strip()
            if question:
                result.append({"question": question[:500], "choices": []})
            continue
        if not isinstance(value, dict):
            continue
        question = str(value.get("question") or value.get("message") or "").strip()
        choices = _bounded_string_list(value.get("choices") or [], limit=8)
        if question or choices:
            result.append({"question": question[:500], "choices": choices})
    return result


def _bounded_string_list(values: Iterable[Any], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values)[:limit]:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text[:500])
    return result


def _retrieve_from_intent(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    intent: dict[str, Any],
    allowed_search_domains: Iterable[str],
    include_future: bool,
    limit: int,
) -> dict[str, Any]:
    scope = book_scope_service.effective_book_scope_selections(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    selected_ids = {
        str(value or "").strip()
        for value in scope.get("selection_ids") or []
        if str(value or "").strip()
    }
    chapter = chapter_plan_service.get_chapter(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    ).get("chapter") or {}
    chapter_selected_ids = {
        str(item.get("record_id") or "").strip()
        for item in chapter.get("selected_canon_refs") or []
        if isinstance(item, dict) and str(item.get("record_id") or "").strip()
    }

    allowed = set(_normalize_record_types(allowed_search_domains))
    requested = set(_normalize_record_types(intent.get("requested_record_types") or []))
    if allowed and requested:
        record_types = sorted(allowed & requested)
    elif allowed:
        record_types = sorted(allowed)
    else:
        record_types = sorted(requested)

    term_specs = _intent_search_terms(intent)
    candidates: dict[str, dict[str, Any]] = {}
    for dimension, term in term_specs:
        for search_term in _expanded_search_terms(term):
            rows = canon_index_service.search_index(
                project_id,
                search_term,
                record_types=record_types or None,
                limit=200,
            ).get("results") or []
            for row in rows:
                record_id = str(row.get("internal_id") or "").strip()
                if not record_id:
                    continue
                item = candidates.setdefault(
                    record_id,
                    {"row": dict(row), "matches": defaultdict(list)},
                )
                bucket = item["matches"][dimension]
                if term not in bucket:
                    bucket.append(term)

    if not term_specs:
        rows = canon_index_service.list_records(
            project_id,
            record_types=record_types or None,
            limit=min(max(limit * 5, limit), 1000),
        ).get("results") or []
        for row in rows:
            record_id = str(row.get("internal_id") or "").strip()
            if record_id:
                candidates.setdefault(
                    record_id,
                    {"row": dict(row), "matches": defaultdict(list)},
                )

    results: list[dict[str, Any]] = []
    status_counts: dict[str, int] = defaultdict(int)
    hidden_counts: dict[str, int] = defaultdict(int)
    for record_id, candidate in candidates.items():
        row = candidate["row"]
        in_book_scope = record_id in selected_ids
        if not intent.get("include_out_of_scope", True) and not in_book_scope:
            continue

        decision = story_eligibility_service.evaluate_story_eligibility(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            candidate_ref={
                "record_id": record_id,
                "record_type": str(row.get("record_type") or ""),
                "label": str(row.get("display_label") or ""),
            },
            requested_use="chapter_selection",
            selected=in_book_scope,
        )
        status = str(decision.get("status") or "")
        status_counts[status] += 1
        if not (in_book_scope or include_future or status in VISIBLE_CURRENT_STATUSES):
            hidden_counts[status] += 1
            continue

        item = _result_item(
            row,
            status=status,
            eligibility=decision,
            in_book_scope=in_book_scope,
            selected_for_chapter=record_id in chapter_selected_ids,
        )
        matches = candidate["matches"]
        item["relevance"] = {
            "source": "canon_index",
            "deterministic": True,
            "intent_model_only_interpreted_query": True,
            "matched_capabilities": list(matches.get("capability", [])),
            "matched_roles": list(matches.get("role", [])),
            "matched_story_functions": list(matches.get("story_function", [])),
            "matched_locations": list(matches.get("location", [])),
            "matched_relationships": list(matches.get("relationship", [])),
            "matched_escalation": list(matches.get("escalation", [])),
        }
        item["_intent_match_count"] = sum(len(values) for values in matches.values())
        results.append(item)

    results.sort(
        key=lambda item: (
            -int(item.get("_intent_match_count") or 0),
            str(item.get("label") or "").casefold(),
            str(item.get("record_id") or ""),
        )
    )
    results = results[:limit]
    for item in results:
        item.pop("_intent_match_count", None)

    index_status = canon_index_service.get_index_status(project_id)
    return {
        "results": results,
        "categories": _group_categories(results),
        "status_counts": dict(sorted(status_counts.items())),
        "hidden_counts": dict(sorted(hidden_counts.items())),
        "source_index_hash": str(index_status.get("index_content_hash") or ""),
    }


def _intent_search_terms(intent: dict[str, Any]) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    for field, dimension in (
        ("desired_capabilities", "capability"),
        ("desired_roles", "role"),
        ("location_constraints", "location"),
        ("relationship_constraints", "relationship"),
    ):
        for value in intent.get(field) or []:
            text = str(value or "").strip()
            if text:
                specs.append((dimension, text))

    story_function = str(intent.get("story_function") or "").strip()
    if story_function:
        specs.append(("story_function", story_function))
    desired_escalation = str(intent.get("desired_escalation") or "").strip()
    if desired_escalation:
        specs.append(("escalation", desired_escalation))
    return specs


def _expanded_search_terms(value: str) -> list[str]:
    phrase = " ".join(str(value or "").split())
    if not phrase:
        return []
    terms = [phrase]
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", phrase):
        if len(token) < 4:
            continue
        if token.casefold() in {"with", "that", "from", "into", "current", "other"}:
            continue
        if token.casefold() not in {item.casefold() for item in terms}:
            terms.append(token)
    return terms[:8]


def _intent_diagnostic(
    *,
    query_id: str,
    provider: str,
    model: str,
    profile: str,
    input_hash: str,
    output_hash: str,
    confidence: float,
    status: str,
    repair_used: bool,
    fallback_used: bool,
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "provider": provider,
        "model": model,
        "profile": profile,
        "intent_schema_version": PLANNER_INTENT_SCHEMA_VERSION,
        "system_prompt_version": PLANNER_INTENT_SYSTEM_PROMPT_VERSION,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "confidence": confidence,
        "status": status,
        "repair_used": bool(repair_used),
        "fallback_used": bool(fallback_used),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _append_intent_diagnostic(project_id: str, diagnostic: dict[str, Any]) -> None:
    project_dir = project_loader.project_dir(project_id)
    path = project_dir / PLANNER_QUERY_DIAGNOSTIC_FILENAME
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(diagnostic, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _intent_failure_response(
    project_id: str,
    *,
    query_id: str,
    book_number: int,
    chapter_number: int,
    author_query: str,
    status: str,
    message: str,
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "service": PLANNER_QUERY_SERVICE_MARKER,
        "intent_model": PLANNER_INTENT_MODEL_MARKER,
        "schema_version": PLANNER_INTENT_REQUEST_SCHEMA_VERSION,
        "intent_schema_version": PLANNER_INTENT_SCHEMA_VERSION,
        "routing": "model_intent",
        "model_used": status not in {"model_unavailable"},
        "query_id": query_id,
        "project_id": project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "author_query": author_query,
        "message": message,
        "results": [],
        "result_count": 0,
        "deterministic_actions_available": True,
        "author_confirmation_required": True,
        "fallback_used": False,
        "diagnostic": diagnostic,
        "execution_locks": _execution_locks(),
    }


def _stable_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _find_more_canon(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
    query: str,
    record_types: Iterable[str] | None,
    include_future: bool,
    limit: int,
) -> dict[str, Any]:
    scope = book_scope_service.effective_book_scope_selections(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    selected_ids = {
        str(value or "").strip()
        for value in scope.get("selection_ids") or []
        if str(value or "").strip()
    }
    chapter = chapter_plan_service.get_chapter(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    ).get("chapter") or {}
    chapter_selected_ids = {
        str(item.get("record_id") or "").strip()
        for item in chapter.get("selected_canon_refs") or []
        if isinstance(item, dict) and str(item.get("record_id") or "").strip()
    }

    manifest_obj = project_loader.load_manifest(project_id)
    context = build_project_context(manifest_obj)
    index_status = canon_index_service.ensure_current_index(project_id)
    all_rows = canon_index_service.list_records_current(project_id, limit=10000).get("results") or []
    eligibility_context = story_eligibility_service.prepare_story_eligibility_context(
        context, index_status=index_status, indexed_records=list(all_rows)
    )

    types = _normalize_record_types(record_types)
    needle = str(query or "").strip()
    if needle:
        rows = canon_index_service.search_index(
            project_id,
            needle,
            record_types=types or None,
            limit=min(max(limit * 3, limit), 200),
        ).get("results") or []
    else:
        rows = [
            row for row in all_rows
            if not types or str(row.get("record_type") or "") in set(types)
        ]

    results: list[dict[str, Any]] = []
    status_counts: dict[str, int] = defaultdict(int)
    hidden_counts: dict[str, int] = defaultdict(int)
    for row in rows:
        record_id = str(row.get("internal_id") or "").strip()
        if not record_id:
            continue
        in_book_scope = record_id in selected_ids
        decision = story_eligibility_service.evaluate_story_eligibility_for_context(
            context,
            book_number=book_number,
            chapter_number=chapter_number,
            candidate_ref={
                "record_id": record_id,
                "record_type": str(row.get("record_type") or ""),
                "label": str(row.get("display_label") or ""),
            },
            requested_use="chapter_selection",
            selected=in_book_scope,
            prepared_context=eligibility_context,
            indexed_record=(eligibility_context.get("records_by_id") or {}).get(record_id) or row,
        )
        status = str(decision.get("status") or "")
        status_counts[status] += 1
        if not (in_book_scope or include_future or status in VISIBLE_CURRENT_STATUSES):
            hidden_counts[status] += 1
            continue

        item = _result_item(
            row,
            status=status,
            eligibility=decision,
            in_book_scope=in_book_scope,
            selected_for_chapter=record_id in chapter_selected_ids,
        )
        results.append(item)
        if len(results) >= limit:
            break

    categories = _group_categories(results)
    return _base_response(
        project_id,
        action=ACTION_FIND_MORE_CANON,
        book_number=book_number,
        chapter_number=chapter_number,
        query=needle,
        include_future=include_future,
        results=results,
        extra={
            "record_types": types,
            "status_counts": dict(sorted(status_counts.items())),
            "hidden_counts": dict(sorted(hidden_counts.items())),
            "categories": categories,
            "scope_revision": int(scope.get("effective_revision") or 0),
            "scope_content_hash": str(scope.get("effective_content_hash") or ""),
        },
    )


def _related_event_candidates(
    project_id: str,
    *,
    action: str,
    book_number: int,
    chapter_number: int,
    query: str,
    include_future: bool,
    anchor_event_id: str,
    limit: int,
) -> dict[str, Any]:
    scope = book_scope_service.effective_book_scope_selections(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    selected_ids = {
        str(value or "").strip()
        for value in scope.get("selection_ids") or []
        if str(value or "").strip()
    }
    chapter_result = chapter_plan_service.get_chapter(
        project_id,
        book_number=book_number,
        chapter_number=chapter_number,
    )
    chapter = chapter_result.get("chapter") or {}
    assigned_ids = {
        str(item.get("record_id") or "").strip()
        for item in chapter.get("assigned_event_refs") or []
        if isinstance(item, dict) and str(item.get("record_id") or "").strip()
    }

    anchors = _resolve_anchor_ids(
        project_id,
        explicit_anchor_id=anchor_event_id,
        assigned_event_ids=assigned_ids,
        require_explicit=(action == ACTION_RELATED_EVENTS),
    )
    if not anchors:
        return _base_response(
            project_id,
            action=action,
            book_number=book_number,
            chapter_number=chapter_number,
            query=str(query or "").strip(),
            include_future=include_future,
            results=[],
            extra={
                "anchor_events": [],
                "message": "Assign or select an anchor event to retrieve canon-supported directions.",
                "scope_revision": int(scope.get("effective_revision") or 0),
                "scope_content_hash": str(scope.get("effective_content_hash") or ""),
            },
        )

    candidates: dict[str, dict[str, Any]] = {}
    for anchor_id in anchors:
        anchor_lookup = canon_index_service.get_record_by_id(project_id, anchor_id)
        anchor_record = dict(anchor_lookup.get("record") or {})
        anchor_label = str(anchor_record.get("display_label") or anchor_id)

        relationship_result = canon_index_service.relationships_for_record(
            project_id,
            anchor_id,
            direction="both",
            relationship_types=EVENT_RELATIONSHIP_TYPES,
        )
        for edge in relationship_result.get("relationships") or []:
            related_id = (
                str(edge.get("target_internal_id") or "").strip()
                if str(edge.get("direction") or "") == "outgoing"
                else str(edge.get("source_internal_id") or "").strip()
            )
            if not related_id or related_id == anchor_id:
                continue

            lookup = canon_index_service.get_record_by_id(project_id, related_id)
            if lookup.get("status") != "found":
                continue
            row = dict(lookup["record"])
            if str(row.get("record_group_id") or "") != "events":
                continue

            candidate = candidates.setdefault(
                related_id,
                {
                    "record": row,
                    "relationships_to_anchor": [],
                },
            )
            relationship = {
                "anchor_record_id": anchor_id,
                "anchor_label": anchor_label,
                "relationship_type": str(edge.get("relationship_type") or ""),
                "direction": str(edge.get("direction") or ""),
            }
            if relationship not in candidate["relationships_to_anchor"]:
                candidate["relationships_to_anchor"].append(relationship)

    needle = _normalize_search_text(query)
    results: list[dict[str, Any]] = []
    for record_id in sorted(
        candidates,
        key=lambda value: (
            str(candidates[value]["record"].get("display_label") or "").casefold(),
            value,
        ),
    ):
        candidate = candidates[record_id]
        row = candidate["record"]
        if needle and needle not in _normalize_search_text(
            " ".join(
                [
                    str(row.get("display_label") or ""),
                    str(row.get("summary") or ""),
                    str(row.get("story_code") or ""),
                    str(row.get("narrative_type") or ""),
                ]
            )
        ):
            continue

        in_book_scope = record_id in selected_ids
        decision = story_eligibility_service.evaluate_story_eligibility(
            project_id,
            book_number=book_number,
            chapter_number=chapter_number,
            candidate_ref={
                "record_id": record_id,
                "record_type": str(row.get("record_type") or ""),
                "label": str(row.get("display_label") or ""),
            },
            requested_use="event_placement",
            selected=in_book_scope,
        )
        status = str(decision.get("status") or "")
        if not (in_book_scope or include_future or status in VISIBLE_CURRENT_STATUSES):
            continue

        item = _result_item(
            row,
            status=status,
            eligibility=decision,
            in_book_scope=in_book_scope,
            selected_for_chapter=record_id in assigned_ids,
        )
        item["relationships_to_anchor"] = sorted(
            candidate["relationships_to_anchor"],
            key=lambda rel: (
                str(rel.get("anchor_label") or "").casefold(),
                str(rel.get("relationship_type") or ""),
                str(rel.get("direction") or ""),
            ),
        )
        results.append(item)
        if len(results) >= limit:
            break

    anchor_payloads = []
    for anchor_id in anchors:
        lookup = canon_index_service.get_record_by_id(project_id, anchor_id)
        row = dict(lookup.get("record") or {})
        anchor_payloads.append(
            {
                "record_id": anchor_id,
                "label": str(row.get("display_label") or anchor_id),
                "story_code": str(row.get("story_code") or ""),
            }
        )

    return _base_response(
        project_id,
        action=action,
        book_number=book_number,
        chapter_number=chapter_number,
        query=str(query or "").strip(),
        include_future=include_future,
        results=results,
        extra={
            "anchor_events": anchor_payloads,
            "scope_revision": int(scope.get("effective_revision") or 0),
            "scope_content_hash": str(scope.get("effective_content_hash") or ""),
        },
    )


def _resolve_anchor_ids(
    project_id: str,
    *,
    explicit_anchor_id: str,
    assigned_event_ids: set[str],
    require_explicit: bool,
) -> list[str]:
    explicit = str(explicit_anchor_id or "").strip()
    if explicit:
        lookup = canon_index_service.get_record_by_id(project_id, explicit)
        if lookup.get("status") != "found":
            raise PlannerQueryContractError(
                "anchor_event_id does not resolve in the current Canon Index."
            )
        record = dict(lookup["record"])
        if str(record.get("record_group_id") or "") != "events":
            raise PlannerQueryContractError("anchor_event_id must reference an event.")
        return [explicit]
    if require_explicit:
        raise PlannerQueryContractError("related_events requires anchor_event_id.")
    return sorted(assigned_event_ids)


def _result_item(
    row: dict[str, Any],
    *,
    status: str,
    eligibility: dict[str, Any],
    in_book_scope: bool,
    selected_for_chapter: bool,
) -> dict[str, Any]:
    record_id = str(row.get("internal_id") or "")
    record_type = str(row.get("record_type") or "")
    group = str(row.get("record_group_id") or "")
    label = str(row.get("display_label") or "")
    actions: list[str] = []
    available = bool(eligibility.get("available"))
    if in_book_scope and available:
        actions.append("add_to_chapter")
        if group == "events":
            actions.append("place_event")
    elif available:
        actions.append("add_to_book")
    else:
        actions.extend(str(value) for value in eligibility.get("allowed_actions") or [])

    return {
        "record_id": record_id,
        "record_type": record_type,
        "record_group_id": group,
        "display_name": label,
        "label": label,
        "story_code": str(row.get("story_code") or ""),
        "narrative_type": str(row.get("narrative_type") or ""),
        "summary": str(row.get("summary") or ""),
        "status": status,
        "selected": in_book_scope,
        "in_book_scope": in_book_scope,
        "selected_for_chapter": selected_for_chapter,
        "eligibility": eligibility,
        "allowed_actions": list(dict.fromkeys(actions)),
        "relevance": {
            "source": "canon_index",
            "deterministic": True,
        },
    }


def _group_categories(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        key = str(item.get("record_group_id") or item.get("record_type") or "other")
        grouped[key].append(item)
    categories = []
    for key in sorted(grouped):
        items = sorted(
            grouped[key],
            key=lambda item: (
                str(item.get("label") or "").casefold(),
                str(item.get("record_id") or ""),
            ),
        )
        categories.append(
            {
                "category_key": key,
                "items": items,
                "total": len(items),
                "selected_count": sum(1 for item in items if item.get("selected") is True),
            }
        )
    return categories


def _base_response(
    project_id: str,
    *,
    action: str,
    book_number: int,
    chapter_number: int,
    query: str,
    include_future: bool,
    results: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index_status = canon_index_service.get_index_status(project_id)
    return {
        "status": "ok",
        "service": PLANNER_QUERY_SERVICE_MARKER,
        "schema_version": PLANNER_QUERY_SCHEMA_VERSION,
        "routing": "deterministic",
        "model_used": False,
        "project_id": project_id,
        "action": action,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "query": query,
        "include_future": include_future,
        "result_count": len(results),
        "results": results,
        "source_index_hash": str(index_status.get("index_content_hash") or ""),
        "author_confirmation_required": True,
        "execution_locks": _execution_locks(),
        **(extra or {}),
    }


def _validate_position(
    manifest: dict[str, Any],
    *,
    book_number: int,
    chapter_number: int,
) -> tuple[int, int]:
    try:
        book = int(book_number)
        chapter = int(chapter_number)
    except (TypeError, ValueError) as exc:
        raise PlannerQueryContractError(
            "book_number and chapter_number must be integers."
        ) from exc

    book_count = max(1, int(manifest.get("book_count") or 1))
    chapters_per_book = max(1, int(manifest.get("chapters_per_book") or 1))
    if book < 1 or book > book_count:
        raise PlannerQueryContractError(
            f"book_number must be between 1 and {book_count}."
        )
    if chapter < 1 or chapter > chapters_per_book:
        raise PlannerQueryContractError(
            f"chapter_number must be between 1 and {chapters_per_book}."
        )
    return book, chapter


def _normalize_record_types(values: Iterable[str] | None) -> list[str]:
    return sorted(
        {
            str(value or "").strip()
            for value in values or []
            if str(value or "").strip()
        }
    )


def _bounded_limit(value: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PlannerQueryContractError("limit must be an integer.") from exc
    return max(1, min(result, 200))


def _normalize_search_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _execution_locks() -> dict[str, Any]:
    return {
        "planner_model_execution": False,
        "planner_model_scope": "intent_interpretation_only",
        "generation": True,
        "prompt_builder": True,
        "provider_execution": True,
        "runtime_writes": True,
        "approved_continuity_writes": True,
        "master_canon_mutation": True,
        "book_scope_mutation": True,
        "chapter_plan_mutation": True,
    }
