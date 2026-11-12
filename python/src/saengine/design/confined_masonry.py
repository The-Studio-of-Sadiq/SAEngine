"""Confined masonry: masonry walls built first and confined by cast-in-place RC tie columns and
tie beams. The ``"confinedPanels"`` method of the code pack's ``masonry.confined`` (absent: the
pack does not cover confined masonry).

The tie columns are placed by the pack's rules (:func:`tie_column_positions`): at the wall's
ends, at both sides of openings larger than ``tieColumns.openingArea`` and within the wall so
that none are farther apart than ``tieColumns.maxSpacing``; a tie beam at every floor. The shell
model carries the masonry only (the confining elements are not modelled), and the checks are
the masonry's allowable stress checks with:

- in-plane flexure on the reinforced masonry assumptions: the cracked section with the tie
  columns' bars as the tension steel (bars in compression not counted, the masonry stress
  only), fb ≤ Fb and fs ≤ Fs;
- in-plane shear as the sum of the unreinforced masonry's Fv over the masonry length (the pier
  less the tie columns' depth) and the tie columns' concrete at the pack's allowable vc =
  ``concreteShear`` √f'c (their bars not counted);
- out of plane on the unreinforced masonry assumptions (fa/Fa + fb/Fb ≤ 1, fb - fa ≤ Ft);
- the walls' least thickness and h/t, the tie beams' spacing, the confining elements' size,
  bars and ties (:func:`element_rows`);
- per building (:func:`building_rows`): the wall density in each direction and the storeys by
  zone, the confined walls per direction and the plan's length to width.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from saengine.design import masonry as M
from saengine.design import masonry_asd as A
from saengine.design import masonry_dimensions as D
from saengine.design.ductile_members import _row
from saengine.design.rc import DesignError, bar_area


def rules() -> Any:
    """The code pack's confined masonry rules, or None (not covered)."""
    return M.table().confined


def covered() -> bool:
    return rules() is not None


@dataclass(frozen=True)
class Element:
    """A tie column or tie beam [mm]."""

    width: float
    depth: float
    count: int
    dia: float
    tie_dia: float
    tie_spacing: float
    end_tie_spacing: float | None = None

    @property
    def area(self) -> float:
        return self.width * self.depth

    @property
    def steel(self) -> float:
        return self.count * bar_area(self.dia)


@dataclass(frozen=True)
class Confinement:
    column: Element
    beam: Element
    fc: float
    fy: float
    cover: float = 25.0
    toothed: bool = True


def confinement_of(c: Any, thickness: float, mats: dict[str, Any]) -> Confinement:
    """The :class:`Confinement` of a wall type's ``confinement`` (``library.objects.
    WallConfinement``); raises :class:`DesignError` for unknown materials."""
    concrete = mats.get(c.concrete)
    rebar = mats.get(c.rebar)
    if concrete is None or getattr(concrete, "concrete", None) is None:
        raise DesignError(f"confinement: '{c.concrete}' is not a concrete")
    if rebar is None or getattr(rebar, "steel", None) is None:
        raise DesignError(f"confinement: '{c.rebar}' is not a rebar")

    def element(e: Any) -> Element:
        return Element(
            float(e.width or thickness),
            float(e.depth),
            int(e.count),
            float(e.dia),
            float(e.tieDia),
            float(e.tieSpacing),
            None if e.endTieSpacing is None else float(e.endTieSpacing),
        )

    return Confinement(
        element(c.tieColumn),
        element(c.tieBeam),
        float(concrete.concrete.fc),
        float(rebar.steel.fy),
        float(c.cover),
        bool(c.toothed),
    )


def tie_column_positions(
    length: float, openings: Iterable[tuple[float, float, float]], depth: float
) -> list[float]:
    """Centres [mm from the wall's start] of the tie columns of a wall of ``length`` with
    ``openings`` ``(start, end, area m²)`` along it: at both ends, at both sides of each opening
    larger than the pack's area, and between them at no more than the pack's spacing (centre to
    centre)."""
    r = rules()
    big = float(r.tieColumns["openingArea"])
    spacing = float(r.tieColumns["maxSpacing"])
    half = depth / 2.0
    fixed = {half, max(length - half, half)}
    for start, end, area in openings:
        if area > big + 1e-9:
            fixed.add(max(start - half, half))
            fixed.add(min(end + half, length - half))
    points = sorted(fixed)
    # Split the runs longer than the spacing (not the span of a large opening itself); a column
    # that would fall in a small opening moves beside it.
    holes = [(s, e) for s, e, _a in openings]
    big_spans = [
        (max(s - half, half), min(e + half, length - half))
        for s, e, a in openings
        if a > big + 1e-9
    ]
    out: list[float] = []
    for a, b in itertools.pairwise(points):
        out.append(a)
        if any(abs(a - s) < 1e-6 and abs(b - e) < 1e-6 for s, e in big_spans):
            continue
        n = math.ceil((b - a) / spacing - 1e-9)
        for k in range(1, n):
            x = a + (b - a) * k / n
            for s, e in holes:
                if s - half < x < e + half:
                    x = s - half if x - (s - half) <= (e + half) - x else e + half
            out.append(min(max(x, half), length - half))
    out.append(points[-1])
    return sorted({round(x, 1) for x in out})


