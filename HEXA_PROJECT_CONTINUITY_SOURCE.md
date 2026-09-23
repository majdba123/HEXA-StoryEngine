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



---

## MONTAGE20 GENERAL RECOVERY + DESKTOP RUNTIME CHECKPOINT — 2026-09-23

Development branch: `montage`.

### WHITE-HAT FULL RUN FAILURE ROOT CAUSE

Observed production run reached:
- Pass1: 118 authored assets across 35 scenes.
- Pass2: 133 assets (+15).
- Story: 35 beats.
- Authoring QA: 133 semantic sync anchors, 0 conservative fallbacks.
- Failure occurred only in Recovery with:
  `MULTI_ELEMENT_POP`.

Root cause:
- the legacy Recovery detector treated several simultaneous entrances as a defect unless
  cue end times clustered around `beat.audio_start`;
- explicit Final Package semantic bindings intentionally allow multiple real Pass1/Pass2
  cutouts in one scene to share the same trusted Story V2 phrase window;
- therefore correct `reveal_start -> settle_at` motion was being reclassified as an
  accidental pop after Authoring QA had already accepted it;
- rebuilding Motion could not change the result, so Recovery repeated the same issue.

Fix:
- Recovery now recognizes a grouped entrance as narration-locked when every cue has a
  trusted Story V2 activation and the compiled cue matches that activation's
  `reveal_start` and `settle_at` within tolerance;
- incomplete, malformed or partially-bound groups still fall through to the existing
  `MULTI_ELEMENT_POP` detector;
- no scene IDs, White-Hat vocabulary, asset counts or package-specific exceptions exist.

Pass1 and Pass2 remain unchanged.

### DESKTOP / WINDOWS PROCESS UX

Product requirement:
- visible console/setup activity is allowed only for first-time environment bootstrap or
  explicit environment repair;
- normal generation must remain inside the HEXA Dashboard;
- FFmpeg, FFprobe and other child processes must not create transient Windows console
  windows during pipeline stages.

Implementation:
- added `app/shared/process.py` with a Windows-aware hidden child-process runner;
- all application-owned subprocess calls use the centralized hidden runner;
- an architecture test rejects future raw `subprocess.run/Popen` calls inside `app/`;
- WhisperX alignment no longer receives an audio file path, because WhisperX would launch
  its own FFmpeg subprocess; HEXA decodes the audio through its configured hidden FFmpeg
  path and passes a 16 kHz mono numpy waveform directly to WhisperX;
- custom `HEXA_FFMPEG` configuration is propagated into transcription/alignment;
- `HEXA.bat` remains the visible bootstrap/setup entry and validates FFmpeg/FFprobe
  during setup;
- `HEXA.vbs` is the normal silent launcher: if the environment is ready it opens the
  Dashboard directly; if not, it invokes the visible bootstrap.

### GENERALIZATION / MENTAL-TEST CONTRACT

These fixes are package-agnostic. They do not depend on:
- characters being present;
- a fixed asset count;
- illustrations versus real photos;
- Arabic text length or numeric density;
- comparison/timeline scenes;
- scene duration;
- narration speed;
- repeated or re-entering assets.

Recovery trusts only explicit Story V2 timing evidence, not package identity.
Desktop child-process suppression is independent of Final Package content.

### VERIFIED COMMITS

- `967616d963439eee490aa6ed7f3978cb7a0c60f5` — respect Story V2 grouped semantic entrances in Recovery.
- `85a61c8ffff739f4d01308052bd95fbb7a57f9d1` — regression coverage for semantic-bound multi-element recovery.
- `07bacbd7af393bb166a071ad42f5a3abd84c4aaf` — centralized hidden Windows subprocess runner.
- `f3064da586749389ba21ca445dc9dfe5c698689d` — silent desktop launcher.
- `b4bc28e5106a4893a2ba76e8b3884d1f74a6d93a` — hidden FFmpeg audio decode.
- `2b46f5190707ed84c625c00a41161d2e4432e1fb` — console-free WhisperX waveform input.
- `3df964af7611951655ee94a530138322fe0a3192` — cleanup checkpoint before final green CI.

### CI

GitHub Actions run `35815260128`: SUCCESS.
Compile: SUCCESS.
Lint: SUCCESS.
Tests: `199 passed, 12 warnings`.

