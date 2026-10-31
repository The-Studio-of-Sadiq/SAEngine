"""Import of ETABS models from their text export (``.e2k``, File → Export → ETABS .e2k).

The e2k file is a list of ``$ SECTION`` blocks of keyword lines with quoted names and
``KEY value`` pairs, all in the units of its ``$ CONTROLS`` line (``UNITS "KN" "M" "C"``). This
reads the blocks a frame-and-shell building needs and hands them to
:class:`~saengine.importers.common.ProjectBuilder`:

- ``$ STORIES - IN SEQUENCE FROM TOP``: story heights (and the base elevation) → stories;
- ``$ GRIDS``: cartesian grid lines (``DIR "X"``: a line at x = COORD) → grid lines;
- ``$ MATERIAL PROPERTIES``: type, weight per volume, E, ν, α, f'c, fy, fu → materials;
- ``$ FRAME SECTIONS`` and ``$ CONCRETE SECTIONS``: rectangular and circular concrete (with
  their column bars, as sizes and counts or as a pattern and the area of a bar), I, channel,
  angle, tee, box and pipe steel, general sections as the rectangle of the same area and
  inertia → profiles; library shapes (named only, ``FILE`` on the first of each library) through
  the section lookup;
- ``$ SHELL PROPERTIES`` (and the older slab, deck and wall properties): thickness → slab and
  wall types;
- ``$ POINT COORDINATES``, ``$ LINE CONNECTIVITIES``, ``$ AREA CONNECTIVITIES`` with the
  ``$ LINE ASSIGNS`` and ``$ AREA ASSIGNS`` that place them on stories → columns, beams, braces,
  floors, wall panels and openings; end releases (steel beams and braces pinned at both ends get
  a simple connection) and property modifiers (BNBC's cracked factors → SAEngine's cracked
  sections); offsets, insertion points and pier labels are reported;
- ``$ POINT ASSIGNS``: restraints → supports (point springs are reported; no supports at all is
  an error of the report);
- ``$ LOAD PATTERNS`` (or the older ``$ STATIC LOADS``), ``$ LOAD CASES``, ``$ LOAD
  COMBINATIONS``: combinations on SAEngine's cases (Dead and Superimposed Dead → D, Live → L,
  Roof Live → Lr, Other named as a fluid → F, Wind → WX/WY, Seismic → EX/EY by the X or Y in
  their names; response-spectrum
  cases → EX/EY by their ACCEL U1/U2 directions); terms by LOAD / CASE (older files) or
  LOADCASE / LOADCOMBO (ETABS 2013+);
- ``$ SHELL OBJECT LOADS`` / ``$ AREA OBJECT LOADS`` (and uniform load sets): uniform gravity
  pressures on the floors → the floor and roof area loads, per slab; ``$ FRAME OBJECT LOADS``
  (uniform, trapezoidal as its mean, point) and ``$ POINT OBJECT LOADS`` (forces) → the member
  loads of ``05 Floor Plan/loads.json`` on the beams and columns (see
  :mod:`saengine.importers.common`; the rest reported with their totals);
- ``$ MASS SOURCE`` and the auto seismic definitions: reported where SAEngine differs.

Conventions of the format this follows (from its published structure; checked on the synthetic
files of the tests): a line's or area's points are at the story of its assign, less the number of
stories given after them (a column ``"1" "1" 1`` runs from the story below up to the story; for a
brace the first point is the lower one); point coordinates are plan x, y, and a third number puts
the point that far below the story it is used at; a ``DIR "GRAV"`` load is positive down.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.importers.common import (
    ImportedProject,
    ImportReport,
    ProjectBuilder,
    Units,
    bar_diameter,
)

#: A profile (SAEngine profile JSON, mm) for a section name of a steel database (W14X90, HE200B,
#: ISMB300, ...), for sections the file names without their dimensions.
#: name -> profile JSON, or (profile JSON, the approximation made or None), or None.
SectionLookup = Callable[[str], dict[str, Any] | tuple[dict[str, Any], str | None] | None]

_TOKEN = re.compile(r'"([^"]*)"|(\S+)')
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9_]*$")


@dataclass
class _Tok:
    text: str
    quoted: bool


def _tokens(line: str) -> list[_Tok]:
    return [
        _Tok(m.group(1), True) if m.group(1) is not None else _Tok(m.group(2), False)
        for m in _TOKEN.finditer(line)
    ]


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _pairs(tokens: list[_Tok]) -> dict[str, str]:
    """``KEY value`` pairs: a bare word followed by its value."""
    result: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if not t.quoted and _KEY.match(t.text) and i + 1 < len(tokens):
            result[t.text.upper()] = tokens[i + 1].text
            i += 2
        else:
            i += 1
    return result


def _num(pairs: dict[str, str], *keys: str) -> float | None:
    for key in keys:
        if key in pairs:
            value = _number(pairs[key])
            if value is not None:
                return value
    return None


@dataclass
class E2k:
    """The raw content of an e2k file, in its own units."""

    program: str = "ETABS"
    version: str | None = None
    units: Units = field(default_factory=lambda: Units("KN", "M"))
    units_given: bool = False
    temperature: str = "C"
    title: str | None = None
    stories: list[dict[str, str]] = field(default_factory=list)  # top first, with "NAME"
    grids: list[dict[str, str]] = field(default_factory=list)
    grid_systems: dict[str, dict[str, str]] = field(default_factory=dict)
    materials: dict[str, dict[str, str]] = field(default_factory=dict)
    frame_sections: dict[str, dict[str, str]] = field(default_factory=dict)
    concrete_sections: dict[str, dict[str, str]] = field(default_factory=dict)
    shell_props: dict[str, dict[str, str]] = field(default_factory=dict)
    points: dict[str, tuple[float, float, float | None]] = field(default_factory=dict)
    lines: dict[str, tuple[str, str, str, int]] = field(default_factory=dict)
    areas: dict[str, tuple[str, list[str], list[int]]] = field(default_factory=dict)
    point_assigns: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    line_assigns: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    area_assigns: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    patterns: dict[str, dict[str, str]] = field(default_factory=dict)
    old_cases: dict[str, dict[str, str]] = field(default_factory=dict)
    cases: dict[str, dict[str, Any]] = field(default_factory=dict)
    load_sets: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    point_loads: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    line_loads: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    area_loads: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)
    combos: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Auto seismic definitions: name -> pairs with "TYPE" (UBC 97, User Coefficient, ...).
    seismic: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Mass sources: name -> pairs, with "LOADS" [(pattern, factor)].
    mass_sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    unread: dict[str, int] = field(default_factory=lambda: defaultdict(int))


#: Keys that name a term of a load combination.
_COMBO_TERM_KEYS = ("LOADCASE", "LOADCOMBO", "LOAD", "CASE", "COMBO", "LOADPAT")

#: Blocks read only for what they contain, not needed for the model (reported as not read when
#: they have lines).
_IGNORED_BLOCKS = (
    "DIAPHRAGM",
    "PIER",
    "SPANDREL",
    "GROUP",
    "FUNCTION",
    "SPRING",
    "LINK",
    "PANEL ZONE",
    "TENDON",
    "DESIGN",
    "PREFERENCES",
    "ANALYSIS OPTIONS",
    "MASS SOURCE",
    "DIMENSION",
    "LOG",
    "AUTO SELECT",
    "STEEL DESIGN",
    "CONCRETE DESIGN",
    "COMPOSITE",
    "WALL DESIGN",
    "PROJECT INFORMATION",
    "SECTION CUTS",
    "GENERALIZED DISPLACEMENTS",
    "NAMED",
)


#: Keywords of definitions SAEngine makes itself (lateral load parameters, design and
#: analysis preferences), covered by the report's notes on the patterns.
_QUIET = {
    "SEISMIC",
    "WIND",
    "AUTOSEISMIC",
    "AUTOWIND",
    "PREFERENCE",
    "RLLF",
    "TITLE1",
    "TITLE2",
    "DIAPHRAGM",
    "MASSSOURCE",
}


def parse(text: str) -> E2k:
    """The blocks of an e2k file."""
    e = E2k()
    block = ""
    library = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("$"):
            block = line[1:].strip().upper()
            continue
        tokens = _tokens(line)
        if not tokens:
            continue
        keyword = tokens[0].text.upper()
        rest = tokens[1:]
        name = rest[0].text if rest else ""
        pairs = _pairs(rest[1:]) if rest else {}
        if keyword == "PROGRAM":
            e.program = name or e.program
            e.version = pairs.get("VERSION")
        elif keyword == "UNITS" and len(rest) >= 2:
            try:
                e.units = Units.parse(rest[0].text, rest[1].text)
                e.units_given = True
                if len(rest) >= 3:
                    e.temperature = rest[2].text.upper()
            except ValueError:
                pass
        elif keyword in ("TITLE1", "TITLE2") and name and e.title is None:
            e.title = name
        elif keyword == "STORY":
            existing = next((s for s in e.stories if s["NAME"] == name), None)
            if existing is None:
                e.stories.append({"NAME": name, **pairs})
            else:
                existing.update(pairs)
        elif keyword == "GRIDSYSTEM":
            e.grid_systems.setdefault(name, {}).update(pairs)
        elif keyword == "GRID":
            e.grids.append({"SYSTEM": name, **pairs})
        elif keyword == "MATERIAL":
            e.materials.setdefault(name, {}).update(pairs)
        elif keyword == "FRAMESECTION":
            section = e.frame_sections.setdefault(name, {})
            section.update(pairs)
            # ETABS names the shape library (FILE "AISC14") on the first section from it only.
            if "FILE" in pairs:
                library = pairs["FILE"]
            elif library and "SHAPE" in pairs and not any(k in pairs for k in ("D", "T3")):
                section.setdefault("FILE", library)
        elif keyword == "CONCRETESECTION":
            e.concrete_sections.setdefault(name, {}).update(pairs)
        elif keyword == "SHELLPROP":
            e.shell_props.setdefault(name, {}).update(pairs)
        elif keyword in ("SLAB", "DECK", "WALL") and "PROPERT" in block:
            props = e.shell_props.setdefault(name, {})
            props.setdefault("PROPTYPE", "Wall" if keyword == "WALL" else keyword.title())
            props.update(pairs)
        elif keyword == "POINT" and len(rest) >= 3:
            x, y = _number(rest[1].text), _number(rest[2].text)
            dz = _number(rest[3].text) if len(rest) >= 4 else None
            if x is not None and y is not None:
                e.points[name] = (x, y, dz)
        elif keyword == "LINE" and len(rest) >= 4:
            n = _number(rest[4].text) if len(rest) >= 5 else 0
            e.lines[name] = (rest[1].text.upper(), rest[2].text, rest[3].text, int(n or 0))
        elif keyword == "AREA" and len(rest) >= 3:
            count = int(_number(rest[2].text) or 0)
            labels = [t.text for t in rest[3 : 3 + count]]
            offsets = [int(_number(t.text) or 0) for t in rest[3 + count : 3 + 2 * count]]
            offsets += [0] * (count - len(offsets))
            e.areas[name] = (rest[1].text.upper(), labels, offsets)
        elif keyword in ("POINTASSIGN", "LINEASSIGN", "AREAASSIGN") and len(rest) >= 2:
            entry = (name, rest[1].text, _pairs(rest[2:]))
            {
                "POINTASSIGN": e.point_assigns,
                "LINEASSIGN": e.line_assigns,
                "AREAASSIGN": e.area_assigns,
            }[keyword].append(entry)
        elif keyword == "LOADPATTERN":
            e.patterns.setdefault(name, {}).update(pairs)
        elif keyword == "LOADCASE":
            case = e.cases.setdefault(name, {"pairs": {}, "loads": []})
            if "LOADPAT" in pairs:
                case["loads"].append((pairs["LOADPAT"], _num(pairs, "SF") or 1.0))
            elif "ACCEL" in pairs:  # response spectrum: ACCEL "U1" FUNC "..." SF 9.81
                case.setdefault("accel", []).append(
                    (pairs["ACCEL"].upper(), abs(_num(pairs, "SF") or 1.0))
                )
            else:
                case["pairs"].update(pairs)
                e.old_cases.setdefault(name, {}).update(pairs)
        elif keyword == "SHELLUNIFORMLOADSET":
            value = _num(pairs, "VALUE", "FVAL")
            if "LOADPAT" in pairs and value is not None:
                e.load_sets.setdefault(name, []).append((pairs["LOADPAT"], value))
        elif keyword == "POINTLOAD" and len(rest) >= 2:
            e.point_loads.append((name, rest[1].text, _pairs(rest[2:])))
        elif keyword == "LINELOAD" and len(rest) >= 2:
            e.line_loads.append((name, rest[1].text, _pairs(rest[2:])))
        elif keyword in ("AREALOAD", "SHELLLOAD") and len(rest) >= 2:
            e.area_loads.append((name, rest[1].text, _pairs(rest[2:])))
        elif keyword == "COMBO":
            combo = e.combos.setdefault(name, {"pairs": {}, "loads": []})
            # A term names its load case, pattern or nested combination under one of several
            # keys (LOAD / CASE in older files, LOADCASE / LOADCOMBO in ETABS 2013+), or under
            # whatever key comes just before SF.
            load = next((pairs[k] for k in _COMBO_TERM_KEYS if k in pairs), None)
            if load is None and "SF" in pairs:
                keys = list(pairs)
                at = keys.index("SF")
                if at > 0 and keys[at - 1] != "TYPE":
                    load = pairs[keys[at - 1]]
            if load is not None:
                combo["loads"].append((load, _num(pairs, "SF") or 1.0))
            else:
                combo["pairs"].update(pairs)
        elif keyword == "SEISMIC" and len(rest) >= 2:
            e.seismic[name] = {"TYPE": rest[1].text, **_pairs(rest[2:])}
        elif keyword == "MASSSOURCE":
            e.mass_sources.setdefault(name, {"LOADS": []}).update(pairs)
        elif keyword == "MASSSOURCELOAD" and len(rest) >= 3:
            factor = _number(rest[2].text)
            if factor is not None:
                source = e.mass_sources.setdefault(name, {"LOADS": []})
                source["LOADS"].append((rest[1].text, factor))
        elif keyword not in _QUIET:
            e.unread[block or keyword] += 1
    return e


# ─────────────────────────────────────── load patterns ───────────────────────────────────────


def _axis(name: str) -> tuple[str, bool]:
    """The direction X or Y of a lateral pattern from its name; True when it is a guess."""
    letters = re.sub(r"[^A-Z]", "", name.upper())
    has_x, has_y = "X" in letters, "Y" in letters
    if has_y and not has_x:
        return "Y", False
    return "X", not (has_x and not has_y)


def _is_spectrum(pairs: dict[str, str]) -> bool:
    kind = re.sub(r"[^A-Z]", "", pairs.get("TYPE", "").upper())
    return kind in ("RESPONSESPECTRUM", "RESPSPEC", "LINEARRESPONSESPECTRUM", "SPECTRUM")


#: Prefix of the pseudo patterns that stand for SAEngine's EX / EY in place of a response
#: spectrum term of a combination.
_SPECTRUM = "\0spectrum:"


def _spectrum_terms(name: str, case: dict[str, Any], report: ImportReport) -> dict[str, float]:
    """A response-spectrum case as SAEngine's earthquake cases EX / EY with their weights.

    The horizontal directions of its ``ACCEL`` lines (U1 → EX, U2 → EY) are weighted by their
    scale factors relative to the largest one (so a 100 % / 30 % case gives EX 1.0, EY 0.3); a
    case without them takes its direction from the X or Y in its name.
    """
    accel = {d: sf for d, sf in case.get("accel", []) if d in ("U1", "U2")}
    if accel:
        top = max(accel.values()) or 1.0
        return {
            _SPECTRUM + ("EX" if d == "U1" else "EY"): sf / top for d, sf in accel.items() if sf
        }
    axis, guessed = _axis(name)
    if guessed:
        report.approximate(f"response-spectrum case without a direction taken as E{axis}", name)
    return {_SPECTRUM + "E" + axis: 1.0}


#: Names of "Other" patterns that hold fluid loads (SAEngine's F case): F, F1, FL, Fluid, Water,
#: Liquid, Tank, ... The other "Other" patterns (ETABS's template patterns A, B, C, ...) say
#: nothing SAEngine can place.
_FLUID = re.compile(r"^(?:F|FL)(?:\d*|[\s_.-].*)$|^(?:FLUID|WATER|LIQUID|TANK)", re.IGNORECASE)


def _pattern_case(name: str, pairs: dict[str, str], report: ImportReport) -> str | None:
    kind = re.sub(r"[^A-Z]", "", pairs.get("TYPE", "").upper())
    if kind in ("DEAD", "SUPERDEAD", "SUPERIMPOSEDDEAD"):
        return "D"
    if kind in ("LIVE", "REDUCELIVE", "REDUCIBLELIVE", "UNREDUCELIVE", "LIVEREDUCIBLE"):
        return "L"
    if kind in ("ROOFLIVE", "REDUCEROOFLIVE"):
        return "Lr"
    if kind in ("OTHER", "FLUID", "LIQUID") and _FLUID.match(name):
        return "F"
    if kind in ("WIND", "SEISMIC", "QUAKE", "EARTHQUAKE"):
        axis, guessed = _axis(name)
        if guessed:
            report.approximate(f"lateral pattern without X or Y in its name taken as {axis}", name)
        return ("W" if kind == "WIND" else "E") + axis
    return None


# ─────────────────────────────────────────── import ───────────────────────────────────────────


def read_e2k(
    source: str | Path,
    name: str | None = None,
    section_lookup: SectionLookup | None = None,
    text: str | None = None,
) -> ImportedProject:
    """The SAEngine project of the e2k file ``source`` (or of ``text``, ``source`` naming it)."""
    path = Path(source)
    if text is None:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
    e = parse(text)
    report = ImportReport("ETABS", path.name)
    report.source.update({"version": e.version, "units": e.units.label})
    if not e.units_given:
        report.warn("The file has no units line: kN and m assumed.")
    builder = ProjectBuilder(name or e.title or path.stem, report)
    _Importer(e, builder, report, section_lookup).run()
    return builder.build()


class _Importer:
    def __init__(
        self,
        e: E2k,
        builder: ProjectBuilder,
        report: ImportReport,
        lookup: SectionLookup | None,
    ) -> None:
        self.e, self.b, self.report, self.lookup = e, builder, report, lookup
        self.u = e.units
        self.elevation: dict[str, float] = {}
        self.order: list[str] = []  # stories bottom up
        self.pattern_cases: dict[str, str | None] = {}
        self.instances: dict[tuple[str, str], str] = {}  # (line or area, story) -> name
        self.lengths: dict[str, float] = {}  # line instance -> length m
        #: Property modifiers by kind (column, beam, brace, slab, wall): (instance, values).
        self.modifiers: dict[str, list[tuple[str, dict[str, float]]]] = defaultdict(list)
        self.labels: dict[str, set[str]] = defaultdict(set)  # pier / spandrel -> labels

    def run(self) -> None:
        self._stories()
        self._grids()
        self._materials()
        self._frame_sections()
        self._shell_props()
        self._lines()
        self._areas()
        self._supports()
        self._patterns()
        self._loads()
        self._combinations()
        self._stiffness()
        self._seismic_and_mass()
        for key, labels in self.labels.items():
            for label in sorted(labels):
                self.report.skip(
                    f"{key} labels not read (SAEngine groups and designs its walls itself)", label
                )
        for block, count in self.e.unread.items():
            if count and not block.startswith(("PROGRAM", "CONTROLS", "FILE")):
                if any(word in block for word in _IGNORED_BLOCKS) or "LOAD CASES" in block:
                    continue
                self.report.skip(f"lines of '{block.title()}' not read", f"{count} lines")

    # ── stories and grids ──

    def _stories(self) -> None:
        elevation = 0.0
        for k, story in enumerate(reversed(self.e.stories)):
            elev = _num(story, "ELEV")
            height = _num(story, "HEIGHT")
            if elev is not None:
                elevation = self.u.to_mm(elev)
            elif height is not None and k > 0:
                elevation += self.u.to_mm(height)
            elif k > 0:
                self.report.skip("stories without a height", story["NAME"])
                continue
            self.elevation[story["NAME"]] = elevation
            self.order.append(story["NAME"])
            self.b.add_story(story["NAME"], round(elevation, 3))

    def _level(self, story: str, below: int) -> float | None:
        if story not in self.elevation:
            return None
        index = self.order.index(story) - below
        return self.elevation[self.order[index]] if index >= 0 else None

    def _grids(self) -> None:
        for grid in self.e.grids:
            system = self.e.grid_systems.get(grid.get("SYSTEM", ""), {})
            kind = system.get("TYPE", "CARTESIAN").upper()
            rotation = _num(system, "ROTATION", "BUBBLEROTATION") or 0.0
            ox, oy = (
                _num(system, "ORIGINX", "XORIGIN") or 0.0,
                _num(system, "ORIGINY", "YORIGIN") or 0.0,
            )
            coord = _num(grid, "COORD", "ORDINATE")
            direction = grid.get("DIR", "").upper()
            if (
                kind != "CARTESIAN"
                or abs(rotation) > 1e-9
                or coord is None
                or direction not in ("X", "Y")
            ):
                self.report.skip(
                    "grid lines that are not cartesian X or Y lines", grid.get("LABEL")
                )
                continue
            origin = ox if direction == "X" else oy
            self.b.add_grid(
                "x" if direction == "X" else "y",
                grid.get("LABEL", ""),
                round(self.u.to_mm(coord + origin), 3),
            )

    # ── materials and sections ──

    def _materials(self) -> None:
        temperature_f = self.e.temperature == "F"
        for name, m in self.e.materials.items():
            kind = re.sub(r"[^A-Z]", "", (m.get("TYPE") or m.get("DESIGNTYPE") or "").upper())
            E = _num(m, "E", "E1")
            e_mpa = self.u.to_mpa(E) if E else None
            category = {
                "CONCRETE": "concrete",
                "STEEL": "steel",
                "COLDFORMED": "steel",
                "REBAR": "rebar",
                "MASONRY": "masonry",
            }.get(kind)
            if category is None and kind in ("ISOTROPIC", "", "OTHER"):
                if "FC" in m:
                    category = "concrete"
                elif "FY" in m:
                    category = "steel"
            if category is None:
                category = "other"
                self.report.approximate("materials of other types as 'other'", name)
            weight = _num(m, "WEIGHTPERVOLUME", "W")
            mass = _num(m, "MASSPERVOLUME", "M")
            density = None
            if weight:
                density = self.u.to_density(weight)
            elif mass:
                density = mass * self.u.newton * 1e12 / self.u.mm**4
            alpha = _num(m, "A", "ALPHA", "A1")
            if alpha is not None and temperature_f:
                alpha *= 1.8
            fc, fy, fu = _num(m, "FC"), _num(m, "FY"), _num(m, "FU")
            self.b.add_material(
                name,
                category,  # type: ignore[arg-type]
                E=e_mpa,
                nu=_num(m, "U", "U12"),
                density=round(density, 3) if density else None,
                alpha=alpha,
                fc=round(self.u.to_mpa(fc), 3) if fc else None,
                fy=round(self.u.to_mpa(fy), 3) if fy else None,
                fu=round(self.u.to_mpa(fu), 3) if fu else None,
                grade=m.get("GRADE"),
            )
        self.report.source["materials"] = len(self.e.materials)

    def _frame_sections(self) -> None:
        for name, s in self.e.frame_sections.items():
            profile = self._profile(name, s)
            if profile is None:
                continue
            material = s.get("MATERIAL", "")
            if material not in self.e.materials:
                self.report.skip("sections with an unknown material", f"{name} ({material})")
                continue
            column_bars = beam_bars = None
            rc = self.e.concrete_sections.get(name)
            if rc is not None:
                column_bars, beam_bars = self._bars(name, rc, profile)
            self.b.add_frame_section(
                name,
                material,
                profile,
                column_reinforcement=column_bars,
                beam_reinforcement=beam_bars,
            )

    def _profile(self, name: str, s: dict[str, str]) -> dict[str, Any] | None:
        shape = re.sub(r"[^A-Z]", "", s.get("SHAPE", "").upper())
        mm = self.u.to_mm

        def dim(*keys: str) -> float | None:
            value = _num(s, *keys)
            return round(mm(value), 4) if value and value > 0 else None

        d, b = dim("D", "T3"), dim("B", "T2")
        tf, tw = dim("TF"), dim("TW")
        if shape in ("CONCRETERECTANGULAR", "RECTANGULAR", "RECTANGLE", "STEELRECTANGULAR"):
            if d and b:
                return {"shape": "rectangle", "xDim": b, "yDim": d}
        elif shape in ("CONCRETECIRCLE", "CIRCLE", "CIRCULAR", "STEELCIRCLE", "STEELROD", "ROD"):
            if d:
                return {"shape": "circle", "radius": d / 2}
        elif shape in ("IWIDEFLANGE", "WIDEFLANGE", "ISECTION", "I", "STEELI", "STEELIWIDEFLANGE"):
            if d and b and tf and tw:
                b2, tf2 = dim("T2B", "BB"), dim("TFB")
                if (b2 and abs(b2 - b) > 0.01) or (tf2 and abs(tf2 - tf) > 0.01):
                    self.report.approximate(
                        "unequal-flange I sections as symmetric (top flange)", name
                    )
                return {
                    "shape": "I",
                    "overallWidth": b,
                    "overallDepth": d,
                    "webThickness": tw,
                    "flangeThickness": tf,
                }
        elif shape in ("STEELTUBE", "BOXTUBE", "BOX", "TUBE", "RECTANGULARTUBE", "STEELBOXTUBE"):
            if d and b and (tf or tw):
                wall = tf or tw
                if tf and tw and abs(tf - tw) > 0.01:
                    wall = round((tf + tw) / 2, 4)
                    self.report.approximate(
                        "boxes with unequal walls at their mean thickness", name
                    )
                return {"shape": "rectangleHollow", "xDim": b, "yDim": d, "wallThickness": wall}
        elif shape in ("PIPE", "STEELPIPE", "CIRCLETUBE"):
            t = tw or dim("T")
            if d and t:
                return {"shape": "circleHollow", "radius": d / 2, "wallThickness": t}
        elif shape in ("CHANNEL", "STEELCHANNEL"):
            if d and b and tf and tw:
                return {
                    "shape": "U",
                    "depth": d,
                    "flangeWidth": b,
                    "webThickness": tw,
                    "flangeThickness": tf,
                }
        elif shape in ("ANGLE", "STEELANGLE"):
            if d and b and (tf or tw):
                if tf and tw and abs(tf - tw) > 0.01:
                    self.report.approximate(
                        "angles with unequal legs' thickness at the flange's", name
                    )
                return {"shape": "L", "depth": d, "width": b, "thickness": tf or tw}
        elif shape in ("TEE", "STEELTEE"):
            if d and b and tf and tw:
                return {
                    "shape": "T",
                    "depth": d,
                    "flangeWidth": b,
                    "webThickness": tw,
                    "flangeThickness": tf,
                }
        elif shape in ("CONCRETETEE", "CONCRETEL"):
            if d and tw:
                self.report.approximate("concrete T and L beams as their web rectangle", name)
                return {"shape": "rectangle", "xDim": tw, "yDim": d}
        elif shape in ("GENERAL", "SDSECTION", "SECTIONDESIGNER"):
            area = _num(s, "A", "AREA")
            inertia = _num(s, "I33", "I3")
            if area and inertia and area > 0 and inertia > 0:
                a_mm, i_mm = area * self.u.mm**2, inertia * self.u.mm**4
                h = math.sqrt(12 * i_mm / a_mm)
                self.report.approximate(
                    "general sections as the rectangle of the same area and major inertia", name
                )
                return {"shape": "rectangle", "xDim": round(a_mm / h, 3), "yDim": round(h, 3)}
        elif "AUTOSELECT" in shape or shape == "NONPRISMATIC":
            self.report.skip("auto-select lists and non-prismatic sections", name)
            return None
        elif shape in ("DOUBLEANGLE", "DOUBLECHANNEL"):
            self.report.skip("double angle and double channel sections", name)
            return None
        if d is None and self.lookup is not None:
            for candidate in (s.get("SHAPE", ""), name):
                found = self.lookup(candidate) if candidate else None
                # A lookup may also say how it read the name: (profile, approximation or None).
                note = None
                if isinstance(found, tuple):
                    found, note = found
                if found:
                    library = f" ({s['FILE']})" if s.get("FILE") else ""
                    self.report.approximate(
                        f"database sections{library}: {note}"
                        if note
                        else f"database sections{library} from SAEngine's section table",
                        name,
                    )
                    return found
        library = f" ({s['FILE']})" if s.get("FILE") else ""
        reason = (
            f"sections named from a steel database{library} that could not be read"
            if d is None
            else "sections of shapes SAEngine does not read"
        )
        self.report.skip(reason, f"{name} ({s.get('SHAPE', '')})")
        return None

    def _bars(
        self, name: str, rc: dict[str, str], profile: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """(column bars, beam bars) of a concrete section: the column layout of a column
        section; beams' bars are left to SAEngine's design (e2k gives only covers)."""
        kind = rc.get("TYPE", "").upper()
        material = rc.get("LONGBARMATERIAL") or rc.get("LONGITUDINALBARMATERIAL") or ""
        if kind == "BEAM":
            self.report.approximate(
                "beam bars left to SAEngine's design (e2k gives covers only)", name
            )
            return None, None
        if kind != "COLUMN":
            return None, None
        if material not in self.e.materials:
            self.report.approximate("column bars without a rebar material left out", name)
            return None, None
        # Older files name bar sizes (BARSIZE "#9", NUMBARS3DIR 4); ETABS 2016+ writes a
        # pattern and the area of one bar (PATTERN "R-4-3" LONGBARAREA 314.2: 4 and 3 bars on
        # the faces, 10 in all; PATTERN "C-8": 8 round a circle).
        dia = bar_diameter(rc.get("BARSIZE")) or self._bar_from_area(_num(rc, "LONGBARAREA"))
        tie = bar_diameter(rc.get("TIESIZE")) or self._bar_from_area(
            _num(rc, "CONFINEBARAREA", "TIEBARAREA")
        )
        cover = _num(rc, "COVER")
        spacing = _num(rc, "TIESPACING", "CONFINEBARSPACING")
        pattern = rc.get("PATTERN", "").upper().replace(" ", "")
        rectangular = re.fullmatch(r"R-(\d+)-(\d+)", pattern)
        round_pattern = re.fullmatch(r"C-(\d+)", pattern)
        circle = profile["shape"] == "circle" or pattern == "CIRCLE" or bool(round_pattern)
        if circle:
            count = int(_num(rc, "NUMBARSCIRC", "NUMBARS") or 0)
            if round_pattern:
                count = int(round_pattern.group(1))
        else:
            n3, n2 = int(_num(rc, "NUMBARS3DIR") or 0), int(_num(rc, "NUMBARS2DIR") or 0)
            if rectangular:
                n3, n2 = int(rectangular.group(1)), int(rectangular.group(2))
            count = 2 * (n3 + n2) - 4 if n3 >= 2 and n2 >= 2 else 0
        if not (dia and count and cover):
            self.report.approximate(
                "column bars that could not be read left to SAEngine's design", name
            )
            return None, None
        bars: dict[str, Any] = {
            "material": material,
            "cover": round(self.u.to_mm(cover), 3),
            "longitudinal": [{"position": "perimeter", "count": count, "dia": dia}],
        }
        if tie and spacing:
            spiral = "SPIRAL" in (rc.get("CONFINEMENT", "") + rc.get("TRANSREINF", "")).upper()
            transverse: dict[str, Any] = {
                "type": "spiral" if spiral else "tie",
                "dia": tie,
                "spacing": round(self.u.to_mm(spacing), 3),
            }
            legs3 = _num(rc, "NUMR3BARS", "NUMCONFINEBARS3")
            legs2 = _num(rc, "NUMR2BARS", "NUMCONFINEBARS2")
            if not circle and legs3 and legs2:
                # Column local 2 lies along the profile's x: ties along 3 run along y.
                transverse["legs"] = int(legs3)
                transverse["legsX"] = int(legs2)
            bars["transverse"] = transverse
        if "DESIGN" in (rc.get("DESIGNTYPE", "").upper(), rc.get("DESIGNCHECK", "").upper()):
            self.report.approximate(
                "column bars from the ETABS layout of a section ETABS designs (DESIGNTYPE Design)",
                name,
            )
        return bars, None

    def _bar_from_area(self, area: float | None) -> float | None:
        """The diameter [mm, to 0.1 mm] of a bar of ``area`` (file units²)."""
        if not area or area <= 0:
            return None
        dia = round(math.sqrt(4 * area * self.u.mm**2 / math.pi), 1)
        return dia if 5 <= dia <= 60 else None

    def _shell_props(self) -> None:
        for name, p in self.e.shell_props.items():
            kind = p.get("PROPTYPE", "").upper()
            material = p.get("MATERIAL") or p.get("SLABMATERIAL") or p.get("DECKMATERIAL") or ""
            thickness = _num(p, "SLABTHICKNESS", "WALLTHICKNESS", "THICKNESS", "TM", "TB")
            slab_type = p.get("SLABTYPE", "").upper()
            if kind == "DECK":
                depth, rib = (
                    _num(p, "SLABDEPTH", "DECKSLABDEPTH"),
                    _num(p, "RIBDEPTH", "DECKRIBDEPTH"),
                )
                if depth:
                    thickness = depth + (rib or 0) / 2
                    self.report.approximate("decks as solid slabs of the depth to mid-rib", name)
            if slab_type in ("RIBBED", "WAFFLE"):
                self.report.approximate("ribbed and waffle slabs as solid slabs of their top", name)
            if slab_type in ("MAT", "FOOTING"):
                self.report.skip(
                    "mat and footing slabs (foundations belong to 9 Substructure)", name
                )
                continue
            if not thickness or thickness <= 0:
                self.report.skip("shell properties without a thickness", name)
                continue
            if material not in self.e.materials:
                self.report.skip(
                    "shell properties with an unknown material", f"{name} ({material})"
                )
                continue
            if p.get("MODELINGTYPE", "").upper() == "MEMBRANE":
                self.report.approximate(
                    "membrane slabs as SAEngine slabs (loads to the beams)", name
                )
            self.b.add_shell_section(name, material, round(self.u.to_mm(thickness), 3))

    # ── geometry ──

    def _xyz(self, point: str, story: str, below: int) -> tuple[float, float, float] | None:
        p = self.e.points.get(point)
        z = self._level(story, below)
        if p is None or z is None:
            return None
        # A point's third number puts it that far below the story it is used at.
        dz = self.u.to_mm(p[2]) if p[2] else 0.0
        return (round(self.u.to_mm(p[0]), 3), round(self.u.to_mm(p[1]), 3), round(z - dz, 3))

    def _lines(self) -> None:
        for label, story, pairs in self.e.line_assigns:
            line = self.e.lines.get(label)
            instance = f"{label}-{story}"
            if line is None:
                self.report.skip("line assigns of unknown lines", instance)
                continue
            kind, pi, pj, below = line
            section = pairs.get("SECTION", "")
            if kind == "NULL" or section.upper() == "NONE":
                self.report.skip("null lines", instance)
                continue
            a, c = self._xyz(pi, story, below), self._xyz(pj, story, 0)
            if a is None or c is None:
                self.report.skip("lines with an unknown point or story", instance)
                continue
            if not self.b.has_frame_section(section):
                self.report.skip(
                    "frame members whose section could not be imported", f"{instance} ({section})"
                )
                continue
            frame_kind = {"COLUMN": "column", "BEAM": "beam", "BRACE": "brace"}.get(kind)
            pinned = self._releases(instance, pairs)
            self._offsets(instance, frame_kind, pairs)
            material = self.e.frame_sections.get(section, {}).get("MATERIAL", "")
            self._modifiers(frame_kind or "frame", instance, pairs, material)
            self._pier(pairs)
            self.b.add_frame(
                instance,
                section,
                a,
                c,
                frame_kind,  # type: ignore[arg-type]
                _num(pairs, "ANG") or 0.0,
                pinned,
            )
            self.instances[(label, story)] = instance
            self.lengths[instance] = math.dist(a, c) / 1000

    def _releases(self, instance: str, pairs: dict[str, str]) -> bool:
        """Whether a member's ends are both released in bending (pinned); what else it
        releases is reported, as SAEngine expresses only members pinned at both ends."""
        released = set(pairs.get("RELEASE", "").upper().split())
        if not released:
            return False
        bending = {"M2I", "M3I", "M2J", "M3J"}
        if "PINNED" in released:  # ETABS's shorthand: both bending moments at both ends
            released = (released - {"PINNED"}) | bending
        at_i, at_j = released & {"M2I", "M3I"}, released & {"M2J", "M3J"}
        pinned = bool(at_i) and bool(at_j)
        if pinned and (at_i | at_j) != bending:
            self.report.approximate(
                "members released in one bending plane at both ends taken as pinned in both",
                instance,
            )
        elif not pinned and (at_i or at_j):
            self.report.approximate(
                "bending releases at one end only not expressed (member continuous there)",
                f"{instance} ({pairs['RELEASE']})",
            )
        if released - bending:
            self.report.approximate(
                "axial, shear and torsion releases not expressed",
                f"{instance} ({pairs['RELEASE']})",
            )
        return pinned

    def _offsets(self, instance: str, kind: str | None, pairs: dict[str, str]) -> None:
        """Reports the offsets and insertion points SAEngine does not model yet."""
        if any(_num(pairs, key) for key in ("LENGTHOFFI", "LENGTHOFFJ")):
            self.report.approximate(
                "end length offsets ignored (SAEngine has no rigid end zones yet)",
                f"{instance} ({pairs.get('LENGTHOFFI', 0)}, {pairs.get('LENGTHOFFJ', 0)})",
            )
        if _num(pairs, "RIGIDZONE"):
            self.report.approximate(
                "rigid-zone factors ignored (SAEngine has no rigid end zones yet)",
                f"{instance} ({pairs['RIGIDZONE']})",
            )
        point = int(_num(pairs, "CARDINALPT") or 0)
        # 10 is the centroid; 8, the top centre, is where SAEngine puts its beams anyway.
        if point not in (0, 10) and not (kind == "beam" and point == 8):
            self.report.approximate(
                "insertion points (cardinal points) other than the centroid ignored",
                f"{instance} ({point})",
            )
        if any(_num(pairs, key) for key in pairs if key.startswith("OFFSET")):
            self.report.approximate("joint offsets of members ignored", instance)

    def _modifiers(self, kind: str, instance: str, pairs: dict[str, str], material: str) -> None:
        """Collects a member's or area's property modifiers (``PROPMODI33 0.35``) by kind
        (concrete members also without any, as SAEngine's cracked sections reach them)."""
        values = {
            key[len("PROPMOD") :]: value
            for key in pairs
            if key.startswith("PROPMOD") and (value := _num(pairs, key)) is not None
        }
        m = self.e.materials.get(material, {})
        concrete = "CONCRETE" in (m.get("TYPE", "") + m.get("DESIGNTYPE", "")).upper()
        if values or concrete:
            self.modifiers[kind].append((instance, values))

    def _pier(self, pairs: dict[str, str]) -> None:
        for key in ("PIER", "SPANDREL"):
            label = pairs.get(key, "")
            if label and label.upper() != "NONE":
                self.labels[key.lower()].add(label)

    def _areas(self) -> None:
        self.area_sets: dict[str, list[tuple[str, float]]] = {}
        for label, story, pairs in self.e.area_assigns:
            area = self.e.areas.get(label)
            instance = f"{label}-{story}"
            if area is None:
                self.report.skip("area assigns of unknown areas", instance)
                continue
            kind, labels, offsets = area
            points = [self._xyz(p, story, k) for p, k in zip(labels, offsets, strict=True)]
            if any(p is None for p in points) or len(points) < 3:
                self.report.skip("areas with an unknown point or story", instance)
                continue
            section = pairs.get("SECTION", "")
            if pairs.get("OPENING", "").upper() == "YES":
                self.b.add_opening(instance, points)  # type: ignore[arg-type]
                continue
            if kind == "NULL" or section.upper() == "NONE":
                self.report.skip("null areas", instance)
                continue
            if not self.b.has_shell_section(section):
                self.report.skip(
                    "areas whose section could not be imported", f"{instance} ({section})"
                )
                continue
            area_kind = {"FLOOR": "floor", "PANEL": "wall", "RAMP": "floor"}.get(kind)
            props = self.e.shell_props.get(section, {})
            material = props.get("MATERIAL") or props.get("SLABMATERIAL") or ""
            self._modifiers("wall" if kind == "PANEL" else "slab", instance, pairs, material)
            self._pier(pairs)
            self.b.add_area(instance, section, points, area_kind)  # type: ignore[arg-type]
            self.instances[(label, story)] = instance
            load_set = pairs.get("UNIFLOADSET")
            if load_set:
                self.area_sets[instance] = self.e.load_sets.get(load_set, [])

    def _supports(self) -> None:
        for point, story, pairs in self.e.point_assigns:
            restraint = pairs.get("RESTRAINT")
            if "SPRINGPROP" in pairs:
                self.b.springs += 1
                self.report.skip(
                    "point springs not imported (SAEngine's soil springs come from 9 "
                    "Substructure): check the supports",
                    f"{point}-{story} ({pairs['SPRINGPROP']})",
                )
            if not restraint or restraint.upper() in ("NO", "NONE"):
                continue
            at = self._xyz(point, story, 0)
            if at is None:
                self.report.skip("restraints at unknown points", f"{point}-{story}")
                continue
            dofs = set(restraint.upper().split())
            fixity = tuple(d in dofs for d in ("UX", "UY", "UZ", "RX", "RY", "RZ"))
            if any(fixity):
                self.b.add_support(at, fixity, f"{point}-{story}")

    # ── stiffness, mass and seismic definitions ──

    def _stiffness(self) -> None:
        """The property modifiers on SAEngine's section stiffness setting.

        SAEngine has no modifiers per member: its cracked sections (02 Project Settings →
        Analysis model) give concrete columns 0.70 Ig, beams 0.35 Ig, slabs 0.25 Ig and walls
        0.70 Ig (0.35 Ig cracked). Modifiers that are these factors switch them on for all
        cases (ETABS's modifiers act in every case); other values, membrane, axial, shear,
        torsion, mass and weight modifiers are reported as not applied.
        """
        cracked = {
            "column": {"I22": 0.7, "I33": 0.7},
            "beam": {"I33": 0.35},
            "slab": {"M11": 0.25, "M22": 0.25},
            "wall": {"M11": 0.7, "M22": 0.7},
        }
        mass_keys = {"M", "W", "MASS", "WEIGHT"}
        matched: list[str] = []
        unmodified: list[str] = []
        walls_cracked = False
        for kind, entries in self.modifiers.items():
            for instance, values in entries:
                values = {k: v for k, v in values.items() if abs(v - 1.0) > 1e-9}
                for key in sorted(values.keys() & mass_keys):
                    self.report.approximate(
                        "mass and weight modifiers not applied",
                        f"{instance} ({key} {values[key]:g})",
                    )
                stiffness = {k: v for k, v in values.items() if k not in mass_keys}
                expected = cracked.get(kind)
                if expected is None:
                    if stiffness:
                        self.report.approximate(
                            "property modifiers of braces and other members not applied", instance
                        )
                    continue
                if not stiffness:
                    unmodified.append(instance)
                    continue
                if kind == "wall" and all(
                    abs(stiffness.get(k, 1.0) - 0.35) < 0.02 for k in expected
                ):
                    walls_cracked = True
                elif not all(abs(stiffness.get(k, 1.0) - v) < 0.02 for k, v in expected.items()):
                    text = ", ".join(f"{k} {v:g}" for k, v in sorted(stiffness.items()))
                    self.report.approximate(
                        "property modifiers SAEngine cannot apply member by member (its cracked "
                        "section factors apply)",
                        f"{instance} ({text})",
                    )
                    continue
                matched.append(instance)
                rest = {k: v for k, v in stiffness.items() if k not in expected}
                if kind == "beam":
                    rest.pop("I22", None)
                if rest:
                    text = ", ".join(f"{k} {v:g}" for k, v in sorted(rest.items()))
                    self.report.approximate(
                        "membrane, axial, shear and torsion modifiers not applied",
                        f"{instance} ({text})",
                    )
        if matched:
            self.b.analysis.update(
                {"stiffness": "aci", "crackedFor": "all", "wallsCracked": walls_cracked}
            )
            self.report.approximate(
                "property modifiers as SAEngine's cracked sections in all cases (02 Project "
                "Settings → Analysis model)",
                f"{len(matched)} members",
            )
            for instance in unmodified:
                self.report.approximate(
                    "members without modifiers analysed with cracked sections too", instance
                )
        elif unmodified and not any(v for e in self.modifiers.values() for _, v in e):
            self.report.warn(
                "The file has no property modifiers (gross sections): SAEngine analyses the "
                "lateral cases on cracked concrete sections (BNBC 2020 Part 6 Sec 6.3.10.4.1; "
                "02 Project Settings → Analysis model → Section stiffness)."
            )

    def _seismic_and_mass(self) -> None:
        """Reports the auto seismic definitions and how the mass source differs from SAEngine's
        seismic weight (dead and superimposed dead loads and a share of the live load)."""
        from saengine.library.bnbc import SEISMIC_LIVE_SHARE

        for name, d in self.e.seismic.items():
            detail = f"{name}: {d.get('TYPE', '')}"
            if "SHEARCOEFF" in d:
                detail += f", C {d['SHEARCOEFF']}, k {d.get('HEIGHTEXPONENT', '1')}"
            self.report.approximate(
                "auto seismic definitions replaced by SAEngine's BNBC 2020 loads (02 Project "
                "Settings)",
                detail,
            )
        sources = self.e.mass_sources
        if not sources:
            return
        name, source = next(
            ((n, m) for n, m in sources.items() if m.get("ISDEFAULT", "").upper() == "YES"),
            next(iter(sources.items())),
        )

        def yes(key: str) -> bool:
            return source.get(key, "").upper() == "YES"

        differences = []
        if "INCLUDEELEMENTS" in source and not yes("INCLUDEELEMENTS"):
            differences.append("without the members' own mass")
        if yes("INCLUDELOADS"):
            factors: dict[str, float] = defaultdict(float)
            for pattern, factor in source.get("LOADS", []):
                case = self.pattern_cases.get(pattern) or pattern
                factors[case] = max(factors[case], factor)
            for case, factor in sorted(factors.items()):
                expected = 1.0 if case == "D" else SEISMIC_LIVE_SHARE if case == "L" else 0.0
                if abs(factor - expected) > 1e-6:
                    differences.append(f"{case} × {factor:g} (SAEngine {expected:g})")
        if yes("LUMPATSTORIES"):
            differences.append("lumped at the stories (SAEngine keeps it at the nodes)")
        if differences:
            self.report.approximate(
                f"mass source differs from SAEngine's seismic weight (D + SD + "
                f"{SEISMIC_LIVE_SHARE:g} L)",
                f"{name}: {'; '.join(differences)}",
            )

    # ── loads ──

    def _patterns(self) -> None:
        patterns = self.e.patterns
        if not patterns:
            # Older files: the static load cases are the patterns.
            patterns = {
                n: p
                for n, p in self.e.old_cases.items()
                if ("SELFWEIGHT" in p or "TYPE" in p) and not _is_spectrum(p)
            }
            self.e.patterns = patterns
        self_weight = False
        # The load patterns, counted as the SAP2000 and STAAD.Pro imports count their cases.
        self.report.count("loadCases", len(patterns))
        for name, p in patterns.items():
            case = _pattern_case(name, p, self.report)
            self.pattern_cases[name] = case
            sw = _num(p, "SELFWEIGHT", "SWMULT") or 0.0
            if sw:
                self_weight = True
                if case != "D" or abs(sw - 1) > 1e-9:
                    self.report.approximate(
                        "self-weight multipliers other than 1 in a dead pattern", name
                    )
            if case is None:
                self.report.note("loads.patterns.noCase", f"{name} ({p.get('TYPE')})")
            elif case == "F":
                self.report.approximate(
                    "patterns of type Other named as fluid loads taken as SAEngine's F", name
                )
            elif case[0] in "WE":
                self.report.note("loads.lateral.cases", name)
        self.b.self_weight = self_weight or not patterns

    def _loads(self) -> None:
        """The point and frame loads go to the builder (onto the floor-plan beams and columns);
        the uniform area loads of gravity patterns onto the floors."""
        u = self.u
        for point, story, pairs in self.e.point_loads:
            case = self.pattern_cases.get(pairs.get("LC", ""))
            example = f"{point}-{story} {pairs.get('LC', '')}"
            if any(_num(pairs, k) for k in ("MX", "MY", "MZ")):
                self.report.note("loads.joint.moments", example)
            at = self._xyz(point, story, 0)
            if at is None or pairs.get("TYPE", "FORCE").upper() != "FORCE":
                self.report.skip("point loads at unknown points or not forces", example)
                continue
            force = tuple(u.to_kn(_num(pairs, k) or 0.0) for k in ("FX", "FY", "FZ"))
            self.b.add_joint_load(at, case, force, example)  # type: ignore[arg-type]
        for line, story, pairs in self.e.line_loads:
            instance = self.instances.get((line, story), f"{line}-{story}")
            case = self.pattern_cases.get(pairs.get("LC", ""))
            example = f"{instance} {pairs.get('LC', '')}"
            length = self.lengths.get(instance, 0.0) * 1000  # mm
            kind = pairs.get("TYPE", "").upper()

            def vector(value: float, direction: str = pairs.get("DIR", "GRAV")) -> Any:
                """The load (x, y, z; Z up) of ``value`` in global direction ``direction``
                (GRAV: down), or None for a local direction."""
                d = re.sub(r"\s*PROJ(ECTED)?$", "", direction.strip().upper())
                axes = {"GRAV": (0, 0, -1), "X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}
                return tuple(value * k for k in axes[d]) if d in axes else None

            start: float | None = None  # mm from the member's start
            loaded: float | None = None  # mm loaded (None: to the end)
            point = kind == "POINTF"
            if kind == "UNIFF":
                value = u.to_kn_per_m(_num(pairs, "FVAL") or 0.0)
            elif kind == "TRAPF":
                f0, f1 = _num(pairs, "FSTART") or 0.0, _num(pairs, "FEND") or 0.0
                r0, r1 = _num(pairs, "RDSTART") or 0.0, _num(pairs, "RDEND")
                r1 = 1.0 if r1 is None else r1
                if abs(f0 - f1) > 1e-12:
                    self.report.note("loads.member.varying", example)
                value = u.to_kn_per_m((f0 + f1) / 2)
                start, loaded = min(r0, r1) * length, abs(r1 - r0) * length
            elif point:
                value = u.to_kn(_num(pairs, "FVAL") or 0.0)
                rd = _num(pairs, "RDIST")
                start = None if rd is None else rd * length
            elif kind.endswith("M"):  # UNIFM, POINTM, TRAPM: moments
                self.report.note("loads.member.moments", f"{example} ({kind})")
                continue
            else:
                self.report.skip("frame loads of types not read", f"{example} ({kind or '?'})")
                continue
            force = vector(value)
            if force is None:
                if case in ("WX", "WY", "EX", "EY"):
                    size = abs(value) * (1.0 if point else (loaded or length) / 1000)
                    self.b.lateral_load("loads.lateral.member", case, size, example)
                else:
                    self.report.note("loads.member.direction", example)
                continue
            self.b.add_member_load(
                instance,
                case,
                force,
                point=point,
                start=start,
                length=loaded,
                example=example,
            )
        pressures: list[tuple[str, str, float, str]] = []  # instance, pattern, pressure, dir
        for area, story, pairs in self.e.area_loads:
            instance = self.instances.get((area, story), f"{area}-{story}")
            if pairs.get("TYPE", "UNIFF").upper() not in ("UNIFF", "UNIFORM"):
                self.b.not_carried("non-uniform area loads", None, 0.0, instance)
                continue
            pressures.append(
                (
                    instance,
                    pairs.get("LC", ""),
                    _num(pairs, "FVAL") or 0.0,
                    pairs.get("DIR", "GRAV"),
                )
            )
        for instance, loads in getattr(self, "area_sets", {}).items():
            pressures += [(instance, pattern, value, "GRAV") for pattern, value in loads]
        for instance, pattern, value, direction in pressures:
            case = self.pattern_cases.get(pattern)
            d = direction.upper()
            down = u.to_kpa(value) * (1.0 if d == "GRAV" else -1.0 if d == "Z" else 0.0)
            area_m2 = self.b.area_of(instance)
            if case in ("WX", "WY", "EX", "EY"):
                size = abs(u.to_kpa(value)) * area_m2
                self.b.lateral_load("loads.lateral.area", case, size, f"{instance} {pattern}")
                continue
            if case not in ("D", "L", "Lr", "F"):
                self.b.not_carried_item("loads.noCase.area", case, down * area_m2, instance)
                continue
            if d not in ("GRAV", "Z"):
                self.b.not_carried(
                    "area loads in horizontal directions",
                    case,
                    abs(u.to_kpa(value)) * area_m2,
                    instance,
                )
                continue
            if case == "F":
                # SAEngine's F holds the contents of 07 MEP equipment only.
                self.report.approximate(
                    "fluid area loads applied as superimposed dead load (D factors)", instance
                )
                case = "D"
            self.b.add_area_load(instance, case, down)  # type: ignore[arg-type]

    def _combinations(self) -> None:
        cases = {n: c for n, c in self.e.cases.items() if c["loads"]}

        def patterns(name: str, seen: frozenset[str]) -> dict[str, float] | None:
            """The load patterns of a combination, case or pattern with their factors."""
            if name in self.e.combos and name not in seen:
                combo = self.e.combos[name]
                kind = re.sub(r"[^A-Z]", "", combo["pairs"].get("TYPE", "LINEARADD").upper())
                if kind not in ("LINEARADD", "ADD"):
                    return None
                total: dict[str, float] = defaultdict(float)
                for load, sf in combo["loads"]:
                    part = patterns(load, seen | {name})
                    if part is None:
                        self.report.approximate(
                            "combination terms that are not static load cases dropped",
                            f"{name}: {load}",
                        )
                        continue
                    for k, v in part.items():
                        total[k] += sf * v
                return dict(total)
            if name in self.e.cases and _is_spectrum(self.e.cases[name]["pairs"]):
                self.report.approximate(
                    "response-spectrum terms of combinations taken as SAEngine's equivalent "
                    "static earthquake cases EX / EY (BNBC 2020 loads, same factor and sign)",
                    name,
                )
                return _spectrum_terms(name, self.e.cases[name], self.report)
            if name in cases:
                total = defaultdict(float)
                for pattern, sf in cases[name]["loads"]:
                    total[pattern] += sf
                return dict(total)
            return {name: 1.0} if name in self.pattern_cases else None

        for name, combo in self.e.combos.items():
            kind = re.sub(r"[^A-Z]", "", combo["pairs"].get("TYPE", "LINEARADD").upper())
            if kind not in ("LINEARADD", "ADD"):
                self.report.note("combinations.envelope", f"{name} ({combo['pairs'].get('TYPE')})")
                continue
            # SAEngine's D is all dead load (self-weight and superimposed): one factor for the
            # dead patterns; the other cases likewise per case.
            by_case: dict[str, set[float]] = defaultdict(set)
            for pattern, factor in (patterns(name, frozenset()) or {}).items():
                if pattern.startswith(_SPECTRUM):
                    case = pattern[len(_SPECTRUM) :]
                else:
                    case = self.pattern_cases.get(pattern)
                if case is None:
                    if abs(factor) > 1e-12:
                        self.report.approximate(
                            "combination terms of patterns SAEngine has no case for dropped",
                            f"{name}: {pattern}",
                        )
                    continue
                by_case[case].add(round(factor, 6))
            result: dict[str, float] = {}
            for case, values in by_case.items():
                values.discard(0.0)
                if not values:
                    continue
                if len(values) > 1:
                    self.report.approximate(
                        "combinations with different factors on patterns of one SAEngine case: "
                        "the largest applies",
                        f"{name}: {case} {', '.join(f'{v:g}' for v in sorted(values))}",
                    )
                result[case] = max(values, key=abs)
            if not result:
                self.report.skip("combinations with no SAEngine case", name)
                continue
            self.b.add_combination(name, result)
