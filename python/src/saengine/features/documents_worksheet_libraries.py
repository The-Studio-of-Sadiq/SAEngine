"""Reusable formulas, engineering constants, section profiles and material lookup tables."""

from __future__ import annotations

import json
import math
import re
from itertools import pairwise

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    text,
)
from saengine.features.documents_common import (
    cell_address,
    cell_value,
    ensure_cell,
    parse_cell,
    range_cells,
    read_csv_rows,
    require_root,
    save_worksheet_workspace,
    worksheet_workspace,
)


def _open(ctx, values):
    return worksheet_workspace(ctx, values["worksheetId"])


def _save(ctx, sheet, state, summary):
    path = save_worksheet_workspace(ctx, sheet, state)
    return result(summary={**summary, "worksheetId": sheet.id, "worksheetPath": path})


@feature(
    "documentsWorksheetLibraries.insertFormula",
    "Insert Formula",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Destination cell", "A1"),
        text("formula", "Formula", "=SUM(B1:B10)"),
    ],
)
def insert_formula(ctx: FeatureContext, values: dict) -> dict:
    """Insert a formula into a cell and immediately evaluate it to catch invalid references."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    cell["formula"] = (
        values["formula"] if values["formula"].startswith("=") else "=" + values["formula"]
    )
    cell.pop("value", None)
    value = cell_value(values["cell"], state)
    return _save(
        ctx, sheet, state, {"cell": values["cell"], "formula": cell["formula"], "value": value}
    )


@feature(
    "documentsWorksheetLibraries.searchFormulas",
    "Search Formulas",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("query", "Formula text", "SUM"),
    ],
)
def search_formulas(ctx: FeatureContext, values: dict) -> dict:
    """Search worksheet formulas for a function or expression fragment."""
    sheet, state = _open(ctx, values)
    matches = [
        {"cell": address, "formula": cell["formula"]}
        for address, cell in state.get("cells", {}).items()
        if values["query"].casefold() in str(cell.get("formula", "")).casefold()
    ]
    state.setdefault("settings", {})["formulaSearch"] = {
        "query": values["query"],
        "matches": matches,
    }
    _save(ctx, sheet, state, {"matchCount": len(matches)})
    return result(
        summary={"matchCount": len(matches)},
        tables=[
            {
                "title": "Formula search",
                "columns": [
                    {"key": "cell", "title": "Cell"},
                    {"key": "formula", "title": "Formula"},
                ],
                "rows": matches,
            }
        ],
    )


@feature(
    "documentsWorksheetLibraries.favouriteFormulas",
    "Favourite Formulas",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("formula", "Formula text", "=SUM(A1:A5)"),
        text("label", "Label", "Column total"),
        checkbox("remove", "Remove favourite", False),
    ],
)
def favourite_formulas(ctx: FeatureContext, values: dict) -> dict:
    """Add or remove a labeled formula from the engineer's project formula favourites."""
    sheet, state = _open(ctx, values)
    favorites = state.setdefault("favoriteFormulas", [])
    key = values["formula"].strip()
    if values["remove"]:
        state["favoriteFormulas"] = [item for item in favorites if item.get("formula") != key]
    elif not any(item.get("formula") == key for item in favorites):
        favorites.append({"formula": key, "label": values["label"].strip()})
    return _save(
        ctx,
        sheet,
        state,
        {
            "favoriteCount": len(state["favoriteFormulas"]),
            "formula": key,
            "removed": values["remove"],
        },
    )


@feature(
    "documentsWorksheetLibraries.formulaVersion",
    "Formula Version",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "B1"),
        text("note", "Version note", "Reviewed equation"),
    ],
)
def formula_version(ctx: FeatureContext, values: dict) -> dict:
    """Snapshot the selected formula with timestamp, calculated result and engineering note."""
    sheet, state = _open(ctx, values)
    cell = state.get("cells", {}).get(values["cell"].upper(), {})
    formula = cell.get("formula")
    if formula is None:
        raise FeatureInputError("Selected cell does not contain a formula.")
    value = cell_value(values["cell"], state)
    versions = state.setdefault("formulaVersions", {}).setdefault(values["cell"].upper(), [])
    versions.append(
        {"formula": formula, "value": value, "note": values["note"], "version": len(versions) + 1}
    )
    return _save(
        ctx, sheet, state, {"cell": values["cell"], "version": len(versions), "value": value}
    )


