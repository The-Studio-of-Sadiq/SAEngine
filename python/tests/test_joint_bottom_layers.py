"""The bottom bars of crossing beams at a joint (owner decision 2026-11-11, SAEngine practice):
the secondary direction's bottom bars pass one main bar diameter higher, the mirror of the top
bars' second layer (T33). The design takes the less sagging d, the detailing sets the bars at
that level (``at.bottomRise``, the bars straight) and the cages' joint check no longer flags the
crossing (saengine.design.rc_detailing.joint_bottom_layers)."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.design.rc import Bar, with_bottom_rise, with_joint_layers, with_top_drop
from saengine.design.rc_detailing import joint_bottom_layers, joint_top_layers

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def _type(id_: str, h: float, top: float = 16, bottom: float = 16) -> SimpleNamespace:
    groups = [
        SimpleNamespace(position="top", dia=top),
        SimpleNamespace(position="bottom", dia=bottom),
    ]
    return SimpleNamespace(
        id=id_,
        profile=SimpleNamespace(yDim=h),
        reinforcement=SimpleNamespace(
            longitudinal=groups, cover=40.0, transverse=SimpleNamespace(dia=10.0)
        ),
    )


def _joint(x_type: str, y_type: str) -> SimpleNamespace:
    beam = SimpleNamespace
    return SimpleNamespace(
        id="J1",
        beams=[
            beam(id="X1", type=x_type, direction=(1.0, 0.0), length=6000.0),
            beam(id="X2", type=x_type, direction=(-1.0, 0.0), length=6000.0),
            beam(id="Y1", type=y_type, direction=(0.0, 1.0), length=5000.0),
        ],
    )


def test_secondary_bottom_bars_rise_a_main_bar_diameter() -> None:
    """Equal depths: the longer spans (x) are the main direction at both faces; the y beam's
    top bars drop and its bottom bars rise by the x beams' Ø20 bottom bars."""
    types = {"BX": _type("BX", 500, bottom=20), "BY": _type("BY", 500, bottom=16)}
    joints = [_joint("BX", "BY")]
    assert joint_top_layers(joints, types) == {"J1": {"Y1": 16.0}}
    assert joint_bottom_layers(joints, types) == {"J1": {"Y1": 20.0}}
    # the deeper beam is the main one in "auto", the plan direction in "x" / "y"
    deeper = {"BX": _type("BX", 500), "BY": _type("BY", 510)}
    assert joint_bottom_layers(joints, deeper) == {"J1": {"X1": 16.0, "X2": 16.0}}
    # but its bottom bars are 10 mm lower only: the x beams' still meet them
    assert joint_bottom_layers(joints, deeper, "y") == {"J1": {"X1": 16.0, "X2": 16.0}}
    assert joint_bottom_layers(joints, types, "sameLayer") == {}


def test_a_shallower_beam_s_bottom_bars_are_already_clear() -> None:
    """A secondary beam 100 mm shallower has its bottom bars far above the main ones: not
    raised (its top bars still go in the second layer)."""
    types = {"BX": _type("BX", 600), "BY": _type("BY", 500)}
    joints = [_joint("BX", "BY")]
    assert joint_top_layers(joints, types) == {"J1": {"Y1": 16.0}}
    assert joint_bottom_layers(joints, types) == {}


def test_the_raised_bars_give_the_less_sagging_d() -> None:
    from saengine.design.rc import section_of
    from saengine.library.objects import LinearReinforcement, RectangleProfile

    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [
                {"position": "top", "count": 3, "dia": 16},
                {"position": "bottom", "count": 3, "dia": 16},
            ],
            "transverse": {"type": "stirrup", "dia": 10, "legs": 2, "spacing": 150},
        }
    )
    section = section_of(RectangleProfile(xDim=300, yDim=500), reinforcement, 24.1, 420, 2e5)
    d = section.effective_depth(top=False)
    raised = with_bottom_rise(section, 16)
    assert raised.effective_depth(top=False) == pytest.approx(d - 16)
    assert raised.effective_depth(top=True) == pytest.approx(section.effective_depth(top=True))
    both = with_joint_layers(section, 16, 16)
    assert both.bars == with_bottom_rise(with_top_drop(section, 16), 16).bars
    assert with_bottom_rise(section, 0) is section
    # only the bars below the centre move
    moved = [(a, b) for a, b in zip(section.bars, raised.bars, strict=True) if a != b]
    assert moved and all(a.y < 0 and b == Bar(a.x, a.y + 16, a.area, a.dia) for a, b in moved)


def test_the_sample_frame_bottom_bars_no_longer_cross_at_one_level(tmp_path: Path) -> None:
    """The Sample Frame flagged the bottom bars of B1+B2 and B3+B4 against B5 at C2 and C5
    (Ø16, -16 mm): B5's bottom bars now pass 16 mm higher, scheduled in the second layer with
    the same lengths, and the crossings pass (0 mm: the bars touch, as the top bars do)."""
    from saengine.pipeline.drawings import rebar_cages

    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    found = rebar_cages(root)
    crossing = [c for c in found["checks"] if "cross at one level" in c["name"]]
    bottom = [c for c in crossing if c["name"].startswith("bottom")]
    assert {c["where"] for c in bottom} == {"joint C2 at L1", "joint C5 at L1"}
    assert all(c["ok"] and c["provided"] == pytest.approx(0.0) for c in crossing)

    from saengine.drawings.detailing import detailing_model

    plain = shutil.copytree(SAMPLE, tmp_path / "plain")
    model = detailing_model(plain)
    beams = {e["id"]: e for e in model["elements"] if e.get("kind") == "beam"}
    b5 = next(e for e in beams.values() if "B5" in (e.get("members") or [e["id"]]))
    assert b5["at"]["bottomRise"] == 16.0 and b5["at"]["topDrop"] == 16.0
    bottoms = [b for b in b5["bars"] if b["at"].get("face") == "bottom"]
    assert bottoms and all(b["at"]["layer"] == 2 for b in bottoms)
    assert any("bottom bars 16 mm higher" in n for n in b5["notes"])
    others = [e for e in beams.values() if e is not b5]
    assert others and all(not e["at"].get("bottomRise") for e in others)


def test_the_raised_bottom_bars_sit_in_the_raised_cage() -> None:
    """The closed stirrups go up with the raised bottom bars, as they go down with the dropped
    top bars: the core is shallower by both and its centre moves by half their difference."""
    from saengine.design.torsion import TorsionSection, perimeter_bars

    plain = TorsionSection(300, 500, 40, 10, 440)
    both = TorsionSection(300, 500, 40, 10, 440, top_drop=16, bottom_rise=20)
    assert both.core == (plain.core[0], plain.core[1] - 36)
    bars = [Bar(x, y, 201.0, 16) for x in (-92, 92) for y in (192 - 16, -192 + 20)]
    assert perimeter_bars(bars, both)[1] == 4


def test_the_former_joint_top_bars_key_is_read_as_joint_bars() -> None:
    """Owner decision 2026-11-11: the setting covers the top and the bottom bars, so it is
    ``construction.jointBars`` now; projects saved with ``jointTopBars`` keep their choice."""
    from saengine.design.rc_detailing import joint_mode
    from saengine.library.settings import Construction

    old = Construction.model_validate({"jointTopBars": "y"})
    assert old.jointBars == "y"
    assert "jointTopBars" not in old.model_dump()
    assert joint_mode(SimpleNamespace(construction=old)) == "y"
    both = Construction.model_validate({"jointTopBars": "y", "jointBars": "x"})
    assert both.jointBars == "x"
    assert Construction().jointBars == "auto"
