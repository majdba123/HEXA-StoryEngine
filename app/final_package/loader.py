from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Iterable

from PIL import Image
from pydantic import ValidationError

from app.canonical import (
    AnchorGranularity,
    BindingType,
    CanonicalAsset,
    CanonicalContinuity,
    CanonicalPackage,
    CanonicalProgression,
    CanonicalRelation,
    CanonicalScene,
    CanonicalScriptSpan,
    CanonicalSemanticEvent,
    CanonicalSemanticGroup,
    CanonicalVisualLocator,
    CanonicalVisualProgression,
    CompoundVisualClassification,
    ContinuityMode,
    SemanticGroupAnimationPolicy,
    VisualFocus,
)
from app.shared.errors import InvalidPackageError

from .models import (
    ContinuityPayload,
    ScriptSpanPayload,
    UnifiedFinalPackagePayload,
    UnifiedObjectPayload,
    UnifiedScenePayload,
    VisualLocatorPayload,
    VisualStatePayload,
)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class FinalPackageLoader:
    """Load the single supported HEXA Unified Final Package 2.0 contract.

    The boundary is intentionally strict. 1.x manifest/scene-plan/semantic-bindings
    packages are not adapted here; they must be converted before entering production.
    """

    def load(self, source: Path, workspace: Path) -> CanonicalPackage:
        source = source.expanduser().resolve()
        if not source.exists():
            raise InvalidPackageError(f"Final Package not found: {source}")
        package_root = self._materialize(source, workspace)
        package_json = package_root / "package.json"
        if not package_json.is_file():
            raise InvalidPackageError(
                "Unified Final Package 2.0 requires package.json; legacy 1.x packages are unsupported"
            )
        self._reject_legacy_companions(package_root)
        payload = self._load_payload(package_json)
        self._validate_payload(payload, package_root)
        return self._canonical(payload, package_root)


    @staticmethod
    def _reject_legacy_companions(root: Path) -> None:
        legacy_names = {"manifest.json", "scene_plan.json", "semantic_bindings.json"}
        found = sorted(
            str(path.relative_to(root))
            for path in root.rglob("*.json")
            if path.name in legacy_names
        )
        if found:
            raise InvalidPackageError(
                "Unified Final Package 2.0 must have one semantic source; "
                f"legacy companion files are forbidden: {', '.join(found)}"
            )

    def _materialize(self, source: Path, workspace: Path) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            return source
        if source.suffix.lower() != ".zip":
            raise InvalidPackageError("Final Package must be a directory or .zip")
        target = workspace / "package"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        try:
            with zipfile.ZipFile(source) as archive:
                target_root = target.resolve()
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise InvalidPackageError("unsafe path found inside Final Package")
                    member_target = (target / member.filename).resolve()
                    if target_root not in member_target.parents and member_target != target_root:
                        raise InvalidPackageError("unsafe path found inside Final Package")
                archive.extractall(target)
        except zipfile.BadZipFile as exc:
            raise InvalidPackageError("Final Package ZIP is invalid") from exc
        children = [item for item in target.iterdir() if item.name != "__MACOSX"]
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return target

    @staticmethod
    def _load_payload(path: Path) -> UnifiedFinalPackagePayload:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidPackageError("invalid json: package.json") from exc
        if not isinstance(raw, dict):
            raise InvalidPackageError("json root must be an object: package.json")
        try:
            return UnifiedFinalPackagePayload.model_validate(raw)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            location = ".".join(str(item) for item in first.get("loc", ()))
            message = first.get("msg", "schema validation failed")
            detail = f" at {location}" if location else ""
            raise InvalidPackageError(f"invalid Unified Final Package 2.0{detail}: {message}") from exc

    def _validate_payload(self, package: UnifiedFinalPackagePayload, root: Path) -> None:
        if not package.canonical_script.strip():
            raise InvalidPackageError("canonical_script must be non-empty")
        if not package.scenes:
            raise InvalidPackageError("Unified Final Package contains no scenes")
        if package.image_spec.width <= 0 or package.image_spec.height <= 0:
            raise InvalidPackageError("image_spec dimensions must be positive")
        if package.image_spec.format.casefold() not in {"png", "jpg", "jpeg", "webp"}:
            raise InvalidPackageError("unsupported image_spec format")

        scene_ids = [scene.scene_id for scene in package.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise InvalidPackageError("duplicate scene_id in Unified Final Package")
        orders = [scene.order for scene in package.scenes]
        if len(orders) != len(set(orders)):
            raise InvalidPackageError("duplicate scene order in Unified Final Package")

        global_object_ids: set[str] = set()
        global_event_ids: set[str] = set()
        for scene in package.scenes:
            self._validate_scene(package, root, scene, global_object_ids, global_event_ids)

    def _validate_scene(
        self,
        package: UnifiedFinalPackagePayload,
        root: Path,
        scene: UnifiedScenePayload,
        global_object_ids: set[str],
        global_event_ids: set[str],
    ) -> None:
        image = self._safe_path(root, scene.image, label=f"scene image {scene.scene_id}")
        image_rel = Path(scene.image)
        image_dir = Path(package.image_spec.directory)
        image_dir_parts = image_dir.parts
        if not image_dir_parts or image_rel.parts[: len(image_dir_parts)] != image_dir_parts:
            raise InvalidPackageError(
                f"scene image must live under image_spec.directory: {scene.scene_id}:{scene.image}"
            )
        expected_suffix = ".jpg" if package.image_spec.format.casefold() == "jpeg" else f".{package.image_spec.format.casefold()}"
        if image_rel.suffix.casefold() != expected_suffix:
            raise InvalidPackageError(
                f"scene image extension does not match image_spec: {scene.scene_id}:{scene.image}"
            )
        if not image.is_file() or image.suffix.lower() not in _IMAGE_EXTENSIONS:
            raise InvalidPackageError(f"missing scene image: {scene.scene_id}:{scene.image}")
        with Image.open(image) as source:
            if source.size != (package.image_spec.width, package.image_spec.height):
                raise InvalidPackageError(
                    f"scene image dimensions do not match image_spec: {scene.scene_id}"
                )

        self._validate_span(package.canonical_script, scene.script_span, f"{scene.scene_id}:script_span")
        object_ids: set[str] = set()
        event_ids: set[str] = set()
        group_ids: set[str] = set()

        for obj in scene.objects:
            if obj.scene_id != scene.scene_id:
                raise InvalidPackageError(f"object scene_id mismatch: {scene.scene_id}:{obj.asset_id}")
            if obj.asset_id in object_ids:
                raise InvalidPackageError(f"duplicate object asset_id in scene: {scene.scene_id}:{obj.asset_id}")
            if obj.object_type.upper() == "VISUAL_ASSET_INTENT" and obj.asset_id in global_object_ids:
                raise InvalidPackageError(f"duplicate visual asset_id: {obj.asset_id}")
            if not obj.asset_id.strip() or not obj.unit_id.strip():
                raise InvalidPackageError(f"object identity is required: {scene.scene_id}")
            object_ids.add(obj.asset_id)
            if obj.object_type.upper() == "VISUAL_ASSET_INTENT":
                global_object_ids.add(obj.asset_id)
            for label, span in (
                ("script_span", obj.script_span),
                ("appear_trigger", obj.appear_trigger),
                ("focus_trigger", obj.focus_trigger),
                ("exit_trigger", obj.exit_trigger),
            ):
                self._validate_span(
                    package.canonical_script,
                    span,
                    f"{scene.scene_id}:{obj.asset_id}:{label}",
                    allow_empty=True,
                )
            self._validate_locator(obj.visual_locator, f"{scene.scene_id}:{obj.asset_id}")
            self._validate_enumish(obj.binding_type, BindingType, "binding_type", scene.scene_id, obj.asset_id)
            self._validate_enumish(
                obj.anchor_granularity,
                AnchorGranularity,
                "anchor_granularity",
                scene.scene_id,
                obj.asset_id,
            )
            self._validate_enumish(obj.visual_focus, VisualFocus, "visual_focus", scene.scene_id, obj.asset_id)
            self._validate_enumish(
                obj.compound_visual_classification,
                CompoundVisualClassification,
                "compound_visual_classification",
                scene.scene_id,
                obj.asset_id,
            )
            self._validate_continuity(obj.continuity, scene.scene_id, obj.asset_id)

        for group in scene.semantic_groups:
            if group.semantic_group_id in group_ids:
                raise InvalidPackageError(
                    f"duplicate semantic group: {scene.scene_id}:{group.semantic_group_id}"
                )
            group_ids.add(group.semantic_group_id)
            try:
                SemanticGroupAnimationPolicy(group.animation_policy.upper())
            except ValueError as exc:
                raise InvalidPackageError(
                    f"unsupported semantic group animation policy: {scene.scene_id}:{group.semantic_group_id}"
                ) from exc
            self._require_refs(group.asset_ids, object_ids, f"semantic group {group.semantic_group_id}")

        for event in scene.semantic_events:
            if event.scene_id != scene.scene_id:
                raise InvalidPackageError(
                    f"semantic event scene_id mismatch: {scene.scene_id}:{event.semantic_event_id}"
                )
            if event.semantic_event_id in event_ids or event.semantic_event_id in global_event_ids:
                raise InvalidPackageError(f"duplicate semantic event: {event.semantic_event_id}")
            event_ids.add(event.semantic_event_id)
            global_event_ids.add(event.semantic_event_id)
            self._validate_span(
                package.canonical_script,
                event.script_span,
                f"{scene.scene_id}:{event.semantic_event_id}:script_span",
                allow_empty=True,
            )
            self._validate_enumish(
                event.anchor_granularity,
                AnchorGranularity,
                "anchor_granularity",
                scene.scene_id,
                event.semantic_event_id,
            )
            refs = [
                event.visual_leader_asset_id,
                event.text_anchor_asset_id,
                *event.participant_asset_ids,
                *event.context_asset_ids,
                *event.result_asset_ids,
            ]
            self._require_refs([item for item in refs if item], object_ids, f"event {event.semantic_event_id}")

        for event in scene.semantic_events:
            self._require_refs(
                event.depends_on_event_ids,
                event_ids,
                f"event dependency {event.semantic_event_id}",
            )
        self._require_acyclic_dependencies(scene)

        for obj in scene.objects:
            if obj.semantic_group_id and obj.semantic_group_id not in group_ids:
                raise InvalidPackageError(
                    f"object semantic_group_id is missing: {scene.scene_id}:{obj.asset_id}:{obj.semantic_group_id}"
                )
            if obj.semantic_event_id and obj.semantic_event_id not in event_ids:
                raise InvalidPackageError(
                    f"object semantic_event_id is missing: {scene.scene_id}:{obj.asset_id}:{obj.semantic_event_id}"
                )
            if obj.parent_asset_id and obj.parent_asset_id not in object_ids:
                raise InvalidPackageError(
                    f"object parent is missing: {scene.scene_id}:{obj.asset_id}:{obj.parent_asset_id}"
                )
            self._require_refs(obj.children_asset_ids, object_ids, f"children {obj.asset_id}")
            if obj.interaction_target and obj.interaction_target not in object_ids:
                raise InvalidPackageError(
                    f"interaction target is missing: {scene.scene_id}:{obj.asset_id}:{obj.interaction_target}"
                )
            if obj.continuity.target_asset_id and obj.continuity.target_asset_id not in object_ids:
                raise InvalidPackageError(
                    f"continuity target is missing: {scene.scene_id}:{obj.asset_id}:{obj.continuity.target_asset_id}"
                )
        self._require_parent_children_consistency(scene)
        self._require_group_membership_consistency(scene)
        self._require_event_membership_consistency(scene)

        for relation in scene.relations:
            relation_type = relation.relation_type or relation.relationship
            if not relation_type:
                raise InvalidPackageError(f"relation type is required: {scene.scene_id}")
            if relation.relation_type and relation.relationship and relation.relation_type != relation.relationship:
                raise InvalidPackageError(f"relation type/relationship mismatch: {scene.scene_id}")
            refs = [relation.subject_asset_id, relation.object_asset_id]
            for optional in (relation.result_asset_id, relation.connector_asset_id):
                if optional:
                    refs.append(optional)
            self._require_refs(refs, object_ids, f"relation {relation.relation_id or relation_type}")
            self._validate_span(
                package.canonical_script,
                relation.script_span,
                f"{scene.scene_id}:{relation.relation_id or relation_type}:script_span",
                allow_empty=True,
            )

        for progression in scene.visual_progression:
            self._require_refs(progression.targets, object_ids, f"visual progression {scene.scene_id}")
            self._validate_span(
                package.canonical_script,
                progression.trigger,
                f"{scene.scene_id}:visual_progression:trigger",
                allow_empty=True,
            )

        self._require_refs(
            scene.semantic_progression.event_order,
            event_ids,
            f"semantic progression {scene.scene_id}",
        )

    @staticmethod
    def _validate_span(script: str, span: ScriptSpanPayload, context: str, *, allow_empty: bool = False) -> None:
        start, end, text = span.global_char_start, span.global_char_end, span.text
        if start is None and end is None and (text is None or not text.strip()):
            if allow_empty:
                return
            raise InvalidPackageError(f"script span is required: {context}")
        if start is None or end is None:
            raise InvalidPackageError(f"script span offsets are incomplete: {context}")
        if start < 0 or end < start or end > len(script):
            raise InvalidPackageError(f"script span offsets are invalid: {context}")
        actual = script[start:end]
        if text is not None and text != actual:
            raise InvalidPackageError(f"script span text mismatch: {context}")

    @staticmethod
    def _validate_locator(locator: VisualLocatorPayload, context: str) -> None:
        values = (locator.cx, locator.cy, locator.width, locator.height)
        if all(value is None for value in values):
            if locator.coordinate_space is not None:
                raise InvalidPackageError(f"visual_locator is partially empty: {context}")
            return
        if any(value is None for value in values):
            raise InvalidPackageError(f"visual_locator is incomplete: {context}")
        if locator.coordinate_space != "normalized_scene":
            raise InvalidPackageError(f"unsupported visual_locator coordinate_space: {context}")
        assert locator.cx is not None and locator.cy is not None
        assert locator.width is not None and locator.height is not None
        if not (0 <= locator.cx <= 1 and 0 <= locator.cy <= 1):
            raise InvalidPackageError(f"visual_locator center is outside normalized scene: {context}")
        if not (0 < locator.width <= 1 and 0 < locator.height <= 1):
            raise InvalidPackageError(f"visual_locator size is invalid: {context}")
        if locator.cx - locator.width / 2 < -1e-6 or locator.cx + locator.width / 2 > 1 + 1e-6:
            raise InvalidPackageError(f"visual_locator exceeds horizontal scene bounds: {context}")
        if locator.cy - locator.height / 2 < -1e-6 or locator.cy + locator.height / 2 > 1 + 1e-6:
            raise InvalidPackageError(f"visual_locator exceeds vertical scene bounds: {context}")

    @staticmethod
    def _validate_enumish(value: str | None, enum_type, field: str, scene_id: str, object_id: str) -> None:
        if value is None:
            return
        try:
            enum_type(value.upper())
        except ValueError as exc:
            raise InvalidPackageError(
                f"unsupported {field}: {scene_id}:{object_id}:{value}"
            ) from exc

    @staticmethod
    def _validate_continuity(value: ContinuityPayload, scene_id: str, asset_id: str) -> None:
        if value.mode is None:
            if value.target_asset_id is not None:
                raise InvalidPackageError(
                    f"continuity target requires mode: {scene_id}:{asset_id}"
                )
            return
        try:
            mode = ContinuityMode(value.mode.upper())
        except ValueError as exc:
            raise InvalidPackageError(f"unsupported continuity mode: {scene_id}:{asset_id}") from exc
        if mode is ContinuityMode.TRANSFORM_TO and not value.target_asset_id:
            raise InvalidPackageError(f"TRANSFORM_TO requires target_asset_id: {scene_id}:{asset_id}")

    @staticmethod
    def _require_refs(values: Iterable[str], available: set[str], context: str) -> None:
        for value in values:
            if value not in available:
                raise InvalidPackageError(f"reference is missing: {context}:{value}")

    @staticmethod
    def _require_acyclic_dependencies(scene: UnifiedScenePayload) -> None:
        graph = {event.semantic_event_id: tuple(event.depends_on_event_ids) for event in scene.semantic_events}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visited:
                return
            if node in visiting:
                raise InvalidPackageError(f"semantic event dependency cycle: {scene.scene_id}:{node}")
            visiting.add(node)
            for parent in graph.get(node, ()):
                visit(parent)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)

    @staticmethod
    def _require_parent_children_consistency(scene: UnifiedScenePayload) -> None:
        children_by_parent: dict[str, set[str]] = {}
        for obj in scene.objects:
            if obj.parent_asset_id:
                children_by_parent.setdefault(obj.parent_asset_id, set()).add(obj.asset_id)
        by_id = {obj.asset_id: obj for obj in scene.objects}
        for parent_id, derived in children_by_parent.items():
            declared = set(by_id[parent_id].children_asset_ids)
            if declared != derived:
                raise InvalidPackageError(
                    f"parent/children mismatch: {scene.scene_id}:{parent_id}"
                )
        for obj in scene.objects:
            if obj.asset_id not in children_by_parent and obj.children_asset_ids:
                raise InvalidPackageError(
                    f"parent/children mismatch: {scene.scene_id}:{obj.asset_id}"
                )

    @staticmethod
    def _require_group_membership_consistency(scene: UnifiedScenePayload) -> None:
        declared = {
            group.semantic_group_id: set(group.asset_ids)
            for group in scene.semantic_groups
        }
        derived: dict[str, set[str]] = {}
        for obj in scene.objects:
            if obj.semantic_group_id:
                derived.setdefault(obj.semantic_group_id, set()).add(obj.asset_id)
        for group_id in set(declared) | set(derived):
            if declared.get(group_id, set()) != derived.get(group_id, set()):
                raise InvalidPackageError(
                    f"semantic group membership mismatch: {scene.scene_id}:{group_id}"
                )

    @staticmethod
    def _require_event_membership_consistency(scene: UnifiedScenePayload) -> None:
        by_event: dict[str, set[str]] = {}
        for event in scene.semantic_events:
            members = {
                asset_id
                for asset_id in (
                    event.visual_leader_asset_id,
                    event.text_anchor_asset_id,
                    *event.participant_asset_ids,
                    *event.context_asset_ids,
                    *event.result_asset_ids,
                )
                if asset_id
            }
            by_event[event.semantic_event_id] = members
        for obj in scene.objects:
            if obj.semantic_event_id is None:
                continue
            if obj.asset_id not in by_event.get(obj.semantic_event_id, set()):
                raise InvalidPackageError(
                    f"semantic event membership mismatch: "
                    f"{scene.scene_id}:{obj.asset_id}:{obj.semantic_event_id}"
                )

        object_event = {obj.asset_id: obj.semantic_event_id for obj in scene.objects}
        for event in scene.semantic_events:
            strict_owned = [
                event.visual_leader_asset_id,
                event.text_anchor_asset_id,
                *event.result_asset_ids,
            ]
            for asset_id in (item for item in strict_owned if item):
                if object_event.get(asset_id) != event.semantic_event_id:
                    raise InvalidPackageError(
                        f"semantic event ownership mismatch: "
                        f"{scene.scene_id}:{asset_id}:{event.semantic_event_id}"
                    )
    @staticmethod
    def _safe_path(root: Path, relative: str, *, label: str) -> Path:
        candidate = (root / relative).resolve()
        root_resolved = root.resolve()
        if root_resolved not in candidate.parents and candidate != root_resolved:
            raise InvalidPackageError(f"path escapes Final Package: {label}")
        return candidate

    def _canonical(self, package: UnifiedFinalPackagePayload, root: Path) -> CanonicalPackage:
        scenes = tuple(self._canonical_scene(scene, root) for scene in sorted(package.scenes, key=lambda row: row.order))
        return CanonicalPackage(
            root=root,
            package_id=package.package_id,
            script=package.canonical_script,
            contract_name=package.contract,
            contract_version=package.contract_version,
            language=package.language,
            project_slug=package.project_slug,
            builder_target=package.builder_target,
            timing_authority=package.timing_authority,
            script_audio_relationship=package.script_audio_relationship,
            has_authoritative_semantics=True,
            scenes=scenes,
            extension_metadata={
                "source_provenance": package.source_provenance.model_dump(mode="python"),
                "image_spec": package.image_spec.model_dump(mode="python"),
            },
        )

    def _canonical_scene(self, scene: UnifiedScenePayload, root: Path) -> CanonicalScene:
        return CanonicalScene(
            id=scene.scene_id,
            image_path=self._safe_path(root, scene.image, label=f"scene image {scene.scene_id}"),
            order=scene.order,
            title=scene.title,
            narration_hint=scene.narration_hint,
            script_char_start=scene.script_span.global_char_start,
            script_char_end=scene.script_span.global_char_end,
            purpose=scene.purpose,
            visual_concept=scene.visual_concept,
            relation_to_previous=scene.relation_to_previous,
            character_category=scene.character_category,
            units=tuple(self._canonical_object(obj) for obj in scene.objects),
            visual_progression=tuple(
                CanonicalVisualProgression(
                    action=row.action,
                    targets=tuple(row.targets),
                    trigger=self._span_or_none(row.trigger),
                    extension_metadata={
                        "event_id": row.event_id,
                        "order": row.order,
                    },
                )
                for row in scene.visual_progression
            ),
            semantic_groups=tuple(
                CanonicalSemanticGroup(
                    semantic_group_id=row.semantic_group_id,
                    script_text=row.script_text,
                    animation_policy=SemanticGroupAnimationPolicy(row.animation_policy.upper()),
                    asset_ids=tuple(row.asset_ids),
                )
                for row in scene.semantic_groups
            ),
            semantic_events=tuple(
                CanonicalSemanticEvent(
                    semantic_event_id=row.semantic_event_id,
                    scene_id=row.scene_id,
                    script_text=row.script_text,
                    script_span=self._span_or_none(row.script_span),
                    anchor_granularity=self._enum_or_none(AnchorGranularity, row.anchor_granularity),
                    sequence_order=row.sequence_order,
                    visual_leader_asset_id=row.visual_leader_asset_id,
                    participant_asset_ids=tuple(row.participant_asset_ids),
                    context_asset_ids=tuple(row.context_asset_ids),
                    result_asset_ids=tuple(row.result_asset_ids),
                    text_anchor_asset_id=row.text_anchor_asset_id,
                    confidence=row.confidence,
                    needs_review=row.needs_review,
                    ambiguity_reason=row.ambiguity_reason,
                    depends_on_event_ids=tuple(row.depends_on_event_ids),
                )
                for row in scene.semantic_events
            ),
            relations=tuple(
                CanonicalRelation(
                    subject_asset_id=row.subject_asset_id,
                    relation_type=str(row.relation_type or row.relationship),
                    object_asset_id=row.object_asset_id,
                    result_asset_id=row.result_asset_id,
                    script_text=row.script_text,
                    script_span=self._span_or_none(row.script_span),
                    confidence=row.confidence,
                    extension_metadata={
                        "relation_id": row.relation_id,
                        "relationship": row.relationship,
                        "connector_asset_id": row.connector_asset_id,
                    },
                )
                for row in scene.relations
            ),
            semantic_progression=CanonicalProgression(
                type=scene.semantic_progression.type,
                event_order=tuple(scene.semantic_progression.event_order),
            ),
        )

    def _canonical_object(self, row: UnifiedObjectPayload) -> CanonicalAsset:
        state = self._state_or_none(row.visual_state)
        continuity = self._continuity_or_none(row.continuity)
        locator = self._locator_or_none(row.visual_locator)
        return CanonicalAsset(
            unit_id=row.unit_id,
            asset_id=row.asset_id,
            scene_id=row.scene_id,
            type=row.object_type,
            semantic_name=row.semantic_name,
            visual_concept=row.visual_concept,
            semantic_meaning=row.semantic_meaning,
            role=row.role,
            semantic_role=row.semantic_role,
            semantic_intent=row.semantic_intent,
            narrative_function=row.narrative_function,
            binding_type=self._enum_or_none(BindingType, row.binding_type),
            script_text=row.script_text,
            script_span=self._span_or_none(row.script_span),
            appear_trigger=self._span_or_none(row.appear_trigger),
            focus_trigger=self._span_or_none(row.focus_trigger),
            exit_trigger=self._span_or_none(row.exit_trigger),
            semantic_group_id=row.semantic_group_id,
            sequence_order=row.sequence_order,
            parent_asset_id=row.parent_asset_id,
            children_asset_ids=tuple(row.children_asset_ids),
            confidence=row.confidence,
            interaction_target=row.interaction_target,
            relationship=row.relationship,
            semantic_event_id=row.semantic_event_id,
            anchor_granularity=self._enum_or_none(AnchorGranularity, row.anchor_granularity),
            visual_focus=self._enum_or_none(VisualFocus, row.visual_focus),
            visual_state=state,
            continuity=continuity,
            compound_visual_classification=self._enum_or_none(
                CompoundVisualClassification, row.compound_visual_classification
            ),
            internal_progression_unavailable=row.internal_progression_unavailable,
            needs_review=row.needs_review,
            ambiguity_reason=row.ambiguity_reason,
            visual_locator=locator,
            extension_metadata={"source_asset_id": row.source_asset_id},
        )

    @staticmethod
    def _span_or_none(row: ScriptSpanPayload) -> CanonicalScriptSpan | None:
        if row.text is None and row.global_char_start is None and row.global_char_end is None:
            return None
        return CanonicalScriptSpan(
            text=row.text,
            global_char_start=row.global_char_start,
            global_char_end=row.global_char_end,
        )

    @staticmethod
    def _locator_or_none(row: VisualLocatorPayload) -> CanonicalVisualLocator | None:
        if row.cx is None and row.cy is None and row.width is None and row.height is None:
            return None
        assert row.coordinate_space is not None
        assert row.cx is not None and row.cy is not None and row.width is not None and row.height is not None
        return CanonicalVisualLocator(
            coordinate_space=row.coordinate_space,
            cx=row.cx,
            cy=row.cy,
            width=row.width,
            height=row.height,
        )

    @staticmethod
    def _state_or_none(row: VisualStatePayload) -> dict[str, str] | None:
        if row.before is None and row.after is None:
            return None
        return {"before": row.before or "", "after": row.after or ""}

    @staticmethod
    def _continuity_or_none(row: ContinuityPayload) -> CanonicalContinuity | None:
        if row.mode is None and row.target_asset_id is None:
            return None
        return CanonicalContinuity(
            mode=ContinuityMode(row.mode.upper()) if row.mode else None,
            target_asset_id=row.target_asset_id,
        )

    @staticmethod
    def _enum_or_none(enum_type, value: str | None):
        return enum_type(value.upper()) if value is not None else None

    @staticmethod
    def package_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
