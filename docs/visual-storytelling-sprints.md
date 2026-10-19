# HEXA StoryEngine — Visual Storytelling Sprint Tracker

> **REAL-PACKAGE RENDER BLOCKER — ROOT CAUSE FIXED, P0 (2026-10-19):** see section 0 of [Storytelling / Real-Render Failure Handoff](handoffs/2026-10-19-storytelling-render-regression.md) and "P0 production recovery" at the end of this file. `HEXA-diagnostic-f96ba7e0.zip` was triaged: PayoffResolutionDirector replaced a valid Planner PAYOFF with an icon hit that broke the shared floor/comfort contract. Every final target plan now passes encoded-motion QA's metadata contract before any encode. The table there separates code, local tests, synthetic encode, real preflight, real encode and user acceptance.

**Working branch:** `feature/storytelling-sprints` (one branch for ALL six sprints).
**Base snapshot:** `montage` at `624a032c706c6c364b2a2795d67101de15b7ed10` (includes causal-overlap fix).
**Protected branches:** `montage`, `bayer`. Never change, reset, force-push, or merge them.
**Current sprint:** S02 — Four-way visual flow (VERIFIED by synthetic encoded and regression CI; awaiting real-package visual acceptance). Next planned sprint: S03.
**Allowed statuses:** TODO / IN_PROGRESS / VERIFIED / BLOCKED. A sprint is VERIFIED only after required checks pass; report encoding gaps honestly.

