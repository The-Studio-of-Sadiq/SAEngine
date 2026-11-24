"""Independent known-answer tests for standalone calculators in the BOQ window."""

from __future__ import annotations

import math

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── BOQ Items (boq_items.py: 2) ────────────────────────────────────────────────────────────────────


def test_boq_add_item() -> None:
    res = features.run(
        "boq.addItem",
        None,
        {
            "code": "C.10",
            "group": "concrete",
            "description": "Slab concrete",
            "quantity": 15.0,
            "unit": "m3",
            "unitRate": 12000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["code"] == "C.10"
    assert res["summary"]["quantity"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["amount"] == pytest.approx(180000.0, rel=0.01)


def test_boq_deduct_openings() -> None:
    # Gross = 100 m2 @ 0.2 m thick; thresh = 0.5 m2.
    # D1 (1*2=2.0 >= 0.5, x2 -> 4.0 deducted), V1 (0.4*0.5=0.2 < 0.5 -> 0), W1 (1.5*1.0=1.5 >= 0.5, x1 -> 1.5).
    # Total deducted = 5.5 m2, net area = 94.5 m2, net vol = 18.9 m3.
    res = features.run(
        "boq.deductOpenings",
        None,
        {
            "grossAreaM2": 100.0,
            "thicknessMm": 200.0,
            "minDeductAreaM2": 0.5,
            "openingsCsv": "D1,1.0,2.0,2\nV1,0.4,0.5,3\nW1,1.5,1.0,1",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["deductedAreaM2"] == pytest.approx(5.5, rel=0.01)
    assert res["summary"]["netAreaM2"] == pytest.approx(94.5, rel=0.01)
    assert res["summary"]["netVolumeM3"] == pytest.approx(18.9, rel=0.01)


# ── BOQ Costing (boq_costing.py: 4) ────────────────────────────────────────────────────────────────


def test_boq_costing_labour_rates() -> None:
    # 2 Masons @ 1000 + 4 Helpers @ 500 = 4000 base/day; +10% burden = 4400/day; / 10 m3 = 440/m3.
    res = features.run(
        "boqCosting.labourRates",
        None,
        {
            "crewCsv": "Mason,2,1000,8\nHelper,4,500,8",
            "dailyOutput": 10.0,
            "outputUnit": "m3",
            "burdenPct": 10.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["crewSize"] == 6
    assert res["summary"]["dailyCrewCost"] == pytest.approx(4400.0, rel=0.01)
    assert res["summary"]["unitLabourCost"] == pytest.approx(440.0, rel=0.01)


def test_boq_costing_material_rates() -> None:
    # Base=10000, 10% trade discount -> 9000, +500 haulage -> delivered = 9500, +4% waste = 380 -> 9880.
    res = features.run(
        "boqCosting.materialRates",
        None,
        {
            "baseSupplyPrice": 10000.0,
            "deliveryCharge": 500.0,
            "wastagePct": 4.0,
            "discountPct": 10.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["deliveredRate"] == pytest.approx(9500.0, rel=0.01)
    assert res["summary"]["wastageCost"] == pytest.approx(380.0, rel=0.01)
    assert res["summary"]["effectiveMaterialRate"] == pytest.approx(9880.0, rel=0.01)


def test_boq_costing_plant_rates() -> None:
    # Price=5M, 10 yr, 10% salvage (0.5M), 1000 hr/yr, fuel=1000/hr, operator=300/hr:
    # Operating = 1000 + 300 = 1300/hr; depreciation >= 450/hr; all-in = standing + operating.
    res = features.run(
        "boqCosting.plantRates",
        None,
        {
            "purchasePrice": 5000000.0,
            "lifeYears": 10.0,
            "salvagePct": 10.0,
            "hoursPerYear": 1000.0,
            "fuelAndMaintPerHr": 1000.0,
            "operatorPerHr": 300.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["standingPerHour"] >= 450.0
    assert res["summary"]["operatingPerHour"] == pytest.approx(1300.0, rel=0.01)
    assert res["summary"]["allInHourlyRate"] == pytest.approx(
        res["summary"]["standingPerHour"] + 1300.0, rel=0.01
    )


def test_boq_costing_rate_build_up() -> None:
    # mat=10000*(1.05)=10500, lab=2000, plant=1000 -> net direct = 13500; *1.15 OH&P = 15525.0.
    # Material share of built-up rate = 10500 / 15525 * 100 = 67.6329%.
    res = features.run(
        "boqCosting.rateBuildUp",
        None,
        {
            "itemName": "Grade concrete",
            "materialCost": 10000.0,
            "labourCost": 2000.0,
            "plantCost": 1000.0,
            "wastePct": 5.0,
            "ohpPct": 15.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["netDirectRate"] == pytest.approx(13500.0, rel=0.01)
    assert res["summary"]["builtUpRate"] == pytest.approx(15525.0, rel=0.01)
    assert res["summary"]["materialSharePct"] == pytest.approx(10500.0 / 15525.0 * 100.0, rel=0.01)


# ── BOQ Library (boq_library.py: 11) ───────────────────────────────────────────────────────────────


def test_boq_library_bulk_update() -> None:
    # Default rate schedule has 6 rated items in group 'concrete'; +10% => multiplier 1.10.
    res = features.run(
        "boqLibrary.bulkUpdate", None, {"groupFilter": "concrete", "pctIncrease": 10.0}
    )
    assert res["problems"] == []
    assert res["summary"]["matchedItems"] == 6
    assert res["summary"]["multiplier"] == pytest.approx(1.10, rel=0.01)
    row0 = res["tables"][0]["rows"][0]
    assert row0["newRate"] == pytest.approx(1.10 * row0["oldRate"], rel=0.01)


def test_boq_library_contract_rates() -> None:
    # Default rate schedule has 17 rated items in BDT; 5% discount => contractRate = 0.95 * listRate.
    res = features.run("boqLibrary.contractRates", None, {"volumeDiscountPct": 5.0})
    assert res["problems"] == []
    assert res["summary"]["currency"] == "BDT"
    assert res["summary"]["discountedItems"] == 17
    row0 = res["tables"][0]["rows"][0]
    assert row0["contractRate"] == pytest.approx(0.95 * row0["listRate"], rel=0.01)


def test_boq_library_delivery_terms() -> None:
    # EXW 100000 + 4% freight (4000) + 6% duty (6000) = 110000 landed cost.
    res = features.run(
        "boqLibrary.deliveryTerms",
        None,
        {"incoterm": "EXW", "orderValue": 100000.0, "freightPct": 4.0, "dutyPct": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["invoiceValue"] == pytest.approx(100000.0, rel=0.01)
    assert res["summary"]["buyerFreight"] == pytest.approx(4000.0, rel=0.01)
    assert res["summary"]["buyerDuty"] == pytest.approx(6000.0, rel=0.01)
    assert res["summary"]["totalLandedCost"] == pytest.approx(110000.0, rel=0.01)


def test_boq_library_inflation() -> None:
    # 1,000,000 * 1.10^3 = 1,331,000; multiplier = 1.331.
    res = features.run(
        "boqLibrary.inflation",
        None,
        {"baseAmount": 1000000.0, "annualRatePct": 10.0, "yearsAhead": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["inflationMultiplier"] == pytest.approx(1.331, rel=0.01)
    assert res["summary"]["escalatedAmount"] == pytest.approx(1331000.0, rel=0.01)


def test_boq_library_labour_constants() -> None:
    # 2.5 man-hr/unit * 100 units = 250 man-hr; / 8 hr/day = 31.25 man-days; ceil(31.25 / 5) = 7 gang days.
    res = features.run(
        "boqLibrary.labourConstants",
        None,
        {"hoursPerUnit": 2.5, "quantity": 100.0, "crewSize": 5.0, "hoursPerDay": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalManHours"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["totalManDays"] == pytest.approx(31.25, rel=0.01)
    assert res["summary"]["gangDurationDays"] == 7


def test_boq_library_location_factors() -> None:
    # remote=1.18, haul=50 km @ 6%/100km -> +0.03 -> composite = 1.21.
    res = features.run(
        "boqLibrary.locationFactors",
        None,
        {"remoteness": "remote", "haulageKm": 50.0, "haulagePremiumPer100KmPct": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["baseLocationFactor"] == pytest.approx(1.18, rel=0.01)
    assert res["summary"]["haulageIncrement"] == pytest.approx(0.03, rel=0.01)
    assert res["summary"]["compositeFactor"] == pytest.approx(1.21, rel=0.01)


def test_boq_library_material_prices() -> None:
    # 1:1.5:3 nominal mix (dry=1.54 -> 0.28 m3 cement = 8.064 bags, 14.8322 cft sand, 29.6643 cft stone).
    # 8.064*600 + 14.832174*60 + 29.664348*200 = 4838.40 + 889.93 + 5932.87 = 11661.20.
    res = features.run(
        "boqLibrary.materialPrices",
        None,
        {"cementBagPrice": 600.0, "sandPerCft": 60.0, "stonePerCft": 200.0, "rebarPerKg": 100.0},
    )
    assert res["problems"] == []
    expected = (0.28 * 1440.0 / 50.0) * 600.0 + (0.42 * 35.3147) * 60.0 + (0.84 * 35.3147) * 200.0
    assert res["summary"]["concreteMaterialCostPerM3"] == pytest.approx(expected, rel=0.01)
    assert res["summary"]["rebarPricePerKg"] == pytest.approx(100.0, rel=0.01)


def test_boq_library_plant_output() -> None:
    # 40/hr * 75% = 30/hr * 8 hr = 240/day; 1200 / 240 = 5.0 machine-days.
    res = features.run(
        "boqLibrary.plantOutput",
        None,
        {
            "ratedOutputPerHr": 40.0,
            "siteEfficiencyPct": 75.0,
            "shiftHours": 8.0,
            "targetQuantity": 1200.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveHourlyOutput"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["dailyOutput"] == pytest.approx(240.0, rel=0.01)
    assert res["summary"]["machineDaysRequired"] == pytest.approx(5.0, rel=0.01)


def test_boq_library_rate_validity() -> None:
    # Default rate schedule: 24 items total, 7 with null rate needing entry.
    res = features.run("boqLibrary.rateValidity", None, {"validityDays": 60.0})
    assert res["problems"] == []
    assert res["summary"]["totalItems"] == 24
    assert res["summary"]["needsRevalidation"] == 7


def test_boq_library_supplier_rating() -> None:
    # 0.4*80 + 0.35*90 + 0.25*80 = 32 + 31.5 + 20 = 83.5.
    res = features.run(
        "boqLibrary.supplierRating",
        None,
        {"priceScore": 80.0, "qualityScore": 90.0, "deliveryScore": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["weightedScore"] == pytest.approx(83.5, rel=0.01)


def test_boq_library_update_prices() -> None:
    # Default rate schedule: 17 rated items; +10% -> newRate = 1.10 * oldRate.
    res = features.run("boqLibrary.updatePrices", None, {"adjustmentPct": 10.0})
    assert res["problems"] == []
    assert res["summary"]["updatedItems"] == 17
    assert res["summary"]["adjustmentPct"] == pytest.approx(10.0, rel=0.01)
    row0 = res["tables"][0]["rows"][0]
    assert row0["newRate"] == pytest.approx(1.10 * row0["oldRate"], rel=0.01)


# ── BOQ Reconcile (boq_reconcile.py: 2) ────────────────────────────────────────────────────────────


def test_boq_reconcile_back_charge() -> None:
    # direct = 30000 + 20000 = 50000; +10% admin = 5000; total = 55000.
    res = features.run(
        "boqReconcile.backCharge",
        None,
        {
            "subcontractor": "Sub-B",
            "labourCost": 30000.0,
            "materialCost": 20000.0,
            "adminMarkupPct": 10.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["directCost"] == pytest.approx(50000.0, rel=0.01)
    assert res["summary"]["adminFee"] == pytest.approx(5000.0, rel=0.01)
    assert res["summary"]["totalBackCharge"] == pytest.approx(55000.0, rel=0.01)


def test_boq_reconcile_rate_adjustment() -> None:
    # contractQty=100, actualQty=130 (+30% > 20% thresh), rate=10000, revisedRate=9000.
    # orig = 130*10000 = 1.3M; threshold cap = 120 units @ 10000 + 10 excess @ 9000 = 1.29M (or all 130 @ 9000).
    res = features.run(
        "boqReconcile.rateAdjustment",
        None,
        {
            "contractQty": 100.0,
            "actualQty": 130.0,
            "contractRate": 10000.0,
            "thresholdPct": 20.0,
            "revisedRate": 9000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["quantityChangePct"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["reratingTriggered"] is True
    assert res["summary"]["originalValuation"] == pytest.approx(1300000.0, rel=0.01)
    assert res["summary"]["adjustedValuation"] < res["summary"]["originalValuation"]


# ── BOQ Reports (boq_reports.py: 1) ────────────────────────────────────────────────────────────────


def test_boq_reports_embodied_carbon() -> None:
    # Default pack: cement=0.588, rebar=1.92, steel=1.92, brick=1900 kg/m3 * 0.24.
    # 10000*0.588 + 5000*1.92 + 2000*1.92 + 10*1900*0.24 = 5880 + 9600 + 3840 + 4560 = 23880 kgCO2e = 23.88 tCO2e.
    res = features.run(
        "boqReports.embodiedCarbon",
        None,
        {"cementKg": 10000.0, "rebarKg": 5000.0, "structSteelKg": 2000.0, "brickM3": 10.0},
    )
    assert res["problems"] == []
    tot = 10000.0 * 0.588 + 5000.0 * 1.92 + 2000.0 * 1.92 + 10.0 * 1900.0 * 0.24
    assert res["summary"]["totalCarbonKgCo2e"] == pytest.approx(tot, rel=0.01)
    assert res["summary"]["totalCarbonTonnesCo2e"] == pytest.approx(tot / 1000.0, rel=0.01)


# ── BOQ Schedule (boq_schedule.py: 4) ──────────────────────────────────────────────────────────────


def test_boq_schedule_earned_value() -> None:
    # BAC=1,000,000; PV=50%, EV=40%, AC=50% => SV=-100k, CV=-100k, SPI=0.80, CPI=0.80, EAC=1,250,000.
    res = features.run(
        "boqSchedule.earnedValue",
        None,
        {"bac": 1000000.0, "plannedPct": 50.0, "earnedPct": 40.0, "actualCostPct": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["bac"] == pytest.approx(1000000.0, rel=0.01)
    assert res["summary"]["spi"] == pytest.approx(0.80, rel=0.01)
    assert res["summary"]["cpi"] == pytest.approx(0.80, rel=0.01)
    assert res["summary"]["scheduleVariance"] == pytest.approx(-100000.0, rel=0.01)
    assert res["summary"]["costVariance"] == pytest.approx(-100000.0, rel=0.01)
    assert res["summary"]["eac"] == pytest.approx(1250000.0, rel=0.01)


def test_boq_schedule_shift_patterns() -> None:
    # 37 days on 2 shifts (1.85x) -> ceil(37/1.85) = 20 days, saved = 17 days.
    res = features.run("boqSchedule.shiftPatterns", None, {"baseDurationDays": 37.0, "shifts": "2"})
    assert res["problems"] == []
    assert res["summary"]["shifts"] == 2
    assert res["summary"]["effectiveMultiplier"] == pytest.approx(1.85, rel=0.01)
    assert res["summary"]["adjustedDays"] == 20
    assert res["summary"]["daysSaved"] == pytest.approx(17.0, rel=0.01)


def test_boq_schedule_weather_days() -> None:
    # 50 outdoor days @ 10% rain -> 5.0 allowance days -> 55.0 adjusted days.
    res = features.run("boqSchedule.weatherDays", None, {"outdoorDays": 50.0, "rainProbPct": 10.0})
    assert res["problems"] == []
    assert res["summary"]["weatherAllowanceDays"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["adjustedDays"] == pytest.approx(55.0, rel=0.01)


def test_boq_schedule_work_calendar() -> None:
    # 7-day continuous calendar over 100 days less 10 holidays => 90 net days, efficiency = 0.90.
    res = features.run(
        "boqSchedule.workCalendar",
        None,
        {"workWeek": "7", "calendarDaysSpan": 100.0, "holidaysCount": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["calendarDays"] == 100
    assert res["summary"]["grossWorkingDays"] == 100
    assert res["summary"]["netWorkingDays"] == 90
    assert res["summary"]["efficiencyRatio"] == pytest.approx(0.90, rel=0.01)


# ── BOQ Takeoff (boq_takeoff.py: 6) ────────────────────────────────────────────────────────────────


def test_boq_takeoff_area_takeoff() -> None:
    # Right triangle (0,0)-(10,0)-(0,8), depth=0.5 m:
    # Area = 0.5*10*8 = 40 m2; perim = 10 + 8 + sqrt(164) = 30.8062 m; vol = 20 m3.
    res = features.run(
        "boqTakeoff.areaTakeoff",
        None,
        {"zoneName": "Apron", "polygonPtsM": "0,0\n10,0\n0,8", "depthM": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["perimeterM"] == pytest.approx(18.0 + math.hypot(10.0, 8.0), rel=0.01)
    assert res["summary"]["volumeM3"] == pytest.approx(20.0, rel=0.01)


def test_boq_takeoff_deduction_rules() -> None:
    # 0.30 m2 exceeds concrete limit (0.10) but is below masonry limit (0.50).
    res = features.run(
        "boqTakeoff.deductionRules",
        None,
        {"minConcreteVoidM2": 0.10, "minMasonryOpeningM2": 0.50, "testOpeningM2": 0.30},
    )
    assert res["problems"] == []
    assert res["summary"]["concreteDeduct"] is True
    assert res["summary"]["masonryDeduct"] is False


def test_boq_takeoff_linear_takeoff() -> None:
    # Polyline (0,0)-(3,4)-(15,4) => raw = 5 + 12 = 17 m; scale=2.0 -> 34.0 m; h=3.0 -> face area = 102 m2.
    res = features.run(
        "boqTakeoff.linearTakeoff",
        None,
        {"itemLabel": "Kerb", "polylinePtsM": "0,0\n3,4\n15,4", "scaleFactor": 2.0, "heightM": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["segments"] == 2
    assert res["summary"]["totalLengthM"] == pytest.approx(34.0, rel=0.01)
    assert res["summary"]["faceAreaM2"] == pytest.approx(102.0, rel=0.01)


def test_boq_takeoff_rounding_rules() -> None:
    # 12.34 rounded to nearest 0.5 => 12.5, delta = +0.16.
    res = features.run(
        "boqTakeoff.roundingRules",
        None,
        {"rawQuantity": 12.34, "mode": "nearest05"},
    )
    assert res["problems"] == []
    assert res["summary"]["roundedQuantity"] == pytest.approx(12.5, rel=0.01)
    assert res["summary"]["roundingDelta"] == pytest.approx(0.16, rel=0.01)


def test_boq_takeoff_scale_check() -> None:
    # 100 mm paper = 5200 mm true => calibrated 1:52 vs stated 1:50 => error 4.0% => scaleAccurate=False.
    res = features.run(
        "boqTakeoff.scaleCheck",
        None,
        {"paperDistMm": 100.0, "trueDistMm": 5200.0, "statedScale": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["calibratedScale"] == pytest.approx(52.0, rel=0.01)
    assert res["summary"]["errorPercent"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["scaleAccurate"] is False


def test_boq_takeoff_waste_factors() -> None:
    # 100*(1.04)=104, 10000*(1.05)=10500, 50*(1.10)=55.
    res = features.run(
        "boqTakeoff.wasteFactors",
        None,
        {
            "concreteM3": 100.0,
            "concreteWastePct": 4.0,
            "rebarKg": 10000.0,
            "rebarWastePct": 5.0,
            "masonryM3": 50.0,
            "masonryWastePct": 10.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["grossConcreteM3"] == pytest.approx(104.0, rel=0.01)
    assert res["summary"]["grossRebarKg"] == pytest.approx(10500.0, rel=0.01)
    assert res["summary"]["grossMasonryM3"] == pytest.approx(55.0, rel=0.01)
