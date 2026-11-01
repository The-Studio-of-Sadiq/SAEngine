"""One member's results along its length, and a column's interaction diagram.

The member detail window of the FEM results (ETABS's "frame detail"):

- :func:`member_forces`: the section forces N, Vy, Vz, T, My, Mz (local axes, tension
  positive; :func:`saengine.fem.display.element_section_forces`) and the deflection (local axes,
  relative to the chord between the member's ends, and the absolute displacement) at stations
  along a building member made of one or more analysis elements (``C3``, ``C3#2``, ...), for
  every static case and load combination of the project settings;
- :func:`column_interaction`: a concrete column's φ-factored P-M interaction curves about its
  section x and y axes and the P-Mx-My contour at the governing axial force, with the demand
  points of every load combination. Worked out by SAEngine's own design checks
  (:func:`saengine.design.required.gather`, :class:`saengine.design.rc.InteractionSurface`;
  Run All's own gathering while current, :func:`saengine.pipeline.design_mode.gathered`):
  slow (minutes), so once per run for all columns, kept in ``column-interaction.json`` beside
  the results while the run and the design inputs stay the same.

Values in the model's units (m, N, N·m) for the forces; the interaction diagrams in kN and kN·m.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem.story_response import _finite

CACHE_FILE = "column-interaction.json"
CACHE_SCHEMA = "saengine.columnInteraction/1"
#: Axial forces the P-M curves are sampled at, from pure tension to φPn,max.
CURVE_POINTS = 41

_lock = threading.Lock()


def member_of(name: str) -> str:
    """The building member an analysis element belongs to (``C3#2`` -> ``C3``)."""
    return name.split("#")[0]


def _chain(elements: list[Any]) -> list[tuple[Any, bool]]:
    """The member's elements in order from one end to the other, each with whether it runs
    backwards (j to i) along the member."""
    if len(elements) <= 1:
        return [(e, False) for e in elements]
    ends: dict[int, int] = {}
    for e in elements:
        ends[e.i] = ends.get(e.i, 0) + 1
        ends[e.j] = ends.get(e.j, 0) + 1
    start = next((e.i for e in elements if ends[e.i] == 1), elements[0].i)
    left, order, node = list(elements), [], start
    while left:
        nxt = next((e for e in left if node in (e.i, e.j)), None)
        if nxt is None:  # not a chain: keep the rest as they come
            order += [(e, False) for e in left]
            break
        left.remove(nxt)
        backwards = nxt.j == node
        order.append((nxt, backwards))
        node = nxt.i if backwards else nxt.j
    return order


@dataclass
class MemberResults:
    """The last steps a member's window needs of a static case: its elements' end forces, its
    nodes' displacements and the load factors (the shape of ``StaticResults`` for them)."""

    load_factors: np.ndarray
    element_forces: dict[int, np.ndarray]
    node_disp: dict[int, np.ndarray]


def _read_some(group: Any, name: str, keys: list[int]) -> dict[int, np.ndarray]:
    """The arrays of ``group[name]`` of the ids ``keys`` only, reading just their slices of a
    packed group (one id's values, not the whole case's)."""
    if name not in group:
        return {}
    sub = group[name]
    if not sub.attrs.get("packed"):
        return {k: sub[str(k)][()] for k in keys if str(k) in sub}
    ids = sub["ids"][()]
    order = np.argsort(ids)
    offsets, shapes, values = sub["offsets"], sub["shapes"], sub["values"]
    out: dict[int, np.ndarray] = {}
    for key in keys:
        at = int(np.searchsorted(ids, key, sorter=order))
        if at >= len(ids) or int(ids[order[at]]) != key:
            continue
        i = int(order[at])
        start, end = (int(v) for v in offsets[i : i + 2])
        row = shapes[i].tolist()
        out[key] = values[start:end].reshape(row[1 : 1 + row[0]])
    return out


def member_results(
    entry: dict[str, Any], out_dir: str | Path, element_ids: list[int], node_ids: list[int]
) -> MemberResults:
    """What :func:`member_forces` reads of a static case: only the member's elements and nodes
    (a whole case of a tall building is tens of megabytes)."""
    import h5py

    with h5py.File(Path(out_dir) / entry["files"][0], "r") as f:
        return MemberResults(
            load_factors=f["load_factors"][()] if "load_factors" in f else np.empty(0),
            element_forces=_read_some(f, "element_forces", element_ids),
            node_disp=_read_some(f, "node_disp", node_ids),
        )


def _section_name(project: dict[str, Any], element_id: int) -> str | None:
    """The name of an element's section (SAEngine: the object type's, ``C400x600 column``)."""
    element = next((e for e in project.get("elements", []) if e.get("id") == element_id), {})
    section = next(
        (s for s in project.get("sections", []) if s.get("id") == element.get("section_id")), {}
    )
    return section.get("name") or None


def member_forces(out_dir: str | Path, project_path: str | Path, member: str) -> dict[str, Any]:
    """``{"member", "kind" ("column", "beam", "brace"), "length", "elements", "section", "axes":
    {"x", "y", "z"}, "stations": [x], "results": [{"key", "label", "kind", "forces": [[N, Vy, Vz, T, My,
    Mz]], "deflection": [[u1, u2, u3]], "displacement": [[ux, uy, uz]]}], "notes"}``: stations in
    m from the member's start (the end with the lower node, the bottom of a column); forces as
    at a cut, of the part beyond it on the part before (the first element's member axes,
    :func:`saengine.fem.derive.member_axes`: a beam's axis 2 up; an
    element running backwards has its forces turned to them); the deflection in the local axes
    relative to the chord between the ends; the displacement global."""

    from saengine.fem.derive import member_axes
    from saengine.fem.display import (
        _case_loads,
        _code,
        _elements,
        _last,
        _load,
        _manifest,
        element_displacements,
        element_section_forces,
    )
    from saengine.fem.thermal import end_force_corrections, load_corrections

    manifest = _manifest(out_dir)
    if manifest is None:
        raise ValueError("there are no results; run the analysis first")
    project = _load(project_path)
    # Only this member's elements and their nodes are read (a tall building has thousands).
    mine = [
        e
        for e in project.get("elements", [])
        if member_of(e.get("name") or str(e.get("id"))) == member
    ]
    own = _elements({**project, "elements": mine})
    if not own:
        raise ValueError(f"{member} is not a frame member of the analysis model")
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project["nodes"]}
    chain = _chain(own)
    element_ids = [e.id for e in own]
    node_ids = sorted({n for e in own for n in (e.i, e.j)})
    # Run from the lower end (a column's bottom), else from the end nearer the origin.
    first, last = chain[0], chain[-1]
    a = coords[first[0].j if first[1] else first[0].i]
    b = coords[last[0].i if last[1] else last[0].j]
    if (b[2] - a[2] < -1e-6) or (abs(b[2] - a[2]) <= 1e-6 and tuple(b[:2]) < tuple(a[:2])):
        chain = [(e, not back) for e, back in reversed(chain)]
        a, b = b, a
    # The member axes (a beam's axis 2 up): the forces are turned to them below.
    axes = member_axes(chain[0][0].axes)
    if chain[0][1]:
        axes = np.array([-axes[0], axes[1], -axes[2]])  # the same right-handed frame, reversed
    chord = b - a
    length = float(np.linalg.norm(chord))
    vertical = abs(chord[2]) > 0.9 * length if length > 0 else False
    horizontal = abs(chord[2]) < 0.1 * length if length > 0 else False
    kind = "column" if vertical else "beam" if horizontal else "brace"

    # The static cases and the combinations of the project settings: (key, label, kind, parts).
    by_code: dict[str, tuple[dict[str, Any], Any]] = {}
    keys: list[tuple[str, str, str, list[tuple[float, Any, int]]]] = []
    for entry in manifest["cases"]:
        if entry.get("result_type") != "StaticResults":
            continue
        results = member_results(entry, out_dir, element_ids, node_ids)
        by_code[_code(entry["case_name"])] = (entry, results)
        keys.append(
            (
                f"case:{entry['case_id']}",
                entry["case_name"],
                "static",
                [(1.0, results, int(entry["case_id"]))],
            )
        )
    notes: list[str] = []
    if project.get("meta", {}).get("author") == "SAEngine":
        from saengine.fem.combinations import (
            combination_factors,
            combination_label,
            settings_beside,
        )

        settings = settings_beside(project_path)
        for number, combination in enumerate(settings.combinations if settings else [], 1):
            factors = combination_factors(combination, set(by_code))
            if factors and set(factors) <= set(by_code):
                parts = [
                    (f, by_code[c][1], int(by_code[c][0]["case_id"])) for c, f in factors.items()
                ]
                label = combination_label(combination, set(by_code))
                keys.append((f"combination:{number}", label, "combination", parts))
    thermal = load_corrections(project_path)
    code_of = {int(e["case_id"]): _code(e["case_name"]) for e in manifest["cases"]}
    # Per case, once: the member's uniform loads and its temperature end-force corrections.
    wanted = set(element_ids)
    case_loads: dict[int, dict[int, np.ndarray]] = {}
    corrections: dict[int, dict[int, np.ndarray]] = {}
    for *_, parts in keys:
        for _, _, aid in parts:
            if aid not in case_loads:
                every = _case_loads(project, aid)
                case_loads[aid] = {k: v for k, v in every.items() if k in wanted}
                found = end_force_corrections(thermal, code_of.get(aid, ""))
                corrections[aid] = {k: v for k, v in found.items() if k in wanted}

    stations: list[float] = []
    offset = 0.0
    for element, backwards in chain:
        count = 11
        xs = np.linspace(0.0, element.length, count)
        if backwards:
            xs = xs[::-1]
        stations += [offset + float(x if not backwards else element.length - x) for x in xs]
        offset += element.length

    out = []
    for key, label, kind_of, parts in keys:
        loads: dict[int, np.ndarray] = {}
        for factor, results, analysis_id in parts:
            reached = float(results.load_factors[-1]) if len(results.load_factors) else 1.0
            for element_id, w in case_loads[analysis_id].items():
                loads[element_id] = loads.get(element_id, np.zeros(3)) + factor * reached * w
        forces_rows, displacement_rows = [], []
        for element, backwards in chain:
            end = sum(
                f
                * (_last(r.element_forces, element.id, 12) + corrections[aid].get(element.id, 0.0))
                for f, r, aid in parts
            )
            disp = {
                n: sum(f * _last(r.node_disp, n, 6) for f, r, _ in parts)
                for n in (element.i, element.j)
            }
            load = loads.get(element.id, np.zeros(3))
            forces = element_section_forces(element, end, load)
            moved = element_displacements(element, disp[element.i], disp[element.j], load)
            if backwards:
                forces, moved = forces[::-1], moved[::-1]
            # To the member's local axes. Walked backwards, the part before a cut is the one
            # beyond it for the element: the forces on it are the opposite ones.
            turn = axes @ element.axes.T
            sign = -1.0 if backwards else 1.0
            f_local = sign * np.column_stack([forces[:, :3] @ turn.T, forces[:, 3:] @ turn.T])
            forces_rows += f_local.tolist()
            displacement_rows += moved.tolist()
        disp_arr = np.asarray(displacement_rows)
        local = disp_arr @ axes.T
        t = np.asarray(stations) / length if length > 0 else np.zeros(len(stations))
        relative = local - (local[0] + np.outer(t, local[-1] - local[0]))
        out.append(
            {
                "key": key,
                "label": label,
                "kind": kind_of,
                "forces": np.round(forces_rows, 3).tolist(),
                "deflection": np.round(relative, 9).tolist(),
                "displacement": np.round(disp_arr, 9).tolist(),
            }
        )
    return _finite(
        {
            "member": member,
            "kind": kind,
            "length": length,
            "elements": [e.name for e, _ in chain],
            "section": _section_name(project, chain[0][0].id),
            "axes": {"x": axes[0].tolist(), "y": axes[1].tolist(), "z": axes[2].tolist()},
            "stations": stations,
            "results": out,
            "notes": notes,
        }
    )


