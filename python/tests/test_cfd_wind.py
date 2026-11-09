"""Alpha 9 L3: the CFD wind tunnel link: the OpenFOAM case of a box building, the surface
pressures of a synthetic field to Cp and storey forces, the ASCII readers, the CFD wind cases
(written 2026-11-09, not run yet: the test pass is next).

OpenFOAM itself is not run here (it is not part of SAEngine); the end-to-end pass runs one case
where an installation exists."""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes.registry import load
from saengine.fem.cfd_wind import RESULTS, foam_io, openfoam, post, runner
from saengine.fem.cfd_wind.case import (
    CaseOptions,
    boundary_layer,
    case_name,
    domain,
    write_case,
)
from saengine.fem.cfd_wind.envelope import (
    Envelope,
    envelope_from_building,
    signed_area,
    stl_text,
    to_case,
    triangulate,
)
from saengine.fem.cfd_wind.loads import apply_cfd_wind, assign_cases

BOX = ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0))
LEVELS = tuple(3.0 * (i + 1) for i in range(10))  # ten storeys of 3 m, H = 30 m


def box_envelope() -> Envelope:
    return Envelope(0.0, LEVELS, tuple((BOX,) for _ in LEVELS))


# ───────────────────────────────────────── envelope ─────────────────────────────────────────


def test_box_is_one_tier_and_setback_two() -> None:
    env = box_envelope()
    tiers = env.tiers()
    assert len(tiers) == 1
    assert (tiers[0].bottom, tiers[0].top) == (0.0, 30.0)
    small = ((5.0, 2.0), (15.0, 2.0), (15.0, 8.0), (5.0, 8.0))
    setback = Envelope(0.0, (3.0, 6.0, 9.0), ((BOX,), (BOX,), (small,)))
    tiers = setback.tiers()
    assert [(t.bottom, t.top) for t in tiers] == [(0.0, 6.0), (6.0, 9.0)]
    assert env.centre == (10.0, 5.0)
    assert env.stamp() == box_envelope().stamp()
    assert Envelope.from_json(env.to_json()).stamp() == env.stamp()


def test_envelope_from_bim_slabs_and_columns() -> None:
    stories = [NS(elevation=0.0), NS(elevation=3000.0), NS(elevation=6000.0)]
    mm = [[x * 1000, y * 1000] for x, y in BOX]
    elements = [
        NS(kind="slab", elevation=0.0, boundary=mm),  # on the ground: not an outline
        NS(kind="slab", elevation=3000.0, boundary=mm[:2] + [[20000, 5000], [0, 5000]]),
        NS(
            kind="slab",
            elevation=3000.0,
            boundary=[[0, 5000], [20000, 5000], [20000, 10000], [0, 10000]],
        ),
        # Level 6 m has no slab: the columns of the storey below give its hull.
        *[
            NS(kind="column", position=p, bottom=3000.0, top=6000.0)
            for p in ([0, 0], [10000, 0], [10000, 8000], [0, 8000])
        ],
    ]
    env = envelope_from_building(NS(stories=stories, elements=elements))
    assert env.base == 0.0
    assert env.levels == (3.0, 6.0)
    (first,) = env.outlines[0]  # the two slabs joined
    assert abs(signed_area(first)) == pytest.approx(200.0)
    (second,) = env.outlines[1]
    assert abs(signed_area(second)) == pytest.approx(80.0)
    assert any("convex hull" in n for n in env.notes)


def test_envelope_needs_a_level_above_the_base() -> None:
    with pytest.raises(ValueError):
        envelope_from_building(NS(stories=[NS(elevation=0.0)], elements=[]))


def test_triangulation_of_an_l_shape_covers_its_area() -> None:
    ell = ((0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0))
    tris = triangulate(ell)
    assert len(tris) == 4
    total = sum(abs(signed_area([ell[i], ell[j], ell[k]])) for i, j, k in tris)
    assert total == pytest.approx(abs(signed_area(ell)))
    assert all(signed_area([ell[i], ell[j], ell[k]]) > 0 for i, j, k in tris)  # CCW


def test_turning_to_the_case_puts_the_wind_along_x() -> None:
    # Wind toward 90° (+Y): the case turns the plan by -90°, so +Y of the model is +x.
    x, y = to_case((10.0, 15.0), (10.0, 5.0), 90.0)
    assert (x, y) == pytest.approx((10.0, 0.0))
    x, y = post.to_model_vector((1.0, 0.0), 90.0)
    assert (x, y) == pytest.approx((0.0, 1.0))


