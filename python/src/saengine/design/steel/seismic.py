"""Capacity design of steel seismic load resisting systems: the general requirements and the
moment frames (special, intermediate, ordinary and special truss moment frames).

Every number is the code pack's ``steelSeismic`` table (BNBC 2020: Part 6 Sec 10.20.1-10.20.12,
Tables 6.10.17-6.10.18, Appendix N); every clause reference comes from the table's
``sources``. The table's ``systems`` maps the structural systems of Project Settings to the
frame kind (``frames``) their members follow; B38 adds the braced frames, plate walls and
composite systems to the same table and module.

What is built:

- **When the provisions apply** (:func:`provisions`): R taken above ``trigger.rAbove`` for a
  system the table maps; the strictest frame kind of the systems in use governs.
- **Expected strengths** (:func:`expected_ratios`): Ry and Rt of the steel by the table's rows
  (grade, standard, id or name matched; Fy ranges), the largest of the table otherwise.
- **Members** (:func:`member_checks`): Fy of members expected to yield; heavy-section
  toughness (flags); seismically compact (or compact) width-thickness ratios with Ca; the
  lateral bracing of beams (Lb ≤ c ry E / Fy) and the brace force next to the hinges; column
  strength under the amplified seismic load when Pu / φPn exceeds the table's ratio.
- **Beam-to-column connections** (:func:`connection_shear`): the required shear with
  E = 2 (1.1 Ry Mp) / Lh (special and intermediate frames; ordinary FR connections), the
  connection re-checked at the expected moment when the beam type has a flange-plate moment
  connection, the conformance (prequalified or tested connection, the drift angle) as a flag,
  the protected zones.
- **Joints** (:func:`moment_ratio_check`, :func:`panel_zone_checks`,
  :func:`continuity_plate_checks`): the column-beam moment ratio with its exemption for
  lightly loaded top-storey columns, the panel zone shear at the projected expected moments
  (φ of the frame) and the panel zone thickness, the column flange bracing at connections,
  and the continuity plates of ordinary frames.
- **Splices and bases** (:func:`splice_checks`, :func:`base_demands`): the splice location,
  the capacity-design splice and base forces.
- **Special truss moment frames** (:func:`truss_checks`): the special segment geometry and
  members, Eq 6.10.302 (no structural system of the BNBC pack selects them: Table 6.2.19 has no
  row for them).
- **Panel zone deformations in the drift** (:func:`panel_zone_model_check`): a steel moment
  frame analysed with rigid zones at its joints leaves them out.

Where the code defers to the tested or prequalified connection (the hinge location, the extent
of the protected zone) the table's ``practice`` group holds SAEngine's choice, labelled so.

Units: mm, MPa, N, N·mm. Checks follow :func:`saengine.design.check._check` with a
``"clause"``; their names start with :data:`PREFIX`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

TABLE = "steelSeismic"
PREFIX = "Seismic: "
#: Moment frame kinds in increasing order of stringency.
MOMENT_FRAMES = ("omf", "imf", "smf")


# ─────────────────────────────────────────── data ───────────────────────────────────────────


def seismic_table() -> Any | None:
    """The ``steelSeismic`` table of the pack in force; None when the pack does not cover it."""
    try:
        from saengine.codes import context as code_context

        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery (a bare calculation)
        from saengine.codes.tables import builtin_table

        return builtin_table(TABLE)


def _table(table: Any | None) -> Any:
    found = table if table is not None else seismic_table()
    if found is None:
        raise ValueError("the code pack in force has no steel seismic provisions")
    return found


def pack_name() -> str:
    try:
        from saengine.codes import context as code_context

        return code_context.current().name
    except Exception:  # noqa: BLE001
        return "the code pack"


def cite(table: Any, key: str) -> str:
    """The clause of ``key`` in the table's sources (its text before the page)."""
    return table.sources.get(key, "").split(" (", 1)[0]


def _check(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    clause: str,
    note: str = "",
    combination: str | None = None,
    flag: bool = False,
    utilisation: float | None = None,
) -> dict[str, Any]:
    if utilisation is None:
        utilisation = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    u = round(float(utilisation), 3) if math.isfinite(utilisation) else 99.0
    return {
        "name": PREFIX + name,
        "demand": round(float(demand), 3),
        "capacity": round(float(capacity), 3),
        "unit": unit,
        "utilisation": u,
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": flag,
        "clause": clause,
    }


def _rule(name: str, ok: bool, clause: str, note: str, flag: bool = False) -> dict[str, Any]:
    """A yes/no requirement as a check (utilisation 0 when met, 99 when not)."""
    return _check(
        name, 0.0 if ok else 1.0, 1.0, "-", clause, note, flag=flag, utilisation=0.0 if ok else 99.0
    )


# ───────────────────────────────────── when they apply ─────────────────────────────────────


@dataclass
class Provisions:
    """Whether the steel seismic provisions apply to the project and to which frames."""

    applies: bool
    frame: str | None  # the governing frame kind ("smf", "imf", "omf"), None without one
    systems: list[str] = field(default_factory=list)  # the steel systems in use
    r: float | None = None  # the largest R of those systems
    reason: str = ""


def _systems_in_use(settings: Any) -> list[tuple[str, float | None]]:
    """``(system id, R override)`` of every structural system of the settings."""
    seismic = settings.seismic
    found: list[tuple[str, float | None]] = [(seismic.system, seismic.r)]
    if seismic.systemY:
        found.append((seismic.systemY, None))
    for other in [*(seismic.otherSystems or []), *(seismic.otherSystemsY or [])]:
        found.append((other, None))
    seen: set[str] = set()
    return [(s, r) for s, r in found if not (s in seen or seen.add(s))]


def provisions(settings: Any, table: Any | None = None) -> Provisions:
    """Which frame provisions apply: the systems in use the table maps (``systems``) with R
    taken above ``trigger.rAbove`` (Sec 10.1.1.2, 10.20.1); the strictest frame kind."""
    t = table if table is not None else seismic_table()
    if t is None:
        return Provisions(False, None, reason=f"{pack_name()} has no steel seismic provisions")
    from saengine.codes import context as code_context

    rows = code_context.table("seismic").systems
    kinds: list[str] = []
    systems: list[str] = []
    largest: float | None = None
    below: list[str] = []
    for system, override in _systems_in_use(settings):
        kind = t.systems.get(system)
        if kind is None:
            continue
        row = rows.get(system)
        r = float(override if override is not None else (row.R if row is not None else 0.0))
        if r <= t.trigger.rAbove:
            below.append(system)
            continue
        kinds.append(kind)
        systems.append(system)
        largest = r if largest is None else max(largest, r)
    if not kinds:
        reason = (
            f"R of {', '.join(below)} is not above {t.trigger.rAbove:g}: the steel seismic "
            f"provisions are not required ({cite(t, 'trigger')})"
            if below
            else "no steel seismic load resisting system is selected"
        )
        return Provisions(False, None, systems=below, reason=reason)
    moment = [k for k in kinds if k in MOMENT_FRAMES]
    frame = max(moment, key=MOMENT_FRAMES.index) if moment else kinds[0]
    return Provisions(True, frame, systems, largest)


