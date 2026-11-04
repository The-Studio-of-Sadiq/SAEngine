"""Check rows of the partial-factor methods for the members C5b left to the parent pack
(alpha 9 C5c): the glue between the generic method modules and slabs, stairs, walls and beams.
Each function runs only where :mod:`saengine.design.method_selection` names the method; the
default pack never comes here.

- Slabs and stairs (:func:`slab_span_depth_row`, :func:`stair_span_depth_row`): the limiting
  span/effective depth ratio of the ``deflection`` method (``spanDepthK``) with K by the
  span's continuity (flat slabs: the longer span; two-way slabs: the shorter), ρ of the bottom
  bars along the span, As,req = As,prov (on the safe side). It takes the place of the parent's
  least thickness table.
- Tying systems (:func:`tie_rows`, method ``tieForces``): a perimeter beam carries the
  peripheral tie Ftie,per = q1 li >= q2 and the column tie Ftie,col; an inner beam the internal
  tie q3 (l1 + l2) / 2 >= q4 with (l1 + l2) / 2 taken as its span (SAEngine practice); the
  beam's continuous bars at fyk (the accidental situation's γs) against it. They take the place
  of the parent's structural integrity bars.
- Walls out of their plane (:func:`wall_out_of_plane_rows`, method ``columnAnalogy``): a strip
  of the web as a column, l0 = β lc, i = t/√12, the moment per metre at least NEd e0, λ against
  λlim and the nominal curvature MEd (:func:`saengine.design.limit_state_rows.
  nominal_curvature`, single curvature: rm = 1), the strip's MRd at NEd against MEd; and the
  out-of-plane shear per metre against VRd,c. They take the place of the parent's slab shear
  and slender-wall rows.
- Flanged wall groups (:func:`web_shear_resistance`): each web's VRd by the variable strut
  method (bw = t, d = 0.8 lw, the horizontal bars as links, σcp of its axial force), summed.

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import design_strength, method_selection


def cite(key: str) -> str:
    return code_context.cite("concreteMethods", key)


def _row(name: str, demand: float, capacity: float, unit: str, combination: str | None,
         note: str, key: str | None = None, flag: bool = False,
         utilisation: float | None = None) -> dict[str, Any]:  # fmt: skip
    from saengine.design.limit_state_rows import _row as row

    return row(name, demand, capacity, unit, combination, note, key, flag, utilisation)


# ─────────────────────────────── slabs and stairs ───────────────────────────────


def span_depth_selected() -> bool:
    """True when the pack checks deflection by the limiting span/depth ratio."""
    return method_selection.uses("deflection", "spanDepthK")


def _system(ends: int, cantilever: bool = False, flat: bool = False) -> str:
    if cantilever:
        return "cantilever"
    if flat:
        return "flatSlab"
    return ("simplySupported", "endSpan", "interiorSpan")[min(max(ends, 0), 2)]


def span_depth_row(
    name: str, span: float, d: float, rho: float, fc: float, fy: float, system: str, note: str
) -> dict[str, Any]:
    from saengine.design import crack_control

    rho = max(rho, 1e-9)
    limit = crack_control.span_depth_limit(system, rho, 0.0, fc, fy, 1.0, 1.0, span)
    return _row(
        name,
        span / d if d > 0 else math.inf,
        limit,
        "",
        "service",
        f"l/d = {span:.0f}/{d:.0f}; {system}, ρ = {rho:.4f}, As,req = As,prov (on the safe "
        f"side){note}",
        "slabDeflection",
    )


def slab_span_depth_row(thickness: Any, h: float, fc: float, fy: float,
                        capacities: dict[str, Any]) -> dict[str, Any] | None:  # fmt: skip
    """The span/depth row of a slab panel from the parent's thickness survey (``thickness``
    :class:`saengine.design.slab.Thickness` with its span, continuous ends and direction) and
    the bottom layer along that span; None without them."""
    span = getattr(thickness, "span", None)
    if not span:
        return None
    along = getattr(thickness, "along", None) or "x"
    layer = capacities.get(f"bottom{along.upper()}") or next(
        (capacities[k] for k in ("bottomX", "bottomY") if capacities.get(k) is not None), None
    )
    if layer is None:
        return None
    d = float(layer.d)
    rho = float(layer.area) / (1000.0 * d) if d > 0 else 0.0
    system = _system(
        int(getattr(thickness, "ends", 0)), flat=bool(getattr(thickness, "flat", False))
    )
    return span_depth_row(
        "Deflection: span/depth",
        float(span),
        d,
        rho,
        fc,
        fy,
        system,
        f"; span {span:.0f} mm along {along} (h = {h:.0f} mm)",
    )


def stair_span_depth_row(label: str, span: float, ends: int, d: float, area: float, fc: float,
                         fy: float) -> dict[str, Any]:  # fmt: skip
    """The span/depth row of a stair flight or landing (``area`` the main bars [mm²/m])."""
    rho = area / (1000.0 * d) if d > 0 else 0.0
    return span_depth_row(f"{label}: deflection, span/depth", span, d, rho, fc, fy,
                          _system(ends), "")  # fmt: skip


# ─────────────────────────────── tying systems ───────────────────────────────


def tie_rules() -> Any | None:
    if not method_selection.uses("ties", "tieForces"):
        return None
    return code_context.table("concreteMethods").ties


def tie_rows(section: Any, perimeter: bool, span: float | None) -> list[dict[str, Any]]:
    """The tie rows of a cast-in-place beam (see the module notes): the beam type's bars run
    its whole length, so all its longitudinal bars (bottom, and top of a perimeter beam) are
    continuous ties."""
    r = tie_rules()
    if r is None:
        return []
    length = (span or 0.0) / 1e3
    fyk = section.fy
    f_yd = design_strength.fyd(fyk, accidental=True)
    bottom = sum(b.area for b in section.bars if b.y < 0)
    every = sum(b.area for b in section.bars)
    rows = []
    if perimeter:
        need = max(r.peripheralPerLength * length, r.peripheralMin)
        need = max(need, r.columnMin)
        rows.append(
            _row(
                "Peripheral and column tie",
                need,
                every * f_yd / 1e3,
                "kN",
                "accidental",
                f"Ftie,per = q1 li = {r.peripheralPerLength:g} × {length:.2f} m at least "
                f"{r.peripheralMin:g} kN, and the column tie {r.columnMin:g} kN; all the beam's "
                f"bars (they run its length) at fyd of the accidental situation = {f_yd:.0f} MPa",
                "ties",
            )
        )
    else:
        need = max(r.internalPerLength * length, r.internalMin)
        rows.append(
            _row(
                "Internal tie",
                need,
                bottom * f_yd / 1e3,
                "kN",
                "accidental",
                f"Ftie,int = q3 (l1 + l2)/2 = {r.internalPerLength:g} × {length:.2f} m ((l1 + "
                f"l2)/2 taken as the beam's span, SAEngine practice) at least {r.internalMin:g} "
                f"kN; the continuous bottom bars at fyd = {f_yd:.0f} MPa",
                "ties",
            )
        )
    return rows


# ─────────────────────────────── walls ───────────────────────────────


def wall_slenderness_rules() -> Any | None:
    if not method_selection.uses("wallSlenderness", "columnAnalogy"):
        return None
    return code_context.table("concreteMethods").wallSlenderness


#: The parent's out-of-plane rows the pack's wall method replaces.
_PARENT_OUT_OF_PLANE = ("Out-of-plane shear per metre", "Slender wall:")


def wall_out_of_plane_rows(
    checks: list[dict[str, Any]],
    geometry: Any,
    bars: Any,
    forces: list[Any],
    fc: float,
    fy: float,
    es: float,
) -> list[dict[str, Any]]:
    """A wall pier's rows with the pack's out-of-plane method (see the module notes)."""
    from saengine.design import limit_state_rows
    from saengine.design import walls as W

    r = wall_slenderness_rules()
    if r is None:
        return checks
    kept = [c for c in checks if not c["name"].startswith(_PARENT_OUT_OF_PLANE)]
    t, lw = geometry.thickness, geometry.length
    if lw <= 0 or t <= 0 or not forces:
        return kept
    width = r.stripWidth
    face = t / 2 - bars.cover - bars.horizontal_dia - bars.vertical_dia / 2
    xs = [-face, face] if bars.layers == 2 and face > 0 else [0.0]
    area = W.bar_area(bars.vertical_dia) * width / bars.vertical_spacing
    steel = area * len(xs)
    d = t / 2 + face if len(xs) == 2 else t / 2
    beta = r.effectiveLength["braced" if geometry.braced else "cantilever"]
    l0 = beta * geometry.clear_height
    i = t / math.sqrt(12)
    strip = W.PierInteraction(
        W.RcSection(
            profile=W.RectangleProfile(xDim=t, yDim=width),
            bars=tuple(W.Bar(x, 0.0, area, bars.vertical_dia) for x in xs),
            fc=fc,
            fy=fy,
            es=es,
            transverse_dia=bars.horizontal_dia,
        )
    )
    e0 = design_strength.eccentricity(t)
    worst = None
    for f in forces:
        ned = max(f.P, 0.0) / lw * width
        m0 = max(abs(f.M2) / lw * width, ned * e0)
        found = limit_state_rows.nominal_curvature(
            ned, m0, m0, False, False, l0, i, d, fc, fy, es, t * width, steel
        )
        med = float(found["med"])
        sense = 1 if f.M2 >= 0 else -1
        cap = strip.capacity(ned, "M2", sense)
        util = med / cap if cap > 0 else math.inf
        if worst is None or util > worst[0]:
            worst = (util, f, med, cap, found, ned)
    if worst is not None:
        util, f, med, cap, found, ned = worst
        kept.append(
            _row(
                "Out-of-plane bending with second order, per metre",
                med / 1e6,
                cap / 1e6,
                "kN·m/m",
                f.combination,
                f"a {width:.0f} mm strip as a column: NEd = {ned / 1e3:.0f} kN/m, l0 = {beta:g} lc"
                f" = {l0:.0f} mm, i = t/√12 = {i:.0f} mm, M at least NEd e0 (e0 = {e0:.0f} mm), "
                "single curvature (rm = 1); "
                + limit_state_rows.slenderness_note(found, geometry.clear_height, beta, i, False)
                + f" ({cite('wallSlenderness')})",
                "wallSlenderness",
                utilisation=util,
            )
        )
    v3 = max(forces, key=lambda f: abs(f.V3))
    if abs(v3.V3) > 0:
        rho = steel / 2 / (width * d) if len(xs) == 2 else steel / (width * d)
        vrdc, _ = limit_state_rows.one_way_shear(rho, d, fc)
        q = abs(v3.V3) / lw * 1000
        kept.append(
            _row(
                "Out-of-plane shear per metre",
                q / 1e3,
                vrdc / 1e3,
                "kN/m",
                v3.combination,
                f"VRd,c of a 1 m strip, d = {d:.0f} mm, ρl = {rho:.4f} of the tension face's bars",
                "shearNoLinks",
            )
        )
    return kept


def flanged_shear_selected() -> bool:
    """True when walls take the pack's shear method (and partial factors)."""
    return design_strength.partial_factors() and method_selection.uses("shear", "variableStrut")


