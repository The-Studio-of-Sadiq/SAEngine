"""Materials Concrete tab: mix proportioning, durability, compliance, sustainability, fresh & hardened tests."""

from __future__ import annotations

import math
from typing import Any

from saengine.boq.costing import default_carbon_text, parse_carbon
from saengine.design.rc_detailing import (
    concrete_modulus as code_concrete_modulus,
)
from saengine.design.rc_detailing import current_aggregate
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.materials_common import parse_csv_rows, parse_numbers, parse_pairs
from saengine.library.materials import modulus_of_rupture
from saengine.report.clauses import in_force

_SLUMP_CLASSES = {
    "S1": (10.0, 40.0),
    "S2": (50.0, 90.0),
    "S3": (100.0, 150.0),
    "S4": (160.0, 210.0),
    "S5": (220.0, 280.0),
}

_EXPOSURE_RULES = {
    "mild": (0.60, 260.0, 20.0, 25.0, "Dry or protected interior"),
    "moderate": (0.55, 280.0, 25.0, 35.0, "Humid / external sheltered"),
    "severe": (0.45, 320.0, 30.0, 45.0, "Wet / cyclic drying / de-icing"),
    "coastal": (0.40, 360.0, 35.0, 55.0, "Marine / tidal splash zone"),
    "aggressive": (0.40, 380.0, 40.0, 60.0, "Chemical / high-sulfate ground"),
}


@feature(
    "libraryConcrete.trialMixes",
    "Trial Mixes",
    part="materials",
    fields=[
        text(
            "trialCsv",
            "Trial mixes CSV (mix,wc,cement_kg,fc7_mpa,fc28_mpa)",
            "mix,wc,cement_kg,fc7_mpa,fc28_mpa\nTM-1,0.50,350,22.5,31.4\nTM-2,0.45,380,26.8,37.2\nTM-3,0.40,420,31.0,42.5",
        ),
        number("targetMeanMpa", "Target mean 28-day strength", 35.0, unit="MPa", min=10.0),
    ],
    requires_project=False,
)
def trial_mixes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate trial mix batches against target mean strength and 7-to-28 day strength ratio."""
    rows_raw = parse_csv_rows(values["trialCsv"])
    target = values["targetMeanMpa"]
    out = []
    passing = []
    for r in rows_raw:
        try:
            wc = float(r["wc"])
            cem = float(r["cement_kg"])
            fc7 = float(r["fc7_mpa"])
            fc28 = float(r["fc28_mpa"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "Trial mix CSV requires mix, wc, cement_kg, fc7_mpa, fc28_mpa."
            ) from exc
        ok = fc28 >= target
        if ok:
            passing.append((cem, r["mix"], fc28, wc))
        out.append(
            {
                "mix": r["mix"],
                "wc": wc,
                "cementKgPerM3": cem,
                "fc7Mpa": fc7,
                "fc28Mpa": fc28,
                "ratio7To28": fc7 / fc28 if fc28 > 0 else 0.0,
                "meetsTarget": ok,
            }
        )
    best = min(passing, key=lambda x: x[0]) if passing else None
    return result(
        summary={
            "trialCount": len(out),
            "passingCount": len(passing),
            "recommendedMix": best[1] if best else "none",
            "bestStrengthMpa": max(r["fc28Mpa"] for r in out),
        },
        tables=[
            table(
                "Trial mix test summary",
                [
                    ("mix", "Mix"),
                    ("wc", "w/c"),
                    ("cementKgPerM3", "Cement", "kg/m3"),
                    ("fc7Mpa", "7-day", "MPa"),
                    ("fc28Mpa", "28-day", "MPa"),
                    ("ratio7To28", "7d/28d"),
                    ("meetsTarget", "Meets target"),
                ],
                out,
            )
        ],
        notes=["Selects lowest-cement passing mix as economical baseline."],
    )


@feature(
    "libraryConcrete.aggregateGrading",
    "Aggregate Grading",
    part="materials",
    fields=[
        text(
            "sievePassing",
            "Sieve size [mm], % passing pairs",
            "20, 98\n12.5, 76\n10, 62\n4.75, 42\n2.36, 33\n1.18, 25\n0.60, 18\n0.30, 10\n0.15, 3",
        ),
        number("maxSizeMm", "Nominal maximum aggregate size", 20.0, unit="mm", min=4.75),
    ],
    requires_project=False,
)
def aggregate_grading(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare combined aggregate sieve grading against the Fuller-Thompson ideal curve."""
    pairs = sorted(parse_pairs(values["sievePassing"], "Sieve grading"), key=lambda p: -p[0])
    dmax = values["maxSizeMm"]
    rows = []
    max_dev = 0.0
    fm_sum = 0.0
    fm_sieves = {4.75, 2.36, 1.18, 0.6, 0.3, 0.15}
    for d, p_pass in pairs:
        p_fuller = min(100.0, 100.0 * (d / dmax) ** 0.45)
        low_env = max(0.0, p_fuller - 10.0)
        high_env = min(100.0, p_fuller + 10.0)
        dev = abs(p_pass - p_fuller)
        max_dev = max(max_dev, dev)
        if round(d, 2) in fm_sieves:
            fm_sum += (100.0 - p_pass) / 100.0
        rows.append(
            {
                "sieveMm": d,
                "passingPercent": p_pass,
                "idealPercent": p_fuller,
                "envelopeMin": low_env,
                "envelopeMax": high_env,
                "withinEnvelope": low_env <= p_pass <= high_env,
            }
        )
    return result(
        summary={
            "sieveCount": len(rows),
            "finenessModulus": fm_sum,
            "maxDeviationPercent": max_dev,
            "allInEnvelope": all(r["withinEnvelope"] for r in rows),
        },
        tables=[
            table(
                "Combined aggregate grading",
                [
                    ("sieveMm", "Sieve", "mm"),
                    ("passingPercent", "Passing", "%"),
                    ("idealPercent", "Fuller ideal", "%"),
                    ("envelopeMin", "Lower", "%"),
                    ("envelopeMax", "Upper", "%"),
                    ("withinEnvelope", "In envelope"),
                ],
                rows,
            )
        ],
        notes=["Fuller-Thompson 0.45-power maximum density curve with +/-10% envelope."],
    )


