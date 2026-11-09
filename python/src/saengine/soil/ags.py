"""AGS4 borehole data (the UK Association of Geotechnical and Geoenvironmental Specialists'
transfer format, version 4) in and out of the soil report (alpha 9 L8).

An AGS4 file is comma separated text, every field quoted, in groups: a ``"GROUP"`` line, the
``"HEADING"``, ``"UNIT"`` and ``"TYPE"`` lines, then ``"DATA"`` lines. The groups and headings
read into 01 Soil Report:

- ``LOCA`` (locations): ``LOCA_ID`` the borehole, ``LOCA_LOCX`` / ``LOCA_LOCY`` (local grid) as
  project x/y, else ``LOCA_LAT`` / ``LOCA_LON`` (WGS 84), else ``LOCA_NATE`` / ``LOCA_NATN`` (the
  national grid) as project x/y from the first such borehole (a note says so); ``LOCA_GL``
  ground level, ``LOCA_FDEP`` termination depth, ``LOCA_STAR`` date, ``LOCA_TYPE`` method;
- ``GEOL`` (field geological descriptions): ``GEOL_TOP``, ``GEOL_BASE``, ``GEOL_DESC`` as a
  layer, its soil type from the description's principal soil (or rock) name;
- ``ISPT`` (standard penetration tests): ``ISPT_TOP`` the depth; the six 75 mm increments
  ``ISPT_INC1``-``ISPT_INC6`` as the seating drive (1 + 2) and N1 (3 + 4), N2 (5 + 6);
  ``ISPT_NVAL`` N; a test drive short of 300 mm (``ISPT_NPEN`` < 300) a refusal of
  ``ISPT_MAIN`` blows for ``ISPT_NPEN`` mm; ``ISPT_ERAT`` the energy ratio;
- ``WSTG`` / ``WSTD`` (water strikes): the shallowest strike, or the level after the
  observation (``WSTD_POST``), as the water table;
- ``SAMP`` (samples): ``SAMP_TOP``, ``SAMP_BASE``, ``SAMP_REF``, ``SAMP_TYPE`` (U, UT, P: UD;
  D, B, BLK: disturbed; C: core; SPT, SPTLS: SPT), ``SAMP_RECV``;
- laboratory groups on their sample (``LOCA_ID``, ``SAMP_TOP``, ``SAMP_REF``, ``SAMP_TYPE``,
  ``SAMP_ID``): ``LNMC_MC`` moisture; ``LLPL_LL``, ``LLPL_PL`` (NP: non-plastic) limits;
  ``LDEN_BDEN``, ``LDEN_DDEN`` densities (as unit weights); ``GRAG_FINE``, ``GRAG_CLAY``
  fines and clay fraction; ``GRAT_SIZE`` / ``GRAT_PERP`` the grading curve; ``TRIT_CU``,
  ``TRIT_CELL``, ``TRIT_DEVF`` the undrained triaxial; ``TREG_COH``, ``TREG_PHI`` the effective
  triaxial; ``SHBG_PCOH``, ``SHBG_PHI`` the shear box; ``GCHM_CODE`` / ``GCHM_RESL`` /
  ``GCHM_UNIT`` the pH, sulphate and chloride.

Every other group and heading with a value is listed as not imported. Units: the ``UNIT`` line's
(m, mm, kPa, deg, %, Mg/m3) converted to the soil report's.

:func:`write` writes the soil report's boreholes as AGS4 4.1: ``PROJ``, ``TRAN``, ``UNIT``,
``TYPE``, ``ABBR``, then the groups above that have data. The heading names follow the AGS4
data dictionary as published by the AGS; they are listed for checking in the PR.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from saengine.library.soil import SOIL_TYPES

#: g [m/s²]: densities (Mg/m³) to unit weights (kN/m³).
G = 9.80665
#: Length units to mm.
_LENGTH = {"m": 1000.0, "mm": 1.0, "cm": 10.0, "ft": 304.8, "": 1000.0}
#: The headings that tie a laboratory row to its sample.
SAMPLE_KEY = ("LOCA_ID", "SAMP_TOP", "SAMP_REF", "SAMP_TYPE", "SAMP_ID")

#: Groups and headings the import reads (the others are reported as not imported).
READ: dict[str, set[str]] = {
    "PROJ": {"PROJ_ID", "PROJ_NAME", "PROJ_LOC", "PROJ_CLNT", "PROJ_CONT", "PROJ_ENG"},
    "TRAN": {
        "TRAN_ISNO",
        "TRAN_DATE",
        "TRAN_PROD",
        "TRAN_STAT",
        "TRAN_AGS",
        "TRAN_RECV",
        "TRAN_DLIM",
        "TRAN_RCON",
        "TRAN_DESC",
        "TRAN_REM",
    },
    "UNIT": {"UNIT_UNIT", "UNIT_DESC", "UNIT_REM"},
    "TYPE": {"TYPE_TYPE", "TYPE_DESC"},
    "ABBR": {"ABBR_HDNG", "ABBR_CODE", "ABBR_DESC", "ABBR_LIST", "ABBR_REM"},
    "DICT": set(),
    "LOCA": {
        "LOCA_ID",
        "LOCA_TYPE",
        "LOCA_GL",
        "LOCA_FDEP",
        "LOCA_STAR",
        "LOCA_LOCX",
        "LOCA_LOCY",
        "LOCA_LAT",
        "LOCA_LON",
        "LOCA_NATE",
        "LOCA_NATN",
        "LOCA_STAT",
        "LOCA_GREF",
        "LOCA_REM",
    },
    "GEOL": {"LOCA_ID", "GEOL_TOP", "GEOL_BASE", "GEOL_DESC", "GEOL_LEG", "GEOL_GEOL", "GEOL_REM"},
    "ISPT": {
        "LOCA_ID",
        "ISPT_TOP",
        "ISPT_SEAT",
        "ISPT_MAIN",
        "ISPT_NPEN",
        "ISPT_NVAL",
        "ISPT_REP",
        "ISPT_ERAT",
        "ISPT_INC1",
        "ISPT_INC2",
        "ISPT_INC3",
        "ISPT_INC4",
        "ISPT_INC5",
        "ISPT_INC6",
        "ISPT_PEN1",
        "ISPT_PEN2",
        "ISPT_PEN3",
        "ISPT_PEN4",
        "ISPT_PEN5",
        "ISPT_PEN6",
        "ISPT_TYPE",
        "ISPT_REM",
    },
    "WSTG": {"LOCA_ID", "WSTG_DPTH", "WSTG_DTIM"},
    "WSTD": {"LOCA_ID", "WSTG_DPTH", "WSTD_POST", "WSTD_NMIN", "WSTG_DTIM", "WSTD_DTIM"},
    "SAMP": {*SAMPLE_KEY, "SAMP_BASE", "SAMP_RECV", "SAMP_DESC"},
    "LNMC": {*SAMPLE_KEY, "SPEC_REF", "SPEC_DPTH", "LNMC_MC"},
    "LLPL": {*SAMPLE_KEY, "SPEC_REF", "SPEC_DPTH", "LLPL_LL", "LLPL_PL", "LLPL_PI"},
    "LDEN": {*SAMPLE_KEY, "SPEC_REF", "SPEC_DPTH", "LDEN_BDEN", "LDEN_DDEN", "LDEN_MC"},
    "GRAG": {
        *SAMPLE_KEY,
        "SPEC_REF",
        "SPEC_DPTH",
        "GRAG_FINE",
        "GRAG_CLAY",
        "GRAG_SILT",
        "GRAG_SAND",
        "GRAG_GRAV",
        "GRAG_UC",
    },
    "GRAT": {*SAMPLE_KEY, "SPEC_REF", "SPEC_DPTH", "GRAT_SIZE", "GRAT_PERP", "GRAT_TYPE"},
    "TRIG": {*SAMPLE_KEY, "SPEC_REF", "SPEC_DPTH", "TRIG_TYPE", "TRIG_COND"},
    "TRIT": {
        *SAMPLE_KEY,
        "SPEC_REF",
        "SPEC_DPTH",
        "TRIT_TESN",
        "TRIT_CELL",
        "TRIT_DEVF",
        "TRIT_CU",
        "TRIT_BDEN",
    },
    "TREG": {*SAMPLE_KEY, "SPEC_REF", "SPEC_DPTH", "TREG_TYPE", "TREG_COH", "TREG_PHI"},
    "SHBG": {*SAMPLE_KEY, "SPEC_REF", "SPEC_DPTH", "SHBG_TYPE", "SHBG_PCOH", "SHBG_PHI"},
    "GCHM": {
        *SAMPLE_KEY,
        "SPEC_REF",
        "SPEC_DPTH",
        "GCHM_CODE",
        "GCHM_RESL",
        "GCHM_UNIT",
        "GCHM_METH",
        "GCHM_NAME",
        "GCHM_TTYP",
    },
}


class Group:
    """One AGS group: its headings, units, types and data rows (by heading)."""

    def __init__(self, name: str, line: int) -> None:
        self.name = name
        self.line = line
        self.headings: list[str] = []
        self.units: dict[str, str] = {}
        self.types: dict[str, str] = {}
        self.rows: list[tuple[int, dict[str, str]]] = []


def parse(text: str) -> tuple[dict[str, Group], list[str]]:
    """The groups of an AGS4 text, and the problems of its structure."""
    groups: dict[str, Group] = {}
    problems: list[str] = []
    current: Group | None = None
    reader = csv.reader(io.StringIO(text.replace("\r\n", "\n").replace("\r", "\n")))
    for number, row in enumerate(reader, start=1):
        if not row or all(not c.strip() for c in row):
            current = None
            continue
        kind = row[0].strip().upper()
        if kind == "GROUP":
            name = row[1].strip().upper() if len(row) > 1 else ""
            current = groups.setdefault(name, Group(name, number))
        elif current is None:
            problems.append(f"line {number}: '{row[0]}' outside a group")
        elif kind == "HEADING":
            current.headings = [h.strip().upper() for h in row[1:]]
        elif kind in ("UNIT", "TYPE"):
            target = current.units if kind == "UNIT" else current.types
            for heading, value in zip(current.headings, row[1:], strict=False):
                target[heading] = value.strip()
        elif kind == "DATA":
            if len(row) - 1 != len(current.headings):
                problems.append(
                    f"line {number}: {current.name} has {len(current.headings)} headings but "
                    f"{len(row) - 1} values"
                )
            current.rows.append((number, dict(zip(current.headings, row[1:], strict=False))))
        else:
            problems.append(f"line {number}: unknown descriptor '{row[0]}'")
    return groups, problems


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    value = text.strip()
    if not value:
        return None
    try:
        found = float(value)
    except ValueError:
        return None
    return found if math.isfinite(found) else None


def _length(group: Group, row: dict[str, str], heading: str) -> float | None:
    """A length heading in mm (by its unit, m when none)."""
    value = _number(row.get(heading))
    if value is None:
        return None
    unit = group.units.get(heading, "m").strip().lower()
    return value * _LENGTH.get(unit, 1000.0)


def _angle(text: str | None) -> float | None:
    """Decimal degrees, or degrees:minutes:seconds with an optional N/S/E/W."""
    if text is None or not text.strip():
        return None
    value = _number(text)
    if value is not None:
        return value
    match = re.fullmatch(r"\s*(-?\d+)[:° ](\d+)[:' ]?(\d+(?:\.\d+)?)?\"?\s*([NSEWnsew])?\s*", text)
    if not match:
        return None
    deg, minutes, seconds, hemi = match.groups()
    out = abs(float(deg)) + float(minutes) / 60 + float(seconds or 0) / 3600
    if deg.startswith("-") or (hemi and hemi.upper() in "SW"):
        out = -out
    return out


_EXTRA_WORDS = {
    "made ground": "fill",
    "topsoil": "organic",
    "peat": "organic",
    "mudstone": "rock",
    "sandstone": "rock",
    "siltstone": "rock",
    "limestone": "rock",
    "chalk": "rock",
    "granite": "rock",
    "shale": "rock",
    "basalt": "rock",
    "boulders": "gravel",
    "cobbles": "gravel",
}


def soil_type(description: str) -> str | None:
    """The soil type of a BS 5930 / EN ISO 14688 description: its principal name (in capitals
    by convention), else the importer's last soil word."""
    from saengine.soil.importer import soil_type_of

    text = description.strip()
    lower = text.lower()
    for word, kind in _EXTRA_WORDS.items():
        if word in lower and (word.upper() in text or word in ("made ground", "topsoil")):
            return kind
    capitals = " ".join(re.findall(r"\b[A-Z]{3,}\b", text))
    if capitals:
        found = soil_type_of(None, None, capitals)
        if found:
            return found
        for word, kind in _EXTRA_WORDS.items():
            if word.upper() in capitals:
                return kind
    found = soil_type_of(None, None, text)
    if found:
        return found
    for word, kind in _EXTRA_WORDS.items():
        if word in lower:
            return kind
    return None


