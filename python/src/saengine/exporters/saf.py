"""SAF (Structural Analysis Format): the open Excel exchange of analysis models, written and read.

Alpha 9 L12. SAF is a public, vendor-neutral specification (one worksheet per object kind, one row
per object, units in the column headers). This module writes the sheets below from SAEngine's
analysis model (:mod:`saengine.exporters.analytical`) and reads them back into a new project
through the shared import builder (:func:`saengine.importers.neutral.build`), as the ``.std`` and
``.s2k`` readers do.

The sheet and column names are taken from the public SAF documentation as SAEngine understands
it; they are kept in :data:`SHEETS` so they can be corrected in one place. They are NOT verified
against a reference file or another program's reader (see ``docs/exchange.md``):

- ``StructuralMaterial``, ``StructuralCrossSection`` (parametric rectangles, circles, I, channel,
  angle, tee, box and pipe shapes with their parameters in mm, general sections by A, Iy, Iz, It),
  ``StructuralPointConnection``, ``StructuralCurveMember`` (beams, columns, braces; rotation),
  ``StructuralSurfaceMember`` (plates by their corner nodes, thickness in mm),
  ``StructuralPointSupport`` (Rigid or Free per degree of freedom), ``RelConnectsStructuralMember``
  (end releases: Free rotations at the pinned ends);
- ``StructuralLoadGroup``, ``StructuralLoadCase``, ``StructuralLoadCombination`` (case and factor
  columns), ``StructuralPointAction`` (nodal forces, kN), ``StructuralCurveAction`` (uniform member
  loads, kN/m, global directions).

Rigid diaphragms have no SAF object here: they are left out, and so are the loads on their master
nodes (the storey forces at the centres of mass), which the report lists with their size.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from saengine.exporters.analytical import AnalyticalModel, ExchangeReport, count_written

FORMAT_NAME = "SAF (.xlsx)"
EXTENSION = ".xlsx"
EXPORT_FOLDER = "SAF"

#: Sheet -> its columns, in order.
SHEETS: dict[str, tuple[str, ...]] = {
    "StructuralMaterial": (
        "Name",
        "Type",
        "Quality",
        "Unit mass [kg/m3]",
        "E modulus [MPa]",
        "G modulus [MPa]",
        "Poisson Coefficient",
        "Characteristic strength [MPa]",
        "Ultimate strength [MPa]",
    ),
    "StructuralCrossSection": (
        "Name",
        "Material",
        "Cross-section type",
        "Shape",
        "Parameters [mm]",
        "Profile",
        "A [m2]",
        "Iy [m4]",
        "Iz [m4]",
        "It [m4]",
    ),
    "StructuralPointConnection": (
        "Name",
        "Coordinate X [m]",
        "Coordinate Y [m]",
        "Coordinate Z [m]",
    ),
    "StructuralCurveMember": (
        "Name",
        "Type",
        "Cross section",
        "Nodes",
        "Segments",
        "Begin node",
        "End node",
        "Length [m]",
        "Rotation [deg]",
        "Analysis type",
    ),
    "StructuralSurfaceMember": (
        "Name",
        "Type",
        "Material",
        "Thickness type",
        "Thickness [mm]",
        "Nodes",
        "Analysis type",
    ),
    "StructuralPointSupport": ("Name", "Type", "Node", "Ux", "Uy", "Uz", "Fix", "Fiy", "Fiz"),
    "RelConnectsStructuralMember": (
        "Name",
        "Member",
        "Position",
        "Ux",
        "Uy",
        "Uz",
        "Fix",
        "Fiy",
        "Fiz",
    ),
    "StructuralLoadGroup": ("Name", "Load group type", "Relation"),
    "StructuralLoadCase": ("Name", "Description", "Action type", "Load group", "Load type"),
    "StructuralLoadCombination": ("Name", "Description", "Category", "Type"),
    "StructuralPointAction": (
        "Name",
        "Type",
        "Direction",
        "Force action",
        "Reference node",
        "Value [kN]",
        "Load case",
        "Coordinate system",
    ),
    "StructuralCurveAction": (
        "Name",
        "Type",
        "Force action",
        "Member",
        "Direction",
        "Distribution",
        "Value 1 [kN/m]",
        "Value 2 [kN/m]",
        "Load case",
        "Coordinate system",
        "Location",
    ),
}

_GROUPS = {
    "D": ("Permanent", "Permanent"),
    "SD": ("Permanent", "Permanent"),
    "L": ("Variable", "Variable"),
    "Lr": ("Variable", "Variable"),
    "W": ("Variable", "Variable"),
    "E": ("Accidental", "Variable"),
    "other": ("Variable", "Variable"),
}
_MEMBER_TYPES = {"column": "Column", "beam": "Beam", "brace": "Bracing"}
_SHAPES = {
    "rectangle": ("Rectangle", ("yDim", "xDim")),
    "circle": ("Circle", ("radius",)),
    "I": ("I", ("overallDepth", "overallWidth", "webThickness", "flangeThickness")),
    "U": ("U", ("depth", "flangeWidth", "webThickness", "flangeThickness")),
    "T": ("T", ("depth", "flangeWidth", "webThickness", "flangeThickness")),
    "L": ("L", ("depth", "width", "thickness")),
    "rectangleHollow": ("Box", ("yDim", "xDim", "wallThickness")),
    "circleHollow": ("Pipe", ("radius", "wallThickness")),
}


def _r(value: float, digits: int = 9) -> float:
    return round(float(value), digits)


def saf_rows(
    model: AnalyticalModel, report: ExchangeReport | None = None
) -> dict[str, list[list[Any]]]:
    """The rows of every sheet (without the header row), in SAF's units."""
    report = report or ExchangeReport(FORMAT_NAME, EXTENSION)
    rows: dict[str, list[list[Any]]] = {name: [] for name in SHEETS}
    for m in model.materials.values():
        kind = {"concrete": "Concrete", "steel": "Steel"}.get(m.kind, "Other")
        strength = m.fc if m.kind == "concrete" else m.fy
        rows["StructuralMaterial"].append(
            [
                m.name,
                kind,
                m.name,
                _r(m.density, 3),
                _r(m.E / 1e6, 3),
                _r(m.G / 1e6, 3),
                _r(m.nu, 4),
                _r(strength / 1e6, 3) if strength else None,
                _r(m.fu / 1e6, 3) if m.fu else None,
            ]
        )
        report.count("materials")
    for s in model.sections.values():
        if s.shape in _SHAPES:
            shape, keys = _SHAPES[s.shape]
            values = [s.dims[k] * (2 if k == "radius" else 1) * 1000 for k in keys]
            params = ";".join(f"{_r(v, 3):g}" for v in values)
            kind = "Parametric"
        else:
            shape, params, kind = "General", "", "General"
        rows["StructuralCrossSection"].append(
            [
                s.name,
                s.material,
                kind,
                shape,
                params,
                s.designation or "",
                _r(s.A),
                _r(s.I33, 12),
                _r(s.I22, 12),
                _r(s.J, 12),
            ]
        )
        report.count("sections")
    # A diaphragm's master is left out only when it is a node of its own (the centre of mass):
    # a master the analysis put on a structural node (a column top, as the steel generator does)
    # is a joint of members like any other, and the loads on it act on that joint.
    structural = {n for m in model.members for n in (m.i, m.j)}
    structural.update(n for p in model.plates for n in p.nodes)
    structural.update(n for n, node in model.nodes.items() if node.supported)
    master_nodes = {d.master for d in model.diaphragms} - structural
    used = [n for n in model.used_nodes() if n not in master_nodes]
    names = {n: f"N{n}" for n in used}
    for n in used:
        x, y, z = model.nodes[n].xyz
        rows["StructuralPointConnection"].append([names[n], _r(x), _r(y), _r(z)])
    report.count("joints", len(used))
    for m in model.members:
        rows["StructuralCurveMember"].append(
            [
                m.id,
                _MEMBER_TYPES.get(m.kind, "Beam"),
                m.section,
                f"{names[m.i]};{names[m.j]}",
                "Line",
                names[m.i],
                names[m.j],
                _r(model.length(m), 6),
                _r(m.rotation, 6),
                "Standard",
            ]
        )
        for position, released in (("Begin", m.releases[0]), ("End", m.releases[1])):
            if released:
                rows["RelConnectsStructuralMember"].append(
                    [
                        f"{m.id}-{position}",
                        m.id,
                        position,
                        *(
                            "Free" if a in released else "Rigid"
                            for a in ("P", "V2", "V3", "T", "M2", "M3")
                        ),
                    ]
                )
    for p in model.plates:
        section = model.plate_sections[p.section]
        kind = {"wall": "Wall", "slab": "Plate"}.get(section.kind, "Shell")
        rows["StructuralSurfaceMember"].append(
            [
                p.id,
                kind,
                section.material,
                "Constant",
                _r(section.thickness * 1000, 3),
                ";".join(names[n] for n in p.nodes),
                "Standard",
            ]
        )
    for n in used:
        node = model.nodes[n]
        if node.supported:
            r = node.restraint
            kind = "Fixed" if all(r) else "Hinged" if all(r[:3]) and not any(r[3:]) else "Custom"
            rows["StructuralPointSupport"].append(
                [f"Sn{n}", kind, names[n], *("Rigid" if f else "Free" for f in r)]
            )
            report.count("supports")
    if model.diaphragms:
        report.skip(
            "rigid diaphragms (no SAF object here) and the loads on their master nodes",
            model.diaphragms[0].name,
        )
    groups_written: set[str] = set()
    for c in model.cases:
        group, action = _GROUPS[c.kind]
        if group not in groups_written:
            rows["StructuralLoadGroup"].append(
                [f"LG {group}", group, "Together" if group == "Permanent" else "Standard"]
            )
            groups_written.add(group)
        rows["StructuralLoadCase"].append(
            [c.name, c.title or c.name, action, f"LG {group}", "Standard"]
        )
        k = 0
        for n, f in sorted(c.nodal.items()):
            if n in master_nodes:
                report.not_carried[c.name] += sum(v * v for v in f[:3]) ** 0.5 / 1000
                continue
            for axis, value, kind in (
                ("X", f[0], "Force"),
                ("Y", f[1], "Force"),
                ("Z", f[2], "Force"),
                ("X", f[3], "Moment"),
                ("Y", f[4], "Moment"),
                ("Z", f[5], "Moment"),
            ):
                if abs(value) > 1e-9 and n in names:
                    k += 1
                    rows["StructuralPointAction"].append(
                        [
                            f"{c.name}-P{k}",
                            kind,
                            axis,
                            "In node",
                            names[n],
                            _r(value / 1000, 6),
                            c.name,
                            "Global",
                        ]
                    )
        k = 0
        for mid, w in c.uniform.items():
            for axis, value in zip(("X", "Y", "Z"), w, strict=True):
                if abs(value) > 1e-9:
                    k += 1
                    rows["StructuralCurveAction"].append(
                        [
                            f"{c.name}-L{k}",
                            "Force",
                            "On beam",
                            mid,
                            axis,
                            "Uniform",
                            _r(value / 1000, 6),
                            _r(value / 1000, 6),
                            c.name,
                            "Global",
                            "Length",
                        ]
                    )
    for name, factors in model.combinations:
        row: list[Any] = [name, name, "ULS", "Linear add"]
        for case, factor in factors.items():
            row += [case, _r(factor, 6)]
        rows["StructuralLoadCombination"].append(row)
    count_written(report, model, diaphragms=None)
    return rows


