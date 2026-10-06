from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from app.assets import AssetManager
from app.choreography import ChoreographyDirective
from app.layout.footprint import AlphaFootprintResolver
from app.models import LayoutItem, VisualAsset
from app.targets.models import REFERENCE_HEIGHT, REFERENCE_WIDTH, NormalizedRect, TargetProjection

Rect = tuple[float, float, float, float]

REFLOW_PLACEMENT_SOURCE = "authored_target_reflow"


@dataclass(frozen=True, slots=True)
class _Cluster:
    """A rigid block of the authored scene: one or more families in authored contact."""

    key: str
    item_ids: tuple[str, ...]
    foot: Rect  # visible footprint in reference (16:9) pixels
    reading: tuple[float, float]


@dataclass(frozen=True, slots=True)
class _Arrangement:
    rows: tuple[tuple[int, ...], ...]
    scale: float


class ReelsCompositionPolicy:
    """Responsive 9:16 projection of one authored scene; no new semantics, no cropping.

    The authored 16:9 layout (Final Package geometry, already contain-fit by the shared
    CompositionPlanner) is the spatial reference. Families in authored contact form rigid
    clusters, so a Pass2 family, or a character touching the object it holds, moves as
    one block with its internal geometry intact. Clusters are ordered by the authored
    relation topology Choreography already resolved (source above target, result last)
    with authored reading order as the tie-break, then packed into centred rows inside
    the target art region. One uniform scale is chosen for the whole scene, so the
    authored size hierarchy and the visual leader are preserved and no asset is
    stretched. The arrangement with the largest legible scale wins; ties keep fewer rows.
    Everything is deterministic and package-agnostic.
    """

    def __init__(
        self,
        *,
        frame: tuple[int, int],
        art_region: NormalizedRect,
        contact_px: float,
        gap_px: float,
        related_gap_px: float,
        max_scale: float,
        footprints: AlphaFootprintResolver | None = None,
    ) -> None:
        self.frame = frame
        self.art_region = art_region
        self.contact_px = contact_px
        self.gap_px = gap_px
        self.related_gap_px = related_gap_px
        self.max_scale = max_scale
        self.footprints = footprints or AlphaFootprintResolver()

    def project(
        self,
        items: list[LayoutItem],
        assets: list[VisualAsset],
        directives: list[ChoreographyDirective],
    ) -> TargetProjection:
        if not items:
            return TargetProjection(items=items, evidence="target:REELS_9_16:responsive:empty")
        by_id = {asset.id: asset for asset in assets}
        clusters = self._clusters(items, by_id)
        edges = self._edges(clusters, directives)
        order = self._order(clusters, edges)
        arrangement = self._arrange(clusters, order, edges)
        placed = self._place(items, clusters, arrangement, edges)
        rows = "|".join(",".join(str(index) for index in row) for row in arrangement.rows)
        return TargetProjection(
            items=placed,
            evidence=(
                f"target:REELS_9_16:responsive:clusters={len(clusters)}"
                f":rows={len(arrangement.rows)}[{rows}]:scale={arrangement.scale:.4f}"
            ),
        )

    # -- clusters ------------------------------------------------------------------------
    def _clusters(self, items: list[LayoutItem], by_id: dict[str, VisualAsset]) -> list[_Cluster]:
        families: dict[str, list[str]] = {}
        feet: dict[str, Rect] = {}
        for item in items:
            asset = by_id.get(item.asset_id)
            family = AssetManager.family_id(asset) if asset is not None else item.asset_id
            families.setdefault(family, []).append(item.asset_id)
            foot = self._foot(item, asset)
            prior = feet.get(family)
            feet[family] = foot if prior is None else _union(prior, foot)
        names = sorted(families)
        parent = {name: name for name in names}

        def root(name: str) -> str:
            while parent[name] != name:
                parent[name] = parent[parent[name]]
                name = parent[name]
            return name

        for left, right in combinations(names, 2):
            if _gap(feet[left], feet[right]) < self.contact_px:
                a, b = root(left), root(right)
                if a != b:
                    parent[max(a, b)] = min(a, b)
        grouped: dict[str, list[str]] = {}
        for name in names:
            grouped.setdefault(root(name), []).append(name)
        order = {item.asset_id: index for index, item in enumerate(items)}
        clusters = []
        for key, members in sorted(grouped.items()):
            ids = tuple(sorted(
                (asset_id for family in members for asset_id in families[family]),
                key=order.__getitem__,
            ))
            foot = feet[members[0]]
            for family in members[1:]:
                foot = _union(foot, feet[family])
            clusters.append(_Cluster(key=key, item_ids=ids, foot=foot, reading=_center(foot)))
        return clusters

    def _foot(self, item: LayoutItem, asset: VisualAsset | None) -> Rect:
        box = self.footprints.resolve(item, asset).box
        return (
            box[0] * REFERENCE_WIDTH, box[1] * REFERENCE_HEIGHT,
            box[2] * REFERENCE_WIDTH, box[3] * REFERENCE_HEIGHT,
        )

    # -- authored topology ---------------------------------------------------------------
    @staticmethod
    def _edges(
        clusters: list[_Cluster], directives: list[ChoreographyDirective],
    ) -> set[tuple[int, int]]:
        """Directed cluster edges from relations Choreography already resolved."""
        index = {asset_id: n for n, cluster in enumerate(clusters) for asset_id in cluster.item_ids}
        pairs: list[tuple[str | None, str | None]] = []
        for directive in directives:
            pairs.extend((row.source_asset_id, row.target_asset_id) for row in directive.relation_flows)
            rows = directive.interactions or (
                (directive.interaction,) if directive.interaction is not None else ()
            )
            for row in rows:
                pairs.append((row.subject_asset_id, row.object_asset_id))
                pairs.append((row.object_asset_id or row.subject_asset_id, row.result_asset_id))
        edges = set()
        for source, target in pairs:
            if source in index and target in index and index[source] != index[target]:
                edges.add((index[source], index[target]))
        return edges

    @staticmethod
    def _order(clusters: list[_Cluster], edges: set[tuple[int, int]]) -> list[int]:
        """Topological order (sources first, results last); authored reading order breaks ties."""
        xs = [cluster.reading[0] for cluster in clusters]
        ys = [cluster.reading[1] for cluster in clusters]
        horizontal = (max(xs) - min(xs)) >= (max(ys) - min(ys))

        def reading(n: int) -> tuple[float, float, str]:
            x, y = clusters[n].reading
            return (x, y, clusters[n].key) if horizontal else (y, x, clusters[n].key)

        remaining = set(range(len(clusters)))
        incoming = {n: {s for s, t in edges if t == n} for n in remaining}
        order: list[int] = []
        while remaining:
            ready = [n for n in remaining if not (incoming[n] & remaining)]
            # A relation cycle cannot be ordered topologically: fall back to reading order.
            pick = min(ready or remaining, key=reading)
            order.append(pick)
            remaining.discard(pick)
        return order

    # -- arrangement ---------------------------------------------------------------------
    def _arrange(
        self, clusters: list[_Cluster], order: list[int], edges: set[tuple[int, int]],
    ) -> _Arrangement:
        width = self.art_region.width * self.frame[0]
        height = self.art_region.height * self.frame[1]
        best: _Arrangement | None = None
        for rows in _partitions(order):
            scale = self._scale(clusters, rows, edges, width, height)
            if scale <= 0.0:
                continue
            candidate = _Arrangement(rows=rows, scale=scale)
            if best is None or _better(candidate, best):
                best = candidate
        if best is None:  # nothing fits even at the gaps alone: stack and shrink
            rows = tuple((n,) for n in order)
            best = _Arrangement(rows=rows, scale=max(1e-3, self._scale(clusters, rows, edges, width, height)))
        return best

    def _scale(
        self,
        clusters: list[_Cluster],
        rows: tuple[tuple[int, ...], ...],
        edges: set[tuple[int, int]],
        width: float,
        height: float,
    ) -> float:
        limit = self.max_scale
        row_heights = 0.0
        for row in rows:
            span = sum(_w(clusters[n].foot) for n in row)
            gaps = sum(self._gap_between(a, b, edges) for a, b in zip(row, row[1:]))
            if gaps >= width:
                return 0.0
            limit = min(limit, (width - gaps) / max(1e-6, span))
            row_heights += max(_h(clusters[n].foot) for n in row)
        vertical_gaps = sum(
            self._row_gap(upper, lower, edges) for upper, lower in zip(rows, rows[1:])
        )
        if vertical_gaps >= height:
            return 0.0
        return min(limit, (height - vertical_gaps) / max(1e-6, row_heights))

    def _gap_between(self, a: int, b: int, edges: set[tuple[int, int]]) -> float:
        related = (a, b) in edges or (b, a) in edges
        return self.related_gap_px if related else self.gap_px

    def _row_gap(
        self, upper: tuple[int, ...], lower: tuple[int, ...], edges: set[tuple[int, int]],
    ) -> float:
        related = any((a, b) in edges or (b, a) in edges for a in upper for b in lower)
        return self.related_gap_px if related else self.gap_px

    # -- placement -----------------------------------------------------------------------
    def _place(
        self,
        items: list[LayoutItem],
        clusters: list[_Cluster],
        arrangement: _Arrangement,
        edges: set[tuple[int, int]],
    ) -> list[LayoutItem]:
        fw, fh = self.frame
        s = arrangement.scale
        region = self.art_region
        rows = arrangement.rows
        row_heights = [max(_h(clusters[n].foot) for n in row) * s for row in rows]
        total = sum(row_heights) + sum(
            self._row_gap(upper, lower, edges) for upper, lower in zip(rows, rows[1:])
        )
        top = region.top * fh + (region.height * fh - total) / 2.0
        center_x = (region.left + region.width / 2.0) * fw
        origin: dict[int, tuple[float, float]] = {}
        for index, row in enumerate(rows):
            # Inside a row, keep authored left-to-right order of the clusters.
            ordered = sorted(row, key=lambda n: (clusters[n].reading[0], clusters[n].key))
            span = sum(_w(clusters[n].foot) * s for n in ordered) + sum(
                self._gap_between(a, b, edges) for a, b in zip(ordered, ordered[1:])
            )
            x = center_x - span / 2.0
            for position, n in enumerate(ordered):
                if position:
                    x += self._gap_between(ordered[position - 1], n, edges)
                y = top + (row_heights[index] - _h(clusters[n].foot) * s) / 2.0
                origin[n] = (x, y)
                x += _w(clusters[n].foot) * s
            if index + 1 < len(rows):
                top += row_heights[index] + self._row_gap(row, rows[index + 1], edges)
        cluster_of = {asset_id: n for n, cluster in enumerate(clusters) for asset_id in cluster.item_ids}
        output = []
        for item in items:
            n = cluster_of[item.asset_id]
            fx, fy = clusters[n].foot[0], clusters[n].foot[1]
            ox, oy = origin[n]
            cx = ox + (item.x * REFERENCE_WIDTH - fx) * s
            cy = oy + (item.y * REFERENCE_HEIGHT - fy) * s
            output.append(item.model_copy(update={
                "x": cx / fw,
                "y": cy / fh,
                "width": max(1e-6, item.width * REFERENCE_WIDTH * s / fw),
                "height": max(1e-6, item.height * REFERENCE_HEIGHT * s / fh),
                "placement_source": REFLOW_PLACEMENT_SOURCE,
            }))
        return output


