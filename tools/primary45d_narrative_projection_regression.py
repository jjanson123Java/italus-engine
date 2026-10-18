"""Primary 45D source-bound narrative projection behavioral regression."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.generation_knowledge_projection_service import (
    GenerationKnowledgeProjectionError, build_projection,
)

ROOT = Path(__file__).resolve().parents[1]
SIDE = ROOT / "data/projects/italus-saga/canon_packs/chapter_knowledge_pack/book_01_chapter_001.json"
PLAN = ROOT / "data/projects/italus-saga/chapter_plan.json"

def project(sidecar):
    return build_projection(
        sidecar, raw_chapter_text="",
        generation_guardrails={"chapter_restrictions": ["No future revelations"]},
    )["projection"]

sidecar = json.loads(SIDE.read_text(encoding="utf-8"))
plan = json.loads(PLAN.read_text(encoding="utf-8"))
chapter = next(ch for book in plan["books"] if book["book_number"] == 1
               for ch in book["chapters"] if ch["chapter_number"] == 1)
# The uploaded data was compiled before Patch 1; reproduce compilation output
# exclusively from the actual authored Chapter Plan and sidecar source identity.
sidecar["chapter_narrative_source"] = {
    "chapter_objective": chapter["chapter_objective"].strip(),
    "generation_kickoff": chapter["generation_kickoff"].strip(),
    "chapter_plan_sha256": sidecar["source"]["chapter_plan_sha256"],
    "chapter_plan_revision": sidecar["source"]["chapter_plan_revision"],
}
p = project(sidecar)
brief = p["chapter_narrative_brief"]
assert brief["chapter_objective"] == chapter["chapter_objective"]
assert brief["generation_kickoff"] == chapter["generation_kickoff"]
assert "family and village suspicion" in brief["chapter_objective"]
assert p["raw_canon_records_included"] is False
assert p["raw_chapter_knowledge_included"] is False
assert p["chapter_disclosure_authority"]
assert p["chapter_execution"]["required_event_sequence"]
assert p["chapter_execution"]["pov_contract"]["configured"] is True

# Project ID, book, and chapter are dynamic, not hard-coded to Italus Saga.
foreign = json.loads(json.dumps(sidecar))
foreign["project_id"] = "synthetic-cross-project"
foreign["book_number"] = 2
foreign["chapter_number"] = 7
for control in foreign["story_controls"]:
    control["book_number"] = 2
    control["chapter_number"] = 7
foreign["chapter_narrative_source"]["chapter_objective"] = "Investigate a missing lantern through three authorized encounters."
foreign["chapter_narrative_source"]["generation_kickoff"] = "Open with the empty lantern hook."
fp = project(foreign)
assert fp["project_id"] == "synthetic-cross-project"
assert fp["chapter_narrative_brief"]["generation_kickoff"] == "Open with the empty lantern hook."

for badkey, badvalue in [
    ("chapter_plan_sha256", "f" * 64),
    ("chapter_objective", ""),
    ("generation_kickoff", ""),
    ("chapter_plan_revision", -1),
]:
    corrupt = json.loads(json.dumps(sidecar))
    corrupt["chapter_narrative_source"][badkey] = badvalue
    try:
        project(corrupt)
    except GenerationKnowledgeProjectionError:
        pass
    else:
        raise AssertionError("Malformed source authority passed: " + badkey)

# Preserve legacy synthetic test inputs without a newly compiled narrative source.
legacy = json.loads(json.dumps(sidecar))
legacy.pop("chapter_narrative_source")
assert "chapter_narrative_brief" not in project(legacy)
print("PRIMARY45D NARRATIVE PROJECTION PASS")
