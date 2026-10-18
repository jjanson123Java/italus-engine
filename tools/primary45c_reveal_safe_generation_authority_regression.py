from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DATA = ROOT / "data" / "projects" / "italus-saga"
MARKER = "primary45c-reveal-safe-generation-authority-regression-v1"


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


def ck(code: str, label: str, ok: bool, detail: str = "") -> bool:
    print(f"{code} {'PASS' if ok else 'FAIL'} - {label}" + (f" :: {detail}" if detail else ""))
    return bool(ok)


def run() -> int:
    before = tree_sha256(PROJECT_DATA)
    results: list[bool] = []

    from app import prompt_builder
    from app.services import (
        generation_knowledge_projection_service,
        generation_quality_gate_service,
        generation_service,
        replacement_generation_context_service,
    )

    envelope = generation_service.build_generation_request_envelope(
        "italus-saga", book_number=1, chapter_number=1
    )
    prompt = envelope["prompt"]
    reference = prompt["reference_context"]["chapter_knowledge"]
    user_text = prompt_builder.provider_user_prompt_text(prompt)
    system_text = prompt_builder.provider_system_text(prompt)

    results.append(ck(
        "P45C-01",
        "Provider reference is a reveal-safe projection rather than raw Chapter Knowledge",
        prompt.get("schema_version") == "project_local_generation_prompt_v4"
        and reference.get("source_kind") == "reveal_safe_generation_projection"
        and reference.get("raw_chapter_knowledge_included") is False
        and (envelope["source_artifacts"]["chapter_knowledge"] or {}).get(
            "raw_chapter_knowledge_in_provider_input"
        ) is False,
    ))

    forbidden_literals = [
        "approximately 39",
        "39 years old",
        "born approximately 550",
    ]
    broad_future_threads = [
        "farovald-nerve-reflex",
        "farovald-unaging-face",
        "farovald-perimeter-pact",
    ]
    results.append(ck(
        "P45C-02",
        "Provider user reference excludes known Farovald age/birth facts and inactive reveal threads",
        not any(item.lower() in user_text.lower() for item in forbidden_literals)
        and not any(item.lower() in user_text.lower() for item in broad_future_threads),
    ))

    results.append(ck(
        "P45C-03",
        "Reveal-safe user reference stays bounded independently of required prose authority",
        len(user_text.encode("utf-8")) < 24000
        and len(user_text.encode("utf-8")) < len(
            (ROOT / "data/projects/italus-saga/canon_packs/chapter_knowledge_pack/book_01_chapter_001.md").read_bytes()
        )
        and bool(envelope["token_planning"]["exact_request_locally_estimated_input_tokens"] > 0),
        detail=(
            f"estimated_tokens={envelope['token_planning']['exact_request_locally_estimated_input_tokens']}; "
            f"bytes={envelope['token_planning']['provider_bound_input_utf8_bytes']}"
        ),
    ))

    provider_guardrails = dict(prompt.get("provider_system", {}).get("generation_guardrails") or {})
    provider_controls = list(provider_guardrails.get("story_controls") or [])
    results.append(ck(
        "P45C-04",
        "Active Story Control identity and safe knowledge boundary survive without validator-only disclosure instructions",
        len(provider_controls) == 1
        and all(isinstance(item, dict) for item in provider_controls)
        and all("instruction" not in item and "forbidden_assertions" not in item for item in provider_controls)
        and "story-control-43694f1e3338401d" in system_text
        and "chapter_restrictions" not in provider_guardrails
        and "forbidden_future_knowledge" not in provider_guardrails
        and bool(provider_guardrails.get("authority_rules")),
    ))

    results.append(ck(
        "P45C-05",
        "Required events, participants, locations, and POV remain available",
        "Open in 789" in system_text
        and "brief external analepsis to 589" in system_text
        and '"label":"Luca"' in system_text
        and '"label":"Farovald"' in system_text
        and "Pollino / Southern Italy" in system_text
        and "third_person_omniscient" in system_text,
    ))

    raw_chapter = (
        ROOT
        / "data/projects/italus-saga/canon_packs/chapter_knowledge_pack/book_01_chapter_001.md"
    ).read_text(encoding="utf-8")
    try:
        generation_knowledge_projection_service.assert_provider_reference_safe(
            raw_chapter,
            raw_chapter_text=raw_chapter,
            local_sensitive_literals=[],
        )
        raw_blocked = False
    except generation_knowledge_projection_service.GenerationKnowledgeProjectionError:
        raw_blocked = True
    results.append(ck(
        "P45C-06",
        "Pre-spend input guard fails closed if raw Chapter Knowledge reaches provider reference",
        raw_blocked,
    ))

    rejected = "gen_9d9355b6fa08bff0085366f7877995a6"
    correction = replacement_generation_context_service.build_replacement_correction_context(
        "italus-saga", rejected, book_number=1, chapter_number=1
    )
    expected_semantic_failures = {
        "chapter.restriction.622f7978c1703ffd",
        "chapter.restriction.f50c72cb8cb9710f",
        "chapter.restriction.d8ac20441bd227c3",
        "reveal.forbidden_future.4242585dd085fee8",
        "reveal.forbidden_future.5720968dbb75143d",
        "story_control.story-control-43694f1e3338401d.compliance",
    }
    actual_semantic_failures = {
        str(item.get("rule_id") or "")
        for item in correction.get("audited_semantic_failures") or []
    }
    results.append(ck(
        "P45C-07",
        "Replacement correction promotes the six exact-content audited semantic FAIL verdicts",
        correction.get("audited_semantic_failure_count") == 6
        and actual_semantic_failures == expected_semantic_failures,
        detail=f"rules={sorted(actual_semantic_failures)}",
    ))

    results.append(ck(
        "P45C-08",
        "UNKNOWN semantic items and rejected prose remain excluded from replacement correction",
        correction.get("unknown_semantic_rules_promoted") is False
        and correction.get("rejected_prose_included") is False
        and "content_after" not in str(correction)
        and "evidence_excerpts" not in str(correction)
        and "reveal.forbidden_future.1be440df3d0fce1c"
            not in actual_semantic_failures,
    ))

    replacement = generation_service.build_generation_request_envelope(
        "italus-saga",
        book_number=1,
        chapter_number=1,
        replacement_correction_context=correction,
    )
    replacement_system = prompt_builder.provider_system_text(replacement["prompt"])
    replacement_user = prompt_builder.provider_user_prompt_text(replacement["prompt"])
    results.append(ck(
        "P45C-09",
        "Audited semantic failures reach only provider system correction authority",
        "audited_semantic_failures" in replacement_system
        and all(rule_id in replacement_system for rule_id in expected_semantic_failures)
        and "audited_semantic_failures" not in replacement_user,
    ))

    receipt_path = (
        ROOT
        / "data/projects/italus-saga/usage/provider_generation_receipts/"
          "gen_61496be2bc5b92468338ad360e337c66.json"
    )
    bad_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    metrics = prompt["provider_system"]["generation_guardrails"]["hard_prose_metrics"]
    bad_report = generation_quality_gate_service.evaluate_output(
        bad_receipt["output_text"],
        stop_reason=bad_receipt.get("stop_reason"),
        hard_prose_metrics=metrics,
    )
    blocker_codes = {
        str(item.get("code") or "") for item in bad_report.get("blockers") or []
    }
    bad_metrics = {
        str(item.get("metric") or "")
        for item in bad_report.get("blockers") or []
        if item.get("code") == "DETERMINISTIC_PROSE_FAILURE"
    }
    results.append(ck(
        "P45C-10",
        "Known truncated replacement is rejected by completion gate",
        bad_report.get("passed") is False
        and "INCOMPLETE_PROVIDER_OUTPUT" in blocker_codes
        and str(bad_receipt.get("stop_reason") or "") == "max_tokens",
    ))

    results.append(ck(
        "P45C-11",
        "Known replacement deterministic prose violations are rejected before author-review promotion",
        {"em_dashes", "colons"}.issubset(bad_metrics),
        detail=f"failed_metrics={sorted(bad_metrics)}",
    ))

    compliant_text = " ".join(["word"] * 4000)
    good_report = generation_quality_gate_service.evaluate_output(
        compliant_text,
        stop_reason="end_turn",
        hard_prose_metrics=metrics,
    )
    results.append(ck(
        "P45C-12",
        "Completed deterministically compliant provider output remains promotable",
        good_report.get("passed") is True
        and not (good_report.get("blockers") or []),
    ))

    execution_source = (
        ROOT / "app/services/provider_execution_service.py"
    ).read_text(encoding="utf-8")
    final_gate_index = execution_source.rfind(
        "quality_gate = _quality_gate_receipt("
    )
    final_origin_index = execution_source.rfind(
        "model_origin = _ensure_model_origin("
    )
    results.append(ck(
        "P45C-13",
        "Provider execution records quality gate in receipt and gates before MODEL-origin promotion",
        '"generation_quality_gate": quality_gate_report' in execution_source
        and final_gate_index >= 0
        and final_origin_index > final_gate_index,
    ))

    workspace_source = (ROOT / "frontend/workspace.js").read_text(encoding="utf-8")
    results.append(ck(
        "P45C-14",
        "Provider replay paths re-run quality gate and author history hides failed/truncated generations",
        execution_source.count("_quality_gate_receipt(") >= 4
        and execution_source.count("model_origin = _ensure_model_origin(") >= 3
        and "generation_quality_gate_passed" in workspace_source
        and "provider_stop_reason" in workspace_source
        and "max_tokens" in workspace_source,
    ))

    p45a = subprocess.run(
        [sys.executable, "tools/primary45a_author_validation_surface_cleanup_regression.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    results.append(ck(
        "P45C-15",
        "Primary 45A/45/44/43/42/41/40/39 chain remains green",
        p45a.returncode == 0
        and "PRIMARY45A PASS: 13" in p45a.stdout
        and "PRIMARY45A FAIL: 0" in p45a.stdout,
        detail=f"returncode={p45a.returncode}",
    ))

    after = tree_sha256(PROJECT_DATA)
    results.append(ck(
        "P45C-16",
        "Primary 45C regression performs no real Italus project-data mutation",
        before == after,
        detail=f"before={before}; after={after}",
    ))

    passed = sum(results)
    failed = len(results) - passed
    print(f"PRIMARY45C MARKER: {MARKER}")
    print(f"PRIMARY45C TOTAL: {len(results)}")
    print(f"PRIMARY45C PASS: {passed}")
    print(f"PRIMARY45C FAIL: {failed}")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