### NEXT

Pull current `montage`.
Use `HEXA.vbs` for normal launches.
Run the same full White-Hat semantic-bindings render again.
Expected next gate:
- Recovery must pass the previous `MULTI_ELEMENT_POP` point;
- generation stages remain visible only in the Dashboard log/progress UI;
- no transient FFmpeg/FFprobe/WhisperX console windows;
- then perform full visual sync QA on the completed render.


## MONTAGE20 BLACK-HAT AUTHORING GRAMMAR RECOVERY — 2026-09-23

- Real user run on asset-level Black-Hat Final Package reached Motion after:
  - Pass1: 157 authored assets / 40 scenes
  - Pass2: 179 assets (+22)
  - Story: 40 beats; densest scene 12 assets
  - Composition: geometry locked; 0 text cues
- Diagnostic job: `f8e1717d9e8a41c29c8778ea9c953569`.
- Failure was NOT Final Package loading, semantic asset timing, Pass1/Pass2, Composition, or Motion sequencing.
- Storytelling authoring QA failed only on legacy `REFERENCE_VISUAL_GRAMMAR`:
  - 13 choreography sequences
  - 12 compliant
  - 1 incomplete
  - 179 semantic motion cues were already present.
- Root cause: `ReferenceGrammarPlanner` gave generic final `HANDOFF` beats only `RELEASE`, so a valid two-beat sequence could become `ENTER + READ + RELEASE` with no `ADD/RELATE/RESULT` and be falsely rejected.
- General fix:
  - `HANDOFF` now counts as a progressive `ADD` stage for non-first beats.
  - This preserves the intended grammar: the handoff introduces the next visual/narrative unit, then releases the sequence.
  - No scene/package special cases; no Pass1/Pass2 changes.
- Diagnostics improved:
  - Storytelling report now records exact `incomplete_grammar_sequences` with sequence ID, beat count, and stages.
- Regression test added for a generic two-beat handoff sequence.
- Final live `montage` HEAD:
  - `ceb749a23fd6f8c379187cd48e6f628b02b45408`
- GitHub Actions:
  - Run `35822102043` SUCCESS
  - Compile SUCCESS
  - Ruff: All checks passed
  - Pytest: 208 passed, 12 warnings
- Next acceptance step:
  - pull `montage`
  - rerun the same Black-Hat Final Package + audio
  - expect authoring QA to pass the previous 12/13 grammar blocker
  - then verify actual render for narration-locked sequential asset entrances.


## MONTAGE20 SINGLE-BEAT GRAMMAR RECOVERY — 2026-09-23

- Second real Black-Hat run diagnostic job: `2dc00ad32d7c4aac8d62218a5e5fd477`.
- Pipeline again reached Motion after:
  - Pass1: 157 authored assets / 40 scenes
  - Pass2: 179 assets (+22)
  - Story: 40 beats; densest scene 12 assets
  - Motion semantic cues: 179 / 179 rich motion cues
- Remaining authoring failure was isolated exactly by improved diagnostics:
  - `sequence-013[beats=1;stages=ENTER,READ,RELEASE]`
  - 13 sequences total, 12 compliant before fix.
- Root cause:
  - Storytelling validator required every sequence, including a single-beat standalone sequence, to contain `ADD/RELATE/RESULT`.
  - A one-beat sequence has no later beat available to add/relate/result, so requiring that stage fabricated meaning and caused a false-positive QA failure.
- General fix:
  - Single-beat sequence is compliant when it has complete `ENTER + READ + RELEASE` grammar.
  - Multi-beat sequences still require `ADD/RELATE/RESULT` in addition to `ENTER + READ + RELEASE`.
  - No Final Package special case, no scene IDs, no Pass1/Pass2 change, no semantic timing relaxation.
- Regression coverage:
  - standalone single-beat grammar passes without fabricated ADD
  - multi-beat grammar without meaning progression still fails
  - multi-beat grammar with ADD passes
- Code/test HEAD before this continuity commit:
  - `3928f64563da73d80223be407e171d3116482ce7`
- GitHub Actions:
  - Run `35823220724` SUCCESS
  - Compile SUCCESS
  - Ruff: All checks passed
  - Pytest: 210 passed, 12 warnings
