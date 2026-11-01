"""Code pack template, validation and comparison: the authoring side of code packs.

* :func:`new_pack` writes the skeleton of a new pack that extends another one (BNBC 2020 by
  default): ``pack.json``, one help-only data file per table the pack may override (with the
  first entries of the parent's table as an example), and a ``README.md`` that explains every
  key of ``pack.json``.
* :func:`validate_pack` checks a pack folder: :func:`saengine.codes.registry.validate` (manifest,
  inheritance, every table validated by its pydantic model) plus the authoring checks of this
  module (values in a file whose table is not in ``covers``, a pack without sources).
* :func:`diff_packs` lists the table/key differences of two resolved packs (a regional pack
  against BNBC, say).

JSON has no comments: the help of a data file goes into ``$help`` and ``$example``. Keys that
start with ``$`` are directives of the loader (:mod:`saengine.codes.merge`) and never reach the
resolved data, so a data file with only these keys changes nothing. ``pack.json`` takes only the
keys of :class:`saengine.codes.manifest.PackManifest`; its help is in the pack's README.md.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.codes.manifest import MANIFEST_FILE, MANIFEST_SCHEMA_ID, PACK_ID_PATTERN, PackManifest
from saengine.codes.merge import parse_table_file

#: A pack id: lower-case letters, digits, '.', '_' and '-' ("bd-coastal").
PACK_ID = re.compile(PACK_ID_PATTERN)

DEFAULT_PARENT = "bnbc2020"

#: What each table holds (the skeleton's help, ``saengine codepack show``, docs/code-packs.md).
TABLE_HELP: dict[str, str] = {
    "locations": "Towns and districts with their seismic zone and basic wind speed (the code's "
    "hazard maps as a list of places), keyed by a short id. Add your region's towns, or change "
    "the zone or wind speed of one.",
    "zoneCoefficients": "Seismic zone coefficient Z by seismic zone.",
    "windSpeeds": "Basic wind speeds, when the code gives them apart from the locations.",
    "occupancyCategories": "Occupancy (risk) categories with their seismic and wind importance "
    "factors.",
    "areaLoads": "Minimum live loads by use of the floor area, in kN/m2.",
    "deadLoads": "Unit weights of masonry and plaster (kN/m3) and the wall types whose weight "
    "the line loads of walls on beams take (loads.json of the floor plan).",
    "combinations": "Load cases (loadCases); the strength, temperature and gravity combinations, "
    "lists matched by name; the dead load factors of the seismic combinations "
    "(seismicDeadUpper, seismicDeadLower); and the overstrength (Omega0) note (overstrength). "
    "The service combinations (service) are unfactored and used only by the serviceability "
    "checks (serviceability).",
    "nonstructural": "Nonstructural components: the seismic force method and its factors, the "
    "component importance factors, the component rows (amplification and response reduction), "
    "the default rows of drawn walls and equipment, the exemptions, the exterior panel "
    "connection factors and the least anchorage force of walls.",
    "concreteTime": "Time-dependent concrete: the creep coefficient (creep: tabulatedCoefficient, "
    "by thickness, humidity and age at loading, with its development in time), drying shrinkage "
    "(shrinkage: tabulatedStrain, with the reinforced-section factor), the indoor and outdoor "
    "humidities, the strength gain for the modulus at the age of loading and the lump creep and "
    "shrinkage of the prestress losses.",
    "pushover": "Nonlinear static (pushover) analysis: the load pattern the code requires and how "
    "far to push (procedure), the target displacement method by id with its factors "
    "(targetDisplacement: coefficient) and the member acceptance method by id with its shares "
    "and strains (acceptance: fibreStrain).",
    "serviceability": "Serviceability: the storey drift and top sway limits under the service "
    "wind combination, member deflection limits (span divisors) by use of the member, and the "
    "factor of safety of the whole building against overturning.",
    "seismic": "Site classes (soil factor, corner periods), structural systems (R, Omega0, Cd, "
    "height limits), period coefficients Ct and m, seismic design category table, drift limits "
    "and the other plain numbers of the seismic analysis.",
    "wind": "Exposure categories and profiles, directionality, topographic and gust factors, "
    "pressure coefficients, topographic speed-up, force coefficients of other structures "
    "(signs and walls, chimneys and tanks, lattices and towers) and rooftop equipment.",
    "materials": "Material constants and limits: concrete strain, steel modulus, the grades "
    "permitted in seismic members, grade tolerances.",
    "factors": "Strength reduction factors phi of reinforced concrete: flexure, shear, "
    "compression (tied, spiral), bearing, ...",
    "concrete": "Reinforced concrete members: bar sizes, cover, minimum thickness tables of "
    "slabs and beams, steel ratio limits, spacing.",
    "detailing": "Detailing limits that are plain numbers: special moment frames, joints, walls, "
    "lintels.",
    "steel": "Structural steel: phi factors and slenderness limits.",
    "foundations": "Foundations: pile safety factors, partial factors of skin and base "
    "resistance, strut-and-tie factors; 'machine': machine foundations under dynamic forces "
    "(left out: not covered).",
    "transfer": "Deep beams and transfer girders, corbels and brackets, diaphragm chords and "
    "collectors: the limits and least steel of their clauses.",
    "slabCoefficients": "Slabs on beams designed by moment coefficients: the two-way tables "
    "by span ratio and edge case, their limits, the one-way coefficients, bar spacing limits.",
    "plumbing": "Water supply, drainage and rainwater: water demand by occupancy, storage, "
    "fixture units and the probable demand curve, velocity and pressure limits, stacks, drains "
    "and vents, septic tank and soak pit, leaders, gutters and storm drains, and the pipe data "
    "SAEngine assumes. 'pages' names where each clause is; the reports cite it.",
    "hvac": "Air-conditioning and energy: the outside design conditions of the stations, inside "
    "conditions, ventilation rates and occupancy, lighting power density, glazing and overhangs, "
    "and the loads SAEngine assumes where the code is silent ('assumptions', for the report).",
    "electrical": "Electrical services: load densities by use, the substation, transformer and "
    "generator rooms, shafts and risers, earthing, the lightning risk indices and protection, "
    "and typical equipment sizes and masses for the first layout.",
    "planning": "Planning rules of the plot: FAR and maximum ground coverage by use, plot size "
    "and road width, setbacks by plot size and height (the planning authority's rules; Dhaka: "
    "Imarat Nirman Bidhimala 2008).",
    "fire": "Fire protection: hazard classes of the occupancy groups, flows and durations, "
    "standpipe and hose pressures, pump ratings, sprinkler pipe schedules and spacing, and the "
    "NFPA values the code leaves out (marked 'from memory, to be checked').",
    "liveReduction": "Reduction of floor live loads by influence area: the formula's "
    "constants, the least factors, the uses not reduced and the live load element factors KLL.",
    "fireResistance": "Construction types and the fire resistance ratings of their elements; "
    "least sizes of concrete (by aggregate type) and masonry members by rating; advisory covers.",
    "siteInvestigation": "Site investigation and soil chemistry: the number, spacing and depth "
    "of the borings, the bands that identify organic, expansive, collapsible, dispersive and "
    "soft soils, the corrosivity scores and ratings, the corrosive-site limits, and the "
    "sulphate classes and chloride exposure of concrete in the ground.",
    "timber": "Sawn timber (permissible stress design): stresses by strength group and "
    "location of use, the column formulas, the depth factor, load duration factors and "
    "deflection limits.",
    "masonry": "Masonry walls: the design method by id (allowableStress), the mortar grades, "
    "the allowable stresses and their reductions and increases, Em, the dimension rules "
    "(effective height and length, slenderness, stiffening, basement, free-standing and "
    "parapet walls), the reinforcement details, the strength design and earthquake values, an "
    "optional f'm estimate from the unit strength and the clause of each check.",
    "steelSections": "The standard steel shapes: the nominal dimensions of each rolled family "
    "with the standard it comes from (its 'source'), the angles, the hollow section sizes and "
    "the walls rolled for them, the density. SAEngine computes the properties from them.",
    "construction": "Construction practice: the rules of excavation work (depths, side slopes, "
    "guard rail, surcharge zone, machinery setback, adjoining structures, notices), the seepage "
    "method at the base, fills, waterproofing and formwork (loads, timber stress, camber, posts, "
    "standard sizes). A group left out is not covered.",
    "slabMethods": "Two-way slab systems on columns, walls or flexible beams: the methods tried "
    "in order (twoWayMethods: directDesign, equivalentFrame) with their limits and moment "
    "shares, and the corner reinforcement and slab opening rules. A method or group left out is "
    "not covered.",
    "wallMethods": "Walls: the out-of-plane design of slender walls (slender: midheightMoment) "
    "and walls designed as grade beams (gradeBeam: beam). A group left out is not covered.",
    "stairMethods": "Stairs: flights built into walls, open wells, stringer beams and the "
    "special stairs (freeStanding: empiricalTable, sawtooth: supportChart, helicoidal: "
    "redundantCharts). A group left out is not covered.",
    "compositeConcrete": "Composite concrete flexural members (precast and cast-in-place parts "
    "placed separately): the horizontal shear limits at the contact surface and the ties.",
    "bamboo": "Round bamboo members (permissible stresses): safe working stresses by species, "
    "by density or from tests with the factors of safety, load duration factors, the column "
    "rules and the joints. A pack without it does not cover bamboo.",
    "ferrocement": "Ferrocement members: the mesh types (fy, effective moduli, efficiency "
    "factor), strength and service load design, crack width and fatigue limits, the detailing "
    "rules. A pack without it does not cover ferrocement.",
    "designClauses": "Clause references of the member and connection design, by module group "
    "(clauses.<group>.<key>, without the code's name), and the code's short name for compact "
    "notes. A pack without it names only itself in the design notes.",
    "designLimits": "Code values of the member design no other table holds: the cap of √f'c in "
    "shear and torsion, the ERW wall thickness factor, the stair geometry rules and widths. A "
    "pack without it does not cover those checks.",
}

#: Keys of pack.json, in the order the template writes them, with their help (written into the
#: new pack's README.md: pack.json itself takes no help keys).
MANIFEST_HELP: dict[str, str] = {
    "schema": f'Always "{MANIFEST_SCHEMA_ID}".',
    "id": "Short id of the pack: lower-case letters, digits, '.', '_' and '-' (bd-coastal). "
    "Projects refer to the pack by it: keep it once the pack is in use.",
    "name": "Name shown in Project Settings and in the report (Bangladesh coastal belt).",
    "edition": "The code and edition the pack follows (BNBC 2020 with the coastal amendment).",
    "country": "ISO 3166 country code (BD, NP, LK, ...).",
    "region": "State, province or city, when the pack is for part of a country; else null.",
    "version": "Version of the pack itself (1.0.0); raise it when you change a value.",
    "extends": "Id of the pack this one starts from (bnbc2020). Every table you do not provide "
    "comes from it unchanged; null for a pack that provides every table itself.",
    "covers": "Tables this pack provides (see data/). List a table here when you put values in "
    "its file.",
    "description": "One or two sentences: what the pack changes and for whom.",
    "sources": 'The documents the values come from: [{"id": "BNBC", "title": "Bangladesh '
    'National Building Code", "edition": "2020", "publisher": "HBRI"}].',
    "clauses": 'Clause references by table: {"locations": ["Gazette 12/2025, Table 3"]}. A data '
    "file's own $sources take precedence.",
    "author": "Who prepared the pack (name, firm, contact).",
    "licence": "SPDX id of the licence of the pack's data (CC-BY-4.0), or null.",
    "hooks": "Optional: a Python file in the pack (hooks.py) whose functions replace design "
    "formulas. Hooks run code, so SAEngine runs them only after the user trusts the pack, and "
    "any edit of the file withdraws the trust. null for a data-only pack.",
    "kind": 'Optional: "designCode" (the default; leave it out for a design code pack). '
    'Templates are "structureTemplate" or "buildingTemplate" packages.',
    "requires": 'Optional: what the pack needs, {"saengine": ">=0.0.47", "packages": '
    '{"bnbc2020": ">=1.0.0"}}; SAEngine refuses or flags a pack whose needs are not met.',
    "contents": 'Optional: the pack\'s files, default ["data/*.json"].',
    "preview": "Optional: a small card image in the pack folder (preview.png).",
}


def known_tables() -> list[str]:
    """The tables a pack may provide: the registry's (registered models and known areas)."""
    from saengine.codes import registry

    return list(registry.known_tables())