def test_stl_of_a_box_is_one_closed_solid() -> None:
    text = stl_text(box_envelope(), 0.0, below=1.0)
    assert text.startswith("solid building") and text.rstrip().endswith("endsolid building")
    assert text.count("facet normal") == 12  # 4 walls × 2, top 2, bottom 2
    zs = [float(v.split()[3]) for v in re.findall(r"vertex [^\n]+", text)]
    assert min(zs) == pytest.approx(-1.0) and max(zs) == pytest.approx(30.0)


# ───────────────────────────────────────── the case ─────────────────────────────────────────


def test_box_case_files(tmp_path: Path) -> None:
    env = box_envelope()
    options = CaseOptions(angle=0.0, z0=0.3, iterations=800, residual=1e-4)
    info = write_case(tmp_path / case_name(0.0), env, options)
    case = tmp_path / "dir-000"
    for rel in (
        "system/blockMeshDict",
        "system/snappyHexMeshDict",
        "system/controlDict",
        "system/fvSchemes",
        "system/fvSolution",
        "system/decomposeParDict",
        "constant/triSurface/building.stl",
        "constant/transportProperties",
        "constant/physicalProperties",
        "constant/turbulenceProperties",
        "constant/momentumTransport",
        "0.orig/U",
        "0.orig/p",
        "0.orig/k",
        "0.orig/epsilon",
        "0.orig/nut",
    ):
        assert (case / rel).is_file(), rel
    # The domain: 5H upstream, at least 15H downstream, 5H to the sides and above (H = 30 m).
    x0, x1 = info["domain"]["x"]
    y0, y1 = info["domain"]["y"]
    assert x0 == pytest.approx(-10.0 - 150.0)
    assert x1 >= 10.0 + 450.0 - 1e-9
    assert y0 == pytest.approx(-5.0 - 150.0)
    assert y1 >= 5.0 + 150.0 - 1e-9
    assert info["domain"]["z"][1] >= 180.0 - 1e-9
    cells = info["domain"]["cells"]
    assert cells[0] * cells[1] * cells[2] <= options.maxCells
    block = (case / "system/blockMeshDict").read_text()
    assert f"({cells[0]} {cells[1]} {cells[2]}) simpleGrading (1 1 1)" in block
    for patch in ("inlet", "outlet", "ground", "top", "sides"):
        assert patch in block
    u = (case / "0.orig/U").read_text()
    assert "atmBoundaryLayerInletVelocity" in u
    assert "z0              uniform 0.3;" in u
    assert "Zref            30;" in u
    assert '"building.*"' in u
    nut = (case / "0.orig/nut").read_text()
    assert "nutkAtmRoughWallFunction" in nut
    control = (case / "system/controlDict").read_text()
    assert "application     simpleFoam;" in control
    assert "endTime         800;" in control
    assert "writeFormat     ascii;" in control
    snappy = (case / "system/snappyHexMeshDict").read_text()
    inside = [float(v) for v in re.search(r"locationInMesh \(([^)]*)\)", snappy).group(1).split()]
    assert inside[0] < -10.0  # upstream of the building: in the air
    assert "level (3 3);" in snappy
    layer = boundary_layer(0.3, 30.0)
    assert info["boundaryLayer"]["ustar"] == pytest.approx(layer["ustar"])


def test_boundary_layer_log_law() -> None:
    layer = boundary_layer(0.3, 30.0, 10.0)
    ustar = 0.41 * 10.0 / math.log(30.3 / 0.3)
    assert layer["ustar"] == pytest.approx(ustar)
    assert layer["k"] == pytest.approx(ustar**2 / math.sqrt(0.09))
    assert layer["epsilon"] == pytest.approx(ustar**3 / (0.41 * 30.3))
    assert layer["omega"] == pytest.approx(layer["epsilon"] / (0.09 * layer["k"]))


def test_sst_case_and_foam_run(tmp_path: Path) -> None:
    options = CaseOptions(angle=30.0, z0=0.02, turbulence="kOmegaSST", solver="foamRun")
    info = write_case(tmp_path / case_name(30.0), box_envelope(), options)
    case = tmp_path / "dir-030"
    omega = (case / "0.orig/omega").read_text()
    assert "fixedValue" in omega  # no ABL ω inlet without OpenFOAM.com
    assert not (case / "0.orig/epsilon").exists()
    assert "application     foamRun;" in (case / "system/controlDict").read_text()
    assert any("ω" in n for n in info["notes"])
    com = CaseOptions(angle=30.0, z0=0.02, turbulence="kOmegaSST", flavour="com")
    write_case(tmp_path / "com", box_envelope(), com)
    assert "atmBoundaryLayerInletOmega" in (tmp_path / "com/0.orig/omega").read_text()


