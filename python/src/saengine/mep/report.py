"""The MEP coordination report of a project: equipment loads, opening checks and clashes.

:func:`mep_report` reads the project's parts (``07 MEP/mep.json`` and what it refers to), the
analysis model and its results when the analysis has run (``08 FEM``), and the MEP IFC models
listed in ``mep.json``. :func:`mep_suggest_sleeves` proposes the sleeves and openings that would
coordinate the clashes, each with its geometric checks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from saengine.library.bim import BeamElement, BuildingModel, SlabElement, WallElement
from saengine.library.materials import MaterialLibrary
from saengine.library.mep import MEP_FILE, MepModel, Opening, check, parse
from saengine.library.objects import ObjectLibrary, Wall
from saengine.library.settings import ProjectSettings
from saengine.mep import clash, loads, openings

METHOD = [
    (
        "Equipment (BNBC 2020 Part 6): the empty weight and a plinth are dead load, case SD "
        "(Sec 2.2.6, fixed service equipment); the contents are the fluid load F of Sec 2.7.3.1, "
        "which is in 1.4(D + F) and 1.2(D + F + T) + ... and not in the 0.9D combinations (a "
        "tank may be empty): their own case F when the analysis has one, else live load L, or "
        "SD only when 07 MEP says they are always there; vibrating machinery and lifts add "
        "an impact allowance as live load L (Sec 2.3.12, Table 6.2.6). The equipment and its "
        "contents count in full in the seismic weight (Sec 2.5.7.3 (c))."
    ),
    (
        "Sleeves and openings: beams by the net-section method for small openings (h/3 deep, d "
        "long), shear with d - a0 (BNBC 6.4.1.1.1, ACI 318-19 22.5), the compression zone and "
        "the bars clear of the opening, at least h from the support face, sleeves at most h/3 and "
        "3 diameters apart (SAEngine practice limits: BNBC 5.16.3.3 gives no number for sleeves "
        "passing through, the limits are those 5.16.3.5 sets for embedded pipes); larger "
        "openings need a Vierendeel design (not done). "
        "Slabs: BNBC 6.5.4 strip limits, 6.4.10.6 punching perimeter near columns. Walls: the "
        "length removed and trim bars (BNBC 6.6.3.7)."
    ),
    (
        "Clashes: the MEP IFC models against the structure SAEngine exports from the building "
        "model, with IfcOpenShell's geometry tree; a clash through a beam, slab or wall with a "
        "sleeve or opening of 07 MEP (or a shaft) where it crosses is coordinated."
    ),
]


class _Project:
    def __init__(self, project_root: str | Path, mep_text: str | None = None) -> None:
        self.root = Path(project_root)
        self.settings = ProjectSettings.model_validate_json(
            self.read("02 Project Settings/project-settings.json")
        )
        self.materials = MaterialLibrary.model_validate_json(
            self.read("03 Materials/materials.json")
        )
        self.objects = ObjectLibrary.model_validate_json(self.read("04 Objects/objects.json"))
        self.building = BuildingModel.model_validate_json(self.read("06 BIM/bim.json"))
        if mep_text is None:
            try:
                mep_text = (self.root / MEP_FILE).read_text(encoding="utf-8")
            except OSError:
                mep_text = None
        try:
            self.mep: MepModel = parse(mep_text)
        except ValueError as error:
            raise ValueError(f"{MEP_FILE} is not valid: {error}") from error

    def read(self, relative: str) -> str:
        try:
            return (self.root / relative).read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"{relative} could not be read: {error}") from error

    @property
    def densities(self) -> dict[str, float | None]:
        return {m.id: m.mechanical.density for m in self.materials.materials}


def _analysis(project: _Project, out_dir: Path) -> tuple[openings.Analysis | None, str]:
    from saengine.design.check import _demands

    try:
        model = json.loads((project.root / "08 FEM" / "model.osmodel").read_text("utf-8"))
    except (OSError, ValueError):
        return None, "there is no analysis model: shear and flexure at the openings are not checked"
    try:
        names, pieces, _, _ = _demands(model, out_dir, project.settings)
    except ValueError:
        return (
            None,
            "there are no analysis results: shear and flexure at the openings are not checked",
        )
    return openings.Analysis(names, pieces), ""


def mep_report(
    project_root: str | Path, out_dir: str | Path | None = None, mep_text: str | None = None
) -> dict[str, Any]:
    """The MEP coordination report of the project at ``project_root`` with the analysis results
    in ``out_dir`` (default ``08 FEM/model.results``), ready for JSON. ``mep_text``: the
    editor's text of ``07 MEP/mep.json`` (unsaved edits), else the file is read.

    ``{"method", "equipment": [per item {"id", "name", "kind", "story", "slabs", "host" (the
    first of them), "loads" {case: kN}, "load" (their sum, kN), "loadCase" ("SD", "SD + L"),
    "impactPercent", "impactSource", "plinth", "area", "pressure" (operating weight over the
    footprint, kPa), "seismicWeight", "loadAs", "note"}], "stories": [per story {"story",
    "count", "load"}], "openings": [per opening {"id", "host", "hostKind", "kind", "service",
    "checks", "utilisation", "ok", "checked", "check" (the governing check), "note", "notes"}],
    "clashes": [see :func:`saengine.mep.clash.find_clashes`], "summary", "problems",
    "notes"}``. Raises ``ValueError`` when a part cannot be read or is invalid."""
    project = _Project(project_root, mep_text)
    mep, building = project.mep, project.building
    out = Path(out_dir) if out_dir is not None else project.root / "08 FEM" / "model.results"
    notes: list[str] = []

    # The plumbing's overhead tanks, the HVAC plant and the electrical equipment load the
    # model as equipment (saengine.mep.loads.services_equipment, each once).
    loaded, service_notes = loads.with_services_equipment(mep, project.materials)
    notes += service_notes
    equipment = []
    for item in loaded.equipment:
        entry = loads.summary_of(item, mep.contentsAs, project.densities)
        entry["slabs"] = loads.slabs_under(item, building)
        entry["host"] = entry["slabs"][0] if entry["slabs"] else None
        entry["load"] = round(sum(entry["loads"].values()), 3)
        entry["loadCase"] = " + ".join(entry["loads"])
        entry["note"] = (
            f"impact {entry['impactPercent']:g} % ({entry['impactSource']})"
            if entry["impactPercent"]
            else ""
        )
        if not entry["slabs"]:
            entry["note"] = "not on a slab of its story: its loads are not applied"
        equipment.append(entry)
    stories: dict[str, dict[str, Any]] = {}
    for entry in equipment:
        story = stories.setdefault(
            entry["story"], {"story": entry["story"], "count": 0, "load": 0.0}
        )
        story["count"] += 1
        story["load"] = round(story["load"] + entry["load"], 3)

    analysis, why = _analysis(project, out) if mep.openings else (None, "")
    if why:
        notes.append(why)
    checked, more = openings.opening_checks(
        mep, building, project.objects, project.materials, analysis
    )
    notes += more
    for result in checked:
        strength = [c for c in result["checks"] if not c["flag"]]
        governing_check = max(strength, key=lambda c: c["utilisation"], default=None)
        result["check"] = governing_check["name"] if governing_check else None
        result["note"] = "; ".join(result["notes"])

    clashes: list[dict[str, Any]] = []
    if mep.ifcModels:
        models, more = clash.open_models(project.root, mep)
        notes += more
        if models:
            structure, *_ = clash.structural_ifc(project.root)
            clashes, more = clash.find_clashes(structure, building, project.objects, mep, models)
            notes += more

    totals: dict[str, float] = {}
    for entry in equipment:
        for case, value in entry["loads"].items():
            totals[case] = round(totals.get(case, 0.0) + value, 3)
    failed = [o for o in checked if o["checked"] and not o["ok"]]
    governing = max(checked, key=lambda o: o["utilisation"], default=None)
    return {
        "method": METHOD,
        "equipment": equipment,
        "stories": list(stories.values()),
        "openings": checked,
        "clashes": clashes,
        "summary": {
            "equipment": len(equipment),
            "loads": totals,
            "openings": len(checked),
            "openingsFailed": len(failed),
            "maxUtilisation": governing["utilisation"] if governing else None,
            "governing": governing["id"] if governing else None,
            "clashes": sum(1 for c in clashes if c["status"] == "clash" and c["kind"] == "hard"),
            "coordinated": sum(1 for c in clashes if c["status"] == "coordinated"),
            "clearance": sum(1 for c in clashes if c["kind"] == "clearance"),
            "suggestions": sum(1 for c in clashes if c["sleeve"]),
        },
        "problems": check(mep, building),
        "notes": notes,
    }


def suggestion_checks(
    suggestion: dict[str, Any],
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The geometric checks (no analysis forces) of a proposed opening."""
    fields = {k: suggestion[k] for k in ("id", "host", "kind", "shape", "position", "service")}
    for key in ("diameter", "width", "height"):
        if key in suggestion:
            fields[key] = suggestion[key]
    opening = Opening.model_validate(fields)
    host = next((e for e in building.elements if e.id == opening.host), None)
    if isinstance(host, BeamElement):
        section, why = openings.beam_section(host, objects, materials, building)
        if section is None:
            return [], [f"{opening.id}: {host.id} is not checked: {why}"]
        checks, notes = openings.beam_opening_checks(opening, section, None)
        return checks, [n for n in notes if "no analysis results" not in n]
    if isinstance(host, SlabElement):
        info, columns, why = openings.slab_info(host, objects, materials, building)
        if info is None:
            return [], [f"{opening.id}: {host.id} is not checked: {why}"]
        return openings.slab_opening_checks(opening, info, columns)
    if isinstance(host, WallElement):
        wall_type = next((o for o in objects.objects if o.id == host.type), None)
        thickness = wall_type.thickness if isinstance(wall_type, Wall) else 200.0
        return openings.wall_opening_checks(opening, host, thickness)
    return [], []


