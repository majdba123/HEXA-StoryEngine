# HEXA REVIEW — OFFICIAL CONTINUITY SOURCE

> This file is the authoritative handoff/state file for the **review** conversation chain.
> Current review worker at seed: **review 1**.
> Repository: `majdba123/HEXA-StoryEngine`
> Working branch at seed: `montage11-publish`
> Source HEAD inspected before this file was created: `6b918f01f0bf0d8d4f61f269f2caf607ea43c2d2`
> Seed date: 2026-09-19
>
> IMPORTANT: Never trust the HEAD above as current. Every review chat must verify the live branch/HEAD before work.

---

## 0. CONTROL BLOCK

- DOCUMENT_ROLE: official review-chain source of truth
- CURRENT_REVIEW_CHAT: review 1
- NEXT_REVIEW_CHAT: review 2
- STATE_VERSION: 1
- STATUS: active
- ACTIVE_FOCUS: Typography/Text System quality and placement; Smart Arrows are discussed but intentionally deferred until text is proven
- CURRENT_CODE_BRANCH_AT_SEED: montage11-publish
- CURRENT_CODE_HEAD_AT_SEED: 6b918f01f0bf0d8d4f61f269f2caf607ea43c2d2
- LAST_CONFIRMED_USER_DIRECTION: Increase typography density, do NOT reduce it; improve semantic selection quality; preserve current good motion; match chosen reference typography style; text placement must be extremely safe, strong, and smooth
- CODE_CHANGES_BY_REVIEW_1: none
- DOC_CHANGES_BY_REVIEW_1: created this continuity source
- NEXT_PRIMARY_STEP: inspect/modify Text System according to Section 9 only after live code sync and requirements receipt

### Mandatory synchronization protocol

Every future review chat must treat this file as persistent shared state.

At startup it must:
1. Read this file completely before proposing or changing anything.
2. Verify live repository, branch, HEAD, and relevant recent diffs/commits.
3. If the live source is newer than the state recorded here, inspect the changes first and merge that knowledge into this file before making new decisions.
4. Adopt the value of `NEXT_REVIEW_CHAT` as its own worker name, then update `CURRENT_REVIEW_CHAT` and increment `NEXT_REVIEW_CHAT`.
5. Read the CURRENT STATE, DECISIONS, ACTIVE TASKS, and EVENT LOG before continuing.
6. Never restart analysis from zero unless this file is corrupt or clearly stale.

During work it must:
- Log every meaningful user requirement, architectural decision, task start, task completion, code change, commit, CI result, render result, Visual QA result, blocker, and next step.
- Update this file progressively, not only at the end.
- Preserve previous history. Do not erase earlier decisions just because a newer decision supersedes them; mark superseded items explicitly.
- Before each write, fetch the latest version/blob of this file again. If it changed, merge the other chat's changes first and then write. Never blindly overwrite.
- For source-code writes, verify branch/HEAD again immediately before the write.
- Never claim a commit/CI/render/QA result unless verified.
- If a task is started but not finished, record it as IN_PROGRESS with enough detail for the next chat to resume exactly.

At handoff/end of chat it must:
- Update CURRENT STATE.
- Update ACTIVE TASKS.
- Append an EVENT LOG entry.
- Record the exact last verified branch/HEAD and any commit/CI/render evidence.
- State the exact next action for the next review worker.

---

## 1. PROJECT ROLE AND ENGINEERING STANDARD

This project is a production-grade video editing/generation application, not a tutorial or prototype.

Review chats act as:
- Senior Software Architect
- Senior Software Engineer
- Video Processing Engineer
- FFmpeg Specialist
- Performance Engineer
- Product Engineer
- Visual/Motion Review Engineer

Core rule:
**Fix the system, not one example video.**

For every significant change think in this sequence:

Requirement -> Correct owning layer -> Current behavior -> Desired behavior -> General rule -> Cross-package risk -> Failure cases -> Regression risk -> Tests -> Render evidence -> Visual QA.

No content-specific scene-ID hacks unless they are proven product-level behavior.

---

## 2. ARCHITECTURAL MODEL AGREED IN REVIEW 1

Conceptual pipeline:

`Story -> Visual Director -> Choreography -> Composition -> Layout Safety -> Text / Motion -> Render -> QA`

Ownership principles:

