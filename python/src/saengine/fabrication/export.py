"""The fabrication exports of ``11 Exports`` (alpha 9 L10), each made only when asked (the
Exports page's rows, the CLI's ``saengine export``); the structural drawing set is not touched:

- ``Shop Drawings/``: the steel shop drawings (:mod:`saengine.drawings.sheets.shop`): one DXF
  per sheet (``SD-101 ...``), ``shop-drawings.pdf`` with every sheet, and ``shop-drawings.json``
  (what was written, the assembly and part marks with their sheets);
- ``nc/``: one DSTV NC file per part mark (:mod:`.dstv`), ``<part mark>.nc1``;
- ``bvbs/``: the BVBS records of the bar marks of the bar bending schedule (:mod:`.bvbs`), one
  file ``<schedule>.abs``; the bars are detailed as the drawings detail them (the kept design
  checks and required steel of the analysis run and the bar marks of the last drawing set:
  :func:`saengine.pipeline.drawings.kept_detailing_inputs`).

All run under the project's code pack (its ``fabrication`` and ``barSchedule`` tables, its hole
sizes) with Project Settings › Drawings › Fabrication. Each answer is ``{folder, files, notes,
problems}`` (absolute paths) and the shop drawings' ``sheets`` too; the RPC wrappers
(``fabrication/shopDrawings``, ``fabrication/nc``, ``fabrication/bvbs``) answer ``{error}`` when
nothing can be made.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SHOP_FOLDER = "11 Exports/Shop Drawings"
NC_FOLDER = "11 Exports/nc"
BVBS_FOLDER = "11 Exports/bvbs"
SHOP_PDF = "shop-drawings.pdf"
SHOP_RECORD = "shop-drawings.json"

SETTINGS_FILE = "02 Project Settings/project-settings.json"
FILES = {
    "settings": SETTINGS_FILE,
    "materials": "03 Materials/materials.json",
    "objects": "04 Objects/objects.json",
    "floorPlan": "05 Floor Plan/floor-plan.json",
    "bim": "06 BIM/bim.json",
}


class FabricationError(RuntimeError):
    """Nothing can be made: why."""


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


@dataclass
class _Project:
    root: Path
    texts: dict[str, str | None]
    settings: Any  # ProjectSettings or None
    fabrication: Any  # library.settings.Fabrication
    drawings: dict[str, Any]  # the drawings settings (dumped)
    title: dict[str, Any]  # the title block's fields (TitleInfo keys)


def _project(project_root: str | Path) -> _Project:
    from saengine.library.settings import Fabrication, ProjectSettings
    from saengine.pipeline.drawings import drawing_settings

    root = Path(project_root)
    texts = {k: _read(root / v) for k, v in FILES.items()}
    if not texts["bim"] or not texts["objects"]:
        raise FabricationError(
            "The building model (06 BIM) and the object types (04 Objects) are needed."
        )
    settings = None
    if texts["settings"]:
        try:
            settings = ProjectSettings.model_validate_json(texts["settings"])
        except ValueError:
            settings = None
    drawings, title = drawing_settings(texts["settings"])
    try:
        fabrication = Fabrication.model_validate(drawings.get("fabrication") or {})
    except ValueError:
        fabrication = Fabrication()
    info: dict[str, Any] = {}
    if settings is not None:
        project = settings.project.model_dump()
        info = {k: v for k, v in project.items() if isinstance(v, str)}
        if "name" in info:
            info["project"] = info.pop("name")
    info.update({k: v for k, v in title.items() if v is not None})
    return _Project(root, texts, settings, fabrication, drawings, info)


@contextmanager
def _pack(p: _Project) -> Iterator[None]:
    """The project's code pack in force (its overrides) while the exports are made."""
    from saengine.codes import context as code_context

    pack = code_context.pack_for(p.settings, p.root)
    with code_context.project(p.root), code_context.using(pack):
        yield


def _libraries(p: _Project) -> tuple[Any, Any, Any]:
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    bim = BuildingModel.model_validate_json(p.texts["bim"] or "")
    objects = ObjectLibrary.model_validate_json(p.texts["objects"] or "")
    materials = None
    if p.texts["materials"]:
        try:
            materials = MaterialLibrary.model_validate_json(p.texts["materials"])
        except ValueError:
            materials = None
    return bim, objects, materials


def fabrication_model(project_root: str | Path) -> tuple[Any, Any]:
    """``(model, options)``: the project's fabrication model
    (:func:`saengine.fabrication.model.build`) and the options it was made with, under the
    project's code pack."""
    p = _project(project_root)
    with _pack(p):
        return _model(p)


