"""Part 9 Substructure: the model of substructure.json, and the shallow foundations (isolated,
combined and strip footings, tie beams) by hand, on synthetic loads and on an analysed frame;
the migration of the footings drawn in the building model, and the sizing assistant.

The footing cases by hand are those of the Part 8 footing design (tests/test_design_footing.py)
in their new home."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from test_fem_derive import OBJECTS, PLAN, SETTINGS

from saengine.fem.derive import derive_fem
from saengine.library import FloorPlan, ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel, FootingElement, generate
from saengine.library.objects import BarMesh
from saengine.library.settings import Foundation as FoundationSettings
from saengine.library.settings import ProjectSettings
from saengine.library.substructure import (
    SUBSTRUCTURE_FILE,
    Foundation,
    Substructure,
    check,
    is_placeholder,
    parse,
)
from saengine.substructure import migrate, propose, substructure_report
from saengine.substructure.context import Context, Skip, load_context
from saengine.substructure.loads import Base, BaseLoads, service_combinations
from saengine.substructure.report import report
from saengine.substructure.shallow import (
    ColumnBase,
    FootingSpec,
    SoilBearing,
    design_footing,
    design_shallow,
    design_tie_beam,
    one_way_shear_capacity,
    punching_stress,
    soil_pressure,
)

KN = 1e3
G = 9.80665


def by_name(checks: list[dict]) -> dict[str, dict]:
    return {c["name"]: c for c in checks}


# ─────────────────────────────────────── the model ───────────────────────────────────────

MESH = {"dia": 16, "spacing": 150}
REINFORCEMENT = {"material": "B420DWR", "cover": 75, "bottomX": MESH, "bottomY": MESH}


def footing(id: str, columns: list[str], **values: object) -> dict:
    return {
        "id": id,
        "type": "isolated",
        "columns": columns,
        "length": 1800,
        "width": 1800,
        "thickness": 500,
        "material": "C24.1",
        "reinforcement": REINFORCEMENT,
        **values,
    }


def test_substructure_file_round_trips_and_validates() -> None:
    data = {
        "schema": "saengine.substructure/1",
        "foundations": [
            footing("F1", ["C1"]),
            {
                "id": "P1",
                "type": "pileCap",
                "columns": ["C2"],
                "center": [6000, 0],
                "length": 2400,
                "width": 2400,
                "thickness": 900,
                "piles": ["PL1", "PL2", "PL3", "PL4"],
            },
            {
                "id": "S1",
                "type": "strip",
                "columns": ["W1"],
                "path": [[0, 0], [6000, 0]],
                "width": 1200,
                "thickness": 400,
            },
            {"id": "R1", "type": "raft", "outline": [[0, 0], [9, 0], [9, 9]], "thickness": 600},
        ],
        "pileTypes": [{"id": "BP500", "diameter": 500, "length": 18000, "material": "C24.1"}],
        "pileGrid": {
            "origin": [5250, -750],
            "rotation": 0,
            "x": [{"label": "a", "position": 0}, {"label": "b", "position": 1500}],
            "y": [{"label": "1", "position": 0}, {"label": "2", "position": 1500}],
        },
        "piles": [
            {"id": f"PL{k + 1}", "type": "BP500", "position": [6000 + dx, dy]}
            for k, (dx, dy) in enumerate([(-750, -750), (750, -750), (750, 750), (-750, 750)])
        ],
        "tieBeams": [{"id": "TB1", "from": "F1", "to": "P1", "type": "TB"}],
        "design": {"springsFrom": 12000, "factorOfSafety": {"pileCompression": 3}},
    }
    model = Substructure.model_validate(data)
    dumped = json.loads(model.model_dump_json(by_alias=True, exclude_none=True))
    assert dumped["tieBeams"][0]["from"] == "F1" and dumped["schema"] == data["schema"]
    assert Substructure.model_validate(dumped) == model
    # The piles in plan, as offsets in the cap's axes; the pile grid's crossings.
    cap = model.foundations[1]
    assert model.cap_pile_type(cap).id == "BP500"
    assert model.pile_offsets(cap) == [[-750, -750], [750, -750], [750, 750], [-750, 750]]
    assert [p[2] for p in model.pileGrid.intersections()] == [
        [5250, -750], [5250, 750], [6750, -750], [6750, 750]
    ]  # fmt: skip
    # Defaults from BNBC 2020 Table 6.3.10a (permanent, normal control) and Sec 3.10.1.18.
    fs = Substructure().design.factorOfSafety
    assert (fs.pileCompression, fs.pileUplift, fs.pileSkin, fs.pileEndBearing) == (2.5, 2.5, 1.5, 3)
    assert model.design.springsFrom == 12000 and Substructure().design.springsFrom == "soilReport"
    # The founding level defaults to 1.5 m below the finished ground.
    assert model.foundations[0].founding_level(200.0) == -1300.0
    assert (
        Foundation.model_validate(footing("F", ["C"], foundingLevel=-2000)).founding_level(0)
        == -2000
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["foundations"].append(footing("F1", ["C9"])), "duplicate foundations ids: F1"),
        (
            lambda d: d["foundations"].append(footing("F2", ["C1"])),
            "C1 is carried by both F1 and F2",
        ),
        (lambda d: d["foundations"][0].pop("width"), "F1: a isolated footing needs width"),
        (lambda d: d["foundations"][0].update(columns=[]), "needs center (or columns)"),
        (lambda d: d["foundations"][0].update(length=-5), "greater than 0"),
        (lambda d: d["tieBeams"][0].update(to="F7"), "TB1: unknown foundation 'F7'"),
        (lambda d: d["tieBeams"][0].update(to="F1"), "TB1: ties F1 to itself"),
        (lambda d: d["piles"][0].update(type="X"), "PL1: unknown pile type 'X'"),
        (lambda d: d["foundations"][1].update(piles=["PL1", "PL9"]), "P1: unknown pile 'PL9'"),
        (lambda d: d["foundations"][1].update(piles=["PL1", "PL1"]), "P1: PL1 listed twice"),
        (lambda d: d["foundations"][1].pop("piles"), "P1: a pile cap needs piles"),
        (lambda d: d["foundations"][1].pop("center"), "P1: a pile cap needs center"),
        (lambda d: d["foundations"][0].update(piles=["PL1"]), "F1: only a pile cap stands on"),
        (
            lambda d: d["foundations"].append({**d["foundations"][1], "id": "P2", "columns": []}),
            "pile PL1 is under both P1 and P2",
        ),
        (
            lambda d: (
                d["pileTypes"].append({**d["pileTypes"][0], "id": "BP600"}),
                d["piles"][1].update(type="BP600"),
            ),
            "P1: its piles are of more than one type (BP500, BP600)",
        ),
        (lambda d: d["pileGrid"]["y"].append({"label": "a", "position": 9}), "a used twice"),
    ],
)
def test_substructure_validation(change, message: str) -> None:
    data = {
        "foundations": [
            footing("F1", ["C1"]),
            {
                "id": "P1",
                "type": "pileCap",
                "columns": ["C2"],
                "center": [6000, 0],
                "length": 1800,
                "width": 1800,
                "thickness": 900,
                "piles": ["PL1", "PL2"],
            },
        ],
        "pileTypes": [{"id": "BP500", "diameter": 500, "length": 18000, "material": "C24.1"}],
        "pileGrid": {"x": [{"label": "a", "position": 0}], "y": []},
        "piles": [
            {"id": "PL1", "type": "BP500", "position": [5400, 0]},
            {"id": "PL2", "type": "BP500", "position": [6600, 0]},
        ],
        "tieBeams": [{"id": "TB1", "from": "F1", "to": "P1", "type": "TB"}],
    }
    Substructure.model_validate(data)
    change(data)
    with pytest.raises(ValidationError, match=re_escape(message)):
        Substructure.model_validate(data)


def re_escape(text: str) -> str:
    import re

    return re.escape(text)


def test_placeholder_and_references_into_the_other_parts() -> None:
    assert is_placeholder({"schema": 1, "part": "substructure"})
    assert parse('{"schema": 1, "part": "substructure"}') == Substructure()
    assert parse(None) == Substructure() and parse("  ") == Substructure()
    building = generate(PLAN, "s")
    model = Substructure.model_validate(
        {
            "foundations": [
                footing("F1", ["C1", "B1"], material="B420DWR"),
                footing("F2", ["C9"], reinforcement={**REINFORCEMENT, "material": "C24.1"}),
            ],
            "tieBeams": [{"id": "TB1", "from": "F1", "to": "F2", "type": "COL"}],
        }
    )
    assert check(model, building, default_material_library(), OBJECTS) == [
        "F1: 'B1' is not a column or wall of 6 BIM",
        "F2: 'C9' is not a column or wall of 6 BIM",
        "F1: material 'B420DWR' is not concrete",
        "F2: reinforcement material 'C24.1' is not rebar",
        "TB1: object type 'COL' is not a beam",
    ]


# ─────────────────────────────────────── soil pressure ───────────────────────────────────────


def test_bearing_pressure_inside_the_kern_by_hand() -> None:
    # 1000 kN on 2.0 x 1.5 m, 200 mm off centre along the length: q = P/A (1 ± 6e/L).
    p = soil_pressure(1000 * KN, 200, 0, 2000, 1500)
    mean = 1000 * KN / (2000 * 1500)
    assert p.state == "kern" and p.contact == 1
    assert p.qmax == pytest.approx(mean * 1.6) and p.qmin == pytest.approx(mean * 0.4)
    assert p.over(-1000, 1000, -750, 750) == pytest.approx(1000 * KN)
    q = soil_pressure(1000 * KN, 100, 75, 2000, 1500)
    assert q.qmax == pytest.approx(mean * (1 + 0.3 + 0.3))


def test_bearing_pressure_in_partial_contact_by_hand() -> None:
    # e = 500 mm > L/6: triangular pressure over 3 (L/2 - e) = 1500 mm.
    p = soil_pressure(1000 * KN, 500, 0, 2000, 1500)
    qmax = 2 * 1000 * KN / (3 * 1500 * (1000 - 500))
    assert p.state == "partial" and p.qmax == pytest.approx(qmax)
    assert p.contact == pytest.approx(0.75)
    force, first_u, _ = p.integrals(-1000, 1000, -750, 750)
    assert force == pytest.approx(1000 * KN) and first_u / force == pytest.approx(500)
    assert soil_pressure(1000 * KN, 1000, 0, 2000, 1500).state == "unstable"
    assert soil_pressure(-1.0, 0, 0, 2000, 1500).state == "uplift"


@pytest.mark.parametrize(
    ("eu", "ev", "length", "width"),
    [(300, 200, 2000, 1500), (-227, -107, 1800, 1800), (600, 400, 2000, 1500)],
)
def test_biaxial_partial_contact_is_in_equilibrium(eu, ev, length, width) -> None:
    p = soil_pressure(1000 * KN, eu, ev, length, width)
    n = 400
    u = (np.arange(n) + 0.5) / n * length - length / 2
    v = (np.arange(n) + 0.5) / n * width - width / 2
    uu, vv = np.meshgrid(u, v, indexing="ij")
    q = np.maximum(p.a + p.gu * uu + p.gv * vv, 0.0) * (length / n) * (width / n)
    total = float(q.sum())
    assert total == pytest.approx(1000 * KN, rel=2e-3)
    assert float((q * uu).sum()) / total == pytest.approx(eu, abs=0.002 * length)
    assert float((q * vv).sum()) / total == pytest.approx(ev, abs=0.002 * length)


# ─────────────────────────────── one footing, loads by hand ───────────────────────────────

T16 = BarMesh(dia=16, spacing=150)


def square_footing(**changes: object) -> FootingSpec:
    """1.8 x 1.8 x 0.5 m, cover 75, T16 at 150 both ways, f'c 25, fy 420, a 400 x 400 column."""
    values: dict = {
        "id": "F1",
        "type": "isolated",
        "footing_type": "isolated",
        "length": 1800,
        "width": 1800,
        "thickness": 500,
        "elevation": -1000,
        "cover": 75,
        "fc": 25,
        "fy": 420,
        "columns": [ColumnBase("C1", 0, 0, 400, 400, 1500)],
        "bottom_x": T16,
        "bottom_y": T16,
    }
    values.update(changes)
    return FootingSpec(**values)


