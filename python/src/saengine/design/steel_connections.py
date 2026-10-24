"""Simple steel connections: basic strength checks, stated assumptions (BNBC 2020 Part 6
Chapter 10, Sec 10.10; LRFD).

Three connection types, set per object type (the ``connection`` field the integrator adds to
04 Objects' beam and brace types):

- ``finPlate``: a single plate welded to the support (both sides, fillet welds along its
  height) and bolted to the beam web with one vertical line of bolts. Checked for the beam
  end shear V: bolt shear with the eccentricity ``a`` (support face to bolt line) by the
  elastic method, bearing/tear-out on the plate and on the beam web, plate shear yielding and
  rupture, plate block shear, plate flexure at the bolt line, the welds (direct shear plus the
  moment V·a, elastic line method), and the bolt spacing, edge distances and weld sizes.
- ``endPlate``: a shear end plate welded to both sides of the beam web, bolted to the support
  with two vertical lines of bolts. Checked for V: bolt shear, bearing on the plate and on the
  support (``supportThickness``), plate shear yielding/rupture, block shear (two blocks), the
  web welds and the beam web along them, spacing, edges, weld sizes.
- ``gusset``: a brace end bolted to a gusset plate (``rows`` bolts along the brace in
  ``lines`` lines) welded to the frame. Angles and channels bolt through their connected leg /
  web; hollow and I braces are taken to have a tab plate (``tabThickness``) slotted in and
  welded with ``tabWelds`` fillet welds of ``tabWeldLength``. Checked for the brace tension
  and compression: bolt shear (``shearPlanes``), bearing/tear-out on the gusset and on the
  brace part, the Whitmore section in tension yielding and rupture, gusset block shear,
  gusset buckling on the Whitmore width (K = ``gussetK`` over ``gussetFreeLength``), the
  gusset-to-frame welds for the whole brace force and the tab welds.

Clauses read in BNBC 2020 (bnbc-2020-part2.pdf pages): bolt tension/shear 10.10.3.6 Eq
6.10.168, φ 0.75, Fnv Table 6.10.10 (p. 127, 130); bearing 10.10.3.10 Eq 6.10.173a, φ 0.75
(p. 132-133); holes Table 6.10.11, spacing 10.10.3.3 (2⅔ d), edges Table 6.10.12, maximum
edge 10.10.3.5 (p. 128-129); elements in tension 10.10.4.1 Eq 6.10.174-175 (An <= 0.85 Ag
for bolted splice plates), in shear 10.10.4.2 Eq 6.10.176-177, block shear 10.10.4.3 Eq
6.10.178, in compression 10.10.4.4 Eq 6.10.179 (p. 134-135) and flexural buckling 10.5.3 Eq
6.10.16-19 (p. 60); fillet welds: sizes Table 6.10.7 and maximum size (p. 116), strength
0.60 FEXX, φ 0.75, Eq 6.10.162-163 (p. 121-122).

From memory, to be checked against the code: the fillet throat 0.707 w; the net-hole
allowance dh + 2 mm; the Whitmore width (spread at 30°) and the gusset buckling factor K;
the elastic bolt-group and weld-line methods for eccentricity; plate flexure φ 0.9 Fy Z;
ISO 8.8 / 10.9 bolts taken as A325 / A490 (Table 6.10.10 lists ASTM grades only).

Not checked: prying, slip-critical design, coped beams and weld access holes, beam web local
buckling at copes, column web/flange local effects, the brace net section with shear lag
(a member check), gusset edge buckling, the interface forces of the uniform force method.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design.steel_proposal import SteelMaterial, compression_capacity
from saengine.library.objects import (  # the connection models live with the object types
    BraceGussetConnection,
    EndPlateConnection,
    FinPlateConnection,
    _Bolted,
)
from saengine.library.steel_sections import SteelSection

# ─────────────────────────────────────── data ───────────────────────────────────────

#: Table 6.10.10 nominal shear stress Fnv in bearing-type connections [MPa] (and Fnt).
BOLT_GRADES: dict[str, dict[str, float]] = {
    "A307": {"Fnt": 310, "Fnv": 165},
    "A325N": {"Fnt": 620, "Fnv": 330},  # threads not excluded from the shear planes
    "A325X": {"Fnt": 620, "Fnv": 414},  # threads excluded
    "A490N": {"Fnt": 780, "Fnv": 414},
    "A490X": {"Fnt": 780, "Fnv": 520},
}
#: ISO property classes stocked in Bangladesh, taken as their ASTM counterparts.
BOLT_ALIASES = {
    "8.8": "A325N",
    "8.8N": "A325N",
    "8.8X": "A325X",
    "10.9": "A490N",
    "10.9N": "A490N",
    "10.9X": "A490X",
}

# Table 6.10.11 standard hole diameters [mm]
_HOLES = {16: 18, 20: 22, 22: 24, 24: 27, 27: 30, 30: 33}
# Table 6.10.12 minimum edge distance, rolled edges or thermally cut edges [mm]
_EDGE_ROLLED = {16: 22, 20: 26, 22: 28, 24: 30, 27: 34, 30: 38, 36: 46}
_EDGE_SHEARED = {16: 28, 20: 34, 22: 38, 24: 42, 27: 48, 30: 52, 36: 64}

# ─────────────────────────────────────── helpers ───────────────────────────────────────


def _check(name, demand, capacity, unit, combination, note="", flag=False) -> dict[str, Any]:
    """A check in the design_report format (saengine.design.check._check)."""
    u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(demand), 2),
        "capacity": round(float(capacity), 2),
        "unit": unit,
        "utilisation": u,
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": flag,
    }


def _min_rule(name, provided, required, note) -> dict[str, Any]:
    """A detailing minimum (provided >= required) as a check: utilisation required/provided."""
    return _check(name, required, provided, "mm", None, note)


def _max_rule(name, provided, limit, note) -> dict[str, Any]:
    return _check(name, provided, limit, "mm", None, note)


def bolt_grade(grade: str) -> dict[str, float]:
    return BOLT_GRADES[BOLT_ALIASES.get(grade, grade)]


def hole_diameter(d: float) -> float:
    """Standard hole, Table 6.10.11."""
    return _HOLES.get(int(d), d + 3)


def net_hole(d: float) -> float:
    """Hole width taken off for net areas: dh + 2 mm (from memory, to be checked)."""
    return hole_diameter(d) + 2.0


def min_edge(d: float, sheared: bool = False) -> float:
    """Table 6.10.12."""
    table = _EDGE_SHEARED if sheared else _EDGE_ROLLED
    if int(d) in table:
        return table[int(d)]
    return (1.75 if sheared else 1.25) * d


def bolt_shear_capacity(grade: str, d: float, planes: int = 1) -> float:
    """φRn of one bolt in shear [N], Eq 6.10.168, φ 0.75."""
    return 0.75 * bolt_grade(grade)["Fnv"] * math.pi * d**2 / 4 * planes


def bearing_capacity(d: float, t: float, fu: float, lc: float) -> float:
    """φRn of one bolt hole in bearing/tear-out [N], Eq 6.10.173a, φ 0.75."""
    return 0.75 * min(1.2 * max(lc, 0.0) * t * fu, 2.4 * d * t * fu)


def bearing_line(d, t, fu, rows, pitch, end) -> float:
    """Σ bearing of a line of bolts loaded towards the end distance ``end`` (None: no edge
    close by, the 2.4 d t Fu limit)."""
    dh = hole_diameter(d)
    first = bearing_capacity(d, t, fu, end - dh / 2) if end is not None else 0.75 * 2.4 * d * t * fu
    return first + (rows - 1) * bearing_capacity(d, t, fu, pitch - dh)


def block_shear(fy, fu, agv, anv, ant, ubs: float = 1.0) -> float:
    """φRn, Eq 6.10.178, φ 0.75."""
    return 0.75 * min(0.6 * fu * anv + ubs * fu * ant, 0.6 * fy * agv + ubs * fu * ant)


def fillet_capacity_per_mm(w: float, fexx: float, theta_deg: float = 0.0) -> float:
    """φRn of a fillet weld per mm of length [N/mm], Eq 6.10.162-163, φ 0.75, throat 0.707 w."""
    s = math.sin(math.radians(theta_deg))
    return 0.75 * 0.6 * fexx * (1.0 + 0.5 * s**1.5) * 0.707 * w


def fillet_min_size(t_thinner: float) -> float:
    """Table 6.10.7."""
    return 3.0 if t_thinner <= 6 else 5.0 if t_thinner <= 13 else 6.0 if t_thinner <= 19 else 8.0


def fillet_max_size(t_edge: float) -> float:
    """Along edges: t below 6 mm, t - 2 mm otherwise (Sec 10.10.2.2, p. 116)."""
    return t_edge if t_edge < 6 else t_edge - 2.0


def whitmore_width(rows: int, lines: int, pitch: float, gauge: float) -> float:
    """Width of the Whitmore section at the last bolt row: the bolt-group width plus the
    30° spread over the bolt-group length on each side (from memory, to be checked)."""
    return (lines - 1) * gauge + 2 * (rows - 1) * pitch * math.tan(math.radians(30))


def _bolt_rules(c: _Bolted, t_plate: float, lines: int = 1, gauge: float | None = None):
    d = c.boltDiameter
    edge = min_edge(d, c.shearedEdges)
    out = []
    if c.rows > 1:
        out.append(_min_rule("bolt pitch", c.pitch, 8 / 3 * d, "Sec 10.10.3.3: 2⅔ d"))
    if lines > 1 and gauge is not None:
        out.append(_min_rule("bolt gauge", gauge, 8 / 3 * d, "Sec 10.10.3.3: 2⅔ d"))
    out.append(_min_rule("end distance", c.endDistance, edge, "Table 6.10.12"))
    out.append(_min_rule("edge distance", c.edgeDistance, edge, "Table 6.10.12"))
    limit = min(12 * t_plate, 150.0)
    out.append(
        _max_rule(
            "largest edge distance",
            max(c.endDistance, c.edgeDistance),
            limit,
            "Sec 10.10.3.5: 12 t, at most 150 mm",
        )
    )
    return out


def _weld_rules(w: float, t_thinner: float, t_edge: float | None):
    out = [_min_rule("fillet weld size", w, fillet_min_size(t_thinner), "Table 6.10.7")]
    if t_edge is not None:
        out.append(
            _max_rule(
                "fillet weld size (max)",
                w,
                fillet_max_size(t_edge),
                "Sec 10.10.2.2 maximum size along edges",
            )
        )
    return out


def _result(kind: str, checks: list[dict[str, Any]], assumptions: list[str]) -> dict[str, Any]:
    strength = [c for c in checks if not c["flag"]]
    return {
        "connection": kind,
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "assumptions": assumptions,
    }


def _governing(demands: list[tuple[str | None, float]], sign: int = 0) -> tuple[str | None, float]:
    """The largest |value| (sign 0), largest positive (1) or most negative (-1) demand."""
    best: tuple[str | None, float] = (None, 0.0)
    for comb, v in demands:
        key = abs(v) if sign == 0 else v * sign
        if key > (abs(best[1]) if sign == 0 else best[1] * sign):
            best = (comb, v)
    return best


# ─────────────────────────────────────── fin plate ───────────────────────────────────────


def check_fin_plate(
    c: FinPlateConnection,
    beam: SteelSection,
    beam_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    shears: list[tuple[str | None, float]],
) -> dict[str, Any]:
    """Checks of a fin plate for the beam end shears ``[(combination, V [N])]``."""
    plate = plate_material or beam_material
    comb, v = _governing(shears)
    v = abs(v)
    d, n, s, tp = c.boltDiameter, c.rows, c.pitch, c.plateThickness
    dn = net_hole(d)
    hp = 2 * c.endDistance + (n - 1) * s
    a = c.boltLineOffset
    # elastic bolt group: one line, polar moment Σ y²
    ys = [(i - (n - 1) / 2) * s for i in range(n)]
    sum_y2 = sum(y * y for y in ys)
    ymax = max(abs(y) for y in ys)
    r_max = math.hypot(v / n, v * a * ymax / sum_y2 if sum_y2 > 0 else 0.0) if n > 1 else v
    if n == 1:
        r_max = v  # a single bolt takes the moment only as a pin: plate flexure covers it
    efficiency = v / r_max if r_max > 0 else n  # effective number of bolts
    phi_bolt = bolt_shear_capacity(c.boltGrade, d, 1)
    checks = [
        _check(
            "bolt shear (most loaded bolt)",
            r_max / 1e3,
            phi_bolt / 1e3,
            "kN",
            comb,
            f"Eq 6.10.168; elastic method, e = {a:g} mm, {n} bolts",
        ),
    ]
    share = efficiency / n
    plate_bearing = bearing_line(d, tp, plate.fu, n, s, c.endDistance) * share
    web_bearing = bearing_line(d, beam.tw, beam_material.fu, n, s, None) * share
    checks.append(
        _check(
            "bearing on the plate",
            v / 1e3,
            plate_bearing / 1e3,
            "kN",
            comb,
            "Eq 6.10.173a, tear-out to the bottom edge",
        )
    )
    checks.append(
        _check(
            "bearing on the beam web",
            v / 1e3,
            web_bearing / 1e3,
            "kN",
            comb,
            "Eq 6.10.173a, uncoped web",
        )
    )
    agv = hp * tp
    anv = (hp - n * dn) * tp
    checks.append(
        _check(
            "plate shear yielding",
            v / 1e3,
            1.0 * 0.6 * plate.fy * agv / 1e3,
            "kN",
            comb,
            "Eq 6.10.176, φ 1.00",
        )
    )
    checks.append(
        _check(
            "plate shear rupture",
            v / 1e3,
            0.75 * 0.6 * plate.fu * anv / 1e3,
            "kN",
            comb,
            "Eq 6.10.177",
        )
    )
    bs_agv = (hp - c.endDistance) * tp
    bs_anv = bs_agv - (n - 0.5) * dn * tp
    bs_ant = (c.edgeDistance - 0.5 * dn) * tp
    checks.append(
        _check(
            "plate block shear",
            v / 1e3,
            block_shear(plate.fy, plate.fu, bs_agv, bs_anv, bs_ant) / 1e3,
            "kN",
            comb,
            "Eq 6.10.178, Ubs = 1",
        )
    )
    phi_mp = 0.9 * plate.fy * tp * hp**2 / 4
    checks.append(
        _check(
            "plate flexure at the bolt line",
            v * a / 1e6,
            phi_mp / 1e6,
            "kN·m",
            comb,
            "φ 0.9 Fy Z (from memory)",
        )
    )
    # two fillet welds along the plate height: direct shear + moment V·a, per mm
    f_direct = v / (2 * hp)
    f_moment = v * a / (2 * hp**2 / 6)
    f = math.hypot(f_direct, f_moment)
    checks.append(
        _check(
            "welds to the support",
            f,
            fillet_capacity_per_mm(c.weldSize, c.electrode),
            "N/mm",
            comb,
            "Eq 6.10.162-163, θ = 0 (conservative), elastic line method",
        )
    )
    checks += _bolt_rules(c, tp)
    checks += _weld_rules(c.weldSize, tp, None)
    return _result(
        "finPlate",
        checks,
        [
            "one vertical line of bolts in standard holes, bearing-type, single shear",
            f"bolt group eccentricity a = {a:g} mm by the elastic method (conservative)",
            "beam web uncoped; the support strong enough for the welds",
            "plate edges rolled or thermally cut" if not c.shearedEdges else "sheared edges",
        ],
    )


# ─────────────────────────────────────── end plate ───────────────────────────────────────


def check_end_plate(
    c: EndPlateConnection,
    beam: SteelSection,
    beam_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    shears: list[tuple[str | None, float]],
) -> dict[str, Any]:
    plate = plate_material or beam_material
    comb, v = _governing(shears)
    v = abs(v)
    d, n, s, tp = c.boltDiameter, c.rows, c.pitch, c.plateThickness
    dn = net_hole(d)
    hp = 2 * c.endDistance + (n - 1) * s
    ts = c.supportThickness or tp
    bolts = 2 * n
    phi_bolt = bolt_shear_capacity(c.boltGrade, d, 1)
    checks = [
        _check(
            "bolt shear",
            v / bolts / 1e3,
            phi_bolt / 1e3,
            "kN",
            comb,
            f"Eq 6.10.168, {bolts} bolts in single shear",
        ),
        _check(
            "bearing on the end plate",
            v / 1e3,
            2 * bearing_line(d, tp, plate.fu, n, s, c.endDistance) / 1e3,
            "kN",
            comb,
            "Eq 6.10.173a",
        ),
        _check(
            "bearing on the support",
            v / 1e3,
            2 * bearing_line(d, ts, plate.fu, n, s, None) / 1e3,
            "kN",
            comb,
            "Eq 6.10.173a; support of the plate's material",
        ),
    ]
    checks.append(
        _check(
            "plate shear yielding",
            v / 1e3,
            0.6 * plate.fy * 2 * hp * tp / 1e3,
            "kN",
            comb,
            "Eq 6.10.176, φ 1.00, two planes",
        )
    )
    checks.append(
        _check(
            "plate shear rupture",
            v / 1e3,
            0.75 * 0.6 * plate.fu * 2 * (hp - n * dn) * tp / 1e3,
            "kN",
            comb,
            "Eq 6.10.177, two planes",
        )
    )
    agv = 2 * (hp - c.endDistance) * tp
    anv = agv - 2 * (n - 0.5) * dn * tp
    ant = 2 * (c.edgeDistance - 0.5 * dn) * tp
    checks.append(
        _check(
            "plate block shear",
            v / 1e3,
            block_shear(plate.fy, plate.fu, agv, anv, ant) / 1e3,
            "kN",
            comb,
            "Eq 6.10.178, two blocks, Ubs = 1",
        )
    )
    weld = 2 * hp * fillet_capacity_per_mm(c.weldSize, c.electrode)
    checks.append(
        _check(
            "welds to the beam web",
            v / 1e3,
            weld / 1e3,
            "kN",
            comb,
            "Eq 6.10.162-163, two welds along the plate height, θ = 0",
        )
    )
    checks.append(
        _check(
            "beam web shear at the welds",
            v / 1e3,
            0.6 * beam_material.fy * beam.tw * hp / 1e3,
            "kN",
            comb,
            "Eq 6.10.176, φ 1.00, the web over the plate height",
        )
    )
    checks += _bolt_rules(c, tp, lines=2, gauge=c.gauge)
    checks += _weld_rules(c.weldSize, min(tp, beam.tw), None)
    return _result(
        "endPlate",
        checks,
        [
            "two vertical lines of bolts in standard holes, bearing-type, no prying (shear only)",
            "end plate shorter than the beam depth, welded to the web only",
            "support flange of the plate's material, thickness as given",
        ],
    )


# ─────────────────────────────────────── brace gusset ───────────────────────────────────────


def _brace_part(c: BraceGussetConnection, brace: SteelSection) -> tuple[float, bool]:
    """(thickness of the brace part bolted to the gusset, whether it is a welded tab)."""
    if brace.shape == "L":
        return brace.tw, False
    if brace.shape == "U":
        return brace.tw, False
    return c.tabThickness or c.plateThickness, True


def check_brace_gusset(
    c: BraceGussetConnection,
    brace: SteelSection,
    brace_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    axial: list[tuple[str | None, float]],
) -> dict[str, Any]:
    """Checks of a bolted brace-to-gusset end for the brace axial forces ``[(combination,
    N [N], tension +)]``."""
    plate = plate_material or brace_material
    d, n, m, s, g, tg = c.boltDiameter, c.rows, c.lines, c.pitch, c.gauge, c.plateThickness
    dn = net_hole(d)
    t_part, tab = _brace_part(c, brace)
    part_fu = plate.fu if tab else brace_material.fu
    bolts = n * m
    phi_bolt = bolt_shear_capacity(c.boltGrade, d, c.shearPlanes)
    lw = whitmore_width(n, m, s, g)
    lw = max(lw, 2 * d)  # a single bolt: at least the bolt's own spread
    checks: list[dict[str, Any]] = []
    for sign, label in ((1, "tension"), (-1, "compression")):
        comb, p = _governing(axial, sign)
        if p * sign <= 0:
            continue
        p = abs(p)
        checks.append(
            _check(
                f"bolt shear ({label})",
                p / bolts / 1e3,
                phi_bolt / 1e3,
                "kN",
                comb,
                f"Eq 6.10.168, {bolts} bolts, {c.shearPlanes} plane(s)",
            )
        )
        end = c.endDistance if sign > 0 else None  # compression bears into the plate
        checks.append(
            _check(
                f"bearing on the gusset ({label})",
                p / 1e3,
                m * bearing_line(d, tg, plate.fu, n, s, end) / 1e3,
                "kN",
                comb,
                "Eq 6.10.173a",
            )
        )
        checks.append(
            _check(
                f"bearing on the brace {'tab' if tab else 'leg/web'} ({label})",
                p / 1e3,
                m * bearing_line(d, t_part, part_fu, n, s, end) / 1e3,
                "kN",
                comb,
                "Eq 6.10.173a",
            )
        )
        if sign > 0:
            ag = lw * tg
            an = min((lw - m * dn) * tg, 0.85 * ag)
            checks.append(
                _check(
                    "gusset Whitmore yielding",
                    p / 1e3,
                    0.9 * plate.fy * ag / 1e3,
                    "kN",
                    comb,
                    f"Eq 6.10.174 on the Whitmore width {lw:.0f} mm",
                )
            )
            checks.append(
                _check(
                    "gusset Whitmore rupture",
                    p / 1e3,
                    0.75 * plate.fu * an / 1e3,
                    "kN",
                    comb,
                    "Eq 6.10.175, An <= 0.85 Ag",
                )
            )
            planes = 2
            agv = planes * (c.endDistance + (n - 1) * s) * tg
            anv = agv - planes * (n - 0.5) * dn * tg
            ant = max((m - 1) * (g - dn) * tg, 0.0)
            checks.append(
                _check(
                    "gusset block shear",
                    p / 1e3,
                    block_shear(plate.fy, plate.fu, agv, anv, ant) / 1e3,
                    "kN",
                    comb,
                    "Eq 6.10.178, Ubs = 1",
                )
            )
        else:
            r = tg / math.sqrt(12)
            kl_r = c.gussetK * c.gussetFreeLength / r
            ag = lw * tg
            if kl_r <= 25:
                cap, note = 0.9 * plate.fy * ag, "Eq 6.10.179 (KL/r <= 25)"
            else:
                cap = compression_capacity(ag, plate, kl_r)
                note = "Sec 10.5.3 Eq 6.10.16-19"
            checks.append(
                _check(
                    "gusset buckling (Whitmore)",
                    p / 1e3,
                    cap / 1e3,
                    "kN",
                    comb,
                    f"{note}; KL/r = {kl_r:.1f}, K = {c.gussetK:g}",
                )
            )
        weld = 2 * c.gussetWeldLength * fillet_capacity_per_mm(c.weldSize, c.electrode)
        checks.append(
            _check(
                f"gusset welds to the frame ({label})",
                p / 1e3,
                weld / 1e3,
                "kN",
                comb,
                "Eq 6.10.162-163, two welds, whole brace force, θ = 0",
            )
        )
        if tab:
            tab_weld = (
                c.tabWelds * c.tabWeldLength * fillet_capacity_per_mm(c.weldSize, c.electrode)
            )
            checks.append(
                _check(
                    f"tab welds to the brace ({label})",
                    p / 1e3,
                    tab_weld / 1e3,
                    "kN",
                    comb,
                    f"{c.tabWelds} fillet welds, θ = 0",
                )
            )
    checks += _bolt_rules(c, min(tg, t_part), lines=m, gauge=g)
    checks += _weld_rules(c.weldSize, tg, None)
    return _result(
        "gusset",
        checks,
        [
            "bolts in standard holes, bearing-type",
            "hollow and I braces: a slotted-in tab plate welded to the brace"
            if tab
            else "angle/channel bolted through its connected leg/web",
            "gusset-to-frame welds carry the whole brace force (no uniform force method)",
            "Whitmore spread at 30°; gusset buckling as a column of the Whitmore width",
            "the brace's own net section with shear lag is a member check, not here",
        ],
    )


# ─────────────────────────────────────── dispatch and design ───────────────────────────────────────


def check_connection(
    c: FinPlateConnection | EndPlateConnection | BraceGussetConnection,
    section: SteelSection,
    member_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    demands: list[tuple[str | None, float]],
) -> dict[str, Any]:
    """The connection's checks: ``{"connection", "checks", "utilisation", "ok",
    "assumptions"}``, ``demands`` the beam end shears or the brace axial forces [N]."""
    if isinstance(c, FinPlateConnection):
        return check_fin_plate(c, section, member_material, plate_material, demands)
    if isinstance(c, EndPlateConnection):
        return check_end_plate(c, section, member_material, plate_material, demands)
    return check_brace_gusset(c, section, member_material, plate_material, demands)


def propose_connection(
    c: FinPlateConnection | EndPlateConnection | BraceGussetConnection,
    section: SteelSection,
    member_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    demands: list[tuple[str | None, float]],
    max_rows: int = 10,
    sizes: tuple[int, ...] = (16, 20, 22, 24),
    plates: tuple[float, ...] = (8, 10, 12, 16, 20, 25),
) -> dict[str, Any]:
    """The fewest bolts (then the smallest bolt, then the thinnest plate) that pass:
    ``{"current", "proposed" (connection JSON or None), "result", "status"}``."""
    current = check_connection(c, section, member_material, plate_material, demands)
    best = None
    for rows in range(1 if c.type == "gusset" else 2, max_rows + 1):
        for size in sizes:
            for tp in plates:
                trial = c.model_copy(
                    update={"rows": rows, "boltDiameter": size, "plateThickness": tp}
                )
                res = check_connection(trial, section, member_material, plate_material, demands)
                if res["ok"]:
                    best = (trial, res)
                    break
            if best:
                break
        if best:
            break
    if best is None:
        return {"current": current, "proposed": None, "result": None, "status": "tooSmall"}
    trial, res = best
    same = trial.model_dump() == c.model_dump()
    return {
        "current": current,
        "proposed": trial.model_dump(),
        "result": res,
        "status": "unchanged" if same else "ok",
    }
