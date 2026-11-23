"""Unit handling for calculation worksheet cells."""

from __future__ import annotations

import re

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    text,
)
from saengine.features.documents_common import (
    ensure_cell,
    range_cells,
    save_worksheet_workspace,
    worksheet_workspace,
)
from saengine.units import KINDS


def _open(ctx: FeatureContext, values: dict):
    return worksheet_workspace(ctx, values["worksheetId"])


def _save(ctx: FeatureContext, sheet, state, summary):
    path = save_worksheet_workspace(ctx, sheet, state)
    return result(summary={**summary, "worksheetId": sheet.id, "worksheetPath": path})


@feature(
    "documentsWorksheetUnits.assignUnitSet",
    "Assign Unit Set",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        select(
            "kind", "Quantity kind", [(name, kind.title) for name, kind in KINDS.items()], "length"
        ),
    ],
)
def assign_unit_set(ctx: FeatureContext, values: dict) -> dict:
    """Assign a registered quantity kind to cells so later calculations can check dimensions."""
    sheet, state = _open(ctx, values)
    cells = range_cells(values["range"])
    for address in cells:
        ensure_cell(state, address)["unitKind"] = values["kind"]
    return _save(ctx, sheet, state, {"assignedCells": len(cells), "unitKind": values["kind"]})


@feature(
    "documentsWorksheetUnits.mixedUnits",
    "Mixed Units",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
    ],
)
def mixed_units(ctx: FeatureContext, values: dict) -> dict:
    """Inspect a range for mixed unit kinds before it is used in a calculation."""
    _sheet, state = _open(ctx, values)
    groups = {}
    for address in range_cells(values["range"]):
        groups.setdefault(
            state.get("cells", {}).get(address, {}).get("unitKind", "unitless"), []
        ).append(address)
    return result(
        summary={"unitKindCount": len(groups), "mixed": len(groups) > 1},
        tables=[
            {
                "title": "Units in range",
                "columns": [
                    {"key": "kind", "title": "Quantity kind"},
                    {"key": "cells", "title": "Cells"},
                ],
                "rows": [{"kind": kind, "cells": addresses} for kind, addresses in groups.items()],
            }
        ],
    )


@feature(
    "documentsWorksheetUnits.displayUnits",
    "Display Units",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        text("unit", "Display unit", "ft"),
    ],
)
def display_units(ctx: FeatureContext, values: dict) -> dict:
    """Set a display unit after confirming it belongs to every cell's assigned quantity kind."""
    sheet, state = _open(ctx, values)
    cells = range_cells(values["range"])
    for address in cells:
        current = state.get("cells", {}).get(address, {}).get("unitKind")
        matches = [
            name
            for name, definition in KINDS.items()
            if values["unit"] == definition.si or values["unit"] in definition.options
        ]
        if current and current not in matches:
            raise FeatureInputError(
                f"Unit {values['unit']} is incompatible with cell {address} ({current})."
            )
        ensure_cell(state, address)["displayUnit"] = values["unit"]
    return _save(ctx, sheet, state, {"displayCells": len(cells), "unit": values["unit"]})


@feature(
    "documentsWorksheetUnits.convertUnits",
    "Convert Units",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        text("fromUnit", "From unit", "m"),
        text("toUnit", "To unit", "ft"),
    ],
)
def convert_units(ctx: FeatureContext, values: dict) -> dict:
    """Convert numeric cell values between compatible registered units and update their unit labels."""
    from saengine.units import kind_of

    source, target = kind_of(values["fromUnit"]), kind_of(values["toUnit"])
    if source is None or target is None or source[0] != target[0]:
        raise FeatureInputError(
            "Source and target units must be registered units of the same quantity."
        )
    kind = KINDS[source[0]]
    sheet, state = _open(ctx, values)
    converted = []
    for address in range_cells(values["range"]):
        cell = ensure_cell(state, address)
        if "value" not in cell:
            continue
        try:
            si_value = (float(cell["value"]) - kind.offset(values["fromUnit"])) / source[1]
            cell["value"] = si_value * target[1] + kind.offset(values["toUnit"])
        except (TypeError, ValueError) as exc:
            raise FeatureInputError(f"Cell {address} is not numeric.") from exc
        cell["unitKind"] = source[0]
        cell["displayUnit"] = values["toUnit"]
        converted.append(address)
    return _save(
        ctx,
        sheet,
        state,
        {
            "convertedCells": len(converted),
            "conversionFactor": source[1] / target[1],
            "fromUnit": values["fromUnit"],
            "toUnit": values["toUnit"],
        },
    )