- Next acceptance step:
  - pull latest `montage`
  - rerun the same Black-Hat Final Package + narration
  - expected: previous `REFERENCE_VISUAL_GRAMMAR` blocker for sequence-013 is gone
  - then verify actual sequential asset entrances in encoded render.


## MONTAGE20 OPTIONAL TEXT LAYER RECOVERY — 2026-09-23

- Third real Black-Hat run diagnostic job: `21e6f7222ad844a2bbd0a1db80545d77`.
- Pipeline reached Motion with:
  - Pass1: 157 authored assets / 40 scenes
  - Pass2: 179 assets (+22)
  - Story: 40 beats; densest scene 12 assets
  - Composition: geometry locked; 0 text cues
- Failure:
  - `StageFailedError: required text layer produced no narration-locked cues`
  - code: `TEXT_LAYER_MISSING`.
- Root cause:
  - `Settings` dataclass default was `require_text_layer=False`, but `Settings.from_env()` silently made production default mandatory using `HEXA_REQUIRE_TEXT_LAYER=1`.
  - Desktop launchers did not explicitly set the variable.
  - Therefore a valid sparse-text decision of zero cues became a hard failure even though Text is an independent optional layer.
- General fix:
  - production/default `HEXA_REQUIRE_TEXT_LAYER` is now opt-in (`0` by default).
  - operators can still explicitly require text via `HEXA_REQUIRE_TEXT_LAYER=1`.
  - no Text Planner semantics were weakened; no fake keywords are generated to satisfy QA.
  - diagnostics now record `require_text_layer` explicitly in report settings.
- Regression coverage:
  - default text layer policy is optional
  - explicit `HEXA_REQUIRE_TEXT_LAYER=1` remains mandatory
- Final tested code HEAD before continuity commit:
  - `7a584353a67e09261b954ff24392477d59b844b9`
- GitHub Actions:
  - Run `35824023603` SUCCESS
  - Compile SUCCESS
  - Ruff: All checks passed
  - Pytest: 212 passed, 12 warnings
- Next acceptance step:
  - pull latest `montage`
  - rerun same Black-Hat package + narration
  - expected: zero text cues no longer blocks render under normal desktop defaults
  - then inspect encoded render for sequential narration-locked asset entrances.


## MONTAGE20 FINAL-PACKAGE-DRIVEN TEXT GENERALIZATION — 2026-09-23

- Root cause of zero-text behavior:
  - Text timing/motion were healthy.
  - `TextSemanticSelector` still relied primarily on a historical finance/payment importance lexicon, so unrelated Final Packages could produce zero meaningful keyword candidates.
- Architectural fix:
  - Final Package semantic metadata is now the primary topic authority for Text.
  - `TextPlanner` passes the full `PackageModel` into `TextSemanticSelector`.
  - Selector consumes per-scene `semantic_groups`, asset `semantic_meaning`, `visual_concept`, `binding_type`, and exact `script_text`.
  - Display text is selected from canonical-script spans; no topic-specific replacement wording is invented.
  - WhisperX/forced-alignment remains the sole timing authority after selection.
  - Numeric/amount detection remains generic and can coexist with package semantics.
  - Generic linguistic fallback is used only when a package has no usable semantic bindings.
  - Legacy finance lexicon is no longer required by semantic Final Packages.
- Quality/generalization rules:
  - compact 1–3 word semantic windows
  - no cross-clause phrase joins
  - Arabic light morphology matching is ranking-only and never changes timing spans
  - weak standalone verbs are suppressed
  - SUPPORT/PARENT/AMBIGUOUS assets do not independently force text
  - 1–3 text cues per beat depending on spoken duration, while avoiding filler text
- Cross-domain regression coverage:
  - cybersecurity: `المعرفة التقنية`
  - medical: `ضغط الدم`
  - automotive: `ناقل الحركة`
  - long semantic beat can surface multiple meaningful cues while keeping forced timing
- Real Final Package acceptance test:
  - package: user-provided 40-scene Black-Hat asset-level semantic package
  - 40 scenes
  - 43 text cues
  - 40/40 beats contain at least one meaningful text cue
  - 43 text motion cues
  - every text motion cue starts at its forced-aligned cue `spoken_start`
  - no timing contract changes
