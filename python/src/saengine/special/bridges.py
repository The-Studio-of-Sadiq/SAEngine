"""Girder bridges: dead loads, the traffic's envelope, the girders' checks, bearings, expansion
joints and load rating (Project Settings → Bridges and Special Structures).

Model. The spans are simply supported (each its own girder line) or continuous (one line over
knife-edge supports). The traffic is shared among the girders either

- by the rigid cross-section (Courbon, ``analysis`` "lineGirder"): a lane at e from the girders'
  centroid gives girder i the share 1/n + e·yi/Σy² of the line girder's influence lines, or
- by a deck grillage (``analysis`` "grillage", :class:`saengine.library.shapes.DeckGrillage`):
  girders of the tee section and transverse deck strips (the station spacing wide, the deck
  slab's thickness deep, torsion b t³/6), on the bearings of each support line (fixed: held in
  plan both ways; guided: across only; free: vertically only), solved by OpenSees for a unit
  load at every girder node (:mod:`saengine.special.frame`). A wheel between two girders is
  shared between them by the lever rule (beyond the outer girders, all to the outer one); the
  lane loads are averaged across the lane's width.

The lanes are placed side by side from either kerb (both arrangements tried), each lane's loads
on its centre line (the wheels at ± half the gauge). The dead loads are shared equally among the
girders: the girder's web and its share of the deck slab and barriers (DC), the wearing surface
(DW).

Checks (the pack's ``bridgeDesign``, else SAEngine practice; resistances by the pack's concrete
methods, :mod:`saengine.design.rc` and :mod:`saengine.design.prestress`):

- flexure: Mu = γDC MDC + γDW MDW + γLL M(LL+IM) at every station, against the tee's design
  moment (sagging: the effective flange width as a rectangle, the neutral axis checked to stay in
  the flange; hogging over the supports: the web with the top bars);
- shear at the supports' first stations: Vu against the web's design shear with its stirrups
  (prestressing left out: on the safe side);
- prestressed girders: the stresses at transfer (Pi, the girder's own weight) and at service
  (Pe, the permanent loads; then with the traffic, × the pack's tension factor for the tension)
  against the pack's limits, and the strength with fps of bonded strands;
- bearings: each support line's reactions per girder, service and factored, and uplift;
- expansion joints: the deck's movement α ΔT L from the fixed bearings (L to the joint);
- load rating (``rating`` set): RF = (C - γDC DC - γDW DW) / (γL (LL + IM)) at the inventory
  and operating levels for flexure and shear, C = φc φs φRn (φc φs at least the pack's least).

Not covered (stated in the results): the deck slab's own design, the girders' fatigue,
deflection and staged (non-composite) construction, cracking of reinforced girders, skew and
curved decks, cantilever overhangs, piers and abutments (Part 9 substructure), bearing and
joint product selection. Units: m, kN, kN·m, MPa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.special import moving_loads as ml

G = 9.80665
#: Largest element along a girder line for the influence lines [m].
LINE_STEP = 0.5
#: Largest element along a grillage girder [m] (a unit load at each of its nodes).
GRILLAGE_STEP = 1.0
#: A hogging envelope smaller than this share of the sagging one is numerical noise (a simply
#: supported girder has none): its check is left out as not applicable.
HOGGING_TOLERANCE = 0.01
#: Concrete unit weight when the material gives no density [kg/m³].
CONCRETE_DENSITY = 2400.0


@dataclass
class Row:
    """One check: demand against capacity."""

    name: str
    demand: float | None
    capacity: float | None
    unit: str
    note: str = ""
    ratio: float | None = None
    ok: bool | None = None

    def __post_init__(self) -> None:
        if self.ratio is None and self.demand is not None and self.capacity:
            self.ratio = abs(self.demand) / abs(self.capacity) if self.capacity else None
        if self.ok is None and self.ratio is not None:
            self.ok = self.ratio <= 1.0 + 1e-9

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "demand": None if self.demand is None else round(self.demand, 3),
            "capacity": None if self.capacity is None else round(self.capacity, 3),
            "unit": self.unit,
            "ratio": None if self.ratio is None else round(self.ratio, 3),
            "ok": self.ok,
            "note": self.note,
        }


# ───────────────────────────────────── sections ─────────────────────────────────────


@dataclass(frozen=True)
class TeeSection:
    """A girder with its flange [mm, mm², mm⁴]: area, centroid from the top, second moment."""

    depth: float
    web: float
    flange: float
    slab: float

    @property
    def area(self) -> float:
        return self.flange * self.slab + self.web * (self.depth - self.slab)

    @property
    def top(self) -> float:
        """Centroid below the top [mm]."""
        af = self.flange * self.slab
        aw = self.web * (self.depth - self.slab)
        return (af * self.slab / 2 + aw * (self.slab + (self.depth - self.slab) / 2)) / self.area

    @property
    def inertia(self) -> float:
        h, t, yt = self.depth, self.slab, self.top
        af = self.flange * t
        aw = self.web * (h - t)
        return (
            self.flange * t**3 / 12
            + af * (yt - t / 2) ** 2
            + self.web * (h - t) ** 3 / 12
            + aw * (t + (h - t) / 2 - yt) ** 2
        )

    @property
    def lateral(self) -> float:
        return self.slab * self.flange**3 / 12 + (self.depth - self.slab) * self.web**3 / 12

    @property
    def torsion(self) -> float:
        """St Venant constant: the web b³h/3 (1 - 0.63 b/h) and half the flange's b t³/3."""
        hw = self.depth - self.slab
        b, h = min(self.web, hw), max(self.web, hw)
        web = b**3 * h / 3 * (1 - 0.63 * b / h)
        return web + self.flange * self.slab**3 / 6


