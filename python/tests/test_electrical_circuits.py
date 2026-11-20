"""Distribution boards, circuiting, cable sizing, voltage drop and short-circuit checks
(IEC 60364-5-52, IEC 60364-4-41/-43, IEC 60909-0), verified by hand calculations."""

from __future__ import annotations

import json
import math
from pathlib import Path

import openpyxl
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.drawings.sheets import mep as mep_sheets
from saengine.drawings.sheets.model import Building as SheetBuilding
from saengine.drawings.sheets.model import Level
from saengine.electrical.cables import (
    adiabatic_min_size,
    correction_factors,
    effective_ampacity,
    size_cable,
    voltage_drop,
)
from saengine.electrical.demand import demand
from saengine.electrical.panels import (
    balance_phases,
    db_schedule_table,
    export_db_schedules_xlsx,
    generate_boards,
)
from saengine.electrical.report import electrical_results
from saengine.electrical.short_circuit import (
    check_breaking_capacity,
    check_disconnection,
    fault_at_node,
    transformer_source,
    zs_limit,
)
from saengine.library.mep import MepModel
from saengine.mep import rooms as R
from saengine.plumbing.building import Building
from saengine.verification.cases.electrical import (
    eight_storey,
    eight_storey_bim,
    eight_storey_electrical,
)


def test_2_5_mm2_cu_pvc_method_c_30c_single_circuit_hand() -> None:
    """Hand check: 2.5 mm² Cu PVC final circuit, Method C, 30 °C, single circuit, Ib = 16 A,
    L = 20 m:
    - Table B.52.4 (2 loaded conductors): It = 27 A; Ca(30 °C) = 1.00, Cg(1) = 1.00, Ci = 1.00
      -> Iz = 27.0 A >= 16 A (with In = 16 A: 16 <= 16 <= 27).
    - mV/A/m = 18.0 -> Vd = 18.0 * 16 * 20 / 1000 = 5.76 V = 5.76 / 230 * 100 = 2.504 % <= 3 %.
    """
    amp = effective_ampacity(
        2.5, conductor="Cu", insulation="PVC", method="C", phases=1, ambient_temp=30.0
    )
    assert amp["It"] == pytest.approx(27.0)
    assert (amp["Ca"], amp["Cg"], amp["Ci"]) == (1.0, 1.0, 1.0)
    assert amp["Iz"] == pytest.approx(27.0)
    assert amp["Iz"] >= 16.0

    vd = voltage_drop(2.5, ib=16.0, length_m=20.0, phases=1, conductor="Cu", insulation="PVC")
    hand_vd_v = 18.0 * 16.0 * 20.0 / 1000.0  # 5.76 V
    hand_vd_pct = hand_vd_v / 230.0 * 100.0  # 2.50435 %
    assert vd["mvPerAM"] == pytest.approx(18.0)
    assert vd["vdV"] == pytest.approx(hand_vd_v)
    assert vd["vdPct"] == pytest.approx(hand_vd_pct)
    assert vd["vdPct"] <= 3.0  # passes lighting (3 %) and other (5 %) limits

    # Also verify R/X with cos(phi) = 0.85:
    # R_op = 7.41 * 1.20 = 8.892 ohm/km, X = 0.10 ohm/km, sin(phi) = sqrt(1 - 0.85^2)
    sin_phi = math.sqrt(1.0 - 0.85**2)
    hand_rx_v = 2.0 * 16.0 * 20.0 * (7.41 * 1.20 * 0.85 + 0.10 * sin_phi) / 1000.0
    vd_rx = voltage_drop(
        2.5, ib=16.0, length_m=20.0, phases=1, pf=0.85, conductor="Cu", insulation="PVC", mode="rx"
    )
    assert vd_rx["vdV"] == pytest.approx(hand_rx_v)

    sized = size_cable(
        ib=16.0,
        length_m=20.0,
        phases=1,
        kind="lighting",
        conductor="Cu",
        insulation="PVC",
        method="C",
        ambient_temp=30.0,
        grouped_circuits=1,
        in_rating=16.0,
    )
    # 1.5 mm²: Vd = 29 * 16 * 20 / 1000 = 9.28 V = 4.03 % > 3 % -> fails Vd, so 2.5 mm² is chosen.
    assert sized["size"] == 2.5
    assert sized["ok"]


