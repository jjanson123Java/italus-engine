from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROJECT_DATA = ROOT / "data" / "projects" / "italus-saga"
GENERATION_ID = "gen_9d9355b6fa08bff0085366f7877995a6"


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
    results: list[bool] = []

    from app.services import (
        candidate_semantic_validation_execution_service as semantic_execution,
        candidate_semantic_validation_store_service as semantic_store,
        candidate_validation_resolution_service,
        validation_service,
    )

    validation = validation_service.validate_generation_candidate(
        "italus-saga", GENERATION_ID
    )
    unresolved = list(validation.get("manual_resolution_required") or [])
    results.append(check(
        "P45-01",
        "Current exact candidate exposes unresolved narrative rules without fabricating verdicts",
        len(unresolved) == 15
        and all(str(item.get("status") or "") == "UNKNOWN" for item in unresolved)
        and all(
            (item.get("details") or {}).get("semantic_verdict_produced") is False
            for item in unresolved
        ),
        f"unresolved={len(unresolved)}",
    ))

    provider_input = semantic_execution.build_semantic_provider_input(validation)
    requested_rules = provider_input["rules"]
    candidate_text = str((validation.get("candidate") or {}).get("text") or "")
    results.append(check(
        "P45-02",
        "Semantic provider input is bounded to exact candidate plus unresolved rule contracts",
        len(requested_rules) == 15
        and candidate_text
        and '"candidate_text":' in provider_input["user_text"]
        and "book_knowledge" not in provider_input["user_text"].lower()
        and str((validation.get("validator_context") or {}).get("candidate_content_sha256") or "")
            in provider_input["user_text"],
    ))

    first_rule = requested_rules[0]["rule_id"]
    bad_payload = {
        "schema_version": "italus_semantic_verdict_v1",
        "verdicts": [
            {
                "rule_id": item["rule_id"],
                "verdict": "FAIL" if item["rule_id"] == first_rule else "UNKNOWN",
                "rationale": "Bounded test rationale.",
                "evidence_excerpts": [],
            }
            for item in requested_rules
        ],
    }
    fail_without_evidence_rejected = False
    try:
        semantic_execution.validate_provider_verdicts(
            json.dumps(bad_payload),
            requested_rules=requested_rules,
            candidate_text=candidate_text,
        )
    except semantic_execution.CandidateSemanticValidationExecutionError as exc:
        fail_without_evidence_rejected = exc.code == "SEMANTIC_FAIL_EVIDENCE_REQUIRED"
    results.append(check(
        "P45-03",
        "Semantic FAIL cannot be accepted without exact candidate evidence",
        fail_without_evidence_rejected,
    ))

    exact_excerpt = candidate_text[:80]
    good_payload = {
        "schema_version": "italus_semantic_verdict_v1",
        "verdicts": [],
    }
    for index, item in enumerate(requested_rules):
        verdict = "UNKNOWN"
        evidence = []
        if index == 0:
            verdict = "PASS"
        elif index == 1:
            verdict = "FAIL"
            evidence = [exact_excerpt]
        good_payload["verdicts"].append({
            "rule_id": item["rule_id"],
            "verdict": verdict,
            "rationale": "Audited bounded regression verdict.",
            "evidence_excerpts": evidence,
        })
    cleaned = semantic_execution.validate_provider_verdicts(
        json.dumps(good_payload),
        requested_rules=requested_rules,
        candidate_text=candidate_text,
    )
    results.append(check(
        "P45-04",
        "Semantic parser accepts only complete PASS/FAIL/UNKNOWN rule coverage with exact FAIL evidence",
        len(cleaned) == len(requested_rules)
        and cleaned[0]["verdict"] == "PASS"
        and cleaned[1]["verdict"] == "FAIL"
        and cleaned[1]["evidence_excerpts"] == [exact_excerpt.strip()],
    ))

    original_exact_map = semantic_store.exact_verdict_map
    try:
        synthetic_map = {}
        for item in cleaned:
            synthetic_map[item["rule_id"]] = {
                **item,
                "semantic_validation_id": "semval_" + "1" * 32,
                "provider_id": "anthropic",
                "model_id": "regression-model",
                "receipt_sha256": "2" * 64,
            }
        semantic_store.exact_verdict_map = lambda *args, **kwargs: synthetic_map
        semantic_validation = validation_service.validate_generation_candidate(
            "italus-saga", GENERATION_ID
        )
    finally:
        semantic_store.exact_verdict_map = original_exact_map

    semantic_rules = {
        item.get("rule_id"): item
        for item in semantic_validation.get("content_rules") or []
    }
    results.append(check(
        "P45-05",
        "Audited semantic verdicts feed the acceptance gate for the exact content",
        semantic_rules[requested_rules[0]["rule_id"]]["status"] == "PASS"
        and semantic_rules[requested_rules[1]["rule_id"]]["status"] == "FAIL"
        and semantic_validation.get("validation_state") == "content_failed"
        and (semantic_rules[requested_rules[1]["rule_id"]].get("details") or {}).get(
            "semantic_verdict_produced"
        ) is True,
    ))

    original_exact_map = semantic_store.exact_verdict_map
    original_resolution_map = validation_service._resolved_rule_map
    try:
        semantic_store.exact_verdict_map = lambda *args, **kwargs: {
            requested_rules[0]["rule_id"]: {
                "rule_id": requested_rules[0]["rule_id"],
                "verdict": "FAIL",
                "rationale": "Synthetic semantic failure.",
                "evidence_excerpts": [exact_excerpt],
                "semantic_validation_id": "semval_" + "3" * 32,
            }
        }
        validation_service._resolved_rule_map = lambda *args, **kwargs: {
            requested_rules[0]["rule_id"]: {
                "decision": candidate_validation_resolution_service.AUTHOR_CONFIRMED_COMPLIANT
            }
        }
        author_override = validation_service.validate_generation_candidate(
            "italus-saga", GENERATION_ID
        )
    finally:
        semantic_store.exact_verdict_map = original_exact_map
        validation_service._resolved_rule_map = original_resolution_map

    override_rule = next(
        item for item in author_override["content_rules"]
        if item.get("rule_id") == requested_rules[0]["rule_id"]
    )
    results.append(check(
        "P45-06",
        "Explicit author resolution remains higher authority than a semantic model verdict",
        override_rule.get("status") == "PASS"
        and (override_rule.get("details") or {}).get("resolution_authority")
            == "author_confirmed_compliant",
    ))

    results.append(check(
        "P45-07",
        "Related-passage retrieval remains non-authoritative when no audited semantic receipt exists",
        all(
            (item.get("details") or {}).get("semantic_verdict_produced") is False
            for item in unresolved
        )
        and validation.get("authority", {}).get("related_passages_are_semantic_verdicts") is False,
    ))

    route_text = (ROOT / "app/api/routes/project.py").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/workspace.js").read_text(encoding="utf-8")
    execution_text = (
        ROOT / "app/services/candidate_semantic_validation_execution_service.py"
    ).read_text(encoding="utf-8")
    store_text = (
        ROOT / "app/services/candidate_semantic_validation_store_service.py"
    ).read_text(encoding="utf-8")

    results.append(check(
        "P45-08",
        "Semantic validation route is explicit and requires an Idempotency-Key",
        "/semantic-validation/execute" in route_text
        and 'http_request.headers.get("Idempotency-Key")' in route_text,
    ))
    results.append(check(
        "P45-09",
        "Workspace requires explicit author confirmation for a separate billable semantic call",
        "Run Semantic Validation (billable)" in workspace
        and "This is a separate billable provider call" in workspace
        and "executeAuthorSemanticValidation()" in workspace,
    ))
    results.append(check(
        "P45-10",
        "Semantic provider usage is cost-accounted but excluded from generation-history discovery",
        '"operation_kind": "semantic_validation"' in execution_text
        and "operationKind === 'generation'" in workspace,
    ))
    results.append(check(
        "P45-11",
        "Semantic receipts are bound to exact content and validator-contract identity with fail-closed intents",
        "content_sha256" in store_text
        and "validator_contract_sha256" in store_text
        and "provider_call_pending" in store_text
        and "receipt_sha256" in store_text,
    ))
    results.append(check(
        "P45-12",
        "Semantic execution reuses exact project provider/model/credential/pricing lineage and preflight",
        "provider_execution_service._current_lineage(project_id)" in execution_text
        and "run_project_provider_preflight" in execution_text
        and "resolve_api_key" in execution_text
        and "execute_direct_generation" in execution_text,
    ))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p44 = ROOT / "tools" / "primary44_rejection_aware_replacement_generation_regression.py"
    result = subprocess.run(
        [sys.executable, str(p44)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    results.append(check(
        "P45-13",
        "Primary 44/43/42/41/40/39 chain remains green",
        result.returncode == 0
        and "PRIMARY44 PASS: 13" in result.stdout
        and "PRIMARY44 FAIL: 0" in result.stdout,
        f"returncode={result.returncode}",
    ))

    after = tree_sha256(PROJECT_DATA)
    results.append(check(
        "P45-14",
        "Primary 45 regression performs no real Italus project-data mutation",
        before == after,
        f"before={before}; after={after}",
    ))

    passed = sum(results)
    failed = len(results) - passed
    print("PRIMARY45 MARKER: primary45-audited-semantic-validation-regression-v1")
    print(f"PRIMARY45 TOTAL: {len(results)}")
    print(f"PRIMARY45 PASS: {passed}")
    print(f"PRIMARY45 FAIL: {failed}")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
