"""Alpha 9 P6: isolator kinds, property modification factors, the single-level isolation
procedure (ASCE 7-22 Chapter 17, EN 1998-1 Section 10 in their packs), the supplemental dampers
(ASCE 7-22 Chapter 18) and the devices of the nonlinear time history (saengine.fem.isolation,
isolation_single_level, dampers, device_response). Written in alpha 9; run in the test pass."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.fem import dampers as fd
from saengine.fem import isolation as iso
from saengine.fem import isolation_single_level as single
from saengine.fem import spectral_hazard as sh
from saengine.library import ObjectLibrary
from saengine.library.objects import (
    IsolatorPropertyModification,
    SeismicIsolator,
    SupplementalDamper,
)

G = 9.80665


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.clear_cache()
    yield
    registry.clear_cache()


def _pack(pack_id: str):
    return code_context.using(registry.load(pack_id))


def _units(spec: SeismicIsolator, a: float = 5.0) -> list[iso.Unit]:
    return [
        iso.Unit(f"C{k}", "COL", k + 1, x, y, spec)
        for k, (x, y) in enumerate([(-a, -a), (a, -a), (a, a), (-a, a)])
    ]


LEVELS = [(0.0, 1000e3), (3.0, 1500e3), (6.0, 1500e3)]


# ─────────────────────────────── the packs' values ───────────────────────────────


def test_asce7_chapter_17_values():
    with _pack("aci318-asce7-22"):
        t = code_context.table("isolation")
        # Sec 17.5: one MCER level, Vst = Vb (Ws/W)^(1 - 2.5 betaM), k = 14 betaM Tfb.
        assert t.procedure.method == "singleLevel"
        assert t.procedure.shearExponent == 2.5
        assert t.procedure.distribution == "dampingPeriod"
        assert t.procedure.distributionFactor == 14.0
        assert t.procedure.baseLevelForce is True
        assert t.spectrum.mceFactor == 1.5
        # Table 17.5-1.
        assert [(p.damping, p.B) for p in t.dampingCoefficients] == [
            (2.0, 0.8), (5.0, 1.0), (10.0, 1.2), (20.0, 1.5), (30.0, 1.7), (40.0, 1.9),
        ]  # fmt: skip
        # Sec 17.5.3.3: DTM at least 1.15 DM; Sec 17.2.4.4: the restoring force at DM.
        assert t.torsion.method == "periodRatio" and t.torsion.minimumFactor == 1.15
        assert t.restoring.at == "maximum" and t.restoring.forceShare == 0.025
        # Sec 17.2.8.4: 0.75 on the aging and environmental factors.
        assert t.propertyModification.aeShare == 0.75
        # Sec 17.4.1: at most 4 storeys and 19.8 m (65 ft), TM at most 3.0 s.
        assert (t.staticLimits.maxStoreys, t.staticLimits.maxHeight) == (4, 19.8)
        assert iso.damping_coefficient(15) == pytest.approx(1.35)
        assert iso.damping_coefficient(60) == pytest.approx(1.9)  # the last row beyond


def test_eurocode_section_10_values():
    with _pack("eurocodes"):
        t = code_context.table("isolation")
        # EN 1998-1 10.3(2): gamma_x = 1.2; 10.10(5): q at most 1.5.
        assert t.procedure.displacementFactor == 1.2
        assert iso.reduction_factor(4.0) == pytest.approx(1.5)
        assert iso.reduction_factor(1.2) == pytest.approx(1.2)
        # EN 1998-1 Eq 3.6: eta = sqrt(10 / (5 + xi)) >= 0.55, B = 1/eta.
        assert iso.damping_coefficient(5) == pytest.approx(1.0)
        assert iso.damping_coefficient(10) == pytest.approx(math.sqrt(1.5))
        assert iso.damping_coefficient(40) == pytest.approx(1 / 0.55)
        # Sec 10.9.4: a uniform acceleration above the interface.
        assert t.distribution.exponent == 0.0 and t.procedure.shearExponent == 0.0


def test_default_pack_keeps_its_two_level_procedure():
    t = code_context.table("isolation")
    assert t.procedure is None and t.dampingFormula is None and t.propertyModification is None
    assert not fd.covered()  # BNBC 2020 has no damping system procedure


# ─────────────────────────────── isolators ───────────────────────────────


def test_property_modification_factors_eq_17_2_1():
    lam = IsolatorPropertyModification(
        aeMax=1.2, aeMin=0.9, testMax=1.15, testMin=0.95, specMax=1.1, specMin=0.9
    )
    spec = SeismicIsolator(propertyModification=lam)
    with _pack("aci318-asce7-22"):
        lower, upper = iso.property_factors(spec)
        assert upper == pytest.approx((1 + 0.75 * 0.2) * 1.15 * 1.1)
        assert lower == pytest.approx((1 - 0.75 * 0.1) * 0.95 * 0.9)
    # A pack without the rule: the plain products.
    lower, upper = iso.property_factors(spec)
    assert upper == pytest.approx(1.2 * 1.15 * 1.1)
    assert lower == pytest.approx(0.9 * 0.95 * 0.9)
    # No λ factors: the bound factors as entered.
    plain = SeismicIsolator(lowerBoundFactor=0.85, upperBoundFactor=1.2)
    assert iso.property_factors(plain) == (0.85, 1.2)


def test_friction_pendulum_curve_from_mu_and_radius():
    spec = SeismicIsolator(
        kind="slidingPendulum", frictionCoefficient=0.06, radius=2500, yieldDisplacement=1
    )
    curve = iso.curve_of(spec, 1000e3)
    assert curve.qd == pytest.approx(0.06 * 1000e3)
    assert curve.kd == pytest.approx(1000e3 / 2.5)
    # A flat slider has no restoring stiffness; a type without μ keeps its entered curve.
    flat = SeismicIsolator(kind="flatSlider", frictionCoefficient=0.05, radius=None)
    assert iso.curve_of(flat, 1000e3).kd == 0.0
    assert iso.curve_of(SeismicIsolator(), 1000e3).qd == pytest.approx(60e3)


def test_dm_eq_17_5_1_in_the_constant_velocity_range():
    curves = [iso.Curve(60e3, 800e3, 0.015)] * 4
    sm1 = 0.9
    with _pack("aci318-asce7-22"):
        found = single._solve(curves, 4000e3, lambda t: sm1 / t)
        assert found["converged"]
        # DM = g SM1 TM / (4 pi^2 BM) when Sa = SM1 / T.
        assert found["D"] == pytest.approx(
            G * sm1 * found["T"] / (4 * math.pi**2 * found["B"]), rel=1e-4
        )


def test_vst_and_the_distribution_exponent():
    # Eq 17.5-7: Vst = Vb (Ws/W)^(1 - 2.5 betaM).
    assert single.shear_above(1000.0, 800.0, 1000.0, 0.2, 2.5) == pytest.approx(1000 * 0.8**0.5)
    assert single.shear_above(1000.0, 800.0, 1000.0, 0.2, 0.0) == pytest.approx(800.0)
    with _pack("aci318-asce7-22"):
        # Eq 17.5-11: k = 14 betaM Tfb.
        assert single.distribution_exponent(0.2, 0.5) == pytest.approx(1.4)
    forces = single.distribute_above([(0.0, 500.0), (3.0, 1000.0), (6.0, 1000.0)], 900.0, 1.0)
    assert forces == pytest.approx([0.0, 300.0, 600.0])


def test_period_ratio_torsion_eq_17_5_3():
    # Four equal units at (±a, ±a): b = d = 2a, PT = sqrt(2a²) / sqrt(8a²/12) = sqrt(3),
    # e = 0.05·2a; the corner (y = a) moves D (1 + a·12e / (3·8a²)) = 1.05 D.
    units = _units(SeismicIsolator())
    found = iso.period_ratio_displacements(units, (0.0, 0.0), 0.2, 0.05)
    assert found["X"]["PT"] == pytest.approx(math.sqrt(3))
    assert found["X"]["factor"] == pytest.approx(1.05)
    # At least 1.15 DM (Sec 17.5.3.3).
    floored = iso.period_ratio_displacements(units, (0.0, 0.0), 0.2, 0.05, 1.15)
    assert floored["Y"]["total"] == pytest.approx(1.15 * 0.2)


def test_small_isolated_frame_through_the_asce_elf_procedure():
    spec = SeismicIsolator(
        characteristicStrength=60, postYieldStiffness=800, yieldDisplacement=15,
        lowerBoundFactor=0.85, upperBoundFactor=1.3, displacementCapacity=900,
        verticalCapacity=3000,
    )  # fmt: skip
    hazard = sh.SpectralHazard(1.0, 0.6, 0.5, 8.0)  # SDS, SD1, S1, TL
    with _pack("aci318-asce7-22"):
        out = iso.design(
            _units(spec),
            LEVELS,
            (0.0, 0.0),
            site_class="SD",
            z=hazard,
            r={"X": 8.0, "Y": 5.0},
            fixed_period={"X": 0.4, "Y": 0.45},
            wind_shear={"X": 50e3, "Y": 40e3},
            storeys=2,
            accidental_share=0.05,
        )
        assert out["procedure"] == "singleLevel"
        low, up = out["bounds"]["lower"], out["bounds"]["upper"]
        # The displacement with the lower bound, larger than with the upper bound.
        assert low["D_mm"] > up["D_mm"]
        assert out["maximum"]["D_mm"] == pytest.approx(low["D_mm"])
        # In the 1/T range the MCER is SM1 / T = 1.5 SD1 / T.
        assert low["Sa"] * low["T"] == pytest.approx(1.5 * 0.6, rel=1e-3)
        assert low["D_mm"] / 1e3 == pytest.approx(
            G * low["Sa"] * low["T"] ** 2 / (4 * math.pi**2 * low["B"]), rel=1e-4
        )
        f = out["forces"]["X"]
        # Vb = kM DM of the governing bound; Vst; Vs = Vst / RI (RI = 2.0 for R = 8).
        vb = max(b["kMin_kNm"] * b["D_mm"] / 1e3 for b in (low, up))
        assert f["Vb_kN"] == pytest.approx(vb, rel=1e-6)
        beta = (up if up["kMin_kNm"] * up["D_mm"] >= low["kMin_kNm"] * low["D_mm"] else low)["beta"]
        assert f["Vst_kN"] == pytest.approx(vb * (3000 / 4000) ** (1 - 2.5 * beta), rel=1e-6)
        assert f["RI"] == 2.0
        assert f["VsFormula_kN"] == pytest.approx(f["Vst_kN"] / 2.0)
        assert f["Vs_kN"] == pytest.approx(max(f["VsFormula_kN"], *f["minima_kN"].values()))
        assert f["k"] == pytest.approx(14 * beta * 0.4)
        assert f["baseLevel_kN"] == pytest.approx((f["Vb_kN"] - f["Vst_kN"]) / 2.0)
        assert sum(lv["F_kN"] for lv in f["levels"]) == pytest.approx(f["Vs_kN"])
        assert all(lv["h"] > 0 for lv in f["levels"])
        # DTM at least 1.15 DM.
        assert out["total"]["DTM_mm"] >= 1.15 * out["maximum"]["D_mm"] - 1e-6
        ids = {c["id"] for c in out["checks"]}
        assert {"restoring", "restraint", "overturning", "stability"} <= ids
        statuses = {r["id"]: r["ok"] for r in out["requirements"]}
        assert statuses["17.2.4.4"] is next(
            c["ok"] for c in out["checks"] if c["id"] == "restoring"
        )
        assert statuses["17.2.4.1"] is True  # bounds entered
        # The time-history criteria over 0.75 TM to 1.25 TM, seven pairs.
        assert out["history"]["minRecords"] == 7
        assert out["history"]["periodRange"] == pytest.approx([0.75 * low["T"], 1.25 * low["T"]])


def test_nonlinear_bearings_replace_the_fixed_bases():
    history = {
        "nodes": [
            {"id": 1, "coords": [0.0, 0.0, 0.0], "mass": [0.0] * 6, "restraint": [True] * 6},
            {"id": 2, "coords": [0.0, 0.0, 3.0], "mass": [1e3] * 6, "restraint": [False] * 6},
        ],
        "materials": [],
        "sections": [],
        "elements": [],
    }
    summary = {
        "weight_kN": 1000.0,
        "units": [{"column": "C1", "type": "LRB", "node": 1, "x": 0.0, "y": 0.0}],
    }
    spec = SeismicIsolator()
    notes = iso.nonlinear_bearings(history, summary, {"LRB": spec})
    bearing = next(e for e in history["elements"] if e["name"] == "C1/isolator")
    assert bearing["type"] == "ElastomericBearingBoucWen"
    curve = iso.curve_of(spec)
    assert bearing["k_init"] == pytest.approx(curve.fy / curve.dy)
    assert bearing["qd"] == pytest.approx(curve.qd)
    assert history["nodes"][0]["restraint"][:3] == [False, False, False]
    assert notes
    pendulum = SeismicIsolator(kind="slidingPendulum", frictionCoefficient=0.05, radius=3000)
    history2 = {
        **history,
        "elements": [],
        "materials": [],
        "nodes": [dict(n) for n in history["nodes"]],
    }
    history2["nodes"][0]["restraint"] = [True] * 6
    iso.nonlinear_bearings(history2, summary, {"LRB": pendulum})
    fp = next(e for e in history2["elements"] if e["name"] == "C1/isolator")
    assert fp["type"] == "SingleFPBearing" and fp["r_eff"] == pytest.approx(3.0)
    assert history2["friction_models"][0]["mu"] == pytest.approx(0.05)


# ─────────────────────────────── dampers ───────────────────────────────


def test_damper_needs_its_values():
    with pytest.raises(ValueError):
        SupplementalDamper(kind="viscous")
    with pytest.raises(ValueError):
        SupplementalDamper(kind="metallic")
    SupplementalDamper(kind="viscoelastic", storageStiffness=1e4, lossStiffness=5e3)


def test_viscous_energy_lambda():
    assert fd.viscous_lambda(1.0) == pytest.approx(math.pi)
    alpha = 0.5
    assert fd.viscous_lambda(alpha) == pytest.approx(
        2 ** (2 + alpha) * math.gamma(1 + alpha / 2) ** 2 / math.gamma(2 + alpha)
    )


def _brace(spec: SupplementalDamper) -> fd.DamperBrace:
    # A diagonal over one 3 m storey and a 4 m bay: L = 5 m, cos = 0.8 along X.
    brace = fd.DamperBrace("D1", "BR", spec, np.array([0.0, 0.0, 0.0]), np.array([4.0, 0.0, 3.0]))
    brace.axial = 2e11 * 0.004 / 5.0
    brace.area = 0.004
    return brace


def test_added_damping_of_a_linear_viscous_brace():
    c = 500.0  # kN s/m
    brace = _brace(SupplementalDamper(kind="viscous", coefficient=c, exponent=1.0))
    weight = 2000e3
    mode = fd.modal_values([(0.0, 0.0), (3.0, weight)])
    period = 0.5
    beta = fd.added_damping([brace], "X", mode, 0.02, period)
    # beta = T sum(C cos² phi_r²) / (4 pi sum(m phi²)), phi = 1 at the roof.
    assert beta == pytest.approx(period * c * 1e3 * 0.8**2 / (4 * math.pi * weight / G))
    # Energy of a cycle: pi C omega delta².
    assert brace.energy(0.01, period) == pytest.approx(
        math.pi * c * 1e3 * (2 * math.pi / period) * 1e-4
    )
    assert brace.force(0.01, 0.2) == pytest.approx(c * 1e3 * 0.2)


def test_metallic_and_friction_loops():
    metallic = _brace(
        SupplementalDamper(
            kind="metallic", yieldForce=200, initialStiffness=1e5, postYieldRatio=0.0
        )
    )
    # 4 Fy (delta - dy), dy = Fy / k0 = 2 mm.
    assert metallic.energy(0.01, 1.0) == pytest.approx(4 * 200e3 * (0.01 - 0.002))
    assert metallic.force(0.001, 0.0) == pytest.approx(1e8 * 0.001)
    friction = _brace(SupplementalDamper(kind="friction", yieldForce=100))
    assert friction.force(0.05, 0.0) == pytest.approx(100e3)


def test_chapter_18_values_and_the_minimum_base_shear():
    with _pack("aci318-asce7-22"):
        t = code_context.table("dampers")
        assert t.method == "modalStrength" and t.minimumShare == 0.75
        assert t.residualPeriodShare == 0.4 and t.inherentMax == 3.0
        # Table 18.7-1.
        assert fd.damping_coefficient(30) == pytest.approx(1.8)
        assert fd.damping_coefficient(90) == pytest.approx(3.6)
        assert fd.damping_coefficient(100) == pytest.approx(3.6)
        brace = _brace(SupplementalDamper(kind="viscous", coefficient=20000, exponent=1.0))
        given = fd.Axis(shear=400e3, period=0.6, R=8.0, Cd=5.5, omega=3.0)
        found = fd.design_axis(
            [brace], "X", [(0.0, 0.0), (3.0, 2000e3)], given, 0.05, lambda t: min(1.0, 0.6 / t)
        )
        assert found["available"] and found["betaI"] == pytest.approx(0.03)
        assert found["betaV"] > 0
        # V not below 0.75 of the fixed-base base shear, nor V / B(V+I).
        assert found["Vdesign_kN"] >= 0.75 * 400 - 1e-6
        assert found["Vmin_kN"] == pytest.approx(max(400 / found["BVI"], 0.75 * 400))
        assert found["Vdesign_kN"] == pytest.approx(max(found["V_kN"], found["Vmin_kN"]))


def _damper_library() -> dict:
    lib = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "BR",
                    "name": "Damper brace",
                    "kind": "brace",
                    "material": "S275",
                    "profile": {"shape": "rectangle", "xDim": 100, "yDim": 100},
                    "damper": {"kind": "viscous", "coefficient": 800, "exponent": 0.5},
                }
            ]
        }
    )
    return {o.id: o for o in lib.objects}


def test_damper_brace_in_the_linear_and_nonlinear_models():
    member = SimpleNamespace(id="M1", type="BR", x1=0, y1=0, z1=0, x2=4000, y2=0, z2=3000)
    building = SimpleNamespace(additions=SimpleNamespace(members=[member]), elements=[])
    project = {
        "nodes": [
            {"id": 1, "coords": [0.0, 0.0, 0.0], "mass": [0.0] * 6, "restraint": [True] * 6},
            {"id": 2, "coords": [4.0, 0.0, 3.0], "mass": [1e3] * 6, "restraint": [False] * 6},
        ],
        "materials": [],
        "sections": [{"id": 1, "type": "ElasticSection", "E": 2e11, "A": 0.004}],
        "elements": [
            {"id": 1, "name": "M1", "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1}
        ],
    }
    braces, notes = fd.prepare_linear(project, building, _damper_library())
    assert len(braces) == 1 and notes
    brace = braces[0]
    assert brace.nodes == (1, 2)
    assert brace.axial == pytest.approx(2e11 * 0.004 / 5.0)
    own = next(s for s in project["sections"] if s["id"] == project["elements"][0]["section_id"])
    assert own["A"] == pytest.approx(0.004 * fd.STATIC_SHARE)  # a viscous damper: no stiffness
    history = {
        "nodes": project["nodes"],
        "materials": [],
        "sections": [dict(s) for s in project["sections"]],
        "elements": [dict(e) for e in project["elements"]],
    }
    fd.nonlinear_links(history, braces, 0.6)
    link = next(e for e in history["elements"] if e["name"] == "M1/damper")
    assert link["type"] == "TwoNodeLink" and link["nodes"] == [1, 2] and link["dofs"] == [1]
    material = next(m for m in history["materials"] if m["id"] == link["material_ids"][0])
    assert material["type"] == "ViscousDamper"
    assert material["Cd"] == pytest.approx(800e3) and material["alpha"] == 0.5
    assert material["K"] == pytest.approx(brace.axial)


def test_viscous_damper_material_of_the_solver():
    from opensees_studio.core.materials import ViscousDamper

    mat = ViscousDamper(id=1, K=1e8, Cd=1e5, alpha=0.5)
    assert mat.type == "ViscousDamper"
    with pytest.raises(ValueError):
        ViscousDamper(id=2, K=1e8, Cd=1e5, alpha=0.0)


def test_device_suite_design_values():
    from saengine.fem import device_response as dr

    row = {"kind": "damper", "name": "M1", "element": "TwoNodeLink", "u": [0.0], "F": [0.0]}
    per = [
        [{**row, "displacement": 0.02, "force": 100e3, "velocity": 0.3, "energy": 5e3}],
        [{**row, "displacement": 0.04, "force": 120e3, "velocity": 0.5, "energy": 9e3}],
    ]
    found = dr.suite_devices(per, ["NTH: a", "NTH: b"], "max")
    assert found["rows"][0]["displacement_mm"] == pytest.approx(40.0)
    assert found["rows"][0]["record"] == "NTH: b"
    mean = dr.suite_devices(per, ["NTH: a", "NTH: b"], "mean")
    assert mean["rows"][0]["force_kN"] == pytest.approx(110.0)
    assert found["loops"] and found["loops"][0]["name"] == "M1"