@feature(
    "libraryConcrete.waterCementRatio",
    "Water Cement Ratio",
    part="materials",
    fields=[
        number("waterKgPerM3", "Mixing water", 180.0, unit="kg/m3", min=80.0),
        number("cementKgPerM3", "Portland cement", 360.0, unit="kg/m3", min=100.0),
        number("scmKgPerM3", "Supplementary cementitious material", 0.0, unit="kg/m3", min=0.0),
        select(
            "exposure",
            "Exposure class",
            [(k, k.title()) for k in _EXPOSURE_RULES],
            "moderate",
        ),
    ],
    requires_project=False,
)
def water_cement_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check water/binder ratio and minimum cement content against exposure durability limits."""
    binder = values["cementKgPerM3"] + values["scmKgPerM3"]
    wb = values["waterKgPerM3"] / binder
    max_wb, min_cem, min_fc, _, desc = _EXPOSURE_RULES[values["exposure"]]
    est_fc = 98.0 * (0.045**wb)
    ok = wb <= max_wb and binder >= min_cem
    return result(
        summary={
            "waterBinderRatio": wb,
            "maxAllowedWc": max_wb,
            "binderKgPerM3": binder,
            "estimatedFcMpa": est_fc,
            "compliant": ok,
        },
        tables=[
            table(
                "Durability w/b check",
                [("check", "Check"), ("actual", "Actual"), ("limit", "Limit"), ("ok", "Pass")],
                [
                    {
                        "check": "Water / binder ratio",
                        "actual": wb,
                        "limit": max_wb,
                        "ok": wb <= max_wb,
                    },
                    {
                        "check": "Binder content [kg/m3]",
                        "actual": binder,
                        "limit": min_cem,
                        "ok": binder >= min_cem,
                    },
                    {
                        "check": "Estimated strength [MPa]",
                        "actual": est_fc,
                        "limit": min_fc,
                        "ok": est_fc >= min_fc,
                    },
                ],
            )
        ],
        notes=[f"Exposure '{values['exposure']}': {desc}."],
    )


@feature(
    "libraryConcrete.mixCost",
    "Mix Cost",
    part="materials",
    fields=[
        number("cementKg", "Cement mass", 360.0, unit="kg/m3", min=0.0),
        number("fineKg", "Fine aggregate mass", 680.0, unit="kg/m3", min=0.0),
        number("coarseKg", "Coarse aggregate mass", 1120.0, unit="kg/m3", min=0.0),
        number("admixtureKg", "Admixture mass", 3.6, unit="kg/m3", min=0.0),
        number("cementRate", "Cement unit rate", 0.14, unit="currency/kg", min=0.0),
        number("fineRate", "Fine aggregate unit rate", 0.025, unit="currency/kg", min=0.0),
        number("coarseRate", "Coarse aggregate unit rate", 0.035, unit="currency/kg", min=0.0),
        number("admixtureRate", "Admixture unit rate", 2.5, unit="currency/kg", min=0.0),
    ],
    requires_project=False,
)
def mix_cost(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate concrete constituent material cost per cubic metre."""
    items = [
        ("Cement", values["cementKg"], values["cementRate"]),
        ("Fine aggregate", values["fineKg"], values["fineRate"]),
        ("Coarse aggregate", values["coarseKg"], values["coarseRate"]),
        ("Admixture", values["admixtureKg"], values["admixtureRate"]),
    ]
    total = sum(m * r for _, m, r in items)
    rows = [
        {
            "item": name,
            "massKgPerM3": mass,
            "ratePerKg": rate,
            "costPerM3": mass * rate,
            "sharePercent": (mass * rate / total * 100.0) if total > 0 else 0.0,
        }
        for name, mass, rate in items
    ]
    return result(
        summary={
            "totalCostPerM3": total,
            "cementSharePercent": rows[0]["sharePercent"],
            "totalMassKgPerM3": sum(m for _, m, _ in items),
        },
        tables=[
            table(
                "Mix cost breakdown",
                [
                    ("item", "Constituent"),
                    ("massKgPerM3", "Mass", "kg/m3"),
                    ("ratePerKg", "Rate", "/kg"),
                    ("costPerM3", "Cost", "/m3"),
                    ("sharePercent", "Share", "%"),
                ],
                rows,
            )
        ],
        notes=["Material constituent cost only; excludes batching, transport, and placing."],
    )