def test_punching_one_way_shear_and_flexure_by_hand() -> None:
    spec = square_footing()
    pu = 1200 * KN
    checks, notes = design_footing(
        spec, {}, {"1.2D + 1.6L": [np.array([pu, 0.0, 0.0])]}, FoundationSettings()
    )
    checks = by_name(checks)
    d_x, d_y = 500 - 75 - 8, 500 - 75 - 16 - 8
    d = (d_x + d_y) / 2
    q = pu / 1800**2
    lambda_s = math.sqrt(2 / (1 + 0.004 * d))
    # Punching at d/2: Vu = Pu - q (c + d)², vc = 0.33 λs √f'c.
    b0 = 4 * (400 + d)
    vu = pu - q * (400 + d) ** 2
    phi_vc = 0.75 * 0.33 * lambda_s * 5
    assert punching_stress(400, 400, d, b0, 40, 25) == pytest.approx(0.33 * lambda_s * 5)
    assert checks["Punching at C1"]["demand"] == pytest.approx(vu / KN, rel=0.01)
    assert checks["Punching at C1"]["utilisation"] == pytest.approx(
        vu / (b0 * d) / phi_vc, rel=0.01
    )
    a_s = math.pi * 16**2 / 4 * 1000 / 150
    for label, d_layer in (("X", d_x), ("Y", d_y)):
        rho = a_s / (1000 * d_layer)
        lam = math.sqrt(2 / (1 + 0.004 * d_layer))
        vu1 = q * (900 - 200 - d_layer) * 1800
        phi_vc1 = 0.75 * 0.66 * lam * rho ** (1 / 3) * 5 * 1800 * d_layer
        assert one_way_shear_capacity(1800, d_layer, rho, 25) == pytest.approx(phi_vc1)
        assert checks[f"One-way shear {label}"]["demand"] == pytest.approx(vu1 / KN, rel=0.005)
        # Flexure at the column face: q B l² / 2 per metre width, l = 700 mm.
        a = a_s * 420 / (0.85 * 25 * 1000)
        flexure = checks[f"Flexure {label} (bottom)"]
        assert flexure["demand"] == pytest.approx(q * 1800 * 700**2 / 2 / 1.8 / 1e6, rel=0.01)
        assert flexure["capacity"] == pytest.approx(
            0.9 * a_s * 420 * (d_layer - a / 2) / 1e6, rel=5e-3
        )
    minimum = checks["Min. reinforcement X (bottom)"]
    assert (minimum["demand"], minimum["capacity"]) == pytest.approx((900, a_s), rel=1e-3)
    assert notes == ["F1: no service combination could be formed for the bearing check"]


def test_bearing_net_of_overburden_with_footing_weight_and_soil() -> None:
    spec = square_footing()
    foundation = FoundationSettings(allowableBearing=300, soilUnitWeight=18, groundLevel=0)
    service = {"D + L": [np.array([800 * KN, 0.0, 0.0])], "D": [np.array([600 * KN, 0.0, 0.0])]}
    checks, _ = design_footing(spec, service, {}, foundation)
    bearing = by_name(checks)["Bearing (service)"]
    area = 1.8 * 1.8
    weight = 2400 * G / 1e3 * area * 0.5 + 18 * area * 1.0
    assert bearing["combination"] == "D + L"
    assert bearing["demand"] == pytest.approx((800 + weight) / area - 18 * 1.5, rel=1e-3)
    # Beyond the kern: qmax = 2P / (3 B (L/2 - e)).
    moment = 800 * KN * 450
    checks, _ = design_footing(
        spec, {"D + 0.6WX": [np.array([800 * KN, 0.0, moment])]}, {}, foundation
    )
    total = 800 + weight
    e = 450 * 800 / total
    qmax = 2 * total / (3 * 1.8 * (0.9 - e / 1000))
    assert by_name(checks)["Bearing (service)"]["demand"] == pytest.approx(qmax - 27, rel=1e-3)
    # Without qa: no bearing check, and a note says what to enter.
    checks, notes = design_footing(spec, service, {}, FoundationSettings())
    assert "Bearing (service)" not in by_name(checks)
    assert any("enter the net allowable bearing pressure" in n for n in notes)


