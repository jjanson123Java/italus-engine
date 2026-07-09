# Italus Generation Control Lifecycle Contract

**Status:** Architecture contract  
**Scope:** Documentation only. No runtime behavior.  
**Patch:** `italus_generation_control_lifecycle_contract_patch_v5`  
**Purpose:** Add the Generation Control Layer before prompt routing, provider execution, draft validation, author decision UI, or approved runtime persistence are wired.

## 1. Architecture Decision

Italus requires a Generation Control Layer between canon approval and generation execution.

The layer converts approved canon and system control rules into project-local provider context, normalizes provider/backend issues into structured author decisions, validates candidate drafts, and prevents unapproved provider output from entering runtime memory.

## 2. Canon And Control Hierarchy

```text
Primary author canon
-> source of truth

System control templates
-> developer-authored safety rules and genre controls

Project-local knowledge/control packs
-> derived artifacts generated from approved canon and approved runtime state

Provider output
-> candidate only

Backend validation
-> authoritative validation before author approval

Runtime adapter
-> approved text persistence only
```

Primary canon remains the source of truth. Project-local packs are compiled working context and must not become independent canon.

## 3. Project-Local Control Pack Model

After canon approval, a future control-pack service may generate project-local artifacts such as:

```text
data/projects/<project_id>/canon/project_knowledge_pack.md
data/projects/<project_id>/canon/project_control_pack.md
data/projects/<project_id>/canon/book_<book_id>_knowledge_pack.md
data/projects/<project_id>/canon/book_<book_id>_control_pack.md
```

Generated packs must be:

- derived from approved canon
- versioned against source canon
- invalidated when source canon changes
- refreshed only from approved runtime state
- excluded from primary author-editable canon

Unapproved provider drafts must never refresh knowledge packs or control packs.

## 4. Generation Intent Model

The system must support multiple generation intents:

```text
single_scene
single_chapter_single_unit
chapter_ordered_composition
chapter_multi_pov
chapter_multi_thread
continue_existing
replace_existing
regenerate_existing
```

The architecture must not assume one request always equals one event, one scene, and one draft.

## 5. Ordered Chapter Composition

A chapter may contain one unit or multiple ordered units.

A composition unit may represent:

```text
historical event angle
scene type
character POV
plot thread
location
timeline window
emotional beat
investigation clue
battle phase
romance beat
political maneuver
```

The author-defined unit order is binding generation intent. The provider must not silently reorder units.

## 6. Chapter Narrative Spine

Multi-unit chapters must include a chapter narrative spine.

The spine defines:

```text
chapter goal
chapter conflict
through-line
emotional or informational arc
transition intent
ending state
```

The provider must generate one coherent chapter, not disconnected short stories stitched together.

## 7. Prompt Builder Boundary

Future prompt builder routing must support:

```text
scene_generation_prompt
chapter_single_unit_prompt
chapter_composition_prompt
```

Prompt builder builds provider prompts only. It must not validate drafts, persist text, decide approval, or write runtime JSON.

## 8. Provider Output Types

Provider runners may return:

```text
candidate_draft
author_decision_required
provider_warning
blocked_generation
```

Provider output is advisory until normalized and validated by backend services.

## 9. Generation Control Normalization

A future normalization boundary must convert provider/backend issues into structured application objects.

Example states:

```text
chapter_structure_needed
scene_direction_needed
possible_scene_duplicate
draft_ready_for_review
draft_validation_warning
draft_blocked
requires_revision
```

The frontend must consume structured backend state, not parse raw LLM prose for control flow.

## 10. Author Decision Sidebar Model

The workspace generation sidebar must render one active state at a time.

Author-facing states include:

```text
Chapter Structure Needed
Scene Direction Needed
Possible Scene Duplicate
Draft Ready For Review
Draft Validation Warning
Draft Blocked
```

### Chapter Structure Needed

Used when the author is planning a single-unit or multi-unit chapter.

The author may select units, order units, define or edit the chapter narrative spine, and generate from that structure.

### Scene Direction Needed

Used when related scene material exists but the request may be a valid new angle, continuation, or replacement.

Use neutral language. Do not label intentional same-event coverage as a duplicate.

