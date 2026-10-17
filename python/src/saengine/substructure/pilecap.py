"""Pile groups and pile caps (Part 9, deep foundations).

A pile cap of plan L × B (local u along its length, v along its width, origin at its centre)
and thickness h carries one or more columns (:class:`saengine.substructure.shallow.ColumnBase`, in
the cap's axes) on piles at offsets (u, v) from its centre. The column loads per combination
are :data:`saengine.substructure.shallow.Loads`: ``[P, Cu, Cv]`` per column, the downward force [N]
and the moments [N·mm] about u and v at the cap's underside, the column's action on the cap.

Pile loads (rigid cap): ``Ri = P/n + a ui' + b vi'`` with ui', vi' measured from the piles'
centroid and (a, b) solving ``[Σu'² Σu'v'; Σu'v' Σv'²] [a b] = [Mv Mu]``, Mv and Mu the
resultant's moments about the centroid (for a doubly symmetric group the familiar
``P/n ± Mv u/Σu² ± Mu v/Σv²``). A group whose piles lie in one line (or a single pile) takes
no moment across that line: it is reported and must be restrained by tie beams. The cap's own
weight and the soil above it (``soil_above``) add to P under the service combinations
(times the combination's dead-load factor). The soil under the cap carries nothing (BNBC 2020
Part 6 Sec 3.10.1.20).

Group checks (service combinations):

- the largest pile load against the single pile's allowable compression and the least against
  its allowable uplift (:func:`saengine.substructure.piles.single_pile`);
- group efficiency, BNBC Sec 3.10.1.19: 1.0, except for friction piles in cohesive soil (here:
  skin friction above end bearing, most of it in cohesive layers), where the Converse-Labarre
  formula is used (the code gives no formula): ``Eg = 1 - θ ((n - 1) m + (m - 1) n) / (90 m
  n)``, θ = atan(D/s) in degrees, m rows of n piles; the group's capacity Eg n Qa against the
  total load;
- block failure in clay (Terzaghi & Peck 1967): ``Qblock = 2 (Bg + Lg) Σ cu ΔL + Nc cu,b Bg
  Lg``, Nc = 5 (1 + 0.2 L/Bg)(1 + 0.2 Bg/Lg) ≤ 9 (Skempton 1951), Bg × Lg the outline of the
  outer piles' faces (a tip in granular soil: the base at the pile's unit end bearing), divided
  by the compression factor of safety;
- spacing: at least 2.5 D (Sec 3.10.1.19) and 750 mm (Sec 3.10.1.30), 3 D for friction piles
  (Sec 3.10.1.30); the cap at least 100 mm beyond the piles' faces and a bottom cover of at
  least 50 mm (Sec 3.10.1.20); piles embedded at least 75 mm (noted);
- group settlement: the group as a solid foundation at 2/3 of the pile length (BNBC Sec 3.10.5,
  Long term settlement for pile group), Bg × Lg, under the largest gravity service load,
  computed by :func:`saengine.soil.settlement.settlement` (consolidation of the clay layers with
  the 2:1 spread, Schmertmann in sand) and shown with BNBC Table 6.3.8's limit (Sec 3.10.5
  refers to the shallow foundations' limits).

Cap design (strength combinations, ACI 318-19 as BNBC 2020 adopts it), with the pile reactions
of the column loads alone (the cap's own factored weight adds to the reactions and loads the
cap back in nearly the same places, so both are left out):

- flexure at each column face, beam method: the moment of the pile reactions beyond the face
  (less the other columns beyond it) over the whole cap width, against φMn of the bottom (or,
  hogging, top) bars of that direction (rectangular stress block, φ from εt);
- one-way shear at d from each column face (ACI 13.2.7.2 via 7.4.3.2), φVc = 0.75 · 0.66 λs
  ρ^(1/3) √f'c b d (Table 22.5.5.1 (c), no shear reinforcement);
- punching at d/2 round each column (22.6.4.1) and round each pile (as the square of the same
  area, sections cut by the cap's edges: corner and edge piles), vc of 22.6.5.2 with λs;
- the pile reactions on a section (13.4.2.5): a pile whose centre is D/2 or more outside the
  section counts fully, D/2 or more inside not at all, linearly in between;
- deep caps: when the shear span a (column face to the farthest pile centre beyond it) is less
  than d in a direction, the cap is a deep member there and the strut-and-tie method (ACI 318-19
  Chapter 23) governs: the sectional flexure and one-way shear are reported for reference and
  flagged, and a simple strut-and-tie model is checked in their place: the tie (the bottom bars
  of that direction over the cap width) for ``T = M / z``, M the moment of the pile reactions
  beyond the column's quarter point (the column load split in two halves at c/4 from its centre,
  where the struts start), z = 0.9 d, against φ As fy (23.7.2.1, φ = 0.75 of Table 21.2.1); the
  node under each column (C-C-C, βn = 1.0, Anz the column's section) and over the most loaded
  pile (C-C-T, βn = 0.8, Anz the pile's area) against φ 0.85 βn f'c Anz (23.9.1, Table 23.9.2,
  βc = 1 on the safe side). Punching, minimum steel and the hogging check always count;
- As,min = 0.0018 Ag (fy 420; Table 7.6.1.1) in each direction with the bottom bars.

Units: mm, N, N·mm and MPa inside; reported in kN, kN·m, kPa, mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.design.rc import PHI_SHEAR, STEEL_E
from saengine.design.slab import NO_DEMAND, critical_section, punching_capacity
from saengine.library.objects import BarMesh
from saengine.substructure.shallow import (
    ColumnBase,
    Loads,
    mesh_area,
    min_steel_ratio,
    one_way_shear_capacity,
    plain_flexure,
    strip_flexure,
)

G = 9.80665
#: Shear span over effective depth below which a cap is a deep member (strut-and-tie).
DEEP_RATIO = 1.0
#: Least clear distance from a pile's face to the cap's edge [mm] (BNBC Sec 3.10.1.20).
EDGE_DISTANCE = 100.0
#: Least clear cover of the cap's main bars [mm] (BNBC Sec 3.10.1.20).
CAP_COVER = 50.0
#: Least embedment of the piles in the cap [mm] (BNBC Sec 3.10.1.20).
PILE_EMBEDMENT = 75.0


@dataclass
class CapSpec:
    """A pile cap to design: geometry [mm] in its own axes, materials [MPa] and its piles."""

    id: str
    length: float  # along u
    width: float  # along v
    thickness: float
    cover: float
    fc: float
    fy: float
    columns: list[ColumnBase]
    piles: list[tuple[float, float]]  # offsets from the cap centre [mm]
    pile_diameter: float
    bottom_x: BarMesh | None = None
    bottom_y: BarMesh | None = None
    top_x: BarMesh | None = None
    top_y: BarMesh | None = None
    es: float = STEEL_E
    unit_weight: float = 2400 * G * 1e-9  # N/mm³
    soil_above: float = 0.0  # N/mm², soil and floor over the cap
    notes: list[str] = field(default_factory=list)

    @property
    def weight(self) -> float:
        """Weight of the cap and what lies on it [N]."""
        area = self.length * self.width
        return self.unit_weight * area * self.thickness + self.soil_above * area

    def depths(self, face: str = "bottom") -> dict[str, float]:
        """Effective depth [mm] of the X ("u") and Y ("v") bars of a face, X outer."""
        outer, inner = (
            (self.bottom_x, self.bottom_y) if face == "bottom" else (self.top_x, self.top_y)
        )
        base = self.thickness - self.cover
        d_outer = base - outer.dia / 2 if outer else None
        d_inner = base - (outer.dia if outer else 0.0) - inner.dia / 2 if inner else None
        return {
            "u": d_outer if d_outer is not None else (d_inner if d_inner is not None else base),
            "v": d_inner if d_inner is not None else (d_outer if d_outer is not None else base),
        }

    @property
    def d(self) -> float:
        depths = self.depths("bottom")
        return (depths["u"] + depths["v"]) / 2

    def outline(self) -> list[tuple[float, float]]:
        a, b = self.length / 2, self.width / 2
        return [(-a, -b), (a, -b), (a, b), (-a, b)]


# ─────────────────────────────────────── pile loads ───────────────────────────────────────


def pile_reactions(
    spec: CapSpec, loads: list[np.ndarray], weight: float = 0.0
) -> tuple[np.ndarray, list[str]]:
    """Pile loads [N] (compression positive) of a rigid cap under the column ``loads`` and a
    ``weight`` [N] at the cap's centre, and notes when the group cannot take a moment."""
    piles = np.asarray(spec.piles, dtype=float).reshape(-1, 2)
    n = len(piles)
    if n == 0:
        raise ValueError(f"{spec.id}: the pile cap has no piles")
    total = weight + sum(float(f[0]) for f in loads)
    centre = piles.mean(axis=0)
    # Moments about the piles' centroid, in the footing convention (see shallow._eccentricity).
    mv = -weight * centre[0] + sum(
        float(f[0]) * (c.u - centre[0]) + float(f[2])
        for c, f in zip(spec.columns, loads, strict=True)
    )
    mu = -weight * centre[1] + sum(
        float(f[0]) * (c.v - centre[1]) - float(f[1])
        for c, f in zip(spec.columns, loads, strict=True)
    )
    rel = piles - centre
    matrix = rel.T @ rel
    notes: list[str] = []
    coefficients = np.linalg.pinv(matrix, rcond=1e-9) @ np.array([mv, mu])
    reactions = total / n + rel @ coefficients
    residual = np.array([mv, mu]) - matrix @ coefficients
    if float(np.linalg.norm(residual)) > 1e3:  # more than 1 N·m left unresisted
        notes.append(
            "the piles lie in one line (or one pile): the group takes no moment across it; the "
            "column moments that way must go to tie beams"
        )
    return reactions, notes