@feature(
    "documentsWorksheetLibraries.addConstant",
    "Add Constant",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Constant name", "GAMMA_CONCRETE"),
        number("value", "Value", 24),
        text("unit", "Unit", "kN/m³"),
        text("source", "Source", "Project specification"),
    ],
)
def add_constant(ctx: FeatureContext, values: dict) -> dict:
    """Add a named engineering constant with unit and source citation."""
    sheet, state = _open(ctx, values)
    key = values["name"].strip().upper()
    if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
        raise FeatureInputError("Constant name must use letters, digits and underscores.")
    constants = state.setdefault("constants", {})
    if key in constants:
        raise FeatureInputError("That constant already exists; use Edit Constant to change it.")
    constants[key] = {
        "value": values["value"],
        "unit": values["unit"],
        "source": values["source"].strip(),
    }
    return _save(
        ctx, sheet, state, {"constant": key, "value": values["value"], "unit": values["unit"]}
    )


@feature(
    "documentsWorksheetLibraries.editConstant",
    "Edit Constant",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Constant name", "GAMMA_CONCRETE"),
        number("value", "New value", 24),
        text("unit", "Unit", "kN/m³"),
        text("source", "Source", "Updated project specification"),
    ],
)
def edit_constant(ctx: FeatureContext, values: dict) -> dict:
    """Update an existing engineering constant and retain its previous value in revision history."""
    sheet, state = _open(ctx, values)
    key = values["name"].strip().upper()
    constants = state.setdefault("constants", {})
    if key not in constants:
        raise FeatureInputError("That constant does not exist.")
    old = constants[key]
    state.setdefault("constantHistory", {}).setdefault(key, []).append(old)
    constants[key] = {
        "value": values["value"],
        "unit": values["unit"],
        "source": values["source"].strip(),
    }
    return _save(
        ctx,
        sheet,
        state,
        {"constant": key, "previousValue": old["value"], "value": values["value"]},
    )


@feature(
    "documentsWorksheetLibraries.importConstants",
    "Import Constants",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("csvPath", "Project-relative CSV", "11 Exports/constants.csv"),
    ],
)
def import_constants(ctx: FeatureContext, values: dict) -> dict:
    """Import named constants from a CSV containing name,value,unit and optional source columns."""
    root = require_root(ctx)
    path = (root / values["csvPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Constants CSV must be inside the project folder.") from exc
    rows = read_csv_rows(path)
    sheet, state = _open(ctx, values)
    constants = state.setdefault("constants", {})
    added = []
    for row in rows:
        name = row.get("name", "").strip().upper()
        try:
            value = float(row.get("value", ""))
        except ValueError as exc:
            raise FeatureInputError(
                f"Constant {name or '<unnamed>'} has a non-numeric value."
            ) from exc
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", name):
            raise FeatureInputError("Each imported constant needs a valid name.")
        constants[name] = {
            "value": value,
            "unit": row.get("unit", ""),
            "source": row.get("source", ""),
        }
        added.append(name)
    return _save(ctx, sheet, state, {"importedConstants": len(added), "names": added})


@feature(
    "documentsWorksheetLibraries.constantUnits",
    "Constant Units",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Constant name", "GAMMA_CONCRETE"),
        text("unit", "Unit label", "kN/m³"),
    ],
)
def constant_units(ctx: FeatureContext, values: dict) -> dict:
    """Change a named constant's unit annotation after confirming the constant exists."""
    sheet, state = _open(ctx, values)
    key = values["name"].strip().upper()
    constant = state.get("constants", {}).get(key)
    if constant is None:
        raise FeatureInputError("That constant does not exist.")
    constant["unit"] = values["unit"]
    return _save(
        ctx, sheet, state, {"constant": key, "value": constant["value"], "unit": values["unit"]}
    )