# ─────────────────────────────── column interaction ───────────────────────────────


def _stamp(out_dir: Path, project_path: Path) -> str:
    """What the interaction diagrams depend on: the run (its manifest) and the design inputs."""
    root = project_path.resolve().parent.parent
    digest = hashlib.sha256()
    for path in (
        out_dir / "manifest.json",
        project_path,
        root / "02 Project Settings/project-settings.json",
        root / "03 Materials/materials.json",
        root / "04 Objects/objects.json",
        root / "06 BIM/bim.json",
    ):
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"-")
    return digest.hexdigest()


def _demand_points(points: list[tuple]) -> list[dict[str, Any]]:
    """Per load combination the demands that matter on the diagrams: the largest axial force,
    the largest Mx, the largest My and the largest resultant moment (kN, kN·m)."""
    by_combination: dict[str, list[tuple]] = {}
    for point in points:
        by_combination.setdefault(point[3], []).append(point)
    out = []
    for combination, rows in by_combination.items():
        chosen = {
            max(rows, key=lambda p: p[0]),
            max(rows, key=lambda p: abs(p[1])),
            max(rows, key=lambda p: abs(p[2])),
            max(rows, key=lambda p: math.hypot(p[1], p[2])),
        }
        for pu, mx, my, _, where in chosen:
            out.append(
                {
                    "combination": combination,
                    "where": where,
                    "P": pu / 1e3,
                    "Mx": abs(mx) / 1e6,
                    "My": abs(my) / 1e6,
                }
            )
    return out


