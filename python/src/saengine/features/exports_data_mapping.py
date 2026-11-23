"""Exports Data Mapping - translate properties, units and classifications."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
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
from saengine.features.exports_common import output_path, require_source, write_export_json


def _mapping_file(ctx: FeatureContext) -> Path:
    if ctx.root is None:
        raise FeatureInputError("Open a project to manage data mappings.")
    return output_path(ctx, "property-mapping.json", "Mappings")


def _mapping(ctx: FeatureContext) -> tuple[Path, dict[str, Any]]:
    path = _mapping_file(ctx)
    try:
        data = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"properties": {}, "units": {}, "classes": {}}
        )
    except ValueError as error:
        raise FeatureInputError("Saved mapping is not valid JSON.") from error
    if not isinstance(data, dict):
        raise FeatureInputError("Saved mapping must be a JSON object.")
    return path, data


def _save(ctx: FeatureContext, path: Path, data: dict[str, Any]) -> str:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path.relative_to(ctx.root).as_posix()


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result_map = {}
        for key, item in value.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            result_map.update(_flatten(item, child))
        return result_map
    if isinstance(value, list):
        result_map = {}
        for index, item in enumerate(value):
            result_map.update(_flatten(item, f"{prefix}[{index}]"))
        return result_map
    return {prefix: value} if prefix else {}


@feature(
    "exportsDataMapping.mapProperty",
    "Map Property",
    part="settings",
    fields=[text("source", "Source property", "Name"), text("target", "Target property", "name")],
)
def map_property(ctx: FeatureContext, values: dict) -> dict:
    """Add one source-to-target property path to the saved mapping definition."""
    source, target = values["source"].strip(), values["target"].strip()
    if not source or not target:
        raise FeatureInputError("Both source and target property names are required.")
    path, data = _mapping(ctx)
    data.setdefault("properties", {})[source] = target
    data["updatedUtc"] = datetime.now(UTC).isoformat()
    relative = _save(ctx, path, data)
    return result(
        summary={"mappedProperties": len(data["properties"]), "mappingPath": relative},
        tables=[
            table(
                "Property mappings",
                [("source", "Source"), ("target", "Target")],
                [{"source": k, "target": v} for k, v in data["properties"].items()],
            )
        ],
    )


@feature(
    "exportsDataMapping.unmappedList",
    "Unmapped List",
    part="settings",
    fields=[
        text("source", "JSON source path", "06 BIM/bim.json"),
        text("known", "Known source properties, comma separated", "id,name,kind,type"),
    ],
)
def unmapped_list(ctx: FeatureContext, values: dict) -> dict:
    """Compare flattened source keys with a known property list and the saved mapping."""
    source = require_source(ctx, values["source"])
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Cannot parse source JSON: {error}") from error
    keys = set(_flatten(raw))
    known = {item.strip() for item in values["known"].split(",") if item.strip()}
    path, data = _mapping(ctx)
    mapped = set(data.get("properties", {}))
    rows = [
        {"property": key, "known": key in known, "mapped": key in mapped}
        for key in sorted(keys)
        if key not in known and key not in mapped
    ]
    return result(
        summary={
            "unmappedPropertyCount": len(rows),
            "mappingPath": path.relative_to(ctx.root).as_posix(),
        },
        tables=[
            table(
                "Unmapped properties",
                [("property", "Property path"), ("known", "Known"), ("mapped", "Mapped")],
                rows,
            )
        ],
    )


@feature(
    "exportsDataMapping.defaultValues",
    "Default Values",
    part="settings",
    fields=[text("defaults", "Property to default value JSON", '{"status":"unspecified"}')],
)
def default_values(ctx: FeatureContext, values: dict) -> dict:
    """Validate and store defaults for absent mapped export properties."""
    try:
        defaults = json.loads(values["defaults"])
    except ValueError as error:
        raise FeatureInputError("Defaults must be valid JSON.") from error
    if not isinstance(defaults, dict):
        raise FeatureInputError("Default values must be a JSON object.")
    path, data = _mapping(ctx)
    data["defaults"] = defaults
    relative = _save(ctx, path, data)
    return result(
        summary={"defaultCount": len(defaults), "mappingPath": relative},
        tables=[
            table(
                "Fallback values",
                [("property", "Property"), ("value", "Default")],
                [
                    {"property": k, "value": json.dumps(v, ensure_ascii=False)}
                    for k, v in defaults.items()
                ],
            )
        ],
    )


@feature(
    "exportsDataMapping.saveMapping",
    "Save Mapping",
    part="settings",
    fields=[
        text("name", "Mapping name", "default"),
        checkbox("includeTimestamp", "Record save timestamp", True),
    ],
)
def save_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Snapshot the current mapping into a named readable JSON file."""
    _, data = _mapping(ctx)
    data["name"] = values["name"].strip() or "mapping"
    if values["includeTimestamp"]:
        data["savedUtc"] = datetime.now(UTC).isoformat()
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", data["name"]) + ".json"
    path = write_export_json(ctx, filename, data, "Mappings")
    return result(summary={"mappingPath": path, "propertyCount": len(data.get("properties", {}))})


