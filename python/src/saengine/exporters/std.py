"""The analysis model as a ``.std`` command file (STAAD command language), units kN, m.

Alpha 9 L12. Written from the command language's public description and kept to the commands
SAEngine's own ``.std`` reader understands (:mod:`saengine.importers.staad`), so an export reads
back into SAEngine; the target program's acceptance is NOT verified here (no copy of it is run or
read; see ``docs/exchange.md``). The file:

- ``STAAD SPACE``, ``SET Z UP`` (SAEngine's axes as they are), ``UNIT METER KN``;
- ``JOINT COORDINATES`` and ``MEMBER INCIDENCES`` numbered from 1 (the export report's
  ``numbering`` maps them to SAEngine's ids; members carry their ids in comments), ``ELEMENT
  INCIDENCES SHELL`` for the plates;
- ``DEFINE MATERIAL`` (``ISOTROPIC``, ``E``, ``POISSON``, ``DENSITY`` as a unit weight, ``TYPE``,
  ``STRENGTH FY/FU/FCU``), ``MEMBER PROPERTY`` (``PRIS YD ZD`` rectangles, ``PRIS YD`` circles,
  ``PIPE OD ID``, ``TUBE TH WT DT``, other shapes and general sections ``PRIS AX IZ IY IX``: the
  steel shapes by their properties, not by a table name), ``ELEMENT PROPERTY ... THICKNESS``,
  ``CONSTANTS`` (``MATERIAL``, ``BETA`` for rotated members);
- ``MEMBER RELEASE`` (``START``/``END MY MZ`` of the pinned ends), ``SUPPORTS`` (``FIXED``,
  ``PINNED``, ``FIXED BUT ...``);
- rigid diaphragms as ``SLAVE XY MASTER m JOINT ...`` (in-plane with Z up; unverified wording);
- one ``LOAD n LOADTYPE ... TITLE ...`` per case with ``JOINT LOAD`` and ``MEMBER LOAD ... UNI GX/
  GY/GZ`` (partial: ``UNI GZ w d1 d2``; point loads ``CON GZ f d``) (the self-weight is in the
  dead case's loads already: no ``SELFWEIGHT`` command); the modal analysis: a ``LOADTYPE Mass``
  case with SAEngine's lumped masses as joint weights in X and Y and ``MODAL CALCULATION
  REQUESTED`` (``CUT OFF MODE SHAPE`` SAEngine's number of modes); ``LOAD COMBINATION n name``
  per combination; ``PERFORM ANALYSIS``, ``FINISH``.

The members are the building's members, not the analysis mesh's segments
(:func:`saengine.exporters.analytical.joined_members`).

The section orientation (``BETA``) follows the command language's default member axes as SAEngine's
reader reads them; it is listed as unverified in ``docs/exchange.md``.
"""

from __future__ import annotations

from saengine.exporters.analytical import (
    AnalyticalModel,
    ExchangeReport,
    count_written,
    joined_members,
    numbering,
)

FORMAT_NAME = "STD text (.std)"
EXTENSION = ".std"
EXPORT_FOLDER = "STD"
#: m/s²: a mass's weight in the modal analysis' load case.
G = 9.80665

_LOADTYPES = {
    "D": "Dead",
    "SD": "Dead",
    "L": "Live",
    "Lr": "Roof Live",
    "W": "Wind",
    "E": "Seismic",
    "other": "None",
}
_RELEASES = {"P": "FX", "V2": "FY", "V3": "FZ", "T": "MX", "M2": "MY", "M3": "MZ"}


def _n(value: float) -> str:
    v = round(float(value), 9)
    return "0" if v == 0 else f"{v:.10g}"


def _title(text: str) -> str:
    return " ".join(str(text).replace(";", ",").split())[:70] or "-"


def _lists(numbers: list[int], per_line: int = 12) -> list[str]:
    """``1 2 3 -`` continuation lines of a list of numbers (``TO`` ranges for runs)."""
    tokens: list[str] = []
    sorted_numbers = sorted(set(numbers))
    k = 0
    while k < len(sorted_numbers):
        start = sorted_numbers[k]
        end = start
        while k + 1 < len(sorted_numbers) and sorted_numbers[k + 1] == end + 1:
            k += 1
            end = sorted_numbers[k]
        tokens.append(
            f"{start} TO {end}"
            if end - start >= 2
            else " ".join(str(v) for v in range(start, end + 1))
        )
        k += 1
    lines = []
    for i in range(0, len(tokens), per_line):
        lines.append(" ".join(tokens[i : i + per_line]))
    return [line + (" -" if i < len(lines) - 1 else "") for i, line in enumerate(lines)]


