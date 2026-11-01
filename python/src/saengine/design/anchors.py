"""Anchoring to concrete: the strength of a group of cast-in or post-installed anchors in
tension and shear, under the anchoring rules of the code pack in force (its ``anchors`` table;
Appendix K of Part 6 in the default pack).

One engine for every attachment that anchors into concrete: steel column base plates
(:func:`saengine.design.steel_connections.check_base_plate`), embedded plates and other
attachments. Masonry anchor bolts have their own rules (the masonry design).

For a group of anchors (positions in the plane of the concrete surface, one diameter, one
embedment) and its demands (the tension of each anchor and the shear on the group, per
combination), :func:`check_group` checks, with the pack's φ and factors:

- tension: the steel of the anchor (Ase,N futa), the concrete breakout of the anchors in
  tension (projected areas ANc/ANco with the eccentricity, edge, cracking and splitting
  factors, the narrow-member hef), the pullout of headed and hooked anchors (or the product's
  tested value), and the side-face blowout of headed anchors deep near an edge (singly and as
  a row along the edge);
- shear: the steel (Ase,V futa, the grout pad factor), the concrete breakout toward each edge
  (projected areas AVc/AVco with the edge, cracking and thickness factors, the narrow-member
  ca1), both the row nearest the edge with its share and the farthest row with all the shear,
  and pryout (kcp Ncbg);
- anchor reinforcement in place of a breakout, when its area is given;
- the interaction of tension and shear (a trilinear rule);
- in earthquake combinations of the Seismic Design Categories the pack names: the concrete
  modes reduced, and the ductility rule chosen (a ductile anchor's steel governs, a yielding
  attachment, or a reduced strength);
- the least spacing, edge distances and depth limits, and the method's range.

The shear direction of a column base is not known (the base forces are resultants), so the full
shear is taken toward each edge in turn and the worst kept; shear parallel to an edge (which the
code allows twice the perpendicular value) is not used, which is on the safe side.

A pack without an ``anchors`` table does not cover anchoring: :func:`check_group` returns
``covered: False`` with no checks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from saengine.library.objects import AnchorConcrete

TABLE = "anchors"

#: Kinds cast into the concrete (the rest are post-installed).
CAST_IN = frozenset({"headedBolt", "headedStud", "hookedBolt"})
#: Kinds with a head bearing on the concrete.
HEADED = frozenset({"headedBolt", "headedStud"})

INF = math.inf


def anchors_table() -> Any | None:
    """The ``anchors`` table of the pack in force; None when it does not cover anchoring."""
    try:
        from saengine.codes import context as code_context

        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery (a bare calculation)
        from saengine.codes.tables import builtin_table

        return builtin_table(TABLE)


def pack_name() -> str:
    try:
        from saengine.codes import context as code_context

        return code_context.current().name
    except Exception:  # noqa: BLE001
        return "the code pack"


def cite(table: Any, key: str) -> str:
    """The short clause of ``key`` in the table's sources (its text before the page)."""
    text = table.sources.get(key, "")
    return text.split(" (", 1)[0]


# ─────────────────────────────────────── inputs ───────────────────────────────────────


@dataclass(frozen=True)
class SeismicContext:
    """The earthquake side of a run: the Seismic Design Category and the combinations with
    earthquake (their names; response spectrum patterns ``"<name> [<label>]"`` match too)."""

    category: str | None
    earthquake: frozenset[str] = frozenset()

    def applies(self, table: Any, combination: str | None) -> bool:
        if not combination or self.category not in set(table.seismic.categories):
            return False
        base = combination
        if base.endswith("]") and " [" in base:
            base = base.rsplit(" [", 1)[0]
        return combination in self.earthquake or base in self.earthquake


@dataclass
class Group:
    """A group of anchors of one diameter in one concrete member. ``points``: the anchors'
    positions [mm] from the attachment's centre (x, y); ``edges``: the concrete edges as
    distances from that centre (-x, +x, -y, +y), INF for far."""

    points: list[tuple[float, float]]
    diameter: float
    fu: float
    fy: float
    concrete: float
    spec: AnchorConcrete
    edges: tuple[float, float, float, float] = (INF, INF, INF, INF)
    attachment_thickness: float | None = None


