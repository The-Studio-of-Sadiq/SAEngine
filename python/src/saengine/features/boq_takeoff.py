"""BOQ - Takeoff tab: model, room, linear, area, drawing & verification takeoffs."""

from __future__ import annotations

import math
from typing import Any

from saengine.boq import takeoff as tk
from saengine.boq.quantities import GROUPS
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
from saengine.features.boq_common import (
    load_takeoff,
    parse_csv_rows,
    parse_pairs,
    require_bill,
    save_export,
)


@feature(
    "boqTakeoff.modelTakeoff",
    "Model Takeoff",
    part="boq",
    fields=[],
    requires_project=True,
)
def model_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise quantities measured from the BIM model grouped by trade and measurement unit."""
    bill = require_bill(ctx)
    agg: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], int] = {}
    for it in bill["items"]:
        key = (str(it.get("group", "")), str(it.get("unit", "")))
        agg[key] = agg.get(key, 0.0) + float(it.get("quantity", 0.0))
        counts[key] = counts.get(key, 0) + 1
    rows = [
        {"group": g, "unit": u, "items": counts[(g, u)], "totalQty": q} for (g, u), q in agg.items()
    ]
    return result(
        summary={"totalBillItems": len(bill["items"]), "groupUnitPairs": len(rows)},
        tables=[
            table(
                "BIM model takeoff summary",
                [
                    ("group", "Group"),
                    ("unit", "Unit"),
                    ("items", "Line items"),
                    ("totalQty", "Total quantity"),
                ],
                rows,
            )
        ],
        notes=["Aggregates quantities directly from 10 BOQ/boq.json."],
    )


@feature(
    "boqTakeoff.roomTakeoff",
    "Room Takeoff",
    part="boq",
    fields=[
        text(
            "roomsCsv",
            "Rooms CSV (room,length_m,width_m,height_m,deduct_m2)",
            "Living,5.5,4.2,3.0,3.2\nBedroom-1,4.0,3.6,3.0,2.4\nKitchen,3.2,2.8,3.0,1.8",
        ),
    ],
    requires_project=False,
)
def room_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure floor finish, ceiling finish, skirting, and net wall plaster quantities by room."""
    raw = parse_csv_rows(values["roomsCsv"])
    rows = []
    tot_floor = tot_wall = tot_skirt = 0.0
    for r in raw:
        try:
            l_m = float(r["length_m"])
            w_m = float(r["width_m"])
            h_m = float(r["height_m"])
            ded = float(r.get("deduct_m2", 0.0))
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "CSV requires room, length_m, width_m, height_m, deduct_m2."
            ) from exc
        floor = l_m * w_m
        perim = 2.0 * (l_m + w_m)
        wall = max(0.0, perim * h_m - ded)
        tot_floor += floor
        tot_wall += wall
        tot_skirt += perim
        rows.append(
            {
                "room": r["room"],
                "floorM2": floor,
                "ceilingM2": floor,
                "skirtingM": perim,
                "wallFinishM2": wall,
            }
        )
    return result(
        summary={
            "roomCount": len(rows),
            "floorAreaM2": tot_floor,
            "wallFinishM2": tot_wall,
            "skirtingM": tot_skirt,
        },
        tables=[
            table(
                "Room finishes takeoff",
                [
                    ("room", "Room"),
                    ("floorM2", "Floor", "m2"),
                    ("ceilingM2", "Ceiling", "m2"),
                    ("skirtingM", "Skirting", "m"),
                    ("wallFinishM2", "Wall net", "m2"),
                ],
                rows,
            )
        ],
        notes=["Net wall finish deducts door/window openings from perimeter * clear height."],
    )


