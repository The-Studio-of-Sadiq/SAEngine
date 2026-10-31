"""The exports of ``11 Exports``, without the workbench: the same files, in the same places, as
the Exports page writes them.

- ``pdf``: the design report, ``11 Exports/report.pdf`` (:func:`saengine.report.build_report`);
- ``ifc``: the building model, ``11 Exports/IFC/<project>.ifc`` (the building editor's Export
  IFC: :func:`saengine.rpc.handlers.building_ifc` with the building model, object types,
  materials, the project's name and, as the app's ``saengine.bim.ifc`` command fills them in,
  the substructure, the project settings and the MEP coordination model);
- ``csv``: the bill of quantities, ``11 Exports/boq.csv`` (``toCsv`` of ``boqDocument.ts``,
  ported exactly: RFC 4180, CRLF);
- ``xlsx``: the bill of quantities with its costing and embodied carbon, ``11 Exports/boq.xlsx``
  (:func:`saengine.boq.workbook.write_boq_xlsx`, priced by ``10 BOQ/rates.json`` and
  ``10 BOQ/carbon-factors.json``, the shipped sample and factors when there are none);
- ``dxf``: the structural plan of every story, ``11 Exports/Floor Plan/<story id> <name>.dxf``
  (``floorPlanDrawing`` of ``floorPlanDrawing.ts``, ported: the same layers, entities and
  sizes). The app writes the DXF with its CAD editor's writer and this module with ezdxf, so the
  files hold the same drawing but are not byte-identical (header, handles);
- ``drawings``: the structural drawing set, ``11 Exports/Drawings/`` (sheet DXFs, ``drawings.pdf``,
  ``previews/``, ``bbs.csv``; :mod:`saengine.pipeline.drawings`, as the Exports page's Generate).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from saengine.pipeline.project import Project, write_text

EXPORTS_FOLDER = "11 Exports"
FORMATS = ("pdf", "ifc", "dxf", "csv", "xlsx", "drawings")
_UNSAFE = re.compile(r'[\\/:*?"<>|]')


class ExportError(RuntimeError):
    """The export could not be written: its problems."""


def _exports(project: Project) -> Path:
    return project.root / EXPORTS_FOLDER


# ─────────────────────────────── PDF ───────────────────────────────


def export_pdf(project: Project, out: Path | None = None) -> list[Path]:
    from saengine.rpc.handlers import build_report

    result = build_report(str(project.root), str(out) if out else None)
    if result.get("problems") or not result.get("path"):
        raise ExportError(" ".join(map(str, result.get("problems") or ["no report written"])))
    return [Path(result["path"])]


# ─────────────────────────────── IFC ───────────────────────────────


def export_ifc(project: Project, out: Path | None = None) -> list[Path]:
    from saengine.rpc.handlers import building_ifc

    bim, objects = project.text("bim"), project.text("objects")
    if bim is None or objects is None:
        raise ExportError("The building model and the object types are needed for the IFC.")
    name = project.name or "Project"
    # As the app's ``saengine.bim.ifc`` command: the foundations of 09 Substructure (founded from
    # the settings' ground level) and the coordination elements of 07 MEP are in the IFC too.
    result = building_ifc(
        bim,
        objects,
        project.text("materials"),
        name,
        substructure_text=project.text("substructure"),
        settings_text=project.text("settings"),
        mep_text=project.text("mep"),
        architecture_text=project.text("architecture"),
    )
    if not result.get("text"):
        raise ExportError(
            "The IFC could not be written: " + "; ".join(result.get("problems") or [])
        )
    target = out or _exports(project) / "IFC" / f"{_UNSAFE.sub('-', name)}.ifc"
    write_text(target, result["text"])
    return [target]


# ─────────────────────────────── CSV ───────────────────────────────


def _csv_field(value: Any) -> str:
    """``csvField``: ``String(value)``, quoted when it holds a quote, comma or line break."""
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int | float):
        from saengine.fem.derive import js_json

        text = js_json(value)
    else:
        text = str(value)
    return f'"{text.replace(chr(34), chr(34) * 2)}"' if re.search(r'[",\r\n]', text) else text


def boq_csv(document: dict[str, Any]) -> str:
    """``toCsv``: one ``item`` row per item, then an ``element`` row per breakdown entry."""
    rows: list[list[Any]] = [[
        "Row", "Code", "Group", "Description", "Element", "Story", "Detail",
        "Item Quantity", "Element Quantity", "Unit",
    ]]  # fmt: skip
    for item in document.get("items", []):
        rows.append(["item", item.get("code"), item.get("group"), item.get("description"),
                     "", "", "", item.get("quantity"), "", item.get("unit")])  # fmt: skip
        for entry in item.get("breakdown") or []:
            rows.append(["element", item.get("code"), item.get("group"), item.get("description"),
                         entry.get("element"), entry.get("story"), entry.get("detail"), "",
                         entry.get("quantity"), item.get("unit")])  # fmt: skip
    return "\r\n".join(",".join(_csv_field(v) for v in row) for row in rows) + "\r\n"


def export_csv(project: Project, out: Path | None = None) -> list[Path]:
    from saengine.pipeline.run_all import parse_boq

    document = parse_boq(project.text("boq"))
    if document is None:
        raise ExportError("Measure the bill of quantities (10 BOQ) first.")
    target = out or _exports(project) / "boq.csv"
    write_text(target, boq_csv(document))
    return [target]


def boq_folder_text(project: Project, name: str) -> str | None:
    """The text of a file of ``10 BOQ`` beside ``boq.json`` (``rates.json``, ...), or None."""
    from saengine.pipeline.project import read_text

    return read_text(project.file("boq").parent / name)


def export_xlsx(project: Project, out: Path | None = None) -> list[Path]:
    from saengine.boq.costing import CARBON_FILE, RATES_FILE
    from saengine.boq.workbook import write_boq_xlsx_texts

    target = out or _exports(project) / "boq.xlsx"
    result = write_boq_xlsx_texts(
        target,
        project.text("boq"),
        boq_folder_text(project, RATES_FILE),
        boq_folder_text(project, CARBON_FILE),
        project.name or "",
    )
    if result.get("problems"):
        raise ExportError(" ".join(map(str, result["problems"])))
    return [Path(result["path"])]


# ─────────────────────────────── DXF ───────────────────────────────

LAYERS = (
    ("S-GRID", 8, "CENTER", "Grid lines"),
    ("S-GRID-IDEN", 7, None, "Grid bubbles and labels"),
    ("S-COLS", 4, None, "Columns"),
    ("S-BEAM", 3, "DASHED", "Beams (below the slab)"),
    ("S-WALL", 5, None, "Walls"),
    ("S-SLAB", 6, None, "Slab edges"),
    ("S-FNDN", 30, None, "Footings and pile caps"),
    ("S-ANNO-IDEN", 7, None, "Member labels"),
)
BUBBLE_RADIUS = 400
BUBBLE_TEXT = 350
LABEL_TEXT = 250
GRID_OVERRUN = 1500
GRID_LINETYPE_SCALE = 200
BEAM_LINETYPE_SCALE = 100


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return value


def _list(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _rectangle(width: float, depth: float) -> list[tuple[float, float]]:
    w, d = width / 2, depth / 2
    return [(-w, -d), (w, -d), (w, d), (-w, d)]


def _translate(points, origin, degrees: float = 0.0) -> list[tuple[float, float]]:
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return [(origin[0] + x * c - y * s, origin[1] + x * s + y * c) for x, y in points]


def profile_outline(profile: dict[str, Any]) -> tuple[str, Any] | None:
    """``profileOutline``: ``("polygon", points)`` or ``("circle", radius)``."""

    def n(key: str) -> float | None:
        return _num(profile.get(key))

    shape = profile.get("shape")
    if shape in ("rectangle", "rectangleHollow"):
        w, d = n("xDim"), n("yDim")
        return ("polygon", _rectangle(w, d)) if w and d else None
    if shape in ("circle", "circleHollow"):
        r = n("radius")
        return ("circle", r) if r else None
    if shape == "I":
        b, h, tw, tf = n("overallWidth"), n("overallDepth"), n("webThickness"), n("flangeThickness")
        if not (b and h and tw and tf):
            return None
        x, y, w = b / 2, h / 2, tw / 2
        return ("polygon", [(-x, -y), (x, -y), (x, -y + tf), (w, -y + tf), (w, y - tf), (x, y - tf),
                            (x, y), (-x, y), (-x, y - tf), (-w, y - tf), (-w, -y + tf),
                            (-x, -y + tf)])  # fmt: skip
    if shape == "T":
        b, h, tw, tf = n("flangeWidth"), n("depth"), n("webThickness"), n("flangeThickness")
        if not (b and h and tw and tf):
            return None
        x, y, w = b / 2, h / 2, tw / 2
        return ("polygon", [(-w, -y), (w, -y), (w, y - tf), (x, y - tf), (x, y), (-x, y),
                            (-x, y - tf), (-w, y - tf)])  # fmt: skip
    if shape == "L":
        b, h, t = n("width"), n("depth"), n("thickness")
        if not (b and h and t):
            return None
        x, y = b / 2, h / 2
        return ("polygon", [(-x, -y), (x, -y), (x, -y + t), (-x + t, -y + t), (-x + t, y), (-x, y)])
    if shape == "U":
        b, h, tw, tf = n("flangeWidth"), n("depth"), n("webThickness"), n("flangeThickness")
        if not (b and h and tw and tf):
            return None
        x, y = b / 2, h / 2
        return ("polygon", [(-x, -y), (x, -y), (x, -y + tf), (-x + tw, -y + tf), (-x + tw, y - tf),
                            (x, y - tf), (x, y), (-x, y)])  # fmt: skip
    return None


def _profile_width(profile: dict[str, Any]) -> float | None:
    outline = profile_outline(profile)
    if outline is None:
        return None
    if outline[0] == "circle":
        return 2 * outline[1]
    xs = [p[0] for p in outline[1]]
    return max(xs) - min(xs)


def _centroid(points) -> tuple[float, float]:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def stories_of(layout: Any) -> list[dict[str, Any]]:
    """``storiesOf``: the stories, lowest first."""
    stories = _list(layout.get("stories") if isinstance(layout, dict) else None)
    result = [
        {"id": s["id"], "name": s["name"] if isinstance(s.get("name"), str) and s["name"] else s["id"],
         "elevation": s["elevation"]}
        for s in stories
        if isinstance(s.get("id"), str) and _num(s.get("elevation")) is not None
    ]  # fmt: skip
    return sorted(result, key=lambda s: s["elevation"])


def floor_plan_drawing(layout: Any, objects: Any, story_id: str) -> tuple[list[dict], list[str]]:
    """``floorPlanDrawing``: the entities of the plan of ``story_id`` and the problems."""
    model = layout if isinstance(layout, dict) else {}
    grids = model.get("grids") if isinstance(model.get("grids"), dict) else {}

    def lines(axis: str) -> dict[str, float]:
        return {
            g["label"]: g["position"]
            for g in _list(grids.get(axis))
            if isinstance(g.get("label"), str) and _num(g.get("position")) is not None
        }

    x_lines, y_lines = lines("x"), lines("y")
    elevation = {s["id"]: s["elevation"] for s in stories_of(model)}
    level = elevation.get(story_id)
    types = {
        o["id"]: o
        for o in _list(objects.get("objects") if isinstance(objects, dict) else None)
        if isinstance(o.get("id"), str)
    }
    entities: list[dict[str, Any]] = []
    problems: list[str] = []
    xs, ys = list(x_lines.values()), list(y_lines.values())
    min_x, max_x = (min(xs), max(xs)) if xs else (0, 0)
    min_y, max_y = (min(ys), max(ys)) if ys else (0, 0)

    def bubble(label: str, center) -> None:
        entities.append({"kind": "circle", "layer": "S-GRID-IDEN", "center": center,
                         "radius": BUBBLE_RADIUS})  # fmt: skip
        entities.append({"kind": "text", "layer": "S-GRID-IDEN", "position": center,
                         "height": BUBBLE_TEXT, "text": label})  # fmt: skip

    for label, x in x_lines.items():
        y0, y1 = min_y - GRID_OVERRUN, max_y + GRID_OVERRUN
        entities.append({"kind": "line", "layer": "S-GRID", "start": (x, y0), "end": (x, y1),
                         "linetypeScale": GRID_LINETYPE_SCALE})  # fmt: skip
        bubble(label, (x, y0 - BUBBLE_RADIUS))
        bubble(label, (x, y1 + BUBBLE_RADIUS))
    for label, y in y_lines.items():
        x0, x1 = min_x - GRID_OVERRUN, max_x + GRID_OVERRUN
        entities.append({"kind": "line", "layer": "S-GRID", "start": (x0, y), "end": (x1, y),
                         "linetypeScale": GRID_LINETYPE_SCALE})  # fmt: skip
        bubble(label, (x0 - BUBBLE_RADIUS, y))
        bubble(label, (x1 + BUBBLE_RADIUS, y))
    if level is None:
        return entities, problems

    def point(member: dict[str, Any], value: Any):
        p = value if isinstance(value, dict) else None
        x = x_lines.get(p.get("x")) if p else None
        y = y_lines.get(p.get("y")) if p else None
        if x is None or y is None:
            where = f"{p.get('x')}-{p.get('y')}" if p else "?"
            problems.append(f"{member.get('id')}: grid point {where} does not exist")
            return None
        return (x + (_num(p.get("dx")) or 0), y + (_num(p.get("dy")) or 0))

    def type_of(member: dict[str, Any]) -> dict[str, Any] | None:
        found = types.get(member["type"]) if isinstance(member.get("type"), str) else None
        if found is None:
            problems.append(f"{member.get('id')}: unknown object type '{member.get('type')}'")
        return found

    def label(member: dict[str, Any], position) -> None:
        if isinstance(member.get("id"), str):
            entities.append({"kind": "text", "layer": "S-ANNO-IDEN", "position": position,
                             "height": LABEL_TEXT, "text": member["id"]})  # fmt: skip

    def spans(member: dict[str, Any]) -> bool:
        base, top = elevation.get(member.get("base")), elevation.get(member.get("top"))
        return base is not None and top is not None and base < level <= top

    def band(layer: str, start, end, width: float, scale: float | None = None):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if not length:
            return None
        nx, ny = -dy / length * width / 2, dx / length * width / 2
        points = [(start[0] + nx, start[1] + ny), (end[0] + nx, end[1] + ny),
                  (end[0] - nx, end[1] - ny), (start[0] - nx, start[1] - ny)]  # fmt: skip
        entities.append({"kind": "polyline", "layer": layer, "closed": True, "points": points,
                         "linetypeScale": scale})  # fmt: skip
        return points

    for slab in (s for s in _list(model.get("slabs")) if s.get("story") == story_id):
        found = type_of(slab)
        corners = [point(slab, c) for c in _list(slab.get("boundary"))]
        if not found or len(corners) < 3 or any(c is None for c in corners):
            continue
        entities.append({"kind": "polyline", "layer": "S-SLAB", "points": corners, "closed": True})
        thickness = _num(found.get("thickness"))
        text = f"{slab['id']} ({_js(thickness)})" if thickness else str(slab.get("id"))
        entities.append({"kind": "text", "layer": "S-ANNO-IDEN", "position": _centroid(corners),
                         "height": LABEL_TEXT, "text": text})  # fmt: skip
    for beam in (b for b in _list(model.get("beams")) if b.get("story") == story_id):
        found = type_of(beam)
        start, end = point(beam, beam.get("start")), point(beam, beam.get("end"))
        profile = found.get("profile") if found else None
        width = _profile_width(profile) if isinstance(profile, dict) else None
        if not start or not end or not width:
            continue
        band("S-BEAM", start, end, width, BEAM_LINETYPE_SCALE)
        label(beam, _centroid([start, end]))
    for wall in (w for w in _list(model.get("walls")) if spans(w)):
        found = type_of(wall)
        start, end = point(wall, wall.get("start")), point(wall, wall.get("end"))
        thickness = _num(found.get("thickness")) if found else None
        if not start or not end or not thickness:
            continue
        band("S-WALL", start, end, thickness)
    for column in (c for c in _list(model.get("columns")) if spans(c)):
        found = type_of(column)
        at = point(column, column.get("at"))
        profile = found.get("profile") if found else None
        outline = profile_outline(profile) if isinstance(profile, dict) else None
        if not at or not outline:
            continue
        if outline[0] == "circle":
            entities.append(
                {"kind": "circle", "layer": "S-COLS", "center": at, "radius": outline[1]}
            )
        else:
            points = _translate(outline[1], at, _num(column.get("rotation")) or 0)
            entities.append(
                {"kind": "polyline", "layer": "S-COLS", "points": points, "closed": True}
            )
    for footing in (f for f in _list(model.get("footings")) if f.get("story") == story_id):
        found = type_of(footing)
        at = point(footing, footing.get("at"))
        length = _num(found.get("length")) if found else None
        width = _num(found.get("width")) if found else None
        if not at or not length or not width:
            continue
        points = _translate(_rectangle(length, width), at, _num(footing.get("rotation")) or 0)
        entities.append({"kind": "polyline", "layer": "S-FNDN", "points": points, "closed": True})
        label(footing, at)
    return entities, problems


def _js(value: float | None) -> str:
    from saengine.fem.derive import js_json

    return js_json(value)


def drawing_dxf(entities: list[dict[str, Any]]) -> str:
    """The DXF text of a drawing (R2013, millimetres), with the floor plan's layers, the two
    linetypes it uses and the drawing sheets' TrueType text style, nothing else: no text styles
    whose fonts a CAD program would have to substitute (docs/drawings-layers.md)."""
    import io

    import ezdxf
    from ezdxf.enums import TextEntityAlignment
    from ezdxf.tools.standards import linetypes

    from saengine.drawings.sheets.layout import FONT, FONT_FAMILY

    doc = ezdxf.new("R2013", setup=False, units=ezdxf.units.MM)
    used = {linetype for _, _, linetype, _ in LAYERS if linetype}
    # ezdxf's definitions, as the app's entity linetype scales (200, 100) expect them
    for name, description, pattern in linetypes():
        if name in used:
            doc.linetypes.add(name, pattern, description=description)
    style = doc.styles.get("Standard")
    style.dxf.font = FONT
    style.set_extended_font_data(FONT_FAMILY)
    doc.header["$TEXTSTYLE"] = "Standard"
    for name, color, linetype, description in LAYERS:
        layer = doc.layers.add(name, color=color, linetype=linetype or "Continuous")
        layer.description = description
    space = doc.modelspace()
    for e in entities:
        attribs: dict[str, Any] = {"layer": e["layer"]}
        if e.get("linetypeScale"):
            attribs["ltscale"] = e["linetypeScale"]
        match e["kind"]:
            case "line":
                space.add_line(e["start"], e["end"], dxfattribs=attribs)
            case "circle":
                space.add_circle(e["center"], e["radius"], dxfattribs=attribs)
            case "polyline":
                space.add_lwpolyline(e["points"], close=e.get("closed", False), dxfattribs=attribs)
            case "text":
                text = space.add_text(e["text"], height=e["height"], dxfattribs=attribs)
                text.set_placement(e["position"], align=TextEntityAlignment.MIDDLE_CENTER)
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue()


def export_dxf(project: Project, out: Path | None = None) -> list[Path]:
    """Every story's plan to ``11 Exports/Floor Plan`` (or the folder ``out``)."""
    if project.type != "building":
        raise ExportError("DXF floor plans are exported from the floor plan of a building project.")
    try:
        layout = json.loads(project.text("floorPlan") or "")
    except ValueError as error:
        raise ExportError(f"The floor plan cannot be read: {error}") from error
    if not isinstance(layout, dict) or layout.get("schema") != "saengine.floorPlan/1":
        raise ExportError("Draw the floor plan (5 Floor Plan) first.")
    try:
        objects = json.loads(project.text("objects") or "null")
    except ValueError:
        objects = None
    folder = out or _exports(project) / "Floor Plan"
    written = []
    for story in stories_of(layout):
        entities, _ = floor_plan_drawing(layout, objects, story["id"])
        name = _UNSAFE.sub("-", f"{story['id']} {story['name']}")
        target = folder / f"{name}.dxf"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(drawing_dxf(entities), encoding="utf-8", newline="")
        written.append(target)
    return written


