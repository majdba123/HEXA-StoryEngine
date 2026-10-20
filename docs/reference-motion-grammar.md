# Reference Motion Grammar (measured)

Sources, analysed directly on 2026-10-19 (decoded frames, NCC tracking of the settled subject,
per-frame change profiles). Nothing here is taken from titles or general motion-design lore.

| Reference | Path | Stream |
| --- | --- | --- |
| A | `Desktop\content\Refrence\MainCharecter\hexacharecter\انحياز 2.mp4` | 854×480, 30 fps, 2380 frames, 79.33 s |
| B | `Desktop\content\Refrence\MainCharecter\hexacharecter\تأثير المتفرج2.mp4` | 854×480, 25 fps, 1823 frames, 72.92 s |

Both are white-canvas cutout explainers with one recurring character, keyword text and icons;
the same visual material class as HEXA. They define an editing language, not artwork or scenes.

## 1. Measured gestures (timecoded)

| # | Ref, time | Observed | Measured |
| --- | --- | --- | --- |
| G1 | B 0.24–0.70 s | Character enters from fully off-screen RIGHT, no fade, no scale | first visible offset 11.5 % W, then 98→79→64→50→38→30→22→15→9 px per frame (≈ 20 % of the remaining distance per frame): **ease-out**, ~12 frames, heavy blur on the first frames only |
| G2 | A 2.83–3.27 s | Light bulb rises from fully off-screen BOTTOM | 113→84→62→49→36→27→19→13→8 px (≥ 23.5 % H): ease-out, ~13 frames, no fade, no scale |
| G3 | A 2.44–2.80 s | Character relocates RIGHT for the next idea | 24.8 % W in ~11 frames; peak ≈ 1.2 W/s, mean ≈ 0.7 W/s; motion blur while fast |
| G4 | B 3.56–4.00 s | Scene change carried by the persistent character moving LEFT | 34 % W in 11 frames; 2-frame ease-in, long ease-out; peak ≈ 2.3 W/s, mean ≈ 0.77 W/s; heavy blur; the old ticket/arrow/result **fade out over ~7 frames at the same time**; no hard cut |
| G5 | B 2.12–2.40 s | Curved arrow **writes on** from the cause toward the result | ~8 frames of progressive stroke, then ~5 frames of hold before the result appears |
| G6 | B 2.60–2.76 s | Result ("NEW" reel) appears at the arrow tip | fade-in with a small growth over ~5 frames, then still |
| G7 | A 8.00–9.00 s | Supporting icons (checkmarks) **cascade** in | each fades in over 2–4 frames; a new one starts every ~2 frames (≈ 12 per second) |
| G8 | A 4.00–4.80 s, 11.6–12.4 s | Arrow + text label pointing at an idea | arrow draws, label fades in beside it |
| G9 | A 12.60–12.73 s | Previous scene clears | fades to white in ~3 frames, then the next build starts |
| G10 | A 12.73–13.07 s | Character with pointer enters diagonally from off-screen bottom-right | ~10 frames, blur on fast frames, ease-out |
| G11 | A 13.47–13.87 s | Badge rises from the bottom | ~7 frames with a vertical motion-blur smear, then crisp; its label fades in after it settles |
| G12 | A 1.6–2.3 s, B 0.8 s | Keyword text | appears word by word (fade ~3–4 frames), leaves with a ~4-frame fade before the next movement |
| G13 | A 0.0–1.5 s | Hook | horizontally scrolling row of topic badges (series teaser), hard cut to the first idea at 1.5 s |

Rhythm (per-frame change profile, ≥ 0.2 % pixels changing): B changes on 79 % of frames with a
median continuous motion run of 13 frames; only one still stretch longer than 1 s in 73 s. A
changes on 51 % of frames (its character art is animated on twos). HEXA v6 changes on 56 % with
a median motion run of 8 frames.

Not observed anywhere in either reference: held 1.07 icon pulses, sideways nudges, in-place
dips or post-settle pulses. Result emphasis is carried by **arrival, the drawn arrow, the grey
wash and the large keyword** (G5, G6, G14–G17), never by a pulse on an already visible element.

