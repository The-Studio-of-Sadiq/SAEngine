"""Supplemental dampers in braces (alpha 9 P6): the damper braces in the analysis model, the
added effective damping of the devices, the damped equivalent lateral force and response
spectrum by the code pack's ``dampers`` table, the devices' strokes, velocities, forces and
energy, and the devices in the nonlinear time history model.

A brace type with a :class:`saengine.library.objects.SupplementalDamper` puts the device in
each of its braces (the inclined members and members of the building). Every value and clause
of the design comes from the code pack in force (:class:`saengine.codes.damper_tables.
DampersTable`); a pack without the table models the devices but takes no reduction.

How it works (SI inside: m, N, s):

- **The linear model** (:func:`prepare_linear`): each damper brace gets its own section with
  the axial stiffness of the device in series with the brace: a viscous damper has none (the
  area × :data:`STATIC_SHARE`), a viscoelastic one its storage stiffness K′, a metallic or
  friction one its initial stiffness (else the brace's own). The brace member is then
  designed for those forces; the device force comes from the damper schedule below.
- **Effective damping**: the fundamental mode taken as ``φ = h / hr`` (the height over the
  roof height), the roof displacement D; a device between the heights z1 and z2 with the
  direction cosine c along the motion deforms ``δ = D |z2 − z1| / hr · c``. Its energy per
  cycle: viscous ``λ(α) C ω^α δ^(1+α)`` with ``λ = 2^(2+α) Γ²(1 + α/2) / Γ(2 + α)``
  (π for α = 1), viscoelastic ``π K″ δ²``, metallic and friction the bilinear loop
  ``4 Qd (δ − δy)``. The strain energy of the mode ``½ ω² Σ m (D φ)²``; the added damping
  ``βV = Σ E / (4π W)``.
- **Method** ``modalStrength`` (the fundamental and residual mode form): iterate the design
  roof displacement ``D1D = g/(4π²) Γ1 Sa(T1D) T1D² / B1D`` with ``T1D = T1 √μD``,
  ``β1D = βI + βV √μD + βHD``, the effective ductility ``μD = D1D / DY`` (at least 1, at
  most R/(Ω0 Ie)), ``DY = g/(4π²) (Ω0 Cd / R) Γ1 Cs T1²`` (Cs the fixed-base coefficient
  V/W), ``βHD = qH (hystereticBase − βI)(1 − 1/μD)``, ``qH = qhFactor TS / T1`` within its
  limits (TS the end of the spectrum's plateau). ``V1 = (R/Cd) Sa(T1D) / (Ω0 B1D) W̄1``,
  ``VR = (R/Cd) Sa(TR) / (Ω0 BR) W̄R`` (TR = residualPeriodShare T1, βR = βI + βV),
  ``V = √(V1² + VR²)`` not below ``Vmin = max(V / B(βI + βV), minimumShare V)``.
- **Method** ``dampedSpectrum``: ``V = Vfixed B(βI) / B(βI + βV)``, not below
  minimumShare·Vfixed.
- **The analysis** (:func:`apply_dampers`): the static earthquake cases EX, EY (and the
  eccentric ones) × V / Vfixed; the response spectrum ÷ B1D / B(ξ) (ξ the damping the
  spectrum is at) from dampedFromShare·T1
  up (SAEngine practice, as the isolation spectrum). Not with isolators: the isolation design
  sets those forces.
- **The devices** at the earthquake level × ``mceFactor``: stroke, velocity ``2π δ / T1D``,
  force (viscous ``C v^α``, viscoelastic ``δ √(K′² + K″²)``, metallic the bilinear curve,
  friction the slip force), energy per cycle; against their capacities.
- **Nonlinear time history** (:func:`nonlinear_links`): each device a ``twoNodeLink``
  between the brace ends: viscous a Maxwell ViscousDamper (the brace's EA/L in series),
  viscoelastic a Kelvin element (K′, C = K″/ω1), metallic Steel02 (Fy, k0, b), friction an
  elastic-perfectly-plastic one (k0, the slip force); the brace's own section then carries
  almost nothing.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.codes import context as code_context

G = 9.80665  # m/s²
MM = 1e-3
#: The damper design beside the analysis model (``08 FEM/dampers.json``).
DAMPERS_FILE = "dampers.json"
SCHEMA = "saengine.dampers/1"
#: Name suffix of the devices' links in the nonlinear time history model.
LINK_SUFFIX = "/damper"
#: The share of its area a brace keeps where the device in it has no static stiffness.
STATIC_SHARE = 1e-3
#: Static earthquake cases by direction (the eccentric ones scale with their source case).
_STATIC_CASES = {"X": ("EX", "EXP", "EXN"), "Y": ("EY", "EYP", "EYN")}


# ─────────────────────────────────────── pack access ───────────────────────────────────────


def covered() -> bool:
    """Whether the code pack in force covers structures with damping systems."""
    try:
        return bool(code_context.current().has("dampers"))
    except Exception:  # noqa: BLE001 - a broken pack covers nothing
        return False


def _table() -> Any:
    return code_context.table("dampers")


def clauses() -> dict[str, str]:
    """The clause references of the damper design (the pack's ``dampers.sources``)."""
    return dict(_table().sources) if covered() else {}


def damping_coefficient(damping_percent: float) -> float:
    """B of the effective damping [%] (the pack's table, linear in between, the end values
    beyond)."""
    points = sorted(_table().dampingCoefficients, key=lambda p: p.damping)
    return float(np.interp(damping_percent, [p.damping for p in points], [p.B for p in points]))


# ─────────────────────────────────────── the devices ───────────────────────────────────────


def viscous_lambda(alpha: float) -> float:
    """``λ = 2^(2+α) Γ²(1 + α/2) / Γ(2 + α)`` of a viscous damper's energy per cycle
    ``λ C ω^α δ^(1+α)`` under a harmonic motion of amplitude δ (π for α = 1)."""
    return 2.0 ** (2.0 + alpha) * math.gamma(1.0 + alpha / 2.0) ** 2 / math.gamma(2.0 + alpha)


@dataclass
class DamperBrace:
    """A damper brace of the model: its member, type, device and geometry [m]."""

    member: str
    type: str
    spec: Any
    start: np.ndarray
    end: np.ndarray
    nodes: tuple[int, int] | None = None
    #: The brace's own axial stiffness EA/L [N/m] and area [m²] before the device.
    axial: float = 0.0
    area: float = 0.0
    sections: list[int] = field(default_factory=list)

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.end - self.start))

    def cosine(self, axis: str) -> float:
        """The direction cosine of the brace along the plan axis."""
        a = 0 if axis == "X" else 1
        return abs(float(self.end[a] - self.start[a])) / self.length if self.length else 0.0

    @property
    def rise(self) -> float:
        return abs(float(self.end[2] - self.start[2]))

    def stiffness(self) -> float:
        """The device's elastic (stick) stiffness [N/m]: entered, else the brace's EA/L."""
        k0 = getattr(self.spec, "initialStiffness", None)
        return float(k0) * 1e3 if k0 else self.axial

    def energy(self, delta: float, period: float) -> float:
        """Energy dissipated in one cycle of amplitude ``delta`` [m] at ``period`` [s] [J]."""
        spec = self.spec
        delta = abs(delta)
        if delta <= 0:
            return 0.0
        if spec.kind == "viscous":
            alpha = float(spec.exponent)
            omega = 2 * math.pi / period
            return (
                viscous_lambda(alpha) * float(spec.coefficient) * 1e3 * omega**alpha
                * delta ** (1.0 + alpha)
            )  # fmt: skip
        if spec.kind == "viscoelastic":
            return math.pi * float(spec.lossStiffness) * 1e3 * delta**2
        k0 = self.stiffness()
        fy = float(spec.yieldForce) * 1e3
        if k0 <= 0:
            return 0.0
        dy = fy / k0
        ratio = float(spec.postYieldRatio) if spec.kind == "metallic" else 0.0
        qd = fy * (1.0 - ratio)
        return 4.0 * qd * (delta - dy) if delta > dy else 0.0

    def force(self, delta: float, velocity: float) -> float:
        """The device's peak force [N] at the amplitude ``delta`` [m] and velocity [m/s]."""
        spec = self.spec
        delta, velocity = abs(delta), abs(velocity)
        if spec.kind == "viscous":
            return float(spec.coefficient) * 1e3 * velocity ** float(spec.exponent)
        if spec.kind == "viscoelastic":
            return delta * math.hypot(float(spec.storageStiffness), float(spec.lossStiffness)) * 1e3
        k0 = self.stiffness()
        fy = float(spec.yieldForce) * 1e3
        if spec.kind == "friction":
            return min(k0 * delta, fy) if k0 > 0 else fy
        dy = fy / k0 if k0 > 0 else 0.0
        if delta <= dy:
            return k0 * delta
        return fy + float(spec.postYieldRatio) * k0 * (delta - dy)


