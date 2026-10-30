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
A footing thicker than its founding depth is lowered so its top stays at the finished ground.
Merging repeats until no two proposed footings overlap; one that would overlap a foundation that
is kept is reported.

5. A raft instead: when the footings would cover more than :data:`RAFT_RATIO` of the plan of the
   columns they carry, or overlapping footings cannot be combined, and every column base is
   being sized (at least :data:`RAFT_MIN_COLUMNS`, not in one line), one raft under all of
   them is proposed (:func:`raft_proposal`): the columns'
   outline :data:`RAFT_OVERHANG` beyond the outer column lines, the thickness for punching at
   the heaviest column without shear reinforcement and the minimum mesh both faces. The raft
   check (:mod:`saengine.substructure.raft`) then gives its flexure, settlement and pressure.
   When only some columns are sized, the proposal stays footings and a note suggests the raft.

The proposal is a fragment of ``substructure.json`` (``{"foundations": [...]}``) for the editor
to merge; nothing is written.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.bars import mesh_for, slab_flexure_need
from saengine.library.bim import ColumnElement
from saengine.library.materials import Category
from saengine.library.objects import BarMesh, Column
from saengine.library.substructure import DEFAULT_FOUNDING_DEPTH, Foundation
from saengine.substructure.context import Context, Skip, load_context
from saengine.substructure.shallow import (
    LATERAL,
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
#: A raft is proposed for at least this many columns spread over an area (not in one line).
RAFT_MIN_COLUMNS = 4
#: The largest isolated footing proposed before giving up [mm].
MAX_SIZE = 8000.0
#: Concrete cast against and permanently in contact with the ground (ACI 318-19 Table
#: 20.5.1.3.1) [mm].
COVER = 75.0
BAR_DIAS = (12.0, 16.0, 20.0, 25.0)
#: Beyond the outer column faces of a combined footing [mm].
OVERHANG = 300.0
#: Footings covering more than this share of the plan of their columns are replaced by a raft:
#: the usual rule of practice (a mat when spread footings would cover more than about half the
#: building area; e.g. Bowles, Foundation Analysis and Design, 5th ed., section 10-1). Not a
#: BNBC value.
RAFT_RATIO = 0.5
#: A proposed raft's edge beyond the outer column centre lines [mm].
RAFT_OVERHANG = 1000.0
#: The thinnest raft proposed [mm].
RAFT_MIN_THICKNESS = 500.0
#: phi of shear (ACI 318-19 Table 21.2.1) and the punching stress factor of 22.6.5.2(a).
PHI_V = 0.75
PUNCHING = 0.33

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
        """Plan size, thickness and bars of a trial; its final checks under every combination.

        Sized under the combinations that govern it (:meth:`governing`), then checked under all
        of them; a combination that makes a check fail there is added and the trial sized again
        (N-U4: each trial size was checked under some 300 combinations; 20 columns took 19 min).
        """
        full = self.loads
        service, strength = self.governing(trial)
        try:
            for _ in range(4):
                self.loads = replace(full, service=service, strength=strength)
                self._size(trial)
                self.loads = full
                checks = self.evaluate(trial)
                used = {n for n, _ in service} | {n for n, _ in strength}
                missed = {
                    c["combination"]
                    for c in checks.values()
                    if not c["ok"] and not c["flag"] and c["combination"] not in used
                }
                if not missed:
                    return checks
                service = [c for c in full.service if c[0] in used or c[0] in missed]
                strength = [c for c in full.strength if c[0] in used or c[0] in missed]
            return self.evaluate(trial)
        finally:
            self.loads = full

    def governing(
        self, trial: Trial
    ) -> tuple[list[tuple[str, dict[str, float]]], list[tuple[str, dict[str, float]]]]:
        """The service and strength combinations a footing under ``trial``'s columns is sized
        for: by their resultant at the columns' centroid (P down, M about X and Y), those with
        the largest P, the least P (uplift), the largest |M| each way and the largest corner
        pressure P/B² + 6 (|Mx| + |My|)/B³ of square footings B = 1 to 6 m; and every service
        combination without wind or earthquake (the full-contact check under gravity)."""
        loads = self.loads
        about = np.array([*np.mean([b.nodes[0][1][:2] for b in self.bases(trial)], axis=0), 0.0])

        def pick(combinations: list[tuple[str, dict[str, float]]]) -> set[str]:
            if not combinations:
                return set()
            rows = np.array(
                [
                    sum(loads.resultant(c, factors, about) for c in trial.columns)
                    for _, factors in combinations
                ]
            )
            p, mx, my = -rows[:, 2], np.abs(rows[:, 3]), np.abs(rows[:, 4])
            names = [n for n, _ in combinations]
            keep = {names[int(np.argmax(p))], names[int(np.argmin(p))]}
            keep |= {names[int(np.argmax(mx))], names[int(np.argmax(my))]}
            for b in (1000.0, 2000.0, 3000.0, 4000.0, 6000.0):
                keep.add(names[int(np.argmax(p / b**2 + 6 * (mx + my) / b**3))])
            return keep

        service = pick(loads.service) | {n for n, _ in loads.service if not LATERAL.search(n)}
        strength = pick(loads.strength)
        return (
            [c for c in loads.service if c[0] in service],
            [c for c in loads.strength if c[0] in strength],
        )

    def bases(self, trial: Trial) -> list[Any]:
        return [self.loads.bases[c] for c in trial.columns]

    def _size(self, trial: Trial) -> None:
        """Plan size, thickness and bars of a trial under :attr:`loads`."""
        for _ in range(6):
            self.size_bearing(trial)
            before = (trial.length, trial.width, trial.founding_level)
            self.size_section(trial)
            self.keep_below_ground(trial)
            self.size_bearing(trial)  # the weight grew with the thickness
            if (trial.length, trial.width, trial.founding_level) == before:
                break

    def keep_below_ground(self, trial: Trial) -> None:
        """Lowers a footing thicker than its founding depth until its top is at the finished
        ground (a footing standing out of the ground is not what was meant), in steps of
        :data:`STEP`."""
        if trial.founding_level + trial.thickness > self.ctx.ground_level:
            lowered = math.floor((self.ctx.ground_level - trial.thickness) / STEP) * STEP
            self.notes.append(
                f"{', '.join(trial.columns)}: the footing is {trial.thickness:.0f} mm thick, more "
                f"than its founding depth: founded {trial.founding_level - lowered:.0f} mm "
                "deeper so its top stays at the finished ground"
            )
            trial.founding_level = lowered

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

    # Merge overlapping footings into combined ones until none overlap (each merge leaves one
    # footing fewer, so this ends).
    by_id = {c.id: c for c in chosen}
    unresolved = False
    while True:
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
            unresolved = True
            break
        sizer.notes.append(
            f"{', '.join(merged.columns)}: their footings would overlap: one combined footing, "
            "centred on the resultant of the heaviest service gravity combination"
        )
        trials = [t for t in trials if t is not a and t is not b] + [merged]

    # Footings that would overlap a foundation that stays (not being sized again).
    sized = {c for t in trials for c in t.columns}
    kept = [f for f in ctx.substructure.foundations if not sized & set(f.columns)]
    for trial in trials:
        for other in kept:
            corners = foundation_corners(other)
            if corners is not None and penetration(trial.corners(), corners) > 0.5:
                sizer.notes.append(
                    f"{', '.join(trial.columns)}: the footing would overlap {other.id}, which is "
                    f"not being sized: select {other.id}'s columns too and Size Footings again"
                )
                unresolved = True

    # A raft when the footings would cover most of the plan, or cannot be kept apart.
    bases = [b for b in loads.bases.values() if isinstance(b.element, ColumnElement)]
    every = len(chosen) == len(bases) and not on_caps
    plan = column_plan(chosen)
    covered = sum(t.length * t.width for t in trials)
    ratio = covered / plan if plan > 0 else 0.0
    spread = len(chosen) >= RAFT_MIN_COLUMNS and column_hull_area(chosen) > 0
    if trials and spread and (ratio > RAFT_RATIO or unresolved):
        why = (
            f"the footings would cover {ratio:.0%} of the plan of their columns (more than "
            f"{RAFT_RATIO:.0%})"
            if ratio > RAFT_RATIO
            else "overlapping footings could not be kept apart"
        )
        if every:
            try:
                raft, raft_notes = raft_proposal(sizer, chosen)
            except Skip as reason:
                sizer.notes.append(f"A raft would suit ({why}) but none was proposed: {reason}")
            else:
                return {
                    "foundations": [raft],
                    "designs": [
                        {
                            "id": raft["id"],
                            "columns": raft["columns"],
                            "utilisation": None,
                            "ok": None,
                            "governing": None,
                        }
                    ],
                    "notes": [
                        (
                            f"One raft proposed instead of {len(trials)} footings: {why}. Its "
                            "flexure, contact pressure and settlement are checked once it is applied."
                        ),
                        *raft_notes,
                        *sizer.notes,
                    ],
                    "raft": {"areaRatio": round(ratio, 3), "footings": len(trials)},
                }
        else:
            sizer.notes.append(
                f"Consider a raft: {why}. Size all the columns (select none) to have one "
                "proposed, or use Add Raft"
            )

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


def foundation_corners(foundation: Foundation) -> np.ndarray | None:
    """The plan corners [mm] of a footing or pile cap with a centre and a size; a raft's
    outline; else None."""
    if foundation.type == "raft" and foundation.outline:
        return None  # a raft carries its own columns; footings never stand beside one
    if foundation.center is None or not foundation.length or not foundation.width:
        return None
    trial = Trial(
        list(foundation.columns),
        np.array(foundation.center[:2], dtype=float),
        float(foundation.rotation or 0.0),
        float(foundation.length),
        float(foundation.width),
        0.0,
        "",
        "",
        0.0,
    )
    return trial.corners()


def column_hull_area(columns: list[ColumnElement]) -> float:
    """The area [mm²] of the convex hull of the columns' centres (0 when they are in a line)."""
    from shapely.geometry import MultiPoint

    return float(MultiPoint([(c.position[0], c.position[1]) for c in columns]).convex_hull.area)


def column_plan(columns: list[ColumnElement]) -> float:
    """The plan area [mm²] of a group of columns: their convex hull :data:`RAFT_OVERHANG`
    beyond the outer column lines (what a raft under them would cover); 0 for none."""
    outline = raft_outline(columns)
    if not outline:
        return 0.0
    points = np.array(outline)
    x, y = points[:, 0], points[:, 1]
    return float(abs((x * np.roll(y, -1) - np.roll(x, -1) * y).sum()) / 2)


def raft_outline(columns: list[ColumnElement]) -> list[list[float]]:
    """A raft's outline under ``columns``: the convex hull of their centres grown by
    :data:`RAFT_OVERHANG` with mitred corners, rounded to :data:`STEP` (counter-clockwise)."""
    from shapely.geometry import MultiPoint

    if not columns:
        return []
    hull = MultiPoint([(c.position[0], c.position[1]) for c in columns]).convex_hull
    grown = hull.buffer(RAFT_OVERHANG, join_style=2, cap_style=3)
    ring = list(grown.exterior.coords)[:-1]
    outline: list[list[float]] = []
    for x, y in ring:
        point = [round(x / STEP) * STEP, round(y / STEP) * STEP]
        if not outline or point != outline[-1]:
            outline.append(point)
    if len(outline) > 1 and outline[0] == outline[-1]:
        outline.pop()
    return outline


def raft_proposal(sizer: Sizer, columns: list[ColumnElement]) -> tuple[dict[str, Any], list[str]]:
    """One raft under ``columns`` (see the module notes), as ``substructure.json``'s raft, and
    notes on how it was sized. The thickness: d for punching at each column as an interior
    column, Vu <= phi 0.33 sqrt(fc) b0 d with b0 = 4 (c + d) (ACI 318-19 22.6.5.2(a), the soil
    reaction inside the section left out: conservative), and d for one-way shear of a metre
    strip between the columns: the net factored soil pressure qu = sum of the columns' largest
    factored loads / the raft's area over (L/2 - c/2 - d), L the largest distance of a column to
    its nearest one, against phi Vc of ACI 318-19 Table 22.5.5.1(c) with the minimum mesh;
    h = d + cover + 1.5 bar, in steps of :data:`STEP`, at least :data:`RAFT_MIN_THICKNESS`."""
    from saengine.substructure.run import minimum_mesh
    from saengine.substructure.shallow import one_way_shear_capacity

    ctx = sizer.ctx
    concrete, rebar = sizer.materials_of(columns[0])
    fc = ctx.mats[concrete].concrete.fc if ctx.mats[concrete].concrete else None
    fy = ctx.mats[rebar].steel.fy if ctx.mats[rebar].steel else None
    if not fc or not fy:
        raise Skip("the concrete or bars have no strength")
    stress = PHI_V * PUNCHING * math.sqrt(fc)  # N/mm²
    d = 0.0
    heaviest = ""
    for column in columns:
        vu = sizer.loads.max_axial(column.id, "strength")
        c = max(sizer.side(column), 200.0)
        # 4 stress (c + d) d = Vu
        need = (-c + math.sqrt(c * c + vu / stress)) / 2
        if need > d:
            d, heaviest = need, column.id
    dia = 20.0
    outline = raft_outline(columns)
    area = column_plan(columns)
    qu = sum(sizer.loads.max_axial(c.id, "strength") for c in columns) / area if area else 0.0
    points = np.array([c.position[:2] for c in columns], dtype=float)
    span = max(
        (
            float(np.min(np.delete(np.linalg.norm(points - p, axis=1), k)))
            for k, p in enumerate(points)
        ),
        default=0.0,
    )
    side = max((max(sizer.side(c), 200.0) for c in columns), default=200.0)
    governs = "punching at " + heaviest
    while True:
        h = max(RAFT_MIN_THICKNESS, _round_up(d + COVER + 1.5 * dia))
        mesh = minimum_mesh(h, fy)
        rho = math.pi * mesh["dia"] ** 2 / 4 * 1000 / mesh["spacing"] / (1000 * d) if d else 0.0
        demand = qu * 1000 * max(span / 2 - side / 2 - d, 0.0)
        if d <= 0 or one_way_shear_capacity(1000.0, d, rho, fc) >= demand:
            break
        d += 25.0
        governs = f"one-way shear between the columns ({span / 1e3:.1f} m apart)"
    thickness = h
    taken = {f.id for f in ctx.substructure.foundations}
    number = 1
    while f"R{number}" in taken:
        number += 1
    founding = ctx.ground_level - max(DEFAULT_FOUNDING_DEPTH, thickness)
    raft = {
        "id": f"R{number}",
        "type": "raft",
        "columns": [c.id for c in columns],
        "outline": outline,
        "thickness": thickness,
        "foundingLevel": founding,
        "material": concrete,
        "reinforcement": {
            "material": rebar,
            "cover": COVER,
            **{layer: dict(mesh) for layer in ("bottomX", "bottomY", "topX", "topY")},
        },
        "note": (
            f"Proposed by the sizing assistant for {len(columns)} columns; thickness for {governs}."
        ),
    }
    Foundation.model_validate(raft)
    notes = [
        (
            f"Raft thickness {thickness:.0f} mm for {governs} without shear reinforcement "
            f"(ACI 318-19 22.6.5.2(a), 22.5.5.1; d = {d:.0f} mm), minimum mesh "
            f"{mesh['dia']:g}@{mesh['spacing']:g} both ways top and bottom (ACI 318-19 7.6.1.1); "
            "the raft check gives the bars its flexure needs"
        )
    ]
    return raft, notes


def propose_footings(
    project_root: str | Path,
    out_dir: str | Path | None = None,
    columns: list[str] | None = None,
) -> dict[str, Any]:
    """:func:`propose` for the project at ``project_root`` (results in ``out_dir``, default
    ``08 FEM/model.results``). Raises ``ValueError`` when there are no analysis results. Runs
    under the project's code pack."""
    ctx = load_context(project_root, out_dir)
    with (
        code_context.project(ctx.root or project_root),
        code_context.using(code_context.pack_for(ctx.settings, ctx.root)),
    ):
        try:
            return propose(ctx, columns)
        except Skip as reason:
            raise ValueError(str(reason)) from reason
