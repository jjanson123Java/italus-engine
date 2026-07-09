# ITALUS AUTHOR VOICE SUBSYSTEM STATE FILE — FUTURE IMPLEMENTATION

Generated: 2026-07-08  
Project: Italus Narrative Studio / Italus novel workspace migration  
Subsystem: Author Voice / Narrative Voice / Character Voice / Project-Series Voice / Genre Voice / Scene-Level Voice  
Current main project phase: Stage 9 — Runtime Storage Architecture Review  
Subsystem status: FUTURE ARCHITECTURE COMPONENT — LOCKED, NOT YET IMPLEMENTED  
Implementation rule: Do not implement this subsystem until project-local runtime storage and prompt routing through ProjectContext are stable.

---

## 1. Purpose Of This State File

This file preserves the full architectural design for the future Italus Voice subsystem so it is not lost while the project continues through runtime storage migration.

The voice subsystem gives Italus a major authorship advantage:

- It allows Italus to learn from accepted author decisions.
- It distinguishes the author’s long-term literary fingerprint from the narrator, characters, genre, project, and scene tone.
- It prevents generic AI prose by grounding future generation in project-local, author-approved literary memory.
- It enables local voice analysis through Ollama without sending author style material to external providers.
- It stores structured voice memory in SQLite so the voice system can grow over time without becoming scattered JSON or uncontrolled prompt text.

Core decision:

```text
Author Voice is approved as a future subsystem.
Author Voice is not approved for immediate Stage 9 runtime storage implementation.
```

---

## 2. Current Project Boundary

The current main Italus migration phase is:

```text
Stage 9 — Runtime Storage Architecture Review
```

Stage 8 is complete:

```text
Validation / Export Readiness Panels
Validation / Export contrast fix
Stage 8 docs alignment
```

Immediate Stage 9 work remains focused on:

```text
project-local runtime storage
runtime file contract
runtime initialization rules
source-of-truth matrix
rollback rules
protected backend runtime file boundaries
```

Author Voice must not contaminate Stage 9 runtime storage work.

Allowed now:

```text
Document Author Voice as a future subsystem.
Preserve architecture notes.
Add future patch plan entries.
```

Forbidden now:

```text
Do not create author_voice/
Do not create author_voice.sqlite
Do not create Ollama runner
Do not create voice analyzer service
Do not integrate voice with prompt_builder.py
Do not modify project_runner.py
Do not unlock generation
Do not run provider calls
Do not run validation/export
```

---

## 3. Core Architectural Principle

The voice subsystem must not be treated as a simple prompt setting.

Correct model:

```text
Voice as project-local learned literary memory.
```

The subsystem should learn from accepted author artifacts and produce structured, approved voice guidance that later systems may consume.

Incorrect model:

```text
A single "style prompt"
A free-form AI-generated voice description
A global style setting shared across all projects by default
A hidden background process that mutates prompts or rewrites scenes
```

The voice system must be explicit, inspectable, author-approved, and project-local by default.

---

## 4. Voice Layer Hierarchy

Italus must distinguish multiple voice layers.

### 4.1 Global Author Voice

Definition:

```text
The long-term literary fingerprint of the real author.
```

It includes persistent tendencies across projects:

- diction
- sentence rhythm
- tone
- imagery
- metaphor style
- pacing
- dialogue tendencies
- narrative distance
- preferred sensory detail
- rhetorical habits
- emotional register
- compression / expansiveness
- degree of ornamentation
- use of irony, humor, melancholy, solemnity, lyricism, directness

Implementation rule:

```text
Global Author Voice can be reused across projects only by explicit author approval.
```

It must not automatically leak one project’s voice into another.

### 4.2 Project / Series Voice

Definition:

```text
The stylistic identity of a specific book, series, or narrative universe.
```

It can differ from the author’s global voice.

Examples:

- one series may be lyrical and mythic
- another may be clipped and noir
- another may be formal historical epic
- another may be intimate first-person confession

Project voice should include:

- genre-specific diction
- target prose density
- historical or cultural register
- formality level
- recurring motifs
- preferred pacing
- narration style
- world-specific idioms
- acceptable modernity level
- permitted anachronism rules
- series-specific tonal boundaries

Implementation rule:

```text
Project Voice belongs to data/projects/<project_id>/author_voice/ by default.
```

