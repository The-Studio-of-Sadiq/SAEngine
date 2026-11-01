"""Steel connections: strength checks and stated assumptions (Part 6 Chapter 10 of the code pack
in force, Sec 10.10-10.11; LRFD).

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

Clauses (Part 6 Chapter 10 of the default code pack; the numbers, tables and φ are the pack's
``steel`` table): bolt tension/shear 10.10.3.6 Eq 6.10.168 with Table 6.10.10; combined
tension and shear 10.10.3.7; slip-critical bolts 10.10.3.8-10.10.3.9 (pretension Table 6.10.9,
μ, Du, hsc, ks); bearing 10.10.3.10 Eq 6.10.173a; holes Table 6.10.11, spacing 10.10.3.3,
edges Table 6.10.12, maximum edge 10.10.3.5; net hole width 10.2.3.13.2; elements in tension
10.10.4.1, shear 10.10.4.2, block shear 10.10.4.3, compression 10.10.4.4; fillet welds Table
6.10.7, 10.10.2.2.2, Eqs 6.10.162-163; long bolt patterns in tension splices Table 6.10.10
note [f].

SAEngine practice where the code requires the effect but gives no method (the pack's
``methods`` and its source label them): prying by the T-stub method (Sec 10.10.3.6 asks for the
prying tension), the elastic bolt-group and weld-line methods, the Whitmore width (30° spread)
and gusset buckling K, plate flexure φ Fy Z. The fillet throat 0.707 w is the geometry of an
equal-leg fillet.

Not checked: coped beams and weld access holes, beam web local buckling at copes, the brace net
section with shear lag (a member check), gusset edge buckling, the interface forces of the
uniform force method, A307 bolts with grips over 5 d (Table 6.10.10 note [b]).

Connections 2 (moment connections, splices, column bases and HSS joints), each built only from
the provisions of Part 6 Chapter 10 (the AISC 360-05 provisions; the section numbers follow its
chapter J and K structure):

- ``flangePlate`` (beams, :func:`check_flange_plate`): a bolted flange-plate moment connection.
  The flange force Puf = M / (d + tp); flange plate bolts (Eq 6.10.168), bearing on the plate
  and the beam flange (Eq 6.10.173a), the plate in tension (Eqs 6.10.174-175, An <= 0.85 Ag)
  and in compression (Sec 10.10.4.4, K 0.65 over the setback and end distance), block shear
  of the plate and the beam flange (Eq 6.10.178), the beam's flexural rupture at the flange
  holes (Sec 10.6.13.1), the plate-to-column welds (CJP: the plate governs; fillets Eq
  6.10.162-163 transverse), the web fin plate for the shear (:func:`check_fin_plate`), and the
  column side for the flange force (Sec 10.10.10): flange local bending 6.25 tf² Fy, web local
  yielding (5k + lb) Fy tw, web crippling 0.80 tw² [1 + 3 (lb/d)(tw/tf)^1.5] √(E Fy tf / tw),
  panel zone shear (Eqs 6.10.193-196), web compression buckling, stiffeners and doublers; on an
  HSS column the transverse plate checks of Sec 10.11.1.3.
- ``coverPlate`` splices (beams and columns, :func:`check_splice`): the flange force
  M / (d - tf) plus the flange's share of the axial force (compression left out where the
  ends are finished to bear, Sec 10.10.1.4), checked as the flange plate above on each side of
  the joint, and the web plates (bolts in double shear, bearing on the web, shear yielding
  and rupture, Sec 10.10.4.2) for V and the web's share of the axial force; splices designed
  for the forces at the splice, Sec 10.10.6.
- ``basePlate`` (columns at a support, :func:`check_base_plate`): concrete bearing φc Pp,
  Pp = 0.8 f'c A1 √(A2/A1) <= 1.7 f'c A1 (Sec 10.10.8, as printed), the anchor rods' steel in tension and
  shear as threaded parts (Table 6.10.10: Fnt 0.75 Fu, Fnv 0.40 / 0.50 Fu; combined Sec
  10.10.3.7) and the column-to-plate fillet welds. Track B26: the rods' tension from uplift and
  the base moment (Sec 10.10.9; method ``bearingBlock`` of the pack, a rigid plate on a
  rectangular bearing block) and their anchorage in the concrete by the shared anchor engine
  :mod:`saengine.design.anchors` (Appendix K). The plate thickness by the cantilever method of
  the steel design guides is a planned feature: stated, not checked.
- ``hssJoint`` (braces, :func:`check_hss_joint`): a welded HSS-to-HSS truss joint, Sec 10.11.2:
  round chords (chord plastification of T/Y, X and gapped K joints, punching shear) and
  rectangular chords (chord wall plastification, punching shear, sidewall yielding and
  crippling at β = 1, branch yielding from uneven load), with the limits of applicability as
  checks. The welds are taken to develop the branch.

Built in track B10 (the clauses as printed, part2 pp. 121-171): the column side under the
flange forces Sec 10.10.10.1-10.10.10.9 (flange local bending, web local yielding and crippling
with the reductions near a member end, web sidesway buckling as a function, web compression
buckling, the panel zone Eqs 6.10.193-196, transverse stiffeners and doubler plates); plates on
HSS Sec 10.11.1 (transverse plates on HSS columns, plates along a rectangular HSS, cap plates);
overlapped K joints (round: g = -q in Eq 6.10.214; rectangular Eqs 6.10.232-236); HSS-to-HSS
moment connections Sec 10.11.3 (``hssMoment``, :func:`check_hss_moment`); end plates under
the beam's axial tension (bolt tension with shear and prying).
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
    HssCapPlate,
    HssJointConnection,
    HssMomentConnection,
    SteelSplice,
    _Bolted,
)
from saengine.library.steel_sections import SteelSection

#: The connection kinds that pass no moment (the analysis pins the member ends).
SIMPLE_KINDS = frozenset({"finPlate", "endPlate", "gusset", "hssJoint"})

# ─────────────────────────────────────── data ───────────────────────────────────────
# The bolt grades, holes, edges, welds, slip and concrete bearing values are the code pack's
# (``steel`` table, ``connections`` group; :mod:`saengine.codes.tables` SteelConnectionData).


def steel_table() -> Any:
    """The ``steel`` table of the code pack in force (the built-in default when none is set)."""
    try:
        from saengine.codes import context as code_context

        return code_context.pack_table("steel")
    except Exception:  # noqa: BLE001 - no pack machinery (a bare calculation)
        from saengine.codes.tables import builtin_table

        return builtin_table("steel")


def connection_data() -> Any:
    """The pack's connection data (the default pack's when the pack in force has none)."""
    data = steel_table().connections
    if data is None:
        from saengine.codes.tables import builtin_table

        data = builtin_table("steel").connections
    return data


def clause(key: str) -> str:
    """The clause reference of ``key`` in the steel table's ``sources`` ("" when none)."""
    return steel_table().sources.get(key, "")


def method(key: str) -> str | None:
    """The method id the pack chooses for ``key`` (``connections.methods``); None: not made."""
    return connection_data().methods.get(key)


def __getattr__(name: str) -> Any:
    """``BOLT_GRADES`` and ``BOLT_ALIASES`` read from the pack in force (older callers)."""
    if name == "BOLT_ALIASES":
        return dict(connection_data().boltAliases)
    if name == "BOLT_GRADES":
        return {
            k: {"Fnt": g.Fnt, "Fnv": g.Fnv}
            for k, g in connection_data().boltGrades.items()
            if g.Fnt is not None
        }
    raise AttributeError(name)


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


def grade_id(grade: str) -> str:
    """The pack's bolt grade id of ``grade`` (aliases resolved)."""
    return connection_data().boltAliases.get(grade, grade)


def bolt_grade(grade: str) -> dict[str, float]:
    """``{"Fnt", "Fnv"}`` [MPa] of a bolt grade (the pack's bolt grades table)."""
    g = connection_data().boltGrades[grade_id(grade)]
    return {"Fnt": float(g.Fnt or 0.0), "Fnv": float(g.Fnv or 0.0)}


def hole_diameter(d: float) -> float:
    """Standard hole diameter [mm] (the pack's holes table; larger bolts d + ``holeOver``)."""
    data = connection_data()
    return float(data.holes.get(int(d), d + data.holeOver))


def net_hole(d: float) -> float:
    """Hole width taken off for net areas: the hole + the pack's ``netHoleAllowance``."""
    return hole_diameter(d) + connection_data().netHoleAllowance


def min_edge(d: float, sheared: bool = False) -> float:
    """Least edge distance [mm] from a standard hole (the pack's edge tables)."""
    data = connection_data()
    table = data.edgeSheared if sheared else data.edgeRolled
    if int(d) in table:
        return float(table[int(d)])
    return (data.edgeOverSheared if sheared else data.edgeOverRolled) * d


def min_spacing(d: float) -> float:
    return connection_data().minSpacing * d


def long_joint_factor(length: float, tension_splice: bool) -> float:
    """Factor on Fnv of a bearing-type tension splice with a bolt pattern ``length`` [mm] long
    along the force (1 below the pack's ``longJointLength``)."""
    data = connection_data()
    if tension_splice and length > data.longJointLength:
        return data.longJointFactor
    return 1.0


def bolt_shear_capacity(grade: str, d: float, planes: int = 1, factor: float = 1.0) -> float:
    """φRn of one bolt in shear [N], Rn = Fnv Ab (``factor``: the long-joint reduction)."""
    return phi("bolt", 0.75) * factor * bolt_grade(grade)["Fnv"] * math.pi * d**2 / 4 * planes


def bolt_tension_capacity(grade: str, d: float, frv: float = 0.0) -> tuple[float, str]:
    """φRn of one bolt in tension [N] with the required shear stress ``frv`` [MPa]: Fnt Ab, or
    F'nt = 1.3 Fnt - Fnt / (φ Fnv) frv <= Fnt with shear; and the note."""
    g = bolt_grade(grade)
    p = phi("bolt", 0.75)
    ab = math.pi * d**2 / 4
    fnt = g["Fnt"]
    if frv <= 0:
        return p * fnt * ab, "Eq 6.10.168: Fnt Ab"
    fnt_ = max(min(1.3 * fnt - fnt / (p * g["Fnv"]) * frv, fnt), 0.0)
    return p * fnt_ * ab, f"Eqs 6.10.169-170a: F'nt = {fnt_:.0f} MPa with fv = {frv:.0f} MPa"


def slip_capacity(c: Any, d: float, planes: int = 1, tension: float = 0.0) -> tuple[float, str]:
    """φRn of one pretensioned bolt against slip [N], Rn = μ Du hsc Tb Ns, times ks = 1 - Tu /
    (Du Tb) under the bolt's applied tension ``tension`` [N]; and the note. 0 when the grade is
    not pretensioned."""
    data = connection_data()
    g = data.boltGrades[grade_id(c.boltGrade)]
    family = data.pretension.get(g.pretension or "")
    if not family or int(d) not in family:
        return 0.0, f"{c.boltGrade} M{d:g}: no minimum pretension in the code pack"
    tb = family[int(d)] * 1e3
    slip = data.slip
    mu = slip.mu[c.surfaceClass]
    hsc = slip.hsc[c.holeType]
    p = slip.phiStrength if c.slipCritical == "strength" else slip.phiServiceability
    ks = max(1.0 - tension / (slip.Du * tb), 0.0) if tension > 0 else 1.0
    rn = mu * slip.Du * hsc * tb * planes
    note = (
        f"Eq 6.10.171: φ {p:g} × μ {mu:g} × Du {slip.Du:g} × hsc {hsc:g} × Tb {tb / 1e3:.0f} kN"
        f" × {planes} plane(s)"
    )
    if tension > 0:
        note += f"; Eq 6.10.172a ks = {ks:.2f}"
    return p * rn * ks, note


