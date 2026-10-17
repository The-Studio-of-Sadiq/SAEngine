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
MODEL_OPTIONAL_SOURCES = {"soil": SOIL_FILE}

#: Upstream files of the bill of quantities, by the keys of its ``source`` stamps.
BOQ_SOURCES = {
    "bim": BIM_FILE,
    "objects": OBJECTS_FILE,
    "materials": MATERIALS_FILE,
    "substructure": SUBSTRUCTURE_FILE,
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
KIND_ORDER = ["footing", "pileCap", "pile", "column", "wall", "beam", "brace", "slab", "staircase"]

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
    "member": "Members",
}

BOQ_GROUPS = {
    "earthwork": "Earthwork",
    "concrete": "Concrete",
    "masonry": "Masonry",
    "reinforcement": "Reinforcement",
    "formwork": "Formwork",
    "steel": "Structural steel",
}

UNITS = {"m3": "m³", "m2": "m²", "kg": "kg"}

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
    report["boq"] = _boq(parts)
    report["limitations"] = {
        "design": report["design"].get("notes", []),
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


def _basis(settings: Any, parts: _Parts, model: dict[str, Any], manifest: dict[str, Any]) -> dict:
    from saengine.library import bnbc

    basis: dict[str, Any] = {}
    if settings is not None:
        from saengine.library.settings import derived

        values = derived(settings)
        codes = settings.codes
        basis["codes"] = [
            ["Loads and general", codes.general],
            ["Concrete", codes.concrete],
            ["Steel", codes.steel],
            ["Design method", "Strength design (LRFD)"],
        ]
        location = bnbc.LOCATIONS.get(settings.site.location)
        category = bnbc.OCCUPANCY_CATEGORIES.get(settings.occupancy.category)
        system = bnbc.STRUCTURAL_SYSTEMS.get(settings.seismic.system)
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
                bnbc.AREA_USES[load.use].name if load.use in bnbc.AREA_USES else "Custom",
                fmt(load.live, 2),
                fmt(load.finish, 2),
                fmt(load.partitions, 2),
            ]
            for load in settings.areaLoads
        ]
        cases = ["D", "L", "Lr", "WX", "WY", "EX", "EY"]
        used = [c for c in cases if any(getattr(k, c) for k in settings.combinations)]
        basis["combinations"] = {
            "columns": used,
            "rows": [
                [k.name, *(_factor(getattr(k, c)) for c in used)] for k in settings.combinations
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


def _derive_again(root: Path, parts: _Parts) -> Any:
    from saengine.fem.derive import derive_fem

    inputs = (parts.building(), parts.objects(), parts.materials(), parts.settings())
    if any(value is None for value in inputs):
        return None
    try:
        return derive_fem(*inputs, None, root / "08 FEM")
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
    from saengine.design import design_report

    try:
        report = design_report(results_dir, model_path)
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
    failed = int(summary.get("failed", 0) or 0)
    if failed:
        warnings.append(f"{failed} element(s) fail their design checks.")
    return {
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
                        fmt(i.quantity, 0 if i.unit == "kg" else 2),
                        UNITS.get(i.unit, i.unit),
                    ]
                    for i in items
                ],
                # Excavation and backfill are the same earth twice: no earthwork total.
                "total": fmt(sum(i.quantity for i in items), 0 if unit == "kg" else 2)
                if unit and group != "earthwork"
                else "",
            }
        )
    source = boq.source.model_dump()
    changed = [
        relative
        for key, relative in BOQ_SOURCES.items()
        if source.get(key) is not None and parts.stamp(relative) != source.get(key)
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
