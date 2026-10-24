"""Bar bending schedules (drawings): BS 8666 shapes, cutting lengths, totals, BOQ reconciliation.

All models are synthetic; the expected values are worked by hand in the comments.
"""

from __future__ import annotations

import csv
import io

import pytest

from saengine.boq.quantities import BillOfQuantities
from saengine.drawings.bbs import (
    SHAPES,
    bar_mass,
    bar_schedule,
    bend_radius,
    cutting_length,
    reconcile,
    reconciliation_table,
    round_up,
    schedule_csv,
    seismic_hook,
    shape_code,
    sheet_table,
    split_straight,
)


def beam(**extra):
    """Two beams B1, 300 x 500, 40 mm cover to the links."""
    return {
        "id": "B1",
        "kind": "beam",
        "member": "B1 (1F)",
        "story": "1F",
        "count": 2,
        "bars": [
            # links: A = 300 - 2*40 = 220, B = 500 - 2*40 = 420 (outside dimensions)
            {"mark": "01", "dia": 10, "shape": "stirrup", "count": 20, "dims": {"A": 220, "B": 420},
             "material": "B420DWR", "zone": "end"},
            # an L bar into the column: A = 1000, B = 400
            {"mark": "02", "dia": 16, "shape": "11", "count": 2, "segments": [1000, 400],
             "material": "B420DWR", "role": "bottom"},
        ],
        **extra,
    }  # fmt: skip


def test_kg_per_metre():
    assert bar_mass(16) == pytest.approx(1.5802, abs=1e-4)  # 256 / 162
    assert bar_mass(10) == pytest.approx(0.6173, abs=1e-4)  # 100 / 162
    assert bar_mass(12) == pytest.approx(0.8889, abs=1e-4)  # 144 / 162


def test_round_up_to_25():
    assert round_up(1440) == 1450
    assert round_up(1450) == 1450
    assert round_up(1450.0000001) == 1450  # float noise is not a new 25 mm
    assert round_up(1451) == 1475


def test_bend_radius_takes_the_larger_of_bs8666_and_bnbc():
    # links of 16 mm and smaller: BNBC 4 d inside diameter = 2 d radius = BS 8666's 2 d
    assert bend_radius(10, transverse=True) == 20
    # main bars 10-25 mm: BNBC 6 d diameter = 3 d radius > BS 8666's 2 d (16 mm: 48 > 32)
    assert bend_radius(16) == 48
    # 25 mm: BS 8666 r = 87 > BNBC 75
    assert bend_radius(25) == 87
    # 32 mm: BNBC 8 d diameter = 128 > BS 8666 112
    assert bend_radius(32) == 128


def test_seismic_hook_of_a_link():
    # 6 d = 60 < 75 -> 75 + r (20) + d (10) = 105, less than P (130 mm for 10 mm bars)
    assert seismic_hook(10) == 130
    # 16 mm: 96 + 32 + 16 = 144 < P = 210
    assert seismic_hook(16) == 210


def test_shape_codes_and_names():
    assert shape_code("51") == "51"
    assert shape_code(0) == "00"
    assert shape_code("Stirrup") == "51"
    assert shape_code("L") == "11"
    assert shape_code("straight") == "00"
    with pytest.raises(ValueError):
        shape_code("zigzag")
    for code in ("00", "11", "21", "33", "51", "63"):
        assert SHAPES[code].formula.startswith("L =")


def test_stirrup_of_a_300x500_beam():
    # shape 51: L = 2(A + B + C) - 2.5 r - 5 d = 2(220 + 420 + 130) - 50 - 50 = 1440 -> 1450
    assert cutting_length("51", {"A": 220, "B": 420, "C": 130}, 10, 20) == pytest.approx(1440)
    row = bar_schedule({"elements": [beam()]}).rows[0]
    assert row.shape == "51"
    assert row.dims == {"A": 220, "B": 420, "C": 130}
    assert row.cutting_length == 1450
    assert (row.members, row.per_member, row.total_count) == (2, 20, 40)
    assert row.total_length == pytest.approx(58.0)  # 40 x 1.45 m
    assert row.mass == pytest.approx(58.0 * 100 / 162)  # 35.80 kg
    assert row.size == "B420DWR Ø10"
    assert row.remarks == "zone end"