def slip_checks(
    c: Any,
    label: str,
    per_bolt: float,
    comb: str | None,
    planes: int = 1,
    tension: float = 0.0,
) -> list[dict[str, Any]]:
    """The slip check of a slip-critical connection (none for bearing-type): ``per_bolt`` the
    bolt's shear [N] (factored combinations, also for slip as a serviceability limit: on the
    safe side), ``tension`` its applied tension [N]."""
    if getattr(c, "slipCritical", "none") == "none":
        return []
    cap, note = slip_capacity(c, c.boltDiameter, planes, tension)
    level = "strength" if c.slipCritical == "strength" else "serviceability, factored forces"
    return [
        _check(
            f"{label} slip resistance",
            per_bolt / 1e3,
            cap / 1e3,
            "kN",
            comb,
            f"Sec 10.10.3.8 ({level}): {note}",
        )
    ]


def bearing_capacity(d: float, t: float, fu: float, lc: float) -> float:
    """φRn of one bolt hole in bearing/tear-out [N], Eq 6.10.173a, φ 0.75."""
    return phi("bearing", 0.75) * min(1.2 * max(lc, 0.0) * t * fu, 2.4 * d * t * fu)


def bearing_line(d, t, fu, rows, pitch, end) -> float:
    """Σ bearing of a line of bolts loaded towards the end distance ``end`` (None: no edge
    close by, the 2.4 d t Fu limit)."""
    dh = hole_diameter(d)
    first = (
        bearing_capacity(d, t, fu, end - dh / 2)
        if end is not None
        else bearing_capacity(d, t, fu, math.inf)
    )
    return first + (rows - 1) * bearing_capacity(d, t, fu, pitch - dh)


def block_shear(fy, fu, agv, anv, ant, ubs: float = 1.0) -> float:
    """φRn, Eq 6.10.178, φ 0.75."""
    return phi("blockShear", 0.75) * min(
        0.6 * fu * anv + ubs * fu * ant, 0.6 * fy * agv + ubs * fu * ant
    )


def fillet_capacity_per_mm(w: float, fexx: float, theta_deg: float = 0.0) -> float:
    """φRn of a fillet weld per mm of length [N/mm], Eq 6.10.162-163, φ 0.75, throat 0.707 w."""
    s = math.sin(math.radians(theta_deg))
    return phi("weld", 0.75) * 0.6 * fexx * (1.0 + 0.5 * s**1.5) * 0.707 * w


def fillet_min_size(t_thinner: float) -> float:
    """Least fillet weld leg [mm] by the thinner part joined (the pack's ``filletMin``)."""
    for t_max, leg in connection_data().filletMin:
        if t_max is None or t_thinner <= t_max:
            return float(leg)
    return float(connection_data().filletMin[-1][1])


def fillet_max_size(t_edge: float) -> float:
    """Largest fillet weld leg along an edge [mm]: the thickness below ``filletMaxThin``, else
    the thickness less ``filletMaxReduce``."""
    data = connection_data()
    return t_edge if t_edge < data.filletMaxThin else t_edge - data.filletMaxReduce


def whitmore_width(rows: int, lines: int, pitch: float, gauge: float) -> float:
    """Width of the Whitmore section at the last bolt row: the bolt-group width plus the
    30° spread over the bolt-group length on each side (SAEngine practice: the code gives no
    method, see the pack's ``methods`` source)."""
    return (lines - 1) * gauge + 2 * (rows - 1) * pitch * math.tan(math.radians(30))


def _bolt_rules(c: _Bolted, t_plate: float, lines: int = 1, gauge: float | None = None):
    d = c.boltDiameter
    data = connection_data()
    edge = min_edge(d, c.shearedEdges)
    spacing = min_spacing(d)
    out = []
    if c.rows > 1:
        out.append(
            _min_rule("bolt pitch", c.pitch, spacing, f"Sec 10.10.3.3: {data.minSpacing:.3g} d")
        )
    if lines > 1 and gauge is not None:
        out.append(
            _min_rule("bolt gauge", gauge, spacing, f"Sec 10.10.3.3: {data.minSpacing:.3g} d")
        )
    out.append(_min_rule("end distance", c.endDistance, edge, "Table 6.10.12"))
    out.append(_min_rule("edge distance", c.edgeDistance, edge, "Table 6.10.12"))
    limit = min(data.maxEdgeThickness * t_plate, data.maxEdge)
    out.append(
        _max_rule(
            "largest edge distance",
            max(c.endDistance, c.edgeDistance),
            limit,
            f"Sec 10.10.3.5: {data.maxEdgeThickness:g} t, at most {data.maxEdge:g} mm",
        )
    )
    if getattr(c, "slipCritical", "none") == "none" and getattr(c, "holeType", "standard") != (
        "standard"
    ):
        out.append(
            _check(
                "holes of a bearing-type connection",
                1.0,
                0.0,
                "-",
                None,
                "Sec 10.10.3.2: oversized holes (and slots along the load) need a slip-critical "
                "connection; standard holes taken for the bearing checks",
                flag=True,
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
    support: SteelSection | None = None,
    support_material: SteelMaterial | None = None,
) -> dict[str, Any]:
    """Checks of a fin plate for the beam end shears ``[(combination, V [N])]``; ``support``: a
    rectangular HSS the plate is welded to (the plate along its axis, Sec 10.11.1.5)."""
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
            phi("shearYielding", 1.0) * 0.6 * plate.fy * agv / 1e3,
            "kN",
            comb,
            "Eq 6.10.176, φ 1.00",
        )
    )
    checks.append(
        _check(
            "plate shear rupture",
            v / 1e3,
            phi("shearRupture", 0.75) * 0.6 * plate.fu * anv / 1e3,
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
    phi_mp = phi("plateFlexure", 0.9) * plate.fy * tp * hp**2 / 4
    checks.append(
        _check(
            "plate flexure at the bolt line",
            v * a / 1e6,
            phi_mp / 1e6,
            "kN·m",
            comb,
            "φ Fy Z, SAEngine practice (the code gives no plate flexure rule)",
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
            "Eq 6.10.162-163, θ = 0 (conservative), elastic line method (SAEngine practice)",
        )
    )
    checks += slip_checks(c, "bolt (most loaded)", r_max, comb)
    checks += _bolt_rules(c, tp)
    checks += _weld_rules(c.weldSize, tp, None)
    assumptions = [
        "one vertical line of bolts, single shear, "
        + ("bearing-type" if c.slipCritical == "none" else f"slip-critical ({c.slipCritical})"),
        f"bolt group eccentricity a = {a:g} mm by the elastic method (SAEngine practice, conservative)",
        "beam web uncoped; the support strong enough for the welds",
        "plate edges rolled or thermally cut" if not c.shearedEdges else "sheared edges",
    ]
    if support is not None:
        more, notes = hss_longitudinal_plate_checks(
            support, support_material or beam_material, plate, tp, v, comb
        )
        checks += more
        assumptions += notes
    return _result("finPlate", checks, assumptions)


# ─────────────────────────────────────── end plate ───────────────────────────────────────


def check_end_plate(
    c: EndPlateConnection,
    beam: SteelSection,
    beam_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    shears: list[tuple[str | None, float]],
    forces: list[tuple[str | None, float, float]] | None = None,
) -> dict[str, Any]:
    """Checks of a shear end plate for the beam end shears ``[(combination, V [N])]`` and,
    when given, the end forces ``[(combination, V, N [N], tension +)]`` (bolt tension with
    prying under the beam's axial tension)."""
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
            phi("shearYielding", 1.0) * 0.6 * plate.fy * 2 * hp * tp / 1e3,
            "kN",
            comb,
            "Eq 6.10.176, φ 1.00, two planes",
        )
    )
    checks.append(
        _check(
            "plate shear rupture",
            v / 1e3,
            phi("shearRupture", 0.75) * 0.6 * plate.fu * 2 * (hp - n * dn) * tp / 1e3,
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
            phi("shearYielding", 1.0) * 0.6 * beam_material.fy * beam.tw * hp / 1e3,
            "kN",
            comb,
            "Eq 6.10.176, φ 1.00, the web over the plate height",
        )
    )
    checks += slip_checks(c, "bolt", v / bolts, comb)
    assumptions = [
        "two vertical lines of bolts in standard holes, "
        + ("bearing-type" if c.slipCritical == "none" else f"slip-critical ({c.slipCritical})"),
        "end plate shorter than the beam depth, welded to the web only",
        "support flange of the plate's material, thickness as given",
    ]
    tension_row = _governing_vector(list(forces or []), 2, 1)
    if tension_row is not None:
        more, notes = _end_plate_tension(c, beam, beam_material, plate, tension_row, hp)
        checks += more
        assumptions += notes
    else:
        assumptions.append("no axial tension at the beam ends: the bolts carry shear only")
    checks += _bolt_rules(c, tp, lines=2, gauge=c.gauge)
    checks += _weld_rules(c.weldSize, min(tp, beam.tw), None)
    return _result("endPlate", checks, assumptions)


def prying_capacity(
    b_tension: float, b: float, a: float, p: float, t: float, fu: float, d: float
) -> tuple[float, str]:
    """Available tension of one bolt of a T-stub (end plate) with prying [N], by the T-stub
    method of the steel design manuals (SAEngine practice: the code requires prying in the bolt
    tension, Sec 10.10.3.6, but gives no method): ``b_tension`` the bolt's φRn in tension [N],
    ``b`` bolt line to the face of the web, ``a`` bolt line to the plate edge (<= 1.25 b), ``p``
    the plate length per bolt, ``t`` the plate, ``d`` the bolt [mm]. tc = √(4 B b' / (φ p Fu)),
    α' = [(tc / t)² - 1] / (δ (1 + ρ)), Q = 1 (α' < 0), (t / tc)² (1 + δ α') (0..1) or
    (t / tc)² (1 + δ) (α' > 1)."""
    a = min(a, 1.25 * b)
    b1 = max(b - d / 2, 1e-6)
    a1 = a + d / 2
    rho = b1 / a1
    delta = max(1 - hole_diameter(d) / p, 1e-6)
    tc = math.sqrt(4 * b_tension * b1 / (phi("plateFlexure", 0.9) * p * fu))
    alpha = ((tc / t) ** 2 - 1) / (delta * (1 + rho))
    if alpha < 0:
        q = 1.0
    elif alpha <= 1:
        q = (t / tc) ** 2 * (1 + delta * alpha)
    else:
        q = (t / tc) ** 2 * (1 + delta)
    q = min(q, 1.0)
    note = (
        f"T-stub prying (SAEngine practice): b' = {b1:.0f}, a' = {a1:.0f}, p = {p:.0f} mm, "
        f"tc = {tc:.1f} mm, α' = {alpha:.2f}, Q = {q:.2f}"
    )
    return b_tension * q, note


