# V2 Architecture

## Product boundary

Premiere Pro is the user-facing host. The UXP panel selects a Final Package and narration audio and submits a job to the local StoryEngine API. The engine owns all media/AI work. Premiere receives only job status and the final output path, then imports the result into the active project/timeline.

## Stage ownership

- `input`: Final Package validation/materialization.
- `transcription`: narration timing.
- `vision`: semantic object/group discovery.
- `cutout`: individual visual extraction/matting.
- `story`: visual beat order and attention handoff.
- `composition`: size/position/frame occupancy.
- `motion`: reveal/handoff timing and motion grammar.
- `render`: deterministic layer compositing.
- `final`: audio/video mux and final media production.
- `recovery`: known issue registry, handlers, post-fix validation history.

Downstream stages must not silently rewrite upstream intent. A renderer defect is repaired in render; a bad handoff is repaired in story; a bad matte is repaired in cutout.

## Recovery rule

A recovery handler being called is not proof that a defect is solved. The owning stage is rebuilt, the same QA detector runs again, and only the post-QA result is stored in recovery history. Known issues persist outside individual project workspaces so validated handling is reusable across different Final Packages.

## Rendering rule

The V2 renderer composes extracted assets as independent layers. The source scene image is not treated as a protected poster. Story determines what enters and when; composition determines where; motion determines how; renderer executes those decisions.

## Legacy reference policy

The old `Montagetools` repository remains read/reference provenance. Proven runtime/model loading, FFmpeg, tests and Premiere ideas may be migrated selectively. Legacy V31 planner/finalizer chains are not copied wholesale.