@dataclass
class Demand:
    """One combination's anchor forces: the tension of each anchor (>= 0) [N] and the shear on
    the group [N] (its eccentricity from the group's centre [mm])."""

    combination: str | None
    tensions: list[float]
    shear: float = 0.0
    shear_eccentricity: float = 0.0


@dataclass
class _Mode:
    """A failure mode's worst demand over the combinations."""

    name: str
    unit: str
    note: str
    side: str  # "tension" | "shear"
    concrete: bool
    utilisation: float = -1.0
    demand: float = 0.0
    capacity: float = 0.0
    combination: str | None = None
    per_combination: dict[Any, float] = field(default_factory=dict)

    def add(self, key: Any, combination: str | None, demand: float, capacity: float) -> None:
        u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else 99.0)
        self.per_combination[key] = max(self.per_combination.get(key, 0.0), u)
        if u > self.utilisation:
            self.utilisation, self.demand, self.capacity = u, demand, capacity
            self.combination = combination


def _check(name, demand, capacity, unit, combination, note="", flag=False) -> dict[str, Any]:
    """A check in the design_report format (saengine.design.check._check)."""
    u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(demand), 2) if math.isfinite(demand) else 0.0,
        "capacity": round(float(capacity), 2) if math.isfinite(capacity) else 0.0,
        "unit": unit,
        "utilisation": u,
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": flag,
    }


# ─────────────────────────────────────── geometry ───────────────────────────────────────


def _bounds(g: Group) -> tuple[float, float, float, float]:
    """The concrete as coordinates: xmin, xmax, ymin, ymax."""
    return (-g.edges[0], g.edges[1], -g.edges[2], g.edges[3])


def _distances(g: Group, i: int) -> tuple[float, float, float, float]:
    """Anchor ``i`` to the four edges (-x, +x, -y, +y)."""
    x, y = g.points[i]
    xmin, xmax, ymin, ymax = _bounds(g)
    return (x - xmin, xmax - x, y - ymin, ymax - y)


def _max_spacing(g: Group, idx: list[int]) -> float:
    pts = [g.points[i] for i in idx]
    return max((math.dist(a, b) for a in pts for b in pts), default=0.0)


def _min_spacing(g: Group) -> float:
    pts = g.points
    return min(
        (math.dist(pts[i], pts[j]) for i in range(len(pts)) for j in range(i + 1, len(pts))),
        default=INF,
    )


def effective_area(g: Group, table: Any) -> float:
    """Ase [mm²] of a threaded anchor: π/4 (da - c/nt)², nt from the coarse pitch."""
    pitch = table.estimates.threadPitch.get(str(round(g.diameter)))
    if pitch is None:
        return math.pi * g.diameter**2 / 4
    d = g.diameter - table.steel.threadConstant * pitch
    return math.pi * d**2 / 4


def bearing_area(g: Group, table: Any) -> float:
    """Abrg [mm²]: the entered head area, or a hex nut of nutAcrossFlats × da less the rod."""
    if g.spec.headBearingArea:
        return float(g.spec.headBearingArea)
    f = table.estimates.nutAcrossFlats * g.diameter
    return math.sqrt(3) / 2 * f**2 - math.pi * g.diameter**2 / 4


def _fc(g: Group, table: Any) -> float:
    key = "castIn" if g.spec.kind in CAST_IN else "postInstalled"
    return min(g.concrete, table.concreteStrengthMax[key])


# ─────────────────────────────────────── tension ───────────────────────────────────────


def _phi_tension(g: Group, table: Any, condition: str) -> float:
    key = "castIn" if g.spec.kind in CAST_IN else f"category{g.spec.category}"
    return float(getattr(table.phi.concreteTension[key], condition))


def _condition(g: Group) -> str:
    return "A" if g.spec.supplementaryReinforcement else "B"