def _sample_type(code: str) -> str:
    c = code.strip().upper()
    if c.startswith("SPT"):
        return "SPT"
    if c in ("U", "UT", "U100", "P", "TW", "PS") or c.startswith("U"):
        return "UD"
    if c in ("D", "B", "BLK", "LB", "SB", "W"):
        return "disturbed" if c != "W" else c
    if c in ("C", "CS", "CR"):
        return "core"
    return code.strip()


def read(path: str | Path) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """The boreholes of an AGS4 file in the soil report's format (mm), the problems that stop
    the import, and the notes (what was taken how, and what was not imported)."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return read_text(text, Path(path).name)


def read_text(text: str, name: str = "AGS4") -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """:func:`read` of the file's text."""
    groups, problems = parse(text)
    notes: list[str] = []
    if "LOCA" not in groups:
        return [], [f"{name}: no LOCA group (the locations)"], notes
    holes: dict[str, dict[str, Any]] = {}
    national: tuple[float, float] | None = None
    loca = groups["LOCA"]
    for number, row in loca.rows:
        hid = row.get("LOCA_ID", "").strip()
        if not hid:
            problems.append(f"{name} line {number}: LOCA without LOCA_ID")
            continue
        hole: dict[str, Any] = {"id": hid, "layers": [], "spt": [], "samples": []}
        x, y = _length(loca, row, "LOCA_LOCX"), _length(loca, row, "LOCA_LOCY")
        lat, lon = _angle(row.get("LOCA_LAT")), _angle(row.get("LOCA_LON"))
        east, north = _length(loca, row, "LOCA_NATE"), _length(loca, row, "LOCA_NATN")
        btm = re.search(r"BTM|9678", row.get("LOCA_GREF", ""), re.IGNORECASE) is not None
        if x is not None and y is not None:
            hole["x"], hole["y"] = x, y
        if lat is not None and lon is not None:
            hole["lat"], hole["lon"], hole["position"] = lat, lon, "wgs84"
        elif btm and east is not None and north is not None:
            hole["easting"], hole["northing"] = east / 1e3, north / 1e3
            hole["position"] = "btm"
        elif x is not None and y is not None:
            hole["position"] = "project"
        elif east is not None and north is not None:
            if national is None:
                national = (east, north)
                notes.append(
                    f"{name}: positions from the national grid (LOCA_NATE/LOCA_NATN), as "
                    f"project x/y from {hid}"
                )
            hole["x"], hole["y"] = east - national[0], north - national[1]
        gl = _length(loca, row, "LOCA_GL")
        if gl is not None:
            hole["groundLevel"] = gl
        depth = _length(loca, row, "LOCA_FDEP")
        if depth is not None:
            hole["depth"] = depth
        if row.get("LOCA_STAR", "").strip():
            hole["date"] = row["LOCA_STAR"].strip()[:64]
        method = re.search(r"\bmethod: ([^;]+)", row.get("LOCA_REM", ""))  # SAEngine's remark
        if method:
            hole["method"] = method.group(1).strip()[:200]
        elif row.get("LOCA_TYPE", "").strip():
            hole["method"] = row["LOCA_TYPE"].strip()[:200]
        holes[hid] = hole

    def hole_of(group: Group, number: int, row: dict[str, str]) -> dict[str, Any] | None:
        hid = row.get("LOCA_ID", "").strip()
        if hid not in holes:
            problems.append(f"{name} line {number}: {group.name} names no location '{hid}'")
            return None
        return holes[hid]

    if "GEOL" in groups:
        geol = groups["GEOL"]
        for number, row in geol.rows:
            hole = hole_of(geol, number, row)
            top, bottom = _length(geol, row, "GEOL_TOP"), _length(geol, row, "GEOL_BASE")
            if hole is None:
                continue
            if top is None or bottom is None:
                problems.append(f"{name} line {number}: GEOL needs GEOL_TOP and GEOL_BASE")
                continue
            desc = row.get("GEOL_DESC", "").strip()
            remark = row.get("GEOL_REM", "")
            # SAEngine's own remark (see to_text): "soil type clay; USCS CL".
            given = re.search(r"\bsoil type (\w+)", remark)
            kind = given.group(1) if given and given.group(1) in SOIL_TYPES else soil_type(desc)
            if kind is None:
                problems.append(
                    f"{name} line {number}: GEOL_DESC '{desc[:60]}' names no soil or rock this "
                    "import knows (clay, silt, sand, gravel, peat, made ground, rock names)"
                )
                continue
            layer: dict[str, Any] = {
                "top": top,
                "bottom": bottom,
                "description": desc,
                "soilType": kind,
            }
            uscs = re.search(r"\bUSCS ([A-Z]{2}(?:-[A-Z]{2})?)", remark)
            if uscs:
                layer["uscs"] = uscs.group(1)
            hole["layers"].append(layer)
    if "ISPT" in groups:
        ispt = groups["ISPT"]
        for number, row in ispt.rows:
            hole = hole_of(ispt, number, row)
            depth = _length(ispt, row, "ISPT_TOP")
            if hole is None:
                continue
            if depth is None:
                problems.append(f"{name} line {number}: ISPT needs ISPT_TOP")
                continue
            record = _spt(ispt, row)
            if record is None:
                problems.append(f"{name} line {number}: ISPT gives no N, increments or refusal")
                continue
            record["depth"] = depth
            hole["spt"].append(record)
    water: dict[str, float] = {}
    for gname in ("WSTG", "WSTD"):
        group = groups.get(gname)
        if group is None:
            continue
        for _number_, row in group.rows:
            hid = row.get("LOCA_ID", "").strip()
            level = _length(group, row, "WSTD_POST") if gname == "WSTD" else None
            level = level if level is not None else _length(group, row, "WSTG_DPTH")
            if hid in holes and level is not None:
                water[hid] = min(water.get(hid, level), level)
    for hid, level in water.items():
        holes[hid]["waterTable"] = level
    samples = _samples(groups, holes, problems, notes, name)
    for hid, by_key in samples.items():
        holes[hid]["samples"] = sorted(by_key.values(), key=lambda s: s["depth"])
    for hole in holes.values():
        hole["layers"].sort(key=lambda layer: layer["top"])
        hole["spt"].sort(key=lambda r: r["depth"])
    notes += not_imported(groups, name)
    return list(holes.values()), problems, notes


