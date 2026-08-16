"""
Canon template questionnaire service.

This service is an inert schema boundary for future author-facing canon
authoring. It exposes structured canon-building questionnaires by genre.

It does not save author answers, render frontend forms, generate knowledge
packs, call prompt construction, call providers, write runtime memory, or
unlock generation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.templates.template_registry import list_templates, normalize_template_id


CANON_TEMPLATE_SERVICE_MARKER = "project-canon-template-questionnaire-boundary-20260715"
CANON_TEMPLATE_SERVICE_VERSION = "project_canon_authoring_schema_v3_planning_interface"

FIELD_SHORT_TEXT = "short_text"
FIELD_LONG_TEXT = "long_text"
FIELD_RICH_TEXT = "rich_text"
FIELD_SELECT = "select"
FIELD_MULTI_SELECT = "multi_select"
FIELD_BOOLEAN = "boolean"
FIELD_RECORD_LIST = "record_list"

STORY_CODE_HELP = (
    "Give this item a short code or nickname that is easy for you to recognize while planning, such as "
    "FIRST-CONTACT or JAX-M003. Use one if it helps you organize your story. Leave it blank if you do not need one."
)
AVAILABLE_FROM_HELP = (
    "Choose the earliest book where this character, location, event, or other canon item should normally become "
    "available. For example, choosing Book 3 keeps it out of normal planning for Books 1 and 2. Leave it blank if "
    "it can be used from the beginning or you do not want to set a restriction."
)
NARRATIVE_TYPE_HELP = (
    "Choose the role this event plays in the story, such as a mission, reveal, milestone, clue, escalation, or "
    "consequence. This can make events easier to organize and plan. Leave it blank if you have not decided yet."
)
NARRATIVE_TYPE_OPTIONS = [
    "mission",
    "reveal",
    "saga_event",
    "historical_event",
    "milestone",
    "clue",
    "relationship_change",
    "escalation",
    "transition",
    "consequence",
    "other",
]


def list_canon_questionnaire_templates() -> list[dict[str, Any]]:
    """Return available authoring questionnaire templates.

    This is a read-only catalog used by future API/UI layers. It intentionally
    mirrors the active template registry IDs so project creation and canon
    authoring remain aligned.
    """

    available = []
    for template in list_templates():
        template_id = normalize_template_id(template.get("template_id"), template.get("genre"))
        schema = get_canon_questionnaire_template(template_id)
        available.append(
            {
                "template_id": schema["template_id"],
                "genre": schema["genre"],
                "label": schema["label"],
                "description": schema["description"],
                "version": schema["version"],
                "section_count": len(schema["sections"]),
                "required_section_count": sum(
                    1 for section in schema["sections"] if section.get("required")
                ),
            }
        )
    return available


def get_canon_questionnaire_template(
    template_id: str | None = None,
    genre: str | None = None,
) -> dict[str, Any]:
    """Return a structured canon-building questionnaire for a genre/template."""

    resolved_id = normalize_template_id(template_id, genre)
    genre_schema = _GENRE_QUESTIONNAIRES.get(resolved_id, _GENRE_QUESTIONNAIRES["custom"])

    schema = _merge_base_and_genre_schema(resolved_id, genre_schema)
    return _with_completion_metadata(schema)


def get_base_canon_questionnaire_template() -> dict[str, Any]:
    """Return the universal canon questionnaire shared by all genres."""

    schema = deepcopy(_BASE_QUESTIONNAIRE)
    return _with_completion_metadata(schema)


def get_questionnaire_section(
    template_id: str,
    section_id: str,
    genre: str | None = None,
) -> dict[str, Any]:
    """Return one questionnaire section by ID."""

    schema = get_canon_questionnaire_template(template_id, genre)
    for section in schema["sections"]:
        if section.get("section_id") == section_id:
            return deepcopy(section)
    raise ValueError(f"Unknown canon questionnaire section: {section_id}")


def validate_questionnaire_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return structural validation for a questionnaire schema.

    This validates schema shape only. It does not validate author answers.
    """

    errors: list[str] = []
    required_top_level = ["template_id", "genre", "label", "version", "sections"]
    for key in required_top_level:
        if key not in schema:
            errors.append(f"missing top-level key: {key}")

    sections = schema.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("sections must be a non-empty list")
        sections = []

    seen_section_ids: set[str] = set()
    for section in sections:
        section_id = section.get("section_id")
        if not section_id:
            errors.append("section missing section_id")
            continue
        if section_id in seen_section_ids:
            errors.append(f"duplicate section_id: {section_id}")
        seen_section_ids.add(section_id)

        if not section.get("label"):
            errors.append(f"section {section_id} missing label")

        fields = section.get("fields", [])
        records = section.get("records", [])
        if not fields and not records:
            errors.append(f"section {section_id} has no fields or records")

        for field in fields:
            _validate_field(field, f"section {section_id}", errors)

        for record in records:
            record_id = record.get("record_id")
            if not record_id:
                errors.append(f"section {section_id} record missing record_id")
            record_fields = record.get("fields", [])
            if not record_fields:
                errors.append(f"record {record_id or '<unknown>'} has no fields")
            for field in record_fields:
                _validate_field(field, f"record {record_id or '<unknown>'}", errors)

    return {
        "valid": not errors,
        "errors": errors,
        "section_count": len(sections),
    }


