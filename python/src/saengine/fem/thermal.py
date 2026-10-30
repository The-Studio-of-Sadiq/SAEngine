"""The temperature load case T: uniform temperature changes and gradients through the depth.

BNBC 2020 Part 6 Sec 2.6.4 asks for temperature effects to be considered where significant,
either relieved by expansion/contraction joints or designed for; the analysis shall include
"the warping or any other distortion caused due to temperature changes and temperature
gradient". Its load combinations (Sec 2.7) carry them as ``T``, the self-straining forces
(temperature, creep, shrinkage, differential settlement). This module computes ``T`` for a
temperature change:

- ``ΔTu``: a uniform change of the members' temperature relative to the temperature they were
  built at (+ expansion, - contraction), and
- ``ΔTg``: a linear gradient through the depth, top face minus bottom face (a sun-exposed roof:
  top hotter), of horizontal members and slabs at the roof.

Neither OpenSees' ``elasticBeamColumn`` nor ``ASDShellQ4``/``ASDShellT3`` takes a thermal load
in OpenSeesPy 3.8 (``eleLoad -beamThermal`` / ``-shellThermal`` are refused: "load type
unknown"; the thermal elements that accept them are fiber elements meant for fire analysis).
So the case is analysed with equivalent fixed-end actions, the textbook method of the direct
stiffness method:

1. Each element is held at its nodes (fixed) and heated. The forces the nodes then exert on it
   are its fixed-end forces ``f0``:

   - frame member (local axes, OpenSees ``localForce`` convention, the forces of the nodes on
     the element): axial ``N0 = E A α ΔTu`` (``+N0`` at i, ``-N0`` at j: the held member is in
     compression), and for a gradient ``ΔTg`` over the depth ``h`` along local z (``+z`` face
     hotter) ``M0 = E Iy α ΔTg / h`` (``My = +M0`` at i, ``-M0`` at j: the held member's
     hotter face is compressed); a gradient along local y gives ``Mz = -E Iz α ΔTg / h`` at i,
     ``+`` at j;
   - shell (plate section, isotropic): the thermal membrane force and moment per unit length
     ``NT = E t α ΔTu / (1 - ν)`` and ``MT = E t² α ΔTg / (12 (1 - ν))`` (``= D (1 + ν) κT`` with
     ``D = E t³ / 12 (1 - ν²)`` and the free thermal curvature ``κT = α ΔTg / t``). For a
     resultant constant over the element the consistent nodal forces are its boundary
     tractions: along each edge of length ``Le`` with outward in-plane normal ``n``,
     ``NT n Le / 2`` and the moment vector ``MT (h × n) Le / 2`` (``h``: the unit normal of
     the hotter face) at each of the edge's two nodes.

2. The structure is analysed under the equivalent nodal loads ``-f0`` (in global axes): the
   nodal loads of the case's load pattern. The reactions OpenSees reports already include the
   loads applied at restrained nodes, so they are the true reactions. A rigid floor diaphragm
   cannot be used for this case: it holds the ends of every floor member together in plan, so a
   heated roof beam would carry the fully held force ``E A α ΔTu`` and bend no column. The
   case's analysis therefore runs without the diaphragms (OpenSees Studio's
   ``StaticCase.release_diaphragms``), the floors acting through their own slabs and beams.
   The case is superposed on the other cases (analysed with the diaphragms) as usual.

3. The members' true internal forces are the analysis forces plus the fixed-end forces: for a
   frame ``localForce + f0`` (12 values), for a shell its section forces plus
   ``(-NT, -NT, 0, -MT', -MT', 0, 0, 0)`` (``MT'`` = ``MT`` signed to the shell's own normal).
   The deflected shape needs no correction: a held member stays straight. These "add backs"
   are written next to the model (``thermal.json``) and read by the result views, the
   combinations and the design (:func:`end_force_corrections`, :func:`shell_force_corrections`).

Units: m, N, Pa (the analysis model), temperatures in °C (= K for differences).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from saengine.fem.derive import local_axes

CASE = "T"
CASE_TITLE = "Temperature"
SIDE_FILE = "thermal.json"
"""The fixed-end forces of the case, beside the analysis model (``08 FEM/thermal.json``)."""

#: Coefficient of thermal expansion [1/°C] by material category when the material gives none:
#: typical values (concrete 10e-6, steel 12e-6; clay brick masonry about 6e-6).
DEFAULT_ALPHA: dict[str, float] = {
    "concrete": 10e-6,
    "steel": 12e-6,
    "rebar": 12e-6,
    "masonry": 6e-6,
}

#: Sign of ASDShell's bending moments M11, M22 against the moment ``∫ σ z dz`` (z along the
#: shell's local 3 axis): checked by a free plate heated on one face (tests/test_fem_thermal.py).
_SHELL_MOMENT_SIGN = 1.0

_LEVEL_TOLERANCE = 1e-3  # m


@dataclass(frozen=True)
class ThermalOptions:
    """What the case applies (the integrator fills it from the project settings)."""

    uniform: float = 0.0
    """ΔTu [°C]: uniform change relative to the construction temperature, + expansion."""
    gradient: float = 0.0
    """ΔTg [°C]: top face minus bottom face of the roof's horizontal members and slabs."""
    scope: Literal["roof", "all"] = "roof"
    """Where ΔTu applies: the roof's horizontal members and slabs (exposed to the sun over a
    shaded building), or every frame member and shell (an open, unenclosed structure)."""


