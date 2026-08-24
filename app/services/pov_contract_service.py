"""
Structured Point-of-View contract for chapter planning and prompt-facing packs.

This module owns POV vocabulary, cardinality rules, and prompt-facing narrative
access rules. It does not select Canon, generate prose, call providers, or
persist Chapter Plan state.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


POV_CONTRACT_VERSION = "pov_contract_v1"

POV_TYPE_FIRST_PERSON = "first_person"
POV_TYPE_SECOND_PERSON = "second_person"
POV_TYPE_THIRD_PERSON_LIMITED = "third_person_limited"
POV_TYPE_THIRD_PERSON_OMNISCIENT = "third_person_omniscient"
POV_TYPE_THIRD_PERSON_OBJECTIVE = "third_person_objective"
POV_TYPE_CHORAL_COLLECTIVE = "choral_collective"

POV_TYPE_LABELS = {
    POV_TYPE_FIRST_PERSON: "First-Person",
    POV_TYPE_SECOND_PERSON: "Second-Person",
    POV_TYPE_THIRD_PERSON_LIMITED: "Third-Person Limited",
    POV_TYPE_THIRD_PERSON_OMNISCIENT: "Third-Person Omniscient",
    POV_TYPE_THIRD_PERSON_OBJECTIVE: "Third-Person Objective",
    POV_TYPE_CHORAL_COLLECTIVE: "Choral / Collective",
}

SINGLE_CHARACTER_POV_TYPES = frozenset(
    {
        POV_TYPE_FIRST_PERSON,
        POV_TYPE_SECOND_PERSON,
        POV_TYPE_THIRD_PERSON_LIMITED,
    }
)

OMNISCIENT_STYLE_RESTRAINED = "restrained"
OMNISCIENT_STYLE_BROAD = "broad"
OMNISCIENT_STYLE_NARRATOR_LED = "narrator_led"

OMNISCIENT_STYLE_LABELS = {
    OMNISCIENT_STYLE_RESTRAINED: "Restrained Omniscient",
    OMNISCIENT_STYLE_BROAD: "Broad Omniscient",
    OMNISCIENT_STYLE_NARRATOR_LED: "Narrator-Led Omniscient",
}


class PovContractError(ValueError):
    """Raised when POV settings are structurally inconsistent."""


def pov_type_options() -> list[dict[str, str]]:
    return [
        {"value": key, "label": label}
        for key, label in POV_TYPE_LABELS.items()
    ]


def omniscient_style_options() -> list[dict[str, str]]:
    return [
        {"value": key, "label": label}
        for key, label in OMNISCIENT_STYLE_LABELS.items()
    ]


def normalize_plan_settings(
    pov_type: Any,
    omniscient_style: Any,
    character_refs: list[dict[str, Any]],
) -> tuple[str, str]:
    """Validate and normalize author-owned POV planning settings."""

    normalized_type = str(pov_type or "").strip()
    normalized_style = str(omniscient_style or "").strip()
    count = len(character_refs or [])

    if not normalized_type:
        if count:
            raise PovContractError(
                "Choose an Advanced POV type before assigning POV characters."
            )
        return "", ""

    if normalized_type not in POV_TYPE_LABELS:
        raise PovContractError(f"Unsupported POV type: {normalized_type}")

    if normalized_type in SINGLE_CHARACTER_POV_TYPES and count != 1:
        raise PovContractError(
            f"{POV_TYPE_LABELS[normalized_type]} requires exactly one POV character."
        )

    if normalized_type == POV_TYPE_THIRD_PERSON_OMNISCIENT and count < 1:
        raise PovContractError(
            "Third-Person Omniscient requires at least one authorized interior character."
        )

    if normalized_type == POV_TYPE_THIRD_PERSON_OBJECTIVE and count != 0:
        raise PovContractError(
            "Third-Person Objective does not permit POV character interior access."
        )

    if normalized_type == POV_TYPE_CHORAL_COLLECTIVE and count < 2:
        raise PovContractError(
            "Choral / Collective requires at least two collective POV characters."
        )

    if normalized_type == POV_TYPE_THIRD_PERSON_OMNISCIENT:
        normalized_style = normalized_style or OMNISCIENT_STYLE_RESTRAINED
        if normalized_style not in OMNISCIENT_STYLE_LABELS:
            raise PovContractError(
                f"Unsupported omniscient interior style: {normalized_style}"
            )
    else:
        normalized_style = ""

    return normalized_type, normalized_style


def build_prompt_contract(
    pov_type: Any,
    omniscient_style: Any,
    character_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build deterministic prompt-facing POV semantics."""

    normalized_type, normalized_style = normalize_plan_settings(
        pov_type,
        omniscient_style,
        character_refs,
    )
    refs = deepcopy(character_refs or [])

    if not normalized_type:
        return {
            "contract_version": POV_CONTRACT_VERSION,
            "configured": False,
            "pov_type": "",
            "pov_type_label": "Not Set",
            "character_refs": [],
            "interior_access": "not_configured",
            "pronoun_mode": "not_configured",
            "narrator_scope": "not_configured",
            "head_hopping": "not_configured",
            "omniscient_style": "",
            "omniscient_style_label": "",
            "prompt_rules": [],
        }

    labels = [
        str(ref.get("label") or ref.get("record_id") or "").strip()
        for ref in refs
        if str(ref.get("label") or ref.get("record_id") or "").strip()
    ]
    names = ", ".join(labels) if labels else "the authorized POV character"

    common_rules = [
        "POV controls narrative access to consciousness; it does not control chapter participation.",
        "Non-POV chapter participants may speak, act, react, move, interact, and affect events normally.",
        "POV never overrides Canon, historical constraints, Book reveal boundaries, Story Controls, Chapter Plan requirements, or Approved Continuity.",
        "Do not grant a POV character knowledge that the character cannot possess at the current story position.",
        "Do not expose hidden or future Canon merely because a POV character learns it later in the story.",
        "Do not invent a POV transition, narrator change, or interior-access permission that is not authorized by this contract.",
    ]

    if normalized_type == POV_TYPE_FIRST_PERSON:
        specific = [
            f"Narrate from {names}'s first-person perspective.",
            "Use first-person grammatical person for the narrating character.",
            "Direct access to thoughts, memories, emotions, sensations, interpretations, and private perceptions is permitted only for the authorized POV character.",
            "Do not directly narrate another character's private thoughts, memories, motives, emotions, intentions, or unseen perceptions.",
            "Other characters' internal states may be inferred only from information available to the narrating character.",
            "Do not change narrating character.",
        ]
        interior_access = "single_authorized_character"
        pronoun_mode = "first_person"
        narrator_scope = "limited"
        head_hopping = "forbidden"

    elif normalized_type == POV_TYPE_SECOND_PERSON:
        specific = [
            f"Render {names} through second-person narration using 'you' where grammatically appropriate.",
            "Direct interior access is permitted only to the authorized focal character's experience.",
            "Do not directly narrate another character's private interior state.",
            "Other characters remain external participants and may interact normally.",
            "Do not change focal character.",
        ]
        interior_access = "single_authorized_character"
        pronoun_mode = "second_person"
        narrator_scope = "limited"
        head_hopping = "forbidden"

    elif normalized_type == POV_TYPE_THIRD_PERSON_LIMITED:
        specific = [
            "Use third-person narration.",
            f"{names} is the focal consciousness.",
            "Directly render the focal character's thoughts, memories, emotions, sensations, interpretations, fears, assumptions, and private perceptions when appropriate.",
            "Do not directly narrate another character's private thoughts, memories, motives, emotions, intentions, or unseen perceptions.",
            "Represent another character's internal state only through observable behavior, dialogue, physical reaction, or the focal character's interpretation.",
            "Do not shift focal consciousness away from the authorized POV character.",
        ]
        interior_access = "single_authorized_character"
        pronoun_mode = "third_person"
        narrator_scope = "limited"
        head_hopping = "forbidden"

    elif normalized_type == POV_TYPE_THIRD_PERSON_OMNISCIENT:
        specific = [
            "Use third-person omniscient narration.",
            f"Direct interior access is permitted only for these authorized characters: {names}.",
            "The narrator may know information beyond one character's immediate perception only when that information is permitted by Canon and the Chapter Plan.",
            "Do not reveal the private interior of an unauthorized character.",
            "Do not use omniscience as permission for arbitrary sentence-level switching between minds.",
        ]
        if normalized_style == OMNISCIENT_STYLE_RESTRAINED:
            specific.extend(
                [
                    "Use restrained omniscience.",
                    "Maintain one stable focal center for substantial passages rather than alternating rapidly between private minds.",
                    "When interior focus changes, clearly ground the reader in the new authorized character before revealing that character's private experience.",
                    "Do not move from one private interior to another sentence-by-sentence merely for convenience.",
                    "A change of interior focus must be narratively grounded and sustained long enough to establish a coherent focal center.",
                ]
            )
        elif normalized_style == OMNISCIENT_STYLE_BROAD:
            specific.extend(
                [
                    "Use broad omniscience while preserving clear narrative grounding.",
                    "The narrator may move among authorized interiors more freely, but every interior shift must remain clear to the reader.",
                    "Do not alternate private interiors sentence-by-sentence or create ungrounded head-hopping.",
                ]
            )
        else:
            specific.extend(
                [
                    "Use narrator-led omniscience.",
                    "Maintain a stable external omniscient narrator as the primary organizing consciousness.",
                    "The narrator may summarize or enter authorized interiors when useful, but must clearly identify whose interior is being rendered.",
                    "Do not let rapid character-to-character interior switching replace the stable narrator.",
                ]
            )
        interior_access = "multiple_authorized_characters"
        pronoun_mode = "third_person"
        narrator_scope = "omniscient"
        head_hopping = "rapid_switching_forbidden"

    elif normalized_type == POV_TYPE_THIRD_PERSON_OBJECTIVE:
        specific = [
            "Use third-person objective narration.",
            "Do not directly state any character's private thoughts, memories, motives, emotions, intentions, or unseen perceptions.",
            "Narrate only externally available information such as physical action, dialogue, facial expression, body language, physical reaction, sound, visible environment, and externally observable events.",
            "Do not interpret an internal state as fact unless it has been made externally knowable through dialogue, action, Canon, or another authoritative source.",
        ]
        interior_access = "none"
        pronoun_mode = "third_person"
        narrator_scope = "external_objective"
        head_hopping = "not_applicable"

    else:
        specific = [
            "Use a collective narrative voice centered on the authorized group.",
            "Use first-person plural forms such as 'we', 'us', and 'our' where grammatically appropriate.",
            "The collective voice may express perceptions, memories, beliefs, emotions, and judgments that coherently belong to the authorized collective.",
            "Do not silently collapse from collective narration into the private first-person interior of an individual member.",
            "Do not attribute private knowledge belonging to one member to the entire collective unless Canon or the Chapter Plan establishes that the knowledge is shared.",
            "Characters outside the authorized collective remain external to the collective interior voice.",
        ]
        interior_access = "authorized_collective"
        pronoun_mode = "first_person_plural"
        narrator_scope = "collective"
        head_hopping = "individual_collapse_forbidden"

    return {
        "contract_version": POV_CONTRACT_VERSION,
        "configured": True,
        "pov_type": normalized_type,
        "pov_type_label": POV_TYPE_LABELS[normalized_type],
        "character_refs": refs,
        "interior_access": interior_access,
        "pronoun_mode": pronoun_mode,
        "narrator_scope": narrator_scope,
        "head_hopping": head_hopping,
        "omniscient_style": normalized_style,
        "omniscient_style_label": (
            OMNISCIENT_STYLE_LABELS.get(normalized_style, "")
        ),
        "prompt_rules": common_rules + specific,
    }
