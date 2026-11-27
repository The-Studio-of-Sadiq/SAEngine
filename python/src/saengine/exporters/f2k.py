"""The analysis model as a SAFE ``.f2k`` text file (v20+ database tables as text:
``TABLE:  "NAME"`` followed by records of ``Key=Value`` pairs), units kN, m, °C.

Alpha 9 L12. Written from the format's public description and public SAFE v20/v23 sample
files, kept to the tables and fields SAEngine's own ``.f2k`` reader understands
(:mod:`saengine.importers.safe`), so an export reads back into SAEngine; the target program's
acceptance of every field is NOT verified (no copy of SAFE is run or read here; see
``docs/exchange.md``).

In particular, public SAFE v20/v23 samples contain no frame or wall connectivity tables; the
tables written here for frames, walls and their loads (``COLUMN OBJECT CONNECTIVITY``, ``BEAM
OBJECT CONNECTIVITY``, ``WALL OBJECT CONNECTIVITY``, ``FRAME ASSIGNMENTS - LOCAL AXES``,
``FRAME ASSIGNMENTS - RELEASES``, ``FRAME LOAD ASSIGNMENTS - DISTRIBUTED``, ``FRAME LOAD
ASSIGNMENTS - POINT``, and ``JOINT LOAD ASSIGNMENTS - FORCE``) are UNVERIFIED and written by
analogy with ETABS database tables.

The frames are the members, not the analysis mesh's segments
(:func:`saengine.exporters.analytical.joined_members`). Design strips (``STRIP OBJECT
CONNECTIVITY``) are generated along the X and Y grid lines across each floor slab's bounding
box with half-spacing tributary widths.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from saengine.exporters.analytical import (
    AnalyticalModel,
    ExchangeReport,
    Member,
    Plate,
    count_written,
    joined_members,
)
from saengine.exporters.s2k import _PATTERN_TYPES, _record, _yes

FORMAT_NAME = "SAFE text (.f2k)"
EXTENSION = ".f2k"
#: The folder of ``11 Exports`` the app writes it to.
EXPORT_FOLDER = "F2K"

_SHAPE_LABELS = {
    "rectangle": "Concrete Rectangular",
    "circle": "Concrete Circle",
    "I": "Steel I/Wide Flange",
}


def _is_floor(plate: Plate, model: AnalyticalModel) -> bool:
    ps = model.plate_sections.get(plate.section)
    if ps is not None and ps.kind == "slab":
        return True
    if ps is not None and ps.kind == "wall":
        return False
    zs = [model.nodes[n].xyz[2] for n in plate.nodes if n in model.nodes]
    return bool(zs) and (max(zs) - min(zs)) <= 1e-3


def _load_norm(values: list[float]) -> float:
    return math.sqrt(sum(v * v for v in values[:3]))


def _design_strips(
    model: AnalyticalModel,
    floors: list[Plate],
    next_point_id: int,
) -> tuple[list[tuple[int, float, float, float]], list[dict[str, Any]]]:
    """Generate Layer A (along X, for Y grids) and Layer B (along Y, for X grids) design strips
    per floor level where floor plates and grids exist. Returns (extra_points, strip_rows)."""
    if not floors or not model.grids:
        return [], []
    by_level: dict[float, list[Plate]] = defaultdict(list)
    for p in floors:
        zs = [model.nodes[n].xyz[2] for n in p.nodes if n in model.nodes]
        if zs:
            by_level[round(sum(zs) / len(zs), 3)].append(p)

    all_x = sorted({round(coord, 6) for axis, _, coord in model.grids if axis.upper() == "X"})
    all_y = sorted({round(coord, 6) for axis, _, coord in model.grids if axis.upper() == "Y"})
    extra_points: list[tuple[int, float, float, float]] = []
    strips: list[dict[str, Any]] = []
    pid = next_point_id
    a_idx, b_idx = 1, 1

    for z_level in sorted(by_level):
        pts = [model.nodes[n].xyz for p in by_level[z_level] for n in p.nodes if n in model.nodes]
        if not pts:
            continue
        xmin = min(pt[0] for pt in pts)
        xmax = max(pt[0] for pt in pts)
        ymin = min(pt[1] for pt in pts)
        ymax = max(pt[1] for pt in pts)
        z = sum(pt[2] for pt in pts) / len(pts)

        if xmax - xmin > 1e-6:
            ys = [y for y in all_y if ymin - 1e-6 <= y <= ymax + 1e-6]
            for i, y in enumerate(ys):
                w_left = 0.5 * (ys[i + 1] - y) if i + 1 < len(ys) else max(0.0, ymax - y)
                w_right = 0.5 * (y - ys[i - 1]) if i > 0 else max(0.0, y - ymin)
                p1, p2 = pid, pid + 1
                pid += 2
                extra_points.extend([(p1, xmin, y, z), (p2, xmax, y, z)])
                strips.append(
                    {
                        "Name": f"CSA{a_idx}",
                        "Number Segments": 1,
                        "Strip Start Point": str(p1),
                        "Segment End Point": str(p2),
                        "Start Width Left": w_left,
                        "Start Width Right": w_right,
                        "End Width Left": w_left,
                        "End Width Right": w_right,
                        "Auto Widen": "No",
                        "Layer": "A",
                    }
                )
                a_idx += 1

        if ymax - ymin > 1e-6:
            xs = [x for x in all_x if xmin - 1e-6 <= x <= xmax + 1e-6]
            for i, x in enumerate(xs):
                w_left = 0.5 * (x - xs[i - 1]) if i > 0 else max(0.0, x - xmin)
                w_right = 0.5 * (xs[i + 1] - x) if i + 1 < len(xs) else max(0.0, xmax - x)
                p1, p2 = pid, pid + 1
                pid += 2
                extra_points.extend([(p1, x, ymin, z), (p2, x, ymax, z)])
                strips.append(
                    {
                        "Name": f"CSB{b_idx}",
                        "Number Segments": 1,
                        "Strip Start Point": str(p1),
                        "Segment End Point": str(p2),
                        "Start Width Left": w_left,
                        "Start Width Right": w_right,
                        "End Width Left": w_left,
                        "End Width Right": w_right,
                        "Auto Widen": "No",
                        "Layer": "B",
                    }
                )
                b_idx += 1

    return extra_points, strips


def write_f2k(model: AnalyticalModel, report: ExchangeReport | None = None) -> str:
    """The ``.f2k`` text of ``model`` (SAFE v20+ dialect, kN, m, °C)."""
    report = report or ExchangeReport(FORMAT_NAME, EXTENSION)
    model = joined_members(model, report)
    count_written(report, model, members=False, diaphragms=False, masses=False)
    if model.modes:
        report.skip("modal analysis case (not in this format)", None)

    kn = 1 / 1000
    out: list[str] = [
        f"File {model.name}.f2k was written by SAEngine (alpha 9 exchange export)",
        "",
    ]

    def table(name: str, rows: list[str]) -> None:
        if rows:
            out.extend([f'TABLE:  "{name}"', *rows, ""])

    # Partition members (columns, beams; braces are left out) and plates (floors, walls).
    columns: list[Member] = []
    beams: list[Member] = []
    skipped_members: set[str] = set()
    for m in model.members:
        if m.kind == "column":
            columns.append(m)
            report.count("columns")
        elif m.kind == "beam":
            beams.append(m)
            report.count("beams")
        else:
            skipped_members.add(m.id)
            report.skip("braces (not in SAFE .f2k)", m.id)

    written_members = [m for m in model.members if m.id not in skipped_members]
    written_member_ids = {m.id for m in written_members}
    floors: list[Plate] = []
    walls: list[Plate] = []
    for p in model.plates:
        if _is_floor(p, model):
            floors.append(p)
        else:
            walls.append(p)
    if model.plates:
        report.count("plates", len(model.plates))

    # Nodes actually used by written geometry or supports (exclude orphan diaphragm masters
    # and nodes only referenced by skipped braces).
    structural_nodes: set[int] = set()
    for m in written_members:
        structural_nodes.update((m.i, m.j))
    for p in model.plates:
        structural_nodes.update(p.nodes)
    for n in model.nodes.values():
        if n.supported:
            structural_nodes.add(n.id)
    diaphragm_masters = {d.master for d in model.diaphragms}
    for c in model.cases:
        for n in c.nodal:
            if n in model.nodes and n not in diaphragm_masters:
                structural_nodes.add(n)
    written_nodes = sorted(n for n in structural_nodes if n in model.nodes)
    written_node_set = set(written_nodes)

    table(
        "PROGRAM CONTROL",
        [
            _record(
                {
                    "ProgramName": "SAFE",
                    "Version": "23.1.0",
                    "ProgLevel": "Standard",
                    "CurrUnits": "KN, m, C",
                    "ModelName": model.name,
                }
            )
        ],
    )

    if model.grids:
        table(
            "GRID DEFINITIONS - GRID LINES",
            [
                _record(
                    {
                        "Name": "G1",
                        "Grid Line Type": f"{axis.upper()} (Cartesian)",
                        "ID": label,
                        "Ordinate": coord,
                        "Visible": "Yes",
                    }
                )
                for axis, label, coord in model.grids
            ],
        )

    # ── materials ──
    mat_general, mat_mech, mat_steel, mat_concrete = [], [], [], []
    for m in model.materials.values():
        kind = {"concrete": "Concrete", "steel": "Steel"}.get(m.kind, "Other")
        mat_general.append(_record(Material=m.name, Type=kind, SymType="Isotropic"))
        mat_mech.append(
            _record(
                Material=m.name,
                DensityType="Weight",
                UnitWeight=m.unit_weight * kn,
                UnitMass=m.density * kn,
                E1=m.E * kn,
                G12=m.G * kn,
                U12=m.nu,
            )
        )
        if m.kind == "steel" and m.fy:
            mat_steel.append(_record(Material=m.name, Fy=m.fy * kn, Fu=(m.fu or m.fy) * kn))
        if m.kind == "concrete" and m.fc:
            mat_concrete.append(_record(Material=m.name, Fc=m.fc * kn))
        report.count("materials")
    table("MATERIAL PROPERTIES - GENERAL", mat_general)
    table("MATERIAL PROPERTIES - BASIC MECHANICAL PROPERTIES", mat_mech)
    table("MATERIAL PROPERTIES - STEEL DATA", mat_steel)
    table("MATERIAL PROPERTIES - CONCRETE DATA", mat_concrete)

    # ── frame sections ──
    sec_kind: dict[str, str] = {}
    for m in written_members:
        sec_kind.setdefault(m.section, "Column" if m.kind == "column" else "Beam")
    rect_rows, circ_rows, steel_i_rows, gen_rows = [], [], [], []
    used_sections = {m.section for m in written_members}
    for s in model.sections.values():
        if written_members and s.name not in used_sections:
            continue
        d = s.dims
        if s.shape == "rectangle":
            rect_rows.append(
                _record(
                    {
                        "Name": s.name,
                        "Material": s.material,
                        "Depth": d["yDim"],
                        "Width": d["xDim"],
                        "Section Type": sec_kind.get(s.name, "Beam"),
                    }
                )
            )
        elif s.shape == "circle":
            circ_rows.append(
                _record(
                    {
                        "Name": s.name,
                        "Material": s.material,
                        "Diameter": 2 * d["radius"],
                        "Section Type": sec_kind.get(s.name, "Column"),
                    }
                )
            )
        elif s.shape == "I":
            steel_i_rows.append(
                _record(
                    {
                        "Name": s.name,
                        "Material": s.material,
                        "Total Depth": d["overallDepth"],
                        "Top Flange Width": d["overallWidth"],
                        "Top Flange Thickness": d["flangeThickness"],
                        "Web Thickness": d["webThickness"],
                        "Bottom Flange Width": d["overallWidth"],
                        "Bottom Flange Thickness": d["flangeThickness"],
                    }
                )
            )
        else:
            gen_rows.append(
                _record(
                    {
                        "Name": s.name,
                        "Material": s.material,
                        "Area": s.A,
                        "TorsConst": s.J,
                        "I33": s.I33,
                        "I22": s.I22,
                    }
                )
            )
            if s.shape != "general":
                report.approximate(
                    "other frame section shapes written by properties (GENERAL)", s.name
                )
        report.count("sections")
    table("FRAME SECTION PROPERTY DEFINITIONS - CONCRETE RECTANGULAR", rect_rows)
    table("FRAME SECTION PROPERTY DEFINITIONS - CONCRETE CIRCLE", circ_rows)
    table("FRAME SECTION PROPERTY DEFINITIONS - STEEL I/WIDE FLANGE", steel_i_rows)
    table("FRAME SECTION PROPERTY DEFINITIONS - GENERAL", gen_rows)

    # ── slab & wall properties ──
    floor_sec_names = {p.section for p in floors}
    wall_sec_names = {p.section for p in walls}
    slab_props, wall_props = [], []
    for ps in model.plate_sections.values():
        is_slab = ps.name in floor_sec_names or (
            ps.name not in wall_sec_names and ps.kind != "wall"
        )
        if is_slab:
            slab_props.append(
                _record(
                    {
                        "Name": ps.name,
                        "Modeling Type": "Shell-Thick",
                        "Property Type": "Slab",
                        "Material": ps.material,
                        "Slab Thickness": ps.thickness,
                    }
                )
            )
        else:
            wall_props.append(
                _record(
                    {
                        "Name": ps.name,
                        "Modeling Type": "Shell-Thin",
                        "Material": ps.material,
                        "Wall Thickness": ps.thickness,
                    }
                )
            )
    table("SLAB PROPERTY DEFINITIONS", slab_props)
    table("WALL PROPERTY DEFINITIONS - SPECIFIED", wall_props)

    # ── design strips & points ──
    next_pt = max(model.nodes, default=0) + 1
    strip_points, strip_records = _design_strips(model, floors, next_pt)

    point_rows = [
        _record(
            {
                "UniqueName": str(n),
                "Is Auto Point": "No",
                "IsSpecial": "No",
                "X": model.nodes[n].xyz[0],
                "Y": model.nodes[n].xyz[1],
                "Z": model.nodes[n].xyz[2],
            }
        )
        for n in written_nodes
    ] + [
        _record(
            {
                "UniqueName": str(pid),
                "Is Auto Point": "No",
                "IsSpecial": "Yes",
                "X": x,
                "Y": y,
                "Z": z,
            }
        )
        for pid, x, y, z in strip_points
    ]
    table("POINT OBJECT CONNECTIVITY", point_rows)
    report.count("joints", len(written_nodes))

    # ── objects ──
    table(
        "COLUMN OBJECT CONNECTIVITY",
        [
            _record({"UniqueName": m.id, "UniquePtI": str(m.i), "UniquePtJ": str(m.j)})
            for m in columns
        ],
    )
    table(
        "BEAM OBJECT CONNECTIVITY",
        [
            _record({"UniqueName": m.id, "UniquePtI": str(m.i), "UniquePtJ": str(m.j)})
            for m in beams
        ],
    )
    table(
        "FLOOR OBJECT CONNECTIVITY",
        [
            _record(
                {
                    "Unique Name": p.id,
                    **{f"UniquePt{k}": str(n) for k, n in enumerate(p.nodes, start=1)},
                }
            )
            for p in floors
        ],
    )
    table(
        "WALL OBJECT CONNECTIVITY",
        [
            _record(
                {
                    "Unique Name": p.id,
                    **{f"UniquePt{k}": str(n) for k, n in enumerate(p.nodes, start=1)},
                }
            )
            for p in walls
        ],
    )
    if strip_records:
        table("STRIP OBJECT CONNECTIVITY", [_record(r) for r in strip_records])
        report.count("designStrips", len(strip_records))

    table(
        "FRAME ASSIGNMENTS - SECTION PROPERTIES",
        [
            _record(
                {
                    "UniqueName": m.id,
                    "Shape": _SHAPE_LABELS.get(model.sections[m.section].shape, "General"),
                    "Auto Select List": "N.A.",
                    "Section Property": m.section,
                }
            )
            for m in written_members
        ],
    )
    angles = []
    for m in written_members:
        angle = (m.rotation + (90.0 if m.kind == "column" else 0.0)) % 360.0
        if abs(angle) > 1e-9:
            angles.append(_record({"UniqueName": m.id, "Angle": angle}))
    table("FRAME ASSIGNMENTS - LOCAL AXES", angles)

    rel_names = ("P", "V2", "V3", "T", "M2", "M3")
    releases = []
    for m in written_members:
        if m.releases[0] or m.releases[1]:
            fields: dict[str, Any] = {"UniqueName": m.id}
            fields.update({f"{n}I": _yes(n in m.releases[0]) for n in rel_names})
            fields.update({f"{n}J": _yes(n in m.releases[1]) for n in rel_names})
            fields["PartialFix"] = "No"
            releases.append(_record(fields))
            report.count("releasedEnds", bool(m.releases[0]) + bool(m.releases[1]))
    table("FRAME ASSIGNMENTS - RELEASES", releases)

    area_assigns = [
        _record({"UniqueName": p.id, "Section Property": p.section, "Property Type": "Slab"})
        for p in floors
    ] + [
        _record({"UniqueName": p.id, "Section Property": p.section, "Property Type": "Wall"})
        for p in walls
    ]
    table("AREA ASSIGNMENTS - SECTION PROPERTIES", area_assigns)

    table(
        "JOINT ASSIGNMENTS - RESTRAINTS",
        [
            _record(
                {
                    "UniqueName": str(n),
                    **{
                        k: _yes(f)
                        for k, f in zip(
                            ("UX", "UY", "UZ", "RX", "RY", "RZ"),
                            model.nodes[n].restraint,
                            strict=True,
                        )
                    },
                }
            )
            for n in written_nodes
            if model.nodes[n].supported
        ],
    )

    # ── loads ──
    table(
        "LOAD PATTERN DEFINITIONS",
        [
            _record(
                {
                    "Name": c.name,
                    "Is Auto Load": "No",
                    "Type": _PATTERN_TYPES[c.kind],
                    "Self Weight Multiplier": 0,
                }
            )
            for c in model.cases
        ],
    )
    table(
        "LOAD CASE DEFINITIONS - LINEAR STATIC",
        [
            _record(
                {
                    "Name": c.name,
                    "Initial Condition": "Unstressed",
                    "Load Type": "Load",
                    "Load Name": c.name,
                    "Load SF": 1,
                }
            )
            for c in model.cases
        ],
    )

    joint_loads: list[str] = []
    frame_loads: list[str] = []
    point_loads: list[str] = []
    members_by_id = {m.id: m for m in model.members}
    for c in model.cases:
        for n, f in sorted(c.nodal.items()):
            if not any(abs(v) > 1e-9 for v in f):
                continue
            if n not in written_node_set:
                report.skip("joint loads on nodes not exported", f"{c.name}: {n}")
                report.not_carried[c.name] += _load_norm(f) * kn
                continue
            joint_loads.append(
                _record(
                    {
                        "UniqueName": str(n),
                        "Load Pattern": c.name,
                        "FX": f[0] * kn,
                        "FY": f[1] * kn,
                        "FZ": f[2] * kn,
                        "MX": f[3] * kn,
                        "MY": f[4] * kn,
                        "MZ": f[5] * kn,
                    }
                )
            )
        for mid, w in c.uniform.items():
            if mid not in written_member_ids:
                m_obj = members_by_id.get(mid)
                length = model.length(m_obj) if m_obj else 0.0
                report.skip("member loads on braces (not in SAFE .f2k)", f"{c.name}: {mid}")
                report.not_carried[c.name] += _load_norm(w) * length * kn
                continue
            for axis, value in zip(("X", "Y", "Z"), w, strict=True):
                if abs(value) > 1e-9:
                    frame_loads.append(
                        _record(
                            {
                                "UniqueName": mid,
                                "Load Pattern": c.name,
                                "Direction": axis,
                                "Distribution Type": "Relative",
                                "Relative Distance A": 0,
                                "Relative Distance B": 1,
                                "Load A": value * kn,
                                "Load B": value * kn,
                            }
                        )
                    )
        for mid, runs in c.partial.items():
            if mid not in written_member_ids:
                for w, a, b in runs:
                    report.skip("member loads on braces (not in SAFE .f2k)", f"{c.name}: {mid}")
                    report.not_carried[c.name] += _load_norm(w) * abs(b - a) * kn
                continue
            for w, a, b in runs:
                for axis, value in zip(("X", "Y", "Z"), w, strict=True):
                    if abs(value) > 1e-9:
                        frame_loads.append(
                            _record(
                                {
                                    "UniqueName": mid,
                                    "Load Pattern": c.name,
                                    "Direction": axis,
                                    "Distribution Type": "Absolute",
                                    "Absolute Distance A": a,
                                    "Absolute Distance B": b,
                                    "Load A": value * kn,
                                    "Load B": value * kn,
                                }
                            )
                        )
        for mid, forces in c.points.items():
            if mid not in written_member_ids:
                for f, _ in forces:
                    report.skip("member loads on braces (not in SAFE .f2k)", f"{c.name}: {mid}")
                    report.not_carried[c.name] += _load_norm(f) * kn
                continue
            for f, at in forces:
                for axis, value in zip(("X", "Y", "Z"), f[:3], strict=True):
                    if abs(value) > 1e-9:
                        point_loads.append(
                            _record(
                                {
                                    "UniqueName": mid,
                                    "Load Pattern": c.name,
                                    "Direction": axis,
                                    "Absolute Distance": at,
                                    "Load": value * kn,
                                }
                            )
                        )
    table("JOINT LOAD ASSIGNMENTS - FORCE", joint_loads)
    table("FRAME LOAD ASSIGNMENTS - DISTRIBUTED", frame_loads)
    table("FRAME LOAD ASSIGNMENTS - POINT", point_loads)
    report.count("memberPointLoads", len(point_loads))
    report.count("jointLoads", len(joint_loads))
    report.count("memberLoads", len(frame_loads))

    combos = []
    for name, factors in model.combinations:
        first = True
        for case, factor in factors.items():
            combos.append(
                _record(
                    {
                        "Name": name,
                        "Type": "Linear Add" if first else None,
                        "Is Auto": "No" if first else None,
                        "Load Name": case,
                        "SF": factor,
                    }
                )
            )
            first = False
    table("LOAD COMBINATION DEFINITIONS", combos)
    out.append("END TABLE DATA")
    return "\n".join(out) + "\n"


__all__ = ["EXPORT_FOLDER", "EXTENSION", "FORMAT_NAME", "write_f2k"]
