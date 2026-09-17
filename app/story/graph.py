from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import StoryBeat


class StoryGraphNode(BaseModel):
    beat_id: str
    scene_id: str
    story_role: str
    semantic_names: list[str] = Field(default_factory=list)
    tension: float = Field(default=0.0, ge=0, le=1)
    confidence: float = Field(default=0.0, ge=0, le=1)


class StoryGraphEdge(BaseModel):
    source_beat_id: str
    target_beat_id: str
    kind: str
    authority: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    causal: bool = False
    shared_semantic_names: list[str] = Field(default_factory=list)


class StoryGraph(BaseModel):
    nodes: list[StoryGraphNode] = Field(default_factory=list)
    edges: list[StoryGraphEdge] = Field(default_factory=list)


class StoryGraphBuilder:
    """Build a cross-beat semantic graph without inventing cause/effect.

    Explicit Final Package scene relations are retained as authority. Shared semantic
    identity is represented as continuity evidence only; it is never promoted to a
    physical handoff or causal edge at this layer.
    """

    def build(self, beats: list[StoryBeat]) -> StoryGraph:
        nodes = [self._node(beat) for beat in beats]
        edges: list[StoryGraphEdge] = []

        for source, target in zip(beats, beats[1:]):
            target_context = target.semantic_context
            relation = target_context.continuity_relation if target_context else None
            edges.append(
                StoryGraphEdge(
                    source_beat_id=source.id,
                    target_beat_id=target.id,
                    kind=relation or "TEMPORAL_NEXT",
                    authority=(
                        "FINAL_PACKAGE_SCENE_RELATION"
                        if relation
                        else "NARRATION_TIMELINE"
                    ),
                    confidence=0.98 if relation else 0.70,
                    causal=False,
                )
            )

            shared = sorted(self._semantic_names(source) & self._semantic_names(target))
            if shared:
                edges.append(
                    StoryGraphEdge(
                        source_beat_id=source.id,
                        target_beat_id=target.id,
                        kind="SHARED_SEMANTIC_IDENTITY",
                        authority="FINAL_PACKAGE_SEMANTIC_NAME",
                        confidence=0.88,
                        causal=False,
                        shared_semantic_names=shared,
                    )
                )

        return StoryGraph(nodes=nodes, edges=edges)

    @staticmethod
    def _node(beat: StoryBeat) -> StoryGraphNode:
        context = beat.semantic_context
        return StoryGraphNode(
            beat_id=beat.id,
            scene_id=beat.scene_id,
            story_role=context.story_role if context else "CONTEXT",
            semantic_names=sorted(StoryGraphBuilder._semantic_names(beat)),
            tension=context.tension if context else 0.0,
            confidence=context.confidence if context else 0.0,
        )

    @staticmethod
    def _semantic_names(beat: StoryBeat) -> set[str]:
        context = beat.semantic_context
        if context is None:
            return set()
        return {
            entity.semantic_name
            for entity in context.entities
            if entity.semantic_name
        }
