"""Precast piece shop drawings (alpha 9 L1): one detail per piece mark, with its elevation
(length, depth, the lifting and erection inserts with their setting-out, the corbels), its
section (hollow-core cores, double-tee stems, the profile) and the piece's data, then the
piece schedule and each mark's bar list.

What is drawn comes from elsewhere: the marks and their sections from
:mod:`saengine.design.precast`, the quantities from :mod:`saengine.boq.precast`, the bars
from the object type's reinforcement in 04 Objects. Layers ``S-CONC`` (outlines), ``S-HATCH``,
``S-REBAR-MAIN`` (bars in the section), ``S-TEXT`` (inserts and marks), ``S-DIMS``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from saengine.drawings.sheets.layout import TEXT, View, ViewSpec
from saengine.drawings.sheets.model import Table

__all__ = [
    "PrecastPieceDetail",
    "bar_table",
    "piece_detail",
    "precast_notes",
    "precast_pieces",
    "schedule_table",
]

#: Scales tried for the elevation (the first that keeps it under the width) and the section.
ELEVATION_SCALES = (20, 25, 50, 75, 100)
SECTION_SCALE = 10
MAX_WIDTH = 380.0  # paper mm of a detail


@dataclass
class PrecastPieceDetail:
    """One mark as the drawing needs it (lengths in mm)."""

    mark: str
    type: str
    element: str
    count: int
    length: float
    section: Any  # saengine.design.precast.Section
    outline: list[tuple[float, float]]  # the section's outline, x across, y up
    cores: list[tuple[float, float, float]] = field(default_factory=list)  # (x, y, diameter)
    inserts: list[tuple[float, str]] = field(default_factory=list)  # (position, label)
    corbels: list[dict[str, float | str]] = field(default_factory=list)
    bars: list[dict[str, Any]] = field(default_factory=list)  # {"mark", "count", "dia", "length"}
    cover: float | None = None
    data: list[str] = field(default_factory=list)  # the data lines beside the drawing


def _outline(obj: Any, section: Any) -> tuple[list[tuple[float, float]], list[tuple]]:
    """The section outline (centred on x) and the hollow-core cores."""
    p = obj.precast
    b, h = section.b, section.h
    if p.element == "doubleTee":
        tf = float(p.flangeThickness or 50.0)
        bw = float(p.stemWidth or 150.0)
        s = float(p.stemSpacing or b / 2)
        a, c = s / 2 - bw / 2, s / 2 + bw / 2
        pts = [
            (-b / 2, h),
            (b / 2, h),
            (b / 2, h - tf),
            (c, h - tf),
            (c, 0),
            (a, 0),
            (a, h - tf),
            (-a, h - tf),
            (-a, 0),
            (-c, 0),
            (-c, h - tf),
            (-b / 2, h - tf),
        ]
        return pts, []
    shape = getattr(getattr(obj, "profile", None), "shape", "")
    if p.element in ("beam", "column") and shape == "T":
        pr = obj.profile
        bf, tw, tf = float(pr.flangeWidth), float(pr.webThickness), float(pr.flangeThickness)
        pts = [
            (-bf / 2, h),
            (bf / 2, h),
            (bf / 2, h - tf),
            (tw / 2, h - tf),
            (tw / 2, 0),
            (-tw / 2, 0),
            (-tw / 2, h - tf),
            (-bf / 2, h - tf),
        ]
        return pts, []
    if p.element in ("beam", "column") and shape == "circle":
        r = b / 2
        return [
            (r * math.cos(t), r + r * math.sin(t))
            for t in (2 * math.pi * k / 48 for k in range(48))
        ], []
    cores: list[tuple] = []
    if p.element == "hollowCore" and p.cores and p.coreDiameter:
        n = int(p.cores)
        cores = [(-b / 2 + (k + 0.5) * b / n, h / 2, float(p.coreDiameter)) for k in range(n)]
    return [(-b / 2, 0), (b / 2, 0), (b / 2, h), (-b / 2, h)], cores


def _bars(obj: Any, length: float) -> list[dict[str, Any]]:
    """The piece's bar list: :func:`saengine.design.precast.piece_bars` (the same bars the bar
    bending schedule and BVBS take for a precast piece)."""
    from saengine.design.precast import piece_bars

    return piece_bars(obj, length)


def precast_pieces(building: Any, objects: Any, materials: Any) -> list[PrecastPieceDetail]:
    """The details of the project's precast marks (none without precast types)."""
    from saengine.design.precast import _density, piece_section, pieces_of, self_weight

    types = {o.id: o for o in getattr(objects, "objects", [])}
    out = []
    for piece in pieces_of(building, objects):
        obj = types[piece.type]
        p = obj.precast
        width = piece.height if piece.element == "wallPanel" else (piece.width or None)
        try:
            section = piece_section(obj, p, width)
        except ValueError:
            continue
        material = materials.get(obj.material) if materials is not None else None
        outline, cores = _outline(obj, section)
        weight = self_weight(section, _density(material)) * piece.length / 1e3
        volume = (section.area + section.weight_area) * piece.length * 1e-9
        concrete = getattr(material, "concrete", None)
        strip = p.stripStrength
        data = [
            f"{piece.count} No. {section.label}",
            f"Concrete {material.name if material else obj.material}"
            + (f", f'c {concrete.fc:g} MPa" if concrete else ""),
            f"Stripping strength {strip:g} MPa"
            if strip
            else "Stripping strength: per the code pack's share of f'c (see the calculations)",
            f"Volume {volume:.3f} m³, weight {weight:.1f} kN each",
            f"Lifting: {p.rigging}, slings at {p.slingAngle:g}°",
        ]
        if p.topping:
            data.append(f"Cast-in-place topping {p.topping:g} mm (not on the piece)")
        inserts = [
            (
                i.position,
                f"{'LI' if i.use != 'erection' else 'EI'} {i.name or ''} "
                f"WLL {i.workingLoad:g} kN".replace("  ", " "),
            )
            for i in p.inserts
        ]
        corbels = [
            {
                "face": c.face,
                "at": c.height,
                "projection": c.corbel.projection,
                "depth": c.corbel.depth,
                "edge": c.corbel.edgeDepth,
                "width": c.corbel.width,
            }
            for c in p.corbels
        ]
        out.append(
            PrecastPieceDetail(
                mark=piece.mark,
                type=piece.type,
                element=piece.element,
                count=piece.count,
                length=piece.length,
                section=section,
                outline=outline,
                cores=cores,
                inserts=inserts,
                corbels=corbels,
                bars=_bars(obj, piece.length),
                cover=getattr(getattr(obj, "reinforcement", None), "cover", None),
                data=data,
            )
        )
    return out


