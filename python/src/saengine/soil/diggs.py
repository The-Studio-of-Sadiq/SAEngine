"""DIGGS borehole data (Data Interchange for Geotechnical and Geoenvironmental Specialists, the
US GML/XML schema, version 2.6) in and out of the soil report (alpha 9 L8).

The reader goes by the elements' local names (any namespace prefix), so files of 2.5 and 2.6
read the same:

- ``Borehole`` (a sampling feature): its ``gml:name`` (else ``gml:identifier`` or its
  ``gml:id``) the borehole; ``referencePoint/PointLocation/gml:pos`` its position (latitude and
  longitude when the ``srsName`` is EPSG 4326 / 4979 / WGS 84, else project x/y), the third
  ordinate its ground level; ``totalMeasuredDepth`` its depth; ``whenConstructed`` its date;
  ``boreholePurpose`` / ``constructionMethod`` its method;
- ``Lithology`` (an observation on the borehole by ``investigationTarget``): its interval
  ``location/LinearExtent/gml:posList`` (top and bottom depth), ``lithDescription`` /
  ``classificationName`` the description, a ``classificationCode`` in a USCS code space the
  USCS group; the soil type from the group, else the description;
- ``Test`` with a ``DrivenPenetrationTest`` procedure (the SPT): its depth (the interval's top),
  the drive sets' ``blowCount`` (three 6-in / 150 mm sets: seating, N1, N2; a short last set a
  refusal), ``hammerEfficiency`` the energy ratio, an N value among the results;
- ``WaterLevel`` / ``GroundwaterObservation``: ``waterDepth`` (or the interval's top) the water
  table;
- ``Sample``: its name and interval (top and bottom), ``sampleType``.

Depths are in the unit of the borehole's linear referencing (``uom`` of its total depth, else
``ft``), lengths in the ``uom`` attribute where one is given. Every other element with content
is listed as not imported.

:func:`write` writes the soil report's boreholes as DIGGS 2.6 XML (the elements above). The
element names follow the DIGGS 2.6 schema as SAEngine knows it; the output is not validated
against the schema (listed for checking in the PR).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

DIGGS_NS = "http://diggsml.org/schemas/2.6"
GML_NS = "http://www.opengis.net/gml/3.2"
XLINK_NS = "http://www.w3.org/1999/xlink"
#: Lengths to mm.
_LENGTH = {
    "m": 1000.0,
    "mm": 1.0,
    "cm": 10.0,
    "ft": 304.8,
    "in": 25.4,
    "feet": 304.8,
    "foot": 304.8,
    "meter": 1000.0,
    "metre": 1000.0,
}
#: Elements the reader reads (local names), inside the ones it maps.
_USED = {
    "Diggs",
    "documentInformation",
    "DocumentInformation",
    "creationDate",
    "project",
    "Project",
    "name",
    "identifier",
    "samplingFeature",
    "Borehole",
    "projectRef",
    "referencePoint",
    "PointLocation",
    "pos",
    "totalMeasuredDepth",
    "whenConstructed",
    "TimeInterval",
    "start",
    "timePosition",
    "beginPosition",
    "end",
    "endPosition",
    "boreholePurpose",
    "constructionMethod",
    "observation",
    "Lithology",
    "investigationTarget",
    "location",
    "LinearExtent",
    "posList",
    "lithologyClassification",
    "LithologyClassification",
    "classificationCode",
    "classificationName",
    "lithDescription",
    "legendCode",
    "measurement",
    "Test",
    "procedure",
    "DrivenPenetrationTest",
    "driveSet",
    "DriveSet",
    "index",
    "blowCount",
    "penetration",
    "hammerEfficiency",
    "penetrationTestType",
    "outcome",
    "TestResult",
    "results",
    "ResultSet",
    "parameters",
    "PropertyParameters",
    "properties",
    "Property",
    "propertyName",
    "typeData",
    "propertyClass",
    "dataValues",
    "WaterLevel",
    "GroundwaterObservation",
    "waterDepth",
    "Sample",
    "sampleType",
    "samplingLocation",
    "description",
    "remarks",
    "centerLine",
    "linearReferencing",
    "LinearSpatialReferenceSystem",
    "lrm",
    "LinearReferencingMethod",
    "units",
    "type",
    "linearElement",
    "uom",
    "srsName",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in element if _local(c.tag) == name]


def _find(element: ET.Element, *path: str) -> ET.Element | None:
    """The first descendant along ``path`` (local names; each step any depth below)."""
    current: ET.Element | None = element
    for name in path:
        if current is None:
            return None
        current = next(
            (e for e in current.iter() if e is not current and _local(e.tag) == name), None
        )
    return current


def _text(element: ET.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _gml_id(element: ET.Element) -> str:
    for key, value in element.attrib.items():
        if _local(key) == "id":
            return value
    return ""


def _href(element: ET.Element | None) -> str:
    if element is None:
        return ""
    for key, value in element.attrib.items():
        if _local(key) == "href":
            return value.lstrip("#")
    return ""


def _uom(element: ET.Element | None, default: str) -> float:
    unit = default
    if element is not None:
        for key, value in element.attrib.items():
            if _local(key) == "uom":
                unit = value
    return _LENGTH.get(unit.strip().lower(), _LENGTH.get(default, 1.0))


def _float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _interval(element: ET.Element, scale: float) -> tuple[float | None, float | None]:
    """(top, bottom) [mm] of an element's ``location`` interval (a point: bottom None)."""
    # Not ``or``: an element without children is falsy, so a found posList would be dropped.
    pos = _find(element, "location", "posList")
    if pos is None:
        pos = _find(element, "location", "pos")
    if pos is None:
        return None, None
    values = [_float(v) for v in _text(pos).split()]
    numbers = [v for v in values if v is not None]
    if not numbers:
        return None, None
    top = numbers[0] * scale
    bottom = numbers[1] * scale if len(numbers) > 1 else None
    return top, bottom


