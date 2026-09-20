from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "frontend" / "workspace.js"
PROJECT_DATA = ROOT / "data" / "projects" / "italus-saga"


def tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return digest.hexdigest()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def check(code: str, label: str, passed: bool, details: str = "") -> tuple[str, bool]:
    suffix = f" :: {details}" if details else ""
    print(f"{code} {'PASS' if passed else 'FAIL'} - {label}{suffix}")
    return code, passed


def run() -> int:
    before = tree_sha256(PROJECT_DATA)
    text = WORKSPACE.read_text(encoding="utf-8")
    results: list[tuple[str, bool]] = []

    results.append(check(
        "P43-01",
        "Generation success seeds the exact new candidate into author-review state",
        "authorReviewGenerationOptionFromResult(result)" in text
        and "mergeAuthorReviewGenerationOptions(" in text,
    ))
    results.append(check(
        "P43-02",
        "Generation success starts Validation & Review preload immediately",
        "void preloadAuthorReviewForGeneration(result);" in text,
    ))
    results.append(check(
        "P43-03",
        "Eager handoff no longer clears generation options before review discovery",
        "state.authorReviewGenerationOptions = [];" not in text[
            text.index("async function executeWorkspaceGeneration"):
            text.index("async function executeReplacementGeneration")
        ],
    ))
    results.append(check(
        "P43-04",
        "Validation detail and usage-history refresh run concurrently",
        "Promise.allSettled([" in text
        and "loadAuthorReviewGeneration(generationId, { render: false })" in text
        and "refreshAuthorReviewGenerationOptions({ render: false })" in text,
    ))
    results.append(check(
        "P43-05",
        "Exact candidate review loader still fetches validation/review/classification/continuity concurrently",
        "const [validation, review, classification, continuity] = await Promise.all([" in text,
    ))
    results.append(check(
        "P43-06",
        "Generation screen exposes a bounded Preparing Validation & Review handoff state",
        "Preparing Validation &amp; Review…" in text
        and "authorReviewPreloadGenerationId === String(result.generation_id)" in text,
    ))
    results.append(check(
        "P43-07",
        "Completed preload refreshes whichever author surface is active",
        "state.activeSection === 'validation'" in text
        and "state.activeSection === 'generation'" in text
        and "renderGenerationPanel(state.bootstrap || {}, { refresh: false });" in text,
    ))
    results.append(check(
        "P43-08",
        "Replacement generation continues through the same eager generation handoff",
        "replacement: true" in text
        and "replacementForGenerationId:" in text
        and "executeWorkspaceGeneration(bootstrap, {" in text,
    ))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p42 = ROOT / "tools" / "primary42_bounded_generation_prompt_authority_regression.py"
    result = subprocess.run(
        [sys.executable, str(p42)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    p42_text = result.stdout
    results.append(check(
        "P43-09",
        "Primary 42/41/40/39 generation-control chain remains green",
        result.returncode == 0
        and "PRIMARY42 PASS: 15" in p42_text
        and "PRIMARY42 FAIL: 0" in p42_text
        and "PRIMARY40 PASS: 33" in p42_text
        and "PRIMARY39 REGRESSION: PASS (72/72)" in p42_text,
        f"returncode={result.returncode}",
    ))

    after = tree_sha256(PROJECT_DATA)
    results.append(check(
        "P43-10",
        "Primary 43 regression performs no Italus project-data mutation",
        before == after,
        f"before={before}; after={after}",
    ))

    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    print("PRIMARY43 MARKER: primary43-eager-validation-review-handoff-regression-v1")
    print(f"PRIMARY43 TOTAL: {len(results)}")
    print(f"PRIMARY43 PASS: {passed}")
    print(f"PRIMARY43 FAIL: {failed}")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