def test_combined_footing_resultant_and_hogging_between_columns_by_hand() -> None:
    columns = [ColumnBase("C1", -3000, 0, 400, 400), ColumnBase("C2", 3000, 0, 400, 400)]
    spec = square_footing(
        footing_type="combined", length=7800, thickness=600, columns=columns, top_x=T16, top_y=T16
    )
    pu = 900 * KN
    checks, _ = design_footing(
        spec, {}, {"1.4D": [np.array([pu, 0, 0]), np.array([pu, 0, 0])]}, FoundationSettings()
    )
    checks = by_name(checks)
    assert checks["Flexure between columns (top)"]["demand"] == pytest.approx(
        pu * (3000 - 7800 / 4) / 1.8 / 1e6, rel=0.01
    )
    d = 600 - 75 - 16
    d_y = 600 - 75 - 16 - 8
    transverse = checks["Flexure Y (bottom)"]
    assert transverse["demand"] == pytest.approx(pu / 1800 * 700**2 / 2 / (400 + d) / 1e3, rel=0.01)
    assert checks["One-way shear Y"]["demand"] == pytest.approx(
        pu / 1800 * (700 - d_y) / KN, rel=5e-3
    )
    # Unequal loads: the resultant of both columns about the centroid.
    service = {"D": [np.array([1000 * KN, 0, 0]), np.array([500 * KN, 0, 0])]}
    checks, _ = design_footing(
        spec, service, {}, FoundationSettings(allowableBearing=500, groundLevel=-1000)
    )
    weight = 2400 * G / 1e3 * 7.8 * 1.8 * 0.6
    total = 1500 + weight
    e = 3000 * 500 / total
    gross = total / (7.8 * 1.8) * (1 + 6 * e / 7800)
    assert by_name(checks)["Bearing (service)"]["demand"] == pytest.approx(gross - 10.8, rel=1e-3)


def test_service_combinations_follow_bnbc_2_7_2() -> None:
    names = [name for name, _ in service_combinations(["D", "SD", "L", "Lr", "WX", "EY"])]
    assert names[:2] == ["D", "D + L + Lr"]
    assert "D + 0.75L + 0.75Lr + 0.75WX" in names and "0.6D - 0.7EY" in names
    strength_level = dict(service_combinations(["D", "L", "WY"], strength_level_wind=True))
    assert strength_level["D + 0.75L + 0.45WY"] == {"D": 1.0, "L": 0.75, "WY": 0.45}


def test_service_combinations_take_the_figure_6_2_9_wind_cases() -> None:
    """Bearing is checked under every design wind load case (Sec 2.4.11.3, p. 559): Case 3
    (0.75 of both directions) and, with WTX/WTY analysed, Cases 2 and 4."""
    combos = dict(service_combinations(["D", "L", "WX", "WY", "WTX", "WTY"]))
    assert combos["D + WX"] == {"D": 1.0, "WX": 1.0}
    assert combos["D + 0.75WX - 0.75WY [Case 3 -WY]"] == {"D": 1.0, "WX": 0.75, "WY": -0.75}
    case2 = combos["D + 0.75WX + 0.75WTX [Case 2 +e]"]
    assert case2 == {"D": 1.0, "WX": 0.75, "WTX": 0.75}
    with_live = [f for n, f in combos.items() if n.startswith("D + 0.75L") and "Case 4" in n]
    assert with_live
    for f in with_live:
        assert f["L"] == 0.75
        for c in ("WX", "WY", "WTX", "WTY"):
            assert abs(f[c]) == pytest.approx(0.75 * 0.563)
    # Without the torsional cases analysed: Cases 1 and 3 only.
    plain = [n for n, _ in service_combinations(["D", "WX", "WY"])]
    assert any("Case 3" in n for n in plain) and not any("Case 2" in n for n in plain)


def test_uplifted_part_hogs_under_its_own_weight() -> None:
    spec = square_footing()
    loads = {"0.9D + 1.0EX": [np.array([100 * KN, 0.0, 100 * KN * 1000])]}
    checks, _ = design_footing(
        spec, {}, loads, FoundationSettings(groundLevel=0), dead={"0.9D + 1.0EX": 0.9}
    )
    top = by_name(checks)["Flexure X (top)"]
    w = 0.9 * (2400 * G / 1e3 * 0.5 + 18 * 1.0)
    assert top["demand"] == pytest.approx(w * 0.7**2 / 2, rel=0.01)
    assert top["capacity"] == pytest.approx(0.6 * 0.42 * 5 * 450**2 / 6 / 1e3, rel=1e-3)


def test_soil_bearing_overrides() -> None:
    clay = [{"top": 0, "bottom": 20000, "description": "Clay", "soilType": "clay", "cu": 100}]
    soil = json.dumps(
        {
            "boreholes": [
                {
                    "id": "BH-1",
                    "x": 0,
                    "y": 0,
                    "layers": clay,
                    "spt": [{"depth": 1500, "N": 15}],
                }
            ]
        }
    )
    plain = SoilBearing(soil, FoundationSettings()).at(0, 0, -1500, 1800, 1800)
    assert plain.source == "soilReport" and plain.qa == pytest.approx(272.9, abs=0.05)
    # The substructure's factor of safety replaces the soil report's (3): qa scales with 1/FS.
    halved = SoilBearing(soil, FoundationSettings(), 6.0).at(0, 0, -1500, 1800, 1800)
    assert halved.qa == pytest.approx(plain.qa / 2, rel=1e-3)
    # A foundation's own qa wins over everything.
    own = SoilBearing(soil, FoundationSettings(allowableBearing=90)).at(
        0, 0, -1500, 1800, 1800, 120, "F1"
    )
    assert (own.qa, own.source) == (120, "override") and "F1 in 9 Substructure" in own.note


# ───────────────────────── strip footings and tie beams, synthetic loads ──────────────────────────

STRIP_OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            *OBJECTS.model_dump(mode="json", by_alias=True)["objects"],
            {"id": "WL", "name": "Wall 200", "kind": "wall", "material": "C24.1", "thickness": 200},
            {
                "id": "TB",
                "name": "Tie beam 250x400",
                "kind": "beam",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 250, "yDim": 400},
                "reinforcement": {
                    "material": "B420DWR",
                    "cover": 40,
                    "longitudinal": [
                        {"position": "top", "count": 2, "dia": 16},
                        {"position": "bottom", "count": 2, "dia": 16},
                    ],
                    "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
                },
            },
        ]
    }
)


def synthetic(
    elements: list[dict],
    supports: dict[str, list[tuple[int, list[float], list[float]]]],
    substructure: dict,
    settings: ProjectSettings | None = None,
) -> Context:
    """A context with hand-made loads: per base its support nodes (id, [x, y, z] mm, the dead
    load reaction [Fx, Fy, Fz, Mx, My, Mz] N, N·m) and the one strength combination 1.0D."""
    building = BuildingModel.model_validate({"elements": elements})
    cases: dict[str, dict[int, np.ndarray]] = {"D": {}}
    bases = {}
    by_id = {e.id: e for e in building.elements}
    for base_id, nodes in supports.items():
        for node, _, reaction in nodes:
            cases["D"][node] = np.array(reaction, dtype=float)
        bases[base_id] = Base(
            base_id, by_id[base_id], [(n, np.array(xyz, dtype=float)) for n, xyz, _ in nodes]
        )
    loads = BaseLoads(
        cases, bases, [("1.0D", {"D": 1.0})], [("D", {"D": 1.0})], {"1.0D": 1.0}, False
    )
    return Context(
        Substructure.model_validate(substructure),
        building,
        STRIP_OBJECTS,
        default_material_library(),
        settings or SETTINGS,
        loads=loads,
    )


