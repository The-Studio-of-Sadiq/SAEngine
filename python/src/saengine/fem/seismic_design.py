"""Seismic design from the response spectrum (BNBC 2020 Part 6 Chapter 2).

The analysis model runs the response spectrum cases RX and RY (:mod:`saengine.fem.derive`: the
BNBC design spectrum, already reduced by R, CQC of the modes). OpenSees Studio's runner keeps
only their peak translations (combined and per mode), so the member forces are found here:

- **Modal forces.** For each mode k and direction d, the static response to the load
  ``f = ω_k² · M · u_k,d`` (``u_k,d`` the mode's signed peak displacement, Γ·φ·Sa/ω²) is exactly
  the mode's peak response, since K·φ = ω²·M·φ, provided K is the stiffness the modes came
  from: each case copies the RS case's section overrides (cracked lateral sections) and its
  modal case's gravity preload (P-Delta, the increment from the preload is reported). These
  static cases are run once with the
  runner, in ``<results>/rs-design`` (removed with the results when the analysis runs again),
  and their member end forces, shell forces and reactions are combined over the modes with the
  rule and correlation of the response spectrum case (CQC, Der Kiureghian), per component.
  BNBC 2020 Part 6 Sec 2.5.9.4 (p. 635): every response quantity is the combination of its
  modal values (SRSS or CQC; CQC where modes are closely spaced).
- **Scaling** (Sec 2.5.9.4, p. 635): where the dynamic base shear V_rs is less than 85 % of the
  equivalent static base shear V (Sec 2.5.7, the cases EX and EY the model already has), all
  the forces, but not the drifts, are multiplied by 0.85·V/V_rs. BNBC gives one fraction for
  regular and irregular buildings alike. With several towers on a podium each tower's shear at
  the podium top is checked the same way (:mod:`saengine.fem.towers`) and the building is scaled
  by the largest factor; the towers' own periods, drifts and torsion are in ``towers``.
- **Accidental torsion** (Sec 2.5.7.6.2, p. 630, eq. 6.2.43): ``M_ta,i = ±0.05·L_i·F_i`` at each
  level, ``F_i`` the equivalent static storey force, ``L_i`` the floor dimension perpendicular
  to the force, the same direction at every floor. With dynamic analysis BNBC either offsets
  the centres of mass in the dynamic model (then no amplification Ax is needed, Sec 2.5.9.4)
  or, as here, adds the static torsional moments: the cases AX (the moments of the X forces,
  mass shifted along Y) and AY, enveloped with ± and added to the scaled RS. Where both
  directions act together, the 5 % shift is applied in one direction only, the one that
  produces the greater effect (Sec 2.5.7.6.3, p. 631): both are combined, each as its own
  combination, and the design takes the larger. A shift along X moves the line of action of
  the Y forces only, so with EX + 0.3EY it gives 0.3·AY (and with 0.3EX + EY, 0.3·AX).
- **Torsional irregularity and Ax** (Sec 2.5.5.3.1(i), p. 617; Sec 2.5.7.6.2, p. 630, eq.
  6.2.44): with the static torsional moments the amplification Ax is required where the
  building is torsionally irregular in Category C or D. Each storey is checked at the two
  ends of the plan across the force: the storey drift (RS, scaled to the design force level,
  ± the torsion case) at one end over the average of the two ends, irregular above 1.2,
  extreme above 1.4. Where irregular, Ax = (δmax / 1.2·δavg)² (1 ≤ Ax ≤ 3.0), from the
  displacements of the level the same way; the largest Ax of the direction multiplies its
  torsion case everywhere (the case is linear in its moments, so this is ≥ Ax at each level:
  conservative), in the combinations and in the drift.
- **Orthogonal effects** (Sec 2.5.13.1(b), p. 645): Seismic Design Category D (and C with the
  non-parallel system irregularity, type V) is designed for 100 % of one direction plus 30 %
  of the other: E = ±(EX + 0.3EY) and ±(0.3EX + EY). Category B (and C otherwise) may take
  the directions one at a time (Sec 2.5.13.1(a)).
- **Signs.** Response spectrum results have no sign. The design uses ± the envelope with the
  gravity combination, every force component of a section at its peak (as ETABS does by
  default): conservative, as the components do not peak together. Columns and walls are
  checked at the corners (±N, ±My, ±Mz: 8 sign patterns, :func:`saengine.fem.combinations.
  variants`), beams the same way (where only ±M matters the extra patterns repeat).
- **Combinations** (Sec 2.7.3.1, p. 685, combinations 5 and 7, and Sec 2.5.13, p. 644): E =
  Eh + Ev in 1.2D + 1.0E + 1.0L, E = Eh − Ev in 0.9D + 1.0E (H is not modelled), with the
  vertical component Ev = 0.50·a_h·D, a_h = (2/3)·Z·S (Sec 2.5.13.2, pp. 645-646). The live
  load factor may be 0.5 for L ≤ 5.0 kN/m² except garages and assembly (Sec 2.7.3.1 exception
  1): taken from the project's own static earthquake combination. BNBC has no redundancy
  factor on E (ρ appears only in the drift limit) and asks for the overstrength factor Ω0
  only "where specifically required" (Sec 2.5.13.4, p. 646): not in the general combinations.
- **Drift** (Sec 2.5.9.4, p. 635 and Sec 2.5.7.7, p. 631): the RS displacements and drifts,
  unscaled, times Cd/I; each storey's drift is the modal combination of the modal drifts
  (not the difference of the combined peaks), at every plan position with a node at both
  levels (the largest, so the edges count: Sec 2.5.14.1, p. 647), plus the drift of the
  accidental torsion case, each direction with the Cd of its own systems. The allowable
  storey drift is the row of the pack's drift table (Table 6.2.21, p. 648: masonry
  cantilever walls, other masonry walls, 4 storeys or less with drift-tolerant finishes, all
  other structures) by occupancy category; Δa/ρ for moment frames in Category D (Sec
  2.5.14.1).
- **Diaphragm deflection** (Sec 2.5.14.2, p. 647): the floor's in-plane deflection relative to
  the rigid motion of its vertical elements, against the permissible deflection of the attached
  elements the engineer enters (the code gives no number).
- **Separation** (Sec 2.5.14.3, pp. 648-649): the largest computed displacement δx = Cd·δxe/I
  (Sec 2.5.7.7) against the gap to the property line and to the adjacent units (SRSS, × 0.7
  for the same floor levels), by the pack's ``seismic.separation``.
- **Site-specific study** (Sec 2.5.3.1, 2.5.4.3): S1 or S2 flagged by the soil report gives the
  pack's warning in the notes and the category of its assumed class (SE).
- **Other irregularities** (B12, :mod:`saengine.fem.irregularity`): the plan and vertical
  irregularities with the torsion rows above, whether dynamic analysis is required, the soft
  storeys; in the categories the pack names (C), non-parallel systems ask for 100 % + 30 %
  (Sec 2.5.13.1(b)).

Every value and clause reference comes from the code pack in force (its ``seismic`` table).

Units follow the model: m, N, N·m (the summary gives kN).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from saengine.codes import context as code_context

#: Folder of the modal-force run inside the analysis results folder.
RS_FOLDER = "rs-design"
#: The summary :func:`seismic_design` writes into :data:`RS_FOLDER`.
SUMMARY_FILE = "seismic-design.json"
SUMMARY_SCHEMA = "saengine.seismicDesign/1"

# The code values (the least scale of the response spectrum base shear, the accidental
# eccentricity, the orthogonal share, the mass participation, the torsional irregularity
# ratios and the limit of Ax, the moment frame systems) and the clause references all come
# from the code pack in force (its ``seismic`` table): see :func:`_seismic` and
# :func:`clauses`.


def _seismic() -> Any:
    """The ``seismic`` table of the code pack in force."""
    return code_context.table("seismic")


def clauses() -> dict[str, str]:
    """The clause references of the seismic results, from the code pack in force (its
    ``seismic.clauses``, each after the pack's name, e.g. "<code> Part 6 Sec 2.5.9.4")."""
    pack = code_context.current()
    code = pack.edition or pack.name
    return {key: f"{code} {text}" for key, text in _seismic().clauses.items()}


class _Clauses(dict):
    """``CLAUSES[key]``: the pack's clause reference, read when it is used (empty when the
    pack has none)."""

    def __getitem__(self, key: str) -> str:
        return clauses().get(key, "")

    def get(self, key: str, default: Any = "") -> Any:  # type: ignore[override]
        return clauses().get(key, default)


CLAUSES: dict[str, str] = _Clauses()


def moment_frame_systems() -> frozenset[str]:
    """Systems "comprised solely of moment frames" (the pack's ``momentFrame`` flag): Δa/ρ in
    Category D."""
    return frozenset(k for k, v in _seismic().systems.items() if v.momentFrame)


#: The envelope parts :class:`SeismicForces` gives: the scaled response spectrum in X and Y and
#: the accidental torsion cases of the X and Y forces (all peaks, ≥ 0).
PARTS = ("RX", "RY", "AX", "AY")
_AXES = {"X": 1, "Y": 2}


# ─────────────────────────────────────── options ───────────────────────────────────────


@dataclass
class SeismicOptions:
    """How the response spectrum is designed for (the settings the integrator adds; see
    :func:`options_from_settings`)."""

    #: "auto": 100 % + 30 % in Seismic Design Category D (Sec 2.5.13.1(b)); "always" (also for a
    #: Category C building with non-parallel systems, irregularity type V); "never".
    orthogonal: Literal["auto", "always", "never"] = "auto"
    #: Add the static accidental torsion cases AX, AY (Sec 2.5.7.6).
    accidentalTorsion: bool = True
    #: E = Eh ± Ev with Ev = 0.5·a_h·D on the dead loads (Sec 2.5.13, 2.5.13.2).
    verticalComponent: bool = True
    #: Live load factor of 1.2D + 1.0E + L; None: the project's static earthquake combination's.
    liveFactor: float | None = None
    #: Redundancy factor ρ of the drift limit Δa/ρ (moment frames, Category D): 1.0, or 1.3 for
    #: very low redundancy (Sec 2.5.14.1).
    redundancy: float = 1.0
    #: Sign patterns of the envelope: "corners" (±N, ±My, ±Mz: 8) or "plusMinus" (2).
    signs: Literal["corners", "plusMinus"] = "corners"


def options_from_settings(settings: Any) -> SeismicOptions:
    """The options from ``settings.analysis.seismicDesign*`` fields when the settings have them
    (the integrator adds them), else the defaults."""
    analysis = getattr(settings, "analysis", None)
    options = SeismicOptions()
    for name, key in (
        ("orthogonal", "seismicOrthogonal"),
        ("accidentalTorsion", "seismicAccidentalTorsion"),
        ("verticalComponent", "seismicVerticalComponent"),
        ("liveFactor", "seismicLiveFactor"),
        ("redundancy", "seismicRedundancy"),
        ("signs", "seismicSigns"),
    ):
        value = getattr(analysis, key, None)
        if value is not None:
            setattr(options, name, value)
    return options


def design_uses_spectrum(settings: Any) -> bool:
    """The settings ask for the earthquake design from the dynamic analysis
    (``analysis.seismicDesign`` "responseSpectrum", or "timeHistory", B19, which builds on the
    response spectrum run; absent: the static cases, as before)."""
    analysis = getattr(settings, "analysis", None)
    return getattr(analysis, "seismicDesign", "static") in ("responseSpectrum", "timeHistory")


def design_uses_time_history(settings: Any) -> bool:
    """The settings ask for the earthquake design from the linear time histories (B19)."""
    analysis = getattr(settings, "analysis", None)
    return getattr(analysis, "seismicDesign", "static") == "timeHistory"


# ─────────────────────────────────────── code values ───────────────────────────────────────


def scale_factor(v_static: float, v_dynamic: float, fraction: float | None = None) -> float:
    """``max(1, fraction·V / V_rs)`` (Sec 2.5.9.4): the factor on the response spectrum forces.
    1 without a dynamic or a static base shear."""
    if v_dynamic <= 0 or v_static <= 0:
        return 1.0
    share = _seismic().minimumScale if fraction is None else fraction
    return max(1.0, share * v_static / v_dynamic)


def zone_of(z: float | None) -> int | None:
    """The seismic zone (1-4) of a zone coefficient Z: the zone whose Z is nearest (zones of
    the code pack in force)."""
    if not z:
        return None
    zones = code_context.table("zoneCoefficients").zones
    return min(zones, key=lambda k: abs(zones[k] - z))


def seismic_design_category(zone: int | None, site_class: str, occupancy: str) -> str | None:
    """Table 6.2.18 (p. 617): "B", "C" or "D"; None without a zone. From the code pack in
    force (``seismic.designCategories``); a site class without a row takes the last row (SE)."""
    if zone is None:
        return None
    table = code_context.table("seismic").designCategories
    rows = table.bySiteClass
    site = table.aliases.get(site_class, site_class)
    row = rows.get(site) or rows.get("SE") or list(rows.values())[-1]
    group = table.occupancyGroups.get(occupancy) or next(iter(row))
    return row[group][int(zone) - 1]


def orthogonal_required(category: str | None, option: str = "auto") -> bool:
    """Whether 100 % + 30 % applies (Sec 2.5.13.1): Category D, or as the option says."""
    if option == "always":
        return True
    if option == "never":
        return False
    return category == "D"


def peak_ground_acceleration(settings: Any) -> float:
    """a_h = (2/3)·Z·S [g] (Sec 2.5.13.2, p. 646); 0 without Z."""
    from saengine.library.settings import code_pack, derived

    z = derived(settings)["Z"]
    if not z:
        return 0.0
    seismic = code_pack(settings).table("seismic")
    return seismic.pgaFactor * float(z) * seismic.siteClasses[settings.site.siteClass].S


def vertical_coefficient(settings: Any) -> float:
    """Ev / D = verticalFactor·a_h (the pack's; eq. 6.2.56, p. 645: 0.50)."""
    return _seismic().verticalFactor * peak_ground_acceleration(settings)


def drift_limit(
    occupancy: str,
    category: str | None = None,
    system: str = "",
    redundancy: float = 1.0,
    *,
    storeys: int | None = None,
    masonry: bool | None = None,
    cantilever: bool = False,
    tolerant: bool = False,
    moment_frames_only: bool | None = None,
) -> dict[str, Any]:
    """The allowable storey drift Δa / hsx and the row of the pack's drift table it comes from:
    ``{"ratio", "row", "label"}``. The first of ``seismic.driftLimits`` whose conditions hold
    (a masonry system, its walls cantilevered, at most ``maxStoreys`` storeys, finishes
    designed for the drift), else ``allowableDrift``; divided by ρ for systems of moment
    frames only in the pack's ``driftRedundancyCategories``."""
    table = _seismic()
    entry = table.systems.get(system)
    if masonry is None:
        masonry = bool(entry and entry.masonry)
    limits, row, label = table.allowableDrift, "other", table.allowableDriftLabel
    for candidate in table.driftLimits:
        if candidate.masonry is not None and candidate.masonry != masonry:
            continue
        if candidate.cantileverWalls is not None and candidate.cantileverWalls != cantilever:
            continue
        if candidate.maxStoreys is not None and (storeys is None or storeys > candidate.maxStoreys):
            continue
        if (
            candidate.driftTolerantFinishes is not None
            and candidate.driftTolerantFinishes != tolerant
        ):
            continue
        limits, row, label = candidate.limits, candidate.id, candidate.label
        break
    ratio = limits.get(occupancy, limits.get("II", next(iter(limits.values()))))
    if moment_frames_only is None:
        moment_frames_only = system in moment_frame_systems()
    if category in table.driftRedundancyCategories and moment_frames_only and redundancy > 0:
        ratio /= redundancy
    return {"ratio": ratio, "row": row, "label": label}


def allowable_drift_ratio(
    occupancy: str,
    category: str | None = None,
    system: str = "",
    redundancy: float = 1.0,
    **conditions: Any,
) -> float:
    """Δa / hsx (Table 6.2.21, p. 648; Δa/ρ, Sec 2.5.14.1, p. 647): :func:`drift_limit`'s
    ratio; without ``conditions`` the "all other structures" row (or the masonry rows of a
    masonry ``system``)."""
    return drift_limit(occupancy, category, system, redundancy, **conditions)["ratio"]


def settings_drift_limit(
    settings: Any,
    category: str | None = None,
    storeys: int | None = None,
    redundancy: float = 1.0,
) -> dict[str, Any]:
    """:func:`drift_limit` for the project: its occupancy, its systems in both directions
    (masonry when one is, moment frames only when all are), the cantilever masonry walls and
    the drift-tolerant finishes of its settings."""
    from saengine.library.settings import system_values

    by_axis = system_values(settings)
    return drift_limit(
        settings.occupancy.category,
        category,
        settings.seismic.system,
        redundancy,
        storeys=storeys,
        masonry=any(a["masonry"] for a in by_axis.values()),
        cantilever=bool(settings.seismic.cantileverMasonryWalls),
        tolerant=bool(settings.seismic.driftTolerantFinishes),
        moment_frames_only=all(a["momentFramesOnly"] for a in by_axis.values()),
    )


def height_limit_note(settings: Any, category: str | None, height: float) -> str | None:
    """A note when the building of ``height`` [m] is taller than the height limit of its
    systems in Seismic Design Category ``category`` (the most stringent of the systems of both
    directions, ``seismic.systemCombination``), else None."""
    from saengine.library.settings import system_values

    if category is None:
        return None
    worst: tuple[float, str] | None = None
    for axis in system_values(settings).values():
        limit = axis["heightLimits"].get(category)
        if limit is not None and limit > 0 and (worst is None or limit < worst[0]):
            worst = (float(limit), " + ".join(axis["names"]))
    if worst is None or height <= worst[0] + 1e-6:
        return None
    return (
        f"the building is {height:.1f} m tall, above the {worst[0]:g} m height limit of "
        f"{worst[1]} in Seismic Design Category {category} ({CLAUSES['systems']})"
    )


def combine(peaks: np.ndarray, omegas: list[float], damping: float | None, rule: str) -> np.ndarray:
    """Modal combination of signed modal values (first axis the mode) with the engine's rules
    (``opensees_studio.core.modal_combination``): CQC (Der Kiureghian) or SRSS."""
    from opensees_studio.core.modal_combination import combine_cqc, combine_srss, cqc_correlation

    peaks = np.asarray(peaks, dtype=float)
    if peaks.shape[0] == 0:
        return np.zeros(peaks.shape[1:])
    if rule.upper() == "CQC":
        zeta = damping if damping and damping > 0 else 0.05
        key = (tuple(float(w) for w in omegas), float(zeta))
        rho = _CQC_RHO.get(key)
        if rho is None:
            # The same modes are combined for every element and combination: the matrix once.
            rho = cqc_correlation(omegas, zeta)
            rho.setflags(write=False)
            if len(_CQC_RHO) > 16:
                _CQC_RHO.clear()
            _CQC_RHO[key] = rho
        return combine_cqc(peaks, rho)
    return combine_srss(peaks)


_CQC_RHO: dict[tuple[tuple[float, ...], float], np.ndarray] = {}
"""The CQC correlation matrices :func:`combine` made, by frequencies and damping."""


def modal_base_shear(modes: list[dict[str, Any]], damping: float | None, rule: str) -> float:
    """V_rs [N]: the modal base shears V_k = M_eff,k·Sa_k (all of one sign: Γ_k·L_k = M_eff,k)
    combined like the other responses (Sec 2.5.9.4)."""
    used = [m for m in modes if m.get("angular_frequency", 0) > 0]
    shears = np.array([m["effective_mass"] * m["sa_at_period"] for m in used])
    return float(combine(shears, [m["angular_frequency"] for m in used], damping, rule))


# ─────────────────────────────────────── the model ───────────────────────────────────────


def _pattern(project: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((p for p in project.get("load_patterns", []) if p.get("name") == name), None)


def static_storey_forces(project: dict[str, Any], case: str) -> list[dict[str, Any]]:
    """The equivalent static storey forces of ``case`` ("EX" or "EY") from its load pattern:
    ``[{"z", "force" (N), "nodes": {node: force}}]`` by level, bottom up."""
    pattern = _pattern(project, case)
    if pattern is None:
        return []
    axis = 0 if case == "EX" else 1
    coords = {n["id"]: n["coords"] for n in project.get("nodes", [])}
    levels: dict[float, dict[int, float]] = {}
    for load in pattern.get("nodal_loads", []):
        force = float(load["forces"][axis])
        if force and load["node_id"] in coords:
            z = round(float(coords[load["node_id"]][2]), 3)
            levels.setdefault(z, {})[load["node_id"]] = force
    return [
        {"z": z, "force": sum(nodes.values()), "nodes": nodes}
        for z, nodes in sorted(levels.items())
    ]


def torsion_loads(project: dict[str, Any], case: str) -> tuple[list[dict[str, Any]], list[dict]]:
    """Nodal loads of the accidental torsion case of ``case`` (Sec 2.5.7.6.2): at each level the
    moment M_ta = 0.05·L·F about the vertical, L the floor's extent perpendicular to the force,
    as forces ``w·α·(−dy, dx)`` on the level's loaded nodes (w their share of the storey force,
    proportional to their weight; d from the weighted centre, α = M / Σ w·r²): no net force,
    moment M. Returns (nodal loads, per level ``{"z", "force", "L", "moment"}``)."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    across = 1 if case == "EX" else 0
    loads: dict[int, np.ndarray] = {}
    levels = []
    for level in static_storey_forces(project, case):
        here = [xyz for xyz in coords.values() if abs(xyz[2] - level["z"]) < 1e-3]
        span = float(max(c[across] for c in here) - min(c[across] for c in here)) if here else 0.0
        moment = _seismic().accidentalEccentricity * span * abs(level["force"])
        levels.append({"z": level["z"], "force": level["force"], "L": span, "moment": moment})
        weights = {n: abs(f) for n, f in level["nodes"].items()}
        total = sum(weights.values())
        if not moment or not total:
            continue
        centre = sum(coords[n][:2] * w for n, w in weights.items()) / total
        polar = sum(w * float(np.sum((coords[n][:2] - centre) ** 2)) for n, w in weights.items())
        if polar <= 1e-12:
            node = next(iter(weights))
            loads.setdefault(node, np.zeros(6))[5] += moment
            continue
        alpha = moment / polar
        for n, w in weights.items():
            dx, dy = coords[n][:2] - centre
            loads.setdefault(n, np.zeros(6))[:2] += alpha * w * np.array([-dy, dx])
    nodal = [{"node_id": n, "forces": [float(v) for v in f]} for n, f in sorted(loads.items())]
    return nodal, levels


def _static_case(case_id: int, name: str) -> dict[str, Any]:
    from saengine.fem.derive import SOLVER

    # The analysis's own solver: a banded one runs out of memory on tall buildings (on 25
    # storeys OpenSees crashed and the design fell back to the static EX, EY).
    return {
        "id": case_id,
        "name": name,
        "type": "Static",
        "pattern_ids": [case_id],
        "n_steps": 1,
        "load_factor_increment": 1.0,
        "system": SOLVER,
        "constraints": "Plain",
        "integrator": "LoadControl",
        "algorithm": "Linear",
        "test": "NormDispIncr",
        "tolerance": 1e-8,
        "max_iter": 25,
    }


def spectrum_stiffness(
    project: dict[str, Any], case_id: int | None
) -> tuple[list[dict[str, Any]], list[int]]:
    """The stiffness the response spectrum case ``case_id`` of ``project`` was solved on, as the
    runner builds it: (its ``section_overrides`` — the runner applies the RS case's own
    overrides to the whole case, its modal analysis included, and not those of the modal case
    —, the ``preload_case_ids`` of its modal case — locked before the eigen analysis, P-Delta).
    ([], []) when the case is not found."""
    analyses = {a.get("id"): a for a in project.get("analyses", [])}
    rs = analyses.get(case_id)
    if rs is None:
        return [], []
    modal = analyses.get(rs.get("modal_case_id"), {})
    preloads = [int(i) for i in modal.get("preload_case_ids", []) or [] if i in analyses]
    return list(rs.get("section_overrides", []) or []), preloads


def diaphragm_rotations(
    project: dict[str, Any],
) -> dict[int, Callable[[dict[Any, Any]], float]]:
    """Per rigid diaphragm's retained node, a function giving the floor's rotation about Z from
    nodal translations ``{node: [ux, uy, ...]}`` (as the response spectrum's modal peaks, which
    carry no rotations): the floor is rigid in plan, so ``u_n = u_m + θ·(−dy, dx)`` and θ is the
    least-squares fit over its nodes (exact for a rigid floor)."""
    coords = {int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    found: dict[int, Callable[[dict[Any, Any]], float]] = {}
    for mp in project.get("mp_constraints", []) or []:
        if mp.get("type") != "RigidDiaphragm" or int(mp.get("perp_dir", 3)) != 3:
            continue
        master = int(mp["retained_node"])
        if master not in coords:
            continue
        arms = {
            int(n): coords[int(n)][:2] - coords[master][:2]
            for n in mp.get("constrained_nodes", [])
            if int(n) in coords
        }

        def theta(
            peaks: dict[Any, Any], master: int = master, arms: dict[int, np.ndarray] = arms
        ) -> float:
            def at(node: int) -> np.ndarray | None:
                u = peaks.get(node, peaks.get(str(node)))
                return None if u is None else np.asarray(u, dtype=float)[:2]

            base = at(master)
            if base is None:
                return 0.0
            top = bottom = 0.0
            for node, (dx, dy) in arms.items():
                u = at(node)
                if u is None:
                    continue
                du = u - base
                top += dx * du[1] - dy * du[0]
                bottom += dx * dx + dy * dy
            return top / bottom if bottom > 1e-12 else 0.0

        found[master] = theta
    return found


def modal_force_model(
    project: dict[str, Any], spectra: dict[str, dict[str, Any]], torsion: bool = True
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The analysis model with one static case per mode and direction (the load ω²·M·u_k,d that
    gives the mode's peak response) and, with ``torsion``, the accidental torsion cases AX, AY.
    ``spectra``: per direction ("X", "Y") ``{"case_id", "modes": [scalars], "peaks": [{node:
    u}]}`` from the response spectrum results. Each generated case is solved on the stiffness
    of its direction's RS case (:func:`spectrum_stiffness`: the same section overrides, e.g.
    cracked lateral sections, and the same gravity preload, P-Delta; a preloaded static case
    reports the increment from the preload, so the response stays the mode's peak); AX and AY
    take that of RX, RY (or of the other direction when one is missing). Returns (model, case
    map ``[{"id", "part", "mode"}]``); only the case map's ids are to be run."""
    model = {k: v for k, v in project.items() if k not in ("analyses", "load_patterns")}
    model["spectra"], model["ground_motions"] = [], []
    source = {a["id"]: a for a in project.get("analyses", [])}
    stiffness = {
        axis: spectrum_stiffness(project, data.get("case_id")) for axis, data in spectra.items()
    }
    # The preload cases (and their patterns and time series) are kept with their own ids.
    kept_cases: dict[int, dict[str, Any]] = {}
    for _, preloads in stiffness.values():
        for i in preloads:
            case = {
                k: v
                for k, v in source[i].items()
                if k not in ("preload_case_ids", "section_overrides")
            }
            kept_cases[i] = case
    pattern_ids = {int(p) for c in kept_cases.values() for p in c.get("pattern_ids", [])}
    kept_patterns = [p for p in project.get("load_patterns", []) if p.get("id") in pattern_ids]
    series_ids = {p.get("time_series_id") for p in kept_patterns}
    series = [s for s in project.get("time_series", []) if s.get("id") in series_ids]
    linear = max((int(s["id"]) for s in series), default=0) + 1
    model["time_series"] = [*series, {"id": linear, "name": "", "type": "Linear", "factor": 1.0}]
    first_pattern = max((int(p["id"]) for p in kept_patterns), default=0) + 1
    first_case = max(kept_cases, default=0) + 1
    masses = {
        n["id"]: np.asarray(n.get("mass", [0.0] * 6), dtype=float)[:6] for n in project["nodes"]
    }
    turns = diaphragm_rotations(project)
    patterns: list[dict[str, Any]] = list(kept_patterns)
    analyses: list[dict[str, Any]] = list(kept_cases.values())
    cases: list[dict[str, Any]] = []

    def add(name: str, nodal: list[dict[str, Any]], part: str, mode: int | None) -> None:
        pattern_id, case_id = first_pattern + len(cases), first_case + len(cases)
        patterns.append(
            {
                "id": pattern_id,
                "name": name,
                "type": "Plain",
                "time_series_id": linear,
                "nodal_loads": nodal,
                "element_loads": [],
            }
        )
        static = {**_static_case(case_id, name), "pattern_ids": [pattern_id]}
        axis = part[1]
        overrides, preloads = stiffness.get(axis) or next(iter(stiffness.values()), ([], []))
        if overrides:
            static["section_overrides"] = json.loads(json.dumps(overrides))
        if preloads:
            static["preload_case_ids"] = list(preloads)
        analyses.append(static)
        cases.append({"id": case_id, "part": part, "mode": mode})

    for axis, data in spectra.items():
        for index, (mode, peaks) in enumerate(zip(data["modes"], data["peaks"], strict=True)):
            omega = float(mode.get("angular_frequency", 0.0))
            nodal = []
            for node_id, u in sorted(peaks.items()):
                m = masses.get(int(node_id))
                if m is None or not np.any(m):
                    continue
                force = np.zeros(6)
                force[:3] = omega**2 * m[:3] * np.asarray(u, dtype=float)[:3]
                # The polar inertia lumped on a diaphragm's node turns with the floor: its
                # inertia moment I·θ (θ from the floor's translations, the peaks having none).
                if m[5] and int(node_id) in turns:
                    force[5] = omega**2 * m[5] * turns[int(node_id)](peaks)
                if np.any(force):
                    nodal.append({"node_id": int(node_id), "forces": [*map(float, force)]})
            if nodal:
                add(
                    f"R{axis}{index + 1}: mode {mode['mode_number']} in {axis}",
                    nodal,
                    f"R{axis}",
                    index,
                )
    if torsion:
        for axis in ("X", "Y"):
            nodal, _ = torsion_loads(project, f"E{axis}")
            if nodal:
                add(f"A{axis}: accidental torsion of E{axis}", nodal, f"A{axis}", None)
    model["load_patterns"], model["analyses"] = patterns, analyses
    return model, cases


def _run(model: dict[str, Any], folder: Path, ids: list[int] | None = None) -> Path:
    """Run every case of ``model`` with OpenSees Studio's runner (its own process, as the app)
    into ``folder/results``. Raises ``ValueError`` when the run fails."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "rs-design.osmodel"
    path.write_text(json.dumps(model), encoding="utf-8")
    out = folder / "results"
    run_ids = [str(i) for i in (ids if ids is not None else [a["id"] for a in model["analyses"]])]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONSAFEPATH": "1"}
    done = subprocess.run(
        [sys.executable, "-P", "-m", "opensees_studio.run", "--project", str(path)]
        + ["--cases", *run_ids, "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        cwd=str(folder),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if done.returncode != 0:
        # The runner's own error line when it wrote one; else the process stopped (OpenSees
        # crashed, e.g. out of memory), and stderr holds only its banners.
        errors = []
        for line in done.stdout.splitlines():
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("type") == "error":
                errors.append(str(message.get("message", "")))
        reason = errors[-1] if errors else f"OpenSees stopped (exit code {done.returncode})"
        raise ValueError(f"the response spectrum force run failed: {reason}")
    return out


def fundamental_periods(project: dict[str, Any], folder: Path | None = None) -> dict[str, Any]:
    """The fundamental period of the analysis model in X and in Y from its modal case (run on
    its own, on the stiffness the modal case has: cracked sections, P-Delta preload): per
    direction ``{"period" s, "mode", "massRatio"}``, the mode with the largest effective mass
    in that direction (BNBC 2020 Part 6 Sec 2.5.7.2 (a), p. 627: a structural dynamics
    procedure such as modal eigenvalue analysis). Raises ``ValueError`` when the model has no
    modal case or masses, or the run fails. ``folder``: where to run (a temporary folder by
    default)."""
    import tempfile

    from opensees_studio.services.result_store import load_manifest, load_results

    analyses = {a["id"]: a for a in project.get("analyses", [])}
    modal = next((a for a in analyses.values() if a.get("type") == "Modal"), None)
    if modal is None:
        raise ValueError("the model has no modal case")
    kept = [modal] + [analyses[i] for i in modal.get("preload_case_ids", []) or [] if i in analyses]
    model = {**project, "analyses": kept, "spectra": [], "ground_motions": []}
    model["load_patterns"] = [
        p for p in project.get("load_patterns", []) if p.get("type", "Plain") == "Plain"
    ]
    model["time_series"] = [s for s in project.get("time_series", []) if "record_id" not in s]
    # Every DOF with mass counts in the generalized mass, the polar inertia lumped on a
    # diaphragm's node (I·θ²) too, as in OpenSees Studio's mass participation.
    mass = {
        int(n["id"]): np.asarray(n.get("mass", [0.0] * 6), dtype=float)[:6]
        for n in project.get("nodes", [])
    }
    mass = {n: np.pad(m, (0, 6 - m.size)) for n, m in mass.items()}
    total = np.sum([m[:2] for m in mass.values()], axis=0) if mass else np.zeros(2)
    if not np.any(total[:2]):
        raise ValueError("the model has no masses")
    with tempfile.TemporaryDirectory(prefix="saengine-period-") as tmp:
        out = _run(model, Path(folder or tmp), [int(modal["id"])])
        results = None
        for entry in load_manifest(out)["cases"]:
            if entry.get("result_type") == "ModalResults" or int(entry["case_id"]) == modal["id"]:
                results = load_results(entry, out)
                break
        if results is None or not hasattr(results, "mode_shapes"):
            raise ValueError("the modal case gave no modes")
        best: dict[str, dict[str, Any]] = {}
        for k, period in enumerate(results.periods, start=1):
            shape = results.mode_shapes.get(k, {})
            vectors = {int(n): np.asarray(v, dtype=float)[:6] for n, v in shape.items()}
            vectors = {n: np.pad(v, (0, 6 - v.size)) for n, v in vectors.items()}
            generalized = sum(float(mass[n] @ (v * v)) for n, v in vectors.items() if n in mass)
            if generalized <= 0:
                continue
            for axis, name in ((0, "X"), (1, "Y")):
                gamma = sum(float(mass[n][axis] * v[axis]) for n, v in vectors.items() if n in mass)
                ratio = gamma**2 / generalized / float(total[axis] or 1.0)
                if ratio > best.get(name, {}).get("massRatio", -1.0):
                    best[name] = {"period": float(period), "mode": k, "massRatio": ratio}
    if set(best) != {"X", "Y"}:
        raise ValueError("no mode moves the building in X and in Y")
    return best


# ─────────────────────────────────────── the results ───────────────────────────────────────


def _spectra(out_dir: Path) -> dict[str, dict[str, Any]]:
    """The response spectrum results by direction: ``{"X": {"name", "rule", "damping",
    "modes", "peaks", "combined"}}``."""
    from opensees_studio.services.result_store import load_manifest, load_results

    found: dict[str, dict[str, Any]] = {}
    for entry in load_manifest(out_dir)["cases"]:
        if entry.get("result_type") != "ResponseSpectrumResults":
            continue
        axis = {1: "X", 2: "Y"}.get(int(entry.get("direction", 0)))
        if axis is None or axis in found:
            continue
        results = load_results(entry, out_dir)
        found[axis] = {
            "case_id": int(entry["case_id"]),
            "name": str(entry["case_name"]),
            "rule": str(entry.get("combination", "CQC")),
            "damping": entry.get("damping_ratio"),
            "modes": [dict(m) for m in entry["modes"]],
            "peaks": [m.modal_peak_disp for m in results.modes],
            "combined": results.combined_disp,
        }
    return found


def _expected_axes(project: dict[str, Any]) -> set[str]:
    """The directions of the model's response spectrum cases (what a finished run of all its
    cases has results for)."""
    found: set[str] = set()
    for case in project.get("analyses", []):
        if case.get("type") != "ResponseSpectrum":
            continue
        axis = {1: "X", 2: "Y"}.get(int(case.get("direction", 0) or 0))
        if axis:
            found.add(axis)
    return found


def expected_axes(project_path: str | Path) -> set[str]:
    """:func:`_expected_axes` of the analysis model at ``project_path`` (empty when unreadable)."""
    try:
        return _expected_axes(json.loads(Path(project_path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _manifest_axes(out_dir: Path) -> set[str]:
    """The directions of the response spectrum results listed in ``out_dir/manifest.json``."""
    from opensees_studio.services.result_store import load_manifest

    return {
        axis
        for entry in load_manifest(out_dir)["cases"]
        if entry.get("result_type") == "ResponseSpectrumResults"
        and (axis := {1: "X", 2: "Y"}.get(int(entry.get("direction", 0) or 0)))
    }


def _stamp(out_dir: Path, project_path: Path, torsion: bool) -> str:
    from saengine.fem.derive import model_stamp

    # The model without its meta: deriving it again to the same analysis keeps this run.
    model = model_stamp(Path(project_path).read_bytes()).encode()
    text = model + (out_dir / "manifest.json").read_bytes()
    # "2": the modal-force cases carry the RS case's stiffness (overrides, preload); "3": they
    # are solved with the analysis's solver.
    return hashlib.sha1(text + (b"T" if torsion else b"-") + b"3").hexdigest()


@dataclass
class SeismicForces:
    """The scaled response spectrum envelopes of the members (:data:`PARTS`), from the
    modal-force run. Every value is a peak (≥ 0); RX and RY are multiplied by the scale
    factors, AX and AY are the accidental torsion cases (absolute values)."""

    scale: dict[str, float]
    rules: dict[str, tuple[str, float | None, list[float]]]  # part -> (rule, damping, omegas)
    modal: dict[str, list[Any]]  # part -> StaticResults per mode (None for a zero case)
    torsion: dict[str, Any]  # part -> StaticResults
    #: R part -> per mode (as ``modal``) its lateral load ω²·M·u {node: global force [N]}.
    loads: dict[str, list[dict[int, np.ndarray]]] = field(default_factory=dict)
    heights: dict[int, float] = field(default_factory=dict)  # node -> z [m]
    _cache: dict[tuple[str, str, int], dict[str, np.ndarray]] = field(default_factory=dict)
    #: R part -> (node heights [m], per mode its loads [N, (nodes, 3)]), stacked once.
    _stacked: dict[str, tuple[np.ndarray, list[np.ndarray]]] = field(default_factory=dict)
    _shears: dict[float, dict[str, np.ndarray]] = field(default_factory=dict)

    def _loads_of(self, part: str) -> tuple[np.ndarray, list[np.ndarray]]:
        """The modes' lateral loads of an R part as arrays over its nodes (in a fixed order),
        with the nodes' heights: a storey cut is then a mask, not a loop over every node."""
        found = self._stacked.get(part)
        if found is None:
            modes = self.loads[part]
            nodes = sorted({n for mode in modes for n in mode})
            heights = np.array([self.heights.get(n, -np.inf) for n in nodes])
            zero = np.zeros(3)
            loads = [np.array([mode.get(n, zero) for n in nodes]).reshape(-1, 3) for mode in modes]
            found = self._stacked[part] = (heights, loads)
        return found

    def storey_shear(self, cut: float) -> dict[str, np.ndarray]:
        """The scaled response spectrum storey shear [N, global X Y Z, ≥ 0] at the height
        ``cut`` [m], per R part: in each mode the sum of its lateral loads above the cut (the
        storey shear of that mode, one consistent sign), combined over the modes like the other
        responses. The peak of the sum, not the sum of the members' peaks, so it matches the
        combined drift of the storey (for its stability index Q). The torsion cases add no
        storey shear (moments only)."""
        if cut in self._shears:
            return dict(self._shears[cut])
        out: dict[str, np.ndarray] = {}
        for part in self.loads:
            if part not in self.rules:
                continue
            rule, damping, omegas = self.rules[part]
            heights, loads = self._loads_of(part)
            above = heights > cut
            rows = [mode[above].sum(axis=0) for mode in loads]
            out[part] = self.scale[part[1]] * combine(
                np.array(rows).reshape(-1, 3), omegas, damping, rule
            )
        self._shears[cut] = out
        return dict(out)

    @property
    def parts(self) -> list[str]:
        return [p for p in PARTS if p in self.modal or p in self.torsion]

    def _envelope(
        self, kind: str, key: int, value: Any, values: Any = None
    ) -> dict[str, np.ndarray]:
        """``value(results)`` of each mode combined per part; ``values(modes)``, when given,
        gives them for a part's modes at once (the same rows)."""
        cached = self._cache.get((kind, "", key))
        if cached is not None:
            return cached
        out: dict[str, np.ndarray] = {}
        for part, results in self.modal.items():
            rule, damping, omegas = self.rules[part]
            rows = list(values(results)) if values is not None else [value(r) for r in results]
            out[part] = self.scale[part[1]] * combine(np.array(rows), omegas, damping, rule)
        for part, results in self.torsion.items():
            out[part] = np.abs(value(results))
        self._cache[(kind, "", key)] = out
        return out

    def frame(self, element: Any) -> dict[str, np.ndarray]:
        """Section forces N, Vy, Vz, T, My, Mz at the stations of a frame element
        (:class:`saengine.fem.display._Element`), shape (STATIONS, 6), per part."""
        from saengine.fem.display import _last, element_section_forces, element_section_forces_many

        def modes(results: list[Any]) -> Any:
            # Every mode at once (element_section_forces, the same arithmetic).
            if not results or not element.length > 0:
                return [
                    element_section_forces(
                        element, _last(r.element_forces, element.id, 12), np.zeros(3)
                    )
                    for r in results
                ]
            return element_section_forces_many(
                np.full(len(results), float(element.length)),
                np.array([_last(r.element_forces, element.id, 12) for r in results]),
                np.zeros((len(results), 3)),
            )

        return self._envelope(
            "frame",
            element.id,
            lambda r: element_section_forces(
                element, _last(r.element_forces, element.id, 12), np.zeros(3)
            ),
            modes,
        )

    def end_forces(self, element_id: int) -> dict[str, np.ndarray]:
        """The 12 local end forces of an element, per part."""
        from saengine.fem.display import _last

        return self._envelope("ends", element_id, lambda r: _last(r.element_forces, element_id, 12))

    def shell(self, element_id: int) -> dict[str, np.ndarray]:
        """N11 N22 N12 M11 M22 M12 Q13 Q23 at each integration point, shape (n, 8), per part."""

        def rows(r: Any) -> np.ndarray:
            data = r.shell_forces.get(element_id)
            if data is None or not len(data):
                return np.zeros((1, 8))
            return np.asarray(data[-1], dtype=float).reshape(-1, 8)

        return self._envelope("shell", element_id, rows)

    def reaction(self, node_id: int) -> dict[str, np.ndarray]:
        """Fx Fy Fz Mx My Mz of a support, per part."""
        from saengine.fem.display import _last

        return self._envelope("reaction", node_id, lambda r: _last(r.node_reaction, node_id, 6))

    def displacement(self, node_id: int) -> dict[str, np.ndarray]:
        """Ux Uy Uz Rx Ry Rz of a node, per part, scaled like the forces (for the stability
        index of a storey, its drift over its shear; the design drift is
        :func:`storey_drifts`, unscaled)."""
        from saengine.fem.display import _last

        return self._envelope("disp", node_id, lambda r: _last(r.node_disp, node_id, 6))


def load_seismic_forces(out_dir: str | Path) -> SeismicForces | None:
    """The envelopes of the last :func:`seismic_design` run of these results, or None when it
    has not run. No stamp check here: :func:`seismic_design` (run) re-runs a stale folder and
    removes it before it does, so after a failed re-run nothing stale is left to load."""
    from opensees_studio.services.result_store import load_manifest, load_results

    folder = Path(out_dir) / RS_FOLDER
    try:
        summary = json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8"))
        manifest = load_manifest(folder / "results")
    except (OSError, ValueError):
        return None
    if summary.get("schema") != SUMMARY_SCHEMA or not summary.get("available"):
        return None
    info = summary.get("run")
    if not info:
        return None
    # A run made from other response spectrum results (another set of directions) is stale.
    try:
        current = _manifest_axes(Path(out_dir))
    except (OSError, ValueError, KeyError):
        return None
    if {p[1] for p in info["parts"] if p.startswith("R")} != current:
        return None
    by_id = {int(e["case_id"]): e for e in manifest["cases"]}
    modal: dict[str, list[Any]] = {}
    torsion: dict[str, Any] = {}
    rules: dict[str, tuple[str, float | None, list[float]]] = {}
    for part, spec in info["parts"].items():
        if part.startswith("A"):
            entry = by_id.get(int(spec["case"]))
            if entry is not None:
                torsion[part] = load_results(entry, folder / "results")
            continue
        results = [load_results(by_id[int(c)], folder / "results") for c in spec["cases"]]
        modal[part] = results
        rules[part] = (spec["rule"], spec["damping"], spec["omegas"])
    scale = {"X": float(summary["scale"]["x"]), "Y": float(summary["scale"]["y"])}
    loads: dict[str, list[dict[int, np.ndarray]]] = {}
    heights: dict[int, float] = {}
    try:
        model = json.loads((folder / "rs-design.osmodel").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        model = None
    if model is not None:
        heights = {int(n["id"]): float(n["coords"][2]) for n in model.get("nodes", [])}
        patterns = {int(p["id"]): p for p in model.get("load_patterns", [])}
        cases = {int(a["id"]): a for a in model.get("analyses", [])}
        for part, spec in info["parts"].items():
            if part.startswith("A"):
                continue
            per_mode = []
            for case_id in spec["cases"]:
                mode: dict[int, np.ndarray] = {}
                for pid in cases.get(int(case_id), {}).get("pattern_ids", []):
                    for load in patterns.get(int(pid), {}).get("nodal_loads", []):
                        f = np.asarray(load["forces"][:3], dtype=float)
                        node = int(load["node_id"])
                        mode[node] = mode.get(node, np.zeros(3)) + f
                per_mode.append(mode)
            loads[part] = per_mode
    forces = SeismicForces(
        scale=scale, rules=rules, modal=modal, torsion=torsion, loads=loads, heights=heights
    )
    # B19: the time-history parts when the design uses them (saengine.fem.linear_time_history).
    history = summary.get("timeHistory") or {}
    if history.get("use") and history.get("parts") and model is not None:
        from saengine.fem.linear_time_history import TimeHistoryForces

        model_file = Path(str(history.get("modelFile") or ""))
        try:
            project = json.loads(model_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return forces
        return TimeHistoryForces(
            forces, out_dir, project, model_file.parent, history,
            [float(v) for v in history.get("levels") or []], float(_seismic().orthogonalShare),
        )  # fmt: skip
    return forces


# ─────────────────────────────────────── drift ───────────────────────────────────────


def storey_drifts(
    project: dict[str, Any],
    spectra: dict[str, dict[str, Any]],
    levels: list[float],
    amplification: float | dict[str, float],
    allowable: float,
    torsion: dict[str, Any] | None = None,
    torsion_factor: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Design storey drifts from the response spectrum: per direction and storey, the largest
    over the plan positions with a node at both levels of Cd/I·(Δ_rs + Ax·|Δ_torsion|) (Cd/I
    one value, or by direction), Δ_rs
    the modal combination of the modal drifts (unscaled: Sec 2.5.9.4), Ax the direction's
    ``torsion_factor`` (default 1). Heights and drifts in m."""
    at_level = _positions(project, levels)
    rows = []
    for axis, data in spectra.items():
        a = _AXES[axis] - 1
        used = [k for k, m in enumerate(data["modes"]) if m.get("angular_frequency", 0) > 0]
        omegas = [data["modes"][k]["angular_frequency"] for k in used]
        twist = (torsion or {}).get(f"A{axis}")
        factor = float((torsion_factor or {}).get(axis, 1.0))
        amp = float(amplification[axis] if isinstance(amplification, dict) else amplification)
        for k in range(1, len(levels)):
            height = levels[k] - levels[k - 1]
            if height <= 0:
                continue
            best: dict[str, Any] | None = None
            for position, top in at_level[k].items():
                bottom = at_level[k - 1].get(position)
                if bottom is None:
                    continue
                modal = np.array(
                    [
                        float(
                            np.asarray(data["peaks"][i].get(top, np.zeros(3)))[a]
                            - np.asarray(data["peaks"][i].get(bottom, np.zeros(3)))[a]
                        )
                        for i in used
                    ]
                )
                elastic = float(combine(modal, omegas, data["damping"], data["rule"]))
                extra = 0.0
                if twist is not None:
                    from saengine.fem.display import _last

                    extra = factor * abs(
                        float(
                            _last(twist.node_disp, top, 6)[a] - _last(twist.node_disp, bottom, 6)[a]
                        )
                    )
                design = amp * (elastic + extra)
                if best is None or design > best["designDrift"]:
                    best = {
                        "direction": axis,
                        "bottom": round(levels[k - 1], 3),
                        "top": round(levels[k], 3),
                        "height": round(height, 3),
                        "position": [position[0] / 1e3, position[1] / 1e3],
                        "elasticDrift": elastic,
                        "torsionDrift": extra,
                        "designDrift": design,
                    }
            if best is not None:
                best["ratio"] = best["designDrift"] / height
                best["allowableRatio"] = allowable
                best["ok"] = bool(best["ratio"] <= allowable + 1e-12)
                rows.append(best)
    return rows


def _positions(project: dict[str, Any], levels: list[float]) -> list[dict[tuple[int, int], int]]:
    """Per level, the nodes at it by plan position (x, y in mm)."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    at_level: list[dict[tuple[int, int], int]] = []
    for z in levels:
        here = {}
        for node_id, xyz in coords.items():
            if abs(xyz[2] - z) < 1e-3:
                here[(round(xyz[0] * 1e3), round(xyz[1] * 1e3))] = node_id
        at_level.append(here)
    return at_level


# ─────────────────────────────── diaphragm deflection, separation ───────────────────────────────


def _amp(amplification: float | dict[str, float], axis: str) -> float:
    return float(amplification[axis] if isinstance(amplification, dict) else amplification)


def _modal_values(data: dict[str, Any], nodes: list[int], a: int) -> tuple[np.ndarray, list]:
    """The signed modal peaks of ``nodes`` in direction ``a`` (modes × nodes) and the
    frequencies of the modes used."""
    used = [k for k, m in enumerate(data["modes"]) if m.get("angular_frequency", 0) > 0]
    omegas = [data["modes"][k]["angular_frequency"] for k in used]
    values = np.array(
        [[float(np.asarray(data["peaks"][k].get(n, np.zeros(3)))[a]) for n in nodes] for k in used]
    ).reshape(len(used), len(nodes))
    return values, omegas


def diaphragm_deflections(
    project: dict[str, Any],
    spectra: dict[str, dict[str, Any]],
    levels: list[float],
    amplification: float | dict[str, float],
    limit_mm: float | None = None,
) -> list[dict[str, Any]]:
    """The in-plane deflection of each floor diaphragm (Sec 2.5.14.2, p. 647; Sec 1.7.3.8):
    per direction and level, the largest displacement of a floor node relative to the rigid
    motion (two translations and a rotation, least squares) of the floor's nodes on vertical
    elements (columns, walls, braces reaching below the floor), each mode on its own, combined over the modes
    like the drifts and times Cd/I. A rigid diaphragm gives none. ``limit_mm``: the permissible
    deflection of the attached elements (the code gives no number), else no verdict. Rows
    ``{"direction", "level", "deflection" m, "position" [x, y] m, "limit" m | None, "ok"}``,
    only for floors with nodes off the vertical elements."""
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    at_level = _positions(project, levels)
    limit = None if limit_mm is None else float(limit_mm) / 1e3
    pack_limit = _seismic().diaphragmDeflection.limit
    if limit is None and pack_limit is not None:
        limit = float(pack_limit) / 1e3
    # Nodes on vertical elements: an element of theirs reaches below them (columns, walls).
    vertical: set[int] = set()
    for element in project.get("elements", []):
        ids = [int(n) for n in element.get("nodes", []) if int(n) in coords]
        if len(ids) < 2:
            continue
        bottom = min(coords[n][2] for n in ids)
        vertical.update(n for n in ids if coords[n][2] > bottom + 1e-3)
    rows: list[dict[str, Any]] = []
    for k in range(1, len(levels)):
        here = at_level[k]
        supports = [p for p, n in here.items() if n in vertical]
        if len(supports) < 2 or len(here) <= len(supports):
            continue
        positions = list(here)
        nodes = [here[p] for p in positions]
        xy = np.array([coords[n][:2] for n in nodes])
        centre = xy.mean(axis=0)
        index = {p: i for i, p in enumerate(positions)}
        s = [index[p] for p in supports]
        # Rigid motion u = (tx − θ·dy, ty + θ·dx) fitted to the supports' (ux, uy).
        d = xy[s] - centre
        fit = np.zeros((2 * len(s), 3))
        fit[0::2, 0], fit[0::2, 2] = 1.0, -d[:, 1]
        fit[1::2, 1], fit[1::2, 2] = 1.0, d[:, 0]
        solve = np.linalg.pinv(fit)
        dall = xy - centre
        for axis, data in spectra.items():
            ux, omegas = _modal_values(data, nodes, 0)
            uy, _ = _modal_values(data, nodes, 1)
            if not omegas:
                continue
            b = np.empty((ux.shape[0], 2 * len(s)))
            b[:, 0::2], b[:, 1::2] = ux[:, s], uy[:, s]
            params = b @ solve.T  # modes × (tx, ty, θ)
            a = _AXES[axis] - 1
            rigid = (
                params[:, 0:1] - params[:, 2:3] * dall[:, 1]
                if a == 0
                else params[:, 1:2] + params[:, 2:3] * dall[:, 0]
            )
            own = (ux if a == 0 else uy) - rigid
            combined = np.abs(combine(own, omegas, data["damping"], data["rule"]))
            worst = int(np.argmax(combined))
            value = _amp(amplification, axis) * float(combined[worst])
            if value < 1e-7:  # a rigid diaphragm: no in-plane deflection
                continue
            rows.append(
                {
                    "direction": axis,
                    "level": round(levels[k], 3),
                    "deflection": value,
                    "position": [positions[worst][0] / 1e3, positions[worst][1] / 1e3],
                    "limit": limit,
                    "ok": None if limit is None else bool(value <= limit + 1e-12),
                }
            )
    return rows


def diaphragm_notes(rows: list[dict[str, Any]], limit_mm: float | None) -> list[str]:
    """The notes of :func:`diaphragm_deflections`: the failures, or the largest deflection
    when there is no permissible deflection to check it with."""
    if not rows:
        return []
    clause = CLAUSES["diaphragmDeflection"]
    worst = max(rows, key=lambda r: r["deflection"])
    failing = [r for r in rows if r["ok"] is False]
    if failing:
        bad = max(failing, key=lambda r: r["deflection"])
        return [
            (
                f"diaphragm in-plane deflection {1e3 * bad['deflection']:.1f} mm in "
                f"{bad['direction']} at {bad['level']:g} m exceeds the permissible "
                f"{1e3 * bad['limit']:.1f} mm of the attached elements ({clause})"
            )
        ]
    if worst["limit"] is None and worst["deflection"] > 1e-4:
        return [
            (
                f"diaphragm in-plane deflection up to {1e3 * worst['deflection']:.1f} mm "
                f"({worst['direction']} at {worst['level']:g} m): enter the permissible deflection "
                f"of the attached elements (Project Settings, Seismic) to check it ({clause})"
            )
        ]
    return []


def level_displacements(
    project: dict[str, Any],
    spectra: dict[str, dict[str, Any]],
    levels: list[float],
    amplification: float | dict[str, float],
    torsion: dict[str, Any] | None = None,
    torsion_factor: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """The computed maximum horizontal displacement δx = Cd·δxe / I of each level (Sec
    2.5.7.7, Eq. 6.2.45): per direction the largest over the level's nodes of the modal
    combination (unscaled, as the drifts) plus Ax·|the accidental torsion case|. Rows
    ``{"level", "X", "Y"}`` [m], bottom up from the first level above the base."""
    at_level = _positions(project, levels)
    rows: list[dict[str, Any]] = []
    for k in range(1, len(levels)):
        nodes = list(at_level[k].values())
        if not nodes:
            continue
        row: dict[str, Any] = {"level": round(levels[k], 3), "X": 0.0, "Y": 0.0}
        for axis, data in spectra.items():
            a = _AXES[axis] - 1
            values, omegas = _modal_values(data, nodes, a)
            if not omegas:
                continue
            elastic = np.abs(combine(values, omegas, data["damping"], data["rule"]))
            twist = (torsion or {}).get(f"A{axis}")
            if twist is not None:
                from saengine.fem.display import _last

                factor = float((torsion_factor or {}).get(axis, 1.0))
                elastic = elastic + factor * np.array(
                    [abs(float(_last(twist.node_disp, n, 6)[a])) for n in nodes]
                )
            row[axis] = _amp(amplification, axis) * float(np.max(elastic))
        rows.append(row)
    return rows


def separation_checks(
    project: dict[str, Any],
    spectra: dict[str, dict[str, Any]],
    levels: list[float],
    amplification: float | dict[str, float],
    settings: Any,
    torsion: dict[str, Any] | None = None,
    torsion_factor: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Separation from adjacent structures (Sec 2.5.14.3 (i)-(iii), pp. 648-649) by the pack's
    ``seismic.separation``: to the property line at least δmax (the building's largest
    computed displacement, either direction, :func:`level_displacements`); to a unit of the
    same property the SRSS of the two δmax; times the reduction where the floor levels are the
    same. ``{"displacements": rows, "maxDisplacement" m, "checks": [{"name", "gap" m,
    "required" m, "basis", "ok"}], "notes"}``."""
    rule = _seismic().separation
    clause = CLAUSES["separation"]
    rows = level_displacements(project, spectra, levels, amplification, torsion, torsion_factor)
    delta = max((max(r["X"], r["Y"]) for r in rows), default=0.0)
    seismic = settings.seismic
    checks: list[dict[str, Any]] = []
    if seismic.propertyLineGap is not None:
        required = rule.propertyLineFactor * delta
        checks.append(
            {
                "name": "property line",
                "gap": seismic.propertyLineGap / 1e3,
                "required": required,
                "basis": "δmax of this building",
                "ok": bool(seismic.propertyLineGap / 1e3 >= required - 1e-9),
            }
        )
    for other in seismic.adjacent:
        theirs = other.displacement / 1e3
        if other.sameProperty:
            required = math.hypot(delta, theirs) if rule.sameProperty == "srss" else delta + theirs
            basis = "SRSS of the two δmax" if rule.sameProperty == "srss" else "sum of the two δmax"
        else:
            required = rule.propertyLineFactor * delta
            basis = "δmax of this building to the property line"
        if other.sameFloorLevels and rule.equalFloorLevelsFactor < 1:
            required *= rule.equalFloorLevelsFactor
            basis += f", × {rule.equalFloorLevelsFactor:g} (same floor levels)"
        checks.append(
            {
                "name": other.name,
                "gap": other.gap / 1e3,
                "required": required,
                "basis": basis,
                "ok": bool(other.gap / 1e3 >= required - 1e-9),
            }
        )
    notes = [
        f"separation from {c['name']}: {1e3 * c['gap']:.0f} mm is less than the "
        f"{1e3 * c['required']:.0f} mm required ({c['basis']}; {clause})"
        for c in checks
        if not c["ok"]
    ]
    if not checks and delta > 0:
        notes.append(
            f"largest computed displacement δmax = {1e3 * delta:.0f} mm "
            f"({CLAUSES['displacement']}): enter the gap to the property line and the "
            f"adjacent structures (Project Settings, Seismic) to check the separation ({clause})"
        )
    return {"displacements": rows, "maxDisplacement": delta, "checks": checks, "notes": notes}


def diaphragm_rows(summary: dict[str, Any]) -> list[list[str]]:
    """The diaphragm deflections of a :func:`seismic_design` summary as report rows:
    direction, level [m], deflection [mm], permissible [mm], result."""
    out = []
    for r in summary.get("diaphragmDeflection") or []:
        out.append(
            [
                r["direction"],
                f"{r['level']:g}",
                f"{1e3 * r['deflection']:.2f}",
                "–" if r["limit"] is None else f"{1e3 * r['limit']:.1f}",
                "–" if r["ok"] is None else "OK" if r["ok"] else "FAIL",
            ]
        )
    return out


def separation_rows(summary: dict[str, Any]) -> list[list[str]]:
    """The separation checks of a :func:`seismic_design` summary as report rows: to, gap
    [mm], required [mm], basis, result."""
    sep = summary.get("separation") or {}
    return [
        [
            str(c["name"]),
            f"{1e3 * c['gap']:.0f}",
            f"{1e3 * c['required']:.0f}",
            str(c["basis"]),
            "OK" if c["ok"] else "FAIL",
        ]
        for c in sep.get("checks", [])
    ]


def torsional_irregularity(
    project: dict[str, Any],
    spectra: dict[str, dict[str, Any]],
    levels: list[float],
    scale: dict[str, float] | None = None,
    torsion: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The torsional irregularity check of each storey and direction (Sec 2.5.5.3.1(i), p. 617)
    and the amplification Ax of its top level (eq. 6.2.44, p. 630), computed with Ax = 1.

    The two ends of the plan are the lines of plan positions (with a node at both levels) at
    the smallest and the largest coordinate across the force. At every position the response
    is the modal combination of the RS modal values, times the direction's ``scale`` (the
    design force level, as the torsion case), plus s·(the signed torsion case ``A<axis>``), s
    = ±1 (the 5 % either way); an end takes its largest position. ``ratio`` = Δmax / Δavg of
    the storey drifts (the larger over s); ``amplification`` = (δmax / 1.2·δavg)² of the
    displacements of the top level, clamped to [1, 3.0]. Rows ``{"direction", "bottom",
    "top", "driftMax", "driftAvg", "ratio", "irregular", "extreme", "displacementMax",
    "displacementAvg", "amplification"}`` (m); storeys with a single line of positions across
    the force (a plane frame) are skipped."""
    from saengine.fem.display import _last

    at_level = _positions(project, levels)
    rows = []
    for axis, data in spectra.items():
        a = _AXES[axis] - 1
        across = 1 - a
        used = [k for k, m in enumerate(data["modes"]) if m.get("angular_frequency", 0) > 0]
        omegas = [data["modes"][k]["angular_frequency"] for k in used]
        factor = float((scale or {}).get(axis, 1.0))
        twist = (torsion or {}).get(f"A{axis}")

        peaks = [data["peaks"][i] for i in used]

        def modal(node: int | None, a: int = a, peaks: list[Any] = peaks) -> np.ndarray:
            if node is None:
                return np.zeros(len(peaks))
            return np.array([float(np.asarray(p.get(node, np.zeros(3)))[a]) for p in peaks])

        def turned(node: int | None, a: int = a, twist: Any = twist) -> float:
            if twist is None or node is None:
                return 0.0
            return float(_last(twist.node_disp, node, 6)[a])

        for k in range(1, len(levels)):
            pairs = {
                p: (at_level[k - 1].get(p), top)
                for p, top in at_level[k].items()
                if at_level[k - 1].get(p) is not None
            }
            if not pairs:
                continue
            low = min(p[across] for p in pairs)
            high = max(p[across] for p in pairs)
            if high - low < 1:
                continue
            ends = [[p for p in pairs if abs(p[across] - edge) <= 1] for edge in (low, high)]
            best: dict[str, Any] | None = None
            for s in (1.0, -1.0):
                drift_ends, disp_ends = [], []
                for end in ends:
                    drifts, disps = [], []
                    for p in end:
                        bottom, top = pairs[p]
                        rs_drift = combine(
                            modal(top) - modal(bottom), omegas, data["damping"], data["rule"]
                        )
                        rs_disp = combine(modal(top), omegas, data["damping"], data["rule"])
                        drifts.append(factor * float(rs_drift) + s * (turned(top) - turned(bottom)))
                        disps.append(factor * float(rs_disp) + s * turned(top))
                    drift_ends.append(max(drifts))
                    disp_ends.append(max(disps))
                d_max, d_avg = max(drift_ends), sum(drift_ends) / 2
                u_max, u_avg = max(disp_ends), sum(disp_ends) / 2
                ratio = d_max / d_avg if d_avg > 1e-12 else 1.0
                if best is None or ratio > best["ratio"]:
                    amp = (
                        (u_max / (_seismic().torsionIrregular * u_avg)) ** 2
                        if u_avg > 1e-12
                        else 1.0
                    )
                    best = {
                        "direction": axis,
                        "bottom": round(levels[k - 1], 3),
                        "top": round(levels[k], 3),
                        "driftMax": d_max,
                        "driftAvg": d_avg,
                        "ratio": ratio,
                        "irregular": bool(ratio > _seismic().torsionIrregular + 1e-12),
                        "extreme": bool(ratio > _seismic().torsionExtreme + 1e-12),
                        "displacementMax": u_max,
                        "displacementAvg": u_avg,
                        "amplification": float(
                            min(_seismic().torsionAmplificationMax, max(1.0, amp))
                        ),
                    }
            if best is not None:
                rows.append(best)
    return rows


def torsion_amplification(
    rows: list[dict[str, Any]], category: str | None, torsion: bool = True
) -> dict[str, float]:
    """Ax per direction (eq. 6.2.44, p. 630): where a storey of the direction is torsionally
    irregular and the building is in Category C or D, the largest ``amplification`` of the
    direction's storeys, else 1 (also without the static torsion cases: then there is no
    accidental torsion moment to amplify)."""
    out = {"X": 1.0, "Y": 1.0}
    if not torsion or category not in ("C", "D"):
        return out
    for axis in out:
        mine = [r for r in rows if r["direction"] == axis]
        if any(r["irregular"] for r in mine):
            out[axis] = max(r["amplification"] for r in mine)
    return out


def _levels(project: dict[str, Any], given: list[float] | None) -> list[float]:
    """Storey levels [m]: the given ones, else the base (lowest node) and the levels of the
    equivalent static forces, else the elevations of the nodes with mass."""
    if given:
        return sorted(given)
    zs = [float(n["coords"][2]) for n in project.get("nodes", [])]
    if not zs:
        return []
    base = round(min(zs), 3)
    found = {lv["z"] for case in ("EX", "EY") for lv in static_storey_forces(project, case)}
    if not found:
        found = {
            round(float(n["coords"][2]), 3)
            for n in project["nodes"]
            if any(float(v) for v in (n.get("mass") or [0])[:2])
        }
    return sorted({base, *found})


# ─────────────────────────────────────── combinations ───────────────────────────────────────


def _live_factor(settings: Any, options: SeismicOptions) -> float:
    if options.liveFactor is not None:
        return float(options.liveFactor)
    for c in getattr(settings, "combinations", []):
        if (c.EX or c.EY) and c.D > 1.0:
            return float(c.L)
    return 1.0


def seismic_combinations(
    settings: Any,
    options: SeismicOptions,
    orthogonal: bool,
    torsion: bool,
    amplification: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """The strength combinations with the response spectrum E (Sec 2.7.3.1 combinations 5 and
    7, E = Eh ± Ev): ``[{"name", "loads": {case factors of a LoadCombination}, "envelope":
    {part: factor}, "clause"}]`` (:class:`saengine.fem.combinations.DesignCombination`).

    With ``torsion`` and 100 % + 30 %, each direction pair appears twice: with the 5 % shift
    across the principal force (AX with EX + 0.3EY) and with the shift along it (0.3·AY: the
    shift moves the line of action of the 30 % Y forces only), Sec 2.5.7.6.3: the design takes
    the one with the greater effect. ``amplification``: Ax per direction on its torsion case
    (:func:`torsion_amplification`, default 1)."""
    ev = vertical_coefficient(settings) if options.verticalComponent else 0.0
    live = _live_factor(settings, options)
    ax = {k: round(float(v), 4) for k, v in (amplification or {}).items()}
    tx, ty = ax.get("X", 1.0), ax.get("Y", 1.0)
    share = _seismic().orthogonalShare
    if orthogonal and torsion:
        directions = [
            ("EX + 0.3EY", {"RX": 1.0, "RY": share, "AX": tx}),
            ("0.3EX + EY", {"RX": share, "RY": 1.0, "AY": ty}),
            ("EX + 0.3EY, torsion of EY", {"RX": 1.0, "RY": share, "AY": round(share * ty, 4)}),
            ("0.3EX + EY, torsion of EX", {"RX": share, "RY": 1.0, "AX": round(share * tx, 4)}),
        ]
    elif orthogonal:
        directions = [
            ("EX + 0.3EY", {"RX": 1.0, "RY": share}),
            ("0.3EX + EY", {"RX": share, "RY": 1.0}),
        ]
    else:
        directions = [
            ("EX", {"RX": 1.0} | ({"AX": tx} if torsion else {})),
            ("EY", {"RY": 1.0} | ({"AY": ty} if torsion else {})),
        ]
    upper, lower = round(1.2 + ev, 4), round(0.9 - ev, 4)
    result = []
    for label, envelope in directions:
        live_text = f" + {live:.1f}L" if live else ""
        result.append(
            {
                "name": f"{upper:g}D{live_text} ± 1.0E(RS {label})",
                "loads": {"D": upper, "L": live},
                "envelope": envelope,
                "clause": f"{CLAUSES['combinations']} no. 5, E = Eh + Ev",
            }
        )
    for label, envelope in directions:
        result.append(
            {
                "name": f"{lower:g}D ± 1.0E(RS {label})",
                "loads": {"D": lower},
                "envelope": envelope,
                "clause": f"{CLAUSES['combinations']} no. 7, E = Eh − Ev",
            }
        )
    return result


# ─────────────────────────────────────── the design ───────────────────────────────────────


@code_context.in_project_pack(path_params=("project_path", "out_dir"))
def seismic_design(
    out_dir: str | Path,
    project_path: str | Path,
    settings: Any,
    options: SeismicOptions | None = None,
    levels: list[float] | None = None,
    run: bool = True,
) -> dict[str, Any]:
    """The response spectrum design values of an analysis run: ``{"available", "scale": {"x",
    "y", "vStatic": {"x", "y"}, "vDynamic": {"x", "y"}, "fraction", "clause"},
    "massParticipation": {"x", "y"}, "category", "orthogonal", "verticalCoefficient",
    "torsion": {"X": [levels], "Y": [...]}, "torsionalIrregularity": [rows of
    :func:`torsional_irregularity`], "torsionAmplification": {"X", "Y"}, "combinations": [...],
    "drift": [...], "notes"}``
    (base shears in kN, drift in m). With ``run``, the modal-force cases are run (once per
    analysis run; :func:`load_seismic_forces` then gives the member envelopes) and the summary
    is written to ``<out_dir>/rs-design/seismic-design.json``. ``levels``: the storey
    elevations [m] (default: from the model's equivalent static forces)."""
    from saengine.library.settings import derived

    out_dir, project_path = Path(out_dir), Path(project_path)
    options = options or options_from_settings(settings)
    project = json.loads(project_path.read_text(encoding="utf-8"))
    notes: list[str] = []
    folder = out_dir / RS_FOLDER

    def unavailable(note: str) -> dict[str, Any]:
        # With ``run``, a summary of earlier results must not outlive them: the design would
        # read its forces (``load_summary``) as if they were of these results.
        if run:
            shutil.rmtree(folder, ignore_errors=True)
        return {"schema": SUMMARY_SCHEMA, "available": False, "notes": [note]}

    # The stamp is taken BEFORE the spectra are read and checked again after: the app calls this
    # while the analysis runs, and the runner rewrites manifest.json as cases finish (a case run
    # in a fresh process even writes a manifest of its own case only), so results read from a
    # manifest that then changes must not be stamped with the later one.
    try:
        stamp_before = _stamp(out_dir, project_path, False) if run else None
    except (OSError, ValueError, KeyError):
        stamp_before = None
    memo_key = (
        (
            str(out_dir.resolve()),
            stamp_before,
            settings.model_dump_json(),
            repr(options),
            repr(levels),
        )
        if stamp_before is not None
        else None
    )
    known = _SUMMARY_MEMO
    if memo_key is not None and known is not None and known[0] == memo_key:
        try:
            if (folder / SUMMARY_FILE).stat().st_mtime_ns == known[1]:
                return copy.deepcopy(known[2])
        except OSError:
            pass
    try:
        spectra = _spectra(out_dir)
    except (OSError, ValueError, KeyError):
        spectra = {}
    if not spectra:
        return unavailable(
            "no response spectrum results: enable Response spectrum (Project Settings, "
            "Analysis model) and run the analysis; the design uses the static cases EX, EY"
        )
    missing = sorted(_expected_axes(project) - set(spectra))
    if missing:
        return unavailable(
            "the response spectrum case in "
            + " and ".join(missing)
            + " has no results (the analysis has not finished, or was run without it): run "
            "all the cases; until then the design uses the static cases EX, EY"
        )
    if run and _stamp(out_dir, project_path, False) != stamp_before:
        return unavailable(
            "the analysis results changed while they were read (the analysis is still "
            "running); the design uses the static cases EX, EY until it has finished"
        )
    from saengine.library.settings import category_site_class, site_specific_warning, soil_flags

    values = derived(settings)
    # S1 / S2 flagged by the soil report: the pack's assumed class for the category, and its
    # warning in the notes (never silent).
    flags = soil_flags(settings)
    category = seismic_design_category(
        zone_of(values["Z"]),
        category_site_class(settings, settings.site.siteClass, flags),
        settings.occupancy.category,
    )
    site_warning = site_specific_warning(settings, flags)
    if site_warning:
        notes.append(site_warning)

    # ── scaling (Sec 2.5.9.4) ──
    v_static, v_dynamic, scale, participation = {}, {}, {}, {}
    for axis in ("X", "Y"):
        forces = static_storey_forces(project, f"E{axis}")
        v_static[axis] = abs(sum(lv["force"] for lv in forces))
        data = spectra.get(axis)
        if data is None:
            v_dynamic[axis], scale[axis], participation[axis] = 0.0, 1.0, 0.0
            notes.append(f"no response spectrum case in {axis}")
            continue
        v_dynamic[axis] = modal_base_shear(data["modes"], data["damping"], data["rule"])
        scale[axis] = scale_factor(v_static[axis], v_dynamic[axis])
        participation[axis] = sum(float(m.get("mass_ratio", 0.0)) for m in data["modes"])
        if not v_static[axis]:
            notes.append(
                f"{axis}: no equivalent static base shear (case E{axis} has no forces), so the "
                "response spectrum forces are not scaled"
            )
        if participation[axis] < _seismic().massParticipation - 1e-9:
            notes.append(
                f"{axis}: the modes reach {100 * participation[axis]:.1f} % of the mass, less "
                f"than the {100 * _seismic().massParticipation:g} % of {CLAUSES['modes']}; add modes"
            )

    # ── towers on a podium (saengine.fem.towers): each tower's response spectrum shear at the
    # podium top must reach the same share of its part of the static shear; the design scales
    # the building by the largest factor of the building and its towers ──
    from saengine.fem.towers import tower_checks, tower_scale, tower_shears, towers_beside

    towers = towers_beside(project_path)
    shears = tower_shears(project, towers, spectra) if towers is not None else {}
    for axis in ("X", "Y"):
        scale[axis] = max(scale[axis], tower_scale(shears, axis))

    orthogonal = orthogonal_required(category, options.orthogonal)
    torsion_levels = (
        {axis: torsion_loads(project, f"E{axis}")[1] for axis in ("X", "Y")}
        if options.accidentalTorsion
        else {}
    )
    torsion = options.accidentalTorsion and any(
        lv["moment"] for levels_ in torsion_levels.values() for lv in levels_
    )

    # ── the modal-force run ──
    run_info: dict[str, Any] | None = None
    forces: dict[str, Any] = {}
    if run:
        # The stamp of the results the spectra were read from (checked unchanged above).
        stamp = _stamp(out_dir, project_path, torsion)
        previous = None
        try:
            previous = json.loads((folder / SUMMARY_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        old = (previous or {}).get("run") or {}
        same_parts = sorted(old.get("directions") or []) == sorted(spectra) and {
            p[1] for p in old.get("parts", {}) if p.startswith("R")
        } == set(spectra)
        if old.get("stamp") == stamp and same_parts:
            run_info = old
        else:
            # A stale summary and its results go first: should the run fail, the design finds
            # nothing (the static cases) rather than the old forces.
            shutil.rmtree(folder, ignore_errors=True)
            if (folder / SUMMARY_FILE).exists():
                (folder / SUMMARY_FILE).unlink()
            model, cases = modal_force_model(project, spectra, torsion)
            _run(model, folder, [c["id"] for c in cases])
            parts: dict[str, Any] = {}
            for axis, data in spectra.items():
                ids = [c["id"] for c in cases if c["part"] == f"R{axis}"]
                modes = [c["mode"] for c in cases if c["part"] == f"R{axis}"]
                parts[f"R{axis}"] = {
                    "cases": ids,
                    "rule": data["rule"],
                    "damping": data["damping"],
                    "omegas": [data["modes"][k]["angular_frequency"] for k in modes],
                }
            for c in cases:
                if c["part"].startswith("A"):
                    parts[c["part"]] = {"case": c["id"]}
            if _stamp(out_dir, project_path, False) != stamp_before:
                return unavailable(
                    "the analysis results changed during the response spectrum force run (the "
                    "analysis is still running); the design uses the static cases EX, EY until "
                    "it has finished"
                )
            run_info = {"stamp": stamp, "directions": sorted(spectra), "parts": parts}
        if any(p.startswith("A") for p in run_info["parts"]):
            from opensees_studio.services.result_store import load_manifest, load_results

            by_id = {int(e["case_id"]): e for e in load_manifest(folder / "results")["cases"]}
            for part, spec in run_info["parts"].items():
                if part.startswith("A"):
                    forces[part] = load_results(by_id[int(spec["case"])], folder / "results")

    # ── drift (Sec 2.5.7.7, 2.5.9.4, 2.5.14.1) ──
    amplification = (
        values["Cd"] / values["seismicImportance"]
        if values["Cd"] and values["seismicImportance"]
        else 1.0
    )
    # Each direction with the Cd of its own systems (Sec 2.5.5.5.1).
    by_axis_amplification = {
        axis: (
            values.get(f"Cd{axis}", values["Cd"]) / values["seismicImportance"]
            if values["seismicImportance"]
            else 1.0
        )
        for axis in ("X", "Y")
    }
    storeys = _levels(project, levels)
    limit_row = settings_drift_limit(
        settings, category, max(len(storeys) - 1, 0), options.redundancy
    )
    allowable = limit_row["ratio"]
    height_note = height_limit_note(
        settings, category, storeys[-1] - storeys[0] if storeys else 0.0
    )
    if height_note:
        notes.append(height_note)
    # ── torsional irregularity and Ax (Sec 2.5.5.3.1(i), 2.5.7.6.2) ──
    irregularity = torsional_irregularity(project, spectra, storeys, scale, forces)
    ax = torsion_amplification(irregularity, category, torsion and bool(forces))
    for axis in ("X", "Y"):
        mine = [r for r in irregularity if r["direction"] == axis]
        worst = max(mine, key=lambda r: r["ratio"], default=None)
        if worst is None or not worst["irregular"]:
            continue
        kind = "extreme torsional irregularity" if worst["extreme"] else "torsional irregularity"
        text = (
            f"{axis}: {kind}, storey drift at one end {worst['ratio']:.2f} × the average between "
            f"{worst['bottom']:g} and {worst['top']:g} m ({CLAUSES['irregularity']})"
        )
        if ax[axis] > 1.0:
            text += f"; the accidental torsion is amplified by Ax = {ax[axis]:.3f} ({CLAUSES['amplification']})"
        elif category not in ("C", "D"):
            text += "; no amplification Ax outside Seismic Design Category C or D"
        elif not (torsion and forces):
            text += "; Ax not applied: no accidental torsion case"
        notes.append(text)
    if not run and torsion:
        notes.append(
            "torsional irregularity checked without the accidental torsion case (not run), so "
            "Ax is not applied"
        )
    # ── B12: the other irregularities, the dynamic analysis requirement, the soft storeys and
    # the orthogonal rule of Category C with non-parallel systems (saengine.fem.irregularity) ──
    irregular = _irregularities(out_dir, project_path, settings, irregularity, notes)
    if (
        irregular is not None
        and "nonparallel" in irregular["types"]
        and category in _orthogonal_categories()
        and options.orthogonal == "auto"
        and not orthogonal
    ):
        orthogonal = True
        notes.append(
            f"Seismic Design Category {category} with non-parallel systems: 100 % + 30 % "
            f"({CLAUSES['orthogonal']})"
        )
    drift = storey_drifts(project, spectra, storeys, by_axis_amplification, allowable, forces, ax)
    tower_summary = None
    if towers is not None:
        tower_summary = tower_checks(
            project, towers, shears, spectra, storeys, by_axis_amplification, allowable, scale,
            forces, ax,
        )  # fmt: skip
        notes.extend(tower_summary["notes"])
    # ── diaphragm deflection (Sec 2.5.14.2) and separation (Sec 2.5.14.3) ──
    diaphragm = diaphragm_deflections(
        project, spectra, storeys, by_axis_amplification, settings.seismic.diaphragmDeflectionLimit
    )
    separation = separation_checks(
        project, spectra, storeys, by_axis_amplification, settings, forces, ax
    )
    notes.extend(diaphragm_notes(diaphragm, settings.seismic.diaphragmDeflectionLimit))
    notes.extend(separation["notes"])
    if any(not d["ok"] for d in drift):
        worst = max(drift, key=lambda d: d["ratio"])
        notes.append(
            f"storey drift {100 * worst['ratio']:.2f} % in {worst['direction']} between "
            f"{worst['bottom']:g} and {worst['top']:g} m exceeds the allowable "
            f"{100 * allowable:.2f} % ({CLAUSES['drift']})"
        )
    if not torsion and options.accidentalTorsion:
        notes.append("accidental torsion: no floor has an equivalent static force and an extent")
    notes.append(
        "signs: ± the envelope, each force component at its peak (conservative); columns and "
        "walls at the corners ±N, ±My, ±Mz"
    )
    if category == "C" and options.orthogonal == "auto" and not orthogonal:
        notes.append(
            "Seismic Design Category C: the directions are taken one at a time (no non-parallel "
            f"systems found; {CLAUSES['orthogonal']})"
        )
    combinations = seismic_combinations(settings, options, orthogonal, torsion, ax)
    # ── B19: the linear time histories (saengine.fem.linear_time_history): their suites, base
    # shear scaling and drifts; with seismicDesign "timeHistory" they replace RX, RY in E ──
    history = None
    try:
        from saengine.fem import linear_time_history as lth

        history = lth.design_summary(
            out_dir, project, project_path.parent, settings, spectra, v_static,
            {a: scale[a] * v_dynamic[a] for a in ("X", "Y")}, storeys, by_axis_amplification,
            allowable, design_uses_time_history(settings),
        )  # fmt: skip
    except (OSError, ValueError, KeyError) as error:
        notes.append(f"the time-history design could not be worked out: {error}")
    if history is not None:
        history["modelFile"] = str(project_path.resolve())
        notes.extend(history.get("notes", []))
        if history.get("use"):
            parts = history["parts"]
            one_way = seismic_combinations(settings, options, False, torsion, ax)
            combinations = lth.history_combinations(
                one_way if "H" in parts else combinations, parts
            )
    elif design_uses_time_history(settings):
        notes.append(
            "the earthquake design asks for the time histories, but the model has none: the "
            "response spectrum is used"
        )

    summary = {
        "schema": SUMMARY_SCHEMA,
        "available": True,
        "scale": {
            "x": scale["X"],
            "y": scale["Y"],
            "vStatic": {"x": v_static["X"] / 1e3, "y": v_static["Y"] / 1e3},
            "vDynamic": {"x": v_dynamic["X"] / 1e3, "y": v_dynamic["Y"] / 1e3},
            "fraction": _seismic().minimumScale,
            "clause": CLAUSES["scale"],
        },
        "massParticipation": {"x": participation["X"], "y": participation["Y"]},
        "category": category,
        "orthogonal": orthogonal,
        "verticalCoefficient": vertical_coefficient(settings) if options.verticalComponent else 0.0,
        "amplification": amplification,
        "amplificationByAxis": by_axis_amplification,
        "allowableDrift": allowable,
        "driftRow": limit_row,
        "diaphragmDeflection": diaphragm,
        "separation": separation,
        "siteSpecific": site_warning,
        "torsion": torsion_levels,
        "torsionalIrregularity": irregularity,
        "torsionAmplification": ax,
        "irregularities": _irregularity_summary(irregular),
        "combinations": combinations,
        "timeHistory": history,
        "signs": options.signs,
        "drift": drift,
        "towers": tower_summary,
        "notes": notes,
        "clauses": clauses(),
    }
    if run_info is not None:
        summary["run"] = run_info
        folder.mkdir(parents=True, exist_ok=True)
        (folder / SUMMARY_FILE).write_text(json.dumps(summary, indent=1), encoding="utf-8")
        if memo_key is not None:
            _remember_summary(memo_key, (folder / SUMMARY_FILE).stat().st_mtime_ns, summary)
    return summary


def _orthogonal_categories() -> set[str]:
    """The Seismic Design Categories where non-parallel systems ask for 100 % + 30 % (the
    pack's ``irregularities.nonparallelOrthogonal``)."""
    found = getattr(_seismic(), "irregularities", None)
    return set(found.nonparallelOrthogonal) if found is not None else set()


def _irregularities(
    out_dir: Path,
    project_path: Path,
    settings: Any,
    torsion_rows: list[dict[str, Any]],
    notes: list[str],
) -> dict[str, Any] | None:
    """B12: the building's irregularities (:func:`saengine.fem.irregularity.assessment_of`)
    with the response spectrum torsion rows; their notes go into ``notes``. None when the
    building model cannot be read (a bare analysis model) or the pack does not cover them."""
    from saengine.fem import irregularity

    if irregularity.table() is None:
        return None
    try:
        found = irregularity.assessment_of(out_dir, project_path, settings, torsion_rows)
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return None
    for finding in found["findings"]:
        if finding["type"] in ("torsion", "extremeTorsion"):
            continue  # noted above with Ax
        notes.append(
            f"{finding['label']}: {finding['where']}"
            + (f" in {finding['direction']}" if finding.get("direction") else "")
            + f", {finding['value']} ({finding['clause']})"
        )
    notes.extend(found["notes"])
    return found


def _irregularity_summary(found: dict[str, Any] | None) -> dict[str, Any] | None:
    if found is None:
        return None
    return {
        k: found.get(k)
        for k in (
            "types",
            "plan",
            "vertical",
            "irregular",
            "findings",
            "softStoreys",
            "dynamic",
            "connections",
        )
    }


_SUMMARY_MEMO: tuple[tuple[Any, ...], int, dict[str, Any]] | None = None
"""The last summary :func:`seismic_design` ran and wrote: its inputs, the time its file was
written and the summary. While the results, the model and the settings stay the same and the
file is the one it wrote, the next call returns it rather than reading every result again."""


def _remember_summary(key: tuple[Any, ...], written: int, summary: dict[str, Any]) -> None:
    global _SUMMARY_MEMO
    _SUMMARY_MEMO = (key, written, copy.deepcopy(summary))


def load_summary(out_dir: str | Path) -> dict[str, Any] | None:
    """The summary :func:`seismic_design` last wrote for these results, or None."""
    try:
        summary = json.loads((Path(out_dir) / RS_FOLDER / SUMMARY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return summary if summary.get("schema") == SUMMARY_SCHEMA else None


@code_context.in_project_pack(path_params=("out_dir",))
def design_demands(
    project: dict[str, Any],
    out_dir: str | Path,
    settings: Any,
    extra: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    base: Any = None,
) -> tuple[list[str], dict[str, list[Any]], list[str], dict[int, list[np.ndarray]]]:
    """:func:`saengine.design.check._demands` with the response spectrum combinations: the
    same result (combination names, pieces with their forces per combination, notes, shell
    forces per combination), the project's combinations with EX or EY replaced by those of the
    ``summary`` (default: :func:`load_summary`), each expanded into its sign patterns
    (:func:`saengine.fem.combinations.sign_patterns`, ``summary["signs"]``) as
    ``"<name> [<label>]"``. A pattern's forces are ``S + sign·E``: S its static cases (as
    ``_demands`` forms them, through a stand-in combination of the same name), E the envelope
    of its parts (:meth:`SeismicForces.frame`, :meth:`SeismicForces.shell`). ``sway`` of a
    pattern is ``sign·E``; its lateral displacements (``extra["lateralDisplacements"]``) are
    the factored scaled peaks Σ|f|·u, for the stability index, and its storey shear
    (``extra["storeyShear"]``, a function of the cut height) the factored
    :meth:`SeismicForces.storey_shear`. Without an available summary or a modal-force run with
    every RS part the combinations name, ``base`` (``check._demands``), with a note when a
    summary was there but could not be used."""
    from saengine.fem.combinations import (
        EARTHQUAKE_CASES,
        DesignCombination,
        sign_patterns,
    )
    from saengine.fem.display import _elements
    from saengine.library.settings import LoadCombination

    if base is None:
        from saengine.design import check

        base = check._demands
    summary = summary if summary is not None else load_summary(out_dir)
    forces = load_seismic_forces(out_dir) if summary and summary.get("available") else None
    if forces is None or not summary.get("combinations"):
        names, pieces, notes, shells = base(project, out_dir, settings, extra)
        if summary and summary.get("available") and summary.get("combinations"):
            notes = [
                *notes,
                (
                    "the response spectrum design is not used: its modal-force run is missing "
                    "or was made from other results; the design uses the static cases EX, EY"
                ),
            ]
        return names, pieces, notes, shells
    # Every response spectrum part a combination names must be in the run: one left out would
    # drop that direction's earthquake without a word (a missing accidental torsion part is a
    # direction without torsion loads: zero, nothing lost).
    needed = {p for c in summary["combinations"] for p in c.get("envelope", {}) if p[0] == "R"}
    lost = sorted(needed - set(forces.parts))
    if lost:
        names, pieces, notes, shells = base(project, out_dir, settings, extra)
        return (
            names,
            pieces,
            [
                *notes,
                (
                    "the response spectrum design is not used: its modal-force run has no "
                    + ", ".join(lost)
                    + "; run the analysis again; the design uses the static cases EX, EY"
                ),
            ],
            shells,
        )

    rs = {c["name"]: DesignCombination.from_json(c) for c in summary["combinations"]}
    kept = [c for c in settings.combinations if not any(getattr(c, k) for k in EARTHQUAKE_CASES)]
    stand_ins = [
        LoadCombination(name=c["name"], **c.get("loads", {})) for c in summary["combinations"]
    ]
    trial = settings.model_copy(update={"combinations": kept + stand_ins})
    inner: dict[str, Any] = {}
    names, pieces, notes, shells = base(project, out_dir, trial, inner)
    signs = str(summary.get("signs", "corners"))
    frame_patterns = sign_patterns("frame", signs)
    shell_patterns = sign_patterns("shell", signs)
    by_id = {e.id: e for e in _elements(project)}

    def total(env: dict[str, np.ndarray], combination: DesignCombination) -> np.ndarray | None:
        found = [abs(f) * np.abs(env[p]) for p, f in combination.envelope.items() if p in env]
        return sum(found[1:], found[0]) if found else None

    # Per new combination: (index in ``names``, the RS combination or None, sign pattern).
    plan: list[tuple[int, DesignCombination | None, int]] = []
    new_names: list[str] = []
    for index, name in enumerate(names):
        combination = rs.get(name)
        if combination is None:
            plan.append((index, None, 0))
            new_names.append(name)
            continue
        for pattern, (label, _) in enumerate(frame_patterns):
            plan.append((index, combination, pattern))
            new_names.append(f"{name} [{label}]")

    for member in pieces.values():
        for piece in member:
            element = by_id.get(piece.id)
            per: dict[str, np.ndarray | None] = {}
            new_forces, new_sway, new_sustained = [], [], []
            for index, combination, pattern in plan:
                s = piece.forces[index]
                sway = piece.sway[index] if piece.sway is not None else None
                if combination is None:
                    new_forces.append(s)
                    new_sway.append(sway)
                    new_sustained.append(piece.sustained[index] if piece.sustained else None)
                    continue
                if combination.name not in per:
                    per[combination.name] = (
                        total(forces.frame(element), combination) if element else None
                    )
                env = per[combination.name]
                sign = frame_patterns[pattern][1]
                e = sign * env if env is not None else np.zeros_like(s)
                new_forces.append(s + e)
                new_sway.append((sway if sway is not None else np.zeros_like(s)) + e)
                new_sustained.append(piece.sustained[index] if piece.sustained else None)
            piece.forces = new_forces
            if piece.sway is not None:
                piece.sway = new_sway
            if piece.sustained is not None:
                piece.sustained = new_sustained
    for shell_id, rows in shells.items():
        per = {}
        new_rows = []
        for index, combination, pattern in plan:
            if combination is None:
                new_rows.append(rows[index])
                continue
            if combination.name not in per:
                per[combination.name] = total(forces.shell(shell_id), combination)
            env = per[combination.name]
            sign = shell_patterns[pattern][1]
            new_rows.append(rows[index] + (sign * env if env is not None else 0.0))
        shells[shell_id] = new_rows

    if extra is not None:
        factors = inner.get("factors", [{} for _ in names])
        lateral = inner.get("lateralDisplacements", [{} for _ in names])
        nodes = [int(n["id"]) for n in project.get("nodes", [])]
        peaks: dict[str, dict[int, np.ndarray]] = {}
        new_factors, new_lateral = [], []
        for index, combination, _ in plan:
            new_factors.append(factors[index])
            if combination is None:
                new_lateral.append(lateral[index])
                continue
            if combination.name not in peaks:
                moved: dict[int, np.ndarray] = {}
                for node in nodes:
                    u = total(forces.displacement(node), combination)
                    if u is not None and np.any(u):
                        moved[node] = u
                peaks[combination.name] = moved
            new_lateral.append(peaks[combination.name])
        extra["factors"] = new_factors
        extra["lateralDisplacements"] = new_lateral
        extra["envelope"] = [dict(c.envelope) if c else {} for _, c, _ in plan]

        def shear_of(combination: DesignCombination) -> Any:
            def shear(cut: float) -> np.ndarray:
                parts = forces.storey_shear(cut)
                found = [abs(f) * parts[p] for p, f in combination.envelope.items() if p in parts]
                return sum(found[1:], found[0]) if found else np.zeros(3)

            return shear

        # Per combination the storey shear of its earthquake (a function of the cut height),
        # None for the others: the stability index's Vus (saengine.design.slender.storeys).
        extra["storeyShear"] = [shear_of(c) if c else None for _, c, _ in plan]
    history = summary.get("timeHistory") or {}
    if history.get("use"):
        notes = [*notes, *[n for n in history.get("notes", []) if n.startswith("earthquake from")]]
    notes = [
        *notes,
        (
            "earthquake from the response spectrum, scaled by "
            f"{float(summary['scale']['x']):.3f} (X) and {float(summary['scale']['y']):.3f} (Y) "
            f"({summary['scale'].get('clause', CLAUSES['scale'])}); ± the envelope, "
            + ("8 sign patterns (±N, ±My, ±Mz)" if signs == "corners" else "+E and −E")
        ),
    ]
    return new_names, pieces, notes, shells


def drift_rows(summary: dict[str, Any]) -> list[list[str]]:
    """The drift of a :func:`seismic_design` summary as report rows: direction, storey, height,
    elastic drift [mm], Cd·δ/I [mm], ratio [%], allowable [%], OK."""
    rows = []
    for d in summary.get("drift", []):
        rows.append(
            [
                d["direction"],
                f"{d['bottom']:g} to {d['top']:g} m",
                f"{d['height']:.2f}",
                f"{1e3 * (d['elasticDrift'] + d['torsionDrift']):.2f}",
                f"{1e3 * d['designDrift']:.2f}",
                f"{100 * d['ratio']:.3f}",
                f"{100 * d['allowableRatio']:.2f}",
                "OK" if d["ok"] else "FAIL",
            ]
        )
    return rows


def irregularity_rows(summary: dict[str, Any]) -> list[list[str]]:
    """The torsional irregularity check of a :func:`seismic_design` summary as report rows:
    direction, storey, Δmax [mm], Δavg [mm], Δmax/Δavg, verdict, Ax of the level."""
    rows = []
    for r in summary.get("torsionalIrregularity", []):
        verdict = "extreme" if r["extreme"] else "irregular" if r["irregular"] else "regular"
        rows.append(
            [
                r["direction"],
                f"{r['bottom']:g} to {r['top']:g} m",
                f"{1e3 * r['driftMax']:.2f}",
                f"{1e3 * r['driftAvg']:.2f}",
                f"{r['ratio']:.3f}",
                verdict,
                f"{r['amplification']:.3f}" if r["irregular"] else "1.000",
            ]
        )
    return rows
