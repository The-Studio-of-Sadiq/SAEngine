"""Alpha 9 L11, the office tools over JSON-RPC (registered by :func:`register` in
:mod:`saengine.rpc.server`; the workbench calls them as ``EngineMethod`` through the
``saengine.office.request`` command):

- ``office/schedule`` ``{projectRoot, start?}`` -> the 4D programme generated and written
  (``10 BOQ/construction-schedule.json``) with the elements' dates
  (:mod:`saengine.boq.construction_schedule`; worker); ``office/reschedule`` ``{text}`` -> an
  edited programme's dates; ``office/exportSchedule`` ``{text, path, format: "csv" | "mspdi"}``;
  ``office/productivityTemplate`` ``{}`` -> the sample productivity rates;
- ``office/optimise`` ``{outDir, projectPath, ratesText?, options?}`` -> the cheapest passing
  options per member group (:mod:`saengine.design.cost_optimisation`; design worker);
  ``office/applyOptimisation`` ``{objectsText, result, accept?}`` -> the new 04 Objects text;
- ``office/takeoff`` ``{text}`` -> the takeoff's items measured and its bill lines
  (:mod:`saengine.boq.takeoff`); ``office/calibrate`` ``{a, b, length}`` -> the calibration;
- ``office/terrainImport`` ``{projectRoot, path, units?, crs?, datum?, platform?}``,
  ``office/terrainRecompute`` ``{projectRoot, platform?}`` and ``office/terrainMesh``
  ``{projectRoot}`` (:mod:`saengine.gis.terrain`; worker);
- ``office/sun`` ``{projectRoot, day?}``, ``office/daylight`` ``{projectRoot}``,
  ``office/noise`` ``{projectRoot}`` (:mod:`saengine.environment.service`; worker);
- ``office/fabrication`` ``{projectRoot, write?}`` -> the MEP runs detailed to LOD 400, the spool
  sheets written (:mod:`saengine.mep.fabrication`; worker);
- ``office/phaseBill`` ``{projectRoot}`` -> the bill split by phase, ``office/compareOptions``
  ``{projectRoot, options, ratesText?, carbonText?}`` -> design options side by side
  (:mod:`saengine.project.phasing`; worker).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _text(root: str, rel: str) -> str | None:
    try:
        return (Path(root) / rel).read_text(encoding="utf-8")
    except OSError:
        return None


def schedule(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.boq.construction_schedule import generate_for_project

    try:
        return generate_for_project(args["projectRoot"], args.get("start"))
    except ValueError as error:
        return {"problems": [str(error).strip().splitlines()[0]]}


def reschedule(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.boq.construction_schedule import reschedule_text

    return reschedule_text(args["text"])


def export_schedule(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.boq.construction_schedule import export

    try:
        return export(args["text"], args["path"], args.get("format") or "csv")
    except (ValueError, OSError) as error:
        return {"problems": [str(error).strip().splitlines()[0]]}


def productivity_template(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.boq.construction_schedule import sample_productivity_text

    return {"text": sample_productivity_text()}


def optimise(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.design.cost_optimisation import optimise as run

    try:
        return run(args["outDir"], args["projectPath"], args.get("ratesText"), args.get("options"))
    except (ValueError, OSError) as error:
        return {"problems": [str(error).strip().splitlines()[0]]}


def apply_optimisation(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.design.cost_optimisation import apply_optimisation as apply

    return apply(args["objectsText"], args["result"], args.get("accept"))


def takeoff(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.boq.takeoff import summary

    return summary(args["text"])


def calibrate(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.boq.takeoff import calibrate as run

    try:
        return run(args["a"], args["b"], float(args["length"]))
    except (ValueError, TypeError) as error:
        return {"problems": [str(error).strip().splitlines()[0]]}


def terrain_import(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.gis.terrain import import_survey

    return import_survey(
        args["projectRoot"],
        args["path"],
        args.get("units") or "m",
        args.get("crs"),
        args.get("datum"),
        args.get("platform"),
    )


def terrain_recompute(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.gis.terrain import recompute

    return recompute(args["projectRoot"], args.get("platform"))


def terrain_mesh(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.gis.terrain import mesh

    return mesh(args["projectRoot"])


def sun(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.environment.service import sun_study

    return sun_study(args["projectRoot"], args.get("day"))


def daylight(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.environment.service import daylight_study

    return daylight_study(args["projectRoot"])


def noise(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.environment.service import noise_study

    return noise_study(args["projectRoot"])


def fabrication(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.mep.fabrication import run_for_project

    return run_for_project(args["projectRoot"], args.get("write", True) is not False)


def phase_bill(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.project import phasing

    root = args["projectRoot"]
    boq = _text(root, "10 BOQ/boq.json")
    if not boq:
        return {"problems": ["Measure the bill of quantities (10 BOQ) first."]}
    try:
        found = phasing.parse(_text(root, phasing.PHASING_FILE))
    except ValueError as error:
        return {"problems": [str(error).strip().splitlines()[0]]}
    return phasing.phase_bill(json.loads(boq), found)


def compare_options(args: dict[str, Any]) -> dict[str, Any]:
    from saengine.project.phasing import compare_options as run

    return run(
        args["projectRoot"], list(args.get("options") or []), args.get("ratesText"),
        args.get("carbonText"),
    )  # fmt: skip


#: method -> (handler, where it runs: "now", "worker" or "design").
METHODS: dict[str, tuple[Callable[[dict[str, Any]], Any], str]] = {
    "office/schedule": (schedule, "worker"),
    "office/reschedule": (reschedule, "now"),
    "office/exportSchedule": (export_schedule, "worker"),
    "office/productivityTemplate": (productivity_template, "now"),
    "office/optimise": (optimise, "design"),
    "office/applyOptimisation": (apply_optimisation, "now"),
    "office/takeoff": (takeoff, "now"),
    "office/calibrate": (calibrate, "now"),
    "office/terrainImport": (terrain_import, "worker"),
    "office/terrainRecompute": (terrain_recompute, "worker"),
    "office/terrainMesh": (terrain_mesh, "worker"),
    "office/sun": (sun, "worker"),
    "office/daylight": (daylight, "worker"),
    "office/noise": (noise, "worker"),
    "office/fabrication": (fabrication, "worker"),
    "office/phaseBill": (phase_bill, "worker"),
    "office/compareOptions": (compare_options, "worker"),
}
