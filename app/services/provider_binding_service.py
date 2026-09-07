from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.projects import project_loader
from app.services import (
    provider_config_service,
    provider_generation_receipt_service,
    provider_usage_service,
)


PROVIDER_BINDING_SCHEMA_VERSION = "primary33.2.1a2-project-model-binding-v3"
LOCK_POLICY = "provider_and_model_lock_after_provider_execution_start_or_first_usage_event"


class ProviderBindingError(ValueError):
    """Raised when project provider binding is invalid."""


class ProviderBindingLockedError(ProviderBindingError):
    """Raised when a project with provider usage attempts a provider/model switch."""


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def binding_path(project_id: str) -> Path:
    project_loader.load_manifest(project_id)
    return project_loader.project_dir(project_id) / "provider_binding.json"


def _read_binding(project_id: str) -> dict[str, Any] | None:
    path = binding_path(project_id)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else None


def _require_binding_identity(
    project_id: str,
    binding: dict[str, Any] | None,
) -> None:
    if binding is None:
        return

    bound_project_id = str(binding.get("project_id") or "").strip()
    if bound_project_id != project_id:
        raise ProviderBindingError(
            "Project provider binding identity does not match the requested project. "
            "Provider/model changes are blocked until the binding is reconciled."
        )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, path)


def _usage_event_count(project_id: str) -> int:
    try:
        ledger_count = provider_usage_service.get_usage_ledger_event_count(project_id)
    except OSError as exc:
        raise ProviderBindingError(
            "Provider usage ledger could not be read. Provider/model changes are blocked "
            "until usage state is reconciled."
        ) from exc

    try:
        summary_payload = provider_usage_service.get_usage_summary(project_id)
    except provider_usage_service.ProviderUsageError as exc:
        if ledger_count > 0:
            return ledger_count
        raise ProviderBindingError(
            "Provider usage summary integrity could not be established. Provider/model "
            "changes are blocked until usage state is reconciled."
        ) from exc

    summary = summary_payload.get("summary") if isinstance(summary_payload, dict) else {}
    raw_summary_count = (summary or {}).get("event_count") or 0

    if isinstance(raw_summary_count, bool):
        raise ProviderBindingError(
            "Provider usage summary event_count is invalid. Provider/model changes are "
            "blocked until usage state is reconciled."
        )

    try:
        summary_count = int(raw_summary_count)
    except (TypeError, ValueError) as exc:
        raise ProviderBindingError(
            "Provider usage summary event_count is invalid. Provider/model changes are "
            "blocked until usage state is reconciled."
        ) from exc

    if summary_count < 0:
        raise ProviderBindingError(
            "Provider usage summary event_count cannot be negative. Provider/model changes "
            "are blocked until usage state is reconciled."
        )

    return max(summary_count, ledger_count)


def _execution_intent_lock_state(project_id: str) -> dict[str, Any]:
    try:
        state = provider_generation_receipt_service.get_project_execution_lock_state(
            project_id
        )
    except provider_generation_receipt_service.ProviderGenerationReceiptError as exc:
        raise ProviderBindingError(
            "Provider execution-intent integrity could not be established. Provider/model "
            "changes are blocked until execution state is reconciled."
        ) from exc

    if not isinstance(state, dict):
        raise ProviderBindingError(
            "Provider execution-intent state is invalid. Provider/model changes are blocked "
            "until execution state is reconciled."
        )
    return state


def get_project_provider_binding(project_id: str) -> dict[str, Any]:
    with provider_generation_receipt_service.project_execution_state_lock(project_id):
        manifest = project_loader.load_manifest(project_id)
        binding = _read_binding(project_id)
        _require_binding_identity(project_id, binding)
        event_count = _usage_event_count(project_id)
        execution_state = _execution_intent_lock_state(project_id)
        execution_locked = bool(execution_state.get("locked"))
        locked = event_count > 0 or execution_locked

        if execution_locked:
            reason = (
                "Provider/model binding is locked because an unresolved provider execution "
                "is active for this project."
            )
        elif event_count > 0:
            reason = (
                "Provider/model binding is locked because provider usage already exists for "
                "this project."
            )
        else:
            reason = (
                "Provider/model may be rebound until provider execution starts or the first "
                "provider usage event is recorded."
            )

        return {
            "status": "ok",
            "schema_version": PROVIDER_BINDING_SCHEMA_VERSION,
            "project_id": project_id,
            "project_name": manifest.project_name,
            "binding": binding,
            "lineage": {
                "binding_instance_id": (
                    str((binding or {}).get("binding_instance_id") or "") or None
                ),
                "ready_for_usage_provenance": bool(
                    str((binding or {}).get("binding_instance_id") or "").strip()
                ),
            },
            "lock": {
                "policy": LOCK_POLICY,
                "locked": locked,
                "can_change": not locked,
                "usage_event_count": event_count,
                "active_execution_intent_count": int(
                    execution_state.get("active_intent_count") or 0
                ),
                "execution_intent_statuses": dict(
                    execution_state.get("statuses") or {}
                ),
                "reason": reason,
            },
            "execution": {
                "provider_execution_allowed": False,
                "reason": "Primary 33.2.2A execution machinery is installed but production provider execution remains locked.",
            },
        }


