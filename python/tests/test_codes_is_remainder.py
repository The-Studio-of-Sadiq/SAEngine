"""Indian Standards pack, the remainder (alpha 9 track C9b): the checks that fell back to BNBC
2020 under C7, C8 and C9, pinned with their clauses (worked by hand from the values of the
pack's VERIFY.md), the default pack unchanged, and a small generated building designed under
the pack.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library.objects import RectangleProfile

PACK = "is-codes"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def is_pack():
    pack = registry.load(PACK)
    with code_context.using(pack):
        yield pack


def _column(b=400.0, h=400.0, fc=25.0, fy=415.0, dia=16.0, cover=40.0):
    """Eight bars: three a face, the corners shared."""
    from saengine.design.rc import Bar, RcSection, bar_area

    x, y = b / 2 - cover - dia / 2, h / 2 - cover - dia / 2
    spots = [(-x, -y), (0, -y), (x, -y), (-x, 0), (x, 0), (-x, y), (0, y), (x, y)]
    bars = tuple(Bar(px, py, bar_area(dia), dia) for px, py in spots)
    return RcSection(RectangleProfile(xDim=b, yDim=h), bars, fc, fy)


def test_pack_validates_and_the_default_pack_keeps_its_methods():
    found = registry.validate(registry.BUILTIN_DIR / PACK)
    assert not [p for p in found.problems if p.severity == "error"], found.problems
    from saengine.design import corbels, deep_beams, tabulated_shear
    from saengine.fem import loads

    with code_context.using(registry.load("bnbc2020")):
        assert tabulated_shear.rules() is None
        assert deep_beams.lever_rules() is None and corbels.tie_rules() is None
        # The default pack's η = √(10 / (5 + 100 ξ)) is unchanged.
        assert code_context.table("seismic").dampingCorrection.method == "squareRoot"
        assert loads.damping_correction(0.02) == pytest.approx(math.sqrt(10 / 7))
        # Bolts of property class 4.6 are taken as A307 in the default pack.
        from saengine.design.steel_connections import grade_id

        assert grade_id("4.6") == "A307"


def test_column_shear_with_the_axial_factor(is_pack):
    # IS 456 40.2.2: δ = 1 + 3 Pu / (Ag fck) <= 1.5; net tension: the line down, not below 0.
    from saengine.design import tabulated_shear as ts
    from saengine.design.column_shear import shear_axes
    from saengine.library.objects import Transverse

    ag, fck = 400.0 * 400.0, 25.0
    assert ts.axial_factor(600e3, ag, fck) == pytest.approx(1.45)
    assert ts.axial_factor(1000e3, ag, fck) == pytest.approx(1.5)
    assert ts.axial_factor(-200e3, ag, fck) == pytest.approx(0.85)
    section = _column()
    ties = Transverse(type="tie", dia=8, spacing=150, legs=2)
    rows = ts.column_rows(section, ties, [(600e3, 0.0, 120e3, "C1", "base")])
    shear = next(r for r in rows if r["name"].startswith("Column shear along y"))
    assert "IS 456:2000 40.2.2" in shear["note"]
    part = next(p for p in shear_axes(section, ties) if p.axis == "y")
    far = 3 * math.pi * 16**2 / 4
    tc = ts.tau_c(fck, 100 * far / (part.bw * part.d))
    vus = 415 / 1.15 * part.av * part.d / 150
    assert shear["capacity"] == pytest.approx((1.45 * tc * part.bw * part.d + vus) / 1e3, abs=0.01)


def test_wall_axial_strength(is_pack):
    # IS 456 32.2.5: Puw = 0.3 (t - 1.2 e - 2 ea) fck Lw, e >= t/20, ea = Hwe²/(2500 t),
    # Hwe = 0.75 H (braced, restrained).
    from saengine.design import tabulated_shear as ts
    from saengine.design.walls import PierForces, WallGeometry

    geometry = WallGeometry(length=2000.0, thickness=200.0, height=3000.0, clear_height=3000.0)
    rows = ts.wall_axial_rows(geometry, [PierForces("C1", 1000e3, 0.0, 0.0)], 25.0, 0.8)
    slender, axial = rows
    assert slender["demand"] == pytest.approx(2250 / 200)
    ea = 2250**2 / (2500 * 200)
    puw = 0.3 * (200 - 1.2 * 10 - 2 * ea) * 25 * 2000
    assert axial["capacity"] == pytest.approx(puw / 1e3, abs=0.01)
    assert axial["flag"] and "32.2.5" in axial["name"]


def test_corner_torsion_steel(is_pack):
    # Annex D-1.8: 3/4 of the largest midspan steel each layer; D-1.9: half that.
    from saengine.design import panel_coefficients as pc
    from saengine.design import slab

    def side(continuous):
        return SimpleNamespace(continuous=continuous)

    panel = SimpleNamespace(
        lx=4000.0,
        ly=5000.0,
        sides={"x-": side(False), "x+": side(True), "y-": side(False), "y+": side(True)},
    )
    mesh = SimpleNamespace(dia=10.0, spacing=150.0)
    reinforcement = SimpleNamespace(cover=20.0, bottomX=mesh, bottomY=mesh, topX=mesh, topY=mesh)
    envelope = {"bottomX": (8000.0, "C1", ""), "bottomY": (5000.0, "C1", "")}
    rows = pc.corner_rows(panel, 150.0, reinforcement, 25.0, 415.0, 200000.0, envelope)
    need = pc._required_area(8000.0, 125.0, 25.0, 415.0, 200000.0)
    assert slab.layer_capacity(need, 125.0, 25.0, 415.0).phi_mn == pytest.approx(8e6, rel=1e-6)
    both = next(r for r in rows if "both edges" in r["name"])
    one = next(r for r in rows if "one edge" in r["name"])
    assert both["demand"] == pytest.approx(0.75 * need, abs=0.01)
    assert one["demand"] == pytest.approx(0.375 * need, abs=0.01)
    assert "x-/y-" in both["note"] and "x-/y+" in one["note"] and "x+/y-" in one["note"]
    assert "Annex D" in both["name"]


def test_deep_beam_lever_arm(is_pack):
    # IS 456 29.1-29.2: l/D < 2 (simple), z = 0.2 (l + 2 D) for 1 <= l/D <= 2, 0.6 l below 1.
    from saengine.design import deep_beams as db

    span = db.DeepSpan(
        clear=2400.0, depth=1500.0, width=300.0, d=1400.0, fc=25.0, fy=415.0,
        bearings=(400.0, 400.0), tie_area=2000.0, tie_height=120.0,
    )  # fmt: skip
    length = min(2400 + 400, 1.15 * 2400)
    assert db.lever_span(span) == pytest.approx(length)
    assert db.lever_is_deep(span, False)[0]
    assert db.lever_arm(span, False) == pytest.approx(0.2 * (length + 2 * 1500))
    assert db.lever_arm(span, True) == pytest.approx(0.2 * (length + 1.5 * 1500))
    short = db.DeepSpan(**{**span.__dict__, "depth": 3000.0, "d": 2900.0})
    assert db.lever_arm(short, False) == pytest.approx(0.6 * length)
    demands = db.SpanDemands(((500e3, "C1"), (500e3, "C1")), (600e6, "C1"), (500e3, "C1"))
    rows = db.lever_span_checks(span, demands, "", False)
    tie = rows[0]
    z = 0.2 * (length + 2 * 1500)
    assert tie["capacity"] == pytest.approx(415 / 1.15 * 2000 * z / 1e6, abs=0.01)
    zone = next(r for r in rows if "near the soffit" in r["name"])
    assert zone["capacity"] == pytest.approx(0.25 * 1500 - 0.05 * length, abs=0.01)


def test_corbel_root_tie(is_pack):
    # IS 456 28: Nuc >= 0.5 Vu, As = Af + An by the design strengths, links >= 0.5 As.
    from saengine.design import corbels
    from saengine.library.modifiers import Corbel, CorbelBars

    corbel = Corbel(
        width=400, depth=500, edgeDepth=300, projection=300, cover=40,
        mainBars=CorbelBars(count=4, dia=20), ties=CorbelBars(count=3, dia=10),
    )  # fmt: skip
    rows = corbels.corbel_checks(corbel, 25.0, 415.0, corbels.CorbelDemand(400e3, "C1"))
    by = {r["name"].split(": ", 1)[1]: r for r in rows}
    assert by["depth at the outer edge"]["demand"] == pytest.approx(250.0)
    d = 500 - 40 - 10
    nuc = 0.5 * 400e3
    mu = 400e3 * 150 + nuc * (500 - d)
    from saengine.design import design_strength

    p = design_strength.properties(25.0)
    block = p.eta * design_strength.fcd(25.0) * 400
    fyd = 415 / 1.15
    af = block * (d - math.sqrt(d * d - 2 * mu / block)) / fyd
    assert by["main bars As"]["demand"] == pytest.approx(af + nuc / fyd, abs=0.5)
    assert by["closed ties Ah"]["demand"] == pytest.approx(0.5 * 4 * math.pi * 100, abs=0.5)


def test_torsion_need_for_design_reinforcement(is_pack):
    # IS 456 41.4.3: Asv/sv = Tu/(b1 d1 fyd) + Vu/(2.5 d1 fyd); 26.5.1.7 spacing.
    from saengine.design import tabulated_shear as ts
    from saengine.design.rc import Bar, RcSection, bar_area

    bars = tuple(Bar(x, y, bar_area(16), 16) for x in (-100, 100) for y in (-202, 202))
    section = RcSection(RectangleProfile(xDim=300, yDim=500), bars, 25.0, 415.0)
    points = [(20e6, 80e3, 50e6, "C1", "end")]
    need = ts.torsion_need(section, 40.0, (8.0, 2, 150.0), points)
    fyd = 415 / 1.15
    b1, d1 = 300 - 80 - 8, 500 - 80 - 8
    expected = 20e6 / (b1 * d1 * fyd) + 80e3 / (2.5 * d1 * fyd)
    assert need.asv_s >= expected - 1e-9 and need.at_s == pytest.approx(need.asv_s / 2)
    assert need.s_max == pytest.approx(min(b1, (b1 + d1) / 4, 300))


def test_loads_damping_vertical_and_cyclonic_k4(is_pack):
    # IS 1893 (Part 1):2016 Table 4; 6.4.6 two-thirds; IS 875 (Part 3) 6.3.4 k4 1.30.
    from saengine.fem import loads, wind_speed_factors

    assert loads.damping_correction(0.02) == pytest.approx(1.4)
    assert loads.damping_correction(0.035) == pytest.approx(1.2)
    assert loads.damping_correction(0.05) == pytest.approx(1.0)
    assert code_context.table("seismic").verticalFactor == pytest.approx(0.667)
    assert wind_speed_factors.cyclonic_importance(1.07) == pytest.approx(1.3)
    assert wind_speed_factors.cyclonic_importance(1.0) == pytest.approx(1.0)
    # Not cyclonic by default: k4 1.0.
    assert wind_speed_factors.factors(10.0, 44.0, "2", 1.07)["k4"] == pytest.approx(1.0)


def test_steel_sections_bolts_and_base_plate(is_pack):
    from saengine.design.steel_connections import bearing_on_concrete
    from saengine.library.objects import ColumnBasePlate

    table = code_context.table("steelSections")
    assert {"ISLB", "ISWB", "ISHB"} <= set(table.families)
    ishb = {s.designation: s for s in table.rolled["ISHB"].sections}
    s = ishb[300]
    assert (s.h, s.b, s.tw, s.tf) == (300, 250, 7.6, 10.6)
    # The mass with the derived root radius is within 1 % of IS 808's 58.8 kg/m.
    area = 2 * s.b * s.tf + (s.h - 2 * s.tf) * s.tw + 4 * (1 - math.pi / 4) * s.r**2
    assert area * 7.85e-3 == pytest.approx(58.8, rel=0.01)
    # IS 800 7.4.1: 0.6 fck A1.
    plate = ColumnBasePlate(length=400, width=300, concreteStrength=25)
    assert bearing_on_concrete(plate) == pytest.approx(0.6 * 25 * 400 * 300)


def test_masonry_strengthening_by_is_zones(is_pack):
    from saengine.design import masonry_seismic

    assert masonry_seismic.zone_group(2) is None
    assert masonry_seismic.zone_group(4) == "zone23"
    assert masonry_seismic.zone_group(5) == "zone4"
    assert masonry_seismic.strengthening_row(5, 3).zones == [5]


def test_generated_building_is_designed_under_the_pack(tmp_path):
    import json
    from pathlib import Path

    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building
    from saengine.rpc import handlers

    spec = {
        "name": "IS Remainder",
        "gridsX": [5000, 5000],
        "gridsY": [4000],
        "storyCount": 1,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": PACK,
        "lateralSizing": "gravity",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    with code_context.project(root):
        proposal = handlers.design_proposal(
            str(root / "08 FEM/model.results"), str(root / "08 FEM/model.osmodel")
        )
    objects_path, bim_path = root / "04 Objects/objects.json", root / "06 BIM/bim.json"
    applied = handlers.design_apply_proposal(
        objects_path.read_text(encoding="utf-8"), bim_path.read_text(encoding="utf-8"), proposal
    )
    objects_path.write_text(applied["objectsText"], encoding="utf-8")
    bim_path.write_text(applied["bimText"], encoding="utf-8")
    result = run_all(root, steps=["derive", "analysis", "design"])
    assert result.steps[-1].status in ("ok", "warning"), [s.message for s in result.steps]
    report = json.loads(
        (root / "08 FEM/model.results/design-report.json").read_text(encoding="utf-8")
    )["result"]
    assert any(line.startswith("Column shear by τc × δ") for line in report["method"])
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert any(n.startswith("Column shear along x (") and "40" in n for n in names), sorted(names)
    assert not any(n.startswith("Column shear along x: minimum ties") for n in names)
    # Delhi (zone IV): the IS 13920 joints are listed for the joints view.
    assert report.get("joints"), "no joints in the report"
    assert all(j["checks"] for j in report["joints"])