def test_mesh_is_coarsened_to_the_cell_limit() -> None:
    d = domain(box_envelope(), CaseOptions(angle=0.0, z0=0.3, cellsPerHeight=40, maxCells=200_000))
    assert d.cells[0] * d.cells[1] * d.cells[2] <= 200_000
    assert d.dx > 30.0 / 40


def test_case_names() -> None:
    assert case_name(0) == "dir-000"
    assert case_name(30) == "dir-030"
    assert case_name(360) == "dir-000"
    assert case_name(22.5) == "dir-022.5"


# ─────────────────────────────────── surface pressures to Cp ───────────────────────────────────

CP = {"windward": 0.8, "leeward": -0.5, "side": -0.7, "roof": -0.9}


def synthetic_box(uref: float = 10.0, n: int = 4) -> post.Surface:
    """A 20 x 10 x 30 m box centred at the origin (the case's axes, wind along +x), each face
    split into n x n panels, with Cp per face: windward (x = -10) 0.8, leeward -0.5, sides -0.7,
    roof -0.9. Area vectors point into the building (out of the air)."""
    q = 0.5 * uref**2
    centres, vectors, p = [], [], []

    def face(origin, du, dv, inward, cp):
        for i in range(n):
            for j in range(n):
                c = (
                    np.asarray(origin)
                    + (i + 0.5) / n * np.asarray(du)
                    + (j + 0.5) / n * np.asarray(dv)
                )
                area = np.linalg.norm(np.cross(du, dv)) / n**2
                centres.append(c)
                vectors.append(np.asarray(inward, dtype=float) * area)
                p.append(cp * q)

    face((-10, -5, 0), (0, 10, 0), (0, 0, 30), (1, 0, 0), CP["windward"])
    face((10, -5, 0), (0, 10, 0), (0, 0, 30), (-1, 0, 0), CP["leeward"])
    face((-10, -5, 0), (20, 0, 0), (0, 0, 30), (0, 1, 0), CP["side"])
    face((-10, 5, 0), (20, 0, 0), (0, 0, 30), (0, -1, 0), CP["side"])
    face((-10, -5, 30), (20, 0, 0), (0, 10, 0), (0, 0, -1), CP["roof"])
    return post.Surface(np.array(centres), np.array(vectors), np.array(p))


def test_storey_coefficients_of_a_synthetic_field() -> None:
    surface = synthetic_box(n=20)  # panels 1.5 m high: bands of 3 m hold whole panels
    levels = [3.0 * (i + 1) for i in range(10)]
    out = post.evaluate(surface, angle=0.0, levels=levels, base=0.0, uref=10.0)
    assert out["faces"] == 5 * 400
    # A middle level: 3 m of the 10 m faces, (0.8 + 0.5) per m² along the wind, sides cancel.
    middle = out["levels"][4]
    assert middle["z_m"] == pytest.approx(15.0)
    assert middle["CFx_m2"] == pytest.approx(1.3 * 10 * 3)
    assert middle["CFy_m2"] == pytest.approx(0.0, abs=1e-9)
    assert middle["CMz_m3"] == pytest.approx(0.0, abs=1e-9)  # symmetric
    assert middle["area_m2"] == pytest.approx(30.0)
    assert middle["cfAlong"] == pytest.approx(1.3)
    # The base takes the lower half of the first storey; the roof level the top half storey.
    assert out["toBase"]["CFx_m2"] == pytest.approx(1.3 * 10 * 1.5)
    assert out["levels"][-1]["CFx_m2"] == pytest.approx(1.3 * 10 * 1.5)
    assert out["total"]["CFx_m2"] == pytest.approx(1.3 * 10 * 30)
    # Facade zones of the first storey (the base's band with it).
    first = {z["zone"]: z for z in out["zones"] if z["z_m"] == pytest.approx(3.0)}
    assert first["X-"]["role"] == "windward" and first["X-"]["cpMean"] == pytest.approx(0.8)
    assert first["X+"]["role"] == "leeward" and first["X+"]["cpMean"] == pytest.approx(-0.5)
    assert first["Y+"]["role"] == "side" and first["Y-"]["cpMin"] == pytest.approx(-0.7)
    top = {z["zone"]: z for z in out["zones"] if z["z_m"] == pytest.approx(30.0)}
    assert top["roof"]["cpMean"] == pytest.approx(-0.9)


