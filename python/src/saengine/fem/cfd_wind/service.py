"""The CFD wind tunnel for the app and the report (alpha 9 L3): the work behind the RPC methods
``cfd/detect``, ``cfd/write``, ``cfd/start``, ``cfd/status``, ``cfd/cancel``, ``cfd/results``
and the report's section.

The values a code decides come from the project's code pack (``cfdWind``: the directions, z0 by
exposure, the lower limit, the validation statement; the wind table's exposures and velocity
pressure); the project's own settings (``wind.cfd``) override them.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from saengine.codes import context as code_context
from saengine.fem.cfd_wind import CASES, FOLDER, RESULTS, openfoam, post, runner
from saengine.fem.cfd_wind.case import UREF, CaseOptions, case_name, write_case
from saengine.fem.cfd_wind.envelope import Envelope, envelope_from_building

SETTINGS_FILE = "02 Project Settings/project-settings.json"
BIM_FILE = "06 BIM/bim.json"
MODEL_FILE = "08 FEM/model.osmodel"
#: Where a value came from when the pack gives none (named in the results and the report).
PRACTICE = "SAEngine practice"


def _settings(root: Path) -> Any:
    from saengine.library.settings import ProjectSettings, read_soil_text, resolve_site_class

    text = (root / SETTINGS_FILE).read_text(encoding="utf-8")
    settings = ProjectSettings.model_validate_json(text)
    return resolve_site_class(settings, read_soil_text(root))[0]


def _options(settings: Any) -> Any:
    from saengine.library.settings import CfdWind

    return getattr(settings.wind, "cfd", None) or CfdWind()


def _nodes(root: Path) -> list[list[float]] | None:
    try:
        model = json.loads((root / MODEL_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return [n["coords"] for n in model.get("nodes", []) if len(n.get("coords") or []) == 3]


def envelope_of(root: Path) -> Envelope:
    """The project's envelope (its BIM, the analysis model's nodes where a level has neither
    slabs nor columns); ValueError with the reason when there is none."""
    from pydantic import ValidationError

    from saengine.library.bim import BuildingModel

    try:
        building = BuildingModel.model_validate_json((root / BIM_FILE).read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"the building model (6 BIM) cannot be read: {error}") from error
    except ValidationError as error:
        raise ValueError("the building model (6 BIM) has errors: open it to fix them") from error
    if building.source is not None and building.source.structure is not None:
        raise ValueError(
            "a special structure (built from the structural model) has no building envelope: "
            "its wind is on its members (Project Settings > Wind > Open structures)"
        )
    if not building.elements:
        raise ValueError("the building model (6 BIM) has no members yet: build it first")
    return envelope_from_building(building, _nodes(root))


def roughness(settings: Any) -> tuple[float, str]:
    """z0 [m] and where it comes from: the project's, the pack's ``cfdWind.roughness`` of the
    exposure, the wind table's exposure (``z0``), its gust factor's roughness; ValueError when
    none gives one (the project enters it)."""
    own = _options(settings).roughness
    if own is not None:
        return float(own), "the project's setting"
    exposure = settings.wind.exposure
    pack = code_context.current()
    name = code_context.code_name()
    if pack.has("cfdWind"):
        table = pack.table("cfdWind")
        if exposure in (table.roughness or {}):
            source = (table.sources or {}).get("roughness") or name
            return float(table.roughness[exposure]), str(source)
    if pack.has("wind"):
        wind = pack.table("wind")
        profile = (getattr(wind, "exposures", None) or {}).get(exposure)
        z0 = getattr(profile, "z0", None) if profile is not None else None
        if z0:
            return float(z0), f"{name}, exposure {exposure}"
        gust = getattr(wind, "gustFactor", None)
        values = getattr(gust, "roughness", None) or {}
        if exposure in values:
            return float(values[exposure]), f"{name}, terrain {exposure}"
    raise ValueError(
        f"the code pack {name} gives no roughness length z0 for the exposure '{exposure}': "
        "enter one in Project Settings > Wind > CFD wind tunnel"
    )


def directions(settings: Any) -> tuple[list[float], str]:
    """The wind directions [°] and where they come from."""
    from saengine.library.settings import CFD_DIRECTION_STEP

    options = _options(settings)
    if options.directions:
        angles = sorted({round(float(a) % 360, 6) for a in options.directions})
        return angles, "the project's list"
    step, source = options.directionStep, "the project's step"
    if step is None:
        pack = code_context.current()
        if pack.has("cfdWind"):
            step = float(pack.table("cfdWind").directionStep)
            source = str(pack.table("cfdWind").sources.get("directionStep") or "the code pack")
        else:
            step, source = CFD_DIRECTION_STEP, f"{PRACTICE} (the code pack gives none)"
    count = max(1, round(360 / step))
    return [round(k * 360 / count, 6) for k in range(count)], source


def _pack_info() -> dict[str, Any]:
    pack = code_context.current()
    info: dict[str, Any] = {"id": pack.id, "name": code_context.code_name(), "covers": False}
    if pack.has("cfdWind"):
        table = pack.table("cfdWind")
        info.update(
            covers=True,
            validation=table.validation,
            lowerLimit=table.lowerLimit,
            procedure=code_context.cite("cfdWind", "procedure"),
            sources=dict(table.sources or {}),
        )
    return info


def _within(root: Path, settings: Any):
    return code_context.using(code_context.pack_for(settings, root))


# ───────────────────────────────────────── the RPC methods ─────────────────────────────────────────


def detect(setting: str | None, distribution: str | None) -> dict[str, Any]:
    """``cfd/detect``: the installation found (never raises) and how to install one."""
    inst = openfoam.detect(setting, distribution)
    return {**inst.to_json(), "install": openfoam.install_steps()}


def write_cases(root: str | Path, installation: dict[str, Any] | None = None) -> dict[str, Any]:
    """``cfd/write``: the cases of every direction (old cases removed) and their plan; nothing
    runs. ``installation`` (of ``cfd/detect``) adapts the files to it."""
    root = Path(root)
    try:
        settings = _settings(root)
    except (OSError, ValueError) as error:
        return {"ok": False, "message": f"the project settings cannot be read: {error}"}
    inst = openfoam.Installation.from_json(installation or {})
    with _within(root, settings):
        try:
            envelope = envelope_of(root)
            z0, z0_source = roughness(settings)
            angles, angle_source = directions(settings)
        except ValueError as error:
            return {"ok": False, "message": str(error)}
        pack = _pack_info()
    options = _options(settings)
    cases = root / CASES
    if runner.running(cases):
        return {"ok": False, "message": "a CFD run is running: cancel it first"}
    cases.mkdir(parents=True, exist_ok=True)
    for child in cases.iterdir():
        if child.is_dir() and child.name.startswith("dir-"):
            shutil.rmtree(child, ignore_errors=True)
    for name in (runner.STATUS, runner.CANCEL):
        (cases / name).unlink(missing_ok=True)
    written = []
    for angle in angles:
        case_options = CaseOptions(
            angle=angle,
            z0=z0,
            turbulence=options.turbulence,
            cellsPerHeight=options.cellsPerHeight,
            surfaceLevel=options.surfaceLevel,
            wakeLevel=options.wakeLevel,
            maxCells=options.maxCells,
            iterations=options.iterations,
            residual=options.residual,
            processors=options.processors,
            flavour=inst.flavour or "",
            solver=inst.solver or "simpleFoam",
        )
        written.append(write_case(cases / case_name(angle), envelope, case_options))
    notes = list(envelope.notes)
    for w in written:
        notes += [n for n in w["notes"] if n not in notes]
    plan = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "directions": angles,
        "cases": [case_name(a) for a in angles],
        "envelope": envelope.to_json(),
        "reference": {"uref": UREF, "zref_m": envelope.height, "centre": list(envelope.centre)},
        "settings": {
            **options.model_dump(),
            "z0": z0,
            "z0Source": z0_source,
            "directionsSource": angle_source,
        },
        "installation": inst.to_json(),
        "pack": pack,
        "results": str(root / RESULTS),
        "notes": notes,
    }
    (cases / runner.PLAN).write_text(json.dumps(plan, indent=1), encoding="utf-8")
    return {
        "ok": True,
        "folder": str(cases),
        "directions": angles,
        "directionsSource": angle_source,
        "z0": z0,
        "z0Source": z0_source,
        "height_m": envelope.height,
        "estimatedCells": max((w["estimatedCells"] for w in written), default=0),
        "cells": written[0]["domain"]["cells"] if written else None,
        "notes": notes,
    }


def start(root: str | Path, setting: str | None, distribution: str | None) -> dict[str, Any]:
    """``cfd/start``: finds OpenFOAM, writes the cases for it and starts the background run."""
    root = Path(root)
    cases = root / CASES
    if runner.running(cases):
        return {"ok": False, "message": "a CFD run is already running"}
    inst = openfoam.detect(setting, distribution)
    if not inst.found:
        return {
            "ok": False,
            "message": "OpenFOAM was not found: " + "; ".join(inst.problems),
            "installation": inst.to_json(),
            "install": openfoam.install_steps(),
        }
    written = write_cases(root, inst.to_json())
    if not written.get("ok"):
        return written
    plan = json.loads((cases / runner.PLAN).read_text(encoding="utf-8"))
    post.start_results(root / RESULTS, plan)
    started = runner.start(cases)
    return {**written, **started, "installation": inst.to_json()}


def status(root: str | Path) -> dict[str, Any]:
    """``cfd/status``: the run's status and progress."""
    return runner.status(Path(root) / CASES)