@feature(
    "exportsDataMapping.sourceUnits",
    "Source Units",
    part="settings",
    fields=[text("units", "Source property to unit JSON", '{"length":"mm","elevation":"mm"}')],
)
def source_units(ctx: FeatureContext, values: dict) -> dict:
    """Save the source units associated with mapped numeric properties."""
    try:
        units = json.loads(values["units"])
    except ValueError as error:
        raise FeatureInputError("Source units must be valid JSON.") from error
    if not isinstance(units, dict) or any(not isinstance(v, str) or not v for v in units.values()):
        raise FeatureInputError("Provide a JSON object mapping property names to unit labels.")
    path, data = _mapping(ctx)
    data["sourceUnits"] = units
    return result(
        summary={"unitDefinitions": len(units), "mappingPath": _save(ctx, path, data)},
        tables=[
            table(
                "Source units",
                [("property", "Property"), ("unit", "Unit")],
                [{"property": k, "unit": v} for k, v in units.items()],
            )
        ],
    )


@feature(
    "exportsDataMapping.targetUnits",
    "Target Units",
    part="settings",
    fields=[text("units", "Target property to unit JSON", '{"length":"m","elevation":"m"}')],
)
def target_units(ctx: FeatureContext, values: dict) -> dict:
    """Save the target units requested by downstream data consumers."""
    try:
        units = json.loads(values["units"])
    except ValueError as error:
        raise FeatureInputError("Target units must be valid JSON.") from error
    if not isinstance(units, dict) or any(not isinstance(v, str) or not v for v in units.values()):
        raise FeatureInputError("Provide a JSON object mapping property names to unit labels.")
    path, data = _mapping(ctx)
    data["targetUnits"] = units
    return result(
        summary={"unitDefinitions": len(units), "mappingPath": _save(ctx, path, data)},
        tables=[
            table(
                "Target units",
                [("property", "Property"), ("unit", "Unit")],
                [{"property": k, "unit": v} for k, v in units.items()],
            )
        ],
    )


_UNIT_SCALE = {
    "m": ("length", 1.0),
    "mm": ("length", 0.001),
    "cm": ("length", 0.01),
    "ft": ("length", 0.3048),
    "in": ("length", 0.0254),
    "kg": ("mass", 1.0),
    "g": ("mass", 0.001),
    "t": ("mass", 1000.0),
    "kn": ("force", 1000.0),
    "n": ("force", 1.0),
    "kpa": ("pressure", 1000.0),
    "mpa": ("pressure", 1000000.0),
    "pa": ("pressure", 1.0),
}