def test_l_bar():
    # shape 11: L = A + B - 0.5 r - d, r = 48 (BNBC 6 d): 1400 - 24 - 16 = 1360 -> 1375
    row = bar_schedule({"elements": [beam()]}).rows[1]
    assert row.shape == "11"
    assert row.radius == 48
    assert row.cutting_length == 1375
    assert row.mass == pytest.approx(4 * 1.375 * 256 / 162)  # 8.69 kg


def test_straight_bar_with_laps():
    # 15 m of 16 mm bar, lap 40 d = 640: one 12 m bar and 15000 - (12000 - 640) = 3640
    pieces = split_straight(15_000, 640)
    assert pieces == [12_000, 3_640]
    assert sum(pieces) == 15_000 + 640
    assert split_straight(30_000, 640) == [12_000, 12_000, 7_280]  # two laps
    assert split_straight(9_000, 640) == [9_000]
    element = {
        "id": "GB1",
        "kind": "beam",
        "bars": [
            {"mark": "10", "dia": 16, "shape": "00", "count": 3, "length": pieces[0], "lap": 640},
            {"mark": "11", "dia": 16, "shape": "00", "count": 3, "length": pieces[1], "lap": 640},
        ],
    }
    schedule = bar_schedule({"elements": [element]})
    assert [r.cutting_length for r in schedule.rows] == [12_000, 3_650]
    assert schedule.rows[1].dims == {"A": 3640}
    assert schedule.rows[0].remarks == "lap 640"
    # 3 x (12.000 + 3.650) m x 1.5802 kg/m
    assert schedule.total == pytest.approx(3 * 15.65 * 256 / 162)


def test_totals_per_size_and_kind():
    column = {
        "id": "C1",
        "kind": "column",
        "count": 4,
        "bars": [{"mark": "20", "dia": 16, "shape": "00", "count": 8, "dims": {"A": 3_500}}],
    }
    schedule = bar_schedule({"elements": [beam(), column]})
    links = 58.0 * 100 / 162
    l_bars = 5.5 * 256 / 162
    columns = 32 * 3.5 * 256 / 162
    assert schedule.by_diameter == pytest.approx({10: links, 16: l_bars + columns})
    assert schedule.by_kind["beam"] == pytest.approx({10: links, 16: l_bars})
    assert schedule.by_kind["column"] == pytest.approx({16: columns})
    assert schedule.total == pytest.approx(links + l_bars + columns)


def test_problems_are_noted_not_raised():
    element = {
        "id": "X",
        "kind": "beam",
        "bars": [
            {"mark": "a", "dia": 12, "shape": "21", "dims": {"A": 300}},  # B, C missing
            {"mark": "b", "dia": 12, "shape": "21", "dims": {"A": 300}, "length": 900},
            {"mark": "c", "dia": 12, "shape": "11", "dims": {"A": 100, "B": 500}},  # A < P
            {"mark": "d", "dia": 0, "length": 100},
        ],
    }
    schedule = bar_schedule({"elements": [element]})
    assert [r.mark for r in schedule.rows] == ["b", "c"]
    assert schedule.rows[0].shape == "99" and schedule.rows[0].cutting_length == 900
    text = " ".join(schedule.notes)
    assert "X a" in text and "minimum end projection" in text and "X d" in text


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_objects_as_well_as_dicts():
    bar = Obj(mark="01", dia=10, shape="51", count=5, dims={"A": 220, "B": 420})
    schedule = bar_schedule(Obj(elements=[Obj(id="B2", kind="beam", bars=[bar])]))
    assert schedule.rows[0].cutting_length == 1450 and schedule.rows[0].members == 1


