from __future__ import annotations

import hashlib
import json
from typing import Any

from app.models import MotionCue, RenderPlan

# Motion segment fields that carry meaning (when and why an asset acts). Program
# keyframes, offsets and connector geometry are spatial and may differ per target.
_SEGMENT_SEMANTICS = (
    "phase", "start", "end", "semantic_event_id", "semantic_action", "relationship",
    "involvement", "source_asset_id", "target_asset_id", "result_asset_id",
    "handoff_deadline", "connection",
)


def _round(value: Any) -> Any:
    return round(float(value), 6) if isinstance(value, float) else value


def motion_semantics(cue: MotionCue) -> dict[str, Any]:
    return {
        "beat_id": cue.beat_id,
        "asset_id": cue.asset_id,
        "kind": cue.kind,
        "start": _round(cue.start),
        "end": _round(cue.end),
        "segments": [
            {name: _round(getattr(segment, name)) for name in _SEGMENT_SEMANTICS}
            for segment in cue.segments
        ],
    }


def semantic_signature(plan: RenderPlan) -> dict[str, Any]:
    """Everything that must be identical across output formats of one generation.

    Geometry (Composition boxes, text placement, motion paths, connector endpoints and
    target-safe boundary downgrades) is deliberately excluded.
    """
    return {
        "fps": plan.fps,
        "duration": _round(plan.duration),
        "frame_count": max(1, round(plan.duration * plan.fps)),
        "story": [beat.model_dump(mode="json") for beat in plan.story],
        "text_cues": [cue.model_dump(mode="json") for cue in plan.text.cues],
        "text_owners": sorted(
            (item.text_cue_id, item.anchor_asset_id or "")
            for beat in plan.text_composition for item in beat.items
        ),
        "text_timing": [
            {
                "text_cue_id": row.text_cue_id,
                "beat_id": row.beat_id,
                "kind": row.kind,
                "start": _round(row.start),
                "end": _round(row.end),
                "tokens": [
                    (token.text, _round(token.start), _round(token.end), _round(token.visible_end))
                    for token in row.tokens
                ],
            }
            for row in plan.text_motion
        ],
        "motion": sorted(
            (motion_semantics(cue) for cue in plan.motion),
            key=lambda row: (row["beat_id"], row["asset_id"]),
        ),
        "composition_semantics": [
            (beat.beat_id, beat.state_name, beat.semantic_focus_asset_id,
             sorted(item.asset_id for item in beat.items))
            for beat in plan.composition
        ],
        "boundary_intent": [(row.beat_id, row.from_beat_id) for row in plan.scene_boundaries],
    }


def fingerprint(payload: Any) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def semantic_differences(reference: RenderPlan, candidate: RenderPlan) -> list[str]:
    """Human-readable semantic divergences of ``candidate`` from ``reference``."""
    left, right = semantic_signature(reference), semantic_signature(candidate)
    issues: list[str] = []
    for key in left:
        if left[key] == right[key]:
            continue
        a, b = left[key], right[key]
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                issues.append(f"{key}: count {len(a)} != {len(b)}")
                continue
            for index, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    issues.append(f"{key}[{index}]: {_brief(x)} != {_brief(y)}")
                    if len(issues) > 40:
                        return issues
        else:
            issues.append(f"{key}: {a} != {b}")
    return issues


def plan_fingerprint(plan: RenderPlan) -> str:
    """Path-independent fingerprint of a whole RenderPlan (geometry included)."""
    payload = plan.model_dump(mode="json")
    for asset in payload["assets"]:
        asset.pop("image_path", None)
    return fingerprint(payload)


def _brief(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 300 else text[:300] + "..."
