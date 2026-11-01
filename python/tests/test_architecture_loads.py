"""Loads of the architecture on the analysis model (saengine.fem.architecture_loads), checked by
hand on the one-bay frame of test_line_loads (A-B 6 m along x, 1-2 5 m along y, 3.2 m stories,
beams 300 x 500, slab 150 mm, area load FL: finish 1.2, partitions 1.0, live 2.0 kN/m²)."""

from __future__ import annotations

from typing import Any

import pytest
from test_line_loads import OBJECTS, _applied, plan

from saengine.fem import architecture_loads as al
from saengine.fem.derive import derive_fem
from saengine.library import architecture as arch_lib
from saengine.library import default_material_library
from saengine.library.bim import generate
from saengine.library.settings import default_project_settings

PLASTER = {"material": "Cement plaster", "thickness": 12.5, "unitWeight": 23.0}
#: BNBC Table 6.2.2 (p. 530-531): brick 1.910 kN/m² per 100 mm, plaster 0.230 per 10 mm:
#: B250 = 0.25 × 19.1 + 2 × 0.0125 × 23 = 4.775 + 0.575 = 5.35 kN/m²;
#: B125 = 0.125 × 19.1 + 0.575 = 2.3875 + 0.575 = 2.9625 kN/m².
WALL_TYPES = [
    {
        "id": "B250",
        "name": "250 mm brick, plastered",
        "layers": [PLASTER, {"material": "Brick", "thickness": 250, "unitWeight": 19.1}, PLASTER],
    },
    {
        "id": "B125",
        "name": "125 mm brick, plastered",
        "layers": [PLASTER, {"material": "Brick", "thickness": 125, "unitWeight": 19.1}, PLASTER],
    },
]
#: 50 mm screed + 10 mm tiles, both taken at 21 kN/m³: 0.060 × 21 = 1.26 kN/m².
FINISH = {"id": "SCT", "name": "Screed + tiles", "kind": "floor", "thickness": 60, "unitWeight": 21}
#: A bay-wide frame of room separators on L1, and one at x = 4 m: rooms of 4 x 5 m and 2 x 5 m.
SEPARATORS = [
    {"id": f"RS{k}", "story": "L1", "start": a, "end": b}
    for k, (a, b) in enumerate(
        [
            ([0, 0], [6000, 0]),
            ([6000, 0], [6000, 5000]),
            ([6000, 5000], [0, 5000]),
            ([0, 5000], [0, 0]),
            ([4000, 0], [4000, 5000]),
        ]
    )
]


def architecture(**parts: Any) -> arch_lib.Architecture:
    return arch_lib.Architecture.model_validate(
        {
            "wallTypes": WALL_TYPES,
            "doorTypes": [{"id": "D1", "name": "Door", "width": 1000, "height": 2100}],
            "finishTypes": [FINISH],
            **parts,
        }
    )


def derived(
    arch: arch_lib.Architecture | None, slabs: str = "loadsToBeams", mode: str | None = None
):
    settings = default_project_settings("Bay")
    update: dict[str, Any] = {"slabs": slabs}
    if mode:
        update["partitionLoads"] = mode
    settings = settings.model_copy(update={"analysis": settings.analysis.model_copy(update=update)})
    building = generate(plan(2), "s")
    return derive_fem(
        building,
        OBJECTS,
        default_material_library(),
        settings,
        {"bim": "abc"},
        architecture=arch if arch is not None else False,
    )


def sd(derivation: Any) -> float:
    """Total SD applied, kN (down positive)."""
    return -_applied(derivation.project, "SD") / 1e3


def live(derivation: Any) -> float:
    return -_applied(derivation.project, "L") / 1e3


WALL_ON_BEAM = {
    "walls": [
        {"id": "W1", "type": "B250", "base": "L1", "height": 3000, "path": [[0, 0], [6000, 0]]}
    ],
    "doors": [{"id": "DR1", "type": "D1", "wall": "W1", "offset": 3000}],
}