def _material(materials: Any, material_id: str, what: str) -> Any:
    found = next((m for m in materials.materials if m.id == material_id), None)
    if found is None:
        raise ValueError(f"{what} material '{material_id}' is not in 03 Materials")
    return found


def unit_weight(material: Any) -> float:
    """[kN/m³]."""
    density = (material.mechanical.density if material.mechanical else None) or CONCRETE_DENSITY
    return density * G / 1000.0


# ───────────────────────────────────── the bridge's effects ─────────────────────────────────


@dataclass
class GirderEffects:
    """The effects along one girder of one segment (a simple span, or the continuous line):
    stations ``x`` [m]; dead load moments, shears and reactions (DC, DW, the girder's own
    weight alone); the traffic's envelope with its dynamic allowance (largest and least)."""

    girder: int
    segment: int
    x: np.ndarray
    supports: list[int]
    dc: dict[str, np.ndarray]
    dw: dict[str, np.ndarray]
    own: dict[str, np.ndarray]
    moment: tuple[np.ndarray, np.ndarray]
    shear: tuple[np.ndarray, np.ndarray]
    reaction: tuple[np.ndarray, np.ndarray]
    governing: dict[str, str] = field(default_factory=dict)


def _segments(bridge: Any) -> list[list[float]]:
    spans = [float(s) for s in bridge.spans]
    return [spans] if bridge.continuity == "continuous" else [[s] for s in spans]


def dead_loads(bridge: Any, concrete: Any) -> dict[str, float]:
    """Per girder [kN/m]: ``dc`` (web, slab share, barriers), ``dw`` (wearing surface), ``own``
    (the web alone)."""
    gamma = unit_weight(concrete)
    girder = bridge.girder
    t = bridge.deckThickness / 1000
    web = girder.webWidth / 1000 * max(girder.depth / 1000 - t, 0.0) * gamma
    deck = max(bridge.carriageway, bridge.girders * bridge.girderSpacing)
    slab = deck * t * gamma / bridge.girders
    barriers = 2 * bridge.barrier / bridge.girders
    dw = bridge.wearingSurface * bridge.carriageway / bridge.girders
    return {"dc": web + slab + barriers, "dw": dw, "own": web}


def girder_positions(bridge: Any) -> list[float]:
    """Girder lines across the bridge [m], centred on 0."""
    n = bridge.girders
    return [(k - (n - 1) / 2) * bridge.girderSpacing for k in range(n)]


def effects(bridge: Any, materials: Any, notes: list[str]) -> list[GirderEffects]:
    """The dead load and traffic effects of every girder of every segment."""
    traffic = ml.basis("movingLoads")
    concrete = _material(materials, bridge.girder.concrete, "concrete")
    loads = dead_loads(bridge, concrete)
    girders = girder_positions(bridge)
    table = traffic.table
    width = ml.lane_width(bridge.carriageway, table)
    arrangements = ml.lane_centres(bridge.carriageway, 0.0, table)
    notes.append(
        f"traffic: {traffic.label}: {ml.lane_count(bridge.carriageway, table)} lane(s) "
        f"{width:.2f} m wide{_cite(traffic, 'lanes')}; "
        + ", ".join(m.label for k, m in table.loadModels.items() if _wanted(bridge, k))
    )
    out: list[GirderEffects] = []
    for index, spans in enumerate(_segments(bridge)):
        longest = max(spans)
        dynamic, how = ml.dynamic_factor(table, longest, bridge.material)
        if index == 0 or bridge.continuity == "simple":
            notes.append(f"segment {index + 1} ({' + '.join(f'{s:g}' for s in spans)} m): {how}")
        dead = {k: ml.uniform_effects(spans, w, LINE_STEP) for k, w in loads.items()}
        if bridge.analysis == "grillage" and bridge.girders > 1:
            per_girder = _grillage_lanes(bridge, spans, materials, arrangements, width, notes)
        else:
            per_girder = _line_lanes(bridge, spans, girders, arrangements, width)
        cache: dict[Any, ml.LaneEffect] = {}
        for g, (x, supports, lanes_of) in enumerate(per_girder):
            fx = dead["dc"]["x"]
            moment = _envelopes(lanes_of["moment"], traffic, dynamic, bridge, cache, kind="moment")
            shear = _envelopes(lanes_of["shear"], traffic, dynamic, bridge, cache, kind="shear")
            interior = [0 < k < len(supports) - 1 for k in range(len(supports))]
            reaction = _envelopes(
                lanes_of["reaction"],
                traffic,
                dynamic,
                bridge,
                cache,
                kind="reaction",
                interior=interior,
            )
            out.append(
                GirderEffects(
                    girder=g,
                    segment=index,
                    x=x,
                    supports=supports,
                    dc={k: _on(fx, x, v) for k, v in dead["dc"].items() if k != "x"},
                    dw={k: _on(fx, x, v) for k, v in dead["dw"].items() if k != "x"},
                    own={k: _on(fx, x, v) for k, v in dead["own"].items() if k != "x"},
                    moment=moment[:2],
                    shear=shear[:2],
                    reaction=reaction[:2],
                    governing={"moment": moment[2], "shear": shear[2], "reaction": reaction[2]},
                )
            )
    return out


