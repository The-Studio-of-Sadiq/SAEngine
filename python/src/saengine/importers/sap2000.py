"""Import of a SAP2000 text file (``.s2k``, the database tables exported as text) into a SAEngine
project.

The file is a sequence of tables, each a ``TABLE:  "NAME"`` line followed by records of
``Key=Value`` pairs (a value with spaces in quotes, a record continued on the next line by a
trailing ``_``). The reader uses:

- ``PROGRAM CONTROL`` (``CurrUnits``, e.g. ``"KN, m, C"``) for the units of every table;
- ``JOINT COORDINATES``, ``CONNECTIVITY - FRAME``, ``CONNECTIVITY - AREA``;
- ``FRAME SECTION ASSIGNMENTS``, ``FRAME SECTION PROPERTIES 01 - GENERAL`` (rectangular,
  circular, I/wide flange, box/tube, pipe, channel, angle and tee shapes from their dimensions;
  general sections as a rectangle of the same area and major inertia),
  ``FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL``;
- ``AREA SECTION ASSIGNMENTS``, ``AREA SECTION PROPERTIES`` (the thickness);
- ``MATERIAL PROPERTIES 01 - GENERAL`` (the type), ``02 - BASIC MECHANICAL PROPERTIES``
  (unit weight, E, Poisson), ``03A - STEEL DATA`` (Fy, Fu), ``03B - CONCRETE DATA`` (Fc);
- ``JOINT RESTRAINT ASSIGNMENTS``;
- ``LOAD PATTERN DEFINITIONS`` (design type, self-weight multiplier), ``LOAD CASE
  DEFINITIONS`` with ``CASE - STATIC 1 - LOAD ASSIGNMENTS`` (cases made of patterns);
- ``FRAME LOADS - DISTRIBUTED`` (mean of the two ends over the loaded length), ``FRAME LOADS -
  POINT``, ``JOINT LOADS - FORCE``, ``AREA LOADS - UNIFORM`` and ``- UNIFORM TO FRAME``;
- ``COMBINATION DEFINITIONS`` (linear additive, combinations of combinations expanded).

Other tables are skipped and listed in the import report.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from saengine.importers.common import ImportedProject, ImportReport, Units
from saengine.importers.neutral import (
    Area,
    FileUnits,
    Frame,
    Load,
    LoadCase,
    MaterialDef,
    SectionDef,
    TextModel,
    build,
    circle_profile,
    equivalent_rectangle,
    named_profile,
    rectangle,
)
from saengine.library import objects as o

FORMAT = "SAP2000"

_RECORD = re.compile(r'([^\s=]+)=("[^"]*"|\S*)')

#: Tables the reader uses (others are listed as skipped).
_USED = {
    "PROGRAM CONTROL",
    "JOINT COORDINATES",
    "CONNECTIVITY - FRAME",
    "CONNECTIVITY - AREA",
    "FRAME SECTION ASSIGNMENTS",
    "FRAME SECTION PROPERTIES 01 - GENERAL",
    "FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL",
    "AREA SECTION ASSIGNMENTS",
    "AREA SECTION PROPERTIES",
    "MATERIAL PROPERTIES 01 - GENERAL",
    "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES",
    "MATERIAL PROPERTIES 03A - STEEL DATA",
    "MATERIAL PROPERTIES 03B - CONCRETE DATA",
    "JOINT RESTRAINT ASSIGNMENTS",
    "LOAD PATTERN DEFINITIONS",
    "LOAD CASE DEFINITIONS",
    "CASE - STATIC 1 - LOAD ASSIGNMENTS",
    "FRAME LOADS - DISTRIBUTED",
    "FRAME LOADS - POINT",
    "JOINT LOADS - FORCE",
    "AREA LOADS - UNIFORM",
    "AREA LOADS - UNIFORM TO FRAME",
    "COMBINATION DEFINITIONS",
}
#: Tables that only hold what SAEngine derives or does not need: not reported as skipped.
_QUIET = re.compile(
    r"^(ACTIVE DEGREES OF FREEDOM|ANALYSIS OPTIONS|COORDINATE SYSTEMS|GRID LINES|"
    r"MATERIAL PROPERTIES 0[4-9].*|.*DESIGN.*|PREFERENCES.*|PROJECT INFORMATION|"
    r"GROUPS .*|OPTIONS .*|.*DEFINITIONS - .*|CASE - .*|.*AUTO .*|FUNCTION .*|"
    r"MASS SOURCE.*|.*DISPLAY.*|TABLES AUTOMATICALLY SAVED.*|CONSTRAINT DEFINITIONS.*)$"
)


def tables(text: str) -> dict[str, list[dict[str, str]]]:
    """The tables of an ``.s2k`` text: name -> records of key -> value (quotes removed)."""
    result: dict[str, list[dict[str, str]]] = {}
    current: list[dict[str, str]] | None = None
    pending = ""
    for raw in text.splitlines():
        line = pending + raw.strip()
        pending = ""
        if line.endswith(" _"):
            pending = line[:-1]
            continue
        if not line:
            continue
        m = re.match(r'^TABLE:\s*"([^"]+)"', line, re.IGNORECASE)
        if m:
            current = result.setdefault(m.group(1).strip().upper(), [])
            continue
        if line.upper().startswith("END TABLE DATA"):
            current = None
            continue
        if current is None or "=" not in line:
            continue
        record = {k: v[1:-1] if v.startswith('"') else v for k, v in _RECORD.findall(line)}
        if record:
            current.append(record)
    return result


def _float(record: dict[str, str], key: str, default: float | None = None) -> float | None:
    value = record.get(key)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _yes(value: str | None) -> bool:
    return (value or "").strip().upper() in ("YES", "Y", "TRUE")


_KINDS = {
    "DEAD": "D",
    "SUPER DEAD": "SD",
    "SUPERDEAD": "SD",
    "LIVE": "L",
    "REDUCIBLE LIVE": "L",
    "REDUCE LIVE": "L",
    "ROOF LIVE": "Lr",
    "WIND": "W",
    "QUAKE": "E",
    "SEISMIC": "E",
}


class _Reader:
    def __init__(self, text: str, file: str) -> None:
        self.tables = tables(text)
        self.model = TextModel(format=FORMAT, file=file, report=ImportReport(FORMAT, file))
        self.report = self.model.report
        self.units = FileUnits()
        self.normals: dict[str, np.ndarray] = {}

    def rows(self, name: str) -> list[dict[str, str]]:
        return self.tables.get(name, [])

    def read(self) -> TextModel:
        for name, records in self.tables.items():
            if name not in _USED and not _QUIET.match(name):
                self.report.skip("tables not read", f"{name} ({len(records)})")
        self.read_units()
        self.read_geometry()
        self.read_materials()
        self.read_sections()
        self.read_supports()
        self.read_loads()
        self.read_combinations()
        return self.model

    def read_units(self) -> None:
        control = self.rows("PROGRAM CONTROL")
        text = control[0].get("CurrUnits") if control else None
        if not text:
            self.report.approximate(
                "files without units (PROGRAM CONTROL CurrUnits): kN, m assumed"
            )
            self.model.units = "KN, m"
            self.units = FileUnits(1000.0, 1000.0)
            return
        parts = [p.strip() for p in text.split(",")]
        try:
            units = Units.parse(parts[0], parts[1])
        except (ValueError, IndexError):
            self.report.approximate("units that could not be read: kN, m assumed", text)
            units = Units.parse("KN", "M")
        self.units = FileUnits(units.mm, units.newton)
        self.model.units = text
        if len(parts) > 2 and parts[2].upper() not in ("C", "F"):
            self.report.skip("temperature units", parts[2])

    def read_geometry(self) -> None:
        mm = self.units.length
        m = self.model
        for r in self.rows("JOINT COORDINATES"):
            jid = r.get("Joint")
            if jid is None:
                continue
            if "GlobalX" in r:
                xyz = [_float(r, k, 0.0) for k in ("GlobalX", "GlobalY", "GlobalZ")]
            elif r.get("CoordType", "Cartesian").upper().startswith("CART"):
                xyz = [_float(r, k, 0.0) for k in ("XorR", "Y", "Z")]
                if r.get("CoordSys", "GLOBAL").upper() != "GLOBAL":
                    self.report.approximate(
                        "joints in other coordinate systems read as global", jid
                    )
            else:
                self.report.skip("joints in cylindrical or spherical coordinates", jid)
                continue
            m.joints[jid] = np.array(xyz, dtype=float) * mm
        sections = {r.get("Frame"): r for r in self.rows("FRAME SECTION ASSIGNMENTS")}
        angles = {
            r.get("Frame"): _float(r, "Angle", 0.0) or 0.0
            for r in self.rows("FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL")
        }
        for r in self.rows("CONNECTIVITY - FRAME"):
            fid = r.get("Frame")
            if fid is None:
                continue
            if _yes(r.get("IsCurved")):
                self.report.approximate("curved frames taken straight", fid)
            assignment = sections.get(fid, {})
            section = assignment.get("AnalSect") or assignment.get("SectionName")
            material = assignment.get("MatProp")
            m.frames.append(
                Frame(
                    fid,
                    r.get("JointI", ""),
                    r.get("JointJ", ""),
                    section,
                    None if material in (None, "", "Default") else material,
                    rotation=angles.get(fid, 0.0),
                )
            )
        area_sections = {
            r.get("Area"): r.get("Section") for r in self.rows("AREA SECTION ASSIGNMENTS")
        }
        for r in self.rows("CONNECTIVITY - AREA"):
            aid = r.get("Area")
            if aid is None:
                continue
            count = int(_float(r, "NumJoints", 0) or 0)
            joints = [r[f"Joint{k}"] for k in range(1, count + 1) if f"Joint{k}" in r]
            m.areas.append(Area(aid, joints, area_sections.get(aid)))
            if all(j in m.joints for j in joints) and len(joints) >= 3:
                pts = [m.joints[j] for j in joints]
                normal = np.zeros(3)
                for p, q in zip(pts, pts[1:] + pts[:1], strict=True):
                    normal += np.cross(p - pts[0], q - pts[0])
                size = float(np.linalg.norm(normal))
                if size > 0:
                    self.normals[aid] = normal / size

    def read_materials(self) -> None:
        u = self.units
        types = {
            r.get("Material"): (r.get("Type") or "").lower()
            for r in self.rows("MATERIAL PROPERTIES 01 - GENERAL")
        }
        steel = {r.get("Material"): r for r in self.rows("MATERIAL PROPERTIES 03A - STEEL DATA")}
        concrete = {
            r.get("Material"): r for r in self.rows("MATERIAL PROPERTIES 03B - CONCRETE DATA")
        }
        for r in self.rows("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"):
            name = r.get("Material")
            if not name:
                continue
            kind = types.get(name, "")
            weight = _float(r, "UnitWeight")
            e = _float(r, "E1")
            d = MaterialDef(
                name=name,
                E=u.mpa(e) if e else None,
                nu=_float(r, "U12"),
                density=u.density(weight) if weight else None,
                kind="steel"
                if kind.startswith(("steel", "coldformed", "aluminum"))
                else "concrete"
                if kind.startswith("concrete")
                else None,
            )
            if kind.startswith(("rebar", "tendon")):
                continue  # bars and tendons: not the material of a member
            if name in steel:
                fy, fu = _float(steel[name], "Fy"), _float(steel[name], "Fu")
                d.fy, d.fu = (u.mpa(fy) if fy else None), (u.mpa(fu) if fu else None)
            if name in concrete:
                fc = _float(concrete[name], "Fc")
                d.fc = u.mpa(fc) if fc else None
            self.model.materials[name] = d

    def read_sections(self) -> None:
        mm = self.units.length
        for r in self.rows("FRAME SECTION PROPERTIES 01 - GENERAL"):
            name = r.get("SectionName")
            if not name:
                continue
            shape = (r.get("Shape") or "").lower()

            def dim(key: str, record: dict[str, str] = r) -> float:
                return (_float(record, key, 0.0) or 0.0) * mm

            t3, t2, tf, tw = dim("t3"), dim("t2"), dim("tf"), dim("tw")
            profile = None
            approximation = None
            try:
                if shape.startswith("rect") or shape == "concrete rectangular":
                    profile = rectangle(t2, t3)
                elif shape.startswith("circ"):
                    profile = circle_profile(t3 / 2)
                elif shape.startswith(("i/wide", "i-", "i section")):
                    if (
                        r.get("t2b")
                        and abs(dim("t2b") - t2) > 0.5
                        or (r.get("tfb") and abs(dim("tfb") - tf) > 0.5)
                    ):
                        approximation = "with unequal flanges taken with the top flange"
                    profile = o.IShapeProfile(
                        overallWidth=t2, overallDepth=t3, webThickness=tw, flangeThickness=tf
                    )
                elif shape.startswith("box"):
                    if abs(tf - tw) > 0.01:
                        approximation = "boxes with different flange and web walls: the mean wall"
                    profile = o.RectangleHollowProfile(
                        xDim=t2, yDim=t3, wallThickness=(tf + tw) / 2
                    )
                elif shape.startswith("pipe"):
                    profile = o.CircleHollowProfile(radius=t3 / 2, wallThickness=tw)
                elif shape.startswith("channel"):
                    profile = o.UShapeProfile(
                        depth=t3, flangeWidth=t2, webThickness=tw, flangeThickness=tf
                    )
                elif shape.startswith("angle"):
                    if abs(tf - tw) > 0.01:
                        approximation = "angles with different legs' thicknesses: the mean"
                    profile = o.LShapeProfile(depth=t3, width=t2, thickness=(tf + tw) / 2)
                elif shape.startswith("tee"):
                    profile = o.TShapeProfile(
                        depth=t3, flangeWidth=t2, webThickness=tw, flangeThickness=tf
                    )
                elif shape.startswith("general") or shape == "":
                    area = (_float(r, "Area", 0.0) or 0.0) * mm**2
                    inertia = (_float(r, "I33", 0.0) or 0.0) * mm**4
                    profile = equivalent_rectangle(area, inertia)
                    approximation = (
                        "given by their properties: a rectangle of the same area and major "
                        "inertia (minor inertia and torsion differ)"
                    )
                else:
                    profile, approximation = named_profile(r.get("SectInFile") or name)
                    approximation = approximation or f"of shape '{r.get('Shape')}' read by name"
            except ValueError:
                profile = None
            if profile is None:
                self.report.skip(
                    "frame sections that could not be read", f"{name} ({r.get('Shape')})"
                )
                continue
            self.model.sections[name] = SectionDef(
                name, profile, material=r.get("Material"), approximation=approximation
            )
        for r in self.rows("AREA SECTION PROPERTIES"):
            name = r.get("Section")
            if not name:
                continue
            thickness = _float(r, "Thickness") or _float(r, "BendThick")
            area_type = (r.get("AreaType") or "Shell").lower()
            if area_type not in ("shell", "plane", "asolid") or not thickness:
                self.report.skip("area sections without a thickness (decks, membranes, ...)", name)
                continue
            if area_type != "shell":
                self.report.approximate("plane and solid area sections taken as shells", name)
            if (r.get("Type") or "").lower().startswith("membrane"):
                self.report.approximate("membrane areas analysed as shells", name)
            self.model.area_sections[name] = SectionDef(
                name, thickness=thickness * mm, material=r.get("Material")
            )

    def read_supports(self) -> None:
        for r in self.rows("JOINT RESTRAINT ASSIGNMENTS"):
            jid = r.get("Joint")
            if jid is None:
                continue
            restraint = tuple(_yes(r.get(k)) for k in ("U1", "U2", "U3", "R1", "R2", "R3"))
            if any(restraint):
                self.model.supports[jid] = restraint

    def read_loads(self) -> None:
        u = self.units
        m = self.model
        for r in self.rows("LOAD PATTERN DEFINITIONS"):
            name = r.get("LoadPat")
            if not name:
                continue
            design = (r.get("DesignType") or "").upper()
            case = LoadCase(name=name, kind=_KINDS.get(design, "other"))
            case.selfweight = _float(r, "SelfWtMult", 0.0) or 0.0
            if case.kind == "other" and design:
                self.report.skip(
                    "load patterns of types SAEngine has no case for", f"{name} ({design})"
                )
            m.cases[name] = case
        lengths = {
            f.id: float(np.linalg.norm(m.joints[f.j] - m.joints[f.i]))
            for f in m.frames
            if f.i in m.joints and f.j in m.joints
        }
        frames = {f.id: f for f in m.frames}

        def vector(
            direction: str, frame: str | None = None, area: str | None = None
        ) -> np.ndarray | None:
            d = direction.strip().upper()
            if d.startswith("GRAVITY"):
                return np.array([0.0, 0.0, -1.0])
            axis = {"X": 0, "Y": 1, "Z": 2}.get(d.split()[0] if d else "")
            if axis is not None:
                v = np.zeros(3)
                v[axis] = 1.0
                return v
            if d in ("1", "2", "3"):
                if area is not None and d == "3" and area in self.normals:
                    return self.normals[area]
                if frame is not None and frame in frames:
                    f = frames[frame]
                    if f.i in m.joints and f.j in m.joints:
                        x = m.joints[f.j] - m.joints[f.i]
                        x = x / np.linalg.norm(x)
                        if d == "1":
                            return x
                        if d == "2" and abs(x[2]) < 0.999:  # local 2: up for beams
                            return np.array([0.0, 0.0, 1.0])
            return None

        def case_of(r: dict[str, str]) -> LoadCase | None:
            name = r.get("LoadPat")
            if name not in m.cases and name:
                m.cases[name] = LoadCase(name=name)
            return m.cases.get(name or "")

        for r in self.rows("FRAME LOADS - DISTRIBUTED"):
            case, fid = case_of(r), r.get("Frame", "")
            if case is None:
                continue
            if (r.get("Type") or "Force").lower() != "force":
                self.report.skip("distributed moments on frames", f"{case.name}: {fid}")
                continue
            v = vector(r.get("Dir", ""), frame=fid)
            if v is None:
                self.report.skip("frame loads in local directions not read", f"{case.name}: {fid}")
                continue
            if "PROJ" in (r.get("Dir") or "").upper():
                self.report.approximate("projected frame loads taken on the member length", fid)
            fa, fb = _float(r, "FOverLA", 0.0) or 0.0, _float(r, "FOverLB", 0.0) or 0.0
            length = lengths.get(fid, 0.0)
            if r.get("AbsDistA") is not None and r.get("AbsDistB") is not None:
                loaded = (
                    (_float(r, "AbsDistB", 0.0) or 0.0) - (_float(r, "AbsDistA", 0.0) or 0.0)
                ) * u.length
            else:
                loaded = (
                    (_float(r, "RelDistB", 1.0) or 0.0) - (_float(r, "RelDistA", 0.0) or 0.0)
                ) * length
            if abs(fa - fb) > 1e-9:
                self.report.approximate(
                    "trapezoidal frame loads taken as their mean", f"{case.name}: {fid}"
                )
            case.loads.append(
                Load("uniform", fid, v * u.n_per_m((fa + fb) / 2), length=abs(loaded) or None)
            )
        for r in self.rows("FRAME LOADS - POINT"):
            case, fid = case_of(r), r.get("Frame", "")
            if case is None:
                continue
            v = vector(r.get("Dir", ""), frame=fid)
            if v is None or (r.get("Type") or "Force").lower() != "force":
                self.report.skip(
                    "frame point loads not read (moments, local)", f"{case.name}: {fid}"
                )
                continue
            case.loads.append(Load("point", fid, v * (_float(r, "Force", 0.0) or 0.0) * u.force))
        for r in self.rows("JOINT LOADS - FORCE"):
            case, jid = case_of(r), r.get("Joint", "")
            if case is None:
                continue
            if r.get("CoordSys", "GLOBAL").upper() != "GLOBAL":
                self.report.approximate(
                    "joint loads in other coordinate systems read as global", jid
                )
            force = np.array([_float(r, k, 0.0) or 0.0 for k in ("F1", "F2", "F3")]) * u.force
            if any(_float(r, k, 0.0) for k in ("M1", "M2", "M3")):
                self.report.skip("joint moments", f"{case.name}: {jid}")
            case.loads.append(Load("joint", jid, force))
        for r in self.rows("AREA LOADS - UNIFORM"):
            case, aid = case_of(r), r.get("Area", "")
            if case is None:
                continue
            v = vector(r.get("Dir", ""), area=aid)
            if v is None:
                self.report.skip("area loads in directions not read", f"{case.name}: {aid}")
                continue
            case.loads.append(
                Load("pressure", aid, v * u.n_per_m2(_float(r, "UnifLoad", 0.0) or 0.0))
            )
        for r in self.rows("AREA LOADS - UNIFORM TO FRAME"):
            # The usual load of null-area slabs: SAP spreads it to the frames around the area.
            case, aid = case_of(r), r.get("Area", "")
            if case is None:
                continue
            v = vector(r.get("Dir", ""), area=aid)
            if v is None:
                self.report.skip("area loads in directions not read", f"{case.name}: {aid}")
                continue
            case.loads.append(
                Load("to-frame", aid, v * u.n_per_m2(_float(r, "UnifLoad", 0.0) or 0.0))
            )
        for name in (
            "AREA LOADS - SURFACE PRESSURE",
            "FRAME LOADS - TEMPERATURE",
        ):
            for r in self.rows(name):
                self.report.skip(
                    f"{name.lower()}", f"{r.get('LoadPat')}: {r.get('Area') or r.get('Frame')}"
                )

    def read_combinations(self) -> None:
        m = self.model
        # Load cases made of patterns (by default each pattern's own case of the same name).
        cases: dict[str, dict[str, float]] = {name: {name: 1.0} for name in m.cases}
        assignments: dict[str, dict[str, float]] = {}
        for r in self.rows("CASE - STATIC 1 - LOAD ASSIGNMENTS"):
            case = r.get("Case")
            if not case or (r.get("LoadType") or "Load pattern").lower() != "load pattern":
                continue
            pattern = r.get("LoadName", "")
            assignments.setdefault(case, {})
            assignments[case][pattern] = assignments[case].get(pattern, 0.0) + (
                _float(r, "LoadSF", 1.0) or 0.0
            )
        cases.update(assignments)
        for r in self.rows("LOAD CASE DEFINITIONS"):
            case_type = (r.get("Type") or "").lower()
            if (
                r.get("Case") not in assignments
                and r.get("Case") not in m.cases
                and case_type
                and "static" not in case_type
            ):
                self.report.skip("modal, response spectrum and other analysis cases", r.get("Case"))
        combos: dict[str, tuple[str, list[tuple[str, str, float]]]] = {}
        for r in self.rows("COMBINATION DEFINITIONS"):
            name = r.get("ComboName")
            if not name:
                continue
            entry = combos.setdefault(name, (r.get("ComboType") or "Linear Add", []))
            if r.get("ComboType") and not entry[1]:
                combos[name] = (r["ComboType"], entry[1])
            combos[name][1].append(
                (
                    r.get("CaseType") or "",
                    r.get("CaseName") or "",
                    _float(r, "ScaleFactor", 1.0) or 0.0,
                )
            )

        def expand(name: str, depth: int = 0) -> dict[str, float] | None:
            kind, terms = combos[name]
            if kind.lower().replace(" ", "") != "linearadd" or depth > 10:
                return None
            result: dict[str, float] = {}
            for case_type, case_name, factor in terms:
                if case_type.lower().endswith("combo") or (
                    case_name in combos and case_name not in cases
                ):
                    inner = expand(case_name, depth + 1) if case_name in combos else None
                    if inner is None:
                        return None
                    parts = inner
                elif case_name in cases:
                    parts = cases[case_name]
                else:
                    self.report.skip(
                        "combination terms on cases that are not read", f"{name}: {case_name}"
                    )
                    continue
                for pattern, f in parts.items():
                    result[pattern] = result.get(pattern, 0.0) + factor * f
            return result

        for name, (kind, _) in combos.items():
            factors = expand(name)
            if factors is None:
                self.report.skip("envelope, absolute and SRSS combinations", f"{name} ({kind})")
                continue
            m.combinations.append((name, factors))


def read_sap2000_text(text: str, file: str = "model.s2k") -> TextModel:
    return _Reader(text, file).read()


def read_sap2000(path: str | Path) -> TextModel:
    path = Path(path)
    return read_sap2000_text(path.read_text(encoding="utf-8", errors="replace"), path.name)


def import_sap2000(path: str | Path, name: str | None = None) -> ImportedProject:
    """The SAEngine project parts of the SAP2000 ``.s2k`` file at ``path``, with its report."""
    return build(read_sap2000(path), name)


__all__ = ["import_sap2000", "read_sap2000", "read_sap2000_text", "tables"]
