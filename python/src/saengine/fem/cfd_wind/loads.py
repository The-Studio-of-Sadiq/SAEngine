"""The "CFD wind" cases (alpha 9 L3): the CFD wind tunnel's storey forces in place of the code's
static wind, when the project asks for it (``wind.cfd.useInAnalysis``).

Each direction run becomes a wind case on the plan axis it is nearest: within 45° of +X the case
WX, of +Y WY, of -X WXN, of -Y WYN; a second or third direction near the same axis becomes the
variant WX2, WX3, ... (at most :data:`saengine.fem.loads.WIND_MAX_VARIANTS` per axis). The
direction with the largest base shear along its axis takes the axis's own case. The load
combinations then take every variant where they take the axis's wind and the opposite
direction's case for a negative factor (:func:`saengine.fem.loads.resolve_wind_cases`), so
every direction is designed for. An axis without a direction keeps none: a combination with -WX
and no WXN takes WX with the negative factor (the mirror image).

The forces: F = q·CF of each level (:func:`saengine.fem.cfd_wind.post.design_levels`), q the
code's design velocity pressure at the roof height (velocity pressure × the pack's gust factor,
with the project's overrides), shared among the level's nodes like the code's wind, with the
couple that puts the CFD's torsion about the plan's centre. When the code pack gives a lower
limit (``cfdWind.lowerLimit``), every CFD case is scaled up until the largest base shear along
X and along Y is at least that share of the code's own static wind (WX, WY before the CFD).

The code's torsional wind cases (WTX, WTY, the design cases' eccentricity) are kept: the CFD's
mean torsion is in its own cases, the code's accidental torsion on top of it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.fem.cfd_wind import RESULTS, post

#: Levels of the results and of the model match within this [m].
LEVEL_TOLERANCE = 0.05


def lower_limit() -> tuple[float | None, str]:
    """The code pack's lower limit on the CFD base shear (share of the code's) and its clause."""
    pack = code_context.current()
    if not pack.has("cfdWind"):
        return None, ""
    table = pack.table("cfdWind")
    return table.lowerLimit, str((table.sources or {}).get("lowerLimit") or "")


def design_pressure(height: float, speed: float, exposure: str, importance: float) -> float:
    """q [kN/m²] the CFD coefficients scale with: the code's velocity pressure at ``height``
    times its gust factor (run inside :func:`saengine.fem.loads.wind_overrides`)."""
    from saengine.fem import loads as fl

    return fl.velocity_pressure(height, speed, exposure, importance) * fl.gust_factor(
        height, exposure
    )


def assign_cases(
    directions: list[dict[str, Any]], q: float, most: int
) -> tuple[list[tuple[str, dict[str, Any]]], list[float]]:
    """(case name, direction) of every direction (see the module notes) and the angles left
    out (more than ``most`` near one axis: the smallest along their axis)."""
    from saengine.fem.loads import wind_variant_case

    groups: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    for d in directions:
        case = post.case_of(d["angle"])
        forces = post.base_forces(d, q, 0.0)
        along = {
            "WX": forces["Vx_kN"],
            "WXN": -forces["Vx_kN"],
            "WY": forces["Vy_kN"],
            "WYN": -forces["Vy_kN"],
        }[case]
        groups.setdefault(case, []).append((along, d))
    out: list[tuple[str, dict[str, Any]]] = []
    dropped: list[float] = []
    for case in ("WX", "WY", "WXN", "WYN"):
        ranked = sorted(groups.get(case, []), key=lambda item: -item[0])
        for k, (_, d) in enumerate(ranked):
            if k >= most:
                dropped.append(float(d["angle"]))
                continue
            out.append((wind_variant_case(case, k + 1), d))
    return out, dropped


def apply_cfd_wind(
    *,
    model_dir: str | Path | None,
    heights: list[float],
    base_m: float,
    coords: dict[int, np.ndarray],
    level_shares: Callable[[float], dict[int, float]],
    retained_of: dict[float, int],
    torsion_forces: Callable[..., dict[int, np.ndarray]],
    patterns: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    speed: float,
    exposure: str,
    importance: float,
) -> list[str]:
    """Replaces the code's WX, WY (after :func:`saengine.fem.derive._wind_loads`) by the CFD
    cases and adds their variants into ``patterns``; ``summary["cfdWind"]`` says what was done.
    Returns the notes. Nothing changes (a note says why) when there are no usable results."""
    from saengine.fem import loads as fl

    if model_dir is None:
        return ["CFD wind: the analysis model has no project folder; the code's wind is used"]
    results = post.read_results(Path(model_dir).parent / RESULTS)
    if results is None or not results.get("directions"):
        return [
            (
                "CFD wind is asked for (Project Settings > Wind > CFD wind tunnel) but no CFD run "
                "has finished: the code's wind is used"
            )
        ]
    envelope = results["envelope"]
    levels = [float(z) for z in envelope["levels_m"]]
    if (
        len(levels) != len(heights)
        or abs(float(envelope["base_m"]) - base_m) > LEVEL_TOLERANCE
        or any(abs(a - b) > LEVEL_TOLERANCE for a, b in zip(levels, heights, strict=False))
    ):
        return [
            (
                "CFD wind: the CFD results are for other levels than the model's (run the CFD wind "
                "tunnel again for this building): the code's wind is used"
            )
        ]
    directions = list(results["directions"])
    height = heights[-1] - base_m
    q = design_pressure(height, speed, exposure, importance)
    assigned, dropped = assign_cases(directions, q, fl.WIND_MAX_VARIANTS)
    names = {name for name, _ in assigned}
    if "WX" not in names or "WY" not in names:
        return [
            (
                "CFD wind: the CFD run has no direction within 45° of +X or of +Y, so it cannot "
                "replace both WX and WY: the code's wind is used"
            )
        ]
    notes: list[str] = []
    share, clause = lower_limit()
    scale = 1.0
    code_x, code_y = float(summary.get("wind_X_kN") or 0), float(summary.get("wind_Y_kN") or 0)
    bases = {name: post.base_forces(d, q, base_m) for name, d in assigned}
    cfd_x = max(abs(b["Vx_kN"]) for b in bases.values())
    cfd_y = max(abs(b["Vy_kN"]) for b in bases.values())
    if share is not None:
        needs = [share * code / cfd for code, cfd in ((code_x, cfd_x), (code_y, cfd_y)) if cfd > 0]
        scale = max([1.0, *needs])
        if scale > 1.0:
            notes.append(
                f"CFD wind: scaled by {scale:.3f} so the largest base shear along X and Y is at "
                f"least {share:.0%} of the code's static wind ({code_x:.1f} kN, {code_y:.1f} kN)"
                + (f" ({clause})" if clause else "")
            )
    centre = results["reference"]["centre"]
    xr, yr = float(centre[0]), float(centre[1])
    # The code's WX, WY go; the CFD's take their place.
    for case in ("WX", "WY"):
        patterns.setdefault(case, {"nodal": {}, "element": {}})["nodal"] = {}
    labels: dict[str, str] = {}
    rows: dict[str, list[dict[str, float]]] = {}
    axis_cases: dict[str, list[str]] = {"X": [], "Y": []}
    for name, d in assigned:
        target = patterns.setdefault(name, {"nodal": {}, "element": {}})["nodal"]
        level_rows = post.design_levels(d, q * scale)
        for h, row in zip(heights, level_rows, strict=True):
            shares = level_shares(h)
            total = sum(shares.values())
            if total <= 0:
                continue
            centre_xy = sum(coords[n][:2] * s for n, s in shares.items()) / total
            fx, fy = row["Fx_kN"] * 1e3, row["Fy_kN"] * 1e3  # N
            for node_id, s in shares.items():
                vector = target.setdefault(node_id, np.zeros(6))
                vector[0] += fx * s
                vector[1] += fy * s
            # The forces at the shares' centre turn by (cx - xr)·Fy - (cy - yr)·Fx about the
            # plan's centre; the couple makes up the CFD's torsion there.
            couple = row["Mz_kNm"] * 1e3 - (
                (float(centre_xy[0]) - xr) * fy - (float(centre_xy[1]) - yr) * fx
            )
            for node_id, vector in torsion_forces(
                coords, shares, retained_of.get(h), couple
            ).items():
                target.setdefault(node_id, np.zeros(6))[:] += vector
        labels[name] = f"CFD wind toward {float(d['angle']):g}° (engineer-supplied)"
        rows[name] = [{**r, "z": r["z_m"]} for r in level_rows]
        axis_cases["X" if name.startswith("WX") else "Y"].append(name)
    if dropped:
        notes.append(
            "CFD wind: more than "
            f"{fl.WIND_MAX_VARIANTS} directions near one axis; left out: "
            + ", ".join(f"{a:g}°" for a in dropped)
        )
    for axis in ("XN", "YN"):
        if f"W{axis}" not in names:
            notes.append(
                f"CFD wind: no direction near -{axis[0]}: the combinations take W{axis[0]} with "
                "the negative factor (its mirror image)"
            )
    if (summary.get("wind") or {}).get("rooftop"):
        notes.append(
            "CFD wind: the rooftop equipment's code wind is not in the CFD cases (the envelope "
            "has no rooftop structures); add it as loads if it matters"
        )
    if fl.wind_design_cases() is None and len(assigned) > 2:
        notes.append(
            "CFD wind: the code pack has no design wind cases, so its combinations take WX and WY "
            "only; the other directions' cases are analysed but not combined"
        )
    if not results.get("complete"):
        notes.append(
            "CFD wind: the CFD run did not finish every direction; the finished ones are used"
        )
    unconverged = [f"{d['angle']:g}°" for d in directions if d.get("converged") is False]
    if unconverged:
        notes.append("CFD wind: not converged (check before use): " + ", ".join(unconverged))
    notes.append(
        f"CFD wind ({len(assigned)} directions, engineer-supplied, to be validated): the wind "
        f"cases {', '.join(name for name, _ in assigned)} take the CFD storey forces F = q·CF, "
        f"q = {q:.3f} kN/m² (the code's velocity pressure × gust factor at h = {height:.2f} m)"
        + (f" × {scale:.3f}" if scale > 1.0 else "")
        + "; the code's torsional wind cases are kept"
    )
    summary["cfdWind"] = {
        "labels": labels,
        "cases": {name: float(d["angle"]) for name, d in assigned},
        "axisCases": axis_cases,
        "q_kPa": q,
        "scale": scale,
        "lowerLimit": share,
        "code_kN": {"X": code_x, "Y": code_y},
        "base": {name: post.base_forces(d, q * scale, base_m) for name, d in assigned},
        "levels": rows,
        "complete": bool(results.get("complete")),
    }
    return notes