**Correction (2026-10-20).** The first version of this document also listed grey washes and
defocus pulls as "not observed". That was wrong: the short sequences sampled for it missed them.
A full-length, frame-by-frame review of both references (1 fps contact sheets of the whole
running time, then per-frame sheets of every device) shows they are among the most frequent tools.

## 1b. Full-length review (2026-10-20): the devices a viewer actually sees

| # | Ref, time | Observed | Measured |
| --- | --- | --- | --- |
| G14 | A 7.0 s, 47–50 s; B 20–23 s | Kinetic keyword typography | single words set at **12–27 % of the frame height**, white fill, dark outline, soft drop shadow; often the largest object on screen; words appear one by one |
| G15 | A 40.9–41.2 s, 46.9 s, 66 s | Visible motion blur | a fast element is smeared over about its own size for **3–5 frames** (it is unreadable on the first one), then crisp at rest |
| G16 | A 40.87–41.17 s; B 4.96–5.20 s | Scene whip instead of a cut | at the moment the new idea's first element appears, the **whole old scene leaves as one block in ~6 frames**, heavily smeared, travelling the same way as the arriving element; the new element arrives smeared from the opposite edge; ~8 frames in total, no hard cut |
| G17 | A 9–12 s, 17–25 s, 27–28 s, 32–40 s, 61–76 s; B 3 s, 18–23 s, 48–50 s | Keyword arrows | a short, **curved, bold, black hand-drawn arrow** ties almost every keyword to the element it names (or one element to another), drawn with the word, gone with it |
| G18 | A 26–28 s, 34–35 s, 62–65 s; B 8 s, 12–14 s, 27 s, 29–30 s, 38–40 s, 55–56 s | Grey wash + background defocus | when the key element arrives over a built scene, the backdrop turns light grey (≈ 205/255) and blurs within ~3 frames while the new element (and the presenter) stay crisp; one every **~5–10 s**; held until the scene changes |

Element scale: each reference frame carries one to three large subjects. HEXA's authored scene
layouts already fill ~90 % of the frame once complete (median union 0.93 W × 0.90 H, Black Hat),
so "high scale" is matched by large typography (G14) and by not shrinking subjects, not by
re-laying out the Final Package.

## 2. Reference → HEXA translation

| Behaviour | Function | HEXA owner | v6 deficiency (measured) | Change | Encoded acceptance |
| --- | --- | --- | --- | --- | --- |
| G1, G2, G10, G11 edge entry | announce a new element with energy, then rest | `motion/arrivals.py` slides, `timing.REFERENCE_SLIDE` | ≤ 0.12 W, smoothstep (slow start), ≤ 0.6 W/s; v6 encoded: 68/149 entries travel ≥ 40 px | C1: start off-frame (or as far as the window allows), **ease-out cubic**, mean speed ≤ 0.8 W/s (reference means 0.62–0.77 W/s) | tracked first visible offset ≥ 15 % W for edge assets; ≥ 60 % of travel in the first half; crisp final pose |
| G3, G4 relocation / transition | carry attention into the next idea without a cut | `boundary/release.py`, `motion/cross_scene.py` | 37/39 Black Hat boundaries are hard cuts | C2: outgoing artwork fades out over ~6 frames while the incoming opener enters (overlap allowed during the fade) | boundaries with a visible fade/handoff instead of a cut; incoming never before its reveal |
| G5, G6, G8 arrow + result | make cause → effect visible | `render/connection.py`, `choreography/interactions.py` | connectors are static geometry with an opacity reveal | C3: progressive write-on (~8 frames), result arrival after the stroke | stroke length grows over ≥ 6 frames; direction = authored relation |
| G6 result arrival | resolve the idea | `motion/resolution.py` | rare held hits; pops under fades | C4: result arrives (pop/slide) after its cause; pulse only where comfortable | tracked scale/position curve |
| blur on fast frames | sell speed, keep rest crisp | `motion/motion_blur.py` | blur exists but motions were too slow to smear | follows C1 speeds automatically (shutter 0.5, ≤ 0.06 W) | moving-subject smear on peak frames, none at rest |
| G7 cascade | build a set quickly | Story order + arrivals | multi-object reveals mostly fade in place | C1 travel applies to each; ordering stays Story-owned | per-asset tracked travel |
| G9 clear to white | reset between ideas | boundary release | hard cut | C2 (same as G4) | fade frames at boundary |

