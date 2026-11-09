"""Floor (in-structure) response spectra (alpha 9 L5), by the code pack's ``floorSpectra``
table (:class:`saengine.codes.floor_spectra_tables.FloorSpectraTable`); this module only
computes. The default pack's BNBC 2020 gives component forces by height only (Part 6 Sec
2.5.15): floor spectra are SAEngine practice there, and the results say so.

**Floors.** The levels of the run (:func:`saengine.fem.story_response.storey_levels`), or
the stories chosen in the settings (``analysis.floorSpectra.stories``); a floor's motion is
the mass-weighted mean of its nodes' (one diaphragm moves as one).

**Time history** (``timeHistory``): each time-history case's floor absolute acceleration
ü + üg in X and Y (the run records ü of every node), through damped oscillators of the
pack's periods and damping ratios (:func:`saengine.fem.spectral_matching.spectrum`, Nigam and
Jennings); over the cases their design value (the mean from the pack's ``meanFrom`` records,
else the largest; :func:`saengine.fem.records.design_value`).

**Direct, spectrum to spectrum** (``spectrumToSpectrum``): the site's elastic spectrum
(R = I = 1, at the structure's damping) as a one-sided power spectral density G(ω), iterated
until its oscillator peaks meet the spectrum (the first estimate after Vanmarcke, 1976:
G(ωn) = (Sa²/p² − ∫₀^ωn G) / (ωn (π/(4ζ) − 1))); the floor's absolute acceleration transfer
function from the modes, H(ω) = 1 + Σ Γi φi ω² / (ωi² − ω² + 2iζωiω) (the modes' correlation
and the rigid part in it); a component's oscillator Hc(ω) = (ωc² + 2iζcωcω) / (ωc² − ω² +
2iζcωcω); the peak p √(∫ |Hc|² |H|² G dω) with the Davenport peak factor p = √(2 ln ντ) +
0.5772/√(2 ln ντ), ν = √(λ2/λ0)/π, τ the pack's strong-motion duration.

**Broadening** (:func:`broaden`): Sa_b(T) = max Sa(T') for T' within T(1 ± b), b the pack's
(±15 %).

**Components** (:func:`apply_to_components`, used by
:func:`saengine.design.nonstructural.project_components` when the settings ask for it): F =
Sa(Tc) Wc Ic / Rc at the component's floor (the nearest level to its attachment), at the
pack's component damping, within the nonstructural table's least and largest force; a rigid
component (αc up to ``flexibleAlpha``) at ``rigidPeriod``, a flexible one at the spectrum's
peak (its period is not entered). The results are kept in ``08 FEM/floor-spectra.json``.

Accelerations in g, periods in s, levels in m.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

__all__ = [
    "FILE",
    "apply_to_components",
    "broaden",
    "direct_floor_spectrum",
    "evaluate",
    "floor_transfer",
    "peak_factor",
    "psd_from_spectrum",
    "report_rows",
    "table",
]

TABLE = "floorSpectra"
FILE = "floor-spectra.json"
G = 9.80665
LEVEL_TOLERANCE = 1e-3


def table(pack: Any = None) -> Any | None:
    target = pack if pack is not None else code_context.current()
    return target.table(TABLE) if target.has(TABLE) else None


def periods_of(rule: Any) -> np.ndarray:
    first, last, count = rule.periods
    return np.geomspace(float(first), float(last), int(count))


# ─────────────────────────────────────── broadening ───────────────────────────────────────


def broaden(periods: Sequence[float], sa: Sequence[float], share: float) -> np.ndarray:
    """The spectrum with its peaks widened by ± ``share`` of their period (see the module notes),
    on a fine log grid between the given periods."""
    t = np.asarray(periods, dtype=float)
    a = np.asarray(sa, dtype=float)
    if share <= 0 or len(t) < 2:
        return a.copy()
    fine = np.geomspace(t[0], t[-1], max(8 * len(t), 400))
    values = np.interp(np.log(fine), np.log(t), a)
    out = np.empty_like(a)
    for k, period in enumerate(t):
        lo, hi = period * (1 - share), period * (1 + share)
        inside = values[(fine >= lo) & (fine <= hi)]
        ends = np.interp(np.log([max(lo, t[0]), min(hi, t[-1])]), np.log(t), a)
        out[k] = max(float(inside.max()) if inside.size else 0.0, float(ends.max()))
    return out


# ─────────────────────────────────────── direct method ───────────────────────────────────────


def _trapz(y: np.ndarray, x: np.ndarray) -> float:
    return float(np.sum((y[1:] + y[:-1]) * np.diff(x)) / 2)


def peak_factor(moments: tuple[float, float, float], duration: float) -> float:
    """Davenport's peak factor of a process with spectral moments (λ0, λ1, λ2)."""
    l0, _, l2 = moments
    if l0 <= 0:
        return 0.0
    nu = math.sqrt(max(l2, 0.0) / l0) / math.pi
    n = max(nu * duration, 1.5)
    root = math.sqrt(2 * math.log(n))
    return root + 0.5772 / root