def breakout_tension(
    g: Group, table: Any, idx: list[int], tensions: list[float] | None = None
) -> tuple[float, dict[str, float]]:
    """Nominal concrete breakout strength Ncbg [N] of the anchors ``idx`` in tension (their
    forces ``tensions`` set the eccentricity; none: concentric), and the factors used."""
    bt = table.breakoutTension
    spec = g.spec
    hef = spec.embedment
    proj = bt.projection
    dist = [_distances(g, i) for i in idx]
    near = [min(d[k] for d in dist) for k in range(4)]
    influencing = [c for c in near if c < proj * hef]
    if len(influencing) >= bt.narrowEdges:
        hef = min(hef, max(max(influencing) / proj, bt.spacingShare * _max_spacing(g, idx)))
    xmin, xmax, ymin, ymax = _bounds(g)
    xs = [g.points[i][0] for i in idx]
    ys = [g.points[i][1] for i in idx]
    width = min(max(xs) + proj * hef, xmax) - max(min(xs) - proj * hef, xmin)
    depth = min(max(ys) + proj * hef, ymax) - max(min(ys) - proj * hef, ymin)
    anco = (2 * proj * hef) ** 2
    anc = min(width * depth, len(idx) * anco)
    # Eccentricity of the tension resultant from the centroid of the anchors in tension.
    psi_ec = 1.0
    if tensions is not None and len(idx) > 1:
        total = sum(tensions[i] for i in idx)
        if total > 0:
            for axis in (0, 1):
                centre = sum(g.points[i][axis] for i in idx) / len(idx)
                at = sum(tensions[i] * g.points[i][axis] for i in idx) / total
                psi_ec *= min(1.0, 1.0 / (1.0 + bt.eccentricity * abs(at - centre) / hef))
    camin = min(near)
    psi_ed = 1.0 if camin >= proj * hef else bt.edgeBase + bt.edgeSlope * camin / (proj * hef)
    cast = spec.kind in CAST_IN
    psi_c = 1.0
    if not spec.cracked:
        psi_c = bt.uncrackedCastIn if cast else bt.uncrackedPostInstalled
    psi_cp = 1.0
    if not cast and not spec.cracked and not spec.supplementaryReinforcement:
        cac = table.spacing.criticalEdge.get(spec.kind, 0.0) * hef
        if cac > 0 and camin < cac:
            psi_cp = max(camin / cac, proj * hef / cac)
    fc = _fc(g, table)
    kc = bt.kc["castIn" if cast else "postInstalled"]
    nb = kc * spec.lightweightFactor * math.sqrt(fc) * hef**bt.exponent
    if spec.kind in HEADED and bt.deepHefMin <= hef <= bt.deepHefMax:
        nb = max(
            nb, bt.deepCoefficient * spec.lightweightFactor * math.sqrt(fc) * hef**bt.deepExponent
        )
    factors = {
        "hef": hef,
        "ANc": anc,
        "ANco": anco,
        "psiEc": psi_ec,
        "psiEd": psi_ed,
        "psiC": psi_c,
        "psiCp": psi_cp,
        "Nb": nb,
    }
    return anc / anco * psi_ec * psi_ed * psi_c * psi_cp * nb, factors


def pullout(g: Group, table: Any) -> float | None:
    """Npn [N] of one anchor; None when it cannot be calculated (a post-installed anchor without
    its tested value)."""
    po = table.pullout
    spec = g.spec
    psi = po.uncracked if not spec.cracked else 1.0
    fc = _fc(g, table)
    if spec.kind in HEADED:
        return psi * po.headed * bearing_area(g, table) * fc
    if spec.kind == "hookedBolt":
        eh = spec.hookExtension or po.hookMax * g.diameter
        eh = min(eh, po.hookMax * g.diameter)
        return psi * po.hooked * fc * eh * g.diameter
    if spec.pulloutStrength:
        return psi * spec.pulloutStrength * 1e3
    return None