def test_csv_is_excel_friendly():
    text = schedule_csv(bar_schedule({"elements": [beam()]}))
    assert "\r\n" in text
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][:4] == ["Member", "Bar mark", "Type and size", "Shape code"]
    assert rows[1][:4] == ["B1 (1F)", "01", "B420DWR Ø10", "51"]
    assert rows[1][12] == "1450" and rows[1][14] == "35.80"
    assert any(r and r[0] == "Total" and r[14] == f"{35.802 + 8.691:.2f}" for r in rows)
    assert any(r and r[0] == "Beams total" for r in rows)


def test_sheet_table():
    table = sheet_table(bar_schedule({"elements": [beam()]}))
    keys = [c["key"] for c in table["columns"]]
    assert keys[:4] == ["member", "mark", "size", "shape"]
    assert all(len(r) == len(keys) for r in table["rows"])
    assert table["rows"][1][0] == ""  # the member only on its first row
    assert table["groups"] == [{"member": "B1 (1F)", "first": 0, "count": 2}]
    size = table["columns"][2]
    assert size["width"] >= len("B420DWR Ø10") and size["align"] == "left"
    assert table["columns"][14]["align"] == "right"
    totals = table["totals"]
    assert [c["key"] for c in totals["columns"]] == ["kind", "d10", "d16", "total"]
    assert totals["rows"][-1][0] == "Total"


BOQ = {
    "items": [
        {"code": "R.01", "group": "reinforcement", "description": "10 mm", "quantity": 30.0,
         "unit": "kg", "material": "B420DWR", "diameter": 10,
         "breakdown": [{"element": "B1", "detail": "stirrups", "quantity": 30.0}]},
        {"code": "R.02", "group": "reinforcement", "description": "16 mm", "quantity": 15.0,
         "unit": "kg", "material": "B420DWR", "diameter": 16,
         "breakdown": [{"element": "B1", "detail": "longitudinal", "quantity": 10.0},
                       {"element": "C9", "detail": "longitudinal", "quantity": 5.0}]},
        {"code": "C.01", "group": "concrete", "description": "x", "quantity": 1.0, "unit": "m3"},
    ]
}  # fmt: skip


def test_reconciliation_with_the_boq():
    schedule = bar_schedule({"elements": [beam()]})
    rec = reconcile(schedule, BOQ)
    by = {r.dia: r for r in rec.rows}
    links = 58.0 * 100 / 162  # 35.80
    assert by[10].bbs == pytest.approx(links)
    assert by[10].boq == 30.0
    assert by[10].difference == pytest.approx(links - 30.0)  # +5.80
    assert by[10].percent == pytest.approx(100 * (links - 30) / 30)
    assert "Links and ties: +5.8 kg" in by[10].reasons[0]
    l_bars = 5.5 * 256 / 162  # 8.69
    assert by[16].categories["longitudinal"] == pytest.approx((l_bars, 15.0))
    assert by[16].only_boq == {"C9": 5.0}
    assert any("In the BOQ but not detailed: C9" in r for r in by[16].reasons)
    assert rec.bbs == pytest.approx(links + l_bars) and rec.boq == 45.0
    table = reconciliation_table(rec)
    assert table["rows"][-1][:3] == ["Total", f"{links + l_bars:.1f}", "45.0"]


def test_reconciliation_reads_a_bill_of_quantities_model():
    rec = reconcile(bar_schedule({"elements": [beam()]}), BillOfQuantities.model_validate(BOQ))
    assert {r.dia: r.boq for r in rec.rows} == {10: 30.0, 16: 15.0}


