from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "frontend" / "workspace.js"
WORKSPACE_CSS = ROOT / "frontend" / "workspace.css"
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


def check(code: str, label: str, passed: bool, details: str = "") -> bool:
    suffix = f" :: {details}" if details else ""
    print(f"{code} {'PASS' if passed else 'FAIL'} - {label}{suffix}")
    return bool(passed)


def run() -> int:
    before = tree_sha256(PROJECT_DATA)
    text = WORKSPACE.read_text(encoding="utf-8")
    css = WORKSPACE_CSS.read_text(encoding="utf-8")

    panel_start = text.index("function paintAuthorReviewPanel(")
    panel_end = text.index("async function submitAuthorValidationResolutions(", panel_start)
    panel = text[panel_start:panel_end]

    selected_start = panel.index("const selectedMarkup")
    selected_end = panel.index("mainPanel.innerHTML", selected_start)
    selected_markup = panel[selected_start:selected_end]

    results: list[bool] = []

    results.append(check(
        "P45A-01",
        "Main Validation Results excludes integrity/technical checks",
        "authorValidationReportCategory(item) !== 'integrity'" in panel,
    ))

    results.append(check(
        "P45A-02",
        "Semantic FAIL and REVIEW results remain visible in Validation Results tiles",
        "const authorFacingChecks = (staleValidation ? [] : checks).filter((item)" in panel
        and "authorValidationReportCategory(item) !== 'integrity'" in panel
        and "!unresolvedRuleIds.has" not in panel,
    ))

    results.append(check(
        "P45A-03",
        "Author-facing validation tiles and resolution rows use human-readable rule labels",
        panel.count("authorValidationRuleLabel(item)") >= 2
        and "<strong>${escapeHtml(item.rule_id" not in panel,
    ))

    results.append(check(
        "P45A-04",
        "Primary-number implementation labels are absent from the author review panel",
        "Primary 34" not in panel
        and "Primary 35" not in panel
        and "Primary 36" not in panel,
    ))

    results.append(check(
        "P45A-05",
        "Generated Draft summary hides generation and version identifiers",
        "definition('Generation ID'" not in selected_markup
        and "definition('Current Version'" not in selected_markup,
    ))

    results.append(check(
        "P45A-06",
        "Draft selector labels do not expose generation IDs",
        "item.generation_id," not in panel[
            panel.index("const generationOptions"):
            panel.index("const authorFacingChecks")
        ],
    ))

    results.append(check(
        "P45A-07",
        "Provenance/HCCS classification is removed from the author-facing page",
        "const classificationMarkup = '';" in panel
        and "<h3>Provenance Classification</h3>" not in panel,
    ))

    results.append(check(
        "P45A-08",
        "Approved Continuity is shown only when actionable, accepted-pending-continuity, or committed",
        "continuityStatus === 'ready'" in panel
        and "reviewState === 'accepted_pending_approved_continuity'" in panel
        and "continuityCommitted" in panel,
    ))

    results.append(check(
        "P45A-09",
        "Author-facing introduction contains no control-plane migration language",
        "Review provider-generated chapter candidates after Primary" not in panel
        and "versioned HCCS" not in panel
        and "Review the generated chapter" in panel,
    ))

    results.append(check(
        "P45A-10",
        "Long definition/check content wraps inside author-facing cards",
        "overflow-wrap: anywhere;" in css
        and ".workspace-author-review-check.is-review" in css,
    ))

    # Technical detail remains available in the detailed report.
    report_start = text.index("function authorValidationTechnicalGroupMarkup(")
    report_end = text.index("function openAuthorValidationReport(", report_start)
    report = text[report_start:report_end]
    results.append(check(
        "P45A-11",
        "Detailed report retains collapsed Technical Validation diagnostics",
        "Technical Validation" in report
        and "technical-validation" in report
        and "provider receipts" in report,
    ))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p45 = ROOT / "tools" / "primary45_audited_semantic_validation_regression.py"
    result = subprocess.run(
        [sys.executable, str(p45)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    p45_text = result.stdout
    results.append(check(
        "P45A-12",
        "Primary 45/44/43/42/41/40/39 chain remains green",
        result.returncode == 0
        and "PRIMARY45 PASS: 14" in p45_text
        and "PRIMARY45 FAIL: 0" in p45_text
        and "P45-13 PASS" in p45_text,
        f"returncode={result.returncode}",
    ))

    after = tree_sha256(PROJECT_DATA)
    results.append(check(
        "P45A-13",
        "Primary 45A regression performs no Italus project-data mutation",
        before == after,
        f"before={before}; after={after}",
    ))

    passed = sum(results)
    failed = len(results) - passed
    print("PRIMARY45A MARKER: primary45a-author-validation-surface-cleanup-v1")
    print(f"PRIMARY45A TOTAL: {len(results)}")
    print(f"PRIMARY45A PASS: {passed}")
    print(f"PRIMARY45A FAIL: {failed}")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
