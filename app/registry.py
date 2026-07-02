import json
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BACKUPS_DIR = PROJECT_ROOT / "data_backups"

BOOK_STATE_PATH = DATA_DIR / "book_state.json"
CHAPTER_DIGESTS_PATH = DATA_DIR / "chapter_continuity_digests.json"
BOOKS_PATH = DATA_DIR / "books.json"
CHAPTERS_PATH = DATA_DIR / "chapters.json"
SCENES_PATH = DATA_DIR / "scenes.json"
COVERAGE_PATH = DATA_DIR / "coverage_map.json"
EVENT_INDEX_PATH = DATA_DIR / "event_index.json"
SESSION_STATE_PATH = DATA_DIR / "session_state.json"
APP_SETTINGS_PATH = DATA_DIR / "app_settings.json"
MAX_BACKUP_SNAPSHOTS = 100
MAX_BACKUP_AGE_DAYS = 30



def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    
def load_book_state() -> dict:
    """
    Load persistent book-level continuity state.
    """
    return load_json(BOOK_STATE_PATH, {})


def save_book_state(state: dict):
    """
    Save persistent book-level continuity state.
    """
    save_json(BOOK_STATE_PATH, state)


def load_book_state_for(book_id: str) -> dict:
    """
    Return continuity state for one book_id only.
    """
    if not book_id:
        return {}
    state = load_book_state()
    return state.get(book_id, {})


def update_book_state(book_id: str, data: dict):
    """
    Merge updates into a single book's continuity state.
    """
    if not book_id:
        return
    state = load_book_state()
    state.setdefault(book_id, {})
    state[book_id].update(data)
    save_book_state(state)


def load_chapter_digests() -> dict:
    """
    Load all chapter continuity digests.
    """
    return load_json(CHAPTER_DIGESTS_PATH, {})


def save_chapter_digests(data: dict):
    """
    Save all chapter continuity digests.
    """
    save_json(CHAPTER_DIGESTS_PATH, data)


def load_chapter_digest(chapter_id: str) -> dict:
    """
    Return continuity digest for one chapter_id only.
    """
    if not chapter_id:
        return {}
    digests = load_chapter_digests()
    return digests.get(chapter_id, {})


def update_chapter_digest(chapter_id: str, digest_data: dict):
    """
    Merge updates into a single chapter continuity digest.
    """
    if not chapter_id:
        return
    digests = load_chapter_digests()
    digests.setdefault(chapter_id, {})
    digests[chapter_id].update(digest_data)
    save_chapter_digests(digests) 


def load_books():
    return load_json(BOOKS_PATH, [])

def load_chapters():
    return load_json(CHAPTERS_PATH, [])

def load_scenes():
    return load_json(SCENES_PATH, [])

def load_coverage():
    return load_json(COVERAGE_PATH, {"saga_id": "ITALUS_SAGA", "generated_at": "", "books": {}, "events": {}})

def load_event_index():
    return load_json(EVENT_INDEX_PATH, [])

def save_scenes(scenes):
    save_json(SCENES_PATH, scenes)

def save_chapters(chapters):
    save_json(CHAPTERS_PATH, chapters)

def save_coverage(coverage):
    save_json(COVERAGE_PATH, coverage)

def add_scene(scene_record: dict):
    scenes = load_scenes()
    scenes.append(scene_record)
    save_scenes(scenes)
    
def load_session_state() -> dict:
    if not SESSION_STATE_PATH.exists():
        return {}
    with open(SESSION_STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session_state(state: dict):
    with open(SESSION_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        
def load_app_settings() -> dict:
    if not APP_SETTINGS_PATH.exists():
        return {"timezone": "America/New_York"}
    with open(APP_SETTINGS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_app_settings(settings: dict):
    with open(APP_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)



def prune_old_backups(max_snapshots: int = MAX_BACKUP_SNAPSHOTS, max_age_days: int = MAX_BACKUP_AGE_DAYS):
    """
    Enforce backup retention policy:
    1. delete backups older than max_age_days
    2. keep only the newest max_snapshots backups
    """
    if not BACKUPS_DIR.exists():
        return

    now = datetime.now()
    backup_dirs = [p for p in BACKUPS_DIR.iterdir() if p.is_dir()]

    # Remove backups older than retention age
    for backup_dir in backup_dirs:
        try:
            age_days = (now - datetime.fromtimestamp(backup_dir.stat().st_mtime)).days
            if age_days > max_age_days:
                shutil.rmtree(backup_dir, ignore_errors=True)
        except Exception:
            continue

    # Refresh list after age-based pruning
    backup_dirs = [p for p in BACKUPS_DIR.iterdir() if p.is_dir()]
    backup_dirs = sorted(backup_dirs, key=lambda p: p.stat().st_mtime, reverse=True)

    # Keep only newest N
    for old_dir in backup_dirs[max_snapshots:]:
        shutil.rmtree(old_dir, ignore_errors=True)

        
def create_data_backup(label: str = "manual") -> str:
    """
    Create a timestamped backup snapshot of runtime JSON data files.
    Returns the backup directory path as a string.
    """
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUPS_DIR / f"{timestamp}_{label}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    files_to_backup = [
        BOOKS_PATH,
        CHAPTERS_PATH,
        SCENES_PATH,
        COVERAGE_PATH,
        EVENT_INDEX_PATH,
        SESSION_STATE_PATH,
        APP_SETTINGS_PATH,
    ]

    optional_paths = [
        DATA_DIR / "book_state.json",
        DATA_DIR / "chapter_continuity_digests.json",
    ]

    for path in files_to_backup + optional_paths:
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)

    prune_old_backups()

    return str(backup_dir)