def frame_rules(frame: str, table: Any | None = None) -> Any:
    return _table(table).frames[frame]


# ──────────────────────────────────── expected strength ────────────────────────────────────


def _material_text(material: Any) -> tuple[str, float]:
    m = material if isinstance(material, dict) else material.model_dump()
    steel = m.get("steel") or {}
    source = m.get("source") or {}
    text = " ".join(
        str(x)
        for x in (steel.get("grade"), source.get("standard"), m.get("id"), m.get("name"))
        if x
    )
    return text, float(steel.get("fy") or 0.0)


def application_of(family: str) -> str:
    """The table application of a shape family: hollow sections or shapes."""
    return "hss" if family in ("rhs", "chs") else "shapes"


def expected_ratios(
    material: Any, family: str = "I", table: Any | None = None
) -> tuple[float, float, str]:
    """``(Ry, Rt, what)`` of a steel material for members of the shape ``family`` (Table
    6.10.17): the first row of the application whose pattern matches the material's grade,
    standard, id or name and whose Fy range holds its Fy; a round hollow section also tries
    the pipe rows. Without a match the table's fallback (its largest values)."""
    t = _table(table)
    text, fy = _material_text(material)
    apps = [application_of(family)] + (["pipe"] if family == "chs" else [])
    for app in apps:
        for row in t.expected.rows.values():
            if row.application != app:
                continue
            if row.fyMin is not None and fy < row.fyMin:
                continue
            if row.fyMax is not None and fy > row.fyMax:
                continue
            if any(re.search(p, text, re.IGNORECASE) for p in row.match):
                return float(row.Ry), float(row.Rt), row.label
    return (
        float(t.expected.fallbackRy),
        float(t.expected.fallbackRt),
        f"no row of {cite(t, 'expected')} names this steel: the table's largest Ry and Rt",
    )


# ───────────────────────────────────── width-thickness ─────────────────────────────────────


def axial_coefficient(pu: float, py: float, table: Any | None = None) -> float:
    """Ca = Pu / (φb Py) (note [k] of Table 6.10.18), compression positive (0 in tension)."""
    t = _table(table)
    return max(pu, 0.0) / (t.widthThickness.phiB * py) if py > 0 else 0.0


def web_limit(ca: float, root: float, table: Any | None = None) -> float:
    """λps of webs in flexure or flexure and axial compression (Table 6.10.18) at Ca;
    ``root`` = √(E/Fy). With ``leastOfBoth`` the least of the printed range assignment and the
    swapped one (owner decision on misprints)."""
    w = _table(table).widthThickness.web
    linear = w.linearA * root * (1 - w.linearB * ca)
    offset = max(w.offsetA * root * (w.offsetB - ca), w.floor * root)
    above = ca > w.split
    printed = linear if above == w.linearAbove else offset
    if not w.leastOfBoth:
        return printed
    swapped = offset if above == w.linearAbove else linear
    return min(printed, swapped)


def seismic_compact_limits(
    shape: Any, fy: float, e: float, kind: str, frame: str, ca: float, table: Any | None = None
) -> list[tuple[str, float, float]]:
    """``(element, λ, λps)`` of a shape's compression elements (Table 6.10.18) for a beam or
    column of the frame kind."""
    wt = _table(table).widthThickness
    root = math.sqrt(e / fy)
    d = shape.dims
    out: list[tuple[str, float, float]] = []
    match shape.family:
        case "I":
            out.append(("flange", d["bf"] / 2 / d["tf"], wt.iFlange * root))
            web = (
                wt.smfBeamWeb * root
                if kind == "beam" and frame == "smf" and ca <= 0
                else web_limit(ca, root, table)
            )
            out.append(("web", d["h"] / d["tw"], web))
        case "channel":
            out.append(("flange", d["bf"] / d["tf"], wt.channelFlange * root))
            out.append(("web", d["h"] / d["tw"], web_limit(ca, root, table)))
        case "tee":
            out.append(("flange", d["bf"] / 2 / d["tf"], wt.angleLeg * root))
            out.append(("stem", d["d"] / d["tw"], wt.teeStem * root))
        case "angle":
            out.append(("leg", max(d["d"], d["b"]) / d["t"], wt.angleLeg * root))
        case "rhs":
            out.append(("wall (width)", d["b"] / d["t"], wt.rectHss * root))
            out.append(("wall (depth)", d["h"] / d["t"], wt.rectHss * root))
        case "chs":
            out.append(("wall", d["D"] / d["t"], wt.roundHss * e / fy))
    return out


def compactness_checks(
    shape: Any,
    fy: float,
    e: float,
    kind: str,
    frame: str,
    pu: float,
    relaxed: bool = False,
    table: Any | None = None,
) -> list[dict[str, Any]]:
    """Width-thickness checks of a beam or column of the frame kind: seismically compact
    (Sec 10.20.8.2.2, Table 6.10.18) or compact (Sec 10.20.8.2.1, Table 6.10.1) as the frame
    asks; ``relaxed``: a special moment frame column whose moment ratios exceed the table's
    ``relaxedRatio`` (note [b]: λp of Table 6.10.1 is permitted)."""
    t = _table(table)
    rules = t.frames[frame]
    level = rules.compactness
    if level == "none":
        return []
    if level == "seismic" and relaxed and kind == "column":
        level = "compact"
    clause = cite(t, "compact")
    if level == "compact":
        from saengine.design.steel import classify as cl

        elements = cl.flexure_elements(shape, fy, e, "x") or cl.compression_elements(shape, fy, e)
        checks = []
        for el in elements:
            limit = el.lambda_p if el.lambda_p is not None else el.lambda_r
            checks.append(
                _check(
                    f"{el.name} width-thickness (compact)",
                    el.ratio,
                    limit,
                    "",
                    clause,
                    f"λ = {el.ratio:.1f} ≤ λp = {limit:.1f} of Table 6.10.1 case {el.case}"
                    + (
                        "; the moment ratio exceeds the relaxed ratio (note [b])" if relaxed else ""
                    ),
                )
            )
        return checks
    ca = axial_coefficient(pu, shape.area * fy, t) if kind == "column" else 0.0
    return [
        _check(
            f"{name} width-thickness (seismically compact)",
            ratio,
            limit,
            "",
            clause,
            f"λ = {ratio:.1f} ≤ λps = {limit:.1f}" + (f", Ca = {ca:.3f}" if ca else ""),
        )
        for name, ratio, limit in seismic_compact_limits(shape, fy, e, kind, frame, ca, t)
    ]


# ─────────────────────────────────────────── members ───────────────────────────────────────────


def material_checks(kind: str, fy: float, frame: str, table: Any | None = None) -> list[dict]:
    """Sec 10.20.6.1: Fy of members expected to yield at most the frame's limit (beams; the
    columns of moment frames are expected to yield at their base only)."""
    t = _table(table)
    if kind != "beam":
        return []
    limit = t.frames[frame].fyLimit
    return [
        _check(
            "Fy of a member expected to yield",
            fy,
            limit,
            "MPa",
            cite(t, "materials"),
            f"Fy at most {limit:g} MPa unless the steel's suitability is shown by tests",
        )
    ]


