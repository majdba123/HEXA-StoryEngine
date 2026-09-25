import re

import pytest
from pathlib import Path

from app.composition import TextCompositionPlanner
from app.models import (
    AssetActivation,
    CompositionBeat,
    MotionCue,
    LayoutItem,
    PackageModel,
    SceneSource,
    StoryBeat,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
    VisualAsset,
)
from app.motion import TextMotionPlanner
from app.text import TextPlanner


def _transcript(script: str, *, timing_source: str = "forced_alignment") -> Transcript:
    matches = list(re.finditer(r"\S+", script))
    words = [
        TranscriptWord(
            start=index * 0.45,
            end=index * 0.45 + 0.32,
            text=match.group(),
            char_start=match.start(),
            char_end=match.end(),
        )
        for index, match in enumerate(matches)
    ]
    return Transcript(
        language="ar",
        duration=max(1.0, words[-1].end + 0.3),
        segments=[
            TranscriptSegment(
                start=words[0].start,
                end=words[-1].end,
                text=script,
                char_start=0,
                char_end=len(script),
                words=words,
            )
        ],
        words=words,
        timing_source=timing_source,
    )


def _beat(transcript: Transcript) -> StoryBeat:
    return StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=transcript.duration,
        audio_start=0.0,
        audio_end=transcript.words[-1].end,
        narration="الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة",
        primary_asset_ids=["wallet"],
        support_asset_ids=["lock"],
        action="EMPHASIZE",
    )


def _assets() -> list[VisualAsset]:
    return [
        VisualAsset(
            id="wallet",
            scene_id="scene-001",
            role="primary",
            image_path=Path("wallet.png"),
            extraction_method="fixture",
        ),
        VisualAsset(
            id="lock",
            scene_id="scene-001",
            role="support",
            image_path=Path("lock.png"),
            extraction_method="fixture",
        ),
    ]


def test_text_planner_selects_sparse_keywords_from_forced_alignment() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)

    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())

    assert [cue.text for cue in text.cues] == ["1000 ريال", "300 ريال محجوزة"]
    assert text.cues[0].semantic_type == "amount"
    assert text.cues[1].semantic_type == "warning_amount"
    assert all(cue.anchor_asset_id == "wallet" for cue in text.cues)
    assert all(cue.spoken_start >= 0 for cue in text.cues)
    assert [token.text for token in text.cues[0].tokens] == ["1000", "ريال"]
    assert [token.text for token in text.cues[1].tokens] == ["300", "ريال", "محجوزة"]
    assert all(token.spoken_end > token.spoken_start for cue in text.cues for token in cue.tokens)
    assert {style.id for style in text.styles} == {"amount", "warning_amount"}


def test_text_timing_refuses_non_forced_alignment_timestamps() -> None:
    script = "الرصيد الظاهر 1000 ريال"
    transcript = _transcript(script, timing_source="script_fallback")
    beat = _beat(transcript)

    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())

    assert text.cues == []
    assert text.styles == []


def test_text_composition_is_separate_from_visual_composition() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)
    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())
    visual = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(asset_id="wallet", x=0.50, y=0.55, width=0.44, height=0.52, z=20),
                LayoutItem(asset_id="lock", x=0.76, y=0.55, width=0.18, height=0.22, z=15),
            ],
        )
    ]

    text_composition = TextCompositionPlanner().plan([beat], visual, text.cues)

    assert len(text_composition) == 1
    assert len(text_composition[0].items) == 2
    assert all(item.text_cue_id.startswith("text-") for item in text_composition[0].items)
    assert visual[0].items[0].asset_id == "wallet"
    assert all(item.z >= 50 for item in text_composition[0].items)


def test_text_motion_is_separate_and_locked_to_spoken_start() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)
    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())
    visual = [
        CompositionBeat(
            beat_id=beat.id,
            items=[LayoutItem(asset_id="wallet", x=0.5, y=0.5, width=0.4, height=0.5, z=20)],
        )
    ]
    text_composition = TextCompositionPlanner().plan([beat], visual, text.cues)

    cues = TextMotionPlanner().plan([beat], text.cues, text_composition)

    assert len(cues) == len(text.cues)
    by_id = {cue.id: cue for cue in text.cues}
    for motion in cues:
        source = by_id[motion.text_cue_id]
        assert motion.start == source.spoken_start
        assert motion.params["emphasis_time"] == source.emphasis_time
        assert motion.params["anchor_asset_id"] == "wallet"
        assert motion.params["reveal_mode"] == "sequential_words"
        assert [token.text for token in motion.tokens] == [token.text for token in source.tokens]
        assert [token.start for token in motion.tokens] == [token.spoken_start for token in source.tokens]



