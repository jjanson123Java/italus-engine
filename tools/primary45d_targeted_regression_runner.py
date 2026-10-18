"""Deterministic Primary 45D targeted regression runner.

Executes checked-in regressions via the current Python interpreter.
Does not generate prose, contact providers, or mutate project artifacts.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "primary45d_authority_channel_consistency_regression.py",
    "primary45d_authorized_continuity_schema_regression.py",
    "primary45d_continuity_handoff_alignment_regression.py",
    "primary45d_established_projection_regression.py",
    "primary45d_execution_reference_alignment_regression.py",
    "primary45d_full_provider_channel_reveal_regression.py",
    "primary45d_reference_authority_integrity_regression.py",
    "primary45d_stage1_behavioral_authority_regression.py",
)


def main() -> int:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing if existing else "")
    failures = []
    for filename in TESTS:
        target = ROOT / "tools" / filename
        if not target.is_file():
            print("FAIL missing regression:", filename, flush=True)
            failures.append(filename)
            continue
        result = subprocess.run(
            [sys.executable, str(target)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            print("FAIL", filename, "exit", result.returncode, flush=True)
            print(result.stdout[-4000:], flush=True)
            print(result.stderr[-4000:], file=sys.stderr, flush=True)
            failures.append(filename)
        else:
            print("PASS", filename, flush=True)
    if failures:
        print("PRIMARY45D TARGETED REGRESSION FAIL", len(failures), flush=True)
        return 1
    print("PRIMARY45D TARGETED REGRESSION PASS", len(TESTS), flush=True)
    print("FULL INHERITED REGRESSION ACCEPTANCE: NOT ESTABLISHED", flush=True)
    print("LIVE GENERATION ACCEPTANCE: NOT ESTABLISHED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