@feature(
    "exportsDataMapping.unitConversion",
    "Unit Conversion",
    part="settings",
    fields=[
        number("value", "Value", 1000),
        text("sourceUnit", "Source unit", "mm"),
        text("targetUnit", "Target unit", "m"),
    ],
)
def unit_conversion(ctx: FeatureContext, values: dict) -> dict:
    """Convert between explicitly supported SI and customary length, mass, force and pressure units."""
    source, target = (
        values["sourceUnit"].strip().casefold(),
        values["targetUnit"].strip().casefold(),
    )
    if (
        source not in _UNIT_SCALE
        or target not in _UNIT_SCALE
        or _UNIT_SCALE[source][0] != _UNIT_SCALE[target][0]
    ):
        raise FeatureInputError(
            "Units must share one supported dimension: length, mass, force or pressure."
        )
    converted = float(values["value"]) * _UNIT_SCALE[source][1] / _UNIT_SCALE[target][1]
    return result(
        summary={
            "inputValue": float(values["value"]),
            "sourceUnit": source,
            "convertedValue": converted,
            "targetUnit": target,
            "dimension": _UNIT_SCALE[source][0],
        }
    )


@feature("exportsDataMapping.verifyUnits", "Verify Units", part="settings", fields=[])
def verify_units(ctx: FeatureContext, values: dict) -> dict:
    """Check saved source and target unit declarations for compatible dimensions."""
    _, data = _mapping(ctx)
    source, target = data.get("sourceUnits", {}), data.get("targetUnits", {})
    rows = []
    for name in sorted(set(source) | set(target)):
        left, right = str(source.get(name, "")).casefold(), str(target.get(name, "")).casefold()
        compatible = (
            left in _UNIT_SCALE
            and right in _UNIT_SCALE
            and _UNIT_SCALE[left][0] == _UNIT_SCALE[right][0]
        )
        rows.append(
            {"property": name, "sourceUnit": left, "targetUnit": right, "compatible": compatible}
        )
    return result(
        summary={
            "unitPairs": len(rows),
            "incompatiblePairs": sum(not row["compatible"] for row in rows),
        },
        tables=[
            table(
                "Unit compatibility",
                [
                    ("property", "Property"),
                    ("sourceUnit", "Source"),
                    ("targetUnit", "Target"),
                    ("compatible", "Compatible"),
                ],
                rows,
            )
        ],
    )


@feature(
    "exportsDataMapping.classMapping",
    "Class Mapping",
    part="settings",
    fields=[
        text(
            "classes",
            "Source class to target class JSON",
            '{"Beam":"IfcBeam","Column":"IfcColumn"}',
        )
    ],
)
def class_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Add model class translations to the project mapping definition."""
    try:
        classes = json.loads(values["classes"])
    except ValueError as error:
        raise FeatureInputError("Class mappings must be valid JSON.") from error
    if not isinstance(classes, dict) or any(not isinstance(v, str) for v in classes.values()):
        raise FeatureInputError("Class mappings must be a JSON object of strings.")
    path, data = _mapping(ctx)
    data["classes"] = {**data.get("classes", {}), **classes}
    return result(
        summary={"classCount": len(data["classes"]), "mappingPath": _save(ctx, path, data)},
        tables=[
            table(
                "Class mappings",
                [("source", "Source class"), ("target", "Target class")],
                [{"source": k, "target": v} for k, v in data["classes"].items()],
            )
        ],
    )


@feature(
    "exportsDataMapping.typeMapping",
    "Type Mapping",
    part="settings",
    fields=[text("types", "Source type to target type JSON", "{}")],
)
def type_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Store type-level translations separately from the broader class mapping."""
    try:
        types = json.loads(values["types"])
    except ValueError as error:
        raise FeatureInputError("Type mappings must be valid JSON.") from error
    if not isinstance(types, dict) or any(not isinstance(v, str) for v in types.values()):
        raise FeatureInputError("Type mappings must be a JSON object of strings.")
    path, data = _mapping(ctx)
    data["types"] = {**data.get("types", {}), **types}
    return result(
        summary={"typeCount": len(data["types"]), "mappingPath": _save(ctx, path, data)},
        tables=[
            table(
                "Type mappings",
                [("source", "Source type"), ("target", "Target type")],
                [{"source": k, "target": v} for k, v in data["types"].items()],
            )
        ],
    )