def save_project_provider_binding(
    project_id: str,
    *,
    provider_id: str,
) -> dict[str, Any]:
    manifest = project_loader.load_manifest(project_id)
    profile = provider_config_service.get_provider_profile(provider_id)
    if profile is None:
        raise ProviderBindingError(
            "Save a provider/model configuration profile before binding that provider to a project."
        )

    validation = profile.get("model_validation") or {}
    if not bool(validation.get("accepted")):
        raise ProviderBindingError(
            "The saved provider profile uses a model ID that is not accepted by the "
            "curated direct-provider catalog. Select and save an accepted model before "
            "binding this provider to a project."
        )

    snapshot = {
        "provider_id": str(profile["provider_id"]),
        "model_id": str(profile["model_id"]),
        "service_tier": str(profile["service_tier"]),
        "inference_scope": str(profile["inference_scope"]),
    }

    with provider_generation_receipt_service.project_execution_state_lock(project_id):
        current = _read_binding(project_id)
        _require_binding_identity(project_id, current)
        event_count = _usage_event_count(project_id)
        execution_state = _execution_intent_lock_state(project_id)

        comparable_current = {
            key: str((current or {}).get(key) or "")
            for key in snapshot
        }
        same_snapshot = comparable_current == snapshot

        if bool(execution_state.get("locked")):
            if same_snapshot:
                return get_project_provider_binding(project_id)
            raise ProviderBindingLockedError(
                "Provider/model switching is forbidden while an unresolved provider execution "
                "is active for this project. Complete or reconcile that execution first."
            )

        if event_count > 0:
            if same_snapshot:
                return get_project_provider_binding(project_id)
            raise ProviderBindingLockedError(
                "Provider/model switching is forbidden after provider usage begins for this project. "
                "Use the Gate 38A controlled provider/model migration workflow to change it safely."
            )

        existing_binding_instance_id = str(
            (current or {}).get("binding_instance_id") or ""
        ).strip()
        binding_instance_id = (
            existing_binding_instance_id
            if same_snapshot and existing_binding_instance_id
            else f"bind_{uuid.uuid4().hex}"
        )

        now = _utc_iso()
        payload = {
            "schema_version": PROVIDER_BINDING_SCHEMA_VERSION,
            "project_id": project_id,
            "project_name": manifest.project_name,
            **snapshot,
            "binding_instance_id": binding_instance_id,
            "provider_profile_model_id_at_binding": str(profile.get("model_id") or ""),
            "provider_profile_updated_at": profile.get("updated_at"),
            "model_selection_source": "provider_profile_default",
            "previous_binding_instance_id": (
                str((current or {}).get("binding_instance_id") or "") or None
                if not same_snapshot
                else (current or {}).get("previous_binding_instance_id")
            ),
            "lock_policy": LOCK_POLICY,
            "created_at": (current or {}).get("created_at") or now,
            "updated_at": now,
        }
        _write_json_atomic(binding_path(project_id), payload)
        return get_project_provider_binding(project_id)


