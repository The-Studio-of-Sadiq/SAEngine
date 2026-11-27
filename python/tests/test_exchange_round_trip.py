"""Result-level round-trip tests for .e2k, .s2k, .std, and .f2k across verified cases A3, AP3,
and DQ1 (static part only): export -> re-import -> derive -> run gives identical geometry,
sections, loads, displacements, and member end forces within 0.1 %.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from saengine.exporters.analytical import case_totals, from_osmodel
from saengine.exporters.etabs import write_e2k
from saengine.exporters.f2k import write_f2k
from saengine.exporters.s2k import write_s2k
from saengine.exporters.std import write_std
from saengine.fem.display import _elements
from saengine.importers.etabs import read_e2k
from saengine.importers.neutral import build
from saengine.importers.project import section_lookup_noted
from saengine.importers.safe import read_safe_text
from saengine.importers.sap2000 import read_sap2000_text
from saengine.importers.staad import read_staad_text
from saengine.library.bim import generate
from saengine.verification.cases import analysis, parity, rs_design
from saengine.verification.cases.common import (
    MATERIALS,
    G,
    building,
    derive,
    node_at,
    objects,
    only_pattern,
    point,
    run_model,
    settings,
    structure,
)

pytestmark = pytest.mark.slow

FORMATS = ("e2k", "s2k", "std", "f2k")
CASES = ("A3", "AP3", "DQ1")


def _pt_key(xyz: Any) -> tuple[float, float, float]:
    return (round(float(xyz[0]), 6), round(float(xyz[1]), 6), round(float(xyz[2]), 6))


def _section_dims(sec: dict[str, Any]) -> tuple[float, float]:
    """Return sorted (b, h) [m] derived from ElasticSection A and max(Iy, Iz)."""
    area = float(sec["A"])
    imax = max(float(sec["Iy"]), float(sec["Iz"]))
    h = math.sqrt(12.0 * imax / area)
    b = area / h
    return (min(b, h), max(b, h))


def _text_model_totals(text_model: Any) -> dict[str, float]:
    """Per-case resultant [kN] of a TextModel (joints in mm, loads in N / N/m)."""
    lengths = {
        f.id: float(np.linalg.norm(text_model.joints[f.j] - text_model.joints[f.i])) / 1e3
        for f in text_model.frames
        if f.i in text_model.joints and f.j in text_model.joints
    }
    totals: dict[str, float] = {}
    for case in text_model.cases.values():
        vec = np.zeros(3)
        for load in case.loads:
            if load.kind in ("joint", "point"):
                vec += load.value[:3]
            elif load.kind == "uniform":
                span = (
                    (load.length / 1e3)
                    if load.length is not None
                    else lengths.get(load.target, 0.0)
                )
                vec += load.value[:3] * span
        totals[case.name] = float(np.linalg.norm(vec)) / 1e3
    return totals


def _osmodel_pattern_totals(project: dict[str, Any]) -> dict[str, float]:
    """Per-pattern resultant [kN] of an osmodel project (nodal + element loads)."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project["nodes"]}
    elems = {e["id"]: e for e in project["elements"]}
    totals: dict[str, float] = {}
    for pat in project.get("load_patterns", []):
        vec = np.zeros(3)
        for nl in pat.get("nodal_loads", []):
            vec += np.asarray(nl["forces"][:3], dtype=float)
        for el_load in pat.get("element_loads", []):
            e = elems.get(el_load["element_id"])
            if not e:
                continue
            a, b = coords[e["nodes"][0]], coords[e["nodes"][1]]
            length = float(np.linalg.norm(b - a))
            # Transform local (wx, wy, wz) to global via element axes
            from saengine.exporters.analytical import local_axes

            x, y, z = local_axes(tuple(a), tuple(b), e.get("vecxz"))
            w = (
                x * float(el_load.get("wx", 0.0))
                + y * float(el_load.get("wy", 0.0))
                + z * float(el_load.get("wz", 0.0))
            )
            vec += w * length
        totals[pat["name"]] = float(np.linalg.norm(vec)) / 1e3
    return totals


