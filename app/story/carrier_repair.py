"""Repair instead of stopping when a carrier audit finds authored content hidden.

The carrier audits (``SemanticCarrierAuditor``) prove that every required authored element
keeps a visible carrier and that no significant authored cutout is dropped. They used to
stop the render. A render that stops helps nobody (user direction 2026-10-21), and every
finding here has a safe visual answer: show the hidden cutout. It appears exactly when a
cutout already carrying the same authored unit appears (the rest of the same drawing),
else with the scene's first visible element. The audits then run again on the repaired
Story; whatever they still report is recorded, and only contested ownership between
cutouts that are now all visible is accepted as a warning. Every repair is logged.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.models import AssetActivation, SemanticEventProxy, StoryBeat
from app.story.windows import _WINDOW_EVIDENCE, StoryAssetActivation

STORY_CARRIER_REPAIR = True
# An event repaired onto a visible cutout uses the authority Motion and Choreography already
# treat as "an authored event carried by a cutout that also carries its unit".
EVENT_PROXY_AUTHORITY = "FINAL_PACKAGE_REUSED_CARRIER_PROXY"
_REPAIRABLE = frozenset({"UNRESOLVED", "HIDDEN", "AMBIGUOUS"})


def _abstained(row) -> bool:
    return (getattr(row, "activation_policy", None) == "SAFE_ABSTENTION"
            or getattr(row, "policy", None) in {"SAFE_ABSTENTION", "FALLBACK"})


def assets_to_reveal(carrier_records: list[dict[str, Any]],
                     hidden_records: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    """scene id -> {hidden runtime asset id: the authored unit it belongs to (or None)}."""
    reveal: dict[str, dict[str, str | None]] = defaultdict(dict)
    for row in carrier_records:
        if row.get("status") not in _REPAIRABLE:
            continue
        ids = row.get("candidate_hidden_asset_ids") or []
        if row.get("status") == "HIDDEN":
            ids = row.get("carrier_asset_ids") or ids
        for asset_id in ids:
            reveal[row["scene_id"]].setdefault(asset_id, row.get("semantic_asset_id"))
    for row in hidden_records:
        mapping = row.get("runtime_mapping") or {}
        reveal[row["scene_id"]].setdefault(row["runtime_asset_id"], mapping.get("semantic_unit_id"))
    return reveal


def _evidence(template: AssetActivation, rule: str) -> list[str]:
    """Repair markers plus the template's Story window payload, which Motion and Text read
    back from evidence once the activation crosses a base-typed container."""
    window = [line for line in template.evidence if line.startswith(_WINDOW_EVIDENCE)]
    return ["revealed_hidden_authored_cutout", rule, *window]


def _scene_start(base: AssetActivation | None, asset_id: str, unit_id: str | None, beat: StoryBeat) -> AssetActivation:
    """A visible activation on the beat's own window (the scene had nothing on screen)."""
    start, end = float(beat.start), max(float(beat.start), float(beat.end))
    settle = min(end, start + 0.4)
    peak = start + (settle - start) * 0.5  # a normal entry shape: the peak inside the window
    data = (base.model_dump() if base is not None else {"asset_id": asset_id})
    data.update({
        "asset_id": asset_id, "semantic_unit_id": unit_id or data.get("semantic_unit_id"),
        "spoken_start": beat.audio_start, "spoken_end": beat.audio_end, "policy": "GROUP",
        "confidence": max(float(data.get("confidence") or 0.0), 0.5), "source": "carrier_repair",
        "evidence": ["revealed_hidden_authored_cutout", "with_scene_start"],
        "phrase_start": start, "phrase_end": end, "reveal_start": start, "semantic_peak": peak,
        "settle_at": settle, "activation_policy": "INHERITED_WINDOW",
    })
    return StoryAssetActivation.model_validate(data).with_legacy_evidence()


def reveal_assets(beats: list[StoryBeat],
                  reveal: dict[str, dict[str, str | None]]) -> tuple[list[StoryBeat], list[dict[str, Any]]]:
    """Give every asset to reveal a visible activation: its unit sibling's window, else the
    scene opener's, else (nothing of the scene on screen) the scene's first beat. The
    revealed activation lives in the beat its window comes from."""
    by_scene: dict[str, list[int]] = defaultdict(list)
    for index, beat in enumerate(beats):
        by_scene[beat.scene_id].append(index)
    output = list(beats)
    repairs: list[dict[str, Any]] = []
    for scene_id, assets in reveal.items():
        positions = by_scene.get(scene_id, [])
        if not positions:
            continue
        visible = [(position, row) for position in positions for row in output[position].asset_activations
                   if not _abstained(row)]
        opener = min(visible, key=lambda pair: (
            pair[1].spoken_start if pair[1].spoken_start is not None else float("inf"), pair[1].asset_id),
            default=None)
        on_screen = {row.asset_id for _position, row in visible}
        for asset_id, unit_id in sorted(assets.items()):
            if asset_id in on_screen:
                continue  # already visible: its own (package) activation stays untouched
            base = next((row for p in positions for row in output[p].asset_activations if row.asset_id == asset_id),
                        None)
            sibling = next(((position, row) for position, row in visible
                            if unit_id and row.semantic_unit_id == unit_id and row.asset_id != asset_id), None)
            if sibling or opener:
                position, template = sibling or opener
                rule = "with_unit_sibling" if sibling else "with_scene_opener"
                update = {
                    "asset_id": asset_id, "semantic_unit_id": unit_id or template.semantic_unit_id,
                    "source": "carrier_repair", "evidence": _evidence(template, rule),
                }
                if not sibling:  # only the rest of the same drawing shares its sibling's event
                    update.update(semantic_event_id=None, semantic_event_roles=[], semantic_event_order=None,
                                  semantic_event_dependency_ids=[])
                revealed = template.model_copy(update=update)
                timing_from = template.asset_id
            else:
                position, rule = positions[0], "with_scene_start"
                revealed = _scene_start(base, asset_id, unit_id, output[position])
                timing_from = output[position].id
            for p in positions:  # one activation per asset in its scene
                rows = output[p].asset_activations
                if any(row.asset_id == asset_id for row in rows):
                    output[p] = output[p].model_copy(update={
                        "asset_activations": [row for row in rows if row.asset_id != asset_id]})
            output[position] = output[position].model_copy(update={
                "asset_activations": [*output[position].asset_activations, revealed]})
            repairs.append({"scene_id": scene_id, "asset_id": asset_id, "unit_id": unit_id,
                            "timing_from": timing_from, "rule": rule.removeprefix("with_")})
    return output, repairs