def _diagram(section: Any, surface: Any, points: list[tuple]) -> dict[str, Any]:
    """The P-M curves about x and y and the contour at the governing point's axial force."""
    pus = np.linspace(-section.phi_tension, section.phi_pn_max, CURVE_POINTS)
    curves = {}
    for name, angle in (("x", 0.0), ("y", math.pi / 2)):
        curves[name] = [
            [float(pu / 1e3), float(surface.moment_capacity(float(pu), angle) / 1e6)] for pu in pus
        ]
    governing = None
    for pu, mx, my, combination, where in points:
        result = surface.check(pu, abs(mx), abs(my))
        if governing is None or result.utilisation > governing[0]:
            governing = (result.utilisation, pu, combination, where)
    contour = None
    if governing is not None:
        ring = surface.contour(governing[1])
        if ring is not None:
            contour = (np.asarray(ring) / 1e6).round(3).tolist()
    return {
        "phiPnMax": section.phi_pn_max / 1e3,
        "phiTension": section.phi_tension / 1e3,
        "curves": curves,
        "contour": contour,
        "governing": None
        if governing is None
        else {
            "utilisation": governing[0],
            "P": governing[1] / 1e3,
            "combination": governing[2],
            "where": governing[3],
        },
        "points": _demand_points(points),
    }


