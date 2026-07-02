from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANON_PACKS_DIR = PROJECT_ROOT / "canon_packs"

    
def load_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_core_pack():
    return load_text_if_exists(CANON_PACKS_DIR / "ITALUS_KNOWLEDGE_PACK_CORE.txt")


def load_generation_pack():
    return load_text_if_exists(CANON_PACKS_DIR / "ITALUS_KNOWLEDGE_PACK_GENERATION.txt")


def load_book_pack(book_id: str):
    if not book_id:
        return ""
    filename = f"ITALUS_KNOWLEDGE_PACK_{book_id}.txt"
    return load_text_if_exists(CANON_PACKS_DIR / filename)

def build_generation_prompt(request, event_scenes, coverage, book_state, chapter_digest):
    
    core_pack = load_core_pack()
    generation_pack = load_generation_pack()
    book_pack = load_book_pack(request.get("book_id", ""))
    book_state_block = json.dumps(book_state, indent=2) if book_state else "- none"
    chapter_digest_block = json.dumps(chapter_digest, indent=2) if chapter_digest else "- none"

    # Local import avoids circular-import risk if prompt_builder is imported early
    from app.registry import load_scenes

    all_scenes = load_scenes()
    scene_map = {s.get("scene_id"): s for s in all_scenes}

    def summarize_scene(scene):
        return (
            f'{scene.get("scene_id", "")} | '
            f'{scene.get("title", "")} | '
            f'{scene.get("year", "")} | '
            f'{scene.get("event_name", "")} | '
            f'{scene.get("guardian", "")} | '
            f'{scene.get("location", "")} | '
            f'{scene.get("scene_type", "")} | '
            f'{scene.get("tone", "")} | '
            f'Summary: {scene.get("summary", "")}'
        )

    covered = "\n".join(
    f'- {s.get("scene_id","")} | {s.get("title","")} — {s.get("scene_type","")} — {s.get("location","")} — {s.get("tone","")}'
    for s in event_scenes
) or "- none"

    coverage_block = coverage.get("events", {}).get(request.get("event_name", ""), {})
    recommended = coverage_block.get("recommended_scene_types", [])
    recommended_block = "\n".join(f"- {item}" for item in recommended) or "- none"

    # --- Direct structural parent ---
    parent_scene = None
    parent_scene_id = request.get("continued_from_scene_id")
    if parent_scene_id:
        parent_scene = scene_map.get(parent_scene_id)

    if parent_scene:
        parent_block = summarize_scene(parent_scene)
    else:
        parent_block = "- none"

    # --- Callback/reference scenes ---
    callback_ids = request.get("callback_scene_ids", []) or []
    callback_scenes = [scene_map[cid] for cid in callback_ids if cid in scene_map]

    callback_block = "\n".join(
        f"- {summarize_scene(scene)}"
        for scene in callback_scenes
    ) or "- none"

    return f"""
ITALUS KNOWLEDGE PACK — CORE
{core_pack or "- none"}

ITALUS KNOWLEDGE PACK — GENERATION
{generation_pack or "- none"}

ITALUS KNOWLEDGE PACK — BOOK
{book_pack or "- none"}

BOOK CONTINUITY STATE
{book_state_block}

CHAPTER CONTINUITY DIGEST
{chapter_digest_block}

Current request:
- book_id: {request.get("book_id", "")}
- chapter_id: {request.get("chapter_id", "")}
- year: {request.get("year", "")}
- event_id: {request.get("event_id", "")}
- event_name: {request.get("event_name", "")}
- guardian: {request.get("guardian", "")}
- location: {request.get("location", "")}
- scene_type: {request.get("scene_type", "")}
- time_window: {request.get("time_window", "")}
- tone: {request.get("tone", "")}
- pov: {request.get("pov", "")}

Direct continuity parent scene:
{parent_block}

Callback/reference scenes:
{callback_block}

Known canon scenes already generated for this event:
{covered}

Recommended underused scene types for this event:
{recommended_block}

Instruction:
1. Apply the core knowledge pack as the primary canon authority.
2. Apply the generation pack as the scene-writing rule set.
3. Apply the book pack, when present, as the local book continuity layer.
4. If duplicate detection triggers, return the required user-facing duplicate structure.
5. If NEW ANGLE is offered, make each option descriptive in one sentence so the author knows the likely direction.
6. Use the direct continuity parent as the primary canon anchor for narrative sequence, state, and causality.
7. Use callback/reference scenes only as thematic, memory, symbolic, or emotional context.
8. Do not treat callback/reference scenes as the most recent event unless explicitly instructed.
9. If any canon rule fails, stop and report the conflict.
10. If no canon rules fail, generate the scene.
""".strip()