### 4.3 Narrative Voice

Definition:

```text
The voice of the narrator or narrating entity for a specific work.
```

It is not the same as Author Voice.

A narrator may be:

- omniscient
- limited third-person
- first-person character narrator
- unreliable
- formal
- intimate
- oral-tradition inspired
- scholarly
- satirical
- poetic
- emotionally restrained
- prophetic
- cynical
- childlike
- fragmented

Narrative Voice should track:

- point of view
- narrative distance
- narrator reliability
- narrator attitude toward events
- typical syntax
- preferred exposition style
- sensory emphasis
- interiority level
- judgment level
- degree of commentary
- narrator bias

Implementation rule:

```text
Prompt builder may eventually consume Narrative Voice only after prompt routing through ProjectContext is stable.
```

### 4.4 Character Voice

Definition:

```text
How an individual character speaks, thinks, perceives, reacts, and frames the world.
```

Character Voice must be separated from both Author Voice and Narrative Voice.

It should track:

- vocabulary
- education/formality level
- dialect markers
- idioms
- emotional temperature
- sentence length
- hesitation patterns
- favorite metaphors
- worldview
- moral assumptions
- speech rhythm
- humor style
- directness vs evasiveness
- aggression/passivity
- silence patterns
- contradiction patterns
- sensory anchors
- culturally specific phrasing
- what the character notices first
- what the character avoids saying

Implementation rule:

```text
A character’s dialect or speech pattern must not be absorbed into the global Author Voice profile.
```

### 4.5 Genre Voice

Definition:

```text
The stylistic expectations and constraints associated with the project’s genre or template.
```

Examples:

- historical epic
- literary fiction
- fantasy saga
- thriller
- romance
- mystery
- memoir
- satire
- oral-history style
- gothic
- noir
- mythic / biblical cadence

Genre Voice should track:

- acceptable diction range
- pacing norms
- scene structure expectations
- expected imagery density
- tone boundaries
- exposition style
- action vs introspection balance
- dialogue conventions
- emotional amplitude
- level of stylization

Implementation rule:

```text
Genre Voice should constrain output without overriding Author, Project, Narrative, or Character Voice.
```

### 4.6 Scene-Level Voice

Definition:

```text
The temporary tonal and stylistic requirement for a specific scene.
```

A scene may require:

- clipped urgency
- lyrical grief
- ceremonial formality
- comic relief
- quiet dread
- mythic elevation
- intimate confession
- battlefield compression
- political tension
- investigative clarity
- dreamlike ambiguity

Scene-Level Voice should track:

- desired mood
- prose intensity
- sentence rhythm
- emotional pressure
- imagery palette
- dialogue density
- interiority level
- pacing
- restraint vs release
- transition style

Implementation rule:

```text
Scene-Level Voice is temporary and must not permanently overwrite higher-level profiles unless the author explicitly accepts it as a learned pattern.
```

---

## 5. Voice Source Rule

The voice system must learn only from approved artifacts.

Approved sources:

```text
accepted final books
accepted final chapters
accepted final scenes
author-edited passages
approved events
approved character dialogue
approved revisions
final exported manuscript sections
manual author voice samples
```

Unapproved sources:

```text
raw AI drafts
rejected generations
temporary suggestions
provider responses that were not accepted
unreviewed validation outputs
```

Core rule:

```text
Only author-approved text updates voice memory.
```

AI-generated drafts are candidate material, not voice evidence, unless explicitly accepted.

---

## 6. Proposed Project-Local Directory Structure

Future root:

```text
data/projects/<project_id>/author_voice/
```

Recommended future structure:

```text
data/projects/<project_id>/author_voice/
├── author_voice.sqlite
├── samples/
├── exports/
├── profiles/
└── analysis_cache/
```

Preferred source of truth:

```text
author_voice.sqlite
```

Loose files should be secondary/export/cache only, not the canonical state.

Rationale:

SQLite is preferred for:

- structured observations
- sample metadata
- profile versioning
- revision history
- author decisions
- queryable evolution over time
- local project portability
- stable service boundary

---

## 7. Proposed SQLite Data Model

The exact schema should be designed later, but the architecture should preserve these entity types.

### 7.1 voice_samples

Purpose:

```text
Store text samples approved for analysis.
```

Fields to consider:

