"""Wind-induced motion of tall buildings: the peak acceleration of the top floor against the
occupants' comfort (alpha 9 P7).

The method and every value are the code pack's ``windComfort`` table
(:class:`saengine.codes.practice_tables.WindComfortTable`); a pack without it does not check
occupant comfort. The default pack's BNBC 2020 asks for it on flexible buildings by a rational
dynamic analysis (Part 6 Sec 10.12.6) and gives none: the method is SAEngine practice there.

**From the modal analysis of the run**, per wind direction (X, Y): the mode with the largest
effective mass in that direction, its frequency n1, its shape φ normalised to 1 at the top
level (the mean over the top level's nodes with mass), the generalised mass m1 = Σ m φ² of
the model's nodal masses, and the shape's exponent ξ of φ = (z/H)^ξ by least squares over
the levels (between 0.5 and 3).

**The wind** of ``returnPeriod`` years: the project's basic wind speed × the ratio of
``speedRatio`` (see the table).

**The response** (``response``):

- ``alongWindGust`` (the along-wind form of the ASCE 7 commentary, C6.5.8 of ASCE 7-05 and
  C26.11 of later editions): σ = 0.85 ρ B H Cfx V̄z̄² Iz̄ K R / m1 with K = 1.65^ᾱ / (ᾱ + ξ + 1),
  V̄z̄, Iz̄ and the resonant factor R of the wind table's flexible gust-effect factor
  (:func:`saengine.fem.loads.flexible_gust_factor`, at the comfort damping) and Cfx the
  windward plus leeward wall coefficients;
- ``turbulenceSpectrum`` (EN 1991-1-4 Annex B.4): σ = cf ρ b Iv(zs) vm²(zs) R Kx / me with
  Kx = (2ξ + 1)((ξ + 1)(ln(zs/z0) + 0.5) - 1) / ((ξ + 1)² ln(zs/z0)), R² = π²/(2δ) SL Rh Rb
  of the wind table's detailed structural factor constants (δ = 2π ζ), cf the wall
  coefficients' sum and me = m1 (2ξ + 1) / H the equivalent mass per height.

The peak a = g σ with g = √(2 ln n1T) + ``peakConstant`` / √(2 ln n1T), T = ``duration``,
against the occupancy's limit (``occupancyLimits``) or its curve at n1 (``frequencyCurve``).
The occupancy is that of the typical floor's area load. Across-wind and torsional motion are
not computed (the report says so).

Units: m, kg, s; accelerations in milli-g.
"""

from __future__ import annotations

import math
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

G = 9.81


def table() -> Any | None:
    pack = code_context.current()
    return pack.table("windComfort") if pack.has("windComfort") else None


def speed_ratio(rules: Any) -> float:
    """V_T / V_ref of the comfort wind's return period (see the table)."""
    t = float(rules.returnPeriod)
    if rules.speedRatio == "logarithmicMri":
        a, b = rules.mriTerms
        return (a + b * math.log(12 * t)) / rules.referenceToFifty
    k, n = rules.probabilityTerms

    def term(period: float) -> float:
        p = 1 - math.exp(-1 / period)
        return 1 - k * math.log(-math.log(1 - p))

    return (term(t) / term(float(rules.referencePeriod))) ** n


def peak_factor(n1: float, rules: Any) -> float:
    root = math.sqrt(2 * math.log(max(n1 * rules.duration, 1.0001)))
    return root + rules.peakConstant / root


def limit_of(occupancy: str, n1: float, rules: Any) -> float:
    """The limit [milli-g] of ``occupancy`` at ``n1`` [Hz]."""
    if rules.acceptance == "occupancyLimits":
        return float(rules.limits[occupancy])
    points = sorted(rules.curves[occupancy])
    if n1 <= points[0][0]:
        return float(points[0][1])
    for (f0, a0), (f1, a1) in pairwise(points):
        if n1 <= f1:
            t = math.log(n1 / f0) / math.log(f1 / f0)
            return float(math.exp(math.log(a0) + t * (math.log(a1) - math.log(a0))))
    return float(points[-1][1])


