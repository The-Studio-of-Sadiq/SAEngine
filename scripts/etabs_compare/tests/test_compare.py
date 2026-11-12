"""Tests of the comparison harness's report and tolerance logic (scripts/etabs_compare).

    python -m pytest -q scripts/etabs_compare/tests

CI-safe: synthetic data only, no analysis program, no SAEngine run.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = load("compare")


def q(saengine, reference, kind, **kw):
    return C.judge(C.Quantity("g", "n", saengine, reference, kind, **kw), {kind: "a reason"})


def test_tolerances_pass_and_flag():
    assert q(1.0, 1.019, "period").status == "PASS"
    flagged = q(1.0, 1.021, "period")
    assert flagged.status == "FLAG" and flagged.reason == "a reason"
    assert flagged.diff_pct == pytest.approx(2.1)
    assert flagged.tol_pct == pytest.approx(2.0)
    assert q(100.0, 100.9, "reaction").status == "PASS"
    assert q(100.0, 101.1, "reaction").status == "FLAG"
    assert q(43.95, 37.16, "baseShear").status == "FLAG"
    assert q(10.0, 10.49, "faceMoment").status == "PASS"
    assert q(0.001, 0.0011, "drift").status == "FLAG"


def test_signs_are_ignored_and_floor_passes_small_values():
    assert q(-43.95, -43.95, "baseShear").status == "PASS"
    small = C.judge(C.Quantity("g", "n", 0.30, 0.22, "faceMoment"), {}, floor=0.5)
    assert small.status == "PASS" and "floor" in small.reason


def test_missing_values():
    m = q(None, 1.0, "period")
    assert m.status == "MISSING" and "SAEngine" in m.reason


def test_internal_forces_simply_supported_beam():
    # a 6 m beam, w = 10 kN/m down (local z up: wz = -10); end i reaction 30 kN up
    # forces on the element at i: Vz = +30, My = 0 (pinned)
    fi = [0.0, 0.0, 30.0, 0.0, 0.0, 0.0]
    w = [0.0, 0.0, -10.0]
    mid = C.internal_forces(fi, w, 3.0)
    assert abs(mid[4]) == pytest.approx(10 * 6**2 / 8)  # wL²/8
    assert abs(mid[2]) == pytest.approx(0.0)  # no shear at mid-span
    end = C.internal_forces(fi, w, 6.0)
    assert abs(end[4]) == pytest.approx(0.0, abs=1e-9)
    assert abs(end[2]) == pytest.approx(30.0)


def test_saengine_at_picks_the_sub_element():
    span = {
        "kind": "beam",
        "subs": [
            {
                "a": 0.0,
                "b": 1.0,
                "axes": {},
                "cases": {"D": {"fi": [0, 0, 30, 0, 0, 0], "w": [0, 0, -10]}},
            },
            {
                "a": 1.0,
                "b": 6.0,
                "axes": {},
                "cases": {"D": {"fi": [0, 0, 20, 0, -25, 0], "w": [0, 0, -10]}},
            },
        ],
    }
    at = C.saengine_at(span, "D", 3.0)
    # from the second sub-element: x = 2, My = -(-25 + 20*2 - 10*4/2) = 5
    assert abs(at["f"][4]) == pytest.approx(5.0)
    assert C.saengine_at(span, "L", 3.0) is None


def test_column_components_on_the_reference_axes():
    # a vertical member: SAEngine local y = -Y, local z = +X
    axes = {"y": [0.0, -1.0, 0.0], "z": [1.0, 0.0, 0.0]}
    bottom, top = [0.0, 0.0, 0.0], [0.0, 0.0, 3.0]
    # the reference at angle 0: local 2 = X, local 3 = Y
    s = C.moment_components("column", [0, 0, 0, 0, 4.0, 3.0], axes, C.reference_axes(bottom, top))
    assert s == {"M2": pytest.approx(3.0), "M3": pytest.approx(4.0)}
    assert C.reference_components("column", {"M2": -3.0, "M3": 4.0}) == {"M2": 3.0, "M3": 4.0}
    # at 90° the reference's local 2 is Y: the components swap
    s90 = C.moment_components(
        "column", [0, 0, 0, 0, 4.0, 3.0], axes, C.reference_axes(bottom, top, 90.0)
    )
    assert s90["M2"] == pytest.approx(4.0) and s90["M3"] == pytest.approx(3.0)
    assert C.reference_components("beam", {"M2": 1.0, "M3": 9.0}) == {
        "Mmajor": 9.0,
        "Mminor": 1.0,
    }


def test_reference_axes_follow_the_documented_defaults():
    beam = C.reference_axes([0, 0, 3], [6, 0, 3])
    assert beam["e2"] == pytest.approx([0, 0, 1]) and beam["e3"] == pytest.approx([0, -1, 0])
    col = C.reference_axes([0, 0, 0], [0, 0, 3], 135.0)
    r = math.sqrt(0.5)
    assert col["e2"] == pytest.approx([-r, r, 0]) and col["e3"] == pytest.approx([-r, -r, 0])


def test_mirror_angle_gives_the_reference_saengine_axes():
    # a column at 135° analysed with its own vecxz: SAEngine's local z is the vecxz
    r = math.sqrt(0.5)
    assert C.mirror_angle([0, 0, 0], [0, 0, 3], [-r, r, 0]) == pytest.approx(135.0)
    # an unturned column and a beam along X need no angle
    assert C.mirror_angle([0, 0, 0], [0, 0, 3], [1, 0, 0]) == 0.0
    assert C.mirror_angle([0, 0, 3], [6, 0, 3], [0, 0, 1]) == 0.0
    # a brace sloping in the vertical YZ plane: SAEngine (vecxz = X) has local y in that
    # plane and local z = X horizontal, the reference's default local 2 is in the plane:
    # a quarter turn makes its local 3 SAEngine's y, so M3 is SAEngine's My
    pi, pj = [0, 0, 0], [0, 1, 3]
    x = C._unit([0, 1, 3])
    y = C._unit(C._cross([1, 0, 0], x))
    z = C._cross(x, y)
    angle = C.mirror_angle(pi, pj, z)
    assert abs(angle) == pytest.approx(90.0)
    ref = C.reference_axes(pi, pj, angle)
    assert abs(C._dot(ref["e3"], y)) == pytest.approx(1.0)
    m = C.moment_components("brace", [0, 0, 0, 0, 7.0, 2.0], {"y": y, "z": z}, ref)
    assert m == {"Mmajor": pytest.approx(7.0), "Mminor": pytest.approx(2.0)}
    # with the default axes the same moments would be the other way round
    m0 = C.moment_components(
        "brace", [0, 0, 0, 0, 7.0, 2.0], {"y": y, "z": z}, C.reference_axes(pi, pj)
    )
    assert m0 == {"Mmajor": pytest.approx(2.0), "Mminor": pytest.approx(7.0)}


def test_rigid_end_offsets_start_the_statics_at_the_faces():
    # a 5 m cantilever with 0.5 m rigid zones and a 10 kN tip load: OpenSees localForce
    # (-jntOffset) gives My_i = -45 at the face (0.5 m), the reaction moment is 50
    span = {
        "kind": "beam",
        "subs": [
            {
                "na": 0.0,
                "nb": 5.0,
                "a": 0.5,
                "b": 4.5,
                "axes": {},
                "cases": {"D": {"fi": [0, 0, 10, 0, -45, 0], "w": [0, 0, 0]}},
            }
        ],
    }
    assert abs(C.saengine_at(span, "D", 0.5)["f"][4]) == pytest.approx(45.0)
    assert abs(C.saengine_at(span, "D", 0.0)["f"][4]) == pytest.approx(50.0)
    assert abs(C.saengine_at(span, "D", 4.5)["f"][4]) == pytest.approx(5.0)
    # a reversed element (node i at the span's end) measures from its own face
    rev = {"kind": "beam", "subs": [{**span["subs"][0], "na": 5.0, "nb": 0.0, "a": 4.5, "b": 0.5}]}
    assert abs(C.saengine_at(rev, "D", 4.5)["f"][4]) == pytest.approx(45.0)


def test_span_load_acts_on_the_flexible_length_only():
    # 6 m between joints, 0.3 m rigid zones, w = 10 kN/m on the 5.4 m flexible part, pinned
    # at the faces: Vz_i = 27, My = 0 at the face; mid-span wL²/8 of the flexible length
    sub = {
        "na": 0.0,
        "nb": 6.0,
        "a": 0.3,
        "b": 5.7,
        "axes": {},
        "cases": {"D": {"fi": [0, 0, 27, 0, 0, 0], "w": [0, 0, -10]}},
    }
    span = {"kind": "beam", "subs": [sub]}
    assert abs(C.saengine_at(span, "D", 3.0)["f"][4]) == pytest.approx(10 * 5.4**2 / 8)
    # inside the rigid zone at j: the shear carries on with no load (27 - 54 = -27)
    at_face = C.saengine_at(span, "D", 5.7)["f"]
    at_node = C.saengine_at(span, "D", 6.0)["f"]
    assert abs(at_face[4]) == pytest.approx(0.0, abs=1e-9)
    assert abs(at_node[2]) == pytest.approx(27.0)
    assert abs(at_node[4]) == pytest.approx(27.0 * 0.3)


def _synthetic(ref_scale: float = 1.0):
    csv_mass = "Story,UX,UY\nL1,80,80\nBase,5,5\n"
    csv_forces = "Story,Output Case,Location,VX,VY\nL1,EX,Bottom,-44,0\nL1,EY,Bottom,0,-44\n"
    csv_cm = "Story,Diaphragm,Output Case,UX,UY\nL1,D1,EX,0.0001,0\nL1,D1,EY,0,0.0003\n"
    sae = {
        "modal": {
            "periods": [0.2, 0.1, 0.05],
            "effMass_t": [[70, 1], [1, 70], [5, 5]],
            "massTotal_t": 80.0,
        },
        "baseReactions": {
            "D": [0, 0, 500, 0, 0, 0],
            "EX": [-44, 0, 0, 0, 0, 0],
            "EY": [0, -44, 0, 0, 0, 0],
        },
        "seismic": {"W_kN": 784.5, "V_kN": 44.0, "massTotal_t": 80.0},
        "stories": {
            "levels": [{"name": "L1", "z": 3.2, "h": 3.2}],
            "shear": {"EX": {"L1": 44.0}, "EY": {"L1": 44.0}},
            "cmDisp": {"EX": {"L1": [0.0001, 0.0]}, "EY": {"L1": [0.0, 0.0003]}},
        },
        "members": [
            {
                "label": "B1",
                "kind": "beam",
                "angle": 0.0,
                "length": 6.0,
                "subs": [
                    {
                        "a": 0.0,
                        "b": 6.0,
                        "axes": {"y": [0, 1, 0], "z": [0, 0, 1]},
                        "cases": {"D": {"fi": [0, 0, 30, 0, 30, 0], "w": [0, 0, -10]}},
                    }
                ],
            }
        ],
        "analysisSettings": {},
    }
    s = ref_scale
    ref = {
        "mode": "native",
        "runs": [
            {
                "cases": ["EX", "EY", "Modal"],
                "modal": [
                    {"mode": 1, "T": 0.2 * s, "UX": 70 / 80, "UY": 1 / 80},
                    {"mode": 2, "T": 0.1, "UX": 1 / 80, "UY": 70 / 80},
                    {"mode": 3, "T": 0.05, "UX": 5 / 80, "UY": 5 / 80},
                ],
                "base": [
                    {"case": "EX", "FX": -44 * s, "FY": 0, "FZ": 0},
                    {"case": "EY", "FX": 0, "FY": -44, "FZ": 0},
                ],
                "frames": {},
                "tables": {
                    "Mass Summary by Story": {"csv": csv_mass},
                    "Story Forces": {"csv": csv_forces},
                    "Diaphragm Center Of Mass Displacements": {"csv": csv_cm},
                },
            },
            {
                "cases": ["D"],
                "base": {"case": "D", "FX": 0, "FY": 0, "FZ": 500},
                # a single row serialised as an object, as PowerShell does
                "frames": {
                    "B1": {
                        "first": {
                            "case": "D",
                            "sta": 0.25,
                            "P": 0,
                            "V2": 0,
                            "V3": 0,
                            "T": 0,
                            "M2": 0,
                            "M3": 22.1875,
                        },
                        "last": [
                            {
                                "case": "D",
                                "sta": 5.75,
                                "P": 0,
                                "V2": 0,
                                "V3": 0,
                                "T": 0,
                                "M2": 0,
                                "M3": 0,
                            }
                        ],
                        "lastStart": 0.0,
                    }
                },
                "tables": {},
            },
        ],
    }
    return sae, ref


def test_compare_end_to_end(tmp_path: Path):
    sae, ref = _synthetic()
    quantities = C.compare(sae, ref, "native")
    by = {(x.name, x.case): x for x in quantities}
    assert by[("T1", "Modal")].status == "PASS"
    assert by[("mode 1 effective mass UX", "Modal")].status == "PASS"
    assert by[("base FZ", "D")].status == "PASS"
    assert by[("static base shear V", "EX")].status == "PASS"
    assert by[("storey shear L1", "EX")].status == "PASS"
    assert by[("storey drift L1 (centre of mass)", "EY")].status == "PASS"
    w = by[("seismic weight W", "")]
    assert w.reference == pytest.approx(80 * C.G) and w.status == "PASS"
    # B1 i face at 0.25 m: M = -(30 + 30*0.25 - 10*0.25²/2) -> 37.1875 vs 22.1875: FLAG
    face = by[("B1 i Mmajor", "D")]
    assert face.saengine == pytest.approx(37.1875)
    assert face.status == "FLAG" and "end zones" in face.reason
    assert face.detail["station_m"] == pytest.approx(0.25)
    doc = C.write_outputs(
        tmp_path,
        {"project": "Synthetic", "mode": "native", "members": ["B1"]},
        quantities,
        {"SAEngine": ["a note"]},
    )
    assert doc["summary"]["FLAG"] >= 1
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "| B1 i Mmajor @ 0.250 m | D |" in report and "FLAG" in report
    assert "ETABS" not in report  # public material never names the reference program
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["schema"] == "saengine.referenceComparison/1"
    assert data["tolerances"]["period"]["rel"] == 0.02


def test_mirror_beam_moment_flag_does_not_blame_the_mesh():
    reasons = C.reasons_for("mirror", {"analysisSettings": {"slabs": "shells", "meshSize": 1000}})
    assert "not the mesh" in reasons["faceMoment"]


def test_native_skew_reason_only_when_the_column_was_snapped():
    def span(vecxz):
        return {
            "label": "C2",
            "kind": "column",
            "angle": 135.0,
            "start": [0, 0, 0],
            "end": [0, 0, 3],
            "length": 3.0,
            "subs": [
                {
                    "na": 0.0,
                    "nb": 3.0,
                    "a": 0.0,
                    "b": 3.0,
                    "vecxz": vecxz,
                    "axes": {"y": [0, -1, 0], "z": [1, 0, 0]},
                    "cases": {"D": {"fi": [0, 0, 0, 0, 10, 0], "w": [0, 0, 0]}},
                }
            ],
        }

    row = {"case": "D", "sta": 0.0, "P": 0, "M2": 20.0, "M3": 20.0}
    frames = {"C2": {"first": [row], "last": [{**row, "sta": 3.0}], "lastStart": 0.0}}
    ref = {"mode": "native", "runs": [{"cases": ["D"], "frames": frames}]}
    for vecxz, snapped in ((None, True), ([-0.7071, 0.7071, 0], False)):
        sae = {"members": [span(vecxz)], "analysisSettings": {}}
        flags = [q for q in C.compare(sae, ref, "native") if q.status == "FLAG"]
        assert flags
        assert all(("snapped" in q.reason) == snapped for q in flags)


def test_compare_flags_a_period_difference_with_the_mirror_reason():
    sae, ref = _synthetic(ref_scale=1.05)
    by = {(x.name, x.case): x for x in C.compare(sae, ref, "mirror")}
    t1 = by[("T1", "Modal")]
    assert t1.status == "FLAG" and "solver" in t1.reason
    assert by[("base FX", "EX")].status == "FLAG"
    assert math.isclose(by[("base FX", "EX")].diff_pct, 5.0, rel_tol=1e-6)


def test_mirror_input_loads_the_flexible_length_and_turns_skewed_frames(tmp_path: Path):
    pytest.importorskip("saengine.fem.derive")
    sys.path.insert(0, str(HERE))
    X = load("sae_export")
    project = tmp_path / "P"
    (project / "06 BIM").mkdir(parents=True)
    (project / "08 FEM").mkdir()
    bim = {"stories": [{"id": "Base", "elevation": 0}, {"id": "L1", "elevation": 3000}]}
    (project / "06 BIM" / "bim.json").write_text(json.dumps(bim), encoding="utf-8")
    r = math.sqrt(0.5)
    free, fixed = [False] * 6, [True] * 6
    model = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "mass": [0] * 6, "restraint": fixed},
            {"id": 2, "coords": [0, 0, 3], "mass": [0] * 6, "restraint": free},
            {"id": 3, "coords": [6, 0, 3], "mass": [0] * 6, "restraint": free},
        ],
        "sections": [
            {
                "id": 1,
                "type": "ElasticSection",
                "name": "C1",
                "E": 2.5e10,
                "G": 1e10,
                "A": 0.09,
                "J": 1e-3,
                "Iy": 6e-4,
                "Iz": 7e-4,
            },
        ],
        "elements": [
            {
                "id": 1,
                "name": "C2",
                "type": "ElasticBeamColumn",
                "nodes": [1, 2],
                "section_id": 1,
                "vecxz": [-r, r, 0.0],
            },
            {
                "id": 2,
                "name": "B1",
                "type": "ElasticBeamColumn",
                "nodes": [2, 3],
                "section_id": 1,
                "joint_offsets": [0.3, 0, 0, -0.3, 0, 0],
            },
        ],
        "load_patterns": [
            {
                "id": 1,
                "name": "D",
                "type": "Plain",
                "nodal_loads": [{"node_id": 2, "forces": [0, 0, -3000, 0, 0, 0]}],
                "element_loads": [{"element_id": 2, "wx": 0, "wy": 0, "wz": -10000}],
            },
        ],
        "analyses": [{"type": "Static", "name": "D", "pattern_ids": [1]}],
        "mp_constraints": [],
    }
    (project / "08 FEM" / "model.osmodel").write_text(json.dumps(model), encoding="utf-8")
    out = X.mirror_input(project, [])
    frames = {f["member"]: f for f in out["frames"]}
    assert frames["C2"]["angle"] == pytest.approx(135.0)
    assert frames["B1"]["angle"] == 0.0
    span_load = out["elem_loads"]["D"][0]
    assert span_load["d0"] == pytest.approx(0.05) and span_load["d1"] == pytest.approx(0.95)
    assert span_load["length"] == pytest.approx(5.4)
    assert span_load["g"] == pytest.approx([0, 0, -10])  # local z of a beam along X is +Z
    assert X.flexible_ends(model["elements"][1]) == pytest.approx((0.3, 0.3))
    # native mode gives the reference's automatic end offsets SAEngine's rigid-zone factor
    from types import SimpleNamespace

    settings = SimpleNamespace(analysis=SimpleNamespace())
    assert X.rigid_zone_factor(project, model, settings) == 0.5
    (project / "08 FEM" / "faces.json").write_text('{"rigidZoneFactor": 0.75}', encoding="utf-8")
    assert X.rigid_zone_factor(project, model, settings) == 0.75
    plain = {"elements": [e for e in model["elements"] if "joint_offsets" not in e]}
    assert X.rigid_zone_factor(project, plain, settings) is None


def test_rigid_zone_reasons_name_the_axial_and_torsion_convention():
    plain = {"members": [{"subs": [{"rigid": [0.0, 0.0]}]}], "analysisSettings": {}}
    zoned = {"members": [{"subs": [{"rigid": [0.25, 0.0]}]}], "analysisSettings": {}}
    assert not C.has_rigid_zones(plain) and C.has_rigid_zones(zoned)
    assert "torsion" in C.reasons_for("mirror", zoned)["period"]
    assert "torsion" not in C.reasons_for("mirror", plain)["period"]
    assert "same factor" in C.reasons_for("native", zoned)["faceMoment"]
    assert "same factor" not in C.reasons_for("native", plain)["faceMoment"]
