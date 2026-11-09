"""From a CFD case's surface pressures to pressure coefficients and storey forces (alpha 9 L3).

The building's faces of the mesh (the patches ``building*``) with their kinematic pressure p
[m²/s²] (the cells' values: the pressure is zero-gradient at the walls) give

- Cp = p / (½ Uref²) of every face (Uref the inlet's speed at the roof height H, p = 0 at the
  outlet);
- the force coefficients of each level, CF = Σ Cp·A over the faces of its band [m²] (the force
  per unit reference pressure: F = q·CF), the torsion coefficient CMz = Σ (x·CFy - y·CFx) [m³]
  about the plan's centre, and the projected area of the band facing the wind, for the
  dimensionless Cf = CF / A;
- Cp of every facade zone (the walls facing +X, -X, +Y, -Y of the model, the roofs, the
  undersides) in every storey's band: the area-weighted mean, the least and the largest, with the
  zone's role in this direction (windward, leeward, side).

A level's band reaches from half way to the level below (the base takes the lower half of the
first storey, as in the code's own storey forces) to half way to the level above (the roof level
everything above). Face area vectors point out of the air, into the building, so the force on
the building is Σ p·A.

Storey forces for design (:func:`design_levels`): F = q·CF with q the code's design velocity
pressure at H (``velocity_pressure(H) · G``, the code pack's own gust factor), a mean-pressure
(quasi-steady) scaling: the steady RANS gives mean pressures only.
"""

from __future__ import annotations

import itertools
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem.cfd_wind import SCHEMA, foam_io
from saengine.fem.cfd_wind.envelope import to_model

#: Wall faces steeper than this (|nz| below) belong to a facade [-].
WALL_NZ = 0.7
#: A face is windward (leeward) when its outward normal is against (along) the wind by more
#: than this cosine.
ROLE_COS = 0.5
ZONES = ("X+", "Y+", "X-", "Y-", "roof", "soffit")


@dataclass(frozen=True)
class Surface:
    """The building's faces in the case's axes: centres [m] (z above the base), area vectors
    [m²] out of the air, kinematic pressure [m²/s²]."""

    centres: np.ndarray
    vectors: np.ndarray
    p: np.ndarray


def read_surface(case: Path) -> Surface:
    """The building's faces and pressures of a finished case (its latest time)."""
    mesh = case / "constant" / "polyMesh"
    time = foam_io.latest_time(case, "p")
    if time is None:
        raise FileNotFoundError("the case has no results (no time folder with p)")
    boundary = foam_io.read_boundary(mesh / "boundary")
    patches = [(n, b) for n, b in boundary.items() if n.lower().startswith("building")]
    if not patches:
        raise ValueError("the mesh has no building patch (snappyHexMesh did not cut it out)")
    points = foam_io.read_points(mesh / "points")
    owner = foam_io.read_labels(mesh / "owner")
    p_cells = foam_io.read_internal(time / "p")
    centres, vectors, values = [], [], []
    for _, patch in patches:
        first, count = int(patch["startFace"]), int(patch["nFaces"])
        if count <= 0:
            continue
        faces = foam_io.read_faces(mesh / "faces", first, count)
        c, v = foam_io.face_geometry(points, faces)
        cells = owner[first : first + count]
        pv = np.full(count, float(p_cells)) if np.isscalar(p_cells) else np.asarray(p_cells)[cells]
        centres.append(c)
        vectors.append(v)
        values.append(pv)
    if not centres:
        raise ValueError("the building patch has no faces")
    return Surface(np.vstack(centres), np.vstack(vectors), np.concatenate(values))


def band_edges(levels: list[float]) -> list[float]:
    """The bands' edges [m above the base]: the base's band from 0 up to half the first
    storey, each level's from half way below to half way above, the roof's up to infinity."""
    edges = [levels[0] / 2]
    edges += [(a + b) / 2 for a, b in itertools.pairwise(levels)]
    return [*edges, math.inf]


