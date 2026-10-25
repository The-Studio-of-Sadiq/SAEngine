"""The analysis model's conventions of the comparison with a commercial analysis program: mass
lumped at the story levels, eccentric static earthquake cases, the modal period capped at
1.4 Ta, rigid end zones with forces at the support faces, columns at any angle, and the mesh
convergence check (saengine.fem.derive, end_zones, mesh_check, seismic_design)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from saengine.fem import derive as fem_derive
from saengine.fem.derive import G, column_vecxz, derive_fem, local_axes, quarter_turns
from saengine.fem.end_zones import face_section_forces, section_at, support_reach
from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan, default_material_library
from saengine.library.bim import generate
from saengine.library.objects import RectangleProfile
from saengine.library.settings import default_project_settings

OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "COL",
                "name": "Column 400x400",
                "kind": "column",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
            },
            {
                "id": "BM",
                "name": "Beam 300x500",
                "kind": "beam",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            },
            {"id": "SL", "name": "Slab 150", "kind": "slab", "material": "C24.1", "thickness": 150},
            {
                "id": "WL",
                "name": "Shear wall 200",
                "kind": "wall",
                "material": "C24.1",
                "thickness": 200,
            },
        ]
    }
)
MATERIALS = default_material_library()
DENSITY = next(m for m in MATERIALS.materials if m.id == "C24.1").mechanical.density
CORNERS = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]
STORIES = [
    {"id": "BASE", "name": "Base", "elevation": 0},
    {"id": "L1", "name": "Level 1", "elevation": 3200},
    {"id": "L2", "name": "Level 2", "elevation": 6400},
]


def plan(walls: bool = False) -> FloorPlan:
    """One bay (A-B 6 m, 1-2 5 m), two stories of 3.2 m; with ``walls`` a shear wall along 1."""
    return FloorPlan.model_validate(
        {
            **default_floor_plan().model_dump(mode="json", by_alias=True),
            "stories": STORIES,
            "columns": [
                {
                    "id": f"C{i + 1}",
                    "type": "COL",
                    "at": {"x": x, "y": y},
                    "base": "BASE",
                    "top": "L2",
                }
                for i, (x, y) in enumerate(CORNERS)
            ],
            "beams": [
                {
                    "id": f"B{story}{i + 1}",
                    "type": "BM",
                    "story": f"L{story}",
                    "start": {"x": a[0], "y": a[1]},
                    "end": {"x": b[0], "y": b[1]},
                }
                for story in (1, 2)
                for i, (a, b) in enumerate(zip(CORNERS, CORNERS[1:] + CORNERS[:1]))
            ],
            "slabs": [
                {
                    "id": f"S{story}",
                    "type": "SL",
                    "story": f"L{story}",
                    "boundary": [{"x": x, "y": y} for x, y in CORNERS],
                }
                for story in (1, 2)
            ],
            "walls": [
                {
                    "id": "W1",
                    "type": "WL",
                    "base": "BASE",
                    "top": "L2",
                    "start": {"x": "A", "y": "1"},
                    "end": {"x": "B", "y": "1"},
                }
            ]
            if walls
            else [],
        }
    )


def settings(**analysis: object):
    s = default_project_settings("Parity")
    return s.model_copy(update={"analysis": s.analysis.model_copy(update=analysis)})


def derivation(walls: bool = False, **analysis: object):
    return derive_fem(
        generate(plan(walls), "s"), OBJECTS, MATERIALS, settings(**analysis), {"bim": "abc"}
    )


def run(project: dict, folder: Path, ids: list[int]) -> Path:
    from saengine.fem.seismic_design import _run

    return _run(project, folder, ids)


# ─────────────────────────────── mass lumping and the seismic weight ───────────────────────────────


def test_seismic_weight_per_level_by_hand() -> None:
    """Two stories of a frame: each level carries its slab, its beams, half the columns above
    and below it, the superimposed dead load and 25 % of the live load (a floor; the roof's
    live load Lr is not in W); the lower half of the first storey's columns is at the fixed
    base and does not participate."""
    d = derivation(massLumping="storyLevels")
    s = default_project_settings("x")
    loads = {a.id: a for a in s.areaLoads}
    floor, roof = loads[s.floorLoad], loads[s.roofLoad]
    weight = DENSITY * G
    share = 0.5 if floor.live > 3.0 else 0.25
    level1 = (
        weight * (0.15 * 30 + 0.15 * 22 + 4 * 0.16 * 3.2)
        + (floor.finish + floor.partitions) * 30e3
        + share * floor.live * 30e3
    )
    level2 = (
        weight * (0.15 * 30 + 0.15 * 22 + 4 * 0.16 * 1.6) + (roof.finish + roof.partitions) * 30e3
    )
    w = d.summary["seismicWeight"]
    assert [row["weight_kN"] for row in w["levels"]] == pytest.approx(
        [level1 / 1e3, level2 / 1e3], rel=1e-4
    )
    assert w["total_kN"] == pytest.approx((level1 + level2) / 1e3, rel=1e-4)
    assert d.summary["weight_kN"] == pytest.approx((level1 + level2) / 1e3, rel=1e-4)
    assert w["levels"][0]["parts_kN"]["L"] == pytest.approx(share * floor.live * 30, rel=1e-4)
    assert "seismic weight W" in w["note"]
    # The masses: each level's weight at its nodes and diaphragm node (all on the level).
    masses = sum(n["mass"][0] for n in d.project["nodes"])
    assert masses * G == pytest.approx(level1 + level2, rel=1e-4)


def test_lumping_sends_the_lower_half_storey_to_the_base() -> None:
    """With a wall meshed between the levels, "storyLevels" gives the weight of its nodes in the
    lower half of the first storey to the base (not participating) and the others to their
    nearest level's diaphragm node; "levelAbove" (before) counts it all for the first level."""
    lumped = derivation(walls=True, massLumping="storyLevels", meshSize=400)
    before = derivation(walls=True, massLumping="levelAbove", meshSize=400)
    w, w0 = lumped.summary["seismicWeight"], before.summary["seismicWeight"]
    assert w0["method"] == "levelAbove" and w0["toBase_kN"] == 0
    # What goes to the base is what W loses.
    assert w0["total_kN"] - w["total_kN"] == pytest.approx(w["toBase_kN"], abs=2e-3)
    # The wall (6 m x 0.2 m) and the four columns below mid-height of the first storey (1.6 m),
    # the supports' own share included; within a few per cent, as the wall's mesh is not
    # regular and its nodes take their tributary weight whole to the nearer level.
    per_metre = DENSITY * G * (0.2 * 6.0 + 4 * 0.16) / 1e3
    assert w["toBase_kN"] == pytest.approx(per_metre * 1.6, rel=0.05)
    # Nodes between the levels keep no mass; each diaphragm node carries its lumped weight and
    # the moment of inertia of it about the vertical.
    coords = {n["id"]: n["coords"] for n in lumped.project["nodes"]}
    off_level = [
        n
        for n in lumped.project["nodes"]
        if all(abs(n["coords"][2] - z) > 1e-6 for z in (0.0, 3.2, 6.4))
    ]
    assert off_level and all(n["mass"][0] == 0 for n in off_level)
    masters = {c["retained_node"] for c in lumped.project["mp_constraints"]}
    rotary = [n["mass"][5] for n in lumped.project["nodes"] if n["id"] in masters]
    assert len(masters) == 2 and all(r > 0 for r in rotary)
    total = sum(n["mass"][0] for n in lumped.project["nodes"]) * G / 1e3
    assert total == pytest.approx(w["total_kN"], rel=1e-4)
    assert all(coords)