def test_wall_on_a_6_m_beam_with_a_door_by_hand() -> None:
    # 5.35 kN/m² × (3.0 m × 6.0 m − 1.0 × 2.1 m door) / 6.0 m = 5.35 × 15.9 / 6 = 14.1775 kN/m,
    # 85.065 kN on B11 (the wall's height is given: no beam is deducted).
    arch = architecture(**WALL_ON_BEAM)
    loads = al.architecture_loads(arch, generate(plan(2), "s"), OBJECTS)
    [line] = loads.lines
    assert line.member == "B11" and line.case == "SD"
    assert line.load / 1e3 == pytest.approx(14.1775, rel=1e-9)
    [row] = loads.wall_rows
    assert row["on"] == "beam" and row["openings_m2"] == pytest.approx(2.1)
    assert row["total_kN"] == pytest.approx(85.065, abs=1e-3)
    # In the model: + 85.065 kN of SD, less the L1 slab's partition allowance (1.2 kN/m², the
    # least of BNBC 2020 Part 6 Sec 2.3.6, over 6 × 5 = 30 m² = 36 kN, dropped where walls are
    # drawn, never both): + 49.065 kN against the allowance alone; the seismic weight takes SD
    # in full.
    with_walls = derived(arch)
    allowance = derived(arch, mode="allowance")
    assert sd(with_walls) - sd(allowance) == pytest.approx(85.065 - 36.0, rel=1e-6)
    assert with_walls.summary["weight_kN"] - allowance.summary["weight_kN"] == pytest.approx(
        85.065 - 36.0, rel=1e-3
    )
    rows = with_walls.summary["architectureLoads"]
    assert rows["walledStories"] == ["L1"] and rows["walls"][0]["member"] == "B11"
    assert "architectureLoads" not in derived(None).summary


def test_clear_height_deducts_the_beam_above() -> None:
    # To story L2: 3200 − the 500 mm beam B21 above = 2700 mm; 5.35 × 2.7 = 14.445 kN/m.
    arch = architecture(
        walls=[{"id": "W1", "type": "B250", "base": "L1", "top": "L2", "path": [[0, 0], [6000, 0]]}]
    )
    [line] = al.architecture_loads(arch, generate(plan(2), "s"), OBJECTS).lines
    assert line.load / 1e3 == pytest.approx(5.35 * 2.7, rel=1e-9)


def test_wall_across_the_slab() -> None:
    # B125, 3.0 m high, across the bay at x = 3 m: 2.9625 × 3.0 = 8.8875 kN/m, 44.4375 kN in
    # all. Its ends cross B11 and B13 (half the 300 mm beam + 25 mm: 175 mm each), each a point
    # load of 0.175 × 8.8875 = 1.555 kN at mid-span.
    arch = architecture(
        walls=[
            {
                "id": "P1",
                "type": "B125",
                "base": "L1",
                "height": 3000,
                "path": [[3000, 0], [3000, 5000]],
            }
        ]
    )
    loads = al.architecture_loads(arch, generate(plan(2), "s"), OBJECTS)
    assert not loads.lines
    assert sorted(p.member for p in loads.points) == ["B11", "B13"]
    assert [p.force / 1e3 for p in loads.points] == pytest.approx([0.175 * 8.8875] * 2)
    assert loads.points[0].at[:2] == pytest.approx((3.0, 0.0))
    [on_slab] = loads.slabs
    assert on_slab.slab == "S1"
    assert on_slab.load * 4.65 / 1e3 == pytest.approx(8.8875 * 4.65, rel=1e-9)
    # Heavier than a light partition (5.5 kN/m): noted.
    assert any("light partition" in note for note in loads.notes)
    base = derived(None)
    # Slabs as loads to beams: the panel takes max(41.33 kN / 30 m² = 1.378, 0.33 × 8.8875 =
    # 2.933) kN/m² (BNBC Sec 2.3.6) = 87.99 kN, the beams 2 × 0.175 × 8.8875 = 3.111 kN; the
    # 36 kN partition allowance (1.2 kN/m² × 30 m²) goes.
    beams = derived(arch)
    assert sd(beams) - sd(base) == pytest.approx(0.33 * 8.8875 * 30 + 0.35 * 8.8875 - 36, rel=1e-6)
    # Shells: the wall is a line load on the shells, its weight exact: 44.4375 − 36 kN.
    shells = derived(arch, "shells")
    assert sd(shells) - sd(derived(None, "shells")) == pytest.approx(44.4375 - 36, rel=1e-6)