Hard limits that the references do not override: narration/Story reveal instants, authored final
geometry, family rigidity, collision/text safety, the P0 pre-encode and encoded QA. Every new
profile is a documented, tested contract (`app/motion/contract.py` evaluates it).

## 3. Rebuild R1 (2026-10-20): how each device is applied to every Final Package

| Device | Owner | Rule | Evidence on Black Hat v9 |
| --- | --- | --- | --- |
| G14 typography | `composition/text_director.py`, `text/metrics.py` | rungs 2.2–1.15 × the style size are tried first; the shared text/artwork contract accepts or rejects each; never wider than the safe area | 22/35 words above 1.0 ×, 11 at ≥ 1.9 × |
| G15 blur | `motion/motion_blur.py` | 360° shutter (1.3 for the dominant mover), smear ≤ 22 % of the height | entries visibly smeared over 4–5 frames |
| G16 whip | `boundary/release.py` (`SCENE_WHIP`) | every crisp change whose old scene has no continuity owner: one rigid block, 6 frames from the unchanged opener, under the incoming art, blurred | 33/39 boundaries |
| G17 keyword arrows | `render/connection.py`, `render/text.py` | from the placed word's ink box to the named asset's visible artwork; curved bows first; only on a clean route ≥ 90 px; shown with the word | 13 arrows |
| G18 wash | `motion/resolution.py` (icon pulse off) | existing fail-closed wash rules, spacing 5 s | 7 washes |
| no in-place gestures | `motion/stillness.py`, `motion/hero_travel.py` | post-settle pulses off; every out-and-back accent becomes a deliberate still segment (QA still rejects weak non-zero motion) | 34 → 0 micro gestures |

## 4. Rebuild R2 (2026-10-20, after the user reviewed v10): what the per-frame review corrected

The user's verdict on v10: arrows cut through drawings and pointed into them; the video felt
like "a rocket" (too much, messy, nothing understood); "high scale" never visible; the element
being talked about never pulsed. A per-frame review of the references showed three misreadings:

| # | Ref, time | Observed (per frame) | R2 rule |
| --- | --- | --- | --- |
| G19 | A 7.68–7.95 s (magnet), A 16.68–16.85 s (cross), B 30.60–30.84 s (coin bag) | **High-scale landing**: a named object appears in place, faint, ~1.25–1.3× its size and out of focus, then shrinks onto its size while it sharpens in ~8 frames; it never slides in from an edge. Characters are the ones that slide. | `motion/landing.py`: every entering non-character object lands (start 1.28×, ease-out, gaussian defocus 12 px → 0, opacity 0.3 → 1 in 5 frames); the start scale steps down when the shared contract demands; characters keep slides / hero travel |
| G9 (re-read) | A 12.5–12.6 s, B 35.2 s | Most idea changes **fade the old scene to white in 3–5 frames**; the smeared whip (A 41 s, B 5 s) carries a **character swap** | `boundary/release.py`: fade (5 frames, no smear) by default; whip only when a character leaves and a character opens the next scene |
| G17 (re-read) | A 16.4 s, A 61–63 s, B 21–23 s | Arrows are **short (5–12 % W)**, sit in the gap beside the word, never cross another drawing, point at its edge | `render/connection.py`: ≤ 14 % W, ≥ 70 px, bow ≤ 0.12, head stops 14 px before the alpha silhouette, every other drawing is an obstacle, drawn after the element settles and the word is read |
| focus | B 31.68–34.3 s | When the narration moves on, the previous focus recedes while the new element arrives crisp | grey wash (G18) where Story resolves an event; per-element recede left for later |
| pulse | user direction | The element the narrator names pulses on its word | `motion/spoken_pulse.py`: ~1.14 peak, 12 frames, only when the element is already on screen and settled (a first mention lands instead) |

Measured on the corpus (pre-encode QA 0/8): landings 72/64/89/70, fades 25/26/27/23, whips
8/12/10/13, keyword arrows (Black Hat) 10 of length 104–257 px, spoken pulses 4/1/4/1.

