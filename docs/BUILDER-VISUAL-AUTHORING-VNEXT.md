# Builder visual authoring — VNext requirements (Final Package 2.0, backward compatible)

The StoryEngine renders what a Final Package authors. Some viewer-facing defects cannot be
repaired by the engine without inventing meaning, reordering authored sequences or moving
narration. This document states what the Builder must author so those scenes become
readable. No new field is required: every rule uses existing Final Package 2.0 fields.

The Builder source is not in this repository, so nothing here is implemented in the
Builder. The engine side is implemented as far as authority allows, and every package
export now carries `diagnostics/authoring-audit.json` (see §6) listing each finding with
its scene, assets and the exact correction.

Status vocabulary: `ENGINE_FIXED` (the engine now handles it), `BUILDER_SPEC_READY` (exact
authoring correction specified here), `BLOCKED_BY_MISSING_AUTHORING_SOURCE` (Builder code
unavailable to this repository).

---

## B1 — Several visuals ordered on one short final word · `BUILDER_SPEC_READY`

**Problem.** A `SEQUENTIAL_WITHIN_PHRASE` group binds N visuals to the same final word of a
scene (Black Hat scene 10: phone, laptop, camera on "أجهزة", 380 ms). The engine must keep
`sequence_order` and may not make the group simultaneous, so the last visual — often the
event leader — appears in the last ~200 ms and is cut before it can be read.

**Engine.** Removes optional motion first (VNext: entries arrive within 13 frames; optional
recedes and second payoff pulses yield to the read hold). It never reorders or merges.

**Builder rule.** Within one scene, the visual that carries the event's meaning must not be
the last of ≥ 2 sequential visuals bound to the scene's final spoken word. Do one of:

1. Make the semantic subject the event leader and bind it to its own earlier word:
   ```json
   {"semantic_event_id": "SCENE_010_EVENT_01", "visual_leader_asset_id": "SCENE_010_A01_device_controller"}
   ```
   and author the devices as `visual_focus: "SUPPORT"` participants.
2. Or bind the supporting visuals to earlier words (`script_span` over "السيطرة على") so
   only the leader is on the final word.
3. Or set the group's `animation_policy` to `SIMULTANEOUS_WITHIN_PHRASE` when the visuals
   are one idea ("the devices").

**Rejected.** Leader as the 3rd/4th sequential item on a final word shorter than
`0.30 s × items`.

## B2 — RESULT before its cause · `ENGINE_FIXED` (contained case) / `BUILDER_SPEC_READY`

**Engine (VNext).** When a RESULT's authored phrase starts before, and still contains, its
event leader's phrase ("وصل إلى حساب موظف" around "حساب موظف"), Story now reveals the
RESULT after the leader settles (or with it when time is short), inside its own phrase,
with its gesture length kept. A RESULT authored entirely before its leader (the narration
states the outcome first), or on the same words as its leader (sequence order decides), is
unchanged; so is a RESULT that would lose its read time.

**Builder rule.** Author causal chains in spoken order:

```json
{"semantic_event_id": "E1", "script_text": "وصل", "visual_leader_asset_id": "A02_login_gateway",
 "sequence_order": 1, "depends_on_event_ids": []}
{"semantic_event_id": "E2", "script_text": "حساب موظف", "visual_leader_asset_id": "A01_employee_badge",
 "sequence_order": 2, "depends_on_event_ids": ["E1"], "result_asset_ids": ["A03_access_key"]}
```

* `depends_on_event_ids` must point to events spoken earlier.
* A RESULT's `script_span` should cover its consequence words, not the whole sentence.
* Optional relation (`subject_asset_id` → `object_asset_id`, `result_asset_id`) lets the
  engine's INTERACT → REACT → PAYOFF primitives express the cause.

**Rejected.** A dependent event spoken before its prerequisite; a RESULT span that starts on
the first verb of the sentence when its cause is named later.

## B3 — Final result on the final word · `BUILDER_SPEC_READY`

**Problem.** The scene's result is bound to its last word and the scene cuts when the
sentence ends, so there is no legal time to rest (13 Black Hat scenes; 7 of them within one
frame of the requirement). The engine does not hold a finished scene over the next
sentence (that was the stale-picture defect fixed in v5).

**Builder rule.** Per scene, the last authored visual should be bound so that
`scene_audio_end − visual_word_start ≥ 0.30 s + 0.26 s` (entry minimum + read hold), i.e. to
the last content phrase, not only the last word. Where the narration itself is too short,
the narration/TTS should add ≥ 0.3 s pause after the scene's final word.

## B4 — Openings without a safe carrier · `BUILDER_SPEC_READY` (engine fails closed)

**Engine.** Every scene opening reveals its first visual from the first spoken word under
`BOUNDED_STORY_LEAD`, `SCENE_PRELUDE` or `AUTHORED_EVENT_SPOKEN`, never a RESULT, a dependent
event or a later event. When no safe carrier exists the scene opens on its first authored
trigger (13 of 368 corpus openings).

**Builder rule.** The earliest authored span of every scene must belong to a non-RESULT,
dependency-free visual of event order 1, and no unit/relation span may start before the
first event span (otherwise `SCENE_PRELUDE` cannot prove the opening words are unbound).

## B5 — Text anchor that appears late · `ENGINE_FIXED` (timing) / `BUILDER_SPEC_READY`

**Engine (VNext).** Text never appears before its own visual subject is recognizable (half
opaque, or half-way through a travel). It waits for the subject; when waiting would leave
less than its readable floor, the cue is withheld and recorded
(`anchor_not_recognizable_in_time`). Text wording and spoken timing are unchanged.

**Builder rule.** `text_anchor_asset_id` must be the first visual of its phrase (lowest
`sequence_order` among assets on the same span), or the label must be bound to the words
spoken when its anchor appears.

---

## 6. Authoring audit (engine diagnostics, non-blocking)

Every generated bundle writes `diagnostics/authoring-audit.json`:

| Code | Rule | Engine behaviour |
|---|---|---|
| `SEQUENTIAL_GROUP_ON_FINAL_WORD` | B1 | order kept; optional motion removed |
| `RESULT_BEFORE_LEADER_CONTAINED` | B2 | RESULT follows its cause |
| `RESULT_STATED_BEFORE_LEADER` | B2 | unchanged (authored order) |
| `DEPENDENT_EVENT_SPOKEN_FIRST` | B2 | unchanged; flagged |
| `FINAL_VISUAL_ON_FINAL_WORD` | B3 | read hold may be short; flagged |
| `OPENING_WITHOUT_SAFE_CARRIER` | B4 | fails closed |
| `TEXT_ANCHOR_LATE_IN_SEQUENCE` | B5 | text waits or is withheld |

Recommended Builder validator: run the same checks before export and refuse packages with
`DEPENDENT_EVENT_SPOKEN_FIRST`, `TEXT_ANCHOR_LATE_IN_SEQUENCE` or a leader that is not first on
a final-word sequence, unless a reviewer accepts them.

## 7. Backward compatibility

Existing packages load unchanged. All checks are warnings in the engine; nothing in a
package is rewritten. Engine-side rules (B2 contained case, B5 timing) only move a reveal or
a text later, never earlier, and never across scene boundaries.

## 8. Tests

* Unsafe openings fail closed: `tests/test2/story/test_scene_opening_establishment.py`.
* RESULT after cause and its exclusions: `tests/visual/test_vnext_emphasis_causality_text.py`.
* Text never before its subject: same file.
* Authoring audit findings: `tests/test2/final_package/test_authoring_audit.py`.