@feature(
    "documentsWorksheetUnits.decimalPlaces",
    "Decimal Places",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        number("places", "Decimal places", 2, min=0, max=12),
    ],
)
def decimal_places(ctx: FeatureContext, values: dict) -> dict:
    """Set a fixed-decimal display format on selected worksheet cells."""
    sheet, state = _open(ctx, values)
    pattern = "0" + ("." + "0" * int(values["places"]) if values["places"] else "")
    for address in range_cells(values["range"]):
        ensure_cell(state, address).setdefault("style", {})["numberFormat"] = pattern
    return _save(
        ctx,
        sheet,
        state,
        {
            "formattedCells": len(range_cells(values["range"])),
            "decimalPlaces": int(values["places"]),
        },
    )


@feature(
    "documentsWorksheetUnits.significantFigures",
    "Significant Figures",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        number("figures", "Significant figures", 3, min=1, max=12),
    ],
)
def significant_figures(ctx: FeatureContext, values: dict) -> dict:
    """Save a significant-figure display rule and apply it to numeric cell values."""
    sheet, state = _open(ctx, values)
    n = int(values["figures"])
    changed = 0
    for address in range_cells(values["range"]):
        cell = ensure_cell(state, address)
        cell.setdefault("style", {})["significantFigures"] = n
        try:
            value = float(cell.get("value"))
            if value:
                cell["displayValue"] = format(value, f".{n}g")
            changed += 1
        except (TypeError, ValueError):
            pass
    return _save(ctx, sheet, state, {"numericCells": changed, "significantFigures": n})


@feature(
    "documentsWorksheetUnits.roundMode",
    "Round Mode",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        select(
            "mode",
            "Rounding mode",
            [
                ("halfEven", "Half to even"),
                ("halfUp", "Half away from zero"),
                ("floor", "Down"),
                ("ceiling", "Up"),
            ],
            "halfEven",
        ),
    ],
)
def round_mode(ctx: FeatureContext, values: dict) -> dict:
    """Set the worksheet's rounding convention for calculated display values."""
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["roundMode"] = values["mode"]
    return _save(ctx, sheet, state, {"roundingMode": values["mode"]})


@feature(
    "documentsWorksheetUnits.roundingTolerance",
    "Rounding Tolerance",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("tolerance", "Tolerance", 0.01, min=0),
        text("unit", "Tolerance unit", "mm"),
    ],
)
def rounding_tolerance(ctx: FeatureContext, values: dict) -> dict:
    """Set the smallest difference to preserve for worksheet numeric outputs."""
    if values["tolerance"] <= 0:
        raise FeatureInputError("Tolerance must be greater than zero.")
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["roundingTolerance"] = {
        "value": values["tolerance"],
        "unit": values["unit"],
    }
    return _save(ctx, sheet, state, {"tolerance": values["tolerance"], "unit": values["unit"]})


@feature(
    "documentsWorksheetUnits.convertValues",
    "Convert Values",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        number("factor", "Conversion multiplier", 1000),
        text("targetUnit", "Target unit label", "mm"),
    ],
)
def convert_values(ctx: FeatureContext, values: dict) -> dict:
    """Apply a user-specified conversion multiplier to numeric values while retaining the original in audit data."""
    sheet, state = _open(ctx, values)
    count = 0
    for address in range_cells(values["range"]):
        cell = ensure_cell(state, address)
        try:
            value = float(cell.get("value"))
        except (TypeError, ValueError):
            continue
        cell.setdefault("conversionHistory", []).append(
            {
                "fromValue": value,
                "factor": values["factor"],
                "unit": cell.get("displayUnit"),
                "toUnit": values["targetUnit"],
            }
        )
        cell["value"] = value * values["factor"]
        cell["displayUnit"] = values["targetUnit"]
        count += 1
    return _save(
        ctx,
        sheet,
        state,
        {"convertedCells": count, "factor": values["factor"], "targetUnit": values["targetUnit"]},
    )


