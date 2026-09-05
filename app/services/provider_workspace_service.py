from __future__ import annotations

from typing import Any

from app.projects import project_loader
from app.services import (
    budget_service,
    provider_binding_service,
    provider_config_service,
    provider_pricing_service,
    provider_usage_service,
)


PROVIDER_WORKSPACE_SCHEMA_VERSION = "primary33.2.1a3-provider-workspace-summary-v5"


def get_project_provider_workspace_summary(project_id: str) -> dict[str, Any]:
    """Return the read-only Provider 33.1 projection consumed by Workspace.

    This function performs local state reads only. It never resolves API-key
    plaintext, calls a provider, performs token preflight, records usage, or
    enables generation.
    """

    manifest = project_loader.load_manifest(project_id)
    budget_plan = project_loader.load_budget_plan(project_id) or {}
    binding_payload = provider_binding_service.get_project_provider_binding(project_id)
    binding = binding_payload.get("binding")
    binding = binding if isinstance(binding, dict) else None

    catalog_payload = provider_config_service.provider_catalog()
    catalog = catalog_payload.get("providers")
    catalog = catalog if isinstance(catalog, list) else []

    profiles: list[dict[str, Any]] = []
    for profile in provider_config_service.list_provider_profiles():
        if not isinstance(profile, dict):
            continue
        profiles.append(
            {
                "provider_id": profile.get("provider_id"),
                "model_id": profile.get("model_id"),
                "service_tier": profile.get("service_tier"),
                "inference_scope": profile.get("inference_scope"),
                "updated_at": profile.get("updated_at"),
            }
        )

    policy = provider_pricing_service.get_pricing_policy()["policy"]
    pricing = None
    scheduled_pricing = None
    previous_pricing = None
    pricing_lifecycle: dict[str, Any] = {}
    freshness = provider_pricing_service.pricing_freshness_status(
        None,
        threshold_days=int(policy["freshness_threshold_days"]),
    )
    planning_estimate = None

    if binding:
        pricing_payload = provider_pricing_service.get_current_pricing(
            provider_id=str(binding.get("provider_id") or ""),
            model_id=str(binding.get("model_id") or ""),
            service_tier=str(binding.get("service_tier") or "standard"),
            inference_scope=str(binding.get("inference_scope") or "global"),
        )
        pricing = pricing_payload.get("pricing")
        pricing = pricing if isinstance(pricing, dict) else None
        scheduled_pricing = pricing_payload.get("next_scheduled_pricing")
        scheduled_pricing = (
            scheduled_pricing if isinstance(scheduled_pricing, dict) else None
        )
        freshness = pricing_payload.get("freshness") or freshness
        policy = pricing_payload.get("policy") or policy

        registry_payload = provider_pricing_service.get_pricing_registry(
            provider_id=str(binding.get("provider_id") or ""),
            service_tier=str(binding.get("service_tier") or "standard"),
            inference_scope=str(binding.get("inference_scope") or "global"),
        )
        registry_rows = registry_payload.get("models")
        registry_rows = registry_rows if isinstance(registry_rows, list) else []
        registry_row = next(
            (
                row
                for row in registry_rows
                if isinstance(row, dict)
                and str(row.get("model_id") or "") == str(binding.get("model_id") or "")
            ),
            None,
        )
        if isinstance(registry_row, dict):
            scheduled_versions = registry_row.get("scheduled_versions")
            retired_versions = registry_row.get("retired_versions")
            versions = registry_row.get("versions")
            retired_versions = (
                retired_versions if isinstance(retired_versions, list) else []
            )
            previous_candidate = retired_versions[0] if retired_versions else None
            previous_pricing = (
                previous_candidate if isinstance(previous_candidate, dict) else None
            )
            pricing_lifecycle = {
                "current_version_id": (
                    str((pricing or {}).get("pricing_version_id") or "") or None
                ),
                "previous_version_id": (
                    str((previous_pricing or {}).get("pricing_version_id") or "") or None
                ),
                "scheduled_count": len(scheduled_versions) if isinstance(scheduled_versions, list) else 0,
                "retired_count": len(retired_versions),
                "version_count": len(versions) if isinstance(versions, list) else 0,
            }

        if pricing:
            planning_estimate = budget_service.estimate_provider_planning_cost(
                budget_plan,
                pricing,
            )

    usage_payload = provider_usage_service.get_usage_summary(project_id)
    usage_summary = usage_payload.get("summary")
    usage_summary = usage_summary if isinstance(usage_summary, dict) else {}

    project_model_control: dict[str, Any] | None = None
    if binding:
        provider_id = str(binding.get("provider_id") or "").strip().lower()
        profile = provider_config_service.get_provider_profile(provider_id)
        provider_entry = next(
            (
                item
                for item in catalog
                if str((item or {}).get("provider_id") or "").strip().lower()
                == provider_id
            ),
            None,
        )
        models = (
            provider_entry.get("models")
            if isinstance(provider_entry, dict)
            and isinstance(provider_entry.get("models"), list)
            else []
        )
        accepted_models = [
            {
                "display_name": model.get("display_name"),
                "model_id": model.get("model_id"),
                "catalog_tier": model.get("catalog_tier"),
                "recommended_use": model.get("recommended_use"),
                "is_default": bool(model.get("is_default")),
            }
            for model in models
            if isinstance(model, dict)
            and bool(model.get("enabled"))
            and str(model.get("status") or "") == "production"
        ]
        binding_lock = binding_payload.get("lock") or {}
        project_model_control = {
            "provider_id": provider_id,
            "profile_default_model_id": (
                str((profile or {}).get("model_id") or "") or None
            ),
            "effective_model_id": str(binding.get("model_id") or ""),
            "model_selection_source": str(
                binding.get("model_selection_source") or "binding_snapshot"
            ),
            "available_models": accepted_models,
            "can_change": bool(binding_lock.get("can_change")),
            "locked": bool(binding_lock.get("locked")),
            "reason": str(binding_lock.get("reason") or ""),
        }

    return {
        "status": "ok",
        "schema_version": PROVIDER_WORKSPACE_SCHEMA_VERSION,
        "project_id": project_id,
        "project_name": manifest.project_name,
        "provider_catalog": catalog,
        "configured_profiles": profiles,
        "binding": binding,
        "binding_lock": binding_payload.get("lock") or {},
        "project_model_control": project_model_control,
        "pricing": pricing,
        "scheduled_pricing": scheduled_pricing,
        "previous_pricing": previous_pricing,
        "pricing_lifecycle": pricing_lifecycle,
        "pricing_policy": policy,
        "pricing_freshness": freshness,
        "planning_estimate": planning_estimate,
        "usage_summary": usage_summary,
        "billing_history": usage_summary.get("billing_segments") or [],
        "execution": {
            "provider_execution_allowed": False,
            "reason": (
                "Primary 33.2.1A3 exposes project-effective model controls and effective-dated pricing lineage only. "
                "Provider execution remains locked until later Primary 33.2 acceptance gates pass."
            ),
        },
    }