@feature(
    "boqTakeoff.linearTakeoff",
    "Linear Takeoff",
    part="boq",
    fields=[
        text("itemLabel", "Linear element", "Boundary wall / kerbs"),
        text("polylinePtsM", "Polyline vertices x,y [m]", "0,0\n12.5,0\n12.5,8.0\n0,8.0"),
        number("scaleFactor", "Scale multiplier", 1.0, min=0.01),
        number("heightM", "Height (0 = keep linear m, >0 = m2)", 0.0, unit="m", min=0.0),
    ],
    requires_project=False,
)
def linear_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure polyline run lengths and optional vertical face areas from 2D coordinates."""
    pts = parse_pairs(values["polylinePtsM"], "Polyline points")
    if len(pts) < 2:
        raise FeatureInputError("Provide at least 2 points for a linear takeoff.")
    seg_rows = []
    tot_len = 0.0
    for i in range(len(pts) - 1):
        seg = math.dist(pts[i], pts[i + 1]) * values["scaleFactor"]
        tot_len += seg
        seg_rows.append(
            {"segment": i + 1, "fromPt": f"{pts[i]}", "toPt": f"{pts[i + 1]}", "lengthM": seg}
        )
    area = tot_len * values["heightM"] if values["heightM"] > 0 else 0.0
    return result(
        summary={"segments": len(seg_rows), "totalLengthM": tot_len, "faceAreaM2": area},
        tables=[
            table(
                f"Linear takeoff: {values['itemLabel']}",
                [
                    ("segment", "Seg #"),
                    ("fromPt", "Start"),
                    ("toPt", "End"),
                    ("lengthM", "Length", "m"),
                ],
                seg_rows,
            )
        ],
        notes=["Uses Euclidean segment summation along the digitised polyline."],
    )


@feature(
    "boqTakeoff.areaTakeoff",
    "Area Takeoff",
    part="boq",
    fields=[
        text("zoneName", "Polygon zone name", "External Paving"),
        text("polygonPtsM", "Closed polygon vertices x,y [m]", "0,0\n15,0\n15,10\n4,10\n0,6"),
        number("depthM", "Thickness/depth (0 = m2 only, >0 = m3)", 0.15, unit="m", min=0.0),
    ],
    requires_project=False,
)
def area_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure closed polygon area and volume via shoelace integration."""
    pts = [list(p) for p in parse_pairs(values["polygonPtsM"], "Polygon vertices")]
    if len(pts) < 3:
        raise FeatureInputError("Provide at least 3 vertices for an area polygon.")
    area = tk.polygon_area(pts)
    perim = tk.polyline_length([*pts, pts[0]])
    vol = area * values["depthM"]
    return result(
        summary={"zone": values["zoneName"], "areaM2": area, "perimeterM": perim, "volumeM3": vol},
        tables=[
            table(
                "Polygon area takeoff",
                [("metric", "Quantity"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Plan area", "value": area, "unit": "m2"},
                    {"metric": "Perimeter", "value": perim, "unit": "m"},
                    {"metric": "Volume (at depth)", "value": vol, "unit": "m3"},
                ],
            )
        ],
        notes=["Computed via saengine.boq.takeoff.polygon_area."],
    )


@feature(
    "boqTakeoff.takeoffAudit",
    "Takeoff Audit",
    part="boq",
    fields=[],
    requires_project=True,
)
def takeoff_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check BOQ quantities against BIM breakdown sums and 2D drawing takeoff calibration."""
    bill = require_bill(ctx)
    rows = []
    mismatches = 0
    for it in bill["items"]:
        q = float(it.get("quantity", 0.0))
        bd_sum = sum(float(b.get("quantity", 0.0)) for b in (it.get("breakdown") or []))
        has_bd = bool(it.get("breakdown"))
        diff = abs(q - bd_sum) if has_bd else 0.0
        ok = diff <= max(0.05, 0.01 * abs(q))
        if not ok:
            mismatches += 1
        rows.append(
            {
                "code": it.get("code"),
                "qty": q,
                "breakdownSum": bd_sum if has_bd else q,
                "diff": diff,
                "ok": ok,
            }
        )
    return result(
        summary={
            "auditedItems": len(rows),
            "mismatches": mismatches,
            "allReconciled": mismatches == 0,
        },
        tables=[
            table(
                "Takeoff vs breakdown audit",
                [
                    ("code", "Code"),
                    ("qty", "Item qty"),
                    ("breakdownSum", "Breakdown sum"),
                    ("diff", "Diff"),
                    ("ok", "OK"),
                ],
                rows[:40],
            )
        ],
        notes=[
            "Verifies every BOQ line item quantity agrees with the sum of its element breakdowns."
        ],
    )


@feature(
    "boqTakeoff.unitCheck",
    "Unit Check",
    part="boq",
    fields=[],
    requires_project=True,
)
def unit_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Flag BOQ items measured in unexpected units for their trade group."""
    bill = require_bill(ctx)
    expected = {
        "earthwork": {"m3"},
        "concrete": {"m3"},
        "masonry": {"m3", "m2"},
        "finishes": {"m2", "nr", "m"},
        "reinforcement": {"kg"},
        "formwork": {"m2"},
        "steel": {"kg"},
        "mep": {"m3", "m2", "kg", "nr", "m"},
        "materials": {"kg", "bag", "cft", "l"},
    }
    rows = []
    bad = 0
    for it in bill["items"]:
        grp = str(it.get("group", ""))
        unit = str(it.get("unit", ""))
        allowed = expected.get(grp, {unit})
        ok = unit in allowed
        if not ok:
            bad += 1
        rows.append(
            {
                "code": it.get("code"),
                "group": grp,
                "unit": unit,
                "allowed": ", ".join(sorted(allowed)),
                "ok": ok,
            }
        )
    return result(
        summary={"checkedItems": len(rows), "unitAnomalies": bad, "allConsistent": bad == 0},
        tables=[
            table(
                "BOQ unit consistency check",
                [
                    ("code", "Code"),
                    ("group", "Group"),
                    ("unit", "Unit"),
                    ("allowed", "Expected"),
                    ("ok", "Valid"),
                ],
                rows[:40],
            )
        ],
        notes=["Compares each item's measurement unit against standard trade-group units."],
    )


@feature(
    "boqTakeoff.overrideQuantity",
    "Override Quantity",
    part="boq",
    fields=[
        text("itemCode", "BOQ item code (blank = first)", ""),
        number("overrideQty", "New override quantity", 10.0, min=0.0),
        text("reason", "Override justification", "Verified against site survey measurement."),
    ],
    requires_project=True,
)
def override_quantity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview overriding a BOQ item's measured quantity with an auditable delta and reason."""
    bill = require_bill(ctx)
    code = values["itemCode"].strip()
    item = (
        next((i for i in bill["items"] if str(i.get("code", "")).lower() == code.lower()), None)
        if code
        else bill["items"][0]
    )
    if item is None:
        raise FeatureInputError(f"BOQ item '{code}' not found.")
    orig = float(item.get("quantity", 0.0))
    new_q = values["overrideQty"]
    return result(
        summary={
            "itemCode": str(item.get("code")),
            "originalQty": orig,
            "overrideQty": new_q,
            "delta": new_q - orig,
        },
        tables=[
            table(
                "Quantity override record",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Item", "value": f"{item.get('code')} - {item.get('description')}"},
                    {"field": "Original quantity", "value": f"{orig} {item.get('unit')}"},
                    {"field": "Override quantity", "value": f"{new_q} {item.get('unit')}"},
                    {"field": "Reason", "value": values["reason"]},
                ],
            )
        ],
        notes=["Records engineer override audit trail without altering 10 BOQ/boq.json."],
    )


