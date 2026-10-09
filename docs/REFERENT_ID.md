# `referent_id` — authored cross-scene referent identity

Final Package 2.0 additive field (Roadmap V2 Sprint 7A). Optional on every object.

## What it is

`referent_id` is an opaque, authored identifier. Two objects carrying the **same** `referent_id` — in any two scenes, adjacent or not — are asserted by the author to depict **the same semantic referent**: the same person, the same object instance, the same organisation, the same group.

```json
{ "scene_id": "SCENE_010", "asset_id": "ASSET_031", "referent_id": "REF_HACKER_01", "...": "..." }
{ "scene_id": "SCENE_011", "asset_id": "ASSET_047", "referent_id": "REF_HACKER_01", "...": "..." }
```

`ASSET_031` and `ASSET_047` are different objects and usually different artwork; they show the same authored hacker.

## What it is not

* **Not a motion or visual instruction.** It answers *who/what*, never *how*. It does not request persistence, inherited position, a transition, a fade or a morph. A later runtime decides whether identity can safely become visual continuity.
* **Not `unit_id`.** `unit_id` is a scene-local semantic slot (`UNIT_001` recurs in every scene with different referents).
* **Not `source_asset_id`.** `source_asset_id` is a source/library/template key (`hexa_presenter`, `security_researcher`). Equal keys never prove the same referent.
* **Not `asset_id`.** `asset_id` is package object identity and is unique per package.
* **Not `continuity.target_asset_id`.** That target stays inside its own scene; `PERSIST` and `TRANSFORM_TO` keep their existing meaning.
* **Never inferred.** The engine never derives it from names, roles, keys, images, scene order or models. Missing means *not authored*.

## Format

`[A-Za-z0-9][A-Za-z0-9._:-]{0,127}` — ASCII, no whitespace, 1–128 characters, compared byte-for-byte. No trimming or case folding: `REF_A` and `ref_a` are two referents. `null` or an absent key is valid. Anything else fails package loading (`invalid referent_id: SCENE:ASSET`).

Examples: `REF_HACKER_01`, `PERSON:ALICE`, `DEVICE_LAPTOP_03`, `ORG.COMPANY.A`.

## When to reuse an id

Reuse only when the script/authoring makes the referent literally continue:

* «the attacker enters the account» → «then **he** steals the data», drawn as that attacker: same id.
* The victim's laptop in scene 3 and **the same** laptop being wiped in scene 7: same id (non-adjacent recurrence is valid).
* A before/after comparison **of the same object** («the server before and after the patch»): same id.

## When not to

| Situation | Rule |
|---|---|
| Same word, different individual («a hacker» … «another hacker») | different ids or `null` |
| Generic class vs a specific instance («hackers often…» → «one attacker named X…») | different ids unless the script establishes the instance *is* the earlier referent |
| Individual vs group (`REF_ATTACKER_01` vs `REF_ATTACKER_GROUP`) | different ids; a group keeps one id only while it is the same group |
| Two entities shown for comparison (white-hat vs black-hat) | different ids |
| Concept icon vs a concrete instance (generic password icon vs *the victim's* password) | different ids or `null` |
| Same library key, colour, role, icon style or image | never by itself a reason to share an id |
| Unsure | `null` |

## One carrier per scene

Within one scene, a `referent_id` resolves to at most one carrier. Put it on the **root/primary** object of a character. Several objects may share it in one scene only when they form one authored compound: exactly one root among them and every other one descending from it through `parent_asset_id`. Two independent objects (or siblings under an unshared parent) with the same id in one scene fail closed: `ambiguous referent carriers in scene: SCENE:REF:ASSETS`. The engine never picks one.

```json
[
  { "asset_id": "S04_HACKER",     "referent_id": "REF_HACKER_01", "parent_asset_id": null },
  { "asset_id": "S04_HACKER_ARM", "referent_id": "REF_HACKER_01", "parent_asset_id": "S04_HACKER" }
]
```

## Compatibility

Every existing Final Package 2.0 remains valid without the field; `contract_version` stays `2.0`. Packages are never migrated automatically. `tools/audit_referents.py PACKAGE…` reports authored referents, adjacent-scene candidates, non-adjacent recurrences and compound carriers without inferring anything. The canonical package exposes `CanonicalAsset.referent_id`; no planning layer consumes it yet, so it does not change any RenderPlan or video.