@feature(
    "documentsWorksheetLibraries.lookupTable",
    "Lookup Table",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Table name", "Steel grades"),
        text("csvPath", "Project-relative CSV", "11 Exports/steel-grades.csv"),
    ],
)
def lookup_table(ctx: FeatureContext, values: dict) -> dict:
    """Load a CSV lookup table into the worksheet library after validating its headings."""
    root = require_root(ctx)
    path = (root / values["csvPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Lookup CSV must be inside the project folder.") from exc
    rows = read_csv_rows(path)
    if not rows:
        raise FeatureInputError("Lookup table CSV needs a header and at least one data row.")
    sheet, state = _open(ctx, values)
    tables = state.setdefault("lookupTables", {})
    tables[values["name"]] = {
        "source": path.relative_to(root).as_posix(),
        "columns": list(rows[0]),
        "rows": rows,
    }
    return _save(
        ctx, sheet, state, {"table": values["name"], "rows": len(rows), "columns": list(rows[0])}
    )


@feature(
    "documentsWorksheetLibraries.interpolateValue",
    "Interpolate Value",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("table", "Lookup table", "Material curve"),
        text("xColumn", "Independent column", "temperature"),
        text("yColumn", "Dependent column", "strength"),
        number("x", "Interpolation point", 20),
    ],
)
def interpolate_value(ctx: FeatureContext, values: dict) -> dict:
    """Interpolate one dependent value from an ordered two-column worksheet lookup table."""
    sheet, state = _open(ctx, values)
    table = state.get("lookupTables", {}).get(values["table"])
    if not table:
        raise FeatureInputError("Choose a loaded lookup table.")
    try:
        pairs = sorted(
            (float(row[values["xColumn"]]), float(row[values["yColumn"]])) for row in table["rows"]
        )
    except (KeyError, ValueError) as exc:
        raise FeatureInputError("Lookup columns must contain numeric values.") from exc
    for (x0, y0), (x1, y1) in pairwise(pairs):
        if x0 <= values["x"] <= x1:
            y = y0 + (y1 - y0) * (values["x"] - x0) / (x1 - x0)
            state.setdefault("settings", {})["lastLookupInterpolation"] = {
                "table": values["table"],
                "x": values["x"],
                "y": y,
            }
            _save(ctx, sheet, state, {"interpolatedValue": y})
            return result(summary={"interpolatedValue": y})
    raise FeatureInputError("Interpolation point lies outside the table domain.")


@feature(
    "documentsWorksheetLibraries.applyLookup",
    "Apply Lookup",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("table", "Lookup table", "Steel grades"),
        text("keyColumn", "Key column", "grade"),
        text("key", "Lookup key", "S355"),
        text("valueColumn", "Value column", "fyMPa"),
        text("destinationCell", "Destination cell", "A1"),
    ],
)
def apply_lookup(ctx: FeatureContext, values: dict) -> dict:
    """Find an exact key in a loaded lookup table and place its selected property in a cell."""
    sheet, state = _open(ctx, values)
    table = state.get("lookupTables", {}).get(values["table"])
    if not table:
        raise FeatureInputError("Choose a loaded lookup table.")
    matches = [row for row in table["rows"] if row.get(values["keyColumn"]) == values["key"]]
    if len(matches) != 1:
        raise FeatureInputError(
            f"Lookup key matched {len(matches)} rows; exactly one match is required."
        )
    try:
        value = float(matches[0][values["valueColumn"]])
    except (KeyError, ValueError):
        value = matches[0].get(values["valueColumn"])
    ensure_cell(state, values["destinationCell"])["value"] = value
    return _save(
        ctx,
        sheet,
        state,
        {"cell": values["destinationCell"], "lookupValue": value, "key": values["key"]},
    )


