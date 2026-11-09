"""SDNF (Steelwork Detailing Neutral File): the steel members and plates for detailing software.

Alpha 9 L12. SDNF is a published plain-text neutral format of the steel *physical* model: members
as one piece end to end (not the analysis model's split members, :func:`saengine.exporters.
analytical.physical_members`), with their section by table name, grade, cardinal point, rotation
and end releases; plates by their outline. Packets written (version 3.0 layout as SAEngine
understands the public description; NOT verified against a reference file or a detailing program,
see ``docs/exchange.md``):

- ``Packet 00`` title: program, project, date and time, units (millimetres);
- ``Packet 10`` linear members: per member ``id "cardinal point" status "class" "type" "piece
  mark" "grade" "section" rotation`` then the start and end points [mm], the web orientation
  vector (the section's depth direction), the cut-backs and offsets (0) and the end releases
  (``"FFFFFF"``-style codes: F fixed, R released, in the order Fx Fy Fz Mx My Mz);
- ``Packet 20`` plate members: ``id status "class" "type" "piece mark" "grade" thickness
  vertices`` then the vertices [mm].

Only steel goes in by default (the format is for steelwork); concrete members and plates are
reported as left out (``include_concrete`` writes them too, as SAEngine's sections).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from saengine.exporters.analytical import (
    AnalyticalModel,
    ExchangeReport,
    local_axes,
    physical_members,
)

FORMAT_NAME = "SDNF (.sdnf)"
EXTENSION = ".sdnf"
EXPORT_FOLDER = "SDNF"
VERSION = "3.0"

_CLASS = {"column": "Column", "beam": "Beam", "brace": "Brace"}
_ORDER = ("P", "V2", "V3", "T", "M2", "M3")


def _q(text: str) -> str:
    return '"' + str(text).replace('"', "'") + '"'


def _mm(value: float) -> str:
    v = round(float(value) * 1000, 3)
    return "0" if v == 0 else f"{v:g}"


def _release_code(released: frozenset[str]) -> str:
    return "".join("R" if a in released else "F" for a in _ORDER)


def depth_direction(model_member_start, model_member_end, rotation: float, kind: str) -> np.ndarray:
    """The section's depth direction (global unit vector) of a member: the analysis model's
    default (a beam's local z, a vertical member's local y) turned by ``rotation`` about the axis."""
    x, y, z = local_axes(model_member_start, model_member_end)
    base = y if kind == "column" else z
    other = np.cross(x, base)
    a = np.radians(rotation)
    return np.cos(a) * base + np.sin(a) * other


def write_sdnf(
    model: AnalyticalModel,
    report: ExchangeReport | None = None,
    *,
    include_concrete: bool = False,
    when: datetime | None = None,
) -> str:
    """The SDNF text of ``model``'s steel members and plates."""
    report = report or ExchangeReport(FORMAT_NAME, EXTENSION)
    when = when or datetime.now()
    out = [
        "Packet 00",
        (
            f'"SAEngine" {_q(model.name)} {_q(when.strftime("%Y-%m-%d"))} '
            f'{_q(when.strftime("%H:%M:%S"))} {VERSION} "Millimeters"'
        ),
    ]
    members = []
    for p in physical_members(model):
        section = model.sections[p.section]
        material = model.materials.get(section.material)
        steel = material is not None and material.kind == "steel"
        if not steel and not include_concrete:
            report.skip("concrete and other non-steel members (SDNF is for steelwork)", p.id)
            continue
        members.append((p, section, material))
    out += ["Packet 10", str(len(members))]
    for p, section, material in members:
        grade = material.name if material is not None else section.material
        name = section.designation or section.name
        if not section.designation:
            report.approximate(
                "sections without a table name written by SAEngine's name", section.name
            )
        out.append(
            f'{_q(p.id)} "10" 0 {_q(_CLASS.get(p.kind, "Beam"))} {_q(_CLASS.get(p.kind, "Beam"))} '
            f"{_q(p.id)} {_q(grade)} {_q(name)} {round(p.rotation, 6):g}"
        )
        out.append(" ".join(_mm(v) for v in (*p.start, *p.end)))
        web = depth_direction(p.start, p.end, p.rotation, p.kind)
        out.append(" ".join(f"{round(float(v), 6):g}" for v in web))
        out.append("0 0 0 0 0 0")
        out.append(f"{_q(_release_code(p.releases[0]))} {_q(_release_code(p.releases[1]))}")
        report.count("members")
    plates = []
    for plate in model.plates:
        ps = model.plate_sections[plate.section]
        material = model.materials.get(ps.material)
        if (material is None or material.kind != "steel") and not include_concrete:
            report.skip("concrete plates (slabs and walls) left out", plate.id)
            continue
        plates.append((plate, ps))
    out += ["Packet 20", str(len(plates))]
    for plate, ps in plates:
        out.append(
            f'{_q(plate.id)} 0 "Plate" "Plate" {_q(plate.id)} {_q(ps.material)} '
            f"{_mm(ps.thickness)} {len(plate.nodes)}"
        )
        for n in plate.nodes:
            out.append(" ".join(_mm(v) for v in model.nodes[n].xyz))
        report.count("plates")
    if not members and not plates:
        report.warn("The model has no steel members or plates: the SDNF file is empty.")
    return "\r\n".join(out) + "\r\n"


__all__ = ["EXPORT_FOLDER", "EXTENSION", "FORMAT_NAME", "VERSION", "depth_direction", "write_sdnf"]
