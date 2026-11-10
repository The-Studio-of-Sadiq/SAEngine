"""Walk 4 engineering majors:

- W4A-10: the seismic hoops proposed over the lap splices keep within min(d/4, ...) at the d
  the checks take (the top bars in the second layer at the joints, ``topDrop``), rounded down
  to the pack's spacing step (whole inches in the US pack);
- W4A-11: an apply that changes only bars hands back the floor plan and the BIM model as they
  were (not re-indented), so the page does not call the analysis out of date;
- W4B-9: the floor response spectra of an isolated building take the isolation damping on
  the isolated modes;
- W4B-13: floor vibration says where slabs were not checked (no shells) in the Charts table
  and prints the method by name;
- W4B-10: a soft clay with SPTs and no consolidation tests takes mv from N60 (Stroud &
  Butler 1975), not the modulus number of a soft silty clay.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

BEAM_BARS = {
    "material": "B420DWR",
    "cover": 40,
    "longitudinal": [
        {"position": "top", "count": 3, "dia": 22},
        {"position": "bottom", "count": 2, "dia": 19},
    ],
    "transverse": {"type": "stirrup", "dia": 10, "spacing": 125, "legs": 2},
}


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


# ─────────────────────────────── W4A-10 ───────────────────────────────


def test_us_pack_rounds_spacings_to_whole_inches() -> None:
    from saengine.design.bars import spacing_step

    with code_context.using(registry.load("aci318-asce7-22")):
        assert spacing_step() == pytest.approx(25.4)
    with code_context.using(registry.load("bnbc2020")):
        assert spacing_step() == 25.0


@pytest.mark.parametrize("pack", ["aci318-asce7-22", "bnbc2020"])
def test_splice_hoops_keep_within_the_checked_limit(pack: str) -> None:
    from saengine.design import ductile_members as dm
    from saengine.design.bars import spacing_step
    from saengine.design.proposal import seismic_transverse
    from saengine.design.rc import section_of, with_top_drop
    from saengine.design.required import Options
    from saengine.library.objects import Beam, LinearReinforcement

    beam = Beam.model_validate(
        {
            "id": "B275x475",
            "name": "Beam",
            "material": "C27.6",
            "profile": {"shape": "rectangle", "xDim": 275, "yDim": 475},
        }
    )
    with code_context.using(registry.load(pack)):
        found, _ = seismic_transverse(
            "beam",
            beam,
            json.loads(json.dumps(BEAM_BARS)),
            [{"seismicContext": {"level": "special", "lateral": True}, "topDrop": 16.0}],
            27.6,
            420.0,
            200_000.0,
            None,
            Options.of({}),
        )
        splice = found["transverse"]["splice"]["spacing"]
        # The check's section: the chosen ties, the top bars 16 mm lower at the joints.
        bars = {**BEAM_BARS, "transverse": found["transverse"]}
        section = with_top_drop(
            section_of(beam.profile, LinearReinforcement.model_validate(bars), 27.6, 420.0), 16.0
        )
        limit = dm.beam_splice_spacing(dm._effective_depth(section))[0]
        step = spacing_step()
    # US4: 100 mm (3.94 in) against 99.5 mm (3.92 in) before; now 76.2 mm (3 in).
    assert splice <= limit + 1e-9
    assert splice / step == pytest.approx(round(splice / step))


# ─────────────────────────────── W4A-11 ───────────────────────────────


def test_unchanged_part_comes_back_as_it_was() -> None:
    from saengine.design.proposal import _dump

    compact = '{"schema": "saengine.floorPlan/1", "beams": [{"id": "B1", "type": "B1"}]}'
    assert _dump(json.loads(compact), compact) is compact
    changed = json.loads(compact)
    changed["beams"][0]["type"] = "B1-2"
    assert json.loads(_dump(changed, compact))["beams"][0]["type"] == "B1-2"


# ─────────────────────────────── W4B-9 ───────────────────────────────


def test_floor_spectrum_takes_the_isolation_damping(tmp_path) -> None:
    from saengine.fem import floor_spectra as fs
    from saengine.fem.isolation import ISOLATION_FILE, SCHEMA

    periods = np.geomspace(0.02, 4.0, 60)
    ground = np.where(periods < 0.5, 0.2 + 0.5 * periods / 0.5, 0.7 * 0.5 / periods)
    ground = np.minimum(ground, 0.45)
    omegas = [2 * math.pi / 1.0, 2 * math.pi / 0.24]
    terms = [0.86, 0.14]
    plain = fs.direct_floor_spectrum(periods, ground, omegas, terms, 0.05, 0.05, 20.0, 4)
    (tmp_path / ISOLATION_FILE).write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "available": True,
                "spectrum": {"modalDamping": 26.7, "B": 1.63, "dampedFrom": 0.78},
            }
        ),
        encoding="utf-8",
    )
    zetas, note = fs._isolation_damping(tmp_path / "model.osmodel", omegas, 0.05)
    assert zetas == [pytest.approx(0.267), 0.05] and "isolation damping" in note
    damped = fs.direct_floor_spectrum(periods, ground, omegas, terms, 0.05, 0.05, 20.0, 4, zetas)
    # W4B-3storey level 3: peak 2.99 g → 0.82 g, zero-period 0.42 g → 0.19 g (site 0.21 g).
    assert damped.max() < 0.6 * plain.max()
    assert damped[0] < plain[0]
    # Without an isolation design every mode keeps the structure's damping.
    assert fs._isolation_damping(tmp_path / "none" / "model.osmodel", omegas, 0.05) == (None, "")


# ─────────────────────────────── W4B-13 ───────────────────────────────


def test_floor_vibration_table_names_method_and_unchecked_slabs() -> None:
    from saengine.fem import floor_vibration as fv

    row = {
        "slab": "S1", "story": "L1", "occupancy": "Office", "floor": "concrete",
        "method": "responseFactor", "deflection": 1.0, "fn": 9.0, "w": 5.0, "bay": [5.0, 6.0],
        "value": 1.78, "limit": 8.0, "unit": "", "ok": True,
    }  # fmt: skip
    note = "2 slabs not checked (S2, S3): floor vibration needs the slabs analysed as shells"
    sheet = fv.sheet([row], "source", [note])
    assert sheet["rows"][0][4] == "response factor R"
    assert sheet["notes"] == [note, "source"]


# ─────────────────────────────── W4B-10 ───────────────────────────────


def test_soft_clay_mv_from_spt() -> None:
    from saengine.soil.profile import SoilLayer
    from saengine.soil.settlement import stroud_mv

    def clay(n60: float | None, pi: float | None = None) -> SoilLayer:
        return SoilLayer(
            index=0, top=0.0, bottom=4.0, soil_type="clay", description="soft clay",
            behaviour="cohesive", gamma=17.0, gamma_sat=18.0, cu=4.5 * (n60 or 0), n60=n60,
            pi=pi,
        )  # fmt: skip

    # N 4-6, PI unknown: mv 0.37-0.56 m²/MN (soft-to-firm clay 0.3-1.0); was about 2 m²/MN.
    assert stroud_mv(clay(4.0)) * 1e3 == pytest.approx(1 / 1.8, rel=1e-6)
    assert stroud_mv(clay(6.0)) * 1e3 == pytest.approx(1 / 2.7, rel=1e-6)
    assert stroud_mv(clay(5.0, pi=20.0)) * 1e3 == pytest.approx(1 / 3.0, rel=1e-6)
    assert stroud_mv(clay(None)) is None