@feature(
    "exportsDataMapping.fallbackClass",
    "Fallback Class",
    part="settings",
    fields=[text("class", "Fallback target class", "IfcBuildingElementProxy")],
)
def fallback_class(ctx: FeatureContext, values: dict) -> dict:
    """Set a clearly named fallback class for source classes without explicit translations."""
    if not values["class"].strip():
        raise FeatureInputError("Enter a fallback target class.")
    path, data = _mapping(ctx)
    data["fallbackClass"] = values["class"].strip()
    return result(
        summary={"fallbackClass": data["fallbackClass"], "mappingPath": _save(ctx, path, data)}
    )


@feature(
    "exportsDataMapping.validateMapping",
    "Validate Mapping",
    part="settings",
    fields=[text("source", "JSON source file", "06 BIM/bim.json")],
)
def validate_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Check mapping targets for duplicate names and confirm source fields exist."""
    source = require_source(ctx, values["source"])
    try:
        flat = _flatten(json.loads(source.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Cannot parse source data: {error}") from error
    _, data = _mapping(ctx)
    props = data.get("properties", {})
    targets = list(props.values())
    duplicates = sorted({name for name in targets if targets.count(name) > 1})
    rows = [
        {"source": name, "exists": name in flat, "target": target} for name, target in props.items()
    ]
    return result(
        summary={
            "mappingCount": len(rows),
            "missingSources": sum(not row["exists"] for row in rows),
            "duplicateTargets": len(duplicates),
        },
        tables=[
            table(
                "Mapping validation",
                [("source", "Source"), ("exists", "Present"), ("target", "Target")],
                rows,
            ),
            table(
                "Repeated targets",
                [("target", "Target")],
                [{"target": name} for name in duplicates],
            ),
        ],
    )


@feature(
    "exportsDataMapping.loadMapping",
    "Load Mapping",
    part="settings",
    fields=[text("filename", "Saved mapping filename", "11 Exports/Mappings/default.json")],
)
def load_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Load a readable mapping JSON file and replace the current mapping after validation."""
    source = require_source(ctx, values["filename"])
    try:
        candidate = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Mapping file cannot be parsed: {error}") from error
    if not isinstance(candidate, dict) or any(
        not isinstance(candidate.get(key, {}), dict)
        for key in ("properties", "units", "classes", "types", "defaults")
    ):
        raise FeatureInputError(
            "Mapping file must be an object with object-valued mapping sections."
        )
    path = _mapping_file(ctx)
    relative = _save(ctx, path, candidate)
    return result(
        summary={
            "propertyCount": len(candidate.get("properties", {})),
            "mappingPath": relative,
        },
        notes=["The validated saved mapping is now active for subsequent exports."],
    )


@feature(
    "exportsDataMapping.exportSchema",
    "Export Schema",
    part="settings",
    fields=[text("name", "Schema name", "project-exchange")],
)
def export_schema(ctx: FeatureContext, values: dict) -> dict:
    """Write a JSON Schema describing the current mapping document structure."""
    _, data = _mapping(ctx)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": values["name"],
        "type": "object",
        "properties": {
            "properties": {"type": "object", "additionalProperties": {"type": "string"}},
            "sourceUnits": {"type": "object", "additionalProperties": {"type": "string"}},
            "targetUnits": {"type": "object", "additionalProperties": {"type": "string"}},
            "classes": {"type": "object", "additionalProperties": {"type": "string"}},
            "types": {"type": "object", "additionalProperties": {"type": "string"}},
            "defaults": {"type": "object"},
        },
    }
    path = write_export_json(ctx, "mapping-schema.json", schema, "Mappings")
    return result(
        summary={"schemaPath": path, "sections": sum(isinstance(v, dict) for v in data.values())}
    )


