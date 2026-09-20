from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from app import prompt_builder
from app.services import generation_service, provider_direct_generation_service


MARKER = "primary42-bounded-generation-prompt-authority-regression-v1"


class RegressionSuite:
    def __init__(self) -> None:
        self.pass_count = 0
        self.fail_count = 0

    def check(self, code: str, message: str, condition: bool, *, details: str = "") -> None:
        if condition:
            self.pass_count += 1
            suffix = f" :: {details}" if details else ""
            print(f"{code} PASS - {message}{suffix}")
        else:
            self.fail_count += 1
            suffix = f" :: {details}" if details else ""
            print(f"{code} FAIL - {message}{suffix}")

    def equal(self, code: str, message: str, actual: Any, expected: Any) -> None:
        self.check(code, message, actual == expected, details=f"actual={actual!r}; expected={expected!r}")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tree_fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        h.update(b"\0")
    return h.hexdigest()


class _Headers:
    def get(self, name: str) -> str | None:
        return "req_primary42" if str(name).lower() == "x-request-id" else None


class _Response:
    status = 200
    headers = _Headers()

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def read(self, _limit: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


def _capture_provider_bodies() -> list[tuple[str, dict[str, Any]]]:
    captured: list[tuple[str, dict[str, Any]]] = []

    def opener(request: Any, timeout: float) -> _Response:
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        captured.append((str(request.full_url), body))
        if "anthropic.com" in str(request.full_url):
            return _Response(
                {
                    "id": "msg_primary42",
                    "model": "claude-test",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                }
            )
        return _Response(
            {
                "id": "resp_primary42",
                "model": "gpt-test",
                "status": "completed",
                "output": [{"content": [{"type": "output_text", "text": "ok"}]}],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "input_tokens_details": {"cached_tokens": 0},
                },
            }
        )

    provider_direct_generation_service.execute_direct_generation(
        provider_id="anthropic",
        model_id="claude-test",
        system_text="SYSTEM AUTHORITY",
        prompt_text="USER PROMPT",
        max_output_tokens=100,
        api_key="test-secret",
        opener=opener,
    )
    provider_direct_generation_service.execute_direct_generation(
        provider_id="openai",
        model_id="gpt-test",
        system_text="SYSTEM AUTHORITY",
        prompt_text="USER PROMPT",
        max_output_tokens=100,
        api_key="test-secret",
        opener=opener,
    )
    return captured