@dataclass
class Problem:
    """A problem of a pack: ``level`` is "error" (the pack cannot be used) or "warning"."""

    level: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.where}: {self.message}"


@dataclass
class ValidationResult:
    path: Path
    id: str = ""
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(p.level == "error" for p in self.problems)

    def to_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "id": self.id,
            "ok": self.ok,
            "problems": [p.__dict__ for p in self.problems],
        }


class TemplateError(Exception):
    """The pack cannot be created (bad id, existing folder, unknown parent)."""


# ─────────────────────────────── helpers ───────────────────────────────


def plain(value: Any) -> Any:
    """``value`` as plain JSON data: pydantic models dumped by alias, tuples as lists."""
    if hasattr(value, "model_dump"):
        return plain(value.model_dump(mode="json", by_alias=True))
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return plain(value._asdict())
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    return value


def _excerpt(table: Any, entries: int = 2) -> Any:
    """An example of a table's format: every top-level key, the collections in them cut to
    their first ``entries`` entries."""
    if not isinstance(table, dict):
        return table

    def cut(value: Any) -> Any:
        if isinstance(value, dict) and len(value) > entries:
            return dict(list(value.items())[:entries])
        if (
            isinstance(value, list)
            and len(value) > entries
            and not all(isinstance(v, int | float) for v in value)
        ):
            return value[:entries]
        return value

    return {k: cut(v) for k, v in table.items() if k not in ("sources",)}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