def _cite(basis_: ml.Basis, key: str) -> str:
    found = basis_.cite(key)
    return f" ({found})" if found else ""


def _wanted(bridge: Any, key: str) -> bool:
    return not bridge.loadModels or key in bridge.loadModels


def _on(fine: np.ndarray, coarse: np.ndarray, values: np.ndarray) -> np.ndarray:
    """``values`` at ``fine`` stations taken at the ``coarse`` stations (the same grid or a
    subset: interpolated). Reactions (one per support) are kept as they are."""
    if len(values) != len(fine):
        return np.asarray(values, dtype=float)
    if len(fine) == len(coarse) and np.allclose(fine, coarse):
        return np.asarray(values, dtype=float)
    return np.interp(coarse, fine, values)


def _envelopes(
    points: list[list[ml.Lane]],
    traffic: ml.Basis,
    dynamic: float,
    bridge: Any,
    cache: dict[Any, ml.LaneEffect],
    kind: str,
    interior: list[bool] | None = None,
) -> tuple[np.ndarray, np.ndarray, str]:
    """The (largest, least) traffic effect at each point, its lanes in every arrangement, and
    the governing load model of the largest magnitude."""
    models = list(bridge.loadModels) or None
    high = np.zeros(len(points))
    low = np.zeros(len(points))
    label, worst = "", 0.0
    for k, arrangements in enumerate(points):
        for lanes in arrangements:
            hogging = (
                (kind == "reaction" and bool(interior and interior[k])),
                kind == "moment",
            )
            up, down = ml.envelope(lanes, traffic, dynamic, hogging, models, cache)
            high[k] = max(high[k], up.value)
            low[k] = min(low[k], down.value)
            for found in (up, down):
                if abs(found.value) > worst:
                    worst = abs(found.value)
                    label = f"{found.model}, {found.lanes} lane(s)"
    return high, low, label


def _line_lanes(
    bridge: Any,
    spans: list[float],
    girders: list[float],
    arrangements: list[list[float]],
    width: float,
) -> list[tuple[np.ndarray, list[int], dict[str, list[list[ml.Lane]]]]]:
    """Each girder's lanes at each effect point, by the Courbon share of the line girder."""
    infl = ml.line_influence(spans, LINE_STEP)
    x = infl.x
    moments = [infl.moment[s].copy() for s in range(len(x))]
    shears = [
        (infl.shear_right[s] if s < len(x) - 1 else infl.shear_left[s]).copy()
        for s in range(len(x))
    ]
    reactions = [infl.reaction[k].copy() for k in range(len(infl.supports))]
    out = []
    for g in range(len(girders)):
        shares = [[ml.courbon_share(c, girders)[g] for c in lanes] for lanes in arrangements]

        def lanes_for(il: np.ndarray, shares: list[list[float]] = shares) -> list[list[ml.Lane]]:
            return [[(x, il, il, width, s) for s in row] for row in shares]

        out.append(
            (
                x,
                list(infl.supports),
                {
                    "moment": [lanes_for(il) for il in moments],
                    "shear": [lanes_for(il) for il in shears],
                    "reaction": [lanes_for(il) for il in reactions],
                },
            )
        )
    return out


# ───────────────────────────────────── grillage ─────────────────────────────────────


def grillage_shape(bridge: Any, spans: list[float]) -> Any:
    """The deck grillage of a segment (:class:`saengine.library.shapes.DeckGrillage`, mm)."""
    from saengine.library.shapes import DeckGrillage

    divisions = max(10, max(math.ceil(s / GRILLAGE_STEP) for s in spans))
    return DeckGrillage(
        spans=[s * 1000 for s in spans],
        girders=bridge.girders,
        girderSpacing=bridge.girderSpacing * 1000,
        divisions=divisions,
        memberType="GIRDER",
        crossType="DECK",
        supports="pinned",
    )


def bearing_fixity(bridge: Any, line: int) -> tuple[int, int, int, int, int, int]:
    """The DOFs a bearing of support line ``line`` holds (ux along the bridge, uy across)."""
    kinds = {b.support: b.kind for b in bridge.bearings}
    kind = kinds.get(line, "fixed" if line == 0 else "guided")
    rx = 1 if bridge.girders == 1 else 0  # one girder: its supports hold its twist
    if kind == "fixed":
        return (1, 1, 1, rx, 0, 0)
    if kind == "guided":
        return (0, 1, 1, rx, 0, 0)
    return (0, 0, 1, rx, 0, 0)


