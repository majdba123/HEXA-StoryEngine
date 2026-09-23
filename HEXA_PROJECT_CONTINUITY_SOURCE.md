# HEXA PROJECT CONTINUITY SOURCE

## OFFICIAL CURRENT CHECKPOINT

Last updated: 2026-09-19

This file is the operational handoff for the HEXA StoryEngine project. It is authoritative for the current accepted baseline.

### Current accepted baseline

- Baseline name: Montage11 / Bayer baseline
- Functional scope: Pass1 + Pass2 extraction/refinement only
- Layer3 / Pass3: REJECTED and NOT part of the accepted product baseline
- Accepted source commit before this documentation-only checkpoint:
  - `a983ea44a9b295b8d4e7ab6d567f88e79f01ec23`
  - message: `[montage11] Generalize Pass2 separation and strengthen V7 presentation`
- Source tree: `c2f880ba0e0b81fde99329cc34d34b38ec4a92fa`
- At recovery time, branches `majd` and `bayer` were identical at the source commit above.

### CI proof for the accepted source

- `majd` CI run: `35397632207` — SUCCESS
- `bayer` CI run: `35402644424` — SUCCESS
- Workflow: `V2 CI`
- Official GitHub Actions source artifact:
  - `hexa-storyengine-source-a983ea44a9b295b8d4e7ab6d567f88e79f01ec23`
  - artifact id: `10569495135`
  - SHA256: `9421f62d450b33c6e33451be1535bdedd4a1528ea4fc7ec85c460f3390d37512`

### Accepted render reference

- Filename: `HEXA_BAYER_MONTAGE11_BASELINE.mp4`
- SHA256: `67b5733d89ee41d9f45aa2e27c2d8548bd39895900351c9612e8570b0674520b`
- Resolution: 1920x1080
- Frame rate: 30 fps
- Duration: 102.4 s
- Video codec: H.264
- Audio codec: AAC

This render is the visual regression reference for current work.

## HARD DECISIONS

1. Do not use any Layer3 / Pass3 implementation, experiment, dataset render, overlay system, host reconstruction experiment, or high-sensitivity third-pass extraction in production.
2. Do not use any post-Montage11 experimental render as a baseline.
3. Pass1 and Pass2 behavior, composition ordering, motion ordering, synchronization, and rendering behavior are protected baseline behavior.
4. New work must begin from the accepted Montage11/Bayer source, not from local experimental snapshots.
5. If a future change alters composition, ordering, timing, alpha extraction, motion, or render behavior, compare against the accepted baseline render before accepting it.
6. Layer3 may only be reopened if the user explicitly requests it again. Until then it is considered permanently out of scope.

## REJECTED EXPERIMENTAL LINE

All Layer3 / Pass3 work performed after the accepted Montage11/Bayer baseline is rejected, including experiments that caused:
- composition reordering,
- elements entering or overlapping each other,
- rectangular clearing/cropping,
- host damage,
- semantic over-segmentation,
- shadow/ghost artifacts,
- unstable family motion.

None of those experimental outputs may be treated as a source of truth.

## CURRENT PROJECT POSITION

We are back on the stable Montage11 architecture:
`Final Package -> Vision -> Pass1 -> Pass2 -> Story -> Composition -> Motion -> Render -> QA`

There is no accepted third extraction layer.

The next engineering work must improve or extend the product without changing this baseline unintentionally. Any extraction improvement should be made inside the existing Pass1/Pass2 architecture or behind an explicit opt-in experiment that cannot affect the accepted baseline.

## BRANCH POLICY FOR THIS CHECKPOINT

After this handoff update, `majd` and `bayer` must point to the same documentation-only checkpoint commit. The application code in that commit must remain identical to source commit `a983ea44a9b295b8d4e7ab6d567f88e79f01ec23`; only this continuity document is added.



## MONTAGE12 FINAL-PACKAGE GEOMETRY CONTRACT — 2026-09-21

Development branch: `majd`.

This change starts directly from the protected Bayer/Montage11 checkpoint
`7218814e3ecd62370feb0588b143e00fc0d14c18` and does not modify `bayer`.