def _int(text: str | None) -> int | None:
    value = _number(text)
    return None if value is None else round(value)


def _spt(group: Group, row: dict[str, str]) -> dict[str, Any] | None:
    """An SPT record of an ISPT row (the 75 mm increments in pairs as 150 mm ones)."""
    record: dict[str, Any] = {}
    inc = [_int(row.get(f"ISPT_INC{i}")) for i in range(1, 7)]
    npen = _number(row.get("ISPT_NPEN"))
    if npen is not None and group.units.get("ISPT_NPEN", "mm").strip().lower() == "m":
        npen *= 1000
    main = _int(row.get("ISPT_MAIN"))
    nval = _int(row.get("ISPT_NVAL"))
    seat = _int(row.get("ISPT_SEAT"))
    remark = row.get("ISPT_REM", "")
    if inc[0] is not None and inc[1] is not None:
        record["seat"] = inc[0] + inc[1]
    elif seat is not None:
        record["seat"] = seat
    if npen is not None and 0 < npen < 300 and main is not None and main > 0:
        record["refusal"] = {"blows": main, "penetration": float(npen)}
        if inc[2] is not None and inc[3] is not None and npen > 150:
            record["N1"] = inc[2] + inc[3]
    elif all(v is not None for v in inc[2:6]):
        record["N1"] = inc[2] + inc[3]  # type: ignore[operator]
        record["N2"] = inc[4] + inc[5]  # type: ignore[operator]
    # SAEngine's own remark (see to_text): the 150 mm increments, a refusal, the sample.
    for key in ("N1", "N2"):
        match = re.search(rf"\b{key}=(\d+)", remark)
        if match and key not in record:
            record[key] = int(match.group(1))
    if re.search(r"\brefusal\b", remark, re.IGNORECASE) and "refusal" not in record:
        record["refusal"] = True
    match = re.search(r"\bsample ([^;]+)", remark)
    if match:
        record["sampleNumber"] = match.group(1).strip()[:32]
    if nval is not None:
        record["N"] = min(nval, 300)
    if "N" not in record and "N1" not in record and "refusal" not in record:
        if main is None:
            return None
        record["N"] = min(main, 300)
    increments = "N1" in record and "N2" in record and record.get("refusal") is not True
    if increments and "N" in record and record["N"] != record["N1"] + record["N2"]:
        record.pop("N1")
        record.pop("N2")
    er = _number(row.get("ISPT_ERAT"))
    if er is not None and 0 < er <= 100:
        record["energyRatio"] = er
    return record