def side_face(g: Group, table: Any, idx: list[int], tensions: list[float]) -> list[tuple]:
    """Side-face blowout of headed anchors in tension deep near an edge: per edge,
    ``(demand [N], nominal strength [N], ca1)``."""
    if g.spec.kind not in HEADED:
        return []
    sf = table.sideFace
    hef = g.spec.embedment
    lam = g.spec.lightweightFactor
    fc = _fc(g, table)
    abrg = bearing_area(g, table)
    found = []
    for k in range(4):
        near = [(i, _distances(g, i)[k]) for i in idx if tensions[i] > 0]
        near = [(i, c) for i, c in near if hef > sf.deepRatio * c]
        if not near:
            continue
        ca1 = min(c for _, c in near)
        row = [i for i, c in near if c <= ca1 + 1.0]
        nsb = sf.coefficient * ca1 * math.sqrt(abrg) * lam * math.sqrt(fc)
        across = 1 if k < 2 else 0  # the axis along the edge
        if len(row) > 1:
            along = [g.points[i][across] for i in row]
            s = max(along) - min(along)
            if s < sf.groupSpacing * ca1:
                demand = sum(tensions[i] for i in row)
                found.append((demand, (1 + s / (sf.groupSpacing * ca1)) * nsb, ca1))
                continue
        for i in row:
            d = _distances(g, i)
            ca2 = min(d[2], d[3]) if k < 2 else min(d[0], d[1])
            n = nsb
            if ca2 < sf.cornerRatioMax * ca1:
                ratio = min(max(ca2 / ca1, 1.0), sf.cornerRatioMax)
                n *= (1 + ratio) / sf.cornerDivisor
            found.append((tensions[i], n, ca1))
    return found


# ─────────────────────────────────────── shear ───────────────────────────────────────


def breakout_shear(g: Group, table: Any, edge: int, row: list[int], eccentricity: float = 0.0):
    """Nominal shear breakout strength Vcbg [N] of the anchors ``row`` toward edge ``edge``
    (0: -x, 1: +x, 2: -y, 3: +y), and the factors used."""
    bs = table.breakoutShear
    spec = g.spec
    proj = bs.projection
    ca1 = min(_distances(g, i)[edge] for i in row)
    side = (2, 3) if edge < 2 else (0, 1)
    ca2a = min(_distances(g, i)[side[0]] for i in row)
    ca2b = min(_distances(g, i)[side[1]] for i in row)
    ha = spec.memberThickness or INF
    if ca2a < proj * ca1 and ca2b < proj * ca1 and ha < proj * ca1:
        ca1 = min(ca1, max(ca2a / proj, ca2b / proj, ha / proj, _max_spacing(g, row) / 3))
    along = [g.points[i][1 if edge < 2 else 0] for i in row]
    width = max(along) - min(along) + min(proj * ca1, ca2a) + min(proj * ca1, ca2b)
    height = min(proj * ca1, ha)
    avco = bs.projectedArea * ca1**2
    avc = min(width * height, len(row) * avco)
    psi_ec = min(1.0, 1.0 / (1.0 + bs.eccentricity * eccentricity / ca1))
    ca2 = min(ca2a, ca2b)
    psi_ed = 1.0 if ca2 >= proj * ca1 else bs.edgeBase + bs.edgeSlope * ca2 / (proj * ca1)
    if not spec.cracked:
        psi_c = bs.uncracked
    else:
        psi_c = {
            "none": bs.crackedNoBar,
            "edgeBar": bs.crackedEdgeBar,
            "edgeBarStirrups": bs.crackedEdgeBarStirrups,
        }[spec.shearEdgeReinforcement]
    psi_h = max(1.0, math.sqrt(proj * ca1 / ha)) if math.isfinite(ha) else 1.0
    da = g.diameter
    le = min(spec.embedment, bs.bearingLengthMax * da)
    coefficient = bs.coefficient
    if (
        spec.welded
        and spec.kind in CAST_IN
        and (g.attachment_thickness or 0) >= max(bs.weldedMinThickness, da / 2)
        and _min_spacing(g) >= bs.weldedMinSpacing
    ):
        coefficient = bs.weldedCoefficient
    fc = _fc(g, table)
    vb = (
        coefficient
        * (le / da) ** bs.lengthExponent
        * math.sqrt(da)
        * spec.lightweightFactor
        * math.sqrt(fc)
        * ca1**bs.exponent
    )
    factors = {
        "ca1": ca1,
        "AVc": avc,
        "AVco": avco,
        "psiEc": psi_ec,
        "psiEd": psi_ed,
        "psiC": psi_c,
        "psiH": psi_h,
        "Vb": vb,
    }
    return avc / avco * psi_ec * psi_ed * psi_c * psi_h * vb, factors