def pier_ends(
    pier_start: float, pier_end: float, columns: Iterable[float], depth: float
) -> tuple[bool, bool, list[float]]:
    """(tie column at the pier's start, at its end, the centres within it, from its start)."""
    inside = [c - pier_start for c in columns if pier_start - 1 <= c <= pier_end + 1]
    lw = pier_end - pier_start
    at_start = any(abs(x - depth / 2) <= depth / 2 + 1 for x in inside)
    at_end = any(abs(x - (lw - depth / 2)) <= depth / 2 + 1 for x in inside)
    return at_start, at_end, inside


def _worst(rows: Iterable[dict[str, Any] | None]) -> dict[str, Any] | None:
    return max((r for r in rows if r), key=lambda r: r["utilisation"], default=None)


def panel_checks(
    geometry: Any,
    forces: list[Any],
    m: M.Masonry,
    conf: Confinement,
    columns: list[float],
    lateral: Iterable[str] = (),
    storeys: int | None = None,
) -> M.MasonryDesign:
    """The checks of a confined masonry pier (a panel and its tie columns) under the allowable
    stress combinations (see the module notes). ``columns``: the centres of its tie columns
    from the pier's start."""
    r = rules()
    if r is None:
        raise DesignError("confined masonry is not covered by the code pack")
    lateral = set(lateral)
    t, lw, h = geometry.thickness, geometry.length, geometry.clear_height
    col = conf.column
    share = M.allowable_share(m)
    notes = list(m.notes)
    checks: list[dict[str, Any] | None] = []
    w = r.wall
    checks.append(
        _row(
            f"Confined wall thickness ({M.clause('confinedWalls')})",
            float(w["thicknessMin"]),
            t,
            "mm",
        )
    )
    checks.append(
        _row(
            f"Confined wall h/t ≤ {float(w['heightThicknessMax']):g} ({M.clause('confinedWalls')})",
            h / t,
            float(w["heightThicknessMax"]),
            "",
        )
    )
    gaps = [b - a for a, b in itertools.pairwise(columns)]
    if gaps:
        checks.append(
            _row(
                f"Tie column spacing ({M.clause('confinedPlacement')})",
                max(gaps),
                float(r.tieColumns["maxSpacing"]),
                "mm",
            )
        )
    checks.append(
        _row(
            f"Tie beam spacing ({M.clause('confinedPlacement')})",
            h,
            float(r.tieBeams["maxSpacing"]),
            "mm",
            note="a tie beam at every floor",
        )
    )
    if share < 1.0:
        notes.append(f"{share:.0%} of the allowable masonry stresses ({M.clause('quality')})")
    if not forces:
        found = [c for c in checks if c]
        return M.MasonryDesign(found, notes + ["no forces: not checked"], 0.0)

    ae = t * lw
    s_out = lw * t * t / 6.0
    h_eff = D.effective_height(h, geometry.braced)
    fa_full = A.allowable_axial(m.fm, h_eff, t)
    fb_full = A.allowable_flexural_compression(m.fm)
    ft_full = A.allowable_flexural_tension(m, "bed")
    fv_full = A.allowable_wall_shear_plain(m)
    fs_allow = A.allowable_steel(conf.fy, "tensionDeformed")
    n = float(M.table().elastic.es) / m.em
    # The tie columns' bars, at their centres; the far ones in tension either way.
    bars = [(x, col.steel) for x in columns]
    mirrored = [(lw - x, a) for x, a in bars]
    ends = [x for x in columns if x <= col.depth or x >= lw - col.depth]
    masonry_length = max(lw - len(columns) * col.depth, 0.0)
    cover = conf.cover + col.tie_dia + col.dia / 2
    concrete = sum(col.width * max(col.depth - cover, 0.0) for _ in ends)
    vc = float(r.concreteShear) * math.sqrt(conf.fc)
    axial, combined, tension, in_plane, steel, shear = [], [], [], [], [], []
    for f in forces:
        k_lat = A.lateral_factor(f.combination, lateral)
        k = share * k_lat
        inc = f"; × {k_lat:.3g} (wind or earthquake)" if k_lat > 1 else ""
        fa = max(f.P, 0.0) / ae
        axial.append(
            _row(
                f"Axial stress fa ≤ Fa ({M.clause('axial')})",
                fa,
                k * fa_full,
                "MPa",
                f.combination,
                f"{f.where}{inc}",
            )
        )
        fb_out = abs(f.M2) / s_out
        combined.append(
            _row(
                f"Out of plane fa/Fa + fb/Fb ≤ 1 ({M.clause('confinedVerification')})",
                fa / (k * fa_full) + fb_out / (k * fb_full),
                float(M.table().allowable.interaction),
                "",
                f.combination,
                f"{f.where}; fb {fb_out:.2f} MPa{inc}",
            )
        )
        tension.append(
            _row(
                f"Out of plane fb - fa ≤ Ft ({M.clause('flexuralTension')})",
                max(fb_out - f.P / ae, 0.0),
                k * ft_full,
                "MPa",
                f.combination,
                f"{f.where}{inc}",
            )
        )
        worst_fb, worst_fs = 0.0, 0.0
        for layout in (bars, mirrored):
            fb, fs, _c = A.cracked_section(lw, t, layout, f.P, f.M3, n)
            worst_fb, worst_fs = max(worst_fb, fb), max(worst_fs, fs)
        in_plane.append(
            _row(
                f"In-plane fb ≤ Fb, tie columns in tension ({M.clause('confinedVerification')})",
                worst_fb,
                k * fb_full,
                "MPa",
                f.combination,
                f"{f.where}; cracked section, n = {n:.1f}{inc}",
            )
        )
        steel.append(
            _row(
                f"Tie column bars fs ≤ Fs ({M.clause('steel')})",
                worst_fs,
                fs_allow,
                "MPa",
                f.combination,
                f.where,
            )
        )
        capacity = k * fv_full * t * masonry_length + vc * concrete
        shear.append(
            _row(
                f"In-plane shear V ≤ masonry + tie columns ({M.clause('confinedShear')})",
                abs(f.V2) / 1e3,
                capacity / 1e3,
                "kN",
                f.combination,
                f"{f.where}; masonry {k * fv_full:.3f} MPa over {masonry_length:.0f} mm, "
                f"concrete vc {vc:.2f} MPa over {concrete:.0f} mm²{inc}",
            )
        )
    for group in (axial, combined, tension, in_plane, steel, shear):
        checks.append(_worst(group))
    if not ends:
        notes.append("no tie column at the pier's ends: the in-plane tension has no bars")
    found = [c for c in checks if c]
    strength = [c for c in found if not c["flag"]]
    return M.MasonryDesign(found, notes, max((c["utilisation"] for c in strength), default=0.0))


