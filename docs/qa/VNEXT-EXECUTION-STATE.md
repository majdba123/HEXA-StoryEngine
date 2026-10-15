# VNext execution state (Cinematic Quality VNext + Web UI integration)

Durable checkpoint for resuming this assignment. Large media and caches stay outside Git
(`E:\hexa-vnext\`, `E:\hexa-editorial\`, `E:\HEXA_Exports\`).

## Baseline (recorded 2026-10-15)

| Ref | SHA |
|---|---|
| `origin/montage` | `0304a6b68d359fecb84e62f434283845d0a90a4f` (v5 editorial baseline) |
| `origin/feature/web-ui` | `19dc1f103042c4ae9339a1f6b1fe7ac18c5ced8b` (based on `2477e83`) |
| `origin/bayer` | `72058e962588a296926dbbac7630e238d333aa0c` (never modified) |
| `origin/majd` | `bb42383c74fd2770e9e6e2b8a66415fa45f616b6` (never modified) |

Worktrees present at start: main repo (`montage`), `HEXA-StoryEngine-web-ui`
(`feature/web-ui`, clean), `HEXA-StoryEngine-baseline-diagnostic`, `%TEMP%/hexa-base`,
`E:/hexa-er-head` (8a13539 baseline), `E:/hexa-vp1-base-code` (prunable). None modified.

## Branch

`integration/web-cinematic-vnext` created from `origin/montage` (0304a6b), no upstream.
Web UI merged with `--no-ff` (merge commit `0b1b36e`); the merge is additive
(12 files, no engine file touched). `tests/web`: 7 passed.

## Reference evidence (generated, not reference data)

`.hexa/vnext/reference_probe.py` → `E:\hexa-vnext\ref\probe-*.json`

| Measure | انحياز 2 | تأثير المتفرج2 |
|---|---|---|
| post-settle pulse peak, median (p10–p90) | 1.065 (1.055–1.079), n=3 | 1.050 (1.034–1.076), n=22 |
| exits that are cuts | 76 % | 84 % |
| entries: slide / scale / opacity / near-instant | 31 / 26 / 11 / 31 % | 11 / 28 / 9 / 52 % |
| grey-wash transition frames | 15 % | 11 % |

## Phase status

- [x] Phase 1 forensic review (git state, web branch, references)
- [x] Phase 2 integration preparation (merge on isolated branch, web tests)
- [x] Phase 3 cinematic improvements
  - `app/motion/arrival.py` + `EntryArrivalPolicy` in the pipeline: entries arrive within
    13 frames instead of creeping across long Story windows (BH: 13 entries bounded);
    handoff validator accepts an opacity clock that ends inside the Story window.
  - `app/motion/hero_travel.py`: post-settle emphasis takes the strongest safe reference
    amplitude (8 % .. readable floor) and `fit_emphasis_to_text` trims/revokes it against
    composed text (BH mean 1.037 -> 1.07, encoded peaks 1.046-1.082).
  - `app/story/windows.py`: `_results_follow_their_cause` (B2 contained case; BH scene 21).
  - Text never before its Story subject (+3 frames); withheld when then unreadable
    (`app/text/timing/visibility.py`, `app/composition/text.py`, `app/motion/text.py`).
  - `app/composition/text_director.py`: readable label floor 0.68 within anchor reach.
  - `app/pipeline.py`: transaction revoke used `row.beat_id` on Story beats (latent crash).
- [x] Phase 4 Builder authority: `docs/BUILDER-VISUAL-AUTHORING-VNEXT.md`,
  `app/final_package/authoring_audit.py` -> `authoring-audit.json` per bundle.
- [x] Phase 5 tests: `tests/visual/test_vnext_*`, `tests/test2/final_package/test_authoring_audit.py`,
  `tests/web/test_web_security.py`.
- [x] Phase 6 encoded verification (v6 YouTube/Reels, holdouts Gray Hat and Script Kiddie)
- [x] Phase 7 web end-to-end (HEXA-WEB.bat, real ZIP+audio, v6 produced, cancel, restart)
- [x] Phase 8 promotion to `montage` (fast-forward push of this branch)
- [ ] Phase 9 `feature/web-ui` cleanup (after CI on the promoted SHA)
- [x] Phase 10 handoff: `docs/qa/VNEXT-FINAL-REPORT.md`, `docs/qa/vnext-acceptance.json`

## Evidence locations

`E:\hexa-vnext\` (corpus-a*/ plans, render/, review/, audit/, proof/, ref/).

## Next step

Verify GitHub CI on the promoted `montage` SHA, confirm PR #3 shows merged, then delete
the remote `feature/web-ui` branch (the local Codex worktree is left untouched).

## Resume commands

```
git -C "C:/Users/INTEL CENTER/Documents/GitHub/HEXA-StoryEngine" switch integration/web-cinematic-vnext
.venv/Scripts/python.exe -m pytest -q tests/web -p no:cacheprovider
```
