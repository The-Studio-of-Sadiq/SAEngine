"""Section capacity by fibre integration, for any designed section (Section Designer, 4 Objects):
moment-curvature at a given axial force, and the plastic P-M / M-M interaction of sections
without concrete (steel plates, built-up and hollow steel sections).

The interaction diagrams of reinforced-concrete sections stay where they are,
:class:`saengine.library.section_designer.DesignedRcSection` (concreteproperties with the
BNBC 2020 / ACI 318 stress block and the pack's φ); this module adds what that one does not
give, on the same section, materials and moment convention.

Fibres. Each region is meshed with sectionproperties at the Section Designer's mesh size
(:func:`saengine.library.section_designer.mesh_size`); every triangle is a fibre at its
centroid. Bars are point fibres of their area, and the concrete they displace is taken out by a
fibre of negative area at the bar.

Strain plane. Strains are compression positive: ε = ε0 + κ v, with v the distance from the
gross centroid normal to the neutral axis, towards the compression side. The neutral axis is at
angle θ from the x axis as in concreteproperties (θ = 0: compression on top, +Mx; θ = π:
compression at the bottom; θ = π/2: compression on the left). Forces are compression positive;
Mx = Σ F (y - cy), My = Σ F (x - cx), and the moment in the plane of bending is M = Σ F v =
Mx cos θ - My sin θ. Units: mm, MPa, N, N·mm, 1/mm.

Material laws (not design-code values, except where cited):

- concrete in compression: the Hognestad parabola (Hognestad 1951, as in Park and Paulay,
  "Reinforced Concrete Structures", 1975, Sec 2.1.3): f = f''c [2 ε/ε0 - (ε/ε0)²] up to
  ε0 = 2 f''c / Ec, then a straight line to 0.85 f''c at 0.0038, with f''c = 0.85 f'c (the
  stress intensity of BNBC 2020 Part 6 Sec 6.2.2 / ACI 318-19 Sec 22.2.2.4.1) and Ec the
  material's E (BNBC 2020 Part 6 Sec 6.1.7.1). The curve ends at the usable strain εcu = 0.003
  (BNBC 2020 Part 6 Sec 6.2.2 / ACI 318-19 Sec 22.2.2.1), which ends the analysis;
- concrete in tension: linear up to the modulus of rupture fr (the material's, else
  0.62 √f'c, BNBC 2020 Part 6 Eq. 6.6.3), nothing once cracked; it can be left out;
- bars and steel plates: elastic-perfectly plastic at fy, both signs; the analysis also ends
  when a steel fibre reaches the limit strain the engineer gives (default 0.05; BNBC sets no
  steel strain limit for flexure).

Key points of a moment-curvature curve: first cracking (concrete reaching fr), first yield
(the first steel fibre at fy; κy, My), the end (εcu in the concrete or the steel limit strain;
κu, Mu), the peak moment, the effective flexural stiffness EIeff = My / κy and the equal-energy
bilinear idealisation (an elastic branch of slope EIeff, a plateau Mn chosen so the areas under
the bilinear and the computed curve up to κu are equal; κ'y = Mn / EIeff), with the curvature
ductility μκ = κu / κ'y.

Plastic interaction of sections without concrete: rigid-plastic stress blocks, fy on either
side of a plastic neutral axis swept across the section at each angle: the cross-section's
yield surface (Pn, Mn). Design values use φ of the pack's ``steel`` table (BNBC 2020 Part 6
Chapter 10: ``compression`` for P >= 0, ``tensionYield`` for P < 0; ``flexure`` for M, the
least of the two for a point). It is a cross-section strength only: member buckling and local
buckling (BNBC 2020 Part 6 Sec 10.5 and Table 6.10.1) are not part of it.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.library.section_designer import (
    DesignedSection,
    SectionError,
    _mat,
    _polygon,
    mesh_size,
)

#: Strain at the end of the Hognestad curve's descending branch (Hognestad 1951).
HOGNESTAD_EPS_END = 0.0038
#: Stress at that strain, as a share of f''c.
HOGNESTAD_RESIDUAL = 0.85
#: f''c / f'c: the stress intensity of the rectangular block (BNBC 2020 Part 6 Sec 6.2.2).
STRESS_INTENSITY = 0.85
#: Default limit strain of bars and plates for the end of a moment-curvature curve.
DEFAULT_STEEL_LIMIT = 0.05

#: Mesh refinement of the plastic interaction's fibres.
PLASTIC_REFINE = 4.0

_CONCRETE, _STEEL = 0, 1


@dataclass(frozen=True)
class Fibres:
    """The section as fibres: centroid x, y [mm], area [mm²] (negative: concrete displaced by
    a bar), kind (0 concrete, 1 steel), E, f'c or fy, fr [MPa], and the gross centroid."""

    x: np.ndarray
    y: np.ndarray
    area: np.ndarray
    kind: np.ndarray
    E: np.ndarray
    strength: np.ndarray  # f'c of concrete, fy of steel
    fr: np.ndarray  # concrete modulus of rupture (0 for steel)
    cx: float
    cy: float
    #: Where strains are checked (cracking, yield, the limit strains): the corners of the
    #: regions and the bar centres, so the extreme fibres are the section's own and not the
    #: centroids of the mesh's triangles. x, y [mm], kind, and the strain of cracking
    #: (concrete, fr / Ec) or yield (steel, fy / Es).
    px: np.ndarray = field(default_factory=lambda: np.zeros(0))
    py: np.ndarray = field(default_factory=lambda: np.zeros(0))
    pkind: np.ndarray = field(default_factory=lambda: np.zeros(0))
    pstrain: np.ndarray = field(default_factory=lambda: np.zeros(0))

    @property
    def concrete(self) -> np.ndarray:
        return self.kind == _CONCRETE

    @property
    def steel(self) -> np.ndarray:
        return self.kind == _STEEL

    def v(self, theta: float) -> np.ndarray:
        """Distance from the centroid normal to a neutral axis at ``theta``, towards
        compression [mm]."""
        return -(self.x - self.cx) * math.sin(theta) + (self.y - self.cy) * math.cos(theta)

    def pv(self, theta: float) -> np.ndarray:
        """As :meth:`v`, for the check points."""
        return -(self.px - self.cx) * math.sin(theta) + (self.py - self.cy) * math.cos(theta)