def test_reconciliation_counts_laps_and_cut_offs():
    element = {
        "id": "B1",
        "kind": "beam",
        "bars": [
            {"mark": "1", "dia": 16, "count": 2, "length": 6_000, "lap": 640, "curtailed": True},
        ],
    }
    rec = reconcile(bar_schedule({"elements": [element]}), {"items": []})
    row = rec.rows[0]
    assert row.laps == pytest.approx(2 * 0.640 * 256 / 162)
    assert row.cutoffs == 1
    assert row.only_bbs == {"B1": pytest.approx(12 * 256 / 162)}
    assert row.percent is None


def one_bar(bar, kind="beam", **element):
    return bar_schedule({"elements": [{"id": "X", "kind": kind, "bars": [bar], **element}]})


def test_shape_12_uses_the_scheduled_radius():
    # L = A + B - 0.43 R - 1.2 d = 1000 + 1000 - 0.43 * 500 - 1.2 * 16 = 1765.8 -> 1775
    bar = {"mark": "1", "dia": 16, "shape": "12", "dims": {"A": 1000, "B": 1000, "R": 500}}
    row = one_bar(bar).rows[0]
    assert row.cutting_length == 1775
    assert sheet_table(one_bar(bar))["rows"][0][8] == "500"  # R in the E/R column
    # without R the minimum radius r = 3 d = 48: 2000 - 20.64 - 19.2 = 1960.2 -> 1975
    del bar["dims"]["R"]
    assert one_bar(bar).rows[0].cutting_length == 1975
    # an R below the minimum is scheduled with the minimum, and noted
    bar["dims"]["R"] = 20
    schedule = one_bar(bar)
    assert schedule.rows[0].cutting_length == 1975
    assert any("below the minimum bend radius" in n for n in schedule.notes)


def test_bad_numbers_are_noted_not_raised():
    bars = [
        {"mark": "a", "dia": 12, "shape": "11", "segments": [{"len": 300}, {"len": 500}]},
        {"mark": "b", "dia": "abc", "length": 1000},
        {"mark": "c", "dia": 12, "shape": "11", "dims": {"A": "abc", "B": 400}},
        {"mark": "d", "dia": 12, "count": "two", "length": 1000},
        {"mark": "e", "dia": 12, "length": 1000, "lap": None},  # None: no lap
        {"mark": "f", "dia": "Ø12", "length": "1000 mm", "count": "3"},  # texts read as numbers
    ]
    schedule = bar_schedule({"elements": [{"id": "X", "kind": "beam", "bars": bars}]})
    assert [r.mark for r in schedule.rows] == ["e", "f"]
    f = schedule.rows[1]
    assert f.dia == 12 and f.cutting_length == 1000 and f.per_member == 3
    text = "\n".join(schedule.notes)
    assert "X a: segment A has no length; not scheduled." in text
    assert "X b: the bar diameter is not a number ('abc'); not scheduled." in text
    assert "X c: dimension A is not a number ('abc'); not scheduled." in text
    assert "X d: the number of bars is not a number ('two'); not scheduled." in text


def test_helix_turns_and_curtailed_texts():
    # shape 77: L = C pi (A - d) = 12.5 pi (500 - 10) = 19242.5 -> 19250
    helix = {"mark": "P", "dia": 10, "shape": "helix", "dims": {"A": 500, "B": 100, "C": 12.5}}
    schedule = one_bar(helix, kind="column")
    row = schedule.rows[0]
    assert row.dims == {"A": 500, "B": 100, "C": 12.5} and row.cutting_length == 19250
    assert "C = turns" in row.remarks
    assert sheet_table(schedule)["rows"][0][6] == "12.5"
    assert (
        not one_bar({"mark": "1", "dia": 12, "length": 900, "curtailed": "false"}).rows[0].curtailed
    )
    assert one_bar({"mark": "1", "dia": 12, "length": 900, "curtailed": "yes"}).rows[0].curtailed