- Story: narrative/semantic meaning.
- Visual Director: what should be seen and semantic relationships; not low-level pixel geometry.
- Choreography: sequence/timing of visual beats and attention changes.
- Composition: final spatial arrangement/resting positions while respecting authored Final Package geometry.
- Layout Safety: prevents unsafe overlap/offscreen/collision; it should not redesign healthy scenes.
- Text: semantic text cues, typography layout, text rendering support.
- Motion: how planned visual events move; should not invent story.
- Renderer: deterministic execution, not creative decision-making.
- QA: detects and reports problems; does not become a creative director.

Creativity belongs in planning. Execution should be deterministic and inspectable.

---

## 3. REFERENCE VIDEO REVIEW — UNIFIED STYLE

Reference videos used in review:
- `hallo 2.mp4`
- `انحياز 2.mp4`
- `تأثير المتفرج2.mp4`

They are treated as one unified **Reference Style**, not as three competing styles.

Approximate unified reference baseline recorded in review 1:
- overall / viral potential: ~8.4/10
- visual storytelling: ~9.0
- semantic speech-to-visual link: ~8.7–9.0
- visual identity: ~8.7
- pattern interrupts: ~8.5
- motion density: ~8.5
- retention: ~8.4

Reference strengths:
- continual visual change
- strong semantic coupling between narration and visual events
- bold Arabic typography used as an editing event, not subtitles
- arrows/annotations used to guide eye and explain relationships
- strong cutout/explainer identity

Reference weaknesses observed:
- hook is good but not maximally aggressive
- some static periods
- payoff/loopability can improve
- style is not necessarily optimized for Shorts

User target is **horizontal YouTube 16:9**, not Shorts/TikTok.

---

## 4. CURRENT TOOL VIDEO REVIEW

Reviewed tool output:
`59e3ef95-14e9-4e7e-8a83-522f7cff85e4.mp4`

Approximate review-1 observations:
- static scene/asset quality: ~9.3
- semantic visualization: ~9.2
- visual metaphors: ~9.3
- scene diversity: ~9.1
- production value: ~9.1
- motion: ~7.2
- pattern interrupts: ~7.4
- pacing: ~7.6
- retention: ~7.9
- viral potential: ~8.0 vs reference ~8.4

Qualitative gap:
The tool often has prettier/clearer scenes, but at times behaves like an animated presentation:
`object enters -> settles -> waits -> next object`.

The references more consistently pull the viewer forward with new visual events.

Earlier conclusion: Choreography and Motion were the largest global gaps. However, at the current point the user says current **motion is strong** and does not want it redesigned while solving typography.

---

## 5. CHARACTER LIBRARY — DEFERRED / DO NOT IMPLEMENT

A 22-pose HEXA character library was reviewed from:
`hexacharecter مفرغ.zip`

The idea evolved from persistent character usage to occasional character/typography beats.

Final user decision in review 1:
**drop this idea for now.**

Do not bring the character-library feature back unless the user explicitly asks.

---

## 6. TYPOGRAPHY REFERENCE STYLE AGREED

The exact font cannot be proven from rendered MP4 alone.

Closest visual estimate chosen in review:
**Baloo Bhaijaan 2 ExtraBold / weight 800**

Treat this as the target visual match, not an absolute forensic identification.

Reference typography characteristics:
- heavy Arabic display
- rounded forms
- primary mode: white fill + thick black outline
- alternate mode: solid black
- light shadow only if needed
- usually short words/phrases, often one line
- typography behaves as a visual beat, not subtitles

Observed native reference resolution was approximately 854x480.

For 1920x1080, review-1 starting ranges:
- keyword / emphasis: ~120–180 px
- strong title / major phrase: ~150–220 px

These are adaptive starting ranges, not fixed constants.

White outlined text:
- outline/stroke should scale relative to actual rendered glyph size
- target roughly 4–6% of glyph height
- avoid one hardcoded stroke pixel value for all sizes/resolutions

Reference placement patterns seen:
- large text behind a character
- text split around a character
- top-centered title above objects
- local label near a relevant object

Critical adaptation rule for HEXA:
The AI Final Package scene is already composed. **Do not recompose or move scene assets just to make room for text.**
Take the reference font/style/presence, but adapt placement to real negative space in the already-authored scene.

---

## 7. CURRENT COMPOSITION BEHAVIOR — VERIFIED IN SOURCE

Review 1 inspected the actual source on `montage11-publish`.

