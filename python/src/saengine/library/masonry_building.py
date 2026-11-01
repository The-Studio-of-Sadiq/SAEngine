"""A low-rise load-bearing masonry building from a grid and storeys (T31).

The New Building wizard's "Load-bearing masonry" system (``BuildingSpec.system == "masonry"``,
:func:`saengine.library.generator.generate_building` hands it here). On every grid line, between
each pair of adjacent intersections and in every storey, a structural masonry wall; in every
bay a two-way RC slab spanning onto the walls (in the analysis as shells, since there are no
beams); strip footings under the walls of each grid line. No columns or beams.

- The structural system is the first masonry bearing wall system that BNBC 2020 Part 6 Table
  6.2.19 permits in the Seismic Design Category and height: ordinary plain masonry shear walls,
  else ordinary reinforced masonry shear walls (Sec 2.5.5.4). Neither is permitted in Category
  D: the spec is refused with a note (confined masonry is a planned feature; an RC system
  serves meanwhile).
- The masonry is the default first-class brick (03 Materials ``BRICK-1``) with a unit strength
  of 17.2 MPa where none is entered (a first-class brick, SAEngine's assumption to replace with
  the test value); f'm is the code pack's estimate from the units and the mortar grade
  (:func:`saengine.design.masonry.prism_estimate`, used with the reduced allowable stresses)
  and Em is the pack's (``masonry.elastic``).
- Walls: 250 mm (one brick) in the top three storeys, 375 mm (one and a half bricks) below
  them (rule of thumb). Reinforced masonry walls get one central layer of 16 mm bars at 800 mm
  vertically and 12 mm at 400 mm horizontally (within the bar sizes and spacings of the code
  pack's seismic detailing of reinforced walls in Zones 2 and 3, ``masonry.seismic``).
- Slabs: BNBC 2020 Part 6 Eq. 6.6.6 (αfm > 2, the walls as stiff supports), ln (0.8 + fy/1400)
  / (36 + 9 β) ≥ 90 mm, at least the spec's least slab, rounded up to 5 mm.
- Strip footings: width from 1.1 × the gravity service load per metre of wall (the walls' own
  weight, and the slabs' dead, superimposed and live load over half the bays on each side) /
  qa, at least 600 mm, rounded up to 100 mm; thickness max(300 mm, width / 3).

Design mode then checks the walls (:mod:`saengine.design.masonry`) from the analysis.
"""

from __future__ import annotations

from typing import Any

from saengine.library import bnbc
from saengine.library.defaults import default_material_library
from saengine.library.floorplan import FloorPlan
from saengine.library.generator import (
    DEFAULT_BEARING,
    BuildingSpec,
    G,
    _deep_merge,
    _system,
    _template,
    ceil_to,
    letters,
    settings_patch,
)
from saengine.library.materials import Category, MaterialDefaults
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import ProjectSettings
from saengine.library.substructure import Substructure

#: The default masonry of 03 Materials the walls are made of.
BRICK_ID = "BRICK-1"
#: Unit strength assumed for a first-class brick without a test value [MPa] (SAEngine).
FIRST_CLASS_BRICK = 17.2
#: Wall thickness of the top storeys and below them [mm] (one and one and a half bricks).
THIN_WALL, THICK_WALL = 250.0, 375.0
#: Storeys from the top with the thin wall.
THIN_STOREYS = 3
#: Storeys above which the template warns that it is meant for low-rise buildings.
LOW_RISE = 5
#: Bars of a reinforced masonry wall: (dia, spacing) vertical and horizontal [mm].
VERTICAL_BARS, HORIZONTAL_BARS = (16.0, 800.0), (12.0, 400.0)


