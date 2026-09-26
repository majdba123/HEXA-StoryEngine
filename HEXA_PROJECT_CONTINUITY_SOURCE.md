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


## MONTAGE20 TEXT BEHAVIOR ROLLBACK / STYLE-SIZE PRESERVATION — 2026-09-23

This checkpoint SUPERSEDES the behavioral parts of the earlier Typography V2 checkpoint.

User decision:
Restore the text system completely to the pre-Typography-V2 behavior, while preserving
ONLY the newest text visual style and large size.

### Authoritative behavioral baseline

Text behavior is restored to checkpoint:

`814c5b521712f76dcbc767059a4c91f41e3cc6d5`

The following were restored exactly from that baseline:
- `app/composition/text.py`
- `app/composition/text_director.py`
- `app/models.py`
- `app/motion/text.py`
- `app/pipeline.py`
- `app/qa/authoring.py`
- `app/text/planner.py`
- `app/text/semantic/selector.py`

The Typography V2 behavior-only module and tests were removed:
- `app/text/typography.py`
- `tests/test_typography_v2.py`

### What remains from the newer Typography change

ONLY render-level visual style and size are preserved in `app/render/text.py`.

Preserved visual changes:
- font family target: `Noto Kufi Arabic Extra Bold`
- white text fill
- black outline
- restrained black shadow
- larger visual sizes:
  - Keyword: 158
  - Number: 188
  - Amount: 188
  - WarningAmount: 194
  - Warning: 188
  - Emphasis: 178
- thick outline sized for the larger typography:
  - Keyword 8.0
  - Number / Amount / Warning 9.5
  - WarningAmount 9.8
  - Emphasis 9.0

Everything else in text rendering behavior is the old implementation, including the old
text motion/tag construction and old font_scale behavior.

### Explicitly rolled back

Do NOT treat the following previous Typography V2 behavior as current:
- richer max-4 semantic cue budget
- new semantic activation -> text anchor selection
- new shaped TypographyMetrics placement authority
- new hard-reject placement thresholds
- new character-specific stronger protected halo logic
- new safe-suppression behavior when no position exists
- new adaptive `font_size_ratio` field
- new center-screen rejection behavior
- new Typography V2 placement zone logic
- new short-beat text-motion capping changes
- new placed-vs-suppressed pipeline count
- Typography V2 A-J behavioral acceptance tests

The old text selection, timing, placement, collision scoring, anchor behavior, and text
motion are authoritative again.

### Visual Locator remains untouched

This rollback applies only to the text/Typography subsystem.

The prior Visual Identity / Visual Locator checkpoint remains fully authoritative:
- Pass1 + Pass2 only
- `visual_locator` is source identity metadata
- Visual Identity Binder remains active
- semantic intent -> real cutout identity improvements remain active
- Story asset activation improvements remain active
- no Visual Locator code was reverted.

### Proven structural check

Comparison against pre-Typography-V2 baseline `814c5b...` showed the only code difference
remaining is:
- `app/render/text.py`
- `tests/test_text_renderer.py`

plus continuity documentation.

Therefore text behavior has returned to the old code, while visual style/size alone remain
new.

### Proven CI

Behavior/code checkpoint:
`823196838358e841bda33ced395bd9896a915971`

GitHub Actions:
- Run: `35883010555`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **229 passed, 11 warnings in 7.18s**

### Do not regress this decision

Until the user explicitly requests otherwise:
- keep old text behavior
- do not reintroduce Typography V2 semantic selection changes
- do not reintroduce Typography V2 placement redesign
- do not reintroduce Typography V2 motion redesign
- do not reintroduce TypographyMetrics or adaptive font-size layout fields
- preserve the current new heavy visual style and larger font sizes
- preserve forced alignment exactly as the old text system does
- preserve Visual Locator / Visual Identity work independently


## MONTAGE20 FINAL PACKAGE VISUAL LOCATOR REAL-PACKAGE QA — 2026-09-23

This checkpoint validates the new Final Package visual-locator contract against a real
40-scene package and closes one remaining identity-cardinality gap.

### Package inspected

Real uploaded package:
- project_id: `HEXA_BLACK_HAT_HACKER_AR`
- 40 scene images
- 129 semantic assets
- 40 semantic groups
- 107 authored `visual_locator` entries
- 22 semantic assets intentionally omit locator under correctness-over-coverage policy
- package semantic validation report: PASS
- visual locator validation errors: 0

The current `FinalPackageLoader` loaded the package successfully:
- 40/40 scenes
- canonical script loaded
- scene_plan loaded
- semantic_bindings loaded
- all authored locators accepted

### Important production discovery

The initial VisualIdentityBinder correctly resolved 99/107 locators one-to-one, but
8 locator intents remained unresolved.

This was NOT a malformed-locator problem.

Those 8 semantic intents intentionally described one visual unit composed of several
detached real cutouts, for example:
- network nodes
- profile cards
- protected file cases
- infected devices
- growing devices
- installation path pieces
- month calendars
- digital footprints

The Final Package already declared:

`cutout_mapping_cardinality = ZERO_OR_ONE_OR_MANY`

The engine architecture had documented that one semantic intent may correspond to
zero/one/many real cutouts, but the visual-locator binder still returned only one real
asset per semantic locator.

### Fix: locator-backed multi-cutout visual units

VisualIdentityBinder now preserves the original strict one-to-one path first.

It does NOT lower:
- `_MIN_SCORE = 0.60`
- `_MIN_MARGIN = 0.065`

Only after one-to-one matching abstains, a locator may resolve as a multi-cutout visual
unit when all conservative geometry gates pass:

- multiple unreserved real cutouts are strongly contained by the authored locator;
- primary members each occupy meaningful locator area;
- candidate members are spatially distinct rather than near-duplicate overlapping masks;
- the union bbox strongly reproduces the locator geometry;
- total locator coverage is meaningful;
- tiny satellite pieces are included only relative to the visual unit's real member scale.

The binder now exposes:
- `matches` for one-to-one identity;
- `multi_matches` for one semantic intent -> multiple real cutouts;
- `matches_for(semantic_asset_id)` as the unified consumer API.

Source for multi matches:
`visual_locator_multi`

### Conflict protection

This extension remains conservative:

- one-to-one proven locators reserve their real cutouts first;
- a multi locator cannot steal a cutout already proven by another locator;
- heavily overlapping/near-duplicate candidates do NOT become a visual unit;
- ambiguous geometry still abstains;
- locator matching still never creates/crops/segments/moves an asset.

### Story activation

One semantic intent can now generate AssetActivation for every real cutout in its proven
visual unit.

All members inherit the same authored:
- semantic_unit_id
- script_text
- semantic_group_id
- sequence_order
- binding_type
- forced-aligned phrase timing

This is compatible with Story sequence windows because same-sequence-order members are
already defined as one simultaneous visual unit.

Evidence includes:
`visual_identity_multi_cutout_member`

Diagnostics now report:
- `real_asset_ids`
- `member_count`
- reason `accepted_multi_cutout_visual_unit`

### Loader contract hardening

If an Asset-Level Semantic package declares `cutout_mapping_cardinality`, the loader
now validates that it is:

`ZERO_OR_ONE_OR_MANY`

Omission remains backward compatible.

### Real package extraction / identity QA

Using the actual uploaded 40-scene package with the production code path:

- Vision detections: 157
- Pass1 cutouts: 157
- Pass2 cutouts: 179
- Pass2 additions: +22
- authored visual locators: 107
- one-to-one locator intents: 99
- multi-cutout locator intents: 8
- real cutouts assigned through those 8 visual units: 30
- unresolved authored locators after fix: **0**
- locator intent resolution coverage: **107/107 = 100%**

This is identity QA only. No claim is made here that a full final video render/audio QA
was run, because this checkpoint was performed from the uploaded Final Package without a
new narration/audio render request.

### Regression coverage

Added tests prove:
- one locator can resolve to several spatially distinct cutouts;
- a multi locator cannot steal an individually proven cutout;
- multiple real assets receive the same semantic intent/sequence/timing;
- old ambiguous overlapping-candidate case still abstains;
- incompatible cutout cardinality metadata is rejected.

### Proven CI

Tested code HEAD:
`592c6d111a03d33f19ec17e3755677cae96900d8`

GitHub Actions:
- Run: `35888006842`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **233 passed, 11 warnings in 7.27s**

### Do not regress

- Preserve Pass1 + Pass2 only.
- Do not lower one-to-one locator confidence/margin thresholds to gain coverage.
- Multi-cutout matching must only run after strict one-to-one matching abstains.
- Do not treat overlapping duplicate masks as a valid visual unit.
- Do not let a multi locator steal a real cutout reserved by a stronger locator.
- Same semantic intent may legally map to ZERO, ONE, OR MANY real cutouts.
- Multi members must share the authored semantic intent and sequence order.
- Visual Locator remains identity metadata only; never crop/layout/motion authority.
- The 22 assets without locator in this real package remain valid and use the legacy
  semantic path; do not invent locators for them in StoryEngine.


## MONTAGE20 FINAL PACKAGE → MOTION ORDER AUTHORITY — 2026-09-23

This checkpoint makes Final Package semantic ordering an explicit Motion authority and
closes the observed 1→2→3 becoming 3→2→1 / layout-order problem.

### Root cause

Motion was deterministic, but it was not always semantically authoritative.

Story already preserved Final Package:
- `semantic_group_id`
- `sequence_order`
- `group_animation_policy`
- aligned phrase timing

and Story V2 already allocated ordered windows for distinct `sequence_order` values.

However MotionPlanner still iterated raw Composition `layout.items` and passed that
layout index into motion/timing decisions. Extraction/layout order is not guaranteed to
equal semantic Final Package order.

A second gap existed for Visual Locator one-to-many bindings:
one semantic intent may map to several real cutouts. Those cutouts correctly share one
Story semantic window, but Motion had no explicit internal ordering authority.

### Authority hierarchy

The production rule is now:

```
Final Package sequence_order
        ↓
Story preserves semantic order + owns outer timing window
        ↓
MotionOrderResolver
        ↓
Motion executes semantic order
        ↓
Internal visual-unit order only when one semantic intent has multiple cutouts
```

Final Package `sequence_order` is authoritative over:
- extraction order
- cutout ID ordering
- Composition item list ordering
- incidental layout index
- asset size

Motion MUST NOT reverse an authored semantic order.

### New MotionOrderResolver

New file:
`app/motion/order.py`

For every Composition item it creates an explicit Motion ordering slot.

If an AssetActivation comes from:
`source = final_package_semantic_binding`

and carries:
- semantic_group_id
- sequence_order

then ordering source becomes:
`final_package_sequence_order`

Otherwise legacy/layout order remains the conservative fallback.

No scene IDs, Black Hat terms, cybersecurity vocabulary, fixed asset counts, or package-
specific rules are used.

### Multi-cutout internal ordering

When Visual Identity proves:
one semantic intent -> multiple real cutouts

through evidence:
`visual_identity_multi_cutout_member`

Motion may derive an internal reveal order WITHOUT changing Story's outer semantic order
or Composition geometry.

Generic internal rule:
1. If previous and next semantic steps exist, follow the authored spatial direction from
   previous-step centroid toward next-step centroid.
2. If only next exists, flow from current-group centroid toward next.
3. If only previous exists, flow away from previous toward current-group centroid.
4. If neither exists, follow the dominant authored spatial axis.
5. If members occupy effectively the same position and differ materially in visual size,
   use small -> large only as a deterministic tie-breaker.
6. Original layout order is the final stable tie-breaker.

This is a generic geometry rule, NOT a special rule for cards.

### Story timing remains authority

Motion does not invent a new semantic time window.

For a multi-cutout visual unit:
- first member begins at the Story-owned reveal boundary;
- members are staggered only inside that Story window;
- final member completes at Story-owned settle;
- if the window is too short to stagger safely, the unit remains simultaneous.

The outer phrase timing remains WhisperX / Story authority.

### Simultaneous visual units

If:
`group_animation_policy = SIMULTANEOUS_VISUAL_UNIT`

Motion does NOT internally stagger the members.

### Pass2 family protection

If several members share the same Pass2 `asset_family_id` and are rendered as family
canvases, Motion does NOT split their reveal timing.

Reason:
family-main / family-secondary layers may jointly reconstruct one authored visual. A
stagger must never expose a temporary hole, missing child, or parent reconstruction
artifact.

Pass1 / Pass2 behavior is unchanged.

### Renderer protection

The renderer historically kept primary artwork visible from beat start to prevent a
blank canvas. That behavior could defeat a deliberately ordered multi-cutout reveal.

Renderer now preserves that primary-beat protection for normal assets, but does NOT
force early visibility for an explicitly staggered internal visual unit.

Final authored Composition position remains unchanged.

### Motion diagnostics

Each MotionCue now records:
`params.motion_order`

including:
- source
- semantic_group_id
- semantic_unit_id
- sequence_order
- internal_index
- internal_count
- stagger_applied

This makes ordering explainable and testable in production diagnostics.

### QA contract

StorySyncQA now rejects:
- reversed Final Package semantic order;
- collapsed explicitly scheduled sequence steps;
- incomplete internal visual-unit ranks;
- reversed internal visual-unit order;
- collapsed internal stagger when stagger was declared;
- final internal member missing the Story-owned settle target;
- internal member starting before or settling after its Story outer window.

QA allows earlier members in one internal visual unit to settle before the outer final
settle, because that is intentional choreography. The final member must close the Story
window.

### Tests

New:
`tests/test_motion_final_package_ordering.py`

Regression coverage proves:
1. input layout deliberately 3,2,1 -> Motion outputs Final Package 1,2,3;
2. locator-backed multi-cutout units receive deterministic internal geometry-flow order;
3. same-position visual members can use small->large only as a tie-breaker;
4. SIMULTANEOUS_VISUAL_UNIT stays simultaneous;
5. Pass2 family-canvas members are never split.

Existing Motion / Story / Render tests continue to pass.

### Real Final Package adversarial validation

Package:
`HEXA_BLACK_HAT_HACKER_AR`

Validation used the actual current 40-scene Final Package and deliberately reversed the
input semantic layout order before running the tested MotionOrderResolver.

Result:
- scenes checked: 40
- scenes preserving Final Package sequence authority: 40
- failures: 0
- result: PASS

This verifies the implementation against the current real package while remaining
topic-agnostic.

### Tested checkpoint

Behavior HEAD:
`d96fd8dcb40eadc788cf065bbc936614bcad336d`

GitHub Actions:
- Run: `35896640956`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **238 passed, 11 warnings in 5.33s**

### Do not regress

- Final Package sequence_order outranks layout/extraction/index ordering.
- Motion must never silently reverse a trusted Final Package order.
- Story/WhisperX retain outer timing authority.
- Motion only owns internal HOW/order execution inside the allowed Story window.
- Internal one-to-many ordering must be deterministic and generic.
- Do not hardcode cards, hackers, finance, medicine, scene IDs, or asset counts.
- Do not apply small->large globally; it is only a geometric tie-breaker.
- SIMULTANEOUS_VISUAL_UNIT must remain simultaneous.
- Pass2 family-canvas reconstruction must remain simultaneous.
- Do not change Composition final positions to solve ordering.
- Do not modify Pass1/Pass2 to solve ordering.
- Do not touch text behavior for Motion ordering work.
- If reliable Final Package order is absent, preserve conservative legacy/layout fallback.


## MONTAGE20 ORDERED MOTION WHITE-FLASH FIX — 2026-09-23

This checkpoint fixes the first production failure discovered after enabling strict Final
Package motion ordering.

### Production failure

User Windows run:
- job: `94c9b958d6e34c7e9ac189e0bca6a564`
- build HEAD: `70ad5e67a0ca2d75f640a5c1c9ce9659a9d4559c`
- package: `HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_SCENE_PACKAGE_V1_FINAL_SEMANTIC_ARCHITECTURE.zip`
- Pass1: 157 assets
- Pass2: 179 assets
- Story: 40 beats
- Motion/Authoring QA: PASS
- Render: completed
- Final Recovery failure: `VISUAL_WHITE_FLASH`

Detected internal near-white frames:
- frame 643 / 21.433333s
- frame 704 / 23.466667s
- frame 705 / 23.500000s

### Root cause

The strict Motion ordering checkpoint intentionally stopped the renderer from forcing every
primary member of an ordered multi-cutout visual unit visible from beat start.

That preserved 1→2→3 ordering, but created a new boundary case:

```
new beat starts
white canvas exists
first ordered incoming cue starts slightly later
no persistent previous asset exists
=> one or more pure/near-white frames
```

The previous renderer primary-visibility guard had prevented this for ordinary primary
artwork. Ordered visual units bypassed that guard so later members could not appear before
their authored stagger, but no replacement visual carrier had been selected.

### Fix

`app/render/renderer.py` now selects one `visual_carrier_id` whenever:

- the current beat has visible layout items; and
- no true persistent asset already spans the beat boundary.

The carrier is the earliest planned incoming visual according to:
1. Motion cue start;
2. Final Package sequence_order;
3. internal visual-unit rank;
4. stable authored layer order.

Only that ONE earliest incoming layer is visible from frame zero.

Important:
- its Motion cue does NOT start early;
- its transform still begins at the authored cue time;
- later ordered members remain hidden until their own reveal times;
- 2/3 cannot become visible before 1;
- unrelated outgoing artwork is still NOT carried across beats;
- no alpha ghost crossfade is reintroduced;
- Composition final geometry is unchanged;
- Story / WhisperX timing is unchanged;
- Pass1 / Pass2 are unchanged;
- Visual Locator is unchanged.

If the selected carrier is an alpha-only reveal layer, its boundary carrier visibility
takes precedence over the alpha fade so a white frame cannot remain before its cue.

### Regression test

Extended:
`tests/test_renderer_handoff_continuity.py`

New FFmpeg integration regression creates:
- previous beat artwork;
- new ordered visual unit with two members;
- first ordered member intentionally delayed by 0.20s after the beat boundary;
- second member staggered later.

Assertions prove:
- encoded boundary frame is not white;
- first semantic member is visible as the boundary carrier;
- second member is still absent before its own reveal;
- `RecoveryDetector._white_flash_frames()` returns no internal flashes.

Therefore the fix preserves semantic ordering while removing the blank-frame failure.

### Proven CI

Behavior HEAD:
`cf186ced587d1867762e45c68c20eb10c1d7b8e2`

GitHub Actions:
- Run: `35900113411`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **239 passed, 11 warnings in 6.82s**

### Do not regress

- Do not restore blanket early visibility for every member of an ordered visual unit.
- Exactly one incoming carrier may cover an otherwise blank beat boundary.
- Carrier selection must respect semantic/Motion order.
- Later ordered members must keep their own reveal times.
- Do not solve this by carrying unrelated previous-scene artwork.
- Do not solve this with translucent crossfades that create ghost silhouettes.
- Do not disable `VISUAL_WHITE_FLASH` QA.
- Do not weaken Final Package sequence_order authority.


## MONTAGE20 FINAL PACKAGE 1.1 → STORY/CHOREOGRAPHY/MOTION INTEGRATION — 2026-09-23

This checkpoint consumes the user's new validated Final Package semantic contract as
authoritative Story/Choreography input and strengthens Motion without reopening the
previous collision/wobble regressions.

### Real Final Package inspected

Project:
- `HEXA_WHITE_HAT_HACKER_AR`
- scenes: 35
- semantic assets: 145
- semantic groups: 35
- precise asset script spans: 145
- authored visual locators: 112
- relations: 14 across 13 scenes
- visual_focus fields: 12
- visual_state fields: 4
- continuity fields: 0 (intentional omission under MINIMUM USEFUL METADATA)
- package validation: PASS

The package uses the intended additive 1.1 contract:
- group phrase may be wider than asset phrase;
- asset `script_text + script_span` identifies the smallest trusted visual phrase;
- relations describe semantic interaction, never pixel motion;
- focus/state/continuity are optional;
- omission is valid;
- timing remains WhisperX/Story-owned;
- geometry remains Composition-owned;
- Motion owns HOW.

### Loader contract upgrade

`app/input/loader.py` now:
- allows semantic group phrase != precise asset phrase;
- validates half-open `script_span` exactly against canonical script bytes/characters;
- validates relation subjects/objects/results against real semantic assets in the scene;
- validates relation confidence and optional relation span;
- validates optional `visual_focus`;
- validates optional semantic `visual_state`;
- validates optional conservative continuity schema;
- keeps all new metadata optional/backward compatible.

It does NOT require optional metadata on simple scenes.

### Story integration

Story now consumes Final Package asset-level semantics rather than leaving them in JSON.

`AssetActivation` carries:
- precise phrase/span timing identity;
- semantic group/order;
- visual_focus;
- visual_state;
- continuity.

`PackageStoryInterpreter` imports:
- semantic asset entities;
- `FINAL_PACKAGE_ASSET_RELATION`;
- relation-specific result intent;
- authored focus/state/continuity evidence.

Visual binding reuses locator-proven Story activations before geometry heuristics.

Exact `script_span` is used before phrase search, so repeated phrases resolve to the
authored occurrence rather than whichever duplicate appears first.

### Sequence-order reconciliation

Real-package QA exposed four cases where precise phrase starts alone could reverse the
authored visual sequence.

Story now reconciles a sequential semantic group only when exact speech anchors would
collapse or reverse `sequence_order`.

Authority remains:
1. exact phrases define trusted semantic/speech evidence;
2. Final Package sequence_order defines visual progression;
3. Story allocates ordered sub-windows inside the available semantic group envelope;
4. WhisperX still provides actual spoken times.

This is generic; no scene IDs or cybersecurity vocabulary are hardcoded.

### Choreography patterns

Added generic reference-style choreography patterns:
- `PROGRESSIVE_BUILD`
- `FOCUS_TRANSFER`
- `STATE_TRANSFORM`
- `CAUSE_EFFECT_CHAIN`
- `STANDARD` fallback.

Pattern priority is conservative:
1. explicit meaningful Final Package visual_state -> STATE_TRANSFORM;
2. executable explicit Final Package relation -> CAUSE_EFFECT_CHAIN
   (comparison remains comparison/focus-oriented);
3. authored visual_focus -> FOCUS_TRANSFER;
4. >=3 ordered Final Package semantic steps -> PROGRESSIVE_BUILD;
5. STANDARD.

These are semantic staging patterns, NOT animation commands from the Final Package.

### Relation support

Explicit Final Package relationships now reach executable choreography, including:
- REVEALS
- PROTECTS
- ATTACKS
- GRANTS_ACCESS_TO
- COMPARES_WITH
- CREATES
- RESULTS_IN
- REPAIRS
- REPORTS_TO
- AUTHORIZES
- DEPENDS_ON

Relation-specific result assets are preserved instead of using only a global guessed result.

### Visual focus / state authority

- Final Package visual_focus outranks size/character geometry focus heuristics.
- Locator-proven semantic activation outranks SemanticAssetBinder re-guessing.
- Explicit Final Package visual_state outranks inferred action state.

No state is invented merely because an asset appears.

### Motion safety + reference-style strength

Existing stability rule remains:
`entry / semantic action -> settle -> complete hold`.

The new patterns may add exactly ONE controlled meaning-bearing accent before settle.
No post-settle wobble/recoil is restored.

Examples:
- Progressive Build: restrained one-time build accent plus Story sequencing.
- Focus Transfer: focal asset receives the visual attention accent; supports remain calm.
- State Transform: authored changed asset gets one controlled transform accent.
- Cause/Effect: subject approaches, object reacts, result lands last according to role.

All pattern motion:
- returns to authored Composition geometry at settle;
- stays fully static after settle;
- preserves Story/WhisperX timing;
- preserves Pass1/Pass2 family-canvas safety;
- remains density-bounded;
- caps semantic interaction displacement to +/-0.06 normalized units to avoid sparse-scene
  collisions when relationship endpoints are far apart.

### Real-package architectural QA

The actual uploaded Final Package was run through the CI-tested source with synthetic
forced-alignment timestamps preserving exact canonical character identity. This validates
architecture/ordering independently of the user's narration audio.

Observed:
- package load: 35/35 scenes PASS
- Vision detections: 118
- Pass1 assets: 118
- Pass2 assets: 133 (+15)
- Story beats: 35
- Motion cues: 133
- Final Package relations imported into Story: 14/14
- authored relation interactions reaching Choreography: 14/14
- choreography patterns:
  - PROGRESSIVE_BUILD: 19 beats
  - CAUSE_EFFECT_CHAIN: 8 beats
  - STATE_TRANSFORM: 4 beats
  - FOCUS_TRANSFER: 3 beats
  - STANDARD: 1 beat
- StorySyncQA: PASS
- sync violations: 0
- max semantic settle delta: 0.0
- post-settle drift: 0

Visual Locator real-package check:
- authored locators: 112
- strict one-to-one resolved: 111
- unresolved: 1
- unresolved intent: `SCENE_026_evidence_photos`

The unresolved locator is intentionally NOT force-bound. In SCENE_026 the evidence photos
overlap/merge visually with the camera into one real Pass1/Pass2 cutout; there is no safe
independent photos cutout. The camera+photos artwork remains present as the real visual
block, but Story/Motion must not pretend the photos can animate independently.
Do NOT lower identity thresholds or reopen extraction to force this intent.

### Regression coverage

New/extended tests cover:
- wider group phrase + narrower precise asset triggers;
- exact half-open script_span validation;
- repeated phrase occurrence selected by authored span;
- relation/focus/state import into Story;
- locator-proven semantic identity reused by Choreography;
- authored visual focus outranking visual-weight heuristic;
- explicit state outranking inferred state;
- relation-specific result preservation;
- generic pattern selection;
- controlled pattern accent + complete post-settle freeze;
- precise phrases cannot reverse Final Package sequence_order.

### Proven CI

Behavior HEAD before continuity-only commit:
`7506db711949f8b9fd23e9f36a9cd6e9e6ebc872`

GitHub Actions:
- Run: `35912228793`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **249 passed, 11 warnings in 6.83s**

### Do not regress

- Pass1 + Pass2 only. Never reintroduce Layer3.
- Final Package is semantic authority.
- WhisperX remains actual speech timing authority.
- Composition remains final authored geometry authority.
- Motion never invents semantic meaning absent Story/Final Package evidence.
- visual_locator remains identity metadata only.
- Do not require optional metadata on every asset.
- Do not infer continuity when the package intentionally omits it.
- Do not hardcode topic nouns, scene IDs, or fixed asset counts.
- Do not let precise phrase timing reverse reliable sequence_order.
- Do not let sequence_order erase precise phrase identity.
- Do not restore post-settle oscillation.
- Do not lower locator thresholds to improve coverage.
- Do not animate an unresolved semantic intent as an independent cutout.


## MONTAGE20 → MONTAGE17 HANDOFF — REFERENCE-GRADE MOTION / FOCUS / TEXT SYNC — 2026-09-23

This is the official takeover checkpoint for the next conversation, named `Montage17`.

### Live repository state at handoff

Repository:
`majdba123/HEXA-StoryEngine`

Working branch:
`montage` ONLY.

Live HEAD verified:
`02eb19cce9c8c571be8f2f33258110f1a33995a9`

HEAD message:
`[continuity] Record Final Package semantic choreography integration`

Draft PR:
- #1
- base: `majd`
- head: `montage`
- do NOT merge unless the user explicitly asks.

Latest CI:
- Run: `35912434619`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **249 passed, 11 warnings in 6.20s**

All previously accepted behavior commits are present under this HEAD, including:
- `f0e1d30b4d2518b71c2f7f08e6abd25a7d4f40f1`
  `[story] Consume precise Final Package semantic contract`
- `1c24cecd3282b44def5c681c9594f811a1f0dc3a`
  `[tests] Correct precise semantic span fixture`
- `920d3146b1031328d27b2b89c18f8bdf3b9f009d`
  `[motion] Drive choreography from Final Package semantics`
- `2821728e57baca0c252f48d7f07ec2cea82ab96e`
  `[story] Reconcile precise phrase timing with authored sequence order`
- `7506db711949f8b9fd23e9f36a9cd6e9e6ebc872`
  `[motion] Bound semantic interaction displacement`
- `8080367aeecff53233dfba0d1abe3af679df4d48`
  `[continuity] Record ordered-motion white-flash fix`

No stronger-motion/focus/text-sync implementation was committed after the above continuity checkpoint.
The user's latest request is the NEXT PHASE, not already-completed behavior.

### Immutable architecture / do not regress

- Pass1 + Pass2 only.
- NEVER reintroduce Layer3 / Pass3.
- Final Package is semantic authority.
- WhisperX / forced alignment remains actual speech timing authority.
- Story owns WHAT + semantic WHEN.
- Choreography owns semantic visual relationship / progression.
- Motion owns HOW.
- Composition owns final authored geometry.
- Visual Locator is WHICH VISUAL only, never crop/segmentation/motion/target position.
- No scene/topic/count hardcoding.
- No post-settle wobble/recoil.
- No collision/relayout.
- Final positions must remain exactly authored.
- No white rectangles / pre-shadows / ghost alpha crossfades / early reveal regressions.
- If ambiguous, abstain/fallback conservatively.
- Text wording/selection behavior remains the restored OLD behavior.
- Text visual style/size remains the accepted current renderer style.
- Do NOT redesign text selection, typography, size, or composition unless the user explicitly asks.

### New Final Package 1.1 is considered CLOSED

The user explicitly wants the new Final Package semantic contract treated as complete.

The uploaded current 1.1 package already proved:
- 35 scenes
- 145 semantic assets
- 145 precise asset script spans
- 14 relations
- 12 visual_focus
- 4 visual_state
- 0 continuity by intentional omission
- package validation PASS.

Story/Choreography integration for this contract is already implemented and CI-proven.

Do NOT respond to future visual problems by inventing more Final Package metadata.
First inspect Story/Choreography/Motion/Text Motion consumption.

### IMPORTANT: current reviewed video is from the OLD Black-Hat package

User uploaded for review:
`HEXA_BLACK_HAT_HACKER_AR(4).mp4`

Media:
- duration: ~97.07 s
- 1920x1080
- 30 fps
- H.264
- AAC mono 44.1 kHz.

The matching Black-Hat Final Package available during review uses the OLD semantic contract:
- 40 scenes
- 129 semantic assets
- 107 visual locators in the locator-enabled variant
- **0 precise asset script_span**
- **0 visual_focus**
- **0 visual_state**
- **0 scene relations**

Its assets generally share the whole semantic-group phrase.

Example:
SCENE_003:
- decision_compass
- protected_shield
- open_lock

All three are bound to:
`لكن الهدف مختلف تمامًا.`

Therefore this video CANNOT fully demonstrate the new 1.1 package's exact word→asset synchronization or authored focus/state/relations.
Some apparent early reveal / weak hierarchy in this video is caused by the old coarse phrase-level contract, not by the new Final Package.

Do not use this fact as an excuse to leave Motion weak. It is a diagnostic boundary:
- exact word identity improves with the new package;
- reference-grade hierarchy/choreography still needs stronger Motion/Text Motion execution.

### Visual review of HEXA_BLACK_HAT_HACKER_AR(4).mp4

Overall:
- clear improvement over older broken/collision versions;
- element identity/order is much more coherent;
- composition is clean;
- no obvious catastrophic collisions;
- progressive sequencing exists in several places;
- BUT it still feels like `elements appear into a composed scene` more than `the idea happens visually in front of the viewer`.

Primary remaining gap is NOT extraction.
Primary remaining gap is NOT Final Package metadata.
Primary remaining gap is **Motion hierarchy + semantic focus transfer + visual/text synchronization strength**.

#### 0.0–4.0 s

Observed:
- main black-hat character, broken lock, warning shield;
- next scene character + laptop;
- readable, but multiple saturated objects quickly reach equal visual importance;
- text arrives as a separate overlay rather than feeling like the same attention event.

Diagnosis:
- hierarchy is too flat;
- one beat-level primary is not enough;
- the currently spoken semantic unit needs temporary focal authority.

#### 5.5–9.5 s

Observed:
- compass scene then shield/open-lock progression;
- `الهدف` appears after some related visuals are already visible;
- then researcher/cracked-shield scene.

Important:
Because old SCENE_003 binds all three assets to the same full phrase
`لكن الهدف مختلف تمامًا.`, Story cannot know exact per-word identity in this old package.

Still, Motion should:
- make one semantic step focal at a time;
- avoid making future result/support artwork equally readable too early;
- keep exact sequence while increasing focus transfer.

This is the clearest example of apparent visual semantic lead.

#### 12.5–16.5 s

Observed:
- hourglass -> eye -> broken device/shield -> identity cards -> character/bag;
- sequencing works, but cards/support objects become visible with nearly the same visual authority;
- `حسابات` text appears after the cards are already visually established.

Diagnosis:
- progressive build exists but does not transfer focus strongly enough;
- later ordered members should receive their own momentary focal hit when their phrase is active.

#### 18.2–23.2 s

Observed:
- character/company -> shields -> hacker/device -> laptop/phone/camera -> malware targeting composition.

Diagnosis:
- semantic order is understandable;
- motion is still primarily `entry -> settle -> hold`;
- relationships are represented by static layout more than by cause/effect choreography.

#### 50.2–57.2 s

Observed:
- server/folder/identity/lock sequence;
- many blue/gold elements share similar saturation/visual mass.

Diagnosis:
- scene can be semantically correct while eye priority stays ambiguous;
- focal asset needs stronger readable motion than contextual/support assets.

#### 59.3–65.5 s

Observed:
- door/key/broken shield/hacker progression;
- calendar sequence around ~64–65 s is one of the better progressive-build examples.

Diagnosis:
- ordering is good;
- each calendar/step still needs a clearer micro-focus handoff instead of all members becoming equal after reveal.

#### 90.3–97.0 s

Observed:
- hacker + stolen account/profile cards -> money/data bag;
- progressive card reveal is coherent.

Diagnosis:
- this is structurally close to the desired behavior;
- final/result bag needs a stronger payoff/focus hit;
- supports should stop competing once the result is established.

### What the reference videos do better

Reference videos reviewed:
- `تأثير المتفرج2.mp4`
- `انحياز 2.mp4`

The important difference is NOT simply `more movement everywhere`.

References concentrate movement into semantic attention events:

1. **Progressive visual construction**
   - arrows/icons/results build one after another;
   - each addition changes meaning.

2. **Focus transfer**
   - the eye clearly moves from A -> B -> C;
   - prior context becomes visually secondary;
   - the new focal object is unmistakable.

3. **Cause/effect staging**
   - source action -> target reaction -> result;
   - not just three independent reveals.

4. **State/payoff hits**
   - result/check/x/large arrow/change receives a decisive visual beat.

5. **Text and visual feel like one event**
   - keyword arrives at the semantic moment;
   - it reinforces the currently focused object/result;
   - text does not feel like a parallel independent layer.

6. **Selective energy**
   - references are not uniformly hyperactive;
   - important moments are stronger while context stays calm.

Do NOT solve this by globally increasing every amplitude.
That would create collisions and destroy hierarchy.

### Current code-level gaps that Montage17 must inspect first

#### 1. One fixed primary item per whole beat is too coarse

Current `MotionPlanner` computes one `primary_item` for the beat.

Problem:
In a progressive semantic group 1 -> 2 -> 3, item 2 and item 3 can remain `support` for the whole beat even when their own spoken semantic window becomes active.

Current PROGRESSIVE_BUILD accent is also restrained:
- primary scale ~1.035
- support scale ~1.018 before energy/density scaling.

Result:
ordered assets appear correctly but do not each become visually dominant at their own semantic moment.

Required direction:
derive **momentary semantic focus per activation/window**, not only one static beat-level primary.

#### 2. Pattern strength is still below reference readability

Current patterns:
- PROGRESSIVE_BUILD
- FOCUS_TRANSFER
- STATE_TRANSFORM
- CAUSE_EFFECT_CHAIN

Architecture is correct.
Strength/readability still needs calibration.

Increase semantic distinction, not random movement:
- focal/primary/result: stronger pre-settle scale/translation;
- support: restrained;
- context: calm;
- result: strongest payoff when justified;
- dense scenes: stricter caps;
- short beats: conservative fallback.