def _validate_field(field: dict[str, Any], scope: str, errors: list[str]) -> None:
    field_id = field.get("field_id")
    if not field_id:
        errors.append(f"{scope} field missing field_id")
    if not field.get("label"):
        errors.append(f"{scope} field {field_id or '<unknown>'} missing label")
    if not field.get("field_type"):
        errors.append(f"{scope} field {field_id or '<unknown>'} missing field_type")


def _merge_base_and_genre_schema(
    resolved_id: str,
    genre_schema: dict[str, Any],
) -> dict[str, Any]:
    schema = deepcopy(_BASE_QUESTIONNAIRE)
    schema.update(
        {
            "template_id": resolved_id,
            "genre": genre_schema["genre"],
            "label": genre_schema["label"],
            "description": genre_schema["description"],
            "version": CANON_TEMPLATE_SERVICE_VERSION,
            "extends": "base",
            "italus_guided": bool(genre_schema.get("italus_guided", False)),
        }
    )

    sections_by_id = {section["section_id"]: section for section in schema["sections"]}

    for section_id, overrides in (genre_schema.get("base_section_overrides") or {}).items():
        if section_id in sections_by_id:
            sections_by_id[section_id].update(deepcopy(overrides))

    for genre_section in genre_schema.get("sections", []):
        section_id = genre_section["section_id"]
        if section_id in sections_by_id:
            sections_by_id[section_id].update(deepcopy(genre_section))
        else:
            schema["sections"].append(deepcopy(genre_section))

    _apply_template_specific_record_fields(schema, resolved_id)

    schema["authoring_model"] = {
        "author_input": "structured_fields_plus_rich_text",
        "primary_storage": "project_local_json",
        "readable_rendering": "project_local_markdown",
        "future_compiled_packets": "generated_later_from_author_canon",
        "xml_primary_storage": False,
        "raw_text_primary_storage": False,
    }
    schema["execution_locks"] = _execution_locks()
    return schema


def _apply_template_specific_record_fields(schema: dict[str, Any], resolved_id: str) -> None:
    """Apply genre-specific record fields without duplicating shared record schemas."""

    if resolved_id != "historical_epic":
        return

    for section in schema.get("sections", []):
        if section.get("section_id") != "timeline_event_ledger":
            continue
        for record in section.get("records", []):
            if record.get("record_id") != "events":
                continue

            fields = list(record.get("fields") or [])
            insert_at = next(
                (index + 1 for index, field in enumerate(fields) if field.get("field_id") == "narrative_type"),
                1,
            )
            fields[insert_at:insert_at] = [
                _field(
                    "event_type",
                    "Historical / Reality Classification",
                    FIELD_SELECT,
                    options=["fictional", "historical", "hybrid"],
                    help_text="Classifies this event's relationship to real historical fact.",
                ),
                _field(
                    "historical_status",
                    "Historical Constraint",
                    FIELD_SELECT,
                    options=["flexible", "constrained", "immutable"],
                    help_text="Defines how strictly the historical event must be preserved.",
                ),
            ]
            record["fields"] = fields
            return