def cancel(root: str | Path) -> dict[str, Any]:
    """``cfd/cancel``: asks the run to stop."""
    return runner.cancel(Path(root) / CASES)


def _code_bases(envelope: Envelope, speed: float, exposure: str, importance: float) -> dict:
    """The code's static wind base shear along X and Y [kN] on the envelope (each storey's face
    from its level's extent, :func:`saengine.fem.loads.wind_levels`)."""
    from saengine.fem import loads as fl

    rel = envelope.relative_levels
    boxes = []
    for parts in envelope.outlines:
        pts = [p for poly in parts for p in poly]
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            boxes.append((min(xs), max(xs), min(ys), max(ys)))
        else:
            boxes.append((0.0, 0.0, 0.0, 0.0))
    out = {}
    for axis, key in ((0, "X"), (1, "Y")):
        spans = [(b[2], b[3]) if axis == 0 else (b[0], b[1]) for b in boxes]
        depths = [b[1] - b[0] if axis == 0 else b[3] - b[2] for b in boxes]
        levels = fl.wind_levels(rel, spans, depths, speed, exposure, importance)
        out[key] = {
            "V_kN": sum(level.force for level in levels),
            "levels": [level.force for level in levels],
        }
    return out


def results(root: str | Path) -> dict[str, Any]:
    """``cfd/results`` (and the report): the coefficients with the design storey forces of every
    direction, compared with the code's static wind; ``{"available": False, "reason"}`` before a
    run has finished a direction."""
    from saengine.fem import loads as fl
    from saengine.library.settings import derived

    root = Path(root)
    data = post.read_results(root / RESULTS)
    if data is None or not data.get("directions"):
        return {"available": False, "reason": "no CFD run has finished a direction yet"}
    try:
        settings = _settings(root)
    except (OSError, ValueError) as error:
        return {"available": False, "reason": f"the project settings cannot be read: {error}"}
    envelope = Envelope.from_json(data["envelope"])
    notes = list(data.get("notes") or [])
    try:
        current = envelope_of(root).stamp()
    except ValueError:
        current = None
    stale = current is not None and current != envelope.stamp()
    if stale:
        notes.append(
            "the building's envelope changed since the CFD run: run it again before using it"
        )
    with _within(root, settings):
        pack = _pack_info()
        values = derived(settings)
        speed, importance = values.get("windSpeed"), values.get("windImportance")
        exposure = settings.wind.exposure
        q = None
        code = None
        if speed:
            with fl.wind_overrides(settings.wind):
                from saengine.fem.cfd_wind.loads import design_pressure

                q = design_pressure(envelope.height, float(speed), exposure, float(importance))
                code = _code_bases(envelope, float(speed), exposure, float(importance))
        else:
            notes.append(
                "the site has no basic wind speed: the coefficients are shown without forces"
            )
    rows = []
    storeys = []
    zones = []
    for d in data["directions"]:
        base = post.base_forces(d, q, envelope.base) if q else None
        row = {
            "angle": d["angle"],
            "case": post.case_of(d["angle"]),
            "converged": d.get("converged"),
            "residual": d.get("residual"),
            "iterations": d.get("iterations"),
            "CFx_m2": d["total"]["CFx_m2"],
            "CFy_m2": d["total"]["CFy_m2"],
            "CMz_m3": d["total"]["CMz_m3"],
        }
        if base is not None:
            row.update(base)
            if code:
                row["shareX"] = (
                    abs(base["Vx_kN"]) / code["X"]["V_kN"] if code["X"]["V_kN"] else None
                )
                row["shareY"] = (
                    abs(base["Vy_kN"]) / code["Y"]["V_kN"] if code["Y"]["V_kN"] else None
                )
        rows.append(row)
        forces = post.design_levels(d, q) if q else None
        storeys.append(
            {
                "angle": d["angle"],
                "rows": [
                    {
                        "z_m": lv["z_m"],
                        "CFx_m2": lv["CFx_m2"],
                        "CFy_m2": lv["CFy_m2"],
                        "CMz_m3": lv["CMz_m3"],
                        "cfAlong": lv.get("cfAlong"),
                        "cfAcross": lv.get("cfAcross"),
                        **(forces[i] if forces else {}),
                    }
                    for i, lv in enumerate(d["levels"])
                ],
            }
        )
        zones.append({"angle": d["angle"], "rows": d.get("zones") or []})
    settings_used = data.get("settings") or {}
    return {
        "available": True,
        "complete": bool(data.get("complete")),
        "stale": stale,
        "generated": data.get("generated"),
        "height_m": envelope.height,
        "base_m": envelope.base,
        "levels_m": list(envelope.levels),
        "q_kPa": q,
        "code": code,
        "pack": pack,
        "settings": settings_used,
        "installation": data.get("installation"),
        "directions": rows,
        "storeys": storeys,
        "zones": zones,
        "useInAnalysis": bool(_options(settings).useInAnalysis),
        "notes": notes,
    }