def _oscillator(omega: np.ndarray, wn: float, zeta: float) -> np.ndarray:
    """|Hc(ω)|² of an oscillator's absolute acceleration."""
    num = wn**4 + (2 * zeta * wn * omega) ** 2
    den = (wn * wn - omega * omega) ** 2 + (2 * zeta * wn * omega) ** 2
    return num / den


def _peak(omega: np.ndarray, density: np.ndarray, duration: float) -> float:
    m = tuple(_trapz(omega**k * density, omega) for k in (0, 1, 2))
    return peak_factor(m, duration) * math.sqrt(max(m[0], 0.0))


def psd_from_spectrum(
    omega: np.ndarray, sa: np.ndarray, zeta: float, duration: float, iterations: int
) -> np.ndarray:
    """The one-sided density G(ω) [g²·s/rad] whose oscillators' peaks (damping ``zeta``) are
    the spectrum ``sa`` [g] at the frequencies ``omega`` (see the module notes)."""
    g = np.zeros_like(omega)
    p0 = 2.5
    for k, w in enumerate(omega):
        done = _trapz(g[: k + 1], omega[: k + 1]) if k else 0.0
        g[k] = max(sa[k] ** 2 / p0**2 - done, 0.0) / (w * (math.pi / (4 * zeta) - 1))
    for _ in range(iterations):
        got = np.array([_peak(omega, _oscillator(omega, w, zeta) * g, duration) for w in omega])
        ratio = np.where(got > 0, sa / np.maximum(got, 1e-12), 1.0)
        g = g * ratio**2
    return g


def floor_transfer(
    omega: np.ndarray,
    omegas: Sequence[float],
    gammas_phis: Sequence[float],
    zeta: float,
) -> np.ndarray:
    """|H(ω)|² of a floor's absolute acceleration in one direction: ``gammas_phis`` the modes'
    Γi φi at the floor in that direction."""
    h = np.ones_like(omega, dtype=complex)
    for wi, gp in zip(omegas, gammas_phis, strict=True):
        h += gp * omega**2 / (wi * wi - omega**2 + 2j * zeta * wi * omega)
    return np.abs(h) ** 2


def direct_floor_spectrum(
    periods: np.ndarray,
    ground_sa: np.ndarray,
    omegas: Sequence[float],
    gammas_phis: Sequence[float],
    structure_damping: float,
    damping: float,
    duration: float,
    iterations: int,
) -> np.ndarray:
    """The floor spectrum [g] at ``periods`` and component ``damping`` by the direct method;
    ``ground_sa`` the ground spectrum at ``periods`` and the structure's damping."""
    omega = np.sort(2 * math.pi / np.asarray(periods, dtype=float))
    sa_w = np.interp(omega, 2 * math.pi / periods[::-1], ground_sa[::-1])
    density = psd_from_spectrum(omega, sa_w, structure_damping, duration, iterations)
    # A finer grid for the floor's response, the density interpolated onto it.
    fine = np.geomspace(omega[0], omega[-1] * 1.5, 1200)
    g_fine = np.interp(fine, omega, density, right=0.0)
    floor = floor_transfer(fine, omegas, gammas_phis, structure_damping) * g_fine
    out = []
    for t in periods:
        wn = 2 * math.pi / float(t)
        out.append(_peak(fine, _oscillator(fine, wn, damping) * floor, duration))
    return np.asarray(out)