def _model(p: _Project) -> tuple[Any, Any]:
    from saengine.fabrication.model import FabricationOptions, build

    bim, objects, materials = _libraries(p)
    if materials is None:
        raise FabricationError("The materials (03 Materials) are needed to find the steel.")
    opts = FabricationOptions.resolve(p.fabrication)
    model = build(bim, objects, materials, opts)
    if not model.assemblies:
        raise FabricationError(
            "The building model has no structural steel members (object types of 04 Objects "
            "whose material is a steel)."
        )
    return model, opts


def _drawing_of(model: Any) -> dict[str, str]:
    """The drawing named in a part's NC header: its sheet when the shop drawings were made from
    the same marks, else the first assembly it is in."""
    out: dict[str, str] = {}
    for p, _ in model.parts():
        assemblies = model.assemblies_of(p.mark)
        out[p.mark] = assemblies[0] if assemblies else p.mark
    return out


# ─────────────────────────────────── shop drawings ───────────────────────────────────


def export_shop_drawings(project_root: str | Path) -> dict[str, Any]:
    """The steel shop drawings into ``11 Exports/Shop Drawings`` (see the module notes)."""
    from saengine.drawings.sheets.build import write_drawings
    from saengine.drawings.sheets.layout import TitleInfo
    from saengine.drawings.sheets.model import SteelSet
    from saengine.drawings.sheets.project import building_of
    from saengine.drawings.sheets.shop import sheet_of_marks, shop_categories, shop_sheets
    from saengine.drawings.sheets.standards import Standard
    from saengine.drawings.sheets.steel import steel_members

    p = _project(project_root)
    notes: list[str] = []
    with _pack(p):
        model, opts = _model(p)
        bim, objects, materials = _libraries(p)
        plan = None
        if p.texts["floorPlan"]:
            from saengine.library.floorplan import FloorPlan

            try:
                plan = FloorPlan.model_validate_json(p.texts["floorPlan"])
            except ValueError:
                notes.append("The floor plan cannot be read: the marking plans have no grids.")
        building = building_of(bim, objects, plan)
        steel = SteelSet(steel_members(bim, objects, materials))
        size = p.fabrication.sheetSize
        cats, problems = shop_categories(
            model,
            building,
            steel,
            size,
            opts.weld_symbols,
            float(p.drawings.get("planScale") or 100),
            float(p.drawings.get("elevationScale") or 50),
        )
        standard = None
        if p.drawings.get("standard"):
            standard = Standard.from_dict(p.drawings["standard"])
            problems += standard.problems
        info = TitleInfo.from_dict(p.title)
        sheets = shop_sheets(cats, size, info, standard)
    folder = p.root / SHOP_FOLDER
    written = write_drawings(sheets, folder, png=False, pdf_name=SHOP_PDF, problems=problems)
    marks = sheet_of_marks(sheets)
    record = {
        "schema": "saengine.shopDrawings/1",
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "size": size,
        "weldSymbols": opts.weld_symbols,
        "sheets": [
            {k: (Path(v).name if k in ("dxf", "png") and v else v) for k, v in row.items()}
            for row in written["sheets"]
        ],
        "assemblies": [
            {
                "mark": a.mark,
                "quantity": a.quantity,
                "members": a.members,
                "sheet": marks.get(a.mark),
            }
            for a in model.marked()
        ],
        "parts": [
            {"mark": part.mark, "quantity": n, "name": part.name, "sheet": marks.get(part.mark)}
            for part, n in model.parts()
        ],
    }
    (folder / SHOP_RECORD).write_text(json.dumps(record, indent=2), encoding="utf-8")
    files = [r["dxf"] for r in written["sheets"]] + ([written["pdf"]] if written["pdf"] else [])
    return {
        "folder": str(folder),
        "files": files,
        "sheets": written["sheets"],
        "pdf": written["pdf"],
        "assemblies": len(model.marked()),
        "parts": len(model.parts()),
        "notes": [*notes, *model.notes],
        "problems": problems,
    }


# ─────────────────────────────────── NC files ───────────────────────────────────


