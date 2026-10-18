"""Primary 45D: provider projection must not forward unknown establishment metadata."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "app/services/generation_knowledge_projection_service.py"
spec = importlib.util.spec_from_file_location("projection_under_test", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

sidecar = {
    "project_id": "test",
    "book_number": 1,
    "chapter_number": 2,
    "chapter_execution_contract": {},
    "continuity": {
        "required": True,
        "bounded_state": {
            "established": [{
                "type": "reveal_established",
                "target_ref": "reveal-1",
                "book_number": 1,
                "chapter_number": 1,
                "future_reveal": "LEAK_SENTINEL",
            }]
        }
    },
}
result = mod.build_projection(
    sidecar, raw_chapter_text="", generation_guardrails={"chapter_restrictions": ["test"]}
)
entries = result["projection"]["approved_continuity"]["bounded_state"]["established"]
assert entries == [{
    "type": "reveal_established",
    "target_ref": "reveal-1",
    "book_number": 1,
    "chapter_number": 1,
}], entries
assert "LEAK_SENTINEL" not in result["projection_text"]
print("PRIMARY45D ESTABLISHED PROJECTION PASS")