# ─────────────────────────────────────── the run ───────────────────────────────────────


def _floor_nodes(project: dict[str, Any], levels: Sequence[float]) -> list[list[int]]:
    out: list[list[int]] = [[] for _ in levels]
    for node in project.get("nodes", []):
        c = node.get("coords", [])
        mass = node.get("mass") or []
        if len(c) < 3 or len(mass) < 2 or not any(mass[:2]):
            continue
        for k, z in enumerate(levels):
            if abs(float(c[2]) - z) <= LEVEL_TOLERANCE:
                out[k].append(int(node["id"]))
                break
    return out


def _modal_terms(
    project: dict[str, Any], modal: Any, floors: list[list[int]]
) -> tuple[list[float], dict[int, list[list[float]]]]:
    """(ωi of the modes, {direction 0/1: per floor the modes' Γi φi})."""
    masses = {
        int(n["id"]): np.asarray((n.get("mass") or [0.0] * 6)[:6] + [0.0] * 6, dtype=float)[:6]
        for n in project.get("nodes", [])
    }
    omegas: list[float] = []
    terms: dict[int, list[list[float]]] = {0: [[] for _ in floors], 1: [[] for _ in floors]}
    for k, period in enumerate(modal.periods, start=1):
        if not period or period <= 0:
            continue
        shape = modal.mode_shapes.get(k) or modal.mode_shapes.get(str(k)) or {}
        vectors = {int(n): np.asarray(v, dtype=float)[:6] for n, v in shape.items()}
        vectors = {n: np.pad(v, (0, 6 - len(v))) for n, v in vectors.items()}
        generalized = sum(float(masses[n] @ (v * v)) for n, v in vectors.items() if n in masses)
        if generalized <= 0:
            continue
        omegas.append(2 * math.pi / float(period))
        for d in (0, 1):
            gamma = sum(masses[n][d] * v[d] for n, v in vectors.items() if n in masses)
            gamma /= generalized
            for f, nodes in enumerate(floors):
                weights = [masses[n][d] for n in nodes if n in vectors]
                values = [vectors[n][d] for n in nodes if n in vectors]
                total = sum(weights)
                phi = (
                    sum(w * v for w, v in zip(weights, values, strict=True)) / total
                    if total
                    else 0.0
                )
                terms[d][f].append(gamma * phi)
    return omegas, terms


def _ground_spectrum(settings: Any, periods: np.ndarray, damping: float) -> np.ndarray:
    """The site's elastic spectrum [g] (R = I = 1) at ``damping``."""
    from saengine.fem import loads as fl
    from saengine.library.settings import derived

    values = derived(settings)
    if not values.get("Z"):
        raise ValueError("the site has no seismic zone coefficient")
    return np.asarray(
        [
            fl.design_acceleration(
                float(t), settings.site.siteClass, values["Z"], 1.0, 1.0, damping
            )
            for t in periods
        ]
    )


