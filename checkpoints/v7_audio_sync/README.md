# HEXA V7 Audio-Synced Object Storytelling Checkpoint

This directory freezes the exact runtime code, generated plans, and diagnostics used for the user-approved V7 review baseline on 2026-09-18.

V7 is the current strongest user-approved montage10 direction. Its defining behavior is **audio-driven progressive object reveal**: separated cutouts enter/focus in relation to aligned narration content instead of exposing every object at scene start. Text cues are also dynamically positioned in scene negative space instead of using a fixed lane.

## Pull / restore

After pulling branch `majd`, restore the exact V7 acceptance runtime source with `python checkpoints/v7_audio_sync/restore_runtime.py <destination>`. The base64-encoded deterministic runtime archive is versioned at `checkpoints/v7_audio_sync/runtime_source.tar.gz.b64`; `manifest.json` freezes the decoded archive and each inner source file, and CI verifies those bytes.

The exact generated alignment/assets/render-plan/diagnostics are preserved in the persistent Library bundle `/HEXA/checkpoints/v7_audio_sync/HEXA_V7_AUDIO_SYNC_CHECKPOINT_BUNDLE.tar.gz`, SHA256 `862bbfaaecd24b1bee4e57afc3e532d1494520789624a82767854193df3ebebd`.

The preserved checkpoint contains:

- `align_ctc.py`
- `serialize_assets.py`
- `build_v7_plan.py`
- `render_v7.py`
- `render_v7_fast.py`
- `reposition_text.py`
- `reposition_text_v2.py`
- `collision_audit_v7.py`
- `alignment.json`
- `assets.json`
- `v7_plan.json`
- `object-audio-sync.json`
- `text-placement.json`
- `ffprobe-final.json`

## Exact review artifact identity

The MP4 is not embedded in Git source history, but its immutable identity is frozen in the manifest:

- `HEXA_V7_AUDIO_SYNC_OBJECT_STORYTELLING_FULL_RENDER.mp4`
- SHA256 `b1964762ed826b2442cd76085b2f31bd067e8595fe71424600eabd1a5e0329cd`
- H.264, 1920x1080, CFR 30fps, 102.4s
- AAC mono, 44.1kHz

## Protected V7 behavior

Future work must preserve:

- 227-word narration alignment provenance used by this review.
- 96 separated object layers.
- 49 Story beats.
- 21 narration-locked text cues.
- progressive audio/content-triggered object reveal.
- independent character/primary/support/family-secondary animation rather than rigid whole-scene motion.
- authored/source resting geometry.
- dynamic text placement based on actual scene free space.

## Known next maintenance target

The accepted V7 review still has a strict-alpha caveat: transient Pass2-family visible collision events were found by `collision_audit_v7.py`. The next maintenance pass should remove those collisions **without** regressing the V7 object/audio synchronization, animation richness, authored resting geometry, or dynamic text placement.

The frozen scripts intentionally retain their original `/mnt/data/...` acceptance-runtime paths. They are exact evidence/reference code. Migrating this behavior into parameterized core `app/` services is the next productization step, and that migration must be compared against this checkpoint before replacement.
