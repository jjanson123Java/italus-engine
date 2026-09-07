from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable


PRIMARY39_MARKER = "primary39-full-migration-regression-v1"
PRIMARY39_SCHEMA_VERSION = "primary39_full_migration_regression_v1"


class RegressionSuite:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def check(self, test_id: str, description: str, condition: bool, details: str = "") -> None:
        passed = bool(condition)
        self.results.append(
            {
                "id": test_id,
                "description": description,
                "status": "PASS" if passed else "FAIL",
                "details": str(details or ""),
            }
        )

    def equal(self, test_id: str, description: str, actual: Any, expected: Any) -> None:
        self.check(
            test_id,
            description,
            actual == expected,
            details=f"actual={actual!r}; expected={expected!r}",
        )

    def contains(self, test_id: str, description: str, container: Any, value: Any) -> None:
        self.check(
            test_id,
            description,
            value in container,
            details=f"required={value!r}",
        )

    @property
    def passed(self) -> int:
        return sum(1 for item in self.results if item["status"] == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for item in self.results if item["status"] == "FAIL")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _source(repo: Path, relative_path: str) -> str:
    return (repo / relative_path).read_text(encoding="utf-8")


def _function_names(source_text: str, function_name: str) -> set[str]:
    tree = ast.parse(source_text)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            names: set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    names.add(child.id)
                elif isinstance(child, ast.Attribute):
                    names.add(child.attr)
            return names
    raise AssertionError(f"Function not found: {function_name}")