# ───────────────────────────────────────── the report ─────────────────────────────────────────


def _f(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.{digits}f}"


def report_section(root: str | Path) -> dict[str, Any] | None:
    """The report's section (strings): None when the project has no CFD wind tunnel run."""
    found = results(root)
    if not found.get("available"):
        return None
    pack = found["pack"] or {}
    validation = pack.get("validation") or (
        f"the code pack {pack.get('name', '')} gives no rule for wind tunnel or numerical "
        "wind studies"
    )
    settings = found.get("settings") or {}
    inst = found.get("installation") or {}
    intro = [
        "Engineer-supplied wind loads: a steady RANS simulation (OpenFOAM "
        f"{inst.get('version') or ''} {inst.get('solver') or ''}".rstrip()
        + ") of the building alone in an atmospheric boundary layer. It is not a code wind "
        "tunnel test: it gives mean pressures only (no peak or dynamic response, no "
        "neighbouring buildings or topography), and its results depend on the mesh and the "
        "turbulence model. Validate them against a boundary-layer wind tunnel test (or the "
        "code's procedure) before using them for design.",
        f"Code requirement: {validation}"
        + (f" ({pack['procedure']})" if pack.get("procedure") else ""),
        (
            f"Inlet: log-law boundary layer, z0 = {_f(settings.get('z0'), 3)} m "
            f"({settings.get('z0Source', '')}), Uref = {UREF:g} m/s at H = "
            f"{_f(found['height_m'], 2)} m; {settings.get('turbulence', '')} turbulence model; "
            f"directions: {settings.get('directionsSource', '')}; mesh {settings.get('cellsPerHeight')} "
            f"cells per H, {settings.get('surfaceLevel')} refinement levels at the building."
        ),
    ]
    if found.get("q_kPa"):
        intro.append(
            f"Storey forces F = q·CF with q = {_f(found['q_kPa'], 3)} kN/m² (the code's design "
            "velocity pressure at H times its gust factor): a quasi-steady scaling of the mean "
            "pressure coefficients."
        )
    columns = [
        "Direction",
        "Case",
        "Vx [kN]",
        "Vy [kN]",
        "T [kN·m]",
        "Vx / code X",
        "Vy / code Y",
        "Converged",
    ]
    rows = [
        [
            f"{r['angle']:g}°",
            r["case"],
            _f(r.get("Vx_kN")),
            _f(r.get("Vy_kN")),
            _f(r.get("T_kNm")),
            _f(r.get("shareX"), 2),
            _f(r.get("shareY"), 2),
            "yes" if r.get("converged") else "no",
        ]
        for r in found["directions"]
    ]
    code = found.get("code") or {}
    notes = list(found.get("notes") or [])
    if code:
        notes.insert(
            0,
            f"Code static wind on the envelope: Vx = {_f(code['X']['V_kN'])} kN, Vy = "
            f"{_f(code['Y']['V_kN'])} kN.",
        )
    if pack.get("lowerLimit"):
        notes.append(
            f"Used in the analysis, the CFD storey forces are scaled up to at least "
            f"{pack['lowerLimit']:.0%} of the code's base shear on each axis "
            f"({(pack.get('sources') or {}).get('lowerLimit', '')})."
        )
    notes.append(
        "Used in the analysis: "
        + (
            "yes (Project Settings > Wind > CFD wind tunnel > Use in the analysis); the cases "
            "are named in the load cases"
            if found.get("useInAnalysis")
            else "no (the code's wind is used)"
        )
    )
    # The governing direction's storeys and facade zones.
    governing = max(
        found["directions"],
        key=lambda r: abs(r.get("Vx_kN") or r["CFx_m2"]) + abs(r.get("Vy_kN") or r["CFy_m2"]),
    )
    storey = next(s for s in found["storeys"] if s["angle"] == governing["angle"])
    storey_rows = [
        [
            _f(r["z_m"], 2),
            _f(r["CFx_m2"]),
            _f(r["CFy_m2"]),
            _f(r["CMz_m3"]),
            _f(r.get("cfAlong"), 2),
            _f(r.get("Fx_kN")),
            _f(r.get("Fy_kN")),
            _f(r.get("Mz_kNm")),
        ]
        for r in storey["rows"]
    ]
    zone = next(z for z in found["zones"] if z["angle"] == governing["angle"])
    zone_rows = [
        [
            _f(r["z_m"], 2),
            r["zone"],
            r["role"],
            _f(r["cpMean"], 2),
            _f(r["cpMin"], 2),
            _f(r["cpMax"], 2),
        ]
        for r in zone["rows"]
    ]
    return {
        "title": "CFD wind tunnel (engineer-supplied, to be validated)",
        "intro": intro,
        "columns": columns,
        "rows": rows,
        "storeyTitle": f"Storey force coefficients and forces, wind toward {governing['angle']:g}°",
        "storeyColumns": [
            "z [m]",
            "CFx [m²]",
            "CFy [m²]",
            "CMz [m³]",
            "Cf along",
            "Fx [kN]",
            "Fy [kN]",
            "Mz [kN·m]",
        ],
        "storeyRows": storey_rows,
        "zoneTitle": f"Facade pressure coefficients, wind toward {governing['angle']:g}°",
        "zoneColumns": ["z [m]", "Zone", "Role", "Cp mean", "Cp min", "Cp max"],
        "zoneRows": zone_rows,
        "notes": notes,
    }


__all__ = [
    "FOLDER",
    "cancel",
    "detect",
    "directions",
    "envelope_of",
    "report_section",
    "results",
    "roughness",
    "start",
    "status",
    "write_cases",
]