Always:
`meaning-bearing movement -> settle at authored Composition geometry -> total hold`.

No post-settle bounce.

#### 3. Progressive Build must create a real hierarchy wave

Every ordered semantic step should be allowed a short focal moment during its own Story window.

Do NOT animate all items equally.

Desired:
`context stays readable -> step 1 focus -> step 2 focus -> step 3/result focus`.

#### 4. Cause/effect role differentiation must be more visible

For explicit relations:
- SUBJECT: approaches/directs attention toward object;
- OBJECT: reacts;
- RESULT: lands last with strongest readable payoff.

Keep displacement bounded.
Do not physically collide objects.

#### 5. Text anchor selection is currently too beat-primary-oriented

Current `TextPlanner` generally chooses:
`directive.primary_asset_id`
as `anchor_asset_id`.

This is too coarse for precise Final Package 1.1.

TextCue already has exact canonical source spans.
AssetActivation already has exact trigger spans from Final Package.

Recommended:
resolve the text cue anchor by **overlap between TextCue source_char span and Story AssetActivation trigger_char span**, then use choreography primary only as fallback.

This improves:
`spoken phrase -> exact text -> exact visual asset`
without changing text selection, wording, style, size, or placement system.

#### 6. Text Motion and Visual Motion are not yet strongly coupled

Pipeline already computes visual Motion before Text Motion.

Current TextMotionPlanner:
- starts cue at spoken_start;
- starts token at token.spoken_start;
- this is GOOD and must remain;
- but it does not consume the visual motion cue of its anchor asset.

Recommended:
let TextMotionPlanner receive visual Motion (or a compact sync map).
For the cue's resolved anchor asset:
- preserve text/token spoken_start exactly;
- coordinate its visual emphasis/entry completion with the anchor's semantic settle/Story semantic peak;
- do NOT shift words earlier than speech.

This is a synchronization-strength improvement, not a text-content redesign.

#### 7. Text renderer entry is fixed and semantically flat

Current first-line ASS gesture is roughly:
- 14 px horizontal move
- 10 px vertical move
- 165 ms
- 65 ms fade

for all semantic importance.

Do NOT change font/style/size.
But Montage17 may make entry-strength parameters driven by TextMotionCue semantic role/focus:
- stronger result/warning/emphasis entry;
- calmer support keyword;
- same final x/y/font/size/style.

No bounce after arrival.

#### 8. Audit anti-white-flash visual carrier for semantic lead

The renderer's visual-carrier fix is necessary and must NOT be removed.

But a carrier can make the first incoming semantic asset visible from beat boundary before its authored cue motion begins.

Audit:
- prefer safe CONTEXT/actor/background-like real asset as boundary carrier when available;
- do not use a future RESULT/semantic step as early carrier merely to avoid white;
- later ordered members must stay hidden;
- no unrelated previous-scene carry;
- no ghost crossfade;
- if no better carrier exists, keep the proven conservative behavior and document the limitation.

Do NOT reintroduce VISUAL_WHITE_FLASH.

### Required acceptance behavior for next phase

The target is:
**at minimum the same semantic-motion clarity / attention hierarchy spirit as the two references**, while preserving HEXA's authored illustration style and current architecture.

For every significant scene, viewer should understand without narration alone:
- what to look at first;
- what appeared because of what;
- what changed;
- what is the result;
- where attention moved next.

Text should reinforce the same focal event.

### Strict tests Montage17 should add

Must stay generic:
- 1 asset;
- 3 ordered assets;
- 20 dense assets;
- 0.5 s beat;
- 8 s beat;
- fast narration;
- slow narration;
- real-photo-like geometry;
- illustration geometry;
- comparison scene;
- relation scene;
- state transform;
- same visual intent -> multiple real cutouts;
- family-canvas Pass2 asset;
- unresolved semantic intent;
- text cue overlapping exact asset script_span;
- duplicate phrase with distinct script spans.

Assertions:
- sequence order never reverses;
- focal step has stronger readable pre-settle motion than support/context;
- result emphasis > support when authored/derived;
- no post-settle drift;
- no final geometry changes;
- dense-scene displacement caps hold;
- family-canvas stays footprint-locked;
- text start == spoken_start;
- token start == token spoken_start;
- text anchor maps to matching activation span when available;
- text does not start before speech;
- visual semantic step does not lead its Story window beyond tolerance;
- no white-flash regression.

### Real validation required

After code tests:
1. run CI;
2. run the NEW Final Package 1.1 with real narration audio;
3. produce a full render;
4. compare representative strips against both references;
5. visually inspect:
   - focus hierarchy;
   - exact semantic reveal timing;
   - text/visual coupling;
   - cause/effect readability;
   - state/result payoff;
   - collision/ghost/white-flash regressions.

Do not claim `reference-grade` from unit tests alone.

### Next-owner startup behavior

Montage17 must:
1. read this continuity file fully;
2. verify live repo / branch / HEAD / CI;
3. inspect current code before editing;
4. confirm that Final Package 1.1 integration is already complete;
5. state clearly that the next work is **Motion hierarchy/focus + Text Motion synchronization**, not extraction and not Final Package redesign;
6. include a concise visual review of `HEXA_BLACK_HAT_HACKER_AR(4).mp4` in its first response;
7. then implement conservatively on `montage`.

## MONTAGE17 MOMENTARY SEMANTIC FOCUS + TEXT/VISUAL SYNC — 2026-09-24

Development branch: `montage`.

### Real video review used for this implementation

Reference videos were reviewed directly frame-by-frame:
- `تأثير المتفرج2.mp4` — ~72.92 s / 854x480 / 25 fps.
- `انحياز 2.mp4` — ~79.33 s / 854x480 / 30 fps.

Current HEXA renders reviewed directly:
- `HEXA_BLACK_HAT_HACKER_AR(5).mp4` — 97.066667 s / 1920x1080 / 30 fps.
- `HEXA_WHITE_HAT_HACKER_AR(1).mp4` — 99.20 s / 1920x1080 / 30 fps.

The references confirmed that the target is NOT globally stronger motion. Their readability comes from:
- short semantic attention events;
- one new focal element at a time;
- previous context holding still;
- progressive construction;
- clear subject -> object -> result staging;
- decisive result/payoff hits;
- text and the focused visual feeling like the same event.

Observed current HEXA behavior before this checkpoint:
- both renders are much cleaner than older broken/collision versions;
- order and authored composition are generally coherent;
- White-Hat benefits from the newer semantic package contract and shows stronger semantic sequencing;
- the main remaining gap is still hierarchy: after reveal, several elements quickly become equal in visual authority;
- Black-Hat around ~12.8-16.4 s shows good ordered construction (hourglass -> eye -> broken device -> cards/bag) but weak focus handoff;
- Black-Hat around ~63-65.5 s shows a useful calendar progression but each step needs a clearer focal moment;
- Black-Hat ~93-97 s has coherent account-card progression into the bag, but the result/payoff is not visually dominant enough;
- White-Hat ~22-24 s progressively builds multiple protected-company visuals correctly, but all members settle to similar weight;
- White-Hat ~24.4-30.8 s correctly stages server/problem/breach concepts, but the semantic result is still not given enough visual priority;
- White-Hat ~56-63 s contains clear semantic additions/state ideas, but the motion still reads mostly as reveal -> settle rather than attention transfer;
- White-Hat ~84-99 s has a coherent concluding progression but still needs stronger selective focus.

A few pale/ghost-like secondary reveal frames are visible in the existing Black-Hat render around the digital-footprint sequence. This checkpoint does NOT change Pass2/family extraction or the proven white-flash carrier without diagnostics proving the source. Do not overfit the Motion hierarchy fix to that separate issue.

These uploaded renders predate the code below. They are diagnostic inputs, NOT proof of the new behavior.

### Root cause

`MotionPlanner` still used one beat-level `primary_item` as the main strength authority.

Even when Story V2 already gave ordered assets separate trusted semantic windows, a later semantic step could remain visually treated as support for the whole beat.

That meant:
`1 enters -> settles -> 2 enters -> settles -> 3 enters -> settles`

instead of the reference-style hierarchy wave:
`1 active focus -> hold -> 2 active focus -> hold -> 3/result payoff -> hold`.

Text had a related coarse link:
- TextPlanner normally anchored to the choreography/beat primary;
- TextMotion did not consume the visual MotionCue of its anchor;
- renderer entry gesture was fixed regardless of semantic focus.

### Motion implementation

`app/motion/planner.py` now derives a temporary semantic focus profile from the trusted Story V2 activation window.

Authority:
- Story/Final Package still owns WHICH semantic unit and WHEN;
- Motion only increases the pre-settle gesture during that unit's own trusted window;
- SAFE_ABSTENTION/missing windows never gain invented focus;
- `visual_focus=CONTEXT` remains calm;
- explicit RESULT semantics remain the strongest payoff;
- after settle every asset returns to exact authored Composition geometry and total hold.

Focus metadata is exported on each MotionCue:
- `active`
- `role`
- `source`
- `visual_focus`
- trigger character span

Strength is role-aware:
- active semantic focus > inactive support;
- RESULT > support when explicitly authored/derived;
- SUBJECT keeps bounded directional relationship motion;
- OBJECT receives a clearer reaction;
- ACTOR remains restrained;
- CONTEXT remains calm.

Pattern calibration was strengthened conservatively:
- STANDARD can receive a restrained focus accent only when Story proves an active semantic window;
- PROGRESSIVE_BUILD gives each active ordered step its own focal accent;
- FOCUS_TRANSFER has a stronger focal hit;
- STATE_TRANSFORM gives the authored state target the strongest state accent;
- CAUSE_EFFECT_CHAIN differentiates subject/object/result more visibly.

No post-settle bounce/recoil was added.

### Density safety

Motion strength remains density-bounded.

Sparse scenes may use stronger focus/result scale accents.
As density increases, offset and scale caps tighten.
20-element scenes retain the existing <= 0.045 normalized displacement cap for focused items and stricter support bounds.

Final authored geometry is unchanged.

### Text exact semantic anchor

`app/text/planner.py` now resolves `anchor_asset_id` using canonical character-span overlap:

`TextCue source_char span -> AssetActivation trigger_char span -> real asset`

Ranking uses:
- cue-span overlap;
- activation-span overlap;
- activation confidence;
- authored visual focus;
- narrower matching activation.

When several real cutouts share the same exact semantic span, choreography primary and Story primary are preferred before a deterministic stable fallback.

If no exact overlap exists, old choreography/beat-primary behavior remains the fallback.

Text selection/wording is unchanged.
Forced-aligned spoken timing is unchanged.

### Text Motion + visual Motion synchronization

`TextMotionPlanner` now optionally consumes the already-compiled visual Motion list.

For a text cue's resolved anchor:
- text cue start remains exactly `spoken_start`;
- every token still starts exactly at `token.spoken_start`;
- visual semantic settle/focus role contributes only to bounded text entry strength/duration;
- long visual windows cannot stretch a keyword into a slow subtitle gesture.

TextMotionCue diagnostics now record:
- `entry_strength`
- `entry_duration_ms`
- visual sync availability
- anchor asset
- visual semantic settle
- focus role

### Text renderer

Typography behavior remains the user-approved restored OLD behavior.

UNCHANGED:
- word selection
- font family
- font sizes
- white fill
- black outline
- placement architecture
- final x/y
- sequential-word reveal logic.

Only the first entry gesture is now semantically bounded:
- old/no-sync path preserves the historical ~14 px horizontal / 10 px vertical / 165 ms / 65 ms fade behavior;
- focused/result text may use a somewhat stronger move, bounded to roughly 24 px horizontal / 15 px vertical and <=240 ms;
- no bounce after arrival.

### White-flash carrier

The existing visual-carrier fix remains unchanged in this checkpoint.

Reason:
- current renders show no justification for risking a `VISUAL_WHITE_FLASH` regression merely to optimize carrier semantics;
- future RESULT early-carrier cases should be fixed only with concrete diagnostics proving a safe CONTEXT/actor alternative.

### Behavior commits

- `bcbadfa0da2718aaed3afe1673b6dab177175d21`
  `[motion] Add momentary semantic focus hierarchy`
- `cfdc8d75bdee7439f31fbba9349be7d9577f7427`
  `[motion] Expose semantic focus metadata to render pipeline`
- `a2e8bbfb52c14c9e25c5f013dc018c748f57f0ac`
  `[text] Anchor keywords to exact semantic asset spans`
- `053189e300e9b12837ef8f32a55264a5ccd481e3`
  `[text] Couple text motion to visual semantic focus`
- `f040609dbd086167401207376af1f96c01cff049`
  `[pipeline] Feed visual motion into text synchronization`
- `bcc48ac77a5041819254956577bc8bf171dcee04`
  `[render] Scale text entry gesture by semantic focus`
- `7fa44fa59ae6abf68d0d4c75c7308ab40217de07`
  `[tests] Cover exact text anchors and visual text sync`
- `e715a41a225825a9439b4f330679c58f22a3e99f`
  `[tests] Cover momentary focus hierarchy and result payoff`
- `87d887331bcdd3d0f8b43e7d681d1862fb46850b`
  `[tests] Cover focus-driven text entry rendering`

Behavior HEAD before this continuity-only commit:
`87d887331bcdd3d0f8b43e7d681d1862fb46850b`

### CI proof

GitHub Actions:
- Run: `35926744734`
- Workflow: `V2 CI`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **254 passed, 11 warnings in 4.91s**

New regression coverage proves:
- ordered Story semantic windows each gain temporary focus;
- explicit RESULT payoff is stronger than non-result participants;
- final geometry/post-settle hold remains exact;
- exact text span maps to the matching asset instead of beat-primary;
- Text Motion consumes visual focus without moving text/token starts before speech;
- stronger text entry changes motion only, not font/style/size.

All existing ordering, dense-scene, Pass2 family-canvas, renderer, Story sync, text timing and white-flash regression tests remain green.

### Status

PROVEN:
- code architecture/CI for momentary semantic focus;
- role-based focus/result hierarchy;
- exact TextCue -> AssetActivation span anchoring;
- visual Motion -> Text Motion sync metadata;
- preserved text/token spoken_start authority;
- preserved final Composition geometry and post-settle freeze.

NOT YET PROVEN:
- final reference-grade visual quality from a new encoded render produced by this code;
- exact perceptual calibration of the stronger accents on the real Final Package 1.1;
- whether the pale secondary reveal seen in the older Black-Hat render comes from family alpha reveal, extraction content, or another render path.

### Next real acceptance gate

Pull latest `montage`, then run the NEW Final Package 1.1 with its real narration audio.

Review the new full render specifically for:
- focus handoff step-by-step;
- result/payoff visibility;
- cause/effect readability;
- exact narration/visual timing;
- text/visual event coupling;
- no collision;
- no ghost/pre-shadow regression;
- no white flash;
- no post-settle drift.

Do NOT claim reference-grade from CI alone.

## MONTAGE17 FOCUS ARBITRATION CORRECTION — PRECISE REV9 PACKAGES — 2026-09-24

The user supplied the actual current precise Final Packages and a new White-Hat render:
- `HEXA_WHITE_HAT_HACKER_AR_HEXA_V20_SCENE_PACKAGE_V1_REV9_PRECISE_FINAL.zip`
- `HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_SCENE_PACKAGE_V1_REV9_PRECISE_FINAL.zip`
- `HEXA_WHITE_HAT_HACKER_AR(2).mp4`

### Package evidence — Final Package is NOT the blocker

White-Hat semantic validation is PASS:
- 35 scenes
- 145 semantic assets
- 145 / 145 precise script spans
- 145 / 145 sequence orders
- 14 relations
- 12 visual_focus fields
- 4 visual_state fields
- 112 visual locators
- 0 validation errors
- 0 script-span mismatches
- 0 relation-reference errors

Black-Hat REV9 precise semantic validation is also PASS:
- 40 scenes
- 129 semantic assets
- 129 / 129 precise script spans
- 129 / 129 sequence orders
- 14 relations
- 12 visual_focus fields
- 4 visual_state fields
- 1 continuity field
- 107 visual locators
- 0 validation errors
- 0 script-span mismatches
- 0 relation-reference errors

IMPORTANT CORRECTION:
Earlier handoff analysis described an OLD Black-Hat package with coarse phrase bindings.
That statement does NOT apply to the newly supplied REV9_PRECISE_FINAL Black-Hat package.
The current Black-Hat package is precise and metadata-rich.

Concrete White-Hat examples prove sufficient semantic authority:
- SCENE_018: mutable URL action + RESULT profile; explicit REVEALS relation; result state PRIVATE -> EXPOSED.
- SCENE_023: expected vs unexpected result; explicit COMPARES_WITH relation; unexpected container has visual_focus PRIMARY and EXPECTED -> UNEXPECTED state.
- SCENE_031: report/company progression with bounty reward authored as RESULT + visual_focus RESULT.
- SCENE_028: repaired shield authored as RESULT with VULNERABLE -> REPAIRED state and REPAIRS relation.

Concrete Black-Hat example:
- SCENE_026 infected_server is semantic RESULT, visual_focus RESULT, state SAFE -> INFECTED, anchored to the precise phrase `يثبت برنامج`.

The new White-Hat render was visually matched against the supplied package scene artwork, confirming the reviewed render uses the same scene content.

### Visual acceptance failure found in White-Hat render

The package gives the correct distinctions, but Motion was flattening them.

Example:
- SCENE_023 metadata explicitly distinguishes PRIMARY unexpected-result focus/state.
- Render still makes expected and unexpected containers visually similar in authority.

Example:
- SCENE_031 metadata explicitly marks bounty_reward as RESULT.
- Render presents it mostly as the fourth added object instead of a decisive payoff.

Therefore the blocker is code-side semantic focus consumption, not missing Final Package metadata.

### Root cause in code

The first Montage17 momentary-focus implementation treated nearly every trusted Story V2 activation window as strong `ACTIVE_FOCUS`.

That conflated:
- timing authority: “this asset is semantically active now”
with
- attention authority: “this asset should dominate the viewer’s eye now”.

Because REV9 correctly provides many precise timed assets, the bug could make too many valid assets receive similar focal strength.

### Fix

Behavior commits:
- `6c2a510a27af1af68059f0663d8a017dfea10ddc`
  `[motion] Arbitrate semantic focus strength by authored role`
- `fd50d544ca875800c3c4cc6ffb123fe42fbc1667`
  `[text] Follow visual focus arbitration strength`
- `1c6f6f825cd1381b8d667738e6d92ea73fedd742`
  `[tests] Cover authored-role focus arbitration`

Motion now separates trusted timing from visual dominance.

Focus authority:
- authored visual_focus RESULT: strongest
- authored visual_focus PRIMARY: near-strongest
- relation RESULT / authored state: strong
- semantic RESULT: strong
- SUBJECT / OBJECT relation participant: medium-strong
- semantic PRIMARY / ACTION: medium
- generic ordered semantic step: moderate
- ACTOR / CHARACTER: calm
- OBJECT/SUPPORT sub-elements: restrained
- authored CONTEXT: no focal promotion
- SUPPORT binding: capped unless stronger explicit evidence overrides it

The exact Story timing remains unchanged.
Sequence order remains unchanged.
Composition/final geometry remains unchanged.
Post-settle freeze remains unchanged.

Text Motion now consumes the same numeric visual focus strength instead of treating every active anchor as equivalent.

### CI proof

Run: `35931793178`
Workflow: `V2 CI`
Result: SUCCESS
Compile: SUCCESS
Ruff: All checks passed
Pytest: **255 passed, 11 warnings in 7.30s**

### Next acceptance gate

Render the same White-Hat REV9 precise package again from latest `montage`.
The expected visible difference is NOT more global movement.
It is:
- fewer simultaneous “hero” objects;
- clearer eye priority;
- stronger authored RESULT/PRIMARY payoff;
- calmer character/support/context elements;
- text emphasis following the same focus strength;
- preserved exact timing, ordering and final authored composition.

Do not modify the Final Package contract to solve this issue.

## MONTAGE17 SEMANTIC VISIBILITY / CARRIER / TEXT SAFE-AREA HARDENING — 2026-09-24

This checkpoint follows direct visual review of the user's latest Black-Hat render and the supplied
REV9_PRECISE_FINAL White/Black packages. The Final Packages are confirmed sufficient; these fixes
belong to general Story/Choreography/Motion/Renderer/Text consumption.

### Visual failures reproduced

The reviewed render showed three distinct execution failures:

1. Future semantic visuals were visible before their narration cue.
   - Old-program scene: the later "years" result was already visible before its phrase.
   - Install scene: the server/result was visible before the install action completed.
   - Return-later scene: destination/result visuals were visible before the return action.

2. Character/context artwork could steal first attention from the semantic concept.
   - Company-discovery scene: the company manager was visually dominant before the company/discovery
     concept despite metadata being sufficient to distinguish CHARACTER / OBJECT / RESULT.

3. Arabic text could escape the screen.
   - Character-count width estimation materially under-measured shaped Noto Kufi Arabic glyphs.
   - The renderer only trusted the planned box and did not apply a final glyph-level title-safe clamp.
   - Entry motion could move an otherwise safe final position outside the frame.

A fourth issue was confirmed in renderer behavior:
- Pass2/family-canvas alpha fades could produce pale/ghost-looking reveal frames over white.

### Root causes

#### Renderer visibility leak

Renderer contained a legacy exception that made every Story `primary_asset_id` visible from the
visual beat boundary, even if its Motion/Story semantic cue started later.

Story primary may be selected from visual weight before precise semantic activation is enriched.
Therefore a large future RESULT could appear early even while Motion timing itself was correct.

This is why simply increasing/decreasing Motion amplitude could never fully repair narration sync.

#### Boundary carrier selection

The anti-white-flash carrier previously chose the earliest candidate primarily by time/order.
It did not reason about semantic risk strongly enough.

#### Character identity in semantic binding

`SemanticAssetBinder` historically detected actors mainly from scene-unit `type`.
REV9 precise packages commonly express units as `VISUAL_ASSET_INTENT` and carry the real meaning in
`semantic_role`.

Consequently a large CHARACTER could remain in normal focus competition and win by visual weight.

#### Base primitive energy

Even after focus arbitration, a non-focused CHARACTER/SUPPORT could still receive a strong entry
from its base semantic primitive. Focus strength only affected the later choreography accent.

#### Text box estimation

Text placement used character-count approximations. Arabic Kufi shaping can be far wider than those
estimates. The renderer had no final measurement guard using the actual production font geometry.

### General fixes

#### 1. Semantic visibility is now authoritative

For every non-persistent visual:
- renderer visibility begins at its Motion/Story cue start;
- Story's legacy area-ranked primary no longer forces early visibility;
- future sequence members and RESULT visuals remain hidden until their own semantic window.

Only one boundary carrier may be visible early, solely to avoid a blank/white handoff frame.

#### 2. Semantic-safe carrier arbitration

The carrier is chosen only from assets whose cue is at or very near the earliest reveal window.

Within that earliest cohort, risk ordering prefers:
- authored CONTEXT;
- early semantic OBJECT/context concept;
- CHARACTER/ACTOR;
- SUPPORT;
- ACTION;
- PRIMARY;
- unknown;
- RESULT last.

A later RESULT cannot become carrier simply because it is large.
Internal multi-cutout ordering remains respected.

This is generic and contains no scene/topic hardcoding.

#### 3. Semantic CHARACTER identity now outranks image area

Story's proven `AssetActivation.semantic_unit_id -> real asset_id` identity is reused with
`StorySemanticContext.entities[].role`.

CHARACTER/ACTOR cutouts are excluded from ordinary concept-focus competition unless:
- the package explicitly authors visual focus on them; or
- no non-character semantic visual exists.

This fixes the class of failures represented by the company-discovery scene without coding for
"company", "manager", or any scene id.

#### 4. Base entry motion now obeys attention authority

A new attention budget scales the pre-settle primitive itself:
- RESULT / explicit focus keeps strong entry authority;
- PRIMARY / ACTION / relation participants remain readable;
- explicit semantic OBJECT may become a real momentary focus;
- CHARACTER / ACTOR entry is calmer;
- SUPPORT is more restrained;
- CONTEXT is quietest.

Final geometry, Story timing, sequence order and post-settle freeze remain unchanged.

#### 5. Explicit semantic objects can receive focus

An EXPLICIT Final Package OBJECT with its own precise activation is no longer automatically treated
as weak support. It can receive moderate momentary focus.

This is required for phrases such as a company/object concept followed by a discovery/result while
the character remains contextual.

#### 6. Family-canvas reveals are crisp

Renderer no longer alpha-fades geometry-locked family members over white.
Their authored alpha is preserved and visibility is gated at the semantic cue boundary.

This removes the pale/ghost silhouette mechanism without moving or scaling the family footprint.

#### 7. Production Arabic glyph measurement

New:
`app/text/metrics.py`

It measures text using the production Noto Kufi heavy face with Pillow/RAQM when available.
- Exact glyph width/height is used instead of character count.
- ExtraBold is preferred for Noto Kufi so metrics do not under-measure a heavier rendered face.
- Cross-platform font lookup supports environment override and common Linux/macOS/Windows font roots.
- Fontconfig is used through the existing hidden-subprocess wrapper when available.
- A conservative fallback remains when exact font measurement is unavailable.

#### 8. Final renderer title-safe clamp

TextRenderer now performs a final glyph-level safety pass:
- measures the full shaped phrase;
- includes horizontal/vertical entry excursion;
- clamps the final anchor to 4.5% horizontal / 5.5% vertical safe margins;
- applies a bounded emergency scale reduction only when required to prevent clipping;
- preserves wording, font family, visual style, outline and placement intent.

This protects both the resting position and the first moving text frame.

### Behavior commits

- `621b460207698582701d76adfc8d954bf2789a49`
  `[text] Measure production Arabic glyph bounds`
- `90b0a91092370a7e2f8faac376a18ad4efeaf5e2`
  `[text] Use shaped glyph bounds for placement`
- `b43348326ba50b8bb6ee85368127735efba91375`
  `[story] Exclude semantic characters from focus competition`
- `17f3a73e07ada2702c08c0aedfaa2d88c2211263`
  `[motion] Enforce attention hierarchy on base entrances`
- `ab7877bd1c88bebb49098a43ddd0644e626ab10b`
  `[render] Enforce semantic visibility before motion`
- `b5e81654cabb7ab9573dc13e8e07a7e02211b4cb`
  `[render] Keep shaped Arabic text inside safe area`
- `8825a8bde8650210ecc59885f5dcb67306ab8578`
  `[tests] Cover semantic character focus suppression`
- `cd1f5028a47d24b0740f3a689bc1bec0180460f1`
  `[tests] Cover semantic visibility carrier and crisp reveals`
- `e6606c43abfed475ec52be41b8ed43052f8c20f9`
  `[tests] Cover real Arabic glyph width measurement`
- `0006eb87f70f641c0bfa04dc162a56313a03f89a`
  `[tests] Cover final Arabic title-safe clamp`
- `fcdd5506c78f65d254de1f0a837c23289871d1c7`
  `[tests] Make glyph-width regression font-environment tolerant`

### CI proof

Behavior HEAD:
`fcdd5506c78f65d254de1f0a837c23289871d1c7`

GitHub Actions:
- Run: `35935992486`
- Workflow: `V2 CI`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **261 passed, 11 warnings in 4.80s**

New regressions prove:
- a Story-primary future RESULT cannot leak before its semantic cue;
- a boundary carrier prefers a safe early semantic object over a character/result;
- semantic CHARACTER context is excluded from normal focus competition;
- explicit semantic OBJECT focus can outrank character context;
- base character entry energy is lower than the active semantic concept;
- family-canvas visible frames remain opaque/crisp instead of alpha-ghosted;
- wide shaped Arabic text is measured materially wider than the old approximation;
- final text glyphs and their entry trajectory remain inside title-safe margins.

### Invariants preserved

- Pass1 + Pass2 only.
- No Layer3 / Pass3.
- Final Package remains semantic authority.
- WhisperX/forced alignment remains speech timing authority.
- Composition final geometry unchanged.
- No relayout/collision solver.
- No post-settle wobble/recoil.
- No future semantic reveal through Story primary.
- No unrelated outgoing-art carry.
- No alpha ghost crossfade.
- Text wording/selection/font family/style unchanged.
- PR #1 remains draft and unmerged.

### Next visual acceptance gate

Render the same precise Black-Hat or White-Hat package again from latest `montage`.

Mandatory review points:
- old-program progression: later result stays hidden until its phrase;
- install progression: program -> action/path -> result, no result pre-exposure;
- return-later progression: source -> return action -> destination/result;
- company/discovery class: character remains context, semantic object gets concept focus,
  result/discovery gets payoff focus;
- all Arabic text fully inside screen including entry motion;
- no pale family reveal;
- no white flash;
- no collision or final-position drift.

Do not modify the Final Package to compensate for these bugs.

## MONTAGE17 TEMPORAL TEXT / VISUAL QA FIX — 2026-09-24

The user reran the precise Black-Hat package on commit
`326914c1ec1b723c521b33032deb473edb27a414` and supplied diagnostic job
`094056752aa0493aa0046b338b8fd68a`.

This was a CURRENT-HEAD failure, not an old-run artifact.

### Diagnostic result

Pipeline successfully reached Motion after:
- 40 scenes
- Pass1: 157 authored assets
- Pass2: 179 assets (+22)
- Story: 40 beats
- Text: 51 cues
- Composition locked to Final Package geometry

Failure:
`TEXT_LAYOUT_REFERENCE_VIOLATION`

The new shaped-glyph text measurement correctly exposed 20 text/visual overlap reports.

### Root cause

After semantic visibility was introduced, Text Placement and Authoring QA still reasoned against
the entire final Composition at once.

This was temporally incorrect:
- Final Composition contains future assets that have not appeared yet.
- A text cue may disappear before a later RESULT/OBJECT is revealed.
- Those two objects cannot visually collide at runtime, but the old QA treated them as simultaneous.

The shaped Arabic bounds fix made this stale assumption visible by increasing text boxes to their
real production glyph footprint.

### General fix

Text Placement is now temporally visibility-aware before Motion:
- Story V2 reveal windows determine which visual assets may coexist with each text cue.
- Future semantic assets whose reveal begins after the text readability window no longer consume
  negative space.
- Unknown/legacy assets remain conservative and are treated as visible.
- The earliest reveal cohort is retained conservatively because Renderer may choose one as the
  anti-white boundary carrier.
- When multiple valid candidate positions exist, candidates under the same QA overlap threshold are
  preferred explicitly before typography-size/style priors.

Authoring QA is now temporally authoritative after Motion:
- Uses final MotionCue start times for each asset.
- Validates text only against artwork that is actually visible while the text remains readable.
- Keeps the earliest Motion cohort conservative for carrier behavior.
- Assets without Motion remain treated as visible.
- Text/text temporal collision validation remains unchanged.
- A visual that reveals DURING the text lifetime still triggers overlap failure.

This does NOT disable QA and does NOT allow real collisions.
It removes false positives caused by comparing text to future visual state.

### Commits

- `c17bff173ee43d1e671d1c34f905527e3032b30f`
  `[text] Place cues against temporally visible artwork`
- `363efee145e6877dc5a508aad50246c899c5c5e9`
  `[text] Pass readability window into placement`
- `d4194bc18656416ab0470a5adc828cad834314d7`
  `[qa] Validate text against rendered visual timing`
- `f0de6780f45734fa973d9269b8d3ba7ae8e96dfe`
  `[tests] Cover temporal negative-space placement`
- `d0cea202b825526e2f3dec003856273b2720806f`
  `[tests] Cover motion-timed text visual QA`

### CI proof

Behavior HEAD:
`d0cea202b825526e2f3dec003856273b2720806f`

Run:
`35937516047`

Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **264 passed, 12 warnings in 6.66s**

### Acceptance expectation

Rerun the SAME precise Black-Hat Final Package + SAME narration audio after pulling latest
`montage`. No Final Package modification is required.

The run should now proceed past the prior text-layout false-positive gate while still rejecting
any true text overlap that exists at the same rendered time.

## MONTAGE17 SELF-HEALING TEXT LAYOUT RECOVERY — 2026-09-24

A new diagnostic ZIP from job `e7330cf748174e9188a5816784705e69` proved that the
temporal-placement correction alone was insufficient for production robustness.

### Diagnostic facts

Build:
`d0cea202b825526e2f3dec003856273b2720806f`

Failure:
`TEXT_LAYOUT_REFERENCE_VIOLATION`

The run reached Motion after:
- 40 scenes
- Pass1: 157 assets
- Pass2: 179 assets
- Story: 40 beats
- Text: 51 cues
- Composition: completed

The final Authoring QA still reported real same-time text/visual overlap on multiple beats.

Critical reliability defect:
`recovery-events.json` contained **0 events**.

This meant the pipeline could detect a recoverable text-layout failure but had no registered
Recovery handler and therefore terminated the entire video.

### Product requirement

HEXA is a general production tool. Optional text layout must never make a valid visual/video job
unrecoverable when a safe degraded result exists.

The correct behavior is:
1. repair automatically;
2. preserve Final Package visual geometry;
3. preserve Story/Motion semantic timing;
4. record the recovery;
5. only fail when an explicitly required contract remains impossible.

### General self-healing policy

New known issue:
`TEXT_LAYOUT_REFERENCE_VIOLATION`

Registered as a proven Recovery issue with up to 3 bounded attempts.

Recovery ladder:

#### Attempt 1 — final-Motion-aware recomposition
- Re-run Text Composition using actual final Motion reveal times.
- Text sees only visual assets that can coexist during its readability window.
- Final Package visual Composition is untouched.

#### Attempt 2 — bounded emergency typography fit
- Same real Motion visibility.
- Adds only two emergency scales: 0.52 and 0.50.
- Font family, weight, fill, outline, wording and style remain unchanged.
- This mode is used only after normal production sizes cannot produce a QA-safe placement.

#### Attempt 3 — optional-cue degradation
Only when `require_text_layer=false`:
- parse the exact violating text cue IDs;
- remove only those impossible text cues;
- recompose all remaining cues;
- re-plan Text Motion;
- re-run Authoring QA;
- continue the video if clean.

The video therefore survives impossible optional text geometry instead of failing globally.

When `require_text_layer=true`, impossible required text remains a hard failure after bounded
repair attempts. This preserves explicit product contracts.

### Recovery observability

Every attempt is now recorded through `RecoveryManager.record_outcome()` with:
- issue code;
- attempt number;
- remaining issue count;
- repair level;
- any optional text cue IDs removed by the final fallback.

Future diagnostics should no longer show `recovery-events: 0` for this known issue.

### Code changes

- `1a5ce6c0a2b0a4b446be9a05e35668faf6ba282f`
  `[text] Add bounded collision-repair placement mode`
- `0684ab63710fe91852c206fa2e8660354f4888d0`
  `[models] Permit bounded emergency text scaling`
- `18d46590df45e252aaf8378cc1751fb0b6e54678`
  `[text] Recompose against final Motion visibility during repair`
- `e12d0f58de9a8dd7493c0b8a1b4d9efe1ab46677`
  `[recovery] Add text-layout repair handler`
- `95d25c102e9f768bb382e074e6de0eedea65762d`
  `[recovery] Register text-layout self-healing`
- `df6639911a9c8cf70552ee6e10b27d1c2ed668fe`
  `[pipeline] Self-heal text layout before render`
- `a697ec5fbdbb63cecb2c4a1d76d6febc28f27068`
  `[tests] Cover self-healing text layout recovery`

### CI proof

Behavior HEAD:
`a697ec5fbdbb63cecb2c4a1d76d6febc28f27068`

Run:
`35938530388`

Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **268 passed, 12 warnings in 7.64s**

Regression coverage now proves:
- the issue is registered and has a proven handler;
- attempts are bounded to 3;
- violation strings identify only real known cue IDs;
- emergency scale 0.50 is model-valid;
- prior temporal placement / Motion QA tests remain passing.

### Invariants preserved