def _route_signatures(router: Any) -> set[tuple[str, str]]:
    signatures: set[tuple[str, str]] = set()
    for route in router.routes:
        path = str(getattr(route, "path", "") or "")
        for method in set(getattr(route, "methods", set()) or set()):
            signatures.add((str(method).upper(), path))
    return signatures


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run_primary38_probe(suite: RegressionSuite) -> None:
    from app.services import approved_continuity_integration_service as integration
    from app.services import authorship_ledger_service as ledger

    accepted_a = "Author-rewritten accepted manuscript passage one."
    accepted_b = "Author replacement accepted manuscript passage two."
    origin_a = "Model origin passage one."
    origin_b = "Model origin passage two."

    commit_a = {
        "commit_id": "ac_probe_a",
        "project_id": "probe-project",
        "generation_id": "gen_probe_a",
        "segment_id": "seg_probe_a",
        "book_number": 1,
        "chapter_number": 1,
        "accepted_version_id": "review_version_a",
        "accepted_content_sha256": _sha(accepted_a),
        "accepted_content": accepted_a,
        "author_accept_event_id": "review_event_a",
        "author_accept_after_hash": _sha(accepted_a),
        "classification_evidence": {
            "service": "primary35-provenance-classification-v1",
            "schema_version": "primary35_provenance_classification_v1",
            "assessment_status": "classified",
            "final_segment_state": "AI_GENERATED_SUBSTANTIVELY_REWRITTEN",
            "hccs": 72.5,
            "accepted_version_id": "review_version_a",
            "accepted_content_sha256": _sha(accepted_a),
            "evidence_confidence": {"tier": "high"},
            "awarded_level": {"level": 3, "name": "Human Modified"},
        },
    }
    commit_b = {
        "commit_id": "ac_probe_b",
        "project_id": "probe-project",
        "generation_id": "gen_probe_b",
        "segment_id": "seg_probe_b",
        "book_number": 1,
        "chapter_number": 2,
        "accepted_version_id": "review_version_b",
        "accepted_content_sha256": _sha(accepted_b),
        "accepted_content": accepted_b,
        "author_accept_event_id": "review_event_b",
        "author_accept_after_hash": _sha(accepted_b),
        "classification_evidence": {
            "service": "primary35-provenance-classification-v1",
            "schema_version": "primary35_provenance_classification_v1",
            "assessment_status": "classified",
            "final_segment_state": "AI_GENERATED_REPLACED_BY_AUTHOR",
            "hccs": 91.0,
            "accepted_version_id": "review_version_b",
            "accepted_content_sha256": _sha(accepted_b),
            "evidence_confidence": {"tier": "high"},
            "awarded_level": {"level": 4, "name": "Human Authored - AI Assisted"},
        },
    }
    continuity = {
        "status": "ok",
        "service": "primary36a-approved-continuity-core-v1",
        "schema_version": "approved_continuity_v1",
        "project_id": "probe-project",
        "revision": 2,
        "content_hash": "a" * 64,
        "document": {"commits": [commit_a, commit_b]},
    }

    def lineage(
        generation_id: str,
        segment_id: str,
        origin_text: str,
        accepted_text: str,
        event_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "origins": [
                {
                    "origin_id": "origin_" + generation_id,
                    "version_id": "origin_version_" + generation_id,
                    "generation_id": generation_id,
                    "segment_id": segment_id,
                    "origin_actor": "MODEL",
                    "provider": "probe-provider",
                    "provider_model": "probe-model",
                    "content": origin_text,
                    "content_hash": _sha(origin_text),
                    "immutable": True,
                }
            ],
            "events": [
                {
                    "event_id": event_id,
                    "version_id": version_id,
                    "actor": "AUTHOR",
                    "operation": "AUTHOR_ACCEPT",
                    "parent_version_ids": ["origin_version_" + generation_id],
                    "before_hash": _sha(origin_text),
                    "after_hash": _sha(accepted_text),
                    "content_after": accepted_text,
                    "source_generation_id": generation_id,
                }
            ],
            "versions": {},
            "segment": {},
        }

    lineages = {
        ("gen_probe_a", "seg_probe_a"): lineage(
            "gen_probe_a",
            "seg_probe_a",
            origin_a,
            accepted_a,
            "review_event_a",
            "review_version_a",
        ),
        ("gen_probe_b", "seg_probe_b"): lineage(
            "gen_probe_b",
            "seg_probe_b",
            origin_b,
            accepted_b,
            "review_event_b",
            "review_version_b",
        ),
    }

    original_path = ledger.authorship_ledger_path
    original_provenance_status = ledger.authorship_provenance_service.get_provenance_status
    original_continuity_read = ledger.approved_continuity_service.read_approved_continuity_document
    original_lineage_read = ledger.authorship_provenance_service.get_segment_lineage_records
    original_build = integration.authorship_ledger_service.build_authorship_ledger

    try:
        with tempfile.TemporaryDirectory(prefix="italus_primary39_ledger_") as temp_name:
            ledger_path = Path(temp_name) / "authorship_ledger.json"
            ledger.authorship_ledger_path = lambda project_id: ledger_path
            ledger.authorship_provenance_service.get_provenance_status = lambda project_id: {
                "initialized": True,
                "integrity_status": "ok",
                "integrity_error": "",
            }
            ledger.approved_continuity_service.read_approved_continuity_document = (
                lambda project_id: continuity
            )
            ledger.authorship_provenance_service.get_segment_lineage_records = (
                lambda project_id, generation_id, segment_id: lineages[
                    (generation_id, segment_id)
                ]
            )

            first = ledger.build_authorship_ledger("probe-project")
            suite.check(
                "P39-LEDGER-01",
                "Primary 38 builds from two Approved Continuity commits",
                first.get("ledger_built") is True and first.get("entry_count") == 2,
            )
            persisted_text = ledger_path.read_text(encoding="utf-8")
            suite.check(
                "P39-LEDGER-02",
                "Primary 38 ledger does not persist raw accepted/model prose",
                all(
                    value not in persisted_text
                    for value in (accepted_a, accepted_b, origin_a, origin_b)
                ),
            )
            first_hash = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
            second = ledger.build_authorship_ledger("probe-project")
            suite.check(
                "P39-LEDGER-03",
                "Primary 38 rebuild is idempotent",
                second.get("idempotent_replay") is True
                and hashlib.sha256(ledger_path.read_bytes()).hexdigest() == first_hash,
            )
            current = ledger.get_authorship_ledger_status("probe-project")
            suite.check(
                "P39-LEDGER-04",
                "Primary 38 reports current ledger against unchanged source",
                current.get("current") is True and current.get("stale") is False,
            )
            continuity["content_hash"] = "b" * 64
            stale = ledger.get_authorship_ledger_status("probe-project")
            suite.check(
                "P39-LEDGER-05",
                "Primary 38 detects stale ledger after continuity hash change",
                stale.get("current") is False and stale.get("stale") is True,
            )
            continuity["content_hash"] = "a" * 64

            saved_events = lineages[("gen_probe_a", "seg_probe_a")]["events"]
            lineages[("gen_probe_a", "seg_probe_a")]["events"] = []
            blocked = False
            try:
                ledger._compile_source("probe-project")
            except ledger.AuthorshipLedgerError as exc:
                blocked = exc.code == "AUTHORSHIP_LEDGER_AUTHOR_ACCEPT_EVENT_MISSING"
            finally:
                lineages[("gen_probe_a", "seg_probe_a")]["events"] = saved_events
            suite.check(
                "P39-LEDGER-06",
                "Primary 38 fails closed when AUTHOR_ACCEPT evidence is missing",
                blocked,
            )

            integration.authorship_ledger_service.build_authorship_ledger = (
                lambda project_id: {"status": "ok", "ledger_built": True}
            )
            refreshed = integration._refresh_authorship_ledger_after_continuity(
                "probe-project"
            )
            suite.check(
                "P39-LEDGER-07",
                "Approved Continuity integration can refresh ledger after commit",
                refreshed.get("status") == "ok",
            )

            def fail_build(project_id: str) -> dict[str, Any]:
                raise ledger.AuthorshipLedgerError(
                    "PROBE_LEDGER_FAIL",
                    "probe failure",
                )

            integration.authorship_ledger_service.build_authorship_ledger = fail_build
            failed = integration._refresh_authorship_ledger_after_continuity(
                "probe-project"
            )
            suite.check(
                "P39-LEDGER-08",
                "Ledger failure never rolls back durable Approved Continuity",
                failed.get("status") == "error"
                and failed.get("continuity_remains_committed") is True
                and failed.get("ledger_retry_is_idempotent") is True,
            )
    finally:
        ledger.authorship_ledger_path = original_path
        ledger.authorship_provenance_service.get_provenance_status = (
            original_provenance_status
        )
        ledger.approved_continuity_service.read_approved_continuity_document = (
            original_continuity_read
        )
        ledger.authorship_provenance_service.get_segment_lineage_records = (
            original_lineage_read
        )
        integration.authorship_ledger_service.build_authorship_ledger = original_build


