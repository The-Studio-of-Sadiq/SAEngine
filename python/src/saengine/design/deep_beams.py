"""Deep beams and transfer girders (default pack BNBC 2020 Part 6 Sec 6.4.6).

A beam span is deep (Sec 6.4.6.1, ACI 318-11 Sec 11.7.1) when its clear span ln is at most 4 h,
or when a concentrated load lies within 2 h of a support's face, with the beam loaded on one
face and supported on the other so that struts can form. A transfer girder is a beam a column
lands on (its column does not continue below); it is checked here when that makes it deep, and
by the sectional checks of :mod:`saengine.design.check` otherwise. Its Ω0 combinations are
:mod:`saengine.design.overstrength`'s (Sec 2.5.5.6.1).

For a deep span the design adds, beside the sectional checks (the one-way shear of a slender
beam is flagged as reference: the strut-and-tie model governs):

- the shear limit Vu <= φ 0.83 √f'c bw d (Sec 6.4.6.2);
- the least distributed web steel: vertical Av >= 0.0025 bw s, horizontal Avh >= 0.0015 bw s2,
  s and s2 at most d/5 and 300 mm (Sec 6.4.6.3, 6.4.6.4);
- a strut-and-tie model, the one of the deep pile caps (:mod:`saengine.design.stm`, the
  pack's strut-and-tie procedure: the default pack's BNBC 2020 Appendix I, which Sec 6.3.7.1 and 6.4.6 send deep
  beams to; φ = 0.75 of Sec 6.2.3.2.6): at each
  support a strut from the support's node to the load, the bottom bars as the tie at z = 0.9 d
  (the pack's ``tieArm``) over the span. The load of a span is the landing column's (the jump
  of the analysis shear where it stands), or for a distributed load the resultant of each half
  at ln/4 from the face. Checked: the tie T = max(R a / z, Mu / z) against φ As fy; the strut
  at each support, C = R / sin θ, against φ 0.85 βs f'c ws bw with ws = lb sin θ + wt cos θ
  (βs 0.75 with the web steel of Sec I.3.3, else 0.6); the support's C-C-T node, R against
  φ 0.85 (0.8) f'c lb bw; the landing column's C-C-C node, P against φ 0.85 f'c lc bw; and the
  strut angle θ = atan(z / a) at least 25° (Sec I.2.5). The clauses are the pack's.

Units: mm, N, MPa inside; reported in kN, mm².
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design import stm
from saengine.design.clauses import Clauses, short_clause
from saengine.design.rc import RcSection, bar_area
from saengine.design.rc import value as rc_value

__all__ = [
    "CLAUSES",
    "DeepSpan",
    "SpanDemands",
    "deep_span_checks",
    "is_deep",
    "member_checks",
    "web_steel",
]

#: The clause of each check, from the code pack in force (``designClauses.deepBeams``).
CLAUSES: Clauses = Clauses("deepBeams")


def __getattr__(name: str) -> str:
    # ``REFERENCE_NOTE``, said on the sectional shear checks of a deep span (read from the pack).
    if name == "REFERENCE_NOTE":
        return (
            "deep span: for reference, the strut-and-tie model governs "
            f"({short_clause('deepBeamsText', 'reference')})"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _table() -> Any:
    return code_context.pack_table("transfer").deepBeam


@dataclass
class DeepSpan:
    """One span of a beam between two supports [mm, MPa]."""

    clear: float  # ln, face to face
    depth: float  # h
    width: float  # bw
    d: float
    fc: float
    fy: float
    bearings: tuple[float, float]  # support lengths along the beam, left and right
    tie_area: float  # bottom bars As [mm²]
    tie_height: float  # wt = 2 (h - d)
    fyt: float = 420.0
    #: Vertical web steel: (Av of one set [mm²], spacing s [mm]), None without stirrups.
    vertical: tuple[float, float] | None = None
    #: Horizontal web steel: (Avh of one layer, both faces [mm²], spacing s2 [mm]), or None.
    horizontal: tuple[float, float] | None = None
    #: Landing columns: (distance from the left face [mm], length along the beam [mm]).
    loads: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class SpanDemands:
    """The factored demands of a span [N, N·mm], each with its combination."""

    reactions: tuple[tuple[float, str | None], tuple[float, str | None]]  # at the faces
    moment: tuple[float, str | None]  # largest sagging moment
    shear: tuple[float, str | None]  # largest shear
    #: Per landing column of :attr:`DeepSpan.loads`: (P, combination).
    loads: list[tuple[float, str | None]] = field(default_factory=list)


def is_deep(span: DeepSpan) -> tuple[bool, str]:
    """(deep, why): ln <= 4 h, or a concentrated load within 2 h of a face (Sec 6.4.6.1)."""
    table = _table()
    if span.clear <= table.spanRatio * span.depth:
        return True, f"ln = {span.clear:.0f} mm <= {table.spanRatio:g} h = " + (
            f"{table.spanRatio * span.depth:.0f} mm"
        )
    reach = table.loadDistance * span.depth
    for at, length in span.loads:
        gap = min(at - length / 2, span.clear - at - length / 2)
        if gap <= reach:
            return True, (
                f"a column lands {max(gap, 0.0):.0f} mm from a support face, within "
                f"{table.loadDistance:g} h = {reach:.0f} mm"
            )
    return False, ""


def web_steel(span: DeepSpan) -> dict[str, Any]:
    """The least web steel of Sec 6.4.6.3-4 against what the span has: per direction the
    ratio given and required and the spacing given and allowed."""
    table = _table()
    allowed = min(span.d / table.spacingDepth, table.spacingMax)
    found = {}
    for key, given, need in (
        ("vertical", span.vertical, table.verticalRatio),
        ("horizontal", span.horizontal, table.horizontalRatio),
    ):
        area, spacing = given if given else (0.0, 0.0)
        ratio = area / (span.width * spacing) if spacing > 0 else 0.0
        found[key] = {"ratio": ratio, "required": need, "spacing": spacing, "allowed": allowed}
    return found


def _shear_spans(span: DeepSpan) -> tuple[float, float]:
    """Shear span a [mm] at each support, from the support's centre to the load's: the nearest
    landing column, or ln/4 from the face for a distributed load."""
    left = span.bearings[0] / 2
    right = span.bearings[1] / 2
    if span.loads:
        first = min(at for at, _ in span.loads)
        last = max(at for at, _ in span.loads)
        return left + first, right + span.clear - last
    return left + span.clear / 4, right + span.clear / 4


def deep_span_checks(span: DeepSpan, demands: SpanDemands, where: str = "") -> list[dict]:
    """The checks of one deep span (see the module's docstring), in the design report's
    shape."""
    from saengine.design.check import _check

    table = _table()
    suffix = f"; {where}" if where else ""
    checks: list[dict[str, Any]] = []
    root = math.sqrt(span.fc)
    vu, v_combination = demands.shear
    limit = rc_value("PHI_SHEAR") * table.shearLimit * root * span.width * span.d
    checks.append(
        _check(
            "Deep beam shear limit",
            vu / 1e3,
            limit / 1e3,
            "kN",
            v_combination,
            f"φ {table.shearLimit:g} √f'c bw d, φ = {rc_value('PHI_SHEAR'):g}, bw = {span.width:.0f} mm, "
            f"d = {span.d:.0f} mm ({CLAUSES['limit']}){suffix}",
        )
    )
    web = web_steel(span)
    for key, label, clause in (
        ("vertical", "vertical (stirrups)", CLAUSES["vertical"]),
        ("horizontal", "horizontal (side bars)", CLAUSES["horizontal"]),
    ):
        found = web[key]
        checks.append(
            _check(
                f"Deep beam web steel, {label}",
                found["required"] * 1e3,
                found["ratio"] * 1e3,
                "‰",
                None,
                f"A / (bw s) at least {found['required']:g}"
                + (
                    f", s = {found['spacing']:.0f} mm"
                    if found["spacing"]
                    else ": none given (add bars)"
                )
                + f" ({clause})",
            )
        )
        if found["spacing"]:
            checks.append(
                _check(
                    f"Deep beam web spacing, {label}",
                    found["spacing"],
                    found["allowed"],
                    "mm",
                    None,
                    f"s at most d/{table.spacingDepth:g} and {table.spacingMax:g} mm ({clause})",
                )
            )
    # ── the strut-and-tie model ──
    z = stm.factor("tieArm") * span.d
    spans = _shear_spans(span)
    confined = all(web[k]["ratio"] >= stm.factor("webRatio") / 2 for k in web) and (
        web["vertical"]["ratio"] + web["horizontal"]["ratio"] >= stm.factor("webRatio")
    )
    tie = (demands.moment[0] / z, demands.moment[1], "Mu / z")
    for k, (reaction, combination) in enumerate(demands.reactions):
        force = reaction * spans[k] / z
        if force > tie[0]:
            tie = (force, combination, f"R a / z at the {'left' if k == 0 else 'right'} support")
    checks.append(
        _check(
            "Tie (bottom bars, strut-and-tie)",
            tie[0] / 1e3,
            stm.tie_capacity(span.tie_area, span.fy) / 1e3,
            "kN",
            tie[1],
            f"T = {tie[2]}, z = {stm.factor('tieArm'):g} d = {z:.0f} mm; φ As fy, φ = "
            f"{stm.phi():g}, As = {span.tie_area:.0f} mm² ({CLAUSES['phi']}, "
            f"{stm.cite('deltaFpBonded') or CLAUSES['stm']}); anchor the tie past the support's node{suffix}",
        )
    )
    least = stm.min_angle()
    for k, (reaction, combination) in enumerate(demands.reactions):
        side = "left" if k == 0 else "right"
        a = spans[k]
        theta = math.atan2(z, a)
        degrees = math.degrees(theta)
        checks.append(
            _check(
                f"Strut angle at the {side} support",
                least,
                degrees,
                "°",
                None,
                f"θ = atan(z / a), a = {a:.0f} mm, z = {z:.0f} mm; at least {least:g}° "
                f"({stm.cite('minAngle') or CLAUSES['stm']})",
            )
        )
        bearing = span.bearings[k]
        width = stm.strut_width(bearing, span.tie_height, theta)
        checks.append(
            _check(
                f"Strut at the {side} support",
                reaction / math.sin(theta) / 1e3,
                stm.strut_capacity(span.fc, width * span.width, "bottle", confined) / 1e3,
                "kN",
                combination,
                f"C = R / sin θ, θ = {degrees:.1f}°; bottle-shaped, βs = "
                f"{stm.factor('betaBottle' if confined else 'betaBottlePlain'):g}"
                + (
                    ""
                    if confined
                    else f" (web steel below the {stm.factor('webRatio'):g} of "
                    f"{stm.cite('webRatio') or CLAUSES['stm']})"
                )
                + f", ws = lb sin θ + wt cos θ = {width:.0f} mm (lb = {bearing:.0f}, wt = "
                f"{span.tie_height:.0f}) ({stm.cite('betaBottle') or CLAUSES['stm']})",
            )
        )
        checks.append(
            _check(
                f"Node at the {side} support (C-C-T)",
                reaction / 1e3,
                stm.node_capacity(span.fc, bearing * span.width, "CCT") / 1e3,
                "kN",
                combination,
                f"φ 0.85 βn f'c lb bw, βn = {stm.factor('betaCCT'):g}, lb = {bearing:.0f} mm "
                f"({stm.cite('betaCCT') or CLAUSES['stm']})",
            )
        )
    for (at, length), (load, combination) in zip(span.loads, demands.loads, strict=False):
        if load <= 0 or length <= 0:
            continue
        checks.append(
            _check(
                f"Node under the landing column at {at:.0f} mm (C-C-C)",
                load / 1e3,
                stm.node_capacity(span.fc, length * span.width, "CCC") / 1e3,
                "kN",
                combination,
                f"φ 0.85 βn f'c lc bw, βn = {stm.factor('betaCCC'):g}, lc = {length:.0f} mm "
                f"({stm.cite('betaCCC') or CLAUSES['stm']})",
            )
        )
    return checks


# ─────────────────────────────────── from the design ───────────────────────────────────

_ON_LINE = 1.0


def _web_of(beam: Any, section: RcSection) -> tuple[tuple | None, tuple | None]:
    """(vertical, horizontal) web steel of a beam type: the stirrups' legs at their spacing,
    and the side bars as layers of two (one each face) over the clear height between the
    top and bottom bars."""
    reinforcement = beam.reinforcement
    transverse = reinforcement.transverse if reinforcement else None
    vertical = None
    if transverse is not None and transverse.spacing:
        vertical = (transverse.legs * bar_area(transverse.dia), float(transverse.spacing))
    sides = [
        g for g in (reinforcement.longitudinal if reinforcement else []) if g.position == "sides"
    ]
    horizontal = None
    count = sum(g.count for g in sides)
    if count >= 2:
        layers = count // 2
        dia = max(g.dia for g in sides)
        inset = float(reinforcement.cover) + (transverse.dia if transverse else 0.0)
        spacing = (section.depth - 2 * inset) / (layers + 1)
        horizontal = (2 * bar_area(dia), spacing)
    return vertical, horizontal


def _tie(section: RcSection) -> tuple[float, float]:
    """(As [mm²], wt [mm]) of the bottom bars: the bars in the lowest quarter of the depth;
    wt twice their centroid's height."""
    low = [b for b in section.bars if b.y < -section.depth / 4]
    if not low:
        return 0.0, 0.0
    area = sum(b.area for b in low)
    centroid = sum(b.area * b.y for b in low) / area
    return area, 2 * (section.depth / 2 + centroid)


def _stations(
    pieces: list[Any], combinations: list[str], turned: bool, a: np.ndarray, axis: np.ndarray
) -> list[tuple[float, np.ndarray, np.ndarray]]:
    """Per station (s along the beam [mm], Vy per combination [N], Mx per combination
    [N·mm])."""
    from saengine.design.check import _profile_blocks

    rows: list[tuple[float, np.ndarray, np.ndarray]] = []
    count = len(combinations)
    for piece in pieces:
        if piece.start is None or piece.end is None:
            continue
        p0 = np.asarray(piece.start, dtype=float)[:2] * 1e3
        p1 = np.asarray(piece.end, dtype=float)[:2] * 1e3
        s0, s1 = float((p0 - a) @ axis), float((p1 - a) @ axis)
        for first, _, values in _profile_blocks(piece, turned):
            vy, mx = values["Vy"], values["Mx"]
            stations = vy.shape[1]
            for k in range(stations):
                s = s0 + (s1 - s0) * k / max(stations - 1, 1)
                v = np.zeros(count)
                m = np.zeros(count)
                v[first : first + vy.shape[0]] = vy[:, k]
                m[first : first + mx.shape[0]] = mx[:, k]
                rows.append((s, v, m))
    rows.sort(key=lambda r: r[0])
    return rows


def _peak(values: np.ndarray, combinations: list[str]) -> tuple[float, str | None]:
    if not len(values):
        return 0.0, None
    c = int(np.argmax(values))
    return float(values[c]), combinations[c]


def member_checks(
    element: Any,
    beam: Any,
    section: RcSection,
    pieces: list[Any],
    combinations: list[str],
    turned: bool,
    framing: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The deep-beam checks of a beam of the building model, span by span between its
    supports (``framing``: :class:`saengine.design.check._BeamFraming`): ``(checks, notes)``,
    both empty when no span is deep."""
    a = np.array(element.start, dtype=float)
    c = np.array(element.end, dtype=float)
    length = float(np.linalg.norm(c - a))
    if length <= 0 or not pieces:
        return [], []
    axis = (c - a) / length
    z = float(element.elevation)
    below: list[tuple[float, float]] = []  # (station [mm], length along the beam)
    landing: list[tuple[float, float]] = []
    from saengine.design.check import _segment_cross

    for position, bottom, top, reach in framing.columns:
        foot = np.asarray(position, dtype=float)[:2]
        s = float((foot - a) @ axis)
        off = float(np.linalg.norm(foot - (a + s * axis)))
        if off > reach + _ON_LINE or not -reach - _ON_LINE <= s <= length + reach + _ON_LINE:
            continue
        if bottom < z - 1.0 <= top:
            below.append((min(max(s, 0.0), length), 2 * reach))
        elif z - section.depth - 1.0 <= bottom <= z + 1.0 and top > z + 1.0:
            landing.append((s, 2 * reach))
    for w0, w1, bottom, top, half in framing.walls:
        if not bottom < z - 1.0 <= top:
            continue
        for s, end in ((0.0, a), (length, c)):
            t, off = framing._station(end, w0, w1)
            if off <= half + _ON_LINE and -1e-6 <= t <= 1 + 1e-6:
                below.append((s, 2 * half))
        hit = _segment_cross(a, c, w0, w1)
        if hit is not None:
            below.append((hit * length, 2 * half))
    merged: list[tuple[float, float]] = []
    for s, w in sorted(below):
        if merged and s - merged[-1][0] <= (merged[-1][1] + w) / 2 + _ON_LINE:
            merged[-1] = (merged[-1][0], max(merged[-1][1], w))
            continue
        merged.append((s, w))
    below = merged
    # A landing column that also continues below is a support, not a load.
    landing = [(s, w) for s, w in landing if not any(abs(s - x) <= w / 2 for x, _ in below)]
    if len(below) < 2:
        return [], []
    vertical, horizontal = _web_of(beam, section)
    tie_area, tie_height = _tie(section)
    try:
        d = section.effective_depth(top=False)
    except ValueError:
        return [], []
    stations = _stations(pieces, combinations, turned, a, axis)
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    fyt = min(section.fy, rc_value("FYT_SHEAR_MAX"))
    for (s0, w0), (s1, w1) in itertools.pairwise(below):
        left, right = s0 + w0 / 2, s1 - w1 / 2
        clear = right - left
        if clear <= 0:
            continue
        loads = [(s - left, w) for s, w in landing if left < s < right]
        span = DeepSpan(
            clear=clear,
            depth=section.depth,
            width=section.width,
            d=d,
            fc=section.fc,
            fy=section.fy,
            bearings=(max(w0, 1.0), max(w1, 1.0)),
            tie_area=tie_area,
            tie_height=max(tie_height, 1.0),
            fyt=fyt,
            vertical=vertical,
            horizontal=horizontal,
            loads=loads,
        )
        deep, why = is_deep(span)
        if not deep:
            continue
        inside = [r for r in stations if left - 1.0 <= r[0] <= right + 1.0]
        if not inside:
            continue
        shear = np.max(np.abs(np.stack([r[1] for r in inside])), axis=0)
        sag = np.max(-np.stack([r[2] for r in inside]), axis=0)
        ends = []
        for face in (left, right):
            nearest = min(inside, key=lambda r: abs(r[0] - face))
            ends.append(_peak(np.abs(nearest[1]), combinations))
        point_loads = []
        for at, _ in loads:
            here = [r for r in inside if abs(r[0] - (left + at)) <= _ON_LINE]
            if len(here) >= 2:
                jump = np.abs(here[0][1] - here[-1][1])
                point_loads.append(_peak(jump, combinations))
            else:
                point_loads.append((0.0, None))
        demands = SpanDemands(
            reactions=(ends[0], ends[1]),
            moment=_peak(sag, combinations),
            shear=_peak(shear, combinations),
            loads=point_loads,
        )
        where = f"span {s0 / 1e3:.2f}-{s1 / 1e3:.2f} m: deep ({why}, {CLAUSES['deep']})"
        if loads:
            where += f"; a transfer girder under {len(loads)} landing column(s)"
        checks += deep_span_checks(span, demands, where)
        notes.append(f"{element.id}: {where}")
    return checks, notes