Final architecture contract:
- The Final Package scene image is the authoritative spatial composition.
- Pass1/Pass2 may separate movable visual assets, but separation must not grant
  Composition permission to redesign the scene.
- Every asset with valid `source_bbox/source_canvas_*` is mapped directly back to its
  authored scene geometry. Asset count does not change the position of existing assets.
- Story owns narration/audio timing, semantic activation, primary/support intent and
  sequencing. Story no longer drops dense-scene assets merely because there are more
  than six.
- Composition owns final destination only. Authored geometry is locked; only
  geometry-less legacy/fallback assets may receive bounded repair.
- Text is placed after visual geometry is locked. It searches real alpha negative space
  and may reduce its own scale down to a readable floor; visual artwork is never moved
  to make room for text.
- Motion owns the path to the Composition destination. Cross-artwork semantic handoff
  morphing is disabled; only the same asset receives positional continuity. Motion
  amplitude decreases as scene density rises and always settles at Composition.
- Desktop UI includes a visible Log panel and a persistent `generation.log` for each
  job. Pipeline progress records Pass1/Pass2 counts, beat/density information,
  Composition/text placement state and Authoring QA outcome.
- Authoring QA checks visual layout, text-vs-alpha layout, text-vs-text overlap and
  short directional motion. QA never repairs authored artwork by re-layout.

Real-package validation before publication:
- accepted insufficient-balance package: 49 beats / 96 assets / 21 text cues;
  0 visual layout violations, 0 text layout violations, 0 motion violations.
- white-hat-hacker package: 35 beats / 133 assets / 2 text cues;
  forced alignment 220/220 words;
  0 visual layout violations, 0 text layout violations, 0 motion violations.
- both full renders completed at 1920x1080 CFR 30fps with successful full decode checks.
- generated videos remain review artifacts until user visual approval; Bayer remains the
  protected historical visual baseline.

Operational rule:
- Users may run `HEXA.bat`, choose a Final Package ZIP plus narration audio, and press
  Generate. Production generation must not bypass forced alignment or Authoring QA.


## MONTAGE SEMANTIC AUDIO SYNCHRONIZATION — 2026-09-21

Development branch: `montage`.

Protected branches at the start of this work:
- `majd` = `d1c2ad87116238ed7c46e1b01f6e129a0d2cd5ed`
- `bayer` = `d1c2ad87116238ed7c46e1b01f6e129a0d2cd5ed`
- neither protected branch is modified by this synchronization work.

Synchronization responsibility contract:
- Final Package remains immutable input and its geometry is not changed.
- Story owns semantic timing: asset meaning -> narration phrase -> aligned audio time.
- Motion owns only execution: enter before the Story anchor, settle on the anchor,
  then remain stable under the existing entry/settle/freeze contract.
- Composition remains the sole spatial destination authority.
- Choreography remains the semantic motion/action authority and does not own audio time.

Implementation checkpoints:
- `11d5d6981178b0705aeac29148ac1277e8b72b8b`
  `[montage] Add Story semantic asset activation timing`
- `abba657a0727607e64926087a566c60a354362f5`
  `[montage] Add semantic synchronization QA`
- `22b9c1c86ee8e60033ad56e75331c3f4121775a2`
  `[montage] Add multimodal Story sync fallback and runtime`
- `89200219ae7a638e1c41a2077bff43940d6c768b`
  `[montage] Add per-asset semantic sync diagnostics`
- `7e03851f685dfb1a193e971eb68b0344ef08a1ff`
  `[montage] Defer VLM sync matching to unresolved semantics`

Current semantic timing design:
1. Narrow explicit Final Package triggers are accepted as highest-confidence evidence.
2. Story builds phrase candidates from forced-aligned words and exact script character spans.
3. A multilingual semantic encoder can match English/Arabic semantic metadata to Arabic
   narration phrases. Product default is `intfloat/multilingual-e5-small`, with runtime
   override through `HEXA_SEMANTIC_TEXT_MODEL`.