def _run_gate38a_probe(suite: RegressionSuite) -> None:
    from app.services import provider_binding_service as binding
    from app.services import provider_config_service as config
    from app.services import provider_generation_receipt_service as receipts
    from app.services import provider_migration_service as migration

    class Manifest:
        project_name = "Primary 39 Gate 38A Probe"

    loader = migration.project_loader
    originals = {
        "validate_project_id": loader.validate_project_id,
        "load_manifest": loader.load_manifest,
        "project_dir": loader.project_dir,
        "get_provider_profile": config.get_provider_profile,
        "require_accepted_model_id": config.require_accepted_model_id,
        "usage_event_count": binding._usage_event_count,
        "execution_intent_lock_state": binding._execution_intent_lock_state,
        "receipt_execution_state": receipts.get_project_execution_lock_state,
    }

    try:
        with tempfile.TemporaryDirectory(prefix="italus_primary39_gate38a_") as temp_name:
            temp_root = Path(temp_name)
            project_id = "primary39-gate38a-probe"
            project_dir = temp_root / project_id
            project_dir.mkdir(parents=True)

            loader.validate_project_id = lambda value: str(value)
            loader.load_manifest = lambda value: Manifest()
            loader.project_dir = lambda value: temp_root / str(value)
            config.get_provider_profile = lambda provider_id: {
                "provider_id": str(provider_id),
                "model_id": "gpt-5.6-sol",
                "service_tier": "standard",
                "inference_scope": "global",
                "updated_at": "2026-09-07T00:00:00Z",
                "model_validation": {"accepted": True},
            }
            config.require_accepted_model_id = lambda provider_id, model_id: {
                "provider_id": provider_id,
                "model_id": model_id,
            }
            binding._usage_event_count = lambda value: 1
            binding._execution_intent_lock_state = lambda value: {
                "locked": False,
                "active_intent_count": 0,
                "statuses": {},
            }
            receipts.get_project_execution_lock_state = lambda value: {
                "locked": False,
                "active_intent_count": 0,
                "statuses": {},
            }

            old_binding = {
                "schema_version": binding.PROVIDER_BINDING_SCHEMA_VERSION,
                "project_id": project_id,
                "project_name": "Primary 39 Gate 38A Probe",
                "provider_id": "openai",
                "model_id": "gpt-5.6-terra",
                "service_tier": "standard",
                "inference_scope": "global",
                "binding_instance_id": "bind_old_lineage",
                "previous_binding_instance_id": None,
                "provider_profile_model_id_at_binding": "gpt-5.6-terra",
                "provider_profile_updated_at": "2026-09-06T00:00:00Z",
                "model_selection_source": "provider_profile_default",
                "lock_policy": binding.LOCK_POLICY,
                "created_at": "2026-09-06T00:00:00Z",
                "updated_at": "2026-09-06T00:00:00Z",
            }
            binding.binding_path(project_id).write_text(
                json.dumps(old_binding, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            provenance = project_dir / "provenance" / "origins"
            provenance.mkdir(parents=True)
            origin_path = provenance / "origin_probe.json"
            origin_path.write_text('{"immutable":true}\n', encoding="utf-8")
            origin_hash_before = hashlib.sha256(origin_path.read_bytes()).hexdigest()

            result = migration.migrate_project_provider_model(
                project_id,
                idempotency_key="primary39-probe-key",
                expected_current_binding_instance_id="bind_old_lineage",
                target_provider_id="openai",
                target_model_id="gpt-5.6-sol",
            )
            new_binding = result["binding"]["binding"]
            suite.check(
                "P39-G38A-01",
                "Gate 38A creates a distinct future binding lineage",
                result.get("accepted") is True
                and new_binding.get("binding_instance_id") != "bind_old_lineage",
            )
            suite.equal(
                "P39-G38A-02",
                "Gate 38A new binding points to prior binding instance",
                new_binding.get("previous_binding_instance_id"),
                "bind_old_lineage",
            )
            suite.equal(
                "P39-G38A-03",
                "Gate 38A marks binding source as controlled migration",
                new_binding.get("model_selection_source"),
                "gate38a_controlled_migration",
            )
            record = result["migration"]
            suite.check(
                "P39-G38A-04",
                "Gate 38A performs no provider call and requires no credential",
                record["execution"].get("provider_called") is False
                and record["execution"].get("credential_required_for_migration") is False,
            )
            suite.equal(
                "P39-G38A-05",
                "Gate 38A preserves MODEL-origin provenance bytes",
                hashlib.sha256(origin_path.read_bytes()).hexdigest(),
                origin_hash_before,
            )
            replay = migration.migrate_project_provider_model(
                project_id,
                idempotency_key="primary39-probe-key",
                expected_current_binding_instance_id="bind_old_lineage",
                target_provider_id="openai",
                target_model_id="gpt-5.6-sol",
            )
            suite.check(
                "P39-G38A-06",
                "Gate 38A exact replay is idempotent",
                replay.get("idempotent_replay") is True,
            )

            normal_locked = False
            try:
                binding.save_project_model_override(
                    project_id,
                    model_id="gpt-5.6-terra",
                )
            except binding.ProviderBindingLockedError:
                normal_locked = True
            suite.check(
                "P39-G38A-07",
                "Normal post-usage model mutation remains locked",
                normal_locked,
            )

            receipts.get_project_execution_lock_state = lambda value: {
                "locked": True,
                "active_intent_count": 1,
                "statuses": {"prepared": 1},
            }
            active_blocked = False
            try:
                migration.migrate_project_provider_model(
                    project_id,
                    idempotency_key="primary39-active-execution-negative",
                    expected_current_binding_instance_id=new_binding[
                        "binding_instance_id"
                    ],
                    target_provider_id="openai",
                    target_model_id="gpt-5.6-luna",
                )
            except migration.ProviderMigrationConflictError as exc:
                active_blocked = exc.code == "ACTIVE_EXECUTION_INTENT"
            suite.check(
                "P39-G38A-08",
                "Gate 38A fails closed while provider execution is active",
                active_blocked,
            )
    finally:
        loader.validate_project_id = originals["validate_project_id"]
        loader.load_manifest = originals["load_manifest"]
        loader.project_dir = originals["project_dir"]
        config.get_provider_profile = originals["get_provider_profile"]
        config.require_accepted_model_id = originals["require_accepted_model_id"]
        binding._usage_event_count = originals["usage_event_count"]
        binding._execution_intent_lock_state = originals[
            "execution_intent_lock_state"
        ]
        receipts.get_project_execution_lock_state = originals[
            "receipt_execution_state"
        ]


def _run_suite(repo: Path) -> RegressionSuite:
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from app.api.routes import project as project_routes
    from app.services import approved_continuity_integration_service
    from app.services import approved_continuity_service
    from app.services import author_voice_projection_service
    from app.services import author_voice_provenance_gate_service
    from app.services import author_voice_store_service
    from app.services import author_review_service
    from app.services import authorship_classification_service
    from app.services import authorship_ledger_service
    from app.services import authorship_provenance_service
    from app.services import book_plan_service
    from app.services import book_scope_service
    from app.services import chapter_plan_service
    from app.services import generation_control_service
    from app.services import generation_service
    from app.services import planner_intent_model_adapter
    from app.services import planner_query_service
    from app.services import project_runtime_storage_service
    from app.services import provider_binding_service
    from app.services import provider_execution_service
    from app.services import provider_generation_receipt_service
    from app.services import provider_migration_service
    from app.services import provider_usage_service
    from app.services import story_control_service

    suite = RegressionSuite()

    critical_files = [
        "app/projects/project_context.py",
        "app/services/project_runtime_storage_service.py",
        "app/services/canon_record_identity_service.py",
        "app/services/canon_reference_service.py",
        "app/services/canon_index_service.py",
        "app/services/book_scope_service.py",
        "app/services/book_plan_service.py",
        "app/services/chapter_plan_service.py",
        "app/services/story_control_service.py",
        "app/services/generation_control_service.py",
        "app/services/generation_service.py",
        "app/prompt_builder.py",
        "app/services/provider_binding_service.py",
        "app/services/provider_execution_service.py",
        "app/services/provider_generation_receipt_service.py",
        "app/services/provider_usage_service.py",
        "app/services/authorship_provenance_service.py",
        "app/services/author_review_service.py",
        "app/services/authorship_classification_service.py",
        "app/services/approved_continuity_service.py",
        "app/services/approved_continuity_integration_service.py",
        "app/services/author_voice_provenance_gate_service.py",
        "app/services/author_voice_store_service.py",
        "app/services/author_voice_projection_service.py",
        "app/services/authorship_ledger_service.py",
        "app/services/provider_migration_service.py",
        "app/api/routes/project.py",
    ]
    suite.check(
        "P39-FILES-01",
        "All migration-critical control-plane files are present",
        all((repo / relative_path).is_file() for relative_path in critical_files),
    )
    syntax_ok = True
    syntax_error = ""
    for relative_path in critical_files:
        try:
            ast.parse(_source(repo, relative_path))
        except Exception as exc:
            syntax_ok = False
            syntax_error = f"{relative_path}: {exc}"
            break
    suite.check(
        "P39-FILES-02",
        "All migration-critical Python files parse",
        syntax_ok,
        syntax_error,
    )

    runtime_source = _source(repo, "app/services/project_runtime_storage_service.py")
    suite.check(
        "P39-RUNTIME-01",
        "Project runtime storage explicitly blocks legacy data copy",
        '"legacy_copy": "never"' in runtime_source
        and '"copy_legacy_data": "blocked_until_migration_design"' in runtime_source,
    )
    suite.check(
        "P39-RUNTIME-02",
        "Runtime storage remains bounded to the project runtime directory",
        "context.runtime_data_dir.resolve()" in runtime_source
        and 'if project_dir not in runtime_dir.parents' in runtime_source
        and 'expected_name = "runtime"' in runtime_source,
    )

    scope_contract = book_scope_service.get_book_scope_contract()
    suite.equal(
        "P39-PLAN-01",
        "Book Scope storage is project-local",
        scope_contract["document"]["storage_scope"],
        "project_local",
    )
    suite.check(
        "P39-PLAN-02",
        "Book Scope approval requires current sources",
        scope_contract["freshness"]["approval_requires_current_sources"] is True,
    )
    plan_contract = book_plan_service.get_book_plan_contract()
    suite.equal(
        "P39-PLAN-03",
        "Book Plan storage is project-local",
        plan_contract["document"]["storage_scope"],
        "project_local",
    )
    suite.check(
        "P39-PLAN-04",
        "Book Plan never guesses unresolved legacy references",
        "never guessed"
        in plan_contract["reference_contract"]["unresolved_legacy"].lower(),
    )
    chapter_contract = chapter_plan_service.get_chapter_plan_contract()
    suite.equal(
        "P39-PLAN-05",
        "Chapter Plan storage is project-local",
        chapter_contract["document"]["storage_scope"],
        "project_local",
    )
    story_contract = story_control_service.get_story_control_contract()
    suite.check(
        "P39-PLAN-06",
        "Story Controls cannot mutate master Canon",
        story_contract["capabilities"]["master_canon_mutation"] is False,
    )

    generation_contract = generation_control_service.get_generation_control_contract()
    suite.equal(
        "P39-GEN-01",
        "Generation readiness contract is healthy",
        generation_contract.get("status"),
        "ok",
    )
    required_generation_dimensions = {
        "project_loaded",
        "runtime_storage_ready",
        "book_scope_current_approved",
        "book_plan_current_approved",
        "chapter_plan_current_ready",
        "story_controls_valid",
        "chapter_knowledge_pack_current",
        "prompt_builder_project_local_routing_ready",
        "provider_execution_ready",
        "validator_ready",
        "provenance_capture_ready",
        "author_review_persistence_ready",
        "approved_continuity_commit_path_ready",
    }
    suite.check(
        "P39-GEN-02",
        "Generation readiness spans migrated planning through continuity",
        required_generation_dimensions.issubset(
            set(generation_contract.get("readiness_dimensions") or [])
        ),
    )
    suite.check(
        "P39-GEN-03",
        "Migrated Prompt Builder and provider execution readiness are enabled",
        generation_contract["patch_29_locks"][
            "prompt_builder_project_local_routing_ready"
        ]
        is True
        and generation_contract["patch_29_locks"]["provider_execution_ready"] is True,
    )

    generation_source = _source(repo, "app/services/generation_service.py")
    prompt_source = _source(repo, "app/prompt_builder.py")
    suite.check(
        "P39-GEN-04",
        "Generation Request uses project-local Prompt Builder entry point",
        "prompt_builder.build_project_local_generation_prompt(" in generation_source,
    )
    suite.check(
        "P39-GEN-05",
        "Generation Request does not import legacy project_runner or ai_runner",
        "app.project_runner" not in generation_source
        and "app.ai_runner" not in generation_source,
    )
    prompt_names = _function_names(
        prompt_source,
        "build_project_local_generation_prompt",
    )
    forbidden_prompt_names = {
        "load_core_pack",
        "load_generation_pack",
        "load_book_pack",
        "CANON_PACKS_DIR",
        "build_generation_prompt",
    }
    suite.check(
        "P39-GEN-06",
        "Project-local Prompt Builder has no legacy-pack fallback calls",
        not (prompt_names & forbidden_prompt_names),
        details=f"forbidden_names_present={sorted(prompt_names & forbidden_prompt_names)}",
    )
    suite.check(
        "P39-GEN-07",
        "Project-local Prompt Builder marker is present",
        "PROJECT_LOCAL_PROMPT_BUILDER_MARKER" in prompt_source
        and "project-local" in prompt_source.lower(),
    )

    provider_execution_source = _source(
        repo,
        "app/services/provider_execution_service.py",
    )
    suite.check(
        "P39-PROVIDER-01",
        "Provider execution service remains activated through migrated boundary",
        provider_execution_service.PROVIDER_EXECUTION_ACTIVATION_READY is True,
    )
    suite.check(
        "P39-PROVIDER-02",
        "Provider execution does not import legacy project_runner",
        "project_runner" not in provider_execution_source,
    )
    suite.check(
        "P39-PROVIDER-03",
        "Provider receipt service exposes create-once receipt path",
        hasattr(provider_generation_receipt_service, "write_receipt_once"),
    )
    suite.check(
        "P39-PROVIDER-04",
        "Provider receipt service exposes execution fingerprint",
        hasattr(provider_generation_receipt_service, "execution_fingerprint"),
    )
    suite.check(
        "P39-PROVIDER-05",
        "Provider usage service exposes append/read accounting boundaries",
        hasattr(provider_usage_service, "append_usage_event"),
    )
    suite.check(
        "P39-PROVIDER-06",
        "Normal binding service retains usage-aware lock policy",
        "usage" in provider_binding_service.LOCK_POLICY.lower(),
    )
    credential_backend_source = _source(
        repo,
        "app/services/provider_credential_backends.py",
    )
    suite.check(
        "P39-PROVIDER-07",
        "Selected credential backend performs no cross-backend fallback",
        "No fallback is attempted" in credential_backend_source,
    )

    planner_contract = planner_query_service.get_planner_query_contract()
    suite.check(
        "P39-PLANNER-01",
        "Planner query contract has no cloud fallback implementation",
        planner_contract.get("intent_model", {}).get("cloud_fallback_implemented") is False,
    )
    adapter_contract = planner_intent_model_adapter.get_local_intent_model_status()
    suite.check(
        "P39-PLANNER-02",
        "Planner intent adapter is loopback/local only with no cloud fallback",
        adapter_contract.get("cloud_fallback_configured") is False
        and adapter_contract.get("endpoint_is_local") is True,
        details=json.dumps(adapter_contract, sort_keys=True),
    )

    provenance_contract = authorship_provenance_service.get_provenance_contract()
    suite.check(
        "P39-PROV-01",
        "Provenance origin is immutable and events are append-only",
        provenance_contract["storage_contract"]["origin_mutability"]
        == "immutable_create_once"
        and provenance_contract["storage_contract"]["event_mutability"]
        == "append_only",
    )
    suite.check(
        "P39-PROV-02",
        "Provenance records evidence without legal authorship scoring",
        provenance_contract["authority"]["scores_authorship"] is False
        and provenance_contract["authority"]["declares_legal_copyrightability"]
        is False,
    )

    review_source = _source(repo, "app/services/author_review_service.py")
    suite.check(
        "P39-REVIEW-01",
        "Author Review preserves explicit ACCEPT/EDIT/REJECT actions",
        all(
            marker in review_source
            for marker in ('ACTION_ACCEPT = "accept"', 'ACTION_EDIT = "edit"', 'ACTION_REJECT = "reject"')
        ),
    )

    classification = authorship_classification_service.get_classification_contract()
    suite.check(
        "P39-CLASS-01",
        "Primary 35 HCCS remains an internal provenance metric",
        classification["authority"]["hccs_internal_provenance_metric"] is True
        and classification["authority"]["hccs_is_legal_authorship_percentage"] is False,
    )
    suite.check(
        "P39-CLASS-02",
        "Primary 35 does not write Continuity, Author Voice, or ledger",
        classification["authority"]["writes_approved_continuity"] is False
        and classification["authority"]["updates_author_voice"] is False
        and classification["authority"]["writes_authorship_ledger"] is False,
    )
    suite.check(
        "P39-CLASS-03",
        "Model-to-model rewriting earns no human expressive credit",
        "model_to_model_rewriting_receives_no_human_expressive_credit"
        in classification["anti_skew_rules"],
    )

    continuity = approved_continuity_service.get_approved_continuity_contract()
    suite.equal(
        "P39-CONT-01",
        "Approved Continuity requires terminal AUTHOR_ACCEPT",
        continuity["required_terminal_operation"],
        "AUTHOR_ACCEPT",
    )
    suite.check(
        "P39-CONT-02",
        "Approved Continuity owns story-state write but not provider/model mutation",
        continuity["authority"]["writes_approved_continuity"] is True
        and continuity["authority"]["mutates_provider_binding"] is False
        and continuity["authority"]["calls_provider"] is False,
    )
    integration_contract = (
        approved_continuity_integration_service.get_approved_continuity_integration_contract()
    )
    suite.check(
        "P39-CONT-03",
        "Primary 38 ledger refresh is downstream of durable Continuity",
        integration_contract["authority"]["writes_authorship_ledger"] is True
        and integration_contract["authority"]["authorship_ledger_update_policy"][
            "ledger_failure_rolls_back_continuity"
        ]
        is False,
    )

    voice_gate = (
        author_voice_provenance_gate_service.get_author_voice_provenance_gate_contract()
    )
    suite.check(
        "P39-VOICE-01",
        "Author Voice gate rejects untouched/light/moderate MODEL prose",
        voice_gate["policy"]["untouched_model_prose_eligible"] is False
        and voice_gate["policy"]["light_model_prose_edit_eligible"] is False
        and voice_gate["policy"]["moderate_model_prose_edit_eligible"] is False,
    )
    suite.check(
        "P39-VOICE-02",
        "Author Voice gate requires classification, AUTHOR_ACCEPT and Continuity",
        voice_gate["policy"]["requires_terminal_author_accept"] is True
        and voice_gate["policy"]["requires_approved_continuity_commit"] is True
        and voice_gate["policy"]["requires_primary35_classification"] is True,
    )
    voice_store = author_voice_store_service.get_author_voice_store_contract()
    suite.equal(
        "P39-VOICE-03",
        "Author Voice store remains application-author-level and cross-project",
        voice_store["scope"],
        "application_author_level_cross_project",
    )
    suite.check(
        "P39-VOICE-04",
        "Author Voice store requires Primary 37A eligibility and cannot mutate Canon",
        voice_store["authority"]["requires_primary37a_eligibility"] is True
        and voice_store["authority"]["mutates_canon"] is False,
    )
    projection = author_voice_projection_service.get_author_voice_projection_contract()
    suite.check(
        "P39-VOICE-05",
        "Raw Author Voice prose is never injected into prompt",
        projection["source"]["raw_prose_in_prompt"] is False,
    )
    suite.equal(
        "P39-VOICE-06",
        "Author Voice prompt authority remains soft style only",
        projection["authority"]["prompt_authority"],
        "soft_style_preference_only",
    )
    suite.equal(
        "P39-VOICE-07",
        "Author Voice precedence remains below Canon/controls/intent/character voice",
        projection["precedence"],
        [
            "hard_canon_story_legality",
            "story_control_required_facts_and_prohibitions",
            "chapter_narrative_intent",
            "character_voice",
            "author_voice_style",
        ],
    )

    ledger_contract = authorship_ledger_service.get_authorship_ledger_contract()
    suite.equal(
        "P39-LEDGER-C01",
        "Primary 38 ledger source of truth is Approved Continuity",
        ledger_contract["source_of_truth"]["accepted_manuscript"],
        "Primary 36 Approved Continuity",
    )
    suite.check(
        "P39-LEDGER-C02",
        "Primary 38 ledger excludes rejected/uncommitted text",
        ledger_contract["rejected_or_uncommitted_text_in_manuscript_ledger"] is False,
    )
    suite.check(
        "P39-LEDGER-C03",
        "Primary 38 ledger does not make legal authorship determinations",
        ledger_contract["authority"]["makes_legal_authorship_determination"] is False,
    )
    suite.check(
        "P39-LEDGER-C04",
        "Primary 38 remains separate from Gate 38A",
        ledger_contract["authority"]["implements_gate_38a"] is False,
    )

    migration_contract = provider_migration_service.get_provider_migration_contract()
    suite.equal(
        "P39-G38A-C01",
        "Controlled provider/model migration identifies Gate 38A",
        migration_contract["gate"],
        "38A",
    )
    migration_authority = migration_contract["authority"]
    suite.check(
        "P39-G38A-C02",
        "Gate 38A creates new binding lineage and preserves prior snapshot",
        migration_authority["changes_future_provider_binding"] is True
        and migration_authority["creates_new_binding_instance"] is True
        and migration_authority["preserves_previous_binding_snapshot"] is True,
    )
    suite.check(
        "P39-G38A-C03",
        "Gate 38A preserves usage/receipt/pricing/MODEL-origin history",
        migration_authority["preserves_historical_usage"] is True
        and migration_authority["preserves_historical_receipts"] is True
        and migration_authority["preserves_historical_pricing_lineage"] is True
        and migration_authority["preserves_model_origin_provenance"] is True,
    )
    suite.check(
        "P39-G38A-C04",
        "Gate 38A performs no provider call and requires no live credential",
        migration_authority["calls_provider"] is False
        and migration_authority["requires_live_provider_credential"] is False,
    )
    migration_source = _source(repo, "app/services/provider_migration_service.py")
    suite.check(
        "P39-G38A-C05",
        "Gate 38A service does not import provider execution or credential mutation",
        "provider_execution_service" not in migration_source
        and "provider_credential_service" not in migration_source,
    )

    routes = _route_signatures(project_routes.router)
    required_routes = {
        ("GET", "/api/project/{project_id}/generation-readiness"),
        ("POST", "/api/project/{project_id}/generation-request/build"),
        ("POST", "/api/provider/projects/{project_id}/generation/execute"),
        ("GET", "/api/project/provenance/classification/contract"),
        ("POST", "/api/provider/projects/{project_id}/generation/{generation_id}/review"),
        ("POST", "/api/provider/projects/{project_id}/generation/{generation_id}/approved-continuity/commit"),
        ("GET", "/api/project/provenance/ledger/contract"),
        ("POST", "/api/project/{project_id}/provenance/ledger/build"),
        ("GET", "/api/provider/projects/{project_id}/migration/contract"),
        ("GET", "/api/provider/projects/{project_id}/migration/history"),
        ("POST", "/api/provider/projects/{project_id}/migration"),
    }
    suite.check(
        "P39-ROUTE-01",
        "Migrated generation/authorship/Gate38A API surfaces are registered",
        required_routes.issubset(routes),
        details=f"missing={sorted(required_routes - routes)}",
    )

    project_context_source = _source(repo, "app/projects/project_context.py")
    suite.check(
        "P39-NOLEGACY-01",
        "Legacy root reference mode remains isolated to project setup/context compatibility",
        "legacy_root_reference" in project_context_source,
    )
    suite.check(
        "P39-NOLEGACY-02",
        "Migrated generation service contains no legacy-root compatibility access",
        "legacy_root_reference" not in generation_source
        and "legacy_canon_" not in generation_source,
    )
    suite.check(
        "P39-NOLEGACY-03",
        "Migrated project-local Prompt Builder does not use legacy context attributes",
        not any(
            name.startswith("legacy_")
            for name in prompt_names
        ),
        details=f"legacy_names={sorted(name for name in prompt_names if name.startswith('legacy_'))}",
    )
    suite.check(
        "P39-NOLEGACY-04",
        "Gate 38A never falls back to live execution to migrate lineage",
        "execute_provider_generation" not in migration_source
        and "generate_with_ai" not in migration_source,
    )

    _run_primary38_probe(suite)
    _run_gate38a_probe(suite)

    return suite


def main() -> int:
    repo = _repo_root()
    try:
        suite = _run_suite(repo)
    except Exception as exc:
        print("PRIMARY39 REGRESSION HARNESS ERROR")
        print(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 2

    for result in suite.results:
        suffix = f" :: {result['details']}" if result["details"] else ""
        print(
            f"{result['status']} {result['id']} - {result['description']}{suffix}"
        )

    total = len(suite.results)
    print("")
    print(f"PRIMARY39 MARKER: {PRIMARY39_MARKER}")
    print(f"PRIMARY39 SCHEMA: {PRIMARY39_SCHEMA_VERSION}")
    print(f"PRIMARY39 TOTAL: {total}")
    print(f"PRIMARY39 PASS: {suite.passed}")
    print(f"PRIMARY39 FAIL: {suite.failed}")

    if suite.failed:
        print("PRIMARY39 REGRESSION: FAIL")
        return 1

    print("PRIMARY39 REGRESSION: PASS")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    print("LEGACY GENERATION FALLBACK: NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
