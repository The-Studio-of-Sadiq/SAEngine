"""BIM and MEP depth tests (GitHub issue #299, docs/parity-matrix.md part 2): the IFC export and
a third-party IFC adopted, the drawing sheets through DWG and back, a clash benchmark with its
BCF round trip, a hand take-off of a two-bay frame, the bill split by phase, and one room's
cooling load against a published worked example.

The frame (:func:`two_bay_plan`): grids A, B, C at 0, 6 and 12 m and 1, 2 at 0 and 5 m; six
400 x 400 columns from the base (0) to level 1 (3.2 m), seven 300 x 500 beams on the grid lines
at level 1 (four along X, three along Y) and two 150 mm slabs over the bays; under each column an
isolated footing 2.0 x 2.0 x 0.5 m founded at -1.5 m in 9 Substructure; the ground at 0. No bars:
the take-off is of concrete, formwork and earthwork. All synthetic.

The references are worked by hand in the cases (the BOQ's measurement rules as its notes state
them, not its code), or taken from the published example or the IFC file's own quantities.
"""

from __future__ import annotations

import collections
import io
import json
import math
import shutil
import zipfile
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from saengine.verification.cases.common import Case, Outcome, Quantity, Reference

EXACT = 0.005
DATA = Path(__file__).resolve().parents[1] / "data"
BSI_SAMPLE = DATA / "bsi-building-architecture-ifc2x3.ifc"

XS = {"A": 0.0, "B": 6000.0, "C": 12000.0}
YS = {"1": 0.0, "2": 5000.0}
COLUMNS = {  # id: (x grid, y grid)
    "C1": ("A", "1"), "C2": ("B", "1"), "C3": ("C", "1"),
    "C4": ("A", "2"), "C5": ("B", "2"), "C6": ("C", "2"),
}  # fmt: skip
BEAMS = {  # id: (start, end) as grid pairs
    "BX1": (("A", "1"), ("B", "1")), "BX2": (("B", "1"), ("C", "1")),
    "BX3": (("A", "2"), ("B", "2")), "BX4": (("B", "2"), ("C", "2")),
    "BY1": (("A", "1"), ("A", "2")), "BY2": (("B", "1"), ("B", "2")),
    "BY3": (("C", "1"), ("C", "2")),
}  # fmt: skip
SLABS = {"S1": ("A", "B"), "S2": ("B", "C")}