@feature(
    "documentsWorksheetLibraries.validateLookup",
    "Validate Lookup",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("table", "Lookup table", "Steel grades"),
        text("keyColumn", "Unique key column", "grade"),
    ],
)
def validate_lookup(ctx: FeatureContext, values: dict) -> dict:
    """Find duplicate or blank keys in a loaded lookup table."""
    sheet, state = _open(ctx, values)
    table = state.get("lookupTables", {}).get(values["table"])
    if not table:
        raise FeatureInputError("Choose a loaded lookup table.")
    keys = [row.get(values["keyColumn"], "") for row in table["rows"]]
    duplicates = sorted({key for key in keys if key and keys.count(key) > 1})
    blank_count = sum(not key for key in keys)
    table["validation"] = {
        "valid": not duplicates and blank_count == 0,
        "duplicateKeys": duplicates,
        "blankKeys": blank_count,
    }
    return _save(
        ctx,
        sheet,
        state,
        {
            "valid": table["validation"]["valid"],
            "duplicateKeys": duplicates,
            "blankKeys": blank_count,
        },
    )


@feature(
    "documentsWorksheetLibraries.importProfile",
    "Import Profile",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("csvPath", "Project-relative section profile CSV", "11 Exports/profiles.csv"),
        text("nameColumn", "Name column", "name"),
    ],
)
def import_profile(ctx: FeatureContext, values: dict) -> dict:
    """Import engineering section profiles and require area and inertia properties for every row."""
    root = require_root(ctx)
    path = (root / values["csvPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Profile file must be inside the project folder.") from exc
    rows = read_csv_rows(path)
    required = {values["nameColumn"], "areaMm2", "ixMm4", "iyMm4"}
    if not rows or not required.issubset(rows[0]):
        raise FeatureInputError("Profile CSV needs name, areaMm2, ixMm4 and iyMm4 columns.")
    profiles = []
    for row in rows:
        try:
            profiles.append(
                {
                    "name": row[values["nameColumn"]],
                    "areaMm2": float(row["areaMm2"]),
                    "ixMm4": float(row["ixMm4"]),
                    "iyMm4": float(row["iyMm4"]),
                }
            )
        except ValueError as exc:
            raise FeatureInputError("Profile properties must be numeric.") from exc
    sheet, state = _open(ctx, values)
    state.setdefault("sectionProfiles", {}).update({row["name"]: row for row in profiles})
    return _save(
        ctx,
        sheet,
        state,
        {"importedProfiles": len(profiles), "names": [row["name"] for row in profiles]},
    )


@feature(
    "documentsWorksheetLibraries.shapeFilter",
    "Shape Filter",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("minimumArea", "Minimum area", 0, unit="mm²", min=0),
        number("minimumInertia", "Minimum major inertia", 0, unit="mm⁴", min=0),
    ],
)
def shape_filter(ctx: FeatureContext, values: dict) -> dict:
    """Filter imported section profiles by minimum gross area and major-axis inertia."""
    _sheet, state = _open(ctx, values)
    rows = [
        row
        for row in state.get("sectionProfiles", {}).values()
        if row["areaMm2"] >= values["minimumArea"]
        and max(row["ixMm4"], row["iyMm4"]) >= values["minimumInertia"]
    ]
    return result(
        summary={"matchingShapes": len(rows)},
        tables=[
            {
                "title": "Section profile matches",
                "columns": [
                    {"key": "name", "title": "Shape"},
                    {"key": "areaMm2", "title": "Area [mm²]"},
                    {"key": "ixMm4", "title": "Ix [mm⁴]"},
                    {"key": "iyMm4", "title": "Iy [mm⁴]"},
                ],
                "rows": rows,
            }
        ],
    )


