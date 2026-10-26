"""The log sheet in the soil report: SPT increments and refusals, the laboratory tests of the
samples, and the layer values derived from them, against hand calculations."""

from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from saengine.library.soil import Grading, Sample, SoilReport, SptRecord, check
from saengine.soil import lab, soil_report
from saengine.soil.profile import GAMMA_W, Profile

# ─────────────────────────────── SPT ───────────────────────────────


def test_spt_increments_give_n() -> None:
    record = SptRecord.model_validate({"depth": 1500, "seat": 5, "N1": 12, "N2": 14})
    assert record.blows == 26 and record.derived == 26
    # The worked-out N is not stored as if entered.
    assert record.N is None and "N" not in record.model_dump(exclude_none=True)
    # An entered N that agrees is kept; one that differs is kept and reported as a problem.
    agrees = SptRecord.model_validate({"depth": 1500, "N": 26, "N1": 12, "N2": 14})
    assert agrees.blows == 26 and agrees.mismatch is None and agrees.issues == []
    differs = SptRecord.model_validate({"depth": 1500, "N": 25, "N1": 12, "N2": 14})
    assert differs.blows == 25
    assert differs.mismatch == "N is 25 but N1 + N2 = 12 + 14 = 26; N 25 is used"
    report = SoilReport.model_validate(
        {
            "boreholes": [
                {
                    "id": "BH-1",
                    "layers": [{"top": 0, "bottom": 3000, "soilType": "sand"}],
                    "spt": [{"depth": 1500, "N": 25, "N1": 12, "N2": 14}],
                }
            ]
        }
    )
    assert any("SPT at 1.5 m: N is 25 but" in p for p in check(report))
    with pytest.raises(ValidationError, match="both increments"):
        SptRecord.model_validate({"depth": 1500, "N1": 12})
    with pytest.raises(ValidationError, match="needs N"):
        SptRecord.model_validate({"depth": 1500, "seat": 4})


def test_spt_refusal_is_extrapolated_to_300_mm() -> None:
    # 50 blows for 100 mm: 50 × 300/100 = 150; 50/150 mm: 100 (the old convention).
    r = SptRecord.model_validate({"depth": 9000, "refusal": {"blows": 50, "penetration": 100}})
    assert r.blows == 150 and r.refusal is not None and r.refusal.text == "50/100 mm"
    assert r.N is None and r.issues == []
    r = SptRecord.model_validate({"depth": 9000, "refusal": {"blows": 50, "penetration": 150}})
    assert r.blows == 100
    # 100 blows for 50 mm would be 600: capped at the field's 300.
    r = SptRecord.model_validate({"depth": 9000, "refusal": {"blows": 100, "penetration": 50}})
    assert r.blows == 300
    # An entered N (e.g. the consultant's cap of 50) wins over the extrapolation, reported.
    r = SptRecord.model_validate(
        {"depth": 9000, "N": 50, "refusal": {"blows": 50, "penetration": 100}}
    )
    assert r.blows == 50
    assert r.mismatch == "N is 50 but the refusal 50/100 mm scales to 150 over 300 mm; N 50 is used"
    # N1 completed, refusal in the third increment: 30 + 20 blows for 150 + 60 mm.
    r = SptRecord.model_validate(
        {"depth": 9000, "N1": 30, "refusal": {"blows": 50, "penetration": 210}}
    )
    assert r.blows == round(50 * 300 / 210) and r.issues == []
    # A refusal with N2 is used (the refusal gives N) and reported, not rejected.
    r = SptRecord.model_validate(
        {"depth": 9000, "N1": 20, "N2": 30, "refusal": {"blows": 50, "penetration": 100}}
    )
    assert r.blows == 150
    assert any("did not reach 300 mm, N2 is ignored" in i for i in r.issues)
    assert any("does not fit the refusal" in i for i in r.issues)


