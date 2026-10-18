"""Bounded static regression for 45D event anchor/participant reference authority."""
from pathlib import Path

source = (Path(__file__).resolve().parents[1] / "app/services/generation_service.py").read_text(encoding="utf-8")
checks = {
    "event anchor identity": 'hard_event.get("anchor_event_ref")',
    "event label identity": 'hard_event.get("event_ref") or {}).get("label")',
    "participant/location reference check": '"execution_reference_authority_mismatch"',
    "participant reference": '"required_participants", "required_participants"',
    "location reference": '"required_locations", "required_locations"',
}
for name, marker in checks.items():
    if marker not in source:
        raise AssertionError(f"Missing {name}: {marker}")
print("PRIMARY45D EXECUTION REFERENCE ALIGNMENT PASS")
