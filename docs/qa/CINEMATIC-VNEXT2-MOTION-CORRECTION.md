# HEXA StoryEngine — Cinematic VNext2 motion correction (exits, payoff, pacing, sync)

**Status:** implemented on `cinematic/vnext2`, verified by tests and by real FFmpeg encodes of
all ten available real packages (YouTube and Reels). Update 2026-10-16: the user authorized the
Story `SCENE_SENTENCE_START` opening authority (Problem D, §2-§4). **Not a certification:** the user's
visual review is pending. Production (`montage`, `bayer`, VPS, CI/CD) untouched.

Evidence (outside Git): `E:\hexa-vnext2\motion-fix\` — `b0-head\` (HEAD `280ae40` plans),
`b1-wip\` (HEAD + preserved WIP plans), `c3\` (motion correction plans), `c5\` (final plans,
with the Story authority), `encodes-a\`..`encodes-e\` (encodes + `render-report.json`; c/d/e
re-encode the four packages whose plans changed), `compare\` (before/after video and frame strips),
`gates\` (pytest junit/log). Harness (git-ignored): `.hexa/vnext2-motion/` (`probe.py`,
`plan_all.py`, `render_package.py`, `compare.py`, `tables.py`, `beat_dump.py`,
`asset_track.py`, `holds.py`, `rescore.py`).

## 1. Starting point

| Item | Value |
|---|---|
| Branch / worktree | `cinematic/vnext2` / `E:\hexa-vnext2-wt` |
| HEAD at start | `280ae40` (Motion/Render: a rigid Pass2 family moves as one unit) |
| Preserved WIP | `app/motion/arrivals.py` (`_is_nudge` accepts sub-visible planner gestures), `app/motion/hero_travel.py` (`hold_emphasis` opener pulse), `app/pipeline.py` (calls it). Kept and committed with this work; patch copy saved before any edit |
| Measurement | `probe.py` runs the real `FFmpegRenderer._render_beat_segment` for every beat, captures the filtergraph and evaluates its overlay/scale/fade expressions on every encoded frame (geometry and opacity of every cutout); real encodes confirm |
| Planning input | cached transcript/vision/cutouts (`E:\hexa-vp3\cache`), Story/Director/Choreography/Text re-planned with the code under test (as `_plan_shared`) |

Note: planning from the cache *without* re-planning Story reproduces the old 2026-10-13 Story
(Black Hat: 22 stale boundaries, 12.7 s); the current Story code gives 1 boundary, 0.23 s.

## 2. Root causes (measured)

| # | Problem | Owner | Root cause |
|---|---|---|---|
| A1 | Elements vanish mid-exit | `app/render/renderer.py` bridge | Every ordinary scene change (`MOTION_HANDOFF`, Boundary row `HARD_CUT`, audit `clean_cut`) still drew the legacy outgoing drift: 48–120 px over the 3–12 frames before the opener, then the cutout was removed fully opaque and on screen. Boundary had planned a clean cut; the renderer executed a partial exit. **1553 such vanishes in 10 packages** (BH 140) |
| A2 | Planned exits never finish | `app/boundary/release.py` `_exit_schedule` + renderer | CRISP_HANDOFF "restrained exit" was capped at the EXIT comfort speed (0.14 w/s) and clipped to stay inside the canvas, so by design it moved a few pixels and was then cut (100 planned in 10 packages) |
| A3 | One-frame jump at a pop | `app/render/motion.py` | A non-ENTRY segment starting on an encoded frame was bounded by `between(t, start, …)` written with 6 decimals; the bound can round past the frame, so that frame drew the previous pose (a pop's first frame at full size, then a snap to 0.84). Verified on Hacktivist frame 2928 |
| A4 | Two elements leave glued together (user review 2026-10-16) | `release._exit_schedule` | Complete exits only checked that each unit could leave in time, not its path: in Social Engineer 015 → 016 (`c3`) the man (centre) and the ID card (top-left, drawn above him) both left through the left edge; the man's path ran under the card, so for 9 frames (28.1 s) they moved as one block. Pass2 families (one picture split into layers, e.g. a broken lock and its shard) are not affected: they must move as one |
| B1 | Several elements pulse at once | Motion (no owner) | Up to five sources grew cutouts above rest independently: event-chain arrival overshoots (1.018–1.032 on every ADD/ESTABLISH asset), relation accents, hero pulse, secondary PAYOFF pulse, the WIP opener hold pulse. No "one leader per beat" rule existed. **134 beats with >1 pulsing family, 73 beats with the same element pulsing twice** |
| B2 | Pulse looks cheap | `hero_travel._emphasis` | 0.45 s, peak at 45 % with no hold, up to 8 %, 2 frames after settle |
| C1 | Rushed arrivals | `resolution.py` / `arrivals.py` constants | VNext2 reference pop from 0.62 size in ≤ 5 frames (peak scale rate up to **6.6 /s**); slides 0.12 w in 4–10 frames (WIP lowered the minimum to 4 frames) |
| C2 | Rushed travel/exits | `HERO_TRAVEL` | VNext2 raised the authorized VP4 contract (1.0 w/s, 0.40 s) to 1.25 w/s, 0.30 s |
| C3 | Busy scene openings | `release._hero_overlap_exit` | The outgoing hero's full-frame exit ran while several incoming elements arrived (e.g. BH 024 "ممكن يبيعها", 0.8 s: hero exit + 3 arrivals) |
| D | Next sentence over the previous scene | Story (`_establish_opening_visual`) | Already fixed for Black Hat by `7b3676b` (0.23 s left, < 300 ms). In the other packages 25 boundaries remained (14.3 s over 10 packages, 22 of them > 300 ms): the opening establishment failed closed — 15 because the first visual's word comes > 0.42 s after the sentence starts with no authored evidence, 7 because the first visual is a RESULT — and Boundary (correctly) held the old scene instead of a white canvas. **Fixed 2026-10-16 with the user-authorized `SCENE_SENTENCE_START` authority (RESULT exclusion kept)** |

## 3. Changes (all generic: no package, scene, word or asset conditions)

| File | Change |
|---|---|
| `app/render/renderer.py` | An ordinary outgoing cutout (no planned release, no authored object-handoff target, no authored blur) never drifts: it stays still and leaves on the incoming opener frame. A planned exit moves the cutout completely off the canvas through its nearest side edge (`_offcanvas_exit_offset`). `_restrained_exit_offset` removed |
| `app/boundary/release.py` | `_exit_schedule` plans an exit only when the unit can leave the frame (smoothstep, HERO_TRAVEL cap, projection margin) inside the post-read-hold window, ending on the unchanged opener; the last unit (the semantic result) always stays as cover until the opener. `_hero_overlap_exit` yields (clean cut) when other incoming reveals would arrive while the hero is still leaving — only when the opener is solid (opaque from its first frame, ≥ 2 % of the frame), else the leaving hero stays as cover so no frame turns near-white |
| `app/render/motion.py` | A segment owns the encoded frame it starts on (0.5 ms tolerance on the lower bound) |
| `app/boundary/release.py` (2026-10-16) | Every unit leaves on its own: units decide in order (supporting first), each planned exit is simulated frame by frame against every other outgoing unit at its own pose (still or leaving, alpha footprints); a path that runs over another unit beyond their authored overlap (+2 %) is not planned and the unit leaves with the cut. Audit: `path_blocked_units` |
| `app/motion/emphasis_leader.py` (new) | `EmphasisLeaderPolicy`: per beat at most one Pass2 family grows above authored size, once. Leader = Sprint 4.1 character emphasis › scene hero's settle emphasis › other settle emphasis › (no pulse) PAYOFF subject / scene hero / semantic focus overshoot. Others keep translation and scale-in from below; scale > 1 is lowered to 1; non-leader settle pulses removed with their carried ENTRY; a leader's arrival overshoot is removed when it has a settle pulse. Sprint 4.1 `EMPHASIZE` never removed; de-emphasis (< 1) kept. No keyframe mutation (copies), deterministic |
| `app/pipeline.py` | Runs the policy after all Motion planners (before Text), re-applies it after the post-Text passes, writes `diagnostics/emphasis-leaders.json` |
| `app/motion/hero_travel.py` | `HERO_TRAVEL` back to the authorized 1.0 w/s / 0.40 s. Settle emphasis: 6-frame rest after settle, then rise (35 %) → hold (30 %) → release (35 %) over up to 0.90 s (≥ 0.60 s or no pulse), amplitude 5 % → 3 % (≤ 6 % only where the readability floor needs it). WIP `hold_emphasis` kept; it abstains when the beat already has an emphasis leader |
| `app/motion/resolution.py` | Pop from 0.84 over up to 9 frames on a smoothstep, ≥ 6 frames (else the calm opacity entry), peak scale rate ≤ 1.0 /s (`pop_start_scale`); the PAYOFF secondary pulse abstains when another asset leads the beat |
| `app/motion/arrivals.py` | Slide 0.08 w, 8–12 frames, ≤ 0.6 w/s; smoothstep pops. WIP `_is_nudge` kept; WIP 4-frame slide minimum superseded |
| `app/motion/timing.py` | Encoded-motion QA profiles `REFERENCE_POP` / `REFERENCE_SLIDE` enforce the same calm limits |
| `app/story/windows.py` (2026-10-16) | New opening authority `SCENE_SENTENCE_START` (user-authorized): on a scene's first beat, the first reveal cohort's safe carrier — non-RESULT (role and focus), dependency-free, event order 1 (or no event), CONTEXT/LEADER/PRIMARY/PARTICIPANT — is revealed at the first spoken word of its own sentence even when its own word is > 0.42 s later. Authored evidence (`AUTHORED_EVENT_SPOKEN`/`SCENE_PRELUDE`) keeps precedence. Phrase anchor, semantic peak and settle are unchanged; a RESULT-first scene keeps its timing; later reveals are never pulled forward |
| `app/motion/arrival.py` (2026-10-16) | A semantic segment that starts with an (earlier) reveal but rests until after the bounded arrival now starts when the arrival ends (keyframes keep their absolute times), so it no longer masks the arrival on screen. Found by the encoded-motion gate on White Hat beat 031 (`RENDERED_SEGMENT_INACTIVE`) |

Unchanged: Composition geometry, narration/word timing (only scene-opening reveals moved, §3),
scene order, text placement rules,
Sprint 4.1 character emphasis and de-emphasis, Sprint 7 continuity, projection, FFmpeg
encode settings.

## 4. Measured result (frame-exact probe, final plans `c5` vs WIP baseline `b1`)

| Metric | Black Hat | Bug Bounty Hunter | Cybercrime Gangs | Gray Hat | Hacktivist | Insider Threat | Script Kiddie | Social Engineer | State Linked Group | White Hat | Total |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Mid-motion vanishes (YouTube) | 140→0 | 153→0 | 269→0 | 128→0 | 147→0 | 148→0 | 116→0 | 155→0 | 189→0 | 108→0 | **1553→0** |
| Mid-motion vanishes (Reels) | 140→0 | 151→0 | 268→0 | 128→0 | 147→0 | 148→0 | 116→0 | 154→0 | 188→0 | 108→0 | **1548→0** |
| Complete off-screen exits | 15→10 | 13→1 | 11→2 | 11→5 | 4→2 | 22→14 | 7→5 | 3→3 | 11→5 | 15→12 | **112→59** |
| Above-rest scale events | 77→32 | 57→27 | 123→52 | 59→32 | 39→16 | 87→37 | 66→28 | 55→30 | 103→36 | 55→23 | **721→313** |
| Beats with >1 pulsing family | 18→0 | 11→0 | 19→0 | 8→0 | 4→0 | 18→0 | 15→0 | 9→0 | 23→0 | 9→0 | **134→0** |
| Simultaneous emphasis (s) | 0.333→0 | 0.033→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0.067→0 | 0.067→0 | 0.1→0 | 0.133→0 | **0.733→0** |
| Beats repeating a pulse | 4→0 | 5→0 | 13→0 | 9→0 | 1→0 | 10→0 | 5→0 | 9→0 | 10→0 | 7→0 | **73→0** |
| Frames scale rate > 1.2/s | 69→0 | 71→0 | 66→0 | 79→0 | 71→0 | 93→5 | 73→0 | 96→0 | 132→0 | 54→0 | **804→5** |
| Max scale rate (/s) | 5.563→1.171 | 5.32→0.995 | 5.465→1.121 | 5.949→0.985 | 5.837→0.993 | 5.152→1.696 | 6.592→1.181 | 5.305→1.171 | 5.368→1.024 | 5.514→1.142 | **6.592→1.696** |
| Max travel speed (w/s) | 1.221→0.984 | 1.235→0.949 | 1.231→0.975 | 1.225→0.866 | 1.227→0.851 | 1.224→0.864 | 1.229→0.96 | 1.234→0.903 | 1.224→0.999 | 1.224→0.845 | **1.235→0.999** |
| Frames with 3+ moving families | 118→37 | 161→23 | 199→24 | 105→24 | 112→17 | 110→0 | 93→0 | 175→40 | 184→30 | 114→12 | **1371→207** |
| Beats final hold < 0.5 s | 26→18 | 30→30 | 40→39 | 22→25 | 23→26 | 22→14 | 24→21 | 31→32 | 36→34 | 26→23 | **280→262** |
| Stale previous-scene boundaries | 1→1 | 7→0 | 2→0 | 0→0 | 0→0 | 3→3 | 3→3 | 4→1 | 2→2 | 3→0 | **25→10** |
| Stale previous-scene seconds | 0.233→0.233 | 5.067→0 | 1.1→0 | 0→0 | 0→0 | 1.666→1.666 | 0.967→0.967 | 2.466→0.333 | 0.667→0.667 | 2.1→0 | **14.266→3.866** |

Problem D (2026-10-16 authority, `c3` → `c5`): boundaries where the new sentence plays over the previous scene 25 → 10, 14.27 s → 3.87 s over 10 packages; 7 remain > 300 ms. The 15 targeted beats (Bug Bounty 7, Cybercrime 2, Social Engineer 3, White Hat 3) now open with their first safe carrier on the first spoken word (e.g. Bug Bounty beat 011: the previous scene was held 1.43 s into the new sentence, now the cut is on frame 3). The remaining ones are all kept exclusions: 9 RESULT-first scenes and Black Hat beat 021 (0.23 s), whose first visual depends on another event (order 2). Plans of the other six packages are byte-identical. Glued exits (two different families moving together while overlapping, ≥ 3 frames; `glued.py`): `c3` 1 (Social Engineer 28.1 s, the case the user saw) → final 0 on YouTube and Reels; the final plans are byte-identical with and without the A4 rule (it guards future packages).

Emphasis leaders over 488 beats: scene-hero overshoot 149, hero held pulse 80, Sprint 4.1
character emphasis 38, other settle pulse 16, PAYOFF subject 8, none (calm beat) 197;
291 non-leader overshoots flattened, 6 conflicting pulses removed. Remaining frames with a
scale rate > 1.2 /s (5, Insider Threat) and the 1.12 peak are Sprint 4.1 character emphasis
(protected). Short final holds are mostly narration-locked late reveals (BH: 12 of 18 are a
fade-in of an asset whose word is spoken in the last 0.5 s).

Encoded proof (BH YouTube, mean absolute frame difference before the first scene cuts):
v7 before `[24.5, 37.1, 70.5]` (drift, drift, cut) → after `[0.0, 0.0, 68.2]` (still, still,
cut); likewise at frames 225, 306 and 428.

## 5. Real encodes (production renderer, encoded-motion verifier, mux, final-media gate)

| Package | Target | Encode | Video | Frames (plan / file) | Duration video / container | Audio | Encoded motion | Final media (A/V, white flash) |
|---|---|---|---|---|---|---|---|---|
| Black Hat Hacker | youtube | `encodes-a` | h264 1920x1080 30/1 yuv420p | 2912 / 2912 | 97.067 / 97.067 | aac 44100 Hz | PASS | PASS |
| Black Hat Hacker | reels | `encodes-a` | h264 1080x1920 30/1 yuv420p | 2912 / 2912 | 97.067 / 97.067 | aac 44100 Hz | PASS | PASS |
| Bug Bounty Hunter | youtube | `encodes-c` | h264 1920x1080 30/1 yuv420p | 3309 / 3309 | 110.300 / 110.300 | aac 44100 Hz | PASS | PASS |
| Bug Bounty Hunter | reels | `encodes-c` | h264 1080x1920 30/1 yuv420p | 3309 / 3309 | 110.300 / 110.300 | aac 44100 Hz | PASS | PASS |
| Cybercrime Gangs | youtube | `encodes-d` | h264 1920x1080 30/1 yuv420p | 4581 / 4581 | 152.700 / 152.700 | aac 44100 Hz | PASS | PASS |
| Cybercrime Gangs | reels | `encodes-d` | h264 1080x1920 30/1 yuv420p | 4581 / 4581 | 152.700 / 152.700 | aac 44100 Hz | PASS | PASS |
| Gray Hat Hacker | youtube | `encodes-a` | h264 1920x1080 30/1 yuv420p | 2966 / 2966 | 98.867 / 98.871 | aac 44100 Hz | PASS | PASS |
| Gray Hat Hacker | reels | `encodes-a` | h264 1080x1920 30/1 yuv420p | 2966 / 2966 | 98.867 / 98.871 | aac 44100 Hz | PASS | PASS |
| Hacktivist | youtube | `encodes-a` | h264 1920x1080 30/1 yuv420p | 3423 / 3423 | 114.100 / 114.103 | aac 44100 Hz | PASS | PASS |
| Hacktivist | reels | `encodes-a` | h264 1080x1920 30/1 yuv420p | 3423 / 3423 | 114.100 / 114.103 | aac 44100 Hz | PASS | PASS |
| Insider Threat | youtube | `encodes-b` | h264 1920x1080 30/1 yuv420p | 4204 / 4204 | 140.133 / 140.147 | aac 44100 Hz | PASS | PASS |
| Insider Threat | reels | `encodes-b` | h264 1080x1920 30/1 yuv420p | 4204 / 4204 | 140.133 / 140.147 | aac 44100 Hz | PASS | PASS |
| Script Kiddie | youtube | `encodes-a` | h264 1920x1080 30/1 yuv420p | 2898 / 2898 | 96.600 / 96.600 | aac 44100 Hz | PASS | PASS |
| Script Kiddie | reels | `encodes-a` | h264 1080x1920 30/1 yuv420p | 2898 / 2898 | 96.600 / 96.600 | aac 44100 Hz | PASS | PASS |
| Social Engineer | youtube | `encodes-d` | h264 1920x1080 30/1 yuv420p | 3103 / 3103 | 103.433 / 103.433 | aac 44100 Hz | PASS | PASS |
| Social Engineer | reels | `encodes-d` | h264 1080x1920 30/1 yuv420p | 3103 / 3103 | 103.433 / 103.433 | aac 44100 Hz | PASS | PASS |
| State Linked Group | youtube | `encodes-b` | h264 1920x1080 30/1 yuv420p | 4773 / 4773 | 159.100 / 159.100 | aac 44100 Hz | PASS | PASS |
| State Linked Group | reels | `encodes-b` | h264 1080x1920 30/1 yuv420p | 4773 / 4773 | 159.100 / 159.100 | aac 44100 Hz | PASS | PASS |
| White Hat Hacker | youtube | `encodes-e` | h264 1920x1080 30/1 yuv420p | 2976 / 2976 | 99.200 / 99.200 | aac 44100 Hz | PASS | PASS |
| White Hat Hacker | reels | `encodes-e` | h264 1080x1920 30/1 yuv420p | 2976 / 2976 | 99.200 / 99.200 | aac 44100 Hz | PASS | PASS |

**20 / 20 final outputs pass every gate** (the six packages whose plans did not change keep their `c3` encodes: their `c5` plans are byte-identical and the renderer is unchanged). The first `c4` White Hat YouTube encode failed the encoded-motion gate (beat 031, `RENDERED_SEGMENT_INACTIVE`); fixed in `app/motion/arrival.py` and re-encoded (`encodes-e`). Before/after: `compare\BLACK_HAT_v7_before_LEFT_vs_motionfix_after_RIGHT.mp4` (full, with narration) and `compare\BLACK_HAT_key_moments_slow40pct_before_LEFT_after_RIGHT.mp4`.

## 6. Tests

Full suite on the final tree (`gates/pytest-final3.xml`, idle machine): 10188 tests, 0 failures, 0 errors, 38 skipped (1342 s). ruff, `git diff --check` and `compileall` pass. (The 2026-10-15 run under two parallel encode batches had only the two wall-clock budgets of `tests/test3/test_package_shaped_stress.py` over budget; they pass unloaded.) 2026-10-16 also: `tests/visual/test_vp2_restrained_exit.py` (an exit never runs over another outgoing unit — the Social Engineer man/card case — and the same exit is planned when nothing is in the way).

New: `tests/visual/test_vnext2_emphasis_leader.py` (9), `tests/visual/test_vnext2_exit_pacing.py`
(frame ownership ×4 — fails on HEAD for 3 of 4 frames —, hero exit vs arrivals, faint-opener
cover, no second leader from hold/PAYOFF pulses, QA profile parity). Updated to the new
contract (each assertion kept or strengthened): `test_sprint_4_5_scene_handoffs.py` (unplanned
cut stays still), `test_vp2_restrained_exit.py` (complete exit, result covers, encoded exit
leaves the canvas before removal), `test_vp4_hero_travel.py` (1.0 w/s cap, held pulse shape),
`test_vnext_emphasis_causality_text.py` (5 %→3 % amplitudes, 6 % floor case),
`test_vnext2_arrivals.py` (6-frame pop minimum, smoothstep, no overshoot, ≤ 1.0 /s).
2026-10-16: `tests/test2/story/test_opening_establishment.py` (sentence-start authority for every long-lead case; RESULT, RESULT focus, dependency, event order 2, unordered event, unclassified role and non-first beat stay excluded; the 570a01cb diagnostic is covered without evidence and still fails closed when its first visual is a RESULT), `test_activation_windows.py` (opening beyond the 0.42 s budget), `tests/visual/test_vnext_entry_arrival.py` (a resting segment yields to the arrival with absolute keyframe times kept; a moving one keeps its window; no mutation).

## 7. Remaining issues and decisions

1. **D:** fixed for every non-RESULT, dependency-free opener by the 2026-10-16 authority. Kept
   by design (user: keep the RESULT exclusion): 9 RESULT-first scenes (0.13–0.83 s, 7 above
   300 ms) and one opener that depends on another event (Black Hat 021, 0.23 s).
2. **Sprint 4.1 character emphasis** (38 beats) still peaks at up to 12 % in 0.3–0.6 s without
   a hold (protected certified behaviour). Reshaping it to the new held ≤ 6 % gesture is a
   one-line policy decision for the user.
3. Late narration-locked reveals leave < 0.5 s before some cuts (Story timing, unchanged).
4. Planner in-scene `EXIT` segments (`semantic_release_exit`) are not produced by any real
   package (0 in 10); untouched.
5. Probe near-empty preflight is conservative (box-based); the encoded white-flash gate is
   the authority (§5).

## 8. Recommendation

**READY for visual review** of the corrected motion (A, B, C) and of the scene/narration sync
(D) on Black Hat and the nine other packages: zero mid-motion vanishes, one emphasis per beat,
calm arrivals, every non-RESULT scene opener on its sentence's first word, 20/20 final encodes
passing every gate, full test suite green. **Not a certification** — the user's visual review
decides. Still open: the Sprint 4.1 character-emphasis amplitude (§7.2). Before/after videos:
`compare\BLACK_HAT_v7_before_LEFT_vs_motionfix_after_RIGHT.mp4`,
`compare\BLACK_HAT_key_moments_slow40pct_before_LEFT_after_RIGHT.mp4`,
`compare\SCENE_SYNC_before_LEFT_after_RIGHT_BugBounty011_SocialEng016_WhiteHat028.mp4`.
