# Semantic Carrier Resolver — acceptance certification

- Suite: `tests/certification/semantic_carrier` — 1505 tests, 0 failures, 0 errors, 0 skipped
- Assignment matrices: 2040 (all compared with an exact optimum)
- Generated cases: 866 = 252 clean + 204 complex + 200 expected-failure + 210 mutation; 114 through RenderPlan
- Expected typed failures exercised: 277
- Determinism: 4080 assignment permutations, 456 shuffled resolutions, 1000 repeated executions

## Resolver scaling (one scene)

| intents | candidate cells | wall ms (median of 3) |
|---:|---:|---:|
| 1 | 1 | 0.32 |
| 5 | 25 | 1.53 |
| 10 | 100 | 5.57 |
| 25 | 625 | 15.01 |
| 50 | 2500 | 64.74 |
| 75 | 5625 | 139.49 |
| 100 | 10000 | 243.62 |
| 150 | 22500 | 545.07 |

## Real packages

```json
{
 "confidence_distribution": {
  "BLACK_HAT_HACKER": {
   "required": {
    "PROVEN": 94,
    "HIGH_CONFIDENCE": 18,
    "UNRESOLVED": 9,
    "INFERRED": 8
   },
   "optional": {},
   "kinds": {
    "EXCLUSIVE": 96,
    "GROUP": 11,
    "NONE": 9,
    "ORDER_HINT": 8,
    "ELIMINATION": 5
   },
   "audit": {
    "CARRIED": 120,
    "MERGED_VISIBLE": 9
   },
   "hidden_content": 0
  },
  "GRAY_HAT_HACKER": {
   "required": {
    "PROVEN": 93,
    "HIGH_CONFIDENCE": 18,
    "UNRESOLVED": 16,
    "INFERRED": 8
   },
   "optional": {},
   "kinds": {
    "EXCLUSIVE": 97,
    "GROUP": 9,
    "NONE": 16,
    "ORDER_HINT": 8,
    "ELIMINATION": 2,
    "SHARED": 3
   },
   "audit": {
    "CARRIED": 127,
    "MERGED_VISIBLE": 8
   },
   "hidden_content": 0
  },
  "HACKTIVIST": {
   "required": {
    "INFERRED": 46,
    "HIGH_CONFIDENCE": 12,
    "PROVEN": 4
   },
   "optional": {},
   "kinds": {
    "ORDER_HINT": 46,
    "SHARED": 5,
    "EXCLUSIVE": 4,
    "GROUP": 7
   },
   "audit": {
    "CARRIED": 62
   },
   "hidden_content": 0
  },
  "SCRIPT_KIDDIE": {
   "required": {
    "PROVEN": 53,
    "HIGH_CONFIDENCE": 27
   },
   "optional": {},
   "kinds": {
    "EXCLUSIVE": 52,
    "GROUP": 28
   },
   "audit": {
    "CARRIED": 80
   },
   "hidden_content": 0
  },
  "STATE_LINKED_GROUP": {
   "required": {
    "INFERRED": 102,
    "UNRESOLVED": 5,
    "PROVEN": 4
   },
   "optional": {},
   "kinds": {
    "ORDER_HINT": 102,
    "NONE": 5,
    "EXCLUSIVE": 4
   },
   "audit": {
    "CARRIED": 106,
    "MERGED_VISIBLE": 5
   },
   "hidden_content": 0
  },
  "WHITE_HAT_HACKER": {
   "required": {
    "PROVEN": 109,
    "UNRESOLVED": 24,
    "INFERRED": 6,
    "HIGH_CONFIDENCE": 6
   },
   "optional": {},
   "kinds": {
    "EXCLUSIVE": 109,
    "NONE": 24,
    "ORDER_HINT": 6,
    "ELIMINATION": 3,
    "SHARED": 1,
    "GROUP": 2
   },
   "audit": {
    "CARRIED": 124,
    "MERGED_VISIBLE": 21
   },
   "hidden_content": 0
  }
 },
 "gates": {
  "required_AMBIGUOUS": 0,
  "required_UNRESOLVED": 54,
  "required_AMBIGUOUS_gate_met": true,
  "required_UNRESOLVED_gate_met": false,
  "note": "Resolver-level confidence. Every one of these units is still CARRIED or MERGED_VISIBLE in the production carrier audit (event proxy / merged region), hidden_content = 0, and no package fails. They are units whose package carries no locator evidence the resolver may use; closing them needs authored locators."
 },
 "baseline_mapping_comparison": {
  "baseline": "pre-Sprint-3 mapping (scene-global resolver not yet in place)",
  "A_identical": "all units",
  "B_improved": 0,
  "C_regressed": 0,
  "differences": 0
 },
 "manual_audit": {
  "BLACK_HAT_HACKER": {
   "SCENE_016 clapper": "EXCLUSIVE / PROVEN 0.961",
   "SCENE_018 caution icon": "EXCLUSIVE / PROVEN 0.959",
   "SCENE_032": "corridor ELIMINATION / HIGH_CONFIDENCE; gateway ORDER_HINT / INFERRED"
  },
  "GRAY_HAT_HACKER": {
   "SCENE_020": "gray_hat SHARED asset-02; white_hat SHARED asset-01; missing_permission GROUP + shared; signed_permission EXCLUSIVE 0.61; key PROVEN",
   "SCENE_023": "footprints GROUP of 5; outside_key SHARED on house; bell and house PROVEN"
  },
  "SCRIPT_KIDDIE": "SCENE_014/023/027/032/035 groups owned, no unowned cutout",
  "HACKTIVIST": "SCENE_004/007/009/013/014 groups owned",
  "STATE_LINKED_GROUP": "SCENE_003/008/020/027 mostly ORDER_HINT / INFERRED, one UNRESOLVED participant in 003, 020 and 027; SCENE_014 fully PROVEN, one unowned cutout"
 },
 "levels": {
  "A_structural": "PASS 6/6",
  "B_semantic": "PASS 6/6",
  "C_D_planning": "PASS 6/6",
  "E_full_encode": "PASS 6/6 (workflow_dispatch level_e=true, run 36726414444)"
 }
}
```

