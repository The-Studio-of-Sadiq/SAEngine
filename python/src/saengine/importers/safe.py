"""Import of a CSI SAFE text file (``.f2k``, database tables as text) into a SAEngine project.

Supports both SAFE v12 (``OBJ GEOM - POINT COORDINATES``, ``SLAB PROPERTIES 02 - SOLID SLABS``,
``COLUMN PROPERTIES 01 - GENERAL``, ``LOAD ASSIGNMENTS - ...``) and SAFE v20/v23 (``POINT OBJECT
CONNECTIVITY``, ``FLOOR OBJECT CONNECTIVITY``, ``SLAB PROPERTY DEFINITIONS``, ``WALL PROPERTY
DEFINITIONS - SPECIFIED``, ``FRAME SECTION PROPERTY DEFINITIONS - ...``, ``LOAD PATTERN
DEFINITIONS``, ``AREA LOAD ASSIGNMENTS - UNIFORM``, plus the beam/column/wall connectivity and
frame/joint load tables written by :mod:`saengine.exporters.f2k`).

Reuses the shared ``.s2k`` table parser (:func:`saengine.importers.sap2000.tables`) and builds the
SAEngine project through :func:`saengine.importers.neutral.build`.
"""

from __future__ import annotations

import math
import re
from collections import Counter
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
from saengine.importers.sap2000 import _KINDS, _float, _yes, tables
from saengine.library import objects as o

FORMAT = "SAFE"

_USED = {
    "PROGRAM CONTROL",
    # Geometry / connectivity (v12 + v20+)
    "OBJ GEOM - POINT COORDINATES",
    "OBJ GEOM - LINES 01 - GENERAL",
    "OBJ GEOM - AREAS 01 - GENERAL",
    "POINT OBJECT CONNECTIVITY",
    "COLUMN OBJECT CONNECTIVITY",
    "BEAM OBJECT CONNECTIVITY",
    "FLOOR OBJECT CONNECTIVITY",
    "WALL OBJECT CONNECTIVITY",
    "STRIP OBJECT CONNECTIVITY",
    "TENDON OBJECT CONNECTIVITY",
    # Materials (v12 + v20+)
    "MATERIAL PROPERTIES 01 - GENERAL",
    "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES",
    "MATERIAL PROPERTIES 03A - STEEL DATA",
    "MATERIAL PROPERTIES 03B - CONCRETE DATA",
    "MATERIAL PROPERTIES 03E - REBAR DATA",
    "MATERIAL PROPERTIES - GENERAL",
    "MATERIAL PROPERTIES - BASIC MECHANICAL PROPERTIES",
    "MATERIAL PROPERTIES - STEEL DATA",
    "MATERIAL PROPERTIES - CONCRETE DATA",
    "MATERIAL PROPERTIES - REBAR DATA",
    "MATERIAL PROPERTIES - TENDON DATA",
    # Sections (v12 + v20+)
    "SLAB PROPERTIES 01 - GENERAL",
    "SLAB PROPERTIES 02 - SOLID SLABS",
    "WALL PROPERTIES 01 - GENERAL",
    "COLUMN PROPERTIES 01 - GENERAL",
    "BEAM PROPERTIES 01 - GENERAL",
    "SLAB PROPERTY DEFINITIONS",
    "WALL PROPERTY DEFINITIONS - SPECIFIED",
    "FRAME SECTION PROPERTY DEFINITIONS - SUMMARY",
    "FRAME SECTION PROPERTY DEFINITIONS - CONCRETE RECTANGULAR",
    "FRAME SECTION PROPERTY DEFINITIONS - CONCRETE CIRCLE",
    "FRAME SECTION PROPERTY DEFINITIONS - STEEL I/WIDE FLANGE",
    "FRAME SECTION PROPERTY DEFINITIONS - GENERAL",
    # Assignments & supports
    "SLAB PROPERTY ASSIGNMENTS",
    "WALL PROPERTY ASSIGNMENTS",
    "COLUMN PROPERTY ASSIGNMENTS",
    "BEAM PROPERTY ASSIGNMENTS",
    "FRAME ASSIGNMENTS - SECTION PROPERTIES",
    "FRAME ASSIGNMENTS - LOCAL AXES",
    "FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL",
    "FRAME ASSIGNMENTS - RELEASES",
    "FRAME RELEASE ASSIGNMENTS 1 - GENERAL",
    "AREA ASSIGNMENTS - SECTION PROPERTIES",
    "JOINT ASSIGNMENTS - RESTRAINTS",
    "JOINT RESTRAINT ASSIGNMENTS",
    # Loads & combinations (v12 + v20+)
    "LOAD PATTERNS",
    "LOAD PATTERN DEFINITIONS",
    "LOAD CASES 01 - GENERAL",
    "LOAD CASES 02 - STATIC",
    "LOAD CASE DEFINITIONS - SUMMARY",
    "LOAD CASE DEFINITIONS - LINEAR STATIC",
    "LOAD CASE DEFINITIONS - HYPERSTATIC",
    "MODAL CASE DEFINITIONS - EIGEN",
    "LOAD COMBINATIONS",
    "LOAD COMBINATION DEFINITIONS",
    "LOAD ASSIGNMENTS - SURFACE LOADS",
    "LOAD ASSIGNMENTS - POINT LOADS",
    "LOAD ASSIGNMENTS - LINE LOADS",
    "AREA LOAD ASSIGNMENTS - UNIFORM",
    "JOINT LOAD ASSIGNMENTS - FORCE",
    "FRAME LOAD ASSIGNMENTS - DISTRIBUTED",
    "FRAME LOAD ASSIGNMENTS - POINT",
}