def save_project_model_override(
    project_id: str,
    *,
    model_id: str,
) -> dict[str, Any]:
    """Change only the project-effective model for the currently bound provider.

    Provider Settings remains the reusable provider/default configuration. This
    operation preserves the project's bound provider, service tier, and
    inference scope. Before provider usage begins, changing the effective model
    creates a new binding instance for deterministic future usage lineage.
    """

    manifest = project_loader.load_manifest(project_id)

    with provider_generation_receipt_service.project_execution_state_lock(project_id):
        current = _read_binding(project_id)
        _require_binding_identity(project_id, current)
        if current is None:
            raise ProviderBindingError(
                "Bind a saved provider profile to this project before selecting a project model."
            )

        execution_state = _execution_intent_lock_state(project_id)
        if bool(execution_state.get("locked")):
            raise ProviderBindingLockedError(
                "Project model switching is forbidden while an unresolved provider execution "
                "is active. Complete or reconcile that execution first."
            )

        event_count = _usage_event_count(project_id)
        if event_count > 0:
            raise ProviderBindingLockedError(
                "Project model switching is forbidden after provider usage begins. "
                "Use the Gate 38A controlled provider/model migration workflow to preserve billing lineage."
            )

        provider_id = str(current.get("provider_id") or "").strip().lower()
        if not provider_id:
            raise ProviderBindingError("The current project binding has no provider_id.")

        profile = provider_config_service.get_provider_profile(provider_id)
        if profile is None:
            raise ProviderBindingError(
                "The bound provider profile no longer exists. Restore the provider profile before changing the project model."
            )

        requested_model_id = str(model_id or "").strip()
        try:
            provider_config_service.require_accepted_model_id(
                provider_id,
                requested_model_id,
            )
        except provider_config_service.ProviderConfigError as exc:
            raise ProviderBindingError(str(exc)) from exc

        current_model_id = str(current.get("model_id") or "").strip()
        if requested_model_id == current_model_id:
            return get_project_provider_binding(project_id)

        previous_binding_instance_id = str(
            current.get("binding_instance_id") or ""
        ).strip() or None
        now = _utc_iso()

        payload = {
            **current,
            "schema_version": PROVIDER_BINDING_SCHEMA_VERSION,
            "project_id": project_id,
            "project_name": manifest.project_name,
            "provider_id": provider_id,
            "model_id": requested_model_id,
            "service_tier": str(current.get("service_tier") or "standard"),
            "inference_scope": str(current.get("inference_scope") or "global"),
            "binding_instance_id": f"bind_{uuid.uuid4().hex}",
            "previous_binding_instance_id": previous_binding_instance_id,
            "provider_profile_model_id_at_binding": str(profile.get("model_id") or ""),
            "provider_profile_updated_at": profile.get("updated_at"),
            "model_selection_source": "project_override",
            "lock_policy": LOCK_POLICY,
            "created_at": current.get("created_at") or now,
            "updated_at": now,
        }
        _write_json_atomic(binding_path(project_id), payload)
        return get_project_provider_binding(project_id)



def _apply_controlled_migration_binding(
    project_id: str,
    *,
    target_provider_id: str,
    target_model_id: str,
    service_tier: str,
    inference_scope: str,
    expected_current_binding_instance_id: str,
    migration_id: str,
) -> dict[str, Any]:
    """Internal Gate 38A binding transition.

    This is intentionally not exposed as a normal binding operation. The
    provider_migration_service owns preservation evidence and calls this helper
    only while holding the project execution-state lock.
    """

    manifest = project_loader.load_manifest(project_id)
    target_provider = str(target_provider_id or "").strip().lower()
    target_model = str(target_model_id or "").strip()
    target_tier = str(service_tier or "").strip().lower()
    target_scope = str(inference_scope or "").strip().lower()
    expected_id = str(expected_current_binding_instance_id or "").strip()
    migration = str(migration_id or "").strip()

    if not all((target_provider, target_model, target_tier, target_scope, expected_id, migration)):
        raise ProviderBindingError(
            "Gate 38A controlled migration binding inputs are incomplete."
        )

    profile = provider_config_service.get_provider_profile(target_provider)
    if profile is None:
        raise ProviderBindingError(
            "Save the target provider profile before controlled migration."
        )
    try:
        provider_config_service.require_accepted_model_id(
            target_provider,
            target_model,
        )
    except provider_config_service.ProviderConfigError as exc:
        raise ProviderBindingError(str(exc)) from exc

    with provider_generation_receipt_service.project_execution_state_lock(project_id):
        current = _read_binding(project_id)
        _require_binding_identity(project_id, current)
        if current is None:
            raise ProviderBindingError(
                "Gate 38A controlled migration requires an existing provider binding."
            )

        current_id = str(current.get("binding_instance_id") or "").strip()
        if not current_id or current_id != expected_id:
            raise ProviderBindingLockedError(
                "Gate 38A current binding instance no longer matches the migration precondition."
            )

        execution_state = _execution_intent_lock_state(project_id)
        if bool(execution_state.get("locked")):
            raise ProviderBindingLockedError(
                "Gate 38A controlled migration is forbidden while provider execution is active or unresolved."
            )

        current_snapshot = {
            "provider_id": str(current.get("provider_id") or "").strip().lower(),
            "model_id": str(current.get("model_id") or "").strip(),
            "service_tier": str(current.get("service_tier") or "standard").strip().lower(),
            "inference_scope": str(current.get("inference_scope") or "global").strip().lower(),
        }
        target_snapshot = {
            "provider_id": target_provider,
            "model_id": target_model,
            "service_tier": target_tier,
            "inference_scope": target_scope,
        }
        if current_snapshot == target_snapshot:
            raise ProviderBindingError(
                "Gate 38A target binding must differ from the current binding."
            )

        now = _utc_iso()
        payload = {
            "schema_version": PROVIDER_BINDING_SCHEMA_VERSION,
            "project_id": project_id,
            "project_name": manifest.project_name,
            **target_snapshot,
            "binding_instance_id": f"bind_{uuid.uuid4().hex}",
            "previous_binding_instance_id": current_id,
            "provider_profile_model_id_at_binding": str(profile.get("model_id") or ""),
            "provider_profile_updated_at": profile.get("updated_at"),
            "model_selection_source": "gate38a_controlled_migration",
            "migration_id": migration,
            "migrated_from_binding_instance_id": current_id,
            "lock_policy": LOCK_POLICY,
            "created_at": now,
            "updated_at": now,
        }
        _write_json_atomic(binding_path(project_id), payload)
        return get_project_provider_binding(project_id)