@feature(
    "documentsWorksheetUnits.factorTable",
    "Factor Table",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        select(
            "kind", "Quantity kind", [(name, kind.title) for name, kind in KINDS.items()], "length"
        ),
    ],
)
def factor_table(ctx: FeatureContext, values: dict) -> dict:
    """Show official conversion factors for one SAEngine quantity kind."""
    kind = KINDS[values["kind"]]
    rows = [{"unit": kind.si, "factorToSI": 1.0}] + [
        {"unit": unit, "factorToSI": 1 / factor} for unit, factor in kind.us
    ]
    return result(
        summary={"quantityKind": kind.id, "unitCount": len(rows)},
        tables=[
            {
                "title": kind.title,
                "columns": [
                    {"key": "unit", "title": "Unit"},
                    {"key": "factorToSI", "title": "Factor to SI"},
                ],
                "rows": rows,
            }
        ],
    )


@feature(
    "documentsWorksheetUnits.customUnit",
    "Custom Unit",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("symbol", "Unit symbol", "kN_custom"),
        text("kind", "Quantity kind", "force"),
        number("factorToSI", "Multiplier to SI unit", 1),
        number("offsetToSI", "Offset to SI", 0),
    ],
)
def custom_unit(ctx: FeatureContext, values: dict) -> dict:
    """Register a project-scoped affine unit mapping with its base quantity kind."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_./·²³]*", values["symbol"]):
        raise FeatureInputError("Unit symbol contains unsupported characters.")
    if values["factorToSI"] == 0:
        raise FeatureInputError("Conversion factor cannot be zero.")
    if values["kind"] not in KINDS:
        raise FeatureInputError("Choose a registered quantity kind.")
    sheet, state = _open(ctx, values)
    units = state.setdefault("customUnits", {})
    units[values["symbol"]] = {
        "kind": values["kind"],
        "factorToSI": values["factorToSI"],
        "offsetToSI": values["offsetToSI"],
    }
    return _save(ctx, sheet, state, {"unit": values["symbol"], "quantityKind": values["kind"]})


@feature(
    "documentsWorksheetUnits.conversionAudit",
    "Conversion Audit",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
    ],
)
def conversion_audit(ctx: FeatureContext, values: dict) -> dict:
    """List per-cell conversions, original values, factors and target units."""
    _sheet, state = _open(ctx, values)
    rows = []
    for address in range_cells(values["range"]):
        cell = state.get("cells", {}).get(address, {})
        for entry in cell.get("conversionHistory", []):
            rows.append({"cell": address, **entry})
    return result(
        summary={"conversionCount": len(rows)},
        tables=[
            {
                "title": "Conversion audit",
                "columns": [
                    {"key": "cell", "title": "Cell"},
                    {"key": "fromValue", "title": "Original value"},
                    {"key": "factor", "title": "Factor"},
                    {"key": "toUnit", "title": "Target unit"},
                ],
                "rows": rows,
            }
        ],
    )


def _set_system(ctx: FeatureContext, values: dict, system: str) -> dict:
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["unitSystem"] = system
    return _save(ctx, sheet, state, {"unitSystem": system})


@feature(
    "documentsWorksheetUnits.siMetric",
    "SI Metric",
    part="documents",
    fields=[text("worksheetId", "Worksheet id", "calculations")],
)
def si_metric(ctx: FeatureContext, values: dict) -> dict:
    """Set worksheet display defaults to SAEngine's SI units."""
    return _set_system(ctx, values, "SI")