def wall_strip(offset: float, width: float = 1500, per_metre: float = 150) -> Context:
    """A 4 m wall W1 (200 thick, base at -1000) on a strip 4 m long, ``width`` wide, 400 thick,
    founded at -1500 under 0.5 m of soil; its base edge on five supports 1 m apart, ``offset``
    from the strip's centre line, carrying ``per_metre`` kN/m (the end nodes half as much)."""
    nodes = []
    for k in range(5):
        share = 0.5 if k in (0, 4) else 1.0
        nodes.append(
            (k + 1, [k * 1000.0, offset, -1000.0], [0, 0, share * per_metre * KN, 0, 0, 0])
        )
    return synthetic(
        [
            {
                "id": "W1",
                "kind": "wall",
                "type": "WL",
                "start": [0, offset],
                "end": [4000, offset],
                "bottom": -1000,
                "top": 2000,
            }
        ],
        {"W1": nodes},
        {
            "foundations": [
                {
                    "id": "S1",
                    "type": "strip",
                    "columns": ["W1"],
                    "path": [[0, 0], [4000, 0]],
                    "width": width,
                    "thickness": 400,
                    "foundingLevel": -1500,
                    "material": "C24.1",
                    "reinforcement": {
                        **REINFORCEMENT,
                        "bottomX": {"dia": 12, "spacing": 150},
                        "bottomY": {"dia": 12, "spacing": 150},
                    },
                    "allowableBearing": 300,
                }
            ]
        },
        SETTINGS.model_copy(update={"foundation": FoundationSettings(groundLevel=0)}),
    )


def test_strip_footing_under_a_wall_per_metre_by_hand() -> None:
    ctx = wall_strip(0.0)
    result, notes = design_shallow(ctx, ctx.substructure.foundations[0])
    checks = by_name(result["checks"])
    assert result["columns"] == ["W1"] and result["type"] == "strip"
    assert not any(n.startswith("Punching") for n in checks)
    # Per metre: 150 kN on 1.5 m: q = 100 kPa; the wall face 650 mm from the edge.
    q = 150 / 1.5  # kPa = kN/m per m
    flexure = checks["Flexure Y (bottom)"]
    assert flexure["demand"] == pytest.approx(q * 0.65**2 / 2, rel=1e-3)  # 21.1 kN·m/m
    assert "under wall W1, per metre of wall" in flexure["note"]
    d_y = 400 - 75 - 12 - 6
    shear = checks["One-way shear Y"]
    assert shear["demand"] == pytest.approx(q * (650 - d_y) / 1000, rel=1e-3)
    a_s = math.pi * 36 * 1000 / 150
    assert shear["capacity"] == pytest.approx(
        one_way_shear_capacity(1000, d_y, a_s / (1000 * d_y), 24.1) / KN, rel=1e-3
    )
    # Bearing per metre: 150 kN + the strip (0.4 m) + 1.1 m of soil, net of 18 x 1.5.
    weight = 2400 * G / 1e3 * 0.4 * 1.5 + 18 * 1.1 * 1.5
    bearing = checks["Bearing (service)"]
    assert bearing["demand"] == pytest.approx((150 + weight) / 1.5 - 27, rel=1e-3)
    assert result["pressure"]["source"] == "override" and bearing["capacity"] == 300
    assert result["sizes"]["length"] == 4000 and result["sizes"]["foundingLevel"] == -1500
    assert result["ok"], result
    assert notes == []


def test_strip_footing_under_an_eccentric_wall_by_hand() -> None:
    # The wall 300 mm off the centre line: e = 300 x 150 / (150 + weight) < B/6 = 250 mm.
    ctx = wall_strip(300.0)
    result, _ = design_shallow(ctx, ctx.substructure.foundations[0])
    weight = 2400 * G / 1e3 * 0.4 * 1.5 + 18 * 1.1 * 1.5
    total = 150 + weight
    e = 300 * 150 / total
    assert e < 250
    bearing = by_name(result["checks"])["Bearing (service)"]
    assert bearing["demand"] == pytest.approx(total / 1.5 * (1 + 6 * e / 1500) - 27, rel=1e-3)
    # 450 mm off: beyond the kern, qmax = 2P / (3 (B/2 - e)) per metre.
    ctx = wall_strip(450.0)
    result, _ = design_shallow(ctx, ctx.substructure.foundations[0])
    e = 450 * 150 / total
    bearing = by_name(result["checks"])["Bearing (service)"]
    assert bearing["demand"] == pytest.approx(2 * total / (3 * (0.75 - e / 1000)) - 27, rel=1e-3)
    assert "partial contact" in bearing["note"]
    # Flexure at the wall's inner face v = 350 mm, per metre of wall: the contact pressure of
    # a 1 m strip under the wall's load and its own weight (factor 1.0), less that weight, by
    # statics over the 1100 mm from the far edge at v = -750 mm.
    flexure = by_name(result["checks"])["Flexure Y (bottom)"]
    w = weight * KN / 1500 / 1000  # N/mm² of base
    p = soil_pressure(total * KN, 0, e, 1000, 1500)
    force, _, first = p.integrals(-500, 500, -750, 350)
    expected = (350 * force - first - w * 1000 * 1100**2 / 2) / 1e6
    assert flexure["demand"] == pytest.approx(expected, rel=0.01)


def test_strip_footing_reports_what_it_cannot_design() -> None:
    ctx = wall_strip(0.0)
    bent = ctx.substructure.foundations[0].model_copy(
        update={"path": [[0, 0], [2000, 0], [4000, 500]]}
    )
    with pytest.raises(Skip, match="only straight strip footings"):
        design_shallow(ctx, bent)
    narrow = ctx.substructure.foundations[0].model_copy(update={"width": 150})
    with pytest.raises(Skip, match="wall W1 extends beyond the strip"):
        design_shallow(ctx, narrow)
    isolated = Foundation.model_validate(footing("F9", ["W1"], center=[2000, 0]))
    with pytest.raises(Skip, match="wall W1 can stand on a strip footing only"):
        design_shallow(ctx, isolated)


def two_columns(
    settlement: float | None = None,
    p1: float = 900,
    p2: float = 1300,
    x2: float = 6000,
    foundations: bool = True,
) -> Context:
    """C1 at (0, 0) and C2 at (``x2``, 0), 400 x 400, carrying ``p1`` and ``p2`` kN of dead
    load, on footings F1 and F2 tied by TB1 (``foundations``)."""
    elements = [
        {"id": "C1", "kind": "column", "type": "COL", "position": [0, 0], "bottom": 0, "top": 3000},
        {"id": "C2", "kind": "column", "type": "COL", "position": [x2, 0], "bottom": 0,
         "top": 3000},
    ]  # fmt: skip
    tie = {"id": "TB1", "from": "F1", "to": "F2", "type": "TB"}
    if settlement is not None:
        tie["settlement"] = settlement
    return synthetic(
        elements,
        {
            "C1": [(1, [0, 0, 0], [0, 0, p1 * KN, 0, 0, 0])],
            "C2": [(2, [x2, 0, 0], [0, 0, p2 * KN, 0, 0, 0])],
        },
        {
            "foundations": [footing("F1", ["C1"]), footing("F2", ["C2"])],
            "tieBeams": [tie],
        }
        if foundations
        else {},
        SETTINGS.model_copy(update={"foundation": FoundationSettings(allowableBearing=150)}),
    )


