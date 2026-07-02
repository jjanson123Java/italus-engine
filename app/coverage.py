from collections import defaultdict
from datetime import datetime
from app.registry import load_scenes, save_json, COVERAGE_PATH

VALID_SCENE_TYPES = [
    "aftermath",
    "lead-up",
    "private conversation",
    "street reaction",
    "travel reflection",
    "institutional response",
    "trial observer"
]

def build_coverage():
    scenes = load_scenes()
    events = defaultdict(lambda: {
        "scene_count": 0,
        "locations_used": set(),
        "povs_used": set(),
        "scene_types_used": set()
    })

    for s in scenes:
        if s.get("status") != "canon":
            continue
        e = events[s["event_name"]]
        e["scene_count"] += 1
        e["locations_used"].add(s["location"])
        e["povs_used"].add(s["pov"])
        e["scene_types_used"].add(s["scene_type"])

    coverage = {
        "saga_id": "ITALUS_SAGA",
        "generated_at": datetime.utcnow().isoformat(),
        "events": {}
    }

    for event_name, data in events.items():
        coverage["events"][event_name] = {
            "scene_count": data["scene_count"],
            "locations_used": sorted(data["locations_used"]),
            "povs_used": sorted(data["povs_used"]),
            "scene_types_used": sorted(data["scene_types_used"]),
            "recommended_scene_types": [
                t for t in VALID_SCENE_TYPES if t not in data["scene_types_used"]
            ]
        }

    save_json(COVERAGE_PATH, coverage)
    return coverage