OBJECTS = {
    "objects": [
        {"id": "COL", "name": "Column 400x400", "kind": "column", "material": "C24.1",
         "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400}},
        {"id": "BM", "name": "Beam 300x500", "kind": "beam", "material": "C24.1",
         "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500}},
        {"id": "SL", "name": "Slab 150", "kind": "slab", "material": "C24.1", "thickness": 150},
        {"id": "STR", "name": "Stair", "kind": "staircase", "material": "C24.1",
         "waistThickness": 150, "riser": 160, "tread": 280, "flightWidth": 1200},
    ]
}  # fmt: skip


def two_bay_plan() -> Any:
    from saengine.library import FloorPlan, default_floor_plan

    base = default_floor_plan().model_dump(mode="json", by_alias=True)
    base["grids"]["x"] = [{"label": k, "position": v} for k, v in XS.items()]
    base["grids"]["y"] = [{"label": k, "position": v} for k, v in YS.items()]
    base["columns"] = [
        {"id": c, "type": "COL", "at": {"x": x, "y": y}, "base": "BASE", "top": "L1"}
        for c, (x, y) in COLUMNS.items()
    ]
    base["beams"] = [
        {"id": b, "type": "BM", "story": "L1", "start": {"x": s[0], "y": s[1]},
         "end": {"x": e[0], "y": e[1]}}
        for b, (s, e) in BEAMS.items()
    ]  # fmt: skip
    base["slabs"] = [
        {"id": s, "type": "SL", "story": "L1",
         "boundary": [{"x": a, "y": "1"}, {"x": b, "y": "1"}, {"x": b, "y": "2"},
                      {"x": a, "y": "2"}]}
        for s, (a, b) in SLABS.items()
    ]  # fmt: skip
    return FloorPlan.model_validate(base)


def two_bay_building(stair: bool = False) -> Any:
    from saengine.library.bim import Additions, generate

    building = generate(two_bay_plan(), "s")
    if stair:
        additions = {"stairs": [{"id": "ST1", "type": "STR", "base": "BASE", "top": "L1",
                                 "x": 2000, "y": 1000, "direction": 90}]}  # fmt: skip
        building = building.model_copy(update={"additions": Additions.model_validate(additions)})
    return building


FOOTING = {"type": "isolated", "length": 2000, "width": 2000, "thickness": 500,
           "foundingLevel": -1500, "material": "C24.1"}  # fmt: skip


def substructure() -> dict[str, Any]:
    return {
        "schema": "saengine.substructure/1",
        "foundations": [
            {"id": f"F{c[1:]}", "columns": [c], "center": [XS[gx], YS[gy]], **FOOTING}
            for c, (gx, gy) in COLUMNS.items()
        ],
    }


def _settings_json(ground: float = 0.0) -> str:
    from saengine.library.settings import Foundation, default_project_settings

    s = default_project_settings("Verification")
    s = s.model_copy(update={"foundation": Foundation(groundLevel=ground)})
    return s.model_dump_json(by_alias=True)


@cache
def two_bay_bill() -> dict[str, Any]:
    """The bill of quantities of the two-bay frame with its footings (``compute_boq``)."""
    from saengine.boq import compute_boq
    from saengine.library import default_material_library

    return compute_boq(
        two_bay_building().model_dump_json(by_alias=True),
        json.dumps(OBJECTS),
        default_material_library().model_dump_json(by_alias=True),
        json.dumps(substructure()),
        _settings_json(),
    )


def _item(bill: dict[str, Any], group: str, kind: str) -> dict[str, Any]:
    return next(i for i in bill["items"] if i["group"] == group and i.get("kind") == kind)


def _share(item: dict[str, Any], element: str) -> float:
    return sum(b["quantity"] for b in item["breakdown"] if b["element"] == element)


# ─────────────────────── hand take-off of the frame (DI4, DI5) ───────────────────────

COL_H, COL_B = 3.2, 0.4
BEAM_B, BEAM_H, SLAB_T = 0.3, 0.5, 0.15
CORNER = ("C1", "C3", "C4", "C6")  # a quarter of each under a slab
EDGE = ("C2", "C5")  # half of each under the two slabs
CLEAR = {"BX1": 5.6, "BX2": 5.6, "BX3": 5.6, "BX4": 5.6, "BY1": 4.6, "BY2": 4.6, "BY3": 4.6}
INNER = ("BY2",)  # under slabs on both sides


def hand_concrete() -> dict[str, float]:
    """Each element's concrete [m³] by the BOQ's rules (its notes): slabs to the grid lines,
    the parts of beams and columns under a slab measured with the slab, beams between the
    column faces."""
    out: dict[str, float] = {}
    for c in COLUMNS:
        under = (0.2 * 0.2) if c in CORNER else (0.4 * 0.2)
        out[c] = COL_B * COL_B * COL_H - under * SLAB_T
    for b, clear in CLEAR.items():
        under = BEAM_B if b in INNER else BEAM_B / 2
        out[b] = clear * BEAM_B * BEAM_H - clear * under * SLAB_T
    for s in SLABS:
        out[s] = 6.0 * 5.0 * SLAB_T
    for c in COLUMNS:
        out[f"F{c[1:]}"] = 2.0 * 2.0 * 0.5
    return out


def takeoff_case(_: Path) -> Outcome:
    bill = two_bay_bill()
    conc = hand_concrete()
    columns = sum(conc[c] for c in COLUMNS)
    beams = sum(conc[b] for b in BEAMS)
    slabs = sum(conc[s] for s in SLABS)
    footings = sum(conc[f"F{c[1:]}"] for c in COLUMNS)
    # Formwork. Columns: four sides over the height, less the faces the slab lies against over
    # its depth (corner columns 0.2 + 0.2 m, edge columns 0.2 + 0.2 + 0.4 m).
    col_form = 6 * 4 * COL_B * COL_H - SLAB_T * (4 * 0.4 + 2 * 0.8)
    # Beams: soffit and two sides over the clear span, less the sides against the slab.
    span = sum(CLEAR.values())
    against = sum(CLEAR[b] * (2 if b in INNER else 1) for b in CLEAR)
    beam_form = span * (BEAM_B + 2 * BEAM_H) - against * SLAB_T
    # Slabs: the soffit less the beams and columns under it; the edges all over beams.
    under_beams = sum(CLEAR[b] * (BEAM_B if b in INNER else BEAM_B / 2) for b in CLEAR)
    under_cols = 4 * 0.2 * 0.2 + 2 * 0.4 * 0.2
    slab_form = 2 * 30.0 - under_beams - under_cols
    footing_form = 6 * 4 * 2.0 * 0.5
    # Earthwork: pits 300 mm beyond the footings (2.6 x 2.6 m) from the ground (0) to the
    # blinding's underside (-1.5 - 0.075 m); the pits do not overlap (gaps 6 - 2.6 and 5 - 2.6).
    pit = 2.6 * 2.6 * 1.575
    blinding = 6 * 2.15 * 2.15 * 0.075
    steps = [
        (
            f"columns 6 x 0.4 x 0.4 x 3.2 less the slab's share 0.15 x (4 x 0.04 + 2 x 0.08) = "
            f"{columns:.3f} m³"
        ),
        (
            f"beams 0.3 x 0.5 over the clear spans 4 x 5.6 + 3 x 4.6 = {span:g} m, less 0.15 x 0.15 "
            f"under the slab (0.15 x 0.30 for BY2 between the bays) = {beams:.3f} m³"
        ),
        f"slabs 2 x 6 x 5 x 0.15 = {slabs:.3f} m³; footings 6 x 2 x 2 x 0.5 = {footings:.3f} m³",
        f"blinding 6 x 2.15 x 2.15 x 0.075 = {blinding:.4f} m³",
        f"formwork: columns 6 x 1.6 x 3.2 - 0.15 x 3.2 = {col_form:.3f} m²",
        (
            f"beams {span:g} x 1.3 - 0.15 x {against:g} (sides against the slab) = "
            f"{beam_form:.3f} m²"
        ),
        f"slabs 60 - {under_beams:.2f} (beams under) - {under_cols:.2f} (columns) = {slab_form:.3f} m²",
        f"footings 6 x 8 x 0.5 = {footing_form:g} m²",
        f"excavation 6 x 2.6 x 2.6 x 1.575 = {6 * pit:.3f} m³",
    ]

    def q(name: str, unit: str, ref: float, group: str, kind: str) -> Quantity:
        return Quantity(name, unit, ref, _item(bill, group, kind)["quantity"], EXACT)

    return Outcome(
        Reference(
            "Hand take-off by the BOQ's stated measurement rules (its notes: slabs to the grid "
            "lines, beams between column faces, pits 300 mm beyond the foundations to the "
            "underside of 75 mm blinding)",
            "V = b h L, A = perimeter x height less the faces against other members; "
            "excavation = (B + 0.6)(L + 0.6)(depth + 0.075)",
            steps,
        ),
        [
            q("Concrete, columns", "m³", columns, "concrete", "column"),
            q("Concrete, beams", "m³", beams, "concrete", "beam"),
            q("Concrete, slabs", "m³", slabs, "concrete", "slab"),
            q("Concrete, footings", "m³", footings, "concrete", "footing"),
            q("Concrete, blinding", "m³", blinding, "concrete", "blinding"),
            q("Formwork, columns", "m²", col_form, "formwork", "column"),
            q("Formwork, beams", "m²", beam_form, "formwork", "beam"),
            q("Formwork, slabs", "m²", slab_form, "formwork", "slab"),
            q("Formwork, footings", "m²", footing_form, "formwork", "footing"),
            q("Excavation", "m³", 6 * pit, "earthwork", "excavation"),
        ],
    )


def phasing_case(_: Path) -> Outcome:
    from saengine.project.phasing import Phasing, phase_bill

    bill = two_bay_bill()
    conc = hand_concrete()
    bay1 = ["C1", "C2", "C4", "C5", "BX1", "BX3", "BY1", "BY2", "S1", "F1", "F2", "F4", "F5"]
    phasing = Phasing.model_validate(
        {
            "phases": [{"id": "existing", "name": "Existing"}, {"id": "new", "name": "New"}],
            "defaultPhase": "new",
            "elements": {
                **{e: {"created": "existing"} for e in bay1},
                "S1": {"created": "existing", "demolished": "new"},
            },
        }
    )
    split = phase_bill(bill, phasing)
    new = next(p for p in split["phases"] if p["phase"] == "new")

    def total(rows: list[dict[str, Any]]) -> float:
        return sum(r["quantity"] for r in rows if r["group"] == "concrete" and r["unit"] == "m3")

    # The blinding is measured per footing too: bay 2's two footings' blinding is new.
    blind = 2.15 * 2.15 * 0.075
    kept = sum(conc[e] for e in bay1 if e != "S1") + 4 * blind
    built = sum(v for e, v in conc.items() if e not in bay1) + 2 * blind
    return Outcome(
        Reference(
            "Hand split of the take-off of DI4 by phase",
            "existing kept = sum over bay 1 but S1; new = sum over bay 2; demolished = S1",
            [
                (
                    "Existing (bay A-B): C1, C2, C4, C5, BX1, BX3, BY1, BY2, S1, F1, F2, F4, F5; S1 is "
                    "taken down in the new phase; everything else is new"
                ),
                (
                    f"kept {kept:.4f} m³ (with four footings' blinding), new {built:.4f} m³, "
                    f"demolished S1 {conc['S1']:.3f} m³"
                ),
            ],
        ),
        [
            Quantity("Existing concrete kept", "m³", kept, total(split["existing"]), EXACT),
            Quantity("New concrete", "m³", built, total(new["new"]), EXACT),
            Quantity("Demolished concrete", "m³", conc["S1"], total(new["demolished"]), EXACT),
            Quantity(
                "Whole bill",
                "m³",
                sum(conc.values()) + 6 * blind,
                sum(i["quantity"] for i in bill["items"] if i["group"] == "concrete"),
                EXACT,
            ),
        ],
    )


# ─────────────────────────────── DI1: IFC ───────────────────────────────


def _schema_errors(file: Any) -> list[str]:
    import ifcopenshell.validate

    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(file, log, express_rules=True)
    return [
        f"{s.get('attribute') or s.get('instance')}: {s.get('message')}"
        for s in log.statements
        if s.get("level", "error") == "error"
    ]


def ifc_case(_: Path) -> Outcome:
    import ifcopenshell
    import ifcopenshell.util.element as element_util

    from saengine.library import default_material_library
    from saengine.library.architecture import Architecture
    from saengine.library.architecture_ifc import import_architecture
    from saengine.library.ifc import export_ifc
    from saengine.library.objects import ObjectLibrary

    building = two_bay_building(stair=True)
    objects = ObjectLibrary.model_validate(OBJECTS)
    materials = default_material_library()
    counts: dict[str, int] = {}
    errors: dict[str, list[str]] = {}
    for schema in ("IFC4", "IFC2X3"):
        file, ids, _ = export_ifc(building, objects, materials, "Verification", schema=schema)
        errors[schema] = _schema_errors(file)
        counts[schema] = len(ids)
    sample = ifcopenshell.open(str(BSI_SAMPLE))
    sample_errors = _schema_errors(sample)
    walls = sample.by_type("IfcWall")
    qto = [element_util.get_psets(w).get("Qto_WallBaseQuantities", {}) for w in walls]
    length = sum(float(q["Length"]) for q in qto)
    thickness = sorted(float(q["Width"]) for q in qto)
    arch, summary = import_architecture(str(BSI_SAMPLE), Architecture(), {"GF": 0.0})
    types = {t.id: sum(layer.thickness for layer in t.layers) for t in arch.wallTypes}
    adopted_length = sum(
        sum(math.dist(a, b) for a, b in zip(w.path, w.path[1:], strict=False)) for w in arch.walls
    )
    adopted_thickness = sorted(types[w.type] for w in arch.walls)
    elements = 6 + 7 + 2 + 1  # columns, beams, slabs, the stair
    notes = (
        [f"{schema}: {e}" for schema, es in errors.items() for e in es]
        + [f"sample: {e}" for e in sample_errors]
        + summary.get("notes", [])
    )
    return Outcome(
        Reference(
            "IfcOpenShell's schema validation (ifcopenshell.validate, with the EXPRESS rules); "
            "the third-party sample's own Qto_WallBaseQuantities (buildingSMART "
            "Sample-Test-Files, Simple-Scene Building-Architecture.ifc, IFC2X3, CC BY 4.0)",
            "errors = 0; adopted walls, rooms = IfcWall, IfcSpace; length and width as the Qto",
            [
                (
                    f"SAEngine's export of the two-bay frame with a stair: {elements} elements, in "
                    "IFC4 and IFC2X3"
                ),
                f"sample: {len(walls)} IfcWall, {len(sample.by_type('IfcSpace'))} IfcSpace",
                (
                    f"Qto lengths {' + '.join(f'{float(q["Length"]):g}' for q in qto)} = {length:g} mm; "
                    f"widths {', '.join(f'{t:g}' for t in thickness)} mm"
                ),
            ],
        ),
        [
            Quantity("IFC4 schema errors", "", 0, len(errors["IFC4"]), EXACT),
            Quantity("IFC2X3 schema errors", "", 0, len(errors["IFC2X3"]), EXACT),
            Quantity("IFC4 elements exported", "", elements, counts["IFC4"], EXACT),
            Quantity("Sample schema errors", "", 0, len(sample_errors), EXACT),
            Quantity("Sample walls adopted", "", len(walls), summary["adopted"]["walls"], EXACT),
            Quantity(
                "Sample rooms adopted",
                "",
                len(sample.by_type("IfcSpace")),
                summary["adopted"]["rooms"],
                EXACT,
            ),
            Quantity("Adopted wall length", "mm", length, adopted_length, EXACT),
            *(
                Quantity(f"Adopted wall thickness {i + 1}", "mm", t, a, EXACT)
                for i, (t, a) in enumerate(zip(thickness, adopted_thickness, strict=False))
            ),
        ],
        [
            *notes,
            (
                "The sample is a SketchUp export: no openly licensed Revit- or ArchiCAD-exported "
                "IFC could be confirmed (see verification/data/README.md)."
            ),
        ],
    )


# ─────────────────────────────── DI2: DWG round trip ───────────────────────────────


def write_project(root: Path, mep: dict[str, Any] | None = None) -> Path:
    """The two-bay frame as a project folder (settings, materials, objects, floor plan, building
    model, substructure and 07 MEP)."""
    from saengine.library import default_material_library

    files = {
        "02 Project Settings/project-settings.json": _settings_json(),
        "03 Materials/materials.json": default_material_library().model_dump_json(by_alias=True),
        "04 Objects/objects.json": json.dumps(OBJECTS),
        "05 Floor Plan/floor-plan.json": two_bay_plan().model_dump_json(by_alias=True),
        "06 BIM/bim.json": two_bay_building().model_dump_json(by_alias=True),
        "09 Substructure/substructure.json": json.dumps(substructure()),
        "07 MEP/mep.json": json.dumps(mep or {"schema": "saengine.mep/1"}),
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _entities(path: Path) -> collections.Counter[tuple[str, str]]:
    import logging

    import ezdxf

    # LibreDWG's DXF draws ezdxf's warnings on its block and handle table; not wanted on stderr.
    logging.getLogger("ezdxf").setLevel(logging.ERROR)
    doc = ezdxf.readfile(str(path))
    return collections.Counter(
        (e.dxf.layer, e.dxftype())
        for layout in doc.layouts
        for e in layout
        if e.dxftype() != "VIEWPORT"
    )


def _rotated_mtext(path: Path) -> int:
    import ezdxf

    doc = ezdxf.readfile(str(path))
    return sum(
        1
        for space in [*doc.layouts, *doc.blocks]
        for text in space.query("MTEXT")
        if text.dxf.hasattr("rotation")
    )


def dwg_case(folder: Path) -> Outcome:
    from saengine.library import dwg
    from saengine.pipeline import drawings

    reference = Reference(
        "The sheets' own DXF (SAEngine's master file), counted with ezdxf",
        "entities per (layer, type) of the DXF handed to dxf2dwg = the sheet's; with LibreDWG, "
        "after DXF -> dxf2dwg -> DWG -> dwg2dxf -> DXF = before",
    )
    root = write_project(folder / "project")
    answer = drawings.generate(root, use_design=False)
    sheets = answer["sheets"]
    count = len(sheets)
    notes: list[str] = []
    # The part SAEngine does itself, with or without LibreDWG: the copy dwg_ready writes for
    # dxf2dwg keeps every entity and leaves no MTEXT rotation (group code 50) for it to refuse.
    ready_total = before_total = ready_mismatched = rotated_before = rotated_left = 0
    for sheet in sheets:
        dxf = Path(sheet["dxf"])
        ready = folder / "ready" / f"{sheet['number']}.dxf"
        ready.parent.mkdir(parents=True, exist_ok=True)
        dwg.dwg_ready(dxf, ready)
        before, after = _entities(dxf), _entities(ready)
        before_total += sum(before.values())
        ready_total += sum(after.values())
        rotated_before += _rotated_mtext(dxf)
        rotated_left += _rotated_mtext(ready)
        for key in before.keys() | after.keys():
            if before[key] != after[key]:
                ready_mismatched += 1
                notes.append(f"{sheet['number']} for dxf2dwg {key}: {before[key]} -> {after[key]}")
    reference.steps = [
        f"{count} sheets of the two-bay frame drawn (drawings.generate, no design results)",
        (
            f"{before_total} entities in their DXF (paper-space viewports left out), "
            f"{rotated_before} of them rotated MTEXT"
        ),
    ]
    quantities = [
        Quantity("Entities kept in the copy for dxf2dwg", "", before_total, ready_total, EXACT),
        Quantity("Layer and type groups changed for dxf2dwg", "", 0, ready_mismatched, EXACT),
        Quantity("Rotated MTEXT left for dxf2dwg", "", 0, rotated_left, EXACT),
    ]
    notes.append(
        "LibreDWG 0.14 rejected every sheet with a rotated MTEXT (DXF group code 50) until "
        "write_dwg turned the rotations into text directions (#299); the paper-space viewport "
        "comes back on layer 0 instead of VIEWPORTS, so viewports are not compared."
    )
    if dwg.find_writer() is None or dwg.find_converter() is None:
        notes.append("The DWG round trip was skipped: GNU LibreDWG (dxf2dwg, dwg2dxf) not found.")
        return Outcome(reference, quantities, notes)
    written = mismatched = after_total = 0
    for sheet in sheets:
        dxf = Path(sheet["dxf"])
        target = folder / "dwg" / f"{sheet['number']}.dwg"
        try:
            dwg.write_dwg(dxf, target)
        except dwg.DwgError as error:
            notes.append(f"{sheet['number']}: {error}")
            continue
        written += 1
        with dwg.converted(target) as back:
            before, after = _entities(dxf), _entities(back.dxf)
        after_total += sum(after.values())
        for key in before.keys() | after.keys():
            if before[key] != after[key]:
                mismatched += 1
                notes.append(f"{sheet['number']} {key}: {before[key]} -> {after[key]}")
    quantities += [
        Quantity("Sheets written as DWG", "", count, written, EXACT),
        Quantity("Entities read back", "", before_total, after_total, EXACT),
        Quantity("Layer and type groups that differ", "", 0, mismatched, EXACT),
    ]
    return Outcome(reference, quantities, notes)


# ─────────────────────────────── DI3: clashes and BCF ───────────────────────────────

#: DN100 pipe along Y through beam BX1 (y = 0, 300 wide, 2700-3200) at x = 3000, centre at
#: 2850: through the full width of the beam, its top 150 mm under the slab soffit (3050).
PIPE = {
    "class": "IfcPipeSegment",
    "name": "DN100 drain",
    "diameter": 100.0,
    "origin": [3000.0, -1000.0, 2850.0],
    "direction": [0.0, 1.0, 0.0],
    "length": 2000.0,
}
#: A 400 x 300 duct riser beside beam BX3 (y = 5000, its outer face at 5150): the duct's
#: face at y = 5200, 50 mm off the beam; 2.6 m clear of the columns at x = 0 and 6 m.
DUCT = {
    "class": "IfcDuctSegment",
    "name": "SA riser 400x300",
    "width": 400.0,
    "height": 300.0,
    "origin": [3000.0, 5350.0, 2000.0],
    "direction": [0.0, 0.0, 1.0],
    "length": 2000.0,
}
CLEARANCE = 100.0


def _placement(origin: list[float], x_axis: list[float], z_axis: list[float]) -> np.ndarray:
    x, z = np.array(x_axis, dtype=float), np.array(z_axis, dtype=float)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, np.cross(z, x), z, origin
    return m


def services_ifc(path: Path, services: list[dict[str, Any]]) -> None:
    """An MEP IFC in mm: each service an extruded circle or rectangle from ``origin`` along
    ``direction`` over ``length`` (as the clash tests build them)."""
    import ifcopenshell.api

    run = ifcopenshell.api.run
    f = run("project.create_file", version="IFC4")
    project = run("root.create_entity", f, ifc_class="IfcProject", name="MEP")
    run("unit.assign_unit", f, length={"is_metric": True, "raw": "MILLIMETERS"})
    model = run("context.add_context", f, context_type="Model")
    body = run("context.add_context", f, context_type="Model", context_identifier="Body",
               target_view="MODEL_VIEW", parent=model)  # fmt: skip
    site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    for item in services:
        element = run("root.create_entity", f, ifc_class=item["class"], name=item["name"])
        if "diameter" in item:
            profile = run("profile.add_parameterized_profile", f, ifc_class="IfcCircleProfileDef")
            profile.Radius = item["diameter"] / 2
        else:
            profile = run(
                "profile.add_parameterized_profile", f, ifc_class="IfcRectangleProfileDef"
            )
            profile.XDim, profile.YDim = item["width"], item["height"]
        shape = run("geometry.add_profile_representation", f, context=body, profile=profile,
                    depth=item["length"] / 1000)  # fmt: skip
        run("geometry.assign_representation", f, product=element, representation=shape)
        direction = np.array(item["direction"], dtype=float)
        x_axis = [1.0, 0.0, 0.0] if abs(direction[0]) < 0.9 else [0.0, 0.0, 1.0]
        run("geometry.edit_object_placement", f, product=element,
            matrix=_placement(item["origin"], x_axis, list(direction)), is_si=False)  # fmt: skip
        run("spatial.assign_container", f, products=[element], relating_structure=site)
    f.write(str(path))


def clash_case(folder: Path) -> Outcome:
    import ifcopenshell

    from saengine.library import default_material_library
    from saengine.library.ifc import export_ifc
    from saengine.library.mep import Coordination, MepModel
    from saengine.library.objects import ObjectLibrary
    from saengine.mep import bcf, coordination
    from saengine.mep.clash import find_clashes

    folder.mkdir(parents=True, exist_ok=True)
    building = two_bay_building()
    objects = ObjectLibrary.model_validate(OBJECTS)
    structure, _, _ = export_ifc(building, objects, default_material_library(), "Verification")
    services = folder / "services.ifc"
    services_ifc(services, [PIPE, DUCT])
    model = ifcopenshell.open(str(services))
    found, _ = find_clashes(
        structure, building, objects, MepModel(), [("services.ifc", "plumbing", model)],
        clearance=CLEARANCE,
    )  # fmt: skip
    hard = [c for c in found if c["kind"] == "hard"]
    near = [c for c in found if c["kind"] == "clearance"]
    pipe = next((c for c in hard if c["mepName"] == PIPE["name"]), None)
    duct = next((c for c in near if c["mepName"] == DUCT["name"]), None)
    # BCF: the clashes as issues of a coordination test, out to BCF 3.0 and into a fresh one.
    labels = {c["mep"]: c["mepName"] for c in found}
    issues = [
        {"key": f"T1:{c['mep']}:{c['structuralGlobalId']}", "test": "T1",
         "elements": [c["mep"], c["structuralGlobalId"]],
         "labels": [labels[c["mep"]], c["structural"]], "point": c["point"], "story": c["story"]}
        for c in found
    ]  # fmt: skip
    coord, _ = coordination.merge_found(Coordination(author="Verification"), issues, {"T1"})
    data = bcf.export_bcf(coord, ["services.ifc"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        markups = sum(n.endswith("markup.bcf") for n in archive.namelist())
    topics = bcf.read_bcf(data)
    merged, counts = bcf.merge_bcf(Coordination(), topics)
    kept = sum(
        1
        for issue in coord.issues
        for topic in topics
        if topic["guid"] == issue.guid and topic["elements"] == issue.elements
    )
    point_error = max(
        (
            math.dist(topic["point"], issue.point)
            for issue in coord.issues
            for topic in topics
            if topic["guid"] == issue.guid and topic.get("point") and issue.point
        ),
        default=math.inf,
    )
    shutil.rmtree(folder, ignore_errors=True)
    return Outcome(
        Reference(
            "Hand placement of the services against the frame's members",
            "overlap = the member's width crossed; gap = face to face",
            [
                (
                    "DN100 pipe along Y through BX1 (300 wide, 2700-3200 high) at x = 3000, centre "
                    "2850: overlap 300 mm, its top 3050 - 2900 = 150 mm under the slab (> 100)"
                ),
                (
                    "400 x 300 duct riser, faces at y = 5200 and 5500, beside BX3 (outer face 5150): "
                    "gap 50 mm < 100 mm clearance; 2.6 m from the columns, 200 mm from the slab edge"
                ),
                "hard clashes 1 (pipe - BX1), clearance clashes 1 (duct - BX3)",
                "BCF 3.0: one topic per clash; read back, the same GUIDs, elements and points",
            ],
        ),
        [
            Quantity("Hard clashes", "", 1, len(hard), EXACT),
            Quantity("Clearance clashes", "", 1, len(near), EXACT),
            Quantity("Pipe overlap through BX1", "mm", 300, pipe["depth"] if pipe else 0, 0.01),
            Quantity("Duct gap to BX3", "mm", 50, duct["depth"] if duct else 0, 0.01),
            Quantity("BCF topics written", "", len(found), markups, EXACT),
            Quantity("BCF topics read back", "", len(found), len(topics), EXACT),
            Quantity("Issues added on import", "", len(found), counts.get("added", 0), EXACT),
            Quantity("Topics with the same elements", "", len(found), kept, EXACT),
            Quantity("Viewpoint point error (<= 1 mm)", "mm", 1.0, max(point_error, 1.0), EXACT),
        ],
        [
            f"{c['kind']} {c['mepName']} / {c['structural']}: {c['type']}, {c['depth']} mm"
            for c in found
        ]
        + [f"imported: {len(merged.issues)} issues"],
    )


# ─────────────────────── DI6: one room's cooling load (published example) ───────────────────────

#: NPTEL (IIT Kharagpur), Refrigeration and Air Conditioning, Lesson 35 "Cooling and heating load
#: calculations", questions and answers, Q 10: a 3 m wide x 6 m deep x 3 m high room, only its
#: west wall (3 x 3 m, a 1.5 x 1.5 m double-glazed window) exposed, roof exposed, the floor over
#: a ventilated basement at the outdoor temperature; 43 °C DB / 24 °C WB out, 25 °C / 50 % in,
#: 101 kPa. Its results [W]:
NPTEL = {"wall": 300.38, "roof": 710.6, "floor": 388.8, "glassConduction": 126.4,
         "glassSolar": 580.5, "infiltrationS": 151.0, "infiltrationL": 16.4, "peopleS": 360.0,
         "peopleL": 160.0, "lights": 594.0, "equipmentS": 600.0, "equipmentL": 300.0,
         "sensible": 3811.68, "latent": 476.4, "total": 4288.08, "wOut": 0.0107,
         "wIn": 0.0099167}  # fmt: skip


def cooling_case(_: Path) -> Outcome:
    import dataclasses

    from shapely.geometry import box

    from saengine.hvac import fallback as F
    from saengine.hvac.constructions import FLOOR, u_value, with_u
    from saengine.hvac.constructions import envelope as envelope_choice
    from saengine.hvac.gains import Design, ZoneGains
    from saengine.hvac.geometry import Surface, ThermalZone, Window
    from saengine.library.mep import MepModel

    hvac = MepModel.model_validate({"hvac": {"design": {}, "envelope": {}, "stories": []}}).hvac
    env = envelope_choice(hvac.envelope)
    env = dataclasses.replace(
        env,
        wall=with_u(env.wall, 1.78),
        roof=with_u(env.roof, 1.316, roof=True),
        uGlazing=3.12,
        shgc=0.86,
        shading="none",
    )
    window = Window("W1", [], 1.5, 1.5)
    surfaces = [
        Surface("west", "Wall", "Wall", "Outdoors", [], 9.0, facade="W", windows=[window]),
        Surface("east", "Wall", "Wall", "Adiabatic", [], 9.0, facade="E"),
        Surface("north", "Wall", "Wall", "Adiabatic", [], 18.0, facade="N"),
        Surface("south", "Wall", "Wall", "Adiabatic", [], 18.0, facade="S"),
        Surface("roof", "Roof", "Roof", "Outdoors", [], 18.0),
        Surface("floor", "Floor", "Floor", "Outdoors", [], 18.0),
    ]
    zone = ThermalZone("room", "GF", 0.0, 3.0, box(0, 0, 3, 6), True, None, surfaces)
    gains = ZoneGains("office", 4, 33.0, 600.0 / 18.0, 130.0, 0.0, 0.0, 0.5, 25.0, 50.0)
    # 101 kPa: the standard atmosphere at 27.1 m (ASHRAE Fundamentals Ch 1 Eq 3, solved).
    elevation = (1 - (101.0 / 101.325) ** (1 / 5.2559)) / 2.25577e-5
    design = Design(None, 43.0, 24.0, 0.0, 0.0, 0.0, elevation, (5,))  # type: ignore[arg-type]
    est = F.zone_load(zone, gains, env, design)
    b = {k: v * 1000 for k, v in est["breakdown"].items()}
    p = F.pressure(elevation)
    w_out = F.humidity_ratio_wb(43.0, 24.0, p)
    w_in = F.humidity_ratio_rh(25.0, 50.0, p)
    vs, vl = F.ventilation_load(0.5 * 54 / 3600, 43.0, w_out, 25.0, w_in)
    u_floor = u_value(FLOOR)
    total = est["total"] * 1000 + 300.0  # the example's equipment latent, which SAEngine omits
    return Outcome(
        Reference(
            "NPTEL / IIT Kharagpur, Refrigeration and Air Conditioning (course 112105129, "
            "archive.nptel.ac.in/courses/112/105/112105129), Lesson 35, Questions and answers, "
            "Q 10 (numbers read from a public copy of the lesson; not checked against NPTEL's own "
            "PDF)",
            "Q = U A ETD (wall, roof) + U A dT (floor, glass) + A SHGF SC + people + lights + "
            "equipment + infiltration",
            [
                (
                    "wall 1.78 x 6.75 x 25 (ETD) = 300.4 W; roof 1.316 x 18 x 30 = 710.6 W; floor "
                    "1.2 x 18 x 18 = 388.8 W"
                ),
                "glass 3.12 x 2.25 x 18 = 126.4 W; solar 2.25 x 300 x 0.86 = 580.5 W",
                "people 4 x (90 + 40) W; lights 33 x 18 = 594 W; equipment 600 + 300 W",
                "infiltration 0.5 ACH x 54 m³ at 1.095 kg/m³: 151.0 W sensible, 16.4 W latent",
                "sensible 3811.7, latent 476.4, total 4288.1 W",
            ],
        ),
        [
            Quantity("Outdoor humidity ratio (43 / 24 °C)", "kg/kg", NPTEL["wOut"], w_out, 0.03),
            Quantity("Indoor humidity ratio (25 °C, 50 %)", "kg/kg", NPTEL["wIn"], w_in, 0.01),
            Quantity(
                "Glass conduction", "W", NPTEL["glassConduction"], b["glazingConduction"], EXACT
            ),
            Quantity("Lights", "W", NPTEL["lights"], b["lights"], EXACT),
            Quantity("Equipment, sensible", "W", NPTEL["equipmentS"], b["equipment"], EXACT),
            Quantity("People, total", "W", NPTEL["peopleS"] + NPTEL["peopleL"], b["people"], EXACT),
        ],
        [
            (
                "Where SAEngine's estimate uses another method the results differ and are not "
                "compared: "
                f"walls {b['walls']:.0f} W (sol-air a I / ho with the west 300 W/m² mean, "
                f"against ETD 25 K: {NPTEL['wall']} W); roof {b['roof']:.0f} W (600 W/m², "
                f"against ETD 30 K: {NPTEL['roof']} W); glass solar {b['glazingSolar']:.0f} W "
                f"(west peak 500 W/m² x SHGC, against 300 W/m² x SC: {NPTEL['glassSolar']} W); "
                f"floor {b['floors']:.0f} W (SAEngine's 150 mm RC slab, U = {u_floor:.2f}, "
                f"against U = 1.2: {NPTEL['floor']} W)."
            ),
            (
                "People: SAEngine splits 130 W into 75 sensible + 55 latent, the example 90 + 40; "
                "the total agrees. Equipment latent (300 W) has no input in SAEngine."
            ),
            (
                f"Infiltration: SAEngine's outdoor air at standard density 1.204 kg/m³ gives "
                f"{vs * 1000:.0f} W sensible and {vl * 1000:.1f} W latent, against the example's "
                f"1.095 kg/m³ at 43 °C ({NPTEL['infiltrationS']} and {NPTEL['infiltrationL']} W, "
                "the latter with dW read off a chart as 0.0008)."
            ),
            (
                f"Whole room: SAEngine's estimate {est['total'] * 1000:.0f} W (+ the example's 300 W "
                f"equipment latent = {total:.0f} W) against {NPTEL['total']} W, ratio "
                f"{total / NPTEL['total']:.3f}: on the safe side, mainly through the exposed floor "
                "(a bare RC slab, U 4.2 against the example's 1.2; the estimate has no input for "
                "an exposed floor's construction), then the sol-air roof and the peak west glass."
            ),
        ],
    )


CASES = [
    Case(
        "DI1",
        "IFC export validated; a third-party IFC adopted",
        "design",
        "SAEngine's IFC4 and IFC2X3 exports of a two-bay frame with a stair pass IfcOpenShell's "
        "schema validation; buildingSMART's Building-Architecture sample validates and its "
        "walls and spaces come in through the architect-IFC import with their own lengths and "
        "widths.",
        "Two-bay frame (6 + 6 m x 5 m, one storey) with a 1200 mm stair; buildingSMART "
        "Simple-Scene Building-Architecture.ifc (IFC2X3, SketchUp export, CC BY 4.0).",
        ifc_case,
    ),
    Case(
        "DI2",
        "Drawing sheets through DWG and back",
        "design",
        "Every sheet of the two-bay frame's drawing set is written as DWG with LibreDWG's "
        "dxf2dwg, read back with dwg2dxf and its entities counted per layer and type against "
        "the sheet's DXF; without LibreDWG only the copy SAEngine hands dxf2dwg is checked.",
        "The two-bay frame's drawings (no design results): plans, schedules, details.",
        dwg_case,
    ),
    Case(
        "DI3",
        "Clash benchmark and BCF round trip",
        "design",
        "A pipe through a beam (known overlap) and a duct riser beside a beam (known gap) against "
        "the frame's IFC, with a 100 mm clearance test; the clashes go out as BCF 3.0 and come "
        "back into a fresh coordination.",
        "DN100 pipe through BX1, 400 x 300 duct 50 mm from BX3; the two-bay frame.",
        clash_case,
    ),
    Case(
        "DI4",
        "Hand take-off of a two-bay frame",
        "design",
        "Concrete, formwork and excavation of a two-bay frame on isolated footings by hand, "
        "against the bill of quantities.",
        "Two-bay frame, six 2 x 2 x 0.5 m footings founded at -1.5 m, ground at 0.",
        takeoff_case,
    ),
    Case(
        "DI5",
        "Bill split by phase",
        "design",
        "The two-bay frame's bay A-B existing (its slab demolished), bay B-C new: the concrete "
        "kept, built and demolished by hand against the bill split by phase.",
        "Phases Existing and New over the two-bay frame of DI4.",
        phasing_case,
    ),
    Case(
        "DI6",
        "One room's cooling load against a published example",
        "design",
        "The fallback cooling estimate of one room on the inputs of NPTEL's worked example "
        "(Lesson 35, Q 10): the components computed alike are compared; the others are reported.",
        "3 x 6 x 3 m room, west wall and window, roof and floor exposed; 43 / 24 °C outside.",
        cooling_case,
    ),
]