def test_turned_direction_gives_model_axes() -> None:
    # The same field for wind toward 90°: along +Y of the model; X- of the case is Y- there.
    surface = synthetic_box(n=20)
    out = post.evaluate(surface, angle=90.0, levels=[15.0, 30.0], base=2.0, uref=10.0)
    total = out["total"]
    assert total["CFx_m2"] == pytest.approx(0.0, abs=1e-9)
    assert total["CFy_m2"] == pytest.approx(1.3 * 10 * 30)
    assert out["levels"][0]["z_m"] == pytest.approx(17.0)  # absolute: base 2 m
    roles = {z["zone"]: z["role"] for z in out["zones"]}
    assert roles["Y-"] == "windward" and roles["Y+"] == "leeward"


def test_design_forces_and_cases() -> None:
    surface = synthetic_box(n=20)
    d = post.evaluate(surface, angle=0.0, levels=list(LEVELS), base=0.0, uref=10.0)
    rows = post.design_levels(d, 2.0)
    assert rows[4]["Fx_kN"] == pytest.approx(2.0 * 39.0)
    base = post.base_forces(d, 2.0, 0.0)
    assert base["Vx_kN"] == pytest.approx(2.0 * 1.3 * 10 * 28.5)  # without the base's band
    assert base["Myy_kNm"] > 0
    assert [post.case_of(a) for a in (0, 30, 44, 46, 90, 180, 225, 300, 315, 330)] == [
        "WX", "WX", "WX", "WY", "WY", "WXN", "WYN", "WYN", "WX", "WX",
    ]  # fmt: skip


def _direction(angle: float, along: float) -> dict:
    a = math.radians(angle)
    return {
        "angle": angle,
        "levels": [
            {"z_m": z, "CFx_m2": along * math.cos(a), "CFy_m2": along * math.sin(a), "CMz_m3": 0.0}
            for z in (3.0, 6.0)
        ],
    }


def test_directions_become_wind_cases_and_variants() -> None:
    directions = [_direction(a, 100.0 if a % 90 == 0 else 80.0) for a in range(0, 360, 30)]
    assigned, dropped = assign_cases(directions, 1.0, 9)
    names = {name: d["angle"] for name, d in assigned}
    assert names["WX"] == 0 and names["WY"] == 90 and names["WXN"] == 180 and names["WYN"] == 270
    assert {names["WX2"], names["WX3"]} == {30, 330}
    assert not dropped
    _, dropped = assign_cases(directions, 1.0, 2)
    assert len(dropped) == 4


# ───────────────────────────────────────── the ASCII readers ─────────────────────────────────────────

HEADER = "FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {cls};\n    object {obj};\n}}\n// * * //\n\n"


def _write_unit_cube(case: Path) -> None:
    """One 1 m hex cell, its six faces all on the patch "building" (normals out of the cell)."""
    mesh = case / "constant/polyMesh"
    mesh.mkdir(parents=True)
    points = [
        (0, 0, 0),
        (1, 0, 0),
        (1, 1, 0),
        (0, 1, 0),
        (0, 0, 1),
        (1, 0, 1),
        (1, 1, 1),
        (0, 1, 1),
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5)]
    (mesh / "points").write_text(
        HEADER.format(cls="vectorField", obj="points")
        + f"{len(points)}\n(\n"
        + "".join(f"({x} {y} {z})\n" for x, y, z in points)
        + ")\n"
    )
    (mesh / "faces").write_text(
        HEADER.format(cls="faceList", obj="faces")
        + f"{len(faces)}\n(\n"
        + "".join(f"4({' '.join(map(str, f))})\n" for f in faces)
        + ")\n"
    )
    (mesh / "owner").write_text(
        HEADER.format(cls="labelList", obj="owner") + "6\n(\n0\n0\n0\n0\n0\n0\n)\n"
    )
    (mesh / "boundary").write_text(
        HEADER.format(cls="polyBoundaryMesh", obj="boundary")
        + "1\n(\n    building\n    {\n        type wall;\n        inGroups List<word> 1(wall);\n"
        + "        nFaces 6;\n        startFace 0;\n    }\n)\n"
    )
    time_dir = case / "250"
    time_dir.mkdir()
    (time_dir / "p").write_text(
        HEADER.format(cls="volScalarField", obj="p")
        + "dimensions [0 2 -2 0 0 0 0];\n\ninternalField   nonuniform List<scalar> 1(40);\n\n"
        + "boundaryField\n{\n    building\n    {\n        type zeroGradient;\n    }\n}\n"
    )