- Pass1 + Pass2 only.
- No Pass3 / Layer3.
- Final Package remains semantic authority.
- Visual Composition remains immutable.
- Story timing and Motion are not changed to make room for text.
- No collision solver moves artwork.
- Text wording, font family, bold weight, white fill and black outline are unchanged.
- Optional text degradation affects only impossible cues after two repair attempts.
- PR #1 remains draft and unmerged.

### Next acceptance gate

Pull latest `montage` and rerun the exact same Black-Hat Final Package + narration.

Expected behavior:
- if standard text placement is safe: no recovery;
- if final Motion creates a text conflict: Recovery events appear and text is recomposed;
- if a cue is physically impossible to place safely: only that optional cue is omitted;
- the video continues to Render instead of terminating with
  `TEXT_LAYOUT_REFERENCE_VIOLATION`.

## MONTAGE17 FINAL FOCUS CALIBRATION / SPEECH-FIRST ORDER / TEXT AUTHORITY / FLASH RECOVERY — 2026-09-24

This batch was driven by the user's latest Black-Hat render/screenshot and the goal of closing the
current project quality phase.

### Confirmed package evidence

The precise REV9 Final Package already contains enough information. No package change is required.

SCENE_035:
- CHARACTER `SCENE_035_A01_screen_hacker`
  - precise span 1004–1018
  - text: `شخص يكتب بسرعة`
  - sequence_order 1
- OBJECT `SCENE_035_A02_black_monitor`
  - precise span 1024–1034
  - text: `شاشة سوداء`
  - sequence_order 2
- ACTION `SCENE_035_A03_fast_keyboard`
  - precise span 1008–1018
  - text: `يكتب بسرعة`
  - sequence_order 3

Therefore narration semantics require:
CHARACTER context -> KEYBOARD/ACTION on `يكتب بسرعة` -> MONITOR/OBJECT on `شاشة سوداء`.
The previous engine incorrectly let sequence_order force monitor before keyboard.

SCENE_030:
- manager CHARACTER: span 828–842, `الشركة تكتشفها`
- company OBJECT: span 828–834, `الشركة`
- discovery magnifier RESULT: span 835–842, `تكتشفها`

Desired attention:
manager quiet context -> company concept focus -> magnifier strongest RESULT payoff.

### Authority correction: precise speech timing wins

Story timing now treats precise script/WhisperX spans as the authoritative WHEN.

`sequence_order` is only allowed to split/stagger assets when they genuinely share the same precise
semantic trigger. Distinct precise spans retain natural narration order even if a visual ordering hint
has a conflicting sequence number.

This is general and contains no scene/topic IDs.

Commits:
- `c06c3909b1db4a9c309ae8a92a61d284c5b78dfd`
  `[story] Let precise speech timing outrank visual sequence hints`
- `717d3c87e636034a93b7e37245a3824c4cf81897`
  `[qa] Validate sequence order only inside shared trigger windows`
- `359a404c1c337c9229d5ef9a3786725f7982dbba`
  `[story] Scope focus calibration to authored semantic attention`

### Reference-style semantic attention calibration

Focus timing is now role-aware and pace-aware.

Nominal authored semantic focus targets:
- ACTION: ~180 ms
- SUBJECT: ~220 ms
- OBJECT: ~230 ms
- PRIMARY: ~250 ms
- STATE: ~300 ms
- RESULT: ~320 ms
- CHARACTER/CONTEXT/SUPPORT: ~160 ms establishment only

These durations compress on fast narration and expand modestly on slower narration.

Motion strength hierarchy adds bounded one-shot pre-settle accents:
- ACTION >= 1.060
- OBJECT/SUBJECT >= 1.070
- PRIMARY >= 1.080
- STATE >= 1.095
- RESULT >= 1.105

After semantic settle:
- exact authored Composition is restored;
- motion energy becomes zero;
- no opacity dimming;
- no wobble/recoil;
- no post-arrival bounce;
- previous elements visually quiet by being static, not ghosted.

Motion metadata exposes:
- `focus_duration_ms`
- `attention_decay=static_hold`
- `handoff_residual_strength=0.40`

Commit:
- `bfbe29f74c1663eeb5cb8521aaf2b1948d2d524d`
  `[motion] Calibrate semantic focus handoff and result payoff`

### Stronger semantic text selection

Text now prefers exact asset-level `script_span` evidence from the Final Package.

Authority ranking:
1. numeric/amount evidence
2. precise semantic asset RESULT/ACTION/OBJECT/SUBJECT/PRIMARY/STATE
3. aggregate semantic package phrase
4. precise CHARACTER/CONTEXT-like phrase
5. generic fallback

Semantic-package videos may use a slightly richer text budget, while legacy/no-package behavior retains
the previous sparse baseline.

Cue priority also carries semantic salience.

Expected examples:
- SCENE_035 favors `يكتب بسرعة` and `شاشة سوداء`, not the broad CHARACTER phrase.
- SCENE_030 favors `الشركة` then `تكتشفها`, with discovery as the stronger cue.

Text recovery also changed:
- text/text collision no longer drops both cues;
- it preserves the stronger semantic cue and drops only the weaker one if bounded placement repair
  remains impossible.

Commits:
- `dbdd9e22cc7012ba5dcaa5c11ca699793e970c5b`
  `[text] Prefer precise semantic asset phrases and stronger cue density`
- `08bb38e8594e572b29c7ca86d5f6401eef5344e2`
  `[text] Keep legacy sparsity and prioritize precise asset spans`
- `53210a37a410cdd58c760667e14f05f26c05fd02`
  `[text] Make precise semantic spans authoritative over aggregate phrases`
- `afafcdcce2be6f4f230b93109f260a481ea9d4ce`
  `[text] Preserve precise authority during keyword dedupe`
- `ac73dddd9dccac9892aa1c7544fe8f12a07ed69e`
  `[text] Carry semantic salience into cue priority`
- `bddd3712cecede0044715f8c4dd21ea806533f30`
  `[recovery] Preserve strongest semantic text cue on collision`

### White-flash QA and recovery hardening

The prior final QA used a broad >99% white detector. That could incorrectly classify valid sparse
reference-style scenes containing one small semantic object as a flash.

New two-stage detection:
1. broad FFmpeg blackframe candidate scan;
2. exact encoded-frame RGB inspection for actual dark/colored foreground occupancy.

Uniform H.264 codec-white (often RGB ~252–254) remains blank; a small but real semantic object is
accepted.

If a TRUE internal blank remains, `VISUAL_WHITE_FLASH` is now a proven Recovery issue:
- one bounded rerender attempt;
- strict boundary coverage mode;
- candidate must come from the same earliest semantic reveal cohort;
- future RESULT assets remain forbidden;
- within that safe cohort, prefer enough authored visual footprint to cover the boundary;
- remux and re-run final QA.

Commits:
- `e02aa90b716d8dbfc4ba9b65d7d09214a7bda0c1`
  `[qa] Distinguish sparse semantic frames from true white flashes`
- `f1407d188698eb061698fb533880153e3b617e38`
  `[render] Add strict semantic-safe boundary coverage recovery`
- `7134a32b1b96717943795fc121b070c5b0d02b59`
  `[recovery] Add strict white-flash rerender handler`
- `377b651279816646263255247ae588823b0ebbe0`
  `[recovery] Register true white-flash self-healing`
- `74fd462f1fbb800e1a8d3d3b2563de504eaa7611`
  `[pipeline] Recover true white flashes with strict boundary render`
- `6dcafa8389c944de21564f44a3eb8628b584895b`
  `[qa] Verify white-flash candidates by exact encoded frame`
- `c1673c7d22a0b7920b1ec43bb29974b6e3329cc0`
  `[qa] Treat uniform codec-white as blank, not foreground`
- `1982dff8c7f7e52a45e2d6e36dbf80a04a74e562`
  `[qa] Remove obsolete white-distance calculation`

### Regression tests

New tests prove:
- distinct precise speech spans outrank conflicting sequence_order;
- identical precise spans still respect sequence_order;
- ACTION attention is shorter than RESULT attention;
- hacker text prefers ACTION/OBJECT precise phrases;
- company text prefers company concept + discovery result;
- stronger semantic cue survives text/text fallback;
- sparse white semantic scenes are not false-positive flashes;
- true encoded internal blank remains a flash;
- strict carrier prefers largest safe early visual and never future RESULT.

Test commits:
- `8b8af1fa47b5193342717d68d0ea2c242fcbcfe8`
- `464a6027d18fe95bbc399f5ffc6c42f8a7be94ad`
- `9114974f7126e71a20f83ffc5f40c84d4e9acfc9`
- `680118cb96ed447a650a77701665ea63120ee903`

### Final CI proof for behavior HEAD

Behavior HEAD:
`1982dff8c7f7e52a45e2d6e36dbf80a04a74e562`

Run:
`35941511136`

Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **275 passed, 12 warnings in 8.16s**

### Invariants preserved

- Pass1 + Pass2 only.
- No Pass3 / Layer3.
- No Final Package schema expansion.
- Final Package remains semantic WHAT/source.
- precise speech/WhisperX remains timing authority.
- sequence_order remains useful only as a shared-trigger visual tie-break.
- Composition positions remain immutable.
- no collision solver moves artwork.
- no future-result carrier reveal.
- no alpha ghosting.
- no post-settle motion.
- text typography look remains unchanged.
- PR #1 remains draft/unmerged.

### Next and final visual acceptance gate

Run the SAME precise Black-Hat REV9 package + narration on the latest `montage`.

Mandatory visual checks:
1. SCENE_035: CHARACTER context -> KEYBOARD on `يكتب بسرعة` -> MONITOR on `شاشة سوداء`.
2. SCENE_030: manager quiet -> company focus -> magnifier strongest RESULT at `تكتشفها`.
3. SCENE_014: old program -> update failure -> years/result; no early calendar.
4. SCENE_026: installer -> action/path -> infected result.
5. SCENE_027: backdoor -> return action -> gateway/result.
6. text stays inside frame and uses stronger semantic phrases.
7. no false white-flash rejection for sparse valid scenes.
8. any true blank boundary self-recovers once through strict safe carrier mode.
9. no future-element reveal, collision, drift, ghosting, wobble or recoil.

Code/CI acceptance is complete. Fresh encoded visual acceptance still requires one new full product
render on the production desktop/runtime; do not claim visual parity until that render is watched.

## MONTAGE17 MULTI-TRIGGER SEQUENCE QA CORRECTION — 2026-09-24

A fresh Black-Hat render on HEAD
`40246b8d93c9737aa9ff1dc5cf769175ed0149d2` failed before Render with
`STORY_SYNC_INVALID`.

Diagnostic job:
`004c2710cee24adda36950fc8b2b2ed8`

The package/audio were valid. Story built 40 beats and Text placed 65 cues.
The failure contained sequence-order QA violations in beats 013, 017, 021, 028, 032, 034 and 040.

### Root cause

The speech-first scheduling correction was correct, but StorySyncQA still validated sequence order too
coarsely at the semantic-group level.

A semantic group may legitimately contain multiple precise trigger clusters. Example:
- order 1 -> one precise narration span;
- order 2 and order 3 -> a different shared precise narration span.

Story correctly sequences order 2 -> 3 inside their shared trigger while allowing their narration
span to occur before order 1. QA incorrectly used:
`any(row_is_sequential_window)`
for an adjacent order pair, which could enforce order 1 -> 2 even though those two orders were not
part of the same trigger cluster.

This produced false:
- `sequence_order_motion_reversed`
- `sequence_order_motion_collapsed`

### General correction

Story scheduling and StorySyncQA now share the exact same
`same_precise_trigger()` identity rule.

QA:
- collects only activations that Story explicitly scheduled as sequential;
- clusters them by actual precise trigger identity;
- enforces `sequence_order` only inside each cluster;
- never compares sequence numbers across different narration spans;
- retains internal multi-cutout ordering validation separately.

This does NOT disable sequence QA.
Shared-trigger sequences are still required to be strictly ordered.
Distinct precise narration spans remain governed by spoken timing.

### Commits

- `71b0d3bc8784b44957f77f323f8f5054840b2a3e`
  `[story] Share precise-trigger identity across scheduling and QA`
- `4886a7f811f9fcc835fed76a60f30464c69e2970`
  `[qa] Validate sequence order within precise trigger clusters`
- `b37e5fab57b153a0037720d5246361d82ef3a0b1`
  `[tests] Cover multi-trigger semantic-group sync QA`

### Regression proof

The new regression intentionally models:
- one semantic group;
- order 1 on a later precise phrase;
- order 2 and order 3 on an earlier shared precise phrase.

It proves:
- speech timing may place order 2/3 before order 1;
- order 2 still must precede order 3;
- StorySyncQA passes the valid result.

CI run:
`35943130887`

Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **276 passed, 12 warnings in 6.69s**

### Invariants

- precise speech remains WHEN authority;
- sequence_order remains authoritative inside one shared semantic trigger;
- no Final Package change;
- no weakening of visual sync QA;
- no Pass3/Layer3;
- Composition remains locked.

## MONTAGE17 RELEASE RENDER SMOKE + CONVERGENT OPTIONAL TEXT RECOVERY — 2026-09-24

A fresh diagnostic ZIP from Black-Hat REV9 on HEAD
`d704d31408a07e71065201b6332ff703945ac037`
(job `58d39e36c0e04ee3bc3f9950e4b453f8`) exposed a remaining recovery hole.

### Production failure

The run passed:
- Final Package load
- transcription/alignment
- vision
- Pass1: 157 assets
- Pass2: 179 assets
- Story: 40 beats
- Composition: 65 initial text cues
- Story Sync QA

Text Recovery then:
- attempt 1 -> 21 issues
- attempt 2 -> 14 issues
- attempt 3 dropped 14 unsafe optional cues

After that reflow exposed a NEW collision:
`beat-019:text_visual_overlap:text-028:0.051`

The old attempt-3 implementation degraded optional text only once and then returned. Therefore
AuthoringQA could still terminate the whole video even with `require_text_layer=false`.

### Convergent optional-text recovery

Attempt 3 is now monotonic and iterative:

`detect unsafe -> drop weakest unsafe cues -> recompose -> re-plan text motion -> re-run QA -> repeat`

- Up to 8 bounded degradation cycles.
- Each cycle operates on the NEW QA result after reflow.
- Text/text collisions still preserve the stronger semantic cue.
- Visual Composition, Story, visual Motion and Final Package geometry are never changed.

Final fail-safe:
- when `require_text_layer=false`, if bounded degradation still cannot converge,
  clear the remaining optional text layer only;
- rebuild Text Composition/Text Motion;
- re-run Authoring QA;
- the valid visual/video job is allowed to continue.

Therefore an optional text-layout conflict may no longer kill an otherwise valid video.

Commit:
- `837deaff38b2635488fb614bb306bacfe1ff179a`
  `[recovery] Converge optional text layout before render`

Regression:
- cascading QA fixture reproduces a second collision appearing only after the first cue is removed.
- recovery must converge to zero violations.

Commit:
- `6c8111b75b26875e35fff06b5b316955739c0cb7`
  `[tests] Cover cascading optional text recovery`

### Actual encoded MP4 release smoke

A new CI integration test now performs a REAL downstream release path using FFmpeg:

1. create real RGBA visual assets;
2. build a 2-beat RenderPlan;
3. run `FFmpegRenderer`;
4. encode H.264 MP4;
5. generate real PCM narration audio;
6. run `FinalExporter.mux`;
7. verify final video+audio streams;
8. run `RecoveryDetector.inspect_final`;
9. require zero final-media issues;
10. run `RenderedVisualQA` and require visual evidence.

This is an actual encoded MP4 test, not a mocked render.

Commit:
- `9cd515c42466d68ea0364190c5a055a870cfae42`
  `[tests] Add actual MP4 release render smoke`

The first smoke run correctly found an additional robustness issue:
very short videos could fail to emit the multi-sample contact sheet because the tile filter did not
have enough frames to flush.

RenderedVisualQA now:
- first attempts the normal multi-sample contact sheet;
- if unavailable, falls back to one encoded frame;
- never reports a false unsampled state solely because the video is short.

Commit:
- `1f4d792ab6bdeec16f1d0bb2c275175bbdb3064a`
  `[qa] Fall back to single-frame evidence for short renders`

### CI proof

Behavior HEAD:
`1f4d792ab6bdeec16f1d0bb2c275175bbdb3064a`

Run:
`35944415369`

Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **278 passed, 12 warnings in 6.91s**

The passing suite now includes:
- multi-trigger semantic-group Story Sync QA;
- focus calibration;
- precise keyword selection;
- temporal text placement;
- cascading optional-text recovery;
- white-flash classification/recovery;
- actual H.264 MP4 render;
- real audio mux;
- final A/V detector;
- post-render visual evidence.

### Release rule

Do not ask the user to run a full production render after code changes unless:
1. Compile is green;
2. Ruff is green;
3. full pytest suite is green;
4. the actual MP4 release smoke is green.

A fresh full Black-Hat production render is still the final visual acceptance gate because CI cannot
run the user's WhisperX/model/runtime or the full 40-scene package/audio pair.


## MONTAGE17 STORY-HANDOFF PRODUCTION FAILURE HARDENING — 2026-09-24

Fresh Black-Hat REV9 diagnostic job:
`829ed88b3e164a7183f756cc19ee2dd0`

The run reached Motion after:
- Pass1: 157 authored assets / 40 scenes
- Pass2: 179 assets (+22)
- Story: 40 beats
- Text: 65 cues
- Composition locked to authored Final Package geometry

It then failed with `STORY_SYNC_INVALID` before render.

Violation profile:
- 13 x `focus_peak_too_late`
- 15 x `settle_past_next_handoff`
- 4 x `strong_focus_overlap`

### Root causes

1. Footprint-locked Pass2 family secondary layers are deliberately static/alpha-only. StorySyncQA
   incorrectly manufactured a spatial focus peak from their last neutral keyframe, producing false
   late-peak violations even though those layers have no spatial gesture to validate.

2. Shared-trigger `SEQUENTIAL_WITHIN_PHRASE` windows were bounded by the shared phrase end but not
   by the next distinct precise narration trigger. A sequence could therefore continue moving into
   the next spoken meaning.

3. Exact Final Package SUPPORT/CONTEXT activations without explicit visual_focus could retain a long
   phrase-sized motion window even when a later precise semantic hit existed. This allowed support
   motion to cross a real narration handoff.

### Corrections

- Static/alpha-only programs no longer synthesize an `actual_peak`; reveal/settle contracts still
  remain enforced.
- Shared-trigger sequence clusters are capped at the next distinct precise semantic hit.
- Exact package visuals with a known later semantic hit receive a bounded entry and then static hold,
  including SUPPORT/CONTEXT roles.
- No Final Package, Composition geometry, Pass1/Pass2 extraction architecture, Renderer layout, or
  Text typography changes.
- No QA tolerance increase and no scene-specific exceptions.

### Commits

- `1a813c85e388954d3fc170d36e6430c5c10b92ec`
  `[timing] Bound visual attention before later semantics`
- `2d7e43266c7e36191bcd09b46489e1e9c6a708ec`
  `[qa] Ignore nonexistent peaks on static family layers`
- `3f471866d6f44ee570606dc6aa11496ce892680e`
  `[tests] Fix bounded handoff assertions`
- `231876990442f5119c30d8d49245925faa26e8d9`
  `[tests] Cover static family focus peak QA`

### CI proof

Run:
`35995994163`

Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **290 passed, 12 warnings in 9.14s**
- Actual encoded MP4 release smoke remains in the passing suite.

Fresh full production render is still required for visual acceptance.
## MONTAGE19 STARTUP / COHORT ATTENTION AUDIT CHECKPOINT — 2026-09-24

Incoming owner: `montage19`.
Received from: the latest repository continuity line after Montage17 production hardening.
Development branch: `montage` ONLY.

### Startup verification

Live branch was re-verified from GitHub before any write.

- Live `montage` HEAD before this continuity commit:
  `866254fcf5b961323f4799fd52c57bb97d1be66d`
- HEAD message:
  `[motion] Budget attention within semantic cohorts`
- Previous handoff behavior SHA:
  `231876990442f5119c30d8d49245925faa26e8d9`
- Compare result:
  - status: ahead
  - commits ahead: 2
  - behind: 0

### Unseen commit audit completed

Both commits after the last recorded behavior SHA were reviewed before this documentation write.

1. `a084ca53547e1f48d3ab550929a5cfe5a4e85fa3`
   `[continuity] Record semantic handoff production hardening`
   - documentation-only;
   - appends the Story-handoff failure/root-cause/fix/CI evidence already reflected in the final
     Montage17 checkpoint;
   - changed only `HEXA_PROJECT_CONTINUITY_SOURCE.md`.

2. `866254fcf5b961323f4799fd52c57bb97d1be66d`
   `[motion] Budget attention within semantic cohorts`
   - behavior change in `app/motion/planner.py`;
   - regression additions in `tests/test_final_package_choreography_v11.py`;
   - introduces a bounded attention budget for assets sharing the same Story semantic cohort;
   - chooses one semantic leader from authored focus/role/relation evidence;
   - keeps relation participants readable but below the leader;
   - suppresses simultaneous support/context motion energy rather than letting every valid activation
     become equally strong;
   - preserves Story-owned timing, exact Composition geometry, final settle, post-settle freeze,
     Pass1/Pass2 architecture and existing choreography authority.

No additional unseen commit exists between the recorded behavior SHA and the live HEAD.

### Live CI proof

GitHub Actions:
- Run: `35999994814`
- Workflow: `V2 CI`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: **295 passed, 12 warnings in 7.43s**
- The actual encoded MP4 release smoke remains part of the passing suite.

### Render / Visual QA / PROVEN state

Render:
- No fresh full production Black-Hat/White-Hat render is recorded for exact HEAD
  `866254fc...`.

Visual QA:
- NOT YET performed on a full encoded production render from this exact HEAD.
- Therefore the new cohort attention budget is code/CI proven but not perceptually accepted.

PROVEN:
- Pass1 + Pass2 only.
- Final Package semantic authority.
- precise speech/WhisperX timing authority.
- Story handoff bounding and static family-layer QA hardening.
- cohort attention-budget architecture and regression coverage.
- Compile/Ruff/full pytest/release-smoke gate.

NOT PROVEN:
- reference-grade focus hierarchy from a real 40-scene production render on exact HEAD
  `866254fc...`;
- final perceptual balance of leader/participant/support energy on real narration;
- absence of any scene-specific visual regression in the full user package/audio runtime.

### Current blocker / next action

The engineering gate is no longer a known code/CI failure.

The remaining acceptance blocker is the fresh exact-HEAD production render using the precise REV9
Final Package + real narration audio, followed by full visual review.

Mandatory visual checks remain:
- one clear focus leader per simultaneous semantic cohort;
- relation participants readable without competing with RESULT/PRIMARY;
- support/context/character calm unless explicitly promoted;
- no future semantic reveal;
- no settle past the next narration handoff;
- no strong-focus overlap;
- exact final authored geometry;
- no collision, ghost alpha, white flash, wobble/recoil, or text clipping.

Do not make another motion-strength change until a fresh exact-HEAD render or concrete diagnostic
shows the remaining defect.

## MONTAGE19 FINAL PACKAGE 1.2 END-TO-END SEMANTIC EVENT INTEGRATION — 2026-09-24

This checkpoint is the authoritative completion of the user's new package:
`HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2.zip`.

### User target

The requested production chain is now explicit and tested:

```
spoken word / WhisperX timing
    -> exact canonical script span
    -> written keyword/text cue
    -> semantic event
    -> correct visual intent / real cutout
    -> icon / event ordering
    -> visual leader + focus arbitration
    -> relation-aware motion direction
    -> result/payoff
    -> exact authored Composition settle
```

Final Package remains WHAT/identity/semantic authority.
WhisperX/forced alignment remains actual WHEN authority.
Motion still owns HOW.
Composition final geometry remains immutable.

### Final Package 1.2 contract consumed

The loader and runtime now consume, validate and preserve:
- `semantic_events`
- event `sequence_order`
- `visual_leader_asset_id`
- `participant_asset_ids`
- `context_asset_ids`
- `result_asset_ids`
- `text_anchor_asset_id`
- `depends_on_event_ids`
- scene `progression.event_order`
- `relation_type`
- `global_char_start/global_char_end`
- `anchor_granularity`
- `compound_visual_classification`
- `internal_progression_unavailable`

Backward compatibility remains for v1.1:
- legacy `relationship`
- legacy `char_start/char_end`
- packages without semantic events.

### Loader hardening

Final Package 1.2 now fails closed for:
- duplicate semantic events;
- missing event leaders/text anchors;
- invalid role asset references;
- missing event dependencies;
- dependency cycles;
- progression referencing missing events;
- progression order conflicting with event sequence;
- invalid compound classifications;
- `internal_progression_unavailable=true` unless the asset is `COMPOUND_REQUIRED`;
- conflicting local/global script coordinates.

Top-level semantic event mirrors are validated against scene-level events.

### Spoken word -> exact semantic timing

Asset and relation spans can use the 1.2 global coordinate contract.

The activation path now resolves:
- `global_char_start/global_char_end`
- repeated phrases by exact canonical span;
- forced-aligned spoken timestamps from that exact span.

A repeated identical word can no longer silently reuse timing from an earlier occurrence merely because the text matches.

### Semantic Event -> correct visual

Every resolved `AssetActivation` can now carry:
- `semantic_event_id`
- `semantic_event_order`
- `semantic_event_roles`
- `semantic_event_dependency_ids`
- `compound_visual_classification`
- `internal_progression_unavailable`.

Event roles include:
- LEADER
- PARTICIPANT
- CONTEXT
- RESULT
- TEXT_ANCHOR.

Visual Locator remains WHICH VISUAL authority only; no crop/layout authority was added.

### Written word -> correct icon

Text selection and anchoring now understand 1.2 event evidence.

When candidate spans overlap:
1. Final Package TEXT_ANCHOR evidence wins;
2. event LEADER is next;
3. exact activation/span confidence/focus remains the fallback;
4. old beat/choreography primary remains the final fallback.

Text spoken_start/token spoken_start remain forced-aligned.
No text typography/style redesign was introduced.

### Ordering

Motion order metadata now carries semantic event order/dependencies.

Shared timing windows can use event order + existing asset sequence order without discarding precise spoken-span timing.

The prior rule remains:
- distinct precise speech triggers follow speech order;
- `sequence_order` remains a visual tie-break within the same trusted trigger;
- event progression adds a higher semantic progression layer where authored.

### Focus

The previous cohort attention budget is now driven by explicit event authority.

Inside simultaneous semantic cohorts:
- explicit event LEADER gets leader authority;
- same semantic visual-unit members may share leader authority when one intent maps to multiple real cutouts;
- PARTICIPANT remains readable below leader;
- CONTEXT is quiet;
- RESULT receives payoff authority;
- no global “everything becomes hero” behavior.

### Relation -> motion direction

1.2 `relation_type` is normalized into existing choreography actions.

Added generic support for relations including:
- ENABLES
- CAUSES
- CAUSES_UNUSED_SECURITY
- LEADS_TO
- LEADS_TO_DISCOVERY
- REVEALS_IDENTITY
- PARALLEL_CAUSES
- WITHHOLDS_DISCLOSURE
- SPECIFIES
- PROGRESSES_TO
- PERSISTS_OVER_TIME
- CONTAINS_RISK

They remain generic semantic relations, never package/topic-specific pixel commands.

Examples:
- ENABLES / causal relation can compile SUBJECT -> OBJECT directional staging;
- RESULT lands last/strongest where authored;
- PARALLEL_CAUSES stays comparison-oriented rather than being forced into cause/effect choreography;
- SPECIFIES remains non-executable descriptive evidence.

### Compound visual safety

When Final Package marks one semantic intent:
`COMPOUND_REQUIRED`
or
`internal_progression_unavailable=true`

MotionOrderResolver does NOT internally stagger its multi-cutout members.

This prevents StoryEngine from creating fake internal sequencing for a visual the authoring stage explicitly says must remain compound.

Pass1/Pass2 extraction itself remains unchanged.

### Choreography progression

Authored 1.2 scene event progression can promote generic `PROGRESSIVE_BUILD` behavior when no stronger explicit state/relation pattern overrides it.

Existing pattern authority remains:
- state transform;
- executable relation/cause-effect;
- authored focus;
- authored event progression;
- fallback.

### Behavior commits

- `c843890245b08fe0dcd8c683a0504e4bc8810922`
  `[final-package] Integrate semantic events contract 1.2 end to end`
- `6814d9bf489f01b6048a2664d2cc1d66efefcf0b`
  `[tests] Cover Final Package 1.2 semantic event authority`
- `1a8053271393e630045d926a8093719c508c788b`
  `[tests] Clean Final Package 1.2 regression imports`

### Exact-head CI proof

Behavior HEAD:
`1a8053271393e630045d926a8093719c508c788b`

GitHub Actions:
- Run: `36037286686`
- Workflow: `V2 CI`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **300 passed, 12 warnings in 9.50s**
- actual encoded MP4 release smoke remains in the passing suite.

The earlier Run `36037138570` failed only because the new test file had one unused import.
That import was removed; no production behavior changed for the rerun.

### Real Black-Hat 1.2 package acceptance

The real user-supplied 40-scene package was run through the current architecture.

Observed:
- scenes: **40**
- Vision / Pass1: **157**
- Pass2: **179** (**+22**)
- semantic events reaching runtime activations: **55 / 55**
- authored relations reaching Choreography: **15 / 15**
- authored visual locators: **107 / 107 resolved**
  - strict one-to-one: 99
  - multi-cutout semantic units: 8
- COMPOUND_REQUIRED intents tested: 2
  - internal stagger applied: 0
- Story beats: 40
- Text cues: 51
- Text cues carrying explicit Final Package text-anchor evidence: 39
- Motion cues: 179
- Motion cues carrying semantic-event authority: 150
- StorySyncQA: **PASS**
- sync violations: **0**
- max semantic settle delta: **0.0**
- semantic visual coverage: **100%**
  - 166 OWN-window activations
  - 13 inherited/support-safe activations

This proves architectural/runtime consumption of Final Package 1.2.
It does NOT by itself prove final perceptual parity with the reference videos.

### Render status

The uploaded 1.2 ZIP contains:
- 40 PNG scene images
- 5 JSON files
- 1 TXT file
- **no narration audio file**

Therefore no new full narration-synchronized production MP4 can be truthfully produced from this package alone in this checkpoint.

The engine is now ready for the same real narration audio to be paired with this 1.2 package for the final visual acceptance render.

### PROVEN

- Final Package 1.2 loads and validates.
- global precise spans reach forced-aligned timing.
- semantic event identity reaches Story.
- event leaders/participants/context/results reach focus arbitration.
- text anchors reach TextPlanner.
- event ordering/dependencies reach Motion metadata/order.
- relation_type reaches Choreography and direction semantics.
- COMPOUND_REQUIRED blocks fake internal stagger.
- old v1.1 behavior remains regression-covered.
- full GitHub CI + encoded release smoke is green.
- real 40-scene 1.2 package architectural acceptance is green.

### NOT YET PROVEN

- final reference-grade perceptual quality of a NEW full Black-Hat render using the 1.2 package + real narration audio;
- exact visual calibration of focus amplitudes on every production scene after this new event authority;
- final frame-by-frame comparison against the two reference videos.

### Next acceptance gate

Do NOT redesign Final Package again before this gate.

Use the exact same Black-Hat narration audio with the new 1.2 Final Package and current `montage`.

Mandatory visual review:
1. spoken phrase activates the correct exact semantic icon;
2. written keyword reinforces that same icon/event;
3. future semantic icons remain hidden until their event;
4. event ordering is visually readable;
5. one clear leader/focus per semantic event;
6. relation direction reads as subject -> object -> result where causal;
7. comparison relations stay comparison-oriented;
8. RESULT/payoff is stronger than support/context;
9. COMPOUND_REQUIRED visuals remain coherent and never split into fake internal animation;
10. exact authored final geometry returns at settle;
11. no collision, ghost alpha, white flash, text clipping, wobble/recoil, or motion past the next narration handoff.

Until that encoded render is watched, describe this checkpoint as:
**1.2 code/runtime integration PROVEN; final perceptual acceptance pending production render.**

## MONTAGE19 FINAL-SCHEDULE HANDOFF RUNTIME HARDENING — 2026-09-24

Fresh user production diagnostic:
- Job: `67b38b8524cc449aa67b437494f8b19f`
- Source commit: `4935820c8fb256d3c1e2a6785347758744706ccc`
- Final Package: `HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2.zip`
- Audio: real ElevenLabs Black-Hat narration
- Platform: Windows 10
- FFmpeg: 9.0.2

The production run reached Motion after:
- Pass1: 157 authored assets / 40 scenes
- Pass2: 179 assets (+22)
- Story: 40 beats
- Composition: authored Final Package geometry locked
- Text placement completed

It then failed before render with exactly one StorySync violation:

```
beat-007:SCENE_007:asset-02:settle_past_next_handoff:
role=RESULT:
actual_reveal=15.363:
actual_settle=15.683:
next_target=15.525
```

### Root cause

SCENE_007 uses one semantic event for the phrase equivalent to "steal accounts".

The RESULT/leader visual is authored against the wider exact phrase, while a participant owns the
later exact sub-word. The first Story scheduling pass normally bounds precise activations using raw
spoken anchors. However, final locator/group/window mapping can produce a later Story-owned reveal
boundary that is only visible after scheduling/inheritance.

Therefore the raw-anchor pass was not a sufficient invariant: one valid RESULT gesture could still
remain active across a later final scheduled semantic reveal even though StorySyncQA correctly
rejected that overlap.

This was a scheduler gap, not a Final Package error and not a reason to weaken QA.

### Correction

Commit:
`15bb34e725ceb46180fd457f0923c8c442aab99a`
`[timing] Enforce final semantic handoffs after scheduling`

Story now runs a final semantic-handoff enforcement pass after group/window inheritance.

For exact Final Package semantic activations:
- inspect the fully scheduled Story reveal windows;
- locate the first later distinct precise semantic reveal;
- if the current settle crosses it, compress the current one-shot focus envelope;
- preserve reveal time;
- preserve phrase identity;
- bound semantic peak inside the compressed window;
- finish strictly before the later reveal where capacity permits;
- record `handoff_policy=final_scheduled_reveal`.

The rule intentionally does NOT alter inferred/legacy pre-roll activations, because those may reveal
before phrase_start by design.

Same-precise-trigger cohorts remain untouched.

No QA tolerance was increased.
No scene-specific exception was added.
No Final Package change was required.
Pass1/Pass2, Composition, Renderer layout and Text typography remain unchanged.

### Regression

A dedicated regression reproduces the production timing:
- RESULT reveal: 15.363
- previous invalid settle: 15.683
- next exact semantic reveal: 15.525

The corrected Story window settles before 15.525.

A companion regression proves same-precise-trigger cohorts are not clipped.

### CI proof

Run:
`36040230405`

Exact behavior commit:
`15bb34e725ceb46180fd457f0923c8c442aab99a`

Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **302 passed, 12 warnings in 9.99s**
- release MP4 smoke remains in the passing suite.

### Current render gate

The exact user production run that failed must be rerun from commit `15bb34e...` or newer.

Expected behavior:
- the previous SCENE_007 `settle_past_next_handoff` failure must not recur;
- if a different real runtime defect appears, treat it as a new concrete diagnostic and fix the
  producer/scheduler rather than lowering StorySyncQA.

The current state is:
**production failure root-caused + generalized fix published + regression covered + CI PROVEN**.

## MONTAGE19 GRAY-HAT MIXED EVENT COVERAGE ORDERING HARDENING — 2026-09-24

Fresh production diagnostic supplied by the user:
- Job: `82d463773b34444c89ec8f0ea6f320e1`
- Source commit: `1da8b53940953584cf34181e2704aa6877dcf781`
- Final Package: `HEXA_GRAY_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2.zip`
- Audio: real ElevenLabs Gray-Hat narration
- Platform: Windows 10
- Duration before failure: 312.624s

