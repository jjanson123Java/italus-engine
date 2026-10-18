"""Primary 45D reference authority integrity: actual function negative/positive tests."""
from app.services import generation_service as generation
from app.services import generation_knowledge_projection_service as projection

def expect_error(fn, err, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except err:
        return
    raise AssertionError("Expected fail-closed rejection was not raised")

valid = [{"record_id": "event-1", "record_type": "event", "label": "Authorized event"}]
assert projection._safe_refs(valid) == valid
expect_error(projection._safe_refs, projection.GenerationKnowledgeProjectionError, [{"label": "Unidentified future revelation"}])
expect_error(projection._safe_refs, projection.GenerationKnowledgeProjectionError, [None])
expect_error(projection._safe_refs, projection.GenerationKnowledgeProjectionError, {"record_id": "event-1"})
sidecar = {
    "book_number": 1, "chapter_number": 2,
    "chapter_execution_contract": {
        "required_participant_refs": valid,
        "required_location_refs": [],
        "required_event_sequence": [],
        "pov_contract": {"character_refs": valid},
    },
}
good = generation._build_generation_guardrails(sidecar)
assert good["required_participants"] == valid
assert good["pov_contract"]["authorized_characters"] == valid
for field in ("required_participant_refs", "required_location_refs"):
    mutated = {**sidecar, "chapter_execution_contract": {
        **sidecar["chapter_execution_contract"], field: [{"label": "No record identity"}]}}
    expect_error(generation._build_generation_guardrails, generation.GenerationRequestBuildError, mutated)
mutated = {**sidecar, "chapter_execution_contract": {
    **sidecar["chapter_execution_contract"], "pov_contract": {"character_refs": [None]}}}
expect_error(generation._build_generation_guardrails, generation.GenerationRequestBuildError, mutated)
print("PRIMARY45D REFERENCE AUTHORITY INTEGRITY PASS")