def test_spt_half_entered_rows_keep_the_report_readable() -> None:
    # N with only one increment, or a depth-to above the depth: N is used, the row reported.
    r = SptRecord.model_validate({"depth": 3000, "N": 25, "N1": 12})
    assert r.blows == 25
    assert r.issues == ["only N1 of the increments is given; the entered N 25 is used"]
    r = SptRecord.model_validate({"depth": 3000, "depthTo": 2000, "N": 25})
    assert r.blows == 25 and "is above the depth 3 m; it is ignored" in r.issues[0]
    report = SoilReport.model_validate(
        {
            "boreholes": [
                {
                    "id": "B",
                    "layers": [{"top": 0, "bottom": 5000, "soilType": "sand"}],
                    "spt": [{"depth": 3000, "N": 25, "N2": 12}],
                }
            ]
        }
    )
    assert check(report) == [
        "B: SPT at 3 m: only N2 of the increments is given; the entered N 25 is used"
    ]


def test_spt_correcting_increments_after_a_save_changes_n() -> None:
    from saengine.soil.report import dumps, parse

    text = json.dumps(
        {
            "boreholes": [
                {
                    "id": "B",
                    "layers": [{"top": 0, "bottom": 5000, "soilType": "sand"}],
                    "spt": [
                        {"depth": 1500, "N1": 10, "N2": 12},
                        {"depth": 3000, "refusal": {"blows": 50, "penetration": 100}},
                    ],
                }
            ]
        }
    )
    parsed = parse(text)
    assert isinstance(parsed, SoilReport)
    saved = json.loads(dumps(parsed))
    spt = saved["boreholes"][0]["spt"]
    assert "N" not in spt[0] and "N" not in spt[1]
    spt[0]["N1"] = 15
    spt[1]["refusal"]["penetration"] = 250
    report = SoilReport.model_validate(saved)
    assert [r.blows for r in report.boreholes[0].spt] == [27, 60]
    assert check(report) == []


OLD_REPORT = {
    "schema": "saengine.soilReport/1",
    "report": {"title": "Synthetic"},
    "groundLevel": 0.0,
    "boreholes": [
        {
            "id": "BH-1",
            "x": 1000.0,
            "y": 2000.0,
            "position": "project",
            "waterTable": 1500.0,
            "layers": [
                {"top": 0.0, "bottom": 6000.0, "description": "", "soilType": "clay", "cu": 30.0},
                {"top": 6000.0, "bottom": 15000.0, "description": "", "soilType": "sand"},
            ],
            "spt": [{"depth": 1500.0, "N": 4}, {"depth": 7500.0, "N": 18}],
            "samples": [
                {
                    "depth": 3000.0,
                    "type": "UD",
                    "moisture": 32.0,
                    "unitWeight": 18.2,
                    "liquidLimit": 42.0,
                    "plasticLimit": 22.0,
                    "nonPlastic": False,
                }
            ],
        }
    ],
}


def test_old_files_load_unchanged() -> None:
    """A report with only the earlier fields loads, means the same and is written back the same
    (the new fields' defaults aside: ``position`` and ``nonPlastic``)."""
    old = json.loads(json.dumps(OLD_REPORT))
    for hole in old["boreholes"]:
        hole.pop("position")
        for sample in hole["samples"]:
            sample.pop("nonPlastic")
    report = SoilReport.model_validate(old)
    dumped = report.model_dump(mode="json", by_alias=True, exclude_none=True)
    dumped.pop("design")
    assert dumped == OLD_REPORT
    assert [r.N for r in report.boreholes[0].spt] == [4, 18]
    assert "site" not in dumped


# ─────────────────────────────── grading and USCS ───────────────────────────────


def grading(*points: tuple[float, float]) -> Grading:
    return Grading.model_validate({"sieves": [{"size": s, "passing": p} for s, p in points]})


def test_grading_sizes_by_log_interpolation() -> None:
    curve = grading(
        (4.75, 100), (2.0, 90), (0.85, 70), (0.425, 50), (0.25, 30), (0.15, 15), (0.075, 3)
    )
    g = lab.grading_summary(curve)
    # D10 between 0.15 mm (15 %) and 0.075 mm (3 %): 0.075 · 2^((10 - 3)/12).
    d10 = 0.075 * 2 ** (7 / 12)
    d60 = 0.425 * 2 ** ((60 - 50) / 20)  # between 0.85 (70 %) and 0.425 (50 %)
    assert g["D10"] == pytest.approx(d10) and g["D30"] == pytest.approx(0.25)
    assert g["D60"] == pytest.approx(d60)
    assert g["Cu"] == pytest.approx(d60 / d10)  # 5.35
    assert g["Cc"] == pytest.approx(0.25**2 / (d10 * d60))  # 0.925
    assert g["fines"] == pytest.approx(3) and g["gravel"] == 0 and g["sand"] == pytest.approx(97)
    assert g["clayFraction"] is None  # the curve stops at 0.075 mm
    # Cu < 6: poorly graded sand.
    assert lab.uscs(g, None, None)["symbol"] == "SP"


