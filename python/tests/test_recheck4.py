"""Quick re-check 4 of the alpha 9 gate (2026-11-10): column-top anchorage credits and bar
limit, isolators unticked, US units of the proposal and Run All, S-101 cover names."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _using(pack_id: str):
    from saengine.codes import context as cc

    return cc.using(cc.pack_for({"codePack": pack_id}))


def _column(count: int, dia: float, size: float = 711.2, tie: float = 12.7):
    from saengine.library.objects import Column

    return Column.model_validate(
        {
            "id": "C28x28",
            "name": "Column 28x28",
            "material": "C4000",
            "profile": {"shape": "rectangle", "xDim": size, "yDim": size},
            "reinforcement": {
                "material": "A615-60",
                "cover": 40.0,
                "longitudinal": [{"position": "perimeter", "count": count, "dia": dia}],
                "transverse": {
                    "type": "tie",
                    "dia": tie,
                    "spacing": 127.0,
                    "legs": 3,
                    "zone": {"spacing": 101.6},
                },
            },
        }
    )


# ── 1. Column-top anchorage: the pack's credits where the detailing earns them ──


def test_us_case_c28x28_no9_passes_under_23_9_in_beams() -> None:
    from saengine.design import ductile_joints as dj

    column = _column(8, 28.65)
    with _using("aci318-asce7-22"):
        detail = dj.column_top_detail(column.profile, column.reinforcement, 27.6, 413.7)
        plain, available = dj.column_top_anchorage(28.65, 413.7, 27.6, 607.0)
        credited, _ = dj.column_top_anchorage(28.65, 413.7, 27.6, 607.0, detail=detail)
    assert plain.value > available  # the re-check's FAIL (36.3 in > 22.4 in) without credits
    assert credited.value <= available  # psi_r = psi_o = 1.0: half of it
    assert credited.value == pytest.approx(plain.value / (1.6 * 1.25), rel=1e-6)
    assert "credits for cover and confinement" in credited.formula
    assert "Table 25.4.3.2" in credited.formula


def test_credits_follow_each_pack() -> None:
    from saengine.design import ductile_joints as dj

    column = _column(8, 28.65)
    with _using("bnbc2020"):
        detail = dj.column_top_detail(column.profile, column.reinforcement, 27.6, 413.7)
        plain, _ = dj.column_top_anchorage(28.65, 413.7, 27.6, 607.0)
        credited, _ = dj.column_top_anchorage(28.65, 413.7, 27.6, 607.0, detail=detail)
    # Sec 8.2.6.3(a): cover (x 0.7); (b) not: ties at 101.6 mm > 3 db
    assert credited.value == pytest.approx(plain.value * 0.7, rel=1e-6)
    assert "8.2.6.3" in credited.formula
    with _using("eurocodes"):
        plain, _ = dj.column_top_anchorage(28.65, 413.7, 27.6, 607.0)
        credited, _ = dj.column_top_anchorage(28.65, 413.7, 27.6, 607.0, detail=detail)
    # cd = min(a/2, c1) > 3 phi earns alpha1 = 0.7 of bent bars
    assert credited.value <= plain.value


def test_no_cover_credit_with_thin_cover_and_close_bars() -> None:
    from saengine.drawings import detailing

    with _using("aci318-asce7-22"):
        thin = detailing.HookDetailing(side_cover=40.0, bar_spacing=100.0)
        cover, confined, why = detailing.hook_credits(28.65, thin)
    assert not cover and not confined
    assert "side cover 40 mm < 63.5 mm or 6 db" in why
    with _using("aci318-asce7-22"):
        large = detailing.HookDetailing(side_cover=200.0, bar_spacing=400.0)
        assert detailing.hook_credits(43.0, large)[:2] == (False, False)  # above No. 11


def test_proposal_limits_column_bars_to_top_hooks_that_fit() -> None:
    from saengine.design.proposal import _column_top_short
    from saengine.design.required import Options

    column = _column(8, 32.0, size=400.0, tie=10.0)
    member = {
        "id": "C1-L4",
        "kind": "column",
        "type": "C28x28",
        "object": column,
        "fc": 27.6,
        "fy": 413.7,
        "element": SimpleNamespace(top=12000.0),
    }
    gathered = SimpleNamespace(collect={"members": [member]})
    entry = {
        "kind": "column",
        "members": ["C1-L4"],
        "proposed": {
            "longitudinal": [{"position": "perimeter", "count": 8, "dia": 32.0}],
            "text": "8Ø32",
        },
    }
    opts = Options(column_diameters=(16.0, 20.0, 25.0, 32.0))
    with _using("aci318-asce7-22"):
        found = _column_top_short(entry, {"C1-L4": (12000.0, 350.0)}, gathered, opts)
    assert found is not None
    db, (worst, need, available), fitting = found
    assert db == 32.0 and worst == "C1-L4" and need > available
    assert fitting and max(fitting) < 32.0
    # a beam deep enough: nothing to limit
    with _using("aci318-asce7-22"):
        assert _column_top_short(entry, {"C1-L4": (12000.0, 900.0)}, gathered, opts) is None