4. If Qwen3-VL is configured, Story can perform one joint scene decision mapping
   semantic unit -> extracted asset -> narration phrase. Returned IDs and phrase indexes
   are strictly validated and low-confidence matches are discarded.
5. Parent/family sub-assets may inherit a trusted parent semantic anchor instead of
   inventing a separate word-level trigger.
6. Low-confidence or ambiguous matches explicitly abstain and use conservative fallback
   timing. The system must never fabricate semantic certainty merely to animate an asset.
7. MotionTimingPolicy consumes `AssetActivation` and uses its `spoken_start` as the
   semantic settle target when the activation is trusted.
8. StorySyncQA compares each trusted Story anchor with the compiled Motion settle time.
   A drift greater than 50 ms, missing motion cue, missing settle time, or invalid
   non-monotonic semantic ordering is a production failure. Diagnostics are written to
   `diagnostics/story-sync-qa.json`.

Runtime provisioning:
- `HEXA.bat` now uses a versioned readiness marker and installs desktop,
  transcription, WhisperX alignment, and semantic-model runtime dependencies.
- The multilingual semantic model is lazy-loaded and cached in-process.
- Optional semantic/VLM inference is fail-safe: dependency/model failure falls back to
  conservative timing rather than corrupting geometry or crashing render planning.

CI proof:
- run `35600241035` for `11d5d698...`: SUCCESS, 104 tests.
- run `35600631569` for `abba657...`: SUCCESS, 107 tests.
- run `35601157706` for `22b9c1c...`: SUCCESS, 108 tests.
- run `35601586057` for `8920021...`: SUCCESS, 108 tests.
- run `35601905928` for `7e03851...`: SUCCESS, 108 tests.

Generality rules retained:
- no assumption that a scene contains a character;
- no fixed asset count or six-asset cap;
- dense scenes may abstain instead of forcing one phrase per asset;
- real photos and illustrations share the same semantic timing contract;
- long Arabic text is matched only within the current aligned scene/beat;
- fast/short beats may safely fall back when there is not enough executable motion time;
- repeated assets can receive different Story activations on different beats;
- no Final Package schema change is required.

PROVEN status:
- Code/CI contract: PROVEN GREEN on `montage`.
- Real-package semantic visual synchronization: NOT YET VISUALLY PROVEN.
  The next acceptance step is to run multiple real Final Packages and inspect whether
  the chosen icon/phrase pairs are semantically correct, not merely time-correct.


## MONTAGE13 TRANSFER CHECKPOINT — 2026-09-21

Outgoing owner: Montage12.
Incoming owner: Montage13.
Development branch: `montage`.

State handed off:
- semantic synchronization implementation is committed on `montage`;
- latest implementation/documentation checkpoint before this transfer:
  `e90ac28784241225f1e7adabace06c4b007bc3c8`
  `[continuity] Record final semantic sync diagnostics and VLM fallback`;
- CI run `35602060137` on that checkpoint: SUCCESS;
- Ruff: `All checks passed!`;
- Pytest: `108 passed, 12 warnings in 6.31s`;
- protected branches `majd` and `bayer` remain unchanged at
  `d1c2ad87116238ed7c46e1b01f6e129a0d2cd5ed`.

What is implemented and must be preserved:
- Story owns per-asset semantic activation time through `AssetActivation`.
- semantic-unit -> cutout binding lives under Story; Choreography reuses the same binder
  through a compatibility export rather than maintaining a second mapping algorithm.
- trusted explicit triggers are preferred; coarse whole-scene triggers are not treated
  as fake word-level truth.
- forced-aligned word/character spans are used to generate narration phrase candidates.
- multilingual semantic matching is available, with conservative confidence/margin
  gating and explicit abstention.
- optional Qwen3-VL is only a fallback for unresolved semantic cases and its outputs are
  strictly constrained to known assets/phrases.
- family/sub-assets may inherit a trusted parent anchor instead of inventing independent
  semantic timing.
- Motion consumes trusted Story activation times and targets semantic settle at the
  spoken anchor; the existing entry -> settle -> freeze motion contract stays intact.
- Story synchronization QA writes `diagnostics/story-sync-qa.json` and rejects timing
  drift greater than 50 ms for trusted semantic anchors.