- Final tested code HEAD:
  - `1710f5e4b45a846b8cbb3f1b69747ae16010b159`
- GitHub Actions:
  - Run `35826385729` SUCCESS
  - Compile SUCCESS
  - Ruff: All checks passed
  - Pytest: 216 passed, 12 warnings
- Next acceptance step:
  - pull latest `montage`
  - rerun the same Final Package + narration
  - expected Text stage: non-zero package-driven cues instead of 0
  - then review encoded render for text choice, negative-space placement, text timing, and asset sequential motion.


## MONTAGE20 TEMPORAL TEXT QA RECOVERY — 2026-09-23

- Real post-generalization diagnostic:
  - Text extraction succeeded: 51 text cues were placed instead of 0.
  - Authoring QA failed on 11 `text_text_overlap` rows.
- Root cause:
  - TextCompositionPlanner and TextMotionPlanner already use `TextVisibilityPolicy` and may intentionally reuse the same negative-space slot for cues that never coexist on screen.
  - AuthoringVisualQA compared every text box within a beat spatially only, ignoring visibility timing.
  - This produced false-positive layout failures for sequential cues occupying the same clean slot at different times.
- General production fix:
  - AuthoringVisualQA now receives Story timing from the pipeline.
  - It uses the same shared `TextVisibilityPolicy` as TextComposition and TextMotion.
  - Text/text collision is a hard failure only when BOTH:
    1. spatial overlap exceeds the existing threshold, and
    2. visibility windows overlap in time.
  - Same spatial slot + non-overlapping visibility is explicitly valid.
  - Same spatial slot + overlapping visibility remains a hard failure.
  - Real collision diagnostics now include the overlapping time interval.
  - QA API remains backward-compatible for controlled callers that omit Story timing.
- No Final Package/video/topic special cases were added.
- Regression coverage:
  - sequential cues at identical coordinates pass
  - simultaneous cues at identical coordinates fail
- Final tested code HEAD:
  - `8fa4dcba67955b1882524fdd1414850ce7847bb8`
- GitHub Actions:
  - Run `35827480901` SUCCESS
  - Compile SUCCESS
  - Ruff: All checks passed
  - Pytest: 218 passed, 12 warnings
- Next acceptance step:
  - pull latest `montage`
  - rerun the same Final Package + narration
  - expected: sequential reuse of clean text regions no longer triggers `TEXT_LAYOUT_REFERENCE_VIOLATION`
  - any truly simultaneous text collision is still blocked.


## MONTAGE20 PRESERVATION CHECKPOINT — FINAL-PACKAGE-DRIVEN TEXT + TEMPORAL QA — 2026-09-23

This checkpoint is intentionally marked as a behavior to PRESERVE in future work.

### General product invariant

HEXA is a general Final Package tool. Every future implementation must pass the question:

> What happens with a completely different Final Package?

No production logic may depend on White-Hat/Black-Hat vocabulary, finance/payment vocabulary, specific scene IDs, specific asset counts, or one package's exact structure beyond the documented package contract.

### Text semantic selection — preserve

- Final Package semantic metadata is the topic/content authority for Text selection.
- Text selection must learn meaningful words/short phrases from the current Final Package itself.
- Primary evidence:
  - canonical script
  - semantic groups
  - asset semantic meaning
  - visual concept
  - binding type
  - semantic role
  - exact script_text
- Displayed wording must remain traceable to canonical-script spans.
- Do NOT restore a topic-specific keyword dictionary as the primary path.
- Do NOT fix future domains by adding domain words such as hacker/medical/automotive/finance terms.
- Generic number/amount recognition is allowed because numbers are domain-independent.
- Legacy/generic linguistic fallback is acceptable only when semantic package metadata is unavailable or unusable.
- Weak filler/standalone verbs should not be selected merely to increase cue count.
- Text remains sparse and meaningful, not subtitle-like.

### Timing authority — preserve

- WhisperX forced alignment remains the timing authority for selected text.
- Text semantic selection decides WHAT wording is useful.
- TextTiming decides WHEN from forced-aligned canonical-script spans.
- TextMotion starts from the narration-locked spoken timing.
- Do not invent independent text timestamps in Final Package metadata.
- Do not weaken forced-alignment requirements to increase cue count.

### Text composition / motion / QA contract — preserve