def _history_spectra(
    out_dir: Path,
    project: dict[str, Any],
    project_path: Path,
    floors: list[list[int]],
    periods: np.ndarray,
    dampings: Sequence[float],
) -> dict[tuple[int, int, float], list[np.ndarray]]:
    """{(floor, direction, damping): [spectrum per time-history case]}."""
    import h5py
    from opensees_studio.services.result_store import load_manifest

    from saengine.fem import linear_time_history as lth
    from saengine.fem import records as rec
    from saengine.fem.spectral_matching import spectrum

    cases = {int(c["id"]): c for c in lth.transient_cases(project)}
    masses = {
        int(n["id"]): float((n.get("mass") or [0.0, 0.0])[0] or 0.0)
        for n in project.get("nodes", [])
    }
    found: dict[tuple[int, int, float], list[np.ndarray]] = {}
    for entry in load_manifest(out_dir)["cases"]:
        case = cases.get(int(entry.get("case_id", -1)))
        if case is None or not entry.get("files"):
            continue
        with h5py.File(out_dir / entry["files"][0], "r") as f:
            times = np.asarray(f["time"][:], dtype=float)
            if len(times) < 3:
                continue
            dt = float(np.median(np.diff(times)))
            uniform = np.arange(times[0], times[-1] + dt / 2, dt)
            ground = np.zeros((len(times), 2))
            for direction, series in case["excitations"]:
                g = rec.ground_acceleration(project, project_path.parent, series)
                if g is not None:
                    step, values = g
                    ground[:, direction - 1] += np.interp(
                        times, step * np.arange(len(values)), values, right=0.0
                    )
            for k, nodes in enumerate(floors):
                total = np.zeros((len(times), 2))
                weight = 0.0
                for n in nodes:
                    key = f"nodes/{n}/accel"
                    if key not in f:
                        continue
                    acc = np.asarray(f[key][:], dtype=float)[:, :2]
                    w = masses.get(n, 0.0) or 1.0
                    total[: len(acc)] += w * acc
                    weight += w
                if weight <= 0:
                    continue
                absolute = (total / weight + ground) / G  # g
                for d in (0, 1):
                    series = np.interp(uniform, times, absolute[:, d])
                    if not np.any(series):
                        continue
                    for z in dampings:
                        found.setdefault((k, d, float(z)), []).append(
                            spectrum(dt, series, periods, float(z))
                        )
    return found