- the Final Package format, scene geometry, Pass1, Pass2, Composition authority and
  protected baseline branches are not changed by this work.

What is NOT proven yet:
- semantic pairing quality on real diverse Final Packages is not visually accepted yet.
- CI proves the contract and synthetic cases, not that every real icon is matched to the
  correct narration phrase.
- motion-style quality is intentionally deferred. First finish and prove synchronization;
  only then start the separate motion-quality improvement problem.

Mandatory next steps for Montage13:
1. Verify live branch/HEAD/CI before editing; do not trust this file alone.
2. Read the current `app/story/activation.py`, `app/story/sync_qa.py`,
   `app/story/binding.py`, `app/motion/timing.py`, `app/motion/planner.py`,
   `app/pipeline.py`, and semantic-sync tests before changing behavior.
3. Run real-package validation on multiple materially different Final Packages.
4. Inspect diagnostics per asset: asset ID, semantic unit, chosen phrase, spoken anchor,
   confidence/source/policy, compiled settle time and delta.
5. Measure semantic correctness separately from timing correctness. A 0 ms timing delta
   to the wrong phrase is still a synchronization failure.
6. Add regression cases for every real false match or unsafe abstention discovered.
7. Prefer calibrated abstention over forced guesses. Never special-case scene numbers,
   filenames, hacker vocabulary, banking vocabulary, or one current package.
8. Mental-test every change against: no character; 20 assets; one asset; photos;
   illustrations; long Arabic text; numbers; comparisons; timelines; motion-limited
   assets; very fast/slow narration; 0.5 s/8 s scenes; repeated assets; re-entry.
9. Keep `majd` and `bayer` untouched. All synchronization development stays on
   `montage`.
10. Do not begin motion-style redesign until real-package synchronization is proven or
    the user explicitly changes priority.

Acceptance target for the synchronization phase:
- correct semantic phrase chosen for important movable assets on diverse real packages;
- trusted Motion settle aligns to the chosen forced-aligned phrase within QA tolerance;
- ambiguous/decorative assets abstain or group safely instead of receiving invented
  word-level timing;
- no Final Package geometry/layout regression;
- green CI plus real visual review.


## MONTAGE14 / MONTAGE15 VISUAL SEMANTIC UNDERSTANDING CHECKPOINT — 2026-09-23

Development branch: `montage`.

### Live source state before this handoff update

- Live `montage` HEAD verified on GitHub:
  `1fcf67ba6453b5fc7f8df56e4b972f9b07cc939d`
  `[montage15] Force eager attention for Florence compatibility`
- V2 CI run `35806303627`: SUCCESS.
- Ruff: `All checks passed!`
- Pytest: `221 passed, 12 warnings in 9.16s`.
- Protected branches remain untouched:
  - `majd` = `d1c2ad87116238ed7c46e1b01f6e129a0d2cd5ed`
  - `bayer` = `d1c2ad87116238ed7c46e1b01f6e129a0d2cd5ed`

### CURRENT TASK — MUST BE PRESERVED

The active engineering problem is **visual semantic understanding for extracted assets**.

The system already knows how to:
- extract assets through Pass1 + Pass2,
- preserve Final Package geometry,
- align narration using forced alignment,
- match semantic text to Arabic narration through multilingual E5,
- create Story V2 activation windows,
- execute those windows in Motion.

The remaining problem is that many independently animatable cutouts have **no trustworthy semantic meaning** in metadata. Story therefore cannot know which narration phrase each icon/cutout represents.

The target pipeline is:

`Pass1 / Pass2 -> Visual Semantic Resolver -> visual description -> E5 phrase retrieval -> forced-aligned phrase -> Story V2 activation -> Motion`

Hard responsibility boundaries:
- Pass1 / Pass2 = WHAT VISUAL ASSET EXISTS / safe extraction.
- Visual Semantic Resolver = WHAT THE EXTRACTED IMAGE MEANS visually.
- E5 = WHICH narration phrase is semantically closest.
- Forced alignment = EXACT spoken timestamps.
- Story V2 = WHEN the asset reveals/peaks/settles.
- Composition = WHERE the asset ends.
- Motion = HOW it moves.
- No visual model may invent timestamps.
- No visual model may change extraction geometry.
- No Pass3 / Layer3 may be reintroduced.