@pytest.mark.parametrize("lumping", ["storyLevels", "levelAbove"])
def test_seismic_weight_does_not_depend_on_the_mesh(lumping: str) -> None:
    """The weight of the supports' own nodes is not lost (to the base with "storyLevels", with
    the first level with "levelAbove"), and a node half way between two levels gives half to
    each: W + the base's share is the whole weight at any mesh, "levelAbove" gives the same W
    at any mesh, and "storyLevels" stays close to the hand value of the lower half storey."""
    rows = []
    for mesh in (400, 500, 1000):
        d = derivation(walls=True, massLumping=lumping, meshSize=mesh, meshBySpan=False)
        w = d.summary["seismicWeight"]
        rows.append((w["total_kN"], w["toBase_kN"]))
    whole = [total + base for total, base in rows]
    assert whole == pytest.approx([whole[0]] * 3, abs=2e-3)  # the summary rounds to 1 N
    if lumping == "levelAbove":
        assert [base for _, base in rows] == [0, 0, 0]
        return
    # The lower half of the first storey by hand: the wall and the four columns over 1.6 m.
    # Nodal lumping on the wall's irregular mesh leaves W within 1 % of it at any mesh.
    lower = DENSITY * G * 1.6 * (0.2 * 6.0 + 4 * 0.16) / 1e3
    assert [total for total, _ in rows] == pytest.approx([whole[0] - lower] * 3, rel=1e-2)


def test_seismic_weight_of_the_sample_does_not_depend_on_the_mesh() -> None:
    """The shipped sample (walls, slabs and frames) at 500 and 1000 mm: W + the base's share is
    the same, and W itself changes by less than 0.5 % (measured 574.76 and 576.62 kN, the
    base's share 99.82 and 97.96 kN: nodes between the levels on the walls' irregular mesh take
    their tributary weight whole to the nearer level)."""
    from saengine.report.build import _Parts

    root = (
        Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples"
    ) / "Sample Frame"
    parts = _Parts(root, [])
    settings = parts.settings()
    rows = []
    for mesh in (500, 1000):
        analysis = settings.analysis.model_copy(
            update={"meshSize": mesh, "meshBySpan": False, "massLumping": "storyLevels"}
        )
        d = derive_fem(
            parts.building(),
            parts.objects(),
            parts.materials(),
            settings.model_copy(update={"analysis": analysis}),
        )
        w = d.summary["seismicWeight"]
        rows.append((w["total_kN"], w["toBase_kN"]))
    (fine, fine_base), (coarse, coarse_base) = rows
    assert fine + fine_base == pytest.approx(coarse + coarse_base, abs=2e-3)
    assert coarse == pytest.approx(fine, rel=5e-3)


