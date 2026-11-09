"""Visual programs: node graphs whose nodes wrap SAEngine's functions (gap API-6).

A graph is a JSON file in ``12 Automation/graphs/<name>.sagraph.json`` (schema ``saengine.graph/1``)::

    {"schema": "saengine.graph/1", "name": "Storey height study",
     "nodes": [{"id": "n1", "type": "value.number", "x": 40, "y": 60, "params": {"value": 3200}},
               {"id": "n2", "type": "project.setValue", "params": {"file": "05 Floor Plan/floor-plan.json",
                                                              "path": "stories/2/elevation"}}, ...],
     "edges": [{"from": {"node": "n1", "port": "value"}, "to": {"node": "n2", "port": "value"}}]}

The node editor in the app (a webview-free editor drawn on the shared editor frame) edits it;
:func:`run_graph` executes it in the backend: the nodes in dependency order, each input from its
wire or else from the node's own parameter or its default, the outputs kept per node (shown on
the nodes after a run). A node that fails stops the nodes downstream of it, not the others.

The nodes (:data:`NODE_TYPES`; ``graph/nodeTypes`` gives the editor their ports):

- values and lists: a number, a text, a list, a range, arithmetic, a JSON path into a value;
- geometry: a new building from grids and storeys (the New Building generator), a parametric
  shape's geometry (``saengine.api.shape_geometry``) and inserting it into a structural model;
- the project: read a part, set a value in a part file (writes the file), the project's grid
  spacings scaled (the design studies' parameters, :mod:`saengine.automation.studies`);
- run: Run All's steps (:func:`saengine.pipeline.run_all.run_all`);
- results: the design summary, the largest storey drift, the bill of quantities' cost, carbon
  and steel, and exports (``.s2k``, ``.std``, SAF, SDNF, CIS/2, web viewer).

Nothing here runs arbitrary code: a node is one of the types below, with JSON parameters.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saengine.automation import FOLDER

SCHEMA = "saengine.graph/1"
GRAPHS_FOLDER = "graphs"
EXTENSION = ".sagraph.json"
#: Longest text of a node's output kept for the editor.
MAX_OUTPUT_CHARS = 4000


class GraphError(ValueError):
    """The graph cannot run (unknown node type, a cycle, a bad wire)."""


@dataclass(frozen=True)
class Port:
    name: str
    type: str = "any"  # number, text, list, json, project, geometry, any
    default: Any = None
    description: str = ""


@dataclass(frozen=True)
class NodeType:
    id: str
    title: str
    category: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    run: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    description: str = ""
    #: Writes project files (the editor says so, and saves the open editors first).
    writes: bool = False

    def to_json(self) -> dict[str, Any]:
        def port(p: Port) -> dict[str, Any]:
            return {
                "name": p.name,
                "type": p.type,
                "default": p.default,
                "description": p.description,
            }

        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "inputs": [port(p) for p in self.inputs],
            "outputs": [port(p) for p in self.outputs],
            "writes": self.writes,
        }


# ─────────────────────────────────────────── helpers ───────────────────────────────────────────


def _number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise GraphError(f"{name}: not a number ({value!r})") from error
    if not math.isfinite(number):
        raise GraphError(f"{name}: not a finite number")
    return number


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        return [_maybe_number(v.strip()) for v in text.split(",") if v.strip()]
    if value is None:
        return []
    return [value]


def _maybe_number(text: str) -> Any:
    try:
        return float(text) if any(c in text for c in ".eE") else int(text)
    except ValueError:
        return text


def json_path(path: Any) -> list[Any]:
    """``"stories/2/elevation"`` or ``["stories", 2, "elevation"]`` as a list of keys and
    indices."""
    parts = path if isinstance(path, list) else [p for p in str(path or "").split("/") if p != ""]
    return [int(p) if isinstance(p, str) and re.fullmatch(r"-?\d+", p) else p for p in parts]


def get_path(document: Any, path: Any) -> Any:
    value = document
    for key in json_path(path):
        if isinstance(value, list) and isinstance(key, int) and -len(value) <= key < len(value):
            value = value[key]
        elif isinstance(value, dict) and str(key) in value:
            value = value[str(key)]
        else:
            raise GraphError(f"no {key!r} at {path!r}")
    return value


def set_path(document: Any, path: Any, value: Any) -> None:
    keys = json_path(path)
    if not keys:
        raise GraphError("an empty path")
    target = document
    for key in keys[:-1]:
        if isinstance(target, list) and isinstance(key, int):
            target = target[key]
        elif isinstance(target, dict):
            target = target.setdefault(str(key), {})
        else:
            raise GraphError(f"cannot go into {key!r} of {path!r}")
    last = keys[-1]
    if isinstance(target, list) and isinstance(last, int):
        target[last] = value
    elif isinstance(target, dict):
        target[str(last)] = value
    else:
        raise GraphError(f"cannot set {last!r} of {path!r}")


def project_file(root: str | Path, relative: str) -> Path:
    """A file inside the project; a :class:`GraphError` for a path that would leave it."""
    base = Path(root).resolve()
    rel = str(relative or "").replace("\\", "/").strip("/")
    if not rel or ":" in rel or any(p in ("", ".", "..", ".git") for p in rel.split("/")):
        raise GraphError(f"{relative!r} is not a file of the project")
    target = (base / rel).resolve()
    if base not in target.parents:
        raise GraphError(f"{relative!r} is not a file of the project")
    return target


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise GraphError(f"{path.name} could not be read: {error}") from error


def _write_json(path: Path, value: Any) -> None:
    from saengine.pipeline.project import write_text

    write_text(path, json.dumps(value, indent="\t", ensure_ascii=False) + "\n")


def _project(inputs: dict[str, Any], context: dict[str, Any]) -> str:
    root = inputs.get("project") or context.get("projectRoot")
    if not root:
        raise GraphError("no project: wire a project or run the graph in one")
    from saengine.pipeline.project import ProjectError, open_project

    try:
        return str(open_project(root).root)
    except ProjectError as error:
        raise GraphError(str(error)) from error


# ─────────────────────────────────────────── node runs ───────────────────────────────────────────


def _value(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    return {"value": i.get("value")}


def _number_node(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    return {"value": _number(i.get("value"), "value")}


def _list_node(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    return {"list": _list(i.get("items"))}


def _range(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    start, stop, step = (_number(i.get(k), k) for k in ("start", "stop", "step"))
    if step == 0 or (stop - start) / step > 1000 or (stop - start) / step < 0:
        raise GraphError("range: a step towards stop, at most 1000 values")
    values, k = [], 0
    while (step > 0 and start + k * step <= stop + 1e-9) or (
        step < 0 and start + k * step >= stop - 1e-9
    ):
        values.append(round(start + k * step, 9))
        k += 1
    return {"list": values}


def _math(op: str) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    def run(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
        a, b = _number(i.get("a"), "a"), _number(i.get("b"), "b")
        if op == "divide" and b == 0:
            raise GraphError("division by zero")
        result = {
            "add": a + b,
            "subtract": a - b,
            "multiply": a * b,
            "divide": a / b if b else 0.0,
        }[op]
        return {"result": result}

    return run


def _pick(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    return {"value": get_path(i.get("value"), i.get("path"))}


def _read_part(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    root = _project(i, c)
    return {"json": _read_json(project_file(root, str(i.get("file")))), "project": root}


def _set_value(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    root = _project(i, c)
    path = project_file(root, str(i.get("file")))
    document = _read_json(path)
    set_path(document, i.get("path"), i.get("value"))
    _write_json(path, document)
    return {"project": root}


def _scale_grids(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from saengine.automation.studies import apply_parameter

    root = _project(i, c)
    notes = apply_parameter(
        Path(root),
        {"kind": "gridSpacing", "axis": str(i.get("axis") or "both")},
        _number(i.get("factor"), "factor"),
    )
    return {"project": root, "notes": notes}


def _new_building(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from saengine.rpc.handlers import new_building

    dest = i.get("destParent") or (
        str(Path(c["projectRoot"]).parent) if c.get("projectRoot") else None
    )
    if not dest:
        raise GraphError("destParent: the folder to create the project in")
    spec = {
        "name": str(i.get("name") or "Building"),
        "gridsX": [_number(v, "gridsX") for v in _list(i.get("gridsX"))],
        "gridsY": [_number(v, "gridsY") for v in _list(i.get("gridsY"))],
        "storyCount": int(_number(i.get("storyCount"), "storyCount")),
        "typicalHeight": _number(i.get("typicalHeight"), "typicalHeight"),
        "system": str(i.get("system") or "rcFrame"),
    }
    answer = new_building(spec, str(dest), spec["name"], bool(i.get("overwrite")), None)
    if answer.get("error"):
        raise GraphError(str(answer["error"]))
    return {"project": answer.get("root")}


def _shape_input(shape: Any) -> Any:
    """The parsed shape (``saengine.library.shapes.ShapeInput``) of a shape's JSON."""
    from pydantic import ValidationError

    from saengine.library.shapes import ShapeInput

    if isinstance(shape, str):
        try:
            shape = json.loads(shape)
        except ValueError as error:
            raise GraphError(f"shape: not JSON ({error})") from error
    if isinstance(shape, dict) and "shape" in shape and "kind" not in shape:
        shape = shape["shape"]
    try:
        return ShapeInput.model_validate({"shape": shape}).shape
    except ValidationError as error:
        raise GraphError(f"shape: {error.errors()[0]['msg']}") from error


