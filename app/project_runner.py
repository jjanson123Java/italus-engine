from app.registry import (
    load_scenes,
    load_event_index,
    load_chapters,
    save_chapters,
    add_scene,
    load_session_state,
    save_session_state,
    load_app_settings,
    create_data_backup,
    load_book_state_for,
    load_chapter_digest,
    update_book_state,
    update_chapter_digest,
)
from app.post_generation_canon_validator import find_exact_duplicate, find_event_scenes
from app.coverage import build_coverage
from app.prompt_builder import build_generation_prompt
from app.ai_runner import generate_with_ai
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def get_default_ai_provider() -> str:
    """
    Resolve the default AI provider from app settings.
    """
    app_settings = load_app_settings()
    return str(app_settings.get("ai_provider", "claude")).strip().lower()
    
def get_ai_provider_config() -> dict:
    """
    Return frontend-safe AI provider configuration.
    """
    from app.ai_runner import get_available_ai_providers

    default_provider = get_default_ai_provider()
    providers = get_available_ai_providers()

    return {
        "default_provider": default_provider,
        "providers": providers,
    }


def normalize(value: str) -> str:
    return value.strip().lower()


def resolve_event_context(request: dict) -> dict:
    """
    Resolve event_name or event_id to canonical event data using event_index.json.
    Priority:
    1. explicit event_id
    2. exact event_name match
    3. fallback to existing request values
    """
    events = load_event_index()

    if request.get("event_id"):
        for event in events:
            if event.get("event_id") == request["event_id"]:
                request["event_name"] = event["event_name"]
                request["book_id"] = event["book_id"]
                if not request.get("year"):
                    request["year"] = event["year_start"]
                if not request.get("guardian") and event.get("active_guardians"):
                    request["guardian"] = event["active_guardians"][0]
                return request

    if request.get("event_name"):
        target = normalize(request["event_name"])
        for event in events:
            if normalize(event.get("event_name", "")) == target:
                request["event_id"] = event["event_id"]
                request["book_id"] = event["book_id"]
                if not request.get("year"):
                    request["year"] = event["year_start"]
                if not request.get("guardian") and event.get("active_guardians"):
                    request["guardian"] = event["active_guardians"][0]
                return request

    return request


def filter_candidate_scenes(request: dict, scenes: list) -> list:
    """
    Scope scenes so duplicate checks never compare across unrelated books/events.
    """
    candidates = scenes

    if request.get("book_id"):
        candidates = [s for s in candidates if s.get("book_id") == request["book_id"]]

    if request.get("event_id"):
        event_matches = [s for s in candidates if s.get("event_id") == request["event_id"]]
        if event_matches:
            candidates = event_matches

    if request.get("chapter_id"):
        chapter_matches = [s for s in candidates if s.get("chapter_id") == request["chapter_id"]]
        if chapter_matches:
            candidates = chapter_matches

    return candidates


def autofill_continuation_links(request: dict, scenes: list) -> dict:
    """
    If this is a continuation scene and linkage fields are missing,
    infer the most recent prior canon scene in the same book/event context.
    """
    if request.get("scene_type") != "continuation":
        return request

    # If caller already provided linkage, keep it
    if request.get("continued_from_scene_id") or request.get("parent_scene_id"):
        return request

    candidates = scenes

    if request.get("book_id"):
        candidates = [s for s in candidates if s.get("book_id") == request["book_id"]]

    if request.get("event_id"):
        candidates = [s for s in candidates if s.get("event_id") == request["event_id"]]

    candidates = [s for s in candidates if s.get("status") == "canon"]

    if not candidates:
        return request

    # Sort deterministically and use the latest scene
    candidates = sorted(candidates, key=lambda s: s.get("scene_id", ""))

    prior_scene = candidates[-1]
    request["continued_from_scene_id"] = prior_scene["scene_id"]
    request["parent_scene_id"] = prior_scene["scene_id"]

    return request


def generate_next_scene_id(chapter_id: str, scenes: list) -> str:
    """
    Generate the next scene ID for a given chapter.
    Example:
    BOOK_07_CH_06 -> BOOK_07_CH_06_SC_03
    """
    chapter_scenes = [s for s in scenes if s.get("chapter_id") == chapter_id]
    next_number = len(chapter_scenes) + 1
    return f"{chapter_id}_SC_{next_number:02d}"