def damper_types(types: dict[str, Any]) -> dict[str, Any]:
    """The brace types with a damper: ``{type id: SupplementalDamper}``."""
    return {
        tid: t.damper
        for tid, t in types.items()
        if getattr(t, "kind", None) == "brace" and getattr(t, "damper", None) is not None
    }


def damper_braces(building: Any, types: dict[str, Any]) -> list[DamperBrace]:
    """The braces of damper types: the inclined members and the members of the building."""
    from saengine.library.bim import MemberElement

    devices = damper_types(types)
    out: list[DamperBrace] = []
    if not devices:
        return out
    for m in building.additions.members:
        if m.type in devices:
            out.append(
                DamperBrace(
                    m.id,
                    m.type,
                    devices[m.type],
                    np.array([m.x1, m.y1, m.z1], dtype=float) * MM,
                    np.array([m.x2, m.y2, m.z2], dtype=float) * MM,
                )
            )
    for e in building.elements:
        if isinstance(e, MemberElement) and e.type in devices:
            out.append(
                DamperBrace(
                    e.id,
                    e.type,
                    devices[e.type],
                    np.array(e.start, dtype=float) * MM,
                    np.array(e.end, dtype=float) * MM,
                )
            )
    return out


def _belongs(name: str, member: str) -> bool:
    """Whether an element ``name`` is a piece of ``member`` (``id``, ``id#k``, ``id/pk``)."""
    base = str(name).split("#")[0]
    return base == member or base.startswith(member + "/p")