def _semantic_package(script: str, *, meanings: list[tuple[str, str]]) -> PackageModel:
    scene = SceneSource(
        id="scene-001",
        image_path=Path("scene.png"),
        order=1,
        script_char_start=0,
        script_char_end=len(script) - 1,
    )
    assets = []
    asset_ids = []
    for index, (binding_type, meaning) in enumerate(meanings, start=1):
        asset_id = f"intent-{index}"
        asset_ids.append(asset_id)
        assets.append({
            "scene_id": scene.id,
            "asset_id": asset_id,
            "semantic_meaning": meaning,
            "visual_concept": meaning,
            "semantic_role": "OBJECT" if index > 1 else "PRIMARY",
            "binding_type": binding_type,
            "script_text": script,
            "semantic_group_id": "group-1",
            "sequence_order": index,
            "confidence": 0.98,
        })
    return PackageModel(
        root=Path("/tmp"),
        package_id="semantic-text",
        scenes=[scene],
        script=script,
        semantic_bindings={
            "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
            "scenes": [{
                "scene_id": scene.id,
                "semantic_groups": [{
                    "semantic_group_id": "group-1",
                    "script_text": script,
                    "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                    "asset_ids": asset_ids,
                }],
                "assets": assets,
            }],
        },
    )


@pytest.mark.parametrize(
    "script,meanings,expected",
    [
        (
            "هذا النوع يستخدم نفس المعرفة التقنية تقريبًا،",
            [("EXPLICIT", "معرفة برمجية"), ("SEMANTIC", "شبكة تقنية")],
            "المعرفة التقنية",
        ),
        (
            "ارتفاع ضغط الدم يحتاج متابعة مستمرة.",
            [("EXPLICIT", "قياس ضغط الدم")],
            "ضغط الدم",
        ),
        (
            "ناقل الحركة يغير السرعات تلقائيًا.",
            [("EXPLICIT", "ناقل الحركة")],
            "ناقل الحركة",
        ),
    ],
)
def test_text_planner_learns_keywords_from_final_package_semantics(
    script: str,
    meanings: list[tuple[str, str]],
    expected: str,
) -> None:
    transcript = _transcript(script)
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=transcript.duration,
        audio_start=0.0,
        audio_end=transcript.words[-1].end,
        narration=script,
        action="INTRODUCE",
    )
    package = _semantic_package(script, meanings=meanings)

    plan = TextPlanner().plan(
        transcript=transcript,
        story=[beat],
        package=package,
        assets=_assets(),
    )

    assert expected in [cue.text for cue in plan.cues]
    assert all(cue.spoken_end > cue.spoken_start for cue in plan.cues)


def test_semantic_final_package_can_surface_multiple_meaningful_cues() -> None:
    script = "الخطر الحقيقي يظهر عندما يكتشف الضعف"
    transcript = _transcript(script)
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=transcript.duration,
        audio_start=0.0,
        audio_end=transcript.words[-1].end,
        narration=script,
        action="EMPHASIZE",
    )
    package = _semantic_package(
        script,
        meanings=[
            ("EXPLICIT", "الخطر الحقيقي"),
            ("EXPLICIT", "اكتشاف الضعف"),
        ],
    )

    plan = TextPlanner().plan(transcript=transcript, story=[beat], package=package)
    texts = [cue.text for cue in plan.cues]

    assert len(texts) >= 2
    assert "الخطر الحقيقي" in texts
    assert "يكتشف الضعف" in texts

def test_text_anchor_uses_exact_asset_activation_span_before_beat_primary() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)
    first_start = script.index("1000")
    first_end = first_start + len("1000 ريال")
    second_start = script.index("300")
    second_end = second_start + len("300 ريال محجوزة")
    beat.asset_activations = [
        AssetActivation(
            asset_id="wallet",
            trigger_char_start=first_start,
            trigger_char_end=first_end,
            confidence=0.99,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            visual_focus="SUPPORT",
        ),
        AssetActivation(
            asset_id="lock",
            trigger_char_start=second_start,
            trigger_char_end=second_end,
            confidence=0.99,
            source="final_package_semantic_binding",
            policy="EXPLICIT",
            visual_focus="RESULT",
        ),
    ]

    plan = TextPlanner().plan(
        transcript=transcript,
        story=[beat],
        assets=_assets(),
    )

    assert [cue.text for cue in plan.cues] == ["1000 ريال", "300 ريال محجوزة"]
    assert plan.cues[0].anchor_asset_id == "wallet"
    assert plan.cues[1].anchor_asset_id == "lock"