@dataclass(frozen=True)
class ThermalSection:
    """The thermal data of an analysis section."""

    alpha: float
    """Coefficient of thermal expansion [1/°C]."""
    depth: float | None = None
    """Depth along local z of a horizontal frame member [m] (for ΔTg); plates use their h."""


@dataclass
class ThermalCase:
    """The case added to the project, and what the result readers add back."""

    pattern_id: int
    analysis_id: int
    corrections: dict[str, Any]
    notes: list[str] = field(default_factory=list)


# ───────────────────────────────── element formulas ─────────────────────────────────


def frame_fixed_end_forces(
    e: float,
    a: float,
    iy: float,
    iz: float,
    alpha: float,
    uniform: float,
    gradient_z: float = 0.0,
    depth_z: float | None = None,
    gradient_y: float = 0.0,
    depth_y: float | None = None,
) -> np.ndarray:
    """Fixed-end forces of a held frame member (12 values, local axes, OpenSees ``localForce``:
    the forces and moments of the nodes on the member at i then j).

    ``gradient_z``: temperature of the +z face minus the -z face over ``depth_z`` [m] (bending
    about local y, stiffness ``E Iy``); ``gradient_y`` likewise along local y (about z).
    """
    f = np.zeros(12)
    n0 = e * a * alpha * uniform
    f[0], f[6] = n0, -n0
    if gradient_z and depth_z:
        m0 = e * iy * alpha * gradient_z / depth_z
        f[4], f[10] = m0, -m0
    if gradient_y and depth_y:
        m0 = e * iz * alpha * gradient_y / depth_y
        f[5], f[11] = -m0, m0
    return f


def plate_thermal_resultants(
    e: float, nu: float, thickness: float, alpha: float, uniform: float, gradient: float
) -> tuple[float, float]:
    """``(NT, MT)``: the membrane force [N/m] and moment [N·m/m] a fully held isotropic plate
    would need to suppress ``uniform`` and ``gradient`` (hotter face minus the other)."""
    n_t = e * thickness * alpha * uniform / (1 - nu)
    m_t = e * thickness**2 * alpha * gradient / (12 * (1 - nu))
    return n_t, m_t


def shell_normal(corners: list[np.ndarray]) -> np.ndarray:
    """The unit normal of a shell from its node order (right hand), as ASDShell takes it."""
    if len(corners) == 4:
        n = np.cross(corners[2] - corners[0], corners[3] - corners[1])
    else:
        n = np.cross(corners[1] - corners[0], corners[2] - corners[0])
    return n / np.linalg.norm(n)


def shell_equivalent_loads(
    corners: list[np.ndarray], n_t: float, m_t: float, hot: np.ndarray | None = None
) -> list[np.ndarray]:
    """Equivalent nodal loads (6 per node, global axes) of a constant thermal membrane force
    ``n_t`` and moment ``m_t`` in a flat shell: ``-f0``, its boundary tractions.

    ``hot``: unit normal of the hotter face (for ``m_t``); by default the shell's own normal.
    """
    normal = shell_normal(corners)
    hot = normal if hot is None else hot / np.linalg.norm(hot)
    loads = [np.zeros(6) for _ in corners]
    count = len(corners)
    for k in range(count):
        a, b = corners[k], corners[(k + 1) % count]
        edge = b - a
        length = float(np.linalg.norm(edge))
        outward = np.cross(edge, normal) / length
        force = n_t * outward * length / 2
        moment = m_t * np.cross(hot, outward) * length / 2
        for node in (k, (k + 1) % count):
            loads[node][:3] += force
            loads[node][3:] += moment
    return loads