def test_tie_beam_force_size_and_settlement_by_hand() -> None:
    ctx = two_columns(settlement=12)
    result, notes = design_tie_beam(ctx, ctx.substructure.tieBeams[0])
    checks = by_name(result["checks"])
    # 10 % of the larger column load (BNBC 2020 Part 6 Sec 1.8.5.2 (b)): 0.1 x 1300 kN.
    assert result["force"] == pytest.approx(130)
    a_s = 4 * math.pi * 16**2 / 4
    tension = checks["Tie force (tension)"]
    assert tension["demand"] == pytest.approx(130) and "C2, 1300 kN" in tension["note"]
    assert tension["capacity"] == pytest.approx(0.9 * 420 * a_s / KN, rel=1e-3)
    p0 = 0.85 * 24.1 * (250 * 400 - a_s) + 420 * a_s
    assert checks["Tie force (compression)"]["capacity"] == pytest.approx(
        0.8 * 0.65 * p0 / KN, rel=1e-3
    )
    # Size: the clear spacing between the column faces 6000 - 400 = 5600 mm / 20 = 280 mm.
    size = checks["Size (BNBC 8.3.11.3)"]
    assert (size["demand"], size["capacity"], size["ok"]) == (280, 250, False)
    # Settlement: M = 6 E (0.35 Ig) Δ / L², V = 2M / L.
    e = default_material_library().get("C24.1").mechanical.E
    inertia = 0.35 * 250 * 400**3 / 12
    moment = 6 * e * inertia * 12 / 6000**2
    assert checks["Flexure from settlement"]["demand"] == pytest.approx(moment / 1e6, rel=1e-3)
    assert checks["Shear from settlement"]["demand"] == pytest.approx(
        2 * moment / 6000 / KN, rel=1e-3
    )
    assert 0 < checks["Flexure from settlement"]["capacity"] < 100
    # Shear with the 130 kN tie force in tension (ACI 318-19 Table 22.5.5.1): Vc less
    # Nu / (6 Ag) bw d = 130000 / (6 x 250 x 400) = 0.217 MPa times bw d.
    from saengine.design.rc import section_of, shear
    from saengine.library.objects import Beam

    beam = next(o for o in STRIP_OBJECTS.objects if o.id == "TB")
    assert isinstance(beam, Beam)
    section = section_of(beam.profile, beam.reinforcement, 24.1, 420, 200000)
    plain = shear(section, 10, 2, 150)
    reduced = plain.vc - 130e3 / (6 * 250 * 400) * 250 * plain.d
    assert 0 < reduced < plain.vc
    assert checks["Shear from settlement"]["capacity"] == pytest.approx(
        0.75 * (reduced + plain.vs) / KN, abs=0.01
    )
    assert "Nu / (6 Ag)" in checks["Shear from settlement"]["note"]
    assert not result["ok"] and notes == []
    # Without a settlement: no flexure or shear checks.
    ctx = two_columns()
    result, _ = design_tie_beam(ctx, ctx.substructure.tieBeams[0])
    assert [c["name"] for c in result["checks"]] == [
        "Tie force (tension)",
        "Tie force (compression)",
        "Size (BNBC 8.3.11.3)",
    ]


def test_tie_force_takes_the_footing_load_of_a_combined_footing() -> None:
    # BNBC 2020 Part 6 Sec 1.8.5.2 (b): "10 % of the larger footing or column load". A combined
    # footing under C1 and C2 (1000 kN each) tied to F3 under C3 (500 kN): 0.1 x 2000 kN.
    elements = [
        {"id": c, "kind": "column", "type": "COL", "position": xy, "bottom": 0, "top": 3000}
        for c, xy in (("C1", [0, 0]), ("C2", [3000, 0]), ("C3", [1500, 6000]))
    ]
    ctx = synthetic(
        elements,
        {
            "C1": [(1, [0, 0, 0], [0, 0, 1000 * KN, 0, 0, 0])],
            "C2": [(2, [3000, 0, 0], [0, 0, 1000 * KN, 0, 0, 0])],
            "C3": [(3, [1500, 6000, 0], [0, 0, 500 * KN, 0, 0, 0])],
        },
        {
            "foundations": [
                footing("F1", ["C1", "C2"], type="combined", length=4000),
                footing("F3", ["C3"]),
            ],
            "tieBeams": [{"id": "TB1", "from": "F1", "to": "F3", "type": "TB"}],
        },
    )
    result, _ = design_tie_beam(ctx, ctx.substructure.tieBeams[0])
    assert result["force"] == pytest.approx(200)
    tension = by_name(result["checks"])["Tie force (tension)"]
    assert (
        "F1 (C1, C2), 2000 kN" in tension["note"] and "footing or column load" in (tension["note"])
    )


def test_strip_under_columns_and_a_wall_keeps_its_one_way_shear() -> None:
    # A strip 6.8 m x 1.5 m x 600 under C1 and C2 (400 x 400, 6 m apart, 1000 kN each) and a
    # 10 kN/m wall W1 between them: the sections at d from the column faces lie within the
    # wall's spread load and must still be checked.
    wall = [
        (10 + k, [k * 1000.0, 0, 0], [0, 0, (0.5 if k in (0, 6) else 1.0) * 10 * KN, 0, 0, 0])
        for k in range(7)
    ]
    elements = [
        {"id": "C1", "kind": "column", "type": "COL", "position": [0, 0], "bottom": 0,
         "top": 3000},
        {"id": "C2", "kind": "column", "type": "COL", "position": [6000, 0], "bottom": 0,
         "top": 3000},
        {"id": "W1", "kind": "wall", "type": "WL", "start": [0, 0], "end": [6000, 0],
         "bottom": 0, "top": 3000},
    ]  # fmt: skip
    ctx = synthetic(
        elements,
        {
            "C1": [(1, [0, 0, 0], [0, 0, 1000 * KN, 0, 0, 0])],
            "C2": [(2, [6000, 0, 0], [0, 0, 1000 * KN, 0, 0, 0])],
            "W1": wall,
        },
        {
            "foundations": [
                {
                    "id": "S1",
                    "type": "strip",
                    "columns": ["C1", "C2", "W1"],
                    "path": [[-400, 0], [6400, 0]],
                    "width": 1500,
                    "thickness": 600,
                    "foundingLevel": -1500,
                    "material": "C24.1",
                    "reinforcement": {**REINFORCEMENT, "topX": MESH},
                    "allowableBearing": 300,
                }
            ]
        },
        SETTINGS.model_copy(update={"foundation": FoundationSettings(groundLevel=0)}),
    )
    result, _ = design_shallow(ctx, ctx.substructure.foundations[0])
    shear = by_name(result["checks"])["One-way shear X"]
    # d = 600 - 75 - 16/2 = 517 mm; the section 517 mm inside C2's inner face, 1117 mm from
    # the strip's end: V = 1000 + 10 x 0.717 (wall up to C2's centre) - 2060 x 1117 / 6800.
    d = 517
    assert shear["demand"] == pytest.approx(1000 + 10 * 0.717 - 2060 * 1.117 / 6.8, rel=1e-3)
    rho = math.pi * 64 * 1000 / 150 / (1000 * d)
    assert shear["capacity"] == pytest.approx(
        one_way_shear_capacity(1500, d, rho, 24.1) / KN, rel=1e-3
    )
    assert not shear["ok"] and not result["ok"]


def test_report_of_synthetic_footings_and_ties() -> None:
    ctx = two_columns(p1=400, p2=400)
    data = report(ctx)
    json.dumps(data)
    assert [f["id"] for f in data["foundations"]] == ["F1", "F2"]
    assert [t["id"] for t in data["tieBeams"]] == ["TB1"]
    assert data["summary"]["checked"] == 3 and data["summary"]["analysed"]
    assert data["summary"]["governing"] == "TB1"  # the 250 mm beam is too small for 5.6 m
    assert data["combinations"] == {"service": ["D"], "strength": ["1.0D"]}
    assert any("Tie beams" in line for line in data["method"])
    f1 = data["foundations"][0]
    assert f1["sizes"]["center"] == [0.0, 0.0] and f1["sizes"]["foundingLevel"] == -1500
    # Without loads every foundation is skipped, with the reason.
    ctx.loads, ctx.no_loads = None, "there are no analysis results; run the analysis first"
    data = report(ctx)
    assert {s["id"]: s["reason"] for s in data["skipped"]} == {
        "F1": "there are no analysis results; run the analysis first",
        "F2": "there are no analysis results; run the analysis first",
        "TB1": "there are no analysis results; run the analysis first",
    }
    assert not data["summary"]["analysed"]


