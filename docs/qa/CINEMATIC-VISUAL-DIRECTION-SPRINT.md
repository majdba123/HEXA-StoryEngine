# HEXA StoryEngine — Cinematic Visual Direction & Motion Quality Sprint (2026-10-16)

**Status:** implemented on `montage` (local commits on top of `df0482c`, not pushed), verified by
tests, frame-exact plan probes and real FFmpeg encodes. **Not an artistic certification:** the
user's visual review of the final videos is pending. `bayer`, the VPS, user data, uploads,
production exports, the Final Package inputs and authored Composition geometry are untouched.

Evidence (outside Git): `E:\hexa-visual\` — `stage1\`..`stage6\` (clips, strips, audits, plan
deltas), `p2\` (plans after Stage 2), `p3\` (Stage 3), `p4\` (Stage 4), `p5\` (Stage 5),
`final\` (final encodes + reports). Baseline plans: `E:\hexa-vnext2\motion-fix\c8-montage-merge\`
(byte-identical to `df0482c`). Baseline Black Hat render (A/B reference):
`C:\Users\INTEL CENTER\Documents\HEXA-Archive\cinematic-vnext2-final-2026-10-16\review\videos\`.
Harness (git-ignored): `.hexa/visual-sprint/` (`segment_clip.py` renders only the beat segments of
a window with the production renderer; `text_audit.py`, `plan_delta.py`, `ass_diff.py`,
`blur_proto.py`, `capture_graph.py`, `ab_clip.py`, `time_render.py`, and the VNext2 tools —
`probe.py` now also reads motion-blur branches).

## 1. Reference analysis (measured, normalised)

Supplied: `انحياز 2.mp4` (854×480, 30 fps, 79.3 s; the animation is 25 fps with every 6th frame
duplicated) and `تأثير المتفرج2.mp4` (854×480, 25 fps, 72.9 s). **`hallo 2.mp4` is not on this
machine** (searched the desktop, downloads, videos, documents and `E:`); nothing below is derived
from it. Positions are fractions of the canvas, speeds in canvas widths (w) or heights (h) per
second of real time.

| Moment | Measurement | Reading |
|---|---|---|
| Bias 2.27–3.5 s, character slide | 0.32 w to the right; peak 1.15 w/s at +0.23 s, long ease-out to rest at ~3.5 s | fast start, long settle |
| same, motion blur | fitted horizontal box blur 0.041 w at the peak, ≈ velocity × 0.03 s (≈ 0.9 frame at 30 fps); ≤ 3 px below ~0.1 w/s; sharp at rest (Laplacian variance 40 → 1780) | velocity-proportional, resolves sharp |
| Bias 62.17–62.47 s, context recedes | Gaussian σ ≈ 0.0094 h, white → 212, contrast × 0.65, 0.30 s smooth ramp; the character stays sharp at full contrast | depth/focus wash |
| Bias 62.67–63.2 s, confirmation | check mark fades in over 0.13 s and pops 0.71 → 1.13 → 1.0 (0.53 s) over the blurred context | one sharp payoff element |
| Bystander 11.16–11.36 s | context σ ≈ 0.0115 h, white → 210, gain 0.78, 0.20 s ramp, starting 0.08 s before the coins | the backdrop recedes as the subject arrives |
| Bystander 11.24–12.4 s, coins | rise from below the canvas, ~1 h/s then a long drift; vertical motion blur that fades with speed | vertical entry, sharp-on-blur |
| Text (both) | words fade in 0.33–0.40 s, out ~0.20 s; one or two words placed in negative space beside their subject; first word on the right | restrained text grammar |

HEXA's existing PAYOFF wash (`REFERENCE_WASH`: σ 9 px at 1080 lines = 0.0083 h, white → 213, 0.2 s
ramp) already matches the measured recession; what HEXA lacked was motion blur on moving
elements, vertical arrivals and a soft text grammar.

## 2. Stage 1 — Arabic reading order (commit `204bff5`)

**Root cause (traced Canonical script → Semantic Text Selection → spans → timing → Text
Motion → ASS → libass → encoded frame).** Every layer up to Text Motion keeps the logical order.
Words spoken before their subject is recognisable start at the same instant
(`display_after_anchor`); `TextRenderer._cue_events` re-sorted the reveal states by `(start, end)`,
so a shorter second word came first and libass shaped `التقنية المعرفة` for `المعرفة التقنية`
(Black Hat beat-002, encoded frame confirmed). Corpus: **12 cues in 5 packages** (Black Hat, Bug
Bounty, Insider Threat, State-Linked Group, White Hat), YouTube and Reels.

**Fix.** Reveal states follow the planned reading order; words starting within one frame form one
state (no overlapping states); Text Motion keeps token starts non-decreasing; the render handoff
rejects tokens that do not read as their cue (`text_motion_tokens_out_of_reading_order`).

**Evidence.** ASS diff over 20 plans: 24 of 976 beat text events change (exactly the tied cues),
952 identical. Encoded-frame tests (`tests/test2/text/test_reading_order.py`): the first spoken
word stays on the right through every reveal state and the completed line is pixel-equal to the
cue shaped as one RTL run; they fail on the old renderer.

## 3. Stage 2 — Text hierarchy and placement (commits `f3872c4`, `3335caf`)

**Audit** (454 cues per target; the exact ASS plus frame-exact asset geometry): no text/text
overlap, no safe-area violation, no sustained text/asset overlap (text covered > 10 % for at most
2–4 frames, when the next asset arrives as the text leaves). Weaknesses: every later word popped
in (304), every phrase vanished with a cut (454, 241 mid-scene), short words drifted up to 75 px
right of their anchor (edge-aligned in the 346 px minimum label box), and 26 words revealed during
the entry gesture made the line jump up to 24 px.

**Change.** Text Motion plans `entry_fade_ms` (half the entry gesture, 65–120 ms), `word_fade_ms`
(100 ms) and `exit_fade_ms` (≤ 180 ms and ≤ 30 % of the full-phrase hold). The renderer fades an
added word alone (the new state is clipped to the new words while the earlier state keeps drawing
the earlier ones — nothing is drawn twice); mixed-direction lines and touching words keep a cut; a
state inside the entry gesture continues it; text is softer only while it travels; the completed
phrase is centred on its planned box when its entry path fits. Plans without the new fields render
as before (except centring and continuation).

**Evidence.** Soft word reveals 297/304 (YouTube), 286/304 (Reels); exit fade 454/454; anchor
drift > 40 px 16 → 0; RenderPlan delta only adds the three `text_motion` fields; encoded test:
during a word fade the earlier words are exactly the earlier state's pixels. `3335caf` removes a
`1920×1080` default and format names that `f3872c4` had put into the shared text renderer (the
dual-format architecture guard).

## 4. Stage 3 — Cinematic blur system (commit `81fadb2`)

**Investigation.** Renderer blur before this sprint: the PAYOFF focus wash (B2, calibrated, kept),
the `BLUR_BRIDGE` scene bridge (Gaussian over the old scene) and a 0.25–0.35 px text blur. Moving
elements were never blurred. Prototypes on the real Black Hat beat-031 graph: temporal
supersampling (4 sub-frames) strobed into discrete copies (+5.9 s per segment); per-frame
directional blur (`dblur` + `sendcmd`) gave a smooth smear (+0.85 s). dblur is symmetric; its
10–90 % edge spread is ≈ 3.3 × radius, so a box exposure of length L uses radius 0.24 L. The
reference smear (≈ 0.03 s ≈ 324°) was compared with 180° and 270° on encoded frames; **180° (half
a frame) is the default** — natural on illustrations, keeps them legible.

**B1/B4 — ownership.** Motion owns motion blur (`app/motion/motion_blur.py`, decided on the final
Motion after family binding): a cue whose drawn position travels a visible distance during a
centred half-frame exposure gets `params.motion_blur`; lengths are fractions of the content height
(min 0.0019, max 0.06; a jump beyond four maximum smears within one exposure is a cut, not motion).
Scale-only motion, geometry-locked layers and imperceptible travel abstain; a Pass2 follower
inherits its leader's blur through the shared transform. Boundary owns the blur of the exits it
plans (`SceneBoundaryRelease.exit_motion_blur`, only with `exit_starts`/`overlap_exits`) — **B3**.

**Execution.** `app/render/expression.py` evaluates the exact FFmpeg position expressions the
renderer writes (whitelisted syntax tree, never `eval`). Per frame, the smear is the displacement
of the element centre during its exposure (direction and length). Each blur window is its own
branch, trimmed to the window: padded (never clipped), premultiplied (no halo), `dblur` driven by
`sendcmd`, then the same transform. Frames outside the windows are drawn by the untouched sharp
branch; the split input is pinned to `rgba` so they stay byte-identical.

**B5 — certification.**

| Check | Result |
|---|---|
| Coverage (10 packages, YouTube) | 704 of 1825 cues blurred; 907 below a visible smear; 214 geometry-locked; 48 planned exits blurred |
| Smear length | median 6.4 px, p90 12.7 px, max 55.6 px at 1080 lines (cap 64.8) |
| RenderPlan delta (Stage 2 → 3) | only `motion.params.motion_blur` (1408) and `scene_boundaries.exit_motion_blur` (96) |
| Frame-exact probe, blur vs no blur | identical: 0 abrupt disappearances, 0 multi-leader beats, 0 repeated pulses, max speed 0.999 w/s, 10 fast-scale frames (Sprint 4.1), 20 sentence-over-scene boundaries (kept exclusions); geometry equal within 0.49 px on all 8372 Black Hat asset-frames |
| Rest frames | byte-identical (lossless encode test) |
| Direction | horizontal travel smears horizontal gradients (< 0.85 ×) and keeps vertical ones (> 0.9 ×) |
| Halo | trail never darker than the sprite (−8 levels tolerance); a straight-alpha mutant fails at −40 |
| Scene boundaries | blur windows are trimmed inside their own segment — no cross-cut pixels by construction |
| Render cost (Black Hat YouTube, one worker) | 146.3 s → 156.5 s (+7 %) on an idle machine; a second pair (165.8 / 220.8 s) overlapped another full pytest run and is not used |

**Defect found by the final-media gate and fixed (commit `56f2de5`).** The first final Black Hat
encode failed `VISUAL_WHITE_FLASH` (8 near-white handoff frames: 36.13, 36.33, 45.80, 45.90, 61.87,
62.07, 65.77, 65.97 s). With `eof_action=pass`, FFmpeg's overlay drops the frame that arrives
together with the blur branch's end of stream: the element vanished on the last frame of every
blur window and completely on one-frame windows (a scene opener alone on screen → a white frame).
The plan probe models the trim and could not see it, and the encoded test compared frame ranges,
not presence. Each branch now keeps one spare frame past its window (outside the overlay's
enable); the encoded test asserts the element is drawn on every frame and fails without the fix
("element missing on frame 32", the window's last frame). Every clip and encode in this report
was re-rendered after the fix.

A/B clips (`E:\hexa-visual\REVIEW-visual-sprint\ab-blur\`, rendered after the fix): `AB-arrival-slow2.mp4` (Bystander 11.15 s | Black Hat
before | after: the eye arriving over the washed backdrop), `AB-exit-slow2.mp4` (Bias 2.2 s |
Black Hat opening hero exit), `AB-travel-slow2.mp4`.

Pre-existing, not changed: the box-fit resize of every cutout (`scale … force_original_aspect_ratio`)
interpolates straight alpha; with the packages' white transparent pixels this leaves a ≤ 1 px light
edge fringe, invisible on the white canvas. Fixing it changes every cutout's edge pixels and is
left as a separate decision.

## 5. Stage 4 — Entry and exit direction (commit `0c3d7ab`)

**Eligibility audit** (YouTube, 1845 entering cues, Stage 3 plans): directional entries 118
(51 side-edge slides, 67 hero travels), 495 pops, 1185 fades — window below the pop minimum 419,
certified gesture owns the entry 269, geometry-locked layer 167, accent inside the arrival 156,
entry segment owns the motion 91, yields to the hero pulse 42, family cannot move as one 24.
Edge slides only considered the left/right edges; the references also bring objects up from the
bottom.

**Change** (`app/motion/arrivals.py`). An asset near no side edge but within the same *physical*
reach of the top or bottom edge slides in vertically from that edge, over the same pixel distance
and peak speed as a side slide (0.08 width-equivalent, ≤ 0.6 w/s, 8–12 frames, smoothstep with the
calm opacity entry; reason `edge_slide_vertical`). Side-edge slides are unchanged; every safety
check applies unchanged (path clear of visible assets and hero paths; a path through composed text
falls back).

**Result** (Stage 3 → 4 plans): slides 51 → 97 (+46 vertical), pops 495 → 451, directional entries
118 → 164; 3 slides fell back because their path met composed text. RenderPlan delta: `motion`
only. Probe: unchanged except frames with ≥ 3 elements moving 416 → 448 (+32 frames over 20 plans;
a slide moves where a pop only scales). Of the 263 reference pops left, 260 are near an edge but
their Story window (reveal → settle) is shorter than the 8-frame calm-slide minimum; 3 have a
blocked path. The binding constraint is Story timing with the user-approved calm pacing, not
direction.

**Exits — abstained by design.** 478 boundaries: HARD_CUT 431, CRISP_HANDOFF 32, HOLD_TO_OPENER 7,
OVERLAP 8; 46 full-frame hero exits planned. Off-frame travel and exit overlap into the next scene
are authorized for the hero only (2026-10-14 contract); hero exits abstain when incoming arrivals
would overlap the exit (262 + mixed), the path crosses incoming artwork (48 + 26), the incoming
scene is too short (69), the hero recedes behind a resolution (15) or the path crosses incoming
text (4). Widening exits would break the independent-exit and no-collision protections, so no exit
rule changed; Stage 3 gave the 48 planned exits their motion blur.

## 6. Stage 5 — PAYOFF, scale and pacing

**Black Hat ~46–47.5 s (beat-021, «إذا وصل إلى حساب موظف»), investigated before changing.**
Layout: login gateway (left), employee badge (centre, scene hero), access key (bottom right).
Motion: the badge fades in at 46.29 s with a 1.012 CONNECT breath; the gateway nudges 0.016 w right
and back (CONNECT, 46.43–46.79 s); the key is the PAYOFF result (BUILD_UP, P0) and *pops* 0.84 → 1.0
at 46.51–46.77 s at the bottom-right edge, 0.87 s before the cut. The suspected off-centre pivot is
**rejected**: every asset's visible content is centred in its box (0.50, 0.50 after trimming), so
the pop grows in place. What reads as "an asset enlarging toward the right" is the payoff itself: a
pure scale pop of the last element at the frame edge, with no visual link to the badge, while the
backdrop wash is blocked (`wash:no_readable_hold`).

**Evidence-based treatment (cause → consequence).** The package authors the event's leader (badge)
and RESULT (key) with the Choreography relation `ENABLES` (`CAUSE_EFFECT_CHAIN`). When a resolving
result's relation is one of the Choreography `CONNECTABLE_RELATIONS` (directional flow/cause — the
only relations allowed to be drawn as a connection) and the event's leader of another family is
already on screen, Resolution marks it `causal_arrival`; Arrivals then lets it arrive moving away
from that cause: a short slide along the cause → result direction with the edge slide's limits
(≤ 0.08 w, ≤ 0.6 w/s, ≥ 8 frames, never beyond halfway to the cause), **scale unchanged**, path
clear of other visible assets (the cause only when the result is drawn above it, so it emerges from
it), of hero paths and of composed text; otherwise the pop stays with an exact reason. The verifier
applies the reference slide comfort to a PAYOFF-phase slide exactly as it does to a pop.

**Result** (YouTube): of 166 payoff pops, 8 carry causal evidence; 3 became causal slides (Bug
Bounty 028 magnifier out of the researcher's tablet, `LEADS_TO`; Social Engineer 046 warning gear
out of the shield, `LEADS_TO`; State-Linked 010 pause button out of the server, `CAUSES`); 3 keep the
pop (path crosses a visible asset); 2 keep it because the payoff window is shorter than the 8-frame
calm-slide minimum — **including Black Hat beat-021** (window 0.256 s = 7.7 frames). The other 158
pops have no directional evidence or no earlier leader and keep the pop (nothing invented).
RenderPlan delta: `motion` only (106 values); probe unchanged. A/B strip and clips (rendered after
the blur fix): `E:\hexa-visual\REVIEW-visual-sprint\ab-payoff\`.

**Not changed, with evidence.** Scale anchors (content centred; Pass2 layers scale with their
family's shared box). Sprint 4.1 character emphasis (protected; no new evidence). Pacing audit
(1825 reveals): median reveal − spoken trigger 0.000 s (p10 −0.36 s: the user-authorized
sentence-start openers; p90 0.15 s); readable hold after the last arrival median 0.50 s, 114 of 488
scenes below 0.3 s — set by narration (the last element's word comes late in the sentence);
changing it would move Story instants or scene sync, both protected.

**Open decision for the user (Black Hat 021 and similar tight payoffs):** keep the calm pop;
allow a 7-frame causal slide (peak 0.47 w/s, within the speed limit, below the 8-frame minimum the
user approved); or reveal the key on its own trigger word earlier (a Story decision).

## 7. Stage 6 — Opening hooks and continuity

Scene openers (488): 208 keep a certified gesture, 94 have a window below the pop minimum, 66 pop,
38 have an entry segment, 26 an accent, 21 a payoff pop, 17 slide, 12 belong to a family that cannot
move as one. A scene's opener is drawn at full opacity on the cut by design ("a faint first frame
over an empty canvas is a near-white flash", user review of earlier renders). For the **first scene
of each video** this means the first element appears at once after 1–8 blank frames (Black Hat 3,
Hacktivist 8). A soft fade-in from white would be a calmer cold open but adds 3–6 near-white frames;
that is an artistic call, so it is **left for the user** and not changed. Continuity across scenes
(handoffs, families, sentence-start openings, independent exits) is unchanged and protected; the
new text exit fades and exit motion blur make scene changes softer without new transitions.

## 8. Final encodes and regression matrix

All 20 outputs (10 packages × YouTube/Reels) were rendered from the final plans (Black Hat plans
re-planned at HEAD `56f2de5` are byte-identical to the encoded ones) with the production renderer,
muxed with the source narration and checked by the production gates:

| Gate | Result |
|---|---|
| Encoded-motion verifier | 20/20 pass, 0 violations |
| Final-media verifier (A/V, white flashes, blank frames, …) | 20/20 pass (after the `56f2de5` fix; before it, Black Hat YouTube failed `VISUAL_WHITE_FLASH`) |
| Rendered visual evidence | written for every output (`final\<PKG>\<target>\diagnostics\`) |
| Streams | every output has video (1920×1080 or 1080×1920, 30 fps) and the narration audio |
| Render time | 2441.6 s for the 20 outputs, one worker each, sequential on a shared machine |

Per-package matrix: `E:\hexa-visual\final\regression-matrix.md` (copied below).

| Package | Target | Render s | Encoded motion | Final media | Abrupt | Multi-leader | Max w/s | Text cues (soft/hard words, overlap, unsafe, drift>40) | Blurred cues | Vertical / causal slides |
|---|---|---|---|---|---|---|---|---|---|---|
| BLACK_HAT_HACKER | youtube | 185.9 | pass | pass | 0 | 0 | 0.984 | 35 (25/0, 0, 0, 0) | 78 | 3 / 0 |
| BLACK_HAT_HACKER | reels | 126.5 | pass | pass | 0 | 0 | 0.828 | 35 (24/1, 0, 0, 0) | 78 | 3 / 0 |
| BUG_BOUNTY_HUNTER | youtube | 131.1 | pass | pass | 0 | 0 | 0.949 | 39 (25/0, 0, 0, 0) | 81 | 5 / 1 |
| BUG_BOUNTY_HUNTER | reels | 78.7 | pass | pass | 0 | 0 | 0.797 | 39 (23/2, 0, 0, 0) | 81 | 5 / 1 |
| CYBERCRIME_GANGS | youtube | 157.2 | pass | pass | 0 | 0 | 0.975 | 66 (41/0, 0, 0, 0) | 123 | 6 / 0 |
| CYBERCRIME_GANGS | reels | 112.4 | pass | pass | 0 | 0 | 0.819 | 66 (40/1, 0, 0, 0) | 123 | 6 / 0 |
| GRAY_HAT_HACKER | youtube | 136.2 | pass | pass | 0 | 0 | 0.866 | 43 (25/0, 0, 0, 0) | 59 | 1 / 0 |
| GRAY_HAT_HACKER | reels | 88.2 | pass | pass | 0 | 0 | 0.825 | 43 (25/0, 0, 0, 0) | 59 | 1 / 0 |
| HACKTIVIST | youtube | 125.9 | pass | pass | 0 | 0 | 0.851 | 43 (20/0, 0, 0, 0) | 57 | 7 / 0 |
| HACKTIVIST | reels | 87.9 | pass | pass | 0 | 0 | 0.826 | 43 (19/1, 0, 0, 0) | 57 | 7 / 0 |
| INSIDER_THREAT | youtube | 166.4 | pass | pass | 0 | 0 | 0.864 | 56 (43/0, 0, 0, 0) | 83 | 9 / 0 |
| INSIDER_THREAT | reels | 117.8 | pass | pass | 0 | 0 | 0.842 | 56 (41/2, 0, 0, 0) | 83 | 9 / 0 |
| SCRIPT_KIDDIE | youtube | 161.1 | pass | pass | 0 | 0 | 0.96 | 37 (35/1, 0, 0, 0) | 50 | 4 / 0 |
| SCRIPT_KIDDIE | reels | 81.9 | pass | pass | 0 | 0 | 0.839 | 37 (33/3, 0, 0, 0) | 50 | 4 / 0 |
| SOCIAL_ENGINEER | youtube | 118.6 | pass | pass | 0 | 0 | 0.903 | 40 (22/0, 0, 0, 0) | 69 | 2 / 1 |
| SOCIAL_ENGINEER | reels | 72.4 | pass | pass | 0 | 0 | 0.817 | 40 (21/1, 0, 0, 0) | 69 | 2 / 1 |
| STATE_LINKED_GROUP | youtube | 190.5 | pass | pass | 0 | 0 | 0.999 | 64 (41/3, 0, 0, 0) | 92 | 7 / 1 |
| STATE_LINKED_GROUP | reels | 141.6 | pass | pass | 0 | 0 | 0.839 | 64 (41/3, 0, 0, 0) | 92 | 7 / 1 |
| WHITE_HAT_HACKER | youtube | 102.5 | pass | pass | 0 | 0 | 0.845 | 31 (20/3, 0, 0, 0) | 61 | 2 / 0 |
| WHITE_HAT_HACKER | reels | 58.8 | pass | pass | 0 | 0 | 0.827 | 31 (19/4, 0, 0, 0) | 61 | 2 / 0 |

Outputs: 20; encoded-motion pass 20; final-media pass 20.

Text columns: cues, later words revealed soft/with a cut, text/text overlaps, safe-area violations, anchor drift > 40 px (frame-exact asset geometry). Vertical and causal slides are Motion decisions shared by both targets (Reels is projected from the YouTube plan).

Protected gains (frame-exact probe of the final plans' filtergraphs, 20 plans — a model of
what FFmpeg draws, which is why the blur last-frame defect needed the encoded gates and the
encoded presence test to be found): mid-motion vanishes 0, abrupt disappearances 0, beats with more than one pulsing family 0, repeated pulses 0, max centre speed
0.999 w/s, frames above 1.2 scale/s 10 (Sprint 4.1, unchanged), sentence-over-previous-scene
boundaries 20 (the kept RESULT/dependency exclusions, unchanged), glued exits unchanged (no exit rule
changed), Composition geometry unchanged (RenderPlan deltas never touch `composition`).

## 9. Tests

New tests: `tests/test2/text/test_reading_order.py`, `tests/test2/text/test_text_transitions.py`,
`tests/test2/render/test_motion_blur.py`, `tests/visual/test_visual_sprint_vertical_slides.py`,
`tests/visual/test_visual_sprint_causal_payoff.py` (encoded-frame tests where the claim is visual).
Mutation checks: the reading-order tests fail on the old renderer; the halo test fails on a
straight-alpha blur; the presence test fails without the spare blur frame. One existing fixture
moved (`test_a_centred_asset_pops_and_a_tiny_one_keeps_its_fade`: its tiny asset sat near the top
edge, where it now slides; the visibility-floor rule it checks is unchanged).

Full suite on the final code (`56f2de5`, worktree `E:\hexa-visual-wt`): **10289 tests, 0 failures, 0 errors, 38 skipped, exit 0** (1293 s; junit `E:\hexa-visualinal\gates\pytest-full.xml`). Package-holdout gate (`python -m tests.package_holdouts.report require`, holdouts run on their own as in CI): **80/80 executed and passed**. Ruff: all checks passed. CI on `montage` has not run because nothing is pushed.

## 10. Accepted, rejected, abstained

| Item | Decision | Why |
|---|---|---|
| Arabic reading order | accepted | measured defect, 12 cues; encoded-frame tests |
| Soft word reveals, exit fades, entry fade | accepted | reference grammar, no double draw, bounded by the readable hold |
| Phrase centred on its box | accepted | removes up to 75 px anchor drift |
| Entry-gesture continuation, sharp-at-rest text | accepted | removes up to 24 px jumps and re-sharpening |
| Directional motion blur (B1) and exit blur (B3) | accepted (180°) | velocity-proportional, sharp at rest, no halo, +7 % render |
| Temporal-supersampling blur | rejected | strobes into copies at 4 samples; 7× the cost of dblur for smooth results |
| 270° shutter | offered as A/B | closer to the reference, softer illustrations — user's call |
| Depth/focus wash (B2) | kept as is | already matches the reference recession |
| Transition focus pulls / full-frame blur over cuts | abstained | no measured need; the prompt forbids blur that hides weak cuts |
| Vertical edge slides | accepted | +46 directional entries, same limits as side slides |
| More exits | abstained | hero-only contract; independent-exit and collision protections |
| Off-centre scale pivot | rejected (not a cause) | content is centred in every box |
| Cause → consequence payoff slide | accepted | 3 corpus cases with authored directional relations |
| Black Hat 021 payoff | abstained (pop kept) | 7.7-frame window; options for the user in §6 |
| Sprint 4.1 emphasis | unchanged | protected; no new evidence |
| Pacing / readable hold | unchanged | set by narration; changing it would move Story instants |
| Cold-open fade-in | left to the user | adds near-white frames that an earlier review rejected |
| Straight-alpha box-fit fringe | left to the user | pre-existing; would change every cutout's edge pixels |
| Exporter decode warning | follow-up | `app/final/exporter.py` decodes FFmpeg output with the Windows code page; a background reader thread logs `UnicodeDecodeError` (also in the 2026-10-16 VNext2 encode log); the mux result is unaffected and verified separately |

## 11. Changed files

`app/render/text.py`, `app/motion/text.py`, `app/shared/handoff_text.py` (text);
`app/motion/motion_blur.py` (new), `app/render/expression.py` (new), `app/render/renderer.py`,
`app/pipeline.py`, `app/models.py`, `app/boundary/release.py` (blur); `app/motion/arrivals.py`
(vertical and causal slides), `app/motion/resolution.py` (causal evidence),
`app/render/verification.py` (PAYOFF slide comfort). 18 files, +1640 / −88 lines including tests.