def toughness_flags(shape: Any, table: Any | None = None) -> list[dict[str, Any]]:
    """Sec 10.20.6.3: rolled shapes with flanges at least the table's thickness need the
    Charpy V-notch toughness (a mill certificate; reported as a flag)."""
    t = _table(table).toughness
    tf = shape.dims.get("tf") or shape.dims.get("t") or 0.0
    if tf < t.flangeThickness:
        return []
    tab = _table(table)
    return [
        _rule(
            "heavy section toughness",
            False,
            cite(tab, "toughness"),
            f"flange {tf:g} mm ≥ {t.flangeThickness:g} mm: Charpy V-notch at least "
            f"{t.energy:g} J at {t.temperature:g} °C (alternate core location) to be specified",
            flag=True,
        )
    ]


def beam_bracing_checks(
    shape: Any,
    fy: float,
    e: float,
    ry_ratio: float,
    lb: float,
    frame: str,
    table: Any | None = None,
) -> list[dict[str, Any]]:
    """Sec 10.20.9.8 / 10.20.10.8: both flanges braced at most c ry E / Fy apart (``lb`` [mm],
    the longest unbraced length of the beam); the brace next to a hinge needs Pu = 0.06 Mu /
    ho with Mu = Ry Z Fy (reported as a flag)."""
    t = _table(table)
    rules = t.frames[frame]
    if rules.beamBracing is None:
        return []
    key = "smfBeamBracing" if frame == "smf" else "imfBeamBracing"
    limit = rules.beamBracing * shape.ry * e / fy
    checks = [
        _check(
            "lateral bracing of the beam",
            lb,
            limit,
            "mm",
            cite(t, key),
            f"Lb ≤ {rules.beamBracing:g} ry E / Fy = {limit:.0f} mm, both flanges braced",
        )
    ]
    ho = shape.dims.get("ho") or shape.dims.get("d", 0.0)
    if rules.braceStrength is not None and ho > 0:
        mu = ry_ratio * shape.zx * fy
        pu = rules.braceStrength * mu / ho
        checks.append(
            _check(
                "brace next to a plastic hinge",
                pu / 1e3,
                pu / 1e3,
                "kN",
                cite(t, key),
                f"each brace next to a hinge needs Pu = {rules.braceStrength:g} Ry Z Fy / ho = "
                f"{pu / 1e3:.1f} kN and the stiffness of Eq 6.10.292 (Cd = 1)",
                flag=True,
            )
        )
    return checks


def column_strength_checks(
    pu_plain: float,
    phi_pn: float,
    omega_rows: list[tuple[str, float]],
    phi_pt: float,
    table: Any | None = None,
) -> list[dict[str, Any]]:
    """Sec 10.20.8.3: when Pu / φPn (without the amplified load) exceeds the table's ratio, the
    axial compression and tension of the combinations with the amplified seismic load (Ω0,
    ``omega_rows`` ``(combination, P [N] compression +)``) against φPn and φPt."""
    t = _table(table)
    c = t.columns
    clause = cite(t, "columnStrength")
    ratio = pu_plain / phi_pn if phi_pn > 0 else 0.0
    if ratio <= c.axialRatio:
        return []
    if not omega_rows:
        return [
            _rule(
                "column axial strength with the amplified seismic load",
                False,
                clause,
                f"Pu / φPn = {ratio:.2f} > {c.axialRatio:g}: no combination with Ω0 was formed",
                flag=True,
            )
        ]
    comp = max(omega_rows, key=lambda r: r[1])
    tens = min(omega_rows, key=lambda r: r[1])
    note = (
        f"Pu / φPn = {ratio:.2f} > {c.axialRatio:g}: the axial force alone under the amplified "
        f"seismic load; it need not exceed what the connecting members deliver at "
        f"{c.connectionFactor:g} Ry times their nominal strengths, nor the foundation's uplift "
        "resistance (not taken: conservative)"
    )
    checks = [
        _check(
            "column compression with the amplified seismic load",
            max(comp[1], 0.0) / 1e3,
            phi_pn / 1e3,
            "kN",
            clause,
            note,
            comp[0],
        )
    ]
    if tens[1] < 0:
        checks.append(
            _check(
                "column tension with the amplified seismic load",
                -tens[1] / 1e3,
                phi_pt / 1e3,
                "kN",
                clause,
                note,
                tens[0],
            )
        )
    return checks


# ───────────────────────────────────────── connections ─────────────────────────────────────────


@dataclass
class BeamHinge:
    """A moment frame beam's capacity-design numbers."""

    id: str
    ry: float
    fy: float
    zx: float
    depth: float
    tf: float
    lh: float  # mm, between the hinges
    sh: float  # mm, hinge to the column face
    vg: float  # N, the gravity shear at the hinge
    mp: float = 0.0
    ev: float = 0.0
    vu: float = 0.0
    m_expected: float = 0.0  # hinge factor × Ry Mp
    m_face: float = 0.0  # projected to the column face

    def __post_init__(self) -> None:
        self.mp = self.fy * self.zx


def connection_shear(beam: BeamHinge, frame: str, table: Any | None = None) -> BeamHinge:
    """Eq 6.10.298 / 6.10.301: E = 2 (hinge factor × Ry Mp) / Lh, the required shear Vu = the
    gravity shear + E (in place); the expected moment and its projection to the column face."""
    rules = _table(table).frames[frame]
    beam.m_expected = rules.hingeFactor * beam.ry * beam.mp
    beam.ev = 2 * beam.m_expected / beam.lh if beam.lh > 0 else math.inf
    beam.vu = beam.vg + beam.ev
    beam.m_face = beam.m_expected + beam.vu * beam.sh
    return beam


def connection_checks(
    beam: BeamHinge, phi_vn: float, frame: str, connection: Any = None, table: Any | None = None
) -> list[dict[str, Any]]:
    """The beam-to-column connection of a moment frame beam: the required shear against the
    beam web's φVn, the conformance demonstration (flag), the bolts (slip-critical, Sec
    10.20.7.2) and the demand-critical welds."""
    t = _table(table)
    rules = t.frames[frame]
    key = {"smf": "smfConnection", "imf": "imfConnection"}.get(frame, "omfConnection")
    clause = cite(t, key)
    checks = [
        _check(
            "connection shear at the expected moments",
            beam.vu / 1e3,
            phi_vn / 1e3,
            "kN",
            clause,
            f"Vu = gravity {beam.vg / 1e3:.1f} kN + 2 ({rules.hingeFactor:g} Ry Mp) / Lh = "
            f"{beam.ev / 1e3:.1f} kN, Ry = {beam.ry:g}, Lh = {beam.lh:.0f} mm; against the "
            "beam web (the connection's own shear checks follow its type)",
        )
    ]
    if rules.driftAngle is not None:
        checks.append(
            _rule(
                "connection qualified for the drift",
                False,
                cite(t, "conformance"),
                f"use a prequalified connection or one qualified by cyclic tests: interstory "
                f"drift angle {rules.driftAngle:g} rad with at least "
                f"{rules.flexuralShare or 0:g} Mp at the column face; the engineer confirms it",
                flag=True,
            )
        )
    if connection is not None and getattr(connection, "slipCritical", None) == "none":
        checks.append(
            _rule(
                "pretensioned slip-critical bolts",
                False,
                cite(t, "bolts"),
                f"bolts of the seismic load resisting system are pretensioned, slip-critical "
                f"with a class {t.connections.slipClass} surface, in standard or short-slotted "
                "holes: set the connection's slip-critical option",
            )
        )
    return checks