### PROVEN TEXT-ONLY BASELINE

Real White-Hat full package baseline with:
- exact full Final Package: 35 scenes / 133 eligible assets after Pass2,
- real WhisperX forced alignment,
- `intfloat/multilingual-e5-small`,
- visual VLM disabled.

Measured Story result:
- eligible assets: 133
- trusted: 33
- inherited: 6
- total trusted + inherited: 39 / 133
- eligible coverage: 29.32%
- abstained: 94

This `39 / 133 = 29.32%` result is the official E5/metadata baseline that future visual models must improve without regressing existing trusted anchors.

### FAILED MODEL — SmolVLM-500M-Instruct

Model tested:
`HuggingFaceTB/SmolVLM-500M-Instruct`

Purpose:
- understand extracted White-Hat cutouts visually,
- produce a short semantic description,
- feed that description to E5 for narration phrase retrieval.

Important implementation checkpoints:
- `d512fb34913801b283d0dccbd4b16a9072a58421`
  `[montage14] Remove accidental shell artifacts`
- `f8210b301c99d85bbecef17f2111dab37667f371`
  `[montage14] Add SmolVLM Story visual backend`
- `8438d620d385665d2fb7a081fdb6ce24c287558f`
  `[montage14] Bound SmolVLM CPU processing and diagnostics`
- `f7d5eedef623360abffe412f4396c26e0517563d`
  `[montage14] Harden SmolVLM inventory output parsing`

What was tried:
- narration-blind visual inventory,
- exact allowed asset IDs,
- deterministic JSON parser,
- support for fenced/prefixed/suffixed JSON,
- smaller page size: 6 assets for SmolVLM instead of 24,
- compact prompt,
- diagnostics for malformed/empty responses,
- confidence threshold preserved at 0.62.

Real 4-scene White-Hat probe:
- scenes: 001, 008, 017, 028
- visual runtime available: true
- visual inventory count: 9
- visual semantic count: 9
- new `E5_VISUAL` matches: 0
- OWN: 4
- INHERITED: 1
- abstained: 12

Why SmolVLM is considered FAILED for this task:
- accepted descriptions were copies of the prompt template such as:
  `visible object/action`
- it invented placeholder IDs such as:
  `asset_id = "ID"`
- scene 008 returned only an asset ID instead of structured semantic output,
- scene 028 degenerated into repeated placeholder rows and took about 708 seconds,
- no useful new visual meaning reached E5,
- White-Hat coverage therefore remained the text-only baseline:
  `39 / 133 = 29.32%`.

Conclusion:
**SmolVLM-500M is not accepted as the production visual-semantic model.**
Do not spend further work lowering thresholds or prompt-tuning it for coverage.

SmolVLM support still exists in code only as an optional backend for compatibility. It is not the active production choice.

### ACTIVE MODEL — Florence-2-large-ft

Active model:
`microsoft/Florence-2-large-ft`

Reason for choosing Florence:
- its job in HEXA is much narrower than SmolVLM's previous contract,
- Florence is not asked to produce JSON, asset IDs, phrase indexes, timing, or narration decisions,
- Florence sees **one extracted asset image at a time** and produces only a visual caption,
- asset identity stays deterministic in our code,
- E5 remains responsible for matching the visual meaning to narration.

Active pipeline:

`one asset image -> Florence <MORE_DETAILED_CAPTION> -> visual description -> E5 -> narration phrase -> forced alignment -> Story V2 -> Motion`

This architecture intentionally removes the two biggest failure modes seen with SmolVLM:
1. multi-asset contact-sheet reasoning,
2. model-generated asset IDs / structured inventory contracts.

### Florence implementation checkpoints

- `f023aad8858e3bb252fe570489947df100abbdaf`
  `[montage15] Add Florence Story visual caption backend`
