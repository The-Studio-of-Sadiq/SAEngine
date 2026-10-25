"""The printed design report of a SAEngine project (Part 11 Exports, ``11 Exports/report.pdf``).

The report is an engineer's calculation report: cover and contents, design basis (codes, site,
seismic and wind parameters, materials, load cases and combinations, analyses run), the soil and
foundations of ``01 Soil Report/soil-report.json`` (when it has boreholes: the boreholes, the
site class, the allowable bearing pressures and the liquefaction screening), the foundations of
``09 Substructure/substructure.json`` with their design checks (pile capacities and loads, raft
results), a summary
of the analysis model and its run, the main analysis results (modal periods, base reactions,
displacements and story drifts), the member design checks of :mod:`saengine.design`, the bill
of quantities of ``10 BOQ/boq.json`` and the limitations every part reported.

:func:`report_data` gathers everything into plain JSON, every number already formatted as text;
:func:`build_report` hands it to the Typst template ``templates/report.typ`` (through
``sys.inputs``, read back with Typst's ``json()``), which only lays it out. User text therefore
reaches the template as strings and is printed literally: names with ``#``, ``$``, ``*``, ``_``,
``@``, ``<`` or ``[`` need no escaping.

Units: the project files are in mm and MPa, the analysis model in SI (m, N, Pa). The report
prints kN, kN·m, kN/m², MPa, mm and m.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

import saengine
from saengine.codes import context as code_context

TEMPLATE = Path(__file__).parent / "templates" / "report.typ"

SOIL_FILE = "01 Soil Report/soil-report.json"
SETTINGS_FILE = "02 Project Settings/project-settings.json"
MATERIALS_FILE = "03 Materials/materials.json"
OBJECTS_FILE = "04 Objects/objects.json"
BIM_FILE = "06 BIM/bim.json"
SUBSTRUCTURE_FILE = "09 Substructure/substructure.json"
MODEL_FILE = "08 FEM/model.osmodel"
RESULTS_DIR = "08 FEM/model.results"
BOQ_FILE = "10 BOQ/boq.json"
DEFAULT_OUTPUT = "11 Exports/report.pdf"

#: Upstream files of the analysis model, by the keys of the stamps it records.
MODEL_SOURCES = {
    "bim": BIM_FILE,
    "objects": OBJECTS_FILE,
    "materials": MATERIALS_FILE,
    "settings": SETTINGS_FILE,
}

#: Upstream files recorded only when the derivation used them (the soil report's site class).
MODEL_OPTIONAL_SOURCES = {"soil": SOIL_FILE, "loads": "05 Floor Plan/loads.json"}

#: Upstream files of the bill of quantities, by the keys of its ``source`` stamps.
BOQ_SOURCES = {
    "bim": BIM_FILE,
    "objects": OBJECTS_FILE,
    "materials": MATERIALS_FILE,
    "substructure": SUBSTRUCTURE_FILE,
    "mep": "07 MEP/mep.json",
    "settings": SETTINGS_FILE,
}

RESULT_TYPES = {
    "StaticResults": "Linear static",
    "ModalResults": "Modal (eigenvalue)",
    "ResponseSpectrumResults": "Response spectrum",
    "TransientResults": "Time history",
    "PushoverResults": "Pushover",
}

#: Element kinds of the design tables, in this order; any other kind follows alphabetically.
KIND_ORDER = [
    "footing",
    "pileCap",
    "pile",
    "column",
    "wall",
    "beam",
    "brace",
    "slab",
    "staircase",
    "lintel",
]

KIND_TITLES = {
    "footing": "Footings",
    "pileCap": "Pile caps",
    "pile": "Piles",
    "column": "Columns",
    "wall": "Walls",
    "beam": "Beams",
    "brace": "Braces",
    "slab": "Slabs",
    "staircase": "Stairs",
    "lintel": "Lintels",
    "member": "Members",
}

BOQ_GROUPS = {
    "earthwork": "Earthwork",
    "concrete": "Concrete",
    "masonry": "Masonry",
    "reinforcement": "Reinforcement",
    "formwork": "Formwork",
    "steel": "Structural steel",
    "mep": "MEP coordination",
    "materials": "Materials (cement, sand, stone chips, water)",
}

UNITS = {
    "m3": "m³", "m2": "m²", "kg": "kg", "nr": "nr", "m": "m", "cft": "cft", "bag": "bags", "l": "l"
}  # fmt: skip

#: Lateral load cases of a derived model and the global direction they push in (0 = X, 1 = Y).
LATERAL_CASES = {"WX": 0, "WY": 1, "EX": 0, "EY": 1}

MAX_MODES = 12

UNITS_STATEMENT = (
    "Units: geometry in m (sections and bar sizes in mm); forces in kN, moments in kN·m, "
    "distributed loads in kN/m², stresses and strengths in MPa, displacements in mm. The "
    "analysis model is in SI units (m, N, Pa); its results are converted for this report."
)


# ─────────────────────────────────────── entry points ───────────────────────────────────────


def build_report(
    project_root: str | Path, out_pdf: str | Path | None = None, *, version: str | None = None
) -> dict[str, Any]:
    """Typesets the design report of the project at ``project_root`` as a PDF.

    ``out_pdf`` defaults to ``<project>/11 Exports/report.pdf``; ``version`` is the SAEngine
    version printed on the cover (the Python package's version when not given). Returns
    ``{"path", "pages", "warnings"}`` (``warnings``: what the report could not include, and
    Typst's own warnings), or ``{"problems"}`` when there is nothing to report or the PDF could
    not be written.
    """
    root = Path(project_root)
    # The project's own code packs (02 Project Settings/code-packs) are found while it is built.
    with code_context.project(root):
        data = report_data(root, version=version)
    if "problems" in data:
        return {"problems": data["problems"]}
    target = Path(out_pdf) if out_pdf else root / DEFAULT_OUTPUT
    try:
        pdf, typst_warnings = render_pdf(data)
    except Exception as error:  # noqa: BLE001 - Typst, font and IO failures alike
        return {"problems": [f"The report could not be typeset: {error}"]}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(pdf)
    except OSError as error:
        return {
            "problems": [
                (
                    f"{target} could not be written ({error.strerror or error}); "
                    "close it if it is open in a PDF viewer and try again."
                )
            ]
        }
    result: dict[str, Any] = {
        "path": str(target),
        "warnings": list(data["warnings"]) + typst_warnings,
    }
    pages = count_pages(pdf)
    if pages:
        result["pages"] = pages
    return result


def render_pdf(data: dict[str, Any]) -> tuple[bytes, list[str]]:
    """The PDF of the report ``data`` (from :func:`report_data`) and Typst's warnings."""
    import typst

    inputs = {"data": json.dumps(data, ensure_ascii=False, allow_nan=False)}
    result = typst.compile_with_warnings(str(TEMPLATE), format="pdf", sys_inputs=inputs)
    pdf, warnings = result if isinstance(result, tuple) else (result, [])
    return pdf, [f"Typst: {getattr(w, 'message', w)}" for w in warnings or []]


def count_pages(pdf: bytes) -> int:
    """Pages of a PDF written by Typst (page objects are not in compressed object streams)."""
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf))