Pipeline reached Motion successfully after:
- 35 scenes
- Pass1: 127 authored assets
- Pass2: 153 assets (+26)
- Story: 35 beats
- Text/Composition: 72 text cues placed
- Composition locked to Final Package geometry

The run then failed StorySyncQA with:
```
beat-033:SCENE_033_G01:sequence_order_motion_reversed:event1/asset5>event2/asset3
beat-033:SCENE_033_G01:sequence_order_motion_collapsed:event1/asset5=event2/asset3
```

### Root cause

Inside one exact spoken-trigger cohort, some semantic-group assets had explicit
`semantic_event_order` and some contextual/support members did not.

The Story scheduler previously used event order only when **every** row in the cohort
had event metadata:

```
use_event_order = all(row.semantic_event_order is not None ...)
```

Therefore one eventless support/context row disabled authored semantic event ordering
for the entire cohort and Story fell back to asset-level `sequence_order`.

StorySyncQA, however, still evaluated rows by:
`(semantic_event_order-or-0, sequence_order)`.

That created a producer/validator disagreement. In the Gray-Hat SCENE_033 case,
event 1 asset-sequence 5 could be scheduled after event 2 asset-sequence 3 even though
event order explicitly required event 1 before event 2.

This is why earlier packages could pass while the third package exposed the bug:
the failure requires mixed event coverage inside the same exact-trigger semantic group.

### Generalized correction

Commit:
`4d2a9d719d3b14c869ab9abec3989046f10ec388`
`[story] Preserve semantic event order with mixed event coverage`

A single shared ordering function now defines the contract for both producer and QA:

```
semantic_visual_order =
    (semantic_event_order if present else 0, sequence_order)
```

Meaning:
- authored event ordering remains active whenever present;
- a support/context member without event metadata occupies deterministic lane 0;
- missing event metadata on one asset can never disable event ordering for other assets;
- Story scheduling and StorySyncQA consume the exact same function, preventing future drift.

The QA diagnostic was also corrected so one reversed pair does not simultaneously emit
both `reversed` and `collapsed`; these are now mutually exclusive diagnostics.
No validation protection was weakened.

### Regression

A dedicated regression reproduces the Gray-Hat structure:
- one eventless context asset;
- event 1 with asset sequence 5;
- event 2 with asset sequence 3;
- all in the same exact precise trigger and semantic group.

Required result:
- context lane first;
- event 1 reveal before event 2 reveal;
- semantic-group sequential Story windows preserved.

This exact mixed-coverage condition now passes.

### CI proof

Exact behavior commit:
`4d2a9d719d3b14c869ab9abec3989046f10ec388`

GitHub Actions:
- Run: `36045944073`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **303 passed, 12 warnings in 9.81s**
- release MP4 smoke remains green.

### Current production gate

The supplied diagnostic ZIP intentionally contains reports only; it does not contain
the raw Gray-Hat Final Package or narration audio. Therefore the exact 35-scene production
job cannot be rerun from this diagnostic archive alone.

The user should rerun the same Gray-Hat package/audio from commit
`4d2a9d719d3b14c869ab9abec3989046f10ec388` or newer.

Expected:
- SCENE_033 mixed-event ordering failure must not recur;
- a support/context row without semantic_event_order must never cancel authored event order;
- if a different concrete runtime defect appears, fix the producer contract rather than
  lowering StorySyncQA.

State:
**root cause proven + generalized producer/QA contract unified + regression covered + CI green;
exact Gray-Hat rerender pending user runtime.**

## MONTAGE19 REFERENCE-GRADE CHOREOGRAPHY / FINAL PACKAGE EVENT FLOW — 2026-09-24

Scope decision:
- This phase intentionally modifies **Choreography only**.
- Motion/Focus implementation is frozen except for consuming the existing ChoreographyDirective fields it already consumed.
- Story, Text, Composition, Pass1, Pass2 and Renderer are unchanged.
- No hacker-specific scene ids, nouns, asset counts or topic presets were introduced.

Behavior commit:
`bdb96620bb076a8d74821e56f6b35a37e8704c93`
`[choreography] Compile Final Package semantic events into visual flows`

### Reference-video analysis driving the change

The user's current Black-Hat render was compared against:
- `تأثير المتفرج2.mp4`
- `انحياز 2.mp4`
- `hallo 2.mp4`

The stable visual difference across the references was not text layout or authored composition.
The references repeatedly build one visual sentence as:

`ESTABLISH -> ADD -> INTERACT -> REACT -> PAYOFF -> RELEASE`

while the current HEXA render too often reads as independent sequential reveals.

Quantitative frame-activity sampling supported the same conclusion:
- current HEXA high-activity sample rate: ~33.6%
- references: ~43.2% to ~55.4%
- current low-activity sample rate: ~47.6%
- references: ~21.2% to ~39.9%
- current median spacing between strong visual-change samples: ~0.4s
- references: typically ~0.2s

These metrics are diagnostic only; they are not hardcoded thresholds or runtime targets.
The implementation encodes the semantic grammar, not the reference-video numbers.

### New Choreography authority: SemanticEventFlowPlanner

New module:
`app/choreography/event_flow.py`

For every Story beat, Choreography now consumes the already-resolved Final Package 1.2 event
metadata carried by `AssetActivation`:
- `semantic_event_id`
- `semantic_event_order`
- `semantic_event_roles`
- `semantic_event_dependency_ids`
- exact runtime cutout identity after Visual Locator / Story binding

It groups real renderable cutouts by semantic event and compiles a
`SemanticEventFlow` containing:
- ordered event id/order
- dependency ids
- leader asset ids
- participant asset ids
- context asset ids
- result asset ids
- text-anchor asset ids
- authored interactions assigned to the correct event
- reference-style semantic stages
- authority/evidence/confidence

The semantic stages are:
- `ESTABLISH`
- `ADD`
- `INTERACT`
- `REACT`
- `PAYOFF`
- `RELEASE`

### Final Package is used heavily, not treated as passive metadata

Rules:
- LEADER drives event establishment.
- PARTICIPANT creates progressive addition.
- CONTEXT is preserved as context rather than promoted into the main action.
- RESULT creates explicit payoff.
- TEXT_ANCHOR is preserved in the same event contract.
- event dependencies preserve authored cross-event causality/order.
- explicit Final Package asset relations are assigned to the event whose real runtime
  cutouts participate in that relation.
- visual-progression pseudo-relations are not mistaken for executable interactions;
  event order/dependencies already own that authority.
- fallback/inferred interactions are not allowed to invent an event INTERACT phase.

One relation may bridge into a later result event. Choreography keeps the interaction on
the event containing its subject/object while the later semantic event owns RESULT/PAYOFF,
with dependency order preserved.

### ChoreographyDirective changes

Each directive now carries:
`event_flows: tuple[SemanticEventFlow, ...]`

The Director uses event flows to:
- choose the first authored event leader as the stable beat choreography anchor;
- preserve authored leader/participant/result progression;
- select `CAUSE_EFFECT_CHAIN` when the event owns an executable authored interaction;
- select `PROGRESSIVE_BUILD` for multi-event or leader+participant authored flows;
- select `FOCUS_TRANSFER` for a single result-focused authored event when appropriate;
- apply only a small bounded energy reward (max +0.10) for authored INTERACT/REACT/PAYOFF
  richness; no arbitrary global motion amplification was added.

The existing Motion layer therefore receives a materially better WHAT/RELATION/PATTERN plan
without changing Motion implementation in this phase.

### ReferenceGrammarPlanner changes

Final Package event flows can now contribute multiple semantic grammar stages inside one Story beat.

Mapping:
- multiple events / ADD -> `VisualGrammarStage.ADD`
- INTERACT / REACT -> `VisualGrammarStage.RELATE`
- PAYOFF -> `VisualGrammarStage.RESULT`

This is important because one scene/beat may contain several real semantic events and should no
longer be flattened to one generic READ or ADD action.

### Safety / validation

`ChoreographyPlan.validate()` now also verifies:
- event ids unique per beat;
- authored event order preserved;
- a non-empty event flow ends in RELEASE;
- every authored result flow contains PAYOFF;
- mapped dependency order cannot point backward.

The new event-flow compiler abstains when there are no trustworthy Final Package event activations.
Legacy/V1.1 packages therefore remain compatible and continue through the previous Choreography path.

### Regression coverage

Added a dedicated Choreography regression proving:
- event E1 leader + participant + context -> ESTABLISH/ADD/INTERACT/REACT/RELEASE;
- authored relation is attached to E1;
- later E2 result/leader depends on E1 -> ESTABLISH/PAYOFF/RELEASE.

The existing Final Package 1.2 end-to-end test now proves:
- E1/E2 event flow preservation;
- leader/participant/result extraction from the package;
- relation attached to the correct event;
- dependency preserved;
- package evidence includes `final_package_event_flow_choreography`;
- beat grammar contains ADD + RELATE + RESULT.

### Verification

Local source-artifact suite:
- focused Choreography + Final Package 1.2 tests: PASS
- full suite excluding the unavailable source-artifact V7 frozen checkpoint: PASS
- the only local full-suite failures were the known missing
  `checkpoints/v7_audio_sync/manifest.json` artifact, not behavior failures.

GitHub Actions exact behavior commit:
- Run: `36051040645`
- Result: **SUCCESS**
- Compile: SUCCESS
- Ruff: **All checks passed**
- Pytest: **304 passed, 12 warnings in 9.50s**

### Next gate

This phase is Choreography-complete.

The next production render should be used to judge whether richer event-flow planning improves the
current independent-reveal feel. Do **not** immediately modify Motion/Focus in the same iteration.
First inspect the render and identify which remaining gaps are Choreography-plan gaps versus Motion
execution gaps.

Current state:
**Final Package 1.2 event semantics are now first-class Choreography authority; reference-style
event grammar is encoded; Choreography-only implementation proven by CI.**

## MONTAGE19 CHOREOGRAPHY SECOND-PASS REFERENCE AUDIT — EXPLICIT EVENT PHASE OWNERSHIP — 2026-09-24

User requested a full re-evaluation of the Choreography-only work against the accepted reference-video spirit before moving to Motion/Focus.

Live branch before this audit:
- `c0479e6c4fea866bc1d8ee0119041b47a6872d84`
- `[montage19] Record Final Package event-flow choreography checkpoint`

### Audit conclusion

The first event-flow implementation correctly made Final Package 1.2 semantic events first-class Choreography authority and materially improved pattern selection.

One remaining Choreography gap was identified:

The plan knew that an event contained semantic phases such as
`ESTABLISH / ADD / INTERACT / REACT / PAYOFF / RELEASE`,
but the phase contract did not explicitly bind every phase to:
- the visual that owns focus;
- the participating visual ids;
- relation source and target;
- authored result visual;
- the next semantic event/visual handoff.

This was weaker than the stable reference-video grammar, where a visual sentence does not merely
contain stages; the viewer's attention is explicitly handed from one semantic participant to the
next.

### Generalized correction

Behavior commit:
`0a7d68c5189c8a7e6384e2afdc145817c9e47189`
`[choreography] Bind semantic event phases to explicit visual handoffs`

New Choreography contract:
- `EventFlowStep` represents one semantic phase inside an event.
- Each step can carry:
  - stage;
  - focus asset;
  - participating assets;
  - source;
  - target;
  - result;
  - relationship;
  - semantic action;
  - authority.
- `SemanticEventFlow` now also carries:
  - ordered `steps`;
  - `handoff_to_event_id`;
  - `handoff_to_asset_id`;
  - derived `focus_path_asset_ids`.
- `ChoreographyDirective` exposes the beat-level ordered
  `event_focus_path_asset_ids`.

Reference-style contract now reads explicitly as:
`leader -> participant -> authored interaction -> target reaction -> result payoff -> next event leader`

Context visuals are preserved as context and are not promoted into event focus unless the Final
Package explicitly gives them another semantic role.

No pixel semantics or topic-specific rules were added.
No inferred relationship is promoted above an authored package relationship.
Motion trajectory/amplitude implementation remains unchanged in this phase.

### Cross-event handoff

For ordered events inside one Story beat, Choreography now names the next event and the exact visual
that should receive the semantic handoff.

This is visual progression authority, not invented causality:
- authored relations still own causal meaning;
- event order owns progression;
- handoff only records where the visual sentence continues.

### Validation

`ChoreographyPlan.validate()` additionally proves:
- event steps end in RELEASE;
- RESULT flows own an explicit PAYOFF step;
- event handoffs point to an event in the same beat;
- handoffs move forward when event order is explicit;
- handoff visual belongs to the target event.

### Regression proof

The Final Package 1.2 regression now proves the focus path:
`a -> b -> c`

and proves:
- E1 establishes leader A;
- participant B owns ADD;
- authored A -> B relation owns INTERACT;
- B owns reaction focus;
- E1 RELEASE explicitly hands off to E2 visual C;
- E2 owns C as RESULT/PAYOFF;
- CONTEXT is not silently promoted into the focus path.

### Verification

Local source-artifact suite excluding unavailable frozen V7 checkpoint files:
- PASS

GitHub Actions exact behavior commit:
- Run: `36053742960`
- Result: **SUCCESS**
- Compile: SUCCESS
- Ruff: **All checks passed**
- Pytest: **304 passed, 12 warnings in 7.86s**

### Current architectural judgment

For the Choreography layer itself, the reference-style semantic contract is now complete enough for
the next production acceptance gate:

`ESTABLISH -> ADD -> INTERACT -> REACT -> PAYOFF -> RELEASE/HANDOFF`

with explicit semantic visual ownership at each stage.

Do NOT modify Motion/Focus before a fresh production render is reviewed. The remaining unknown is no
longer whether Choreography can describe the reference-style event; it is whether the existing
Motion consumer expresses this richer plan strongly enough on screen.

State:
**Choreography semantic planning complete + second-pass reference audit closed + CI proven;
perceptual acceptance requires the next real render.**

## MONTAGE19 MOTION EVENT-FLOW EXECUTION CHECKPOINT — 2026-09-24

Behavior commit:
`a163535fe6a5dd669d20e6b55833e7a707b6aff5`
`[motion] Execute semantic event flow from choreography`

Scope is intentionally limited to Motion/Focus execution.
No Pass1/Pass2, Text, Composition geometry, Story timing, or Renderer layout changes.

What changed:
- Motion now consumes Choreography semantic event flow directly instead of relying only on pattern/primary/interaction summaries.
- Event execution is driven by Final Package 1.2 authority via Choreography:
  `ESTABLISH -> ADD -> INTERACT -> REACT -> PAYOFF -> RELEASE/HANDOFF`.
- Each asset is resolved against the semantic event Story actually activated, preventing reused visuals from inheriting a stronger role from an older event.
- Directional interaction is source -> target from authored relation geometry.
- Target reaction and RESULT payoff are distinct bounded phases.
- When one asset owns multiple phases inside its active event, Motion can compile a phase chain inside the same Story-owned window when timing capacity allows.
- Short windows degrade conservatively rather than extending past semantic settle.
- Context stays quiet.
- COMPOUND_REQUIRED / family-canvas geometry remains protected.
- Every program still ends at exact Composition geometry and remains static after semantic settle.
- No topic/scene/count hardcoding.

Reference audit conclusion:
The remaining reference gap was primarily Choreography -> Motion execution, not missing semantic understanding.
The three accepted reference videos consistently use longer connected motion phrases, directional focus transfer, and RESULT as the visual destination.

Local A/B on the same Black-Hat package/timing showed:
- average visual activity approximately 3.95 -> 5.11;
- average motion burst approximately 0.316s -> 0.427s;
- median burst 0.2s -> 0.3s;
- max burst 1.3s -> 2.0s.
These are diagnostic comparison metrics, not product acceptance thresholds.

Semantic/runtime checks:
- 55/55 Black-Hat semantic events receive event-aware Motion representation;
- reused-asset event authority is preserved;
- StorySync: 0 violations;
- final geometry/timing contracts preserved.

GitHub Actions exact behavior commit:
- Run: `36061238545`
- Result: SUCCESS
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **309 passed, 12 warnings in 9.33s**

Next acceptance gate:
User should pull `montage` and perform the real production render locally with the original Final Package + narration.
Review should focus on:
1. whether motion now reads as a connected visual sentence;
2. source -> target directionality;
3. visible target reaction;
4. RESULT payoff;
5. focus handoff into the next event;
6. no motion past semantic handoff;
7. no collisions, wobble, ghosting, white flash, or geometry drift.

State:
**Motion is now directly coupled to Choreography event flow and CI-proven. Real user-side render is the next required visual acceptance step.**

## MONTAGE19 FINAL PACKAGE SEMANTICS → CHOREOGRAPHY → MOTION CLOSURE — 2026-09-24

Behavior commit:
`c405b03a617de94310223c7eec6048295415bada`
`[motion] Preserve full Final Package event semantics`

Scope:
- Final closure pass for the Choreography → Motion bridge.
- No Pass1/Pass2 changes.
- No Text changes.
- No Composition geometry changes.
- No Renderer layout changes.
- No topic/scene/count-specific rules.
- Story remains the sole timing authority.
- Composition remains the sole final geometry authority.

### Why this pass was required

The previous event-flow implementation correctly connected Motion to Choreography, but an audit of
the real Black-Hat Final Package 1.2 exposed four remaining genericity gaps:

1. rich authored relationship types could collapse to generic INTERACT/REACT motion;
2. several participants inside one semantic event could share one ADD step, so only the first had
   explicit focus ownership;
3. multiple authored results could collapse to one explicit PAYOFF leader;
4. event-to-event handoff was mostly sequential even when dependency metadata described a branch.

The fix preserves full Final Package semantic intent without inventing topic-specific behavior.

### Choreography event-flow changes

Every distinct semantic visual unit now gets its own authored phase:
- LEADER → ESTABLISH
- each PARTICIPANT → ADD
- executable relation → INTERACT
- target state response when semantically justified → REACT
- each RESULT → PAYOFF
- RELEASE/HANDOFF follows the dependency graph.

If one semantic intent resolves to multiple runtime cutouts, those cutouts remain one visual unit and
do not receive fake internal semantic order.

Final Package `progression.type` is preserved in the event-flow contract for diagnostics/future
generic behavior. No topic-specific motion is inferred from its string value.

### Dependency / branching handoff

`SemanticEventFlow` now carries:
- `handoff_mode`
- `handoff_to_event_ids`
- `handoff_to_asset_ids`
- backward-compatible singular handoff fields when there is exactly one target.

Rules:
- direct dependency edge wins over simple next-event order;
- one dependent → DEPENDENCY;
- multiple dependents → BRANCH;
- no dependency edge → SEQUENTIAL fallback;
- terminal event → NONE.

A branch never chooses one arbitrary child as the single next focus.
A merge never invents one arbitrary incoming visual source.

### Relation-specific Motion character

Motion event phases now preserve the authored semantic action instead of flattening all relations to
one generic interaction gesture.

Generic action families currently preserve distinct bounded one-shot behavior for:
- COMPARE
- LOOP / persistence
- TRAVEL
- CONNECT
- BLOCK
- REJECT
- LOCK
- PROTECT
- RESOLVE
- REVEAL
- general causal interaction fallback.

COMPARE remains balanced rather than causal.
LOOP/persistence receives one bounded tangential cue, never continuous wobble.
RESULT/PAYOFF remains the strongest visual destination while still returning to exact authored
Composition geometry.

All relationship movement remains bounded by existing density/collision-safe Motion limits.

### Reaction correctness

COMPARE and LOOP no longer automatically create a fake REACT phase merely because the relation is
executable. They create a reaction only when a meaningful authored visual state transition actually
exists.

This keeps:
- comparison as comparison;
- persistence as persistence;
- cause/effect as cause/effect.

### Multi-result attention

Every authored RESULT gets a PAYOFF step.
When multiple results share one semantic instant:
- one may remain the cohort leader;
- sibling results receive `result_peer` attention rather than being demoted to quiet support.

No result is silently lost merely because another result shares its timing.

### Compound / multi-cutout safety

If one semantic unit resolves to multiple runtime cutouts and is:
- `COMPOUND_REQUIRED`, or
- `internal_progression_unavailable=true`,

Motion abstains from per-piece event choreography.

All members use the identical one-shot:
`compound_unit_coherent_reveal`

so the semantic unit moves coherently and settles to exact authored geometry.
Pass2 family-canvas behavior remains unchanged.

### Regression matrix added

New regressions cover:
- multiple participants in one event;
- multiple results in one event;
- dependency branching;
- compare/parallel semantics;
- relation-specific Motion flavor;
- reused assets with Story event authority;
- short-window phase compression;
- compound-required multi-cutout units;
- legacy packages without semantic event flow.

### Real Black-Hat 1.2 structural audit

No-render audit against the real Final Package:
- semantic events represented: **55 / 55**
- participant visual units with explicit ADD ownership: **74 / 74**
- authored result units with explicit PAYOFF ownership: **30 / 30**
- authored relations: **15**
- executable relations preserved in Motion event flow: **14 / 14**
- `SPECIFIES`: intentionally descriptive / non-executable
- dependency handoffs: **15**
- compare fake-reaction violations: **0**
- loop fake-reaction violations: **0**
- result coverage failures: **0**
- synthetic StorySync: **PASS / 0 violations**

This is a structural/runtime contract audit, not a substitute for the user's production visual
acceptance render.

### CI proof

GitHub Actions exact behavior commit:
- Run: `36064337668`
- Result: **SUCCESS**
- Compile: SUCCESS
- Ruff: **All checks passed**
- Pytest: **315 passed, 12 warnings in 9.40s**

### Production acceptance gate

The implementation is now ready for the user-side full production render from branch `montage`.

Required visual acceptance:
1. event reads as one connected visual sentence;
2. multi-participant focus follows the spoken/semantic order;
3. relation character is visible (compare != cause, loop != impact, block != connect);
4. every meaningful authored result receives payoff;
5. dependency handoff is coherent;
6. compound visuals remain visually intact;
7. no motion crosses the next semantic handoff;
8. no collision, ghosting, white flash, wobble, or final-geometry drift.

State:
**Final Package 1.2 semantics are now strongly consumed end-to-end by Choreography and Motion,
generalized regressions are green, and the next gate is the user's real full render.**


## MONTAGE20 TIMED RELATION MOTION + SCENE CONTINUITY + ENCODED VIDEO QA CHECKPOINT — 2026-09-25

Behavior HEAD before this documentation commit:
`0b8d8a0ae362ea938e973647f332e0fa739a88c1`
`[qa] Verify semantic motion in encoded video`

Scope:
- Adds timed semantic re-activation inside a scene.
- Adds scene-to-scene continuity / handoff rendering.
- Adds structural Motion interaction QA.
- Adds scene continuity QA.
- Adds encoded-MP4 semantic Motion QA.
- No Pass1 changes.
- No Pass2 changes.
- No Pass3 / Layer3.
- No Composition geometry authority changes.
- No Text behavior changes.
- No topic-specific rules.
- Story / WhisperX remains the sole timing authority.
- Composition remains the sole final geometry authority.

### Why this pass was required

The previous MONTAGE19 closure correctly compiled Final Package semantic events into Choreography and
Motion, but one visual limitation remained: one asset was effectively represented by one short Motion
cue. That allowed a correct entry but made later semantic re-activation difficult to express.

The target behavior is now:

```
spoken mention -> ENTRY -> HOLD
relation script span -> INTERACT + overlapping REACT
result trigger / relation tail -> PAYOFF
segment end -> exact Composition geometry
later semantic event -> asset may reactivate again
```

The second missing behavior was cross-scene continuity. A new scene must not normally replace the
previous scene as an abrupt visual reset. The renderer now supports a bounded scene handoff in which
outgoing artwork remains briefly visible behind the incoming scene, exits with controlled Motion, and
may receive a blur bridge for explicit semantic continuations.

### Story relation timing

`StoryRelation` now carries:
- `spoken_start`
- `spoken_end`

Authored relation `script_span` character offsets are resolved by Story onto the narration clock.

The timing travels through:
```
Final Package relation.script_span
-> StoryRelation
-> InteractionIntent
-> EventFlowStep
-> MotionEventPhase
-> MotionSegment
```

No Motion component guesses a relation time.

Final Package semantic-entry behavior is preserved:
- exact semantic binding entry starts at the Story-owned spoken reveal;
- no new pre-speech lead was introduced.

### Multi-segment Motion contract

`MotionCue` remains the backward-compatible one-cue-per-asset container.

It now also carries:
`segments: list[MotionSegment]`

A `MotionSegment` records:
- phase
- absolute start/end
- program
- semantic_event_id
- semantic_action
- relationship
- involvement
- source/target/result asset ids
- handoff deadline

This allows one asset to:
1. enter;
2. settle;
3. hold;
4. move again during an authored relation;
5. settle exactly back to Composition;
6. participate again in a later semantic event.

### Relation timing behavior

For an authored relation window, Motion creates independent semantic windows.

Current generic timing pattern:
- source INTERACT begins at relation start;
- target REACT starts after source action has begun;
- source and target overlap intentionally;
- RESULT/PAYOFF begins near the relation tail or at the result's own spoken activation.

The implementation intentionally rejects the old visual reading:
```
A finishes -> B starts -> C starts
```

and encodes the intended reading:
```
A action
    overlaps B reaction
              -> C payoff
```

COMPARE and LOOP keep their existing non-causal reaction semantics.

### Renderer execution

`FFmpegMotionAdapter` now evaluates `MotionCue.segments` directly.

Each semantic segment is evaluated only inside its absolute time window.
Outside the window the asset returns to identity-relative Composition geometry.

No transform accumulation is allowed between semantic re-activations.

### Backward compatibility issue found and fixed

Initial behavior commit:
`40105e794cd738072efc91d128218344321ad7f5`
`[motion] Execute timed semantic relation segments`

Initial CI:
- Run: `36084620770`
- Result: **FAILURE**
- 3 failed / 316 passed / 12 warnings

The failure exposed three legacy contract regressions:
- Final Package semantic contract still expected the legacy event program to preserve directional intent;
- `test_motion_executes_choreography_event_steps_not_just_pattern_metadata` expected event-chain program identity;
- multi-result PAYOFF regression expected the existing result focus scaling contract.

Root cause:
the first implementation replaced the legacy event program whenever a timed semantic segment timeline
was present.

Fix:
`5d4efef06cf15946e7627330ac698e74531c45bd`
`[motion] Preserve legacy event program beside semantic segments`

The final design deliberately separates:
- legacy/base program = compatibility + diagnostic semantic program;
- ENTRY segment program = actual Story-timed entry used by the renderer;
- later relation segments = actual semantic re-activations.

This preserves old tested contracts without rendering the old interaction before the spoken relation.

CI after fix:
- Run: `36084770836`
- Result: **SUCCESS**
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **319 passed, 12 warnings in 7.81s**

### Motion Interaction QA

New:
`app/qa/motion_semantics.py`

Pipeline diagnostic:
`diagnostics/motion-interaction-qa.json`

Hard failures include:
- missing target reaction for causal relations;
- subject / target relation windows with zero temporal overlap;
- missing authored result PAYOFF;
- PAYOFF before the cause;
- semantic segment crossing a handoff deadline;
- missing executable keyframes;
- segment ending away from exact Composition geometry.

This means semantic metadata alone is no longer enough for a relation to pass authoring QA.

### Scene Continuity architecture

Extended existing transition seam instead of adding a duplicate subsystem:
- `app/render/transition.py`
- `app/render/renderer.py`

Modes:
- `NONE`
- `CLEAN_HANDOFF`
- `MOTION_HANDOFF`
- `BLUR_BRIDGE`

Rules:
- same-scene continuity does not invent an unrelated bridge;
- cross-scene boundaries with distinct outgoing assets receive controlled outgoing continuity;
- ordinary cross-scene change -> `MOTION_HANDOFF`;
- explicit HANDOFF / authored continuation semantics -> `BLUR_BRIDGE`;
- blur is NOT applied to every transition.

Important rendering contract:
- unrelated outgoing artwork is never alpha-crossfaded;
- outgoing artwork remains opaque behind the incoming scene;
- outgoing assets receive bounded exit/recede motion;
- blur, when selected, is applied to the old full-scene bridge;
- incoming assets remain crisp above the bridge;
- incoming Story timing remains authoritative;
- after the bridge expires the frame is the clean authored white scene.

The old pale/washed ghost silhouette regression therefore remains prohibited.

Behavior commit:
`9e5177c144dd1a148efbd7daef22eb43196d2f81`
`[render] Add semantic scene continuity bridges`

CI:
- Run: `36085256870`
- Result: **SUCCESS**
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **320 passed, 12 warnings in 10.22s**

Rendered regression coverage includes:
- previous scene remains visible across a delayed incoming spoken reveal;
- incoming artwork does not leak early merely to avoid a white boundary;
- previous scene exits and incoming scene takes ownership after the handoff;
- no internal white flash;
- blur is reserved for authored semantic handoff rather than every scene transition.

### Scene Continuity QA

New:
`app/qa/scene_continuity.py`

Pipeline diagnostic:
`diagnostics/scene-continuity-qa.json`

Hard checks:
- cross-scene boundary with distinct outgoing visuals cannot resolve to no bridge;
- selected bridge must contain outgoing visual carriers;
- bridge cannot be pathologically short;
- BLUR_BRIDGE must actually carry blur;
- non-blur transitions cannot accidentally receive blur;
- bridge cannot exceed beat duration;
- incoming Motion cannot begin before Story's current beat boundary.

Behavior commit:
`b37f48864098b63e81278ef5b170dbba15c4c9b0`
`[qa] Gate semantic scene continuity`

CI:
- Run: `36085400600`
- Result: **SUCCESS**
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **322 passed, 12 warnings in 9.51s**

### Encoded MP4 semantic Motion QA

New:
`app/qa/rendered_motion.py`

Pipeline diagnostic:
`diagnostics/rendered-motion-qa.json`

This QA runs AFTER FFmpeg produces:
`render/video-only.mp4`

It does not trust timeline metadata alone.

For each non-trivial:
- INTERACT
- REACT
- PAYOFF

the QA:
1. finds the authored Composition ROI;
2. calculates the expected transform magnitude from MotionSegment keyframes;
3. samples the encoded frame before the semantic segment;
4. samples the encoded frame near the authored motion peak;
5. measures actual pixel change in the asset ROI;
6. fails if the timeline expects meaningful movement but the encoded video is effectively static.

This catches:
```
metadata says interaction exists
but FFmpeg output did not actually move the visual
```

Rendered regression:
- a real rendered semantic segment passes;
- a deliberately static MP4 evaluated against the same expected Motion timeline fails with
  `RENDERED_SEGMENT_INACTIVE`.

Behavior commit:
`0b8d8a0ae362ea938e973647f332e0fa739a88c1`
`[qa] Verify semantic motion in encoded video`

Final behavior CI:
- Run: `36085622202`
- Result: **SUCCESS**
- Compile: SUCCESS
- Ruff: All checks passed
- Pytest: **324 passed, 12 warnings in 9.38s**

### Final validation layers now present

The pipeline now validates the target behavior at multiple levels:

1. Story timing authority
2. Final Package semantic relation mapping
3. Choreography event ownership
4. Motion multi-segment schedule
5. source/target relation overlap
6. result PAYOFF presence
7. handoff deadline safety
8. exact Composition settle
9. scene-continuity transition contract
10. actual encoded MP4 Motion activity
11. existing final A/V drift and white-flash recovery checks
12. existing rendered contact sheet evidence

### Production render acceptance gate

The code and automated QA are now ready for a fresh real production render from `montage`.

The real render must still be visually reviewed against the accepted reference behavior, especially
`hallo` style continuity. The reference video itself was not accessible as a file in this chat
session, so this checkpoint must not claim a new frame-by-frame perceptual comparison.

Review the next real render for:
1. entry never precedes the spoken semantic activation;
2. already-visible source can reactivate later during relation speech;
3. source and target visibly overlap in time;
4. RESULT/PAYOFF reads after the interaction rather than at its beginning;
5. repeated re-activation produces no wobble or accumulated geometry drift;
6. scene A does not disappear as an abrupt reset when a cross-scene bridge is required;
7. outgoing A motion remains readable while incoming B begins;
8. authored continuation may use blurred old-scene bridge behind crisp incoming artwork;
9. blur ends and returns to clean authored white Scene B;
10. no ghost silhouette, white flash, black frame, collision expansion or semantic leakage;
11. relation character remains distinct (COMPARE != causal CONNECT/BLOCK/REJECT/etc.);
12. overall sequence reads as connected visual sentences rather than independent icon pop-ins.

### Next operator instructions

1. Pull branch `montage`.
2. Confirm HEAD is this documentation commit or newer.
3. Run the normal production batch with the real Final Package + narration.
4. Do NOT disable:
   - MotionInteractionQA
   - SceneContinuityQA
   - RenderedMotionQA
   - StorySyncQA
5. Preserve all diagnostics from the run:
   - `motion-interaction-qa.json`
   - `scene-continuity-qa.json`
   - `rendered-motion-qa.json`
   - `story-sync-qa.json`
   - `authoring-visual-qa.json`
   - `visual-contact-sheet.jpg`
6. Review the resulting MP4 perceptually against the references before any additional Motion tuning.
7. If the render fails a QA gate, fix the general contract; do not weaken thresholds or add a
   package/scene-specific exception.

State:
**Timed semantic re-activation, source/target overlap enforcement, result payoff, scene continuity,
optional semantic blur bridge, encoded-video Motion verification and regression coverage are all
implemented and CI-proven. The remaining gate is the fresh real production render and perceptual
acceptance against the references.**


## MONTAGE20 POST-CHECKPOINT FINAL PACKAGE CONSUMPTION + RENDER SAFETY AUDIT — 2026-09-25

This audit was performed after the timed Motion / Scene Continuity checkpoint because the operator
explicitly requested a code-level review before running the next production render.

Behavior HEAD entering the audit:
`772072a98150c424584efcfae0da43f9a9a53624`

Important limitation:
the exact real Black-Hat / Gray-Hat V1.2 ZIP bytes were not accessible as a conversation/library file
in this chat session. Therefore this audit proves the generic V1.2 code path and actual encoded FFmpeg
runtime with a synthetic rich V1.2 package, but it does not claim that the operator's exact ZIP has
already been executed in this session. The next real production run remains the package-specific gate.

### Final Package consumption audit

The code path was traced live from loader through encoded output.

Confirmed behavior-driving fields:

- canonical `script_text` / `script_span`:
  validated by FinalPackageLoader and converted by Story onto forced-aligned narration timing.
- `visual_locator`:
  consumed by Story activation identity binding; explicit locator evidence can map one semantic intent
  to one or multiple real cutouts without falling back to unsafe size/order guessing.
- `binding_type`:
  controls explicit vs semantic activation policy; ambiguous bindings abstain.
- `semantic_group_id` + group `animation_policy`:
  preserved into AssetActivation and Motion grouping/stagger behavior.
- `sequence_order`:
  authoritative Motion ordering before layout/extraction fallback.
- `semantic_role` / `visual_focus`:
  drives Story roles, attention hierarchy, Choreography focus and Motion attention budget.
- `visual_state.before/after`:
  compiled into authored VisualStateTransition rows before inferred state transitions.
- asset `continuity`:
  preserved in Story and now consumed as semantic evidence for scene-handoff mode selection only.
  It never owns destination geometry.
- `semantic_event_id`, event `sequence_order`, leader/participant/context/result/text-anchor roles:
  drive event-flow ownership, focus path, result PAYOFF, text anchoring and Motion event assignment.
- `depends_on_event_ids`:
  drives dependency handoff and is now also honored by MotionInteractionQA for result PAYOFF events.
- `compound_visual_classification` + `internal_progression_unavailable`:
  prevent fake per-piece choreography for compound semantic units.
- asset relations:
  source/object/result + relation type + authored relation script span drive InteractionIntent,
  relation-specific Motion and timed multi-segment reactivation.
- scene `relation_to_previous` and semantic continuity:
  select scene transition class without changing Composition geometry.