def _end_plate_tension(
    c: EndPlateConnection,
    beam: SteelSection,
    beam_material: SteelMaterial,
    plate: SteelMaterial,
    row: tuple[Any, ...],
    hp: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The end plate under the beam's axial tension ``row`` = (combination, V, T [N]): bolt
    tension with shear (Sec 10.10.3.7) and prying, the web welds and the web in tension."""
    comb, v, t = row[0], abs(row[1]), row[2]
    d, n, tp = c.boltDiameter, c.rows, c.plateThickness
    bolts = 2 * n
    ab = math.pi * d**2 / 4
    per_bolt = t / bolts
    b_cap, b_note = bolt_tension_capacity(c.boltGrade, d, v / bolts / ab)
    checks: list[dict[str, Any]] = []
    notes = [f"beam axial tension T = {t / 1e3:.1f} kN shared by the {bolts} bolts"]
    if method("prying") == "tStub":
        b = max((c.gauge - beam.tw) / 2, d)
        cap, note = prying_capacity(b_cap, b, c.edgeDistance, hp / n, tp, plate.fu, d)
        checks.append(
            _check(
                "bolt tension with prying",
                per_bolt / 1e3,
                cap / 1e3,
                "kN",
                comb,
                f"Sec 10.10.3.6-10.10.3.7: {b_note}; {note}",
            )
        )
        notes.append(clause("methods") or "prying by the T-stub method")
    else:
        checks.append(_check("bolt tension", per_bolt / 1e3, b_cap / 1e3, "kN", comb, b_note))
        notes.append("prying not checked: the code pack names no method")
    checks += slip_checks(c, "bolt (with tension)", v / bolts, comb, 1, per_bolt)
    f = math.hypot(v, t) / (2 * hp)
    checks.append(
        _check(
            "welds to the beam web (shear and tension)",
            f,
            fillet_capacity_per_mm(c.weldSize, c.electrode),
            "N/mm",
            comb,
            "Eq 6.10.162-163, two welds, θ = 0",
        )
    )
    checks.append(
        _check(
            "beam web tension yielding at the welds",
            t / 1e3,
            phi("tensionYield", 0.9) * beam_material.fy * beam.tw * hp / 1e3,
            "kN",
            comb,
            "Sec 10.10.4.1 Eq 6.10.174 on the web over the plate height",
        )
    )
    return checks, notes


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
        checks += slip_checks(c, f"bolt ({label})", p / bolts, comb, c.shearPlanes)
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
            an = min((lw - m * dn) * tg, steel_table().netAreaMax * ag)
            checks.append(
                _check(
                    "gusset Whitmore yielding",
                    p / 1e3,
                    phi("tensionYield", 0.9) * plate.fy * ag / 1e3,
                    "kN",
                    comb,
                    f"Eq 6.10.174 on the Whitmore width {lw:.0f} mm",
                )
            )
            checks.append(
                _check(
                    "gusset Whitmore rupture",
                    p / 1e3,
                    phi("tensionRupture", 0.75) * plate.fu * an / 1e3,
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
                cap, note = phi("compression", 0.9) * plate.fy * ag, "Eq 6.10.179 (KL/r <= 25)"
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
            "bolts in standard holes, "
            + ("bearing-type" if c.slipCritical == "none" else f"slip-critical ({c.slipCritical})"),
            "hollow and I braces: a slotted-in tab plate welded to the brace"
            if tab
            else "angle/channel bolted through its connected leg/web",
            "gusset-to-frame welds carry the whole brace force (no uniform force method)",
            (
                "Whitmore spread at 30°; gusset buckling as a column of the Whitmore width "
                "(SAEngine practice: the code gives no method)"
            ),
            "the brace's own net section with shear lag is a member check, not here",
        ],
    )


# ─────────────────────────────────────── connections 2: shared ───────────────────────────────────────


def phi(key: str, default: float) -> float:
    """φ ``key`` of the code pack's steel table (``phi``, extra keys allowed); ``default`` when
    the pack in use has none."""
    try:
        table = steel_table().phi
    except Exception:  # noqa: BLE001 - no pack at all: the default given
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
        return phi(
            "compression", 0.9
        ) * m.fy * area, f"Sec 10.10.4.4 Eq 6.10.179, KL/r = {kl_r:.1f} <= 25"
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
    tension_splice: bool = False,
) -> list[dict[str, Any]]:
    """Checks of a bolted flange plate carrying ``force`` [N] along the member flange: bolts,
    bearing, the plate in tension or compression, block shear of the plate and the flange.
    ``tension_splice``: a splice of a member in tension (long bolt patterns reduce Fnv)."""
    d, n, s, tp, m = c.boltDiameter, c.rows, c.pitch, c.plateThickness, c.lines
    dn = net_hole(d)
    bp = (m - 1) * c.gauge + 2 * c.edgeDistance
    edge_flange = (flange.b - (m - 1) * c.gauge) / 2
    bolts = n * m
    pattern = (n - 1) * s
    factor = long_joint_factor(pattern, tension_splice and not compression)
    note = f"Eq 6.10.168, {bolts} bolts in single shear"
    if factor < 1:
        note += f"; Table 6.10.10 [f]: bolt pattern {pattern:.0f} mm long, Fnv × {factor:g}"
    out = [
        _check(
            f"{label} bolt shear",
            force / bolts / 1e3,
            bolt_shear_capacity(c.boltGrade, d, 1, factor) / 1e3,
            "kN",
            comb,
            note,
        )
    ]
    out += slip_checks(c, f"{label} bolt", force / bolts, comb)
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
        an = min((bp - m * dn) * tp, steel_table().netAreaMax * ag)
        out.append(
            _check(
                f"{label} plate tension yielding",
                force / 1e3,
                phi("tensionYield", 0.9) * plate.fy * ag / 1e3,
                "kN",
                comb,
                "Sec 10.10.4.1 Eq 6.10.174",
            )
        )
        out.append(
            _check(
                f"{label} plate tension rupture",
                force / 1e3,
                phi("tensionRupture", 0.75) * plate.fu * an / 1e3,
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


def flange_local_bending(tf: float, fy: float, end_distance: float | None) -> tuple[float, str]:
    """φRn of flange local bending [N], Eq 6.10.185: 6.25 tf² Fyf, halved within 10 tf of the
    member end."""
    rn = 6.25 * tf**2 * fy
    note = "Sec 10.10.10.1 Eq 6.10.185: 6.25 tf² Fyf"
    if end_distance is not None and end_distance < 10 * tf:
        rn *= 0.5
        note += ", × 0.5 within 10 tf of the end"
    return phi("flangeLocalBending", 0.9) * rn, note


def web_local_yielding(
    k: float, n: float, tw: float, fy: float, d: float, end_distance: float | None
) -> tuple[float, str]:
    """φRn of web local yielding [N], Eqs 6.10.186-187: (5k + N) Fyw tw, (2.5k + N) Fyw tw
    within the member depth of the end."""
    near = end_distance is not None and end_distance <= d
    f = 2.5 if near else 5.0
    note = (
        f"Sec 10.10.10.2 Eq {'6.10.187' if near else '6.10.186'}: ({f:g}k + N) Fyw tw, "
        f"k = {k:.0f} mm, N = {n:.0f} mm"
    )
    return phi("webLocalYielding", 1.0) * (f * k + n) * fy * tw, note


def web_crippling(
    n: float, d: float, tw: float, tf: float, fy: float, e: float, end_distance: float | None
) -> tuple[float, str]:
    """φRn of web crippling [N], Eqs 6.10.188-189."""
    root = math.sqrt(e * fy * tf / tw)
    if end_distance is None or end_distance >= d / 2:
        rn = 0.80 * tw**2 * (1 + 3 * (n / d) * (tw / tf) ** 1.5) * root
        note = "Sec 10.10.10.3 Eq 6.10.188: 0.80 tw² [1 + 3 (N/d)(tw/tf)^1.5] √(E Fyw tf / tw)"
    elif n / d <= 0.2:
        rn = 0.40 * tw**2 * (1 + 3 * (n / d) * (tw / tf) ** 1.5) * root
        note = "Sec 10.10.10.3 Eq 6.10.189a (within d/2 of the end, N/d <= 0.2)"
    else:
        rn = 0.40 * tw**2 * (1 + (4 * n / d - 0.2) * (tw / tf) ** 1.5) * root
        note = "Sec 10.10.10.3 Eq 6.10.189b (within d/2 of the end, N/d > 0.2)"
    return phi("webCrippling", 0.75) * rn, note


def web_sidesway_buckling(
    tw: float,
    tf: float,
    h: float,
    bf: float,
    unbraced: float,
    restrained: bool,
    yielded: bool,
) -> tuple[float | None, str]:
    """φRn of web sidesway buckling [N], Eqs 6.10.190-191 (a compressive single force on a
    member whose flanges are not restrained against relative lateral movement there); None
    when the limit state does not apply ((h/tw)/(l/bf) above 2.3 restrained, 1.7 not).
    ``yielded``: Mu >= My at the force (Cr 3.31e6 MPa, else 6.62e6)."""
    cr = 3.31e6 if yielded else 6.62e6
    ratio = (h / tw) / (unbraced / bf)
    if restrained:
        if ratio > 2.3:
            return None, "Sec 10.10.10.4: (h/tw)/(l/bf) > 2.3, does not apply"
        rn = cr * tw**3 * tf / h**2 * (1 + 0.4 * ratio**3)
        eq = "6.10.190"
    else:
        if ratio > 1.7:
            return None, "Sec 10.10.10.4: (h/tw)/(l/bf) > 1.7, does not apply"
        rn = cr * tw**3 * tf / h**2 * (0.4 * ratio**3)
        eq = "6.10.191"
    note = f"Sec 10.10.10.4 Eq {eq}: Cr = {cr:.3g} MPa, (h/tw)/(l/bf) = {ratio:.2f}"
    return phi("webSideswayBuckling", 0.85) * rn, note


def web_compression_buckling(
    tw: float, h: float, fy: float, e: float, d: float, end_distance: float | None
) -> tuple[float, str]:
    """φRn of web compression buckling under a pair of compressive forces [N], Eq 6.10.192:
    24 tw³ √(E Fyw) / h, halved within d/2 of the member end."""
    rn = 24 * tw**3 * math.sqrt(e * fy) / h
    note = "Sec 10.10.10.5 Eq 6.10.192: 24 tw³ √(E Fyw) / h"
    if end_distance is not None and end_distance < d / 2:
        rn *= 0.5
        note += ", × 0.5 within d/2 of the end"
    return phi("webCompressionBuckling", 0.9) * rn, note


def panel_zone_shear(
    fy: float,
    dc: float,
    tw: float,
    axial_ratio: float,
    in_analysis: bool = False,
    bcf: float = 0.0,
    tcf: float = 0.0,
    db: float = 1.0,
    phi_v: float | None = None,
) -> tuple[float, str]:
    """φRn of the web panel zone in shear [N], Eqs 6.10.193-196 (``axial_ratio`` = Pr / Pc,
    Pc = Py). ``phi_v``: a φ of its own (B35: the seismic provisions' special moment frames,
    :mod:`saengine.design.steel.seismic`); None: the pack's panel zone φ."""
    base = 0.60 * fy * dc * tw
    if not in_analysis:
        if axial_ratio <= 0.4:
            rn, eq = base, "6.10.193: 0.60 Fy dc tw"
        else:
            rn, eq = base * (1.4 - axial_ratio), "6.10.194: 0.60 Fy dc tw (1.4 - Pr/Pc)"
    else:
        boost = 1 + 3 * bcf * tcf**2 / (db * dc * tw)
        if axial_ratio <= 0.75:
            rn, eq = base * boost, "6.10.195: 0.60 Fy dc tw (1 + 3 bcf tcf² / (db dc tw))"
        else:
            rn = base * boost * (1.9 - 1.2 * axial_ratio)
            eq = "6.10.196: ... (1.9 - 1.2 Pr/Pc)"
    note = f"Sec 10.10.10.6 Eq {eq}, Pr/Pc = {axial_ratio:.2f}"
    return (phi("panelZone", 0.9) if phi_v is None else phi_v) * rn, note


def column_side_checks(
    force: float,
    comb: str | None,
    column: SteelSection,
    column_material: SteelMaterial,
    bearing_length: float,
    stiffened: bool,
    *,
    loaded_width: float | None = None,
    delivering_thickness: float | None = None,
    end_distance: float | None = None,
    double_sided: bool = False,
    axial_ratio: float = 0.0,
    panel_in_analysis: bool = False,
    beam_depth: float | None = None,
    stiffener_width: float = 0.0,
    stiffener_thickness: float = 0.0,
    doubler: float = 0.0,
    weld: float = 6.0,
    electrode: float = 480.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Checks of a column flange and web under a beam flange force ``force`` [N] (Sec
    10.10.10), and assumptions: flange local bending (tension flange), web local yielding, web
    crippling (compression flange), web compression buckling (beams on both flanges), the panel
    zone (with a doubler plate), and the transverse stiffeners (Sec 10.10.10.8) and doubler
    (Sec 10.10.10.9) when given. ``loaded_width``/``delivering_thickness``: the plate (or
    flange) delivering the force; ``end_distance``: column end to the force [mm]."""
    fy, e = column_material.fy, column_material.E
    tf, tw, dc, bf = column.tf, column.tw, column.h, column.b
    k = tf + column.r
    h = dc - 2 * k
    checks: list[dict[str, Any]] = []
    notes = [
        "column side: the beam flange forces on the column "
        + ("from beams on both flanges" if double_sided else "(one-sided joint)")
        + (
            f", {end_distance:g} mm from the column end"
            if end_distance is not None
            else ", far from the column's ends"
        )
    ]
    local: list[tuple[str, float, str, str]] = []  # name, φRn, note, "t"/"c"/"both"
    if loaded_width is not None and loaded_width < 0.15 * bf:
        notes.append("flange local bending not checked: loaded width < 0.15 bf (Sec 10.10.10.1)")
    else:
        cap, note = flange_local_bending(tf, fy, end_distance)
        local.append(("column flange local bending", cap, note, "t"))
    cap, note = web_local_yielding(k, bearing_length, tw, fy, dc, end_distance)
    local.append(("column web local yielding", cap, note, "both"))
    cap, note = web_crippling(bearing_length, dc, tw, tf, fy, e, end_distance)
    local.append(("column web crippling", cap, note, "c"))
    if double_sided:
        cap, note = web_compression_buckling(tw, h, fy, e, dc, end_distance)
        local.append(("column web compression buckling", cap, note, "c"))
    for name, cap, note, _ in local:
        checks.append(
            _check(
                name,
                force / 1e3,
                cap / 1e3,
                "kN",
                comb,
                note + ("; taken by the stiffeners" if stiffened else ""),
                flag=stiffened,
            )
        )
    # The panel zone: the flange force(s) as the panel shear (the column's storey shear left
    # out, conservative); beams on both flanges taken bending the same way (sway).
    v_panel = force * (2 if double_sided else 1)
    cap, note = panel_zone_shear(
        fy, dc, tw, axial_ratio, panel_in_analysis, bf, tf, beam_depth or dc
    )
    if doubler > 0:
        extra = phi("panelZone", 0.9) * 0.60 * fy * dc * doubler
        note += f"; doubler {doubler:g} mm adds 0.60 Fy dc td (Sec 10.10.10.9, Sec 10.7)"
        cap += extra
    checks.append(_check("column panel zone shear", v_panel / 1e3, cap / 1e3, "kN", comb, note))
    if doubler > 0:
        vd = v_panel * doubler / (tw + doubler)
        checks.append(
            _check(
                "doubler plate edge welds",
                vd / dc,
                fillet_capacity_per_mm(weld, electrode),
                "N/mm",
                comb,
                "Sec 10.10.10.9(b): welds develop the doubler's share td / (tw + td) of the "
                "panel shear, shear flow Vd / dc on each edge, Eq 6.10.162-163",
            )
        )
        notes.append(f"web doubler plate {doubler:g} mm on the panel zone, fillet welded")
    if stiffened:
        more, more_notes = _stiffener_checks(
            force,
            comb,
            column,
            column_material,
            local,
            loaded_width or bf,
            delivering_thickness or tf,
            stiffener_width,
            stiffener_thickness,
            end_distance,
            weld,
            electrode,
        )
        checks += more
        notes += more_notes
    return checks, notes


def _stiffener_checks(
    force: float,
    comb: str | None,
    column: SteelSection,
    m: SteelMaterial,
    local: list[tuple[str, float, str, str]],
    delivering_width: float,
    delivering_thickness: float,
    width: float,
    thickness: float,
    end_distance: float | None,
    weld: float,
    electrode: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """A pair of full-depth transverse stiffeners opposite a beam flange (Sec 10.10.10.8):
    sized for the force the flange and web cannot take (tension and compression), the
    compression pair as a column of the stiffeners and a web strip (0.75 h, 25 tw inside, 12 tw
    at a member end), its welds, and the width and thickness rules."""
    tf, tw, dc, bf = column.tf, column.tw, column.h, column.b
    k = tf + column.r
    h = dc - 2 * k
    bs = width or (bf - tw) / 2
    ts = thickness or delivering_thickness
    clip = max(k - tf, 0.0)
    t_cap = min((c for _, c, _, s in local if s in ("t", "both")), default=math.inf)
    c_cap = min((c for _, c, _, s in local if s in ("c", "both")), default=math.inf)
    need_t = max(force - t_cap, 0.0)
    need_c = max(force - c_cap, 0.0)
    need = max(need_t, need_c)
    area = 2 * bs * ts
    checks = [
        _check(
            "stiffeners in tension",
            need_t / 1e3,
            phi("tensionYield", 0.9) * m.fy * area / 1e3,
            "kN",
            comb,
            "Sec 10.10.10.8 (Sec 10.4): the force less the flange and web strength, Fy As",
        )
    ]
    strip = (12 if end_distance is not None and end_distance <= dc else 25) * tw
    a_col = area + strip * tw
    i_col = ts * (2 * bs + tw) ** 3 / 12
    r = math.sqrt(i_col / a_col)
    kl_r = 0.75 * h / r
    if kl_r <= 25:
        cap_c, note = phi("compression", 0.9) * m.fy * a_col, "Sec 10.10.4.4 Eq 6.10.179"
    else:
        cap_c, note = compression_capacity(a_col, m, kl_r), "Sec 10.5.3"
    checks.append(
        _check(
            "stiffeners as a column (compression)",
            force / 1e3,
            cap_c / 1e3,
            "kN",
            comb,
            f"Sec 10.10.10.8: two stiffeners + {strip:.0f} mm of web, KL = 0.75 h, "
            f"KL/r = {kl_r:.1f}; {note}",
        )
    )
    per_mm = fillet_capacity_per_mm(weld, electrode)
    flange_weld = 2 * 2 * max(bs - clip, 0.0) * per_mm
    web_weld = 2 * 2 * max(h, 0.0) * per_mm
    checks.append(
        _check(
            "stiffener welds to the flange",
            need / 1e3,
            flange_weld / 1e3,
            "kN",
            comb,
            "Sec 10.10.10.8: the difference between the required and available strength, "
            "fillet welds both faces, Eq 6.10.162-163",
        )
    )
    checks.append(
        _check(
            "stiffener welds to the web",
            need / 1e3,
            web_weld / 1e3,
            "kN",
            comb,
            "Sec 10.10.10.8: the force passed to the web, fillet welds both faces",
        )
    )
    checks.append(
        _min_rule(
            "stiffener width + tw / 2",
            bs + tw / 2,
            delivering_width / 3,
            "Sec 10.10.10.8: at least 1/3 of the delivering flange or plate width",
        )
    )
    checks.append(
        _min_rule(
            "stiffener thickness",
            ts,
            max(delivering_thickness / 2, bs / 15),
            "Sec 10.10.10.8(a): at least half the delivering flange or plate and width / 15",
        )
    )
    notes = [
        (
            f"stiffener pair {bs:.0f} × {ts:g} mm, full depth, fillet welded ({weld:g} mm) to the "
            "flange and the web"
        )
    ]
    return checks, notes


# ─────────────────────────────────────── plates on HSS (Sec 10.11.1) ───────────────────────────


def _hss_material_limits(m: SteelMaterial, what: str) -> list[dict[str, Any]]:
    return [
        _limit(f"{what} Fy", m.fy, 360.0, "Sec 10.11.1.2: Fy <= 360 MPa"),
        _limit(f"{what} Fy / Fu", m.fy / m.fu, 0.8, "Sec 10.11.1.2: Fy / Fu <= 0.8"),
    ]


def _qf_round(u: float, compression: bool) -> float:
    """Chord stress factor of round HSS, Eq 6.10.209: 1 - 0.3 U (1 + U) in compression."""
    return 1.0 - 0.3 * u * (1 + u) if compression else 1.0


def _qf_rect(u: float, beta: float, compression: bool) -> float:
    """Chord stress factor of rectangular HSS, Eq 6.10.218: 1.3 - 0.4 U / β <= 1."""
    return min(1.3 - 0.4 * u / beta, 1.0) if compression else 1.0


def hss_transverse_plate_checks(
    force: float,
    comb: str | None,
    hss: SteelSection,
    hss_material: SteelMaterial,
    plate_width: float,
    tp: float,
    plate_material: SteelMaterial,
    u: float = 0.0,
    cross: bool = False,
    welds: tuple[float, float] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """A plate across an HSS wall carrying ``force`` [N] perpendicular to the HSS axis (a beam
    flange plate on an HSS column), Sec 10.11.1.3: round (local yielding, Eq 6.10.197) or
    rectangular (uneven load Eq 6.10.198, punching Eq 6.10.199, sidewall Eqs 6.10.200-202,
    effective weld length Eq 6.10.203). ``u``: the HSS utilisation (compression) for Qf;
    ``welds``: (fillet leg, FEXX) of the plate's fillet welds (None: CJP, not checked)."""
    fy, _fu, e, t = hss_material.fy, hss_material.fu, hss_material.E, hss.tw
    checks = _hss_material_limits(hss_material, "HSS")
    notes = [
        "plate across the HSS wall, perpendicular to its axis"
        + (", plates on both faces (cross)" if cross else "")
    ]
    if hss.shape == "circleHollow":
        d = hss.h
        ratio = plate_width / d
        checks.append(_limit("Bp / D", ratio, 1.0, "Sec 10.11.1.3.1: 0.2 < Bp / D <= 1.0"))
        checks.append(_limit("Bp / D (least)", ratio, 0.2, "Sec 10.11.1.3.1", above=True))
        checks.append(_limit("HSS D / t", d / t, 40.0 if cross else 50.0, "Sec 10.11.1.3.1"))
        qf = _qf_round(u, True)
        rn = fy * t**2 * (5.5 / (1 - 0.81 * min(ratio, 1.0))) * qf
        checks.append(
            _check(
                "HSS wall local yielding",
                force / 1e3,
                phi("hssPlateRound", 0.9) * rn / 1e3,
                "kN",
                comb,
                f"Sec 10.11.1.3.1 Eq 6.10.197: Fy t² [5.5 / (1 - 0.81 Bp/D)] Qf, Qf = {qf:.2f}",
            )
        )
    elif hss.shape == "rectangleHollow":
        b, hh = hss.b, hss.h
        bt = b / t
        beta = plate_width / b
        checks.append(_limit("Bp / B", beta, 1.0, "Sec 10.11.1.3.2: 0.25 < Bp / B <= 1.0"))
        checks.append(_limit("Bp / B (least)", beta, 0.25, "Sec 10.11.1.3.2", above=True))
        checks.append(_limit("HSS B / t", bt, 35.0, "Sec 10.11.1.3.2"))
        rn = min(10 / bt * fy * t * plate_width, plate_material.fy * tp * plate_width)
        checks.append(
            _check(
                "plate local yielding (uneven load)",
                force / 1e3,
                phi("hssPlateUneven", 0.95) * rn / 1e3,
                "kN",
                comb,
                "Sec 10.11.1.3.2 Eq 6.10.198: [10 / (B/t)] Fy t Bp <= Fyp tp Bp",
            )
        )
        if 0.85 * b <= plate_width <= b - 2 * t:
            bep = min(10 * plate_width / bt, plate_width)
            rn = 0.6 * fy * t * (2 * tp + 2 * bep)
            checks.append(
                _check(
                    "HSS wall punching",
                    force / 1e3,
                    phi("hssPlatePunching", 0.95) * rn / 1e3,
                    "kN",
                    comb,
                    f"Sec 10.11.1.3.2 Eq 6.10.199: 0.6 Fy t (2 tp + 2 Bep), Bep = {bep:.0f} mm",
                )
            )
        if beta >= 0.99:
            k = max(hss.r, 1.5 * t)
            n = tp
            checks.append(
                _check(
                    "HSS sidewall local yielding",
                    force / 1e3,
                    phi("hssPlateSidewallYielding", 1.0) * 2 * fy * t * (5 * k + n) / 1e3,
                    "kN",
                    comb,
                    "Sec 10.11.1.3.2 Eq 6.10.200: 2 Fy t (5k + N)",
                )
            )
            qf = _qf_rect(u, beta, True)
            if cross:
                rn = 48 * t**3 / (hh - 3 * t) * math.sqrt(e * fy) * qf
                cap = phi("hssPlateSidewallBuckling", 0.9) * rn
                note = "Eq 6.10.202: 48 t³ / (H - 3t) √(E Fy) Qf"
            else:
                rn = 1.6 * t**2 * (1 + 3 * n / (hh - 3 * t)) * math.sqrt(e * fy) * qf
                cap = phi("hssPlateSidewallCrippling", 0.75) * rn
                note = "Eq 6.10.201: 1.6 t² [1 + 3N / (H - 3t)] √(E Fy) Qf"
            checks.append(
                _check(
                    "HSS sidewall crippling (compression)",
                    force / 1e3,
                    cap / 1e3,
                    "kN",
                    comb,
                    f"Sec 10.11.1.3.2 {note}, Qf = {qf:.2f}",
                )
            )
        if welds is not None:
            le = min(2 * (10 / bt) * (fy * t / (plate_material.fy * tp)) * plate_width,
                     2 * plate_width)  # fmt: skip
            checks.append(
                _check(
                    "plate welds to the HSS (effective length)",
                    force / 1e3,
                    le * fillet_capacity_per_mm(welds[0], welds[1], 90.0) / 1e3,
                    "kN",
                    comb,
                    f"Sec 10.11.1.3.2 Eq 6.10.203: Le = {le:.0f} mm of the welds on both sides",
                )
            )
    else:
        raise ValueError("plates on HSS need a round or rectangular HSS")
    for check in checks:
        if check["unit"] == "":
            check["unit"] = "-"
    return checks, notes


def hss_longitudinal_plate_checks(
    hss: SteelSection,
    hss_material: SteelMaterial,
    plate_material: SteelMaterial,
    tp: float,
    force: float,
    comb: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """A plate along a rectangular HSS's axis carrying a force parallel to it (a beam's fin
    plate on an HSS column), Sec 10.11.1.5 Eq 6.10.206: Fyp tp <= Fu t."""
    if hss.shape != "rectangleHollow":
        return [], [f"support {hss.name}: not a rectangular HSS, its wall not checked"]
    checks = _hss_material_limits(hss_material, "HSS")
    checks.append(
        _check(
            "HSS wall under the plate (Fyp tp <= Fu t)",
            plate_material.fy * tp,
            hss_material.fu * hss.tw,
            "N/mm",
            comb,
            "Sec 10.11.1.5 Eq 6.10.206",
        )
    )
    for check in checks:
        if check["unit"] == "":
            check["unit"] = "-"
    return checks, [f"plate welded along the wall of the HSS column {hss.name}"]


def check_cap_plate(
    c: HssCapPlate,
    column: SteelSection,
    column_material: SteelMaterial,
    demands: list[tuple[str | None, float]],
) -> dict[str, Any]:
    """The walls of a rectangular HSS column under a concentrated axial force on its cap plate
    ``[(combination, P [N] compression +)]``, Sec 10.11.1.6: wall local yielding Eq 6.10.207
    and, in compression, wall local crippling Eq 6.10.208, summed over 4 walls when 5 tp + N
    >= B, else over 2."""
    if column.shape != "rectangleHollow":
        raise ValueError("cap plates are checked on rectangular HSS columns")
    m = column_material
    t, b = column.tw, column.b
    tp, n = c.thickness, c.bearingLength
    walls = 4 if 5 * tp + n >= b else 2
    checks = _hss_material_limits(m, "HSS")
    yield_wall = min(m.fy * t * (5 * tp + n), b * m.fy * t)
    crip_wall = 0.8 * t**2 * (1 + 6 * n / b * (t / tp) ** 1.5) * math.sqrt(m.E * m.fy * tp / t)
    comb, p = _governing(demands)
    if p != 0:
        checks.append(
            _check(
                "HSS wall local yielding",
                abs(p) / 1e3,
                phi("hssCapYielding", 1.0) * walls * yield_wall / 1e3,
                "kN",
                comb,
                f"Sec 10.11.1.6 Eq 6.10.207: Fy t (5 tp + N) <= B Fy t per wall, {walls} walls",
            )
        )
    comb_c, pc = _governing(demands, 1)
    if pc > 0:
        checks.append(
            _check(
                "HSS wall local crippling",
                pc / 1e3,
                phi("hssCapCrippling", 0.75) * walls * crip_wall / 1e3,
                "kN",
                comb_c,
                f"Sec 10.11.1.6 Eq 6.10.208: 0.8 t² [1 + (6N/B)(t/tp)^1.5] √(E Fy tp / t), "
                f"{walls} walls",
            )
        )
    for check in checks:
        if check["unit"] == "":
            check["unit"] = "-"
    return _result(
        "capPlate",
        checks,
        [
            f"cap plate {tp:g} mm, bearing length N = {n:g} mm, {walls} walls take the force",
            (
                "the force acts along the column axis at its top; the plate's own bending and its "
                "welds are not checked"
            ),
        ],
    )


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
                phi("flexure", 0.9) * beam_material.fu * afn / afg * beam.Sx / 1e6,
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
        slipCritical=c.slipCritical,
        surfaceClass=c.surfaceClass,
        holeType=c.holeType,
    )
    web_result = check_fin_plate(
        web, beam, beam_material, plate_material, [(r[0], r[2]) for r in demands]
    )
    checks += [{**w, "name": f"web: {w['name']}"} for w in web_result["checks"]]
    checks += _flange_rules(c, beam)
    assumptions = [
        "flange plates outside the beam flanges, bolts in standard holes, "
        + ("bearing-type" if c.slipCritical == "none" else f"slip-critical ({c.slipCritical})"),
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
        if column.shape in ("rectangleHollow", "circleHollow"):
            more, notes = hss_transverse_plate_checks(
                puf,
                comb,
                column,
                cm,
                bp,
                tp,
                plate,
                c.columnUtilisation,
                c.doubleSided,
                (c.weldSize, c.electrode) if c.plateWeld == "fillet" else None,
            )
            checks += more
            assumptions += notes
        elif not _is_i(column):
            assumptions.append("column side not checked: the column is not an I-section or HSS")
        else:
            lb = tp + (2 * c.weldSize if c.plateWeld == "fillet" else 0.0)
            more, notes = column_side_checks(
                puf,
                comb,
                column,
                cm,
                lb,
                c.columnStiffeners,
                loaded_width=bp,
                delivering_thickness=tp,
                end_distance=c.columnEndDistance,
                double_sided=c.doubleSided,
                axial_ratio=c.columnAxialRatio,
                panel_in_analysis=c.panelZoneInAnalysis,
                beam_depth=beam.h,
                stiffener_width=c.stiffenerWidth,
                stiffener_thickness=c.stiffenerThickness,
                doubler=c.doublerThickness,
                weld=c.weldSize,
                electrode=c.electrode,
            )
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
            tension_splice=True,
        )
        dn = net_hole(c.boltDiameter)
        an = min((b - c.lines * dn) * tf, steel_table().netAreaMax * af)
        checks.append(
            _check(
                "member flange net section rupture",
                tension[0] / 1e3,
                phi("tensionRupture", 0.75) * material.fu * an / 1e3,
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
    checks += slip_checks(c, "web bolt", fw / n, cw, 2)
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
            phi("shearRupture", 0.75) * 0.6 * plate.fu * 2 * (hp - n * dn) * tpw / 1e3,
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
        checks.append(_min_rule("web bolt pitch", s, min_spacing(d), "Sec 10.10.3.3"))
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
    part = connection_data().boltGrades["threadedX" if c.threadsExcluded else "threadedN"]
    fnt = float(part.FntOfFu or 0.0) * c.anchorFu
    fnv = float(part.FnvOfFu or 0.0) * c.anchorFu
    p = phi("anchorRod", 0.75)
    return p * fnt * ab, p * fnv * ab, fnt, fnv


def bearing_on_concrete(c: ColumnBasePlate) -> float:
    """φc Pp [N] (Sec 10.10.8, Eqs 6.10.183-184): Pp = full × f'c A1 on the full concrete area,
    partial × f'c A1 √(A2/A1) <= max × f'c A1 on part of it (the pack's ``concreteBearing*``:
    0.8 / 0.8 / 1.7 as printed in the default pack's BNBC 2020)."""
    data = connection_data()
    a1 = c.length * c.width
    a2 = max((c.supportLength or c.length) * (c.supportWidth or c.width), a1)
    fc = c.concreteStrength
    if a2 <= a1 * (1 + 1e-9):
        pp = data.concreteBearingFull * fc * a1
    else:
        pp = min(
            data.concreteBearingPartial * fc * a1 * math.sqrt(a2 / a1),
            data.concreteBearingMax * fc * a1,
        )
    return phi("concreteBearing", 0.6) * pp


def anchor_points(c: ColumnBasePlate) -> list[tuple[float, float]]:
    """The anchor rods' positions [mm] from the plate centre (x along N, y along B): two rows
    across B at x = ±(N/2 - anchorEdge), each spread evenly within ±(B/2 - anchorEdge) (one rod
    in a row: on the axis)."""
    gx = max(c.length / 2 - c.anchorEdge, 0.0)
    gy = max(c.width / 2 - c.anchorEdge, 0.0)
    rows = (c.anchors - c.anchors // 2, c.anchors // 2)
    points = []
    for x, count in zip((-gx, gx), rows, strict=True):
        for k in range(count):
            y = 0.0 if count == 1 else -gy + 2 * gy * k / (count - 1)
            points.append((x, y))
    return points


def rod_tensions(
    c: ColumnBasePlate, points: list[tuple[float, float]], p: float, m: float
) -> tuple[list[float], dict[str, Any]]:
    """Tension of each anchor rod [N] under the axial force ``p`` (compression +) and the base
    moment ``m`` [N·mm] (a resultant: applied about each plate axis in turn, the worse kept),
    by the pack's ``momentBase`` method, and what it found: ``{"axis", "e", "Y", "need",
    "lever"}`` (``need`` > ``lever``: the plate cannot carry the moment by bearing).

    Method ``bearingBlock``: a rigid plate on a rectangular bearing block of stress
    q = φc Pp / A1 (Sec 10.10.8) over the bearing length Y. No rod tension while
    e = M/P <= N/2 - P/(2qB), Y = N - 2e; beyond it the rods of the outer line on the tension
    side (at f from the centre) balance it: Y = (f + N/2) - √((f + N/2)² - 2P(e + f)/(qB)),
    T = qBY - P. When no bearing length balances it (``need`` > ``lever``), the rods take it about
    the opposite rod line, T = P(e - f)/2f. Under net uplift the rods alone take P and M
    elastically (T = -P/n + M x / Σx²)."""
    if method("momentBase") != "bearingBlock":
        raise ValueError("the code pack names no moment base method")
    n = len(points)
    fp = bearing_on_concrete(c) / (c.length * c.width)
    m = abs(m)
    best: tuple[list[float], dict[str, Any]] | None = None
    for axis, length, width in ((0, c.length, c.width), (1, c.width, c.length)):
        coords = [pt[axis] for pt in points]
        info: dict[str, Any] = {"axis": "N" if axis == 0 else "B", "e": 0.0, "Y": None}
        if p <= 0:
            sxx = sum(x * x for x in coords)
            tension = [max(-p / n + (m * x / sxx if sxx > 0 else 0.0), 0.0) for x in coords]
        else:
            q = fp * width
            e = m / p
            info["e"] = e
            if e <= length / 2 - p / (2 * q):
                info["Y"] = length - 2 * e
                tension = [0.0] * n
            else:
                f = max(coords)
                outer = [i for i, x in enumerate(coords) if x >= f - 1.0]
                lever = f + length / 2
                need = math.sqrt(2 * p * (e + f) / q)
                info.update(need=need, lever=lever)
                if need > lever or f <= 0:
                    total = max(p * (e - f) / (2 * f), 0.0) if f > 0 else math.inf
                    info["Y"] = None
                else:
                    y = lever - math.sqrt(lever**2 - need**2)
                    total = q * y - p
                    info["Y"] = y
                tension = [total / len(outer) if i in outer else 0.0 for i in range(n)]
        worse = best is None or max(tension, default=0.0) > max(best[0], default=0.0)
        if best is not None and "need" in info and "need" not in best[1]:
            worse = worse or info["need"] > info["lever"]
        if worse:
            best = (tension, info)
    assert best is not None
    return best


def _anchor_group(c: ColumnBasePlate, points: list[tuple[float, float]]) -> Any:
    """The rods as an anchor group (:class:`saengine.design.anchors.Group`): the concrete edges
    are the anchorage's ``edgeN``/``edgeB``, else half the concrete support (far without one)."""
    from saengine.design import anchors

    a = c.anchorage
    en = a.edgeN or ((c.supportLength / 2) if c.supportLength else math.inf)
    eb = a.edgeB or ((c.supportWidth / 2) if c.supportWidth else math.inf)
    return anchors.Group(
        points=points,
        diameter=float(c.anchorDiameter),
        fu=c.anchorFu,
        fy=c.anchorFy,
        concrete=c.concreteStrength,
        spec=a,
        edges=(en, en, eb, eb),
        attachment_thickness=c.thickness,
    )


def check_base_plate(
    c: ColumnBasePlate,
    column: SteelSection,
    column_material: SteelMaterial,
    plate_material: SteelMaterial | None,
    demands: list[tuple[str | None, float, float, float]],
    seismic: Any = None,
) -> dict[str, Any]:
    """Checks of a column base plate for the base forces ``[(combination, P [N] compression
    +, V [N] resultant, M [N·mm] resultant)]``: bearing (with the base moment), the anchor rods'
    tension from uplift and moment (Sec 10.10.9) and their steel as threaded parts, their
    anchorage in the concrete (:mod:`saengine.design.anchors`; ``seismic`` its
    :class:`~saengine.design.anchors.SeismicContext`), and the welds."""
    from saengine.design import anchors

    checks: list[dict[str, Any]] = []
    data = connection_data()
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
                f"{clause('concreteBearing').split(' (')[0]}: φc Pp, Pp = "
                f"{data.concreteBearingPartial:g} f'c A1 √(A2/A1) <= "
                f"{data.concreteBearingMax:g} f'c A1",
            )
        )
    points = anchor_points(c)
    n = len(points)
    rows: list[tuple[str | None, list[float], float]] = []
    block: tuple[float, float, str | None] | None = None
    for comb, p, v, m in demands:
        tension, info = rod_tensions(c, points, p, m)
        rows.append((comb, tension, v))
        if "need" in info and (block is None or info["need"] / info["lever"] > block[0] / block[1]):
            block = (info["need"], info["lever"], comb)
    if block is not None:
        checks.append(
            _check(
                "moment base: plate length for the bearing block",
                block[0],
                block[1],
                "mm",
                block[2],
                "√(2P(e + f)/(qB)) <= f + N/2, q = φc Pp / A1 (method bearingBlock: "
                f"{clause('methods').split(' (')[0]})",
            )
        )
    t_rod, v_rod, fnt, fnv = anchor_capacities(c)
    governing = max(rows, key=lambda r: max(r[1], default=0.0), default=None)
    if governing is not None and max(governing[1], default=0.0) > 0:
        comb, tension, v = governing
        frt = max(tension)
        checks.append(
            _check(
                "anchor rod tension",
                frt / 1e3,
                t_rod / 1e3,
                "kN",
                comb,
                f"{clause('anchorRods').split(' (')[0]}, Eq 6.10.168, Table 6.10.10: 0.75 Fu; "
                "from uplift and the base moment",
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
    shear = _governing_vector(demands, 2)
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
    # The rods' anchorage in the concrete (the shared anchor engine).
    anchorage = anchors.check_group(
        _anchor_group(c, points),
        [anchors.Demand(comb, tension, v) for comb, tension, v in rows],
        seismic,
    )
    checks += [{**k, "name": f"anchorage: {k['name']}"} for k in anchorage["checks"]]
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
            (
                f"{n} anchor rods in two rows across B, {c.anchorEdge:g} mm in from the plate "
                "edges; the base moment (the resultant of both axes) about each plate axis in "
                "turn, the worse kept: a rigid plate on a rectangular bearing block at φc Pp / A1 "
                "with the outer rods in tension (SAEngine practice); under net uplift the rods "
                "alone"
            ),
            "the base shear taken by the anchor rods in bearing (no friction, no shear key)",
            *anchorage["assumptions"],
            "not checked (planned feature): the plate thickness (cantilever method)",
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
    overlapped: SteelSection | None = None,
    overlapped_material: SteelMaterial | None = None,
) -> dict[str, Any]:
    """Checks of a welded HSS-to-HSS truss joint for the branch axial forces ``[(combination,
    N [N], tension +)]`` (Sec 10.11.2): T/Y, cross, gapped K and overlapped K joints (this brace
    the overlapping branch; ``overlapped`` the other, thru branch, default this brace's
    section)."""
    cm = chord_material or branch_material
    fy, fu, e = cm.fy, cm.fu, cm.E
    fyb = branch_material.fy
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
    lap = c.joint == "KOverlap"
    k_joint = c.joint in ("K", "KOverlap")
    other = overlapped or branch
    other_m = overlapped_material or branch_material
    if lap and other.shape != branch.shape:
        raise ValueError(
            "the overlapped branch must be of the brace's shape (round or rectangular)"
        )
    ref = "Sec 10.11.2"
    checks.append(_limit("chord Fy", fy, 360.0, f"{ref}: Fy <= 360 MPa"))
    checks.append(_limit("chord Fy / Fu", fy / fu, 0.8, f"{ref}: Fy / Fu <= 0.8"))
    checks.append(_limit("branch Fy", fyb, 360.0, f"{ref}: Fy <= 360 MPa"))
    checks.append(_limit("branch Fy / Fu", fyb / branch_material.fu, 0.8, f"{ref}: Fy / Fu <= 0.8"))
    capacities: list[tuple[str, float, str, bool]] = []  # name, φPn, note, compression only
    overlap_note = None
    if lap:
        checks.append(_limit("overlap Ov", c.overlap, 100.0, f"{ref}: 25 % <= Ov <= 100 %"))
        checks.append(_limit("overlap Ov (least)", c.overlap, 25.0, ref, above=True))
        checks.append(
            _limit(
                "overlapping / overlapped branch thickness",
                branch.tw / other.tw,
                1.0,
                f"{ref}: the overlapping branch no thicker than the overlapped one",
            )
        )
    if round_:
        ref = "Sec 10.11.2.2"
        dc, db, tb = chord.h, branch.h, branch.tw
        beta = db / dc
        gamma = dc / (2 * t)
        qf = _qf_round(c.chordUtilisation, c.chordCompression)
        checks.append(_limit("chord D / t", dc / t, 40.0 if c.joint == "X" else 50.0, ref))
        checks.append(_limit("branch D / t (tension)", db / tb, 50.0, ref))
        checks.append(
            _limit("branch D / t (compression)", db / tb, 0.05 * e / fyb, f"{ref}: 0.05 E / Fy")
        )
        checks.append(_limit("β = Db / D", beta, 1.0, f"{ref}: β <= 1.0"))
        least = 0.4 if c.joint == "K" else 0.2
        checks.append(
            _limit("β = Db / D (least)", beta, least, f"{ref}: β >= {least:g}", above=True)
        )
        p_pl = phi("hssPlastification", 0.9)
        if c.joint == "TY":
            pn = fy * t**2 * (3.1 + 15.6 * beta**2) * gamma**0.2 * qf / sin
            note = "Eq 6.10.211: Fy t² (3.1 + 15.6 β²) γ^0.2 Qf / sin θ"
        elif c.joint == "X":
            pn = fy * t**2 * (5.7 / (1 - 0.81 * beta)) * qf / sin
            note = "Eq 6.10.213: Fy t² (5.7 / (1 - 0.81 β)) Qf / sin θ"
        else:
            if lap:
                q = c.overlap / 100 * db / sin
                g = -q
                gap_note = f"overlapped: g = -q = {g:.0f} mm"
            else:
                g = c.gap
                gap_note = f"g = {g:g} mm"
                checks.append(
                    _limit("gap g", c.gap, 2 * tb, f"{ref}: g >= tb,comp + tb,tens", above=True)
                )
            qg = gamma**0.2 * (1 + 0.024 * gamma**1.2 / (math.exp(0.5 * g / t - 1.33) + 1))
            pn = fy * t**2 * (2.0 + 11.33 * db / dc) * qg * qf / sin
            note = (
                f"Eqs 6.10.214-216: Fy t² (2.0 + 11.33 Db / D) Qg Qf / sin θ, Qg = {qg:.2f}, "
                + gap_note
            )
        capacities.append(
            ("chord plastification", p_pl * pn, f"{ref} {note}, Qf = {qf:.2f}", False)
        )
        if beta <= 1 - 1 / gamma and not lap:
            pn = 0.6 * fy * t * math.pi * db * (1 + sin) / (2 * sin**2)
            if c.joint == "K":
                p_ps, eq = phi("hssPunchingRoundK", 0.9), "6.10.217"
            else:
                p_ps, eq = phi("hssPunching", 0.95), "6.10.212"
            capacities.append(
                (
                    "chord punching shear",
                    p_ps * pn,
                    f"{ref} Eq {eq}: 0.6 Fy t π Db (1 + sin θ) / (2 sin² θ), φ {p_ps:g}",
                    False,
                )
            )
    else:
        ref = "Sec 10.11.2.3"
        bc, hc = chord.b, chord.h
        bb, hb, tb = branch.b, branch.h, branch.tw
        beta = bb / bc
        gamma = bc / (2 * t)
        eta = hb / sin / bc
        n_len = hb / sin
        u = c.chordUtilisation
        beta_eff = (bb + hb + other.b + other.h) / (4 * bc)
        qf = _qf_rect(u, beta_eff if c.joint == "K" else beta, c.chordCompression)
        beop = min(5 * beta / gamma, beta)
        root = math.sqrt(e / fyb)
        checks.append(_limit("chord B / t", bc / t, 30.0 if lap else 35.0, ref))
        checks.append(_limit("chord H / t", hc / t, 30.0 if lap else 35.0, ref))
        checks.append(_limit("branch B / t (tension)", bb / tb, 35.0, ref))
        comp = (1.1 if lap else 1.25) * root
        checks.append(
            _limit(
                "branch B / t (compression)",
                bb / tb,
                comp if lap else min(comp, 35.0),
                f"{ref}: {'1.1' if lap else '1.25'} √(E / Fyb)" + ("" if lap else ", 35"),
            )
        )
        checks.append(_limit("chord H / B", hc / bc, 2.0, f"{ref}: 0.5 <= H / B <= 2.0"))
        checks.append(_limit("chord H / B (least)", hc / bc, 0.5, ref, above=True))
        checks.append(_limit("branch H / B", hb / bb, 2.0, f"{ref}: 0.5 <= Hb / Bb <= 2.0"))
        checks.append(_limit("branch H / B (least)", hb / bb, 0.5, ref, above=True))
        if c.joint == "K":
            checks.append(
                _limit("β (least)", beta, 0.35, f"{ref}.3: β >= 0.35 (gapped K)", above=True)
            )
            checks.append(
                _limit("βeff (least)", beta_eff, 0.35, f"{ref}.3(b): βeff >= 0.35", above=True)
            )
            checks.append(
                _limit(
                    "Bb / B",
                    beta,
                    0.1 + gamma / 50,
                    f"{ref}.3(a): Bb / B >= 0.1 + γ / 50",
                    above=True,
                )
            )
            checks.append(
                _limit(
                    "gap g / B",
                    c.gap / bc,
                    0.5 * (1 - beta_eff),
                    f"{ref}.3(c): ζ = g / B >= 0.5 (1 - βeff)",
                    above=True,
                )
            )
            checks.append(
                _limit(
                    "gap g", c.gap, tb + other.tw, f"{ref}.3(d): g >= tb,comp + tb,tens", above=True
                )
            )
            checks.append(
                _limit(
                    "smaller / larger branch width",
                    min(bb, other.b) / max(bb, other.b),
                    0.63,
                    f"{ref}.3(e): > 0.63",
                    above=True,
                )
            )
            pn = fy * t**2 * (9.8 * beta_eff * gamma**0.5) * qf / sin
            capacities.append(
                (
                    "chord wall plastification",
                    phi("hssPlastification", 0.9) * pn,
                    (
                        f"{ref}.3 Eq 6.10.228: Fy t² (9.8 βeff γ^0.5) Qf / sin θ, βeff = "
                        f"{beta_eff:.2f}, Eq 6.10.219 Qf = {qf:.2f}"
                    ),
                    False,
                )
            )
            square = abs(bb - hb) < 1e-6
            if bb < bc - 2 * t or not square:
                pn = 0.6 * fy * t * bc * (2 * eta + beta + beop) / sin
                capacities.append(
                    (
                        "chord punching shear",
                        phi("hssPunching", 0.95) * pn,
                        f"{ref}.3 Eq 6.10.229: 0.6 Fy t B (2η + β + βeop) / sin θ",
                        False,
                    )
                )
            if not square or bc / t < 15:
                beoi = min(10 / (bc / t) * (fy * t / (fyb * tb)) * bb, bb)
                pn = fyb * tb * (2 * hb + bb + beoi - 4 * tb)
                capacities.append(
                    (
                        "branch yielding (uneven load)",
                        phi("hssBranchYielding", 0.95) * pn,
                        f"{ref}.3 Eq 6.10.230: Fyb tb (2Hb + Bb + beoi - 4tb)",
                        False,
                    )
                )
        elif lap:
            checks.append(_limit("β (least)", beta, 0.25, f"{ref}: β >= 0.25", above=True))
            checks.append(
                _limit(
                    "overlapping / overlapped branch width",
                    bb / other.b,
                    0.75,
                    f"{ref}.1(i): >= 0.75",
                    above=True,
                )
            )
            ov = c.overlap
            beoi = min(10 / (bc / t) * (fy * t / (fyb * tb)) * bb, bb)
            beov = min(10 / (other.b / other.tw) * (other_m.fy * other.tw / (fyb * tb)) * bb, bb)
            if ov < 50:
                pn = fyb * tb * (ov / 50 * (2 * hb - 4 * tb) + beoi + beov)
                eq = "6.10.232: Fybi tbi [(Ov/50)(2Hbi - 4tbi) + beoi + beov]"
            elif ov < 80:
                pn = fyb * tb * (2 * hb - 4 * tb + beoi + beov)
                eq = "6.10.233: Fybi tbi (2Hbi - 4tbi + beoi + beov)"
            else:
                pn = fyb * tb * (2 * hb - 4 * tb + bb + beov)
                eq = "6.10.234: Fybi tbi (2Hbi - 4tbi + Bbi + beov)"
            p_lap = phi("hssBranchYielding", 0.95)
            capacities.append(
                (
                    "overlapping branch yielding (uneven load)",
                    p_lap * pn,
                    f"{ref}.4 Eq {eq}, beoi = {beoi:.0f}, beov = {beov:.0f} mm",
                    False,
                )
            )
            ratio = (other.A * other_m.fy) / (branch.A * fyb)
            capacities.append(
                (
                    "overlapped branch yielding (uneven load)",
                    p_lap * pn * ratio,
                    (
                        f"{ref}.4: the overlapping branch's Pn × Abj Fybj / (Abi Fybi) = × {ratio:.2f} "
                        "(both branches carry the brace force)"
                    ),
                    False,
                )
            )
        else:
            checks.append(_limit("β (least)", beta, 0.25, f"{ref}.2: β >= 0.25", above=True))
            if beta <= 0.85:
                pn = fy * t**2 * (2 * eta / (1 - beta) + 4 / math.sqrt(1 - beta)) * qf / sin
                capacities.append(
                    (
                        "chord wall plastification",
                        phi("hssPlastificationRect", 1.0) * pn,
                        (
                            f"{ref}.2 Eq 6.10.221: Fy t² [2η / (1 - β) + 4 / √(1 - β)] Qf / sin θ, "
                            f"Qf = {qf:.2f}"
                        ),
                        False,
                    )
                )
            punching = beta <= 1 - 1 / gamma and (beta >= 0.85 or bc / t < 10)
            if punching:
                pn = 0.6 * fy * t * bc * (2 * eta + 2 * beop) / sin
                capacities.append(
                    (
                        "chord punching shear",
                        phi("hssPunching", 0.95) * pn,
                        f"{ref}.2 Eq 6.10.222: 0.6 Fy t B (2η + 2βeop) / sin θ",
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
                        f"{ref}.2 Eq 6.10.223: 2 Fy t (5k + N) / sin θ",
                        False,
                    )
                )
                if c.joint == "TY":
                    pn = 1.6 * t**2 * (1 + 3 * n_len / (hc - 3 * t)) * math.sqrt(e * fy) * qf / sin
                    p_cr = phi("hssSidewallCripplingTY", 0.75)
                    note = "Eq 6.10.224: 1.6 t² [1 + 3N / (H - 3t)] √(E Fy) Qf / sin θ"
                else:
                    pn = 48 * t**3 / (hc - 3 * t) * math.sqrt(e * fy) * qf / sin
                    p_cr = phi("hssSidewallCripplingX", 0.9)
                    note = "Eq 6.10.225: 48 t³ / (H - 3t) √(E Fy) Qf / sin θ"
                capacities.append(("chord sidewall crippling", p_cr * pn, f"{ref}.2 {note}", True))
                if c.joint == "X" and c.angle < 90:
                    overlap_note = (
                        "cross joint at θ < 90°: the chord sidewall shear (Sec 10.7.5) is a "
                        "member check, not made here"
                    )
            if beta > 0.85:
                beoi = min(10 / (bc / t) * (fy * t / (fyb * tb)) * bb, bb)
                pn = fyb * tb * (2 * hb + 2 * beoi - 4 * tb)
                capacities.append(
                    (
                        "branch yielding (uneven load)",
                        phi("hssBranchYielding", 0.95) * pn,
                        f"{ref}.2 Eq 6.10.226: Fyb tb (2Hb + 2beoi - 4tb)",
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
    joint = {"TY": "T or Y", "X": "cross (X)", "K": "gapped K", "KOverlap": "overlapped K"}[c.joint]
    assumptions = [
        f"{'round' if round_ else 'rectangular'} {joint} joint, θ = {c.angle:g}°, chord {chord.name}",
        f"chord in compression, utilisation U = {c.chordUtilisation:g}"
        if c.chordCompression
        else "chord in tension (Qf = 1)",
        "the welds develop the branch (not checked)",
    ]
    if k_joint:
        assumptions.append(
            "K joints: the other branch "
            + (f"{other.name}" if overlapped is not None else "of this section")
            + ", loaded in the opposite sense with the same force"
        )
    if lap:
        assumptions.append(f"overlap Ov = {c.overlap:g} %, this brace overlapping the other")
    if rect and c.joint == "K" and abs(hc - bc) > 1e-6:
        assumptions.append(
            "chord shear in the gap of a non-square chord (Sec 10.7) is a member check, not here"
        )
    if overlap_note:
        assumptions.append(overlap_note)
    return _result("hssJoint", checks, assumptions)


# ─────────────────────────────────────── HSS moment connections ───────────────────────────────


def check_hss_moment(
    c: HssMomentConnection,
    branch: SteelSection,
    branch_material: SteelMaterial,
    chord: SteelSection,
    chord_material: SteelMaterial | None,
    demands: list[tuple[str | None, float, float, float]],
) -> dict[str, Any]:
    """Checks of a welded HSS-to-HSS moment connection (Sec 10.11.3) for the beam end forces
    ``[(combination, N [N] tension +, Mip [N·mm], Mop [N·mm])]``: the branch axial strength of
    a T/Y or cross joint (Sec 10.11.2), the in-plane and out-of-plane moment strengths, and
    the interaction Eq 6.10.247 (round) or Eq 6.10.260 (rectangular)."""
    cm = chord_material or branch_material
    fy, _fu, e = cm.fy, cm.fu, cm.E
    fyb = branch_material.fy
    t = chord.tw
    sin = math.sin(math.radians(c.angle))
    round_ = chord.shape == "circleHollow" and branch.shape == "circleHollow"
    rect = chord.shape == "rectangleHollow" and branch.shape == "rectangleHollow"
    if not (round_ or rect):
        raise ValueError(
            "HSS moment connections need a round branch on a round chord or rectangular on "
            "rectangular"
        )
    cross = c.joint == "X"
    checks = _hss_material_limits(cm, "chord")
    checks += _hss_material_limits(branch_material, "branch")
    if round_:
        ref = "Sec 10.11.3.2"
        dc, db, tb = chord.h, branch.h, branch.tw
        beta, gamma = db / dc, dc / (2 * t)
        qf = _qf_round(c.chordUtilisation, c.chordCompression)
        checks.append(_limit("chord D / t", dc / t, 40.0 if cross else 50.0, f"{ref}.1(b)"))
        checks.append(_limit("branch D / t (tension)", db / tb, 50.0, f"{ref}.1(c)"))
        checks.append(
            _limit(
                "branch D / t (compression)", db / tb, 0.05 * e / fyb, f"{ref}.1(d): 0.05 E / Fy"
            )
        )
        checks.append(_limit("β = Db / D", beta, 1.0, f"{ref}.1(e): 0.2 < β <= 1.0"))
        checks.append(_limit("β = Db / D (least)", beta, 0.2, f"{ref}.1(e)", above=True))
        if cross:
            pn = fy * t**2 * (5.7 / (1 - 0.81 * beta)) * qf / sin
            p_eq = "6.10.213"
        else:
            pn = fy * t**2 * (3.1 + 15.6 * beta**2) * gamma**0.2 * qf / sin
            p_eq = "6.10.211"
        p_cap = phi("hssPlastification", 0.9) * pn
        p_note = f"Sec 10.11.2.2 Eq {p_eq}"
        punch = beta <= 1 - 1 / gamma
        if punch:
            p_cap = min(
                p_cap,
                phi("hssPunching", 0.95) * 0.6 * fy * t * math.pi * db * (1 + sin) / (2 * sin**2),
            )
            p_note += ", 6.10.212"
        mip = (
            phi("hssMomentPlastification", 0.9)
            * 5.39
            * fy
            * t**2
            * gamma**0.5
            * beta
            * db
            * qf
            / sin
        )
        mip_note = "Eq 6.10.243: 5.39 Fy t² γ^0.5 β Db Qf / sin θ"
        mop = (
            phi("hssMomentPlastification", 0.9)
            * fy
            * t**2
            * db
            * (3.0 / (1 - 0.81 * beta))
            * qf
            / sin
        )
        mop_note = "Eq 6.10.245: Fy t² Db [3.0 / (1 - 0.81 β)] Qf / sin θ"
        if punch:
            p_ps = phi("hssMomentPunching", 0.95)
            mip_ps = p_ps * 0.6 * fy * t * db**2 * (1 + 3 * sin) / (4 * sin**2)
            mop_ps = p_ps * 0.6 * fy * t * db**2 * (3 + sin) / (4 * sin**2) * qf
            if mip_ps < mip:
                mip, mip_note = mip_ps, "Eq 6.10.244: 0.6 Fy t Db² (1 + 3 sin θ) / (4 sin² θ)"
            if mop_ps < mop:
                mop, mop_note = mop_ps, "Eq 6.10.246: 0.6 Fy t Db² (3 + sin θ) / (4 sin² θ) Qf"
        interaction_eq = "Eq 6.10.247: P/φPn + (Mip/φMip)² + Mop/φMop"
        squared = True
    else:
        ref = "Sec 10.11.3.3"
        bc, hc = chord.b, chord.h
        bb, hb, tb = branch.b, branch.h, branch.tw
        beta, gamma = bb / bc, bc / (2 * t)
        eta = hb / bc
        qf = _qf_rect(c.chordUtilisation, beta, c.chordCompression)
        checks.append(_limit("branch angle", c.angle, 90.0, f"{ref}.1(a): about 90°", above=True))
        checks.append(_limit("chord B / t", bc / t, 35.0, f"{ref}.1(b)"))
        checks.append(_limit("branch B / t (tension)", bb / tb, 35.0, f"{ref}.1(c)"))
        checks.append(
            _limit(
                "branch B / t (compression)",
                bb / tb,
                min(1.25 * math.sqrt(e / fyb), 35.0),
                f"{ref}.1(d): 1.25 √(E / Fyb), 35",
            )
        )
        checks.append(_limit("β (least)", beta, 0.25, f"{ref}.1(e): >= 0.25", above=True))
        checks.append(_limit("chord H / B", hc / bc, 2.0, f"{ref}.1(f): 0.5 to 2.0"))
        checks.append(_limit("chord H / B (least)", hc / bc, 0.5, f"{ref}.1(f)", above=True))
        checks.append(_limit("branch H / B", hb / bb, 2.0, f"{ref}.1(f): 0.5 to 2.0"))
        checks.append(_limit("branch H / B (least)", hb / bb, 0.5, f"{ref}.1(f)", above=True))
        # The branch axial strength: T/Y or cross joint of Sec 10.11.2.3.2.
        axial_joint = HssJointConnection(
            joint="X" if cross else "TY",
            angle=c.angle,
            chordCompression=c.chordCompression,
            chordUtilisation=c.chordUtilisation,
        )
        axial = check_hss_joint(
            axial_joint, branch, branch_material, chord, cm, [("_", 1.0), ("_", -1.0)]
        )
        caps = [x["capacity"] * 1e3 for x in axial["checks"] if x["unit"] == "kN"]
        p_cap = min(caps) if caps else math.inf
        p_note = "Sec 10.11.2.3.2"
        fy_star = (0.8 if cross else 1.0) * fy
        cands_ip: list[tuple[float, str]] = []
        cands_op: list[tuple[float, str]] = []
        if beta <= 0.85:
            cands_ip.append(
                (
                    phi("hssMomentPlastificationRect", 1.0)
                    * fy * t**2 * hb * (1 / (2 * eta) + 2 / math.sqrt(1 - beta) + eta / (1 - beta))
                    * qf,
                    "Eq 6.10.251: Fy t² Hb [1/(2η) + 2/√(1-β) + η/(1-β)] Qf",
                )
            )  # fmt: skip
            cands_op.append(
                (
                    phi("hssMomentPlastificationRect", 1.0)
                    * fy * t**2
                    * (0.5 * hb * (1 + beta) / (1 - beta)
                       + math.sqrt(2 * bc * bb * (1 + beta) / (1 - beta)))
                    * qf,
                    "Eq 6.10.255: Fy t² [0.5 Hb (1+β)/(1-β) + √(2 B Bb (1+β)/(1-β))] Qf",
                )
            )  # fmt: skip
        else:
            cands_ip.append(
                (
                    phi("hssMomentSidewall", 1.0) * 0.5 * fy_star * t * (hb + 5 * t) ** 2,
                    "Eq 6.10.252: 0.5 Fy* t (Hb + 5t)²",
                )
            )
            cands_op.append(
                (
                    phi("hssMomentSidewall", 1.0) * fy_star * t * (bc - t) * (hb + 5 * t),
                    "Eq 6.10.256: Fy* t (B - t)(Hb + 5t)",
                )
            )
            beoi = min(10 / (bc / t) * (fy * t / (fyb * tb)) * bb, bb)
            zb_ip = branch.Zx
            zb_op = branch.Zy
            cands_ip.append(
                (
                    phi("hssMomentUneven", 0.95) * fyb * (zb_ip - (1 - beoi / bb) * bb * hb * tb),
                    "Eq 6.10.253: Fyb [Zb - (1 - beoi/Bb) Bb Hb tb]",
                )
            )
            cands_op.append(
                (
                    phi("hssMomentUneven", 0.95)
                    * fyb
                    * (zb_op - 0.5 * (1 - beoi / bb) ** 2 * bb**2 * tb),
                    "Eq 6.10.257: Fyb [Zb - 0.5 (1 - beoi/Bb)² Bb² tb]",
                )
            )
        if not cross and not c.distortionPrevented:
            cands_op.append(
                (
                    phi("hssMomentDistortion", 1.0)
                    * 2 * fy * t * (hb * t + math.sqrt(bc * hc * t * (bc + hc))),
                    "Eq 6.10.259: 2 Fy t [Hb t + √(B H t (B + H))] (chord distortion)",
                )
            )  # fmt: skip
        mip, mip_note = min(cands_ip)
        mop, mop_note = min(cands_op)
        interaction_eq = "Eq 6.10.260: P/φPn + Mip/φMip + Mop/φMop"
        squared = False
    worst = None
    for comb, n, m_ip, m_op in demands:
        ratio = abs(n) / p_cap + (abs(m_ip) / mip) ** (2 if squared else 1) + abs(m_op) / mop
        if worst is None or ratio > worst[0]:
            worst = (ratio, comb, n, m_ip, m_op)
    if worst is not None:
        ratio, comb, n, m_ip, m_op = worst
        row = max(demands, key=lambda r: abs(r[2]))
        checks.append(
            _check(
                "in-plane moment strength",
                abs(row[2]) / 1e6,
                mip / 1e6,
                "kN·m",
                row[0],
                f"{ref} {mip_note}",
            )
        )
        row = max(demands, key=lambda r: abs(r[3]))
        checks.append(
            _check(
                "out-of-plane moment strength",
                abs(row[3]) / 1e6,
                mop / 1e6,
                "kN·m",
                row[0],
                f"{ref} {mop_note}",
            )
        )
        row = max(demands, key=lambda r: abs(r[1]))
        checks.append(
            _check(
                "branch axial strength",
                abs(row[1]) / 1e3,
                p_cap / 1e3,
                "kN",
                row[0],
                p_note,
            )
        )
        checks.append(
            _check(
                "axial force and moments",
                ratio,
                1.0,
                "-",
                comb,
                f"{ref} {interaction_eq}: N = {n / 1e3:.1f} kN, Mip = {m_ip / 1e6:.1f}, "
                f"Mop = {m_op / 1e6:.1f} kN·m",
            )
        )
    for check in checks:
        if check["unit"] == "":
            check["unit"] = "-"
    return _result(
        "hssMoment",
        checks,
        [
            (
                f"{'round' if round_ else 'rectangular'} {'cross' if cross else 'T or Y'} moment "
                f"connection to the chord {chord.name}, θ = {c.angle:g}°"
            ),
            (
                "in-plane moment: the beam's major-axis end moment; out-of-plane: its minor-axis "
                "end moment"
            ),
            f"chord in compression, utilisation U = {c.chordUtilisation:g}"
            if c.chordCompression
            else "chord in tension (Qf = 1)",
            "the welds develop the branch (not checked); the beam end is kept rigid",
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