| ID | Sprint | Status | Implementation commit | Tests / A-B evidence |
| --- | --- | --- | --- | --- |
| S01 | Authored cross-scene referent and object continuity | VERIFIED | `80a0af96c6c8eb642928911e07a98cb0080839a4` | Synthetic encoded 16:9 and 9:16 A/B passed; affected regression suites passed. No real package media available. |
| S02 | Safe four-direction ENTRY / EXIT with semantic lifetime | VERIFIED (synthetic CI) | `61bb73d3898cdf3d7c37b545b3d4ab8b32e8d13e` | GitHub Actions [run 39170163399](https://github.com/majdba123/HEXA-StoryEngine/actions/runs/39170163399) green: S01, S02 focused FFmpeg encoded vertical exit, causal regressions, broad visual/layer, backward-compatible Final Package; real Black Hat+audio A/B and visual approval pending. |
| S03 | Causal source → action → reaction → result visual interactions | TODO | — | — |
| S04 | Hook selection + primary attention + ordered focus handoff | TODO | — | — |
| S05 | Narration-synchronized visual rhythm, rests, and readable holds | TODO | — | — |
| S06 | Verify/improve existing motion blur and payoff in encoded output | TODO | — | — |

## Delivery protocol

1. Before editing, verify the checked-out branch and working tree; if needed, work in an isolated worktree. Never discard local changes.
2. Read this file plus only relevant code/tests. Implement **one sprint per Codex session**, starting with the first TODO; do not start the next sprint in the same session.
3. Each sprint must change real production behavior (not metadata only), add regression tests, and preserve previous verified sprint behavior.
4. Run targeted tests, then affected legacy/visual suites; check 16:9 and 9:16, frame/audio timing, FFmpeg render and encoded frames when fixtures/media are available. Never claim real-package certification without real media.
5. Record changed files, commit SHA, exact test commands/results, measured before/after behavior and blockers in the corresponding table row. Update status to VERIFIED only if its defined gate passes. Commit and push exclusively to the working branch.
6. Do not modify the Unified Final Package 2.0 schema, fabricate visual semantics, weaken validators, or silently drop causal constraints.
7. Keep the first 10 seconds of a Black Hat reference package as a useful A/B evaluation when the package and audio are actually available; do not hard-code any content-specific behavior.
8. Avoid long prose, blanket codebase dumps, repeated discovery, parallel engines, and artificial movement. Focus on visible narrative improvement.

## Sprint-specific gates

- **S01:** authored referent can persist across adjacent scenes without unwanted disappearance/re-entry; unrelated assets remain separate; boundary safety and text placement hold.
- **S02:** LEFT / RIGHT / TOP / BOTTOM entrance and exit are feasible and tested; selection is contextual; short scenes safely abstain; semantic lifetime and causal-overlap guarantees remain intact; no blank frames.
- **S03:** authored relations yield readable direction of action/reaction/result when renderable; preserve Story event ordering; abstain without evidence.
- **S04:** opening hooks are selected only from authored curiosity/action/contrast/consequence/progressive reveal/continuity evidence; one primary attention target; avoid generic zoom or invented drama.
- **S05:** semantic motion aligns to speech without changing audio timing; resulting frame has adequate readable hold; no competitive simultaneous accents.
- **S06:** inspect and reuse current blur/payoff code; ensure encoded effect is perceptible where warranted, stays comfortable, and has no major render-time regression; do not duplicate effect passes.

**Definition of done:** For each sprint, compare identical inputs baseline vs candidate, show a clear benefit in eligible scenes, enumerate justified abstentions, pass code and integration checks, provide encoded A/B proof if media is available, and declare remaining limitations explicitly.

## S01 verification — 2026-10-18

- Changed `app/motion/cross_scene.py` and `app/pipeline.py`; added regression coverage in `tests/test2/motion/test_cross_scene_continuity.py`, `tests/test2/pipeline/test_cross_scene_transaction.py`, and `tests/test2/render/test_cross_scene_handoff_encoded.py`.
- Authored referent handoffs now replace an in-place successor's fresh pop/slide ENTRY with a stationary opaque ENTRY at the same reveal time. A missing referent can use authored primary attention, geometry, and the existing Motion entry window for a speed-bounded directional lead; it never receives `handoff_from` or a shared identity claim. Every production scene boundary records a semantic/focus decision or an explicit safe-cut reason, with confidence in its diagnostic payload. The existing Text/Boundary transaction can revoke a focus candidate.
- `python -m pytest tests/test2/motion/test_cross_scene_continuity.py tests/test2/pipeline/test_cross_scene_transaction.py -q` (project `.venv`): passed. `python -m pytest tests/test2/render/test_cross_scene_handoff_encoded.py tests/test2/render/test_renderer_handoff_continuity.py tests/test2/motion/test_continuity_contracts.py tests/test2/render/test_transition_regressions.py -q` (project `.venv`): passed. `git diff --check`: passed.
- Encoded synthetic A/B used identical input scenes and FFmpeg at 320×180 and 180×320. The focus carrier's first visible frame moved at least 1.5% of frame width toward the previous focus, while the final encoded centroid matched baseline within one pixel. Existing full-resolution YouTube 16:9 and Reels 9:16 encoded handoff tests passed. Identity-free boundaries with no unique visible focus, unsafe distance/geometry, text/artwork interference, or occupied entry windows retain the certified cut/bridge.
- Limitation: no real package/audio media was present in the checkout, so real-package first-ten-second A/B, audio-sync inspection, and user visual acceptance remain unverified. No S02–S06 changes were made.

## S02 verification — 2026-10-19

- **Implementation baseline:** `61bb73d3898cdf3d7c37b545b3d4ab8b32e8d13e`. Scope: `app/motion/visual_flow/direction.py` (small proposed cardinal attention offsets), `app/motion/arrivals.py` (primary four-way safe slide), `app/boundary/release.py` (four-direction safe hero exit and contextual ordinary exits), `app/render/renderer.py` (execute planned X/Y exits), `app/motion/motion_blur.py` (dominant alpha-footprint shutter when multiple assets move), `app/motion/hero_travel.py` (selective larger scale under existing gates), `app/pipeline.py` (target-projection margins and available assets), `app/motion/cross_scene.py` (S01/S02 authority separation), and `tests/test2/motion/test_scene_flow_s02.py`.
- **Independent verification:** [GitHub Actions 39170163399](https://github.com/majdba123/HEXA-StoryEngine/actions/runs/39170163399), conclusion `success` on the exact implementation SHA. Static checks, S01 encoded A/B, S02 directional entrants/exits/motion-blur and actual FFmpeg-encoded vertical exit, causal-overlap regressions, broad visual/Pass2 regressions and Final Package backward-compatibility tests all passed.
- **Legacy guarantees:** Original scale candidates and defaults kept for non-eligible scenes, held referent exits fail closed, no hard-coded target dimensions, no Final Package 2.0 schema changes, no scene graph or narration timing edits. Short, unsafe or unowned transitions preserve certified fallback.
- **Unverified/acceptance limits:** No real Black Hat package plus voice media was rendered side-by-side or auditioned on this runner; a real package A/B for the opening seconds and user visual quality approval is still required. Eligible entries are restrained slides, not guaranteed full-frame travel on all assets; safety gates deliberately abstain on some boundaries. Do not represent this synthetic verification as proof of a particular real-video aesthetic.

## P0 production recovery — 2026-10-19 (real Black Hat MOTION_BELOW_PERCEPTUAL_FLOOR)

Not a sprint; a blocker fix that must hold before S03. Root cause, evidence and changed files: handoff section 0.

| Evidence level | Status | Detail |
| --- | --- | --- |
| Production code changed | DONE | `app/motion/contract.py` (shared metadata segment contract), `app/render/verification.py` (`preflight`, `require_preflight`), `app/motion/resolution.py` (contract-validated pop / held icon hit, leader-aware), `app/motion/hero_travel.py` (no hold pulse beside a held hit), `app/pipeline.py` (dual-target pre-encode gate), `app/diagnostics/failure_policy.py`, `app/shared/runtime_integrity.py` + `app/desktop/main.py` + `HEXA.bat` + `app/diagnostics/report.py` (runtime/source guard). |
| Failing-first regression | DONE | `tests/test2/motion/test_real_package_payoff_final_plan.py`: real beat-036 fixture through the production downstream chain → RenderPlan → Reels projection → preflight; failed with the exact 0.01188 < 0.01340 on both targets before the fix. Plus `test_payoff_icon_hit_contract.py` (size × window matrix, infeasible keep, leader interaction), `test_runtime_integrity.py`, and a pipeline gate test in `tests/visual/test_roadmap_v2_sprint_1_dual_format.py`. |
| Real-package pre-encode preflight (no encode) | PASSED | Same ZIP/MP3 as the failed job plus White Hat, Gray Hat, Script Kiddie (LastPackge corpus, real narration). Old code: Black Hat 1+1, Gray Hat 2+2 (`MOTION_TOO_FAST` icon hits), Script Kiddie 1+1 (hit flattened to static by the leader policy), White Hat 0. New code: **0 on all 8 target plans**. Scenes, beats, assets, cue sets, story/composition/text/boundaries and every segment window identical to baseline. |
| Local static + regression gates | PASSED | Windows 10 / Python 3.11.9 / FFmpeg 9.0.2, project `.venv`: `compileall app`, `ruff check app tests` clean; CI focused S01/S02/causal lists + new P0 tests passed (one `MemoryError` in `test_motion_blur.py` while Whisper held RAM; 16/16 passed when rerun alone); `tests/visual tests/test2` 1952 collected, 0 failed / 0 errors / 0 skipped; `tests/test1 tests/package_holdouts` 818 collected, 780 passed, 38 skipped (real-corpus certification, run separately below). |
| Real-corpus certification Levels A–D | PASSED | `HEXA_REAL_PACKAGE_CORPUS` = local `_CERTIFIED_UNIFIED_2_0_CORPUS` (SHA-256 verified against `Bayer_Packages/unified_2_0_certified_corpus.json`, 6 packages): 39 tests, 33 passed, 0 failed, 6 skipped (Level E full-length encodes are opt-in). These levels use deterministic transcripts, not narration audio. |
| Real encoded acceptance (both targets) | PASSED | `generate_bundle` (production settings) on `4d125b42`, clean tree, same ZIP (fingerprint `0e65914c…`) and MP3 as the failed job: bundle `E:\HEXA_Exports\HEXA_BLACK_HAT_HACKER_AR4`, YouTube 1920×1080 and Reels 1080×1920, 2912 frames, 97.059 s audio / 97.067 s video, encoded-motion PASS and final-media PASS on both, 768.5 s total (pre-encode gate at 342 s). |
| Encoded A/B (YouTube, same inputs) | MEASURED | Whole video vs the user's failed encode (job f96ba7e0): 2876 of 2912 frames identical; the 36 changed frames all lie in 82.667–83.833 s (beat-036). Result icon scale per frame (NCC ≥ 0.994): before 1.025 → 1.045 → 1.07 ×3 → 1.04 → 1.00 (2-frame return); after 1.04 → 1.07 → 1.08 ×3 → 1.035 → 1.01 → 1.00 (3-frame return). The fix is a correctness fix, not a broad visual upgrade. |
| GitHub Actions (exact SHA) | PASSED | [Run 39250352081](https://github.com/majdba123/HEXA-StoryEngine/actions/runs/39250352081) on `075c730506f1cc559f4eb0b40e6f5f1c7f28ac4d`: static, S01, S02, causal, broad visual/test2, Final Package compatibility + holdouts all `success`. The earlier run 39248664966 on `4d125b42` failed in the broad step: a new runtime-integrity test hard-coded the Windows `\.` suffix; fixed in `075c7305` (test only). Synthetic CI does not replace the real-package evidence above. |
| User visual acceptance | PENDING | Requires the user to watch the encoded bundle. |

### P1 audit (real Black Hat final plan, YouTube, after P0) — measured, not yet changed

- 149 independently entering assets: 104 (70 %) carry ≥ 6 px of authored entry motion; 45 appear by fade/pop-in, 35 of them because Story's reveal→settle window is < 0.20 s (ReferenceMotionEnforcer keeps such entries static by design).
- Visible-entry directions: BOTTOM 36, RIGHT 12, LEFT 8, TOP 3, scale-only 45; 75 progressive-scale entries; 73 motion-blurred cues.
- Scene exits: 37 of 39 boundaries are HARD_CUT; only 9 hero full-frame exits. Downgrades: opener collides with outgoing artwork 24, overlap window insufficient 9, protected motion 6. The incoming opener typically appears ~3 frames into the scene (release needs ≥ 5). Outgoing scenes hold still a median 0.38–0.56 s after their last motion across the corpus; only 3–6 boundaries per package have ≥ 0.9 s, so tail exits would consume read-holds (user decision).
- PAYOFF accents (23): 11 reference pops (0.84→1.0), 1 held icon hit, 9 vertical lifts, 2 lateral nudges (beat-017, beat-038).
- Held icon hit feasibility: relaxing the old fixed `seconds >= 0.29` gate to "whatever the shared contract allows" adds only one hit per package (corpus 1→4), all QA-valid; 8–19 per package abstain with `no_comfortable_hold` because a 7 % boom on a ~0.2-frame icon needs ≥ 0.127 s per ramp under the 0.11/s PAYOFF comfort ceiling while PAYOFF windows are 0.25–0.32 s. A held peak for most results needs either a longer accent window past Story's settle instant or a higher comfort ceiling: a contract decision for the user, not tuning.

## P1 cinematic visual recovery — 2026-10-19 (after the user rejected v4's look)

Owners changed: `app/motion/arrivals.py`, `app/motion/resolution.py`, `app/motion/planner.py`,
`app/motion/visual_flow/direction.py`, `app/motion/timing.py` (details: handoff, P1 section). No speed ceiling raised,
no Story instant moved, every new program validated by the shared P0 contract; pre-encode and encoded QA unchanged.

| Evidence | Baseline v4 | P1 | How measured |
| --- | --- | --- | --- |
| Observable directional entrances (Black Hat, 149 entering assets) | 34 (23 %) | 68 (46 %) on v5 and on final v6 | NCC tracking of every entering asset in the decoded YouTube MP4 (≥ 40 px travel while visible) |
| Fade-only appearances | 78 (52 %) | 57 (38 %); 38 of them have Story windows < 0.2 s | same tracker (fade does not move an NCC match) |
| Encoded directions L / R / B / T | 17 / 8 / 5 / 4 | 24 / 16 / 18 / 10 | same tracker, direction of first visible offset |
| Opening travel lock / shield / character | 0 / 3 / 2 px | 77 (LEFT) / 161 (RIGHT) / 94 (BOTTOM) px, growing 0.93 → 1.00 | tracker on the real opening encode |
| Strong planned directional entrances (≥ 77 px), corpus | 6–12 % | 38–40 % | plan audit, all four packages |
| Lateral PAYOFF nudges, corpus | 5 | 0 | plan audit |
| Broad grey/defocus windows reported by the reviewer | not present in v4 (sharpness ratio 0.86–1.20, saturation 0.91–1.30 vs context) | unchanged | Laplacian/saturation per frame; the reviewed file's SHA differs from v4 |
| Pre-encode QA, corpus × 2 targets | 0 | 0 | `EncodedMotionVerifier.preflight` |
| Real dual-target render | v4 PASS | v5 (`4546c3a5`) PASS; final **v6 (`13bba594`) PASS**: YouTube + Reels, 2912 frames each, audio 97.059 s / video 97.067 s, story/choreography/text fingerprints identical to v4 | production `generate_bundle`, encoded-motion + final-media QA |
| Local gates on `13bba594` | — | static clean; `tests/visual tests/test2` 1963 / 0 failed; `tests/test1 tests/package_holdouts` 818, 780 passed, 38 corpus-only skips; real-corpus certification A–D 33 passed, 6 opt-in Level E skips | junit |
| Evidence sheets | — | `E:\HEXA_Exports\_P1_EVIDENCE_2026-10-19\` (v4 vs v5/v6, same timestamps) | decoded frames |

Measured limits (not tuned away): 38 fade-only assets have Story windows of 0.08–0.19 s (below the 6-frame minimum);
held icon hits stay rare because a 7 % boom needs ≥ 0.127 s per ramp under the 0.11/s PAYOFF ceiling in
0.25–0.32 s windows; ~39 corpus assets carry an authored relation accent overlapping a carried ENTRY in their first
0.4 s; 37/39 Black Hat boundaries remain cuts because incoming openers appear ~3 frames into the scene. User visual
acceptance is pending.

## Reference-driven cinematic rebuild (C0–C5) — 2026-10-19/20 (after the user rejected v6)

Grammar measured from the two approved references: `docs/reference-motion-grammar.md` (G1–G13). Commits:
`6bb467e7` C0+C1, `c6a2691f` C3, `cf0f2af1` C4, `12b2d1fc` scene-opener fix found by Level 5. C2 was dropped
(no visible effect; see below). No Story instant, narration, final position, asset or text changed.

| Evidence | v6 | Rebuild (v8, `12b2d1fc`) | How measured |
| --- | --- | --- | --- |
| C1 opening entries | lock 77 px, shield 161 px, in-frame starts | lock from beyond LEFT, shield from beyond RIGHT, ease-out, blur while fast | decoded opening encode |
| C3 authored arrows/paths | faded in place (full extent from the first visible frame) | drawn along their causal relation: beat-029 leading edge 141→583→903→1153→1235 px over 8 frames; beat-022 arrow in its 4-frame settle window | decoded ROI per frame |
| C3 generated connectors | 0.2 s opacity fade | 8-frame write-on, last frame == complete arrow | unit + encoded test |
| C4 relation results (corpus 4 cues) | 1.0→1.03→1.0 pulse while fading in place | one edge arrival + 0.93→1.0 growth on REACT and PAYOFF; beat-005 moneybag solid at 11.40 s vs 11.50 s | decoded gold-pixel track |
| Decoded entering assets (YouTube, 149) | DIRECTIONAL 68 / FADE_ONLY 57 | 68 / 56; mean travel 134→146 px; ≥ 300 px entries 2→9 | NCC tracker |
| Rhythm, first 65.5 s | moving 0.563, median motion run 8 f, 0 beats with ≥ 1 s still | 0.559, 8 f, 0 | `ref_profile.py`, `beat_audit.py` (references 0.51/0.79, run 13 f) |
| Preservation (8 corpus plans) | — | Story, text, assets, final positions, duration, audio byte-identical | plan diff |
| Pre-encode QA, corpus × 2 targets | 0 | 0 | `EncodedMotionVerifier.preflight` |
| Level 5 dual-target render | v6 PASS | first attempt REJECTED (near-white cut frame 71.533 s, beat-032) → fixed → **v8 PASS**, YouTube + Reels 97.059 s, encoded-motion + final-media OK, 743 s total | production `generate_bundle` |
| Local gates `12b2d1fc` | — | ruff clean; web 63, test1 738 (38 corpus skips), test2 1617, test3 814, certification 6725, holdouts 80, visual 355 — 0 failures; certified real corpus 355 / 0 failed (6 opt-in Level E skips) | junit |

Measured limits: global activity density is unchanged (the gap to the references is whole-character relocation
between ideas, which needs Story/read-hold authority); boundaries stay authored holds that end on the opener
(fading them early would erase authored visibility); 26/34 authored relations are touching pairs with no path
art (no connector is invented); write-ons inside settle windows < 8 frames are fast (beat-022: 4 frames); YouTube
encode +14 % (geq masks). User visual acceptance is pending.