def export_nc(project_root: str | Path) -> dict[str, Any]:
    """One DSTV NC file per part mark into ``11 Exports/nc``."""
    from saengine.fabrication.dstv import NcHeader, write_nc_files

    p = _project(project_root)
    with _pack(p):
        model, _ = _model(p)
    number = p.title.get("number") or ""
    header = NcHeader(
        order=p.fabrication.orderNumber or number or p.title.get("project", ""),
        drawing="",
        phase=p.fabrication.phase,
        marking=p.fabrication.ncMarking,
        comment=f"SAEngine NC-DSTV {p.title.get('project', '')}".strip(),
    )
    folder = p.root / NC_FOLDER
    record = _shop_record(p.root)
    drawings = _drawing_of(model)
    if record is not None:
        # the shop drawings' sheets, when they were made with these marks: a plate's own
        # drawing, else the drawing of the first assembly it is in
        sheets = {r.get("mark"): r.get("sheet") for r in record.get("parts") or []}
        names = {r.get("mark"): r.get("name") for r in record.get("parts") or []}
        of_assembly = {r.get("mark"): r.get("sheet") for r in record.get("assemblies") or []}
        if all(names.get(part.mark) == part.name for part, _ in model.parts()):
            for part, _ in model.parts():
                assemblies = model.assemblies_of(part.mark)
                sheet = sheets.get(part.mark) or (
                    of_assembly.get(assemblies[0]) if assemblies else None
                )
                if sheet:
                    drawings[part.mark] = str(sheet)
    files = write_nc_files(model.parts(), folder, header, drawings)
    notes = list(model.notes)
    for a in model.marked():
        notes += [f"{a.mark}: {n}" for n in a.notes if "slot" in n or "profiled" in n]
    return {
        "folder": str(folder),
        "files": [str(f) for f in files],
        "notes": notes,
        "problems": [],
    }


def _shop_record(root: Path) -> dict[str, Any] | None:
    text = _read(root / SHOP_FOLDER / SHOP_RECORD)
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# ─────────────────────────────────── BVBS ───────────────────────────────────


def export_bvbs(project_root: str | Path) -> dict[str, Any]:
    """The BVBS records of the bar schedule's bar marks into ``11 Exports/bvbs``."""
    from saengine.drawings import bbs
    from saengine.drawings.detailing import detailing_model
    from saengine.fabrication.bvbs import FILE_EXTENSION, BvbsHeader, records, write_bvbs
    from saengine.pipeline.drawings import kept_detailing_inputs

    p = _project(project_root)
    inputs = kept_detailing_inputs(p.root)
    options = {
        "method": p.drawings.get("developmentLength", "simplified"),
        "curtail": p.drawings.get("curtail", True),
    }
    with _pack(p):
        try:
            detailing = detailing_model(
                p.root,
                design_report=inputs["design_report"],
                required=inputs["required"],
                options=options,
                previous=inputs["previous"],
            )
        except ValueError as error:
            raise FabricationError(f"The reinforcement could not be detailed: {error}") from error
        schedule = bbs.bar_schedule(detailing)
        if not schedule.rows:
            raise FabricationError("The bar bending schedule has no bars.")
        header = BvbsHeader(
            project=p.title.get("number") or p.title.get("project", ""),
            drawing=p.fabrication.bvbsDrawing or "BBS",
            revision=str(p.title.get("revision") or "0"),
        )
        lines, notes = records(schedule, header)
    folder = p.root / BVBS_FOLDER
    path = write_bvbs(lines, folder, header.drawing)
    for old in folder.glob(f"*{FILE_EXTENSION}"):
        if old != path:
            try:
                old.unlink()
            except OSError:
                pass
    return {
        "folder": str(folder),
        "files": [str(path)],
        "marks": len(lines),
        "notes": [*notes, *schedule.notes],
        "problems": [],
    }


# ─────────────────────────────────── RPC ───────────────────────────────────


def _rpc(fn: Any, params: dict[str, Any]) -> dict[str, Any]:
    root = params.get("projectRoot")
    if not root:
        return {"error": "No project."}
    try:
        return fn(root)
    except FabricationError as error:
        return {"error": str(error)}
    except (ValueError, OSError) as error:
        text = str(error).strip()
        return {"error": text.splitlines()[0] if text else type(error).__name__}


def rpc_shop_drawings(params: dict[str, Any]) -> dict[str, Any]:
    """``fabrication/shopDrawings`` ``{projectRoot}``: :func:`export_shop_drawings`."""
    return _rpc(export_shop_drawings, params)


def rpc_nc(params: dict[str, Any]) -> dict[str, Any]:
    """``fabrication/nc`` ``{projectRoot}``: :func:`export_nc`."""
    return _rpc(export_nc, params)


def rpc_bvbs(params: dict[str, Any]) -> dict[str, Any]:
    """``fabrication/bvbs`` ``{projectRoot}``: :func:`export_bvbs`."""
    return _rpc(export_bvbs, params)
