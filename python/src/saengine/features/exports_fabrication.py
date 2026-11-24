"""Exports Fabrication - machine files, material schedules and production packages."""

from __future__ import annotations

import json
import math

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
from saengine.features.exports_common import (
    model_elements,
    write_export_json,
    write_export_text,
)
from saengine.features.studies_common import records


@feature("exportsFabrication.ncFiles", "NC Files", part="bim", fields=[])
def nc_files(ctx: FeatureContext, values: dict) -> dict:
    """Generate DSTV NC1 files for the project's fabricated structural steel parts."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to generate steel NC files.")
    from saengine.fabrication.export import export_nc

    response = export_nc(ctx.root)
    paths = [str(p) for p in response.get("files", [])]
    if not paths:
        raise FeatureInputError("The project did not produce any fabrication NC files.")
    relative = [__import__("pathlib").Path(p).relative_to(ctx.root).as_posix() for p in paths]
    return result(
        summary={"fileCount": len(relative), "outputDirectory": "11 Exports/nc"},
        tables=[
            table(
                "Generated NC files",
                [("path", "Relative path")],
                [{"path": path} for path in relative],
            )
        ],
        notes=[*response.get("notes", []), *response.get("problems", [])],
    )


@feature(
    "exportsFabrication.dstvExport",
    "DSTV Export",
    part="bim",
    fields=[
        text("order", "Fabrication order", "Project order"),
        text("phase", "Fabrication phase", "1"),
    ],
)
def dstv_export(ctx: FeatureContext, values: dict) -> dict:
    """Write the engine's DSTV NC1 part files and report their project-relative deliverable paths."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to export DSTV part files.")
    from saengine.fabrication.export import export_nc

    response = export_nc(ctx.root)
    files = [__import__("pathlib").Path(name) for name in response.get("files", [])]
    if not files:
        raise FeatureInputError("There are no steel fabrication parts to write as DSTV NC1 files.")
    return result(
        summary={
            "partFileCount": len(files),
            "order": values["order"],
            "phase": values["phase"],
            "outputDirectory": "11 Exports/nc",
        },
        tables=[
            table(
                "DSTV NC1 parts",
                [("file", "Part file"), ("sizeBytes", "Size", "byte")],
                [
                    {
                        "file": path.relative_to(ctx.root).as_posix(),
                        "sizeBytes": path.stat().st_size,
                    }
                    for path in files
                ],
            )
        ],
        notes=[
            *response.get("notes", []),
            "Order and phase are reported here; the fabrication exporter uses the project fabrication settings for NC headers.",
        ],
    )


