"""The result tables of a run, read one at a time (the FEM view's Result Tables panel and its
Excel export).

:func:`table_index` lists, without reading any result, every result that has tables (the run's
cases; for a model SAEngine derived, the load combinations of the project settings, the response
spectrum design combinations and the envelope of the combinations) and the tables of each.
:func:`result_table` works out one table of one result. A tall building's run has thousands of
elements and dozens of results: all of them at once took minutes and hundreds of megabytes.

The tables of a model SAEngine derived are in the units the engineer reads (kN, kN·m, mm) with a
fixed number of decimals, its points named by grid and level (``B-3, Level 2``) and its members'
forces given per member at the stations along it (the ends of its analysis pieces, ``C3#2``) in
the member axes 1, 2, 3 (:func:`saengine.fem.derive.member_axes`: a beam's axis 2 up, so its
gravity bending is M3). Other results (modal periods, spectrum, time history, pushover) keep
OpenSees Studio's tables in model units.

:func:`export_xlsx` streams the chosen tables to an Excel workbook (``write_only``, to a temporary
file renamed at the end): one sheet per kind of table with the result in its first column, the
progress readable and the export cancellable (:func:`export_progress`, :func:`cancel_export`).
"""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

#: Decimals of the values shown: forces and moments, displacements, rotations, stations.
FORCE_DECIMALS = 2
LENGTH_DECIMALS = 3
ROTATION_DECIMALS = 6
STATION_DECIMALS = 3

#: The tables of a static case or combination (id, title).
DISPLACEMENTS = ("displacements", "Joint displacements")
REACTIONS = ("reactions", "Support reactions")
MEMBER_FORCES = ("members", "Member forces")
SHELL_FORCES = ("shells", "Wall and slab forces")
ENVELOPE = ("envelope", "Member forces, envelope")
#: Linear buckling under a combination's axial forces (saengine.fem.buckling).
BUCKLING = ("buckling", "Buckling factors")
EFFECTIVE_LENGTHS = ("effectiveLengths", "Effective length factors (buckling)")

_KN = 1e-3
_MM = 1e3


# ─────────────────────────────── point and member names ───────────────────────────────


@dataclass
class _Names:
    """Grid and level names of the points of a SAEngine model (``B-3, Level 2``)."""

    x: list[tuple[float, str]] = field(default_factory=list)  # grid positions [m], labels
    y: list[tuple[float, str]] = field(default_factory=list)
    levels: list[tuple[float, str]] = field(default_factory=list)  # elevations [m], names

    @staticmethod
    def of(project_path: str | Path, project: dict[str, Any]) -> _Names:
        import json

        from saengine.fem.story_response import storey_levels

        names = _Names()
        root = Path(project_path).resolve().parent.parent
        try:
            plan = json.loads((root / "05 Floor Plan" / "floor-plan.json").read_text("utf-8"))
            grids = plan.get("grids") or {}
            names.x = [(float(g["position"]) / 1e3, str(g["label"])) for g in grids.get("x", [])]
            names.y = [(float(g["position"]) / 1e3, str(g["label"])) for g in grids.get("y", [])]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        try:
            names.levels = [
                (float(lv["z"]), str(lv["name"])) for lv in storey_levels(project, project_path)
            ]
        except (OSError, ValueError, KeyError, TypeError):
            names.levels = []
        return names

    @staticmethod
    def _on(lines: list[tuple[float, str]], value: float) -> str | None:
        for position, label in lines:
            if abs(position - value) <= 0.005:
                return label
        return None

    def point(self, coords: Any) -> str:
        """``B-3, Level 2``; off the grids ``x 13.01, y 18.00 m``; between levels ``z 1.75 m``."""
        x, y, z = (float(c) for c in coords[:3])
        gx, gy = self._on(self.x, x), self._on(self.y, y)
        if gx and gy:
            plan = f"{gx}-{gy}"
        elif gx:
            plan = f"{gx}, y {y:.2f} m"
        elif gy:
            plan = f"x {x:.2f} m, {gy}"
        else:
            plan = f"x {x:.2f}, y {y:.2f} m"
        level = self._on(self.levels, z)
        return f"{plan}, {level}" if level else f"{plan}, z {z:.2f} m"


def _member(name: str) -> str:
    return name.split("#")[0]


def _is_link(name: str) -> bool:
    """A link the derivation adds (a pinned end's spring ``<member>/pin``, a strut into a solid
    ``<member>/embed``): its forces are not a member's."""
    return "/" in _member(name)


# ─────────────────────────────── the index ───────────────────────────────