def test_mass_source_factors_and_extra_mass() -> None:
    base = derivation(massLumping="storyLevels")
    source = {
        "dead": 1.0,
        "superimposed": 1.0,
        "liveShare": 0.5,
        "extraMasses": [{"story": "L1", "weight": 100.0, "x": 0.0, "y": 0.0}],
    }
    d = derivation(massLumping="storyLevels", massSource=source)
    s = default_project_settings("x")
    floor = {a.id: a for a in s.areaLoads}[s.floorLoad]
    w0, w = base.summary["seismicWeight"], d.summary["seismicWeight"]
    added_live = (0.5 - 0.25) * floor.live * 30
    assert w["levels"][0]["weight_kN"] == pytest.approx(
        w0["levels"][0]["weight_kN"] + added_live + 100.0, rel=1e-4
    )
    assert w["extra_kN"] == pytest.approx(100.0)
    assert w["levels"][1]["weight_kN"] == pytest.approx(w0["levels"][1]["weight_kN"], rel=1e-6)


# ─────────────────────────────── static earthquake: eccentricity and period ───────────────────────────────


def _pattern(project: dict, name: str) -> dict[int, np.ndarray]:
    pattern = next(p for p in project["load_patterns"] if p["name"] == name)
    return {n["node_id"]: np.array(n["forces"]) for n in pattern["nodal_loads"]}


@pytest.mark.parametrize("diaphragm", ["rigid", "flexible"])
def test_eccentric_cases_add_the_torsion_f_times_e(diaphragm: str) -> None:
    """EXP, EXN, EYP, EYN: the forces of EX or EY plus at each level the moment F·e about the
    vertical, e = 5 % of the floor's dimension across the force (BNBC 2020 Part 6 Sec
    2.5.7.6.2): masses shifted +Y turn the X forces by -F·e, shifted +X the Y forces by +F·e."""
    d = derivation(accidentalEccentricity=True, diaphragm=diaphragm)
    names = [p["name"] for p in d.project["load_patterns"]]
    assert names[-4:] == ["EXP", "EXN", "EYP", "EYN"]
    assert [a["name"].split(":")[0] for a in d.project["analyses"][8:12]] == names[8:12]
    coords = {n["id"]: np.array(n["coords"]) for n in d.project["nodes"]}

    def per_level(loads: dict[int, np.ndarray]) -> dict[float, tuple[np.ndarray, float]]:
        out: dict[float, tuple[np.ndarray, float]] = {}
        for node, f in loads.items():
            z = round(float(coords[node][2]), 3)
            force, moment = out.get(z, (np.zeros(3), 0.0))
            mz = f[5] + coords[node][0] * f[1] - coords[node][1] * f[0]
            out[z] = (force + f[:3], moment + mz)
        return out

    for case, source, span, sign in (
        ("EXP", "EX", 5.0, -1),
        ("EXN", "EX", 5.0, 1),
        ("EYP", "EY", 6.0, 1),
        ("EYN", "EY", 6.0, -1),
    ):
        plain, shifted = (
            per_level(_pattern(d.project, source)),
            per_level(_pattern(d.project, case)),
        )
        assert set(plain) == set(shifted) == {3.2, 6.4}
        axis = 0 if source == "EX" else 1
        for z, (force, moment) in plain.items():
            torsion = shifted[z][1] - moment
            assert shifted[z][0] == pytest.approx(force, abs=1e-2)
            assert torsion == pytest.approx(sign * 0.05 * span * force[axis], rel=1e-3)
    levels = d.summary["accidentalTorsion"]
    assert {row["case"] for row in levels} == {"EXP", "EXN", "EYP", "EYN"}
    assert all(row["e_m"] == pytest.approx(0.05 * row["L_m"]) for row in levels)


