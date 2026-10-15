"""Non-blocking audit of Final Package authoring that limits what the engine can show.

Each finding names the scene, the authored assets/events and the exact Builder-side
correction (docs/BUILDER-VISUAL-AUTHORING-VNEXT.md). The audit reads authored script spans
only; it never changes the package and never blocks generation.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.canonical import CanonicalPackage, CanonicalScene

_TRAILING = re.compile(r"[\s،؛؟.,;:!?\"'«»()\-]+$")
_SEQUENTIAL = "SEQUENTIAL"


@dataclass(frozen=True, slots=True)
class AuthoringFinding:
    code: str
    scene_id: str
    detail: str
    asset_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    engine_behaviour: str = ""
    builder_rule: str = ""

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["asset_ids"] = list(self.asset_ids)
        payload["event_ids"] = list(self.event_ids)
        return payload


def _span(record) -> tuple[int, int] | None:
    span = getattr(record, "script_span", None)
    if span is None:
        return None
    start, end = span.global_char_start, span.global_char_end
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end:
        return start, end
    return None


def _content_end(script: str, scene: CanonicalScene) -> int | None:
    if scene.script_char_end is None:
        return None
    text = script[: scene.script_char_end]
    return len(_TRAILING.sub("", text))


def _last_word_start(script: str, end: int) -> int:
    start = end
    while start > 0 and not script[start - 1].isspace():
        start -= 1
    return start


def audit_package(package: CanonicalPackage) -> list[AuthoringFinding]:
    script = package.script or ""
    findings: list[AuthoringFinding] = []
    for scene in package.scenes:
        units = {unit.asset_id: unit for unit in scene.units}
        spans = {asset_id: span for asset_id, unit in units.items() if (span := _span(unit))}
        events = {event.semantic_event_id: event for event in scene.semantic_events}
        event_spans = {event_id: span for event_id, event in events.items() if (span := _span(event))}
        end = _content_end(script, scene)
        roles: dict[str, set[str]] = {}
        for event in events.values():
            if event.visual_leader_asset_id:
                roles.setdefault(event.visual_leader_asset_id, set()).add("LEADER")
            for asset_id in event.result_asset_ids:
                roles.setdefault(asset_id, set()).add("RESULT")

        # B1 / B3: visuals on the scene's final word.
        if end is not None:
            on_final = [asset_id for asset_id, (left, right) in spans.items() if right >= end and left >= end - 24]
            groups = {}
            for asset_id in on_final:
                groups.setdefault(spans[asset_id], []).append(asset_id)
            for (left, right), members in groups.items():
                sequential = any(_SEQUENTIAL in str(group.animation_policy).upper()
                                 for group in scene.semantic_groups if set(members) & set(group.asset_ids))
                ordered = sorted(members, key=lambda a: (units[a].sequence_order or 0, a))
                if len(ordered) >= 2 and sequential:
                    last = ordered[-1]
                    findings.append(AuthoringFinding(
                        "SEQUENTIAL_GROUP_ON_FINAL_WORD", scene.id,
                        f"{len(ordered)} sequential visuals on the final words '{script[left:right]}'; "
                        f"last is {last}" + (" (event leader)" if "LEADER" in roles.get(last, set()) else ""),
                        asset_ids=tuple(ordered), engine_behaviour="order kept; optional motion removed",
                        builder_rule="B1"))
                elif len(ordered) == 1 and left >= _last_word_start(script, end):
                    findings.append(AuthoringFinding(
                        "FINAL_VISUAL_ON_FINAL_WORD", scene.id,
                        f"{ordered[0]} is bound to the final words '{script[left:right]}'",
                        asset_ids=tuple(ordered), engine_behaviour="read hold may be short",
                        builder_rule="B3"))

        # B2: RESULT before its leader; dependent event spoken before its prerequisite.
        for event_id, event in events.items():
            leader = event.visual_leader_asset_id
            if leader in spans:
                for result in event.result_asset_ids:
                    if result == leader or result not in spans:
                        continue
                    (r0, r1), (l0, _l1) = spans[result], spans[leader]
                    if r0 < l0:
                        contained = r0 < l0 < r1
                        findings.append(AuthoringFinding(
                            "RESULT_BEFORE_LEADER_CONTAINED" if contained else "RESULT_STATED_BEFORE_LEADER",
                            scene.id,
                            f"RESULT {result} '{script[r0:r1]}' starts before its leader {leader} "
                            f"'{script[l0:spans[leader][1]]}'",
                            asset_ids=(result, leader), event_ids=(event_id,),
                            engine_behaviour=("RESULT revealed after its cause" if contained
                                              else "authored order kept"),
                            builder_rule="B2"))
            for prerequisite in event.depends_on_event_ids:
                if event_id in event_spans and prerequisite in event_spans \
                        and event_spans[event_id][0] < event_spans[prerequisite][0]:
                    findings.append(AuthoringFinding(
                        "DEPENDENT_EVENT_SPOKEN_FIRST", scene.id,
                        f"{event_id} depends on {prerequisite} but is spoken first",
                        event_ids=(event_id, prerequisite), engine_behaviour="spoken order kept",
                        builder_rule="B2"))

        # B4: the earliest authored visual is not a safe opening carrier.
        if spans:
            first = min(left for left, _right in spans.values())
            cohort = sorted(asset_id for asset_id, (left, _r) in spans.items() if left == first)
            safe = []
            for asset_id in cohort:
                unit = units[asset_id]
                event = events.get(unit.semantic_event_id or "")
                unsafe = ("RESULT" in roles.get(asset_id, set()) or str(unit.visual_focus or "").upper() == "RESULT"
                          or (event is not None and (event.depends_on_event_ids
                                                      or (event.sequence_order not in (None, 1)))))
                if not unsafe:
                    safe.append(asset_id)
            if not safe:
                findings.append(AuthoringFinding(
                    "OPENING_WITHOUT_SAFE_CARRIER", scene.id,
                    "the scene's earliest authored visuals are RESULT, dependent or later-event visuals",
                    asset_ids=tuple(cohort), engine_behaviour="opening fails closed",
                    builder_rule="B4"))

        # B5: text anchor that is not the first visual of its own phrase.
        for event_id, event in events.items():
            anchor = event.text_anchor_asset_id
            if anchor not in spans:
                continue
            same = [asset_id for asset_id, span in spans.items() if span == spans[anchor]]
            earlier = [asset_id for asset_id in same
                       if (units[asset_id].sequence_order or 0) < (units[anchor].sequence_order or 0)]
            if earlier:
                findings.append(AuthoringFinding(
                    "TEXT_ANCHOR_LATE_IN_SEQUENCE", scene.id,
                    f"text anchor {anchor} follows {len(earlier)} visual(s) on the same words",
                    asset_ids=(anchor, *sorted(earlier)), event_ids=(event_id,),
                    engine_behaviour="text waits for its anchor or is withheld",
                    builder_rule="B5"))
    return findings
