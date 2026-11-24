"""Exports Exchange - structural solver, BIM, CAD, geotechnical and GIS exchange."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

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
    coordinate_rows,
    csv_document,
    model_elements,
    output_path,
    write_export_json,
    write_export_text,
)
from saengine.features.studies_common import records


def _solver_geometry(ctx: FeatureContext):
    """Build deduplicated solver nodes and line element connectivity from BIM members."""
    nodes: dict[tuple[float, float, float], int] = {}
    members = []

    def node(point: tuple[float, float, float]) -> int:
        key = tuple(round(value, 6) for value in point)
        if key not in nodes:
            nodes[key] = len(nodes) + 1
        return nodes[key]

    for element in model_elements(ctx):
        kind = element.get("kind", "")
        start, end = element.get("start"), element.get("end")
        if isinstance(start, dict) and isinstance(end, dict):
            z = float(element.get("elevation", 0))
            a = (float(start["x"]), float(start["y"]), float(start.get("z", z)))
            b = (float(end["x"]), float(end["y"]), float(end.get("z", z)))
        elif kind == "column" and isinstance(element.get("position"), dict):
            pos = element["position"]
            a = (float(pos["x"]), float(pos["y"]), float(element.get("bottom", 0)))
            b = (float(pos["x"]), float(pos["y"]), float(element.get("top", 0)))
        else:
            continue
        members.append(
            {
                "id": str(element.get("id", len(members) + 1)),
                "kind": kind,
                "section": element.get("type", ""),
                "i": node(a),
                "j": node(b),
                "startMm": a,
                "endMm": b,
            }
        )
    if not members:
        raise FeatureInputError("The BIM model has no line members for structural exchange.")
    return nodes, members


@feature(
    "exportsExchange.midasGenMgt",
    "MIDAS Gen MGT",
    part="bim",
    fields=[text("filename", "MGT filename", "model"), text("units", "Midas unit label", "KN, M")],
)
def midas_gen_mgt(ctx: FeatureContext, values: dict) -> dict:
    """Export BIM line geometry as MIDAS text nodes and elements with explicit unit header."""
    nodes, members = _solver_geometry(ctx)
    lines = ["*UNIT", values["units"], "*NODE"]
    lines.extend(
        f"{identifier}, {x / 1000:g}, {y / 1000:g}, {z / 1000:g}"
        for (x, y, z), identifier in nodes.items()
    )
    lines.append("*ELEMENT")
    lines.extend(f"{i + 1}, BEAM, {row['i']}, {row['j']}, 1, 1" for i, row in enumerate(members))
    name = values["filename"].strip() or "model"
    path = write_export_text(ctx, f"{name}.mgt", "\n".join(lines) + "\n", "Midas")
    return result(
        summary={"nodeCount": len(nodes), "elementCount": len(members), "outputPath": path},
        tables=[
            table(
                "MIDAS geometry mapping",
                [
                    ("element", "Element"),
                    ("id", "Source id"),
                    ("i", "Start node"),
                    ("j", "End node"),
                    ("section", "Object type"),
                ],
                [{"element": i + 1, **row} for i, row in enumerate(members)],
            )
        ],
        notes=[
            f"MIDAS GEN geometry exchange written to {path}. Section properties, materials, supports, loads and combinations are not exported by this geometry-only mapping."
        ],
    )


@feature(
    "exportsExchange.abaqusInp",
    "Abaqus INP",
    part="bim",
    fields=[
        text("filename", "Input file name", "model"),
        select(
            "elementType",
            "Beam element family",
            [("B31", "3D beam (B31)"), ("T3D2", "3D truss (T3D2)")],
            "B31",
        ),
    ],
)
def abaqus_inp(ctx: FeatureContext, values: dict) -> dict:
    """Write BIM member nodes and connectivity as an Abaqus orphan-mesh input deck."""
    nodes, members = _solver_geometry(ctx)
    lines = ["*Heading", "SAEngine geometry-only orphan mesh", "*Node"]
    lines.extend(
        f"{identifier}, {x / 1000:.8g}, {y / 1000:.8g}, {z / 1000:.8g}"
        for (x, y, z), identifier in nodes.items()
    )
    lines += [f"*Element, type={values['elementType']}, elset=SAENGINE_MEMBERS"]
    lines.extend(f"{i + 1}, {row['i']}, {row['j']}" for i, row in enumerate(members))
    lines.append("** Add sections, materials, boundary conditions and load steps before analysis.")
    name = values["filename"].strip() or "model"
    path = write_export_text(ctx, f"{name}.inp", "\n".join(lines) + "\n", "Abaqus")
    return result(
        summary={
            "nodeCount": len(nodes),
            "elementCount": len(members),
            "elementType": values["elementType"],
            "outputPath": path,
        },
        notes=[
            f"Abaqus input mesh written to {path}; section definitions, materials, restraints and loads remain project-specific."
        ],
    )


@feature(
    "exportsExchange.robotExr",
    "Robot EXR",
    part="bim",
    fields=[text("filename", "Exchange file name", "robot-model")],
)
def robot_exr(ctx: FeatureContext, values: dict) -> dict:
    """Export line-member geometry and source object references to a readable Robot exchange record."""
    nodes, members = _solver_geometry(ctx)
    payload = {
        "format": "SAEngine.RobotGeometry/1",
        "units": {"length": "m", "force": "kN"},
        "nodes": [
            {"id": identifier, "xyz": [x / 1000, y / 1000, z / 1000]}
            for (x, y, z), identifier in nodes.items()
        ],
        "members": [
            {
                "id": row["id"],
                "kind": row["kind"],
                "startNode": row["i"],
                "endNode": row["j"],
                "sectionType": row["section"],
            }
            for row in members
        ],
    }
    path = write_export_json(
        ctx, f"{values['filename'].strip() or 'robot-model'}.robot-geometry.json", payload, "Robot"
    )
    return result(
        summary={"nodeCount": len(nodes), "memberCount": len(members), "outputPath": path},
        notes=[
            f"Robot geometry mapping saved to {path}; it is an explicit JSON exchange record and does not create a native Robot .str model."
        ],
    )


@feature(
    "exportsExchange.ansysCdb",
    "ANSYS CDB",
    part="bim",
    fields=[
        text("filename", "CDB file name", "model"),
        number("keypointTolerance", "Node merge tolerance", 0.01, unit="mm", min=0),
    ],
)
def ansys_cdb(ctx: FeatureContext, values: dict) -> dict:
    """Write a basic ANSYS APDL database geometry with merged nodes and line elements."""
    nodes, members = _solver_geometry(ctx)
    lines = [
        "/PREP7",
        "! SAEngine geometry exchange; define sections/materials before solving",
        "ET,1,BEAM188",
    ]
    lines.extend(
        f"N,{identifier},{x / 1000:g},{y / 1000:g},{z / 1000:g}"
        for (x, y, z), identifier in nodes.items()
    )
    lines.extend(f"E,{row['i']},{row['j']}" for row in members)
    lines.append("FINISH")
    path = write_export_text(
        ctx, f"{values['filename'].strip() or 'model'}.cdb", "\n".join(lines) + "\n", "ANSYS"
    )
    return result(
        summary={
            "nodeCount": len(nodes),
            "elementCount": len(members),
            "mergeToleranceMm": values["keypointTolerance"],
            "outputPath": path,
        },
        notes=[
            f"ANSYS APDL geometry database written to {path}; nodes are merged by exact source coordinates, and element sections/materials are intentionally left for assignment in the target model."
        ],
    )


@feature(
    "exportsExchange.nastranBdf",
    "Nastran BDF",
    part="bim",
    fields=[
        text("filename", "Bulk data file name", "model"),
        select("coordinateUnit", "Coordinate unit", [("m", "Metres"), ("mm", "Millimetres")], "m"),
    ],
)
def nastran_bdf(ctx: FeatureContext, values: dict) -> dict:
    """Export the model's structural points and line connectivity to Nastran bulk-data cards."""
    nodes, members = _solver_geometry(ctx)
    scale = 0.001 if values["coordinateUnit"] == "m" else 1.0
    lines = ["$ SAEngine basic geometry exchange", "BEGIN BULK"]
    lines.extend(
        f"GRID,{identifier},,{x * scale:.8g},{y * scale:.8g},{z * scale:.8g}"
        for (x, y, z), identifier in nodes.items()
    )
    lines.extend(
        f"$ Member {row['id']} between grid {row['i']} and grid {row['j']}; assign property and material in target."
        for row in members
    )
    lines.append("ENDDATA")
    path = write_export_text(
        ctx, f"{values['filename'].strip() or 'model'}.bdf", "\n".join(lines) + "\n", "Nastran"
    )
    return result(
        summary={
            "gridCount": len(nodes),
            "memberReferences": len(members),
            "coordinateUnit": values["coordinateUnit"],
            "outputPath": path,
        },
        tables=[
            table(
                "Nastran line references",
                [
                    ("id", "Source element"),
                    ("gridI", "Start grid"),
                    ("gridJ", "End grid"),
                    ("sectionType", "Object type"),
                ],
                [
                    {
                        "id": row["id"],
                        "gridI": row["i"],
                        "gridJ": row["j"],
                        "sectionType": row["section"],
                    }
                    for row in members
                ],
            )
        ],
        notes=[
            f"Bulk data written to {path}. GRID cards are valid geometry cards; element property, material, constraints and load cards must be assigned in the receiving model."
        ],
    )