## 5. Element interaction (2026-10-20, user: "the elements must interact with each other")

References A 16.3–16.9 s (the arrow leaves the character, then the cross lands at its tip) and
A 60 s (gear → vault): when a relation between two elements is narrated, the cause acts, an arrow
carries the relation, and the effect appears or answers at the arrow's tip.

| Case (Final Package causal, directional relation) | What the viewer sees | Owner |
| --- | --- | --- |
| cause revealed before the effect (the usual order) | the cause pulses, a short arrow writes on toward the effect's place in the 8 frames before it appears, the effect lands (high scale) at the tip | `motion/interaction.py` schedule + pulse, `render/connection.relation_arrow_specs` |
| effect revealed first, or both together | once both have settled: the cause pulses, the arrow writes on, the effect pulses as the head arrives | same |
| touching pair / no clean route | no arrow; the pulses carry the relation | same |

Arrows run silhouette to silhouette (≤ 22 % of the width), never across a third drawing or a
keyword, and stay until the scene changes. Black Hat: 6 of 7 relations now draw an arrow
(v11: 1); cause pulses 6/7 (Black Hat), 4/13, 5/8, 3/6 (White Hat, Gray Hat, Script Kiddie).
Decoded: beat-005 chip pulses 11.07 s, arrow 11.13–11.30 s, money bag lands at the tip 11.33 s.


## 6. Idea boards and keyword hold (2026-10-21, after the frame review of Social Engineer v1)

Measured on both references at 3 fps (A 29.5–36.2 s burger idea, B 30.6–35.4 s money-bag
idea): one idea lasts 3–7 s and is built on one picture.
- An anchor comes first (a character pose or one large object).
- A new element arrives every 0.5–1 s, each landing beside it.
- The spoken keyword appears big under a short arrow and stays until the next keyword replaces it (1.3–2 s when words come quickly).
- An element only leaves when the focus moves; the newspaper lands where the character stood.
- The screen clears to white only when the idea changes.

Social Engineer v1, by contrast, showed a new picture every 2.1 s with every word gone after about 1 s. About half of all scene changes in the Final Packages happen inside one sentence (Social Engineer 22/49, Black Hat 22/39): the package splits one idea over two or three pictures.

| Device | What the viewer sees | Owner |
| --- | --- | --- |
| Idea board | at a scene change inside one sentence (the outgoing narration does not end with `. ! ? ؟ …`) nothing is cleared: each old element stays until a new element or keyword lands on its spot and fades 2 frames before it (fully before a word); untouched elements stay until the new picture is complete; at most 5 units share the screen. Authored positions only; nothing moves | `boundary/release.py` `_idea_board_exits` (`IDEA_BOARD`) |
| Keyword hold | a keyword stays until the next keyword or its scene end (≤ 4 s) instead of a ~1 s reading window | `text/timing/visibility.py` (`KEYWORD_HOLD_SECONDS`) |
| Keyword carry | inside a board, the keyword on screen at the cut stays in the next picture (no new entrance) until the next keyword or an arrival on it | `SceneBoundaryRelease.text_carry`, renderer `-text-carried.ass` |
| Never smaller | Text Composition tries the held window first; if holding would shrink or drop the word, it keeps the reading window for that word (`TextLayoutItem.visible_end`), which Text Motion follows | `composition/text.py`, `motion/text.py` |

A finished sentence keeps the plain fade to white; a character swap after a finished sentence keeps its whip.

Corpus (4 cached packages; pre-encode QA 0 everywhere):
- 15–21 boundaries per package become boards.
- 40–50 % of old elements outlive the new picture's first element.
- Words placed and median font scale are equal to montage.
- Keyword hold median goes from 1.0–1.14 s to 1.22–1.52 s (maximum 3–4 s); 4–8 words are carried per package.

Black Hat 0–28 s, rendered old vs new (encoded QA ok on both):
- At 18.4 s the old version shows a screen of fading ghosts; the new one keeps the thief's glove while the cards give way to files.
- «السيطرة» stays from 21.0 to 22.27 s while the devices build, where it used to vanish at 21.5 s.