def _build_case(case_id: str):
    """Build (bim, objs, settings, prepare_project_fn) for A3, AP3, or DQ1."""
    # Note: rigid end zones (AP3) are not carried by e2k/s2k/std/f2k, so both original and
    # imported models derive with endOffsets=False for direct result comparison.
    s = settings(endOffsets=False, diaphragm="flexible", meshSize=10000)
    if case_id == "A3":
        plan = parity._plan(stories=1, slabs=False, only="B11")
        bim = generate(plan, "v")
        objs = objects(parity.COLUMN, parity.BEAM)

        def prepare(project: dict[str, Any]) -> None:
            for node in project["nodes"]:
                node["mass"] = [0.0] * 6
            left = node_at(project, (0.0, 0.0, 3.2))
            only_pattern(project, nodal=[{"node_id": left, "forces": [10e3, 0, 0, 0, 0, 0]}])

        return bim, objs, s, prepare

    if case_id == "AP3":
        plan = parity._plan(stories=1, slabs=False, only="B11")
        bim = generate(plan, "v")
        objs = objects(parity.COLUMN, parity.BEAM)

        def prepare(project: dict[str, Any]) -> None:
            coords = {n["id"]: n["coords"] for n in project["nodes"]}
            beam = next(
                e
                for e in project["elements"]
                if e.get("type") == "ElasticBeamColumn"
                and abs(coords[e["nodes"][0]][2] - 3.2) < 1e-6
                and abs(coords[e["nodes"][1]][2] - 3.2) < 1e-6
            )
            held = set(beam["nodes"][:2]) | {
                n["id"] for n in project["nodes"] if abs(n["coords"][2]) < 1e-9
            }
            for node in project["nodes"]:
                node["restraint"] = [True] * 6 if node["id"] in held else [False] * 6
                node["mass"] = [0.0] * 6
            project["mp_constraints"] = []
            only_pattern(
                project,
                element=[{"element_id": beam["id"], "wx": 0.0, "wy": 0.0, "wz": -10e3}],
            )

        return bim, objs, s, prepare

    if case_id == "DQ1":
        # Static part of DQ1: 3 m 400x400 column under equivalent static lateral tip load.
        model = structure(
            members=[
                {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3000)}
            ],
            supports=[{"id": "S1", "at": point(0, 0, 0)}],
        )
        bim = building(model)
        objs = objects(analysis.COLUMN)
        sa = 2 / 3 * 0.20 * 1.0 / 5.0 * 2.5 * 1.35 * G
        v_static = rs_design.STATIC_OVER_DYNAMIC * rs_design.MASS * sa

        def prepare(project: dict[str, Any]) -> None:
            for node in project["nodes"]:
                node["mass"] = [0.0] * 6
            top = node_at(project, (0.0, 0.0, 3.0))
            only_pattern(project, nodal=[{"node_id": top, "forces": [v_static, 0, 0, 0, 0, 0]}])

        return bim, objs, s, prepare

    raise AssertionError(f"unknown case {case_id}")


def _run_and_extract(project: dict[str, Any], folder: Path) -> dict[str, Any]:
    """Run the first static case of ``project`` and return canonical geometry, sections,
    displacements, and global 12-component end forces per frame member."""
    case_id = project["analyses"][0]["id"]
    _, _, results = run_model(project, folder, [case_id])
    res = results[case_id]
    coords = {n["id"]: _pt_key(n["coords"]) for n in project["nodes"]}
    sections_by_id = {s["id"]: s for s in project["sections"]}
    raw_elems = {e["id"]: e for e in project["elements"]}

    node_disp = {
        coords[n["id"]]: np.asarray(res.node_disp[n["id"]][-1], dtype=float)
        for n in project["nodes"]
    }

    members: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]], dict[str, Any]
    ] = {}
    for el in _elements(project):
        pi, pj = coords[el.i], coords[el.j]
        flipped = pj < pi
        key = (pj, pi) if flipped else (pi, pj)
        raw_f = np.asarray(res.element_forces[el.id][-1][:12], dtype=float)
        fi = el.axes.T @ raw_f[0:3]
        mi = el.axes.T @ raw_f[3:6]
        fj = el.axes.T @ raw_f[6:9]
        mj = el.axes.T @ raw_f[9:12]
        global_forces = np.concatenate([fj, mj, fi, mi] if flipped else [fi, mi, fj, mj])
        sec = sections_by_id[raw_elems[el.id]["section_id"]]
        members[key] = {
            "dims": _section_dims(sec),
            "A": float(sec["A"]),
            "forces": global_forces,
        }

    return {
        "nodes": sorted(coords.values()),
        "node_disp": node_disp,
        "members": members,
    }


