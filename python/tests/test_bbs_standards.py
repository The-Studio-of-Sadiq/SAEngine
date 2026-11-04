"""Bar bending schedules by the code pack's standard (alpha 9 C14): BS 8666 (default pack),
EN ISO 3766 (Eurocodes), IS 2502 (IS codes), ACI 315 / CRSI (US pack).

Cutting lengths are worked by hand in the comments; the formulas are the packs' (VERIFY.md).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.drawings import bbs

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _fresh():
    registry.clear_cache()
    yield
    registry.clear_cache()


def _in(pack_id: str):
    return code_context.using(registry.load(pack_id))


def test_formula_evaluator_reads_arithmetic_only():
    assert bbs.evaluate("A + B - 0.5 * r - d", {"A": 1000, "B": 400, "r": 48, "d": 16}) == 1360
    assert bbs.evaluate("max(R, r) + sqrt(9) + 2 ** 3", {"R": 1, "r": 5}) == 16
    with pytest.raises(ValueError):
        bbs.evaluate("__import__('os')", {})
    with pytest.raises(ValueError):
        bbs.evaluate("A + Q", {"A": 1})


def test_bs8666_default_pack_pins():
    with _in("bnbc2020"):
        std = bbs.standard()
        assert (std.name, std.title, std.roundTo) == ("BS 8666", "Bar bending schedule", 25.0)
        # shape 11: A + B - 0.5 r - d = 1000 + 400 - 24 - 16 = 1360
        assert bbs.cutting_length("11", {"A": 1000, "B": 400}, 16, 48) == pytest.approx(1360)
        # shape 51: 2(A + B + C) - 2.5 r - 5 d = 2 (220 + 420 + 130) - 50 - 50 = 1440
        assert bbs.cutting_length("51", {"A": 220, "B": 420, "C": 130}, 10, 20) == 1440
        # shape 21: A + B + C - r - 2 d = 300 + 900 + 300 - 48 - 32 = 1420
        assert bbs.cutting_length("21", {"A": 300, "B": 900, "C": 300}, 16, 48) == 1420
        assert bbs.shape_code("stirrup") == "51" and bbs.size_label(16) == "Ø16"
        assert bbs.shape_key_on() is False  # the default pack's sheets stay as they were


def test_en_iso_3766_centre_line_pins():
    with _in("eurocodes"):
        std = bbs.standard()
        assert std.name == "EN ISO 3766" and bbs.shape_key_on()
        # EN 1992-1-1 mandrel 4 φ for φ <= 16 (concreteMethods.barShapes): r = 2 d = 32
        assert bbs.bend_radius(16) == 32
        # shape 11: A + B - 2(r + d) + π/2 (r + d/2) = 1400 - 96 + π/2 × 40
        expect = 1400 - 96 + math.pi / 2 * 40
        assert bbs.cutting_length("11", {"A": 1000, "B": 400}, 16, 32) == pytest.approx(expect)
        # shape 51: 2(A + B) + 2C - 10(r + d) + 3π(r + d/2), d 10, r 20, C 80
        expect = 2 * 640 + 160 - 300 + 3 * math.pi * 25
        got = bbs.cutting_length("51", {"A": 220, "B": 420, "C": 80}, 10, 20)
        assert got == pytest.approx(expect)
        # the link hook: ext = max(5 d, 50) = 50 (barShapes.link135) + r + d = 80
        assert bbs.link_hook(10, 20) == 80


def test_is_2502_deduction_pins():
    with _in("is-codes"):
        std = bbs.standard()
        assert std.name == "IS 2502" and std.roundTo == 10
        # 90° bend deduction 2 d: 1000 + 400 - 32 = 1368
        assert bbs.cutting_length("11", {"A": 1000, "B": 400}, 16, 48) == pytest.approx(1368)
        # link: 2(A + B) + 2C - 3 × 2d - 2 × 3d = 1280 + 210 - 60 - 60 = 1370
        assert bbs.cutting_length("51", {"A": 220, "B": 420, "C": 105}, 10, 20) == 1370
        # helix: C √((π(A - d))² + B²)
        expect = 10 * math.sqrt((math.pi * 388) ** 2 + 75**2)
        got = bbs.cutting_length("77", {"A": 400, "B": 75, "C": 10}, 12, 24)
        assert got == pytest.approx(expect)


def test_aci_315_crsi_pins():
    with _in("aci318-asce7-22"):
        std = bbs.standard()
        assert (std.name, std.title, std.roundTo) == ("ACI 315 / CRSI", "Bar list", 25.4)
        assert bbs.shape_code("L") == "1" and bbs.shape_code("stirrup") == "T1"
        assert bbs.size_label(16) == "No. 16"
        # out-to-out: A + B = 1400; a tie 2(A + B) + 2C = 1280 + 210 = 1490
        assert bbs.cutting_length("1", {"A": 1000, "B": 400}, 16, 48) == 1400
        assert bbs.cutting_length("T1", {"A": 220, "B": 420, "C": 105}, 10, 20) == 1490
        assert bbs.round_length(1400) == pytest.approx(56 * 25.4)  # 1422.4 mm (4 ft 8 in)


def test_project_override_picks_a_standard_of_another_pack():
    table = registry.load("bnbc2020").table("barSchedule").model_copy(update={"standard": "is2502"})
    std, why = bbs.standard_of(table)
    assert std.name == "IS 2502" and "IS" in why


@pytest.mark.parametrize(
    ("pack_id", "name", "codes"),
    [
        ("bnbc2020", "BS 8666", {"00", "11", "21", "51"}),
        ("eurocodes", "EN ISO 3766", {"00", "11", "21", "51"}),
        ("is-codes", "IS 2502", {"00", "11", "21", "51"}),
        ("aci318-asce7-22", "ACI 315 / CRSI", {"STR", "1", "2", "T1"}),
    ],
)
def test_generated_building_schedule_under_each_pack(pack_id, name, codes):
    import test_boq as tb

    from saengine.drawings.detailing import detailing_model

    bim = tb.dump(tb.generate(tb.PLAN, "s"))
    with _in(pack_id):
        model = detailing_model(
            texts={"bim": bim, "objects": json.dumps(tb.OBJECTS), "materials": tb.MATERIALS}
        )
        schedule = bbs.bar_schedule(model)
        table = bbs.sheet_table(schedule)
        text = bbs.schedule_csv(schedule)
    assert schedule.std.name == name and {r.shape for r in schedule.rows} == codes
    assert schedule.total > 0 and name in schedule.notes[-1]
    assert table["title"] == schedule.std.title
    assert table["cuttingLengths"] and text.splitlines()[0].startswith("Member,")
    step = schedule.std.roundTo
    assert all(abs(r.cutting_length / step - round(r.cutting_length / step)) < 1e-6
               for r in schedule.rows)  # fmt: skip
    if pack_id != "bnbc2020":
        assert {s["code"] for s in table["shapeKey"]} == codes