def test_period_from_the_modal_analysis_is_capped_at_1_4_ta(monkeypatch) -> None:
    """Sec 2.5.7.2 (a): the analysis period, not more than 1.4 Ta (and not below Ta, as a
    commercial analysis program takes it); the static forces follow."""
    import saengine.fem.seismic_design as sd

    plain = derivation()
    ta = plain.summary["period_s"]
    for modal, expected in ((5.0, 1.4 * ta), (1.2 * ta, 1.2 * ta), (0.6 * ta, ta)):
        monkeypatch.setattr(
            sd,
            "fundamental_periods",
            lambda project, folder=None, modal=modal: {
                "X": {"period": modal, "mode": 1, "massRatio": 0.9},
                "Y": {"period": modal, "mode": 2, "massRatio": 0.9},
            },
        )
        d = derivation(periodMethod="analysis")
        seismic = d.summary["seismic"]
        assert d.summary["periodMethod"] == "analysis"
        assert d.summary["periodCap_s"] == pytest.approx(1.4 * ta)
        assert seismic["EX"]["period_s"] == pytest.approx(expected)
        from saengine.fem import loads as fl

        values = fem_derive.derived(settings())
        sa = fl.design_acceleration(
            expected, "SD", values["Z"], values["seismicImportance"], values["R"]
        )
        assert seismic["EX"]["Sa_g"] == pytest.approx(sa)
        applied = sum(f[0] for f in _pattern(d.project, "EX").values())
        assert applied == pytest.approx(sa * d.summary["weight_kN"] * 1e3, rel=1e-4)
        # The summary's row stays consistent: Ta, and Cs, Sa and V of the period used (V = Sa·W).
        assert d.summary["period_s"] == pytest.approx(ta)
        assert d.summary["periodUsed_s"] == pytest.approx(expected)
        assert d.summary["Sa_g"] == pytest.approx(sa)
        assert d.summary["Cs"] == pytest.approx(fl.normalized_spectrum(expected, "SD"))
        assert d.summary["base_shear_kN"] == pytest.approx(sa * d.summary["weight_kN"])


def test_fundamental_periods_of_the_bay(tmp_path: Path) -> None:
    from saengine.fem.seismic_design import fundamental_periods

    d = derivation()
    periods = fundamental_periods(d.project, tmp_path)
    assert set(periods) == {"X", "Y"}
    for axis in ("X", "Y"):
        assert 0.05 < periods[axis]["period"] < 2.0
        assert periods[axis]["massRatio"] > 0.5


# ─────────────────────────────── rigid end zones and faces ───────────────────────────────


def test_support_reach_of_rotated_columns() -> None:
    column = RectangleProfile(xDim=400, yDim=600)
    assert support_reach(column, 0, (1, 0)) == pytest.approx(200)
    assert support_reach(column, 0, (0, -3)) == pytest.approx(300)
    assert support_reach(column, 90, (1, 0)) == pytest.approx(300)
    # At 45° a ray along X leaves the square's corner region at half-width / cos 45°.
    assert support_reach(RectangleProfile(xDim=400, yDim=400), 45, (1, 0)) == pytest.approx(
        200 * math.sqrt(2)
    )


def test_fixed_end_beam_with_rigid_zones_gives_face_moments_by_hand(tmp_path: Path) -> None:
    """A 6 m beam between fixed joints, 500 mm wide supports (offset a = 250 mm), rigid zone
    factor 0.5 (rigid r = 125 mm): fixed-end moments w·Lf²/12 at the rigid ends (Lf = L - 2r),
    and at the faces M = -w·Lf²/12 + V·(a - r) - w·(a - r)²/2 with V = w·Lf/2."""
    w, length, a, r = 10e3, 6.0, 0.25, 0.125
    project = {
        "schema_version": 2,
        "meta": {"name": "rz", "description": "", "author": "", "units": "SI (m, N, kg, s, Pa)"},
        "ndm": 3,
        "ndf": 6,
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [length, 0, 0], "restraint": [True] * 6},
            {"id": 3, "coords": [length / 2, 0, 0], "restraint": [False] * 6},
        ],
        "materials": [],
        "sections": [
            {
                "id": 1,
                "type": "ElasticSection",
                "E": 25e9,
                "A": 0.15,
                "Iz": 0.3**3 * 0.5 / 12,
                "Iy": 0.3 * 0.5**3 / 12,
                "G": 10e9,
                "J": 0.003,
            }
        ],
        # Two elements (a node at mid-span), the rigid zones at the supports.
        "elements": [
            {
                "id": 1,
                "type": "ElasticBeamColumn",
                "nodes": [1, 3],
                "section_id": 1,
                "joint_offsets": [r, 0, 0, 0, 0, 0],
            },
            {
                "id": 2,
                "type": "ElasticBeamColumn",
                "nodes": [3, 2],
                "section_id": 1,
                "joint_offsets": [0, 0, 0, -r, 0, 0],
            },
        ],
        "time_series": [{"id": 1, "type": "Linear", "factor": 1.0}],
        "load_patterns": [
            {
                "id": 1,
                "name": "D",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [],
                "element_loads": [
                    {"element_id": k, "wy": 0.0, "wz": -w, "wx": 0.0} for k in (1, 2)
                ],
            }
        ],
        "analyses": [
            {
                "id": 1,
                "name": "D",
                "type": "Static",
                "pattern_ids": [1],
                "n_steps": 1,
                "load_factor_increment": 1.0,
                "system": "BandGeneral",
                "constraints": "Plain",
                "integrator": "LoadControl",
                "algorithm": "Linear",
                "test": "NormDispIncr",
                "tolerance": 1e-8,
                "max_iter": 25,
            }
        ],
    }
    from opensees_studio.core.project import Project

    Project.model_validate(project)  # joint_offsets is part of the element
    out = run(project, tmp_path, [1])
    from opensees_studio.services.result_store import load_manifest, load_results

    results = load_results(load_manifest(out)["cases"][0], out)
    forces = np.asarray(results.element_forces[1][-1], dtype=float)[:12]
    forces2 = np.asarray(results.element_forces[2][-1], dtype=float)[:12]
    flexible = length - 2 * r
    fixed_end = w * flexible**2 / 12
    # The element's own end moments are at its rigid ends: the fixed-end moments of Lf.
    assert abs(forces[4]) == pytest.approx(fixed_end, rel=1e-6)
    assert abs(forces[2]) == pytest.approx(w * flexible / 2, rel=1e-6)
    faces = {
        "elements": {
            "1": {
                "i": {"offset": 250, "rigid": 125, "at": [1, a]},
            },
            "2": {"j": {"offset": 250, "rigid": 125, "at": [2, length / 2 - a]}},
        }
    }
    load = np.array([0.0, 0.0, -w])
    at_faces = face_section_forces(
        {1: project["elements"][0], 2: project["elements"][1]},
        {1: forces, 2: forces2},
        {1: load, 2: load},
        faces,
    )
    d = a - r
    face_moment = -fixed_end + w * flexible / 2 * d - w * d**2 / 2
    assert at_faces[1]["i"]["My"] == pytest.approx(at_faces[2]["j"]["My"], rel=1e-6)
    assert abs(at_faces[1]["i"]["My"]) == pytest.approx(abs(face_moment), rel=1e-5)
    assert abs(at_faces[1]["i"]["Vz"]) == pytest.approx(w * (flexible / 2 - d), rel=1e-5)
    # Mid-span from the same formula: w·Lf²/24.
    mid = section_at(forces, load, length / 2 - r)
    assert abs(mid[4]) == pytest.approx(w * flexible**2 / 24, rel=1e-6)


