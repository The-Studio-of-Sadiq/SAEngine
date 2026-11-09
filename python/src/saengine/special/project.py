"""The project's bridges and special structures: their run (kept beside the analysis model for the
results view), the design report's section and the bill of quantities' lines.

Every structure of Project Settings → Bridges and Special Structures is computed under the
project's code pack; one that cannot be (a pack that does not cover it, a missing object type
or material) gives its reason and the others go on. Units as in :mod:`saengine.special`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from saengine.codes import context as code_context

SETTINGS_FILE = "02 Project Settings/project-settings.json"
MATERIALS_FILE = "03 Materials/materials.json"
OBJECTS_FILE = "04 Objects/objects.json"
#: The last run, for the results view (written by :func:`run_project` with ``keep``).
KEPT_FILE = "08 FEM/special-structures.json"

#: How the bill names the kinds of its lines.
WORDS = {
    "bridge": "bridges",
    "latticeTower": "lattice towers",
    "silo": "silos",
    "chimney": "chimneys",
    "coolingTower": "cooling towers",
    "offshore": "offshore structures",
}

KIND_TITLES = {
    "bridges": "Bridge",
    "towers": "Lattice tower",
    "silos": "Silo",
    "chimneys": "Chimney",
    "coolingTowers": "Cooling tower",
    "offshore": "Offshore structure",
    "piping": "Piping system",
}


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8-sig")
    except OSError:
        return None


def load(root: str | Path) -> tuple[Any, Any, Any, str]:
    """(settings, materials, objects, the settings' text) of the project at ``root``."""
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings

    root = Path(root)
    text = _read(root, SETTINGS_FILE)
    if text is None:
        raise ValueError("the project has no settings")
    with code_context.project(root):
        settings = ProjectSettings.model_validate_json(text)
    materials_text = _read(root, MATERIALS_FILE)
    objects_text = _read(root, OBJECTS_FILE)
    materials = MaterialLibrary.model_validate_json(materials_text) if materials_text else None
    objects = ObjectLibrary.model_validate_json(objects_text) if objects_text else None
    return settings, materials, objects, text


def analyse(kind: str, entry: Any, settings: Any, materials: Any, objects: Any) -> dict[str, Any]:
    """The results of one structure under the pack in force."""
    from saengine.special import bridges, offshore, piping, shells, towers

    if kind == "bridges":
        return bridges.check_bridge(entry, _need(materials, "materials"))
    if kind == "towers":
        return towers.analyse_tower(
            entry, settings, _need(objects, "object types"), _need(materials, "materials")
        )
    if kind == "silos":
        return shells.analyse_silo(entry, _need(materials, "materials"))
    if kind == "chimneys":
        return shells.analyse_chimney(entry, settings, _need(materials, "materials"))
    if kind == "coolingTowers":
        return shells.analyse_cooling_tower(entry, settings, _need(materials, "materials"))
    if kind == "offshore":
        return offshore.analyse_offshore(
            entry, settings, _need(objects, "object types"), _need(materials, "materials")
        )
    if kind == "piping":
        return piping.analyse_piping(entry)
    raise ValueError(f"unknown kind of structure '{kind}'")


def _need(library: Any, what: str) -> Any:
    if library is None:
        raise ValueError(f"the project has no {what}")
    return library


def run_project(root: str | Path, keep: bool = True) -> dict[str, Any]:
    """Every special structure of the project: ``{"available", "configured", "code",
    "structures": [{"kind", "id", "name", ...results or "error"}], "sheets"}`` (``sheets``: per
    structure the tables and charts of the results view); written to :data:`KEPT_FILE` with
    ``keep``."""
    from saengine.library.bim import source_stamp
    from saengine.library.settings import code_pack

    root = Path(root)
    settings, materials, objects, _ = load(root)
    special = settings.specialStructures
    if special.is_empty():
        return {"available": False, "configured": False, "reason": "none in Project Settings"}
    with code_context.project(root):
        pack = code_pack(settings)
        with code_context.using(pack):
            code = code_context.code_name(pack)
            structures = []
            for kind, entries in special.items():
                for entry in entries:
                    try:
                        found = analyse(kind, entry, settings, materials, objects)
                    except Exception as error:  # noqa: BLE001 - one structure must not stop the rest
                        found = {"error": str(error) or type(error).__name__}
                    structures.append({"kind": kind, "id": entry.id, "name": entry.name, **found})
    out = {
        "available": True,
        "configured": True,
        "code": code,
        "stamp": source_stamp(json.dumps(special.model_dump(mode="json"), sort_keys=True)),
        "structures": structures,
        "sections": [view_section(s) for s in structures],
    }
    if keep:
        path = root / KEPT_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return out


def kept(root: str | Path) -> dict[str, Any]:
    """The last run kept beside the analysis model; ``{"available": False, "reason": "not run
    yet", "configured"}`` without one (or when the structures changed since)."""
    from saengine.library.bim import source_stamp

    root = Path(root)
    try:
        settings, _, _, _ = load(root)
    except ValueError:
        return {"available": False, "configured": False, "reason": "no project settings"}
    special = settings.specialStructures
    configured = not special.is_empty()
    text = _read(root, KEPT_FILE)
    if not configured:
        return {"available": False, "configured": False, "reason": "none in Project Settings"}
    if text is None:
        return {"available": False, "configured": True, "reason": "not run yet"}
    try:
        found = json.loads(text)
    except ValueError:
        return {"available": False, "configured": True, "reason": "not run yet"}
    stamp = source_stamp(json.dumps(special.model_dump(mode="json"), sort_keys=True))
    if found.get("stamp") != stamp:
        return {"available": False, "configured": True, "reason": "changed since the last run"}
    return found


# ───────────────────────────────────── the results view ─────────────────────────────────


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return round(value, 3) if math.isfinite(value) else str(value)
    return value


def _check_sheet(rows: list[dict[str, Any]], name: str = "Checks") -> dict[str, Any]:
    return {
        "name": name,
        "columns": ["Check", "Demand", "Capacity", "Unit", "Ratio", "Note"],
        "rows": [
            [
                r.get("name", ""),
                _cell(r.get("demand")),
                _cell(r.get("capacity")),
                r.get("unit", ""),
                _cell(r.get("ratio")),
                r.get("note", ""),
            ]
            for r in rows
        ],
        "fails": [r.get("ok") is False for r in rows],
    }


def _table(name: str, columns: list[str], keys: list[str], rows: list[dict[str, Any]]) -> dict:
    return {
        "name": name,
        "columns": columns,
        "rows": [[_cell(r.get(k)) for k in keys] for r in rows],
        "fails": [False] * len(rows),
    }


def _member_sheet(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sheet = _table(
        "Governing members",
        ["Role", "Member", "Type", "Section", "Length [m]", "N [kN]", "Ratio", "Combination"],
        ["role", "member", "type", "section", "length", "axial", "ratio", "combination"],
        rows,
    )
    sheet["fails"] = [float(r.get("ratio") or 0) > 1.0 for r in rows]
    return sheet


def view_section(found: dict[str, Any]) -> dict[str, Any]:
    """A structure's results as sheets (``name``, ``columns``, ``rows``, ``fails``) and charts
    (``title``, ``xLabel``, ``yLabel``, ``series`` of ``name`` and ``points``) and notes."""
    kind = found["kind"]
    title = f"{KIND_TITLES.get(kind, kind)} {found['id']}" + (
        f": {found['name']}" if found.get("name") else ""
    )
    if "error" in found:
        return {"title": title, "error": found["error"], "sheets": [], "charts": [], "notes": []}
    sheets: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    if kind == "bridges":
        sheets.append(_check_sheet(found["rows"]))
        sheets.append(
            _table(
                "Bearings",
                [
                    "Support line",
                    "Kind",
                    "Service max [kN]",
                    "Service min [kN]",
                    "Factored [kN]",
                    "Uplift",
                ],
                ["line", "kind", "serviceMax", "serviceMin", "factored", "uplift"],
                found["bearings"],
            )
        )
        sheets.append(
            _table(
                "Expansion joints",
                ["Support line", "Length from fixed [m]", "Movement ± [mm]"],
                ["line", "length", "movement"],
                found["joints"],
            )
        )
        if found.get("rating"):
            sheet = _table(
                "Load rating",
                ["Effect", "Level", "Girder", "At x [m]", "RF"],
                ["effect", "level", "girder", "at", "rf"],
                found["rating"],
            )
            sheet["fails"] = [float(r["rf"]) < 1.0 for r in found["rating"]]
            sheets.append(sheet)
        chart = found.get("chart") or {}
        if chart.get("x"):
            xs = chart["x"]
            charts.append(
                {
                    "title": f"Moments along girder {chart['girder']}",
                    "xLabel": "x [m]",
                    "yLabel": "Moment [kN·m]",
                    "series": [
                        {
                            "name": "LL + IM, largest",
                            "points": [[x, v] for x, v in zip(xs, chart["llMax"], strict=True)],
                        },
                        {
                            "name": "LL + IM, least",
                            "points": [[x, v] for x, v in zip(xs, chart["llMin"], strict=True)],
                        },
                        {
                            "name": "DC",
                            "points": [[x, v] for x, v in zip(xs, chart["dc"], strict=True)],
                        },
                        {
                            "name": "DW",
                            "points": [[x, v] for x, v in zip(xs, chart["dw"], strict=True)],
                        },
                    ],
                }
            )
    elif kind == "towers":
        sheets.append(_member_sheet(found["rows"]))
        sheets.append(
            _table(
                "Wind on the panels (normal to a face)",
                ["Panel", "z [m]", "ε", "Cf", "Rr", "Af [m²]", "Ar [m²]", "qz [kPa]", "F [kN]"],
                ["panel", "z", "solidity", "Cf", "Rr", "Af", "Ar", "qz", "F"],
                found["panels"],
            )
        )
        if found.get("antennas"):
            sheets.append(
                _table(
                    "Antennas",
                    ["Name", "z [m]", "F [kN]", "Weight [kN]"],
                    ["name", "z", "F", "weight"],
                    found["antennas"],
                )
            )
        r = found["reactions"]
        rows = [{"what": "Weight [kN]", "value": r.get("weight")}]
        for key in ("W0", "W45"):
            if key in r:
                rows.append({"what": f"Base shear {key} [kN]", "value": r[key]["shear"]})
                rows.append({"what": f"Overturning moment {key} [kN·m]", "value": r[key]["moment"]})
        rows += [
            {"what": "Leg compression, factored [kN]", "value": r.get("legCompression")},
            {"what": "Leg uplift, factored [kN]", "value": r.get("legUplift")},
        ]
        sheets.append(_table("Base reactions", ["", "Value"], ["what", "value"], rows))
        charts.append(
            {
                "title": "Wind force per panel",
                "xLabel": "F [kN]",
                "yLabel": "z [m]",
                "series": [{"name": "F", "points": [[p["F"], p["z"]] for p in found["panels"]]}],
            }
        )
    elif kind == "silos":
        sheets.append(_check_sheet(found["rows"]))
        sheets.append(
            _table(
                "Pressures [kPa]",
                ["Depth z [m]", "ph", "pw", "pv", "ph discharge"],
                ["z", "ph", "pw", "pv", "phDischarge"],
                found["pressures"],
            )
        )
        charts.append(
            {
                "title": "Horizontal pressure on the wall",
                "xLabel": "ph [kPa]",
                "yLabel": "Depth z [m]",
                "series": [
                    {"name": "filling", "points": [[p["ph"], -p["z"]] for p in found["pressures"]]},
                    {
                        "name": "discharge",
                        "points": [[p["phDischarge"], -p["z"]] for p in found["pressures"]],
                    },
                ],
            }
        )
    elif kind == "chimneys":
        sheets.append(_check_sheet(found["rows"]))
        rows = [{"what": "First frequency [Hz]", "value": found.get("frequency")}]
        rows += [{"what": f"Along-wind {k}", "value": v} for k, v in found["alongWind"].items()]
        rows += [
            {"what": f"Vortex shedding {k}", "value": v} for k, v in found.get("vortex", {}).items()
        ]
        sheets.append(_table("Wind and vortex shedding", ["", "Value"], ["what", "value"], rows))
    elif kind == "coolingTowers":
        sheets.append(_check_sheet(found["rows"]))
        rows = [{"what": k, "value": v} for k, v in found["forces"].items()]
        sheets.append(
            _table("Shell forces, factored [kN/m]", ["", "Value"], ["what", "value"], rows)
        )
    elif kind == "offshore":
        sheets.append(_member_sheet(found["rows"]))
        w = found["wave"]
        rows = [{"what": k, "value": v} for k, v in w.items()]
        rows.append({"what": "base shear, unfactored [kN]", "value": found.get("baseShear")})
        sheets.append(_table("Design wave", ["", "Value"], ["what", "value"], rows))
    elif kind == "piping":
        sheets.append(_check_sheet(found["rows"]))
        if found.get("nozzles"):
            sheets.append(
                _table(
                    "Nozzle (anchor) loads",
                    ["Route point", "Combination", "Force [kN]", "Moment [kN·m]"],
                    ["point", "combination", "force", "moment"],
                    found["nozzles"],
                )
            )
    return {"title": title, "sheets": sheets, "charts": charts, "notes": found.get("notes", [])}


# ───────────────────────────────────── the design report ─────────────────────────────────


def report_section(root: str | Path) -> dict[str, Any] | None:
    """The design report's section: ``{"title", "intro", "structures": [{"title", "error",
    "sheets", "notes"}]}``; None without special structures."""
    found = run_project(root, keep=False)
    if not found.get("available"):
        return None
    return {
        "title": "Bridges and special structures",
        "intro": f"By the code pack {found['code']}: each structure's loads, its checks and the "
        "notes on what the checks leave out.",
        "structures": [
            {
                "title": s["title"],
                "error": s.get("error"),
                "sheets": s["sheets"],
                "notes": s["notes"],
            }
            for s in found["sections"]
        ],
    }


# ───────────────────────────────────── the bill of quantities ─────────────────────────────


def quantities(
    special: Any, objects: Any, materials: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    """The bill's lines of the special structures: ``(lines, notes)``, each line ``{"group",
    "key", "description", "unit", "element", "quantity", "material", "kind"}`` (concrete m³,
    steel kg, strands kg, pipe m)."""
    from saengine.boq.quantities import _kind_order
    from saengine.library.shapes import RevolutionShell
    from saengine.special.common import member_type
    from saengine.special.offshore import jacket_shape
    from saengine.special.towers import tower_shape

    lines: list[dict[str, Any]] = []
    notes: list[str] = []
    mats = {m.id: m for m in materials.materials} if materials is not None else {}

    def concrete(element: str, material: str, kind: str, volume: float) -> None:
        if volume > 0:
            lines.append(
                {
                    "group": "concrete",
                    "key": (_kind_order(kind), material),
                    "description": f"Concrete {material} in {WORDS.get(kind, kind)}",
                    "unit": "m3",
                    "element": element,
                    "quantity": volume,
                    "material": material,
                    "kind": kind,
                }
            )

    def steel(element: str, material: str, kind: str, mass: float, what: str) -> None:
        if mass > 0:
            lines.append(
                {
                    "group": "steel",
                    "key": (material, _kind_order(kind), what),
                    "description": f"Structural steel {material}, {what}, in {WORDS.get(kind, kind)}",
                    "unit": "kg",
                    "element": element,
                    "quantity": mass,
                    "material": material,
                    "kind": kind,
                }
            )

    for b in special.bridges:
        length = sum(b.spans)
        t = b.deckThickness / 1000
        web = b.girders * b.girder.webWidth / 1000 * max(b.girder.depth / 1000 - t, 0) * length
        deck = max(b.carriageway, b.girders * b.girderSpacing) * t * length
        concrete(b.id, b.girder.concrete, "bridge", web + deck)
        if b.girder.prestress is not None:
            mass = b.girder.prestress.area * 1e-6 * length * 7850 * b.girders
            lines.append(
                {
                    "group": "special",
                    "key": ("strand", b.id),
                    "description": f"Prestressing strand in the girders of {b.id}",
                    "unit": "kg",
                    "element": b.id,
                    "quantity": mass,
                    "material": None,
                    "kind": "bridge",
                }
            )
        notes.append(f"{b.id}: the girders' and deck's reinforcement are not measured")
    for tw in special.towers:
        try:
            geometry = tower_shape(tw).local()
            by_type: dict[str, float] = {}
            for m in geometry.members:
                by_type[m.type] = by_type.get(m.type, 0.0) + float(math.dist(m.start, m.end)) / 1000
            for type_id, length in by_type.items():
                kind_ = member_type(type_id, objects, materials)
                obj = next(o for o in objects.objects if o.id == type_id)
                steel(
                    tw.id,
                    obj.material,
                    "latticeTower",
                    length * kind_.section.mass,
                    f"{kind_.label} ({length:.1f} m)",
                )
        except (ValueError, AttributeError, StopIteration) as error:
            notes.append(f"{tw.id}: not measured ({error})")
    for s in special.silos:
        t = s.wallThickness / 1000
        concrete(s.id, s.concrete, "silo", math.pi * (s.diameter + t) * t * s.height)
        notes.append(f"{s.id}: the hopper and roof are not measured")
    for c in special.chimneys:
        steps = 20
        volume = 0.0
        for k in range(steps):
            z = (k + 0.5) / steps
            d = c.baseDiameter + (c.topDiameter - c.baseDiameter) * z
            th = (c.baseThickness + (c.topThickness - c.baseThickness) * z) / 1000
            volume += math.pi * d * th * c.height / steps
        material = mats.get(c.material)
        category = getattr(getattr(material, "category", None), "value", None)
        if category == "steel":
            density = (material.mechanical.density if material.mechanical else None) or 7850
            steel(c.id, c.material, "chimney", volume * density, "chimney shell")
        else:
            concrete(c.id, c.material, "chimney", volume)
    for ct in special.coolingTowers:
        shape = RevolutionShell(
            profile="hyperboloid",
            height=ct.height * 1000,
            baseRadius=ct.baseRadius * 1000,
            topRadius=ct.topRadius * 1000,
            throatRadius=ct.throatRadius * 1000,
            throatHeight=ct.throatHeight * 1000,
            panelType="SHELL",
        )
        area = 0.0
        steps = 60
        for k in range(steps):
            z0, z1 = ct.height * k / steps, ct.height * (k + 1) / steps
            r0 = shape.radius(z0 * 1000) / 1000
            r1 = shape.radius(z1 * 1000) / 1000
            area += math.pi * (r0 + r1) * math.hypot(z1 - z0, r1 - r0)
        concrete(ct.id, ct.concrete, "coolingTower", area * ct.thickness / 1000)
    for o in special.offshore:
        try:
            geometry = jacket_shape(o).local()
            by_type = {}
            for m in geometry.members:
                by_type[m.type] = by_type.get(m.type, 0.0) + float(math.dist(m.start, m.end)) / 1000
            for type_id, length in by_type.items():
                kind_ = member_type(type_id, objects, materials)
                obj = next(x for x in objects.objects if x.id == type_id)
                steel(
                    o.id,
                    obj.material,
                    "offshore",
                    length * kind_.section.mass,
                    f"{kind_.label} ({length:.1f} m)",
                )
        except (ValueError, AttributeError, StopIteration) as error:
            notes.append(f"{o.id}: not measured ({error})")
    for p in special.piping:
        length = sum(
            math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
            for a, b in zip(p.route, p.route[1:], strict=False)
        )
        lines.append(
            {
                "group": "special",
                "key": ("pipe", p.material, p.outsideDiameter, p.wallThickness),
                "description": f"Pipe {p.material}, {p.outsideDiameter:g} × {p.wallThickness:g} mm",
                "unit": "m",
                "element": p.id,
                "quantity": length,
                "material": None,
                "kind": "piping",
            }
        )
    return lines, notes