- `39a973deaaf64dc230f533cd2b30570dbbda3981`
  `[montage15] Fix Florence per-asset cache creation`
- `1296b12c034ac68cd8ab1da93f2aa09006084e9f`
  `[montage15] Add Florence timm runtime dependency`
- `1fcf67ba6453b5fc7f8df56e4b972f9b07cc939d`
  `[montage15] Force eager attention for Florence compatibility`

Current production behavior:
- Story backend name: `florence`
- Story model env:
  `HEXA_STORY_FLORENCE_MODEL`
- visual backend selection:
  `HEXA_VISUAL_SEMANTIC_BACKEND=florence`
- Florence Story runtime is independent from the existing Pass2 variable:
  `HEXA_FLORENCE_MODEL`
- Qwen Director behavior remains unchanged.
- Florence Story inference uses local model files only.
- model is lazy-loaded.
- CPU path uses float32.
- each asset is captioned independently.
- task: `<MORE_DETAILED_CAPTION>`
- generic captions are rejected.
- existing visual-semantic minimum confidence remains 0.62.
- valid captions use conservative acceptance confidence 0.72 before E5 matching.
- per-asset cache is backend/model/schema isolated.
- valid rejected/accepted caption attempts are cached to avoid repeated CPU work.
- no narration, phrase candidate, or timestamp is passed into Florence.

### Florence runtime provisioning / compatibility

The user downloaded the full local model to:

`C:\Users\INTEL CENTER\HEXA-Models\Florence-2-large-ft`

Large model weight:
`model.safetensors` approximately 1.54 GB.

The initial runtime exposed two environment compatibility issues, both now fixed in project code:

1. Missing `timm`
   - fixed by adding `timm>=1.0,<2` to the `vision` optional dependency.

2. Florence remote-code / Transformers SDPA compatibility:
   - runtime error:
     `Florence2ForConditionalGeneration object has no attribute _supports_sdpa`
   - fixed by forcing:
     `attn_implementation="eager"`
   - applied to both Story Florence and the existing Florence detector path to keep behavior consistent.

The user then verified the real local model manually with:
- local files only,
- `trust_remote_code=True`,
- `attn_implementation="eager"`.

Observed result:
`FLORENCE LOCAL READY`

Therefore:
**Florence model download + dependency/runtime loading is now locally PROVEN.**

### What is NOT proven yet

Florence semantic quality on the White-Hat package is **NOT YET PROVEN**.

No Florence White-Hat Story probe has been accepted yet.
No Florence-based full render has been visually reviewed yet.

Do not claim that Florence improves the 29.32% baseline until a real probe proves:
- meaningful non-generic visual descriptions,
- new correct `E5_VISUAL` matches,
- trusted/inherited total above the baseline without false semantic matches,
- correct phrase-to-asset pairing on visual review.

### NEXT OFFICIAL TEST

Run the real White-Hat Story-only probe with:

- `HEXA_VISUAL_SEMANTIC_BACKEND=florence`
- `HEXA_STORY_FLORENCE_MODEL=C:\Users\INTEL CENTER\HEXA-Models\Florence-2-large-ft`
- `HEXA_SEMANTIC_TEXT_MODEL=intfloat/multilingual-e5-small`
- forced alignment enabled.

Measure:
- `eligible_asset_count`
- `visual_inventory_count`
- `visual_semantic_count`
- `trusted_count`
- `inherited_count`
- `abstained_count`
- `eligible_coverage`
- `visual_runtime_available`
- `visual_runtime_error`
- sample visual descriptions and their chosen phrases.

Acceptance comparison:
- baseline = `39 / 133 = 29.32%`
- Florence must add useful, semantically correct matches rather than merely increase the number.

Only after the Story probe is semantically acceptable:
1. run full White-Hat render,
2. user shares rendered video / diagnostics,
3. inspect whether assets enter on the correct narration idea,
4. fix code on `montage` based on real visual/timing failures.

### WORK SPLIT FROM THIS CHECKPOINT