def test_derived_end_offsets_and_their_loads() -> None:
    """Beams get rigid zones of 0.5 × half the column (200 mm) at both ends, columns of 0.5 × the
    beam depth (500 mm) at their tops; the uniform loads on the rigid zones go to the joints, so
    every case's total load is unchanged."""
    plain = derivation()
    d = derivation(endOffsets=True, rigidZoneFactor=0.5)
    elements = {e["id"]: e for e in d.project["elements"]}
    coords = {n["id"]: np.array(n["coords"]) for n in d.project["nodes"]}
    beam = next(e for e in d.project["elements"] if e["name"] == "B11")
    assert np.linalg.norm(beam["joint_offsets"][:3]) == pytest.approx(0.1)
    assert np.linalg.norm(beam["joint_offsets"][3:]) == pytest.approx(0.1)
    column = next(e for e in d.project["elements"] if e["name"] == "C1")
    assert np.linalg.norm(column["joint_offsets"][3:]) == pytest.approx(0.25)
    assert np.linalg.norm(column["joint_offsets"][:3]) == pytest.approx(0.0)
    faces = d.faces["elements"]
    assert faces[str(beam["id"])]["i"] == {"offset": 200.0, "rigid": 100.0, "at": [beam["id"], 0.2]}
    assert faces[str(column["id"])]["j"]["offset"] == 500.0
    assert d.faces["rigidZoneFactor"] == 0.5

    def total(project: dict, name: str) -> np.ndarray:
        pattern = next(p for p in project["load_patterns"] if p["name"] == name)
        out = sum((np.array(n["forces"][:3]) for n in pattern["nodal_loads"]), np.zeros(3))
        for load in pattern["element_loads"]:
            e = (elements if project is d.project else plain_elements)[load["element_id"]]
            c = coords if project is d.project else plain_coords
            a, b = (c[n] for n in e["nodes"])
            x, y, z = local_axes(a, b)
            ri = np.linalg.norm(e.get("joint_offsets", [0] * 6)[:3])
            rj = np.linalg.norm(e.get("joint_offsets", [0] * 6)[3:])
            flexible = np.linalg.norm(b - a) - ri - rj
            out = out + (load["wx"] * x + load["wy"] * y + load["wz"] * z) * flexible
        return out

    plain_elements = {e["id"]: e for e in plain.project["elements"]}
    plain_coords = {n["id"]: np.array(n["coords"]) for n in plain.project["nodes"]}
    for case in ("D", "SD", "Lr"):
        assert total(d.project, case) == pytest.approx(total(plain.project, case), rel=1e-6)
    assert any("end offsets" in note for note in d.notes)