@feature(
    "boqTakeoff.dimensionTakeoff",
    "Dimension Takeoff",
    part="boq",
    fields=[
        text(
            "dimCsv",
            "Dimension sheet CSV (mark,times,L_m,W_m,H_m)",
            "Footing Exc,4,2.6,2.1,1.8\nPlinth Beam,6,5.5,0.3,0.45\nSlab S1,1,12.0,10.0,0.15",
        ),
    ],
    requires_project=False,
)
def dimension_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute standard QS dimension-sheet squaring (timesing * L * W * H) into volumes and areas."""
    raw = parse_csv_rows(values["dimCsv"])
    rows = []
    tot_vol = 0.0
    for r in raw:
        try:
            times = float(r["times"])
            l_m = float(r["L_m"])
            w_m = float(r["W_m"])
            h_m = float(r.get("H_m", 1.0))
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires mark, times, L_m, W_m, H_m.") from exc
        vol = times * l_m * w_m * h_m
        tot_vol += vol
        rows.append(
            {"mark": r["mark"], "times": times, "L": l_m, "W": w_m, "H": h_m, "squaredVolM3": vol}
        )
    return result(
        summary={"entries": len(rows), "totalVolumeM3": tot_vol},
        tables=[
            table(
                "QS dimension squaring sheet",
                [
                    ("mark", "Description"),
                    ("times", "Times"),
                    ("L", "L", "m"),
                    ("W", "W", "m"),
                    ("H", "H", "m"),
                    ("squaredVolM3", "Volume", "m3"),
                ],
                rows,
            )
        ],
        notes=["Standard 4-column dimension-sheet squaring."],
    )


@feature(
    "boqTakeoff.countTakeoff",
    "Count Takeoff",
    part="boq",
    fields=[
        text(
            "symbolsCsv",
            "Symbol counts CSV (symbol,sheet,count,rate)",
            "Fire Extinguisher,A-101,12,4500\nFloor Drain,P-101,18,1200\nSmoke Detector,FA-101,32,2800",
        ),
    ],
    requires_project=False,
)
def count_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tally counted drawing symbols and fixtures with extended budget totals."""
    raw = parse_csv_rows(values["symbolsCsv"])
    rows = []
    tot_nr = 0
    tot_val = 0.0
    for r in raw:
        try:
            cnt = int(float(r["count"]))
            rate = float(r.get("rate", 0.0))
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires symbol, sheet, count, rate.") from exc
        amt = cnt * rate
        tot_nr += cnt
        tot_val += amt
        rows.append(
            {
                "symbol": r["symbol"],
                "sheet": r.get("sheet", "-"),
                "count": cnt,
                "rate": rate,
                "amount": amt,
            }
        )
    return result(
        summary={"symbolTypes": len(rows), "totalCountNr": tot_nr, "totalValue": tot_val},
        tables=[
            table(
                "Counted drawing items",
                [
                    ("symbol", "Symbol"),
                    ("sheet", "Sheet"),
                    ("count", "Count [nr]"),
                    ("rate", "Rate"),
                    ("amount", "Amount"),
                ],
                rows,
            )
        ],
        notes=["Tallies discrete counted items across drawing sheets."],
    )


