"""Seismically isolated buildings (B37, saengine.fem.isolation): the code pack's values (BNBC
2020 Part 6 Sec 2.5.16, Table 6.2.24), the isolator curve, the displacements, forces and checks,
and the isolators in the derived analysis model."""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.fem import isolation as iso
from saengine.fem.derive import derive_fem
from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan, default_material_library
from saengine.library.bim import generate
from saengine.library.objects import SeismicIsolator
from saengine.library.settings import default_project_settings

G = 9.80665


# ─────────────────────────────── the code pack ───────────────────────────────


@pytest.mark.parametrize(
    ("beta", "b"),
    [(2, 0.8), (5, 1.0), (10, 1.2), (20, 1.5), (30, 1.7), (40, 1.9), (50, 2.0)],
)
def test_damping_coefficient_table_6_2_24(beta: float, b: float) -> None:
    assert iso.damping_coefficient(beta) == pytest.approx(b)


def test_damping_coefficient_interpolates_and_clamps() -> None:
    # Table 6.2.24 note b: linear interpolation; at most 2 % -> 0.8, at least 50 % -> 2.0.
    assert iso.damping_coefficient(15) == pytest.approx(1.35)
    assert iso.damping_coefficient(1) == pytest.approx(0.8)
    assert iso.damping_coefficient(70) == pytest.approx(2.0)


@pytest.mark.parametrize(("r", "ri"), [(8, 2.0), (5, 1.875), (4, 1.5), (2, 1.0)])
def test_reduction_factor_sec_2_5_16_2_2(r: float, ri: float) -> None:
    # RI the lesser of 3/8 R and 2.0, but not less than 1.0 (p. 661).
    assert iso.reduction_factor(r) == pytest.approx(ri)


def test_pack_values_sec_2_5_16() -> None:
    t = code_context.table("isolation")
    # Sec 2.5.16.2 (p. 658): equivalent static analysis limits.
    assert t.staticLimits.siteClasses == ["SA", "SB", "SC", "SD", "SE"]
    assert (t.staticLimits.maxStoreys, t.staticLimits.maxHeight) == (4, 20.0)
    assert t.staticLimits.maxPeriodM == 3.0 and t.staticLimits.periodRatio == 3.0
    assert t.staticLimits.stiffnessRatio == pytest.approx(1 / 3)
    assert t.staticLimits.stiffnessAtShare == 0.2
    # Sec 2.5.16.1 (4), (7) (p. 653).
    assert (t.restoring.forceShare, t.restoring.atShare) == (0.025, 0.5)
    assert t.overturning.minimumFactor == 1.0
    # Sec 2.5.16.2.2 (pp. 660-661).
    assert t.forces.importance == 1.0 and t.forces.activationFactor == 1.5
    # Drift limits: Sec 2.5.16.2.4 (p. 662), 2.5.16.3.3 (p. 664).
    assert (t.drift.static, t.drift.spectrum, t.drift.history) == (0.015, 0.015, 0.020)
    # Sec 2.5.16.3.1 (p. 663).
    assert t.spectrumAnalysis.maxModalDamping == 30.0
    assert t.spectrumAnalysis.orthogonalShare == 0.3
    assert t.spectrum.mceFactor == 1.5
    # Sec 2.5.16.3.2 (pp. 663-664).
    h = t.history
    assert (h.minRecords, h.averageFrom) == (3, 7)
    assert (h.periodFromShare, h.periodToShare, h.spectrumFactor, h.tolerance) == (
        0.5,
        1.25,
        1.3,
        0.1,
    )
    # Sec 2.5.16.4 (p. 665): 20 wind cycles, 3 at 0.25/0.5/1.0 DD, 1.0 DM, 1.0 DTM, 10 at DTD.
    steps = [(s.share, s.of, s.cycles) for s in t.testing.steps]
    assert t.testing.windCycles == 20 and t.testing.liveShare == 0.5
    assert steps == [
        (0.25, "DD", 3),
        (0.5, "DD", 3),
        (1.0, "DD", 3),
        (1.0, "DM", 3),
        (1.0, "DTM", 3),
        (1.0, "DTD", 10),
    ]
    assert [r.id for r in t.requirements] == [str(k) for k in range(1, 14)]
    assert len(t.review) == 5


# ─────────────────────────────── the isolator ───────────────────────────────


def test_bilinear_curve_secant_stiffness_and_loop() -> None:
    c = iso.Curve(qd=60e3, kd=800e3, dy=0.015)
    assert c.fy == pytest.approx(72e3)
    assert c.force(0.2) == pytest.approx(60e3 + 800e3 * 0.2)
    assert c.stiffness(0.2) == pytest.approx((60e3 + 160e3) / 0.2)
    assert c.stiffness(0.01) == pytest.approx(72e3 / 0.015)  # elastic branch
    assert c.loop(0.2) == pytest.approx(4 * 60e3 * (0.2 - 0.015))
    beta = iso.system_damping([c], 0.2)
    assert beta == pytest.approx(4 * 60e3 * 0.185 / (2 * math.pi * 1.1e6 * 0.04))


