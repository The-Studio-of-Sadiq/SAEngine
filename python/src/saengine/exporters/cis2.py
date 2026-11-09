"""CIS/2 (CIMsteel Integration Standards, LPM/6): the analysis model as a STEP physical file.

Alpha 9 L12. CIS/2 is the STEP-based (ISO 10303-21 file) steel exchange; its logical product model
LPM/6 (schema ``STRUCTURAL_FRAME_SCHEMA``) has an analysis model, a design model and a
manufacturing model. SAEngine writes the basics of the *analysis model* (LPM/6 basics): the
units, materials, section profiles with their properties, nodes with their restraints, curve
elements on the nodes, and the static load cases with nodal and uniform element loads.

The entity names follow the public LPM/6 documentation as SAEngine understands it, but their
attribute lists are written from that understanding only: they are NOT verified with a CIS/2
checker or a receiving program (see ``docs/exchange.md``; validate a file with a CIS/2 / LPM/6
checker before relying on it). For a steel *detailing* program, IFC (the building model export)
or SDNF are the tested routes.
"""

from __future__ import annotations

from datetime import datetime

from saengine.exporters.analytical import AnalyticalModel, ExchangeReport

FORMAT_NAME = "CIS/2 LPM/6 (.stp)"
EXTENSION = ".stp"
EXPORT_FOLDER = "CIS2"
SCHEMA = "STRUCTURAL_FRAME_SCHEMA"


def _s(text: str) -> str:
    """A STEP string: apostrophes doubled, ASCII only."""
    clean = str(text).encode("ascii", "replace").decode("ascii").replace("'", "''")
    return f"'{clean}'"


def _r(value: float) -> str:
    v = round(float(value), 9)
    text = f"{v:.9G}"
    return text if any(c in text for c in ".E") else text + "."


class _Step:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, entity: str, *attributes: str) -> str:
        ref = f"#{len(self.lines) + 1}"
        self.lines.append(f"{ref}={entity}({','.join(attributes)});")
        return ref