### Possible Scene Duplicate

Used only when the request closely matches an existing scene.

Options may include continue existing scene, write a different angle, replace existing scene, or cancel.

### Draft Ready For Review

Used when a draft exists and backend validation finds no blocking or warning issues.

Options may include accept draft, edit draft, regenerate, or cancel.

### Draft Validation Warning

Used when a draft exists and backend validation finds warning-level issues.

Options may include edit draft, regenerate with correction, accept if allowed, or cancel.

### Draft Blocked

Used when a draft contains hard canon/control violations.

Blocked drafts cannot be persisted.

## 11. Backend Validation Boundary

Backend validation must run after every provider draft.

Validation categories include:

```text
timeline drift
duplicate content
canon conflict
continuity violation
historical mismatch
character/location/date error
scene structure violation
chapter pacing issue
chapter cohesion issue
```

Backend validation is authoritative. Provider compliance is advisory.

## 12. Chapter Cohesion Validation

For multi-unit chapters, validation must check:

```text
selected units are present
selected units follow author-defined order
transitions are coherent
units advance the chapter narrative spine
tone and motivation do not reset between units
timeline remains plausible
canon and control rules remain intact
ending state follows from prior units
```

## 13. Runtime Persistence Boundary

The runtime registry adapter persists only approved text.

Raw provider drafts, provider warnings, blocked drafts, decision prompts, and unapproved candidate text must not update:

```text
books.json
chapters.json
scenes.json
coverage_map.json
book_state.json
chapter_continuity_digests.json
future knowledge packs
future control packs
```

Temporary candidate state may later be held in session-level state until approval.

## 14. Existing Patch Plan Reconciliation

This architecture does not replace existing remaining implementation work. It inserts a prerequisite control layer before that work proceeds.

Existing work still required later:

```text
project-local control pack generation
generation result normalization
draft validation and continuity services
author decision sidebar
prompt builder project-control routing
provider candidate draft contract
author approval workflow
runtime adapter persistence wiring
knowledge pack refresh
validation/export pipeline
```

Generation remains locked until the appropriate future implementation stage explicitly unlocks it.

## 15. Hard Boundaries

This contract does not modify runtime behavior.

Do not touch in this patch:

```text
app/project_runner.py
app/prompt_builder.py
app/registry.py
app/coverage.py
app/post_generation_canon_validator.py
app/ai_runner.py
app/claude_runner.py
app/openai_runner.py
app/novelcraft_runner.py
frontend/workspace.js
frontend/workspace.css
runtime JSON files
```

## 16. Acceptance Criteria

This contract is accepted when:

```text
Generation Control Lifecycle contract exists.
Migration roadmap references the control layer.
Generation remains locked.
Provider execution remains locked.
Prompt builder remains untouched.
Runtime adapter remains inert from generation.
Runtime JSON content is unchanged.
Sidebar model distinguishes chapter planning, scene direction, duplicate risk, clean draft review, warnings, and blockers.
Ordered chapter composition and chapter narrative spine are documented.
Approved-text-only persistence remains explicit.
```


## 17. Patch Artifact Discipline

This patch follows the Italus patch delivery convention:

```text
tools/
  deploy_italus_generation_control_lifecycle_contract_patch_v5.ps1
  verify_italus_generation_control_lifecycle_contract_patch_v5.ps1
  docs_italus_generation_control_lifecycle_contract_patch_v5.ps1
  rollback_italus_generation_control_lifecycle_contract_patch_v5.ps1

downloads/
  italus_generation_control_lifecycle_contract_patch_v5.zip
```

Deployment applies the contract document first. Documentation finalization runs only after deploy and verification are approved.


## 14. Patch Discipline For This Lifecycle

This contract follows the Italus migration patch process:

```text
Patch zip
Deploy script
Verify script
Docs script
Rollback script
All artifacts bundle
```

Deployment installs this lifecycle contract only. Verification confirms the lifecycle contract is present and no runtime execution files are modified by the patch payload. Documentation finalization is performed only after deploy and verify output are approved.

The docs script records:

```text
completed patch
verified status
approved next phases
locked implementation boundaries
```

