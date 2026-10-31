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

Connections 2 (moment connections, splices, column bases and HSS truss joints), each built only
from the provisions of BNBC 2020 Part 6 Chapter 10 (which adopts AISC 360-05; the section
numbers follow its chapter J and K structure, pages to be checked against the BNBC text):

- ``flangePlate`` (beams, :func:`check_flange_plate`): a bolted flange-plate moment connection.
  The flange force Puf = M / (d + tp); flange plate bolts (Eq 6.10.168), bearing on the plate
  and the beam flange (Eq 6.10.173a), the plate in tension (Eqs 6.10.174-175, An <= 0.85 Ag)
  and in compression (Sec 10.10.4.4, K 0.65 over the setback and end distance), block shear
  of the plate and the beam flange (Eq 6.10.178), the beam's flexural rupture at the flange
  holes (Sec 10.6.13.1), the plate-to-column welds (CJP: the plate governs; fillets Eq
  6.10.162-163 transverse), the web fin plate for the shear (:func:`check_fin_plate`), and the
  column side for the flange force (Sec 10.10.10): flange local bending 6.25 tf² Fy, web local
  yielding (5k + lb) Fy tw, web crippling 0.80 tw² [1 + 3 (lb/d)(tw/tf)^1.5] √(E Fy tf / tw),
  panel zone shear 0.60 Fy dc tw (Pr <= 0.4 Pc assumed).
- ``coverPlate`` splices (beams and columns, :func:`check_splice`): the flange force
  M / (d - tf) plus the flange's share of the axial force (compression left out where the
  ends are finished to bear, Sec 10.10.1.4), checked as the flange plate above on each side of
  the joint, and the web plates (bolts in double shear, bearing on the web, shear yielding
  and rupture, Sec 10.10.4.2) for V and the web's share of the axial force; splices designed
  for the forces at the splice, Sec 10.10.6.
- ``basePlate`` (columns at a support, :func:`check_base_plate`): concrete bearing φc Pp,
  Pp = 0.85 f'c A1 √(A2/A1) <= 1.7 f'c A1 (Sec 10.10.8), the anchor rods' steel in tension and
  shear as threaded parts (Table 6.10.10: Fnt 0.75 Fu, Fnv 0.40 / 0.50 Fu; combined Sec
  10.10.3.7) and the column-to-plate fillet welds. The plate thickness by the cantilever
  method of the steel design guides, moment bases and the anchors' concrete capacity (ACI
  318 Chapter 17, which BNBC refers to) are planned features: stated, not checked.
- ``hssJoint`` (braces, :func:`check_hss_joint`): a welded HSS-to-HSS truss joint, Sec 10.11.2:
  round chords (chord plastification of T/Y, X and gapped K joints, punching shear) and
  rectangular chords (chord wall plastification, punching shear, sidewall yielding and
  crippling at β = 1, branch yielding from uneven load), with the limits of applicability as
  checks. The welds are taken to develop the branch.

From memory, to be checked against the BNBC text: the Chapter K equations and their limits,
φ of the concentrated-force checks, φc 0.60 of bearing on concrete.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design.steel_proposal import SteelMaterial, compression_capacity
from saengine.library.objects import (  # the connection models live with the object types
    BraceGussetConnection,
    ColumnBasePlate,
    EndPlateConnection,
    FinPlateConnection,
    FlangePlateConnection,
    HssJointConnection,
    SteelSplice,
    _Bolted,
)
from saengine.library.steel_sections import SteelSection

#: The connection kinds that pass no moment (the analysis pins the member ends).
SIMPLE_KINDS = frozenset({"finPlate", "endPlate", "gusset", "hssJoint"})

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


# ─────────────────────────────────────── connections 2: shared ───────────────────────────────────────


def phi(key: str, default: float) -> float:
    """φ ``key`` of the code pack's steel table (``phi``, extra keys allowed); ``default`` when
    the pack in use has none."""
    try:
        from saengine.codes import context as code_context

        table = code_context.table("steel").phi
    except Exception:  # noqa: BLE001 - no pack loaded (a bare calculation): the BNBC value
        return default
    value = getattr(table, key, None)
    if value is None:
        value = (getattr(table, "model_extra", None) or {}).get(key)
    return float(value) if value is not None else default


def _plate_compression(area: float, t: float, length: float, m: SteelMaterial) -> tuple[float, str]:
    """φPn of a plate in compression over ``length`` (K 0.65, fixed at the weld and at the bolts):
    Sec 10.10.4.4 Eq 6.10.179 when KL/r <= 25, else flexural buckling (Sec 10.5.3)."""
    kl_r = 0.65 * length / (t / math.sqrt(12))
    if kl_r <= 25:
        return 0.9 * m.fy * area, f"Sec 10.10.4.4 Eq 6.10.179, KL/r = {kl_r:.1f} <= 25"
    return compression_capacity(area, m, kl_r), f"Sec 10.5.3 Eq 6.10.16-19, KL/r = {kl_r:.1f}"