def _triangles(polygon: Any, size: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centroids and areas of the mesh of a shapely polygon (sectionproperties' mesher)."""
    from sectionproperties.pre.geometry import Geometry

    geometry = Geometry(polygon)
    geometry.create_mesh(mesh_sizes=size)
    vertices = np.asarray(geometry.mesh["vertices"], dtype=float)
    corners = vertices[np.asarray(geometry.mesh["triangles"])[:, :3]]
    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    area = 0.5 * np.abs(
        (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    )
    centroid = corners.mean(axis=1)
    return centroid[:, 0], centroid[:, 1], area


def _modulus_of_rupture(materials: Any, material_id: str, fc: float) -> float:
    """The material's fr, else 0.62 √f'c (BNBC 2020 Part 6 Eq. 6.6.3, normal-weight)."""
    from saengine.library.materials import MaterialLibrary

    found = (
        materials.get(material_id)
        if isinstance(materials, MaterialLibrary)
        else next((m for m in materials if m.id == material_id), None)
    )
    ft = found.concrete.ft if found is not None and found.concrete else None
    return ft if ft else 0.62 * math.sqrt(fc)


def fibres(section: DesignedSection, materials: Any, refine: float = 1.0) -> Fibres:
    """The section's fibres (see the module's notes); ``refine`` divides the mesh size."""
    from shapely.geometry import Point as ShapelyPoint

    size = mesh_size(section) / refine
    parts: list[tuple[np.ndarray, ...]] = []
    checks: list[tuple[float, float, int, float]] = []
    polygons = []
    total = 0.0
    sx = sy = 0.0
    for region in section.regions:
        m = _mat(materials, region.material)
        polygon = _polygon(region)
        polygons.append((polygon, m))
        total += polygon.area
        sx += polygon.centroid.x * polygon.area
        sy += polygon.centroid.y * polygon.area
        x, y, a = _triangles(polygon, size)
        if m.category == "concrete":
            if not m.fc:
                raise SectionError(f"concrete '{m.id}' has no f'c")
            kind, strength = _CONCRETE, m.fc
            fr = _modulus_of_rupture(materials, m.id, m.fc)
        else:
            if not m.fy:
                raise SectionError(f"steel '{m.id}' has no fy")
            kind, strength, fr = _STEEL, m.fy, 0.0
        limit = fr / m.E if kind == _CONCRETE else strength / m.E
        for ring in (region.outline, *region.holes):
            checks.extend((px, py, kind, limit) for px, py in ring)
        n = len(a)
        parts.append(
            (x, y, a, np.full(n, kind), np.full(n, m.E), np.full(n, strength), np.full(n, fr))
        )
    for bar in section.bars:
        m = _mat(materials, bar.material or section.rebar or "")
        if not m.fy:
            raise SectionError(f"bar material '{m.id}' has no fy")
        area = math.pi * bar.dia**2 / 4
        checks.append((bar.x, bar.y, _STEEL, m.fy / m.E))
        parts.append(
            (
                np.array([bar.x]),
                np.array([bar.y]),
                np.array([area]),
                np.array([_STEEL]),
                np.array([m.E]),
                np.array([m.fy]),
                np.array([0.0]),
            )
        )
        host = next(
            (
                (p, pm)
                for p, pm in polygons
                if pm.category == "concrete" and p.contains(ShapelyPoint(bar.x, bar.y))
            ),
            None,
        )
        if host is not None:
            _, pm = host
            parts.append(
                (
                    np.array([bar.x]),
                    np.array([bar.y]),
                    np.array([-area]),
                    np.array([_CONCRETE]),
                    np.array([pm.E]),
                    np.array([pm.fc]),
                    np.array([_modulus_of_rupture(materials, pm.id, pm.fc or 0.0)]),
                )
            )
    columns = [np.concatenate(c) for c in zip(*parts, strict=True)]
    px, py, pkind, pstrain = (np.array(c, dtype=float) for c in zip(*checks, strict=True))
    return Fibres(
        *columns, cx=sx / total, cy=sy / total, px=px, py=py, pkind=pkind, pstrain=pstrain
    )


# ─────────────────────────────────────── stresses ───────────────────────────────────────


def concrete_stress(
    eps: np.ndarray, fc: np.ndarray, ec: np.ndarray, fr: np.ndarray, tension: bool
) -> np.ndarray:
    """Concrete stress [MPa], compression positive: the Hognestad curve, and the linear
    tension branch up to fr when ``tension`` (see the module's notes)."""
    fpp = STRESS_INTENSITY * fc
    eps0 = 2 * fpp / ec
    rising = fpp * (2 * eps / eps0 - (eps / eps0) ** 2)
    slope = (1 - HOGNESTAD_RESIDUAL) / np.maximum(HOGNESTAD_EPS_END - eps0, 1e-9)
    falling = fpp * np.maximum(1 - slope * (eps - eps0), 0.0)
    stress = np.where(eps <= eps0, rising, falling)
    stress = np.where(eps > 0, stress, 0.0)
    if tension:
        cracking = fr / ec
        stress = np.where((eps <= 0) & (-eps <= cracking), ec * eps, stress)
    return stress


def steel_stress(eps: np.ndarray, fy: np.ndarray, es: np.ndarray) -> np.ndarray:
    """Elastic-perfectly plastic stress [MPa], both signs."""
    return np.clip(es * eps, -fy, fy)


# ─────────────────────────────────── moment-curvature ───────────────────────────────────


@dataclass
class _Plane:
    """The fibres' stresses for one strain plane."""

    fibres: Fibres
    v: np.ndarray
    tension: bool
    #: Largest v of the concrete (None: no concrete): ε0 is kept so that this fibre stays
    #: within the Hognestad curve, where the axial force still grows with ε0.
    v_top: float | None = None

    def stresses(self, eps0: float, kappa: float) -> tuple[np.ndarray, np.ndarray]:
        f = self.fibres
        eps = eps0 + kappa * self.v
        stress = np.where(
            f.concrete,
            concrete_stress(eps, f.strength, f.E, f.fr, self.tension),
            steel_stress(eps, f.strength, f.E),
        )
        return eps, stress

    def axial(self, eps0: float, kappa: float) -> float:
        _, stress = self.stresses(eps0, kappa)
        return float(np.dot(stress, self.fibres.area))

    def solve(self, p: float, kappa: float) -> float | None:
        """ε0 so that the fibres carry the axial force ``p`` at curvature ``kappa``, or None
        if the section cannot (beyond its squash load or full tension)."""
        span = abs(kappa) * float(np.max(np.abs(self.v))) + 0.02
        lo, hi = -span, span
        if self.v_top is not None:
            hi = max(min(hi, HOGNESTAD_EPS_END - kappa * self.v_top), lo + 1e-9)
        n_lo, n_hi = self.axial(lo, kappa) - p, self.axial(hi, kappa) - p
        if n_lo > 0 or n_hi < 0:
            return None
        for _ in range(70):
            mid = 0.5 * (lo + hi)
            n_mid = self.axial(mid, kappa) - p
            if n_mid < 0:
                lo = mid
            else:
                hi = mid
            if hi - lo < 1e-12:
                break
        return 0.5 * (lo + hi)


def moment_curvature(
    section: DesignedSection,
    materials: Any,
    axial: float = 0.0,
    theta: float = 0.0,
    tension: bool = True,
    steel_limit: float = DEFAULT_STEEL_LIMIT,
    steps: int = 60,
) -> dict[str, Any]:
    """The moment-curvature curve of the section under the axial force ``axial`` [N,
    compression positive] with the neutral axis at ``theta`` [rad]: ``points`` (κ [1/mm], M,
    Mx, My [N·mm], εc,max, εs,max, neutral-axis depth c [mm]), the key points (``cracking``,
    ``yield``, ``ultimate``, ``peak``), ``EIeff`` [N·mm²], the ``bilinear`` idealisation and
    ``ductility``; ``end`` says what ended it. Raises SectionError if the section cannot carry
    the axial force."""
    f = fibres(section, materials)
    v = f.v(theta)
    pv = f.pv(theta)
    p_conc = f.pkind == _CONCRETE
    p_steel = f.pkind == _STEEL
    has_concrete = bool(p_conc.any())
    has_steel = bool(p_steel.any())
    plane = _Plane(f, v, tension, float(pv[p_conc].max()) if has_concrete else None)
    depth = float(pv.max() - pv.min())
    top = float(pv.max())
    if plane.solve(axial, 0.0) is None:
        raise SectionError("the section cannot carry this axial force")

    from saengine.design.rc import EPS_CU

    def state(kappa: float) -> dict[str, float] | None:
        eps0 = plane.solve(axial, kappa)
        if eps0 is None:
            return None
        _eps, stress = plane.stresses(eps0, kappa)
        force = stress * f.area
        mx = float(np.dot(force, f.y - f.cy))
        my = float(np.dot(force, f.x - f.cx))
        pe = eps0 + kappa * pv
        return {
            "kappa": kappa,
            "M": mx * math.cos(theta) - my * math.sin(theta),
            "Mx": mx,
            "My": my,
            "epsC": float(pe[p_conc].max()) if has_concrete else 0.0,
            "epsS": float(np.abs(pe[p_steel]).max()) if has_steel else 0.0,
            "steelRatio": float((np.abs(pe[p_steel]) / f.pstrain[p_steel]).max())
            if has_steel
            else 0.0,
            "crackRatio": float((-pe[p_conc] / f.pstrain[p_conc]).max()) if has_concrete else 0.0,
            "c": (eps0 + kappa * top) / kappa if kappa > 0 else math.inf,
        }

    def failed(s: dict[str, float]) -> str | None:
        if has_concrete and s["epsC"] >= EPS_CU:
            return "concrete"
        if has_steel and s["epsS"] >= steel_limit:
            return "steel"
        return None

    # Curvature steps: a fine start (cracking, yield) then growing to the end.
    yield_strain = float(np.min(f.pstrain[p_steel])) if has_steel else 0.002
    reference = max(yield_strain, 0.001) / max(depth, 1.0)
    ladder = np.concatenate(
        [np.linspace(0.02, 1.0, steps // 3), np.geomspace(1.05, 400.0, steps - steps // 3)]
    )
    points = [state(0.0)]
    end = "limit"
    last_ok = 0.0
    for k in ladder:
        kappa = float(k * reference)
        s = state(kappa)
        if s is None:
            end = "axial"
            break
        reason = failed(s)
        if reason is not None:
            # The end: bisect between the last good curvature and this one.
            lo, hi = last_ok, kappa
            final = None
            for _ in range(40):
                mid = 0.5 * (lo + hi)
                sm = state(mid)
                if sm is None or failed(sm):
                    hi = mid
                else:
                    lo, final = mid, sm
            if final is not None and final["kappa"] > points[-1]["kappa"]:
                points.append(final)
            end = reason
            break
        points.append(s)
        last_ok = kappa
    points = [p for p in points if p is not None]

    def crossing(key: str, target: float) -> dict[str, float] | None:
        """The point where ``key`` first reaches ``target``, refined by bisection on κ."""
        for a, b in itertools.pairwise(points):
            if a[key] < target <= b[key]:
                lo, hi = a["kappa"], b["kappa"]
                best = b
                for _ in range(40):
                    mid = 0.5 * (lo + hi)
                    sm = state(mid)
                    if sm is None:
                        break
                    if sm[key] >= target:
                        hi, best = mid, sm
                    else:
                        lo = mid
                return best
        return None

    cracking = crossing("crackRatio", 1.0) if tension and has_concrete else None
    first_yield = crossing("steelRatio", 1.0) if has_steel else None
    ultimate = points[-1]
    peak = max(points, key=lambda p: p["M"])
    result: dict[str, Any] = {
        "axial": axial,
        "theta": theta,
        "tension": tension,
        "steelLimit": steel_limit,
        "end": end,
        "points": [_row(p) for p in points],
        "cracking": _row(cracking) if cracking else None,
        "yield": _row(first_yield) if first_yield else None,
        "ultimate": _row(ultimate),
        "peak": _row(peak),
        "EIeff": None,
        "bilinear": None,
        "ductility": None,
    }
    if first_yield and first_yield["kappa"] > 0 and ultimate["kappa"] > first_yield["kappa"]:
        stiffness = first_yield["M"] / first_yield["kappa"]
        bilinear = equal_energy_bilinear(
            [p["kappa"] for p in points], [p["M"] for p in points], stiffness
        )
        result["EIeff"] = stiffness
        if bilinear is not None:
            mn, kappa_y = bilinear
            result["bilinear"] = {"Mn": mn, "kappaY": kappa_y, "kappaU": ultimate["kappa"]}
            result["ductility"] = ultimate["kappa"] / kappa_y
    return result


def _row(p: dict[str, float]) -> dict[str, float | None]:
    return {
        "kappa": p["kappa"],
        "M": p["M"],
        "Mx": p["Mx"],
        "My": p["My"],
        "epsC": p["epsC"],
        "epsS": p["epsS"],
        "c": p["c"] if math.isfinite(p["c"]) else None,
    }


def equal_energy_bilinear(
    kappa: list[float], moment: list[float], stiffness: float
) -> tuple[float, float] | None:
    """The plateau Mn and yield curvature κ'y = Mn / K of the elastic-perfectly plastic line of
    slope ``stiffness`` K with the same area under it up to the last κ as the curve (trapezoids):
    Mn κu - Mn² / (2 K) = A, so Mn = K (κu - √(κu² - 2 A / K)). None if no real root."""
    if len(kappa) < 2 or stiffness <= 0:
        return None
    area = float(np.trapezoid(moment, kappa))
    ku = kappa[-1]
    disc = ku**2 - 2 * area / stiffness
    if disc < 0:
        return None
    mn = stiffness * (ku - math.sqrt(disc))
    return mn, mn / stiffness


# ─────────────────────────────── plastic interaction (steel) ───────────────────────────────


def _steel_phi(pack: Any) -> dict[str, float]:
    """φ of the pack's ``steel`` table (BNBC 2020 Part 6 Chapter 10)."""
    if pack is None:
        from saengine.codes import context

        pack = context.current()
    phi = pack.table("steel").phi
    return {
        "compression": float(phi["compression"]),
        "tension": float(phi["tensionYield"]),
        "flexure": float(phi["flexure"]),
    }


class PlasticSection:
    """The cross-section yield surface of a section without concrete (see the module's
    notes): the same row format as :class:`saengine.library.section_designer.DesignedRcSection`
    (``uniaxial``, ``surface``, ``contour``) so the Section Designer shows both alike."""

    def __init__(self, section: DesignedSection, materials: Any, pack: Any = None) -> None:
        # A finer mesh: rigid-plastic stresses jump at the neutral axis, which cuts fibres.
        self.fibres = fibres(section, materials, refine=PLASTIC_REFINE)
        if self.fibres.concrete.any():
            raise SectionError("the section has concrete: its capacity is the RC one")
        self.phi = _steel_phi(pack)
        f = self.fibres
        self.squash = float(np.dot(f.strength, f.area))  # Py = Σ fy A
        self.centroid = (f.cx, f.cy)

    def _phi_of(self, p: float) -> float:
        axial = self.phi["compression"] if p >= 0 else self.phi["tension"]
        return min(axial, self.phi["flexure"])

    def point(self, theta: float, offset: float) -> dict[str, float]:
        """Rigid-plastic actions with the plastic neutral axis at ``offset`` [mm] along v."""
        f = self.fibres
        v = f.v(theta)
        stress = np.where(v >= offset, f.strength, -f.strength)
        force = stress * f.area
        p = float(force.sum())
        mx = float(np.dot(force, f.y - f.cy))
        my = float(np.dot(force, f.x - f.cx))
        phi = self._phi_of(p)
        return {
            "P": p,
            "Mx": mx,
            "My": my,
            "phi": phi,
            "phiP": phi * p,
            "phiMx": phi * mx,
            "phiMy": phi * my,
            "phiPcapped": phi * p,
            "epsT": math.inf,
        }

    def meridian(self, theta: float, count: int = 24) -> list[dict[str, float]]:
        """From full tension to full compression: the plastic neutral axis swept from the
        compression-side extreme to the far one."""
        v = self.fibres.v(theta)
        top, bottom = float(v.max()), float(v.min())
        offsets = np.linspace(top + 1e-6, bottom - 1e-6, count)
        return [self.point(theta, float(o)) for o in offsets]

    def uniaxial(self, axis: str = "x", count: int = 24) -> dict[str, Any]:
        thetas = (0.0, math.pi) if axis == "x" else (-math.pi / 2, math.pi / 2)
        key = "Mx" if axis == "x" else "My"
        branches = []
        for theta in thetas:
            branches.append(
                [
                    {
                        "P": r["P"],
                        "M": r[key],
                        "phiP": r["phiPcapped"],
                        "phiM": r["phi" + key],
                        "phi": r["phi"],
                        "epsT": None,
                    }
                    for r in self.meridian(theta, count)
                ]
            )
        first, second = branches
        return {
            "axis": axis,
            "points": [*first, *reversed(second)],
            "phiPnMax": self.phi["compression"] * self.squash,
            "phiTension": self.phi["tension"] * self.squash,
            "p0": self.squash,
        }

    def contour(self, p: float, angles: int = 72) -> list[dict[str, float]] | None:
        """The (Mx, My) contour at axial force ``p`` [N]: at each neutral-axis angle the
        plastic neutral axis that gives ``p`` (bisection; the force falls as the axis moves to
        the compression side). None beyond the squash load."""
        if abs(p) >= self.squash:
            return None
        rows = []
        for k in range(angles):
            theta = -math.pi + 2 * math.pi * k / angles
            v = self.fibres.v(theta)
            lo, hi = float(v.min()) - 1e-6, float(v.max()) + 1e-6  # P(lo) = +Py, P(hi) = -Py
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                if self.point(theta, mid)["P"] > p:
                    lo = mid
                else:
                    hi = mid
            row = self.point(theta, 0.5 * (lo + hi))
            phi = self._phi_of(p)
            rows.append(
                {
                    "theta": theta,
                    "Mx": row["Mx"],
                    "My": row["My"],
                    "phiMx": phi * row["Mx"],
                    "phiMy": phi * row["My"],
                }
            )
        return rows


# ─────────────────────────────────────── M-M (RC) ───────────────────────────────────────


def rc_contour(
    rc: Any, p: float, angles: int = 24, count: int = 10
) -> list[dict[str, float]] | None:
    """The (φMx, φMy) and nominal contour of a
    :class:`saengine.library.section_designer.DesignedRcSection` at the factored axial force
    ``p`` [N]: on each meridian (concreteproperties, the pack's φ) the crossing of φP = p
    nearest the origin, interpolated; the nominal moments at the same neutral axis. None if a
    meridian never reaches ``p`` (beyond φPn,max or the tension capacity)."""
    rows = []
    for k in range(angles):
        theta = -math.pi + 2 * math.pi * k / angles
        meridian = rc.meridian(theta, count)
        best = None
        for a, b in itertools.pairwise(meridian):
            lo, hi = a["phiPcapped"] - p, b["phiPcapped"] - p
            if lo == hi or lo * hi > 0:
                continue
            t = lo / (lo - hi)
            row = {key: a[key] + t * (b[key] - a[key]) for key in ("Mx", "My", "phiMx", "phiMy")}
            row["theta"] = theta
            reach = math.hypot(row["phiMx"], row["phiMy"])
            if best is None or reach < best[0]:
                best = (reach, row)
        if best is None:
            return None
        rows.append(best[1])
    return rows