## Findings

```json
[
 {
  "id": "F1",
  "layer": "assignment",
  "commit": "b8e984c",
  "defect": "a margin exactly equal to the 0.065 threshold was classified ambiguous because of binary float rounding",
  "fix": "inclusive boundary with _MARGIN_EPSILON = 1e-9",
  "regression_test": "test_margin_exactly_at_the_threshold_is_not_ambiguous"
 },
 {
  "id": "F2",
  "layer": "resolver",
  "commit": "b8e984c",
  "defect": "an unrelated decorative speck counted as an elimination candidate and blocked a valid locator-less elimination",
  "fix": "decorative cutouts are excluded from the elimination remainder",
  "regression_test": "test_decorative_speck_is_not_an_elimination_candidate"
 }
]
```

## Known risks

```json
[
 "54 required units in the certified corpus are UNRESOLVED at resolver level (Black 9, Gray 16, State-Linked 5, White 24); they render through proxy/merged carriers, not through an owned cutout.",
 "INFERRED order-hint ownership (170 required units, mostly State-Linked and Hacktivist) is not geometrically verified and can be wrong without a diagnostic.",
 "An under-segmented cutout whose event is already represented by other participants fails typed (SEMANTIC_CARRIER_UNRESOLVED) instead of using the SHARED carrier.",
 "A located optional decorative unit whose cutout is hidden fails AUTHORED_CONTENT_HIDDEN (Sprint 2 design).",
 "Certification uses a synthetic narration clock, not real audio alignment."
]
```

## Verdict

```json
{
 "status": "BLOCKED",
 "unmet_gates": [
  "UNRESOLVED required = 0 in the certified corpus"
 ],
 "met": "every other acceptance gate (algorithm, resolver, generated, mutation, determinism, performance, Levels A-E, CI)"
}
```
