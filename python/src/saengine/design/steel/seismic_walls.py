"""Steel plate shear walls: special plate shear walls and composite steel plate shear walls.

Every number is the code pack's ``steelSeismic`` table (BNBC 2020: Part 6 Sec 10.20.17, Eqs
6.10.307-6.10.308, and Sec 13.5.6, Eq 6.13.28); the clauses come from its ``sources``.

A steel plate wall is a wall type whose material is steel: its thickness is the web plate's.
Its vertical boundary elements (VBE) are the columns at its ends and its horizontal boundary
elements (HBE) the beams along its top and bottom, found from the building's geometry. The
wall type's ``plateWall`` gives the concrete of a composite wall.

- **Webs** (:func:`web_angle`, :func:`web_shear`): the angle of the tension field α (Eq
  6.10.308) and Vn = 0.42 Fy tw Lcf sin 2α (Eq 6.10.307) against the storey's in-plane shear of
  the analysis; the panel aspect ratio; the web connections at the web's expected yield.
- **Boundary elements** (special walls): the VBE inertia Ic ≥ 0.00307 tw h⁴ / L, their
  flexure from the yielded web, the HBE flexure from the net tension field of the webs above
  and below, the HBE-to-VBE connection shear (1.1 Ry Mp at the ends plus the web's share), the
  seismically compact HBE and VBE, the HBE bracing (flags where the model gives no input).
- **Composite walls** (:func:`composite_wall_checks`): Vns = 0.6 As Fy when the concrete
  stiffens the plate (its thickness and the connectors), else the plate alone as a web above;
  the bars and their spacing.

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.design.steel import seismic as S
from saengine.design.steel.seismic import PREFIX, _check, _rule, cite
from saengine.design.steel.seismic_braced import _cross

TOL = 50.0  # mm, a column or beam meeting a wall's end or edge (SAEngine practice)


def web_angle(
    tw: float, length: float, height: float, ab: float, ac: float, ic: float, table=None
) -> float:
    """α [rad] of the web's tension field from the vertical (Eq 6.10.308): tan⁴α = (1 + tw L /
    (2 Ac)) / (1 + tw h (1/Ab + h³ / (c Ic L))). ``ab`` or ``ic`` inf: a rigid element."""
    c = S._table(table).plateWalls.angleCoefficient
    num = 1 + tw * length / (2 * ac) if ac > 0 else math.inf
    inv_ab = 1 / ab if ab > 0 and math.isfinite(ab) else 0.0
    term = height**3 / (c * ic * length) if ic > 0 and math.isfinite(ic) and length > 0 else 0.0
    den = 1 + tw * height * (inv_ab + term)
    return math.atan((num / den) ** 0.25)


def web_shear(fy: float, tw: float, lcf: float, alpha: float, table: Any | None = None) -> float:
    """Vn = c Fy tw Lcf sin 2α (Eq 6.10.307) [N]."""
    w = S._table(table).plateWalls
    return w.shearCoefficient * fy * tw * lcf * math.sin(2 * alpha)


def vbe_inertia_required(tw: float, height: float, length: float, table=None) -> float:
    """Sec 10.20.17.4.7: Ic ≥ c tw h⁴ / L [mm⁴]."""
    w = S._table(table).plateWalls
    return w.inertiaCoefficient * tw * height**4 / length


def tension_field(ry: float, fy: float, tw: float, alpha: float) -> dict[str, float]:
    """The web's expected yield in tension at α per unit length of its boundary [N/mm]: on a
    VBE the normal (horizontal) Ry Fy tw sin²α, on an HBE the normal (vertical) Ry Fy tw cos²α,
    along both Ry Fy tw sin α cos α."""
    s = ry * fy * tw
    return {
        "vbeNormal": s * math.sin(alpha) ** 2,
        "hbeNormal": s * math.cos(alpha) ** 2,
        "shear": s * math.sin(alpha) * math.cos(alpha),
        "stress": s,
    }


@dataclass
class Boundary:
    """A boundary element of the wall: its member id and section numbers."""

    id: str
    area: float
    inertia: float  # about the axis perpendicular to the wall's plane (in-plane bending)
    z: float  # plastic modulus for in-plane bending
    depth: float  # along the wall
    fy: float
    ry: float
    ry_radius: float = 0.0  # ry of the section (HBE bracing)
    aw: float = 0.0  # φv Vn of the web (HBE shear) [N]
    shape: Any = None
    e: float = 200_000.0


def composite_wall_checks(
    pw: Any,
    tw: float,
    length: float,
    fy: float,
    vu: float,
    web_vn: float,
    concrete_fc: float | None,
    table: Any | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """Sec 13.5.6: a composite plate shear wall. ``(checks, φVn)``: the plate stiffened by the
    concrete (its thickness on each side, connectors) takes Vns = 0.6 As Fy (Eq 6.13.28, As = tw
    × the plate length), else the plate alone at ``web_vn`` (the web strength of a plate shear
    wall); the detailing."""
    t = S._table(table)
    cw = t.compositeSeismic.plateWall
    clause = cite(t, "compositeWall")
    need = cw.concreteBothSides if pw.concrete == "bothSides" else cw.concreteOneSide
    thick_ok = pw.concreteThickness >= need
    stiffened = thick_ok and pw.connectors
    checks = [
        _check(
            "composite wall concrete thickness",
            need,
            pw.concreteThickness,
            "mm",
            clause,
            f"at least {need:g} mm "
            + ("on each side" if pw.concrete == "bothSides" else "on the one side"),
        ),
        _rule(
            "composite wall connectors",
            pw.connectors,
            clause,
            "headed studs or other connectors against local buckling and separation of the "
            "plate and the concrete",
        ),
        _check(
            "composite wall bar ratio",
            cw.ratioMin,
            pw.barRatio,
            "",
            clause,
            f"each way at least {cw.ratioMin:g}",
        ),
        _check(
            "composite wall bar spacing",
            pw.barSpacing,
            cw.spacingMax,
            "mm",
            clause,
            f"at most {cw.spacingMax:g} mm",
        ),
        _rule(
            "composite wall plate edges",
            False,
            clause,
            "the plate is continuously connected on all edges to the framing and boundary "
            "members by welds or slip-critical bolts developing its nominal shear strength",
            flag=True,
        ),
    ]
    comp = t.compositeSeismic
    if concrete_fc is not None:
        checks.append(
            _check(
                "composite wall concrete f'c",
                comp.concreteMin,
                concrete_fc,
                "MPa",
                cite(t, "compositeMaterials"),
                f"at least {comp.concreteMin:g} MPa",
            )
        )
    if stiffened:
        vn = cw.shearCoefficient * tw * length * fy
        phi = cw.phi
        note = (
            f"Vns = {cw.shearCoefficient:g} As Fy, As = {tw:g} × {length:.0f} mm (stiffened plate)"
        )
    else:
        vn = web_vn
        phi = t.plateWalls.phi
        note = "the concrete does not stiffen the plate: the plate alone as a plate shear wall web"
    checks.append(_check("composite wall shear", vu / 1e3, phi * vn / 1e3, "kN", clause, note))
    return checks, phi * vn


def _vbe_axis_inertia(shape: Any, rotation: float, along: np.ndarray) -> tuple[float, float, float]:
    """(I, Z, depth along the wall) of a column for bending in the wall's plane."""
    from saengine.design import ductile_joints as dj

    ex, ey = dj.column_axes(rotation)
    major = abs(float(along @ ey)) >= abs(float(along @ ex))
    d = shape.dims
    if major:
        return shape.ix, shape.zx, d.get("d") or d.get("H", 0.0)
    return shape.iy, shape.zy, d.get("bf") or d.get("B", 0.0)