def test_ascii_mesh_and_field_are_read(tmp_path: Path) -> None:
    _write_unit_cube(tmp_path)
    assert foam_io.latest_time(tmp_path) == tmp_path / "250"
    boundary = foam_io.read_boundary(tmp_path / "constant/polyMesh/boundary")
    assert boundary == {"building": {"type": "wall", "nFaces": 6, "startFace": 0}}
    points = foam_io.read_points(tmp_path / "constant/polyMesh/points")
    faces = foam_io.read_faces(tmp_path / "constant/polyMesh/faces")
    centres, vectors = foam_io.face_geometry(points, faces)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert np.allclose(vectors.sum(axis=0), 0.0)  # a closed cell
    assert vectors[0].tolist() == pytest.approx([0, 0, -1])  # bottom, out of the cell
    assert centres[1].tolist() == pytest.approx([0.5, 0.5, 1.0])
    surface = post.read_surface(tmp_path)
    assert surface.p.tolist() == pytest.approx([40.0] * 6)


def test_long_lists_uniform_lists_and_compact_faces(tmp_path: Path) -> None:
    labels = tmp_path / "owner"
    labels.write_text(
        HEADER.format(cls="labelList", obj="owner")
        + "12\n(\n"
        + "\n".join(str(i) for i in range(12))
        + "\n)\n"
    )
    assert foam_io.read_labels(labels).tolist() == list(range(12))
    uniform = tmp_path / "p"
    uniform.write_text(
        HEADER.format(cls="volScalarField", obj="p")
        + "internalField   nonuniform List<scalar> 30{2.5};\n"
    )
    assert foam_io.read_internal(uniform).tolist() == pytest.approx([2.5] * 30)
    plain = tmp_path / "q"
    plain.write_text(HEADER.format(cls="volScalarField", obj="q") + "internalField   uniform 0;\n")
    assert foam_io.read_internal(plain) == 0.0
    compact = tmp_path / "faces"
    compact.write_text(
        HEADER.format(cls="faceCompactList", obj="faces")
        + "3\n(\n0\n4\n7\n)\n\n7\n(\n0\n1\n2\n3\n4\n5\n6\n)\n"
    )
    faces = foam_io.read_faces(compact)
    assert [f.tolist() for f in faces] == [[0, 1, 2, 3], [4, 5, 6]]
    assert [f.tolist() for f in foam_io.read_faces(compact, 1, 1)] == [[4, 5, 6]]
    binary = tmp_path / "points"
    binary.write_text(
        HEADER.format(cls="vectorField", obj="points").replace("ascii", "binary") + "1\n(\n)\n"
    )
    with pytest.raises(foam_io.FoamFormatError):
        foam_io.read_points(binary)


# ───────────────────────────────────────── finding OpenFOAM ─────────────────────────────────────────


def test_probe_answer_and_flavour() -> None:
    values = openfoam.parse_probe(
        "noise\nSAE_BASHRC=/usr/lib/openfoam/openfoam2312/etc/bashrc\nSAE_VERSION=v2312\n"
        "SAE_HAS_simpleFoam=1\nSAE_HAS_foamRun=0\nSAE_HAS_blockMesh=1\nSAE_HAS_snappyHexMesh=1\n"
        "SAE_HAS_decomposePar=1\nSAE_HAS_reconstructPar=1\nSAE_HAS_mpirun=1\nSAE_CORES=8\n"
    )
    inst = openfoam.installation_from_probe(values, "wsl", "Ubuntu-24.04")
    assert inst.found and inst.flavour == "com" and inst.solver == "simpleFoam"
    assert inst.parallel and inst.cores == 8
    assert openfoam.flavour_of("12") == "org" and openfoam.flavour_of("dev") == "org"
    missing = openfoam.installation_from_probe({"HAS_blockMesh": "1"}, "posix", None)
    assert not missing.found and "simpleFoam" in missing.problems[0]
    org = openfoam.installation_from_probe(
        {"VERSION": "12", "HAS_foamRun": "1", "HAS_blockMesh": "1", "HAS_snappyHexMesh": "1"},
        "posix",
        None,
    )
    assert org.found and org.solver == "foamRun"
    assert openfoam.solver_argv(org, False, 1) == ["foamRun", "-solver", "incompressibleFluid"]
    assert openfoam.solver_argv(inst, True, 4) == ["mpirun", "-np", "4", "simpleFoam", "-parallel"]


