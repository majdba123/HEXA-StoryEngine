# V2 Architecture

## Product boundary

Premiere Pro is the user-facing host. The UXP panel selects a Final Package and narration audio and submits a job to the local StoryEngine API. The engine owns all media/AI work. Premiere receives only job status and the final output path, then imports the result into the active project/timeline.

## Stage ownership

- `input`: Final Package validation/materialization.
- `transcription`: narration timing.
- `vision`: semantic object/group discovery.
- `cutout`: individual visual extraction/matting.
- `story`: visual beat order, semantic entities/relationships, narrative role and attention handoff.
- `choreography`: visual state changes, inter-layer interactions, sequence grammar, hooks and continuity intent.
- `composition`: size/position/frame occupancy and semantic layout states.
- `motion`: trajectories and pacing between Composition-authored states.
- `text`: narration-locked semantic reinforcement synchronized with Story/Choreography without surrendering wording/timing authority.
- `render`: deterministic layer compositing.
- `final`: audio/video mux and final media production.
- `recovery`: known issue registry, handlers, post-fix validation history.

Downstream stages must not silently rewrite upstream intent. A renderer defect is repaired in render; a bad handoff is repaired in story/choreography; a bad matte is repaired in cutout.

## Final Package semantic authority rule

The Final Package is the primary visual-semantic authority. Semantically relevant package information must not be read and then discarded. Story preserves entities, relationships, roles, progression, unit/event triggers, purpose, visual concept and scene continuity as explicit evidence; Choreography converts that evidence into state changes/interactions; Composition uses it to establish visual hierarchy; Motion executes meaning-bearing trajectories; Text inherits the same semantic context while remaining narration/forced-alignment locked; QA verifies that the evidence survived the authoring pipeline.

Sparse or older Final Packages remain supported through conservative fallbacks. Fallbacks may reduce semantic richness, but they must never invent physical causality that is absent from the package.

## Choreography / motion rule

A visual movement must have a storytelling job. Decorative shake/jitter/wiggle/idle-bounce is not accepted as a substitute for an event. Neutral layers settle and hold. Follow-through is reserved for explicit meaning-bearing actions such as transfer, block, reject, connect, compare, reveal, result, reaction or resolution.

Reference-inspired sequence grammar is progressive construction rather than poster animation:

`ENTER -> READ -> ADD -> RELATE -> RESULT -> RELEASE`

Not every beat owns every stage, but a rich sequence must progress through the grammar as a whole and must include a semantic relationship/state change before it is considered ready for render review.

## Cutout refinement rule

Current Pass1/Pass2 extraction remains protected. Choreography emits explicit asset requirements. A future third refinement pass is allowed only when a required semantic participant is genuinely missing or non-independent; it must be targeted to that requirement rather than re-segmenting every scene.

## Recovery rule

A recovery handler being called is not proof that a defect is solved. The owning stage is rebuilt, the same QA detector runs again, and only the post-QA result is stored in recovery history. Known issues persist outside individual project workspaces so validated handling is reusable across different Final Packages.

## Rendering rule

The V2 renderer composes extracted assets as independent layers. The source scene image is not treated as a protected poster. Story determines what the narration means; Choreography determines what should happen; Composition determines where semantic states rest; Motion determines how elements travel between them; Renderer executes those decisions.

## Legacy reference policy

The old `Montagetools` repository remains read/reference provenance. Proven runtime/model loading, FFmpeg, tests and Premiere ideas may be migrated selectively. Legacy V31 planner/finalizer chains are not copied wholesale.
