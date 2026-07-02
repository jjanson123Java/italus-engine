import copy
import json
from pathlib import Path

import project_runner
import registry


def load_raw_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_raw_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def base_request() -> dict:
    return {
        "event_name": "Galileo Trial",
        "chapter_id": "BOOK_07_CH_08",
        "location": "Nowhere",
        "scene_type": "continuation",
        "time_window": "later",
        "tone": "test",
        "pov": "Domenico",
        "guardian": "Domenico",
        "year": 1633,
        "book_id": "BOOK_07",
        "event_id": "EV108",
    }


def run_save_test(name: str, request: dict, should_pass: bool):
    before = len(registry.load_scenes())

    try:
        scene = project_runner.save_accepted_scene(
            request=request,
            title=f"{name} Title",
            summary=f"{name} Summary",
        )
        after = len(registry.load_scenes())

        if not should_pass:
            return {
                "name": name,
                "status": "FAIL",
                "detail": "Expected failure, but scene was saved.",
                "before": before,
                "after": after,
                "saved_scene": scene,
            }

        return {
            "name": name,
            "status": "PASS",
            "detail": "Scene saved as expected.",
            "before": before,
            "after": after,
            "saved_scene": scene,
        }

    except Exception as e:
        after = len(registry.load_scenes())

        if should_pass:
            return {
                "name": name,
                "status": "FAIL",
                "detail": f"Expected success, but got exception: {e}",
                "before": before,
                "after": after,
                "saved_scene": None,
            }

        return {
            "name": name,
            "status": "PASS",
            "detail": f"Failed as expected: {e}",
            "before": before,
            "after": after,
            "saved_scene": None,
        }


def validate_saved_scene_fields(result: dict, expected_parent: str, expected_callbacks: list[str]):
    scene = result.get("saved_scene")
    if not scene:
        return {
            "name": result["name"] + " field check",
            "status": "FAIL",
            "detail": "No saved scene available to inspect.",
        }

    parent_ok = scene.get("parent_scene_id") == expected_parent
    continued_ok = scene.get("continued_from_scene_id") == expected_parent
    callback_ok = scene.get("callback_scene_ids") == expected_callbacks

    if parent_ok and continued_ok and callback_ok:
        return {
            "name": result["name"] + " field check",
            "status": "PASS",
            "detail": "Saved scene fields are correct.",
        }

    return {
        "name": result["name"] + " field check",
        "status": "FAIL",
        "detail": (
            f"Field mismatch. "
            f"parent_scene_id={scene.get('parent_scene_id')}, "
            f"continued_from_scene_id={scene.get('continued_from_scene_id')}, "
            f"callback_scene_ids={scene.get('callback_scene_ids')}"
        ),
    }


def print_result(result: dict):
    print(f"\n=== {result['name']} ===")
    print(f"Status : {result['status']}")
    print(f"Detail : {result['detail']}")
    if "before" in result:
        print(f"Before : {result['before']}")
        print(f"After  : {result['after']}")


def main():
    scenes_path = registry.SCENES_PATH
    original_scenes = load_raw_json(scenes_path)

    results = []

    try:
        # Test 1 — Missing parent
        req = base_request()
        results.append(run_save_test("Test 1 Missing Parent", req, should_pass=False))

        # Test 2 — Nonexistent parent
        req = base_request()
        req["continued_from_scene_id"] = "BOOK_07_CH_99_SC_99"
        results.append(run_save_test("Test 2 Nonexistent Parent", req, should_pass=False))

        # Test 3 — Parent not latest canon scene
        req = base_request()
        req["continued_from_scene_id"] = "BOOK_07_CH_06_SC_01"
        results.append(run_save_test("Test 3 Not Latest Parent", req, should_pass=False))

        # Test 4 — Valid latest parent
        req = base_request()
        req["continued_from_scene_id"] = "BOOK_07_CH_08_SC_01"
        req["callback_scene_ids"] = []
        result = run_save_test("Test 4 Valid Latest Parent", req, should_pass=True)
        results.append(result)
        results.append(
            validate_saved_scene_fields(
                result,
                expected_parent="BOOK_07_CH_08_SC_01",
                expected_callbacks=[],
            )
        )

        # Restore baseline after pass test
        save_raw_json(scenes_path, copy.deepcopy(original_scenes))

        # Test 5 — Valid callback
        req = base_request()
        req["continued_from_scene_id"] = "BOOK_07_CH_08_SC_01"
        req["callback_scene_ids"] = ["BOOK_07_CH_06_SC_01"]
        result = run_save_test("Test 5 Valid Callback", req, should_pass=True)
        results.append(result)
        results.append(
            validate_saved_scene_fields(
                result,
                expected_parent="BOOK_07_CH_08_SC_01",
                expected_callbacks=["BOOK_07_CH_06_SC_01"],
            )
        )

        # Restore baseline after pass test
        save_raw_json(scenes_path, copy.deepcopy(original_scenes))

        # Test 6 — Bad callback
        req = base_request()
        req["continued_from_scene_id"] = "BOOK_07_CH_08_SC_01"
        req["callback_scene_ids"] = ["BOOK_07_CH_99_SC_99"]
        results.append(run_save_test("Test 6 Bad Callback", req, should_pass=False))

        # Test 7 — Duplicate callback
        req = base_request()
        req["continued_from_scene_id"] = "BOOK_07_CH_08_SC_01"
        req["callback_scene_ids"] = ["BOOK_07_CH_06_SC_01", "BOOK_07_CH_06_SC_01"]
        results.append(run_save_test("Test 7 Duplicate Callback", req, should_pass=False))

        # Test 8 — Callback not a list
        req = base_request()
        req["continued_from_scene_id"] = "BOOK_07_CH_08_SC_01"
        req["callback_scene_ids"] = "BOOK_07_CH_06_SC_01"
        results.append(run_save_test("Test 8 Callback Not List", req, should_pass=False))

        # Test 9 — Parent duplicated in callback list
        req = base_request()
        req["continued_from_scene_id"] = "BOOK_07_CH_08_SC_01"
        req["callback_scene_ids"] = ["BOOK_07_CH_08_SC_01"]
        results.append(run_save_test("Test 9 Parent In Callback List", req, should_pass=False))

        # Test 10 — Non-continuation scene with callbacks
        req = base_request()
        req["scene_type"] = "private conversation"
        req.pop("continued_from_scene_id", None)
        req["callback_scene_ids"] = ["BOOK_07_CH_06_SC_01"]
        result = run_save_test("Test 10 Non-Continuation With Callback", req, should_pass=True)
        results.append(result)

    finally:
        # Always restore the original scenes.json
        save_raw_json(scenes_path, original_scenes)

    print("\n\n########## REGRESSION TEST RESULTS ##########")
    pass_count = 0
    fail_count = 0

    for result in results:
        print_result(result)
        if result["status"] == "PASS":
            pass_count += 1
        else:
            fail_count += 1

    print("\n########## SUMMARY ##########")
    print(f"Passed: {pass_count}")
    print(f"Failed: {fail_count}")


if __name__ == "__main__":
    main()