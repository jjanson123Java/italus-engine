from __future__ import annotations

import ast
from collections import deque
from pathlib import Path
from typing import Any


PRIMARY40C_ISOLATION_MARKER = "primary40c-legacy-production-isolation-v1"
PRIMARY41_RETIREMENT_MARKER = "primary41-legacy-runtime-retirement-v1"
PRODUCTION_ENTRY_MODULE = "app.api.main"

RETIRED_LEGACY_MODULES = frozenset(
    {
        "app.ITALUS_PROJECT_RUNNER_MENU_TONE",
        "app.project_runner",
        "app.ai_runner",
        "app.claude_runner",
        "app.openai_runner",
        "app.novelcraft_runner",
        "app.bootstrap_manifests",
    }
)

RETIRED_LEGACY_FILES = (
    "app/ITALUS_PROJECT_RUNNER_MENU_TONE.py",
    "app/project_runner.py",
    "app/ai_runner.py",
    "app/claude_runner.py",
    "app/openai_runner.py",
    "app/novelcraft_runner.py",
    "app/bootstrap_manifests.py",
)

PRODUCTION_FRONTEND_FILES = (
    "frontend/script.js",
    "frontend/workspace.js",
)

FORBIDDEN_FRONTEND_TOKENS = (
    "ITALUS_PROJECT_RUNNER_MENU_TONE",
    "project_runner",
    "ai_runner",
    "claude_runner",
    "openai_runner",
    "novelcraft_runner",
    "build_generation_prompt",
    "generate_with_ai",
)


class LegacyProductionIsolationError(RuntimeError):
    """Raised when retired runtime code can re-enter the production surface."""


