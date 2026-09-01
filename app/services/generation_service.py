"""Provider-neutral generation request construction for Primary 32.

This service builds a reproducible GenerationRequestEnvelope from already-current
project-local Book and Chapter Knowledge artifacts.  It is deliberately
side-effect free: no provider is selected or called, no budget is reserved, no
provenance/continuity is written, and no generation identifier is minted.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app import prompt_builder
from app.projects import project_loader
from app.projects.project_context import ProjectContext, build_project_context
from app.services import (
    book_knowledge_pack_service,
    chapter_knowledge_pack_service,
    generation_control_service,
)


GENERATION_REQUEST_SERVICE_MARKER = (
    "provider-neutral-generation-request-primary32-20260831"
)
GENERATION_REQUEST_SCHEMA_VERSION = "generation_request_envelope_v1"
LOCAL_INPUT_ESTIMATOR_VERSION = "utf8_bytes_div_4_v1"
OUTPUT_POLICY_VERSION = "prose_goal_x1_30_with_x1_25_headroom_v1"


class GenerationRequestBuildError(RuntimeError):
    """Bounded request-construction failure with a stable reason code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.details = dict(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


def build_generation_request_envelope(
    project_id: str,
    *,
    book_number: int,
    chapter_number: int,
) -> dict[str, Any]:
    """Build, but do not persist or execute, a provider-neutral request."""

    manifest_obj = project_loader.load_manifest(project_id)
    manifest = manifest_obj.to_dict()
    context = build_project_context(manifest_obj)

    book_number = _validated_position(
        book_number,
        "book_number",
        maximum=max(1, int(manifest.get("book_count") or 1)),
    )
    chapter_number = _validated_position(
        chapter_number,
        "chapter_number",
        maximum=max(1, int(manifest.get("chapters_per_book") or 1)),
    )

    readiness = generation_control_service.get_generation_control_status_for_context(
        context,
        manifest,
        wizard_state=project_loader.load_wizard_state(project_id) or {},
        book_number=book_number,
        chapter_number=chapter_number,
    )
    if readiness.get("upstream_ready") is not True:
        raise GenerationRequestBuildError(
            "generation_request_not_ready",
            "Requested project/book/chapter inputs are not ready for prompt construction.",
            details={
                "book_number": book_number,
                "chapter_number": chapter_number,
                "blockers": list(readiness.get("upstream_blockers") or []),
            },
        )

    dependency_state = readiness.get("dependency_state") or {}
    book_target = dict(dependency_state.get("book_runtime_context") or {})
    chapter_status = dict(dependency_state.get("chapter_knowledge_pack") or {})
    chapter_pack = dict(chapter_status.get("pack") or {})

    if (
        book_target.get("status") != book_knowledge_pack_service.STATUS_CURRENT
        or not book_target.get("sha256")
        or not book_target.get("project_relative_path")
    ):
        raise GenerationRequestBuildError(
            "book_knowledge_not_current",
            "Requested Book Knowledge artifact is not current.",
            details={"book_number": book_number},
        )

    if (
        chapter_status.get("status")
        != chapter_knowledge_pack_service.STATUS_CURRENT
        or chapter_pack.get("current") is not True
        or not chapter_pack.get("sha256")
        or not chapter_pack.get("project_relative_path")
        or not chapter_pack.get("sidecar_sha256")
        or not chapter_pack.get("sidecar_project_relative_path")
    ):
        raise GenerationRequestBuildError(
            "chapter_knowledge_not_current",
            "Requested Chapter Knowledge artifact is not current.",
            details={
                "book_number": book_number,
                "chapter_number": chapter_number,
            },
        )

    book_path = _project_local_file(
        context,
        str(book_target["project_relative_path"]),
        artifact_name="Book Knowledge",
    )
    chapter_path = _project_local_file(
        context,
        str(chapter_pack["project_relative_path"]),
        artifact_name="Chapter Knowledge",
    )
    sidecar_path = _project_local_file(
        context,
        str(chapter_pack["sidecar_project_relative_path"]),
        artifact_name="Chapter Knowledge sidecar",
    )

    book_bytes = book_path.read_bytes()
    chapter_bytes = chapter_path.read_bytes()
    sidecar_bytes = sidecar_path.read_bytes()

    _require_hash(
        book_bytes,
        str(book_target["sha256"]),
        artifact_name="Book Knowledge",
    )
    _require_hash(
        chapter_bytes,
        str(chapter_pack["sha256"]),
        artifact_name="Chapter Knowledge",
    )
    _require_hash(
        sidecar_bytes,
        str(chapter_pack["sidecar_sha256"]),
        artifact_name="Chapter Knowledge sidecar",
    )

    try:
        book_text = book_bytes.decode("utf-8")
        chapter_text = chapter_bytes.decode("utf-8")
        sidecar = json.loads(sidecar_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GenerationRequestBuildError(
            "artifact_content_invalid",
            "A current Knowledge artifact cannot be decoded from its required format.",
        ) from exc

    _validate_sidecar_identity(
        sidecar,
        project_id=context.project_id,
        book_number=book_number,
        chapter_number=chapter_number,
        expected_pack_sha256=str(chapter_pack["sha256"]),
    )

    rulebook = sidecar.get("prose_rulebook") or {}
    metrics = rulebook.get("quantitative_metrics") or {}
    word_count = metrics.get("word_count") or {}
    minimum_words = _positive_contract_int(
        word_count.get("minimum"),
        code="chapter_prompt_contract_missing",
        message="Chapter Knowledge sidecar does not define the prose word-count minimum.",
    )
    project_target_words = _positive_contract_int(
        manifest.get("target_words_per_chapter"),
        code="chapter_prompt_contract_missing",
        message="Project manifest does not define a positive chapter word target.",
    )
    prose_goal_words = max(project_target_words, minimum_words)

    prompt = prompt_builder.build_project_local_generation_prompt(
        book_knowledge_text=book_text,
        chapter_knowledge_text=chapter_text,
        target_words=prose_goal_words,
    )
    canonical_prompt = prompt_builder.canonicalize_project_local_generation_prompt(
        prompt
    )
    prompt_bytes = canonical_prompt.encode("utf-8")
    local_input_tokens = int(math.ceil(len(prompt_bytes) / 4.0))
    estimated_output_tokens = int(math.ceil(prose_goal_words * 1.30))
    requested_output_token_ceiling = int(
        math.ceil(estimated_output_tokens * 1.25)
    )

    source_artifacts = {
        "book_knowledge": {
            "schema_version": book_knowledge_pack_service.BOOK_KNOWLEDGE_PACK_SCHEMA_VERSION,
            "project_relative_path": str(book_target["project_relative_path"]),
            "sha256": str(book_target["sha256"]),
            "dependency_set_sha256": str(
                book_target.get("dependency_set_sha256") or ""
            ),
        },
        "chapter_knowledge": {
            "schema_version": str(
                sidecar.get("schema_version")
                or chapter_knowledge_pack_service.CHAPTER_KNOWLEDGE_PACK_SCHEMA_VERSION
            ),
            "project_relative_path": str(chapter_pack["project_relative_path"]),
            "sha256": str(chapter_pack["sha256"]),
            "sidecar_project_relative_path": str(
                chapter_pack["sidecar_project_relative_path"]
            ),
            "sidecar_sha256": str(chapter_pack["sidecar_sha256"]),
            "dependency_set_sha256": str(
                chapter_status.get("dependency_set_sha256")
                or sidecar.get("dependency_set_sha256")
                or ""
            ),
        },
    }

    target_output = {
        "content_type": "text/plain",
        "project_target_words": project_target_words,
        "prose_rulebook_minimum_words": minimum_words,
        "prose_goal_words": prose_goal_words,
        "estimated_output_tokens": estimated_output_tokens,
        "requested_output_token_ceiling": requested_output_token_ceiling,
        "output_policy_version": OUTPUT_POLICY_VERSION,
    }
    token_planning = {
        "exact_request_locally_estimated_input_tokens": local_input_tokens,
        "canonical_prompt_utf8_bytes": len(prompt_bytes),
        "estimation_method": "ceil(utf8_bytes/4)",
        "estimator_version": LOCAL_INPUT_ESTIMATOR_VERSION,
    }

    request_hash_payload = {
        "schema_version": GENERATION_REQUEST_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "source_artifacts": source_artifacts,
        "prompt_sha256": str(prompt["prompt_sha256"]),
        "target_output": target_output,
        "token_planning": token_planning,
    }
    request_content_sha256 = hashlib.sha256(
        _canonical_json(request_hash_payload).encode("utf-8")
    ).hexdigest()

    return {
        "status": "request_ready",
        "service": GENERATION_REQUEST_SERVICE_MARKER,
        "schema_version": GENERATION_REQUEST_SCHEMA_VERSION,
        "project_id": context.project_id,
        "book_number": book_number,
        "chapter_number": chapter_number,
        "source_artifacts": source_artifacts,
        "prompt": prompt,
        "target_output": target_output,
        "token_planning": token_planning,
        "execution": {
            "request_ready": True,
            "provider_execution_allowed": False,
        },
        "request_content_sha256": request_content_sha256,
    }


def _validated_position(value: Any, field_name: str, *, maximum: int) -> int:
    if isinstance(value, bool):
        parsed = 0
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
    if parsed < 1 or parsed > int(maximum):
        raise GenerationRequestBuildError(
            "request_scope_invalid",
            f"{field_name} must be between 1 and {int(maximum)}.",
            details={field_name: value, "maximum": int(maximum)},
        )
    return parsed


def _project_local_file(
    context: ProjectContext,
    relative_path: str,
    *,
    artifact_name: str,
) -> Path:
    clean = str(relative_path or "").replace("\\", "/").lstrip("/")
    if not clean:
        raise GenerationRequestBuildError(
            "artifact_missing",
            f"{artifact_name} path is missing.",
        )

    project_root = context.project_dir.resolve()
    candidate = (context.project_dir / clean).resolve()
    if candidate == project_root or project_root not in candidate.parents:
        raise GenerationRequestBuildError(
            "artifact_path_invalid",
            f"{artifact_name} path escapes project-local storage.",
            details={"project_relative_path": clean},
        )
    if not candidate.is_file():
        raise GenerationRequestBuildError(
            "artifact_missing",
            f"{artifact_name} file is missing.",
            details={"project_relative_path": clean},
        )
    return candidate


def _require_hash(content: bytes, expected: str, *, artifact_name: str) -> None:
    actual = hashlib.sha256(content).hexdigest()
    if not expected or actual != expected:
        raise GenerationRequestBuildError(
            "artifact_hash_mismatch",
            f"{artifact_name} hash does not match its current status contract.",
            details={"expected_sha256": expected, "actual_sha256": actual},
        )


def _validate_sidecar_identity(
    sidecar: dict[str, Any],
    *,
    project_id: str,
    book_number: int,
    chapter_number: int,
    expected_pack_sha256: str,
) -> None:
    identity_matches = bool(
        str(sidecar.get("project_id") or "") == project_id
        and int(sidecar.get("book_number") or 0) == book_number
        and int(sidecar.get("chapter_number") or 0) == chapter_number
        and str(sidecar.get("pack_sha256") or "") == expected_pack_sha256
    )
    if not identity_matches:
        raise GenerationRequestBuildError(
            "chapter_prompt_contract_missing",
            "Chapter Knowledge sidecar identity does not match the requested chapter.",
            details={
                "book_number": book_number,
                "chapter_number": chapter_number,
            },
        )


def _positive_contract_int(value: Any, *, code: str, message: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    if parsed <= 0:
        raise GenerationRequestBuildError(code, message)
    return parsed


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