def protected_zone(beam_depth: float, table: Any | None = None) -> dict[str, Any]:
    """The protected zone at each end of a moment frame beam (SAEngine practice where no
    prequalified connection gives it)."""
    t = _table(table)
    return {
        "fromFace": 0.0,
        "length": round(t.practice.protectedDepths * beam_depth, 1),
        "clause": cite(t, "protected"),
        "note": "no welded studs, deck fasteners through the flange, or attachments in it",
    }


# ─────────────────────────────────────────── joints ───────────────────────────────────────────


@dataclass
class JointColumnSide:
    """A column at a joint (below or above): plastic modulus about the axis, Fy, Ag and the
    largest factored compression without the amplified load."""

    z: float
    fy: float
    area: float
    puc: float


def moment_ratio_check(
    columns: list[JointColumnSide],
    beams: list[BeamHinge],
    column_depth: float,
    top: bool,
    axis: str,
    table: Any | None = None,
) -> tuple[dict[str, Any] | None, float | None]:
    """Eq 6.10.300 at a joint for one axis: ΣM*pc = Σ Zc (Fyc - Puc / Ag), ΣM*pb = Σ (1.1 Ry
    Fyb Zb + Muv) with Muv = Vu (sh + dc / 2); the ratio must exceed the table's. Exempt
    (flag) where every column carries less than ``axialExemption`` Fy Ag and the joint is at
    the top storey (exception (a)(i)). Returns the check and the ratio."""
    t = _table(table)
    rules = t.frames["smf"]
    if rules.momentRatio is None or not beams or not columns:
        return None, None
    mpc = sum(max(c.z * (c.fy - c.puc / c.area), 0.0) for c in columns)
    mpb = sum(b.m_expected + b.vu * (b.sh + column_depth / 2) for b in beams)
    ratio = mpc / mpb if mpb > 0 else math.inf
    light = all(c.puc < (rules.axialExemption or 0.0) * c.fy * c.area for c in columns)
    exempt = bool(light and top)
    note = (
        f"ΣM*pc = {mpc / 1e6:.0f} kN·m, ΣM*pb = {mpb / 1e6:.0f} kN·m about {axis}: ratio "
        f"{ratio:.2f} must exceed {rules.momentRatio:g}"
    )
    if exempt:
        note += (
            f"; exempt: a top-storey column with Puc < {rules.axialExemption:g} Fy Ag "
            "(exception (a)(i))"
        )
    elif light:
        note += (
            "; exceptions (a)(ii) (exempt columns' share of the storey shear) and (b) are not "
            "checked by SAEngine"
        )
    check = _check(
        f"column-beam moment ratio about {axis}",
        mpb / 1e6 * rules.momentRatio,
        mpc / 1e6,
        "kN·m",
        cite(t, "momentRatio"),
        note,
        flag=exempt,
        utilisation=(rules.momentRatio / ratio if ratio > 0 else 99.0)
        if math.isfinite(ratio)
        else 0.0,
    )
    if not exempt and ratio <= rules.momentRatio:
        check["ok"] = False
        check["utilisation"] = max(check["utilisation"], 1.001)
    return check, ratio


def panel_zone_checks(
    column: Any,
    column_fy: float,
    beams: list[BeamHinge],
    axial_ratio: float,
    in_analysis: bool,
    doubler: float = 0.0,
    table: Any | None = None,
) -> list[dict[str, Any]]:
    """Sec 10.20.9.3: the panel zone of a special moment frame column (``column`` an I-section
    :class:`~saengine.library.steel_sections.SteelSection`, beams on its major axis): the
    required shear Σ M_face / (db - tbf) against φv Rn of Sec 10.10.10.6 (φv of the frame),
    with a doubler; the thickness of the web and the doubler, Eq 6.10.299."""
    from saengine.design import steel_connections as sc

    t = _table(table)
    rules = t.frames["smf"]
    if not beams:
        return []
    dc, tw, tcf, bcf = column.h, column.tw, column.tf, column.b
    db = max(b.depth for b in beams)
    tbf = max(b.tf for b in beams)
    ru = sum(b.m_face / (b.depth - b.tf) for b in beams)
    cap, note = sc.panel_zone_shear(column_fy, dc, tw, axial_ratio, in_analysis, bcf, tcf, db)
    phi = rules.panelZonePhi or 1.0
    rn = cap / sc.phi("panelZone", 0.9)
    if doubler > 0:
        rn += 0.60 * column_fy * dc * doubler
        note += f"; doubler {doubler:g} mm adds 0.60 Fy dc td"
    checks = [
        _check(
            "panel zone shear at the expected moments",
            ru / 1e3,
            phi * rn / 1e3,
            "kN",
            cite(t, "panelZone"),
            f"Ru = Σ M_face / (db - tbf) of {len(beams)} beam(s), φv = {phi:g}; {note}"
            + ("" if in_analysis else "; the panel zone deformation is not in the analysis"),
        )
    ]
    if rules.panelThicknessDivisor:
        dz = db - 2 * tbf
        wz = dc - 2 * tcf
        need = (dz + wz) / rules.panelThicknessDivisor
        for what, thick in (("column web", tw), ("doubler plate", doubler)):
            if thick <= 0:
                continue
            checks.append(
                _check(
                    f"panel zone thickness ({what})",
                    need,
                    thick,
                    "mm",
                    cite(t, "panelThickness"),
                    f"t ≥ (dz + wz) / {rules.panelThicknessDivisor:g} = ({dz:.0f} + {wz:.0f}) / "
                    f"{rules.panelThicknessDivisor:g} (plug welds to the web allow the total)",
                )
            )
    return checks


def connection_bracing_flag(
    ratio: float | None, beam_fy: float, bf: float, tbf: float, table: Any | None = None
) -> dict[str, Any] | None:
    """Sec 10.20.9.7.1: a column not shown elastic (moment ratio at most ``elasticRatio``) is
    braced at both beam flange levels, each brace for 2 % of Fy bf tbf (a flag)."""
    t = _table(table)
    rules = t.frames["smf"]
    if rules.elasticRatio is None or ratio is None or ratio > rules.elasticRatio:
        return None
    force = (rules.flangeBraceShare or 0.0) * beam_fy * bf * tbf
    return _rule(
        "column flange bracing at the connection",
        False,
        cite(t, "connectionBracing"),
        f"the moment ratio {ratio:.2f} ≤ {rules.elasticRatio:g}: brace the column flanges at "
        f"the top and bottom beam flanges, each brace {force / 1e3:.1f} kN; an unbraced "
        f"connection needs L/r ≤ {rules.unbracedSlenderness or 0:g}",
        flag=True,
    )