# ─────────────────────────────── the analysed one-bay frame ───────────────────────────────


def write_project(
    root: Path, building: BuildingModel, settings: ProjectSettings = SETTINGS
) -> Path:
    """A SAEngine project folder with the frame analysed for all its static cases."""
    for folder in ("02 Project Settings", "03 Materials", "04 Objects", "06 BIM", "08 FEM"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    files = {
        "02 Project Settings/project-settings.json": settings,
        "03 Materials/materials.json": default_material_library(),
        "04 Objects/objects.json": STRIP_OBJECTS,
        "06 BIM/bim.json": building,
    }
    for name, model in files.items():
        (root / name).write_text(model.model_dump_json(by_alias=True), encoding="utf-8")
    d = derive_fem(building, STRIP_OBJECTS, default_material_library(), settings, {"bim": "abc"})
    model = root / "08 FEM" / "model.osmodel"
    model.write_text(json.dumps(d.project), encoding="utf-8")
    static = [a["id"] for a in d.project["analyses"] if a.get("type", "Static") == "Static"]
    run = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model), "--cases",
         *map(str, static), "--out", str(root / "08 FEM" / "model.results")],
        check=False, capture_output=True, text=True, timeout=600,
    )  # fmt: skip
    assert run.returncode == 0, run.stderr[-2000:]
    return root


def write_substructure(root: Path, data: dict) -> None:
    path = root / SUBSTRUCTURE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture(scope="module")