def read(path: str | Path) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """The boreholes of a DIGGS file in the soil report's format (mm), the problems that stop
    the import, and the notes."""
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as error:
        return [], [f"{Path(path).name}: not well-formed XML: {error}"], []
    return read_tree(tree.getroot(), Path(path).name)


def read_text(text: str, name: str = "DIGGS") -> tuple[list[dict[str, Any]], list[str], list[str]]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        return [], [f"{name}: not well-formed XML: {error}"], []
    return read_tree(root, name)


def read_tree(root: ET.Element, name: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    if _local(root.tag) != "Diggs":
        problems.append(f"{name}: the root element is {_local(root.tag)}, not Diggs")
        return [], problems, notes
    from saengine.soil.importer import soil_type_of

    holes: dict[str, dict[str, Any]] = {}
    scales: dict[str, float] = {}
    used: set[int] = set()

    def mark(element: ET.Element | None) -> None:
        if element is not None:
            for e in element.iter():
                used.add(id(e))

    for bh in (e for e in root.iter() if _local(e.tag) == "Borehole"):
        gid = _gml_id(bh)
        hid = _text(_find(bh, "name")) or _text(_find(bh, "identifier")) or gid
        if not hid:
            problems.append(f"{name}: a Borehole without a name or id")
            continue
        depth_el = _find(bh, "totalMeasuredDepth")
        units = _text(_find(bh, "lrm", "units")) or "ft"
        scale = _uom(depth_el, units)
        hole: dict[str, Any] = {"id": hid[:64], "layers": [], "spt": [], "samples": []}
        point = _find(bh, "referencePoint")
        pos = _find(point, "pos") if point is not None else None
        if pos is not None:
            values = [_float(v) for v in _text(pos).split()]
            srs = ""
            for el in (pos, _find(point, "PointLocation")):
                if el is None:
                    continue
                for key, value in el.attrib.items():
                    if _local(key) == "srsName":
                        srs = value
            geographic = re.search(r"4326|4979|WGS ?84|CRS84", srs, re.IGNORECASE) is not None
            if len(values) >= 2 and values[0] is not None and values[1] is not None:
                if geographic:
                    lat, lon = values[0], values[1]
                    if re.search(r"CRS84", srs):
                        lat, lon = lon, lat
                    hole.update(lat=lat, lon=lon, position="wgs84")
                else:
                    hole.update(x=values[0] * scale, y=values[1] * scale)
            if len(values) >= 3 and values[2] is not None:
                hole["groundLevel"] = values[2] * (1000.0 if geographic else scale)
        depth = _float(_text(depth_el))
        if depth is not None:
            hole["depth"] = depth * scale
        when = _text(_find(bh, "whenConstructed", "beginPosition")) or _text(
            _find(bh, "whenConstructed", "timePosition")
        )
        if when:
            hole["date"] = when[:64]
        method = _text(_find(bh, "constructionMethod")) or _text(_find(bh, "boreholePurpose"))
        if method:
            hole["method"] = method[:200]
        mark(bh)
        holes[gid or hid] = hole
        scales[gid or hid] = scale
    by_name = {h["id"]: key for key, h in holes.items()}

    def target(element: ET.Element) -> str | None:
        ref = _href(_find(element, "investigationTarget"))
        if ref in holes:
            return ref
        if ref in by_name:
            return by_name[ref]
        return None

    for lith in (e for e in root.iter() if _local(e.tag) == "Lithology"):
        key = target(lith)
        if key is None:
            problems.append(f"{name}: a Lithology names no borehole ({_gml_id(lith)})")
            continue
        top, bottom = _interval(lith, scales[key])
        if top is None or bottom is None:
            problems.append(f"{name}: Lithology {_gml_id(lith)} has no interval")
            continue
        desc = _text(_find(lith, "lithDescription")) or _text(_find(lith, "classificationName"))
        uscs = ""
        for code in (e for e in lith.iter() if _local(e.tag) == "classificationCode"):
            space = next((v for k, v in code.attrib.items() if _local(k) == "codeSpace"), "")
            if "uscs" in space.lower() or re.fullmatch(r"[A-Z]{2}(-[A-Z]{2})?", _text(code)):
                uscs = _text(code)
        kind = soil_type_of(None, uscs or None, desc or None)
        given = re.search(r"\bsoil type (\w+)", _text(_find(lith, "remarks")))
        if given:
            kind = given.group(1)
        if kind is None:
            problems.append(
                f"{name}: Lithology at {top / 1e3:.2f} m: no soil type in '{desc[:60]}'"
            )
            continue
        layer: dict[str, Any] = {
            "top": top,
            "bottom": bottom,
            "description": desc,
            "soilType": kind,
        }
        if uscs:
            layer["uscs"] = uscs
        holes[key]["layers"].append(layer)
        mark(lith)
    for test in (e for e in root.iter() if _local(e.tag) == "Test"):
        spt = _find(test, "DrivenPenetrationTest")
        if spt is None:
            continue
        key = target(test)
        if key is None:
            problems.append(f"{name}: an SPT names no borehole ({_gml_id(test)})")
            continue
        top, _bottom = _interval(test, scales[key])
        if top is None:
            problems.append(f"{name}: SPT {_gml_id(test)} has no depth")
            continue
        record = _spt(test, spt)
        if record is None:
            problems.append(f"{name}: SPT at {top / 1e3:.2f} m gives no blow counts")
            continue
        record["depth"] = top
        holes[key]["spt"].append(record)
        mark(test)
    for obs in (
        e for e in root.iter() if _local(e.tag) in ("WaterLevel", "GroundwaterObservation")
    ):
        key = target(obs)
        if key is None:
            continue
        depth_el = _find(obs, "waterDepth")
        value = _float(_text(depth_el))
        level = (
            value * _uom(depth_el, "ft") if value is not None else _interval(obs, scales[key])[0]
        )
        if level is not None:
            current = holes[key].get("waterTable")
            holes[key]["waterTable"] = level if current is None else min(current, level)
            mark(obs)
    for sample in (e for e in root.iter() if _local(e.tag) == "Sample"):
        key = target(sample) or _href(_find(sample, "samplingFeatureRef"))
        if key not in holes:
            continue
        top, bottom = _interval(sample, scales[key])
        if top is None:
            continue
        found: dict[str, Any] = {"depth": top}
        if bottom is not None and bottom >= top:
            found["depthTo"] = bottom
        label = _text(_find(sample, "name"))
        if label:
            found["number"] = label[:32]
        kind = _text(_find(sample, "sampleType"))
        if kind:
            found["type"] = kind
        holes[key]["samples"].append(found)
        mark(sample)
    for hole in holes.values():
        hole["layers"].sort(key=lambda layer: layer["top"])
        hole["spt"].sort(key=lambda r: r["depth"])
        hole["samples"].sort(key=lambda s: s["depth"])
    skipped = Counter(
        _local(e.tag)
        for e in root.iter()
        if id(e) not in used
        and _local(e.tag) not in _USED
        and (_text(e) or any(True for _ in e.attrib))
        and not len(e)
    )
    if skipped:
        listed = ", ".join(f"{tag} ({count})" for tag, count in sorted(skipped.items()))
        notes.append(f"{name}: not imported: {listed}")
    return list(holes.values()), problems, notes


def _spt(test: ET.Element, spt: ET.Element) -> dict[str, Any] | None:
    sets = []
    for drive in (e for e in spt.iter() if _local(e.tag) == "DriveSet"):
        blows = _float(_text(_find(drive, "blowCount")))
        pen_el = _find(drive, "penetration")
        pen = _float(_text(pen_el))
        index = _float(_text(_find(drive, "index")))
        if blows is None:
            continue
        sets.append(
            (
                index if index is not None else len(sets) + 1,
                int(blows),
                None if pen is None else pen * _uom(pen_el, "in"),
            )
        )
    sets.sort()
    record: dict[str, Any] = {}
    if sets:
        record["seat"] = sets[0][1]
    if len(sets) >= 3:
        last_pen = sets[2][2]
        if last_pen is not None and last_pen < 150 - 1:
            record["refusal"] = {
                "blows": sets[1][1] + sets[2][1],
                "penetration": float((sets[1][2] or 150.0) + last_pen),
            }
        else:
            record["N1"], record["N2"] = sets[1][1], sets[2][1]
    elif len(sets) == 2:
        pen = sets[1][2]
        if pen is not None and 0 < pen < 300 - 1:
            record["refusal"] = {"blows": sets[1][1], "penetration": float(pen)}
        else:
            record["N1"] = sets[1][1]
            record["refusal"] = True
    n = None
    for prop in (e for e in test.iter() if _local(e.tag) == "propertyName"):
        if re.search(r"\bN\b|n.?value|blow ?count|spt", _text(prop), re.IGNORECASE):
            values = _text(_find(test, "dataValues")).replace(",", " ").split()
            numbers = [_float(v) for v in values]
            n = next((int(v) for v in numbers if v is not None), None)
            break
    if n is not None:
        record["N"] = min(n, 300)
    if "N" not in record and "N1" not in record and "refusal" not in record:
        return None
    if (
        "N" in record
        and "N1" in record
        and "N2" in record
        and record["N"] != record["N1"] + record["N2"]
    ):
        record.pop("N1")
        record.pop("N2")
    efficiency = _float(_text(_find(spt, "hammerEfficiency")))
    if efficiency is not None and 0 < efficiency <= 100:
        record["energyRatio"] = efficiency
    return record


# ─────────────────────────────── writing ───────────────────────────────


def _q(tag: str, ns: str = DIGGS_NS) -> str:
    return f"{{{ns}}}{tag}"


def _sub(
    parent: ET.Element, tag: str, text: Any = None, ns: str = DIGGS_NS, **attrib: str
) -> ET.Element:
    element = ET.SubElement(parent, _q(tag, ns), {k: v for k, v in attrib.items()})
    if text is not None:
        element.text = str(text)
    return element


def _gid(parent: ET.Element, tag: str, gid: str, ns: str = DIGGS_NS) -> ET.Element:
    return ET.SubElement(parent, _q(tag, ns), {_q("id", GML_NS): gid})


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)