# ───────────────────────────────── sections ─────────────────────────────────


def default_alpha(material: Any) -> float | None:
    """The material's α [1/°C], or the typical value of its category, or None."""
    alpha = getattr(material.mechanical, "alpha", None)
    if alpha:
        return float(alpha)
    return DEFAULT_ALPHA.get(material.category.value)


def profile_depth(profile: Any, turned: bool = False) -> float:
    """Overall depth of a profile [mm] (its vertical extent; its width when ``turned``)."""
    from saengine.library.sections import profile_geometry

    xmin, xmax, ymin, ymax = profile_geometry(profile).calculate_extents()
    return float(xmax - xmin) if turned else float(ymax - ymin)


def thermal_sections(
    section_keys: dict[int, tuple[Any, ...]], types: dict[str, Any], mats: dict[str, Any]
) -> dict[int, ThermalSection]:
    """Thermal data of the analysis sections from :func:`saengine.fem.derive.derive_fem`'s
    section keys (``{section id: key}``; keys ``(type id, quarter turns % 2, vertical)`` for
    frames, ``("plate", type id)`` for plates; other keys are skipped)."""
    result: dict[int, ThermalSection] = {}
    for section_id, key in section_keys.items():
        if key[0] == "plate":
            object_type = types.get(key[1])
            depth = None
        elif len(key) == 3 and isinstance(key[2], bool | np.bool_):  # numpy for beams
            object_type = types.get(key[0])
            depth = None
            if object_type is not None and hasattr(object_type, "profile") and not key[2]:
                # A horizontal member: local z is up, along the profile's depth.
                depth = profile_depth(object_type.profile, bool(key[1])) / 1000
        else:
            continue
        material = mats.get(object_type.material) if object_type is not None else None
        alpha = default_alpha(material) if material is not None else None
        if alpha:
            result[section_id] = ThermalSection(alpha=alpha, depth=depth)
    return result


# ───────────────────────────────── the case ─────────────────────────────────

#: A horizontal beam above another, within this distance of it in plan, shades it [m].
_COVER_DISTANCE = 0.05


def _thermal_candidates(project: dict[str, Any]) -> list[dict[str, Any]]:
    """The elements the case can heat: elastic frame members and shells (not embedded ones)."""
    return [
        e
        for e in project.get("elements", [])
        if e.get("type") in ("ElasticBeamColumn", "Shell")
        and not str(e.get("name", "")).split("#")[0].endswith("/embed")
    ]


def _in_polygon(point: np.ndarray, polygon: np.ndarray, tol: float) -> bool:
    """Whether a plan point is inside (or within ``tol`` of the edge of) a plan polygon."""
    inside = False
    n = len(polygon)
    for k in range(n):
        a, b = polygon[k], polygon[(k + 1) % n]
        ab = b - a
        t = float(np.clip(((point - a) @ ab) / (ab @ ab), 0.0, 1.0)) if ab @ ab > 0 else 0.0
        if np.linalg.norm(point - (a + t * ab)) <= tol:
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            x = a[0] + (point[1] - a[1]) * ab[0] / ab[1]
            if point[0] < x:
                inside = not inside
    return inside