def column_interaction(
    out_dir: str | Path, project_path: str | Path, member: str | None = None
) -> dict[str, Any]:
    """The interaction diagrams of the run's concrete columns (all, or ``member``'s):
    ``{"columns": {id: {"type", "assumedBars", "phiPnMax", "phiTension", "curves": {"x": [[P,
    M]], "y": [...]}, "contour": [[Mx, My]] | None, "governing": {...} | None, "points": [{"combination",
    "where", "P", "Mx", "My"}]}}, "notes"}`` (kN, kN·m; compression positive; moments about the
    section's own x and y axes as the design checks take them). Worked out once per run and
    kept beside the results."""
    from saengine.design.rc import InteractionSurface
    from saengine.pipeline import design_mode

    out_dir, project_path = Path(out_dir), Path(project_path)
    cache = out_dir / CACHE_FILE
    with _lock:
        stamp = _stamp(out_dir, project_path)
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
        if not cached or cached.get("schema") != CACHE_SCHEMA or cached.get("stamp") != stamp:
            # Run All's design step's checks while they are current (design_mode.gathered).
            gathered = design_mode.gathered(out_dir, project_path, substructure=False)
            surfaces: dict[str, Any] = {}
            columns: dict[str, Any] = {}
            for entry in gathered.collect.get("members", []):
                if entry.get("kind") != "column" or not entry.get("points"):
                    continue
                type_id = entry["type"]
                if type_id not in surfaces:
                    surfaces[type_id] = InteractionSurface(entry["section"])
                columns[entry["id"]] = {
                    "type": type_id,
                    "assumedBars": type_id in gathered.assumed,
                    **_diagram(entry["section"], surfaces[type_id], entry["points"]),
                }
            cached = _finite(
                {
                    "schema": CACHE_SCHEMA,
                    "stamp": stamp,
                    "columns": columns,
                    "notes": [
                        (
                            "φ-factored capacities (the code pack's concrete design); "
                            "slender columns' demands carry their magnified moments."
                        )
                    ],
                }
            )
            try:
                cache.write_text(json.dumps(cached), encoding="utf-8")
            except OSError:
                pass
    columns = cached["columns"]
    if member is not None:
        columns = {member: columns[member]} if member in columns else {}
    return {"columns": columns, "notes": cached.get("notes", [])}