Key files:
- `app/models.py`
- `app/cutout/pass1/service.py`
- `app/cutout/pass2/service_geometry.py`
- `app/cutout/pass2/extractor.py`
- `app/assets/manager.py`
- `app/composition/planner.py`
- `app/composition/states.py`
- `app/composition/footprint.py`
- `app/layout/solver.py`
- `app/composition/text_director.py`
- `app/pipeline.py`

Verified behavior:

### 7.1 Source geometry capture

Pass1 stores:
- `VisualAsset.source_bbox`
- `source_canvas_width`
- `source_canvas_height`

from the detected object's location inside the Final Package source image.

### 7.2 Composition does not use arbitrary templates when source geometry exists

`CompositionPlanner._source_relative_layout()` reconstructs relative authored geometry using source bboxes/canvas dimensions.

It computes the union of selected source boxes, preserves their relative arrangement, and fits the group into the output composition.

Current relevant target fit values in the inspected code:
- target width ~0.88
- target height ~0.82
- center x ~0.50
- center y ~0.51

Important correction captured during review:
The final asset position is **not necessarily the exact original source pixel coordinate 1:1**.
The source image geometry is the authored reference; the selected group may be uniformly transformed/fitted into 16:9 while preserving relative authored spatial relationships.

### 7.3 Pass2 family-canvas registration

Pass2-derived layers intentionally preserve parent-canvas geometry.

`service_geometry.py` explicitly keeps `source_bbox/source_canvas` unchanged for family layers.

`AssetManager` marks full-canvas Pass2/refined layers with `render_as_family_canvas`.

`CompositionPlanner._restore_family_canvas_geometry()` restores family-canvas members to authored positions after composition-state direction so their registration is not destroyed.

### 7.4 Composition state changes are bounded

`CompositionStateDirector` can make bounded semantic emphasis changes:
- max shift ~0.075 normalized screen space
- max scale up ~1.12
- min scale down ~0.92

This allows small narrative hierarchy adjustments without wholesale redesign.

### 7.5 Layout safety preserves healthy authored layout

`ConstraintLayoutSolver` first inspects the layout.

If no violation exists and standard element limits are satisfied:
it returns the authored layout and records `layout:authored_preserved`.

Repair happens only when necessary.

### 7.6 Alpha-aware geometry

`AlphaFootprintResolver` computes the actual visible alpha footprint rather than treating the whole transparent PNG rectangle as occupied.

This is already used by layout safety and text placement.

This is important for typography and future arrows.

---

## 8. CURRENT TEXT PLACEMENT — VERIFIED IN SOURCE

Existing implementation:
`app/composition/text_director.py`

Class:
`TextPlacementDirector`

Current useful foundation:
- receives the final/current `CompositionBeat`
- estimates text box size
- resolves an anchor from `TextCue.anchor_asset_id`
- builds a candidate field over safe screen regions
- adds candidates around the anchor
- uses alpha footprints for actual visual occupancy
- adds protected halos around visual elements
- strongly penalizes artwork overlap
- penalizes concurrent text collision
- considers anchor proximity
- considers preferred zone
- applies edge penalties and whitespace/clearance preference
- avoids blindly treating transparent canvas as occupied

This means typography placement is **not a greenfield feature**.
The correct direction is to improve its visual taste, scoring, typography measurement/style, density handling, and acceptance/fallback behavior without discarding the good geometry foundation.

---

## 9. ACTIVE TYPOGRAPHY REQUIREMENTS — OFFICIAL

This section supersedes earlier suggestions to reduce typography count.

### 9.1 User intent

The user explicitly corrected review 1:

**Do NOT reduce the number of words/text moments. Increase them.**
The goal is:
`MORE TYPOGRAPHY + BETTER SELECTION QUALITY`

Do not interpret this as longer subtitle-like sentences.

Increase the number of meaningful text cues across the video while keeping individual cues concise and visually strong.

Current motion is considered strong by the user and should remain essentially unchanged during this task.

### 9.2 Selection quality

Text is not subtitles.

Extract more useful semantic moments from narration, prioritizing:
- pivotal keywords
- results
- causes
- contrasts
- important negation
- surprise
- numbers
- concepts/terms
- short questions
- warnings
- words directly tied to a visible object
- semantic transitions
- important starts/ends of an idea
- spoken emphasis where meaningful

Do not fill density with weak filler.

A scene/beat may legitimately contain multiple high-quality text moments if the narration contains multiple meaningful shifts.

### 9.3 Cue length vs cue count

