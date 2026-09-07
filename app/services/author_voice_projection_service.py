"""
Primary 37C bounded Author Voice read projection.

This service reads only Primary 37B Author Voice samples that already passed the
Primary 37A provenance gate. It derives compact deterministic style guidance for
prompt consumption without exposing or copying raw learned prose into generation
requests.

Author Voice remains subordinate to Canon, Story Controls, chapter intent, and
character voice. This service never mutates Canon, continuity, provenance, or the
Author Voice source store.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any

from app.services import author_voice_store_service


AUTHOR_VOICE_PROJECTION_MARKER = "primary37c-author-voice-projection-v1"
AUTHOR_VOICE_PROJECTION_SCHEMA_VERSION = "primary37c_author_voice_projection_v1"
AUTHOR_VOICE_PROJECTION_POLICY_VERSION = "bounded_deterministic_style_projection_v1"

MAX_SOURCE_SAMPLES = 200
MAX_GUIDANCE_ITEMS = 5

_WORD_RE = re.compile(r"\b[\w\u2019'-]+\b", re.UNICODE)
_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)", re.UNICODE)


class AuthorVoiceProjectionError(RuntimeError):
    """Raised when Author Voice projection cannot be constructed safely."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "AUTHOR_VOICE_PROJECTION_FAILED")
        self.details = deepcopy(details or {})

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "details": deepcopy(self.details),
        }


def get_author_voice_projection_contract() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": AUTHOR_VOICE_PROJECTION_MARKER,
        "schema_version": AUTHOR_VOICE_PROJECTION_SCHEMA_VERSION,
        "policy_version": AUTHOR_VOICE_PROJECTION_POLICY_VERSION,
        "source": {
            "service": author_voice_store_service.AUTHOR_VOICE_STORE_MARKER,
            "schema_version": author_voice_store_service.AUTHOR_VOICE_STORE_SCHEMA_VERSION,
            "max_samples": MAX_SOURCE_SAMPLES,
            "raw_prose_in_prompt": False,
        },
        "authority": {
            "reads_author_voice_samples": True,
            "writes_author_voice_samples": False,
            "writes_author_voice_features": False,
            "mutates_canon": False,
            "mutates_approved_continuity": False,
            "mutates_provenance": False,
            "calls_provider": False,
            "prompt_authority": "soft_style_preference_only",
        },
        "precedence": [
            "hard_canon_story_legality",
            "story_control_required_facts_and_prohibitions",
            "chapter_narrative_intent",
            "character_voice",
            "author_voice_style",
        ],
    }


def build_author_voice_projection(
    author_profile_id: str | None = None,
) -> dict[str, Any]:
    """Build the active author's deterministic bounded style projection."""

    try:
        status = author_voice_store_service.get_author_voice_store_status(
            author_profile_id
        )
    except author_voice_store_service.AuthorVoiceStoreError as exc:
        raise AuthorVoiceProjectionError(
            "AUTHOR_VOICE_STORE_STATUS_FAILED",
            "Author Voice store status could not be read safely.",
            details=exc.to_detail(),
        ) from exc

    profile_id = str(status.get("author_profile_id") or "").strip()
    if not profile_id:
        raise AuthorVoiceProjectionError(
            "AUTHOR_VOICE_PROFILE_ID_MISSING",
            "Author Voice projection requires a stable active Author Profile identity.",
        )

    if status.get("present") is not True or int(status.get("sample_count") or 0) <= 0:
        return _empty_projection(profile_id, reason="no_eligible_samples")

    try:
        samples = author_voice_store_service.list_author_voice_samples(
            profile_id,
            limit=MAX_SOURCE_SAMPLES,
        )
    except author_voice_store_service.AuthorVoiceStoreError as exc:
        raise AuthorVoiceProjectionError(
            "AUTHOR_VOICE_SAMPLE_READ_FAILED",
            "Eligible Author Voice samples could not be read safely.",
            details=exc.to_detail(),
        ) from exc

    if not samples:
        return _empty_projection(profile_id, reason="no_eligible_samples")

    return project_author_voice_samples(profile_id, samples)