def _case_tables(entry: dict[str, Any], saengine: bool) -> list[tuple[str, str]]:
    kind = entry.get("result_type")
    if kind == "StaticResults":
        tables = [DISPLACEMENTS, REACTIONS, MEMBER_FORCES] if saengine else []
        if not saengine:
            tables = [("static:0", "Displacements"), ("static:1", "Reactions")]
            tables.append(("static:2", "Element forces"))
        if int(entry.get("completed_steps") or 1) > 1 and not entry.get("stages"):
            tables.append(("static:3", "Static history"))
        return tables
    if kind == "ModalResults":
        return [("modal:0", "Frequencies")]
    if kind == "ResponseSpectrumResults":
        return [("spectrum:0", "Combined displacements"), ("spectrum:1", "Modes")]
    if kind == "TransientResults":
        return [("history:0", "Peak displacements")]
    if kind == "PushoverResults":
        return [("pushover:0", "Curve"), ("pushover:1", "Displacements")] + [
            ("pushover:2", "Element forces")
        ]
    return []


def table_index(out_dir: str | Path, project_path: str | Path) -> dict[str, Any]:
    """``{"results": [{"key", "label", "group", "warnings", "tables": [{"id", "title"}]}]}``:
    every result with tables, in groups ``case``, ``combination``, ``spectrum`` (the response
    spectrum design combinations) and ``envelope``. Reads the manifest and the settings only."""
    from saengine.fem.display import _code, _load, _manifest

    manifest = _manifest(out_dir)
    if manifest is None:
        return {"results": []}
    project = _load(project_path)
    saengine = project.get("meta", {}).get("author") == "SAEngine"
    out: list[dict[str, Any]] = []
    static_codes: set[str] = set()
    for entry in manifest["cases"]:
        if entry.get("result_type") == "StaticResults":
            static_codes.add(_code(entry["case_name"]))
        out.append(
            {
                "key": f"case:{entry['case_id']}",
                "label": entry["case_name"],
                "group": "case",
                "warnings": list(entry.get("warnings", []))
                + (["the analysis stopped early"] if entry.get("early_stop") else []),
                "tables": [{"id": i, "title": t} for i, t in _case_tables(entry, saengine)],
            }
        )
    pushover = any(a.get("type") == "PushoverCase" for a in project.get("analyses", []))
    if not saengine or pushover:
        return {"results": out}
    from saengine.fem.combinations import (
        combination_factors,
        combination_label,
        settings_beside,
    )

    settings = settings_beside(project_path)
    formed = 0
    for number, combination in enumerate(settings.combinations if settings else [], 1):
        factors = combination_factors(combination, static_codes)
        missing = sorted(c for c in factors if c not in static_codes)
        formed += not missing
        out.append(
            {
                "key": f"combination:{number}",
                "label": combination_label(combination, static_codes),
                "group": "combination",
                "warnings": (
                    [f"not formed: case {', '.join(missing)} has no results (run it first)"]
                    if missing
                    else []
                ),
                "tables": []
                if missing
                else [
                    {"id": i, "title": t}
                    for i, t in (
                        DISPLACEMENTS,
                        REACTIONS,
                        MEMBER_FORCES,
                        BUCKLING,
                        EFFECTIVE_LENGTHS,
                    )
                ],
            }
        )
    seismic = _seismic(out_dir, settings)
    for number, data in enumerate((seismic or {}).get("combinations", []), 1):
        out.append(
            {
                "key": f"spectrum:{number}",
                "label": str(data.get("name", f"Spectrum design {number}")),
                "group": "spectrum",
                "warnings": [],
                "tables": [
                    {"id": MEMBER_FORCES[0], "title": "Member forces, S − E and S + E"},
                    {"id": REACTIONS[0], "title": "Support reactions, S − E and S + E"},
                ],
            }
        )
    if formed:
        out.append(
            {
                "key": "envelope",
                "label": "Envelope of all combinations",
                "group": "envelope",
                "warnings": [],
                "tables": [{"id": ENVELOPE[0], "title": ENVELOPE[1]}],
            }
        )
    return {"results": out}


def _seismic(out_dir: str | Path, settings: Any) -> dict[str, Any] | None:
    from saengine.fem import seismic_design as rs

    if settings is None or not rs.design_uses_spectrum(settings):
        return None
    summary = rs.load_summary(out_dir)
    return summary if summary and summary.get("available") else None


# ─────────────────────────────── one table ───────────────────────────────