- semantic event progression:
  consumed by event-flow order / dependency logic and now hard-gated against downstream loss.
- text-anchor metadata:
  beats generic beat-primary fallback when selecting which visual owns a text relationship.

Validation-only / descriptive fields remain validation/evidence rather than independent Motion
instructions where that is semantically correct. For example, anchor granularity constrains/validates
the authored text span; it does not invent a second timing authority.

### Loader / package rejection coverage

FinalPackageLoader rejects malformed V1.2 contracts before expensive work, including:
- bad/missing scene or semantic-binding files;
- semantic asset intent missing from scene plan;
- invalid or mismatched canonical script spans;
- invalid semantic-group coverage;
- broken relation references;
- invalid relation source/object/result references;
- invalid semantic event membership;
- invalid event dependencies / cycles;
- progression/event-order mismatch;
- top-level semantic event mirror mismatch;
- unsafe package paths / missing scene images.

The V1.2 contract remains:
`cutout_mapping_cardinality = ZERO_OR_ONE_OR_MANY`.

Therefore an authored semantic intent is not automatically required to produce its own independent
cutout. This is intentional. A missing independent cutout is not converted into a broad Pass3 or a
false hard failure. Explicit executable relations/results are instead protected by downstream event,
interaction, asset-binding and encoded Motion QA.

### Audit finding 1 — half-open relation script span

Found:
FinalPackageLoader validates semantic-binding script spans as half-open `[start,end)`, while the
legacy Story timing helper accepts an inclusive end. New relation timing initially passed the
half-open end directly.

Risk:
relation timing could extend by one character / into the following narration token. This was primarily
a semantic timing precision bug, not a typical renderer crash, but it could weaken choreography sync.

Fix:
`daca47f057797290ece31e8eaf3c5d6c15a02716`
`[story] Honor half-open relation script spans`

The relation boundary alone now converts `end -> end - 1` before using the legacy helper. Legacy
scene timing contracts were not changed.

CI:
- Run `36086305135`
- SUCCESS
- Compile SUCCESS
- Ruff SUCCESS
- Pytest **324 passed, 12 warnings in 9.72s**

### Audit finding 2 — V1.2 event / asset-relation coverage gate

Found:
StorytellingValidator's generic relationship coverage still counted only the older
`FINAL_PACKAGE_INTERACTION_TARGET` authority. V1.2 `FINAL_PACKAGE_ASSET_RELATION` was executed by
Choreography/Motion, but a theoretical downstream drop was not covered by that specific hard gate.
Semantic-event package-vs-Choreography coverage was also not an explicit hard set comparison.

Fix:
`5fad6bed8d99c5edb50044a55a8b7b45eb70729c`
`[qa] Gate Final Package event and asset-relation coverage`

Now:
- relationship coverage counts old and V1.2 asset-relation authorities;
- authored V1.2 semantic events are compared with represented Choreography event flows;
- missing semantic events produce `FINAL_PACKAGE_SEMANTIC_EVENT_COVERAGE` hard failure before render;
- V1.2 regression asserts full relation + 2/2 event representation.

CI:
- Run `36086548914`
- SUCCESS
- Compile SUCCESS
- Ruff SUCCESS
- Pytest **324 passed, 12 warnings in 10.55s**

### Audit finding 3 — delayed incoming reveal could overextend blur

Found:
the first Scene Continuity implementation extended the outgoing bridge to cover a delayed incoming
Story cue. For a long narration gap, this could make the previous scene remain blurred much longer
than the intended reference-style transition.

This was not a crash bug, but it violated the desired visual grammar:
`A crisp -> short outgoing/blur bridge -> B crisp -> clean settle`.

Fix:
`2400b35367f976d170220258d518f594d29269bd`
`[render] Bound semantic blur bridge around incoming reveal`

New behavior:
- old scene remains crisp across a narration gap;
- bridge begins shortly before the first Story-owned incoming reveal;
- bridge duration remains bounded by transition policy;
- outgoing Motion occurs only during the bridge;
- BLUR_BRIDGE blurs only the short bridge interval;
- B remains crisp;
- bridge ends shortly after incoming ownership begins;
- `CONTINUES_EXPLANATION`-style scene relations are recognized by semantic continuity matching;
- asset-level `PERSIST / TRANSFORM_TO` continuity can select a semantic bridge but never controls
  position/size.

CI:
- Run `36086810367`
- SUCCESS
- Compile SUCCESS
- Ruff SUCCESS
- Pytest **326 passed, 12 warnings in 10.33s**

### Audit finding 4 — end-to-end V1.2 test exposed result-event QA mismatch

A new end-to-end regression was added:
`[test] Render V1.2 semantic package end to end`
commit:
`2b56b73f504ca02d92ceded74d83eb17785d41bd`

The test executes:
```
FinalPackageLoader
-> StoryPlanner
-> ChoreographyDirector
-> MotionPlanner
-> MotionInteractionQA
-> RenderPlan
-> real FFmpegRenderer / H.264 MP4
-> RenderedMotionQA
```

First run:
- CI `36086926919`
- FAILURE
- **1 failed, 326 passed, 12 warnings**

The failure was useful and correct to investigate:
the relation lived in event `E1`, while its authored result `C` lived in event `E2`, with
`E2 depends_on E1`. Motion correctly created C's PAYOFF in E2. MotionInteractionQA incorrectly
required the result PAYOFF to duplicate E1.

Fix:
`573e8b2c84e7d43b4f0d40c73a736cdf7654a310`
`[qa] Follow dependent events for result payoff`

QA now accepts a result PAYOFF in:
- the relation event itself; or
- the result asset's authored semantic event when that event explicitly depends on the relation event.

It does NOT accept arbitrary later events. The dependency must come from Story/Final Package.

Final V1.2 end-to-end CI:
- Run `36087049362`
- SUCCESS
- Compile SUCCESS
- Ruff SUCCESS
- Pytest **327 passed, 12 warnings in 7.41s**

This proves the synthetic rich V1.2 semantic package survives through a real encoded MP4 and encoded
Motion verification.

### Render/runtime risk assessment after audit

Code-level crash risk is now guarded by:
1. strict package/schema/script-span validation;
2. semantic-intent-to-cutout binding and locator evidence;
3. Story timing / StorySync;
4. full V1.2 semantic-event coverage gate;
5. old + V1.2 relation coverage gate;
6. Choreography asset requirements / diagnostics;
7. AssetUsageValidator for independently animatable runtime cutouts;
8. MotionInteractionQA for overlap / dependent PAYOFF / settle / handoff;
9. SceneContinuityQA;
10. real FFmpeg transition regressions;
11. real V1.2 semantic-package-to-MP4 regression;
12. RenderedMotionQA on encoded frames;
13. release smoke test through H.264 render + AAC mux;
14. RecoveryDetector A/V drift and white-flash checks;
15. rendered contact-sheet evidence.

No code review can honestly guarantee that an unseen real ZIP and a different local machine will
never produce an environment/package-specific error. The exact package-specific guarantee requires
running that exact package. The current code now fails early with a diagnostic for known contract
violations rather than silently producing a wrong semantic render.

### Required next production gate

Pull the final `montage` HEAD after this audit documentation commit and run the real Final Package
with its narration.

If it completes, retain:
- `motion-interaction-qa.json`
- `scene-continuity-qa.json`
- `rendered-motion-qa.json`
- `story-sync-qa.json`
- `storytelling-authoring.json`
- `authoring-visual-qa.json`
- `visual-contact-sheet.jpg`

Then review the actual MP4 against the references. At this point any remaining work should be driven
by the real perceptual result, not by another speculative architecture rewrite.

State:
**The V1.2 Final Package contract is now consumed and hard-gated across Loader, Story, Choreography,
Motion, Scene Continuity and encoded-video QA. A synthetic rich V1.2 package completes a real FFmpeg
render in CI. The remaining unknown is only the operator's exact unseen production ZIP/environment,
which must be validated by the next real render.**


## MONTAGE20 REAL BLACK-HAT DIAGNOSTIC ENTRY/HANDOFF FIX — 2026-09-25

Real production diagnostic:
- Job: `3d5bd61b707b43fe8507eeca5e73bbe4`
- Final Package: `HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2.zip`
- Audio: ElevenLabs Ahmed narration used by operator
- Runtime platform: Windows 10 / Python 3.11.9 / FFmpeg 9.0.2
- Input package, transcription, vision, Pass1, Pass2, Story, Text and Composition all completed.
- Pass1: 157 authored assets across 40 scenes.
- Pass2: 179 assets (+22).
- Story: 40 beats.
- Composition: Final Package geometry locked; 87 text cues placed.
- Failure occurred only at MotionInteractionQA before FFmpeg render.

Observed violations:
- `beat-017 / SCENE_017:asset-02`: ENTRY 37.759 > handoff 37.087
- `beat-021 / SCENE_021:asset-03`: ENTRY 46.037 > handoff 45.749
- `beat-027 / SCENE_027:asset-01`: ENTRY 58.410 > handoff 57.572
- `beat-038 / SCENE_038:asset-03`: ENTRY 87.734 > handoff 87.117

Root cause:
the semantic timeline correctly computed the next event handoff deadline, but the ENTRY segment still
copied legacy `cue.end` unchanged. Therefore an otherwise valid Story-owned reveal could continue
moving after the next semantic event had already taken ownership.

Fix:
`c8f64aac6c9ba06fef6cf6950d0b1b6ef2311462`
`[motion] Fit entry before semantic handoff`

New contract:
```
ENTRY.start = Story-owned cue.start
ENTRY.end   = min(legacy cue.end, semantic handoff deadline)
```

When clipping is required:
- the ENTRY trajectory is time-compressed only inside the legal pre-handoff window;
- transform amplitude is reduced based on the available duration to avoid a violent fast entry;
- the last ENTRY keyframe remains exact Composition identity;
- the next semantic event can start with no transform overlap or accumulated drift.

If there is effectively no positive interval before handoff:
- ENTRY is omitted;
- the visual snaps directly to its authored Composition geometry at reveal;
- later semantic INTERACT/REACT/PAYOFF segments still execute normally;
- the system does not cross the handoff merely to preserve an entrance animation.

Important:
- MotionInteractionQA was NOT weakened.
- `SEGMENT_PAST_HANDOFF` remains a hard failure.
- no scene-specific ids, timings or Black-Hat topic rules were added to production code.
- the exact four real diagnostic end/deadline pairs are now regression test cases.

Regression coverage:
- 4 parameterized tests reproduce all real diagnostic violation pairs.
- each verifies ENTRY ends exactly at the handoff deadline.
- each verifies exact Composition settle at the final keyframe.
- each verifies clipped displacement is reduced.
- each verifies MotionInteractionQA passes afterward.
- zero-pre-handoff-time fallback is tested separately.

CI:
- Run: `36088489474`
- Result: **SUCCESS**
- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **332 passed, 12 warnings in 10.11s**

Production state:
**The real Black-Hat diagnostic Motion failure is fixed at the scheduler, not hidden in QA. Pull the
new montage HEAD and rerun the exact same Final Package + audio. Any subsequent failure should be
treated as the next real production gate and diagnosed from its new diagnostic ZIP.**


## MONTAGE21 PERCEPTUAL MOTION + SELECTIVE CONTINUITY SPRINT CHECKPOINT — 2026-09-25

Behavior HEAD before this documentation commit:
`6b7705e8a458ddec469f2f0e3b411ab391a28faf`
`[lint] Remove obsolete paired outgoing temporary`

### Why this sprint was opened

The operator supplied the real rendered Black-Hat MP4 after the timed semantic-motion / scene
continuity work. Frame-by-frame visual review showed that the previous architecture was semantically
richer than the visible result:

- many changes read as appearance / disappearance rather than a clear trajectory;
- INTERACT / REACT / PAYOFF existed in metadata but were often too small to perceive;
- RELEASE existed in Choreography but did not become a real visual EXIT;
- scene continuity was visually dominated by blur;
- PERSIST / TRANSFORM_TO semantics incorrectly acted like reasons to blur the whole outgoing scene;
- outgoing scene movement was only about 34px horizontal / 10px vertical and was visually hidden by blur;
- encoded-video QA proved that pixels changed, but not that the motion was large enough to read.

This sprint was therefore treated as a perceptual-motion architecture correction, not an easing/parameter
tuning pass.

No extraction architecture changed:
- Pass1 unchanged.
- Pass2 unchanged.
- no Pass3 / Layer3.
- Composition remains the only final geometry authority.
- Story / WhisperX remains the only narration timing authority.
- Final Package semantic events / relations remain the semantic authority.

### Sprint Task 1 — make blur explicit, not a synonym for continuity

Initial transition correction:
`a644a07f805e17443e04523aa76c66c59c3ca6a4`
`[render] Make blur explicit and continuity object-level`

Final refinement:
`3123b6c5f7543a598dffd16870b0e13134e62109`
`[render] Keep full outgoing continuity and require explicit blur style`

New transition classes:
- NONE
- CLEAN_HANDOFF
- OBJECT_HANDOFF
- MOTION_HANDOFF
- BLUR_BRIDGE

Rules:
- generic HANDOFF does NOT imply blur;
- CONTINUES_EXPLANATION does NOT imply blur;
- RESULT / PAYOFF does NOT imply blur;
- PERSIST / TRANSFORM_TO does NOT imply whole-scene blur;
- a continuity word such as SOFT_CONTINUATION does not itself authorize blur;
- BLUR_BRIDGE requires explicit render-style intent such as BLUR / DEFOCUS / DEPTH_BRIDGE or an
  explicit transition-style field whose value is intentionally soft/blurred.

Blur sigma was also reduced from the earlier 7.5 to 5.5 for the cases where blur is truly authored.

Scene outgoing motion is no longer a fixed tiny 34px / 10px nudge. It is resolution-aware and bounded:
- MOTION_HANDOFF: approximately 5% horizontal / 3.2% vertical where geometry allows;
- OBJECT_HANDOFF: approximately 4% / 2.6% fallback;
- BLUR_BRIDGE remains intentionally smaller so blur does not compete with large travel.

At 1920x1080, tests require ordinary outgoing handoff displacement to be perceptually readable.

### Sprint Task 2 — real object-level continuity

Core runtime pairing:
`1fa340db55451fccef89780c110d55e0d4da1964`
`[render] Resolve object continuity to runtime cutout handoffs`

Regression commits:
`814941b1ad0ebe0eff10c6765e6cde6c11ce9821`
`[test] Prove runtime object handoff pairing`

`68ef17b60c2f2644910e9e79f79ba0a0cdca5561`
`[test] Drive object handoff QA from runtime semantic pairing`

PERSIST / TRANSFORM_TO is now resolved from authored semantic ids to actual Pass1/Pass2 runtime cutout
ids using AssetActivation bindings.

An OBJECT_HANDOFF is allowed only when there is one unambiguous runtime old-cutout -> new-cutout pair.
Ambiguous mapping abstains rather than inventing a transform.

For an accepted pair:
- old runtime cutout moves toward the new cutout's authored Composition position;
- movement uses roughly 55% of the old->new vector, bounded to safe transition displacement;
- new cutout still enters according to Story timing;
- Composition still owns the final new position;
- the old cutout is never allowed to redefine the new layout.

Final code review found an additional visual issue: carrying only the paired old cutout would cause all
other old-scene visuals to hard-cut. The final policy therefore keeps every outgoing old-scene visual
alive during the short bridge. The paired visual seeks its target; unpaired visuals perform normal
recede/exit motion.

Regressions prove:
- runtime semantic id pairing;
- target-directed movement;
- all unpaired outgoing scene visuals remain in the bridge until their short exit;
- no global blur is required.

### Sprint Task 3 — perceptually readable ENTRY

`9734d6213d15fbc57452381e6c794e9125cfd89d`
`[motion] Enforce readable semantic entries`

ENTRY now has a size-aware normalized motion floor for normal independent cutouts.
The floor is reduced for very short windows so compressed timing does not become violent.

Geometry-locked family/compound units are excluded from this strengthening.

The final keyframe remains exact Composition identity.

### Sprint Task 4 — stronger INTERACT / REACT / PAYOFF

`60475ce533729f90b36900055d2304047c862fa6`
`[motion] Add semantic exits and readable interaction floor`

Event-specific perceptual floors now apply after semantic direction is derived from actual Composition
geometry:

- INTERACT: minimum normalized movement about 0.030;
- REACT: minimum about 0.026;
- PAYOFF: minimum movement/scale emphasis;
- PAYOFF scale accent: at least about 7.5% where safe for the semantic segment;
- REACT scale accent: at least about 4.5% where a reaction would otherwise be visually negligible.

The direction is still authored-semantics / Composition-derived:
- source INTERACT moves relative to target;
- target REACT responds relative to source;
- COMPARE / LOOP / BLOCK / REJECT / TRAVEL / CONNECT etc. keep distinct motion character;
- no generic random direction was introduced.

### Sprint Task 5 — RELEASE becomes a real EXIT

Motion planner now produces EXIT segments for outgoing assets at semantic handoffs.

Renderer implementation:
`8ce0f8a9fef5dda319774dc26805ffd3a528d623`
`[render] Hide assets after semantic exit`

EXIT behavior:
- starts after the asset's prior semantic activity;
- gets a directional leave trajectory;
- shrinks slightly while leaving;
- finishes at the semantic handoff deadline;
- renderer stops overlaying the asset after EXIT.end.

This means RELEASE is no longer just metadata.

Normal MotionProgram invariant remains:
all ordinary programs must finish exactly on Composition.

An initial EXIT implementation violated that invariant by trying to encode a non-identity terminal
keyframe as a normal MotionProgram.

Integration CI:
- Run `36090768039`
- FAILURE
- Compile SUCCESS
- Ruff SUCCESS
- Pytest **5 failed, 334 passed, 12 warnings**
- all 5 failures were the same invariant:
  `motion program must finish on the Composition target`

Correct fix:
`884ebac99a0bd3f4b42b228cfe9bc57ee71782d7`
`[motion] Keep exit terminal behavior outside settle invariant`

EXIT is now an explicit MotionSegment payload with:
`terminal_behavior = LEAVE`

The strict identity-settle invariant for every normal MotionProgram was NOT weakened.

Final review also found that ENTRY could consume the whole pre-handoff window and leave no readable
space for EXIT.

Fix:
`57b014a673f9f28546a3fd9c0644c5e635fd96b7`
`[motion] Reserve readable exit time before semantic handoff`

When a normal window is large enough (>= about 0.34s), planner reserves about 0.18s for EXIT.
Tight windows preserve semantic timing instead of forcing a rushed exit.

### Sprint Task 6 — encoded MP4 must prove readable motion, not merely changed pixels

`a0c31fad36e0c8ea1fc78f527765e6eca6cc4bdf`
`[qa] Enforce perceptual motion floor in encoded video`

RenderedMotionQA now evaluates:
- ENTRY
- INTERACT
- REACT
- PAYOFF
- EXIT

It computes expected encoded movement in pixels and applies a phase-specific readable floor, bounded by
asset size.

Typical floor ratios:
- ENTRY: ~1.0% canvas width
- INTERACT: ~1.5%
- REACT: ~1.3%
- PAYOFF: ~0.9%
- EXIT: ~1.6%

The floor is bounded to avoid unreasonable demands on small visuals.
Geometry-locked / compound-unit motion is conservatively exempt.

New failure:
`MOTION_BELOW_PERCEPTUAL_FLOOR`

Existing encoded ROI activity verification remains, so a segment must both:
1. be authored strongly enough to read; and
2. actually survive FFmpeg encoding as visible pixel activity.

Regression:
`4fe925f6b604dd24c61845903b6da25d0bd639c7`
`[test] Reject tiny motion and prove encoded exits`

Tests prove:
- deliberately tiny 0.5%-class motion is rejected;
- real encoded EXIT moves and then disappears from the ROI.

### Sprint Task 7 — scene continuity QA updated for object handoff and explicit blur

`f914df14145d22604647d9ebcd4bdc6733727d42`
`[qa] Accept object handoffs and require explicit blur intent`

SceneContinuityQA now accepts OBJECT_HANDOFF as a real continuity bridge.

BLUR_BRIDGE additionally requires:
`reason == explicit_blur_intent`

Therefore the renderer cannot silently reintroduce generic continuity blur without breaking QA.

Regression:
`643d31f0411b9a8a09198c9a34f72e6019ad46ab`
`[test] Cover object handoff continuity without blur`

Final refinements:
- soft continuation wording alone is proven not to blur;
- explicitly styled soft_blur_bridge is still allowed;
- object handoff with extra old visuals is proven to retain them for exit rather than hard-cutting.

### Sprint Task 8 — stronger motion must not create new collisions

Final independent code review identified one remaining architectural risk:
raising perceptual floors could create a collision even when Final Package Composition had safe spacing.

Hardening commit:
`1dc4c778a951baff0e8bfbfd8d580c8dcf9ff27d`
`[qa] Prevent stronger semantic motion from creating collisions`

MotionInteractionQA now optionally consumes Composition.

For source INTERACT + target REACT:
- samples the actual simultaneous overlap window;
- evaluates Motion keyframes/easing at that shared time;
- computes normalized transformed boxes;
- compares authored overlap against animated overlap;
- geometry-locked assets are excluded;
- pre-existing authored overlap is respected;
- hard failure occurs only when previously separate artwork gains a material new overlap.

Failure code:
`MOTION_CREATES_COLLISION`

The first regression fixture did not actually collide and CI correctly refused to fail it:
- Run `36091396474`
- FAILURE
- Compile SUCCESS
- Ruff SUCCESS
- **1 failed, 341 passed, 12 warnings**
- the only failed assertion expected a collision that the geometry correctly showed was still safe.

The test geometry was corrected to remain authored-separated by about 0.5% canvas width while being
close enough that the stronger relation motion truly creates a collision. QA thresholds were NOT
weakened.

Regression fix:
`b7ebbedeb127a3f1a431dad6c7a5120fd32df8f9`
`[test] Exercise actual motion-created collision geometry`

### Final review cleanup

The final review also tightened blur semantics and full outgoing continuity:
`3123b6c5f7543a598dffd16870b0e13134e62109`
`[render] Keep full outgoing continuity and require explicit blur style`

Regression:
`44e90fe71fa4d9d8163bb152fa8f7e2d288da30a`
`[test] Guard blur intent and full outgoing object continuity`

That run stopped on one Ruff-only issue: an obsolete local `paired_outgoing` variable remained after
the policy changed to carry all outgoing visuals.

CI:
- Run `36091593915`
- FAILURE
- Compile SUCCESS
- Ruff FAILURE: F841 unused `paired_outgoing`
- Pytest skipped

Cleanup:
`6b7705e8a458ddec469f2f0e3b411ab391a28faf`
`[lint] Remove obsolete paired outgoing temporary`

No behavior changed in the cleanup.

### Final integration CI

Run:
`36091683824`

Result:
**SUCCESS**

- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **344 passed, 12 warnings in 10.80s**

### Final independent code review

The sprint was reviewed from the pre-sprint Black-Hat behavior point:
`5676c907761a153859bbd11ab82504547718842f`
through:
`6b7705e8a458ddec469f2f0e3b411ab391a28faf`

Scope:
- 20 commits
- production files changed only in Motion / Render / QA / Pipeline integration
- tests extended accordingly
- no Pass1 files changed
- no Pass2 files changed
- no Composition planner authority changed
- no Text selection/placement ownership changed
- no Final Package schema weakened

Reviewed invariants:
1. Story still owns reveal/relation/handoff timing.
2. Composition still owns every final in-scene destination.
3. ordinary MotionProgram still settles exactly to Composition.
4. EXIT is the only intentional terminal non-settle behavior and disappears immediately afterward.
5. compound/geometry-locked visuals remain conservative.
6. interaction direction comes from semantic relation + authored geometry.
7. source/target overlap in time remains mandatory.
8. stronger motion cannot cross semantic handoff.
9. stronger source/target motion cannot introduce a material new collision.
10. blur is explicit-only, not continuity-by-default.
11. object continuity resolves semantic intent to actual runtime cutouts and abstains when ambiguous.
12. unpaired outgoing scene visuals receive short exit continuity instead of hard cuts.
13. encoded MP4 QA now requires perceptually meaningful motion, not merely nonzero pixels.

No additional code-level blocker was found after the collision and full-outgoing-continuity fixes.

### Production acceptance gate

This checkpoint proves architecture, scheduling, FFmpeg execution, structural QA, encoded-motion QA and
regression behavior.

It does NOT claim that the visual target is already perceptually accepted until the same real Black-Hat
Final Package + narration is rerendered and reviewed.

The next production render should specifically be checked for:
- visible ENTRY trajectories rather than simple pop-ins;
- obvious but controlled source INTERACT;
- temporally overlapping target REACT;
- readable PAYOFF;
- actual per-element EXIT / disappearance at handoff;
- old-scene visuals moving/receding rather than vanishing;
- PERSIST / TRANSFORM_TO reading as an object-level handoff;
- blur appearing only when explicitly authored and no longer dominating scene continuity;
- no new collisions, white flashes, ghosting, wobble or geometry drift.

State:
**The motion/choreography weakness observed in the supplied Black-Hat render has been addressed at the
architecture, renderer and QA levels. Final CI is green. The remaining gate is a fresh real Black-Hat
rerender for perceptual comparison against the supplied render and reference videos.**


## MONTAGE22 GOLDEN MOTION COMFORT CHECKPOINT — 2026-09-25

Behavior HEAD before this documentation commit:
`6f88e218858069c8ae35143dd6a3c2a7ed7613a5`
`[qa] Measure semantic motion in true pixel travel distance`

This sprint was opened after the operator accepted the stronger semantic-motion architecture but
correctly identified two remaining perceptual risks:

1. movement could still feel accelerated / rushed, especially exits and short semantic reactions;
2. Golden Ratio had not yet been formalized as an engine-wide motion timing rule.

The goal was NOT to weaken the stronger motion from MONTAGE21. The goal was to keep motion expressive
while making its timing smooth, comfortable and internally consistent.

### Locked Golden timing contract

Central constants now live in `app/motion/timing.py`:

- `GOLDEN_MAJOR = 0.6180339887498949`
- `GOLDEN_MINOR = 0.3819660112501051`

Golden Ratio is no longer an incidental numeric resemblance.

It is consumed by:
- ENTRY trajectory shaping;
- semantic INTERACT / REACT / PAYOFF timing;
- EXIT trajectory shaping;
- scene-handoff lead timing;
- rendered-motion comfort QA.

### Central MotionComfortProfile

The engine now has an explicit phase comfort contract:

- ENTRY: target ~0.42s, minimum ~0.26s, normalized speed ceiling ~0.14/s;
- INTERACT: target ~0.40s, minimum ~0.28s, speed ceiling ~0.13/s;
- REACT: target ~0.36s, minimum ~0.26s, speed ceiling ~0.12/s;
- PAYOFF: target ~0.42s, minimum ~0.30s, speed ceiling ~0.11/s;
- EXIT: target ~0.40s, minimum ~0.32s, speed ceiling ~0.14/s.

These are comfort targets, not permission to violate Story timing.

When Story provides less time:
- semantic timing remains authoritative;
- amplitude is reduced to fit the legal speed envelope;
- a decorative EXIT is omitted when no comfortable exit window remains;
- the engine does NOT accelerate motion just to preserve a nominal displacement.

### ENTRY — Golden deceleration without wobble

Commit:
`ffd551cf4b822814f7d3f4602256abc91dca0f82`
`[motion] Shape entry travel with golden-ratio deceleration`

A normal entry now has:
- authored start transform;
- one Golden checkpoint at `settle_progress * 0.618...`;
- approximately 38.2% of the original remaining displacement at that checkpoint;
- final semantic settle exactly at Composition;
- post-settle hold with no recoil/wobble.

The interpolation is smooth (`ease_in_out_cubic` / `smoothstep`) rather than a mechanical snap.

ENTRY readability strengthening is now duration-aware and bounded by the comfort speed budget.

### INTERACT / REACT / PAYOFF — expressive but no rushed return

Core commits:
`c52f2ef165a1c412a761db3fd221110d3e2666fe`
`[motion] Apply golden-ratio smooth timing and comfort speed caps`

`f93cc450e55a8b7fdf1125d014d5efca791f7abe`
`[motion] Cap semantic accents by shorter golden return leg`

Semantic event segments are still real out-and-back reactions:
- start from Composition identity;
- reach the semantic accent at 61.8% progress;
- return to Composition during the final 38.2%.

The important correction is that the final 38.2% is the speed bottleneck.
Displacement is therefore capped against the shorter Golden return leg, not against the whole segment.

This prevents the previous failure mode:
a segment could have a comfortable average duration but snap back too quickly after its peak.

Meaning still owns direction:
- source moves relative to target;
- target reacts relative to source;
- compare/loop/block/reject/travel/connect/etc. remain distinct;
- no random generic vector was introduced.

### Strong scale emphasis remains, but is asset-size aware

Commits:
`e16026e050b900657afe4389989fe440e7429d3b`
`[motion] Keep payoff emphasis strong with asset-aware scale speed`

`e9b67c766b5eecb3e38a4433c5028ea1abd445dc`
`[motion] Bound reaction scale by asset-aware comfort speed`

Scale is not unnecessarily weakened just because translation has a speed limit.

Instead:
- the allowable scale delta is projected through the actual authored asset extent;
- PAYOFF can retain a strong emphasis when the object is small enough for it to remain comfortable;
- REACT/PAYOFF scale is also capped from above, so a semantic primitive cannot inject a fast zoom spike.

Thus the engine preserves expression without allowing scale to bypass the motion-speed contract.

### EXIT — comfortable release, never a forced snap

The prior ~0.18s fixed exit reserve from MONTAGE21 is superseded.

EXIT now uses the central comfort profile:
- target ~0.40s;
- minimum ~0.32s;
- Golden checkpoint at 61.8%;
- approximately 61.8% of total leave displacement reached at that checkpoint;
- final 38.2% completes the leave;
- the proportional distance/time split produces smooth approximately uniform perceived travel before
  the asset is removed.

If there is insufficient legal time for both the current semantic activity and a comfortable exit:
- INTERACT / REACT / PAYOFF keep their Story-owned timing;
- EXIT is omitted instead of stealing time from meaning or accelerating.

Commit:
`e8143461a87620125600f9f45f8170591fe6c4e0`
`[motion] Prioritize semantic phases and cap golden-leg speed`

This is a priority invariant:
**semantic meaning outranks decorative release.**

### Scene handoff — smooth travel instead of linear slide

Commit:
`dc91fed5e446fa9f35a693ea12ce6004842da90e`
`[render] Smooth scene handoff travel with golden lead timing`

The outgoing scene bridge previously used linear FFmpeg progress.

It now:
- uses smoothstep-style progress;
- uses Golden minor (~38.2%) to derive the bounded lead before incoming reveal;
- preserves the existing explicit-only blur rule;
- does not reintroduce default blur.

Object handoff / motion handoff therefore follows the same comfort language as in-scene motion.

### Story V2 ultra-short windows remain exact

Commit:
`5573b20f29a15eb743c326c482ffa2f07ad75cc9`
`[motion] Preserve exact Story timing in sub-frame golden windows`

The renderer has an intentional 50ms minimum interpolation window.
For a Story-owned activation shorter than 50ms, an interior Golden checkpoint has no perceptual value
and can create rounding ambiguity around the exact semantic settle.

The compiler therefore collapses sub-50ms Story-V2 entries to:
- one legal transform leg;
- exact Story settle;
- Composition hold.

Golden shaping is used when it is perceptually expressible.
Story timing always wins when it is not.

This preserves the strict no-early/no-late synchronization contract.

### Rendered Motion QA — now checks comfort, not only strength

Commit:
`d55d3033f38cb90bfc42179c6daf51be2d844ec1`
`[qa] Reject rushed motion and scale floors by Story time`

New hard failure:
`MOTION_TOO_FAST`

RenderedMotionQA now verifies both sides of the perceptual envelope:
- too weak => `MOTION_BELOW_PERCEPTUAL_FLOOR`;
- too fast => `MOTION_TOO_FAST`.

Subsequent hardening aligned QA math with Planner math:

`81a56248c342ccd6f8e80c470d298e9babe1b435`
`[qa] Measure comfort speed on actual keyframe legs`

Speed is measured on each real keyframe leg, not as whole-segment average.

`7d0a15fb053ae3ed69535fe3abb5de31be3e329a`
`[qa] Bound readability floor by available comfort-speed budget`

A readability floor may never require more displacement than the legal comfort-speed budget for the
available Story time.

`d1b5eaf59d1a46ff74955899c8aab56b1ddd6e05`
`[qa] Project comfort budget through actual gesture direction`

Normalized motion is projected through:
- actual x/y gesture direction;
- canvas aspect ratio;
- actual authored asset extent;
- scale contribution.

`6f88e218858069c8ae35143dd6a3c2a7ed7613a5`
`[qa] Measure semantic motion in true pixel travel distance`

Pixel activity and keyframe speed now use Euclidean pixel travel rather than `max(x, y)`.
This removed the final mismatch between diagonal Planner geometry and encoded-video QA.

### CI failures were used as contract checks, not bypassed

The Golden/comfort sprint intentionally kept strict CI throughout.

Important failures and corrections:

1. Initial Golden/comfort integration exposed:
   - rushed REACT/INTERACT under per-leg measurement;
   - ultra-short Story-V2 settle precision;
   - one old QA mutation fixture that became unordered after the extra Golden checkpoint.
   These were fixed at Planner/Compiler level; the Story timing invariant was not weakened.

2. Run `36138126516`
   - Compile SUCCESS
   - Ruff SUCCESS
   - Pytest **1 failed, 346 passed, 12 warnings**
   - remaining failure: REACT exceeded comfort speed in the real V1.2 end-to-end encoded contract.
   Fix: bound scale from above using actual authored asset size.

3. Run `36138295840`
   - Compile SUCCESS
   - Ruff SUCCESS
   - Pytest **1 failed, 346 passed, 12 warnings**
   - remaining failure: after speed correction, the nominal perceptual floor was higher than the
     displacement physically allowed by the comfort ceiling.
   Fix: make floor and ceiling a satisfiable joint contract.

4. Run `36138534013`
   - Compile SUCCESS
   - Ruff SUCCESS
   - Pytest **1 failed, 347 passed, 12 warnings**
   - residual floor mismatch was caused by assuming a horizontal pixel projection.
   Fix: directional/asset-aware pixel budget.

5. Run `36138811759`
   - Compile SUCCESS
   - Ruff SUCCESS
   - Pytest **1 failed, 347 passed, 12 warnings**
   - final ~0.09px mismatch was caused by using Euclidean geometry for the budget but `max(x,y)`
     for measured movement.
   Fix: true Euclidean pixel travel for both activity and speed.

No threshold was arbitrarily relaxed to make CI green.

### Final integration CI

Behavior commit:
`6f88e218858069c8ae35143dd6a3c2a7ed7613a5`

Run:
`36138971899`

Result:
**SUCCESS**

- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **348 passed, 12 warnings in 8.58s**

### Final independent review

Review base:
`c545115ed6a97dc49348abb084b68d5b549d20ca`
(MONTAGE21 checkpoint)

Reviewed behavior head:
`6f88e218858069c8ae35143dd6a3c2a7ed7613a5`

Scope:
- 25 commits after MONTAGE21;
- production changes only in:
  - `app/motion/timing.py`
  - `app/motion/planner.py`
  - `app/motion/compiler.py`
  - `app/qa/rendered_motion.py`
  - `app/render/renderer.py`
- regression tests updated/added accordingly;
- Pass1 unchanged;
- Pass2 unchanged;
- no Pass3 / Layer3;
- Composition authority unchanged;
- Story/WhisperX timing authority unchanged;
- Text ownership unchanged;
- Final Package schema unchanged.

