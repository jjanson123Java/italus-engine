from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


MARKER = "candidate-validation-evidence-report-v2-regression-20260920"
PROJECT_ID = "italus-saga"
GENERATION_ID = "gen_f66b53921d88e90df6860046b49dcc7e"


class Suite:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        self.results.append((name, bool(condition), detail))

    def finish(self) -> int:
        for name, passed, detail in self.results:
            suffix = f" — {detail}" if detail else ""
            print(f"{'PASS' if passed else 'FAIL'} {name}{suffix}")
        passed = sum(1 for _, result, _ in self.results if result)
        failed = len(self.results) - passed
        print(f"{MARKER}: {passed}/{len(self.results)} PASS; {failed} FAIL")
        return 0 if failed == 0 else 1


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".git/") or "__pycache__" in path.parts:
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _rule(report: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return next(
        item
        for item in report.get("content_rules") or []
        if str(item.get("rule_id") or "") == rule_id
    )


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    frontend = Path(
        os.getenv("ITALUS_VALIDATION_REPORT_FRONTEND", str(repo / "frontend" / "workspace.js"))
    ).resolve()
    project_root = repo / "data" / "projects" / PROJECT_ID
    before = _tree_hash(project_root)

    from app.services import provider_direct_generation_service
    from app.services.validation_service import validate_generation_candidate

    original_executor = provider_direct_generation_service.execute_direct_generation

    def provider_call_forbidden(**_: Any) -> dict[str, Any]:
        raise AssertionError("candidate validation attempted a provider call")

    provider_direct_generation_service.execute_direct_generation = provider_call_forbidden
    try:
        report = validate_generation_candidate(PROJECT_ID, GENERATION_ID)
    finally:
        provider_direct_generation_service.execute_direct_generation = original_executor

    after = _tree_hash(project_root)
    suite = Suite()
    suite.check("validation remains read-only", before == after)
    suite.check("provider-free validation completed", report.get("status") == "ok")
    suite.check("acceptance remains blocked", report.get("acceptable_for_author_acceptance") is False)
    suite.check("validation state remains content_failed", report.get("validation_state") == "content_failed")
    suite.check("authoritative check count unchanged", len(report.get("checks") or []) == 31)

    em_dashes = _rule(report, "prose.em_dashes.quantitative")
    em_evidence = (em_dashes.get("details") or {}).get("evidence") or []
    suite.check("em-dash rule fails", em_dashes.get("status") == "FAIL")
    suite.check("em-dash count remains 25", (em_dashes.get("details") or {}).get("measurement") == 25)
    suite.check("em-dash required reduction is 17", (em_dashes.get("details") or {}).get("required_reduction") == 17)
    suite.check("all em dashes have exact evidence", len(em_evidence) == 25)
    candidate = str((report.get("candidate") or {}).get("text") or "")
    suite.check(
        "em-dash offsets bind to exact text",
        all(candidate[int(item["start_offset"]):int(item["end_offset"])] == "—" for item in em_evidence),
    )
    suite.check(
        "em-dash evidence has author locations",
        all(int(item.get("sentence_number") or 0) > 0 and int(item.get("paragraph_number") or 0) > 0 for item in em_evidence),
    )

    colons = _rule(report, "prose.colons.quantitative")
    suite.check("colon rule fails 4 over 3", colons.get("status") == "FAIL" and (colons.get("details") or {}).get("measurement") == 4)
    suite.check("all colons have exact evidence", len((colons.get("details") or {}).get("evidence") or []) == 4)

    diagnostics = report.get("diagnostic_checks") or []
    short = diagnostics[0] if diagnostics else {}
    short_evidence = (short.get("details") or {}).get("evidence") or []
    suite.check("very-short-sentence diagnostic is present", short.get("rule_id") == "prose.very_short_sentences.review")
    suite.check("short-sentence judgment stays review-only", short.get("status") in {"PASS", "REVIEW"} and short.get("required") is False)
    suite.check("short-sentence evidence has exact locations", bool(short_evidence) and all(int(item.get("end_offset") or 0) > int(item.get("start_offset") or 0) for item in short_evidence))

    age_rule = _rule(report, "chapter.restriction.f50c72cb8cb9710f")
    age_details = age_rule.get("details") or {}
    age_evidence = age_details.get("evidence") or []
    suite.check("canon rule remains honest UNKNOWN", age_rule.get("status") == "UNKNOWN")
    suite.check("canon evidence is not promoted to a verdict", age_details.get("semantic_verdict_produced") is False)
    suite.check(
        "Farovald age passage is surfaced",
        any("thirty-nine years old" in str(item.get("excerpt") or "").casefold() for item in age_evidence),
    )
    suite.check(
        "canon evidence offsets bind to the saved draft",
        all(
            candidate[int(item["context_start_offset"]):int(item["context_end_offset"])]
            for item in age_evidence
        ),
    )

    source = frontend.read_text(encoding="utf-8")
    required_markers = (
        "workspace-candidate-validation-author-facing-report-v2d-20260920",
        "Writing Rules",
        "Canon & Narrative Rules",
        "Detected Failures",
        "Author Review Required",
        "Passed Rules",
        "Locate in Draft",
        "Bring Report to Front",
        "Open Validation Report",
        "startAuthorValidationReportMonitor",
        "syncAuthorValidationReportButton",
        "data-theme=\"${escapeHtml(activeTheme)}\"",
    )
    suite.check("frontend evidence report markers present", all(marker in source for marker in required_markers))
    suite.check("ambiguous focus label removed", "Focus Validation Report" not in source)
    suite.check("close monitor observes popup state", "authorValidationReportWindow.closed" in source and "window.setInterval" in source)
    suite.check("four application themes are mapped", all(f'data-theme=\"{theme}\"' in source for theme in ("sci-fi", "mystery", "fantasy")))
    suite.check("acceptance gate remains authoritative", "!acceptanceReady ? 'disabled' : ''" in source)
    suite.check(
        "author-facing group totals expose status split",
        "checks total" in source and "group-status-summary" in source and "failure${counts.failed === 1 ? '' : 's'}" in source,
    )
    suite.check(
        "review rules without evidence still expose guidance",
        "No specific passage was isolated automatically" in source and "What to review" in source,
    )
    suite.check(
        "author cards hide developer metadata by default",
        "options.technical === true ? authorValidationTechnicalDetailsMarkup(item) : ''" in source,
    )
    suite.check(
        "technical lineage is collapsed out of author workflow",
        "Technical Validation" in source and "system safeguards, not writing decisions" in source,
    )
    suite.check(
        "top author summary excludes technical identity fields",
        '<strong>Generation</strong>${escapeHtml(validation.generation_id' not in source[source.find('<div class="summary result-summary">'):source.find('${groupMarkup}', source.find('<div class="summary result-summary">'))],
    )

    node = subprocess.run(
        ["node", "--check", str(frontend)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    suite.check("frontend JavaScript syntax", node.returncode == 0, node.stderr.strip())
    return suite.finish()


if __name__ == "__main__":
    raise SystemExit(main())

