"""Line and point loads on members (05 Floor Plan/loads.json): hand calculations, typical floors,
and the loads reaching the analysis model."""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from saengine.fem import member_loads as ml
from saengine.fem.end_zones import element_offsets
from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan, default_material_library
from saengine.library import line_loads as ll
from saengine.library.bim import generate
from saengine.library.settings import default_project_settings

OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "COL",
                "name": "Column 400x400",
                "kind": "column",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
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


def plan(levels: int = 1, typical: bool = False) -> FloorPlan:
    """One bay (A-B 6 m, 1-2 5 m), ``levels`` stories of 3.2 m; with ``typical`` the stories
    above L1 repeat it. Beam ids: B<story><edge>, B1 of each story from A-1 to B-1."""
    base = default_floor_plan().model_dump(mode="json", by_alias=True)
    stories = [{"id": "BASE", "name": "Base", "elevation": 0}] + [
        {
            "id": f"L{k}",
            "name": f"Level {k}",
            "elevation": 3200 * k,
            **({"similarTo": "L1"} if typical and k > 1 else {}),
        }
        for k in range(1, levels + 1)
    ]
    ids = ["BASE"] + [f"L{k}" for k in range(1, levels + 1)]
    return FloorPlan.model_validate(
        {
            **base,
            "stories": stories,
            "columns": [
                {
                    "id": f"C{k}{i + 1}",
                    "type": "COL",
                    "at": {"x": x, "y": y},
                    "base": ids[k - 1],
                    "top": ids[k],
                }
                for k in range(1, levels + 1)
                for i, (x, y) in enumerate(CORNERS)
            ],
            "beams": [
                {
                    "id": f"B{k}{i + 1}",
                    "type": "BM",
                    "story": f"L{k}",
                    "start": {"x": a[0], "y": a[1]},
                    "end": {"x": b[0], "y": b[1]},
                }
                for k in range(1, levels + 1)
                for i, (a, b) in enumerate(zip(CORNERS, CORNERS[1:] + CORNERS[:1], strict=True))
            ],
            "slabs": [
                {
                    "id": f"S{k}",
                    "type": "SL",
                    "story": f"L{k}",
                    "boundary": [{"x": x, "y": y} for x, y in CORNERS],
                }
                for k in range(1, levels + 1)
            ],
        }
    )


def loads(*items: dict) -> ll.MemberLoads:
    return ll.MemberLoads.model_validate(
        {
            "wallTypes": [w.model_dump() for w in ll.default_wall_types()],
            "loads": list(items),
        }
    )


# ── values by hand ──


def test_wall_types_from_bnbc_table_6_2_2() -> None:
    types = {w.id: w for w in ll.default_wall_types()}
    # Brick (burnt clay) 1.910 kN/m² per 100 mm, cement plaster 0.230 kN/m² per 10 mm, 12.5 mm
    # on both faces.
    assert types["BW250"].weight_per_area() == pytest.approx(1.910 * 2.5 + 0.230 * 2.5)
    assert types["BW125"].weight_per_area() == pytest.approx(1.910 * 1.25 + 0.230 * 2.5)


def test_line_load_from_a_wall_by_hand() -> None:
    model = loads(
        {
            "id": "W1",
            "story": "L1",
            "member": "B11",
            "wall": {"type": "BW250", "height": 2700, "openings": 20},
        },
        {"id": "W2", "story": "L1", "member": "B12", "value": 7.5, "case": "D"},
    )
    wall, explicit = model.loads
    # (19.1 kN/m³ x 0.25 m + 23 kN/m³ x 2 x 0.0125 m) x 2.7 m x (1 - 0.20) = 11.556 kN/m
    assert ll.line_value(wall, model) == pytest.approx(5.35 * 2.7 * 0.8)
    assert ll.line_value(explicit, model) == 7.5
    assert wall.case == "SD"  # superimposed dead by default
    assert ll.describe(wall, model) == "BW250 × 2.7 m − 20 % = 11.56 kN/m"