def _sample_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row.get(h, "").strip() for h in SAMPLE_KEY)


def _samples(
    groups: dict[str, Group],
    holes: dict[str, dict[str, Any]],
    problems: list[str],
    notes: list[str],
    name: str,
) -> dict[str, dict[tuple[str, ...], dict[str, Any]]]:
    """Each borehole's samples with their laboratory values, by the sample key."""
    out: dict[str, dict[tuple[str, ...], dict[str, Any]]] = defaultdict(dict)

    def sample(group: Group, number: int, row: dict[str, str]) -> dict[str, Any] | None:
        hid = row.get("LOCA_ID", "").strip()
        if hid not in holes:
            problems.append(f"{name} line {number}: {group.name} names no location '{hid}'")
            return None
        key = _sample_key(row)
        found = out[hid].get(key)
        if found is None:
            depth = _length(group, row, "SAMP_TOP")
            if depth is None:
                depth = _length(group, row, "SPEC_DPTH")
            if depth is None:
                problems.append(f"{name} line {number}: {group.name} needs SAMP_TOP")
                return None
            found = {"depth": depth}
            ref = row.get("SAMP_REF", "").strip() or row.get("SAMP_ID", "").strip()
            if ref:
                found["number"] = ref[:32]
            if row.get("SAMP_TYPE", "").strip():
                found["type"] = _sample_type(row["SAMP_TYPE"])
            out[hid][key] = found
        return found

    def each(gname: str):
        group = groups.get(gname)
        if group is None:
            return
        for number, row in group.rows:
            found = sample(group, number, row)
            if found is not None:
                yield group, row, found

    for group, row, s in each("SAMP"):
        base = _length(group, row, "SAMP_BASE")
        if base is not None and base >= s["depth"]:
            s["depthTo"] = base
        recovery = _number(row.get("SAMP_RECV"))
        if recovery is not None and 0 <= recovery <= 100:
            s["recovery"] = recovery
    for _group, row, s in each("LNMC"):
        mc = _number(row.get("LNMC_MC"))
        if mc is not None:
            s["moisture"] = mc
    for _group, row, s in each("LLPL"):
        ll, pl = _number(row.get("LLPL_LL")), row.get("LLPL_PL", "").strip()
        if ll is not None:
            s["liquidLimit"] = ll
        if pl.upper() == "NP":
            s["nonPlastic"] = True
        elif _number(pl) is not None:
            s["plasticLimit"] = _number(pl)
    for group, row, s in each("LDEN"):
        for heading, key in (("LDEN_BDEN", "unitWeight"), ("LDEN_DDEN", "dryUnitWeight")):
            value = _density(group, row, heading)
            if value is not None:
                s[key] = value
        mc = _number(row.get("LDEN_MC"))
        if mc is not None and "moisture" not in s:
            s["moisture"] = mc
    for _group, row, s in each("GRAG"):
        fines, clay = _number(row.get("GRAG_FINE")), _number(row.get("GRAG_CLAY"))
        if fines is None:
            silt = _number(row.get("GRAG_SILT"))
            fines = None if silt is None or clay is None else silt + clay
        if fines is not None and 0 <= fines <= 100:
            s["finesContent"] = fines
        if clay is not None and 0 <= clay <= 100:
            s["clayFraction"] = clay
    for group, row, s in each("GRAT"):
        size = _number(row.get("GRAT_SIZE"))
        passing = _number(row.get("GRAT_PERP"))
        unit = group.units.get("GRAT_SIZE", "mm").strip().lower()
        if size is not None and unit in ("um", "µm", "micron"):
            size /= 1000
        if size is not None and size > 0 and passing is not None and 0 <= passing <= 100:
            s.setdefault("grainSize", {"sieves": []})["sieves"].append(
                {"size": size, "passing": passing}
            )
    cus: dict[int, list[float]] = defaultdict(list)
    for group, row, s in each("TRIT"):
        cu = _pressure(group, row, "TRIT_CU")
        if cu is not None:
            cus[id(s)].append(cu)
            s["_cu"] = cus[id(s)]
        cell, dev = _pressure(group, row, "TRIT_CELL"), _pressure(group, row, "TRIT_DEVF")
        if cell is not None and dev is not None:
            tri = s.setdefault("triaxial", {"type": "UU", "specimens": []})
            tri.setdefault("specimens", []).append({"cell": cell, "deviator": dev})
    for _group, row, s in each("TRIG"):
        kind = row.get("TRIG_TYPE", "").strip().upper()
        if kind in ("UU", "CU", "CD") and "triaxial" in s:
            s["triaxial"]["type"] = kind
    for group, row, s in each("TREG"):
        c, phi = _pressure(group, row, "TREG_COH"), _number(row.get("TREG_PHI"))
        if c is not None:
            s["c"] = c
        if phi is not None and 0 <= phi <= 50:
            s["phi"] = phi
    for group, row, s in each("SHBG"):
        c, phi = _pressure(group, row, "SHBG_PCOH"), _number(row.get("SHBG_PHI"))
        shear: dict[str, Any] = {}
        if c is not None:
            shear["c"] = c
        if phi is not None and 0 <= phi <= 50:
            shear["phi"] = phi
        if shear:
            s["directShear"] = shear
    for _group, row, s in each("GCHM"):
        code = re.sub(r"[^A-Z0-9]", "", row.get("GCHM_CODE", "").upper())
        value = _number(row.get("GCHM_RESL"))
        unit = row.get("GCHM_UNIT", "").strip().lower()
        if value is None:
            continue
        chem = s.setdefault("chemistry", {})
        if code == "PH" and 0 <= value <= 14:
            chem["pH"] = value
        elif "SO4" in code:
            chem["sulphateSoil" if unit in ("%", "%w/w", "% w/w") else "sulphateWater"] = value
        elif code in ("CL", "CHLORIDE") or code.startswith("CL"):
            chem["chlorideSoil" if unit in ("%", "%w/w", "% w/w") else "chlorideWater"] = value
    for by_key in out.values():
        for s in by_key.values():
            values = s.pop("_cu", None)
            if values:
                s["cu"] = sum(values) / len(values)
            if "chemistry" in s and not s["chemistry"]:
                s.pop("chemistry")
            if "grainSize" in s:
                s["grainSize"]["sieves"].sort(key=lambda p: -p["size"])
    if any(g in groups for g in ("GCHM",)):
        notes.append(
            f"{name}: GCHM codes read as pH, SO4 and Cl by their code and unit (% in soil, "
            "mg/l in water); check the chemistry"
        )
    return out


