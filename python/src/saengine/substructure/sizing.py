"""The sizing assistant: footings proposed for the columns of an analysed model.

For each column (or group of columns) it proposes the smallest footing that passes the checks
of :mod:`saengine.substructure.shallow`:

1. Plan size: a square isolated footing B x B, B grown in steps of :data:`STEP` until the net
   service pressure is within qa. qa depends on B (and on the founding level and the position):
   it is taken from the soil report again for every trial size, as each footing's check does.
2. Thickness h, in steps of :data:`STEP` from :data:`MIN_THICKNESS`, until punching and one-way
   shear pass without shear reinforcement.
3. Bottom bars: the lightest mesh of :data:`BAR_DIAS` at a spacing in steps of 25 mm that carries
   the flexure at the column faces and gives the minimum steel 0.0018 Ag (ACI 7.6.1.1) at a
   spacing of at most min(3h, 450 mm) (ACI 7.7.2.3); top bars where the footing hogs beyond what
   plain concrete carries.
4. Footings that would overlap become one combined footing under their columns: its long axis
   through the two farthest columns, centred on the resultant of the heaviest service gravity
   combination (uniform pressure under it), :data:`OVERHANG` beyond the outer column faces, its
   width grown for bearing like an isolated footing's, with top bars between the columns.

The bearing loop runs again after the thickness is chosen (the footing's weight grows with it).
The proposal is a fragment of ``substructure.json`` (``{"foundations": [...]}``) for the editor
to merge; nothing is written.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from saengine.design.bars import mesh_for, slab_flexure_need
from saengine.library.bim import ColumnElement
from saengine.library.materials import Category
from saengine.library.objects import BarMesh, Column
from saengine.library.substructure import DEFAULT_FOUNDING_DEPTH, Foundation
from saengine.substructure.context import Context, Skip, load_context
from saengine.substructure.shallow import (
    design_footing,
    footing_loads,
    min_steel_ratio,
    place_footing,
)

#: Plan sizes and thicknesses are multiples of this [mm].
STEP = 50.0
#: The thinnest footing proposed [mm] (ACI 318-19 13.3.1.2: d of the bottom bars >= 150 mm).
MIN_THICKNESS = 300.0
MAX_THICKNESS = 2500.0
#: The largest isolated footing proposed before giving up [mm].
MAX_SIZE = 8000.0
#: Concrete cast against and permanently in contact with the ground (ACI 318-19 Table
#: 20.5.1.3.1) [mm].
COVER = 75.0
BAR_DIAS = (12.0, 16.0, 20.0, 25.0)
#: Beyond the outer column faces of a combined footing [mm].
OVERHANG = 300.0

SHEAR_CHECKS = ("Punching at", "One-way shear")
BEARING_CHECKS = (
    "Bearing (service)",
    "Resultant within the base (service)",
    "Base in contact (service, stability)",
    # Reported only in the design, but a proposed footing keeps its whole base in contact under
    # the gravity combinations (no tilting under the sustained load).
    "Full contact under gravity (service)",
)


def _round_up(value: float, step: float = STEP) -> float:
    return math.ceil(value / step - 1e-9) * step


@dataclass
class Trial:
    """A proposed footing being sized."""

    columns: list[str]
    center: np.ndarray
    rotation: float
    length: float
    width: float
    thickness: float
    material: str
    rebar: str
    founding_level: float
    bottom: BarMesh | None = None
    top: BarMesh | None = None
    square: bool = True
    least: float = 1000.0  # the smallest width the plan may shrink to [mm]
    least_length: float | None = None  # and length (default: the starting length)

    def foundation(self, foundation_id: str) -> Foundation:
        kind = "combined" if len(self.columns) > 1 else "isolated"
        reinforcement: dict[str, Any] = {"material": self.rebar, "cover": COVER}
        mesh = self.bottom or BarMesh(dia=16, spacing=150)
        reinforcement.update(bottomX=mesh, bottomY=mesh)
        if self.top is not None:
            reinforcement.update(topX=self.top, topY=self.top)
        return Foundation.model_validate(
            {
                "id": foundation_id,
                "type": kind,
                "columns": self.columns,
                "center": [round(float(self.center[0]), 1), round(float(self.center[1]), 1)],
                "rotation": round(self.rotation, 3),
                "length": self.length,
                "width": self.width,
                "thickness": self.thickness,
                "foundingLevel": self.founding_level,
                "material": self.material,
                "reinforcement": reinforcement,
            }
        )

    def corners(self) -> np.ndarray:
        theta = math.radians(self.rotation)
        u = np.array([math.cos(theta), math.sin(theta)])
        v = np.array([-math.sin(theta), math.cos(theta)])
        return np.array(
            [
                self.center + su * self.length / 2 * u + sv * self.width / 2 * v
                for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))
            ]
        )


def penetration(ca: np.ndarray, cb: np.ndarray) -> float:
    """How far two rectangles (their 4 corners in order) overlap in plan [their unit]: the least
    overlap of their projections on the axes of their sides (separating axis test); 0 when they
    are apart or only touch."""
    depth = math.inf
    for corners in (ca, cb):
        for k in range(2):
            edge = corners[k + 1] - corners[k]
            axis = np.array([-edge[1], edge[0]]) / float(np.linalg.norm(edge))
            pa, pb = ca @ axis, cb @ axis
            depth = min(depth, float(min(pa.max() - pb.min(), pb.max() - pa.min())))
            if depth <= 1e-6:
                return 0.0
    return depth


def overlap(a: Trial, b: Trial) -> bool:
    """Whether two footings overlap in plan (touching is no overlap)."""
    return penetration(a.corners(), b.corners()) > 0


class Sizer:
    """Sizes footings in a :class:`~saengine.substructure.context.Context`."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.loads = ctx.require_loads()
        self.founding = ctx.ground_level - DEFAULT_FOUNDING_DEPTH
        self.notes: list[str] = []

    def evaluate(
        self, trial: Trial, service: bool = True, strength: bool = True
    ) -> dict[str, dict[str, Any]]:
        """The checks of a trial by name."""
        ctx = self.ctx
        foundation = trial.foundation("PROPOSAL")
        placed = place_footing(ctx, foundation)
        service_loads, strength_loads = footing_loads(self.loads, placed)
        spec = placed.spec
        bearing = ctx.soil.at(
            float(placed.center[0]),
            float(placed.center[1]),
            placed.founding_level,
            min(spec.width, spec.length),
            max(spec.width, spec.length),
        )
        if service and bearing.qa is None:
            raise Skip(
                "no allowable bearing pressure: "
                + (
                    bearing.note
                    or "enter qa in 1 Soil Report (boreholes) or as the override in Project "
                    "Settings → Foundation"
                )
            )
        checks, _ = design_footing(
            spec,
            service_loads if service else {},
            strength_loads if strength else {},
            ctx.settings.foundation,
            self.loads.dead,
            bearing,
        )
        return {c["name"]: c for c in checks}

    def _bearing_fails(self, trial: Trial) -> list[dict[str, Any]]:
        checks = self.evaluate(trial, strength=False)
        return [checks[n] for n in BEARING_CHECKS if n in checks and not checks[n]["ok"]]

    def size_bearing(self, trial: Trial) -> None:
        """The smallest plan in steps of :data:`STEP` whose service pressure is within qa: B x B
        for one column; a combined footing grows its width up to its length, then both (its
        length about the resultant, where it is centred). Grown in proportion to the overload,
        then shrunk back while a step smaller still passes (not below the starting size)."""
        least = (trial.least, trial.least_length or trial.length)

        def resized(width: float, length: float) -> Trial:
            return replace(trial, width=width, length=width if trial.square else length)

        while True:
            failing = self._bearing_fails(trial)
            if not failing:
                for dimension in ("width", "length"):
                    while True:
                        width = trial.width - STEP * (dimension == "width")
                        length = trial.length - STEP * (dimension == "length")
                        if (
                            width < least[0]
                            or length < least[1]
                            or (trial.square and dimension == "length")
                        ):
                            break
                        smaller = resized(width, length)
                        if self._bearing_fails(smaller):
                            break
                        trial.width, trial.length = smaller.width, smaller.length
                return
            if max(trial.length, trial.width) >= MAX_SIZE:
                raise Skip(f"no footing up to {MAX_SIZE / 1e3:g} m carries the bearing")
            # Grow in proportion to the overload (at least one step).
            ratio = math.sqrt(min(max(c["utilisation"] for c in failing), 4.0))
            if trial.square:
                grow = max(STEP, _round_up(trial.width * (ratio - 1)))
                trial.width = trial.length = min(trial.width + grow, MAX_SIZE)
            elif trial.width < trial.length:
                grow = max(STEP, _round_up(trial.width * (ratio - 1)))
                trial.width = min(trial.width + grow, trial.length)
            else:
                grow = max(STEP, _round_up(trial.length * (ratio - 1)))
                trial.length = min(trial.length + grow, MAX_SIZE)
                trial.width = min(trial.width + grow, MAX_SIZE)

    def choose_mesh(self, trial: Trial, demand: float, axis_d: float, top: bool) -> BarMesh:
        """The lightest mesh carrying ``demand`` [N·mm per metre] at depth ``axis_d`` with the
        minimum steel and the largest spacing of ACI 7.7.2.3: the bars of
        :func:`saengine.design.bars.slab_flexure_need` in :func:`saengine.design.bars.mesh_for`
        (as Design Reinforcement chooses them); too thin a footing is skipped."""
        h = trial.thickness
        concrete = self.ctx.mats[trial.material].concrete
        rebar = self.ctx.mats[trial.rebar].steel
        if concrete is None or rebar is None:
            raise Skip("the footing's concrete or bars have no strength")
        fc, fy = concrete.fc, rebar.fy
        flexure = slab_flexure_need(demand, axis_d, fc, fy)
        if flexure.too_small:
            raise Skip("the footing is too thin for the flexure")
        need = flexure.area
        if not top:
            need = max(need, min_steel_ratio(fy) * h * 1000)
        # A little over: d of the layers differ.
        best = mesh_for(need * 1.02, min(3 * h, 450.0), BAR_DIAS)
        if best is None:
            raise Skip("no mesh of the bar sizes carries the flexure")
        return BarMesh(dia=best.dia, spacing=best.spacing)

    def size_section(self, trial: Trial) -> dict[str, dict[str, Any]]:
        """Thickness and meshes: thicken until punching and one-way shear pass without shear
        reinforcement, then the lightest bars for that thickness (thicker again when those
        bars lower the shear strength too much or no mesh carries the flexure); the final
        checks."""
        trial.thickness = max(trial.thickness, MIN_THICKNESS)
        trial.bottom = trial.bottom or BarMesh(dia=16, spacing=150)
        while True:
            if trial.thickness > MAX_THICKNESS:
                raise Skip(f"no thickness up to {MAX_THICKNESS / 1e3:g} m passes shear")
            checks = self.evaluate(trial, service=False)
            if not all(c["ok"] for n, c in checks.items() if n.startswith(SHEAR_CHECKS)):
                trial.thickness += STEP
                continue
            try:
                checks = self.choose_meshes(trial, checks)
            except Skip:
                trial.thickness += STEP
                continue
            if all(
                c["ok"]
                for n, c in checks.items()
                if n.startswith((*SHEAR_CHECKS, "Flexure", "Min."))
            ):
                return checks
            trial.thickness += STEP

    def choose_meshes(
        self, trial: Trial, checks: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """The bottom (and, where it hogs, top) meshes for the flexure of ``checks``, until
        they settle; the checks with them."""
        for _ in range(4):
            changed = False
            d = trial.thickness - COVER - 1.5 * (trial.bottom.dia if trial.bottom else 16)
            bottom = max(
                (
                    c["demand"]
                    for n, c in checks.items()
                    if n.startswith("Flexure") and n.endswith("(bottom)")
                ),
                default=0.0,
            )
            mesh = self.choose_mesh(trial, bottom * 1e6, d, top=False)
            if mesh != trial.bottom:
                trial.bottom, changed = mesh, True
            tops = [c for n, c in checks.items() if n.startswith("Flexure") and n.endswith("(top)")]
            if tops and (
                len(trial.columns) > 1 or trial.top is not None or any(not c["ok"] for c in tops)
            ):
                worst = max(c["demand"] for c in tops)
                d_top = trial.thickness - COVER - 1.5 * (trial.top.dia if trial.top else 16)
                mesh = self.choose_mesh(trial, worst * 1e6, d_top, top=True)
                if mesh != trial.top:
                    trial.top, changed = mesh, True
            if not changed:
                return checks
            checks = self.evaluate(trial, service=False)
        return checks

    def size(self, trial: Trial) -> dict[str, dict[str, Any]]:
        """Plan size, thickness and bars of a trial; its final checks."""
        for _ in range(6):
            self.size_bearing(trial)
            before = (trial.length, trial.width)
            self.size_section(trial)
            self.size_bearing(trial)  # the weight grew with the thickness
            if (trial.length, trial.width) == before:
                break
        return self.evaluate(trial)

    # ── trials ──

    def materials_of(self, column: ColumnElement) -> tuple[str, str]:
        """Concrete and bar material ids for a column's footing: the column's own, else the
        project's (``defaults`` of the materials, else the first of the library's)."""
        mats = self.ctx.mats
        column_type = self.ctx.types.get(column.type)
        concrete = getattr(column_type, "material", None)
        if concrete not in mats or mats[concrete].category != Category.CONCRETE:
            concrete = self.ctx.materials.default_concrete()
        reinforcement = getattr(column_type, "reinforcement", None)
        rebar = reinforcement.material if reinforcement is not None else None
        if rebar not in mats or mats[rebar].steel is None:
            rebar = self.ctx.materials.default_rebar()
        if concrete is None or rebar is None:
            raise Skip("the material library has no concrete or no reinforcing bars")
        return concrete, rebar

    def side(self, column: ColumnElement) -> float:
        column_type = self.ctx.types.get(column.type)
        profile = column_type.profile if isinstance(column_type, Column) else None
        if profile is None:
            return 0.0
        if hasattr(profile, "radius"):
            return 2 * profile.radius
        return max(getattr(profile, "xDim", 0.0), getattr(profile, "yDim", 0.0))

    def isolated(self, column: ColumnElement) -> Trial:
        concrete, rebar = self.materials_of(column)
        least = _round_up(max(self.side(column) + 2 * OVERHANG, 1000.0))
        start = least
        p = self.loads.max_axial(column.id, "service")
        qa = self.ctx.soil.at(
            column.position[0], column.position[1], self.founding, 2000.0, 2000.0
        ).qa
        if qa:
            start = max(start, _round_up(math.sqrt(p / (qa * 1e-3)) * 0.9))
        return Trial(
            [column.id],
            np.array(column.position[:2], dtype=float),
            0.0,
            start,
            start,
            MIN_THICKNESS,
            concrete,
            rebar,
            self.founding,
            least=least,
        )

    def combined(self, columns: list[ColumnElement]) -> Trial:
        concrete, rebar = self.materials_of(columns[0])
        points = np.array([c.position[:2] for c in columns], dtype=float)
        pairs = [(i, j) for i in range(len(points)) for j in range(i + 1, len(points))]
        i, j = max(pairs, key=lambda ij: float(np.linalg.norm(points[ij[1]] - points[ij[0]])))
        axis = points[j] - points[i]
        theta = math.degrees(math.atan2(axis[1], axis[0]))
        if theta > 90:
            theta -= 180
        elif theta <= -90:
            theta += 180
        u = np.array([math.cos(math.radians(theta)), math.sin(math.radians(theta))])
        v = np.array([-u[1], u[0]])
        # The resultant of the heaviest service gravity combination.
        _, factors = max(
            (c for c in self.loads.service if not any(k[:1] in "WE" for k in c[1])),
            key=lambda c: sum(self._axial(col.id, c[1]) for col in columns),
            default=self.loads.service[0],
        )
        weights = np.array([max(self._axial(c.id, factors), 1.0) for c in columns])
        resultant = (points * weights[:, None]).sum(axis=0) / weights.sum()
        s = (points - resultant) @ u
        t = (points - resultant) @ v
        sides = [self.side(c) for c in columns]
        half_l = max(abs(si) + c / 2 for si, c in zip(s, sides, strict=True)) + OVERHANG
        half_w = max(abs(ti) + c / 2 for ti, c in zip(t, sides, strict=True)) + OVERHANG
        return Trial(
            [c.id for c in columns],
            resultant,
            theta,
            _round_up(2 * half_l),
            _round_up(max(2 * half_w, 1000.0)),
            MIN_THICKNESS,
            concrete,
            rebar,
            self.founding,
            square=False,
            least=_round_up(max(2 * half_w, 1000.0)),
        )

    def _axial(self, column_id: str, factors: dict[str, float]) -> float:
        base = self.loads.bases[column_id]
        return float(-self.loads.resultant(column_id, factors, base.nodes[0][1])[2])


def propose(ctx: Context, columns: list[str] | None = None) -> dict[str, Any]:
    """Footings proposed for ``columns`` (default: every column base of the analysis model that
    no foundation of the substructure carries yet): ``{"foundations": [...], "designs":
    [{"id", "columns", "utilisation", "ok", "governing"}], "notes": [...]}``, the foundations
    ready for ``substructure.json``."""
    sizer = Sizer(ctx)
    loads = sizer.loads
    carried = {c for f in ctx.substructure.foundations for c in f.columns}
    # A column on a pile cap keeps it: its piles are laid out with the pile tools and checked
    # from the soil's pile capacity, not replaced by a footing.
    on_caps = {
        c: f.id for f in ctx.substructure.foundations if f.type == "pileCap" for c in f.columns
    }
    wanted = columns or [
        b for b, base in loads.bases.items() if isinstance(base.element, ColumnElement)
    ]
    chosen: list[ColumnElement] = []
    for column_id in wanted:
        base = loads.bases.get(column_id)
        if base is None or not isinstance(base.element, ColumnElement):
            sizer.notes.append(f"{column_id}: not a column base of the analysis model; left out")
        elif column_id in carried and columns is None:
            continue
        elif column_id in on_caps:
            sizer.notes.append(
                f"{column_id}: stands on pile cap {on_caps[column_id]}; Size Footings sizes "
                "footings only (lay its piles out again with the pile tools)"
            )
        else:
            chosen.append(base.element)

    trials: list[Trial] = []
    for column in chosen:
        try:
            trial = sizer.isolated(column)
            sizer.size(trial)
        except Skip as reason:
            sizer.notes.append(f"{column.id}: no footing proposed: {reason}")
            continue
        trials.append(trial)

    # Merge overlapping footings into combined ones until none overlap.
    by_id = {c.id: c for c in chosen}
    for _ in range(len(trials)):
        pair = next(
            ((a, b) for k, a in enumerate(trials) for b in trials[k + 1 :] if overlap(a, b)),
            None,
        )
        if pair is None:
            break
        a, b = pair
        group = [by_id[c] for c in a.columns + b.columns]
        try:
            merged = sizer.combined(group)
            sizer.size(merged)
        except Skip as reason:
            sizer.notes.append(
                f"{', '.join(c.id for c in group)}: their footings overlap and no combined "
                f"footing could be proposed: {reason}"
            )
            break
        sizer.notes.append(
            f"{', '.join(merged.columns)}: their footings would overlap: one combined footing, "
            "centred on the resultant of the heaviest service gravity combination"
        )
        trials = [t for t in trials if t is not a and t is not b] + [merged]

    taken = {f.id for f in ctx.substructure.foundations}
    number = 0
    foundations: list[dict[str, Any]] = []
    designs: list[dict[str, Any]] = []
    for trial in trials:
        number += 1
        while f"F{number}" in taken:
            number += 1
        foundation_id = f"F{number}"
        foundation = trial.foundation(foundation_id)
        checks = sizer.evaluate(trial)
        counted = [c for c in checks.values() if not c["flag"]]
        governing = max(counted, key=lambda c: c["utilisation"], default=None)
        data = foundation.model_dump(mode="json", by_alias=True, exclude_none=True)
        data["note"] = (
            f"Proposed by the sizing assistant for {', '.join(trial.columns)}"
            + (f"; governed by {governing['name']}" if governing else "")
            + "."
        )
        foundations.append(data)
        designs.append(
            {
                "id": foundation_id,
                "columns": trial.columns,
                "utilisation": governing["utilisation"] if governing else 0.0,
                "ok": all(c["ok"] for c in counted),
                "governing": governing["name"] if governing else None,
            }
        )
    return {"foundations": foundations, "designs": designs, "notes": sizer.notes}


def propose_footings(
    project_root: str | Path,
    out_dir: str | Path | None = None,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """:func:`propose` for the project at ``project_root`` (results in ``out_dir``, default
    ``08 FEM/model.results``). Raises ``ValueError`` when there are no analysis results."""
    ctx = load_context(project_root, out_dir)
    try:
        return propose(ctx, columns)
    except Skip as reason:
        raise ValueError(str(reason)) from reason
