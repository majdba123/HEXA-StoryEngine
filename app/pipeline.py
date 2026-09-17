from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Callable

from app.choreography import ChoreographyDirector
from app.composition import CompositionPlanner, TextCompositionPlanner
from app.config import Settings
from app.diagnostics import AssetUsageValidator, StorytellingValidator
from app.cutout import CutoutService, Pass2CutoutService
from app.final import FinalExporter
from app.input import FinalPackageLoader
from app.models import RenderPlan, Stage
from app.motion import MotionPlanner, TextMotionPlanner
from app.recovery.detector import DetectedIssue, RecoveryDetector
from app.refinement import RefinementService
from app.cutout.pass2.semantic import FlorenceSemanticBackend
from app.cutout.pass2.segmenter import SAM2MaskBackend
from app.recovery.manager import RecoveryManager
from app.render import RenderPlanner
from app.render.renderer import FFmpegRenderer
from app.shared.errors import (
    GenerationCancelledError,
    HexaError,
    StageFailedError,
)
from app.story import StoryPlanner
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
            ffprobe_bin=self.settings.ffprobe_bin,
            forced_aligner=WhisperXForcedAligner(
                model_by_language=alignment_models or None,
            ),
            require_forced_alignment=self.settings.require_forced_alignment,
        )
        self.vision = VisionService()
        self.cutout = CutoutService(allow_scene_fallback=self.settings.allow_scene_fallback)
        self.refinement = RefinementService()
        florence_raw = os.getenv("HEXA_FLORENCE_MODEL")
        sam_raw = os.getenv("HEXA_SAM2_CHECKPOINT")
        self.cutout_pass2 = Pass2CutoutService(
            semantic_backend=(
                FlorenceSemanticBackend(Path(florence_raw).expanduser().resolve())
                if florence_raw
                else None
            ),
            mask_backend=(
                SAM2MaskBackend(
                    Path(sam_raw).expanduser().resolve(),
                    config=os.getenv("HEXA_SAM2_CONFIG") or None,
                )
                if sam_raw
                else None
            ),
        )
        self.story = StoryPlanner()
        self.choreography = ChoreographyDirector()
        self.text = TextPlanner()
        self.composition = CompositionPlanner()
        self.text_composition = TextCompositionPlanner()
        self.motion = MotionPlanner()
        self.text_motion = TextMotionPlanner()
        self.render_planner = RenderPlanner()
        self.renderer = FFmpegRenderer(self.settings.ffmpeg_bin)
        self.final = FinalExporter(self.settings.ffmpeg_bin)
        self.detector = RecoveryDetector(self.settings.ffprobe_bin, self.settings.ffmpeg_bin)
        self.recovery = RecoveryManager(Path.home() / ".hexa-storyengine" / "recovery")

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
        workspace.mkdir(parents=True, exist_ok=True)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, 0.04, "Reading Final Package")
        package = self.loader.load(package_path, workspace, script_path)
        audio_path = audio_path.expanduser().resolve()
        if not audio_path.is_file():
            raise StageFailedError("audio file not found", details={"path": str(audio_path)})

        self._check_cancel(cancelled)
        self._progress(progress, Stage.transcription, 0.12, "Aligning narration")
        transcript = self.transcriber.transcribe(audio_path, package.script)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.vision, 0.22, "Understanding scene elements")
        detections = self.vision.analyze(package)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.cutout, 0.32, "Extracting visual assets")
        assets = self.cutout.extract(package, detections, workspace)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.refinement, 0.38, "Checking isolated secondary visuals")
        assets = self._apply_refinement(package, assets, workspace)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.story, 0.43, "Building visual story")
        story = self.story.plan(package, transcript, assets)
        choreography = self.choreography.plan(package, story, assets)

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
        composition = self.composition.plan(story, assets, choreography)
        text_composition = self.text_composition.plan(story, composition, text.cues, assets)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.motion, 0.63, "Planning visual and text entrances")
        motion = self.motion.plan(story, composition, choreography)
        text_motion = self.text_motion.plan(
            story, text.cues, text_composition, choreography
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

        self._check_cancel(cancelled)
        self._progress(progress, Stage.render, 0.76, "Rendering story")
        video_only = self.renderer.render(plan, workspace / "render" / "video-only.mp4")

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
        self._check_cancel(cancelled)
        self._progress(progress, Stage.final, 1.0, "Video ready")
        return final_path

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
            plan = self._rebuild_plan(
                invalidate_from=result.invalidate_from_stage,
                current=plan,
                package=package,
                transcript=transcript,
                detections=detections,
                workspace=workspace,
            )
            remaining = self.detector.inspect_plan(plan)
            success = not any(item.code == issue.code for item in remaining)
            self.recovery.record_outcome(
                code=issue.code,
                job_id=job_id,
                package_id=package.package_id,
                attempt=attempt,
                handler_result=result,
                success=success,
                details={"remaining_issue_count": len(remaining)},
            )
            if not success and attempt >= 3:
                raise self._unresolved(issue)

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
        if start <= 2:
            story = self.story.plan(package, transcript, assets)
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
            composition = self.composition.plan(story, assets, choreography)
            text_composition = self.text_composition.plan(story, composition, text.cues, assets)
        if start <= 5:
            motion = self.motion.plan(story, composition, choreography)
            text_motion = self.text_motion.plan(
                story, text.cues, text_composition, choreography
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
            if result.invalidate_from_stage == "render":
                video_only = self.renderer.render(
                    plan,
                    workspace / "render" / f"recovered-{attempt}.mp4",
                )
                final_path = self.final.mux(video_only, audio_path, final_path)
            elif result.invalidate_from_stage == "final":
                final_path = self.final.mux(video_only, audio_path, final_path)
            else:
                raise self._unresolved(issue)

            remaining = self.detector.inspect_final(final_path, audio_path)
            success = not any(item.code == issue.code for item in remaining)
            self.recovery.record_outcome(
                code=issue.code,
                job_id=job_id,
                package_id=package_id,
                attempt=attempt,
                handler_result=result,
                success=success,
                details={"remaining_issue_count": len(remaining)},
            )
            if not success and attempt >= 3:
                raise self._unresolved(issue)

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
