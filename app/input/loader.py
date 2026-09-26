from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from app.models import PackageModel, SceneSource
from app.shared.errors import InvalidPackageError

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_SEMANTIC_BINDING_SCHEMAS = {"HEXA_SEMANTIC_BINDINGS", "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS"}
_ASSET_LEVEL_BINDING_TYPES = {"EXPLICIT", "SEMANTIC", "SUPPORT", "PARENT", "AMBIGUOUS"}
_SEMANTIC_GROUP_POLICIES = {"SEQUENTIAL_WITHIN_PHRASE", "SIMULTANEOUS_VISUAL_UNIT"}
_VISUAL_FOCUS_VALUES = {"PRIMARY", "SUPPORT", "RESULT", "CONTEXT"}
_CONTINUITY_MODES = {"PERSIST", "TRANSFORM_TO"}
_COMPOUND_VISUAL_CLASSIFICATIONS = {"SEPARABLE_SAFE", "COMPOUND_REQUIRED"}
_ANCHOR_GRANULARITIES = {"EXACT_WORD", "EXACT_PHRASE", "SCENE_PHRASE"}


class FinalPackageLoader:
    def load(self, source: Path, workspace: Path, script_path: Path | None = None) -> PackageModel:
        source = source.expanduser().resolve()
        if not source.exists():
            raise InvalidPackageError(f"Final Package not found: {source}")
        package_root = self._materialize(source, workspace)
        manifest_path = package_root / "manifest.json"
        manifest = self._load_json(manifest_path) if manifest_path.exists() else {}
        script = self._load_script(package_root, script_path, manifest)
        scene_plan = self._load_scene_plan(package_root, manifest)
        semantic_bindings = self._load_semantic_bindings(package_root, manifest)
        scenes = self._discover_scenes(package_root, manifest, scene_plan)
        if not scenes:
            raise InvalidPackageError("Final Package contains no scene images")
        self._validate_scene_unit_visual_locators(scenes)
        self._validate_semantic_binding_script(semantic_bindings, script)
        self._validate_semantic_binding_units(semantic_bindings, scenes)
        package_id = (
            manifest.get("package_id")
            or manifest.get("project_id")
            or scene_plan.get("project_id")
            or self._stable_package_id(source)
        )
        return PackageModel(
            root=package_root,
            package_id=str(package_id),
            scenes=scenes,
            script=script,
            manifest=manifest,
            scene_plan=scene_plan,
            semantic_bindings=semantic_bindings,
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
    def _load_json(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InvalidPackageError(f"invalid json: {path.name}") from exc
        if not isinstance(data, dict):
            raise InvalidPackageError(f"json root must be an object: {path.name}")
        return data

    def _load_semantic_bindings(self, root: Path, manifest: dict) -> dict:
        raw = manifest.get("semantic_bindings")
        candidates: list[Path] = []
        if isinstance(raw, str):
            candidate = (root / raw).resolve()
            if not self._inside(root, candidate):
                raise InvalidPackageError("semantic bindings path escapes Final Package")
            candidates.append(candidate)
        candidates.append(root / "semantic_bindings.json")

        for candidate in candidates:
            if not candidate.is_file():
                continue
            data = self._load_json(candidate)
            self._validate_semantic_bindings(data)
            return data
        return {}

    @staticmethod
    def _validate_semantic_bindings(data: dict) -> None:
        schema = data.get("schema_name")
        if schema is not None and schema not in _SEMANTIC_BINDING_SCHEMAS:
            raise InvalidPackageError("unsupported semantic bindings schema")
        asset_level = schema == "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS"
        if asset_level:
            semantic_intent = data.get("asset_is_semantic_intent_not_cutout")
            if semantic_intent is not None and semantic_intent is not True:
                raise InvalidPackageError(
                    "asset-level semantic bindings must describe semantic intent"
                )
            no_fixed_timing = data.get("no_fixed_timing")
            if no_fixed_timing is not None and no_fixed_timing is not True:
                raise InvalidPackageError(
                    "asset-level semantic bindings cannot own fixed timing"
                )
            cardinality = data.get("cutout_mapping_cardinality")
            if cardinality is not None and cardinality != "ZERO_OR_ONE_OR_MANY":
                raise InvalidPackageError(
                    "asset-level semantic cutout_mapping_cardinality must be "
                    "ZERO_OR_ONE_OR_MANY"
                )

        scenes = data.get("scenes")
        if not isinstance(scenes, list):
            raise InvalidPackageError("semantic bindings scenes must be a list")

        seen_scenes: set[str] = set()
        for scene in scenes:
            if not isinstance(scene, dict):
                raise InvalidPackageError("semantic bindings scene must be an object")
            scene_id = scene.get("scene_id")
            if not isinstance(scene_id, str) or not scene_id.strip():
                raise InvalidPackageError("semantic bindings scene_id is required")
            if scene_id in seen_scenes:
                raise InvalidPackageError(f"duplicate semantic bindings scene: {scene_id}")
            seen_scenes.add(scene_id)

            assets = scene.get("assets")
            if not isinstance(assets, list):
                raise InvalidPackageError(
                    f"semantic bindings assets must be a list: {scene_id}"
                )
            seen_assets: set[str] = set()
            parent_by_asset: dict[str, str | None] = {}
            group_by_asset: dict[str, str] = {}
            event_by_asset: dict[str, str] = {}
            for asset in assets:
                if not isinstance(asset, dict):
                    raise InvalidPackageError(
                        f"semantic binding asset must be an object: {scene_id}"
                    )
                asset_id = asset.get("asset_id")
                phrase = asset.get("script_text")
                if not isinstance(asset_id, str) or not asset_id.strip():
                    raise InvalidPackageError(
                        f"semantic binding asset_id is required: {scene_id}"
                    )
                if asset_id in seen_assets:
                    raise InvalidPackageError(
                        f"duplicate semantic binding asset: {scene_id}:{asset_id}"
                    )
                if not isinstance(phrase, str) or not phrase.strip():
                    raise InvalidPackageError(
                        f"semantic binding script_text is required: {scene_id}:{asset_id}"
                    )
                declared_scene = asset.get("scene_id")
                if declared_scene is not None and declared_scene != scene_id:
                    raise InvalidPackageError(
                        f"semantic binding scene mismatch: {scene_id}:{asset_id}"
                    )
                parent = asset.get("parent_asset_id")
                if parent is not None and not isinstance(parent, str):
                    raise InvalidPackageError(
                        f"semantic binding parent_asset_id must be a string: {scene_id}:{asset_id}"
                    )

                if asset_level:
                    binding_type = asset.get("binding_type")
                    if binding_type not in _ASSET_LEVEL_BINDING_TYPES:
                        raise InvalidPackageError(
                            f"invalid semantic binding type: {scene_id}:{asset_id}"
                        )
                    group_id = asset.get("semantic_group_id")
                    if not isinstance(group_id, str) or not group_id.strip():
                        raise InvalidPackageError(
                            f"semantic_group_id is required: {scene_id}:{asset_id}"
                        )
                    order = asset.get("sequence_order")
                    if isinstance(order, bool) or not isinstance(order, int) or order < 1:
                        raise InvalidPackageError(
                            f"sequence_order must be a positive integer: {scene_id}:{asset_id}"
                        )
                    confidence = asset.get("confidence")
                    if (
                        isinstance(confidence, bool)
                        or not isinstance(confidence, (int, float))
                        or not 0.0 <= float(confidence) <= 1.0
                    ):
                        raise InvalidPackageError(
                            f"confidence must be between 0 and 1: {scene_id}:{asset_id}"
                        )
                    locator = asset.get("visual_locator")
                    if locator is not None:
                        FinalPackageLoader._validate_visual_locator(
                            locator, scene_id=scene_id, asset_id=asset_id
                        )
                    script_span = asset.get("script_span")
                    if script_span is not None and not isinstance(script_span, dict):
                        raise InvalidPackageError(
                            f"script_span must be an object: {scene_id}:{asset_id}"
                        )
                    visual_focus = asset.get("visual_focus")
                    if visual_focus is not None:
                        if (
                            not isinstance(visual_focus, str)
                            or visual_focus.upper() not in _VISUAL_FOCUS_VALUES
                        ):
                            raise InvalidPackageError(
                                f"invalid visual_focus: {scene_id}:{asset_id}"
                            )
                    anchor_granularity = asset.get("anchor_granularity")
                    if anchor_granularity is not None and (
                        not isinstance(anchor_granularity, str)
                        or anchor_granularity.upper() not in _ANCHOR_GRANULARITIES
                    ):
                        raise InvalidPackageError(
                            f"invalid anchor_granularity: {scene_id}:{asset_id}"
                        )
                    compound = asset.get("compound_visual_classification")
                    if compound is not None and (
                        not isinstance(compound, str)
                        or compound.upper() not in _COMPOUND_VISUAL_CLASSIFICATIONS
                    ):
                        raise InvalidPackageError(
                            f"invalid compound_visual_classification: {scene_id}:{asset_id}"
                        )
                    internal_unavailable = asset.get("internal_progression_unavailable")
                    if internal_unavailable is not None and not isinstance(internal_unavailable, bool):
                        raise InvalidPackageError(
                            f"internal_progression_unavailable must be boolean: {scene_id}:{asset_id}"
                        )
                    if internal_unavailable is True and str(compound or "").upper() != "COMPOUND_REQUIRED":
                        raise InvalidPackageError(
                            f"internal_progression_unavailable requires COMPOUND_REQUIRED: {scene_id}:{asset_id}"
                        )
                    semantic_event_id = asset.get("semantic_event_id")
                    if semantic_event_id is not None:
                        if not isinstance(semantic_event_id, str) or not semantic_event_id.strip():
                            raise InvalidPackageError(
                                f"semantic_event_id must be non-empty: {scene_id}:{asset_id}"
                            )
                        event_by_asset[asset_id] = semantic_event_id
                    visual_state = asset.get("visual_state")
                    if visual_state is not None:
                        if not isinstance(visual_state, dict):
                            raise InvalidPackageError(
                                f"visual_state must be an object: {scene_id}:{asset_id}"
                            )
                        before = visual_state.get("before")
                        after = visual_state.get("after")
                        if (
                            not isinstance(before, str)
                            or not before.strip()
                            or not isinstance(after, str)
                            or not after.strip()
                            or before.strip() == after.strip()
                        ):
                            raise InvalidPackageError(
                                f"visual_state requires distinct before/after values: "
                                f"{scene_id}:{asset_id}"
                            )
                    continuity = asset.get("continuity")
                    if continuity is not None:
                        if not isinstance(continuity, dict):
                            raise InvalidPackageError(
                                f"continuity must be an object: {scene_id}:{asset_id}"
                            )
                        mode = continuity.get("mode")
                        if mode not in _CONTINUITY_MODES:
                            raise InvalidPackageError(
                                f"unsupported continuity mode: {scene_id}:{asset_id}"
                            )
                        if mode == "TRANSFORM_TO":
                            target = continuity.get("target_asset_id")
                            if not isinstance(target, str) or not target.strip():
                                raise InvalidPackageError(
                                    f"TRANSFORM_TO continuity requires target_asset_id: "
                                    f"{scene_id}:{asset_id}"
                                )
                    group_by_asset[asset_id] = group_id

                seen_assets.add(asset_id)
                parent_by_asset[asset_id] = parent

            for asset_id, parent in parent_by_asset.items():
                if parent is not None and parent not in seen_assets:
                    raise InvalidPackageError(
                        f"semantic binding parent is missing: {scene_id}:{asset_id}"
                    )

            for asset_id in parent_by_asset:
                chain: set[str] = set()
                current: str | None = asset_id
                while current is not None:
                    if current in chain:
                        raise InvalidPackageError(
                            f"semantic binding parent cycle: {scene_id}:{asset_id}"
                        )
                    chain.add(current)
                    current = parent_by_asset.get(current)

            if asset_level:
                groups = scene.get("semantic_groups")
                if not isinstance(groups, list) or not groups:
                    raise InvalidPackageError(
                        f"asset-level semantic_groups are required: {scene_id}"
                    )
                declared_groups: dict[str, dict] = {}
                referenced_assets: set[str] = set()
                for group in groups:
                    if not isinstance(group, dict):
                        raise InvalidPackageError(
                            f"semantic group must be an object: {scene_id}"
                        )
                    group_id = group.get("semantic_group_id")
                    if not isinstance(group_id, str) or not group_id.strip():
                        raise InvalidPackageError(
                            f"semantic group id is required: {scene_id}"
                        )
                    if group_id in declared_groups:
                        raise InvalidPackageError(
                            f"duplicate semantic group: {scene_id}:{group_id}"
                        )
                    policy = group.get("animation_policy", "SEQUENTIAL_WITHIN_PHRASE")
                    if policy not in _SEMANTIC_GROUP_POLICIES:
                        raise InvalidPackageError(
                            f"unsupported semantic group policy: {scene_id}:{group_id}"
                        )
                    group_assets = group.get("asset_ids")
                    if not isinstance(group_assets, list) or not group_assets:
                        raise InvalidPackageError(
                            f"semantic group asset_ids are required: {scene_id}:{group_id}"
                        )
                    for asset_id in group_assets:
                        if asset_id not in seen_assets:
                            raise InvalidPackageError(
                                f"semantic group references missing asset: {scene_id}:{group_id}"
                            )
                        if group_by_asset.get(asset_id) != group_id:
                            raise InvalidPackageError(
                                f"semantic group membership mismatch: {scene_id}:{asset_id}"
                            )
                        if asset_id in referenced_assets:
                            raise InvalidPackageError(
                                f"semantic asset appears in multiple groups: {scene_id}:{asset_id}"
                            )
                        referenced_assets.add(asset_id)
                    group_phrase = group.get("script_text")
                    if not isinstance(group_phrase, str) or not group_phrase.strip():
                        raise InvalidPackageError(
                            f"semantic group script_text is required: {scene_id}:{group_id}"
                        )
                    declared_groups[group_id] = group
                if referenced_assets != seen_assets:
                    raise InvalidPackageError(
                        f"semantic groups must cover every semantic asset: {scene_id}"
                    )

                relations = scene.get("relations", [])
                if relations is not None and not isinstance(relations, list):
                    raise InvalidPackageError(
                        f"semantic relations must be a list: {scene_id}"
                    )
                seen_relations: set[str] = set()
                for relation in relations or []:
                    if not isinstance(relation, dict):
                        raise InvalidPackageError(
                            f"semantic relation must be an object: {scene_id}"
                        )
                    relation_id = relation.get("relation_id")
                    if relation_id is not None:
                        if not isinstance(relation_id, str) or not relation_id.strip():
                            raise InvalidPackageError(
                                f"semantic relation_id must be non-empty: {scene_id}"
                            )
                        if relation_id in seen_relations:
                            raise InvalidPackageError(
                                f"duplicate semantic relation: {scene_id}:{relation_id}"
                            )
                        seen_relations.add(relation_id)
                    subject = relation.get("subject_asset_id")
                    if not isinstance(subject, str) or subject not in seen_assets:
                        raise InvalidPackageError(
                            f"semantic relation subject is missing: {scene_id}"
                        )
                    relationship = relation.get("relationship") or relation.get("relation_type")
                    if not isinstance(relationship, str) or not relationship.strip():
                        raise InvalidPackageError(
                            f"semantic relation relationship/relation_type is required: {scene_id}"
                        )
                    for field in ("object_asset_id", "result_asset_id"):
                        target = relation.get(field)
                        if target is not None and (
                            not isinstance(target, str) or target not in seen_assets
                        ):
                            raise InvalidPackageError(
                                f"semantic relation {field} is missing: {scene_id}"
                            )
                    confidence = relation.get("confidence")
                    if confidence is not None and (
                        isinstance(confidence, bool)
                        or not isinstance(confidence, (int, float))
                        or not 0.0 <= float(confidence) <= 1.0
                    ):
                        raise InvalidPackageError(
                            f"semantic relation confidence must be between 0 and 1: {scene_id}"
                        )
                    relation_span = relation.get("script_span")
                    if relation_span is not None and not isinstance(relation_span, dict):
                        raise InvalidPackageError(
                            f"semantic relation script_span must be an object: {scene_id}"
                        )

                FinalPackageLoader._validate_semantic_events(
                    scene=scene,
                    scene_id=scene_id,
                    seen_assets=seen_assets,
                    event_by_asset=event_by_asset,
                )

        FinalPackageLoader._validate_top_level_semantic_events(data)

    @staticmethod
    def _validate_semantic_events(
        *,
        scene: dict,
        scene_id: str,
        seen_assets: set[str],
        event_by_asset: dict[str, str],
    ) -> None:
        events = scene.get("semantic_events", [])
        if events is None:
            events = []
        if not isinstance(events, list):
            raise InvalidPackageError(f"semantic_events must be a list: {scene_id}")

        event_rows: dict[str, dict] = {}
        referenced_assets: dict[str, set[str]] = {}
        dependency_map: dict[str, list[str]] = {}
        for event in events:
            if not isinstance(event, dict):
                raise InvalidPackageError(f"semantic event must be an object: {scene_id}")
            event_id = event.get("semantic_event_id")
            if not isinstance(event_id, str) or not event_id.strip():
                raise InvalidPackageError(f"semantic_event_id is required: {scene_id}")
            if event_id in event_rows:
                raise InvalidPackageError(f"duplicate semantic event: {scene_id}:{event_id}")
            declared_scene = event.get("scene_id")
            if declared_scene is not None and declared_scene != scene_id:
                raise InvalidPackageError(f"semantic event scene mismatch: {scene_id}:{event_id}")
            phrase = event.get("script_text")
            if not isinstance(phrase, str) or not phrase.strip():
                raise InvalidPackageError(f"semantic event script_text is required: {scene_id}:{event_id}")
            span = event.get("script_span")
            if not isinstance(span, dict):
                raise InvalidPackageError(f"semantic event script_span is required: {scene_id}:{event_id}")
            anchor = event.get("anchor_granularity")
            if anchor is not None and (
                not isinstance(anchor, str) or anchor.upper() not in _ANCHOR_GRANULARITIES
            ):
                raise InvalidPackageError(f"invalid semantic event anchor_granularity: {scene_id}:{event_id}")
            order = event.get("sequence_order")
            if isinstance(order, bool) or not isinstance(order, int) or order < 1:
                raise InvalidPackageError(f"semantic event sequence_order must be positive: {scene_id}:{event_id}")
            confidence = event.get("confidence")
            if confidence is not None and (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0.0 <= float(confidence) <= 1.0
            ):
                raise InvalidPackageError(f"semantic event confidence must be between 0 and 1: {scene_id}:{event_id}")

            leader = event.get("visual_leader_asset_id")
            text_anchor = event.get("text_anchor_asset_id")
            for field, asset_id in (("visual_leader_asset_id", leader), ("text_anchor_asset_id", text_anchor)):
                if not isinstance(asset_id, str) or asset_id not in seen_assets:
                    raise InvalidPackageError(f"semantic event {field} is missing: {scene_id}:{event_id}")

            role_assets: set[str] = {str(leader), str(text_anchor)}
            for field in ("participant_asset_ids", "context_asset_ids", "result_asset_ids"):
                values = event.get(field, [])
                if not isinstance(values, list) or any(
                    not isinstance(value, str) or value not in seen_assets for value in values
                ):
                    raise InvalidPackageError(f"semantic event {field} is invalid: {scene_id}:{event_id}")
                role_assets.update(values)

            dependencies = event.get("depends_on_event_ids", [])
            if dependencies is None:
                dependencies = []
            if not isinstance(dependencies, list) or any(
                not isinstance(value, str) or not value.strip() for value in dependencies
            ):
                raise InvalidPackageError(f"semantic event dependencies are invalid: {scene_id}:{event_id}")
            if event_id in dependencies:
                raise InvalidPackageError(f"semantic event cannot depend on itself: {scene_id}:{event_id}")

            event_rows[event_id] = event
            referenced_assets[event_id] = role_assets
            dependency_map[event_id] = list(dependencies)

        for event_id, dependencies in dependency_map.items():
            for dependency in dependencies:
                if dependency not in event_rows:
                    raise InvalidPackageError(
                        f"semantic event dependency is missing: {scene_id}:{event_id}:{dependency}"
                    )

        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(event_id: str) -> None:
            if event_id in visited:
                return
            if event_id in visiting:
                raise InvalidPackageError(f"semantic event dependency cycle: {scene_id}:{event_id}")
            visiting.add(event_id)
            for dependency in dependency_map.get(event_id, []):
                visit(dependency)
            visiting.remove(event_id)
            visited.add(event_id)
        for event_id in event_rows:
            visit(event_id)

        for asset_id, event_id in event_by_asset.items():
            if event_id not in event_rows:
                raise InvalidPackageError(
                    f"semantic asset references missing event: {scene_id}:{asset_id}:{event_id}"
                )
            if asset_id not in referenced_assets[event_id]:
                raise InvalidPackageError(
                    f"semantic event does not reference assigned asset: {scene_id}:{asset_id}:{event_id}"
                )

        progression = scene.get("progression")
        if progression is not None:
            if not isinstance(progression, dict):
                raise InvalidPackageError(f"semantic progression must be an object: {scene_id}")
            progression_type = progression.get("type")
            if progression_type is not None and (
                not isinstance(progression_type, str) or not progression_type.strip()
            ):
                raise InvalidPackageError(f"semantic progression type must be non-empty: {scene_id}")
            event_order = progression.get("event_order")
            if not isinstance(event_order, list) or not event_order:
                raise InvalidPackageError(f"semantic progression event_order is required: {scene_id}")
            if len(set(event_order)) != len(event_order) or any(
                not isinstance(value, str) or value not in event_rows for value in event_order
            ):
                raise InvalidPackageError(f"semantic progression event_order is invalid: {scene_id}")
            sequence = [int(event_rows[event_id]["sequence_order"]) for event_id in event_order]
            if any(right <= left for left, right in zip(sequence, sequence[1:])):
                raise InvalidPackageError(f"semantic progression order conflicts with event sequence: {scene_id}")

    @staticmethod
    def _validate_top_level_semantic_events(data: dict) -> None:
        top_events = data.get("semantic_events")
        if top_events is None:
            return
        if not isinstance(top_events, list):
            raise InvalidPackageError("top-level semantic_events must be a list")
        scene_events = {
            str(event.get("semantic_event_id")): str(scene.get("scene_id"))
            for scene in data.get("scenes", [])
            if isinstance(scene, dict)
            for event in scene.get("semantic_events", [])
            if isinstance(event, dict) and event.get("semantic_event_id")
        }
        seen: set[str] = set()
        for event in top_events:
            if not isinstance(event, dict):
                raise InvalidPackageError("top-level semantic event must be an object")
            event_id = event.get("semantic_event_id")
            scene_id = event.get("scene_id")
            if not isinstance(event_id, str) or event_id in seen:
                raise InvalidPackageError("top-level semantic event id must be unique")
            seen.add(event_id)
            if event_id not in scene_events or scene_events[event_id] != scene_id:
                raise InvalidPackageError(f"top-level semantic event mismatch: {event_id}")
        if seen != set(scene_events):
            raise InvalidPackageError("top-level semantic_events must mirror scene semantic events")

    @staticmethod
    def _validate_visual_locator(locator: object, *, scene_id: str, asset_id: str) -> None:
        if not isinstance(locator, dict):
            raise InvalidPackageError(
                f"visual_locator must be an object: {scene_id}:{asset_id}"
            )
        coordinate_space = locator.get("coordinate_space", "normalized_scene")
        if coordinate_space != "normalized_scene":
            raise InvalidPackageError(
                f"visual_locator coordinate_space must be normalized_scene: "
                f"{scene_id}:{asset_id}"
            )
        values: dict[str, float] = {}
        for name in ("cx", "cy", "width", "height"):
            value = locator.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise InvalidPackageError(
                    f"visual_locator {name} must be numeric: {scene_id}:{asset_id}"
                )
            values[name] = float(value)
        cx, cy = values["cx"], values["cy"]
        width, height = values["width"], values["height"]
        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
            raise InvalidPackageError(
                f"visual_locator center must be normalized: {scene_id}:{asset_id}"
            )
        if not (0.0 < width <= 1.0 and 0.0 < height <= 1.0):
            raise InvalidPackageError(
                f"visual_locator size must be normalized and positive: {scene_id}:{asset_id}"
            )
        epsilon = 1e-9
        if (
            cx - width / 2 < -epsilon
            or cx + width / 2 > 1.0 + epsilon
            or cy - height / 2 < -epsilon
            or cy + height / 2 > 1.0 + epsilon
        ):
            raise InvalidPackageError(
                f"visual_locator must stay inside scene bounds: {scene_id}:{asset_id}"
            )

    @staticmethod
    def _validate_scene_unit_visual_locators(scenes: list[SceneSource]) -> None:
        for scene in scenes:
            for unit in scene.units:
                if not isinstance(unit, dict) or unit.get("visual_locator") is None:
                    continue
                unit_id = str(unit.get("unit_id") or "unknown")
                FinalPackageLoader._validate_visual_locator(
                    unit["visual_locator"],
                    scene_id=scene.id,
                    asset_id=unit_id,
                )

    @staticmethod
    def _validate_semantic_binding_script(data: dict, script: str | None) -> None:
        if not data:
            return
        for scene in data.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("scene_id") or "")
            for asset in scene.get("assets", []):
                if not isinstance(asset, dict):
                    continue
                phrase = str(asset.get("script_text") or "").strip()
                if script and phrase and phrase not in script:
                    raise InvalidPackageError(
                        f"semantic binding script_text not found in canonical script: "
                        f"{scene_id}:{asset.get('asset_id')}"
                    )
                FinalPackageLoader._validate_precise_script_span(
                    script,
                    asset.get("script_span"),
                    phrase,
                    context=f"{scene_id}:{asset.get('asset_id')}",
                )
            for group in scene.get("semantic_groups", []):
                if not isinstance(group, dict):
                    continue
                phrase = str(group.get("script_text") or "").strip()
                if script and phrase and phrase not in script:
                    raise InvalidPackageError(
                        f"semantic group script_text not found in canonical script: "
                        f"{scene_id}:{group.get('semantic_group_id')}"
                    )
            for relation in scene.get("relations", []) or []:
                if not isinstance(relation, dict):
                    continue
                phrase = str(relation.get("script_text") or "").strip()
                if script and phrase and phrase not in script:
                    raise InvalidPackageError(
                        f"semantic relation script_text not found in canonical script: "
                        f"{scene_id}:{relation.get('relation_id')}"
                    )
                FinalPackageLoader._validate_precise_script_span(
                    script,
                    relation.get("script_span"),
                    phrase,
                    context=f"{scene_id}:{relation.get('relation_id') or relation.get('relation_type') or 'relation'}",
                )
            for event in scene.get("semantic_events", []) or []:
                if not isinstance(event, dict):
                    continue
                phrase = str(event.get("script_text") or "").strip()
                if script and phrase and phrase not in script:
                    raise InvalidPackageError(
                        f"semantic event script_text not found in canonical script: "
                        f"{scene_id}:{event.get('semantic_event_id')}"
                    )
                FinalPackageLoader._validate_precise_script_span(
                    script,
                    event.get("script_span"),
                    phrase,
                    context=f"{scene_id}:{event.get('semantic_event_id') or 'semantic_event'}",
                )

    @staticmethod
    def _validate_precise_script_span(
        script: str | None,
        span: object,
        expected_text: str,
        *,
        context: str,
    ) -> None:
        if span is None:
            return
        if script is None:
            raise InvalidPackageError(
                f"script_span requires canonical script: {context}"
            )
        if not isinstance(span, dict):
            raise InvalidPackageError(f"script_span must be an object: {context}")
        local_start = span.get("char_start")
        local_end = span.get("char_end")
        global_start = span.get("global_char_start")
        global_end = span.get("global_char_end")
        if local_start is not None or local_end is not None:
            start, end = local_start, local_end
            if (global_start is not None or global_end is not None) and (
                global_start != local_start or global_end != local_end
            ):
                raise InvalidPackageError(f"conflicting script_span coordinates: {context}")
        else:
            start, end = global_start, global_end
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(script)
        ):
            raise InvalidPackageError(f"invalid half-open script_span: {context}")
        if expected_text and script[start:end] != expected_text:
            raise InvalidPackageError(f"script_span does not match script_text: {context}")

    @staticmethod
    def _validate_semantic_binding_units(data: dict, scenes: list[SceneSource]) -> None:
        if data.get("schema_name") != "HEXA_ASSET_LEVEL_SEMANTIC_BINDINGS":
            return
        binding_scenes = {
            str(row.get("scene_id")): row
            for row in data.get("scenes", [])
            if isinstance(row, dict)
        }
        for scene in scenes:
            binding_scene = binding_scenes.get(scene.id)
            if binding_scene is None or not scene.units:
                continue
            unit_ids = {
                str(unit.get("unit_id"))
                for unit in scene.units
                if isinstance(unit, dict) and unit.get("unit_id")
            }
            missing = [
                str(asset.get("asset_id"))
                for asset in binding_scene.get("assets", [])
                if isinstance(asset, dict) and str(asset.get("asset_id")) not in unit_ids
            ]
            if missing:
                raise InvalidPackageError(
                    f"semantic asset intent missing from scene plan: {scene.id}:{missing[0]}"
                )

    def _load_scene_plan(self, root: Path, manifest: dict) -> dict:
        raw = manifest.get("scene_plan")
        candidates: list[Path] = []
        if isinstance(raw, str):
            candidate = (root / raw).resolve()
            if not self._inside(root, candidate):
                raise InvalidPackageError("scene plan path escapes Final Package")
            candidates.append(candidate)
        candidates.append(root / "scene_plan.json")
        for candidate in candidates:
            if candidate.is_file():
                return self._load_json(candidate)
        return {}

    def _load_script(self, root: Path, explicit: Path | None, manifest: dict) -> str | None:
        candidates: list[Path] = []
        if explicit:
            candidates.append(explicit.expanduser().resolve())
        for field in ("script", "canonical_script"):
            manifest_script = manifest.get(field)
            if not isinstance(manifest_script, str):
                continue
            candidate = (root / manifest_script).resolve()
            if self._inside(root, candidate) and candidate.exists():
                candidates.append(candidate)
                continue
            if field == "script" and ("\n" in manifest_script or len(manifest_script.split()) > 5):
                return manifest_script.strip()
        candidates.extend([root / "canonical_script.txt", root / "script.txt", root / "narration.txt"])
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.read_text(encoding="utf-8-sig").strip()
        return None

    def _discover_scenes(self, root: Path, manifest: dict, scene_plan: dict) -> list[SceneSource]:
        planned = scene_plan.get("scenes")
        if isinstance(planned, list):
            rows: list[SceneSource] = []
            for index, item in enumerate(planned):
                if not isinstance(item, dict):
                    continue
                raw_path = item.get("image") or item.get("path")
                if not isinstance(raw_path, str):
                    continue
                image = (root / raw_path).resolve()
                if not self._inside(root, image):
                    raise InvalidPackageError(f"scene path escapes Final Package: {raw_path}")
                if not image.is_file() or image.suffix.lower() not in _IMAGE_EXTENSIONS:
                    continue
                span = item.get("script_span") if isinstance(item.get("script_span"), dict) else {}
                rows.append(SceneSource(
                    id=str(item.get("scene_id") or item.get("id") or f"scene-{index + 1:03d}"),
                    image_path=image,
                    order=int(item.get("order", index + 1)) - 1,
                    title=item.get("title"),
                    narration_hint=span.get("text") or item.get("narration") or item.get("text"),
                    script_char_start=self._int_or_none(span.get("global_char_start")),
                    script_char_end=self._int_or_none(span.get("global_char_end")),
                    purpose=item.get("purpose"),
                    visual_concept=item.get("visual_concept"),
                    relation_to_previous=item.get("relation_to_previous"),
                    units=[row for row in item.get("units", []) if isinstance(row, dict)],
                    visual_progression=[
                        row for row in item.get("visual_progression", []) if isinstance(row, dict)
                    ],
                    semantic_events=[
                        row for row in item.get("semantic_events", []) if isinstance(row, dict)
                    ],
                    semantic_progression=(
                        dict(item["progression"])
                        if isinstance(item.get("progression"), dict)
                        else None
                    ),
                ))
            if rows:
                return sorted(rows, key=lambda row: row.order)

        declared = manifest.get("scenes")
        scenes: list[SceneSource] = []
        if isinstance(declared, list):
            for index, item in enumerate(declared):
                if not isinstance(item, dict):
                    continue
                raw_path = item.get("image") or item.get("path")
                if not isinstance(raw_path, str):
                    continue
                image = (root / raw_path).resolve()
                if not self._inside(root, image):
                    raise InvalidPackageError(f"scene path escapes Final Package: {raw_path}")
                if image.exists() and image.suffix.lower() in _IMAGE_EXTENSIONS:
                    scenes.append(SceneSource(
                        id=str(item.get("id") or f"scene-{index + 1:03d}"),
                        image_path=image,
                        order=index,
                        title=item.get("title"),
                        narration_hint=item.get("narration") or item.get("text"),
                    ))
        if scenes:
            return scenes
        scene_dirs = [root / "scenes", root / "images", root]
        images: list[Path] = []
        for directory in scene_dirs:
            if directory.exists():
                images = sorted(
                    p for p in directory.iterdir()
                    if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
                )
                if images:
                    break
        return [
            SceneSource(id=f"scene-{i + 1:03d}", image_path=path, order=i)
            for i, path in enumerate(images)
        ]

    @staticmethod
    def _int_or_none(value) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _inside(root: Path, candidate: Path) -> bool:
        root = root.resolve()
        candidate = candidate.resolve()
        return candidate == root or root in candidate.parents

    @staticmethod
    def _stable_package_id(source: Path) -> str:
        digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
        return f"pkg-{digest}"
