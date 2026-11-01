"""The linear time histories in design (B19): suites, the base shear scaling, the drifts and the
member envelopes of the linear response history procedure.

The analysis model runs each time history as a Transient case after the dead loads
(:mod:`saengine.fem.derive`; a pair of components as one case, both directions at once). This
module reads those results and, with the rules of the code pack in force
(:mod:`saengine.fem.records`), works out what the design uses:

- **Suites.** The cases form a suite per direction (one excitation, X or Y) and one of pairs
  (both directions at once: a three-dimensional analysis, the orthogonal effects of the
  simultaneous components, BNBC 2020 Part 6 Sec 2.5.13.1(c)). A suite is used in design when
  it has the pack's least number of records and every case ran to its end.
- **Spectrum check.** Each suite is checked again with the fundamental period of the modal
  analysis (the model scales the records with the period it knows when it is made, the
  approximate Ta unless one is given): where the mean spectrum falls short of the criterion
  the suite's responses are multiplied by the shortfall (the analysis is linear, so this is
  the response to the records scaled up by it).
- **Peaks.** Per case: the base and storey shears from the inertia forces m·(ü + üg) of the
  nodes above a cut (the reactions are not recorded; with stiffness-proportional damping only
  they balance them exactly), each storey's drift (the largest over the plan positions with a
  node at both levels of the peak of Δu(t)), each node's peak displacement and each frame
  element's peak end and section forces, all measured from the state under the dead loads.
- **Design value** (Sec 2.5.10.3): the largest of the cases' peaks below the pack's
  ``meanFrom`` records (or pairs), their mean from it; then times max(1, V/Vth), V the
  equivalent static base shear of the direction and Vth the suite's design base shear (a pair
  takes the larger factor of its two directions); drifts too (``scaleDrifts``), then times
  Cd/I (Sec 2.5.7.7) against the allowable storey drift.
- **Envelope parts** for the design combinations: ``HX``, ``HY`` (two-dimensional suites) or
  ``H`` (pairs), in place of ``RX``, ``RY`` of the response spectrum
  (:func:`history_combinations`). The frames take the time-history forces themselves; the
  shells (walls, slabs) and the supports, whose stress resultants and reactions the time
  history does not record, take the scaled response spectrum envelope times the ratio of the
  suite's design base shear to the response spectrum's (pairs: 100 % of one direction with
  the pack's orthogonal share of the other): a stated approximation.

Units follow the model: m, N, N·m (summaries in kN, m).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem import records as rec

#: Folder of the cached peaks inside the analysis results folder.
FOLDER = "th-design"
#: The envelope part of each suite.
PART_OF = {"X": "HX", "Y": "HY", "XY": "H"}
#: Bump when the cached peaks change meaning.
_VERSION = "1"


# ─────────────────────────────────────── cases ───────────────────────────────────────


def transient_cases(project: dict[str, Any]) -> list[dict[str, Any]]:
    """The model's time-history cases: ``[{"id", "name", "suite", "excitations": [(direction,
    series id)]}]``, suite "X", "Y" or "XY" from the directions of its uniform excitations."""
    patterns = {int(p["id"]): p for p in project.get("load_patterns", [])}
    out = []
    for case in project.get("analyses", []):
        if case.get("type") != "Transient":
            continue
        shaking = [
            patterns[int(p)]
            for p in case.get("pattern_ids", [])
            if patterns.get(int(p), {}).get("type") == "UniformExcitation"
        ]
        directions = sorted({int(p.get("direction", 0)) for p in shaking})
        suite = (
            "XY"
            if directions == [1, 2]
            else {1: "X", 2: "Y"}.get(directions[0])
            if len(directions) == 1
            else None
        )
        if suite is None:
            continue
        out.append(
            {
                "id": int(case["id"]),
                "name": str(case.get("name", "")),
                "suite": suite,
                "excitations": [(int(p["direction"]), int(p["accel_series_id"])) for p in shaking],
            }
        )
    return out


# ─────────────────────────────────────── peaks ───────────────────────────────────────


def _positions(project: dict[str, Any], levels: list[float]) -> list[dict[tuple[int, int], int]]:
    from saengine.fem.seismic_design import _positions as positions

    return positions(project, levels)


def record_peaks(
    project: dict[str, Any],
    model_dir: str | Path,
    h5_path: str | Path,
    case: dict[str, Any],
    levels: list[float],
) -> dict[str, np.ndarray]:
    """The peaks of one time-history case (see the module doc): ``{"base": [Vx, Vy] N,
    "heights": levels with mass [m], "shears": peak storey shear above each height [N, (n,
    2)], "drift": per storey [X, Y] m (rows of ``levels[1:]``), "nodes", "nodePeaks": (n, 6),
    "elements", "ends": (n, 12), "stations": (n, STATIONS, 6)}``."""
    import h5py

    from saengine.fem.display import STATIONS, _elements, element_section_forces_many

    nodes = {int(n["id"]): n for n in project.get("nodes", [])}
    with h5py.File(h5_path, "r") as f:
        times = np.asarray(f["time"][:], dtype=float)
        steps = len(times)
        ground = np.zeros((steps, 2))
        for direction, series in case["excitations"]:
            found = rec.ground_acceleration(project, model_dir, series)
            if found is None:
                continue
            dt, values = found
            ground[:, direction - 1] += np.interp(
                times, dt * np.arange(len(values)), values, right=0.0
            )
        # Inertia forces by height, the peaks of each node's displacement.
        by_height: dict[float, np.ndarray] = {}
        node_ids = sorted(nodes)
        node_peaks = np.zeros((len(node_ids), 6))
        at_level = _positions(project, levels)
        wanted = {n for level in at_level for n in level.values()}
        lateral: dict[int, np.ndarray] = {}
        for k, node_id in enumerate(node_ids):
            key = f"nodes/{node_id}/disp"
            if key not in f:
                continue
            disp = np.asarray(f[key][:], dtype=float)
            if disp.ndim != 2 or not len(disp):
                continue
            moved = disp - disp[0]
            width = min(6, moved.shape[1])
            node_peaks[k, :width] = np.abs(moved[:, :width]).max(axis=0)
            if node_id in wanted:
                lateral[node_id] = moved[:, :2]
            mass = np.asarray(nodes[node_id].get("mass") or [0.0] * 6, dtype=float)
            if mass.size < 2 or not np.any(mass[:2]):
                continue
            accel_key = f"nodes/{node_id}/accel"
            if accel_key not in f:
                continue
            accel = np.asarray(f[accel_key][:], dtype=float)[:, :2]
            z = round(float(nodes[node_id]["coords"][2]), 3)
            force = mass[:2] * (accel + ground[: len(accel)])
            by_height[z] = by_height.get(z, np.zeros((steps, 2))) + force
        heights = sorted(by_height)
        shears = np.zeros((len(heights), 2))
        running = np.zeros((steps, 2))
        for k in range(len(heights) - 1, -1, -1):
            running = running + by_height[heights[k]]
            shears[k] = np.abs(running).max(axis=0)
        base = shears[0] if len(heights) else np.zeros(2)
        # Storey drifts: the largest over the plan positions of the peak of Δu(t).
        drift = np.zeros((max(len(levels) - 1, 0), 2))
        for k in range(1, len(levels)):
            for position, top in at_level[k].items():
                bottom = at_level[k - 1].get(position)
                if bottom is None or top not in lateral or bottom not in lateral:
                    continue
                peak = np.abs(lateral[top] - lateral[bottom]).max(axis=0)
                drift[k - 1] = np.maximum(drift[k - 1], peak)
        # Frame elements: the peaks of their end and section forces.
        frames = _elements(project)
        element_ids, ends, stations = [], [], []
        for element in frames:
            key = f"elements/{element.id}/forces"
            if key not in f:
                continue
            forces = np.asarray(f[key][:], dtype=float)
            if forces.ndim != 2 or forces.shape[1] != 12 or not len(forces):
                continue
            moved = forces - forces[0]
            element_ids.append(element.id)
            ends.append(np.abs(moved).max(axis=0))
            sections = element_section_forces_many(
                np.full(len(moved), float(element.length)), moved, np.zeros((len(moved), 3))
            )
            stations.append(np.abs(sections).max(axis=0))
    return {
        "base": np.asarray(base, dtype=float),
        "heights": np.asarray(heights, dtype=float),
        "shears": shears,
        "drift": drift,
        "nodes": np.asarray(node_ids, dtype=int),
        "nodePeaks": node_peaks,
        "elements": np.asarray(element_ids, dtype=int),
        "ends": np.asarray(ends, dtype=float).reshape(-1, 12),
        "stations": np.asarray(stations, dtype=float).reshape(-1, STATIONS, 6),
    }


def _cache_key(h5_path: Path, project: dict[str, Any], levels: list[float]) -> str:
    stat = h5_path.stat()
    text = json.dumps(
        [_VERSION, str(h5_path.name), stat.st_size, stat.st_mtime_ns, levels], sort_keys=True
    )
    model = json.dumps(
        {k: project.get(k) for k in ("nodes", "elements", "time_series", "ground_motions")},
        sort_keys=True,
    )
    return hashlib.sha1((text + model).encode()).hexdigest()


def cached_peaks(
    out_dir: str | Path,
    project: dict[str, Any],
    model_dir: str | Path,
    entry: dict[str, Any],
    case: dict[str, Any],
    levels: list[float],
) -> dict[str, np.ndarray]:
    """:func:`record_peaks` of a manifest ``entry``, kept in ``<out_dir>/th-design`` while its
    results and the model do not change."""
    out_dir = Path(out_dir)
    h5 = out_dir / entry["files"][0]
    key = _cache_key(h5, project, levels)
    path = out_dir / FOLDER / f"case_{case['id']}.npz"
    try:
        with np.load(path, allow_pickle=False) as data:
            if str(data["key"]) == key:
                return {k: data[k] for k in data.files if k != "key"}
    except (OSError, ValueError, KeyError):
        pass
    peaks = record_peaks(project, model_dir, h5, case, levels)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, key=np.asarray(key), **peaks)
    except OSError:
        pass
    return peaks


# ─────────────────────────────────────── the summary ───────────────────────────────────────


def _fundamental(spectra: dict[str, dict[str, Any]], axis: str) -> float | None:
    """The period [s] of the mode with the largest effective mass in ``axis``."""
    data = spectra.get(axis)
    if not data:
        return None
    modes = [m for m in data.get("modes", []) if float(m.get("angular_frequency", 0)) > 0]
    if not modes:
        return None
    mode = max(modes, key=lambda m: float(m.get("mass_ratio", 0.0)))
    return 2 * np.pi / float(mode["angular_frequency"])


def _suite_records(
    project: dict[str, Any], model_dir: str | Path, cases: list[dict[str, Any]]
) -> tuple[list[tuple[float, np.ndarray]], list[tuple[int, int]]]:
    """The suite's ground accelerations in g (as applied, scale included) and its pairs."""
    records: list[tuple[float, np.ndarray]] = []
    pairs: list[tuple[int, int]] = []
    for case in cases:
        start = len(records)
        for _, series in sorted(case["excitations"]):
            found = rec.ground_acceleration(project, model_dir, series)
            if found is None:
                raise ValueError(f"{case['name']}: its record could not be read")
            records.append((found[0], found[1] / rec.G))
        if len(records) - start == 2:
            pairs.append((start, start + 1))
    return records, pairs


