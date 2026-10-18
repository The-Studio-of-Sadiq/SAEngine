"""HVAC and electrical of 7 MEP wired into SAEngine: the loads on the analysis model (each item
once), the stamps the workbench shares, the RPC methods, the bill of quantities, the IFC model,
the design report's chapters and the shipped sample. Synthetic, hand-checked data."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path

import ifcopenshell
import pytest

from saengine.library.mep import MepModel, check
from saengine.mep.loads import has_model_content, services_equipment
from saengine.rpc import handlers

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"

SOIL = {
    "schema": "saengine.soilReport/1",
    "boreholes": [
        {
            "id": "BH1",
            "x": 6500,
            "y": 2500,
            "groundLevel": 0,
            "waterTable": 3000,
            "layers": [
                {"top": 0, "bottom": 30000, "description": "Uniform medium dense sand (synthetic)",
                 "soilType": "sand", "unitWeight": 18.0},
            ],
            "spt": [{"depth": 1500 * k, "N": 10} for k in range(1, 21)],
        }
    ],
}  # fmt: skip


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    (root / "01 Soil Report" / "soil-report.json").write_text(json.dumps(SOIL), encoding="utf-8")
    return root


def _mep(**sections: object) -> MepModel:
    return MepModel.model_validate({"schema": "saengine.mep/1", **sections})


# ───────────────────────────── loads, each item once ─────────────────────────────


def test_plant_and_electrical_equipment_load_the_model_once() -> None:
    mep = _mep(
        equipment=[
            {"id": "EQC", "kind": "chiller", "story": "L1", "x": 5000, "y": 5000,
             "length": 3000, "width": 1500, "operatingWeight": 40},
        ],
        hvac={
            "system": "vrf",
            "plant": [
                # Typical size and weight of its own 14 kW (saengine.hvac.plant.own_size).
                {"id": "ODU1", "kind": "vrfOutdoor", "story": "L1", "x": 1000, "y": 1000,
                 "capacity": 14},
                # Linked to EQC, and one standing on EQC's footprint: both are EQC's weight.
                {"id": "CH1", "kind": "chiller", "story": "L1", "x": 9000, "y": 9000,
                 "length": 3000, "width": 1500, "operatingWeight": 40, "equipment": "EQC"},
                {"id": "CH2", "kind": "chiller", "story": "L1", "x": 5200, "y": 5100,
                 "length": 3000, "width": 1500, "operatingWeight": 40},
                # Nothing to size it by: not loaded.
                {"id": "P1", "kind": "pump", "story": "BASE", "x": 0, "y": 0},
            ],
        },
        electrical={
            "equipment": [
                # 17.7 kN typical for 400 kVA (saengine.electrical.tables), oil included: SD.
                {"id": "TX1", "kind": "transformer", "story": "BASE", "x": 3000, "y": 3000,
                 "rating": 400},
                {"id": "FT1", "kind": "fuelTank", "story": "BASE", "x": 8000, "y": 3000,
                 "length": 750, "width": 750, "operatingWeight": 3.3, "emptyWeight": 0.6},
                # An electrical item whose id would give EQ-ODU1 again gets its own id.
                {"id": "ODU1", "kind": "lvPanel", "story": "BASE", "x": 12000, "y": 3000,
                 "length": 1000, "width": 600, "operatingWeight": 4},
            ]
        },
    )  # fmt: skip
    items, notes = services_equipment(mep)
    by_id = {e.id: e for e in items}
    assert sorted(by_id) == ["EQ-FT1", "EQ-ODU1", "EQ-ODU1-2", "EQ-TX1"]
    odu = by_id["EQ-ODU1"]
    assert (odu.length, odu.width, odu.operatingWeight, odu.vibrating) == (310, 760, 0.8, True)
    assert by_id["EQ-TX1"].operatingWeight == pytest.approx(17.7)
    assert by_id["EQ-TX1"].emptyWeight is None  # the oil is part of its dead load
    assert by_id["EQ-FT1"].emptyWeight == pytest.approx(0.6)  # the diesel is F
    assert by_id["EQ-ODU1-2"].kind == "other"
    text = " ".join(notes)
    assert "CH1: its weight is that of equipment EQC" in text
    assert "CH2: stands where equipment EQC is" in text
    assert "P1: no footprint or operating weight yet; not loaded" in text
    assert has_model_content(_mep(hvac={"plant": mep.hvac.plant[:1]}))


def test_an_item_whose_id_an_equipment_has_is_not_loaded_again() -> None:
    """Coordination equipment EQ-ODU1 (away from the plant's centre) is the VRF unit ODU1: it
    is not loaded a second time. Two disciplines with one id are told apart by discipline."""
    from saengine.mep.loads import services_by_discipline

    odu = {
        "id": "ODU1",
        "kind": "vrfOutdoor",
        "story": "L1",
        "x": 1000,
        "y": 1000,
        "length": 310,
        "width": 760,
        "operatingWeight": 0.8,
    }
    tx = {
        "id": "ODU1",
        "kind": "transformer",
        "story": "BASE",
        "x": 3000,
        "y": 3000,
        "length": 1200,
        "width": 800,
        "operatingWeight": 7.4,
    }
    entered = {
        "id": "EQ-ODU1",
        "name": "odu",
        "kind": "other",
        "story": "L1",
        "x": 9000,
        "y": 9000,
        "length": 300,
        "width": 300,
        "operatingWeight": 0.8,
    }
    items, notes = services_equipment(_mep(equipment=[entered], hvac={"plant": [odu]}))
    assert [e.id for e in items] == []
    assert any("ODU1: equipment EQ-ODU1 of 07 MEP has its id" in n for n in notes)
    items, _ = services_equipment(_mep(equipment=[{**entered, "id": "ODU1"}],
                                       electrical={"equipment": [tx]}))  # fmt: skip
    assert [e.id for e in items] == []
    groups, notes = services_by_discipline(
        _mep(hvac={"plant": [odu]}, electrical={"equipment": [tx]})
    )
    assert (groups["hvac"]["ODU1"].id, groups["hvac"]["ODU1"].operatingWeight) == ("EQ-ODU1", 0.8)
    assert groups["electrical"]["ODU1"].id == "EQ-ODU1-2"
    assert groups["electrical"]["ODU1"].operatingWeight == pytest.approx(7.4)
    assert "electrical: ODU1: loaded as EQ-ODU1-2 (EQ-ODU1 is the id of another item)" in notes


def test_entered_generator_and_outdoor_transformer_on_the_sample(tmp_path: Path) -> None:
    """The sample's G1 (50 kVA entered) sets the generator results: 50 x 0.8 = 40 kW, fuel
    40 x 8 h x 0.27 l/kWh = 86.4 l, Table 8.1.24's 48 kW row (24 m²); SAEngine's own 20 kVA is
    kept as proposedKva. TX1 stands outside the slabs: no room height check, a note."""
    from saengine.electrical.report import electrical_report

    report = electrical_report(_copy(tmp_path))
    gen = report["supply"]["generator"]
    assert (gen["kva"], gen["kw"], gen["proposedKva"], gen["entered"]) == (50.0, 40.0, 20.0, ["G1"])
    assert gen["fuel"] == pytest.approx(86.4)
    assert (gen["roomArea"], gen["roomRow"]) == (24.0, "1 x 48 kW")
    assert gen["tank"]["volume"] == pytest.approx(0.0864 * 1.1)
    assert any(s.startswith("Generator 50 kVA") and "fuel 86 l" in s for s in report["summary"])
    names = [c["name"] for c in report["checks"]]
    assert "TX1 room height" not in names
    assert any(n.startswith("TX1 is not under a slab") for n in report["notes"])
    tank = [e for e in report["equipment"] if e["kind"] == "fuelTank"]
    assert len(tank) == 1 and tank[0]["story"] == "BASE" and tank[0]["y"] == -3000


def test_links_to_missing_equipment_are_problems() -> None:
    mep = _mep(
        hvac={"plant": [{"id": "CH1", "kind": "chiller", "story": "L1", "x": 0, "y": 0,
                         "equipment": "NOPE"}]},
        electrical={"equipment": [{"id": "G1", "kind": "generator", "story": "L1", "x": 0,
                                   "y": 0, "equipment": "GONE"}]},
    )  # fmt: skip

    from types import SimpleNamespace

    building = SimpleNamespace(stories=[SimpleNamespace(id="L1", elevation=3200)], elements=[])
    problems = check(mep, building)
    assert "CH1: no equipment 'NOPE'" in problems
    assert "G1: no equipment 'GONE'" in problems


def test_derived_model_takes_the_plant_and_equipment(tmp_path: Path) -> None:
    """The sample's two VRF outdoor units on the roof slab (0.8 kN each, SD, with the impact
    allowance of rotating plant as L) load the derived model; the transformer and generator
    stand outside the footprint, on the ground, and do not."""
    root = _copy(tmp_path)
    args = [
        _read(root, "06 BIM/bim.json"),
        _read(root, "04 Objects/objects.json"),
        _read(root, "03 Materials/materials.json"),
        _read(root, "02 Project Settings/project-settings.json"),
        str(root / "08 FEM"),
    ]
    mep = json.loads(_read(root, "07 MEP/mep.json"))
    with_services = handlers.derive_fem(*args, mep_text=json.dumps(mep))
    bare_mep = {k: v for k, v in mep.items() if k not in ("hvac", "electrical")}
    bare = handlers.derive_fem(*args, mep_text=json.dumps(bare_mep))
    assert "text" in with_services, with_services.get("problems")

    def vertical(result: dict, case: str) -> float:
        project = json.loads(result["text"])
        pattern = next((p for p in project["load_patterns"] if p["name"] == case), None)
        return -sum(n["forces"][2] for n in pattern["nodal_loads"]) / 1e3 if pattern else 0.0

    assert vertical(with_services, "SD") - vertical(bare, "SD") == pytest.approx(1.6, abs=1e-3)
    # Light machinery: 20 % of the static load (BNBC 2020 Part 6 Table 6.2.6) as live load.
    assert vertical(with_services, "L") - vertical(bare, "L") == pytest.approx(0.32, abs=1e-3)
    notes = " ".join(with_services.get("notes") or [])
    assert "EQ-TX1: stands on the base level (on grade)" in notes


# ───────────────────────────── stamps shared with the workbench ─────────────────────────────


def test_mep_stamp_takes_the_plant_and_equipment() -> None:
    """The same text and stamps as femDerivationBar.test.ts ('stamps the HVAC plant and the
    electrical equipment')."""
    from saengine.fem.derive import mep_stamp

    text = (
        '{"schema": "saengine.mep/1", "equipment": [], "hvac": {"system": "vrf", "plant": '
        '[{"id": "ODU1", "kind": "vrfOutdoor", "story": "L1", "x": 1800, "y": 1500.5, '
        '"name": "x"}], "ducts": [{"id": "D1", "story": "BASE", "path": [[0, 0], [1, 1]]}]}, '
        '"electrical": {"supply": {"transformerType": "dry"}, "equipment": [{"id": "TX1", '
        '"kind": "transformer", "story": "BASE", "x": 3000, "y": -3000}]}}'
    )
    stamp = mep_stamp(text)
    assert mep_stamp(text.replace("1500.5", "1600")) != stamp
    assert mep_stamp(text.replace('"dry"', '"oil"')) != stamp
    assert mep_stamp(text.replace("[[0, 0], [1, 1]]", "[[0, 0], [2, 2]]")) == stamp  # ducts
    assert mep_stamp(text.replace('"name": "x"', '"name": "y"')) == stamp  # labels
    assert stamp == STAMP


#: :func:`test_mep_stamp_takes_the_plant_and_equipment`'s stamp, as the workbench computes it.
STAMP = "71aa261edebd5ae64a6f6214c92ca19c3a97322c"


# ───────────────────────────── RPC ─────────────────────────────


def test_rpc_methods_on_the_sample(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    report = handlers.hvac_report(str(root))
    assert report["zones"][0]["story"] == "BASE"
    assert report["calculated"] in (True, False) and "stamp" not in report
    air = report["air"]
    assert [c["beam"] for c in air["conflicts"]] == ["B5"]  # the supply duct under L1's slab
    assert any(c["name"] == "Ducts through beams and slabs" and not c["ok"] for c in air["checks"])
    plant = handlers.hvac_propose_plant(str(root))
    assert [p["id"] for p in plant["plant"] if p["kind"] == "vrfOutdoor"] == ["ODU1", "ODU2"]
    openings = handlers.hvac_duct_openings(str(root))
    assert openings["openings"] == [] and openings["conflicts"]
    tables = handlers.hvac_tables()
    dhaka = next(c for c in tables["cities"] if c["key"] == "dhaka")
    assert (dhaka["db"], dhaka["wb"]) == (34.5, 27.0)  # Table 8.2.2, 2 % (Sec 2.12.2.1)
    assert any(u["key"] == "officeSpace" for u in tables["uses"])
    constructions = handlers.hvac_constructions()
    assert {c["key"] for c in constructions["wall"]} >= {"brick250", "brick125"}
    assert all(0 < c["u"] < 6 for k in ("wall", "roof", "glazing") for c in constructions[k])
    uses = handlers.electrical_uses()["uses"]
    office = next(u for u in uses if u["key"] == "office")
    assert (office["nonAc"], office["ac"]) == (28, 75)  # Table 8.1.17

    electrical = handlers.electrical_report(str(root))
    columns = [d["columns"] for d in electrical["lightning"]["downConductors"]]
    assert len(columns) == 2 and all(columns)
    proposed = handlers.electrical_propose_equipment(str(root))
    assert isinstance(proposed["equipment"], list)
    missing = handlers.electrical_openings(str(root))
    assert [o["id"] for o in missing["openings"]] == ["PE-ER1-L1"]  # the busbar through S2
    assert missing["openings"][0]["host"] == "S2"
    assert handlers.hvac_report(str(root), "{")["problems"]
    assert handlers.electrical_report(str(root), "{")["problems"]


def _energyplus() -> str | None:
    from saengine.hvac.energyplus import find_energyplus

    exe = find_energyplus()
    return str(exe) if exe else None


@pytest.mark.skipif(_energyplus() is None, reason="EnergyPlus version 26.2.0 is not installed")
def test_calculate_loads_caches_and_the_report_reuses_it(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    before = handlers.hvac_report(str(root))
    assert before["engine"] == "estimate" and before["calculated"] is False
    calculated = handlers.hvac_report(str(root), calculate=True)
    assert calculated["engine"] == "EnergyPlus version 26.2.0" and calculated["calculated"]
    assert (root / "07 MEP" / "hvac.results" / "loads.json").is_file()
    after = handlers.hvac_report(str(root))
    assert after["engine"] == "EnergyPlus version 26.2.0" and after["cached"]
    assert after["total"] == pytest.approx(calculated["total"])


@pytest.mark.skipif(_energyplus() is None, reason="EnergyPlus version 26.2.0 is not installed")
def test_cancel_stops_the_energyplus_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run the editor cancels is stopped (the process killed), not left to finish."""
    import subprocess

    from saengine.hvac import energyplus as EP

    started = threading.Event()
    real = subprocess.Popen

    def slow(args, **kwargs):  # a stand-in for a long EnergyPlus run
        started.set()
        return real(["ping", "-n", "30", "127.0.0.1"] if os.name == "nt" else ["sleep", "30"],
                    **kwargs)  # fmt: skip

    monkeypatch.setattr(EP.subprocess, "Popen", slow)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            EP._run_cancellable(["x"], Path.cwd(), 60)
        except EP.EnergyPlusError as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    start = time.perf_counter()
    thread.start()
    assert started.wait(10)
    time.sleep(0.3)
    assert handlers.hvac_cancel_loads()["cancelled"] == 1
    thread.join(20)
    assert time.perf_counter() - start < 15
    assert errors and isinstance(errors[0], EP.EnergyPlusCancelled)


# ───────────────────────────── bill, IFC, report, sample ─────────────────────────────


def test_bill_of_quantities_measures_the_services() -> None:
    from saengine.boq.quantities import compute_boq

    bill = compute_boq(
        _read(SAMPLE, "06 BIM/bim.json"),
        _read(SAMPLE, "04 Objects/objects.json"),
        _read(SAMPLE, "03 Materials/materials.json"),
        _read(SAMPLE, "09 Substructure/substructure.json"),
        _read(SAMPLE, "02 Project Settings/project-settings.json"),
        _read(SAMPLE, "07 MEP/mep.json"),
    )
    items = {i["description"]: (i["quantity"], i["unit"]) for i in bill["items"]}
    # SD1 runs from x 3000 to 10500 mm; CT1 from 7000 to 12000; ER1 from BASE to L1 (3.2 m).
    assert items["Ducts, supply air, 650 x 250 mm"] == (7.5, "m")
    assert items["Cable trays 300 x 100 mm"] == (5.0, "m")
    assert items["Rising mains: busbar trunking 200 x 150 mm"] == (3.2, "m")
    assert items["HVAC plant: VRF outdoor unit"] == (2.0, "nr")
    # Two down-conductor columns: a roof and a base terminal each, and an inspection box each.
    assert items["Lightning: bonding terminals welded to the column bars (roof and base)"] == (
        4.0,
        "nr",
    )
    assert items["Lightning: earth inspection box recesses"] == (2.0, "nr")


def test_ifc_has_the_plant_ducts_trays_and_equipment(tmp_path: Path) -> None:
    result = handlers.building_ifc(
        _read(SAMPLE, "06 BIM/bim.json"),
        _read(SAMPLE, "04 Objects/objects.json"),
        _read(SAMPLE, "03 Materials/materials.json"),
        "Sample",
        mep_text=_read(SAMPLE, "07 MEP/mep.json"),
    )
    path = tmp_path / "model.ifc"
    path.write_text(result["text"], encoding="utf-8")
    model = ifcopenshell.open(str(path))

    def tags(ifc_class: str) -> list[tuple[str, str]]:
        return sorted((e.Tag, e.PredefinedType) for e in model.by_type(ifc_class))

    assert tags("IfcUnitaryEquipment") == [("ODU1", "SPLITSYSTEM"), ("ODU2", "SPLITSYSTEM")]
    assert tags("IfcDuctSegment") == [("SD1", "RIGIDSEGMENT")]
    assert tags("IfcTransformer") == [("TX1", "VOLTAGE")]
    assert tags("IfcElectricGenerator") == [("G1", "ENGINEGENERATOR")]
    assert tags("IfcCableSegment") == [("ER1", "BUSBARSEGMENT")]
    assert tags("IfcCableCarrierSegment") == [("CT1", "CABLETRAYSEGMENT")]
    assert {"ODU1", "SD1", "TX1", "ER1", "CT1"} <= set(result["ids"])


def test_report_chapters(tmp_path: Path) -> None:
    from saengine.report.build import _electrical, _hvac, _Parts

    root = _copy(tmp_path)
    hvac = _hvac(_Parts(root, []))
    assert hvac["available"] and hvac["failed"] >= 1
    assert [row[0] for row in hvac["plant"]] == ["ODU1", "ODU2"]
    assert hvac["plant"][0][-1] == "0.8 kN SD, impact L"
    assert hvac["conflicts"][0][:2] == ["SD1", "B5"]
    assert "raise the floor above" in hvac["conflicts"][0][3]
    electrical = _electrical(_Parts(root, []))
    assert electrical["available"]
    assert len(electrical["lightning"]["conductors"]) == 2
    assert any("Down-conductor column lines" in n for n in electrical["lightning"]["structural"])
    assert [row[0] for row in electrical["equipment"]] == ["TX1", "G1"]
    assert [row[0] for row in electrical["openings"]] == ["PE-ER1-L1"]


def test_the_sample_has_hvac_and_electrical() -> None:
    from saengine.library.bim import BuildingModel
    from saengine.library.mep import parse

    mep = parse(_read(SAMPLE, "07 MEP/mep.json"))
    building = BuildingModel.model_validate_json(_read(SAMPLE, "06 BIM/bim.json"))
    assert check(mep, building) == []
    assert mep.hvac.system == "vrf"
    assert [(p.id, p.kind, p.story) for p in mep.hvac.plant] == [
        ("ODU1", "vrfOutdoor", "L1"),
        ("ODU2", "vrfOutdoor", "L1"),
    ]
    assert [(d.id, d.system, d.story) for d in mep.hvac.ducts] == [("SD1", "supply", "BASE")]
    kinds = [(e.id, e.kind, e.story) for e in mep.electrical.equipment]
    assert kinds == [("TX1", "transformer", "BASE"), ("G1", "generator", "BASE")]
    assert [r.kind for r in mep.electrical.risers] == ["busbar"]
    lightning = mep.electrical.lightning
    assert lightning.enabled and lightning.downConductors == "structuralRebar"
    # No cache of a load calculation is shipped.
    assert not (SAMPLE / "07 MEP" / "hvac.results").exists()


def test_the_backend_finds_the_bundled_energyplus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installer copies EnergyPlus to <app>/resources/energyplus, next to the bundled
    Python in <app>/resources/python (scripts/installer/energyplus_runtime.py)."""
    import sys

    from saengine.hvac import energyplus as EP

    python = tmp_path / "resources" / "python" / "python.exe"
    bundled = tmp_path / "resources" / "energyplus" / EP.EXE
    for path in (python, bundled):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    monkeypatch.delenv(EP.ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "executable", str(python))
    assert EP.find_energyplus() == bundled
