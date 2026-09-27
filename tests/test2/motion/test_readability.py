from __future__ import annotations
# Owner-scoped Test2 coverage; historical regression content is preserved.

from app.diagnostics.failure_policy import FailureDisposition, failure_policy
from app.models import MotionSegment
from app.motion import MotionPlanner


def test_encoded_underfloor_motion_is_proof_only() -> None:
    policy = failure_policy("MOTION_BELOW_PERCEPTUAL_FLOOR")
    assert policy is not None
    assert policy.disposition == FailureDisposition.POST_RENDER_PROOF


def test_relation_overlap_extension_preserves_authored_active_duration() -> None:
    segment = MotionSegment(
        phase="REACT",
        start=0.20,
        end=0.50,
        program={
            "name": "reference_target_react",
            "semantic_active_duration": 0.22,
            "keyframes": [
                {"progress": 0.0, "dx": 0.0, "dy": 0.0, "scale": 1.0},
                {"progress": 1.0, "dx": 0.02, "dy": 0.0, "scale": 1.0},
            ],
        },
    )

    extended = MotionPlanner._retime_segment_end(segment, 0.72)

    assert extended.end == 0.72
    assert extended.program["semantic_active_duration"] == 0.22
    assert extended.program["keyframes"] == segment.program["keyframes"]