def _shear_cases(g: Group) -> list[tuple[int, list[int], float]]:
    """``(edge, anchors, share of the shear)``: toward each near edge, the row nearest it with
    its share and the farthest row with all of it."""
    n = len(g.points)
    cases = []
    for edge in range(4):
        if not math.isfinite(g.edges[edge]):
            continue
        dist = [_distances(g, i)[edge] for i in range(n)]
        near, far = min(dist), max(dist)
        front = [i for i in range(n) if dist[i] <= near + 1.0]
        cases.append((edge, front, len(front) / n))
        if far > near + 1.0:
            back = [i for i in range(n) if dist[i] >= far - 1.0]
            cases.append((edge, back, 1.0))
    return cases


# ─────────────────────────────────────── the checks ───────────────────────────────────────


def check_group(
    g: Group, demands: list[Demand], seismic: SeismicContext | None = None
) -> dict[str, Any]:
    """The checks of the anchor group under ``demands``: ``{"covered", "checks",
    "assumptions", "source"}`` (see the module)."""
    table = anchors_table()
    if table is None:
        return {
            "covered": False,
            "checks": [],
            "assumptions": [
                f"anchorage in the concrete: not covered by the code pack {pack_name()}"
            ],
            "source": "",
        }
    spec = g.spec
    n = len(g.points)
    phi = table.phi
    cond = _condition(g)
    ductile = spec.ductile
    phi_st = phi.steelTensionDuctile if ductile else phi.steelTensionBrittle
    phi_sv = phi.steelShearDuctile if ductile else phi.steelShearBrittle
    phi_ct = _phi_tension(g, table, cond)
    phi_ct_b = _phi_tension(g, table, "B")
    phi_cv = float(getattr(phi.concreteShear, cond))
    phi_cv_b = float(phi.concreteShear.B)
    sd = table.seismic

    futa = min(g.fu, table.steel.futaOfFya * g.fy, table.steel.futaMax)
    ase = effective_area(g, table)
    nsa = ase * futa
    shear_coef = table.steel.shearStud if spec.kind == "headedStud" else table.steel.shearBolt
    vsa = shear_coef * ase * futa * (table.steel.groutPad if spec.groutPad else 1.0)
    np_ = pullout(g, table)
    everyone = list(range(n))
    ncbg_all, _ = breakout_tension(g, table, everyone)
    kcp = table.pryout.kcpShort if spec.embedment < table.pryout.shortHef else table.pryout.kcpLong
    ar_t = (
        table.phi.anchorReinforcement * spec.anchorReinforcementTension * spec.anchorReinforcementFy
    )
    ar_v = (
        table.phi.anchorReinforcement * spec.anchorReinforcementShear * spec.anchorReinforcementFy
    )

    modes = {
        "steelT": _Mode("anchor steel in tension (per anchor)", "kN",
                        f"{cite(table, 'steelTension')}: φ Ase,N futa, futa = {futa:.0f} MPa",
                        "tension", False),
        "breakoutT": _Mode("concrete breakout in tension (anchors in tension)", "kN",
                           cite(table, "breakoutTension"), "tension", True),
        "reinforcementT": _Mode("anchor reinforcement for tension", "kN",
                                cite(table, "anchorReinforcement"), "tension", False),
        "pullout": _Mode("pullout (per anchor)", "kN", cite(table, "pullout"), "tension", True),
        "sideFace": _Mode("side-face blowout", "kN", cite(table, "sideFace"), "tension", True),
        "steelV": _Mode("anchor steel in shear (per anchor)", "kN",
                        cite(table, "steelShear")
                        + (", with the grout pad factor" if spec.groutPad else ""),
                        "shear", False),
        "breakoutV": _Mode("concrete breakout in shear (toward an edge)", "kN",
                           cite(table, "breakoutShear"), "shear", True),
        "reinforcementV": _Mode("anchor reinforcement for shear", "kN",
                                cite(table, "anchorReinforcement"), "shear", False),
        "pryout": _Mode("concrete pryout", "kN", f"{cite(table, 'pryout')}: kcp = {kcp:g}",
                        "shear", True),
    }  # fmt: skip
    shear_cases = _shear_cases(g)
    any_seismic = False
    for key, d in enumerate(demands):
        quake = seismic is not None and seismic.applies(table, d.combination)
        any_seismic = any_seismic or quake
        factor = sd.concreteFactor if quake else 1.0
        if quake and spec.seismicDesign == "reducedStrength":
            factor *= sd.reducedFactor
        elif quake and spec.seismicDesign == "studWall":
            factor *= sd.studWallFactor
        tensions = [max(t, 0.0) for t in d.tensions]
        loaded = [i for i in everyone if tensions[i] > 0]
        comb = d.combination
        if loaded:
            tmax = max(tensions)
            modes["steelT"].add(key, comb, tmax / 1e3, phi_st * nsa / 1e3)
            total = sum(tensions[i] for i in loaded)
            if ar_t > 0:
                modes["reinforcementT"].add(key, comb, total / 1e3, ar_t / 1e3)
            else:
                ncbg, _ = breakout_tension(g, table, loaded, tensions)
                modes["breakoutT"].add(key, comb, total / 1e3, factor * phi_ct * ncbg / 1e3)
            if np_ is not None:
                modes["pullout"].add(key, comb, tmax / 1e3, factor * phi_ct_b * np_ / 1e3)
            for demand, nominal, _ in side_face(g, table, loaded, tensions):
                modes["sideFace"].add(key, comb, demand / 1e3, factor * phi_ct * nominal / 1e3)
        v = abs(d.shear)
        if v > 0:
            modes["steelV"].add(key, comb, v / n / 1e3, phi_sv * vsa / 1e3)
            if ar_v > 0:
                modes["reinforcementV"].add(key, comb, v / 1e3, ar_v / 1e3)
            else:
                for edge, row, share in shear_cases:
                    vcbg, _ = breakout_shear(g, table, edge, row, d.shear_eccentricity)
                    modes["breakoutV"].add(key, comb, share * v / 1e3, factor * phi_cv * vcbg / 1e3)
            modes["pryout"].add(key, comb, v / 1e3, factor * phi_cv_b * kcp * ncbg_all / 1e3)

    checks: list[dict[str, Any]] = []
    for mode in modes.values():
        if mode.utilisation >= 0:
            checks.append(
                _check(mode.name, mode.demand, mode.capacity, mode.unit, mode.combination,
                       mode.note)
            )  # fmt: skip

    # Interaction of tension and shear (trilinear).
    it = table.interaction
    worst = None
    for key, d in enumerate(demands):
        un = max((m.per_combination.get(key, 0.0) for m in modes.values()
                  if m.side == "tension"), default=0.0)  # fmt: skip
        uv = max((m.per_combination.get(key, 0.0) for m in modes.values()
                  if m.side == "shear"), default=0.0)  # fmt: skip
        if un > it.threshold and uv > it.threshold and (worst is None or un + uv > worst[0]):
            worst = (un + uv, d.combination)
    if worst is not None:
        checks.append(
            _check("tension and shear interaction", worst[0], it.limit, "", worst[1],
                   f"{cite(table, 'interaction')}: Nua/φNn + Vua/φVn <= {it.limit:g}")
        )  # fmt: skip

    # Seismic ductility (the steel of a ductile anchor governs).
    assumptions: list[str] = []
    if any_seismic:
        assumptions.append(
            f"earthquake combinations in Seismic Design Category {seismic.category}: the "
            f"concrete modes × {sd.concreteFactor:g} ({cite(table, 'seismic')}); anchors are "
            "not in a plastic hinge zone"
        )
        if spec.seismicDesign == "ductileSteel":
            for side, steel_key in (("tension", "steelT"), ("shear", "steelV")):
                steel = modes[steel_key]
                concrete = [m for m in modes.values() if m.side == side and m.concrete
                            and m.utilisation >= 0]  # fmt: skip
                if steel.utilisation <= 0 or not concrete:
                    continue
                uc = max(m.utilisation for m in concrete)
                checks.append(
                    _check(
                        f"ductile steel governs in {side} (earthquake)",
                        uc,
                        steel.utilisation if ductile else 0.0,
                        "",
                        None,
                        f"{cite(table, 'seismic')}: the concrete modes' utilisation within "
                        "the anchor steel's" + ("" if ductile else "; the anchor is not ductile"),
                    )
                )
        elif spec.seismicDesign == "yieldingAttachment":
            assumptions.append(
                "earthquake: the attachment yields at anchor forces within their design "
                "strength (stated by the designer, not checked)"
            )
        else:
            f = sd.reducedFactor if spec.seismicDesign == "reducedStrength" else sd.studWallFactor
            assumptions.append(f"earthquake: the concrete modes' design strength × {f:g} more")

    # Spacing, edges, depth and the method's range.
    checks += _rules(g, table)
    if np_ is None and any(max(d.tensions or [0.0]) > 0 for d in demands):
        assumptions.append(
            "pullout of the post-installed anchor not checked: enter the product's tested Np"
        )
    if not spec.headBearingArea and spec.kind in HEADED:
        assumptions.append(
            f"head bearing area Abrg {bearing_area(g, table):.0f} mm² estimated from a hex nut "
            "(SAEngine practice; enter the nut or washer's own)"
        )
    if spec.anchorReinforcementTension > 0 or spec.anchorReinforcementShear > 0:
        assumptions.append(
            "anchor reinforcement developed on both sides of the breakout surface replaces the "
            "breakout strength"
        )
    assumptions.append(
        "the shear toward each concrete edge in turn (its direction is not known), shared by "
        "the front row or taken whole by the back row; shear parallel to an edge not credited"
    )
    if spec.cracked:
        assumptions.append("cracked concrete (no service-load analysis shows otherwise)")
    return {"covered": True, "checks": checks, "assumptions": assumptions,
            "source": table.source}  # fmt: skip