# ─────────────────────────────── new pack ───────────────────────────────


def new_pack(
    dest: Path | str,
    pack_id: str,
    name: str = "",
    extends: str | None = DEFAULT_PARENT,
    *,
    edition: str = "",
    country: str = "",
    author: str = "",
    project_root: Path | None = None,
) -> Path:
    """Writes the skeleton of a new pack into ``dest/<pack_id>`` and returns that folder.

    The parent (``extends``) must be a pack the registry knows (built-in, user, or a pack of
    ``project_root``); its tables give the data files their examples. A pack that extends
    nothing gets BNBC 2020's tables as examples; it must then fill every table."""
    from saengine.codes import registry

    if not PACK_ID.match(pack_id):
        raise TemplateError(
            f"'{pack_id}' is not a pack id: use lower-case letters, digits, '.', '_' and '-', "
            "starting with a letter or digit (at most 64 characters)"
        )
    dest_path = Path(dest)
    if dest_path.exists() and not dest_path.is_dir():
        raise TemplateError(f"{dest_path} is a file, not a folder")
    folder = dest_path / pack_id
    if folder.exists() and not folder.is_dir():
        raise TemplateError(f"{folder} exists and is a file")
    try:
        if folder.exists() and any(folder.iterdir()):
            raise TemplateError(f"{folder} exists and is not empty")
    except OSError as error:
        raise TemplateError(f"cannot read {folder}: {error}") from error
    try:
        # The parent, or BNBC 2020 as the example of the tables' format for a root pack.
        parent = registry.load(extends or DEFAULT_PARENT, project_root)
    except registry.CodePackError as error:
        raise TemplateError(f"cannot extend '{extends or DEFAULT_PARENT}': {error}") from error
    parent_name = parent.name
    parent_data = {t: parent.data(t) for t in parent.tables()}

    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA_ID,
        "id": pack_id,
        "name": name or pack_id,
        "edition": edition or None,
        "country": country or None,
        "region": None,
        "version": "0.1.0",
        "extends": extends or None,
        "covers": [],
        "description": None,
        "sources": [],
        "clauses": {},
        "author": author or None,
        "licence": None,
        "hooks": None,
    }
    PackManifest.model_validate(manifest)
    try:
        _write_skeleton(folder, manifest, parent_data, parent_name, extends, name or pack_id)
    except OSError as error:
        raise TemplateError(f"cannot write the pack into {folder}: {error}") from error
    return folder