def test_face_forces_of_an_analysed_bay(tmp_path: Path) -> None:
    """The face forces file of an analysed model: per static case and element the forces at the
    faces; a beam's face moment is smaller than its joint moment."""
    from saengine.fem.end_zones import FACES_FILE, write_face_forces

    d = derivation(endOffsets=True)
    folder = tmp_path / "08 FEM"
    folder.mkdir()
    model = folder / "model.osmodel"
    model.write_text(json.dumps(d.project), encoding="utf-8")
    (folder / FACES_FILE).write_text(json.dumps(d.faces), encoding="utf-8")
    ids = [a["id"] for a in d.project["analyses"] if a["name"].split(":")[0] in ("D", "SD")]
    from saengine.fem.seismic_design import _run

    out = _run(d.project, folder / "run", ids)
    path = write_face_forces(model, out)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["cases"]) == {"D", "SD"}
    beam = next(e for e in d.project["elements"] if e["name"] == "B11")
    face = data["cases"]["D"][str(beam["id"])]["i"]
    assert set(face) == {"N", "Vy", "Vz", "T", "My", "Mz"}
    assert data["faceOffsets"][str(beam["id"])] == {"i": 200.0, "j": 200.0}


# ─────────────────────────────── columns at any angle ───────────────────────────────


def test_column_rotation_is_not_snapped() -> None:
    assert quarter_turns(180) == 2 and quarter_turns(135) is None
    # The swap rule the design must share: 60° swaps nothing with exact angles (its axes are
    # turned instead), and is a quarter turn without them (as the design rounds it today).
    assert fem_derive.analysed_turns(60, True) == 0 and fem_derive.analysed_turns(60, False) == 1
    assert fem_derive.analysed_turns(90, True) == fem_derive.analysed_turns(90, False) == 1
    assert column_vecxz(90) is None
    assert column_vecxz(135) == pytest.approx((-math.sqrt(0.5), math.sqrt(0.5), 0.0))
    building = generate(plan(), "s")
    turned = building.model_copy(
        update={
            "elements": [
                e.model_copy(update={"rotation": 135.0}) if e.id == "C2" else e
                for e in building.elements
            ]
        }
    )
    d = derive_fem(turned, OBJECTS, MATERIALS, settings(exactColumnRotation=True), {"bim": "abc"})
    assert not any("is analysed as" in note for note in d.notes)
    c2 = [e for e in d.project["elements"] if e["name"].split("#")[0] == "C2"]
    assert c2 and all(e["vecxz"] == pytest.approx(column_vecxz(135)) for e in c2)
    others = [e for e in d.project["elements"] if e["name"].split("#")[0] == "C1"]
    assert all("vecxz" not in e for e in others)
    # With the setting off (the behaviour before version 0.0.44) the angle is rounded to quarter
    # turns, with the note, and the design rounds it the same way (it reads the model).
    old = derive_fem(
        turned, OBJECTS, MATERIALS, settings(exactColumnRotation=False), {"bim": "abc"}
    )
    assert any("C2: rotation 135.0° is analysed as 180°" in note for note in old.notes)
    assert all("vecxz" not in e for e in old.project["elements"])


def test_rotated_cantilever_bends_about_its_own_axes(tmp_path: Path) -> None:
    """A 400 x 800 column turned 30°, loaded along X: its tip moves as the turned section's
    flexibility gives, F·L³/3E · R·diag(1/I)·Rᵀ (not as the nearest quarter turn's)."""
    from opensees_studio.services.result_store import load_manifest, load_results

    e_mod, length, force, angle = 25e9, 3.0, 10e3, math.radians(30)
    i_x, i_y = 0.4 * 0.8**3 / 12, 0.8 * 0.4**3 / 12  # about the profile's x and y axes
    project = {
        "schema_version": 2,
        "meta": {"name": "rot", "description": "", "author": "", "units": "SI (m, N, kg, s, Pa)"},
        "ndm": 3,
        "ndf": 6,
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [0, 0, length], "restraint": [False] * 6},
        ],
        "materials": [],
        # An unturned column's section: the profile's x-axis inertia in Iz (local z = global X).
        "sections": [
            {
                "id": 1,
                "type": "ElasticSection",
                "E": e_mod,
                "A": 0.32,
                "Iz": i_x,
                "Iy": i_y,
                "G": 10e9,
                "J": 0.01,
            }
        ],
        "elements": [
            {
                "id": 1,
                "type": "ElasticBeamColumn",
                "nodes": [1, 2],
                "section_id": 1,
                "vecxz": list(column_vecxz(30.0)),
            }
        ],
        "time_series": [{"id": 1, "type": "Linear", "factor": 1.0}],
        "load_patterns": [
            {
                "id": 1,
                "name": "P",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [{"node_id": 2, "forces": [force, 0, 0, 0, 0, 0]}],
                "element_loads": [],
            }
        ],
        "analyses": [
            {
                "id": 1,
                "name": "P",
                "type": "Static",
                "pattern_ids": [1],
                "n_steps": 1,
                "load_factor_increment": 1.0,
                "system": "BandGeneral",
                "constraints": "Plain",
                "integrator": "LoadControl",
                "algorithm": "Linear",
                "test": "NormDispIncr",
                "tolerance": 1e-8,
                "max_iter": 25,
            }
        ],
    }
    out = run(project, tmp_path, [1])
    results = load_results(load_manifest(out)["cases"][0], out)
    tip = np.asarray(results.node_disp[2][-1], dtype=float)[:2]
    # Bending in the profile's y direction is resisted by i_x (about its x axis), and so on.
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    flexibility = rotation @ np.diag([1 / i_y, 1 / i_x]) @ rotation.T * length**3 / (3 * e_mod)
    assert tip == pytest.approx(flexibility @ np.array([force, 0.0]), rel=1e-6)