def evaluate(
    surface: Surface,
    *,
    angle: float,
    levels: list[float],
    base: float,
    uref: float,
) -> dict[str, Any]:
    """The coefficients of one direction (see the module notes). ``levels``: the levels above
    the base [m]; ``base``: the base's elevation [m], to give levels absolute in the result.
    Moments about the case's origin, the plan's centre."""
    q = 0.5 * uref**2
    cp = surface.p / q
    cf = surface.vectors * cp[:, None]  # [m²] per face, case axes
    x, y, z = surface.centres[:, 0], surface.centres[:, 1], surface.centres[:, 2]
    edges = band_edges(levels)
    band = np.searchsorted(np.asarray(edges), z, side="right")  # 0: base, i: level i
    # Outward normals of the building and the wind in the model's axes.
    a = math.radians(angle)
    ca, sa = math.cos(a), math.sin(a)
    vx, vy = surface.vectors[:, 0], surface.vectors[:, 1]
    fx = cf[:, 0] * ca - cf[:, 1] * sa
    fy = cf[:, 0] * sa + cf[:, 1] * ca
    mz = x * cf[:, 1] - y * cf[:, 0]
    areas = np.linalg.norm(surface.vectors, axis=1)
    safe = np.where(areas > 0, areas, 1.0)
    nx_model = -(vx * ca - vy * sa) / safe
    ny_model = -(vx * sa + vy * ca) / safe
    nz = -surface.vectors[:, 2] / safe
    facing = np.where(surface.vectors[:, 0] > 0, surface.vectors[:, 0], 0.0)  # windward area

    def sums(mask: np.ndarray) -> dict[str, float]:
        return {
            "CFx_m2": float(fx[mask].sum()),
            "CFy_m2": float(fy[mask].sum()),
            "CMz_m3": float(mz[mask].sum()),
        }

    rows = []
    for i, level in enumerate(levels):
        mask = band == i + 1
        row = {"z_m": base + level, **sums(mask), "area_m2": float(facing[mask].sum())}
        along = row["CFx_m2"] * ca + row["CFy_m2"] * sa
        across = -row["CFx_m2"] * sa + row["CFy_m2"] * ca
        row["cfAlong"] = along / row["area_m2"] if row["area_m2"] > 0 else None
        row["cfAcross"] = across / row["area_m2"] if row["area_m2"] > 0 else None
        rows.append(row)
    to_base = sums(band == 0)
    total = sums(np.ones_like(band, dtype=bool))
    # Facade zones by the model's axes and the roof, per storey band.
    zone = np.full(len(cp), "", dtype=object)
    wall = np.abs(nz) < WALL_NZ
    phi = np.degrees(np.arctan2(ny_model, nx_model)) % 360
    compass = np.array(["X+", "Y+", "X-", "Y-"], dtype=object)[
        (((phi + 45) % 360) // 90).astype(int)
    ]
    zone[wall] = compass[wall]
    zone[(~wall) & (nz >= WALL_NZ)] = "roof"
    zone[(~wall) & (nz <= -WALL_NZ)] = "soffit"
    zones = []
    for i, level in enumerate(levels):
        in_band = band == i + 1
        if i == 0:
            in_band = in_band | (band == 0)
        for name in ZONES:
            mask = in_band & (zone == name)
            if not mask.any():
                continue
            w = areas[mask]
            area = float(w.sum())
            if name in ("roof", "soffit"):
                role = name
            else:
                normal = {"X+": (1, 0), "Y+": (0, 1), "X-": (-1, 0), "Y-": (0, -1)}[name]
                c = normal[0] * ca + normal[1] * sa
                role = "windward" if c < -ROLE_COS else "leeward" if c > ROLE_COS else "side"
            zones.append(
                {
                    "z_m": base + level,
                    "zone": name,
                    "role": role,
                    "area_m2": area,
                    "cpMean": float((cp[mask] * w).sum() / area) if area > 0 else 0.0,
                    "cpMin": float(cp[mask].min()),
                    "cpMax": float(cp[mask].max()),
                }
            )
    return {
        "angle": float(angle),
        "uref": float(uref),
        "faces": len(cp),
        "levels": rows,
        "toBase": to_base,
        "total": total,
        "zones": zones,
    }


# ───────────────────────────────────────── results file ─────────────────────────────────────────


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_results(path: Path) -> dict[str, Any] | None:
    """The results file, or None when there is none (or it is not one)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None


def start_results(path: Path, plan: dict[str, Any]) -> None:
    """A new results file for the run of ``plan`` (the directions follow as they finish)."""
    _write_json(
        path,
        {
            "schema": SCHEMA,
            "generated": plan.get("generated"),
            "complete": False,
            "envelope": plan["envelope"],
            "reference": plan["reference"],
            "settings": plan["settings"],
            "installation": {
                k: plan.get("installation", {}).get(k) for k in ("version", "flavour", "solver")
            },
            "pack": plan.get("pack"),
            "directions": [],
            "notes": list(plan.get("notes") or []),
        },
    )


def store_direction(path: Path, direction: dict[str, Any], complete: bool = False) -> None:
    """Adds (or replaces) one direction's coefficients in the results file."""
    data = read_results(path)
    if data is None:
        raise FileNotFoundError(str(path))
    rest = [d for d in data["directions"] if abs(d["angle"] - direction["angle"]) > 1e-9]
    data["directions"] = sorted([*rest, direction], key=lambda d: d["angle"])
    data["complete"] = complete
    _write_json(path, data)


def finish_results(path: Path, complete: bool, notes: list[str] | None = None) -> None:
    data = read_results(path)
    if data is None:
        return
    data["complete"] = complete
    data["notes"] = [*data.get("notes", []), *(notes or [])]
    _write_json(path, data)


# ───────────────────────────────────────── design forces ─────────────────────────────────────────


def design_levels(direction: dict[str, Any], q: float) -> list[dict[str, float]]:
    """The storey forces of one direction for the design velocity pressure ``q`` [kN/m²]:
    Fx, Fy [kN] and Mz [kN·m] about the plan's centre at each level."""
    return [
        {
            "z_m": row["z_m"],
            "Fx_kN": q * row["CFx_m2"],
            "Fy_kN": q * row["CFy_m2"],
            "Mz_kNm": q * row["CMz_m3"],
        }
        for row in direction["levels"]
    ]


def base_forces(direction: dict[str, Any], q: float, base: float) -> dict[str, float]:
    """The base shears, torsion and overturning moments [kN, kN·m] of the levels' forces."""
    levels = design_levels(direction, q)
    vx = sum(r["Fx_kN"] for r in levels)
    vy = sum(r["Fy_kN"] for r in levels)
    return {
        "Vx_kN": vx,
        "Vy_kN": vy,
        "T_kNm": sum(r["Mz_kNm"] for r in levels),
        # Overturning about the base: about Y by the X forces, about X by the Y forces.
        "Myy_kNm": sum(r["Fx_kN"] * (r["z_m"] - base) for r in levels),
        "Mxx_kNm": -sum(r["Fy_kN"] * (r["z_m"] - base) for r in levels),
    }


def case_of(angle: float) -> str:
    """The plan axis case a direction belongs to: WX (within 45° of +X), WY, WXN, WYN."""
    a = float(angle) % 360
    return ("WX", "WY", "WXN", "WYN")[int(((a + 45) % 360) // 90)]


def to_model_vector(vector: tuple[float, float], angle: float) -> tuple[float, float]:
    return to_model(vector, angle)
