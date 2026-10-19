# HEXA StoryEngine — Storytelling / Real-Render Failure Handoff

## 0. RESOLUTION UPDATE — 2026-10-19 (P0 production recovery)

This section supersedes "root cause UNKNOWN" below. Sections 1–7 are kept as history.

**Diagnostic inspected.** `HEXA-diagnostic-f96ba7e0.zip` (report.json, report.md, workspace-manifest.json) and the
job's retained work directory `.hexa/work/f96ba7e0…` (real final `render-plan.json` for both targets, stage diagnostics).
Job `f96ba7e0452e4937918fca085fb59ade`, commit `65f44df`, YouTube encoded, then `MOTION_BELOW_PERCEPTUAL_FLOOR`
`beat-036` / `SCENE_036:asset-04` / PAYOFF, 0.01188 < 0.01340.

**Root cause (proven).** `app/motion/resolution.py` `PayoffResolutionDirector._pop()` replaced the complete PAYOFF
program that `MotionPlanner` had already validated with a fixed icon hit (1.00 → 1.07 → 1.07 → 1.00, return in 23 % of
0.3 s). It checked only a pixel threshold computed from a start scale it then discarded. Violated invariant: *a downstream
pass that replaces a semantic segment program must satisfy the same shared readability/comfort contract that encoded QA
applies to that segment.* Evidence from the real package re-planned on this machine (identical counts: Pass1 149 / 40
scenes, Pass2 167, 40 beats), fingerprinting the asset after every pass:
- `MotionPlanner.plan`: PAYOFF `reference_result_enter`, scale 1.075 + upward dy −0.01340 → activity 0.01340 ≥ floor
  (the previous `_enforce_event_readability` patch DID run and was valid).
- `PayoffResolutionDirector.plan`: program replaced by `reference_icon_hit_payoff`, dy 0, peak 1.07 →
  0.07 × 0.16977 (item width) = **0.01188**. Its 2-frame return also ran 0.172/s against the 0.119/s PAYOFF ceiling
  (masked because QA reports the first violation per segment).
- Every later pass, RenderPlan compile and the Reels projection left it unchanged; YouTube and Reels failed identically.
- Floor: segment 0.31895 s → comfort budget 0.31895 × 0.382 × 0.11 = 0.01340.
- The earlier regression passed because it called the Planner directly with an inferred item width (0.1584 × 0.075
  coincidentally also equals 0.01188); it never ran the downstream chain.
- Engine-level, not package-specific: the old `_pop()` produced a QA-rejected program in 8 of 12 cases of a
  size/duration matrix (every icon hit on an asset wider than ~0.12 of the frame broke `MOTION_TOO_FAST`).
- The failure was detectable before encoding: the metadata-only half of `EncodedMotionVerifier.inspect()` run on the
  real final plan reproduces it exactly, ~2.5 minutes of YouTube encode earlier.

**Runtime/source check (no defect in the failing run).** The worktree's `.venv` is a directory junction to the main
checkout's venv; the diagnostic resolves the junction, so it showed the main checkout's `pythonw.exe`. The executed code
was the worktree at `65f44df` (traceback paths and line numbers match). Latent hazard found: that venv's editable install
points at the protected `bayer` checkout, so any launch outside the worktree directory (or the `hexa-desktop.exe` console
script) imports `bayer` code. Guard added (below).

**Fix (production files).**
- `app/motion/contract.py` (new): the single metadata segment contract (activity, peak speed, authorized comfort
  profile, accent floor, pixel floor) shared by authoring and QA; no new thresholds.
- `app/render/verification.py`: metadata phase extracted to `_analyze_plan`; new `preflight(plan)`; `inspect()` uses the
  same analysis; `require_preflight()` fails closed with per-violation program evidence (`PRE_ENCODE_MOTION_CONTRACT_FAILED`).