# ─────────────────────────────────────── the linear model ───────────────────────────────────────


def _static_factor(brace: DamperBrace, ea: float) -> float:
    """The share of its area the brace keeps for the device's static stiffness."""
    spec = brace.spec
    length = brace.length
    if spec.kind == "viscous" or ea <= 0 or length <= 0:
        return STATIC_SHARE
    if spec.kind == "viscoelastic":
        return max(float(spec.storageStiffness) * 1e3 * length / ea, STATIC_SHARE)
    k0 = getattr(spec, "initialStiffness", None)
    return max(float(k0) * 1e3 * length / ea, STATIC_SHARE) if k0 else 1.0


def prepare_linear(
    project: dict[str, Any], building: Any, types: dict[str, Any]
) -> tuple[list[DamperBrace], list[str]]:
    """Give each damper brace of ``project`` (in place) its own section with the device's
    static axial stiffness (module notes). Returns the braces found in the model and the
    notes; no braces: the model is unchanged."""
    braces = damper_braces(building, types)
    notes: list[str] = []
    if not braces:
        return [], notes
    nodes = {n["id"]: n for n in project["nodes"]}
    sections = {s["id"]: s for s in project["sections"]}
    next_section = max(sections, default=0) + 1
    found: list[DamperBrace] = []
    for brace in braces:
        elements = [
            e
            for e in project["elements"]
            if e.get("type") == "ElasticBeamColumn" and _belongs(e.get("name", ""), brace.member)
        ]
        if not elements or brace.length <= 0:
            notes.append(f"{brace.member}: a damper brace with no frame element; no damper")
            continue
        ids = {int(k) for e in elements for k in e["nodes"]}

        def nearest(point: np.ndarray, ids: set[int] = ids) -> int:
            return min(
                ids,
                key=lambda node_id: float(
                    np.linalg.norm(np.asarray(nodes[node_id]["coords"]) - point)
                ),
            )

        brace.nodes = (nearest(brace.start), nearest(brace.end))
        if brace.nodes[0] == brace.nodes[1]:
            notes.append(f"{brace.member}: its ends are one node; no damper")
            continue
        own: dict[int, int] = {}
        for e in elements:
            sid = int(e["section_id"])
            section = sections.get(sid)
            if section is None or "A" not in section or "E" not in section:
                continue
            if sid not in own:
                ea = float(section["E"]) * float(section["A"])
                if not brace.axial:
                    brace.axial = ea / brace.length
                    brace.area = float(section["A"])
                copied = copy.deepcopy(section)
                copied["id"] = next_section
                copied["name"] = f"{brace.member} damper brace"
                copied["A"] = float(section["A"]) * _static_factor(brace, ea)
                project["sections"].append(copied)
                sections[next_section] = copied
                own[sid] = next_section
                next_section += 1
            e["section_id"] = own[sid]
        if not own:
            notes.append(f"{brace.member}: the damper brace has no elastic section; no damper")
            continue
        brace.sections = sorted(own.values())
        found.append(brace)
    if found:
        kinds: dict[str, int] = {}
        for brace in found:
            kinds[brace.spec.kind] = kinds.get(brace.spec.kind, 0) + 1
        notes.append(
            "dampers: "
            + ", ".join(f"{n} {kind}" for kind, n in sorted(kinds.items()))
            + " damper braces; in the linear analysis each brace has the device's static "
            "stiffness (a viscous damper none), and the device forces come from the damper "
            "schedule (08 FEM/dampers.json): design the braces and their connections for them"
        )
    return found, notes


