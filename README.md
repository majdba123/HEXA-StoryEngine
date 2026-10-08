# HEXA StoryEngine

HEXA StoryEngine is the clean V2 codebase for HEXA's story-driven automated video editor.

## What the product does

From Adobe Premiere, the user opens the HEXA panel, chooses a Final Package and narration audio, presses **Generate**, then receives the generated video back in Premiere and can insert it directly on the active timeline.

## Processing stages

All engine stages live under `app/`:

`input -> transcription -> vision -> cutout -> story -> composition -> motion -> render -> final`

`recovery` watches the plan/final QA results, recognizes known issue codes, routes the repair to the owning stage, re-runs QA, and persists the verified outcome so the same class of problem is known on future Final Packages.

## Unified Final Package 2.0

Production accepts exactly one Final Package contract: **HEXA Unified Final Package 2.0**.

A package is a directory or ZIP containing:

```text
package.json
images/
  SCENE_001.png
  SCENE_002.png
  ...
```

`package.json` is the only semantic authority. It contains the canonical script, scene order,
visual objects, exact script anchors, visual locators, semantic groups/events, dependencies,
relations, progression, continuity/state metadata, and compound-visual rules. Legacy 1.x
`manifest.json`, `scene_plan.json`, and `semantic_bindings.json` companions are rejected.

The loader validates the 2.0 contract and produces the immutable `CanonicalPackage` boundary
directly. Story, Choreography, Composition, Motion, Text, and Render consume only that canonical
runtime model. Narration timing is still owned by forced alignment; the Final Package owns WHAT,
not encoded seconds.

## Local engine

```bash
python -m pip install -e .
hexa serve
```

Generate without Premiere:

```bash
hexa generate --package /path/to/final-package --audio /path/to/audio.wav
```

## Premiere panel

The UXP panel lives at `premiere/plugin/`. During development it connects to the local engine on `127.0.0.1:8765`.

## Model/runtime configuration

Optional environment variables:

- `HEXA_FLORENCE_MODEL` — local Florence model directory
- `HEXA_SAM2_CHECKPOINT` — local SAM2 checkpoint
- `HEXA_SAM2_CONFIG` — SAM2 config override
- `HEXA_WHISPER_MODEL` — Faster Whisper model/path
- `HEXA_FFMPEG` / `HEXA_FFPROBE` — media tool overrides

## Third-party font

Editorial text is rendered with **Noto Kufi Arabic ExtraBold** (v2.110, The Noto Project
Authors), vendored at `app/text/fonts/NotoKufiArabic-ExtraBold.ttf` and licensed under the
SIL Open Font License 1.1 (`app/text/fonts/OFL.txt`, shipped with the font). Planning
measures and libass renders this exact file; no system font is used for text.

## Legacy reference

`majdba123/Montagetools` remains the official legacy/provenance/reference repository. V2 may reuse proven runtime/model/FFmpeg/Premiere ideas, but the old V31 planner/finalizer/recovery chain is not the V2 architecture.
