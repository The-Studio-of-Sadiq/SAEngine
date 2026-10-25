"""Benchmarks of the analysis model's conventions (version 0.0.44): the seismic mass lumped at
the story levels, the eccentric static earthquake cases, rigid end zones with the forces at the
support faces, and a line load on a simply supported beam.

Each case builds a one-bay building through SAEngine's floor plan (``saengine.library.bim.
generate``) and :func:`saengine.fem.derive.derive_fem`, then checks the derived loads and masses
against hand calculations, or runs OpenSees Studio and compares the forces with closed forms.

Synthetic data: one bay 6 m (A-B) by 5 m (1-2), stories of 3.2 m, C24.1 concrete of the default
material library, 400 x 400 columns, 300 x 500 beams, 150 mm slabs; the default project settings.
Units: the floor plan in mm, the analysis model in m, N, Pa.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem.derive import pinned_twins
from saengine.library import FloorPlan, default_floor_plan
from saengine.library import line_loads as ll
from saengine.library.bim import generate
from saengine.library.settings import default_project_settings
from saengine.verification.cases.common import (
    BY_ID,
    MATERIALS,
    Case,
    G,
    Outcome,
    Quantity,
    Reference,
    derive,
    fmt,
    objects,
    run_model,
    settings,
)

CONCRETE = BY_ID["C24.1"]
DENSITY = CONCRETE.mechanical.density
COLUMN = {
    "id": "COL",
    "name": "Column 400x400",
    "kind": "column",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
}
BEAM = {
    "id": "BM",
    "name": "Beam 300x500",
    "kind": "beam",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
}
SLAB = {"id": "SL", "name": "Slab 150", "kind": "slab", "material": CONCRETE.id, "thickness": 150}
STEEL_BEAM = {
    "id": "SB",
    "name": "Steel beam, fin plates",
    "kind": "beam",
    "material": "A992",
    "profile": {
        "shape": "I",
        "overallWidth": 150,
        "overallDepth": 300,
        "webThickness": 7,
        "flangeThickness": 10,
    },
    "connection": {"type": "finPlate"},
}
CORNERS = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]
#: Exact element formulations: closed forms within 1 %; sums of loads within 0.1 %.
FRAME = 0.01
SUMS = 0.001


def _plan(stories: int = 2, slabs: bool = True, beam_type: str = "BM", only: str | None = None):
    levels = [{"id": "BASE", "name": "Base", "elevation": 0}] + [
        {"id": f"L{k}", "name": f"Level {k}", "elevation": 3200 * k} for k in range(1, stories + 1)
    ]
    top = f"L{stories}"
    beams = [
        {
            "id": f"B{k}{i + 1}",
            "type": beam_type,
            "story": f"L{k}",
            "start": {"x": a[0], "y": a[1]},
            "end": {"x": b[0], "y": b[1]},
        }
        for k in range(1, stories + 1)
        for i, (a, b) in enumerate(zip(CORNERS, CORNERS[1:] + CORNERS[:1], strict=True))
    ]
    if only is not None:
        beams = [b for b in beams if b["id"] == only]
    return FloorPlan.model_validate(
        {
            **default_floor_plan().model_dump(mode="json", by_alias=True),
            "stories": levels,
            "columns": [
                {
                    "id": f"C{i + 1}",
                    "type": "COL",
                    "at": {"x": x, "y": y},
                    "base": "BASE",
                    "top": top,
                }
                for i, (x, y) in enumerate(CORNERS)
            ],
            "beams": beams,
            "slabs": [
                {
                    "id": f"S{k}",
                    "type": "SL",
                    "story": f"L{k}",
                    "boundary": [{"x": x, "y": y} for x, y in CORNERS],
                }
                for k in range(1, stories + 1)
            ]
            if slabs
            else [],
        }
    )


# ─────────────────────────────── seismic mass at the story levels ───────────────────────────────


def story_mass(folder: Path) -> Outcome:
    s = default_project_settings("Verification")
    d = derive(
        generate(_plan(), "v"),
        objects(COLUMN, BEAM, SLAB),
        MATERIALS,
        settings(massLumping="storyLevels"),
    )
    loads = {a.id: a for a in s.areaLoads}
    floor, roof = loads[s.floorLoad], loads[s.roofLoad]
    gamma = DENSITY * G
    share = 0.5 if floor.live > 3.0 else 0.25
    slab, beams = 0.15 * 30, 0.15 * 22  # m³: 6 x 5 x 0.15; 0.3 x 0.5 x (2 x 5.6 + 2 x 4.6)
    level1 = (
        gamma * (slab + beams + 4 * 0.16 * 3.2)
        + (floor.finish + floor.partitions) * 30e3
        + share * floor.live * 30e3
    )
    level2 = gamma * (slab + beams + 4 * 0.16 * 1.6) + (roof.finish + roof.partitions) * 30e3
    to_base = gamma * 4 * 0.16 * 1.6  # the columns' lower half of the first storey
    w = d.summary["seismicWeight"]
    masses = sum(n["mass"][0] for n in d.project["nodes"]) * G
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 2.5.7.3 (p. 628): W is the dead load including partitions "
        "and 25 % of a live load up to 3 kN/m²; the weight lumped at the nearest story level",
        formula="W_i = γ (slab + beams + columns half a storey above and below) + (finish + "
        "partitions + 0.25 L) A",
        steps=[
            f"γ = {fmt(DENSITY)} × 9.80665 = {fmt(gamma / 1e3)} kN/m³, A = 6 × 5 = 30 m²",
            "beams between the column faces: 0.3 × 0.5 × (2 × 5.6 + 2 × 4.6) = 3.3 m³ per level",
            (
                f"level 1: γ (4.5 + 3.3 + 4 × 0.16 × 3.2) + ({floor.finish:g} + "
                f"{floor.partitions:g} + {share:g} × {floor.live:g}) × 30 = {fmt(level1 / 1e3)} kN"
            ),
            (
                f"level 2: γ (4.5 + 3.3 + 4 × 0.16 × 1.6) + ({roof.finish:g} + {roof.partitions:g})"
                f" × 30 = {fmt(level2 / 1e3)} kN (roof live load Lr not in W)"
            ),
            (
                f"to the base (not in W): γ × 4 × 0.16 × 1.6 = {fmt(to_base / 1e3)} kN, the "
                "columns' lower half of the first storey"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("W at level 1", "kN", level1 / 1e3, w["levels"][0]["weight_kN"], SUMS),
            Quantity("W at level 2", "kN", level2 / 1e3, w["levels"][1]["weight_kN"], SUMS),
            Quantity("Weight to the base", "kN", to_base / 1e3, w["toBase_kN"], SUMS),
            Quantity("Lateral mass × g", "kN", (level1 + level2) / 1e3, masses / 1e3, SUMS),
        ],
    )


# ─────────────────────────────── eccentric static earthquake cases ───────────────────────────────


def _level_torsion(project: dict[str, Any], name: str) -> dict[float, tuple[float, float]]:
    """Per level (z m) the X force and the moment about the vertical through the origin."""
    coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    pattern = next(p for p in project["load_patterns"] if p["name"] == name)
    out: dict[float, tuple[float, float]] = {}
    for load in pattern["nodal_loads"]:
        f = np.array(load["forces"])
        xyz = coords[load["node_id"]]
        z = round(float(xyz[2]), 3)
        fx, mz = out.get(z, (0.0, 0.0))
        out[z] = (fx + f[0], mz + f[5] + xyz[0] * f[1] - xyz[1] * f[0])
    return out


def eccentric_torsion(folder: Path) -> Outcome:
    d = derive(
        generate(_plan(), "v"),
        objects(COLUMN, BEAM, SLAB),
        MATERIALS,
        settings(accidentalEccentricity=True),
    )
    plain = _level_torsion(d.project, "EX")
    shifted = _level_torsion(d.project, "EXP")
    quantities = []
    steps = []
    for k, z in enumerate(sorted(plain), start=1):
        force = plain[z][0]
        expected = -0.05 * 5.0 * force  # masses shifted +Y turn the +X forces clockwise
        got = shifted[z][1] - plain[z][1]
        quantities.append(
            Quantity(f"Torsion added at level {k}", "kN·m", expected / 1e3, got / 1e3, SUMS)
        )
        steps.append(
            f"level {k}: F = {fmt(force / 1e3)} kN, M = -0.05 × 5 × F = {fmt(expected / 1e3)} kN·m"
        )
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 2.5.7.6.2 (p. 630), Eq. 6.2.43: M_ta = e_a F at each "
        "floor, e_a = ±0.05 L, L the floor's dimension across the force",
        formula="M_EXP - M_EX = -0.05 × L_y × F_x per level (masses shifted +Y)",
        steps=["L_y = 5 m (the bay across X)", *steps],
    )
    return Outcome(reference, quantities)


# ─────────────────────────────── rigid end zones, forces at the faces ───────────────────────────────


def rigid_end_zone_beam(folder: Path) -> Outcome:
    """Beam B11 of a one-storey bay with end offsets, its two joints held fixed (so it is a
    fixed-ended beam with rigid zones), under 10 kN/m: the face moment and shear against the
    fixed-ended flexible length."""
    from saengine.fem import end_zones

    plan = _plan(stories=1, slabs=False, only="B11")
    d = derive(
        generate(plan, "v"),
        objects(COLUMN, BEAM),
        MATERIALS,
        # One element between the joints: a mesh size longer than the beam (since 0.0.45 a beam
        # is cut into members of the mesh size for the slabs' load shapes).
        settings(endOffsets=True, rigidZoneFactor=0.5, diaphragm="flexible", meshSize=10000),
    )
    project = d.project
    beam = [e for e in project["elements"] if str(e.get("name", "")).startswith("B11")]
    assert len(beam) == 1, "the beam is one element between the column joints"
    element = beam[0]
    # The beam's joints and the column bases held; the tops of the other two columns stay free
    # (so the model has degrees of freedom), unloaded.
    held = set(element["nodes"][:2]) | {
        n["id"] for n in project["nodes"] if abs(n["coords"][2]) < 1e-9
    }
    for node in project["nodes"]:
        node["restraint"] = [True] * 6 if node["id"] in held else [False] * 6
        node["mass"] = [0.0] * 6
    project["mp_constraints"] = []
    w = 10e3  # N/m
    pattern = project["load_patterns"][0]
    pattern["nodal_loads"] = []
    pattern["element_loads"] = [{"element_id": element["id"], "wx": 0.0, "wy": 0.0, "wz": -w}]
    case = project["analyses"][0]["id"]
    model, out, _ = run_model({**project, "analyses": project["analyses"][:1]}, folder, [case])
    (model.parent / end_zones.FACES_FILE).write_text(json.dumps(d.faces), encoding="utf-8")
    faces = end_zones.face_forces(model, out)
    code = next(iter(faces["cases"]))
    face = faces["cases"][code][str(element["id"])]["i"]
    ri, rj = end_zones.element_offsets(element)
    a = faces["faceOffsets"][str(element["id"])]["i"] / 1e3
    length = 6.0
    lf = length - ri - rj
    x = a - ri
    m_face = w * lf**2 / 12 - w * lf / 2 * x + w * x**2 / 2
    v_face = w * (lf / 2 - x)
    reference = Reference(
        source="Fixed-ended beam under a uniform load (e.g. Ghali, Neville & Brown, Structural "
        "Analysis): the rigid zones fixed to held joints fix the ends of the flexible part",
        formula="M(x) = w Lf²/12 - w Lf x/2 + w x²/2, V(x) = w (Lf/2 - x), x from the flexible end",
        steps=[
            f"end offset a = {fmt(a)} m (half the 400 mm column), rigid zone r = 0.5 a = {fmt(ri)} m",
            f"Lf = 6 - 2 × {fmt(ri)} = {fmt(lf)} m, the face at x = a - r = {fmt(x)} m",
            f"M_face = {fmt(m_face / 1e3)} kN·m, V_face = {fmt(v_face / 1e3)} kN",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity(
                "Moment at the support face", "kN·m", m_face / 1e3, abs(face["My"]) / 1e3, FRAME
            ),
            Quantity("Shear at the support face", "kN", v_face / 1e3, abs(face["Vz"]) / 1e3, FRAME),
        ],
    )


# ─────────────────────────────── line load on a simply supported beam ───────────────────────────────


def line_load_beam(folder: Path) -> Outcome:
    """A 125 mm brick wall 2.7 m high on a steel beam with fin plates (pinned ends) between two
    column joints held fixed, in the live load case L (the bay has no slab): reactions wL/2 and
    the mid-span moment wL²/8."""
    from saengine.fem.display import _elements, element_section_forces

    wall = next(t for t in ll.default_wall_types() if t.id == "BW125")
    loads = ll.MemberLoads.model_validate(
        {
            "wallTypes": [wall.model_dump()],
            "loads": [
                {
                    "id": "W1",
                    "kind": "line",
                    "story": "L1",
                    "member": "B11",
                    "case": "L",
                    "wall": {"type": "BW125", "height": 2700},
                }
            ],
        }
    )
    plan = _plan(stories=1, slabs=False, beam_type="SB", only="B11")
    d = derive(
        generate(plan, "v"),
        objects(COLUMN, STEEL_BEAM),
        MATERIALS,
        # One element between the joints (every node but the twins is held below).
        settings(diaphragm="flexible", meshSize=10000),
        member_loads=loads,
    )
    project = d.project
    # The column joints held; the beam's pinned twin nodes (its released ends) stay free.
    twins = set(pinned_twins(project))
    for node in project["nodes"]:
        node["restraint"] = [False] * 6 if node["id"] in twins else [True] * 6
        node["mass"] = [0.0] * 6
    project["mp_constraints"] = []
    analysis = next(a for a in project["analyses"] if a["name"].split(":")[0].strip() == "L")
    _model, _out, results = run_model({**project, "analyses": [analysis]}, folder, [analysis["id"]])
    result = results[analysis["id"]]
    w = ll.wall_line_load(wall, 2700) * 1e3  # N/m
    length = 6.0
    elements = [e for e in _elements(project) if e.name.startswith("B11")]
    pattern = next(p for p in project["load_patterns"] if p["id"] in analysis["pattern_ids"])
    on = {
        int(x["element_id"]): np.array([x["wx"], x["wy"], x["wz"]])
        for x in pattern["element_loads"]
    }
    moments = []
    for e in elements:
        forces = element_section_forces(
            e, np.asarray(result.element_forces[e.id][-1])[:12], on.get(e.id, np.zeros(3))
        )
        moments.append(np.abs(forces[:, 4]).max())
    reactions = sum(
        float(np.asarray(r[-1])[2]) for n, r in result.node_reaction.items() if n not in twins
    )
    reference = Reference(
        source="Simply supported beam under a uniform load; the wall's weight from BNBC 2020 "
        "Part 6 Table 6.2.2 (p. 530-531): brick 19.1 kN/m³, cement plaster 23.0 kN/m³",
        formula="w = (0.125 × 19.1 + 2 × 0.0125 × 23.0) × h;  R = w L / 2;  M = w L² / 8",
        steps=[
            f"w = {fmt(wall.weight_per_area())} kN/m² × 2.7 m = {fmt(w / 1e3)} kN/m",
            f"total w L = {fmt(w * length / 1e3)} kN, M = {fmt(w * length**2 / 8 / 1e3)} kN·m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Total of the reactions", "kN", w * length / 1e3, reactions / 1e3, SUMS),
            Quantity("Mid-span moment", "kN·m", w * length**2 / 8 / 1e3, max(moments) / 1e3, FRAME),
        ],
    )


CASES = [
    Case(
        id="AP1",
        title="Seismic weight lumped at the story levels",
        category="analysis",
        description="The seismic weight W of a two-storey bay per level, and what goes to the base.",
        model="One bay 6 x 5 m, two storeys of 3.2 m, 400 x 400 columns, 300 x 500 beams, 150 mm slab.",
        run=story_mass,
    ),
    Case(
        id="AP2",
        title="Eccentric static earthquake case",
        category="analysis",
        description="The torsion the case EXP adds to EX at each floor: 5 % of the width across the force.",
        model="The two-storey bay of the story mass case, rigid floors.",
        run=eccentric_torsion,
    ),
    Case(
        id="AP3",
        title="Rigid end zones: forces at the support face",
        category="analysis",
        description="A fixed-ended beam with rigid end zones (factor 0.5) under 10 kN/m: the moment "
        "and shear at the column face.",
        model="Beam 300 x 500 of 6 m between 400 x 400 columns, the joints held.",
        run=rigid_end_zone_beam,
    ),
    Case(
        id="AP4",
        title="Wall line load on a simply supported beam",
        category="analysis",
        description="A 125 mm brick wall 2.7 m high (loads.json) on a beam with pinned ends: the "
        "reactions and the mid-span moment.",
        model="Steel I 300 x 150 of 6 m with fin plates between held column joints.",
        run=line_load_beam,
    ),
]
