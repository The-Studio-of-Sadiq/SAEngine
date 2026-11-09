"""The analysis model as a ``.s2k`` text file: the database tables as text (``TABLE:  "NAME"``
followed by records of ``Key=Value`` pairs), units kN, m, °C.

Alpha 9 L12. Written from the format's public description and kept to the tables and fields
SAEngine's own ``.s2k`` reader understands (:mod:`saengine.importers.sap2000`), so an export reads
back into SAEngine; the target program's acceptance of every field is NOT verified (no copy of it
is run or read here; see ``docs/exchange.md``). The tables:

``PROGRAM CONTROL`` (``CurrUnits="KN, m, C"``), ``JOINT COORDINATES``, ``JOINT RESTRAINT
ASSIGNMENTS``, ``MATERIAL PROPERTIES 01 - GENERAL`` / ``02 - BASIC MECHANICAL PROPERTIES`` / ``03A
- STEEL DATA`` / ``03B - CONCRETE DATA``, ``FRAME SECTION PROPERTIES 01 - GENERAL`` (rectangular,
circular, I/wide flange, channel, angle, tee, box, pipe by their dimensions; general sections by A,
I33, I22, J), ``AREA SECTION PROPERTIES``, ``CONNECTIVITY - FRAME`` / ``- AREA``, ``FRAME SECTION
ASSIGNMENTS``, ``AREA SECTION ASSIGNMENTS``, ``FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL`` (the
angle: a vertical member's default local 2 lies along +X, so its depth along Y takes 90°),
``FRAME RELEASE ASSIGNMENTS 1 - GENERAL``, ``JOINT CONSTRAINT ASSIGNMENTS`` (the rigid
diaphragms), ``JOINT ADDED MASS ASSIGNMENTS`` and ``MASS SOURCE`` (SAEngine's lumped masses, the
mass source from the masses only), ``LOAD PATTERN DEFINITIONS`` (self-weight multiplier 0: the
analysis model's dead load case already holds the self-weight as loads), ``LOAD CASE
DEFINITIONS`` (the static cases and ``MODAL``, ``CASE - MODAL 1 - GENERAL`` with SAEngine's
number of modes) and ``CASE - STATIC 1 - LOAD ASSIGNMENTS``, ``JOINT LOADS - FORCE``, ``FRAME
LOADS - DISTRIBUTED`` (global X, Y, Z components; partial loads by absolute distances) and ``-
POINT``, ``COMBINATION DEFINITIONS`` (linear add).

The frames are the members, not the analysis mesh's segments
(:func:`saengine.exporters.analytical.joined_members`).
"""

from __future__ import annotations

from typing import Any

from saengine.exporters.analytical import (
    AnalyticalModel,
    ExchangeReport,
    count_written,
    joined_members,
)

FORMAT_NAME = "SAP text (.s2k)"
EXTENSION = ".s2k"
#: The folder of ``11 Exports`` the app writes it to.
EXPORT_FOLDER = "S2K"
#: The modal load case's name (SAEngine's modal analysis on its lumped masses).
MODAL_CASE = "MODAL"

_PATTERN_TYPES = {
    "D": "Dead",
    "SD": "Super Dead",
    "L": "Live",
    "Lr": "Roof Live",
    "W": "Wind",
    "E": "Quake",
    "other": "Other",
}


def _n(value: float) -> str:
    v = round(float(value), 9)
    return "0" if v == 0 else f"{v:.10g}"


def _v(value: Any) -> str:
    text = str(value)
    return f'"{text}"' if any(c in text for c in ' ,"=') or text == "" else text


def _record(**fields: Any) -> str:
    parts = []
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(
            f"{key}={_n(value) if isinstance(value, int | float) and not isinstance(value, bool) else _v(value)}"
        )
    return "   " + "   ".join(parts)


def _yes(flag: bool) -> str:
    return "Yes" if flag else "No"