def _pressure(group: Group, row: dict[str, str], heading: str) -> float | None:
    value = _number(row.get(heading))
    if value is None:
        return None
    unit = group.units.get(heading, "kPa").strip().lower()
    return value * {"mpa": 1000.0, "kpa": 1.0, "kn/m2": 1.0, "pa": 0.001}.get(unit, 1.0)


def _density(group: Group, row: dict[str, str], heading: str) -> float | None:
    """A density as a unit weight [kN/m³]."""
    value = _number(row.get(heading))
    if value is None:
        return None
    unit = group.units.get(heading, "Mg/m3").strip().lower().replace("³", "3")
    if unit in ("kn/m3",):
        return value
    if unit in ("kg/m3",):
        return value * G / 1000
    return value * G  # Mg/m3, t/m3, g/cm3


def not_imported(groups: dict[str, Group], name: str) -> list[str]:
    """Notes of the groups and headings with values the import does not read."""
    out = []
    for gname, group in groups.items():
        known = READ.get(gname)
        if known is None:
            out.append(f"{name}: not imported: group {gname} ({len(group.rows)} rows)")
            continue
        if not known:
            continue
        unused = sorted(
            h
            for h in group.headings
            if h not in known and any(r.get(h, "").strip() for _, r in group.rows)
        )
        if unused:
            out.append(f"{name}: not imported from {gname}: {', '.join(unused)}")
    return out