def write_std(model: AnalyticalModel, report: ExchangeReport | None = None) -> str:
    """The ``.std`` text of ``model`` (kN, m)."""
    report = report or ExchangeReport(FORMAT_NAME, EXTENSION)
    model = joined_members(model, report)
    count_written(report, model, masses=True)
    kn = 1 / 1000
    nodes, members, plates = numbering(model)
    out = [
        "STAAD SPACE",
        f"* {_title(model.name)}: written by SAEngine (alpha 9 exchange export)",
        "START JOB INFORMATION",
        f"JOB NAME {_title(model.name)}",
        "END JOB INFORMATION",
        "INPUT WIDTH 79",
        "SET Z UP",
        "UNIT METER KN",
        "JOINT COORDINATES",
    ]
    for node_id, k in nodes.items():
        x, y, z = model.nodes[node_id].xyz
        out.append(f"{k} {_n(x)} {_n(y)} {_n(z)};")
    report.count("joints", len(nodes))
    if model.members:
        out.append("MEMBER INCIDENCES")
        for m in model.members:
            out.append(f"{members[m.id]} {nodes[m.i]} {nodes[m.j]};")
    if model.plates:
        out.append("ELEMENT INCIDENCES SHELL")
        for p in model.plates:
            if len(p.nodes) not in (3, 4):
                report.skip("plates with other than 3 or 4 nodes", p.id)
                continue
            out.append(f"{plates[p.id]} " + " ".join(str(nodes[n]) for n in p.nodes) + ";")
    # ── materials ──
    out.append("DEFINE MATERIAL START")
    for mat in model.materials.values():
        out += [
            f"ISOTROPIC {mat.name}",
            f"E {_n(mat.E * kn)}",
            f"POISSON {_n(mat.nu)}",
            f"DENSITY {_n(mat.unit_weight * kn)}",
            f"G {_n(mat.G * kn)}",
            f"TYPE {'CONCRETE' if mat.kind == 'concrete' else 'STEEL' if mat.kind == 'steel' else 'OTHER'}",
        ]
        if mat.kind == "steel" and mat.fy:
            out.append(f"STRENGTH FY {_n(mat.fy * kn)} FU {_n((mat.fu or mat.fy) * kn)}")
        elif mat.kind == "concrete" and mat.fc:
            out.append(f"STRENGTH FCU {_n(mat.fc * kn)}")
        report.count("materials")
    out.append("END DEFINE MATERIAL")
    # ── properties ──
    if model.members:
        out.append("MEMBER PROPERTY")
        by_section: dict[str, list[int]] = {}
        for m in model.members:
            by_section.setdefault(m.section, []).append(members[m.id])
        for name, numbers in by_section.items():
            s = model.sections[name]
            d = s.dims
            if s.shape == "rectangle":
                prop = f"PRIS YD {_n(d['yDim'])} ZD {_n(d['xDim'])}"
            elif s.shape == "circle":
                prop = f"PRIS YD {_n(2 * d['radius'])}"
            elif s.shape == "circleHollow":
                od = 2 * d["radius"]
                prop = f"PIPE OD {_n(od)} ID {_n(od - 2 * d['wallThickness'])}"
            elif s.shape == "rectangleHollow":
                prop = f"TUBE TH {_n(d['wallThickness'])} WT {_n(d['xDim'])} DT {_n(d['yDim'])}"
            else:
                prop = f"PRIS AX {_n(s.A)} IZ {_n(s.I33)} IY {_n(s.I22)} IX {_n(s.J)}"
                if s.shape != "general":
                    report.approximate(
                        "steel shapes written by their properties (PRIS AX IZ IY IX)",
                        s.designation or s.name,
                    )
            out.append(f"* {s.name}")
            lines = _lists(numbers)
            lines[-1] = f"{lines[-1]} {prop}"
            out += lines
            report.count("sections")
    if model.plates:
        out.append("ELEMENT PROPERTY")
        by_plate: dict[str, list[int]] = {}
        for p in model.plates:
            by_plate.setdefault(p.section, []).append(plates[p.id])
        for name, numbers in by_plate.items():
            lines = _lists(numbers)
            lines[-1] = f"{lines[-1]} THICKNESS {_n(model.plate_sections[name].thickness)}"
            out += lines
    out.append("CONSTANTS")
    by_material: dict[str, list[int]] = {}
    for m in model.members:
        by_material.setdefault(model.sections[m.section].material, []).append(members[m.id])
    for p in model.plates:
        by_material.setdefault(model.plate_sections[p.section].material, []).append(plates[p.id])
    for name, numbers in by_material.items():
        out.append(f"MATERIAL {name} MEMB " + " ".join(_lists(numbers, 1000)))
    betas: dict[float, list[int]] = {}
    for m in model.members:
        if abs(m.rotation) > 1e-9:
            betas.setdefault(round(m.rotation, 6), []).append(members[m.id])
    for beta, numbers in betas.items():
        out.append(f"BETA {_n(beta)} MEMB " + " ".join(_lists(numbers, 1000)))
    # ── releases, supports, diaphragms ──
    starts = [(members[m.id], m.releases[0]) for m in model.members if m.releases[0]]
    ends = [(members[m.id], m.releases[1]) for m in model.members if m.releases[1]]
    if starts or ends:
        out.append("MEMBER RELEASE")
        report.count("releasedEnds", len(starts) + len(ends))
        for number, names in starts:
            out.append(f"{number} START " + " ".join(_RELEASES[n] for n in sorted(names)))
        for number, names in ends:
            out.append(f"{number} END " + " ".join(_RELEASES[n] for n in sorted(names)))
    supported = [n for n in nodes if model.nodes[n].supported]
    if supported:
        out.append("SUPPORTS")
        for n in supported:
            r = model.nodes[n].restraint
            if all(r):
                out.append(f"{nodes[n]} FIXED")
            elif all(r[:3]) and not any(r[3:]):
                out.append(f"{nodes[n]} PINNED")
            else:
                free = [
                    k for k, f in zip(("FX", "FY", "FZ", "MX", "MY", "MZ"), r, strict=True) if not f
                ]
                out.append(f"{nodes[n]} FIXED BUT " + " ".join(free))
        report.count("supports", len(supported))
    for d in model.diaphragms:
        slaves = [nodes[n] for n in d.nodes if n in nodes]
        if slaves:
            out.append(f"SLAVE XY MASTER {nodes[d.master]} JOINT " + " ".join(_lists(slaves, 1000)))
    if model.diaphragms:
        report.approximate(
            "rigid diaphragms as master and slave joints (SLAVE XY)", model.diaphragms[0].name
        )
    # ── loads ──
    case_numbers = {c.name: k for k, c in enumerate(model.cases, start=1)}
    for c in model.cases:
        out.append(
            f"LOAD {case_numbers[c.name]} LOADTYPE {_LOADTYPES[c.kind]} TITLE {_title(c.title_text())}"
        )
        joint = [(n, f) for n, f in sorted(c.nodal.items()) if any(abs(v) > 1e-9 for v in f)]
        if joint:
            out.append("JOINT LOAD")
            for n, f in joint:
                parts = [
                    f"{key} {_n(v * kn)}"
                    for key, v in zip(("FX", "FY", "FZ", "MX", "MY", "MZ"), f, strict=True)
                    if abs(v) > 1e-9
                ]
                out.append(f"{nodes[n]} " + " ".join(parts))
        member = [(mid, w) for mid, w in c.uniform.items() if any(abs(v) > 1e-9 for v in w)]
        if member:
            out.append("MEMBER LOAD")
            for mid, w in member:
                for axis, value in zip(("GX", "GY", "GZ"), w, strict=True):
                    if abs(value) > 1e-9:
                        out.append(f"{members[mid]} UNI {axis} {_n(value * kn)}")
        partial = [
            (mid, w, a, b, axis, value)
            for mid, runs in c.partial.items()
            for w, a, b in runs
            for axis, value in zip(("GX", "GY", "GZ"), w, strict=True)
            if value
        ]
        points = [
            (mid, at, axis, value)
            for mid, forces in c.points.items()
            for f, at in forces
            for axis, value in zip(("GX", "GY", "GZ"), f[:3], strict=True)
            if value
        ]
        if (partial or points) and not member:
            out.append("MEMBER LOAD")
        for mid, _w, a, b, axis, value in partial:
            out.append(f"{members[mid]} UNI {axis} {_n(value * kn)} {_n(a)} {_n(b)}")
        for mid, at, axis, value in points:
            out.append(f"{members[mid]} CON {axis} {_n(value * kn)} {_n(at)}")
    # SAEngine's lumped masses as the modal analysis' weights (kN, X and Y: the masses' own
    # directions; the vertical mass is not used by SAEngine's modal analysis)
    modal = bool(model.modes) and any(any(m[:2]) for m in model.masses.values())
    next_number = len(model.cases) + 1
    if modal:
        out.append(f"LOAD {next_number} LOADTYPE Mass TITLE MASSES OF THE MODAL ANALYSIS")
        out.append("JOINT LOAD")
        for n, m in sorted(model.masses.items()):
            if n not in nodes or not any(m[:3]):
                continue
            parts = [
                f"{key} {_n(v * G * kn)}"
                for key, v in zip(("FX", "FY", "FZ"), m[:3], strict=True)
                if abs(v) > 0
            ]
            out.append(f"{nodes[n]} " + " ".join(parts))
        out.append("MODAL CALCULATION REQUESTED")
        if any(abs(m[5]) > 0 for m in model.masses.values()):
            report.approximate(
                "rotary masses about Z left out of the modal analysis' weights", None
            )
        report.count("modalCases")
        next_number += 1
    for k, (name, factors) in enumerate(model.combinations, start=next_number):
        out.append(f"LOAD COMBINATION {k} {_title(name)}")
        terms = [f"{case_numbers[c]} {_n(f)}" for c, f in factors.items() if c in case_numbers]
        out.append(" ".join(terms))
    if modal:
        out.append(f"CUT OFF MODE SHAPE {int(model.modes)}")
    out += ["PERFORM ANALYSIS", "FINISH"]
    # The numbering in comments after FINISH: never read as commands.
    out.append("* SAEngine ids of the members: number = id")
    out += [f"* {members[m.id]} = {m.id}" for m in model.members]
    return "\n".join(out) + "\n"


__all__ = ["EXPORT_FOLDER", "EXTENSION", "FORMAT_NAME", "write_std"]