def _service_weight(spec: CapSpec, name: str, dead_factor: dict[str, float] | None) -> float:
    factor = (dead_factor or {}).get(name, 1.0)
    return factor * spec.weight


# ─────────────────────────────────────── group ───────────────────────────────────────


def converse_labarre(piles: np.ndarray, diameter: float) -> tuple[float, int, int, float]:
    """Converse-Labarre efficiency of a group: (Eg, m rows, n per row, spacing [mm])."""
    if len(piles) < 2:
        return 1.0, 1, len(piles), 0.0
    us = np.unique(np.round(piles[:, 0] / 10.0))
    vs = np.unique(np.round(piles[:, 1] / 10.0))
    n, m = len(us), len(vs)
    s = min_spacing(piles)
    theta = math.degrees(math.atan(diameter / s)) if s > 0 else 90.0
    eg = 1 - theta * ((n - 1) * m + (m - 1) * n) / (90 * m * n)
    return max(eg, 0.0), m, n, s


def min_spacing(piles: np.ndarray) -> float:
    best = math.inf
    for i in range(len(piles)):
        for j in range(i + 1, len(piles)):
            best = min(best, float(np.linalg.norm(piles[i] - piles[j])))
    return best if math.isfinite(best) else 0.0


def group_outline(spec: CapSpec) -> tuple[float, float]:
    """Bg ≤ Lg [mm]: the outline of the outer piles' faces."""
    piles = np.asarray(spec.piles, dtype=float).reshape(-1, 2)
    extent = piles.max(axis=0) - piles.min(axis=0) + spec.pile_diameter
    return float(min(extent)), float(max(extent))


def _friction_in_clay(pile: dict[str, Any], profile: Any) -> bool:
    if pile["Qs"] <= pile["Qb"] or profile is None:
        return False
    cohesive = 0.0
    for row in pile["layers"]:
        layer = profile.layers[row["layer"]]
        if layer.behaviour == "cohesive":
            cohesive += row["Qs"]
    return cohesive > 0.5 * pile["Qs"]