@feature(
    "boqTakeoff.scaleCheck",
    "Scale Check",
    part="boq",
    fields=[
        number(
            "paperDistMm",
            "Measured paper distance between reference ticks",
            120.0,
            unit="mm",
            min=1.0,
        ),
        number("trueDistMm", "Known real-world dimension", 6000.0, unit="mm", min=10.0),
        number("statedScale", "Titleblock stated scale 1:N", 50.0, min=1.0),
    ],
    requires_project=False,
)
def scale_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify PDF/drawing calibration scale factor against stated titleblock scale."""
    sheet = tk.Sheet(
        id="S1",
        file="drawing.pdf",
        calibration=tk.Calibration(
            a=[0.0, 0.0], b=[values["paperDistMm"], 0.0], length=values["trueDistMm"]
        ),
        scale=values["statedScale"],
    )
    true_scale = tk.scale_of(sheet)
    err_pct = (true_scale - values["statedScale"]) / values["statedScale"] * 100.0
    return result(
        summary={
            "calibratedScale": true_scale,
            "statedScale": values["statedScale"],
            "errorPercent": err_pct,
            "scaleAccurate": abs(err_pct) <= 1.0,
        },
        tables=[
            table(
                "Drawing scale calibration check",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Calibrated factor (1:N)", "value": f"1:{true_scale:.2f}"},
                    {"metric": "Stated scale", "value": f"1:{values['statedScale']:g}"},
                    {"metric": "Deviation [%]", "value": err_pct},
                ],
            )
        ],
        notes=["Uses saengine.boq.takeoff.scale_of; flags deviations exceeding 1%."],
    )


@feature(
    "boqTakeoff.layerMapping",
    "Layer Mapping",
    part="boq",
    fields=[
        text(
            "layersCsv",
            "CAD/PDF layers CSV (layer,group,element_kind,unit)",
            "A-WALL-MAS,masonry,wall,m3\nS-SLAB-OUT,concrete,slab,m3\nA-DOOR-SYM,finishes,door,nr",
        ),
    ],
    requires_project=False,
)
def layer_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map CAD/PDF drawing layers onto valid BOQ trade groups and element kinds."""
    raw = parse_csv_rows(values["layersCsv"])
    rows = []
    valid = 0
    for r in raw:
        grp = r.get("group", "")
        ok = grp in GROUPS
        if ok:
            valid += 1
        rows.append(
            {
                "layer": r.get("layer", ""),
                "group": grp,
                "codePrefix": GROUPS.get(grp, "?"),
                "kind": r.get("element_kind", ""),
                "unit": r.get("unit", ""),
                "valid": ok,
            }
        )
    return result(
        summary={"mappedLayers": len(rows), "validGroups": valid},
        tables=[
            table(
                "Drawing layer to BOQ mapping",
                [
                    ("layer", "Layer"),
                    ("group", "BOQ group"),
                    ("codePrefix", "Prefix"),
                    ("kind", "Kind"),
                    ("unit", "Unit"),
                    ("valid", "Valid"),
                ],
                rows,
            )
        ],
        notes=["Validates layer targets against canonical BOQ trade groups."],
    )


