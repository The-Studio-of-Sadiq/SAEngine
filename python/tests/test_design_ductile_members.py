"""Seismic detailing of moment-frame beams and columns (BNBC 2020 Sec 8.3.4, 8.3.5, 8.3.9,
8.3.10, 8.3.12), checked against hand calculations on synthetic sections."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from saengine.design.ductile_members import (
    BeamNeed,
    ColumnNeed,
    Zones,
    _face_bars,
    _row,
    ash_per_spacing,
    beam_checks,
    beam_need,
    column_checks,
    face_steel,
    held_required,
    minimum_dimensions,
    propose_zones,
    rho_s_required,
    so_special,
    zones_of,
)
from saengine.design.rc import flexure, section_of
from saengine.library.objects import CircleProfile, LinearReinforcement, RectangleProfile

BAR = {d: math.pi * d**2 / 4 for d in (8, 10, 12, 16, 20, 25)}
#: Above 0.1 Ag f'c of the 500 x 500, f'c 30 column (750 kN): the column rules of 8.3.5.
HEAVY = (2.0e6, "1.2D + 1.0E + 1.0L")


def reinforcement(groups, transverse) -> LinearReinforcement:
    return LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": p, "count": n, "dia": d} for p, n, d in groups],
            "transverse": transverse,
        }
    )


def by_name(detailing, start: str) -> dict:
    rows = [c for c in detailing.checks if c["name"].startswith(start)]
    assert len(rows) == 1, [c["name"] for c in detailing.checks]
    return rows[0]


def names(detailing) -> list[str]:
    return [c["name"] for c in detailing.checks]


STIRRUPS = {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2}


def smf_beam(bottom=(3, 16), top=(3, 20), b=300, h=500):
    r = reinforcement([("top", *top), ("bottom", *bottom)], STIRRUPS)
    return section_of(RectangleProfile(xDim=b, yDim=h), r, 25, 420), r


# ─────────────────────────────────────── beams ───────────────────────────────────────


def test_smf_beam_spacing_limits_by_hand() -> None:
    # 300x500, cover 40, Ø10 stirrups: d (top, 3Ø20) = 500 - 40 - 10 - 10 = 440, d (bottom,
    # 3Ø16) = 442: d = 440. 8.3.4.3(b): min(d/4 = 110, 8 x 16 = 128, 24 x 10 = 240, 300) =
    # 110 over 2h = 1000 mm; elsewhere d/2 = 220 (8.3.4.3(c)); laps min(d/4, 100) = 100.
    section, r = smf_beam()
    result = beam_checks(section, r.transverse, "special", clear_span=5000)
    need = result.need
    assert isinstance(need, BeamNeed)
    assert need.d == pytest.approx(440)
    assert need.zone_spacing == pytest.approx(110)
    assert need.zone_length == pytest.approx(1000)
    assert need.outside_spacing == pytest.approx(220)
    assert need.splice_spacing == pytest.approx(100)
    assert need.first == 50
    # Old object type, no zone fields: the 150 mm spacing is taken for the whole length.
    ends = by_name(result, "Hoop spacing at the ends")
    assert (ends["demand"], ends["capacity"], ends["ok"]) == (150, 110, False)
    assert "no confinement zone given: spacing 150 mm used for the whole length" in result.notes
    assert by_name(result, "Hoop spacing elsewhere")["ok"]
    # With zones: Ø10 @ 100 over 1000 mm, the first at 50, laps @ 100.
    zones = Zones("stirrup", 10, 200, 2, zone_spacing=100, zone_length=1000, zone_first=50,
                  splice_spacing=100)  # fmt: skip
    result = beam_checks(section, r.transverse, "special", clear_span=5000, zones=zones)
    assert all(c["ok"] for c in result.checks), [c for c in result.checks if not c["ok"]]
    assert by_name(result, "Hoop zone length")["demand"] == 1000
    assert by_name(result, "Hoops over lap splices")["capacity"] == 100
    assert by_name(result, "Hoop spacing elsewhere")["demand"] == 200
    # 4d = 1760 mm against the clear span; 0.3 and 250 mm against the width.
    assert by_name(result, "Clear span")["demand"] == pytest.approx(1760)
    assert by_name(result, "Width to depth")["capacity"] == pytest.approx(0.6)
    # Least steel ratio max(0.25 √25, 1.4)/420 = 1.4/420 = 0.333 %; top 3Ø20 / (300 x 440).
    least_top = by_name(result, "Least steel ratio, top")
    assert least_top["demand"] == pytest.approx(0.33)
    assert least_top["capacity"] == pytest.approx(100 * 3 * BAR[20] / (300 * 440), abs=0.01)


def strain_compatibility_mn(as_t, d, as_c, d_c, b, fc, fy):
    """Mn of a rectangular section by hand: stress block 0.85 f'c over 0.85 c (β1 = 0.85),
    tension bars yielding, the other face's bars elastic (fs = 600 (c - d')/c, compression
    positive, less 0.85 f'c where they lie in the block), solved from the quadratic of
    equilibrium. Moments about the tension bars."""
    k = 0.85 * fc * b * 0.85

    def solve(displaced):
        # k c² + (600 As' - 0.85 f'c As' [displaced] - As fy) c - 600 As' d' = 0
        lin = 600 * as_c - (0.85 * fc * as_c if displaced else 0.0) - as_t * fy
        return (-lin + math.sqrt(lin**2 + 4 * k * 600 * as_c * d_c)) / (2 * k)

    c = solve(True)
    displaced = 0.85 * c > d_c
    if not displaced:
        c = solve(False)
    fs = 600 * (c - d_c) / c
    assert abs(fs) < fy  # elastic, as assumed
    force = as_c * (fs - (0.85 * fc if displaced else 0.0))
    return k * c * (d - 0.85 * c / 2) + force * (d - d_c)


def test_smf_beam_moment_fractions_with_rc_flexure() -> None:
    # 4Ø20 top, 2Ø12 bottom, 300 x 500, f'c 25, fy 420, cover 40, Ø10 stirrups.
    # Mn+ (sagging): d = 500 - 40 - 10 - 6 = 444; the top bars at d' = 60 lie below the
    # neutral axis (c = 49 mm) and are in tension at 135 MPa: Mn+ = 46.9 kN·m (41.5 kN·m
    # with them neglected). Mn- (hogging): d = 440, the Ø12 at d' = 56 in compression at
    # 222 MPa, c = 89 mm: Mn- = 211.4 kN·m. 8.3.4.2(a): Mn+ >= Mn-/2 = 105.7 fails, and
    # min(Mn) >= max(Mn)/4 = 52.9 fails.
    section, r = smf_beam(bottom=(2, 12), top=(4, 20))
    sag, hog = flexure(section, False), flexure(section, True)
    mn_pos = strain_compatibility_mn(2 * BAR[12], 444, 4 * BAR[20], 60, 300, 25, 420)
    mn_neg = strain_compatibility_mn(4 * BAR[20], 440, 2 * BAR[12], 56, 300, 25, 420)
    assert mn_pos == pytest.approx(46.9e6, rel=2e-3)
    assert mn_neg == pytest.approx(211.4e6, rel=2e-3)
    assert sag.mn == pytest.approx(mn_pos, rel=0.01)
    assert hog.mn == pytest.approx(mn_neg, rel=0.01)
    result = beam_checks(section, r.transverse, "special", capacities={False: sag, True: hog})
    face = by_name(result, "Positive moment strength at the face")
    assert face["demand"] == pytest.approx(round(hog.mn / 2e6, 2))
    assert face["capacity"] == pytest.approx(round(sag.mn / 1e6, 2))
    assert face["demand"] == pytest.approx(105.7, rel=0.01)
    assert not face["ok"]
    along = by_name(result, "Moment strength along the member")
    assert along["demand"] == pytest.approx(round(hog.mn / 4e6, 2))
    assert not along["ok"]
    # The smallest bar is now Ø12: 8 x 12 = 96 mm governs the hoop spacing.
    assert result.need.zone_spacing == pytest.approx(96)
    assert "8 db governs" in result.need.zone_rule
    # IMF fractions are 1/3 and 1/5 (8.3.10.4(a)): 46.9 >= 70.5 fails, 46.9 >= 42.3 passes.
    imf = beam_checks(section, r.transverse, "intermediate")
    assert by_name(imf, "Positive moment strength")["demand"] == pytest.approx(
        round(hog.mn / 3e6, 2)
    )
    assert by_name(imf, "Moment strength along")["demand"] == pytest.approx(round(hog.mn / 5e6, 2))
    assert not by_name(imf, "Positive moment strength")["ok"]
    assert by_name(imf, "Moment strength along")["ok"]
    # The 3Ø16 / 3Ø20 beam passes both: 3Ø16 Mn+ ≈ 108 kN·m against 162/2.
    section, r = smf_beam()
    assert by_name(beam_checks(section, r.transverse, "special"), "Positive moment")["ok"]


def test_smf_beam_failing_dimensional_limits() -> None:
    # 200 x 700: b < 250 mm, b/h = 0.286 < 0.3, and a clear span of 2000 mm < 4d (d = 640).
    section, r = smf_beam(b=200, h=700, top=(2, 20), bottom=(2, 20))
    result = beam_checks(section, r.transverse, "special", clear_span=2000)
    assert not by_name(result, "Width ≥ 250 mm")["ok"]
    ratio = by_name(result, "Width to depth")
    assert ratio["capacity"] == pytest.approx(0.29) and not ratio["ok"]
    span = by_name(result, "Clear span")
    assert span["demand"] == pytest.approx(4 * 640) and not span["ok"]
    # 900 wide on a 300 x 300 column: at most c2 + 2 min(c2, 0.75 c1) = 300 + 450 = 750 mm.
    section, r = smf_beam(b=900, h=500)
    result = beam_checks(section, r.transverse, "special", supports=[(300, 300), (600, 300)])
    first, second = (c for c in result.checks if c["name"].startswith("Width within"))
    assert (first["capacity"], first["ok"]) == (750, False)
    assert (second["capacity"], second["ok"]) == (900, True)  # 300 + 2 min(300, 450)
    # Axial compression above 0.1 Ag f'c = 0.1 x 900 x 500 x 25 = 1125 kN.
    result = beam_checks(section, r.transverse, "special", axial=(1.2e6, "1.2D + 1.0E + 1.0L"))
    axial = by_name(result, "Axial force of a flexural member")
    assert (axial["capacity"], axial["ok"]) == (1125, False)
    assert axial["combination"] == "1.2D + 1.0E + 1.0L"


def test_smf_beam_steel_ratio_and_lateral_support() -> None:
    # 250 x 400 with 6Ø25 top: ρ = 2945 / (250 x 327.5) = 3.6 % > 2.5 %. 6 bars in 250 mm do
    # not fit in one row, the outer row holds the bars on the hoop.
    section, r = smf_beam(b=250, h=400, top=(6, 25), bottom=(2, 16))
    result = beam_checks(section, r.transverse, "special")
    assert not by_name(result, "Largest steel ratio, top")["ok"]
    # 5 bars over 400 mm wide: gaps under 150 mm clear, the corners and the middle bar held
    # (2 + 3 // 2 = 3) - two stirrup legs are too few.
    section, r = smf_beam(b=400, h=600, top=(5, 20), bottom=(3, 16))
    result = beam_checks(section, r.transverse, "special")
    support = by_name(result, "Lateral support of the top bars")
    assert (support["demand"], support["capacity"], support["ok"]) == (3, 2, False)
    assert by_name(result, "Lateral support of the bottom bars")["ok"]
    assert held_required([(0, 20), (300, 20)]) == 2
    assert held_required([(0, 20), (200, 20), (400, 20)]) == 3  # 180 mm clear: all held


def test_imf_beam_stirrups_and_no_dimension_limits() -> None:
    # 8.3.10.4(b), (c): stirrups over 2h, min(d/4, 8 db, 24 ds, 300) = 110, d/2 = 220.
    section, r = smf_beam(b=220, h=500)  # 220 mm would fail an SMF beam's 250 mm
    result = beam_checks(section, r.transverse, "intermediate", clear_span=1000)
    assert not any("Width" in n or "Clear span" in n or "steel ratio" in n for n in names(result))
    assert by_name(result, "Stirrup spacing at the ends")["capacity"] == 110
    assert by_name(result, "Stirrup spacing elsewhere")["capacity"] == 220
    assert not any(n.startswith("Lateral support") for n in names(result))


def test_omf_and_gravity_beams() -> None:
    section, r = smf_beam()
    # OMF beams of the lateral system: Sec 8.3.9 gives no rule.
    result = beam_checks(section, r.transverse, "ordinary")
    assert result.checks == [] and "Chapter 6 governs" in result.notes[0]
    # Not in the lateral system, OMF/IMF (8.3.9.1(b)): 8.3.4.2(a) only.
    result = beam_checks(section, r.transverse, "ordinary", lateral=False)
    assert "Positive moment strength at the face (8.3.4.2(a))" in names(result)
    assert not any("spacing" in n for n in names(result))
    # SDC D, not in the SFRS (8.3.12.3(b)): 8.3.4.2 and stirrups at d/2, no hoop zones.
    result = beam_checks(section, r.transverse, "special", lateral=False, clear_span=1000)
    assert "Stirrup spacing elsewhere (8.3.12.3(b))" in names(result)
    assert not any("Clear span" in n or "at the ends" in n for n in names(result))


# ─────────────────────────────────────── columns ───────────────────────────────────────


def smf_column(legs=4, spacing=150, dia=10, count=12, bar=20, b=500, h=500, fc=30):
    r = reinforcement(
        [("perimeter", count, bar)], {"type": "tie", "dia": dia, "spacing": spacing, "legs": legs}
    )
    return section_of(RectangleProfile(xDim=b, yDim=h), r, fc, 420), r


def test_smf_column_lo_so_ash_by_hand() -> None:
    # 500 x 500, f'c 30, fy = fyt = 420, cover 40, Ø10 ties with 4 legs each way, 12Ø20.
    # lo = max(h = 500, 3000/6 = 500, 450) = 500 (8.3.5.4(d)).
    # hx = (420 - 2 x 10 - 20) / 3 = 126.7: so = 100 + (350 - 126.7)/3 = 174 -> 150.
    # s in lo <= min(500/4 = 125, 6 x 20 = 120, 150) = 120 (8.3.5.4(b)).
    # bc = 500 - 80 = 420, Ach = 420² = 176 400, Ag/Ach - 1 = 0.4172:
    # Ash/s = max(0.3 x 420 x 30/420 x 0.4172 = 3.755, 0.09 x 420 x 30/420 = 2.7) = 3.755.
    # 4 Ø10 legs = 314.2 mm²: s <= 83.7 mm. Outside lo: min(6 x 20, 150) = 120 (8.3.5.4(f)).
    section, r = smf_column()
    result = column_checks(section, r.transverse, "special", 40, clear_height=3000,
                           axial=(2.0e6, "1.2D + 1.0E + 1.0L"))  # fmt: skip
    need = result.need
    assert isinstance(need, ColumnNeed)
    assert need.zone_length == pytest.approx(500)
    assert need.hx == pytest.approx(380 / 3)
    assert need.so == pytest.approx(150)
    assert need.zone_spacing == pytest.approx(120)
    ash_s = 0.3 * 420 * 30 / 420 * (250000 / 176400 - 1)
    assert ash_s == pytest.approx(3.7551, rel=1e-4)
    assert need.ash_s == pytest.approx((ash_s, ash_s))
    assert need.outside_spacing == pytest.approx(120)
    assert need.first == pytest.approx(75)
    assert need.splice_spacing == pytest.approx(100)
    # The type's 150 mm (no zone given) fails the spacing and Ash = 563 mm² > 314 mm².
    ash_x = by_name(result, "Confinement Ash, bc along x, in lo")
    assert ash_x["demand"] == pytest.approx(ash_s * 150, abs=0.01)
    assert ash_x["capacity"] == pytest.approx(4 * BAR[10], abs=0.01)
    assert not ash_x["ok"]
    assert not by_name(result, "Tie spacing in lo")["ok"]
    assert "no confinement zone given: spacing 150 mm used for the whole length" in result.notes
    # Zone Ø10 @ 100: spacing fine, Ash 375.5 > 314.2 still fails; @ 75: 281.6 passes.
    for s, ok in ((100, False), (75, True)):
        zones = Zones("tie", 10, 100, 4, zone_spacing=s, zone_length=500, zone_first=50,
                      splice_spacing=75)  # fmt: skip
        result = column_checks(section, None, "special", 40, clear_height=3000, zones=zones,
                               axial=HEAVY)  # fmt: skip
        assert by_name(result, "Confinement Ash, bc along y")["ok"] is ok
        assert by_name(result, "Tie spacing in lo")["ok"]
    assert all(c["ok"] for c in result.checks), [c for c in result.checks if not c["ok"]]
    # A taller storey: lo = 4200/6 = 700.
    taller = column_checks(section, None, "special", 40, clear_height=4200, zones=zones,
                           axial=HEAVY)  # fmt: skip
    assert taller.need.zone_length == pytest.approx(700)
    assert not by_name(taller, "Confinement length lo")["ok"]
    # Formulas on their own.
    assert ash_per_spacing(420, 250000, 176400, 30, 420) == pytest.approx(ash_s)
    assert ash_per_spacing(420, 250000, 176400, 30, 900) == pytest.approx(
        ash_per_spacing(420, 250000, 176400, 30, 700)
    )  # fyt capped at 700 MPa (8.3.3.4(c))
    assert so_special(0) == 150 and so_special(350) == 100 and so_special(200) == 150
    assert so_special(260) == pytest.approx(130)


def test_smf_column_two_legs_and_dimensions() -> None:
    # Two legs across 500: hx = 380 > 350 (8.3.5.4(c)), so = 100 + (350 - 380)/3 -> 100.
    section, r = smf_column(legs=2)
    result = column_checks(section, r.transverse, "special", 40, clear_height=3000)
    hx = by_name(result, "Cross-tie spacing hx")
    assert hx["demand"] == pytest.approx(380) and not hx["ok"]
    assert result.need.so == 100 and result.need.zone_spacing == 100
    # 12 bars, 3 between corners per face at under 150 mm clear: 2 + 2 // 2 = 3 held.
    assert not by_name(result, "Lateral support of the top bars")["ok"]
    # 250 x 600: least dimension 250 < 300, 250/600 = 0.417 >= 0.4.
    section, r = smf_column(b=250, h=600, count=8, bar=16)
    result = column_checks(section, r.transverse, "special", 40, clear_height=3000)
    assert not by_name(result, "Least dimension")["ok"]
    assert by_name(result, "Least to perpendicular")["ok"]
    # 300 x 800: 0.375 < 0.4.
    section, r = smf_column(b=300, h=800, count=8, bar=16)
    result = column_checks(section, r.transverse, "special", 40)
    assert not by_name(result, "Least to perpendicular")["ok"]
    assert "clear height not given" in " ".join(result.notes)
    # ρg = 4 x 491 / 400² = 1.23 %; 4Ø16 in 500 x 500: 0.32 % < 1 %.
    section, r = smf_column(count=4, bar=16)
    assert not by_name(column_checks(section, r.transverse, "special", 40), "Least steel ratio")[
        "ok"
    ]


def test_smf_column_full_height_and_spiral() -> None:
    section, _ = smf_column()
    zones = Zones("tie", 10, 120, 4, zone_spacing=75, zone_length=500)
    result = column_checks(section, None, "special", 40, zones=zones, full_height=True,
                           axial=HEAVY)  # fmt: skip
    # Over the full height the 120 mm spacing must meet lo's 120 mm and Ash (450 > 314).
    assert by_name(result, "Tie spacing over the full height")["capacity"] == 120
    assert not by_name(result, "Confinement Ash, bc along x, over the full height")["ok"]
    # Spiral Ø10 at 50 mm in a 500 mm circle, cover 40: Dc = 420, Ag/Ach - 1 = 0.4172,
    # ρs >= max(0.12 x 30/420 = 0.857 %, 0.45 x 0.4172 x 30/420 = 1.341 %); provided
    # 4 x 78.5 / (420 x 50) = 1.496 %.
    spiral = reinforcement(
        [("perimeter", 8, 20)], {"type": "spiral", "dia": 10, "spacing": 50, "legs": 1}
    )
    section = section_of(CircleProfile(radius=250), spiral, 30, 420)
    rho = rho_s_required(math.pi * 250**2, math.pi * 210**2, 30, 420)
    assert rho == pytest.approx(0.45 * (250**2 / 210**2 - 1) * 30 / 420)
    assert rho == pytest.approx(0.01341, rel=1e-3)
    result = column_checks(section, spiral.transverse, "special", 40, clear_height=3000,
                           zones=Zones("spiral", 10, 50, 1, zone_spacing=50))  # fmt: skip
    check = by_name(result, "Confinement ρs, in lo")
    assert check["demand"] == pytest.approx(1.34, abs=0.01)
    assert check["capacity"] == pytest.approx(100 * 4 * BAR[10] / (420 * 50), abs=0.01)
    assert check["ok"]


def test_imf_column_by_hand() -> None:
    # 400 x 400, 8Ø16, Ø8 ties: so = min(8 x 16 = 128, 24 x 8 = 192, 400/2 = 200, 300) = 128
    # over lo = max(3000/6 = 500, 400, 450) = 500; first tie <= 64; 2 so = 256 elsewhere.
    section, r = smf_column(b=400, h=400, count=8, bar=16, dia=8, spacing=200, legs=2)
    result = column_checks(section, r.transverse, "intermediate", 40, clear_height=3000,
                           axial=(1.0e6, "1.2D + 1.0E + 1.0L"))  # fmt: skip
    need = result.need
    assert (need.zone_spacing, need.zone_length, need.first, need.outside_spacing) == (
        128,
        500,
        64,
        256,
    )
    assert not by_name(result, "Tie spacing in lo (8.3.10.5(a))")["ok"]  # 200 > 128, no zone
    assert by_name(result, "Tie spacing outside lo (8.3.10.5(d))")["ok"]
    assert not any("Ash" in n or "Least dimension" in n for n in names(result))
    zones = Zones("tie", 8, 200, 2, zone_spacing=125, zone_length=500, zone_first=60)
    result = column_checks(section, None, "intermediate", 40, clear_height=3000, zones=zones,
                           axial=(1.0e6, None))  # fmt: skip
    assert all(c["ok"] for c in result.checks)
    assert by_name(result, "First tie from the face (8.3.10.5(b))")["capacity"] == 64


def test_lightly_loaded_lateral_columns() -> None:
    # 400 x 600, 8Ø16 at 40 + 10 + 8 = 58 mm from each face, Ø10 ties, 2 legs at 150 mm,
    # f'c 25: 0.1 Ag f'c = 0.1 x 240 000 x 25 = 600 kN. d = min(600, 400) - 58 = 342 mm.
    section, r = smf_column(b=400, h=600, count=8, bar=16, dia=10, spacing=150, legs=2, fc=25)
    # IMF, Pu = 300 kN <= 600 kN: 8.3.10.2 sends it to 8.3.10.4 (not 8.3.10.5):
    # s <= min(d/4 = 85.5, 8 x 16 = 128, 24 x 10 = 240, 300) = 85.5 over 2h = 1200 mm;
    # first stirrup <= 50 mm; d/2 = 171 elsewhere. (8.3.10.5 would allow 128 mm.)
    light = column_checks(section, r.transverse, "intermediate", 40, clear_height=3000,
                          axial=(300e3, None))  # fmt: skip
    need = light.need
    assert need.zone_spacing == pytest.approx(85.5)
    assert (need.zone_length, need.first, need.outside_spacing) == (1200, 50, 171)
    row = by_name(light, "Tie spacing in lo (8.3.10.4(b))")
    assert (row["demand"], row["capacity"], row["ok"]) == (150, 85.5, False)
    assert by_name(light, "Tie spacing outside lo (8.3.10.4(c))")["ok"]  # 150 <= 171
    assert "8.3.10.4 apply (8.3.10.2)" in " ".join(light.notes)
    # Above 600 kN: 8.3.10.5, so = min(128, 240, 400/2 = 200, 300) = 128.
    heavy = column_checks(section, r.transverse, "intermediate", 40, clear_height=3000,
                          axial=(900e3, None))  # fmt: skip
    assert heavy.need.zone_spacing == pytest.approx(128)
    assert "Tie spacing in lo (8.3.10.5(a))" in names(heavy)
    # SMF, Pu <= 0.1 Ag f'c: the 8.3.5.4 rules with the 8.3.4.3 hoop rules, the stricter:
    # hx = (320 - 20 - 16) / 1 = 284 (2 legs across 400), so = 100 + (350 - 284)/3 = 122;
    # s <= min(400/4 = 100, 6 x 16 = 96, 122, d/4 = 85.5, 24 x 10 = 240, 300) = 85.5;
    # lo = max(600, 3000/6, 450, 2h = 1200) = 1200; elsewhere min(96, 150, d/2 = 171) = 96.
    smf = column_checks(section, r.transverse, "special", 40, clear_height=3000,
                        axial=(300e3, None))  # fmt: skip
    assert smf.need.zone_spacing == pytest.approx(85.5)
    assert smf.need.zone_length == pytest.approx(1200)
    assert smf.need.outside_spacing == pytest.approx(96)
    assert "Tie spacing in lo (8.3.5.4(b), 8.3.4.3(b))" in names(smf)
    assert any(n.startswith("Confinement Ash") for n in names(smf))
    # The same column above 600 kN: the column rules only, s <= 96 over lo = 600.
    smf = column_checks(section, r.transverse, "special", 40, clear_height=3000,
                        axial=(900e3, None))  # fmt: skip
    assert (smf.need.zone_spacing, smf.need.zone_length) == (96, 600)


def test_omf_and_gravity_columns() -> None:
    # 600 x 600, 8Ø25, Ø10 ties: 8.3.9.2 only above 0.1 Ag f'c = 0.1 x 360 000 x 25 = 900 kN.
    section, r = smf_column(b=600, h=600, count=8, bar=25, fc=25, spacing=250)
    low = column_checks(section, r.transverse, "ordinary", 40, axial=(800e3, None))
    assert low.checks == [] and "no tie rule" in low.notes[0]
    high = column_checks(section, r.transverse, "ordinary", 40, clear_height=3000,
                         axial=(1.5e6, None))  # fmt: skip
    # so = min(8 x 25 = 200, 24 x 10 = 240, 600/2 = 300) = 200 (no 300 mm cap in 8.3.9.2(b));
    # lo = max(500, 600, 450) = 600; 2 so = 400 anywhere.
    assert (high.need.zone_spacing, high.need.zone_length, high.need.outside_spacing) == (
        200,
        600,
        400,
    )
    assert not by_name(high, "Tie spacing in lo (8.3.9.2(b))")["ok"]
    # SDC D, not in the SFRS, low axial (8.3.12.3(b)): ties at d/2, d = 600 - 40 - 10 - 12.5.
    gravity = column_checks(section, r.transverse, "special", 40, lateral=False,
                            axial=(800e3, None))  # fmt: skip
    assert by_name(gravity, "Tie spacing (8.3.12.3(b))")["capacity"] == pytest.approx(268.75)
    # High axial: 8.3.5.3 and 8.3.5.4 but not the dimensional limits of 8.3.5.1.
    gravity = column_checks(section, r.transverse, "special", 40, lateral=False,
                            axial=(1.5e6, None))  # fmt: skip
    assert "Least steel ratio (8.3.12.3(c), 8.3.5.3(a))" in names(gravity)
    assert any(n.startswith("Confinement Ash") for n in names(gravity))
    assert not any(n.startswith("Least dimension") for n in names(gravity))


# ─────────────────────────────────── zones and design mode ───────────────────────────────────


def test_zones_of_old_and_new_objects() -> None:
    old = reinforcement([("perimeter", 8, 20)], {"type": "tie", "dia": 10, "spacing": 150})
    zones = zones_of(old.transverse)
    assert zones == Zones("tie", 10, 150, 2)
    assert not zones.has_zone and zones.in_zone == 150 and zones.across_depth == 2
    assert zones_of(None) is None
    new = {
        "type": "tie",
        "dia": 10,
        "spacing": 150,
        "legs": 4,
        "legsX": 3,
        "zone": {"spacing": 100, "length": 600},
        "splice": {"spacing": 100},
    }
    zones = zones_of(new)
    assert (zones.zone_spacing, zones.zone_length, zones.zone_first) == (100, 600, None)
    assert (zones.splice_spacing, zones.legs, zones.across_depth) == (100, 4, 3)
    # Attribute access (the pydantic model once it has the fields).
    obj = SimpleNamespace(type="stirrup", dia=8, spacing=200, legs=2, legsX=None,
                          zone=SimpleNamespace(spacing=90, length=None, first=50),
                          splice=None)  # fmt: skip
    zones = zones_of(obj)
    assert (zones.zone_spacing, zones.zone_first, zones.legs_x) == (90, 50, None)
    # No transverse reinforcement at all: one failing row.
    bare = reinforcement([("top", 2, 16), ("bottom", 2, 16)], None)
    section = section_of(RectangleProfile(xDim=300, yDim=500), bare, 25, 420)
    result = beam_checks(section, bare.transverse, "special")
    assert by_name(result, "Transverse reinforcement")["ok"] is False


def test_propose_zones_and_minimum_dimensions() -> None:
    section, r = smf_beam()
    need = beam_checks(section, r.transverse, "special").need
    assert propose_zones(need, 10, 2) == {
        "zone": {"length": 1000, "spacing": 100, "first": 50},
        "spacing": 200,
        "splice": {"spacing": 100},
    }
    # Shear asking for 150 mm keeps the outside spacing within it.
    assert propose_zones(need, 10, 2, shear_spacing=150)["spacing"] == 150
    section, r = smf_column()
    need = column_checks(section, r.transverse, "special", 40, clear_height=3000, axial=HEAVY).need
    # Ash: s <= 314.2 / 3.755 = 83.7 -> 75; outside min(6 x 20, 150) = 120 -> 100.
    assert propose_zones(need, 10, 4) == {
        "zone": {"length": 500, "spacing": 75, "first": 75},
        "spacing": 100,
        "splice": {"spacing": 75},
    }
    gravity = beam_checks(section, r.transverse, "ordinary", lateral=False).need
    assert propose_zones(gravity, 10, 2) is None
    assert minimum_dimensions("beam", "special", 900) == {"width": 270}
    assert minimum_dimensions("column", "special") == {"least": 300, "ratio": 0.4}
    assert minimum_dimensions("beam", "intermediate", 900) == {}


def test_unknown_frame() -> None:
    section, r = smf_beam()
    with pytest.raises(ValueError):
        beam_checks(section, r.transverse, "dual")


# ────────────────────────────── review regressions ──────────────────────────────


def test_beam_face_steel_leaves_out_side_bars() -> None:
    # 300x600, f'c 25, Ø10 stirrups, 2Ø16 top and bottom, 4Ø12 side bars. Top: d = 600 - 40
    # - 10 - 8 = 542, As = 2 x 201.1 = 402.1, ρ = 402.1 / (300 x 542) = 0.247 % < 1.4/420 =
    # 0.333 % (8.3.4.2(a)): fails, the side bars not counted. 2 + 2 continuous bars.
    r = reinforcement([("top", 2, 16), ("bottom", 2, 16), ("sides", 4, 12)], STIRRUPS)
    section = section_of(RectangleProfile(xDim=300, yDim=600), r, 25, 420)
    result = beam_checks(section, r.transverse, "special")
    low = by_name(result, "Least steel ratio, top")
    assert low["capacity"] == pytest.approx(100 * 2 * BAR[16] / (300 * 542), abs=0.01)
    assert low["demand"] == pytest.approx(100 * 1.4 / 420, abs=0.01)
    assert not low["ok"]
    assert "2 top, 2 bottom" in by_name(result, "Continuous bars")["note"]
    assert result.need.d == pytest.approx(542)

    # One top bar and side bars: the two-bar rule fails on the top.
    r = reinforcement([("top", 1, 20), ("bottom", 2, 16), ("sides", 2, 12)], STIRRUPS)
    section = section_of(RectangleProfile(xDim=300, yDim=600), r, 25, 420)
    row = by_name(beam_checks(section, r.transverse, "special"), "Continuous bars")
    assert (row["demand"], row["capacity"], row["ok"]) == (2, 1, False)
    assert "1 top, 2 bottom" in row["note"]


def test_beam_face_steel_keeps_inner_rows() -> None:
    # 300x500, Ø10 stirrups: 200 mm clear inside the stirrups holds 4Ø25 at 25 mm clear
    # (4 x 25 + 3 x 25 = 175); the other 2Ø25 go into a second row, its outer edge 25 mm below
    # the first: y = 187.5 and 137.5. d = 250 + (4 x 187.5 + 2 x 137.5)/6 = 420.8. The side
    # bars stay out.
    r = reinforcement([("top", 6, 25), ("bottom", 2, 16), ("sides", 2, 12)], STIRRUPS)
    section = section_of(RectangleProfile(xDim=300, yDim=500), r, 25, 420)
    top = face_steel(section, True)
    assert len(top) == 6
    assert sorted({round(b.y, 1) for b in top}) == [137.5, 187.5]
    assert [b.dia for b in face_steel(section, False)] == [16, 16]
    low = by_name(beam_checks(section, r.transverse, "special"), "Least steel ratio, top")
    assert low["capacity"] == pytest.approx(100 * 6 * BAR[25] / (300 * 420.83), abs=0.01)


def test_column_face_keeps_larger_corner_bars() -> None:
    # 400x400, f'c 30, cover 40, Ø10 ties with 2 legs, 4Ø25 corners + 12Ø16: 3 Ø16 on each face
    # between the corners, 5 bars per face. The Ø25 centres sit 4.5 mm further in, their
    # outer edges with the Ø16's. Clear between bars (275/4 - 20.5) < 150 mm: every corner
    # and alternate bar held, 2 + 3 // 2 = 3 legs > 2 (8.1.9.4(c)) on every face.
    r = reinforcement(
        [("perimeter", 4, 25), ("perimeter", 12, 16)],
        {"type": "tie", "dia": 10, "spacing": 100, "legs": 2},
    )
    section = section_of(RectangleProfile(xDim=400, yDim=400), r, 30, 420)
    for axis, sign in (("y", 1), ("y", -1), ("x", 1), ("x", -1)):
        assert len(_face_bars(section, axis, sign)) == 5
    result = column_checks(section, r.transverse, "special", 40, axial=(2000e3, None))
    rows = [c for c in result.checks if c["name"].startswith("Lateral support")]
    assert len(rows) == 4
    assert all((c["demand"], c["capacity"], c["ok"]) == (3, 2, False) for c in rows)

    # A beam with a mixed top row (2Ø20 corners + 2Ø16) keeps its corners: 4 bars, 3 held.
    r = reinforcement([("top", 2, 20), ("top", 2, 16), ("bottom", 3, 16)], STIRRUPS)
    section = section_of(RectangleProfile(xDim=400, yDim=600), r, 25, 420)
    assert len(_face_bars(section, "y", 1)) == 4
    row = by_name(beam_checks(section, r.transverse, "special"), "Lateral support of the top")
    assert (row["demand"], row["capacity"]) == (3, 2)


def test_omf_column_without_ties_has_no_rule_at_low_axial() -> None:
    # 500x500, f'c 30, 8Ø20, no transverse steel. 0.1 Ag f'c = 750 kN: at 100 kN BNBC 8.3.9.2
    # sets no tie rule, so no row; at 1000 kN the missing ties fail.
    r = reinforcement([("perimeter", 8, 20)], None)
    section = section_of(RectangleProfile(xDim=500, yDim=500), r, 30, 420)
    low = column_checks(section, None, "ordinary", 40, axial=(100e3, None))
    assert low.checks == []
    assert any("no tie rule" in n for n in low.notes)
    high = column_checks(section, None, "ordinary", 40, axial=(1000e3, None))
    assert [(c["name"], c["ok"]) for c in high.checks] == [("Ties (8.3)", False)]


def test_rows_and_needs_are_finite() -> None:
    # One tie leg: hx is taken between the corner bars, (500 - 80 - 20 - 20) / 1 = 380 mm.
    section, r = smf_column(legs=1, count=8, spacing=100)
    result = column_checks(section, r.transverse, "special", 40, axial=(2000e3, None))
    hx = by_name(result, "Cross-tie spacing hx")
    assert hx["demand"] == pytest.approx(380) and not hx["ok"]
    json.dumps(result.checks, allow_nan=False)
    assert any("fewer than 2 tie legs" in n for n in result.notes)
    # A beam with no spacing rule outside the zones: None, not infinity.
    beam, _ = smf_beam()
    assert beam_need(beam, "intermediate", 10, lateral=False).outside_spacing is None
    assert _row("x", math.inf, 1, "")["demand"] == 0.0