# ─────────────────────────────── mesh convergence ───────────────────────────────


def test_mesh_check_on_a_small_slab() -> None:
    from saengine.fem.mesh_check import mesh_convergence

    s = settings(slabs="shells", meshSize=1000)
    result = mesh_convergence(generate(plan(), "s"), OBJECTS, MATERIALS, s)
    assert result["meshSize_mm"] == 1000 and result["coarseSize_mm"] == 2000
    assert result["compared"] >= 8  # 8 beams, two ends each, the small ones left out
    assert 0 < result["maxChangePercent"] < 100
    assert result["warning"] == (result["maxChangePercent"] > 5.0)
    first = result["members"][0]
    assert abs(first["changePercent"]) == result["maxChangePercent"]
    assert first["member"].startswith("B")


def test_span_rule_refines_the_slabs() -> None:
    coarse = derivation(slabs="shells", meshSize=1000, meshBySpan=False)
    fine = derivation(slabs="shells", meshSize=1000, meshBySpan=True)
    # 5 m short span / 8 = 625 mm: more shells than at 1000 mm.
    assert fine.summary["shells"] > coarse.summary["shells"]


def test_lumped_masses_route_the_eigen_solver() -> None:
    """Masses lumped at a few diaphragms have few DOF: the modal case asks for fewer modes, and
    OpenSees Studio leaves ARPACK (which aborts when 2 · modes reach the DOF with mass)."""
    from opensees_studio.core.modal import mass_dof_bound, resolve_modal_solver
    from opensees_studio.core.project import Project

    d = derivation(walls=True, massLumping="storyLevels", meshSize=400)
    project = Project.model_validate(d.project)
    bound = mass_dof_bound(project)
    assert bound == 6  # two diaphragms, 3 each
    modal = next(a for a in d.project["analyses"] if a["type"] == "Modal")
    assert modal["n_modes"] == 6  # every mode with mass
    assert resolve_modal_solver("genBandArpack", 2000, 6, bound)[0] == "fullGenLapack"
    assert resolve_modal_solver("genBandArpack", 5000, 6, bound)[0] == "condensed"
    assert resolve_modal_solver("genBandArpack", 5000, 2, 40)[0] == "genBandArpack"
    assert resolve_modal_solver("genBandArpack", 5000, 2, 10)[0] == "condensed"  # 2 + 8
    # Before (masses at every node) the count is large and the modes stay 3 per level.
    before = derivation(walls=True, meshSize=400)
    assert next(a for a in before.project["analyses"] if a["type"] == "Modal")["n_modes"] == 6


def _modal_run(project_dict: dict, monkeypatch, condensed: bool):
    """The modal case of ``project_dict`` run in this process by OpenSees Studio's runner,
    routed to ARPACK and from there (too few DOF with mass) to the condensed or dense solve."""
    from opensees_studio.core import modal as osm
    from opensees_studio.core.project import Project
    from opensees_studio.services.opensees_runner import OpenSeesRunner

    monkeypatch.setenv(osm.DENSE_EIGEN_MAX_FREE_DOF_ENV, "0")
    monkeypatch.setattr(osm, "CONDENSED_MIN_FREE_DOF", 0 if condensed else 10**9)
    project = Project.model_validate(project_dict)
    case = next(a for a in project.analyses if a.type == "Modal")
    return project, OpenSeesRunner(project).run(case)


def test_lumped_modes_carry_all_the_mass(monkeypatch) -> None:
    """Masses lumped at the levels: the modal case takes every mode with mass (3 per
    diaphragm), so the participating mass is 100 % in X and Y (BNBC 2020 Part 6 Sec 2.5.9.2
    asks for 90 %); the condensed solve of a large model gives the dense solve's modes."""
    from opensees_studio.services.spectrum import mass_participation

    d = derivation(walls=True, massLumping="storyLevels", meshSize=400)
    _, dense = _modal_run(d.project, monkeypatch, condensed=False)
    project, condensed = _modal_run(d.project, monkeypatch, condensed=True)
    assert dense.solver == "fullGenLapack" and condensed.solver == "condensed"
    assert len(condensed.eigenvalues) == len(dense.eigenvalues) == 6
    assert condensed.eigenvalues == pytest.approx(dense.eigenvalues, rel=1e-6)
    for direction in (1, 2):
        for results in (dense, condensed):
            ratios = [m.mass_ratio for m in mass_participation(project, results, direction)]
            assert sum(ratios) == pytest.approx(1.0, abs=1e-6)
    # The same shapes at every node (sign-normalized; the scale is the solver's, the dense
    # solver's vectors not being mass-normalized, so each is divided by its largest value).
    for mode in range(1, 7):
        a, b = dense.mode_shapes[mode], condensed.mode_shapes[mode]
        scale_a = max(np.max(np.abs(v)) for v in a.values())
        scale_b = max(np.max(np.abs(v)) for v in b.values())
        for node, shape in a.items():
            assert b[node] / scale_b == pytest.approx(shape / scale_a, abs=1e-6)