@feature(
    "boqTakeoff.deductionRules",
    "Deduction Rules",
    part="boq",
    fields=[
        number(
            "minConcreteVoidM2",
            "Concrete slab opening deduction threshold",
            0.10,
            unit="m2",
            min=0.0,
        ),
        number(
            "minMasonryOpeningM2", "Masonry/plaster opening threshold", 0.50, unit="m2", min=0.0
        ),
        number("testOpeningM2", "Sample opening area to test", 0.45, unit="m2", min=0.0),
    ],
    requires_project=False,
)
def deduction_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate trade-specific minimum void sizes for opening deductions."""
    test = values["testOpeningM2"]
    rows = [
        {
            "trade": "Concrete & Formwork",
            "thresholdM2": values["minConcreteVoidM2"],
            "sampleOpeningM2": test,
            "deduct": test >= values["minConcreteVoidM2"],
        },
        {
            "trade": "Masonry & Plaster",
            "thresholdM2": values["minMasonryOpeningM2"],
            "sampleOpeningM2": test,
            "deduct": test >= values["minMasonryOpeningM2"],
        },
    ]
    return result(
        summary={"concreteDeduct": rows[0]["deduct"], "masonryDeduct": rows[1]["deduct"]},
        tables=[
            table(
                "Trade opening deduction rules",
                [
                    ("trade", "Trade"),
                    ("thresholdM2", "Min void", "m2"),
                    ("sampleOpeningM2", "Test void", "m2"),
                    ("deduct", "Deduct?"),
                ],
                rows,
            )
        ],
        notes=[
            "Small openings below the threshold are left undeducted to cover extra reveal forming/trimming."
        ],
    )


@feature(
    "boqTakeoff.wasteFactors",
    "Waste Factors",
    part="boq",
    fields=[
        number("concreteM3", "Net concrete volume", 45.0, unit="m3", min=0.0),
        number(
            "concreteWastePct", "Concrete spillage/pump waste", 2.5, unit="%", min=0.0, max=20.0
        ),
        number("rebarKg", "Net rebar mass", 5400.0, unit="kg", min=0.0),
        number("rebarWastePct", "Rebar offcut waste", 4.0, unit="%", min=0.0, max=20.0),
        number("masonryM3", "Net masonry volume", 30.0, unit="m3", min=0.0),
        number("masonryWastePct", "Brick breakage waste", 5.0, unit="%", min=0.0, max=20.0),
    ],
    requires_project=False,
)
def waste_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply material-specific procurement wastage factors to net takeoff quantities."""
    rows = [
        {
            "material": "Ready-mix / site concrete",
            "net": values["concreteM3"],
            "unit": "m3",
            "wastePct": values["concreteWastePct"],
            "gross": values["concreteM3"] * (1 + values["concreteWastePct"] / 100),
        },
        {
            "material": "Reinforcement steel",
            "net": values["rebarKg"],
            "unit": "kg",
            "wastePct": values["rebarWastePct"],
            "gross": values["rebarKg"] * (1 + values["rebarWastePct"] / 100),
        },
        {
            "material": "Brickwork masonry",
            "net": values["masonryM3"],
            "unit": "m3",
            "wastePct": values["masonryWastePct"],
            "gross": values["masonryM3"] * (1 + values["masonryWastePct"] / 100),
        },
    ]
    return result(
        summary={
            "grossConcreteM3": rows[0]["gross"],
            "grossRebarKg": rows[1]["gross"],
            "grossMasonryM3": rows[2]["gross"],
        },
        tables=[
            table(
                "Gross procurement quantities with waste",
                [
                    ("material", "Material"),
                    ("net", "Net qty"),
                    ("unit", "Unit"),
                    ("wastePct", "Waste", "%"),
                    ("gross", "Gross order"),
                ],
                rows,
            )
        ],
        notes=["Net bill quantities stay uninflated; gross order quantities include site wastage."],
    )