def continuity_plate_checks(
    column_tf: float,
    beam_bf: float,
    beam_tf: float,
    beam_fy: float,
    column_fy: float,
    two_sided: bool,
    provided: float | None,
    table: Any | None = None,
) -> list[dict[str, Any]]:
    """Sec 10.20.11.5: ordinary moment frames with beam flanges (or their plates) welded to the
    column flange need continuity plates when tcf < 0.54 √(bf tbf Fyb / Fyc) or tcf < bf / 6,
    at least half the beam flange thick (one-sided) or as thick as it (two-sided).
    ``provided``: the plates' thickness, None without plates."""
    t = _table(table)
    rules = t.frames["omf"]
    if rules.continuityCoefficient is None:
        return []
    clause = cite(t, "omfContinuity")
    need_t = rules.continuityCoefficient * math.sqrt(beam_bf * beam_tf * beam_fy / column_fy)
    need_b = beam_bf / (rules.continuityWidthRatio or math.inf)
    required = column_tf < need_t or column_tf < need_b
    if not required:
        return [
            _rule(
                "continuity plates",
                True,
                clause,
                f"not required: tcf {column_tf:g} mm ≥ {need_t:.1f} and ≥ bf / "
                f"{rules.continuityWidthRatio:g} = {need_b:.1f} mm",
                flag=True,
            )
        ]
    if provided is None:
        return [
            _rule(
                "continuity plates",
                False,
                clause,
                f"required: tcf {column_tf:g} mm < max({need_t:.1f}, {need_b:.1f}) mm; add "
                "column stiffeners to the connection",
            )
        ]
    share = rules.plateTwoSided if two_sided else rules.plateOneSided
    least = (share or 0.0) * beam_tf
    return [
        _check(
            "continuity plate thickness",
            least,
            provided,
            "mm",
            clause,
            f"{'two' if two_sided else 'one'}-sided: at least {share:g} tbf",
        )
    ]


# ─────────────────────────────────────── splices and bases ───────────────────────────────────────


def splice_location_check(
    distance: float, clear_height: float, table: Any | None = None
) -> dict[str, Any]:
    """Sec 10.20.8.4: a column splice at least ``splices.distance`` from the beam-to-column
    connections, at mid clear height where the clear height is below ``shortStorey``.
    ``distance``: from the lower connection [mm]."""
    t = _table(table)
    s = t.splices
    clause = cite(t, "splices")
    if clear_height < s.shortStorey:
        off = abs(distance - clear_height / 2)
        return _check(
            "column splice at mid clear height",
            off,
            max(0.05 * clear_height, 1.0),
            "mm",
            clause,
            f"clear height {clear_height:.0f} mm < {s.shortStorey:g} mm: the splice at half of it",
        )
    nearest = min(distance, clear_height - distance)
    return _check(
        "column splice away from the connections",
        s.distance,
        nearest,
        "mm",
        clause,
        f"{nearest:.0f} mm from the nearer beam-to-column connection, at least {s.distance:g} mm",
    )


def splice_demand(
    ry: float,
    fy: float,
    zx: float,
    sum_mpc: float,
    height: float,
    lateral: bool,
    frame: str,
    table: Any | None = None,
) -> tuple[float, float, str]:
    """``(M [N·mm], V [N], clause)`` a bolted column splice is checked for: special moment
    frames Ry Fy Zx and ΣMpc / H (Sec 10.20.9.9); columns not in the seismic load resisting
    system the shear Mpc / H (Sec 10.20.8.4.2) and no moment."""
    t = _table(table)
    s = t.splices
    if not lateral:
        return 0.0, s.gravityShear * (sum_mpc / 2) / height, cite(t, "splices")
    if frame == "smf":
        return s.smfFlexure * ry * fy * zx, s.smfShear * sum_mpc / height, cite(t, "smfSplices")
    return 0.0, 0.0, cite(t, "splices")


def base_demands(
    ry: float,
    fy: float,
    zx: float,
    height: float,
    v_amplified: float,
    m_amplified: float,
    table: Any | None = None,
) -> tuple[float, float]:
    """Sec 10.20.8.5.2-10.20.8.5.3: the column base shear and moment, the lesser of the
    capacity-design values (2 Ry Fy Zx / H, 1.1 Ry Fy Z) and those of the combinations with
    the amplified seismic load."""
    b = _table(table).bases
    v = min(b.shearFactor * ry * fy * zx / height, v_amplified) if height > 0 else v_amplified
    m = min(b.flexureFactor * ry * fy * zx, m_amplified)
    return v, m


# ─────────────────────────────────── special truss moment frames ───────────────────────────────────


@dataclass
class TrussSegment:
    """A special truss moment frame's truss and its special segment (mm, N, N·mm)."""

    span: float
    depth: float
    segment_start: float  # from the truss's left end
    segment_length: float
    panel_length: float
    ry: float
    chord_mnc: float
    chord_ei: float
    chord_fy: float
    chord_area: float
    chord_axial: float  # required, by tensile yielding
    diagonal_pnt: float = 0.0
    diagonal_pnc: float = 0.0
    diagonal_fy: float = 0.0
    diagonal_area: float = 0.0
    diagonal_gravity: float = 0.0
    angle: float = 0.0  # rad, diagonals to the horizontal
    vertical_shear: float = 0.0  # the required vertical shear of the segment
    phi_chord_shear: float = 0.0  # the chords' available shear through flexure


def expected_truss_shear(s: TrussSegment, table: Any | None = None) -> float:
    """Eq 6.10.302: Vne = 3.75 Ry Mnc / Ls + 0.075 EI (L - Ls) / Ls³ + Ry (Pnt + 0.3 Pnc) sin α."""
    tr = _table(table).truss
    ls = s.segment_length
    return (
        tr.vneMoment * s.ry * s.chord_mnc / ls
        + tr.vneStiffness * s.chord_ei * (s.span - ls) / ls**3
        + s.ry * (s.diagonal_pnt + tr.diagonalCompression * s.diagonal_pnc) * math.sin(s.angle)
    )


def truss_checks(s: TrussSegment, table: Any | None = None) -> list[dict[str, Any]]:
    """Sec 10.20.12.1-10.20.12.3: span and depth, the special segment's length and place, its
    panels' proportions, the chords' share of the shear and axial force, the diagonals'
    gravity force."""
    t = _table(table)
    tr = t.truss
    clause = cite(t, "stmf")
    checks = [
        _check("truss span", s.span, tr.spanMax, "mm", clause),
        _check("truss depth", s.depth, tr.depthMax, "mm", clause),
        _check(
            "special segment length (least)",
            tr.segmentMin * s.span,
            s.segment_length,
            "mm",
            clause,
            f"at least {tr.segmentMin:g} × the span",
        ),
        _check(
            "special segment length (largest)",
            s.segment_length,
            tr.segmentMax * s.span,
            "mm",
            clause,
            f"at most {tr.segmentMax:g} × the span",
        ),
    ]
    lo = (1 - tr.segmentZone) / 2 * s.span
    hi = s.span - lo
    inside = lo - 1e-6 <= s.segment_start and s.segment_start + s.segment_length <= hi + 1e-6
    checks.append(
        _rule(
            "special segment between the quarter points",
            inside,
            clause,
            f"from {lo:.0f} to {hi:.0f} mm",
        )
    )
    ratio = s.panel_length / s.depth
    checks.append(_check("panel length / depth (largest)", ratio, tr.panelRatioMax, "", clause))
    checks.append(_check("panel length / depth (least)", tr.panelRatioMin, ratio, "", clause))
    if s.vertical_shear > 0:
        checks.append(
            _check(
                "chords' share of the vertical shear",
                tr.chordShear * s.vertical_shear / 1e3,
                s.phi_chord_shear / 1e3,
                "kN",
                clause,
                f"the chords give at least {tr.chordShear:g} of it",
            )
        )
    checks.append(
        _check(
            "chord axial force",
            s.chord_axial / 1e3,
            tr.chordAxial * tr.phi * s.chord_fy * s.chord_area / 1e3,
            "kN",
            clause,
            f"at most {tr.chordAxial:g} φ Fy Ag",
        )
    )
    if s.diagonal_area > 0:
        checks.append(
            _check(
                "diagonal gravity force",
                s.diagonal_gravity / 1e3,
                tr.diagonalGravity * s.diagonal_fy * s.diagonal_area / 1e3,
                "kN",
                clause,
                f"at most {tr.diagonalGravity:g} Fy Ag",
            )
        )
    return checks