def along_wind_gust(
    height: float, width: float, depth: float, n1: float, speed: float, exposure: str,
    damping: float, m1: float, xi: float, rules: Any,
) -> dict[str, Any] | None:  # fmt: skip
    """σ [m/s²] of ``alongWindGust`` (see the module notes); None without the wind table's
    flexible gust constants."""
    from saengine.fem import loads

    wind = code_context.table("wind")
    terms = loads.flexible_gust_factor(height, width, depth, n1, speed, exposure, damping)
    if terms is None:
        return None
    alpha = float(wind.exposures[exposure].alphaBar)
    cfx = float(wind.cpWindward) - loads.leeward_coefficient(depth / width if width else 1.0)
    k = 1.65**alpha / (alpha + xi + 1)
    sigma = (
        0.85 * rules.airDensity * width * height * cfx * terms["Vz_ms"] ** 2 * terms["Iz"] * k
        * terms["R"] / m1
    )  # fmt: skip
    return {
        "sigma": sigma,
        "R": terms["R"],
        "I": terms["Iz"],
        "V": terms["Vz_ms"],
        "cf": cfx,
        "K": k,
        "basis": f"V̄z̄ {terms['Vz_ms']:.1f} m/s at z̄ {terms['zbar_m']:.1f} m, Iz̄ "
        f"{terms['Iz']:.3f}, R {terms['R']:.3f}, K {k:.3f}, Cfx {cfx:.2f}",
    }


def turbulence_spectrum(
    height: float, width: float, n1: float, speed: float, terrain: str, damping: float,
    m1: float, xi: float, rules: Any,
) -> dict[str, Any] | None:  # fmt: skip
    """σ [m/s²] of ``turbulenceSpectrum`` (see the module notes); None without the wind
    table's detailed structural factor constants."""
    from saengine.fem import peak_velocity_pressure as pvp
    from saengine.fem.loads import wind_factor

    wind = code_context.table("wind")
    rule = getattr(getattr(wind, "structuralFactor", None), "detailed", None)
    if rule is None or wind.peakVelocityPressure is None:
        return None
    z0 = float(wind.exposures[terrain].z0)
    zs = rule.heightShare * height
    terms = pvp.roughness_terms(zs, terrain, wind)
    vb = wind_factor("directionality") * wind.peakVelocityPressure.season * speed
    vm = terms["cr"] * terms["co"] * vb
    iv = terms["Iv"]
    alpha = rule.alphaBase + rule.alphaLog * math.log(z0)
    scale = rule.scaleLength * (terms["z"] / rule.scaleHeight) ** alpha
    fl = n1 * scale / vm
    a, b = rule.spectrum
    sl = a * fl / (1 + b * fl) ** (5 / 3)
    rh = pvp._resonance(rule.admittance * height * fl / scale)
    rb = pvp._resonance(rule.admittance * width * fl / scale)
    delta = 2 * math.pi * damping
    r = math.sqrt(math.pi**2 / (2 * delta) * sl * rh * rb)
    log = math.log(terms["z"] / z0)
    kx = (2 * xi + 1) * ((xi + 1) * (log + 0.5) - 1) / ((xi + 1) ** 2 * log)
    cpe_d, cpe_e = pvp.wall_coefficients(height / max(width, 1e-9), wind)
    cf = cpe_d - cpe_e
    me = m1 * (2 * xi + 1) / height
    sigma = cf * wind.peakVelocityPressure.airDensity * width * iv * vm**2 * r * kx / me
    return {
        "sigma": sigma,
        "R": r,
        "I": iv,
        "V": vm,
        "cf": cf,
        "K": kx,
        "basis": f"vm(zs) {vm:.1f} m/s at zs {terms['z']:.1f} m, Iv {iv:.3f}, R {r:.3f}, Kx "
        f"{kx:.3f}, cf {cf:.2f}, me {me / 1e3:.1f} t/m",
    }


