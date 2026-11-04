"""Strut-and-tie models of deep beams, corbels and pile caps on the design strengths (method
``designStressLimits`` of the pack's ``concreteMethods.strutAndTie``; alpha 9 C5c).

The parent's strut-and-tie procedure (:mod:`saengine.design.stm`, φ and the effective strength
of f'c) is replaced where the pack picks this method:

- struts: σRd,max = ``strutUncracked`` fcd where there is no transverse tension (a prism),
  ``strutCracked`` ν' fcd in cracked zones (a bottle-shaped strut, a corbel's or a deep beam's
  support strut), ν' = 1 - fck / ``nuDivisor``;
- nodes: C-C-C ``nodeCCC`` ν' fcd, C-C-T ``nodeCCT`` ν' fcd, C-T-T ``nodeCTT`` ν' fcd;
- ties: As fyd; no φ.

Deep beams (:func:`deep_span_rows`): a span is deep below ``deepSpanRatio`` h; the web mesh of
``deepMeshRatio`` Ac per face and way (at least ``deepMeshMin`` mm²/m) at most
min(n b, mm) apart; the model of :mod:`saengine.design.deep_beams` (a strut from each
support's node to the load, the bottom bars as the tie at ``tieArm`` d) with the strengths above.
Corbels (:func:`corbel_rows`): the tie Ftd = FEd / tan θ + HEd with tan θ = z0 / ac, z0 =
``corbelLeverShare`` d, tan θ within ``corbelTanTheta``; the node under the bearing (C-C-T),
the strut at the column face (cracked); closed links ``corbelHorizontalLinks`` As,main where
ac <= ``corbelShortShare`` hc, else ``corbelVerticalLinks`` FEd / fyd where FEd > VRd,c.

The general D-region models of :mod:`saengine.design.stm_model` keep the parent's procedure
(the design report says so). Units: mm, N, MPa.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import design_strength, method_selection


def rules() -> Any | None:
    """The pack's ``strutAndTie`` group when it is this method (None: the parent's)."""
    if not method_selection.uses("strutAndTie", "designStressLimits"):
        return None
    return code_context.table("concreteMethods").strutAndTie


def cite(key: str = "strutAndTie") -> str:
    return code_context.cite("concreteMethods", key)


def nu_prime(fck: float, r: Any = None) -> float:
    """ν' = 1 - fck / divisor."""
    r = r or rules()
    return 1 - fck / r.nuDivisor


def strut_strength(fck: float, cracked: bool = True) -> float:
    """σRd,max [MPa] of a strut."""
    r = rules()
    if not cracked:
        return r.strutUncracked * design_strength.fcd(fck)
    return r.strutCracked * nu_prime(fck, r) * design_strength.fcd(fck)


def node_strength(fck: float, kind: str = "CCT") -> float:
    """σRd,max [MPa] of a node face: ``kind`` "CCC", "CCT" or "CTT"."""
    r = rules()
    k = {"CCC": r.nodeCCC, "CCT": r.nodeCCT}.get(kind, r.nodeCTT)
    return k * nu_prime(fck, r) * design_strength.fcd(fck)


def tie_capacity(area: float, fyk: float) -> float:
    """As fyd [N]."""
    return area * design_strength.fyd(fyk)


def strength_text(kind: str) -> str:
    """The formula of a node or strut's strength for the notes."""
    r = rules()
    if kind == "prism":
        return f"{r.strutUncracked:g} fcd"
    if kind == "strut":
        return f"{r.strutCracked:g} ν' fcd"
    k = {"CCC": r.nodeCCC, "CCT": r.nodeCCT}.get(kind, r.nodeCTT)
    return f"{k:g} ν' fcd"


# ─────────────────────────────── deep beams ───────────────────────────────


def is_deep(span: Any) -> tuple[bool, str] | None:
    """(deep, why) of a span by the pack's span ratio; None: not this method."""
    r = rules()
    if r is None:
        return None
    if span.clear < r.deepSpanRatio * span.depth:
        return True, f"l = {span.clear:.0f} mm < {r.deepSpanRatio:g} h = " + (
            f"{r.deepSpanRatio * span.depth:.0f} mm ({cite('deepBeams')})"
        )
    return None


def deep_mesh_rows(span: Any, suffix: str = "") -> list[dict[str, Any]]:
    """The web mesh of a deep span: per face and way As,dbmin, the spacing."""
    from saengine.design.check import _check

    r = rules()
    need = max(r.deepMeshRatio * span.width * 1000.0 / 2, r.deepMeshMin)  # mm²/m per face
    n, mm = r.deepMeshSpacing
    allowed = min(n * span.width, mm)
    rows = []
    for label, given in (("vertical", span.vertical), ("horizontal", span.horizontal)):
        area, spacing = given if given else (0.0, 0.0)
        per_face = area / 2 * 1000.0 / spacing if spacing > 0 else 0.0
        rows.append(
            _check(
                f"Deep beam web mesh, {label} (each face)",
                need,
                per_face,
                "mm²/m",
                None,
                f"As,dbmin = max({r.deepMeshRatio:g} Ac / 2, {r.deepMeshMin:g} mm²/m) per face "
                + ("" if spacing else "; none given (add bars)")
                + f" ({cite('deepBeams')}){suffix}",
            )
        )
        if spacing:
            rows.append(
                _check(
                    f"Deep beam web spacing, {label}",
                    spacing,
                    allowed,
                    "mm",
                    None,
                    f"s at most min({n:g} b, {mm:g} mm) ({cite('deepBeams')})",
                )
            )
    return rows