@pytest.mark.parametrize(
    ("points", "ll", "pl", "np_", "symbol"),
    [
        # D60 = 1, D30 = 0.4, D10 = 0.1: Cu = 10, Cc = 1.6 → SW (4 % fines).
        ([(4.75, 100), (1.0, 60), (0.4, 30), (0.1, 10), (0.075, 4)], None, None, False, "SW"),
        # D30 = 0.3: Cc = 0.9 < 1 → SP.
        ([(4.75, 100), (1.0, 60), (0.3, 30), (0.1, 10), (0.075, 4)], None, None, False, "SP"),
        # Gravel 60 % of the soil: D60 = 10, D30 = 2, D10 = 0.6: Cu 16.7, Cc 0.67 → GP.
        (
            [(50, 100), (10, 60), (4.75, 40), (2, 30), (0.6, 10), (0.075, 3)],
            None,
            None,
            False,
            "GP",
        ),
        # 8 % non-plastic fines, Cu 10, Cc 0.9: SP-SM.
        ([(4.75, 100), (1.0, 60), (0.3, 30), (0.1, 10), (0.075, 8)], None, None, True, "SP-SM"),
        # 20 % fines, LL 35, PI 15 above the A-line (10.95): SC.
        ([(4.75, 100), (0.425, 60), (0.075, 20)], 35, 20, False, "SC"),
        # PI 6 (4-7) above the A-line (3.65): SC-SM.
        ([(4.75, 100), (0.425, 60), (0.075, 20)], 25, 19, False, "SC-SM"),
        # PI 2 < 4: SM.
        ([(4.75, 100), (0.425, 60), (0.075, 20)], 25, 23, False, "SM"),
        # Fine-grained: LL 45, PI 25 ≥ A 18.25 → CL; LL 60, PI 15 < A 29.2 → MH; PI 35 → CH.
        ([(0.425, 100), (0.075, 80)], 45, 20, False, "CL"),
        ([(0.425, 100), (0.075, 90)], 60, 45, False, "MH"),
        ([(0.425, 100), (0.075, 90)], 60, 25, False, "CH"),
        ([(0.425, 100), (0.075, 90)], None, None, True, "ML"),
    ],
)
def test_uscs_group(points, ll, pl, np_, symbol) -> None:
    g = lab.grading_summary(grading(*points))
    assert lab.uscs(g, ll, pl, np_)["symbol"] == symbol


def test_uscs_only_what_the_data_decide() -> None:
    sand = lab.grading_summary(grading((4.75, 100), (0.425, 60), (0.075, 20)))
    assert lab.uscs(sand, None, None)["symbol"] == "S"  # fines of unknown plasticity
    silty = lab.grading_summary(grading((0.425, 100), (0.075, 70)))
    assert lab.uscs(silty, None, None)["symbol"] == "M or C"


