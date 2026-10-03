# Sprint 4.1 closure certification

Date: 2026-10-03

## Source identity

- Branch: `montage`
- Pushed Sprint 4.1 start HEAD: `0eb3e052485a919f2d3882f4718b6f1d2fc50ee4`
- Parent reviewed in full: `e0c4636c9883ca0e654dba84078af1635ebf15c4`
- Certification covers the start HEAD plus the narrow closure changes in the single
  Sprint 4.1 closure commit: public Story character-classification reuse, UTF-8 media
  probe hardening, regressions, and this record.

## Code review

- Choreography no longer calls Story's private `_authored_character_assets` helper.
  The unchanged classifier is exposed as
  `SemanticAssetBinder.authored_character_assets` and reused by Story and Choreography.
- `CONNECTABLE_RELATIONS` was compared with the authored relation vocabulary of all
  seven acceptance packages and Insider Threat. It remains a semantic directional
  flow/cause allowlist. Descriptive, containment, persistence, comparison, identity,
  and state relations remain non-connectable; no package-specific relation was added.
- Composition final geometry remains unchanged. Every encoded emphasis/de-emphasis
  segment begins and ends at identity (`dx=0`, `dy=0`, `scale=1`).
- A production Hacktivist run exposed Windows locale decoding of Arabic ffprobe/ffmpeg
  metadata. Final-media subprocess decoding is now explicit and deterministic; the
  media contract and verification thresholds are unchanged.

## Production evidence

Retained locally under `.hexa/sprint-4.1-certification/`:

- final H.264/AAC MP4s in `outputs/`;
- exact render plans, semantic carrier audits, encoded-motion reports, and contact
  sheets in `work/`;
- representative before/peak/settled and connector review sheets in `manual-review/`;
- machine-readable hashes and verifier results in `certification-audit.json`.

Every output passed forced alignment, the full production pipeline,
`EncodedMotionVerifier`, `FinalMediaVerifier`, full decode, H.264/AAC and CFR 30/1
checks. No white flash, malformed output, hidden authored content, or Composition
geometry regression was found.

| Package | Focus | Scale | Support de-emphasis | Abstained | Visual review |
|---|---:|---:|---:|---:|---|
| Black Hat | 27 | 3 | 4 | 20 | PASS |
| Gray Hat | 28 | 0 | 6 | 22 | PASS |
| Hacktivist | 28 | 0 | 3 | 25 | PASS |
| Script Kiddie | 28 | 4 | 3 | 21 | PASS |
| Social Engineer | 37 | 0 | 6 | 31 | PASS |
| State-Linked Group | 42 | 6 | 16 | 20 | PASS |
| White Hat | 29 | 3 | 7 | 19 | PASS |
| **Seven-package total** | **219** | **16** | **45** | **158** | **PASS** |
| Insider Threat regression | 38 | 16 | 3 | 19 | PASS |
| **Including Insider** | **257** | **32** | **48** | **177** | **PASS** |

Manual review confirmed restrained focus, no zoom-pulse appearance, no supporting
element pop, active participants protected from de-emphasis, exact settled geometry,
clean unobstructed connectors, no crowding regression, and improved semantic
readability for all seven acceptance outputs. Abstentions were preserved where motion
would be unsafe or visually worse.

## Regression gates

The closure tree passed:

- `python -m compileall -q app`
- `ruff check app tests`
- `pytest tests/test1`
- `pytest tests/test2`
- `pytest tests/test3`
- `pytest tests/certification`
- `pytest tests/package_holdouts`
- `pytest tests/visual/test_sprint_4_1_semantic_choreography.py`

Sprint 4.1 is closed. Sprint 4.2 was not started.