All three must share the same TextVisibilityPolicy:

1. TextComposition
2. TextMotion
3. AuthoringVisualQA

Collision rule:

- Spatial overlap + temporal overlap = real text collision => FAIL.
- Spatial overlap + no temporal overlap = valid slot reuse => PASS.

This permits sequential narration-locked cues to reuse the same clean negative-space region without falsely failing QA, while preserving hard blocking of true simultaneous collisions.

### Real acceptance evidence at this checkpoint

Final Package-driven text generalization was validated with:
- cybersecurity semantics
- medical semantics
- automotive semantics
- multiple semantic cues in a longer beat

Real 40-scene package acceptance before encoded render review:
- 43 semantic text cues in controlled acceptance
- 40/40 beats covered by at least one text cue
- 43 text motion cues
- text motion retained spoken_start timing authority

Real subsequent user run:
- package-driven text selection produced 51 text cues
- failure was NOT text extraction; it exposed a separate temporal QA false positive
- temporal QA was then generalized and fixed.

### Regression protection

Tests now protect:
- cross-domain package-driven semantic text selection
- multiple meaningful cues
- forced-alignment timing
- text motion start timing
- optional text-layer policy
- same coordinates + non-overlapping visibility => PASS
- same coordinates + overlapping visibility => FAIL
- generic Final Package behavior without package/topic special cases

### Current protected checkpoint

- Branch: `montage`
- HEAD at preservation checkpoint before this continuity commit:
  `5b1c28ccda7a1091cc0cb0e97918fb86e96beeaa`
- Temporal QA tested code HEAD:
  `8fa4dcba67955b1882524fdd1414850ce7847bb8`
- CI Run:
  `35827480901`
- Result:
  - SUCCESS
  - Compile SUCCESS
  - Ruff: All checks passed
  - Pytest: 218 passed, 12 warnings

### Do-not-regress rules

Future chats/engineers must NOT:
- reintroduce topic-specific Text selection as the production authority
- make Final Package semantic bindings create or force visual cutouts
- break Pass1 + Pass2 extraction architecture
- invent text timing outside forced alignment
- treat sequential text cues as simultaneous spatial collisions
- disable real simultaneous text collision protection
- specialize fixes to this package's 40 scenes, 179 assets, or cybersecurity subject
- reduce semantic text cue quality merely to satisfy a minimum count

Preserve this checkpoint unless a later change is proven by stronger general regression tests and real render QA.


## MONTAGE20 VISUAL IDENTITY BINDING CHECKPOINT — 2026-09-23

This checkpoint fixes the remaining semantic identity weakness between Final Package
semantic intents and real Pass1/Pass2 cutouts. PRESERVE this architecture.

### Root cause proven in live code

Before this checkpoint, Asset-Level semantic timing could be correct while the wrong icon
received that timing because `SemanticAssetBinder` eventually mapped unresolved semantic
units using focus/interaction/visual-weight ordering. With several similarly sized icons,
semantic meaning + phrase timing could therefore be correct while semantic intent -> real
cutout identity was swapped.

### Architecture

No new extraction layer was added.

```
Final Package semantic intent
        |
        | optional authored visual_locator
        v
Visual Identity Binder
        |
        | matches only existing Pass1/Pass2 cutouts
        v
Story AssetActivation
        |
        v
WhisperX timing -> Story windows -> Motion
```

Hard invariant remains:

```
Pass1 + Pass2 only
```

Visual Identity Binding never:
- creates a cutout
- requests a new segmentation
- changes alpha extraction
- changes Composition geometry
- changes final positions
- invents narration timing
- changes Motion behavior

It answers only:
**WHICH existing real cutout corresponds to this semantic intent?**

### Final Package visual locator contract

Asset-Level Final Packages may optionally provide:

```json
"visual_locator": {
  "coordinate_space": "normalized_scene",
  "cx": 0.72,
  "cy": 0.43,
  "width": 0.14,
  "height": 0.19
}
```

Coordinates are normalized to the original scene image.

The locator may live:
1. directly on the semantic binding asset, or
2. on the matching `scene_plan.units[]` row with the same `unit_id`.

Semantic-binding asset locator takes precedence when both are present.

The locator is source identity metadata only. It is NOT:
- a target layout rectangle
- a crop command
- a motion path
- an animation region
- a new segmentation request