@feature(
    "documentsWorksheetLibraries.propertyLookup",
    "Property Lookup",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("material", "Material id or name", "Steel"),
        text("property", "Property name", "fyMPa"),
        text("destinationCell", "Destination cell", "A1"),
    ],
)
def property_lookup(ctx: FeatureContext, values: dict) -> dict:
    """Find a property on a project material record and place it in the selected worksheet cell."""
    from saengine.features.documents_common import project_fields

    data = project_fields(ctx).get("materials") or {}
    items = data.get("materials", data if isinstance(data, list) else [])
    match = next(
        (
            item
            for item in items
            if values["material"].casefold() in str(item.get("id", item.get("name", ""))).casefold()
        ),
        None,
    )
    if not match or values["property"] not in match:
        raise FeatureInputError(
            "Material or requested property was not found in the project materials library."
        )
    sheet, state = _open(ctx, values)
    value = match[values["property"]]
    ensure_cell(state, values["destinationCell"])["value"] = value
    return _save(
        ctx,
        sheet,
        state,
        {
            "material": values["material"],
            "property": values["property"],
            "value": value,
            "cell": values["destinationCell"],
        },
    )


@feature(
    "documentsWorksheetLibraries.customShape",
    "Custom Shape",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Shape name", "RHS 200x100x8"),
        number("width", "Outer width", 100, unit="mm", min=0.001),
        number("depth", "Outer depth", 200, unit="mm", min=0.001),
        number("thickness", "Wall thickness", 8, unit="mm", min=0.001),
    ],
)
def custom_shape(ctx: FeatureContext, values: dict) -> dict:
    """Calculate and save area and principal inertias for a rectangular hollow section."""
    b, d, t = values["width"], values["depth"], values["thickness"]
    if 2 * t >= min(b, d):
        raise FeatureInputError("Wall thickness must leave a positive hollow core.")
    area = b * d - (b - 2 * t) * (d - 2 * t)
    ix = (b * d**3 - (b - 2 * t) * (d - 2 * t) ** 3) / 12
    iy = (d * b**3 - (d - 2 * t) * (b - 2 * t) ** 3) / 12
    shape = {
        "name": values["name"],
        "areaMm2": area,
        "ixMm4": ix,
        "iyMm4": iy,
        "widthMm": b,
        "depthMm": d,
        "thicknessMm": t,
    }
    sheet, state = _open(ctx, values)
    state.setdefault("sectionProfiles", {})[values["name"]] = shape
    return _save(
        ctx, sheet, state, {"shape": values["name"], "areaMm2": area, "ixMm4": ix, "iyMm4": iy}
    )


@feature(
    "documentsWorksheetLibraries.materialLibrary",
    "Material Library",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("query", "Material search", "steel"),
    ],
)
def material_library(ctx: FeatureContext, values: dict) -> dict:
    """Search materials saved in the active project and return their named properties."""
    from saengine.features.documents_common import project_fields

    data = project_fields(ctx).get("materials") or {}
    items = data.get("materials", []) if isinstance(data, dict) else data
    matches = [
        item
        for item in items
        if values["query"].casefold() in json.dumps(item, default=str).casefold()
    ]
    return result(
        summary={"materialCount": len(matches)},
        tables=[
            {
                "title": "Project material matches",
                "columns": [
                    {"key": "name", "title": "Material"},
                    {"key": "properties", "title": "Properties"},
                ],
                "rows": [
                    {"name": item.get("name", item.get("id", "")), "properties": item}
                    for item in matches
                ],
            }
        ],
    )


