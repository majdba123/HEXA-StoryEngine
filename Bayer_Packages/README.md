# Bayer Packages — Known Working Final Packages

This folder records the four historical Final Packages that the user reports successfully completed real production renders.

These packages are treated as **Golden Working Candidates** until the accompanying historical handoff is reviewed.

## Repository scope

- Branch: `montage`
- Baseline HEAD when this index was created: `fbcabc294b4d3ae8e94263890c91255d7e9ad51c`
- No production code is changed by this folder.
- The ZIP bytes were not committed by ChatGPT because the current GitHub connector cannot upload large local binary ZIP files directly. The SHA-256 fingerprints below identify the exact uploaded files unambiguously.

## Exact package fingerprints

| Package | ZIP bytes | ZIP entries | Scene PNGs | ZIP integrity | SHA-256 |
|---|---:|---:|---:|---|---|
| `HEXA_BLACK_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip` | 39,071,446 | 46 | 40 | PASS | `c2339d883b2a377ae32fd8c397408d0b33d03c5ff492fdd8f98d37b5c8e8dc15` |
| `HEXA_GRAY_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED.zip` | 40,603,724 | 41 | 35 | PASS | `a34e3578e780b7bef7101ad588dedce5a2a58b658a62348dd179bccb4879f2a0` |
| `HEXA_WHITE_HAT_HACKER_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED(3).zip` | 41,905,483 | 41 | 35 | PASS | `37304adf5cd8d9dfa35575ce5ec5eda9814485ef96983ed210e48e576f96dccf` |
| `HEXA_SCRIPT_KIDDIE_AR_HEXA_V20_FINAL_PACKAGE_1_2_CORRECTED(2).zip` | 51,293,390 | 41 | 35 | PASS | `ce50388a77c195de9769d274783f844d2493516a2f882dd12e621650c253bee4` |

## Common metadata present

Each inspected package contains the expected metadata family:

- `canonical_script.txt`
- `manifest.json`
- `scene_plan.json`
- `semantic_bindings.json`
- `semantic_validation_report.json`
- `validation_report.json`

The historical handoff must be reviewed before promoting these from **Golden Working Candidates** to the authoritative working-package policy.

## Certified Unified Final Package 2.0 corpus

Production accepts Unified Final Package 2.0 only. The six certified packages are
pinned by SHA-256 in `unified_2_0_certified_corpus.json`; ZIP bytes are not committed.

- Gray Hat, Script Kiddie and Hacktivist are the locator-repaired versions
  (`visual_locator` only; semantics, events, groups and relations unchanged). Every
  repaired locator is listed in `LOCATOR_REPAIR_REPORT.md`.
- The corpus is hosted as release assets of the PRIVATE repository
  `majdba123/HEXA-certified-corpus` (tag `unified-2.0-certified-corpus-2026-09-30`); no
  ZIP is published on this public repository.
- The `Real Package Certification` workflow reads the repository variable
  `HEXA_REAL_PACKAGE_CORPUS_URL` (the release API URL `.../releases/tags/<tag>`, or any
  base URL serving the six filenames) and the secret `HEXA_REAL_PACKAGE_CORPUS_TOKEN`
  (fine-grained token, read-only `Contents` on the corpus repository). It downloads the
  assets, verifies the SHA-256 values and runs Levels A-D with
  `HEXA_REQUIRE_REAL_PACKAGE_CORPUS=1`. A missing, partial or different corpus fails the
  job, as does any skipped test.
- Level E (full-length encode) runs only when the workflow is dispatched with
  `level_e=true`; otherwise its job reports `LEVEL E NOT EXECUTED`.
- Local check: `python -m tests.support.real_corpus verify <directory>`.