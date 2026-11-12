"""B18: construction types and fire resistance through the bnbc2020 code pack.

Pins Part 3 Tables 3.3.1(a)-(b) and Sec 3.1.1 (pp. 165-172) and Part 4 Table 4.1.1 (p. 284);
the ACI 216.1 covers stay a flagged advisory (owner decision 7).
"""

from __future__ import annotations

from types import SimpleNamespace as N

import pytest

from saengine.codes.tables import builtin_table
from saengine.design import fire_resistance as F
from saengine.design.masonry import Masonry, fire_row
from saengine.library.settings import Construction, ProjectSettings

ZERO = N(columns=0, beams=0, slabs=0, walls=0)


def _settings(type_id: str = "", aggregate: str = "siliceous", separation=None, least=ZERO):
    return N(
        construction=Construction(
            constructionType=type_id, aggregate=aggregate, fireSeparation=separation
        ),
        analysis=N(fireResistance=least),
    )


def _column(x: float, y: float, cover: float = 40.0, tie: float = 10.0) -> N:
    return N(
        profile=N(shape="rectangle", xDim=x, yDim=y),
        reinforcement=N(cover=cover, transverse=N(dia=tie)),
    )


# ── Part 3 Tables 3.3.1(a)-(b) ──


def test_construction_types_group_one():
    t = builtin_table("fireResistance").constructionTypes
    # Columns, girders and framing supporting more than one floor: 4/3/2/1/0 h.
    assert [t[k].framingMoreFloors for k in ("I-A", "I-B", "I-C", "I-D", "I-E")] == [4, 3, 2, 1, 0]
    # Supporting one floor and floor construction: 3/2/1.5/1/0 h.
    assert [t[k].framingOneFloor for k in ("I-A", "I-B", "I-C", "I-D", "I-E")] == [3, 2, 1.5, 1, 0]
    assert [t[k].floors for k in ("I-A", "I-B", "I-C", "I-D", "I-E")] == [3, 2, 1.5, 1, 0]
    assert [t[k].interiorBearingWalls for k in ("I-A", "I-B", "I-C", "I-D", "I-E")] == [
        4, 3, 2, 1, 0,
    ]  # fmt: skip
    # Exterior bearing walls by separation band (<= 0.9, < 4.5, < 9.0, >= 9.0 m).
    assert t["I-D"].exteriorBearing == [2, 2, 1, 1]
    assert t["I-E"].exteriorBearing == [2, 2, 0, 0]
    assert t["I-A"].exteriorNonBearing == [2, 2, 1.5, 0]
    assert t["I-A"].fireSeparationWalls == 4 and t["I-B"].fireSeparationWalls == 2
    assert all(t[k].group == "nonCombustible" for k in ("I-A", "I-B", "I-C", "I-D", "I-E"))


def test_construction_types_group_two():
    t = builtin_table("fireResistance").constructionTypes
    assert t["II-A"].framingMoreFloors is None  # 'as per provisions of this Code'
    assert t["II-C"].framingMoreFloors == 1  # printed '0 or 1': the larger (note)
    assert [t[k].membersSupportingWalls for k in ("II-A", "II-B", "II-C", "II-D", "II-E")] == [
        3, 2.5, 2, 1.5, 1,
    ]  # fmt: skip
    assert [t[k].interiorBearingWalls for k in ("II-A", "II-B", "II-C", "II-D", "II-E")] == [
        2, 1, 0, 1, 0,
    ]  # fmt: skip
    assert t["II-B"].exteriorBearing == [2, 2, 2, 1.5]
    assert all(t[k].group == "combustible" for k in ("II-A", "II-B", "II-C", "II-D", "II-E"))


def test_ratings_from_type_and_least():
    rated = F.ratings_of(_settings("I-A"))
    assert {k: h for k, (h, _w) in rated.items()} == {
        "column": 4, "beam": 3, "slab": 3, "wall": 4,
    }  # fmt: skip
    # The larger of the type's and Analysis model > Fire resistance.
    least = N(columns=0, beams=0, slabs=3, walls=0)
    rated = F.ratings_of(_settings("I-C", least=least))
    assert rated["slab"] == (3.0, "Project Settings")
    assert rated["column"][0] == 2
    # Not classified: only the least ratings.
    assert F.ratings_of(_settings(""))["column"][0] == 0


def test_exterior_wall_band():
    # I-D: interior bearing 1 h, exterior bearing 2 h within 4.5 m, 1 h from 4.5 m.
    assert F.ratings_of(_settings("I-D", separation=0.9))["wall"][0] == 2
    assert F.ratings_of(_settings("I-D", separation=3.0))["wall"][0] == 2
    assert F.ratings_of(_settings("I-D", separation=4.5))["wall"][0] == 1
    assert F.ratings_of(_settings("I-D", separation=12.0))["wall"][0] == 1