def write_cis2(
    model: AnalyticalModel, report: ExchangeReport | None = None, *, when: datetime | None = None
) -> str:
    """The CIS/2 (LPM/6) STEP text of ``model``'s analysis model (SI units: m, N, Pa)."""
    report = report or ExchangeReport(FORMAT_NAME, EXTENSION)
    when = when or datetime.now()
    s = _Step()
    length = s.add("SI_UNIT", "*", "$", ".METRE.")
    force = s.add("SI_UNIT", "*", "$", ".NEWTON.")
    pressure = s.add("SI_UNIT", "*", "$", ".PASCAL.")
    s.add("GLOBAL_UNIT_ASSIGNED_CONTEXT", f"({length},{force},{pressure})")
    analysis = s.add(
        "ANALYSIS_MODEL_3D",
        _s(model.name),
        _s("SAEngine analysis model"),
        ".SPACE_FRAME.",
        "3",
    )
    materials: dict[str, str] = {}
    for m in model.materials.values():
        ref = s.add("MATERIAL", _s(m.name), _s(m.kind))
        s.add(
            "MATERIAL_ELASTICITY",
            ref,
            _r(m.E),
            _r(m.G),
            _r(m.nu),
        )
        s.add("MATERIAL_MASS_DENSITY", ref, _r(m.density))
        if m.fy:
            s.add("MATERIAL_STRENGTH", ref, _s("yield"), _r(m.fy))
        materials[m.name] = ref
        report.count("materials")
    sections: dict[str, str] = {}
    for sec in model.sections.values():
        d = sec.dims
        if sec.shape == "I":
            profile = s.add(
                "SECTION_PROFILE_I_TYPE",
                _s(sec.designation or sec.name),
                _r(d["overallDepth"]),
                _r(d["overallWidth"]),
                _r(d["webThickness"]),
                _r(d["flangeThickness"]),
            )
        elif sec.shape == "rectangle":
            profile = s.add("SECTION_PROFILE_RECTANGLE", _s(sec.name), _r(d["yDim"]), _r(d["xDim"]))
        elif sec.shape == "circle":
            profile = s.add("SECTION_PROFILE_CIRCLE", _s(sec.name), _r(d["radius"]))
        elif sec.shape == "circleHollow":
            profile = s.add(
                "SECTION_PROFILE_CIRCLE_HOLLOW",
                _s(sec.name),
                _r(d["radius"]),
                _r(d["wallThickness"]),
            )
        elif sec.shape == "rectangleHollow":
            profile = s.add(
                "SECTION_PROFILE_RECTANGLE_HOLLOW",
                _s(sec.name),
                _r(d["yDim"]),
                _r(d["xDim"]),
                _r(d["wallThickness"]),
            )
        else:
            profile = s.add("SECTION_PROFILE", _s(sec.name))
            if sec.shape != "general":
                report.approximate(
                    "channel, angle and tee profiles written by their properties", sec.name
                )
        s.add("SECTION_PROPERTIES", profile, _r(sec.A), _r(sec.I33), _r(sec.I22), _r(sec.J))
        sections[sec.name] = profile
        report.count("sections")
    nodes: dict[int, str] = {}
    for n in model.used_nodes():
        node = model.nodes[n]
        point = s.add("CARTESIAN_POINT", _s(""), "(" + ",".join(_r(v) for v in node.xyz) + ")")
        restraint = "$"
        if node.supported:
            restraint = s.add(
                "BOUNDARY_CONDITION_LOGICAL",
                _s(f"support {n}"),
                *(".T." if f else ".F." for f in node.restraint),
            )
            report.count("supports")
        nodes[n] = s.add("NODE", _s(str(n)), point, restraint, analysis)
    report.count("joints", len(nodes))
    elements: dict[str, str] = {}
    for m in model.members:
        sec = model.sections[m.section]
        elements[m.id] = s.add(
            "ELEMENT_CURVE_SIMPLE",
            _s(m.id),
            _s(m.kind),
            "1",
            analysis,
            sections[m.section],
            materials.get(sec.material, "$"),
            nodes[m.i],
            nodes[m.j],
            _r(m.rotation),
        )
        if m.releases[0] or m.releases[1]:
            report.approximate("end releases not written (curve elements rigidly connected)", m.id)
        report.count("members")
    if model.plates:
        report.skip("plates (slabs and walls): not in this CIS/2 subset", model.plates[0].id)
    if model.diaphragms:
        report.skip(
            "rigid diaphragms (not in this CIS/2 subset) and the loads on their master nodes",
            model.diaphragms[0].name,
        )
    masters = {d.master for d in model.diaphragms}
    for c in model.cases:
        case = s.add("LOAD_CASE", _s(c.name), _s(c.title or c.name), analysis)
        for n, f in sorted(c.nodal.items()):
            if n in masters or n not in nodes:
                report.not_carried[c.name] += sum(v * v for v in f[:3]) ** 0.5 / 1000
                continue
            if any(abs(v) > 1e-9 for v in f):
                s.add(
                    "LOAD_NODE",
                    _s(f"{c.name} {n}"),
                    case,
                    nodes[n],
                    "(" + ",".join(_r(v) for v in f) + ")",
                )
        for mid, w in c.uniform.items():
            if any(abs(v) > 1e-9 for v in w):
                s.add(
                    "LOAD_ELEMENT_DISTRIBUTED_CURVE_LINE",
                    _s(f"{c.name} {mid}"),
                    case,
                    elements[mid],
                    ".GLOBAL.",
                    "(" + ",".join(_r(v) for v in w) + ")",
                )
        report.count("loadCases")
    for name, factors in model.combinations:
        s.add(
            "LOAD_COMBINATION",
            _s(name),
            analysis,
            "(" + ",".join(_s(k) for k in factors) + ")",
            "(" + ",".join(_r(v) for v in factors.values()) + ")",
        )
        report.count("combinations")
    header = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('CIS/2 analysis model (LPM/6 basics), written by SAEngine'),'2;1');",
        (
            f"FILE_NAME({_s(model.name + EXTENSION)},{_s(when.strftime('%Y-%m-%dT%H:%M:%S'))},"
            "(''),(''),'SAEngine','SAEngine','');"
        ),
        f"FILE_SCHEMA(('{SCHEMA}'));",
        "ENDSEC;",
        "DATA;",
    ]
    return "\n".join([*header, *s.lines, "ENDSEC;", "END-ISO-10303-21;"]) + "\n"


__all__ = ["EXPORT_FOLDER", "EXTENSION", "FORMAT_NAME", "SCHEMA", "write_cis2"]