def element_rows(conf: Confinement) -> list[dict[str, Any]]:
    """The size, bar and tie rows of the tie columns and tie beams."""
    r = rules()
    e = r.element
    clause = M.clause("confinedElements")
    rows: list[dict[str, Any]] = []
    for name, el in (("Tie column", conf.column), ("Tie beam", conf.beam)):
        rows += [
            _row(f"{name} area ({clause})", float(e["areaMin"]), el.area, "mm²"),
            _row(f"{name} depth in the wall's plane ({clause})", float(e["dimensionMin"]),
                 el.depth, "mm"),
            _row(f"{name} bars ({clause})",
                 max(float(e["steelAreaMin"]), float(e["steelRatioMin"]) * el.area), el.steel,
                 "mm²"),
            _row(f"{name} tie diameter ({clause})", float(e["tieDiaMin"]), el.tie_dia, "mm"),
            _row(f"{name} tie spacing ({clause})", el.tie_spacing, float(e["tieSpacingMax"]),
                 "mm"),
        ]  # fmt: skip
    end = conf.column.end_tie_spacing or conf.column.tie_spacing
    if end > float(e["endTieSpacing"]) + 1e-9:
        row = _row(
            f"Tie column end-zone ties ({clause})",
            end,
            float(e["endTieSpacing"]),
            "mm",
            note="recommended at the top and bottom of each storey",
        )
        row["flag"] = True
        rows.append(row)
    return rows