def write(report: Any, path: str | Path, producer: str = "SAEngine") -> list[str]:
    """Write the soil report's boreholes as DIGGS 2.6 XML; the notes of what was not written."""
    text, notes = to_text(report, producer)
    Path(path).write_text(text, encoding="utf-8")
    return notes


def to_text(report: Any, producer: str = "SAEngine") -> tuple[str, list[str]]:
    """The DIGGS XML of the soil report's boreholes (depths in m), and notes."""
    from saengine.library.soil import SptRefusal

    ET.register_namespace("", DIGGS_NS)
    ET.register_namespace("gml", GML_NS)
    ET.register_namespace("xlink", XLINK_NS)
    notes: list[str] = []
    root = ET.Element(_q("Diggs"), {_q("id", GML_NS): "SAEngine_export"})
    info = _gid(_sub(root, "documentInformation"), "DocumentInformation", "DocInfo")
    _sub(info, "creationDate", date.today().isoformat())
    _sub(info, "sourceSoftware", producer)
    project = _gid(_sub(root, "project"), "Project", "Project_1")
    _sub(project, "name", report.report.title or "SAEngine project", GML_NS)
    for hole in report.boreholes:
        hid = f"Location_{_safe(hole.id)}"
        bh = _gid(_sub(root, "samplingFeature"), "Borehole", hid)
        _sub(bh, "name", hole.id, GML_NS)
        _sub(bh, "projectRef", None, **{_q("href", XLINK_NS): "#Project_1"})
        gl = report.ground_level(hole) / 1e3
        point = _gid(_sub(bh, "referencePoint"), "PointLocation", f"{hid}_point")
        if hole.lat is not None and hole.lon is not None:
            point.set("srsName", "urn:ogc:def:crs:EPSG::4979")
            _sub(point, "pos", f"{hole.lat:.7f} {hole.lon:.7f} {gl:.3f}", GML_NS)
        else:
            point.set("srsName", "#SAEngine_project_grid")
            _sub(point, "pos", f"{hole.x / 1e3:.3f} {hole.y / 1e3:.3f} {gl:.3f}", GML_NS)
        point.set("srsDimension", "3")
        lrs = _gid(_sub(bh, "linearReferencing"), "LinearSpatialReferenceSystem", f"{hid}_lrs")
        lrm = _gid(_sub(lrs, "lrm"), "LinearReferencingMethod", f"{hid}_lrm")
        _sub(lrm, "name", "chainage")
        _sub(lrm, "type", "absolute")
        _sub(lrm, "units", "m")
        _sub(bh, "totalMeasuredDepth", f"{(hole.depth or hole.bottom) / 1e3:.3f}", uom="m")
        if hole.date:
            interval = _gid(_sub(bh, "whenConstructed"), "TimeInterval", f"{hid}_time", GML_NS)
            _sub(interval, "beginPosition", hole.date, GML_NS)
        if hole.method:
            _sub(bh, "constructionMethod", hole.method)
        for k, layer in enumerate(hole.layers, start=1):
            lith = _gid(_sub(root, "observation"), "Lithology", f"{hid}_lith{k}")
            _sub(lith, "investigationTarget", None, **{_q("href", XLINK_NS): f"#{hid}"})
            extent = _gid(_sub(lith, "location"), "LinearExtent", f"{hid}_lith{k}_loc", GML_NS)
            _sub(extent, "posList", f"{layer.top / 1e3:.3f} {layer.bottom / 1e3:.3f}", GML_NS)
            cls = _gid(
                _sub(lith, "lithologyClassification"),
                "LithologyClassification",
                f"{hid}_lith{k}_cls",
            )
            if layer.uscs:
                _sub(
                    cls,
                    "classificationCode",
                    layer.uscs,
                    codeSpace="https://diggsml.org/def/codes/DIGGS/0.1/uscs.xml",
                )
            _sub(cls, "classificationName", layer.soilType.upper())
            _sub(lith, "lithDescription", layer.description or layer.soilType)
            _sub(lith, "remarks", f"soil type {layer.soilType}")
        for k, r in enumerate(hole.spt, start=1):
            test = _gid(_sub(root, "measurement"), "Test", f"{hid}_spt{k}")
            _sub(test, "investigationTarget", None, **{_q("href", XLINK_NS): f"#{hid}"})
            extent = _gid(_sub(test, "location"), "LinearExtent", f"{hid}_spt{k}_loc", GML_NS)
            bottom = r.depthTo if r.depthTo is not None else r.depth + 450
            _sub(extent, "posList", f"{r.depth / 1e3:.3f} {bottom / 1e3:.3f}", GML_NS)
            outcome = _sub(_sub(test, "outcome"), "TestResult")
            result = _sub(_sub(outcome, "results"), "ResultSet")
            props = _sub(_sub(_sub(result, "parameters"), "PropertyParameters"), "properties")
            prop = _sub(props, "Property", index="1")
            _sub(prop, "propertyName", "N value")
            _sub(prop, "typeData", "integer")
            _sub(prop, "propertyClass", "spt_n_value")
            _sub(result, "dataValues", str(r.blows), cs=",", ts=" ", decimal=".")
            proc = _gid(_sub(test, "procedure"), "DrivenPenetrationTest", f"{hid}_spt{k}_proc")
            _sub(proc, "penetrationTestType", "SPT")
            if r.energyRatio is not None:
                _sub(proc, "hammerEfficiency", f"{r.energyRatio:g}", uom="%")
            refusal = r.refusal if isinstance(r.refusal, SptRefusal) else None
            sets: list[tuple[int, float]] = []
            if r.seat is not None:
                sets.append((r.seat, 150.0))
            if refusal is not None:
                if r.N1 is not None and refusal.penetration > 150:
                    sets += [(r.N1, 150.0), (refusal.blows - r.N1, refusal.penetration - 150)]
                else:
                    sets.append((refusal.blows, refusal.penetration))
            elif r.N1 is not None and r.N2 is not None:
                sets += [(r.N1, 150.0), (r.N2, 150.0)]
            if sets and r.seat is not None:
                for index, (blows, pen) in enumerate(sets, start=1):
                    drive = _gid(_sub(proc, "driveSet"), "DriveSet", f"{hid}_spt{k}_set{index}")
                    _sub(drive, "index", index)
                    _sub(drive, "blowCount", blows)
                    _sub(drive, "penetration", f"{pen / 1000:.3f}", uom="m")
            elif r.N1 is not None or refusal is not None:
                notes.append(
                    f"{hole.id}: SPT at {r.depth / 1e3:.2f} m: increments without the "
                    "seating drive are written as N only"
                )
        if hole.waterTable is not None:
            water = _gid(_sub(root, "observation"), "WaterLevel", f"{hid}_water")
            _sub(water, "investigationTarget", None, **{_q("href", XLINK_NS): f"#{hid}"})
            _sub(water, "waterDepth", f"{hole.waterTable / 1e3:.3f}", uom="m")
        for k, s in enumerate(hole.samples, start=1):
            sample = _gid(_sub(root, "samplingFeature"), "Sample", f"{hid}_sample{k}")
            if s.number:
                _sub(sample, "name", s.number, GML_NS)
            _sub(sample, "investigationTarget", None, **{_q("href", XLINK_NS): f"#{hid}"})
            extent = _gid(_sub(sample, "location"), "LinearExtent", f"{hid}_sample{k}_loc", GML_NS)
            top = s.depth / 1e3
            text = f"{top:.3f}" + (f" {s.depthTo / 1e3:.3f}" if s.depthTo is not None else "")
            _sub(extent, "posList", text, GML_NS)
            if s.type:
                _sub(sample, "sampleType", s.type)
            if s.model_dump(
                exclude_none=True, exclude={"number", "depth", "depthTo", "type", "nonPlastic"}
            ):
                notes.append(
                    f"{hole.id}: the laboratory values of the samples are not written to DIGGS"
                )
    ET.indent(root)
    text = ET.tostring(root, encoding="unicode", xml_declaration=False)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + text + "\n", sorted(set(notes))
