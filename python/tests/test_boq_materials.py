"""The BOQ's materials take-off: cement in kg and bags, sand and stone chips in cft, water in
litres, from the mixes of 03 Materials (hand-checked)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.boq.quantities import (
    BRICKWORK_WET_MORTAR,
    CEMENT_BAG,
    CEMENT_DENSITY,
    CFT,
    DRY_VOLUME_CONCRETE,
    DRY_VOLUME_MORTAR,
    SAND_DENSITY,
    STONE_DENSITY,
    _Measure,
    compute_boq,
)
from saengine.library.materials import DesignMix, NominalMix

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def _measure() -> _Measure:
    return _Measure.__new__(_Measure)  # mix_quantities needs no project


def test_nominal_concrete_mix_by_hand() -> None:
    # 1 m³ of 1:2:4 concrete, w/c 0.5: dry volume 1.54 m³ shared 1/7, 2/7, 4/7.
    out = _measure().mix_quantities(
        NominalMix(ratio=[1, 2, 4], waterCement=0.5), 1.0, DRY_VOLUME_CONCRETE
    )
    cement = 1.54 / 7 * 1440
    assert out == pytest.approx(
        {"cement": cement, "sand": 1.54 * 2 / 7, "stone": 1.54 * 4 / 7, "water": 0.5 * cement}
    )
    assert cement == pytest.approx(316.8)  # 6.34 bags of 50 kg per m³


def test_design_mix_by_hand() -> None:
    mix = DesignMix(cement=380, water=171, fineAggregate=720, coarseAggregate=1100)
    out = _measure().mix_quantities(mix, 2.0, DRY_VOLUME_CONCRETE)
    assert out == pytest.approx(
        {
            "cement": 760,
            "water": 342,
            "sand": 1440 / SAND_DENSITY,
            "stone": 2200 / STONE_DENSITY,
        }
    )


def test_mortar_mix_by_hand() -> None:
    # 1 m³ of brickwork: 0.23 m³ of wet 1:4 mortar, dry volume x 1.30, shared 1/5, 4/5.
    wet = BRICKWORK_WET_MORTAR
    out = _measure().mix_quantities(NominalMix(ratio=[1, 4]), wet, DRY_VOLUME_MORTAR)
    assert out == pytest.approx(
        {"cement": wet * 1.3 / 5 * CEMENT_DENSITY, "sand": wet * 1.3 * 4 / 5}
    )


def test_masonry_takes_its_mortar_and_a_concrete_without_a_mix_gets_an_assumed_one() -> None:
    m = _Measure.__new__(_Measure)
    m.materials = {
        "BRICK": SimpleNamespace(id="BRICK", masonry=SimpleNamespace(mortar="M14")),
        "M14": SimpleNamespace(id="M14", composition=NominalMix(ratio=[1, 4])),
        "C30": SimpleNamespace(id="C30", composition=None, concrete=SimpleNamespace(fc=30.0)),
        "BRICK2": SimpleNamespace(id="BRICK2", masonry=SimpleNamespace(mortar=None)),
    }
    from saengine.boq.quantities import _Bill

    m.bill = _Bill()
    m.notes = []
    m.unreinforced = {}
    m.bill.add(
        "masonry", (1, "BRICK"), "Masonry BRICK in walls", "m3", "W1", 10.0, material="BRICK"
    )
    m.bill.add(
        "masonry", (2, "BRICK2"), "Masonry BRICK2 in walls", "m3", "W2", 1.0, material="BRICK2"
    )
    m.bill.add("concrete", (1, "C30"), "Concrete C30 in slabs", "m3", "S1", 5.0, material="C30")
    m.measure_materials()
    items = {i.description: i.quantity for i in m.bill.items()}
    mortar = 10 * BRICKWORK_WET_MORTAR * DRY_VOLUME_MORTAR
    dry = 5 * DRY_VOLUME_CONCRETE  # f'c 30 MPa: 1:1.5:3 assumed (IS 456:2000 Table 9, M20)
    cement = mortar / 5 * CEMENT_DENSITY + dry / 5.5 * CEMENT_DENSITY
    assert items == pytest.approx(
        {
            "Cement": cement,
            f"Cement in {CEMENT_BAG:g} kg bags": cement / CEMENT_BAG,
            "Sand (fine aggregate)": (mortar * 4 / 5 + dry * 1.5 / 5.5) * CFT,
            "Stone chips (coarse aggregate)": dry * 3 / 5.5 * CFT,
            "Masonry BRICK in walls": 10.0,
            "Masonry BRICK2 in walls": 1.0,
            "Concrete C30 in slabs": 5.0,
        },
        abs=1e-3,  # the bill rounds to 3 decimals
    )
    assert m.notes == [
        (
            "Materials: concrete C30 has no mix: 1:1.5:3 assumed (f'c 30 MPa), a nominal mix of "
            "IS 456:2000 Table 9 by strength, no water (enter the mix in 03 Materials to replace "
            "it)."
        ),
        (
            "Materials: masonry BRICK2: its mortar is not named, so no cement, sand or stone is "
            "taken off for it (add the mix in 03 Materials)."
        ),
    ]
    # The assumed mix is a note; the mortar with no mix leaves the bill incomplete.
    assert m.problems() == [
        (
            "No cement or sand for masonry BRICK2: its mortar is not named (add the mix in 03 "
            "Materials)."
        )
    ]


def test_assumed_mixes_by_strength() -> None:
    from saengine.boq.quantities import assumed_mix

    def ratio(fc: float) -> list[float]:
        return assumed_mix(SimpleNamespace(concrete=SimpleNamespace(fc=fc))).ratio

    assert [ratio(10), ratio(15), ratio(20.7), ratio(27.6)] == [
        [1, 3, 6],
        [1, 2, 4],
        [1, 1.5, 3],
        [1, 1.5, 3],
    ]


def test_the_sample_bill_takes_off_its_concrete() -> None:
    def read(rel: str) -> str:
        return (SAMPLE / rel).read_text(encoding="utf-8")

    bill = compute_boq(
        read("06 BIM/bim.json"),
        read("04 Objects/objects.json"),
        read("03 Materials/materials.json"),
        read("09 Substructure/substructure.json"),
        read("02 Project Settings/project-settings.json"),
        read("07 MEP/mep.json"),
    )
    items = bill["items"]
    # The sample's frame concrete is C24.1, a 1:1.5:3 nominal mix (5.5 parts); its tank concrete
    # C27.6 has no mix, and 1:1.5:3 is assumed for it (IS 456:2000 Table 9 by strength).
    volume = {
        m: sum(i["quantity"] for i in items if i["group"] == "concrete" and i.get("material") == m)
        for m in ("C24.1", "C27.6")
    }
    dry = (volume["C24.1"] + volume["C27.6"]) * DRY_VOLUME_CONCRETE
    materials: dict[str, tuple[float, str]] = {}
    for i in items:
        if i["group"] == "materials":
            total, _ = materials.get(i["kind"], (0.0, ""))
            materials[i["kind"]] = (total + i["quantity"], i["unit"])
    assert materials["cement"] == (pytest.approx(dry / 5.5 * CEMENT_DENSITY, rel=1e-3), "kg")
    assert materials["bags"] == (pytest.approx(dry / 5.5 * CEMENT_DENSITY / 50, rel=1e-3), "bag")
    assert materials["sand"] == (pytest.approx(dry * 1.5 / 5.5 * CFT, rel=1e-3), "cft")
    assert materials["stone"] == (pytest.approx(dry * 3 / 5.5 * CFT, rel=1e-3), "cft")
    assert materials["water"][1] == "l"
    assert any("C27.6 has no mix: 1:1.5:3 assumed" in n for n in bill["notes"])