def test_invalid_loads_are_refused() -> None:
    with pytest.raises(ValidationError, match="either a wall or a value"):
        loads({"id": "X", "story": "L1", "member": "B11"})
    with pytest.raises(ValidationError, match="either a wall or a value"):
        loads(
            {
                "id": "X",
                "story": "L1",
                "member": "B11",
                "value": 3,
                "wall": {"type": "BW125", "height": 3000},
            }
        )
    with pytest.raises(ValidationError, match="no wall type 'BW300'"):
        loads({"id": "X", "story": "L1", "member": "B11", "wall": {"type": "BW300", "height": 1}})
    with pytest.raises(ValidationError, match="duplicate load ids"):
        loads(
            {"id": "X", "story": "L1", "member": "B11", "value": 1},
            {"id": "X", "story": "L1", "member": "B12", "value": 1},
        )
    with pytest.raises(ValidationError):
        loads({"id": "X", "story": "L1", "member": "B11", "value": 1, "case": "EX"})
    assert ll.parse(None).loads == [] and ll.parse("  ").loads == []


def test_check_against_the_floor_plan() -> None:
    model = loads(
        {"id": "A", "story": "L1", "member": "B11", "value": 1},
        {"id": "B", "story": "L2", "member": "B11", "value": 1},
        {"id": "C", "story": "L1", "member": "B99", "value": 1},
        {"id": "D", "story": "L1", "member": "C11", "kind": "point", "value": 5},
        {"id": "E", "story": "L2", "member": "C11", "kind": "point", "value": 5},
    )
    problems = ll.check(model, plan(levels=2))
    assert problems == [
        "B: beam B11 is not on story L2",
        "C: no beam 'B99'",
        "E: column C11 does not reach L2",
    ]


# ── typical floors ──


def test_loads_follow_typical_floors() -> None:
    building = generate(plan(levels=3, typical=True), "s")
    model = loads(
        {"id": "ON-MASTER", "story": "L1", "member": "B11", "value": 10},
        # Entered on a similar story: the whole family too.
        {"id": "ON-SIMILAR", "story": "L2", "member": "B22", "value": 4},
        {"id": "ONLY", "story": "L3", "member": "B33", "value": 2, "thisStoryOnly": True},
        {
            "id": "P",
            "story": "L1",
            "member": "B11",
            "kind": "point",
            "value": 20,
            "distance": 1500,
        },
    )
    out = ml.member_loads(building, model)
    by_source: dict[str, list[ml.MemberLineLoad]] = {}
    for line in out.lines:
        by_source.setdefault(line.source, []).append(line)
    assert sorted(line.member for line in by_source["ON-MASTER"]) == ["B11", "B21", "B31"]
    assert sorted(line.member for line in by_source["ON-SIMILAR"]) == ["B12", "B22", "B32"]
    assert [line.member for line in by_source["ONLY"]] == ["B33"]
    assert sorted(line.start[2] for line in by_source["ON-MASTER"]) == pytest.approx(
        [3.2, 6.4, 9.6]
    )
    points = sorted(out.points, key=lambda p: p.at[2])
    assert [(p.member, p.at) for p in points] == [
        ("B11", pytest.approx((1.5, 0.0, 3.2))),
        ("B21", pytest.approx((1.5, 0.0, 6.4))),
        ("B31", pytest.approx((1.5, 0.0, 9.6))),
    ]
    # 6 m x 10 kN/m x 3 + 5 m x 4 kN/m x 3 + 6 m x 2 kN/m + 3 x 20 kN
    assert out.totals() == {"SD": pytest.approx(180 + 60 + 12 + 60)}
    assert not out.notes


def test_no_typical_floor_means_its_own_story() -> None:
    building = generate(plan(levels=2), "s")
    out = ml.member_loads(building, loads({"id": "A", "story": "L1", "member": "B11", "value": 1}))
    assert [line.member for line in out.lines] == ["B11"]
    out = ml.member_loads(building, loads({"id": "A", "story": "L1", "member": "NOPE", "value": 1}))
    assert out.notes == ["A: no beam 'NOPE' in the model; not applied"]


# ── point loads on nodes ──


