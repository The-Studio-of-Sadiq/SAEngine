"""Alpha 9 P2: creep and shrinkage models chosen by the code pack, the age-adjusted analysis,
walls and cores, pre-sets, and the creep and shrinkage forces case CS (saengine.fem.staged,
saengine.fem.concrete_time).

The hand values below re-derive each model from its printed equations (ACI 209R-92 Eqs 2-8,
2-10 with the Sec 2.5 factors; EN 1992-1-1 Annex B Eqs B.1-B.8 and Eqs 3.8-3.13)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import context, registry
from saengine.fem import concrete_time as ct
from saengine.fem import staged
from saengine.library.settings import TimeDependent


def _pack(pack_id: str):
    return context.using(registry.active({"codePack": pack_id}))


# ───────────────────────────── the models by hand ─────────────────────────────


def _aci_phi(h0: float, rh: float, t0: float, days: float) -> float:
    """ACI 209R-92 Eq 2-8 with Eqs 2-11 (moist cured), 2-14, 2-21 (V/S = h0 / 2)."""
    gamma = (
        1.25
        * t0**-0.118
        * (1.27 - 0.67 * rh / 100)
        * (2 / 3)
        * (1 + 1.13 * math.exp(-0.0213 * h0 / 2))
    )
    return days**0.6 / (10 + days**0.6) * 2.35 * gamma


def _aci_shrinkage(h0: float, rh: float, drying: float) -> float:
    """ACI 209R-92 Eq 2-10 (7 days moist curing), Eqs 2-15, 2-22."""
    gamma = (1.40 - 1.02 * rh / 100) * 1.2 * math.exp(-0.00472 * h0 / 2)
    return drying / (35 + drying) * 780e-6 * gamma


def test_aci209_creep_and_shrinkage_by_hand() -> None:
    with _pack("aci318-asce7-22"):
        assert ct.creep_method() == "aci209" and ct.creep_basis() == ("loading", 1.0)
        for t0, days in ((7, 30), (28, 365), (90, 10000)):
            assert ct.creep_phi(200, 50, t0, days) == pytest.approx(
                _aci_phi(200, 50, t0, days), rel=1e-3
            )
        assert ct.free_shrinkage(200, 50, 7 + 10950, 7) == pytest.approx(
            _aci_shrinkage(200, 50, 10950), rel=1e-6
        )
        # Above 80 % RH the other humidity band: 3.0 - 3.0 h (ACI 209R-92 Eq 2-15).
        assert ct.free_shrinkage(200, 90, 10957, 7) / ct.free_shrinkage(
            200, 70, 10957, 7
        ) == pytest.approx((3.0 - 2.7) / (1.40 - 1.02 * 0.7))


def test_en1992_annex_b_by_hand() -> None:
    fck, h0, rh, t0, days = 30.0, 200.0, 50.0, 28.0, 10000.0
    fcm = fck + 8
    a1, a2, a3 = (35 / fcm) ** 0.7, (35 / fcm) ** 0.2, (35 / fcm) ** 0.5
    phi_rh = (1 + (1 - rh / 100) / (0.1 * h0 ** (1 / 3)) * a1) * a2  # Eq B.3b
    beta_h = min(1.5 * (1 + (0.012 * rh) ** 18) * h0 + 250 * a3, 1500 * a3)  # Eq B.8b
    phi = phi_rh * 16.8 / math.sqrt(fcm) / (0.1 + t0**0.2) * (days / (beta_h + days)) ** 0.3
    eps_cd0 = 0.85 * (220 + 110 * 4) * math.exp(-0.12 * fcm / 10) * 1e-6 * 1.55 * (1 - 0.5**3)
    kh = 0.85  # Table 3.3, h0 = 200
    eps_cd = days / (days + 0.04 * h0**1.5) * kh * eps_cd0  # Eq 3.10
    eps_ca = (1 - math.exp(-0.2 * math.sqrt(days + 7))) * 2.5 * (fck - 10) * 1e-6  # Eqs 3.12-3.13
    with _pack("eurocodes"):
        assert ct.creep_basis() == ("28", 1.05)
        assert ct.creep_phi(h0, rh, t0, days, fck) == pytest.approx(phi, rel=1e-9)
        assert ct.free_shrinkage(h0, rh, days + 7, 7, fck) == pytest.approx(
            eps_cd + eps_ca, rel=1e-9
        )
        assert ct.strength_share(7) == pytest.approx(math.exp(0.25 * (1 - math.sqrt(4))))
    # National Annex packs inherit the model.
    with _pack("eurocodes-uk"):
        assert ct.creep_method() == "en1992AnnexB"


def test_is456_coefficients_and_bnbc_unchanged() -> None:
    with _pack("is-codes"):
        assert ct.creep_coefficient(150, 60, 7) == pytest.approx(2.2)  # IS 456 6.2.5.1
        assert ct.creep_coefficient(600, 90, 28) == pytest.approx(1.6)
        assert ct.creep_coefficient(300, 50, 365) == pytest.approx(1.1)
        assert ct.free_shrinkage(300, 50, 10957, 7) == pytest.approx(300e-6)  # 6.2.4.1
        assert ct.analysis_method() == "ageAdjusted"
    with _pack("bnbc2020"):
        assert ct.analysis_method() == "superposition" and ct.ageing() == (0.8, False)
        assert ct.creep_phi(300, 45, 28, 10950) == pytest.approx(
            ct.creep_coefficient(300, 45, 28) * ct.creep_share(10950)
        )
        assert staged.model_of(TimeDependent()).legacy


# ───────────────────────────── one column in time ─────────────────────────────


def _column(n: float = 1.6e6) -> tuple[dict, dict]:
    project = {
        "nodes": [
            {"id": 1, "coords": [0.0, 0.0, 0.0], "restraint": [True] * 6},
            {"id": 2, "coords": [0.0, 0.0, 3.0]},
        ],
        "sections": [
            {"id": 1, "type": "ElasticSection", "E": 25e9, "A": 0.16, "Iy": 0.4**4 / 12}
            | {"Iz": 0.4**4 / 12, "G": 1e10, "J": 0.003}
        ],
        "elements": [
            {"id": 1, "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1, "name": "C1"}
        ],
        "analyses": [{"id": 1, "name": "D: Dead", "type": "Static"}],
    }
    row = np.zeros(12)
    row[0], row[6] = n, -n  # compression
    results = {"D": SimpleNamespace(element_forces={1: np.array([row])})}
    return project, results


LEVELS1 = [{"z": 0.0, "name": "Base"}, {"z": 3.0, "name": "L1"}]


def test_a_column_by_aci209_superposition_and_age_adjusted() -> None:
    project, results = _column()
    options = TimeDependent(
        enabled=True, method="superposition", steelRatio=0.0, relativeHumidity=50
    )
    with _pack("aci318-asce7-22"):
        found = staged.column_shortening(project, results, LEVELS1, options)
        assert found["available"] and found["model"]["analysis"] == "superposition"
        row = found["lines"][0]["rows"][-1]
        e_t = 25e9 * math.sqrt(7 / (4 + 0.85 * 7))  # Eq 2-1 and Ec ∝ √f'c
        elastic = 1.6e6 / 0.16 / e_t
        # Loaded at 7 days (one floor cycle), 30 years after completion.
        creep = elastic * _aci_phi(200, 50, 7, 10950)
        shrink = _aci_shrinkage(200, 50, 10950)
        assert row["elastic"] == pytest.approx(3 * elastic, rel=1e-6)
        assert row["creep"] == pytest.approx(3 * creep, rel=1e-3)
        assert row["shrinkage"] == pytest.approx(3 * shrink, rel=1e-3)
        # The history: one year after loading.
        history = found["history"]
        k = history["days"].index(7 + 365.0)
        expected = elastic * (1 + _aci_phi(200, 50, 7, 365)) + _aci_shrinkage(200, 50, 365)
        assert history["lines"][0]["values"][k] == pytest.approx(3 * expected, rel=1e-3)

        # The age-adjusted effective modulus: the steel restrains the creep and shrinkage.
        es = float(context.current().table("materials").steelE) * 1e6
        rho = 0.02
        aaem = staged.column_shortening(
            project,
            results,
            LEVELS1,
            options.model_copy(update={"method": "ageAdjusted", "steelRatio": rho}),
        )
        row = aaem["lines"][0]["rows"][-1]
        ac, as_ = 0.16 * (1 - rho), 0.16 * rho
        initial = 1.6e6 / (ac * e_t + as_ * es)
        phi = _aci_phi(200, 50, 7, 10950)
        e_bar = e_t / (1 + 0.8 * phi)
        restraint = ac * e_bar / (ac * e_bar + as_ * es)
        assert row["elastic"] == pytest.approx(3 * initial, rel=1e-6)
        assert row["creep"] == pytest.approx(3 * initial * phi * restraint, rel=1e-3)
        assert row["shrinkage"] == pytest.approx(3 * shrink * restraint, rel=2e-3)


def test_final_time_and_casting_days() -> None:
    project, results = _column()
    options = TimeDependent(enabled=True, finalDays=10000, castDays=[{"level": "L1", "day": 20}])
    with _pack("eurocodes"):
        found = staged.column_shortening(project, results, LEVELS1, options)
    assert found["times"]["complete"] == pytest.approx(27.0)  # cast on day 20, loaded a cycle on
    assert found["times"]["end"] == pytest.approx(10000.0)
    assert found["model"]["analysis"] == "ageAdjusted" and found["model"]["chi"] == 0.8


# ───────────────────────────── a 10-storey frame with a core ─────────────────────────────

STOREYS, HEIGHT = 10, 3.0


def _frame_and_core() -> tuple[dict, dict, list[dict]]:
    """A column line at x = 8 m and a 2 m core wall at x = 0-2 m (two shells per storey),
    joined by a beam per level; the column carries 1.2 MN per storey, the wall 1.5 MN."""
    nodes, elements = [], []
    nid = iter(range(1, 10_000))
    col, wall = {}, {}
    for k in range(STOREYS + 1):
        z = k * HEIGHT
        col[k] = next(nid)
        nodes.append({"id": col[k], "coords": [8.0, 0.0, z]})
        for x in (0.0, 1.0, 2.0):
            wall[k, x] = next(nid)
            nodes.append({"id": wall[k, x], "coords": [x, 0.0, z]})
    for n in nodes:
        if n["coords"][2] == 0.0:
            n["restraint"] = [True] * 6
    forces: dict[int, np.ndarray] = {}
    eid = iter(range(1, 10_000))
    for k in range(1, STOREYS + 1):
        above = STOREYS - k + 1
        c = next(eid)
        elements.append(
            {"id": c, "type": "ElasticBeamColumn", "nodes": [col[k - 1], col[k]]}
            | {"section_id": 1, "name": f"C1#{k}"}
        )
        row = np.zeros(12)
        row[0], row[6] = 1.2e6 * above, -1.2e6 * above
        forces[c] = np.array([row])
        for x0, x1 in ((0.0, 1.0), (1.0, 2.0)):
            s = next(eid)
            quad = [wall[k - 1, x0], wall[k - 1, x1], wall[k, x1], wall[k, x0]]
            elements.append({"id": s, "type": "Shell", "nodes": quad, "section_id": 2})
            elements[-1]["name"] = f"W1#{k}{x0:g}"
            share = 1.5e6 * above / 4  # per bottom node (+) and top node (-)
            nodal = np.zeros((4, 6))
            nodal[:2, 2], nodal[2:, 2] = share, -share
            forces[s] = np.array([nodal.ravel()])
        b = next(eid)
        elements.append(
            {"id": b, "type": "ElasticBeamColumn", "nodes": [wall[k, 2.0], col[k]]}
            | {"section_id": 3, "name": f"B{k}"}
        )
        forces[b] = np.array([np.zeros(12)])
    project = {
        "nodes": nodes,
        "elements": elements,
        "sections": [
            {"id": 1, "type": "ElasticSection", "E": 30e9, "A": 0.36, "Iy": 0.6**4 / 12}
            | {"Iz": 0.6**4 / 12, "G": 1.2e10, "J": 0.01},
            {"id": 2, "type": "ElasticMembranePlateSection", "E": 30e9, "nu": 0.2, "h": 0.4},
            {"id": 3, "type": "ElasticSection", "E": 30e9, "A": 0.18, "Iy": 0.3 * 0.6**3 / 12}
            | {"Iz": 0.6 * 0.3**3 / 12, "G": 1.2e10, "J": 0.005},
        ],
        "analyses": [{"id": 1, "name": "D: Dead", "type": "Static"}],
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": [],
    }
    levels = [{"z": 0.0, "name": "Base"}] + [
        {"z": k * HEIGHT, "name": f"L{k}"} for k in range(1, STOREYS + 1)
    ]
    return project, {"D": SimpleNamespace(element_forces=forces)}, levels


@pytest.mark.parametrize("pack", ["bnbc2020", "eurocodes"])
def test_ten_storey_frame_and_core_differential_shortening(pack: str) -> None:
    project, results, levels = _frame_and_core()
    options = TimeDependent(enabled=True, walls=True, steelRatio=0.01, wallSteelRatio=0.005)
    with _pack(pack):
        found = staged.column_shortening(project, results, levels, options)
    assert found["available"]
    kinds = {line["line"]: line["kind"] for line in found["lines"]}
    assert kinds == {"C1": "column", "W1": "wall"}
    by = {line["line"]: line for line in found["lines"]}
    # The wall's storey forces come from its shells' nodal forces.
    wall_top = by["W1"]["rows"][-1]
    column_top = by["C1"]["rows"][-1]
    assert len(by["W1"]["rows"]) == STOREYS and len(by["C1"]["rows"]) == STOREYS
    # The column (1.2 MN a storey over 0.36 m²: 33 MPa at the base) shortens more than the
    # wall (1.5 MN a storey over 0.8 m²: 19 MPa); the dead load arrives at completion, so the
    # shortening after casting grows up the building.
    assert column_top["total"] > wall_top["total"] > 0
    after = [r["afterCasting"] for r in by["C1"]["rows"]]
    assert after[-1] > after[0] > 0
    # The beams between the column and the wall: their differential shortening.
    beams = {r["beam"]: r for r in found["differential"]}
    assert len(beams) == STOREYS
    level = max(beams.values(), key=lambda r: r["difference"])
    k = int(level["level"][1:]) - 1
    assert level["difference"] == pytest.approx(
        by["C1"]["rows"][k]["afterCasting"] - by["W1"]["rows"][k]["afterCasting"]
    )
    assert level["moment"] == pytest.approx(
        6 * 30e9 * 0.3 * 0.6**3 / 12 * level["difference"] / 6.0**2
    )
    pair = found["pairs"][0]
    assert {pair["a"], pair["b"]} == {"C1", "W1"} and pair["distance"] == pytest.approx(6.0)
    assert pair["difference"] == pytest.approx(level["difference"])
    camber = {(r["line"], r["level"]): r for r in found["camber"]}
    assert camber["W1", "L10"]["relative"] == pytest.approx(0.0)
    assert camber["C1", "L10"]["preset"] == pytest.approx(after[-1])
    assert camber["C1", "L10"]["storey"] == pytest.approx(after[-1] - after[-2])


def test_forces_case_loads_are_self_equilibrated() -> None:
    project, results, levels = _frame_and_core()
    options = TimeDependent(enabled=True, walls=True, forcesCase=True)
    with _pack("eurocodes"):
        corrections, notes = staged.add_creep_shrinkage_case(project, results, levels, options)
    assert corrections is not None and corrections["case"] == "CS"
    assert 0 < corrections["relaxation"] < 1
    assert len(corrections["frames"]) == STOREYS and len(corrections["shells"]) == 2 * STOREYS
    analysis = project["analyses"][-1]
    assert analysis["name"].startswith("CS: ") and analysis["type"] == "Static"
    pattern = next(p for p in project["load_patterns"] if p["name"] == "CS")
    total = np.sum([load["forces"] for load in pattern["nodal_loads"]], axis=0)
    assert np.allclose(total[:3], 0.0, atol=1e-3)  # imposed strains: no net force
    # A held column pulls its ends together: tension N0 = E A ε r in the add-back.
    f0 = np.asarray(next(iter(corrections["frames"].values())))
    assert f0[0] < 0 and f0[6] == pytest.approx(-f0[0])
    # The held wall: a vertical tension N22 or N11 (along the wall's vertical local axis).
    held = np.asarray(next(iter(corrections["shells"].values())))
    assert max(held[0], held[1]) > 0 and any("relaxed" in n for n in notes)


def test_combinations_with_cs_and_add_backs() -> None:
    from saengine.fem.combinations import combination_factors
    from saengine.fem.thermal import end_force_corrections, shell_force_corrections
    from saengine.library.settings import strength_combinations

    with _pack("bnbc2020"):
        plain = strength_combinations()
        rows = strength_combinations(creep_shrinkage=True)
    assert all(not c.CS for c in plain)
    with_cs = [c for c in rows if c.CS]
    assert [c.name for c in with_cs] == ["1.2D + 1.2CS + 1.6L + 0.5Lr"]
    assert combination_factors(with_cs[0])["CS"] == 1.2
    assert "CS" not in with_cs[0].model_copy(update={"CS": 0}).model_dump()  # left out at 0
    with _pack("aci318-asce7-22"):
        assert [c.CS for c in strength_combinations(creep_shrinkage=True) if c.CS] == [1.0]
    side = {"schema": 1, "case": None, "frames": {}, "shells": {}}
    side["more"] = {"CS": {"frames": {"5": [1.0] * 12}, "shells": {"9": [2.0] * 8}}}
    assert list(end_force_corrections(side, "CS")) == [5]
    assert list(shell_force_corrections(side, "CS")) == [9]
    assert end_force_corrections(side, "T") == {}


# ───────────────────────────── a derived frame with the case CS, run ─────────────────────────────


def test_derived_frame_runs_the_forces_case(tmp_path) -> None:
    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library
    from saengine.library.bim import generate
    from tests.test_fem_derive import OBJECTS
    from tests.test_fem_staged import PLAN, settings

    s = settings(True)
    s.analysis.timeDependent.enabled = True
    s.analysis.timeDependent.forcesCase = True
    d = derive_fem(generate(PLAN, "s"), OBJECTS, default_material_library(), s, {"bim": "x"})
    cs = next(a for a in d.project["analyses"] if a["name"].startswith("CS: "))
    assert cs["type"] == "Staged" and d.thermal and "CS" in d.thermal["more"]
    model = tmp_path / "model.osmodel"
    model.write_text(json.dumps(d.project), encoding="utf-8")
    keep = [a["id"] for a in d.project["analyses"] if a["name"].split(":")[0] in ("D", "CS")]
    out = tmp_path / "model.results"
    done = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model), "--cases"]
        + [str(i) for i in keep]
        + ["--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    from opensees_studio.services.result_store import load_manifest, load_results

    results = {}
    for entry in load_manifest(out)["cases"]:
        results[entry["case_name"].split(":")[0]] = load_results(entry, out)
    reaction = sum(np.asarray(r[-1])[2] for r in results["CS"].node_reaction.values())
    assert abs(reaction) < 1.0  # self-equilibrated: the supports carry no net force
    found = staged.column_shortening(
        d.project,
        results,
        staged.levels_of(d.project, generate(PLAN, "s").stories),
        s.analysis.timeDependent,
        d.thermal,
    )
    induced = found["induced"]
    assert induced["beams"] and induced["beams"][0]["moment"] > 0
    # Inner and outer columns shorten differently: the case moves load between them.
    assert sum(abs(r["force"]) for r in induced["redistribution"]) > 0