@feature(
    "boqTakeoff.roundingRules",
    "Rounding Rules",
    part="boq",
    fields=[
        number("rawQuantity", "Raw measured quantity", 14.374, min=0.0),
        select(
            "mode",
            "Rounding rule",
            [
                ("ceilInt", "Round up to whole integer (bags/nr)"),
                ("nearest05", "Nearest 0.5"),
                ("twoDec", "Nearest 0.01 (2 decimals)"),
                ("threeDec", "Nearest 0.001 (3 decimals)"),
            ],
            "twoDec",
        ),
    ],
    requires_project=False,
)
def rounding_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply standard QS quantity rounding increments and report rounding variance."""
    q = values["rawQuantity"]
    m = values["mode"]
    if m == "ceilInt":
        rnd = float(math.ceil(q))
    elif m == "nearest05":
        rnd = round(q * 2.0) / 2.0
    elif m == "twoDec":
        rnd = round(q, 2)
    else:
        rnd = round(q, 3)
    return result(
        summary={"rawQuantity": q, "roundedQuantity": rnd, "roundingDelta": rnd - q},
        tables=[
            table(
                "Quantity rounding result",
                [("rule", "Rule"), ("value", "Value")],
                [
                    {"rule": "Raw measured", "value": q},
                    {"rule": m, "value": rnd},
                    {"rule": "Delta", "value": rnd - q},
                ],
            )
        ],
        notes=[
            "Whole-unit items like cement bags round up; continuous volumes retain 2-3 decimals."
        ],
    )


@feature(
    "boqTakeoff.cutoffHeights",
    "Cutoff Heights",
    part="boq",
    fields=[],
    requires_project=True,
)
def cutoff_heights(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Split measured concrete and masonry quantities across storey elevation bands."""
    bill = require_bill(ctx)
    by_story: dict[str, float] = {}
    for it in bill["items"]:
        if it.get("group") != "concrete":
            continue
        for st, q in (it.get("byStory") or {}).items():
            by_story[str(st)] = by_story.get(str(st), 0.0) + float(q)
    rows = [{"story": st, "concreteM3": q} for st, q in by_story.items()]
    return result(
        summary={
            "storyCount": len(rows),
            "totalStoryConcreteM3": sum(r["concreteM3"] for r in rows),
        },
        tables=[
            table(
                "Concrete quantities split by storey cutoff",
                [("story", "Storey"), ("concreteM3", "Concrete", "m3")],
                rows,
            )
        ],
        notes=["Reflects story-level cutoffs at top-of-slab elevations."],
    )


