# HEXA StoryEngine — Visual Storytelling Sprint Tracker

**Working branch:** `feature/storytelling-sprints` (one branch for ALL six sprints).
**Base snapshot:** `montage` at `624a032c706c6c364b2a2795d67101de15b7ed10` (includes causal-overlap fix).
**Protected branches:** `montage`, `bayer`. Never change, reset, force-push, or merge them.
**Current sprint:** S01 — Cross-scene continuity.
**Allowed statuses:** TODO / IN_PROGRESS / VERIFIED / BLOCKED. A sprint is VERIFIED only after required checks pass; report encoding gaps honestly.

| ID | Sprint | Status | Implementation commit | Tests / A-B evidence |
| --- | --- | --- | --- | --- |
| S01 | Authored cross-scene referent and object continuity | TODO | — | — |
| S02 | Safe four-direction ENTRY / EXIT with semantic lifetime | TODO | — | — |
| S03 | Causal source → action → reaction → result visual interactions | TODO | — | — |
| S04 | Hook selection + primary attention + ordered focus handoff | TODO | — | — |
| S05 | Narration-synchronized visual rhythm, rests, and readable holds | TODO | — | — |
| S06 | Verify/improve existing motion blur and payoff in encoded output | TODO | — | — |

## Delivery protocol

1. Before editing, verify the checked-out branch and working tree; if needed, work in an isolated worktree. Never discard local changes.
2. Read this file plus only relevant code/tests. Implement **one sprint per Codex session**, starting with the first TODO; do not start the next sprint in the same session.
3. Each sprint must change real production behavior (not metadata only), add regression tests, and preserve previous verified sprint behavior.
4. Run targeted tests, then affected legacy/visual suites; check 16:9 and 9:16, frame/audio timing, FFmpeg render and encoded frames when fixtures/media are available. Never claim real-package certification without real media.
5. Record changed files, commit SHA, exact test commands/results, measured before/after behavior and blockers in the corresponding table row. Update status to VERIFIED only if its defined gate passes. Commit and push exclusively to the working branch.
6. Do not modify the Unified Final Package 2.0 schema, fabricate visual semantics, weaken validators, or silently drop causal constraints.
7. Keep the first 10 seconds of a Black Hat reference package as a useful A/B evaluation when the package and audio are actually available; do not hard-code any content-specific behavior.
8. Avoid long prose, blanket codebase dumps, repeated discovery, parallel engines, and artificial movement. Focus on visible narrative improvement.

## Sprint-specific gates

- **S01:** authored referent can persist across adjacent scenes without unwanted disappearance/re-entry; unrelated assets remain separate; boundary safety and text placement hold.
- **S02:** LEFT / RIGHT / TOP / BOTTOM entrance and exit are feasible and tested; selection is contextual; short scenes safely abstain; semantic lifetime and causal-overlap guarantees remain intact; no blank frames.
- **S03:** authored relations yield readable direction of action/reaction/result when renderable; preserve Story event ordering; abstain without evidence.
- **S04:** opening hooks are selected only from authored curiosity/action/contrast/consequence/progressive reveal/continuity evidence; one primary attention target; avoid generic zoom or invented drama.
- **S05:** semantic motion aligns to speech without changing audio timing; resulting frame has adequate readable hold; no competitive simultaneous accents.
- **S06:** inspect and reuse current blur/payoff code; ensure encoded effect is perceptible where warranted, stays comfortable, and has no major render-time regression; do not duplicate effect passes.

**Definition of done:** For each sprint, compare identical inputs baseline vs candidate, show a clear benefit in eligible scenes, enumerate justified abstentions, pass code and integration checks, provide encoded A/B proof if media is available, and declare remaining limitations explicitly.