@feature(
    "exportsExchange.ifcStructural",
    "IFC Structural",
    part="bim",
    fields=[
        select("schema", "IFC schema", [("IFC4", "IFC4"), ("IFC2X3", "IFC2X3")], "IFC4"),
        text("filename", "IFC filename", "structural-model"),
    ],
)
def ifc_structural(ctx: FeatureContext, values: dict) -> dict:
    """Write the project's physical model and structural properties as IFC."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to export IFC.")
    from saengine.library.bim import BuildingModel
    from saengine.library.defaults import default_material_library, default_object_library
    from saengine.library.ifc import export_ifc
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    try:
        building = BuildingModel.model_validate(ctx.raw("bim"))
        objects = ObjectLibrary.model_validate(ctx.raw("objects"))
        material_raw = ctx.raw("materials")
        materials = (
            MaterialLibrary.model_validate(material_raw)
            if material_raw
            else default_material_library()
        )
    except Exception as error:
        raise FeatureInputError(
            f"The BIM, objects or materials part is not valid for IFC export: {error}"
        ) from error
    if not objects.objects:
        objects = default_object_library()
    model, ids, skipped = export_ifc(
        building,
        objects,
        materials,
        ctx.root.name,
        schema=values["schema"],
        include_connections=False,
        include_georeferencing=False,
    )
    target = output_path(ctx, f"{values['filename'].strip() or 'structural-model'}.ifc", "IFC")
    model.write(str(target))
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={
            "productCount": len(ids),
            "skippedCount": len(skipped),
            "schema": values["schema"],
            "outputPath": path,
        },
        tables=[
            table(
                "IFC products",
                [("element", "Element"), ("globalId", "Global id")],
                [{"element": key, "globalId": value} for key, value in ids.items()],
            )
        ],
        notes=[
            f"IFC {values['schema']} written to {path}. {len(skipped)} elements were omitted by the IFC writer."
        ],
    )


@feature(
    "exportsExchange.dwgExchange",
    "DWG Exchange",
    part="bim",
    fields=[
        text("filename", "Exchange file name", "cad-geometry"),
        select("unit", "Drawing unit", [("mm", "Millimetres"), ("m", "Metres")], "mm"),
    ],
)
def dwg_exchange(ctx: FeatureContext, values: dict) -> dict:
    """Write a CAD-neutral geometry exchange manifest for line and area element coordinates."""
    rows = coordinate_rows(ctx)
    scale = 0.001 if values["unit"] == "m" else 1.0
    payload = {
        "format": "SAEngine.CADGeometry/1",
        "unit": values["unit"],
        "entities": [
            {
                "element": row["element"],
                "kind": row["kind"],
                "role": row["role"],
                "xyz": [row["xMm"] * scale, row["yMm"] * scale, row["zMm"] * scale],
            }
            for row in rows
        ],
    }
    path = write_export_json(
        ctx, f"{values['filename'].strip() or 'cad-geometry'}.cad-geometry.json", payload, "CAD"
    )
    return result(
        summary={"entityPointCount": len(rows), "outputPath": path},
        notes=[
            f"CAD geometry manifest saved to {path}; it is a neutral JSON interchange file, not a binary DWG drawing."
        ],
    )


@feature(
    "exportsExchange.excelData",
    "Excel Data",
    part="bim",
    fields=[
        select(
            "source",
            "Project data source",
            [
                ("bim", "BIM elements"),
                ("materials", "Materials"),
                ("objects", "Object types"),
                ("boq", "Bill of quantities"),
            ],
            "bim",
        ),
        text("filename", "Workbook filename", "project-data"),
    ],
)
def excel_data(ctx: FeatureContext, values: dict) -> dict:
    """Write one project data collection to a readable Excel worksheet."""
    data = ctx.raw(values["source"])
    if not isinstance(data, dict):
        raise FeatureInputError(f"The project has no {values['source']} JSON file.")
    collection = next((value for value in data.values() if isinstance(value, list)), None)
    if collection is None:
        collection = [data]
    rows = [row for row in collection if isinstance(row, dict)]
    if not rows:
        raise FeatureInputError(f"The {values['source']} part has no records to write.")
    try:
        from openpyxl import Workbook
    except ImportError as error:
        raise FeatureInputError("The Excel workbook dependency is unavailable.") from error
    columns = list(dict.fromkeys(key for row in rows for key in row))
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = values["source"].title()
    sheet.append(columns)
    for row in rows:
        sheet.append(
            [
                json.dumps(row.get(key), ensure_ascii=False)
                if isinstance(row.get(key), (dict, list))
                else row.get(key)
                for key in columns
            ]
        )
    target = output_path(ctx, f"{values['filename'].strip() or 'project-data'}.xlsx", "Data")
    workbook.save(target)
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={"recordCount": len(rows), "columnCount": len(columns), "outputPath": path},
        notes=[f"{values['source']} records written to workbook {path}."],
    )


@feature(
    "exportsExchange.importMapping",
    "Import Mapping",
    part="settings",
    fields=[
        text("sourceFields", "Source field names", "Member ID,Element Type,Section,Level"),
        text(
            "mapping",
            "Source to project field map",
            '{"Member ID":"id","Element Type":"type","Section":"section","Level":"elevation"}',
        ),
    ],
    requires_project=False,
)
def import_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Validate a source-to-SAEngine field map and save it as an import configuration."""
    mapping = json.loads(values["mapping"])
    if not isinstance(mapping, dict):
        raise FeatureInputError(
            "The mapping must be a JSON object from source field to project field."
        )
    source = [name.strip() for name in values["sourceFields"].split(",") if name.strip()]
    rows = [
        {"source": key, "target": value, "sourceExists": key in source}
        for key, value in mapping.items()
    ]
    payload = {"sourceFields": source, "mapping": mapping, "direction": "import"}
    path = write_export_json(ctx, "import-mapping.json", payload, "Mappings") if ctx.root else None
    return result(
        summary={
            "mappingCount": len(mapping),
            "sourceFieldsMissing": sum(not row["sourceExists"] for row in rows),
            "outputPath": path,
        },
        tables=[
            table(
                "Import field map",
                [
                    ("source", "Source field"),
                    ("target", "SAEngine field"),
                    ("sourceExists", "Present in declared source"),
                ],
                rows,
            )
        ],
        notes=[
            "The mapping is saved for review; a subsequent importer must apply the field-specific conversions."
        ],
    )