def test_room_finish_replaces_the_flat_finish() -> None:
    # Room 4 x 5 m with 50 mm screed + 10 mm tiles (1.26 kN/m²) instead of the flat 1.2:
    # 20 × (1.26 − 1.2) = + 1.2 kN of SD; the rest of the panel (10 m²) keeps 1.2.
    arch = architecture(
        separators=SEPARATORS,
        rooms=[{"id": "R1", "story": "L1", "point": [2000, 2500], "floorFinish": "SCT"}],
    )
    for slabs in ("loadsToBeams", "shells"):
        assert sd(derived(arch, slabs)) - sd(derived(None, slabs)) == pytest.approx(1.2, abs=1e-4)
    [row] = derived(arch).summary["architectureLoads"]["rooms"]
    assert row["area_m2"] == pytest.approx(20.0) and row["finish_kNm2"] == pytest.approx(1.26)


def test_sunk_filling_in_a_wet_room() -> None:
    # A 250 mm sunk slab filled at 16 kN/m³: + 4.0 kN/m² in the wet room only.
    finish = {**FINISH, "sunkFilling": 250}
    arch = arch_lib.Architecture.model_validate(
        {
            "wallTypes": WALL_TYPES,
            "finishTypes": [finish],
            "separators": SEPARATORS,
            "rooms": [
                {
                    "id": "T1",
                    "story": "L1",
                    "point": [5000, 2500],
                    "floorFinish": "SCT",
                    "wet": True,
                },
                {"id": "R1", "story": "L1", "point": [2000, 2500], "floorFinish": "SCT"},
            ],
        }
    )
    loads = al.architecture_loads(arch, generate(plan(2), "s"), OBJECTS)
    weights = {room.room: room.finish for room in loads.rooms}
    assert weights == pytest.approx({"T1": 1.26 + 4.0, "R1": 1.26})


def test_office_room_on_a_residential_floor() -> None:
    # Office (BNBC Table 6.2.3: 2.4 kN/m²) on 4 x 5 m of a residential floor (2.0):
    # L = 20 × 2.4 + 10 × 2.0 = 68 kN instead of 30 × 2.0 = 60 kN.
    arch = architecture(
        separators=SEPARATORS,
        rooms=[{"id": "R1", "story": "L1", "point": [2000, 2500], "occupancy": "office"}],
    )
    for slabs in ("loadsToBeams", "shells"):
        assert live(derived(arch, slabs)) - live(derived(None, slabs)) == pytest.approx(
            8.0, abs=1e-4
        )


def test_wall_over_a_floor_plan_wall_is_not_counted_twice() -> None:
    from saengine.library import FloorPlan

    data = plan(2).model_dump(mode="json", by_alias=True)
    data["walls"] = [
        {
            "id": "FW1",
            "type": "WL",
            "base": "L1",
            "top": "L2",
            "start": {"x": "A", "y": "1"},
            "end": {"x": "B", "y": "1"},
        }
    ]
    objects = OBJECTS.model_validate(
        {
            "objects": [
                *[o.model_dump(mode="json") for o in OBJECTS.objects],
                {"id": "WL", "name": "Wall", "kind": "wall", "material": "C24.1", "thickness": 200},
            ]
        }
    )
    building = generate(FloorPlan.model_validate(data), "s")
    arch = architecture(**WALL_ON_BEAM)
    loads = al.architecture_loads(arch, building, objects)
    assert not loads.lines and [r["on"] for r in loads.wall_rows] == ["structural"]
    referenced = architecture(
        walls=[
            {**WALL_ON_BEAM["walls"][0], "path": [[0, 2500], [6000, 2500]], "structuralRef": "FW1"}
        ]
    )
    loads = al.architecture_loads(referenced, building, objects)
    assert not loads.lines and not loads.slabs
    # Nor measured twice: the floor-plan wall stays in the bill as before, no brickwork for W1.
    from saengine.boq.quantities import bill_of_quantities

    bill = bill_of_quantities(building, objects, default_material_library(), architecture=arch)
    assert not [i for i in bill.items if i.description.startswith("Brickwork")]
    assert any(
        "FW1" in {e.element for e in i.breakdown} for i in bill.items if i.group == "concrete"
    )


