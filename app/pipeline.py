from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Callable

from app.choreography import ChoreographyDirector
from app.shared.handoff import LayerHandoffValidator
from app.assets import AssetManager
from app.director import Qwen3VLBackend, VisualDirector
from app.reference import ReferenceAnalyzer
from app.composition import CompositionPlanner, TextCompositionPlanner
from app.config import Settings
from app.cutout import CutoutService, Pass2CutoutService
from app.final import FinalExporter, FinalMediaVerifier
from app.canonical import CanonicalPackage
from app.final_package import FinalPackageLoader
from app.models import Stage
from app.motion import MotionPlanner, ReferenceMotionEnforcer, TextMotionPlanner
from app.refinement import RefinementService
from app.cutout.pass2.segmenter import SAM2MaskBackend
from app.render import RenderPlanner
from app.render.evidence import RenderedVisualEvidence
from app.render.verification import EncodedMotionVerifier
from app.render.renderer import FFmpegRenderer
from app.shared.errors import (
    GenerationCancelledError,
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
        self.reference = ReferenceAnalyzer().analyze()
        self.asset_manager = AssetManager()
        self.director = VisualDirector(semantic_vlm)
        self.choreography = ChoreographyDirector()
        self.handoff_contracts = LayerHandoffValidator()
        self.text = TextPlanner()
        self.composition = CompositionPlanner()
        self.text_composition = TextCompositionPlanner()
        self.motion = MotionPlanner()
        self.motion_reference = ReferenceMotionEnforcer(self.reference.profile)
        self.text_motion = TextMotionPlanner()
        self.encoded_motion_verifier = EncodedMotionVerifier()
        self.rendered_visual_evidence = RenderedVisualEvidence(self.settings.ffmpeg_bin)
        self.render_planner = RenderPlanner()
        self.renderer = FFmpegRenderer(self.settings.ffmpeg_bin)
        self.final = FinalExporter(self.settings.ffmpeg_bin)
        self.final_media = FinalMediaVerifier(
            self.settings.ffprobe_bin,
            self.settings.ffmpeg_bin,
        )

    def generate(
        self,
        *,
        package_path: Path,
        audio_path: Path,
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
        package = self.loader.load(package_path, workspace)

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
        self.handoff_contracts.require_assets_for_story(package=package, assets=assets)
        self._progress(
            progress,
            Stage.refinement,
            0.41,
            f"Pass2 ready: {len(assets)} assets ({len(assets) - pass1_count:+d} vs Pass1)",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.story, 0.43, "Building visual story")
        try:
            story = self.story.plan(package, transcript, assets)
        finally:
            # Candidates, scores, selected/rejected carriers and confidence per scene:
            # written on failure too, so a blocked render still explains itself.
            (workspace / "semantic-carrier-resolution.json").write_text(
                json.dumps(self.story.carrier_resolution_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        # Per-asset proof of why each required authored asset is (or is merged)
        # on screen; failures carry the same records in their error details.
        (workspace / "semantic-carrier-audit.json").write_text(
            json.dumps(
                {
                    "semantic_carriers": self.story.semantic_carrier_audit,
                    "hidden_content": self.story.hidden_content_audit,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.handoff_contracts.require_story_for_choreography(
            package=package, transcript=transcript, assets=assets, story=story
        )
        directions = self.director.plan(package, story, assets)
        choreography = self.choreography.plan(package, story, assets)
        self.handoff_contracts.require_choreography_for_composition(
            story=story, assets=assets, choreography=choreography
        )
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
        self.handoff_contracts.require_text_for_composition(
            transcript=transcript, story=story, assets=assets, text=text
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.composition, 0.54, "Composing authored visuals")
        composition = self.composition.plan(story, assets, choreography, directions)
        self.handoff_contracts.require_composition_for_motion(
            story=story, assets=assets, composition=composition
        )
        self._progress(
            progress,
            Stage.composition,
            0.57,
            "Visual Composition locked to Final Package geometry",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.motion, 0.61, "Planning final visual motion")
        motion = self.motion_reference.enforce(
            self.motion.plan(story, composition, choreography, assets=assets)
        )
        self.handoff_contracts.require_motion_for_text_and_render(
            story=story,
            assets=assets,
            composition=composition,
            choreography=choreography,
            motion=motion,
        )

        self._check_cancel(cancelled)
        self._progress(
            progress,
            Stage.text,
            0.63,
            "Placing text against final visual visibility windows",
        )
        text, text_composition, text_motion = self._compose_text_against_visual_motion(
            story=story,
            composition=composition,
            motion=motion,
            text=text,
            assets=assets,
            choreography=choreography,
        )
        self.handoff_contracts.require_text_render_contract(
            story=story,
            assets=assets,
            text=text,
            text_composition=text_composition,
            text_motion=text_motion,
        )
        self._progress(
            progress,
            Stage.composition,
            0.64,
            f"Placed {len(text.cues)} text cues against final visual lifetimes",
        )

        self._progress(
            progress,
            Stage.motion,
            0.67,
            (
                "Owner contracts passed for Story, Composition, Motion, and Text"
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

        self._check_cancel(cancelled)
        self._progress(progress, Stage.render, 0.76, "Rendering story")
        video_only = self.renderer.render(plan, workspace / "render" / "video-only.mp4")
        rendered_motion_report = self.encoded_motion_verifier.inspect(video=video_only, plan=plan)
        self.encoded_motion_verifier.write(
            rendered_motion_report,
            workspace / "diagnostics" / "rendered-motion-qa.json",
        )
        self.encoded_motion_verifier.require(rendered_motion_report)

        self._check_cancel(cancelled)
        output_file = self._output_path(package.package_id, output_name)
        self._progress(progress, Stage.final, 0.90, "Building final video")
        final_path = self.final.mux(video_only, audio_path, output_file)
        self.final_media.require(final_path, audio_path)
        self.rendered_visual_evidence.inspect(final_path, workspace / "diagnostics")
        self._check_cancel(cancelled)
        self._progress(progress, Stage.final, 1.0, "Video ready")
        return final_path

    def _compose_text_against_visual_motion(
        self,
        *,
        story,
        composition,
        motion,
        text,
        assets,
        choreography,
    ):
        """Author the final legal text set against final visual lifetimes once."""
        text_composition = self.text_composition.plan(
            story,
            composition,
            text.cues,
            assets,
            visual_motion=motion,
        )
        accepted_ids = {
            item.text_cue_id
            for beat in text_composition
            for item in beat.items
        }
        if len(accepted_ids) != len(text.cues):
            if self.settings.require_text_layer:
                missing = sorted(cue.id for cue in text.cues if cue.id not in accepted_ids)
                raise StageFailedError(
                    "Required text cannot be placed safely",
                    details={
                        "code": "TEXT_LAYOUT_REFERENCE_VIOLATION",
                        "text_cue_ids": missing,
                    },
                )
            text = text.model_copy(
                update={"cues": [cue for cue in text.cues if cue.id in accepted_ids]}
            )
        text_motion = self.text_motion.plan(
            story,
            text.cues,
            text_composition,
            choreography,
            visual_motion=motion,
        )
        return text, text_composition, text_motion

    def _apply_refinement(
        self,
        package: CanonicalPackage,
        assets,
        workspace: Path,
    ):
        mode = self.settings.refinement_mode
        if mode in {"off", "pass1", "disabled"}:
            return assets
        if mode in {"vnext", "pass2_vnext", "hybrid"}:
            unit_types = {
                scene.id: [str(unit.type or "") for unit in scene.units]
                for scene in package.scenes
            }
            return self.cutout_pass2.refine(
                assets,
                workspace,
                scene_unit_types=unit_types,
            )
        return self.refinement.refine(assets, workspace)

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