# ─────────────────────────────── writing ───────────────────────────────


def _q(value: Any) -> str:
    text = "" if value is None else str(value)
    return '"' + text.replace('"', '""') + '"'


def _f(value: float | None, digits: int) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _group(name: str, headings: list[tuple[str, str, str]], rows: list[list[Any]]) -> list[str]:
    """The lines of a group: (heading, unit, type) and the data rows."""
    lines = [
        ",".join(_q(v) for v in ("GROUP", name)),
        ",".join(_q(v) for v in ["HEADING", *[h for h, _, _ in headings]]),
        ",".join(_q(v) for v in ["UNIT", *[u for _, u, _ in headings]]),
        ",".join(_q(v) for v in ["TYPE", *[t for _, _, t in headings]]),
    ]
    lines += [",".join(_q(v) for v in ["DATA", *row]) for row in rows]
    return lines


def _m(value_mm: float | None, digits: int = 2) -> str:
    return "" if value_mm is None else _f(value_mm / 1000, digits)


def write(report: Any, path: str | Path, producer: str = "SAEngine") -> list[str]:
    """Write the soil report's boreholes as AGS4 (4.1) to ``path``; the notes of what was not
    written."""
    text, notes = to_text(report, producer)
    Path(path).write_text(text, encoding="utf-8", newline="")
    return notes


