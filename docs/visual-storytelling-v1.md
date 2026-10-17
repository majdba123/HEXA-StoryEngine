# Visual Storytelling V1 — isolated feature branch

## Contract and baseline

This feature is intentionally isolated on `feature/visual-storytelling-v1`.
It adds `app/visual_storytelling/` and one opt-in call site in the existing
pipeline. No original Final Package files are rewritten or migrated.

* The existing Unified 2.0 `package.json` and `images/` remain authoritative.
* An optional root-level `visual_storytelling_v1.json` provides a strict addendum.
* `HEXA_VISUAL_STORYTELLING_V1=0` (default): the legacy pipeline is untouched.
* `HEXA_VISUAL_STORYTELLING_V1=1`: reference RenderPlan is passed to the addendum
  processor before vertical projection, preserving both-format parity.
* Invalid sidecar with feature enabled: explicit error, never silent fallback.
* Missing sidecar: old RenderPlan unchanged; `ABSENT` diagnostics.

## What is implemented

The supplied 39-scene sidecar contains only 11 `RESULT_FOCUS` directives,
which must be grounded in the corresponding scene's semantic event and
`result_asset_ids`. The parser does not accept arbitrary actions or commands.
Phase one is deliberately conservative: it raises an already-authorized
reference-wash background tint alpha by 0.04 (maximum 0.48), making an existing
resolved result more prominent without moving elements or changing audio timing,
geometry, text, events, focus ownership or scene boundaries. If the existing
renderer found no safe focus wash for that event, it ABSTAINS and logs the reason.
The phase-one implementation **does not** manufacture interaction animation,
retime Story, or improve every directive. This is not full Visual Storytelling
certification.

Diagnostics: `<workspace>/reference/diagnostics/visual-storytelling-v1.json`
or the single-target workspace. Includes applied and abstained counts.
The source ZIP and original package JSON are never modified.

## Local checks required before promotion

```powershell
python -m pytest tests/visual/test_visual_storytelling_v1.py -q
python -m pytest tests/test2 tests/visual tests/package_holdouts tests/web -q
python -m ruff check app/visual_storytelling tests/visual/test_visual_storytelling_v1.py
```

Then, on a disposable local feature-branch workspace, run the same valid 39-scene
package and narration with the feature off and on. Preserve separate exports and
run the encoded motion, final-media, dual-format semantic-parity, and visual QA
gates. Verify the addendum actually produces a visible change (`applied > 0`),
and inspect the affected beat with/without audio; if every directive abstains,
treat the phase-one effect as NOT proven and do not promote.

Also run legacy packages with feature off, check plan fingerprints or exact output
hash parity, and exercise upload V1/V2, authenticated jobs, resume, cancel and
download. Older `.hexa` evidence is not assumed to survive local cleanup.

The sandbox used to author this branch does not provide the Windows renderer and
narration media. **No full encoded render or real machine test is claimed here.**
No PR/merge/deploy to `montage` or `bayer` is authorized.
