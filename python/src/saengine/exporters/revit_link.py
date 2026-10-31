"""The Revit link: a neutral structural exchange file, written for Revit and read back with a
preview of the changes before any is applied.

SAEngine never loads Revit's API. A separate add-in (its own project and licence) reads and
writes the exchange file inside Revit; this module only knows the file:

- :func:`export_exchange_file` writes ``11 Exports/Revit/<project>.exchange.json``: the levels,
  the grid lines, the materials, the sections (one per object type of 04 Objects), the
  analytical elements of the building model (columns, beams, walls, slabs, footings, braces and
  the members and areas of special structures) and the designed reinforcement (the bars of the
  3D cages the drawings detail, :func:`saengine.pipeline.drawings.rebar_cages`), each element
  with the Revit id it was last linked to;
- :func:`preview_import` reads a file the add-in wrote back and lists what changed in Revit
  against the project now: levels and grid lines moved or added, elements added, moved,
  resized (another section) or deleted. Each change says whether SAEngine can take it and why
  not;
- :func:`apply_import` applies the changes the engineer picked to the floor plan (05 Floor
  Plan, the part that owns the layout; the building model is rebuilt from it as usual), keeps
  a copy of the floor plan as it was, and records the Revit ids in ``revit-link.json``.

What SAEngine does not take back: reinforcement (it comes from the design, never from a
drawing tool), braces and other building-model additions, special-structure members, sloped
or slanted members, and sections no object type matches. The preview lists them as not
applicable with the reason.

The file format (``saengine.structuralExchange/1``) is plain JSON in mm, degrees and MPa; its
fields are documented in ``docs/revit-link.md``.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_ID = "saengine.structuralExchange/1"
LINK_SCHEMA_ID = "saengine.revitLink/1"
#: Where the exchange files go, inside ``11 Exports``.
EXPORT_FOLDER = "Revit"
#: The exchange file written for Revit: ``<project>.exchange.json``.
EXCHANGE_SUFFIX = ".exchange.json"
#: The ids SAEngine and Revit gave the same element, kept beside the exchange file.
LINK_FILE = "revit-link.json"
#: The floor plan as it was before the last import, kept beside the exchange file.
BACKUP_FILE = "floor-plan.before-revit-import.json"

#: Two points closer than this are the same [mm] (Revit works in feet: 1 mm covers rounding).
TOLERANCE = 1.0
#: An element end within this of a level is on it [mm].
LEVEL_TOLERANCE = 5.0
#: Rotations closer than this are the same [degrees].
ANGLE_TOLERANCE = 0.5

#: The element kinds of the exchange file, as the building model names them.
KINDS = ("column", "beam", "wall", "slab", "footing", "brace", "member", "area")
#: The kinds the floor plan holds (and so the kinds SAEngine can take back from Revit).
PLAN_KINDS = {
    "column": "columns",
    "beam": "beams",
    "wall": "walls",
    "slab": "slabs",
    "footing": "footings",
}
#: The object-type kinds each element kind may use.
_TYPE_KINDS = {
    "column": ("column",),
    "beam": ("beam",),
    "wall": ("wall",),
    "slab": ("slab",),
    "footing": ("footing", "pileCap"),
    "brace": ("brace", "beam", "column"),
    "member": ("beam", "column", "brace"),
    "area": ("slab", "wall"),
}


class RevitLinkError(ValueError):
    """The project cannot be exported, or the file cannot be read as an exchange file."""


# ───────────────────────────────────────── export ─────────────────────────────────────────


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _r(value: float) -> float:
    return round(float(value), 1)


def _pt(p: Any, z: float | None = None) -> list[float]:
    if z is None:
        return [_r(p[0]), _r(p[1]), _r(p[2])]
    return [_r(p[0]), _r(p[1]), _r(z)]


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("saengine")
    except Exception:  # noqa: BLE001 - a source checkout has no installed metadata
        return "dev"


def _section(obj: Any) -> dict[str, Any]:
    """One object type as an exchange section: its kind, material and dimensions."""
    out: dict[str, Any] = {"id": obj.id, "name": obj.name, "kind": obj.kind}
    out["material"] = obj.material
    profile = getattr(obj, "profile", None)
    if profile is not None:
        out["profile"] = profile.model_dump(mode="json", exclude_none=True)
    for key in ("thickness", "length", "width", "waistThickness"):
        value = getattr(obj, key, None)
        if isinstance(value, int | float):
            out[key] = float(value)
    if obj.kind == "wall":
        out["structural"] = bool(obj.structural)
    if obj.kind == "footing":
        out["footingType"] = obj.footingType
    reinforcement = getattr(obj, "reinforcement", None)
    if reinforcement is not None:
        out["reinforcement"] = reinforcement.model_dump(mode="json", exclude_none=True)
    return out


def _material(m: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"id": m.id, "name": m.name, "category": m.category.value}
    mech = m.mechanical
    if mech.E is not None:
        out["E"] = mech.E
    if mech.nu is not None:
        out["nu"] = mech.nu
    if mech.density is not None:
        out["density"] = mech.density
    if m.concrete is not None:
        out["fc"] = m.concrete.fc
    if m.steel is not None:
        out["fy"] = m.steel.fy
        if m.steel.fu is not None:
            out["fu"] = m.steel.fu
        if m.steel.grade:
            out["grade"] = m.steel.grade
    return out


def _story_at(stories: list[Any], elevation: float) -> str | None:
    for s in stories:
        if abs(s.elevation - elevation) <= LEVEL_TOLERANCE:
            return s.id
    return None


def _elements(building: Any) -> list[dict[str, Any]]:
    """The building model's elements as exchange elements (analytical lines and outlines)."""
    stories = sorted(building.stories, key=lambda s: s.elevation)
    out: list[dict[str, Any]] = []
    for e in building.elements:
        owner = "floorPlan" if e.source else "buildingModel"
        base: dict[str, Any] = {"id": e.id, "kind": e.kind, "section": e.type, "owner": owner}
        if e.kind == "column":
            base |= {
                "curve": [_pt(e.position + [e.bottom]), _pt(e.position + [e.top])],
                "rotation": _r(e.rotation),
                "baseLevel": _story_at(stories, e.bottom),
                "topLevel": _story_at(stories, e.top),
            }
        elif e.kind == "beam":
            base |= {
                "curve": [_pt(e.start, e.elevation), _pt(e.end, e.elevation)],
                "level": _story_at(stories, e.elevation),
                "reference": "top",
            }
        elif e.kind == "wall":
            base |= {
                "curve": [_pt(e.start, e.bottom), _pt(e.end, e.bottom)],
                "bottom": _r(e.bottom),
                "top": _r(e.top),
                "baseLevel": _story_at(stories, e.bottom),
                "topLevel": _story_at(stories, e.top),
            }
        elif e.kind == "slab":
            base |= {
                "outline": [_pt(p, e.elevation) for p in e.boundary],
                "level": _story_at(stories, e.elevation),
                "reference": "top",
            }
        elif e.kind == "footing":
            base |= {
                "point": _pt(e.position, e.elevation),
                "rotation": _r(e.rotation),
                "level": _story_at(stories, e.elevation),
                "reference": "top",
            }
        elif e.kind == "member":
            base |= {"curve": [_pt(e.start), _pt(e.end)], "rotation": _r(e.rotation)}
        elif e.kind == "area":
            base |= {
                "outline": [_pt(p) for p in e.outline],
                "openings": [[_pt(p) for p in loop] for loop in e.openings],
            }
        else:  # solid blocks have no analytical counterpart in Revit
            continue
        out.append(base)
    for m in building.additions.members:
        out.append(
            {
                "id": m.id,
                "kind": "brace",
                "section": m.type,
                "owner": "buildingModel",
                "curve": [_pt((m.x1, m.y1, m.z1)), _pt((m.x2, m.y2, m.z2))],
            }
        )
    hosts = {e.id: e for e in building.elements}
    openings: dict[str, list[list[list[float]]]] = {}
    for o in building.additions.slabOpenings:
        slab = hosts.get(o.host)
        if slab is None or slab.kind != "slab":
            continue
        a = math.radians(o.rotation)
        corners = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            dx, dy = sx * o.xDim / 2, sy * o.yDim / 2
            x = o.x + dx * math.cos(a) - dy * math.sin(a)
            y = o.y + dx * math.sin(a) + dy * math.cos(a)
            corners.append(_pt((x, y), slab.elevation))
        openings.setdefault(o.host, []).append(corners)
    for element in out:
        if element["id"] in openings and element["kind"] == "slab":
            element["openings"] = openings[element["id"]]
    return out