@feature(
    "documentsWorksheetLibraries.strengthGrade",
    "Strength Grade",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("grade", "Material grade", "S355"),
        number("thickness", "Thickness", 20, unit="mm", min=0.001),
        text("destinationCell", "Yield strength destination", "A1"),
    ],
)
def strength_grade(ctx: FeatureContext, values: dict) -> dict:
    """Look up a project's strength-grade record and select the nearest thickness band."""
    from saengine.features.documents_common import project_fields

    data = project_fields(ctx).get("materials") or {}
    items = data.get("grades", data.get("materials", [])) if isinstance(data, dict) else data
    row = next(
        (
            row
            for row in items
            if str(row.get("grade", row.get("name", ""))).casefold() == values["grade"].casefold()
        ),
        None,
    )
    if row is None:
        raise FeatureInputError("That strength grade is not in the project materials library.")
    bands = row.get("thicknessBands", [])
    band = next(
        (b for b in bands if float(b.get("maximumMm", math.inf)) >= values["thickness"]), None
    )
    strength = band.get("fyMPa") if band else row.get("fyMPa")
    if strength is None:
        raise FeatureInputError(
            "The selected grade has no yield-strength value for this thickness."
        )
    sheet, state = _open(ctx, values)
    ensure_cell(state, values["destinationCell"])["value"] = strength
    return _save(
        ctx,
        sheet,
        state,
        {
            "grade": values["grade"],
            "thicknessMm": values["thickness"],
            "yieldStrengthMPa": strength,
            "cell": values["destinationCell"],
        },
    )


@feature(
    "documentsWorksheetLibraries.thermalProperty",
    "Thermal Property",
    part="documents",
    fields=[
        number("coefficient", "Expansion coefficient", 12, unit="µm/m·°C", min=0),
        number("length", "Member length", 6, unit="m", min=0),
        number("temperatureChange", "Temperature change", 30, unit="°C"),
    ],
)
def thermal_property(ctx: FeatureContext, values: dict) -> dict:
    """Calculate free thermal expansion from the entered coefficient, length and temperature change."""
    delta = values["coefficient"] * 1e-6 * values["length"] * 1000 * values["temperatureChange"]
    return result(
        summary={
            "thermalExpansionMm": delta,
            "lengthM": values["length"],
            "temperatureChangeC": values["temperatureChange"],
        }
    )


@feature(
    "documentsWorksheetLibraries.saveSnippet",
    "Save Snippet",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Snippet name", "Beam capacity"),
        text("range", "Cell range", "A1:C5"),
        text("description", "Description", "Reusable beam check block"),
    ],
)
def save_snippet(ctx: FeatureContext, values: dict) -> dict:
    """Save the selected cell block, formulas, styles and dimensions as a reusable worksheet snippet."""
    sheet, state = _open(ctx, values)
    addresses = range_cells(values["range"])
    rows = [parse_cell(a)[0] for a in addresses]
    cols = [parse_cell(a)[1] for a in addresses]
    r0, c0, r1, c1 = min(rows), min(cols), max(rows), max(cols)
    cells = {}
    for address in addresses:
        row, col = parse_cell(address)
        cells[f"{row - r0 + 1},{col - c0 + 1}"] = state.get("cells", {}).get(address, {})
    snippets = state.setdefault("snippets", {})
    snippets[values["name"]] = {
        "description": values["description"],
        "rows": r1 - r0 + 1,
        "columns": c1 - c0 + 1,
        "cells": cells,
    }
    return _save(ctx, sheet, state, {"snippet": values["name"], "cellCount": len(addresses)})


@feature(
    "documentsWorksheetLibraries.insertSnippet",
    "Insert Snippet",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("name", "Snippet name", "Beam capacity"),
        text("startCell", "Destination origin", "F1"),
    ],
)
def insert_snippet(ctx: FeatureContext, values: dict) -> dict:
    """Insert a saved relative cell block at a destination origin, preserving formulas and formatting."""
    sheet, state = _open(ctx, values)
    snippet = state.get("snippets", {}).get(values["name"])
    if not snippet:
        raise FeatureInputError("That worksheet snippet does not exist.")
    row0, col0 = parse_cell(values["startCell"])
    for key, cell in snippet["cells"].items():
        r, c = map(int, key.split(","))
        ensure_cell(state, cell_address(row0 + r - 1, col0 + c - 1)).update(cell)
    return _save(
        ctx,
        sheet,
        state,
        {
            "snippet": values["name"],
            "insertedCells": len(snippet["cells"]),
            "startCell": values["startCell"],
        },
    )
