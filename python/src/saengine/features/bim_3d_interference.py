"""BIM 3D clash and interference feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


def _elem_bbox_mm(
    el: dict[str, Any], obj: dict[str, Any] | None = None
) -> tuple[float, float, float, float, float, float] | None:
    prof = (obj or {}).get("profile") or {}
    half_w = (
        float(prof.get("xDim") or prof.get("width") or (obj or {}).get("thickness") or 300.0) / 2.0
    )
    half_d = (
        float(prof.get("yDim") or prof.get("depth") or (obj or {}).get("thickness") or 300.0) / 2.0
    )
    if isinstance(el.get("position"), list) and len(el["position"]) >= 2:
        x, y = float(el["position"][0]), float(el["position"][1])
        z0 = float(el.get("bottom", 0.0) or 0.0)
        z1 = float(el.get("top", z0 + 3000.0) or (z0 + 3000.0))
        return (x - half_w, y - half_d, z0, x + half_w, y + half_d, z1)
    if isinstance(el.get("start"), list) and isinstance(el.get("end"), list):
        x0, y0 = float(el["start"][0]), float(el["start"][1])
        x1, y1 = float(el["end"][0]), float(el["end"][1])
        if "bottom" in el and "top" in el:
            z0, z1 = float(el["bottom"]), float(el["top"])
        else:
            elev = float(el.get("elevation", 3200.0) or 3200.0)
            z0, z1 = elev - half_d * 2.0, elev
        return (
            min(x0, x1) - half_w,
            min(y0, y1) - half_w,
            z0,
            max(x0, x1) + half_w,
            max(y0, y1) + half_w,
            z1,
        )
    if isinstance(el.get("boundary"), list) and el["boundary"]:
        xs = [float(p[0]) for p in el["boundary"] if isinstance(p, list) and len(p) >= 2]
        ys = [float(p[1]) for p in el["boundary"] if isinstance(p, list) and len(p) >= 2]
        if xs and ys:
            elev = float(el.get("elevation", 3200.0) or 3200.0)
            thick = float((obj or {}).get("thickness") or 150.0)
            return (min(xs), min(ys), elev - thick, max(xs), max(ys), elev)
    return None


def _mep_items_with_bbox(
    mep: dict[str, Any], story_elev: dict[str, float]
) -> list[tuple[str, tuple[float, float, float, float, float, float]]]:
    items: list[tuple[str, tuple[float, float, float, float, float, float]]] = []
    for duct in (mep.get("hvac") or {}).get("ducts") or []:
        pts = duct.get("path") or []
        if len(pts) >= 2:
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            z = story_elev.get(str(duct.get("story", "")), 0.0) + 2700.0
            hw = float(duct.get("width", 400.0)) / 2.0
            hh = float(duct.get("height", 250.0)) / 2.0
            items.append(
                (
                    str(duct.get("id", "DUCT")),
                    (min(xs) - hw, min(ys) - hw, z - hh, max(xs) + hw, max(ys) + hw, z + hh),
                )
            )
    for tray in (mep.get("electrical") or {}).get("trays") or []:
        pts = tray.get("path") or []
        if len(pts) >= 2:
            xs = [float(p[0]) for p in pts]
            ys = [float(p[1]) for p in pts]
            z = story_elev.get(str(tray.get("story", "")), 0.0) + 2500.0
            hw = float(tray.get("width", 300.0)) / 2.0
            hh = float(tray.get("height", 100.0)) / 2.0
            items.append(
                (
                    str(tray.get("id", "TRAY")),
                    (min(xs) - hw, min(ys) - hw, z - hh, max(xs) + hw, max(ys) + hw, z + hh),
                )
            )
    for riser in (mep.get("plumbing") or {}).get("risers") or []:
        r = float(riser.get("diameter") or 100.0) / 2.0
        x, y = float(riser.get("x", 0.0)), float(riser.get("y", 0.0))
        z0 = story_elev.get(str(riser.get("fromStory", "")), 0.0)
        z1 = story_elev.get(str(riser.get("toStory", "")), z0 + 3200.0)
        items.append(
            (str(riser.get("id", "RISER")), (x - r, y - r, min(z0, z1), x + r, y + r, max(z0, z1)))
        )
    return items


def _run_bim_clashes(
    ctx: FeatureContext, data: dict[str, Any], clearance_mm: float = 0.0
) -> list[dict[str, Any]]:
    from saengine.library.mep import MepModel
    from saengine.mep import clash

    raw_mep = ctx.raw("mep")
    if ctx.root is not None and isinstance(raw_mep, dict):
        try:
            mep = MepModel.model_validate(raw_mep)
            if mep.ifcModels:
                structure, building, objects, _ = clash.structural_ifc(ctx.root)
                models, _ = clash.open_models(ctx.root, mep)
                if models:
                    res, _ = clash.find_clashes(
                        structure, building, objects, mep, models, clearance=clearance_mm
                    )
                    return [
                        {
                            "id": str(c.get("id", f"CL-{i + 1:03d}")),
                            "elementA": str(c.get("mepName") or c.get("mep") or ""),
                            "elementB": str(c.get("structural", "")),
                            "clearanceMm": float(c.get("depth", 0.0) or 0.0),
                            "status": "Coordinated" if c.get("status") == "coordinated" else "Open",
                        }
                        for i, c in enumerate(res)
                    ]
        except (ValueError, TypeError, OSError):
            pass

    objs = {
        str(o.get("id", "")): o
        for o in ((ctx.raw("objects") or {}).get("objects") or [])
        if isinstance(o, dict)
    }
    story_elev = {
        str(s.get("id", "")): float(s.get("elevation", 0.0))
        for s in (data.get("stories") or [])
        if isinstance(s, dict)
    }
    clashes: list[dict[str, Any]] = []
    if isinstance(raw_mep, dict):
        mep_boxes = _mep_items_with_bbox(raw_mep, story_elev)
        for el in data.get("elements") or []:
            if not isinstance(el, dict):
                continue
            bb = _elem_bbox_mm(el, objs.get(str(el.get("type", ""))))
            if bb is None:
                continue
            for mid, mb in mep_boxes:
                gx = max(bb[0] - mb[3], mb[0] - bb[3])
                gy = max(bb[1] - mb[4], mb[1] - bb[4])
                gz = max(bb[2] - mb[5], mb[2] - bb[5])
                gap = max(gx, gy, gz)
                if gap <= clearance_mm:
                    clashes.append(
                        {
                            "id": f"CL-{len(clashes) + 1:03d}",
                            "elementA": mid,
                            "elementB": str(el.get("id", "")),
                            "clearanceMm": round(gap, 1),
                            "status": "Open",
                        }
                    )
    return clashes


@feature(
    "bim3dInterference.newTest",
    "New Test",
    part="bim",
    fields=[
        text("testName", "Test name", "Structural vs MEP"),
        select(
            "testType",
            "Test type",
            [("hard", "Hard clash"), ("soft", "Soft clash"), ("clearance", "Clearance")],
            "hard",
        ),
        number("clearanceMm", "Clearance buffer", 50.0, unit="mm", min=0.0),
    ],
)
def new_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Execute 3D structural/MEP clash detection test and save structured results."""
    data = require_bim(ctx)
    tol = 0.0 if values["testType"] == "hard" else float(values["clearanceMm"])
    clashes = _run_bim_clashes(ctx, data, tol)
    hard_count = sum(1 for c in clashes if c["clearanceMm"] <= 0.0)
    payload = {
        "name": values["testName"].strip() or "Clash test",
        "testType": values["testType"],
        "clearanceMm": tol,
        "elementCount": len(data.get("elements") or []),
        "clashCount": len(clashes),
        "hardClashCount": hard_count,
        "clashes": clashes[:50],
    }
    path = write_bim_json(ctx, "bim_clash_test.json", payload)
    return result(
        summary={
            "testName": payload["name"],
            "testType": values["testType"],
            "clashCount": len(clashes),
            "hardClashCount": hard_count,
            "exportPath": path,
        },
        tables=[
            table(
                "Clash Test Results",
                [
                    ("id", "Clash"),
                    ("elementA", "Element A"),
                    ("elementB", "Element B"),
                    ("clearanceMm", "Gap", "mm"),
                    ("status", "Status"),
                ],
                clashes[:25]
                or [
                    {
                        "id": "-",
                        "elementA": "None",
                        "elementB": "None",
                        "clearanceMm": tol,
                        "status": "Clear",
                    }
                ],
            )
        ],
        notes=[
            f"Executed 3D {values['testType']} interference test (tol={tol:g} mm) across {payload['elementCount']} element(s); found {len(clashes)} candidate(s) -> {path}."
        ],
    )