def _rebar(root: Path, building: Any, objects: Any, notes: list[str]) -> list[dict[str, Any]]:
    """The designed bars of the beams and columns, as the 3D cages draw them."""
    from saengine.pipeline.drawings import rebar_cages

    try:
        cages = rebar_cages(root, check=False)
    except Exception as error:  # noqa: BLE001 - the model goes over without its bars
        notes.append(f"Reinforcement not exported: {error}")
        return []
    types = {o.id: o for o in objects.objects}
    elements = {e.id: e for e in building.elements}
    counters: dict[str, int] = {}
    out = []
    for bar in cages.get("bars") or []:
        lines = [line for line in bar.get("lines") or [] if len(line) >= 2]
        if not lines:
            continue
        host = str(bar.get("member") or bar.get("element"))
        n = counters.get(host, 0)
        counters[host] = n + 1
        element = elements.get(host)
        type_ = types.get(element.type) if element is not None else None
        reinforcement = getattr(type_, "reinforcement", None)
        entry = {
            "id": f"rebar:{host}/{n}",
            "host": host,
            "mark": str(bar.get("mark") or ""),
            "role": str(bar.get("role") or ""),
            "dia": float(bar.get("dia") or 0.0),
            "shape": str(bar.get("shape") or ""),
            "length": _r(bar.get("length") or 0.0),
            "count": len(lines),
            "transverse": bool(bar.get("transverse")),
            "lines": [[_pt(p) for p in line] for line in lines],
        }
        if reinforcement is not None:
            entry["material"] = reinforcement.material
        out.append(entry)
    for note in cages.get("notes") or []:
        notes.append(f"Reinforcement: {note}")
    if not out:
        notes.append(
            "No designed reinforcement to export: run the design and generate the drawings "
            "(11 Exports) to detail the bars."
        )
    return out


def _read_link(folder: Path) -> dict[str, Any]:
    try:
        link = json.loads((folder / LINK_FILE).read_text("utf-8"))
    except (OSError, ValueError):
        return {"schema": LINK_SCHEMA_ID, "ids": {}}
    if not isinstance(link, dict) or not isinstance(link.get("ids"), dict):
        return {"schema": LINK_SCHEMA_ID, "ids": {}}
    return link


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent="\t", ensure_ascii=False) + "\n", "utf-8")


def _project(project: str | Path) -> Any:
    from saengine.pipeline.project import ProjectError, open_project

    try:
        return open_project(project)
    except ProjectError as error:
        raise RevitLinkError(str(error)) from error


def _current(p: Any) -> tuple[Any, Any, Any, dict[str, Any] | None, list[str]]:
    """The project as it is now: the building model generated from the floor plan as it is on
    disk (so a building model older than the plan does not show as Revit changes), its object
    types and materials, the floor plan's JSON, and notes."""
    from pydantic import ValidationError

    from saengine.library.bim import BuildingModel, generate, source_stamp
    from saengine.library.floorplan import FloorPlan
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    texts = p.texts(("bim", "objects", "materials"))
    notes: list[str] = []
    try:
        objects = ObjectLibrary.model_validate_json(texts["objects"] or "{}")
        materials = MaterialLibrary.model_validate_json(texts["materials"] or "{}")
        building = BuildingModel.model_validate_json(texts["bim"]) if texts["bim"] else None
    except ValidationError as error:
        raise RevitLinkError(f"{p.name}: a part has errors: {error.errors()[0]['msg']}") from error
    plan_json: dict[str, Any] | None = None
    plan_text = p.text("floorPlan") if p.type == "building" else None
    if plan_text:
        try:
            plan = FloorPlan.model_validate_json(plan_text)
            plan_json = json.loads(plan_text)
            stamp = source_stamp(plan_text)
            if building is not None and building.source and building.source.floorPlan != stamp:
                notes.append(
                    "The building model (06 BIM) is older than the floor plan: the exchange "
                    "follows the floor plan as it is now."
                )
            building = generate(plan, stamp, building)
        except (ValidationError, ValueError, KeyError) as error:
            notes.append(f"The floor plan could not be read ({error}): the building model is used.")
            plan_json = None
    if building is None:
        raise RevitLinkError(f"{p.name}: no building model (06 BIM) to exchange")
    if not building.elements and not building.additions.members:
        raise RevitLinkError(f"{p.name}: the building model has no elements yet")
    return building, objects, materials, plan_json, notes