### Validation

Loader now validates every visual locator:
- object type
- `coordinate_space == normalized_scene`
- numeric `cx/cy/width/height`
- center in [0,1]
- positive normalized size
- full locator stays inside scene bounds

Malformed locator => invalid Final Package instead of silent bad binding.

### Binding evidence priority

Identity authority is now:

1. exact authored real asset id when genuinely available
2. authored visual locator vs real Pass1/Pass2 source geometry
3. Pass2 parent/family provenance
4. geometry similarity
5. legacy semantic-map heuristics only when NO locator was authored

A locator-bearing semantic intent never falls back to visual-weight/order guessing when
the locator cannot be resolved confidently.

### Geometry score

Visual locator candidates are ranked with deterministic evidence:
- IoU
- containment
- center distance
- relative size
- aspect/shape similarity
- parent/family bonus when semantic parent is already identified

Current conservative acceptance thresholds:
- minimum score: 0.60
- minimum winner margin: 0.065

If top candidates are too close, HEXA abstains rather than choosing the wrong icon.

### Pass2 family-canvas protection

Pass2 may intentionally preserve identical `source_bbox` for parent/main and secondary
children so Composition can reassemble exact authored geometry.

Visual Identity therefore does NOT rely only on the shared bbox for family-canvas assets.
For `render_as_family_canvas=True` assets it reads the cutout alpha footprint and maps
that visible alpha region back into the shared source bbox.

This protects cases such as:
- phone + screen icon
- bubble + wallet
- calendar + internal item
- parent object + detached secondary visual

without changing their extraction or Composition registration.

### Heuristic collision protection

A locator-proven real cutout is reserved.

A semantic intent without a locator is not allowed to reuse that same real cutout merely
because the legacy heuristic map selected it. This prevents a strong authored identity
from being cancelled by a weaker heuristic assignment.

### Conservative fallback

If a locator is authored but:
- real cutout geometry is unavailable,
- two candidates have insufficient margin,
- or evidence remains ambiguous,

that semantic intent does not receive a guessed OWN_WINDOW.

Additionally, when any authored locator in a beat is unresolved, the single-group
unbound-support auto-fill is disabled for that beat so ambiguous identity is not silently
reintroduced through support-tail guessing.

This is intentionally conservative: missing independent motion is safer than moving the
wrong icon with the correct spoken phrase.

### Backward compatibility

Final Packages with NO visual locators retain the pre-checkpoint behavior.

No existing package is required to add the field merely to remain loadable.

Therefore this change is additive:
- old packages: existing semantic-map behavior
- locator-aware packages: stronger geometry/provenance identity
- ambiguous locator-aware packages: safe abstention

### Diagnostics

Story semantic diagnostics now record locator identity decisions:
- beat_id
- scene_id
- semantic_asset_id
- selected real_asset_id
- source
- score
- runner_up_score
- margin
- accepted vs abstention reason

Matched AssetActivation evidence also records:
- `visual_identity_binding`
- `visual_identity_source`
- `visual_identity_score`
- `visual_identity_runner_up`
- `visual_identity_margin`

Future semantic/icon mismatch investigation should inspect these values first.

### Regression coverage

New tests prove:
- locator identity beats visual-weight ordering
- ambiguous near-identical candidates abstain
- packages without locators preserve legacy path
- Story activation uses locator identity before heuristic semantic mapping
- unresolved locator disables unsafe single-group support guessing
- locator may be supplied through scene-plan unit metadata
- Pass2 parent/child family canvases with identical source_bbox are distinguished through alpha
- locator-proven cutout cannot be stolen by another heuristic semantic intent
- valid locator package contract loads
- out-of-bounds locator is rejected
- invalid scene-unit locator is rejected

All previous semantic timing, text, Pass1, Pass2, Composition, Motion, and QA tests remain green.

### Proven checkpoint

Tested code HEAD:
`30cf824cb964695587e7ba6d88bef174fedacc03`

GitHub Actions:
- Run: `35831851624`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **229 passed, 12 warnings**

### Final Package authoring requirement for maximum identity quality

To benefit from this improvement, future Asset-Level Final Packages should emit a
`visual_locator` for each semantic visual intent when the authoring/generation stage knows
where that visual was placed in the original scene.

