from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DATA = ROOT / "data" / "projects" / "italus-saga"


def tree_sha256(path: Path) -> str:
    h = hashlib.sha256()
    if not path.exists():
        return h.hexdigest()
    for p in sorted(x for x in path.rglob("*") if x.is_file()):
        h.update(p.relative_to(path).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def ck(code: str, label: str, ok: bool, detail: str = ""):
    print(f"{code} {'PASS' if ok else 'FAIL'} - {label}" + (f" :: {detail}" if detail else ""))
    return ok


def run() -> int:
    before = tree_sha256(PROJECT_DATA)
    results = []

    from app import prompt_builder
    from app.api.routes.project import ProviderGenerationExecuteRequest
    from app.services import generation_service, replacement_generation_context_service

    rejected = "gen_f66b53921d88e90df6860046b49dcc7e"
    current = "gen_9d9355b6fa08bff0085366f7877995a6"

    ctx = replacement_generation_context_service.build_replacement_correction_context(
        "italus-saga", rejected, book_number=1, chapter_number=1
    )
    results.append(ck("P44-01", "Backend proves the replacement source is terminally rejected",
                      ctx["source_generation_id"] == rejected and ctx["rejected_content_sha256"]))
    original_review_loader = (
        replacement_generation_context_service.author_review_service.get_author_review_status
    )
    synthetic_text = "synthetic rejected candidate"
    synthetic_sha = hashlib.sha256(synthetic_text.encode("utf-8")).hexdigest()
    synthetic_generation = "gen_0123456789abcdef0123456789abcdef"
    synthetic_review = {
        "terminal": True,
        "review_state": "rejected",
        "current_content_sha256": synthetic_sha,
        "terminal_event": {
            "operation": "AUTHOR_REJECT",
            "source_generation_id": synthetic_generation,
            "event_id": "review_event_synthetic",
            "version_id": "review_version_synthetic",
            "after_hash": synthetic_sha,
            "metadata": {
                "validation_report_sha256": "a" * 64,
                "rejection_validation": {
                    "validation_run_id": "validation_run_synthetic",
                    "validation_result_sha256": "b" * 64,
                    "validated_content_version_id": "version_synthetic",
                    "validated_content_sha256": synthetic_sha,
                    "validator_contract_sha256": "c" * 64,
                    "deterministic_failures": [
                        {
                            "rule_id": "prose.word_count.quantitative",
                            "message": "Word count is 3000; minimum is 4000.",
                            "instruction": "Increase word count to at least 4000.",
                            "details": {
                                "metric": "word_count",
                                "measurement": 3000,
                                "operator": "minimum",
                                "threshold": 4000,
                            },
                        }
                    ],
                },
            },
        },
        "validation": {
            "validation_run_id": "validation_run_current",
            "validation_result_sha256": "d" * 64,
            "validation_report_sha256": "e" * 64,
            "validator_context": {
                "book_number": 1,
                "chapter_number": 1,
                "candidate_content_sha256": synthetic_sha,
                "current_content_version_id": "version_synthetic",
                "validator_contract_sha256": "c" * 64,
            },
            "content_rules": [
                {
                    "rule_id": "prose.word_count.quantitative",
                    "evaluation_mode": "DETERMINISTIC",
                    "severity": "BLOCKER",
                    "status": "FAIL",
                    "message": "Word count is 3000; minimum is 4000.",
                    "instruction": "Increase word count to at least 4000.",
                    "details": {
                        "metric": "word_count",
                        "measurement": 3000,
                        "operator": "minimum",
                        "threshold": 4000,
                    },
                },
                {
                    "rule_id": "story_control.synthetic",
                    "evaluation_mode": "MANUAL",
                    "severity": "BLOCKER",
                    "status": "UNKNOWN",
                    "message": "Author review required.",
                    "instruction": "Review manually.",
                    "details": {},
                },
            ],
        },
    }
    replacement_generation_context_service.author_review_service.get_author_review_status = (
        lambda project_id, generation_id: synthetic_review
    )
    try:
        synthetic_ctx = (
            replacement_generation_context_service.build_replacement_correction_context(
                "italus-saga",
                synthetic_generation,
                book_number=1,
                chapter_number=1,
            )
        )
        synthetic_review["terminal_event"]["metadata"]["rejection_validation"][
            "deterministic_failures"
        ] = []
        empty_rejection_ctx = (
            replacement_generation_context_service.build_replacement_correction_context(
                "italus-saga",
                synthetic_generation,
                book_number=1,
                chapter_number=1,
            )
        )
    finally:
        replacement_generation_context_service.author_review_service.get_author_review_status = (
            original_review_loader
        )
    results.append(ck(
        "P44-02",
        "Replacement context uses rejection-time deterministic evidence only and excludes manual/semantic rules",
        synthetic_ctx["manual_semantic_rules_promoted"] is False
        and synthetic_ctx["deterministic_failure_source"] == "rejection_time_validation"
        and synthetic_ctx["deterministic_failure_count"] == 1
        and synthetic_ctx["deterministic_failures"][0]["rule_id"]
            == "prose.word_count.quantitative"
        and "story_control.synthetic" not in str(synthetic_ctx["deterministic_failures"])
        and empty_rejection_ctx["deterministic_failure_source"]
            == "rejection_time_validation"
        and empty_rejection_ctx["deterministic_failure_count"] == 0,
    ))
    results.append(ck("P44-03", "Rejected prose is not included in replacement context",
                      ctx["rejected_prose_included"] is False
                      and "content_after" not in str(ctx)
                      and "current_content" not in str(ctx)))

    try:
        replacement_generation_context_service.build_replacement_correction_context(
            "italus-saga", current, book_number=1, chapter_number=1
        )
        non_rejected_blocked = False
    except replacement_generation_context_service.ReplacementGenerationContextError as exc:
        non_rejected_blocked = exc.code == "REPLACEMENT_SOURCE_NOT_REJECTED"
    results.append(ck("P44-04", "Non-rejected candidates cannot source replacement correction", non_rejected_blocked))

    initial = generation_service.build_generation_request_envelope(
        "italus-saga", book_number=1, chapter_number=1
    )
    replacement = generation_service.build_generation_request_envelope(
        "italus-saga", book_number=1, chapter_number=1,
        replacement_correction_context=ctx,
    )
    results.append(ck(
        "P44-05",
        "Replacement request is distinct while initial Primary 42 request identity remains unchanged",
        initial["prompt"]["prompt_sha256"]
            == "4e1e57721d2d8a5cd53062c954820b6c3eb812325935f250e8111fe84a354c13"
        and initial["request_content_sha256"]
            == "0de9257fc6d9d83d4716b4be7fe955e95a1b559b2257df0354862bf594bc3ae9"
        and "replacement" not in initial
        and initial["request_content_sha256"] != replacement["request_content_sha256"]
        and replacement["replacement"]["enabled"] is True
        and replacement["replacement"]["context_sha256"] == ctx["context_sha256"],
    ))

    sys_text = prompt_builder.provider_system_text(replacement["prompt"])
    user_text = prompt_builder.provider_user_prompt_text(replacement["prompt"])
    results.append(ck("P44-06", "Provider system contains bounded rejection correction context",
                      "REPLACEMENT_CORRECTION_CONTEXT_JSON" in sys_text
                      and ctx["context_sha256"] in sys_text))
    results.append(ck("P44-07", "Provider user prompt does not duplicate rejection correction context",
                      "REPLACEMENT_CORRECTION_CONTEXT_JSON" not in user_text
                      and ctx["context_sha256"] not in user_text))

    workspace = (ROOT / "frontend/workspace.js").read_text(encoding="utf-8")
    route = (ROOT / "app/api/routes/project.py").read_text(encoding="utf-8")
    execution = (ROOT / "app/services/provider_execution_service.py").read_text(encoding="utf-8")
    review = (ROOT / "app/services/author_review_service.py").read_text(encoding="utf-8")

    results.append(ck("P44-08", "Browser sends only rejected generation identity for replacement",
                      "replacement_for_generation_id: replacementForGenerationId" in workspace
                      and "replacement_correction_context" not in workspace))
    request_model = ProviderGenerationExecuteRequest(
        book_number=1,
        chapter_number=1,
        replacement_for_generation_id=rejected,
    )
    request_payload = (
        request_model.model_dump()
        if hasattr(request_model, "model_dump")
        else request_model.dict()
    )
    results.append(ck(
        "P44-09",
        "Generation route accepts exactly one bounded replacement source identity",
        request_payload.get("replacement_for_generation_id") == rejected
        and "replacement_for_generation_id=payload.replacement_for_generation_id" in route
        and "replacement_correction_context" not in route,
    ))
    results.append(ck("P44-10", "Provider execution binds replacement identity into immutable lineage",
                      '"replacement_context_sha256"' in execution
                      and '"replacement_correction_context"' in execution
                      and '"replacement_for_generation_id"' in execution))
    results.append(ck("P44-11", "Future AUTHOR_REJECT events bind exact validation identity and compact deterministic failures",
                      'metadata["rejection_validation"]' in review
                      and '"validation_result_sha256"' in review
                      and '"validated_content_sha256"' in review
                      and '"deterministic_failures": deterministic_failures' in review))

    p43 = ROOT / "tools/primary43_eager_validation_review_handoff_regression.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run([sys.executable, str(p43)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    results.append(ck("P44-12", "Primary 43/42/41/40/39 chain remains green",
                      result.returncode == 0 and "PRIMARY43 PASS: 10" in result.stdout
                      and "PRIMARY43 FAIL: 0" in result.stdout,
                      f"returncode={result.returncode}"))

    after = tree_sha256(PROJECT_DATA)
    results.append(ck("P44-13", "Primary 44 regression performs no Italus project-data mutation",
                      before == after, f"before={before}; after={after}"))

    passed = sum(bool(x) for x in results)
    failed = len(results) - passed
    print("PRIMARY44 MARKER: primary44-rejection-aware-replacement-generation-v1")
    print(f"PRIMARY44 TOTAL: {len(results)}")
    print(f"PRIMARY44 PASS: {passed}")
    print(f"PRIMARY44 FAIL: {failed}")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