# ─────────────────────────────── drawings ───────────────────────────────


def export_drawings(
    project: Project, out: Path | None = None, size: str | None = None
) -> list[Path]:
    """The structural drawings (:mod:`saengine.pipeline.drawings`): generated into
    ``11 Exports/Drawings`` as the Exports page generates them (its record of the set, so the
    app shows them current), then, with ``out``, copied into that folder (the sheet DXFs, the PDF
    set, the previews and the bar bending schedule)."""
    import shutil

    from saengine.pipeline.drawings import DrawingsError, generate

    if project.type != "building":
        raise ExportError("Drawings are generated from the building model of a building project.")
    try:
        answer = generate(project.root, size=size)
    except DrawingsError as error:
        raise ExportError(str(error)) from error
    import sys

    # Failing detailing and design checks: the set is written, but not ready to issue.
    for problem in answer.get("problems") or []:
        if isinstance(problem, dict) and problem.get("severity") == "error":
            print(
                f"saengine export: to resolve before issue: {problem['message']}", file=sys.stderr
            )
    written = [Path(s["dxf"]) for s in answer["sheets"] if s.get("dxf")]
    written += [Path(p) for p in (answer.get("pdf"), answer.get("bbsCsv")) if p]
    written += [Path(s["png"]) for s in answer["sheets"] if s.get("png")]
    if out is None:
        return written
    folder = project.root / "11 Exports" / "Drawings"
    copies = []
    for path in written:
        target = out / path.relative_to(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copies.append(target)
    return copies


def export(project: Project, fmt: str, out: Path | None = None, **options: Any) -> list[Path]:
    """Writes export ``fmt`` (:data:`FORMATS`) of ``project``; the files written. ``options``:
    ``size`` (A1, A2, A3) for the drawings."""
    if fmt == "drawings":
        return export_drawings(project, out, options.get("size"))
    writers = {"pdf": export_pdf, "ifc": export_ifc, "csv": export_csv, "xlsx": export_xlsx,
               "dxf": export_dxf}  # fmt: skip
    if fmt not in writers:
        raise ValueError(f"unknown export format: {fmt}")
    return writers[fmt](project, out)