@feature(
    "exportsDataMapping.autoMatch",
    "Auto Match",
    part="settings",
    fields=[
        text("source", "JSON source file", "06 BIM/bim.json"),
        number("minimumLength", "Minimum shared name length", 4, min=1, max=128),
    ],
)
def auto_match(ctx: FeatureContext, values: dict) -> dict:
    """Suggest case-insensitive exact and conservative normalized-name matches without applying them."""
    source = require_source(ctx, values["source"])
    try:
        keys = set(_flatten(json.loads(source.read_text(encoding="utf-8-sig"))))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Cannot parse source JSON: {error}") from error
    target_keys = set()
    for name in keys:
        leaf = name.rsplit(".", 1)[-1].split("[")[0]
        normalized = re.sub(r"[^a-z0-9]", "", leaf.casefold())
        if len(normalized) >= int(values["minimumLength"]):
            target_keys.add((normalized, name))
    rows = [
        {
            "source": name,
            "suggestedTarget": name.rsplit(".", 1)[-1].split("[")[0],
            "confidence": "exact-name" if name in keys else "normalized",
        }
        for _, name in sorted(target_keys)
    ]
    return result(
        summary={"suggestionCount": len(rows), "applied": False},
        tables=[
            table(
                "Mapping suggestions",
                [
                    ("source", "Source"),
                    ("suggestedTarget", "Suggested target"),
                    ("confidence", "Match"),
                ],
                rows,
            )
        ],
        notes=["Suggestions require review and are not automatically added to the active mapping."],
    )


@feature(
    "exportsDataMapping.clearMapping",
    "Clear Mapping",
    part="settings",
    fields=[checkbox("confirm", "Confirm clearing every mapping section", False)],
)
def clear_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Clear active mapping contents only after explicit confirmation."""
    if not values["confirm"]:
        raise FeatureInputError("Enable confirmation to clear the active mapping.")
    path = _mapping_file(ctx)
    old = (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"properties": {}, "units": {}, "classes": {}}
    )
    relative = _save(
        ctx,
        path,
        {
            "properties": {},
            "units": {},
            "classes": {},
            "clearedUtc": datetime.now(UTC).isoformat(),
        },
    )
    return result(summary={"sectionsCleared": len(old), "mappingPath": relative})


@feature(
    "exportsDataMapping.valueExpression",
    "Value Expression",
    part="settings",
    fields=[
        text("source", "JSON source file", "06 BIM/bim.json"),
        text("property", "Property path", "elements[0].name"),
        select(
            "operation",
            "Operation",
            [
                ("trim", "Trim text"),
                ("upper", "Uppercase"),
                ("lower", "Lowercase"),
                ("prefix", "Add prefix"),
                ("suffix", "Add suffix"),
            ],
        ),
        text("argument", "Prefix or suffix", ""),
    ],
)
def value_expression(ctx: FeatureContext, values: dict) -> dict:
    """Apply a selected deterministic text transform to one source JSON property for preview."""
    source = require_source(ctx, values["source"])
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Cannot parse JSON source: {error}") from error
    path = values["property"]
    try:
        value = _flatten(data)[path]
    except KeyError as error:
        raise FeatureInputError(f"Property path was not found: {path}") from error
    raw = str(value)
    operations = {
        "trim": lambda v: v.strip(),
        "upper": lambda v: v.upper(),
        "lower": lambda v: v.lower(),
        "prefix": lambda v: values["argument"] + v,
        "suffix": lambda v: v + values["argument"],
    }
    transformed = operations[values["operation"]](raw)
    return result(
        summary={
            "property": path,
            "original": raw,
            "transformed": transformed,
            "operation": values["operation"],
        },
        notes=["Expression is preview-only; source project data is unchanged."],
    )


@feature(
    "exportsDataMapping.textFormatting",
    "Text Formatting",
    part="settings",
    fields=[
        text("text", "Text value", "Project Element Name"),
        select(
            "format",
            "Formatting",
            [
                ("snake", "snake_case"),
                ("kebab", "kebab-case"),
                ("title", "Title Case"),
                ("upper", "UPPERCASE"),
            ],
        ),
    ],
)
def text_formatting(ctx: FeatureContext, values: dict) -> dict:
    """Preview deterministic name normalization suitable for exchange-property labels."""
    value = values["text"].strip()
    if values["format"] == "snake":
        output = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    elif values["format"] == "kebab":
        output = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    elif values["format"] == "title":
        output = value.title()
    else:
        output = value.upper()
    return result(
        summary={"input": values["text"], "formatted": output, "format": values["format"]}
    )


@feature(
    "exportsDataMapping.enumMapping",
    "Enum Mapping",
    part="settings",
    fields=[
        text("property", "Property name", "status"),
        text("values", "Source to target enum JSON", '{"Draft":"PRELIMINARY","Issued":"ISSUED"}'),
    ],
)
def enum_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Store a controlled-value translation table for one property."""
    try:
        mapping = json.loads(values["values"])
    except ValueError as error:
        raise FeatureInputError("Enum translation table must be valid JSON.") from error
    if not isinstance(mapping, dict) or any(not isinstance(v, str) for v in mapping.values()):
        raise FeatureInputError("Enum translations must map source values to target strings.")
    path, data = _mapping(ctx)
    data.setdefault("enums", {})[values["property"].strip()] = mapping
    return result(
        summary={
            "property": values["property"],
            "valueCount": len(mapping),
            "mappingPath": _save(ctx, path, data),
        },
        tables=[
            table(
                "Enumeration values",
                [("source", "Source value"), ("target", "Target value")],
                [{"source": k, "target": v} for k, v in mapping.items()],
            )
        ],
    )