Do NOT fabricate locators after the fact from semantic guesses.

The producing stage that authored the visual arrangement is the correct authority because
it already knows the intended visual's source position.

If no reliable visual locator is available, omit it. The engine will retain the legacy
path rather than accepting invented geometry.

### Do-not-regress rules

Future work must NOT:
- add Pass3/Layer3 for this problem
- use visual_locator to create cutouts
- let locators alter Composition
- let semantic meaning override real geometry without evidence
- allow visual-weight/order heuristics to override a confident locator
- lower ambiguity thresholds just to increase activation count
- hard-code scene IDs, icon names, cybersecurity words, or package-specific counts
- assume one semantic intent always equals exactly one segmentation component
- break old Final Packages that do not contain locators

Always ask:
**What happens with a completely different Final Package?**


## MONTAGE20 TYPOGRAPHY V2 CHECKPOINT — 2026-09-23

This checkpoint implements the requested reference-oriented Typography V2 while preserving
all existing Final Package, Story, Composition, Motion, extraction, and audio-sync authority.

### Live starting point

- Branch: `montage`
- Starting HEAD: `814c5b521712f76dcbc767059a4c91f41e3cc6d5`
- No Pass1/Pass2, Story asset timing, visual Composition geometry, or asset Motion redesign.

### Ownership contract — preserve

```
Narration
  -> Forced Alignment
  -> Final-Package-driven semantic cue selection
  -> TextCue
  -> Text Composition / Typography feasibility
  -> Text Motion
  -> ASS/libass/FFmpeg render
```

Hard rule:
`TEXT ADAPTS TO SCENE`, never `SCENE ADAPTS TO TEXT`.

### Semantic candidate richness

- Asset-Level Final Packages remain the primary semantic authority.
- Semantic packages can now surface up to 4 strong cue candidates per beat where narration
  density and semantic importance justify it.
- Cue phrase windows may contain 1–4 words.
- Legacy packages without semantic bindings keep the older conservative cue budget so
  Typography V2 does not turn generic narration into subtitles.
- Candidate generation remains separate from visual feasibility:
  rich semantic candidates are selected first; unsafe display instances are suppressed
  later by Text Composition.
- Final Package semantic relevance contributes to cue priority rather than assigning every
  cue of one semantic type the same priority.

### Semantic anchor improvement

TextPlanner now prefers the trusted Story AssetActivation whose canonical script span
overlaps the TextCue source span.

Therefore:
- phrase tied to a specific semantic icon can place relative to that icon;
- visual identity improvements from the prior checkpoint feed Typography placement;
- forced-aligned spoken_start/spoken_end do not change;
- fallback to the beat/directive primary asset remains when no trusted activation matches.

### Typography profile

New shared module: `app/text/typography.py`.

Production visual target:
- heavy Arabic display weight
- default family: `Noto Kufi Arabic Extra Bold`
- environment override: `HEXA_TEXT_FONT_FAMILY`
- optional exact font file override for measurement: `HEXA_TEXT_FONT_FILE`
- this is a visual-weight target close to the requested Baloo Bhaijaan 2 ExtraBold style,
  not a claim that a reference uses that font.

Adaptive 1080p-equivalent sizing:
- normal keyword target around 158 px
- emphasis around 178 px
- number/amount/warning around 188–194 px
- priority/length can raise/lower target
- maximum 220 px
- production readability floor 112 px
- the system does NOT shrink below this floor merely to force text into a dense scene.

### Shaped glyph measurement

The previous character-count width estimate is no longer the primary placement authority.

TypographyMetrics:
- attempts actual Pillow FreeType measurement;
- uses libraqm/HarfBuzz RTL shaping when available;
- measures the chosen Extra Bold font and outline;
- preserves actual Arabic ligature/RTL width behavior;
- adds a small safety halo around measured glyph geometry;
- falls back to a conservative script-aware measurement only when the target font cannot
  be resolved on the runtime.

Measurement is shared/cached for placement and QA to avoid repeated font filesystem scans.

### Visual style / ASS rendering

Renderer now emits:
- heavy Extra Bold Arabic family
- white fill
- black outline
- outline approximately 5.2% of font size
- restrained shadow only
- no gradients
- no neon/glow
- no subtitle rectangle
- adaptive per-cue `\\fs` + `\\bord` tags derived from the chosen layout size.

