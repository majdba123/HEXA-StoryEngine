# Visual Continuity V2 feature candidate

Branch: `feature/visual-continuity-v2`, based on `origin/montage` at
`55d58daff6b127c819e1959687d4fc0b1656685a`. Enable the experiment with
`HEXA_VISUAL_CONTINUITY_V2=1`; the default is off.

## First bad owner

`CrossSceneContinuityPlanner` formerly considered only a shared authored
`referent_id`. `VisualTransitionPolicy` separately resolved `PERSIST` and
`TRANSFORM_TO`, but the Motion planner rejected `OBJECT_HANDOFF` boundaries, so
that relationship never became a frame accurate opaque carrier swap. Without
identity, equal layout or a shared label was deliberately insufficient.
Boundary's idea board and scene fade could then exit the old artwork and Landing
could replay an ENTRY even if Motion had made a handoff cue. The renderer already
has the required frame grid and `handoff_from` carrier execution; it has no
reason to infer identity.

## Feature path

Motion considers evidence in this order: authored referent, explicit authored
`PERSIST`/`TRANSFORM_TO`, then a unique visual slot. Visual slots require an
adjacent `CONTINUES_NARRATIVE` scene, non-character semantic role agreement,
near-identical authored locators, visible graphic content, and a unique
48-by-48-pixel bounded artwork comparison. They assert only presentation
continuity. Ambiguous matches and unsafe layout/timing abstain. The same
one-to-one runtime carrier is passed to the existing renderer. This is decided
once per boundary and cached during planning; no image analysis runs per frame.

For in-place artwork, Motion replaces the incoming ENTRY with a still, opaque
program at the original Story reveal, and `ReferenceLandingPolicy` respects
that V2 instruction. The renderer holds the outgoing source through frame N-1
and enables the incoming art on N. Composition owns the final pose; other
semantic motion segments remain in place. Position/scale handoff and abstention
reuse the existing planner and renderer. A visual slot never sets a referent id.

The first full web render exposed a segmentless reference-arrival cue: its
`params.program` still ran a slide/pop after the handoff despite the accepted
decision. V2 now replaces that base program as well as any ENTRY segment and
removes stale reference-arrival metadata. The correction applies only to
accepted V2 handoffs.

The Text/Boundary transaction still requires identical Text. A Boundary
replan is allowed to differ only when its basic mode, timing, text carry, and
reason remain identical and the baseline release explicitly names the
handoff source. The baseline Boundary plan remains in force; Render already
excludes handed-off sources from its outgoing exit layers, so unrelated exits
keep their original plan. Mode or Text changes revoke the handoff.

## Tehran source and exact boundary

Inputs found in Downloads:

- `HEXA_TEHRAN_FINAL.zip` (SHA-256
  `c7e06834e32b8d5cbacb0822d44d85852ed96bc2781be89b83562f532fde54d7`)
- `tehran_185f93c226a6f6.wav` (41.900680 seconds)
- `HEXA_TEHRAN_CAMERAS_AR_V1_YOUTUBE.mp4` (41.900688 seconds)

The reference export manifest records the same ZIP fingerprint and the
`origin/montage` engine SHA. The source narration says February **28**, not
February 23. `SCENE_012` shows the map and February 28 calendar;
`SCENE_013` adds 2026 in the same calendar. No `referent_id` or explicit
continuity mode is present for these graphics. The visual slot comparison
found one-to-one map, calendar, and arrow candidates, with normalized crop
differences of about 0.011, 0.072, and 0.008, respectively. Pass1/Pass2
produced single runtime carriers for map and calendar; the arrow did not
produce an independent qualifying carrier in the first real plan.

The first real plan exposed two additional rejects: the map's outgoing alpha
bounding box touched the incoming calendar by less than 1% of the smaller
footprint, and Boundary's expected handoff-aware replan caused the calendar
transaction to roll back. Those cases are now bounded as described above.
Real encoded A/B and final visual acceptance are recorded separately; this
document alone is not certification.

## Semantic reveal timing investigation

The original Tehran export at engine `55d58daf` records Story fingerprint
`c6c2e6cc...` and no transcription repair. The first V2 export from the same
ZIP and WAV records Story fingerprint `72ceadf0...` and
`ALIGNMENT_RUNTIME_FAILED`: the forced aligner could not allocate 274,597,888
bytes, so the pipeline used `speech_interval_recovered`. Decoded audio from the
two videos has zero measured lag, but their Story clocks differ. Consequently,
the original video's later map/calendar appearances cannot by themselves prove
that V2 advanced the semantic reveal. The V2 planner accepted only three
handoffs around `SCENE_011` through `SCENE_013`; it did not adapt the earlier
map's arrival or the first calendar arrival.

V2 now requires actual forced-aligned word timing. An alignment failure stops
before visual planning instead of producing a candidate with an uncertified
Story clock. For each accepted handoff, Motion compares the encoded handoff
frame with the Story activation's spoken and reveal authority, and Render
checks the effective successor frame again. The prior representation may
persist up to that frame; an earlier successor is rejected. The flag-off
pipeline retains its existing recovery behavior.

## Local web

`tools/start_local_visual_continuity_v2.ps1` checks the feature or merged montage branch and
binds only `127.0.0.1:8791`. Its SQLite, uploads, work, outputs, exports,
and model cache live under `E:\HEXA_Exports\_VISUAL_CONTINUITY_V2_LOCAL` by
default. The launcher reads `HEXA_ADMIN_EMAIL` and
`HEXA_ADMIN_BOOTSTRAP_PASSWORD` from this worktree's `.env`, or from the
adjacent `HEXA-StoryEngine-montage-consolidation/.env` when no feature `.env`
exists. `-EnvFile` selects another file explicitly. On each start it syncs
the sole active administrator in this isolated database to those values and
revokes that administrator's old sessions if either value changed. It does
not reset jobs or other accounts. Pass `-PythonPath` when this worktree has
no `.venv`. Upload protocol V2 is enabled.

Promotion to `montage` or `bayer` requires explicit user approval after
encoded comparison and full validation. This branch has no deployment path.