def _plate_block_shear(fy, fu, t, rows, pitch, end, lines, gauge, edge, dn) -> float:
    """φRn of block shear of a plate (or flange) with ``lines`` bolt lines of ``rows`` bolts
    loaded along the lines: the smaller of the two outer blocks (tension planes to the edges)
    and the inner block between the outer lines (Eq 6.10.178, Ubs = 1)."""
    agv = 2 * (end + (rows - 1) * pitch) * t
    anv = agv - 2 * (rows - 0.5) * dn * t
    outer = block_shear(fy, fu, agv, anv, 2 * max(edge - 0.5 * dn, 0.0) * t)
    inner = block_shear(fy, fu, agv, anv, max((lines - 1) * (gauge - dn), 0.0) * t)
    return min(outer, inner)


def _flange_force_checks(
    label: str,
    force: float,
    comb: str | None,
    c: Any,
    flange: SteelSection,
    member: SteelMaterial,
    plate: SteelMaterial,
    free_length: float,
    compression: bool,
) -> list[dict[str, Any]]:
    """Checks of a bolted flange plate carrying ``force`` [N] along the member flange: bolts,
    bearing, the plate in tension or compression, block shear of the plate and the flange."""
    d, n, s, tp, m = c.boltDiameter, c.rows, c.pitch, c.plateThickness, c.lines
    dn = net_hole(d)
    bp = (m - 1) * c.gauge + 2 * c.edgeDistance
    edge_flange = (flange.b - (m - 1) * c.gauge) / 2
    bolts = n * m
    out = [
        _check(
            f"{label} bolt shear",
            force / bolts / 1e3,
            bolt_shear_capacity(c.boltGrade, d, 1) / 1e3,
            "kN",
            comb,
            f"Eq 6.10.168, {bolts} bolts in single shear",
        )
    ]
    end = None if compression else c.endDistance
    out.append(
        _check(
            f"{label} bearing on the plate",
            force / 1e3,
            m * bearing_line(d, tp, plate.fu, n, s, end) / 1e3,
            "kN",
            comb,
            "Eq 6.10.173a",
        )
    )
    out.append(
        _check(
            f"{label} bearing on the member flange",
            force / 1e3,
            m * bearing_line(d, flange.tf, member.fu, n, s, end) / 1e3,
            "kN",
            comb,
            "Eq 6.10.173a",
        )
    )
    ag = bp * tp
    if compression:
        cap, note = _plate_compression(ag, tp, free_length, plate)
        out.append(
            _check(f"{label} plate in compression", force / 1e3, cap / 1e3, "kN", comb, note)
        )
    else:
        an = min((bp - m * dn) * tp, 0.85 * ag)
        out.append(
            _check(
                f"{label} plate tension yielding",
                force / 1e3,
                0.9 * plate.fy * ag / 1e3,
                "kN",
                comb,
                "Sec 10.10.4.1 Eq 6.10.174",
            )
        )
        out.append(
            _check(
                f"{label} plate tension rupture",
                force / 1e3,
                0.75 * plate.fu * an / 1e3,
                "kN",
                comb,
                "Sec 10.10.4.1 Eq 6.10.175, An <= 0.85 Ag",
            )
        )
        bs_plate = _plate_block_shear(
            plate.fy, plate.fu, tp, n, s, c.endDistance, m, c.gauge, c.edgeDistance, dn
        )
        out.append(
            _check(
                f"{label} plate block shear",
                force / 1e3,
                bs_plate / 1e3,
                "kN",
                comb,
                "Eq 6.10.178, Ubs = 1",
            )
        )
        bs_flange = _plate_block_shear(
            member.fy, member.fu, flange.tf, n, s, c.endDistance, m, c.gauge, edge_flange, dn
        )
        out.append(
            _check(
                f"{label} member flange block shear",
                force / 1e3,
                bs_flange / 1e3,
                "kN",
                comb,
                "Eq 6.10.178, Ubs = 1",
            )
        )
    return out


def _flange_rules(c: Any, flange: SteelSection) -> list[dict[str, Any]]:
    """Spacing and edges of a flange plate's bolts, and the bolt lines fitting the flange."""
    edge_flange = (flange.b - (c.lines - 1) * c.gauge) / 2
    out = _bolt_rules(c, min(c.plateThickness, flange.tf), lines=c.lines, gauge=c.gauge)
    out.append(
        _min_rule(
            "edge distance on the member flange",
            edge_flange,
            min_edge(c.boltDiameter, False),
            "Table 6.10.12",
        )
    )
    return out


def _is_i(section: SteelSection) -> bool:
    return section.shape == "I"


def _governing_vector(
    demands: list[tuple[Any, ...]], index: int, sign: int = 0
) -> tuple[Any, ...] | None:
    """The demand row whose value ``index`` is the largest |value| (sign 0), largest positive
    (1) or most negative (-1)."""
    best = None
    for row in demands:
        v = row[index]
        key = abs(v) if sign == 0 else v * sign
        if best is None or key > (abs(best[index]) if sign == 0 else best[index] * sign):
            best = row
    if best is not None and sign != 0 and best[index] * sign <= 0:
        return None
    return best