# ── the bill of quantities (saengine.boq.architecture) ──


def test_boq_brickwork_plaster_finishes_and_doors_by_hand() -> None:
    from saengine.boq.quantities import bill_of_quantities

    arch = arch_lib.Architecture.model_validate(
        {
            "wallTypes": WALL_TYPES,
            "doorTypes": [{"id": "D1", "name": "Door", "width": 1000, "height": 2100}],
            "finishTypes": [
                FINISH,
                {
                    "id": "CEIL",
                    "name": "Ceiling plaster",
                    "kind": "ceiling",
                    "thickness": 6,
                    "unitWeight": 20.4,
                },
                {"id": "PNT", "name": "Paint", "kind": "wall", "thickness": 1, "unitWeight": 10},
            ],
            **WALL_ON_BEAM,
            "separators": SEPARATORS,
            "rooms": [
                {
                    "id": "R1",
                    "story": "L1",
                    "point": [2000, 2500],
                    "floorFinish": "SCT",
                    "ceilingFinish": "CEIL",
                    "wallFinish": "PNT",
                }
            ],
        }
    )
    bill = bill_of_quantities(
        generate(plan(2), "s"), OBJECTS, default_material_library(), architecture=arch
    )
    items = {i.description: i for i in bill.items}

    def quantity(start: str) -> float:
        return sum(i.quantity for d, i in items.items() if d.startswith(start))

    # W1: 6.0 × 3.0 = 18 m² gross, less the 2.1 m² door (> 0.1 m²): 15.9 m² × 0.25 m = 3.975 m³.
    assert quantity("Brickwork: Brick 250 mm") == pytest.approx(3.975, abs=1e-3)
    # Plaster 12.5 mm: the door (0.5 to 3 m²) off one face only: 15.9 + 18.0 = 33.9 m².
    assert quantity("Cement plaster 12.5 mm") == pytest.approx(33.9, abs=1e-3)
    # R1's net floor: 4.0 × (5.0 − 0.1375, the half of W1's 275 mm inside it) = 19.45 m².
    assert quantity("Floor finish: Screed + tiles") == pytest.approx(19.45, abs=1e-3)
    assert quantity("Ceiling: Ceiling plaster") == pytest.approx(19.45, abs=1e-3)
    # Its walls: 2 × (4.0 + 4.8625) = 17.725 m × (3.2 − 0.15 slab) = 54.061 m², less the door
    # 2.1 m²: 51.961 m².
    assert quantity("Wall finish: Paint") == pytest.approx(17.725 * 3.05 - 2.1, abs=1e-3)
    assert quantity("Door D1") == 1
    # Cement: brickwork mortar 3.975 × 0.23 × 1.30 / 5 × 1440 = 342.295 kg; plaster mortar (the
    # brick's M1-4) 33.9 × 0.0125 × 1.30 / 5 × 1440 = 158.652 kg.
    cement = next(i for d, i in items.items() if d.startswith("Cement") and i.unit == "kg")
    assert sum(e.quantity for e in cement.breakdown if e.element == "W1") == pytest.approx(
        342.295 + 158.652, abs=0.01
    )
    assert any("IS 1200" in note for note in bill.notes)