@feature(
    "exportsFabrication.boltLists",
    "Bolt Lists",
    part="objects",
    fields=[
        text(
            "bolts",
            "Bolt records",
            '[{"connection":"C1-B1","diameterMm":20,"lengthMm":70,"grade":"8.8","count":8},{"connection":"B1-B2","diameterMm":16,"lengthMm":55,"grade":"8.8","count":4}]',
        )
    ],
    requires_project=False,
)
def bolt_lists(ctx: FeatureContext, values: dict) -> dict:
    """Aggregate bolt takeoffs by diameter, length and grade from connection-level records."""
    groups: dict[tuple, int] = {}
    for row in records(values["bolts"], "bolt records"):
        try:
            key = (float(row["diameterMm"]), float(row["lengthMm"]), str(row["grade"]))
            count = int(row["count"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each bolt record needs diameterMm, lengthMm, grade and integer count."
            ) from error
        if count < 0:
            raise FeatureInputError("Bolt counts must be non-negative.")
        groups[key] = groups.get(key, 0) + count
    rows = [
        {"diameterMm": key[0], "lengthMm": key[1], "grade": key[2], "totalCount": count}
        for key, count in sorted(groups.items())
    ]
    return result(
        summary={"boltTypes": len(rows), "totalBolts": sum(row["totalCount"] for row in rows)},
        tables=[
            table(
                "Bolt procurement list",
                [
                    ("diameterMm", "Diameter", "mm"),
                    ("lengthMm", "Length", "mm"),
                    ("grade", "Grade"),
                    ("totalCount", "Count"),
                ],
                rows,
            )
        ],
        notes=[
            "Identical diameter, length and grade records are consolidated; washers, nuts and spare allowance are not added."
        ],
    )


@feature(
    "exportsFabrication.weldSchedules",
    "Weld Schedules",
    part="objects",
    fields=[
        text(
            "welds",
            "Weld runs",
            '[{"joint":"B1-C1","type":"fillet","legMm":6,"lengthMm":300,"bothSides":true,"count":2},{"joint":"B2-C2","type":"fillet","legMm":8,"lengthMm":250,"bothSides":false,"count":1}]',
        )
    ],
    requires_project=False,
)
def weld_schedules(ctx: FeatureContext, values: dict) -> dict:
    """Calculate nominal fillet-weld throat area and deposited volume for scheduled weld runs."""
    output = []
    for row in records(values["welds"], "weld runs"):
        try:
            leg, length, count = (
                float(row["legMm"]),
                float(row["lengthMm"]),
                int(row.get("count", 1)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each weld needs numeric legMm and lengthMm plus an integer count."
            ) from error
        sides = 2 if row.get("bothSides") else 1
        throat = leg / math.sqrt(2)
        volume = 0.5 * leg**2 * length * sides * count / 1000
        output.append(
            {
                "joint": row.get("joint", "Joint"),
                "type": row.get("type", "fillet"),
                "legMm": leg,
                "effectiveThroatMm": throat,
                "totalLengthM": length * sides * count / 1000,
                "geometricVolumeCm3": volume,
            }
        )
    return result(
        summary={
            "weldRunCount": len(output),
            "totalLengthM": sum(row["totalLengthM"] for row in output),
            "totalVolumeCm3": sum(row["geometricVolumeCm3"] for row in output),
        },
        tables=[
            table(
                "Weld schedule",
                [
                    ("joint", "Joint"),
                    ("type", "Type"),
                    ("legMm", "Leg", "mm"),
                    ("effectiveThroatMm", "Equal-leg throat", "mm"),
                    ("totalLengthM", "Total length", "m"),
                    ("geometricVolumeCm3", "Geometric volume", "cm³"),
                ],
                output,
            )
        ],
        notes=[
            "Equal-leg fillet throat = leg/√2 and geometric weld volume = 0.5 × leg² × total length; weld strength, process allowance and shrinkage are not assessed."
        ],
    )


@feature(
    "exportsFabrication.nestingData",
    "Nesting Data",
    part="bim",
    fields=[
        text("cutLengths", "Required lengths in mm", "4800,3650,2400,2200,1800,1500,1200"),
        number("stockLength", "Stock length", 12000, unit="mm", min=1),
        number("kerf", "Saw kerf", 3, unit="mm", min=0),
    ],
)
def nesting_data(ctx: FeatureContext, values: dict) -> dict:
    """Pack one-dimensional cuts into stock bars using deterministic first-fit decreasing."""
    lengths = sorted(
        (float(x) for x in values["cutLengths"].replace(";", ",").split(",") if x.strip()),
        reverse=True,
    )
    if not lengths or any(length <= 0 or length > values["stockLength"] for length in lengths):
        raise FeatureInputError(
            "Every cut length must be positive and fit within the stock length."
        )
    bars: list[list[float]] = []
    for length in lengths:
        for bar in bars:
            used = sum(bar) + values["kerf"] * len(bar)
            if used + length + values["kerf"] <= values["stockLength"]:
                bar.append(length)
                break
        else:
            bars.append([length])
    rows = [
        {
            "stockBar": i + 1,
            "cutCount": len(bar),
            "usedLengthMm": sum(bar) + values["kerf"] * max(0, len(bar) - 1),
            "offcutMm": values["stockLength"] - sum(bar) - values["kerf"] * max(0, len(bar) - 1),
            "cutsMm": ", ".join(f"{length:g}" for length in bar),
        }
        for i, bar in enumerate(bars)
    ]
    return result(
        summary={
            "requiredCuts": len(lengths),
            "stockBars": len(bars),
            "utilization": sum(lengths) / (len(bars) * values["stockLength"]),
        },
        tables=[
            table(
                "Stock nesting",
                [
                    ("stockBar", "Bar"),
                    ("cutCount", "Cuts"),
                    ("cutsMm", "Cut lengths", "mm"),
                    ("usedLengthMm", "Used", "mm"),
                    ("offcutMm", "Offcut", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "First-fit decreasing on identical stock lengths; kerf is charged between cuts, and remnant reuse is not modeled."
        ],
    )


@feature(
    "exportsFabrication.barBendingData",
    "Bar Bending Data",
    part="bim",
    fields=[
        text(
            "bars",
            "Bar schedule rows",
            '[{"mark":"B1","diameterMm":16,"cutLengthMm":6000,"count":8,"grade":"500"},{"mark":"S1","diameterMm":10,"cutLengthMm":1800,"count":24,"grade":"500"}]',
        )
    ],
    requires_project=False,
)
def bar_bending_data(ctx: FeatureContext, values: dict) -> dict:
    """Calculate bar totals and theoretical mass from cutting lengths and bar diameters."""
    from saengine.drawings.bbs import bar_mass

    output = []
    for row in records(values["bars"], "bar schedule rows"):
        try:
            dia, cut, count = float(row["diameterMm"]), float(row["cutLengthMm"]), int(row["count"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each bar needs diameterMm, cutLengthMm and integer count."
            ) from error
        if dia <= 0 or cut < 0 or count < 0:
            raise FeatureInputError(
                "Bar diameter must be positive; length and quantity cannot be negative."
            )
        total_length = cut * count / 1000
        output.append(
            {
                "mark": row.get("mark", "Bar"),
                "diameterMm": dia,
                "cutLengthMm": cut,
                "count": count,
                "totalLengthM": total_length,
                "massKg": total_length * bar_mass(dia),
                "grade": row.get("grade", ""),
            }
        )
    return result(
        summary={
            "barMarks": len(output),
            "totalBarCount": sum(row["count"] for row in output),
            "totalMassKg": sum(row["massKg"] for row in output),
        },
        tables=[
            table(
                "Bar bending quantities",
                [
                    ("mark", "Mark"),
                    ("diameterMm", "Diameter", "mm"),
                    ("cutLengthMm", "Cut length", "mm"),
                    ("count", "Count"),
                    ("totalLengthM", "Total length", "m"),
                    ("massKg", "Mass", "kg"),
                    ("grade", "Grade"),
                ],
                output,
            )
        ],
        notes=[
            "Mass uses the engine's round-bar unit mass; cutting lengths and counts are taken as supplied and bend deductions are not recalculated."
        ],
    )


@feature(
    "exportsFabrication.precastFiles",
    "Precast Files",
    part="bim",
    fields=[
        text(
            "panels",
            "Precast panel records",
            '[{"mark":"P1","lengthMm":6000,"widthMm":2400,"thicknessMm":180,"massKg":6500},{"mark":"P2","lengthMm":4800,"widthMm":2400,"thicknessMm":180,"massKg":5200}]',
        ),
        text("filename", "Production data name", "precast-panels"),
    ],
    requires_project=False,
)
def precast_files(ctx: FeatureContext, values: dict) -> dict:
    """Package precast panel geometry and handling mass as readable production JSON."""
    panels = records(values["panels"], "precast panels")
    for panel in panels:
        for dimension in ("lengthMm", "widthMm", "thicknessMm", "massKg"):
            try:
                panel[dimension] = float(panel[dimension])
            except (KeyError, TypeError, ValueError) as error:
                raise FeatureInputError(f"Each panel needs a numeric {dimension}.") from error
    if any(
        min(panel[key] for key in ("lengthMm", "widthMm", "thicknessMm", "massKg")) <= 0
        for panel in panels
    ):
        raise FeatureInputError("Panel dimensions and mass must be positive.")
    path = (
        write_export_json(
            ctx,
            f"{values['filename'].strip() or 'precast-panels'}.json",
            {
                "format": "SAEngine.precast-production/1",
                "units": {"geometry": "mm", "mass": "kg"},
                "panels": panels,
            },
            "Precast",
        )
        if ctx.root
        else None
    )
    return result(
        summary={
            "panelCount": len(panels),
            "totalMassKg": sum(panel["massKg"] for panel in panels),
            "outputPath": path,
        },
        tables=[
            table(
                "Precast panel file",
                [(key, key.replace("Mm", " [mm]").title()) for key in panels[0]],
                panels,
            )
        ],
        notes=[
            "Records preserve panel dimensions and mass for downstream precast production planning; no proprietary CAM schema is inferred."
        ],
    )


@feature(
    "exportsFabrication.meshLists",
    "Mesh Lists",
    part="bim",
    fields=[
        text(
            "mesh",
            "Reinforcement mesh records",
            '[{"mark":"M1","wireDiameterMm":8,"spacingXmm":200,"spacingYmm":200,"widthMm":2400,"lengthMm":6000,"count":12}]',
        )
    ],
    requires_project=False,
)
def mesh_lists(ctx: FeatureContext, values: dict) -> dict:
    """Estimate reinforcement mesh wire lengths and mass for rectangular sheets."""
    output = []
    for row in records(values["mesh"], "reinforcement mesh records"):
        try:
            dia, sx, sy, width, length, count = (
                float(row[key])
                for key in (
                    "wireDiameterMm",
                    "spacingXmm",
                    "spacingYmm",
                    "widthMm",
                    "lengthMm",
                    "count",
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each mesh needs diameter, spacing, width, length and count values."
            ) from error
        if min(dia, sx, sy, width, length, count) <= 0:
            raise FeatureInputError(
                "Mesh dimensions, spacing, diameter and sheet count must be positive."
            )
        wires_x = math.floor(width / sx) + 1
        wires_y = math.floor(length / sy) + 1
        total_length = (wires_x * length + wires_y * width) * count / 1000
        mass_per_m = math.pi * (dia / 1000) ** 2 / 4 * 7850
        output.append(
            {
                "mark": row.get("mark", "Mesh"),
                "wiresAlongX": wires_x * count,
                "wiresAlongY": wires_y * count,
                "totalWireLengthM": total_length,
                "estimatedMassKg": total_length * mass_per_m,
            }
        )
    return result(
        summary={
            "sheetTypes": len(output),
            "totalWireLengthM": sum(row["totalWireLengthM"] for row in output),
            "estimatedMassKg": sum(row["estimatedMassKg"] for row in output),
        },
        tables=[
            table(
                "Mesh schedule",
                [
                    ("mark", "Mark"),
                    ("wiresAlongX", "Wires X"),
                    ("wiresAlongY", "Wires Y"),
                    ("totalWireLengthM", "Wire length", "m"),
                    ("estimatedMassKg", "Mass", "kg"),
                ],
                output,
            )
        ],
        notes=[
            "Wire counts are floor(dimension/spacing)+1 and mass uses 7850 kg/m³ steel density; edge cover and laps are not applied."
        ],
    )


@feature(
    "exportsFabrication.cncSettings",
    "CNC Settings",
    part="settings",
    fields=[
        text("machine", "Machine name", "CNC router"),
        select("units", "Machine units", [("mm", "Millimetres"), ("inch", "Inches")], "mm"),
        number("feedRate", "Default feed rate", 1500, unit="mm/min", min=0.1),
        number("spindleSpeed", "Spindle speed", 12000, unit="rpm", min=0),
        number("toolDiameter", "Tool diameter", 8, unit="mm", min=0.1),
    ],
)
def cnc_settings(ctx: FeatureContext, values: dict) -> dict:
    """Validate and save machine coordinate, feed, spindle and cutter defaults."""
    payload = {
        "schema": "SAEngine.cnc-settings/1",
        "machine": values["machine"],
        "units": values["units"],
        "feedRate": values["feedRate"],
        "spindleSpeedRpm": values["spindleSpeed"],
        "toolDiameterMm": values["toolDiameter"],
    }
    path = write_export_json(ctx, "cnc-settings.json", payload, "Fabrication") if ctx.root else None
    return result(
        summary={
            "machine": values["machine"],
            "units": values["units"],
            "feedRate": values["feedRate"],
            "outputPath": path,
        },
        notes=[
            "The setup is stored as a readable machine profile; it does not generate or execute tool motion."
        ],
    )


@feature(
    "exportsFabrication.layerMapping",
    "Layer Mapping",
    part="bim",
    fields=[
        text(
            "mapping",
            "Element kind to layer map",
            '{"beam":"S-BEAM","column":"S-COLUMN","wall":"S-WALL","slab":"S-SLAB"}',
        ),
        text("filename", "DXF filename", "fabrication-layers"),
    ],
)
def layer_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Apply a kind-to-layer map to BIM element records and export a CAD layer manifest."""
    mapping = json.loads(values["mapping"])
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in mapping.items()
    ):
        raise FeatureInputError("Layer mapping must be a JSON object of non-empty layer names.")
    elements = model_elements(ctx)
    rows = [
        {
            "id": element.get("id"),
            "kind": element.get("kind", element.get("type", "unknown")),
            "layer": mapping.get(element.get("kind", element.get("type", "unknown")), "S-OTHER"),
        }
        for element in elements
    ]
    path = (
        write_export_json(
            ctx,
            f"{values['filename'].strip() or 'fabrication-layers'}.layers.json",
            {"mapping": mapping, "elements": rows},
            "CAD",
        )
        if ctx.root
        else None
    )
    return result(
        summary={"elementCount": len(rows), "mappedKinds": len(mapping), "outputPath": path},
        tables=[
            table("Element layers", [("id", "Element"), ("kind", "Kind"), ("layer", "Layer")], rows)
        ],
        notes=[
            "This layer manifest records the proposed CAD layer assignment; a CAD drawing exporter must apply it to entities."
        ],
    )


@feature(
    "exportsFabrication.postProcessor",
    "Post Processor",
    part="settings",
    fields=[
        text("dialect", "Machine dialect", "ISO G-code"),
        text("header", "Program header", "G21\nG90"),
        text("footer", "Program footer", "M30"),
        number("maximumLineLength", "Maximum command line length", 80, min=20, max=512),
    ],
)
def post_processor(ctx: FeatureContext, values: dict) -> dict:
    """Validate a post-processor header and footer and save a local machine profile."""
    commands = [
        line.strip()
        for line in (values["header"] + "\n" + values["footer"]).splitlines()
        if line.strip()
    ]
    long = [line for line in commands if len(line) > values["maximumLineLength"]]
    if long:
        raise FeatureInputError(
            "A configured post-processor command exceeds the maximum line length."
        )
    payload = {
        "dialect": values["dialect"],
        "header": commands[: len([x for x in values["header"].splitlines() if x.strip()])],
        "footer": commands[len([x for x in values["header"].splitlines() if x.strip()]) :],
        "maximumLineLength": int(values["maximumLineLength"]),
    }
    path = (
        write_export_json(ctx, "post-processor.json", payload, "Fabrication") if ctx.root else None
    )
    return result(
        summary={"commandCount": len(commands), "dialect": values["dialect"], "outputPath": path},
        tables=[
            table(
                "Post-processor commands",
                [("sequence", "Sequence"), ("command", "Command")],
                [{"sequence": i + 1, "command": command} for i, command in enumerate(commands)],
            )
        ],
        notes=[
            "Commands are stored as configuration only; macro syntax and safety are the receiving CNC controller's responsibility."
        ],
    )


@feature(
    "exportsFabrication.btlxExport",
    "BTLx Export",
    part="bim",
    fields=[
        text(
            "timber",
            "Timber member records",
            '[{"mark":"T1","lengthMm":4800,"widthMm":140,"heightMm":360,"material":"GL28"}]',
        )
    ],
    requires_project=False,
)
def btlx_export(ctx: FeatureContext, values: dict) -> dict:
    """Serialize timber stock dimensions and identifiers into a readable BTLx-oriented record."""
    timber = records(values["timber"], "timber members")
    for member in timber:
        for key in ("lengthMm", "widthMm", "heightMm"):
            try:
                member[key] = float(member[key])
            except (KeyError, TypeError, ValueError) as error:
                raise FeatureInputError(f"Each timber member needs {key}.") from error
    path = (
        write_export_json(
            ctx,
            "timber-members.btlx-data.json",
            {"format": "SAEngine.timber-members/1", "members": timber},
            "Timber",
        )
        if ctx.root
        else None
    )
    return result(
        summary={"memberCount": len(timber), "outputPath": path},
        tables=[
            table(
                "Timber BTLx source data",
                [(key, key.replace("Mm", " [mm]").title()) for key in timber[0]],
                timber,
            )
        ],
        notes=[
            "Readable production geometry data saved; no BTLx machine schema or CNC operation geometry is fabricated."
        ],
    )


@feature(
    "exportsFabrication.hundeggerCnc",
    "Hundegger CNC",
    part="bim",
    fields=[
        text(
            "parts",
            "Timber part and machining records",
            '[{"mark":"T1","lengthMm":4800,"crossSectionMm":[140,360],"operations":[{"type":"drill","stationMm":250,"diameterMm":16}]}]',
        )
    ],
    requires_project=False,
)
def hundegger_cnc(ctx: FeatureContext, values: dict) -> dict:
    """Validate timber part machining stations and produce an ordered machine-operation list."""
    parts = records(values["parts"], "timber machining records")
    output = []
    for part in parts:
        try:
            length = float(part["lengthMm"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError("Every timber part needs a numeric lengthMm.") from error
        operations = part.get("operations", [])
        for op in operations:
            station = float(op["stationMm"])
            if not 0 <= station <= length:
                raise FeatureInputError(
                    f"Machining station on {part.get('mark', 'part')} lies outside its length."
                )
            output.append(
                {
                    "mark": part.get("mark", "Part"),
                    "stationMm": station,
                    "operation": op.get("type", "operation"),
                    "diameterMm": op.get("diameterMm"),
                }
            )
    output.sort(key=lambda row: (row["mark"], row["stationMm"]))
    path = (
        write_export_json(
            ctx,
            "hundegger-operation-list.json",
            {"machine": "Hundegger", "operations": output},
            "Timber",
        )
        if ctx.root
        else None
    )
    return result(
        summary={"partCount": len(parts), "operationCount": len(output), "outputPath": path},
        tables=[
            table(
                "Ordered machining stations",
                [
                    ("mark", "Part"),
                    ("stationMm", "Station", "mm"),
                    ("operation", "Operation"),
                    ("diameterMm", "Diameter", "mm"),
                ],
                output,
            )
        ],
        notes=[
            "This machine-neutral ordered operation list is not proprietary Hundegger CNC code."
        ],
    )


@feature(
    "exportsFabrication.timberCutList",
    "Timber Cut List",
    part="bim",
    fields=[
        text(
            "members",
            "Timber member dimensions",
            '[{"mark":"T1","lengthMm":4800,"quantity":4,"section":"140x360"},{"mark":"T2","lengthMm":3600,"quantity":6,"section":"120x300"}]',
        ),
        number("stockLength", "Stock length", 6000, unit="mm", min=1),
        number("kerf", "Saw kerf", 3, unit="mm", min=0),
    ],
)
def timber_cut_list(ctx: FeatureContext, values: dict) -> dict:
    """Expand member quantities, group by section and estimate stock sticks and offcuts."""
    items = records(values["members"], "timber cut-list items")
    output = []
    stock_required = 0
    for item in items:
        try:
            length, quantity = float(item["lengthMm"]), int(item["quantity"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each cut-list item needs lengthMm and integer quantity."
            ) from error
        if length <= 0 or quantity < 0 or length > values["stockLength"]:
            raise FeatureInputError(
                "Member lengths must be positive, fit the stock length, and quantities cannot be negative."
            )
        sticks = (
            math.ceil(
                quantity
                / max(
                    1,
                    math.floor(
                        (values["stockLength"] + values["kerf"]) / (length + values["kerf"])
                    ),
                )
            )
            if quantity
            else 0
        )
        stock_required += sticks
        output.append(
            {
                "mark": item.get("mark", "Member"),
                "section": item.get("section", ""),
                "cutLengthMm": length,
                "quantity": quantity,
                "stockSticks": sticks,
            }
        )
    path = (
        write_export_text(
            ctx,
            "timber-cut-list.csv",
            __import__("saengine.features.exports_common", fromlist=["csv_document"]).csv_document(
                output
            ),
            "Timber",
        )
        if ctx.root
        else None
    )
    return result(
        summary={
            "cutMarkCount": len(output),
            "requiredStockSticks": stock_required,
            "outputPath": path,
        },
        tables=[
            table(
                "Timber cut list",
                [
                    ("mark", "Mark"),
                    ("section", "Section"),
                    ("cutLengthMm", "Cut length", "mm"),
                    ("quantity", "Quantity"),
                    ("stockSticks", "Stock sticks"),
                ],
                output,
            )
        ],
        notes=[
            "Stock counts group each cut mark independently; common offcut optimization across different marks is not performed."
        ],
    )


@feature("exportsFabrication.bvbsExport", "BVBS Export", part="bim", fields=[])
def bvbs_export(ctx: FeatureContext, values: dict) -> dict:
    """Write the engine's bar-bending schedule as checksum-protected BVBS records."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to export the reinforcement schedule.")
    from saengine.fabrication.export import export_bvbs

    response = export_bvbs(ctx.root)
    files = response.get("files", [])
    if not files:
        raise FeatureInputError("The project has no detailed reinforcement bars for a BVBS export.")
    relative = [__import__("pathlib").Path(path).relative_to(ctx.root).as_posix() for path in files]
    return result(
        summary={"barMarkCount": response.get("marks", 0), "outputPath": relative[0]},
        tables=[
            table("BVBS deliverables", [("path", "File")], [{"path": path} for path in relative])
        ],
        notes=[*response.get("notes", [])],
    )


@feature(
    "exportsFabrication.couplerSchedule",
    "Coupler Schedule",
    part="bim",
    fields=[
        text(
            "couplers",
            "Coupler joint records",
            '[{"joint":"C1-L1","barDiameterMm":20,"bars":8,"type":"mechanical","location":"column base"},{"joint":"C1-L2","barDiameterMm":16,"bars":12,"type":"mechanical","location":"lap zone"}]',
        )
    ],
    requires_project=False,
)
def coupler_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Group mechanical reinforcement couplers by diameter and type and total their quantities."""
    grouped: dict[tuple, int] = {}
    sources = records(values["couplers"], "coupler joints")
    for row in sources:
        try:
            key = (float(row["barDiameterMm"]), str(row.get("type", "mechanical")))
            count = int(row["bars"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each coupler joint needs barDiameterMm and integer bars."
            ) from error
        grouped[key] = grouped.get(key, 0) + count
    schedule = [
        {"barDiameterMm": dia, "couplerType": kind, "quantity": count}
        for (dia, kind), count in sorted(grouped.items())
    ]
    return result(
        summary={
            "jointCount": len(sources),
            "couplerTypes": len(schedule),
            "totalCouplers": sum(row["quantity"] for row in schedule),
        },
        tables=[
            table(
                "Coupler procurement schedule",
                [
                    ("barDiameterMm", "Bar diameter", "mm"),
                    ("couplerType", "Coupler type"),
                    ("quantity", "Quantity"),
                ],
                schedule,
            )
        ],
        notes=[
            "Every recorded bar end is counted as requiring one coupler; splice detailing and product compatibility remain to be checked."
        ],
    )


@feature(
    "exportsFabrication.rebarTagging",
    "Rebar Tagging",
    part="bim",
    fields=[
        text("marks", "Bar marks", "B1,S1,C2"),
        number("maximumPerBundle", "Maximum bars per bundle", 25, min=1, max=1000),
        text("prefix", "Bundle tag prefix", "RB"),
    ],
    requires_project=False,
)
def rebar_tagging(ctx: FeatureContext, values: dict) -> dict:
    """Assign sequential bundle tags to the requested bar marks within a per-bundle quantity."""
    marks = [mark.strip() for mark in values["marks"].split(",") if mark.strip()]
    if not marks:
        raise FeatureInputError("List at least one bar mark to tag.")
    output = []
    limit = int(values["maximumPerBundle"])
    for i, mark in enumerate(marks):
        output.append(
            {
                "mark": mark,
                "bundle": f"{values['prefix']}-{i // limit + 1:03d}",
                "positionInBundle": i % limit + 1,
            }
        )
    return result(
        summary={"barMarkCount": len(output), "bundleCount": math.ceil(len(output) / limit)},
        tables=[
            table(
                "Rebar bundle tags",
                [("mark", "Bar mark"), ("bundle", "Bundle tag"), ("positionInBundle", "Position")],
                output,
            )
        ],
        notes=[
            "One row represents one bar mark; actual bar counts per mark must be expanded before printing piece-level labels."
        ],
    )


@feature(
    "exportsFabrication.camUniformat",
    "CAM UniFormat",
    part="bim",
    fields=[
        text(
            "panels",
            "Precast panel geometry",
            '[{"mark":"P1","widthMm":2400,"heightMm":3000,"thicknessMm":180,"insertPoints":[[200,200],[2200,200]]}]',
        )
    ],
    requires_project=False,
)
def cam_uniformat(ctx: FeatureContext, values: dict) -> dict:
    """Prepare panel outlines and embedded-part coordinates for precast CAM data handoff."""
    panels = records(values["panels"], "precast panel geometry")
    output = []
    for panel in panels:
        try:
            width, height, thickness = (
                float(panel[key]) for key in ("widthMm", "heightMm", "thicknessMm")
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each panel needs widthMm, heightMm and thicknessMm."
            ) from error
        insert_points = panel.get("insertPoints", [])
        if any(
            not (0 <= float(p[0]) <= width and 0 <= float(p[1]) <= height) for p in insert_points
        ):
            raise FeatureInputError(
                f"An embedded point lies outside panel {panel.get('mark', 'panel')}."
            )
        output.append(
            {
                "mark": panel.get("mark", "Panel"),
                "widthMm": width,
                "heightMm": height,
                "thicknessMm": thickness,
                "insertCount": len(insert_points),
                "insertPoints": insert_points,
            }
        )
    path = (
        write_export_json(
            ctx,
            "precast-cam-data.json",
            {"schema": "SAEngine.precast-cam/1", "panels": output},
            "Precast",
        )
        if ctx.root
        else None
    )
    return result(
        summary={
            "panelCount": len(output),
            "insertCount": sum(row["insertCount"] for row in output),
            "outputPath": path,
        },
        tables=[
            table(
                "Precast CAM panel data",
                [
                    ("mark", "Mark"),
                    ("widthMm", "Width", "mm"),
                    ("heightMm", "Height", "mm"),
                    ("thicknessMm", "Thickness", "mm"),
                    ("insertCount", "Inserts"),
                ],
                output,
            )
        ],
        notes=[
            "A readable panel-production data record is created; proprietary UniFormat machine syntax is not generated."
        ],
    )


@feature(
    "exportsFabrication.palletLayout",
    "Pallet Layout",
    part="bim",
    fields=[
        text(
            "panels",
            "Panel footprint records",
            '[{"mark":"P1","widthMm":2400,"heightMm":3000},{"mark":"P2","widthMm":1800,"heightMm":2400},{"mark":"P3","widthMm":1200,"heightMm":2400}]',
        ),
        number("bedWidth", "Casting bed width", 6000, unit="mm", min=1),
        number("bedLength", "Casting bed length", 12000, unit="mm", min=1),
        number("edgeClearance", "Edge clearance", 100, unit="mm", min=0),
    ],
)
def pallet_layout(ctx: FeatureContext, values: dict) -> dict:
    """Place rectangular panel footprints row-by-row on a casting bed without rotation."""
    panels = sorted(
        records(values["panels"], "panel footprints"),
        key=lambda row: float(row["heightMm"]),
        reverse=True,
    )
    x, y, row_height, output = values["edgeClearance"], values["edgeClearance"], 0.0, []
    for panel in panels:
        width, height = float(panel["widthMm"]), float(panel["heightMm"])
        if x + width > values["bedWidth"] - values["edgeClearance"]:
            x, y = values["edgeClearance"], y + row_height + values["edgeClearance"]
            row_height = 0
        if y + height > values["bedLength"] - values["edgeClearance"]:
            raise FeatureInputError(
                f"Panel {panel.get('mark', 'panel')} does not fit in the remaining bed area."
            )
        output.append(
            {
                "mark": panel.get("mark", "Panel"),
                "xMm": x,
                "yMm": y,
                "widthMm": width,
                "heightMm": height,
            }
        )
        x += width + values["edgeClearance"]
        row_height = max(row_height, height)
    used_area = sum(row["widthMm"] * row["heightMm"] for row in output)
    return result(
        summary={
            "panelCount": len(output),
            "bedAreaM2": values["bedWidth"] * values["bedLength"] / 1e6,
            "panelAreaM2": used_area / 1e6,
            "bedUtilization": used_area / (values["bedWidth"] * values["bedLength"]),
        },
        tables=[
            table(
                "Casting bed positions",
                [
                    ("mark", "Panel"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                    ("widthMm", "Width", "mm"),
                    ("heightMm", "Length", "mm"),
                ],
                output,
            )
        ],
        notes=[
            "Rows are packed by descending panel length, with no rotation or guillotine optimization; overlapping is avoided by the stated edge clearance."
        ],
    )


@feature(
    "exportsFabrication.embeddedParts",
    "Embedded Parts",
    part="bim",
    fields=[
        text(
            "parts",
            "Embedded part coordinates",
            '[{"mark":"EP1","panel":"P1","xMm":200,"yMm":300,"zMm":0,"type":"plate"},{"mark":"A1","panel":"P1","xMm":2200,"yMm":300,"zMm":0,"type":"anchor"}]',
        ),
        text("filename", "Position file name", "embedded-parts"),
    ],
    requires_project=False,
)
def embedded_parts(ctx: FeatureContext, values: dict) -> dict:
    """Validate embedded-part coordinates and export a panel-referenced position file."""
    rows = records(values["parts"], "embedded parts")
    for row in rows:
        try:
            for axis in ("xMm", "yMm", "zMm"):
                row[axis] = float(row[axis])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                "Each embedded part needs numeric xMm, yMm and zMm coordinates."
            ) from error
    path = (
        write_export_text(
            ctx,
            f"{values['filename'].strip() or 'embedded-parts'}.csv",
            __import__("saengine.features.exports_common", fromlist=["csv_document"]).csv_document(
                rows
            ),
            "Precast",
        )
        if ctx.root
        else None
    )
    return result(
        summary={"embeddedPartCount": len(rows), "outputPath": path},
        tables=[
            table(
                "Embedded-part positions",
                [(key, key.replace("Mm", " [mm]").title()) for key in rows[0]],
                rows,
            )
        ],
        notes=[
            "Coordinates are relative to each panel's local datum as supplied; rotation, face orientation and tolerance are not inferred."
        ],
    )


@feature(
    "exportsFabrication.tolerancesFile",
    "Tolerances File",
    part="settings",
    fields=[
        text(
            "dimensions",
            "Dimension stack items",
            '[{"name":"panel width","nominalMm":2400,"toleranceMm":3},{"name":"opening width","nominalMm":900,"toleranceMm":2}]',
        ),
        text("filename", "Tolerance file name", "dimensional-tolerances"),
    ],
    requires_project=False,
)
def tolerances_file(ctx: FeatureContext, values: dict) -> dict:
    """Calculate worst-case and root-sum-square tolerance stacks from explicit dimensional tolerances."""
    parts = records(values["dimensions"], "tolerance stack items")
    for row in parts:
        row["nominalMm"], row["toleranceMm"] = (
            float(row["nominalMm"]),
            abs(float(row["toleranceMm"])),
        )
    worst = sum(row["toleranceMm"] for row in parts)
    rss = math.sqrt(sum(row["toleranceMm"] ** 2 for row in parts))
    path = (
        write_export_json(
            ctx,
            f"{values['filename'].strip() or 'dimensional-tolerances'}.json",
            {
                "schema": "SAEngine.tolerances/1",
                "dimensions": parts,
                "stack": {"worstCaseMm": worst, "rootSumSquareMm": rss},
            },
            "Quality",
        )
        if ctx.root
        else None
    )
    return result(
        summary={
            "dimensionCount": len(parts),
            "worstCaseToleranceMm": worst,
            "rootSumSquareToleranceMm": rss,
            "outputPath": path,
        },
        tables=[
            table(
                "Tolerance contributors",
                [
                    ("name", "Dimension"),
                    ("nominalMm", "Nominal", "mm"),
                    ("toleranceMm", "Tolerance", "mm"),
                ],
                parts,
            )
        ],
        notes=[
            "Worst-case tolerances add directly; RSS assumes statistically independent, centered contributors."
        ],
    )


@feature(
    "exportsFabrication.inspectionPackage",
    "Inspection Package",
    part="bim",
    fields=[
        text(
            "inspections",
            "Inspection checklist items",
            '[{"stage":"Before pour","item":"Check cast-in anchors","acceptance":"Position within drawing tolerance"},{"stage":"Before dispatch","item":"Inspect lifting inserts","acceptance":"Visual and proof-test records available"}]',
        ),
        text("packageName", "Package name", "precast-inspection"),
    ],
    requires_project=False,
)
def inspection_package(ctx: FeatureContext, values: dict) -> dict:
    """Generate a readable inspection package with stages, acceptance criteria and sign-off columns."""
    rows = records(values["inspections"], "inspection checklist")
    if not rows:
        raise FeatureInputError("Add at least one inspection checklist item.")
    header = [
        "Stage",
        "Inspection item",
        "Acceptance criteria",
        "Inspector",
        "Date",
        "Result",
        "Comments",
    ]
    lines = [
        "# Inspection package",
        "",
        f"Package: {values['packageName']}",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * len(header)) + "|",
    ]
    for row in rows:
        vals = [
            row.get("stage", ""),
            row.get("item", ""),
            row.get("acceptance", ""),
            "",
            "",
            "",
            "",
        ]
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in vals) + " |")
    path = (
        write_export_text(
            ctx,
            f"{values['packageName'].strip() or 'inspection-package'}.md",
            "\n".join(lines) + "\n",
            "Quality",
        )
        if ctx.root
        else None
    )
    return result(
        summary={"checkItemCount": len(rows), "outputPath": path},
        tables=[
            table(
                "Inspection checklist",
                [
                    ("stage", "Stage"),
                    ("item", "Inspection item"),
                    ("acceptance", "Acceptance criteria"),
                ],
                rows,
            )
        ],
        notes=[
            "Markdown inspection package saved with blank record fields for site completion; no inspections are marked complete."
        ],
    )