def build_scene_record(request: dict, title: str, summary: str = "", status: str = "canon") -> dict:
    """
    Build a new scene record from the resolved request.
    """
    all_scenes = load_scenes()
    scene_id = generate_next_scene_id(request["chapter_id"], all_scenes)

    return {
        "scene_id": scene_id,
        "book_id": request.get("book_id", ""),
        "chapter_id": request.get("chapter_id", ""),
        "title": title,
        "event_id": request.get("event_id", ""),
        "event_name": request.get("event_name", ""),
        "year": request.get("year", 0),
        "guardian": request.get("guardian", ""),
        "location": request.get("location", ""),
        "scene_type": request.get("scene_type", ""),
        "time_window": request.get("time_window", ""),
        "tone": request.get("tone", ""),
        "pov": request.get("pov", ""),
        "characters_present": request.get("characters_present", []),
        "status": status,
        "parent_scene_id": request.get("parent_scene_id"),
        "continued_from_scene_id": request.get("continued_from_scene_id"),
        "callback_scene_ids": request.get("callback_scene_ids", []),
        "summary": summary,
        "tags": request.get("tags", [])
}


def validate_continuation_parent(request: dict):
    """
    Validate structural continuation separately from literary callbacks.
    """

    all_scenes = load_scenes()
    scene_map = {s.get("scene_id"): s for s in all_scenes}

    callback_ids = request.get("callback_scene_ids", []) or []

    # --- Validate callback references for any scene type ---
    if not isinstance(callback_ids, list):
        raise ValueError("callback_scene_ids must be a list")

    if len(callback_ids) != len(set(callback_ids)):
        raise ValueError("callback_scene_ids contains duplicates")

    for callback_id in callback_ids:
        if callback_id not in scene_map:
            raise ValueError(f"Callback scene not found in registry: {callback_id}")

    # --- Only continuation scenes require structural parent validation ---
    if request.get("scene_type") != "continuation":
        return

    continued_from = request.get("continued_from_scene_id")
    if not continued_from:
        raise ValueError("Continuation scenes must include continued_from_scene_id")

    if continued_from not in scene_map:
        raise ValueError(
            f"Continuation parent scene not found in registry: {continued_from}"
        )

    parent_scene = scene_map[continued_from]

    if request.get("book_id") and parent_scene.get("book_id") != request.get("book_id"):
        raise ValueError("Continuation parent must be in the same book")

    if request.get("event_id") and parent_scene.get("event_id") != request.get("event_id"):
        raise ValueError("Continuation parent must be in the same event")

    # latest canon scene in same scope = valid structural parent
    candidates = [
        s for s in all_scenes
        if s.get("status") == "canon"
        and s.get("book_id") == request.get("book_id")
        and s.get("event_id") == request.get("event_id")
    ]

    if candidates:
        candidates = sorted(candidates, key=lambda s: s.get("scene_id", ""))
        expected_parent = candidates[-1]["scene_id"]

        if continued_from != expected_parent:
            raise ValueError(
                f"Continuation must point to latest canon scene in scope: {expected_parent}"
            )

    if continued_from in callback_ids:
        raise ValueError(
            "Do not include continued_from_scene_id inside callback_scene_ids"
        )


def ensure_chapter_exists(request: dict):
    """
    If the chapter_id in the request does not exist yet, create a minimal chapter entry.
    """
    if not request.get("chapter_id"):
        return

    chapters = load_chapters()
    exists = any(ch.get("chapter_id") == request["chapter_id"] for ch in chapters)
    if exists:
        return

    chapter_number = 1
    try:
        if "_CH_" in request["chapter_id"]:
            chapter_number = int(request["chapter_id"].split("_CH_")[1])
    except Exception:
        chapter_number = 1

    chapter_record = {
        "chapter_id": request["chapter_id"],
        "book_id": request.get("book_id", ""),
        "chapter_number": chapter_number,
        "title": request.get("chapter_title", f"Chapter {chapter_number}"),
        "event_id": request.get("event_id", ""),
        "event_name": request.get("event_name", ""),
        "year": request.get("year", 0),
        "guardian": request.get("guardian", ""),
        "pacing_role": request.get("pacing_role", "Unassigned"),
        "status": "active"
    }

    chapters.append(chapter_record)
    save_chapters(chapters)


