"""Along-wind loads of tall or flexible buildings by the gust factor method (a code pack's
``wind.speedFactors.gustFactor``; the form of IS 875 (Part 3):2015 Clause 10).

The along-wind force at height z is the force coefficient times the area times the hourly mean
design pressure times the gust factor:

    F(z) = Cf A p̄(z) G,   p̄(z) = K airFactor V̄(z)²,   V̄(z) = Vb k1 k̄2(z) k3 k4
    G = 1 + r √(gv² Bs (1 + φ)² + Hs gR² S E / β)

with r = 2 Ih (Ih the turbulence intensity at the roof height h), Bs = 1 / (1 + √(c1 (h - s)²
+ c2 bsh²) / Lh) the background factor (s = 0: the base, bsh the mean breadth), Lh =
coefficient (h/10)^0.25 the integral turbulence length, φ = gv Ih √Bs / 2, Hs = 1 + (s/h)²,
S = 1 / ((1 + c1 f0 h / V̄h)(1 + c2 f0 b / V̄h)) the size reduction, E = π N / (1 + c1 N²)^c2
the spectrum of the turbulence at N = f0 Lh / V̄h, gR = √(2 ln(duration f0)) the peak factor of
the resonant part and β the damping ratio. Every coefficient is the pack's.

SAEngine applies it to the storey forces of the static method: the wind cases (and their
torsion cases) scale level by level by ``G (k̄2 / k2)²``, the ratio of the gust factor method's
pressure to the static design pressure at the level (the same K, k1, k3, k4 and wall
coefficients: SAEngine practice; the code's Cf is taken as the wall coefficients' sum).

The method applies when h / b is above ``heightRatio`` or the first frequency f0 is below
``frequencyLimit``.

Units: m, m/s, Hz.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context


def rules() -> Any | None:
    """The pack's ``wind.speedFactors.gustFactor`` (None: not the pack's method)."""
    table = code_context.table("wind")
    if getattr(table, "method", None) != "speedFactors":
        return None
    return getattr(getattr(table, "speedFactors", None), "gustFactor", None)


def applies(height: float, breadth: float, frequency: float) -> bool:
    """Whether the building is tall (h / b) or flexible (f0) enough for the method."""
    r = rules()
    if r is None:
        return False
    return (breadth > 0 and height / breadth > r.heightRatio) or frequency < r.frequencyLimit


def mean_factor(height: float, exposure: str) -> float:
    """k̄2, the hourly mean speed factor at ``height`` in terrain ``exposure``."""
    from saengine.fem.wind_speed_factors import _interpolate

    rows = rules().meanFactors
    if exposure not in rows:
        raise ValueError(f"no hourly mean speed factors for terrain '{exposure}' in the code pack")
    return _interpolate(rows[exposure], max(float(height), 0.0))


def dynamic_form(r: Any | None = None) -> bool:
    """Alpha 9 C18b: whether the pack's factor is the dynamic response factor Cdyn on the
    design pressure (AS/NZS 1170.2 Section 6 type) rather than G on the mean pressure."""
    r = r if r is not None else rules()
    return r is not None and getattr(r, "form", "gustFactor") == "dynamicResponse"


def turbulence(height: float, exposure: str) -> float:
    """Iz, the turbulence intensity at ``height`` in terrain ``exposure`` (alpha 9 C18b: from
    the pack's ``turbulencePoints`` of the terrain where it gives them)."""
    r = rules()
    points = (getattr(r, "turbulencePoints", None) or {}).get(exposure)
    if points:
        from saengine.fem.wind_speed_factors import _interpolate

        return max(_interpolate(points, max(float(height), 0.0)), 0.0)
    if r.turbulence is None:
        raise ValueError(f"no turbulence intensity for terrain '{exposure}' in the code pack")
    a1, b1, a4, b4 = r.turbulence
    terrains = sorted(r.roughness)
    first, last = terrains[0], terrains[-1]
    z = max(float(height), 10.0 * r.roughness[first], 1e-3)
    i1 = a1 - b1 * math.log10(z / r.roughness[first])
    i4 = a4 - b4 * math.log10(max(z, r.roughness[last] * 1.0001) / r.roughness[last])
    share = r.terrainShares.get(exposure, 0.0)
    return max(i1 + share * (i4 - i1), 0.0)


def gust_factor(
    height: float,
    breadth: float,
    frequency: float,
    speed: float,
    exposure: str,
    importance: float,
    damping: float | None = None,
) -> dict[str, float]:
    """G and its terms for a building ``height`` tall and ``breadth`` wide across the wind with
    the first frequency ``frequency`` [Hz], at the basic wind speed ``speed`` [m/s]."""
    from saengine.fem.wind_speed_factors import factors

    r = rules()
    h = max(float(height), 1e-3)
    top = factors(h, speed, exposure, importance)
    if dynamic_form(r):
        return _dynamic_response(r, h, breadth, frequency, top, exposure, damping)
    vh = float(speed) * top["k1"] * mean_factor(h, exposure) * top["k3"] * top["k4"]
    ih = turbulence(h, exposure)
    rough = 2.0 * ih
    lh = r.scaleCoefficients.get(exposure, max(r.scaleCoefficients.values())) * (h / 10) ** 0.25
    c1, c2 = r.backgroundTerms
    bs = 1.0 / (1.0 + math.sqrt(c1 * h**2 + c2 * breadth**2) / lh)
    phi = r.peakFactor * ih * math.sqrt(bs) / 2
    hs = 1.0
    s1, s2 = r.sizeTerms
    size = 1.0 / ((1 + s1 * frequency * h / vh) * (1 + s2 * frequency * breadth / vh))
    n = frequency * lh / vh
    e1, e2 = r.spectrumTerms
    spectrum = math.pi * n / (1 + e1 * n**2) ** e2
    gr = math.sqrt(2 * math.log(max(r.duration * frequency, 1.0001)))
    beta = float(damping) if damping else r.damping
    g = 1 + rough * math.sqrt(
        r.peakFactor**2 * bs * (1 + phi) ** 2 + hs * gr**2 * size * spectrum / beta
    )
    return {
        "G": g,
        "Ih": ih,
        "r": rough,
        "Lh": lh,
        "Bs": bs,
        "phi": phi,
        "S": size,
        "E": spectrum,
        "N": n,
        "gR": gr,
        "beta": beta,
        "Vh": vh,
    }


def _dynamic_response(
    r: Any,
    h: float,
    breadth: float,
    frequency: float,
    top: dict[str, float],
    exposure: str,
    damping: float | None,
) -> dict[str, float]:
    """Alpha 9 C18b: Cdyn = [1 + 2 Ih √(gv² Bs + Hs gR² S Et / ζ)] / (1 + 2 gv Ih) (the
    AS/NZS 1170.2 6.2.2 form) with Vdes,h the design speed at h (``top``), the mean speed
    V̄h = Vdes,h / (1 + gv Ih) in S and N, Lh = coefficient (h/10)^0.25, Bs = 1 / (1 +
    √(c1 h² + c2 b²) / Lh) (s = 0, Hs = 1: the base), S = 1 / ((1 + c1 n h / V̄h)(1 + c2 n b /
    V̄h)), Et = π N / (1 + c1 N²)^c2, N = n Lh / V̄h, gR = √(2 ln(duration n)). Returned as
    "G" (with the terms), applied to the design pressure of every level."""
    ih = turbulence(h, exposure)
    gv = r.peakFactor
    vh = float(top["Vz"]) / (1 + gv * ih)
    lh = r.scaleCoefficients.get(exposure, max(r.scaleCoefficients.values())) * (h / 10) ** 0.25
    c1, c2 = r.backgroundTerms
    bs = 1.0 / (1.0 + math.sqrt(c1 * h**2 + c2 * breadth**2) / lh)
    hs = 1.0
    s1, s2 = r.sizeTerms
    size = 1.0 / ((1 + s1 * frequency * h / vh) * (1 + s2 * frequency * breadth / vh))
    n = frequency * lh / vh
    e1, e2 = r.spectrumTerms
    spectrum = math.pi * n / (1 + e1 * n**2) ** e2
    gr = math.sqrt(2 * math.log(max(r.duration * frequency, 1.0001)))
    zeta = float(damping) if damping else r.damping
    cdyn = (1 + 2 * ih * math.sqrt(gv**2 * bs + hs * gr**2 * size * spectrum / zeta)) / (
        1 + 2 * gv * ih
    )
    return {
        "G": cdyn,
        "Ih": ih,
        "r": 2.0 * ih,
        "Lh": lh,
        "Bs": bs,
        "phi": 0.0,
        "S": size,
        "E": spectrum,
        "N": n,
        "gR": gr,
        "beta": zeta,
        "Vh": vh,
    }


def level_ratio(z: float, g: float, exposure: str) -> float:
    """The gust factor method's pressure over the static design pressure at height ``z``:
    G (k̄2 / k2)²; alpha 9 C18b: Cdyn itself in the dynamic response form (it acts on the
    design pressure)."""
    from saengine.fem.wind_speed_factors import height_factor

    if dynamic_form():
        return g

    k2 = height_factor(z, exposure)
    return g * (mean_factor(z, exposure) / k2) ** 2 if k2 > 0 else g