Reviewed invariants after this sprint:
1. Story still owns reveal, relation and handoff timing.
2. Composition still owns final resting geometry.
3. Golden Ratio shapes motion only inside legal Story windows.
4. Motion strength cannot force a speed above the comfort ceiling.
5. A short Story window reduces amplitude rather than increasing acceleration.
6. INTERACT/REACT/PAYOFF timing is never shortened merely to force an EXIT.
7. EXIT is omitted when a comfortable release cannot fit.
8. semantic event accents return exactly to Composition.
9. geometry-locked / compound visuals remain conservative.
10. collision QA from MONTAGE21 remains active.
11. encoded-video QA requires motion to be both readable and comfortable.
12. scene handoffs use smooth eased travel; blur remains explicit-only.
13. ultra-short V2 semantic timing remains exact.

No additional code-level blocker was found in the final review.

### Production render expectation

The next real Black-Hat render should now differ from the previously supplied weak render in two ways
at the same time:

**Stronger / more expressive**
- visible ENTRY path;
- clear source INTERACT;
- temporally overlapping target REACT;
- readable PAYOFF;
- real semantic EXIT where enough time exists;
- object-level handoff instead of blur-everywhere continuity.

**More comfortable / smoother**
- no tiny ultra-fast semantic snaps;
- no 0.18s forced exit behavior;
- no linear mechanical scene bridge;
- bounded keyframe-leg speed;
- Golden 61.8 / 38.2 pacing;
- short narration windows reduce amplitude instead of accelerating;
- scale emphasis is bounded relative to actual asset size.

State:
**MONTAGE22 is code/CI complete. The remaining acceptance gate is a fresh production render with the
same real Black-Hat Final Package + narration, followed by visual comparison against the previous
render and the reference videos.**


## MONTAGE23 FINAL-PACKAGE RELATION COVERAGE + ENCODED MOTION CONTRACT CHECKPOINT — 2026-09-25

Behavior HEAD before this documentation commit:
`974dbaa5398f2e692cdf3d7c2cd7ecb47d36ad06`
`[test] Lock cross-event relation execution ownership`

### Why this checkpoint was opened

A new real production render diagnostic from the same Black-Hat V1.2 Final Package failed after
MONTAGE22.

The package itself was not malformed:
- FinalPackageLoader accepted the exact ZIP;
- 40 scenes were present;
- Pass1 / Pass2 / Story / Composition completed;
- the failure occurred in semantic Motion / encoded Motion QA.

The diagnostic exposed three generic engine-contract gaps that could recur with future Final Packages:

1. some V1.2 relations had no relation-level `script_span` even though their source/target/result assets
   had exact authored spans;
2. some authored relations crossed semantic-event ownership boundaries, but Motion initially restricted
   an asset to phases belonging only to its own event;
3. encoded Motion QA could demand visible transform activity from an asset that Renderer intentionally
   geometry-locks, and ENTRY could be hidden by a later semantic segment starting at the same time.

The fixes below are package-agnostic and do not contain Black-Hat scene ids, nouns or timing literals.

### Relation timing fallback from authored participant spans

Commit:
`928503f173ee1c19aead8b55fb996180667a05e7`
`[story] Derive relation timing from authored asset spans`

V1.2 permits an authored relation without its own script span.

New rule:
- if relation.script_span exists, it remains authoritative;
- otherwise Story derives the smallest half-open authored envelope covering:
  - source asset span;
  - target asset span;
  - optional result asset span;
- source + target must both have valid authored spans;
- otherwise Story abstains rather than inventing timing.

No topic inference, NLP guessing or scene-specific fallback is used.

This restores real spoken timing for package-authored relations that were previously semantically known
but temporally inert.

### Cross-event authored relations execute without stealing event ownership

Commit:
`d6131b432b2c5fc2e1ded938e18ad81674c7af06`
`[motion] Execute authored relations across semantic events`

A semantic visual still owns its original event for ENTRY / establishment / result ownership.

However, if the Final Package explicitly names that visual as source or target of an authored relation
from another event, Motion may additionally execute only the cross-event relation phases:
- INTERACT for the authored source;
- REACT for the authored target.

Cross-event phases:
- are appended to the phase chain;
- cannot become the dominant assignment;
- cannot steal ENTRY ownership;
- cannot inject unrelated ESTABLISH / ADD / PAYOFF phases.

This is the minimum permission required to execute authored relation semantics across event boundaries.

### ENTRY and semantic phases can never hide each other

Commit:
`9bdabfe63dc3e0adfaff13395e09fc0dc51cce70`
`[motion] Preserve entry and relation timelines without overlap`

The production diagnostic showed a class of encoded failure where Motion metadata had an ENTRY, but
INTERACT / REACT began at the same instant and FFmpeg correctly preferred the later semantic segment,
making the encoded ENTRY appear static.

New invariant:
- later semantic motion on the same asset begins no earlier than the actual ENTRY end;
- if a short authored relation cannot fit both a decorative ENTRY and its semantic action:
  - semantic meaning wins;
  - ENTRY is omitted;
  - relation motion starts at the Story reveal boundary;
- the engine never retains a metadata-only ENTRY that is guaranteed to be hidden by another segment.

This eliminates the metadata-render disagreement instead of weakening encoded QA.

### Authored relation timing outranks event handoff clipping

Relation phases use their own spoken relation window as timing authority.

A cross-event INTERACT / REACT is no longer truncated merely because an event handoff boundary occurs
inside the authored relation phrase.

Rules:
- relation source can remain active through the authored relation span;
- target REACT is shifted to the target's legal reveal window when needed;
- target REACT can never begin before the relation source's Story activation;
- PAYOFF retains causal ordering and authored visibility constraints;
- no segment may exceed the authored relation end.

This preserves the actual visual sentence rather than slicing it at an unrelated event boundary.

### Geometry-lock render / QA contract aligned

Commit:
`fd1b9ad5c520e922c22e674e0d8fd4232914d0e3`
`[qa] Align encoded motion checks with render and comfort contracts`

Renderer intentionally suppresses translation and scaling when:
`render_constraints.geometry_lock == authored_footprint`

Previously RenderedMotionQA could still demand encoded transform activity from that same asset.

That was a direct contract contradiction.

Now:
- geometry-locked assets remain timing/visibility validated;
- encoded transform-activity checks are skipped for transforms Renderer intentionally suppresses;
- this is not a global QA bypass;
- normal movable assets still require real encoded motion evidence.

Encoded Motion evidence was also hardened:
- multiple evidence points are sampled instead of relying on one exact peak frame;
- ENTRY baseline is sampled from its actual start state;
- expected motion and comfort checks use the same normalized geometry contract as Planner.

### ENTRY speed contract hardened

Planner now limits the complete ENTRY program by actual per-leg normalized speed, including:
- translation;
- scale projected through actual authored asset extent.

If any keyframe leg exceeds the ENTRY comfort ceiling, the complete entry amplitude is reduced
proportionally.

This prevents a hidden fast scale/translation spike between individually safe keyframes.

### Missing executable relation timeline is now a hard pre-render failure

Commit:
`a15d6ba64faa31a41f0fd2a662b54df6e2ed5470`
`[qa] Fail when executable package relations lose motion timelines`

Pipeline integration:
`8227f75ac6e27e5738c549a944fdfd9fb2f1cec1`
`[pipeline] Gate authored relation coverage before render`

MotionInteractionQA now receives the complete Choreography plan.

For every executable relation whose authority is:
- FINAL_PACKAGE_ASSET_RELATION; or
- FINAL_PACKAGE_INTERACTION_TARGET

QA requires a represented INTERACT source timeline.

Missing coverage produces:
`MISSING_RELATION_TIMELINE`

This occurs before render.

Therefore the engine can no longer silently report a rich Final Package while rendering zero relation
timelines.

### First-beat semantic leakage also closed

Commit:
`8b89d4792c22850651657dd1f36b1cc066a9d6d2`
`[render] Never reveal first-beat carrier before Story timing`

Regression:
`424af75539137fc4be6432ca324bb037b0864d44`
`[test] Prevent first-beat semantic leakage before reveal`

The boundary-carrier recovery mechanism is never allowed to reveal a first-beat semantic visual before
Story timing.

This keeps continuity recovery from becoming a semantic early-reveal path.

### Regression coverage added

Key regressions:
- `b841294379782ef4ab4ba420b8d70e7f5fdbb094`
  `[test] Cover spanless V1.2 relation timing and motion coverage`
- `fb128f6ce654740cf1f7f50df13e5a880809a0ed`
  `[test] Cover geometry-locked encoded motion contract`
- `424af75539137fc4be6432ca324bb037b0864d44`
  `[test] Prevent first-beat semantic leakage before reveal`
- `974dbaa5398f2e692cdf3d7c2cd7ecb47d36ad06`
  `[test] Lock cross-event relation execution ownership`

The V1.2 package regression now explicitly:
1. removes relation-level script span;
2. derives timing from authored asset spans;
3. builds Story;
4. builds Choreography;
5. builds Motion;
6. validates MotionInteractionQA with Choreography coverage;
7. intentionally strips Motion segments;
8. proves QA fails with MISSING_RELATION_TIMELINE.

### Exact-package semantic audit

The same Black-Hat Final Package that triggered the diagnostic was audited against the new generic
contracts.

Package semantics:
- 15 authored relations;
- 15/15 relations gained Story timing;
- 14/14 executable relations produced Motion relation timelines;
- the remaining relation was descriptive/non-executable;
- MotionInteractionQA completed with 0 relation violations.

This audit used the package's authored semantic/script spans and deterministic timing alignment to
exercise package consumption independent of any topic-specific rule.

### CI behavior during the fix

An intermediate CI run:
`36147055557`

Compile and Ruff passed, but 3 old semantic-motion tests failed because their assertions represented
the superseded contract:
- required ENTRY even when a short PAYOFF correctly takes semantic priority;
- attempted to manufacture a non-overlap at a timestamp that still overlapped the now-correct
  full-phrase source INTERACT;
- treated the comfort ceiling as a mandatory amplitude target rather than a maximum.

The tests were corrected to validate the current invariants; no production QA threshold was weakened.

### Final CI

Behavior HEAD:
`974dbaa5398f2e692cdf3d7c2cd7ecb47d36ad06`

Run:
`36147220828`

Result:
**SUCCESS**

- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **354 passed, 12 warnings in 11.34s**

### Final production contract after MONTAGE23

1. Final Package relation semantics cannot silently disappear before Motion.
2. Relation-level script span is optional only when source+target authored asset spans can safely define
   the relation timing envelope.
3. Cross-event authored relation participants may execute only their explicit INTERACT / REACT roles.
4. Event ownership for ENTRY / establishment / result remains intact.
5. ENTRY and relation motion on one visual cannot temporally mask each other.
6. A short semantic window drops decorative ENTRY rather than hiding semantic action.
7. Authored relation timing outranks unrelated event handoff clipping.
8. REACT cannot precede the source's Story activation.
9. Geometry-locked visuals are never required to produce transforms that Renderer intentionally forbids.
10. Movable visuals still require encoded Motion evidence.
11. ENTRY speed is bounded on every keyframe leg.
12. First-beat recovery cannot reveal semantic visuals before Story timing.
13. Pass1 + Pass2 extraction architecture remains unchanged.
14. No Pass3 / Layer3 was introduced.
15. Composition remains the final geometry authority.
16. Story / WhisperX remains timing authority.
17. Final Package remains semantic authority.

### Next production gate

Pull the new `montage` HEAD after this checkpoint documentation commit and rerun the exact same
Black-Hat Final Package + narration.

The specific previous diagnostic class should not recur:
- spanless authored relations now execute;
- geometry-lock no longer creates false encoded-transform failures;
- ENTRY cannot be metadata-only because another semantic segment hides it;
- missing executable relations fail before expensive rendering instead of after semantic loss.

If the rerun produces another diagnostic, treat it as a new production gate and do not disable QA.

State:
**The diagnostic was converted into generic engine contracts and regressions. The same package now has
full executable relation coverage in the semantic audit, and the complete GitHub CI is green.**


## MONTAGE24 COLLISION-SAFE RELATION MOTION CHECKPOINT — 2026-09-25

Behavior HEAD before this documentation commit:
`af0f15435c5987f57cf7691b2d951ca95ec0e65d`
`[motion] Auto-fit relation amplitude to prevent collisions`

### Production diagnostic that opened this checkpoint

Diagnostic:
`HEXA-diagnostic-6384c59e.zip`

Job:
`6384c59e601a4caeab3a67669c812396`

Input Final Package:
`HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip`

Runtime commit:
`2f6cf68c735c1f15e5cea651a58b38f8054cfcc2`

The pipeline successfully completed:
- input;
- transcription;
- vision;
- Pass1: 157 authored assets / 40 scenes;
- Pass2: 179 assets (+22);
- Story: 40 beats;
- Text;
- Composition: 87 text cues.

Failure occurred at MotionInteractionQA before render.

Exact violation:
```
MOTION_CREATES_COLLISION
beat: beat-005
event: SCENE_005_EVENT_02
source: SCENE_005:asset-03
target: SCENE_005:asset-02
authored overlap: 0.000
animated overlap: 0.224
```

This was a real Motion-created collision, not a malformed Final Package and not a false-positive QA
failure.

### Root cause

MONTAGE21/22 intentionally raised INTERACT / REACT readability floors so relation motion would be
perceptually visible.

Collision QA was correctly added as a hard pre-render gate, but Planner still treated that gate only as
validation. In tight authored geometry, a strong source/target relation could therefore produce a
material overlap and stop the render instead of adapting its amplitude.

This failure class could recur with any Final Package whose Composition is valid but whose semantic
relation motion has less free spatial clearance.

### Generic architecture fix

New module:
`app/motion/collision.py`

Planner now performs relation-collision fitting immediately after producing the Motion cues for each
beat.

The fitter:
1. considers explicit INTERACT source + REACT target pairs;
2. ignores geometry-locked visuals because Renderer intentionally suppresses their transforms;
3. computes authored Composition overlap at identity;
4. only intervenes when the authored boxes were effectively separate;
5. samples the full simultaneous relation window, including real keyframe times;
6. measures the maximum animated overlap rather than one midpoint only;
7. if Motion creates an unsafe new overlap, performs binary search for the strongest safe common
   amplitude;
8. uniformly scales relation dx / dy / scale deltas;
9. preserves:
   - Story timing;
   - relation direction;
   - easing;
   - Golden 61.8 / 38.2 pacing;
   - semantic roles;
   - exact final Composition settle.

Planner target overlap is deliberately stricter than the QA hard-fail threshold, providing safety
margin.

### Collision priority versus readability floor

A relation may occasionally have so little authored free space that collision safety requires movement
below the normal perceptual floor.

In that case:
- collision safety outranks the ordinary readability floor;
- the segment is explicitly marked:
  - `collision_limited = true`
  - `collision_gain`
  - `collision_policy = preserve_authored_separation`
  - original/authored overlap diagnostics;
- RenderedMotionQA does NOT report `MOTION_BELOW_PERCEPTUAL_FLOOR` for that explicitly
  collision-limited segment;
- encoded activity is still required when the remaining expected movement is measurable;
- comfort-speed validation remains active.

This is not a broad QA bypass. Only Planner-proven collision-limited relation segments receive this
exception.

### QA remains a hard guard

MotionInteractionQA was NOT weakened.

Its collision measurement now uses the same full-window overlap model as Planner rather than checking
only the midpoint.

Therefore:
- normal pipeline => Planner auto-fits the collision and QA passes;
- if Planner fitting is bypassed/regresses => QA still produces `MOTION_CREATES_COLLISION`.

### Regression coverage

Regression 1:
close-but-authored-separated source/target boxes are given strong relation motion.

Expected:
- Planner marks relation motion collision-limited;
- gain remains < 1;
- MotionInteractionQA passes after fitting.

Regression 2:
the fitted programs are deliberately amplified again to simulate a Planner regression/bypass.

Expected:
- MotionInteractionQA still fails with `MOTION_CREATES_COLLISION`.

Regression 3:
an encoded collision-limited semantic segment is allowed below the normal readability floor but must
still produce real encoded movement.

This prevents future changes from solving collision failures by either disabling QA or silently making
metadata-only motion.

### Final CI

Behavior HEAD:
`af0f15435c5987f57cf7691b2d951ca95ec0e65d`

Run:
`36150918909`

Result:
**SUCCESS**

- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **356 passed, 12 warnings in 11.56s**

### Locked production invariant

After MONTAGE24:

**A valid Final Package with safe authored Composition should not fail merely because semantic Motion
creates a new relation collision. Planner must first reduce only the offending relation amplitude to
the strongest collision-safe value. QA remains responsible for catching any collision that escapes
that repair.**

This behavior is generic:
- no Black-Hat topic logic;
- no SCENE_005 hardcode;
- no asset-id hardcode;
- no package-specific timing;
- no Pass3 / Layer3;
- Pass1 + Pass2 unchanged;
- Composition remains final geometry authority;
- Story remains timing authority;
- Final Package remains semantic authority.

### Next production gate

Pull the new montage HEAD after this documentation commit and rerun the exact same Final Package +
narration.

The diagnostic class from job `6384c59e601a4caeab3a67669c812396` should now be automatically
repaired in Motion Planner rather than stopping the render.

If another diagnostic appears, keep QA strict and treat it as the next generic production contract to
close.


## MONTAGE25 WINDOWS-SAFE FFMPEG COMMAND TRANSPORT CHECKPOINT — 2026-09-25

Behavior HEAD before this documentation commit:
`115af7d72d74b60560cefdb78f12d30393ebd84f`
`[test] Guard Windows-safe FFmpeg filter scripts`

### Production diagnostic that opened this checkpoint

Diagnostic:
`HEXA-diagnostic-8aba2e6c.zip`

Job:
`8aba2e6c825246c18c27eeed0e3657ef`

Runtime commit:
`2f28e484197fce2d23186c6f9b44885ccbdc0588`

The exact Black-Hat Final Package completed:
- input;
- transcription;
- vision;
- Pass1: 157 authored assets / 40 scenes;
- Pass2: 179 assets (+22);
- Story: 40 beats;
- Text recovery;
- Composition: 87 text cues;
- Motion authoring QA:
  - 179 semantic sync anchors;
  - 0 conservative fallbacks;
  - 14 relation timelines;
  - 0 visual-layout violations;
  - 0 text-layout violations;
  - 0 short-motion violations.

The failure occurred only after render compilation began.

### Actual root cause

The diagnostic displayed:
`DependencyUnavailableError: ffmpeg is not available`

That message was incorrect.

The underlying Windows exception was:
```
FileNotFoundError: [WinError 206] The filename or extension is too long
```

FFmpeg was installed and detected correctly:
- FFmpeg 9.0.2 available;
- ffprobe available.

The real failure was Windows CreateProcess rejecting an oversized process command line.

Dense production scenes generate large FFmpeg `filter_complex` graphs containing:
- many asset overlays;
- per-segment x/y expressions;
- semantic Motion keyframes;
- scene-continuity transforms;
- text/ASS filtering.

Previously the complete graph was placed inline as:
```
-filter_complex "<very large graph>"
```

This can exceed Windows command-line limits even though FFmpeg itself can execute the graph.

This failure class is generic and can recur with any sufficiently dense Final Package.

### Generic renderer fix

Commit:
`f37c9b2552151b7e802c96a98d41881c63ce3a91`
`[render] Move complex filters out of Windows command line`

Renderer no longer places production filter graphs inline.

For every rendered beat segment:
1. the complete filter graph is written as UTF-8 to:
   `<segment-stem>-filter-complex.ffgraph`
2. FFmpeg receives:
   `-filter_complex_script <script-path>`
3. the process command contains only the small script filename rather than the complete graph.

This is used unconditionally, not only after a command becomes too long.

Benefits:
- Windows command length remains bounded independent of visual density;
- no retry after an expensive CreateProcess failure;
- identical behavior on Windows/Linux;
- the filter graph remains available in the workspace for diagnostics;
- thread safety is preserved because every beat target has a unique segment stem.

### Error classification corrected

The old renderer caught all `FileNotFoundError` exceptions and translated them to:
`DependencyUnavailableError("ffmpeg is not available")`

Windows can expose CreateProcess WinError 206 through that same exception hierarchy.

New behavior:
- `winerror == 206` => `StageFailedError` describing Windows process-command overflow;
- genuine executable-not-found => `DependencyUnavailableError`;
- other OSError cases retain their real OS error metadata.

Therefore a future process-launch problem cannot falsely tell the operator to reinstall FFmpeg when the
binary is already available.

### Regression coverage

Commit:
`115af7d72d74b60560cefdb78f12d30393ebd84f`
`[test] Guard Windows-safe FFmpeg filter scripts`

Regression 1 creates a filter graph larger than 48 KiB.

Required behavior:
- `-filter_complex` is absent from process args;
- `-filter_complex_script` is present;
- script bytes contain the complete graph;
- final process command remains below 2 KiB.

Regression 2 simulates:
`FileNotFoundError(winerror=206)`

Required behavior:
- renderer raises `StageFailedError`;
- error identifies Windows process limit;
- it is never reported as missing FFmpeg.

Existing FFmpeg integration tests also now execute through `-filter_complex_script`, proving that:
- normal visual filters remain valid;
- scene transitions remain valid;
- motion expressions remain valid;
- ASS/text filtering remains valid;
- final MP4 rendering still works.

### Final CI

Behavior HEAD:
`115af7d72d74b60560cefdb78f12d30393ebd84f`

Run:
`36152841146`

Result:
**SUCCESS**

- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **358 passed, 12 warnings in 8.75s**

### Locked production invariant

After MONTAGE25:

**Production FFmpeg filter complexity must not scale the Windows process command line. Filter graphs are
transported through files, so increasing scene density, semantic Motion complexity or text filtering
cannot reproduce WinError 206 through inline filter_complex growth.**

No Final Package-specific rule was added:
- no Black-Hat logic;
- no scene ids;
- no asset ids;
- no package-specific thresholds;
- Pass1 + Pass2 unchanged;
- no Pass3 / Layer3;
- Story remains timing authority;
- Composition remains final geometry authority;
- Final Package remains semantic authority.

### Next production gate

Pull the new montage HEAD after this documentation commit and rerun the exact same Final Package +
narration.

The diagnostic class from job `8aba2e6c825246c18c27eeed0e3657ef` should not recur regardless of
filter-graph size.


## MONTAGE26 FFMPEG CAPABILITY PREFLIGHT + REAL-RENDER CLOSURE GATE — 2026-09-25

Behavior HEAD before this documentation commit:
`8da84eb266ec3863eaab90e4f0b206463e4f486b`
`[test] Gate pipeline on early FFmpeg render preflight`

### Production diagnostic that opened this checkpoint

Diagnostic:
`HEXA-diagnostic-b99c42c3.zip`

Job:
`b99c42c311294de29e455a8805bd8722`

Runtime commit:
`d95f9f3d3227505ef1946473f1f20a8de9ce0cf2`

Environment:
- Windows 10;
- Python 3.11.9;
- FFmpeg 9.0.2 full build;
- NVIDIA GeForce 930MX;
- 4 CPU cores.

The pipeline successfully reached render after:
- Pass1: 157 authored assets / 40 scenes;
- Pass2: 179 assets (+22);
- Story: 40 beats;
- Composition: 87 text cues;
- Motion authoring QA:
  - 179 semantic sync anchors;
  - 14 relation timelines;
  - 0 visual-layout violations;
  - 0 text-layout violations;
  - 0 short-motion violations.

The failure was therefore renderer transport compatibility, not Final Package semantics, Motion QA,
Composition or extraction.

Exact FFmpeg stderr:
```
Unrecognized option 'filter_complex_script'.
Error splitting the argument list: Option not found
```

### Root cause

MONTAGE25 correctly moved large filter graphs out of the Windows process command line to prevent
WinError 206.

However it used the deprecated:
`-filter_complex_script <file>`

FFmpeg 9.0.2 in the operator environment no longer accepts that alias.

Current FFmpeg uses the generic file-option syntax:
`-/filter_complex <file>`

Meanwhile the Ubuntu CI environment uses FFmpeg 6.1.1, which does not understand the newer generic
file-option syntax and still requires the legacy alias.

Therefore hardcoding either spelling is not production-safe.

### Generic capability adapter

Behavior commits:
- `936fd43a0b6a64dd6b5468e568afb95f402e1570`
  `[render] Adapt complex-filter file syntax to FFmpeg capability`
- `85686563cb1b4c6a6d2da72c1bc2e04d62de5907`
  `[test] Cover FFmpeg filter-file capability adaptation`

Renderer now probes:
`ffmpeg -hide_banner -h full`

once per renderer instance.

Selection:
- if FFmpeg advertises `filter_complex_script` => use `-filter_complex_script`;
- otherwise => use `-/filter_complex`.

This is capability-driven rather than package-driven or OS-driven.

The filter graph is still always externalized to a UTF-8 `.ffgraph` file, so Windows command length
remains bounded regardless of:
- asset count;
- Pass2 density;
- relation count;
- Motion keyframe complexity;
- text/ASS filters;
- scene-continuity expressions.

### Fail-fast real render preflight

Behavior commits:
- `da499ca73e66af3ed88eeca3ed2da07bdbf02e6a`
  `[render] Add real FFmpeg preflight before expensive generation`
- `9ac00699ece41105e1aafe2dd8305f608e2e2ffa`
  `[pipeline] Fail fast on incompatible FFmpeg render path`
- `0970d2b50a0f576e7f64ac9ff852df6dbccdae2c`
  `[test] Require real renderer preflight encode`
- `8da84eb266ec3863eaab90e4f0b206463e4f486b`
  `[test] Gate pipeline on early FFmpeg render preflight`

Every generation job now performs a real two-frame H.264 encode before Final Package parsing,
transcription, vision or cutout work.

Preflight validates the actual production path:
- installed FFmpeg executable;
- supported filter-file option;
- external filter graph parsing;
- libx264 availability;
- CRF 18 encode path;
- yuv420p;
- 30fps;
- real non-empty MP4 output.

If this path is incompatible, the job fails immediately instead of spending several minutes in
transcription / vision / extraction before reaching Render.

Preflight artifact:
`<workspace>/preflight/ffmpeg-render-preflight.mp4`

### Quality-preservation contract

This diagnostic was fixed only by changing how the filter graph reaches FFmpeg.

No production visual/audio quality parameter was changed:
- codec remains libx264;
- CRF remains 18;
- pixel format remains yuv420p;
- fps remains 30;
- Motion data unchanged;
- Story timing unchanged;
- Composition geometry unchanged;
- text content/placement logic unchanged by this fix;
- Pass1 + Pass2 unchanged;
- no Pass3 / Layer3;
- no asset count reduction;
- no scene simplification;
- no QA threshold was weakened.

Regression:
`test_filter_file_transport_does_not_change_export_quality_contract`

locks:
- libx264;
- CRF 18;
- yuv420p;
- 30fps.

### Real encoded-render verification after CI

GitHub CI on behavior HEAD:
Run `36155844761`

Result:
**SUCCESS**
- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **363 passed, 12 warnings in 8.60s**
- tested source snapshot uploaded successfully.

The exact tested source snapshot was downloaded and independently exercised outside GitHub CI.

Local FFmpeg:
`7.1.5`

Real release smoke:
`FFmpegRenderer -> H.264 -> audio mux -> final-media QA`
=> PASS.

Dense real-package smoke:
- 12 actual PNG scene images from the uploaded corrected Black-Hat Final Package;
- 12 independent renderer inputs;
- real Composition grid;
- real reveal cues;
- one-second H.264 output;
- 640x360;
- yuv420p;
- 30fps.

Two renders were produced from the exact same RenderPlan:

A. adaptive capability selection:
`-filter_complex_script`

B. forced modern syntax:
`-/filter_complex`

Both outputs:
- H.264;
- 640x360;
- yuv420p;
- 30fps;
- 1.000 seconds;
- 43,090 bytes.

Both had the exact same SHA-256:
`0b524e82344d4cfa089c2101ed7818aab1d66e6d652c5b5c810ba7fc03731915`

Therefore filter transport changed neither encoded pixels nor export quality in this verification.

### Permanent production-bug closure protocol

From this checkpoint forward, a production diagnostic is not considered closed merely because code
compiles or unit tests pass.

For every reproducible production failure:

1. inspect the real diagnostic and identify the root-cause class;
2. implement a package-agnostic engine fix;
3. forbid scene ids, asset ids, topic nouns or package-specific timing hardcodes;
4. add a regression reproducing the failure class;
5. keep QA strict unless the QA contract itself is proven contradictory;
6. run full Compile + Ruff + Pytest CI;
7. run an actual encoded render smoke through FFmpeg;
8. for renderer/export failures, exercise a dense or representative real-media path when possible;
9. verify codec/fps/pixel-format/quality settings and semantic content were not reduced merely to pass QA;
10. only then record the checkpoint as production-ready.

If safety/geometry requires Motion adaptation, the engine must preserve the strongest safe motion and
record the limiting reason; it must not globally weaken Motion or lower QA thresholds.

State:
**The b99c42c3 FFmpeg-9 compatibility failure is closed generically, early render compatibility is now
tested by the product itself, and the fix was independently real-rendered without any export-quality
change.**


## CURRENT OFFICIAL HANDOFF STATE AFTER MONTAGE26 — 2026-09-25

Official branch:
`montage`

Behavior / implementation checkpoint:
`8da84eb266ec3863eaab90e4f0b206463e4f486b`
`[test] Gate pipeline on early FFmpeg render preflight`

MONTAGE26 documentation checkpoint:
`7e5300606d245b94984c81dbfc9d3eb83d6fac4a`
`[montage26] Record FFmpeg capability preflight and real-render gate`

Latest CI on the official documentation HEAD:
Run `36156609706`

Result:
**SUCCESS**
- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **363 passed, 12 warnings in 12.97s**
- tested source snapshot upload: SUCCESS

### What is finished

The following production failure classes are now closed by generic engine contracts and regressions:
- semantic segment crossing handoff deadlines;
- missing V1.2 executable relation coverage;
- spanless authored relations with valid participant spans;
- cross-event INTERACT / REACT execution ownership;
- ENTRY being hidden by a later semantic Motion segment;
- false encoded-motion failures for geometry-locked authored footprints;
- first-beat semantic leakage;
- Motion-created source/target collisions;
- Windows WinError 206 from oversized inline FFmpeg filter graphs;
- FFmpeg 6 versus FFmpeg 9 filter-file option incompatibility;
- late renderer compatibility failures after expensive transcription / vision / cutout work.

Motion remains:
- Golden-ratio shaped;
- comfort-speed bounded;
- collision-safe;
- semantic-timing controlled;
- Composition-settling for normal programs;
- terminal EXIT only where authored timing safely permits.

No quality reduction was used to make QA pass:
- libx264 unchanged;
- CRF 18 unchanged;
- yuv420p unchanged;
- 30fps unchanged;
- Pass1 + Pass2 unchanged;
- no Pass3 / Layer3;
- no global Motion weakening;
- no asset-count reduction;
- no scene simplification;
- no QA threshold suppression used as a shortcut.

### What is no longer pending

Do NOT wait for another code change before attempting the next production render.

MONTAGE26 has:
- green full CI;
- a real FFmpeg preflight integrated into every generation job;
- real encoded renderer smoke coverage;
- dense real-package renderer smoke using actual Black-Hat scene images;
- verified identical output hash between the two supported filter-file transports in the independent render check.

### What we are waiting for now

The only remaining production gate is an operator-side full rerender on the real Windows environment using:
- the exact corrected Black-Hat Final Package;
- the exact narration audio;
- the current `montage` HEAD;
- the operator's FFmpeg 9.0.2 environment.

The new pipeline must first run the real FFmpeg preflight. If that preflight fails, treat the diagnostic as a renderer-environment failure and do not spend time on the rest of the generation.

If preflight passes, complete the full render and inspect:
- ENTRY visibility;
- INTERACT / REACT / PAYOFF readability;
- EXIT smoothness;
- collision-safe relation motion;
- selective rather than pervasive blur;
- object-level continuity;
- text timing;
- no white flashes / ghosting / black frames;
- encoded quality;
- overall reference-video spirit.

### Required protocol for the next production bug

If the new full rerender produces any diagnostic:
1. inspect the exact new diagnostic;
2. do not assume it is an old failure;
3. identify the generic root-cause class;
4. do not hardcode package / scene / asset ids;
5. preserve quality and semantic intent;
6. add a regression;
7. run full CI;
8. run an actual encoded render smoke;
9. for renderer/export bugs, use representative or dense real-media input when possible;
10. only then record a new checkpoint.

### Immediate next action

Operator:
```bash
git checkout montage
git pull origin montage
git rev-parse HEAD
```

Expected current documentation checkpoint before this status commit:
`7e5300606d245b94984c81dbfc9d3eb83d6fac4a`

Then rerun the exact corrected Black-Hat Final Package + narration and return either:
- the completed MP4 for A/B perceptual review; or
- the new `HEXA-diagnostic-*.zip` if any new gate stops the run.

The next conversation must continue from this handoff and must not re-open already closed MONTAGE20-26 failures unless a new diagnostic proves a regression.


## MONTAGE27 FULL-PACKAGE RENDER GATE + SHARED SEMANTIC READABILITY CONTRACT — 2026-09-25

Behavior HEAD before this documentation commit:
`df2b094a92a4daba35cad9d3e9f2d93ac11e9576`
`[test] Keep encoded fixture inside shared floor and speed envelope`

### Production diagnostic that opened this checkpoint

Diagnostic:
`HEXA-diagnostic-ffa3e158.zip`

Job:
`ffa3e158b72b4604b26abf91f686ae04`

Runtime commit:
`7e5300606d245b94984c81dbfc9d3eb83d6fac4a`

Environment:
- Windows 10
- FFmpeg 9.0.2
- corrected Black-Hat V1.2 Final Package
- original ElevenLabs narration on operator machine

The production run completed all structural authoring stages:
- 40 scenes
- Pass1: 157 assets
- Pass2: 179 assets
- Story: 40 beats
- 87 text cues in production alignment
- 14 relation timelines
- 0 visual-layout violations
- 0 text-layout violations
- 0 short-motion violations

The render itself completed, but RenderedMotionQA stopped the job with exactly three REACT readability
violations:

- beat-027 / SCENE_027:asset-03: expected 24.10px, floor 24.96px
- beat-029 / SCENE_029:asset-03: expected 24.26px, floor 24.96px
- beat-037 / SCENE_037:asset-03: expected 24.17px, floor 24.96px

The differences were sub-pixel-scale at the threshold boundary, but the root cause was not treated as a
request to lower QA.

### Root cause: duplicated semantic readability authorities

MotionPlanner authors semantic INTERACT / REACT / PAYOFF amplitude in normalized Composition space.

RenderedMotionQA still had an independent pixel-space readability rule derived partly from output width.

On a 1920x1080 canvas, vertical/diagonal gestures and mixed translation+scale gestures can therefore
satisfy the Planner's exact Golden/comfort contract while the QA projects a slightly larger,
unreachable width-derived floor.

This was a contract mismatch:
- Planner authority: normalized Composition space;
- QA authority: a second pixel-derived semantic floor.

The same semantic quantity had two independent definitions.

### Partial diagnostic fix and why it was not enough

Commits:
- `9d8c392dff62c920a13854cd5584ece08f224f74`
  `[qa] Project comfort floor through dominant motion channel`
- `edc481431b2b7f002ff1dfe2f14e19b62aeacb30`
  `[test] Lock dominant-channel comfort projection`

This corrected one class of projection error by choosing the actual dominant visual channel rather than
the largest theoretical translation/scale projection.

CI:
Run `36159638149`
SUCCESS
- 365 passed
- 12 warnings

However, per the permanent production-bug protocol, CI was NOT treated as sufficient.

The exact corrected 40-scene Final Package was then rendered end-to-end in a full-package gate.

That gate reproduced the failure class again:
- beat-029 REACT
- beat-037 REACT

Therefore the partial projection fix was correctly rejected as incomplete.

### Final architecture fix: one semantic readability source of truth

New shared function:
`app.motion.timing.semantic_readability_floor(...)`

Commits:
- `ab062278c0262b53b5afa446207d62bbe47a473b`
  `[motion] Share semantic readability floor with QA`