def test_displacement_eq_6_2_62_and_period_eq_6_2_63() -> None:
    assert iso.spectral_displacement(0.3, 2.5, 1.5) == pytest.approx(
        0.3 * G * 2.5**2 / (4 * math.pi**2 * 1.5)
    )
    assert iso.effective_period(10e6, 6e6) == pytest.approx(2 * math.pi * math.sqrt(10e6 / 6e6 / G))


def test_solved_displacement_is_consistent() -> None:
    curves = [iso.Curve(60e3, 800e3, 0.015)] * 8
    weight = 8 * 1500e3
    found = iso.solve_displacement(curves, weight, "SD", 0.20)
    assert found["converged"]
    d = found["D"]
    k = iso.system_stiffness(curves, d)
    t = iso.effective_period(weight, k)
    b = iso.damping_coefficient(100 * iso.system_damping(curves, d))
    sa = iso.spectral_acceleration(t, "SD", 0.20)
    assert d == pytest.approx(iso.spectral_displacement(sa, t, b), rel=1e-4)
    # The MCE spectrum is 1.5 times the design spectrum; SaM at the larger of TD and TM.
    m = iso.solve_displacement(curves, weight, "SD", 0.20, mce=True, design_period=found["T"])
    assert m["D"] > d
    assert m["Sa"] >= 1.5 * iso.spectral_acceleration(m["T"], "SD", 0.20) - 1e-12


def test_eq_6_2_68_distribution() -> None:
    forces = iso.distribute([(0.0, 500.0), (3.0, 1000.0), (6.0, 1000.0)], 900.0)
    assert forces == pytest.approx([0.0, 300.0, 600.0])


# ─────────────────────────────── the design ───────────────────────────────


def _units(spec: SeismicIsolator, a: float = 5.0) -> list[iso.Unit]:
    return [
        iso.Unit(f"C{k}", "COL", k + 1, x, y, spec)
        for k, (x, y) in enumerate([(-a, -a), (a, -a), (a, a), (-a, a)])
    ]


def test_rigid_deck_torsion_of_a_symmetric_square() -> None:
    # Four equal units at (±a, ±a): K = 4k, Kθ = 8ka², e = 0.05·2a; the corner moves
    # D (1 + K e a / Kθ) = 1.05 D.
    units = _units(SeismicIsolator())
    found = iso.total_displacements(units, (0.0, 0.0), 0.2, 0.05)
    assert found["X"]["factor"] == pytest.approx(1.05)
    assert found["Y"]["total"] == pytest.approx(0.21)


def _design(spec: SeismicIsolator, **kw):
    levels = [(0.0, 1000e3), (3.0, 1500e3), (6.0, 1500e3)]
    args = {
        "site_class": "SD",
        "z": 0.20,
        "r": {"X": 8.0, "Y": 5.0},
        "fixed_period": {"X": 0.4, "Y": 0.45},
        "wind_shear": {"X": 50e3, "Y": 40e3},
        "storeys": 2,
        "accidental_share": 0.05,
    }
    args.update(kw)
    return iso.design(_units(spec), levels, (0.0, 0.0), **args)


def test_design_forces_and_checks() -> None:
    spec = SeismicIsolator(
        characteristicStrength=60, postYieldStiffness=800, yieldDisplacement=15,
        lowerBoundFactor=0.85, upperBoundFactor=1.2, displacementCapacity=600,
    )  # fmt: skip
    out = _design(spec)
    dd = out["design"]["D_mm"] / 1e3
    upper = iso.curve_of(spec).scaled(1.2)
    vb = 4 * upper.stiffness(dd)
    # Eq 6.2.67: Vb = kDmax·DD; Eq 6.2.66: Vs = Vb / RI (RI = 2.0 in X, 1.875 in Y).
    assert out["forces"]["X"]["Vb_kN"] == pytest.approx(vb * dd / 1e3)
    assert out["forces"]["X"]["RI"] == 2.0 and out["forces"]["Y"]["RI"] == 1.875
    assert out["forces"]["X"]["VsFormula_kN"] == pytest.approx(vb * dd / 2.0 / 1e3)
    for axis in ("X", "Y"):
        f = out["forces"][axis]
        assert f["Vs_kN"] == pytest.approx(max(f["VsFormula_kN"], *f["minima_kN"].values()))
        assert f["minima_kN"]["activation"] == pytest.approx(1.5 * 4 * upper.fy / 1e3)
        # Eq 6.2.68 sums to Vs.
        assert sum(lv["F_kN"] for lv in f["levels"]) == pytest.approx(f["Vs_kN"])
    # Drift: Cd = RI, I = 1.0.
    assert out["drift"]["Cd"] == {"X": 2.0, "Y": 1.875}
    restoring = next(c for c in out["checks"] if c["id"] == "restoring")
    assert restoring["limit"] == pytest.approx(0.025 * 4000)
    assert out["total"]["DTD_mm"] == pytest.approx(1.05 * out["design"]["D_mm"])
    assert out["requirements"][0]["ok"] is True  # bounds entered
    test = out["testing"][0]
    assert test["steps"][0]["cycles"] == 20
    assert test["steps"][-1]["displacement_mm"] == pytest.approx(out["total"]["DTD_mm"])
    h = out["history"]
    assert h["periodRange"] == pytest.approx([0.5 * out["design"]["T"], 1.25 * out["maximum"]["T"]])


