"""JSON-RPC 2.0 server over stdio (LSP base-protocol framing), built on pygls.

Methods:

- ``saengine/info`` -> versions of the backend stack
- ``project/validate`` ``{path}`` -> schema and reference check of an ``.osmodel``
- ``results/tables`` ``{outDir, projectPath?}`` -> result tables of a finished run
- ``results/list`` ``{outDir, projectPath}`` -> the results that can be shown in 3D
- ``results/view`` ``{outDir, projectPath, key, mode?}`` -> one result's shape and diagrams
- ``library/check`` ``{kind, text, materialsText?}`` -> rule violations in a library file
- ``section/analyse`` ``{text, materialsText?, projectRoot?, capacity?, surface?}`` -> a designed
  section's properties, interaction diagrams and P-Mx-My surface (Section Designer)
- ``structure/shapeGeometry`` ``{shape}`` -> a parametric shape's members, areas and supports
- ``structure/importGeometry`` ``{path, options, objectsText?}`` -> a DXF, DWG, IFC or Rhino
  file's
- ``cad/convertDwg`` ``{path, cache?}`` -> ``{ok, dxf, warnings, cached}``: a DWG drawing
  converted to DXF by GNU LibreDWG's dwg2dxf (``saengine.library.dwg``; a separate program, in a
  worker thread), or ``{ok: false, code, message}`` (``no-converter``, ``failed``)
- ``structure/insert`` ``{structureText, geometry}`` -> the structural model with them added
- ``structure/runScript`` ``{structureText, scriptPath}`` -> the model a script built
- ``design/report`` ``{outDir, projectPath}`` -> the RC member design checks of a run
- ``design/required`` ``{outDir, projectPath, options?}`` -> the reinforcement each element
  requires (``saengine.design.design_required``; kept in ``design-required.json`` beside the
  results while the project does not change; in a worker thread)
- ``design/proposal`` ``{outDir, projectPath, options?}`` -> the bars proposed per object type
  and foundation (``options.mode`` "byType" or "splitTypes"; in a worker thread)
- ``design/applyProposal`` ``{objectsText, bimText?, proposal, floorPlanText?,
  substructureText?}`` -> the part files with the proposal applied (pure)
- ``import/structural`` ``{path, destParent, name?, overwrite?}`` -> a new project from an
  ETABS (.e2k), STAAD.Pro (.std) or SAP2000 (.s2k) file (``{root, name, format, report,
  problems, files}`` or ``{error, problems}``; ``saengine.importers.project``; in a worker
  thread); ``library/steelSections`` ``{}`` -> the standard steel section table
- ``library/generateBuilding`` ``{spec, destParent, name?, overwrite?}`` -> a new building
  project generated from its grids and storeys (``{root, name, notes, summary, settingsPatch,
  files}`` or ``{error}``; ``saengine.project.new_building``; in a worker thread)
- ``soil/location`` ``{soilText, bimText?, settingsText?, projectRoot?}`` -> the site, boreholes and building
  outline in WGS 84 with the nearest BNBC town (``saengine.gis.site``)
- ``soil/gisExport`` ``{projectRoot, format: geojson|gpkg, outPath}`` -> ``{path, counts,
  problems}``; ``soil/gisImport`` ``{path, soilText?}`` -> ``{soilText, added, updated, ...}``
- ``soil/qgisProgram`` ``{}`` -> an installed QGIS launcher's path or null;
  ``soil/qgisCommand`` ``{program, filePath}`` -> the arguments that open the file in it
- ``boq/compute`` ``{bimText, objectsText, materialsText, projectRoot?}`` -> the bill of
  quantities (``projectRoot``: where the plumbing tanks' last designs give their bars)
- ``report/build`` ``{projectRoot, outPdf?}`` -> the PDF design report (``{path, pages, warnings}``)
- ``drawings/generate`` ``{projectRoot, sheets?, size?, designReportText?}`` -> the structural
  drawings written into ``11 Exports/Drawings`` (``{sheets, pdf, bbsCsv, generatedAt, size,
  stale, notes, problems}``; ``saengine.pipeline.drawings``; in a worker thread; ``sheets``: only
  those sheet numbers); ``drawings/list`` ``{projectRoot}`` -> the
  same for the last generation with ``stale``/``staleReason``/``changed``;
  ``drawings/progress`` ``{projectRoot}`` -> ``{running, step, index, count, message}``
- ``soil/report`` ``{soilText, settingsText?, projectRoot?}`` -> everything computed from the soil report
- ``soil/allowableBearing`` ``{soilText, settingsText?, x, y, foundingLevel, b, l,
  projectRoot?}`` -> qa [kPa]
  of a footing (lengths in mm)
- ``soil/import`` ``{path, soilText?}`` -> the soil report with a CSV or Excel file's boreholes
- ``soil/template`` ``{path}`` -> writes the borehole import template
- ``soil/settlement`` ``{soilText, borehole, b, l, df, q}`` -> a footing's settlement
- ``soil/sources`` ``{soilText?, settingsText?, projectRoot?}`` -> where the site class and qa come from
- ``fem/derive`` also takes ``soilText?`` (else the project's soil report beside ``modelFolder``)
- ``bim/ifc`` and ``boq/compute`` also take ``substructureText?`` and ``settingsText?``: the
  foundations of 9 Substructure (once it is no longer the placeholder) and the ground level
- ``substructure/report`` ``{projectRoot}`` -> the design checks of the saved substructure
- ``substructure/size`` ``{projectRoot, columns?}`` -> footings proposed by the sizing assistant
- ``substructure/migrate`` ``{projectRoot}`` -> the substructure with the building model's footings
- ``substructure/ensure`` ``{projectRoot}`` -> moves the footings into a placeholder substructure
- ``fem/derive`` also takes ``mepText?`` and ``substructureText?`` (else the project's files beside
  ``modelFolder``): the MEP openings and equipment loads, and the foundations of soil springs
- ``fem/ssiCompare`` ``{projectRoot}`` -> fixed base against soil springs (runs the fixed model)
- ``fem/meshCheck`` ``{projectRoot}`` -> the mesh convergence check of Run All (runs the gravity
  cases on the project's mesh and a coarser one; ``{"skipped"}`` when not needed)
- ``fem/seismicDesign`` ``{outDir, projectPath}`` -> the response spectrum design of a run
  (scaling, orthogonal rule, accidental torsion, drifts, combinations; runs the modal forces
  once per run; null when the project designs from the static cases; in a worker thread)
- ``fem/secondOrder`` ``{outDir, projectPath}`` -> the P-Delta drift amplification and the
  stability coefficient θ of a run (``{"method": "none"}`` for a first-order model)
- ``fem/storyResponse`` ``{outDir, projectPath}`` -> storey displacements, drifts, forces,
  shears and overturning per case and combination, modal participation, the design spectrum,
  base reactions, pushover and time-history curves (``saengine.fem.story_response``; worker)
- ``fem/memberForces`` ``{outDir, projectPath, member}`` -> a member's section forces and
  deflection along it per case and combination (``saengine.fem.member_detail``; worker)
- ``fem/columnInteraction`` ``{outDir, projectPath, member?}`` -> the columns' P-M interaction
  diagrams and demand points (once per run, cached beside the results; worker)
- ``fem/exportXlsx`` ``{path, sheets: [{name, columns, rows, notes?}]}`` -> the tables written
  to an Excel workbook (``{path, sheets}``; worker)
- ``mep/report`` ``{projectRoot, outDir?, mepText?}`` -> the MEP coordination report
- ``mep/suggestSleeves`` ``{projectRoot, mepText?, allowance?}`` -> sleeves for the clashes
- ``mep/importIfc`` ``{projectRoot, path, copy?}`` -> what an MEP IFC model holds
- ``mep/plumbingReport`` ``{projectRoot, mepText?}`` -> the plumbing report (BNBC 2020 Part 8
  sizing, ``tankDesigns``, ``hydraulics``, missing sleeves), JSON-safe
- ``mep/plumbingSizeTanks`` ``{projectRoot, mepText?}`` -> ``{tanks, notes}`` proposed tanks
- ``mep/plumbingSleeves`` ``{projectRoot, mepText?}`` -> ``{openings, notes}`` missing sleeves
- ``mep/plumbingOccupancies`` ``{}`` -> ``{occupancies}`` BNBC Table 8.5.1's rows
- ``mep/hvacReport`` ``{projectRoot, mepText?}`` -> the cooling loads (the cached EnergyPlus run
  of this input, else the estimate; EnergyPlus is not started) and the air side under ``air``
- ``mep/hvacLoads`` ``{projectRoot, mepText?}`` -> the same after running EnergyPlus version
  26.2.0 (a separate process, in a worker thread so the other methods keep answering)
- ``mep/hvacCancelLoads`` ``{}`` -> ``{cancelled}`` stops the EnergyPlus runs in progress
- ``mep/hvacProposePlant`` ``{projectRoot, mepText?}`` -> ``{plant, notes}`` proposed plant
- ``mep/hvacDuctOpenings`` ``{projectRoot, mepText?}`` -> ``{openings, conflicts, stale, notes}``
- ``mep/hvacTables`` ``{}`` -> ``{cities, uses}`` BNBC Tables 8.2.2 (2 %) and 8.2.3
- ``mep/hvacConstructions`` ``{}`` -> ``{wall, roof, glazing}`` with their U-values
- ``mep/electricalReport`` ``{projectRoot, mepText?}`` -> the electrical coordination report
- ``mep/electricalProposeEquipment`` ``{projectRoot, mepText?}`` -> ``{equipment, notes}``
- ``mep/electricalOpenings`` ``{projectRoot, mepText?}`` -> ``{openings, notes}`` still missing
- ``mep/electricalUses`` ``{}`` -> ``{uses}`` BNBC Table 8.1.17's rows
- ``mep/fireReport`` ``{projectRoot, mepText?}`` -> the fire protection report (BNBC 2020 Part 4
  systems, sprinklers, hydraulics, reservoir, pumps, ``tankDesigns``, missing sleeves; in a
  worker thread, as the plumbing report)
- ``mep/fireProposals`` ``{projectRoot, mepText?}`` -> ``{tanks, pumps, notes}`` proposed
- ``mep/fireOpenings`` ``{projectRoot, mepText?}`` -> ``{openings, notes}`` still missing
- ``project/exportArchive`` ``{projectRoot, outPath, includeResults?, includeVersions?,
  includeExports?, note?, saengineVersion?}`` -> ``{path, size, files, skipped, problems}``: the
  project as one ``.civil`` file (``saengine.project.archive``; in a worker thread)
- ``project/inspectArchive`` ``{path, currentVersion?, verify?}`` -> ``{manifest, problems, ok}``
- ``project/importArchive`` ``{path, destParent, name?, overwrite?, currentVersion?, migrate?}``
  -> ``{root, name, files, problems, migrated, pending}`` (in a worker thread)
- ``codes/list`` ``{root?}`` -> every code pack (``PackInfo``: built-in, the user's, the
  project's, shadowed ones included); ``codes/show`` ``{id, root?}`` -> the pack in force with
  its manifest; ``codes/new`` ``{id, name, extends, scope?, dest?, root?}`` -> ``{path}`` of a new
  pack's skeleton; ``codes/install`` ``{path, scope, root?}``; ``codes/validate`` ``{path,
  root?}``; ``codes/trust`` ``{id, trusted, root?}`` (``saengine.codes``). Every request with a
  ``projectRoot``/``root``/``projectPath``/``modelFolder``/``outDir`` runs with that project's
  own code packs available (:mod:`saengine.codes.context`).
- ``versions/status`` ``{projectRoot}``, ``versions/list`` ``{projectRoot, limit?}``,
  ``versions/save`` ``{projectRoot, message, author?, issued?, label?}``, ``versions/diff``
  ``{projectRoot, fromVersion?, toVersion?}``, ``versions/restore`` ``{projectRoot, version, parts?, author?,
  commit?}``, ``versions/markIssued`` ``{projectRoot, version, label, author?}``: the project's
  version history (``saengine.project.versions``; in threads of their own, one operation at a
  time per project, so a long save never holds up the other methods)

A refused archive or versions operation answers ``{ok: false, code, message, problems}``.

Analyses themselves are not run here: the workbench starts
``python -m opensees_studio.run`` per run, so an OpenSees hard exit can never take
this long-lived server down.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, BinaryIO

from pygls.protocol import JsonRPCProtocol, default_converter
from pygls.server import JsonRPCServer

from saengine.codes import context as code_context
from saengine.rpc import handlers


def _plain(value: Any) -> Any:
    """pygls hands untyped params over as named tuples; turn them back into JSON values."""
    if hasattr(value, "_asdict"):
        return {k: _plain(v) for k, v in value._asdict().items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


# This server only reads analysis results (each run writes them from its own process, the
# manifest last). On Windows HDF5 locks a file exclusively even to read it, so two threads
# reading the same case (the design checks, and the charts of a run that has just finished)
# failed with "unable to lock file": no locking here. Set before h5py loads HDF5.
os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

# Long requests (EnergyPlus, tank designs, archives) run in these threads while the server keeps
# answering. Not pygls's ``server.thread()``: its pool also reads stdin, and a result computed
# there could wait for the client's next message before it was sent.
_WORKERS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="saengine-rpc")


#: Parameters that name the project (or a file or folder inside it) a request works on.
_ROOT_PARAMS = ("projectRoot", "root", "projectPath", "modelFolder", "outDir")


def _request_root(params: Any) -> str | None:
    for key in _ROOT_PARAMS:
        value = params.get(key) if isinstance(params, dict) else getattr(params, key, None)
        if isinstance(value, str) and value:
            return value
    return None


def _scoped(handler: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """``handler`` run with the request's project as the code packs' project (integration glue:
    a project's own code packs, ``02 Project Settings/code-packs``, are found while it runs;
    :func:`saengine.codes.context.project`)."""

    @functools.wraps(handler)
    def call(params: Any) -> Any:
        root = _request_root(params)
        if root is None:
            return handler(params)
        with code_context.project(root):
            return handler(params)

    return call


def _in_worker(handler: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """``handler`` run in a worker thread; its answer is sent as soon as it is ready."""
    scoped = _scoped(handler)

    @functools.wraps(handler)
    async def run(params: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(_WORKERS, scoped, params)

    return run


# The version history (dulwich hashing and writing every file of a project, which takes seconds
# with large drawings or scans) runs in its own threads, so neither the quick requests nor the
# long ones above wait behind a save; one operation at a time per project, so two saves, or a
# status read during a restore, never see a half-written index or branch.
_VERSIONS_WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="saengine-versions")
_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


def _project_lock(root: str) -> threading.Lock:
    key = os.path.normcase(os.path.abspath(root))
    with _PROJECT_LOCKS_GUARD:
        return _PROJECT_LOCKS.setdefault(key, threading.Lock())


def _versions_worker(handler: Callable[[dict[str, Any]], Any]) -> Callable[[Any], Any]:
    """``handler`` (given the plain params) run in a versions thread under its project's lock."""

    def locked(params: Any) -> Any:
        args = _plain(params)
        with _project_lock(str(args["projectRoot"])), code_context.project(args["projectRoot"]):
            return handler(args)

    @functools.wraps(handler)
    async def run(params: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(_VERSIONS_WORKERS, locked, params)

    return run


def create_server() -> JsonRPCServer:
    server = JsonRPCServer(protocol_cls=JsonRPCProtocol, converter_factory=default_converter)
    feature = server.feature

    def scoped_feature(*args: Any, **kwargs: Any) -> Callable[[Callable], Callable]:
        register = feature(*args, **kwargs)

        def decorate(fn: Callable) -> Callable:
            return register(fn if asyncio.iscoroutinefunction(fn) else _scoped(fn))

        return decorate

    server.feature = scoped_feature  # type: ignore[method-assign]

    @server.feature("saengine/info")
    def _info(params: Any) -> dict[str, Any]:
        return handlers.info()

    @server.feature("project/validate")
    def _validate(params: Any) -> dict[str, Any]:
        return handlers.validate_project(_plain(params)["path"])

    @server.feature("results/tables")
    def _results_tables(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.results_tables(args["outDir"], args.get("projectPath"))

    @server.feature("results/list")
    def _result_list(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.result_list(args["outDir"], args["projectPath"])

    @server.feature("results/view")
    def _result_view(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.result_view(
            args["outDir"], args["projectPath"], args["key"], args.get("mode")
        )

    @server.feature("library/check")
    def _check_library(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.check_library(args["kind"], args["text"], args.get("materialsText"))

    @_in_worker
    def _section_analyse_worker(params: Any) -> dict[str, Any]:
        from saengine.library.section_designer import analyse

        args = _plain(params)
        return analyse(
            args["text"],
            args.get("materialsText"),
            args.get("projectRoot"),
            capacity=args.get("capacity", True),
            surface=args.get("surface", False),
        )

    @server.feature("section/analyse")
    async def _section_analyse(params: Any) -> dict[str, Any]:
        # The first imports of numpy, sectionproperties and concreteproperties are not safe from
        # two threads at once (numpy's C extension half-initialised): done here, on the server's
        # thread, before the analysis goes to a worker.
        import concreteproperties.concrete_section  # noqa: F401
        import sectionproperties.analysis.section  # noqa: F401

        import saengine.library.section_designer  # noqa: F401

        return await _section_analyse_worker(params)

    @server.feature("bim/generate")
    def _generate_building(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.generate_building(args["floorPlanText"], args.get("bimText"))

    @server.feature("bim/generateFromStructure")
    def _generate_from_structure(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.generate_building_from_structure(args["structureText"], args.get("bimText"))

    @server.feature("fem/derive")
    def _derive_fem(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.derive_fem(
            args["bimText"],
            args["objectsText"],
            args["materialsText"],
            args["settingsText"],
            args.get("modelFolder"),
            args.get("soilText"),
            args.get("mepText"),
            args.get("substructureText"),
            args.get("loadsText"),
        )

    @server.feature("bim/ifc")
    def _building_ifc(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.building_ifc(
            args["bimText"],
            args["objectsText"],
            args.get("materialsText"),
            args.get("name") or "Project",
            args.get("substructureText"),
            args.get("settingsText"),
            args.get("mepText"),
        )

    @server.feature("structure/shapeGeometry")
    def _shape_geometry(params: Any) -> dict[str, Any]:
        return handlers.shape_geometry(_plain(params)["shape"])

    @server.feature("structure/importGeometry")
    @_in_worker  # a DWG is converted first (seconds)
    def _import_geometry(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.import_geometry(
            args["path"], args.get("options") or {}, args.get("objectsText")
        )

    @server.feature("cad/convertDwg")
    @_in_worker
    def _convert_dwg(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.convert_dwg(args["path"], args.get("cache"))

    @server.feature("structure/insert")
    def _insert_geometry(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.insert_geometry(args["structureText"], args["geometry"])

    @server.feature("structure/runScript")
    def _run_script(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.run_script(args["structureText"], args["scriptPath"])

    @server.feature("design/report")
    @_in_worker
    def _design_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.design_report(args["outDir"], args["projectPath"])

    @server.feature("design/required")
    @_in_worker
    def _design_required(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.design_required(args["outDir"], args["projectPath"], args.get("options"))

    @server.feature("design/proposal")
    @_in_worker
    def _design_proposal(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.design_proposal(args["outDir"], args["projectPath"], args.get("options"))

    @server.feature("design/applyProposal")
    def _design_apply_proposal(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.design_apply_proposal(
            args["objectsText"],
            args.get("bimText"),
            args["proposal"],
            args.get("floorPlanText"),
            args.get("substructureText"),
        )

    @server.feature("import/structural")
    @_in_worker
    def _import_structural(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.import_structural(
            args["path"], args["destParent"], args.get("name"), bool(args.get("overwrite"))
        )

    @server.feature("library/generateBuilding")
    @_in_worker
    def _new_building(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.new_building(
            args["spec"], args["destParent"], args.get("name"), bool(args.get("overwrite"))
        )

    @server.feature("library/steelSections")
    def _steel_sections(params: Any) -> dict[str, Any]:
        return handlers.steel_sections()

    @server.feature("boq/compute")
    def _compute_boq(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.compute_boq(
            args["bimText"],
            args["objectsText"],
            args["materialsText"],
            args.get("substructureText"),
            args.get("settingsText"),
            args.get("mepText"),
            args.get("projectRoot"),
        )

    @server.feature("report/build")
    def _build_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.build_report(args["projectRoot"], args.get("outPdf"))

    # Detailing, the schedule and the sheets take seconds to tens of seconds: in a worker thread,
    # with ``drawings/progress`` answering meanwhile; ``drawings/list`` only reads files.
    @server.feature("drawings/generate")
    @_in_worker
    def _drawings_generate(params: Any) -> dict[str, Any]:
        args = _plain(params)
        # The design report as JSON text: pygls would turn its keys into names (digits, spaces).
        text = args.get("designReportText")
        return handlers.drawings_generate(
            args["projectRoot"],
            args.get("sheets"),
            args.get("size"),
            json.loads(text) if text else None,
        )

    @server.feature("drawings/list")
    def _drawings_list(params: Any) -> dict[str, Any]:
        return handlers.drawings_list(_plain(params)["projectRoot"])

    @server.feature("drawings/progress")
    def _drawings_progress(params: Any) -> dict[str, Any]:
        return handlers.drawings_progress(_plain(params)["projectRoot"])

    @server.feature("soil/report")
    def _soil_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.soil_report(args["soilText"], args.get("settingsText"))

    @server.feature("soil/allowableBearing")
    def _soil_allowable_bearing(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.allowable_bearing(
            args["soilText"],
            args.get("settingsText"),
            args["x"],
            args["y"],
            args["foundingLevel"],
            args["b"],
            args["l"],
        )

    @server.feature("soil/import")
    def _soil_import(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.import_soil(args["path"], args.get("soilText"))

    @server.feature("soil/template")
    def _soil_template(params: Any) -> dict[str, Any]:
        return handlers.soil_template(_plain(params)["path"])

    @server.feature("soil/settlement")
    def _soil_settlement(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.soil_settlement(
            args["soilText"], args["borehole"], args["b"], args["l"], args["df"], args["q"]
        )

    @server.feature("soil/sources")
    def _soil_sources(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.soil_sources(args.get("soilText"), args.get("settingsText"))

    @server.feature("soil/location")
    @_in_worker
    def _soil_location(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.soil_location(
            args.get("soilText"), args.get("bimText"), args.get("settingsText")
        )

    @server.feature("soil/gisExport")
    @_in_worker
    def _soil_gis_export(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.gis_export(args["projectRoot"], args["format"], args["outPath"])

    @server.feature("soil/gisImport")
    @_in_worker
    def _soil_gis_import(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.gis_import(args["path"], args.get("soilText"))

    @server.feature("soil/qgisProgram")
    @_in_worker
    def _soil_qgis_program(params: Any) -> str | None:
        return handlers.qgis_program()

    @server.feature("soil/qgisCommand")
    def _soil_qgis_command(params: Any) -> list[str] | dict[str, Any]:
        args = _plain(params)
        return handlers.qgis_command(args["program"], args["filePath"])

    @server.feature("substructure/report")
    def _substructure_report(params: Any) -> dict[str, Any]:
        return handlers.substructure_report(_plain(params)["projectRoot"])

    @server.feature("substructure/size")
    def _substructure_size(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.substructure_size(args["projectRoot"], args.get("columns"))

    @server.feature("substructure/migrate")
    def _substructure_migrate(params: Any) -> dict[str, Any]:
        return handlers.substructure_migrate(_plain(params)["projectRoot"])

    @server.feature("substructure/ensure")
    def _substructure_ensure(params: Any) -> dict[str, Any]:
        return handlers.substructure_ensure(_plain(params)["projectRoot"])

    @server.feature("fem/meshCheck")
    @_in_worker
    def _mesh_check(params: Any) -> dict[str, Any]:
        return handlers.mesh_check(_plain(params)["projectRoot"])

    @server.feature("fem/ssiCompare")
    def _ssi_compare(params: Any) -> dict[str, Any]:
        return handlers.ssi_compare(_plain(params)["projectRoot"])

    @server.feature("fem/seismicDesign")
    @_in_worker
    def _seismic_design(params: Any) -> dict[str, Any] | None:
        args = _plain(params)
        return handlers.seismic_design(args["outDir"], args["projectPath"])

    @server.feature("fem/secondOrder")
    @_in_worker
    def _second_order(params: Any) -> dict[str, Any] | None:
        args = _plain(params)
        return handlers.second_order_summary(args["outDir"], args["projectPath"])

    @server.feature("fem/storyResponse")
    @_in_worker
    def _story_response(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.story_response(args["outDir"], args["projectPath"])

    @server.feature("fem/memberForces")
    @_in_worker
    def _member_forces(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.member_forces(args["outDir"], args["projectPath"], args["member"])

    @server.feature("fem/columnInteraction")
    @_in_worker
    def _column_interaction(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.column_interaction(args["outDir"], args["projectPath"], args.get("member"))

    @server.feature("fem/exportXlsx")
    @_in_worker
    def _export_xlsx(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.export_xlsx(args["path"], args["sheets"])

    @server.feature("mep/report")
    def _mep_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.mep_report(args["projectRoot"], args.get("outDir"), args.get("mepText"))

    @server.feature("mep/suggestSleeves")
    def _mep_suggest_sleeves(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.mep_suggest_sleeves(
            args["projectRoot"], args.get("mepText"), args.get("allowance")
        )

    @server.feature("mep/importIfc")
    def _mep_import_ifc(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.mep_import_ifc(args["projectRoot"], args["path"], bool(args.get("copy")))

    # A project's first tank designs take about half a minute (cached after): in a worker thread,
    # so the editor's other requests (the HVAC and electrical reports) are answered meanwhile.
    @server.feature("mep/plumbingReport")
    @_in_worker
    def _plumbing_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.plumbing_report(
            args["projectRoot"], args.get("mepText"), args.get("designs", True)
        )

    @server.feature("mep/plumbingSizeTanks")
    def _plumbing_size_tanks(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.plumbing_size_tanks(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/plumbingSleeves")
    def _plumbing_sleeves(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.plumbing_sleeves(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/plumbingOccupancies")
    def _plumbing_occupancies(params: Any) -> dict[str, Any]:
        return handlers.plumbing_occupancies()

    @server.feature("mep/hvacReport")
    def _hvac_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hvac_report(args["projectRoot"], args.get("mepText"))

    # EnergyPlus takes up to half a minute: in a worker thread, so the editor's other requests
    # (and mep/hvacCancelLoads) are answered meanwhile.
    @server.feature("mep/hvacLoads")
    @_in_worker
    def _hvac_loads(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hvac_report(args["projectRoot"], args.get("mepText"), calculate=True)

    @server.feature("mep/hvacCancelLoads")
    def _hvac_cancel_loads(params: Any) -> dict[str, Any]:
        return handlers.hvac_cancel_loads()

    @server.feature("mep/hvacProposePlant")
    def _hvac_propose_plant(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hvac_propose_plant(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/hvacDuctOpenings")
    def _hvac_duct_openings(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hvac_duct_openings(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/hvacTables")
    def _hvac_tables(params: Any) -> dict[str, Any]:
        return handlers.hvac_tables()

    @server.feature("mep/hvacConstructions")
    def _hvac_constructions(params: Any) -> dict[str, Any]:
        return handlers.hvac_constructions()

    @server.feature("mep/electricalReport")
    def _electrical_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.electrical_report(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/electricalProposeEquipment")
    def _electrical_propose_equipment(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.electrical_propose_equipment(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/electricalOpenings")
    def _electrical_openings(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.electrical_openings(args["projectRoot"], args.get("mepText"))

    # The fire tanks' first designs take as long as the plumbing tanks': in a worker thread.
    @server.feature("mep/fireReport")
    @_in_worker
    def _fire_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fire_report(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/fireProposals")
    def _fire_proposals(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fire_propose(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/fireOpenings")
    def _fire_openings(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fire_openings(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/electricalUses")
    def _electrical_uses(params: Any) -> dict[str, Any]:
        return handlers.electrical_uses()

    # A project's archive can hold large result files: in a worker thread.
    @server.feature("project/exportArchive")
    @_in_worker
    def _export_archive(params: Any) -> dict[str, Any]:
        args = _plain(params)
        # Under the project's versions lock: the archive may copy the version history.
        with _project_lock(str(args["projectRoot"])):
            return handlers.project_export_archive(
                args["projectRoot"],
                args["outPath"],
                bool(args.get("includeResults")),
                bool(args.get("includeVersions")),
                args.get("includeExports") is not False,
                args.get("note"),
                args.get("saengineVersion"),
            )

    @server.feature("project/inspectArchive")
    def _inspect_archive(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.project_inspect_archive(
            args["path"], args.get("currentVersion"), args.get("verify") is not False
        )

    @server.feature("project/importArchive")
    @_in_worker
    def _import_archive(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.project_import_archive(
            args["path"],
            args["destParent"],
            args.get("name"),
            bool(args.get("overwrite")),
            args.get("currentVersion"),
            args.get("migrate") is not False,
        )

    @server.feature("versions/status")
    @_versions_worker
    def _versions_status(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.versions_status(args["projectRoot"])

    @server.feature("versions/list")
    @_versions_worker
    def _versions_list(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.versions_list(args["projectRoot"], args.get("limit") or 200)

    @server.feature("versions/save")
    @_versions_worker
    def _versions_save(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.versions_save(
            args["projectRoot"],
            args["message"],
            args.get("author"),
            bool(args.get("issued")),
            args.get("label"),
        )

    @server.feature("versions/diff")
    @_versions_worker
    def _versions_diff(args: dict[str, Any]) -> dict[str, Any]:
        # Not "from": pygls turns params into named tuples, which rename Python keywords.
        return handlers.versions_diff(
            args["projectRoot"], args.get("fromVersion"), args.get("toVersion")
        )

    @server.feature("versions/restore")
    @_versions_worker
    def _versions_restore(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.versions_restore(
            args["projectRoot"],
            args["version"],
            args.get("parts"),
            args.get("author"),
            args.get("commit") is not False,
        )

    @server.feature("versions/markIssued")
    @_versions_worker
    def _versions_mark_issued(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.versions_mark_issued(
            args["projectRoot"], args["version"], args["label"], args.get("author")
        )

    # Code packs (Project Settings' Design code, the Code Packs page).
    @server.feature("codes/list")
    def _codes_list(params: Any) -> list[dict[str, Any]]:
        return handlers.codes_list(_plain(params).get("root"))

    @server.feature("codes/show")
    def _codes_show(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_show(args["id"], args.get("root"))

    @server.feature("codes/new")
    def _codes_new(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_new(
            args["id"],
            args.get("name") or "",
            args.get("extends"),
            args.get("scope") or "user",
            args.get("dest"),
            args.get("root"),
        )

    @server.feature("codes/install")
    @_in_worker
    def _codes_install(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_install(args["path"], args.get("scope") or "user", args.get("root"))

    @server.feature("codes/validate")
    def _codes_validate(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_validate(args["path"], args.get("root"))

    @server.feature("codes/trust")
    def _codes_trust(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_trust(args["id"], bool(args.get("trusted")), args.get("root"))

    return server


def _claim_stdout() -> BinaryIO:
    """Keep the real stdout for the protocol and send fd 1 to stderr.

    Native libraries (OpenSees, HDF5) print straight to fd 1; without this a stray
    banner would corrupt the JSON-RPC stream.
    """
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(protocol_fd, "wb", buffering=0)


def _claim_stdin() -> BinaryIO:
    """Keep the real stdin for the protocol and give fd 0 the null device.

    On Windows a pipe with a read pending (the protocol reader waits on stdin between messages)
    blocks every other call on it, and each native extension loaded for the first time (scipy,
    OpenBLAS) asks the standard input for its type: an import in a worker thread then waited
    for the client's next message. The protocol reads its own duplicate of the pipe instead,
    and programs started by the backend no longer inherit (and could read) it.
    """
    protocol_fd = os.dup(0)
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    return os.fdopen(protocol_fd, "rb")


def main() -> int:
    stdin = _claim_stdin()
    stdout = _claim_stdout()
    server = create_server()
    # numpy's extension must finish initialising before any thread imports it: two threads
    # importing it at once fail with "partially initialized module" (seen on the first soil
    # report while the warm-ups ran). So import it here, then warm up in one thread, in turn.
    import numpy  # noqa: F401

    def warm() -> None:
        # WNTR's first import takes a second or two: done ahead of the editor's first request.
        handlers.warm_plumbing()
        handlers.warm_services()

    threading.Thread(target=warm, name="warm-imports", daemon=True).start()
    server.start_io(stdin, stdout)
    return 0