@feature(
    "exportsExchange.exportMapping",
    "Export Mapping",
    part="settings",
    fields=[
        text("fields", "Project fields to export", "id,type,section,elevation"),
        text(
            "mapping",
            "Project to target field map",
            '{"id":"MemberId","type":"ElementType","section":"SectionName","elevation":"LevelMm"}',
        ),
    ],
    requires_project=False,
)
def export_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Validate and save an SAEngine-to-target field map for later export jobs."""
    mapping = json.loads(values["mapping"])
    if not isinstance(mapping, dict):
        raise FeatureInputError("The export mapping must be a JSON object.")
    allowed = set(values["fields"].split(","))
    output = [
        {"projectField": source, "targetField": target, "knownProjectField": source in allowed}
        for source, target in mapping.items()
    ]
    path = (
        write_export_json(
            ctx,
            "export-mapping.json",
            {"fields": sorted(allowed), "mapping": mapping, "direction": "export"},
            "Mappings",
        )
        if ctx.root
        else None
    )
    return result(
        summary={
            "fieldCount": len(mapping),
            "unlistedProjectFields": sum(not row["knownProjectField"] for row in output),
            "outputPath": path,
        },
        tables=[
            table(
                "Export field map",
                [
                    ("projectField", "Project field"),
                    ("targetField", "Target field"),
                    ("knownProjectField", "Declared"),
                ],
                output,
            )
        ],
        notes=[
            "Saves a reusable mapping definition; the selected target format's serializer applies it when exporting data."
        ],
    )


@feature(
    "exportsExchange.unitMapping",
    "Unit Mapping",
    part="settings",
    fields=[
        text(
            "units",
            "Source and target unit pairs",
            '[{"quantity":"length","source":"mm","target":"m","value":6000},{"quantity":"force","source":"kN","target":"N","value":25}]',
        )
    ],
    requires_project=False,
)
def unit_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Convert explicit source quantities to target units through dimension-checked SI factors."""
    units = {
        "mm": ("length", 0.001),
        "cm": ("length", 0.01),
        "m": ("length", 1),
        "km": ("length", 1000),
        "N": ("force", 1),
        "kN": ("force", 1000),
        "MN": ("force", 1e6),
        "Pa": ("stress", 1),
        "kPa": ("stress", 1000),
        "MPa": ("stress", 1e6),
        "kg": ("mass", 1),
        "t": ("mass", 1000),
    }
    output = []
    for row in records(values["units"], "unit mappings"):
        source, target = row.get("source"), row.get("target")
        if source not in units or target not in units or units[source][0] != units[target][0]:
            raise FeatureInputError(
                f"Unsupported or dimensionally incompatible unit pair: {source} to {target}."
            )
        value = float(row["value"])
        output.append(
            {
                "quantity": row.get("quantity", "Quantity"),
                "source": source,
                "target": target,
                "sourceValue": value,
                "targetValue": value * units[source][1] / units[target][1],
            }
        )
    return result(
        summary={"convertedQuantities": len(output)},
        tables=[
            table(
                "Converted units",
                [
                    ("quantity", "Quantity"),
                    ("sourceValue", "Source value"),
                    ("source", "Source unit"),
                    ("targetValue", "Converted value"),
                    ("target", "Target unit"),
                ],
                output,
            )
        ],
        notes=[
            "Conversions are limited to listed length, force, stress and mass units; compound units require a separate explicit mapping."
        ],
    )