def test_text_motion_consumes_visual_focus_without_leading_speech() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)
    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())
    visual = [
        CompositionBeat(
            beat_id=beat.id,
            items=[LayoutItem(asset_id="wallet", x=0.5, y=0.5, width=0.4, height=0.5, z=20)],
        )
    ]
    text_composition = TextCompositionPlanner().plan([beat], visual, text.cues)
    first = text.cues[0]
    visual_motion = [
        MotionCue(
            beat_id=beat.id,
            asset_id="wallet",
            kind="program_v3",
            start=first.spoken_start,
            end=first.spoken_start + 0.7,
            params={
                "semantic_settle_time": first.spoken_start + 0.5,
                "semantic_focus": {
                    "active": True,
                    "role": "ACTIVE_FOCUS",
                    "source": "story_activation_window",
                },
            },
        )
    ]

    cues = TextMotionPlanner().plan(
        [beat],
        text.cues,
        text_composition,
        visual_motion=visual_motion,
    )

    by_id = {cue.id: cue for cue in text.cues}
    synced = next(row for row in cues if row.text_cue_id == first.id)
    assert synced.start == first.spoken_start
    assert synced.tokens[0].start == first.tokens[0].spoken_start
    assert synced.params["visual_sync"]["available"] is True
    assert synced.params["entry_strength"] > 0.8
    assert 130 <= synced.params["entry_duration_ms"] <= 240
    for row in cues:
        source = by_id[row.text_cue_id]
        assert row.start == source.spoken_start
        assert [token.start for token in row.tokens] == [
            token.spoken_start for token in source.tokens
        ]

def _precise_semantic_package(
    script: str,
    assets: list[dict],
) -> PackageModel:
    scene = SceneSource(
        id="scene-001",
        image_path=Path("scene.png"),
        order=1,
        script_char_start=0,
        script_char_end=len(script) - 1,
    )
    asset_ids = [row["asset_id"] for row in assets]
    normalized_assets = []
    for index, row in enumerate(assets, start=1):
        normalized_assets.append({
            "scene_id": scene.id,
            "semantic_group_id": "group-1",
            "sequence_order": index,
            "binding_type": "EXPLICIT",
            "confidence": 1.0,
            **row,
        })
    return PackageModel(
        root=Path("/tmp"),
        package_id="precise-text",
        scenes=[scene],
        script=script,
        semantic_bindings={
            "schema_name": "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS",
            "scenes": [{
                "scene_id": scene.id,
                "semantic_groups": [{
                    "semantic_group_id": "group-1",
                    "script_text": script,
                    "animation_policy": "SEQUENTIAL_WITHIN_PHRASE",
                    "asset_ids": asset_ids,
                }],
                "assets": normalized_assets,
            }],
        },
    )


def test_text_prefers_action_and_object_precise_spans_over_character_phrase() -> None:
    script = "إن الاختراق عبارة عن شخص يكتب بسرعة قدام شاشة سوداء"
    transcript = _transcript(script)
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=transcript.duration,
        audio_start=0.0,
        audio_end=transcript.words[-1].end,
        narration=script,
        action="INTRODUCE",
    )
    character_start = script.index("شخص")
    character_end = script.index("قدام") - 1
    keyboard_start = script.index("يكتب")
    keyboard_end = keyboard_start + len("يكتب بسرعة")
    monitor_start = script.index("شاشة")
    monitor_end = monitor_start + len("شاشة سوداء")
    package = _precise_semantic_package(
        script,
        [
            {
                "asset_id": "character",
                "semantic_role": "CHARACTER",
                "semantic_meaning": "شخص يكتب أمام شاشة",
                "visual_concept": "شخص يكتب أمام شاشة",
                "script_text": "شخص يكتب بسرعة",
                "script_span": {
                    "char_start": character_start,
                    "char_end": character_end,
                },
            },
            {
                "asset_id": "monitor",
                "semantic_role": "OBJECT",
                "semantic_meaning": "شاشة سوداء",
                "visual_concept": "شاشة سوداء",
                "script_text": "شاشة سوداء",
                "script_span": {
                    "char_start": monitor_start,
                    "char_end": monitor_end,
                },
            },
            {
                "asset_id": "keyboard",
                "semantic_role": "ACTION",
                "semantic_meaning": "الكتابة بسرعة",
                "visual_concept": "لوحة مفاتيح سريعة",
                "script_text": "يكتب بسرعة",
                "script_span": {
                    "char_start": keyboard_start,
                    "char_end": keyboard_end,
                },
            },
        ],
    )

    plan = TextPlanner().plan(
        transcript=transcript,
        story=[beat],
        package=package,
    )
    texts = [cue.text for cue in plan.cues]

    assert "يكتب بسرعة" in texts
    assert "شاشة سوداء" in texts
    assert "شخص يكتب بسرعة" not in texts
    keyboard = next(cue for cue in plan.cues if cue.text == "يكتب بسرعة")
    monitor = next(cue for cue in plan.cues if cue.text == "شاشة سوداء")
    assert keyboard.spoken_start < monitor.spoken_start


