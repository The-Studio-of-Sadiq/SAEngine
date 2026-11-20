"""Semantic and geometric diff of two IFC files by ``GlobalId``.

Compares elements (``IfcElement`` and ``IfcBuildingStorey``) across two IFC revisions:

- **Added**: ``GlobalId`` present only in ``after``.
- **Removed / deleted**: ``GlobalId`` present only in ``before``.
- **Changed**: ``GlobalId`` present in both where type, placement (world matrix in mm),
  geometry/shape hash (canonical representation signature), material, or property sets differ.

Returns a JSON-serializable report with ``added``, ``deleted`` (aliased ``removed``),
``changed``, ``counts``, a flat ``changes`` list compatible with
:mod:`saengine.project.diff` (each entry carries ``kind``, ``id``, ``what``, ``before``,
``after``, ``path``, ``colour``/``color``), a ``colourSummary`` for UI badges, and an ANSI
``terminalSummary``.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit

_COLOURS = {
    "added": {"colour": "green", "hex": "#22c55e", "ansi": "\033[32m"},
    "removed": {"colour": "red", "hex": "#ef4444", "ansi": "\033[31m"},
    "changed": {"colour": "amber", "hex": "#f59e0b", "ansi": "\033[33m"},
}
_ANSI_RESET = "\033[0m"


def _open_ifc(source: str | Path | bytes | ifcopenshell.file) -> ifcopenshell.file:
    if isinstance(source, ifcopenshell.file):
        return source
    if isinstance(source, bytes):
        return ifcopenshell.file.from_string(source.decode("utf-8", "replace"))
    if isinstance(source, str) and (source.lstrip().startswith("ISO-10303-21") or "\n" in source):
        return ifcopenshell.file.from_string(source)
    return ifcopenshell.open(str(source))


def _canonical_entity(value: Any, depth: int = 0) -> Any:
    """Deterministic, STEP-id-independent representation of an IFC entity or attribute value."""
    if depth > 12:
        return None
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, tuple | list):
        return [_canonical_entity(v, depth + 1) for v in value]
    if hasattr(value, "is_a"):
        kind = value.is_a()
        if kind in ("IfcGeometricRepresentationContext", "IfcGeometricRepresentationSubContext"):
            return (
                kind,
                getattr(value, "ContextType", None),
                getattr(value, "ContextIdentifier", None),
                getattr(value, "TargetView", None),
            )
        info = value.get_info(recursive=False, include_identifier=False)
        return {
            "type": kind,
            "attrs": {
                k: _canonical_entity(v, depth + 1)
                for k, v in info.items()
                if k != "type" and v is not None
            },
        }
    return str(value)


def _shape_hash(element: Any) -> str:
    """SHA-256 hash of an element's representation geometry and voids (independent of STEP ids)."""
    reps = []
    rep = getattr(element, "Representation", None)
    if rep is not None:
        for r in getattr(rep, "Representations", None) or ():
            reps.append(
                {
                    "id": getattr(r, "RepresentationIdentifier", None),
                    "type": getattr(r, "RepresentationType", None),
                    "items": [_canonical_entity(item) for item in (r.Items or ())],
                }
            )
    openings = []
    for rel in getattr(element, "HasOpenings", None) or ():
        opening = getattr(rel, "RelatedOpeningElement", None)
        if opening is not None:
            openings.append(
                {
                    "placement": _placement_matrix(
                        opening,
                        ifcopenshell.util.unit.calculate_unit_scale(element.wrapped_data.file)
                        if hasattr(element, "wrapped_data")
                        else 0.001,
                    ),
                    "rep": _canonical_entity(getattr(opening, "Representation", None)),
                }
            )
    payload = json.dumps({"reps": reps, "openings": openings}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _placement_matrix(element: Any, scale_to_m: float) -> list[list[float]] | None:
    placement = getattr(element, "ObjectPlacement", None)
    if placement is None:
        return None
    try:
        mat = ifcopenshell.util.placement.get_local_placement(placement)
    except Exception:  # noqa: BLE001
        return None
    rows: list[list[float]] = []
    mm_factor = scale_to_m * 1000.0
    for i in range(4):
        row = []
        for j in range(4):
            val = float(mat[i][j])
            if i < 3 and j == 3:
                val = round(val * mm_factor, 3)
            else:
                val = round(val, 6)
            row.append(0.0 if val == 0.0 else val)
        rows.append(row)
    return rows


def _material_name(element: Any) -> str | None:
    try:
        mat = ifcopenshell.util.element.get_material(element)
    except Exception:  # noqa: BLE001
        return None
    if mat is None:
        return None
    return getattr(mat, "Name", None) or getattr(mat, "LayerSetName", None) or mat.is_a()


def _key_properties(element: Any) -> dict[str, Any]:
    try:
        psets = ifcopenshell.util.element.get_psets(element)
    except Exception:  # noqa: BLE001
        psets = {}
    cleaned: dict[str, Any] = {}
    for pset_name, props in sorted(psets.items()):
        if not isinstance(props, dict):
            continue
        sub = {k: v for k, v in sorted(props.items()) if k != "id"}
        if sub:
            cleaned[pset_name] = sub
    return cleaned


def _snapshot(ifc: ifcopenshell.file) -> dict[str, dict[str, Any]]:
    scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
    elements: list[Any] = list(ifc.by_type("IfcElement")) + list(ifc.by_type("IfcBuildingStorey"))
    snap: dict[str, dict[str, Any]] = {}
    for elem in elements:
        gid = getattr(elem, "GlobalId", None)
        if not gid:
            continue
        snap[gid] = {
            "globalId": gid,
            "ifcClass": elem.is_a(),
            "name": elem.Name or "",
            "tag": getattr(elem, "Tag", None),
            "objectType": getattr(elem, "ObjectType", None),
            "predefinedType": getattr(elem, "PredefinedType", None),
            "description": getattr(elem, "Description", None),
            "elevation": (
                round(float(elem.Elevation) * scale * 1000.0, 3)
                if elem.is_a("IfcBuildingStorey") and elem.Elevation is not None
                else None
            ),
            "material": _material_name(elem),
            "placement": _placement_matrix(elem, scale),
            "shapeHash": _shape_hash(elem),
            "properties": _key_properties(elem),
        }
    return snap


def _label(rec: dict[str, Any]) -> str:
    cls = rec["ifcClass"]
    name = rec["name"] or rec["tag"] or rec["globalId"]
    return f"{cls} {name}".strip()


def _origin(placement: list[list[float]] | None) -> tuple[float, float, float] | None:
    if not placement:
        return None
    return (placement[0][3], placement[1][3], placement[2][3])


def _describe_changes(old: dict[str, Any], new: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return ``(changed_fields, descriptions)`` between two snapshots of the same GlobalId."""
    fields: list[str] = []
    notes: list[str] = []
    if (old["ifcClass"], old["objectType"], old["predefinedType"]) != (
        new["ifcClass"],
        new["objectType"],
        new["predefinedType"],
    ):
        fields.append("type")
        b_type = old["objectType"] or old["ifcClass"]
        a_type = new["objectType"] or new["ifcClass"]
        notes.append(f"type {b_type} → {a_type}")
    if old["placement"] != new["placement"]:
        fields.append("placement")
        o1, o2 = _origin(old["placement"]), _origin(new["placement"])
        if o1 and o2:
            d = tuple(round(b - a, 3) for a, b in zip(o1, o2, strict=True))
            if any(abs(v) > 1e-3 for v in d):
                dist = math.sqrt(sum(v * v for v in d))
                notes.append(f"moved {dist:g} mm Δ=({d[0]:g}, {d[1]:g}, {d[2]:g})")
            else:
                notes.append("rotated")
        else:
            notes.append("placement changed")
    if old["shapeHash"] != new["shapeHash"]:
        fields.append("geometry")
        notes.append("geometry changed")
    if old["material"] != new["material"]:
        fields.append("material")
        notes.append(f"material {old['material'] or '(none)'} → {new['material'] or '(none)'}")
    if old["elevation"] != new["elevation"]:
        fields.append("elevation")
        notes.append(f"elevation {old['elevation']} → {new['elevation']} mm")
    if old["properties"] != new["properties"] or old["description"] != new["description"]:
        fields.append("properties")
        notes.append("properties changed")
    if old["name"] != new["name"] or old["tag"] != new["tag"]:
        fields.append("name")
        notes.append(f"name {old['name']!r} → {new['name']!r}")
    return fields, notes


def diff_ifc(
    before: str | Path | bytes | ifcopenshell.file,
    after: str | Path | bytes | ifcopenshell.file,
    *,
    file: str | None = None,
) -> dict[str, Any]:
    """Compare two IFC models by ``GlobalId`` and return a JSON report + colour-coded summary."""
    ifc_a = _open_ifc(before)
    ifc_b = _open_ifc(after)
    snap_a = _snapshot(ifc_a)
    snap_b = _snapshot(ifc_b)

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    unchanged = 0

    for gid, rec_b in snap_b.items():
        if gid not in snap_a:
            what = f"{_label(rec_b)} added"
            entry = {
                "globalId": gid,
                "ifcClass": rec_b["ifcClass"],
                "name": rec_b["name"],
                "objectType": rec_b["objectType"],
                "what": what,
                "colour": _COLOURS["added"]["colour"],
                "hex": _COLOURS["added"]["hex"],
            }
            added.append(entry)
            c: dict[str, Any] = {
                "kind": "added",
                "id": gid,
                "what": what,
                "before": None,
                "after": rec_b,
                "path": f"ifc[{gid}]",
                "colour": _COLOURS["added"]["colour"],
                "color": _COLOURS["added"]["hex"],
            }
            if file:
                c["file"] = file
            changes.append(c)
            continue

        rec_a = snap_a[gid]
        fields, notes = _describe_changes(rec_a, rec_b)
        if not fields:
            unchanged += 1
            continue

        what = f"{_label(rec_b)}: {'; '.join(notes)}"
        entry = {
            "globalId": gid,
            "ifcClass": rec_b["ifcClass"],
            "name": rec_b["name"],
            "fields": fields,
            "what": what,
            "before": {
                "objectType": rec_a["objectType"],
                "placement": rec_a["placement"],
                "shapeHash": rec_a["shapeHash"],
                "material": rec_a["material"],
                "properties": rec_a["properties"],
            },
            "after": {
                "objectType": rec_b["objectType"],
                "placement": rec_b["placement"],
                "shapeHash": rec_b["shapeHash"],
                "material": rec_b["material"],
                "properties": rec_b["properties"],
            },
            "colour": _COLOURS["changed"]["colour"],
            "hex": _COLOURS["changed"]["hex"],
        }
        changed.append(entry)
        c = {
            "kind": "changed",
            "id": gid,
            "what": what,
            "before": entry["before"],
            "after": entry["after"],
            "path": f"ifc[{gid}]",
            "fields": fields,
            "colour": _COLOURS["changed"]["colour"],
            "color": _COLOURS["changed"]["hex"],
        }
        if file:
            c["file"] = file
        changes.append(c)

    for gid, rec_a in snap_a.items():
        if gid not in snap_b:
            what = f"{_label(rec_a)} removed"
            entry = {
                "globalId": gid,
                "ifcClass": rec_a["ifcClass"],
                "name": rec_a["name"],
                "objectType": rec_a["objectType"],
                "what": what,
                "colour": _COLOURS["removed"]["colour"],
                "hex": _COLOURS["removed"]["hex"],
            }
            removed.append(entry)
            c = {
                "kind": "removed",
                "id": gid,
                "what": what,
                "before": rec_a,
                "after": None,
                "path": f"ifc[{gid}]",
                "colour": _COLOURS["removed"]["colour"],
                "color": _COLOURS["removed"]["hex"],
            }
            if file:
                c["file"] = file
            changes.append(c)

    counts = {
        "added": len(added),
        "deleted": len(removed),
        "removed": len(removed),
        "changed": len(changed),
        "unchanged": unchanged,
    }
    if not changes:
        summary = "No changes"
    else:
        bits = []
        if added:
            bits.append(f"{len(added)} added")
        if removed:
            bits.append(f"{len(removed)} deleted")
        if changed:
            bits.append(f"{len(changed)} changed")
        summary = ", ".join(bits)

    colour_summary = [
        {
            "kind": "added",
            "colour": _COLOURS["added"]["colour"],
            "hex": _COLOURS["added"]["hex"],
            "count": len(added),
            "label": f"+ {len(added)} added",
        },
        {
            "kind": "removed",
            "colour": _COLOURS["removed"]["colour"],
            "hex": _COLOURS["removed"]["hex"],
            "count": len(removed),
            "label": f"- {len(removed)} deleted",
        },
        {
            "kind": "changed",
            "colour": _COLOURS["changed"]["colour"],
            "hex": _COLOURS["changed"]["hex"],
            "count": len(changed),
            "label": f"~ {len(changed)} changed",
        },
    ]

    ansi_lines = [summary]
    for kind_key, items in (("added", added), ("removed", removed), ("changed", changed)):
        prefix = {"added": "+", "removed": "-", "changed": "~"}[kind_key]
        ansi = _COLOURS[kind_key]["ansi"]
        for item in items:
            ansi_lines.append(f"{ansi}{prefix} {item['what']}{_ANSI_RESET}")

    return {
        "schema": "saengine.ifcDiff/1",
        "before": {"schema": ifc_a.schema, "elements": len(snap_a)},
        "after": {"schema": ifc_b.schema, "elements": len(snap_b)},
        "counts": counts,
        "added": added,
        "deleted": removed,
        "removed": removed,
        "changed": changed,
        "changes": changes,
        "summary": summary,
        "colourSummary": colour_summary,
        "terminalSummary": "\n".join(ansi_lines),
    }


__all__ = ["diff_ifc"]