def carry_events(package, beats: list[StoryBeat],
                 missing: list[tuple[str, str]]) -> tuple[list[StoryBeat], list[tuple[str, str, str]]]:
    """Give each missing authored event to a visible, event-free activation of its leader,
    else a participant, else a result unit (earliest first). Returns the carried events."""
    events = {(scene.id, event.semantic_event_id): event for scene in package.scenes
              for event in scene.semantic_events if event.semantic_event_id}
    output = list(beats)
    carried: list[tuple[str, str, str]] = []
    for scene_id, event_id in missing:
        event = events.get((scene_id, event_id))
        if event is None:
            continue
        ranked = [(unit, role) for unit, role in (
            (event.visual_leader_asset_id, "LEADER"),
            *((unit, "PARTICIPANT") for unit in event.participant_asset_ids),
            *((unit, "RESULT") for unit in event.result_asset_ids)) if unit]
        order = event.sequence_order if (event.sequence_order or 0) >= 1 else None

        def visible_rows(unit_id: str):
            return ((position, index, row) for position, beat in enumerate(output) if beat.scene_id == scene_id
                    for index, row in enumerate(beat.asset_activations)
                    if row.semantic_unit_id == unit_id and not _abstained(row))

        # The event is carried as a Story event proxy on the visible cutout (the mechanism
        # Story uses when one rendered cutout carries an authored event), on that
        # activation's own window: Choreography and Motion read it like any carried event.
        found = next(((position, row, role) for unit_id, role in ranked
                      for position, _index, row in visible_rows(unit_id)), None)
        if found is None:
            continue
        position, row, role = found
        window = row if isinstance(row, StoryAssetActivation) else StoryAssetActivation.from_legacy(row)
        times = (window.reveal_start, window.semantic_peak, window.settle_at, row.spoken_start, row.spoken_end)
        if any(value is None for value in times) or float(window.settle_at) <= 0 or float(row.spoken_end) <= 0:
            continue
        span = event.script_span
        # Never before the spoken word: the event's window starts at the narration.
        reveal = max(float(row.spoken_start), float(window.reveal_start))
        peak = max(reveal, float(window.semantic_peak))
        settle = max(peak, float(window.settle_at), 1e-3)
        proxy = SemanticEventProxy(
            asset_id=row.asset_id, semantic_unit_id=row.semantic_unit_id or row.asset_id,
            semantic_event_id=event_id, semantic_event_order=order, semantic_event_roles=[role],
            trigger_text=(span.text if span and span.text else row.trigger_text) or event_id,
            trigger_char_start=int((span.global_char_start if span else None) or row.trigger_char_start or 0),
            trigger_char_end=int((span.global_char_end if span else None) or row.trigger_char_end or 1),
            spoken_start=float(row.spoken_start), spoken_end=float(row.spoken_end),
            reveal_start=reveal, semantic_peak=peak, settle_at=settle, confidence=0.5,
            authority=EVENT_PROXY_AUTHORITY,
            evidence=["carrier_repair", "event_carried_by_visible_unit"],
        )
        beat = output[position]
        renderable = {*beat.primary_asset_ids, *beat.support_asset_ids}
        output[position] = beat.model_copy(update={
            "semantic_event_proxies": [*beat.semantic_event_proxies, proxy],
            "support_asset_ids": (beat.support_asset_ids if row.asset_id in renderable
                                  else [*beat.support_asset_ids, row.asset_id]),
        })
        carried.append((scene_id, event_id, row.asset_id))
    return output, carried


# Findings that leave every involved cutout on screen: the authored content is visible, only
# the proof of which cutout owns the unit is missing. Recorded as warnings, never a stop.
_TOLERATED = {"AMBIGUOUS": None, "UNRESOLVED": "carrier_outside_authored_locator"}


def tolerable(record: dict[str, Any]) -> bool:
    """Contested ownership, or a carrier outside its authored locator, is acceptable once
    every involved cutout is on screen."""
    status = record.get("status")
    if status not in _TOLERATED or (_TOLERATED[status] and record.get("reason") != _TOLERATED[status]):
        return False
    visible = set(record.get("visible_scene_asset_ids") or [])
    involved = set(record.get("carrier_asset_ids") or []) | set(record.get("candidate_hidden_asset_ids") or [])
    return bool(involved) and involved <= visible