def _shape(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """The shape (passed on as its JSON, so the insert node builds it again) and how many
    members, panels and supports it has."""
    from saengine.library.shapes import shape_geometry

    parsed = _shape_input(i.get("shape"))
    geometry = shape_geometry(parsed)
    return {
        "geometry": {
            "shape": parsed.model_dump(mode="json"),
            "members": len(geometry.members),
            "areas": len(geometry.areas),
            "supports": len(geometry.supports),
            "notes": list(geometry.notes),
        }
    }


def _insert(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from saengine.library.shapes import insert, shape_geometry
    from saengine.library.structure import StructuralModel
    from saengine.pipeline.project import STRUCTURE_PART, write_text

    root = _project(i, c)
    path = Path(root) / STRUCTURE_PART.folder / str(STRUCTURE_PART.main_file)
    if not path.is_file():
        raise GraphError("the project has no structural model (05 Structural Model)")
    model = StructuralModel.model_validate_json(path.read_text("utf-8"))
    geometry = shape_geometry(_shape_input(i.get("geometry")))
    updated, added, existing = insert(model, geometry)
    write_text(path, updated.model_dump_json(indent=2, exclude_none=True) + "\n")
    return {"project": root, "added": len(added), "existing": existing}


def _run(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from saengine.pipeline.run_all import run_all

    root = _project(i, c)
    steps = [s for s in re.split(r"[,\s]+", str(i.get("steps") or "")) if s] or None
    try:
        result = run_all(root, steps=steps)
    except ValueError as error:
        raise GraphError(str(error)) from error
    return {
        "project": root,
        "summary": {"ok": result.ok, "stoppedAt": result.stopped_at, "summary": result.summary},
    }


def _design(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from saengine.automation.studies import design_metrics

    root = _project(i, c)
    metrics = design_metrics(Path(root))
    return {"summary": metrics, "maxUtilisation": metrics.get("maxUtilisation")}


def _drift(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from saengine.automation.studies import drift_metric

    return {"drift": drift_metric(Path(_project(i, c)))}


def _boq(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from saengine.automation.studies import boq_metrics

    metrics = boq_metrics(Path(_project(i, c)))
    return {"summary": metrics, "cost": metrics.get("cost"), "steelKg": metrics.get("steelKg")}


def _export(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    from saengine.exporters.exchange import rpc_export

    answer = rpc_export({"projectRoot": _project(i, c), "format": str(i.get("format") or "s2k")})
    if answer.get("error"):
        raise GraphError(str(answer["error"]))
    return {"path": answer.get("path")}


def _show(i: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    return {"value": i.get("value")}


P = Port
NODE_TYPES: dict[str, NodeType] = {
    t.id: t
    for t in (
        NodeType(
            "value.number",
            "Number",
            "Values",
            (P("value", "number", 0),),
            (P("value", "number"),),
            _number_node,
        ),
        NodeType(
            "value.text", "Text", "Values", (P("value", "text", ""),), (P("value", "text"),), _value
        ),
        NodeType(
            "value.list",
            "List",
            "Values",
            (P("items", "text", "1, 2, 3", "Comma-separated, or a JSON list."),),
            (P("list", "list"),),
            _list_node,
        ),
        NodeType(
            "math.range",
            "Range",
            "Values",
            (P("start", "number", 0), P("stop", "number", 10), P("step", "number", 1)),
            (P("list", "list"),),
            _range,
        ),
        NodeType(
            "math.add",
            "Add",
            "Values",
            (P("a", "number", 0), P("b", "number", 0)),
            (P("result", "number"),),
            _math("add"),
        ),
        NodeType(
            "math.subtract",
            "Subtract",
            "Values",
            (P("a", "number", 0), P("b", "number", 0)),
            (P("result", "number"),),
            _math("subtract"),
        ),
        NodeType(
            "math.multiply",
            "Multiply",
            "Values",
            (P("a", "number", 1), P("b", "number", 1)),
            (P("result", "number"),),
            _math("multiply"),
        ),
        NodeType(
            "math.divide",
            "Divide",
            "Values",
            (P("a", "number", 1), P("b", "number", 1)),
            (P("result", "number"),),
            _math("divide"),
        ),
        NodeType(
            "value.pick",
            "Pick",
            "Values",
            (
                P("value", "json"),
                P("path", "text", "", "Keys and indices, e.g. summary/maxUtilisation."),
            ),
            (P("value", "any"),),
            _pick,
            "A value inside another, by its path.",
        ),
        NodeType(
            "geometry.newBuilding",
            "New building",
            "Geometry",
            (
                P("name", "text", "Building"),
                P("gridsX", "list", "6000, 6000", "Spacings [mm]."),
                P("gridsY", "list", "5000, 5000", "Spacings [mm]."),
                P("storyCount", "number", 4),
                P("typicalHeight", "number", 3000, "[mm]"),
                P("system", "text", "rcFrame"),
                P(
                    "destParent",
                    "text",
                    "",
                    "Folder of the new project (default: beside this one).",
                ),
                P("overwrite", "any", False),
            ),
            (P("project", "project"),),
            _new_building,
            "A new building project from grids and storeys (the New Building generator).",
            writes=True,
        ),
        NodeType(
            "geometry.shape",
            "Parametric shape",
            "Geometry",
            (
                P(
                    "shape",
                    "json",
                    '{"kind": "PortalFrame"}',
                    "The shape's input, as the 3D modeller's Shape dialog makes it.",
                ),
            ),
            (P("geometry", "geometry"),),
            _shape,
            "Members, areas and supports of a parametric shape.",
        ),
        NodeType(
            "geometry.insert",
            "Insert into the structural model",
            "Geometry",
            (P("project", "project"), P("geometry", "geometry")),
            (P("project", "project"),),
            _insert,
            "Adds the geometry to 05 Structural Model (writes it).",
            writes=True,
        ),
        NodeType(
            "project.read",
            "Read a part",
            "Project",
            (
                P("project", "project"),
                P("file", "text", "02 Project Settings/project-settings.json"),
            ),
            (P("json", "json"), P("project", "project")),
            _read_part,
        ),
        NodeType(
            "project.setValue",
            "Set a value",
            "Project",
            (
                P("project", "project"),
                P("file", "text", "05 Floor Plan/floor-plan.json"),
                P("path", "text", "stories/1/elevation"),
                P("value", "any"),
            ),
            (P("project", "project"),),
            _set_value,
            "Writes one value of a part file (saved at once).",
            writes=True,
        ),
        NodeType(
            "project.scaleGrids",
            "Scale grid spacings",
            "Project",
            (
                P("project", "project"),
                P("factor", "number", 1.0),
                P("axis", "text", "both", "x, y or both"),
            ),
            (P("project", "project"), P("notes", "list")),
            _scale_grids,
            "Every grid spacing of the floor plan times the factor (writes it).",
            writes=True,
        ),
        NodeType(
            "run.steps",
            "Run",
            "Run",
            (
                P("project", "project"),
                P("steps", "text", "bim, derive, analysis, design", "Run All's steps; empty: all."),
            ),
            (P("project", "project"), P("summary", "json")),
            _run,
            "Run All's steps on the project (headless, as the command line).",
            writes=True,
        ),
        NodeType(
            "results.design",
            "Design summary",
            "Results",
            (P("project", "project"),),
            (P("summary", "json"), P("maxUtilisation", "number")),
            _design,
        ),
        NodeType(
            "results.drift",
            "Largest storey drift",
            "Results",
            (P("project", "project"),),
            (P("drift", "number"),),
            _drift,
        ),
        NodeType(
            "results.boq",
            "Cost and quantities",
            "Results",
            (P("project", "project"),),
            (P("summary", "json"), P("cost", "number"), P("steelKg", "number")),
            _boq,
        ),
        NodeType(
            "results.export",
            "Export",
            "Results",
            (
                P("project", "project"),
                P("format", "text", "s2k", "s2k, std, saf, sdnf, cis2 or webViewer"),
            ),
            (P("path", "text"),),
            _export,
            writes=True,
        ),
        NodeType(
            "output.show",
            "Show",
            "Output",
            (P("value", "any"),),
            (P("value", "any"),),
            _show,
            "Shows the value on the node after a run.",
        ),
    )
}


def node_types() -> dict[str, Any]:
    return {"schema": SCHEMA, "types": [t.to_json() for t in NODE_TYPES.values()]}


# ─────────────────────────────────────────── running ───────────────────────────────────────────


@dataclass
class GraphRun:
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": not self.errors,
            "order": self.order,
            "outputs": {k: _safe(v) for k, v in self.outputs.items()},
            "errors": self.errors,
            "skipped": self.skipped,
        }


def _safe(value: Any) -> Any:
    """A JSON value of at most :data:`MAX_OUTPUT_CHARS` characters per output."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = json.dumps(str(value))
    if len(text) > MAX_OUTPUT_CHARS:
        return {"truncated": text[:MAX_OUTPUT_CHARS]}
    return json.loads(text)


def check_graph(graph: dict[str, Any]) -> list[str]:
    """What is wrong with a graph document (empty when it can run)."""
    problems = []
    if graph.get("schema") != SCHEMA:
        problems.append(f"schema: {SCHEMA} expected")
    ids = set()
    for n in graph.get("nodes") or []:
        if not isinstance(n, dict) or not n.get("id"):
            problems.append("a node without an id")
            continue
        if n["id"] in ids:
            problems.append(f"node {n['id']}: the id is used twice")
        ids.add(n["id"])
        if n.get("type") not in NODE_TYPES:
            problems.append(f"node {n['id']}: unknown type {n.get('type')!r}")
    for e in graph.get("edges") or []:
        try:
            src, dst = e["from"], e["to"]
            a, b = (
                NODE_TYPES[_node(graph, src["node"])["type"]],
                NODE_TYPES[_node(graph, dst["node"])["type"]],
            )
        except (KeyError, TypeError, GraphError):
            problems.append(f"a wire to or from a missing node: {e}")
            continue
        if src["port"] not in {p.name for p in a.outputs}:
            problems.append(f"{src['node']} has no output {src['port']!r}")
        if dst["port"] not in {p.name for p in b.inputs}:
            problems.append(f"{dst['node']} has no input {dst['port']!r}")
    if not problems:
        try:
            _order(graph)
        except GraphError as error:
            problems.append(str(error))
    return problems


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    for n in graph.get("nodes") or []:
        if n.get("id") == node_id:
            return n
    raise GraphError(f"no node {node_id}")


def _order(graph: dict[str, Any]) -> list[str]:
    nodes = [n["id"] for n in graph.get("nodes") or []]
    incoming: dict[str, set[str]] = {n: set() for n in nodes}
    for e in graph.get("edges") or []:
        incoming[e["to"]["node"]].add(e["from"]["node"])
    order, done = [], set()
    while len(order) < len(nodes):
        ready = [n for n in nodes if n not in done and incoming[n] <= done]
        if not ready:
            raise GraphError("the wires make a loop: a node waits for itself")
        order.append(ready[0])
        done.add(ready[0])
    return order


def run_graph(
    graph: dict[str, Any], project_root: str | None = None, *, until: str | None = None
) -> GraphRun:
    """Runs ``graph`` (see the module notes); ``until``: only that node and what it needs."""
    problems = check_graph(graph)
    if problems:
        raise GraphError("; ".join(problems))
    order = _order(graph)
    if until is not None:
        needed = {until}
        changed = True
        while changed:
            changed = False
            for e in graph.get("edges") or []:
                if e["to"]["node"] in needed and e["from"]["node"] not in needed:
                    needed.add(e["from"]["node"])
                    changed = True
        order = [n for n in order if n in needed]
    context = {"projectRoot": project_root}
    run = GraphRun(order=order)
    failed: set[str] = set()
    for node_id in order:
        node = _node(graph, node_id)
        spec = NODE_TYPES[node["type"]]
        wires = [e for e in graph.get("edges") or [] if e["to"]["node"] == node_id]
        if any(e["from"]["node"] in failed for e in wires):
            failed.add(node_id)
            run.skipped.append(node_id)
            continue
        params = node.get("params") or {}
        inputs = {p.name: params.get(p.name, p.default) for p in spec.inputs}
        for e in wires:
            inputs[e["to"]["port"]] = run.outputs.get(e["from"]["node"], {}).get(e["from"]["port"])
        try:
            run.outputs[node_id] = spec.run(inputs, context)
        except GraphError as error:
            run.errors[node_id] = str(error)
            failed.add(node_id)
        except (OSError, ValueError, KeyError, TypeError) as error:
            run.errors[node_id] = f"{type(error).__name__}: {error}"
            failed.add(node_id)
    return run


# ─────────────────────────────────────────── files ───────────────────────────────────────────


def graphs_folder(project_root: str | Path) -> Path:
    return Path(project_root) / FOLDER / GRAPHS_FOLDER


def new_graph(name: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "name": name,
        "nodes": [
            {"id": "n1", "type": "run.steps", "x": 60, "y": 80, "params": {}},
            {"id": "n2", "type": "results.design", "x": 340, "y": 60, "params": {}},
            {"id": "n3", "type": "output.show", "x": 600, "y": 60, "params": {}},
        ],
        "edges": [
            {"from": {"node": "n1", "port": "project"}, "to": {"node": "n2", "port": "project"}},
            {"from": {"node": "n2", "port": "summary"}, "to": {"node": "n3", "port": "value"}},
        ],
    }


def list_graphs(project_root: str | Path) -> dict[str, Any]:
    folder = graphs_folder(project_root)
    graphs = []
    for path in sorted(folder.glob(f"*{EXTENSION}")) if folder.is_dir() else []:
        try:
            name = json.loads(path.read_text("utf-8")).get("name") or path.name
        except (OSError, ValueError):
            name = path.name
        graphs.append({"path": str(path), "name": name})
    return {"graphs": graphs, "folder": str(folder)}


def create_graph(project_root: str | Path, name: str) -> dict[str, Any]:
    safe = re.sub(r'[<>:"/\\|?*]+', "-", name).strip().strip(".") or "Graph"
    path = graphs_folder(project_root) / f"{safe}{EXTENSION}"
    if path.exists():
        raise GraphError(f"{path.name} exists already")
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, new_graph(name))
    return {"path": str(path)}


def rpc_run(params: dict[str, Any]) -> dict[str, Any]:
    """``graph/run`` ``{graph | path, projectRoot?, until?}`` -> :class:`GraphRun` JSON or
    ``{"ok": false, "problems"}``."""
    try:
        graph = params.get("graph")
        if graph is None:
            graph = _read_json(Path(str(params["path"])))
        return run_graph(graph, params.get("projectRoot"), until=params.get("until")).to_json()
    except (GraphError, KeyError) as error:
        return {"ok": False, "problems": [str(error)]}


__all__ = [
    "EXTENSION",
    "NODE_TYPES",
    "SCHEMA",
    "GraphError",
    "GraphRun",
    "check_graph",
    "create_graph",
    "get_path",
    "list_graphs",
    "new_graph",
    "node_types",
    "rpc_run",
    "run_graph",
    "set_path",
]