- id
- project_id
- source_type
- source_id
- source_path
- text_hash
- text_excerpt
- full_text_location
- approval_status
- approved_by_author
- accepted_at
- created_at
- updated_at
- voice_layer_target
- character_id if applicable
- narrative_id if applicable
- scene_id if applicable
- chapter_id if applicable
- book_id if applicable

Source types:

```text
manual_sample
accepted_scene
accepted_chapter
accepted_book
author_revision
approved_character_dialogue
approved_event
final_export_section
```

### 7.2 voice_observations

Purpose:

```text
Store structured analysis extracted from a sample.
```

Fields to consider:

- id
- sample_id
- analyzer
- analyzer_model
- analysis_version
- diction_summary
- syntax_summary
- tone_summary
- imagery_summary
- pacing_summary
- dialogue_summary
- metaphor_summary
- rhythm_summary
- narrative_distance_summary
- sensory_pattern_summary
- confidence_score
- created_at

Observation categories:

```text
diction
syntax
tone
imagery
rhythm
pacing
dialogue
metaphor
narrative_distance
character_speech
genre_register
scene_tone
```

### 7.3 author_voice_profiles

Purpose:

```text
Store accumulated global author voice traits.
```

Fields to consider:

- id
- profile_name
- status
- version
- approved_for_reuse
- diction_profile
- syntax_profile
- tone_profile
- imagery_profile
- pacing_profile
- metaphor_profile
- dialogue_profile
- narrative_distance_profile
- prohibited_patterns
- preferred_patterns
- created_at
- updated_at

### 7.4 project_voice_profiles

Purpose:

```text
Store project-specific or series-specific stylistic identity.
```

Fields to consider:

- id
- project_id
- series_id
- profile_name
- genre
- template
- status
- version
- diction_constraints
- historical_register
- tone_boundaries
- imagery_palette
- pacing_rules
- point_of_view_policy
- prose_density
- created_at
- updated_at

### 7.5 narrative_voice_profiles

Purpose:

```text
Store narrator-specific voice model.
```

Fields to consider:

- id
- project_id
- narrative_id
- narrator_type
- point_of_view
- reliability
- narrative_distance
- exposition_style
- interiority_level
- attitude
- bias
- commentary_level
- syntax_pattern
- tone_pattern
- created_at
- updated_at

### 7.6 character_voice_profiles

Purpose:

```text
Store character-specific speech and perception patterns.
```

Fields to consider:

- id
- project_id
- character_id
- character_name
- status
- version
- vocabulary_profile
- syntax_profile
- dialect_markers
- idioms
- emotional_register
- worldview
- speech_rhythm
- silence_patterns
- conflict_speech_patterns
- humor_style
- education_register
- forbidden_phrases
- created_at
- updated_at

### 7.7 genre_voice_profiles

Purpose:

```text
Store genre and template voice constraints.
```

Fields to consider:

- id
- project_id
- genre
- template
- diction_range
- pacing_expectations
- imagery_expectations
- exposition_expectations
- dialogue_expectations
- tonal_boundaries
- stylization_level
- created_at
- updated_at

### 7.8 scene_voice_profiles

Purpose:

```text
Store temporary scene-level tone and style constraints.
```

Fields to consider:

- id
- project_id
- scene_id
- chapter_id
- desired_mood
- pacing_directive
- sentence_rhythm
- emotional_pressure
- imagery_palette
- dialogue_density
- interiority_level
- tonal_constraints
- status
- created_at
- updated_at

### 7.9 voice_decisions

Purpose:

```text
Record explicit author approvals/rejections related to voice learning.
```

Fields to consider:

- id
- project_id
- target_type
- target_id
- decision
- decision_reason
- author_note
- created_at

Decision values:

```text
accept_as_author_voice
accept_as_project_voice
accept_as_narrative_voice
accept_as_character_voice
accept_as_scene_voice
reject_from_voice_learning
needs_revision
archive
```

### 7.10 voice_prompt_constraints

Purpose:

```text
Store approved prompt-ready constraints derived from profiles.
```

Fields to consider:

- id
- project_id
- profile_type
- profile_id
- constraint_text
- structured_constraint_json
- status
- approved_by_author
- created_at
- updated_at

Core rule:

```text
Prompt builder consumes voice_prompt_constraints, not raw observations.
```

### 7.11 voice_revision_history

Purpose:

```text
Track profile changes over time.
```