def test_height_non_combustible():
    # Sec 3.1.1: above 33 m non-combustible.
    assert builtin_table("fireResistance").nonCombustibleAbove == pytest.approx(33.0)
    assert F.construction_summary(_settings("II-B"), 34.0)["warnings"]
    assert not F.construction_summary(_settings("II-B"), 30.0)["warnings"]
    assert not F.construction_summary(_settings("I-C"), 60.0)["warnings"]
    assert F.construction_summary(_settings("X-9"), 10.0)["warnings"]  # not in the pack


# ── Part 4 Table 4.1.1 ──


@pytest.mark.parametrize(
    ("aggregate", "values"),
    [
        ("siliceous", [89, 109, 127, 157, 178]),
        ("carbonate", [81, 102, 117, 145, 168]),
        ("sandLightweight", [69, 84, 97, 117, 137]),
        ("lightweight", [64, 79, 91, 112, 130]),
    ],
)
def test_thickness_rows(aggregate, values):
    got = [F.required("thickness", h, aggregate) for h in (1, 1.5, 2, 3, 4)]
    assert got == pytest.approx(values)


@pytest.mark.parametrize(
    ("aggregate", "values"),
    [
        ("siliceous", [203, 229, 254, 305, 356]),
        ("carbonate", [203, 229, 254, 279, 305]),
        ("sandLightweight", [203, 216, 229, 267, 305]),
        ("lightweight", [203, 216, 229, 267, 305]),  # no row: sand-lightweight (practice)
    ],
)
def test_column_rows(aggregate, values):
    got = [F.required("columnSize", h, aggregate) for h in (1, 1.5, 2, 3, 4)]
    assert got == pytest.approx(values)


def test_masonry_rows():
    hours = (0.5, 0.75, 1, 1.5, 2, 3, 4)
    assert [F.required("masonryThickness", h, "clayUnfilled") for h in hours] == pytest.approx(
        [43, 51, 58, 72, 86, 109, 127]
    )
    assert [F.required("masonryThickness", h, "clayFilled") for h in hours] == pytest.approx(
        [58, 67, 76, 94, 112, 140, 168]
    )
    assert F.required("masonryThickness", 1, "concreteUnfilled") is None
    assert F.required("thickness", 5) is None


def test_masonry_fire_row():
    assert fire_row(Masonry(fm=5.0)) == {"row": "clayUnfilled", "equivalent": True}
    hollow = Masonry(fm=5.0, units="hollow", grouting="full")
    assert fire_row(hollow) == {"row": "clayFilled", "equivalent": True}
    assert fire_row(Masonry(fm=5.0, units="hollow"))["equivalent"] is False


def test_masonry_wall_check():
    wall = N(thickness=125.0)
    rows = F.member_checks("wall", wall, 4, masonry={"row": "clayUnfilled", "equivalent": True})
    assert rows[0]["demand"] == pytest.approx(127) and not rows[0]["ok"]
    rows = F.member_checks("wall", wall, 3, masonry={"row": "clayUnfilled", "equivalent": True})
    assert rows[0]["ok"]


def test_member_checks_and_advisory():
    # Type I-B column 300 x 300 mm, siliceous: 3 h needs 305 mm.
    checked = [
        {"kind": "column", "type": "C", "ok": True, "utilisation": 0.5},
        {"kind": "beam", "type": "B", "ok": True, "utilisation": 0.5},
    ]
    types = {"C": _column(300.0, 300.0), "B": _column(200.0, 450.0, cover=20.0, tie=8.0)}
    assert F.add_fire_checks(checked, types, _settings("I-B")) == 2
    column, beam = checked
    assert not column["ok"] and column["utilisation"] == pytest.approx(305 / 300, abs=1e-3)
    # Beams: no least size in Table 4.1.1; the ACI covers are flagged and never fail.
    assert beam["ok"]
    assert all(r["flag"] for r in beam["checks"])
    assert any("not BNBC" in r["note"] for r in beam["checks"])
    # Carbonate aggregate: 3 h needs 279 mm.
    checked = [{"kind": "column", "type": "C", "ok": True, "utilisation": 0.5}]
    F.add_fire_checks(checked, types, _settings("I-B", aggregate="carbonate"))
    assert checked[0]["ok"]


def test_settings_defaults():
    s = ProjectSettings.model_validate(
        {"project": {"name": "x"}, "floorLoad": "a", "roofLoad": "a"}
    )
    assert s.construction.constructionType == ""
    assert s.construction.aggregate == "siliceous"
    assert s.construction.fireSeparation is None