- `a27504b98526bca0ab89a35747eefa966a6f7317`
  `[motion] Consume canonical semantic readability floor`
- `a212344561436d6fb76af0c8003220cb5617a4ae`
  `[qa] Validate semantic readability in Planner space`

For INTERACT / REACT / PAYOFF:
- Planner computes the semantic readability floor in normalized Composition units;
- QA uses the exact same function and units;
- the floor still includes:
  - phase-specific minimum readability;
  - asset-size floor;
  - Story-duration comfort gain;
  - Golden-minor return-leg speed ceiling;
- QA still verifies that the expected encoded semantic motion is above that shared floor;
- QA still verifies actual encoded frame activity;
- QA still enforces normalized comfort speed.

Pixel projection remains evidence for encoded visibility, not a second semantic-authoring policy.

No production motion amplitude was weakened by this fix.

### Regression coverage

Commit:
`539a64299899b05730ff355fb47ac4aac2b84356`
`[test] Reproduce full-HD vertical REACT floor contract`

Regressions include:
- shared REACT floor equals the same reachable comfort budget used by Planner;
- real FFmpeg render of a vertical REACT at the shared floor;
- encoded QA must accept valid motion at the canonical floor;
- weak semantic motion still fails;
- metadata-only motion still fails encoded-activity verification.

Existing encoded test fixtures were updated only to remain valid examples inside the same readability +
comfort-speed envelope.

Final fixture commit:
`df2b094a92a4daba35cad9d3e9f2d93ac11e9576`
`[test] Keep encoded fixture inside shared floor and speed envelope`

No production threshold was weakened to make tests pass.

### Final CI

Run:
`36161095670`

Result:
**SUCCESS**

- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **367 passed, 12 warnings in 13.97s**
- tested source snapshot uploaded successfully

Tested-source artifact:
`hexa-storyengine-source-fce82ab71d4f35dc454cdc6056a84d6076ed493a`

The full-package production gate below used the exact tested source snapshot from this CI run, not a
different working tree.

### Full corrected-Black-Hat package gate

The exact conversation package used:
`HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED(1).zip`

Because the original standalone ElevenLabs MP3 was not available as a separate file in the current
sandbox, the narration audio track was extracted from the prior real Black-Hat render:
`HEXA_BLACK_HAT_HACKER_AR.mp4`

Extracted narration duration:
approximately 97.097s.

Important limitation:
- sandbox did not have production WhisperX / multilingual E5 models;
- the gate explicitly used the controlled alignment/semantic fallback mode;
- therefore this gate proves engine/package/render/QA integrity, not byte-identical production timing
  parity with the operator's Windows WhisperX/E5 run;
- the operator-side exact original MP3 + production models remains the final parity gate.

The full gate ran the real product path:
- FFmpeg preflight
- FinalPackageLoader
- Vision
- Pass1
- Pass2
- Story
- Choreography
- Text planner
- Composition
- Motion
- MotionInteractionQA
- StorySyncQA
- Authoring QA
- RenderPlan
- 40-scene FFmpeg render
- RenderedMotionQA
- audio mux
- final recovery
- rendered visual QA

Observed full-gate semantics:
- 40 beats
- 179 semantic sync anchors
- 0 conservative fallbacks
- 15 authored relationships represented
- 14 executable relation timelines
- 55/55 authored semantic events represented
- 0 missing semantic events
- 0 visual-layout violations
- 0 text-layout violations
- 0 short-motion violations

One non-blocking asset-requirement warning remained for a composite/compound semantic requirement:
`SCENE_038_A02_broken_account_lock:RESULT:COMPARE`

This does not represent dropped event/relation semantics:
- all 15 relationships are represented;
- all 55 semantic events are represented;
- package cardinality remains ZERO_OR_ONE_OR_MANY;
- no forbidden Pass3 / Layer3 was introduced merely to manufacture an extra independent cutout.

### Full-package encoded QA result

RenderedMotionQA:
```json
{
  "ok": true,
  "checked_segments": 110,
  "skipped_static_segments": 7,
  "violations": []
}
```

MotionInteractionQA:
```json
{
  "ok": true,
  "checked_segments": 117,
  "checked_relations": 14,
  "violations": []
}
```

SceneContinuityQA:
```json
{
  "ok": true,
  "checked_boundaries": 39,
  "bridged_boundaries": 39,
  "blur_boundaries": 0,
  "violations": []
}
```

The previous ffa3e158 REACT readability class did NOT recur.

### Final encoded file verification

Full-gate output:
`black-hat-full-package-gate.mp4`

SHA-256:
`fc164ff27cfa27d655a241042dc336e30a1f35eab916592254b29fa8711581e2`

Full decode through FFmpeg:
PASS with no decode errors.

ffprobe:
- video codec: H.264
- resolution: 1920x1080
- pixel format: yuv420p
- frame rate: 30/1
- audio codec: AAC
- sample rate: 44.1 kHz
- channels: mono
- duration: 97.100s
- file size: 22,409,008 bytes

Rendered visual contact sheet was generated successfully.

### Quality-preservation proof

This diagnostic was NOT fixed by reducing video quality or weakening production Motion.

Unchanged:
- output resolution 1920x1080;
- H.264 export;
- CRF 18 encoder contract;
- yuv420p;
- 30fps;
- Story timing ownership;
- Composition final geometry;
- Pass1 + Pass2;
- no Pass3 / Layer3;
- no asset-count reduction;
- no scene simplification;
- no global Motion amplitude reduction;
- no relation deletion;
- no blur substitution;
- no global QA bypass.

The fix removes a duplicate semantic threshold and makes Planner + QA use the same authoring contract.

Encoded QA remains strict about:
- actual encoded movement;
- motion speed;
- geometry-lock rules;
- collision-limited exceptions;
- metadata-only motion;
- relation coverage.

### Mandatory production-bug closure protocol — strengthened

From MONTAGE27 forward, a reproducible production bug is NOT closed by unit tests or CI alone.

Required closure sequence:
1. inspect the real production diagnostic;
2. identify the generic root-cause class;
3. implement a package-agnostic fix;
4. prohibit scene-id / asset-id / topic hardcodes;
5. add regression coverage;
6. run Compile + Ruff + full Pytest;
7. use the exact CI-tested source snapshot;
8. if the failing Final Package is available, run that full package end-to-end;
9. reach the exact stage that previously failed and prove it passes;
10. finish final mux and media QA where the environment permits;
11. verify export specs and quality contracts are unchanged;
12. only then document the bug as closed.

If the exact production ML stack is not available in the validation environment, the handoff must state
that limitation explicitly and keep the operator-side production parity rerender as the final gate.

### Current production status

The engine-level failure from diagnostic `ffa3e158` is closed by:
- one shared semantic readability contract;
- 367-test green CI;
- a full 40-scene corrected-Black-Hat render using the exact CI-tested source snapshot;
- 110 encoded semantic segments checked with zero violations;
- successful final mux and decode;
- unchanged export-quality settings.

Remaining parity gate:
rerun the exact corrected Black-Hat Final Package on the operator Windows environment with:
- original ElevenLabs MP3;
- production WhisperX alignment;
- production semantic model;
- FFmpeg 9.0.2.

Any new diagnostic after that run must be treated as a NEW production gate, not assumed to be one of the
already-closed MONTAGE20-27 classes.


## CURRENT OFFICIAL HANDOFF STATE AFTER MONTAGE27 — 2026-09-25

Official branch:
`montage`

Current documentation HEAD before this status commit:
`a5356655eab1392801316b1ea08c6e69a37204d4`
`[montage27] Record full-package render gate and shared readability contract`

Latest CI on that HEAD:
Run `36162207556`

Result:
**SUCCESS**
- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **367 passed, 12 warnings in 13.22s**
- tested source snapshot upload: SUCCESS

### What is complete

MONTAGE20-27 production failure classes are closed generically, including:
- semantic segment / handoff timing;
- V1.2 relation coverage;
- spanless relation timing fallback;
- cross-event INTERACT / REACT ownership;
- ENTRY masking by later semantic motion;
- geometry-lock versus encoded-motion QA mismatch;
- first-beat semantic leakage;
- Motion-created relation collision auto-fit;
- Windows WinError 206 from inline filter-complex growth;
- FFmpeg filter-file transport compatibility / preflight;
- duplicated Planner-versus-QA semantic readability floors.

The latest ffa3e158 failure class is closed by one shared semantic readability contract.

### Full-package proof already completed

The exact corrected Black-Hat Final Package was run through a full 40-scene gate using the exact CI-tested
source snapshot.

Observed full-gate semantics:
- 40 beats
- 179 semantic sync anchors
- 0 conservative fallbacks
- 15 authored relations represented
- 14 executable relation timelines
- 55 / 55 semantic events represented
- 0 missing semantic events
- 0 visual-layout violations
- 0 text-layout violations
- 0 short-motion violations

MotionInteractionQA:
- 117 checked segments
- 14 checked relations
- 0 violations

RenderedMotionQA:
- 110 checked semantic segments
- 7 intentionally skipped static/locked segments
- 0 violations

SceneContinuityQA:
- 39 boundaries
- 39 bridged
- 0 blur boundaries
- 0 violations

Full encoded output:
- H.264
- 1920x1080
- yuv420p
- 30fps
- AAC mono 44.1 kHz
- duration approximately 97.1s
- full FFmpeg decode PASS

### Quality contract is still locked

No bug fix may reduce output quality or weaken visual semantics merely to satisfy QA.

Locked:
- libx264
- CRF 18
- yuv420p
- 30fps
- 1920x1080 production output
- Story / WhisperX timing authority
- Composition final geometry authority
- Final Package semantic authority
- Pass1 + Pass2 only
- no Pass3 / Layer3
- no global Motion weakening
- no asset-count reduction
- no scene simplification
- no relation deletion
- no global QA bypass

Any future QA/Planner disagreement must be resolved by one shared production contract, not by lowering
quality or suppressing the validator.

### Permanent production-bug closure protocol

A new production bug is not considered closed by code review, unit tests or CI alone.

For every reproducible production failure:
1. inspect the exact real diagnostic;
2. identify the generic root-cause class;
3. implement a package-agnostic fix;
4. prohibit topic / scene / asset hardcodes;
5. preserve output quality and semantic intent;
6. add a regression reproducing the exact failure class;
7. run Compile + Ruff + full Pytest;
8. use the exact CI-tested source snapshot;
9. run an actual encoded render;
10. if the failing Final Package is available, run that full package end-to-end;
11. reach and pass the exact stage that previously failed;
12. verify final mux, decode and output specs;
13. only then document the bug as closed.

### Known validation-environment limitation

The full sandbox gate did not have the exact production WhisperX / multilingual E5 stack nor the
standalone original ElevenLabs MP3.

For the full gate, narration audio was recovered from the prior real Black-Hat render and controlled
alignment / semantic fallback was used.

Therefore engine/package/render/QA integrity is proven, but exact operator-side production parity with
the original MP3 + production WhisperX/E5 remains the final external gate.

### What we are waiting for now

No known code fix is currently pending.

The next required action is the operator-side Windows rerender using:
- current `montage` HEAD;
- exact corrected Black-Hat Final Package;
- exact original ElevenLabs narration MP3;
- production WhisperX alignment;
- production semantic model;
- FFmpeg 9.0.2.

Expected result:
- pipeline completes;
- final MP4 is produced;
- then perform A/B perceptual review versus previous render and reference videos.

If a new diagnostic appears, it must be treated as a NEW production gate. Do not reopen a previously
closed MONTAGE20-27 issue unless the new diagnostic proves a regression.

### Immediate next conversation protocol

At the start of the next conversation:
1. read `HEXA_PROJECT_CONTINUITY_SOURCE.md` from branch `montage`;
2. verify live `refs/heads/montage`;
3. verify latest CI live;
4. do not rely on a remembered SHA if the branch has moved;
5. if the user sends a new diagnostic, inspect that exact file first;
6. if the user sends a completed MP4, perform the full perceptual A/B review:
   - Entry strength and smoothness;
   - INTERACT / REACT / PAYOFF readability;
   - EXIT quality;
   - Golden-ratio pacing;
   - focus hierarchy;
   - relation continuity;
   - selective blur;
   - text timing;
   - collision safety;
   - ghost / flash / black-frame checks;
   - reference-video spirit.

State:
**MONTAGE27 is the current stable engine checkpoint. No known code blocker remains. We are waiting for
the exact operator-side Windows production rerender or its next diagnostic.**


## MONTAGE28 AUTHORED RELATION COMPLETENESS GATE — 2026-09-25

Development branch:
`montage`

Behavior HEAD before this documentation commit:
`9bdca4bfde5da542367bb501c8fec582e068f32e`
`[test] Encode Gray-Hat relation completeness regression`

### Production diagnostic

Diagnostic:
`HEXA-diagnostic-10f16ca6.zip`

Job:
`10f16ca6a86e437ab56c5836f9ae705d`

Runtime source:
`ead2900e0a157c1dd23383764b0cbe73c8d85462`

Production input reported by the diagnostic:
`HEXA_GRAY_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip`

The production run reached Motion after:
- 35 scenes;
- Pass1: 127 assets;
- Pass2: 153 assets (+26);
- Story: 35 beats;
- Composition: 75 text cues;
- Final Package geometry locked successfully.

MotionInteractionQA then stopped generation with six authored-relation completeness violations:
- one `MISSING_RELATION_TIMELINE`;
- one `MISSING_TARGET_REACTION`;
- four `MISSING_RESULT_PAYOFF` violations.

This was NOT the MONTAGE27 semantic-readability failure and was NOT an FFmpeg/export failure.

### Root-cause class

The failure exposed a remaining duplicate/incomplete authority for authored relation execution.

Before MONTAGE28:
- MotionInteractionQA treated an executable authored relation with a distinct target as requiring a visible REACT phase except for intentionally balanced/non-causal actions such as COMPARE/LOOP;
- Choreography used a narrower condition based on `requires_state_change` / transition metadata, so a valid authored target could be omitted from REACT;
- an explicit `result_asset_id` did not by itself guarantee PAYOFF if the package omitted a redundant RESULT event role;
- relation-level timing could still be absent for valid Pass2-bound source/target cutouts even though Story already owned spoken windows for the bound participants.

Therefore different valid Final Packages could expose different omissions even though the authored relation itself was executable.

### Generic architecture fix

A canonical relation execution contract now exists in:
`app/choreography/relation_contract.py`

Rules:
- executable authored relation + distinct target => visible REACT by default;
- COMPARE/LOOP remain non-automatic reactions unless an authored target state transition explicitly requires reaction;
- Choreography and MotionInteractionQA consume the same reaction contract.

Event-flow completeness:
- explicit relation result authority can synthesize the required PAYOFF even when the package does not redundantly mark the asset with a RESULT event role;
- if the result asset belongs to a different Story semantic event, PAYOFF stays in that result asset's Story-owned event instead of stealing source-event timing;
- relation metadata remains attached to the generated PAYOFF.

Spanless relation timing:
- if an executable INTERACT/REACT relation has no usable relation-level spoken span, Motion may derive an envelope only from Story-owned spoken windows of the bound source/target participants;
- Motion does not invent timestamps and does not move relation semantics outside Story/beat timing;
- very short explicit relation spans may only be extended through that same Story-owned participant evidence.

No package/topic/scene/asset hardcodes were added to production code.

### Regression coverage

New regressions cover:
- executable target REACT without redundant `requires_state_change`;
- explicit result PAYOFF without redundant RESULT role;
- result asset owned by a different semantic event;
- Pass2-style relation with no relation-level spoken span;
- V1.2 loader -> Story -> Choreography -> Motion -> MotionInteractionQA integration for the production failure class;
- real FFmpeg encoded motion QA for the same relation-completeness class.

### Final CI

Current behavior HEAD:
`9bdca4bfde5da542367bb501c8fec582e068f32e`

V2 CI:
Run `36167480737`

Result:
**SUCCESS**
- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **372 passed, 12 warnings in 14.10s**
- tested source snapshot upload: SUCCESS

Tested-source artifact:
`hexa-storyengine-source-9c0dedfe7d186a48bdfee338be586ba6a11665e3`

Artifact digest:
`sha256:37507961512c55f84c5071b53298732d131d49e81a4bccabc80843e7a3a023a5`

### Exact CI-tested encoded gate

The exact source artifact uploaded by Run `36167480737` was downloaded and used for an independent encoded gate representing the same failure class.

Observed semantic execution:
- source: ENTRY + INTERACT;
- target: ENTRY + REACT;
- result: ENTRY + PAYOFF.

MotionInteractionQA:
- ok = true;
- checked segments = 6;
- checked relations = 1;
- violations = 0.

RenderedMotionQA:
- ok = true;
- checked segments = 6;
- skipped static segments = 0;
- violations = 0.

Encoded output:
- H.264;
- 1920x1080;
- yuv420p;
- 30 fps;
- duration 2.000 s;
- full FFmpeg decode PASS;
- SHA-256:
  `2ebacd06a6c7909d93dadddd5ba91ddd7d3a7de3e61fe26b024044eb845e787`.

This gate proves the fixed relation contract reaches real encoded pixels rather than only satisfying metadata QA.

### Protected quality / architecture contract

Unchanged:
- Final Package semantic authority;
- Story / WhisperX timing authority;
- Composition final geometry authority;
- Pass1 + Pass2 only;
- no Pass3 / Layer3;
- no extraction changes;
- no scene/asset deletion;
- no relation deletion;
- no global Motion weakening;
- no QA bypass;
- production 1920x1080 / libx264 / CRF 18 / yuv420p / 30fps contract remains protected.

### Closure status

Engine-level fix:
**VALIDATED**

Exact production-package closure:
**PENDING OPERATOR RERENDER**

The diagnostic archive does not contain the raw corrected Gray-Hat Final Package ZIP or its narration audio, so the exact 35-scene production package could not be rerun in this validation environment.

The previous corrected Black-Hat Final Package ZIP is also not currently available in the accessible conversation/library files, so a new post-MONTAGE28 full Black-Hat package render was not claimed.

Therefore:
- do NOT report diagnostic `10f16ca6` as fully production-closed yet;
- next operator action is to rerun the exact Gray-Hat Final Package + original narration on Windows using the current live `montage` HEAD;
- if it passes Motion and completes encoded QA, then mark this production gate CLOSED;
- if a new diagnostic appears, inspect that exact diagnostic as a new production gate;
- do not change the Final Package merely to satisfy Motion;
- do not reopen MONTAGE27 readability fixes unless a new diagnostic proves a regression.



## CURRENT OFFICIAL HANDOFF STATE AFTER MONTAGE28 — 2026-09-25

Official branch:
`montage`

Current behavior HEAD:
`9bdca4bfde5da542367bb501c8fec582e068f32e`
`[test] Encode Gray-Hat relation completeness regression`

Current documentation HEAD before this status commit:
`8ad3cf42c1d506ffa5172c59b48236c6279a684e`
`[continuity] Record MONTAGE28 relation completeness gate`

### CI proof

Behavior-head CI:
Run `36167480737` — SUCCESS
- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: 372 passed, 12 warnings in 14.10s
- tested source snapshot upload: SUCCESS

Documentation-head CI:
Run `36168094299` — SUCCESS
- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: 372 passed, 12 warnings in 13.63s
- tested source snapshot upload: SUCCESS

### Diagnostic archive content verification

The exact uploaded diagnostic `HEXA-diagnostic-10f16ca6.zip` was inspected again.

It contains only:
- `report.json`
- `report.md`
- `recovery-events.json`
- `workspace-manifest.json`

It does NOT contain the raw Gray-Hat Final Package ZIP, narration MP3, package scene images, extracted assets, or the generation workspace bytes.

The workspace manifest proves those files existed on the operator machine during the failed run, including the normalized package directory and all 35 scene images, but only filenames/sizes are present in the diagnostic archive. The bytes are not recoverable from the diagnostic alone.

Therefore exact 35-scene post-fix Gray-Hat rerender still requires the operator-side original package + narration.

### Current MONTAGE28 state

Validated:
- generic authored-relation completeness fix;
- shared Choreography/QA target-reaction contract;
- explicit relation result -> PAYOFF coverage without redundant RESULT role;
- cross-event result ownership;
- Story-owned fallback timing for valid spanless source/target relations;
- full green CI;
- real FFmpeg encoded regression from exact CI-tested source;
- no extraction, Composition geometry, global Motion-strength, export-quality, or QA weakening.

Still pending:
- rerun the exact corrected Gray-Hat package with its original narration on the production Windows environment;
- verify that the original six violations do not recur;
- complete final encoded render/QA;
- only then mark diagnostic `10f16ca6` fully CLOSED.

No further production-code change is justified until that exact rerender or a new diagnostic provides new evidence.


## MONTAGE29 REFERENCE CHOREOGRAPHY PROFESSIONALIZATION CHECKPOINT — 2026-09-25

Official development branch:
`montage`

Current live behavior/documentation base before this handoff commit:
`3c667d73e2c050f4c7047e9de8972ce134ec5df6`
`[transport] Restore paginated source newlines`

Primary quality behavior commit:
`d1000edd997c709a5ffa7f13e734a892bcc18879`
`[motion] Complete reference choreography and semantic focus hardening`

The two commits above `d1000...` only restored comments/newline transport after connector pagination.
AST comparison of all ten changed production Python files between the CI-tested/rendered `d1000...`
artifact and current live `3c667d...` is **identical for every file**. No runtime behavior changed.

### Objective

This phase was not a render-unblocking patch. Its purpose was to move HEXA-StoryEngine from
"technically moving correctly" toward the pacing, focus hierarchy, interaction grammar, and visual
breathing of the accepted reference-video family while remaining generic across Final Packages.

Reference videos were treated as one visual-editing grammar rather than copied scene-by-scene.

### Sprint 1 — cross-beat pacing / rhythm

Implemented a reference rhythm policy that:
- keeps the existing narration/Story timing authority;
- smooths isolated pace whiplash between adjacent beats;
- preserves deliberate authored hook/re-hook contrast;
- constrains pacing to a small stable tier set instead of letting each beat feel unrelated;
- keeps Golden-ratio timing as an actual motion relationship, not decorative metadata.

No global slowdown was introduced.

### Sprint 2 — readable holds and focus arbitration

Implemented semantic attention cohorts:
- overlapping visuals compete for one dominant Hero/focus leader;
- participants/support assets receive bounded secondary emphasis;
- context assets become quieter;
- sequential authored semantic events retain independent full focus even when windows touch;
- dense scenes with many assets remain supported without asset deletion;
- text motion consumes the same visual focus hierarchy so labels do not fight the Hero.

This directly targets the prior "everything moves with similar importance" failure.

### Sprint 3 — remove micro-motion duplication

Explicit semantic timelines now separate appearance from semantic action:
- ENTRY is a clean arrival;
- INTERACT / REACT / PAYOFF execute in their own authored phases;
- the same interaction is not hidden inside ENTRY and then repeated as a second pulse;
- fallback-only flows may still express semantics inside ENTRY when no precise Story/event timing exists.

This removes a major source of nervous double-hits.

### Sprint 4 — interaction / reaction / payoff grammar

The relation grammar is now stricter and causal:
- SOURCE owns INTERACT;
- TARGET owns REACT;
- RESULT owns PAYOFF;
- a distinct result does not automatically receive both REACT and PAYOFF;
- general relation participants do not receive accidental PAYOFF;
- relation-level result authority is explicit only;
- an event RESULT is never borrowed to fabricate a causal relation result;
- REACT/PAYOFF cannot execute before the causal source exists;
- trusted PAYOFF remains readable through its Story-owned peak/settle even if the next semantic event
  begins concurrently.

The visual order is therefore cause -> reaction -> consequence instead of "several things move."

### Sprint 5 — Golden semantic peaks and compound Final Package semantics

The first precise semantic accent is shaped around Story's `semantic_peak` using a Golden-ratio
outbound/return window.

If decorative ENTRY would collide with the semantic peak:
- ENTRY is shortened when a readable arrival still fits;
- otherwise ENTRY is removed and semantic meaning wins;
- Motion never invents a new spoken timestamp.

For meaningful Final Package children that correctly remain inside a compound parent after Pass1/Pass2,
Story now has a dedicated `SemanticEventProxy` channel:
- no Pass3 / Layer3;
- no manufactured cutout;
- no duplicate AssetActivation for one rendered asset;
- the existing parent cutout receives one role-aware refocus/pulse at the child event time;
- role precedence prevents duplicate ESTABLISH+PAYOFF or REACT+PAYOFF hits.

White-Hat real-package proof:
- 4 previously unrepresented compound child events now execute as real parent focus pulses;
- StorySyncQA explicitly validates those proxy pulses rather than counting metadata only;
- proxy max peak delta: **42.971 ms**, inside the 50 ms semantic sync contract.

### Sprint 6 — encoded QA hardening and performance

RenderedMotionQA now covers:
- ENTRY
- ESTABLISH
- ADD
- INTERACT
- REACT
- PAYOFF
- EXIT

Acceptance thresholds were not weakened.

The encoded evidence path was changed from repeated H.264 random seeking to:
- collect exact frame requests first;
- decode the video once in frame order;
- retrieve only requested frames;
- keep a bounded working cache.

This keeps the same frames, ROIs, readability floors, speed limits, and encoded-activity thresholds while
making dense full-package QA production-usable.

On the final Black-Hat gate, RenderedMotionQA completed in approximately **3.45 s** while checking
170 segments.

### Reference-family perceptual measurements

Same 10 fps luma-difference analysis, current full Black-Hat render versus previous Black-Hat render and
the three reference videos treated as one family:

- mean visual change:
  - previous: **8.797**
  - current: **7.057**
  - reference-family mean: **5.391**
- strong-motion share (>8 luma-delta):
  - previous: **32.474%**
  - current: **24.433%**
  - reference-family mean: **24.467%**
- median readable hold:
  - previous: **0.25 s**
  - current: **0.30 s**
  - reference-family mean: **0.333 s**
- raw luma jerk mean:
  - previous: **6.944**
  - current: **6.301**
  - reference-family mean: **2.343**

Interpretation:
- global motion strength is now essentially on the reference family distribution;
- holds and breathing space moved materially toward the references;
- average visual activity decreased without globally weakening semantic actions;
- raw pixel jerk remains higher than the references because this package has dense opaque cutout reveals,
  40 scene changes, and different artwork/cut density. This metric is retained as perceptual evidence and
  is NOT "fixed" by adding blanket blur or weakening Motion.

The professional baseline therefore targets reference choreography/focus/rhythm, not pixel-statistical
cloning of unrelated reference artwork.

### Final CI

Current live HEAD:
`3c667d73e2c050f4c7047e9de8972ce134ec5df6`

V2 CI:
Run `36186574627`

Result:
**SUCCESS**
- Compile: SUCCESS
- Ruff: SUCCESS
- Pytest: **389 passed, 12 warnings in 10.61 s**
- tested source snapshot upload: SUCCESS

Current tested-source artifact:
`hexa-storyengine-source-d083ba30b4955d23d86cfb2321cb41b3a7dba642`

Artifact digest:
`sha256:6927a04b67cdd87f53cd4c63daf7de966906fbdc4bc88ded2683f42f4d2c37a8`

The behavior commit `d1000...` also passed full CI:
Run `36186274369`
- 389 passed, 12 warnings
- source artifact digest:
  `sha256:c593ae138239b8f60c9b129344899eb6d59e685efc383a5836e35ee14b4f2489`

### Exact CI-tested Black-Hat full-package gate

Source:
exact tested artifact from behavior commit `d1000...`.

Package:
`HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip`

Validation timing limitation:
sandbox production WhisperX/E5 and standalone original ElevenLabs MP3 were unavailable, so controlled
alignment / recovered narration carrier was used. This proves engine/package/render/QA integrity, not exact
Windows ML-timing parity.

Result:
- 40 / 40 scene segments frame-count verified;
- 179 Story sync anchors;
- 55 / 55 authored semantic events represented;
- 15 / 15 explicit relationships represented;
- 14 executable relation timelines;
- MotionInteractionQA: 77 checked segments / 14 relations / 0 violations;
- ChoreographyRhythmQA: 40 beats / 14 entry cohorts / 0 violations;
- SceneContinuityQA: 39 / 39 boundaries bridged / 0 blur boundaries / 0 violations;
- visual/text/short-motion authoring violations: 0;
- RenderedMotionQA: **170 checked / 26 intentional static skips / 0 violations**;
- RenderedMotionQA runtime: approximately **3.45 s**;
- final video: H.264, 1920x1080, yuv420p, 30fps;
- audio: AAC mono 44.1 kHz;
- duration: **97.0667 s**;
- full FFmpeg decode: PASS;
- SHA-256:
  `2814cb9f5d0a1e53c9cee6d42598119a6f9db56bc05f21bb501ecb84cc159e68`.

This hash is identical to the final local pre-push gate, proving deterministic behavior across the reconciled
source and exact CI-tested source.

### Exact CI-tested White-Hat full-package gate

Package:
`HEXA_WHITE_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED_SEMANTIC_PROGRESSION_FIXED.zip`

Same validation timing limitation applies; controlled timing carrier was used, not a production WhisperX/E5
parity claim.

Result:
- 35 / 35 scene segments frame-count verified;
- 137 Story sync anchors;
- 51 / 51 authored semantic events represented;
- 4 compound child semantic proxies explicitly executed and StorySync-validated;
- proxy max timing delta: **42.971 ms**;
- MotionInteractionQA: 78 checked segments / 11 relations / 0 violations;
- ChoreographyRhythmQA: 35 beats / 7 entry cohorts / 0 violations;
- SceneContinuityQA: 34 / 34 boundaries bridged / 0 blur boundaries / 0 violations;
- visual/text/short-motion authoring violations: 0;
- RenderedMotionQA: **146 checked / 15 intentional static skips / 0 violations**;
- final video: H.264, 1920x1080, yuv420p, 30fps;
- audio: AAC mono 44.1 kHz;
- duration: **97.0667 s**;
- full FFmpeg decode: PASS;
- SHA-256:
  `7f628c1b5443431336db2f00d07afe4733cdd849f00142b1f38ca9558452c271`.

The White package still emits a non-blocking choreography asset-requirement warning for abstract
`UNIT_001/UNIT_002` scene-level semantic entities that do not map one-to-one to independent cutouts.
This is not semantic-event loss:
- all 51 authored semantic events are represented;
- all reported explicit relationships are represented;
- child intents that lack independent cutouts execute through explicit parent proxies;
- no extraction change is permitted merely to silence this diagnostic warning.

### Quality and architecture locks preserved

Unchanged:
- Final Package semantic authority;
- Story / WhisperX timing authority;
- Composition final geometry authority;
- Pass1 + Pass2 only;
- no Pass3 / Layer3;
- no extraction changes;
- no asset deletion to satisfy QA;
- no relation deletion;
- no global Motion weakening;
- no global QA bypass;
- 1920x1080;
- libx264;
- CRF 18;
- yuv420p;
- 30fps;
- collision safety;
- exact Composition settle for normal semantic motion.

### Current quality status

**REFERENCE CHOREOGRAPHY PROFESSIONAL BASELINE: VALIDATED**

This means the engine is now validated as a professional production baseline for:
- stable cross-beat pacing;
- readable holds;
- one clear visual attention leader during competing motion;
- Final Package-driven focus order;
- explicit INTERACT -> REACT -> PAYOFF causal grammar;
- Golden-ratio semantic peak shaping;
- compound child semantic utilization without extra extraction;
- collision-safe execution;
- text-vs-visual attention hierarchy;
- encoded semantic-motion visibility;
- deterministic full-package rendering on two materially different real packages.

It does NOT mean frame-by-frame imitation of the reference videos, and it does not replace the final
operator-side Windows parity run with original narration + production WhisperX/E5.

### Remaining operator parity gate

Run current live `montage` on Windows with:
- original target Final Package;
- original ElevenLabs narration;
- production WhisperX;
- production multilingual semantic model;
- FFmpeg 9.0.2.

For Gray-Hat diagnostic `10f16ca6`, exact package/audio bytes are still absent from this sandbox, so the
operator rerender remains required to close that specific production package gate.

If the Windows render completes, perform perceptual A/B against:
1. previous render;
2. current render;
3. reference-video family.

Do not change production code merely because a scalar pixel-motion statistic is not identical to unrelated
reference artwork. Open a new code change only when visual review or a new diagnostic identifies a concrete
general failure class.
# MONTAGE30 REFERENCE MOTION + CORRECT-BY-CONSTRUCTION RECOVERY HANDOFF — 2026-09-26

## Official branch / live state

Official development branch: `montage`.

Live HEAD before this continuity-only handoff update:
`baec01bd333be75f4f84b6665a2a50a80ec27c6d`
`[motion] Clean shared readability QA imports`

Immediate behavior lineage:
- `29f4c0a6b6289582e31623db670960f540517c38` — `[motion] Replace legacy motion with reference gesture language`
- `bbcb30acab068e5907ae9d4c9190308e8e5cde62` — `[motion] Share rendered readability contract with planner`
- `baec01bd333be75f4f84b6665a2a50a80ec27c6d` — `[motion] Clean shared readability QA imports`

Latest exact-head CI before this handoff update:
- workflow: `V2 CI`
- run: `36203409846`
- run number: `551`
- conclusion: **SUCCESS**
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: **395 passed, 12 warnings in 14.64 s**
- exact tested-source artifact: `hexa-storyengine-source-e8e934fc317c7d9fc2bef11ea141ba2fb1528056`
- artifact digest: `sha256:d12c1c75911e3da1e518bdd4ba16a06ea02750c6b4e10f5b0872368df35d5015`

Always verify live `montage` HEAD/CI before editing.

## Motion decision locked

The user explicitly rejected the old Motion visual character and requested production Motion to follow the approved reference-video family instead of continuing to polish legacy bounce/wobble/recoil shapes.

Approved reference family:
- `تأثير المتفرج2.mp4`
- `انحياز 2.mp4`
- `hallo 2.mp4`

Dominant reference rule:
`one clear meaning-bearing gesture -> settle -> readable HOLD -> next semantic gesture`

Accepted gesture abstraction:
- HOLD
- SLIDE_SETTLE
- POP_REVEAL
- SEQUENTIAL_ADD
- FOCUS_HANDOFF
- DIRECTIONAL_HANDOFF
- SHORT_IMPACT
- STATE_CHANGE
- RESULT_ENTER
- COMPARE_SHIFT

Do not reintroduce continuous decorative wobble, repeated bounce after settle, or generic REACT/PAYOFF pulses.

## Legacy Motion removal

Commit `29f4c0a6b6289582e31623db670960f540517c38` replaced the old production Motion primitive path.

Added:
- `app/reference/motion_language.py`
- `app/motion/reference_gestures.py`

Changed:
- `app/motion/planner.py` now uses `ReferenceGestureLibrary`.

Removed:
- `app/motion/primitives.py`
- `app/motion/semantic_primitives.py`

Architecture remains:
- Final Package = semantic authority.
- Story/WhisperX = timing authority.
- Choreography = semantic action authority.
- Composition = final resting geometry authority.
- Reference Motion Language = visual gesture-shape authority.
- Pass1 + Pass2 only. No Pass3/Layer3.

Reference Motion invariants:
- one primary gesture per semantic moment where possible;
- no unjustified post-settle movement;
- support must not mirror Hero accent automatically;
- PAYOFF is not automatically a bounce;
- REACT is not automatically a shake;
- state/result changes prefer STATE_CHANGE / RESULT_ENTER where appropriate;
- all normal gestures settle exactly to Composition geometry;
- any later motion requires a new semantic reason.

## Black-Hat current operator render

User rendered:
`HEXA_BLACK_HAT_HACKER_AR(2).mp4`

Technical probe:
- approximately 97.07 s
- 1920x1080
- 30 fps
- H.264 + AAC
- technically valid media.

Operator visual feedback remains OPEN:
- some elements appear to disappear and reappear;
- continuity/handoff feels strange in places;
- motion still feels weaker than desired relative to references;
- final shot/final payoff needs stronger authority;
- full lifecycle/continuity review is still required.