def test_point_shares_exact_and_lever_rule() -> None:
    point = ml.MemberPointLoad(
        "P", "B", "L1", "SD", (1.5, 0.0, 3.2), 1000.0, ((0, 0, 3.2), (6, 0, 3.2))
    )
    coords = {1: (0, 0, 3.2), 2: (2.0, 0, 3.2), 3: (6, 0, 3.2), 4: (1.5, 3, 3.2)}
    shares, exact = ml.point_shares(point, coords)
    assert not exact and shares == [(1, pytest.approx(0.25)), (2, pytest.approx(0.75))]
    shares, exact = ml.point_shares(point, {**coords, 9: (1.5, 0, 3.2)})
    assert exact and shares == [(9, 1.0)]
    assert ml.point_shares(point, {4: (1.5, 3, 3.2)}) == ([], False)


def test_split_points_and_lines() -> None:
    building = generate(plan(), "s")
    model = loads(
        {"id": "P1", "story": "L1", "member": "B11", "kind": "point", "value": 5, "distance": 4000},
        {"id": "P2", "story": "L1", "member": "B11", "kind": "point", "value": 5, "distance": 1000},
        {"id": "P3", "story": "L1", "member": "B11", "kind": "point", "value": 5, "distance": 0},
        {"id": "J", "story": "L1", "member": "C11", "kind": "point", "value": 5},
    )
    out = ml.member_loads(building, model)
    cuts = ml.split_points(out)
    assert cuts == {"B11": [(1000.0, 0.0, 3200.0), (4000.0, 0.0, 3200.0)]}
    segments = ml.split_line((0, 0, 3200), (6000, 0, 3200), cuts["B11"])
    assert [s[1][0] for s in segments] == pytest.approx([1000, 4000, 6000])
    joint = next(p for p in out.points if p.source == "J")
    assert joint.along is None and joint.at == pytest.approx((0, 0, 3.2))


def test_apply_through_derive_helpers() -> None:
    building = generate(plan(), "s")
    out = ml.member_loads(
        building,
        loads(
            {"id": "W", "story": "L1", "member": "B11", "value": 10},
            {
                "id": "P",
                "story": "L1",
                "member": "B11",
                "kind": "point",
                "value": 8,
                "distance": 3000,
            },
        ),
    )
    lines: list[tuple] = []
    nodal: list[tuple] = []
    coords = {1: (0, 0, 3.2), 2: (6, 0, 3.2)}
    notes = ml.apply(
        out,
        coords,
        lambda *args: lines.append(args) or True,
        lambda *args: nodal.append(args),
    )
    assert [(s, c, w) for s, c, _, _, w in lines] == [("W", "SD", 10_000.0)]
    assert nodal == [("SD", 1, pytest.approx(4000.0), 3.2), ("SD", 2, pytest.approx(4000.0), 3.2)]
    assert notes == [
        (
            "P: no node at the point on B11; shared between the nodes either side (its local "
            "moment is approximate)"
        )
    ]


# ── the analysis model ──


def _applied(project: dict, name: str) -> float:
    """Total vertical force of a pattern (N, up positive), as test_fem_derive.applied."""
    coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    elements = {e["id"]: e for e in project["elements"]}
    pattern = next(p for p in project["load_patterns"] if p["name"] == name)
    total = sum(n["forces"][2] for n in pattern["nodal_loads"])
    for load in pattern["element_loads"]:
        a, b = (coords[n] for n in elements[load["element_id"]]["nodes"])
        # Element loads act on the flexible length (rigid end zones, saengine.fem.end_zones).
        span = np.linalg.norm(b - a) - sum(element_offsets(elements[load["element_id"]]))
        x = (b - a) / np.linalg.norm(b - a)
        vecxz = np.array([1.0, 0, 0]) if abs(x[2]) > abs(x[0]) else np.array([0, 0, 1.0])
        y = np.cross(vecxz, x)
        y /= np.linalg.norm(y)
        total += float(((load["wx"] * x + load["wy"] * y + load["wz"] * np.cross(x, y)) * span)[2])
    return total


def _wired() -> bool:
    from saengine.fem.derive import derive_fem

    return "member_loads" in inspect.signature(derive_fem).parameters


