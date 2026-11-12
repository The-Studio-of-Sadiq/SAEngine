"""Fabrication detailing (LOD 400) of the routed services of 07 MEP (alpha 9 L11).

An option on the routed runs of ``07 MEP/mep.json``: the HVAC ducts, the fire mains and risers,
the cable trays and the plumbing risers. For each run, :func:`detail_run` gives

- the fittings: an elbow at every change of direction (its angle, its centre-line radius as a
  multiple of the size, the take-out it removes from each straight), a tee where the run meets
  another run of its family on the same storey, and the risers' branch tees at every storey they
  serve;
- the straight cut pieces between the fittings, cut to the stock or section length, each with a
  mark ("<run>-P01") and its cut length;
- the spools: shop assemblies of consecutive pieces and fittings up to the spool length, with
  their marks (the spool sheets);
- the hangers (horizontal runs) or supports (risers): one within ``nearFitting`` of every fitting
  and end, and the rest at no more than the largest spacing, with the rod length to the slab
  soffit above and the load a hanger carries.

The largest spacings come from the code pack's ``mepFabrication`` table (by pipe material and
diameter, by duct size, the fire mains' hangers and their design load); a value the project gives
in ``07 MEP/fabrication.json`` (:class:`FabricationOptions`) wins, and where neither gives one the
run's supports are not detailed (said in its notes). The radii, stock lengths, near-fitting
distance, wall thicknesses and densities are SAEngine practice defaults of the options, editable.

:func:`write_sheets` writes a spool sheet per run as DXF (ezdxf: the run in plan with the piece,
fitting and hanger marks, and its cut list) and the cut list, fittings and hangers as CSV into
``11 Exports/MEP Fabrication``. The plumbing's horizontal branches (worked out by
:mod:`saengine.plumbing.branches`), sanitary fittings (wyes, traps) and seismic bracing are not
detailed yet.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

FABRICATION_FILE = "07 MEP/fabrication.json"
SHEETS_FOLDER = "11 Exports/MEP Fabrication"
WATER = 1000.0  # kg/m³


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PipeWall(_Model):
    wall: float = Field(gt=0, description="Wall thickness [mm].")
    density: float = Field(gt=0, description="[kg/m³]")


class Spacing(_Model):
    horizontal: float | None = Field(default=None, gt=0, description="[mm]")
    vertical: float | None = Field(default=None, gt=0, description="[mm]")


class FabricationOptions(_Model):
    """``07 MEP/fabrication.json``: what to detail and the shop's practice (SAEngine defaults)."""

    schema_: str = Field(default="saengine.mepFabrication/1", alias="schema")
    ducts: bool = True
    fireMains: bool = True
    trays: bool = True
    risers: bool = True
    pipeStock: float = Field(default=6000, gt=0, description="Pipe stock length [mm].")
    rectDuctSection: float = Field(default=1500, gt=0, description="[mm]")
    roundDuctSection: float = Field(default=3000, gt=0, description="[mm]")
    traySection: float = Field(default=3000, gt=0, description="[mm]")
    spoolLength: float = Field(default=6000, gt=0, description="Longest shop spool [mm].")
    pipeElbowRadius: float = Field(default=1.5, gt=0, description="x D (long radius).")
    rectDuctElbowRadius: float = Field(default=1.0, gt=0, description="x width.")
    roundDuctElbowRadius: float = Field(default=1.5, gt=0, description="x D.")
    trayElbowRadius: float = Field(default=300, gt=0, description="[mm]")
    nearFitting: float = Field(
        default=600, gt=0, description="A hanger within this of each fitting and end [mm]."
    )
    trayHangerSpacing: float = Field(
        default=1500, gt=0, description="Cable tray supports [mm] (no code table)."
    )
    ductSheet: list[list[float]] = Field(
        default_factory=lambda: [[750, 0.8], [1500, 1.0], [1e9, 1.2]],
        description="[[largest side mm, sheet thickness mm], ...] of duct sheet metal.",
    )
    pipeWalls: dict[str, PipeWall] = Field(
        default_factory=lambda: {
            "GI": PipeWall(wall=3.6, density=7850),
            "uPVC": PipeWall(wall=3.2, density=1400),
            "PPR": PipeWall(wall=3.4, density=900),
            "HDPE": PipeWall(wall=3.0, density=950),
            "CI": PipeWall(wall=6.0, density=7200),
        }
    )
    fireMainMaterial: str = Field(default="GI", description="Material of the fire mains.")
    spacings: dict[str, Spacing] = Field(
        default_factory=dict,
        description="The project's own largest spacings by pipe material, 'duct', 'tray' or "
        "'fireMain': win over the code pack's.",
    )