def test_grouping_factor_for_3_circuits_hand() -> None:
    """Hand check: grouping factor for 3 bunched circuits (Table B.52.17) Cg = 0.70.
    For 2.5 mm² Cu PVC Method C at 30 °C: Iz = 27 * 1.00 * 0.70 * 1.00 = 18.9 A.
    At Ib = 18 A (In = 20 A), 2.5 mm² fails (20 > 18.9) and 4 mm² (It = 36, Iz = 25.2 A) passes.
    """
    factors = correction_factors(insulation="PVC", ambient_temp=30.0, grouped_circuits=3)
    assert factors["Cg"] == pytest.approx(0.70)
    amp3 = effective_ampacity(
        2.5,
        conductor="Cu",
        insulation="PVC",
        method="C",
        phases=1,
        ambient_temp=30.0,
        grouped_circuits=3,
    )
    assert amp3["Iz"] == pytest.approx(27.0 * 0.70)

    # Ambient 40 °C (Ca = 0.87) + 3 circuits (Cg = 0.70) -> 27 * 0.87 * 0.70 = 16.443 A.
    amp_hot = effective_ampacity(
        2.5,
        conductor="Cu",
        insulation="PVC",
        method="C",
        phases=1,
        ambient_temp=40.0,
        grouped_circuits=3,
    )
    assert amp_hot["Iz"] == pytest.approx(27.0 * 0.87 * 0.70)

    check_fail = size_cable(
        ib=18.0,
        length_m=15.0,
        phases=1,
        kind="socket",
        conductor="Cu",
        insulation="PVC",
        method="C",
        ambient_temp=30.0,
        grouped_circuits=3,
        in_rating=20.0,
        specified_size=2.5,
    )
    assert not check_fail["ampacityOk"] and not check_fail["ok"]
    assert check_fail["recommendedSize"] == 4.0


def test_voltage_drop_failure_reports_passing_size_and_adiabatic_hand() -> None:
    """Long 60 m lighting circuit at 10 A on 1.5 mm² fails 3 % Vd; 4.0 mm² is smallest passing size.
    1.5 mm²: 29 * 10 * 60 / 1000 = 17.4 V = 7.565 % > 3 %.
    2.5 mm²: 18 * 10 * 60 / 1000 = 10.8 V = 4.696 % > 3 %.
    4.0 mm²: 11 * 10 * 60 / 1000 = 6.60 V = 2.870 % <= 3 %.
    """
    res = size_cable(
        ib=10.0,
        length_m=60.0,
        phases=1,
        kind="lighting",
        conductor="Cu",
        insulation="PVC",
        method="C",
        in_rating=10.0,
        specified_size=1.5,
    )
    assert not res["vdOk"] and not res["ok"]
    assert res["cumVdPct"] == pytest.approx(17.4 / 230.0 * 100.0)
    assert res["recommendedSize"] == 4.0

    # Adiabatic withstand: k = 115 (Cu PVC), Ik = 12 kA, t = 0.1 s -> S_min = 12000 * sqrt(0.1) / 115 = 32.998 mm² -> 35 mm².
    s_min = adiabatic_min_size(12.0, 0.1, conductor="Cu", insulation="PVC")
    assert s_min == pytest.approx(12000.0 * math.sqrt(0.1) / 115.0)
    sc_sized = size_cable(
        ib=40.0,
        length_m=10.0,
        phases=3,
        kind="power",
        conductor="Cu",
        insulation="PVC",
        method="C",
        in_rating=40.0,
        ik_ka=12.0,
        fault_duration_s=0.1,
    )
    assert sc_sized["size"] == 35.0


def test_1000kva_transformer_ik3_and_zs_disconnection_hand() -> None:
    """Hand check (IEC 60909-0):
    1000 kVA, 11/0.415 kV transformer, uk = 5 %, infinite HV bus (grid_sk_mva=None):
    - Base formula (c = 1.00): Ik3 = 1000 / (sqrt(3) * 0.415 * 0.05) = 27.8241 kA.
    - With pack c_max = 1.05 (IEC 60909-0 Table 1): Ik3 = 1.05 * 27.8241 = 29.2153 kA.
    """
    base_ik3 = 1000.0 / (math.sqrt(3) * 0.415 * 0.05) / 1000.0  # 27.8241 kA
    assert base_ik3 == pytest.approx(27.8241, abs=1e-3)

    src_c1 = transformer_source(
        1000.0, voltage_v=415.0, uk_pct=5.0, xr_ratio=8.0, grid_sk_mva=None, c_max=1.0
    )
    assert src_c1["ik3Ka"] == pytest.approx(base_ik3, rel=1e-6)

    src = transformer_source(1000.0, voltage_v=415.0, uk_pct=5.0, xr_ratio=8.0, grid_sk_mva=None)
    assert src["cMax"] == pytest.approx(1.05)
    assert src["ik3Ka"] == pytest.approx(1.05 * base_ik3, rel=1e-6)

    # Downstream 25 m of 16 mm² Cu XLPE sub-main + 20 m of 2.5 mm² Cu PVC final circuit:
    node = fault_at_node(
        src,
        [
            {
                "size": 16.0,
                "length": 25.0,
                "conductor": "Cu",
                "insulation": "XLPE",
                "cpcSize": 16.0,
            },
            {"size": 2.5, "length": 20.0, "conductor": "Cu", "insulation": "PVC", "cpcSize": 2.5},
        ],
    )
    assert 0 < node["ik1MinKa"] < node["ik3MaxKa"] < src["ik3Ka"]

    # Zs limit for 16 A Type B (m = 5, Cmin = 0.95, U0 = 230 V): 230 * 0.95 / (5 * 16) = 2.73125 ohm.
    assert zs_limit(16.0, curve="B") == pytest.approx(230.0 * 0.95 / 80.0)
    assert zs_limit(16.0, curve="C") == pytest.approx(230.0 * 0.95 / 160.0)
    disc = check_disconnection(node["zsOhm"], 16.0, curve="B")
    assert disc["ok"]
    brk = check_breaking_capacity(node["ik3MaxKa"], device_type="MCB", breaking_capacity_ka=6.0)
    assert brk["ok"]


