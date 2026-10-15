"""JSON-RPC 2.0 server over stdio (LSP base-protocol framing), built on pygls.

Methods:

- ``saengine/info`` -> versions of the backend stack
- ``project/validate`` ``{path}`` -> schema and reference check of an ``.osmodel``
- ``results/tables`` ``{outDir, projectPath?}`` -> result tables of a finished run
- ``results/list`` ``{outDir, projectPath}`` -> the results that can be shown in 3D
- ``results/view`` ``{outDir, projectPath, key, mode?}`` -> one result's shape and diagrams
- ``library/check`` ``{kind, text, materialsText?}`` -> rule violations in a library file
- ``structure/shapeGeometry`` ``{shape}`` -> a parametric shape's members, areas and supports
- ``structure/importGeometry`` ``{path, options, objectsText?}`` -> a DXF, IFC or Rhino file's
- ``structure/insert`` ``{structureText, geometry}`` -> the structural model with them added
- ``structure/runScript`` ``{structureText, scriptPath}`` -> the model a script built

Analyses themselves are not run here: the workbench starts
``python -m opensees_studio.run`` per run, so an OpenSees hard exit can never take
this long-lived server down.
"""

from __future__ import annotations

import os
import sys
from typing import Any, BinaryIO

from pygls.protocol import JsonRPCProtocol, default_converter
from pygls.server import JsonRPCServer

from saengine.rpc import handlers


def _plain(value: Any) -> Any:
    """pygls hands untyped params over as named tuples; turn them back into JSON values."""
    if hasattr(value, "_asdict"):
        return {k: _plain(v) for k, v in value._asdict().items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def create_server() -> JsonRPCServer:
    server = JsonRPCServer(protocol_cls=JsonRPCProtocol, converter_factory=default_converter)

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
        )

    @server.feature("bim/ifc")
    def _building_ifc(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.building_ifc(
            args["bimText"],
            args["objectsText"],
            args.get("materialsText"),
            args.get("name") or "Project",
        )

    @server.feature("structure/shapeGeometry")
    def _shape_geometry(params: Any) -> dict[str, Any]:
        return handlers.shape_geometry(_plain(params)["shape"])

    @server.feature("structure/importGeometry")
    def _import_geometry(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.import_geometry(
            args["path"], args.get("options") or {}, args.get("objectsText")
        )

    @server.feature("structure/insert")
    def _insert_geometry(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.insert_geometry(args["structureText"], args["geometry"])

    @server.feature("structure/runScript")
    def _run_script(params: Any) -> dict[str, Any]:
        args = _plain(params)
        return handlers.run_script(args["structureText"], args["scriptPath"])

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


def main() -> int:
    stdout = _claim_stdout()
    create_server().start_io(sys.stdin.buffer, stdout)
    return 0