def build_exchange(project: str | Path, *, rebar: bool = True) -> dict[str, Any]:
    """The exchange document of the project at ``project`` (its folder or ``.saengine`` file);
    with ``rebar``, the designed reinforcement too."""
    p = _project(project)
    building, objects, materials, plan_json, notes = _current(p)
    link = _read_link(p.folder("exports") / EXPORT_FOLDER)
    revit_ids: dict[str, str] = link["ids"]
    grids: list[dict[str, Any]] = []
    if plan_json is not None:
        xs = [g["position"] for g in plan_json.get("grids", {}).get("x", [])]
        ys = [g["position"] for g in plan_json.get("grids", {}).get("y", [])]
        lo_x, hi_x = (min(xs), max(xs)) if xs else (0.0, 0.0)
        lo_y, hi_y = (min(ys), max(ys)) if ys else (0.0, 0.0)
        for axis, lines in (
            ("x", plan_json["grids"].get("x", [])),
            ("y", plan_json["grids"].get("y", [])),
        ):
            for g in lines:
                pos = float(g["position"])
                start, end = (
                    ((pos, lo_y), (pos, hi_y)) if axis == "x" else ((lo_x, pos), (hi_x, pos))
                )
                grids.append(
                    {
                        "id": f"{axis}:{g['label']}",
                        "name": g["label"],
                        "axis": axis,
                        "position": _r(pos),
                        "start": [_r(v) for v in start],
                        "end": [_r(v) for v in end],
                    }
                )
    levels = [
        {"id": s.id, "name": s.name, "elevation": _r(s.elevation)}
        for s in sorted(building.stories, key=lambda s: s.elevation)
    ]
    elements = _elements(building)
    used = {e["section"] for e in elements}
    sections = [_section(o) for o in objects.objects if o.id in used]
    used_materials = {s["material"] for s in sections}
    used_materials |= {
        s["reinforcement"]["material"]
        for s in sections
        if s.get("reinforcement", {}).get("material")
    }
    mats = [_material(m) for m in materials.materials if m.id in used_materials]
    for collection in (levels, grids, elements):
        for item in collection:
            if item["id"] in revit_ids:
                item["revitId"] = revit_ids[item["id"]]
    bars = _rebar(p.root, building, objects, notes) if rebar else []
    return {
        "schema": SCHEMA_ID,
        "origin": {"application": "SAEngine", "version": _version(), "written": _now()},
        "project": {"name": p.name, "type": p.type},
        "units": {"length": "mm", "angle": "deg", "stress": "MPa", "density": "kg/m3"},
        "scope": list(KINDS),
        "levels": levels,
        "grids": grids,
        "materials": mats,
        "sections": sections,
        "elements": elements,
        "rebar": bars,
        "notes": notes,
    }


def export_exchange_file(project: str | Path, out_path: str | Path | None = None) -> dict[str, Any]:
    """Writes the exchange document (:func:`build_exchange`) to ``out_path`` (default
    ``11 Exports/Revit/<project>.exchange.json``): ``{"path", "counts", "notes"}``."""
    p = _project(project)
    document = build_exchange(p.root)
    target = (
        Path(out_path)
        if out_path
        else p.folder("exports") / EXPORT_FOLDER / f"{p.name}{EXCHANGE_SUFFIX}"
    )
    if target.is_dir():
        target = target / f"{p.name}{EXCHANGE_SUFFIX}"
    _write_json(target, document)
    folder = p.folder("exports") / EXPORT_FOLDER
    link = _read_link(folder)
    link["lastExport"] = document["origin"]["written"]
    link["schema"] = LINK_SCHEMA_ID
    _write_json(folder / LINK_FILE, link)
    counts: dict[str, int] = {"levels": len(document["levels"]), "grids": len(document["grids"])}
    for e in document["elements"]:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    counts["rebarSets"] = len(document["rebar"])
    return {"path": str(target), "counts": counts, "notes": document["notes"]}


# ───────────────────────────────────────── import ─────────────────────────────────────────


def read_exchange(path: str | Path) -> dict[str, Any]:
    """The exchange document at ``path``, checked for its schema and units."""
    try:
        document = json.loads(Path(path).read_text("utf-8-sig"))
    except OSError as error:
        raise RevitLinkError(f"cannot read {Path(path).name}: {error}") from error
    except ValueError as error:
        raise RevitLinkError(f"{Path(path).name} is not JSON: {error}") from error
    if not isinstance(document, dict) or document.get("schema") != SCHEMA_ID:
        raise RevitLinkError(f"{Path(path).name} is not a SAEngine exchange file ({SCHEMA_ID})")
    units = document.get("units") or {}
    if units.get("length", "mm") != "mm" or units.get("angle", "deg") != "deg":
        raise RevitLinkError("the exchange file must be in mm and degrees")
    for key in ("levels", "grids", "elements", "sections", "rebar"):
        if not isinstance(document.get(key, []), list):
            raise RevitLinkError(f"the exchange file's {key} is not a list")
    return document


def _close(a: Any, b: Any, tol: float = TOLERANCE) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return all(abs(float(u) - float(v)) <= tol for u, v in zip(a, b, strict=False)) and len(
        a
    ) == len(b)