def test_a_bad_sample_keeps_the_report_readable() -> None:
    # A curve whose % passing rises at a smaller sieve, a repeated sieve, and a bottom above
    # the top are data-entry typos: the sample loads, the bad part is ignored and reported.
    rising = Sample.model_validate(
        {
            "depth": 1000,
            "grainSize": {"sieves": [{"size": 2, "passing": 50}, {"size": 0.5, "passing": 60}]},
        }
    )
    assert rising.grading is None
    assert rising.issues == [
        "grain size: 60 % passing 0.5 mm is more than 50 % passing 2 mm; the curve is ignored"
    ]
    repeated = Sample.model_validate(
        {
            "depth": 1000,
            "grainSize": {"sieves": [{"size": 2, "passing": 50}, {"size": 2, "passing": 40}]},
        }
    )
    assert repeated.grading is None and "two sieves of the same size" in repeated.issues[0]
    upside = Sample.model_validate({"depth": 2000, "depthTo": 1500, "moisture": 20})
    assert upside.mid == 2000  # the bottom is ignored
    assert upside.issues == ["depth to 1.5 m is above the depth 2 m; it is ignored"]
    # In a report: every borehole still loads, check() names the sample, lab skips the curve.
    bad = {"number": "D-6", "depth": 2000, "liquidLimit": 40, "plasticLimit": 20}
    bad["grainSize"] = {"sieves": [{"size": 0.425, "passing": 45}, {"size": 0.25, "passing": 47}]}
    hole = clay_hole(bad)
    report = SoilReport.model_validate({"boreholes": [hole]})
    assert any("D-6: grain size: 47 % passing 0.25 mm" in p for p in check(report))
    summary = lab.summary(report.boreholes[0].samples[0])
    assert "grainSize" not in summary and summary["issues"]
    out = soil_report(json.dumps({"boreholes": [hole]}))
    assert "boreholes" in out and out["boreholes"][0]["lab"]


def test_sulphate_class_bounds() -> None:
    # S2 includes 2.00 % and 10 000 ppm; S3 starts above them (from memory, to be checked).
    def worst(**chem: float) -> str:
        return lab.chemistry_flags(Sample.model_validate({"depth": 1, "chemistry": chem}))[0]

    assert "class S2" in worst(sulphateSoil=2.0)
    assert "class S3" in worst(sulphateSoil=2.01)
    assert "class S2" in worst(sulphateWater=10_000)
    assert "class S3" in worst(sulphateWater=10_001)
    assert "class S2" in worst(sulphateSoil=0.20) and "class S1" in worst(sulphateSoil=0.10)
    assert "S0" in worst(sulphateSoil=0.09)


# ─────────────────────────────── strength and consolidation ───────────────────────────────


def test_strength_tests_feed_cu_c_phi() -> None:
    ucs = lab.feed(Sample.model_validate({"depth": 2000, "ucs": {"qu": 80}}))
    assert ucs["cu"] == (40.0, "UCS qu/2")
    # UU wins over the UCS; an entered cu over both.
    both = Sample.model_validate(
        {"depth": 2000, "ucs": {"qu": 80}, "triaxial": {"type": "UU", "cu": 45}}
    )
    assert lab.feed(both)["cu"] == (45.0, "triaxial UU")
    assert lab.feed(both.model_copy(update={"cu": 50.0}))["cu"] == (50.0, "")
    # Direct shear fitted: τ = 15 + 0.5 σn → c' = 15 kPa, φ' = atan 0.5 = 26.57°.
    shear = Sample.model_validate(
        {
            "depth": 2000,
            "directShear": {
                "specimens": [
                    {"normal": 50, "shear": 40},
                    {"normal": 100, "shear": 65},
                    {"normal": 200, "shear": 115},
                ]
            },
        }
    )
    values = lab.feed(shear)
    assert values["c"][0] == pytest.approx(15) and values["phi"][0] == pytest.approx(
        math.degrees(math.atan(0.5))
    )
    # A total-stress CU does not feed c', φ'; an effective one does.
    cu = {"depth": 2000, "triaxial": {"type": "CU", "c": 10, "phi": 18, "effective": False}}
    assert "phi" not in lab.feed(Sample.model_validate(cu))
    cu["triaxial"]["effective"] = True
    assert lab.feed(Sample.model_validate(cu))["phi"] == (18.0, "triaxial CU")
    # γ = γd (1 + w) = 16 × 1.2.
    dry = lab.feed(Sample.model_validate({"depth": 2000, "dryUnitWeight": 16, "moisture": 20}))
    assert dry["unitWeight"][0] == pytest.approx(19.2)


CONSOLIDATION = {
    "preconsolidation": 120,
    "e0": 1.02,
    "points": [
        {"pressure": 25, "e": 1.00},
        {"pressure": 50, "e": 0.98},
        {"pressure": 100, "e": 0.95},
        {"pressure": 200, "e": 0.86},
        {"pressure": 400, "e": 0.77},
        {"pressure": 100, "e": 0.79},
        {"pressure": 25, "e": 0.81},
    ],
}