def write_saf(
    model: AnalyticalModel, path: str | Path, report: ExchangeReport | None = None
) -> Path:
    """Writes the SAF workbook of ``model`` to ``path``."""
    from openpyxl import Workbook

    rows = saf_rows(model, report)
    book = Workbook()
    book.remove(book.active)
    widest_combination = max((len(r) for r in rows["StructuralLoadCombination"]), default=4)
    for sheet, columns in SHEETS.items():
        ws = book.create_sheet(sheet)
        header = list(columns)
        if sheet == "StructuralLoadCombination":
            for k in range(1, (widest_combination - 4) // 2 + 1):
                header += [f"Load case {k}", f"Load factor {k}"]
        ws.append(header)
        for row in rows[sheet]:
            ws.append(row)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    book.save(target)
    return target


# ─────────────────────────────────────────── import ───────────────────────────────────────────


def _sheet(book: Any, name: str) -> list[dict[str, Any]]:
    if name not in book.sheetnames:
        return []
    ws = book[name]
    values = list(ws.iter_rows(values_only=True))
    if not values:
        return []
    header = [str(h).strip() if h is not None else "" for h in values[0]]
    out = []
    for row in values[1:]:
        if row is None or all(v is None or v == "" for v in row):
            continue
        record = {header[k]: row[k] for k in range(min(len(header), len(row))) if header[k]}
        # Combinations: the unnamed trailing case/factor pairs keep their order.
        record["_row"] = list(row)
        out.append(record)
    return out


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_saf(path: str | Path) -> bool:
    """Whether the workbook at ``path`` is a SAF file (it has the point connections sheet)."""
    try:
        from openpyxl import load_workbook

        book = load_workbook(str(path), read_only=True)
        try:
            return "StructuralPointConnection" in book.sheetnames
        finally:
            book.close()
    except Exception:  # noqa: BLE001 - not a workbook we can read
        return False


def read_saf(path: str | Path) -> Any:
    """The :class:`saengine.importers.neutral.TextModel` of a SAF workbook (mm, N, MPa)."""
    import numpy as np
    from openpyxl import load_workbook

    from saengine.importers.common import ImportReport
    from saengine.importers.neutral import (
        Area,
        Frame,
        Load,
        LoadCase,
        MaterialDef,
        SectionDef,
        TextModel,
        circle_profile,
        equivalent_rectangle,
        rectangle,
    )
    from saengine.library import objects as o

    path = Path(path)
    book = load_workbook(str(path), read_only=True, data_only=True)
    try:
        sheets = {name: _sheet(book, name) for name in book.sheetnames}
    finally:
        book.close()
    model = TextModel(format="SAF", file=path.name, report=ImportReport("SAF", path.name))
    report = model.report
    model.units = "kN, m (SAF)"
    known = set(SHEETS)
    for name, records in sheets.items():
        if name not in known and records:
            report.skip("sheets not read", f"{name} ({len(records)})")
    for r in sheets.get("StructuralMaterial", []):
        name = str(r.get("Name") or "")
        if not name:
            continue
        kind = str(r.get("Type") or "").lower()
        strength = _num(r.get("Characteristic strength [MPa]"), 0.0) or None
        model.materials[name] = MaterialDef(
            name=name,
            E=_num(r.get("E modulus [MPa]"), 0.0) or None,
            nu=_num(r.get("Poisson Coefficient"), 0.0) or None,
            density=_num(r.get("Unit mass [kg/m3]"), 0.0) or None,
            kind="steel"
            if kind.startswith("steel")
            else "concrete"
            if kind.startswith("concrete")
            else None,
            fc=strength if kind.startswith("concrete") else None,
            fy=strength if kind.startswith("steel") else None,
            fu=_num(r.get("Ultimate strength [MPa]"), 0.0) or None,
        )
    for r in sheets.get("StructuralCrossSection", []):
        name = str(r.get("Name") or "")
        if not name:
            continue
        shape = str(r.get("Shape") or "").lower()
        params = [
            _num(v)
            for v in str(r.get("Parameters [mm]") or "").replace(",", ".").split(";")
            if v.strip()
        ]
        profile, approximation = None, None
        try:
            if shape == "rectangle" and len(params) >= 2:
                profile = rectangle(params[1], params[0])
            elif shape == "circle" and params:
                profile = circle_profile(params[0] / 2)
            elif shape == "i" and len(params) >= 4:
                profile = o.IShapeProfile(
                    overallDepth=params[0],
                    overallWidth=params[1],
                    webThickness=params[2],
                    flangeThickness=params[3],
                )
            elif shape == "u" and len(params) >= 4:
                profile = o.UShapeProfile(
                    depth=params[0],
                    flangeWidth=params[1],
                    webThickness=params[2],
                    flangeThickness=params[3],
                )
            elif shape == "t" and len(params) >= 4:
                profile = o.TShapeProfile(
                    depth=params[0],
                    flangeWidth=params[1],
                    webThickness=params[2],
                    flangeThickness=params[3],
                )
            elif shape == "l" and len(params) >= 3:
                profile = o.LShapeProfile(depth=params[0], width=params[1], thickness=params[2])
            elif shape == "box" and len(params) >= 3:
                profile = o.RectangleHollowProfile(
                    yDim=params[0], xDim=params[1], wallThickness=params[2]
                )
            elif shape == "pipe" and len(params) >= 2:
                profile = o.CircleHollowProfile(radius=params[0] / 2, wallThickness=params[1])
            else:
                profile = equivalent_rectangle(
                    _num(r.get("A [m2]")) * 1e6, _num(r.get("Iy [m4]")) * 1e12
                )
                approximation = (
                    "given by their properties (general sections): a rectangle of the same area "
                    "and major inertia (minor inertia and torsion differ)"
                )
        except ValueError:
            profile = None
        if profile is None:
            report.skip("cross-sections that could not be read", f"{name} ({r.get('Shape')})")
            continue
        model.sections[name] = SectionDef(
            name,
            profile,
            material=str(r.get("Material") or "") or None,
            approximation=approximation,
        )
    joints = {}
    for r in sheets.get("StructuralPointConnection", []):
        name = str(r.get("Name") or "")
        if name:
            joints[name] = (
                np.array([_num(r.get(f"Coordinate {a} [m]")) for a in ("X", "Y", "Z")], dtype=float)
                * 1000
            )
    model.joints.update(joints)
    for r in sheets.get("StructuralCurveMember", []):
        name = str(r.get("Name") or "")
        i, j = str(r.get("Begin node") or ""), str(r.get("End node") or "")
        if not (name and i and j):
            nodes = str(r.get("Nodes") or "").split(";")
            if len(nodes) >= 2:
                i, j = nodes[0].strip(), nodes[-1].strip()
                if len(nodes) > 2:
                    report.approximate(
                        "curve members of several segments taken straight end to end", name
                    )
        if not (name and i and j):
            continue
        model.frames.append(
            Frame(
                name,
                i,
                j,
                str(r.get("Cross section") or "") or None,
                rotation=_num(r.get("Rotation [deg]")),
            )
        )
    frames = {f.id: f for f in model.frames}
    for r in sheets.get("RelConnectsStructuralMember", []):
        f = frames.get(str(r.get("Member") or ""))
        if f is None:
            continue
        names = ("P", "V2", "V3", "T", "M2", "M3")
        free = frozenset(
            n
            for n, key in zip(names, ("Ux", "Uy", "Uz", "Fix", "Fiy", "Fiz"), strict=True)
            if str(r.get(key) or "").lower() == "free"
        )
        at_end = str(r.get("Position") or "").lower().startswith("end")
        f.releases = (f.releases[0], free) if at_end else (free, f.releases[1])
    for r in sheets.get("StructuralSurfaceMember", []):
        name = str(r.get("Name") or "")
        nodes = [n.strip() for n in str(r.get("Nodes") or "").split(";") if n.strip()]
        if not name or len(nodes) < 3:
            continue
        thickness = _num(r.get("Thickness [mm]"))
        section = f"{r.get('Material') or 'PL'} {thickness:g}"
        model.area_sections.setdefault(
            section,
            SectionDef(section, thickness=thickness, material=str(r.get("Material") or "") or None),
        )
        model.areas.append(Area(name, nodes, section))
    for r in sheets.get("StructuralPointSupport", []):
        node = str(r.get("Node") or "")
        if node:
            model.supports[node] = tuple(
                str(r.get(k) or "").lower() == "rigid"
                for k in ("Ux", "Uy", "Uz", "Fix", "Fiy", "Fiz")
            )
    kinds = {"permanent": "D", "variable": "L", "accidental": "other"}
    for r in sheets.get("StructuralLoadCase", []):
        name = str(r.get("Name") or "")
        if not name:
            continue
        upper = name.upper()
        kind = (
            "D"
            if upper in ("D", "DL", "DEAD")
            else "SD"
            if upper in ("SD", "SDL")
            else "Lr"
            if upper in ("LR", "RL")
            else "L"
            if upper in ("L", "LL", "LIVE")
            else "W"
            if upper.startswith("W")
            else "E"
            if upper.startswith("E")
            else kinds.get(str(r.get("Action type") or "").lower(), "other")
        )
        model.cases[name] = LoadCase(name=name, kind=kind)
    for r in sheets.get("StructuralPointAction", []):
        case = model.cases.get(str(r.get("Load case") or ""))
        node = str(r.get("Reference node") or "")
        if case is None or node not in joints:
            continue
        if str(r.get("Type") or "Force").lower() != "force":
            report.note("loads.joint.moments", f"{case.name}: {node}")
            continue
        v = np.zeros(3)
        axis = {"X": 0, "Y": 1, "Z": 2}.get(str(r.get("Direction") or "").upper())
        if axis is None:
            continue
        v[axis] = _num(r.get("Value [kN]")) * 1000
        case.loads.append(Load("joint", node, v))
    for r in sheets.get("StructuralCurveAction", []):
        case = model.cases.get(str(r.get("Load case") or ""))
        member = str(r.get("Member") or "")
        if case is None or member not in frames:
            continue
        axis = {"X": 0, "Y": 1, "Z": 2}.get(str(r.get("Direction") or "").upper())
        if axis is None or str(r.get("Coordinate system") or "Global").lower() != "global":
            report.note("loads.member.direction", f"{case.name}: {member}")
            continue
        v = np.zeros(3)
        v[axis] = (_num(r.get("Value 1 [kN/m]")) + _num(r.get("Value 2 [kN/m]"))) / 2 * 1000
        if abs(_num(r.get("Value 1 [kN/m]")) - _num(r.get("Value 2 [kN/m]"))) > 1e-9:
            report.note("loads.member.varying", f"{case.name}: {member}")
        case.loads.append(Load("uniform", member, v))
    header = SHEETS["StructuralLoadCombination"]
    for r in sheets.get("StructuralLoadCombination", []):
        name = str(r.get("Name") or "")
        row = r.get("_row") or []
        factors: dict[str, float] = {}
        for k in range(len(header), len(row) - 1, 2):
            case_name, factor = row[k], row[k + 1]
            if case_name and str(case_name) in model.cases:
                factors[str(case_name)] = factors.get(str(case_name), 0.0) + _num(factor)
        if name and factors:
            model.combinations.append((name, factors))
    return model


def import_saf(path: str | Path, name: str | None = None) -> Any:
    """The SAEngine project parts of the SAF workbook at ``path``, with its report."""
    from saengine.importers.neutral import build

    return build(read_saf(path), name)


__all__ = [
    "EXPORT_FOLDER",
    "EXTENSION",
    "FORMAT_NAME",
    "SHEETS",
    "import_saf",
    "is_saf",
    "read_saf",
    "saf_rows",
    "write_saf",
]
