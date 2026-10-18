"""H1 end-to-end Planner authority: new input, stored plan readiness, cross-genre safety."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__import__("os").environ.get("MORPHEUS_H1_REPO") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT))
from app.services import chapter_plan_service as svc
if __import__("os").environ.get("MORPHEUS_H1_STAGED"):
    import importlib.util
    staged = Path(__import__("os").environ["MORPHEUS_H1_STAGED"])
    spec = importlib.util.spec_from_file_location("app.services.chapter_plan_service", staged)
    svc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(svc)


def ref(label):
    return {"record_id": label, "record_type": "event", "label": label, "source_record_hash": "h"}

def placement(label, relationship="", objective="", anchor=None):
    return {"event_ref": ref(label), "position": "early", "relationship_to_anchor": relationship,
            "anchor_event_ref": ref(anchor) if anchor else None, "chapter_role": "reveal",
            "objective": objective}

def expect_error(fn):
    try:
        fn()
    except svc.ChapterPlanContractError:
        return
    raise AssertionError("Expected a blocked contradictory Planner contract")

def run():
    context = SimpleNamespace(project_id="fiction-test")
    def resolve(_ctx, raw, **kwargs):
        if raw["record_id"] not in kwargs["allowed_ids"]:
            raise svc.ChapterPlanContractError("outside authorized scope")
        return raw
    with patch.object(svc, "_single_ref", side_effect=resolve):
        def normalize(items):
            return svc._normalize_event_placements(
                context, items, allowed_ids={"a", "b", "c"},
                assigned_event_ids={"a", "b", "c"})
        expect_error(lambda: normalize([placement(
            "a", "remembers", "Use a brief external analepsis to the earlier storm.", "b")]))
        expect_error(lambda: normalize([placement(
            "a", "remembers", "An independent historical flashback", "b")]))
        expect_error(lambda: normalize([placement("a", "same_anchor", "start", "a")]))
        expect_error(lambda: normalize([placement("a"), placement("a")]))
        expect_error(lambda: normalize([placement("a", anchor="unknown")]))
        assert normalize([placement("a", "remembers",
                         "An immortal recalls the age before the colony.", "b")])
        assert normalize([placement("a", "alternate_perspective",
                         "A nonlinear timeline viewed by an android.", "b")])
        assert normalize([placement("a", "remembers",
                         "Unreliable narrator recounts an uncertain memory.", "b")])
        # The same restored validation must be exercised on persisted plans
        # through the existing readiness decorator.
        dep = {"scope_selection_ids": ["a","b","c"],
               "book_scope_revision": 0, "book_scope_hash": "",
               "book_plan_revision": 0, "book_plan_hash": "",
               "book_scope_approved": True, "book_plan_approved": True}
        chapter = svc._empty_chapter(1, 1)
        chapter["assigned_event_refs"] = [ref("a"), ref("b")]
        chapter["event_placements"] = [placement(
            "a","remembers","Use an external analepsis rather than a memory.","b")]
        chapter["selected_canon_refs"] = []
        with patch.object(svc, "_dependency_snapshot", return_value=dep), \
             patch.object(svc.canon_index_service, "get_record_by_id", return_value={"status":"found"}), \
             patch.object(svc.pov_contract_service, "normalize_plan_settings", return_value=("","")), \
             patch.object(svc.story_control_service, "validate_story_control_refs",
                          return_value={"valid": True, "issues": []}):
            blocked = svc._decorate_chapter(context, {}, book_number=1, chapter=chapter, exists=True)
            assert blocked["generation_readiness"]["ready"] is False, blocked
            assert blocked["validation"]["valid"] is False, blocked
            assert blocked["lifecycle_state"] == svc.CHAPTER_STATUS_RECONCILIATION_REQUIRED
            assert any(i.get("code") == "chapter_event_authority_invalid"
                       for i in blocked["validation"]["issues"])
            assert chapter["event_placements"][0]["relationship_to_anchor"] == "remembers"
            chapter["event_placements"] = [placement(
                "a","remembers","The immortal recounts a genuine prior experience.","b")]
            ready = svc._decorate_chapter(context, {}, book_number=1, chapter=chapter, exists=True)
            assert ready["generation_readiness"]["ready"] is True, ready
    print("PRIMARY45D H1 COMPLETE PLANNER AUTHORITY PASS")


if __name__ == "__main__":
    run()