def generate_masonry_building(
    spec: BuildingSpec | dict[str, Any], settings: Any = None
) -> dict[str, Any]:
    """The parts of a load-bearing masonry building (see the module notes); the result has
    the keys of :func:`saengine.library.generator.generate_building`. Raises ``ValueError``
    where no masonry system is permitted."""
    from saengine.design import masonry as M

    s = spec if isinstance(spec, BuildingSpec) else BuildingSpec.model_validate(spec)
    notes: list[str] = []

    # ── materials ──
    materials = default_material_library()
    concrete = materials.get(s.concrete)
    if concrete is None or concrete.category != Category.CONCRETE or concrete.concrete is None:
        raise ValueError(f"'{s.concrete}' is not a concrete of the default materials")
    rebar = materials.get(s.rebar)
    if rebar is None or rebar.category != Category.REBAR or rebar.steel is None:
        raise ValueError(f"'{s.rebar}' is not a rebar of the default materials")
    materials.defaults = MaterialDefaults(concrete=s.concrete, rebar=s.rebar)
    brick = materials.get(BRICK_ID)
    if brick is None or brick.masonry is None:  # pragma: no cover - the default library has it
        raise ValueError(f"the default materials have no masonry '{BRICK_ID}'")
    if brick.masonry.fm is None and brick.masonry.unitStrength is None:
        brick.masonry.unitStrength = FIRST_CLASS_BRICK
    masonry = M.masonry_of(brick, {m.id: m for m in materials.materials})
    brick.mechanical.E = round(masonry.em, 0)
    if brick.mechanical.nu is None:
        brick.mechanical.nu = 0.2
    notes.append(
        f"Masonry {BRICK_ID}: unit strength {brick.masonry.unitStrength:g} MPa assumed for a "
        f"first-class brick (enter the test value), mortar {masonry.mortar or '-'}, f'm = "
        f"{masonry.fm:.1f} MPa estimated from the units, Em = {masonry.em:.0f} MPa "
        f"({M.clause('elastic')}); with an estimated f'm the walls are checked at "
        f"{M.allowable_share(masonry):.0%} of the allowable stresses ({M.clause('quality')}): "
        "prism tests and special inspection allow the full values (03 Materials)."
    )
    fy = rebar.steel.fy
    gamma_c = (concrete.mechanical.density or 2400.0) * G / 1000.0  # kN/m³
    gamma_m = (brick.mechanical.density or 1920.0) * G / 1000.0

    # ── settings ──
    base_json, patch, sdc, zone = settings_patch(s, settings, notes)
    stories = s.story_list()
    n = len(stories)
    height_m = sum(st.height for st in stories) / 1000
    try:
        system_id, _walls, system_notes = _system("masonry", sdc, height_m)
    except ValueError as error:
        raise ValueError(
            f"no masonry bearing wall system is permitted in Seismic Design Category "
            f"{sdc or 'B'} at {height_m:.1f} m (BNBC 2020 Part 6 Table 6.2.19): choose an RC "
            "system (confined masonry is planned)"
        ) from error
    patch["seismic"] = {"system": system_id}
    patch["analysis"] = {"slabs": "shells"}  # no beams: the slabs carry their loads as shells
    final = ProjectSettings.model_validate(_deep_merge(base_json, patch))
    reinforced = system_id == "masonryOrdinaryReinforced"
    notes.append(
        f"Seismic Design Category {sdc or '-'} (zone {zone or '-'}, site class "
        f"{final.site.siteClass}, occupancy category {final.occupancy.category}); system "
        f"{bnbc.STRUCTURAL_SYSTEMS[system_id].name} (Table 6.2.19)."
    )
    notes += system_notes
    if n > LOW_RISE:
        notes.insert(
            0,
            f"WARNING - {n} storeys: the masonry template is meant for low-rise buildings (up "
            f"to {LOW_RISE} storeys); check the walls' axial strength and slenderness first.",
        )
    notes.append("PRELIMINARY sizes: the analysis and Design mode check every wall and slab.")

    # ── grids and storeys ──
    xs = [0.0]
    for d in s.gridsX:
        xs.append(xs[-1] + d)
    ys = [0.0]
    for d in s.gridsY:
        ys.append(ys[-1] + d)
    xl = [letters(i) for i in range(len(xs))]
    yl = [str(j + 1) for j in range(len(ys))]
    nx, ny = len(xs), len(ys)
    levels = [s.baseElevation]
    for st in stories:
        levels.append(levels[-1] + st.height)
    story_ids = ["BASE"] + [f"L{k}" for k in range(1, n + 1)]

    def thickness(k: int) -> float:
        """Wall thickness of storey k (1 = the lowest)."""
        return THIN_WALL if k > n - THIN_STOREYS else THICK_WALL

    # ── object types ──
    objects: list[dict[str, Any]] = []
    type_ids: set[str] = set()

    def add(data: dict[str, Any]) -> str:
        if data["id"] not in type_ids:
            type_ids.add(data["id"])
            objects.append(data)
        return data["id"]

    def wall_type(t: float) -> str:
        data = _template(
            "Wall",
            id=f"MW{t:g}",
            name=f"{'Reinforced' if reinforced else 'Brick'} masonry wall {t:g}",
            material=BRICK_ID,
            thickness=t,
        )
        if reinforced:
            data["reinforcement"] = {
                "material": s.rebar,
                "cover": 50,
                "vertical": {"dia": VERTICAL_BARS[0], "spacing": VERTICAL_BARS[1]},
                "horizontal": {"dia": HORIZONTAL_BARS[0], "spacing": HORIZONTAL_BARS[1]},
                "layers": 1,
            }
        return add(data)

    slab_of: dict[tuple[int, int], float] = {}
    for i in range(nx - 1):
        for j in range(ny - 1):
            t_wall = thickness(n)
            lx, ly = xs[i + 1] - xs[i] - t_wall, ys[j + 1] - ys[j] - t_wall
            ln, short = max(lx, ly), max(min(lx, ly), 1.0)
            beta = ln / short
            h = max(ln * (0.8 + fy / 1400) / (36 + 9 * beta), 90.0, s.minSlab)
            slab_of[(i, j)] = ceil_to(h, 5)

    def slab_type(t: float) -> str:
        return add(
            _template(
                "Slab",
                id=f"S{t:g}",
                name=f"Slab {t:g}",
                material=s.concrete,
                thickness=t,
                system="twoWay",
            )
        )

    # ── the floor plan ──
    def gp(i: int, j: int) -> dict[str, str]:
        return {"x": xl[i], "y": yl[j]}

    def name(i: int, j: int) -> str:
        return f"{xl[i]}{yl[j]}"

    lines = [((i, j), (i + 1, j)) for j in range(ny) for i in range(nx - 1)]
    lines += [((i, j), (i, j + 1)) for i in range(nx) for j in range(ny - 1)]
    walls, slabs = [], []
    for k in range(1, n + 1):
        sid = story_ids[k]
        for a, b in lines:
            walls.append(
                {
                    "id": f"W-{name(*a)}-{name(*b)}-{sid}",
                    "type": wall_type(thickness(k)),
                    "base": story_ids[k - 1],
                    "top": sid,
                    "start": gp(*a),
                    "end": gp(*b),
                }
            )
        for (i, j), t in sorted(slab_of.items()):
            slabs.append(
                {
                    "id": f"S-{name(i, j)}-{sid}",
                    "type": slab_type(t),
                    "story": sid,
                    "boundary": [gp(i, j), gp(i + 1, j), gp(i + 1, j + 1), gp(i, j + 1)],
                }
            )
    # Typical floors: the storeys above L1 with the same wall thickness as L2.
    similar = {
        k: 2 for k in range(3, n + 1) if s.typical and n >= 3 and thickness(k) == thickness(2)
    }
    plan = FloorPlan.model_validate(
        {
            "grids": {
                "x": [{"label": xl[i], "position": xs[i]} for i in range(nx)],
                "y": [{"label": yl[j], "position": ys[j]} for j in range(ny)],
            },
            "stories": [
                {
                    "id": story_ids[k],
                    "name": "Base" if k == 0 else stories[k - 1].name,
                    "elevation": levels[k],
                    **({"similarTo": story_ids[similar[k]]} if k in similar else {}),
                }
                for k in range(n + 1)
            ],
            "columns": [],
            "beams": [],
            "walls": walls,
            "slabs": slabs,
        }
    )
    library = ObjectLibrary.model_validate({"objects": objects})
    problems = [*library.check_materials(materials), *plan.check_objects(library)]
    if problems:  # pragma: no cover - a generator bug
        raise ValueError("; ".join(problems))

    # ── 09 Substructure: a strip footing under the walls of each grid line ──
    qa = s.allowableBearing or final.foundation.allowableBearing or DEFAULT_BEARING
    floor_load = next(a for a in final.areaLoads if a.id == final.floorLoad)
    roof_load = next(a for a in final.areaLoads if a.id == final.roofLoad)
    foundations: list[dict[str, Any]] = []
    if s.footing != "none":
        if s.footing == "mat":
            notes.append(
                "A mat is not generated under masonry walls: strip footings are placed instead."
            )

        def tributary(index: int, spacings: list[float]) -> float:
            """Half the bays on each side of grid line ``index`` [mm]."""
            left = spacings[index - 1] / 2 if index > 0 else 0.0
            right = spacings[index] / 2 if index < len(spacings) else 0.0
            return left + right

        def line_load(width: float) -> float:
            """Gravity service load per metre of a wall line with ``width`` [mm] of slabs on it
            [kN/m]: every storey's wall and slab."""
            total = 0.0
            for k in range(1, n + 1):
                t_slab = max(slab_of.values(), default=s.minSlab)
                load = roof_load if k == n else floor_load
                q = t_slab / 1000 * gamma_c + load.finish + load.partitions + load.live
                total += q * width / 1000
                total += thickness(k) / 1000 * stories[k - 1].height / 1000 * gamma_m
            return total

        groups = [("x", j, tributary(j, s.gridsY)) for j in range(ny)]
        groups += [("y", i, tributary(i, s.gridsX)) for i in range(nx)]
        for axis, index, width in groups:
            w = line_load(width)
            b = max(600.0, ceil_to(1.1 * w / qa * 1000, 100))
            if axis == "x":
                path = [[xs[0], ys[index]], [xs[-1], ys[index]]]
                carried = [f"W-{name(i, index)}-{name(i + 1, index)}-L1" for i in range(nx - 1)]
                fid = f"F-{yl[index]}"
            else:
                path = [[xs[index], ys[0]], [xs[index], ys[-1]]]
                carried = [f"W-{name(index, j)}-{name(index, j + 1)}-L1" for j in range(ny - 1)]
                fid = f"F-{xl[index]}"
            foundations.append(
                {
                    "id": fid,
                    "type": "strip",
                    "columns": carried,
                    "path": path,
                    "width": b,
                    "thickness": max(300.0, ceil_to(b / 3, 50)),
                    "material": s.concrete,
                    "note": f"Preliminary: gravity service load {w:.0f} kN/m, qa {qa:g} kPa.",
                }
            )
        notes.append(
            "Strip footings under the walls of every grid line: width = 1.1 w / qa rounded up "
            "to 100 mm (at least 600 mm), w the gravity service load per metre (the walls' own "
            "weight and the slabs' dead, superimposed and live load over half the bays on each "
            f"side), qa = {qa:g} kPa; thickness max(300 mm, width/3). Part 9 designs them."
        )
    substructure = Substructure.model_validate({"foundations": foundations})

    notes.append(
        f"Masonry walls on every grid line: {THIN_WALL:g} mm (one brick) in the top "
        f"{THIN_STOREYS} storeys, {THICK_WALL:g} mm below (rule of thumb); add the door and "
        "window openings in 06 BIM (they make piers and lintels)."
        + (
            f" Reinforced masonry (Category {sdc}): one central layer of "
            f"{VERTICAL_BARS[0]:g} mm bars at {VERTICAL_BARS[1]:g} mm vertically and "
            f"{HORIZONTAL_BARS[0]:g} mm at {HORIZONTAL_BARS[1]:g} mm horizontally, in grouted "
            "cells or cavities."
            if reinforced
            else " Plain (unreinforced) masonry."
        )
    )
    notes.append(
        "Slabs: two-way, BNBC 2020 Part 6 Eq. 6.6.6 with the walls as stiff supports, ln "
        "(0.8 + fy/1400) / (36 + 9 β) ≥ 90 mm, at least the least slab, in the analysis as "
        "shells (no beams)."
    )
    summary = {
        "sdc": sdc,
        "warnings": [],
        "suggestCoreWalls": False,
        "columnReasons": {},
        "zone": zone,
        "system": system_id,
        "counts": {
            "columns": 0,
            "beams": 0,
            "walls": len(walls),
            "slabs": len(slabs),
            "foundations": len(foundations),
        },
        "columnTypes": {},
        "beamTypes": [],
        "wallTypes": sorted({o["id"] for o in objects if o["kind"] == "wall"}),
        "slabTypes": sorted({o["id"] for o in objects if o["kind"] == "slab"}),
        "families": [[story_ids[2], *(story_ids[k] for k in sorted(similar))]] if similar else [],
        "lateralSizing": None,
        "stiffness": None,
        "baseServiceLoads": {},
        "masonry": {
            "fm": round(masonry.fm, 2),
            "em": round(masonry.em, 0),
            "reinforced": reinforced,
        },
    }
    dump = {"mode": "json", "by_alias": True, "exclude_none": True}
    return {
        "materials": materials.model_dump(**dump),
        "objects": library.model_dump(**dump),
        "floorPlan": plan.model_dump(**dump),
        "substructure": substructure.model_dump(**dump),
        "settings": final.model_dump(**dump),
        "settingsPatch": patch,
        "notes": notes,
        "summary": summary,
    }


__all__ = ["generate_masonry_building"]
