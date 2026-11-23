"""JSON-RPC 2.0 server over stdio (LSP base-protocol framing), built on pygls.

Methods:

- ``saengine/info`` -> versions of the backend stack
- ``saengine/jobs`` ``{}`` -> ``{jobs: [{id, method, seconds, note, noteSeconds}]}``: the requests
  the server is working on and what each is doing (:mod:`saengine.rpc.jobs`), answered on the
  server's own thread; the design work runs in threads of its own (``_DESIGN_WORKERS``)
- ``saengine/cancelJobs`` ``{methods}`` -> ``{cancelled}``: cancels the running requests of
  those methods; their work stops at its next check (``saengine.rpc.jobs.check``)
- ``actions/list`` ``{kind?}`` -> the actions' catalogue (each with ``kind`` and ``writes``);
  ``actions/run`` ``{projectRoot, steps, overrides?, write?, stopOnError?}`` -> a batch's
  ``{ok, results, changes, failed_step, written, cancelled, version}``; ``actions/cancel``
  ``{}`` -> ``{cancelled}`` stops the batches in progress before their next step (a Run All at
  its next step boundary); they answer what was done (``saengine.actions``)
- ``project/validate`` ``{path}`` -> schema and reference check of an ``.osmodel``
- ``results/tables`` ``{outDir, projectPath?}`` -> result tables of a finished run
- ``results/list`` ``{outDir, projectPath}`` -> the results that can be shown in 3D
- ``results/view`` ``{outDir, projectPath, key, mode?}`` -> one result's shape and diagrams
- ``library/check`` ``{kind, text, materialsText?}`` -> rule violations in a library file
- ``library/limits`` ``{kind?, projectRoot?}`` -> ``{rules}``: the input guardrails with the
  limits of the project's code pack filled in (``saengine.library.guardrails.resolved_rules``),
  which the editors and the New Project wizard check each field against as it is typed
- ``section/analyse`` ``{text, materialsText?, projectRoot?, capacity?, surface?,
  momentCurvature?, contourAt?}`` -> a designed section's properties, interaction diagrams,
  P-Mx-My surface, moment-curvature curve and M-M contour (Section Designer)
- ``architecture/importIfc`` ``{path, architectureText?, floorPlanText}`` -> an architect's IFC
  walls, doors, windows and spaces adopted into the architecture, with what was skipped (in a
  worker thread)
- ``architecture/inspectDrawing`` ``{path}`` -> an architect's DWG/DXF: its layers, unit and a
  preview, for the layer-mapping step (in a worker thread)
- ``architecture/importDrawing`` ``{path, architectureText?, floorPlanText, options}`` -> an
  architect's DWG/DXF plan's walls, doors, windows and room names adopted onto one story, with
  what was skipped (in a worker thread)
- ``architecture/check`` ``{architectureText, floorPlanText?}`` -> the architecture's problems and
  its rooms' net outlines and areas
- ``architecture/ramps`` ``{architectureText, settingsText?}`` -> every ramp checked against the
  code pack's ramp rules (gradient, flight, width, landings, handrails)
- ``structure/shapeGeometry`` ``{shape}`` -> a parametric shape's members, areas and supports
- ``structure/importGeometry`` ``{path, options, objectsText?}`` -> a DXF, DWG, IFC or Rhino
  file's
- ``cad/convertDwg`` ``{path, cache?}`` -> ``{ok, dxf, warnings, cached}``: a DWG drawing
  converted to DXF by GNU LibreDWG's dwg2dxf (``saengine.library.dwg``; a separate program, in a
  worker thread), or ``{ok: false, code, message}`` (``no-converter``, ``failed``)
- ``cad/convertPdf`` ``{path, page?, cache?, pagesOnly?}`` -> ``{ok, dxf, page, pages, vector,
  size, segments, warnings, cached, scale}`` (``pagesOnly``: ``{ok, pages}``): one page of an architect's PDF as DXF, with its lines for object
  snaps (``saengine.library.pdf_underlay``; in a worker thread), or ``{ok: false, code, message}``
- ``cad/convertPointCloud`` ``{path, cut, thickness, voxel?, tolerance?, trace?}`` -> ``{ok,
  dxf, points, total, segments, bounds, warnings, cached}``: a plan slice of a LAS / XYZ / PTS
  scan as DXF with its traced lines for object snaps (alpha 9 L2, ``saengine.library.
  point_cloud``; in a worker thread), or ``{ok: false, code, message}`` (``needs-library``,
  ``failed``)
- ``cad/pointCloudView`` ``{path, voxel?, limit?}`` -> ``{ok, positions, colors, count, total,
  bounds}``: the scan decimated for the 3D view
- ``cad/snapPointCloud`` ``{path, cut, thickness, voxel?, x, y, radius}`` -> ``{ok, point}``
- ``cad/cleanDxf`` ``{paths}`` -> ``{ok, files: [{path, fixed, errors}]}``: DXF files the app
  wrote repaired in place by ezdxf's auditor (``saengine.library.dxf_audit``)
- ``workbook/export`` ``{outPath, floorPlanText, objectsText?, loadsText?}`` -> ``{ok, path,
  sheets}``: grids, stories, members, sections and member loads as an Excel workbook;
  ``workbook/import`` ``{path, floorPlanText, objectsText?, loadsText?}`` -> ``{ok, problems,
  diff, texts, changed}``: an edited workbook validated, with the new files and what changed
  (``saengine.library.workbook``; in a worker thread)
- ``components/list`` ``{}`` -> the setup's optional components the backend runs (EnergyPlus,
  LibreDWG): ``{energyplus, libredwg}``, each ``{state, path?}`` (``installed``, ``elsewhere``,
  ``missing``; ``handlers.installer_components``)
- ``hazard/offers`` ``{settingsText, soilText?, root?, latitude?, longitude?}`` -> ``{ok,
  codePack, coordinates, params, providers: [{id, service, host, url, query, problem?}],
  manualNote}``: the code pack's hazard services and the exact query (no network; alpha 9 C22)
- ``hazard/lookup`` ``{settingsText, provider, consent, soilText?, root?, latitude?,
  longitude?}`` -> ``{ok, values, source}`` or ``{ok: false, code, message}``: the site's
  values from the service (only the coordinates and code parameters are sent; refused
  without ``consent``; in a worker thread)
- ``ai/searchCode`` ``{query, projectRoot?, limit?, docs?}`` -> ``{pack, query, found, passages,
  note}``: the code pack's passages (and the manual's) that best match a question, each with
  its clauses, for the AI assistant's code Q&A (``saengine.ai.knowledge``; in a worker thread)
- ``structure/insert`` ``{structureText, geometry}`` -> the structural model with them added
- ``structure/runScript`` ``{structureText, scriptPath}`` -> the model a script built
- ``design/report`` ``{outDir, projectPath}`` -> the RC member design checks of a run
- ``design/required`` ``{outDir, projectPath, options?}`` -> the reinforcement each element
  requires (``saengine.design.design_required``; kept in ``design-required.json`` beside the
  results while the project does not change; in a worker thread)
- ``design/proposal`` ``{outDir, projectPath, options?}`` -> the bars proposed per object type
  and foundation (``options.mode`` "byType" or "splitTypes"; in a worker thread)
- ``design/strutAndTie`` ``{model, projectPath?}`` -> a strut-and-tie model of a D-region
  solved and checked with the project's code pack (``saengine.design.stm_model``);
  ``design/strutAndTieTemplate`` ``{template, parameters?}`` -> ``{model}`` to start from
- ``design/applyProposal`` ``{objectsText, bimText?, proposal, floorPlanText?,
  substructureText?}`` -> the part files with the proposal applied (pure)
- ``import/structural`` ``{path, destParent, name?, overwrite?}`` -> a new project from an
  ETABS (.e2k), STAAD.Pro (.std) or SAP2000 (.s2k) file (``{root, name, format, report,
  problems, files}`` or ``{error, problems}``; ``saengine.importers.project``; in a worker
  thread); ``library/steelSections`` ``{}`` -> the standard steel section table
- ``export/e2k`` ``{projectRoot, outPath?, units?, lateral?}`` -> the project as an ETABS text
  model in ``11 Exports/ETABS`` with its export report (``{path, reportPath, report}`` or
  ``{error}``; ``saengine.exporters.etabs``; in a worker thread)
- Alpha 9 L12 (``_register_l12``): ``export/exchange`` ``{projectRoot, format: s2k|std|saf|sdnf|
  cis2|webViewer, outPath?}`` -> ``{path, reportPath, readablePath, report}`` or ``{error}``
  (``saengine.exporters.exchange``, ``.web_viewer``; worker); ``office/submit`` ``{projectRoot,
  server, token, steps?}`` -> ``{id}``, ``office/status`` / ``office/cancel`` ``{id}``,
  ``office/info`` ``{server, token}`` (``saengine.office.client``; only the server given is
  contacted); ``graph/nodeTypes``, ``graph/list`` / ``graph/create`` ``{projectRoot, name?}``,
  ``graph/check`` ``{graph}``, ``graph/run`` ``{graph|path, projectRoot?, until?}``
  (``saengine.automation.graph``); ``studies/list|start|status|cancel|apply`` ``{projectRoot,
  study|id, variant?}`` (``saengine.automation.studies``); ``drawings/automate`` ``{projectRoot,
  sheets?, actions}`` (``saengine.drawings.automation``)
- ``fabrication/shopDrawings``, ``fabrication/nc``, ``fabrication/bvbs`` ``{projectRoot}`` -> the
  steel shop drawings (``11 Exports/Shop Drawings``), the DSTV NC files (``11 Exports/nc``) and
  the BVBS rebar files (``11 Exports/bvbs``): ``{folder, files, notes, problems}`` or
  ``{error}`` (``saengine.fabrication.export``, alpha 9 L10; in a worker thread)
- ``library/generateBuilding`` ``{spec, destParent, name?, overwrite?, site?}`` -> a new building
  project generated from its grids and storeys (``{root, name, notes, summary, settingsPatch,
  files}`` or ``{error}``; ``saengine.project.new_building``; in a worker thread)
- ``soil/location`` ``{soilText, bimText?, settingsText?, projectRoot?}`` -> the site, boreholes and building
  outline in WGS 84 with the nearest the default pack (BNBC) town (``saengine.gis.site``)
- ``soil/plotCheck`` ``{soilText, floorPlanText, objectsText?}`` -> the plot and its buildable
  envelope in project mm and the floor plan's members outside them (``saengine.gis.plot``)
- ``soil/gisExport`` ``{projectRoot, format: geojson|gpkg, outPath}`` -> ``{path, counts,
  problems}``; ``soil/gisImport`` ``{path, soilText?}`` -> ``{soilText, added, updated, ...}``
- ``soil/qgisProgram`` ``{}`` -> an installed QGIS launcher's path or null;
  ``soil/qgisCommand`` ``{program, filePath}`` -> the arguments that open the file in it
- ``boq/compute`` ``{bimText, objectsText, materialsText, projectRoot?}`` -> the bill of
  quantities (``projectRoot``: where the plumbing tanks' last designs give their bars)
- ``boq/cost`` ``{boqText, ratesText?, carbonText?}`` -> the bill priced by the schedule of rates
  with its embodied carbon (``{costing, sampleRates}``; the shipped sample and factors when not
  given); ``boq/templates`` ``{}`` -> ``{rates, carbon}``, the texts the project's files start
  from; ``boq/exportXlsx`` ``{path, boqText, ratesText?, carbonText?, title?}`` -> the bill, its
  costing and carbon written to ``path`` (``{path, sheets, total, carbonTotal}``)
- ``report/build`` ``{projectRoot, outPdf?, format?, template?}`` -> the design report, PDF or
  Word (``format`` "docx"), as the report template chooses (``{path, pages, warnings, format,
  template}``); ``report/templates`` ``{projectRoot}`` -> ``{templates, current}``;
  ``report/createTemplate`` ``{projectRoot, id, base?, name?}`` -> ``{path}`` (a copy of ``base``)
- ``worksheets/kinds`` ``{}`` -> the calculation worksheet kinds with their inputs;
  ``worksheets/calculate`` ``{kind, inputs, projectRoot?}`` -> the calculation (the project's
  code pack); ``worksheets/list`` ``{projectRoot}`` -> ``{worksheets, problems}``;
  ``worksheets/create`` ``{projectRoot, kind, id, title?}`` -> ``{path}`` or ``{problems}``
- ``drawings/generate`` ``{projectRoot, sheets?, size?, designReportText?}`` -> the structural
  drawings written into ``11 Exports/Drawings`` (``{sheets, pdf, bbsCsv, generatedAt, size,
  stale, notes, problems}``; ``saengine.pipeline.drawings``; in a worker thread; ``sheets``: only
  those sheet numbers); ``drawings/list`` ``{projectRoot}`` -> the
  same for the last generation with ``stale``/``staleReason``/``changed``;
  ``drawings/progress`` ``{projectRoot}`` -> ``{running, step, index, count, message}``;
  ``drawings/issue`` ``{projectRoot, code?, date?, description?, by?, purpose?, sheets?,
  force?, dwg?}`` -> the generate answer with ``issued`` (in a worker thread);
  ``drawings/dwg`` ``{projectRoot, sheets?}`` -> ``{written, folder, problems}`` (dxf2dwg)
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
  foundations of 9 Substructure (once it is no longer the placeholder) and the ground level;
  ``bim/ifcRebar`` takes what ``bim/ifc`` takes and ``projectRoot``: the same IFC with the
  reinforcement cages of the beams and columns (IfcReinforcingBar; in a worker thread)
- ``substructure/design`` ``{projectRoot}`` -> Run All's foundation step: footings moved in,
  minimum bars given, the checks (``saengine.substructure.run.design_foundations``; in a worker
  thread, as ``substructure/report`` and ``report/build``)
- ``substructure/report`` ``{projectRoot}`` -> the design checks of the saved substructure
- ``substructure/size`` ``{projectRoot, columns?, substructureText?}`` -> footings proposed by the
  sizing assistant (in a worker thread; the editor's unsaved substructure when given)
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
- ``fem/existingAssessment`` ``{outDir, projectPath}`` -> the assessment of an existing
  building of a run and its retrofit's before and after comparison
  (``saengine.fem.existing_building``; worker)
- ``fem/memberForces`` ``{outDir, projectPath, member}`` -> a member's section forces and
  deflection along it per case and combination (``saengine.fem.member_detail``; worker)
- ``fem/columnInteraction`` ``{outDir, projectPath, member?}`` -> the columns' P-M interaction
  diagrams and demand points (once per run, cached beside the results; worker)
- ``fem/exportXlsx`` ``{path, sheets: [{name, columns, rows, notes?}]}`` -> the tables written
  to an Excel workbook (``{path, sheets}``; worker)
- ``fem/tableIndex`` ``{outDir, projectPath}`` -> the results with tables and their tables;
  ``fem/table`` ``{outDir, projectPath, key, table}`` -> one of them; ``fem/exportTables``
  ``{outDir, projectPath, path, keys?, tables?, extra?}`` -> the chosen tables streamed to a
  workbook, ``fem/exportProgress`` / ``fem/exportCancel`` ``{}`` while it runs
  (``saengine.fem.result_tables``; worker, except progress and cancel)
- Alpha 9 L3, the CFD wind tunnel (``saengine.fem.cfd_wind``; OpenFOAM installed by the user):
  ``cfd/detect`` ``{openfoam?, distribution?}`` -> the installation found and how to install one;
  ``cfd/write`` ``{projectRoot, installation?}`` -> the cases written (nothing runs);
  ``cfd/start`` ``{projectRoot, openfoam?, distribution?}`` -> the background run started;
  ``cfd/status`` / ``cfd/cancel`` ``{projectRoot}`` (answered at once); ``cfd/results``
  ``{projectRoot}`` -> the coefficients, storey forces and the code comparison
- Alpha 9 L11, the office tools ``office/*`` (4D programme, cost optimisation, PDF takeoff,
  terrain, sun / daylight / noise, MEP fabrication, phasing and design options): listed in
  :mod:`saengine.rpc.office`
- ``mep/report`` ``{projectRoot, outDir?, mepText?}`` -> the MEP coordination report
- ``mep/suggestSleeves`` ``{projectRoot, mepText?, allowance?}`` -> sleeves for the clashes
- ``mep/importIfc`` ``{projectRoot, path, copy?}`` -> what an MEP IFC model holds
- ``mep/coordinate`` ``{projectRoot, mepText?, tests?}`` -> clash tests run, issues merged
- ``mep/exportBcf`` ``{projectRoot, path, mepText?, issues?}`` -> ``{path, topics}`` BCF 3.0
- ``mep/importBcf`` ``{projectRoot, path, mepText?}`` -> ``{coordination, counts}``
- ``mep/checkIds`` ``{projectRoot, mepText?}`` -> IDS checks (IfcTester), issues merged
- ``mep/plumbingReport`` ``{projectRoot, mepText?}`` -> the plumbing report (the default pack's Part 8
  sizing, ``tankDesigns``, ``hydraulics``, missing sleeves), JSON-safe
- ``mep/plumbingSizeTanks`` ``{projectRoot, mepText?}`` -> ``{tanks, notes}`` proposed tanks
- ``mep/plumbingSleeves`` ``{projectRoot, mepText?}`` -> ``{openings, notes}`` missing sleeves
- ``mep/plumbingOccupancies`` ``{}`` -> ``{occupancies}`` the default pack's Table 8.5.1's rows
- ``mep/hvacReport`` ``{projectRoot, mepText?}`` -> the cooling loads (the cached EnergyPlus run
  of this input, else the estimate; EnergyPlus is not started) and the air side under ``air``
- ``mep/hvacLoads`` ``{projectRoot, mepText?}`` -> the same after running EnergyPlus version
  26.2.0 (a separate process, in a worker thread so the other methods keep answering)
- ``mep/hvacCancelLoads`` ``{}`` -> ``{cancelled}`` stops the EnergyPlus runs in progress
- ``mep/hvacProposePlant`` ``{projectRoot, mepText?}`` -> ``{plant, notes}`` proposed plant
- ``mep/hvacDuctOpenings`` ``{projectRoot, mepText?}`` -> ``{openings, conflicts, stale, notes}``
- ``mep/hvacTables`` ``{}`` -> ``{cities, uses}`` the default pack's Tables 8.2.2 (2 %) and 8.2.3
- ``mep/hvacConstructions`` ``{}`` -> ``{wall, roof, glazing}`` with their U-values
- ``mep/electricalReport`` ``{projectRoot, mepText?}`` -> the electrical coordination report
- ``mep/electricalProposeEquipment`` ``{projectRoot, mepText?}`` -> ``{equipment, notes}``
- ``mep/electricalOpenings`` ``{projectRoot, mepText?}`` -> ``{openings, notes}`` still missing
- ``mep/electricalUses`` ``{}`` -> ``{uses}`` the default pack's Table 8.1.17's rows
- ``mep/fireReport`` ``{projectRoot, mepText?}`` -> the fire protection report (the default pack's Part 4
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
  root?}``; ``codes/trust`` ``{id, trusted, root?, kind?, what?}`` (``saengine.codes``). Every request with a
  ``projectRoot``/``root``/``projectPath``/``modelFolder``/``outDir`` runs with that project's
  own code packs available (:mod:`saengine.codes.context`).
- ``versions/status`` ``{projectRoot}``, ``versions/list`` ``{projectRoot, limit?}``,
  ``versions/save`` ``{projectRoot, message, author?, issued?, label?}``, ``versions/diff``
  ``{projectRoot, fromVersion?, toVersion?}``, ``versions/restore`` ``{projectRoot, version, parts?, author?,
  commit?}``, ``versions/markIssued`` ``{projectRoot, version, label, author?}``: the project's
  version history (``saengine.project.versions``; in threads of their own, one operation at a
  time per project, so a long save never holds up the other methods)

- ``share/status`` ``{projectRoot, user?, fetch?}``, ``share/connect`` ``{projectRoot,
  location, author?}``, ``share/disconnect``, ``share/join`` ``{location, target}``,
  ``share/sync`` ``{projectRoot, author?, resolutions?, user?}``, ``share/lock`` /
  ``share/unlock`` ``{projectRoot, part, user?, note?|force?}``, ``share/heartbeat``
  ``{projectRoot, user?, part?, leaving?}``: the office copy of the versions
  (``saengine.project.share``), in the versions threads.

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

from pygls.protocol import JsonRPCProtocol, JsonRPCRequestMessage, default_converter
from pygls.server import JsonRPCServer

from saengine.codes import context as code_context
from saengine.rpc import handlers, jobs


def _converter() -> Any:
    """pygls's converter with request params kept as the JSON objects they are. Its named
    tuples rename every key that is not a Python name (``from``, ``08 FEM``) to ``_0``, ``_1``…,
    so such keys were lost (a split proposal's ``from``: "KeyError: 'from'" on Apply).
    Notifications keep the named tuples (``$/cancelRequest`` reads ``params.id``)."""
    converter = default_converter()
    converter.register_structure_hook(JsonRPCRequestMessage, lambda obj, cls: cls(**obj))
    return converter


def _plain(value: Any) -> Any:
    """Request params as JSON values (named tuples, from older callers, turned back)."""
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
#: The design work (the design checks, required steel, proposals, interaction diagrams, the report
#: and the drawings, which take minutes on a large building) runs in threads of its own: four of
#: them at once no longer leave a save, a soil report or a table waiting for minutes behind them
#: (SM-11, B10-29 of usability walk 3: "Saving..." for 7.5 minutes, everything queued behind the
#: interaction diagrams).
_DESIGN_WORKERS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="saengine-design")


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
        with code_context.project(root) as found:
            pack = _project_pack(found)
            if pack is None:
                return handler(params)
            # Walk 4 (W4A-16): a project under another pack than the default works under its
            # own pack in every request (its bar sizes, masses, schedule standard), not only in
            # the handlers that set it themselves; the default pack's projects as before.
            with code_context.using(pack):
                return handler(params)

    return call


#: Project settings file -> ((mtime, size), its code pack id and overrides), read once a change.
_SETTINGS_PACKS: dict[str, tuple[tuple[int, int], dict[str, Any] | None]] = {}


def _project_pack(root: Any) -> Any:
    """The code pack the settings of the project at ``root`` choose when it is not the default
    pack (None for the default pack, no project or settings that cannot be read)."""
    if root is None:
        return None
    path = os.path.join(str(root), "02 Project Settings", "project-settings.json")
    try:
        stat = os.stat(path)
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    known = _SETTINGS_PACKS.get(path)
    if known is None or known[0] != stamp:
        try:
            with open(path, encoding="utf-8") as file:
                raw = json.load(file)
        except (OSError, ValueError):
            raw = None
        picked = (
            {k: raw[k] for k in ("codePack", "codeOverrides", "site") if k in raw}
            if isinstance(raw, dict)
            else None
        )
        if len(_SETTINGS_PACKS) >= 32:
            _SETTINGS_PACKS.clear()
        _SETTINGS_PACKS[path] = known = (stamp, picked)
    settings = known[1]
    if not settings or settings.get("codePack") in (None, "", code_context.DEFAULT_PACK):
        return None
    try:
        return code_context.pack_for(settings, root)
    except Exception:  # noqa: BLE001 - the handler reports a pack that cannot be used
        return None


def _in_worker(
    handler: Callable[[Any], Any], pool: ThreadPoolExecutor | None = None
) -> Callable[[Any], Any]:
    """``handler`` run in a worker thread (of ``pool``, default :data:`_WORKERS`); its answer is
    sent as soon as it is ready."""
    scoped = _scoped(handler)
    executor = pool or _WORKERS

    @functools.wraps(handler)
    async def run(params: Any) -> Any:
        # The request's job goes with the work into the worker thread (saengine.rpc.jobs).
        work = functools.partial(jobs.run_as, jobs.current(), scoped)
        return await asyncio.get_running_loop().run_in_executor(executor, work, params)

    return run


def _in_design_worker(handler: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """``handler`` run in a design thread (:data:`_DESIGN_WORKERS`)."""
    return _in_worker(handler, _DESIGN_WORKERS)


def _as_job(method: str, fn: Callable) -> Callable:
    """``fn`` (a feature's handler) counted as a job of ``method`` while it runs
    (:mod:`saengine.rpc.jobs`, the ``saengine/jobs`` answer)."""
    if asyncio.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def run_async(params: Any) -> Any:
            job, token = jobs.start(method)
            try:
                return await fn(params)
            finally:
                jobs.finish(job, token)

        return run_async

    @functools.wraps(fn)
    def run(params: Any) -> Any:
        job, token = jobs.start(method)
        try:
            return fn(params)
        finally:
            jobs.finish(job, token)

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
        lock = _project_lock(str(args["projectRoot"]))
        if lock.locked():
            jobs.note("Waiting for another version operation on the project")
        with lock, code_context.project(args["projectRoot"]):
            jobs.note(None)
            return handler(args)

    @functools.wraps(handler)
    async def run(params: Any) -> Any:
        work = functools.partial(jobs.run_as, jobs.current(), locked)
        return await asyncio.get_running_loop().run_in_executor(_VERSIONS_WORKERS, work, params)

    return run


def _import_substructure() -> None:
    """The first imports of the foundation design's modules (shapely's C extension among them)
    are not safe from two threads at once ("partially initialized module 'shapely'"): done on
    the server's thread before the work goes to a worker, as for section/analyse."""
    import shapely  # noqa: F401

    import saengine.substructure.report
    import saengine.substructure.run  # noqa: F401


def _import_soil() -> None:
    """The soil results' modules, imported on the server's thread before a worker runs them."""
    import saengine.soil.report
    import saengine.soil.stratigraphy  # noqa: F401


def create_server() -> JsonRPCServer:
    server = JsonRPCServer(protocol_cls=JsonRPCProtocol, converter_factory=_converter)
    feature = server.feature

    def scoped_feature(*args: Any, **kwargs: Any) -> Callable[[Callable], Callable]:
        register = feature(*args, **kwargs)

        def decorate(fn: Callable) -> Callable:
            handler = fn if asyncio.iscoroutinefunction(fn) else _scoped(fn)
            name = args[0] if args else kwargs.get("feature_name")
            quick = name in ("saengine/jobs", "saengine/cancelJobs", "actions/cancel")
            return register(handler if quick else _as_job(str(name), handler))

        return decorate

    server.feature = scoped_feature  # type: ignore[method-assign]

    # What the engine is working on, answered at once on the server's thread: the app's engine
    # watchdog tells a busy engine (it answers, with each job's note) from one that no longer
    # responds (B10-21 of usability walk 3).
    @server.feature("saengine/jobs")
    def _jobs(params: Any) -> dict[str, Any]:
        return {"jobs": jobs.running()}

    # Stop Waiting on Design Reinforcement: the engine stops the proposal at its next check
    # (R1-1 of re-walk 1: it ran 11 minutes on beside Run All after the page stopped waiting).
    @server.feature("saengine/cancelJobs")
    def _cancel_jobs(params: Any) -> dict[str, Any]:
        methods = _plain(params).get("methods") or []
        return {"cancelled": jobs.cancel([str(m) for m in methods])}

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
        return handlers.check_library(
            args["kind"], args["text"], args.get("materialsText"), args.get("settingsText")
        )

    @server.feature("library/limits")
    def _library_limits(params: Any) -> dict[str, Any]:
        return handlers.library_limits((_plain(params) or {}).get("kind"))

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
            moment_curvature=args.get("momentCurvature"),
            contour_at=args.get("contourAt"),
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
            args.get("architectureText"),
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
            args.get("architectureText"),
            schema=args.get("schema"),
            include_structural_analysis=args.get("includeStructuralAnalysis"),
            soil_text=args.get("soilText"),
            crs=args.get("crs"),
            project_root=args.get("projectRoot"),
        )

    # With the reinforcement: the detailing of every beam and column first (seconds to tens of
    # seconds on a large building), in a worker thread.
    @server.feature("bim/ifcRebar")
    @_in_worker
    def _building_ifc_rebar(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.building_ifc(
            args["bimText"],
            args["objectsText"],
            args.get("materialsText"),
            args.get("name") or "Project",
            args.get("substructureText"),
            args.get("settingsText"),
            args.get("mepText"),
            args.get("architectureText"),
            rebar_root=args.get("projectRoot"),
            schema=args.get("schema"),
            include_structural_analysis=args.get("includeStructuralAnalysis"),
            soil_text=args.get("soilText"),
            crs=args.get("crs"),
        )

    @server.feature("architecture/importIfc")
    @_in_worker  # IfcOpenShell meshes every wall, door, window and space
    def _architecture_import_ifc(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.architecture_import_ifc(
            args["path"], args.get("architectureText"), args["floorPlanText"]
        )

    @server.feature("architecture/inspectDrawing")
    @_in_worker  # a DWG is converted first; a large plan takes seconds
    def _architecture_inspect_drawing(params: Any) -> dict[str, Any]:
        return handlers.architecture_inspect_drawing(_plain(params)["path"])

    @server.feature("architecture/importDrawing")
    @_in_worker
    def _architecture_import_drawing(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.architecture_import_drawing(
            args["path"], args.get("architectureText"), args["floorPlanText"], args.get("options")
        )

    @server.feature("architecture/check")
    def _architecture_check(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.architecture_check(args["architectureText"], args.get("floorPlanText"))

    @server.feature("architecture/ramps")
    def _architecture_ramps(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.architecture_ramps(args["architectureText"], args.get("settingsText"))

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

    @server.feature("cad/cleanDxf")
    @_in_worker
    def _clean_dxf(params: Any) -> dict[str, Any]:
        from saengine.library.dxf_audit import rpc_clean_dxf

        return rpc_clean_dxf(_plain(params))

    @server.feature("cad/convertPdf")
    @_in_worker  # a dense plan has tens of thousands of paths
    def _convert_pdf(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.convert_pdf(
            args["path"], args.get("page"), args.get("cache"), bool(args.get("pagesOnly"))
        )

    @server.feature("cad/convertPointCloud")  # Alpha 9 L2
    @_in_worker
    def _convert_point_cloud(params: Any) -> dict[str, Any]:
        return handlers.convert_point_cloud(_plain(params))

    @server.feature("cad/pointCloudView")
    @_in_worker
    def _point_cloud_view(params: Any) -> dict[str, Any]:
        return handlers.point_cloud_view(_plain(params))

    @server.feature("cad/snapPointCloud")
    @_in_worker
    def _snap_point_cloud(params: Any) -> dict[str, Any]:
        return handlers.snap_point_cloud(_plain(params))

    @server.feature("workbook/export")
    @_in_worker
    def _workbook_export(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.workbook_export(
            args["outPath"], args["floorPlanText"], args.get("objectsText"), args.get("loadsText")
        )

    @server.feature("workbook/import")
    @_in_worker
    def _workbook_import(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.workbook_import(
            args["path"], args["floorPlanText"], args.get("objectsText"), args.get("loadsText")
        )

    @server.feature("components/list")
    @_in_worker
    def _installer_components(params: Any) -> dict[str, Any]:
        return handlers.installer_components()

    @server.feature("hazard/offers")
    def _hazard_offers(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hazard_offers(
            args.get("settingsText"),
            args.get("soilText"),
            args.get("root"),
            args.get("latitude"),
            args.get("longitude"),
        )

    @server.feature("hazard/lookup")
    @_in_worker
    def _hazard_lookup(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hazard_lookup(
            args.get("settingsText"),
            str(args.get("provider") or ""),
            args.get("consent"),
            args.get("soilText"),
            args.get("root"),
            args.get("latitude"),
            args.get("longitude"),
        )

    @server.feature("ai/searchCode")
    @_in_worker
    def _ai_search_code(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.ai_search_code(
            args["query"],
            args.get("projectRoot"),
            args.get("limit") or 8,
            args.get("docs") is not False,
        )

    @server.feature("structure/insert")
    def _insert_geometry(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.insert_geometry(args["structureText"], args["geometry"])

    @server.feature("structure/runScript")
    def _run_script(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.run_script(args["structureText"], args["scriptPath"])

    @server.feature("design/report")
    @_in_design_worker
    def _design_report(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.design_report(args["outDir"], args["projectPath"])

    @server.feature("design/required")
    @_in_design_worker
    def _design_required(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.design_required(args["outDir"], args["projectPath"], args.get("options"))

    @server.feature("design/proposal")
    @_in_design_worker
    def _design_proposal(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.design_proposal(args["outDir"], args["projectPath"], args.get("options"))

    @server.feature("design/strutAndTie")
    def _strut_and_tie(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.strut_and_tie(args["model"], args.get("projectPath"))

    @server.feature("design/strutAndTieTemplate")
    def _strut_and_tie_template(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.strut_and_tie_template(args["template"], args.get("parameters"))

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

    @server.feature("design/analysisChanged")
    @_in_worker  # derives the analysis model (seconds)
    def _design_analysis_changed(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.design_analysis_changed(
            args["projectRoot"], args["objectsText"], args.get("bimText")
        )

    @server.feature("import/structural")
    @_in_worker
    def _import_structural(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.import_structural(
            args["path"], args["destParent"], args.get("name"), bool(args.get("overwrite"))
        )

    @server.feature("export/e2k")
    @_in_worker  # derives the analysis model for the story forces (seconds to minutes)
    def _export_e2k(params: Any) -> dict[str, Any]:
        from saengine.exporters.etabs import rpc_export_e2k

        return rpc_export_e2k(_plain(params))

    # Alpha 9 L10: the fabrication exports of 11 Exports (saengine.fabrication.export).
    @server.feature("fabrication/shopDrawings")
    @_in_worker  # draws and renders the shop drawing sheets (seconds to minutes)
    def _fabrication_shop_drawings(params: Any) -> dict[str, Any]:
        from saengine.fabrication.export import rpc_shop_drawings

        return rpc_shop_drawings(_plain(params))

    @server.feature("fabrication/nc")
    @_in_worker
    def _fabrication_nc(params: Any) -> dict[str, Any]:
        from saengine.fabrication.export import rpc_nc

        return rpc_nc(_plain(params))

    @server.feature("fabrication/bvbs")
    @_in_worker  # details the reinforcement (seconds)
    def _fabrication_bvbs(params: Any) -> dict[str, Any]:
        from saengine.fabrication.export import rpc_bvbs

        return rpc_bvbs(_plain(params))

    @server.feature("revit/export")
    @_in_worker  # details the reinforcement cages (seconds)
    def _revit_export(params: Any) -> dict[str, Any]:
        from saengine.exporters.revit_link import rpc_export

        return rpc_export(_plain(params))

    @server.feature("revit/preview")
    @_in_worker
    def _revit_preview(params: Any) -> dict[str, Any]:
        from saengine.exporters.revit_link import rpc_preview

        return rpc_preview(_plain(params))

    @server.feature("revit/apply")
    @_in_worker
    def _revit_apply(params: Any) -> dict[str, Any]:
        from saengine.exporters.revit_link import rpc_apply

        return rpc_apply(_plain(params))

    @server.feature("library/generateBuilding")
    @_in_worker
    def _new_building(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.new_building(
            args["spec"],
            args["destParent"],
            args.get("name"),
            bool(args.get("overwrite")),
            args.get("site"),
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
            args.get("architectureText"),
        )

    @server.feature("boq/cost")
    def _cost_boq(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.cost_boq(args["boqText"], args.get("ratesText"), args.get("carbonText"))

    @server.feature("boq/templates")
    def _boq_templates(params: Any) -> dict[str, Any]:
        return handlers.boq_templates()

    @server.feature("boq/exportXlsx")
    @_in_worker
    def _export_boq_xlsx(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.export_boq_xlsx(
            args["path"],
            args["boqText"],
            args.get("ratesText"),
            args.get("carbonText"),
            args.get("title") or "",
            args.get("settingsText"),
        )

    @_in_design_worker
    def _build_report_worker(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.build_report(
            args["projectRoot"],
            args.get("outPdf"),
            args.get("format") or "pdf",
            args.get("template"),
        )

    @server.feature("report/build")
    async def _build_report(params: Any) -> dict[str, Any]:
        # Its modules (and the substructure's, which it reads) first imported on the server's
        # thread: see _import_substructure.
        _import_substructure()
        import saengine.report  # noqa: F401

        return await _build_report_worker(params)

    @server.feature("report/templates")
    def _report_templates(params: Any) -> dict[str, Any]:
        return handlers.report_templates(_plain(params)["projectRoot"])

    @server.feature("report/createTemplate")
    def _report_create_template(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.report_template_create(
            args["projectRoot"], args["id"], args.get("base"), args.get("name")
        )

    @server.feature("worksheets/kinds")
    def _worksheet_kinds(params: Any) -> dict[str, Any]:
        return handlers.worksheet_kinds()

    @server.feature("worksheets/calculate")
    def _worksheet_calculate(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.worksheet_calculate(
            args["kind"], args.get("inputs") or {}, args.get("projectRoot")
        )

    @server.feature("worksheets/list")
    def _worksheet_list(params: Any) -> dict[str, Any]:
        return handlers.worksheet_list(_plain(params)["projectRoot"])

    @server.feature("worksheets/create")
    def _worksheet_create(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.worksheet_create(
            args["projectRoot"], args["kind"], args["id"], args.get("title")
        )

    # Detailing, the schedule and the sheets take seconds to tens of seconds: in a worker thread,
    # with ``drawings/progress`` answering meanwhile; ``drawings/list`` only reads files.
    @server.feature("drawings/generate")
    @_in_design_worker
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

    @server.feature("drawings/issue")
    @_in_design_worker
    def _drawings_issue(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.drawings_issue(args["projectRoot"], args)

    @server.feature("drawings/dwg")
    @_in_worker
    def _drawings_dwg(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.drawings_dwg(args["projectRoot"], args.get("sheets"))

    @server.feature("drawings/list")
    def _drawings_list(params: Any) -> dict[str, Any]:
        return handlers.drawings_list(_plain(params)["projectRoot"])

    @server.feature("drawings/progress")
    def _drawings_progress(params: Any) -> dict[str, Any]:
        return handlers.drawings_progress(_plain(params)["projectRoot"])

    # The soil results take seconds for a few boreholes (the bearing table's settlement
    # bisections): in a worker, so the map's location (soil/location) and the other quick
    # requests do not wait behind them (walkthrough 3, SO-4). The modules are imported on the
    # server's thread first, as for the substructure.
    @_in_worker
    def _soil_report_worker(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.soil_report(args["soilText"], args.get("settingsText"))

    @server.feature("soil/report")
    async def _soil_report(params: Any) -> dict[str, Any]:
        _import_soil()
        return await _soil_report_worker(params)

    @_in_worker
    def _soil_allowable_bearing_worker(params: Any) -> dict[str, Any]:
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

    @server.feature("soil/allowableBearing")
    async def _soil_allowable_bearing(params: Any) -> dict[str, Any]:
        _import_soil()
        return await _soil_allowable_bearing_worker(params)

    @server.feature("soil/import")
    def _soil_import(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.import_soil(args["path"], args.get("soilText"))

    @server.feature("soil/template")
    def _soil_template(params: Any) -> dict[str, Any]:
        return handlers.soil_template(_plain(params)["path"])

    @server.feature("soil/export")  # Alpha 9 L8: AGS4 or DIGGS
    def _soil_export(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.export_soil(args["path"], args["soilText"])

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

    @server.feature("soil/plotCheck")
    @_in_worker
    def _soil_plot_check(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.plot_check(
            args.get("soilText"), args.get("floorPlanText"), args.get("objectsText")
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

    @_in_worker
    def _substructure_report_worker(params: Any) -> dict[str, Any]:
        return handlers.substructure_report(_plain(params)["projectRoot"])

    @server.feature("substructure/report")
    async def _substructure_report(params: Any) -> dict[str, Any]:
        _import_substructure()
        return await _substructure_report_worker(params)

    @_in_design_worker
    def _substructure_design_worker(params: Any) -> dict[str, Any]:
        return handlers.substructure_design(_plain(params)["projectRoot"])

    @server.feature("substructure/design")
    async def _substructure_design(params: Any) -> dict[str, Any]:
        _import_substructure()
        return await _substructure_design_worker(params)

    @_in_worker
    def _substructure_size_worker(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.substructure_size(
            args["projectRoot"], args.get("columns"), args.get("substructureText")
        )

    @server.feature("substructure/size")
    async def _substructure_size(params: Any) -> dict[str, Any]:
        _import_substructure()
        return await _substructure_size_worker(params)

    @server.feature("substructure/migrate")
    def _substructure_migrate(params: Any) -> dict[str, Any]:
        return handlers.substructure_migrate(_plain(params)["projectRoot"])

    @server.feature("substructure/ensure")
    def _substructure_ensure(params: Any) -> dict[str, Any]:
        return handlers.substructure_ensure(_plain(params)["projectRoot"])

    @server.feature("fem/meshCheck")
    @_in_design_worker
    def _mesh_check(params: Any) -> dict[str, Any]:
        return handlers.mesh_check(_plain(params)["projectRoot"])

    @server.feature("fem/ssiCompare")
    def _ssi_compare(params: Any) -> dict[str, Any]:
        return handlers.ssi_compare(_plain(params)["projectRoot"])

    @server.feature("fem/seismicDesign")
    @_in_design_worker
    def _seismic_design(params: Any) -> dict[str, Any] | None:
        args = _plain(params)
        return handlers.seismic_design(args["outDir"], args["projectPath"])

    @server.feature("fem/secondOrder")
    @_in_design_worker
    def _second_order(params: Any) -> dict[str, Any] | None:
        args = _plain(params)
        return handlers.second_order_summary(args["outDir"], args["projectPath"])

    @server.feature("fem/nonlinearStability")
    @_in_worker
    def _nonlinear_stability(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.nonlinear_stability(
            args["outDir"], args["projectPath"], bool(args.get("run"))
        )

    @server.feature("special/structures")
    @_in_worker
    def _special_structures(params: Any) -> dict[str, Any]:
        # Alpha 9 L9: bridges and special structures, kept or computed anew (``run``).
        args = _plain(params)
        return handlers.special_structures(args["projectPath"], bool(args.get("run")))

    @server.feature("design/connectionFe")
    @_in_worker
    def _connection_fe(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.connection_fe(args["outDir"], args["projectPath"], args.get("member"))

    @server.feature("fem/storyResponse")
    @_in_worker
    def _story_response(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.story_response(args["outDir"], args["projectPath"])

    @server.feature("fem/existingAssessment")
    @_in_worker
    def _existing_assessment(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.existing_assessment(args["outDir"], args["projectPath"])

    @server.feature("fem/memberForces")
    @_in_worker
    def _member_forces(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.member_forces(args["outDir"], args["projectPath"], args["member"])

    @server.feature("fem/columnInteraction")
    @_in_design_worker
    def _column_interaction(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.column_interaction(args["outDir"], args["projectPath"], args.get("member"))

    @server.feature("fem/exportXlsx")
    @_in_worker
    def _export_xlsx(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.export_xlsx(args["path"], args["sheets"])

    @server.feature("fem/tableIndex")
    @_in_worker
    def _table_index(params: Any) -> dict[str, Any]:
        from saengine.fem import result_tables

        args = _plain(params)
        return result_tables.table_index(args["outDir"], args["projectPath"])

    @server.feature("fem/table")
    @_in_worker
    def _table(params: Any) -> dict[str, Any]:
        from saengine.fem import result_tables

        args = _plain(params)
        return result_tables.result_table(
            args["outDir"], args["projectPath"], args["key"], args["table"]
        )

    @server.feature("fem/exportTables")
    @_in_worker
    def _export_tables(params: Any) -> dict[str, Any]:
        from saengine.fem import result_tables

        args = _plain(params)
        try:
            return result_tables.export_xlsx(
                args["outDir"],
                args["projectPath"],
                args["path"],
                args.get("keys"),
                args.get("tables"),
                args.get("extra"),
            )
        except result_tables.ExportCancelled:
            return {"cancelled": True}

    # Alpha 9 L3: the CFD wind tunnel (saengine.fem.cfd_wind.service). Finding OpenFOAM, writing
    # the cases and starting the run in a worker; the run itself is a process of its own, its
    # status and cancel answered at once.
    @server.feature("cfd/detect")
    @_in_worker
    def _cfd_detect(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.cfd_detect(args.get("openfoam"), args.get("distribution"))

    @server.feature("cfd/write")
    @_in_worker
    def _cfd_write(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.cfd_write(args["projectRoot"], args.get("installation"))

    @server.feature("cfd/start")
    @_in_worker
    def _cfd_start(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.cfd_start(
            args["projectRoot"], args.get("openfoam"), args.get("distribution")
        )

    @server.feature("cfd/status")
    def _cfd_status(params: Any) -> dict[str, Any]:
        return handlers.cfd_status(_plain(params)["projectRoot"])

    @server.feature("cfd/cancel")
    def _cfd_cancel(params: Any) -> dict[str, Any]:
        return handlers.cfd_cancel(_plain(params)["projectRoot"])

    @server.feature("cfd/results")
    @_in_worker
    def _cfd_results(params: Any) -> dict[str, Any]:
        return handlers.cfd_results(_plain(params)["projectRoot"])

    @server.feature("fem/exportProgress")
    def _export_progress(params: Any) -> dict[str, Any]:
        from saengine.fem import result_tables

        return result_tables.export_progress()

    @server.feature("fem/exportCancel")
    def _export_cancel(params: Any) -> dict[str, Any]:
        from saengine.fem import result_tables

        return result_tables.cancel_export()

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

    @server.feature("mep/coordinate")
    @_in_worker
    def _mep_coordinate(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.mep_coordinate(args["projectRoot"], args.get("mepText"), args.get("tests"))

    @server.feature("mep/exportBcf")
    def _mep_export_bcf(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.mep_export_bcf(
            args["projectRoot"], args["path"], args.get("mepText"), args.get("issues")
        )

    @server.feature("mep/importBcf")
    def _mep_import_bcf(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.mep_import_bcf(args["projectRoot"], args["path"], args.get("mepText"))

    @server.feature("mep/checkIds")
    @_in_worker
    def _mep_check_ids(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.mep_check_ids(args["projectRoot"], args.get("mepText"))

    @server.feature("mep/systems")
    def _mep_systems(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.mep_systems(args["projectRoot"], args.get("mepText"))

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

    # The shared editing actions (saengine.actions): a batch runs under the project's versions
    # lock, so it never interleaves with a save, a restore or another batch on the project.
    @server.feature("actions/list")
    def _actions_list(params: Any) -> list[dict[str, Any]]:
        args = _plain(params) or {}
        return handlers.actions_list(args.get("kind"))

    # Stop for a batch in progress (the chat's Stop, the progress notification's Cancel): it
    # stops before its next step, a Run All at its next step boundary, and answers what was done
    # (``cancelled``). Answered at once on the server's thread.
    @server.feature("actions/cancel")
    def _actions_cancel(params: Any) -> dict[str, Any]:
        return {"cancelled": jobs.cancel(["actions/run"])}

    @server.feature("actions/run")
    @_versions_worker
    def _actions_run(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.actions_run(
            args["projectRoot"],
            args.get("steps") or [],
            args.get("overrides"),
            bool(args.get("write")),
            args.get("stopOnError") is not False,
        )

    # Shared projects (saengine.project.share): under the project's versions lock, since a
    # sync saves and merges versions.
    @server.feature("share/status")
    @_versions_worker
    def _share_status(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.share_status(
            args["projectRoot"], args.get("user"), args.get("fetch") is not False
        )

    @server.feature("share/connect")
    @_versions_worker
    def _share_connect(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.share_connect(args["projectRoot"], args["location"], args.get("author"))

    @server.feature("share/disconnect")
    @_versions_worker
    def _share_disconnect(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.share_disconnect(args["projectRoot"])

    @server.feature("share/join")
    async def _share_join(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return await asyncio.get_running_loop().run_in_executor(
            _VERSIONS_WORKERS, handlers.share_join, args["location"], args["target"]
        )

    @server.feature("share/sync")
    @_versions_worker
    def _share_sync(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.share_sync(
            args["projectRoot"], args.get("author"), args.get("resolutions"), args.get("user")
        )

    @server.feature("share/lock")
    @_versions_worker
    def _share_lock(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.share_lock(
            args["projectRoot"], args["part"], args.get("user"), args.get("note")
        )

    @server.feature("share/unlock")
    @_versions_worker
    def _share_unlock(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.share_unlock(
            args["projectRoot"], args["part"], args.get("user"), args.get("force") is True
        )

    @server.feature("share/heartbeat")
    @_versions_worker
    def _share_heartbeat(args: dict[str, Any]) -> dict[str, Any]:
        return handlers.share_heartbeat(
            args["projectRoot"], args.get("user"), args.get("part"), args.get("leaving") is True
        )

    # Code packs (Project Settings' Design code, the Code Packs page).
    @server.feature("codes/list")
    def _codes_list(params: Any) -> list[dict[str, Any]]:
        args = _plain(params)
        return handlers.codes_list(args.get("root"), args.get("kind"))

    @server.feature("codes/templates")
    def _codes_templates(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_templates(args.get("kind") or "buildingTemplate", args.get("root"))

    @server.feature("codes/checkTemplate")
    @_in_worker
    def _codes_check_template(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_check_template(args["path"], args.get("author") or "")

    @server.feature("codes/remove")
    @_in_worker
    def _codes_remove(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_remove(
            args["id"], args.get("scope") or "user", args.get("kind"), args.get("root")
        )

    @server.feature("codes/show")
    def _codes_show(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_show(args["id"], args.get("root"))

    @server.feature("codes/choices")
    def _codes_choices(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_choices(args["id"], args.get("root"))

    @server.feature("codes/combinations")
    def _codes_combinations(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_combinations(args["settingsText"], args.get("root"))

    @server.feature("codes/areaLoads")
    def _codes_area_loads(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_area_loads(args["settingsText"], args.get("root"))

    @server.feature("codes/settingsForPack")
    def _codes_settings_for_pack(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_settings_for_pack(args["settings"], args["id"], args.get("root"))

    @server.feature("codes/values")
    def _codes_values(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_values(args.get("settingsText"), args.get("root"), args.get("table"))

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
        return handlers.codes_install(
            args["path"],
            args.get("scope") or "user",
            args.get("root"),
            args.get("replace") is True,
        )

    @server.feature("codes/validate")
    def _codes_validate(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_validate(args["path"], args.get("root"))

    @server.feature("codes/trust")
    def _codes_trust(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_trust(
            args["id"],
            bool(args.get("trusted")),
            args.get("root"),
            args.get("kind"),
            args.get("what"),  # Alpha 9 C26: "lookup" trusts the pack's hazard services
        )

    @server.feature("codes/codedGeometry")
    @_in_worker
    def _codes_coded_geometry(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_coded_geometry(
            args["package"],
            args["file"],
            args.get("values"),
            args.get("root"),
            args.get("memberType"),
        )

    # Alpha 9 L11: the office tools (4D programme, cost optimisation, PDF takeoff, terrain,
    # sun/daylight/noise, MEP fabrication, phasing and design options; saengine.rpc.office).
    from saengine.rpc import office

    for method, (handler, where) in office.METHODS.items():
        _register_office(server, method, handler, where)

    _register_l12(server)
    _register_u6d(server)
    _register_u6e(server)
    return server


def _register_office(
    server: Any, method: str, handler: Callable[[dict[str, Any]], Any], where: str
) -> None:
    """One method of :mod:`saengine.rpc.office` as a feature: its params made plain, run at once,
    in a worker or in a design worker."""

    def run(params: Any) -> Any:
        return handler(_plain(params))

    run.__name__ = "_office_" + method.split("/", 1)[1]
    if where == "worker":
        server.feature(method)(_in_worker(run))
    elif where == "design":
        server.feature(method)(_in_design_worker(run))
    else:
        server.feature(method)(run)


def _register_l12(server: JsonRPCServer) -> None:
    """Alpha 9 L12: exchange exports, the office server client, visual programs, design studies
    and drawing automation (see the module notes' list)."""

    @server.feature("export/exchange")
    @_in_worker  # derives the analysis model (seconds to minutes)
    def _export_exchange(params: Any) -> dict[str, Any]:
        from saengine.exporters.exchange import rpc_export

        return rpc_export(_plain(params))

    def office_call(work: Callable[[dict[str, Any]], Any]) -> Callable[[Any], Any]:
        def run(params: Any) -> Any:
            from saengine.office.client import OfficeError

            try:
                return work(_plain(params))
            except OfficeError as error:
                return {"ok": False, "code": error.code, "message": str(error)}
            except (KeyError, OSError, ValueError) as error:
                return {"ok": False, "code": "failed", "message": str(error)}

        return run

    @server.feature("office/submit")
    @_in_worker
    def _office_submit(params: Any) -> Any:
        from saengine.office import client

        return office_call(
            lambda a: client.start_background(
                str(a["projectRoot"]), str(a["server"]), str(a["token"]), a.get("steps")
            )
        )(params)

    @server.feature("office/status")
    def _office_status(params: Any) -> Any:
        from saengine.office import client

        return office_call(lambda a: client.background_status(str(a["id"])))(params)

    @server.feature("office/cancel")
    def _office_cancel(params: Any) -> Any:
        from saengine.office import client

        return office_call(lambda a: client.background_cancel(str(a["id"])))(params)

    @server.feature("office/info")
    @_in_worker
    def _office_info(params: Any) -> Any:
        from saengine.office import client

        return office_call(lambda a: client.rpc(str(a["server"]), str(a["token"]), "office/info"))(
            params
        )

    @server.feature("graph/nodeTypes")
    def _graph_node_types(params: Any) -> dict[str, Any]:
        from saengine.automation.graph import node_types

        return node_types()

    @server.feature("graph/list")
    def _graph_list(params: Any) -> dict[str, Any]:
        from saengine.automation.graph import list_graphs

        return list_graphs(_plain(params)["projectRoot"])

    @server.feature("graph/create")
    def _graph_create(params: Any) -> dict[str, Any]:
        from saengine.automation.graph import GraphError, create_graph

        args = _plain(params)
        try:
            return create_graph(args["projectRoot"], str(args.get("name") or "Graph"))
        except (GraphError, OSError) as error:
            return {"error": str(error)}

    @server.feature("graph/check")
    def _graph_check(params: Any) -> dict[str, Any]:
        from saengine.automation.graph import check_graph

        return {"problems": check_graph(_plain(params)["graph"])}

    @server.feature("graph/run")
    @_in_worker  # may run Run All's steps (minutes)
    def _graph_run(params: Any) -> dict[str, Any]:
        from saengine.automation.graph import rpc_run

        return rpc_run(_plain(params))

    def study_call(work: Callable[[dict[str, Any]], Any]) -> Callable[[Any], Any]:
        def run(params: Any) -> Any:
            from saengine.automation.studies import StudyError

            try:
                return work(_plain(params))
            except (StudyError, KeyError, OSError) as error:
                return {"error": str(error)}

        return run

    @server.feature("studies/list")
    def _studies_list(params: Any) -> Any:
        from saengine.automation import studies

        return study_call(lambda a: studies.list_studies(a["projectRoot"]))(params)

    @server.feature("studies/start")
    def _studies_start(params: Any) -> Any:
        from saengine.automation import studies

        return study_call(lambda a: studies.start(a["projectRoot"], a["study"]))(params)

    @server.feature("studies/status")
    def _studies_status(params: Any) -> Any:
        from saengine.automation import studies

        return study_call(lambda a: studies.status(a["projectRoot"], str(a["id"])))(params)

    @server.feature("studies/cancel")
    def _studies_cancel(params: Any) -> Any:
        from saengine.automation import studies

        return study_call(lambda a: studies.cancel(a["projectRoot"], str(a["id"])))(params)

    @server.feature("studies/apply")
    @_versions_worker
    def _studies_apply(args: dict[str, Any]) -> Any:
        from saengine.automation import studies

        return study_call(
            lambda a: studies.apply_variant(
                a["projectRoot"], str(a["id"]), str(a["variant"]), a.get("author")
            )
        )(args)

    @server.feature("drawings/automate")
    @_in_design_worker
    def _drawings_automate(params: Any) -> dict[str, Any]:
        from saengine.drawings.automation import rpc_automate

        return rpc_automate(_plain(params))

    # U3: domain engine RPC endpoints exposed through ribbon panels.
    @server.feature("mep/electricalCableSize")
    @_in_worker
    def _mep_electrical_cable_size(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.electrical_cable_size(
            args.get("projectRoot"),
            mode=str(args.get("mode") or "project"),
            design_current_a=float(args.get("designCurrentA") or 32.0),
            length_m=float(args.get("lengthM") or 30.0),
            phases=int(args.get("phases") or 1),
            installation_method=str(args.get("installationMethod") or "C"),
            insulation=str(args.get("insulation") or "PVC"),
            conductor=str(args.get("conductor") or "Cu"),
            ambient_c=float(args.get("ambientC") or 35.0),
            grouped_circuits=int(args.get("groupedCircuits") or 1),
            vd_limit_pct=float(args.get("vdLimitPct") or 4.0),
            nominal_voltage=args.get("nominalVoltage"),
        )

    @server.feature("mep/electricalLighting")
    @_in_worker
    def _mep_electrical_lighting(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.electrical_lighting(
            args["projectRoot"],
            luminaire_type=args.get("luminaireType"),
            maintenance_factor=args.get("maintenanceFactor"),
            work_plane_m=args.get("workPlaneM"),
            reflectance=args.get("reflectance"),
        )

    @server.feature("mep/hvacLoadsDetailed")
    @_in_worker
    def _mep_hvac_loads_detailed(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hvac_loads_detailed(
            args["projectRoot"],
            zoning=args.get("zoning"),
            use_energyplus=bool(args.get("useEnergyPlus")),
            annual=bool(args.get("annual")),
            epw=args.get("epw"),
        )

    @server.feature("mep/hvacDuctPressure")
    @_in_worker
    def _mep_hvac_duct_pressure(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hvac_duct_pressure(
            args["projectRoot"],
            friction_rate=float(args.get("frictionRate") or 1.0),
            method=str(args.get("method") or "equalFriction"),
            material=args.get("material"),
            supply_delta_t=args.get("supplyDeltaT"),
        )

    @server.feature("mep/hvacRouteDucts")
    @_in_worker
    def _mep_hvac_route_ducts(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.hvac_route_ducts(
            args["projectRoot"],
            story=args.get("story"),
            system=str(args.get("system") or "supply"),
            shape=str(args.get("shape") or "rect"),
            method=str(args.get("method") or "equalFriction"),
            friction_rate=float(args.get("frictionRate") or 1.0),
            beam_penalty=float(args.get("beamPenalty") or 5000.0),
            material=args.get("material"),
            apply_to_mep=bool(args.get("applyToMep")),
        )

    @server.feature("mep/fireSprinklers")
    @_in_worker
    def _mep_fire_sprinklers(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fire_sprinklers(
            args["projectRoot"],
            hazard=args.get("hazard"),
            material=str(args.get("material") or "steel"),
            ceiling=str(args.get("ceiling") or "beams"),
        )

    @server.feature("mep/fireAlarm")
    @_in_worker
    def _mep_fire_alarm(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fire_alarm(
            args["projectRoot"],
            standby_hours=args.get("standbyHours"),
            alarm_minutes=args.get("alarmMinutes"),
            ageing_factor=args.get("ageingFactor"),
        )

    @server.feature("mep/plumbingHotWater")
    @_in_worker
    def _mep_plumbing_hot_water(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.plumbing_hot_water(
            args["projectRoot"],
            supply_temp_c=args.get("supplyTempC"),
            cold_temp_c=args.get("coldTempC"),
            loop_length_m=args.get("loopLengthM"),
            material=args.get("material"),
        )

    @server.feature("mep/plumbingGas")
    @_in_worker
    def _mep_plumbing_gas(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.plumbing_gas(
            args["projectRoot"],
            fuel=args.get("fuel"),
            supply_pressure_kpa=args.get("supplyPressureKpa"),
            max_drop_kpa=args.get("maxDropKpa"),
        )

    @server.feature("drawings/scopeBoxes")
    @_in_worker
    def _drawings_scope_boxes(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.drawings_scope_boxes(
            args["projectRoot"],
            scope_boxes=args.get("scopeBoxes"),
            size=str(args.get("size") or "A1"),
            scale=float(args.get("scale") or 100.0),
            prefix=str(args.get("prefix") or "S-"),
            write_files=bool(args.get("writeFiles")),
            save_to_settings=bool(args.get("saveToSettings")),
        )

    @server.feature("drawings/callout")
    @_in_worker
    def _drawings_callout(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.drawings_callout(
            args["projectRoot"],
            level=args.get("level"),
            callout_number=str(args.get("calloutNumber") or "1"),
            detail_sheet_number=str(args.get("detailSheetNumber") or "S-501"),
            x0=args.get("x0"),
            y0=args.get("y0"),
            x1=args.get("x1"),
            y1=args.get("y1"),
            plan_scale=float(args.get("planScale") or 100.0),
            detail_scale=float(args.get("detailScale") or 25.0),
            size=str(args.get("size") or "A1"),
            write_files=bool(args.get("writeFiles")),
        )

    @server.feature("drawings/keynotes")
    @_in_worker
    def _drawings_keynotes(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.drawings_keynotes(args["projectRoot"], sheet=args.get("sheet"))

    @server.feature("drawings/legend")
    @_in_worker
    def _drawings_legend(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.drawings_legend(args["projectRoot"], sheet=args.get("sheet"))

    @server.feature("drawings/scheduleCategories")
    def _drawings_schedule_categories(params: Any) -> dict[str, Any]:
        return handlers.drawings_schedule_categories(_plain(params)["projectRoot"])

    @server.feature("drawings/schedule")
    @_in_worker
    def _drawings_schedule(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.drawings_schedule(
            args["projectRoot"],
            args["definition"],
            export_xlsx_path=args.get("exportXlsxPath"),
        )

    @server.feature("bim/exportIfcFile")
    @_in_worker
    def _bim_export_ifc_file(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.bim_export_ifc_file(
            args["projectRoot"],
            schema=args.get("schema"),
            structural_analysis=args.get("includeStructuralAnalysis"),
            include_georeferencing=args.get("includeGeoreferencing"),
            crs=args.get("crs"),
            include_connections=args.get("includeConnections"),
            out_path=args.get("outPath"),
        )

    @server.feature("bim/diffIfc")
    @_in_worker
    def _bim_diff_ifc(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.bim_diff_ifc(args["beforePath"], args["afterPath"])

    @server.feature("project/validateAll")
    @_in_worker
    def _project_validate_all(params: Any) -> dict[str, Any]:
        return handlers.project_validate_all(_plain(params)["projectRoot"])

    @server.feature("verification/cases")
    def _verification_cases(params: Any) -> dict[str, Any]:
        return handlers.verification_cases()

    @server.feature("verification/run")
    @_in_worker
    def _verification_run(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.verification_run(
            out_dir=args.get("outDir"),
            ids=args.get("ids"),
            fast_only=bool(args.get("fastOnly", True)),
            pdf=bool(args.get("pdf", True)),
        )


def _register_u6d(server: JsonRPCServer) -> None:
    """U6d: JSON-RPC endpoints exposed by Soil, Settings, Library, Substructure and BOQ ribbon panels."""

    @server.feature("soil/analysis")
    async def _soil_analysis(params: Any) -> dict[str, Any]:
        _import_soil()
        return await _in_worker(lambda p: handlers.soil_analysis(_plain(p)["projectRoot"]))(params)

    @server.feature("soil/bearingCheck")
    async def _soil_bearing_check(params: Any) -> dict[str, Any]:
        _import_soil()

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.soil_bearing_check(
                args["projectRoot"],
                x=float(args.get("x") or 0.0),
                y=float(args.get("y") or 0.0),
                founding_level=float(
                    args.get("foundingLevel") if args.get("foundingLevel") is not None else -1500.0
                ),
                b=float(args.get("b") or 2000.0),
                l=float(args.get("l") or 2000.0),
            )

        return await _in_worker(run)(params)

    @server.feature("soil/settlementCheck")
    async def _soil_settlement_check(params: Any) -> dict[str, Any]:
        _import_soil()

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.soil_settlement_check(
                args["projectRoot"],
                borehole=args.get("borehole"),
                b=float(args.get("b") or 2000.0),
                l=float(args.get("l") or 2000.0),
                df=float(args.get("df") if args.get("df") is not None else 1500.0),
                q=float(args.get("q") or 150.0),
                foundation=str(args.get("foundation") or "isolated"),
            )

        return await _in_worker(run)(params)

    @server.feature("soil/characteristicBearing")
    async def _soil_characteristic_bearing(params: Any) -> dict[str, Any]:
        _import_soil()

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.soil_characteristic_bearing(
                args["projectRoot"],
                borehole=args.get("borehole"),
                fak=float(args.get("fak") or 150.0),
                b=float(args.get("b") or 2.0),
                l=float(args.get("l") or 2.0),
                df=float(args.get("df") if args.get("df") is not None else 1.5),
                q=float(args.get("q") or 150.0),
            )

        return await _in_worker(run)(params)

    @server.feature("soil/earthPressure")
    def _soil_earth_pressure(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.soil_earth_pressure(
            args["projectRoot"],
            borehole=args.get("borehole"),
            depth_m=float(args.get("depthM") or 6.0),
            surcharge_kpa=float(
                args.get("surchargeKpa") if args.get("surchargeKpa") is not None else 10.0
            ),
            water_table_m=args.get("waterTableM"),
            phi_deg=float(args.get("phiDeg") or 30.0),
            gamma=float(args.get("gamma") or 18.0),
            kh=float(args.get("kh") or 0.0),
            beta_deg=float(args.get("betaDeg") or 0.0),
            delta_deg=float(args.get("deltaDeg") or 0.0),
        )

    @server.feature("soil/plotPlanning")
    @_in_worker
    def _soil_plot_planning(params: Any) -> dict[str, Any]:
        return handlers.soil_plot_planning(_plain(params)["projectRoot"])

    @server.feature("soil/sourcesCheck")
    def _soil_sources_check(params: Any) -> dict[str, Any]:
        return handlers.soil_sources_check(_plain(params)["projectRoot"])

    @server.feature("codes/conformance")
    def _codes_conformance(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_conformance(args.get("projectRoot"), pack_id=args.get("packId"))

    @server.feature("codes/diff")
    @_in_worker
    def _codes_diff(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.codes_diff(
            args["packA"], args["packB"], project_root=args.get("projectRoot")
        )

    @server.feature("settings/hazardSummary")
    def _settings_hazard_summary(params: Any) -> dict[str, Any]:
        return handlers.settings_hazard_summary(_plain(params)["projectRoot"])

    @server.feature("settings/towns")
    def _settings_towns(params: Any) -> dict[str, Any]:
        return handlers.settings_towns((_plain(params) or {}).get("projectRoot"))

    @server.feature("library/materialSummary")
    def _library_material_summary(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.library_material_summary(
            args["projectRoot"],
            fc=float(args.get("fc") or 28.0),
            mix_ratio=str(args.get("mixRatio") or "1:2:4"),
        )

    @server.feature("library/objectSections")
    @_in_worker
    def _library_object_sections(params: Any) -> dict[str, Any]:
        return handlers.library_object_sections(_plain(params)["projectRoot"])

    @server.feature("library/designedSections")
    async def _library_designed_sections(params: Any) -> dict[str, Any]:
        import concreteproperties.concrete_section  # noqa: F401
        import sectionproperties.analysis.section  # noqa: F401

        import saengine.library.section_designer  # noqa: F401

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.library_designed_sections(
                args["projectRoot"],
                section_id=args.get("sectionId"),
                capacity=args.get("capacity") is not False,
                moment_curvature=bool(args.get("momentCurvature")),
                axial_kn=float(args.get("axialKn") or 0.0),
            )

        return await _in_worker(run)(params)

    @server.feature("library/sheetPiles")
    def _library_sheet_piles(params: Any) -> dict[str, Any]:
        args = _plain(params) or {}
        return handlers.library_sheet_piles(shape=args.get("shape"))

    @server.feature("library/archTypes")
    def _library_arch_types(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.library_arch_types(args["projectRoot"], category=args.get("category"))

    @server.feature("library/validateAll")
    def _library_validate_all(params: Any) -> dict[str, Any]:
        return handlers.library_validate_all(_plain(params)["projectRoot"])

    @server.feature("substructure/pileCapacity")
    async def _substructure_pile_capacity(params: Any) -> dict[str, Any]:
        _import_substructure()

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.substructure_pile_capacity(
                args["projectRoot"],
                kind=str(args.get("kind") or "bored"),
                head_level_mm=float(
                    args.get("headLevelMm") if args.get("headLevelMm") is not None else -1500.0
                ),
                diameters_mm=args.get("diametersMm"),
                lengths_m=args.get("lengthsM"),
            )

        return await _in_worker(run)(params)

    @server.feature("substructure/pileLateral")
    async def _substructure_pile_lateral(params: Any) -> dict[str, Any]:
        _import_substructure()

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.substructure_pile_lateral(
                args["projectRoot"],
                borehole=args.get("borehole"),
                kind=str(args.get("kind") or "bored"),
                diameter_mm=float(args.get("diameterMm") or 600.0),
                length_m=float(args.get("lengthM") or 18.0),
                head_depth_m=float(
                    args.get("headDepthM") if args.get("headDepthM") is not None else 1.5
                ),
                fixity=str(args.get("fixity") or "fixed"),
                my_knm=float(args.get("myKnm") or 250.0),
                ep_mpa=float(args.get("epMpa") or 25000.0),
            )

        return await _in_worker(run)(params)

    @server.feature("substructure/pileSettlement")
    async def _substructure_pile_settlement(params: Any) -> dict[str, Any]:
        _import_substructure()

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.substructure_pile_settlement(
                args["projectRoot"],
                borehole=args.get("borehole"),
                kind=str(args.get("kind") or "bored"),
                diameter_mm=float(args.get("diameterMm") or 600.0),
                length_m=float(args.get("lengthM") or 18.0),
                head_depth_m=float(
                    args.get("headDepthM") if args.get("headDepthM") is not None else 1.5
                ),
                load_kn=float(args.get("loadKn") or 800.0),
                count=int(args.get("count") or 4),
                bg_m=float(args.get("bgM") or 2.4),
                lg_m=float(args.get("lgM") or 2.4),
                modulus_mpa=float(args.get("modulusMpa") or 25000.0),
            )

        return await _in_worker(run)(params)

    @server.feature("substructure/downdrag")
    async def _substructure_downdrag(params: Any) -> dict[str, Any]:
        _import_substructure()

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.substructure_downdrag(
                args["projectRoot"],
                borehole=args.get("borehole"),
                kind=str(args.get("kind") or "bored"),
                diameter_mm=float(args.get("diameterMm") or 600.0),
                length_m=float(args.get("lengthM") or 18.0),
                head_depth_m=float(
                    args.get("headDepthM") if args.get("headDepthM") is not None else 1.5
                ),
                sustained_kn=float(args.get("sustainedKn") or 600.0),
                settling_depth_m=args.get("settlingDepthM"),
            )

        return await _in_worker(run)(params)

    @server.feature("substructure/loadTests")
    def _substructure_load_tests(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.substructure_load_tests(
            args["projectRoot"],
            diameter_mm=float(args.get("diameterMm") or 600.0),
            length_m=float(args.get("lengthM") or 18.0),
            ep_mpa=float(args.get("epMpa") or 25000.0),
            curve_text=args.get("curveText"),
        )

    @server.feature("substructure/pileDetailing")
    def _substructure_pile_detailing(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.substructure_pile_detailing(
            args["projectRoot"],
            kind=str(args.get("kind") or "bored"),
            diameter_mm=float(args.get("diameterMm") or 600.0),
            fc_mpa=float(args.get("fcMpa") or 28.0),
            fy_mpa=float(args.get("fyMpa") or 420.0),
            placement=str(args.get("placement") or "tremie"),
        )

    @server.feature("substructure/basementLoads")
    def _substructure_basement_loads(params: Any) -> dict[str, Any]:
        return handlers.substructure_basement_loads(_plain(params)["projectRoot"])

    @server.feature("substructure/embeddedWall")
    async def _substructure_embedded_wall(params: Any) -> dict[str, Any]:
        _import_substructure()

        def run(p: Any) -> dict[str, Any]:
            args = _plain(p)
            return handlers.substructure_embedded_wall(
                args["projectRoot"],
                height_m=float(args.get("heightM") or 5.0),
                kind=str(args.get("kind") or "cantilever"),
                support=str(args.get("support") or "free"),
                prop_depth_m=float(args.get("propDepthM") or 1.5),
                surcharge_kpa=float(
                    args.get("surchargeKpa") if args.get("surchargeKpa") is not None else 10.0
                ),
                water_table_m=args.get("waterTableM"),
            )

        return await _in_worker(run)(params)

    @server.feature("substructure/groundSlab")
    def _substructure_ground_slab(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.substructure_ground_slab(
            args["projectRoot"],
            thickness_mm=float(args.get("thicknessMm") or 150.0),
            fc_mpa=float(args.get("fcMpa") or 25.0),
            subgrade_kn_m3=float(args.get("subgradeKnM3") or 30000.0),
            point_load_kn=float(args.get("pointLoadKn") or 50.0),
            contact_side_mm=float(args.get("contactSideMm") or 150.0),
            fy_mpa=float(args.get("fyMpa") or 420.0),
        )

    @server.feature("substructure/limitState")
    def _substructure_limit_state(params: Any) -> dict[str, Any]:
        return handlers.substructure_limit_state(_plain(params)["projectRoot"])

    @server.feature("boq/summary")
    def _boq_summary(params: Any) -> dict[str, Any]:
        return handlers.boq_summary(_plain(params)["projectRoot"])

    @server.feature("boq/barSchedule")
    @_in_worker
    def _boq_bar_schedule(params: Any) -> dict[str, Any]:
        return handlers.boq_bar_schedule(_plain(params)["projectRoot"])

    @server.feature("boq/scheduleSummary")
    def _boq_schedule_summary(params: Any) -> dict[str, Any]:
        return handlers.boq_schedule_summary(_plain(params)["projectRoot"])

    @server.feature("boq/archTakeoff")
    @_in_worker
    def _boq_arch_takeoff(params: Any) -> dict[str, Any]:
        return handlers.boq_arch_takeoff(_plain(params)["projectRoot"])

    @server.feature("boq/precastSchedule")
    def _boq_precast_schedule(params: Any) -> dict[str, Any]:
        return handlers.boq_precast_schedule(_plain(params)["projectRoot"])

    @server.feature("boq/takeoffSummary")
    def _boq_takeoff_summary(params: Any) -> dict[str, Any]:
        return handlers.boq_takeoff_summary(_plain(params)["projectRoot"])


def _register_u6e(server: JsonRPCServer) -> None:
    """Register the 62 U6e full-ribbon panel endpoints for FEM, BIM, Architecture, Documents,
    Studies, and Exports."""

    @server.feature("fem/notionalLoads")
    def _fem_notional_loads(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_notional_loads(
            args["projectRoot"],
            method=str(args.get("method") or "directAnalysis"),
            drift=float(args.get("drift") or 0.0),
            tau=str(args.get("tau") or "additive"),
            height_m=float(args.get("heightM") or 0.0),
        )

    @server.feature("fem/patternLive")
    def _fem_pattern_live(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_pattern_live(
            args["projectRoot"],
            system=str(args.get("system") or "rcSmf"),
            dead_kpa=float(args.get("deadKpa") or 5.0),
            live_kpa=float(args.get("liveKpa") or 2.0),
            adjacent=bool(args.get("adjacent") if args.get("adjacent") is not None else True),
            alternate=bool(args.get("alternate") if args.get("alternate") is not None else True),
        )

    @server.feature("fem/snowRainLoads")
    def _fem_snow_rain_loads(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_snow_rain_loads(args["projectRoot"])

    @server.feature("fem/thermalLoads")
    def _fem_thermal_loads(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_thermal_loads(
            args["projectRoot"],
            uniform=float(args.get("uniform") or 20.0),
            gradient=float(args.get("gradient") or 0.0),
            thickness_mm=float(args.get("thicknessMm") or 200.0),
            e_mpa=float(args.get("eMpa") or 25000.0),
            alpha=float(args.get("alpha") or 1e-5),
        )

    @server.feature("fem/floodLoads")
    def _fem_flood_loads(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_flood_loads(
            args["projectRoot"],
            wave_height_m=float(args.get("waveHeightM") or 1.2),
            still_depth_m=float(args.get("stillDepthM") or 2.0),
            pile_width_m=float(args.get("pileWidthM") or 0.5),
            velocity_m_s=float(args.get("velocityMS") or 2.0),
        )

    @server.feature("fem/stairCraneLoads")
    def _fem_stair_crane_loads(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_stair_crane_loads(args["projectRoot"])

    @server.feature("fem/loadCombinations")
    def _fem_load_combinations(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_load_combinations(args["projectRoot"])

    @server.feature("fem/spectralHazard")
    def _fem_spectral_hazard(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_spectral_hazard(
            args["projectRoot"],
            damping=float(args.get("damping") or 0.05),
        )

    @server.feature("fem/seismicSummary")
    @_in_worker
    def _fem_seismic_summary(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_seismic_summary(args["projectRoot"])

    @server.feature("fem/groundMotions")
    def _fem_ground_motions(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_ground_motions(
            args["projectRoot"],
            procedure=str(args.get("procedure") or "linear"),
        )

    @server.feature("fem/linearTimeHistory")
    def _fem_linear_time_history(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_linear_time_history(args["projectRoot"])

    @server.feature("fem/irregularities")
    @_in_worker
    def _fem_irregularities(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_irregularities(args["projectRoot"])

    @server.feature("fem/torsionalEffects")
    def _fem_torsional_effects(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_torsional_effects(args["projectRoot"])

    @server.feature("fem/twoLevelSeismic")
    def _fem_two_level_seismic(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_two_level_seismic(args["projectRoot"])

    @server.feature("fem/floorSpectra")
    def _fem_floor_spectra(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_floor_spectra(args["projectRoot"])

    @server.feature("fem/isolationDampers")
    def _fem_isolation_dampers(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_isolation_dampers(args["projectRoot"])

    @server.feature("fem/windSpeedFactors")
    def _fem_wind_speed_factors(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_wind_speed_factors(
            args["projectRoot"],
            height_m=float(args.get("heightM") or 0.0),
        )

    @server.feature("fem/gustResponse")
    def _fem_gust_response(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_gust_response(
            args["projectRoot"],
            frequency_hz=float(args.get("frequencyHz") or 1.0),
            damping=float(args.get("damping") or 0.02),
        )

    @server.feature("fem/peakVelocityPressure")
    def _fem_peak_velocity_pressure(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_peak_velocity_pressure(args["projectRoot"])

    @server.feature("fem/localPressures")
    def _fem_local_pressures(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_local_pressures(
            args["projectRoot"],
            tributary_area_m2=float(args.get("tributaryAreaM2") or 10.0),
            parapet_m=float(args.get("parapetM") or 1.0),
        )

    @server.feature("fem/windComfort")
    def _fem_wind_comfort(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_wind_comfort(
            args["projectRoot"],
            frequency_hz=float(args.get("frequencyHz") or 0.5),
            damping=float(args.get("damping") or 0.015),
        )

    @server.feature("fem/openStructures")
    def _fem_open_structures(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_open_structures(
            args["projectRoot"],
            solidity=float(args.get("solidity") or 0.35),
            width_m=float(args.get("widthM") or 6.0),
            depth_m=float(args.get("depthM") or 6.0),
            height_m=float(args.get("heightM") or 15.0),
        )

    @server.feature("fem/pushoverAnalysis")
    def _fem_pushover_analysis(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_pushover_analysis(args["projectRoot"])

    @server.feature("fem/nonlinearHistory")
    def _fem_nonlinear_history(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_nonlinear_history(args["projectRoot"])

    @server.feature("fem/pDeltaBuckling")
    @_in_worker
    def _fem_p_delta_buckling(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_p_delta_buckling(args["projectRoot"])

    @server.feature("fem/stagedConstruction")
    def _fem_staged_construction(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_staged_construction(args["projectRoot"])

    @server.feature("fem/creepShrinkage")
    def _fem_creep_shrinkage(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_creep_shrinkage(
            args["projectRoot"],
            thickness_mm=float(args.get("thicknessMm") or 200.0),
            humidity=float(args.get("humidity") or 70.0),
            age_days=float(args.get("ageDays") or 28.0),
            fck_mpa=float(args.get("fckMpa") or 28.0),
        )

    @server.feature("fem/ssiSprings")
    def _fem_ssi_springs(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_ssi_springs(
            args["projectRoot"],
            length_m=float(args.get("lengthM") or 2.5),
            width_m=float(args.get("widthM") or 2.5),
            depth_m=float(args.get("depthM") or 1.5),
        )

    @server.feature("fem/swayDrift")
    def _fem_sway_drift(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_sway_drift(args["projectRoot"])

    @server.feature("fem/floorVibration")
    def _fem_floor_vibration(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_floor_vibration(
            args["projectRoot"],
            fn_hz=float(args.get("fnHz") or 6.0),
            span_m=float(args.get("spanM") or 6.0),
            area_m2=float(args.get("areaM2") or 36.0),
            w_kn=float(args.get("wKn") or 150.0),
        )

    @server.feature("fem/differentialSettlement")
    def _fem_differential_settlement(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_differential_settlement(
            args["projectRoot"],
            thermal=bool(args.get("thermal") or False),
        )

    @server.feature("fem/punchingShear")
    def _fem_punching_shear(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_punching_shear(
            args["projectRoot"],
            vu_kn=float(args.get("vuKn") or 350.0),
            c1_mm=float(args.get("c1Mm") or 400.0),
            c2_mm=float(args.get("c2Mm") or 400.0),
            d_mm=float(args.get("dMm") or 180.0),
            fc_mpa=float(args.get("fcMpa") or 28.0),
        )

    @server.feature("fem/deflectionCheck")
    def _fem_deflection_check(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_deflection_check(
            args["projectRoot"],
            ma_knm=float(args.get("maKnm") or 45.0),
            fc_mpa=float(args.get("fcMpa") or 28.0),
            b_mm=float(args.get("bMm") or 300.0),
            h_mm=float(args.get("hMm") or 500.0),
            span_mm=float(args.get("spanMm") or 6000.0),
        )

    @server.feature("fem/crackControl")
    def _fem_crack_control(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_crack_control(
            args["projectRoot"],
            exposure=str(args.get("exposure") or "XC3"),
            moment_knm=float(args.get("momentKnm") or 45.0),
            b_mm=float(args.get("bMm") or 300.0),
            h_mm=float(args.get("hMm") or 500.0),
            bar_mm=float(args.get("barMm") or 16.0),
            as_mm2=float(args.get("asMm2") or 804.0),
        )

    @server.feature("fem/torsionDesign")
    def _fem_torsion_design(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_torsion_design(
            args["projectRoot"],
            tu_knm=float(args.get("tuKnm") or 15.0),
            vu_kn=float(args.get("vuKn") or 120.0),
            b_mm=float(args.get("bMm") or 300.0),
            h_mm=float(args.get("hMm") or 500.0),
            fc_mpa=float(args.get("fcMpa") or 28.0),
            fy_mpa=float(args.get("fyMpa") or 420.0),
        )

    @server.feature("fem/capacitySeismicDetailing")
    def _fem_capacity_seismic_detailing(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_capacity_seismic_detailing(args["projectRoot"])

    @server.feature("fem/fireSteelConnections")
    def _fem_fire_steel_connections(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.fem_fire_steel_connections(
            args["projectRoot"],
            bolt_dia_mm=float(args.get("boltDiaMm") or 20.0),
            grade=str(args.get("grade") or "8.8"),
            weld_mm=float(args.get("weldMm") or 6.0),
            height_m=float(args.get("heightM") or 12.0),
        )

    @server.feature("bim/syncStamps")
    def _bim_sync_stamps(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.bim_sync_stamps(args["projectRoot"])

    @server.feature("bim/detailingModel")
    @_in_worker
    def _bim_detailing_model(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.bim_detailing_model(args["projectRoot"])

    @server.feature("bim/rebarCages")
    @_in_worker
    def _bim_rebar_cages(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.bim_rebar_cages(args["projectRoot"])

    @server.feature("bim/barBendingSchedule")
    @_in_worker
    def _bim_bar_bending_schedule(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.bim_bar_bending_schedule(args["projectRoot"])

    @server.feature("architecture/roomsCheck")
    def _architecture_rooms_check(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.architecture_rooms_check(args["projectRoot"])

    @server.feature("architecture/massingFloors")
    def _architecture_massing_floors(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.architecture_massing_floors(args["projectRoot"])

    @server.feature("architecture/roofCeilingCurtain")
    def _architecture_roof_ceiling_curtain(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.architecture_roof_ceiling_curtain(args["projectRoot"])

    @server.feature("architecture/pointCloudStatus")
    def _architecture_point_cloud_status(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.architecture_point_cloud_status(
            args["projectRoot"],
            path=str(args.get("path") or ""),
        )

    @server.feature("documents/sheetInventory")
    def _documents_sheet_inventory(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.documents_sheet_inventory(args["projectRoot"])

    @server.feature("documents/drawingAutomation")
    def _documents_drawing_automation(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.documents_drawing_automation(args["projectRoot"])

    @server.feature("documents/calculationPackage")
    def _documents_calculation_package(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.documents_calculation_package(args["projectRoot"])

    @server.feature("documents/clauseTraceability")
    def _documents_clause_traceability(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.documents_clause_traceability(args["projectRoot"])

    @server.feature("documents/projectMetadata")
    def _documents_project_metadata(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.documents_project_metadata(args["projectRoot"])

    @server.feature("studies/daylightSolar")
    @_in_worker
    def _studies_daylight_solar(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.studies_daylight_solar(
            args["projectRoot"],
            day=str(args.get("day") or "2025-06-21"),
        )

    @server.feature("studies/noiseStudy")
    @_in_worker
    def _studies_noise_study(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.studies_noise_study(args["projectRoot"])

    @server.feature("studies/phasingSummary")
    def _studies_phasing_summary(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.studies_phasing_summary(args["projectRoot"])

    @server.feature("studies/plotPlanning")
    def _studies_plot_planning(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.studies_plot_planning(args["projectRoot"])

    @server.feature("studies/specialStructures")
    def _studies_special_structures(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.studies_special_structures(args["projectRoot"])

    @server.feature("studies/batchCheck")
    def _studies_batch_check(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.studies_batch_check(args["projectRoot"])

    @server.feature("studies/verificationStatus")
    def _studies_verification_status(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.studies_verification_status(args["projectRoot"])

    @server.feature("exports/formatMatrix")
    def _exports_format_matrix(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.exports_format_matrix(args["projectRoot"])

    @server.feature("exports/fabricationPreview")
    @_in_worker
    def _exports_fabrication_preview(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.exports_fabrication_preview(args["projectRoot"])

    @server.feature("exports/structuralIfcCheck")
    def _exports_structural_ifc_check(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.exports_structural_ifc_check(args["projectRoot"])

    @server.feature("exports/archiveInspection")
    def _exports_archive_inspection(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.exports_archive_inspection(args["projectRoot"])

    @server.feature("exports/bbsReconciliation")
    @_in_worker
    def _exports_bbs_reconciliation(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.exports_bbs_reconciliation(
            args["projectRoot"],
            tolerance=float(args.get("tolerance") or 0.5),
        )


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
    import shapely  # noqa: F401 - the same for shapely, which the warm-ups import too

    # And the project settings (and the code packs behind them), which every request reads to
    # put its project's pack in force and the warm-ups import too: a request racing the
    # warm-up thread got "cannot import name 'ProjectSettings' from partially initialized
    # module".
    import saengine.library.settings

    # And the versions and sharing modules (dulwich behind them): a project opens with
    # versions/status and share/status at once, each on its own versions thread.
    import saengine.project.share
    import saengine.project.versions  # noqa: F401

    # Diagnostics: with SAENGINE_HANG_DUMP=<file>, every thread's stack is appended to the file
    # once a minute, to see where a request hangs.
    hang_dump = os.environ.get("SAENGINE_HANG_DUMP")
    if hang_dump:
        import faulthandler

        faulthandler.dump_traceback_later(60, repeat=True, file=open(hang_dump, "a"))  # noqa: SIM115

    def warm() -> None:
        # WNTR's first import takes a second or two: done ahead of the editor's first request.
        handlers.warm_plumbing()
        handlers.warm_services()

    threading.Thread(target=warm, name="warm-imports", daemon=True).start()
    server.start_io(stdin, stdout)
    return 0