def evaluate(
    out_dir: str | Path,
    project: dict[str, Any],
    project_path: str | Path,
    loaded: list[tuple[dict[str, Any], Any]],
    level_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """The floor spectra of a run when the settings ask for them (see the module notes):
    ``{"available", "method", "periods", "damping", "broadening", "floors": [{"name", "z",
    "direction", "damping", "sa" (broadened), "raw", "zpa", "peak"}], "notes", "clause",
    "sheet"}``; None when the settings do not ask."""
    from opensees_studio.services.results import ModalResults

    from saengine.fem import records as rec
    from saengine.fem.combinations import settings_beside

    settings = settings_beside(project_path)
    options = getattr(getattr(settings, "analysis", None), "floorSpectra", None)
    if options is None:
        return None
    rule = table()
    if rule is None:
        name = code_context.code_name()
        return {"available": False, "reason": f"Not covered by the code pack {name}."}
    project_path = Path(project_path)
    out_dir = Path(out_dir)
    periods = periods_of(rule)
    dampings = [float(z) for z in (options.damping or rule.damping)]
    share = float(options.broadening if options.broadening is not None else rule.broadening)
    # the floors above the base (the base moves with the ground)
    rows = list(level_rows[1:]) if len(level_rows) > 1 else list(level_rows)
    if options.stories:
        wanted = _story_levels(project_path, options.stories)
        rows = [r for r in rows if any(abs(r["z"] - z) < 0.05 for z in wanted)]
    floors = _floor_nodes(project, [r["z"] for r in rows])
    from saengine.fem.linear_time_history import transient_cases

    has_history = bool(transient_cases(project))
    method = options.method
    if method == "pack":
        method = "timeHistory" if has_history and "timeHistory" in rule.methods else rule.methods[0]
        if method == "timeHistory" and not has_history:
            method = "spectrumToSpectrum"
    if method not in rule.methods:
        return {"available": False, "reason": f"the code pack does not allow the method {method}"}
    notes: list[str] = []
    curves: dict[tuple[int, int, float], np.ndarray] = {}
    if method == "timeHistory":
        if not has_history:
            return {"available": False, "reason": "the run has no time-history case"}
        found = _history_spectra(out_dir, project, project_path, floors, periods, dampings)
        for key, spectra in found.items():
            curves[key] = rec.design_value(np.asarray(spectra), rec.design_rule(len(spectra)))
        count = max((len(v) for v in found.values()), default=0)
        notes.append(f"{count} time histories; {rec.design_rule(count)} of their spectra")
    else:
        modal = next((r for _, r in loaded if isinstance(r, ModalResults)), None)
        if modal is None or not getattr(modal, "mode_shapes", None):
            return {"available": False, "reason": "the run has no modal case with mode shapes"}
        direct = rule.direct
        if direct is None:
            return {"available": False, "reason": "the code pack gives no direct method values"}
        zeta_s = float(direct.structureDamping or _spectrum_damping(project) or 0.05)
        from saengine.library.settings import read_soil_text, resolve_site_class

        root = code_context.find_project_root(project_path) or project_path.parent.parent
        settings, _ = resolve_site_class(settings, read_soil_text(root))
        ground = _ground_spectrum(settings, periods, zeta_s)
        omegas, terms = _modal_terms(project, modal, floors)
        notes.append(
            f"{len(omegas)} modes, structure damping {zeta_s:g}, strong motion {direct.duration:g} s; "
            "the site's elastic spectrum (R = I = 1)"
        )
        for k in range(len(floors)):
            for d in (0, 1):
                if not terms[d][k]:
                    continue
                for z in dampings:
                    curves[(k, d, z)] = direct_floor_spectrum(
                        periods,
                        ground,
                        omegas,
                        terms[d][k],
                        zeta_s,
                        z,
                        direct.duration,
                        direct.iterations,
                    )
    out_floors = []
    for (k, d, z), raw in sorted(curves.items()):
        sa = broaden(periods, raw, share)
        out_floors.append(
            {
                "name": rows[k]["name"],
                "z": rows[k]["z"],
                "direction": "XY"[d],
                "damping": z,
                "raw": [round(float(v), 5) for v in raw],
                "sa": [round(float(v), 5) for v in sa],
                "zpa": round(float(raw[0]), 5),
                "peak": round(float(sa.max()), 5),
            }
        )
    result = {
        "available": bool(out_floors),
        "reason": "" if out_floors else "no floor with masses and results",
        "method": method,
        "periods": [round(float(t), 5) for t in periods],
        "damping": dampings,
        "componentDamping": float(rule.componentDamping),
        "broadening": share,
        "floors": out_floors,
        "notes": notes,
        "clause": rule.source,
        "useForComponents": bool(options.useForComponents),
    }
    result["sheet"] = _sheet(result)
    _save(project_path.parent / FILE, result)
    return result


def _spectrum_damping(project: dict[str, Any]) -> float | None:
    for s in project.get("spectra", []) or []:
        value = s.get("damping_ratio") or s.get("damping")
        if value:
            return float(value)
    return None


def _story_levels(project_path: Path, stories: Sequence[str]) -> list[float]:
    root = project_path.resolve().parent.parent
    try:
        building = json.loads((root / "06 BIM/bim.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [
        float(s["elevation"]) / 1e3 for s in building.get("stories", []) if s.get("id") in stories
    ]


def _save(path: Path, result: dict[str, Any]) -> None:
    try:
        path.write_text(
            json.dumps({k: v for k, v in result.items() if k != "sheet"}), encoding="utf-8"
        )
    except OSError:
        pass


def _sheet(result: dict[str, Any]) -> dict[str, Any]:
    """The results view's table: per floor, direction and damping its ZPA and peak."""
    rows = [
        [
            f["name"],
            f"{f['z']:.2f}",
            f["direction"],
            f"{100 * f['damping']:g} %",
            f"{f['zpa']:.3f}",
            f"{f['peak']:.3f}",
        ]
        for f in result["floors"]
    ]
    label = {"timeHistory": "time history", "spectrumToSpectrum": "direct spectrum to spectrum"}
    return {
        "name": "Floor response spectra",
        "columns": ["Floor", "Level [m]", "Direction", "Damping", "ZPA [g]", "Peak, broadened [g]"],
        "rows": rows,
        "notes": [
            f"By {label.get(result['method'], result['method'])}, peaks broadened ±{100 * result['broadening']:g} % ({result['clause']})",
            *result["notes"],
        ],
    }


def report_rows(found: dict[str, Any] | None) -> dict[str, Any] | None:
    """The report's rows (strings) of :func:`evaluate`."""
    if not found:
        return None
    if not found.get("available"):
        return {"available": False, "reason": found.get("reason", "")}
    sheet = found.get("sheet") or _sheet(found)
    return {
        "available": True,
        "columns": sheet["columns"],
        "rows": sheet["rows"],
        "fails": [False] * len(sheet["rows"]),
        "clause": found["clause"],
        "notes": sheet["notes"],
    }


# ─────────────────────────────────────── components ───────────────────────────────────────


def _spectrum_at(curve: dict[str, Any], periods: Sequence[float], period: float | None) -> float:
    sa = np.asarray(curve["sa"], dtype=float)
    if period is None:
        return float(sa.max())
    return float(np.interp(math.log(period), np.log(np.asarray(periods)), sa))


def apply_to_components(
    root: str | Path, rows: list[dict[str, Any]], ground: Any, pack: Any, settings: Any
) -> list[str]:
    """When the settings ask for it, each component row (:func:`saengine.design.nonstructural.
    component_force`) takes its force from its floor's spectrum (see the module notes), its
    height-formula force kept as ``heightFc``; returns notes."""
    options = getattr(getattr(settings, "analysis", None), "floorSpectra", None)
    if options is None or not options.useForComponents:
        return []
    rule = table(pack)
    if rule is None or rule.components is None:
        return ["floor spectra are not covered by the code pack: the height formula is used"]
    try:
        found = json.loads((Path(root) / "08 FEM" / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [
            "no floor spectra worked out yet (run the analysis and open its results): the height formula is used"
        ]
    if not found.get("available"):
        return ["the floor spectra are not available: the height formula is used"]
    c = rule.components
    zeta = float(found.get("componentDamping", rule.componentDamping))
    curves = [f for f in found["floors"] if abs(float(f["damping"]) - zeta) < 1e-9]
    if not curves:
        return [f"no floor spectrum at {100 * zeta:g} % damping: the height formula is used"]
    periods = found["periods"]
    used = 0
    for row in rows:
        if row.get("exempt"):
            continue
        z = (float(row["z"]) + float(ground.base)) / 1e3  # m
        level = min({f["z"] for f in curves}, key=lambda lv: abs(lv - z))
        here = [f for f in curves if f["z"] == level]
        rigid = float(row["alpha"]) <= c.flexibleAlpha
        sa = max(_spectrum_at(f, periods, c.rigidPeriod if rigid else None) for f in here)
        force = sa * float(row["Wc"]) * float(row["Ic"]) / (float(row["R"]) if c.divideByR else 1.0)
        if c.bounds:
            force = min(max(force, float(row["lower"])), float(row["upper"]))
        old = float(row["design"])
        design = float(row.get("factor", 1.0)) * force
        scale = design / old if old > 0 else 0.0
        row["heightFc"] = row["Fc"]
        row["Fc"] = round(force, 3)
        row["design"] = round(design, 3)
        for key in ("perMetre", "pressure", "anchorage"):
            if isinstance(row.get(key), int | float):
                row[key] = round(row[key] * scale, 3)
        if isinstance(row.get("connections"), dict):
            row["connections"] = {k: round(v * scale, 3) for k, v in row["connections"].items()}
        row["floorSpectrum"] = {"Sa": round(sa, 4), "level": level, "rigid": rigid}
        basis = f"floor spectrum at {level:.2f} m: Sa = {sa:.3f} g ({'rigid' if rigid else 'peak, flexible'})"
        row["note"] = "; ".join(n for n in (row.get("note"), basis) if n)
        used += 1
    return [
        f"{used} components take their force from the floor spectra ({rule.sources.get('components') or rule.source})"
    ]