def test_text_company_scene_prefers_concept_then_discovery_result() -> None:
    script = "قبل ما الشركة تكتشفها"
    transcript = _transcript(script)
    beat = StoryBeat(
        id="beat-001",
        scene_id="scene-001",
        start=0.0,
        end=transcript.duration,
        audio_start=0.0,
        audio_end=transcript.words[-1].end,
        narration=script,
        action="REVEAL_DETAIL",
    )
    company_start = script.index("الشركة")
    company_end = company_start + len("الشركة")
    discover_start = script.index("تكتشفها")
    discover_end = discover_start + len("تكتشفها")
    package = _precise_semantic_package(
        script,
        [
            {
                "asset_id": "manager",
                "semantic_role": "CHARACTER",
                "semantic_meaning": "مسؤول يكتشف المشكلة",
                "visual_concept": "مسؤول شركة",
                "script_text": "الشركة تكتشفها",
                "script_span": {
                    "char_start": company_start,
                    "char_end": discover_end,
                },
            },
            {
                "asset_id": "company",
                "semantic_role": "OBJECT",
                "semantic_meaning": "الشركة",
                "visual_concept": "مبنى الشركة",
                "script_text": "الشركة",
                "script_span": {
                    "char_start": company_start,
                    "char_end": company_end,
                },
            },
            {
                "asset_id": "magnifier",
                "semantic_role": "RESULT",
                "visual_focus": "RESULT",
                "semantic_meaning": "اكتشاف الاختراق",
                "visual_concept": "عدسة تكشف الاختراق",
                "script_text": "تكتشفها",
                "script_span": {
                    "char_start": discover_start,
                    "char_end": discover_end,
                },
            },
        ],
    )

    plan = TextPlanner().plan(
        transcript=transcript,
        story=[beat],
        package=package,
    )
    texts = [cue.text for cue in plan.cues]

    assert "الشركة" in texts
    assert "تكتشفها" in texts
    assert "الشركة تكتشفها" not in texts
    company = next(cue for cue in plan.cues if cue.text == "الشركة")
    discovery = next(cue for cue in plan.cues if cue.text == "تكتشفها")
    assert discovery.priority > company.priority




def test_text_motion_respects_visual_cohort_attention_hierarchy() -> None:
    script = "الرصيد الظاهر 1000 ريال لكن 300 ريال محجوزة لعملية سابقة"
    transcript = _transcript(script)
    beat = _beat(transcript)
    text = TextPlanner().plan(transcript=transcript, story=[beat], assets=_assets())
    visual = [
        CompositionBeat(
            beat_id=beat.id,
            items=[
                LayoutItem(asset_id="wallet", x=0.35, y=0.5, width=0.3, height=0.4, z=20),
                LayoutItem(asset_id="lock", x=0.70, y=0.5, width=0.2, height=0.3, z=21),
            ],
        )
    ]
    text_composition = TextCompositionPlanner().plan([beat], visual, text.cues)
    first = text.cues[0]

    def anchor_motion(role: str, gain: float) -> MotionCue:
        return MotionCue(
            beat_id=beat.id,
            asset_id="wallet",
            kind="program_v3",
            start=first.spoken_start,
            end=first.spoken_start + 0.7,
            params={
                "semantic_settle_time": first.spoken_start + 0.5,
                "semantic_focus": {
                    "active": True,
                    "role": "ACTIVE_FOCUS",
                    "source": "story_activation_window",
                    "cohort_role": role,
                    "cohort_gain": gain,
                },
            },
        )

    leader = TextMotionPlanner().plan(
        [beat],
        text.cues,
        text_composition,
        visual_motion=[anchor_motion("leader", 1.0)],
    )
    participant = TextMotionPlanner().plan(
        [beat],
        text.cues,
        text_composition,
        visual_motion=[anchor_motion("participant", 0.58)],
    )

    leader_cue = next(row for row in leader if row.text_cue_id == first.id)
    participant_cue = next(row for row in participant if row.text_cue_id == first.id)
    assert leader_cue.params["entry_strength"] > participant_cue.params["entry_strength"]
    assert leader_cue.params["visual_sync"]["cohort_role"] == "leader"
    assert participant_cue.params["visual_sync"]["cohort_role"] == "participant"
    # Text timing remains narration-owned; only presentation energy changes.
    assert leader_cue.start == participant_cue.start == first.spoken_start
    assert [token.start for token in leader_cue.tokens] == [
        token.start for token in participant_cue.tokens
    ]
