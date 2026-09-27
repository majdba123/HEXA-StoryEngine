from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RuleKind(StrEnum):
    PRE_RENDER = "pre_render"
    ENCODED_PROOF = "encoded_proof"
    DIAGNOSTIC_EVIDENCE = "diagnostic_evidence"


class MigrationState(StrEnum):
    PENDING = "pending"
    MIGRATED = "migrated"
    RETAINED_PROOF = "retained_proof"
    EVIDENCE_ONLY = "evidence_only"


@dataclass(frozen=True, slots=True)
class QualityRule:
    id: str
    legacy_source: str
    owner: str
    test_module: str
    kind: RuleKind = RuleKind.PRE_RENDER
    state: MigrationState = MigrationState.PENDING


# This ledger is the authoritative migration inventory from the legacy runtime QA
# architecture into owner-layer construction contracts.  It intentionally lives
# under tests/: production code must not depend on the migration bookkeeping.
QUALITY_RULES: tuple[QualityRule, ...] = (
    # StorytellingValidator: Story / Choreography / downstream semantic ownership.
    QualityRule("FINAL_PACKAGE_METADATA_COVERAGE", "app/diagnostics/storytelling.py", "app/story/planner.py", "tests/test2/story/test_story_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("FINAL_PACKAGE_RELATIONSHIP_COVERAGE", "app/diagnostics/storytelling.py", "app/choreography/director.py", "tests/test2/choreography/test_choreography_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("FINAL_PACKAGE_SEMANTIC_EVENT_COVERAGE", "app/diagnostics/storytelling.py", "app/choreography/director.py", "tests/test2/choreography/test_choreography_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("FINAL_PACKAGE_DOWNSTREAM_METADATA_COVERAGE", "app/diagnostics/storytelling.py", "cross_layer", "tests/test2/integration/test_semantic_preservation.py"),
    QualityRule("FORBIDDEN_JITTER_MOTION", "app/diagnostics/storytelling.py", "app/motion/planner.py", "tests/test2/motion/test_motion_contracts.py"),
    QualityRule("REFERENCE_VISUAL_GRAMMAR", "app/diagnostics/storytelling.py", "app/choreography/director.py", "tests/test2/choreography/test_choreography_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("NO_MEANINGFUL_VISUAL_STATE_CHANGE", "app/diagnostics/storytelling.py", "app/choreography/director.py", "tests/test2/choreography/test_choreography_contracts.py"),
    QualityRule("MOTION_ONLY_HOOK_PRESENT", "app/diagnostics/storytelling.py", "app/choreography/director.py", "tests/test2/choreography/test_choreography_contracts.py"),
    QualityRule("MOTION_CUE_MISSING_FINAL_PACKAGE_SEMANTICS", "app/diagnostics/storytelling.py", "app/motion/planner.py", "tests/test2/motion/test_motion_contracts.py"),
    QualityRule("TEXT_CUE_MISSING_STORY_SEMANTICS", "app/diagnostics/storytelling.py", "app/text/planner.py", "tests/test2/text/test_text_contracts.py"),
    QualityRule("COMPOSITION_MISSING_FINAL_PACKAGE_SEMANTICS", "app/diagnostics/storytelling.py", "app/composition/planner.py", "tests/test2/composition/test_composition_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("CHOREOGRAPHY_ASSET_REQUIREMENT_UNSATISFIED", "app/diagnostics/storytelling.py", "app/choreography/requirements.py", "tests/test2/choreography/test_choreography_contracts.py"),
    QualityRule("TEXT_MOTION_COVERAGE_INCOMPLETE", "app/diagnostics/storytelling.py", "app/motion/text.py", "tests/test2/text/test_text_contracts.py"),

    # AssetUsageValidator: no independently animatable cutout may silently disappear.
    QualityRule("ASSET_REACHES_STORY", "app/diagnostics/asset_usage.py", "app/story/planner.py", "tests/test2/story/test_story_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("ASSET_REACHES_COMPOSITION", "app/diagnostics/asset_usage.py", "app/composition/planner.py", "tests/test2/composition/test_composition_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("ASSET_REACHES_MOTION", "app/diagnostics/asset_usage.py", "app/motion/planner.py", "tests/test2/motion/test_motion_contracts.py"),

    # AuthoringVisualQA.
    QualityRule("TEXT_LAYER_MISSING", "app/qa/authoring.py", "app/text/planner.py", "tests/test2/text/test_text_contracts.py"),
    QualityRule("LAYOUT_REFERENCE_VIOLATION", "app/qa/authoring.py", "app/composition/planner.py", "tests/test2/composition/test_composition_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("TEXT_LAYOUT_REFERENCE_VIOLATION", "app/qa/authoring.py", "app/composition/text.py", "tests/test2/text/test_text_contracts.py"),
    QualityRule("MOTION_REFERENCE_VIOLATION", "app/qa/authoring.py", "app/motion/planner.py", "tests/test2/motion/test_motion_contracts.py"),

    # ChoreographyRhythmQA.
    QualityRule("INCONSISTENT_BEAT_PACE", "app/qa/choreography_rhythm.py", "app/motion/rhythm.py", "tests/test2/motion/test_rhythm_contracts.py"),
    QualityRule("PACE_WHIPLASH", "app/qa/choreography_rhythm.py", "app/motion/rhythm.py", "tests/test2/motion/test_rhythm_contracts.py"),
    QualityRule("DUPLICATE_SEMANTIC_ENTRY_ACCENT", "app/qa/choreography_rhythm.py", "app/motion/planner.py", "tests/test2/motion/test_rhythm_contracts.py"),
    QualityRule("COMPETING_ENTRY_FOCUS", "app/qa/choreography_rhythm.py", "app/motion/planner.py", "tests/test2/motion/test_rhythm_contracts.py"),

    # MotionInteractionQA.
    QualityRule("MISSING_RELATION_TIMELINE", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_relation_contracts.py"),
    QualityRule("MISSING_TARGET_REACTION", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_relation_contracts.py", state=MigrationState.MIGRATED),
    QualityRule("NO_RELATION_OVERLAP", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_relation_contracts.py"),
    QualityRule("MISSING_RESULT_PAYOFF", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_relation_contracts.py"),
    QualityRule("PAYOFF_PRECEDES_CAUSE", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_relation_contracts.py"),
    QualityRule("MOTION_CREATES_COLLISION", "app/qa/motion_semantics.py", "app/motion/collision.py", "tests/test2/motion/test_relation_contracts.py"),
    QualityRule("SEGMENT_PAST_HANDOFF", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_motion_contracts.py"),
    QualityRule("SEGMENT_PROGRAM_MISSING", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_motion_contracts.py"),
    QualityRule("EXIT_NOT_READABLE", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_motion_contracts.py"),
    QualityRule("SEGMENT_GEOMETRY_DRIFT", "app/qa/motion_semantics.py", "app/motion/planner.py", "tests/test2/motion/test_motion_contracts.py"),

    # SemanticLifetimeQA and SceneContinuityQA.
    QualityRule("PREMATURE_SEMANTIC_EXIT", "app/qa/semantic_lifetime.py", "app/motion/lifetime.py", "tests/test2/motion/test_lifetime_contracts.py"),
    QualityRule("TERMINAL_EXIT_ON_PERSISTENT_ASSET", "app/qa/scene_continuity.py", "app/motion/continuity.py", "tests/test2/motion/test_continuity_contracts.py"),
    QualityRule("MISSING_SCENE_BRIDGE", "app/qa/scene_continuity.py", "app/render/transition.py", "tests/test2/render/test_transition_contracts.py"),
    QualityRule("EMPTY_SCENE_BRIDGE", "app/qa/scene_continuity.py", "app/render/transition.py", "tests/test2/render/test_transition_contracts.py"),
    QualityRule("SCENE_BRIDGE_TOO_SHORT", "app/qa/scene_continuity.py", "app/render/transition.py", "tests/test2/render/test_transition_contracts.py"),
    QualityRule("BLUR_NOT_EXPLICITLY_AUTHORED", "app/qa/scene_continuity.py", "app/render/transition.py", "tests/test2/render/test_transition_contracts.py"),
    QualityRule("BLUR_BRIDGE_WITHOUT_BLUR", "app/qa/scene_continuity.py", "app/render/transition.py", "tests/test2/render/test_transition_contracts.py"),
    QualityRule("UNAUTHORED_BLUR", "app/qa/scene_continuity.py", "app/render/transition.py", "tests/test2/render/test_transition_contracts.py"),
    QualityRule("SCENE_BRIDGE_OVERRUN", "app/qa/scene_continuity.py", "app/render/transition.py", "tests/test2/render/test_transition_contracts.py"),
    QualityRule("INCOMING_BEFORE_STORY", "app/qa/scene_continuity.py", "app/motion/planner.py", "tests/test2/motion/test_continuity_contracts.py"),

    # StorySyncQA consolidated by actual invariant rather than diagnostic spelling.
    QualityRule("STORY_SYNC_ANCHORED_TIME", "app/story/sync_qa.py", "app/story/windows.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_MONOTONIC_ANCHORS", "app/story/sync_qa.py", "app/story/windows.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_MOTION_CUE", "app/story/sync_qa.py", "app/motion/planner.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_SETTLE_EVIDENCE", "app/story/sync_qa.py", "app/motion/planner.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_REVEAL_WINDOW", "app/story/sync_qa.py", "app/motion/planner.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_SETTLE_WINDOW", "app/story/sync_qa.py", "app/motion/planner.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_FOCUS_PEAK", "app/story/sync_qa.py", "app/motion/compiler.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_FOCUS_HANDOFF", "app/story/sync_qa.py", "app/motion/planner.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_SEQUENCE_ORDER", "app/story/sync_qa.py", "app/motion/order.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_VISUAL_UNIT_STAGGER", "app/story/sync_qa.py", "app/motion/order.py", "tests/test2/story/test_story_motion_sync.py"),
    QualityRule("STORY_SYNC_PROXY_TIMING", "app/story/sync_qa.py", "app/motion/planner.py", "tests/test2/story/test_story_motion_sync.py"),

    # Encoded-output proof stays after pre-render QA removal.
    QualityRule("MOTION_BELOW_PERCEPTUAL_FLOOR", "app/qa/rendered_motion.py", "app/render/verification.py", "tests/test2/render/test_encoded_motion_verification.py", RuleKind.ENCODED_PROOF, MigrationState.PENDING),
    QualityRule("MOTION_TOO_FAST", "app/qa/rendered_motion.py", "app/render/verification.py", "tests/test2/render/test_encoded_motion_verification.py", RuleKind.ENCODED_PROOF, MigrationState.PENDING),
    QualityRule("RENDERED_SEGMENT_FRAME_MISSING", "app/qa/rendered_motion.py", "app/render/verification.py", "tests/test2/render/test_encoded_motion_verification.py", RuleKind.ENCODED_PROOF, MigrationState.PENDING),
    QualityRule("RENDERED_SEGMENT_ROI_EMPTY", "app/qa/rendered_motion.py", "app/render/verification.py", "tests/test2/render/test_encoded_motion_verification.py", RuleKind.ENCODED_PROOF, MigrationState.PENDING),
    QualityRule("RENDERED_SEGMENT_INACTIVE", "app/qa/rendered_motion.py", "app/render/verification.py", "tests/test2/render/test_encoded_motion_verification.py", RuleKind.ENCODED_PROOF, MigrationState.PENDING),
    QualityRule("RENDERED_VISUAL_EVIDENCE", "app/qa/rendered.py", "app/render/verification.py", "tests/test2/render/test_encoded_visual_evidence.py", RuleKind.DIAGNOSTIC_EVIDENCE, MigrationState.PENDING),
)

LEGACY_QA_RUNTIME_FILES = frozenset({
    "app/diagnostics/asset_usage.py",
    "app/diagnostics/storytelling.py",
    "app/qa/authoring.py",
    "app/qa/choreography_rhythm.py",
    "app/qa/failure_identity.py",
    "app/qa/motion_semantics.py",
    "app/qa/rendered.py",
    "app/qa/rendered_motion.py",
    "app/qa/scene_continuity.py",
    "app/qa/semantic_lifetime.py",
    "app/story/sync_qa.py",
})

MIGRATION_COMPLETE = False