def deep_span_rows(span: Any, demands: Any, spans: tuple[float, float], suffix: str) -> list:
    """The strut-and-tie rows of a deep span (see the module notes); ``spans`` the shear span
    a at each support."""
    from saengine.design.check import _check

    r = rules()
    fck = span.fc
    z = r.tieArm * span.d
    rows = deep_mesh_rows(span, suffix)
    tie = (demands.moment[0] / z, demands.moment[1], "MEd / z")
    for k, (reaction, combination) in enumerate(demands.reactions):
        force = reaction * spans[k] / z
        if force > tie[0]:
            tie = (force, combination, f"R a / z at the {'left' if k == 0 else 'right'} support")
    rows.append(
        _check(
            "Tie (bottom bars, strut-and-tie)",
            tie[0] / 1e3,
            tie_capacity(span.tie_area, span.fy) / 1e3,
            "kN",
            tie[1],
            f"T = {tie[2]}, z = {r.tieArm:g} d = {z:.0f} mm; As fyd, As = {span.tie_area:.0f} "
            f"mm² ({cite()}); anchor the tie past the support's node{suffix}",
        )
    )
    for k, (reaction, combination) in enumerate(demands.reactions):
        side = "left" if k == 0 else "right"
        theta = math.atan2(z, spans[k])
        degrees = math.degrees(theta)
        rows.append(
            _check(
                f"Strut angle at the {side} support",
                r.minAngle,
                degrees,
                "°",
                None,
                f"θ = atan(z / a), a = {spans[k]:.0f} mm, z = {z:.0f} mm; at least "
                f"{r.minAngle:g}° ({cite('strutAndTie.minAngle') or cite()})",
            )
        )
        bearing = span.bearings[k]
        width = bearing * math.sin(theta) + span.tie_height * math.cos(theta)
        rows.append(
            _check(
                f"Strut at the {side} support",
                reaction / math.sin(theta) / 1e3,
                strut_strength(fck) * width * span.width / 1e3,
                "kN",
                combination,
                f"C = R / sin θ, θ = {degrees:.1f}°; cracked strut σRd,max = "
                f"{strength_text('strut')} = {strut_strength(fck):.2f} MPa, ws = lb sin θ + "
                f"wt cos θ = {width:.0f} mm ({cite()})",
            )
        )
        rows.append(
            _check(
                f"Node at the {side} support (C-C-T)",
                reaction / 1e3,
                node_strength(fck, "CCT") * bearing * span.width / 1e3,
                "kN",
                combination,
                f"σRd,max = {strength_text('CCT')} = {node_strength(fck, 'CCT'):.2f} MPa over "
                f"lb bw, lb = {bearing:.0f} mm ({cite()})",
            )
        )
    for (at, length), (load, combination) in zip(span.loads, demands.loads, strict=False):
        if load <= 0 or length <= 0:
            continue
        rows.append(
            _check(
                f"Node under the landing column at {at:.0f} mm (C-C-C)",
                load / 1e3,
                node_strength(fck, "CCC") * length * span.width / 1e3,
                "kN",
                combination,
                f"σRd,max = {strength_text('CCC')} = {node_strength(fck, 'CCC'):.2f} MPa over "
                f"lc bw, lc = {length:.0f} mm ({cite()})",
            )
        )
    return rows


# ─────────────────────────────── corbels ───────────────────────────────