def test_static_analysis_not_permitted_above_four_storeys() -> None:
    out = _design(SeismicIsolator(), storeys=5)
    cond = {c["id"]: c["ok"] for c in out["staticAnalysis"]["conditions"]}
    assert cond["2"] is False and not out["staticAnalysis"]["permitted"]
    out = _design(SeismicIsolator(), site_class="SE")
    cond = {c["id"]: c["ok"] for c in out["staticAnalysis"]["conditions"]}
    assert cond["1"] is True


def test_history_suite_check() -> None:
    out = _design(SeismicIsolator())
    low, high = out["history"]["periodRange"]
    periods = [low, (low + high) / 2, high]
    target = [1.3 * iso.spectral_acceleration(t, "SD", 0.20) for t in periods]
    ok = iso.check_history_suite(periods, [0.95 * v for v in target], out, "SD", 0.20)
    assert ok["ok"] and ok["required"] == pytest.approx(0.9)
    low_suite = iso.check_history_suite(periods, [0.85 * v for v in target], out, "SD", 0.20)
    assert not low_suite["ok"]


# ─────────────────────────────── the analysis model ───────────────────────────────


MATERIALS = default_material_library()
OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "COL",
                "name": "Column 400x400 on isolators",
                "kind": "column",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                "isolator": {"lowerBoundFactor": 0.85, "upperBoundFactor": 1.2},
            },
            {
                "id": "BM",
                "name": "Beam 300x500",
                "kind": "beam",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            },
            {"id": "SL", "name": "Slab 150", "kind": "slab", "material": "C24.1", "thickness": 150},
        ]
    }
)
CORNERS = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]


def _bay():
    plan = FloorPlan.model_validate(
        {
            **default_floor_plan().model_dump(mode="json", by_alias=True),
            "columns": [
                {
                    "id": f"C{i + 1}",
                    "type": "COL",
                    "at": {"x": x, "y": y},
                    "base": "BASE",
                    "top": "L1",
                }
                for i, (x, y) in enumerate(CORNERS)
            ],
            "beams": [
                {
                    "id": f"B{i + 1}",
                    "type": "BM",
                    "story": "L1",
                    "start": {"x": a[0], "y": a[1]},
                    "end": {"x": b[0], "y": b[1]},
                }
                for i, (a, b) in enumerate(zip(CORNERS, CORNERS[1:] + CORNERS[:1], strict=True))
            ],
            "slabs": [
                {
                    "id": "S1",
                    "type": "SL",
                    "story": "L1",
                    "boundary": [{"x": x, "y": y} for x, y in CORNERS],
                }
            ],
        }
    )
    return generate(plan, "s")


def test_derived_model_has_the_isolators_and_the_isolated_forces() -> None:
    building = _bay()
    d = derive_fem(building, OBJECTS, MATERIALS, default_project_settings("Isolated"))
    assert d.isolation is not None and d.isolation["schema"] == iso.SCHEMA
    springs = [e for e in d.project["elements"] if e["name"].endswith(iso.ELEMENT_SUFFIX)]
    assert len(springs) == 4 and all(e["type"] == "ZeroLength" for e in springs)
    # The base nodes are free to translate on the springs, the ground nodes fixed.
    nodes = {n["id"]: n for n in d.project["nodes"]}
    for e in springs:
        ground, top = e["nodes"]
        assert all(nodes[ground]["restraint"])
        assert nodes[top]["restraint"][:3] == [False, False, False]
    # EX is re-distributed to Vs (Eq 6.2.68).
    ex = next(p for p in d.project["load_patterns"] if p["name"] == "EX")
    total = sum(load["forces"][0] for load in ex["nodal_loads"])
    assert total / 1e3 == pytest.approx(d.isolation["forces"]["X"]["Vs_kN"], rel=1e-6)
    assert "isolation" in d.summary


def test_no_isolator_no_change() -> None:
    plain = ObjectLibrary.model_validate(
        {
            "objects": [
                {**o.model_dump(mode="json", by_alias=True), "isolator": None}
                if o.kind == "column"
                else o.model_dump(mode="json", by_alias=True)
                for o in OBJECTS.objects
            ]
        }
    )
    d = derive_fem(_bay(), plain, MATERIALS, default_project_settings("Fixed"))
    assert d.isolation is None
    assert not any(e["name"].endswith(iso.ELEMENT_SUFFIX) for e in d.project["elements"])