def details_text(conf: Confinement) -> list[str]:
    """The detailing notes of the confining elements for the report and drawings."""
    e = rules().element
    lap = max(float(e["lapDiameters"]) * conf.column.dia, float(e["lapMin"]))
    return [
        (
            f"Tie beams: 90° hooks of at least {float(e['hookLength']):g} mm at intersections; tie "
            "column bars into the tie beam up to its top bars with 90° hooks; ties with 135° hooks "
            f"({M.clause('confinedElements')})."
        ),
        (
            f"Laps at least {lap:.0f} mm at mid-height of the tie columns, none in the ground floor; "
            f"special lintels over openings wider than {float(e['lintelOpening']):g} mm."
        ),
        "Masonry built first with toothed edges at the tie columns, then the tie columns cast."
        if conf.toothed
        else "Masonry built first with steel dowels in the bed joints at the tie columns.",
    ]


def polygon_area(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=False):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def building_rows(
    walls: list[dict[str, Any]],
    floor_area: float,
    zone: int | None,
    storeys: int,
    footprint: tuple[float, float] | None = None,
) -> list[dict[str, Any]]:
    """The building's rows: ``walls`` ``{"start", "end", "thickness", "confined"}`` (every
    structural masonry wall of every storey, mm), ``floor_area`` the sum of the floor areas of
    all storeys [mm²], ``footprint`` the plan's (length, width) [mm]."""
    r = rules()
    if r is None:
        return []
    rows: list[dict[str, Any]] = []
    layout = M.clause("confinedLayout")
    row = next((z for z in r.zones if zone in z.zones), None) if zone is not None else None
    if row is None:
        row = max(r.zones, key=lambda z: z.density)
        zone_note = "zone not known: the strictest row"
    else:
        zone_note = f"Zone {zone}"
    area = {"x": 0.0, "y": 0.0}
    confined = {"x": 0, "y": 0}
    for w in walls:
        dx = float(w["end"][0]) - float(w["start"][0])
        dy = float(w["end"][1]) - float(w["start"][1])
        axis = "x" if abs(dx) >= abs(dy) else "y"
        area[axis] += math.hypot(dx, dy) * float(w["thickness"])
        if w.get("confined") and w.get("lowest"):
            confined[axis] += 1
    for axis in ("x", "y"):
        density = area[axis] / floor_area if floor_area > 0 else 0.0
        rows.append(
            _row(
                f"Wall density in {axis.upper()} ≥ {float(row.density):.0%} ({layout})",
                float(row.density),
                density,
                "",
                note=f"{zone_note}; walls {area[axis] / 1e6:.2f} m² over the floors' "
                f"{floor_area / 1e6:.1f} m²",
            )
        )
        rows.append(
            _row(
                f"Confined walls in {axis.upper()} ({layout})",
                float(r.wallsPerDirection),
                float(confined[axis]),
                "",
                note="in the lowest storey",
            )
        )
    rows.append(
        _row(
            f"Storeys of confined masonry ({layout})",
            float(storeys),
            float(row.storeys),
            "",
            note=zone_note,
        )
    )
    if footprint is not None and min(footprint) > 0:
        ratio = max(footprint) / min(footprint)
        flag = _row(
            f"Plan length/width ≤ {float(r.aspectMax):g} ({layout})",
            ratio,
            float(r.aspectMax),
            "",
            note="guideline",
        )
        flag["flag"] = True
        rows.append(flag)
    return rows


def method_text() -> list[str]:
    r = rules()
    if r is None:
        return []
    return [
        (
            f"Confined masonry ({M.clause('confined')}): tie columns at the walls' ends, beside "
            f"openings over {float(r.tieColumns['openingArea']):g} m² and at ≤ "
            f"{float(r.tieColumns['maxSpacing']):g} mm ({M.clause('confinedPlacement')}), a tie beam "
            "at every floor. The panels by allowable stress design: in-plane flexure on the cracked "
            "section with the tie columns' bars in tension, in-plane shear by the unreinforced "
            f"masonry over its length plus the tie columns' concrete at {float(r.concreteShear):g} "
            f"√f'c ({M.clause('confinedShear')}), out of plane as unreinforced masonry; the "
            f"confining elements' sizes, bars and ties ({M.clause('confinedElements')}); the wall "
            f"density and storeys by zone ({M.clause('confinedLayout')})."
        )
    ]


__all__ = [
    "Confinement",
    "Element",
    "building_rows",
    "confinement_of",
    "covered",
    "details_text",
    "element_rows",
    "method_text",
    "panel_checks",
    "pier_ends",
    "polygon_area",
    "rules",
    "tie_column_positions",
]