def corbel_rows(
    corbel: Any, fc: float, fy: float, demand: Any, label: str = "Corbel"
) -> list[dict[str, Any]]:
    """The strut-and-tie rows of a corbel (:class:`saengine.library.modifiers.Corbel`) under
    ``demand`` (:class:`saengine.design.corbels.CorbelDemand`)."""
    from saengine.design import strut_shear
    from saengine.design.check import _check
    from saengine.design.rc import bar_area

    r = rules()
    b, h = float(corbel.width), float(corbel.depth)
    main = corbel.mainBars
    d = h - float(corbel.cover) - main.dia / 2
    ac = float(corbel.loadOffset or corbel.projection / 2)
    fed, combination = demand.shear, demand.combination
    given = corbel.horizontalForce
    least = r.corbelHorizontalForce * fed
    hed = max(float(given) * 1e3, least) if given is not None else least
    z0 = r.corbelLeverShare * d
    tan_theta = z0 / ac if ac > 0 else math.inf
    lo, hi = r.corbelTanTheta
    clause = cite("corbels")
    rows: list[dict[str, Any]] = [
        _check(
            f"{label}: strut inclination tan θ",
            lo,
            min(tan_theta, 99.0),
            "",
            None,
            f"tan θ = z0 / ac = {z0:.0f} / {ac:.0f}, z0 = {r.corbelLeverShare:g} d; within "
            f"{lo:g}-{hi:g} ({clause}; beyond {hi:g} the corbel is a short cantilever: the "
            "parent's shear rows are not run)",
        )
    ]
    used = min(max(tan_theta, lo), hi)
    ftd = fed / used + hed
    as_main = main.count * bar_area(main.dia)
    rows.append(
        _check(
            f"{label}: tie (main bars)",
            ftd / 1e3,
            tie_capacity(as_main, fy) / 1e3,
            "kN",
            combination,
            f"Ftd = FEd / tan θ + HEd = {fed / 1e3:.1f} / {used:.2f} + {hed / 1e3:.1f} kN "
            + (
                ""
                if given is not None
                else f"(HEd = {r.corbelHorizontalForce:g} FEd, {cite('strutAndTie.corbelHorizontalForce')}) "
            )
            + f"against As fyd, {main.count} Ø{main.dia:g} ({clause}); anchor them past the "
            "loading plate",
        )
    )
    if corbel.bearing:
        area = float(corbel.bearing) * b
        rows.append(
            _check(
                f"{label}: node under the bearing (C-C-T)",
                fed / 1e3,
                node_strength(fc, "CCT") * area / 1e3,
                "kN",
                combination,
                f"σRd,max = {strength_text('CCT')} = {node_strength(fc, 'CCT'):.2f} MPa over "
                f"{corbel.bearing:g} × {b:.0f} mm ({clause})",
            )
        )
    # The strut at the column face: the compression zone x = 2 (d - z0) there, the strut's
    # width x cos θ across its axis (SAEngine practice).
    fcd_s = strut_strength(fc)
    cos_theta = 1 / math.sqrt(1 + used * used)
    fc_strut = fed * math.sqrt(1 + 1 / (used * used))
    room = 2 * (d - z0) * cos_theta
    rows.append(
        _check(
            f"{label}: strut at the column face",
            fc_strut / 1e3,
            fcd_s * room * b / 1e3,
            "kN",
            combination,
            f"Fc = FEd / sin θ, cracked strut {strength_text('strut')} = {fcd_s:.2f} MPa over "
            f"x cos θ = {room:.0f} mm, x = 2 (d - z0) ({clause})",
        )
    )
    ties = corbel.ties
    links = ties.count * 2 * bar_area(ties.dia) if ties else 0.0
    if ac <= r.corbelShortShare * h:
        need = r.corbelHorizontalLinks * as_main
        text = (
            f"ac = {ac:.0f} <= {r.corbelShortShare:g} hc: closed horizontal links ΣAs,lnk >= "
            f"{r.corbelHorizontalLinks:g} As,main"
        )
    else:
        s = strut_shear.rules()
        vrdc = strut_shear.concrete_resistance(b, d, as_main / (b * d), fc, 0.0, s) if s else 0.0
        need = r.corbelVerticalLinks * fed / design_strength.fyd(fy) if fed > vrdc else 0.0
        text = (
            f"ac = {ac:.0f} > {r.corbelShortShare:g} hc: closed vertical links ΣAs,lnk >= "
            f"{r.corbelVerticalLinks:g} FEd / fyd where FEd > VRd,c = {vrdc / 1e3:.1f} kN"
        )
    rows.append(
        _check(
            f"{label}: closed links",
            need,
            links,
            "mm²",
            combination,
            text
            + (f"; {ties.count} closed Ø{ties.dia:g}" if ties else "; no links given")
            + f" ({clause})",
        )
    )
    return rows


def method_lines() -> list[str]:
    """The design report's lines of this method."""
    r = rules()
    if r is None:
        return []
    return [
        "Deep beams (span below "
        f"{r.deepSpanRatio:g} h), corbels and the deep pile caps by strut-and-tie models on the "
        f"design strengths: struts {r.strutUncracked:g} fcd uncracked, {r.strutCracked:g} ν' fcd "
        f"cracked, nodes {r.nodeCCC:g} / {r.nodeCCT:g} / {r.nodeCTT:g} ν' fcd (C-C-C, C-C-T, "
        "C-T-T), ν' = 1 - fck/" + f"{r.nuDivisor:g}, ties As fyd; deep beams' web mesh "
        f"{r.deepMeshRatio:g} Ac per face ({cite()}, {cite('deepBeams')}, {cite('corbels')}). "
        "The general strut-and-tie models of D-regions keep the parent pack's procedure."
    ]
