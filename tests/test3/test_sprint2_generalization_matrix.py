from __future__ import annotations

import math

import pytest

from app.motion.timing import (
    encoded_motion_temporal_floor_seconds,
    story_activation_window,
)
from app.render.renderer import FFmpegRenderer
from tests.test1.certification.test_generated_full_layer_matrix import _plan
from tests.test1.factory import DiskPackageShape, seeded_disk_shape


def _program_has_motion(program: dict | None) -> bool:
    if not isinstance(program, dict):
        return False
    for frame in program.get("keyframes", []):
        if not isinstance(frame, dict):
            continue
        try:
            if (
                abs(float(frame.get("dx", 0.0))) > 1e-9
                or abs(float(frame.get("dy", 0.0))) > 1e-9
                or abs(float(frame.get("scale", 1.0)) - 1.0) > 1e-9
            ):
                return True
        except (TypeError, ValueError, OverflowError):
            continue
    return False


def _group_policy_by_scene_and_id(canonical) -> dict[tuple[str, str], str]:
    output: dict[tuple[str, str], str] = {}
    for scene in canonical.scenes:
        for group in scene.semantic_groups:
            value = (
                group.animation_policy.value
                if hasattr(group.animation_policy, "value")
                else str(group.animation_policy)
            )
            output[(scene.id, group.semantic_group_id)] = str(value)
    return output


def _assert_sprint2_perceptual_contracts(
    canonical,
    story,
    composition,
    motion,
    plan,
) -> None:
    motion_by_key = {(cue.beat_id, cue.asset_id): cue for cue in motion}
    composition_by_beat = {beat.beat_id: beat for beat in composition}
    policy_by_group = _group_policy_by_scene_and_id(canonical)
    temporal_floor = encoded_motion_temporal_floor_seconds()

    for beat in story:
        activations = []
        for activation in beat.asset_activations:
            has_window, window = story_activation_window(activation, beat)
            if not has_window or window is None:
                continue
            activations.append((activation, window))
            cue = motion_by_key.get((beat.id, activation.asset_id))
            if cue is not None:
                assert cue.start + 1e-9 >= window.reveal_start, (
                    beat.id,
                    activation.asset_id,
                    cue.start,
                    window.reveal_start,
                )

        # One semantic intent may map to several runtime cutouts. The attention rule is
        # therefore one full-strength *semantic unit* per sequential authored instant,
        # not one PNG. Explicit simultaneous visual units are intentionally exempt.
        same_event: dict[tuple[str, float], list] = {}
        for activation, window in activations:
            if activation.semantic_event_id:
                same_event.setdefault(
                    (activation.semantic_event_id, round(window.reveal_start, 9)),
                    [],
                ).append(activation)

        for rows in same_event.values():
            if len(rows) < 2 or str(beat.action or "").upper() == "COMPARE":
                continue
            policies = {
                policy_by_group.get((beat.scene_id, activation.semantic_group_id))
                for activation in rows
                if activation.semantic_group_id
            }
            if "SIMULTANEOUS_VISUAL_UNIT" in policies:
                continue

            gain_by_unit: dict[str, float] = {}
            for activation in rows:
                cue = motion_by_key.get((beat.id, activation.asset_id))
                if cue is None:
                    continue
                focus = cue.params.get("semantic_focus", {})
                unit_id = activation.semantic_unit_id or activation.asset_id
                gain = float(focus.get("cohort_gain", 0.0) or 0.0)
                gain_by_unit[unit_id] = max(gain, gain_by_unit.get(unit_id, 0.0))
            full_strength_units = sum(
                1 for gain in gain_by_unit.values() if abs(gain - 1.0) <= 1e-9
            )
            assert full_strength_units <= 1, (beat.id, gain_by_unit, policies)

        layout = composition_by_beat[beat.id]
        ordered_items = sorted(layout.items, key=lambda item: (item.z, item.asset_id))
        if not ordered_items:
            continue

        earliest_motion_start = min(
            motion_by_key[(beat.id, item.asset_id)].start for item in ordered_items
        )
        carrier = FFmpegRenderer._visual_carrier_asset_id(
            beat=beat,
            ordered_items=ordered_items,
            motion=motion_by_key,
            persistent_ids=frozenset(),
            fps=plan.fps,
        )
        if earliest_motion_start > beat.start + 1e-9:
            assert carrier is None, (
                beat.id,
                earliest_motion_start,
                beat.start,
                carrier,
            )

        frame_rows: list[tuple[str, float, dict]] = []
        for item in ordered_items:
            cue = motion_by_key[(beat.id, item.asset_id)]
            assert not any(
                segment.phase == "INTERACT" and segment.involvement == "TARGET"
                for segment in cue.segments
            ), (beat.id, cue.asset_id)

            base_program = (
                cue.params.get("program") if isinstance(cue.params, dict) else None
            )
            if _program_has_motion(base_program):
                assert cue.end - cue.start + 1e-9 >= temporal_floor, (
                    beat.id,
                    cue.asset_id,
                    cue.start,
                    cue.end,
                )
            for segment in cue.segments:
                if segment.phase == "ENTRY" and _program_has_motion(segment.program):
                    assert segment.end - segment.start + 1e-9 >= temporal_floor, (
                        beat.id,
                        cue.asset_id,
                        segment.start,
                        segment.end,
                    )

            order = cue.params.get("motion_order", {})
            if not isinstance(order, dict):
                order = {}
            frame_rows.append(
                (
                    item.asset_id,
                    max(0.0, cue.start - beat.start),
                    order,
                )
            )

        duration = beat.end - beat.start
        frame_schedule = FFmpegRenderer._frame_safe_group_reveal_starts(
            rows=frame_rows,
            fps=plan.fps,
            duration=duration,
        )
        by_group: dict[str, list[tuple[str, float, float]]] = {}
        for asset_id, raw_start, order in frame_rows:
            group_id = order.get("semantic_group_id")
            if group_id and asset_id in frame_schedule:
                by_group.setdefault(str(group_id), []).append(
                    (asset_id, raw_start, frame_schedule[asset_id])
                )

        for group_rows in by_group.values():
            group_rows.sort(key=lambda row: (row[1], row[0]))
            for asset_id, raw_start, threshold in group_rows:
                natural_frame = math.ceil(raw_start * plan.fps - 1e-9)
                scheduled_frame = math.ceil(threshold * plan.fps - 1e-9)
                assert scheduled_frame >= natural_frame, (
                    beat.id,
                    asset_id,
                    raw_start,
                    threshold,
                )

            clusters: list[list[tuple[str, float, float]]] = []
            for row in group_rows:
                if clusters and abs(row[1] - clusters[-1][0][1]) <= 1e-9:
                    clusters[-1].append(row)
                else:
                    clusters.append([row])

            cluster_frames = [
                math.ceil(cluster[0][2] * plan.fps - 1e-9)
                for cluster in clusters
            ]
            assert all(
                left < right
                for left, right in zip(cluster_frames, cluster_frames[1:])
            ), (beat.id, cluster_frames)
            for cluster in clusters:
                assert len(
                    {
                        math.ceil(row[2] * plan.fps - 1e-9)
                        for row in cluster
                    }
                ) == 1