def piece_detail(d: PrecastPieceDetail) -> ViewSpec:
    """The shop drawing of one mark: elevation, section A-A and its data (paper mm, the
    elevation at the first scale of :data:`ELEVATION_SCALES` that fits)."""
    s = d.section
    se = next(
        (x for x in ELEVATION_SCALES if d.length / x <= 0.62 * MAX_WIDTH), ELEVATION_SCALES[-1]
    )
    ss = SECTION_SCALE
    proj = max((float(c["projection"]) for c in d.corbels), default=0.0)
    elev_w, elev_h = d.length / se, (s.h + 2 * proj) / se
    sec_w = s.b / ss
    while sec_w > 0.3 * MAX_WIDTH and ss < 50:
        ss *= 2
        sec_w = s.b / ss
    sec_h = s.h / ss
    data_h = 5.0 * len(d.data)
    width = 20 + elev_w + 24 + sec_w + 20
    height = max(elev_h, sec_h) + 40 + data_h

    def draw(view: View) -> None:
        base_y = data_h + 22 + max(0.0, (sec_h - elev_h) / 2)
        e = view.inset(16, base_y + proj / se, se)
        e.rect(0, 0, d.length, s.h, "S-CONC")
        for c in d.corbels:
            at = float(c["at"])
            depth, edge, pr = float(c["depth"]), float(c["edge"]), float(c["projection"])
            top = c["face"] in ("+y", "+x")
            y0 = s.h if top else 0.0
            sign = 1 if top else -1
            # a column lies with its bottom at x = 0: the corbel's bearing face at x = at
            pts = [(at, y0), (at, y0 + sign * pr), (at - edge, y0 + sign * pr), (at - depth, y0)]
            e.polyline(pts, "S-CONC", close=True)
            e.text(f"CORBEL {c['face']}", (at - depth / 2, y0 + sign * (pr + e.real(3))), TEXT)
        marks = sorted(x for x, _ in d.inserts)
        for x, label in d.inserts:
            e.circle((x, s.h), e.real(1.0), "S-TEXT")
            e.label(label, (x, s.h), [(0, 6, "BC"), (0, 10, "BC")], leader=True)
        e.dim((0, 0), (d.length, 0), -8 - (proj / se if proj else 0))
        if marks:
            e.chain([(0.0, 0.0), *[(x, 0.0) for x in marks], (d.length, 0.0)], -4)
        e.dim((0, 0), (0, s.h), 6, angle=90)
        e.text("A", (d.length / 2, s.h + e.real(14)), TEXT)
        # section A-A
        x0 = 16 + elev_w + 20 + sec_w / 2
        c = view.inset(x0, data_h + 22, ss)
        c.polyline(d.outline, "S-CONC", close=True)
        holes = [
            [
                (x + dia / 2 * math.cos(t), y + dia / 2 * math.sin(t))
                for t in (2 * math.pi * k / 24 for k in range(24))
            ]
            for x, y, dia in d.cores
        ]
        c.hatch(d.outline, holes=holes)
        for x, y, dia in d.cores:
            c.circle((x, y), dia / 2, "S-CONC")
        if d.cover:
            for bar in d.bars:
                if bar["where"] in ("bottom", "top"):
                    y = d.cover + bar["dia"] / 2 if bar["where"] == "bottom" else s.h - d.cover
                    n = int(bar["count"])
                    span = s.b - 2 * d.cover
                    for k in range(n):
                        x = -span / 2 + (span * k / (n - 1) if n > 1 else span / 2)
                        c.dot((x, y), bar["dia"] / 2)
        c.dim((-s.b / 2, 0), (s.b / 2, 0), -6)
        c.dim((s.b / 2, 0), (s.b / 2, s.h), -6, angle=90)
        c.text(f"SECTION A-A  1:{ss:g}", (0, -c.real(14)), TEXT)
        for k, line in enumerate(d.data):
            view.text(line, (16, data_h - 5.0 * k), TEXT, "ML")

    return ViewSpec(
        f"Precast piece {d.mark}",
        1,
        (0, 0, width, height),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"{d.type}, {d.element}, L = {d.length:.0f}   SCALE 1:{se:g}",
        key=f"precast:{d.mark}",
    )