@feature(
    "exportsExchange.revitDbLink",
    "Revit DB Link",
    part="bim",
    fields=[text("filename", "Exchange filename", "revit-link.exchange.json")],
)
def revit_db_link(ctx: FeatureContext, values: dict) -> dict:
    """Build the project's Revit DB Link exchange document, including levels, grids and BIM elements."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to create the Revit exchange document.")
    from saengine.exporters.revit_link import build_exchange

    document = build_exchange(ctx.root)
    name = values["filename"].strip() or "revit-link.exchange.json"
    if not name.endswith(".json"):
        name += ".json"
    path = write_export_json(ctx, name, document, "Revit")
    return result(
        summary={
            "levelCount": len(document["levels"]),
            "gridCount": len(document["grids"]),
            "elementCount": len(document["elements"]),
            "outputPath": path,
        },
        notes=[
            f"Revit DB Link exchange document written to {path}; it is ready for the Revit-side connector to consume."
        ],
    )


@feature(
    "exportsExchange.dxfExport",
    "DXF Export",
    part="bim",
    fields=[
        text("filename", "DXF filename", "building"),
        select(
            "version",
            "DXF version",
            [("R2013", "AutoCAD 2013"), ("R2018", "AutoCAD 2018")],
            "R2018",
        ),
    ],
)
def dxf_export(ctx: FeatureContext, values: dict) -> dict:
    """Export BIM line elements and outlines to a DXF drawing with source element layers."""
    try:
        import ezdxf
    except ImportError as error:
        raise FeatureInputError("The DXF writer dependency is unavailable.") from error
    elements = model_elements(ctx)
    doc = ezdxf.new(values["version"])
    space = doc.modelspace()
    layer_names = set()
    for element in elements:
        layer = str(element.get("kind", element.get("type", "elements")))[:60]
        if layer not in layer_names:
            doc.layers.new(layer)
            layer_names.add(layer)
        start, end = element.get("start"), element.get("end")
        if isinstance(start, dict) and isinstance(end, dict):
            z = float(element.get("elevation", 0))
            space.add_line(
                (start["x"], start["y"], start.get("z", z)),
                (end["x"], end["y"], end.get("z", z)),
                dxfattribs={"layer": layer},
            )
        boundary = element.get("boundary", element.get("outline"))
        if isinstance(boundary, list) and len(boundary) >= 3:
            space.add_polyline3d(
                [
                    (p["x"], p["y"], p.get("z", element.get("elevation", 0)))
                    for p in boundary
                    if isinstance(p, dict)
                ],
                close=True,
                dxfattribs={"layer": layer},
            )
    target = output_path(ctx, f"{values['filename'].strip() or 'building'}.dxf", "CAD")
    doc.saveas(target)
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={"elementCount": len(elements), "layerCount": len(layer_names), "outputPath": path},
        notes=[f"DXF drawing written to {path}; dimensions follow project-grid millimetres."],
    )


@feature(
    "exportsExchange.stepModel",
    "STEP Model",
    part="bim",
    fields=[
        text("filename", "STEP filename", "building"),
        select(
            "schema",
            "STEP exchange schema",
            [
                ("AP214", "Automotive design AP214"),
                ("AP203", "Configuration controlled design AP203"),
            ],
            "AP214",
        ),
    ],
)
def step_model(ctx: FeatureContext, values: dict) -> dict:
    """Write BIM member centerlines and outlines as STEP polyline geometry."""
    points = coordinate_rows(ctx)
    data_ids, geometry = [], []
    for row in points:
        data_ids.append(
            (row["element"], row["role"], row["xMm"] / 1000, row["yMm"] / 1000, row["zMm"] / 1000)
        )
    next_id = 1
    by_element: dict[str, list[int]] = {}
    for element, role, x, y, z in data_ids:
        geometry.append(
            f"#{next_id}=CARTESIAN_POINT('{element}:{role}',({x:.8g},{y:.8g},{z:.8g}));"
        )
        by_element.setdefault(element, []).append(next_id)
        next_id += 1
    for element, point_ids in by_element.items():
        if len(point_ids) >= 2:
            geometry.append(
                f"#{next_id}=POLYLINE('{element}',({','.join(f'#{i}' for i in point_ids)}));"
            )
            next_id += 1
    schema = "CONFIG_CONTROL_DESIGN" if values["schema"] == "AP203" else "AUTOMOTIVE_DESIGN"
    document = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('SAEngine analytical geometry'),'2;1');",
        f"FILE_NAME('{values['filename']}','','',(''),('SAEngine'),'SAEngine','');",
        f"FILE_SCHEMA(('{schema}'));",
        "ENDSEC;",
        "DATA;",
        *geometry,
        "ENDSEC;",
        "END-ISO-10303-21;",
    ]
    path = write_export_text(
        ctx, f"{values['filename'].strip() or 'building'}.step", "\n".join(document) + "\n", "STEP"
    )
    return result(
        summary={"pointCount": len(points), "polylineCount": len(by_element), "outputPath": path},
        notes=[
            f"STEP {values['schema']} wireframe geometry written to {path}; this export contains points and polylines, not closed solids."
        ],
    )


@feature(
    "exportsExchange.igesFile",
    "IGES File",
    part="bim",
    fields=[
        text("filename", "IGES geometry file name", "building"),
        select(
            "entity",
            "IGES entity representation",
            [("points", "3D point set"), ("wireframe", "Wireframe polylines")],
            "wireframe",
        ),
    ],
)
def iges_file(ctx: FeatureContext, values: dict) -> dict:
    """Export a readable IGES-oriented geometry manifest of project points and lines."""
    coordinates = coordinate_rows(ctx)
    payload = {
        "format": "IGES geometry exchange manifest",
        "entityType": "point-set" if values["entity"] == "points" else "wireframe",
        "units": "mm",
        "entities": coordinates,
    }
    path = write_export_json(
        ctx, f"{values['filename'].strip() or 'building'}.iges-geometry.json", payload, "IGES"
    )
    return result(
        summary={
            "pointCount": len(coordinates),
            "entityType": values["entity"],
            "outputPath": path,
        },
        notes=[
            f"IGES-oriented geometry manifest saved to {path}; a native IGES surface/solid writer is not available in the engine, so this JSON file is not an .igs file."
        ],
    )


@feature(
    "exportsExchange.gintData",
    "gINT Data",
    part="soil",
    fields=[text("filename", "Geotechnical export filename", "boreholes")],
)
def gint_data(ctx: FeatureContext, values: dict) -> dict:
    """Export boreholes, strata, SPT records and sample metadata as a normalized CSV exchange."""
    soil = ctx.raw("soil")
    boreholes = soil.get("boreholes", []) if isinstance(soil, dict) else []
    if not boreholes:
        raise FeatureInputError("Add boreholes and soil layers to the 01 Soil Report part first.")
    rows = []
    for hole in boreholes:
        layers = hole.get("layers", []) or [
            {"top": 0, "bottom": hole.get("bottom"), "description": ""}
        ]
        spt = {
            float(record.get("depth", -1)): record
            for record in hole.get("spt", [])
            if isinstance(record, dict)
        }
        for layer in layers:
            depth = float(layer.get("bottom", 0) or 0)
            test = spt.get(depth, {})
            rows.append(
                {
                    "borehole": hole.get("id"),
                    "layerTopMm": layer.get("top"),
                    "layerBottomMm": layer.get("bottom"),
                    "material": layer.get("description", layer.get("name", "")),
                    "sptDepthMm": test.get("depth"),
                    "sptN": test.get("n"),
                    "waterTableMm": hole.get("waterTable"),
                }
            )
    path = write_export_text(
        ctx, f"{values['filename'].strip() or 'boreholes'}.csv", csv_document(rows), "gINT"
    )
    return result(
        summary={"boreholeCount": len(boreholes), "stratumRows": len(rows), "outputPath": path},
        tables=[
            table(
                "Geotechnical rows",
                [(key, key.replace("Mm", " [mm]").title()) for key in rows[0]],
                rows,
            )
        ],
        notes=[
            f"Borehole and stratum data exported to {path} as a tabular exchange; gINT-specific schema validation is not applied."
        ],
    )


@feature(
    "exportsExchange.agcDiggs",
    "AGC DIGGS",
    part="soil",
    fields=[text("filename", "DIGGS XML filename", "geotechnical.xml")],
)
def agc_diggs(ctx: FeatureContext, values: dict) -> dict:
    """Serialize geotechnical boreholes and stratigraphic intervals into structured XML."""
    soil = ctx.raw("soil")
    boreholes = soil.get("boreholes", []) if isinstance(soil, dict) else []
    if not boreholes:
        raise FeatureInputError(
            "Add boreholes to the soil report before building a geotechnical exchange."
        )
    root = ET.Element(
        "GeotechnicalData", {"format": "DIGGS-compatible exchange subset", "units": "mm"}
    )
    for hole in boreholes:
        b = ET.SubElement(root, "Borehole", id=str(hole.get("id", "")))
        if hole.get("bottom") is not None:
            ET.SubElement(b, "TotalDepth").text = str(hole["bottom"])
        for layer in hole.get("layers", []):
            item = ET.SubElement(b, "Stratum")
            for key in ("top", "bottom", "description", "name"):
                if layer.get(key) is not None:
                    ET.SubElement(item, key.title()).text = str(layer[key])
        for spt in hole.get("spt", []):
            item = ET.SubElement(b, "SPT")
            for key, value in spt.items():
                ET.SubElement(item, key).text = str(value)
    path = write_export_text(
        ctx,
        values["filename"].strip() or "geotechnical.xml",
        ET.tostring(root, encoding="unicode", xml_declaration=True),
        "DIGGS",
    )
    return result(
        summary={
            "boreholeCount": len(boreholes),
            "stratumCount": sum(len(hole.get("layers", [])) for hole in boreholes),
            "outputPath": path,
        },
        notes=[
            f"Geotechnical XML subset written to {path}; validate namespace, units and project-specific elements against the receiving DIGGS schema before issue."
        ],
    )


@feature(
    "exportsExchange.geojsonLand",
    "GeoJSON Land",
    part="soil",
    fields=[text("filename", "GeoJSON filename", "site.geojson")],
)
def geojson_land(ctx: FeatureContext, values: dict) -> dict:
    """Export georeferenced site, plot, borehole and building features using the engine GIS exporter."""
    if ctx.root is None:
        raise FeatureInputError("Open a georeferenced project to export site GeoJSON.")
    from saengine.gis.site import gis_export

    target = output_path(ctx, values["filename"].strip() or "site.geojson", "GIS")
    response = gis_export(str(ctx.root), "geojson", str(target))
    if response.get("problems") and not target.exists():
        raise FeatureInputError("; ".join(response["problems"]))
    path = target.relative_to(ctx.root).as_posix()
    return result(
        summary={"featureCount": sum(response.get("counts", {}).values()), "outputPath": path},
        tables=[
            table(
                "GIS feature counts",
                [("layer", "Layer"), ("features", "Features")],
                [
                    {"layer": key, "features": value}
                    for key, value in response.get("counts", {}).items()
                ],
            )
        ],
        notes=[*response.get("problems", []), f"GeoJSON written to {path} in WGS 84 coordinates."],
    )


@feature(
    "exportsExchange.ifcSchemaCheck",
    "IFC Schema Check",
    part="bim",
    fields=[
        text("ifcPath", "IFC file path relative to project", "11 Exports/IFC/structural-model.ifc"),
        select("schema", "Expected schema", [("IFC4", "IFC4"), ("IFC2X3", "IFC2X3")], "IFC4"),
    ],
)
def ifc_schema_check(ctx: FeatureContext, values: dict) -> dict:
    """Parse an IFC file and validate its declared schema and entity reference integrity."""
    if ctx.root is None:
        raise FeatureInputError("Open a project containing an IFC deliverable to validate it.")
    path = (ctx.root / values["ifcPath"]).resolve()
    if ctx.root.resolve() not in path.parents or not path.is_file():
        raise FeatureInputError("The selected IFC file does not exist inside the project.")
    try:
        import ifcopenshell

        model = ifcopenshell.open(str(path))
    except Exception as error:
        raise FeatureInputError(f"The IFC file could not be parsed: {error}") from error
    valid_schema = (
        values["schema"].replace("_", "").upper()
        in model.schema_identifier.replace("_", "").upper()
    )
    products = model.by_type("IfcProduct")
    known = {entity.id() for entity in model}

    def refs(value: object) -> list:
        """The entity instances an attribute points to (lists and tuples included)."""
        if isinstance(value, ifcopenshell.entity_instance):
            return [value]
        if isinstance(value, (list, tuple)):
            return [r for item in value for r in refs(item)]
        return []

    dangling = [
        entity.id()
        for entity in model
        if any(ref.id() and ref.id() not in known for attr in entity for ref in refs(attr))
    ]
    return result(
        summary={
            "declaredSchema": model.schema_identifier,
            "expectedSchema": values["schema"],
            "schemaMatches": valid_schema,
            "productCount": len(products),
            "danglingReferences": len(dangling),
        },
        tables=[
            table(
                "IFC validation",
                [("check", "Check"), ("value", "Value")],
                [
                    {"check": "Schema", "value": model.schema_identifier},
                    {"check": "Expected schema match", "value": valid_schema},
                    {"check": "Product count", "value": len(products)},
                    {"check": "Dangling references", "value": len(dangling)},
                ],
            )
        ],
        notes=[
            "The STEP parser checks syntax and entity references; a full formal schema validation may require a separately installed EXPRESS validator."
        ],
    )


@feature(
    "exportsExchange.propertySetMap",
    "Property Set Map",
    part="bim",
    fields=[
        text(
            "mapping",
            "Property set mapping JSON",
            '{"SAEngine_Element":{"source":"id","target":"ElementId"},"SAEngine_Section":{"source":"type","target":"SectionType"}}',
        )
    ],
)
def property_set_map(ctx: FeatureContext, values: dict) -> dict:
    """Map source BIM properties into named IFC property-set definitions and save the mapping."""
    definitions = json.loads(values["mapping"])
    if not isinstance(definitions, dict) or not definitions:
        raise FeatureInputError("Provide a non-empty JSON object of property sets.")
    elements = model_elements(ctx)
    rows = []
    for pset, spec in definitions.items():
        if not isinstance(spec, dict) or not spec.get("source") or not spec.get("target"):
            raise FeatureInputError(f"Property set {pset} needs source and target keys.")
        rows.append(
            {
                "propertySet": pset,
                "sourceProperty": spec["source"],
                "targetProperty": spec["target"],
                "elementCountWithValue": sum(
                    element.get(spec["source"]) is not None for element in elements
                ),
            }
        )
    path = write_export_json(
        ctx,
        "ifc-property-set-map.json",
        {"schema": "SAEngine.ifc-pset-map/1", "propertySets": definitions},
        "IFC",
    )
    return result(
        summary={
            "propertySetCount": len(rows),
            "mappedElementCount": sum(row["elementCountWithValue"] > 0 for row in rows),
            "outputPath": path,
        },
        tables=[
            table(
                "IFC property-set map",
                [
                    ("propertySet", "Property set"),
                    ("sourceProperty", "Source property"),
                    ("targetProperty", "IFC property"),
                    ("elementCountWithValue", "Elements with value"),
                ],
                rows,
            )
        ],
        notes=[
            f"Mapping definition saved to {path}; it can be applied by an IFC export that supports custom property sets."
        ],
    )