def _run_suite() -> int:
    suite = RegressionSuite()
    repo = _repo_root()
    project_data = repo / "data" / "projects" / "italus-saga"
    before = _tree_fingerprint(project_data)

    envelope = generation_service.build_generation_request_envelope(
        "italus-saga",
        book_number=1,
        chapter_number=1,
    )
    prompt = dict(envelope.get("prompt") or {})
    reference = dict(prompt.get("reference_context") or {})
    provider_system = dict(prompt.get("provider_system") or {})
    guardrails = dict(provider_system.get("generation_guardrails") or {})
    system_text = prompt_builder.provider_system_text(prompt)
    user_text = prompt_builder.provider_user_prompt_text(prompt)
    source_artifacts = dict(envelope.get("source_artifacts") or {})
    book_source = dict(source_artifacts.get("book_knowledge") or {})
    token_planning = dict(envelope.get("token_planning") or {})

    suite.equal(
        "P42-01",
        "Prompt schema is the Primary 42 bounded provider contract",
        prompt.get("schema_version"),
        "project_local_generation_prompt_v3",
    )
    suite.check(
        "P42-02",
        "Raw Book Knowledge is absent from provider reference context",
        reference.get("book_knowledge_raw_text_included") is False
        and "book_knowledge" not in reference,
        details=f"reference_keys={sorted(reference)}",
    )
    suite.check(
        "P42-03",
        "Book Knowledge remains an immutable upstream lineage dependency",
        bool(book_source.get("project_relative_path"))
        and bool(book_source.get("sha256"))
        and bool(book_source.get("dependency_set_sha256")),
        details=f"book_source={book_source!r}",
    )
    suite.check(
        "P42-04",
        "System authority projects chapter restrictions and forbidden-future knowledge",
        len(list(guardrails.get("chapter_restrictions") or [])) == 4
        and len(list(guardrails.get("forbidden_future_knowledge") or [])) == 4,
        details=(
            f"chapter_restrictions={len(list(guardrails.get('chapter_restrictions') or []))}; "
            f"forbidden={len(list(guardrails.get('forbidden_future_knowledge') or []))}"
        ),
    )
    suite.check(
        "P42-05",
        "System authority contains the active Story Control and knowledge ceiling",
        len(list(guardrails.get("story_controls") or [])) == 1
        and "589 storm fragment" in system_text
        and "Book 1 Chapter 1 storm fragment only" in system_text,
    )
    suite.check(
        "P42-06",
        "System authority contains required event sequence and participant/location obligations",
        len(list(guardrails.get("required_event_sequence") or [])) == 2
        and len(list(guardrails.get("required_participants") or [])) == 3
        and len(list(guardrails.get("required_locations") or [])) == 1
        and "Open in 789" in system_text
        and "brief external analepsis to 589" in system_text,
    )
    prose = dict(guardrails.get("hard_prose_metrics") or {})
    suite.check(
        "P42-07",
        "System authority contains deterministic prose limits",
        ((prose.get("word_count") or {}).get("minimum") == 4000)
        and ((prose.get("em_dashes") or {}).get("hard_maximum") == 8)
        and ((prose.get("colons") or {}).get("hard_maximum") == 3)
        and ((prose.get("ellipses") or {}).get("hard_maximum") == 4)
        and ((prose.get("similes") or {}).get("hard_maximum") == 12),
        details=f"metrics={prose!r}",
    )
    suite.check(
        "P42-08",
        "Provider system instruction explicitly outranks conflicting reference facts",
        "The presence of a fact in reference material does not authorize disclosure." in system_text
        and "hard system-level constraints" in system_text
        and "override any conflicting or broader fact" in system_text,
    )
    suite.check(
        "P42-09",
        "Provider-bound system/user hashes match exact serialized content",
        prompt.get("provider_system_sha256") == _sha256_text(system_text)
        and prompt.get("provider_user_prompt_sha256") == _sha256_text(user_text),
        details=(
            f"system_sha={prompt.get('provider_system_sha256')}; "
            f"user_sha={prompt.get('provider_user_prompt_sha256')}"
        ),
    )
    suite.check(
        "P42-10",
        "Book 1 Chapter 1 provider input is materially bounded",
        int(token_planning.get("exact_request_locally_estimated_input_tokens") or 0) < 25000
        and int(token_planning.get("provider_bound_input_utf8_bytes") or 0) < 100000,
        details=(
            f"estimated_tokens={token_planning.get('exact_request_locally_estimated_input_tokens')}; "
            f"provider_bytes={token_planning.get('provider_bound_input_utf8_bytes')}"
        ),
    )

    captured = _capture_provider_bodies()
    anthropic = captured[0][1]
    openai = captured[1][1]
    suite.check(
        "P42-11",
        "Anthropic request uses the provider system authority surface",
        anthropic.get("system") == "SYSTEM AUTHORITY"
        and ((anthropic.get("messages") or [{}])[0]).get("content") == "USER PROMPT",
        details=f"keys={sorted(anthropic)}",
    )
    suite.check(
        "P42-12",
        "OpenAI request uses the provider instructions authority surface",
        openai.get("instructions") == "SYSTEM AUTHORITY"
        and openai.get("input") == "USER PROMPT",
        details=f"keys={sorted(openai)}",
    )

    execution_source = (repo / "app" / "services" / "provider_execution_service.py").read_text(
        encoding="utf-8"
    )
    suite.check(
        "P42-13",
        "Provider execution binds exact system/user prompt hashes into execution lineage",
        '"provider_system_sha256": provider_system_sha256' in execution_source
        and '"provider_user_prompt_sha256": provider_user_prompt_sha256' in execution_source
        and "system_text=system_text" in execution_source,
    )

    p40 = subprocess.run(
        [sys.executable, "tools/primary40_full_migration_regression.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )
    suite.check(
        "P42-14",
        "Primary 40/40C/39 chain remains green with Primary 41 retirement retained",
        p40.returncode == 0
        and "PRIMARY40 PASS: 33" in p40.stdout
        and "PRIMARY39 REGRESSION: PASS (72/72)" in p40.stdout
        and "PRIMARY40C ISOLATION: PASS" in p40.stdout
        and "PRIMARY41 LEGACY RETIREMENT: COMPLETE" in p40.stdout,
        details=f"returncode={p40.returncode}; stdout_tail={p40.stdout[-1600:]!r}",
    )

    after = _tree_fingerprint(project_data)
    suite.equal(
        "P42-15",
        "Primary 42 sanity validation does not mutate Italus project data",
        after,
        before,
    )

    print(f"PRIMARY42 MARKER: {MARKER}")
    print("PRIMARY42 TOTAL: 15")
    print(f"PRIMARY42 PASS: {suite.pass_count}")
    print(f"PRIMARY42 FAIL: {suite.fail_count}")
    print("LIVE PROVIDER CALLS: NONE")
    print("REAL PROJECT DATA MUTATION: NONE")
    return 0 if suite.fail_count == 0 else 1


def main() -> int:
    return _run_suite()


if __name__ == "__main__":
    raise SystemExit(main())
