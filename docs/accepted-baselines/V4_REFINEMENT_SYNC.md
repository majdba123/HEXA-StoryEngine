# V4 Refinement + Narration Sync Publication

Date: 2026-09-15
Branch: `chatgpt/montage6-v2-bootstrap`

## Protected visual baseline

Cutout Pass 1 remains protected. The approved source-relative composition and Pass-1 extraction behavior must not be made more aggressive by Refinement.

## Refinement Pass 2 contract

Refinement is an independent post-Cutout stage.

Hard rule: **clean full object or nothing**.

A secondary split is accepted only when the candidate is a large, obvious, side-isolated visual with a real background gutter from the dominant cluster. The complete side object is recovered while retaining white/low-saturation details such as faces, shoes, labels and antialiasing. If the candidate touches/overlaps the main cluster, the separator is not clearly background, the candidate core is not recovered essentially completely, or the result is ambiguous, Refinement returns the protected Pass-1 asset unchanged.

Small arrows, badges, warning lights, sparks, numbers and internal details are not Pass-2 split targets.

Derived layers keep the parent canvas/source geometry and must reconstruct the Pass-1 alpha exactly when recomposited.

## Narration / motion contract

Narration is the semantic master clock. Story beats preserve `audio_start` / `audio_end` independently from the visual timeline. The primary visual may anticipate speech slightly so it is readable at the spoken concept rather than reacting late.

Short beats use restrained motion instead of speeding up every object. Longer beats may use reveal/handoff/emphasis motion. Support motion is staggered only when phrase duration allows it. Renderer movement uses eased motion and frame-quantized segment ownership.

## Verification evidence

- Local V4 tests before publication: `19 PASS`.
- Local Python compile: PASS.
- Review render: `HEXA_REFINEMENT_SYNC_REVIEW_V4_FULL.mp4`.
- Review render: 854x480, 30 fps CFR, H.264 + AAC.
- Video/audio stream start: 0.000 s / 0.000 s.
- Video duration: ~99.266667 s.
- Audio duration: ~99.288005 s.
- End difference: ~0.0213 s.

GitHub CI on this publication commit is the authoritative compile/lint/test gate.