def write_s2k(model: AnalyticalModel, report: ExchangeReport | None = None) -> str:
    """The ``.s2k`` text of ``model`` (kN, m)."""
    report = report or ExchangeReport(FORMAT_NAME, EXTENSION)
    model = joined_members(model, report)
    count_written(report, model, masses=True)
    kn = 1 / 1000
    out: list[str] = [
        f"File {model.name}.s2k was written by SAEngine (alpha 9 exchange export)",
        "",
    ]

    def table(name: str, rows: list[str]) -> None:
        if rows:
            out.extend([f'TABLE:  "{name}"', *rows, ""])

    table(
        "PROGRAM CONTROL",
        [_record(ProgramName="SAP2000", CurrUnits="KN, m, C", ModelName=model.name)],
    )
    nodes = model.used_nodes()
    table(
        "JOINT COORDINATES",
        [
            _record(
                Joint=str(n),
                CoordSys="GLOBAL",
                CoordType="Cartesian",
                XorR=model.nodes[n].xyz[0],
                Y=model.nodes[n].xyz[1],
                Z=model.nodes[n].xyz[2],
                SpecialJt="No",
                GlobalX=model.nodes[n].xyz[0],
                GlobalY=model.nodes[n].xyz[1],
                GlobalZ=model.nodes[n].xyz[2],
            )
            for n in nodes
        ],
    )
    report.count("joints", len(nodes))
    table(
        "JOINT RESTRAINT ASSIGNMENTS",
        [
            _record(
                Joint=str(n),
                **{
                    k: _yes(f)
                    for k, f in zip(
                        ("U1", "U2", "U3", "R1", "R2", "R3"), model.nodes[n].restraint, strict=True
                    )
                },
            )
            for n in nodes
            if model.nodes[n].supported
        ],
    )
    # SAEngine's lumped masses (its mass source) as joint masses [kN·s²/m, kN·m·s²]
    table(
        "JOINT ADDED MASS ASSIGNMENTS",
        [
            _record(
                Joint=str(n),
                CoordSys="GLOBAL",
                Mass1=m[0] * kn,
                Mass2=m[1] * kn,
                Mass3=m[2] * kn,
                MMI1=m[3] * kn,
                MMI2=m[4] * kn,
                MMI3=m[5] * kn,
            )
            for n, m in sorted(model.masses.items())
            if any(m) and n in model.nodes
        ],
    )
    if model.masses:
        table(
            "MASS SOURCE",
            [
                _record(
                    MassSource="MSSSRC1",
                    Elements="No",
                    Masses="Yes",
                    Loads="No",
                    IsDefault="Yes",
                )
            ],
        )
    # ── materials ──
    general, mech, steel, concrete = [], [], [], []
    for m in model.materials.values():
        kind = {"concrete": "Concrete", "steel": "Steel"}.get(m.kind, "Other")
        general.append(_record(Material=m.name, Type=kind, SymType="Isotropic"))
        mech.append(
            _record(
                Material=m.name,
                UnitWeight=m.unit_weight * kn,
                UnitMass=m.density * kn,
                E1=m.E * kn,
                G12=m.G * kn,
                U12=m.nu,
            )
        )
        if m.kind == "steel" and m.fy:
            steel.append(_record(Material=m.name, Fy=m.fy * kn, Fu=(m.fu or m.fy) * kn))
        if m.kind == "concrete" and m.fc:
            concrete.append(_record(Material=m.name, Fc=m.fc * kn))
        report.count("materials")
    table("MATERIAL PROPERTIES 01 - GENERAL", general)
    table("MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES", mech)
    table("MATERIAL PROPERTIES 03A - STEEL DATA", steel)
    table("MATERIAL PROPERTIES 03B - CONCRETE DATA", concrete)
    # ── sections ──
    rows = []
    for s in model.sections.values():
        d = s.dims
        props = {"Area": s.A, "TorsConst": s.J, "I33": s.I33, "I22": s.I22}
        if s.shape == "rectangle":
            rows.append(
                _record(
                    SectionName=s.name,
                    Material=s.material,
                    Shape="Rectangular",
                    t3=d["yDim"],
                    t2=d["xDim"],
                    **props,
                )
            )
        elif s.shape == "circle":
            rows.append(
                _record(
                    SectionName=s.name,
                    Material=s.material,
                    Shape="Circle",
                    t3=2 * d["radius"],
                    **props,
                )
            )
        elif s.shape == "I":
            rows.append(
                _record(
                    SectionName=s.name,
                    Material=s.material,
                    Shape="I/Wide Flange",
                    t3=d["overallDepth"],
                    t2=d["overallWidth"],
                    tf=d["flangeThickness"],
                    tw=d["webThickness"],
                    t2b=d["overallWidth"],
                    tfb=d["flangeThickness"],
                    **props,
                )
            )
        elif s.shape == "U":
            rows.append(
                _record(
                    SectionName=s.name,
                    Material=s.material,
                    Shape="Channel",
                    t3=d["depth"],
                    t2=d["flangeWidth"],
                    tf=d["flangeThickness"],
                    tw=d["webThickness"],
                    **props,
                )
            )
        elif s.shape == "T":
            rows.append(
                _record(
                    SectionName=s.name,
                    Material=s.material,
                    Shape="Tee",
                    t3=d["depth"],
                    t2=d["flangeWidth"],
                    tf=d["flangeThickness"],
                    tw=d["webThickness"],
                    **props,
                )
            )
        elif s.shape == "L":
            rows.append(
                _record(
                    SectionName=s.name,
                    Material=s.material,
                    Shape="Angle",
                    t3=d["depth"],
                    t2=d["width"],
                    tf=d["thickness"],
                    tw=d["thickness"],
                    **props,
                )
            )
        elif s.shape == "rectangleHollow":
            rows.append(
                _record(
                    SectionName=s.name,
                    Material=s.material,
                    Shape="Box/Tube",
                    t3=d["yDim"],
                    t2=d["xDim"],
                    tf=d["wallThickness"],
                    tw=d["wallThickness"],
                    **props,
                )
            )
        elif s.shape == "circleHollow":
            rows.append(
                _record(
                    SectionName=s.name,
                    Material=s.material,
                    Shape="Pipe",
                    t3=2 * d["radius"],
                    tw=d["wallThickness"],
                    **props,
                )
            )
        else:
            rows.append(_record(SectionName=s.name, Material=s.material, Shape="General", **props))
        report.count("sections")
    table("FRAME SECTION PROPERTIES 01 - GENERAL", rows)
    table(
        "AREA SECTION PROPERTIES",
        [
            _record(
                Section=p.name,
                Material=p.material,
                AreaType="Shell",
                Type="Shell-Thin",
                Thickness=p.thickness,
                BendThick=p.thickness,
            )
            for p in model.plate_sections.values()
        ],
    )
    # ── objects ──
    table(
        "CONNECTIVITY - FRAME",
        [
            _record(Frame=m.id, JointI=str(m.i), JointJ=str(m.j), IsCurved="No")
            for m in model.members
        ],
    )
    table(
        "FRAME SECTION ASSIGNMENTS",
        [
            _record(Frame=m.id, AutoSelect="N.A.", AnalSect=m.section, MatProp="Default")
            for m in model.members
        ],
    )
    angles = []
    for m in model.members:
        angle = (m.rotation + (90.0 if m.kind == "column" else 0.0)) % 360.0
        if abs(angle) > 1e-9:
            angles.append(_record(Frame=m.id, Angle=angle, AdvanceAxes="No"))
    table("FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL", angles)
    names = ("P", "V2", "V3", "T", "M2", "M3")
    releases = []
    for m in model.members:
        if m.releases[0] or m.releases[1]:
            fields = {f"{n}I": _yes(n in m.releases[0]) for n in names}
            fields.update({f"{n}J": _yes(n in m.releases[1]) for n in names})
            releases.append(_record(Frame=m.id, **fields, PartialFix="No"))
            report.count("releasedEnds", bool(m.releases[0]) + bool(m.releases[1]))
    table("FRAME RELEASE ASSIGNMENTS 1 - GENERAL", releases)
    table(
        "CONNECTIVITY - AREA",
        [
            _record(
                Area=p.id,
                NumJoints=len(p.nodes),
                **{f"Joint{k}": str(n) for k, n in enumerate(p.nodes, start=1)},
            )
            for p in model.plates
        ],
    )
    table("AREA SECTION ASSIGNMENTS", [_record(Area=p.id, Section=p.section) for p in model.plates])
    constraints = []
    for d in model.diaphragms:
        for n in [d.master, *d.nodes]:
            constraints.append(_record(Joint=str(n), Constraint=d.name, Type="Diaphragm"))
    table("JOINT CONSTRAINT ASSIGNMENTS", constraints)
    if model.diaphragms:
        table(
            "CONSTRAINT DEFINITIONS - DIAPHRAGM",
            [
                _record(Name=d.name, CoordSys="GLOBAL", Axis="Z", MultiLevel="No")
                for d in model.diaphragms
            ],
        )
    # ── loads ──
    table(
        "LOAD PATTERN DEFINITIONS",
        [
            _record(
                LoadPat=c.name,
                DesignType=_PATTERN_TYPES[c.kind],
                SelfWtMult=0,
                AutoLoad="None" if c.kind in ("W", "E") else None,
            )
            for c in model.cases
        ],
    )
    cases = [
        _record(
            Case=c.name, Type="LinStatic", InitialCond="Zero", DesignType=_PATTERN_TYPES[c.kind]
        )
        for c in model.cases
    ]
    if model.modes and model.masses:
        cases.append(
            _record(Case=MODAL_CASE, Type="LinModal", InitialCond="Zero", DesignType="Other")
        )
    table("LOAD CASE DEFINITIONS", cases)
    if model.modes and model.masses:
        table(
            "CASE - MODAL 1 - GENERAL",
            [
                _record(
                    Case=MODAL_CASE,
                    ModeType="Eigen",
                    MaxNumModes=int(model.modes),
                    MinNumModes=1,
                    EigenShift=0,
                    EigenCutoff=0,
                    EigenTol=1e-9,
                    AutoShift="Yes",
                )
            ],
        )
        report.count("modalCases")
    table(
        "CASE - STATIC 1 - LOAD ASSIGNMENTS",
        [
            _record(Case=c.name, LoadType="Load pattern", LoadName=c.name, LoadSF=1)
            for c in model.cases
        ],
    )
    joint_loads: list[str] = []
    frame_loads: list[str] = []
    point_loads: list[str] = []
    for c in model.cases:
        for n, f in sorted(c.nodal.items()):
            if any(abs(v) > 1e-9 for v in f):
                joint_loads.append(
                    _record(
                        Joint=str(n),
                        LoadPat=c.name,
                        CoordSys="GLOBAL",
                        F1=f[0] * kn,
                        F2=f[1] * kn,
                        F3=f[2] * kn,
                        M1=f[3] * kn,
                        M2=f[4] * kn,
                        M3=f[5] * kn,
                    )
                )
        for mid, w in c.uniform.items():
            for axis, value in zip(("X", "Y", "Z"), w, strict=True):
                if abs(value) > 1e-9:
                    frame_loads.append(
                        _record(
                            Frame=mid,
                            LoadPat=c.name,
                            CoordSys="GLOBAL",
                            Type="Force",
                            Dir=axis,
                            DistType="RelDist",
                            RelDistA=0,
                            RelDistB=1,
                            FOverLA=value * kn,
                            FOverLB=value * kn,
                        )
                    )
        for mid, runs in c.partial.items():
            for w, a, b in runs:
                for axis, value in zip(("X", "Y", "Z"), w, strict=True):
                    if value:
                        frame_loads.append(
                            _record(
                                Frame=mid,
                                LoadPat=c.name,
                                CoordSys="GLOBAL",
                                Type="Force",
                                Dir=axis,
                                DistType="AbsDist",
                                AbsDistA=a,
                                AbsDistB=b,
                                FOverLA=value * kn,
                                FOverLB=value * kn,
                            )
                        )
        for mid, forces in c.points.items():
            for f, at in forces:
                for axis, value in zip(("X", "Y", "Z"), f[:3], strict=True):
                    if value:
                        point_loads.append(
                            _record(
                                Frame=mid,
                                LoadPat=c.name,
                                CoordSys="GLOBAL",
                                Type="Force",
                                Dir=axis,
                                DistType="AbsDist",
                                AbsDist=at,
                                Force=value * kn,
                            )
                        )
    table("JOINT LOADS - FORCE", joint_loads)
    table("FRAME LOADS - DISTRIBUTED", frame_loads)
    table("FRAME LOADS - POINT", point_loads)
    report.count("memberPointLoads", len(point_loads))
    report.count("jointLoads", len(joint_loads))
    report.count("memberLoads", len(frame_loads))
    combos = []
    for name, factors in model.combinations:
        first = True
        for case, factor in factors.items():
            combos.append(
                _record(
                    ComboName=name,
                    ComboType="Linear Add" if first else None,
                    CaseType="Linear Static",
                    CaseName=case,
                    ScaleFactor=factor,
                )
            )
            first = False
    table("COMBINATION DEFINITIONS", combos)
    out.append("END TABLE DATA")
    return "\n".join(out) + "\n"


__all__ = ["EXPORT_FOLDER", "EXTENSION", "FORMAT_NAME", "write_s2k"]