The Black-Hat visual audit was started but interrupted by the White-Hat diagnostic. Do not mark Black-Hat visual parity closed.

Next audit must inspect:
- asset lifecycle / visibility ownership;
- duplicate reveal/re-entry vs legitimate semantic reactivation;
- scene-to-scene continuity;
- motion strength/reference gap without reintroducing legacy bounce;
- final-scene payoff/focus hierarchy.

## White-Hat diagnostic: exact failure

User supplied:
`HEXA-diagnostic-1a54d71f.zip`

Final Package validation itself is valid. This was NOT a package-authority failure.

Pre-render Authoring QA passed:
- 137 semantic sync anchors
- 0 conservative fallbacks
- 11 relation timelines
- 7 focus cohorts
- 0 rhythm violations
- 0 visual layout violations
- 0 text layout violations after recovery
- 0 short-motion violations

Final failure was only in `RenderedMotionQA`:

- code: `MOTION_BELOW_PERCEPTUAL_FLOOR`
- beat: `beat-016`
- asset: `SCENE_016:asset-03`
- phase: `ESTABLISH`
- expected/planned visible motion: **12.45 px**
- rendered readability floor: **15.36 px**
- encoded mean_delta: **0.0**
- encoded changed_ratio: **0.0**

This is the concrete historical example for the new architecture: Planner must not author a gesture below the same perceptual floor enforced later by encoded QA.

## First Correct-by-Construction fix already landed

`bbcb30acab068e5907ae9d4c9190308e8e5cde62`
`[motion] Share rendered readability contract with planner`

`baec01bd333be75f4f84b6665a2a50a80ec27c6d`
`[motion] Clean shared readability QA imports`

The fix centralizes ENTRY / ESTABLISH / ADD / INTERACT / REACT / PAYOFF / EXIT readability in shared `semantic_readability_floor(...)` logic in `app/motion/timing.py`.

The same contract is now consumed by:
- MotionPlanner before committing a semantic segment;
- RenderedMotionQA when projecting expected readability into encoded pixels.

An exact regression test reproduces the White-Hat 15.36 px ESTABLISH floor.

Current CI after the change: 395 passed.

IMPORTANT: White-Hat has NOT yet been rerendered from current exact tested source in this conversation. Code-level root cause is addressed, but encoded proof remains OPEN.

## White diagnostic text Recovery evidence

The same diagnostic recorded three `TEXT_LAYOUT_REFERENCE_VIOLATION` recovery attempts:
- attempt 1: 8 remaining;
- attempt 2: 5 remaining;
- attempt 3: success, 0 remaining.

Third recovery dropped optional cues:
- `text-004`
- `text-024`
- `text-025`
- `text-040`
- `text-066`

This behavior must be reviewed in the new Recovery architecture. Dropping optional text may remain a bounded last fallback, but should not be the default route to passing layout QA. Preferred approach: Text/Composition should build against actual visual occupancy/lifetime first.

No silent degradation is allowed.

## Next official objective

Build a production-grade generic:

**Correct-by-Construction + Error Handling + Recovery + QA architecture**

User requirement:
- known historical failure classes must be handled generically;
- builders/planners should avoid known-invalid states before QA;
- Recovery handles only exceptional cases that cannot be prevented during construction;
- QA remains strict and proves correctness; do not weaken QA to pass;
- missing/invalid Final Package authority is the explicit exception: fail fast and never invent meaning.

Target flow:

`Final Package -> shared quality contracts -> Story -> Composition -> Motion -> bounded Recovery if required -> pre-render QA -> Render -> encoded QA -> reference-match QA`

Do NOT use:
`build invalid plan -> QA fails -> patch until green`

QA is a proof barrier, not the primary repair engine.

## Shared contracts required

Use one source of truth consumed by both builder and QA. Do not duplicate thresholds.

Contracts to centralize/formalize:
- timing / reveal / handoff boundaries;
- focus / attention allocation;
- motion readability / comfort / speed;
- geometry / exact final settle;
- collision / path safety;
- continuity / scene bridge / lifecycle;
- semantic event/relation coverage;
- reference gesture legality.

Do not create a new abstraction package just for aesthetics. Reuse existing ownership where practical. The shared readability contract already lives in `app/motion/timing.py`; preserve one source of truth.

## Correct-by-Construction requirements

Story/timing must prevent before QA:
- reveal before Story/audio authority;
- settle past next semantic handoff;
- reversed sequence;
- collapsed required sequential reveal;
- simultaneous strong focus on distinct sequential meanings.

Focus allocation:
- one dominant Hero/focus owner per semantic moment unless a true authored comparison requires dual focus;
- support/context receive bounded secondary emphasis;
- support cannot automatically copy Hero motion.

Motion feasibility:
Before authoring any gesture, evaluate:
- selected reference gesture;
- available Story time;
- asset dimensions;
- distance;
- semantic importance;
- final Composition geometry;
- minimum perceptual readability;
- maximum comfort/speed/displacement.

If infeasible, generic order:
1. choose a simpler reference-approved gesture if semantics allow;
2. reduce legal travel only if readability remains satisfied;
3. bounded retime inside Story authority;
4. fail closed if truthful representation is impossible.

Do not knowingly author an invalid gesture and rely on RenderedMotionQA to discover it.

Semantic gesture composition:
INTERACT / REACT / PAYOFF remain semantic stages but must not automatically create three perceptual hits.
When they represent one visual sentence, compose them coherently. Reaction may terminate directly in result state. Avoid redundant payoff bounce.

Collision prevention:
Validate candidate motion path before final commit.
Bounded generic candidate order:
1. lower amplitude only while remaining readable;
2. safer semantically consistent direction;
3. bounded retime;
4. alternate reference-approved gesture;
5. reject if no truthful candidate.

A candidate must not introduce a new collision/order violation.

Text/Composition:
Build text against actual artwork visibility/occupancy during its readability window. Prefer valid placement over dropping optional text later.

Scene continuity/lifecycle:
Every scene boundary should resolve to an explicit valid transition contract, e.g. CLEAN_CUT, OBJECT_HANDOFF, MOTION_HANDOFF, or explicitly authored blur.

Builder should prevent:
- missing/empty handoff carrier;
- too-short bridge;
- bridge overrun;
- incoming before Story;
- accidental disappearance/reappearance due to ownership/lifetime errors.

Repeated appearance is valid only with a new authored semantic reason. Otherwise preserve continuity/lifetime.

## Recovery policy

Known non-package failures must become named generic failure classes, never scene-specific patches.

Every recovery class must define:
- trigger;
- owning stage;
- bounded candidate list;
- contracts revalidated after every candidate;
- rollback;
- max attempts;
- diagnostic record;
- fail-closed escalation.

Recommended categories:
- extraction safety / compound integrity;
- semantic representation / compound proxy;
- Story/timing conflict;
- focus conflict;
- motion readability / comfort infeasibility;
- motion collision;
- duplicate semantic accent;
- continuity/handoff/lifecycle;
- text placement;
- render environment / codec/filter incompatibility;
- encoded survival failure.

Never silently recover.

## Final Package exception

Do NOT auto-repair/guess when Final Package itself is invalid or missing semantic authority, including:
- required semantic intent/binding missing;
- malformed progression;
- invalid scene plan;
- missing authored authority needed to know meaning.

Fail clearly. Do not weaken validator and do not invent meaning.

Historical package-authoring examples:
- `semantic asset intent missing ...`
- `semantic progression must be an object ...`

These remain package errors, not Recovery cases.

## QA architecture

Pre-render QA should be nearly zero by construction and prove:
- required semantic event coverage = 100%;
- required authored relation coverage = 100%;
- valid Story order/timing;
- no illegal early reveal;
- no unauthorized competing Hero;
- no motion-created collision;
- no segment past handoff;
- no geometry drift;
- no unsupported legacy gesture;
- no unjustified post-settle movement;
- valid scene bridge/lifecycle;
- text/layout valid for actual visual lifetime.

If pre-render QA fails, treat it as builder bug or unrecoverable input; do not spend FFmpeg time on a known-invalid plan.

Post-render QA remains required for facts only encoding can prove:
- frames exist;
- ROI survives;
- required motion remains visible;
- encoded result is not static when motion is required;
- encoded speed remains legal;
- full decode succeeds;
- A/V/output specs are valid.

Encoded QA must project shared authoring contracts, not own private thresholds.

Reference-match QA must compare editing language, not pixel clone similarity across different artwork.

Measure:
- gesture durations;
- hold durations;
- burst frequency;
- post-settle motion;
- duplicate semantic accents;
- simultaneous strong movers;
- focus handoff cadence;
- motion strength;
- jerk as evidence;
- sequential reveal spacing;
- scene transition pacing;
- final payoff authority.

Derive acceptable ranges from the three approved reference videos.

Hard invariants where applicable:
- unjustified post-settle motion = 0;
- duplicate semantic accents = 0;
- early reveals = 0;
- motion-created collisions = 0;
- required semantic event coverage = 100%;
- required authored relation coverage = 100%;
- valid scene bridge coverage = 100%.

## Regression matrix for every general fix

A fix is not accepted because only White or Black passes.

Run at minimum:
- Black Hat: attack/cause/result + current lifecycle/operator feedback;
- White Hat: compound semantic proxies + ESTABLISH readability regression;
- Gray Hat: density/variation;
- Script Kiddie: materially different package;
- synthetic 1-asset;
- synthetic ~20-item;
- 0.5 s beat;
- 8 s beat;
- comparison;
- repeated asset across scenes;
- same asset enters/exits repeatedly;
- no character;
- long Arabic text;
- realistic-image and illustration cases where available.

Pass1 + Pass2 only throughout.

## Exact next actions

1. Verify live `montage` HEAD and CI.
2. Rerender White Hat from current exact tested source with production inputs if available; prove the previous beat-016 ESTABLISH failure is gone and no new encoded-motion failure appears.
3. Finish interrupted visual audit of `HEXA_BLACK_HAT_HACKER_AR(2).mp4`: disappear/reappear lifecycle, strange continuity, motion strength gap, final payoff.
4. Map every visual/QA defect to its owning builder contract BEFORE writing Recovery.
5. Implement shared contracts incrementally beyond the readability contract: lifecycle/continuity, focus, gesture feasibility, semantic gesture composition.
6. Implement bounded Recovery only after the corresponding builder contract exists.
7. Mirror every contract in strict QA without duplicate thresholds.
8. Add historical regression cases + stress matrix.
9. Full CI after each committed slice.
10. Render Black + White first; then Gray + Script Kiddie.
11. Compare encoded outputs against reference family.
12. Mark a failure class CLOSED only after exact-source render + technical QA + visual approval.

## Non-negotiable locks

- work on live `montage` unless user explicitly changes branch;
- verify HEAD/CI before edits;
- Pass1 + Pass2 only; never Pass3/Layer3;
- Final Package semantic authority remains absolute;
- Story/WhisperX timing authority remains absolute;
- Composition final geometry authority remains absolute;
- Reference Motion Language is the visual motion-shape authority;
- do not weaken QA merely to get green;
- no scene/package-specific production hardcoding;
- no invented semantic meaning for invalid Final Packages;
- no silent Recovery or silent degradation;
- every recovery candidate bounded, monotonic, revalidated, rollback-safe;
- avoid unnecessary re-encoding;
- never claim reference parity from CI/scalar metrics alone;
- record new accepted changes and real render evidence in this continuity file before the next handoff.


# MONTAGE31 SHARED READABILITY DURATION CONTRACT — 2026-09-26

## New White-Hat diagnostic and confirmed engine failure class

Operator diagnostic:
- `HEXA-diagnostic-7980cc76(1).zip`
- job: `7980cc7668bd4e9e8e3dafa195fc21ec`
- source commit reported by the job: `baec01bd333be75f4f84b6665a2a50a80ec27c6d`
- Final Package: `HEXA_WHITE_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip`
- failure remained:
  - code: `MOTION_BELOW_PERCEPTUAL_FLOOR`
  - beat: `beat-016`
  - asset: `SCENE_016:asset-03`
  - phase: `ESTABLISH`
  - planned motion: `12.45 px`
  - rendered/shared floor: `15.36 px`
  - encoded `mean_delta = 0.0`
  - encoded `changed_ratio = 0.0`

This proves the first shared-floor fix was incomplete. The Final Package was not the cause.

## Exact root cause

Planner and RenderedMotionQA used the same `semantic_readability_floor(...)` formula but did not use the same meaning for its duration argument.

For Story-aligned event accents:
- MotionPlanner calculated ESTABLISH/ADD readability from the shorter internal `active_duration` around the semantic peak.
- RenderedMotionQA calculated ESTABLISH/ADD readability from the full authored MotionSegment duration.

A late semantic peak could therefore reduce Planner amplitude below the exact floor that QA would later enforce. The White-Hat case reproduced this deterministically:
- old planner peak: `12.4499 px`
- required floor: `15.3600 px`

This is a generic Planner/QA contract mismatch, not a White-specific exception.

## Generic prevention landed

Behavior commit:
`2b718f0fc32fc86fca3579215a3f2f0916c5542f`
`[motion] Unify planner and rendered readability duration`

Changes:
- `app/motion/timing.py`
  - adds canonical `semantic_readability_duration(...)`.
  - INTERACT/REACT/PAYOFF use semantic active duration.
  - ENTRY/ESTABLISH/ADD/EXIT use authored segment duration.
- `app/motion/planner.py`
  - consumes the canonical duration policy before committing event motion.
  - separates perceptual/readability duration from actual movement duration.
  - comfort remains evaluated against the real active movement window.
  - if readable displacement cannot fit within the comfort ceiling, Planner fails before render with diagnostic code `MOTION_INFEASIBLE_BEFORE_RENDER`.
- `app/qa/rendered_motion.py`
  - consumes the same canonical duration policy.
  - no private duration interpretation remains for the shared floor.
- regressions cover the historical late-peak ESTABLISH mismatch and shared phase-duration semantics.

No Final Package, scene, asset id, QA threshold, or reference threshold was hardcoded into production logic.

## Proof

Deterministic regression:
- old exact source generated `12.4499 px` for the reproduced late-peak ESTABLISH case.
- corrected source generates `15.3600 px`.
- required floor remains unchanged at `15.3600 px`.

CI for behavior commit:
- workflow: `V2 CI`
- run: `36205257737`
- run number: `553`
- conclusion: SUCCESS
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: `396 passed, 12 warnings`
- exact tested-source artifact: `hexa-storyengine-source-35bbac269942681c2c032bd5497b9240000234e4`
- artifact digest: `sha256:68f1bc7d4f6fb24df629de974732e5a1f8b03465f1ce351cf65a7d54d72d0449`

A fail-closed regression is added with this continuity update to prove an infeasible readable+comfortable ESTABLISH is rejected before FFmpeg rather than authored below the QA floor.

## Status / next proof

White-Hat is NOT CLOSED yet.

Required next acceptance:
1. rerender the same White-Hat Final Package + narration from current exact source;
2. pre-render QA must pass;
3. `beat-016 / SCENE_016:asset-03 / ESTABLISH` must no longer report below-floor motion;
4. RenderedMotionQA must pass on the encoded output;
5. full decode and visual/reference review must pass.

Do not weaken the `15.36 px` contract to obtain green output. The Builder must meet it or fail closed before render.

Black-Hat visual lifecycle/continuity/reference-strength audit remains OPEN and resumes after this White-Hat regression proof is locked.


# MONTAGE31 LIFECYCLE + RECOVERY SAFETY + FAILURE IDENTITY — 2026-09-26

## Scope of this checkpoint

This checkpoint converts three observed generic failure classes into shared production contracts:
1. persistent asset lifecycle / disappear-reappear prevention;
2. monotonic rollback-safe Recovery;
3. preservation of specific failure identity through diagnostics/API.

No Final Package meaning, Composition geometry, reference gesture thresholds, or QA thresholds were weakened.

## 1. Persistent asset lifecycle contract

Black-Hat visual audit identified a generic lifecycle contradiction:

`visible -> terminal EXIT/LEAVE -> hidden -> adjacent beat -> same asset_id visible again`

Root cause:
- renderer derived persistence from adjacent-layout asset-id intersection;
- Motion could independently author terminal `EXIT` with `terminal_behavior=LEAVE`;
- SceneContinuityQA previously checked only cross-scene transition quality and did not reject the contradiction on every adjacent beat.

Generic prevention:
- new `app/contracts/continuity.py` is shared authority for adjacent-beat asset lifecycle;
- MotionPlanner does not author terminal EXIT when the exact same asset continues into the next layout;
- SceneContinuityQA checks lifecycle on every adjacent beat, including within one scene;
- invalid externally supplied/legacy plans receive `TERMINAL_EXIT_ON_PERSISTENT_ASSET`;
- FFmpegRenderer consumes the same contract and fails closed if an invalid plan bypasses upstream QA.

Behavior commit:
`4be91516360450568b800e739e8cedca942fec8b`
`[continuity] Enforce persistent asset lifecycle contract`

CI:
- run: `36206336359`
- run number: `555`
- conclusion: SUCCESS
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: `401 passed, 12 warnings`
- exact tested-source artifact: `hexa-storyengine-source-842fbeade98b45ae3bb6ba537c3bd67ca69061e4`
- digest: `sha256:9070d49da46d93440cda978f74bb852d3187df39f4168b0ffd92adb004fed9d6`

Status:
- generic code-level disappear/reappear failure class: PREVENTED + CI PROVEN;
- Black-Hat encoded/visual proof: OPEN until a new exact-source render is inspected.

## 2. Monotonic rollback-safe Recovery

Historical Recovery behavior could accept a candidate merely because the same issue code disappeared. It did not prove that:
- no new issue was introduced;
- another issue count did not regress;
- Final-Package-derived semantic authority remained unchanged;
- the previous accepted plan/output remained available for rollback.

Generic Recovery contract:
`Problem -> bounded candidate -> same detector/contracts -> monotonic evaluator -> accept OR rollback/fail`

Added `app/recovery/evaluator.py`:
- fingerprints issue instances by code + normalized context;
- verifies exact target resolution;
- rejects newly introduced issue instances;
- rejects issue-count regressions;
- requires strict reduction of detected problems;
- compares semantic-authority signatures for plan recovery;
- rejects any candidate that changes semantic authority.

Pipeline changes:
- plan recovery builds and evaluates a candidate before replacing the accepted plan;
- rejected plan candidate leaves the original plan intact;
- final/render recovery writes to candidate paths first;
- accepted candidate is copied to final output only after validation;
- rejected candidate never overwrites the previously accepted output;
- all assessments are recorded in Recovery details.

Behavior commit:
`a5e8543fdd9d474d46c8c1083b7bbc6102a626a2`
`[recovery] Enforce monotonic rollback-safe candidates`

CI:
- run: `36206611878`
- run number: `556`
- conclusion: SUCCESS
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: `405 passed, 12 warnings`
- exact tested-source artifact: `hexa-storyengine-source-374f3110b5c9d2c6fa1f560f400435faa3a1ab9a`
- digest: `sha256:fda7ac4209ca6bb1e778f061ba2831fd2ebab6a5016e3e8447b431e14fddc541`

Locked Recovery rule:
Recovery is never allowed to trade one defect for another, silently change semantic authority, or overwrite an accepted state before candidate validation.

## 3. Specific failure identity

Root cause:
- engine exceptions already carried precise generic codes in `details["code"]`, e.g.
  `MOTION_INFEASIBLE_BEFORE_RENDER` and `TERMINAL_EXIT_ON_PERSISTENT_ASSET`;
- API and diagnostic top-level output surfaced only broad category `STAGE_FAILED`;
- this hid the real Failure Class from the operator and made recurrence analysis weaker.

Generic error identity:
- `HexaError.code` remains the compatibility/category code;
- `HexaError.effective_code` exposes a nonblank specific detail code when present;
- diagnostic JSON records both `code` (specific failure) and `category`;
- diagnostic Markdown displays both;
- API job `error_code` uses the specific effective code.

Behavior commit:
`33370db7cb26ba00bacc7ecd631fd6ae1bbc6d61`
`[errors] Preserve specific failure identity`

CI:
- run: `36206805412`
- run number: `557`
- conclusion: SUCCESS
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: `408 passed, 12 warnings`
- exact tested-source artifact: `hexa-storyengine-source-43f59da1bafba9a4c20a71109b374af32b897636`
- digest: `sha256:fcee419793af24fb5f0ccb9b70b3337217120845b392cae74271d760e9fb37a5`

## Current proof status

Code/CI proven:
- shared White-Hat readability-duration contract;
- fail-before-render for infeasible readable+comfortable motion;
- persistent asset lifecycle prevention;
- continuity QA for terminal-exit/persistence contradiction;
- renderer fail-closed lifecycle guard;
- monotonic rollback-safe Recovery;
- specific error identity through diagnostics/API.

Still OPEN and must not be called visually closed:
- White-Hat rerender from current exact source and encoded RenderedMotionQA;
- Black-Hat rerender from current exact source to prove disappear/reappear is gone;
- Black-Hat motion-language strength/rhythm gap vs approved references;
- final payoff/focus authority;
- full ReferenceMatchQA;
- remaining shared contracts (focus, semantic gesture composition, generalized environment preflight, text lifetime-aware placement).

## Next engineering order

1. Add/strengthen production environment preflight so known FFmpeg/audio/alignment/output failures are rejected before expensive work.
2. Rerender White and Black from the latest exact tested source when production inputs are available.
3. Inspect encoded lifecycle, scene handoff, motion strength and final payoff.
4. Implement FocusContract + semantic gesture composition against concrete remaining defects.
5. Implement ReferenceMatchQA from measured approved-reference distributions, never invented thresholds.
6. Extend Recovery only after each corresponding builder/shared contract exists.
7. Run Black/White/Gray/Script Kiddie + synthetic stress matrix.
8. Mark a failure class CLOSED only after code/CI + exact-source render + technical QA + visual review.



# MONTAGE31 ENVIRONMENT PREFLIGHT CONTRACT — 2026-09-26

## Production environment preflight

Behavior commit:
`1d40fbe7d65db7e5a75d5a2d61b3193de28f0e77`
`[preflight] Fail early on environment dependencies`

The pipeline now proves known environment requirements before expensive visual stages.

Early checks:
- work workspace can be created and written;
- output root can be written;
- FFmpeg render path performs a real tiny H.264/yuv420p encode;
- final export path performs a real copy-video + AAC + MP4 mux;
- narration file exists;
- ffprobe can read valid duration metadata;
- when production forced alignment is required and a script exists, WhisperX runtime and language model are loaded during preflight and cached for the immediate alignment stage.

Specific failure identities include:
- `WORKSPACE_NOT_WRITABLE`
- `OUTPUT_ROOT_NOT_WRITABLE`
- `AUDIO_INPUT_MISSING`
- `FFPROBE_UNAVAILABLE`
- `MEDIA_PROBE_FAILED`
- `MEDIA_PROBE_INVALID_METADATA`
- `MEDIA_DURATION_INVALID`
- `FFMPEG_UNAVAILABLE`
- `FFMPEG_CAPABILITY_PROBE_FAILED`
- `RENDER_PREFLIGHT_EMPTY`
- `FINAL_MUX_PREFLIGHT_FAILED`
- `FINAL_MUX_PREFLIGHT_EMPTY`
- `FINAL_MUX_FAILED`
- `ALIGNMENT_PREFLIGHT_UNAVAILABLE`
- `ALIGNMENT_RUNTIME_UNAVAILABLE`
- `ALIGNMENT_MODEL_NOT_CONFIGURED`
- `ALIGNMENT_MODEL_LOAD_FAILED`
- `ALIGNMENT_SCRIPT_UNSUPPORTED`
- `RENDER_PROCESS_COMMAND_LIMIT`
- `RENDER_PROCESS_OS_ERROR`
- `FFMPEG_COMMAND_FAILED`

The forced-alignment preflight intentionally loads the model early but does not load it twice: the same aligner instance caches the model and `align()` reuses it, then normal release logic frees it after transcription.

CI:
- workflow: `V2 CI`
- run: `36207554935`
- run number: `559`
- conclusion: SUCCESS
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: `416 passed, 12 warnings`
- exact tested-source artifact: `hexa-storyengine-source-d728f0ab6f8e972941e5121db7853efdb94d28ed`
- artifact digest: `sha256:b2bddef3724891af443570e32b566ab9b18625ffd9507163ad3bf6b26d56d48d`

## Reference-match investigation status

No standalone production `ReferenceMatchQA` exists yet.

Existing `ReferenceAnalyzer` currently exposes static visual/reference constants only; it does not extract burst/hold/jerk distributions from reference video bytes.

The three approved references are identifiable as:
- `تأثير المتفرج2.mp4`
- `انحياز 2.mp4`
- `MONTAGE9_REF_HALLO2.mp4` (hallo 2 reference)

The first two are available as raw local media in the current engineering environment. The third is indexed in Library/Project metadata but raw-byte materialization was not authorized in this session. Do not invent thresholds from only two references and do not mark ReferenceMatchQA complete.

Black-Hat motion audit evidence remains:
- motion language feels more fragmented than the approved reference family;
- earlier measurement showed excess short motion bursts relative to the two raw references inspected;
- lifecycle disappear/reappear prevention is now code/CI proven but still requires a fresh Black-Hat encoded render for visual closure.

Semantic gesture-composition investigation:
- EventFlow already prevents the same result asset from receiving redundant REACT+PAYOFF ownership;
- source INTERACT and target REACT may overlap as one cause/reaction sentence;
- PAYOFF timing remains owned by Story/result activation;
- do not collapse or retime semantic phases merely to reduce burst count unless ReferenceMatch/diagnostic evidence proves a redundant accent. Story authority remains absolute.

Next actions:
1. build deterministic ReferenceMatch metric extraction against all three approved references once all three raw videos are available to the runtime;
2. derive acceptable ranges from those videos, never hand-authored guesses;
3. rerender White Hat from current exact tested source and close the historical encoded readability failure only after RenderedMotionQA + full decode + visual review;
4. rerender Black Hat from current exact tested source and verify lifecycle continuity visually;
5. use ReferenceMatch evidence to decide whether a SemanticGestureComposer change is required;
6. continue Gray/Script Kiddie + stress matrix only after the Black/White gates pass.


# STRICT RENDER-FAILURE PERMANENCE CONTRACT — 2026-09-26

## User-mandated non-negotiable product rule

This rule is permanent and applies to every current and future Final Package.

Every real failure discovered while loading, planning, validating, rendering, encoding, muxing, decoding, exporting, or visually reviewing ANY Final Package is a product-level defect class until proven otherwise.

It is forbidden to treat a discovered failure as:
- a one-off package problem without proof;
- a White/Black/Gray/Script-Kiddie special case;
- a scene-id or asset-id exception;
- a manual operator workaround;
- a QA-threshold problem to be weakened;
- a reason to delete/hide assets, relations, text, motion, or semantic intent;
- a reason to modify a valid Final Package so the engine can pass;
- an error that may simply be retried blindly;
- closed merely because unit tests or CI are green.

### Mandatory lifecycle for EVERY discovered failure

For every failure reported from a real operator run:

1. **Preserve evidence**
   - keep the diagnostic ZIP/log/error code/render artifact when available;
   - identify the exact stage, inputs, and observed symptom.

2. **Find the root cause**
   - diagnose the generic engine condition that allowed the failure;
   - do not stop at the top-level exception text.

3. **Assign one owning layer**
   - Final Package validation;
   - Story/timing;
   - Choreography;
   - Composition;
   - Motion;
   - Text;
   - Pass1/Pass2 extraction;
   - Recovery;
   - FFmpeg/render;
   - final export/mux;
   - pre-render QA;
   - encoded/post-render QA;
   - environment/preflight.

4. **Implement a GENERAL fix**
   - the fix must apply to every future package with the same underlying condition;
   - no package name, scene id, asset id, script phrase, hardcoded timestamp, or package-specific geometry may appear in production logic.

5. **Prevent before expensive render whenever technically possible**
   - if the failure can be known from authored state, contracts, timing, geometry, environment, codec/filter capability, asset lifecycle, collision path, semantic coverage, text layout, or motion feasibility, it must be prevented/detected before expensive FFmpeg rendering;
   - do not knowingly author an invalid state and wait for 70%+ render progress to discover it.

6. **Declare an explicit Failure Policy**
   Every production failure code must have an explicit owner and one disposition:
   - PREVENT
   - RECOVER
   - FAIL_FAST
   - POST_RENDER_PROOF

   No production failure code may exist without a policy.

7. **Recovery is allowed only when safe and bounded**
   - candidate-based;
   - monotonic;
   - revalidated against the same contracts;
   - no new defect;
   - no semantic-authority change;
   - rollback-safe;
   - bounded attempts;
   - recorded in diagnostics.
   Blind retry is forbidden.

8. **Add a permanent regression**
   - reproduce the generic condition that caused the real failure;
   - prove the old bad state is rejected or corrected;
   - prove the intended valid state remains accepted;
   - keep the regression permanently in the suite.

9. **Run the broader regression matrix**
   A fix is not accepted because the triggering package alone passes.
   At minimum consider its effect on:
   - White Hat;
   - Black Hat;
   - Gray Hat;
   - Script Kiddie;
   - dense scenes;
   - one-asset scenes;
   - short and long beats;
   - repeated assets;
   - multi-enter/exit cases;
   - comparison/timeline scenes;
   - long Arabic text;
   - character/no-character scenes;
   - realistic and illustrated media where relevant.

10. **CI must pass on exact source**
    - Compile PASS;
    - Ruff PASS;
    - full automated tests PASS;
    - exact tested-source artifact recorded when produced.

11. **Real-render verification is mandatory**
    The failure class is not CLOSED from code/CI alone.
    Re-run the real package/input that exposed it and verify the corrected exact source.

12. **Post-render-only failures still require permanent handling**
    If a fact genuinely cannot be known until encoded frames exist:
    - keep strict post-render proof;
    - add the earliest practical probe/sampling check if it can reduce wasted render time;
    - never pretend such a failure can be proven pre-render when it cannot;
    - once discovered, preserve a regression/proof path so the same root cause is not silently reintroduced.

### Definition of CLOSED for a discovered failure

A real failure may be marked CLOSED only when all applicable gates are satisfied:

`Root Cause identified
-> Generic production fix
-> Shared contract / owning-stage prevention where applicable
-> Explicit Failure Policy
-> Permanent regression
-> Full CI
-> Real triggering-package rerender
-> Technical QA
-> Full decode/export proof where applicable
-> Visual/reference review where the defect is perceptual`

Anything less remains OPEN.

### Recurrence rule

The same known root cause must not be allowed to recur silently in a future Final Package.

If a previously closed failure code or equivalent root cause reappears:
- treat it as a regression in the engine;
- do not patch the new package;
- do not weaken QA;
- reopen the owning contract/implementation and strengthen the permanent regression until the recurrence path is closed.

### Product objective

HEXA-StoryEngine is expected to process many heterogeneous Final Packages. Therefore the product must become progressively stronger from every real failure discovered in production.

The required engineering loop is permanently:

`Real Failure
-> Evidence
-> Root Cause
-> Generic Fix
-> Failure Policy
-> Regression
-> CI
-> Real Render Proof
-> Permanent Contract`

The project must never regress to:

`new package -> wait for late render failure -> manual/package-specific patch -> retry`

### Current implementation baseline when this rule was locked

Behavior HEAD:
`c5111bc1d05afd3971fdf54d57724f95d3d4ca62`
`[preflight] Probe ffmpeg filter transport by execution`

CI proof:
- workflow run: `36210742931`
- run number: `572`
- conclusion: SUCCESS
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: `437 passed, 12 warnings`

The latest FFmpeg failure discovered by the operator:
`ffmpeg does not expose a supported file-backed complex-filter option`

was treated under this rule:
- root cause: help-text-based capability inference produced a false negative on the operator's Windows FFmpeg build;
- generic fix: production filter transport is now selected by executing real capability probes;
- generic order: `-/filter_complex` then fallback to `-filter_complex_script`;
- direct renderer calls resolve capability before worker threads to avoid probe races;
- only if both real probes fail does the engine raise `FFMPEG_FILTER_FILE_UNSUPPORTED`;
- no Final Package, scene, motion, Story, Composition, or QA threshold was changed.

This operator rule supersedes any older handoff wording that could be interpreted as allowing a known render failure to remain a recurring per-package troubleshooting task.


# GRAY-HAT RELATION TIMELINE REGRESSION — 2026-09-26

Operator diagnostic:
- `HEXA-diagnostic-9322cea6.zip`
- job: `9322cea6469c470898d9a8f1deae89fd`
- source commit in diagnostic: `c5111bc1d05afd3971fdf54d57724f95d3d4ca62`
- package: Gray Hat corrected V1.2 package
- failure occurred before FFmpeg render at MotionInteractionQA (~64% pipeline progress).

Observed violations:
- `MISSING_RELATION_TIMELINE` — beat-018, NOT_STOLEN relation.
- `MISSING_RELATION_TIMELINE` — beat-024, compound/Pass2 ENTRIES relation.
- `NO_RELATION_OVERLAP` — beat-010, source INTERACT and target REACT separated by a tiny timing gap.
- `MISSING_TARGET_REACTION` — beat-014, DISCOVERS relation.

Root cause:
- Motion could schedule dense authored relations independently per asset and silently lose a later semantic relation when local timing was already occupied.
- relation source INTERACT could reserve too much of the Story-owned phrase, leaving no legal room for another authored relation.
- Pass2/compound target/source timing could produce a source/reaction pair with no actual causal overlap.
- relation phase deduplication did not include the complete relation identity.
- aggregate QA code `MOTION_CONTRACT_VIOLATIONS` was not itself included in failure-policy coverage, so the diagnostic showed policy=null even though its individual violation codes were classified.

Generic production fix:
- commit: `1ab23e54830b50039e365aba4dc3da5aea476154`
- message: `[motion] Prevent authored relation timeline regressions`
- bounded source INTERACT gestures preserve room for multiple authored relations inside one spoken phrase;
- relation/proxy phases may retry from the Story-owned cue boundary instead of being silently dropped when decorative/previous occupancy consumes the local window;
- relation phase deduplication now includes source/target/result/relationship identity;
- produced SOURCE INTERACT / TARGET REACT pairs receive a bounded causal-overlap finalization inside existing Story/handoff bounds;
- Motion fails closed before downstream Text/Render if an authored event-flow relation still has no INTERACT, no required REACT, or no causal overlap;
- no scene id, asset id, package name, timestamp, semantic phrase, or QA threshold is hardcoded in production logic.

Failure policy hardening:
- aggregate codes are now included in policy-coverage tests.
- `MOTION_CONTRACT_VIOLATIONS` -> owner motion / PREVENT.
- `RHYTHM_CONTRACT_VIOLATIONS` -> choreography / PREVENT.
- `CONTINUITY_CONTRACT_VIOLATIONS` -> continuity / PREVENT.
- `RENDERED_MOTION_CONTRACT_VIOLATIONS` -> render / POST_RENDER_PROOF.

Permanent regressions:
- multiple dense authored relations from one source must all retain source timelines;
- Pass2-style source/reaction timing gaps are repaired inside legal Story bounds;
- missing target reaction fails inside Motion before downstream QA/render;
- legacy/synthetic non-event-flow behavior remains accepted where no production semantic-event authority exists;
- prior behavior regression suite remains green.

CI proof:
- workflow: V2 CI
- run: `36213306879`
- run number: `574`
- conclusion: SUCCESS
- Compile: SUCCESS
- Ruff: `All checks passed!`
- Pytest: `440 passed, 12 warnings in 15.41s`

Closure status:
- code/CI prevention: CLOSED.
- Gray encoded/visual production proof: OPEN until the same Gray package + narration is rerendered from exact source `1ab23e54830b50039e365aba4dc3da5aea476154` or a descendant containing only documentation/non-behavior changes.
- If any of the same relation failure classes recur on rerender, treat as engine regression under the permanent render-failure handling rule; do not patch the Gray package and do not weaken QA.