def project_author_voice_samples(
    author_profile_id: str,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure deterministic projection helper used by runtime and validation."""

    profile_id = str(author_profile_id or "").strip()
    if not profile_id:
        raise AuthorVoiceProjectionError(
            "AUTHOR_VOICE_PROFILE_ID_MISSING",
            "Author Voice projection requires a stable Author Profile identity.",
        )
    if not isinstance(samples, list):
        raise AuthorVoiceProjectionError(
            "AUTHOR_VOICE_SAMPLE_SET_INVALID",
            "Author Voice samples must be supplied as a list.",
        )

    bounded_samples = samples[:MAX_SOURCE_SAMPLES]
    normalized: list[dict[str, Any]] = []
    texts: list[str] = []

    for sample in bounded_samples:
        if not isinstance(sample, dict):
            raise AuthorVoiceProjectionError(
                "AUTHOR_VOICE_SAMPLE_INVALID",
                "Author Voice sample evidence must be an object.",
            )
        sample_profile = str(sample.get("author_profile_id") or "").strip()
        if sample_profile != profile_id:
            raise AuthorVoiceProjectionError(
                "AUTHOR_VOICE_SAMPLE_PROFILE_MISMATCH",
                "Author Voice sample identity does not match the active Author Profile.",
            )

        sample_id = _required_text(sample.get("sample_id"), "sample_id")
        project_id = _required_text(sample.get("project_id"), "project_id")
        generation_id = _required_text(sample.get("generation_id"), "generation_id")
        accepted_sha256 = _required_sha256(
            sample.get("accepted_content_sha256"),
            "accepted_content_sha256",
        )
        content = str(sample.get("accepted_content") or "")
        if not content:
            raise AuthorVoiceProjectionError(
                "AUTHOR_VOICE_SAMPLE_CONTENT_MISSING",
                "Eligible Author Voice sample content is missing.",
                details={"sample_id": sample_id},
            )
        actual_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_sha256 != accepted_sha256:
            raise AuthorVoiceProjectionError(
                "AUTHOR_VOICE_SAMPLE_HASH_MISMATCH",
                "Author Voice sample prose no longer matches its accepted content hash.",
                details={"sample_id": sample_id},
            )

        try:
            awarded_level = int(sample.get("awarded_level"))
        except (TypeError, ValueError) as exc:
            raise AuthorVoiceProjectionError(
                "AUTHOR_VOICE_SAMPLE_LEVEL_INVALID",
                "Author Voice sample provenance level is invalid.",
                details={"sample_id": sample_id},
            ) from exc
        if awarded_level not in (3, 4):
            raise AuthorVoiceProjectionError(
                "AUTHOR_VOICE_SAMPLE_LEVEL_INELIGIBLE",
                "Author Voice projection may consume only Primary 37B eligible levels 3 or 4.",
                details={"sample_id": sample_id, "awarded_level": awarded_level},
            )

        normalized.append(
            {
                "sample_id": sample_id,
                "project_id": project_id,
                "generation_id": generation_id,
                "accepted_content_sha256": accepted_sha256,
                "awarded_level": awarded_level,
            }
        )
        texts.append(content)

    if not normalized:
        return _empty_projection(profile_id, reason="no_eligible_samples")

    metrics = _derive_metrics(texts)
    guidance = _guidance_from_metrics(metrics)[:MAX_GUIDANCE_ITEMS]
    source_set_sha256 = _sha256_json(normalized)

    projection_core = {
        "service": AUTHOR_VOICE_PROJECTION_MARKER,
        "schema_version": AUTHOR_VOICE_PROJECTION_SCHEMA_VERSION,
        "policy_version": AUTHOR_VOICE_PROJECTION_POLICY_VERSION,
        "author_profile_id": profile_id,
        "available": True,
        "sample_count": len(normalized),
        "project_count": len({item["project_id"] for item in normalized}),
        "source_set_sha256": source_set_sha256,
        "confidence": _confidence_label(
            sample_count=len(normalized),
            word_count=int(metrics["word_count"]),
        ),
        "metrics": metrics,
        "prompt_guidance": guidance,
        "raw_prose_included": False,
        "precedence": get_author_voice_projection_contract()["precedence"],
    }
    projection_core["projection_sha256"] = _sha256_json(projection_core)
    return projection_core


def prompt_safe_author_voice_style_context(
    projection: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the only Author Voice subset allowed into the provider prompt."""

    source = projection if isinstance(projection, dict) else {}
    available = source.get("available") is True
    guidance = source.get("prompt_guidance")
    if not isinstance(guidance, list):
        guidance = []

    safe_guidance = [
        str(item).strip()
        for item in guidance[:MAX_GUIDANCE_ITEMS]
        if str(item).strip()
    ]

    return {
        "authority": "soft_style_preference_only",
        "available": available and bool(safe_guidance),
        "author_profile_id": str(source.get("author_profile_id") or ""),
        "projection_schema_version": str(source.get("schema_version") or ""),
        "projection_sha256": str(source.get("projection_sha256") or ""),
        "confidence": str(source.get("confidence") or "none"),
        "guidance": safe_guidance if available else [],
        "raw_author_prose_included": False,
        "precedence": [
            "hard_canon_story_legality",
            "story_control_required_facts_and_prohibitions",
            "chapter_narrative_intent",
            "character_voice",
            "author_voice_style",
        ],
    }


def _empty_projection(profile_id: str, *, reason: str) -> dict[str, Any]:
    source_set_sha256 = _sha256_json([])
    projection = {
        "service": AUTHOR_VOICE_PROJECTION_MARKER,
        "schema_version": AUTHOR_VOICE_PROJECTION_SCHEMA_VERSION,
        "policy_version": AUTHOR_VOICE_PROJECTION_POLICY_VERSION,
        "author_profile_id": profile_id,
        "available": False,
        "reason": str(reason),
        "sample_count": 0,
        "project_count": 0,
        "source_set_sha256": source_set_sha256,
        "confidence": "none",
        "metrics": {},
        "prompt_guidance": [],
        "raw_prose_included": False,
        "precedence": get_author_voice_projection_contract()["precedence"],
    }
    projection["projection_sha256"] = _sha256_json(projection)
    return projection


def _derive_metrics(texts: list[str]) -> dict[str, Any]:
    combined = "\n\n".join(texts)
    words = _WORD_RE.findall(combined)
    lower_words = [word.casefold() for word in words]
    sentences = [
        _WORD_RE.findall(match.group(0))
        for match in _SENTENCE_RE.finditer(combined)
    ]
    sentence_lengths = [len(items) for items in sentences if items]
    paragraphs = [
        _WORD_RE.findall(block)
        for block in re.split(r"\n\s*\n", combined)
        if block.strip()
    ]
    paragraph_lengths = [len(items) for items in paragraphs if items]

    word_count = len(words)
    sentence_count = len(sentence_lengths)
    paragraph_count = len(paragraph_lengths)

    quote_chars = combined.count('"') + combined.count("\u201c") + combined.count("\u201d")
    punctuation_count = max(
        1,
        sum(combined.count(mark) for mark in ".!?;:\u2014"),
    )

    metrics = {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "paragraph_count": paragraph_count,
        "average_sentence_words": _rounded_mean(sentence_lengths),
        "sentence_length_variation": _rounded_cv(sentence_lengths),
        "average_paragraph_words": _rounded_mean(paragraph_lengths),
        "lexical_diversity": round(
            (len(set(lower_words)) / word_count) if word_count else 0.0,
            4,
        ),
        "quote_marks_per_1000_words": _per_thousand(quote_chars, word_count),
        "em_dash_per_1000_words": _per_thousand(combined.count("\u2014"), word_count),
        "semicolon_per_1000_words": _per_thousand(combined.count(";"), word_count),
        "colon_per_1000_words": _per_thousand(combined.count(":"), word_count),
        "question_per_1000_words": _per_thousand(combined.count("?"), word_count),
        "exclamation_per_1000_words": _per_thousand(combined.count("!"), word_count),
        "punctuation_density": round(punctuation_count / max(1, len(combined)), 5),
    }
    return metrics


def _guidance_from_metrics(metrics: dict[str, Any]) -> list[str]:
    guidance: list[str] = []

    average_sentence = float(metrics.get("average_sentence_words") or 0.0)
    if average_sentence <= 12:
        guidance.append("Favor concise sentences and direct rhythmic movement.")
    elif average_sentence <= 22:
        guidance.append("Favor medium-length sentences with a balanced narrative rhythm.")
    else:
        guidance.append("Favor longer, flowing sentences while preserving clarity.")

    variation = float(metrics.get("sentence_length_variation") or 0.0)
    if variation >= 0.55:
        guidance.append("Mix noticeably short and long sentences to preserve rhythmic variation.")
    elif variation <= 0.25:
        guidance.append("Keep sentence rhythm relatively steady rather than highly jagged.")
    else:
        guidance.append("Use moderate sentence-length variation.")

    average_paragraph = float(metrics.get("average_paragraph_words") or 0.0)
    if average_paragraph <= 45:
        guidance.append("Prefer compact paragraphs and frequent visual breaks.")
    elif average_paragraph >= 100:
        guidance.append("Allow extended paragraphs when the narrative thought remains coherent.")
    else:
        guidance.append("Use moderate paragraph length with clear thought boundaries.")

    quote_rate = float(metrics.get("quote_marks_per_1000_words") or 0.0)
    if quote_rate >= 18:
        guidance.append("Maintain a dialogue-forward balance when the chapter context permits it.")
    elif quote_rate <= 4:
        guidance.append("Maintain a narrative-forward balance; use dialogue only when context calls for it.")
    else:
        guidance.append("Balance narrative and dialogue according to the chapter context.")

    punctuation_tendencies: list[str] = []
    if float(metrics.get("em_dash_per_1000_words") or 0.0) >= 2.0:
        punctuation_tendencies.append("em-dash interruptions")
    if float(metrics.get("semicolon_per_1000_words") or 0.0) >= 1.5:
        punctuation_tendencies.append("occasional semicolon-linked clauses")
    if float(metrics.get("question_per_1000_words") or 0.0) >= 2.0:
        punctuation_tendencies.append("interrogative beats")

    if punctuation_tendencies:
        guidance.append(
            "Where natural, preserve observed punctuation tendencies such as "
            + ", ".join(punctuation_tendencies)
            + "."
        )

    return guidance


def _confidence_label(*, sample_count: int, word_count: int) -> str:
    if sample_count >= 8 and word_count >= 4000:
        return "established"
    if sample_count >= 3 and word_count >= 1200:
        return "developing"
    return "limited"


def _rounded_mean(values: list[int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def _rounded_cv(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean <= 0:
        return 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return round(math.sqrt(variance) / mean, 4)


def _per_thousand(count: int, word_count: int) -> float:
    return round((count * 1000.0 / word_count) if word_count else 0.0, 3)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AuthorVoiceProjectionError(
            "AUTHOR_VOICE_SAMPLE_IDENTITY_MISSING",
            f"Author Voice sample requires {field_name}.",
        )
    return text


def _required_sha256(value: Any, field_name: str) -> str:
    digest = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise AuthorVoiceProjectionError(
            "AUTHOR_VOICE_SAMPLE_HASH_INVALID",
            f"Author Voice sample requires a valid SHA-256 for {field_name}.",
        )
    return digest


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