@feature(
    "documentsWorksheetUnits.usCustomary",
    "US Customary",
    part="documents",
    fields=[text("worksheetId", "Worksheet id", "calculations")],
)
def us_customary(ctx: FeatureContext, values: dict) -> dict:
    """Set worksheet display defaults to US customary units for supported kinds."""
    return _set_system(ctx, values, "USCustomary")


@feature(
    "documentsWorksheetUnits.projectDefault",
    "Project Default",
    part="documents",
    fields=[text("worksheetId", "Worksheet id", "calculations")],
)
def project_default(ctx: FeatureContext, values: dict) -> dict:
    """Use the units configured in project settings for worksheet display."""
    sheet, state = _open(ctx, values)
    settings = ctx.settings()
    unit_system = getattr(settings, "units", None)
    if hasattr(unit_system, "system"):
        unit_system = unit_system.system
    state.setdefault("settings", {})["unitSystem"] = "projectDefault"
    state["settings"]["projectUnitSystem"] = unit_system
    return _save(ctx, sheet, state, {"unitSystem": "projectDefault", "projectSetting": unit_system})


@feature(
    "documentsWorksheetUnits.unitSystemSwap",
    "Unit System Swap",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        select(
            "system",
            "Target system",
            [("SI", "SI metric"), ("USCustomary", "US customary")],
            "USCustomary",
        ),
    ],
)
def unit_system_swap(ctx: FeatureContext, values: dict) -> dict:
    """Convert every assigned range cell to the corresponding unit in the selected system."""
    sheet, state = _open(ctx, values)
    changed = []
    for address in range_cells(values["range"]):
        cell = ensure_cell(state, address)
        kind_id = cell.get("unitKind")
        if kind_id not in KINDS:
            continue
        kind = KINDS[kind_id]
        unit = kind.si
        if values["system"] == "USCustomary" and kind.us:
            unit = kind.us[0][0]
        old = cell.get("displayUnit", kind.si)
        try:
            source = kind.factor(old)
            target = kind.factor(unit)
            si_value = (float(cell.get("value", 0)) - kind.offset(old)) / source
            cell["value"] = si_value * target + kind.offset(unit)
        except (KeyError, TypeError, ValueError):
            raise FeatureInputError(f"Cell {address} has a value or unit that cannot be converted.")
        cell["displayUnit"] = unit
        changed.append(address)
    state.setdefault("settings", {})["unitSystem"] = values["system"]
    return _save(
        ctx, sheet, state, {"convertedCells": len(changed), "unitSystem": values["system"]}
    )


@feature(
    "documentsWorksheetUnits.unitFormatting",
    "Unit Formatting",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        checkbox("showUnit", "Show unit after value", True),
        checkbox("space", "Insert space before unit", True),
    ],
)
def unit_formatting(ctx: FeatureContext, values: dict) -> dict:
    """Configure unit suffix display for values with assigned units."""
    sheet, state = _open(ctx, values)
    for address in range_cells(values["range"]):
        ensure_cell(state, address).setdefault("style", {}).update(
            {"showUnit": values["showUnit"], "unitSpace": values["space"]}
        )
    return _save(
        ctx,
        sheet,
        state,
        {"formattedCells": len(range_cells(values["range"])), "unitSuffix": values["showUnit"]},
    )


@feature(
    "documentsWorksheetUnits.scientificNotation",
    "Scientific Notation",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        number("significantDigits", "Significant digits", 4, min=1, max=12),
    ],
)
def scientific_notation(ctx: FeatureContext, values: dict) -> dict:
    """Display numeric cells using scientific notation at the requested significant precision."""
    sheet, state = _open(ctx, values)
    digits = int(values["significantDigits"])
    count = 0
    for address in range_cells(values["range"]):
        cell = ensure_cell(state, address)
        cell.setdefault("style", {})["numberFormat"] = f"0.{('#' * (digits - 1))}E+00"
        try:
            cell["displayValue"] = f"{float(cell.get('value')):.{digits - 1}E}"
            count += 1
        except (TypeError, ValueError):
            pass
    return _save(ctx, sheet, state, {"numericCells": count, "significantDigits": digits})