def test_cells_are_wrapped_to_the_column_width():
    bar = {"mark": "1", "dia": 10, "shape": "51", "dims": {"A": 220, "B": 420},
           "zone": "end lo = 1000 at both ends", "remarks": "135 deg hooks", "curtailed": True}  # fmt: skip
    table = sheet_table(one_bar(bar, member="a very long member label for a beam line 1-2-3"))
    for i, column in enumerate(table["columns"]):
        for row in table["rows"]:
            assert all(len(line) <= column["width"] - 1 for line in row[i].split("\n"))
    remarks = table["rows"][0][-1]
    assert "\n" in remarks and remarks.replace("\n", " ") == (
        "135 deg hooks, zone end lo = 1000 at both ends, cut-off"
    )
    rec = reconcile(one_bar(bar), BOQ)
    table = reconciliation_table(rec)
    why = table["columns"][-1]["width"]
    assert all(len(line) <= why - 1 for r in table["rows"] for line in r[-1].split("\n"))


def test_pile_bars_reconcile_with_the_boq_under_the_cap():
    # 6 bars of 16 mm x 10 m: 60 m x 256 / 162 = 94.81 kg, booked by the BOQ under the cap PC1
    pile = {"id": "P1", "kind": "pile", "cap": "PC1",
            "bars": [{"mark": "1", "dia": 16, "count": 6, "length": 10_000}]}  # fmt: skip
    boq = {"items": [{"group": "reinforcement", "diameter": 16, "quantity": 94.8,
                      "breakdown": [{"element": "PC1", "detail": "pile bars", "quantity": 94.8}]}]}  # fmt: skip
    row = reconcile(bar_schedule({"elements": [pile]}), boq).rows[0]
    assert row.categories == {"longitudinal": pytest.approx((94.81, 94.8), abs=0.01)}
    assert row.only_bbs == {} and row.only_boq == {}
    assert row.reasons == []


def test_wall_end_bars_are_longitudinal_on_both_sides():
    wall = {"id": "W1", "kind": "wall",
            "bars": [{"mark": "E1", "role": "end", "dia": 16, "count": 4, "length": 3_000}]}  # fmt: skip
    mass = 12 * 256 / 162
    boq = {"items": [{"group": "reinforcement", "diameter": 16, "quantity": mass,
                      "breakdown": [{"element": "W1", "detail": "end bars", "quantity": mass}]}]}  # fmt: skip
    row = reconcile(bar_schedule({"elements": [wall]}), boq).rows[0]
    assert list(row.categories) == ["longitudinal"] and row.reasons == []


def test_the_detailing_models_bend_diameter_is_honoured():
    # a 12 mm L bar with bendDia 120 (10 d): r = 60, L = 1000 + 400 - 30 - 12 = 1358 -> 1375;
    # the default r = 36 gives 1400 - 18 - 12 = 1370 -> 1375 too, so check the radius itself
    bar = {"mark": "1", "dia": 12, "shape": "L", "dims": {"A": 1000, "B": 400}, "bendDia": 120}
    assert one_bar(bar).rows[0].radius == 60


def test_a_beam_line_matches_its_bim_beams_in_the_boq():
    # the detailing model details B1 and B2 as one beam line "B1+B2"; the BOQ books B1 and B2
    line = {"id": "B1+B2", "kind": "beam", "members": ["B1", "B2"],
            "bars": [{"mark": "T1", "dia": 16, "count": 2, "length": 8_100}]}  # fmt: skip
    mass = 16.2 * 256 / 162
    boq = {"items": [{"group": "reinforcement", "diameter": 16, "quantity": mass,
                      "breakdown": [{"element": "B1", "detail": "longitudinal", "quantity": 10.0},
                                    {"element": "B2", "detail": "longitudinal",
                                     "quantity": mass - 10.0}]}]}  # fmt: skip
    row = reconcile(bar_schedule({"elements": [line]}), boq).rows[0]
    assert row.only_bbs == {} and row.only_boq == {} and row.reasons == []
