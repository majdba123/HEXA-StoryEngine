# 2026-10-21: idea spread (longer-held pictures inside one idea)

User review: the videos feel too fast and are hard to follow. Measured cause: every Final
Package scene (one per ~2.3 s) fills the whole frame, and its last element lands on the
sentence's last word, so the next scene replaces the picture almost as soon as it is
complete. The idea board (2026-10-21) already keeps old elements until a new one lands on
their spot, but every scene reuses the same spots (character on one side, objects on the
other), so the old picture was gone within a few frames.

## What changed

When the next scene continues the same idea (the idea-board rule: a scene change inside one
sentence, or a sentence that opens with a connective while the idea is younger than 3.5 s;
shared as `app/shared/narration.py` `idea_links`):

- the current picture **glides as one block into the right half** of the frame over 10
  frames from the next scene's first frame (reference G3/G4: a held element relocates to
  make room), and stays complete there until the next picture ends;
- the next scene is **built in the left half** (Arabic reads right to left: the earlier
  picture sits on the right);
- along a longer chain the halves alternate: the third picture takes the right half the
  first one has just left; only the first picture of a chain glides.

A half is a rigid, uniform scale of the staged scene (relations, order, z and aspect are
kept). A scene that would be smaller than 0.4× in its half stays full frame and the chain
restarts there. Narration, Story and every reveal instant are unchanged: nothing appears
earlier or later. A new topic still clears the screen (no blended scenes).

| Owner | Change | Switch |
| --- | --- | --- |
| Composition | `app/composition/idea_spread.py`: chains, half layouts, `CompositionBeat.idea_spread`, the held picture per joining beat | `IDEA_SPREAD` (also off when `IDEA_BOARD` or `SCENE_WHIP` is off; off at safe levels 1 and 2) |
| Boundary | a joining picture always gets the board (a planned free overlap becomes the board); the held picture is never evicted by an arrival, a keyword or the unit cap; its glide is planned on the exits (`glide_start/end/scale/x/y`); a gliding picture leaves its words behind | `app/boundary/release.py` |
| Text | words are placed against the held picture too (within the overlap the text contract allows on any artwork) | `app/composition/text.py` `held_items` |
| Motion | no idea-climax wash on a picture that is held beside the next one (its idea has not ended) | `app/motion/resolution.py` |
| Renderer / Premiere | the held picture's glide (scale + centre, smoothstep); the Premiere capture gets the same expressions | `app/render/renderer.py` |
| Reels | the glide and the hold geometry are projected with the picture | `app/targets/projection.py` |

## Measurements

Reading time = how long a whole picture is on screen and complete: from its last element's
arrival (entry settle, long travels capped at 0.5 s) to the first planned exit of any of its
elements. Plan-only probe on the 4 cached packages (scratchpad `tools/reading.py`), baseline
montage 826e2597 (`b0`) vs this branch (`s3`). Pre-encode QA: 0 violations on every package
and both targets in both runs. Words placed: unchanged (35 / 32 / 43 / 37).

| Package | Reading median | Pictures < 1 s | Pictures ≥ 2 s | Screen clears | Pictures in a half |
| --- | --- | --- | --- | --- | --- |
| Black Hat | 0.69 → 1.61 s | 33 → 15 of 40 | 0 → 15 | 24 → 18 | 23 of 40 (scale median 0.48) |
| White Hat | 0.57 → 1.77 s | 33 → 11 of 40 | 1 → 17 | 19 → 15 | 25 of 40 (0.48) |
| Gray Hat | 0.58 → 1.81 s | 36 → 15 of 42 | 0 → 19 | 27 → 17 | 24 of 42 (0.52) |
| Script Kiddie | 0.67 → 1.59 s | 35 → 16 of 40 | 0 → 17 | 24 → 17 | 22 of 40 (0.49) |

Each element's own time on screen after it has arrived (arrival to its first exit): median
1.28 / 1.39 / 1.27 / 1.40 s → 1.97 / 2.66 / 2.37 / 2.36 s; elements on screen under 1 s
60/167, 35/135, 60/153, 61/147 → 27, 14, 29, 31.

Composition and Boundary agree on every spread except 3 of 94 (a picture with an event
wash keeps its own exit; the next picture then sits in its half alone).

## Limits (for the user's decision)

- **Size.** A picture in a half is drawn at about half its size (0.45–0.53×): the packages'
  scenes span the whole width (a character on one side, objects on the other), so a half
  cannot hold them larger without redesigning the scene. Pictures that do not continue an
  idea keep their full size, and the first picture of a chain is full size until the glide.
- **Reels.** Reels is a letterboxed projection of the 16:9 plan, so the halves are small
  there. Stacking the two halves vertically in the free Reels space is a possible follow-up.
- Pictures before a new topic (a clear) are unchanged: their reading time still ends with
  their sentence.