def test_consolidation_fits_cc_and_cr() -> None:
    sample = Sample.model_validate({"depth": 4000, "consolidation": CONSOLIDATION})
    result = lab.consolidation(sample.consolidation)  # type: ignore[arg-type]
    # Loading beyond σ'p = 120 kPa: 200 and 400 kPa, 0.09 per 0.30103 log cycle.
    assert result["Cc"] == pytest.approx(0.09 / math.log10(2))
    # Unloading 400 → 100 → 25 kPa: 0.02 per log10(4).
    assert result["Cr"] == pytest.approx(0.02 / math.log10(4))


LOOP = [
    (25, 1.00), (50, 0.99), (100, 0.97),  # loading
    (50, 0.975), (25, 0.98),  # unload
    (50, 0.978), (100, 0.972),  # reload: recompression, not virgin
    (200, 0.92), (400, 0.83), (800, 0.74),  # virgin
    (200, 0.76), (50, 0.78),  # final unloading
]  # fmt: skip


def test_consolidation_with_an_unload_reload_loop() -> None:
    def run(**extra: object) -> dict:
        test = {"points": [{"pressure": p, "e": e} for p, e in LOOP], **extra}
        sample = Sample.model_validate({"depth": 4000, "consolidation": test})
        return lab.consolidation(sample.consolidation)  # type: ignore[arg-type]

    # Without σ'p: the last two virgin points, (0.83 - 0.74)/log10(2) = 0.299.
    result = run()
    assert result["Cc"] == pytest.approx(0.09 / math.log10(2))
    # The final unloading 800 → 200 → 50 kPa is a straight line: 0.02 per log10(4) = 0.0332.
    assert result["Cr"] == pytest.approx(0.02 / math.log10(4))
    assert "800 kPa" in result["how"]["Cr"]
    # With σ'p = 150 kPa: the virgin points 200, 400, 800 kPa (0.92, 0.83, 0.74) lie on a line
    # of 0.09 per log10(2); the reload points at 50 and 100 kPa are not virgin.
    result = run(preconsolidation=150)
    assert result["Cc"] == pytest.approx(0.09 / math.log10(2))


def test_triaxial_cu_with_some_pore_pressures_fits_total_stresses() -> None:
    # (σ3, σ1 - σ3, u): fitted to total stresses only; p = σ3 + q, q = (σ1 - σ3)/2.
    specimens = [
        {"cell": 100, "deviator": 120, "porePressure": 40},
        {"cell": 200, "deviator": 200},
        {"cell": 300, "deviator": 280, "porePressure": 120},
    ]
    test = Sample.model_validate(
        {"depth": 1, "triaxial": {"type": "CU", "specimens": specimens}}
    ).triaxial
    out = lab.triaxial(test)  # type: ignore[arg-type]
    # Total points (160, 60), (300, 100), (440, 140): slope 40/140, intercept 60 - 160·2/7.
    slope, a = 40 / 140, 60 - 160 * 40 / 140
    phi = math.asin(slope)
    assert out is not None and not out["effective"]
    assert out["phi"] == pytest.approx(math.degrees(phi))
    assert out["c"] == pytest.approx(a / math.cos(phi))
    assert "not given for every specimen" in out["how"]


def clay_hole(*samples: dict, **layer: object) -> dict:
    return {
        "id": "BH-1",
        "waterTable": 2000,
        "layers": [
            {
                "top": 0,
                "bottom": 10000,
                "soilType": "clay",
                "unitWeight": 18,
                "saturatedUnitWeight": 19,
                **layer,
            }
        ],
        "spt": [{"depth": 3000, "N": 6}],
        "samples": list(samples),
    }


def profile_of(hole: dict) -> Profile:
    report = SoilReport.model_validate({"boreholes": [hole]})
    return Profile(report, report.boreholes[0])