Because the assistant execution environment cannot reliably host/download the user's local visual model weights:
- Assistant owns GitHub code changes, architecture, tests, CI, regression fixes and handoff updates.
- User owns local model execution and final video rendering.
- User sends render videos, logs, diagnostics and visual failure reports back.
- Assistant analyzes root cause and patches `montage`.
- Do not ask the user to use Codex for these code fixes unless the workflow changes explicitly.

### CURRENT DECISION ON MODEL STRENGTH

Florence is the current baseline visual model to prove first.

Possible stronger future candidates such as MiniCPM-V / InternVL may be evaluated later, but they are **not active architecture decisions yet**.

Before changing models:
1. prove Florence on the same White-Hat assets,
2. quantify semantic correctness and runtime cost,
3. only replace or augment Florence if measured quality is insufficient.

Potential Florence improvements if baseline quality is insufficient, before replacing the model:
- compare `DETAILED_CAPTION` vs `MORE_DETAILED_CAPTION`,
- asset-only caption + bounded scene-context caption,
- semantic fusion of isolated/context descriptions before E5,
- keep timing and IDs deterministic outside the visual model.

### HARD STATUS SUMMARY

PROVEN:
- Pass1 + Pass2 only.
- Final Package geometry authority.
- forced-alignment timing contract.
- Story V2 -> Motion integration.
- multilingual E5 runtime.
- White-Hat E5 baseline: 39/133 = 29.32%.
- SmolVLM failure for useful visual semantic descriptions.
- Florence integration code.
- Florence local model download.
- Florence real local load with timm + eager attention.
- live GitHub CI green at `1fcf67ba...`.

NOT PROVEN:
- Florence visual-description quality on White-Hat.
- Florence improvement over 39/133.
- Florence-based final render visual quality.

NEXT:
**Run the White-Hat Florence Story-only probe. Do not redesign Motion or extraction before this semantic test is measured.**
---

## MONTAGE15 FINAL-PACKAGE SEMANTIC AUTHORITY CHECKPOINT — 2026-09-23

This checkpoint SUPERSEDES all earlier Florence / SmolVLM visual-semantic plans and tests.

### FINAL DECISION

Production Story semantic understanding must NOT infer asset meaning from a visual model.

Removed from production architecture:
- Story Florence backend.
- Story SmolVLM backend.
- Story visual-semantic inventory/resolver layer.
- VLM direct asset-to-phrase fallback.
- Florence detector wiring from Vision.
- Florence semantic proposal wiring from Pass2.
- Florence-specific Story/Vision tests and runtime settings.
- Florence-only vision dependency stack from the vision extra.

Deleted source files:
- `app/story/florence.py`
- `app/story/smolvlm.py`
- `app/story/visual_semantic.py`
- `app/vision/florence.py`

### ACTIVE AUTHORITY CONTRACT

`Final Package semantic intent -> extracted Pass1/Pass2 assets -> exact/declared script binding -> WhisperX timing -> Story V2 -> Motion`

Hard ownership:
- Final Package = semantic authority.
- Pass1 + Pass2 = extraction authority.
- WhisperX = spoken timing authority.
- Story V2 = activation-window authority.
- Motion = animation execution authority.

Do NOT restore Florence/SmolVLM as a semantic fallback.

### CURRENT COMPATIBILITY STATE

Until the new additive `semantic_bindings.json` contract is implemented, legacy Final Packages may still use existing package semantic metadata + multilingual E5 text matching. E5 is text-only and must not inspect pixels.

When `semantic_bindings.json` is available, exact declared `script_text` bindings should bypass semantic guessing whenever they can be resolved safely.

The cutout mapping must NOT assume `Final Package element == one extracted cutout`.
Resolver design must account for scene identity, package semantic intent, parent/child relationships, authored role, optional package geometry, Pass1/Pass2 source bbox, parent/family lineage, one-to-many or many-to-one mapping, and SAFE_ABSTENTION.

### VERIFIED CODE STATE