def schedule_table(details: list[PrecastPieceDetail], schedule: dict[str, Any]) -> Table:
    """The piece schedule (:func:`saengine.boq.precast.piece_schedule`) as a sheet table."""
    widths = [8, 8, 10, 6, 9, 9, 9, 9, 8, 7, 8, 9]
    columns = [
        {
            "key": f"c{k}",
            "title": t.replace(" (", "\n("),
            "width": w,
            "align": "left" if k < 3 else "right",
        }
        for k, (t, w) in enumerate(zip(schedule.get("headers", []), widths, strict=False))
    ]
    return Table("Precast piece schedule", columns, [list(r) for r in schedule.get("rows", [])])


def bar_table(details: list[PrecastPieceDetail]) -> Table:
    """The bars of each mark (per piece, then for all pieces of the mark)."""
    from saengine.boq.quantities import bar_mass

    columns = [
        {"key": "piece", "title": "Piece", "width": 8, "align": "left"},
        {"key": "bar", "title": "Bar", "width": 5, "align": "left"},
        {"key": "where", "title": "Where", "width": 8, "align": "left"},
        {"key": "count", "title": "No.\nper piece", "width": 7, "align": "right"},
        {"key": "dia", "title": "Dia\n(mm)", "width": 6, "align": "right"},
        {"key": "length", "title": "Length\n(mm)", "width": 8, "align": "right"},
        {"key": "mass", "title": "Mass per\npiece (kg)", "width": 9, "align": "right"},
        {"key": "all", "title": "Mass all\n(kg)", "width": 9, "align": "right"},
    ]
    rows: list[list[str]] = []
    groups = []
    for d in details:
        first = len(rows)
        for b in d.bars:
            mass = b["count"] * bar_mass(b["dia"]) * b["length"] / 1e3
            rows.append(
                [
                    d.mark,
                    b["mark"],
                    str(b["where"]),
                    str(b["count"]),
                    f"{b['dia']:g}",
                    f"{b['length']:.0f}",
                    f"{mass:.1f}",
                    f"{mass * d.count:.1f}",
                ]
            )
        if len(rows) > first:
            groups.append({"first": first, "count": len(rows) - first})
    notes = ["Floor units and wall panels: their mesh is scheduled with the slabs and walls."]
    return Table("Precast bar list", columns, rows, groups, notes)


def precast_notes() -> list[str]:
    return [
        "Each piece is marked with its mark, its orientation and its date of casting.",
        (
            "Lift only by the inserts shown, with the rigging and sling angle stated; do not "
            "strip before the stripping strength is reached."
        ),
        "Store and transport on supports at the positions shown (else at the inserts).",
        "Brace each piece until its permanent connections are complete.",
        "Inserts: the maker's product of the working load limit shown, or equal approved.",
    ]
