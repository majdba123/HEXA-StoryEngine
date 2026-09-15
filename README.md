# HEXA StoryEngine

HEXA StoryEngine is the clean V2 codebase for HEXA's story-driven automated video editor.

## What the product does

From Adobe Premiere, the user opens the HEXA panel, chooses a Final Package and narration audio, presses **Generate**, then receives the generated video back in Premiere and can insert it directly on the active timeline.

## Processing stages

All engine stages live under `app/`:

`input -> transcription -> vision -> cutout -> story -> composition -> motion -> render -> final`

`recovery` watches the plan/final QA results, recognizes known issue codes, routes the repair to the owning stage, re-runs QA, and persists the verified outcome so the same class of problem is known on future Final Packages.

## Normal Final Packages

V2 does not require extra pre-rendered object images. It can discover visual groups from normal scene images and extract individual assets. When local Florence/SAM2 runtimes are configured, those are used behind the same stage boundaries. Explicit packaged assets are also supported.

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

## Legacy reference

`majdba123/Montagetools` remains the official legacy/provenance/reference repository. V2 may reuse proven runtime/model/FFmpeg/Premiere ideas, but the old V31 planner/finalizer/recovery chain is not the V2 architecture.