def mep_suggest_sleeves(
    project_root: str | Path, allowance: float = 25.0, mep_text: str | None = None
) -> dict[str, Any]:
    """Sleeves and openings that would coordinate the clashes of the project's MEP models:
    ``{"openings": [openings in mep.json's format, nothing else in them], "checks": {opening
    id: {"clash", "mep", "checks", "ok", "notes"}}, "notes"}``, each checked for its geometry
    (no analysis forces). The editor adds the ones the engineer accepts to ``07 MEP/mep.json``.
    ``mep_text``: the editor's text of mep.json (unsaved edits)."""
    project = _Project(project_root, mep_text)
    mep = project.mep
    notes: list[str] = []
    if not mep.ifcModels:
        return {"openings": [], "checks": {}, "notes": ["07 MEP lists no IFC models to check"]}
    models, more = clash.open_models(project.root, mep)
    notes += more
    if not models:
        return {"openings": [], "checks": {}, "notes": notes}
    structure, *_ = clash.structural_ifc(project.root)
    found, more = clash.find_clashes(
        structure, project.building, project.objects, mep, models, allowance=allowance
    )
    notes += more
    proposals: list[dict[str, Any]] = []
    checked: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, tuple[float, ...]]] = set()
    for entry in found:
        suggestion = entry["sleeve"]
        if not suggestion:
            continue
        key = (
            suggestion["host"],
            tuple(round(v / 50) for v in suggestion["position"].values()),
        )
        if key in seen:
            continue
        seen.add(key)
        checks, own = suggestion_checks(
            suggestion, project.building, project.objects, project.materials
        )
        strength = [c for c in checks if not c["flag"]]
        proposals.append(dict(suggestion))
        checked[suggestion["id"]] = {
            "clash": entry["id"],
            "mep": entry["mep"],
            "checks": checks,
            "ok": all(c["ok"] for c in strength),
            "notes": own,
        }
    return {"openings": proposals, "checks": checked, "notes": notes}