def _grillage_lanes(
    bridge: Any,
    spans: list[float],
    materials: Any,
    arrangements: list[list[float]],
    width: float,
    notes: list[str],
) -> list[tuple[np.ndarray, list[int], dict[str, list[list[ml.Lane]]]]]:
    """Each girder's lanes at each effect point from the grillage's influence surfaces."""
    from saengine.special import frame as fr

    shape = grillage_shape(bridge, spans)
    concrete = _material(materials, bridge.girder.concrete, "concrete")
    e = (concrete.mechanical.E or 4700 * math.sqrt(concrete.concrete.fc)) * 1e6
    nu = concrete.mechanical.nu or 0.2
    tee = _tee(bridge)
    girder = fr.Section(
        tee.area * 1e-6,
        tee.inertia * 1e-12,
        tee.lateral * 1e-12,
        tee.torsion * 1e-12,
        e,
        e / (2 * (1 + nu)),
    )
    xs = [v / 1000 for v in shape.stations()]
    strip = xs[1] - xs[0]
    t = bridge.deckThickness / 1000
    deck = fr.Section(
        strip * t, strip * t**3 / 12, t * strip**3 / 12, strip * t**3 / 6, e, e / (2 * (1 + nu))
    )
    geometry = shape.local()
    frame = fr.Frame()
    for m in geometry.members:
        frame.member(m.start / 1000, m.end / 1000, girder if m.type == "GIRDER" else deck)
    ys = [k * bridge.girderSpacing for k in range(bridge.girders)]
    lines = [v / 1000 for v in shape.support_lines()]
    held_y = 0
    for k, xl in enumerate(lines):
        fix = bearing_fixity(bridge, k)
        for y in ys:
            frame.support((xl, y, 0.0), fix)
            held_y += fix[1]
    if not any(bearing_fixity(bridge, k)[0] for k in range(len(lines))):
        frame.support((lines[0], ys[0], 0.0), (1, 1, 1, 0, 0, 0))
        notes.append("grillage: no bearing holds the deck along the bridge; one is held there")
    if held_y < 2:
        frame.support((lines[-1], ys[0], 0.0), (0, 1, 1, 0, 0, 0))
        notes.append("grillage: a second bearing is held across the bridge for stability")
    node = [[frame.node((xv, y, 0.0)) for xv in xs] for y in ys]
    member_of = {(i, j): k for k, (i, j, _) in enumerate(frame.members)}
    cases = {}
    for g in range(len(ys)):
        for s in range(len(xs)):
            loads = fr.Loads()
            loads.add_nodal(node[g][s], [0, 0, -1000.0])
            cases[f"{g}:{s}"] = loads
    results = fr.solve(frame, cases)
    ng, ns, nl = len(ys), len(xs), len(lines)
    support_station = [int(np.argmin([abs(xv - xl) for xv in xs])) for xl in lines]
    moment = np.zeros((ng, ns, ng, ns))  # effect girder, station; load girder, station
    shear = np.zeros((ng, ns, ng, ns))
    reaction = np.zeros((ng, nl, ng, ns))
    for gl in range(ng):
        for sl in range(ns):
            res = results[f"{gl}:{sl}"]
            for g in range(ng):
                for s in range(ns):
                    left = member_of.get((node[g][s - 1], node[g][s])) if s > 0 else None
                    right = member_of.get((node[g][s], node[g][s + 1])) if s < ns - 1 else None
                    values = []
                    if left is not None:
                        values.append(-res.forces[left, 10])
                    if right is not None:
                        values.append(res.forces[right, 4])
                    moment[g, s, gl, sl] = float(np.mean(values)) / 1000 if values else 0.0
                    if right is not None:
                        shear[g, s, gl, sl] = res.forces[right, 2] / 1000
                    elif left is not None:
                        shear[g, s, gl, sl] = -res.forces[left, 8] / 1000
                for k, st in enumerate(support_station):
                    r = res.reactions.get(node[g][st])
                    reaction[g, k, gl, sl] = float(r[2]) / 1000 if r is not None else 0.0
    x = np.array(xs)
    out = []
    for g in range(ng):
        lanes_of: dict[str, list[list[ml.Lane]]] = {"moment": [], "shear": [], "reaction": []}
        for kind, surface, count in (
            ("moment", moment, ns),
            ("shear", shear, ns),
            ("reaction", reaction, nl),
        ):
            for p in range(count):
                arrangements_out = []
                for centres in arrangements:
                    lanes = []
                    for c in centres:
                        y0 = c + (bridge.girders - 1) * bridge.girderSpacing / 2  # to the grid
                        gauge = _lane_gauge(bridge)
                        wheel = 0.5 * (
                            _across(surface[g, p], ys, y0 - gauge / 2)
                            + _across(surface[g, p], ys, y0 + gauge / 2)
                        )
                        area = np.mean(
                            [
                                _across(surface[g, p], ys, y0 + f * width)
                                for f in (-0.4, -0.2, 0, 0.2, 0.4)
                            ],
                            axis=0,
                        )
                        lanes.append((x, wheel, area, width, 1.0))
                    arrangements_out.append(lanes)
                lanes_of[kind].append(arrangements_out)
        out.append((x, list(support_station), lanes_of))
    notes.append(
        f"grillage: {ng} girders × {ns} stations, transverse deck strips {strip:.2f} m wide, "
        f"{len(cases)} unit load cases (OpenSees)"
    )
    return out


def _lane_gauge(bridge: Any) -> float:
    """The wheel gauge of the pack's vehicles (the widest), for the wheel lines of a lane."""
    table = ml.basis("movingLoads").table
    return max((float(v.gauge) for v in table.vehicles.values()), default=1.8)


def _across(surface: np.ndarray, ys: list[float], y: float) -> np.ndarray:
    """The influence line along the deck of a load at ``y`` across it: the surface's girder
    lines shared by the lever rule (all on the outer girder beyond it)."""
    if y <= ys[0]:
        return surface[0]
    if y >= ys[-1]:
        return surface[-1]
    k = int(np.searchsorted(ys, y)) - 1
    t = (y - ys[k]) / (ys[k + 1] - ys[k])
    return (1 - t) * surface[k] + t * surface[k + 1]


# ───────────────────────────────────── checks ─────────────────────────────────────


def _tee(bridge: Any) -> TeeSection:
    g = bridge.girder
    flange = g.flangeWidth or bridge.girderSpacing * 1000
    return TeeSection(float(g.depth), float(g.webWidth), float(flange), float(bridge.deckThickness))


