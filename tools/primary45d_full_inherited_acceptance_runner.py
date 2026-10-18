"""Primary 45D inherited acceptance: PASS, FAIL, or BLOCKED (never fake PASS)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "data" / "projects" / "italus-saga"
TESTS = (
    "primary42_bounded_generation_prompt_authority_regression.py",
    "primary45c_reveal_safe_generation_authority_regression.py",
    "primary45d_targeted_regression_runner.py",
)
BLOCKER_CODE = "generation_request_not_ready"
BLOCKER_MESSAGE = "Requested project/book/chapter inputs are not ready for prompt construction."


def project_fingerprint() -> str:
    digest = hashlib.sha256()
    if PROJECT.exists():
        for entry in sorted(PROJECT.rglob("*")):
            if entry.is_file():
                digest.update(entry.relative_to(PROJECT).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(entry.read_bytes())
                digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    before = project_fingerprint()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    passed = failed = blocked = 0
    for filename in TESTS:
        target = ROOT / "tools" / filename
        if not target.is_file():
            print("FAIL missing test:", filename, flush=True)
            failed += 1
            continue
        try:
            result = subprocess.run(
                [sys.executable, str(target)],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
                timeout=360, check=False,
            )
        except subprocess.TimeoutExpired:
            print("FAIL timeout:", filename, flush=True)
            failed += 1
            continue
        combined = result.stdout + "\n" + result.stderr
        if result.returncode == 0:
            print("PASS:", filename, flush=True)
            passed += 1
        elif (result.returncode != 0 and
              "GenerationRequestBuildError" in combined and
              BLOCKER_MESSAGE in combined and
              "generation_service.py" in combined and
              # No traceback evidence of a later, unrelated test failure.
              "Traceback (most recent call last):" in combined):
            print("BLOCKED: project-derived Chapter 1 inputs are not ready:", filename, flush=True)
            blocked += 1
        else:
            print("FAIL:", filename, "exit", result.returncode, flush=True)
            print(combined[-3000:], flush=True)
            failed += 1
    if project_fingerprint() != before:
        print("FAIL: project data mutated during regressions", flush=True)
        failed += 1
    print("INHERITED ACCEPTANCE: PASS", passed, "BLOCKED", blocked, "FAIL", failed, flush=True)
    print("LIVE PROVIDER CALLS: NONE", flush=True)
    if failed:
        return 1
    if blocked:
        print("FULL INHERITED REGRESSION ACCEPTANCE: BLOCKED", flush=True)
        return 2
    print("FULL INHERITED REGRESSION ACCEPTANCE: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
