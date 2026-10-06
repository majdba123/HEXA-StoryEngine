from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.choreography import ChoreographyDirector, ChoreographyPlan
from app.shared.handoff import LayerHandoffValidator
from app.assets import AssetManager
from app.boundary import SceneBoundaryPlanner
from app.director import Qwen3VLBackend, VisualDirector
from app.reference import ReferenceAnalyzer
from app.composition import CompositionPlanner, TextCompositionPlanner
from app.config import PROJECT_ROOT, Settings
from app.cutout import CutoutService, Pass2CutoutService
from app.final import FinalExporter, FinalMediaVerifier
from app.final.bundle import ExportBundleWriter, ExportRoot, ReservedBundle, export_slug
from app.canonical import CanonicalPackage
from app.final_package import FinalPackageLoader
from app.models import RenderPlan, Stage, StoryBeat, TextPlan, Transcript, VisualAsset
from app.motion import EntryMotionGrammar, MotionPlanner, ReferenceMotionEnforcer, TextMotionPlanner
from app.motion.semantic_reference import MotionSemanticReference
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
from app.shared.process import run_hidden
from app.story import StoryPlanner
from app.targets import (
    REFERENCE_TARGET,
    SUPPORTED_VISUAL_TARGETS,
    VisualTargetProfile,
    visual_target,
)
from app.targets.parity import fingerprint, plan_fingerprint, semantic_differences
from app.text import TextPlanner
from app.transcription import TranscriptionService
from app.transcription.alignment import WhisperXForcedAligner
from app.vision import VisionService

ProgressCallback = Callable[[Stage, float, str], None]
CancellationCallback = Callable[[], bool]


@dataclass(slots=True)
class SharedSemanticPlan:
    """Format-independent result of one generation: computed once, used by every target."""

    package: CanonicalPackage
    transcript: Transcript
    assets: list[VisualAsset]
    story: list[StoryBeat]
    directions: list
    choreography: ChoreographyPlan
    text: TextPlan
    workspace: Path
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TargetOutput:
    target_id: str
    path: Path
    width: int
    height: int
    fps: int
    duration: float
    frame_count: int
    render_plan_path: Path
    render_plan_fingerprint: str
    encoded_motion_ok: bool
    final_media_ok: bool
    media: dict[str, Any]
    seconds: float
    worker_count: int | None