Fields to consider:

- id
- profile_type
- profile_id
- old_version
- new_version
- change_summary
- changed_by
- changed_at

---

## 8. Ollama / Local LLM Role

Ollama is recommended for local voice analysis.

Initial role:

```text
Analyze accepted writing samples locally.
Extract structured traits.
Compare candidate prose against approved profiles.
Suggest voice alignment feedback.
```

Ollama should not initially:

```text
rewrite scenes automatically
modify canon
update runtime scenes
call external providers
unlock generation
persist profile changes without author decision
```

Local model output must be treated as analysis, not authority.

Recommended future adapter:

```text
app/services/local_llm_service.py
```

or:

```text
app/ollama_runner.py
```

Recommended future voice analyzer:

```text
app/services/author_voice_service.py
```

Possible analysis flow:

```text
accepted text sample
→ author_voice_service queues analysis
→ local_llm_service calls Ollama
→ structured observation returned
→ observation stored in SQLite
→ author reviews or system proposes profile update
→ approved voice_prompt_constraints created
```

---

## 9. Voice-To-Prompt Integration

The voice system should not inject raw analysis directly into prompts.

Correct future flow:

```text
SQLite voice profiles
→ approved voice_prompt_constraints
→ prompt_builder reads constraints through ProjectContext
→ generation request includes voice constraints
→ provider/local model returns candidate prose
→ output saved project-locally
→ validation checks voice consistency
```

Prompt builder should eventually consume:

- project voice constraints
- narrative voice constraints
- character voice constraints
- scene voice constraints
- genre constraints
- optional global author voice constraints if explicitly approved

Prompt builder must not consume:

- unapproved observations
- raw local LLM analysis
- rejected samples
- character voice as global author voice
- other project voice profiles unless explicitly promoted/reused

---

## 10. Voice Validation

Voice validation should eventually answer:

```text
Does this generated scene match project voice?
Does the narrator sound consistent?
Does each character speak like themselves?
Did prose drift into generic AI language?
Did tone match the scene requirement?
Did genre diction remain consistent?
Did the author’s long-term style remain visible where intended?
```

Validation must run against persisted project-local output, not transient provider response.

Correct future sequence:

```text
provider/local generation response
→ save generated scene to project-local runtime
→ load saved scene
→ validate canon/continuity/voice
→ write validation result
```

Invalid sequence:

```text
provider response
→ validate raw text
→ save fails
```

That creates validation records for text that does not exist.

---

## 11. Relationship To Existing Italus Runtime Files

The voice subsystem will eventually influence or interact with these protected files, but it must not modify them now.

Protected files:

```text
app/project_runner.py
app/prompt_builder.py
app/registry.py
app/ai_runner.py
app/claude_runner.py
app/openai_runner.py
app/novelcraft_runner.py
app/coverage.py
app/post_generation_canon_validator.py
```

Future interaction model:

```text
author_voice_service
→ produces approved voice constraints
→ prompt_builder consumes constraints
→ project_runner orchestrates generation
→ provider runner returns candidate prose
→ runtime storage persists result
→ validation checks output against canon and voice
```

Do not put voice analysis directly inside:

```text
project_runner.py
prompt_builder.py
registry.py
provider runner files
```

Use service boundaries.

---

## 12. Voice Subsystem Constraints

Hard constraints:

```text
1. Project-local by default.
2. Cross-project author voice reuse requires explicit author approval.
3. Only author-approved text updates voice profiles.
4. AI drafts are candidate material, not voice evidence.
5. Ollama analyzes; it does not silently rewrite.
6. SQLite stores structured observations, decisions, and profiles.
7. Prompt builder consumes approved voice constraints only.
8. Voice validation checks persisted project-local output.
9. Author, project, narrative, character, genre, and scene voice remain separate layers.
10. No provider or generation unlock occurs because voice exists.
11. Voice subsystem must not modify canon directly.
12. Voice subsystem must not mutate runtime scenes directly.
13. Voice subsystem must not write exports.
14. Voice subsystem must not bypass validation gates.
```

---

## 13. Future API And Service Boundaries

Potential future services:

```text
app/services/author_voice_service.py
app/services/local_llm_service.py
app/services/voice_profile_service.py
app/services/voice_validation_service.py
```

Potential future API routes:

```text
GET  /api/projects/{project_id}/author-voice/status
POST /api/projects/{project_id}/author-voice/samples
POST /api/projects/{project_id}/author-voice/analyze
GET  /api/projects/{project_id}/author-voice/profiles
POST /api/projects/{project_id}/author-voice/decisions
GET  /api/projects/{project_id}/author-voice/prompt-constraints
```

These route shapes are future planning notes only. They must be confirmed against actual `app/api/routes/project.py` patterns before implementation.

---

## 14. Future UI / Author Workflow

Future user navigation areas:

```text
Workspace → Voice
Workspace → Characters → Character Voice
Workspace → Runtime / Writing Memory → Voice influence status
Workspace → Validation → Voice consistency checks
```

Future author workflow:

```text
1. Author opens project.
2. Author adds writing samples or accepts final scenes/chapters/books.
3. Italus marks accepted text as eligible for voice learning.
4. Ollama analyzes locally.
5. Italus displays observations:
   - diction
   - syntax
   - tone
   - imagery
   - pacing
   - character speech
6. Author approves, rejects, or edits profile updates.
7. Approved profile updates become voice constraints.
8. Prompt builder uses approved constraints in future generation.
9. Validation checks generated output against the correct voice layer.
```

Important UX distinction:

```text
Author Voice = long-term literary fingerprint
Project Voice = this project/series identity
Narrative Voice = narrator style
Character Voice = individual character speech/thought
Genre Voice = conventions and constraints
Scene Voice = temporary local tone
```

---

## 15. Future Patch Plan For Voice Subsystem

This patch plan is future-facing. It must not interrupt Stage 9 runtime storage.

### Patch V1 — Author Voice Architecture Docs

Purpose:

```text
Add detailed voice subsystem architecture and future sequencing to migration docs.
```

Scope:

```text
docs/migration/ITALUS_AUTHOR_VOICE_ARCHITECTURE_NOTES.md
docs/migration/ITALUS_MIGRATION_PATCH_PLAN.md
docs/migration/ITALUS_PATCH_HISTORY.md
docs/migration/ITALUS_STAGE_ACCEPTANCE_CRITERIA.md
```

Behavior:

```text
Docs only. No runtime changes.
```

### Patch V2 — Author Voice Project Directory Contract

Purpose:

```text
Define project-local author_voice directory contract.
```

Scope:

```text
docs/migration/*.md
possibly frontend read-only preview later
```

No SQLite creation yet unless approved.

### Patch V3 — SQLite Store Skeleton

Purpose:

```text
Create project-local SQLite schema and storage service boundary.
```

Possible files:

```text
app/services/author_voice_service.py
app/services/voice_profile_service.py
docs/migration/*.md
```

Rules:

```text
No prompt integration.
No generation influence.
No Ollama calls yet.
```

### Patch V4 — Ollama Local Analysis Adapter

Purpose:

```text
Add local LLM analysis service for accepted samples.
```

Possible files:

```text
app/services/local_llm_service.py
app/services/author_voice_service.py
```

Rules:

```text
Analyze only.
Do not rewrite.
Do not update profiles without approval.
```

### Patch V5 — Voice Sample Intake

Purpose:

```text
Allow author-approved samples to be registered for voice learning.
```

Sources:

```text
manual samples
accepted scenes
accepted chapters
accepted books
author revisions
character dialogue
```

### Patch V6 — Voice Profile Review UI

Purpose:

```text
Show observations and allow author approval/rejection.
```

Possible frontend areas:

```text
Voice panel
Character detail voice tab
Project voice dashboard
```

### Patch V7 — Approved Voice Prompt Constraints

Purpose:

```text
Create controlled prompt-ready constraints from approved profiles.
```

Rules:

```text
Prompt constraints are derived from approved profiles only.
Raw observations do not enter prompts.
```

### Patch V8 — Prompt Builder Voice Integration

Purpose:

```text
Prompt builder consumes approved voice constraints through ProjectContext.
```

Depends on:

```text
runtime storage stable
prompt routing through ProjectContext stable
voice profile store stable
```

### Patch V9 — Voice Validation

Purpose:

```text
Validate generated project-local output against approved voice profiles.
```

Depends on:

```text
project-local runtime output exists
validation runtime integration exists
```

### Patch V10 — Cross-Project Author Voice Promotion

Purpose:

```text
Allow selected project voice learnings to be promoted to reusable Author Voice.
```

Rule:

```text
Explicit author approval required.
```

---

## 16. Placement In Main Italus Migration Plan

Current main forward plan should include Author Voice after storage and prompt routing.

Recommended sequence:

```text
1. Workspace Navigation Architecture Guide
2. Stage 9 Runtime Storage Architecture Docs
3. Project Runtime Storage Service Skeleton
4. Runtime Storage Initialization
5. Runtime Storage UI Status Update
6. Runtime Adapter Boundary Design
7. Generation Service Boundary
8. Prompt Builder Routing through ProjectContext
9. Author Voice Architecture Review
10. Author Voice SQLite Store
11. Ollama Local Voice Analyzer
12. Author / Narrative / Character Voice Profile UI
13. Voice-to-Prompt Integration
14. Provider Execution Contract
15. Validation Integration
16. Export Pipeline
17. Generation Unlock Gate
```

Key sequencing rule:

```text
Author Voice should be designed before generation unlock,
but implemented after runtime storage and prompt routing are stable.
```

---

## 17. Risks And Mitigations

### Risk: Voice becomes a vague prompt string

Mitigation:

```text
Store structured observations, profiles, decisions, and approved prompt constraints separately.
```

### Risk: Raw AI drafts contaminate author voice

Mitigation:

```text
Only author-approved text updates voice profiles.
```

### Risk: Character dialect contaminates Author Voice

Mitigation:

```text
Separate character_voice_profiles from author_voice_profiles.
```

### Risk: Project voice leaks into another project

Mitigation:

```text
Project-local by default; cross-project reuse requires explicit approval.
```

### Risk: Ollama silently rewrites author text

Mitigation:

```text
Ollama analysis-only until a later explicitly approved editing/rewrite stage.
```

### Risk: Voice validation checks unsaved output

Mitigation:

```text
Validation runs against persisted project-local output only.
```

### Risk: Prompt builder uses unapproved observations

Mitigation:

```text
Prompt builder consumes approved voice_prompt_constraints only.
```

### Risk: SQLite rollback deletes author work

Mitigation:

```text
Stateful rollback must distinguish patch-created empty DB from user-populated DB.
Never delete populated voice database without explicit operator confirmation.
```

---

## 18. Stateful Rollback Rules For Future Voice SQLite Patches

Voice subsystem will create persistent state. Rollback must be stricter than frontend/docs rollback.

If SQLite database did not exist before deploy:

```text
Rollback may remove it only if:
- the patch created it
- no user samples or decisions were added after deploy
- verify failed before user work began
```

If SQLite database existed before deploy:

```text
Rollback must restore backup copy.
Rollback must not delete author voice data.
```

Deploy scripts must record:

```text
author_voice directory existed before patch: true/false
author_voice.sqlite existed before patch: true/false
files created by patch
backup path
```

Verification must check:

```text
schema exists
no prompt integration occurred
no generation flags changed
no provider calls enabled
no voice profiles created from unapproved text
```

---

## 19. Required Future Documentation

When this subsystem is introduced, create:

```text
docs/migration/ITALUS_AUTHOR_VOICE_ARCHITECTURE_NOTES.md
```

It should include:

```text
voice layer definitions
SQLite entity model
Ollama role
approval rules
prompt integration rules
validation rules
stateful rollback
future patch sequence
protected files
project-local ownership rules
```

Optional later user-facing guide:

```text
docs/migration/ITALUS_AUTHOR_VOICE_USER_FLOW.md
```

---

## 20. Final State Decision

```text
Author Voice / Narrative Voice / Character Voice / Project-Series Voice / Genre Voice / Scene-Level Voice is a future subsystem.
It is architecturally approved.
It is locked out of immediate Stage 9 runtime storage implementation.
It must be project-local, approval-based, SQLite-backed, and locally analyzed through Ollama.
It must preserve separate voice layers.
It must feed prompt building only through approved constraints.
It must support later validation against persisted project-local output.
```

This subsystem is a strategic authorship layer, not a styling shortcut.

---

## 21. Next Recommended Main-Project Step

NEXT RECOMMENDED STEP:
Skill 5 — Code Builder

Reason:
Build a docs-only patch that preserves this Author Voice subsystem architecture and links it into the future patch plan without implementing it during Stage 9 runtime storage.