SPRINT2_GENERALIZATION_SEEDS = tuple(range(8101, 8181))


@pytest.mark.parametrize("seed", SPRINT2_GENERALIZATION_SEEDS)
def test_seeded_packages_preserve_sprint2_perceptual_contracts(
    tmp_path,
    seed: int,
) -> None:
    result = _plan(tmp_path, seeded_disk_shape(seed))
    canonical, story, _choreography, composition, motion, _text, plan = result
    _assert_sprint2_perceptual_contracts(
        canonical,
        story,
        composition,
        motion,
        plan,
    )


FIXED_SPRINT2_SHAPES = (
    (
        "single-minimal",
        DiskPackageShape(
            scenes=1,
            assets_per_scene=1,
            relations=False,
            dependencies=False,
        ),
    ),
    (
        "dense-20-arabic",
        DiskPackageShape(
            scenes=1,
            assets_per_scene=20,
            locators="partial",
            group_count=2,
            script_style="arabic",
        ),
    ),
    (
        "dense-20-numbers",
        DiskPackageShape(
            scenes=1,
            assets_per_scene=20,
            locators="all",
            group_count=2,
            script_style="numbers",
        ),
    ),
    (
        "branching-reuse",
        DiskPackageShape(
            scenes=8,
            assets_per_scene=6,
            dependency_mode="branching",
            reuse_first_asset=True,
            script_style="arabic",
        ),
    ),
    (
        "simultaneous-units",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=6,
            group_count=2,
            group_policy="SIMULTANEOUS_VISUAL_UNIT",
        ),
    ),
    (
        "compound-arabic",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=5,
            compound=True,
            script_style="arabic",
        ),
    ),
    (
        "numbers-persist",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=5,
            script_style="numbers",
            continuity="persist",
            reuse_first_asset=True,
        ),
    ),
    (
        "transform-continuity",
        DiskPackageShape(
            scenes=3,
            assets_per_scene=5,
            continuity="transform",
            reuse_first_asset=True,
        ),
    ),
    (
        "no-progression-no-locators",
        DiskPackageShape(
            scenes=4,
            assets_per_scene=5,
            progression=False,
            locators="none",
        ),
    ),
    (
        "support-bindings",
        DiskPackageShape(
            scenes=2,
            assets_per_scene=5,
            binding_types=("EXPLICIT", "SUPPORT"),
        ),
    ),
    (
        "ambiguous-bindings",
        DiskPackageShape(
            scenes=2,
            assets_per_scene=5,
            binding_types=("SEMANTIC", "AMBIGUOUS"),
        ),
    ),
    (
        "parent-bindings",
        DiskPackageShape(
            scenes=2,
            assets_per_scene=5,
            binding_types=("EXPLICIT", "PARENT", "SEMANTIC"),
            compound=True,
        ),
    ),
)


@pytest.mark.parametrize(
    ("case_name", "shape"),
    FIXED_SPRINT2_SHAPES,
    ids=[row[0] for row in FIXED_SPRINT2_SHAPES],
)
def test_fixed_final_package_patterns_preserve_sprint2_perceptual_contracts(
    tmp_path,
    case_name: str,
    shape: DiskPackageShape,
) -> None:
    result = _plan(tmp_path / case_name, shape)
    canonical, story, _choreography, composition, motion, _text, plan = result
    _assert_sprint2_perceptual_contracts(
        canonical,
        story,
        composition,
        motion,
        plan,
    )