@feature(
    "bim3dInterference.selectionSets",
    "Selection Sets",
    part="bim",
    fields=[
        text("setA", "First selection set", "Structural"),
        text("setB", "Second selection set", "MEP"),
    ],
)
def interference_selection_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Pair selection sets for a clash test."""
    require_bim(ctx)
    return result(summary={"setA": values["setA"], "setB": values["setB"]})


@feature(
    "bim3dInterference.tolerance",
    "Tolerance",
    part="bim",
    fields=[number("tolerance", "Contact tolerance", 10.0, unit="mm", min=0)],
)
def tolerance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set clash-detection tolerance."""
    require_bim(ctx)
    return result(
        summary={"toleranceMm": values["tolerance"], "toleranceM": values["tolerance"] / 1000}
    )


@feature(
    "bim3dInterference.runTest",
    "Run Test",
    part="bim",
    fields=[
        text("testName", "Test name", "Structural vs MEP"),
        number("tolerance", "Tolerance", 10.0, unit="mm", min=0),
    ],
)
def run_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run a basic same-coordinate clash scan over model elements."""
    data = require_bim(ctx)
    elements = [e for e in data["elements"] if isinstance(e, dict)]
    tol = values["tolerance"] / 1000
    clashes = []
    for i, a in enumerate(elements):
        pa = a.get("position")
        for b in elements[i + 1 :]:
            pb = b.get("position")
            if (
                isinstance(pa, list)
                and isinstance(pb, list)
                and len(pa) >= 2
                and len(pb) >= 2
                and abs(float(pa[0]) - float(pb[0])) <= tol * 1000
                and abs(float(pa[1]) - float(pb[1])) <= tol * 1000
            ):
                clashes.append(
                    {
                        "elementA": a["id"],
                        "elementB": b["id"],
                        "kindA": a.get("kind", ""),
                        "kindB": b.get("kind", ""),
                    }
                )
    return result(
        summary={
            "testName": values["testName"],
            "toleranceMm": values["tolerance"],
            "clashCount": len(clashes),
        },
        tables=[
            table(
                "Detected Clashes",
                [
                    ("elementA", "Element A"),
                    ("elementB", "Element B"),
                    ("kindA", "Category A"),
                    ("kindB", "Category B"),
                ],
                clashes,
            )
        ],
    )


@feature(
    "bim3dInterference.softClashTest",
    "Soft Clash Test",
    part="bim",
    fields=[
        number("clearance", "Required clearance", 500.0, unit="mm", min=0),
        text("zoneName", "Clearance zone", "Maintenance"),
    ],
)
def soft_clash_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a soft-clash clearance test."""
    data = require_bim(ctx)
    return result(
        summary={
            "clearanceMm": values["clearance"],
            "zoneName": values["zoneName"],
            "elementCount": len(data["elements"]),
        }
    )


