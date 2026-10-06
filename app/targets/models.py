from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.choreography import ChoreographyDirective
    from app.models import LayoutItem, VisualAsset

# Every production target shares the certified 1080p reference pixel scale: the visual
# engine authors pixel-sized constants (clearance, connector length, glyph metrics) at
# this resolution, and a target only changes how many of those pixels fit on each axis.
REFERENCE_WIDTH = 1920
REFERENCE_HEIGHT = 1080


@dataclass(frozen=True, slots=True)
class NormalizedRect:
    """An axis-aligned region in normalized frame units (0..1 on both axes)."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.left < self.right <= 1.0 and 0.0 <= self.top < self.bottom <= 1.0):
            raise ValueError(f"invalid normalized rect: {self}")

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def contains(self, box: tuple[float, float, float, float], *, tolerance: float = 0.0) -> bool:
        return (
            box[0] >= self.left - tolerance and box[1] >= self.top - tolerance
            and box[2] <= self.right + tolerance and box[3] <= self.bottom + tolerance
        )

    def intersects(self, box: tuple[float, float, float, float]) -> bool:
        return (
            min(self.right, box[2]) > max(self.left, box[0])
            and min(self.bottom, box[3]) > max(self.top, box[1])
        )


@dataclass(frozen=True, slots=True)
class FrameMargins:
    """Inset of a safe region from each frame edge (normalized units).

    Stored as margins, not edges, so the reference target reproduces the certified
    ``1.0 - margin`` arithmetic exactly.
    """

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        if min(self.left, self.top, self.right, self.bottom) < 0.0:
            raise ValueError("margins must be non-negative")
        if self.left + self.right >= 1.0 or self.top + self.bottom >= 1.0:
            raise ValueError("margins leave no safe region")

    @property
    def rect(self) -> NormalizedRect:
        return NormalizedRect(self.left, self.top, 1.0 - self.right, 1.0 - self.bottom)


@dataclass(frozen=True, slots=True)
class TargetSafeZones:
    """Where important artwork and text may live on one target frame.

    ``content`` bounds every important visual footprint. ``text`` bounds every important
    text box. ``reserved`` lists platform UI regions that no important text or artwork may
    enter. All three are owned by the target, never by Story or Choreography.
    """

    content: NormalizedRect
    text_margins: FrameMargins
    reserved: tuple[NormalizedRect, ...] = ()
    min_edge_padding_px: int = 0

    @property
    def text(self) -> NormalizedRect:
        return self.text_margins.rect

    def __post_init__(self) -> None:
        for region in self.reserved:
            if region.intersects((self.content.left, self.content.top, self.content.right, self.content.bottom)):
                raise ValueError("content safe frame overlaps a reserved UI region")
            if region.intersects((self.text.left, self.text.top, self.text.right, self.text.bottom)):
                raise ValueError("text safe frame overlaps a reserved UI region")


@dataclass(frozen=True, slots=True)
class TargetProjection:
    items: list["LayoutItem"]
    evidence: str


class TargetCompositionPolicy(Protocol):
    """Map one authored scene layout onto a target frame; never reinterpret semantics."""

    def project(
        self,
        items: list["LayoutItem"],
        assets: list["VisualAsset"],
        directives: list["ChoreographyDirective"],
    ) -> TargetProjection: ...


@dataclass(frozen=True, slots=True)
class VisualTargetProfile:
    """Immutable facts about one output format of the single shared visual engine."""

    target_id: str
    width: int
    height: int
    fps: int
    safe_zones: TargetSafeZones
    layout_policy: str
    output_suffix: str
    description: str = ""
    # Responsive-layout knobs owned by the target (unused by the reference policy).
    layout_options: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.width % 2 or self.height % 2:
            raise ValueError("target dimensions must be positive and even (yuv420p)")
        if self.fps <= 0:
            raise ValueError("target fps must be positive")
        if not self.target_id or not self.output_suffix.isalnum():
            raise ValueError("target id and alphanumeric output suffix are required")

    @property
    def aspect_ratio(self) -> Fraction:
        return Fraction(self.width, self.height)

    @property
    def frame(self) -> tuple[int, int]:
        return self.width, self.height

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    @property
    def is_reference(self) -> bool:
        return self.layout_policy == "authored_reference"

    def x_scale(self) -> float:
        """Reference-pixel to normalized-x factor ratio (exactly 1.0 on the reference)."""
        return REFERENCE_WIDTH / self.width

    def y_scale(self) -> float:
        return REFERENCE_HEIGHT / self.height
