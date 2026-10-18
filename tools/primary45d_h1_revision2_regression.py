"""H1 Revision 2: deterministic event invariants without genre-specific text heuristics."""
import os
import sys
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(os.environ.get("MORPHEUS_H1_REPO") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT))
STAGED = os.environ.get("MORPHEUS_H1_STAGED")
if STAGED:
    spec = importlib.util.spec_from_file_location("app.services.chapter_plan_service", STAGED)
    svc = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = svc
    spec.loader.exec_module(svc)
else:
    from app.services import chapter_plan_service as svc


def ref(record_id):
    return {"record_id": record_id, "record_type": "event",
            "label": record_id, "source_record_hash": "synthetic"}


def placement(record_id, *, relationship="", anchor=None, objective=""):
    return {"event_ref": ref(record_id), "position": "early",
            "relationship_to_anchor": relationship,
            "anchor_event_ref": ref(anchor) if anchor else None,
            "chapter_role": "reveal", "objective": objective}


def rejection(fn):
    try:
        fn()
    except svc.ChapterPlanContractError:
        return
    raise AssertionError("Expected structural Planner contradiction to fail")


def run():
    ctx = SimpleNamespace(project_id="synthetic-nonproduction")
    allowed = {"event589", "event789", "event800"}
    def resolve(_ctx, raw, **kwargs):
        if raw["record_id"] not in kwargs["allowed_ids"]:
            raise svc.ChapterPlanContractError("outside scope")
        return raw

    with patch.object(svc, "_single_ref", side_effect=resolve):
        def normalize(rows, assigned=None):
            return svc._normalize_event_placements(
                ctx, rows, allowed_ids=allowed,
                assigned_event_ids=assigned if assigned is not None else allowed
            )
        assert normalize([
            placement("event789"),
            placement("event589", relationship="remembers", anchor="event789",
                      objective="A brief external analepsis to a century before the mainline.")
        ])
        assert normalize([placement("event589", relationship="remembers",
                                    anchor="event789",
                                    objective="An immortal remembers an earlier century.")])
        assert normalize([placement("event800", relationship="alternate_perspective",
                                    anchor="event789",
                                    objective="Time travel during a nonlinear flashback.")])
        rejection(lambda: normalize([placement("event589"), placement("event589")]))
        rejection(lambda: normalize([placement("event589", relationship="follows",
                                               anchor="event589")]))
        rejection(lambda: normalize([placement("event589", relationship="follows",
                                               anchor="event800")],
                                              assigned={"event589", "event789"}))
        rejection(lambda: normalize([placement("event589")], assigned=set()))
        rejection(lambda: normalize([placement("event589", anchor="not_in_scope")]))
    # Saved plans receive the same structural checks at readiness time.
    chapter = svc._empty_chapter(1, 1)
    chapter["selected_canon_refs"] = []
    chapter["assigned_event_refs"] = [ref("event589"), ref("event789")]
    chapter["event_placements"] = [
        placement("event789"),
        placement("event589", relationship="remembers", anchor="event789",
                  objective="A brief external analepsis.")
    ]
    dependency = {
        "scope_selection_ids": ["event589", "event789"],
        "book_scope_revision": 0, "book_scope_hash": "",
        "book_plan_revision": 0, "book_plan_hash": "",
        "book_scope_approved": True, "book_plan_approved": True
    }
    with patch.object(svc, "_dependency_snapshot", return_value=dependency), \
         patch.object(svc.canon_index_service, "get_record_by_id",
                      return_value={"status": "found"}), \
         patch.object(svc.pov_contract_service, "normalize_plan_settings",
                      return_value=("", "")), \
         patch.object(svc.story_control_service, "validate_story_control_refs",
                      return_value={"valid": True, "issues": []}), \
         patch.object(svc, "_single_ref", side_effect=resolve):
        valid = svc._decorate_chapter(ctx, {}, book_number=1,
                                      chapter=chapter, exists=True)
        assert valid["generation_readiness"]["ready"] is True, valid
        chapter["event_placements"].append(placement("event589"))
        invalid = svc._decorate_chapter(ctx, {}, book_number=1,
                                        chapter=chapter, exists=True)
        assert invalid["generation_readiness"]["ready"] is False, invalid
        assert any(row["code"] == "chapter_event_authority_invalid"
                   for row in invalid["validation"]["issues"]), invalid
    print("PRIMARY45D H1 REVISION 2 STRUCTURAL AUTHORITY PASS")


if __name__ == "__main__":
    run()