def exposed_elements(project: dict[str, Any]) -> set[int]:
    """The roof of the model: the ids of its horizontal frame members and shells with nothing
    horizontal above them in plan (no higher shell over the middle of one, no higher beam within
    :data:`_COVER_DISTANCE` of it). Besides the main roof this takes in every higher roof (a stair
    cover, a lift machine room, an overhead-tank slab) and the main roof around them, but not the
    main roof's part under those rooms, nor the floors below."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    flat: list[tuple[int, float, np.ndarray, bool]] = []  # id, level, plan points, shell
    for e in _thermal_candidates(project):
        points = np.array([coords[n] for n in e["nodes"]])
        if points[:, 2].max() - points[:, 2].min() < _LEVEL_TOLERANCE:
            flat.append((e["id"], float(points[0, 2]), points[:, :2], e["type"] == "Shell"))
    if not flat:
        return set()
    levels = np.array([f[1] for f in flat])
    middles = np.array([f[2].mean(axis=0) for f in flat])
    reach = np.array([0.0 if f[3] else _COVER_DISTANCE for f in flat])
    low = np.array([f[2].min(axis=0) for f in flat]) - reach[:, None] - _LEVEL_TOLERANCE
    high = np.array([f[2].max(axis=0) for f in flat]) + reach[:, None] + _LEVEL_TOLERANCE
    exposed: set[int] = set()
    for i, (element_id, level, _, _) in enumerate(flat):
        point = middles[i]
        above = np.flatnonzero(
            (levels > level + _LEVEL_TOLERANCE)
            & np.all(low <= point, axis=1)
            & np.all(high >= point, axis=1)
        )
        covered = False
        for j in above:
            _, _, plan, shell = flat[j]
            if shell:
                covered = _in_polygon(point, plan, _LEVEL_TOLERANCE)
            else:
                covered = _in_polygon(point, plan, _COVER_DISTANCE)  # a segment: its distance
            if covered:
                break
        if not covered:
            exposed.add(element_id)
    return exposed


def add_thermal_case(
    project: dict[str, Any],
    sections: dict[int, ThermalSection],
    options: ThermalOptions,
    roof_z: float | None = None,
    roof_elements: set[int] | None = None,
) -> ThermalCase:
    """Add the temperature case to an OpenSees Studio ``project`` (in place).

    Fills the load pattern named ``T`` (its nodal loads are replaced) or appends one, with its
    static analysis ``T: Temperature``; with rigid diaphragms in the model that analysis runs
    without them (``release_diaphragms``: a rigid diaphragm would hold the floors' expansion).
    ``sections``: the thermal data per section id. The roof: the horizontal elements of
    ``roof_elements`` (ids; e.g. :func:`exposed_elements`, every roof level of the building),
    else those at ``roof_z`` [m], by default the highest horizontal frame member or shell.
    Returns the case with the fixed-end forces to add back (:data:`SIDE_FILE`) and notes.
    """
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    section_of = {s["id"]: s for s in project.get("sections", [])}
    notes: list[str] = []

    def horizontal(nodes: list[int]) -> bool:
        heights = [coords[n][2] for n in nodes]
        return max(heights) - min(heights) < _LEVEL_TOLERANCE

    candidates = _thermal_candidates(project)
    if roof_elements is None and roof_z is None:
        tops = [coords[e["nodes"][0]][2] for e in candidates if horizontal(e["nodes"])]
        roof_z = max(tops) if tops else None

    def at_roof(element: dict[str, Any]) -> bool:
        nodes = element["nodes"]
        if not horizontal(nodes):
            return False
        if roof_elements is not None:
            return element["id"] in roof_elements
        return roof_z is not None and abs(coords[nodes[0]][2] - roof_z) < _LEVEL_TOLERANCE

    roof_levels = sorted(
        {round(float(coords[e["nodes"][0]][2]), 3) for e in candidates if at_roof(e)}
    )
    if roof_elements is not None and len(roof_levels) > 1:
        notes.append(
            "temperature: the roof is taken at "
            + ", ".join(f"{z:.2f}" for z in roof_levels)
            + " m (the horizontal members and slabs with nothing above them, so the roofs of "
            "stair or machine rooms and the main roof around them)"
        )

    nodal: dict[int, np.ndarray] = {}
    frames: dict[str, list[float]] = {}
    shells: dict[str, list[float]] = {}
    missing: list[str] = []
    for e in candidates:
        nodes = list(e["nodes"])
        roof = at_roof(e)
        uniform = options.uniform if (options.scope == "all" or roof) else 0.0
        gradient = options.gradient if roof else 0.0
        if not uniform and not gradient:
            continue
        section = section_of.get(e.get("section_id"), {})
        thermal = sections.get(e.get("section_id"))
        if thermal is None or not section.get("E"):
            missing.append(str(e.get("name") or e["id"]))
            continue
        if e["type"] == "ElasticBeamColumn":
            a, b = coords[nodes[0]], coords[nodes[1]]
            axes = np.array(local_axes(a, b, e.get("vecxz")))
            # The gradient is top minus bottom: the +z face is the top when local z points up.
            up = float(np.sign(axes[2][2])) if abs(axes[2][2]) > 1e-9 else 0.0
            f0 = frame_fixed_end_forces(
                section["E"],
                section["A"],
                section["Iy"],
                section["Iz"],
                thermal.alpha,
                uniform,
                gradient_z=up * gradient,
                depth_z=thermal.depth,
            )
            if gradient and up and not thermal.depth:
                notes.append(
                    f"{e.get('name')}: no section depth, its temperature gradient left out"
                )
            for k, node in enumerate(nodes):
                load = nodal.setdefault(node, np.zeros(6))
                load[:3] -= axes.T @ f0[6 * k : 6 * k + 3]
                load[3:] -= axes.T @ f0[6 * k + 3 : 6 * k + 6]
            frames[str(e["id"])] = [float(v) for v in f0]
        elif section.get("type") == "ElasticMembranePlateSection":
            corners = [coords[n] for n in nodes]
            n_t, m_t = plate_thermal_resultants(
                section["E"], section["nu"], section["h"], thermal.alpha, uniform, gradient
            )
            hot = np.array([0.0, 0.0, 1.0])  # the top face (gradient only on horizontal shells)
            for node, load in zip(
                nodes, shell_equivalent_loads(corners, n_t, m_t, hot), strict=True
            ):
                nodal.setdefault(node, np.zeros(6))[:] += load
            # In the shell's own axes the hotter face is +3 when its normal points up.
            m_own = _SHELL_MOMENT_SIGN * m_t * float(np.sign(shell_normal(corners) @ hot) or 1.0)
            shells[str(e["id"])] = [-n_t, -n_t, 0.0, -m_own, -m_own, 0.0, 0.0, 0.0]
        else:
            missing.append(str(e.get("name") or e["id"]))
    if missing:
        notes.append(
            f"temperature: {len(missing)} element(s) without α or an elastic section left out "
            f"({', '.join(sorted(missing)[:5])}{', ...' if len(missing) > 5 else ''})"
        )
    # A rigid diaphragm would hold every floor's members together in plan: a heated roof beam
    # would then carry the fully held force E·A·α·ΔTu and bend no column. The case is run
    # without the diaphragms instead (the engine's ``release_diaphragms``), the floors acting
    # through their own slabs and beams, so a heated floor expands and bends its columns.
    release = any(c.get("type") == "RigidDiaphragm" for c in project.get("mp_constraints", []))
    if release and frames | shells:
        notes.append(
            "temperature: the case T is analysed without the rigid floor diaphragms (the floors "
            "act through their slabs and beams), so a floor's expansion bends its columns"
        )

    pattern = next((p for p in project.get("load_patterns", []) if p.get("name") == CASE), None)
    if pattern is None:
        series = next(
            (s["id"] for s in project.get("time_series", []) if s.get("type") == "Linear"), None
        )
        if series is None:
            series = 1 + max((s["id"] for s in project.get("time_series", [])), default=0)
            project.setdefault("time_series", []).append(
                {"id": series, "name": "", "type": "Linear", "factor": 1.0}
            )
        pattern = {
            "id": 1 + max((p["id"] for p in project.get("load_patterns", [])), default=0),
            "name": CASE,
            "type": "Plain",
            "time_series_id": series,
            "nodal_loads": [],
            "element_loads": [],
        }
        project.setdefault("load_patterns", []).append(pattern)
    # The case owns its pattern: its nodal loads are replaced, never added to, so the loads
    # always match the fixed-end forces returned (a second call gives the same case).
    pattern["nodal_loads"] = [
        {"node_id": n, "forces": [round(float(v), 6) for v in f]} for n, f in sorted(nodal.items())
    ]
    analysis = next(
        (a for a in project.get("analyses", []) if pattern["id"] in a.get("pattern_ids", [])), None
    )
    if analysis is None:
        analysis = {
            "id": 1 + max((a["id"] for a in project.get("analyses", [])), default=0),
            "name": f"{CASE}: {CASE_TITLE}",
            "type": "Static",
            "pattern_ids": [pattern["id"]],
            "n_steps": 1,
            "load_factor_increment": 1.0,
            "system": "BandGeneral",
            "constraints": "Plain",
            "integrator": "LoadControl",
            "algorithm": "Linear",
            "test": "NormDispIncr",
            "tolerance": 1e-8,
            "max_iter": 25,
        }
        project.setdefault("analyses", []).append(analysis)
    if release:
        analysis["release_diaphragms"] = True
    else:
        analysis.pop("release_diaphragms", None)
    corrections = {
        "schema": 1,
        "case": CASE,
        "uniform": options.uniform,
        "gradient": options.gradient,
        "scope": options.scope,
        "roof": roof_levels[-1] if roof_levels else roof_z,
        "roofLevels": roof_levels,
        "frames": frames,
        "shells": shells,
    }
    return ThermalCase(pattern["id"], analysis["id"], corrections, notes)


# ───────────────────────────────── combinations ─────────────────────────────────


def strength_combinations_with_t() -> list[tuple[str, dict[str, float]]]:
    """BNBC 2020 Part 6 Sec 2.7.3.1 combination 2 with T, ``1.2(D + F + T) + 1.6(L + H) +
    0.5(Lr or R)``, for a rise (+T) and a fall (-T): (name, factors), ``D`` for the dead and
    superimposed dead cases as in :data:`saengine.library.bnbc.STRENGTH_COMBINATIONS`. T is not
    combined with wind or earthquake (combinations 3 to 7 have no T). The combination without T
    stays in the list ("effects of one or more loads not acting shall be investigated")."""
    return [
        (f"1.2D {sign} 1.2T + 1.6L + 0.5Lr", {"D": 1.2, CASE: s * 1.2, "L": 1.6, "Lr": 0.5})
        for sign, s in (("+", 1.0), ("-", -1.0))
    ]


def service_combinations_with_t(
    cases: set[str] | list[str] | dict[str, Any],
) -> list[tuple[str, dict[str, float]]]:
    """BNBC 2020 Part 6 Sec 2.7.2.1 combinations 2 and 4 with T, ``D + H + F + L + T`` and
    ``D + H + F + 0.75(L + T) + (Lr or R)``, for ±T, in the form of
    :func:`saengine.substructure.loads.service_combinations` (``D`` expanded to the dead cases
    present); empty without a T case."""
    cases = set(cases)
    dead = [c for c in ("D", "SD") if c in cases]
    if CASE not in cases or not dead:
        return []
    live = [c for c in ("L",) if c in cases]
    roof = [c for c in ("Lr",) if c in cases]
    result = []
    for sign, s in (("+", 1.0), ("-", -1.0)):
        factors = {**dict.fromkeys(dead, 1.0), **dict.fromkeys(live, 1.0), CASE: s}
        result.append((f"D{' + L' if live else ''} {sign} T", factors))
        factors = {
            **dict.fromkeys(dead, 1.0),
            **dict.fromkeys(live, 0.75),
            **dict.fromkeys(roof, 1.0),
            CASE: s * 0.75,
        }
        name = f"D + 0.75({'L ' if live else ''}{sign} T){' + Lr' if roof else ''}"
        result.append((name.replace("(+ T)", "T").replace("(- T)", "(-T)"), factors))
    return result


# ───────────────────────────────── reading back ─────────────────────────────────


def write_corrections(model_path: str | Path, corrections: dict[str, Any] | None) -> None:
    """Write (or, with None, remove) the fixed-end forces beside the model file."""
    path = Path(model_path).with_name(SIDE_FILE)
    if corrections is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(json.dumps(corrections), encoding="utf-8")


def load_corrections(model_path: str | Path) -> dict[str, Any] | None:
    """The fixed-end forces written beside the model file, if any."""
    path = Path(model_path).with_name(SIDE_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == 1 else None


def end_force_corrections(corrections: dict[str, Any] | None, case: str) -> dict[int, np.ndarray]:
    """What to add to the frame end forces (``localForce``, 12 values) of ``case``'s results:
    the fixed-end forces for the temperature case, nothing for any other."""
    if not corrections or case != corrections.get("case"):
        return {}
    return {int(k): np.asarray(v, dtype=float) for k, v in corrections.get("frames", {}).items()}


def shell_force_corrections(corrections: dict[str, Any] | None, case: str) -> dict[int, np.ndarray]:
    """What to add to each shell's section forces (N11 N22 N12 M11 M22 M12 Q13 Q23, at every
    integration point) of ``case``'s results."""
    if not corrections or case != corrections.get("case"):
        return {}
    return {int(k): np.asarray(v, dtype=float) for k, v in corrections.get("shells", {}).items()}