def _with_completion_metadata(schema: dict[str, Any]) -> dict[str, Any]:
    schema = deepcopy(schema)
    required_sections = [section for section in schema["sections"] if section.get("required")]
    required_fields = 0
    repeatable_records = 0

    for section in schema["sections"]:
        for field in section.get("fields", []):
            if field.get("required"):
                required_fields += 1
        for record in section.get("records", []):
            repeatable_records += 1
            for field in record.get("fields", []):
                if field.get("required"):
                    required_fields += 1

    schema["completion_model"] = {
        "section_count": len(schema["sections"]),
        "required_section_count": len(required_sections),
        "required_field_count": required_fields,
        "repeatable_record_count": repeatable_records,
        "completion_rule": "all_required_sections_complete_and_required_fields_answered",
    }
    schema["service"] = CANON_TEMPLATE_SERVICE_MARKER
    return schema


def _execution_locks() -> dict[str, bool]:
    return {
        "generation_enabled": False,
        "provider_execution_enabled": False,
        "prompt_builder_enabled": False,
        "draft_validation_enabled": False,
        "approved_persistence_enabled": False,
        "export_enabled": False,
    }


def _field(
    field_id: str,
    label: str,
    field_type: str = FIELD_LONG_TEXT,
    *,
    required: bool = True,
    help_text: str = "",
    placeholder: str = "",
    options: list[str] | None = None,
    planning_field: bool = False,
    author_hidden: bool = False,
    migration_reconciliation: bool = False,
    migration_existing_optional: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "field_id": field_id,
        "label": label,
        "field_type": field_type,
        "required": required,
        "help_text": help_text,
        "placeholder": placeholder,
    }
    if options:
        payload["options"] = list(options)
    if planning_field:
        payload["planning_field"] = True
    if author_hidden:
        payload["author_hidden"] = True
    if migration_reconciliation:
        payload["migration_reconciliation"] = True
    if migration_existing_optional:
        payload["migration_existing_optional"] = True
    return payload


def _record(
    record_id: str,
    label: str,
    fields: list[dict[str, Any]],
    *,
    required: bool = True,
    min_items: int = 1,
    help_text: str = "",
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "label": label,
        "field_type": FIELD_RECORD_LIST,
        "required": required,
        "min_items": min_items,
        "help_text": help_text,
        "fields": fields,
    }