def _better(candidate: _Arrangement, best: _Arrangement) -> bool:
    # A materially larger scene wins; within 3% the arrangement with fewer rows keeps the
    # authored side-by-side reading. Remaining ties resolve on the row tuple itself.
    if candidate.scale > best.scale * 1.03:
        return True
    if best.scale > candidate.scale * 1.03:
        return False
    key_c = (len(candidate.rows), -candidate.scale, candidate.rows)
    key_b = (len(best.rows), -best.scale, best.rows)
    return key_c < key_b


def _partitions(order: list[int]):
    """Every split of ``order`` into consecutive rows (bounded: scenes hold few clusters)."""
    count = len(order)
    if count > 10:  # pathological density: one cluster per row, then pairs
        yield tuple((n,) for n in order)
        yield tuple(tuple(order[i:i + 2]) for i in range(0, count, 2))
        return
    for mask in range(1 << max(0, count - 1)):
        rows, current = [], [order[0]]
        for index in range(1, count):
            if mask & (1 << (index - 1)):
                rows.append(tuple(current))
                current = []
            current.append(order[index])
        rows.append(tuple(current))
        yield tuple(rows)


def _union(a: Rect, b: Rect) -> Rect:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _gap(a: Rect, b: Rect) -> float:
    return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


def _center(rect: Rect) -> tuple[float, float]:
    return (rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0


def _w(rect: Rect) -> float:
    return max(1e-6, rect[2] - rect[0])


def _h(rect: Rect) -> float:
    return max(1e-6, rect[3] - rect[1])
