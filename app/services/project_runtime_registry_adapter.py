"""
Project runtime registry adapter.

This adapter is the Stage 9 project-local runtime access boundary. It is inert
from generation and prompt execution until a later migration phase wires those
execution paths explicitly.

Ownership split:
- project_runtime_storage_service owns creation, repair, and status for the
  project-local runtime folder and empty runtime JSON containers.
- this adapter owns controlled read/write access to the approved runtime JSON
  files after the project context has been resolved.

The adapter deliberately reuses the runtime file contract owned by
project_runtime_storage_service. It does not duplicate the contract and does not
introduce a second source of truth.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.services import project_runtime_storage_service


RUNTIME_REGISTRY_ADAPTER_MARKER = "project-runtime-registry-adapter-20260709"
RUNTIME_REGISTRY_ADAPTER_CONTRACT_SOURCE = "project_runtime_storage_service.runtime_file_names"
RUNTIME_REGISTRY_ADAPTER_VERSION = "stage9_project_runtime_registry_adapter_v2"


class RuntimeRegistryAccessError(ValueError):
    """Raised when a caller requests runtime access outside the approved contract."""


def runtime_file_names() -> tuple[str, ...]:
    """Return the universal project runtime file contract from the storage service."""

    return tuple(project_runtime_storage_service.runtime_file_names())


def validate_runtime_file_name(file_name: str) -> str:
    """Validate that a runtime file name belongs to the approved contract."""

    if not isinstance(file_name, str) or not file_name.strip():
        raise RuntimeRegistryAccessError("runtime file name is required")

    clean_name = file_name.strip().replace("\\", "/")
    if "/" in clean_name or clean_name in {".", ".."}:
        raise RuntimeRegistryAccessError("runtime file name must be a plain file name")

    allowed = set(runtime_file_names())
    if clean_name not in allowed:
        raise RuntimeRegistryAccessError(f"runtime file is not allowed: {clean_name}")

    return clean_name


def default_runtime_payload(file_name: str) -> Any:
    """Return a deep-copied default payload for an approved runtime file."""

    clean_name = validate_runtime_file_name(file_name)
    defaults = project_runtime_storage_service.EMPTY_RUNTIME_PAYLOADS
    if clean_name not in defaults:
        raise RuntimeRegistryAccessError(f"runtime default payload is missing: {clean_name}")
    return copy.deepcopy(defaults[clean_name])


def resolve_runtime_file(context: ProjectContext, file_name: str) -> Path:
    """Resolve an approved runtime file path under the project-local runtime directory."""

    clean_name = validate_runtime_file_name(file_name)
    runtime_dir = _validated_runtime_dir(context)
    return runtime_dir / clean_name


def load_runtime_json(context: ProjectContext, file_name: str) -> Any:
    """Load an approved project-local runtime JSON file.

    Missing files return the approved default payload. This read operation does
    not create folders or files.
    """

    file_path = resolve_runtime_file(context, file_name)
    if not file_path.exists():
        return default_runtime_payload(file_name)

    with file_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_runtime_json(context: ProjectContext, file_name: str, payload: Any) -> dict[str, Any]:
    """Save an approved project-local runtime JSON file.

    The storage service remains responsible for ensuring the runtime folder and
    required files exist. Existing runtime files are overwritten only when this
    explicit save method is called by a future approved execution path.
    """

    clean_name = validate_runtime_file_name(file_name)
    project_runtime_storage_service.ensure_runtime_storage_for_context(context)
    file_path = resolve_runtime_file(context, clean_name)

    with file_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    return {
        "marker": RUNTIME_REGISTRY_ADAPTER_MARKER,
        "file_name": clean_name,
        "relative_path": _relative(file_path),
        "saved": True,
        "generation_ready": False,
    }


def load_runtime_json_for_project(project_id: str, file_name: str) -> Any:
    """Load project runtime JSON after resolving ProjectContext from a project id."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return load_runtime_json(context, file_name)


def save_runtime_json_for_project(project_id: str, file_name: str, payload: Any) -> dict[str, Any]:
    """Save project runtime JSON after resolving ProjectContext from a project id."""

    manifest = project_loader.load_manifest(project_id)
    context = build_project_context(manifest)
    return save_runtime_json(context, file_name, payload)


def runtime_registry_adapter_status(context: ProjectContext) -> dict[str, Any]:
    """Return a read-only adapter status payload for diagnostics and migration checks."""

    return {
        "marker": RUNTIME_REGISTRY_ADAPTER_MARKER,
        "version": RUNTIME_REGISTRY_ADAPTER_VERSION,
        "project_id": context.project_id,
        "contract_source": RUNTIME_REGISTRY_ADAPTER_CONTRACT_SOURCE,
        "file_contract_version": "stage9_seven_file_contract",
        "allowed_files": list(runtime_file_names()),
        "runtime_root": _relative(_validated_runtime_dir(context)),
        "generation_ready": False,
        "prompt_builder_wired": False,
        "project_runner_wired": False,
        "legacy_registry_replaced": False,
        "policy": "adapter_reuses_storage_service_contract_and_is_inert_until_explicit_wiring",
    }


def _validated_runtime_dir(context: ProjectContext) -> Path:
    runtime_dir = context.runtime_data_dir.resolve()
    project_dir = context.project_dir.resolve()

    if project_dir not in runtime_dir.parents:
        raise project_loader.InvalidProjectIdError("runtime path escapes project directory")

    if runtime_dir.name != "runtime":
        raise project_loader.InvalidProjectIdError("runtime path does not target project runtime directory")

    return runtime_dir


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(project_loader.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
