from datetime import datetime, timezone
from project_runner import save_accepted_scene

scene_record = {
    "scene_id": "TEST_SCENE_001",
    "book_id": "BOOK_01",
    "chapter_id": "BOOK_01_CH_01",
    "event_id": "EV001",
    "event_name": "Test Event",
    "guardian": "Test Guardian",
    "location": "Test Location",
    "scene_type": "dialogue",
    "tone": "test tone",
    "pov": "third_person",
    "time_window": "test",
    "characters_present": ["Test Character"],
    "scene_summary": "Test scene summary for backup verification",
    "created_at": datetime.now(timezone.utc).isoformat()
}

title = "Backup System Test Scene"

save_accepted_scene(scene_record, title)

print("Scene saved and backup created.")