# ─────────────────────────────────────── the design ───────────────────────────────────────


def plateau_end(sa: Callable[[float], float]) -> float:
    """TS: the longest period of the spectrum ``sa`` still on its plateau (within 0.1 %),
    searched from 0.02 to 4 s."""
    grid = np.arange(0.02, 4.0001, 0.01)
    values = np.array([sa(float(t)) for t in grid])
    top = float(values.max()) if len(values) else 0.0
    if top <= 0:
        return 0.0
    return float(grid[np.nonzero(values >= 0.999 * top)[0][-1]])


@dataclass
class Axis:
    """What the design takes of one direction: the fixed-base base shear V [N], the
    fundamental period T1 [s], R, Cd, Ω0 and Ie."""

    shear: float
    period: float
    R: float
    Cd: float
    omega: float
    importance: float = 1.0


def modal_values(levels: list[tuple[float, float]]) -> dict[str, float]:
    """The fundamental mode φ = h/hr of the ``levels`` [(height above the base m, weight N)]:
    the roof height hr, Σwφ, Σwφ², W̄1, Γ1 and W."""
    above = [(h, w) for h, w in levels if h > 1e-6]
    weight = sum(w for _, w in levels)
    hr = max((h for h, _ in above), default=0.0)
    if hr <= 0:
        return {"hr": 0.0, "sum": 0.0, "square": 0.0, "W1": 0.0, "gamma": 0.0, "W": weight}
    s1 = sum(w * h / hr for h, w in above)
    s2 = sum(w * (h / hr) ** 2 for h, w in above)
    return {
        "hr": hr,
        "sum": s1,
        "square": s2,
        "W1": s1 * s1 / s2 if s2 else 0.0,
        "gamma": s1 / s2 if s2 else 0.0,
        "W": weight,
    }


def added_damping(
    braces: list[DamperBrace], axis: str, mode: dict[str, float], roof: float, period: float
) -> float:
    """βV (a fraction) of the devices at the roof displacement ``roof`` [m] and ``period``."""
    if roof <= 0 or mode["hr"] <= 0 or period <= 0:
        return 0.0
    omega = 2 * math.pi / period
    strain = 0.5 * omega**2 * roof**2 * mode["square"] / G
    if strain <= 0:
        return 0.0
    energy = sum(b.energy(roof * b.rise / mode["hr"] * b.cosine(axis), period) for b in braces)
    return energy / (4 * math.pi * strain)


