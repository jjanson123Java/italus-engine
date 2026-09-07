from __future__ import annotations

import json
from typing import Any

from app.registry import load_app_settings, save_app_settings


VIEW_SETTINGS_KEY = "view"
DEFAULT_SHOW_TILES = True
DEFAULT_SHOW_LEARN_MORE = True


class ApplicationSettingsError(RuntimeError):
    """Raised when persistent application settings cannot be read or written safely."""


def _load_settings_document() -> dict[str, Any]:
    try:
        settings = load_app_settings()
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplicationSettingsError(
            "Application settings could not be loaded safely."
        ) from exc

    if not isinstance(settings, dict):
        raise ApplicationSettingsError(
            "Application settings must be a JSON object."
        )
    return dict(settings)


def _normalize_view_settings(raw_view: Any) -> dict[str, bool]:
    if raw_view is None:
        raw_view = {}
    if not isinstance(raw_view, dict):
        raise ApplicationSettingsError(
            "Application view settings must be a JSON object."
        )

    normalized = {
        "show_tiles": DEFAULT_SHOW_TILES,
        "show_learn_more": DEFAULT_SHOW_LEARN_MORE,
    }

    for key in tuple(normalized):
        if key not in raw_view:
            continue
        value = raw_view[key]
        if not isinstance(value, bool):
            raise ApplicationSettingsError(
                f"Application view setting {key!r} must be boolean."
            )
        normalized[key] = value

    return normalized


def get_application_view_settings() -> dict[str, Any]:
    settings = _load_settings_document()
    return {
        "status": "ok",
        "view": _normalize_view_settings(settings.get(VIEW_SETTINGS_KEY)),
    }


def update_application_view_settings(
    *,
    show_tiles: bool | None = None,
    show_learn_more: bool | None = None,
) -> dict[str, Any]:
    settings = _load_settings_document()
    view = _normalize_view_settings(settings.get(VIEW_SETTINGS_KEY))

    if show_tiles is not None:
        if not isinstance(show_tiles, bool):
            raise ApplicationSettingsError("show_tiles must be boolean.")
        view["show_tiles"] = show_tiles

    if show_learn_more is not None:
        if not isinstance(show_learn_more, bool):
            raise ApplicationSettingsError("show_learn_more must be boolean.")
        view["show_learn_more"] = show_learn_more

    settings[VIEW_SETTINGS_KEY] = dict(view)

    try:
        save_app_settings(settings)
    except OSError as exc:
        raise ApplicationSettingsError(
            "Application view settings could not be persisted."
        ) from exc

    return {
        "status": "ok",
        "view": dict(view),
    }
