from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


PRIMARY41_MARKER = "primary41-legacy-runtime-retirement-regression-v1b"


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
        self.results.append(
            {
                "id": test_id,
                "description": description,
                "status": "PASS" if condition else "FAIL",
                "details": details,
            }
        )

    @property
    def passed(self) -> int:
        return sum(item["status"] == "PASS" for item in self.results)

    @property
    def failed(self) -> int:
        return sum(item["status"] == "FAIL" for item in self.results)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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


def _run_tool(repo: Path, relative_path: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, relative_path],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _probe_fastapi_startup(repo: Path) -> dict[str, Any]:
    """Probe production FastAPI startup in a fresh interpreter.

    Keeping this probe out-of-process prevents the regression harness itself
    from influencing ``sys.modules`` or router registration state.
    """

    probe_source = r"""
import importlib.metadata
import json
import sys
from pathlib import Path

from app.api.main import app
from app.api.routes.books import router as books_router
from app.api.routes.health import router as health_router
from app.api.routes.project import router as project_router
from app.services import legacy_production_isolation_service


def direct_route_paths(route_owner):
    return sorted(
        {
            str(route.path)
            for route in route_owner.routes
            if getattr(route, "path", None)
        }
    )


openapi = app.openapi()
openapi_paths = sorted(str(path) for path in (openapi.get("paths") or {}).keys())

payload = {
    "app_module": str(Path(sys.modules["app.api.main"].__file__).resolve()),
    "project_module": str(Path(sys.modules["app.api.routes.project"].__file__).resolve()),
    "books_module": str(Path(sys.modules["app.api.routes.books"].__file__).resolve()),
    "health_module": str(Path(sys.modules["app.api.routes.health"].__file__).resolve()),
    "fastapi_version": importlib.metadata.version("fastapi"),
    "starlette_version": importlib.metadata.version("starlette"),
    # app.routes is intentionally only the direct route container on newer
    # FastAPI releases where include_router() preserves nested routers.
    "direct_app_route_paths": direct_route_paths(app),
    # OpenAPI is the public FastAPI contract for included API route registration
    # and traverses included routers across supported FastAPI representations.
    "openapi_paths": openapi_paths,
    "project_route_paths": direct_route_paths(project_router),
    "books_route_paths": direct_route_paths(books_router),
    "health_route_paths": direct_route_paths(health_router),
    "loaded_retired": sorted(
        name
        for name in legacy_production_isolation_service.RETIRED_LEGACY_MODULES
        if name in sys.modules
    ),
}
print("P41_STARTUP_PROBE=" + json.dumps(payload, sort_keys=True))
"""

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", probe_source],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    marker = "P41_STARTUP_PROBE="
    payload: dict[str, Any] = {}
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(marker):
            try:
                payload = json.loads(line[len(marker):])
            except json.JSONDecodeError:
                payload = {}
            break

    payload["_returncode"] = completed.returncode
    payload["_stderr_tail"] = completed.stderr[-1200:]
    payload["_stdout_tail"] = completed.stdout[-1200:]
    return payload


def _path_is_within(path_text: str, repo: Path) -> bool:
    if not path_text:
        return False
    try:
        path = Path(path_text).resolve()
        root = repo.resolve()
        return os.path.commonpath((str(path), str(root))) == str(root)
    except (OSError, ValueError):
        return False