def test_layer_takes_ocr_from_the_consolidation_sample() -> None:
    p = profile_of(
        clay_hole({"depth": 4000, "depthTo": 4500, "type": "UD", "consolidation": CONSOLIDATION})
    )
    layer = p.layers[0]
    # σ'v0 at the mid-depth 4.25 m: 18 × 2 + 19 × 2.25 - 9.81 × 2.25 = 56.6775 kPa.
    sigma = 18 * 2 + 19 * 2.25 - GAMMA_W * 2.25
    assert layer.ocr == pytest.approx(120 / sigma)
    assert layer.sources["OCR"] == "σ'p/σ'v0 of samples (1)"
    assert layer.cc == pytest.approx(0.09 / math.log10(2))
    assert layer.cr == pytest.approx(0.02 / math.log10(4))
    assert layer.e0 == pytest.approx(1.02)
    # The log's own OCR wins.
    logged = profile_of(clay_hole({"depth": 4000, "consolidation": CONSOLIDATION}, OCR=1.5))
    assert logged.layers[0].ocr == 1.5 and logged.layers[0].sources["OCR"] == "log"


def test_layer_values_are_the_mean_of_its_samples() -> None:
    p = profile_of(
        clay_hole(
            {"depth": 2500, "ucs": {"qu": 80}},
            {"depth": 5000, "cu": 50},
            {"depth": 6000, "liquidLimit": 40, "plasticLimit": 20},
            {"depth": 7000, "liquidLimit": 50, "plasticLimit": 24},
            {
                "depth": 8000,
                "grainSize": {
                    "sieves": [{"size": 0.425, "passing": 100}, {"size": 0.075, "passing": 90}]
                },
            },
        )
    )
    layer = p.layers[0]
    assert layer.cu == pytest.approx(45)  # (80/2 + 50)/2
    assert layer.sources["cu"] == "samples (2: UCS qu/2)"
    assert layer.pi == pytest.approx(23)  # (20 + 26)/2
    assert layer.fines == pytest.approx(90)
    assert layer.sources["finesContent"] == "samples (1: grain size, passing 0.075 mm)"


def test_report_carries_the_lab_summary_and_chemistry_flags() -> None:
    hole = clay_hole(
        {
            "number": "UD-1",
            "depth": 3000,
            "liquidLimit": 45,
            "plasticLimit": 20,
            "grainSize": {
                "sieves": [{"size": 0.425, "passing": 100}, {"size": 0.075, "passing": 80}]
            },
            "chemistry": {"sulphateSoil": 0.15, "sulphateWater": 2000, "pH": 5.0},
        }
    )
    out = soil_report(json.dumps({"boreholes": [hole]}))
    bh = out["boreholes"][0]
    assert bh["lab"][0]["uscs"]["symbol"] == "CL"
    notes = " ".join(bh["notes"])
    # 0.15 % in soil is S1, 2000 ppm in water S2: the worse governs.
    assert "UD-1: sulphate: exposure class S2" in notes and "pH 5" in notes


def test_check_reports_plastic_limit_above_liquid_limit() -> None:
    report = SoilReport.model_validate(
        {"boreholes": [clay_hole({"depth": 3000, "liquidLimit": 30, "plasticLimit": 35})]}
    )
    assert any("plastic limit 35 % is above the liquid limit 30 %" in p for p in check(report))


def test_import_reads_the_spt_increments(tmp_path) -> None:
    from saengine.soil import import_soil

    csv = tmp_path / "log.csv"
    csv.write_text(
        "Borehole,Record,Depth,Seat,N1,N2,N,Sample no,Sample type,LL,PL\n"
        "BH-1,spt,1.5,3,5,6,,D-1,,,\n"
        "BH-1,spt,3.0,4,7,9,16,D-2,,,\n"
        "BH-1,sample,2.0,,,,,UD-1,UD,40,20\n",
        "utf-8",
    )
    out = import_soil(str(csv))
    hole = SoilReport.model_validate_json(out["text"]).boreholes[0]
    assert [(r.seat, r.N1, r.N2, r.blows, r.sampleNumber) for r in hole.spt] == [
        (3, 5, 6, 11, "D-1"),
        (4, 7, 9, 16, "D-2"),
    ]
    assert hole.samples[0].number == "UD-1"
    csv.write_text("Borehole,Depth,N1,N2,N\nBH-1,1.5,5,6,12\n", "utf-8")
    assert "is not N1 + N2" in import_soil(str(csv))["problems"][0]