def frame(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_project(tmp_path_factory.mktemp("frame"), generate(PLAN, "s"))


@pytest.fixture(scope="module")
def wall_frame(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The frame with a 200 mm wall W1 along grid line 2 (A2-B2, between C4 and C3)."""
    data = PLAN.model_dump(mode="json", by_alias=True)
    data["walls"] = [
        {"id": "W1", "type": "WL", "base": "BASE", "top": "L1",
         "start": {"x": "A", "y": "2"}, "end": {"x": "B", "y": "2"}},
    ]  # fmt: skip
    return write_project(
        tmp_path_factory.mktemp("walls"), generate(FloorPlan.model_validate(data), "s")
    )


def test_report_of_the_analysed_frame(frame: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from saengine.substructure import report as report_module

    # A foundation type whose design module is not there is skipped, with the reason.
    monkeypatch.setitem(report_module.EXTERNAL, "raft", (("missing",), "design_raft", ()))
    write_substructure(
        frame,
        {
            "foundations": [
                footing("F1", ["C1"], allowableBearing=150),
                footing("F2", ["C2"]),
                {
                    **footing("CF", ["C3", "C4"], length=7800, thickness=600, type="combined"),
                    "reinforcement": {**REINFORCEMENT, "topX": MESH},
                    "allowableBearing": 150,
                },
                footing("F9", ["C9"]),
                footing("F8", ["C1x"], material="C99"),
                {
                    "id": "R1",
                    "type": "raft",
                    "outline": [[0, 0], [1000, 0], [1000, 1000]],
                    "thickness": 500,
                },
            ],
            "tieBeams": [{"id": "TB1", "from": "F1", "to": "F2", "type": "TB"}],
        },
    )
    data = substructure_report(frame)
    json.dumps(data)
    by_id = {f["id"]: f for f in data["foundations"]}
    assert sorted(by_id) == ["CF", "F1", "F2"]
    assert by_id["CF"]["columns"] == ["C3", "C4"] and by_id["CF"]["type"] == "combined"
    names = [c["name"] for c in by_id["F1"]["checks"]]
    assert names[:2] == ["Bearing (service)", "Punching at C1"]
    assert by_id["F1"]["pressure"]["qa"] == 150 and by_id["F1"]["pressure"]["source"] == "override"
    # F2 has no qa (no soil report, no override): its bearing is noted, not checked.
    assert "Bearing (service)" not in [c["name"] for c in by_id["F2"]["checks"]]
    assert any(n.startswith("F2: bearing not checked") for n in data["notes"])
    checks = by_name(by_id["CF"]["checks"])
    assert checks["Flexure between columns (top)"]["demand"] > 0
    assert {"Punching at C3", "Punching at C4"} <= set(checks)
    skipped = {s["id"]: s["reason"] for s in data["skipped"]}
    assert skipped["F9"] == "'C9' is not a column or wall of 6 BIM"
    assert skipped["F8"] == "'C1x' is not a column or wall of 6 BIM"
    assert skipped["R1"] == "rafts are not designed yet"
    assert "9 Substructure: F9: 'C9' is not a column or wall of 6 BIM" in data["notes"]
    assert data["tieBeams"][0]["force"] > 0
    assert data["summary"]["checked"] == 4 and data["summary"]["skipped"] == 3
    # The same footing in Part 8's old path gives the same checks.
    from saengine.design.footing import footing_checks

    old_building = generate(PLAN, "s")
    old_building = old_building.model_copy(
        update={
            "elements": [
                *old_building.elements,
                FootingElement(id="F1", type="F18", position=[0, 0], elevation=-1000),
            ]
        }
    )
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                *STRIP_OBJECTS.model_dump(mode="json", by_alias=True)["objects"],
                {"id": "F18", "name": "F18", "kind": "footing", "material": "C24.1",
                 "length": 1800, "width": 1800, "thickness": 500, "reinforcement": REINFORCEMENT},
            ]
        }
    )  # fmt: skip
    project = json.loads((frame / "08 FEM" / "model.osmodel").read_text(encoding="utf-8"))
    settings = SETTINGS.model_copy(update={"foundation": FoundationSettings(allowableBearing=150)})
    old, _, _ = footing_checks(
        project, frame / "08 FEM" / "model.results", old_building, objects,
        default_material_library(), settings,
    )  # fmt: skip
    new = by_id["F1"]["checks"]
    assert [c["name"] for c in old[0]["checks"]] == [c["name"] for c in new]
    for a, b in zip(old[0]["checks"], new, strict=True):
        assert a["demand"] == pytest.approx(b["demand"]) and a["capacity"] == b["capacity"]


def test_strip_footing_under_the_wall_and_its_columns(wall_frame: Path) -> None:
    write_substructure(
        wall_frame,
        {
            "foundations": [
                {
                    "id": "S1",
                    "type": "strip",
                    "columns": ["W1", "C3", "C4"],
                    "path": [[-500, 5000], [6500, 5000]],
                    "width": 1200,
                    "thickness": 500,
                    "material": "C24.1",
                    "reinforcement": {**REINFORCEMENT, "topX": MESH},
                    "allowableBearing": 100,
                },
                footing("F1", ["C1"], allowableBearing=100),
            ]
        },
    )
    data = substructure_report(wall_frame)
    strip = next(f for f in data["foundations"] if f["id"] == "S1")
    assert strip["columns"] == ["C3", "C4", "W1"]
    checks = by_name(strip["checks"])
    assert {"Bearing (service)", "Punching at C3", "Punching at C4"} <= set(checks)
    assert not any(n.startswith("Punching at W1") for n in checks)
    assert checks["Bearing (service)"]["capacity"] == 100
    # The wall's and the columns' reactions all reach the strip: its resultant under D equals
    # the support reactions of C3, C4 and W1 (shared nodes counted once).
    ctx = load_context(wall_frame)
    nodes = {n for b in ("C3", "C4", "W1") for n, _ in ctx.loads.bases[b].nodes}
    dead = dict(ctx.loads.service)["D"]
    total = sum(ctx.loads.reaction(n, dead)[2] for n in nodes)  # upward reactions
    from saengine.substructure.shallow import footing_loads, place_footing

    placed = place_footing(ctx, ctx.substructure.foundation("S1"))
    service, _ = footing_loads(ctx.loads, placed)
    assert sum(f[0] for f in service["D"]) == pytest.approx(total)
    assert "Column C2: no foundation under it" in data["notes"]
    # U2: C2 stands on nothing, so the checks are not complete even when all pass.
    summary = data["summary"]
    assert summary["total"] == summary["checked"] + summary["skipped"]
    assert summary["unsupported"] == ["C2"]
    assert summary["complete"] is False
    assert summary["status"] in ("fail", "incomplete")


def test_migration_of_the_footings_drawn_in_the_building_model() -> None:
    building = generate(PLAN, "s")
    footings = [
        FootingElement(id="F1", type="F18", position=[0, 0], elevation=-1000),
        FootingElement(id="CF1", type="CF", position=[3000, 0], elevation=-1000),
        FootingElement(id="S1", type="SF", position=[3000, 5000], elevation=-1200, rotation=0),
        FootingElement(id="PC1", type="PC", position=[6000, 5000], elevation=-1000),
    ]
    building = building.model_copy(update={"elements": [*building.elements, *footings]})
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                *STRIP_OBJECTS.model_dump(mode="json", by_alias=True)["objects"],
                {"id": "F18", "name": "F18", "kind": "footing", "material": "C24.1",
                 "length": 1800, "width": 1800, "thickness": 500, "reinforcement": REINFORCEMENT},
                {"id": "CF", "name": "CF", "kind": "footing", "material": "C24.1",
                 "footingType": "combined", "length": 7800, "width": 1800, "thickness": 600},
                {"id": "SF", "name": "SF", "kind": "footing", "material": "C24.1",
                 "footingType": "strip", "length": 7000, "width": 1000, "thickness": 400},
                {"id": "PC", "name": "PC", "kind": "pileCap", "material": "C24.1",
                 "length": 2400, "width": 2400, "thickness": 900, "pile": "BP", "pileCount": 4},
                {"id": "BP", "name": "BP", "kind": "pile", "material": "C24.1",
                 "pileType": "bored", "length": 18000,
                 "profile": {"shape": "circle", "radius": 250}},
            ]
        }
    )  # fmt: skip
    model, notes = migrate(building, objects)
    by_id = {f.id: f for f in model.foundations}
    assert by_id["F1"].columns == ["C1"] and by_id["F1"].type == "isolated"
    assert by_id["F1"].center == [0, 0] and by_id["F1"].foundingLevel == -1500
    assert by_id["F1"].reinforcement.bottomX.dia == 16
    # C1 stands on F1 first: the combined footing takes C2 only.
    assert by_id["CF1"].columns == ["C2"] and by_id["CF1"].type == "combined"
    assert "C1: stands on more than one footing; kept on the first" in notes
    assert by_id["S1"].type == "strip" and by_id["S1"].path == [[-500, 5000], [6500, 5000]]
    assert by_id["S1"].columns == ["C3", "C4"] and by_id["S1"].foundingLevel == -1600
    cap = by_id["PC1"]
    assert cap.columns == [] and "C3: stands on more than one footing; kept on the first" in notes
    assert cap.type == "pileCap" and model.cap_pile_type(cap).id == "BP" and len(cap.piles) == 4
    assert {tuple(p) for p in model.pile_offsets(cap)} == {
        (-800, -800), (800, -800), (-800, 800), (800, 800)
    }  # fmt: skip
    assert {tuple(p.position) for p in model.cap_piles(cap)} == {
        (5200, 4200), (6800, 4200), (5200, 5800), (6800, 5800)
    }  # fmt: skip
    assert model.pileTypes[0].diameter == 500 and model.pileTypes[0].kind == "bored"
    # Running it again adds nothing.
    again, notes = migrate(building, objects, model)
    assert again == model and "F1: already in 9 Substructure; left as it is there" in notes


def test_migration_leaves_out_bad_pile_caps_without_losing_their_columns() -> None:
    building = generate(PLAN, "s")
    footings = [
        FootingElement(id="PC1", type="PC0", position=[0, 0], elevation=-1000),  # no pile type
        FootingElement(id="PC2", type="PCS", position=[6000, 0], elevation=-1000),  # too small
        FootingElement(id="F1", type="F18", position=[0, 0], elevation=-1000),
        FootingElement(id="F2", type="F18", position=[6000, 0], elevation=-1000),
    ]
    building = building.model_copy(update={"elements": [*building.elements, *footings]})
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                *STRIP_OBJECTS.model_dump(mode="json", by_alias=True)["objects"],
                {"id": "F18", "name": "F18", "kind": "footing", "material": "C24.1",
                 "length": 1800, "width": 1800, "thickness": 500, "reinforcement": REINFORCEMENT},
                {"id": "PC0", "name": "PC0", "kind": "pileCap", "material": "C24.1",
                 "length": 2400, "width": 2400, "thickness": 900, "pileCount": 4},
                {"id": "PCS", "name": "PCS", "kind": "pileCap", "material": "C24.1",
                 "length": 500, "width": 500, "thickness": 900, "pile": "BP", "pileCount": 1},
                {"id": "BP", "name": "BP", "kind": "pile", "material": "C24.1",
                 "pileType": "bored", "length": 18000,
                 "profile": {"shape": "circle", "radius": 300}},
            ]
        }
    )  # fmt: skip
    model, notes = migrate(building, objects)  # no ValidationError for the small cap
    by_id = {f.id: f for f in model.foundations}
    assert set(by_id) == {"F1", "F2"} and model.pileTypes == []
    # The caps that were left out carry nothing: the footings below take their columns.
    assert by_id["F1"].columns == ["C1"] and by_id["F2"].columns == ["C2"]
    assert not any("stands on more than one footing" in n for n in notes)
    assert "PC1: its pile cap type names no pile type; left out" in notes
    assert (
        "PC2: its 1 piles do not fit in the cap (the pile at [0, 0] does not lie within the "
        "cap); left out" in notes
    )


def test_sizing_assistant_proposes_footings_that_pass(frame: Path) -> None:
    write_substructure(frame, {"foundations": [footing("F1", ["C1"])]})
    settings = SETTINGS.model_copy(update={"foundation": FoundationSettings(allowableBearing=60)})
    ctx = load_context(frame)
    ctx.settings = settings
    ctx.__post_init__()
    proposal = propose(ctx)
    # C1 has a footing already; the others get one each.
    assert [f["columns"] for f in proposal["foundations"]] == [["C2"], ["C3"], ["C4"]]
    assert [f["id"] for f in proposal["foundations"]] == ["F2", "F3", "F4"]
    assert all(d["ok"] for d in proposal["designs"])
    first = proposal["foundations"][0]
    assert first["length"] == first["width"] and first["length"] % 50 == 0
    assert first["thickness"] >= 300 and first["reinforcement"]["cover"] == 75
    # Minimal: one step smaller fails bearing.
    smaller = Foundation.model_validate({**first, "length": first["length"] - 50,
                                         "width": first["width"] - 50})  # fmt: skip
    result, _ = design_shallow(ctx, smaller)
    assert not by_name(result["checks"])["Bearing (service)"]["ok"]


def test_sizing_assistant_leaves_a_column_on_a_pile_cap_alone(frame: Path) -> None:
    # Selected or not, a column on a pile cap keeps it: no footing is proposed in its place.
    c1 = next(e for e in generate(PLAN, "s").elements if e.id == "C1")
    x, y = c1.position
    piles = [(x - 750, y - 750), (x + 750, y - 750), (x + 750, y + 750), (x - 750, y + 750)]
    write_substructure(
        frame,
        {
            "foundations": [
                {"id": "PC1", "type": "pileCap", "columns": ["C1"], "center": [x, y],
                 "length": 2300, "width": 2300, "thickness": 900,
                 "piles": ["PL1", "PL2", "PL3", "PL4"]},
            ],
            "pileTypes": [{"id": "BP500", "kind": "bored", "diameter": 500, "length": 18000,
                           "material": "C24.1"}],
            "piles": [
                {"id": f"PL{k + 1}", "type": "BP500", "position": list(p)}
                for k, p in enumerate(piles)
            ],
        },
    )  # fmt: skip
    settings = SETTINGS.model_copy(update={"foundation": FoundationSettings(allowableBearing=60)})
    ctx = load_context(frame)
    ctx.settings = settings
    ctx.__post_init__()
    proposal = propose(ctx, ["C1", "C2"])
    assert [f["columns"] for f in proposal["foundations"]] == [["C2"]]
    assert (
        "C1: stands on pile cap PC1; Size Footings sizes footings only (lay its piles out again "
        "with the pile tools)" in proposal["notes"]
    )


def test_sizing_assistant_combines_footings_that_would_overlap() -> None:
    # 1500 and 1000 kN 2.5 m apart on qa = 150 kPa: square footings over 3 m wide would
    # overlap. One combined footing, centred on the resultant 1000 mm from C1.
    ctx = two_columns(p1=1500, p2=1000, x2=2500, foundations=False)
    proposal = propose(ctx)
    assert len(proposal["foundations"]) == 1, proposal
    combined = proposal["foundations"][0]
    assert combined["type"] == "combined" and combined["columns"] == ["C1", "C2"]
    assert combined["center"] == [1000.0, 0.0] and combined["rotation"] == 0
    # At least 300 mm beyond the outer column faces from the resultant: 2 x (1500 + 200 + 300);
    # grown in both directions once it is as wide as long.
    assert combined["length"] >= 4000 and combined["length"] >= combined["width"]
    assert "topX" in combined["reinforcement"] and proposal["designs"][0]["ok"], proposal
    assert any("one combined footing" in n for n in proposal["notes"])
    # The proposal passes when designed as it stands.
    result, _ = design_shallow(ctx, Foundation.model_validate(combined))
    assert result["ok"]
    # Uniform pressure under the dead load (the resultant at the centroid): net = gross - γ Df.
    bearing = by_name(result["checks"])["Bearing (service)"]
    area = combined["length"] * combined["width"] / 1e6
    h = combined["thickness"] / 1e3
    gross = 2500 / area + 2400 * G / 1e3 * h + 18 * (1.5 - h)
    assert bearing["demand"] == pytest.approx(gross - 27, rel=1e-3)


def test_minimum_mesh_meets_the_minimum_steel() -> None:
    from saengine.substructure.run import minimum_mesh

    # The same meshes as the editor's minimumMesh (substructureDocument.test.ts).
    meshes = {h: minimum_mesh(h) for h in (300, 450, 500, 600, 1000)}
    assert meshes == {
        300: {"dia": 12, "spacing": 200},
        450: {"dia": 12, "spacing": 125},
        500: {"dia": 12, "spacing": 125},
        600: {"dia": 16, "spacing": 175},
        1000: {"dia": 20, "spacing": 150},
    }
    for h, mesh in meshes.items():
        assert math.pi * mesh["dia"] ** 2 / 4 * 1000 / mesh["spacing"] >= 0.0018 * h * 1000
    # B500 bars: As,min = 0.0018 · 420 / 500 h = 0.001512 h.
    assert minimum_mesh(600, 500) == {"dia": 16, "spacing": 200}


def test_run_all_step_gives_footings_without_bars_the_minimum_mesh(frame: Path) -> None:
    from saengine.substructure.run import design_foundations

    bare = {k: v for k, v in footing("F1", ["C1"]).items() if k != "reinforcement"}
    write_substructure(frame, {"schema": "saengine.substructure/1", "foundations": [bare]})
    data = design_foundations(frame)
    saved = json.loads((frame / SUBSTRUCTURE_FILE).read_text(encoding="utf-8"))
    bars = saved["foundations"][0]["reinforcement"]
    assert bars["bottomX"] == bars["bottomY"] == {"dia": 12, "spacing": 125}  # h = 500
    summary = data["summary"]
    assert summary["barsAdded"] == ["F1 12@125"]
    assert summary["checked"] == summary["total"] == 1
    # The other columns stand on nothing: designed, but not complete.
    assert summary["status"] in ("incomplete", "fail") and summary["unsupported"]
    assert data["notes"][0].startswith("Minimum bars added")
    # Nothing to design: status none, not "pass".
    write_substructure(frame, {"schema": "saengine.substructure/1", "foundations": []})
    assert design_foundations(frame)["summary"]["status"] == "none"


def test_pile_cap_on_its_own_pile_grid_in_the_report(frame: Path, tmp_path: Path) -> None:
    """A cap over four piles set out on the pile grid, not centred on its column C2 at (6000, 0):
    the report carries the eccentricity into the pile loads (the piles on the column's side take
    more than with the cap centred), names the piles by their marks and positions, and warns of a pile under no cap."""
    from test_substructure_piles import CLAY_ON_SAND

    from saengine.library.settings import SOIL_FILE

    root = tmp_path / "piled"
    shutil.copytree(frame, root)
    (root / SOIL_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / SOIL_FILE).write_text(
        json.dumps({"boreholes": [{**CLAY_ON_SAND, "x": 3000, "y": 2500}]}), encoding="utf-8"
    )

    def layout(x0: float, y0: float) -> dict:
        points = [(x0, y0), (x0 + 1500, y0), (x0 + 1500, y0 + 1500), (x0, y0 + 1500)]
        return {
            "foundations": [
                {"id": "PC1", "type": "pileCap", "columns": ["C2"],
                 "center": [x0 + 750, y0 + 750], "length": 2300, "width": 2300,
                 "thickness": 900, "material": "C24.1", "reinforcement": REINFORCEMENT,
                 "piles": ["PL1", "PL2", "PL3", "PL4"]},
            ],
            "pileTypes": [{"id": "BP500", "diameter": 500, "length": 18000,
                           "material": "C24.1"}],
            "pileGrid": {"origin": [x0, y0],
                         "x": [{"label": "a", "position": 0}, {"label": "b", "position": 1500}],
                         "y": [{"label": "1", "position": 0}, {"label": "2", "position": 1500}]},
            "piles": [{"id": f"PL{k + 1}", "type": "BP500", "position": list(p)}
                      for k, p in enumerate([*points, (9000, 3000)])],
        }  # fmt: skip

    write_substructure(root, layout(5250, -750))  # centred on C2
    centred = {p["mark"]: p for p in substructure_report(root)["foundations"][0]["piles"]}
    write_substructure(root, layout(5100, -900))  # 150 mm off C2 both ways
    report = substructure_report(root)
    assert not report["skipped"], report["skipped"]
    cap = report["foundations"][0]
    assert cap["group"]["eccentricity"] == [150, 150]
    assert any("150 mm (u) and 150 mm (v) off the piles' centroid" in n for n in report["notes"])
    rows = {p["mark"]: p for p in cap["piles"]}
    assert (rows["PL1"]["x"], rows["PL1"]["y"]) == (5100, -900)
    assert (rows["PL3"]["u"], rows["PL3"]["v"]) == (750, 750)
    # The pile nearest the column (PL3, +u +v) takes more than with the cap centred, the far
    # one (PL1) less: P e each way, shared by Σu² (rigid cap).
    assert rows["PL3"]["serviceMax"] > centred["PL3"]["serviceMax"] + 1
    assert rows["PL1"]["serviceMax"] < centred["PL1"]["serviceMax"] - 1
    assert sum(r["serviceMax"] for r in rows.values()) == pytest.approx(
        sum(r["serviceMax"] for r in centred.values()), rel=0.1
    )
    assert cap["sizes"]["piles"] == ["PL1", "PL2", "PL3", "PL4"]
    assert report["pileLayout"] == {
        "piles": 5, "capped": 4, "warnings": ["PL5: under no pile cap"]
    }  # fmt: skip
    assert "Pile layout: PL5: under no pile cap" in report["notes"]