def _mode(modal: Any, masses: dict[int, np.ndarray], axis: int) -> tuple[int, float] | None:
    """(mode number, effective mass share) of the mode with the largest effective mass along
    ``axis``."""
    best = None
    for number, shape in modal.mode_shapes.items():
        num = den = 0.0
        for nid, vec in shape.items():
            m = masses.get(nid)
            if m is None:
                continue
            v = np.asarray(vec, dtype=float)[:3]
            num += m[axis] * v[axis]
            den += float(np.dot(m, v * v))
        if den <= 0:
            continue
        effective = num * num / den
        if best is None or effective > best[1]:
            best = (int(number), effective)
    return best


def _steel(root: Path) -> bool:
    """Whether most of the building's columns are steel."""
    from saengine.library.bim import BuildingModel, ColumnElement
    from saengine.library.materials import Category, MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    try:
        building = BuildingModel.model_validate_json(
            (root / "06 BIM/bim.json").read_text(encoding="utf-8")
        )
        objects = ObjectLibrary.model_validate_json(
            (root / "04 Objects/objects.json").read_text(encoding="utf-8")
        )
        mats = MaterialLibrary.model_validate_json(
            (root / "03 Materials/materials.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return False
    types = {o.id: o for o in objects.objects}
    by_id = {m.id: m for m in mats.materials}
    kinds = []
    for e in building.elements:
        if isinstance(e, ColumnElement):
            m = by_id.get(getattr(types.get(e.type), "material", None))
            kinds.append(m is not None and m.category == Category.STEEL)
    return bool(kinds) and sum(kinds) > len(kinds) / 2


def evaluate(
    project: dict[str, Any],
    project_path: str | Path,
    loaded: list[tuple[dict[str, Any], Any]],
    level_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """The peak acceleration of the top floor in X and Y (see the module notes):
    ``{"available", "rows": [{"direction", "mode", "n1", "xi", "m1", "speed", "a", "limit",
    "ok", "basis"}], "notes", "clause", "sheet"}``."""
    from opensees_studio.services.results import ModalResults

    from saengine.fem.combinations import settings_beside
    from saengine.library.settings import derived

    rules = table()
    if rules is None:
        return {"available": False, "reason": f"Not covered by the code pack {code_context.code_name()}."}  # fmt: skip
    modal = next((r for _, r in loaded if isinstance(r, ModalResults)), None)
    if modal is None or not modal.mode_shapes:
        return {"available": False, "reason": "No modal analysis with mode shapes in the run."}
    settings = settings_beside(project_path)
    if settings is None:
        return {"available": False, "reason": "No project settings."}
    speed = derived(settings).get("windSpeed")
    if not speed:
        return {"available": False, "reason": "No basic wind speed in the project settings."}
    exposure = settings.wind.exposure
    root = Path(project_path).resolve().parent.parent
    material = "steel" if _steel(root) else "concrete"
    damping = float(rules.damping.get(material) or next(iter(rules.damping.values())))
    ratio = speed_ratio(rules)
    v_t = float(speed) * ratio
    nodes = project.get("nodes", [])
    masses = {
        n["id"]: np.asarray((n.get("mass") or [0, 0, 0])[:3], dtype=float)
        for n in nodes
        if any((n.get("mass") or [0])[:3])
    }
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in nodes}
    if not masses or len(level_rows) < 2:
        return {"available": False, "reason": "The model has no storey masses."}
    base, top = float(level_rows[0]["z"]), float(level_rows[-1]["z"])
    height = top - base
    points = np.array([coords[n] for n in coords])
    extent = points.max(axis=0) - points.min(axis=0)
    load = next((a for a in settings.areaLoads if a.id == settings.floorLoad), None)
    occupancy = rules.areaUses.get(getattr(load, "use", ""), rules.defaultOccupancy)
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for axis, name in ((0, "X"), (1, "Y")):
        found = _mode(modal, masses, axis)
        if found is None:
            continue
        number, _ = found
        period = float(np.asarray(modal.periods, dtype=float)[number - 1])
        if not (period > 0 and math.isfinite(period)):
            continue
        n1 = 1 / period
        shape = modal.mode_shapes[number]
        top_nodes = [n for n in masses if abs(coords[n][2] - top) < 0.05 and n in shape]
        if not top_nodes:
            continue
        phi_top = float(np.mean([np.asarray(shape[n], dtype=float)[axis] for n in top_nodes]))
        if abs(phi_top) < 1e-12:
            continue
        m1 = 0.0
        logs = []
        for nid, m in masses.items():
            if nid not in shape:
                continue
            phi = float(np.asarray(shape[nid], dtype=float)[axis]) / phi_top
            m1 += m[axis] * phi * phi
            z = (coords[nid][2] - base) / height
            if 0.05 < z < 1 and phi > 1e-3:
                logs.append((math.log(z), math.log(phi)))
        xi = sum(a * b for a, b in logs) / sum(a * a for a, _ in logs) if logs else 1.0
        xi = min(max(xi, 0.5), 3.0)
        width, depth = (float(extent[1]), float(extent[0])) if axis == 0 else (
            float(extent[0]), float(extent[1]))  # fmt: skip
        if rules.response == "alongWindGust":
            response = along_wind_gust(
                height, width, depth, n1, v_t, exposure, damping, m1, xi, rules
            )
        else:
            response = turbulence_spectrum(height, width, n1, v_t, exposure, damping, m1, xi, rules)
        if response is None:
            return {
                "available": False,
                "reason": "The code pack's wind table has no constants for the comfort "
                f"response method '{rules.response}'.",
            }
        g = peak_factor(n1, rules)
        a = g * response["sigma"] / G * 1e3
        limit = limit_of(occupancy, n1, rules)
        rows.append(
            {
                "direction": name,
                "mode": number,
                "n1": n1,
                "xi": xi,
                "m1": m1,
                "speed": v_t,
                "g": g,
                "a": a,
                "limit": limit,
                "ok": a <= limit,
                "basis": response["basis"],
            }
        )
    flexible = getattr(code_context.table("wind"), "flexible", None)
    if flexible is not None and rows and min(r["n1"] for r in rows) >= flexible.frequencyLimit:
        notes.append(
            f"n1 ≥ {flexible.frequencyLimit:g} Hz in both directions: not a flexible building; "
            "the comfort check is reported for information"
        )
    notes += [
        (
            f"comfort wind: {rules.returnPeriod:g}-year, V = {float(speed):g} × {ratio:.3f} = "
            f"{v_t:.1f} m/s; damping {damping:g} ({material}); occupancy {occupancy}"
        ),
        (
            "along-wind motion only: the across-wind and torsional accelerations of slender or "
            "eccentric towers need a wind tunnel or a specialist method"
        ),
    ]
    return {
        "available": True,
        "rows": rows,
        "notes": notes,
        "clause": rules.source,
        "clauses": [str(v) for v in (rules.clauses or {}).values()],
        "sheet": sheet(rows, rules.source, notes),
    }


def sheet(rows: list[dict[str, Any]], source: str, notes: list[str]) -> dict[str, Any]:
    return {
        "name": "Wind comfort",
        "columns": [
            "Direction", "Mode", "n1 [Hz]", "ξ", "m1 [t]", "V [m/s]", "Peak factor",
            "Peak [milli-g]", "Limit [milli-g]", "Result",
        ],
        "rows": [
            [
                r["direction"], r["mode"], round(r["n1"], 3), round(r["xi"], 2),
                round(r["m1"] / 1e3, 1), round(r["speed"], 1), round(r["g"], 2),
                round(r["a"], 2), round(r["limit"], 1), "OK" if r["ok"] else "FAIL",
            ]
            for r in rows
        ],
        "notes": [source, *notes],
    }  # fmt: skip


def report_rows(found: dict[str, Any] | None) -> dict[str, Any] | None:
    """The report's rows (strings) of :func:`evaluate`."""
    if not found:
        return None
    if not found.get("available"):
        return {"available": False, "reason": found.get("reason", "")}
    data = found["sheet"]
    return {
        "available": True,
        "columns": data["columns"],
        "rows": [[str(c) for c in row] for row in data["rows"]],
        "fails": [not r["ok"] for r in found["rows"]],
        "clause": found["clause"],
        "notes": [*found["notes"], *(f"{r['direction']}: {r['basis']}" for r in found["rows"]),
                  *found["clauses"]],
    }  # fmt: skip