def save_accepted_scene(request: dict, title: str, summary: str = "", status: str = "canon") -> dict:
    """
    Save an accepted scene to scenes.json and rebuild coverage_map.json.
    """
    validate_continuation_parent(request)
    
    backup_label = (
        f'{request.get("book_id", "UNKNOWN_BOOK")}_'
        f'{request.get("chapter_id", "UNKNOWN_CHAPTER")}_'
        f'{request.get("event_id", "UNKNOWN_EVENT")}_'
        f'before_scene_save'
    )
    

    backup_path = create_data_backup(label=backup_label)

    if request.get("scene_type") == "continuation":
        if request.get("continued_from_scene_id") and not request.get("parent_scene_id"):
            request["parent_scene_id"] = request["continued_from_scene_id"]

    ensure_chapter_exists(request)
    
    effective_summary = summary.strip() if isinstance(summary, str) else ""

    if not effective_summary:
        effective_summary = (
            f'{request.get("scene_type", "scene").title()} scene in '
            f'{request.get("location", "unknown location")} focused on '
            f'{request.get("guardian", "unknown guardian")} during '
            f'{request.get("event_name", "unknown event")} '
            f'with tone {request.get("tone", "unspecified")}.'
        )

    scene_record = build_scene_record(
        request=request,
        title=title,
        summary=effective_summary,
        status=status
    )
    
    add_scene(scene_record)
    build_coverage()

    update_chapter_digest(
        request.get("chapter_id"),
        {
            "last_scene_id": scene_record["scene_id"],
            "last_scene_title": title,
            "last_scene_summary": effective_summary,
            "event_id": request.get("event_id"),
            "event_name": request.get("event_name"),
            "guardian": request.get("guardian"),
            "location": request.get("location"),
            "scene_type": request.get("scene_type"),
            "tone": request.get("tone"),
            "pov": request.get("pov"),
            "time_window": request.get("time_window"),
            "characters_present": request.get("characters_present", []),
            "chapter_progress_note": (
                f"{request.get('scene_type', 'scene')} scene at "
                f"{request.get('location', 'unknown location')} involving "
                f"{request.get('guardian', 'unknown guardian')}."
            ),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    )

    update_book_state(
        request.get("book_id"),
        {
            "last_scene_id": scene_record["scene_id"],
            "last_chapter_id": request.get("chapter_id"),
            "last_event_id": request.get("event_id"),
            "last_event": request.get("event_name"),
            "last_guardian": request.get("guardian"),
            "last_location": request.get("location"),
            "last_scene_type": request.get("scene_type"),
            "last_tone": request.get("tone"),
            "last_pov": request.get("pov"),
            "last_update": datetime.now(timezone.utc).isoformat()
        }
    )
    
    session_state = load_session_state()
    session_state["last_scene_id"] = scene_record["scene_id"]
    session_state["last_action"] = "save_scene"
    save_session_state(session_state)
    scene_record["backup_path"] = backup_path
    
    return scene_record


def get_resume_status(session_state: dict, request: dict) -> dict:
    """
    Determine whether the author is continuing, resuming, or starting a new book/chapter.
    """
    now = datetime.now(timezone.utc)

    last_ts = session_state.get("last_request_timestamp")
    last_book_id = session_state.get("last_book_id")
    last_chapter_id = session_state.get("last_chapter_id")

    current_book_id = request.get("book_id")
    current_chapter_id = request.get("chapter_id")

    if not last_ts:
        return {
            "status": "first_use",
            "hours_since_last": None
        }

    last_dt = datetime.fromisoformat(last_ts)
    hours_since_last = (now - last_dt).total_seconds() / 3600.0

    if current_book_id != last_book_id:
        return {
            "status": "new_book",
            "hours_since_last": hours_since_last
        }

    if current_chapter_id != last_chapter_id:
        return {
            "status": "new_chapter",
            "hours_since_last": hours_since_last
        }

    if hours_since_last > 48:
        return {
            "status": "long_pause_resume",
            "hours_since_last": hours_since_last
        }

    if hours_since_last > 2:
        return {
            "status": "resume",
            "hours_since_last": hours_since_last
        }

    return {
        "status": "same_session",
        "hours_since_last": hours_since_last
    }


def format_author_time(iso_timestamp: str | None, timezone_name: str) -> str:
    """
    Convert stored ISO timestamp into the author's configured local time string.
    """
    if not iso_timestamp:
        return "unknown"

    try:
        dt = datetime.fromisoformat(iso_timestamp)
        local_dt = dt.astimezone(ZoneInfo(timezone_name))
        return local_dt.strftime("%Y-%m-%d %I:%M %p %Z")
    except Exception:
        return iso_timestamp


def build_author_context_message(
    resume_info: dict,
    session_state: dict,
    request: dict,
    timezone_name: str
) -> str | None:
    """
    Build informational or warning guidance for the author before generation.
    """
    status = resume_info["status"]

    last_timestamp = format_author_time(
        session_state.get("last_request_timestamp"),
        timezone_name
    )
    hours_since_last = resume_info.get("hours_since_last")
    elapsed_text = (
        f"{hours_since_last:.1f} hours"
        if isinstance(hours_since_last, (int, float))
        else "unknown"
    )

    if status == "first_use":
        return (
            "FIRST WRITING SESSION DETECTED\n\n"
            "The application is applying startup mode.\n\n"
            "Context being loaded:\n"
            "- CORE pack\n"
            "- GENERATION pack\n"
            "- BOOK pack if available\n\n"
            "No prior continuity state exists yet."
        )

    if status == "new_book":
        return (
            f"NEW BOOK START DETECTED\n\n"
            f"You are starting {request.get('book_id')}.\n\n"
            f"The application is applying book-start mode.\n\n"
            f"Context being loaded:\n"
            f"- CORE pack\n"
            f"- GENERATION pack\n"
            f"- BOOK pack\n\n"
            f"No chapter continuity is being loaded yet.\n\n"
            f"Recommended next step:\n"
            f"- Generate prologue or introduction first"
        )

    if status == "new_chapter":
        return (
            f"NEW CHAPTER DETECTED\n\n"
            f"You are moving to {request.get('chapter_id')}.\n\n"
            f"The application is applying chapter-start mode.\n\n"
            f"Context being loaded:\n"
            f"- BOOK pack\n"
            f"- chapter continuity digest if available\n"
            f"- canon re-anchor if needed\n\n"
            f"If no digest exists yet, the first accepted scene will initialize chapter continuity."
        )

    if status == "resume":
        return (
            f"RESUME DETECTED\n\n"
            f"Last work:\n"
            f"- Time: {last_timestamp}\n"
            f"- Book: {session_state.get('last_book_id')}\n"
            f"- Chapter: {session_state.get('last_chapter_id')}\n"
            f"- Latest scene: {session_state.get('last_scene_id')}\n"
            f"- Elapsed: {elapsed_text}\n\n"
            f"The application is applying resume mode.\n\n"
            f"Context being loaded:\n"
            f"- CORE pack\n"
            f"- GENERATION pack\n"
            f"- BOOK pack\n"
            f"- chapter continuity digest if available"
        )

    if status == "long_pause_resume":
        return (
            f"LONG-PAUSE RESUME DETECTED\n\n"
            f"Last work:\n"
            f"- Time: {last_timestamp}\n"
            f"- Book: {session_state.get('last_book_id')}\n"
            f"- Chapter: {session_state.get('last_chapter_id')}\n"
            f"- Latest scene: {session_state.get('last_scene_id')}\n"
            f"- Elapsed: {elapsed_text}\n\n"
            f"The application is applying full re-anchor mode.\n\n"
            f"Context being loaded:\n"
            f"- CORE pack\n"
            f"- GENERATION pack\n"
            f"- BOOK pack\n"
            f"- chapter continuity digest if available\n"
            f"- book state if available\n\n"
            f"This is intended to reduce continuity drift after a long pause."
        )

    if status == "same_session":
        return (
            f"CONTINUATION DETECTED\n\n"
            f"The application is applying continuation mode.\n\n"
            f"Context being loaded:\n"
            f"- BOOK pack\n"
            f"- current chapter continuity when available\n"
            f"- parent/callback context if relevant"
        )

    return None
    
def determine_prompt_mode(resume_status: str) -> dict:
    """
    Determine how much context to load based on author/session behavior.
    """
    if resume_status == "first_use":
        return {
            "mode_name": "startup",
            "include_core": True,
            "include_generation": True,
            "include_book_pack": True
        }

    if resume_status == "new_book":
        return {
            "mode_name": "book_start",
            "include_core": True,
            "include_generation": True,
            "include_book_pack": True
        }

    if resume_status == "new_chapter":
        return {
            "mode_name": "chapter_start",
            "include_core": True,
            "include_generation": True,
            "include_book_pack": True
        }

    if resume_status == "long_pause_resume":
        return {
            "mode_name": "full_reanchor",
            "include_core": True,
            "include_generation": True,
            "include_book_pack": True
        }

    if resume_status == "resume":
        return {
            "mode_name": "resume",
            "include_core": True,
            "include_generation": True,
            "include_book_pack": True
        }

    return {
        "mode_name": "continuation",
        "include_core": True,
        "include_generation": True,
        "include_book_pack": True
    }

def process_request(request: dict):
    """
    Main orchestration flow:
    1. resolve canonical event/book context
    2. load existing scenes
    3. auto-link continuation scenes if needed
    4. scope candidate scenes
    5. run duplicate precheck on scoped candidates only
    6. build prompt for the selected AI provider
    7. call the AI runner for generation
    8. return generation response

    Note:
    Chapters are NOT created during this phase.
    Chapter creation occurs during save_accepted_scene() when a scene
    is actually accepted and committed to canon.
    """
    request = resolve_event_context(request)
    app_settings = load_app_settings()
    timezone_name = app_settings.get("timezone", "America/New_York")

    request_provider = request.get("ai_provider")
    settings_provider = app_settings.get("ai_provider", "claude")

    ai_provider = str(request_provider if request_provider else settings_provider).strip().lower()
    
    request["ai_provider"] = ai_provider

    session_state = load_session_state()
    book_state = load_book_state_for(request.get("book_id"))
    chapter_digest = load_chapter_digest(request.get("chapter_id"))
    resume_info = get_resume_status(session_state, request)
    prompt_mode = determine_prompt_mode(resume_info["status"])
    author_message = build_author_context_message(
        resume_info,
        session_state,
        request,
        timezone_name
    )

    all_scenes = load_scenes()

    request = autofill_continuation_links(request, all_scenes)

    candidate_scenes = filter_candidate_scenes(request, all_scenes)
    duplicate = find_exact_duplicate(request, candidate_scenes)
    event_scenes = find_event_scenes(
        request.get("event_name", ""),
        candidate_scenes,
        request.get("event_id")
    )
    
    
    coverage = build_coverage()
    prompt = build_generation_prompt(
        request,
        event_scenes,
        coverage,
        book_state,
        chapter_digest
    )
    

    try:
        response = generate_with_ai(prompt, provider=ai_provider)
        ai_status = "ok"
        ai_error = None
    except NotImplementedError as exc:
        response = ""
        ai_status = "provider_not_implemented"
        ai_error = str(exc)
    except ValueError as exc:
        response = ""
        ai_status = "provider_invalid"
        ai_error = str(exc)
    except Exception as exc:
        response = ""
        ai_status = "generation_error"
        ai_error = str(exc)
    
    new_session_state = {
        "last_request_timestamp": datetime.now(timezone.utc).isoformat(),
        "last_book_id": request.get("book_id"),
        "last_chapter_id": request.get("chapter_id"),
        "last_scene_id": session_state.get("last_scene_id"),
        "last_action": "generate_scene",
        "current_mode": "chapter"
    }
    save_session_state(new_session_state)

    return {
        "resolved_request": request,
        "candidate_scene_count": len(candidate_scenes),
        "duplicate_candidate": duplicate,
        "response": response,
        "ai_provider": ai_provider,
        "ai_status": ai_status,
        "ai_error": ai_error,
        "author_message": author_message,
        "resume_status": resume_info["status"],
        "prompt_mode": prompt_mode["mode_name"]
    }
    
    
def generate_scene_from_request(request: dict) -> str:
    """
    Thin wrapper for menu/UI callers.
    Runs the orchestration pipeline and returns only the generated response text.
    """
    result = process_request(request)
    return result.get("response", "")
    
def build_generation_warnings(
    ai_status: str,
    ai_error: str | None,
    duplicate_candidate: dict | None,
    author_message: str | None,
    resume_status: str | None,
) -> list[dict]:
    """
    Build normalized frontend-safe warning/info objects for generation results.
    """

    warnings = []

    if duplicate_candidate:
        warnings.append(
            {
                "type": "duplicate_scene",
                "severity": "warning",
                "title": "Possible duplicate scene",
                "message": (
                    f"Possible duplicate scene: "
                    f"{duplicate_candidate.get('scene_id', 'unknown')}"
                ),
                "scene_id": duplicate_candidate.get("scene_id"),
            }
        )

    if resume_status and resume_status != "same_session":
        warnings.append(
            {
                "type": "resume_context",
                "severity": "info",
                "title": "Session context",
                "message": author_message or "Session context detected.",
                "resume_status": resume_status,
            }
        )

    if ai_status != "ok":
        warnings.append(
            {
                "type": "provider_status",
                "severity": "error",
                "title": "AI provider issue",
                "message": ai_error or "AI generation did not complete successfully.",
                "provider_status": ai_status,
            }
        )

    return warnings
    
def generate_scene_payload(request: dict) -> dict:
    """
    Frontend-safe wrapper.

    Returns a stable payload for UI/controller consumers.
    """
    result = process_request(request)

    ai_status = result.get("ai_status", "unknown")
    ai_error = result.get("ai_error")
    duplicate_candidate = result.get("duplicate_candidate")
    author_message = result.get("author_message")
    ai_provider = result.get("ai_provider", "")
    resume_status = result.get("resume_status")
    prompt_mode = result.get("prompt_mode")
    generated_text = result.get("response", "")

    warnings = build_generation_warnings(
        ai_status=ai_status,
        ai_error=ai_error,
        duplicate_candidate=duplicate_candidate,
        author_message=author_message,
        resume_status=resume_status,
    )

    ui_status = {
        "provider": ai_provider,
        "provider_status": ai_status,
        "provider_error": ai_error,
        "author_message": author_message,
        "resume_status": resume_status,
        "prompt_mode": prompt_mode,
        "has_duplicate_warning": bool(duplicate_candidate),
        "duplicate_scene_id": duplicate_candidate.get("scene_id") if duplicate_candidate else None,
    }

    return {
        "ok": ai_status == "ok",
        "data": {
            # legacy key retained for existing CLI compatibility
            "response": generated_text,
            # explicit key for frontend/controller use
            "generated_text": generated_text,
            "duplicate_candidate": duplicate_candidate,
            "resolved_request": result.get("resolved_request", {}),
            "candidate_scene_count": result.get("candidate_scene_count", 0),
        },
        "meta": {
            "ai_provider": ai_provider,
            "ai_status": ai_status,
            "author_message": author_message,
            "resume_status": resume_status,
            "prompt_mode": prompt_mode,
        },
        "ui_status": ui_status,
        "warnings": warnings,
        "errors": [ai_error] if ai_error else [],
    }
    
        
    
def save_accepted_scene_payload(
    request: dict,
    title: str,
    summary: str = "",
    status: str = "canon"
) -> dict:
    """
    Frontend-safe wrapper for saving an accepted scene.

    Returns a stable payload for UI/controller consumers.
    """
    try:
        scene_record = save_accepted_scene(
            request=request,
            title=title,
            summary=summary,
            status=status,
        )

        return {
            "ok": True,
            "data": {
                "scene_record": scene_record,
                "scene_id": scene_record.get("scene_id"),
                "backup_path": scene_record.get("backup_path"),
                "book_id": scene_record.get("book_id"),
                "chapter_id": scene_record.get("chapter_id"),
                "event_id": scene_record.get("event_id"),
                "title": scene_record.get("title"),
                "status": scene_record.get("status"),
            },
            "meta": {
                "action": "save_accepted_scene",
            },
            "ui_status": {
                "save_status": "ok",
                "save_error": None,
                "saved_scene_id": scene_record.get("scene_id"),
            },
            "errors": [],
        }

    except ValueError as exc:
        return {
            "ok": False,
            "data": {},
            "meta": {
                "action": "save_accepted_scene",
            },
            "ui_status": {
                "save_status": "validation_error",
                "save_error": str(exc),
                "saved_scene_id": None,
            },
            "errors": [str(exc)],
        }

    except Exception as exc:
        return {
            "ok": False,
            "data": {},
            "meta": {
                "action": "save_accepted_scene",
            },
            "ui_status": {
                "save_status": "save_error",
                "save_error": str(exc),
                "saved_scene_id": None,
            },
            "errors": [str(exc)],
        }
   