def _restore_binding_after_failed_controlled_migration(
    project_id: str,
    *,
    expected_current_binding_instance_id: str | None,
    prior_binding: dict[str, Any],
) -> None:
    """Restore the exact pre-migration binding after a failed Gate 38A transaction.

    Restoration is drift-protected. It refuses to overwrite a binding that has
    moved beyond the binding created by the failed migration.
    """

    project_loader.load_manifest(project_id)
    if not isinstance(prior_binding, dict):
        raise ProviderBindingError("Gate 38A prior binding snapshot is invalid.")

    with provider_generation_receipt_service.project_execution_state_lock(project_id):
        current = _read_binding(project_id)
        _require_binding_identity(project_id, current)

        expected = str(expected_current_binding_instance_id or "").strip()
        if expected:
            actual = str((current or {}).get("binding_instance_id") or "").strip()
            if actual != expected:
                raise ProviderBindingLockedError(
                    "Gate 38A rollback refused because the current binding has drifted."
                )

        _write_json_atomic(binding_path(project_id), dict(prior_binding))


def list_provider_profile_associations(
    provider_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return every project currently associated with a provider profile.

    Includes active and archived projects so profile deletion cannot silently
    ignore a binding that is outside the active-project selector.
    """
    wanted = str(provider_id or "").strip().lower()
    associations: list[dict[str, Any]] = []

    for project_id in project_loader.list_project_ids():
        binding = _read_binding(project_id)
        if not isinstance(binding, dict):
            continue

        bound_provider = str(binding.get("provider_id") or "").strip().lower()
        if not bound_provider:
            continue
        if wanted and bound_provider != wanted:
            continue

        try:
            payload = get_project_provider_binding(project_id)
        except ProviderBindingError as exc:
            payload = {
                "lock": {
                    "policy": LOCK_POLICY,
                    "locked": True,
                    "can_change": False,
                    "usage_event_count": None,
                    "reason": f"Binding integrity error: {exc}",
                }
            }
        manifest = project_loader.load_manifest(project_id)
        associations.append(
            {
                "project_id": project_id,
                "project_name": manifest.project_name,
                "lifecycle_state": manifest.lifecycle_state,
                "provider_id": bound_provider,
                "model_id": str(binding.get("model_id") or ""),
                "binding_instance_id": str(
                    binding.get("binding_instance_id") or ""
                ) or None,
                "lock": payload.get("lock") or {},
            }
        )

    return sorted(
        associations,
        key=lambda item: (
            str(item.get("project_name") or "").lower(),
            str(item.get("project_id") or "").lower(),
        ),
    )


def delete_project_provider_binding(project_id: str) -> dict[str, Any]:
    """Disassociate a provider profile from a project without deleting the project.

    Provider/model disassociation is blocked once provider execution begins and
    remains blocked after usage is recorded outside the Gate 38A controlled migration path.
    """

    project_loader.load_manifest(project_id)

    with provider_generation_receipt_service.project_execution_state_lock(project_id):
        current = _read_binding(project_id)
        _require_binding_identity(project_id, current)
        if current is None:
            return get_project_provider_binding(project_id)

        execution_state = _execution_intent_lock_state(project_id)
        if bool(execution_state.get("locked")):
            raise ProviderBindingLockedError(
                "Provider/model disassociation is forbidden while an unresolved provider "
                "execution is active. Complete or reconcile that execution first."
            )

        event_count = _usage_event_count(project_id)
        if event_count > 0:
            raise ProviderBindingLockedError(
                "Provider/model disassociation is forbidden after provider usage begins for this project. "
                "Use the Gate 38A controlled provider/model migration workflow."
            )

        path = binding_path(project_id)
        if path.exists():
            path.unlink()

        return get_project_provider_binding(project_id)