def ductile_wall_factor() -> float:
    """ε of the design shear of ductile walls: the largest of the pack's ductility classes'
    (on the safe side where the class is not passed)."""
    from saengine.design import curvature_ductility

    found = curvature_ductility.rules()
    if found is None:
        return 1.0
    return max(float(c.wallShearFactor) for c in found.classes.values())


def web_shear_resistance(length: float, thickness: float, bars: Any, axial: float, fc: float,
                         fy: float) -> float:  # fmt: skip
    """VRd [N] of one web of a wall group by the variable strut method."""
    from saengine.design import strut_shear
    from saengine.design.rc import bar_area

    s = strut_shear.rules()
    if s is None or length <= 0:
        return 0.0
    d = 0.8 * length
    asw = bars.layers * bar_area(bars.horizontal_dia)
    links = strut_shear.link_resistance(thickness, d, asw, bars.horizontal_spacing, fc, fy, s)
    rho_l = bars.rho_l(thickness)
    vrd_c = strut_shear.concrete_resistance(
        thickness, d, min(rho_l / 2, s.rhoLMax), fc, axial / (thickness * length), s
    )
    return max(vrd_c, min(links.vrd_s, links.vrd_max))


# ─────────────────────────────── report ───────────────────────────────


def method_lines() -> list[str]:
    """The design report's lines of the C5c areas in force."""
    from saengine.design import perimeter_punching, stress_fields

    lines = list(stress_fields.method_lines())
    if span_depth_selected():
        lines.append(
            "Slabs and stairs: deflection by the limiting span/effective depth ratio with K of "
            "the span's continuity (two-way slabs the shorter span, flat slabs the longer, K "
            f"of flat slabs), ρ of the bottom bars, As,req = As,prov ({cite('slabDeflection')}); "
            "it takes the place of the parent pack's least thickness table."
        )
    if method_selection.uses("interfaceShear", "interfaceShear"):
        lines.append(
            "Construction joints of columns and walls: interface shear VRdi = c fctd + μ σn + "
            f"ρ fyd μ <= 0.5 ν fcd by the surface ({cite('interfaceShear')})."
        )
    if tie_rules() is not None:
        lines.append(
            "Tying systems: peripheral and column ties on the perimeter beams, internal ties on "
            f"the inner beams, the continuous bars at fyk ({cite('ties')}); in place of the "
            "parent pack's structural integrity bars."
        )
    if perimeter_punching.footing_rules() is not None:
        lines.append(
            "Footings, pile caps and rafts: punching on control perimeters within 2d of the "
            "column, VEd less the soil pressure (pile reactions) inside, vRd,c × 2d/a, the "
            f"moment by k of c1/c2 ({cite('footingPunching')}); one-way shear VRd,c and flexure "
            "on the design strengths; the punching reinforcement is not laid out."
        )
    if wall_slenderness_rules() is not None:
        lines.append(
            "Walls out of their plane: a 1 m strip as a column (l0 = β lc, the moment at least "
            "NEd e0, nominal curvature beyond λlim) and the out-of-plane shear VRd,c "
            f"({cite('wallSlenderness')}); flanged wall groups' shear by the webs' VRd "
            f"({cite('flangedWallShear')})."
        )
    if method_selection.uses("barShapes", "barShapes"):
        lines.append(
            "Detailing: mandrel diameters, hooks and links' bends, compression laps with the "
            f"transverse bars at their ends and column splices ({cite('barShapes')}, "
            f"{cite('compressionLaps')})."
        )
    if method_selection.uses("seismic", "curvatureDuctility"):
        lines.append(
            "Confinement of DCM/DCH columns' critical regions and ductile walls' boundary "
            "elements: α ωwd against 30 μφ νd εsy,d bc/b0 - 0.035 (walls with νd + ωv), μφ "
            f"from q0 and T1 ({cite('confinement')})."
        )
    return lines