- `b4cc556dc67a8dca3f58ece075079dcd6a4bd9d1` — remove visual semantic models and trust Final Package intent.
- `ad552326dd164b4b904ef4de3d0b98e6dcaff828` — cleanup removed visual call residue.
- `98f74a2278d7b28eceb4cf915f1ca4ea1b193aa6` — remove obsolete visual Story test.
- `845404b3105d4688acd856531681e2fb3ff5bda0` — replace visual fallback tests with Final Package authority.
- `72e19471dd58a3a22f09cbb2f8466bc05c68b42d` — final stale import cleanup.

CI:
- GitHub Actions run `35811164400`
- HEAD tested: `72e19471dd58a3a22f09cbb2f8466bc05c68b42d`
- Compile: SUCCESS
- Lint: SUCCESS
- Tests: SUCCESS
- Result: `187 passed, 12 warnings`

### NEXT OFFICIAL STEP

Do NOT run another Florence probe.

Wait for the user's updated Final Package containing additive `semantic_bindings.json`.
Then inspect the real ZIP/JSON, compare package semantic elements with actual Pass1/Pass2 cutouts, design the general resolver from observed data, preserve backward compatibility, add diagnostics/tests, and render only after semantic mapping is proven.

---

## MONTAGE16 SEMANTIC BINDING STORY SYNC CHECKPOINT — 2026-09-23

### INPUT CONTRACT PROVEN

The updated White-Hat Final Package includes additive `semantic_bindings.json` with schema `HEXA_SEMANTIC_BINDINGS` v1.0.
The inspected package contains 35 scenes and 145 semantic binding assets.
For the current White-Hat package, every semantic asset inside a scene uses the same declared `script_text` as the other semantic assets in that scene.

### HARD SAFETY DECISION

Pass1 and Pass2 are unchanged.
`semantic_bindings.json` never creates a cutout and never forces extraction.
Only cutouts actually produced by Pass1/Pass2 may receive Story/Motion activation.

### NEW STORY BEHAVIOR

When one scene has exactly one unambiguous declared semantic-binding phrase:
- every independently animatable non-background/non-decorative cutout produced for that scene receives an explicit Final Package semantic activation;
- Story resolves the exact canonical-script character span;
- WhisperX word alignment supplies the spoken start/end;
- `reveal_start == phrase_start`;
- `settle_at == phrase_end` when the visual beat has capacity;
- source is `final_package_semantic_binding`;
- E5 is not needed for that exact case.

If a scene contains multiple different binding phrases and there is no safe cutout mapping, Story does not guess. It falls back to the pre-existing legacy semantic path.

### MOTION CONTRACT

No new Motion style algorithm was added. Existing Motion V2/V3 already consumes Story activation windows and retimes the smooth authored motion program.
For exact Final Package bindings, motion begins at phrase start and reaches the Composition-authored resting position at phrase end.
The semantic-bound package visual timeline no longer hands off a scene before the previous spoken phrase finishes when the audio spans do not overlap.

### VERIFIED COMMITS

- `8490438541923fae67c3c1dfaae216c80f4dc904` — PackageModel semantic bindings field.
- `eb7e7217bb6db3a262928bcb81d15a11774f99c0` — semantic bindings loader/validation.
- `0c394c496d9209ff283d9df565696dd7810ecf49` — preserve spoken completion for semantic-bound packages.
- `ed1890277d23c31a93e542c8f8cb8b291f0559f0` — exact phrase Story window.
- `378272ed807536d9e4940cbcc38b7d65d4e97814` — apply semantic binding timing to real cutouts.
- `e15d52526140a311218bd82032a1781f3b2db377` — binding phrase normalization fix.
- `c4be3b45fa6878135f1418ed376a6e1b0721d8d0` — loader tests.
- `13c45b2fd4368248f911b7e727c42696a6cbe262` — Story binding/timeline tests.
- `15eb541e760b1e392ace8531e3a843d2275783b1` — Motion settle timing test.

### CI

GitHub Actions run `35813476202`: SUCCESS.
Compile: SUCCESS.
Lint: SUCCESS.
Tests: `193 passed, 12 warnings`.

### NEXT

Pull `montage`, run `HEXA.bat` with the updated White-Hat Final Package containing `semantic_bindings.json` and the existing White-Hat audio, then review the full render and Story sync diagnostics.