def design_summary(
    out_dir: str | Path,
    project: dict[str, Any],
    model_dir: str | Path,
    settings: Any,
    spectra: dict[str, dict[str, Any]],
    v_static: dict[str, float],
    rs_shear: dict[str, float],
    levels: list[float],
    amplification: dict[str, float],
    allowable: float,
    use: bool,
) -> dict[str, Any] | None:
    """The time-history design of an analysis run (see the module doc), or None when the model
    has no time-history case: ``{"available", "use", "suites": [{"key", "part", "cases":
    [{"id", "name", "baseShear": {"x", "y"} kN}], "count", "rule", "enough", "complete",
    "check" (:meth:`records.SuiteCheck.as_dict` or None), "vHistory" {"x", "y"} kN,
    "vStatic" {"x", "y"} kN, "factor", "used"}], "parts": {part: {"suite", "factor", "rule",
    "cases", "ratio": {"x", "y"}}}, "drift": [rows], "notes", "clauses"}``.
    ``v_static``: V by axis [N]; ``rs_shear``: the scaled response spectrum base shear by axis
    [N] (the shells' ratio); ``amplification``: Cd/I by axis; ``use``: the design asks for the
    time histories."""
    from opensees_studio.services.result_store import load_manifest

    cases = transient_cases(project)
    if not cases:
        return None
    rules = rec.rules()
    if rules is None:
        return {
            "available": False,
            "use": False,
            "notes": [
                (
                    "the code pack in force does not cover the linear response history "
                    "procedure: the time histories are shown, not designed for"
                )
            ],
        }
    notes: list[str] = []
    try:
        entries = {
            int(e["case_id"]): e
            for e in load_manifest(out_dir)["cases"]
            if e.get("result_type") == "TransientResults"
        }
    except (OSError, ValueError, KeyError):
        entries = {}
    by_suite: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_suite.setdefault(case["suite"], []).append(case)
    suites: list[dict[str, Any]] = []
    parts: dict[str, dict[str, Any]] = {}
    drift_rows: list[dict[str, Any]] = []
    for key in ("X", "Y", "XY"):
        members = by_suite.get(key)
        if not members:
            continue
        ran = [c for c in members if c["id"] in entries]
        complete = len(ran) == len(members) and not any(
            entries[c["id"]].get("early_stop") for c in ran
        )
        count = len(members)
        rule = rec.design_rule(count)
        enough = count >= rules.minimumRecords
        suite: dict[str, Any] = {
            "key": key,
            "part": PART_OF[key],
            "count": count,
            "rule": rule,
            "enough": enough,
            "complete": complete,
            "cases": [],
            "check": None,
            "used": False,
        }
        suites.append(suite)
        label = "pairs" if key == "XY" else "records"
        if not enough:
            notes.append(
                f"time-history suite {key}: {count} {label}, the code pack asks for at least "
                f"{rules.minimumRecords} ({rec.clause('records')}); not used in design"
            )
        if not complete:
            notes.append(
                f"time-history suite {key}: not every case has run to its end; run the "
                "analysis again (not used in design)"
            )
        if not ran:
            continue
        peaks = [
            cached_peaks(out_dir, project, model_dir, entries[c["id"]], c, levels) for c in ran
        ]
        # ── the spectrum check with the modal period ──
        period = (
            max(_fundamental(spectra, "X") or 0.0, _fundamental(spectra, "Y") or 0.0)
            if key == "XY"
            else _fundamental(spectra, key) or 0.0
        )
        shortfall = 1.0
        try:
            records, pairs = _suite_records(project, model_dir, ran)
            target = rec.target_spectrum(settings, key)
            check = rec.check_suite(records, target, period, pairs or None)
            suite["check"] = check.as_dict()
            shortfall = check.shortfall
            if not check.ok:
                notes.append(
                    f"time-history suite {key}: with the modal period T = {period:.3f} s its "
                    f"mean spectrum reaches {check.least:.3f} of {check.ratio:g} × the design "
                    f"spectrum at {check.governing:.3f} s ({rec.clause('records')}); its "
                    f"responses are scaled up by {shortfall:.3f} (linear analysis)"
                )
        except (OSError, ValueError, KeyError) as error:
            notes.append(f"time-history suite {key}: the spectrum check failed ({error})")
        # The suite's base shear (records scaled up by any shortfall) and the factor on the
        # recorded responses: the shortfall times max(1, V/Vth).
        raw = rec.design_value([p["base"] for p in peaks], rule)
        base = raw * shortfall
        factors = {
            axis: shortfall
            * rec.base_shear_factor(v_static.get(axis, 0.0), float(base[a]), rules.baseShearShare)
            for a, axis in enumerate("XY")
        }
        axes = ["X", "Y"] if key == "XY" else [key]
        factor = max(factors[a] for a in axes) if base.any() else shortfall
        suite.update(
            {
                "cases": [
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "baseShear": {
                            "x": float(p["base"][0]) / 1e3,
                            "y": float(p["base"][1]) / 1e3,
                        },
                    }
                    for c, p in zip(ran, peaks, strict=True)
                ],
                "shortfall": shortfall,
                "vHistory": {"x": float(base[0]) / 1e3, "y": float(base[1]) / 1e3},
                "vStatic": {"x": v_static.get("X", 0.0) / 1e3, "y": v_static.get("Y", 0.0) / 1e3},
                "factor": factor,
            }
        )
        # ── drifts (Sec 2.5.10.3 with Sec 2.5.7.7) ──
        drift = rec.design_value([p["drift"] for p in peaks], rule) if peaks else np.zeros(0)
        on_drift = factor if rules.scaleDrifts else shortfall
        for k in range(1, len(levels)):
            height = levels[k] - levels[k - 1]
            if height <= 0 or k - 1 >= len(drift):
                continue
            for a, axis in enumerate("XY"):
                if axis not in axes:
                    continue
                elastic = float(drift[k - 1][a]) * on_drift
                design = amplification.get(axis, 1.0) * elastic
                ratio = design / height
                drift_rows.append(
                    {
                        "suite": key,
                        "direction": axis,
                        "bottom": round(levels[k - 1], 3),
                        "top": round(levels[k], 3),
                        "height": round(height, 3),
                        "elasticDrift": elastic,
                        "designDrift": design,
                        "ratio": ratio,
                        "allowableRatio": allowable,
                        "ok": bool(ratio <= allowable + 1e-12),
                    }
                )
        if enough and complete:
            suite["used"] = True
            design_base = {a: float(raw[i]) * factor for i, a in enumerate("XY")}
            parts[PART_OF[key]] = {
                "suite": key,
                "factor": factor,
                "rule": rule,
                "cases": [c["id"] for c in ran],
                "ratio": {
                    a.lower(): (design_base[a] / rs_shear[a] if rs_shear.get(a) else 1.0)
                    for a in axes
                },
            }
    # Pairs (a three-dimensional analysis) govern when they are usable; else the directions.
    if "H" in parts:
        for other in ("HX", "HY"):
            if parts.pop(other, None) is not None:
                notes.append(
                    f"time-history suite {other[1]} is not used: the suite of pairs "
                    f"(three-dimensional, {rec.clause('pairs')}) is"
                )
    for suite in suites:
        suite["used"] = suite["part"] in parts
    failing = [r for r in drift_rows if not r["ok"]]
    if failing:
        worst = max(failing, key=lambda r: r["ratio"])
        notes.append(
            f"time-history storey drift {100 * worst['ratio']:.2f} % in {worst['direction']} "
            f"between {worst['bottom']:g} and {worst['top']:g} m exceeds the allowable "
            f"{100 * allowable:.2f} % ({rec.clause('drift')})"
        )
    use = bool(use and parts)
    if use:
        notes.append(
            "earthquake from the linear time histories ("
            + ", ".join(
                f"{p}: {'mean' if v['rule'] == 'mean' else 'largest'} of {len(v['cases'])}, "
                f"× {v['factor']:.3f}"
                for p, v in parts.items()
            )
            + f"; {rec.clause('response')}); walls, slabs and supports: the response spectrum "
            "envelope scaled to the time-history base shear (the time history records no shell "
            "stress resultants or reactions)"
        )
    return {
        "available": True,
        "use": use,
        "suites": suites,
        "parts": parts,
        "drift": drift_rows,
        "levels": [float(z) for z in levels],
        "notes": notes,
        "clauses": dict(rules.clauses),
    }