- `app/motion/resolution.py`: the held icon hit is built for its real window (peak = max(1.07, that window's floor),
  capped at 1.08; ramps keep the comfort ceiling) and every pop/hit replacement is validated with the shared contract
  before it may replace the Planner program; fallback order hit → reference pop → keep the Planner's validated program,
  with the reason recorded in `payoff-resolution.json`.
- `app/pipeline.py`: pre-encode motion QA for every final target plan (YouTube and Reels) after planning/projection and
  before the bundle is reserved or any encode starts; also on the legacy single-target path. Encoded QA after render is
  unchanged.
- `app/diagnostics/failure_policy.py`: `PRE_ENCODE_MOTION_CONTRACT_FAILED` (owner motion, PREVENT).
- `app/shared/runtime_integrity.py` (new), `app/desktop/main.py`, `HEXA.bat`, `app/diagnostics/report.py`: the
  launcher declares its checkout; the app refuses to start if it imported another one; diagnostics record the imported
  source root, the invoked interpreter and the editable-install target.

**Real Black Hat result (same package + MP3 as the failed job, no encode):** baseline code → 1 violation on each target
(the exact production failure); fixed code → **0 violations on YouTube and Reels**. Exactly one of 167 cues changed per
target (`SCENE_036:asset-04` PAYOFF: 1.00 → 1.079 → held → 1.00, ramps 0.122 s); story, composition, text and
boundaries are identical. Corpus and encoded acceptance: see the P0 evidence table in `docs/visual-storytelling-sprints.md`.

---

**Checkpoint:** 2026-10-19, after the user's SECOND post-fix Black Hat export failure.
**Repository:** `majdba123/HEXA-StoryEngine`.
**Only authorized working branch:** `feature/storytelling-sprints`.
**Verified working-branch GitHub HEAD before writing this handoff:** `65f44df210da9438c179fa3e76ecbd646b6e8f1e`.
**Protected branches:** `montage`, `bayer` — DO NOT edit, reset, merge, force push, or deploy.
**Current state: BLOCKED — real Black Hat package has failed again after green synthetic CI. NOT released/approved.**
**Priority:** Diagnose the newest user-attached diagnostic ZIP BEFORE additional motion redesign or another user export attempt.

> This active handoff overrides any older 'S02 VERIFIED' claim for *real-package production readiness*. The sprint tracker uses 'VERIFIED (synthetic CI)' and does not certify actual Black Hat A/V export. Preserve the distinction between code/CI pass and true product acceptance. Do not misrepresent a green Actions run as a successful real export.

## 1. Why this handoff exists / latest user report

The user specifically required: no broken code, no lost scene or object, improved continuity and attractive four-way entry/exit, perceivable smoothly growing high-scale and icon-centred payoff, with Black Hat 16:9 and 9:16 export. The assistant repeatedly reported readiness on green CI, but on the user's own Windows machine, **real Black Hat generation failed twice after substantial processing**. The user is understandably dissatisfied. No further unqualified 'ready to render' or 'nothing broke' promises.

### LATEST user diagnostic (TOP PRIORITY; untriaged)

- Filename exactly **`HEXA-diagnostic-f96ba7e0.zip`**; attached by the user in the conversation on **2026-10-19** after updating to a version including the previous payoff fix.
- In that conversation the local mount was provided as `/mnt/data/HEXA-diagnostic-f96ba7e0.zip`.
- **Contents NOT INSPECTED.** Attempts via Python and container tools returned an internal `ServerError`; do **not** infer its root cause, affected asset, stage or new failure code from the previous report. The diagnostic may need to be reattached if the new chat cannot access the original conversation file.
- First task for next assistant: extract and read its manifest, failure JSON, traceback/stage logs, exact Git SHA/config/target if recorded, and compare with code. Then report evidence-based root cause and a bounded fix.
- Before asking the user to repeat the 11-minute export, build/run an exact failure reproduction and a **whole-package both-target pre-encode plan+QA pass** where feasible. Never silently bypass/loosen validators.

### PREVIOUS diagnostic (distinct, prior bug, addressed at code level)

- Filename `HEXA-diagnostic-4f865cc1.zip`, also attached in prior conversation.
- Analysis found **`MOTION_BELOW_PERCEPTUAL_FLOOR`** for **`SCENE_036:asset-04`**, PAYOFF, expected normalized activity `0.01188` vs minimum `0.01340`, reported after ~11 minutes. This was NOT an E-drive, FFmpeg install, or narration file path issue.
- Underlying conflict in `app/motion/planner.py` `MotionPlanner._enforce_event_readability`: for zero-translation PAYOFF, the code boosted scale by a fixed `0.075 * temporal_gain` but did not re-check the shared normalized perceptual floor after that boost; a small asset can fail even though keyframe motion is nonzero.
- Patch on working branch ensures PAYOFF passes `max(hypot(dx,dy), abs(scale-1)*min(item.width,item.height)) >= floor` before it reaches FFmpeg, with scale prioritization and safe fallbacks or an early `StageFailedError` if impossible; it does NOT suppress QA. Regression added `tests/test2/motion/test_real_package_payoff_readability.py`. Earlier diagnostic's arithmetic was reproduced/corrected in this regression.
- Last independently verified CI **green** at exact code HEAD `65f44df210da9438c179fa3e76ecbd646b6e8f1e`: [GitHub Actions 39227591345](https://github.com/majdba123/HEXA-StoryEngine/actions/runs/39227591345), all static, S01/S02, causal, broad visual/test2 and Final Package backwards-compatibility steps passed.
- **CRITICAL:** That successful CI did not prevent the subsequent new user failure. Do NOT call the last green run a real-package certificate.

## 2. User intent and aesthetic acceptance criteria

The desired result is **a single continuous visual canvas**, not independent slides/PowerPoint. Retain every original Final Package scene, ordering, narration duration, all required visual objects and causal events. The user reported an approximately 97-second Black Hat preview in which motion and payoff were *not* visibly improved enough:

- Only about **20%** of objects seemed to enter/exit; too many cutouts appeared abruptly.
- Opening scene: objects should enter from LEFT/RIGHT; other scenes need TOP/BOTTOM as appropriate, and old object departure must flow into next object entrance.
- Supporting hacker/secondary characters at utterances like 'بدل ما يبحث عن الثغرة عشان يقفلها', 'يبحث عنها عشان يستفيد منها', 'ممكن يكون الدافع', 'أحيانا يبدأ الموضوع', 'كلمة مرور ضعيفة' should enter smoothly from LEFT when appropriate, not wiggle/jitter and stop or simply pop into view.
- At 'قبل ما حد يكتشفوا', objects beside the hourglass should enter from TOP/BOTTOM rather than abruptly appearing.
- At 'السيطرة على أجهزة', objects had insufficient still hold/readability; cards appeared too rapidly one after another without smooth motion and settling.
- Payoff for moneybag, electronic part/chip, password/key, and 'إذا وصل إلى حساب موظف' was described as ugly side-to-side shaking/repeated attention refocus. User wants **one purposeful icon-specific scale 'boom' with clear held peak and settle**, not a grey wash of the whole scene or unrelated camera shake.
- **Scale entry:** ease from about 93% toward final 100% over the allowed motion window, then REST/HOLD; qualifying payoff may emphasize up to ~107% after safe collision/readability checks. Avoid rapid 93 -> 107 jumps.
- Motion blur should emphasize actual dominant alpha-visible icon only where useful, but must remain comfortable (no global smearing or another render pass).
- Fail-closed: if semantic safety, speed, collision, text occlusion, family rigidity, continuity, or too-short beat block a flourish, preserve an intentional clean cut and all content.

**Aesthetic acceptance must be measured using rendered output of the SAME real package and audio; merely asserting animation params in code is not proof.** Need both YouTube 16:9 and Reels 9:16.

## 3. Relevant architecture / protected contracts

`Unified Final Package 2.0 (immutable input) -> Vision/Pass1/Pass2 -> Story/forced alignment -> Choreography -> Composition -> Motion + Boundary -> RenderPlan -> FFmpeg -> encoded QA and versioned export`.

- Story owns narration, semantic activation, timing; Choreography owns cause/interaction/reaction/result; Composition owns final geometry (do not reposition artwork to animate); Motion owns trajectory, rest/holds, comfort; Boundary handles exit/lifetime; renderer consumes *one* RenderPlan.
- Authored `referent_id` identity only; never infer cross-scene object identity from visual similarity alone. Missing referents should not shut off safe scene-flow animation.
- No dropping/reordering/conflating scenes, no changing original spoken timestamps, no fake object relations, no Pass3, no second renderer, no duplicate text/boundary authoring or extra transcoding pass.
- Protected output variants share semantic plan, target-specific projection safety; 16:9 and 9:16 both required.
- Preserve `HEXA_PROJECT_CONTINUITY_SOURCE.md` accepted architecture and `docs/visual-storytelling-sprints.md` sprint rules.
- Important user constraint: **commercial production code, small verified fixes, not large speculative refactors; user loses ~11 minutes per late failure.**

### Main implementation touched in S01/S02 and fixes

- `app/motion/visual_flow/direction.py`: safe cardinal scene focus and nearest-edge directions.
- `app/motion/arrivals.py`: four-way independent arrivals, 0.93 -> 1.0 scale, safety gates.
- `app/boundary/release.py`: four-way exit path planning; held referent/causal safety; projection margins.
- `app/render/renderer.py`: encoded X/Y exit rendering, bridge and motion blur.
- `app/motion/motion_blur.py`: dominant alpha-visible footprint emphasis.
- `app/motion/hero_travel.py`: selectively stronger lead emphasis, legacy default preserved.
- `app/motion/resolution.py`: icon-focused payoff, optional 1.07 held peak, avoid scene-wide wash.
- `app/motion/planner.py`: semantic events, exact PAYOFF readability contract (previous bug fix).
- `app/motion/cross_scene.py`: S01 authored identity vs S02 visual-flow precedence.
- `app/pipeline.py`: precise plan target/verification ownership and old authoring guards.
- `app/render/verification.py`: encoded motion/readability QA; **do not weaken thresholds**.
- `app/motion/timing.py`: shared minimum speed/readability/comfort rules.
- `app/desktop/main.py`, `app/desktop/export_preflight.py`: one-time Windows export-root config into ignored `hexa.settings.json`; default `E:\\HEXA_Exports` if no explicit export setting. Preserves env/other settings, fails visibly if E drive unavailable. Does not move work/cache to E by implication.

### Test locations

- `tests/test2/motion/test_scene_flow_s02.py`: 4-way entrants/exits, blur, scale, encoded visual A/B, short vertical speed.
- `tests/test2/motion/test_real_package_payoff_readability.py`: previous scene-36 failure contract.
- `tests/visual/`, `tests/test2/`: broad motion/layer regressions.
- `tests/test1/`, `tests/package_holdouts/`: package backwards-compatibility.
- Workflow `.github/workflows/s01-independent-verification.yml`: static, S01, S02, causal, broad visual, package holdouts. **Synthetic CI only; NOT actual production corpus certification.**

## 4. Verified development history / status timeline

- `feature/storytelling-sprints` derived from `montage` snapshot `624a032c706c6c364b2a2795d67101de15b7ed10` with protected branches left untouched.
- S01 authored referent/focus continuity: synthetic VERIFIED (see sprint tracker).
- S02 initial four-way motion/exit and blur: green synthetic CI `39170163399`, code `61bb73d...`; user later reported minimal visible difference.
- Subsequent broadened motion, scale/payoff changes and same-branch regression improvements: CI green `39220480529` but real export later failed, showing coverage gap.
- Windows E export-root first-run fix: `app/desktop/` + tests; CI green `39222908482` on `9875fbb86e62a4f6d5a5b22f25d06b86decdd1b9`.
- Previous real scene-36 PAYOFF bug patch: `app/motion/planner.py` + regression test; CI green `39227591345` on `65f44df210da9438c179fa3e76ecbd646b6e8f1e`.
- **AFTER that green run:** user supplied a NEW real export failure `HEXA-diagnostic-f96ba7e0.zip`. **New root cause UNKNOWN**, because attachment extraction tools were unavailable in this handoff turn. That is the current blocker.
- No later production bugfix is verified. No acceptance of Black Hat real render or reliable 'ready' declaration yet.

## 5. Next-assistant action order (do not skip)

1. **Read this file first.** Inspect HEAD and recent GH Actions on `feature/storytelling-sprints`; read latest changed areas, tracker and protected contracts. Do not interpret old green CI as acceptance after the new failure. Keep `montage` and `bayer` untouched.
2. **Obtain and inspect** `HEXA-diagnostic-f96ba7e0.zip`; try mounted conversation attachment first. If not accessible in new conversation, **ask the user to attach it**. Extract full failure stage, traceback, QA issue code, asset/beat, rendering target, any generated intermediate diagnostics, and configuration. DO NOT assume previous PAYOFF issue repeated.
3. Cross-reference reported failure with real production path and identify why previous CI did not catch it. Find a minimized deterministic regression from the report, preferably at exact real plan/asset/beat values. Add a production-path integration verification (both targets where feasible) **before encode** so late motion QA failures are detected early. Keep fail-closed semantics, don't lower validator thresholds, don't skip encoding verification.
4. Patch root cause, with minimal change and explicit fallbacks. Preserve all 40 authored Black Hat scenes and 129 assets, ordered delivery, geometry, output format, text, cue/audio sync, collision/family protections. Do not hard-code scene 36 or hacker content in production policy; package-specific scenarios belong in tests only.
5. Run focused test, exact regression, whole broad CI (S01/S02/causal/visual+test2/test1/package holdouts). **Synthetic CI still insufficient**: if real package and audio can be mounted, run actual full-package preflight then full 16:9+9:16 encode with frame/audio verification and compare with previous output. If inaccessible, declare limitation and ask only once for needed files, never promise a 100% success.
6. Only when genuinely verified, commit/push to existing `feature/storytelling-sprints`. Provide SHA, specific tests and evidence. Ask user to `git status --short` then `git pull --ff-only origin feature/storytelling-sprints` and test a complete dual-target Black Hat render. No blind edits to local user checkout, no changes to protected branches.
7. After user shares video, inspect actual visual entry/exit usage, ease and hold, icon-specific payoff, blur and narration. This is user-acceptance, independent of code safety.

## 6. User Windows run context

Local VS Code PowerShell working directory was shown as
`C:\\Users\\INTEL CENTER\\Documents\\GitHub\\HEXA-StoryEngine-montage-consolidation` with active `feature/storytelling-sprints`. User launches `.\\HEXA.bat`. Windows desktop app takes Final Package ZIP and MP3, generates YouTube + Reels versioned bundles. User requested final exports on drive `E:`. Latest known ZIP pathname included `BLACK_HAT_HACKER_AR_UNIFIED_FINAL_PACKAGE_2_0_UNVERIFIED(1).zip`. Do not trust filenames or paths as current until reconfirmed.

If user has local changes, don't instruct a destructive checkout/pull. The requested action right now was **documentation/handoff only** — no new program changes were authorized in this handoff response.

## 7. Plain-language status for the user

'آخر GitHub CI ناجح على النسخة السابقة، لكن الرندر الحقيقي فشل بعدها. التعديل السابق حلّ حالة الـPayoff المعروفة، أما تقرير الخطأ الأخير فلا يزال غير مفحوص. أول خطوة بالمحادثة الجديدة فحص ZIP التشخيص الجديد، ثم إصلاح سببه مع اختبارات تمنع إضاعة وقتك بالرندر. لا تعمل Pull أو تعيد الرندر لغاية ما نراجع هالخطأ.'

Do not claim to have inspected the new ZIP or proved the latest fix. Do not claim continuous background monitoring unless an actual automation is configured.