def _bars(count: int, dia: float, width: float, inset: float, h: float, top: bool) -> list[Any]:
    """Bars in rows across ``width`` [mm] from the face (``top`` or bottom) of a section ``h``
    deep, centred on the section's axis."""
    from saengine.design.rc import Bar, bar_area

    if count <= 0:
        return []
    gap = max(25.0, dia)
    per_row = max(1, int((width - 2 * inset + gap) // (dia + gap)))
    out = []
    placed = 0
    row = 0
    while placed < count:
        n = min(per_row, count - placed)
        y = h / 2 - inset - dia / 2 - row * (dia + gap)
        y = y if top else -y
        half = width / 2 - inset - dia / 2
        xs = [0.0] if n == 1 else list(np.linspace(-half, half, n))
        out += [Bar(float(xv), float(y), bar_area(dia), dia) for xv in xs]
        placed += n
        row += 1
    return out


def rc_resistances(bridge: Any, materials: Any) -> dict[str, Any]:
    """The girder's design moments (sagging, hogging) [kN·m], design shear [kN] and notes."""
    from saengine.design import rc
    from saengine.library.objects import RectangleProfile

    g = bridge.girder
    concrete = _material(materials, g.concrete, "concrete")
    steel = _material(materials, g.rebar, "rebar")
    fc = float(concrete.concrete.fc)
    fy = float(steel.steel.fy)
    tee = _tee(bridge)
    inset = g.cover + g.stirrupDiameter
    notes: list[str] = []
    bottom = _bars(g.bottomBars, g.bottomDiameter, tee.web, inset, tee.depth, top=False)
    top = _bars(g.topBars, g.topDiameter, tee.web, inset, tee.depth, top=True)
    sag = rc.RcSection(
        RectangleProfile(xDim=tee.flange, yDim=tee.depth), tuple(bottom + top), fc, fy
    )
    web = rc.RcSection(RectangleProfile(xDim=tee.web, yDim=tee.depth), tuple(bottom + top), fc, fy)
    out: dict[str, Any] = {"notes": notes, "fc": fc, "fy": fy}
    if bottom:
        f = rc.flexure(sag, hogging=False)
        out["sagging"] = f.phi_mn / 1e6
        d = sag.effective_depth(top=False)
        c = d * rc.eps_cu(fc) / (rc.eps_cu(fc) + f.eps_t) if math.isfinite(f.eps_t) else 0.0
        if c > tee.slab:
            notes.append(
                f"the neutral axis ({c:.0f} mm) is below the deck slab ({tee.slab:.0f} mm): the "
                "flange-wide rectangle overstates the sagging resistance"
            )
    else:
        out["sagging"] = 0.0
    out["hogging"] = rc.flexure(web, hogging=True).phi_mn / 1e6 if top else 0.0
    try:
        v = rc.shear(web, g.stirrupDiameter, g.stirrupLegs, g.stirrupSpacing)
        out["shear"] = v.phi_vn / 1e3
    except rc.DesignError as error:
        out["shear"] = None
        notes.append(f"shear not checked: {error}")
    return out


def _design_basis() -> ml.Basis:
    return ml.basis("bridgeDesign")


def check_bridge(bridge: Any, materials: Any) -> dict[str, Any]:
    """The bridge's results: ``rows`` (checks), ``bearings``, ``joints``, ``rating``, ``chart``
    (the envelope of the first interior girder's moments) and ``notes``."""
    notes: list[str] = []
    found = effects(bridge, materials, notes)
    design = _design_basis()
    t = design.table
    rows: list[Row] = []
    resist = rc_resistances(bridge, materials)
    notes += resist["notes"]
    prestressed = bridge.girder.prestress is not None
    if prestressed:
        psc = prestress_checks(bridge, materials, found, t, notes)
        rows += psc["rows"]
        sagging_capacity = psc["strength"]
    else:
        sagging_capacity = resist["sagging"]
    f = t.strength
    worst: dict[str, Any] = {}
    for eff in found:
        dead = f.dc * eff.dc["moment"] + f.dw * eff.dw["moment"]
        mu_pos = dead + f.ll * eff.moment[0]
        mu_neg = dead + f.ll * eff.moment[1]
        k_pos = int(np.argmax(mu_pos))
        k_neg = int(np.argmin(mu_neg))
        if mu_pos[k_pos] > worst.get("pos", (0.0,))[0]:
            worst["pos"] = (float(mu_pos[k_pos]), eff, k_pos)
        if mu_neg[k_neg] < worst.get("neg", (0.0,))[0]:
            worst["neg"] = (float(mu_neg[k_neg]), eff, k_neg)
        for s in eff.supports:
            dead_v = f.dc * _support_shear(eff.dc, s) + f.dw * _support_shear(eff.dw, s)
            live_v = max(abs(eff.shear[0][s]), abs(eff.shear[1][s]))
            vu = abs(dead_v) + f.ll * live_v
            if vu > worst.get("shear", (0.0,))[0]:
                worst["shear"] = (float(vu), eff, s)
    strength = design.cite("strength")
    if "pos" in worst:
        mu, eff, k = worst["pos"]
        note = f"{_factors(f)}{_paren(strength)}; {eff.governing.get('moment', '')}"
        name = f"Girder {eff.girder + 1}: sagging moment at x = {eff.x[k]:.1f} m"
        rows.append(Row(name, mu, sagging_capacity, "kN·m", note))
    # W4C-14: a simply supported girder has no hogging (the least envelope is ~0 against the
    # sagging one): no hogging row with a zero capacity, a note instead.
    sagging = worst.get("pos", (0.0,))[0]
    if "neg" in worst and -worst["neg"][0] <= HOGGING_TOLERANCE * max(sagging, 1.0):
        del worst["neg"]
    if "neg" not in worst:
        notes.append("hogging: not applicable (the moment envelope has no negative moment)")
    if "neg" in worst:
        mu, eff, k = worst["neg"]
        name = f"Girder {eff.girder + 1}: hogging moment at x = {eff.x[k]:.1f} m"
        capacity = -resist["hogging"] if resist["hogging"] else 0.0
        note = "over the supports by the web with the top bars"
        if not bridge.girder.topBars:
            note += "; no top bars given"
        rows.append(Row(name, mu, capacity, "kN·m", note, ok=False if not capacity else None))
    if "shear" in worst:
        vu, eff, k = worst["shear"]
        name = f"Girder {eff.girder + 1}: shear at the support (x = {eff.x[k]:.1f} m)"
        note = "the web with its stirrups; prestress left out"
        rows.append(Row(name, vu, resist.get("shear"), "kN", note))
    bearings = bearing_rows(bridge, found, t)
    joints = joint_rows(bridge, t)
    rating = rating_rows(bridge, found, t, sagging_capacity, resist.get("shear"), notes)
    chart = _chart(found, bridge)
    notes.append(f"load factors: {design.label}; resistances by the pack's concrete methods")
    notes.append(
        "not covered: the deck slab's design, fatigue, deflection, staged construction, skew, "
        "cantilever overhangs, piers and abutments (9 Substructure)"
    )
    return {
        "rows": [r.as_dict() for r in rows],
        "bearings": bearings,
        "joints": joints,
        "rating": rating,
        "chart": chart,
        "notes": notes,
    }


def _support_shear(effects_: dict[str, np.ndarray], s: int) -> float:
    """The dead load shear beside support station ``s``: into the span (right of the first
    station, left of the last)."""
    right, left = effects_["shearRight"], effects_["shearLeft"]
    return float(right[s] if s < len(right) - 1 else left[s])


def _paren(text: str) -> str:
    return f" ({text})" if text else ""


def _factors(f: Any) -> str:
    return f"{f.dc:g} DC + {f.dw:g} DW + {f.ll:g} (LL + IM)"


def _chart(found: list[GirderEffects], bridge: Any = None) -> dict[str, Any]:
    """The traffic's moment and shear envelopes and the dead load moments along the most
    loaded girder of the first segment, and (with ``bridge``) the influence lines of that
    segment's girder line, for the results view."""
    first = [e for e in found if e.segment == 0]
    if not first:
        return {}
    eff = max(first, key=lambda e: float(np.max(e.moment[0])))
    out: dict[str, Any] = {
        "girder": eff.girder + 1,
        "x": [round(float(v), 3) for v in eff.x],
        "llMax": [round(float(v), 2) for v in eff.moment[0]],
        "llMin": [round(float(v), 2) for v in eff.moment[1]],
        "dc": [round(float(v), 2) for v in eff.dc["moment"]],
        "dw": [round(float(v), 2) for v in eff.dw["moment"]],
    }
    if len(eff.shear[0]) == len(eff.x):
        out["vMax"] = [round(float(v), 2) for v in eff.shear[0]]
        out["vMin"] = [round(float(v), 2) for v in eff.shear[1]]
    if bridge is not None:
        out["influence"] = influence_chart(_segments(bridge)[0])
    return out


def influence_chart(spans: list[float]) -> dict[str, Any]:
    """W4C-14: the influence lines of a girder line over ``spans`` [m] for the results view:
    the moment at the middle of the first span, the moment over the first interior support
    (continuous spans) and the first support's reaction, each for a unit load moving along."""
    il = ml.line_influence(spans, LINE_STEP)
    x = il.x
    mid = int(np.argmin(np.abs(x - spans[0] / 2)))
    lines = [
        {"name": f"M at x = {x[mid]:.1f} m [kN·m/kN]", "values": il.moment[mid]},
    ]
    if len(il.supports) > 2:
        s = il.supports[1]
        lines.append(
            {"name": f"M over the support at x = {x[s]:.1f} m [kN·m/kN]", "values": il.moment[s]}
        )
    lines.append({"name": "Reaction at x = 0 [kN/kN]", "values": il.reaction[0]})
    return {
        "x": [round(float(v), 3) for v in x],
        "lines": [
            {"name": line["name"], "values": [round(float(v), 4) for v in line["values"]]}
            for line in lines
        ],
    }


def bearing_rows(bridge: Any, found: list[GirderEffects], t: Any) -> list[dict[str, Any]]:
    """Each support line's largest bearing reactions [kN]: service (DC + DW + LL) largest and
    least, and factored."""
    out = []
    per_line: dict[int, dict[str, float]] = {}
    offset = 0
    lines_of: dict[int, list[int]] = {}
    for eff in found:
        lines_of.setdefault(eff.segment, list(range(len(eff.supports))))
    starts = {}
    for seg in sorted(lines_of):
        starts[seg] = offset
        offset += len(lines_of[seg]) - 1
    for eff in found:
        for k in range(len(eff.supports)):
            line = starts[eff.segment] + k
            dead = eff.dc["reaction"][k] + eff.dw["reaction"][k]
            entry = per_line.setdefault(line, {"max": 0.0, "min": math.inf, "factored": 0.0})
            entry["max"] = max(entry["max"], dead + eff.reaction[0][k])
            entry["min"] = min(entry["min"], dead + eff.reaction[1][k])
            entry["factored"] = max(
                entry["factored"],
                t.strength.dc * eff.dc["reaction"][k]
                + t.strength.dw * eff.dw["reaction"][k]
                + t.strength.ll * eff.reaction[0][k],
            )
    kinds = {b.support: b.kind for b in bridge.bearings}
    for line, entry in sorted(per_line.items()):
        kind = kinds.get(line, "fixed" if line == 0 else "guided")
        out.append(
            {
                "line": line,
                "kind": kind,
                "serviceMax": round(entry["max"], 1),
                "serviceMin": round(entry["min"], 1),
                "factored": round(entry["factored"], 1),
                "uplift": entry["min"] < 0,
            }
        )
    return out


def joint_rows(bridge: Any, t: Any) -> list[dict[str, Any]]:
    """The expansion joints' movement [mm] at the deck's ends (and, for simple spans, at every
    support line between spans): ± α ΔT L, L from the fixed bearings to the joint."""
    alpha = float(t.thermalCoefficient)
    spans = [float(s) for s in bridge.spans]
    lines = [0.0, *np.cumsum(spans).tolist()]
    kinds = {b.support: b.kind for b in bridge.bearings}
    fixed = [
        k for k in range(len(lines)) if kinds.get(k, "fixed" if k == 0 else "guided") == "fixed"
    ]
    out = []
    if bridge.continuity == "continuous":
        anchor = sum(lines[k] for k in fixed) / len(fixed) if fixed else 0.0
        for k in (0, len(lines) - 1):
            length = abs(lines[k] - anchor)
            out.append(
                {
                    "line": k,
                    "length": round(length, 2),
                    "movement": round(alpha * bridge.thermalRange * length * 1000, 1),
                }
            )
    else:
        for k, span in enumerate(spans):
            out.append(
                {
                    "line": k + 1,
                    "length": round(span, 2),
                    "movement": round(alpha * bridge.thermalRange * span * 1000, 1),
                }
            )
    return out


def rating_rows(
    bridge: Any,
    found: list[GirderEffects],
    t: Any,
    flexure: float,
    shear: float | None,
    notes: list[str],
) -> list[dict[str, Any]]:
    """Load rating factors (inventory, operating) for flexure and shear of the governing
    girder; empty when the bridge is not rated or the pack gives no rating factors."""
    if bridge.rating is None:
        return []
    r = t.rating
    if r is None:
        notes.append("load rating: not covered by the code pack (no rating factors)")
        return []
    phi_cs = max(bridge.rating.condition * bridge.rating.system, r.systemMin)
    gdw = r.dwMeasured if bridge.rating.wearingMeasured and r.dwMeasured else r.dw
    out = []
    best_m = max(found, key=lambda e: float(np.max(e.moment[0])))
    k = int(np.argmax(best_m.moment[0]))
    dc, dw, ll = best_m.dc["moment"][k], best_m.dw["moment"][k], best_m.moment[0][k]
    for level, gl in (("inventory", r.inventory), ("operating", r.operating)):
        if ll > 0:
            rf = (phi_cs * flexure - r.dc * dc - gdw * dw) / (gl * ll)
            out.append(
                {
                    "effect": "flexure",
                    "level": level,
                    "rf": round(float(rf), 3),
                    "at": round(float(best_m.x[k]), 2),
                    "girder": best_m.girder + 1,
                }
            )
    if shear:
        eff = max(found, key=lambda e: float(np.max(np.abs(e.shear[0]))))
        s = eff.supports[0]
        dc, dw = abs(_support_shear(eff.dc, s)), abs(_support_shear(eff.dw, s))
        ll = max(abs(eff.shear[0][s]), abs(eff.shear[1][s]))
        for level, gl in (("inventory", r.inventory), ("operating", r.operating)):
            if ll > 0:
                rf = (phi_cs * shear - r.dc * dc - gdw * dw) / (gl * ll)
                out.append(
                    {
                        "effect": "shear",
                        "level": level,
                        "rf": round(float(rf), 3),
                        "at": round(float(eff.x[s]), 2),
                        "girder": eff.girder + 1,
                    }
                )
    notes.append(
        f"load rating: RF = (φc φs φRn - γDC DC - γDW DW) / (γL (LL + IM)), φc φs = {phi_cs:.2f}, "
        f"γL {r.inventory:g} (inventory) and {r.operating:g} (operating)"
        + _paren(_design_basis().cite("rating"))
    )
    return out


# ───────────────────────────────────── prestressed girders ─────────────────────────────────


def _stress_limits(t: Any, notes: list[str]) -> dict[str, Any] | None:
    """The bridge table's prestressed limits, else the pack's building prestress limits."""
    if t.prestress is not None:
        p = t.prestress
        return {
            "transferCompression": p.transferCompression,
            "transferTension": p.transferTension,
            "permanentCompression": p.permanentCompression,
            "totalCompression": p.totalCompression,
            "serviceTension": p.serviceTension,
            "absolute": p.tensionForm == "absolute",
            "relaxedYield": p.relaxedYield,
        }
    from saengine.design import prestress

    try:
        lim = prestress.limits()
    except ValueError:
        notes.append("prestressed girder stresses: not covered by the code pack")
        return None
    notes.append("prestressed girder stresses: the pack's building prestress limits are used")
    return {
        "transferCompression": lim.transferCompression,
        "transferTension": lim.transferTension,
        "permanentCompression": lim.sustainedCompression,
        "totalCompression": lim.totalCompression,
        "serviceTension": lim.tensionClassU,
        "absolute": getattr(lim, "tensionForm", "root") == "absolute",
        "relaxedYield": 0.9,
    }


def prestress_checks(
    bridge: Any, materials: Any, found: list[GirderEffects], t: Any, notes: list[str]
) -> dict[str, Any]:
    """The prestressed girder's stresses at transfer and service at the section of the largest
    sagging moment, and its design moment [kN·m] with bonded strands."""
    from saengine.design import prestress

    g = bridge.girder
    p = g.prestress
    assert p is not None
    concrete = _material(materials, g.concrete, "concrete")
    steel = _material(materials, g.rebar, "rebar")
    fc = float(concrete.concrete.fc)
    fci = float(p.transferStrength or 0.7 * fc)
    fy = float(steel.steel.fy)
    tee = _tee(bridge)
    area, yt, inertia = tee.area, tee.top, tee.inertia
    yb = tee.depth - yt
    st, sb = inertia / yt, inertia / yb
    rows: list[Row] = []
    lim = _stress_limits(t, notes)
    jack = p.jacking * p.fpu * p.area  # N
    pi = jack * (1 - p.initialLoss)
    pe = jack * (1 - p.totalLoss)
    eff = max(found, key=lambda e: float(np.max(e.dc["moment"] + e.moment[0])))
    k = int(np.argmax(eff.dc["moment"] + eff.moment[0]))
    span = max(float(s) for s in bridge.spans)
    ecc = p.depth - yt  # below the centroid [mm]
    m_own = eff.own["moment"][k] * 1e6
    m_perm = (t.service.dc * eff.dc["moment"][k] + t.service.dw * eff.dw["moment"][k]) * 1e6
    m_live = t.service.ll * eff.moment[0][k] * 1e6
    m_tension = (t.tensionLive or t.service.ll) * eff.moment[0][k] * 1e6
    live_t = t.tensionLive or t.service.ll

    def stresses(force: float, moment: float) -> tuple[float, float]:
        top = force / area - force * ecc / st + moment / st
        bottom = force / area + force * ecc / sb - moment / sb
        return top, bottom

    def tension_cap(coefficient: float, strength: float) -> float:
        return coefficient if lim and lim["absolute"] else coefficient * math.sqrt(strength)

    where = f"girder {eff.girder + 1} at x = {eff.x[k]:.1f} m"
    if lim is not None:
        top, bottom = stresses(pi, m_own)
        rows.append(
            Row(
                f"Transfer, compression ({where})",
                max(top, bottom),
                lim["transferCompression"] * fci,
                "MPa",
                "Pi with the girder's weight",
            )
        )
        rows.append(
            Row(
                f"Transfer, tension ({where})",
                max(-min(top, bottom), 0.0),
                tension_cap(lim["transferTension"], fci),
                "MPa",
                "Pi with the girder's weight; above the limit needs bonded bars",
                ok=-min(top, bottom) <= tension_cap(lim["transferTension"], fci) + 1e-9,
            )
        )
        top, bottom = stresses(pe, m_perm)
        rows.append(
            Row(
                f"Service, permanent loads, compression ({where})",
                max(top, bottom),
                lim["permanentCompression"] * fc,
                "MPa",
                "Pe with DC + DW",
            )
        )
        top, bottom = stresses(pe, m_perm + m_live)
        rows.append(
            Row(
                f"Service, all loads, compression ({where})",
                max(top, bottom),
                lim["totalCompression"] * fc,
                "MPa",
                "Pe with DC + DW + LL + IM",
            )
        )
        _, bottom = stresses(pe, m_perm + m_tension)
        cap = tension_cap(lim["serviceTension"], fc)
        rows.append(
            Row(
                f"Service, tension ({where})",
                max(-bottom, 0.0),
                cap,
                "MPa",
                f"Pe with DC + DW + {live_t:g} (LL + IM)",
                ok=-bottom <= cap + 1e-9,
            )
        )
    fpy = (lim["relaxedYield"] if lim else 0.9) * p.fpu
    fse = jack * (1 - p.totalLoss) / p.area
    rho_p = p.area / (tee.flange * p.depth)
    bars = sum(
        b.area
        for b in _bars(
            g.bottomBars, g.bottomDiameter, tee.web, g.cover + g.stirrupDiameter, tee.depth, False
        )
    )
    d = tee.depth - g.cover - g.stirrupDiameter - g.bottomDiameter / 2
    try:
        fps = prestress.stress_at_strength(
            fse, p.fpu, fpy, fc, rho_p, span * 1000 / tee.depth, True
        )
    except ValueError:
        fps = p.fpu * (1 - 0.28 / 0.85 * rho_p * p.fpu / fc)
        notes.append("fps with γp 0.28 (SAEngine practice): the pack gives no prestress limits")
    strength = prestress.flexural_strength(p.area, fps, p.depth, bars, fy, d, fc, tee.flange)
    if strength.a > tee.slab:
        notes.append(
            f"prestressed strength: the stress block ({strength.a:.0f} mm) is deeper than the deck "
            "slab; the flange-wide rectangle overstates it"
        )
    notes.append(
        f"prestress: Pi = {pi / 1e3:.0f} kN, Pe = {pe / 1e3:.0f} kN, e = {ecc:.0f} mm, fps = "
        f"{fps:.0f} MPa" + _paren(_design_basis().cite("prestress"))
    )
    return {"rows": rows, "strength": strength.phi_mn / 1e6}