Increase **cue count**, not uncontrolled phrase length.

Typical cue:
1–4 words.

Longer phrases are exceptions.

Do not hard-limit one cue per scene/beat.

Do not use a blind timer rule such as “text every N seconds.”

### 9.4 Ranking strategy

Prefer rich candidate generation and semantic ranking rather than early aggressive filtering.

Conceptual quality tiers:
- VERY HIGH
- HIGH
- MEDIUM
- LOW

Use more VERY HIGH/HIGH candidates.
MEDIUM may be used when visual space/timing is excellent and it improves rhythm.
LOW should normally be rejected.

The semantic text planner should not suppress good candidates merely because it is afraid of layout.

Let Text Composition decide which strong candidates can actually be displayed safely.

### 9.5 Placement requirement

Text must use the **final/current CompositionBeat geometry** that the viewer will actually see, not raw source-image assumptions.

The scene does not move for text.

Text adapts to scene geometry.

Placement must:
- use visible alpha footprints
- preserve a protected halo
- avoid faces/main subjects/important objects/existing scene text
- avoid visual “kissing” even when there is technically zero overlap
- avoid unsafe edges
- avoid concurrent text collision
- prefer meaningful proximity to an anchor when relevant
- preserve scene balance
- treat center screen as expensive, not default

Generate several candidate positions and score them.

Candidate families should cover:
- top left / top center / top right
- left / right
- bottom left / bottom center / bottom right
- above/below/left/right of anchor
- diagonal anchor-relative candidates

If no professional placement exists:
**suppress that cue visually rather than damaging the scene.**

This is a visual feasibility fallback, not a reason to reduce semantic candidate generation upstream.

### 9.6 Reference style

Target the chosen reference style:
- Baloo Bhaijaan 2 ExtraBold / ~800 as current visual target
- heavy rounded Arabic display
- white fill + heavy black outline as primary robust style
- solid black on clean/light negative space
- very light shadow only when justified
- no gradients
- no glow/neon
- no heavy caption boxes by default
- strong, confident presence
- large but adaptive sizes appropriate to 1920x1080

Style selection should be deterministic from local contrast/visual conditions, not random.

### 9.7 Text size

Resolution-independent scaling.

Starting target at 1080p:
- keyword/emphasis ~120–180 px
- strong major phrase ~150–220 px

Final size must adapt to:
- phrase length
- importance
- available safe area
- neighboring elements
- actual shaped text measurement

A single strong word may be materially larger than a 3–4 word phrase.

### 9.8 Outline

Outline/stroke should scale with rendered glyph height, roughly 4–6% as a starting target.

Do not use one fixed pixel outline at all font sizes/resolutions.

### 9.9 Timing

Keep current text motion unless a concrete bug requires change.

Text should appear at or near the spoken semantic moment:
- not so early that it spoils the sentence
- not so late that it loses meaning
- not lingering after its visual purpose is gone

Voice + Text + Visual should feel like one event.

### 9.10 Acceptance

Passing unit tests is not enough.

Need visual proof across varied scenes:
- sparse scene
- dense scene
- character scene
- multi-object scene
- light background
- darker/complex background
- Arabic + numbers
- several cues in one beat/scene
- case where a cue is suppressed because no safe placement exists

Check:
- more typography than current baseline
- higher semantic quality
- no subtitle feel
- reference style is recognizable
- no visual collisions/kissing
- authored scene composition remains intact
- current good motion is not degraded
- placement does not look mechanically repetitive

---

## 10. SMART ARROWS — DISCUSSED, DEFERRED

Reference screenshots show thick black arrows used as semantic guides.

Agreed observations:
- arrows are not decoration
- they can express text -> object
- object -> object
- cause -> result
- concept -> examples
- one concept -> multiple targets

Reference arrow style:
- solid black
- thick
- large clear head
- straight or gently curved
- no gradient/glow/color
- slightly hand-drawn/explainer feel rather than technical CAD perfection

Approximate 1080p starting geometry discussed:
- body ~12–20 px
- head ~2.5–4x body stroke
Ratios matter more than fixed pixels.

Architecture agreed if/when implemented:
- Visual Director: whether an arrow is semantically needed and source/target relationship
- Choreography: when it appears/disappears
- Composition/Annotation Layout: routing, anchors, straight/curved geometry, collision avoidance
- Style System: common arrow visual language
- Motion: draw-on/enter behavior
- Renderer: deterministic drawing
- QA: verify target, visibility, collision, direction, density