def test_wsl_paths_and_the_step_script() -> None:
    assert openfoam.to_wsl_path(r"C:\Users\a b\08 FEM\x") == "/mnt/c/Users/a b/08 FEM/x"
    inst = openfoam.Installation(found=True, mode="wsl", bashrc="/opt/openfoam12/etc/bashrc")
    script = openfoam.step_script(
        Path(r"D:\p q\cases\dir-000"), inst, ["snappyHexMesh", "-overwrite"], "log.snappyHexMesh"
    )
    assert "source /opt/openfoam12/etc/bashrc" in script
    assert "cd '/mnt/d/p q/cases/dir-000'" in script
    assert "echo $$ > .sae-step.pid" in script
    assert "exec snappyHexMesh -overwrite > log.snappyHexMesh 2>&1" in script
    steps = openfoam.install_steps(windows=True)
    assert any("wsl --install" in s for s in steps)
    assert any("does not install, bundle or download" in s for s in steps)


# ───────────────────────────────────────── the run's status ─────────────────────────────────────────


def test_status_progress_and_a_stopped_run(tmp_path: Path) -> None:
    assert runner.status(tmp_path)["state"] == "none"
    data = {
        "state": "running",
        "updated": time.time(),
        "directions": [
            {"angle": 0, "state": "done", "step": "done"},
            {
                "angle": 90,
                "state": "running",
                "step": "solver",
                "iteration": 500,
                "iterations": 1000,
            },
        ],
    }
    (tmp_path / runner.STATUS).write_text(json.dumps(data))
    found = runner.status(tmp_path)
    assert found["state"] == "running"
    assert found["progress"] == pytest.approx((1 + 0.2 + 0.375) / 2)
    assert runner.cancel(tmp_path)["state"] == "cancelling"
    assert (tmp_path / runner.CANCEL).exists()
    data["updated"] = time.time() - 3600
    (tmp_path / runner.STATUS).write_text(json.dumps(data))
    assert runner.status(tmp_path)["state"] == "stopped"
    runner.cancel(tmp_path)
    assert runner.status(tmp_path)["state"] == "cancelled"


def test_start_refuses_without_a_plan(tmp_path: Path) -> None:
    assert runner.start(tmp_path)["ok"] is False


# ───────────────────────────────────────── the CFD wind cases ─────────────────────────────────────────


def _results_file(root: Path, directions: list[dict], levels: list[float]) -> None:
    data = {
        "schema": "saengine.cfdWind/1",
        "complete": True,
        "envelope": {"base_m": 0.0, "levels_m": levels, "outlines": [], "notes": []},
        "reference": {"uref": 10.0, "zref_m": levels[-1], "centre": [0.0, 0.0]},
        "settings": {},
        "directions": directions,
        "notes": [],
    }
    path = root / RESULTS
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data))