@feature(
    "exportsDataMapping.dryRun",
    "Dry Run",
    part="settings",
    fields=[text("source", "JSON source file", "06 BIM/bim.json")],
)
def dry_run(ctx: FeatureContext, values: dict) -> dict:
    """Apply the current property mapping in memory and report a preview without writing output."""
    source = require_source(ctx, values["source"])
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Cannot parse source JSON: {error}") from error
    flat = _flatten(raw)
    _, mapping = _mapping(ctx)
    props = mapping.get("properties", {})
    defaults = mapping.get("defaults", {})
    rows = [
        {
            "source": source_key,
            "target": target,
            "status": "mapped"
            if source_key in flat
            else "defaulted"
            if target in defaults
            else "missing",
            "value": flat.get(source_key, defaults.get(target)),
        }
        for source_key, target in props.items()
    ]
    return result(
        summary={
            "previewRows": len(rows),
            "mapped": sum(row["status"] == "mapped" for row in rows),
            "missing": sum(row["status"] == "missing" for row in rows),
            "written": False,
        },
        tables=[
            table(
                "Mapping preview",
                [
                    ("source", "Source"),
                    ("target", "Target"),
                    ("status", "Status"),
                    ("value", "Value"),
                ],
                rows,
            )
        ],
        notes=["Dry run does not write or alter project files."],
    )


@feature(
    "exportsDataMapping.schemaChecker",
    "Schema Checker",
    part="settings",
    fields=[
        text("source", "JSON source file", "06 BIM/bim.json"),
        text("required", "Required top-level keys, comma separated", "elements"),
    ],
)
def schema_checker(ctx: FeatureContext, values: dict) -> dict:
    """Check JSON syntax and required top-level property presence."""
    source = require_source(ctx, values["source"])
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"Source file is not readable JSON: {error}") from error
    required = [item.strip() for item in values["required"].split(",") if item.strip()]
    rows = [
        {"property": key, "present": isinstance(data, dict) and key in data} for key in required
    ]
    return result(
        summary={
            "jsonValid": True,
            "requiredCount": len(rows),
            "missingCount": sum(not row["present"] for row in rows),
        },
        tables=[
            table(
                "Schema checks", [("property", "Required property"), ("present", "Present")], rows
            )
        ],
    )