def _named_lists(table: Any) -> list[str]:
    """Top-level keys of ``table`` that hold lists of items with a ``name``."""
    if not isinstance(table, dict):
        return []
    return [
        key
        for key, value in table.items()
        if isinstance(value, list)
        and value
        and all(isinstance(v, dict) and "name" in v for v in value)
    ]


def _write_skeleton(
    folder: Path,
    manifest: dict[str, Any],
    parent_data: dict[str, Any],
    parent_name: str,
    extends: str | None,
    title: str,
) -> None:
    """Writes pack.json, the help-only data files and README.md of a new pack."""
    (folder / "data").mkdir(parents=True, exist_ok=True)
    (folder / "docs").mkdir(exist_ok=True)
    _write_json(folder / MANIFEST_FILE, manifest)
    tables = known_tables()
    for table in tables:
        if table not in parent_data:
            continue  # a help-only file over a table the parent lacks would be an empty table
        what = (
            (
                "Put here only the entries you change, in the parent's format (see $example), "
                f"and add '{table}' to 'covers' in pack.json; everything else comes from the "
                "parent."
            )
            if extends
            else (
                "This pack extends no other: give every key of the table (see $example for the "
                f"format) and add '{table}' to 'covers' in pack.json."
            )
        )
        help_lines = [
            TABLE_HELP.get(table, f"The '{table}' table."),
            what,
            (
                "Keys starting with '$' are not data: $help and $example are ignored; "
                '"$replace": true replaces the parent table whole; "$remove": ["key"] in an '
                'object drops those keys of the parent\'s object; "$sources": ["clause"] says '
                "where your values come from."
            ),
        ]
        named = _named_lists(parent_data[table])
        if named:
            help_lines.append(
                f"{', '.join(named)}: lists matched by name. An item whose name the parent has "
                'changes that item, a new name is added, and {"name": "...", "$remove": true} '
                'drops the parent\'s item ("$remove": ["key"] does nothing to a list).'
            )
        help_lines.append(f"$example: the first entries of {parent_name}'s table.")
        content = {"$help": help_lines, "$example": _excerpt(parent_data[table])}
        _write_json(folder / "data" / f"{table}.json", content)
    keys = "\n".join(f"- `{key}`: {text}" for key, text in MANIFEST_HELP.items())
    listed = "\n".join(f"- `{t}`: {TABLE_HELP.get(t, '')}" for t in tables if t in parent_data)
    parent_line = f" extending {parent_name} (`{extends}`)" if extends else ""
    readme = (
        f"# {title}\n\n"
        f"A SAEngine design code pack{parent_line}. See docs/code-packs.md in SAEngine.\n\n"
        "- `pack.json`: what the pack is, what it covers, where its values come from.\n"
        "- `data/<table>.json`: the values; each file starts with its help under `$help`.\n"
        "- `docs/`: notes, extracts of the code you may share, calculations.\n\n"
        "Check it with `saengine codepack validate <this folder>`, and compare it with its "
        f"parent with `saengine codepack diff {extends or DEFAULT_PARENT} <this folder>`.\n\n"
        f"## The keys of pack.json\n\n{keys}\n\n## The tables (data/)\n\n{listed}\n"
    )
    (folder / "README.md").write_text(readme, encoding="utf-8")