_BASE_QUESTIONNAIRE: dict[str, Any] = {
    "template_id": "base",
    "genre": "base",
    "label": "Core Author Canon",
    "description": "Direct author-owned story truth shared by genre templates.",
    "version": CANON_TEMPLATE_SERVICE_VERSION,
    "sections": [
        {
            "section_id": "project_bible",
            "label": "Project Bible",
            "required": True,
            "purpose": "Define the narrative contract and project identity.",
            "author_guidance": "Establish what the story promises to the reader.",
            "fields": [
                _field("project_title", "Project title", FIELD_SHORT_TEXT),
                _field("series_title", "Series title", FIELD_SHORT_TEXT, required=False),
                _field("subgenre", "Subgenre", FIELD_SHORT_TEXT, required=False),
                _field("target_audience", "Target audience", FIELD_SHORT_TEXT),
                _field("narrative_promise", "Narrative promise", FIELD_RICH_TEXT),
                _field("central_theme", "Central theme", FIELD_LONG_TEXT),
                _field("tone", "Tone", FIELD_LONG_TEXT),
                _field("content_boundaries", "Content boundaries", FIELD_RICH_TEXT, required=False),
                _field("author_notes", "Author notes", FIELD_RICH_TEXT, required=False),
            ],
            "records": [],
        },
        {
            "section_id": "world_bible",
            "label": "World & Setting",
            "required": True,
            "purpose": "Define the setting, world rules, geography, and locations.",
            "author_guidance": "Locations are maintained here so setting facts have one authority.",
            "fields": [
                _field("setting_summary", "Setting summary", FIELD_RICH_TEXT),
                _field("time_period", "Time period / era", FIELD_SHORT_TEXT),
                _field("geography", "Geography", FIELD_RICH_TEXT),
                _field("cultures", "Cultures and societies", FIELD_RICH_TEXT),
                _field("social_rules", "Social rules", FIELD_RICH_TEXT),
                _field("political_rules", "Political rules", FIELD_RICH_TEXT, required=False),
                _field("economic_rules", "Economic rules", FIELD_RICH_TEXT, required=False),
                _field("technology_or_magic_rules", "Technology or magic rules", FIELD_RICH_TEXT, required=False),
                _field("forbidden_contradictions", "Forbidden contradictions", FIELD_RICH_TEXT),
                _field("open_questions", "Open questions", FIELD_RICH_TEXT, required=False),
            ],
            "records": [
                _record(
                    "locations",
                    "Locations",
                    [
                        _field("name", "Name", FIELD_SHORT_TEXT),
                        _field(
                            "available_from_book",
                            "Available From",
                            FIELD_SHORT_TEXT,
                            required=False,
                            planning_field=True,
                            help_text=AVAILABLE_FROM_HELP,
                            placeholder="Book number (for example, 3)",
                        ),
                        _field("type", "Type", FIELD_SHORT_TEXT),
                        _field("region", "Region", FIELD_SHORT_TEXT, required=False),
                        _field("description", "Description", FIELD_RICH_TEXT),
                        _field("rules", "Location rules", FIELD_RICH_TEXT, required=False),
                        _field("associated_characters", "Associated characters", FIELD_LONG_TEXT, required=False),
                        _field("associated_events", "Associated events", FIELD_LONG_TEXT, required=False),
                        _field("sensory_details", "Sensory details", FIELD_RICH_TEXT, required=False),
                        _field("continuity_notes", "Continuity notes", FIELD_RICH_TEXT),
                    ],
                    required=False,
                    min_items=0,
                )
            ],
        },
        {
            "section_id": "character_bible",
            "label": "Character Bible",
            "required": True,
            "purpose": "Create stable character records for continuity and story planning.",
            "author_guidance": "Add one record for each major character or recurring entity.",
            "fields": [],
            "records": [
                _record(
                    "characters",
                    "Characters",
                    [
                        _field("name", "Name", FIELD_SHORT_TEXT),
                        _field("aliases", "Aliases", FIELD_LONG_TEXT, required=False),
                        _field(
                            "available_from_book",
                            "Available From",
                            FIELD_SHORT_TEXT,
                            required=False,
                            planning_field=True,
                            help_text=AVAILABLE_FROM_HELP,
                            placeholder="Book number (for example, 3)",
                        ),
                        _field("role", "Narrative role", FIELD_SHORT_TEXT),
                        _field("status", "Status", FIELD_SELECT, options=["active", "dead", "missing", "unknown", "historical", "fictional"]),
                        _field("age_or_lifespan", "Age or lifespan", FIELD_SHORT_TEXT, required=False),
                        _field("first_appearance", "First appearance", FIELD_SHORT_TEXT, required=False),
                        _field("relationships", "Relationships", FIELD_RICH_TEXT),
                        _field("goals", "Goals", FIELD_RICH_TEXT),
                        _field("fears", "Fears", FIELD_RICH_TEXT, required=False),
                        _field("voice", "Voice", FIELD_RICH_TEXT),
                        _field("arc", "Character arc", FIELD_RICH_TEXT),
                        _field("canon_constraints", "Canon constraints", FIELD_RICH_TEXT),
                    ],
                    help_text="Major characters, subjects, historical figures, or recurring entities.",
                )
            ],
        },
        {
            "section_id": "timeline_event_ledger",
            "label": "Timeline & Event Ledger",
            "required": True,
            "purpose": "Control chronology, cause/effect, and immutable historical facts.",
            "author_guidance": "Historical anchors are recorded as historical or hybrid events in this ledger.",
            "fields": [],
            "records": [
                _record(
                    "events",
                    "Events",
                    [
                        _field("date_or_sequence", "Date or sequence", FIELD_SHORT_TEXT),
                        _field(
                            "story_code",
                            "Story Code",
                            FIELD_SHORT_TEXT,
                            required=False,
                            planning_field=True,
                            help_text=STORY_CODE_HELP,
                        ),
                        _field(
                            "narrative_type",
                            "Narrative Type",
                            FIELD_SELECT,
                            required=False,
                            planning_field=True,
                            help_text=NARRATIVE_TYPE_HELP,
                            options=NARRATIVE_TYPE_OPTIONS,
                            migration_reconciliation=True,
                        ),
                        _field(
                            "available_from_book",
                            "Available From",
                            FIELD_SHORT_TEXT,
                            required=False,
                            planning_field=True,
                            help_text=AVAILABLE_FROM_HELP,
                            placeholder="Book number (for example, 3)",
                        ),
                        _field("book", "Book / installment", FIELD_SHORT_TEXT, required=False),
                        _field("location", "Location", FIELD_SHORT_TEXT, required=False),
                        _field("characters_present", "Characters present", FIELD_LONG_TEXT, required=False),
                        _field("event_summary", "Event summary", FIELD_RICH_TEXT),
                        _field("cause", "Cause", FIELD_RICH_TEXT, required=False),
                        _field("effect", "Effect", FIELD_RICH_TEXT, required=False),
                        _field("fictional_interaction_allowed", "Fictional interaction allowed?", FIELD_BOOLEAN, required=False),
                        _field("allowed_interaction_notes", "Allowed interaction notes", FIELD_RICH_TEXT, required=False),
                        _field("must_not_change", "What must not change", FIELD_RICH_TEXT, required=False),
                        _field("continuity_constraints", "Continuity constraints", FIELD_RICH_TEXT),
                    ],
                    help_text="Fictional, historical, and hybrid events maintained in one chronology.",
                )
            ],
        },
    ],
}