@feature(
    "documentsWorksheetUnits.prefixSelector",
    "Prefix Selector",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:A10"),
        select(
            "prefix",
            "SI prefix",
            [("k", "kilo"), ("M", "mega"), ("m", "milli"), ("µ", "micro"), ("none", "None")],
            "k",
        ),
    ],
)
def prefix_selector(ctx: FeatureContext, values: dict) -> dict:
    """Set an SI display prefix and scale numeric values to the corresponding engineering magnitude."""
    factors = {"k": 1e3, "M": 1e6, "m": 1e-3, "µ": 1e-6, "none": 1}
    sheet, state = _open(ctx, values)
    count = 0
    for address in range_cells(values["range"]):
        cell = ensure_cell(state, address)
        if "value" not in cell:
            continue
        try:
            cell["displayValue"] = float(cell["value"]) / factors[values["prefix"]]
            cell["siPrefix"] = values["prefix"]
            count += 1
        except (TypeError, ValueError):
            continue
    return _save(ctx, sheet, state, {"scaledCells": count, "prefix": values["prefix"]})


@feature(
    "documentsWorksheetUnits.dimensionalAnalysis",
    "Dimensional Analysis",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("leftCell", "Left expression cell", "A1"),
        text("rightCell", "Right expression cell", "B1"),
    ],
)
def dimensional_analysis(ctx: FeatureContext, values: dict) -> dict:
    """Compare quantity kinds on two worksheet cells and report dimensional compatibility."""
    _sheet, state = _open(ctx, values)
    left = state.get("cells", {}).get(values["leftCell"].upper(), {}).get("unitKind", "unitless")
    right = state.get("cells", {}).get(values["rightCell"].upper(), {}).get("unitKind", "unitless")
    return result(summary={"leftKind": left, "rightKind": right, "compatible": left == right})


@feature(
    "documentsWorksheetUnits.unitMismatchAlert",
    "Unit Mismatch Alert",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:D10"),
    ],
)
def unit_mismatch_alert(ctx: FeatureContext, values: dict) -> dict:
    """Save a validation alert on formulas whose referenced cells contain incompatible unit kinds."""
    sheet, state = _open(ctx, values)
    alerts = []
    for address in range_cells(values["range"]):
        cell = state.get("cells", {}).get(address, {})
        if "formula" not in cell:
            continue
        refs = re.findall(r"\b[A-Z]{1,3}[1-9][0-9]*\b", cell["formula"].upper())
        kinds = {state.get("cells", {}).get(ref, {}).get("unitKind", "unitless") for ref in refs}
        if len(kinds) > 1:
            alerts.append({"cell": address, "formula": cell["formula"], "unitKinds": sorted(kinds)})
    state.setdefault("settings", {})["unitAlerts"] = alerts
    return _save(
        ctx, sheet, state, {"mismatchCount": len(alerts), "cells": [row["cell"] for row in alerts]}
    )


@feature(
    "documentsWorksheetUnits.overrideCheck",
    "Override Check",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "A1"),
        text("unitKind", "Expected quantity kind", "length"),
        text("reason", "Override reason", "Reviewed conversion"),
    ],
)
def override_check(ctx: FeatureContext, values: dict) -> dict:
    """Record a reasoned, auditable unit-kind override on a single cell."""
    if not values["reason"].strip():
        raise FeatureInputError("Enter a reason for the unit override.")
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    previous = cell.get("unitKind")
    cell["unitKind"] = values["unitKind"]
    cell.setdefault("unitOverrides", []).append(
        {"previous": previous, "new": values["unitKind"], "reason": values["reason"].strip()}
    )
    return _save(
        ctx,
        sheet,
        state,
        {
            "cell": values["cell"],
            "previousKind": previous,
            "unitKind": values["unitKind"],
            "reason": values["reason"].strip(),
        },
    )