@pytest.mark.parametrize("condensed", [False, True])
def test_modal_forces_reproduce_the_modes_with_floor_inertia(
    tmp_path: Path, monkeypatch, condensed: bool
) -> None:
    """The response spectrum's per-mode static cases (ω²·M·u, with the floor's polar inertia
    I·θ on its diaphragm node, θ from the floor's translations) give back the mode shape at
    every node, rotations of the floors included: K·φ = ω²·M·φ."""
    from opensees_studio.services.result_store import load_manifest, load_results

    from saengine.fem.seismic_design import _run, modal_force_model

    d = derivation(walls=True, massLumping="storyLevels", meshSize=400)
    _, modal = _modal_run(d.project, monkeypatch, condensed=condensed)
    masters = {c["retained_node"] for c in d.project["mp_constraints"]}
    modes = [
        {"mode_number": k, "angular_frequency": float(math.sqrt(modal.eigenvalues[k - 1]))}
        for k in range(1, len(modal.eigenvalues) + 1)
    ]
    peaks = [
        {int(n): np.asarray(v, dtype=float)[:3] for n, v in modal.mode_shapes[k].items()}
        for k in range(1, len(modes) + 1)
    ]
    # The RS case's stiffness (its cracked section overrides, as the modal case's).
    rx = next(a["id"] for a in d.project["analyses"] if a["type"] == "ResponseSpectrum")
    spectra = {"X": {"case_id": rx, "modes": modes, "peaks": peaks}}
    model, cases = modal_force_model(d.project, spectra, torsion=False)
    assert len(cases) == len(modes)
    out = _run(model, tmp_path, [c["id"] for c in cases])
    by_id = {int(e["case_id"]): e for e in load_manifest(out)["cases"]}
    torsional = 0
    for case in cases:
        static = load_results(by_id[case["id"]], out)
        shape = modal.mode_shapes[case["mode"] + 1]
        scale = max(np.max(np.abs(v[:3])) for v in shape.values())
        for node, phi in shape.items():
            got = np.asarray(static.node_disp[node][-1], dtype=float)
            assert got[:3] == pytest.approx(phi[:3], abs=1e-6 * scale)
            if node in masters:
                assert got[5] == pytest.approx(phi[5], abs=1e-6 * scale)
                torsional += abs(phi[5]) > 1e-3 * scale
    assert torsional  # some mode turns the floors


def test_heavy_live_rule_needs_the_pack(monkeypatch) -> None:
    """Sec 2.5.7.3 (b): live loads above 3 kN/m² count with 50 % in W; the rule holds when the
    code pack carries heavyLiveLimit (the BNBC pack does since version 0.0.44), a pack
    without it keeps every live load at 25 %."""
    s = settings(massLumping="storyLevels")
    s = s.model_copy(
        update={
            "areaLoads": [
                a.model_copy(update={"live": 5.0}) if a.id == s.floorLoad else a
                for a in s.areaLoads
            ]
        }
    )

    def level1_live() -> float:
        d = derive_fem(generate(plan(), "s"), OBJECTS, MATERIALS, s, {"bim": "abc"})
        return d.summary["seismicWeight"]["levels"][0]["parts_kN"]["L"]

    assert level1_live() == pytest.approx(0.5 * 5.0 * 30, rel=1e-4)  # the BNBC pack
    real = fem_derive.code_context.table

    class Light:
        heavyLiveLimit = None
        heavyLiveShare = None

        def __init__(self, table: object) -> None:
            self._table = table

        def __getattr__(self, name: str) -> object:
            return getattr(self._table, name)

    monkeypatch.setattr(
        fem_derive.code_context,
        "table",
        lambda name: Light(real(name)) if name == "seismic" else real(name),
    )
    assert level1_live() == pytest.approx(0.25 * 5.0 * 30, rel=1e-4)

    class Heavy:
        heavyLiveLimit = 3.0
        heavyLiveShare = 0.5

        def __init__(self, table: object) -> None:
            self._table = table

        def __getattr__(self, name: str) -> object:
            return getattr(self._table, name)

    monkeypatch.setattr(
        fem_derive.code_context,
        "table",
        lambda name: Heavy(real(name)) if name == "seismic" else real(name),
    )
    assert level1_live() == pytest.approx(0.5 * 5.0 * 30, rel=1e-4)
