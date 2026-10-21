# 2026-10-21: variety (sound effects, music bed, entry gestures, keywords)

User review: the effects were "fixed and repeated" and gave a bad feel. The user wants several designs per rule chosen at random, background music in more than one style, and visual effects that do not repeat and never get annoying. Everything stays general for every Final Package and must never stop a render.

## What changed

| Area | Before | Now | Owner (switch) |
| --- | --- | --- | --- |
| Sound effects | one design per kind (whoosh, swish, pop, tick, swell); ~6 effects per 10 s; 13–14 swishes per video | six designs per kind, played in a seeded shuffled rotation (every design before any repeat, never twice in a row), ±5 % pitch and ±1.5 dB per play; tonal designs tuned to the music's key; one sound per transition, per-kind spacing (swish 3 s, tick 2 s, swell 2 s), at most 6 effects in any 10 s; pops pan toward where their picture lands | `app/final/sound.py` (`SOUND_EFFECTS`) |
| Music | none | a procedural bed (numpy only, no samples or licences) in six styles: ambient pad, tech pulse, investigation, light groove, cinematic build, warm keys. The style, key, tempo and progressions come from the story (a re-render is identical, different videos differ). The arrangement changes at every character swap, never at the same intensity twice in a row; a video of 60 s or more changes style once at the swap nearest its middle (2 s crossfade). The bed sits 15 dB under the speech level, ducks a further 8 dB under every word (side-chain from the narration) and carries a 1.5–4 kHz presence dip. It is exactly the narration's length, fades in and out, and a failure keeps the effects (`BACKGROUND_MUSIC_SKIPPED`) | `app/final/music.py` (`BACKGROUND_MUSIC`), `app/final/synth.py` |
| Object entries | 43–58 % of all entries were the same high-scale landing; 24–33 % of new moments repeated the previous gesture | four in-place landing styles: `high` (reference G19), `grow`, `soft`, `bloom`. The first landing of a video is `high`; after it a seeded weighted rotation never repeats the previous style, and elements revealed together share one style. All styles are scale-only within the 1.28× footprint the Boundary board reserves, and each passes the shared segment contract, falling back through the other styles | `app/motion/landing.py` (`LANDING_VARIETY`) |
| Keywords | every keyword entered with the same diagonal slide | three directions (`slide`, `rise`, `side`) in a seeded rotation, never twice in a row; words appearing together share one direction. Every path stays inside the excursion `_safe_text_geometry` reserves, so boxes, anchors and rest positions are unchanged | `app/motion/text.py` (`TEXT_ENTRY_VARIETY`), `app/render/text.py` `_entry_gesture` |
| Premiere | A1 narration, A2 effects | A1 narration, A2 effects, A3 music (already ducked) | `app/final/premiere.py` |

Narration timing, Story instants, layout, text boxes and every QA contract are unchanged. Each feature is a module switch, and turning it off restores the previous behaviour exactly.

## Measurements (4 cached real packages)

Pre-encode QA: 0 violations on every package and both targets (probe run var2).

| Package | Same entry as the previous moment (before → now) | Most common entry share | Keywords repeating the previous direction | Effects (before → now) | Music |
| --- | --- | --- | --- | --- | --- |
| Black Hat | 24 % → 6 % | 43 % → 25 % | 34/34 → 0/34 | 63 → 49 | ambient pad → cinematic build |
| White Hat | 25 % → 3 % | 47 % → 16 % | 31/31 → 0/31 | 56 → 50 | warm keys → ambient pad |
| Gray Hat | 33 % → 0 % | 58 % → 24 % | 42/42 → 0/42 | 67 → 51 | cinematic build → tech pulse |
| Script Kiddie | 26 % → 3 % | 48 % → 24 % | 36/36 → 0/36 | 57 → 46 | cinematic build → ambient pad |

Landing styles (high / grow / soft / bloom): Black Hat 27/19/16/10, White Hat 17/18/14/15, Gray Hat 29/21/22/17, Script Kiddie 21/19/17/13.

Audio: the music adds ~4 s and ~380 MB peak memory per target; nothing reaches above 8 kHz in the music (soft top) and the effects carry no aliasing.

Listening demos (every style, every effect design) and two 32 s review clips: `E:\HEXA_Exports\_review_variety`.

## Not changed (and why)

- **Blur.** Motion blur on whips and fast travel, and the background blur of the grey wash, stay. They come from the references and read as speed and focus. Specific moments the user points at can be tuned.
- **Pacing structure** (fewer, longer pictures). Reading time under 1 s on more than half of the pictures comes from how the packages are cut (a new picture every ~2 s). Changing that is a structural planning change with its own risk, so it is left for its own task.
- **A drawn underline under keywords.** It was considered and left out: the text layout reserves no space under the ink, so an underline could touch artwork without a matching layout change.

## Tests

- `tests/test2/final/test_sound_variety.py`:
  - all 30 effect designs are clean, deterministic and really different;
  - the rotation never repeats back to back;
  - restraint: density, spacing, one sound per transition;
  - pan;
  - music: reproducible, varies across stories, arrangement changes at swaps, two chapters on long videos, every style clean;
  - ducking and level under the voice;
  - full mix length;
  - music failure keeps the effects;
  - the switch;
  - stems.
- `tests/visual/test_entry_variety.py`:
  - landing rotation;
  - footprint and contract for every style;
  - groups share one style;
  - reproducible per story;
  - switch off keeps `high`;
  - keyword rotation, excursion bounds and the rendered `\move` tag.
- `tests/test2/final/test_premiere_export.py`: the A3 music track.