def test_triaxial_from_the_specimens() -> None:
    # UU: cu = mean (σ1 - σ3)/2 = (30 + 32 + 31)/3.
    uu = {
        "type": "UU",
        "specimens": [{"cell": c, "deviator": d} for c, d in ((50, 60), (100, 64), (200, 62))],
    }
    assert lab.feed(Sample.model_validate({"depth": 1, "triaxial": uu}))["cu"][0] == pytest.approx(
        31
    )

    # CD with c' = 10 kPa, φ' = 30°: σ1 = 3 σ3 + 2 c' √3, so σ1 - σ3 = 2 σ3 + 20 √3.
    def specimens(u: float | None) -> list[dict]:
        return [
            {"cell": s3 + (u or 0), "deviator": 2 * s3 + 20 * math.sqrt(3), "porePressure": u}
            for s3 in (50, 100, 200)
        ]

    cd = lab.triaxial(
        Sample.model_validate(
            {"depth": 1, "triaxial": {"type": "CD", "specimens": specimens(None)}}
        ).triaxial
    )  # type: ignore[arg-type]
    assert cd["c"] == pytest.approx(10) and cd["phi"] == pytest.approx(30) and cd["effective"]
    # CU with the pore pressures: σ3' = σ3 - u gives the same effective line.
    cu = lab.triaxial(
        Sample.model_validate(
            {"depth": 1, "triaxial": {"type": "CU", "specimens": specimens(40)}}
        ).triaxial
    )  # type: ignore[arg-type]
    assert cu["c"] == pytest.approx(10) and cu["phi"] == pytest.approx(30) and cu["effective"]
    # Without a type nothing is derived.
    assert (
        lab.triaxial(Sample.model_validate({"depth": 1, "triaxial": {"specimens": []}}).triaxial)
        is None
    )  # type: ignore[arg-type]


def test_refusal_without_penetration_counts_the_blows() -> None:
    r = SptRecord.model_validate({"depth": 9000, "seat": 20, "N1": 50, "refusal": True})
    assert r.blows == 50 and r.issues == []
    r = SptRecord.model_validate({"depth": 9000, "N1": 30, "N2": 50, "refusal": True})
    assert r.blows == 80
    # The extrapolated N entered (e.g. 30 blows for an unrecorded part of 150 mm as 100) is
    # not a mismatch: the blows driven are only a lower bound.
    r = SptRecord.model_validate({"depth": 3000, "N": 100, "N1": 30, "refusal": True})
    assert r.blows == 100 and r.mismatch is None and r.issues == []
    # An entered N below the blows already driven is one.
    r = SptRecord.model_validate({"depth": 3000, "N": 20, "N1": 30, "refusal": True})
    assert r.blows == 20 and "already add up to N1 + N2 = 30 + 0 = 30" in (r.mismatch or "")


def test_n_from_increments_is_capped_at_300() -> None:
    r = SptRecord.model_validate({"depth": 3000, "N1": 200, "N2": 200})
    assert r.blows == 300 and r.derived == 300
    assert r.issues == ["N1 + N2 = 200 + 200 = 400 is more than 300; N 300 is used"]
    r = SptRecord.model_validate({"depth": 3000, "N": 250, "N1": 200, "N2": 200})
    assert r.blows == 250
    assert r.mismatch == "N is 250 but N1 + N2 = 200 + 200 = 400; N 250 is used"


def test_import_reads_increments_numbered_n1_n2_n3(tmp_path) -> None:
    from saengine.soil import import_soil

    csv = tmp_path / "log.csv"
    # N1 is the seating drive on such sheets: N = N2 + N3 = 5 + 6 = 11.
    csv.write_text("Borehole,Depth,N1,N2,N3\nBH-1,1.5,3,5,6\n", "utf-8")
    out = import_soil(str(csv))
    record = SoilReport.model_validate_json(out["text"]).boreholes[0].spt[0]
    assert (record.seat, record.N1, record.N2, record.blows) == (3, 5, 6, 11)
    assert any("N = N2 + N3" in n for n in out["notes"]) and not out.get("problems")
    assert not any("N3" in n and "ignored" in n for n in out["notes"])
    csv.write_text("Borehole,Depth,Seat,N1,N2,N3\nBH-1,1.5,3,5,6,7\n", "utf-8")
    assert "both a seating column and N1, N2, N3" in import_soil(str(csv))["problems"][0]
