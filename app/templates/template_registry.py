"""
Genre/template canon registry.

This registry describes canon architecture. It does not own project instances
and it does not rewrite the legacy Italus runtime. Services resolve these
template rules against one project through ProjectContext.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_TEMPLATE_ID = "historical_epic"

SOURCE_STATIC_SEED_FILE = "static_seed_file"
SOURCE_LEGACY_ROOT_REFERENCE = "legacy_root_reference"
SOURCE_PROJECT_LOCAL_FILE = "project_local_file"
SOURCE_DERIVE_FROM_PROJECT_BOOKS = "derive_from_project_books"
SOURCE_GENERATED_FROM_AUTHOR_CANON = "generated_from_author_canon"


def _local_item(canon_id: str, label: str, role: str, source_file: str) -> dict[str, Any]:
    return {
        "canon_id": canon_id,
        "label": label,
        "role": role,
        "editable": True,
        "required": True,
        "source_strategy": SOURCE_PROJECT_LOCAL_FILE,
        "source_files": [source_file],
    }


def _runtime_pack_group() -> dict[str, Any]:
    return {
        "group_id": "runtime_knowledge_packs",
        "label": "Runtime Knowledge Packs",
        "author_action": "generate_later",
        "description": "Runtime packs will be generated from author canon and project metadata.",
        "items": [
            {
                "canon_id": "project_knowledge_pack",
                "label": "Project Knowledge Pack",
                "role": "runtime_context_pack",
                "editable": False,
                "required": False,
                "source_strategy": SOURCE_GENERATED_FROM_AUTHOR_CANON,
                "source_files": ["canon_packs/project_knowledge_pack.md"],
            },
            {
                "canon_id": "book_knowledge_packs",
                "label": "Book Knowledge Packs",
                "role": "runtime_context_pack",
                "editable": False,
                "required": False,
                "source_strategy": SOURCE_DERIVE_FROM_PROJECT_BOOKS,
                "file_pattern": "canon_packs/book_{book_number:02d}_knowledge_pack.md",
            },
        ],
    }


_TEMPLATE_REGISTRY: dict[str, dict[str, Any]] = {
    "historical_epic": {
        "template_id": "historical_epic",
        "genre": "historical_epic",
        "label": "Historical Epic",
        "description": "A historically anchored long-form narrative template with strict continuity guardrails.",
        "seed_mode": "legacy_root_reference",
        "project_storage_mode": "hybrid_seed_reference",
        "legacy_seed_profile": "italus_historical_epic",
        "project_code": "ITALUS",
        "canon_groups": [
            {
                "group_id": "editable_canon",
                "label": "Editable Canon",
                "author_action": "review_or_build",
                "description": "Primary canon authorities the author can review, replace, or build from seed assets.",
                "items": [
                    {
                        "canon_id": "world_bible",
                        "label": "World Bible",
                        "role": "primary_canon",
                        "editable": True,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_sources/italus_world_bible_MASTER.txt"],
                    },
                    {
                        "canon_id": "character_bible",
                        "label": "Character Bible",
                        "role": "primary_canon",
                        "editable": True,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_sources/italus_character_bible_MASTER.txt"],
                    },
                    {
                        "canon_id": "historical_character_interaction_map",
                        "label": "Historical Character Interaction Map",
                        "role": "primary_canon",
                        "editable": True,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": [
                            "canon_sources/ITALUS_HISTORICAL_CHARACTER_INTERACTION_MAP_180.txt",
                            "canon_sources/ITALUS_HISTORICAL_CHARACTER_INTERACTION_MAP_233.txt",
                        ],
                    },
                    {
                        "canon_id": "appendix_signal_lexicon",
                        "label": "Appendix & Signal Lexicon",
                        "role": "primary_canon",
                        "editable": True,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_sources/ITALUS_APPENDIX_AND_SIGNAL_LEXICON.txt"],
                    },
                ],
            },
            {
                "group_id": "locked_rules",
                "label": "Locked Canon Rules",
                "author_action": "review_locked_rules",
                "description": "Continuity, validation, and drift-prevention rules. These are reviewed, not freely rewritten.",
                "items": [
                    {
                        "canon_id": "timeline_drift_detector",
                        "label": "Timeline Drift Detector",
                        "role": "validation_rules",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_sources/ITALUS_TIMELINE_DRIFT_DETECTOR.txt"],
                    },
                    {
                        "canon_id": "continuity_prompt",
                        "label": "Master Continuity Prompt",
                        "role": "continuity_guardrail",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_sources/Italus_Saga_Master_Continuity_Prompt.txt"],
                    },
                ],
            },
            {
                "group_id": "system_support_files",
                "label": "System Support Files",
                "author_action": "review_engine_rules",
                "description": "Support prompts and compiled context used by generation and validation.",
                "items": [
                    {
                        "canon_id": "book_generation_engine",
                        "label": "Book Generation Engine",
                        "role": "generation_engine_prompt",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_sources/ITALUS_BOOK_GENERATION_ENGINE.txt"],
                    },
                    {
                        "canon_id": "master_storytelling_context",
                        "label": "Master Storytelling Context",
                        "role": "master_context",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_sources/italus_MASTER_STORYTELLING_CONTEXT.txt"],
                    },
                ],
            },
            {
                "group_id": "structured_indexes",
                "label": "Structured Indexes",
                "author_action": "review_structure",
                "description": "Structured manifests for books, events, packs, scenes, and series routing.",
                "items": [
                    {
                        "canon_id": "series_manifest",
                        "label": "Series Manifest",
                        "role": "structured_index",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_manifests/series_manifest.json"],
                    },
                    {
                        "canon_id": "books_manifest",
                        "label": "Books Manifest",
                        "role": "structured_index",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_manifests/books_manifest.json"],
                    },
                    {
                        "canon_id": "events_manifest",
                        "label": "Events Manifest",
                        "role": "structured_index",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_manifests/events_manifest.json"],
                    },
                    {
                        "canon_id": "scene_types_manifest",
                        "label": "Scene Types Manifest",
                        "role": "structured_index",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_manifests/scene_types_manifest.json"],
                    },
                    {
                        "canon_id": "pack_manifest",
                        "label": "Pack Manifest",
                        "role": "structured_index",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_manifests/pack_manifest.json"],
                    },
                ],
            },
            {
                "group_id": "runtime_knowledge_packs",
                "label": "Runtime Knowledge Packs",
                "author_action": "validate_or_regenerate",
                "description": "Compiled runtime packs. Book pack instances are derived from the project's book count.",
                "items": [
                    {
                        "canon_id": "core_knowledge_pack",
                        "label": "Core Knowledge Pack",
                        "role": "runtime_context_pack",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_packs/ITALUS_KNOWLEDGE_PACK_CORE.txt"],
                    },
                    {
                        "canon_id": "generation_knowledge_pack",
                        "label": "Generation Knowledge Pack",
                        "role": "runtime_context_pack",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_LEGACY_ROOT_REFERENCE,
                        "source_files": ["canon_packs/ITALUS_KNOWLEDGE_PACK_GENERATION.txt"],
                    },
                    {
                        "canon_id": "book_knowledge_packs",
                        "label": "Book Knowledge Packs",
                        "role": "runtime_context_pack",
                        "editable": False,
                        "required": True,
                        "source_strategy": SOURCE_DERIVE_FROM_PROJECT_BOOKS,
                        "file_pattern": "canon_packs/ITALUS_KNOWLEDGE_PACK_BOOK_{book_number:02d}.txt",
                    },
                ],
            },
        ],
    },
    "mystery_thriller": {
        "template_id": "mystery_thriller",
        "genre": "mystery_thriller",
        "label": "Mystery / Thriller",
        "description": "A flexible mystery structure with clue, suspect, reveal, and timeline controls.",
        "seed_mode": "blank_project_local",
        "project_storage_mode": "project_local",
        "project_code": "PROJECT",
        "canon_groups": [
            {
                "group_id": "editable_canon",
                "label": "Editable Canon",
                "author_action": "build",
                "items": [
                    _local_item("case_bible", "Case Bible", "primary_canon", "canon_sources/case_bible.md"),
                    _local_item("character_bible", "Character Bible", "primary_canon", "canon_sources/character_bible.md"),
                    _local_item("clue_ledger", "Clue Ledger", "primary_canon", "canon_sources/clue_ledger.md"),
                    _local_item("reveal_chain", "Reveal Chain", "primary_canon", "canon_sources/reveal_chain.md"),
                ],
            },
            _runtime_pack_group(),
        ],
    },
    "science_fiction": {
        "template_id": "science_fiction",
        "genre": "science_fiction",
        "label": "Science Fiction",
        "description": "A flexible science-fiction structure for technology, worlds, factions, and continuity.",
        "seed_mode": "blank_project_local",
        "project_storage_mode": "project_local",
        "project_code": "PROJECT",
        "canon_groups": [
            {
                "group_id": "editable_canon",
                "label": "Editable Canon",
                "author_action": "build",
                "items": [
                    _local_item("world_bible", "World Bible", "primary_canon", "canon_sources/world_bible.md"),
                    _local_item("technology_rules", "Technology Rules", "primary_canon", "canon_sources/technology_rules.md"),
                    _local_item("faction_bible", "Faction Bible", "primary_canon", "canon_sources/faction_bible.md"),
                    _local_item("timeline", "Timeline", "primary_canon", "canon_sources/timeline.md"),
                ],
            },
            _runtime_pack_group(),
        ],
    },
    "fantasy_epic": {
        "template_id": "fantasy_epic",
        "genre": "fantasy_epic",
        "label": "Fantasy Epic",
        "description": "A flexible fantasy structure with world rules, cultures, powers, and timeline constraints.",
        "seed_mode": "blank_project_local",
        "project_storage_mode": "project_local",
        "project_code": "PROJECT",
        "canon_groups": [
            {
                "group_id": "editable_canon",
                "label": "Editable Canon",
                "author_action": "build",
                "items": [
                    _local_item("world_bible", "World Bible", "primary_canon", "canon_sources/world_bible.md"),
                    _local_item("power_rules", "Power / Magic Rules", "primary_canon", "canon_sources/power_rules.md"),
                    _local_item("cultures", "Cultures", "primary_canon", "canon_sources/cultures.md"),
                    _local_item("timeline", "Timeline", "primary_canon", "canon_sources/timeline.md"),
                ],
            },
            _runtime_pack_group(),
        ],
    },
    "memoir": {
        "template_id": "memoir",
        "genre": "memoir",
        "label": "Memoir / Life Story",
        "description": "A factual narrative template with chronology, people, locations, and verification notes.",
        "seed_mode": "blank_project_local",
        "project_storage_mode": "project_local",
        "project_code": "PROJECT",
        "canon_groups": [
            {
                "group_id": "editable_canon",
                "label": "Editable Canon",
                "author_action": "build",
                "items": [
                    _local_item("life_chronology", "Life Chronology", "primary_canon", "canon_sources/life_chronology.md"),
                    _local_item("people", "People", "primary_canon", "canon_sources/people.md"),
                    _local_item("locations", "Locations", "primary_canon", "canon_sources/locations.md"),
                    _local_item("factual_constraints", "Factual Constraints", "validation_rules", "canon_sources/factual_constraints.md"),
                ],
            },
            _runtime_pack_group(),
        ],
    },
    "custom": {
        "template_id": "custom",
        "genre": "custom",
        "label": "Custom",
        "description": "A minimal custom canon structure.",
        "seed_mode": "blank_project_local",
        "project_storage_mode": "project_local",
        "project_code": "PROJECT",
        "canon_groups": [
            {
                "group_id": "editable_canon",
                "label": "Editable Canon",
                "author_action": "build",
                "items": [
                    _local_item("project_bible", "Project Bible", "primary_canon", "canon_sources/project_bible.md"),
                    _local_item("character_notes", "Character Notes", "primary_canon", "canon_sources/character_notes.md"),
                    _local_item("continuity_rules", "Continuity Rules", "validation_rules", "canon_sources/continuity_rules.md"),
                ],
            },
            _runtime_pack_group(),
        ],
    },
}


def normalize_template_id(template_id: str | None, genre: str | None = None) -> str:
    candidate = (template_id or genre or DEFAULT_TEMPLATE_ID or "").strip()
    if candidate in _TEMPLATE_REGISTRY:
        return candidate

    genre_aliases = {
        "historical": "historical_epic",
        "mystery": "mystery_thriller",
        "thriller": "mystery_thriller",
        "fantasy": "fantasy_epic",
        "sci-fi": "science_fiction",
        "scifi": "science_fiction",
        "literary": "custom",
    }
    return genre_aliases.get(candidate, DEFAULT_TEMPLATE_ID)


def get_template(template_id: str | None = None, genre: str | None = None) -> dict[str, Any]:
    resolved_id = normalize_template_id(template_id, genre)
    return deepcopy(_TEMPLATE_REGISTRY[resolved_id])


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "template_id": template["template_id"],
            "genre": template["genre"],
            "label": template["label"],
            "description": template["description"],
            "seed_mode": template["seed_mode"],
            "project_storage_mode": template["project_storage_mode"],
        }
        for template in _TEMPLATE_REGISTRY.values()
    ]