def test_cfd_storey_forces_replace_the_code_wind(tmp_path: Path) -> None:
    root = tmp_path
    levels = [3.0, 6.0]
    directions = [_direction(a, 50.0) for a in (0, 90, 180, 270)]
    _results_file(root, directions, levels)
    coords = {
        1: np.array([-5.0, -5.0, 3.0]),
        2: np.array([5.0, 5.0, 3.0]),
        3: np.array([-5.0, -5.0, 6.0]),
        4: np.array([5.0, 5.0, 6.0]),
    }
    nodes = {3.0: [1, 2], 6.0: [3, 4]}

    def shares(h: float) -> dict[int, float]:
        return {n: 0.5 for n in nodes[h]}

    def torsion(coords_, shares_, master, moment):
        return {} if not moment else {next(iter(shares_)): np.array([0, 0, 0, 0, 0, moment])}

    patterns = {"WX": {"nodal": {1: np.ones(6)}, "element": {}}, "WY": {"nodal": {}, "element": {}}}
    summary = {"wind_X_kN": 1.0, "wind_Y_kN": 1.0}
    with code_context.using(load("bnbc2020")):
        notes = apply_cfd_wind(
            model_dir=root / "08 FEM",
            heights=levels,
            base_m=0.0,
            coords=coords,
            level_shares=shares,
            retained_of={},
            torsion_forces=torsion,
            patterns=patterns,
            summary=summary,
            speed=65.0,
            exposure="A",
            importance=1.0,
        )
    cfd = summary["cfdWind"]
    q = cfd["q_kPa"]
    assert q > 0 and cfd["scale"] == 1.0
    assert set(cfd["cases"]) == {"WX", "WY", "WXN", "WYN"}
    fx = sum(v[0] for v in patterns["WX"]["nodal"].values())
    assert fx == pytest.approx(2 * 50.0 * q * 1e3)  # the code's loads are gone
    fy = sum(v[1] for v in patterns["WY"]["nodal"].values())
    assert fy == pytest.approx(2 * 50.0 * q * 1e3)
    assert sum(v[0] for v in patterns["WXN"]["nodal"].values()) == pytest.approx(
        -2 * 50.0 * q * 1e3
    )
    assert "engineer-supplied" in cfd["labels"]["WX"]
    assert any("engineer-supplied" in n for n in notes)


def test_lower_limit_scales_the_cfd_up(tmp_path: Path) -> None:
    levels = [3.0, 6.0]
    _results_file(tmp_path, [_direction(a, 1.0) for a in (0, 90)], levels)
    coords = {1: np.array([0.0, 0.0, 3.0]), 2: np.array([0.0, 0.0, 6.0])}
    summary = {"wind_X_kN": 1000.0, "wind_Y_kN": 500.0}
    patterns: dict = {}
    with code_context.using(load("bnbc2020")):
        notes = apply_cfd_wind(
            model_dir=tmp_path / "08 FEM",
            heights=levels,
            base_m=0.0,
            coords=coords,
            level_shares=lambda h: {1 if h == 3.0 else 2: 1.0},
            retained_of={},
            torsion_forces=lambda *a: {},
            patterns=patterns,
            summary=summary,
            speed=65.0,
            exposure="A",
            importance=1.0,
        )
    cfd = summary["cfdWind"]
    base_x = cfd["base"]["WX"]["Vx_kN"]
    assert base_x == pytest.approx(0.8 * 1000.0)  # bnbc2020 cfdWind.lowerLimit (SAEngine practice)
    assert any("scaled by" in n for n in notes)


def test_results_of_other_levels_are_not_used(tmp_path: Path) -> None:
    _results_file(tmp_path, [_direction(a, 1.0) for a in (0, 90)], [3.0, 6.0])
    patterns = {"WX": {"nodal": {1: np.ones(6)}, "element": {}}}
    summary: dict = {}
    with code_context.using(load("bnbc2020")):
        notes = apply_cfd_wind(
            model_dir=tmp_path / "08 FEM",
            heights=[3.5, 7.0],
            base_m=0.0,
            coords={},
            level_shares=lambda h: {},
            retained_of={},
            torsion_forces=lambda *a: {},
            patterns=patterns,
            summary=summary,
            speed=65.0,
            exposure="A",
            importance=1.0,
        )
    assert "cfdWind" not in summary
    assert 1 in patterns["WX"]["nodal"]
    assert "other levels" in notes[0]


# ───────────────────────────────────────── settings and the pack ─────────────────────────────────────────


def test_settings_default_has_no_cfd_and_pack_values() -> None:
    from saengine.fem.cfd_wind import service
    from saengine.library.settings import CfdWind, default_project_settings

    settings = default_project_settings()
    assert settings.wind.cfd is None
    assert "cfd" not in settings.model_dump(by_alias=True)["wind"]
    with code_context.using(load("bnbc2020")):
        assert service.roughness(settings)[0] == 0.3
        angles, _ = service.directions(settings)
        assert angles == [float(a) for a in range(0, 360, 30)]
    custom = settings.model_copy(deep=True)
    custom.wind.cfd = CfdWind(directions=[45, 0, 405], roughness=0.1)
    with code_context.using(load("bnbc2020")):
        assert service.directions(custom)[0] == [0.0, 45.0]
        assert service.roughness(custom)[0] == 0.1
    with code_context.using(load("eurocodes")):
        euro = settings.model_copy(deep=True)
        euro.wind.exposure = "III"
        assert service.roughness(euro)[0] == 0.3  # EN 1991-1-4 Table 4.1 via the wind table
