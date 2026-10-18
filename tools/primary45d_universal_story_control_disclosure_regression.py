"""Cross-project structured Story Control disclosure regression, no live provider calls."""
import json
from copy import deepcopy
from pathlib import Path

from app.services.generation_knowledge_projection_service import (
    build_projection, GenerationKnowledgeProjectionError,
)

repo = Path(__file__).resolve().parents[1]
source = json.loads((repo / "data/projects/italus-saga/canon_packs/chapter_knowledge_pack/book_01_chapter_001.json").read_text(encoding="utf-8"))
guardrails = {"chapter_restrictions": source.get("validator_sidecar", {}).get("chapter_restrictions", [])}
types = (
    "mystery_reveal", "knowledge_change", "relationship_change",
    "availability_change", "escalation_change",
)

def projection(sidecar):
    return build_projection(sidecar, raw_chapter_text="", generation_guardrails=guardrails)["projection"]

def reject(sidecar, description):
    try:
        projection(sidecar)
    except GenerationKnowledgeProjectionError:
        return
    raise AssertionError("FAIL OPEN: " + description)

actual = projection(source)
assert actual["chapter_disclosure_authority"][0]["control_type"] == "mystery_reveal"
assert "farovald-nerve-reflex" not in json.dumps(actual["chapter_disclosure_authority"])
assert actual["chapter_disclosure_authority"][0]["permitted_claims"]

for project_id, book, chapter in (("sample-alpha", 3, 7), ("sample-beta", 2, 19)):
    case = deepcopy(source)
    case["project_id"] = project_id
    case["book_number"] = book
    case["chapter_number"] = chapter
    case["story_controls"] = []
    case["story_control_refs"] = []
    for index, kind in enumerate(types):
        control = deepcopy(source["story_controls"][0])
        control["control_id"] = f"{project_id}-control-{index}"
        control["control_type"] = kind
        control["book_number"] = book
        control["chapter_number"] = chapter
        control["allowed_interpretations"] = [f"chapter-scoped-authorized-{index}"] if index % 2 == 0 else []
        control["forbidden_assertions"] = [f"never-disclose-{index}"]
        case["story_controls"].append(control)
        case["story_control_refs"].append(control["control_id"])
    result = projection(case)
    declarations = result["chapter_disclosure_authority"]
    assert [c["control_type"] for c in declarations] == list(types)
    assert len(declarations) == len(types)
    assert all(c["book_number"] == book and c["chapter_number"] == chapter for c in declarations)
    assert all(c["forbidden_claims"] == [f"never-disclose-{i}"] for i,c in enumerate(declarations))
    assert not declarations[1]["permitted_claims"], "Empty permissions must grant nothing"
    assert result["project_id"] == project_id
    mismatch = deepcopy(case)
    mismatch["story_controls"][1]["chapter_number"] = chapter+1
    reject(mismatch, "wrong chapter on non-mystery control")
    inactive = deepcopy(case)
    inactive["story_controls"][2]["protection"]["eligibility_status"] = "INACTIVE"
    reject(inactive, "inactive non-mystery control")
    missing = deepcopy(case)
    missing["story_control_refs"].remove(missing["story_controls"][3]["control_id"])
    reject(missing, "missing active reference")
    duplicate = deepcopy(case)
    duplicate["story_controls"].append(deepcopy(duplicate["story_controls"][0]))
    reject(duplicate, "duplicate control identity")
    unknown = deepcopy(case)
    unknown["story_controls"][4]["control_type"] = "unsupported_disclosure"
    reject(unknown, "unknown control type")
    malformed = deepcopy(case)
    malformed["story_controls"][1]["forbidden_assertions"] = ["ok", None]
    reject(malformed, "malformed forbidden claim")
    none = deepcopy(case)
    none["story_controls"] = []
    none["story_control_refs"] = []
    assert projection(none)["chapter_disclosure_authority"] == []

print("PRIMARY45D UNIVERSAL STORY CONTROL DISCLOSURE PASS")