def _same_curve(a: list[Any] | None, b: list[Any] | None, reversible: bool) -> bool:
    if not a or not b or len(a) != 2 or len(b) != 2:
        return a == b
    if _close(a[0], b[0]) and _close(a[1], b[1]):
        return True
    return reversible and _close(a[0], b[1]) and _close(a[1], b[0])


def _same_outline(a: list[Any] | None, b: list[Any] | None) -> bool:
    """Two closed outlines are the same with any start corner and either direction."""
    if not a or not b or len(a) != len(b):
        return not a and not b
    n = len(a)
    for loop in (b, list(reversed(b))):
        for shift in range(n):
            if all(_close(a[i], loop[(i + shift) % n]) for i in range(n)):
                return True
    return False


def _fmt(p: Any) -> str:
    return "(" + ", ".join(f"{float(v):.0f}" for v in p) + ")"


def _geometry_changes(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    """What moved: one entry per changed field, ``{"field", "from", "to"}`` as text."""
    out = []
    kind = old["kind"]
    linear = kind in ("column", "beam", "wall", "brace", "member")
    if linear and not _same_curve(old.get("curve"), new.get("curve"), kind != "column"):
        a, b = old.get("curve") or [], new.get("curve") or []
        out.append(
            {
                "field": "location",
                "from": " to ".join(map(_fmt, a)),
                "to": " to ".join(map(_fmt, b)),
            }
        )
    if kind == "wall":
        for key in ("bottom", "top"):
            a, b = float(old.get(key, 0)), float(new.get(key, old.get(key, 0)))
            if abs(a - b) > TOLERANCE:
                out.append({"field": key, "from": f"{a:.0f}", "to": f"{b:.0f}"})
    planar = kind in ("slab", "area")
    if planar and not _same_outline(old.get("outline"), new.get("outline")):
        out.append(
            {
                "field": "outline",
                "from": f"{len(old.get('outline') or [])} corners",
                "to": f"{len(new.get('outline') or [])} corners",
            }
        )
    if kind == "footing" and not _close(old.get("point"), new.get("point")):
        out.append(
            {
                "field": "location",
                "from": _fmt(old.get("point") or []),
                "to": _fmt(new.get("point") or []),
            }
        )
    if kind in ("column", "footing", "member"):
        a, b = float(old.get("rotation") or 0), float(new.get("rotation") or 0)
        if abs(((a - b + 180) % 360) - 180) > ANGLE_TOLERANCE:
            out.append({"field": "rotation", "from": f"{a:g}°", "to": f"{b:g}°"})
    return out


def _section_of(document: dict[str, Any], section_id: str | None) -> dict[str, Any] | None:
    for s in document.get("sections") or []:
        if s.get("id") == section_id:
            return s
    return None


def _dims(entry: dict[str, Any]) -> tuple[Any, ...] | None:
    """The dimensions a section is matched by (profile sizes, or thickness and plan size)."""
    profile = entry.get("profile")
    if isinstance(profile, dict):
        shape = profile.get("shape")
        keys = {
            "rectangle": ("xDim", "yDim"),
            "circle": ("radius",),
            "I": ("overallWidth", "overallDepth", "webThickness", "flangeThickness"),
        }.get(shape)
        if keys and all(isinstance(profile.get(k), int | float) for k in keys):
            return (str(shape), *(float(profile[k]) for k in keys))
        return None
    keys = ("thickness", "length", "width")
    values = tuple(float(entry[k]) for k in keys if isinstance(entry.get(k), int | float))
    return values or None


def resolve_section(
    kind: str, section_id: str | None, incoming: dict[str, Any], objects: Any
) -> tuple[str | None, str]:
    """The object type of 04 Objects an element from Revit uses: by id, by name, or by its
    dimensions; ``(id, how)`` or ``(None, why not)``."""
    allowed = _TYPE_KINDS.get(kind, ())
    candidates = [o for o in objects.objects if o.kind in allowed]
    for o in candidates:
        if o.id == section_id:
            return o.id, "same object type"
    entry = _section_of(incoming, section_id) or {}
    name = str(entry.get("name") or section_id or "").strip().lower()
    for o in candidates:
        if name and o.name.strip().lower() == name:
            return o.id, f"object type named {o.name}"
    dims = _dims(entry) if entry else None
    if dims is not None:
        for o in candidates:
            mine = _dims(_section(o))
            if mine is None or len(mine) != len(dims):
                continue
            if all(
                a == b if isinstance(a, str) or isinstance(b, str) else abs(a - b) <= TOLERANCE
                for a, b in zip(mine, dims, strict=True)
            ):
                return o.id, f"object type {o.name} of the same size"
    label = entry.get("name") or section_id or "?"
    return None, f"no {kind} type in 04 Objects matches the Revit type '{label}': add one first"


def _match(
    incoming: dict[str, Any], current: dict[str, dict[str, Any]], by_revit: dict[str, str]
) -> str | None:
    """The SAEngine id of an incoming element: its own id when SAEngine wrote it, else the id
    linked to its Revit id."""
    if incoming.get("id") in current:
        return str(incoming["id"])
    revit = incoming.get("revitId")
    if revit and by_revit.get(str(revit)) in current:
        return by_revit[str(revit)]
    return None


def _label(e: dict[str, Any]) -> str:
    kind = e.get("kind", "element")
    name = e.get("id") or e.get("revitId") or "?"
    return f"{kind} {name}"


def preview_import(project: str | Path, path: str | Path) -> dict[str, Any]:
    """The changes in the exchange file at ``path`` (written back by the Revit add-in) against
    the project now: ``{"changes": [...], "counts", "notes", "source"}``. Each change is
    ``{"id", "action": "add"|"modify"|"remove", "target": "level"|"grid"|"element",
    "kind", "ref", "revitId", "title", "details": [{"field", "from", "to"}], "applicable",
    "reason"}``."""
    p = _project(project)
    incoming = read_exchange(path)
    current = build_exchange(p.root, rebar=False)
    _, objects, _, plan_json, notes = _current(p)
    link = _read_link(p.folder("exports") / EXPORT_FOLDER)
    by_revit = {str(v): k for k, v in link["ids"].items()}
    plan_ok = plan_json is not None
    no_plan = "only the floor plan of a building takes changes back (this project has none)"
    changes: list[dict[str, Any]] = []
    taken_ids: set[str] = set()

    def add(change: dict[str, Any]) -> None:
        change.setdefault("details", [])
        change.setdefault("applicable", True)
        change.setdefault("reason", None)
        key = f"{change['target']}:{change['action']}:{change.get('ref') or change.get('revitId')}"
        n, unique = 2, key
        while unique in taken_ids:
            unique, n = f"{key}#{n}", n + 1
        taken_ids.add(unique)
        change["id"] = unique
        changes.append(change)

    # Levels.
    levels = {lv["id"]: lv for lv in current["levels"]}
    seen_levels: set[str] = set()
    for lv in incoming.get("levels") or []:
        match = _match(lv, levels, by_revit) or next(
            (k for k, v in levels.items() if v["name"] == lv.get("name")), None
        )
        elevation = float(lv.get("elevation") or 0.0)
        if match is None:
            add(
                {
                    "action": "add",
                    "target": "level",
                    "kind": "level",
                    "ref": lv.get("id") or lv.get("name"),
                    "revitId": lv.get("revitId"),
                    "title": f"New level {lv.get('name')} at {elevation:.0f} mm",
                    "applicable": plan_ok,
                    "reason": None if plan_ok else no_plan,
                    "data": {
                        "name": str(lv.get("name") or lv.get("id") or "Level"),
                        "elevation": elevation,
                    },
                }
            )
            continue
        seen_levels.add(match)
        old = levels[match]
        if abs(old["elevation"] - elevation) > TOLERANCE:
            add(
                {
                    "action": "modify",
                    "target": "level",
                    "kind": "level",
                    "ref": match,
                    "revitId": lv.get("revitId"),
                    "title": f"Level {old['name']} moved",
                    "details": [
                        {
                            "field": "elevation",
                            "from": f"{old['elevation']:.0f}",
                            "to": f"{elevation:.0f}",
                        }
                    ],
                    "applicable": plan_ok,
                    "reason": None if plan_ok else no_plan,
                    "data": {"elevation": elevation},
                }
            )
    for key, old in levels.items():
        if key not in seen_levels and incoming.get("levels"):
            add(
                {
                    "action": "remove",
                    "target": "level",
                    "kind": "level",
                    "ref": key,
                    "revitId": old.get("revitId"),
                    "title": f"Level {old['name']} is not in Revit",
                    "applicable": False,
                    "reason": "levels are removed in the floor plan (05 Floor Plan)",
                }
            )

    # Grid lines.
    grids = {g["id"]: g for g in current["grids"]}
    seen_grids: set[str] = set()
    for g in incoming.get("grids") or []:
        match = _match(g, grids, by_revit) or next(
            (k for k, v in grids.items() if v["name"] == g.get("name")), None
        )
        axis, position = _grid_axis(g)
        if match is None:
            ok = plan_ok and axis is not None
            add(
                {
                    "action": "add",
                    "target": "grid",
                    "kind": "grid",
                    "ref": g.get("id") or g.get("name"),
                    "revitId": g.get("revitId"),
                    "title": f"New grid line {g.get('name')}",
                    "details": []
                    if axis is None
                    else [{"field": axis, "from": "", "to": f"{position:.0f}"}],
                    "applicable": ok,
                    "reason": None
                    if ok
                    else (
                        no_plan if not plan_ok else "the floor plan's grids run along x and y only"
                    ),
                    "data": {
                        "axis": axis,
                        "label": str(g.get("name") or g.get("id")),
                        "position": position,
                    },
                }
            )
            continue
        seen_grids.add(match)
        old = grids[match]
        if axis is None:
            add(
                {
                    "action": "modify",
                    "target": "grid",
                    "kind": "grid",
                    "ref": match,
                    "revitId": g.get("revitId"),
                    "title": f"Grid line {old['name']} turned off the x and y axes",
                    "applicable": False,
                    "reason": "the floor plan's grids run along x and y only",
                }
            )
        elif axis != old["axis"] or abs(old["position"] - position) > TOLERANCE:
            add(
                {
                    "action": "modify",
                    "target": "grid",
                    "kind": "grid",
                    "ref": match,
                    "revitId": g.get("revitId"),
                    "title": f"Grid line {old['name']} moved",
                    "details": [
                        {
                            "field": "position",
                            "from": f"{old['position']:.0f}",
                            "to": f"{position:.0f}",
                        }
                    ],
                    "applicable": plan_ok and axis == old["axis"],
                    "reason": None
                    if plan_ok and axis == old["axis"]
                    else "a grid line cannot change direction",
                    "data": {"axis": old["axis"], "label": old["name"], "position": position},
                }
            )
    for key, old in grids.items():
        if key not in seen_grids and incoming.get("grids"):
            add(
                {
                    "action": "remove",
                    "target": "grid",
                    "kind": "grid",
                    "ref": key,
                    "revitId": old.get("revitId"),
                    "title": f"Grid line {old['name']} is not in Revit",
                    "applicable": False,
                    "reason": "grid lines are removed in the floor plan (05 Floor Plan)",
                }
            )

    # Elements.
    elements = {e["id"]: e for e in current["elements"]}
    scope = set(incoming.get("scope") or KINDS)
    seen: set[str] = set()
    for new in incoming.get("elements") or []:
        kind = new.get("kind")
        if kind not in KINDS:
            notes.append(f"{_label(new)}: an element kind SAEngine does not know, left out")
            continue
        match = _match(new, elements, by_revit)
        type_id, how = resolve_section(kind, new.get("section"), incoming, objects)
        if match is None:
            reason = _addable(new, kind, plan_ok, type_id, how)
            add(
                {
                    "action": "add",
                    "target": "element",
                    "kind": kind,
                    "ref": None,
                    "revitId": new.get("revitId"),
                    "title": f"New {kind} from Revit"
                    + (f" ({new.get('name')})" if new.get("name") else ""),
                    "details": [
                        {
                            "field": "type",
                            "from": "",
                            "to": type_id or str(new.get("section") or "?"),
                        }
                    ],
                    "applicable": reason is None,
                    "reason": reason,
                    "data": {"element": new, "section": type_id},
                }
            )
            continue
        seen.add(match)
        old = elements[match]
        details = _geometry_changes(old, new)
        if type_id != old["section"]:
            details.append(
                {"field": "type", "from": old["section"], "to": type_id or str(new.get("section"))}
            )
        if not details:
            continue
        reason = None
        if old.get("owner") != "floorPlan" or not plan_ok:
            reason = (
                "it belongs to the building model (06 BIM): change it there" if plan_ok else no_plan
            )
        elif type_id is None and any(d["field"] == "type" for d in details):
            reason = how
        else:
            reason = _shape_problem(new, kind)
        add(
            {
                "action": "modify",
                "target": "element",
                "kind": kind,
                "ref": match,
                "revitId": new.get("revitId"),
                "title": f"{kind.capitalize()} {match} changed",
                "details": details,
                "applicable": reason is None,
                "reason": reason,
                "data": {"element": new, "section": type_id or old["section"]},
            }
        )
    if incoming.get("elements") is not None:
        for key, old in elements.items():
            if key in seen or old["kind"] not in scope:
                continue
            owned = old.get("owner") == "floorPlan" and plan_ok
            add(
                {
                    "action": "remove",
                    "target": "element",
                    "kind": old["kind"],
                    "ref": key,
                    "revitId": old.get("revitId"),
                    "title": f"{old['kind'].capitalize()} {key} was deleted in Revit",
                    "applicable": owned,
                    "reason": None
                    if owned
                    else "it belongs to the building model (06 BIM): delete it there",
                }
            )

    # Reinforcement: reported, never taken back.
    in_bars = incoming.get("rebar") or []
    if in_bars:
        hosts = {str(bar.get("host")) for bar in in_bars}
        notes.append(
            f"The file carries {len(in_bars)} bar sets on {len(hosts)} members. They are not "
            "taken back: SAEngine's bars come from the design and the detailing (change the "
            "object types' reinforcement in 04 Objects, or design again)."
        )

    counts = {"add": 0, "modify": 0, "remove": 0, "applicable": 0}
    for c in changes:
        counts[c["action"]] += 1
        counts["applicable"] += 1 if c["applicable"] else 0
    origin = incoming.get("origin") or {}
    return {
        "changes": changes,
        "counts": counts,
        "notes": notes + [str(n) for n in incoming.get("notes") or []],
        "source": {
            "application": origin.get("application"),
            "version": origin.get("version"),
            "written": origin.get("written"),
            "document": origin.get("document"),
        },
    }


def _grid_axis(g: dict[str, Any]) -> tuple[str | None, float]:
    """``("x", position)`` for a line along y (a constant x), ``("y", position)`` for one along
    x, ``(None, 0)`` for a slanted line; read from ``start``/``end``, else ``axis``/``position``."""
    start, end = g.get("start"), g.get("end")
    if isinstance(start, list) and isinstance(end, list) and len(start) >= 2 and len(end) >= 2:
        if abs(start[0] - end[0]) <= TOLERANCE:
            return "x", (start[0] + end[0]) / 2
        if abs(start[1] - end[1]) <= TOLERANCE:
            return "y", (start[1] + end[1]) / 2
        return None, 0.0
    if g.get("axis") in ("x", "y") and isinstance(g.get("position"), int | float):
        return g["axis"], float(g["position"])
    return None, 0.0


def _shape_problem(e: dict[str, Any], kind: str) -> str | None:
    """Why the floor plan cannot hold this element as it is in Revit, if it cannot."""
    if kind not in PLAN_KINDS:
        return f"{kind}s belong to the building model (06 BIM)"
    curve = e.get("curve")
    lined = isinstance(curve, list) and len(curve) == 2 and all(len(p) == 3 for p in curve)
    if kind in ("column", "beam", "wall") and not lined:
        return "it has no location line"
    if kind == "column" and not _close(curve[0][:2], curve[1][:2]):
        return "it is slanted: a raking column is an inclined member of the building model"
    if kind == "beam" and abs(curve[0][2] - curve[1][2]) > LEVEL_TOLERANCE:
        return "it is sloped: a sloped beam is an inclined member of the building model"
    if kind == "slab":
        outline = e.get("outline")
        if not isinstance(outline, list) or len(outline) < 3:
            return "it has no outline"
        if max(p[2] for p in outline) - min(p[2] for p in outline) > LEVEL_TOLERANCE:
            return "it is sloped: the floor plan's slabs are level"
    if kind == "footing" and not (isinstance(e.get("point"), list) and len(e["point"]) == 3):
        return "it has no location point"
    return None


def _addable(
    e: dict[str, Any], kind: str, plan_ok: bool, type_id: str | None, how: str
) -> str | None:
    if not plan_ok:
        return "only the floor plan of a building takes new elements"
    problem = _shape_problem(e, kind)
    if problem:
        return problem
    return None if type_id else how


# ───────────────────────────────────────── apply ─────────────────────────────────────────


class _Plan:
    """The floor plan's JSON with the conversions between absolute points and grid points."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        data.setdefault("grids", {}).setdefault("x", [])
        data["grids"].setdefault("y", [])
        data.setdefault("stories", [])
        for key in PLAN_KINDS.values():
            data.setdefault(key, [])

    def axis(self, axis: str) -> dict[str, float]:
        return {g["label"]: float(g["position"]) for g in self.data["grids"][axis]}

    def absolute(self, gp: dict[str, Any]) -> tuple[float, float]:
        return (
            self.axis("x")[gp["x"]] + float(gp.get("dx", 0)),
            self.axis("y")[gp["y"]] + float(gp.get("dy", 0)),
        )

    def grid_point(self, x: float, y: float) -> dict[str, Any]:
        xs, ys = self.axis("x"), self.axis("y")
        if not xs or not ys:
            raise ValueError("the floor plan has no grid lines to place it on")
        gx = min(xs, key=lambda k: abs(xs[k] - x))
        gy = min(ys, key=lambda k: abs(ys[k] - y))
        point: dict[str, Any] = {"x": gx, "y": gy}
        dx, dy = round(x - xs[gx], 1), round(y - ys[gy], 1)
        if abs(dx) > 0.05:
            point["dx"] = dx
        if abs(dy) > 0.05:
            point["dy"] = dy
        return point

    def story(self, elevation: float, prefer: str | None = None) -> str:
        stories = self.data["stories"]
        for s in stories:
            if s["id"] == prefer and abs(float(s["elevation"]) - elevation) <= LEVEL_TOLERANCE:
                return s["id"]
        for s in stories:
            if abs(float(s["elevation"]) - elevation) <= LEVEL_TOLERANCE:
                return s["id"]
        raise ValueError(f"no story at {elevation:.0f} mm: add the level first")

    def grid_points(self) -> list[dict[str, Any]]:
        """Every grid point of the plan's members and towers."""
        out = []
        for c in self.data["columns"]:
            out.append(c["at"])
        for f in self.data["footings"]:
            out.append(f["at"])
        for key in ("beams", "walls"):
            for m in self.data[key]:
                out += [m["start"], m["end"]]
        for s in self.data["slabs"]:
            out += s["boundary"]
        for t in self.data.get("towers") or []:
            out += t["boundary"]
        return out

    def find(self, kind: str, element_id: str) -> tuple[list[dict[str, Any]], int]:
        items = self.data[PLAN_KINDS[kind]]
        for i, m in enumerate(items):
            if m["id"] == element_id:
                return items, i
        raise ValueError(f"no {kind} {element_id} in the floor plan")

    def new_id(self, kind: str) -> str:
        taken = {m["id"] for key in PLAN_KINDS.values() for m in self.data[key]}
        prefix = {"column": "C", "beam": "B", "wall": "W", "slab": "S", "footing": "F"}[kind]
        n = 1
        while f"R{prefix}{n}" in taken:
            n += 1
        return f"R{prefix}{n}"


def _place(plan: _Plan, kind: str, e: dict[str, Any], member: dict[str, Any]) -> None:
    """Sets the location of a floor-plan member from an exchange element."""
    if kind == "column":
        (x0, y0, z0), (_, _, z1) = e["curve"]
        bottom, top = sorted((z0, z1))
        member["at"] = plan.grid_point(x0, y0)
        member["base"] = plan.story(bottom, e.get("baseLevel"))
        member["top"] = plan.story(top, e.get("topLevel"))
        member["rotation"] = round(float(e.get("rotation") or 0.0), 2)
    elif kind == "beam":
        (x0, y0, z0), (x1, y1, _) = e["curve"]
        member["start"] = plan.grid_point(x0, y0)
        member["end"] = plan.grid_point(x1, y1)
        member["story"] = plan.story(z0, e.get("level"))
    elif kind == "wall":
        (x0, y0, z0), (x1, y1, _) = e["curve"]
        bottom = float(e.get("bottom", z0))
        member["start"] = plan.grid_point(x0, y0)
        member["end"] = plan.grid_point(x1, y1)
        member["base"] = plan.story(bottom, e.get("baseLevel"))
        member["top"] = plan.story(float(e["top"]), e.get("topLevel"))
    elif kind == "slab":
        outline = e["outline"]
        member["boundary"] = [plan.grid_point(p[0], p[1]) for p in outline]
        member["story"] = plan.story(outline[0][2], e.get("level"))
    elif kind == "footing":
        x, y, z = e["point"]
        member["at"] = plan.grid_point(x, y)
        member["story"] = plan.story(z, e.get("level"))
        member["rotation"] = round(float(e.get("rotation") or 0.0), 2)
    if member.get("base") and member.get("top"):
        stories = {s["id"]: float(s["elevation"]) for s in plan.data["stories"]}
        if stories[member["top"]] <= stories[member["base"]]:
            raise ValueError("its top level must be above its base level")


def apply_import(project: str | Path, path: str | Path, change_ids: list[str]) -> dict[str, Any]:
    """Applies the picked changes of :func:`preview_import` to the floor plan: ``{"applied",
    "failed": [{"id", "reason"}], "backupPath", "planPath", "notes"}``. Levels and grid lines
    go first; members not changed keep where they are when a grid line moves."""
    from saengine.importers.common import json_text
    from saengine.library.floorplan import FloorPlan
    from saengine.pipeline.project import read_text

    p = _project(project)
    preview = preview_import(p.root, path)
    wanted = set(change_ids)
    picked = [c for c in preview["changes"] if c["id"] in wanted]
    unknown = sorted(wanted - {c["id"] for c in picked})
    failed: list[dict[str, Any]] = [
        {"id": u, "reason": "not a change in the file now"} for u in unknown
    ]
    plan_path = p.file("floorPlan")
    original = read_text(plan_path)
    if original is None or p.type != "building":
        raise RevitLinkError(f"{p.name}: no floor plan to apply the changes to")
    plan = _Plan(json.loads(original))
    applied: list[str] = []
    link_folder = p.folder("exports") / EXPORT_FOLDER
    link = _read_link(link_folder)
    order = {"level": 0, "grid": 1, "element": 2}
    picked.sort(key=lambda c: (order[c["target"]], c["action"] != "remove"))

    # Members keep their absolute positions when grid lines move: taken before the grid edits.
    points = plan.grid_points()
    absolute = [plan.absolute(gp) for gp in points]
    grids_moved = False

    for change in picked:
        if not change["applicable"]:
            failed.append({"id": change["id"], "reason": change["reason"] or "not applicable"})
            continue
        try:
            if change["target"] == "level":
                _apply_level(plan, change)
            elif change["target"] == "grid":
                _apply_grid(plan, change)
                grids_moved = True
            else:
                if grids_moved:
                    _repin(plan, points, absolute)
                    grids_moved = False
                _apply_element(plan, change)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            failed.append({"id": change["id"], "reason": str(error)})
            continue
        applied.append(change["id"])
        if change.get("revitId"):
            ref = change.get("ref")
            if ref and change["action"] != "remove":
                link["ids"][ref] = change["revitId"]
            elif change["action"] == "remove":
                link["ids"].pop(change.get("ref"), None)
    if grids_moved:
        _repin(plan, points, absolute)
    notes: list[str] = []
    backup = None
    if applied:
        try:
            FloorPlan.model_validate(plan.data)
        except ValueError as error:
            raise RevitLinkError(
                f"the floor plan would not be valid after the changes: {error}"
            ) from error
        backup = link_folder / BACKUP_FILE
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(original.encode("utf-8"))
        plan_path.write_text(json_text(plan.data), encoding="utf-8")
        link["schema"] = LINK_SCHEMA_ID
        link["lastImport"] = _now()
        _write_json(link_folder / LINK_FILE, link)
        notes.append("Rebuild the building model (06 BIM) from the floor plan to see the changes.")
        if any(c["action"] == "remove" and c["kind"] in ("column", "wall") for c in picked):
            notes.append("Members were deleted: check the model for beams left unsupported.")
    return {
        "applied": applied,
        "failed": failed,
        "backupPath": str(backup) if backup else None,
        "planPath": str(plan_path),
        "notes": notes,
    }


def _apply_level(plan: _Plan, change: dict[str, Any]) -> None:
    stories = plan.data["stories"]
    data = change["data"]
    if change["action"] == "modify":
        story = next(s for s in stories if s["id"] == change["ref"])
        story["elevation"] = data["elevation"]
    elif change["action"] == "add":
        elevation, name = data["elevation"], data["name"]
        taken = {s["id"] for s in stories}
        base = "".join(ch for ch in str(change["ref"] or name) if ch.isalnum() or ch in "-_") or "L"
        story_id, n = base, 2
        while story_id in taken:
            story_id, n = f"{base}{n}", n + 1
        stories.append({"id": story_id, "name": name, "elevation": elevation})
    else:
        raise ValueError("levels are removed in the floor plan")
    stories.sort(key=lambda s: float(s["elevation"]))


def _apply_grid(plan: _Plan, change: dict[str, Any]) -> None:
    data = change["data"]
    axis, label = data["axis"], data["label"]
    if change["action"] == "modify":
        line = next(g for g in plan.data["grids"][axis] if g["label"] == label)
        line["position"] = data["position"]
    elif change["action"] == "add":
        if any(g["label"] == label for key in ("x", "y") for g in plan.data["grids"][key]):
            raise ValueError(f"grid line {label} is already in the floor plan")
        plan.data["grids"][axis].append({"label": label, "position": data["position"]})
    else:
        raise ValueError("grid lines are removed in the floor plan")
    for axis in ("x", "y"):
        plan.data["grids"][axis].sort(key=lambda g: float(g["position"]))


def _repin(plan: _Plan, points: list[dict[str, Any]], absolute: list[tuple[float, float]]) -> None:
    """Puts every grid point back where it was before the grid lines moved, on the same grid
    lines (their offsets change)."""
    xs, ys = plan.axis("x"), plan.axis("y")
    for gp, (x, y) in zip(points, absolute, strict=True):
        for axis, lines, value in (("x", xs, x), ("y", ys, y)):
            offset = round(value - lines[gp[axis]], 1)
            if abs(offset) > 0.05:
                gp[f"d{axis}"] = offset
            else:
                gp.pop(f"d{axis}", None)


def _apply_element(plan: _Plan, change: dict[str, Any]) -> None:
    kind = change["kind"]
    if kind not in PLAN_KINDS:
        raise ValueError(f"{kind}s belong to the building model")
    if change["action"] == "remove":
        items, i = plan.find(kind, change["ref"])
        items.pop(i)
        return
    e, section = change["data"]["element"], change["data"]["section"]
    if change["action"] == "modify":
        items, i = plan.find(kind, change["ref"])
        member = dict(items[i])
        _place(plan, kind, e, member)
        member["type"] = section
        items[i] = member
        return
    member = {"id": plan.new_id(kind), "type": section}
    _place(plan, kind, e, member)
    plan.data[PLAN_KINDS[kind]].append(member)
    change["ref"] = member["id"]


# ───────────────────────────────────────── the app ─────────────────────────────────────────


def rpc_export(params: dict[str, Any]) -> dict[str, Any]:
    """The app's ``revit/export`` ``{projectRoot, outPath?}``: :func:`export_exchange_file`'s
    answer, or ``{"error"}``."""
    try:
        return export_exchange_file(params["projectRoot"], params.get("outPath"))
    except (RevitLinkError, OSError) as error:
        return {"error": str(error)}


def rpc_preview(params: dict[str, Any]) -> dict[str, Any]:
    """The app's ``revit/preview`` ``{projectRoot, path}``: :func:`preview_import`'s answer
    (without the elements' geometry), or ``{"error"}``."""
    try:
        answer = preview_import(params["projectRoot"], params["path"])
    except (RevitLinkError, OSError) as error:
        return {"error": str(error)}
    for change in answer["changes"]:
        change.pop("data", None)
    return answer


def rpc_apply(params: dict[str, Any]) -> dict[str, Any]:
    """The app's ``revit/apply`` ``{projectRoot, path, changes: [id]}``: :func:`apply_import`'s
    answer, or ``{"error"}``."""
    try:
        return apply_import(
            params["projectRoot"], params["path"], list(params.get("changes") or [])
        )
    except (RevitLinkError, OSError) as error:
        return {"error": str(error)}


__all__ = [
    "BACKUP_FILE",
    "EXCHANGE_SUFFIX",
    "EXPORT_FOLDER",
    "LINK_FILE",
    "SCHEMA_ID",
    "RevitLinkError",
    "apply_import",
    "build_exchange",
    "export_exchange_file",
    "preview_import",
    "read_exchange",
    "resolve_section",
    "rpc_apply",
    "rpc_export",
    "rpc_preview",
]