def _table(
    name: str, title: str, columns: list[str], rows: list[list[Any]], notes: list[str] | None = None
) -> dict[str, Any]:
    return {"name": name, "title": title, "columns": columns, "rows": rows, "notes": notes or []}


def _cell(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _rounded(values: Any, decimals: int) -> list[Any]:
    return [_cell(round(float(v), decimals)) for v in values]


@dataclass
class _Model:
    """What the tables need of the analysis model, worked out once per table."""

    project: dict[str, Any]
    names: _Names
    coords: dict[int, np.ndarray]
    supports: list[int]
    masters: set[int]
    joints: list[int]  # members' ends, supports, diaphragm masters: the joints tabled
    members: list[tuple[str, list[tuple[Any, bool]], np.ndarray]]  # name, chain, member axes


_models: dict[str, tuple[Any, _Model]] = {}


def _model(project_path: str | Path) -> _Model:
    """The model's tables view, worked out once while its files stay the same."""
    path = Path(project_path).resolve()
    plan = path.parent.parent / "05 Floor Plan" / "floor-plan.json"
    stamp = tuple(p.stat().st_mtime if p.exists() else None for p in (path, plan))
    found = _models.get(str(path))
    if found is None or found[0] != stamp:
        _models.clear()  # one model at a time
        found = _models[str(path)] = (stamp, _work_out_model(path))
    return found[1]


def _work_out_model(project_path: Path) -> _Model:
    from saengine.fem.derive import member_axes
    from saengine.fem.display import _elements, _load
    from saengine.fem.member_detail import _chain

    project = _load(project_path)
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    masters = {
        int(c["retained_node"])
        for c in project.get("mp_constraints", [])
        if c.get("retained_node") is not None
    }
    supports = sorted(
        n["id"]
        for n in project.get("nodes", [])
        if any(n.get("restraint") or []) and n["id"] not in masters
    )
    by_member: dict[str, list[Any]] = {}
    for element in _elements(project):
        if not _is_link(element.name):
            by_member.setdefault(_member(element.name), []).append(element)
    members = []
    joints = set(supports) | masters
    for name, pieces in by_member.items():
        chain = _chain(pieces)
        first, last = chain[0], chain[-1]
        a = coords[first[0].j if first[1] else first[0].i]
        b = coords[last[0].i if last[1] else last[0].j]
        if (b[2] - a[2] < -1e-6) or (abs(b[2] - a[2]) <= 1e-6 and tuple(b[:2]) < tuple(a[:2])):
            chain = [(e, not back) for e, back in reversed(chain)]
        axes = member_axes(chain[0][0].axes)
        if chain[0][1]:
            axes = np.array([-axes[0], axes[1], -axes[2]])
        members.append((name, chain, axes))
        joints.add(chain[0][0].j if chain[0][1] else chain[0][0].i)
        joints.add(chain[-1][0].i if chain[-1][1] else chain[-1][0].j)
    members.sort(key=lambda m: _natural(m[0]))
    return _Model(
        project=project,
        names=_Names.of(project_path, project),
        coords=coords,
        supports=supports,
        masters=masters,
        joints=sorted(j for j in joints if j in coords),
        members=members,
    )


def _natural(text: str) -> list[Any]:
    import re

    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


def _point(model: _Model, node: int) -> str:
    name = model.names.point(model.coords[node])
    return f"{name} (diaphragm)" if node in model.masters else name


def _member_rows(
    model: _Model, ends: dict[int, np.ndarray], loads: dict[int, np.ndarray] | None = None
) -> list[list[Any]]:
    """Per member its section forces at the stations along it (the ends of its pieces): Member,
    Station [m], P V2 V3 [kN], T M2 M3 [kN·m] in the member axes, tension positive. ``ends``:
    each element's 12 end forces (``localForce``); ``loads``: its uniform local loads (the
    stations are the pieces' ends, so they only matter for the forces at them, not at all)."""
    rows: list[list[Any]] = []
    for name, chain, axes in model.members:
        offset = 0.0
        for k, (element, backwards) in enumerate(chain):
            end = ends.get(element.id)
            if end is None:
                offset += element.length
                continue
            # The section forces at the piece's i and j ends (fem.display convention).
            at_i, at_j = -np.asarray(end[:6], dtype=float), np.asarray(end[6:12], dtype=float)
            first, second = (at_j, at_i) if backwards else (at_i, at_j)
            turn = axes @ element.axes.T
            sign = -1.0 if backwards else 1.0
            for station, f in ((offset, first), (offset + element.length, second)):
                if k and station == offset and f is first:
                    continue  # the joint between two pieces is tabled once
                local = sign * np.concatenate([turn @ f[:3], turn @ f[3:6]]) * _KN
                rows.append(
                    [name, round(station, STATION_DECIMALS), *_rounded(local, FORCE_DECIMALS)]
                )
            offset += element.length
    return rows


_MEMBER_COLUMNS = [
    "Member",
    "Station [m]",
    "P [kN]",
    "V2 [kN]",
    "V3 [kN]",
    "T [kN·m]",
    "M2 [kN·m]",
    "M3 [kN·m]",
]
_MEMBER_NOTE = (
    "Section forces at the ends of each member's analysis pieces, from its start (a column's "
    "bottom), in the member axes: 1 along it, 2 up for a beam (V2 and M3: gravity shear and "
    "bending, M3 positive sagging), 3 = 1 × 2; tension positive."
)
_DISP_COLUMNS = ["Point", "Ux [mm]", "Uy [mm]", "Uz [mm]", "Rx [rad]", "Ry [rad]", "Rz [rad]"]
_REACTION_COLUMNS = [
    "Support",
    "Fx [kN]",
    "Fy [kN]",
    "Fz [kN]",
    "Mx [kN·m]",
    "My [kN·m]",
    "Mz [kN·m]",
]


def _disp_rows(model: _Model, disp: dict[int, np.ndarray]) -> list[list[Any]]:
    rows = []
    for node in model.joints:
        d = disp.get(node, np.zeros(6))
        rows.append(
            [
                _point(model, node),
                *_rounded(np.asarray(d[:3]) * _MM, LENGTH_DECIMALS),
                *_rounded(d[3:6], ROTATION_DECIMALS),
            ]
        )
    return rows


def _reaction_rows(model: _Model, react: dict[int, np.ndarray]) -> list[list[Any]]:
    rows, total = [], np.zeros(6)
    for node in model.supports:
        r = np.asarray(react.get(node, np.zeros(6)), dtype=float)[:6]
        total = total + r
        rows.append([_point(model, node), *_rounded(r * _KN, FORCE_DECIMALS)])
    rows.append(["Total", *_rounded(total * _KN, FORCE_DECIMALS)])
    return rows


def _last(group: dict[int, Any], key: int, width: int) -> np.ndarray:
    value = np.zeros(width)
    rows = group.get(key)
    if rows is not None and len(rows):
        row = np.asarray(rows[-1], dtype=float)[:width]
        value[: len(row)] = row
    return value


def _parts(out_dir: str | Path, project_path: str | Path, key: str) -> tuple[str, list[Any]]:
    """The label and the ``(factor, results, case code)`` a case or combination sums."""
    from saengine.fem.display import _code, _manifest
    from saengine.fem.story_response import load_cached

    manifest = _manifest(out_dir)
    if manifest is None:
        raise ValueError("there are no results; run the analysis first")
    entries = {f"case:{e['case_id']}": e for e in manifest["cases"]}
    if key in entries:
        entry = entries[key]
        return entry["case_name"], [(1.0, load_cached(entry, out_dir), _code(entry["case_name"]))]
    from saengine.fem.combinations import combination_factors, settings_beside

    settings = settings_beside(project_path)
    number = int(key.split(":")[1])
    if settings is None or not 1 <= number <= len(settings.combinations):
        raise ValueError(f"unknown combination {number}")
    combination = settings.combinations[number - 1]
    by_code = {
        _code(e["case_name"]): e for e in manifest["cases"] if e["result_type"] == "StaticResults"
    }
    from saengine.fem.combinations import combination_label

    label = combination_label(combination, set(by_code))
    parts = []
    for code, factor in combination_factors(combination, set(by_code)).items():
        if code not in by_code:
            raise ValueError(f"{combination.name}: case {code} has no results")
        parts.append((factor, load_cached(by_code[code], out_dir), code))
    return label, parts


def _summed(parts: list[Any], group: str, ids: list[int], width: int, thermal: Any = None):
    from saengine.fem.thermal import end_force_corrections

    out = {}
    added = {code: end_force_corrections(thermal, code) for _, _, code in parts}
    for item in ids:
        total = np.zeros(width)
        for factor, results, code in parts:
            value = _last(getattr(results, group), item, width)
            if group == "element_forces":
                value = value + added[code].get(item, 0.0)
            total += factor * value
        out[item] = total
    return out


def result_table(
    out_dir: str | Path, project_path: str | Path, key: str, table: str
) -> dict[str, Any]:
    """One table (an id of :func:`table_index`) of one result: ``{"name", "title", "columns",
    "rows", "notes"}``."""
    if key.startswith("case:") and ":" in table:
        return _studio_table(out_dir, project_path, key, table)
    if key == "envelope":
        return _envelope(out_dir, project_path)
    if key.startswith("spectrum:"):
        return _spectrum_table(out_dir, project_path, int(key.split(":")[1]), table)
    from saengine.fem.thermal import load_corrections

    label, parts = _parts(out_dir, project_path, key)
    model = _model(project_path)
    if table == DISPLACEMENTS[0]:
        disp = _summed(parts, "node_disp", model.joints, 6)
        return _table(
            DISPLACEMENTS[1],
            f"{DISPLACEMENTS[1]}: {label}",
            _DISP_COLUMNS,
            _disp_rows(model, disp),
            ["The members' ends, the supports and the diaphragms' centres; global axes."],
        )
    if table == REACTIONS[0]:
        react = _summed(parts, "node_reaction", model.supports, 6)
        return _table(
            REACTIONS[1],
            f"{REACTIONS[1]}: {label}",
            _REACTION_COLUMNS,
            _reaction_rows(model, react),
        )
    if table == MEMBER_FORCES[0]:
        ids = [e.id for _, chain, _ in model.members for e, _ in chain]
        thermal = load_corrections(project_path)
        ends = _summed(parts, "element_forces", ids, 12, thermal)
        return _table(
            MEMBER_FORCES[1],
            f"{MEMBER_FORCES[1]}: {label}",
            _MEMBER_COLUMNS,
            _member_rows(model, ends),
            [_MEMBER_NOTE],
        )
    if table in (BUCKLING[0], EFFECTIVE_LENGTHS[0]):
        return _buckling_table(project_path, key, label, parts, model, table)
    raise ValueError(f"{label} has no table {table}")


# ─────────────────────────────────────── buckling ───────────────────────────────────────

_buckling_cache: dict[tuple[str, Any, str], Any] = {}

_BUCKLING_NOTE = (
    "Linear (eigen) buckling of the frame under the axial forces of this combination: λ is the "
    "factor on its loads at which the frame buckles (below 1: unstable under them). Frames, "
    "trusses, pinned-end links, supports and diaphragms are in the buckling model; walls, slabs "
    "(other than through the rigid diaphragms) and solids are not, so a building held by walls "
    "gets lower, conservative, factors. Second-order design still follows BNBC 2020 Part 6 Sec "
    "6.3.10 and Chapter 10."
)
_EFFECTIVE_NOTE = (
    "K = (π / L) √(E I / Pcr) with Pcr = λ1 |P|, the member's largest compression P at the "
    "first critical factor λ1, about the section's strong and weak axes (BNBC 2020 Part 6 Sec "
    "10.5, KL/r; the frame-buckling K of AISC 360-05, which BNBC 2020 Part 6 Chapter 10 "
    "adopts). Meaningful for the members that take part in mode 1; above 10 it is not shown. "
    "The design checks keep their own effective lengths."
)


def _buckling(project_path: str | Path, key: str, parts: list[Any], model: _Model) -> Any:
    """The buckling result of a combination, computed once while the model stays the same."""
    from saengine.fem.buckling import linear_buckling
    from saengine.fem.thermal import load_corrections

    path = Path(project_path).resolve()
    cache_key = (str(path), path.stat().st_mtime, key)
    found = _buckling_cache.get(cache_key)
    if found is None:
        ids = [e.id for _, chain, _ in model.members for e, _ in chain]
        ends = _summed(parts, "element_forces", ids, 12, load_corrections(project_path))
        # Axial force, tension positive: the mean of the two ends (fem.display convention).
        axial = {i: float((-end[0] + end[6]) / 2) for i, end in ends.items()}
        _buckling_cache.clear()  # one at a time: it holds mode shapes
        found = _buckling_cache[cache_key] = linear_buckling(model.project, axial)
    return found


def _buckling_table(
    project_path: str | Path,
    key: str,
    label: str,
    parts: list[Any],
    model: _Model,
    table: str,
) -> dict[str, Any]:
    from saengine.fem.buckling import BucklingError, member_effective_lengths, mode_shares

    try:
        result = _buckling(project_path, key, parts, model)
    except BucklingError as error:
        title = BUCKLING[1] if table == BUCKLING[0] else EFFECTIVE_LENGTHS[1]
        return _table(title, f"{title}: {label}", ["Note"], [[str(error)]], [_BUCKLING_NOTE])
    skipped = ", ".join(f"{n} {kind}" for kind, n in sorted(result.skipped.items()))
    notes = [_BUCKLING_NOTE] + ([f"Not in the buckling model: {skipped}."] if skipped else [])
    if table == BUCKLING[0]:
        rows = []
        for number, (factor, shape) in enumerate(zip(result.factors, result.modes, strict=True), 1):
            shares = mode_shares(shape)
            peak = max(shape, key=lambda n: float(np.linalg.norm(shape[n][:3])), default=None)
            rows.append(
                [
                    number,
                    round(factor, 3),
                    *(round(100 * v, 1) for v in shares),
                    _point(model, peak) if peak in model.coords else "",
                ]
            )
        return _table(
            BUCKLING[1],
            f"{BUCKLING[1]}: {label}",
            ["Mode", "λ", "X [%]", "Y [%]", "Z [%]", "Largest at"],
            rows,
            notes + ["X, Y, Z: shares of the mode's translations along the global axes."],
        )
    members = [(name, [e.id for e, _ in chain]) for name, chain, _ in model.members]
    rows = [
        [
            row["member"],
            round(row["length"], STATION_DECIMALS),
            round(-row["N"] * _KN, FORCE_DECIMALS),
            round(row["Pcr"] * _KN, FORCE_DECIMALS),
            None if row["Kmajor"] is None else round(row["Kmajor"], 2),
            None if row["Kminor"] is None else round(row["Kminor"], 2),
        ]
        for row in member_effective_lengths(result, members)
    ]
    first = result.factors[0] if result.factors else None
    return _table(
        EFFECTIVE_LENGTHS[1],
        f"{EFFECTIVE_LENGTHS[1]}: {label}" + (f" (λ1 = {first:.3f})" if first is not None else ""),
        ["Member", "L [m]", "P [kN]", "Pcr [kN]", "K major", "K minor"],
        rows,
        [_EFFECTIVE_NOTE, *notes[1:]],
    )


def _studio_table(
    out_dir: str | Path, project_path: str | Path, key: str, table: str
) -> dict[str, Any]:
    """A table of OpenSees Studio's (modal periods, spectrum, time history, pushover, static
    history, and the tables of a model SAEngine did not derive), in model units."""
    from opensees_studio.services.persistence import load_project

    from saengine.fem.display import _manifest
    from saengine.fem.story_response import load_cached
    from saengine.rpc.handlers import _tables_for

    manifest = _manifest(out_dir)
    entry = next(
        (e for e in (manifest or {}).get("cases", []) if f"case:{e['case_id']}" == key), None
    )
    if entry is None:
        raise ValueError(f"unknown result {key}")
    project = load_project(str(project_path))
    tables = _tables_for(load_cached(entry, out_dir), project)
    index = int(table.split(":")[1])
    if table.startswith("static:") and index == 3:
        index = len(tables) - 1  # the history follows the three tables
    if not 0 <= index < len(tables):
        raise ValueError(f"{entry['case_name']} has no table {table}")
    return tables[index]


def _envelope(out_dir: str | Path, project_path: str | Path) -> dict[str, Any]:
    """Each member station's least and largest forces over the combinations formed."""
    from saengine.fem.combinations import combination_factors, settings_beside
    from saengine.fem.display import _code, _manifest
    from saengine.fem.story_response import load_cached
    from saengine.fem.thermal import load_corrections

    manifest = _manifest(out_dir) or {"cases": []}
    settings = settings_beside(project_path)
    model = _model(project_path)
    ids = [e.id for _, chain, _ in model.members for e, _ in chain]
    thermal = load_corrections(project_path)
    by_code = {
        _code(e["case_name"]): e for e in manifest["cases"] if e["result_type"] == "StaticResults"
    }
    rows_of: dict[str, np.ndarray] = {}  # case code: member rows' values (rows, 6)
    labels: list[list[Any]] | None = None

    def case_rows(code: str) -> np.ndarray:
        nonlocal labels
        if code not in rows_of:
            results = load_cached(by_code[code], out_dir)
            ends = _summed([(1.0, results, code)], "element_forces", ids, 12, thermal)
            rows = _member_rows(model, ends)
            labels = labels or [r[:2] for r in rows]
            rows_of[code] = np.array([r[2:] for r in rows], dtype=float)
        return rows_of[code]

    low = high = None
    used = []
    for combination in settings.combinations if settings else []:
        factors = combination_factors(combination, set(by_code))
        if not factors or any(c not in by_code for c in factors):
            continue
        value = sum(f * case_rows(c) for c, f in factors.items())
        low = value if low is None else np.minimum(low, value)
        high = value if high is None else np.maximum(high, value)
        used.append(combination.name)
    rows = []
    if low is not None and labels is not None:
        for k, label in enumerate(labels):
            rows.append(
                [*label, *_rounded(low[k], FORCE_DECIMALS), *_rounded(high[k], FORCE_DECIMALS)]
            )
    forces = _MEMBER_COLUMNS[2:]
    return _table(
        ENVELOPE[1],
        ENVELOPE[1],
        ["Member", "Station [m]", *(f"{c} min" for c in forces), *(f"{c} max" for c in forces)],
        rows,
        [f"Over {len(used)} combinations of the project settings.", _MEMBER_NOTE],
    )


def _spectrum_table(
    out_dir: str | Path, project_path: str | Path, number: int, table: str
) -> dict[str, Any]:
    """A response spectrum design combination's member forces or reactions, S − E and S + E."""
    from saengine.fem.combinations import DesignCombination, evaluate, settings_beside
    from saengine.fem.display import _code, _manifest
    from saengine.fem.seismic_design import load_seismic_forces
    from saengine.fem.story_response import load_cached

    seismic = _seismic(out_dir, settings_beside(project_path))
    combos = (seismic or {}).get("combinations", [])
    forces = load_seismic_forces(out_dir)
    if not 1 <= number <= len(combos) or forces is None:
        raise ValueError(f"there is no response spectrum design combination {number}")
    manifest = _manifest(out_dir) or {"cases": []}
    by_code = {
        _code(e["case_name"]): e for e in manifest["cases"] if e["result_type"] == "StaticResults"
    }
    combination = DesignCombination.from_json(combos[number - 1], set(by_code))
    cases = {c: load_cached(by_code[c], out_dir) for c in combination.factors if c in by_code}
    if len(cases) < len(combination.factors):
        raise ValueError(f"{combination.name}: a case has no results")
    model = _model(project_path)
    notes = [combination.clause] if combination.clause else []
    if table == REACTIONS[0]:
        rows = []
        for node in model.supports:
            s, env = evaluate(
                combination,
                {c: _last(r.node_reaction, node, 6) for c, r in cases.items()},
                forces.reaction(node),
            )
            rows.append(
                [
                    _point(model, node),
                    *_rounded((s - env) * _KN, FORCE_DECIMALS),
                    *_rounded((s + env) * _KN, FORCE_DECIMALS),
                ]
            )
        columns = _REACTION_COLUMNS[1:]
        return _table(
            REACTIONS[1],
            f"{REACTIONS[1]}, S − E and S + E: {combination.name}",
            ["Support", *(f"{c} min" for c in columns), *(f"{c} max" for c in columns)],
            rows,
            notes,
        )
    ids = [e.id for _, chain, _ in model.members for e, _ in chain]
    low, high = {}, {}
    for element in ids:
        s, env = evaluate(
            combination,
            {c: _last(r.element_forces, element, 12) for c, r in cases.items()},
            forces.end_forces(element),
        )
        low[element], high[element] = s - env, s + env
    # The end forces turn to section forces with a sign at the i ends: the least and largest
    # values are taken after.
    lows, highs = _member_rows(model, low), _member_rows(model, high)
    rows = []
    for a, b in zip(lows, highs, strict=True):
        pairs = list(zip(a[2:], b[2:], strict=True))
        rows.append([*a[:2], *(min(p) for p in pairs), *(max(p) for p in pairs)])
    columns = _MEMBER_COLUMNS[2:]
    return _table(
        MEMBER_FORCES[1],
        f"{MEMBER_FORCES[1]}, S − E and S + E: {combination.name}",
        ["Member", "Station [m]", *(f"{c} min" for c in columns), *(f"{c} max" for c in columns)],
        rows,
        [*notes, _MEMBER_NOTE],
    )


# ─────────────────────────────── Excel export ───────────────────────────────

_export_lock = threading.Lock()
_progress: dict[str, Any] = {"running": False, "done": 0, "total": 0, "message": ""}
_cancel = threading.Event()


class ExportCancelled(Exception):
    """The engineer stopped the export: nothing was written at the path."""


def export_progress() -> dict[str, Any]:
    """``{"running", "done", "total", "message"}`` of the export under way (or the last)."""
    return dict(_progress)


def cancel_export() -> dict[str, Any]:
    """Stops the export under way after the table it is writing; its file is not written."""
    _cancel.set()
    return {"cancelled": bool(_progress.get("running"))}


def export_xlsx(
    out_dir: str | Path,
    project_path: str | Path,
    path: str | Path,
    keys: list[str] | None = None,
    tables: list[str] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Writes the tables ``tables`` (ids of :func:`table_index`; all when None) of the results
    ``keys`` (all when None) to the workbook ``path``, one sheet per kind of table with the
    result in its first column, then the ``extra`` sheets (``{"name", "columns", "rows",
    "notes"?}``: the summary the view works out). Streamed to a temporary file beside ``path``,
    renamed over it at the end: a stopped or failed export leaves no half-written workbook.
    ``{"path", "sheets", "rows"}``."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font

    from saengine.fem.table_export import sheet_name

    target = Path(path)
    if target.suffix.lower() != ".xlsx":
        raise ValueError(f"{target.name}: an Excel workbook must end in .xlsx")
    if not _export_lock.acquire(blocking=False):
        raise ValueError("an export is already under way")
    try:
        _cancel.clear()
        index = table_index(out_dir, project_path)["results"]
        chosen = [r for r in index if keys is None or r["key"] in keys]
        work = [
            (r, t)
            for r in chosen
            for t in r["tables"]
            if tables is None or t["id"] in tables or t["title"] in tables
        ]
        _progress.update(running=True, done=0, total=len(work), message="")
        book = Workbook(write_only=True)
        taken: set[str] = set()
        # The sheets in the order first met, written to as the tables are worked out (a write
        # only workbook keeps each sheet's rows in its own temporary file, not in memory).
        sheets: dict[str, tuple[Any, list[str]]] = {}
        count = 0

        def open_sheet(name: str, columns: list[str], sample: list[Any]) -> Any:
            sheet = book.create_sheet(sheet_name(name, taken))
            for k, title in enumerate(columns):
                width = max([len(title), *(len(str(r[k])) for r in sample[:200] if len(r) > k)])
                sheet.column_dimensions[_column_letter(k + 1)].width = min(40, width + 2)
            sheet.freeze_panes = "A2"
            heading = []
            for title in columns:
                cell = WriteOnlyCell(sheet, value=title)
                cell.font = Font(bold=True)
                heading.append(cell)
            sheet.append(heading)
            return sheet

        def plain(row: list[Any]) -> list[Any]:
            return [c if isinstance(c, (int, float)) else str(c) for c in row]

        try:
            for done, (result, wanted) in enumerate(work):
                if _cancel.is_set():
                    raise ExportCancelled("the export was stopped")
                _progress.update(done=done, message=f"{result['label']}: {wanted['title']}")
                table = result_table(out_dir, project_path, result["key"], wanted["id"])
                group = result["group"]
                kind = (
                    f"{group if group not in ('case', 'combination') else ''}|{wanted['id']}|"
                    + ("|".join(map(str, table["columns"])))
                )
                if kind not in sheets:
                    name = table["name"] + (" (spectrum design)" if group == "spectrum" else "")
                    rows = [[result["label"], *r] for r in table["rows"][:200]]
                    sheets[kind] = (open_sheet(name, ["Result", *table["columns"]], rows), [])
                sheet, notes = sheets[kind]
                for row in table["rows"]:
                    sheet.append(plain([result["label"], *row]))
                    count += 1
                notes += [n for n in table["notes"] if n not in notes]
            _progress.update(done=len(work), message="writing the workbook")
            for sheet, notes in sheets.values():
                if notes:
                    sheet.append([])
                    for note in notes:
                        sheet.append([str(note)])
            for table in extra or []:
                columns = [str(c) for c in table.get("columns", [])]
                rows = table.get("rows", [])
                sheet = open_sheet(str(table.get("name", "")), columns, rows)
                for row in rows:
                    sheet.append(plain(row))
                    count += 1
                if table.get("notes"):
                    sheet.append([])
                    for note in table["notes"]:
                        sheet.append([str(note)])
        except BaseException:
            # Stopped or failed: the sheets' temporary files are closed (nothing is saved).
            for sheet, _ in sheets.values():
                sheet.close()
            raise
        if not sheets and not extra:
            book.create_sheet("Results").append(["No tables were chosen."])
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.stem}.{os.getpid()}.partial.xlsx")
        try:
            book.save(temporary)
            if _cancel.is_set():
                raise ExportCancelled("the export was stopped")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return {"path": str(target), "sheets": len(sheets) + len(extra or []), "rows": count}
    finally:
        _progress.update(running=False)
        _export_lock.release()


def _column_letter(number: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(number)
