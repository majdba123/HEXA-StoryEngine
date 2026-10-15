# Cinematic VNext2 execution state (zero-regression execution)

Durable checkpoint for resuming this assignment. Large media, caches and evidence stay
outside Git (`E:\hexa-vnext2\`; golden evidence in `E:\hexa-vnext2\golden\` is never
overwritten by candidate output).

## Release safety

| Item | Value |
|---|---|
| Baseline `origin/montage` | `a436917d41085c1b3b6c908da9b2715d5db2f606` (v6 engine/report) |
| Rollback reference | local tag `vnext2-baseline-a436917` |
| `origin/bayer` | `72058e962588a296926dbbac7630e238d333aa0c` (protected, untouched) |
| `origin/majd` | `bb42383c74fd2770e9e6e2b8a66415fa45f616b6` (untouched; 4 unique `[ops]` runtime-bundle commits, see below) |
| Work branch | `cinematic/vnext2` (no upstream) in isolated worktree `E:\hexa-vnext2-wt` |
| Existing stash | `stash@{0}: On main: !!GitHub_Desktop<main>` (preserved) |
| VPS | untouched; no deployment in this assignment |

`majd` is 4 commits ahead of its merge base with `montage` (`4f0884c`):
`81d2320` Rebuild pinned alignment runtime, `cc3ea87` Build pinned semantic runtime bundle,
`0e1c010` Build torch-matched torchaudio runtime, `bb42383` Build Python 3.12 app runtime
wheels. They are not in `montage`; the branch is therefore NOT deleted.

## Phase 1 - golden baseline (recorded 2026-10-15, engine `a436917`)

Evidence: `E:\hexa-vnext2\golden\` (`golden-summary.json`, `inventory.json`, `gates\*.xml|log`,
`corpus\<PKG>\*`).

| Gate | Result |
|---|---|
| compileall / ruff / diff-check | PASS |
| full pytest | 10126 tests, 0 failures, 0 errors, 38 skipped (1645 s) |
| real-package certification A-D | 355 tests, 0 failures, 6 skipped (Level E needs `HEXA_REAL_PACKAGE_ENCODE=1`) |
| official package-holdout gate | 80/80 executed and passed, 0 skipped (`tests.package_holdouts.report require`) |
| 8-package planning | all 8 fingerprints identical to the v6 corpus (`E:\hexa-vnext\corpus-a6`), parity 0 |

Corpus inventory (`inventory.json`, SHA-256 of every ZIP and narration):

* Official fingerprinted (manifest `Bayer_Packages/unified_2_0_certified_corpus.json`): all 6
  found with matching SHA-256 (Black Hat, White Hat, Gray Hat, Script Kiddie, Hacktivist,
  State-Linked Group). Missing: none.
* Additional real packages: Insider Threat, Social Engineer (planning corpus), and two never
  used in development: **Bug Bounty Hunter** (50 scenes) and **Cybercrime Gangs** (70 scenes),
  used as unseen holdouts.
* Synthetic: `tests/package_holdouts` generator seeds (64 structural, 8 encoded, 4 full
  render, 3 opening coverage).

Reference style lock (`.hexa/vnext2/style_probe.py`, same instrument on both references
and on v6): moving entries 39-58 % of reference entries vs 26 % in v6; reference SCALE pops
start at 0.43-0.61 size and finish in 4-5 frames; reference SLIDEs travel 0.10-0.15 w with a
0.83-1.22 w/s peak; reference resolutions blur and grey-wash the backdrop while the new focus
stays crisp (11-15 % of frames, one wash per 7-17 s).

## Phase status

- [x] Phase 1 baseline and inventory
- [x] Phase 2 root causes of weak motion (see report)
- [~] Phase 3 entries/exits: `app/motion/arrivals.py` (edge SLIDE / reference POP), hero travel 1.25 w/s
- [~] Phase 4 focus/HIGH-SCALE: same-subject rule, secondary focus pulse
- [~] Phase 5 PAYOFF: `app/motion/resolution.py` + renderer backdrop wash (candidate B chosen over veil A)
- [~] Phase 6 text: read window from display start; machine-readable justification per withheld cue
- [ ] Phase 7 tests / differential harness
- [ ] Phase 8 renders v7
- [ ] Phase 9 all packages + holdouts encoded
- [ ] Phase 10 browser + desktop launcher
- [ ] Phase 11 promotion
- [ ] Phase 12 branch cleanup
- [ ] Phase 13 final report

## Resume

```
git -C E:/hexa-vnext2-wt status
cd E:/hexa-vnext2-wt && "<repo>/.venv/Scripts/python.exe" -m pytest tests/visual/test_vnext2_payoff_resolution.py tests/visual/test_vnext2_arrivals.py tests/test2/render/test_focus_wash_encoded.py
HEXA_CODE_ROOT=E:/hexa-vnext2-wt HEXA_REPLAN_STORY=1 python .hexa/visual-polish-vp3/diagnose.py E:/hexa-vnext2/candidates/<c> <PKGS> referents
```