def design_axis(
    braces: list[DamperBrace],
    axis: str,
    levels: list[tuple[float, float]],
    given: Axis,
    inherent: float,
    sa: Callable[[float], float],
) -> dict[str, Any]:
    """The damped equivalent lateral force of one direction by the pack's method (module
    notes); ``inherent``: βI (a fraction), ``sa``: the 5 % design spectrum [g] (R = I = 1)."""
    t = _table()
    mode = modal_values(levels)
    weight = mode["W"]
    t1 = given.period
    beta_i = min(inherent, t.inherentMax / 100) if t.inherentMax else inherent
    cap = t.maxDamping / 100 if t.maxDamping else math.inf

    def b_of(beta: float) -> float:
        return damping_coefficient(100 * min(beta, cap))

    def roof_of(period: float, b: float) -> float:
        return G / (4 * math.pi**2) * mode["gamma"] * sa(period) * period**2 / b

    notes: list[str] = []
    if t1 <= 0 or mode["hr"] <= 0 or weight <= 0:
        return {"available": False, "reason": "no period or no seismic weight"}
    factor = given.R / (given.Cd * given.omega) if given.Cd and given.omega else 1.0 / given.R
    mu = 1.0
    b1 = b_of(beta_i)
    roof = roof_of(t1, b1)
    beta_v = beta_h = 0.0
    duct = t.ductility if t.method == "modalStrength" else None
    cs = given.shear / weight if weight else 0.0
    yield_roof = (
        G / (4 * math.pi**2) * (given.omega * given.Cd / given.R) * mode["gamma"] * cs * t1**2
        if duct is not None and given.R
        else 0.0
    )
    ts = plateau_end(sa) if duct is not None else 0.0
    mu_max = (
        given.R / (given.omega * given.importance)
        if duct is not None and duct.maximum == "strengthRatio" and given.omega
        else math.inf
    )
    converged = False
    t1d = t1
    for _ in range(300):
        t1d = t1 * math.sqrt(mu)
        beta_v = added_damping(braces, axis, mode, roof, t1d)
        if duct is not None and mu > 1:
            qh = min(max(duct.qhFactor * ts / t1, duct.qhMin), duct.qhMax)
            beta_h = qh * (duct.hystereticBase - beta_i) * (1 - 1 / mu)
        else:
            beta_h = 0.0
        beta = beta_i + beta_v * math.sqrt(mu) + max(beta_h, 0.0)
        b1 = b_of(beta)
        new_roof = roof_of(t1d, b1)
        new_mu = mu
        if duct is not None and yield_roof > 0:
            new_mu = min(max(new_roof / yield_roof, 1.0), max(mu_max, 1.0))
        if abs(new_roof - roof) <= 1e-7 + 1e-5 * roof and abs(new_mu - mu) <= 1e-5:
            roof, mu, converged = new_roof, new_mu, True
            break
        roof = 0.5 * (roof + new_roof)
        mu = 0.5 * (mu + new_mu)
    if not converged:
        notes.append(f"{axis}: the iteration on the damping and the ductility did not converge")
    t1d = t1 * math.sqrt(mu)
    beta_total = beta_i + beta_v * math.sqrt(mu) + max(beta_h, 0.0)
    b1 = b_of(beta_total)
    b_vi = b_of(beta_i + beta_v)
    out: dict[str, Any] = {
        "available": True,
        "T1": t1,
        "T1D": t1d,
        "mu": mu,
        "W_kN": weight / 1e3,
        "W1_kN": mode["W1"] / 1e3,
        "Gamma1": mode["gamma"],
        "betaI": beta_i,
        "betaV": beta_v,
        "betaH": max(beta_h, 0.0),
        "beta": beta_total,
        "B1D": b1,
        "D1D_mm": roof * 1e3,
        "Vfixed_kN": given.shear / 1e3,
        "converged": converged,
    }
    if t.method == "modalStrength":
        cs1 = factor * sa(t1d) / b1
        tr = t.residualPeriodShare * t1
        b_r = b_of(beta_i + beta_v)
        cs_r = factor * sa(tr) / b_r
        v1 = cs1 * mode["W1"]
        v_r = cs_r * max(weight - mode["W1"], 0.0)
        shear = math.hypot(v1, v_r)
        out.update(
            {
                "Cs1": cs1, "CsR": cs_r, "TR": tr, "BR": b_r, "TS": ts,
                "V1_kN": v1 / 1e3, "VR_kN": v_r / 1e3, "DY_mm": yield_roof * 1e3,
            }
        )  # fmt: skip
    else:
        shear = given.shear * b_of(beta_i) / b_of(beta_i + beta_v)
    minimum = max(given.shear / b_vi, t.minimumShare * given.shear)
    design = max(shear, minimum)
    out.update(
        {
            "V_kN": shear / 1e3,
            "Vmin_kN": minimum / 1e3,
            "BVI": b_vi,
            "Vdesign_kN": design / 1e3,
            "ratio": design / given.shear if given.shear else 1.0,
            "governs": "damped" if design == shear else "minimum",
            "notes": notes,
        }
    )
    return out