# ─────────────────────────────────────── flange-plate moment connection ───────────────────────────────────────


def column_side_checks(
    force: float,
    comb: str | None,
    column: SteelSection,
    column_material: SteelMaterial,
    bearing_length: float,
    stiffened: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Checks of a column flange and web under a beam flange force ``force`` [N] (single
    concentrated force, Sec 10.10.10), and assumptions. Unstiffened: flange local bending
    6.25 tf² Fyf, web local yielding (5k + lb) Fyw tw, web crippling; always the
    panel zone shear 0.60 Fy dc tw (Pr <= 0.4 Pc assumed), the storey shear of the column left
    out (conservative)."""
    fy, e = column_material.fy, column_material.E
    tf, tw, dc = column.tf, column.tw, column.h
    k = tf + column.r
    checks: list[dict[str, Any]] = []
    notes = [
        (
            "column side: one beam flange force on the column (one-sided joint); the force applied "
            "more than the column depth from the column's end"
        )
    ]
    if not stiffened:
        checks.append(
            _check(
                "column flange local bending",
                force / 1e3,
                phi("flangeLocalBending", 0.9) * 6.25 * tf**2 * fy / 1e3,
                "kN",
                comb,
                "Sec 10.10.10.1: 6.25 tf² Fyf",
            )
        )
        checks.append(
            _check(
                "column web local yielding",
                force / 1e3,
                phi("webLocalYielding", 1.0) * (5 * k + bearing_length) * fy * tw / 1e3,
                "kN",
                comb,
                f"Sec 10.10.10.2: (5k + lb) Fyw tw, k = {k:.0f} mm, lb = {bearing_length:.0f} mm",
            )
        )
        crippling = (
            0.80
            * tw**2
            * (1 + 3 * (bearing_length / dc) * (tw / tf) ** 1.5)
            * math.sqrt(e * fy * tf / tw)
        )
        checks.append(
            _check(
                "column web crippling",
                force / 1e3,
                phi("webCrippling", 0.75) * crippling / 1e3,
                "kN",
                comb,
                "Sec 10.10.10.3: 0.80 tw² [1 + 3 (lb/d)(tw/tf)^1.5] √(E Fyw tf / tw)",
            )
        )
    else:
        notes.append("continuity plates take the flange force: their design is not checked")
    checks.append(
        _check(
            "column panel zone shear",
            force / 1e3,
            phi("panelZone", 0.9) * 0.60 * fy * dc * tw / 1e3,
            "kN",
            comb,
            "Sec 10.10.10.6: 0.60 Fy dc tw (Pr <= 0.4 Pc assumed; no doubler plates)",
        )
    )
    return checks, notes


def check_flange_plate(
    c: FlangePlateConnection,
    beam: SteelSection,
    beam_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    demands: list[tuple[str | None, float, float]],
    column: SteelSection | None = None,
    column_material: SteelMaterial | None = None,
) -> dict[str, Any]:
    """Checks of a bolted flange-plate moment connection for the beam end forces
    ``[(combination, M [N·mm], V [N])]``."""
    if not _is_i(beam):
        raise ValueError("flange-plate moment connections are for I-section beams")
    plate = plate_material or beam_material
    row = _governing_vector(demands, 1) or (None, 0.0, 0.0)
    comb, m = row[0], abs(row[1])
    tp = c.plateThickness
    puf = m / (beam.h + tp)
    free = c.setback + c.endDistance
    checks: list[dict[str, Any]] = []
    checks += _flange_force_checks(
        "flange plate (tension)", puf, comb, c, beam, beam_material, plate, free, False
    )
    checks += _flange_force_checks(
        "flange plate (compression)", puf, comb, c, beam, beam_material, plate, free, True
    )
    # Sec 10.6.13.1: flexural rupture of the tension flange at the holes.
    dn = net_hole(c.boltDiameter)
    afg = beam.b * beam.tf
    afn = (beam.b - c.lines * dn) * beam.tf
    yt = 1.0 if beam_material.fy / beam_material.fu <= 0.8 else 1.1
    if beam_material.fu * afn < yt * beam_material.fy * afg:
        checks.append(
            _check(
                "beam flexural rupture at the flange holes",
                m / 1e6,
                0.9 * beam_material.fu * afn / afg * beam.Sx / 1e6,
                "kN·m",
                comb,
                f"Sec 10.6.13.1: Mn = Fu Afn / Afg Sx (Fu Afn < Yt Fy Afg, Yt = {yt:g})",
            )
        )
    bp = (c.lines - 1) * c.gauge + 2 * c.edgeDistance
    if c.plateWeld == "fillet":
        cap = 2 * bp * fillet_capacity_per_mm(c.weldSize, c.electrode, 90.0)
        checks.append(
            _check(
                "flange plate welds to the column",
                puf / 1e3,
                cap / 1e3,
                "kN",
                comb,
                "Eq 6.10.162-163, two transverse fillet welds across the plate, θ = 90°",
            )
        )
        checks += _weld_rules(c.weldSize, tp, None)
    # The web: a fin plate for the end shear.
    web = FinPlateConnection(
        boltGrade=c.boltGrade,
        boltDiameter=c.boltDiameter,
        rows=c.webRows,
        pitch=c.pitch,
        endDistance=c.endDistance,
        edgeDistance=c.edgeDistance,
        plateThickness=c.webPlateThickness,
        weldSize=c.weldSize,
        electrode=c.electrode,
        shearedEdges=c.shearedEdges,
        boltLineOffset=c.webBoltLineOffset,
    )
    web_result = check_fin_plate(
        web, beam, beam_material, plate_material, [(r[0], r[2]) for r in demands]
    )
    checks += [{**w, "name": f"web: {w['name']}"} for w in web_result["checks"]]
    checks += _flange_rules(c, beam)
    assumptions = [
        "flange plates outside the beam flanges, bolts in standard holes, bearing-type",
        (
            f"flange force Puf = M / (d + tp) = {puf / 1e3:.0f} kN (M = {m / 1e6:.1f} kN·m), the "
            f"plate in compression over {free:g} mm (K 0.65)"
        ),
        "CJP groove welds with matching filler: the plates govern (no separate weld check)"
        if c.plateWeld == "cjp"
        else "fillet welds on both faces of each plate, transverse",
        "the beam end is kept rigid in the analysis (a moment connection)",
    ]
    if column is not None:
        cm = column_material or beam_material
        if not _is_i(column):
            assumptions.append("column side not checked: the column is not an I-section")
        else:
            lb = tp + (2 * c.weldSize if c.plateWeld == "fillet" else 0.0)
            more, notes = column_side_checks(puf, comb, column, cm, lb, c.columnStiffeners)
            checks += more
            assumptions += notes
    else:
        assumptions.append("column side not checked: no column section given")
    return _result("flangePlate", checks, assumptions)


# ─────────────────────────────────────── splices ───────────────────────────────────────


def check_splice(
    c: SteelSplice,
    section: SteelSection,
    material: SteelMaterial,
    plate_material: SteelMaterial | None,
    demands: list[tuple[str | None, float, float, float]],
    column: bool = False,
) -> dict[str, Any]:
    """Checks of a bolted cover-plate splice of an I-section for the forces at the splice
    ``[(combination, P [N] compression +, M [N·mm], V [N])]`` (Sec 10.10.6)."""
    if not _is_i(section):
        raise ValueError("cover-plate splices are for I-sections")
    plate = plate_material or material
    h, b, tf, tw = section.h, section.b, section.tf, section.tw
    af = b * tf
    share_f = af / section.A
    aw = max(section.A - 2 * af, 0.0)
    share_w = aw / section.A
    bearing = column and c.finishedToBear
    lever = h - tf
    tension: tuple[float, str | None] = (0.0, None)
    compression: tuple[float, str | None] = (0.0, None)
    web: tuple[float, str | None] = (0.0, None)
    for comb, p, m, v in demands:
        bend = abs(m) / lever
        ft = bend - p * share_f  # P compression positive
        fc = bend + p * share_f
        if bearing and p > 0:
            fc = 0.0  # compression passes by bearing (Sec 10.10.1.4)
        if ft > tension[0]:
            tension = (ft, comb)
        if fc > compression[0]:
            compression = (fc, comb)
        pw = 0.0 if (bearing and p > 0) else abs(p) * share_w
        fw = math.hypot(v, pw)
        if fw > web[0]:
            web = (fw, comb)
    free = c.gap + 2 * c.endDistance
    checks: list[dict[str, Any]] = []
    if tension[0] > 0:
        checks += _flange_force_checks(
            "flange plate (tension)",
            tension[0],
            tension[1],
            c,
            section,
            material,
            plate,
            free,
            False,
        )
        dn = net_hole(c.boltDiameter)
        an = min((b - c.lines * dn) * tf, 0.85 * af)
        checks.append(
            _check(
                "member flange net section rupture",
                tension[0] / 1e3,
                0.75 * material.fu * an / 1e3,
                "kN",
                tension[1],
                "Sec 10.10.4.1 Eq 6.10.175 on the flange",
            )
        )
    if compression[0] > 0:
        checks += _flange_force_checks(
            "flange plate (compression)",
            compression[0],
            compression[1],
            c,
            section,
            material,
            plate,
            free,
            True,
        )
    # Web plates on both sides: bolts in double shear, one line on each side of the joint.
    d, n, s, tpw = c.boltDiameter, c.webRows, c.webPitch, c.webPlateThickness
    dn = net_hole(d)
    hp = 2 * c.webEndDistance + (n - 1) * s
    fw, cw = web
    checks.append(
        _check(
            "web bolt shear",
            fw / n / 1e3,
            bolt_shear_capacity(c.boltGrade, d, 2) / 1e3,
            "kN",
            cw,
            f"Eq 6.10.168, {n} bolts in double shear each side",
        )
    )
    checks.append(
        _check(
            "bearing on the member web",
            fw / 1e3,
            bearing_line(d, tw, material.fu, n, s, None) / 1e3,
            "kN",
            cw,
            "Eq 6.10.173a",
        )
    )
    checks.append(
        _check(
            "bearing on the web plates",
            fw / 1e3,
            2 * bearing_line(d, tpw, plate.fu, n, s, c.webEndDistance) / 1e3,
            "kN",
            cw,
            "Eq 6.10.173a, two plates",
        )
    )
    checks.append(
        _check(
            "web plates shear yielding",
            fw / 1e3,
            phi("shearYielding", 1.0) * 0.6 * plate.fy * 2 * hp * tpw / 1e3,
            "kN",
            cw,
            "Sec 10.10.4.2 Eq 6.10.176, two plates",
        )
    )
    checks.append(
        _check(
            "web plates shear rupture",
            fw / 1e3,
            0.75 * 0.6 * plate.fu * 2 * (hp - n * dn) * tpw / 1e3,
            "kN",
            cw,
            "Sec 10.10.4.2 Eq 6.10.177, two plates",
        )
    )
    checks += _flange_rules(c, section)
    checks.append(
        _max_rule(
            "web plate height",
            hp,
            h - 2 * tf - 2 * section.r,
            "between the flange fillets",
        )
    )
    if n > 1:
        checks.append(_min_rule("web bolt pitch", s, 8 / 3 * d, "Sec 10.10.3.3: 2⅔ d"))
    checks.append(
        _min_rule("web plate end distance", c.webEndDistance, min_edge(d), "Table 6.10.12")
    )
    assumptions = [
        f"splice {c.distance:g} mm from the member's lower end, at the forces there",
        (
            "flange force M / (d - tf) plus the flange's share of the axial force; the web plates "
            "take the shear and the web's share"
        ),
        "outer flange plates in single shear; web plates on both faces",
        "compression by bearing of the finished ends (Sec 10.10.1.4): the plates take tension "
        "and moment"
        if bearing
        else "the plates take the whole axial force",
    ]
    return _result("coverPlate", checks, assumptions)


# ─────────────────────────────────────── column base plates ───────────────────────────────────────


def anchor_capacities(c: ColumnBasePlate) -> tuple[float, float, float, float]:
    """(φ Fnt Ab, φ Fnv Ab, Fnt, Fnv) of one anchor rod as a threaded part [N, MPa]
    (Table 6.10.10: Fnt = 0.75 Fu, Fnv = 0.40 Fu threads included or 0.50 Fu excluded)."""
    ab = math.pi * c.anchorDiameter**2 / 4
    fnt = 0.75 * c.anchorFu
    fnv = (0.50 if c.threadsExcluded else 0.40) * c.anchorFu
    p = phi("anchorRod", 0.75)
    return p * fnt * ab, p * fnv * ab, fnt, fnv


def bearing_on_concrete(c: ColumnBasePlate) -> float:
    """φc Pp [N]: Pp = 0.85 f'c A1 √(A2/A1) <= 1.7 f'c A1 (Sec 10.10.8)."""
    a1 = c.length * c.width
    a2 = max((c.supportLength or c.length) * (c.supportWidth or c.width), a1)
    return (
        phi("concreteBearing", 0.6) * 0.85 * c.concreteStrength * a1 * min(math.sqrt(a2 / a1), 2.0)
    )


def check_base_plate(
    c: ColumnBasePlate,
    column: SteelSection,
    column_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    demands: list[tuple[str | None, float, float, float]],
) -> dict[str, Any]:
    """Checks of a column base plate for the base forces ``[(combination, P [N] compression
    +, V [N] resultant, M [N·mm] resultant)]``."""
    checks: list[dict[str, Any]] = []
    comp = _governing_vector(demands, 1, 1)
    if comp is not None:
        comb, p, _, m = comp
        checks.append(
            _check(
                "bearing on the concrete",
                p / 1e3,
                bearing_on_concrete(c) / 1e3,
                "kN",
                comb,
                "Sec 10.10.8: φc 0.85 f'c A1 √(A2/A1) <= 1.7 f'c A1",
            )
        )
        e = abs(m) / p if p > 0 else 0.0
        checks.append(
            _check(
                "eccentricity M / P within N / 6",
                e,
                c.length / 6,
                "mm",
                comb,
                "beyond N / 6 the bearing is not uniform: a moment base (planned)",
                flag=True,
            )
        )
    t_rod, v_rod, fnt, fnv = anchor_capacities(c)
    n = c.anchors
    uplift = _governing_vector(demands, 1, -1)
    shear = _governing_vector(demands, 2)
    if uplift is not None:
        comb, p, v, _ = uplift
        frt = -p / n
        checks.append(
            _check(
                "anchor rod tension",
                frt / 1e3,
                t_rod / 1e3,
                "kN",
                comb,
                "Eq 6.10.168, Table 6.10.10: 0.75 Fu",
            )
        )
        # Combined tension and shear, Sec 10.10.3.7: F'nt = 1.3 Fnt - Fnt / (φ Fnv) frv <= Fnt.
        ab = math.pi * c.anchorDiameter**2 / 4
        frv = abs(v) / n / ab
        p_rod = phi("anchorRod", 0.75)
        fnt_ = min(1.3 * fnt - fnt / (p_rod * fnv) * frv, fnt)
        checks.append(
            _check(
                "anchor rod tension with shear",
                frt / 1e3,
                max(p_rod * fnt_ * ab, 0.0) / 1e3,
                "kN",
                comb,
                "Sec 10.10.3.7: F'nt = 1.3 Fnt - Fnt / (φ Fnv) frv <= Fnt",
            )
        )
    if shear is not None and abs(shear[2]) > 0:
        comb, _, v, _ = shear
        checks.append(
            _check(
                "anchor rod shear",
                abs(v) / n / 1e3,
                v_rod / 1e3,
                "kN",
                comb,
                "Eq 6.10.168, Table 6.10.10: "
                + ("0.50 Fu (threads excluded)" if c.threadsExcluded else "0.40 Fu"),
            )
        )
    # Column-to-plate fillet welds: all round the profile.
    if column.shape == "I":
        web = column.h - 2 * column.tf
        length = 2 * column.b + 2 * (column.b - column.tw) + 2 * web
    elif column.shape == "circleHollow":
        web = column.h
        length = math.pi * column.h
    else:
        web = 2 * column.h
        length = 2 * (column.h + column.b)
    per_mm = fillet_capacity_per_mm(c.weldSize, c.electrode)
    worst = (0.0, None)
    for comb, p, v, _ in demands:
        f = math.hypot(max(-p, 0.0) / length, abs(v) / web)
        if f > worst[0]:
            worst = (f, comb)
    if worst[0] > 0:
        checks.append(
            _check(
                "column welds to the plate",
                worst[0],
                per_mm,
                "N/mm",
                worst[1],
                "Eq 6.10.162-163, θ = 0; uplift on the whole weld, shear on the web welds",
            )
        )
    checks += _weld_rules(c.weldSize, min(c.thickness, column.tf), None)
    checks.append(_min_rule("plate length N", c.length, column.h, "the plate covers the column"))
    checks.append(_min_rule("plate width B", c.width, column.b, "the plate covers the column"))
    return _result(
        "basePlate",
        checks,
        [
            (
                "column ends finished to bear on the plate: compression by bearing, the welds for "
                "uplift and shear"
            ),
            "uniform bearing on the area A1 = N × B (a concentric axial load)",
            "the base shear taken by the anchor rods in bearing (no friction, no shear key)",
            (
                "not checked (planned features): the plate thickness by the cantilever method, "
                "moment bases, and the anchors' concrete capacity (ACI 318 Chapter 17)"
            ),
        ],
    )


# ─────────────────────────────────────── HSS truss joints ───────────────────────────────────────


def _limit(name: str, value: float, limit: float, note: str, above: bool = False) -> dict[str, Any]:
    """A limit of applicability as a check: ``value`` <= ``limit`` (``above``: >=)."""
    if above:
        return _check(name, limit, value, "", None, note)
    return _check(name, value, limit, "", None, note)


def check_hss_joint(
    c: HssJointConnection,
    branch: SteelSection,
    branch_material: SteelMaterial,
    chord: SteelSection,
    chord_material: SteelMaterial | None,
    axial: list[tuple[str | None, float]],
) -> dict[str, Any]:
    """Checks of a welded HSS-to-HSS truss joint for the branch axial forces ``[(combination,
    N [N], tension +)]`` (Sec 10.11.2)."""
    cm = chord_material or branch_material
    fy, fu, e = cm.fy, cm.fu, cm.E
    t = chord.tw
    theta = math.radians(c.angle)
    sin = math.sin(theta)
    checks: list[dict[str, Any]] = []
    round_ = chord.shape == "circleHollow" and branch.shape == "circleHollow"
    rect = chord.shape == "rectangleHollow" and branch.shape == "rectangleHollow"
    if not (round_ or rect):
        raise ValueError(
            "HSS joints need a round branch on a round chord or rectangular on rectangular"
        )
    clause = "Sec 10.11.2"
    checks.append(_limit("chord Fy", fy, 360.0, f"{clause}: Fy <= 360 MPa"))
    checks.append(_limit("chord Fy / Fu", fy / fu, 0.8, f"{clause}: Fy / Fu <= 0.8"))
    capacities: list[tuple[str, float, str, bool]] = []  # name, φPn, note, compression only
    if round_:
        dc, db, tb = chord.h, branch.h, branch.tw
        beta = db / dc
        gamma = dc / (2 * t)
        u = c.chordUtilisation
        qf = 1.0 - 0.3 * u * (1 + u) if c.chordCompression else 1.0
        checks.append(_limit("chord D / t", dc / t, 40.0 if c.joint == "X" else 50.0, f"{clause}"))
        checks.append(_limit("branch D / t", db / tb, 50.0, clause))
        checks.append(_limit("β = Db / D", beta, 1.0, f"{clause}: 0.2 < β <= 1.0"))
        checks.append(_limit("β = Db / D (least)", beta, 0.2, f"{clause}: β > 0.2", above=True))
        p_pl = phi("hssPlastification", 0.9)
        if c.joint == "TY":
            pn = fy * t**2 * (3.1 + 15.6 * beta**2) * gamma**0.2 * qf / sin
            note = "Fy t² (3.1 + 15.6 β²) γ^0.2 Qf / sin θ"
        elif c.joint == "X":
            pn = fy * t**2 * (5.7 / (1 - 0.81 * beta)) * qf / sin
            note = "Fy t² (5.7 / (1 - 0.81 β)) Qf / sin θ"
        else:
            qg = gamma**0.2 * (1 + 0.024 * gamma**1.2 / (math.exp(0.5 * c.gap / t - 1.33) + 1))
            pn = fy * t**2 * (2.0 + 11.33 * db / dc) * qg * qf / sin
            note = f"Fy t² (2.0 + 11.33 Db / D) Qg Qf / sin θ, Qg = {qg:.2f}"
            checks.append(
                _limit("gap g", c.gap, 2 * tb, f"{clause}: g >= tb,comp + tb,tens", above=True)
            )
        capacities.append(
            ("chord plastification", p_pl * pn, f"{clause}: {note}, Qf = {qf:.2f}", False)
        )
        if db < dc - 2 * t:
            pn = 0.6 * fy * t * math.pi * db * (1 + sin) / (2 * sin**2)
            capacities.append(
                (
                    "chord punching shear",
                    phi("hssPunching", 0.95) * pn,
                    f"{clause}: 0.6 Fy t π Db (1 + sin θ) / (2 sin² θ)",
                    False,
                )
            )
    else:
        bc, hc = chord.b, chord.h
        bb, hb, tb = branch.b, branch.h, branch.tw
        fyb = branch_material.fy
        beta = bb / bc
        gamma = bc / (2 * t)
        eta = hb / sin / bc
        n_len = hb / sin
        u = c.chordUtilisation
        qf = min(1.3 - 0.4 * u / beta, 1.0) if c.chordCompression else 1.0
        beop = min(5 * beta / gamma, beta)
        checks.append(_limit("chord B / t", bc / t, 35.0, clause))
        checks.append(_limit("chord H / t", hc / t, 35.0, clause))
        checks.append(_limit("branch B / t", bb / tb, 35.0, clause))
        checks.append(_limit("chord H / B", hc / bc, 2.0, f"{clause}: 0.5 <= H / B <= 2.0"))
        checks.append(_limit("chord H / B (least)", hc / bc, 0.5, clause, above=True))
        checks.append(_limit("branch H / B", hb / bb, 2.0, f"{clause}: 0.5 <= Hb / Bb <= 2.0"))
        checks.append(_limit("branch H / B (least)", hb / bb, 0.5, clause, above=True))
        if c.joint == "K":
            beta_eff = (bb + hb) / (2 * bc)
            checks.append(_limit("β (least)", beta, 0.35, f"{clause}: β >= 0.35 (K)", above=True))
            checks.append(
                _limit(
                    "gap g / B",
                    c.gap / bc,
                    0.5 * (1 - beta_eff),
                    f"{clause}: g / B >= 0.5 (1 - βeff)",
                    above=True,
                )
            )
            checks.append(
                _limit("gap g", c.gap, 2 * tb, f"{clause}: g >= tb,comp + tb,tens", above=True)
            )
            pn = fy * t**2 * (9.8 * beta_eff * gamma**0.5) * qf / sin
            capacities.append(
                (
                    "chord wall plastification",
                    phi("hssPlastification", 0.9) * pn,
                    f"{clause}: Fy t² (9.8 βeff γ^0.5) Qf / sin θ, βeff = {beta_eff:.2f}, Qf = {qf:.2f}",
                    False,
                )
            )
            square = abs(bb - hb) < 1e-6
            if bb < bc - 2 * t and not square:
                pn = 0.6 * fy * t * bc * (2 * eta + beta + beop) / sin
                capacities.append(
                    (
                        "chord punching shear",
                        phi("hssPunching", 0.95) * pn,
                        f"{clause}: 0.6 Fy t B (2η + β + βeop) / sin θ",
                        False,
                    )
                )
            if not square and bc / t < 15:
                beoi = min(10 / (bc / t) * (fy * t / (fyb * tb)) * bb, bb)
                pn = fyb * tb * (2 * hb + bb + beoi - 4 * tb)
                capacities.append(
                    (
                        "branch yielding (uneven load)",
                        phi("hssBranchYielding", 0.95) * pn,
                        f"{clause}: Fyb tb (2Hb + Bb + beoi - 4tb)",
                        False,
                    )
                )
        else:
            checks.append(_limit("β (least)", beta, 0.25, f"{clause}: β >= 0.25", above=True))
            if beta <= 0.85:
                pn = fy * t**2 * (2 * eta / (1 - beta) + 4 / math.sqrt(1 - beta)) * qf / sin
                capacities.append(
                    (
                        "chord wall plastification",
                        phi("hssPlastificationRect", 1.0) * pn,
                        f"{clause}: Fy t² [2η / (1 - β) + 4 / √(1 - β)] Qf / sin θ, Qf = {qf:.2f}",
                        False,
                    )
                )
            elif beta <= 1 - 1 / gamma:
                pn = 0.6 * fy * t * bc * (2 * eta + 2 * beop) / sin
                capacities.append(
                    (
                        "chord punching shear",
                        phi("hssPunching", 0.95) * pn,
                        f"{clause}: 0.6 Fy t B (2η + 2βeop) / sin θ",
                        False,
                    )
                )
            if beta >= 0.99:
                k = max(chord.r, 1.5 * t)
                pn = 2 * fy * t * (5 * k + n_len) / sin
                capacities.append(
                    (
                        "chord sidewall local yielding",
                        phi("hssSidewallYielding", 1.0) * pn,
                        f"{clause}: 2 Fy t (5k + N) / sin θ",
                        False,
                    )
                )
                if c.joint == "TY":
                    pn = 1.6 * t**2 * (1 + 3 * n_len / (hc - 3 * t)) * math.sqrt(e * fy) * qf / sin
                    p_cr = phi("hssSidewallCripplingTY", 0.75)
                    note = "1.6 t² [1 + 3N / (H - 3t)] √(E Fy) Qf / sin θ"
                else:
                    pn = 48 * t**3 / (hc - 3 * t) * math.sqrt(e * fy) * qf / sin
                    p_cr = phi("hssSidewallCripplingX", 0.9)
                    note = "48 t³ / (H - 3t) √(E Fy) Qf / sin θ"
                capacities.append(
                    ("chord sidewall crippling", p_cr * pn, f"{clause}: {note}", True)
                )
            if beta > 0.85:
                beoi = min(10 / (bc / t) * (fy * t / (fyb * tb)) * bb, bb)
                pn = fyb * tb * (2 * hb + 2 * beoi - 4 * tb)
                capacities.append(
                    (
                        "branch yielding (uneven load)",
                        phi("hssBranchYielding", 0.95) * pn,
                        f"{clause}: Fyb tb (2Hb + 2beoi - 4tb)",
                        False,
                    )
                )
    for sign, label in ((1, "tension"), (-1, "compression")):
        comb, p = _governing(axial, sign)
        if p * sign <= 0:
            continue
        for name, cap, note, compression_only in capacities:
            if compression_only and sign > 0:
                continue
            checks.append(_check(f"{name} ({label})", abs(p) / 1e3, cap / 1e3, "kN", comb, note))
    for check in checks:
        if check["unit"] == "":
            check["unit"] = "-"
    joint = {"TY": "T or Y", "X": "cross (X)", "K": "gapped K"}[c.joint]
    return _result(
        "hssJoint",
        checks,
        [
            (
                f"{'round' if round_ else 'rectangular'} {joint} joint, θ = {c.angle:g}°, chord "
                f"{chord.name}"
            ),
            f"chord in compression, utilisation U = {c.chordUtilisation:g}"
            if c.chordCompression
            else "chord in tension (Qf = 1)",
            "K joints: both branches of this section, loaded in opposite senses",
            "the welds develop the branch (not checked); no overlapped joints",
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
    """The simple connection's checks: ``{"connection", "checks", "utilisation", "ok",
    "assumptions"}``, ``demands`` the beam end shears or the brace axial forces [N]. The
    moment connections, splices, base plates and HSS joints have their own functions (their
    demands are not one force)."""
    if isinstance(c, FinPlateConnection):
        return check_fin_plate(c, section, member_material, plate_material, demands)
    if isinstance(c, EndPlateConnection):
        return check_end_plate(c, section, member_material, plate_material, demands)
    if isinstance(c, BraceGussetConnection):
        return check_brace_gusset(c, section, member_material, plate_material, demands)
    raise TypeError(f"'{c.type}' is not checked by check_connection")


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
    ``{"current", "proposed" (connection JSON or None), "result", "status"}``. Simple
    connections only (fin plate, shear end plate, gusset)."""
    if c.type not in ("finPlate", "endPlate", "gusset"):
        raise TypeError(f"'{c.type}' connections are not proposed")
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
