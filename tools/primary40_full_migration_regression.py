from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable

PRIMARY40_MARKER = "primary40-full-migration-regression-v1"
PRIMARY40_SCHEMA_VERSION = "primary40_full_migration_regression_v1"


class RegressionSuite:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def check(
        self,
        test_id: str,
        description: str,
        condition: bool,
        details: str = "",
    ) -> None:
        passed = bool(condition)
        self.results.append(
            {
                "id": test_id,
                "description": description,
                "status": "PASS" if passed else "FAIL",
                "details": str(details or ""),
            }
        )

    def equal(
        self,
        test_id: str,
        description: str,
        actual: Any,
        expected: Any,
    ) -> None:
        self.check(
            test_id,
            description,
            actual == expected,
            details=f"actual={actual!r}; expected={expected!r}",
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


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return "ABSENT"
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(_sha256_path(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _route_signatures(router: Any) -> set[tuple[str, str]]:
    signatures: set[tuple[str, str]] = set()
    for route in router.routes:
        path = str(getattr(route, "path", "") or "")
        for method in set(getattr(route, "methods", set()) or set()):
            signatures.add((str(method).upper(), path))
    return signatures


def _run_tool(
    repo: Path,
    relative_path: str,
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, relative_path],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _header_request(path: str, idempotency_key: str | None):
    from starlette.requests import Request

    headers: list[tuple[bytes, bytes]] = []
    if idempotency_key is not None:
        headers.append((b"idempotency-key", idempotency_key.encode("utf-8")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 40000),
        "server": ("127.0.0.1", 8000),
    }
    return Request(scope)


def _run_suite(repo: Path) -> RegressionSuite:
    suite = RegressionSuite()

    required_files = {
        "app/services/generation_control_service.py",
        "app/services/generation_service.py",
        "app/services/provider_execution_service.py",
        "app/services/workspace_service.py",
        "app/services/provider_config_service.py",
        "app/services/provider_workspace_service.py",
        "app/services/provider_binding_service.py",
        "app/services/provider_preflight_service.py",
        "app/services/legacy_production_isolation_service.py",
        "app/api/routes/project.py",
        "frontend/workspace.js",
        "frontend/workspace.css",
        "frontend/assets/themes/themes.css",
        "frontend/js/provider_settings.js",
        "tools/primary39_full_migration_regression.py",
        "tools/primary40c_legacy_production_isolation.py",
    }
    missing_files = sorted(path for path in required_files if not (repo / path).is_file())
    suite.check(
        "P40-FILES-01",
        "All Primary 40 migration-critical files are present",
        not missing_files,
        details=f"missing={missing_files}",
    )

    parse_targets = [
        "app/services/generation_control_service.py",
        "app/services/generation_service.py",
        "app/services/provider_execution_service.py",
        "app/services/workspace_service.py",
        "app/services/provider_config_service.py",
        "app/services/provider_workspace_service.py",
        "app/services/provider_binding_service.py",
        "app/services/provider_preflight_service.py",
        "app/services/legacy_production_isolation_service.py",
        "app/api/routes/project.py",
    ]
    parse_errors: list[str] = []
    for relative_path in parse_targets:
        try:
            ast.parse(_source(repo, relative_path), filename=relative_path)
        except SyntaxError as exc:
            parse_errors.append(f"{relative_path}: {exc}")
    suite.check(
        "P40-FILES-02",
        "All Primary 40 Python production files parse",
        not parse_errors,
        details="; ".join(parse_errors),
    )

    from fastapi import HTTPException
    from app.api.routes import project
    from app.services import generation_control_service
    from app.services import generation_service
    from app.services import legacy_production_isolation_service
    from app.services import provider_binding_service
    from app.services import provider_config_service
    from app.services import provider_execution_service
    from app.services import provider_preflight_service
    from app.services import workspace_service

    # 40A — production authority and request contract.
    suite.check(
        "P40-40A-01",
        "Primary 40A production runtime cutover is enabled",
        generation_control_service.PRODUCTION_RUNTIME_CUTOVER_READY is True,
    )
    suite.check(
        "P40-40A-02",
        "Provider execution readiness is enabled",
        generation_control_service.PROVIDER_EXECUTION_READY is True,
    )
    suite.check(
        "P40-40A-03",
        "Provider execution engine activation is enabled",
        provider_execution_service.PROVIDER_EXECUTION_ACTIVATION_READY is True,
    )

    readiness = generation_control_service.get_generation_control_status(
        "italus-saga",
        book_number=1,
        chapter_number=1,
    )
    suite.check(
        "P40-40A-04",
        "Italus generation readiness uses the project-local control plane",
        readiness.get("generation_enabled") is True
        and readiness.get("provider_execution_enabled") is True
        and (readiness.get("production_runtime") or {}).get("control_plane")
        == "project_local_primary40a"
        and (readiness.get("production_runtime") or {}).get("legacy_fallback_allowed")
        is False,
        details=f"status={readiness.get('status')!r}; blockers={readiness.get('blockers')!r}",
    )
    suite.check(
        "P40-40A-05",
        "Italus Book 1 Chapter 1 currently passes Generation Readiness",
        readiness.get("ready") is True and not list(readiness.get("blockers") or []),
        details=f"status={readiness.get('status')!r}; blockers={readiness.get('blockers')!r}",
    )

    envelope = generation_service.build_generation_request_envelope(
        "italus-saga",
        book_number=1,
        chapter_number=1,
    )
    execution = envelope.get("execution") if isinstance(envelope, dict) else {}
    suite.check(
        "P40-40A-06",
        "Generation Request is authorized only by the Primary 40A execution contract",
        isinstance(execution, dict)
        and execution.get("provider_execution_allowed") is True
        and execution.get("control_plane") == "project_local_primary40a"
        and execution.get("legacy_fallback_allowed") is False,
        details=f"execution={execution!r}",
    )

    original_builder = generation_service.build_generation_request_envelope
    generation_service.build_generation_request_envelope = lambda *args, **kwargs: {
        "execution": {
            "provider_execution_allowed": False,
            "control_plane": "project_local_primary40a",
            "legacy_fallback_allowed": False,
        }
    }
    try:
        blocked_code = ""
        try:
            provider_execution_service.execute_provider_generation(
                "italus-saga",
                book_number=1,
                chapter_number=1,
                idempotency_key="p40-negative-runtime-contract",
            )
        except provider_execution_service.ProviderExecutionError as exc:
            blocked_code = str(exc.code)
        suite.equal(
            "P40-40A-07",
            "Provider execution fails closed before provider I/O when runtime authorization is absent",
            blocked_code,
            "PRODUCTION_RUNTIME_NOT_READY",
        )
    finally:
        generation_service.build_generation_request_envelope = original_builder

    # 40R1 — workspace capability truth.
    bootstrap = workspace_service.get_workspace_bootstrap("italus-saga")
    capability = dict(bootstrap.get("production_runtime_capability") or {})
    suite.check(
        "P40-40R1-01",
        "Workspace production runtime capability is ready",
        bootstrap.get("runtime_ready") is True
        and bootstrap.get("generation_enabled") is True
        and bootstrap.get("validation_enabled") is True
        and bootstrap.get("exports_enabled") is False,
        details=(
            f"runtime_ready={bootstrap.get('runtime_ready')!r}; "
            f"generation_enabled={bootstrap.get('generation_enabled')!r}; "
            f"validation_enabled={bootstrap.get('validation_enabled')!r}; "
            f"exports_enabled={bootstrap.get('exports_enabled')!r}"
        ),
    )
    suite.check(
        "P40-40R1-02",
        "Workspace capability preserves position readiness and disables legacy fallback",
        capability.get("control_plane") == "project_local_primary40a"
        and capability.get("generation_capability_available") is True
        and capability.get("position_readiness_required") is True
        and capability.get("provider_credential_readiness_deferred") is True
        and capability.get("legacy_fallback_allowed") is False,
        details=f"capability={capability!r}",
    )

    gate_status = {
        str(item.get("id") or ""): str(item.get("status") or "")
        for item in list(bootstrap.get("runtime_readiness_gates") or [])
        if isinstance(item, dict)
    }
    expected_ready_gates = {
        "runtime_storage",
        "prompt_routing",
        "provider_execution",
        "validation_runtime",
        "author_review",
        "approved_continuity",
        "generation_control",
    }
    suite.check(
        "P40-40R1-03",
        "Workspace migrated capability gates are ready while export remains separate",
        all(gate_status.get(item) == "ready" for item in expected_ready_gates)
        and gate_status.get("export_pipeline") == "blocked",
        details=f"gates={gate_status!r}",
    )

    # 40R2A — provider capability/settings truth.
    provider_capability = provider_config_service.provider_execution_capability()
    suite.check(
        "P40-40R2A-01",
        "Provider platform capability is available without implying credential readiness",
        provider_capability.get("provider_execution_allowed") is True
        and provider_capability.get("control_plane") == "project_local_primary40a"
        and provider_capability.get("credential_readiness_required") is True
        and provider_capability.get("project_preflight_required") is True
        and provider_capability.get("position_readiness_required") is True
        and provider_capability.get("legacy_fallback_allowed") is False,
        details=f"capability={provider_capability!r}",
    )

    catalog = provider_config_service.provider_catalog()
    providers = {
        str(item.get("provider_id") or ""): item
        for item in list(catalog.get("providers") or [])
        if isinstance(item, dict)
    }
    suite.check(
        "P40-40R2A-02",
        "Direct Anthropic/OpenAI capability is enabled and OpenRouter remains disabled",
        providers.get("anthropic", {}).get("execution_enabled") is True
        and providers.get("openai", {}).get("execution_enabled") is True
        and providers.get("openrouter", {}).get("execution_enabled") is False,
        details={
            name: providers.get(name, {}).get("execution_enabled")
            for name in ("anthropic", "openai", "openrouter")
        }.__repr__(),
    )

    inventory = project.get_provider_profiles()
    suite.check(
        "P40-40R2A-03",
        "Provider profile inventory reports platform capability while remaining non-executing",
        inventory.get("provider_execution_allowed") is True
        and (inventory.get("execution") or {}).get("provider_execution_allowed") is True
        and inventory.get("inventory_operation_executes_provider") is False,
        details=f"execution={inventory.get('execution')!r}",
    )

    # 40R2B — binding/preflight operation semantics.
    binding = provider_binding_service.get_project_provider_binding("italus-saga")
    binding_execution = dict(binding.get("execution") or {})
    suite.check(
        "P40-40R2B-01",
        "Binding projects platform capability but the binding operation never executes a provider",
        binding_execution.get("provider_execution_allowed") is True
        and binding_execution.get("binding_operation_executes_provider") is False
        and binding_execution.get("project_preflight_required") is True
        and binding_execution.get("position_readiness_required") is True
        and binding_execution.get("legacy_fallback_allowed") is False,
        details=f"execution={binding_execution!r}",
    )

    preflight = provider_preflight_service._finalize(
        project_id="italus-saga",
        checked_at="2026-09-19T00:00:00Z",
        checks=[],
        binding=binding.get("binding"),
        credential=None,
        pricing=None,
        pricing_freshness=None,
        pricing_version_sha256=None,
        provider_probe=None,
    )
    preflight_execution = dict(preflight.get("execution") or {})
    suite.check(
        "P40-40R2B-02",
        "Preflight separates metadata probing from text generation and usage",
        preflight_execution.get("provider_execution_allowed") is True
        and preflight_execution.get("preflight_operation_executes_generation") is False
        and preflight_execution.get("provider_metadata_probe_may_execute") is True
        and preflight_execution.get("generation_attempted") is False
        and preflight_execution.get("usage_recorded") is False
        and preflight_execution.get("legacy_fallback_allowed") is False,
        details=f"execution={preflight_execution!r}",
    )

    old_provider_ready = generation_control_service.PROVIDER_EXECUTION_READY
    generation_control_service.PROVIDER_EXECUTION_READY = False
    try:
        blocked_capability = provider_config_service.provider_execution_capability()
        blocked_binding = provider_binding_service.get_project_provider_binding("italus-saga")
        blocked_preflight = provider_preflight_service._finalize(
            project_id="italus-saga",
            checked_at="2026-09-19T00:00:00Z",
            checks=[],
            binding=binding.get("binding"),
            credential=None,
            pricing=None,
            pricing_freshness=None,
            pricing_version_sha256=None,
            provider_probe=None,
        )
        blocked_workspace = workspace_service._workspace_production_runtime_capability(
            {
                "status": "initialized",
                "initialized": True,
                "required_files_present": True,
            },
            read_only=False,
        )
        suite.check(
            "P40-40R2B-03",
            "Provider and Workspace capability surfaces fail closed together",
            blocked_capability.get("provider_execution_allowed") is False
            and (blocked_binding.get("execution") or {}).get("provider_execution_allowed") is False
            and (blocked_preflight.get("execution") or {}).get("provider_execution_allowed") is False
            and blocked_workspace.get("generation_capability_available") is False
            and blocked_workspace.get("generation_enabled") is False,
        )
    finally:
        generation_control_service.PROVIDER_EXECUTION_READY = old_provider_ready

    # API execution/idempotency wiring — provider call is replaced by a sentinel.
    payload = project.ProviderGenerationExecuteRequest(book_number=1, chapter_number=1)
    original_execute = provider_execution_service.execute_provider_generation
    observed_calls: list[dict[str, Any]] = []

    def _sentinel_execute(
        project_id: str,
        *,
        book_number: int,
        chapter_number: int,
        idempotency_key: str,
        **_: Any,
    ) -> dict[str, Any]:
        observed_calls.append(
            {
                "project_id": project_id,
                "book_number": book_number,
                "chapter_number": chapter_number,
                "idempotency_key": idempotency_key,
            }
        )
        return {
            "status": "sentinel",
            "generation_id": "p40-regression-sentinel",
        }

    provider_execution_service.execute_provider_generation = _sentinel_execute
    try:
        missing_status = None
        try:
            project.execute_project_provider_generation(
                "italus-saga",
                payload,
                _header_request(
                    "/api/provider/projects/italus-saga/generation/execute",
                    None,
                ),
            )
        except HTTPException as exc:
            missing_status = exc.status_code

        long_status = None
        try:
            project.execute_project_provider_generation(
                "italus-saga",
                payload,
                _header_request(
                    "/api/provider/projects/italus-saga/generation/execute",
                    "x" * 257,
                ),
            )
        except HTTPException as exc:
            long_status = exc.status_code

        result = project.execute_project_provider_generation(
            "italus-saga",
            payload,
            _header_request(
                "/api/provider/projects/italus-saga/generation/execute",
                "p40-valid-idempotency-key",
            ),
        )
        suite.equal(
            "P40-API-01",
            "Provider generation route rejects missing Idempotency-Key before execution",
            missing_status,
            400,
        )
        suite.equal(
            "P40-API-02",
            "Provider generation route rejects oversized Idempotency-Key before execution",
            long_status,
            422,
        )
        suite.check(
            "P40-API-03",
            "Provider generation route forwards only validated execution identity to backend service",
            len(observed_calls) == 1
            and observed_calls[0]
            == {
                "project_id": "italus-saga",
                "book_number": 1,
                "chapter_number": 1,
                "idempotency_key": "p40-valid-idempotency-key",
            }
            and result.get("generation_id") == "p40-regression-sentinel",
            details=f"calls={observed_calls!r}; result={result!r}",
        )
    finally:
        provider_execution_service.execute_provider_generation = original_execute

    routes = _route_signatures(project.router)
    required_routes = {
        ("GET", "/api/project/{project_id}/generation-readiness"),
        ("POST", "/api/provider/projects/{project_id}/generation/execute"),
        (
            "GET",
            "/api/provider/projects/{project_id}/generation/{generation_id}/validation",
        ),
        (
            "GET",
            "/api/provider/projects/{project_id}/generation/{generation_id}/review",
        ),
        (
            "POST",
            "/api/provider/projects/{project_id}/generation/{generation_id}/review",
        ),
    }
    suite.check(
        "P40-API-04",
        "Generation readiness, execution, validation, and author-review routes are registered",
        required_routes.issubset(routes),
        details=f"missing={sorted(required_routes - routes)!r}",
    )

    # 40B — browser wiring and handoff contracts.
    workspace_js = _source(repo, "frontend/workspace.js")
    workspace_css = _source(repo, "frontend/workspace.css")
    themes_css = _source(repo, "frontend/assets/themes/themes.css")
    provider_settings_js = _source(repo, "frontend/js/provider_settings.js")

    required_workspace_markers = {
        "/generation-readiness",
        "/generation/execute",
        "'Idempotency-Key': idempotencyKey",
        "state.authorReviewGenerationId = String(result.generation_id || '');",
        "authorReviewGenerationOptionFromResult(result)",
        "void preloadAuthorReviewForGeneration(result);",
        "state.authorReviewValidation = null;",
        "state.authorReviewStatus = null;",
        "state.authorReviewClassification = null;",
        "state.authorReviewContinuity = null;",
        'id="generation-book-number"',
        'id="generation-chapter-number"',
        'id="generation-check-readiness"',
        'id="generation-execute"',
        "Open Validation &amp; Review",
    }
    missing_workspace_markers = sorted(
        marker for marker in required_workspace_markers if marker not in workspace_js
    )
    suite.check(
        "P40-40B-01",
        "Generate workspace owns readiness, execution, idempotency, and eager A-to-B review handoff wiring",
        not missing_workspace_markers,
        details=f"missing={missing_workspace_markers!r}",
    )

    suite.check(
        "P40-40B-02",
        "Book and Chapter generation positions remain selectors",
        '<select id="generation-book-number"' in workspace_js
        and '<select id="generation-chapter-number"' in workspace_js
        and '<input id="generation-book-number"' not in workspace_js
        and '<input id="generation-chapter-number"' not in workspace_js,
    )

    suite.check(
        "P40-40B-03",
        "Original-theme Generate action buttons have hover/focus/disabled styling",
        "#generation-check-readiness" in workspace_css
        and "#generation-execute" in workspace_css
        and ":hover:not(:disabled)" in workspace_css
        and ":focus-visible" in workspace_css
        and ":disabled" in workspace_css,
    )

    theme_checks = {
        theme: (
            f'html[data-theme="{theme}"] :is(#generation-check-readiness, #generation-execute)'
            in themes_css
            and f'html[data-theme="{theme}"] :is(#generation-check-readiness, #generation-execute):focus-visible'
            in themes_css
        )
        for theme in ("sci-fi", "mystery", "fantasy")
    }
    suite.check(
        "P40-40B-04",
        "Sci-Fi, Mystery, and Fantasy Generate action buttons retain theme/focus alignment",
        all(theme_checks.values()),
        details=f"themes={theme_checks!r}",
    )

    stale_phrases = (
        "Provider execution remains locked",
        "production provider execution remains locked",
        "Real provider generation remains locked",
        "Generation remains disabled",
        "Generation Unlock",
    )
    active_sources = {
        "workspace_service.py": _source(repo, "app/services/workspace_service.py"),
        "provider_config_service.py": _source(repo, "app/services/provider_config_service.py"),
        "provider_workspace_service.py": _source(repo, "app/services/provider_workspace_service.py"),
        "provider_binding_service.py": _source(repo, "app/services/provider_binding_service.py"),
        "provider_preflight_service.py": _source(repo, "app/services/provider_preflight_service.py"),
        "project.py": _source(repo, "app/api/routes/project.py"),
        "workspace.js": workspace_js,
        "provider_settings.js": provider_settings_js,
    }
    stale_hits = {
        name: [phrase for phrase in stale_phrases if phrase in source]
        for name, source in active_sources.items()
    }
    stale_hits = {name: hits for name, hits in stale_hits.items() if hits}
    suite.check(
        "P40-STATUS-01",
        "Active production/status surfaces contain no obsolete global generation/provider lock text",
        not stale_hits,
        details=f"hits={stale_hits!r}",
    )

    suite.check(
        "P40-STATUS-02",
        "Provider Settings presents capability separately from configuration readiness",
        "Provider execution capability: AVAILABLE" in provider_settings_js
        and "Generation Readiness" in provider_settings_js,
    )

    # 40C / Primary 41 boundary.
    isolation_report = legacy_production_isolation_service.assert_production_isolation(repo)
    suite.check(
        "P40-40C-01",
        "Production import/frontend graph cannot reach legacy execution",
        isolation_report.get("isolated") is True
        and not isolation_report.get("legacy_modules_reachable")
        and not isolation_report.get("non_production_compatibility_modules_reachable")
        and not isolation_report.get("frontend_legacy_references"),
        details=f"violations={isolation_report.get('violations')!r}",
    )
    suite.check(
        "P40-41-01",
        "Primary 41 legacy retirement is complete and retired executable assets are absent",
        isolation_report.get("legacy_runtime_retired") is True
        and isolation_report.get("legacy_prompt_builder_retired") is True
        and not isolation_report.get("retired_legacy_files_present")
        and all(
            not (repo / relative_path).exists()
            for relative_path in legacy_production_isolation_service.RETIRED_LEGACY_FILES
        ),
        details=(
            f"retired_files_present="
            f"{isolation_report.get('retired_legacy_files_present')!r}"
        ),
    )

    # Existing lower-level migration regressions must remain green.
    subprocess_env = os.environ.copy()
    subprocess_env["PYTHONPATH"] = str(repo)
    subprocess_env["PYTHONDONTWRITEBYTECODE"] = "1"

    p40c = _run_tool(
        repo,
        "tools/primary40c_legacy_production_isolation.py",
        env=subprocess_env,
    )
    p40c_passed = (
        p40c.returncode == 0
        and "PRIMARY40C RESULT: PASS" in p40c.stdout
        and "LEGACY GENERATION FALLBACK: NONE" in p40c.stdout
    )
    suite.check(
        "P40-CHAIN-01",
        "Primary 40C isolation regression remains green",
        p40c_passed,
        details=(
            "returncode=0"
            if p40c_passed
            else (
                f"returncode={p40c.returncode}; "
                f"stdout_tail={p40c.stdout[-800:]!r}; "
                f"stderr_tail={p40c.stderr[-800:]!r}"
            )
        ),
    )

    p39 = _run_tool(
        repo,
        "tools/primary39_full_migration_regression.py",
        env=subprocess_env,
    )
    p39_passed = (
        p39.returncode == 0
        and "PRIMARY39 TOTAL: 72" in p39.stdout
        and "PRIMARY39 PASS: 72" in p39.stdout
        and "PRIMARY39 FAIL: 0" in p39.stdout
        and "PRIMARY39 REGRESSION: PASS" in p39.stdout
    )
    suite.check(
        "P40-CHAIN-02",
        "Primary 39 full migration regression remains 72/72",
        p39_passed,
        details=(
            "returncode=0; pass=72; fail=0"
            if p39_passed
            else (
                f"returncode={p39.returncode}; "
                f"stdout_tail={p39.stdout[-1200:]!r}; "
                f"stderr_tail={p39.stderr[-800:]!r}"
            )
        ),
    )

    return suite


def main() -> int:
    repo = _repo_root()
    project_data = repo / "data" / "projects" / "italus-saga"
    before_data = _tree_fingerprint(project_data)
    original_config_dir = os.environ.get("ITALUS_CONFIG_DIR")

    try:
        with tempfile.TemporaryDirectory(prefix="italus_primary40_regression_config_") as temp_dir:
            os.environ["ITALUS_CONFIG_DIR"] = temp_dir
            suite = _run_suite(repo)
    except Exception as exc:
        print("PRIMARY40 REGRESSION HARNESS ERROR")
        print(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 2
    finally:
        if original_config_dir is None:
            os.environ.pop("ITALUS_CONFIG_DIR", None)
        else:
            os.environ["ITALUS_CONFIG_DIR"] = original_config_dir

    after_data = _tree_fingerprint(project_data)
    suite.equal(
        "P40-SAFETY-01",
        "Regression gate performs no real Italus project-data mutation",
        after_data,
        before_data,
    )

    for result in suite.results:
        suffix = f" :: {result['details']}" if result["details"] else ""
        print(f"{result['status']} {result['id']} - {result['description']}{suffix}")

    total = len(suite.results)
    print("")
    print(f"PRIMARY40 MARKER: {PRIMARY40_MARKER}")
    print(f"PRIMARY40 SCHEMA: {PRIMARY40_SCHEMA_VERSION}")
    print(f"PRIMARY40 TOTAL: {total}")
    print(f"PRIMARY40 PASS: {suite.passed}")
    print(f"PRIMARY40 FAIL: {suite.failed}")

    if suite.failed:
        print("PRIMARY40 REGRESSION: FAIL")
        return 1

    print("PRIMARY40 REGRESSION: PASS")
    print("PRIMARY39 REGRESSION: PASS (72/72)")
    print("PRIMARY40C ISOLATION: PASS")
    print("LIVE PROVIDER GENERATION CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    print("LEGACY GENERATION FALLBACK: NONE")
    print("PRIMARY41 LEGACY RETIREMENT: COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