def device_rows(
    braces: list[DamperBrace], by_axis: dict[str, dict[str, Any]], levels_hr: float
) -> list[dict[str, Any]]:
    """Each device at the design roof displacement of its governing direction and at the
    pack's earthquake level × mceFactor: stroke, velocity, force, energy, the checks."""
    t = _table()
    rows = []
    for b in braces:
        axis = "X" if b.cosine("X") >= b.cosine("Y") else "Y"
        found = by_axis.get(axis) or {}
        if not found.get("available") or levels_hr <= 0:
            continue
        roof = found["D1D_mm"] / 1e3
        period = found["T1D"]
        delta = roof * b.rise / levels_hr * b.cosine(axis)
        mce = delta * t.mceFactor
        velocity = 2 * math.pi * delta / period if period else 0.0
        velocity_mce = 2 * math.pi * mce / period if period else 0.0
        force = b.force(delta, velocity)
        force_mce = b.force(mce, velocity_mce)
        stroke_cap = b.spec.strokeCapacity
        force_cap = b.spec.forceCapacity
        rows.append(
            {
                "member": b.member, "type": b.type, "kind": b.spec.kind, "axis": axis,
                "nodes": list(b.nodes or ()),
                "angle_deg": math.degrees(math.asin(min(b.rise / b.length, 1.0)))
                if b.length else 0.0,
                "stroke_mm": delta * 1e3, "strokeMCE_mm": mce * 1e3,
                "velocity_ms": velocity, "velocityMCE_ms": velocity_mce,
                "force_kN": force / 1e3, "forceMCE_kN": force_mce / 1e3,
                "energy_kJ": b.energy(delta, period) / 1e3,
                "strokeCapacity_mm": stroke_cap, "forceCapacity_kN": force_cap,
                "strokeOk": None if stroke_cap is None else mce * 1e3 <= float(stroke_cap) + 1e-9,
                "forceOk": None if force_cap is None else force_mce / 1e3 <= float(force_cap) + 1e-9,
            }
        )  # fmt: skip
    return rows


# ─────────────────────────────────────── the analysis ───────────────────────────────────────


def _levels(project: dict[str, Any]) -> tuple[float, list[tuple[float, float]]]:
    """The base (the lowest support) and the seismic weight by height above it."""
    supports = [float(n["coords"][2]) for n in project["nodes"] if all(n.get("restraint") or [0])]
    base = min(supports, default=0.0)
    weights: dict[float, float] = {}
    for n in project["nodes"]:
        z = round(float(n["coords"][2]) - base, 3)
        mass = float((n.get("mass") or [0.0])[0])
        if mass > 0 and z >= -1e-3:
            weights[z] = weights.get(z, 0.0) + mass * G
    return base, sorted(weights.items())