@pytest.mark.skipif(not _wired(), reason="derive_fem does not take member_loads yet (integrator)")
def test_derive_applies_member_loads_and_reactions_rise(tmp_path: Path) -> None:
    from saengine.fem.derive import derive_fem

    settings = default_project_settings("Bay")
    building = generate(plan(), "s")
    model = loads(
        {
            "id": "WALL",
            "story": "L1",
            "member": "B11",
            "wall": {"type": "BW250", "height": 2700},
        },
        {
            "id": "TANK",
            "story": "L1",
            "member": "B12",
            "kind": "point",
            "value": 30,
            "distance": 2000,
        },
    )
    args = (building, OBJECTS, default_material_library(), settings, {"bim": "abc"})
    without = derive_fem(*args)
    with_loads = derive_fem(*args, member_loads=model)
    wall_total = 5.35 * 2.7 * 6.0 + 30.0  # kN
    added = (_applied(without.project, "SD") - _applied(with_loads.project, "SD")) / 1e3
    assert added == pytest.approx(wall_total, rel=1e-6)
    # Superimposed dead load counts in full in the seismic weight.
    assert with_loads.summary["weight_kN"] - without.summary["weight_kN"] == pytest.approx(
        wall_total, rel=1e-3
    )

    def reaction(project: dict) -> float:
        path = tmp_path / f"{len(list(tmp_path.iterdir()))}"
        path.mkdir()
        (path / "model.osmodel").write_text(json.dumps(project), encoding="utf-8")
        sd = 1 + [p["name"] for p in project["load_patterns"]].index("SD")
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "opensees_studio.run",
                "--project",
                str(path / "model.osmodel"),
                "--cases",
                str(sd),
                "--out",
                str(path / "model.results"),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert run.returncode == 0, run.stderr[-2000:]
        from opensees_studio.services.result_store import load_manifest, load_results

        out = path / "model.results"
        entry = next(
            e for e in load_manifest(out)["cases"] if str(e["case_name"]).split(":")[0] == "SD"
        )
        reactions = load_results(entry, out).node_reaction
        return sum(float(np.asarray(rows[-1])[2]) for rows in reactions.values() if len(rows))

    rise = (reaction(with_loads.project) - reaction(without.project)) / 1e3
    assert rise == pytest.approx(wall_total, rel=0.005)


def test_e2k_export_writes_member_loads_and_modifiers() -> None:
    """The .e2k exporter writes the wall as a uniform frame load on its beam, the point load at
    its relative distance, and a member's stiffness modifiers as ETABS property modifiers."""
    from saengine.exporters.etabs import write_e2k

    building = generate(plan(), "s")
    building = building.model_copy(
        update={
            "elements": [
                e.model_copy(update={"modifiers": {"I33": 0.5, "weight": 0.9}})
                if e.id == "B11"
                else e
                for e in building.elements
            ]
        }
    )
    model = loads(
        {"id": "WALL", "story": "L1", "member": "B11", "wall": {"type": "BW250", "height": 2700}},
        {
            "id": "TANK",
            "story": "L1",
            "member": "B12",
            "kind": "point",
            "value": 30,
            "distance": 2000,
        },
    )
    settings = default_project_settings("Bay")
    export = write_e2k(building, OBJECTS, default_material_library(), settings, member_loads=model)
    text = export.text
    wall = [line for line in text.splitlines() if 'TYPE "TRAPF"' in line and 'LC "SD"' in line]
    value = 5.35 * 2.7  # kN/m: BW250 x 2.7 m
    assert any(f"FSTART {value:.4g}"[:12] in line for line in wall), wall
    point = [line for line in text.splitlines() if 'TYPE "POINTF"' in line]
    assert len(point) == 1 and "FVAL 30" in point[0] and "RDIST 0.4" in point[0]
    modified = [line for line in text.splitlines() if "PROPMODI33 0.5" in line]
    assert len(modified) == 1 and "PROPMODW 0.9" in modified[0]
    # The code's cracked factor for I22 is kept beside the engineer's I33.
    assert "PROPMODI22 0.35" in modified[0]
    assert export.report.carried["SD"] >= value * 6.0 + 30.0 - 1e-6