# ─────────────────────────────── validation ───────────────────────────────


_EFFECT_DIRECTIVES = ("$remove", "$replace")


def _changes_parent(value: Any) -> bool:
    """Whether ``value`` (a table's data, directives inside) changes anything: a value, or a
    ``$remove``/``$replace`` directive. Help keys (``$help``, ``$example``, ...) do not."""
    if isinstance(value, dict):
        return any(not str(k).startswith("$") or k in _EFFECT_DIRECTIVES for k in value)
    if isinstance(value, list):
        return len(value) > 0
    return value is not None


def _has_effect(raw: Any) -> bool:
    """Whether a ``data/<table>.json`` document changes the resolved table, read the way the
    loader reads it (``merge.parse_table_file``: the ``{"$data": ...}`` wrapper included)."""
    try:
        parsed = parse_table_file(raw)
    except TypeError:
        return True  # malformed directives: the registry reports them; not "help only"
    return parsed.replace or _changes_parent(parsed.data)


def _authoring_checks(folder: Path, result: ValidationResult) -> None:
    """What the loader accepts but an author should hear about."""
    try:
        manifest = _read_json(folder / MANIFEST_FILE)
    except (OSError, ValueError):
        return  # the registry reports it
    if not isinstance(manifest, dict) or manifest.get("kind", "designCode") != "designCode":
        return  # templates: their files are validated by the registry
    covers = manifest.get("covers")
    covers = set(covers) if isinstance(covers, list) else set()
    data = folder / "data"
    files = sorted(data.glob("*.json")) if data.is_dir() else []
    with_values: set[str] = set()
    for path in files:
        try:
            content = _read_json(path)
        except (OSError, ValueError):
            continue  # the registry reports it
        if _has_effect(content):
            with_values.add(path.stem)
            if path.stem not in covers:
                result.problems.append(
                    Problem(
                        "warning",
                        f"data/{path.name}",
                        f"has values but '{path.stem}' is not in covers",
                    )
                )
    for table in sorted((covers & {p.stem for p in files}) - with_values):
        result.problems.append(
            Problem("warning", "pack.json", f"covers '{table}' but data/{table}.json has only help")
        )
    if not manifest.get("sources") and not manifest.get("clauses"):
        result.problems.append(
            Problem("warning", "pack.json", "no sources or clauses: say where the values come from")
        )