# ─────────────────────────────────── the drift model ───────────────────────────────────


def panel_zone_model_check(settings: Any, frame: str | None, table: Any | None = None):
    """Sec 2.5.9.1(b): the panel zone deformations of steel moment frames in the drift of the
    response spectrum analysis. SAEngine takes them by a centreline model (rigid zone factor at
    most ``practice.rigidZoneMax``); None when not a moment frame or without the analysis."""
    t = _table(table)
    if frame not in MOMENT_FRAMES:
        return None
    analysis = settings.analysis
    if not getattr(analysis, "responseSpectrum", False):
        return None
    factor = float(analysis.rigidZoneFactor) if analysis.endOffsets else 0.0
    ok = factor <= t.practice.rigidZoneMax + 1e-9
    return _rule(
        "panel zone deformations in the drift model",
        ok,
        cite(t, "panelZoneDrift"),
        f"rigid zone factor {factor:g} (at most {t.practice.rigidZoneMax:g}): "
        + (
            "the joints of the steel moment frames deform with the members (centreline model)"
            if ok
            else "set the rigid zone factor to 0 in Project Settings → Analysis so the panel "
            "zones deform in the drift (SAEngine practice, not the code)"
        ),
    )


def method_lines(table: Any | None = None) -> list[str]:
    t = _table(table)
    return [
        f"Steel seismic provisions ({pack_name()} {cite(t, 'trigger')}): with R above "
        f"{t.trigger.rAbove:g} the members, joints and connections of the steel moment frames "
        "are capacity designed: Ry and Rt of the steel, seismically compact sections, beam "
        "bracing, column strength under the amplified seismic load, the connection shear at the "
        "expected moments, the column-beam moment ratio, the panel zone, continuity plates, "
        "splices and bases ('Seismic: ...' checks). " + t.practice.note
    ]


# ─────────────────────────────────── integrator glue ───────────────────────────────────


@dataclass
class SteelMember:
    """A steel beam or column the design checked, with what the seismic checks need."""

    id: str
    kind: str  # "beam" or "column"
    element: Any
    object: Any
    material: Any
    pieces: list[Any]  # with the amplified (Ω0) combinations' forces
    turned: bool
    entry: dict[str, Any]


def _role(member: SteelMember) -> str | None:
    for owner in (member.element, member.object):
        role = getattr(owner, "seismicRole", None)
        if role in ("lateral", "gravity"):
            return role
    return None


def _moment_connected(object_type: Any) -> bool:
    connection = getattr(object_type, "connection", None)
    return connection is None or connection.type in ("flangePlate", "hssMoment")


def _capacity(entry: dict[str, Any], prefix: str) -> float:
    found = next((c for c in entry["checks"] if c["name"].startswith(prefix)), None)
    return float(found["capacity"]) * 1e3 if found else 0.0


def _rescore(entry: dict[str, Any]) -> None:
    strength = [c for c in entry["checks"] if not c["flag"]]
    entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
    entry["ok"] = all(c["ok"] for c in strength)