@feature(
    "libraryConcrete.exposureClasses",
    "Exposure Classes",
    part="materials",
    fields=[
        select(
            "exposure",
            "Exposure environment",
            [(k, f"{k.title()} - {v[4]}") for k, v in _EXPOSURE_RULES.items()],
            "moderate",
        ),
        number("fcMpa", "Specified concrete f'c", 25.0, unit="MPa", min=10.0),
        number("coverMm", "Provided clear cover", 35.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def exposure_classes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine minimum concrete grade, max w/c, min cement, and nominal cover for exposure."""
    max_wc, min_cem, min_fc, req_cover, desc = _EXPOSURE_RULES[values["exposure"]]
    fc_ok = values["fcMpa"] >= min_fc
    cov_ok = values["coverMm"] >= req_cover
    return result(
        summary={
            "maxWcRatio": max_wc,
            "minCementKgPerM3": min_cem,
            "minFcMpa": min_fc,
            "minCoverMm": req_cover,
            "compliant": fc_ok and cov_ok,
        },
        tables=[
            table(
                "Exposure class requirements",
                [
                    ("parameter", "Requirement"),
                    ("provided", "Provided"),
                    ("limit", "Required"),
                    ("ok", "Pass"),
                ],
                [
                    {
                        "parameter": "Compressive strength f'c [MPa]",
                        "provided": values["fcMpa"],
                        "limit": min_fc,
                        "ok": fc_ok,
                    },
                    {
                        "parameter": "Clear cover [mm]",
                        "provided": values["coverMm"],
                        "limit": req_cover,
                        "ok": cov_ok,
                    },
                    {"parameter": "Max w/c ratio", "provided": max_wc, "limit": max_wc, "ok": True},
                    {
                        "parameter": "Min cement [kg/m3]",
                        "provided": min_cem,
                        "limit": min_cem,
                        "ok": True,
                    },
                ],
            )
        ],
        notes=[f"Environment: {desc}."],
    )


@feature(
    "libraryConcrete.chlorideLimits",
    "Chloride Limits",
    part="materials",
    fields=[
        select(
            "memberType",
            "Reinforcement type",
            [
                ("prestressed", "Prestressed"),
                ("reinforcedWet", "Reinforced (wet / chlorides)"),
                ("reinforcedDry", "Reinforced (dry interior)"),
            ],
            "reinforcedWet",
        ),
        number("cementKgPerM3", "Cementitious mass", 360.0, unit="kg/m3", min=100.0),
        number("clCementPct", "Chloride from cement (% by mass)", 0.03, unit="%", min=0.0),
        number("clAggKgPerM3", "Chloride from aggregates + water", 0.25, unit="kg/m3", min=0.0),
        number("clAdmKgPerM3", "Chloride from admixtures", 0.02, unit="kg/m3", min=0.0),
    ],
    requires_project=False,
)
def chloride_limits(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check total concrete chloride ion content (% by mass of cement) against limits."""
    cem = values["cementKgPerM3"]
    cl_cem_kg = cem * values["clCementPct"] / 100.0
    total_cl_kg = cl_cem_kg + values["clAggKgPerM3"] + values["clAdmKgPerM3"]
    total_pct = total_cl_kg / cem * 100.0
    limit_pct = {"prestressed": 0.06, "reinforcedWet": 0.15, "reinforcedDry": 0.40}[
        values["memberType"]
    ]
    return result(
        summary={
            "totalChlorideKgPerM3": total_cl_kg,
            "chloridePercentOfCement": total_pct,
            "limitPercentOfCement": limit_pct,
            "compliant": total_pct <= limit_pct,
        },
        tables=[
            table(
                "Chloride ion budget",
                [
                    ("source", "Source"),
                    ("clKgPerM3", "Cl- mass", "kg/m3"),
                    ("pctCement", "% of cement", "%"),
                ],
                [
                    {
                        "source": "Cementitious binder",
                        "clKgPerM3": cl_cem_kg,
                        "pctCement": cl_cem_kg / cem * 100.0,
                    },
                    {
                        "source": "Aggregates & mixing water",
                        "clKgPerM3": values["clAggKgPerM3"],
                        "pctCement": values["clAggKgPerM3"] / cem * 100.0,
                    },
                    {
                        "source": "Admixtures",
                        "clKgPerM3": values["clAdmKgPerM3"],
                        "pctCement": values["clAdmKgPerM3"] / cem * 100.0,
                    },
                    {"source": "Total", "clKgPerM3": total_cl_kg, "pctCement": total_pct},
                ],
            )
        ],
        notes=[
            f"Checked against water-soluble chloride limit ({limit_pct:.2f}% by mass of cement)."
        ],
    )


@feature(
    "libraryConcrete.sulfateResistance",
    "Sulfate Resistance",
    part="materials",
    fields=[
        number("groundwaterSo4MgPerL", "Groundwater sulfate SO4", 450.0, unit="mg/L", min=0.0),
        number("soilSo4Percent", "Soil water-soluble SO4", 0.25, unit="%", min=0.0),
        number("wcRatio", "Mix water/cement ratio", 0.45, min=0.25, max=0.75),
        number("binderKgPerM3", "Binder content", 360.0, unit="kg/m3", min=150.0),
    ],
    requires_project=False,
)
def sulfate_resistance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen sulfate exposure class and binder/w/c requirements from soil and water SO4."""
    gw = values["groundwaterSo4MgPerL"]
    soil_so4 = values["soilSo4Percent"]
    if gw > 10000 or soil_so4 > 2.0:
        sev, req_wc, req_cem, cement_rec = "Very Severe", 0.40, 380.0, "SRPC + pozzolan / high-slag"
    elif gw > 1500 or soil_so4 > 0.20:
        sev, req_wc, req_cem, cement_rec = "Severe", 0.45, 340.0, "SRPC or >=50% GGBS / >=25% FA"
    elif gw >= 150 or soil_so4 >= 0.10:
        sev, req_wc, req_cem, cement_rec = (
            "Moderate",
            0.50,
            310.0,
            "Moderate sulfate-resisting / blended",
        )
    else:
        sev, req_wc, req_cem, cement_rec = "Negligible", 0.60, 260.0, "OPC or standard blended"

    ok = values["wcRatio"] <= req_wc and values["binderKgPerM3"] >= req_cem
    return result(
        summary={
            "severityClass": sev,
            "maxWcRatio": req_wc,
            "minBinderKgPerM3": req_cem,
            "recommendedCement": cement_rec,
            "compliant": ok,
        },
        tables=[
            table(
                "Sulfate exposure screening",
                [
                    ("parameter", "Parameter"),
                    ("provided", "Provided"),
                    ("required", "Limit"),
                    ("ok", "Pass"),
                ],
                [
                    {
                        "parameter": "w/c ratio",
                        "provided": values["wcRatio"],
                        "required": req_wc,
                        "ok": values["wcRatio"] <= req_wc,
                    },
                    {
                        "parameter": "Binder [kg/m3]",
                        "provided": values["binderKgPerM3"],
                        "required": req_cem,
                        "ok": values["binderKgPerM3"] >= req_cem,
                    },
                ],
            )
        ],
        notes=[f"Governing sulfate severity '{sev}'; recommended binder: {cement_rec}."],
    )


@feature(
    "libraryConcrete.cubeResults",
    "Cube Results",
    part="materials",
    fields=[
        text("cubeMpa", "150 mm cube strengths [MPa]", "33.5, 35.1, 32.8, 36.4, 34.0, 35.8"),
        number(
            "targetCubeMpa", "Specified characteristic cube strength fcu", 30.0, unit="MPa", min=5.0
        ),
    ],
    requires_project=False,
)
def cube_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cube test rolling averages and equivalent cylinder strength (~0.8 fcu)."""
    vals = parse_numbers(values["cubeMpa"], "Cube strengths")
    target = values["targetCubeMpa"]
    rows = []
    roll_avgs = []
    for i, v in enumerate(vals):
        roll = sum(vals[max(0, i - 2) : i + 1]) / min(i + 1, 3)
        if i >= 2:
            roll_avgs.append(roll)
        rows.append(
            {
                "test": i + 1,
                "cubeMpa": v,
                "equivCylinderMpa": 0.8 * v,
                "rolling3Mpa": roll,
                "aboveMin": v >= target - 3.0,
            }
        )
    mean = sum(vals) / len(vals)
    return result(
        summary={
            "cubeCount": len(vals),
            "meanCubeMpa": mean,
            "minRolling3Mpa": min(roll_avgs) if roll_avgs else mean,
            "equivCylinderMeanMpa": 0.8 * mean,
        },
        tables=[
            table(
                "Cube compressive test record",
                [
                    ("test", "Test #"),
                    ("cubeMpa", "Cube fcu", "MPa"),
                    ("equivCylinderMpa", "Equiv cylinder", "MPa"),
                    ("rolling3Mpa", "Rolling-3 mean", "MPa"),
                    ("aboveMin", "Above fcu-3"),
                ],
                rows,
            )
        ],
        notes=["Equivalent cylinder strength estimated as 0.80 * cube strength."],
    )


@feature(
    "libraryConcrete.cylinderResults",
    "Cylinder Results",
    part="materials",
    fields=[
        text(
            "cylinderMpa",
            "150x300 mm cylinder strengths [MPa]",
            "28.2, 30.4, 29.1, 27.6, 31.0, 29.5",
        ),
        number("specifiedFcMpa", "Specified strength f'c", 28.0, unit="MPa", min=5.0),
    ],
    requires_project=False,
)
def cylinder_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate cylinder test breaks against running-3-average and minimum single-test rules."""
    vals = parse_numbers(values["cylinderMpa"], "Cylinder strengths")
    fc = values["specifiedFcMpa"]
    min_single = fc - 3.5 if fc <= 35.0 else 0.9 * fc
    rows = []
    roll3_ok = True
    for i, v in enumerate(vals):
        roll = sum(vals[max(0, i - 2) : i + 1]) / min(i + 1, 3)
        r_ok = True if i < 2 else roll >= fc
        if not r_ok:
            roll3_ok = False
        rows.append(
            {
                "test": i + 1,
                "fcMpa": v,
                "rolling3Mpa": roll,
                "rollingOk": r_ok,
                "singleOk": v >= min_single,
            }
        )
    all_single_ok = all(r["singleOk"] for r in rows)
    return result(
        summary={
            "testCount": len(vals),
            "meanFcMpa": sum(vals) / len(vals),
            "minFcMpa": min(vals),
            "accepted": roll3_ok and all_single_ok,
        },
        tables=[
            table(
                "Cylinder acceptance checks",
                [
                    ("test", "Test #"),
                    ("fcMpa", "Measured", "MPa"),
                    ("rolling3Mpa", "Running 3 avg", "MPa"),
                    ("rollingOk", "Avg >= f'c"),
                    ("singleOk", "Single >= min"),
                ],
                rows,
            )
        ],
        notes=[
            f"Single-test lower limit: {min_single:.2f} MPa; running 3-test average must be >= {fc:.1f} MPa."
        ],
    )


@feature(
    "libraryConcrete.acceptanceCriteria",
    "Acceptance Criteria",
    part="materials",
    fields=[
        text("batchMpa", "Lot strengths [MPa]", "31.0, 32.5, 29.8, 33.4, 30.2, 31.8"),
        number("specifiedMpa", "Specified characteristic strength", 30.0, unit="MPa", min=5.0),
        number("marginMpa", "Lot mean margin", 1.48, unit="MPa", min=0.0),
        number("individualToleranceMpa", "Individual lower tolerance", 3.5, unit="MPa", min=0.0),
    ],
    requires_project=False,
)
def acceptance_criteria(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check statistical lot conformity rules for concrete supply."""
    vals = parse_numbers(values["batchMpa"], "Lot strengths")
    spec = values["specifiedMpa"]
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
    mean_req = spec + max(values["marginMpa"], 0.825 * std)
    min_req = spec - values["individualToleranceMpa"]
    mean_ok = mean >= mean_req
    min_ok = min(vals) >= min_req
    return result(
        summary={
            "lotCount": len(vals),
            "lotMeanMpa": mean,
            "requiredMeanMpa": mean_req,
            "lotMinMpa": min(vals),
            "lotAccepted": mean_ok and min_ok,
        },
        tables=[
            table(
                "Conformity criteria",
                [
                    ("criterion", "Criterion"),
                    ("actualMpa", "Actual", "MPa"),
                    ("limitMpa", "Limit", "MPa"),
                    ("ok", "Pass"),
                ],
                [
                    {
                        "criterion": "Lot mean strength",
                        "actualMpa": mean,
                        "limitMpa": mean_req,
                        "ok": mean_ok,
                    },
                    {
                        "criterion": "Minimum individual test",
                        "actualMpa": min(vals),
                        "limitMpa": min_req,
                        "ok": min_ok,
                    },
                ],
            )
        ],
        notes=[
            "Lot mean >= max(f_spec + margin, f_spec + 0.825 s) and min test >= f_spec - tolerance."
        ],
    )


@feature(
    "libraryConcrete.cementReplacement",
    "Cement Replacement",
    part="materials",
    fields=[
        number("opcKgPerM3", "Portland cement (OPC)", 240.0, unit="kg/m3", min=0.0),
        number("ggbsKgPerM3", "GGBS mass", 90.0, unit="kg/m3", min=0.0),
        number("flyAshKgPerM3", "Fly ash mass", 30.0, unit="kg/m3", min=0.0),
        number("silicaFumeKgPerM3", "Silica fume mass", 0.0, unit="kg/m3", min=0.0),
        number("waterKgPerM3", "Water mass", 170.0, unit="kg/m3", min=50.0),
    ],
    requires_project=False,
)
def cement_replacement(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute SCM replacement percentages and k-value effective binder content."""
    opc = values["opcKgPerM3"]
    ggbs = values["ggbsKgPerM3"]
    fa = values["flyAshKgPerM3"]
    sf = values["silicaFumeKgPerM3"]
    total = opc + ggbs + fa + sf
    if total <= 0:
        raise FeatureInputError("Total cementitious mass must be positive.")
    repl_pct = (ggbs + fa + sf) / total * 100.0
    # Standard k-value concept: GGBS ~0.75, Fly Ash ~0.40, Silica Fume ~2.0
    equiv_binder = opc + 0.75 * ggbs + 0.40 * fa + 2.0 * sf
    eff_wb = values["waterKgPerM3"] / equiv_binder
    rows = [
        {
            "component": "OPC",
            "massKgPerM3": opc,
            "sharePercent": opc / total * 100.0,
            "kFactor": 1.0,
        },
        {
            "component": "GGBS",
            "massKgPerM3": ggbs,
            "sharePercent": ggbs / total * 100.0,
            "kFactor": 0.75,
        },
        {
            "component": "Fly ash",
            "massKgPerM3": fa,
            "sharePercent": fa / total * 100.0,
            "kFactor": 0.40,
        },
        {
            "component": "Silica fume",
            "massKgPerM3": sf,
            "sharePercent": sf / total * 100.0,
            "kFactor": 2.0,
        },
    ]
    return result(
        summary={
            "totalBinderKgPerM3": total,
            "replacementPercent": repl_pct,
            "equivalentBinderKgPerM3": equiv_binder,
            "effectiveWaterBinderRatio": eff_wb,
        },
        tables=[
            table(
                "Blended binder composition",
                [
                    ("component", "Component"),
                    ("massKgPerM3", "Mass", "kg/m3"),
                    ("sharePercent", "Share", "%"),
                    ("kFactor", "k-factor"),
                ],
                rows,
            )
        ],
        notes=[
            "Effective binder uses k-concept (OPC=1.0, GGBS=0.75, fly ash=0.40, silica fume=2.0)."
        ],
    )


@feature(
    "libraryConcrete.embodiedCarbonMix",
    "Embodied Carbon Mix",
    part="materials",
    fields=[
        number("opcKgPerM3", "OPC mass", 300.0, unit="kg/m3", min=0.0),
        number("ggbsKgPerM3", "GGBS mass", 60.0, unit="kg/m3", min=0.0),
        number("flyAshKgPerM3", "Fly ash mass", 0.0, unit="kg/m3", min=0.0),
        number("fineKgPerM3", "Fine aggregate mass", 680.0, unit="kg/m3", min=0.0),
        number("coarseKgPerM3", "Coarse aggregate mass", 1120.0, unit="kg/m3", min=0.0),
        number("fcMpa", "Characteristic strength f'c", 30.0, unit="MPa", min=5.0),
    ],
    requires_project=False,
)
def embodied_carbon_mix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate A1-A3 embodied carbon per m3 of concrete mix using engine carbon factors."""
    factors_doc = parse_carbon(default_carbon_text())
    cement_ef = next(
        (f.factor for f in factors_doc.factors if f.id == "cement" and f.factor is not None), 0.588
    )
    # Typical indicative A1-A3 factors for SCMs & crushed aggregates when not in BOQ defaults
    items = [
        ("OPC cement", values["opcKgPerM3"], float(cement_ef)),
        ("GGBS", values["ggbsKgPerM3"], 0.070),
        ("Fly ash", values["flyAshKgPerM3"], 0.025),
        ("Fine aggregate", values["fineKgPerM3"], 0.005),
        ("Coarse aggregate", values["coarseKgPerM3"], 0.008),
    ]
    total = sum(m * ef for _, m, ef in items)
    rows = [
        {
            "constituent": name,
            "massKgPerM3": mass,
            "factorKgCo2ePerKg": ef,
            "carbonKgCo2ePerM3": mass * ef,
        }
        for name, mass, ef in items
    ]
    return result(
        summary={
            "totalCarbonKgCo2ePerM3": total,
            "carbonPerMpaKgCo2e": total / values["fcMpa"],
            "cementFactorKgCo2ePerKg": float(cement_ef),
        },
        tables=[
            table(
                "Concrete mix embodied carbon (A1-A3)",
                [
                    ("constituent", "Constituent"),
                    ("massKgPerM3", "Mass", "kg/m3"),
                    ("factorKgCo2ePerKg", "Factor", "kgCO2e/kg"),
                    ("carbonKgCo2ePerM3", "Embodied carbon", "kgCO2e/m3"),
                ],
                rows,
            )
        ],
        notes=[
            "OPC factor taken from SAEngine boq/data/carbon-factors.json; replace with supplier EPD values."
        ],
    )


@feature(
    "libraryConcrete.epdLookup",
    "EPD Lookup",
    part="materials",
    fields=[
        text("epdReference", "EPD identifier / supplier reference", "EPD-CONC-30MPa-2026"),
        number("declaredCarbonKgCo2ePerM3", "Declared A1-A3 GWP", 245.0, unit="kgCO2e/m3", min=0.0),
        number(
            "baselineCementKgPerM3", "Baseline OPC mix cement mass", 360.0, unit="kg/m3", min=1.0
        ),
    ],
    requires_project=False,
)
def epd_lookup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare a supplier Environmental Product Declaration against the default carbon schedule."""
    factors_doc = parse_carbon(default_carbon_text())
    cement_ef = next(
        (f.factor for f in factors_doc.factors if f.id == "cement" and f.factor is not None), 0.588
    )
    baseline = values["baselineCementKgPerM3"] * float(cement_ef)
    declared = values["declaredCarbonKgCo2ePerM3"]
    delta = declared - baseline
    rows = [
        {"id": f.id, "material": f.material, "factorKgPerKg": f.factor, "source": f.source}
        for f in factors_doc.factors
    ]
    return result(
        summary={
            "epdReference": values["epdReference"].strip() or "custom-epd",
            "declaredKgCo2ePerM3": declared,
            "baselineKgCo2ePerM3": baseline,
            "reductionPercent": -delta / baseline * 100.0 if baseline > 0 else 0.0,
        },
        tables=[
            table(
                "Engine carbon factor catalog",
                [
                    ("id", "ID"),
                    ("material", "Material"),
                    ("factorKgPerKg", "Factor", "kgCO2e/kg"),
                    ("source", "Reference"),
                ],
                rows,
            )
        ],
        notes=["Compares declared EPD A1-A3 GWP against baseline cement carbon intensity."],
    )


@feature(
    "libraryConcrete.slumpTest",
    "Slump Test",
    part="materials",
    fields=[
        number("measuredSlumpMm", "Measured slump", 120.0, unit="mm", min=0.0, max=300.0),
        select(
            "targetClass",
            "Target workability class",
            [(k, f"{k} ({v[0]:g}-{v[1]:g} mm)") for k, v in _SLUMP_CLASSES.items()],
            "S3",
        ),
        number("toleranceMm", "Acceptance tolerance +/-", 25.0, unit="mm", min=5.0),
    ],
    requires_project=False,
)
def slump_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare measured slump against target workability class bounds."""
    lo, hi = _SLUMP_CLASSES[values["targetClass"]]
    meas = values["measuredSlumpMm"]
    tol = values["toleranceMm"]
    in_class = lo <= meas <= hi
    in_tol = (lo - tol) <= meas <= (hi + tol)
    return result(
        summary={
            "measuredSlumpMm": meas,
            "targetClass": values["targetClass"],
            "withinClass": in_class,
            "withinTolerance": in_tol,
        },
        tables=[
            table(
                "Slump class comparison",
                [
                    ("class", "Class"),
                    ("minMm", "Min", "mm"),
                    ("maxMm", "Max", "mm"),
                    ("selected", "Target"),
                ],
                [
                    {
                        "class": k,
                        "minMm": v[0],
                        "maxMm": v[1],
                        "selected": k == values["targetClass"],
                    }
                    for k, v in _SLUMP_CLASSES.items()
                ],
            )
        ],
        notes=["Checks measured slump against nominal class range and site acceptance tolerance."],
    )


@feature(
    "libraryConcrete.flowTable",
    "Flow Table",
    part="materials",
    fields=[
        number(
            "spread1Mm", "Orthogonal spread diameter d1", 640.0, unit="mm", min=200.0, max=950.0
        ),
        number(
            "spread2Mm", "Orthogonal spread diameter d2", 660.0, unit="mm", min=200.0, max=950.0
        ),
        number("t500Sec", "Time to 500 mm spread T500", 3.2, unit="s", min=0.5, max=20.0),
    ],
    requires_project=False,
)
def flow_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate slump-flow spread diameter and viscosity class for high-workability/SCC mixes."""
    mean_d = 0.5 * (values["spread1Mm"] + values["spread2Mm"])
    t500 = values["t500Sec"]
    if mean_d < 550:
        sf_class = "Below SF1"
    elif mean_d <= 650:
        sf_class = "SF1 (550-650 mm)"
    elif mean_d <= 750:
        sf_class = "SF2 (660-750 mm)"
    else:
        sf_class = "SF3 (760-850 mm)"
    vs_class = "VS1 (T500 < 2 s)" if t500 < 2.0 else "VS2 (T500 >= 2 s)"
    return result(
        summary={
            "meanSpreadMm": mean_d,
            "t500Sec": t500,
            "slumpFlowClass": sf_class,
            "viscosityClass": vs_class,
        },
        tables=[
            table(
                "Slump-flow test summary",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Mean spread diameter", "value": mean_d, "unit": "mm"},
                    {
                        "parameter": "Spread difference |d1-d2|",
                        "value": abs(values["spread1Mm"] - values["spread2Mm"]),
                        "unit": "mm",
                    },
                    {"parameter": "T500 flow time", "value": t500, "unit": "s"},
                ],
            )
        ],
        notes=[
            "Standard two-axis spread averaging; inspect perimeter visually for mortar halo/segregation."
        ],
    )


@feature(
    "libraryConcrete.airContent",
    "Air Content",
    part="materials",
    fields=[
        number("measuredAirPct", "Measured air content", 5.2, unit="%", min=0.0, max=15.0),
        number("maxAggMm", "Nominal max aggregate size", 20.0, unit="mm", min=4.75, max=75.0),
        number("baseFcMpa", "Un-entrained reference f'c", 32.0, unit="MPa", min=10.0),
    ],
    requires_project=False,
)
def air_content(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess freeze-thaw target air content and strength adjustment (~5% loss per 1% extra air)."""
    dmax = values["maxAggMm"]
    target = max(3.5, min(7.5, 7.5 - 0.1 * (dmax - 10.0)))
    meas = values["measuredAirPct"]
    extra_air = max(0.0, meas - 1.5)
    strength_factor = max(0.5, 1.0 - 0.05 * extra_air)
    adj_fc = values["baseFcMpa"] * strength_factor
    return result(
        summary={
            "measuredAirPercent": meas,
            "targetAirPercent": target,
            "withinTarget": abs(meas - target) <= 1.5,
            "adjustedStrengthMpa": adj_fc,
        },
        tables=[
            table(
                "Air entrainment assessment",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Measured air", "value": meas, "unit": "%"},
                    {"parameter": "Recommended target air", "value": target, "unit": "%"},
                    {
                        "parameter": "Strength retention factor",
                        "value": strength_factor,
                        "unit": "-",
                    },
                    {"parameter": "Adjusted f'c", "value": adj_fc, "unit": "MPa"},
                ],
            )
        ],
        notes=[
            "Target air scales inversely with max aggregate size; strength drops roughly 5% per 1% entrained air."
        ],
    )


@feature(
    "libraryConcrete.settingTime",
    "Setting Time",
    part="materials",
    fields=[
        text(
            "penetrationPairs",
            "Elapsed time [min], penetration resistance [MPa]",
            "120, 0.8\n180, 2.2\n210, 3.8\n270, 12.5\n320, 24.0\n345, 29.5",
        )
    ],
    requires_project=False,
)
def setting_time(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Interpolate initial (3.5 MPa) and final (27.6 MPa) setting times from penetration data."""
    pts = sorted(parse_pairs(values["penetrationPairs"], "Penetration pairs"), key=lambda p: p[0])

    def _interp(target_mpa: float) -> float | None:
        for i in range(1, len(pts)):
            t1, r1 = pts[i - 1]
            t2, r2 = pts[i]
            if r1 <= target_mpa <= r2 and r2 > r1:
                return t1 + (target_mpa - r1) / (r2 - r1) * (t2 - t1)
        return None

    t_init = _interp(3.5)
    t_final = _interp(27.6)
    rows = [{"timeMin": t, "resistanceMpa": r} for t, r in pts]
    return result(
        summary={
            "initialSettingMin": t_init if t_init is not None else pts[-1][0],
            "finalSettingMin": t_final if t_final is not None else pts[-1][0],
            "windowMin": (t_final - t_init) if (t_init and t_final) else 0.0,
        },
        tables=[
            table(
                "Penetration resistance readings",
                [("timeMin", "Elapsed time", "min"), ("resistanceMpa", "Resistance", "MPa")],
                rows,
            )
        ],
        notes=[
            "Initial set interpolated at 3.5 MPa and final set at 27.6 MPa penetration resistance."
        ],
    )


@feature(
    "libraryConcrete.bleedingTest",
    "Bleeding Test",
    part="materials",
    fields=[
        number("bleedWaterMl", "Total accumulated bleed water", 32.0, unit="mL", min=0.0),
        number("surfaceAreaCm2", "Specimen top surface area", 491.0, unit="cm2", min=10.0),
        number("specimenMassKg", "Fresh concrete specimen mass", 14.0, unit="kg", min=1.0),
        number("mixWaterKgPerM3", "Mix water per m3", 185.0, unit="kg/m3", min=80.0),
        number("mixDensityKgPerM3", "Fresh concrete density", 2400.0, unit="kg/m3", min=1400.0),
    ],
    requires_project=False,
)
def bleeding_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute bleed water per unit surface area and percentage of total mixing water."""
    bleed_ml = values["bleedWaterMl"]
    bleed_per_area = bleed_ml / values["surfaceAreaCm2"]
    water_in_sample_ml = (
        values["specimenMassKg"] / values["mixDensityKgPerM3"] * values["mixWaterKgPerM3"] * 1000.0
    )
    bleed_pct = (bleed_ml / water_in_sample_ml * 100.0) if water_in_sample_ml > 0 else 0.0
    stability = (
        "Low bleeding (stable)"
        if bleed_pct <= 2.0
        else ("Moderate bleeding" if bleed_pct <= 5.0 else "High bleeding risk")
    )
    return result(
        summary={
            "bleedPerAreaMlPerCm2": bleed_per_area,
            "bleedPercentOfWater": bleed_pct,
            "stabilityRating": stability,
        },
        tables=[
            table(
                "Bleeding test reduction",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Total bleed water", "value": bleed_ml, "unit": "mL"},
                    {"parameter": "Bleed per unit area", "value": bleed_per_area, "unit": "mL/cm2"},
                    {"parameter": "Water in specimen", "value": water_in_sample_ml, "unit": "mL"},
                    {"parameter": "Bleed % of mix water", "value": bleed_pct, "unit": "%"},
                ],
            )
        ],
        notes=["High bleeding (>5%) indicates excessive laitance/plastic settlement risk."],
    )


@feature(
    "libraryConcrete.splitTensile",
    "Split Tensile",
    part="materials",
    fields=[
        number("failureLoadKn", "Splitting failure load P", 210.0, unit="kN", min=0.1),
        number("diameterMm", "Cylinder diameter D", 150.0, unit="mm", min=50.0),
        number("lengthMm", "Cylinder length L", 300.0, unit="mm", min=50.0),
        number("fcMpa", "Reference compressive strength f'c", 30.0, unit="MPa", min=5.0),
    ],
    requires_project=False,
)
def split_tensile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute splitting tensile strength fct = 2P / (pi * L * D)."""
    p_n = values["failureLoadKn"] * 1000.0
    fct = 2.0 * p_n / (math.pi * values["lengthMm"] * values["diameterMm"])
    est_fct = 0.56 * math.sqrt(values["fcMpa"])
    return result(
        summary={
            "splitTensileMpa": fct,
            "empiricalEstimateMpa": est_fct,
            "ratioToRootFc": fct / math.sqrt(values["fcMpa"]),
        },
        tables=[
            table(
                "Splitting tensile test",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Failure load P", "value": values["failureLoadKn"], "unit": "kN"},
                    {"parameter": "Split tensile fct", "value": fct, "unit": "MPa"},
                    {"parameter": "Typical 0.56 sqrt(f'c)", "value": est_fct, "unit": "MPa"},
                ],
            )
        ],
        notes=["Standard Brazilian cylinder splitting formula fct = 2P / (pi L D)."],
    )


@feature(
    "libraryConcrete.flexuralStrength",
    "Flexural Strength",
    part="materials",
    fields=[
        number("failureLoadKn", "Total beam failure load P", 28.0, unit="kN", min=0.1),
        number("spanMm", "Support span L", 450.0, unit="mm", min=100.0),
        number("widthMm", "Beam width b", 150.0, unit="mm", min=50.0),
        number("depthMm", "Beam depth d", 150.0, unit="mm", min=50.0),
        number("fcMpa", "Reference f'c", 30.0, unit="MPa", min=5.0),
    ],
    requires_project=False,
)
def flexural_strength(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute modulus of rupture fr = PL/(bd^2) from third-point beam flexure test."""
    p_n = values["failureLoadKn"] * 1000.0
    fr = p_n * values["spanMm"] / (values["widthMm"] * values["depthMm"] ** 2)
    fr_code = modulus_of_rupture(values["fcMpa"])
    return result(
        summary={
            "flexuralStrengthMpa": fr,
            "codeRuptureMpa": fr_code,
            "ratioToCode": fr / fr_code,
        },
        tables=[
            table(
                "Third-point flexural test",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Measured fr = PL/(bd^2)", "value": fr, "unit": "MPa"},
                    {"parameter": "Code relation 0.62 sqrt(f'c)", "value": fr_code, "unit": "MPa"},
                ],
            )
        ],
        notes=["Assumes fracture occurs within the middle third under third-point loading."],
    )


@feature(
    "libraryConcrete.modulusTest",
    "Modulus Test",
    part="materials",
    fields=[
        number("stress1Mpa", "Lower stress S1 (at 50 microstrain)", 1.3, unit="MPa", min=0.0),
        number("strain1Micro", "Lower strain eps1", 50.0, unit="microstrain", min=0.0),
        number("stress2Mpa", "Upper stress S2 (40% f'c)", 12.0, unit="MPa", min=0.5),
        number("strain2Micro", "Upper strain eps2", 455.0, unit="microstrain", min=10.0),
        number("fcMpa", "Cylinder compressive strength f'c", 30.0, unit="MPa", min=5.0),
    ],
    requires_project=False,
)
def modulus_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute static secant chord elastic modulus from cylinder compression test readings."""
    de = (values["strain2Micro"] - values["strain1Micro"]) * 1e-6
    if de <= 0:
        raise FeatureInputError("Upper strain must exceed lower strain.")
    ec_meas = (values["stress2Mpa"] - values["stress1Mpa"]) / de
    with in_force(ctx.root):
        ec_code, how = code_concrete_modulus(values["fcMpa"], 2400.0, current_aggregate())
    diff_pct = (ec_meas - ec_code) / ec_code * 100.0
    return result(
        summary={
            "measuredModulusMpa": ec_meas,
            "codeModulusMpa": ec_code,
            "differencePercent": diff_pct,
        },
        tables=[
            table(
                "Static modulus test comparison",
                [("basis", "Basis"), ("modulusMpa", "Elastic modulus", "MPa")],
                [
                    {"basis": "Measured chord modulus", "modulusMpa": ec_meas},
                    {"basis": f"Code pack ({how})", "modulusMpa": ec_code},
                ],
            )
        ],
        notes=["Chord modulus Ec = (S2 - S1) / (eps2 - eps1) between 50 microstrain and 0.40 f'c."],
    )


@feature(
    "libraryConcrete.coreTesting",
    "Core Testing",
    part="materials",
    fields=[
        text("coreMpa", "Measured core strengths [MPa]", "26.5, 28.0, 25.8"),
        number("lengthMm", "Capped core length L", 150.0, unit="mm", min=40.0),
        number("diameterMm", "Core diameter D", 100.0, unit="mm", min=40.0),
        select(
            "moisture",
            "Core moisture condition",
            [("dry", "Air-dried"), ("soaked", "Soaked 40h")],
            "dry",
        ),
    ],
    requires_project=False,
)
def core_testing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Correct extracted concrete core strengths for L/D slenderness, diameter, moisture, and damage."""
    cores = parse_numbers(values["coreMpa"], "Core strengths")
    ld = values["lengthMm"] / values["diameterMm"]
    # Standard slenderness factor Fl/d (interpolated between 1.0->0.87 and 2.0->1.00)
    f_ld = min(1.0, max(0.85, 0.87 + 0.13 * (ld - 1.0))) if ld < 2.0 else 1.0
    f_dia = 1.06 if values["diameterMm"] < 75.0 else (1.02 if values["diameterMm"] < 100.0 else 1.0)
    f_mc = 0.96 if values["moisture"] == "dry" else 1.09
    f_dam = 1.06
    factor = f_ld * f_dia * f_mc * f_dam
    rows = [{"core": i + 1, "rawMpa": c, "inSituFcMpa": c * factor} for i, c in enumerate(cores)]
    mean_insitu = sum(r["inSituFcMpa"] for r in rows) / len(rows)
    return result(
        summary={
            "coreCount": len(cores),
            "slendernessLD": ld,
            "combinedFactor": factor,
            "meanInSituFcMpa": mean_insitu,
        },
        tables=[
            table(
                "Core strength correction",
                [
                    ("core", "Core #"),
                    ("rawMpa", "Raw strength", "MPa"),
                    ("inSituFcMpa", "Equivalent f'c", "MPa"),
                ],
                rows,
            )
        ],
        notes=[
            f"Factors: F_ld={f_ld:.3f}, F_dia={f_dia:.3f}, F_mc={f_mc:.3f}, F_damage={f_dam:.3f}."
        ],
    )


@feature(
    "libraryConcrete.nonDestructiveTest",
    "Non-Destructive Test",
    part="materials",
    fields=[
        number("reboundR", "Rebound hammer index R", 36.0, min=10.0, max=70.0),
        number("upvKmPerS", "Ultrasonic pulse velocity V", 4.1, unit="km/s", min=1.5, max=6.0),
    ],
    requires_project=False,
)
def non_destructive_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate in-situ concrete strength using combined SonReb (rebound + UPV) correlation."""
    r = values["reboundR"]
    v = values["upvKmPerS"]
    # Empirical SonReb power correlation: fc = 9.27e-5 * R^1.4 * V^2.6 (V in km/s -> m/s)
    fc_sonreb = 9.27e-5 * (r**1.4) * ((v * 1000.0) ** 0.92) / 1.0
    # Wait: standard RILEM SonReb uses V in km/s: fc ≈ 0.0286 * R^1.246 * V^1.85
    fc_sonreb = 0.0286 * (r**1.246) * (v**1.85)
    fc_rebound = max(5.0, 0.015 * r**2 + 0.35 * r - 4.0)
    quality = (
        "Excellent"
        if v >= 4.5
        else ("Good" if v >= 3.5 else ("Questionable" if v >= 3.0 else "Poor"))
    )
    return result(
        summary={
            "sonrebStrengthMpa": fc_sonreb,
            "reboundOnlyMpa": fc_rebound,
            "upvQuality": quality,
        },
        tables=[
            table(
                "NDT correlation estimate",
                [("method", "Method"), ("estimateMpa", "Estimated strength", "MPa")],
                [
                    {"method": "Combined SonReb (R + UPV)", "estimateMpa": fc_sonreb},
                    {"method": "Rebound hammer correlation", "estimateMpa": fc_rebound},
                ],
            )
        ],
        notes=[
            f"UPV pulse quality rating: {quality}. Calibrate empirical constants against project cores."
        ],
    )


@feature(
    "libraryConcrete.maturityMethod",
    "Maturity Method",
    part="materials",
    fields=[
        text(
            "tempHistory",
            "Time step [hours], concrete temperature [C]",
            "12, 22\n12, 26\n24, 28\n24, 24\n48, 22",
        ),
        number("datumTempC", "Datum temperature T0", -10.0, unit="C", min=-20.0, max=5.0),
        number("fc28Mpa", "Reference 28-day strength", 32.0, unit="MPa", min=10.0),
    ],
    requires_project=False,
)
def maturity_method(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Nurse-Saul maturity index and estimate in-place concrete strength."""
    steps = parse_pairs(values["tempHistory"], "Temperature history")
    t0 = values["datumTempC"]
    m_total = 0.0
    t_total = 0.0
    rows = []
    for dt, temp in steps:
        dm = max(0.0, temp - t0) * dt
        m_total += dm
        t_total += dt
        # Hyperbolic strength-maturity model normalized to 28 days at 20 C (M_28 = 30 * 672 = 20160 C-h)
        m28 = 30.0 * 24.0 * 28.0
        est_fc = values["fc28Mpa"] * (m_total / (m_total + 0.12 * m28)) * 1.12
        rows.append(
            {
                "cumHours": t_total,
                "tempC": temp,
                "maturityCdegHr": m_total,
                "estimatedFcMpa": min(values["fc28Mpa"] * 1.05, est_fc),
            }
        )
    return result(
        summary={
            "totalHours": t_total,
            "maturityIndexCHr": m_total,
            "estimatedStrengthMpa": rows[-1]["estimatedFcMpa"],
            "strengthRatio": rows[-1]["estimatedFcMpa"] / values["fc28Mpa"],
        },
        tables=[
            table(
                "Maturity strength progression",
                [
                    ("cumHours", "Age", "hr"),
                    ("tempC", "Temp", "C"),
                    ("maturityCdegHr", "Maturity", "C-hr"),
                    ("estimatedFcMpa", "Estimated f'c", "MPa"),
                ],
                rows,
            )
        ],
        notes=[
            f"Nurse-Saul TTF M = sum(T - {t0:g}) dt; verify hyperbolic constants with lab maturity calibration."
        ],
    )