def parse_options(text: str | None) -> FabricationOptions:
    return (
        FabricationOptions.model_validate_json(text)
        if text and text.strip()
        else (FabricationOptions())
    )


# ─────────────────────────────────── supports ───────────────────────────────────


def _table() -> Any:
    from saengine.mep.code_pack import table

    return table("mepFabrication")


def pipe_spacing(
    material: str, diameter: float, options: FabricationOptions, vertical: bool = False
) -> tuple[float | None, str]:
    """Largest support spacing [mm] of a pipe and where it comes from."""
    own = options.spacings.get(material)
    value = (own.vertical if vertical else own.horizontal) if own else None
    if value:
        return value, "project (07 MEP/fabrication.json)"
    from saengine.mep.code_pack import code_name

    found = _table()
    if found is None:
        return None, f"not covered by the code pack {code_name()}: give the spacing"
    for row in found.pipeSupports:
        if row.material.lower() != material.lower():
            continue
        if row.minDiameter is not None and diameter <= row.minDiameter:
            continue
        if row.maxDiameter is not None and diameter > row.maxDiameter:
            continue
        clause = found.clauses.get("pipeSupports", "")
        return (row.vertical if vertical else row.horizontal), f"{code_name()} {clause}".strip()
    return None, f"no {material} pipe in the code pack's support table: give the spacing"


def duct_spacing(size: float, options: FabricationOptions) -> tuple[float | None, str]:
    own = options.spacings.get("duct")
    if own and own.horizontal:
        return own.horizontal, "project (07 MEP/fabrication.json)"
    from saengine.mep.code_pack import code_name

    found = _table()
    if found is None or not found.ductSupports:
        return None, f"not covered by the code pack {code_name()}: give the spacing"
    clause = found.clauses.get("ductSupports", "")
    for row in found.ductSupports:
        if row.maxSize is None or size <= row.maxSize:
            return row.spacing, f"{code_name()} {clause}".strip()
    return found.ductSupports[-1].spacing, f"{code_name()} {clause}".strip()


# ─────────────────────────────────── geometry ───────────────────────────────────


def _turn(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    """The change of direction at ``b`` [°] (0: straight on)."""
    u = (b[0] - a[0], b[1] - a[1])
    v = (c[0] - b[0], c[1] - b[1])
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu == 0 or nv == 0:
        return 0.0
    cos = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))
    return math.degrees(math.acos(cos))


def _elbow(angle: float) -> str:
    for nominal in (90.0, 45.0, 22.5, 11.25):
        if abs(angle - nominal) <= 2.0:
            return f"elbow {nominal:g}°"
    return f"elbow {angle:.0f}° (special)"