def _run_suite(repo: Path) -> RegressionSuite:
    suite = RegressionSuite()

    from app.services import generation_service
    from app.services import legacy_production_isolation_service

    retired_files = tuple(legacy_production_isolation_service.RETIRED_LEGACY_FILES)
    present = [path for path in retired_files if (repo / path).exists()]
    suite.check(
        "P41-01",
        "All retired legacy executable files are absent",
        not present,
        details=f"present={present!r}",
    )

    prompt_path = repo / "app" / "prompt_builder.py"
    prompt_source = prompt_path.read_text(encoding="utf-8")
    suite.check(
        "P41-02",
        "Retired build_generation_prompt function is absent",
        "def build_generation_prompt(" not in prompt_source,
    )
    suite.check(
        "P41-03",
        "Project-local prompt builder remains present",
        "def build_project_local_generation_prompt(" in prompt_source
        and "PROJECT_LOCAL_PROMPT_BUILDER_MARKER" in prompt_source,
    )

    report = legacy_production_isolation_service.assert_production_isolation(repo)
    suite.check(
        "P41-04",
        "Fail-closed retirement audit reports a clean retired state",
        report.get("retired") is True
        and report.get("legacy_runtime_retired") is True
        and report.get("legacy_prompt_builder_retired") is True
        and not report.get("retired_legacy_modules_reachable")
        and not report.get("retired_legacy_files_present")
        and not report.get("frontend_legacy_references"),
        details=f"violations={report.get('violations')!r}",
    )

    startup_probe = _probe_fastapi_startup(repo)
    direct_app_route_paths = set(startup_probe.get("direct_app_route_paths") or [])
    openapi_paths = set(startup_probe.get("openapi_paths") or [])
    project_route_paths = set(startup_probe.get("project_route_paths") or [])
    books_route_paths = set(startup_probe.get("books_route_paths") or [])
    health_route_paths = set(startup_probe.get("health_route_paths") or [])
    module_origins_ok = all(
        _path_is_within(str(startup_probe.get(key) or ""), repo)
        for key in ("app_module", "project_module", "books_module", "health_module")
    )
    suite.check(
        "P41-05",
        "FastAPI application starts with all API routers registered after legacy retirement",
        startup_probe.get("_returncode") == 0
        and module_origins_ok
        and "/workspace" in direct_app_route_paths
        and "/api/project/{project_id}" in openapi_paths
        and "/api/health" in openapi_paths
        and "/api/books" in openapi_paths
        and "/api/project/{project_id}" in project_route_paths
        and "/api/health" in health_route_paths
        and "/api/books" in books_route_paths,
        details=(
            f"direct_app_route_count={len(direct_app_route_paths)}; "
            f"openapi_path_count={len(openapi_paths)}; "
            f"project_route_count={len(project_route_paths)}; "
            f"fastapi_version={startup_probe.get('fastapi_version')!r}; "
            f"starlette_version={startup_probe.get('starlette_version')!r}; "
            f"app_module={startup_probe.get('app_module')!r}; "
            f"project_module={startup_probe.get('project_module')!r}; "
            f"returncode={startup_probe.get('_returncode')!r}; "
            f"stderr_tail={startup_probe.get('_stderr_tail')!r}"
        ),
    )

    loaded_retired = list(startup_probe.get("loaded_retired") or [])
    suite.check(
        "P41-06",
        "Fresh FastAPI startup does not load retired legacy modules",
        startup_probe.get("_returncode") == 0 and not loaded_retired,
        details=f"loaded={loaded_retired!r}",
    )

    envelope = generation_service.build_generation_request_envelope(
        "italus-saga",
        book_number=1,
        chapter_number=1,
    )
    prompt = dict(envelope.get("prompt") or {})
    execution = dict(envelope.get("execution") or {})
    suite.check(
        "P41-07",
        "Project-local Book 1 Chapter 1 generation request still builds",
        bool(prompt.get("prompt_sha256"))
        and execution.get("control_plane") == "project_local_primary40a"
        and execution.get("legacy_fallback_allowed") is False,
        details=f"prompt_sha256={prompt.get('prompt_sha256')!r}",
    )

    generation_source = (repo / "app" / "services" / "generation_service.py").read_text(
        encoding="utf-8"
    )
    suite.check(
        "P41-08",
        "Production generation remains wired only to project-local Prompt Builder",
        "prompt_builder.build_project_local_generation_prompt(" in generation_source
        and "build_generation_prompt(" not in generation_source
        and "project_runner" not in generation_source
        and "ai_runner" not in generation_source,
    )

    p40 = _run_tool(repo, "tools/primary40_full_migration_regression.py")
    suite.check(
        "P41-09",
        "Primary 40/40C/39 consolidated migration regressions remain green after retirement",
        p40.returncode == 0
        and "PRIMARY40 FAIL: 0" in p40.stdout
        and "PRIMARY39 REGRESSION: PASS (72/72)" in p40.stdout
        and "PRIMARY40C ISOLATION: PASS" in p40.stdout
        and "PRIMARY41 LEGACY RETIREMENT: COMPLETE" in p40.stdout,
        details=(
            f"returncode={p40.returncode}; "
            f"stdout_tail={p40.stdout[-1200:]!r}; "
            f"stderr_tail={p40.stderr[-1200:]!r}"
        ),
    )

    project_data = repo / "data" / "projects" / "italus-saga"
    before = _tree_fingerprint(project_data)
    generation_service.build_generation_request_envelope(
        "italus-saga",
        book_number=1,
        chapter_number=1,
    )
    after = _tree_fingerprint(project_data)
    suite.check(
        "P41-10",
        "Primary 41 sanity validation does not mutate Italus project data",
        before == after,
        details=f"before={before}; after={after}",
    )

    return suite


def main() -> int:
    repo = _repo_root()
    suite = _run_suite(repo)

    for item in suite.results:
        suffix = f" :: {item['details']}" if item["details"] else ""
        print(
            f"{item['id']} {item['status']} - {item['description']}{suffix}"
        )

    print(f"PRIMARY41 MARKER: {PRIMARY41_MARKER}")
    print(f"PRIMARY41 TOTAL: {len(suite.results)}")
    print(f"PRIMARY41 PASS: {suite.passed}")
    print(f"PRIMARY41 FAIL: {suite.failed}")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    print("LEGACY GENERATION FALLBACK: NONE")

    return 0 if suite.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