def test_greedy_phase_balancing_5_4_3_3_2_1_kw_hand() -> None:
    """Hand check: [5, 4, 3, 3, 2, 1] kW balanced across L1, L2, L3 -> max phase load 6 kW."""
    bal = balance_phases([5, 4, 3, 3, 2, 1])
    assert bal["phaseLoads"] == {"L1": 6.0, "L2": 6.0, "L3": 6.0}
    assert bal["maxPhaseLoad"] == pytest.approx(6.0)
    assert bal["imbalancePct"] == pytest.approx(0.0)


def test_db_schedule_rows_sum_to_incomer_load_and_export(tmp_path: Path) -> None:
    """DB circuit loads sum exactly to DB total connected load and export to Excel & drawings."""
    mep, bim, objects = eight_storey()
    res = electrical_results(mep, bim, objects)
    boards = res["boards"]
    assert len(boards) == 9  # 8 story DBs + DB-MOTOR

    # Every board's schedule rows sum to its incomer totalLoadW, and all DBs sum to demand connected kW.
    for b in boards:
        sched = db_schedule_table(b)
        assert sched["columns"] == [
            "Way",
            "Description",
            "Load (W)",
            "Phase",
            "MCB",
            "Cable",
            "Length (m)",
            "Vd (%)",
        ]
        assert sum(row[2] for row in sched["rows"]) == pytest.approx(b["totalLoadW"], abs=1.0)
        assert b["ok"]
    assert sum(b["totalLoadW"] for b in boards) / 1000.0 == pytest.approx(
        res["demand"]["connected"], rel=1e-4
    )

    # Excel export via existing write_xlsx exporter.
    xlsx = tmp_path / "db_schedules.xlsx"
    out = export_db_schedules_xlsx(xlsx, boards)
    assert out["sheets"] == len(boards) + 1
    wb = openpyxl.load_workbook(xlsx)
    assert "DB Summary" in wb.sheetnames
    assert wb["DB-GF Schedule"]["A1"].value == "Way"

    # Drawing set MEP schedule tables include DB schedules.
    drawing = mep_sheets.MepDrawing(mep, electrical_boards=boards)
    sb = SheetBuilding(levels=[Level(s, s, 3500 * i) for i, s in enumerate(["GF", "L1"])])
    tables = {t.title: t for t in mep_sheets.schedule_tables(drawing, sb)}
    assert "DB-GF Schedule" in tables
    assert len(tables["DB-GF Schedule"].columns) == 8


def test_room_loads_generate_circuits_and_missing_pack_group_handled(tmp_path: Path) -> None:
    """Circuits generated from architectural rooms match story load; missing pack group raises
    code-independent not_covered error when called directly."""
    from test_mep_rooms import layout

    arch = layout()
    bim = eight_storey_bim()
    # One story (L1) with architectural rooms on it.
    el = {
        **eight_storey_electrical(),
        "stories": [{"story": "L1", "use": "office", "airConditioned": True}],
        "motors": [],
    }
    mep = MepModel.model_validate({"schema": "saengine.mep/1", "electrical": el})
    inputs = R.room_inputs(arch, bim)
    building = Building.of(bim)
    dem = demand(mep.electrical, building)
    boards = generate_boards(mep.electrical, dem, building, room_inputs=inputs)
    assert len(boards) == 1
    l1_rooms = {r.id for r in inputs.story("L1").rooms}
    ckt_rooms = {c["room"] for c in boards[0]["circuits"] if c.get("room")}
    assert ckt_rooms == l1_rooms
    assert sum(c["loadW"] for c in boards[0]["circuits"]) / 1000.0 == pytest.approx(
        dem["stories"][0]["connected"], rel=1e-4
    )

    # A code pack without cables/shortCircuit raises not_covered cleanly.
    pack_dir = tmp_path / "no-cables"
    (pack_dir / "data").mkdir(parents=True)
    (pack_dir / "pack.json").write_text(
        json.dumps(
            {
                "schema": "saengine.codePack/1",
                "id": "no-cables",
                "name": "No Cables",
                "extends": "bnbc2020",
                "covers": ["electrical"],
            }
        ),
        encoding="utf-8",
    )
    (pack_dir / "data" / "electrical.json").write_text(
        json.dumps({"$remove": ["cables", "shortCircuit", "circuitRules"]}),
        encoding="utf-8",
    )
    pack = registry.load_path(pack_dir)
    with code_context.using(pack):
        with pytest.raises(ValueError, match="not covered"):
            effective_ampacity(2.5)
        rep = electrical_results(mep, bim)
        assert rep["boards"] == []