Do **not** create a top-level “Arrow Layer” by default.

If implemented later, prefer an annotation subsystem/module under Composition/Layout, potentially reusable for arrows, brackets, circles, callouts, highlights.

Critical fallback:
if no clean arrow route exists, suppress the arrow.

Current decision:
**Do not implement Smart Arrows until Typography V2 is visually proven.**

---

## 11. IMPORTANT PRODUCT RULES FROM REVIEW 1

- Never move/recompose Final Package elements just to fit typography.
- Never make Renderer the creative decision maker.
- Never use per-scene hardcoded coordinates as the product solution.
- Never overfit to the current Final Package.
- Typography must work on future packages with different assets, counts, photographs, illustrations, charts, durations, and backgrounds.
- Use existing geometry/alpha knowledge instead of re-analyzing every frame expensively.
- Geometry decisions should be computed once per cue/beat where possible, not via costly per-frame scene analysis.
- If a visual feature cannot be placed safely, omission is a valid high-quality result.
- Distinguish semantic intent from visual feasibility.
- Preserve inspectability: when placement is bad, it should be possible to identify which planner/scorer made the decision.

---

## 12. CURRENT ACTIVE TASKS

### TASK REVIEW-TEXT-001
Status: READY
Title: Typography V2 — higher density, higher selection quality, reference visual style, safer placement

Scope:
- Improve text semantic candidate quality.
- Increase useful text-cue density.
- Improve placement scoring/measurement/safety.
- Match agreed reference typography style.
- Preserve current motion.
- Preserve Final Package composition.

Out of scope:
- Smart arrows.
- Character library.
- major Motion redesign.
- scene-specific hacks.

Required before implementation:
- live branch/HEAD verification
- inspect any commits since this file's last recorded source state
- code mapping receipt: exact classes/files to change, why each owns the behavior, tests and visual proof plan
- no code until the mapping is coherent

Required after implementation:
- tests
- commit SHA
- CI status if available
- render
- technical QA
- Visual QA
- update this file with results

---

## 13. REVIEW-CHAIN STARTUP RECEIPT FORMAT

Every new review chat must first respond with a compact receipt containing:

- REVIEW WORKER: review N
- RECEIVED FROM: previous review worker
- REVIEW STATE VERSION
- OFFICIAL HANDOFF FILE
- LIVE REPOSITORY
- LIVE BRANCH
- LIVE HEAD
- LAST RECORDED HEAD
- NEW COMMITS SINCE HANDOFF: yes/no + summary
- ACTIVE TASK
- CURRENT DECISIONS THAT MUST NOT BE REGRESSED
- LAST BLOCKER
- NEXT ACTION

Only after this receipt may the chat continue implementation/review.

---

## 14. EVENT LOG

### EVENT 001 — review 1 — 2026-09-19
- Reviewed three reference videos as one unified style.
- Reviewed current HEXA output video and identified style/retention gaps.
- Discussed optional character library; user later deferred it.
- Established reference typography target and approximate font/style/scale.
- Reviewed reference Smart Arrows and defined preliminary architecture; arrows deferred.
- Clarified Composition ownership and arrow ownership.
- Inspected live source on `montage11-publish`.
- Verified authored source geometry flow, Pass2 family-canvas registration, bounded composition-state changes, layout safety, alpha footprint use, and current TextPlacementDirector foundation.
- Corrected earlier simplification: final composition preserves authored relative geometry but may fit/transform the group into the 16:9 frame rather than preserving exact source pixels 1:1.
- User stated current motion and current word selection are already strong foundations.
- User requested text style/placement improvement and better selection quality.
- User explicitly corrected density requirement: **do not reduce text; increase the number of useful text cues while improving selection quality.**
- User requested an official persistent review-chain source and synchronized handoff protocol.
- Created this file as the authoritative review continuity source.
- No application code was changed by review 1 in this conversation.
- Next action: Typography V2 code mapping + implementation only after new worker syncs live state.

---

## 15. HANDOFF RULE

When a review chat reaches context/limit or the user asks to continue elsewhere:

1. Finish writing all current state into this file.
2. Verify the write succeeded.
3. Give the user the reusable startup prompt that points the next chat to this exact file.
4. The next chat must not ask the user to repeat project context already present here.
5. Continue from the latest ACTIVE TASK and EVENT LOG, not from memory.