def _rules(g: Group, table: Any) -> list[dict[str, Any]]:
    spec = g.spec
    sp = table.spacing
    da = g.diameter
    cast = spec.kind in CAST_IN
    found = []
    smin = _min_spacing(g)
    if math.isfinite(smin):
        factor = sp.untorquedCastIn if cast and not spec.torqued else sp.torqued
        found.append(
            _check("anchor spacing", factor * da, smin, "mm", None,
                   f"{cite(table, 'spacing')}: at least {factor:g} da")
        )  # fmt: skip
    camin = min(min(_distances(g, i)) for i in range(len(g.points)))
    if math.isfinite(camin):
        if cast:
            need = sp.edgeTorquedCastIn * da if spec.torqued else spec.cover
        else:
            need = max(spec.cover, sp.edgePostInstalled.get(spec.kind, 0.0) * da)
        found.append(
            _check("anchor edge distance", need, camin, "mm", None, cite(table, "spacing"))
        )
    ap = table.applicability
    found.append(
        _check("anchor diameter within the method's range", da, ap.diameterMax, "mm", None,
               cite(table, "applicability"))
    )  # fmt: skip
    found.append(
        _check("embedment within the method's range", spec.embedment, ap.embedmentMax, "mm",
               None, cite(table, "applicability"))
    )  # fmt: skip
    if not cast and spec.memberThickness:
        ha = spec.memberThickness
        limit = max(sp.postInstalledDepthShare * ha, ha - sp.postInstalledDepthLess)
        found.append(
            _check("post-installed embedment in the member", spec.embedment, limit, "mm", None,
                   cite(table, "postInstalledDepth"))
        )  # fmt: skip
    if spec.kind == "hookedBolt":
        po = table.pullout
        eh = spec.hookExtension or po.hookMax * da
        found.append(
            _check("hook extension eh", po.hookMin * da, eh, "mm", None,
                   f"{cite(table, 'pullout')}: eh >= {po.hookMin:g} da")
        )  # fmt: skip
    return found