def report_data(
    project_root: str | Path, *, version: str | None = None, today: date | None = None
) -> dict[str, Any]:
    """Everything the report prints, as JSON-ready data with numbers formatted as text, or
    ``{"problems"}`` when the project has no analysis results to report."""
    root = Path(project_root)
    model_path = root / MODEL_FILE
    results_dir = root / RESULTS_DIR
    if not model_path.is_file():
        return {"problems": [f"There is no analysis model ({MODEL_FILE}): derive it first."]}
    if not (results_dir / "manifest.json").is_file():
        return {"problems": ["There are no analysis results: run the analysis first."]}
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        manifest = json.loads((results_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return {"problems": [f"The analysis model or its results could not be read: {error}"]}
    if not manifest.get("cases"):
        return {"problems": ["The analysis results hold no cases: run the analysis first."]}

    warnings: list[str] = []
    parts = _Parts(root, warnings)
    settings = parts.settings()
    name = project_name(root, settings)

    report: dict[str, Any] = {
        "meta": _meta(name, settings, version, today or date.today()),
        "warnings": warnings,
    }
    report["basis"] = _basis(settings, parts, model, manifest)
    report["soil"] = _soil(parts)
    report["foundations"] = _foundations(parts)
    report["model"] = _model_summary(root, model, manifest, parts, warnings)
    report["results"] = _results(
        model_path, model, manifest, results_dir, settings, parts, warnings
    )
    report["design"] = _design(results_dir, model_path, warnings)
    report["design"]["required"] = (
        _required(results_dir, model_path, warnings)
        if report["design"].get("available")
        else {"available": False}
    )
    report["mep"] = _mep(parts)
    report["plumbing"] = _plumbing(parts)
    report["hvac"] = _guarded(_hvac, parts, "HVAC")
    report["electrical"] = _guarded(_electrical, parts, "electrical")
    report["boq"] = _boq(parts)
    report["limitations"] = {
        "design": report["design"].get("notes", []),
        "mep": report["mep"].get("notes", []),
        "plumbing": report["plumbing"].get("notes", []),
        "hvac": report["hvac"].get("notes", []),
        "electrical": report["electrical"].get("notes", []),
        "boq": report["boq"].get("notes", []),
        "soil": report["soil"].get("notes", []),
        "foundations": report["foundations"].get("notes", []),
        "model": report["model"].get("notes", []),
        "run": report["model"].get("runWarnings", []),
    }
    return report


# ─────────────────────────────────────── project files ───────────────────────────────────────


class _Parts:
    """The project's part files, read and validated once, problems noted as warnings."""

    def __init__(self, root: Path, warnings: list[str]) -> None:
        self.root = root
        self.warnings = warnings
        self._cache: dict[str, Any] = {}

    def text(self, relative: str) -> str | None:
        try:
            return (self.root / relative).read_text(encoding="utf-8")
        except OSError:
            return None

    def _parse(self, key: str, relative: str, model: Any, label: str) -> Any:
        if key not in self._cache:
            text = self.text(relative)
            value = None
            if text is None:
                self.warnings.append(f"{label} ({relative}) could not be read.")
            else:
                try:
                    value = model.model_validate_json(text)
                except ValueError as error:
                    first = str(error).splitlines()
                    self.warnings.append(
                        f"{label} ({relative}) is not valid"
                        + (f": {first[1].strip()}" if len(first) > 1 else ".")
                    )
            self._cache[key] = value
        return self._cache[key]

    def settings(self) -> Any:
        """The project settings with the site class the analysis uses (from the soil report
        when the settings say so, see ``resolve_site_class``)."""
        from saengine.library.settings import ProjectSettings, resolve_site_class

        if "resolved" not in self._cache:
            entered = self._parse("settings", SETTINGS_FILE, ProjectSettings, "Project settings")
            resolved, site = (
                resolve_site_class(entered, self.text(SOIL_FILE))
                if entered is not None
                else (None, None)
            )
            self._cache["resolved"], self._cache["site"] = resolved, site
        return self._cache["resolved"]

    def site(self) -> dict[str, Any] | None:
        """Where the site class comes from (``resolve_site_class``'s info)."""
        self.settings()
        return self._cache["site"]

    def materials(self) -> Any:
        from saengine.library.materials import MaterialLibrary

        return self._parse("materials", MATERIALS_FILE, MaterialLibrary, "Materials")

    def objects(self) -> Any:
        from saengine.library.objects import ObjectLibrary

        return self._parse("objects", OBJECTS_FILE, ObjectLibrary, "Object types")

    def building(self) -> Any:
        from saengine.library.bim import BuildingModel

        return self._parse("bim", BIM_FILE, BuildingModel, "Building model")

    def stamp(self, relative: str) -> str | None:
        from saengine.library.bim import source_stamp

        text = self.text(relative)
        return source_stamp(text) if text is not None else None

    def boq_stamp(self, key: str, relative: str) -> str | None:
        """The stamp of a source of the bill of quantities as the bill records it: for the
        settings, the stamp of their ground level only (as ``compute_boq`` and the workbench's
        ``boqSourceStamp`` do), else the stamp of the file's text."""
        if key != "settings":
            return self.stamp(relative)
        from saengine.library.bim import ground_level_stamp, source_stamp

        text = self.text(relative)
        if text is None:
            return None
        try:
            settings = json.loads(text)
        except ValueError:
            return source_stamp(text)
        foundation = settings.get("foundation") if isinstance(settings, dict) else None
        ground = foundation.get("groundLevel") if isinstance(foundation, dict) else None
        if isinstance(ground, bool) or not isinstance(ground, int | float):
            ground = 0.0
        return ground_level_stamp(ground)


def project_name(root: Path, settings: Any = None) -> str:
    """The project's name as the workbench shows it: the ``name`` in the ``*.saengine``
    manifest at the root, else the manifest's file name, else the settings' project name, else
    the folder's name."""
    try:
        # Case-insensitive, as the workbench (saengineProjectService) matches the extension.
        manifests = sorted(
            p for p in root.iterdir() if p.is_file() and p.name.lower().endswith(".saengine")
        )
    except OSError:
        manifests = []
    if manifests:
        try:
            name = json.loads(manifests[0].read_text(encoding="utf-8")).get("name")
            if isinstance(name, str) and name.strip():
                return name
        except (OSError, ValueError, AttributeError):
            pass
        return manifests[0].stem
    if settings is not None and settings.project.name:
        return settings.project.name
    return root.resolve().name


# ─────────────────────────────────────── formatting ───────────────────────────────────────


def fmt(value: float | None, digits: int = 1) -> str:
    """A number as the report prints it: fixed decimals, thousands separated, "–" for none."""
    if value is None:
        return "–"
    value = float(value)
    if not math.isfinite(value):
        return "∞" if value > 0 else "–"
    if abs(value) < 0.5 * 10**-digits:
        value = 0.0
    return f"{value:,.{digits}f}"


def _factor(value: float) -> str:
    return "" if not value else f"{value:g}"


# ─────────────────────────────────────── sections ───────────────────────────────────────


def _meta(name: str, settings: Any, version: str | None, today: date) -> dict[str, Any]:
    info = settings.project if settings is not None else None
    details = []
    if info is not None:
        for label, value in (
            ("Project number", info.number),
            ("Client", info.client),
            ("Address", info.address),
            ("Structural engineer", info.engineer),
        ):
            if value:
                details.append([label, value])
    if settings is not None:
        details.append(["Code pack", code_pack_text(settings)])
    return {
        "title": "Structural Design Report",
        "project": name,
        "details": details,
        "code": settings.codes.concrete if settings is not None else "–",
        "date": f"{today.day} {today:%B %Y}",
        "isoDate": today.isoformat(),
        "version": version or saengine.__version__,
        "units": UNITS_STATEMENT,
    }


def code_pack_text(settings: Any) -> str:
    """The code pack the project follows, as the report's front matter states it: "<name>
    (<id>), <edition>, pack version <v>", with "modified by: <pack>" when it extends another
    pack, and where a user or project copy replaces a built-in pack."""
    from saengine.codes import CodePackError
    from saengine.library.settings import code_pack

    try:
        pack = code_pack(settings)
    except CodePackError as error:
        return f"{settings.codePack}: {error}"
    facts = code_context.front_matter(pack)
    text = f"{facts['name']} ({facts['id']})"
    if facts["edition"] and facts["edition"] != facts["name"]:
        text += f", {facts['edition']}"
    text += f", pack version {facts['version']}"
    if facts["extends"] and facts["extends"] != facts["id"]:
        try:
            base = code_context.pack_for({"codePack": facts["extends"]})
            text = f"{base.name} ({base.id}), modified by: {text}"
        except CodePackError:
            text += f", extends {facts['extends']}"
    if facts["replacesBuiltin"]:
        text += f" - a {facts['scope']} copy at {facts['path']}, modified from the built-in code"
    return text


def _basis(settings: Any, parts: _Parts, model: dict[str, Any], manifest: dict[str, Any]) -> dict:
    basis: dict[str, Any] = {}
    if settings is not None:
        from saengine.codes import CodePackError
        from saengine.library.settings import code_pack, derived

        try:
            pack = code_pack(settings)
        except CodePackError as error:
            parts.warnings.append(f"Code pack: {error}")
            return basis
        parts.warnings.extend(f"Code pack {pack.id}: {w.message}" for w in pack.warnings)
        values = derived(settings)
        codes = settings.codes
        basis["codes"] = [
            ["Loads and general", codes.general],
            ["Concrete", codes.concrete],
            ["Steel", codes.steel],
            ["Design method", "Strength design (LRFD)"],
        ]
        location = pack.table("locations").locations.get(settings.site.location)
        category = pack.table("occupancyCategories").categories.get(settings.occupancy.category)
        system = pack.table("seismic").systems.get(settings.seismic.system)
        uses = pack.table("areaLoads").uses
        basis["site"] = [
            ["Building use", settings.occupancy.use.capitalize()],
            [
                "Occupancy category",
                settings.occupancy.category
                + (f": {category.description}" if category is not None else ""),
            ],
            ["Location", location.name if location else "Custom"],
            ["Site class (Table 6.2.13)", _site_class_text(parts)],
            ["Seismic zone", str(values["zone"]) if values["zone"] else "–"],
            ["Seismic zone coefficient Z", fmt(values["Z"], 2)],
            ["Basic wind speed V", f"{fmt(values['windSpeed'], 1)} m/s"],
            ["Wind exposure category", settings.wind.exposure],
        ]
        basis["seismic"] = [
            [
                "Structural system (Table 6.2.19)",
                system.name if system else settings.seismic.system,
            ],
            ["Response reduction factor R", fmt(values["R"], 1)],
            ["Overstrength factor Ω0", fmt(values["omega"], 1)],
            ["Deflection amplification Cd", fmt(values["Cd"], 1)],
            ["Importance factor I (seismic)", fmt(values["seismicImportance"], 2)],
            ["Importance factor (wind)", fmt(values["windImportance"], 2)],
        ]
        basis["areaLoads"] = [
            [
                load.id,
                load.name,
                uses[load.use].name if load.use in uses else "Custom",
                fmt(load.live, 2),
                fmt(load.finish, 2),
                fmt(load.partitions, 2),
            ]
            for load in settings.areaLoads
        ]
        cases = ["D", "L", "Lr", "WX", "WY", "EX", "EY", "T"]
        used = [c for c in cases if any(getattr(k, c) for k in settings.combinations)]
        if any(a.get("name", "").startswith("F:") for a in model.get("analyses", [])):
            used.append("F")  # the fluid case, only in a model with equipment contents
        basis["combinations"] = {
            "columns": used,
            "rows": [
                [k.name, *(_factor(getattr(k, c) or 0.0) for c in used)]
                for k in settings.combinations
            ],
        }
        analysis = settings.analysis
        basis["modelling"] = [
            [
                "Slabs",
                "Meshed as shells"
                if analysis.slabs == "shells"
                else "Loads to beams (not in the stiffness)",
            ],
            ["Floor diaphragm", analysis.diaphragm.capitalize()],
            ["Shell mesh size", f"{fmt(analysis.meshSize, 0)} mm"],
            [
                "Construction sequence",
                "Self-weight applied storey by storey (linear sequential construction; D0: "
                "the same load applied at once)"
                if analysis.constructionSequence
                else "Off (all loads act on the completed building)",
            ],
            ["Column supports", _supports_text(parts.root, analysis)],
            ["Temperature case T", _thermal_text(analysis.thermal)],
        ]
    basis["materials"] = _materials(parts)
    basis["cases"] = []
    for analysis in model.get("analyses", []):
        if analysis.get("type", "Static") not in ("Static", "Staged"):
            continue
        code, _, description = str(analysis.get("name") or analysis.get("id")).partition(":")
        basis["cases"].append([code.strip(), description.strip() or code.strip()])
    run = []
    for entry in manifest.get("cases", []):
        label = RESULT_TYPES.get(entry.get("result_type"), str(entry.get("result_type")))
        if entry.get("stages"):
            label = f"Construction sequence ({len(entry['stages'])} stages)"
        if label not in run:
            run.append(label)
    basis["analyses"] = run
    return basis


def _supports_text(root: Path, analysis: Any) -> str:
    """How the column bases are supported, as the analysis model has them."""
    from saengine.fem.ssi_compare import on_springs, read_comparison

    if analysis.supports != "soilSprings":
        return "Fixed at the column and wall bases"
    if not on_springs(root):
        return (
            "Soil springs asked for, but the model was derived without them (no foundations in "
            "9 Substructure, or not derived again): fixed"
        )
    text = (
        "Soil springs (BNBC 2020 Part 6 Sec 1.2.7.3): each column base on its foundation of 9 "
        "Substructure, springs from the soil of 1 Soil Report (footings ASCE 41-06 Sec "
        "4.4.2.1.2, pile caps from their piles, rafts on subgrade springs); walls and columns "
        "without a foundation fixed. Foundations designed from the fixed-base run."
    )
    comparison = read_comparison(root)
    first = (comparison or {}).get("periods") or []
    if first and comparison and comparison.get("stale"):
        text += (
            " The fixed-base comparison is older than the analysis model or its results, so its "
            "periods are not quoted (8 FEM: Compare Fixed Base and Soil Springs; Run All runs it)."
        )
    elif first:
        mode = first[0]
        text += (
            f" First period {fmt(mode['fixed'], 3)} s fixed, {fmt(mode['ssi'], 3)} s on springs "
            f"(ratio {fmt(mode['ratio'], 3)})."
        )
    return text


def _thermal_text(thermal: Any) -> str:
    if not thermal.enabled:
        return "Off"
    where = "the roofs' beams and slabs" if thermal.scope == "roof" else "every member and shell"
    return (
        f"ΔTu = ±{fmt(abs(thermal.uniform), 0)} °C on {where}, roof gradient ΔTg = "
        f"{fmt(thermal.gradient, 0)} °C (the roofs: the horizontal beams and slabs with nothing "
        "above them, so stair or machine room roofs and the main roof around them; BNBC 2020 Part 6 Sec 2.6.4; T in 1.2(D + F + T) + "
        "1.6L + 0.5Lr, Sec 2.7.3.1); equivalent fixed-end forces, analysed without the rigid "
        "diaphragms"
    )


def _materials(parts: _Parts) -> list[list[str]]:
    """The materials the object types use (all concrete and rebar of the library when the
    object types cannot be read), with their design strengths."""
    library = parts.materials()
    if library is None:
        return []
    objects = parts.objects()
    used: set[str] | None = None
    if objects is not None:
        used = set()

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "material" and isinstance(item, str):
                        used.add(item)
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(objects.model_dump(mode="json"))
    rows = []
    for material in library.materials:
        category = material.category.value
        if used is not None and material.id not in used:
            continue
        if used is None and category not in ("concrete", "rebar"):
            continue
        if material.concrete is not None:
            strength = f"f'c = {fmt(material.concrete.fc, 1)} MPa"
        elif material.steel is not None:
            strength = f"fy = {fmt(material.steel.fy, 0)} MPa" + (
                f", fu = {fmt(material.steel.fu, 0)} MPa" if material.steel.fu else ""
            )
        elif material.masonry is not None and material.masonry.fm:
            strength = f"f'm = {fmt(material.masonry.fm, 1)} MPa"
        else:
            strength = "–"
        modulus = material.mechanical.E
        rows.append(
            [
                material.id,
                material.name,
                category.capitalize(),
                strength,
                f"{fmt(modulus, 0)} MPa" if modulus else "–",
            ]
        )
    return rows


def _recorded_sources(model: dict[str, Any]) -> dict[str, str]:
    description = str(model.get("meta", {}).get("description", ""))
    _, _, listed = description.partition("Sources:")
    sources = {}
    for item in listed.split(";"):
        key, _, value = item.strip().partition("=")
        if key and value:
            sources[key.strip()] = value.strip()
    return sources


def _model_summary(
    root: Path,
    model: dict[str, Any],
    manifest: dict[str, Any],
    parts: _Parts,
    warnings: list[str],
) -> dict[str, Any]:
    nodes = model.get("nodes", [])
    elements = model.get("elements", [])
    by_type: dict[str, int] = {}
    for element in elements:
        by_type[str(element.get("type", "?"))] = by_type.get(str(element.get("type", "?")), 0) + 1
    rows = [
        ["Nodes", fmt(len(nodes), 0)],
        ["Elements", fmt(len(elements), 0)],
        *[[f"  {kind}", fmt(count, 0)] for kind, count in sorted(by_type.items())],
        [
            "Fully fixed supports",
            fmt(sum(1 for n in nodes if all(n.get("restraint") or [False])), 0),
        ],
        ["Rigid diaphragms (constraints)", fmt(len(model.get("mp_constraints", [])), 0)],
        ["Load patterns", fmt(len(model.get("load_patterns", [])), 0)],
        ["Analysis cases", fmt(len(model.get("analyses", [])), 0)],
        ["Units of the analysis model", str(model.get("meta", {}).get("units", "–"))],
    ]
    summary: dict[str, Any] = {"rows": rows, "notes": [], "derived": []}

    # Is the model current, and are the results the model's?
    recorded = _recorded_sources(model)
    changed = [
        relative
        for key, relative in {**MODEL_SOURCES, **MODEL_OPTIONAL_SOURCES}.items()
        if key in recorded and parts.stamp(relative) != recorded[key]
    ]
    site = parts.site()
    if (
        site is not None
        and "soil" not in recorded
        and site["source"] == "soilReport"
        and site["class"] != site["entered"]
        and SOIL_FILE not in changed
    ):
        changed.append(SOIL_FILE)  # derived with the entered class before the boreholes gave one
    current = bool(recorded) and set(MODEL_SOURCES) <= set(recorded) and not changed
    if changed:
        warnings.append(
            "The analysis model was derived from earlier versions of "
            + ", ".join(changed)
            + ": derive it again and rerun the analysis before relying on this report."
        )
    manifest_file = root / RESULTS_DIR / "manifest.json"
    try:
        if (root / MODEL_FILE).stat().st_mtime > manifest_file.stat().st_mtime:
            warnings.append(
                "The analysis model was changed after the analysis ran: rerun the analysis."
            )
    except OSError:
        pass

    # The derivation's notes and code values are not stored in the model: derive it again from
    # the same files when they are unchanged.
    if current:
        derivation = _derive_again(root, parts)
        if derivation is not None:
            summary["notes"] = list(derivation.notes)
            values = derivation.summary
            for key, label, digits, unit in (
                ("levels", "Levels", 0, ""),
                ("weight_kN", "Seismic weight W", 1, "kN"),
                ("period_s", "Approximate period Ta = Ct·hn^m (Table 6.2.20)", 3, "s"),
                ("Cs", "Normalised spectral acceleration Cs", 3, ""),
                ("Sa_g", "Design spectral acceleration Sa", 4, "g"),
                ("base_shear_kN", "Equivalent static base shear V", 1, "kN"),
                ("wind_X_kN", "Total wind force in X", 1, "kN"),
                ("wind_Y_kN", "Total wind force in Y", 1, "kN"),
            ):
                if values.get(key) is not None:
                    text = fmt(values[key], digits)
                    summary["derived"].append([label, f"{text} {unit}".strip()])
            summary["derived"] += _derivation_rows(values, root)

    run_rows, run_warnings = [], []
    for entry in manifest.get("cases", []):
        early = bool(entry.get("early_stop"))
        steps = entry.get("completed_steps")
        run_rows.append(
            [
                str(entry.get("case_name", entry.get("case_id"))),
                "Construction sequence"
                if entry.get("stages")
                else RESULT_TYPES.get(entry.get("result_type"), str(entry.get("result_type"))),
                "–" if steps is None else str(steps),
                "Stopped early" if early else "Complete",
            ]
        )
        for warning in entry.get("warnings", []) or []:
            run_warnings.append(f"{entry.get('case_name')}: {warning}")
        if early:
            warnings.append(f"Analysis case {entry.get('case_name')} stopped early.")
    summary["run"] = run_rows
    summary["runWarnings"] = run_warnings
    return summary


def _derivation_rows(values: dict[str, Any], root: Path) -> list[list[str]]:
    """How W was formed (per level, what went to the base), the period used, the accidental
    torsion cases, the line loads on members and the mesh check, as label-value rows."""
    rows: list[list[str]] = []
    if values.get("periodMethod") == "analysis" and values.get("periodUsed_s") is not None:
        rows.append(
            [
                "Period used T (X)",
                (
                    f"{fmt(values['periodUsed_s'], 3)} s (modal, at most "
                    f"{fmt(values.get('periodCap_s') or 0, 3)} s = 1.4 Ta, BNBC 2020 Part 6 Sec "
                    "2.5.7.2 (a))"
                ),
            ]
        )
    weight = values.get("seismicWeight") or {}
    if weight.get("note"):
        rows.append(["Seismic weight W formed", str(weight["note"])])
    for level in weight.get("levels", []) or []:
        parts = level.get("parts_kN") or {}
        shown = ", ".join(f"{k} {fmt(v, 1)}" for k, v in parts.items() if v)
        rows.append(
            [
                f"W at {level.get('story') or fmt(level.get('z_m', 0), 2) + ' m'}",
                f"{fmt(level.get('weight_kN', 0), 1)} kN" + (f" ({shown})" if shown else ""),
            ]
        )
    if weight.get("toBase_kN"):
        rows.append(["Weight to the base (not in W)", f"{fmt(weight['toBase_kN'], 1)} kN"])
    torsion = values.get("accidentalTorsion")
    if torsion:
        rows.append(
            [
                "Accidental torsion",
                (
                    "static cases EXP, EXN, EYP, EYN: the story masses shifted ±5 % of the "
                    "building's width across the force (BNBC 2020 Part 6 Sec 2.5.7.6.2)"
                ),
            ]
        )
    loads = values.get("memberLoads") or []
    if loads:
        rows.append(
            [
                "Line and point loads on members",
                "; ".join(
                    f"{row['story']} {row['case']} {fmt(row['total_kN'], 1)} kN" for row in loads
                ),
            ]
        )
    from saengine.fem.mesh_check import MESH_CHECK_FILE

    try:
        check = json.loads((root / RESULTS_DIR / MESH_CHECK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        check = None
    if isinstance(check, dict) and check.get("note"):
        rows.append(["Mesh check", str(check["note"])])
    return rows


def _derive_again(root: Path, parts: _Parts) -> Any:
    from saengine.fem.derive import derive_fem
    from saengine.library import mep as mep_library
    from saengine.library import substructure as substructure_library
    from saengine.library.settings import read_soil_text

    inputs = (parts.building(), parts.objects(), parts.materials(), parts.settings())
    if any(value is None for value in inputs):
        return None
    try:
        from saengine.library import line_loads

        member_loads = line_loads.parse(parts.text(line_loads.LOADS_FILE))
        mep = mep_library.parse(parts.text(mep_library.MEP_FILE))
        springs = inputs[3].analysis.supports == "soilSprings"
        return derive_fem(
            *inputs,
            None,
            root / "08 FEM",
            mep=mep if (mep.equipment or mep.openings or mep.shafts) else None,
            substructure=substructure_library.parse(
                parts.text(substructure_library.SUBSTRUCTURE_FILE)
            )
            if springs
            else None,
            soil_text=read_soil_text(root) if springs else None,
            member_loads=member_loads if member_loads.loads else None,
        )
    except Exception as error:  # noqa: BLE001 - the report goes on without these notes
        parts.warnings.append(f"The derivation notes could not be recomputed: {error}")
        return None


# ─────────────────────────────────────── results ───────────────────────────────────────


def _results(
    model_path: Path,
    model: dict[str, Any],
    manifest: dict[str, Any],
    results_dir: Path,
    settings: Any,
    parts: _Parts,
    warnings: list[str],
) -> dict[str, Any]:
    from opensees_studio.services.result_store import load_results
    from opensees_studio.services.results import (
        ModalResults,
        ResponseSpectrumResults,
        StaticResults,
    )

    loaded: list[tuple[dict[str, Any], Any]] = []
    for entry in manifest.get("cases", []):
        try:
            loaded.append((entry, load_results(entry, results_dir)))
        except Exception as error:  # noqa: BLE001 - a missing or unreadable results file
            warnings.append(f"Results of {entry.get('case_name')} could not be read: {error}")

    out: dict[str, Any] = {"modal": None, "reactions": [], "displacements": [], "notes": []}

    # Modal periods, with the mass participation of the response spectrum cases.
    modal = next((r for _, r in loaded if isinstance(r, ModalResults)), None)
    if modal is not None:
        ratios: dict[int, dict[int, float]] = {}  # direction (1, 2) -> mode -> mass ratio
        for _, result in loaded:
            if isinstance(result, ResponseSpectrumResults) and result.direction in (1, 2):
                ratios[result.direction] = {m.mode_number: m.mass_ratio for m in result.modes}
        if not ratios:
            ratios = _mass_participation(model_path, modal)
        rows, cumulative = [], {1: 0.0, 2: 0.0}
        periods = np.asarray(modal.periods, dtype=float)
        for index, period in enumerate(periods[:MAX_MODES]):
            number = index + 1
            row = [str(number), fmt(period, 3), fmt(1 / period if period > 0 else None, 3)]
            for direction in (1, 2):
                if direction in ratios:
                    share = ratios[direction].get(number, 0.0)
                    cumulative[direction] += share
                    row += [fmt(100 * share, 1), fmt(100 * cumulative[direction], 1)]
            rows.append(row)
        columns = ["Mode", "T [s]", "f [Hz]"]
        for direction in (1, 2):
            if direction in ratios:
                axis = "X" if direction == 1 else "Y"
                columns += [f"Mass {axis} [%]", f"Σ {axis} [%]"]
        out["modal"] = {"columns": columns, "rows": rows}
        if len(periods) > MAX_MODES:
            out["notes"].append(f"The first {MAX_MODES} of {len(periods)} modes are listed.")

    # Base reactions of each static case.
    for entry, result in loaded:
        if not isinstance(result, StaticResults):
            continue
        total = np.zeros(3)
        for rows in result.node_reaction.values():
            if len(rows):
                total += np.asarray(rows[-1], dtype=float)[:3]
        out["reactions"].append([str(entry["case_name"]), *(fmt(v / 1e3, 1) for v in total)])

    # Displacements and story drifts of the lateral cases.
    out["displacements"] = _drifts(model, loaded, settings, parts)
    if out["displacements"]:
        out["notes"].append(
            "Story drift: the largest difference of the horizontal displacement in the load's "
            "direction between nodes on one plan position at consecutive story levels, divided "
            "by the story height (elastic, from the analysis). For earthquake cases the design "
            "drift Cd·δ/I is given too; compare it with the allowable story drift of BNBC 2020 "
            "Part 6 Chapter 2 for the occupancy category (not checked by SAEngine)."
        )
    out["seismicDesign"] = _seismic_design(model_path, results_dir, settings, warnings)
    if out["seismicDesign"].get("available") and out["displacements"]:
        out["notes"][-1] = out["notes"][-1].replace(
            " (not checked by SAEngine).",
            "; the design drifts of the response spectrum are checked below.",
        )
    out["secondOrder"] = _second_order(model, results_dir, settings, parts)
    return out


def _seismic_design(
    model_path: Path, results_dir: Path, settings: Any, warnings: list[str]
) -> dict[str, Any]:
    """The earthquake design from the response spectrum (``saengine.fem.seismic_design``): the
    scaling to the static base shear, the orthogonal rule, the accidental torsion, the
    combinations and the design drifts; ``{"available": False}`` when the design uses the
    static cases."""
    from saengine.design.check import ensure_seismic_design
    from saengine.fem import seismic_design as rs

    if settings is None or not rs.design_uses_spectrum(settings):
        return {"available": False, "static": True}
    try:
        summary = ensure_seismic_design(results_dir, model_path, settings)
    except Exception as error:  # noqa: BLE001 - the report goes on without it
        warnings.append(f"The response spectrum design could not be run: {error}")
        return {"available": False, "static": False}
    if not summary or not summary.get("available"):
        return {
            "available": False,
            "static": False,
            "notes": [str(n) for n in (summary or {}).get("notes", [])],
        }
    scale = summary["scale"]
    rows = []
    for axis in ("x", "y"):
        v_dyn = float(scale["vDynamic"][axis])
        if v_dyn <= 0:
            continue
        rows.append(
            [
                axis.upper(),
                fmt(scale["vStatic"][axis], 1),
                fmt(v_dyn, 1),
                fmt(100 * v_dyn / scale["vStatic"][axis], 1) if scale["vStatic"][axis] else "–",
                fmt(scale[axis], 3),
                fmt(100 * summary["massParticipation"][axis], 1),
            ]
        )
    torsion = []
    for axis, levels in (summary.get("torsion") or {}).items():
        for level in levels:
            if level.get("moment"):
                torsion.append(
                    [
                        f"E{axis}",
                        fmt(level["z"], 2),
                        fmt(abs(level["force"]) / 1e3, 1),
                        fmt(level["L"], 2),
                        fmt(level["moment"] / 1e3, 1),
                    ]
                )
    clauses = summary.get("clauses", {})
    orthogonal = (
        f"100 % + 30 %: E = EX + 0.3EY and 0.3EX + EY ({clauses.get('orthogonal', '')}); "
        "the 5 % shift of the mass in one direction at a time, the larger effect governing: "
        "AX or 0.3·AY with EX + 0.3EY, AY or 0.3·AX with 0.3EX + EY (BNBC 2020 Part 6 Sec "
        "2.5.7.6.3, p. 631)"
        if summary.get("orthogonal")
        else f"one direction at a time (Seismic Design Category {summary.get('category') or '–'}, "
        f"{clauses.get('orthogonal', '')})"
    )
    return {
        "available": True,
        "category": str(summary.get("category") or "–"),
        "fraction": fmt(100 * float(scale.get("fraction", 0.85)), 0),
        "clause": str(scale.get("clause", "")),
        "scale": rows,
        "orthogonal": orthogonal,
        "torsionClause": str(clauses.get("torsion", "")),
        "torsion": torsion,
        "vertical": fmt(summary.get("verticalCoefficient"), 3),
        "combinations": [
            [str(c["name"]), str(c.get("clause", ""))] for c in summary.get("combinations", [])
        ],
        "drift": rs.drift_rows(summary),
        "irregularity": rs.irregularity_rows(summary),
        "irregularityClause": str(clauses.get("irregularity", "")),
        "amplificationClause": str(clauses.get("amplification", "")),
        "torsionAmplification": ", ".join(
            f"{axis} {fmt(value, 3)}"
            for axis, value in sorted((summary.get("torsionAmplification") or {}).items())
        ),
        "driftFails": [not d["ok"] for d in summary.get("drift", [])],
        "amplification": fmt(summary.get("amplification"), 2),
        "notes": [str(n) for n in summary.get("notes", [])],
    }


def _analysed_stiffness(model: dict[str, Any], parts: _Parts) -> str:
    """The section stiffness the analysis model (``.osmodel``) was built with, read from the
    model itself: "lateral" when its lateral static cases (W*, E*, R*) carry cracked
    ``section_overrides`` (saengine.fem.second_order, crackedFor "lateral"), "all" when its
    frame sections themselves are cracked (found as saengine.design.slender.Model does,
    against the building members' profiles), else "gross"."""
    from saengine.design.slender import Model, is_lateral

    for case in model.get("analyses", []):
        code = str(case.get("name", "")).split(":")[0].strip()
        if case.get("type") == "Static" and case.get("section_overrides") and is_lateral(code):
            return "lateral"
    building, objects, materials = parts.building(), parts.objects(), parts.materials()
    if building is None or objects is None or materials is None:
        return "gross"
    try:
        found = Model(
            model,
            building,
            {o.id: o for o in objects.objects},
            None,
            {m.id: m for m in materials.materials},
        )
    except Exception:  # noqa: BLE001 - the description is optional; gross when unknown
        return "gross"
    return "all" if found.cracked_frames else "gross"


def _second_order(
    model: dict[str, Any], results_dir: Path, settings: Any, parts: _Parts
) -> dict[str, Any]:
    """The cracked stiffness and the P-Delta analysis (``saengine.fem.second_order``): the
    drift with and without P-Delta per storey and the stability coefficient θ."""
    from saengine.fem import second_order
    from saengine.library.settings import derived

    # What the analysed model used, not what the settings say now (they may have changed
    # since the run, and the results are not re-stamped on a settings change).
    cracked = _analysed_stiffness(model, parts)
    stiffness_text = (
        "cracked sections (BNBC 2020 Part 6 Sec 6.3.10.4.1: columns 0.70 Ig, beams 0.35 Ig, "
        "walls 0.70 Ig or 0.35 Ig, slabs 0.25 Ig) "
        + (
            "for every case"
            if cracked == "all"
            else "for the lateral cases (the gravity cases on the gross sections)"
        )
        if cracked in ("all", "lateral")
        else "gross sections"
    )
    out: dict[str, Any] = {
        "pDelta": second_order.is_second_order(model),
        "stiffness": stiffness_text,
        "rows": [],
        "fails": [],
        "notes": [],
    }
    if not out["pDelta"]:
        return out
    building = parts.building()
    special = building is not None and building.source is not None and building.source.structure
    levels = (
        sorted({s.elevation / 1e3 for s in building.stories})
        if building is not None and not special
        else None
    )
    values = derived(settings) if settings is not None else {}
    result = second_order.drift_amplification(
        model,
        results_dir,
        levels=levels,
        importance=values.get("seismicImportance"),
        cd=values.get("Cd"),
    )
    for case in result.get("cases", []):
        for s in case["storeys"]:
            theta, theta_max = s.get("theta"), s.get("thetaMax")
            out["rows"].append(
                [
                    str(case["case"]),
                    f"{fmt(s['from'], 2)} to {fmt(s['to'], 2)} m",
                    fmt(100 * s["firstOrder"], 3),
                    fmt(100 * s["secondOrder"], 3),
                    fmt(s["ratio"], 3) if s.get("ratio") else "–",
                    fmt(theta, 4) if theta is not None else "–",
                    fmt(theta_max, 3) if theta_max is not None else "–",
                ]
            )
            out["fails"].append(bool(theta is not None and theta_max and theta > theta_max))
    out["notes"] = [str(n) for n in result.get("notes", [])]
    return out


def _mass_participation(model_path: Path, modal: Any) -> dict[int, dict[int, float]]:
    """Mass ratios in X and Y of each mode, when no response spectrum case gives them."""
    try:
        from opensees_studio.services.persistence import load_project
        from opensees_studio.services.spectrum import mass_participation

        project = load_project(model_path)
        return {
            d: {m.mode_number: m.mass_ratio for m in mass_participation(project, modal, d)}
            for d in (1, 2)
        }
    except Exception:  # noqa: BLE001 - mass participation is optional in the report
        return {}


def _drifts(
    model: dict[str, Any], loaded: list[tuple[dict[str, Any], Any]], settings: Any, parts: _Parts
) -> list[list[str]]:
    from opensees_studio.services.results import StaticResults

    from saengine.fem.display import _code

    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in model.get("nodes", [])}
    if not coords:
        return []
    building = parts.building()
    special = (
        building is not None
        and building.source is not None
        and (building.source.structure is not None)
    )
    levels = (
        sorted({s.elevation / 1e3 for s in building.stories})
        if building is not None and not special
        else []
    )
    # Nodes on each story level, by plan position (mm).
    at_level: list[dict[tuple[int, int], int]] = []
    for z in levels:
        here = {}
        for node_id, xyz in coords.items():
            if abs(xyz[2] - z) < 1e-3:
                here[(round(xyz[0] * 1e3), round(xyz[1] * 1e3))] = node_id
        at_level.append(here)
    amplify = None
    if settings is not None:
        from saengine.library.settings import derived

        values = derived(settings)
        if values["Cd"] and values["seismicImportance"]:
            amplify = values["Cd"] / values["seismicImportance"]

    rows = []
    for entry, result in loaded:
        code = _code(str(entry.get("case_name", "")))
        if not isinstance(result, StaticResults) or code not in LATERAL_CASES:
            continue
        axis = LATERAL_CASES[code]

        def u(node_id: int, result: Any = result, axis: int = axis) -> float:
            rows_ = result.node_disp.get(node_id)
            return float(np.asarray(rows_[-1], dtype=float)[axis]) if rows_ is not None else 0.0

        largest = max((abs(u(n)) for n in coords), default=0.0)
        drift, where = None, ""
        for k in range(1, len(levels)):
            height = levels[k] - levels[k - 1]
            if height <= 0:
                continue
            for position, node in at_level[k].items():
                below = at_level[k - 1].get(position)
                if below is None:
                    continue
                ratio = abs(u(node) - u(below)) / height
                if drift is None or ratio > drift:
                    drift = ratio
                    where = f"{fmt(levels[k - 1], 2)} to {fmt(levels[k], 2)} m"
        design = (
            fmt(amplify * drift * 100, 3)
            if drift is not None and amplify and code.startswith("E")
            else "–"
        )
        rows.append(
            [
                str(entry["case_name"]),
                fmt(largest * 1e3, 2),
                fmt(drift * 100, 3) if drift is not None else "–",
                where or "–",
                design,
            ]
        )
    return rows


# ─────────────────────────────────────── design ───────────────────────────────────────


def _governing(element: dict[str, Any]) -> dict[str, Any] | None:
    checks = [c for c in element.get("checks", []) if not c.get("flag")]
    if not checks:
        checks = list(element.get("checks", []))
    return max(checks, key=lambda c: c.get("utilisation", 0.0), default=None)


def _result_label(check: dict[str, Any]) -> str:
    if check.get("ok"):
        return "OK"
    return "NOTE" if check.get("flag") else "FAIL"


def _kind_key(kind: str) -> tuple[int, str]:
    return (KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER), kind)


def _kind_title(kind: str) -> str:
    if kind in KIND_TITLES:
        return KIND_TITLES[kind]
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", kind).lower()
    return words[:1].upper() + words[1:] + "s"


def _design(results_dir: Path, model_path: Path, warnings: list[str]) -> dict[str, Any]:
    from saengine.pipeline.design_mode import checks

    try:
        report = checks(results_dir, model_path)  # Run All's design step's, while current
    except Exception as error:  # noqa: BLE001 - the report goes on without the design
        message = str(error) or type(error).__name__
        warnings.append(f"The member design could not be checked: {message}")
        return {"available": False, "problem": message, "notes": []}

    summary = report.get("summary", {})
    governing = summary.get("governing")
    max_util = summary.get("maxUtilisation")
    kinds: dict[str, list[dict[str, Any]]] = {}
    details = []
    for element in report.get("elements", []):
        kinds.setdefault(str(element.get("kind", "member")), []).append(element)
    tables = []
    for kind in sorted(kinds, key=_kind_key):
        rows, fails = [], []
        for element in kinds[kind]:
            check = _governing(element)
            ok = bool(element.get("ok"))
            rows.append(
                [
                    str(element.get("id")),
                    str(element.get("type", "")),
                    str(check.get("name", "")) if check else "–",
                    fmt(check.get("demand"), 1) if check else "–",
                    fmt(check.get("capacity"), 1) if check else "–",
                    str(check.get("unit", "")) if check else "",
                    # Three decimals: pass/fail is decided on the value rounded to 3 (check.py),
                    # so 1.004 must not print as "1.00" next to FAIL.
                    fmt(element.get("utilisation"), 3),
                    str(check.get("combination") or "–") if check else "–",
                    "OK" if ok else "FAIL",
                ]
            )
            fails.append(not ok)
        failed = sum(fails)
        tables.append(
            {
                "kind": kind,
                "title": _kind_title(kind),
                "count": len(rows),
                "failed": failed,
                "rows": rows,
                "fails": fails,
            }
        )
    for kind in sorted(kinds, key=_kind_key):
        for element in kinds[kind]:
            checks = element.get("checks", [])
            details.append(
                {
                    "id": str(element.get("id")),
                    "title": (
                        f"{element.get('id')} ({_kind_title(kind)[:-1].lower()}, type "
                        f"{element.get('type', '–')}): utilisation "
                        f"{fmt(element.get('utilisation'), 3)}, "
                        f"{'OK' if element.get('ok') else 'FAIL'}"
                    ),
                    "ok": bool(element.get("ok")),
                    "rows": [
                        [
                            str(c.get("name", "")),
                            fmt(c.get("demand"), 2),
                            fmt(c.get("capacity"), 2),
                            str(c.get("unit", "")),
                            fmt(c.get("utilisation"), 3),
                            str(c.get("combination") or "–"),
                            _result_label(c),
                            str(c.get("note", "")),
                        ]
                        for c in checks
                    ],
                    "fails": [_result_label(c) == "FAIL" for c in checks],
                }
            )
    slender_rows, slender_fails = [], []
    for element in report.get("elements", []):
        for c in element.get("checks", []):
            s = c.get("slenderness")
            if not isinstance(s, dict):
                continue
            magnified = (
                f"{fmt(s.get('M2'), 1)} → {fmt(s.get('M2magnified'), 1)}"
                if not s.get("neglected")
                else "neglected"
            )
            slender_rows.append(
                [
                    str(element.get("id")),
                    str(s.get("axis", "")),
                    str(s.get("storey") or "–"),
                    {True: "sway", False: "nonsway"}.get(s.get("sway"), "–"),
                    fmt(s.get("k"), 2),
                    fmt(s.get("klu_r"), 1),
                    fmt(s.get("limit"), 1),
                    fmt(s.get("deltaNs"), 2) if s.get("deltaNs") is not None else "–",
                    fmt(s.get("deltaS"), 2) if s.get("deltaS") is not None else "–",
                    magnified,
                ]
            )
            slender_fails.append(not c.get("ok", True) or bool(c.get("secondOrderRequired")))
    stability = [
        [
            str(r.get("storey") or "–"),
            f"{fmt(r.get('bottom'), 2)} to {fmt(r.get('top'), 2)} m",
            str(r.get("direction", "")),
            fmt(r.get("sumPu"), 0) if r.get("sumPu") is not None else "–",
            fmt(r.get("Vus"), 1) if r.get("Vus") is not None else "–",
            fmt(r.get("deltaO"), 2) if r.get("deltaO") is not None else "–",
            fmt(r.get("Q"), 4) if r.get("Q") is not None else "–",
            "sway" if r.get("sway") else "nonsway",
            fmt(r.get("deltaS"), 2) if r.get("deltaS") is not None else "–",
            str(r.get("combination") or "–"),
        ]
        for r in report.get("stability", [])
    ]
    walls = _walls(report)
    stairs = _stairs(report)
    lintels = _lintels(report)
    punching = _punching(report)
    steel = _steel(report)
    failed = int(summary.get("failed", 0) or 0)
    if failed:
        warnings.append(f"{failed} element(s) fail their design checks.")
    seismic = _seismic_detailing(report)
    if seismic["available"] and seismic["failedChecks"]:
        warnings.append(
            f"{seismic['failedChecks']} project-level seismic requirement(s) fail (system, "
            "materials): see Seismic detailing."
        )
    return {
        "seismic": seismic,
        "walls": walls,
        "stairs": stairs,
        "lintels": lintels,
        "punching": punching,
        "steel": steel,
        "slenderness": slender_rows,
        "slendernessFails": slender_fails,
        "stability": stability,
        "seismicFromSpectrum": any(
            "earthquake from the response spectrum" in str(n) for n in report.get("notes", [])
        ),
        "available": True,
        "code": str(report.get("code", "")),
        "summary": [
            ["Elements checked", str(summary.get("checked", 0))],
            ["Passed", str(summary.get("passed", 0))],
            ["Failed", str(failed)],
            ["Skipped", str(summary.get("skipped", 0))],
            ["Largest utilisation", fmt(max_util, 3) if max_util is not None else "–"],
            ["Governing element", str(governing) if governing else "–"],
        ],
        "failed": failed,
        "combinations": [str(c) for c in report.get("combinations", [])],
        "tables": tables,
        "skipped": [
            [str(s.get("id")), str(s.get("kind", "")), str(s.get("type", "")), str(s.get("reason"))]
            for s in report.get("skipped", [])
        ],
        "method": [str(line) for line in report.get("method", [])],
        "notes": [str(note) for note in report.get("notes", [])],
        "details": details,
    }


def _walls(report: dict[str, Any]) -> dict[str, Any]:
    """Integrator glue: the walls' piers and boundary elements (saengine.design.wall_design)."""
    piers, piers_bad, boundary, coupling, coupling_bad = [], [], [], [], []
    for element in report.get("elements", []):
        if element.get("kind") != "wall":
            continue
        for pier in element.get("piers", []) or []:
            check = _governing(pier)
            forces = pier.get("forces") or {}
            piers.append(
                [
                    str(element.get("id")),
                    str(pier.get("id")),
                    str(pier.get("storey") or "–"),
                    fmt(pier.get("lw"), 0),
                    fmt(pier.get("tw"), 0),
                    fmt(forces.get("P"), 1) if forces else "–",
                    fmt(forces.get("V2"), 1) if forces else "–",
                    fmt(forces.get("M3"), 1) if forces else "–",
                    str(check.get("name", "")) if check else "–",
                    fmt(pier.get("utilisation"), 3),
                    "OK" if pier.get("ok") else "FAIL",
                ]
            )
            piers_bad.append(not pier.get("ok"))
            b = pier.get("boundary")
            if b:
                if b.get("method") == "displacement":
                    test = f"c {fmt(b.get('c'), 0)} vs {fmt(b.get('trigger'), 0)} mm"
                else:
                    test = f"σ {fmt(b.get('stress'), 2)} MPa"
                boundary.append(
                    [
                        str(element.get("id")),
                        str(pier.get("id")),
                        str(b.get("method", "")),
                        test,
                        "required" if b.get("required") else "not required",
                        fmt(b.get("length"), 0) if b.get("length") else "–",
                        fmt(b.get("height"), 0) if b.get("height") else "–",
                    ]
                )
        for beam in element.get("couplingBeams", []) or []:
            check = _governing(beam)
            coupling.append(
                [
                    str(element.get("id")),
                    str(beam.get("id")),
                    f"{fmt(beam.get('ln'), 0)} / {fmt(beam.get('h'), 0)}",
                    "diagonal" if beam.get("diagonal") else "beam",
                    str(check.get("name", "")) if check else "–",
                    fmt(beam.get("utilisation"), 3),
                    "not designed"
                    if beam.get("ok") is None
                    else ("OK" if beam.get("ok") else "FAIL"),
                ]
            )
            coupling_bad.append(not beam.get("ok"))
    return {
        "piers": piers,
        "piersBad": piers_bad,
        "boundary": boundary,
        "coupling": coupling,
        "couplingBad": coupling_bad,
    }


def _steel(report: dict[str, Any]) -> dict[str, Any]:
    """Integrator glue: the steel members (saengine.design.steel_design) and their
    connections; a steel member's entry has a ``section`` with its ``family``."""
    rows, bad, connections, connections_bad = [], [], [], []
    for element in report.get("elements", []):
        section = element.get("section")
        if not isinstance(section, dict) or "family" not in section:
            continue
        own = [
            c
            for c in element.get("checks", [])
            if not str(c.get("name", "")).startswith("Connection: ")
        ]
        check = _governing({**element, "checks": own})
        ok = all(c.get("ok") for c in own if not c.get("flag"))
        rows.append(
            [
                str(element.get("id")),
                str(element.get("kind", "")),
                str(section.get("label", "")),
                str(element.get("material", "–")),
                str(section.get("class", "")),
                fmt(section.get("massPerMetre"), 1),
                str(element.get("lengths", "")),
                str(check.get("name", "")) if check else "–",
                fmt(check.get("utilisation"), 3) if check else "–",
                "OK" if ok else "FAIL",
            ]
        )
        bad.append(not ok)
        for connection in element.get("connections", []) or []:
            worst = _governing(connection)
            connections.append(
                [
                    str(element.get("id")),
                    str(connection.get("description") or connection.get("connection", "")),
                    str(worst.get("name", "")) if worst else "–",
                    fmt(connection.get("utilisation"), 3),
                    "OK" if connection.get("ok") else "FAIL",
                    "; ".join(str(a) for a in connection.get("assumptions", [])),
                ]
            )
            connections_bad.append(not connection.get("ok"))
    return {
        "members": rows,
        "membersBad": bad,
        "connections": connections,
        "connectionsBad": connections_bad,
    }


def _stairs(report: dict[str, Any]) -> dict[str, Any]:
    """Integrator glue: the stairs' flights and landings (saengine.design.stairs), per metre."""
    rows, bad = [], []
    for element in report.get("elements", []):
        if element.get("kind") != "staircase":
            continue
        for part in element.get("parts", []) or []:
            prefix = f"{part.get('name')}: "
            own = [
                c for c in element.get("checks", []) if str(c.get("name", "")).startswith(prefix)
            ]
            strength = [c for c in own if not c.get("flag")]
            utilisation = max((c.get("utilisation", 0.0) for c in strength), default=None)
            ok = all(c.get("ok") for c in strength)
            rows.append(
                [
                    str(element.get("id")),
                    str(part.get("name")),
                    str(part.get("kind", "")),
                    fmt(part.get("span"), 0),
                    fmt(part.get("h"), 0),
                    fmt(part.get("wu"), 2),
                    fmt(part.get("mu"), 2),
                    fmt(part.get("vu"), 2),
                    fmt(utilisation, 3) if utilisation is not None else "–",
                    "OK" if ok else "FAIL",
                ]
            )
            bad.append(not ok)
    return {"parts": rows, "partsBad": bad}


def _bars_text(bars: Any) -> str:
    if not bars:
        return "–"
    return f"{bars[0]} Ø{fmt(bars[1], 0)}"


def _lintels(report: dict[str, Any]) -> dict[str, Any]:
    """Integrator glue: the lintels over openings (saengine.design.lintels) with their bars."""
    rows, bad = [], []
    for element in report.get("elements", []):
        if element.get("kind") != "lintel":
            continue
        bars = element.get("bars") or {}
        links = bars.get("stirrups")
        loads = element.get("loads") or {}
        rows.append(
            [
                str(element.get("id")),
                str(element.get("host", "")),
                fmt(element.get("span"), 0),
                f"{fmt(element.get('b'), 0)} × {fmt(element.get('h'), 0)}",
                fmt(loads.get("Mu"), 2),
                fmt(loads.get("Vu"), 2),
                _bars_text(bars.get("bottom")),
                _bars_text(bars.get("top")),
                f"{links[0]}L Ø{fmt(links[1], 0)} @ {fmt(links[2], 0)}" if links else "–",
                fmt(element.get("utilisation"), 3),
                "OK" if element.get("ok") else "FAIL",
            ]
        )
        bad.append(not element.get("ok"))
    return {"rows": rows, "bad": bad}


def _punching(report: dict[str, Any]) -> dict[str, Any]:
    """Integrator glue: the punching shear reinforcement (saengine.design.punching) given or
    proposed at columns of flat slabs."""
    rows, bad = [], []
    for element in report.get("elements", []):
        for c in element.get("checks", []):
            r = c.get("shearReinforcement")
            if not str(c.get("name", "")).startswith("Punching at") or not isinstance(r, dict):
                continue
            rows.append(
                [
                    str(element.get("id")),
                    str(c.get("name", ""))[len("Punching at ") :],
                    "headed studs" if r.get("kind") == "studs" else "stirrups",
                    f"Ø{fmt(r.get('bar'), 0)}",
                    str(r.get("perLine")),
                    str(r.get("lines")),
                    f"{fmt(r.get('s0'), 0)} / {fmt(r.get('s'), 0)}",
                    fmt(c.get("utilisation"), 3),
                    _result_label(c),
                ]
            )
            bad.append(_result_label(c) == "FAIL")
    return {"rows": rows, "bad": bad}


DETAILING = "Detailing: "


def _scwb_text(scwb: Any) -> str:
    if not isinstance(scwb, dict) or scwb.get("ratio") is None:
        return "–"
    text = f"{scwb['ratio']:.2f}"
    return text + (" (n.r.)" if scwb.get("notRequired") else "")


def _seismic_detailing(report: dict[str, Any]) -> dict[str, Any]:
    """The "Seismic detailing" chapter (BNBC 2020 Part 6 Sec 8.3) from the design report's
    ``seismic`` scope, the members' ``Detailing:`` checks and ``joints``."""
    scope = report.get("seismic")
    if not isinstance(scope, dict) or not scope.get("detailingLevel"):
        return {"available": False, "failedChecks": 0}
    level = {"special": "Special", "intermediate": "Intermediate", "ordinary": "Ordinary"}
    lines = [
        ["Seismic Design Category", f"{scope.get('sdc') or '–'} (Sec 2.5.5.2, Table 6.2.18)"],
        ["Zone", str(scope.get("zone") or "–")],
        [
            "Structural system",
            f"{scope.get('systemName')} (Table 6.2.19 row {scope.get('systemRow') or '–'})",
        ],
        [
            "R, Ω0, Cd",
            f"{fmt(scope.get('R'), 2)}, {fmt(scope.get('Omega0'), 2)}, {fmt(scope.get('Cd'), 2)}",
        ],
        [
            "Detailing level",
            (
                f"{level.get(scope['detailingLevel'], scope['detailingLevel'])} (Sec 8.3.2; the "
                f"category requires {scope.get('requiredFrameType') or '–'}, the system's frames are "
                f"{scope.get('systemFrameType') or 'not part of the system'})"
            ),
        ],
    ]
    checks = scope.get("checks", [])
    check_rows = [[str(c.get("name")), _result_label(c), str(c.get("note", ""))] for c in checks]
    check_bad = [_result_label(c) == "FAIL" for c in checks]
    applies = [
        [
            k,
            str(v.get("title", "")),
            f"p. {v.get('page')}",
            "yes" if v.get("applies") else "no",
            str(v.get("members", "")) if v.get("applies") else "–",
        ]
        for k, v in scope.get("applies", {}).items()
    ]
    # Per object type: every detailing check that fails on any member, else the governing one.
    by_type: dict[tuple[str, str], dict[str, tuple[dict[str, Any], list[str]]]] = {}
    shears = []
    for element in report.get("elements", []):
        if element.get("kind") not in ("beam", "column"):
            continue
        key = (str(element.get("type")), str(element.get("kind")))
        found = by_type.setdefault(key, {})
        for c in element.get("checks", []):
            if not str(c.get("name", "")).startswith(DETAILING) or c.get("flag"):
                continue
            name = c["name"][len(DETAILING) :]
            worst, failing = found.get(name, (c, []))
            if c["utilisation"] >= worst["utilisation"]:
                worst = c
            if not c.get("ok"):
                failing = [*failing, str(element.get("id"))]
            found[name] = (worst, failing)
        detailing = element.get("detailing") or {}
        if detailing.get("Ve") is not None:
            phi = detailing.get("phiVn")
            shears.append(
                [
                    str(element.get("id")),
                    str(element.get("kind")),
                    fmt(detailing.get("Ve"), 1),
                    fmt(phi, 1) if phi is not None else "–",
                    fmt(detailing["Ve"] / phi, 3) if phi else "–",
                    "OK" if phi and detailing["Ve"] <= phi * 1.0005 else "FAIL",
                ]
            )
    member_rows, member_bad = [], []
    for (type_id, kind), found in sorted(by_type.items()):
        if not found:
            continue
        failing = [(n, w, f) for n, (w, f) in found.items() if f]
        chosen = failing or [
            max(((n, w, f) for n, (w, f) in found.items()), key=lambda x: x[1]["utilisation"])
        ]
        for name, worst, members in sorted(chosen, key=lambda x: -x[1]["utilisation"]):
            member_rows.append(
                [
                    type_id,
                    kind,
                    name,
                    fmt(worst.get("demand"), 1),
                    fmt(worst.get("capacity"), 1),
                    str(worst.get("unit", "")),
                    fmt(worst.get("utilisation"), 3),
                    ", ".join(members) if members else "–",
                ]
            )
            member_bad.append(bool(members))
    joints = report.get("joints", []) or []
    joint_rows = [
        [
            str(j.get("id")),
            str(j.get("type", "")),
            ", ".join(j.get("beams", [])),
            _scwb_text((j.get("scwb") or {}).get("x")),
            _scwb_text((j.get("scwb") or {}).get("y")),
            fmt((j.get("shear") or {}).get("Vj"), 1),
            fmt((j.get("shear") or {}).get("phiVn"), 1),
            fmt(j.get("utilisation"), 3),
            "OK" if j.get("ok") else "FAIL",
        ]
        for j in joints
    ]
    return {
        "available": True,
        "lines": lines,
        "checks": check_rows,
        "checksBad": check_bad,
        "failedChecks": sum(check_bad),
        "applies": applies,
        "members": member_rows,
        "membersBad": member_bad,
        "shears": shears,
        "shearsBad": [r[-1] == "FAIL" for r in shears],
        "joints": joint_rows,
        "jointsBad": [r[-1] == "FAIL" for r in joint_rows],
        "notes": [str(n) for n in scope.get("notes", [])]
        + (
            [
                (
                    "Sec 8.3.11 (foundations: column bars into the footing, grade beam ties, pile "
                    "confinement) is not checked yet: 9 Substructure designs the foundations without "
                    "it."
                )
            ]
            if scope.get("applies", {}).get("8.3.11", {}).get("applies")
            else []
        ),
    }


def _required(results_dir: Path, model_path: Path, warnings: list[str]) -> dict[str, Any]:
    """Design mode in the report: the steel each object type requires next to what is entered
    (one row per type, the location that governs), from the answer kept beside the results
    (:mod:`saengine.pipeline.design_mode`; worked out here when it is not current)."""
    from saengine.pipeline.design_mode import required, required_summary, required_tables

    try:
        result = required(results_dir, model_path)
    except Exception as error:  # noqa: BLE001 - the report goes on without the required steel
        message = str(error) or type(error).__name__
        warnings.append(f"The required reinforcement could not be worked out: {message}")
        return {"available": False}
    steel = required_summary(result)
    lines = []
    if steel["short"]:
        lines.append("Steel provided is less than required in " + ", ".join(steel["short"]) + ".")
    if steel["tooSmall"]:
        lines.append(
            "No practical bars make these sections work (a larger section is needed): "
            + ", ".join(steel["tooSmall"])
            + "."
        )
    if steel["otherFailures"]:
        lines.append(
            "Failing checks that bars do not fix (size or depth): "
            + ", ".join(steel["otherFailures"])
            + "."
        )
    if steel["assumed"]:
        lines.append(
            "No bars entered on " + ", ".join(steel["assumed"]) + ": only the steel required."
        )
    return {"available": True, "tables": required_tables(result), "lines": lines}


# ─────────────────────────────────────── soil and foundations ──────────────────────────────────


def _site_class_text(parts: _Parts) -> str:
    """The site class of the design basis, with where it comes from."""
    site = parts.site()
    if site is None:
        return "–"
    if site["source"] == "soilReport":
        return f"{site['class']}, from 1 Soil Report ({site['soil']['detail']})"
    return f"{site['class']} (entered)"


def _m(value: Any, digits: int = 1) -> str:
    """A length in mm printed in m."""
    return "–" if value is None else fmt(float(value) / 1e3, digits)


def _range(top: Any, bottom: Any) -> str:
    return f"{_m(top)}–{_m(bottom)}"


def _soil(parts: _Parts) -> dict[str, Any]:
    """The soil and foundations chapter: printed only when the soil report has boreholes."""
    from saengine.library.settings import resolve_settings_text
    from saengine.soil import soil_report
    from saengine.soil.report import parse

    text = parts.text(SOIL_FILE)
    if text is None:
        return {"available": False, "notes": []}
    report = parse(text)
    if isinstance(report, list):
        parts.warnings.append(
            f"The soil report ({SOIL_FILE}) has errors and is not printed: "
            + "; ".join(report[:3])
            + ("; …" if len(report) > 3 else "")
        )
        return {"available": False, "notes": []}
    if not report.boreholes:
        return {"available": False, "notes": []}
    data = soil_report(text, resolve_settings_text(parts.text(SETTINGS_FILE), text))
    if "problems" in data:
        parts.warnings.append(
            "The soil report could not be computed: " + "; ".join(data["problems"])
        )
        return {"available": False, "notes": []}
    boreholes = data["boreholes"]
    design = report.design

    info = report.report
    details = [
        [label, value]
        for label, value in (
            ("Report", info.title),
            ("Geotechnical consultant", info.consultant),
            ("Report number", info.reportNumber),
            ("Date", info.date),
        )
        if value
    ]
    pga = design.liquefaction.pga
    details += [
        ["Boreholes", str(len(boreholes))],
        ["Ground level (project datum)", f"{_m(report.groundLevel, 2)} m"],
        ["SPT hammer energy ratio", f"{fmt(design.hammerEnergy, 0)} %"],
        ["Factor of safety on bearing", fmt(design.factorOfSafety, 1)],
        ["Allowable settlement", f"{fmt(design.allowableSettlement, 0)} mm"],
        ["Earthquake magnitude (liquefaction)", fmt(design.liquefaction.magnitude, 1)],
        [
            "Peak ground acceleration amax",
            f"{fmt(data.get('amax'), 3)} g"
            + (" (entered)" if pga is not None else " (Z·S of the project settings)"),
        ],
    ]

    rows, strata = [], []
    for b in boreholes:
        site = b.get("siteClass") or {}
        n_bar = site.get("N")
        rows.append(
            [
                str(b["id"]),
                _m(b.get("x"), 2),
                _m(b.get("y"), 2),
                _m(b.get("groundLevel"), 2),
                _m(b.get("waterTable"), 2),
                _m(b.get("depth"), 1),
                str(len(b.get("layers", []))),
                str(len(b.get("profile") or [])),  # the corrected SPT records
                f"{site.get('class') or '–'}" + (f" (N̄ {fmt(n_bar, 1)})" if n_bar else ""),
            ]
        )
        for layer in b.get("layers", []):
            strata.append(
                [
                    str(b["id"]),
                    _range(layer.get("top"), layer.get("bottom")),
                    str(layer.get("soilType", "")),
                    str(layer.get("description", "")),
                    fmt(layer.get("unitWeight"), 1),
                    fmt(layer.get("cu"), 0) if layer.get("cu") else "–",
                    fmt(layer.get("phi"), 0) if layer.get("phi") else "–",
                    fmt(layer.get("N60"), 1),
                ]
            )

    # Site class: each borehole's averages, the governing class, and what the analysis uses.
    site_rows = []
    for b in boreholes:
        site = b.get("siteClass") or {}
        site_rows.append(
            [
                str(b["id"]),
                fmt(site.get("N"), 1),
                fmt(site.get("su"), 0),
                str(site.get("byN") or "–"),
                str(site.get("bySu") or "–"),
                str(site.get("class") or "–"),
                (
                    _m(site.get("depth"), 1)
                    + (" (extrapolated)" if site.get("extrapolated") else "")
                ),
            ]
        )
    used = parts.site()
    site_notes = [str(data["siteClass"].get("note", ""))]
    if used is not None:
        site_notes.append(
            f"The analysis uses site class {_site_class_text(parts)}."
            if used["source"] == "soilReport"
            else f"The analysis uses the entered site class {used['class']} (Project Settings → "
            "Site class source: Entered)."
        )
    for b in boreholes:
        site_notes += [f"{b['id']}: {n}" for n in (b.get("siteClass") or {}).get("notes", [])]

    # Allowable bearing: the lowest qa of the boreholes for each footing width and depth.
    cells: dict[tuple[float, float], list[Any]] = {}
    for b in boreholes:
        for row in b["bearing"]["table"]:
            cells.setdefault((row["B"], row["Df"]), []).append(row["qa"])
    widths = sorted({k[0] for k in cells})
    depths = sorted({k[1] for k in cells})

    def lowest(values: list[Any]) -> str:
        return "–" if not values or any(v is None for v in values) else fmt(min(values), 0)

    bearing_rows = [
        [f"{_m(width, 1)} m", *(lowest(cells.get((width, df), [])) for df in depths)]
        for width in widths
    ]
    reference = []
    for b in boreholes:
        ks = b.get("ksDetail") or {}
        row = next(
            (r for r in b["bearing"]["table"] if r["B"] == ks.get("B") and r["Df"] == ks.get("Df")),
            None,
        )
        reference.append(
            [
                str(b["id"]),
                f"{_m(ks.get('B'), 1)} × {_m(ks.get('Df'), 1)}",
                fmt(row["qa_shear"], 0) if row else "–",
                fmt(row["qa_settlement"], 0) if row else "–",
                fmt(row["qa"], 0) if row else "–",
                str(row["governs"]) if row and row.get("governs") else "–",
                fmt((b.get("settlement") or {}).get("total"), 1),
                fmt(b.get("ks"), 0),
            ]
        )
    bearing_notes = sorted({f"{b['id']}: {n}" for b in boreholes for n in b["bearing"]["notes"]})

    # Liquefaction screening.
    liquefaction_rows, liquefiable = [], []
    for b in boreholes:
        screen = b["liquefaction"]
        fs = [p["fs"] for p in screen.get("points", []) if p.get("fs") is not None]
        layers = "; ".join(
            f"{_range(layer['top'], layer['bottom'])} m {layer['soilType']}"
            for layer in screen.get("layers", [])
        )
        liquefiable.append(bool(screen.get("layers")))
        liquefaction_rows.append(
            [
                str(b["id"]),
                fmt(min(fs), 2) if fs else "–",
                fmt(screen.get("lpi"), 1),
                str(screen.get("category") or "–"),
                layers or "none",
            ]
        )
    # Notes every borehole shares (amax) once; the others with their borehole.
    own_notes = [set(map(str, b["liquefaction"].get("notes", []))) for b in boreholes]
    shared = set.intersection(*own_notes) if own_notes else set()
    liquefaction_notes = sorted(shared) + [
        f"{b['id']}: {n}"
        for b, notes in zip(boreholes, own_notes, strict=True)
        for n in sorted(notes - shared)
    ]

    notes = list(data.get("notes", []))
    for b in boreholes:
        notes += [f"{b['id']}: {n}" for n in b.get("notes", [])]
    return {
        "available": True,
        "details": details,
        "boreholes": rows,
        "strata": strata,
        "site": {
            "class": str(data["siteClass"].get("class") or "–"),
            "rows": site_rows,
            "notes": site_notes,
            "method": str(data["methods"].get("siteClass", "")),
        },
        "bearing": {
            "depths": [f"Df {_m(df, 1)} m" for df in depths],
            "rows": bearing_rows,
            "reference": reference,
            "notes": bearing_notes,
            "method": str(data["methods"].get("bearing", "")),
            "factorOfSafety": fmt(design.factorOfSafety, 1),
            "allowableSettlement": fmt(design.allowableSettlement, 0),
        },
        "liquefaction": {
            "rows": liquefaction_rows,
            "fails": liquefiable,
            "notes": liquefaction_notes,
            "method": str(data["methods"].get("liquefaction", "")),
        },
        "notes": notes,
    }


# ─────────────────────────────────────── foundations ───────────────────────────────────────

#: What the foundation design does not cover, printed with the chapter's limitations.
FOUNDATION_LIMITS = [
    (
        "The superstructure is analysed on fixed column bases (no soil-structure interaction): "
        "the foundations are designed for its support reactions, and their own settlement does "
        "not change the forces in the frame."
    ),
    (
        "Strip footings run along straight paths; their wall loads are spread along the wall. "
        "Settlement of tie beams is the value entered, not computed."
    ),
    (
        "Piles: no rock sockets, lateral load capacity or negative skin friction; square (driven) "
        "piles take the capacity of a round pile of the same size."
    ),
    (
        "Pile caps: deep caps are checked by a simplified strut-and-tie model (lever arm 0.9 d, "
        "no bottle-shaped struts); no diagonal shear at corner piles; tie bars must be anchored "
        "beyond the outer piles."
    ),
    (
        "Rafts: vertical loads only (no horizontal loads, no walls standing on the raft, no ground "
        "floor loads on it), on compression-only Winkler springs of the soil report's subgrade "
        "modulus."
    ),
]

FOUNDATION_TYPE_NAMES = {
    "isolated": "Isolated footing",
    "combined": "Combined footing",
    "strip": "Strip footing",
    "pileCap": "Pile cap",
    "raft": "Raft",
    "tieBeam": "Tie beam",
}


def _size_text(result: dict[str, Any]) -> str:
    sizes = result.get("sizes") or {}
    if "length" in sizes and "width" in sizes:
        text = f"{_m(sizes['length'], 2)} × {_m(sizes['width'], 2)}"
    elif "area" in sizes:
        text = f"{fmt(sizes['area'], 1)} m²"
    elif "width" in sizes:
        text = f"{_m(sizes['width'], 2)} wide"
    else:
        return "–"
    if "thickness" in sizes:
        text += f" × {_m(sizes['thickness'], 2)}"
    return text + " m"


def _check_rows(checks: list[dict[str, Any]]) -> tuple[list[list[str]], list[bool]]:
    rows = [
        [
            str(c.get("name", "")),
            fmt(c.get("demand"), 2),
            fmt(c.get("capacity"), 2),
            str(c.get("unit", "")),
            fmt(c.get("utilisation"), 3),
            str(c.get("combination") or "–"),
            _result_label(c),
            str(c.get("note", "")),
        ]
        for c in checks
    ]
    return rows, [_result_label(c) == "FAIL" for c in checks]


def _foundations(parts: _Parts) -> dict[str, Any]:
    """The foundations chapter: the design checks of 9 Substructure
    (:func:`saengine.substructure.substructure_report`)."""
    from saengine.substructure import substructure_report
    from saengine.substructure.handover import authoritative_substructure, needs_migration

    limits = list(FOUNDATION_LIMITS)
    text = parts.text(SUBSTRUCTURE_FILE)
    try:
        substructure = authoritative_substructure(text)
    except ValueError as error:
        message = f"9 Substructure ({SUBSTRUCTURE_FILE}) is not valid: {str(error).splitlines()[0]}"
        parts.warnings.append(message)
        return {"available": False, "message": message, "notes": [], "limits": limits}
    if substructure is None or not (substructure.foundations or substructure.tieBeams):
        if needs_migration(parts.root):
            message = (
                "The footings of the building model have not been moved to 9 Substructure yet, "
                "so no foundation is designed: open 9 Substructure or Run All."
            )
            parts.warnings.append(message)
        else:
            message = "The project has no foundations in 9 Substructure."
        return {"available": False, "message": message, "notes": [], "limits": limits}
    try:
        report = substructure_report(parts.root)
    except Exception as error:  # noqa: BLE001 - the report goes on without the foundations
        message = f"The foundations could not be designed: {error}"
        parts.warnings.append(message)
        return {"available": False, "message": message, "notes": [], "limits": limits}

    summary = report.get("summary", {})
    designed = report.get("foundations", []) + report.get("tieBeams", [])
    rows, fails = [], []
    for result in designed:
        check = _governing(result)
        kind = str(result.get("type", ""))
        rows.append(
            [
                str(result.get("id")),
                FOUNDATION_TYPE_NAMES.get(kind, kind),
                ", ".join(map(str, result.get("columns", []))) or "–",
                _size_text(result) if kind != "tieBeam" else "–",
                str(check.get("name", "")) if check else "–",
                fmt(result.get("utilisation"), 3),
                str(check.get("combination") or "–") if check else "–",
                "OK" if result.get("ok") else "FAIL",
            ]
        )
        fails.append(not result.get("ok"))

    pressures = []
    for result in report.get("foundations", []):
        pressure = result.get("pressure") or {}
        if pressure.get("net") is None:
            continue
        pressures.append(
            [
                str(result.get("id")),
                fmt(pressure.get("net"), 1),
                fmt(pressure.get("qa"), 1),
                str(pressure.get("combination") or "–"),
                str(pressure.get("source") or "–"),
            ]
        )

    capacities, pile_loads, tables, seen = [], [], [], set()
    for result in report.get("foundations", []):
        pile = result.get("pile")
        if not isinstance(pile, dict):
            continue
        factors = pile.get("factors") or {}
        sizes = result.get("sizes") or {}
        capacities.append(
            [
                str(result.get("id")),
                str(sizes.get("pileType", "–")),
                str(pile.get("kind", "")),
                str(pile.get("borehole") or "–"),
                fmt(pile.get("diameter"), 0),
                _m(pile.get("length"), 1),
                fmt(pile.get("Qs"), 0),
                fmt(pile.get("Qb"), 0),
                fmt(pile.get("Qult"), 0),
                fmt(factors.get("compression"), 1),
                fmt(pile.get("Qa"), 0),
                fmt(pile.get("Ta"), 0),
            ]
        )
        for p in result.get("piles", []):
            pile_loads.append(
                [
                    f"{result.get('id')}/{p.get('index')}",
                    fmt(p.get("u"), 0),
                    fmt(p.get("v"), 0),
                    fmt(p.get("serviceMax"), 1),
                    fmt(p.get("serviceMin"), 1),
                    fmt(p.get("strengthMax"), 1),
                    fmt(p.get("strengthMin"), 1),
                    fmt(pile.get("Qa"), 0),
                ]
            )
        table = result.get("capacityTable")
        key = (
            (table.get("borehole"), table.get("kind"), table.get("method"))
            if isinstance(table, dict)
            else None
        )
        if key and key not in seen and table.get("rows"):
            seen.add(key)
            diameters = [float(d) for d in table.get("diameters", [])]
            lengths = [float(length) for length in table.get("lengths", [])]
            qa = {(float(r["D"]), float(r["L"])): r.get("Qa") for r in table["rows"]}
            tables.append(
                {
                    "title": (
                        f"{str(table.get('kind', '')).capitalize()} piles at "
                        f"{table.get('borehole') or '–'}, head at {_m(table.get('head'), 1)} m "
                        "depth: allowable load Qa [kN]"
                    ),
                    "diameters": [f"D {fmt(d, 0)}" for d in diameters],
                    "rows": [
                        [f"L {_m(length, 1)} m"] + [fmt(qa.get((d, length)), 0) for d in diameters]
                        for length in lengths
                    ],
                }
            )

    rafts = []
    for result in report.get("foundations", []):
        raft = result.get("raft")
        if not isinstance(raft, dict):
            continue
        s = raft.get("summary") or {}
        pressure = result.get("pressure") or {}
        rafts.append(
            [
                str(result.get("id")),
                fmt(raft.get("ks"), 0),
                fmt(raft.get("meshSize"), 0),
                fmt(pressure.get("net"), 1),
                fmt(pressure.get("qa"), 1),
                fmt(s.get("maxPressure"), 1),
                fmt(s.get("maxSettlement"), 1),
                fmt(s.get("maxDifferential"), 1),
                fmt((s.get("maxAngularDistortion") or 0) * 1e3, 2)
                if s.get("maxAngularDistortion") is not None
                else "–",
            ]
        )

    details = []
    for result in designed:
        checks = list(result.get("checks", []))
        check_rows, check_fails = _check_rows(checks)
        kind = str(result.get("type", ""))
        details.append(
            {
                "title": (
                    f"{result.get('id')} ({FOUNDATION_TYPE_NAMES.get(kind, kind).lower()}): "
                    f"utilisation {fmt(result.get('utilisation'), 3)}, "
                    f"{'OK' if result.get('ok') else 'FAIL'}"
                ),
                "ok": bool(result.get("ok")),
                "rows": check_rows,
                "fails": check_fails,
            }
        )

    failed = int(summary.get("failed", 0) or 0)
    if failed:
        parts.warnings.append(f"{failed} foundation(s) or tie beam(s) fail their design checks.")
    if not summary.get("analysed", True):
        parts.warnings.append("The foundations are not designed: there are no analysis results.")
    max_util = summary.get("maxUtilisation")
    governing = summary.get("governing")
    return {
        "available": True,
        "summary": [
            ["Foundations and tie beams checked", str(summary.get("checked", 0))],
            ["Passed", str(summary.get("passed", 0))],
            ["Failed", str(failed)],
            ["Not designed", str(summary.get("skipped", 0))],
            ["Largest utilisation", fmt(max_util, 3) if max_util is not None else "–"],
            ["Governing", str(governing) if governing else "–"],
        ],
        "failed": failed,
        "rows": rows,
        "fails": fails,
        "pressures": pressures,
        "capacities": capacities,
        "pileLoads": pile_loads,
        "capacityTables": tables,
        "rafts": rafts,
        "details": details,
        "skipped": [
            [
                str(s.get("id")),
                FOUNDATION_TYPE_NAMES.get(str(s.get("type")), str(s.get("type"))),
                str(s.get("reason")),
            ]
            for s in report.get("skipped", [])
        ],
        "combinations": {
            "service": [str(c) for c in report.get("combinations", {}).get("service", [])],
            "strength": [str(c) for c in report.get("combinations", {}).get("strength", [])],
        },
        "method": [str(line) for line in report.get("method", [])],
        "notes": [str(note) for note in report.get("notes", [])],
        "limits": limits,
    }


# ─────────────────────────────────────── bill of quantities ───────────────────────────────────


#: What the MEP checks write of an opening whose shear and flexure (or punching) checks did not
#: run, so only its size and spacing were checked (as the MEP editor reads them).
_STRENGTH_SKIPPED = re.compile(
    r"no analysis results|not found in the analysis results|\bis not checked\b|are not checked"
    r"|\(no results\)",
    re.IGNORECASE,
)


def opening_strength_checked(opening: dict[str, Any], general: list[str] | None = None) -> bool:
    """Whether the strength checks of an opening of ``saengine.mep.mep_report`` ran: its own
    ``strengthChecked`` when given, else none of its notes (nor the report's general ``notes``
    about the openings) says they were skipped."""
    flag = opening.get("strengthChecked")
    if isinstance(flag, bool):
        return flag
    if not opening.get("checked", True):
        return False
    texts = [str(opening.get("note") or ""), *(str(n) for n in opening.get("notes") or [])]
    texts += [str(c.get("note") or "") for c in opening.get("checks") or [] if isinstance(c, dict)]
    texts += [n for n in general or [] if "at the openings" in n]
    return not any(_STRENGTH_SKIPPED.search(text) for text in texts)


def _mep(parts: _Parts) -> dict[str, Any]:
    """The MEP coordination chapter: equipment loads, sleeve and opening checks, clashes
    (:func:`saengine.mep.mep_report`); not printed while 07 MEP has nothing."""
    from saengine.library.mep import MEP_FILE, parse
    from saengine.mep import mep_report

    try:
        mep = parse(parts.text(MEP_FILE))
    except ValueError as error:
        return {"available": False, "problem": f"{MEP_FILE} is not valid: {error}", "notes": []}
    if not (mep.equipment or mep.openings or mep.shafts or mep.ifcModels):
        return {"available": False, "problem": "", "notes": []}
    try:
        report = mep_report(parts.root)
    except ValueError as error:
        return {"available": False, "problem": str(error), "notes": []}

    def loads(entry: dict[str, Any]) -> str:
        return " + ".join(f"{case} {fmt(value, 1)}" for case, value in entry["loads"].items())

    equipment = [
        [
            e["id"],
            e["name"],
            e["story"],
            e.get("host") or "–",
            loads(e),
            fmt(e["load"], 1),
            fmt(e["pressure"], 1),
        ]
        for e in report["equipment"]
    ]
    general = [str(n) for n in report["notes"]]

    def result(o: dict[str, Any]) -> str:
        if not o["checked"]:
            return "Not checked"
        if not o["ok"]:
            return "FAIL"
        return "OK" if opening_strength_checked(o, general) else "Size OK, strength not checked"

    openings = [
        [
            o["id"],
            o["host"],
            f"{o['kind']}{' (' + o['service'] + ')' if o.get('service') else ''}",
            o.get("check") or "–",
            f"{o['utilisation']:.3f}" if o["checked"] else "–",
            result(o),
        ]
        for o in report["openings"]
    ]
    partial = sum(1 for row in openings if row[-1].startswith("Size OK"))
    clashes = [
        [
            c["id"],
            c.get("mepName") or c.get("mep") or "",
            c.get("structural") or "",
            c.get("kind", ""),
            c.get("status", ""),
            c.get("note") or "",
        ]
        for c in report["clashes"]
    ]
    summary = report["summary"]
    rows = [
        ["Equipment", str(summary["equipment"])],
        [
            "Equipment loads [kN]",
            " + ".join(f"{k} {fmt(v, 1)}" for k, v in summary["loads"].items()) or "–",
        ],
        [
            "Sleeves and openings",
            f"{summary['openings']} ({summary['openingsFailed']} fail"
            + (f", {partial} strength not checked" if partial else "")
            + ")",
        ],
        ["Hard clashes open", str(summary["clashes"])],
        ["Clashes coordinated", str(summary["coordinated"])],
    ]
    return {
        "available": True,
        "problem": "",
        "summary": rows,
        "equipment": equipment,
        "openings": openings,
        "openingFails": [r[-1] == "FAIL" for r in openings],
        "clashes": clashes,
        "clashOpen": [c.get("status") == "clash" for c in report["clashes"]],
        "failed": summary["openingsFailed"],
        "partial": partial,
        "open": summary["clashes"],
        "method": [str(m) for m in report["method"]],
        "notes": list(report["notes"]) + [str(p) for p in report["problems"]],
    }


#: The tank design's method, as :mod:`saengine.plumbing.tanks` documents it (shortened).
TANK_METHOD = [
    (
        "Tanks: a box of elastic shells (OpenSees Studio ASDShellQ4), an overhead tank pinned "
        "along its walls' lines, a ground tank on Winkler springs (compression only where the "
        "base lifts off; held along its walls where the net load is upward). Loads: D (self "
        "weight, roof finish), F (water to the overflow, each compartment alone too), H (earth "
        "pressure at rest K0 = 1 - sin φ' with the soil report's layers, the full hydrostatic "
        "pressure below the design water table and the uplift on the base, BNBC 2020 Part 6 "
        "Sec 2.6.5), Lr (roof live load, Table 6.2.3)."
    ),
    (
        "Combinations: BNBC 2020 Part 6 Sec 2.7.3.1 (strength) and Sec 2.7.2.1 (service), with "
        "each load not acting investigated. Design per metre: Wood-Armer moments with the "
        "membrane tension (ACI 318-19 flexure with axial tension), one-way shear with the axial "
        "tension term (ACI 318-19 Table 22.5.5.1), minimum bars for early thermal restraint and "
        "BNBC Sec 6.6.3 for walls, crack widths after EN 1992-1-1 7.3.4 against 0.2 mm, covers "
        "BNBC Part 6 Sec 8.1.7; ground tanks: flotation (factor of safety 1.1), net bearing and "
        "settlement (Table 6.3.8)."
    ),
    (
        "Hydraulics: the water network of each riser solved with WNTR (EPANET 2.2), Hazen-"
        "Williams friction, against the residual heads of Table 8.5.6 and the 35 m static limit "
        "(Sec 5.11); the delivery pump at the peak hourly demand (Sec 5.9.1.2(c)(ii)) and its "
        "head by Sec 5.10.5."
    ),
]


def _plumbing(parts: _Parts) -> dict[str, Any]:
    """The plumbing chapter (Part 7, BNBC 2020 Part 8): demand, storage, the sizes the
    structure coordinates with (risers, stacks, tanks, sleeves), the tanks' RC design, the
    hydraulics and the septic tank (:func:`saengine.plumbing.project.full_report`); not printed
    while 07 MEP has no plumbing."""
    from saengine.library.mep import MEP_FILE, PLUMBING_SYSTEMS, TANK_KINDS, parse
    from saengine.plumbing.project import full_report, plumbing_failures

    empty = {"available": False, "problem": "", "notes": []}
    try:
        mep = parse(parts.text(MEP_FILE))
    except ValueError as error:
        return {**empty, "problem": f"{MEP_FILE} is not valid: {error}"}
    p = mep.plumbing
    if p is None or not (p.stories or p.risers or p.tanks):
        return empty
    report = full_report(parts.root)
    if "demand" not in report:
        return {**empty, "problem": "; ".join(str(x) for x in report.get("problems") or [])}

    def result(ok: Any) -> str:
        return "OK" if ok else "FAIL"

    def checked(rows: list[dict[str, Any]]) -> list[list[str]]:
        return [
            [
                str(c.get("name") or ""),
                fmt(c.get("demand"), 2),
                fmt(c.get("capacity"), 2),
                str(c.get("unit") or ""),
                fmt(c.get("utilisation"), 2) if c.get("utilisation") is not None else "–",
                result(c.get("ok")),
            ]
            for c in rows
        ]

    demand = report["demand"]
    stories = [
        [
            s["story"],
            str(s.get("occupancy") or ""),
            fmt(s.get("population"), 0),
            fmt(s.get("lpcd"), 0),
            fmt(s.get("daily"), 0),
            fmt(s.get("supplyUnits"), 1),
            fmt(s.get("drainageUnits"), 1),
        ]
        for s in demand["stories"]
    ]
    storage = report["storage"] or {}
    tanks_required = [
        [
            t["id"],
            TANK_KINDS.get(t["kind"], t["kind"]),
            fmt(t.get("required"), 2),
            fmt(t.get("provided"), 2),
            fmt(t.get("drain"), 0),
            fmt(t.get("overflow"), 0),
            result((t.get("provided") or 0) >= (t.get("required") or 0) - 1e-9),
        ]
        for t in storage.get("tanks") or []
    ]
    risers = [
        [
            r["id"],
            PLUMBING_SYSTEMS.get(r["system"], r["system"]),
            fmt(r.get("units"), 1),
            fmt(r.get("flow"), 1),
            fmt(r.get("diameter"), 0),
            fmt(r.get("required"), 0),
            result(r.get("ok")),
        ]
        for r in report["risers"]
    ]
    designs = []
    for d in report.get("tankDesigns") or []:
        if "error" in d:
            designs.append(
                {"id": str(d.get("id")), "title": str(d.get("id")), "error": d["error"],
                 "rows": [], "checks": [], "bad": []}
            )  # fmt: skip
            continue
        g = d["geometry"]
        diameters = {t.id: t.diameter for t in p.tanks}
        size = (
            f"Ø{fmt(diameters.get(d['id']), 0)} x {fmt(g['height'], 0)} mm inside"
            if d["kind"] == "soakWell"
            else f"{fmt(g['length'], 0)} x {fmt(g['width'], 0)} x {fmt(g['height'], 0)} mm inside"
        )
        rows = [
            ["Kind", TANK_KINDS.get(d["kind"], d["kind"])],
            ["Size", size],
            [
                "Walls, base, roof",
                (
                    f"{fmt(g.get('walls'), 0)}, {fmt(g.get('base'), 0)}, "
                    f"{fmt(g.get('roof'), 0) if g.get('roof') else 'open'} mm"
                ),
            ],
            [
                "Concrete, reinforcement",
                (
                    f"{g.get('concrete')} (f'c {fmt(g.get('fc'), 1)} MPa), "
                    f"{g.get('rebar')} (fy {fmt(g.get('fy'), 0)} MPa)"
                ),
            ],
        ]
        q = d.get("quantities") or {}
        if q:
            rows.append(
                [
                    "Quantities",
                    (
                        f"{fmt(q.get('concrete'), 2)} m³ concrete, {fmt(q.get('formwork'), 1)} "
                        f"m² formwork, {fmt(q.get('reinforcement'), 0)} kg bars"
                    ),
                ]
            )
        support = d.get("supportLoads")
        if support:
            rows.append(
                [
                    "On the structure",
                    (
                        f"{fmt(support['empty'], 1)} kN empty (SD), {fmt(support['water'], 1)} "
                        f"kN water (F), {fmt(support['roofLive'], 1)} kN roof live; "
                        f"{fmt(support['pressureFull'], 1)} kPa full over the footprint"
                    ),
                ]
            )
        uplift = d.get("uplift")
        if uplift:
            rows.append(
                [
                    "Flotation",
                    (
                        f"FS {fmt(uplift.get('FS'), 2)} (at least "
                        f"{fmt(uplift.get('required'), 2)}): {result(uplift.get('ok'))}"
                    ),
                ]
            )
        failing = [c for c in d.get("checks") or [] if c.get("ok") is False]
        governing = sorted(d.get("checks") or [], key=lambda c: -(c.get("utilisation") or 0.0))[:6]
        shown = failing + [c for c in governing if c not in failing]
        designs.append(
            {
                "id": d["id"],
                "title": f"{d['id']}: {TANK_KINDS.get(d['kind'], d['kind'])}",
                "error": "",
                "rows": rows,
                "checks": checked(shown),
                "bad": [c.get("ok") is False for c in shown],
                "count": len(d.get("checks") or []),
                "failed": len(failing),
            }
        )
    hyd = report.get("hydraulics") or {}
    floors = [
        [
            str(f.get("name") or f.get("story")),
            str(f.get("riser") or ""),
            fmt(f.get("fixtureElevation"), 2),
            fmt(f.get("head"), 2),
            fmt(f.get("required"), 2),
            fmt(f.get("staticHead"), 2),
            result(f.get("ok")),
        ]
        for f in sorted(hyd.get("floors") or [], key=lambda f: -(f.get("elevation") or 0.0))
    ]
    pump = hyd.get("pump") or {}
    septic = report.get("septic")
    septic_rows = []
    if septic:
        septic_rows = [
            ["Users", fmt(septic.get("persons"), 0)],
            ["Liquid volume needed", f"{fmt((septic.get('volume') or 0) / 1000, 2)} m³"],
            [
                "Provided",
                (
                    f"{fmt((septic.get('provided') or 0) / 1000, 2)} m³ in "
                    f"{septic.get('count', 1)} tank(s)"
                ),
            ],
        ]
        well = septic.get("soakWell") or {}
        if well:
            septic_rows.append(
                [
                    "Soak well",
                    "; ".join(str(n) for n in (well.get("notes") or [])[:2])
                    or (
                        f"Ø{fmt(well.get('diameter'), 0)}, {fmt(well.get('waterDepth'), 0)} mm "
                        "effective depth"
                    ),
                ]
            )
    failed, low = plumbing_failures(report)
    checks = list(report["checks"]) + list(hyd.get("checks") or [])
    summary = [
        ["Demand", report["summary"][0]],
        ["Storage", report["summary"][1]],
        [
            "Risers and stacks",
            f"{len(report['risers'])}; sleeves missing: {len(report['sleeves'])}",
        ],
        [
            "Pump",
            f"{fmt(pump.get('flowM3h'), 2)} m³/h at {fmt(pump.get('tdh'), 1)} m"
            if pump
            else report["summary"][2],
        ],
        ["Tanks designed", str(sum(1 for d in designs if not d["error"]))],
        ["Checks failing", str(failed)],
        ["Floors below the minimum pressure", str(low)],
    ]
    notes = [str(n) for n in report.get("notes") or []]
    notes += [f"Hydraulics: {n}" for n in hyd.get("notes") or []]
    for d in report.get("tankDesigns") or []:
        notes += [f"{d.get('id')}: {n}" for n in d.get("notes") or []]
    notes += [str(x) for x in report.get("problems") or []]
    notes += [str(x) for x in hyd.get("problems") or []]
    return {
        "available": True,
        "problem": "",
        "summary": summary,
        "stories": stories,
        "tanksRequired": tanks_required,
        "risers": risers,
        "designs": designs,
        "floors": floors,
        "floorFails": [row[-1] == "FAIL" for row in floors],
        "septic": septic_rows,
        "checks": checked(checks),
        "checkFails": [c.get("ok") is False for c in checks],
        "failed": failed,
        "low": low,
        "method": [*(str(m) for m in report.get("method") or []), *TANK_METHOD],
        "notes": notes,
    }


def _guarded(chapter: Any, parts: _Parts, label: str) -> dict[str, Any]:
    """A services chapter, or a note why it could not be written (never fails the report)."""
    try:
        return chapter(parts)
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the report
        return {"available": False, "problem": f"the {label} chapter failed: {error}", "notes": []}


def _service_checks(rows: list[dict[str, Any]]) -> list[list[str]]:
    """Checks ``{name, demand, capacity, unit, utilisation, ok}`` as the report's table rows."""
    return [
        [
            str(c.get("name") or ""),
            fmt(c.get("demand"), 2),
            fmt(c.get("capacity"), 2),
            str(c.get("unit") or ""),
            fmt(c.get("utilisation"), 2) if c.get("utilisation") is not None else "–",
            "OK" if c.get("ok") else "FAIL",
        ]
        for c in rows
    ]


def _service_loads(parts: _Parts, mep: Any, discipline: str) -> dict[str, dict[str, Any]]:
    """The items of one of 7 MEP's disciplines (``hvac``, ``electrical``) as the analysis takes
    their weights (:func:`saengine.mep.loads.services_by_discipline`): the item's own id ->
    ``{id, operatingWeight, emptyWeight, vibrating}``."""
    from saengine.mep.loads import services_by_discipline

    try:
        groups, _ = services_by_discipline(mep, parts.materials())
    except Exception:  # noqa: BLE001 - the chapter still prints, without the load column
        return {}
    return {k: e.model_dump(mode="json") for k, e in groups.get(discipline, {}).items()}


def _same_id(mep: Any, item_id: str) -> str | None:
    """The 07 MEP equipment that has a service item's id (it carries the item's weight)."""
    ids = {f"EQ-{item_id}", item_id}
    return next((e.id for e in mep.equipment if e.id in ids), None)


def _load_note(item_id: str, loaded: dict[str, dict[str, Any]], link: str | None) -> str:
    if link:
        return f"as equipment {link}"
    entry = loaded.get(item_id)
    if entry is None:
        return "not loaded (see the notes)"
    empty = entry.get("emptyWeight")
    return (
        f"{fmt(entry['operatingWeight'], 1)} kN"
        + (f" ({fmt(empty, 1)} kN SD + contents F)" if empty else " SD")
        + (", impact L" if entry.get("vibrating") else "")
    )


def _hvac(parts: _Parts) -> dict[str, Any]:
    """The HVAC coordination chapter (Part 7, BNBC 2020 Part 8 Chapter 2): the cooling loads
    (EnergyPlus version 26.2.0's cached run of this input, else the estimate: EnergyPlus is
    not started by the report), the plant with its weights on the structure, the ducts' openings
    through beams and slabs with their checks, the shafts; not printed while 07 MEP has no
    hvac."""
    from saengine.hvac.air import hvac_air
    from saengine.hvac.report import hvac_loads
    from saengine.library.mep import HVAC_PLANT_KINDS, HVAC_SYSTEMS, MEP_FILE, parse

    empty = {"available": False, "problem": "", "notes": []}
    try:
        mep = parse(parts.text(MEP_FILE))
    except ValueError as error:
        return {**empty, "problem": f"{MEP_FILE} is not valid: {error}"}
    hvac = mep.hvac
    if hvac is None:
        return empty
    loads = hvac_loads(parts.root, run_energyplus=False)
    try:
        air = hvac_air(parts.root, loads=loads)
    except Exception as error:  # noqa: BLE001
        air = {"checks": [], "notes": [], "problems": [f"the air side failed: {error}"]}
    loaded = _service_loads(parts, mep, "hvac")
    zones = [
        [
            str(z.get("story")),
            fmt(z.get("area"), 1),
            fmt(z.get("sensible"), 2),
            fmt(z.get("latent"), 2),
            fmt(z.get("total"), 2),
            fmt(z.get("airflow"), 3),
            fmt(z.get("outdoorAir"), 3),
            " ".join(
                str(x) for x in ((z.get("peak") or {}).get("month"), (z.get("peak") or {}).get("time"))
                if x is not None
            ) or "–",
        ]
        for z in loads.get("zones") or []
    ]  # fmt: skip
    plant = []
    for p in hvac.plant:
        size = " x ".join(fmt(v, 0) for v in (p.length, p.width, p.height) if v) or "typical"
        plant.append(
            [
                p.id,
                HVAC_PLANT_KINDS.get(p.kind, p.kind),
                p.story,
                size,
                fmt(p.capacity, 1 if p.kind not in ("exhaustFan", "freshAirUnit") else 2),
                fmt(p.operatingWeight, 1),
                _load_note(p.id, loaded, p.equipment or _same_id(mep, p.id)),
            ]
        )
    openings = [
        [
            str(o.get("id")),
            str(o.get("host")),
            (
                f"Ø{fmt(o.get('diameter'), 0)}"
                if o.get("shape") == "circle"
                else f"{fmt(o.get('width'), 0)} x {fmt(o.get('height'), 0)}"
            ),
            str(o.get("service") or ""),
        ]
        for o in air.get("openings") or []
    ]
    conflicts = []
    for c in air.get("conflicts") or []:
        failing = [k for k in c.get("checks") or [] if not k.get("ok")]
        worst = max(failing, key=lambda k: k.get("utilisation") or 0.0, default=None)
        options = [o.get("kind") for o in c.get("options") or [] if o.get("ok")]
        conflicts.append(
            [
                str(c.get("duct")),
                str(c.get("beam") or c.get("slab") or ""),
                (
                    f"{worst['name']} ({fmt(worst.get('utilisation'), 2)})"
                    if worst
                    else "; ".join(c.get("notes") or []) or "–"
                ),
                ", ".join(OPTION_LABELS.get(o, o) for o in options) or "–",
            ]
        )
    existing = sorted({str(c["existing"]) for c in air.get("crossings") or [] if c.get("existing")})
    shafts = [
        [str(s.get("id")), fmt(s.get("need"), 3), fmt(s.get("area"), 3),
         "OK" if s.get("ok", True) else "FAIL"]
        for s in air.get("shafts") or []
    ]  # fmt: skip
    checks = list(air.get("checks") or [])
    failed = sum(1 for c in checks if not c.get("ok"))
    engine = str(loads.get("engineLabel") or loads.get("engine") or "not calculated")
    if loads.get("calculated") is False:
        engine += " (loads not calculated with EnergyPlus for this input: run Calculate Loads)"
    building = loads.get("building") or {}
    summary = [
        ["System", HVAC_SYSTEMS.get(hvac.system, hvac.system)],
        ["Cooling loads by", engine],
        [
            "Cooling load",
            f"{fmt(loads.get('total'), 1)} kW ({fmt(loads.get('tons'), 1)} TR), the sum of the "
            "stories' peaks"
            + (
                f"; {fmt(building.get('total'), 1)} kW coincident"
                if building.get("total") is not None
                else ""
            ),
        ],
        ["Supply air, outdoor air", f"{fmt(loads.get('airflow'), 2)}, {fmt(loads.get('outdoorAir'), 2)} m³/s"],
        [
            "Plant on the structure",
            (f"{len(hvac.plant)} items, "
            f"{fmt(sum(p.operatingWeight or 0.0 for p in hvac.plant), 1)} kN entered"),
        ],
        ["Ducts", str(len(hvac.ducts))],
        ["Openings still to add", str(len(openings))],
        ["Ducts that cannot pass", str(len(conflicts))],
        ["Checks failing", str(failed)],
    ]  # fmt: skip
    notes = [str(n) for n in loads.get("notes") or []]
    notes += [f"Air side: {n}" for n in air.get("notes") or []]
    notes += [str(x) for x in loads.get("problems") or []]
    notes += [str(x) for x in air.get("problems") or []]
    stale = air.get("stale") or []
    if stale:
        notes.append(
            f"Openings of 7 MEP no duct crosses any more (remove them): {', '.join(stale)}"
        )
    return {
        "available": True,
        "problem": "",
        "summary": summary,
        "zones": zones,
        "plant": plant,
        "openings": openings,
        "conflicts": conflicts,
        "existing": ", ".join(existing),
        "shafts": shafts,
        "checks": _service_checks(checks),
        "checkFails": [not c.get("ok") for c in checks],
        "failed": failed,
        "method": [str(m) for m in loads.get("method") or []],
        "notes": notes,
    }


#: The duct route options of :func:`saengine.hvac.openings.route_options`.
OPTION_LABELS = {
    "routeBelow": "route below the beam",
    "increaseFloorHeight": "raise the floor above",
    "split": "split into flatter ducts",
    "lowerToMidDepth": "lower to the beam's mid-depth",
    "throughSlab": "rise through the slab",
    "inShaft": "run in a shaft",
}


def _electrical(parts: _Parts) -> dict[str, Any]:
    """The electrical coordination chapter (Part 7, BNBC 2020 Part 8 Chapter 1): the demand,
    the substation, generator and their rooms, the equipment with its weights on the structure,
    the rising mains and trays with their openings, and the lightning protection's down-conductor
    columns and earthing for the structural drawings; not printed while 07 MEP has no
    electrical."""
    from saengine.electrical.report import electrical_report, with_typical
    from saengine.library.mep import ELECTRICAL_EQUIPMENT_KINDS, MEP_FILE, parse

    empty = {"available": False, "problem": "", "notes": []}
    try:
        mep = parse(parts.text(MEP_FILE))
    except ValueError as error:
        return {**empty, "problem": f"{MEP_FILE} is not valid: {error}"}
    electrical = mep.electrical
    if electrical is None:
        return empty
    report = electrical_report(parts.root)
    if "demand" not in report:
        return {**empty, "problem": "; ".join(str(x) for x in report.get("problems") or [])}
    loaded = _service_loads(parts, mep, "electrical")
    demand = report.get("demand") or {}
    stories = [
        [
            str(s.get("story")),
            str(s.get("use") or ""),
            fmt(s.get("area"), 1),
            fmt(s.get("density"), 1),
            fmt(s.get("connected"), 1),
            fmt(s.get("kva"), 1),
        ]
        for s in demand.get("stories") or []
    ]
    equipment = []
    for item in electrical.equipment:
        full = with_typical(item.model_dump(mode="json"), electrical.supply.transformerType)
        size = " x ".join(fmt(full.get(k), 0) for k in ("length", "width", "height") if full.get(k))
        equipment.append(
            [
                item.id,
                ELECTRICAL_EQUIPMENT_KINDS.get(item.kind, item.kind),
                item.story,
                fmt(item.rating, 0),
                size or "–",
                fmt(full.get("operatingWeight"), 1),
                _load_note(item.id, loaded, item.equipment or _same_id(mep, item.id)),
            ]
        )
    risers = [
        [
            str(r.get("id")),
            str(r.get("kind")),
            " x ".join(fmt(r.get(k), 0) for k in ("width", "depth") if r.get(k)) or "–",
            fmt(r.get("rating"), 0),
            fmt(r.get("current"), 0),
            ", ".join(str(s) for s in r.get("stories") or []),
        ]
        for r in report.get("risers") or []
    ]
    openings = [
        [
            str(o.get("id")),
            str(o.get("host")),
            f"{fmt(o.get('width'), 0)} x {fmt(o.get('height'), 0)}",
            str(o.get("service") or ""),
        ]
        for o in report.get("openings") or []
    ]
    lightning = report.get("lightning") or {}
    conductors = [
        [
            str(d.get("id")),
            f"{fmt(d.get('x'), 0)}, {fmt(d.get('y'), 0)}",
            ", ".join(str(c) for c in d.get("columns") or []),
            str(d.get("foundation") or "–"),
            str(d.get("conductor") or ""),
        ]
        for d in lightning.get("downConductors") or []
    ]
    checks = list(report.get("checks") or [])
    failed = sum(1 for c in checks if not c.get("ok"))
    risk = lightning.get("risk") or {}
    summary = [[f"{i + 1}", str(line)] for i, line in enumerate(report.get("summary") or [])]
    notes = [str(n) for n in report.get("notes") or []]
    notes += [str(x) for x in report.get("problems") or []]
    return {
        "available": True,
        "problem": "",
        "summary": summary,
        "stories": stories,
        "equipment": equipment,
        "rooms": _service_checks(report.get("rooms") or []),
        "roomFails": [not c.get("ok") for c in report.get("rooms") or []],
        "risers": risers,
        "openings": openings,
        "lightning": {
            "enabled": bool(lightning.get("enabled")),
            "risk": str(risk.get("note") or risk.get("decision") or ""),
            "conductors": conductors,
            "needed": str(lightning.get("downConductorsNeeded") or len(conductors)),
            "structural": [str(n) for n in lightning.get("structuralNotes") or []],
        },
        "checks": _service_checks(checks),
        "checkFails": [not c.get("ok") for c in checks],
        "failed": failed,
        "method": [str(m) for m in report.get("method") or []],
        "notes": notes,
    }


def _boq(parts: _Parts) -> dict[str, Any]:
    from saengine.boq import BillOfQuantities

    text = parts.text(BOQ_FILE)
    if text is None:
        return {"status": "missing", "message": "There is no bill of quantities.", "notes": []}
    try:
        boq = BillOfQuantities.model_validate_json(text)
    except ValueError:
        return {
            "status": "missing",
            "message": "The bill of quantities has not been computed (10 BOQ/boq.json).",
            "notes": [],
        }
    groups = []
    for group, title in BOQ_GROUPS.items():
        items = [i for i in boq.items if i.group == group]
        if not items:
            continue
        units = {i.unit for i in items}
        unit = UNITS.get(next(iter(units)), "") if len(units) == 1 else ""
        groups.append(
            {
                "title": title,
                "unit": unit,
                "rows": [
                    [
                        i.code,
                        i.description,
                        fmt(i.quantity, 0 if i.unit in ("kg", "nr") else 2),
                        UNITS.get(i.unit, i.unit),
                    ]
                    for i in items
                ],
                # Excavation and backfill are the same earth twice: no earthwork total.
                "total": fmt(sum(i.quantity for i in items), 0 if unit in ("kg", "nr") else 2)
                if unit and group != "earthwork"
                else "",
            }
        )
    source = boq.source.model_dump()
    changed = [
        relative
        for key, relative in BOQ_SOURCES.items()
        if source.get(key) is not None and parts.boq_stamp(key, relative) != source.get(key)
    ]
    unstamped = all(source.get(key) is None for key in BOQ_SOURCES)
    status, message = "ok", ""
    if not boq.items and unstamped:
        status, message = "missing", "The bill of quantities has not been computed."
    elif changed:
        status = "stale"
        message = (
            "The bill of quantities is out of date: "
            + ", ".join(changed)
            + " changed after it was computed. Recompute it before relying on these quantities."
        )
    elif unstamped:
        status = "stale"
        message = "The bill of quantities does not record what it was measured from."
    if status == "stale":
        parts.warnings.append(message)
    return {"status": status, "message": message, "groups": groups, "notes": list(boq.notes)}