def _cut(length: float, stock: float) -> list[float]:
    """``length`` cut into pieces of at most ``stock`` (full lengths, then the rest)."""
    if length <= 1.0:
        return []
    count = int(length // stock)
    pieces = [stock] * count
    rest = length - count * stock
    if rest > 1.0:
        pieces.append(rest)
    return pieces


def _hanger_positions(length: float, near: float, spacing: float) -> list[float]:
    """Hanger stations along a straight of ``length`` [mm]: within ``near`` of each end (a
    fitting or an end of the run), the rest at no more than ``spacing``."""
    if length <= 0:
        return []
    first = min(near, length / 2)
    last = max(length - near, first)
    stations = [first]
    span = last - first
    if span > 1e-6:
        count = max(1, math.ceil(span / spacing - 1e-9))
        stations += [first + span * k / count for k in range(1, count + 1)]
    return stations


def detail_run(
    run: dict[str, Any], options: FabricationOptions, others: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Fittings, cut pieces, spools and hangers of one horizontal run.

    ``run``: ``{id, family ("duct", "fireMain", "tray"), system, size (mm: width or diameter),
    depth (mm, rectangular), round (bool), material, path [[x, y], ...], z (centre line [mm]),
    soffit (mm), spacing (mm or None), spacingSource, unitMass (kg/m, full)}``. ``others``: the
    other runs of its family on its storey (for tees)."""
    path = [(float(p[0]), float(p[1])) for p in run["path"]]
    family, size = run["family"], float(run["size"])
    notes: list[str] = []
    if family == "duct":
        radius = (
            options.roundDuctElbowRadius * size
            if run.get("round")
            else options.rectDuctElbowRadius * size
        )
        stock = options.roundDuctSection if run.get("round") else options.rectDuctSection
    elif family == "tray":
        radius, stock = options.trayElbowRadius, options.traySection
    else:
        radius, stock = options.pipeElbowRadius * size, options.pipeStock
    z = float(run["z"])
    fittings: list[dict[str, Any]] = []
    takeouts = [0.0] * len(path)
    for k in range(1, len(path) - 1):
        angle = _turn(path[k - 1], path[k], path[k + 1])
        if angle < 1.0:
            continue
        takeouts[k] = radius * math.tan(math.radians(angle) / 2)
        fittings.append(
            {
                "mark": f"{run['id']}-F{len(fittings) + 1:02d}",
                "type": _elbow(angle),
                "angle": round(angle, 1),
                "radius": round(radius, 0),
                "at": [round(path[k][0], 1), round(path[k][1], 1), round(z, 1)],
                "size": run["label"],
            }
        )
    # Tees: an end of another run of the family on one of this run's straights.
    from shapely.geometry import LineString, Point

    line = LineString(path) if len(path) >= 2 else None
    for other in others or []:
        if line is None or other["id"] == run["id"]:
            continue
        for end in (other["path"][0], other["path"][-1]):
            p = Point(float(end[0]), float(end[1]))
            if line.distance(p) <= max(size / 2, 50.0):
                d = line.project(p)
                if 1.0 < d < line.length - 1.0:
                    fittings.append(
                        {
                            "mark": f"{run['id']}-F{len(fittings) + 1:02d}",
                            "type": "tee",
                            "branch": other["id"],
                            "at": [round(p.x, 1), round(p.y, 1), round(z, 1)],
                            "size": f"{run['label']} x {other['label']}",
                            "station": round(d, 1),
                        }
                    )
    # Straights between the fittings, cut to stock.
    pieces: list[dict[str, Any]] = []
    hangers: list[dict[str, Any]] = []
    spacing = run.get("spacing")
    rod = max(float(run["soffit"]) - (z + float(run.get("depth") or size) / 2), 0.0)
    walked = 0.0
    for k in range(len(path) - 1):
        a, b = path[k], path[k + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg <= 0:
            continue
        ux, uy = (b[0] - a[0]) / seg, (b[1] - a[1]) / seg
        start, end = takeouts[k], seg - takeouts[k + 1]
        straight = end - start
        if straight < -1.0:
            notes.append(
                f"segment {k + 1} ({seg:.0f} mm) is shorter than its elbows' take-outs: "
                "a special fitting is needed"
            )
            straight = 0.0
        offset = start
        for piece in _cut(straight, stock):
            p0 = (a[0] + ux * offset, a[1] + uy * offset)
            p1 = (a[0] + ux * (offset + piece), a[1] + uy * (offset + piece))
            pieces.append(
                {
                    "mark": f"{run['id']}-P{len(pieces) + 1:02d}",
                    "length": round(piece, 0),
                    "from": [round(p0[0], 1), round(p0[1], 1)],
                    "to": [round(p1[0], 1), round(p1[1], 1)],
                    "station": round(walked + offset, 1),
                }
            )
            offset += piece
        if spacing:
            for s in _hanger_positions(straight, options.nearFitting, float(spacing)):
                x, y = a[0] + ux * (start + s), a[1] + uy * (start + s)
                hangers.append(
                    {
                        "mark": f"{run['id']}-H{len(hangers) + 1:02d}",
                        "at": [round(x, 1), round(y, 1), round(z, 1)],
                        "rod": round(rod, 0),
                        "station": round(walked + start + s, 1),
                    }
                )
        walked += seg
    if not spacing:
        notes.append(f"supports not detailed: {run.get('spacingSource')}")
    # The load a hanger carries: the run's mass over the larger of the gaps either side.
    stations = [h["station"] for h in hangers]
    unit = float(run.get("unitMass") or 0.0)  # kg/m
    rule = run.get("hangerLoad")
    for i, h in enumerate(hangers):
        before = stations[i] - (stations[i - 1] if i else 0.0)
        after = (stations[i + 1] if i + 1 < len(stations) else walked) - stations[i]
        tributary = (before + after) / 2 / 1000  # m
        load = unit * tributary
        if rule:
            load = load * rule["loadFactor"] + rule["extraMass"]
        h["spacing"] = round(max(before, after), 0)
        h["load"] = round(load, 1)
    # Spools: consecutive pieces up to the spool length, with the fittings between them.
    spools: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    fit_by_station = sorted(
        ((f.get("station") or _station(path, f["at"])), f["mark"]) for f in fittings
    )
    for piece in pieces:
        if current is None or current["length"] + piece["length"] > options.spoolLength:
            current = {
                "mark": f"{run['id']}-S{len(spools) + 1:02d}",
                "pieces": [],
                "fittings": [],
                "length": 0.0,
                "start": piece["station"],
            }
            spools.append(current)
        current["pieces"].append(piece["mark"])
        current["length"] += piece["length"]
        current["end"] = piece["station"] + piece["length"]
    for station, mark in fit_by_station:
        for spool in spools:
            if spool["start"] - 1 <= station <= spool["end"] + radius * 2 + 1:
                spool["fittings"].append(mark)
                break
    for spool in spools:
        spool["length"] = round(spool["length"], 0)
        spool.pop("start", None)
        spool.pop("end", None)
    return {
        "id": run["id"],
        "family": family,
        "system": run.get("system"),
        "story": run.get("story"),
        "size": run["label"],
        "material": run.get("material"),
        "length": round(walked / 1000, 3),
        "pieces": pieces,
        "fittings": fittings,
        "hangers": hangers,
        "spools": spools,
        "supportRule": run.get("spacingSource"),
        "notes": notes,
    }


def _station(path: list[tuple[float, float]], at: list[float]) -> float:
    from shapely.geometry import LineString, Point

    return LineString(path).project(Point(at[0], at[1]))


def detail_riser(
    riser: dict[str, Any], options: FabricationOptions, elevations: list[tuple[str, float]]
) -> dict[str, Any]:
    """A vertical riser: pieces cut to stock between its ends, a branch tee at every storey it
    serves, a support at every floor it passes and between at no more than the spacing."""
    bottom, top = float(riser["bottom"]), float(riser["top"])
    height = max(top - bottom, 0.0)
    pieces = []
    at = bottom
    for n, piece in enumerate(_cut(height, options.pipeStock), start=1):
        pieces.append({"mark": f"{riser['id']}-P{n:02d}", "length": round(piece, 0),
                       "from": round(at, 1), "to": round(at + piece, 1)})  # fmt: skip
        at += piece
    fittings = []
    serves = riser.get("serves")
    for story, z in elevations:
        if bottom - 1 <= z <= top + 1 and (serves is None or story in serves):
            fittings.append(
                {
                    "mark": f"{riser['id']}-F{len(fittings) + 1:02d}",
                    "type": "branch tee",
                    "story": story,
                    "at": [riser["x"], riser["y"], round(z + 300, 1)],
                    "size": riser["label"],
                }
            )
    supports = []
    spacing = riser.get("spacing")
    if spacing:
        floors = sorted(z for _, z in elevations if bottom - 1 <= z <= top + 1)
        marks = sorted(set(floors) | {bottom})
        stations = []
        for lo, hi in zip(marks, [*marks[1:], top], strict=False):
            stations.append(lo)
            gap = hi - lo
            count = max(1, math.ceil(gap / float(spacing) - 1e-9))
            stations += [lo + gap * k / count for k in range(1, count)]
        unit = float(riser.get("unitMass") or 0.0)
        for n, z in enumerate(sorted({round(s, 1) for s in stations}), start=1):
            supports.append(
                {
                    "mark": f"{riser['id']}-H{n:02d}",
                    "at": [riser["x"], riser["y"], z],
                    "type": "floor clamp"
                    if any(abs(z - f) < 1 for f in floors)
                    else "wall bracket",
                    "load": round(unit * float(spacing) / 1000, 1),
                    "spacing": round(float(spacing), 0),
                }
            )
    return {
        "id": riser["id"],
        "family": riser["family"],
        "system": riser.get("system"),
        "size": riser["label"],
        "material": riser.get("material"),
        "length": round(height / 1000, 3),
        "pieces": pieces,
        "fittings": fittings,
        "hangers": supports,
        "spools": [
            {
                "mark": f"{riser['id']}-S{n:02d}",
                "pieces": [p["mark"]],
                "fittings": [],
                "length": p["length"],
            }
            for n, p in enumerate(pieces, start=1)
        ],
        "supportRule": riser.get("spacingSource"),
        "notes": [] if spacing else [f"supports not detailed: {riser.get('spacingSource')}"],
    }


# ─────────────────────────────────── the project ───────────────────────────────────


def _pipe_mass(diameter: float, material: str, options: FabricationOptions) -> float:
    """kg/m of a water-filled pipe of nominal (outside) ``diameter``."""
    wall = options.pipeWalls.get(material)
    t = wall.wall if wall else 0.0
    inner = max(diameter - 2 * t, 0.0)
    water = math.pi * inner * inner / 4 * 1e-6 * WATER
    pipe = math.pi * (diameter - t) * t * 1e-6 * wall.density if wall else 0.0
    return water + pipe


def _duct_mass(width: float, height: float, round_: bool, options: FabricationOptions) -> float:
    size = max(width, height)
    t = next((th for limit, th in options.ductSheet if size <= limit), options.ductSheet[-1][1])
    perimeter = math.pi * width if round_ else 2 * (width + height)
    return perimeter * t * 1e-6 * 7850.0


def fabrication(
    mep_text: str, bim_text: str, objects_text: str | None, options: FabricationOptions
) -> dict[str, Any]:
    """The fabrication detailing of every routed run: ``{"runs", "totals", "notes"}``."""
    from saengine.library.bim import BuildingModel
    from saengine.library.mep import parse as parse_mep

    mep = parse_mep(mep_text)
    building = BuildingModel.model_validate_json(bim_text)
    stories = sorted(building.stories, key=lambda s: float(s.elevation))
    elevation = {s.id: float(s.elevation) for s in stories}
    thickness: dict[str, float] = {}
    if objects_text:
        types = {o.get("id"): o for o in json.loads(objects_text).get("objects", [])}
        for e in building.elements:
            if getattr(e, "kind", None) == "slab":
                t = float((types.get(e.type) or {}).get("thickness") or 0.0)
                key = round(float(e.elevation), 1)
                thickness[str(key)] = max(thickness.get(str(key), 0.0), t)
    notes: list[str] = []

    def soffit(story: str) -> float:
        z = elevation[story]
        above = [float(s.elevation) for s in stories if float(s.elevation) > z + 1]
        if not above:
            return z + 3000.0
        level = above[0]
        return level - thickness.get(str(round(level, 1)), 150.0)

    runs: list[dict[str, Any]] = []
    hvac = mep.hvac
    if options.ducts and hvac is not None:
        for d in hvac.ducts:
            if d.story not in elevation or len(d.path) < 2 or d.riser is not None:
                continue
            round_ = d.shape == "round"
            w = (
                float(d.diameter if round_ else (d.width or 0.0))
                if (d.diameter or d.width)
                else 0.0
            )
            h = (
                float(d.diameter if round_ else (d.height or 0.0))
                if (d.diameter or d.height)
                else 0.0
            )
            if w <= 0 or h <= 0:
                notes.append(f"duct {d.id}: no size given (size it in 7 MEP's HVAC first)")
                continue
            top = soffit(d.story) - 25.0
            z = (elevation[d.story] + d.bottom + h / 2) if d.bottom is not None else top - h / 2
            spacing, source = duct_spacing(max(w, h), options)
            runs.append({"id": d.id, "family": "duct", "system": d.system, "story": d.story,
                         "size": w, "depth": h, "round": round_,
                         "label": f"Ø{w:g}" if round_ else f"{w:g}x{h:g}",
                         "material": "galvanised sheet", "path": d.path, "z": z,
                         "soffit": soffit(d.story), "spacing": spacing, "spacingSource": source,
                         "unitMass": _duct_mass(w, h, round_, options)})  # fmt: skip
    fire = mep.fire
    table = _table()
    if options.fireMains and fire is not None:
        for m in fire.mains:
            if m.story not in elevation or m.diameter is None:
                if m.diameter is None:
                    notes.append(f"fire main {m.id}: no diameter given (size it first)")
                continue
            dia = float(m.diameter)
            z = (
                elevation[m.story] + m.bottom + dia / 2
                if m.bottom is not None
                else soffit(m.story) - 150.0 - dia / 2
            )
            own = options.spacings.get("fireMain")
            if own and own.horizontal:
                spacing, source = own.horizontal, "project (07 MEP/fabrication.json)"
            elif table is not None and table.fireMains is not None and table.fireMains.spacing:
                from saengine.mep.code_pack import code_name

                spacing = table.fireMains.spacing
                source = f"{code_name()} {table.clauses.get('fireMains', '')}".strip()
            else:
                spacing, source = pipe_spacing(options.fireMainMaterial, dia, options)
            load = None
            if table is not None and table.fireMains is not None:
                load = table.fireMains.model_dump()
            runs.append({"id": m.id, "family": "fireMain", "system": "fire main", "story": m.story,
                         "size": dia, "label": f"Ø{dia:g}", "material": options.fireMainMaterial,
                         "path": m.path, "z": z, "soffit": soffit(m.story), "spacing": spacing,
                         "spacingSource": source, "hangerLoad": load,
                         "unitMass": _pipe_mass(dia, options.fireMainMaterial, options)})  # fmt: skip
    electrical = mep.electrical
    if options.trays and electrical is not None:
        for t in electrical.trays:
            if t.story not in elevation:
                continue
            w, h = float(t.width), float(t.height)
            z = (
                elevation[t.story] + t.bottom + h / 2
                if t.bottom is not None
                else soffit(t.story) - 150.0 - h / 2
            )
            own = options.spacings.get("tray")
            spacing = own.horizontal if own and own.horizontal else options.trayHangerSpacing
            runs.append({"id": t.id, "family": "tray", "system": "cable tray", "story": t.story,
                         "size": w, "depth": h, "label": f"{w:g}x{h:g}", "material": "steel tray",
                         "path": t.path, "z": z, "soffit": soffit(t.story), "spacing": spacing,
                         "spacingSource": "project" if own else "SAEngine practice (no code table)",
                         "unitMass": 0.0})  # fmt: skip
    detailed = []
    for run in runs:
        others = [r for r in runs if r["family"] == run["family"] and r["story"] == run["story"]]
        detailed.append(detail_run(run, options, others))
    if options.risers:
        levels = [(s.id, float(s.elevation)) for s in stories]
        risers: list[dict[str, Any]] = []
        if mep.plumbing is not None:
            for r in mep.plumbing.risers:
                if r.diameter is None:
                    notes.append(f"riser {r.id}: no diameter given (size it first)")
                    continue
                material = r.material or "uPVC"
                spacing, source = pipe_spacing(material, float(r.diameter), options, vertical=True)
                risers.append({"id": r.id, "family": "riser", "system": r.system, "x": r.x,
                               "y": r.y, "label": f"Ø{float(r.diameter):g}", "material": material,
                               "serves": r.serves, "spacing": spacing, "spacingSource": source,
                               "unitMass": _pipe_mass(float(r.diameter), material, options),
                               "from": r.fromStory, "to": r.toStory})  # fmt: skip
        if fire is not None:
            for r in fire.risers:
                if r.diameter is None:
                    notes.append(f"fire riser {r.id}: no diameter given (size it first)")
                    continue
                material = options.fireMainMaterial
                spacing, source = pipe_spacing(material, float(r.diameter), options, vertical=True)
                risers.append({"id": r.id, "family": "fireRiser", "system": r.system, "x": r.x,
                               "y": r.y, "label": f"Ø{float(r.diameter):g}", "material": material,
                               "serves": None, "spacing": spacing, "spacingSource": source,
                               "unitMass": _pipe_mass(float(r.diameter), material, options),
                               "from": r.fromStory, "to": r.toStory})  # fmt: skip
        for r in risers:
            if r["from"] not in elevation or r["to"] not in elevation:
                continue
            r["bottom"] = elevation[r["from"]]
            r["top"] = soffit(r["to"]) if r["to"] != r["from"] else elevation[r["to"]] + 3000
            detailed.append(detail_riser(r, options, levels))
    fittings: dict[str, int] = {}
    for run in detailed:
        for f in run["fittings"]:
            fittings[f["type"]] = fittings.get(f["type"], 0) + 1
    totals = {
        "runs": len(detailed),
        "pieces": sum(len(r["pieces"]) for r in detailed),
        "spools": sum(len(r["spools"]) for r in detailed),
        "hangers": sum(len(r["hangers"]) for r in detailed),
        "rodLength": round(
            sum(h.get("rod", 0.0) for r in detailed for h in r["hangers"]) / 1000, 2
        ),
        "fittings": fittings,
    }
    if hvac is None and fire is None and electrical is None and mep.plumbing is None:
        notes.append("07 MEP has no routed services (ducts, fire mains, trays, risers)")
    return {"runs": detailed, "totals": totals, "notes": notes}


def to_csv(result: dict[str, Any]) -> dict[str, str]:
    """The cut list, the fittings and the hangers as CSV texts."""
    out = {}
    for name, key, columns in (
        ("cut-list.csv", "pieces", ["run", "mark", "length", "from", "to"]),
        ("fittings.csv", "fittings", ["run", "mark", "type", "angle", "size", "at"]),
        ("hangers.csv", "hangers", ["run", "mark", "at", "rod", "spacing", "load", "type"]),
    ):
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(columns)
        for run in result["runs"]:
            for row in run[key]:
                writer.writerow([run["id"], *(json.dumps(row.get(c)) if isinstance(row.get(c), list) else row.get(c, "") for c in columns[1:])])  # fmt: skip
        out[name] = buffer.getvalue()
    return out


def spool_sheet(run: dict[str, Any], path: Path) -> None:
    """One run's spool sheet as DXF: the run in plan (or elevation for a riser) with its piece,
    fitting and hanger marks, and the cut list as text."""
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    msp = doc.modelspace()
    for name, colour in (("PIECES", 5), ("FITTINGS", 1), ("HANGERS", 3), ("TEXT", 7)):
        doc.layers.add(name, color=colour)
    height = 150.0
    if run["family"] in ("riser", "fireRiser"):
        for p in run["pieces"]:
            msp.add_line((0, p["from"]), (0, p["to"]), dxfattribs={"layer": "PIECES"})
            msp.add_text(f"{p['mark']} L={p['length']:.0f}", height=height,
                         dxfattribs={"layer": "TEXT"}).set_placement((200, (p["from"] + p["to"]) / 2))  # fmt: skip
        for h in run["hangers"]:
            z = h["at"][2]
            msp.add_line((-150, z), (150, z), dxfattribs={"layer": "HANGERS"})
    else:
        for p in run["pieces"]:
            msp.add_line(tuple(p["from"]), tuple(p["to"]), dxfattribs={"layer": "PIECES"})
            mid = ((p["from"][0] + p["to"][0]) / 2, (p["from"][1] + p["to"][1]) / 2 + 200)
            msp.add_text(f"{p['mark']} {p['length']:.0f}", height=height,
                         dxfattribs={"layer": "TEXT"}).set_placement(mid)  # fmt: skip
        for f in run["fittings"]:
            x, y = f["at"][0], f["at"][1]
            msp.add_circle((x, y), 100, dxfattribs={"layer": "FITTINGS"})
            msp.add_text(f"{f['mark']} {f['type']}", height=height,
                         dxfattribs={"layer": "TEXT"}).set_placement((x + 150, y - 300))  # fmt: skip
        for h in run["hangers"]:
            x, y = h["at"][0], h["at"][1]
            msp.add_line((x - 100, y - 100), (x + 100, y + 100), dxfattribs={"layer": "HANGERS"})
            msp.add_line((x - 100, y + 100), (x + 100, y - 100), dxfattribs={"layer": "HANGERS"})
    lines = [
        f"SPOOL SHEET {run['id']}  {run.get('system') or ''}  {run['size']}  {run.get('material') or ''}",
        f"Supports: {run.get('supportRule') or '-'}",
        "Cut list:",
        *(f"  {p['mark']}  {p['length']:.0f} mm" for p in run["pieces"]),
        "Fittings:",
        *(f"  {f['mark']}  {f['type']}  {f.get('size', '')}" for f in run["fittings"]),
        "Spools:",
        *(
            f"  {s['mark']}  {', '.join(s['pieces'])}  {', '.join(s['fittings'])}"
            for s in run["spools"]
        ),
        f"Hangers: {len(run['hangers'])}",
        *(f"Note: {n}" for n in run.get("notes", [])),
    ]
    x0 = min([0.0] + [p["from"][0] for p in run["pieces"] if isinstance(p["from"], list)])
    y0 = min([0.0] + [p["from"][1] for p in run["pieces"] if isinstance(p["from"], list)]) - 1000
    for n, text in enumerate(lines):
        msp.add_text(text, height=height, dxfattribs={"layer": "TEXT"}).set_placement(
            (x0, y0 - n * height * 1.6)
        )
    doc.saveas(str(path))


def run_for_project(project_root: str, write: bool = True) -> dict[str, Any]:
    """The detailing of the project's routed services; with ``write`` the spool sheets and CSV
    lists in ``11 Exports/MEP Fabrication`` (``files``)."""
    root = Path(project_root)

    def read(rel: str) -> str | None:
        try:
            return (root / rel).read_text(encoding="utf-8")
        except OSError:
            return None

    mep_text, bim_text = read("07 MEP/mep.json"), read("06 BIM/bim.json")
    if not mep_text or not bim_text:
        return {"problems": ["07 MEP and 06 BIM are needed"]}
    try:
        options = parse_options(read(FABRICATION_FILE))
        result = fabrication(mep_text, bim_text, read("04 Objects/objects.json"), options)
    except ValueError as error:
        return {"problems": [str(error).strip().splitlines()[0]]}
    if write:
        folder = root / SHEETS_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        files = []
        for name, text in to_csv(result).items():
            (folder / name).write_text(text, encoding="utf-8")
            files.append(str(folder / name))
        for run in result["runs"]:
            target = folder / f"spool-{_safe(run['id'])}.dxf"
            spool_sheet(run, target)
            files.append(str(target))
        result["files"] = files
    return result


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
