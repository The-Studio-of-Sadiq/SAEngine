"""The isolators and dampers over the records of the nonlinear time history (alpha 9 P6):
each device's peak displacement (stroke), force, velocity and dissipated energy per record,
the design value over the suite, and its hysteresis loop.

The devices are the elements :func:`saengine.fem.isolation.nonlinear_bearings` (names ending
``/isolator``: elastomeric bearings, friction pendulums, flat sliders) and
:func:`saengine.fem.dampers.nonlinear_links` (``/damper``: twoNodeLink elements) put in the
nonlinear time history model. The run keeps every element's forces at each step
(``elements/<id>/forces``: the bearings' local forces, the links' basic forces) and the links'
deformations (``elements/<id>/deformations``); a bearing's deformation is its top node's
displacement over its fixed ground node.

Units: m, N, s (rows in mm, kN, kJ).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

#: Points of a hysteresis loop kept for the results view and the report.
LOOP_POINTS = 400
#: Loops kept per suite (the devices with the largest energy of the governing record).
LOOPS = 4
#: Bearing element types of the isolators.
BEARINGS = (
    "ElastomericBearingBoucWen",
    "ElastomericBearingPlasticity",
    "SingleFPBearing",
    "FlatSliderBearing",
)


def devices(project: dict[str, Any]) -> list[dict[str, Any]]:
    """The isolators and dampers of a nonlinear time history model: ``{"id", "name", "kind"
    ("isolator" or "damper"), "top"}`` (``top``: a bearing's upper node)."""
    out = []
    for e in project.get("elements", []):
        name = str(e.get("name", ""))
        if e.get("type") in BEARINGS and name.endswith("/isolator"):
            out.append(
                {"id": int(e["id"]), "name": name.removesuffix("/isolator"), "kind": "isolator",
                 "top": int(e["nodes"][1]), "element": e["type"]}
            )  # fmt: skip
        elif e.get("type") == "TwoNodeLink" and name.endswith("/damper"):
            out.append(
                {"id": int(e["id"]), "name": name.removesuffix("/damper"), "kind": "damper",
                 "top": None, "element": "TwoNodeLink"}
            )  # fmt: skip
    return out


def _thin(u: np.ndarray, f: np.ndarray) -> tuple[list[float], list[float]]:
    """At most :data:`LOOP_POINTS` points of a loop, in order."""
    step = max(int(np.ceil(len(u) / LOOP_POINTS)), 1)
    return [float(v) for v in u[::step]], [float(v) for v in f[::step]]


def _oriented(u: np.ndarray, f: np.ndarray) -> np.ndarray:
    """The force with the sign that makes the loop's work positive (the recorded local forces
    may act on the element or on the node)."""
    return -f if float(np.dot(np.diff(u), 0.5 * (f[1:] + f[:-1]))) < 0 else f


def record_devices(
    project: dict[str, Any], h5_path: str | Path, found: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Each device's response to one record (``h5_path``): ``{"name", "kind", "element",
    "displacement" (peak, m), "force" (peak, N), "velocity" (peak, m/s), "energy" (J), "u",
    "F" (the loop of the governing direction)}``."""
    import h5py

    found = devices(project) if found is None else found
    rows: list[dict[str, Any]] = []
    if not found:
        return rows
    with h5py.File(h5_path, "r") as f:
        times = np.asarray(f["time"][:], dtype=float) if "time" in f else None
        for dev in found:
            key = f"elements/{dev['id']}/forces"
            if key not in f:
                continue
            forces = np.asarray(f[key][:], dtype=float)
            if forces.ndim != 2 or not len(forces):
                continue
            if dev["kind"] == "isolator":
                disp_key = f"nodes/{dev['top']}/disp"
                if disp_key not in f or forces.shape[1] < 3:
                    continue
                disp = np.asarray(f[disp_key][:], dtype=float)[:, :2]
                n = min(len(disp), len(forces))
                disp = disp[:n] - disp[0]
                shear = forces[:n, 1:3] - forces[0, 1:3]  # local y, z: global X, Y
                axis = int(np.argmax(np.abs(disp).max(axis=0)))
                u = disp[:, axis]
                force = _oriented(u, shear[:, axis])
                other = _oriented(disp[:, 1 - axis], shear[:, 1 - axis])
                peak_u = float(np.hypot(disp[:, 0], disp[:, 1]).max())
                peak_f = float(np.hypot(force, other).max())
                energy = float(
                    np.dot(np.diff(u), 0.5 * (force[1:] + force[:-1]))
                    + np.dot(np.diff(disp[:, 1 - axis]), 0.5 * (other[1:] + other[:-1]))
                )
            else:
                def_key = f"elements/{dev['id']}/deformations"
                if def_key not in f:
                    continue
                deformation = np.asarray(f[def_key][:], dtype=float)
                n = min(len(deformation), len(forces))
                u = deformation[:n, 0] - deformation[0, 0]
                force = _oriented(u, forces[:n, 0] - forces[0, 0])
                peak_u = float(np.abs(u).max())
                peak_f = float(np.abs(force).max())
                energy = float(np.dot(np.diff(u), 0.5 * (force[1:] + force[:-1])))
            velocity = 0.0
            if times is not None and len(times) >= n > 1:
                dt = np.diff(times[:n])
                dt[dt <= 0] = np.inf
                velocity = float(np.abs(np.diff(u) / dt).max())
            loop_u, loop_f = _thin(u, force)
            rows.append(
                {
                    "name": dev["name"], "kind": dev["kind"], "element": dev["element"],
                    "displacement": peak_u, "force": peak_f, "velocity": velocity,
                    "energy": max(energy, 0.0), "u": loop_u, "F": loop_f,
                }
            )  # fmt: skip
    return rows


def suite_devices(
    per_record: list[list[dict[str, Any]]], names: list[str], rule: str
) -> dict[str, Any]:
    """The devices of a suite: each one's design displacement, force, velocity and energy over
    the records (the largest, or the mean, by ``rule``), the governing record, and the loops
    of the devices with the most energy. ``names``: the records' case names."""
    by_device: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = {}
    for k, rows in enumerate(per_record):
        for row in rows:
            by_device.setdefault((row["kind"], row["name"]), []).append((k, row))
    count = max(len(per_record), 1)
    out_rows = []
    for (kind, name), found in by_device.items():
        k, worst = max(found, key=lambda item: item[1]["displacement"])

        def value(key: str, found: list[tuple[int, dict[str, Any]]] = found) -> float:
            values = [row[key] for _, row in found]
            return sum(values) / count if rule == "mean" else max(values)

        out_rows.append(
            {
                "kind": kind,
                "name": name,
                "element": worst["element"],
                "record": names[k] if k < len(names) else str(k),
                "displacement_mm": value("displacement") * 1e3,
                "force_kN": value("force") / 1e3,
                "velocity_ms": value("velocity"),
                "energy_kJ": value("energy") / 1e3,
            }
        )
    out_rows.sort(key=lambda r: (r["kind"], -r["displacement_mm"]))
    loops = []
    for kind in ("isolator", "damper"):
        candidates = [
            (k, row) for k, rows in enumerate(per_record) for row in rows if row["kind"] == kind
        ]
        candidates.sort(key=lambda item: -item[1]["energy"])
        seen: set[str] = set()
        for k, row in candidates:
            if row["name"] in seen or len(seen) >= LOOPS // 2:
                continue
            seen.add(row["name"])
            loops.append(
                {
                    "kind": kind,
                    "name": row["name"],
                    "record": names[k] if k < len(names) else str(k),
                    "u_mm": [v * 1e3 for v in row["u"]],
                    "F_kN": [v / 1e3 for v in row["F"]],
                }
            )
    return {"rows": out_rows, "loops": loops, "rule": rule}
