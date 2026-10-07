"""Target registry and profile contract (Roadmap V2 Sprint 1)."""
from __future__ import annotations

from fractions import Fraction

import pytest

from app.composition.text_director import TextPlacementDirector
from app.reference import HexaVisualProfile
from app.targets import (
    REELS_9_16,
    REFERENCE_TARGET,
    SUPPORTED_VISUAL_TARGETS,
    YOUTUBE_16_9,
    active_target,
    composition_policy,
    frame_size,
    target_by_id,
    visual_target,
)
from app.targets.models import FrameMargins, NormalizedRect, TargetSafeZones, VisualTargetProfile


def test_both_formats_are_registered_with_unique_ids() -> None:
    ids = [target.target_id for target in SUPPORTED_VISUAL_TARGETS]
    assert ids == ["YOUTUBE_16_9", "REELS_9_16"]
    assert len(set(ids)) == len(ids)
    assert len({target.output_suffix for target in SUPPORTED_VISUAL_TARGETS}) == len(ids)
    assert REFERENCE_TARGET is YOUTUBE_16_9 and SUPPORTED_VISUAL_TARGETS[0] is REFERENCE_TARGET
    for target in SUPPORTED_VISUAL_TARGETS:
        assert target_by_id(target.target_id) is target
    with pytest.raises(KeyError):
        target_by_id("SQUARE_1_1")


def test_profile_facts() -> None:
    assert (YOUTUBE_16_9.width, YOUTUBE_16_9.height, YOUTUBE_16_9.fps) == (1920, 1080, 30)
    assert (REELS_9_16.width, REELS_9_16.height, REELS_9_16.fps) == (1080, 1920, 30)
    assert YOUTUBE_16_9.aspect_ratio == Fraction(16, 9)
    assert REELS_9_16.aspect_ratio == Fraction(9, 16)
    assert YOUTUBE_16_9.is_reference and not REELS_9_16.is_reference
    assert YOUTUBE_16_9.x_scale() == 1.0 and YOUTUBE_16_9.y_scale() == 1.0


@pytest.mark.parametrize("target", SUPPORTED_VISUAL_TARGETS, ids=lambda t: t.target_id)
def test_safe_regions_are_valid_and_clear_of_reserved_ui(target: VisualTargetProfile) -> None:
    zones = target.safe_zones
    for rect in (zones.content, zones.text):
        assert 0.0 <= rect.left < rect.right <= 1.0 and 0.0 <= rect.top < rect.bottom <= 1.0
        for region in zones.reserved:
            assert not region.intersects((rect.left, rect.top, rect.right, rect.bottom))


def test_youtube_zones_are_the_certified_constants() -> None:
    profile = HexaVisualProfile.production()
    content = YOUTUBE_16_9.safe_zones.content
    assert (content.left, content.top, content.right, content.bottom) == (
        profile.safe_left, profile.safe_top, profile.safe_right, profile.safe_bottom,
    )
    margins = YOUTUBE_16_9.safe_zones.text_margins
    assert (margins.left, margins.top) == (
        TextPlacementDirector._SAFE_MARGIN_X, TextPlacementDirector._SAFE_MARGIN_Y,
    )
    assert YOUTUBE_16_9.safe_zones.reserved == ()


def test_reels_reserves_platform_ui() -> None:
    zones = REELS_9_16.safe_zones
    assert len(zones.reserved) == 3
    top = min(region.bottom for region in zones.reserved if region.top == 0.0)
    assert zones.content.top >= top and zones.text.top >= top
    assert zones.content.bottom <= 0.80 and zones.text.bottom <= 0.80


def test_invalid_profiles_and_zones_are_rejected() -> None:
    with pytest.raises(ValueError):
        NormalizedRect(0.5, 0.0, 0.4, 1.0)
    with pytest.raises(ValueError):
        FrameMargins(0.6, 0.0, 0.5, 0.0)
    with pytest.raises(ValueError):
        TargetSafeZones(
            content=NormalizedRect(0.0, 0.0, 1.0, 1.0),
            text_margins=FrameMargins(0.1, 0.1, 0.1, 0.1),
            reserved=(NormalizedRect(0.9, 0.9, 1.0, 1.0),),
        )
    with pytest.raises(ValueError):
        VisualTargetProfile(
            target_id="ODD", width=1081, height=1920, fps=30,
            safe_zones=REELS_9_16.safe_zones, layout_policy="responsive_portrait",
            output_suffix="ODD",
        )


def test_active_target_scope_defaults_to_reference_and_restores() -> None:
    assert active_target() is YOUTUBE_16_9 and frame_size() == (1920, 1080)
    with visual_target(REELS_9_16):
        assert frame_size() == (1080, 1920)
        with visual_target(YOUTUBE_16_9):
            assert frame_size() == (1920, 1080)
        assert active_target() is REELS_9_16
    assert active_target() is YOUTUBE_16_9


def test_reference_has_a_composition_policy_and_reels_requires_projection() -> None:
    assert composition_policy(YOUTUBE_16_9).project([], [], []).items == []
    with pytest.raises(ValueError, match="unsupported layout policy"):
        composition_policy(REELS_9_16)
