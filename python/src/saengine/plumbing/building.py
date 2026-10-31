"""What the plumbing sizing reads of the building model (``06 BIM``): stories, slabs, footprint.

The building model is optional: without it the sizing works on the stories' order as
``07 MEP`` lists them (no elevations, no slabs: no catchments from the roof, no sleeves, no
separation checks from the building).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

#: A slab belongs to a story when its top is within this of the story's level [mm] (sunken
#: toilet slabs).
SLAB_TOLERANCE = 300.0


@dataclass
class Building:
    """Stories (id -> level, mm) and slabs (id -> outline, level) of the building model."""

    stories: dict[str, float] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    slabs: dict[str, tuple[Polygon, float]] = field(default_factory=dict)
    holes: list[tuple[str, Polygon]] = field(default_factory=list)  # (slab id, opening)
    ground: float = 0.0
    #: The building model itself (beams and slab panels for placing an overhead tank).
    model: Any = None

    @classmethod
    def of(cls, model: Any, ground: float | None = None) -> Building:
        """From a :class:`saengine.library.bim.BuildingModel` (or None: an empty building)."""
        if model is None:
            return cls()
        stories = {s.id: float(s.elevation) for s in model.stories}
        names = {s.id: s.name for s in model.stories}
        slabs = {}
        for e in model.elements:
            if e.kind == "slab":
                polygon = Polygon([(p[0], p[1]) for p in e.boundary]).buffer(0)
                if not polygon.is_empty:
                    slabs[e.id] = (polygon, float(e.elevation))
        holes = []
        for o in model.additions.slabOpenings:
            half_x, half_y = o.xDim / 2, o.yDim / 2
            rect = Polygon(
                [
                    (o.x - half_x, o.y - half_y),
                    (o.x + half_x, o.y - half_y),
                    (o.x + half_x, o.y + half_y),
                    (o.x - half_x, o.y + half_y),
                ]
            )
            if o.rotation:
                from shapely import affinity

                rect = affinity.rotate(rect, o.rotation, origin=(o.x, o.y))
            holes.append((o.host, rect))
        # The ground is at level 0 unless Project Settings give it (its default is 0 too):
        # not the lowest story, which is a basement's floor in a building with basements.
        return cls(
            stories, names, slabs, holes, 0.0 if ground is None else float(ground), model
        )

    @property
    def known(self) -> bool:
        return bool(self.stories)

    def ordered(self, ids: list[str] | None = None) -> list[str]:
        """Story ids from the lowest up (``ids`` keeps its order when the levels are unknown)."""
        if ids is None:
            ids = list(self.stories)
        if not self.stories:
            return list(ids)
        return sorted((i for i in ids if i in self.stories), key=lambda i: self.stories[i])

    def between(self, bottom: str, top: str) -> list[str]:
        """Stories from ``bottom`` to ``top`` (both included), lowest first."""
        if bottom not in self.stories or top not in self.stories:
            return []
        lo, hi = self.stories[bottom], self.stories[top]
        return [s for s in self.ordered() if lo <= self.stories[s] <= hi]

    def height(self, story: str) -> float:
        """Level of a story above the ground [mm] (0 when unknown)."""
        return self.stories.get(story, self.ground) - self.ground

    def slabs_at(self, story: str) -> list[tuple[str, Polygon]]:
        """The slabs of a story: (id, outline)."""
        level = self.stories.get(story)
        if level is None:
            return []
        return [
            (sid, poly) for sid, (poly, z) in self.slabs.items() if abs(z - level) <= SLAB_TOLERANCE
        ]

    def slab_at(self, story: str, x: float, y: float) -> str | None:
        """The slab of a story under a plan point."""
        point = Point(x, y)
        for sid, poly in self.slabs_at(story):
            if poly.covers(point):
                return sid
        return None

    def in_hole(self, slab: str, x: float, y: float) -> bool:
        """Whether a plan point is in an opening the building model cuts in a slab."""
        point = Point(x, y)
        return any(host == slab and hole.covers(point) for host, hole in self.holes)

    def floor_area(self, story: str) -> float:
        """Plan area of the story's slabs [m²]."""
        polys = [p for _, p in self.slabs_at(story)]
        return unary_union(polys).area / 1e6 if polys else 0.0

    def roof(self, story: str) -> Polygon | None:
        """The union of a story's slabs (a roof surface)."""
        polys = [p for _, p in self.slabs_at(story)]
        return unary_union(polys) if polys else None

    def footprint(self) -> Any:
        """The building's plan footprint: the union of all slabs (None without slabs)."""
        polys = [p for p, _ in self.slabs.values()]
        return unary_union(polys) if polys else None