def to_text(report: Any, producer: str = "SAEngine") -> tuple[str, list[str]]:
    """The AGS4 text of the soil report's boreholes, and notes."""
    from saengine.library.soil import SptRefusal

    notes: list[str] = []
    info = report.report
    blocks: list[list[str]] = []
    pid = (info.reportNumber or info.title or "SAENGINE")[:30]
    blocks.append(
        _group(
            "PROJ",
            [
                ("PROJ_ID", "", "ID"),
                ("PROJ_NAME", "", "X"),
                ("PROJ_LOC", "", "X"),
                ("PROJ_CLNT", "", "X"),
                ("PROJ_CONT", "", "X"),
                ("PROJ_ENG", "", "X"),
            ],
            [[pid, info.title or "", "", "", info.consultant or "", ""]],
        )
    )
    blocks.append(
        _group(
            "TRAN",
            [
                ("TRAN_ISNO", "", "X"),
                ("TRAN_DATE", "yyyy-mm-dd", "DT"),
                ("TRAN_PROD", "", "X"),
                ("TRAN_STAT", "", "X"),
                ("TRAN_DESC", "", "X"),
                ("TRAN_AGS", "", "X"),
                ("TRAN_RECV", "", "X"),
                ("TRAN_DLIM", "", "X"),
                ("TRAN_RCON", "", "X"),
            ],
            [
                [
                    "1",
                    date.today().isoformat(),
                    producer,
                    "Final",
                    "Borehole data from SAEngine",
                    "4.1",
                    "",
                    "|",
                    "+",
                ]
            ],
        )
    )
    loca, geol, ispt, samp, wstg = [], [], [], [], []
    lnmc, llpl, lden, grag, grat, trig, trit, treg, shbg = ([] for _ in range(9))
    for hole in report.boreholes:
        gl = report.ground_level(hole)
        loca.append(
            [
                hole.id,
                "",
                _m(gl),
                _m(hole.depth or hole.bottom),
                hole.date or "",
                _m(hole.x, 3),
                _m(hole.y, 3),
                "" if hole.lat is None else f"{hole.lat:.7f}",
                "" if hole.lon is None else f"{hole.lon:.7f}",
                "" if hole.easting is None else f"{hole.easting:.3f}",
                "" if hole.northing is None else f"{hole.northing:.3f}",
                "BTM (EPSG:9678)" if hole.easting is not None else "",
                f"method: {hole.method}" if hole.method else "",
            ]
        )
        for layer in hole.layers:
            remark = f"soil type {layer.soilType}" + (f"; USCS {layer.uscs}" if layer.uscs else "")
            geol.append(
                [
                    hole.id,
                    _m(layer.top),
                    _m(layer.bottom),
                    layer.description or layer.soilType.upper(),
                    remark,
                ]
            )
        for r in hole.spt:
            refusal = r.refusal if isinstance(r.refusal, SptRefusal) else None
            if refusal is not None:
                main, npen = refusal.blows, f"{refusal.penetration:g}"
            elif r.refusal is True:
                main, npen = (r.N1 or 0) + (r.N2 or 0), ""
            else:
                main, npen = (
                    (r.N1 + r.N2 if r.N1 is not None and r.N2 is not None else r.blows),
                    "300",
                )
            # SAEngine keeps the 150 mm increments, AGS4 the 75 mm ones: N1, N2, a refusal
            # without its penetration and the sample number go into ISPT_REM (read back).
            remarks = []
            if r.N1 is not None:
                remarks.append(f"N1={r.N1}")
            if r.N2 is not None:
                remarks.append(f"N2={r.N2}")
            if r.refusal is True:
                remarks.append("refusal")
            if r.sampleNumber:
                remarks.append(f"sample {r.sampleNumber}")
            ispt.append(
                [
                    hole.id,
                    _m(r.depth),
                    "" if r.seat is None else r.seat,
                    main,
                    npen,
                    r.blows,
                    _report_text(r),
                    "" if r.energyRatio is None else f"{r.energyRatio:g}",
                    *[""] * 12,
                    "; ".join(remarks),
                ]
            )
        if hole.waterTable is not None:
            wstg.append([hole.id, _m(hole.waterTable)])
        for k, s in enumerate(hole.samples):
            ref = s.number or f"S{k + 1}"
            stype = {"UD": "U", "disturbed": "D", "core": "C", "SPT": "SPT"}.get(
                s.type or "", s.type or ""
            )
            key = [hole.id, _m(s.depth), ref, stype, f"{hole.id}-{ref}"]
            samp.append(
                [
                    *key,
                    _m(s.depthTo) if s.depthTo is not None else "",
                    "" if s.recovery is None else f"{s.recovery:g}",
                ]
            )
            if s.moisture is not None:
                lnmc.append([*key, f"{s.moisture:g}"])
            if s.liquidLimit is not None or s.plasticLimit is not None or s.nonPlastic:
                pl = (
                    "NP"
                    if s.nonPlastic
                    else ("" if s.plasticLimit is None else f"{s.plasticLimit:g}")
                )
                llpl.append([*key, "" if s.liquidLimit is None else f"{s.liquidLimit:g}", pl])
            if s.unitWeight is not None or s.dryUnitWeight is not None:
                lden.append(
                    [
                        *key,
                        _f(None if s.unitWeight is None else s.unitWeight / G, 3),
                        _f(None if s.dryUnitWeight is None else s.dryUnitWeight / G, 3),
                    ]
                )
            if s.finesContent is not None or s.clayFraction is not None:
                grag.append(
                    [
                        *key,
                        "" if s.finesContent is None else f"{s.finesContent:g}",
                        "" if s.clayFraction is None else f"{s.clayFraction:g}",
                    ]
                )
            if s.grainSize is not None:
                for point in s.grainSize.sieves:
                    grat.append([*key, f"{point.size:g}", f"{point.passing:g}"])
            cu = s.cu if s.cu is not None else (s.triaxial.cu if s.triaxial else None)
            if cu is not None or (s.triaxial and s.triaxial.specimens and s.triaxial.type == "UU"):
                trig.append([*key, (s.triaxial.type if s.triaxial and s.triaxial.type else "UU")])
                specimens = s.triaxial.specimens if s.triaxial else []
                if specimens:
                    for n, sp in enumerate(specimens, start=1):
                        trit.append(
                            [
                                *key,
                                str(n),
                                f"{sp.cell:g}",
                                f"{sp.deviator:g}",
                                _f(sp.deviator / 2, 1),
                            ]
                        )
                else:
                    trit.append([*key, "1", "", "", _f(cu, 1)])
            c = (
                s.c
                if s.c is not None
                else (s.triaxial.c if s.triaxial and s.triaxial.effective else None)
            )
            phi = (
                s.phi
                if s.phi is not None
                else (s.triaxial.phi if s.triaxial and s.triaxial.effective else None)
            )
            if c is not None or phi is not None:
                treg.append(
                    [
                        *key,
                        "CU" if not s.triaxial else (s.triaxial.type or "CU"),
                        "" if c is None else f"{c:g}",
                        "" if phi is None else f"{phi:g}",
                    ]
                )
            if s.directShear is not None and (
                s.directShear.c is not None or s.directShear.phi is not None
            ):
                ds = s.directShear
                shbg.append(
                    [
                        *key,
                        "" if ds.c is None else f"{ds.c:g}",
                        "" if ds.phi is None else f"{ds.phi:g}",
                    ]
                )
            if s.chemistry is not None or s.consolidation is not None or s.permeability is not None:
                notes.append(
                    f"{hole.id} {ref}: chemistry, consolidation and permeability are not written"
                )
    key_h = [
        ("LOCA_ID", "", "ID"),
        ("SAMP_TOP", "m", "2DP"),
        ("SAMP_REF", "", "X"),
        ("SAMP_TYPE", "", "PA"),
        ("SAMP_ID", "", "ID"),
    ]
    units = {"m", "mm", "%", "kPa", "deg", "Mg/m3", "yyyy-mm-dd"}
    types = {
        "ID": "Unique identifier",
        "X": "Text",
        "PA": "Text listed in ABBR group",
        "DT": "Date time in international format",
        "0DP": "Value; 0 decimal places",
        "1DP": "Value; 1 decimal place",
        "2DP": "Value; 2 decimal places",
        "3DP": "Value; 3 decimal places",
        "MC": "Moisture content as per BS 1377",
    }
    groups: list[list[str]] = []
    groups.append(
        _group(
            "LOCA",
            [
                ("LOCA_ID", "", "ID"),
                ("LOCA_TYPE", "", "PA"),
                ("LOCA_GL", "m", "2DP"),
                ("LOCA_FDEP", "m", "2DP"),
                ("LOCA_STAR", "yyyy-mm-dd", "DT"),
                ("LOCA_LOCX", "m", "3DP"),
                ("LOCA_LOCY", "m", "3DP"),
                ("LOCA_LAT", "", "X"),
                ("LOCA_LON", "", "X"),
                ("LOCA_NATE", "m", "2DP"),
                ("LOCA_NATN", "m", "2DP"),
                ("LOCA_GREF", "", "PA"),
                ("LOCA_REM", "", "X"),
            ],
            loca,
        )
    )
    if geol:
        groups.append(
            _group(
                "GEOL",
                [
                    ("LOCA_ID", "", "ID"),
                    ("GEOL_TOP", "m", "2DP"),
                    ("GEOL_BASE", "m", "2DP"),
                    ("GEOL_DESC", "", "X"),
                    ("GEOL_REM", "", "X"),
                ],
                geol,
            )
        )
    if ispt:
        groups.append(
            _group(
                "ISPT",
                [
                    ("LOCA_ID", "", "ID"),
                    ("ISPT_TOP", "m", "2DP"),
                    ("ISPT_SEAT", "", "0DP"),
                    ("ISPT_MAIN", "", "0DP"),
                    ("ISPT_NPEN", "mm", "0DP"),
                    ("ISPT_NVAL", "", "0DP"),
                    ("ISPT_REP", "", "X"),
                    ("ISPT_ERAT", "%", "0DP"),
                    *[(f"ISPT_INC{i}", "", "0DP") for i in range(1, 7)],
                    *[(f"ISPT_PEN{i}", "mm", "0DP") for i in range(1, 7)],
                    ("ISPT_REM", "", "X"),
                ],
                ispt,
            )
        )
    if wstg:
        groups.append(_group("WSTG", [("LOCA_ID", "", "ID"), ("WSTG_DPTH", "m", "2DP")], wstg))
    if samp:
        groups.append(
            _group("SAMP", [*key_h, ("SAMP_BASE", "m", "2DP"), ("SAMP_RECV", "%", "0DP")], samp)
        )
    for name, extra, rows in (
        ("LNMC", [("LNMC_MC", "%", "MC")], lnmc),
        ("LLPL", [("LLPL_LL", "%", "0DP"), ("LLPL_PL", "%", "X")], llpl),
        ("LDEN", [("LDEN_BDEN", "Mg/m3", "3DP"), ("LDEN_DDEN", "Mg/m3", "3DP")], lden),
        ("GRAG", [("GRAG_FINE", "%", "0DP"), ("GRAG_CLAY", "%", "0DP")], grag),
        ("GRAT", [("GRAT_SIZE", "mm", "X"), ("GRAT_PERP", "%", "0DP")], grat),
        ("TRIG", [("TRIG_TYPE", "", "PA")], trig),
        (
            "TRIT",
            [
                ("TRIT_TESN", "", "X"),
                ("TRIT_CELL", "kPa", "0DP"),
                ("TRIT_DEVF", "kPa", "0DP"),
                ("TRIT_CU", "kPa", "1DP"),
            ],
            trit,
        ),
        (
            "TREG",
            [("TREG_TYPE", "", "PA"), ("TREG_COH", "kPa", "1DP"), ("TREG_PHI", "deg", "1DP")],
            treg,
        ),
        ("SHBG", [("SHBG_PCOH", "kPa", "1DP"), ("SHBG_PHI", "deg", "1DP")], shbg),
    ):
        if rows:
            groups.append(_group(name, [*key_h, *extra], rows))
    abbr = [
        ["SAMP_TYPE", c, d]
        for c, d in (
            ("U", "Undisturbed sample"),
            ("D", "Disturbed sample"),
            ("C", "Core sample"),
            ("SPT", "SPT sample"),
        )
    ]
    abbr += [
        ["TRIG_TYPE", c, d]
        for c, d in (
            ("UU", "Unconsolidated undrained"),
            ("CU", "Consolidated undrained"),
            ("CD", "Consolidated drained"),
        )
    ]
    blocks.append(
        _group(
            "UNIT",
            [("UNIT_UNIT", "", "X"), ("UNIT_DESC", "", "X")],
            [[u, _UNIT_TEXT.get(u, u)] for u in sorted(units)],
        )
    )
    blocks.append(
        _group(
            "TYPE",
            [("TYPE_TYPE", "", "X"), ("TYPE_DESC", "", "X")],
            [[t, d] for t, d in sorted(types.items())],
        )
    )
    blocks.append(
        _group(
            "ABBR", [("ABBR_HDNG", "", "X"), ("ABBR_CODE", "", "X"), ("ABBR_DESC", "", "X")], abbr
        )
    )
    blocks += groups
    text = "\r\n\r\n".join("\r\n".join(lines) for lines in blocks) + "\r\n"
    return text, sorted(set(notes))


_UNIT_TEXT = {
    "m": "metre",
    "mm": "millimetre",
    "%": "percentage",
    "kPa": "kilopascal",
    "deg": "degree (angle)",
    "Mg/m3": "megagrams per cubic metre",
    "yyyy-mm-dd": "year month day",
}


def _report_text(r: Any) -> str:
    """ISPT_REP: "N=25", or a refusal as "50/75 mm"."""
    from saengine.library.soil import SptRefusal

    if isinstance(r.refusal, SptRefusal):
        return f"{r.refusal.blows}/{r.refusal.penetration:g}"
    return f"N={r.blows}"