_GENRE_QUESTIONNAIRES: dict[str, dict[str, Any]] = {
    "historical_epic": {
        "genre": "historical_epic",
        "label": "Historical Epic / Historical Fantasy",
        "description": "Historically anchored fiction with explicit historical interaction controls.",
        "italus_guided": True,
        "sections": [
            {
                "section_id": "world_bible",
                "label": "Historical World & Setting",
                "author_guidance": "Define era, geography, culture, historical boundaries, fictional logic, and project locations.",
                "fields": [
                    _field("historical_period", "Historical period", FIELD_SHORT_TEXT),
                    _field("setting_summary", "Setting summary", FIELD_RICH_TEXT),
                    _field("geography", "Geography", FIELD_RICH_TEXT),
                    _field("cultures", "Cultures and societies", FIELD_RICH_TEXT),
                    _field("political_rules", "Political rules", FIELD_RICH_TEXT),
                    _field("religious_or_mythic_context", "Religious / mythic context", FIELD_RICH_TEXT, required=False),
                    _field("historical_constraints", "Historical constraints", FIELD_RICH_TEXT),
                    _field("fictional_allowances", "Fictional allowances", FIELD_RICH_TEXT),
                    _field("forbidden_contradictions", "Forbidden contradictions", FIELD_RICH_TEXT),
                ],
            },
            {
                "section_id": "timeline_event_ledger",
                "label": "Timeline & Historical Event Ledger",
            },
            {
                "section_id": "historical_interaction_map",
                "label": "Historical Character Interaction Map",
                "required": True,
                "purpose": "Control how fictional characters may interact with real historical people or events.",
                "author_guidance": "Record only relationships that require explicit historical interaction limits.",
                "fields": [],
                "records": [
                    _record(
                        "interactions",
                        "Allowed Historical Interactions",
                        [
                            _field("fictional_character", "Fictional character", FIELD_SHORT_TEXT),
                            _field("historical_figure", "Historical figure", FIELD_SHORT_TEXT),
                            _field("date_or_period", "Date or period", FIELD_SHORT_TEXT),
                            _field("interaction_type", "Interaction type", FIELD_SHORT_TEXT),
                            _field("allowed_scope", "Allowed scope", FIELD_RICH_TEXT),
                            _field("prohibited_changes", "Prohibited changes", FIELD_RICH_TEXT),
                            _field("continuity_notes", "Continuity notes", FIELD_RICH_TEXT),
                        ],
                    )
                ],
            },
        ],
    },
    "fantasy_epic": {
        "genre": "fantasy_epic",
        "base_section_overrides": {"world_bible": {"label": "Worldbuilding & Setting"}, "timeline_event_ledger": {"label": "Timeline & Age Ledger"}},
        "label": "Fantasy Epic",
        "description": "Epic fantasy canon with magic, culture, factions, mythology, and world-rule controls.",
        "sections": [
            {
                "section_id": "magic_power_rules",
                "label": "Magic / Power Rules",
                "required": True,
                "purpose": "Define what power can and cannot do.",
                "author_guidance": "Costs and limits prevent later contradictions.",
                "fields": [
                    _field("source_of_power", "Source of power", FIELD_RICH_TEXT),
                    _field("costs", "Costs", FIELD_RICH_TEXT),
                    _field("limits", "Limits", FIELD_RICH_TEXT),
                    _field("forbidden_uses", "Forbidden uses", FIELD_RICH_TEXT),
                    _field("who_can_use_it", "Who can use it", FIELD_RICH_TEXT),
                ],
                "records": [],
            },
            {
                "section_id": "factions_species_mythology",
                "label": "Factions, Species, and Mythology",
                "required": True,
                "purpose": "Define non-human groups, cultures, kingdoms, and myths.",
                "author_guidance": "Use repeatable records for groups that affect plot or continuity.",
                "fields": [],
                "records": [
                    _record(
                        "groups",
                        "Groups / Species / Factions",
                        [
                            _field("name", "Name", FIELD_SHORT_TEXT),
                            _field(
                                "available_from_book",
                                "Available From",
                                FIELD_SHORT_TEXT,
                                required=False,
                                planning_field=True,
                                help_text=AVAILABLE_FROM_HELP,
                                placeholder="Book number (for example, 3)",
                            ),
                            _field("type", "Type", FIELD_SHORT_TEXT),
                            _field("origin", "Origin", FIELD_RICH_TEXT),
                            _field("beliefs", "Beliefs", FIELD_RICH_TEXT),
                            _field("powers_or_capabilities", "Powers or capabilities", FIELD_RICH_TEXT, required=False),
                            _field("constraints", "Constraints", FIELD_RICH_TEXT),
                        ],
                    )
                ],
            },
        ],
    },
    "science_fiction": {
        "genre": "science_fiction",
        "base_section_overrides": {"world_bible": {"label": "Universe, Technology & Setting"}, "timeline_event_ledger": {"label": "Timeline, Missions & Major Events"}},
        "label": "Science Fiction",
        "description": "Science-fiction canon with technology, science constraints, ships/planets, and faction logic.",
        "sections": [
            {
                "section_id": "technology_rules",
                "label": "Technology Rules",
                "required": True,
                "purpose": "Define technical capabilities and limits.",
                "author_guidance": "Future scenes must obey these constraints.",
                "fields": [
                    _field("core_technologies", "Core technologies", FIELD_RICH_TEXT),
                    _field("technology_limits", "Technology limits", FIELD_RICH_TEXT),
                    _field("ai_rules", "AI rules", FIELD_RICH_TEXT, required=False),
                    _field("travel_rules", "Travel / FTL rules", FIELD_RICH_TEXT, required=False),
                    _field("weapons_or_defense_rules", "Weapons / defense rules", FIELD_RICH_TEXT, required=False),
                    _field("scientific_impossibilities", "Scientific impossibilities", FIELD_RICH_TEXT),
                ],
                "records": [],
            },
            {
                "section_id": "ships_planets_factions",
                "label": "Ships, Planets, and Factions",
                "required": True,
                "purpose": "Define operational setting elements.",
                "author_guidance": "Record every ship, planet, station, or faction that governs plot logic.",
                "fields": [],
                "records": [
                    _record(
                        "systems",
                        "Ships / Planets / Factions",
                        [
                            _field("name", "Name", FIELD_SHORT_TEXT),
                            _field(
                                "available_from_book",
                                "Available From",
                                FIELD_SHORT_TEXT,
                                required=False,
                                planning_field=True,
                                help_text=AVAILABLE_FROM_HELP,
                                placeholder="Book number (for example, 3)",
                            ),
                            _field("type", "Type", FIELD_SELECT, options=["ship", "planet", "station", "faction", "species", "organization"]),
                            _field("description", "Description", FIELD_RICH_TEXT),
                            _field("capabilities", "Capabilities", FIELD_RICH_TEXT),
                            _field("limits", "Limits", FIELD_RICH_TEXT),
                        ],
                    )
                ],
            },
        ],
    },
    "mystery_thriller": {
        "genre": "mystery_thriller",
        "base_section_overrides": {"world_bible": {"label": "Setting, Institutions & Social Context"}, "timeline_event_ledger": {"label": "Case Timeline & Event Ledger"}},
        "label": "Mystery / Thriller",
        "description": "Case-driven canon with clues, suspects, reveals, red herrings, and fair-play rules.",
        "sections": [
            {
                "section_id": "case_bible",
                "label": "Case Bible",
                "required": True,
                "purpose": "Define the truth of the central crime, threat, or mystery.",
                "author_guidance": "The writer may hide the truth from the reader, but the system needs it.",
                "fields": [
                    _field("central_case", "Central case / threat", FIELD_RICH_TEXT),
                    _field("truth_of_what_happened", "Truth of what happened", FIELD_RICH_TEXT),
                    _field("victim_or_target", "Victim / target", FIELD_RICH_TEXT, required=False),
                    _field("culprit_or_source", "Culprit / source", FIELD_RICH_TEXT),
                    _field("motive", "Motive", FIELD_RICH_TEXT),
                    _field("fair_play_rules", "Fair-play rules", FIELD_RICH_TEXT),
                ],
                "records": [],
            },
            {
                "section_id": "clue_reveal_chain",
                "label": "Clue and Reveal Chain",
                "required": True,
                "purpose": "Control clues, red herrings, and reveal order.",
                "author_guidance": "Every reveal should be supported by earlier evidence.",
                "fields": [],
                "records": [
                    _record(
                        "clues",
                        "Clues / Red Herrings / Reveals",
                        [
                            _field(
                                "label",
                                "Name / Label",
                                FIELD_SHORT_TEXT,
                                migration_reconciliation=True,
                                migration_existing_optional=True,
                            ),
                            _field(
                                "story_code",
                                "Story Code",
                                FIELD_SHORT_TEXT,
                                required=False,
                                planning_field=True,
                                help_text=STORY_CODE_HELP,
                            ),
                            _field(
                                "available_from_book",
                                "Available From",
                                FIELD_SHORT_TEXT,
                                required=False,
                                planning_field=True,
                                help_text=AVAILABLE_FROM_HELP,
                                placeholder="Book number (for example, 3)",
                            ),
                            _field("type", "Type", FIELD_SELECT, options=["clue", "red_herring", "reveal", "withheld_information", "other"]),
                            _field("appears_when", "Appears when", FIELD_SHORT_TEXT),
                            _field("meaning", "Meaning", FIELD_RICH_TEXT),
                            _field("reader_interpretation", "Reader interpretation", FIELD_RICH_TEXT, required=False),
                            _field("payoff", "Payoff", FIELD_RICH_TEXT),
                        ],
                    )
                ],
            },
        ],
    },
    "memoir": {
        "genre": "memoir",
        "base_section_overrides": {"world_bible": {"label": "Life Context & Setting"}, "timeline_event_ledger": {"label": "Life Timeline"}},
        "label": "Memoir / Life Story",
        "description": "Life-story canon with chronology, people, factual certainty, privacy, and emotional truth.",
        "sections": [
            {
                "section_id": "life_chronology",
                "label": "Life Chronology",
                "required": True,
                "purpose": "Define the order and certainty of lived events.",
                "author_guidance": "Separate remembered truth, documented fact, and interpretation.",
                "fields": [],
                "records": [
                    _record(
                        "life_events",
                        "Life Events",
                        [
                            _field("date_or_period", "Date or period", FIELD_SHORT_TEXT),
                            _field(
                                "available_from_book",
                                "Available From",
                                FIELD_SHORT_TEXT,
                                required=False,
                                planning_field=True,
                                help_text=AVAILABLE_FROM_HELP,
                                placeholder="Book number (for example, 3)",
                            ),
                            _field("event_summary", "Event summary", FIELD_RICH_TEXT),
                            _field("people_involved", "People involved", FIELD_LONG_TEXT, required=False),
                            _field("location", "Location", FIELD_SHORT_TEXT, required=False),
                            _field("memory_certainty", "Memory certainty", FIELD_SELECT, options=["documented", "strong_memory", "partial_memory", "reconstructed", "uncertain"]),
                            _field("emotional_truth", "Emotional truth", FIELD_RICH_TEXT),
                            _field("privacy_flags", "Privacy flags", FIELD_RICH_TEXT, required=False),
                        ],
                    )
                ],
            },
            {
                "section_id": "sensitive_material_rules",
                "label": "Sensitive Material Rules",
                "required": True,
                "purpose": "Define privacy and handling constraints.",
                "author_guidance": "Protect people, facts, and boundaries before drafting.",
                "fields": [
                    _field("people_to_anonymize", "People to anonymize", FIELD_RICH_TEXT, required=False),
                    _field("events_to_handle_carefully", "Events to handle carefully", FIELD_RICH_TEXT),
                    _field("facts_requiring_verification", "Facts requiring verification", FIELD_RICH_TEXT, required=False),
                    _field("material_to_exclude", "Material to exclude", FIELD_RICH_TEXT, required=False),
                ],
                "records": [],
            },
        ],
    },
    "custom": {
        "genre": "custom",
        "base_section_overrides": {"world_bible": {"label": "World & Setting"}, "timeline_event_ledger": {"label": "Timeline & Event Ledger"}},
        "label": "Custom",
        "description": "Flexible canon questionnaire with minimum structure and expandable custom sections.",
        "sections": [
            {
                "section_id": "custom_sections",
                "label": "Custom Sections",
                "required": False,
                "purpose": "Allow project-specific canon categories.",
                "author_guidance": "Use this for nonstandard projects or genres not yet formalized.",
                "fields": [],
                "records": [
                    _record(
                        "custom_sections",
                        "Custom Sections",
                        [
                            _field("section_name", "Section name", FIELD_SHORT_TEXT),
                            _field("purpose", "Purpose", FIELD_RICH_TEXT),
                            _field("canon_content", "Canon content", FIELD_RICH_TEXT),
                            _field("completion_rule", "Completion rule", FIELD_RICH_TEXT, required=False),
                        ],
                        required=False,
                        min_items=0,
                    )
                ],
            }
        ],
    },
}
