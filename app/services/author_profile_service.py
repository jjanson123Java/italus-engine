from __future__ import annotations

import json
from typing import Any

from app.registry import load_author_profile_document, save_author_profile_document


SCHEMA_VERSION = 1
DEFAULT_PROFILE_ID = "default-author"

PROFILE_FIELD_LIMITS = {
    "professional_name": 160,
    "profession_niche": 240,
    "featured_work": 240,
    "genre_mission": 500,
    "standard_bio": 4000,
    "short_bio": 500,
    "credentials_achievements": 1500,
    "expertise_background": 1500,
    "humanizing_detail": 500,
    "location": 240,
    "professional_email": 320,
    "website": 500,
    "newsletter_url": 500,
    "cta": 500,
    "x_url": 500,
    "instagram_url": 500,
    "tiktok_url": 500,
    "linkedin_url": 500,
}


class AuthorProfileError(RuntimeError):
    """Base error for the application-global author profile domain."""


class AuthorProfileStorageError(AuthorProfileError):
    """Raised when persisted author profile state cannot be read or written safely."""


class AuthorProfileValidationError(AuthorProfileError):
    """Raised when an attempted profile update violates the profile contract."""


def _empty_profile(profile_id: str) -> dict[str, str]:
    profile = {"profile_id": profile_id}
    for field_name in PROFILE_FIELD_LIMITS:
        profile[field_name] = ""
    return profile


def _empty_document() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "active_profile_id": DEFAULT_PROFILE_ID,
        "profiles": {
            DEFAULT_PROFILE_ID: _empty_profile(DEFAULT_PROFILE_ID),
        },
    }


def _normalize_text(
    field_name: str,
    value: Any,
    *,
    error_type: type[AuthorProfileError],
) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise error_type(f"Author profile field {field_name!r} must be text.")

    normalized = value.strip()
    max_length = PROFILE_FIELD_LIMITS[field_name]
    if len(normalized) > max_length:
        raise error_type(
            f"Author profile field {field_name!r} exceeds {max_length} characters."
        )
    return normalized


def _normalize_profile(
    raw_profile: Any,
    *,
    expected_profile_id: str,
    error_type: type[AuthorProfileError],
) -> dict[str, str]:
    if not isinstance(raw_profile, dict):
        raise error_type("Author profile record must be a JSON object.")

    profile_id = raw_profile.get("profile_id", expected_profile_id)
    if not isinstance(profile_id, str) or not profile_id.strip():
        raise error_type("Author profile record requires a stable profile_id.")
    profile_id = profile_id.strip()

    if profile_id != expected_profile_id:
        raise error_type("Author profile identity does not match the active profile key.")

    normalized = _empty_profile(profile_id)
    for field_name in PROFILE_FIELD_LIMITS:
        normalized[field_name] = _normalize_text(
            field_name,
            raw_profile.get(field_name, ""),
            error_type=error_type,
        )
    return normalized


def _load_profile_state() -> tuple[dict[str, Any], str, dict[str, str]]:
    try:
        document = load_author_profile_document()
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorProfileStorageError(
            "Author profile could not be loaded safely."
        ) from exc

    if not document:
        document = _empty_document()

    if not isinstance(document, dict):
        raise AuthorProfileStorageError(
            "Author profile storage must be a JSON object."
        )

    if document.get("schema_version") != SCHEMA_VERSION:
        raise AuthorProfileStorageError(
            f"Unsupported author profile schema version: "
            f"{document.get('schema_version')!r}."
        )

    active_profile_id = document.get("active_profile_id")
    if not isinstance(active_profile_id, str) or not active_profile_id.strip():
        raise AuthorProfileStorageError(
            "Author profile storage requires an active_profile_id."
        )
    active_profile_id = active_profile_id.strip()

    profiles = document.get("profiles")
    if not isinstance(profiles, dict):
        raise AuthorProfileStorageError(
            "Author profile storage requires a profiles object."
        )

    raw_profile = profiles.get(active_profile_id)
    if raw_profile is None:
        raise AuthorProfileStorageError(
            "The active author profile record is missing."
        )

    profile = _normalize_profile(
        raw_profile,
        expected_profile_id=active_profile_id,
        error_type=AuthorProfileStorageError,
    )
    return dict(document), active_profile_id, profile


def get_author_profile() -> dict[str, Any]:
    _, active_profile_id, profile = _load_profile_state()
    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "active_profile_id": active_profile_id,
        "profile": dict(profile),
    }


def update_author_profile(**changes: Any) -> dict[str, Any]:
    document, active_profile_id, profile = _load_profile_state()

    for field_name, value in changes.items():
        if field_name not in PROFILE_FIELD_LIMITS:
            raise AuthorProfileValidationError(
                f"Unsupported author profile field: {field_name!r}."
            )
        profile[field_name] = _normalize_text(
            field_name,
            value,
            error_type=AuthorProfileValidationError,
        )

    profiles = document.get("profiles")
    if not isinstance(profiles, dict):
        raise AuthorProfileStorageError(
            "Author profile storage requires a profiles object."
        )

    updated_profiles = dict(profiles)
    updated_profiles[active_profile_id] = dict(profile)

    updated_document = dict(document)
    updated_document["schema_version"] = SCHEMA_VERSION
    updated_document["active_profile_id"] = active_profile_id
    updated_document["profiles"] = updated_profiles

    try:
        save_author_profile_document(updated_document)
    except OSError as exc:
        raise AuthorProfileStorageError(
            "Author profile could not be persisted."
        ) from exc

    return {
        "status": "ok",
        "schema_version": SCHEMA_VERSION,
        "active_profile_id": active_profile_id,
        "profile": dict(profile),
    }