def validate_pack(
    folder: Path | str, project_root: Path | None = None, kind: str | None = None
) -> ValidationResult:
    """Checks the pack in ``folder``: the registry's validation (manifest, inheritance, every
    table or template file, requires, no programs) and the authoring checks. With ``kind``, a
    package of another kind is an error."""
    from saengine.codes import registry

    folder = Path(folder)
    result = ValidationResult(folder)
    if not folder.is_dir():
        result.problems.append(Problem("error", str(folder), "not a folder"))
        return result
    info = registry.validate(folder, project_root)
    result.id = info.id
    if kind is not None and info.kind != kind:
        result.problems.append(
            Problem("error", "pack.json", f"the package is a {info.kind}, not a {kind}")
        )
    for problem in info.problems:
        where = problem.file or (f"data/{problem.table}.json" if problem.table else "pack")
        result.problems.append(Problem(problem.severity, where, problem.message))
    if not info.usable and result.ok:
        result.problems.append(Problem("error", "pack", "the pack cannot be loaded"))
    _authoring_checks(folder, result)
    if info.hooks:
        result.problems.append(
            Problem(
                "warning",
                "pack.json",
                "the pack has hooks (Python code): they run only after the user trusts the pack",
            )
        )
    return result


# ─────────────────────────────── loading and comparing ───────────────────────────────


@contextmanager
def opened(ref: str, project_root: Path | None = None) -> Iterator[Any]:
    """The :class:`CodePack` ``ref`` names: a pack folder (with a pack.json), else a pack id
    the registry knows."""
    from saengine.codes import registry

    path = Path(ref)
    if (path / MANIFEST_FILE).is_file():
        yield registry.load_path(path, project_root)
    else:
        yield registry.load(ref, project_root)


def resolved_tables(pack: Any) -> dict[str, Any]:
    """Every table the pack has (its own and inherited), as plain JSON data."""
    return {name: pack.data(name) for name in pack.tables()}


@dataclass
class Difference:
    """``kind``: "added" (only in b), "removed" (only in a) or "changed"."""

    path: str
    kind: str
    a: Any = None
    b: Any = None

    def __str__(self) -> str:
        if self.kind == "added":
            return f"+ {self.path}: {_short(self.b)}"
        if self.kind == "removed":
            return f"- {self.path}: {_short(self.a)}"
        return f"~ {self.path}: {_short(self.a)} -> {_short(self.b)}"


def _short(value: Any, limit: int = 70) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def compare(a: Any, b: Any, path: str = "") -> list[Difference]:
    """The differences of two plain JSON values, key by key (lists by position; lists of
    objects that all have a distinct "id" or "name" are matched by it)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[Difference] = []
        for key in list(a) + [k for k in b if k not in a]:
            sub = _join(path, str(key))
            if key not in b:
                out.append(Difference(sub, "removed", a=a[key]))
            elif key not in a:
                out.append(Difference(sub, "added", b=b[key]))
            else:
                out += compare(a[key], b[key], sub)
        return out
    if isinstance(a, list) and isinstance(b, list):
        keyed_a, keyed_b = _keyed(a), _keyed(b)
        if keyed_a is not None and keyed_b is not None:
            return compare(keyed_a, keyed_b, path)
        out = []
        for i in range(max(len(a), len(b))):
            sub = f"{path}[{i}]"
            if i >= len(b):
                out.append(Difference(sub, "removed", a=a[i]))
            elif i >= len(a):
                out.append(Difference(sub, "added", b=b[i]))
            else:
                out += compare(a[i], b[i], sub)
        return out
    if a != b:
        return [Difference(path, "changed", a=a, b=b)]
    return []


def _keyed(items: list[Any]) -> dict[str, Any] | None:
    for key in ("id", "name"):
        if items and all(isinstance(i, dict) and isinstance(i.get(key), str) for i in items):
            names = [i[key] for i in items]
            if len(set(names)) == len(names):
                return {f"[{n}]": i for n, i in zip(names, items, strict=True)}
    return None


def diff_packs(a: str, b: str, project_root: Path | None = None) -> list[Difference]:
    """The table/key differences of packs ``a`` and ``b`` (ids or folders), both resolved."""
    with opened(a, project_root) as pack_a:
        tables_a = resolved_tables(pack_a)
    with opened(b, project_root) as pack_b:
        tables_b = resolved_tables(pack_b)
    return compare(tables_a, tables_b)