def design_plate_walls(
    walls: list[tuple[Any, Any, Any]],
    sections_of: dict[str, list[dict[str, Any]]],
    building: Any,
    types: dict[str, Any],
    mats: dict[str, Any],
    settings: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The design elements (``kind`` "wall", ``wallType`` "steelPlate" or "compositePlate")
    of the steel plate walls ``(element, wall type, steel material)``, with the in-plane shear
    of the analysis' storey sections (``sections_of`` by wall id). Returns ``(elements,
    notes)``."""
    from saengine.design.steel import members as sm
    from saengine.design.steel import seismic_braced as SB
    from saengine.design.steel.properties import shape_properties
    from saengine.library.bim import WallElement

    t = S.seismic_table()
    notes: list[str] = []
    if t is None or t.plateWalls is None:
        return [], [f"steel plate walls: {S.pack_name()} has no plate shear wall provisions"]
    w = t.plateWalls
    special = "spsw" in SB.braced_provisions(settings, t).kinds
    phi_flex = SB._steel_phi("flexure")
    beams, columns = SB.frame_members(building, types)
    steel_walls = [
        (e, types.get(e.type))
        for e in building.elements
        if isinstance(e, WallElement) and e.type in {x[1].id for x in walls}
    ]

    def boundary(element: Any, kind: str, along: np.ndarray) -> Boundary | None:
        obj = types.get(element.type)
        mat = mats.get(getattr(obj, "material", None)) if obj is not None else None
        if obj is None or mat is None or not hasattr(obj, "profile"):
            return None
        try:
            shape = shape_properties(obj.profile)
            steel = sm.Steel.of(mat)
        except (ValueError, sm.SteelDesignError):
            return None
        ry, _rt, _what = S.expected_ratios(mat, shape.family, t)
        d = shape.dims
        if kind == "column":
            inertia, z, depth = _vbe_axis_inertia(shape, float(element.rotation or 0.0), along)
        else:
            inertia, z, depth = shape.ix, shape.zx, d.get("d", 0.0)
        try:
            phi_vn = sm.shear_major(shape, steel).design
        except (ValueError, KeyError, ZeroDivisionError):
            phi_vn = 0.0
        return Boundary(
            element.id,
            shape.area,
            inertia,
            z,
            depth,
            steel.fy,
            ry,
            shape.ry,
            phi_vn,
            shape,
            steel.e,
        )

    elements: list[dict[str, Any]] = []
    for e, wt, mat in walls:
        a = np.asarray(e.start, dtype=float)
        b = np.asarray(e.end, dtype=float)
        lw = float(np.linalg.norm(b - a))
        if lw <= 0:
            continue
        along = (b - a) / lw
        tw = float(wt.thickness)
        try:
            steel = sm.Steel.of(mat)
        except sm.SteelDesignError as error:
            notes.append(f"{e.id}: not designed as a steel plate wall: {error}")
            continue
        ry, _rt, _what = S.expected_ratios(mat, "plate", t)
        checks: list[dict[str, Any]] = []
        own_notes: list[str] = []
        vbes: list[Boundary] = []
        for end in (a, b):
            col = next(
                (
                    c
                    for c in columns
                    if np.linalg.norm(np.asarray(c.position, dtype=float) - end) <= TOL + 300
                    and c.bottom - TOL <= e.bottom
                    and c.top + TOL >= e.top
                ),
                None,
            )
            found = boundary(col, "column", along) if col is not None else None
            if found is not None:
                vbes.append(found)
        hbes: dict[str, Boundary] = {}
        for edge, level in (("top", e.top), ("bottom", e.bottom)):
            for bm in beams:
                if abs(float(bm.elevation) - level) > TOL + 300:
                    continue
                p, q = np.asarray(bm.start, dtype=float), np.asarray(bm.end, dtype=float)
                span = float(np.linalg.norm(q - p))
                if span <= 0 or abs(_cross(along, (q - p) / span)) > 1e-3:
                    continue
                if abs(_cross(along, p - a)) > TOL:
                    continue
                mid = (float((p - a) @ along) + float((q - a) @ along)) / 2
                if 0 <= mid <= lw:
                    found = boundary(bm, "beam", along)
                    if found is not None:
                        hbes[edge] = found
                        break
        length = lw  # between the VBE centrelines (the wall runs between them)
        lcf = length - sum(v.depth for v in vbes) / 2 if len(vbes) == 2 else length
        height = float(e.top - e.bottom)
        hbe = hbes.get("top") or hbes.get("bottom")
        ac = min((v.area for v in vbes), default=math.inf)
        ic = min((v.inertia for v in vbes), default=math.inf)
        ab = hbe.area if hbe is not None else math.inf
        alpha = web_angle(tw, length, height, ab, ac, ic, t)
        vn = web_shear(steel.fy, tw, lcf, alpha, t)
        vu = 0.0
        sections = sections_of.get(e.id, [])
        governing = None
        for s in sections:
            for cut in (s.get("cuts") or {}).values():
                for combo, row in (cut or {}).items():
                    v = abs(float(row.get("V2", 0.0))) * 1e3
                    if v > vu:
                        vu, governing = v, combo
        pw = getattr(wt, "plateWall", None)
        composite = pw is not None and pw.concrete != "none"
        if not vbes:
            own_notes.append("no column found at the wall's ends: Ac and Ic taken as rigid")
        if hbe is None:
            own_notes.append("no beam found along the wall's top or bottom: Ab taken as rigid")
        clause = cite(t, "spswWeb")
        alpha_note = (
            f"α = {math.degrees(alpha):.1f}° (Eq 6.10.308: tw {tw:g}, L {length:.0f}, h "
            f"{height:.0f}, Ab {ab:.0f}, Ac {ac:.0f}, Ic {ic / 1e6:.0f}e6)"
        )
        if composite:
            concrete = mats.get(pw.concreteMaterial) if pw.concreteMaterial else None
            fc = getattr(getattr(concrete, "concrete", None), "fc", None)
            rows, _phi_vn = composite_wall_checks(pw, tw, lcf, steel.fy, vu, vn, fc, t)
            checks += rows
        else:
            checks.append(
                _check(
                    "plate wall web shear",
                    vu / 1e3,
                    w.phi * vn / 1e3,
                    "kN",
                    clause,
                    f"Vn = {w.shearCoefficient:g} Fy tw Lcf sin 2α, Lcf = {lcf:.0f} mm, "
                    f"{alpha_note}",
                    governing,
                )
            )
        field_ = tension_field(ry, steel.fy, tw, alpha)
        if special:
            ratio = length / height if height > 0 else 0.0
            ok = w.aspectMin < ratio <= w.aspectMax
            checks.append(
                _rule(
                    "panel aspect ratio L/h",
                    ok,
                    cite(t, "spswAspect"),
                    f"L/h = {ratio:.2f}: above {w.aspectMin:g} and at most {w.aspectMax:g}",
                )
            )
            checks.append(
                _rule(
                    "web connections at the expected yield",
                    False,
                    cite(t, "spswConnections"),
                    f"the web's welds or bolts to the HBE and VBE develop Ry Fy tw = "
                    f"{field_['stress']:.0f} N/mm at α = {math.degrees(alpha):.1f}°",
                    flag=True,
                )
            )
            checks.append(
                _rule(
                    "openings in the web",
                    True,
                    cite(t, "spswOpenings"),
                    "an opening is bounded on all sides by HBE and VBE over the panel's full "
                    "width and height",
                    flag=True,
                )
            )
            for v in vbes:
                need = vbe_inertia_required(tw, height, length, t)
                checks.append(
                    _check(
                        f"VBE {v.id} stiffness",
                        need / 1e6,
                        v.inertia / 1e6,
                        "×10⁶ mm⁴",
                        cite(t, "spswStiffness"),
                        f"Ic ≥ {w.inertiaCoefficient:g} tw h⁴ / L",
                    )
                )
                mu = field_["vbeNormal"] * height**2 / 12
                checks.append(
                    _check(
                        f"VBE {v.id} flexure from the yielded web",
                        mu / 1e6,
                        phi_flex * v.fy * v.z / 1e6,
                        "kN·m",
                        cite(t, "spswBoundary"),
                        f"Ry Fy tw sin²α = {field_['vbeNormal']:.0f} N/mm over h, ends fixed "
                        "(w h² / 12) against φ Fy Z (the web braces the VBE); the axial force "
                        "of the overturning is in the column's own checks",
                    )
                )
                checks += _compact(v, "column", t)
            above = _wall_above(e, steel_walls, lw)
            for edge, hb in hbes.items():
                net = field_["hbeNormal"]
                if edge == "top" and above is not None:
                    net = abs(net - tension_field(ry, steel.fy, above, alpha)["hbeNormal"])
                elif edge == "bottom":
                    continue  # the bottom HBE is the top HBE of the wall below (or the base)
                mu = net * lcf**2 / 8
                checks.append(
                    _check(
                        f"HBE {hb.id} flexure from the webs' tension field",
                        mu / 1e6,
                        phi_flex * hb.fy * hb.z / 1e6,
                        "kN·m",
                        cite(t, "spswBoundary"),
                        f"net Ry Fy tw cos²α = {net:.0f} N/mm (webs above and below), simply "
                        "supported (hinges at the HBE ends are permitted); the gravity load "
                        "with the web giving no support is in the beam's own checks",
                    )
                )
                mp = hb.fy * hb.z
                vu_c = 2 * w.connectionFactor * hb.ry * mp / max(lcf, 1.0) + net * lcf / 2
                checks.append(
                    _check(
                        f"HBE {hb.id} to VBE connection shear",
                        vu_c / 1e3,
                        hb.aw / 1e3,
                        "kN",
                        cite(t, "spswHbeConnection"),
                        f"2 ({w.connectionFactor:g} Ry Mp) / Lcf + the web's {net:.0f} N/mm "
                        "over half the span, against the HBE web; the connection itself "
                        "follows the ordinary moment frame rules",
                    )
                )
                checks += _compact(hb, "beam", t)
                checks.append(
                    _rule(
                        f"HBE {hb.id} lateral bracing",
                        False,
                        cite(t, "spswBracing"),
                        f"braced at every VBE and at most {w.hbeBracing:g} ry E / Fy = "
                        f"{w.hbeBracing * hb.ry_radius * hb.e / hb.fy:.0f} mm apart, both "
                        f"flanges, each brace {w.hbeBraceShare:g} Fy bf tf",
                        flag=True,
                    )
                )
            checks.append(
                _rule(
                    "VBE panel zones, splices and the moment ratio",
                    False,
                    cite(t, "spswHbeConnection"),
                    "the VBE panel zones next to the top and base HBE follow the special moment "
                    "frame panel zone rules; VBE splices follow the column splice rules; the "
                    "column-beam moment ratio holds at every HBE/VBE joint without the webs",
                    flag=True,
                )
            )
        else:
            own_notes.append("not a special plate shear wall system: the web's shear strength only")
        strength = [c for c in checks if not c["flag"]]
        for c in checks:
            c["name"] = c["name"] if c["name"].startswith(PREFIX) else PREFIX + c["name"]
        elements.append(
            {
                "id": e.id,
                "kind": "wall",
                "type": e.type,
                "members": [],
                "checks": checks,
                "utilisation": max((c["utilisation"] for c in strength), default=0.0),
                "ok": all(c["ok"] for c in strength),
                "wallType": "compositePlate" if composite else "steelPlate",
                "plateWall": {
                    "alpha": round(math.degrees(alpha), 2),
                    "Vn": round(vn / 1e3, 1),
                    "Lcf": round(lcf, 0),
                    "vbe": [v.id for v in vbes],
                    "hbe": {k: v.id for k, v in hbes.items()},
                    "special": special,
                },
                "curtains": None,
                "curtainsRequired": None,
                "boundary": None,
                "piers": [],
                "couplingBeams": [],
                "drift": None,
                "height": height,
                "notes": own_notes,
            }
        )
    return elements, notes


def _wall_above(e: Any, walls: list[tuple[Any, Any]], length: float) -> float | None:
    """The web thickness of the steel wall standing on ``e`` (same line, its bottom at e's
    top), None without one."""
    a = np.asarray(e.start, dtype=float)
    for other, wt in walls:
        if other.id == e.id or wt is None or abs(float(other.bottom) - float(e.top)) > TOL:
            continue
        if np.linalg.norm(np.asarray(other.start, dtype=float) - a) <= TOL:
            return float(wt.thickness)
    return None


def _compact(member: Boundary, kind: str, table: Any) -> list[dict[str, Any]]:
    if member.shape is None:
        return []
    return [
        _check(
            f"{'HBE' if kind == 'beam' else 'VBE'} {member.id} {name} width-thickness "
            "(seismically compact)",
            ratio,
            limit,
            "",
            cite(table, "spswCompact"),
            f"λ = {ratio:.1f} ≤ λps = {limit:.1f}",
        )
        for name, ratio, limit in S.seismic_compact_limits(
            member.shape, member.fy, member.e, kind, "spsw", 0.0, table
        )
    ]


def method_lines() -> list[str]:
    t = S._table(None)
    return [
        (
            f"Steel plate shear walls ({S.pack_name()} {cite(t, 'spswWeb')}, "
            f"{cite(t, 'compositeWall')}): the web's tension field angle and shear strength "
            "against the storey's in-plane shear, the aspect ratio, the boundary elements' "
            "stiffness and their flexure and connection shear from the yielded webs; composite "
            "walls by the stiffened plate's 0.6 As Fy with the concrete's thickness, connectors "
            "and bars. The columns at a wall's ends are its VBE and the beams along it its HBE."
        )
    ]


__all__ = [
    "Boundary",
    "composite_wall_checks",
    "design_plate_walls",
    "method_lines",
    "tension_field",
    "vbe_inertia_required",
    "web_angle",
    "web_shear",
]
