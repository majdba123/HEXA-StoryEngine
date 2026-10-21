# 2026-10-21: repair instead of stopping, focus staging, Premiere project

User direction (night of 2026-10-21):
- Quality checks must repair and continue; a render must never stop because of QA.
- Add a button that generates an editable Premiere file with layers.
- Everything lands on `montage`.

## Repair instead of stopping

Every repair is recorded: in the job diagnostics, and in the export manifest under `self_repairs` and each output's `warnings`. Each repair has a module switch; with the switch off, the old fail-closed contract applies, and tests pin it that way.

| Finding (old stop) | Repair now | Switch |
| --- | --- | --- |
| Forced alignment rejects the word mapping | Tokens are matched to aligner words by text and the misses are interpolated; if that is still unsafe (or the aligner is missing), timing comes from the audio's speech intervals and keywords keep their place (`transcription-repair.json`) | `ALIGNMENT_SALVAGE`, `ALIGNMENT_SPEECH_TIMING` |
| Carrier audits: authored content hidden, carrier unresolved or ambiguous | Hidden cutouts are shown with their unit sibling (else with the scene opener), and the audits run again; contested ownership with every contender visible is accepted. A split Pass2 family is completed before abstaining (Hacktivist SCENE_002) | `story/carrier_repair.py` `STORY_CARRIER_REPAIR` |
| An asset dropped from Story, an event without a proven carrier | The asset is added as scene support; the event is recorded as a warning | same |
| Pre-encode motion QA (`PRE_ENCODE_MOTION_CONTRACT_FAILED`) | The rejected gesture becomes still in every target (an ENTRY becomes an alpha reveal, a later accent a reference still; family followers too), then QA runs again (up to 3 rounds; the last round stills the whole cue) | `render/motion_repair.py` `PRE_ENCODE_REPAIR` |
| Planning of a target fails (any non-input stage failure) | Planned again on safe level 1 (no focus staging, idea climax or idea boards), then level 2 (also no scene whip, landing, interaction, spoken pulse or motion blur) | `shared/safe_mode.py` `SAFE_LEVELS` |
| A beat segment's FFmpeg encode fails | That segment is encoded again alone, then with the beat's motion still (no blur, no wash) | `render/renderer.py` `SEGMENT_RETRY` |
| Encoded motion QA after the render | Recorded as a warning: a gesture weaker than its contract already looks still on screen | `motion_repair.ENCODED_QA_WARN` |
| Final media (drift, white flash) | One re-mux; only a missing or unreadable stream still stops | `final/verification.py` `FINAL_MEDIA_REPAIR` |
| Panel job process crashes natively (memory) | Started once more in a fresh process with one render worker | `desktop/job_process.py` `CRASH_RETRY` |

Inputs and infrastructure still stop with their typed code, because no safer edit can fix them: missing export root, insufficient space, an unwritable workspace, a missing FFmpeg, cancellation.

## Premiere project ("توليد كملف بريمير")

`StoryEnginePipeline.generate_premiere` runs the same shared plan, target plans and self-repairs as the video. Instead of encoding, it writes `<root>/<PACKAGE>/vN/<PACKAGE>_<YOUTUBE|REELS>_PREMIERE.xml` with a `_media/` folder (FCP7 XML, xmeml 4; Premiere: File > Import). The capture runs in the job workspace so every path stays inside the Windows path limit.

- **Source of truth.** `FFmpegRenderer.capture_layers` runs the renderer's own segment authoring without encoding and records every drawn layer: position/scale expressions, visibility window, opacity clock, compositing order. A beat that cannot be authored is skipped and reported. If no beat at all can be authored, the export fails (`PREMIERE_EXPORT_FAILED`).
- **Clips.** Each cutout is its original PNG with Basic Motion Center/Scale and Opacity keyframes, sampled per frame and reduced (0.35 px / 0.05 % / 0.5 %). Keywords are transparent QuickTime Animation clips rendered from the same ASS documents; the copy uses `YCbCr Matrix: None`, because on RGBA canvases the TV matrix turns white into 235 grey. Arrows are their write-on frames. The wash is a tint clip with its opacity clock. V1 holds the white canvas, A1 the narration.
- **Stacking.** Within a beat, later layers sit on higher tracks. An element that continues unchanged into the next beat stays one clip.
- **Conventions.** Center is normalized to the sequence, with its origin at the centre and y pointing down, matching a real Premiere export. Scale is a percentage of the source pixels; keyframe `when` is clip-relative (`in` = 0).
- **Not representable** (documented in the project README): motion blur, the wash's background blur, landing defocus and the path write-on mask. Their timing survives as opacity.

Verification:
- `tests/support/premiere_check.py` composites frames from the XML alone and compares them with the encoded video: 0.5–5 mean absolute difference and 0.4–3 % of pixels off by more than 40 on Insider Threat (YouTube and Reels) and Hacktivist. The larger differences sit at whips (motion blur) and washes (background blur).
- End to end through the panel's job process: Hacktivist produced both projects in 7 minutes, 13 tracks and 372 clips, with no warnings.
- Not verified: an import in Premiere Pro itself (Premiere is not installed on this machine).

## Tests added

- `tests/test2/pipeline/test_self_repair.py`: motion repair on the real Black Hat PAYOFF that stopped job f96ba7e0, the recovery ladder, final media, segment retry. Strict twins for each.
- `tests/test2/final/test_premiere_export.py`: units, stacking, a frame match against a real render, a missing cutout, an unauthorable beat, nothing authored.
- Desktop: crash retry, crash retry switched off, the Premiere job in its own process, the button contract.
- Story: fail-closed carrier tests pinned to strict mode, each with its repair twin. Alignment: `test_alignment_timing_repair.py`.

## 31-package scan

Pending at the time of writing: see the commit that records it.