def _assert_close_vectors(ref: np.ndarray, got: np.ndarray, label: str, floor_scale: float) -> None:
    floor = 1e-6 * max(floor_scale, 1e-12)
    for idx, (a, b) in enumerate(zip(ref, got, strict=True)):
        tol = max(0.001 * abs(a), floor)
        assert abs(b - a) <= tol, f"{label}[{idx}]: expected {a}, got {b} (tol {tol})"


@pytest.mark.parametrize("case_id", CASES)
@pytest.mark.parametrize("fmt", FORMATS)
def test_exchange_round_trip(tmp_path: Path, case_id: str, fmt: str) -> None:
    bim, objs, s, prepare = _build_case(case_id)
    orig_derived = derive(bim, objs, MATERIALS, s)
    orig_project = orig_derived.project
    pre_load_totals = _osmodel_pattern_totals(orig_project)

    prepare(orig_project)
    orig_out = _run_and_extract(orig_project, tmp_path / "orig")

    if fmt == "e2k":
        e2k_path = tmp_path / f"{case_id}.e2k"
        write_e2k(bim, objs, MATERIALS, s, name=case_id).write(e2k_path)
        imported = read_e2k(e2k_path, section_lookup=section_lookup_noted)
        # Check derived self-weight loads match pre-only_pattern original
        imp_derived = derive(imported.bim, imported.objects, imported.materials, s)
        imp_totals = _osmodel_pattern_totals(imp_derived.project)
        assert imp_totals.get("D", 0.0) == pytest.approx(pre_load_totals.get("D", 0.0), rel=0.001)
    else:
        am = from_osmodel(orig_project, objs, MATERIALS, s, name=case_id)
        expected_totals = case_totals(am)
        if fmt == "s2k":
            text = write_s2k(am)
            text_model = read_sap2000_text(text, f"{case_id}.s2k")
        elif fmt == "std":
            text = write_std(am)
            text_model = read_staad_text(text, f"{case_id}.std")
        else:
            text = write_f2k(am)
            text_model = read_safe_text(text, f"{case_id}.f2k")

        got_totals = _text_model_totals(text_model)
        for cname, exp_val in expected_totals.items():
            matched = next(
                (
                    v
                    for k, v in got_totals.items()
                    # .std case titles read back as "<number> <name>: <title>"
                    if k.upper() == cname.upper()
                    or re.match(rf"^\d+ {re.escape(cname.upper())}(:|$)", k.upper())
                ),
                None,
            )
            assert matched is not None, f"missing case {cname} in {got_totals}"
            assert matched == pytest.approx(exp_val, rel=0.001, abs=1e-6)

        imported = build(text_model, case_id)
        imp_derived = derive(imported.bim, imported.objects, imported.materials, s)

    imp_project = imp_derived.project
    prepare(imp_project)
    imp_out = _run_and_extract(imp_project, tmp_path / "imp")

    # 1. Same number of frame elements and exact member endpoints
    assert len(imp_out["members"]) == len(orig_out["members"])
    assert set(imp_out["members"]) == set(orig_out["members"])

    # 2. Same node coordinates within 1e-6 m
    assert len(imp_out["nodes"]) == len(orig_out["nodes"])
    for p0, p1 in zip(orig_out["nodes"], imp_out["nodes"], strict=True):
        assert p1 == pytest.approx(p0, abs=1e-6)

    # 3. Same section dimensions per member
    for key, m0 in orig_out["members"].items():
        m1 = imp_out["members"][key]
        assert m1["dims"] == pytest.approx(m0["dims"], rel=1e-6, abs=1e-6)
        assert m1["A"] == pytest.approx(m0["A"], rel=1e-6, abs=1e-9)

    # 4. Every node displacement and every member end force within 0.1 % (floor 1e-6 * max)
    max_disp = max(float(np.max(np.abs(v))) for v in orig_out["node_disp"].values())
    for pt, d0 in orig_out["node_disp"].items():
        _assert_close_vectors(d0, imp_out["node_disp"][pt], f"{case_id} {fmt} disp@{pt}", max_disp)

    max_force = max(float(np.max(np.abs(m["forces"]))) for m in orig_out["members"].values())
    for key, m0 in orig_out["members"].items():
        _assert_close_vectors(
            m0["forces"],
            imp_out["members"][key]["forces"],
            f"{case_id} {fmt} force@{key}",
            max_force,
        )