def apply(
    project: dict[str, Any],
    building: Any,
    types: dict[str, Any],
    mats: dict[str, Any],
    members: list[SteelMember],
    combinations: list[str],
    earthquake: list[int],
    settings: Any,
) -> dict[str, Any]:
    """Adds the steel seismic checks to the steel members' report entries and returns the
    summary ``{"applies", "frame", "systems", "R", "members", "joints", "checks", "notes",
    "clauses"}`` (``checks``: the project's own)."""
    from saengine.design import ductile_joints as dj
    from saengine.design import steel_connections as sc
    from saengine.design.steel import members as sm
    from saengine.design.steel.lengths import member_lengths
    from saengine.design.steel.properties import shape_properties
    from saengine.design.steel_proposal import SteelMaterial
    from saengine.library.steel_sections import find, section_of_profile

    t = seismic_table()
    prov = provisions(settings, t)
    out: dict[str, Any] = {
        "applies": prov.applies,
        "frame": prov.frame,
        "systems": prov.systems,
        "R": prov.r,
        "members": {},
        "joints": [],
        "checks": [],
        "notes": [prov.reason] if prov.reason else [],
        "clauses": dict(t.sources) if t is not None else {},
    }
    if not prov.applies or t is None or prov.frame not in t.frames:
        return out
    frame = prov.frame
    rules = t.frames[frame]
    model = panel_zone_model_check(settings, frame, t)
    if model is not None:
        out["checks"].append(model)
    in_analysis = model is None or model["ok"]
    omega = {c for c, name in enumerate(combinations) if name.startswith("Ω0: ")}
    plain = [c for c in range(len(combinations)) if c not in omega]
    gravity_idx = [c for c in plain if c not in set(earthquake)] or plain

    by_id = {m.id: m for m in members}
    try:
        joints = dj.frame_joints(building, types) if building is not None else []
    except Exception as error:  # noqa: BLE001 - a model the joint search cannot read
        joints = []
        out["notes"].append(f"the beam-column joints could not be found: {error}")
    # Roles: beams with moment connections and the columns they frame into are lateral.
    roles: dict[str, str] = {}
    for m in members:
        role = _role(m)
        if role is None and m.kind == "beam":
            role = "lateral" if _moment_connected(m.object) else "gravity"
        if role is not None:
            roles[m.id] = role
    for j in joints:
        lateral = any(roles.get(b.id) == "lateral" for b in j.beams)
        for cid in (j.below, j.above):
            if cid in by_id and cid not in roles and lateral:
                roles[cid] = "lateral"
    for m in members:
        roles.setdefault(m.id, "gravity" if joints else "lateral")

    info: dict[str, dict[str, Any]] = {}
    for m in members:
        try:
            shape = shape_properties(m.object.profile)
            steel = sm.Steel.of(m.material)
        except (ValueError, sm.SteelDesignError) as error:
            out["notes"].append(f"{m.id}: not checked for the seismic provisions: {error}")
            continue
        ry, rt, what = expected_ratios(m.material, shape.family, t)
        stations = sm.member_stations(m.pieces, combinations, m.turned)
        info[m.id] = {"shape": shape, "steel": steel, "ry": ry, "stations": stations}
        out["members"][m.id] = {
            "role": roles[m.id],
            "Ry": ry,
            "Rt": rt,
            "expected": what,
        }

    def pmax(st: list[Any], idx: list[int]) -> float:
        return max(
            (float(np.max(st[c].P)) for c in idx if c < len(st) and len(st[c].s)), default=0.0
        )

    # Beams: the hinges and connection shear.
    hinges: dict[str, BeamHinge] = {}
    column_depth: dict[str, float] = {}
    for m in members:
        if m.kind == "column" and m.id in info:
            column_depth[m.id] = info[m.id]["shape"].dims.get("d", 0.0)
    ends: dict[str, list[float]] = {}
    for j in joints:
        for b in j.beams:
            ends.setdefault(b.id, []).append(column_depth.get(j.below, 0.0))
    for m in members:
        if m.kind != "beam" or roles[m.id] != "lateral" or m.id not in info:
            continue
        i = info[m.id]
        shape, steel, stations = i["shape"], i["steel"], i["stations"]
        d = shape.dims.get("d", 0.0)
        length = max((float(st.s[-1]) for st in stations if len(st.s)), default=0.0) * 1e3
        faces = ends.get(m.id, [])
        clear = length - sum(faces[:2]) / 2
        sh = t.practice.hingeOffsetDepths * d
        vg = max(
            (
                abs(float(stations[c].Vy[k]))
                for c in gravity_idx
                if len(stations[c].s)
                for k in (0, -1)
            ),
            default=0.0,
        )
        hinge = connection_shear(
            BeamHinge(
                m.id,
                i["ry"],
                steel.fy,
                shape.zx,
                d,
                shape.dims.get("tf", 0.0),
                max(clear - 2 * sh, 1.0),
                sh,
                vg,
            ),
            frame,
            t,
        )
        hinges[m.id] = hinge
        checks = material_checks("beam", steel.fy, frame, t)
        checks += toughness_flags(shape, t)
        checks += compactness_checks(shape, steel.fy, steel.e, "beam", frame, 0.0, table=t)
        try:
            lengths = member_lengths(project, m.pieces, m.turned)
            lb = max(lengths.ltb_top.longest(), lengths.ltb_bottom.longest()) * 1e3
            checks += beam_bracing_checks(shape, steel.fy, steel.e, i["ry"], lb, frame, t)
        except Exception as error:  # noqa: BLE001 - no bracing model: say so
            out["notes"].append(f"{m.id}: beam bracing not checked: {error}")
        connection = getattr(m.object, "connection", None)
        checks += connection_checks(
            hinge, _capacity(m.entry, "Shear along y"), frame, connection, t
        )
        if connection is not None and connection.type == "flangePlate":
            try:
                section = section_of_profile(m.object.profile)
                moment = (
                    hinge.m_face
                    if frame != "omf"
                    else ((rules.connectionMoment or rules.hingeFactor) * hinge.ry * hinge.mp)
                )
                plate = mats.get(connection.plateMaterial) if connection.plateMaterial else None
                col = mats.get(connection.columnMaterial) if connection.columnMaterial else None
                found = sc.check_flange_plate(
                    connection,
                    section,
                    SteelMaterial.from_material(m.material),
                    SteelMaterial.from_material(plate) if plate is not None else None,
                    [("expected moment", moment, hinge.vu)],
                    find(connection.columnSection) if connection.columnSection else None,
                    SteelMaterial.from_material(col) if col is not None else None,
                )
                key = "omfConnection" if frame == "omf" else "smfConnection"
                for c in found["checks"]:
                    checks.append(
                        {
                            **c,
                            "name": f"{PREFIX}connection at the expected moment: {c['name']}",
                            "clause": cite(t, key),
                            "note": (c.get("note") or "")
                            + f"; M = {moment / 1e6:.0f} kN·m, V = {hinge.vu / 1e3:.0f} kN",
                        }
                    )
            except (ValueError, TypeError, KeyError) as error:
                out["notes"].append(f"{m.id}: connection not re-checked: {error}")
        out["members"][m.id]["protectedZone"] = protected_zone(d, t)
        out["members"][m.id]["connectionShear"] = round(hinge.vu / 1e3, 1)
        m.entry["checks"].extend(checks)

    # Joints: moment ratio, panel zone, bracing (special); continuity plates (ordinary).
    ratios: dict[str, list[float]] = {}
    for j in joints:
        below = by_id.get(j.below)
        if below is None or roles.get(below.id) != "lateral" or below.id not in info:
            continue
        ib = info[below.id]
        cshape, csteel = ib["shape"], ib["steel"]
        if cshape.family != "I":
            continue
        rotation = float(getattr(below.element, "rotation", 0.0) or 0.0)
        ex, ey = dj.column_axes(rotation)
        major: list[BeamHinge] = []
        minor: list[BeamHinge] = []
        major_beams: list[str] = []
        for b in j.beams:
            h = hinges.get(b.id)
            if h is None:
                continue
            u = np.asarray(b.direction, dtype=float)
            if abs(float(u @ ey)) >= abs(float(u @ ex)):
                major.append(h)
                major_beams.append(b.id)
            else:
                minor.append(h)
        if not major and not minor:
            continue
        level = j.level / 1e3

        def side(cid: str | None, level: float = level) -> JointColumnSide | None:
            if cid is None or cid not in info:
                return None
            st = info[cid]["stations"]
            return JointColumnSide(
                0.0, info[cid]["steel"].fy, info[cid]["shape"].area, pmax(st, plain)
            )

        rows: list[dict[str, Any]] = []
        summary: dict[str, Any] = {
            "id": j.id,
            "column": j.below,
            "columnAbove": j.above,
            "beams": sorted({b.id for b in j.beams}),
            "level": j.level,
        }
        if frame == "smf":
            for axis, group, zname in (("x", major, "zx"), ("y", minor, "zy")):
                if not group:
                    continue
                sides = []
                for cid in (j.below, j.above):
                    s = side(cid)
                    if s is not None:
                        s.z = getattr(info[cid]["shape"], zname)
                        sides.append(s)
                depth = cshape.dims["d"] if axis == "x" else cshape.dims["bf"]
                check, ratio = moment_ratio_check(sides, group, depth, j.above is None, axis, t)
                if check is not None:
                    rows.append(check)
                    summary[f"ratio{axis.upper()}"] = (
                        None if ratio is None or not math.isfinite(ratio) else round(ratio, 3)
                    )
                    if ratio is not None:
                        ratios.setdefault(j.below, []).append(ratio)
                        if j.above:
                            ratios.setdefault(j.above, []).append(ratio)
                    flag = connection_bracing_flag(
                        ratio,
                        group[0].fy,
                        info[group[0].id]["shape"].dims.get("bf", 0.0),
                        group[0].tf,
                        t,
                    )
                    if flag is not None and axis == "x":
                        rows.append(flag)
            if major:
                try:
                    section = section_of_profile(below.object.profile)
                    doubler = 0.0
                    for bid in major_beams:
                        conn = getattr(by_id[bid].object, "connection", None)
                        if conn is not None and conn.type == "flangePlate":
                            doubler = max(doubler, float(conn.doublerThickness or 0.0))
                    s = side(j.below)
                    pr = (s.puc / (s.area * s.fy)) if s else 0.0
                    rows += panel_zone_checks(
                        section, csteel.fy, major, pr, in_analysis, doubler, t
                    )
                except (ValueError, TypeError, KeyError) as error:
                    out["notes"].append(f"{j.id}: panel zone not checked: {error}")
        elif frame == "omf":
            for bid, h in zip(major_beams, major, strict=False):
                conn = getattr(by_id[bid].object, "connection", None)
                if conn is None or conn.type != "flangePlate":
                    continue
                provided = None
                if conn.columnStiffeners:
                    provided = float(conn.stiffenerThickness or conn.plateThickness)
                rows += continuity_plate_checks(
                    cshape.dims["tf"],
                    info[bid]["shape"].dims.get("bf", 0.0),
                    h.tf,
                    h.fy,
                    csteel.fy,
                    len(major) > 1,
                    provided,
                    t,
                )
        if rows:
            below.entry["checks"].extend({**r, "name": f"{r['name']} at {j.id}"} for r in rows)
            strength = [r for r in rows if not r["flag"]]
            summary["utilisation"] = max((r["utilisation"] for r in strength), default=0.0)
            summary["ok"] = all(r["ok"] for r in strength)
            out["joints"].append(summary)

    # Columns: compactness (relaxed where every ratio exceeds the table's), strength, splices,
    # bases.
    for m in members:
        if m.kind != "column" or m.id not in info:
            continue
        i = info[m.id]
        shape, steel, stations = i["shape"], i["steel"], i["stations"]
        lateral = roles[m.id] == "lateral"
        checks: list[dict[str, Any]] = []
        height = max((float(st.s[-1]) for st in stations if len(st.s)), default=0.0) * 1e3
        mpc = shape.zx * steel.fy
        splice = getattr(m.object, "splice", None)

        def splice_recheck(
            mreq: float,
            vreq: float,
            clause: str,
            what: str,
            m: SteelMember = m,
            splice: Any = splice,
            checks: list[dict[str, Any]] = checks,
        ) -> None:
            try:
                section = section_of_profile(m.object.profile)
                plate = mats.get(splice.plateMaterial) if splice.plateMaterial else None
                found = sc.check_splice(
                    splice,
                    section,
                    SteelMaterial.from_material(m.material),
                    SteelMaterial.from_material(plate) if plate is not None else None,
                    [("capacity design", 0.0, mreq, vreq)],
                    column=True,
                )
                checks.extend(
                    {**c, "name": f"{PREFIX}splice at {what}: {c['name']}", "clause": clause}
                    for c in found["checks"]
                )
            except (ValueError, TypeError, KeyError) as error:
                out["notes"].append(f"{m.id}: splice not re-checked: {error}")

        if splice is not None and height > 0:
            # The member's length stands for the clear height (the beams' depth not taken off).
            checks.append(splice_location_check(float(splice.distance), height, t))
        if not lateral:
            if splice is not None and height > 0:
                mreq, vreq, clause = splice_demand(
                    i["ry"], steel.fy, shape.zx, 2 * mpc, height, False, frame, t
                )
                splice_recheck(mreq, vreq, clause, "Mpc / H")
            if checks:
                m.entry["checks"].extend(checks)
            continue
        pu = pmax(stations, plain)
        own = ratios.get(m.id, [])
        relaxed = bool(own) and min(own) > t.widthThickness.relaxedRatio
        checks += toughness_flags(shape, t)
        checks += compactness_checks(shape, steel.fy, steel.e, "column", frame, pu, relaxed, t)
        omega_rows = [
            (stations[c].combination, float(np.max(stations[c].P)))
            for c in sorted(omega)
            if c < len(stations) and len(stations[c].s)
        ] + [
            (stations[c].combination, float(np.min(stations[c].P)))
            for c in sorted(omega)
            if c < len(stations) and len(stations[c].s)
        ]
        phi_pn = _capacity(m.entry, "Compression: buckling")
        phi_pt = _capacity(m.entry, "Tension: yielding") or 0.9 * steel.fy * shape.area
        if phi_pn > 0:
            checks += column_strength_checks(pu, phi_pn, omega_rows, phi_pt, t)
        if splice is not None and frame == "smf" and height > 0:
            mreq, vreq, clause = splice_demand(
                i["ry"], steel.fy, shape.zx, 2 * mpc, height, True, frame, t
            )
            splice_recheck(mreq, vreq, clause, "Ry Fy Zx")
        base = getattr(m.object, "basePlate", None)
        if base is not None and height > 0 and omega:
            v_amp = max(
                (
                    float(np.max(np.hypot(stations[c].Vx[:1], stations[c].Vy[:1])))
                    for c in omega
                    if c < len(stations) and len(stations[c].s)
                ),
                default=math.inf,
            )
            m_amp = max(
                (
                    float(np.max(np.hypot(stations[c].Mx[:1], stations[c].My[:1])))
                    for c in omega
                    if c < len(stations) and len(stations[c].s)
                ),
                default=math.inf,
            )
            v, mm = base_demands(i["ry"], steel.fy, shape.zx, height, v_amp, m_amp, t)
            out["members"][m.id]["base"] = {
                "V": round(v / 1e3, 1),
                "M": round(mm / 1e6, 1),
                "clause": cite(t, "bases"),
            }
            # The base re-checked at these forces with the least compression of the
            # combinations with the amplified load (uplift governs the anchors).
            p_least = min(
                (
                    float(stations[c].P[0])
                    for c in omega
                    if c < len(stations) and len(stations[c].s)
                ),
                default=0.0,
            )
            try:
                section = section_of_profile(m.object.profile)
                plate = mats.get(base.plateMaterial) if base.plateMaterial else None
                found = sc.check_base_plate(
                    base,
                    section,
                    SteelMaterial.from_material(m.material),
                    SteelMaterial.from_material(plate) if plate is not None else None,
                    [("capacity design", p_least, v, mm)],
                )
                checks.extend(
                    {
                        **c,
                        "name": f"{PREFIX}base at the capacity-design forces: {c['name']}",
                        "clause": cite(t, "bases"),
                    }
                    for c in found["checks"]
                )
            except (ValueError, TypeError, KeyError) as error:
                out["notes"].append(f"{m.id}: base plate not re-checked: {error}")
        m.entry["checks"].extend(checks)

    for m in members:
        _rescore(m.entry)
    if frame == "stmf":
        out["notes"].append(
            "special truss moment frames: the special segment is not found from the model; "
            "its checks run from the truss data"
        )
    return out


__all__ = [
    "PREFIX",
    "BeamHinge",
    "JointColumnSide",
    "Provisions",
    "SteelMember",
    "TrussSegment",
    "apply",
    "axial_coefficient",
    "base_demands",
    "beam_bracing_checks",
    "column_strength_checks",
    "compactness_checks",
    "connection_checks",
    "connection_shear",
    "continuity_plate_checks",
    "expected_ratios",
    "expected_truss_shear",
    "material_checks",
    "method_lines",
    "moment_ratio_check",
    "panel_zone_checks",
    "panel_zone_model_check",
    "protected_zone",
    "provisions",
    "seismic_table",
    "splice_demand",
    "splice_location_check",
    "toughness_flags",
    "truss_checks",
    "web_limit",
]