def _pattern(project: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((p for p in project.get("load_patterns", []) if p.get("name") == name), None)


def _shear(project: dict[str, Any], case: str, axis: int) -> float:
    pattern = _pattern(project, case)
    if pattern is None:
        return 0.0
    return abs(sum(float(load["forces"][axis]) for load in pattern.get("nodal_loads", [])))


def apply_dampers(
    project: dict[str, Any],
    braces: list[DamperBrace],
    summary: dict[str, Any],
    settings: Any,
    values: dict[str, Any],
    isolated: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """The damper design of the derived ``project`` (its earthquake cases and spectra scaled
    in place, module notes): the summary for ``08 FEM/dampers.json`` and the notes."""
    from saengine.fem import loads as fl

    notes: list[str] = []
    base: dict[str, Any] = {
        "schema": SCHEMA,
        "devices": [
            {"member": b.member, "type": b.type, "kind": b.spec.kind, "nodes": list(b.nodes or ())}
            for b in braces
        ],
    }
    if not covered():
        pack = code_context.current()
        notes.append(
            f"dampers: the code pack {pack.name} does not cover structures with damping systems; "
            "the devices are modelled but the earthquake forces are not reduced for them"
        )
        return {**base, "available": False, "reason": notes[-1]}, notes
    t = _table()
    _, levels = _levels(project)
    mode = modal_values(levels)
    seismic = summary.get("seismic") or {}
    modal = summary.get("periodModal") or {}
    inherent = float(getattr(settings.seismic, "damping", None) or 0.05)

    def sa(period: float) -> float:
        return fl.design_acceleration(period, settings.site.siteClass, values["Z"], 1.0, 1.0, None)

    by_axis: dict[str, dict[str, Any]] = {}
    for a, k in (("X", 0), ("Y", 1)):
        period = float((modal.get(a) or {}).get("period") or 0.0) or float(
            (seismic.get(f"E{a}") or {}).get("period_s") or 0.0
        )
        given = Axis(
            shear=_shear(project, f"E{a}", k),
            period=period,
            R=float(values.get(f"R{a}") or values.get("R") or 1.0),
            Cd=float(values.get(f"Cd{a}") or values.get("Cd") or 1.0),
            omega=float(values.get(f"omega{a}") or values.get("omega") or 1.0),
            importance=float(values.get("seismicImportance") or 1.0),
        )
        if given.shear <= 0:
            by_axis[a] = {"available": False, "reason": f"no static earthquake case E{a}"}
            continue
        by_axis[a] = design_axis(braces, a, levels, given, inherent, sa)
        notes.extend(by_axis[a].pop("notes", []) if by_axis[a].get("available") else [])
    cl = clauses()
    # ── the analysis: the static cases and the response spectrum ──
    if isolated:
        notes.append(
            "dampers with seismic isolators: the isolation design sets the earthquake forces; "
            "the damped reduction is not applied"
        )
    else:
        for a, cases in _STATIC_CASES.items():
            found = by_axis.get(a) or {}
            if not found.get("available"):
                continue
            ratio = float(found["ratio"])
            for name in cases:
                pattern = _pattern(project, name)
                if pattern is None:
                    continue
                for load in pattern.get("nodal_loads", []):
                    load["forces"] = [float(v) * ratio for v in load["forces"]]
            notes.append(
                f"dampers E{a}: βI = {100 * found['betaI']:.1f} %, βV = "
                f"{100 * found['betaV']:.1f} %, β = {100 * found['beta']:.1f} %, B = "
                f"{found['B1D']:.2f}; V = {found['Vdesign_kN']:.0f} kN ({found['governs']}) of "
                f"the fixed-base {found['Vfixed_kN']:.0f} kN (× {ratio:.3f}; "
                f"{cl.get('baseShear', '')})"
            )
            if ratio > 1 + 1e-9:
                notes.append(
                    f"dampers E{a}: the damped base shear is more than the fixed-base one; the "
                    "larger is used"
                )
        # The analysis spectrum is already at the structure's damping (settings, else 5 %).
        b_spectrum = damping_coefficient(100 * inherent)
        for spectrum in project.get("spectra", []):
            a = "Y" if str(spectrum.get("name", "")).endswith("Y") else "X"
            found = by_axis.get(a) or {}
            if not found.get("available"):
                continue
            ratio = found["B1D"] / b_spectrum if b_spectrum else 1.0
            start = t.dampedFromShare * found["T1"]
            spectrum["accelerations"] = [
                round(float(acc) / (ratio if period >= start else 1.0), 6)
                for period, acc in zip(spectrum["periods"], spectrum["accelerations"], strict=True)
            ]
        if project.get("spectra"):
            notes.append(
                "dampers: the response spectrum ÷ B1D/B(ξ) from "
                f"{t.dampedFromShare:g} T1 up (SAEngine practice, see the pack's note)"
            )
    devices = device_rows(braces, by_axis, mode["hr"])
    for row in devices:
        for key, label in (("strokeOk", "stroke"), ("forceOk", "force")):
            if row[key] is False:
                notes.append(
                    f"{row['member']}: the damper's {label} at the maximum considered earthquake "
                    "exceeds its capacity"
                )
    requirements = [
        {"id": r.id, "text": r.text, "check": r.check, "ok": None} for r in t.requirements
    ]
    if t.note:
        notes.append(t.note)
    out = {
        **base,
        "available": True,
        "method": t.method,
        "mceFactor": t.mceFactor,
        "byAxis": by_axis,
        "devices": devices,
        "requirements": requirements,
        "review": list(t.review),
        "isolated": isolated,
        "notes": notes,
        "clauses": cl,
    }
    return out, notes


# ─────────────────────────────── the nonlinear time history ───────────────────────────────


def nonlinear_links(history: dict[str, Any], braces: list[DamperBrace], period: float) -> list[str]:
    """Each device of ``braces`` as a ``twoNodeLink`` between its brace ends in the nonlinear
    time history model ``history`` (in place, module notes); the braces' own sections then
    keep :data:`STATIC_SHARE` of their area. ``period``: T1 [s] (a viscoelastic damper's
    C = K″/ω1). Returns the notes."""
    sections = {int(s["id"]): s for s in history.get("sections", [])}
    nodes = {int(n["id"]) for n in history.get("nodes", [])}
    next_material = max((int(m["id"]) for m in history.get("materials", [])), default=0) + 1
    next_element = max((int(e["id"]) for e in history.get("elements", [])), default=0) + 1
    omega = 2 * math.pi / period if period > 0 else 0.0
    placed = 0
    skipped: list[str] = []
    for b in braces:
        if b.nodes is None or not set(b.nodes) <= nodes:
            skipped.append(b.member)
            continue
        spec = b.spec
        name = f"{b.member}{LINK_SUFFIX}"
        k0 = b.stiffness()
        if spec.kind == "viscous":
            material = {
                "type": "ViscousDamper",
                "K": b.axial if b.axial > 0 else 1e9,
                "Cd": float(spec.coefficient) * 1e3,
                "alpha": float(spec.exponent),
            }
        elif spec.kind == "viscoelastic":
            material = {
                "type": "Elastic",
                "E": float(spec.storageStiffness) * 1e3,
                "eta": float(spec.lossStiffness) * 1e3 / omega if omega else 0.0,
            }
        elif spec.kind == "metallic":
            if k0 <= 0:
                skipped.append(b.member)
                continue
            material = {
                "type": "Steel02",
                "Fy": float(spec.yieldForce) * 1e3,
                "E0": k0,
                "b": float(spec.postYieldRatio),
            }
        else:
            if k0 <= 0:
                skipped.append(b.member)
                continue
            material = {
                "type": "ElasticPP",
                "E": k0,
                "epsy_pos": float(spec.yieldForce) * 1e3 / k0,
            }
        history.setdefault("materials", []).append({"id": next_material, "name": name, **material})
        history["elements"].append(
            {
                "id": next_element,
                "name": name,
                "type": "TwoNodeLink",
                "nodes": list(b.nodes),
                "material_ids": [next_material],
                "dofs": [1],
            }
        )
        next_material += 1
        next_element += 1
        for sid in b.sections:
            section = sections.get(sid)
            if section is not None and b.area > 0:
                section["A"] = b.area * STATIC_SHARE
        placed += 1
    notes = []
    if placed:
        notes.append(
            f"nonlinear time history: {placed} dampers as twoNodeLink elements between their "
            "brace ends (viscous: Maxwell with the brace's EA/L; viscoelastic: Kelvin; "
            "metallic: Steel02; friction: elastic-perfectly-plastic)"
        )
    if skipped:
        notes.append("nonlinear time history: no damper link for " + ", ".join(sorted(skipped)))
    return notes


# ─────────────────────────────── reading it back ───────────────────────────────


def load(model_folder: str | Path) -> dict[str, Any] | None:
    """The damper design beside the analysis model (``08 FEM/dampers.json``), or None."""
    try:
        data = json.loads((Path(model_folder) / DAMPERS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None