Text motion remains deliberately short:
- strong semantic events: restrained 88% -> 100% scale settle
- normal keywords: very short directional settle
- no continuous bounce
- no rotation
- no motion redesign of visual assets.

### Placement V2

TextPlacementDirector now uses:
- final/current CompositionBeat geometry
- real visible alpha occupancy where available
- shaped typography dimensions
- 8 authored screen zones plus anchor-relative candidates
- semantic anchor distance
- scene-level soft lane continuity
- visual balance / center cost
- edge safety
- protected visual regions
- actual alpha clearance
- temporal concurrent-text occupancy.

Center screen is rejected as a normal solution when authored visual regions exist unless
the cue is extremely high priority.

### Protected regions / collision behavior

Hard safety:
- actual visual overlap above threshold -> reject candidate
- concurrent text overlap above threshold -> reject candidate
- frame overflow / unsafe edge -> reject candidate
- insufficient visible-pixel clearance -> reject candidate
- character/person/human/actor/narrator/customer assets receive the strongest protected halo
- primary objects receive stronger protection than support/other objects.

Protected-box overlap remains a weighted semantic halo in addition to actual alpha
clearance. This avoids relying on bbox non-intersection alone.

Temporal rule from the previous checkpoint remains:
- spatial overlap + temporal overlap = collision
- same slot + non-overlapping visibility = valid reuse.

### Failure / fallback behavior

If no professional safe location exists at the readability floor:
- DO NOT move a character
- DO NOT move an asset
- DO NOT relayout the Final Package
- DO NOT retime narration
- DO NOT render off-screen
- DO NOT shrink below the production floor
- suppress only that TextCue from TextComposition/TextMotion.

Pipeline progress now reports both:
- placed text cue count
- safely suppressed text cue count.

### Short-beat timing protection

TextMotion entrance/token end times are now capped by the shared visible window.
A very short beat cannot cause an entrance animation to finish after the semantic/audio
window has ended.

`motion.start` remains exactly `TextCue.spoken_start`.

### Render/RTL authority

- ASS/libass remains the render mechanism.
- Full logical phrase states are still shaped as whole RTL runs.
- No Arabic string reversal was introduced.
- Existing Unicode bidi isolate strategy remains.
- Audio timestamps remain sourced only from forced alignment.

### Regression / acceptance coverage

New `tests/test_typography_v2.py` covers the requested production cases:

A. character right + object left -> safe negative-space placement
B. large center object -> text does not cover it
C. 6-asset dense scene -> safe placement or safe suppression, assets unchanged
D. long Arabic phrase -> shaped measurement; never rendered off-frame
E. simultaneous text cues -> spatially separated
F. semantic cue -> specific Story AssetActivation becomes anchor without timing change
G. spoken_start remains forced-aligned (existing + new tests)
H. very short beat -> entrance never extends past visible/beat window
I. character role -> stronger protected region
J. no safe location -> cue suppressed and scene geometry remains byte-for-byte/model-for-model unchanged

Existing tests continue to protect:
- temporal text QA
- forced alignment
- RTL rendering
- Pass1/Pass2
- Composition
- Story semantic activation
- Motion
- Recovery
- desktop/process behavior.

### Proven code checkpoint

Tested code HEAD:
`351fa72f2b8b3ee4045d3df4c7d3305a59b3a3dd`

GitHub Actions:
- Run: `35879045983`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **238 passed, 28 warnings in 6.70s**

Warnings are existing/dependency/Pillow-style warnings and are non-failing.

### Do-not-regress rules

Future work must NOT:
- break forced alignment or independently shift typography timestamps
- reduce Typography V2 to a font-only change
- move Final Package visual assets to make room for text
- reintroduce character-count-only Arabic measurement as primary geometry
- place text over a character/primary object just to preserve cue count
- shrink text below readability floor just to avoid suppression
- treat all text cues in one beat as simultaneous when their visibility windows differ
- make legacy/non-semantic packages subtitle-like
- hard-code Black Hat, White Hat, finance, scene IDs, or package counts
- redesign visual Motion merely because Typography changed
- add Pass3/Layer3.

Always test the change against a completely different Final Package before weakening these
constraints.
