from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Callable

from app.choreography import ChoreographyDirector
from app.assets import AssetManager
from app.director import Qwen3VLBackend, VisualDirector
from app.reference import ReferenceAnalyzer
from app.qa import (
    AuthoringVisualQA,
    ChoreographyRhythmQA,
    MotionInteractionQA,
    RenderedMotionQA,
    RenderedVisualQA,
    SceneContinuityQA,
)
from app.composition import CompositionPlanner, TextCompositionPlanner
from app.config import Settings
from app.diagnostics import AssetUsageValidator, StorytellingValidator
from app.cutout import CutoutService, Pass2CutoutService
from app.final import FinalExporter
from app.input import FinalPackageLoader
from app.models import RenderPlan, Stage
from app.motion import MotionPlanner, ReferenceMotionEnforcer, TextMotionPlanner
from app.recovery import RecoveryCandidateEvaluator
from app.recovery.detector import DetectedIssue, RecoveryDetector
from app.refinement import RefinementService
from app.cutout.pass2.segmenter import SAM2MaskBackend
from app.recovery.manager import RecoveryManager
from app.render import RenderPlanner
from app.render.renderer import FFmpegRenderer
from app.shared.errors import (
    GenerationCancelledError,
    HexaError,
    StageFailedError,
)
from app.story import StoryPlanner, StorySyncQA
from app.text import TextPlanner
from app.transcription import TranscriptionService
from app.transcription.alignment import WhisperXForcedAligner
from app.vision import VisionService

ProgressCallback = Callable[[Stage, float, str], None]
CancellationCallback = Callable[[], bool]


class StoryEnginePipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.loader = FinalPackageLoader()
        alignment_models: dict[str, str] = {}
        if self.settings.alignment_ar_model:
            alignment_models["ar"] = self.settings.alignment_ar_model
        if self.settings.alignment_en_model:
            alignment_models["en"] = self.settings.alignment_en_model
        self.transcriber = TranscriptionService(
            model_name=self.settings.whisper_model,
            ffmpeg_bin=self.settings.ffmpeg_bin,
            ffprobe_bin=self.settings.ffprobe_bin,
            forced_aligner=WhisperXForcedAligner(
                model_by_language=alignment_models or None,
                ffmpeg_bin=self.settings.ffmpeg_bin,
            ),
            require_forced_alignment=self.settings.require_forced_alignment,
        )
        self.vision = VisionService()
        self.cutout = CutoutService(allow_scene_fallback=self.settings.allow_scene_fallback)
        self.refinement = RefinementService()
        sam_raw = os.getenv("HEXA_SAM2_CHECKPOINT")
        self.cutout_pass2 = Pass2CutoutService(
            mask_backend=(
                SAM2MaskBackend(
                    Path(sam_raw).expanduser().resolve(),
                    config=os.getenv("HEXA_SAM2_CONFIG") or None,
                )
                if sam_raw
                else None
            ),
        )
        semantic_vlm = Qwen3VLBackend(self.settings.qwen3_vl_model)
        self.story = StoryPlanner(
            semantic_model_name=self.settings.semantic_text_model,
            semantic_model_required=self.settings.require_semantic_model,
        )
        self.story_sync_qa = StorySyncQA()
        self.reference = ReferenceAnalyzer().analyze()
        self.asset_manager = AssetManager()
        self.director = VisualDirector(semantic_vlm)
        self.choreography = ChoreographyDirector()
        self.text = TextPlanner()
        self.composition = CompositionPlanner()
        self.text_composition = TextCompositionPlanner()
        self.motion = MotionPlanner()
        self.motion_reference = ReferenceMotionEnforcer(self.reference.profile)
        self.text_motion = TextMotionPlanner()
        self.authoring_qa = AuthoringVisualQA(self.reference.profile)
        self.motion_interaction_qa = MotionInteractionQA()
        self.choreography_rhythm_qa = ChoreographyRhythmQA()
        self.scene_continuity_qa = SceneContinuityQA()
        self.rendered_motion_qa = RenderedMotionQA()
        self.rendered_visual_qa = RenderedVisualQA(self.settings.ffmpeg_bin)
        self.render_planner = RenderPlanner()
        self.renderer = FFmpegRenderer(self.settings.ffmpeg_bin)
        self.final = FinalExporter(self.settings.ffmpeg_bin)
        self.detector = RecoveryDetector(self.settings.ffprobe_bin, self.settings.ffmpeg_bin)
        self.recovery = RecoveryManager(Path.home() / ".hexa-storyengine" / "recovery")
        self.recovery_candidates = RecoveryCandidateEvaluator()

    def generate(
        self,
        *,
        package_path: Path,
        audio_path: Path,
        script_path: Path | None = None,
        output_name: str | None = None,
        job_id: str | None = None,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
    ) -> Path:
        job_id = job_id or uuid.uuid4().hex
        workspace = self.settings.work_root / job_id
        audio_path = audio_path.expanduser().resolve()

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, 0.01, "Checking storage and FFmpeg paths")
        self._assert_writable_directory(workspace, code="WORKSPACE_NOT_WRITABLE")
        self._assert_writable_directory(self.settings.output_root, code="OUTPUT_ROOT_NOT_WRITABLE")
        render_probe = self.renderer.preflight(workspace / "preflight")
        self.final.preflight(render_probe, workspace / "preflight")

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, 0.03, "Checking narration media")
        self.transcriber.preflight(audio_path)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, 0.05, "Reading Final Package")
        package = self.loader.load(package_path, workspace, script_path)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, 0.08, "Checking timing dependencies")
        self.transcriber.preflight(audio_path, package.script)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.transcription, 0.12, "Aligning narration")
        transcript = self.transcriber.transcribe(audio_path, package.script)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.vision, 0.22, "Understanding scene elements")
        detections = self.vision.analyze(package)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.cutout, 0.32, "Extracting visual assets")
        assets = self.cutout.extract(package, detections, workspace)
        pass1_count = len(assets)
        self._progress(
            progress,
            Stage.cutout,
            0.35,
            f"Pass1 ready: {pass1_count} authored assets across {len(package.scenes)} scenes",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.refinement, 0.38, "Checking isolated secondary visuals")
        assets = self._apply_refinement(package, assets, workspace)
        assets = self.asset_manager.normalize(assets)
        self._progress(
            progress,
            Stage.refinement,
            0.41,
            f"Pass2 ready: {len(assets)} assets ({len(assets) - pass1_count:+d} vs Pass1)",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.story, 0.43, "Building visual story")
        story = self.story.plan(package, transcript, assets)
        directions = self.director.plan(package, story, assets)
        choreography = self.choreography.plan(package, story, assets)
        max_scene_assets = max(
            (sum(1 for asset in assets if asset.scene_id == scene.id) for scene in package.scenes),
            default=0,
        )
        self._progress(
            progress,
            Stage.story,
            0.46,
            f"Story ready: {len(story)} beats; densest scene has {max_scene_assets} assets",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.text, 0.48, "Selecting narration-locked keywords")
        text = self.text.plan(
            transcript=transcript,
            story=story,
            assets=assets,
            package=package,
            choreography=choreography,
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.composition, 0.54, "Composing visuals and text")
        composition = self.composition.plan(story, assets, choreography, directions)
        text_composition = self.text_composition.plan(story, composition, text.cues, assets)
        self._progress(
            progress,
            Stage.composition,
            0.58,
            f"Composition locked to Final Package geometry; placed {len(text.cues)} text cues in negative space",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.motion, 0.63, "Planning visual and text entrances")
        motion = self.motion_reference.enforce(self.motion.plan(story, composition, choreography, assets=assets))
        text_motion = self.text_motion.plan(
            story,
            text.cues,
            text_composition,
            choreography,
            visual_motion=motion,
        )

        motion_interaction_report = self.motion_interaction_qa.inspect(
            story=story,
            motion=motion,
            composition=composition,
            choreography=choreography,
        )
        self.motion_interaction_qa.write(
            motion_interaction_report,
            workspace / "diagnostics" / "motion-interaction-qa.json",
        )
        self.motion_interaction_qa.require(motion_interaction_report)

        rhythm_report = self.choreography_rhythm_qa.inspect(
            story=story,
            motion=motion,
            choreography=choreography,
        )
        self.choreography_rhythm_qa.write(
            rhythm_report,
            workspace / "diagnostics" / "choreography-rhythm-qa.json",
        )
        self.choreography_rhythm_qa.require(rhythm_report)

        sync_report = self.story_sync_qa.inspect(story=story, motion=motion)
        self.story_sync_qa.write(
            sync_report,
            workspace / "diagnostics" / "story-sync-qa.json",
        )
        self.story_sync_qa.require(sync_report)

        authoring_report = StorytellingValidator.validate(
            package=package,
            story=story,
            choreography=choreography,
            composition=composition,
            motion=motion,
            text=text,
            text_motion=text_motion,
        )
        StorytellingValidator.write(
            authoring_report,
            workspace / "diagnostics" / "storytelling-authoring.json",
        )
        visual_report = self.authoring_qa.inspect(
            transcript=transcript,
            composition=composition,
            motion=motion,
            story=story,
            text=text,
            text_composition=text_composition,
            assets=assets,
        )
        if visual_report.text_layout_violations:
            text, text_composition, text_motion, visual_report = self._recover_text_layout(
                package_id=package.package_id,
                job_id=job_id,
                transcript=transcript,
                story=story,
                composition=composition,
                motion=motion,
                text=text,
                text_composition=text_composition,
                text_motion=text_motion,
                assets=assets,
                choreography=choreography,
                progress=progress,
                cancelled=cancelled,
                initial_report=visual_report,
            )
            authoring_report = StorytellingValidator.validate(
                package=package,
                story=story,
                choreography=choreography,
                composition=composition,
                motion=motion,
                text=text,
                text_motion=text_motion,
            )
            StorytellingValidator.write(
                authoring_report,
                workspace / "diagnostics" / "storytelling-authoring.json",
            )
        self.authoring_qa.write(
            visual_report,
            workspace / "diagnostics" / "authoring-visual-qa.json",
        )
        self.authoring_qa.require(visual_report, require_text=self.settings.require_text_layer)
        self._progress(
            progress,
            Stage.motion,
            0.67,
            (
                "Authoring QA passed: "
                f"{sync_report.anchored_assets} semantic sync anchors, "
                f"{sync_report.fallback_assets} conservative fallbacks; "
                f"{motion_interaction_report.checked_relations} relation timelines; "
                f"{rhythm_report.checked_entry_cohorts} focus cohorts; "
                "0 rhythm, visual layout, text layout, or short-motion violations"
            ),
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.render, 0.69, "Compiling render plan")
        plan, _ = self.render_planner.compile(
            transcript,
            assets,
            story,
            composition,
            motion,
            workspace,
            text=text,
            text_composition=text_composition,
            text_motion=text_motion,
        )

        plan = self._recover_plan(
            plan=plan,
            package=package,
            transcript=transcript,
            detections=detections,
            workspace=workspace,
            job_id=job_id,
            progress=progress,
            cancelled=cancelled,
        )
        AssetUsageValidator.validate(plan)
        continuity_report = self.scene_continuity_qa.inspect(
            story=plan.story,
            composition=plan.composition,
            motion=plan.motion,
        )
        self.scene_continuity_qa.write(
            continuity_report,
            workspace / "diagnostics" / "scene-continuity-qa.json",
        )
        self.scene_continuity_qa.require(continuity_report)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.render, 0.76, "Rendering story")
        video_only = self.renderer.render(plan, workspace / "render" / "video-only.mp4")
        rendered_motion_report = self.rendered_motion_qa.inspect(video=video_only, plan=plan)
        self.rendered_motion_qa.write(
            rendered_motion_report,
            workspace / "diagnostics" / "rendered-motion-qa.json",
        )
        self.rendered_motion_qa.require(rendered_motion_report)

        self._check_cancel(cancelled)
        output_file = self._output_path(package.package_id, output_name)
        self._progress(progress, Stage.final, 0.90, "Building final video")
        final_path = self.final.mux(video_only, audio_path, output_file)
        final_path = self._recover_final(
            final_path=final_path,
            video_only=video_only,
            audio_path=audio_path,
            plan=plan,
            package_id=package.package_id,
            job_id=job_id,
            workspace=workspace,
            progress=progress,
            cancelled=cancelled,
        )
        self.rendered_visual_qa.inspect(final_path, workspace / "diagnostics")
        self._check_cancel(cancelled)
        self._progress(progress, Stage.final, 1.0, "Video ready")
        return final_path

    def _recover_text_layout(
        self,
        *,
        package_id: str,
        job_id: str,
        transcript,
        story,
        composition,
        motion,
        text,
        text_composition,
        text_motion,
        assets,
        choreography,
        progress: ProgressCallback | None,
        cancelled: CancellationCallback | None,
        initial_report,
    ):
        """Self-heal text layout before allowing Authoring QA to stop the job.

        Recovery is deliberately bounded and monotonic:
        1. Recompose using final Motion visibility.
        2. Permit a small emergency scale reduction while keeping the same typography.
        3. If text is optional and geometry is genuinely impossible, remove only the
           unsafe cues instead of failing the entire video.

        Visual Composition, Story timing, Final Package semantics and visual Motion are
        never modified by this repair.
        """
        code = "TEXT_LAYOUT_REFERENCE_VIOLATION"
        report = initial_report
        current_text = text
        current_composition = text_composition
        current_motion = text_motion

        for attempt in (1, 2):
            self._check_cancel(cancelled)
            context = {
                "violations": list(report.text_layout_violations[:20]),
                "violation_count": len(report.text_layout_violations),
                "repair_level": attempt,
            }
            handler_result = self.recovery.handle(
                code=code,
                context=context,
                attempt=attempt,
            )
            if (
                handler_result is None
                or not handler_result.success
                or not handler_result.invalidate_from_stage
            ):
                break

            self._progress(
                progress,
                Stage.recovery,
                0.655,
                f"Repairing text layout ({attempt}/3)",
            )
            current_composition = self.text_composition.plan(
                story,
                composition,
                current_text.cues,
                assets,
                visual_motion=motion,
                repair_level=attempt,
            )
            current_motion = self.text_motion.plan(
                story,
                current_text.cues,
                current_composition,
                choreography,
                visual_motion=motion,
            )
            report = self.authoring_qa.inspect(
                transcript=transcript,
                composition=composition,
                motion=motion,
                story=story,
                text=current_text,
                text_composition=current_composition,
                assets=assets,
            )
            success = not report.text_layout_violations
            self.recovery.record_outcome(
                code=code,
                job_id=job_id,
                package_id=package_id,
                attempt=attempt,
                handler_result=handler_result,
                success=success,
                details={
                    "remaining_issue_count": len(report.text_layout_violations),
                    "repair_level": attempt,
                },
            )
            if success:
                return (
                    current_text,
                    current_composition,
                    current_motion,
                    report,
                )

        if report.text_layout_violations and not self.settings.require_text_layer:
            attempt = 3
            context = {
                "violations": list(report.text_layout_violations[:20]),
                "violation_count": len(report.text_layout_violations),
                "repair_level": attempt,
                "optional_text_fallback": True,
            }
            handler_result = self.recovery.handle(
                code=code,
                context=context,
                attempt=attempt,
            )
            if handler_result is not None and handler_result.success:
                dropped_ids: set[str] = set()
                degradation_cycles = 0
                max_degradation_cycles = min(
                    8,
                    max(1, len(current_text.cues)),
                )

                # Text placement is interdependent: removing one cue can move another
                # cue into newly available negative space and expose a different
                # collision. Therefore optional degradation must converge against the
                # *new* QA result, not assume one batch removal is sufficient.
                while (
                    report.text_layout_violations
                    and current_text.cues
                    and degradation_cycles < max_degradation_cycles
                ):
                    self._check_cancel(cancelled)
                    unsafe_ids = self._text_violation_cue_ids(
                        report.text_layout_violations,
                        current_text.cues,
                    )
                    if not unsafe_ids:
                        break
                    degradation_cycles += 1
                    dropped_ids.update(unsafe_ids)
                    self._progress(
                        progress,
                        Stage.recovery,
                        0.66,
                        (
                            "Resolving unsafe optional text "
                            f"(cycle {degradation_cycles}, drop {len(unsafe_ids)})"
                        ),
                    )
                    current_text = current_text.model_copy(
                        update={
                            "cues": [
                                cue
                                for cue in current_text.cues
                                if cue.id not in unsafe_ids
                            ]
                        }
                    )
                    current_composition = self.text_composition.plan(
                        story,
                        composition,
                        current_text.cues,
                        assets,
                        visual_motion=motion,
                        repair_level=2,
                    )
                    current_motion = self.text_motion.plan(
                        story,
                        current_text.cues,
                        current_composition,
                        choreography,
                        visual_motion=motion,
                    )
                    report = self.authoring_qa.inspect(
                        transcript=transcript,
                        composition=composition,
                        motion=motion,
                        story=story,
                        text=current_text,
                        text_composition=current_composition,
                        assets=assets,
                    )

                cleared_optional_text_layer = False
                if report.text_layout_violations:
                    # Optional text may never block a valid visual/video render.
                    # If bounded semantic degradation cannot converge, remove the
                    # remaining optional text layer as the final fail-safe. Visual
                    # Composition, Story, Motion and Final Package geometry are
                    # deliberately untouched.
                    cleared_optional_text_layer = True
                    dropped_ids.update(cue.id for cue in current_text.cues)
                    self._progress(
                        progress,
                        Stage.recovery,
                        0.665,
                        "Disabling remaining optional text to preserve video render",
                    )
                    current_text = current_text.model_copy(update={"cues": []})
                    current_composition = self.text_composition.plan(
                        story,
                        composition,
                        current_text.cues,
                        assets,
                        visual_motion=motion,
                        repair_level=2,
                    )
                    current_motion = self.text_motion.plan(
                        story,
                        current_text.cues,
                        current_composition,
                        choreography,
                        visual_motion=motion,
                    )
                    report = self.authoring_qa.inspect(
                        transcript=transcript,
                        composition=composition,
                        motion=motion,
                        story=story,
                        text=current_text,
                        text_composition=current_composition,
                        assets=assets,
                    )

                success = not report.text_layout_violations
                self.recovery.record_outcome(
                    code=code,
                    job_id=job_id,
                    package_id=package_id,
                    attempt=attempt,
                    handler_result=handler_result,
                    success=success,
                    details={
                        "remaining_issue_count": len(report.text_layout_violations),
                        "degradation_cycles": degradation_cycles,
                        "dropped_optional_text_cues": sorted(dropped_ids),
                        "cleared_optional_text_layer": cleared_optional_text_layer,
                    },
                )

        return current_text, current_composition, current_motion, report

    @staticmethod
    def _text_violation_cue_ids(
        violations: tuple[str, ...] | list[str],
        cues,
    ) -> set[str]:
        """Choose the minimum semantic text degradation needed to clear QA.

        A visual/offscreen violation belongs to that cue and must remove it if bounded
        repair failed. A text/text collision needs only one side removed: preserve the
        higher-priority semantic cue, then prefer the earlier/shorter phrase on ties.
        """
        cue_by_id = {cue.id: cue for cue in cues}
        unsafe: set[str] = set()
        for violation in violations:
            parts = str(violation).split(":")
            ids = [token for token in parts if token in cue_by_id]
            if not ids:
                continue
            if "text_text_overlap" in parts and len(ids) >= 2:
                candidates = [cue_by_id[cue_id] for cue_id in ids]
                loser = min(
                    candidates,
                    key=lambda cue: (
                        int(cue.priority),
                        -float(cue.spoken_start),
                        -len(cue.text),
                        cue.id,
                    ),
                )
                unsafe.add(loser.id)
                continue
            unsafe.update(ids)
        return unsafe

    def _apply_refinement(self, package, assets, workspace: Path):
        mode = self.settings.refinement_mode
        if mode in {"off", "pass1", "disabled"}:
            return assets
        if mode in {"vnext", "pass2_vnext", "hybrid"}:
            unit_types = {
                scene.id: [str(unit.get("type") or "") for unit in scene.units]
                for scene in package.scenes
            }
            return self.cutout_pass2.refine(
                assets,
                workspace,
                scene_unit_types=unit_types,
            )
        return self.refinement.refine(assets, workspace)

    def _recover_plan(
        self,
        *,
        plan: RenderPlan,
        package,
        transcript,
        detections,
        workspace: Path,
        job_id: str,
        progress: ProgressCallback | None,
        cancelled: CancellationCallback | None,
    ) -> RenderPlan:
        attempts: dict[str, int] = {}
        while True:
            self._check_cancel(cancelled)
            issues = self.detector.inspect_plan(plan)
            if not issues:
                return plan
            issue = issues[0]
            attempt = attempts.get(issue.code, 0) + 1
            attempts[issue.code] = attempt
            result = self.recovery.handle(code=issue.code, context=issue.context, attempt=attempt)
            if result is None or not result.success or not result.invalidate_from_stage:
                raise self._unresolved(issue)

            self._progress(progress, Stage.recovery, 0.70, f"Recovering {issue.code}")
            candidate = self._rebuild_plan(
                invalidate_from=result.invalidate_from_stage,
                current=plan,
                package=package,
                transcript=transcript,
                detections=detections,
                workspace=workspace,
            )
            remaining = self.detector.inspect_plan(candidate)
            assessment = self.recovery_candidates.evaluate(
                target=issue,
                before_issues=issues,
                after_issues=remaining,
                before_plan=plan,
                candidate_plan=candidate,
            )
            self.recovery.record_outcome(
                code=issue.code,
                job_id=job_id,
                package_id=package.package_id,
                attempt=attempt,
                handler_result=result,
                success=assessment.accepted,
                details=assessment.to_details(),
            )
            if assessment.accepted:
                plan = candidate

    def _rebuild_plan(
        self,
        *,
        invalidate_from: str,
        current: RenderPlan,
        package,
        transcript,
        detections,
        workspace: Path,
    ) -> RenderPlan:
        assets = current.assets
        story = current.story
        text = current.text
        composition = current.composition
        text_composition = current.text_composition
        motion = current.motion
        text_motion = current.text_motion
        order = ["cutout", "refinement", "story", "text", "composition", "motion", "render"]
        try:
            start = order.index(invalidate_from)
        except ValueError:
            start = len(order) - 1

        if start <= 0:
            assets = self.cutout.extract(package, detections, workspace)
        if start <= 1:
            assets = self._apply_refinement(package, assets, workspace)
        assets = self.asset_manager.normalize(list(assets))
        if start <= 2:
            story = self.story.plan(package, transcript, assets)
        directions = self.director.plan(package, story, assets)
        choreography = self.choreography.plan(package, story, assets)
        if start <= 3:
            text = self.text.plan(
                transcript=transcript,
                story=story,
                assets=assets,
                package=package,
                choreography=choreography,
            )
        if start <= 4:
            composition = self.composition.plan(story, assets, choreography, directions)
            text_composition = self.text_composition.plan(story, composition, text.cues, assets)
        if start <= 5:
            motion = self.motion_reference.enforce(self.motion.plan(story, composition, choreography, assets=assets))
            text_motion = self.text_motion.plan(
                story,
                text.cues,
                text_composition,
                choreography,
                visual_motion=motion,
            )
        plan, _ = self.render_planner.compile(
            transcript,
            assets,
            story,
            composition,
            motion,
            workspace,
            text=text,
            text_composition=text_composition,
            text_motion=text_motion,
        )
        return plan

    def _recover_final(
        self,
        *,
        final_path: Path,
        video_only: Path,
        audio_path: Path,
        plan: RenderPlan,
        package_id: str,
        job_id: str,
        workspace: Path,
        progress: ProgressCallback | None,
        cancelled: CancellationCallback | None,
    ) -> Path:
        attempts: dict[str, int] = {}
        while True:
            self._check_cancel(cancelled)
            issues = self.detector.inspect_final(final_path, audio_path)
            if not issues:
                return final_path
            issue = issues[0]
            attempt = attempts.get(issue.code, 0) + 1
            attempts[issue.code] = attempt
            result = self.recovery.handle(code=issue.code, context=issue.context, attempt=attempt)
            if result is None or not result.success:
                raise self._unresolved(issue)

            self._progress(progress, Stage.recovery, 0.94, f"Recovering {issue.code}")
            candidate_final = workspace / "render" / f"recovered-final-{issue.code}-{attempt}.mp4"
            candidate_video = video_only
            if result.invalidate_from_stage == "render":
                candidate_video = self.renderer.render(
                    plan,
                    workspace / "render" / f"recovered-video-{issue.code}-{attempt}.mp4",
                    strict_boundary_coverage=(issue.code == "VISUAL_WHITE_FLASH"),
                )
                candidate_final = self.final.mux(candidate_video, audio_path, candidate_final)
            elif result.invalidate_from_stage == "final":
                candidate_final = self.final.mux(video_only, audio_path, candidate_final)
            else:
                raise self._unresolved(issue)

            remaining = self.detector.inspect_final(candidate_final, audio_path)
            assessment = self.recovery_candidates.evaluate(
                target=issue,
                before_issues=issues,
                after_issues=remaining,
            )
            self.recovery.record_outcome(
                code=issue.code,
                job_id=job_id,
                package_id=package_id,
                attempt=attempt,
                handler_result=result,
                success=assessment.accepted,
                details=assessment.to_details(),
            )
            if assessment.accepted:
                final_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate_final, final_path)
                if result.invalidate_from_stage == "render":
                    video_only = candidate_video

    @staticmethod
    def _assert_writable_directory(path: Path, *, code: str) -> None:
        probe = path / f".hexa-write-probe-{uuid.uuid4().hex}"
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe.write_bytes(b"ok")
        except OSError as exc:
            raise StageFailedError(
                "required directory is not writable",
                details={"code": code, "path": str(path), "error": str(exc)},
            ) from exc
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                pass

    def _output_path(self, package_id: str, output_name: str | None) -> Path:
        name = output_name or f"{package_id}.mp4"
        if Path(name).name != name:
            raise StageFailedError("output name must be a file name, not a path")
        if not name.lower().endswith(".mp4"):
            name += ".mp4"
        self.settings.output_root.mkdir(parents=True, exist_ok=True)
        return self.settings.output_root / name

    @staticmethod
    def _progress(callback: ProgressCallback | None, stage: Stage, value: float, message: str) -> None:
        if callback:
            callback(stage, value, message)

    @staticmethod
    def _check_cancel(callback: CancellationCallback | None) -> None:
        if callback and callback():
            raise GenerationCancelledError("generation cancelled by user")

    @staticmethod
    def _unresolved(issue: DetectedIssue) -> HexaError:
        return StageFailedError(
            f"unresolved recovery issue: {issue.code}",
            details={"code": issue.code, "message": issue.message, **issue.context},
        )
