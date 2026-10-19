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

Not observed in the sampled sequences: held 1.07 icon pulses, sideways nudges, grey scene washes,
defocus pulls. Result emphasis is carried by **arrival timing and placement** (G5→G6), not by a
pulse on an already visible icon.

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