_QUIET = re.compile(
    r"^(GRID DEFINITIONS.*|GRID LINES|COORDINATE SYSTEMS|ANALYSIS MODELING OPTIONS|"
    r"ANALYSIS OPTIONS.*|PREFERENCES.*|MISCELLANEOUS OPTIONS|OPTIONS .*|PROJECT INFORMATION|"
    r"MATERIAL LIST .*|.*DESIGN.*|GROUP DEFINITIONS|MASS SOURCE.*|DATABASE TABLE.*|"
    r"REINFORCING BAR SIZES|AREA SECTION PROPERTY DEFINITIONS - SUMMARY|"
    r"JOINT ASSIGNMENTS - SUMMARY|FRAME ASSIGNMENTS - SUMMARY|AREA ASSIGNMENTS - SUMMARY|"
    r"DIMENSION LINE OBJECT GEOMETRY)$"
)


def _get_any(record: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        val = record.get(key)
        if val is not None and val != "":
            return val
    return None


def _float_any(record: dict[str, str], *keys: str, default: float | None = None) -> float | None:
    for key in keys:
        val = _float(record, key)
        if val is not None:
            return val
    return default


class _Reader:
    def __init__(self, text: str, file: str) -> None:
        self.tables = tables(text)
        self.model = TextModel(format=FORMAT, file=file, report=ImportReport(FORMAT, file))
        self.report = self.model.report
        self.units = FileUnits()
        self.normals: dict[str, np.ndarray] = {}
        self.column_ids: set[str] = set()
        self.strip_points: set[str] = set()

    def rows(self, name: str) -> list[dict[str, str]]:
        return self.tables.get(name, [])

    def read(self) -> TextModel:
        for name, records in self.tables.items():
            if records and name not in _USED and not _QUIET.match(name):
                self.report.skip("tables not read", f"{name} ({len(records)})")
        self.read_units()
        self.read_geometry()
        self.read_materials()
        self.read_sections()
        self.read_assignments()
        self.read_supports()
        self.read_loads()
        self.read_combinations()
        self.read_other_objects()
        self._prune_strip_only_points()
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
        for r in self.rows("OBJ GEOM - POINT COORDINATES"):
            pid = r.get("Point")
            if not pid:
                continue
            xyz = [_float(r, k, 0.0) or 0.0 for k in ("GlobalX", "GlobalY", "GlobalZ")]
            m.joints[pid] = np.array(xyz, dtype=float) * mm
        for r in self.rows("POINT OBJECT CONNECTIVITY"):
            pid = _get_any(r, "UniqueName", "Unique Name", "Point")
            if not pid:
                continue
            xyz = [
                _float_any(r, k, gk, default=0.0) or 0.0
                for k, gk in (("X", "GlobalX"), ("Y", "GlobalY"), ("Z", "GlobalZ"))
            ]
            m.joints[pid] = np.array(xyz, dtype=float) * mm

        for r in self.rows("STRIP OBJECT CONNECTIVITY"):
            for k in ("Strip Start Point", "Segment End Point"):
                if r.get(k):
                    self.strip_points.add(r[k])

        # Frame section & orientation lookups across v12 and v20+
        sec_map: dict[str, tuple[str | None, str | None]] = {}
        for r in self.rows("COLUMN PROPERTY ASSIGNMENTS"):
            if r.get("Line"):
                sec_map[r["Line"]] = (r.get("ColProp"), None)
        for r in self.rows("BEAM PROPERTY ASSIGNMENTS"):
            if r.get("Line"):
                sec_map[r["Line"]] = (r.get("BeamProp"), None)
        for r in self.rows("FRAME ASSIGNMENTS - SECTION PROPERTIES"):
            fid = _get_any(r, "UniqueName", "Unique Name", "Frame")
            if fid:
                sec_map[fid] = (
                    _get_any(r, "Section Property", "AnalSect", "SectionName"),
                    r.get("MatProp"),
                )

        angles: dict[str, float] = {}
        for table_name in (
            "FRAME ASSIGNMENTS - LOCAL AXES",
            "FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL",
        ):
            for r in self.rows(table_name):
                fid = _get_any(r, "UniqueName", "Unique Name", "Frame")
                if fid:
                    angles[fid] = _float(r, "Angle", 0.0) or 0.0

        for r in self.rows("OBJ GEOM - LINES 01 - GENERAL"):
            fid = r.get("Line")
            if not fid:
                continue
            sec, mat = sec_map.get(fid, (None, None))
            if (r.get("LineType") or "").lower().startswith("col"):
                self.column_ids.add(fid)
            m.frames.append(
                Frame(
                    fid,
                    r.get("PointI", ""),
                    r.get("PointJ", ""),
                    sec,
                    mat,
                    rotation=angles.get(fid, 0.0),
                )
            )
        for table_name, is_col in (
            ("COLUMN OBJECT CONNECTIVITY", True),
            ("BEAM OBJECT CONNECTIVITY", False),
        ):
            for r in self.rows(table_name):
                fid = _get_any(r, "UniqueName", "Unique Name", "Frame")
                if not fid:
                    continue
                if is_col:
                    self.column_ids.add(fid)
                sec, mat = sec_map.get(fid, (None, None))
                m.frames.append(
                    Frame(
                        fid,
                        _get_any(r, "UniquePtI", "PointI", "JointI") or "",
                        _get_any(r, "UniquePtJ", "PointJ", "JointJ") or "",
                        sec,
                        None if mat in (None, "", "Default") else mat,
                        rotation=angles.get(fid, 0.0),
                    )
                )

        area_sections: dict[str, str] = {}
        for r in self.rows("SLAB PROPERTY ASSIGNMENTS"):
            if r.get("Area") and r.get("SlabProp"):
                area_sections[r["Area"]] = r["SlabProp"]
        for r in self.rows("WALL PROPERTY ASSIGNMENTS"):
            if r.get("Area") and r.get("WallProp"):
                area_sections[r["Area"]] = r["WallProp"]
        for r in self.rows("AREA ASSIGNMENTS - SECTION PROPERTIES"):
            aid = _get_any(r, "UniqueName", "Unique Name", "Area")
            sec = _get_any(r, "Section Property", "Section")
            if aid and sec:
                area_sections[aid] = sec

        def add_area(aid: str, joints: list[str]) -> None:
            m.areas.append(Area(aid, joints, area_sections.get(aid)))
            if all(j in m.joints for j in joints) and len(joints) >= 3:
                pts = [m.joints[j] for j in joints]
                normal = np.zeros(3)
                for p, q in zip(pts, pts[1:] + pts[:1], strict=True):
                    normal += np.cross(p - pts[0], q - pts[0])
                size = float(np.linalg.norm(normal))
                if size > 0:
                    self.normals[aid] = normal / size

        for r in self.rows("OBJ GEOM - AREAS 01 - GENERAL"):
            aid = r.get("Area")
            if not aid:
                continue
            count = int(_float(r, "NumPoints", 0) or 0)
            joints = [r[f"Point{k}"] for k in range(1, count + 1) if f"Point{k}" in r]
            add_area(aid, joints)
        for table_name in ("FLOOR OBJECT CONNECTIVITY", "WALL OBJECT CONNECTIVITY"):
            for r in self.rows(table_name):
                aid = _get_any(r, "Unique Name", "UniqueName", "Area")
                if not aid:
                    continue
                joints: list[str] = []
                k = 1
                while f"UniquePt{k}" in r or f"Point{k}" in r:
                    j = _get_any(r, f"UniquePt{k}", f"Point{k}")
                    if j:
                        joints.append(j)
                    k += 1
                if joints:
                    add_area(aid, joints)

    def read_materials(self) -> None:
        u = self.units
        types: dict[str, str] = {}
        for table_name in ("MATERIAL PROPERTIES 01 - GENERAL", "MATERIAL PROPERTIES - GENERAL"):
            for r in self.rows(table_name):
                if r.get("Material"):
                    types[r["Material"]] = (r.get("Type") or "").lower()
        steel: dict[str, dict[str, str]] = {}
        for table_name in (
            "MATERIAL PROPERTIES 03A - STEEL DATA",
            "MATERIAL PROPERTIES - STEEL DATA",
        ):
            for r in self.rows(table_name):
                if r.get("Material"):
                    steel[r["Material"]] = r
        concrete: dict[str, dict[str, str]] = {}
        for table_name in (
            "MATERIAL PROPERTIES 03B - CONCRETE DATA",
            "MATERIAL PROPERTIES - CONCRETE DATA",
        ):
            for r in self.rows(table_name):
                if r.get("Material"):
                    concrete[r["Material"]] = r
        rebar_data: dict[str, dict[str, str]] = {}
        for table_name in (
            "MATERIAL PROPERTIES 03E - REBAR DATA",
            "MATERIAL PROPERTIES - REBAR DATA",
        ):
            for r in self.rows(table_name):
                if r.get("Material"):
                    rebar_data[r["Material"]] = r

        mech_rows = self.rows("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES") + self.rows(
            "MATERIAL PROPERTIES - BASIC MECHANICAL PROPERTIES"
        )
        for r in mech_rows:
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
            if kind.startswith("rebar"):
                bars = rebar_data.get(name) or steel.get(name) or {}
                fy, fu = _float(bars, "Fy"), _float(bars, "Fu")
                d.fy, d.fu = (u.mpa(fy) if fy else None), (u.mpa(fu) if fu else None)
                self.model.rebars[name] = d
                continue
            if kind.startswith("tendon"):
                continue
            if name in steel:
                fy, fu = _float(steel[name], "Fy"), _float(steel[name], "Fu")
                d.fy, d.fu = (u.mpa(fy) if fy else None), (u.mpa(fu) if fu else None)
            if name in concrete:
                fc = _float(concrete[name], "Fc")
                d.fc = u.mpa(fc) if fc else None
            self.model.materials[name] = d

    def read_sections(self) -> None:
        mm = self.units.length

        # ── v12 column & beam properties ──
        for r in self.rows("COLUMN PROPERTIES 01 - GENERAL"):
            name = r.get("Column")
            if not name:
                continue
            shape = (r.get("Type") or "").lower()
            d2 = (_float(r, "SecDim2", 0.0) or 0.0) * mm
            d3 = (_float(r, "SecDim3", 0.0) or 0.0) * mm
            diam = (_float_any(r, "Diameter", "SecDim2", default=0.0) or 0.0) * mm
            profile = None
            approx = None
            if shape.startswith("circ") and diam > 0:
                profile = circle_profile(diam / 2)
            elif d2 > 0 and d3 > 0:
                profile = rectangle(d3, d2)
            else:
                profile, approx = named_profile(name)
            if profile is not None:
                self.model.sections[name] = SectionDef(
                    name, profile, material=r.get("MatProp"), approximation=approx
                )
            else:
                self.report.skip("frame sections that could not be read", name)

        for r in self.rows("BEAM PROPERTIES 01 - GENERAL"):
            name = r.get("Beam")
            if not name:
                continue
            depth = (_float_any(r, "Depth", "SecDim2", default=0.0) or 0.0) * mm
            width = (_float_any(r, "Width", "SecDim3", default=0.0) or 0.0) * mm
            if depth > 0 and width > 0:
                self.model.sections[name] = SectionDef(
                    name, rectangle(width, depth), material=r.get("MatProp")
                )

        # ── v20+ frame section definitions ──
        for r in self.rows("FRAME SECTION PROPERTY DEFINITIONS - CONCRETE RECTANGULAR"):
            name = r.get("Name")
            if not name:
                continue
            depth = (_float(r, "Depth", 0.0) or 0.0) * mm
            width = (_float(r, "Width", 0.0) or 0.0) * mm
            if depth > 0 and width > 0:
                self.model.sections[name] = SectionDef(
                    name, rectangle(width, depth), material=r.get("Material")
                )

        for r in self.rows("FRAME SECTION PROPERTY DEFINITIONS - CONCRETE CIRCLE"):
            name = r.get("Name")
            if not name:
                continue
            diam = (_float_any(r, "Diameter", "Depth", default=0.0) or 0.0) * mm
            if diam > 0:
                self.model.sections[name] = SectionDef(
                    name, circle_profile(diam / 2), material=r.get("Material")
                )

        for r in self.rows("FRAME SECTION PROPERTY DEFINITIONS - STEEL I/WIDE FLANGE"):
            name = r.get("Name")
            if not name:
                continue
            d = (_float(r, "Total Depth", 0.0) or 0.0) * mm
            bf = (_float(r, "Top Flange Width", 0.0) or 0.0) * mm
            tf = (_float(r, "Top Flange Thickness", 0.0) or 0.0) * mm
            tw = (_float(r, "Web Thickness", 0.0) or 0.0) * mm
            if d > 0 and bf > 0 and tf > 0 and tw > 0:
                approx = None
                bfb = _float(r, "Bottom Flange Width")
                tfb = _float(r, "Bottom Flange Thickness")
                if (bfb is not None and abs(bfb * mm - bf) > 0.5) or (
                    tfb is not None and abs(tfb * mm - tf) > 0.5
                ):
                    approx = "with unequal flanges taken with the top flange"
                profile = o.IShapeProfile(
                    overallWidth=bf, overallDepth=d, webThickness=tw, flangeThickness=tf
                )
            else:
                profile, approx = named_profile(name)
            if profile is not None:
                self.model.sections[name] = SectionDef(
                    name, profile, material=r.get("Material"), approximation=approx
                )

        for r in self.rows("FRAME SECTION PROPERTY DEFINITIONS - GENERAL"):
            name = r.get("Name")
            if not name or name in self.model.sections:
                continue
            area = (_float(r, "Area", 0.0) or 0.0) * mm**2
            inertia = (_float(r, "I33", 0.0) or 0.0) * mm**4
            profile = equivalent_rectangle(area, inertia)
            if profile is None:
                self.report.skip("frame sections that could not be read", name)
                continue
            self.model.sections[name] = SectionDef(
                name,
                profile,
                material=r.get("Material"),
                approximation=(
                    "given by their properties (GENERAL): a rectangle of the same area and "
                    "major inertia (minor inertia and torsion differ)"
                ),
            )

        for r in self.rows("FRAME SECTION PROPERTY DEFINITIONS - SUMMARY"):
            name = r.get("Name")
            if not name or name in self.model.sections:
                continue
            if (r.get("Shape") or "").lower().startswith("auto"):
                continue
            profile, approx = named_profile(name)
            if profile is not None:
                self.model.sections[name] = SectionDef(
                    name, profile, material=r.get("Material"), approximation=approx
                )

        # ── v12 slab & wall properties ──
        slab_gen = {
            r["Slab"]: r for r in self.rows("SLAB PROPERTIES 01 - GENERAL") if r.get("Slab")
        }
        for r in self.rows("SLAB PROPERTIES 02 - SOLID SLABS"):
            name = r.get("Slab")
            if not name:
                continue
            gen = slab_gen.get(name, {})
            thick = _float(r, "Thickness")
            mat = _get_any(r, "MatProp") or gen.get("MatProp")
            if thick and thick > 0:
                self.model.area_sections[name] = SectionDef(
                    name, thickness=thick * mm, material=mat
                )
        for r in self.rows("WALL PROPERTIES 01 - GENERAL"):
            name = r.get("Wall")
            if not name:
                continue
            thick = _float(r, "Thickness")
            if thick and thick > 0:
                self.model.area_sections[name] = SectionDef(
                    name, thickness=thick * mm, material=r.get("MatProp")
                )

        # ── v20+ slab & wall properties ──
        for r in self.rows("SLAB PROPERTY DEFINITIONS"):
            name = r.get("Name")
            if not name:
                continue
            prop_type = (r.get("Property Type") or "Slab").lower()
            thick = _float_any(r, "Slab Thickness", "Thickness")
            if prop_type == "opening" or not thick or thick <= 0:
                self.report.skip("slab sections without thickness (openings)", name)
                continue
            if (r.get("Modeling Type") or "").lower().startswith("membrane"):
                self.report.approximate("membrane slabs analysed as shells", name)
            self.model.area_sections[name] = SectionDef(
                name, thickness=thick * mm, material=r.get("Material")
            )
        for r in self.rows("WALL PROPERTY DEFINITIONS - SPECIFIED"):
            name = r.get("Name")
            if not name:
                continue
            thick = _float_any(r, "Wall Thickness", "Thickness")
            if thick and thick > 0:
                self.model.area_sections[name] = SectionDef(
                    name, thickness=thick * mm, material=r.get("Material")
                )

    def read_assignments(self) -> None:
        frames = {f.id: f for f in self.model.frames}
        names = ("P", "V2", "V3", "T", "M2", "M3")
        for table_name in ("FRAME ASSIGNMENTS - RELEASES", "FRAME RELEASE ASSIGNMENTS 1 - GENERAL"):
            for r in self.rows(table_name):
                fid = _get_any(r, "UniqueName", "Unique Name", "Frame")
                f = frames.get(fid or "")
                if f is None:
                    continue
                at_i = frozenset(n for n in names if _yes(r.get(f"{n}I")))
                at_j = frozenset(n for n in names if _yes(r.get(f"{n}J")))
                f.releases = (at_i, at_j)
                if _yes(r.get("PartialFix")):
                    self.report.approximate(
                        "partial fixity springs at released ends taken as full releases", f.id
                    )

    def read_supports(self) -> None:
        for r in self.rows("JOINT ASSIGNMENTS - RESTRAINTS"):
            jid = _get_any(r, "UniqueName", "Unique Name", "Joint")
            if not jid:
                continue
            restraint = tuple(_yes(r.get(k)) for k in ("UX", "UY", "UZ", "RX", "RY", "RZ"))
            if any(restraint):
                self.model.supports[jid] = restraint
        for r in self.rows("JOINT RESTRAINT ASSIGNMENTS"):
            jid = _get_any(r, "Joint", "Point", "UniqueName")
            if not jid:
                continue
            restraint = tuple(
                _yes(_get_any(r, k1, k2))
                for k1, k2 in (
                    ("U1", "UX"),
                    ("U2", "UY"),
                    ("U3", "UZ"),
                    ("R1", "RX"),
                    ("R2", "RY"),
                    ("R3", "RZ"),
                )
            )
            if any(restraint):
                self.model.supports[jid] = restraint

        # SAFE v12 columns hanging below the slab carry no restraint table; SAFE treats the far
        # end (not connected to anything else) as fixed. Only apply when the file has no
        # restraint entries at all so explicit cantilevers are never altered.
        if not self.model.supports and self.model.frames:
            refs: Counter[str] = Counter()
            for f in self.model.frames:
                refs[f.i] += 1
                refs[f.j] += 1
            for a in self.model.areas:
                for j in a.joints:
                    refs[j] += 1
            joints = self.model.joints
            for f in self.model.frames:
                is_col = f.id in self.column_ids or (
                    f.i in joints
                    and f.j in joints
                    and math.hypot(
                        float(joints[f.j][0] - joints[f.i][0]),
                        float(joints[f.j][1] - joints[f.i][1]),
                    )
                    < 1.0
                )
                if not is_col:
                    continue
                if refs[f.i] == 1 and refs[f.j] > 1:
                    far = f.i
                elif refs[f.j] == 1 and refs[f.i] > 1:
                    far = f.j
                else:
                    continue
                self.model.supports[far] = (True,) * 6
                self.report.approximate(
                    "free column far ends fixed (SAFE assumes columns are fixed at their far end)",
                    far,
                )

    def read_loads(self) -> None:
        u = self.units
        m = self.model
        for table_name in ("LOAD PATTERNS", "LOAD PATTERN DEFINITIONS"):
            for r in self.rows(table_name):
                name = _get_any(r, "LoadPat", "Name")
                if not name:
                    continue
                design = (r.get("Type") or r.get("DesignType") or "").upper()
                case = LoadCase(name=name, kind=_KINDS.get(design, "other"))
                case.selfweight = (
                    _float_any(r, "SelfWtMult", "Self Weight Multiplier", default=0.0) or 0.0
                )
                if case.kind == "other" and design:
                    self.report.note("loads.patterns.noCase", f"{name} ({design})")
                m.cases[name] = case

        lengths = {
            f.id: float(np.linalg.norm(m.joints[f.j] - m.joints[f.i]))
            for f in m.frames
            if f.i in m.joints and f.j in m.joints
        }
        frames = {f.id: f for f in m.frames}

        def frame_axes(f: Frame) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
            if f.i not in m.joints or f.j not in m.joints:
                return None
            x = m.joints[f.j] - m.joints[f.i]
            if np.linalg.norm(x) < 1e-9:
                return None
            e1 = x / np.linalg.norm(x)
            if math.hypot(e1[0], e1[1]) < 1e-3:
                e2 = np.array([1.0, 0.0, 0.0])
                e3 = np.cross(e1, e2)
            else:
                e3 = np.cross(e1, np.array([0.0, 0.0, 1.0]))
                e3 = e3 / np.linalg.norm(e3)
                e2 = np.cross(e3, e1)
            a = math.radians(f.rotation)
            return e1, math.cos(a) * e2 + math.sin(a) * e3, -math.sin(a) * e2 + math.cos(a) * e3

        def vector(
            direction: str, frame: str | None = None, area: str | None = None
        ) -> np.ndarray | None:
            d = direction.strip().upper()
            if d.startswith("GRAV"):
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
                    axes = frame_axes(frames[frame])
                    if axes is not None:
                        return axes[int(d) - 1]
            return None

        def case_of(r: dict[str, str]) -> LoadCase | None:
            name = _get_any(r, "LoadPat", "Load Pattern", "LoadName")
            if not name:
                return None
            if name not in m.cases:
                match = next((k for k in m.cases if k.upper() == name.upper()), None)
                if match is not None:
                    return m.cases[match]
                m.cases[name] = LoadCase(name=name)
            return m.cases[name]

        for table_name in ("LOAD ASSIGNMENTS - SURFACE LOADS", "AREA LOAD ASSIGNMENTS - UNIFORM"):
            for r in self.rows(table_name):
                case = case_of(r)
                aid = _get_any(r, "Area", "UniqueName", "Unique Name") or ""
                if case is None or not aid:
                    continue
                v = vector(_get_any(r, "Dir", "Direction") or "Gravity", area=aid)
                if v is None:
                    self.report.skip("area loads in directions not read", f"{case.name}: {aid}")
                    continue
                val = _float_any(r, "UnifLoad", "Load", default=0.0) or 0.0
                case.loads.append(Load("pressure", aid, v * u.n_per_m2(val)))

        for table_name in ("LOAD ASSIGNMENTS - POINT LOADS", "JOINT LOAD ASSIGNMENTS - FORCE"):
            for r in self.rows(table_name):
                case = case_of(r)
                jid = _get_any(r, "Point", "UniqueName", "Unique Name", "Joint") or ""
                if case is None or not jid:
                    continue
                fgrav = _float(r, "Fgrav", 0.0) or 0.0
                fx = _float_any(r, "FX", "Fx", "F1", default=0.0) or 0.0
                fy = _float_any(r, "FY", "Fy", "F2", default=0.0) or 0.0
                fz = (_float_any(r, "FZ", "Fz", "F3", default=0.0) or 0.0) - fgrav
                if any(
                    _float_any(r, k1, k2, default=0.0)
                    for k1, k2 in (("MX", "Mx"), ("MY", "My"), ("MZ", "Mz"))
                ):
                    self.report.note("loads.joint.moments", f"{case.name}: {jid}")
                case.loads.append(Load("joint", jid, np.array([fx, fy, fz]) * u.force))

        for table_name in ("FRAME LOAD ASSIGNMENTS - DISTRIBUTED", "LOAD ASSIGNMENTS - LINE LOADS"):
            for r in self.rows(table_name):
                case = case_of(r)
                fid = _get_any(r, "UniqueName", "Unique Name", "Frame", "Line") or ""
                if case is None or not fid:
                    continue
                v = vector(_get_any(r, "Direction", "Dir") or "Gravity", frame=fid)
                if v is None:
                    self.report.note("loads.member.direction", f"{case.name}: {fid}")
                    continue
                fa = _float_any(r, "Load A", "FOverLA", "Load", default=0.0) or 0.0
                fb = _float_any(r, "Load B", "FOverLB", default=fa)
                if fb is None:
                    fb = fa
                length = lengths.get(fid, 0.0)
                if (
                    r.get("Absolute Distance A") is not None
                    and r.get("Absolute Distance B") is not None
                ):
                    a = (_float(r, "Absolute Distance A", 0.0) or 0.0) * u.length
                    b = (_float(r, "Absolute Distance B", 0.0) or 0.0) * u.length
                elif r.get("AbsDistA") is not None and r.get("AbsDistB") is not None:
                    a = (_float(r, "AbsDistA", 0.0) or 0.0) * u.length
                    b = (_float(r, "AbsDistB", 0.0) or 0.0) * u.length
                else:
                    a = (
                        _float_any(r, "Relative Distance A", "RelDistA", default=0.0) or 0.0
                    ) * length
                    b = (
                        _float_any(r, "Relative Distance B", "RelDistB", default=1.0) or 0.0
                    ) * length
                if abs(fa - fb) > 1e-9:
                    self.report.note("loads.member.varying", f"{case.name}: {fid}")
                case.loads.append(
                    Load(
                        "uniform",
                        fid,
                        v * u.n_per_m((fa + fb) / 2),
                        length=abs(b - a) or None,
                        start=min(a, b),
                    )
                )

        for r in self.rows("FRAME LOAD ASSIGNMENTS - POINT"):
            case = case_of(r)
            fid = _get_any(r, "UniqueName", "Unique Name", "Frame") or ""
            if case is None or not fid:
                continue
            v = vector(_get_any(r, "Direction", "Dir") or "Gravity", frame=fid)
            if v is None:
                self.report.note("loads.member.direction", f"{case.name}: {fid}")
                continue
            if r.get("Absolute Distance") is not None:
                at = (_float(r, "Absolute Distance", 0.0) or 0.0) * u.length
            elif r.get("Relative Distance") is not None:
                at = (_float(r, "Relative Distance", 0.5) or 0.0) * lengths.get(fid, 0.0)
            else:
                at = None
            val = _float_any(r, "Load", "Force", default=0.0) or 0.0
            case.loads.append(Load("point", fid, v * val * u.force, start=at))

    def read_combinations(self) -> None:
        m = self.model
        cases: dict[str, dict[str, float]] = {name: {name: 1.0} for name in m.cases}
        case_lookup = {name.upper(): name for name in m.cases}

        def resolve_pattern(name: str) -> str:
            return name if name in m.cases else case_lookup.get(name.upper(), name)

        assignments: dict[str, dict[str, float]] = {}
        for table_name in ("LOAD CASES 02 - STATIC", "LOAD CASE DEFINITIONS - LINEAR STATIC"):
            for r in self.rows(table_name):
                case = _get_any(r, "LoadCase", "Name")
                load_type = (r.get("Load Type") or "Load").lower()
                if not case or load_type not in ("load", "load pattern"):
                    continue
                pattern = resolve_pattern(_get_any(r, "LoadPat", "Load Name") or "")
                sf = _float_any(r, "SF", "Load SF", default=1.0) or 0.0
                assignments.setdefault(case, {})
                assignments[case][pattern] = assignments[case].get(pattern, 0.0) + sf
        cases.update(assignments)

        for table_name in ("LOAD CASES 01 - GENERAL", "LOAD CASE DEFINITIONS - SUMMARY"):
            for r in self.rows(table_name):
                cname = _get_any(r, "LoadCase", "Name")
                ctype = (r.get("Type") or "").lower()
                if (
                    cname
                    and cname not in assignments
                    and cname not in m.cases
                    and ctype
                    and "static" not in ctype
                ):
                    self.report.skip("modal, hyperstatic and other analysis cases", cname)
        for table_name in ("MODAL CASE DEFINITIONS - EIGEN", "LOAD CASE DEFINITIONS - HYPERSTATIC"):
            for r in self.rows(table_name):
                cname = r.get("Name")
                if cname:
                    self.report.skip("modal, hyperstatic and other analysis cases", cname)

        combos: dict[str, tuple[str, list[tuple[str, str, float]]]] = {}
        for table_name in ("LOAD COMBINATIONS", "LOAD COMBINATION DEFINITIONS"):
            for r in self.rows(table_name):
                name = _get_any(r, "Combo", "Name")
                if not name:
                    continue
                ctype = r.get("Type") or "Linear Add"
                entry = combos.setdefault(name, (ctype, []))
                if r.get("Type") and not entry[1]:
                    combos[name] = (r["Type"], entry[1])
                load_name = _get_any(r, "Load", "Load Name") or ""
                sf = _float(r, "SF", 1.0) or 0.0
                combos[name][1].append((r.get("CaseType") or "", load_name, sf))

        case_by_upper = {k.upper(): k for k in cases}
        combo_by_upper = {k.upper(): k for k in combos}

        def expand(name: str, depth: int = 0) -> dict[str, float] | None:
            kind, terms = combos[name]
            if kind.lower().replace(" ", "") != "linearadd" or depth > 10:
                return None
            result: dict[str, float] = {}
            for case_type, case_name, factor in terms:
                cname = case_by_upper.get(case_name.upper(), case_name)
                kname = combo_by_upper.get(case_name.upper(), case_name)
                if case_type.lower().endswith("combo") or (kname in combos and cname not in cases):
                    inner = expand(kname, depth + 1) if kname in combos else None
                    if inner is None:
                        return None
                    parts = inner
                elif cname in cases:
                    parts = cases[cname]
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
                self.report.note("combinations.envelope", f"{name} ({kind})")
                continue
            m.combinations.append((name, factors))

    def read_other_objects(self) -> None:
        for r in self.rows("STRIP OBJECT CONNECTIVITY"):
            self.report.skip(
                "design strips: SAEngine designs slabs from its own strips / FE results",
                r.get("Name"),
            )
        for r in self.rows("TENDON OBJECT CONNECTIVITY"):
            self.report.skip("post-tensioning tendons not imported", r.get("Name"))

    def _prune_strip_only_points(self) -> None:
        if not self.strip_points:
            return
        used: set[str] = set(self.model.supports)
        for f in self.model.frames:
            used.update((f.i, f.j))
        for a in self.model.areas:
            used.update(a.joints)
        for c in self.model.cases.values():
            for load in c.loads:
                if load.kind == "joint":
                    used.add(load.target)
        for pid in self.strip_points - used:
            self.model.joints.pop(pid, None)


def read_safe_text(text: str, file: str = "model.f2k") -> TextModel:
    return _Reader(text, file).read()


def read_safe(path: str | Path) -> TextModel:
    path = Path(path)
    return read_safe_text(path.read_text(encoding="utf-8", errors="replace"), path.name)


def import_safe(path: str | Path, name: str | None = None) -> ImportedProject:
    """The SAEngine project parts of the SAFE ``.f2k`` file at ``path``, with its report."""
    return build(read_safe(path), name)


__all__ = ["import_safe", "read_safe", "read_safe_text"]