def block_capacity(
    profile: Any, head: float, length: float, bg: float, lg: float, qb: float = 0.0
) -> tuple[float | None, str]:
    """Ultimate block capacity [kN] of a group Bg × Lg [m] of piles ``length`` m long from
    ``head`` m below the ground, in clay (None when the shaft meets no cohesive soil). Below a
    tip in granular soil the block's base takes the pile's unit end bearing ``qb`` [kPa]."""
    slices = max(1, math.ceil(length / 0.1))
    dz = length / slices
    side, clay = 0.0, False
    for k in range(slices):
        layer = profile.layer_at(head + (k + 0.5) * dz)
        if layer is not None and layer.behaviour == "cohesive" and layer.cu:
            side += layer.cu * dz
            clay = True
    if not clay:
        return None, "no cohesive soil along the piles"
    tip = profile.layer_at(head + length + 1e-6)
    if tip is not None and tip.behaviour == "cohesive" and tip.cu:
        nc = min(9.0, 5 * (1 + 0.2 * length / bg) * (1 + 0.2 * bg / lg))
        base = nc * tip.cu * bg * lg
        text = f"Nc = {nc:.2f}, cu at the tip {tip.cu:.0f} kPa"
    else:
        base = qb * bg * lg
        text = f"granular soil at the tip: the block's base at the pile's qb = {qb:.0f} kPa"
    return 2 * (bg + lg) * side + base, text


# ─────────────────────────────────────── cap design ───────────────────────────────────────


def _share_outside(distance_out: float, diameter: float) -> float:
    """ACI 318-19 13.4.2.5: the share of a pile's reaction acting on the far side of a
    section, from the distance [mm] of its centre outside the section (negative inside)."""
    return min(1.0, max(0.0, (distance_out + diameter / 2) / diameter))


def _face_actions(
    spec: CapSpec,
    reactions: np.ndarray,
    loads: list[np.ndarray],
    axis: int,
    column: int,
    side: int,
    offset: float,
) -> tuple[float, float]:
    """Moment [N·mm] (sagging +) and shear [N] on the section ``offset`` beyond a column's face,
    on its ``side`` (+1 / -1) along ``axis`` (0: u, 1: v): the pile reactions beyond it less
    the other columns beyond it. The moment takes a pile fully when its centre is beyond the
    section; the shear by 13.4.2.5."""
    c = spec.columns[column]
    centre = (c.u, c.v)[axis]
    half = (c.cu, c.cv)[axis] / 2
    section = centre + side * (half + offset)
    moment = shear = 0.0
    for (pu, pv), r in zip(spec.piles, reactions, strict=True):
        beyond = side * ((pu, pv)[axis] - section)
        if beyond > 0:
            moment += r * beyond
        shear += r * _share_outside(beyond, spec.pile_diameter)
    for k, (other, f) in enumerate(zip(spec.columns, loads, strict=True)):
        if k == column:
            continue
        beyond = side * ((other.u, other.v)[axis] - section)
        if beyond > 0:
            moment -= float(f[0]) * beyond
            shear -= float(f[0])
    return moment, shear


def _shear_span(spec: CapSpec, axis: int, column: int, side: int) -> float | None:
    c = spec.columns[column]
    face = (c.u, c.v)[axis] + side * (c.cu, c.cv)[axis] / 2
    arms = [side * ((pu, pv)[axis] - face) for pu, pv in spec.piles]
    arms = [a for a in arms if a > 0]
    return max(arms) if arms else None