def _project_root(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return Path(project_root).resolve()
    return Path(__file__).resolve().parents[2]


def _module_name(project_root: Path, path: Path) -> str:
    relative = path.relative_to(project_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _module_index(project_root: Path) -> dict[str, Path]:
    app_root = project_root / "app"
    if not app_root.is_dir():
        raise LegacyProductionIsolationError(
            f"Primary 41 cannot locate the app package: {app_root}"
        )

    index: dict[str, Path] = {}
    for path in sorted(app_root.rglob("*.py")):
        module_name = _module_name(project_root, path)
        if module_name:
            index[module_name] = path
    return index


def _parse_python(path: Path) -> ast.AST:
    try:
        source = path.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise LegacyProductionIsolationError(
            f"Primary 41 could not parse production dependency source {path}: {exc}"
        ) from exc


def _resolve_app_imports(tree: ast.AST, module_index: dict[str, Path]) -> set[str]:
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app") and alias.name in module_index:
                    imports.add(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if not node.module or not node.module.startswith("app"):
                continue

            if node.module in module_index:
                imports.add(node.module)

            for alias in node.names:
                candidate = f"{node.module}.{alias.name}"
                if candidate in module_index:
                    imports.add(candidate)

    return imports


def _reachable_modules(
    project_root: Path,
    module_index: dict[str, Path],
) -> tuple[set[str], dict[str, ast.AST]]:
    if PRODUCTION_ENTRY_MODULE not in module_index:
        raise LegacyProductionIsolationError(
            f"Primary 41 production entry module is missing: {PRODUCTION_ENTRY_MODULE}"
        )

    reachable: set[str] = set()
    parsed: dict[str, ast.AST] = {}
    pending: deque[str] = deque([PRODUCTION_ENTRY_MODULE])

    while pending:
        module_name = pending.popleft()
        if module_name in reachable:
            continue

        path = module_index[module_name]
        tree = _parse_python(path)
        parsed[module_name] = tree
        reachable.add(module_name)

        for imported_module in sorted(_resolve_app_imports(tree, module_index)):
            if imported_module not in reachable:
                pending.append(imported_module)

    return reachable, parsed


def _legacy_prompt_call_violations(
    reachable: set[str],
    parsed: dict[str, ast.AST],
) -> list[str]:
    violations: list[str] = []

    for module_name in sorted(reachable):
        tree = parsed[module_name]
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "app.prompt_builder":
                    imported_names = {alias.name for alias in node.names}
                    if "build_generation_prompt" in imported_names:
                        violations.append(
                            f"{module_name} imports retired build_generation_prompt"
                        )

            if not isinstance(node, ast.Call):
                continue

            function = node.func
            if isinstance(function, ast.Name) and function.id == "build_generation_prompt":
                violations.append(
                    f"{module_name} calls retired build_generation_prompt"
                )
            elif (
                isinstance(function, ast.Attribute)
                and function.attr == "build_generation_prompt"
            ):
                violations.append(
                    f"{module_name} calls retired build_generation_prompt"
                )

    return violations


def _frontend_files(project_root: Path) -> list[Path]:
    files: list[Path] = []

    for relative_path in PRODUCTION_FRONTEND_FILES:
        path = project_root / relative_path
        if not path.is_file():
            raise LegacyProductionIsolationError(
                f"Primary 41 production frontend file is missing: {relative_path}"
            )
        files.append(path)

    js_root = project_root / "frontend" / "js"
    if js_root.is_dir():
        files.extend(sorted(js_root.rglob("*.js")))

    return files


def _frontend_violations(project_root: Path) -> list[str]:
    violations: list[str] = []

    for path in _frontend_files(project_root):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(project_root).as_posix()
        for token in FORBIDDEN_FRONTEND_TOKENS:
            if token in source:
                violations.append(
                    f"{relative} references retired production token {token}"
                )

    return violations


def _retirement_surface_violations(project_root: Path) -> list[str]:
    violations: list[str] = []

    for relative_path in RETIRED_LEGACY_FILES:
        if (project_root / relative_path).exists():
            violations.append(
                f"retired legacy executable is still present: {relative_path}"
            )

    prompt_builder = project_root / "app" / "prompt_builder.py"
    if not prompt_builder.is_file():
        violations.append("project-local prompt builder is missing: app/prompt_builder.py")
    else:
        source = prompt_builder.read_text(encoding="utf-8")
        if "def build_generation_prompt(" in source:
            violations.append(
                "retired build_generation_prompt function is still present"
            )
        if "def build_project_local_generation_prompt(" not in source:
            violations.append(
                "project-local production prompt builder is missing"
            )

    return violations


def audit_production_isolation(
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Return the fail-closed Primary 41 legacy-retirement audit.

    Primary 40C proved the current production import graph could not reach the
    pre-migration runner chain. Primary 41 turns that isolation boundary into a
    permanent absence contract: retired executable files and the retired prompt
    builder must no longer exist.
    """

    root = _project_root(project_root)
    module_index = _module_index(root)
    reachable, parsed = _reachable_modules(root, module_index)

    retired_reachable = sorted(RETIRED_LEGACY_MODULES.intersection(reachable))

    violations: list[str] = []
    violations.extend(
        f"production import graph reaches retired module {name}"
        for name in retired_reachable
    )
    violations.extend(_legacy_prompt_call_violations(reachable, parsed))
    violations.extend(_frontend_violations(root))
    violations.extend(_retirement_surface_violations(root))

    retired_files_present = [
        relative_path
        for relative_path in RETIRED_LEGACY_FILES
        if (root / relative_path).exists()
    ]

    return {
        "marker": PRIMARY41_RETIREMENT_MARKER,
        "predecessor_marker": PRIMARY40C_ISOLATION_MARKER,
        "production_entry_module": PRODUCTION_ENTRY_MODULE,
        "production_module_count": len(reachable),
        "production_modules": sorted(reachable),
        "retired_legacy_modules_reachable": retired_reachable,
        # Compatibility keys retained for Primary 40 regression consumers.
        "legacy_modules_reachable": retired_reachable,
        "non_production_compatibility_modules_reachable": [],
        "retired_legacy_files": list(RETIRED_LEGACY_FILES),
        "retired_legacy_files_present": retired_files_present,
        "legacy_rollback_files": list(RETIRED_LEGACY_FILES),
        "legacy_rollback_surface_retained": False,
        "legacy_runtime_retired": not retired_files_present,
        "legacy_prompt_builder_retired": not any(
            "build_generation_prompt" in item for item in violations
        ),
        "frontend_legacy_references": [
            item for item in violations if "frontend/" in item
        ],
        "violations": violations,
        "isolated": not violations,
        "retired": not violations,
    }


def assert_production_isolation(
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Fail closed when retired execution code exists or is production-reachable."""

    report = audit_production_isolation(project_root)
    if report["violations"]:
        detail = "; ".join(report["violations"])
        raise LegacyProductionIsolationError(
            f"Primary 41 legacy runtime retirement failed: {detail}"
        )
    return report