@feature(
    "bim3dInterference.isolateClash",
    "Isolate Clash",
    part="bim",
    fields=[text("elementIds", "Clash element ids", "C1,W1")],
)
def isolate_clash(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Isolate the elements involved in a clash."""
    data = require_bim(ctx)
    ids = {v.strip() for v in values["elementIds"].split(",") if v.strip()}
    rows = [
        {"id": e["id"], "kind": e.get("kind", ""), "type": e.get("type", "")}
        for e in data["elements"]
        if isinstance(e, dict) and e["id"] in ids
    ]
    return result(
        summary={"isolatedCount": len(rows)},
        tables=[
            table(
                "Isolated Clash Elements",
                [("id", "Element id"), ("kind", "Category"), ("type", "Object type")],
                rows,
            )
        ],
    )


@feature(
    "bim3dInterference.nextClash",
    "Next Clash",
    part="bim",
    fields=[number("index", "Clash index", 1.0, unit="", min=1)],
)
def next_clash(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select the next clash by index."""
    require_bim(ctx)
    return result(summary={"clashIndex": int(values["index"])})


@feature(
    "bim3dInterference.markResolved",
    "Mark Resolved",
    part="bim",
    fields=[
        text("clashId", "Clash id", "CL-001"),
        select(
            "status",
            "Resolution status",
            [("resolved", "Resolved"), ("accepted", "Accepted"), ("deferred", "Deferred")],
            "resolved",
        ),
    ],
)
def mark_resolved(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Mark a clash status."""
    require_bim(ctx)
    return result(summary={"clashId": values["clashId"], "status": values["status"]})


@feature(
    "bim3dInterference.addComment",
    "Add Comment",
    part="bim",
    fields=[
        text("clashId", "Clash id", "CL-001"),
        text("comment", "Comment", "Coordinate relocation required"),
        select(
            "status",
            "Updated clash status",
            [("Open", "Open"), ("Active", "Active"), ("Resolved", "Resolved")],
            "Active",
        ),
    ],
)
def add_comment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Append timestamped coordination comment to a clash and update persistent clash comment register."""
    import json
    from datetime import date

    require_bim(ctx)
    cid = values["clashId"].strip()
    if not cid or not values["comment"].strip():
        raise FeatureInputError("Enter both a clash ID and coordination comment.")
    entry = {
        "clashId": cid,
        "comment": values["comment"].strip(),
        "status": values["status"],
        "date": date.today().isoformat(),
    }
    reg = ctx.path("11 Exports/BIM/bim_clash_comment.json")
    entries: list[dict[str, Any]] = []
    if reg is not None and reg.exists():
        try:
            loaded = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = [r for r in loaded if isinstance(r, dict)]
        except ValueError:
            pass
    entries.append(entry)
    path = write_bim_json(ctx, "bim_clash_comment.json", entries)
    return result(
        summary={
            "clashId": cid,
            "status": entry["status"],
            "commentCount": len(entries),
            "exportPath": path,
        },
        tables=[
            table(
                "Clash Coordination Log",
                [
                    ("date", "Date"),
                    ("clashId", "Clash"),
                    ("status", "Status"),
                    ("comment", "Comment"),
                ],
                entries[-15:],
            )
        ],
        notes=[f"Appended coordination note ({len(entries)} total) to {path}."],
    )


@feature(
    "bim3dInterference.clashReport",
    "Clash Report",
    part="bim",
    fields=[
        select("format", "Report format", [("json", "JSON"), ("csv", "CSV")], "json"),
        checkbox("includeResolved", "Include resolved clashes", False),
    ],
)
def clash_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run interference scan against 06 BIM / 07 MEP and export filtered clash report."""
    import json

    data = require_bim(ctx)
    clashes = _run_bim_clashes(ctx, data)
    comments_file = ctx.path("11 Exports/BIM/bim_clash_comment.json")
    status_map: dict[str, str] = {}
    if comments_file is not None and comments_file.exists():
        try:
            loaded = json.loads(comments_file.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                for c in loaded:
                    if isinstance(c, dict) and c.get("clashId"):
                        status_map[str(c["clashId"])] = str(c.get("status", "Open"))
        except ValueError:
            pass
    filtered = []
    for c in clashes:
        st = status_map.get(c["id"], c["status"])
        if not values["includeResolved"] and st == "Resolved":
            continue
        filtered.append({**c, "status": st})
    if values["format"] == "csv":
        path = write_bim_csv(
            ctx,
            "bim_clash_report.csv",
            ["id", "elementA", "elementB", "clearanceMm", "status"],
            filtered,
        )
    else:
        path = write_bim_json(
            ctx, "bim_clash_report.json", {"totalFound": len(filtered), "clashes": filtered}
        )
    return result(
        summary={"format": values["format"], "clashCount": len(filtered), "exportPath": path},
        tables=[
            table(
                "Interference Report",
                [
                    ("id", "Clash"),
                    ("elementA", "Element A"),
                    ("elementB", "Element B"),
                    ("status", "Status"),
                ],
                filtered[:25],
            )
        ],
        notes=[f"Compiled {len(filtered)} interference record(s); exported to {path}."],
    )


@feature(
    "bim3dInterference.exportList",
    "Export List",
    part="bim",
    fields=[
        select("format", "Export format", [("csv", "CSV"), ("json", "JSON")], "csv"),
        text("filename", "File name", "clash_list"),
    ],
)
def export_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export real detected BIM/MEP clash candidates to CSV or JSON."""
    data = require_bim(ctx)
    clashes = _run_bim_clashes(ctx, data, 50.0)
    hard_count = sum(1 for c in clashes if float(c.get("clearanceMm", 0.0)) <= 0.0)
    filename = "".join(c for c in values["filename"] if c.isalnum() or c in "-_") or "clash_list"
    if values["format"] == "json":
        path = write_bim_json(
            ctx, filename + ".json", {"clashCount": len(clashes), "clashes": clashes}
        )
    else:
        path = write_bim_csv(
            ctx, filename + ".csv", ["id", "elementA", "elementB", "clearanceMm", "status"], clashes
        )
    return result(
        summary={
            "format": values["format"],
            "clashCount": len(clashes),
            "hardClashCount": hard_count,
            "exportPath": path,
        },
        tables=[
            table(
                "Exported Clash List",
                [
                    ("id", "ID"),
                    ("elementA", "Element A"),
                    ("elementB", "Element B"),
                    ("clearanceMm", "Gap", "mm"),
                    ("status", "Status"),
                ],
                clashes[:25],
            )
        ],
        notes=[f"Exported {len(clashes)} clash candidate(s) ({hard_count} hard) to {path}."],
    )


@feature(
    "bim3dInterference.filterResults",
    "Filter Results",
    part="bim",
    fields=[
        select(
            "status",
            "Status",
            [("all", "All"), ("open", "Open"), ("resolved", "Resolved"), ("accepted", "Accepted")],
            "open",
        ),
        select(
            "priority",
            "Priority",
            [("all", "All"), ("high", "High"), ("medium", "Medium"), ("low", "Low")],
            "all",
        ),
    ],
)
def filter_results(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure clash-result filters."""
    require_bim(ctx)
    return result(summary={"status": values["status"], "priority": values["priority"]})


@feature(
    "bim3dInterference.clearTests",
    "Clear Tests",
    part="bim",
    fields=[checkbox("confirm", "Clear all clash tests", True)],
)
def clear_tests(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Clear clash-test definitions."""
    require_bim(ctx)
    return result(summary={"cleared": bool(values["confirm"])})


@feature(
    "bim3dInterference.headroomClearance",
    "Headroom Clearance",
    part="bim",
    fields=[
        number("requiredHeadroom", "Required headroom", 2200.0, unit="mm", min=0),
        number("obstructionElevation", "Lowest obstruction elevation", 3200.0, unit="mm"),
        number("floorElevation", "Floor elevation", 0.0, unit="mm"),
    ],
)
def headroom_clearance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check available headroom against a minimum."""
    require_bim(ctx)
    available = values["obstructionElevation"] - values["floorElevation"]
    return result(
        summary={
            "availableHeadroomMm": available,
            "requiredHeadroomMm": values["requiredHeadroom"],
            "headroomPass": available + 1e-9 >= values["requiredHeadroom"],
            "shortfallMm": max(0, values["requiredHeadroom"] - available),
        }
    )


@feature(
    "bim3dInterference.equipmentClearance",
    "Equipment Clearance",
    part="bim",
    fields=[
        number("equipmentWidth", "Equipment width", 1500.0, unit="mm", min=0),
        number("equipmentLength", "Equipment length", 2000.0, unit="mm", min=0),
        number("clearance", "Required perimeter clearance", 600.0, unit="mm", min=0),
    ],
)
def equipment_clearance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate an equipment footprint and required clearance envelope."""
    require_bim(ctx)
    envelopeW = values["equipmentWidth"] + 2 * values["clearance"]
    envelopeL = values["equipmentLength"] + 2 * values["clearance"]
    return result(
        summary={
            "equipmentWidthMm": values["equipmentWidth"],
            "equipmentLengthMm": values["equipmentLength"],
            "envelopeWidthMm": envelopeW,
            "envelopeLengthMm": envelopeL,
            "envelopeAreaM2": envelopeW * envelopeL / 1e6,
        }
    )


@feature(
    "bim3dInterference.maintenanceZone",
    "Maintenance Zone",
    part="bim",
    fields=[
        number("width", "Zone width", 1500.0, unit="mm", min=0),
        number("depth", "Zone depth", 1200.0, unit="mm", min=0),
        number("height", "Zone height", 2200.0, unit="mm", min=0),
    ],
)
def maintenance_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define a maintenance-clearance volume."""
    require_bim(ctx)
    volume = values["width"] * values["depth"] * values["height"] / 1e9
    return result(
        summary={
            "widthM": values["width"] / 1000,
            "depthM": values["depth"] / 1000,
            "heightM": values["height"] / 1000,
            "volumeM3": volume,
        }
    )


@feature(
    "bim3dInterference.clashMatrix",
    "Clash Matrix",
    part="bim",
    fields=[
        text("rowCategories", "Row categories", "Structure,Architectural"),
        text("columnCategories", "Column categories", "MEP,Fire"),
    ],
)
def clash_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a clash-check matrix."""
    require_bim(ctx)
    rows = [v.strip() for v in values["rowCategories"].split(",") if v.strip()]
    cols = [v.strip() for v in values["columnCategories"].split(",") if v.strip()]
    data = [{"row": r, **{c: "Run" for c in cols}} for r in rows]
    return result(
        summary={
            "rowCount": len(rows),
            "columnCount": len(cols),
            "testCount": len(rows) * len(cols),
        },
        tables=[table("Clash Matrix", [("row", "Category")] + [(c, c) for c in cols], data)],
    )


@feature(
    "bim3dInterference.ignoreRules",
    "Ignore Rules",
    part="bim",
    fields=[
        text("ruleName", "Rule name", "Wall penetrations"),
        select(
            "scope",
            "Ignore scope",
            [("pair", "Element pair"), ("category", "Category pair"), ("all", "All matches")],
            "pair",
        ),
    ],
)
def ignore_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure a clash-ignore rule."""
    require_bim(ctx)
    return result(summary={"ruleName": values["ruleName"], "scope": values["scope"]})


@feature(
    "bim3dInterference.groupingRules",
    "Grouping Rules",
    part="bim",
    fields=[
        select(
            "groupBy",
            "Group clashes by",
            [
                ("location", "Location"),
                ("level", "Storey"),
                ("category", "Category"),
                ("system", "System"),
            ],
            "location",
        ),
        number("distance", "Merge distance", 1000.0, unit="mm", min=0),
    ],
)
def grouping_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure clash grouping."""
    require_bim(ctx)
    return result(summary={"groupBy": values["groupBy"], "mergeDistanceMm": values["distance"]})


@feature(
    "bim3dInterference.bcfExport",
    "BCF Export",
    part="bim",
    fields=[
        text("topicPrefix", "Topic prefix", "CLASH"),
        checkbox("includeComments", "Include recorded clash comments", True),
    ],
)
def bcf_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build BCF topic issues from real clash candidates and export via saengine.mep.bcf."""
    import uuid

    from saengine.library.mep import Coordination, Issue
    from saengine.mep import bcf

    data = require_bim(ctx)
    clashes = _run_bim_clashes(ctx, data, 50.0)
    prefix = values["topicPrefix"].strip() or "CLASH"
    issues = [
        Issue(
            id=f"{prefix}-{c['id']}",
            guid=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"saengine.bcf.{prefix}.{c['id']}")),
            title=f"{prefix}: {c['elementA']} vs {c['elementB']}",
            source="clash",
            status="active" if c["status"] == "Open" else "resolved",
            description=f"Clearance {c['clearanceMm']} mm",
        )
        for c in clashes[:40]
    ]
    topics = [
        {
            "guid": iss.guid,
            "title": iss.title,
            "status": iss.status,
            "description": iss.description,
        }
        for iss in issues
    ]
    out_zip = ctx.path("11 Exports/BIM/bim_clashes.bcf")
    if out_zip is not None:
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        coord = Coordination(author="SAEngine", issues=issues)
        out_zip.write_bytes(bcf.export_bcf(coord))
        out_path = out_zip.relative_to(ctx.root).as_posix()
    else:
        out_path = write_bim_json(ctx, "bim_bcf_topics.json", {"topics": topics})
    return result(
        summary={"topicPrefix": prefix, "topicCount": len(topics), "exportPath": out_path},
        tables=[
            table(
                "BCF Topics",
                [("guid", "Topic ID"), ("title", "Title"), ("status", "Status")],
                topics[:20],
            )
        ],
        notes=[f"Generated {len(topics)} BCF clash topic(s); saved to {out_path}."],
    )


@feature(
    "bim3dInterference.assignResponsible",
    "Assign Responsible",
    part="bim",
    fields=[
        text("clashId", "Clash id", "CL-001"),
        text("assignee", "Responsible person", "Project team"),
        select(
            "priority",
            "Priority",
            [("high", "High"), ("medium", "Medium"), ("low", "Low")],
            "medium",
        ),
    ],
)
def assign_responsible(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign clash responsibility."""
    require_bim(ctx)
    return result(
        summary={
            "clashId": values["clashId"],
            "assignee": values["assignee"],
            "priority": values["priority"],
        }
    )


@feature(
    "bim3dInterference.clashStatusMatrix",
    "Clash Status Matrix",
    part="bim",
    fields=[
        text("statuses", "Statuses", "Open,Resolved,Accepted"),
        text("systems", "Systems", "Structure,MEP,Fire"),
    ],
)
def clash_status_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a clash status-by-system matrix."""
    require_bim(ctx)
    statuses = [v.strip() for v in values["statuses"].split(",") if v.strip()]
    systems = [v.strip() for v in values["systems"].split(",") if v.strip()]
    rows = [{"system": s, **{st: 0 for st in statuses}} for s in systems]
    return result(
        summary={
            "statusCount": len(statuses),
            "systemCount": len(systems),
            "totalCells": len(statuses) * len(systems),
        },
        tables=[
            table(
                "Clash Status Matrix", [("system", "System")] + [(st, st) for st in statuses], rows
            )
        ],
    )