def history_combinations(
    combinations: list[dict[str, Any]], parts: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """The response spectrum design combinations with the time histories in place of the
    spectrum: ``RX`` → ``HX``, ``RY`` → ``HY`` where those suites are used; with the suite of
    pairs ``H`` both directions are the one part ``H`` (applied simultaneously, Sec
    2.5.13.1(c)): pass the combinations made one direction at a time (each with its own
    accidental torsion); duplicates are dropped."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for combination in combinations:
        envelope: dict[str, float] = {}
        for part, factor in combination.get("envelope", {}).items():
            target = part
            if part in ("RX", "RY"):
                if "H" in parts:
                    target = "H"
                elif f"H{part[1]}" in parts:
                    target = f"H{part[1]}"
            envelope[target] = max(envelope.get(target, 0.0), float(factor))
        if envelope == combination.get("envelope"):
            out.append(combination)
            continue
        # "TH" where the time histories give every direction, "TH+RS" where one keeps the
        # response spectrum.
        mixed = any(p in envelope for p in ("RX", "RY"))
        name = str(combination["name"]).replace("(RS ", "(TH+RS " if mixed else "(TH ")
        if "H" in parts:
            for axis in ("X", "Y"):
                torsion = f", torsion of E{axis}" if f"A{axis}" in envelope else ""
                name = name.replace(f"(TH E{axis})", f"(TH pairs{torsion})")
        key = json.dumps([combination.get("loads"), envelope], sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        clause = rec.clause("response")
        out.append(
            {
                **combination,
                "name": name,
                "envelope": envelope,
                "clause": f"{combination.get('clause', '')}; {clause}".strip("; "),
            }
        )
    return out


# ─────────────────────────────────────── the envelopes ───────────────────────────────────────


class TimeHistoryForces:
    """The response spectrum envelopes (:class:`saengine.fem.seismic_design.SeismicForces`)
    with the time-history parts of a design summary (``HX``, ``HY``, ``H``): every value a
    peak (≥ 0), scaled. Attributes and methods of the spectrum run pass through."""

    def __init__(
        self,
        base: Any,
        out_dir: str | Path,
        project: dict[str, Any],
        model_dir: str | Path,
        summary: dict[str, Any],
        levels: list[float],
        share: float = 0.3,
    ) -> None:
        self._base = base
        self._out_dir = Path(out_dir)
        self._project = project
        self._model_dir = Path(model_dir)
        self._parts = dict(summary.get("parts") or {})
        self._levels = levels
        self._share = share
        self._peaks: dict[str, list[dict[str, np.ndarray]]] | None = None
        self._index: dict[str, list[dict[str, dict[int, int]]]] = {}

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._base, name)

    @property
    def parts(self) -> list[str]:
        return [*self._base.parts, *self._parts]

    def _load(self) -> dict[str, list[dict[str, np.ndarray]]]:
        if self._peaks is None:
            from opensees_studio.services.result_store import load_manifest

            entries = {int(e["case_id"]): e for e in load_manifest(self._out_dir)["cases"]}
            cases = {c["id"]: c for c in transient_cases(self._project)}
            self._peaks = {}
            for part, spec in self._parts.items():
                found = []
                for case_id in spec["cases"]:
                    if case_id in entries and case_id in cases:
                        found.append(
                            cached_peaks(
                                self._out_dir,
                                self._project,
                                self._model_dir,
                                entries[case_id],
                                cases[case_id],
                                self._levels,
                            )
                        )
                self._peaks[part] = found
                self._index[part] = [
                    {
                        "nodes": {int(n): k for k, n in enumerate(p["nodes"])},
                        "elements": {int(e): k for k, e in enumerate(p["elements"])},
                    }
                    for p in found
                ]
        return self._peaks

    def _design(self, part: str, kind: str, item: int, values: str) -> np.ndarray | None:
        """The design value of an item's peaks over the part's cases, scaled; None when a case
        has no peaks of it."""
        peaks = self._load()[part]
        rows = []
        for p, index in zip(peaks, self._index[part], strict=True):
            k = index[kind].get(int(item))
            if k is None:
                return None
            rows.append(p[values][k])
        if not rows:
            return None
        spec = self._parts[part]
        return float(spec["factor"]) * rec.design_value(rows, spec["rule"])

    def _ratio_part(self, part: str, envelope: dict[str, np.ndarray]) -> np.ndarray | None:
        """A shell-type value of a part from the scaled response spectrum one (see the module
        doc)."""
        ratio = self._parts[part].get("ratio", {})
        if part == "H":
            a = envelope.get("RX")
            b = envelope.get("RY")
            if a is None or b is None:
                return None
            a, b = float(ratio.get("x", 1.0)) * a, float(ratio.get("y", 1.0)) * b
            return np.maximum(a + self._share * b, self._share * a + b)
        source = envelope.get(f"R{part[1]}")
        return None if source is None else float(ratio.get(part[1].lower(), 1.0)) * source

    def derived_parts(self, envelope: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        """The time-history parts of a value known only from the spectrum run (a wall cut, a
        shell, a support) from its scaled response spectrum ``envelope`` by part."""
        out = {}
        for part in self._parts:
            value = self._ratio_part(part, envelope)
            if value is not None:
                out[part] = value
        return out

    def _with(
        self, envelope: dict[str, np.ndarray], kind: str, item: int, values: str
    ) -> dict[str, np.ndarray]:
        out = dict(envelope)
        for part in self._parts:
            value = self._design(part, kind, item, values) if kind else None
            if value is None:
                value = self._ratio_part(part, envelope)
            if value is not None:
                out[part] = value
        return out

    def frame(self, element: Any) -> dict[str, np.ndarray]:
        return self._with(self._base.frame(element), "elements", element.id, "stations")

    def end_forces(self, element_id: int) -> dict[str, np.ndarray]:
        return self._with(self._base.end_forces(element_id), "elements", element_id, "ends")

    def displacement(self, node_id: int) -> dict[str, np.ndarray]:
        return self._with(self._base.displacement(node_id), "nodes", node_id, "nodePeaks")

    def shell(self, element_id: int) -> dict[str, np.ndarray]:
        return self._with(self._base.shell(element_id), "", element_id, "")

    def reaction(self, node_id: int) -> dict[str, np.ndarray]:
        return self._with(self._base.reaction(node_id), "", node_id, "")

    def storey_shear(self, cut: float) -> dict[str, np.ndarray]:
        out = dict(self._base.storey_shear(cut))
        for part, spec in self._parts.items():
            rows = []
            for p in self._load()[part]:
                above = np.nonzero(p["heights"] > cut + 1e-6)[0]
                rows.append(p["shears"][above[0]] if len(above) else np.zeros(2))
            if rows:
                value = float(spec["factor"]) * rec.design_value(rows, spec["rule"])
                out[part] = np.array([value[0], value[1], 0.0])
        return out


def drift_rows(summary: dict[str, Any]) -> list[list[str]]:
    """The time-history drift of a design summary as report rows: suite, direction, storey,
    height [m], drift [mm], Cd·δ/I [mm], ratio [%], allowable [%], OK."""
    rows = []
    for d in (summary or {}).get("drift", []):
        rows.append(
            [
                d["suite"],
                d["direction"],
                f"{d['bottom']:g} to {d['top']:g} m",
                f"{d['height']:.2f}",
                f"{1e3 * d['elasticDrift']:.2f}",
                f"{1e3 * d['designDrift']:.2f}",
                f"{100 * d['ratio']:.3f}",
                f"{100 * d['allowableRatio']:.2f}",
                "OK" if d["ok"] else "FAIL",
            ]
        )
    return rows


def suite_rows(summary: dict[str, Any]) -> list[list[str]]:
    """The suites of a design summary as report rows: suite, records, design value, spectrum
    check, Vth [kN], V [kN], factor, used."""
    rows = []
    for s in (summary or {}).get("suites", []):
        check = s.get("check") or {}
        axes = ["x", "y"] if s["key"] == "XY" else [s["key"].lower()]
        rows.append(
            [
                s["key"],
                str(s["count"]),
                "mean" if s["rule"] == "mean" else "largest",
                (
                    f"{check['least']:.3f} at {check['governing']:.2f} s (T = {check['period']:.2f} s)"
                    if check
                    else "-"
                ),
                " / ".join(f"{(s.get('vHistory') or {}).get(a, 0.0):.1f}" for a in axes),
                " / ".join(f"{(s.get('vStatic') or {}).get(a, 0.0):.1f}" for a in axes),
                f"{s.get('factor', 1.0):.3f}",
                "yes" if s.get("used") else "no",
            ]
        )
    return rows