def cap_checks(
    spec: CapSpec, strength: Loads, piles_by_combination: dict[str, np.ndarray] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Flexure, one-way shear, punching and minimum steel of the cap (see the module notes),
    and what the editor shows (``{"deep": {...}, "d": ...}``)."""
    from saengine.design.check import _check

    reactions_of = piles_by_combination or {
        name: pile_reactions(spec, loads)[0] for name, loads in strength.items()
    }
    depths = spec.depths("bottom")
    tops = spec.depths("top")
    meshes = {"u": (spec.bottom_x, spec.top_x), "v": (spec.bottom_y, spec.top_y)}
    widths = {"u": spec.width, "v": spec.length}  # the section across a direction's bars
    checks: list[dict[str, Any]] = []
    deep: dict[str, Any] = {}
    flags: list[str] = []
    for axis, name in ((0, "u"), (1, "v")):
        bars = "X" if name == "u" else "Y"
        width = widths[name]
        bottom, top = meshes[name]
        d, d_top = depths[name], tops[name]
        as_bottom, as_top = mesh_area(bottom), mesh_area(top)
        capacity_bottom = strip_flexure(as_bottom, d, spec.fc, spec.fy, spec.es)
        capacity_top = strip_flexure(as_top, d_top, spec.fc, spec.fy, spec.es)
        sag = (0.0, None, "")
        hog = (0.0, None, "")
        shear_worst = (-1.0, 0.0, 0.0, None, "")
        rho = as_bottom / (1000 * d) if d > 0 else 0.0
        phi_vc = one_way_shear_capacity(width, d, rho, spec.fc)
        spans: list[float] = []
        for k, column in enumerate(spec.columns):
            for side in (1, -1):
                span = _shear_span(spec, axis, k, side)
                if span is not None:
                    spans.append(span)
                where = f"{'+' if side > 0 else '-'}{name} face of {column.id}"
                edge = (spec.length, spec.width)[axis] / 2
                for combination, loads in strength.items():
                    reactions = reactions_of[combination]
                    moment, _ = _face_actions(spec, reactions, loads, axis, k, side, 0.0)
                    if moment > sag[0]:
                        sag = (moment, combination, where)
                    if -moment > hog[0]:
                        hog = (-moment, combination, where)
                    section = (column.u, column.v)[axis] + side * (
                        (column.cu, column.cv)[axis] / 2 + d
                    )
                    if abs(section) >= edge:
                        continue
                    _, vu = _face_actions(spec, reactions, loads, axis, k, side, d)
                    ratio = abs(vu) / phi_vc if phi_vc > 0 else math.inf
                    if ratio > shear_worst[0]:
                        shear_worst = (ratio, abs(vu), phi_vc, combination, f"d from the {where}")
        ratio = (max(spans) / d) if spans and d > 0 else None
        deep[name] = None if ratio is None else round(ratio, 2)
        is_deep = ratio is not None and ratio < DEEP_RATIO
        if is_deep:
            flags.append(name)
        suffix = " (deep cap: strut-and-tie governs)" if is_deep else ""
        phi_mn = capacity_bottom.phi_mn * width / 1000
        checks.append(
            _check(
                f"Flexure bottom {bars} at the column face{suffix}",
                sag[0] / 1e6,
                phi_mn / 1e6,
                "kN·m",
                sag[1],
                f"beam method over the cap width {width:.0f} mm, "
                + (
                    f"Ø{bottom.dia:g} @ {bottom.spacing:g}: As = {as_bottom * width / 1000:.0f} "
                    f"mm², d = {d:.0f} mm, φ = {capacity_bottom.phi:.2f}"
                    if bottom
                    else f"no bottom {bars} bars"
                )
                + (f"; {sag[2]}" if sag[2] else ""),
                flag=is_deep,
            )
        )
        if hog[0] > NO_DEMAND * width:  # as slabs: below 50 N·m/m, no bars needed
            if top:
                hog_capacity = capacity_top.phi_mn * width / 1000
                hog_note = f"Ø{top.dia:g} @ {top.spacing:g}, d = {d_top:.0f} mm"
            else:
                # Without top bars the top face is plain concrete, as for footings (ACI 318-19
                # 14.5.2.1, h less 50 mm by 14.5.1.7).
                hog_capacity = plain_flexure(spec.thickness, spec.fc) * width / 1000
                hog_note = (
                    f"no top {bars} bars: plain concrete, φMn = 0.60 × 0.42 √f'c Sm with "
                    f"h - 50 = {spec.thickness - 50:.0f} mm (ACI 14.5.2.1, 14.5.1.7)"
                )
                if "E" in (hog[1] or ""):
                    hog_note += (
                        "; under earthquake uplift BNBC 2020 Part 6 Sec 8.3.11.2 asks for top "
                        "flexural reinforcement in the pile cap"
                    )
            checks.append(
                _check(
                    f"Flexure top {bars} (hogging)",
                    hog[0] / 1e6,
                    hog_capacity / 1e6,
                    "kN·m",
                    hog[1],
                    hog_note
                    + f"; {hog[2]} (piles in tension pull the cap up: counted for deep caps too)",
                )
            )
        if shear_worst[3] is not None:
            ratio_v, vu, cap_v, combination, where = shear_worst
            checks.append(
                _check(
                    f"One-way shear across {bars}{suffix}",
                    vu / 1e3,
                    cap_v / 1e3,
                    "kN",
                    combination,
                    f"φVc = 0.75 · 0.66 λs ρ^(1/3) √f'c b d (ACI 22.5.5.1 (c)), "
                    f"b = {width:.0f} mm, d = {d:.0f} mm, ρ = {rho:.4f}; pile reactions by ACI "
                    f"13.4.2.5; {where}",
                    utilisation=ratio_v,
                    flag=is_deep,
                )
            )
        if is_deep:
            checks += _tie_check(spec, strength, reactions_of, axis, bars, width, d, as_bottom)
        required = min_steel_ratio(spec.fy) * width * spec.thickness
        checks.append(
            _check(
                f"Min. steel bottom {bars}",
                required,
                as_bottom * width / 1000,
                "mm²",
                None,
                f"As,min = {min_steel_ratio(spec.fy):.4f} b h (ACI Table 7.6.1.1)",
            )
        )
    if flags:
        checks += _node_checks(spec, strength, reactions_of)
    checks += _punching(spec, strength, reactions_of)
    detail = {"d": round(spec.d), "shearSpanRatio": deep, "deep": flags}
    if flags:
        detail["note"] = (
            f"shear span a < d along {', '.join(flags)}: a deep cap; checked by the strut-and-tie "
            "method (ACI 318-19 Chapter 23: the bottom bars as the tie, the nodes at the column "
            "and the pile heads; the sectional flexure and one-way shear are for reference). "
            "Anchor the tie bars beyond the outer piles with hooks or heads (ACI 23.8.3)"
        )
    return checks, detail


#: Strut-and-tie (ACI 318-19): φ (Table 21.2.1 (g)), the tie's lever arm over d, and βn of
#: the column's node (C-C-C) and of the pile heads' nodes (C-C-T) (Table 23.9.2).
PHI_STM = 0.75
TIE_ARM = 0.9
BETA_CCC = 1.0
BETA_CCT = 0.8


def _tie_check(
    spec: CapSpec,
    strength: Loads,
    reactions_of: dict[str, np.ndarray],
    axis: int,
    bars: str,
    width: float,
    d: float,
    as_bottom: float,
) -> list[dict[str, Any]]:
    """The tie of a deep cap along ``axis``: ``T = M / z``, M the moment of the pile reactions
    beyond the column's quarter point (the struts start from the column's load split in two
    halves, each at c/4 from its centre), z = 0.9 d; against φ As fy (ACI 23.7.2.1)."""
    from saengine.design.check import _check

    z = TIE_ARM * d
    worst: tuple[float, str | None, str] = (0.0, None, "")
    for k, column in enumerate(spec.columns):
        quarter = (column.cu, column.cv)[axis] / 4
        for side in (1, -1):
            where = f"{'+' if side > 0 else '-'}{'u' if axis == 0 else 'v'} side of {column.id}"
            for combination, loads in strength.items():
                moment, _ = _face_actions(
                    spec, reactions_of[combination], loads, axis, k, side, -quarter
                )
                if moment / z > worst[0]:
                    worst = (moment / z, combination, where)
    if worst[1] is None:
        return []
    tie, combination, where = worst
    area = as_bottom * width / 1000
    return [
        _check(
            f"Tie (bottom {bars} bars, strut-and-tie)",
            tie / 1e3,
            PHI_STM * area * spec.fy / 1e3,
            "kN",
            combination,
            f"T = M / z, M of the pile reactions beyond the column's quarter point, z = "
            f"{TIE_ARM:g} d = {z:.0f} mm; φ As fy, φ = {PHI_STM:g}, As = {area:.0f} mm² over "
            f"{width:.0f} mm (ACI 318-19 23.7.2.1, 21.2.1); {where}",
        )
    ]


def _node_checks(
    spec: CapSpec, strength: Loads, reactions_of: dict[str, np.ndarray]
) -> list[dict[str, Any]]:
    """Bearing on the nodes of a deep cap (ACI 318-19 23.9): the column's C-C-C node and the
    pile heads' C-C-T nodes, fce = 0.85 βn f'c (βc = 1, on the safe side)."""
    from saengine.design.check import _check

    checks: list[dict[str, Any]] = []
    for k, column in enumerate(spec.columns):
        area = column.cu * column.cv
        worst = max(((float(loads[k][0]), name) for name, loads in strength.items()), default=None)
        if worst is None or area <= 0:
            continue
        fce = 0.85 * BETA_CCC * spec.fc
        checks.append(
            _check(
                f"Node under {column.id} (strut-and-tie)",
                worst[0] / 1e3,
                PHI_STM * fce * area / 1e3,
                "kN",
                worst[1],
                f"C-C-C node, φ 0.85 βn f'c Anz with βn = {BETA_CCC:g}, Anz = the column "
                f"{column.cu:.0f} × {column.cv:.0f} mm (ACI 318-19 23.9.1, Table 23.9.2)",
            )
        )
    area = math.pi * spec.pile_diameter**2 / 4
    worst_pile = max(
        ((float(r.max()), name) for name, r in reactions_of.items() if len(r)), default=None
    )
    if worst_pile is not None:
        fce = 0.85 * BETA_CCT * spec.fc
        checks.append(
            _check(
                "Node over a pile (strut-and-tie)",
                max(worst_pile[0], 0.0) / 1e3,
                PHI_STM * fce * area / 1e3,
                "kN",
                worst_pile[1],
                f"C-C-T node at the pile head, φ 0.85 βn f'c Anz with βn = {BETA_CCT:g}, Anz = "
                f"the pile's area (Ø{spec.pile_diameter:.0f}) (ACI 318-19 23.9.1, Table 23.9.2)",
            )
        )
    return checks


def _rectangle_distance(du: float, dv: float, half_u: float, half_v: float) -> float:
    """Signed distance [mm] of a point outside (+) a rectangle centred at the origin."""
    return max(abs(du) - half_u, abs(dv) - half_v)


def _punching(
    spec: CapSpec, strength: Loads, reactions_of: dict[str, np.ndarray]
) -> list[dict[str, Any]]:
    from saengine.design.check import _check

    d = spec.d
    outline = spec.outline()
    checks: list[dict[str, Any]] = []
    for k, column in enumerate(spec.columns):
        section = critical_section((column.u, column.v), column.cu, column.cv, 0.0, d, outline)
        if not section.sides:
            continue
        lo_u, hi_u, lo_v, hi_v = section.extents
        beta = max(column.cu, column.cv) / min(column.cu, column.cv)
        capacity = punching_capacity(spec.fc, d, section.b0, beta, section.alpha_s)
        worst: tuple[float, float, str | None] = (-1.0, 0.0, None)
        for combination, loads in strength.items():
            reactions = reactions_of[combination]
            inside = 0.0
            for (pu, pv), r in zip(spec.piles, reactions, strict=True):
                du, dv = pu - column.u - (hi_u - lo_u) / 2, pv - column.v - (hi_v - lo_v) / 2
                out = _rectangle_distance(du, dv, (lo_u + hi_u) / 2, (lo_v + hi_v) / 2)
                inside += r * (1 - _share_outside(out, spec.pile_diameter))
            vu = float(loads[k][0]) - inside
            if vu > worst[0]:
                worst = (vu, vu / (section.b0 * d), combination)
        vu, stress, combination = worst
        phi_vc = PHI_SHEAR * capacity.vc
        checks.append(
            _check(
                f"Punching at {column.id}",
                max(vu, 0.0) / 1e3,
                phi_vc * section.b0 * d / 1e3,
                "kN",
                combination,
                f"{section.location} section at d/2, b0 = {section.b0:.0f} mm, d = {d:.0f} mm, "
                f"Vu = P less the pile reactions inside (ACI 13.4.2.5), vu = {stress:.3f} MPa, "
                f"vc = {capacity.vc:.3f} MPa (ACI 22.6.5.2, λs = {capacity.lambda_s:.2f}); "
                "the column moments are in the pile reactions",
                utilisation=max(stress, 0.0) / phi_vc,
            )
        )
    side = math.sqrt(math.pi) / 2 * spec.pile_diameter  # square of the same area
    worst_pile: tuple[float, float, float, str | None, str] = (-1.0, 0.0, 0.0, None, "")
    for i, (pu, pv) in enumerate(spec.piles):
        section = critical_section((pu, pv), side, side, 0.0, d, outline)
        if not section.sides:
            continue
        capacity = punching_capacity(spec.fc, d, section.b0, 1.0, section.alpha_s)
        phi_v = PHI_SHEAR * capacity.vc * section.b0 * d
        for combination in strength:
            r = float(reactions_of[combination][i])
            ratio = r / phi_v if phi_v > 0 else math.inf
            if ratio > worst_pile[0]:
                worst_pile = (
                    ratio,
                    r,
                    phi_v,
                    combination,
                    (
                        f"pile {i + 1} ({section.location}), b0 = {section.b0:.0f} mm, "
                        f"vc = {capacity.vc:.3f} MPa"
                    ),
                )
    if worst_pile[3] is not None:
        ratio, r, phi_v, combination, where = worst_pile
        checks.append(
            _check(
                "Punching round a pile",
                r / 1e3,
                phi_v / 1e3,
                "kN",
                combination,
                f"section at d/2 from the pile (as a {side:.0f} mm square of the same area), cut "
                f"by the cap's edges; {where}",
                utilisation=ratio,
            )
        )
    return checks


# ─────────────────────────────────────── the cap ───────────────────────────────────────


def pile_cap_design(
    spec: CapSpec,
    service: Loads,
    strength: Loads,
    pile: dict[str, Any],
    profile: Any = None,
    pile_section: dict[str, Any] | None = None,
    dead_factor: dict[str, float] | None = None,
    strength_dead_factor: dict[str, float] | None = None,
    kind: str = "bored",
) -> dict[str, Any]:
    """All checks of a pile cap and its piles (see the module notes).

    ``pile``: :func:`saengine.substructure.piles.single_pile` of the cap's pile type at the
    nearest borehole (``profile``, for the group efficiency, block failure and settlement;
    None leaves those out). ``pile_section``: ``{"fc", "fy", "reinforcement"}`` of the pile
    (the structural check is left out without it). ``dead_factor`` / ``strength_dead_factor``:
    the factor on the dead load per service / strength combination, for the cap's weight
    (default 1.0 and 1.2).

    Returns ``{"checks", "piles", "group", "cap", "notes"}``: ``piles`` per pile its offsets
    [mm] and the largest and least service and factored loads [kN]."""
    from saengine.design.check import _check
    from saengine.substructure.piles import structural_checks

    notes = list(spec.notes)
    checks: list[dict[str, Any]] = []
    piles = np.asarray(spec.piles, dtype=float).reshape(-1, 2)
    n = len(piles)
    dia = spec.pile_diameter

    # ── service: pile loads against the single pile ──
    service_max = np.full(n, -math.inf)
    service_min = np.full(n, math.inf)
    worst_c = (-math.inf, None)
    worst_t = (math.inf, None)
    total_max = (0.0, None)
    gravity_max = (0.0, None)
    for name, loads in service.items():
        weight = _service_weight(spec, name, dead_factor)
        reactions, found = pile_reactions(spec, loads, weight)
        for note in found:
            if note not in notes:
                notes.append(note)
        service_max = np.maximum(service_max, reactions)
        service_min = np.minimum(service_min, reactions)
        if reactions.max() > worst_c[0]:
            worst_c = (float(reactions.max()), name)
        if reactions.min() < worst_t[0]:
            worst_t = (float(reactions.min()), name)
        total = float(reactions.sum())
        if total > total_max[0]:
            total_max = (total, name)
        if not any(c in name for c in ("W", "E")) and total > gravity_max[0]:
            gravity_max = (total, name)
    qa, ta = pile["Qa"], pile["Ta"]
    if worst_c[1] is not None:
        checks.append(
            _check(
                "Pile load, compression",
                worst_c[0] / 1e3,
                qa,
                "kN",
                worst_c[1],
                f"rigid cap: P/n ± M u/Σu² ± M v/Σv², cap weight included; Qa of "
                f"{pile['borehole']} ({pile['method']}, FS {pile['factors']['compression']:g})",
            )
        )
        uplift = max(-worst_t[0], 0.0)
        checks.append(
            _check(
                "Pile load, uplift",
                uplift / 1e3,
                ta,
                "kN",
                worst_t[1],
                f"least pile load {worst_t[0] / 1e3:.1f} kN; Ta = (0.7 Qs + W)/FS (BNBC Eq 6.3.12)",
            )
        )

    # ── group ──
    friction_clay = _friction_in_clay(pile, profile)
    if friction_clay and n > 1:
        eg, m_rows, n_cols, s = converse_labarre(piles, dia)
        efficiency_note = (
            f"friction piles in cohesive soil: Converse-Labarre, {m_rows} × {n_cols}, "
            f"s = {s:.0f} mm, θ = {math.degrees(math.atan(dia / s)):.1f}°"
        )
    else:
        eg = 1.0
        efficiency_note = "1.0 (BNBC Sec 3.10.1.19: not friction piles in cohesive soil)"
    if total_max[1] is not None:
        checks.append(
            _check(
                "Group capacity",
                total_max[0] / 1e3,
                eg * n * qa,
                "kN",
                total_max[1],
                f"Eg n Qa with Eg = {eg:.3f}: {efficiency_note}",
            )
        )
    bg, lg = group_outline(spec)
    block = None
    if profile is not None and n > 1 and total_max[1] is not None:
        head, length = pile["head"] / 1e3, pile["length"] / 1e3
        block, block_note = block_capacity(profile, head, length, bg / 1e3, lg / 1e3, pile["qb"])
        if block is not None:
            fs = pile["factors"]["compression"]
            checks.append(
                _check(
                    "Block failure (clay)",
                    total_max[0] / 1e3,
                    block / fs,
                    "kN",
                    total_max[1],
                    f"Qblock = 2 (Bg + Lg) Σ cu ΔL + Nc cu Bg Lg = {block:.0f} kN, Bg × Lg = "
                    f"{bg:.0f} × {lg:.0f} mm, FS {fs:g} (Terzaghi & Peck); {block_note}",
                )
            )
    settlement = None
    if profile is not None and gravity_max[1] is not None:
        settlement = group_settlement(
            profile, pile["head"] / 1e3, pile["length"] / 1e3, bg / 1e3, lg / 1e3,
            gravity_max[0] / 1e3,
        )  # fmt: skip
        settlement["combination"] = gravity_max[1]
        limit = settlement["permissible"]["value"]
        checks.append(
            _check(
                "Group settlement",
                settlement["total"],
                limit,
                "mm",
                gravity_max[1],
                f"solid block at 2/3 L ({settlement['Df']:.0f} mm below the ground), "
                f"{bg:.0f} × {lg:.0f} mm, q = {settlement['q']:.0f} kPa (BNBC Sec 3.10.5); "
                f"{settlement['permissible']['source']}",
            )
        )
    # Spacing and edges (BNBC Secs 3.10.1.19, 3.10.1.20, 3.10.1.30).
    if n > 1:
        s = min_spacing(piles)
        need = max(2.5 * dia, 750.0, 3.0 * dia if pile["Qs"] > pile["Qb"] else 0.0)
        rule = (
            "3 D for friction piles (Sec 3.10.1.30)"
            if pile["Qs"] > pile["Qb"]
            else "2.5 D (Sec 3.10.1.19) and 750 mm (Sec 3.10.1.30)"
        )
        checks.append(_check("Pile spacing", need, s, "mm", None, f"least c/c; at least {rule}"))
    edge = min(
        min(spec.length / 2 - abs(u), spec.width / 2 - abs(v)) - dia / 2 for u, v in spec.piles
    )
    checks.append(
        _check(
            "Cap edge beyond the piles",
            EDGE_DISTANCE,
            edge,
            "mm",
            None,
            "BNBC Sec 3.10.1.20: the cap extends at least 100 mm beyond the edge of all piles",
        )
    )
    checks.append(
        _check(
            "Cover of the cap's main bars",
            max(CAP_COVER, PILE_EMBEDMENT),
            spec.cover,
            "mm",
            None,
            "BNBC Sec 3.10.1.20: clear cover at least 50 mm over a 75 mm levelling course, and "
            "the pile heads embedded at least 75 mm: the bars run over the pile heads, so their "
            "cover to the cap's underside is at least 75 mm (d is taken from this cover)",
        )
    )
    notes.append(
        "pile heads: cut back to sound concrete and embedded at least 75 mm in the cap (BNBC Sec "
        "3.10.1.20); the pile bars run into the cap over their development length (ACI 318-19 "
        "25.4), in tension when the pile can be pulled"
    )
    if n == 1:
        notes.append(
            "a single pile under a column: BNBC Sec 3.10.4.11 does not recommend it unless the "
            "diameter is 600 mm or more; tie beams must brace it in both directions"
        )
    elif n == 2:
        notes.append(
            "two piles are braced along their axis only (BNBC Sec 3.10.1.19): tie beams across"
        )

    # ── strength: factored pile loads (structure) and the cap ──
    strength_reactions: dict[str, np.ndarray] = {}
    factored_max = np.full(n, -math.inf)
    factored_min = np.full(n, math.inf)
    pu = (0.0, None)
    tu = (0.0, None)
    for name, loads in strength.items():
        strength_reactions[name] = pile_reactions(spec, loads)[0]
        factor = (strength_dead_factor or {}).get(name, 1.2)
        with_weight = pile_reactions(spec, loads, factor * spec.weight)[0]
        factored_max = np.maximum(factored_max, with_weight)
        factored_min = np.minimum(factored_min, with_weight)
        if with_weight.max() > pu[0]:
            pu = (float(with_weight.max()), name)
        if -with_weight.min() > tu[0]:
            tu = (float(-with_weight.min()), name)
    if pile_section is not None and strength:
        checks += structural_checks(
            kind,
            dia,
            pile_section["fc"],
            pile_section["fy"],
            pile_section.get("reinforcement"),
            pu[0] / 1e3,
            tu[0] / 1e3,
            max(float(service_max.max()), 0.0) / 1e3 if service else 0.0,
            pu[1],
            tu[1],
        )
    cap: dict[str, Any] = {}
    if strength:
        cap_list, cap = cap_checks(spec, strength, strength_reactions)
        checks += cap_list
        if cap.get("note"):
            notes.append(cap["note"])

    rows = []
    for i, (u, v) in enumerate(spec.piles):
        rows.append(
            {
                "index": i + 1,
                "u": round(u),
                "v": round(v),
                "serviceMax": _kn(service_max[i]),
                "serviceMin": _kn(service_min[i]),
                "strengthMax": _kn(factored_max[i]),
                "strengthMin": _kn(factored_min[i]),
            }
        )
    return {
        "checks": checks,
        "piles": rows,
        "group": {
            "count": n,
            "efficiency": round(eg, 3),
            "efficiencyNote": efficiency_note,
            "Bg": round(bg),
            "Lg": round(lg),
            "block": None if block is None else round(block, 1),
            "settlement": settlement,
            "minSpacing": round(min_spacing(piles)) if n > 1 else None,
        },
        "cap": cap,
        "notes": notes,
    }


def _kn(value: float) -> float | None:
    return round(float(value) / 1e3, 1) if math.isfinite(value) else None


def group_settlement(
    profile: Any, head: float, length: float, bg: float, lg: float, load: float
) -> dict[str, Any]:
    """Settlement [mm] of a pile group as a solid block Bg × Lg [m] at 2/3 of the pile
    ``length`` below its ``head`` [m] under the total ``load`` [kN] (BNBC Sec 3.10.5)."""
    from saengine.soil.settlement import rounded, settlement

    df = head + 2 * length / 3
    q = load / (bg * lg)
    result = rounded(settlement(profile, bg, lg, df, q))
    result["method"] = (
        "equivalent raft at 2/3 L (BNBC Sec 3.10.5): immediate (Schmertmann / Steinbrenner) "
        "and consolidation (2:1 spread) below it; the piles' elastic shortening is not included"
    )
    return result


# ─────────────────────────────────────── in the report ───────────────────────────────────────

PILE_CAP_METHOD = [
    (
        "Pile caps: the columns' support reactions, reversed, in the cap's axes (as footings); "
        "pile loads of a rigid cap, P/n ± M u'/Σu'² ± M v'/Σv'² about the piles' centroid "
        "(the cap's weight and the soil on it under the service combinations), against the "
        "allowable compression and uplift of one pile at the borehole nearest the cap. Group: "
        "efficiency 1.0 (BNBC 2020 Part 6 Sec 3.10.1.19) or Converse-Labarre for friction piles "
        "in clay, block failure in clay (Terzaghi & Peck), spacing ≥ 2.5 D and 750 mm (3 D for "
        "friction piles, Secs 3.10.1.19, 3.10.1.30), the cap 100 mm beyond the piles and 50 mm "
        "cover (Sec 3.10.1.20), settlement of the group as a solid block at 2/3 L (Sec 3.10.5) "
        "against Table 6.3.8."
    ),
    (
        "Pile cap design (ACI 318-19): flexure at the column faces by the beam method, one-way "
        "shear at d from them, punching at d/2 round the columns and the piles (corner and edge "
        "sections cut by the cap), the pile reactions on a section by 13.4.2.5, As,min of Table "
        "7.6.1.1; a cap whose shear span is less than d is deep: the sectional flexure and "
        "one-way shear are flagged as reference values and the strut-and-tie method (Chapter "
        "23) is checked instead: the bottom bars as the tie, T = M/z with M beyond the column's "
        "quarter point and z = 0.9 d, against 0.75 As fy, and the nodes under the column (βn "
        "1.0) and over the piles (βn 0.8) against 0.75 × 0.85 βn f'c."
    ),
]


def design_pile_cap(ctx: Any, foundation: Any) -> tuple[dict[str, Any], list[str]]:
    """The checks of a pile cap of the substructure (``ctx``: a
    :class:`saengine.substructure.context.Context`): ``(result, notes)`` in the report's
    format, with ``piles`` (per pile its offsets and loads), ``pile`` (the single pile's
    capacity), ``group``, ``cap`` and ``capacityTable``. Raises
    :class:`~saengine.substructure.context.Skip` when it cannot be designed."""
    from saengine.substructure.context import Skip
    from saengine.substructure.piles import (
        FactorsOfSafety,
        capacity_table,
        nearest_profile,
        profiles_of,
        single_pile,
        table_sizes,
    )
    from saengine.substructure.shallow import footing_loads, place_footing, summary

    pile_type = ctx.substructure.pile_type(foundation.pileType)
    if pile_type is None:
        raise Skip(f"unknown pile type '{foundation.pileType}'")
    placed = place_footing(ctx, foundation)
    footing = placed.spec
    pile_concrete = ctx.concrete(pile_type.material, pile_type.id)
    pile_fy = footing.fy
    if pile_type.reinforcement is not None:
        pile_fy = ctx.rebar(pile_type.reinforcement.material).steel.fy
    profiles, report, problems = profiles_of(ctx.soil_text)
    if not profiles:
        reason = "; ".join(problems[:2]) if problems else "1 Soil Report has no boreholes"
        raise Skip(f"the pile capacity needs the soil: {reason}")
    centre = placed.center
    profile, distance = nearest_profile(profiles, float(centre[0]), float(centre[1]))
    notes = list(placed.notes)
    head = (report.ground_level(profile.borehole) - placed.founding_level) / 1e3
    if head < 0:
        notes.append(
            f"{foundation.id}: the cap's underside lies above {profile.id}'s ground; the pile "
            "heads are taken at the ground"
        )
        head = 0.0
    design = ctx.substructure.design
    fos = design.factorOfSafety
    factors = FactorsOfSafety(
        fos.pileCompression,
        fos.pileUplift,
        fos.pileSkin,
        fos.pileEndBearing,
        bool(getattr(fos, "pileLoadTest", False)),  # optional field (see the integration notes)
    )
    kind = pile_type.kind
    pile = single_pile(
        profile,
        kind,
        pile_type.diameter / 1e3,
        pile_type.length / 1e3,
        head,
        design.pileCapacity,
        factors,
        (pile_concrete.mechanical.density or 2400.0) * G / 1e3,
    )
    pile["distance"] = round(distance)
    notes += [f"{foundation.id}, pile {pile_type.id}: {n}" for n in pile["notes"]]
    foundation_settings = ctx.settings.foundation
    cover = max(0.0, foundation_settings.groundLevel - footing.elevation)
    spec = CapSpec(
        id=foundation.id,
        length=footing.length,
        width=footing.width,
        thickness=footing.thickness,
        cover=footing.cover,
        fc=footing.fc,
        fy=footing.fy,
        columns=footing.columns,
        piles=[(float(u), float(v)) for u, v in foundation.piles or []],
        pile_diameter=pile_type.diameter,
        bottom_x=footing.bottom_x,
        bottom_y=footing.bottom_y,
        top_x=footing.top_x,
        top_y=footing.top_y,
        es=footing.es,
        unit_weight=footing.unit_weight,
        soil_above=foundation_settings.soilUnitWeight * 1e-6 * cover,
    )
    for u, v in spec.piles:
        if abs(u) > spec.length / 2 or abs(v) > spec.width / 2:
            raise Skip(f"a pile at ({u:.0f}, {v:.0f}) lies outside the cap")
    loads = ctx.loads
    service, strength = footing_loads(loads, placed)
    service_dead = {
        name: factors_.get("D", factors_.get("SD", 1.0)) for name, factors_ in loads.service
    }
    out = pile_cap_design(
        spec,
        service,
        strength,
        pile,
        profile,
        {
            "fc": pile_concrete.concrete.fc,
            "fy": pile_fy,
            "reinforcement": pile_type.reinforcement,
        },
        service_dead,
        loads.dead,
        kind,
    )
    available = (profile.bottom - head) * 1e3 - 3 * pile_type.diameter
    diameters, lengths = table_sizes(pile_type.diameter, pile_type.length, available)
    table = capacity_table(profile, kind, diameters, lengths, head, design.pileCapacity, factors)
    members = list(dict.fromkeys(c.id for c in spec.columns))
    sizes = {
        "length": spec.length,
        "width": spec.width,
        "thickness": spec.thickness,
        "foundingLevel": placed.founding_level,
        "center": [round(float(centre[0]), 1), round(float(centre[1]), 1)],
        "rotation": round(math.degrees(math.atan2(placed.axis_u[1], placed.axis_u[0])), 3),
        "pileType": pile_type.id,
        "pileDiameter": pile_type.diameter,
        "pileLength": pile_type.length,
    }
    result = summary(
        foundation,
        out["checks"],
        members,
        sizes=sizes,
        pressure=None,
        piles=out["piles"],
        pile=pile,
        group=out["group"],
        cap=out["cap"],
        capacityTable=table,
    )
    return result, notes + [f"{foundation.id}: {n}" for n in out["notes"]]