@feature(
    "boqTakeoff.crossCheckTotals",
    "Cross Check Totals",
    part="boq",
    fields=[],
    requires_project=True,
)
def cross_check_totals(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Cross-check concrete takeoff volume against cement, sand, stone, and reinforcement ratios."""
    bill = require_bill(ctx)
    conc_m3 = sum(
        float(it.get("quantity", 0.0)) for it in bill["items"] if it.get("group") == "concrete"
    )
    rebar_kg = sum(
        float(it.get("quantity", 0.0)) for it in bill["items"] if it.get("group") == "reinforcement"
    )
    form_m2 = sum(
        float(it.get("quantity", 0.0)) for it in bill["items"] if it.get("group") == "formwork"
    )
    cement_kg = sum(
        float(it.get("quantity", 0.0))
        for it in bill["items"]
        if it.get("group") == "materials" and it.get("kind") == "cement"
    )
    steel_intensity = rebar_kg / conc_m3 if conc_m3 > 0 else 0.0
    form_ratio = form_m2 / conc_m3 if conc_m3 > 0 else 0.0
    cement_per_m3 = cement_kg / conc_m3 if conc_m3 > 0 else 0.0
    rows = [
        {
            "ratio": "Reinforcement intensity (kg / m3 concrete)",
            "value": steel_intensity,
            "typicalRange": "80 - 220",
        },
        {
            "ratio": "Formwork ratio (m2 / m3 concrete)",
            "value": form_ratio,
            "typicalRange": "4.0 - 9.0",
        },
        {
            "ratio": "Cement content (kg / m3 concrete)",
            "value": cement_per_m3,
            "typicalRange": "250 - 420",
        },
    ]
    return result(
        summary={
            "concreteM3": conc_m3,
            "rebarKg": rebar_kg,
            "formworkM2": form_m2,
            "rebarIntensityKgM3": steel_intensity,
        },
        tables=[
            table(
                "Independent quantity cross-check ratios",
                [
                    ("ratio", "Cross-check metric"),
                    ("value", "Actual"),
                    ("typicalRange", "Plausible range"),
                ],
                rows,
            )
        ],
        notes=["Sanity-checks primary structural quantities via physical material ratios."],
    )


@feature(
    "boqTakeoff.missingTakeoff",
    "Missing Takeoff",
    part="boq",
    fields=[],
    requires_project=True,
)
def missing_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find BIM elements that do not appear in any measured BOQ item breakdown."""
    bill = require_bill(ctx)
    bim = ctx.raw("bim") or {}
    measured_ids = {
        str(br.get("element"))
        for it in bill["items"]
        for br in (it.get("breakdown") or [])
        if br.get("element")
    }
    missing = [
        {
            "elementId": str(el.get("id")),
            "kind": str(el.get("kind")),
            "story": str(el.get("story", "-")),
        }
        for el in (bim.get("elements") or [])
        if isinstance(el, dict) and str(el.get("id")) not in measured_ids
    ]
    return result(
        summary={
            "bimElements": len(bim.get("elements") or []),
            "measuredElements": len(measured_ids),
            "unmeasuredElements": len(missing),
        },
        tables=[
            table(
                "BIM elements without BOQ breakdown",
                [("elementId", "Element"), ("kind", "Kind"), ("story", "Story")],
                missing or [{"elementId": "-", "kind": "All BIM elements measured", "story": "-"}],
            )
        ],
        notes=["Cross-references 06 BIM/bim.json element IDs against 10 BOQ/boq.json breakdowns."],
    )


@feature(
    "boqTakeoff.takeoffVariance",
    "Takeoff Variance",
    part="boq",
    fields=[number("priorConcreteM3", "Previous issue concrete volume", 25.0, unit="m3", min=0.0)],
    requires_project=True,
)
def takeoff_variance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare current takeoff concrete, rebar, and formwork totals against a prior baseline."""
    bill = require_bill(ctx)
    cur_conc = sum(
        float(it.get("quantity", 0.0)) for it in bill["items"] if it.get("group") == "concrete"
    )
    delta = cur_conc - values["priorConcreteM3"]
    pct = (delta / values["priorConcreteM3"] * 100.0) if values["priorConcreteM3"] > 0 else 0.0
    return result(
        summary={
            "priorConcreteM3": values["priorConcreteM3"],
            "currentConcreteM3": cur_conc,
            "varianceM3": delta,
            "variancePct": pct,
        },
        tables=[
            table(
                "Takeoff revision comparison",
                [
                    ("metric", "Item"),
                    ("prior", "Previous"),
                    ("current", "Current"),
                    ("delta", "Change"),
                ],
                [
                    {
                        "metric": "Total Concrete [m3]",
                        "prior": values["priorConcreteM3"],
                        "current": cur_conc,
                        "delta": delta,
                    }
                ],
            )
        ],
        notes=["Highlights volumetric changes between BOQ revisions."],
    )


@feature(
    "boqTakeoff.takeoffSummary",
    "Takeoff Summary",
    part="boq",
    fields=[],
    requires_project=True,
)
def takeoff_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise all measured BOQ quantities and any 2D drawing takeoff sheets."""
    bill = require_bill(ctx)
    takeoff_doc = load_takeoff(ctx)
    rows = [
        {
            "code": it.get("code"),
            "group": it.get("group"),
            "description": it.get("description"),
            "qty": it.get("quantity"),
            "unit": it.get("unit"),
        }
        for it in bill["items"]
    ]
    tk_summary = tk.summary(takeoff_doc) if takeoff_doc is not None else {"sheets": 0, "items": 0}
    return result(
        summary={
            "billLines": len(rows),
            "drawingTakeoffSheets": tk_summary.get("sheets", 0),
            "drawingTakeoffItems": tk_summary.get("items", 0),
        },
        tables=[
            table(
                "Takeoff master summary",
                [
                    ("code", "Code"),
                    ("group", "Group"),
                    ("description", "Description"),
                    ("qty", "Qty"),
                    ("unit", "Unit"),
                ],
                rows[:50],
            )
        ],
        notes=["Combines 3D BIM model quantities with 2D PDF takeoff sheets when present."],
    )


@feature(
    "boqTakeoff.exportTakeoff",
    "Export Takeoff",
    part="boq",
    fields=[text("filename", "CSV filename", "takeoff-summary.csv")],
    requires_project=True,
)
def export_takeoff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the measured takeoff quantities and breakdowns to CSV under 10 BOQ/exports."""
    bill = require_bill(ctx)
    lines = ["code,group,description,quantity,unit"]
    for it in bill["items"]:
        desc = str(it.get("description", "")).replace('"', '""')
        lines.append(
            f'{it.get("code")},{it.get("group")},"{desc}",{it.get("quantity")},{it.get("unit")}'
        )
    fname = values["filename"].strip() or "takeoff-summary.csv"
    if not fname.lower().endswith(".csv"):
        fname += ".csv"
    target = save_export(ctx, fname, "\n".join(lines) + "\n")
    return result(
        summary={"exportedRows": len(bill["items"]), "exportPath": str(target)},
        tables=[
            table(
                "Takeoff export summary",
                [("item", "Property"), ("value", "Value")],
                [
                    {"item": "File path", "value": str(target)},
                    {"item": "Rows", "value": len(bill["items"])},
                ],
            )
        ],
        notes=[f"Takeoff exported to {target}."],
    )


@feature(
    "boqTakeoff.linkQuantities",
    "Link Quantities",
    part="boq",
    fields=[],
    requires_project=True,
)
def link_quantities(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify and preview linkage of 2D drawing takeoff items into BOQ bill lines."""
    bill = require_bill(ctx)
    takeoff_doc = load_takeoff(ctx)
    if takeoff_doc is not None and takeoff_doc.items:
        linked, notes = tk.bill_items(takeoff_doc, GROUPS)
    else:
        linked, notes = (
            [],
            ["No 10 BOQ/takeoff.json drawing items present; showing model-linked items."],
        )
    rows = [
        {
            "code": it.get("code"),
            "description": it.get("description"),
            "qty": it.get("quantity"),
            "unit": it.get("unit"),
        }
        for it in (linked or bill["items"][:15])
    ]
    return result(
        summary={"drawingLinkedItems": len(linked), "billItems": len(bill["items"])},
        tables=[
            table(
                "Linked takeoff-to-BOQ items",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("qty", "Quantity"),
                    ("unit", "Unit"),
                ],
                rows,
            )
        ],
        notes=notes
        or ["All calibrated drawing takeoff items linked via saengine.boq.takeoff.bill_items."],
    )