@dataclass(frozen=True, slots=True)
class GenerationBundleResult:
    """Both production outputs of one Final Package generation, published as ``vN``."""

    package_id: str
    slug: str
    version: int
    directory: Path
    manifest_path: Path
    outputs: dict[str, TargetOutput]

    @property
    def youtube(self) -> TargetOutput:
        return self.outputs["YOUTUBE_16_9"]

    @property
    def reels(self) -> TargetOutput:
        return self.outputs["REELS_9_16"]


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
        self.entry_grammar = EntryMotionGrammar()
        self.scene_boundaries = SceneBoundaryPlanner()
        self.text_motion = TextMotionPlanner()
        self.encoded_motion_verifier = EncodedMotionVerifier()
        self.rendered_visual_evidence = RenderedVisualEvidence(self.settings.ffmpeg_bin)
        self.render_planner = RenderPlanner()
        self.renderer = FFmpegRenderer(
            self.settings.ffmpeg_bin, resources=self.settings.render_resources,
            defer_cleanup=True,
        )
        self.final = FinalExporter(self.settings.ffmpeg_bin)
        self.final_media = FinalMediaVerifier(
            self.settings.ffprobe_bin,
            self.settings.ffmpeg_bin,
        )

    # -- single-format path (certified 16:9; kept for existing callers) -----------------
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
        """Render the reference 16:9 output only into ``output_root`` (legacy contract)."""
        job_id = job_id or uuid.uuid4().hex
        workspace = self.settings.work_root / job_id
        audio_path = audio_path.expanduser().resolve()

        self._preflight(workspace, audio_path, progress, cancelled)
        self._assert_writable_directory(self.settings.output_root, code="OUTPUT_ROOT_NOT_WRITABLE")
        shared = self._plan_shared(
            package_path=package_path, audio_path=audio_path, workspace=workspace,
            progress=progress, cancelled=cancelled,
        )
        target = REFERENCE_TARGET
        plan = self._plan_target(
            shared, target, workspace, progress=progress, cancelled=cancelled, announce=False,
        )
        output_file = self._output_path(shared.package.package_id, output_name)
        result = self._render_target(
            shared, target, plan, workspace, output_file, audio_path,
            progress=progress, cancelled=cancelled, span=(0.76, 0.90), announce=False,
        )
        self._progress(progress, Stage.final, 1.0, "Video ready")
        return result.path

    # -- production dual-format path ------------------------------------------------------
    def generate_bundle(
        self,
        *,
        package_path: Path,
        audio_path: Path,
        job_id: str | None = None,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
        targets: tuple[VisualTargetProfile, ...] = SUPPORTED_VISUAL_TARGETS,
    ) -> GenerationBundleResult:
        """One Final Package -> every supported format, published as ``<root>/<PKG>/vN``.

        Expensive semantic stages (alignment, Vision, Pass1/Pass2, Story, Choreography,
        Text selection) run once. Each target then authors its own geometry through the
        same Composition/Motion/Text/Boundary engines and renders its own RenderPlan
        sequentially. The bundle is published only after every output rendered and
        passed encoded-motion and final-media verification and the manifest is written.
        """
        if not targets or targets[0] is not REFERENCE_TARGET:
            raise StageFailedError(
                "bundle targets must start with the reference target",
                details={"code": "TARGET_SET_INVALID"},
            )
        job_id = job_id or uuid.uuid4().hex
        workspace = self.settings.work_root / job_id
        audio_path = audio_path.expanduser().resolve()
        started = time.perf_counter()

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, 0.005, "Checking export root")
        export_root = ExportRoot(
            self.settings.resolved_export_root, min_free_bytes=self.settings.export_min_free_bytes,
        ).validate()
        self._preflight(workspace, audio_path, progress, cancelled)
        self._require_free_space(self.settings.work_root, self.settings.work_min_free_bytes)

        shared = self._plan_shared(
            package_path=package_path, audio_path=audio_path, workspace=workspace,
            progress=progress, cancelled=cancelled, span=0.44,
        )
        shared.timings["shared_semantic_seconds"] = round(time.perf_counter() - started, 3)

        # Plan every target before any heavy render: a semantic divergence or a target
        # that cannot be composed fails before encode time is spent.
        plans: dict[str, RenderPlan] = {}
        workspaces: dict[str, Path] = {}
        plan_seconds: dict[str, float] = {}
        for index, target in enumerate(targets):
            begin = time.perf_counter()
            target_ws = self._target_workspace(workspace, target)
            workspaces[target.target_id] = target_ws
            reference = plans.get(REFERENCE_TARGET.target_id)
            plans[target.target_id] = self._plan_target(
                shared, target, target_ws, progress=progress, cancelled=cancelled,
                span=(0.46 + 0.04 * index, 0.50 + 0.04 * index),
                semantic_reference=(
                    MotionSemanticReference.from_plan(reference) if reference is not None else None
                ),
            )
            plan_seconds[target.target_id] = time.perf_counter() - begin
        reference_plan = plans[REFERENCE_TARGET.target_id]
        for target in targets[1:]:
            differences = semantic_differences(reference_plan, plans[target.target_id])
            if differences:
                raise StageFailedError(
                    "output formats diverged semantically",
                    details={
                        "code": "TARGET_SEMANTIC_DIVERGENCE",
                        "target_id": target.target_id,
                        "differences": differences[:20],
                    },
                )

        slug = export_slug(shared.package.project_slug or shared.package.package_id)
        writer = ExportBundleWriter(export_root.root)
        bundle = writer.reserve(slug)
        outputs: dict[str, TargetOutput] = {}
        try:
            render_span = (0.56, 0.97)
            step = (render_span[1] - render_span[0]) / len(targets)
            for index, target in enumerate(targets):
                begin = time.perf_counter()
                output = self._render_target(
                    shared, target, plans[target.target_id], workspaces[target.target_id],
                    bundle.output_path(target.output_suffix), audio_path,
                    progress=progress, cancelled=cancelled,
                    span=(render_span[0] + step * index, render_span[0] + step * (index + 1)),
                )
                seconds = plan_seconds[target.target_id] + (time.perf_counter() - begin)
                outputs[target.target_id] = _with_seconds(output, seconds)
            self._check_cancel(cancelled)
            self._progress(progress, Stage.final, 0.98, "Writing export manifest")
            manifest = self._manifest(
                shared=shared, package_path=package_path, bundle=bundle,
                outputs=outputs, plans=plans, total_seconds=time.perf_counter() - started,
            )
            manifest_path = writer.publish(bundle, manifest)
        except BaseException as exc:
            failed = writer.fail(bundle, exc, diagnostics={
                "workspace": str(workspace),
                "rendered_targets": sorted(outputs),
            })
            # Keep the workspace diagnostics; record where the failed bundle went.
            try:
                (workspace / "export-failure.json").write_text(
                    json.dumps({"bundle": str(failed), "error": str(exc)[:2000]}, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass
            raise
        self._progress(progress, Stage.final, 1.0, f"Bundle ready: {slug} {bundle.name}")
        return GenerationBundleResult(
            package_id=shared.package.package_id,
            slug=slug,
            version=bundle.version,
            directory=bundle.directory,
            manifest_path=manifest_path,
            outputs=outputs,
        )

    # -- shared semantic stages -----------------------------------------------------------
    def _preflight(
        self,
        workspace: Path,
        audio_path: Path,
        progress: ProgressCallback | None,
        cancelled: CancellationCallback | None,
    ) -> None:
        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, 0.01, "Checking storage and FFmpeg paths")
        self._assert_writable_directory(workspace, code="WORKSPACE_NOT_WRITABLE")
        render_probe = self.renderer.preflight(workspace / "preflight")
        self.final.preflight(render_probe, workspace / "preflight")

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, 0.03, "Checking narration media")
        self.transcriber.preflight(audio_path)

    def _plan_shared(
        self,
        *,
        package_path: Path,
        audio_path: Path,
        workspace: Path,
        progress: ProgressCallback | None,
        cancelled: CancellationCallback | None,
        span: float = 0.48,
    ) -> SharedSemanticPlan:
        scale = span / 0.48

        def at(value: float) -> float:
            return value * scale

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, at(0.05), "Reading Final Package")
        package = self.loader.load(package_path, workspace)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.input, at(0.08), "Checking timing dependencies")
        self.transcriber.preflight(audio_path, package.script)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.transcription, at(0.12), "Aligning narration")
        transcript = self.transcriber.transcribe(audio_path, package.script)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.vision, at(0.22), "Understanding scene elements")
        detections = self.vision.analyze(package)

        self._check_cancel(cancelled)
        self._progress(progress, Stage.cutout, at(0.32), "Extracting visual assets")
        assets = self.cutout.extract(package, detections, workspace)
        pass1_count = len(assets)
        self._progress(
            progress,
            Stage.cutout,
            at(0.35),
            f"Pass1 ready: {pass1_count} authored assets across {len(package.scenes)} scenes",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.refinement, at(0.38), "Checking isolated secondary visuals")
        assets = self._apply_refinement(package, assets, workspace)
        assets = self.asset_manager.normalize(assets)
        self.handoff_contracts.require_assets_for_story(package=package, assets=assets)
        self._progress(
            progress,
            Stage.refinement,
            at(0.41),
            f"Pass2 ready: {len(assets)} assets ({len(assets) - pass1_count:+d} vs Pass1)",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.story, at(0.43), "Building visual story")
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
            at(0.46),
            f"Story ready: {len(story)} beats; densest scene has {max_scene_assets} assets",
        )

        self._check_cancel(cancelled)
        self._progress(progress, Stage.text, at(0.48), "Selecting narration-locked keywords")
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
        return SharedSemanticPlan(
            package=package,
            transcript=transcript,
            assets=assets,
            story=story,
            directions=directions,
            choreography=choreography,
            text=text,
            workspace=workspace,
        )

    # -- per-target spatial authoring -----------------------------------------------------
    def _plan_target(
        self,
        shared: SharedSemanticPlan,
        target: VisualTargetProfile,
        workspace: Path,
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
        span: tuple[float, float] = (0.54, 0.69),
        announce: bool = True,
        semantic_reference: MotionSemanticReference | None = None,
    ) -> RenderPlan:
        """Composition -> Motion -> Text layout -> Boundaries -> RenderPlan for one target.

        Every engine here is shared; the active target only supplies frame size, safe
        zones and the spatial projection policy of Composition.
        """
        story, assets, choreography = shared.story, shared.assets, shared.choreography
        prefix = f"{target.output_suffix.title()}: " if announce else ""
        lo, hi = span

        def at(value: float) -> float:
            return lo + (hi - lo) * (value - 0.54) / (0.69 - 0.54)

        workspace.mkdir(parents=True, exist_ok=True)
        with visual_target(target):
            self._check_cancel(cancelled)
            self._progress(progress, Stage.composition, at(0.54), f"{prefix}Composing authored visuals")
            composition = self.composition.plan(story, assets, choreography, shared.directions)
            self.handoff_contracts.require_composition_for_motion(
                story=story, assets=assets, composition=composition
            )
            self._progress(
                progress,
                Stage.composition,
                at(0.57),
                f"{prefix}Visual Composition locked to target geometry",
            )

            self._check_cancel(cancelled)
            self._progress(progress, Stage.motion, at(0.61), f"{prefix}Planning final visual motion")
            motion = self.motion_reference.enforce(
                self.motion.plan(
                    story, composition, choreography, assets=assets, reference=semantic_reference,
                )
            )
            # Sprint 4.4: reference-derived entry motion (opacity clock inside the Story
            # window). Runs after the Reference contract; certified planning is untouched.
            motion = self.entry_grammar.apply(
                motion, composition=composition, choreography=choreography, assets=assets,
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
                at(0.63),
                f"{prefix}Placing text against final visual visibility windows",
            )
            text, text_composition, text_motion = self._compose_text_against_visual_motion(
                story=story,
                composition=composition,
                motion=motion,
                text=shared.text,
                assets=assets,
                choreography=choreography,
                reference_cue_ids=(
                    semantic_reference.text_cue_ids if semantic_reference is not None else None
                ),
            )
            self.handoff_contracts.require_text_render_contract(
                story=story,
                assets=assets,
                text=text,
                text_composition=text_composition,
                text_motion=text_motion,
            )
            diagnostics = workspace / "diagnostics"
            diagnostics.mkdir(parents=True, exist_ok=True)
            (diagnostics / "text-owner-coupling.json").write_text(
                json.dumps(self.text_composition.owner_coupling, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (diagnostics / "target-composition.json").write_text(
                json.dumps(
                    {"target_id": target.target_id, "scenes": self.composition.target_evidence},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            self._progress(
                progress,
                Stage.composition,
                at(0.64),
                f"{prefix}Placed {len(text.cues)} text cues against final visual lifetimes",
            )

            self._progress(
                progress,
                Stage.motion,
                at(0.67),
                f"{prefix}Owner contracts passed for Story, Composition, Motion, and Text",
            )

            # Sprint 4.5: how each outgoing scene leaves the screen. Planned here, on final
            # geometry, motion and text; the renderer only executes the result.
            scene_boundaries = self.scene_boundaries.plan(
                story=story,
                composition=composition,
                motion=motion,
                assets=assets,
                duration=shared.transcript.duration,
                text=text,
                text_composition=text_composition,
                text_motion=text_motion,
            )

            self._check_cancel(cancelled)
            self._progress(progress, Stage.render, at(0.69), f"{prefix}Compiling render plan")
            plan, _ = self.render_planner.compile(
                shared.transcript,
                assets,
                story,
                composition,
                motion,
                workspace,
                text=text,
                text_composition=text_composition,
                text_motion=text_motion,
                scene_boundaries=scene_boundaries,
                target=target,
            )
        return plan

    # -- per-target render, verification and mux ------------------------------------------
    def _render_target(
        self,
        shared: SharedSemanticPlan,
        target: VisualTargetProfile,
        plan: RenderPlan,
        workspace: Path,
        output_file: Path,
        audio_path: Path,
        *,
        progress: ProgressCallback | None,
        cancelled: CancellationCallback | None,
        span: tuple[float, float],
        announce: bool = True,
    ) -> TargetOutput:
        story = shared.story
        prefix = f"{target.output_suffix.title()}: " if announce else ""
        begin = time.perf_counter()
        self._check_cancel(cancelled)
        self._progress(progress, Stage.render, span[0], f"{prefix}Rendering story")
        video_only = self.renderer.render(plan, workspace / "render" / "video-only.mp4")
        worker_count = self.renderer.last_worker_count
        rendered_motion_report = self.encoded_motion_verifier.inspect(video=video_only, plan=plan)
        self.encoded_motion_verifier.write(
            rendered_motion_report,
            workspace / "diagnostics" / "rendered-motion-qa.json",
        )
        self.encoded_motion_verifier.require(rendered_motion_report)

        self._check_cancel(cancelled)
        self._progress(
            progress, Stage.final, span[1], f"{prefix}Building final video",
        )
        final_path = self.final.mux(video_only, audio_path, output_file)
        self.final_media.require(
            final_path,
            audio_path,
            first_spoken_start=story[0].audio_start if story else None,
        )
        self.rendered_visual_evidence.inspect(final_path, workspace / "diagnostics")
        self._check_cancel(cancelled)
        if not self.settings.render_resources.keep_intermediates:
            self.renderer.cleanup_intermediates(
                video_only, source_paths={asset.image_path for asset in plan.assets},
            )
            # The encoded-motion and final-media checks have finished. This copy
            # exists only to feed mux/QA; the verified export and diagnostics stay.
            render_dir = (workspace / "render").resolve()
            if (video_only.name == "video-only.mp4" and not video_only.is_symlink()
                    and video_only.resolve().parent == render_dir
                    and video_only.resolve() != final_path.resolve()):
                video_only.unlink()
        return TargetOutput(
            target_id=target.target_id,
            path=final_path,
            width=plan.width,
            height=plan.height,
            fps=plan.fps,
            duration=plan.duration,
            frame_count=max(1, round(plan.duration * plan.fps)),
            render_plan_path=workspace / "render-plan.json",
            render_plan_fingerprint=plan_fingerprint(plan),
            encoded_motion_ok=bool(rendered_motion_report.ok),
            final_media_ok=True,
            media=self.final_media.summary(final_path),
            seconds=round(time.perf_counter() - begin, 3),
            worker_count=worker_count,
        )

    def _compose_text_against_visual_motion(
        self,
        *,
        story,
        composition,
        motion,
        text,
        assets,
        choreography,
        reference_cue_ids: frozenset[str] | None = None,
    ):
        """Author the final legal text set against final visual lifetimes once.

        ``reference_cue_ids`` (non-reference formats): the cue set the reference format
        kept. Text selection is shared, so this format shows exactly those cues with the
        same wording, owner and timing; failing to place one of them fails closed.
        """
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
        if reference_cue_ids is not None:
            missing = sorted(reference_cue_ids - accepted_ids)
            if missing:
                raise StageFailedError(
                    "Text shown on the reference format cannot be placed on this format",
                    details={"code": "TARGET_TEXT_UNPLACEABLE", "text_cue_ids": missing},
                )
            accepted_ids = set(reference_cue_ids)
            text_composition = [
                beat.model_copy(update={
                    "items": [item for item in beat.items if item.text_cue_id in accepted_ids],
                })
                for beat in text_composition
            ]
            text_composition = [beat for beat in text_composition if beat.items]
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

    # -- export manifest ------------------------------------------------------------------
    def _manifest(
        self,
        *,
        shared: SharedSemanticPlan,
        package_path: Path,
        bundle: ReservedBundle,
        outputs: dict[str, TargetOutput],
        plans: dict[str, RenderPlan],
        total_seconds: float,
    ) -> dict[str, Any]:
        reference = plans[REFERENCE_TARGET.target_id]
        return {
            "schema": "hexa.export.bundle/1",
            "completed": True,
            "package_id": shared.package.package_id,
            "project_slug": shared.package.project_slug,
            "export_identity": bundle.slug,
            "export_version": bundle.version,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine_git_sha": _engine_git_sha(),
            "engine_tree_dirty": _engine_tree_dirty(),
            "source_package_fingerprint": _source_fingerprint(package_path),
            "shared_story_fingerprint": fingerprint(
                [beat.model_dump(mode="json") for beat in shared.story]
            ),
            "shared_choreography_fingerprint": fingerprint(
                [_choreography_row(row) for row in shared.choreography.directives]
            ),
            "shared_text_fingerprint": fingerprint(
                [cue.model_dump(mode="json") for cue in reference.text.cues]
            ),
            "narration": {
                "duration": round(shared.transcript.duration, 6),
                "story_beats": len(shared.story),
            },
            "timings": {**shared.timings, "total_seconds": round(total_seconds, 3)},
            "outputs": {
                target_id: {
                    "target_id": target_id,
                    "filename": output.path.name,
                    "width": output.width,
                    "height": output.height,
                    "fps": output.fps,
                    "duration": round(output.duration, 6),
                    "frame_count": output.frame_count,
                    "video_codec": output.media.get("video_codec"),
                    "audio_codec": output.media.get("audio_codec"),
                    "media": output.media,
                    "bytes": output.path.stat().st_size,
                    "render_plan_fingerprint": output.render_plan_fingerprint,
                    "encoded_motion_verification": "PASS" if output.encoded_motion_ok else "FAIL",
                    "final_media_verification": "PASS" if output.final_media_ok else "FAIL",
                    "seconds": output.seconds,
                    "render_workers": output.worker_count,
                }
                for target_id, output in outputs.items()
            },
        }

    # -- helpers --------------------------------------------------------------------------
    @staticmethod
    def _target_workspace(workspace: Path, target: VisualTargetProfile) -> Path:
        # The reference target keeps the historical workspace layout (render-plan.json,
        # diagnostics/ and render/ at the job root); others get their own sub-tree.
        return workspace if target is REFERENCE_TARGET else workspace / "targets" / target.target_id

    @staticmethod
    def _require_free_space(path: Path, required: int) -> None:
        path.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(path).free
        if free < required:
            raise StageFailedError(
                "work root has insufficient free space for dual-format rendering",
                details={
                    "code": "WORK_ROOT_INSUFFICIENT_SPACE",
                    "path": str(path),
                    "free_bytes": free,
                    "required_bytes": required,
                },
            )

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


def _with_seconds(output: TargetOutput, seconds: float) -> TargetOutput:
    from dataclasses import replace

    return replace(output, seconds=round(seconds, 3))


def _choreography_row(directive) -> dict[str, Any]:
    from dataclasses import asdict

    return json.loads(json.dumps(asdict(directive), default=str, sort_keys=True))


def _source_fingerprint(path: Path) -> str:
    path = path.expanduser().resolve()
    digest = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8") + b"\0")
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _engine_git_sha() -> str | None:
    try:
        result = run_hidden(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True,
            timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha if len(sha) == 40 else None


def _engine_tree_dirty() -> bool | None:
    """True when tracked engine files differ from ``engine_git_sha`` (unknown -> None)."""
    try:
        result = run_hidden(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", "app"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(result.stdout.strip())
