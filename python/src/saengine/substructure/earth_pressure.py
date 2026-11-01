"""Lateral earth and groundwater pressure: the one engine every part uses.

The basement and retaining walls (:mod:`saengine.substructure.retaining_walls`), the outer walls
of ground tanks (:mod:`saengine.plumbing.tanks`), the basement walls of the analysis model (load
case H, :mod:`saengine.fem.derive`) and, later, excavation shoring take their pressures from
here. The soil is a column of layers from 1 Soil Report (Part 1: the nearest borehole's
layers, linked, never copied; :func:`soil_column`) or assumed values.

Pressure at depth z below the retained ground (z in m, kPa; the submerged unit weight of the
soil plus the full hydrostatic pressure below the water table, as the default pack's BNBC 2020
Part 6 Sec 2.6.5.1 asks)::

    p(z) = K σ'v(z) ∓ 2 c' √K + K q + u(z)

- σ'v: the layers' unit weights, submerged (γsat - γw) below the design water table, integrated
  exactly between the layers' boundaries and the water table; u = γw (z - zw) below it.
- K by the state of the soil:
  - at rest (a wall that cannot move: basement walls propped by the floors, tank walls):
    ``K0 = 1 - sin φ'`` (Jaky 1944), times ``OCR^sin φ'`` (Mayne & Kulhawy 1982) for an
    overconsolidated layer; a layer without φ' takes ``k0_cohesive`` (0.6 by default);
  - active (a wall free to rotate away from the soil, a cantilever retaining wall): Rankine
    ``Ka = cos β (cos β - √(cos²β - cos²φ')) / (cos β + √(cos²β - cos²φ'))`` with a backfill
    sloping at β (``(1 - sin φ') / (1 + sin φ')`` level), or Coulomb with wall friction δ and
    a battered back (:func:`ka_coulomb`); the cohesion term ``- 2 c' √Ka`` with the tension
    zone set to zero (no tension between soil and wall);
  - passive (resisting soil in front of a wall): Rankine ``Kp`` and ``+ 2 c' √Kp``.
  A layer without φ' (clay given by cu only) is taken at rest with ``k0_cohesive`` for the
  active and at-rest states (long term, on the safe side), and with ``Kp = 1``, ``+ 2 cu``
  (undrained) for the passive state.
- q: a uniform surcharge on the retained ground (kPa), times K at every depth.

Seismic increment (the default pack's code has no clause on seismic earth pressure; the
public methods it rests on):
- a wall that can yield: Mononobe-Okabe (Okabe 1926, Mononobe & Matsuo 1929; AASHTO LRFD
  11.6.5.3 and Appendix A11), ``ΔKae = Kae - Ka`` with kh = half the peak ground acceleration
  (AASHTO LRFD 11.6.5.2.2, a wall free to move 25-50 mm), the increment
  ``ΔPae = ½ γ H² ΔKae`` acting at 0.6 H above the base (Seed & Whitman 1970);
- a wall that cannot yield (basement walls): Wood (1973), ``ΔPe = kh γ H²`` with kh the full
  peak ground acceleration, acting at 0.5 H (a uniform pressure ``kh γ H``).
The peak ground acceleration is the project's, by the code pack's ``seismic.pgaFactor``
(``(2/3) Z S`` in the default pack; :func:`saengine.fem.ssi.peak_acceleration`).

Units: depths in m below the retained ground, kPa, kN/m³, kN/m and kN·m/m per metre run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, Literal

#: Unit weight of water [kN/m³].
GAMMA_W = 9.81

State = Literal["atRest", "active", "passive"]

#: Readable names of the states, for the reports.
STATES = {"atRest": "at rest", "active": "active", "passive": "passive"}


# ───────────────────────────────────── coefficients ─────────────────────────────────────


def k0_jaky(phi: float, ocr: float = 1.0) -> float:
    """At-rest coefficient ``(1 - sin φ') OCR^sin φ'`` (Jaky 1944; Mayne & Kulhawy 1982), φ' in
    degrees."""
    s = math.sin(math.radians(phi))
    return (1 - s) * max(ocr, 1.0) ** s


def ka_rankine(phi: float, beta: float = 0.0) -> float:
    """Rankine active coefficient for a backfill sloping at β ≤ φ' [°] (the pressure acting
    parallel to the slope)."""
    p, b = math.radians(phi), math.radians(min(abs(beta), phi))
    root = math.sqrt(max(math.cos(b) ** 2 - math.cos(p) ** 2, 0.0))
    return math.cos(b) * (math.cos(b) - root) / (math.cos(b) + root)


def kp_rankine(phi: float, beta: float = 0.0) -> float:
    """Rankine passive coefficient for a ground sloping at β ≤ φ' [°]."""
    p, b = math.radians(phi), math.radians(min(abs(beta), phi))
    root = math.sqrt(max(math.cos(b) ** 2 - math.cos(p) ** 2, 0.0))
    return math.cos(b) * (math.cos(b) + root) / (math.cos(b) - root)


def ka_coulomb(phi: float, delta: float = 0.0, beta: float = 0.0, alpha: float = 0.0) -> float:
    """Coulomb active coefficient: φ' the soil's friction angle, δ the wall friction, β the
    backfill slope, α the batter of the wall's back from the vertical (positive leaning over
    the backfill), all in degrees. The thrust acts at δ to the normal of the back."""
    p, d, b, a = (math.radians(v) for v in (phi, delta, beta, alpha))
    if b > p:
        raise ValueError(f"the backfill slope {beta:g}° is steeper than φ' = {phi:g}°")
    num = math.cos(p - a) ** 2
    root = math.sqrt(math.sin(p + d) * math.sin(p - b) / (math.cos(d + a) * math.cos(a - b)))
    return num / (math.cos(a) ** 2 * math.cos(d + a) * (1 + root) ** 2)


def kae_mononobe_okabe(
    phi: float,
    kh: float,
    kv: float = 0.0,
    delta: float = 0.0,
    beta: float = 0.0,
    alpha: float = 0.0,
) -> float | None:
    """Mononobe-Okabe seismic active coefficient Kae (AASHTO LRFD Eq. A11.1.1.1-2, angles in
    degrees, α the batter of the back from the vertical), or None when ``φ' - β - ψ < 0``: the
    backfill is not stable at that acceleration (``ψ = atan(kh / (1 - kv))``)."""
    psi = math.atan2(kh, 1 - kv)
    p, d, b, a = (math.radians(v) for v in (phi, delta, beta, alpha))
    if p - b - psi < 0:
        return None
    num = math.cos(p - psi - a) ** 2
    root = math.sqrt(
        math.sin(p + d) * math.sin(p - psi - b) / (math.cos(d + psi + a) * math.cos(b - a))
    )
    return num / (math.cos(psi) * math.cos(a) ** 2 * math.cos(d + psi + a) * (1 + root) ** 2)


def seed_whitman_trapezoid(force: float, height: float, at: float = 0.6) -> tuple[float, float]:
    """The linear pressure (bottom, top) [kPa] whose resultant is ``force`` [kN/m] acting at
    ``at`` x ``height`` above the base (0.6: Seed & Whitman 1970 for the Mononobe-Okabe
    increment; 0.5: a uniform pressure, Wood 1973)."""
    if height <= 0:
        return 0.0, 0.0
    # p(y) = a + b y (y up from the base): ∫p = aH + bH²/2 = P, ∫p y = aH²/2 + bH³/3 = at H P.
    b = (at - 0.5) * 12 * force / height**2
    a = force / height - b * height / 2
    return a, a + b * height


# ──────────────────────────────────────── soil ────────────────────────────────────────

#: A layer: top, bottom [m below the ground], γ, γsat [kN/m³], φ' [°] (None: cohesive without
#: φ'), and optionally c' [kPa] (the undrained cu for a layer without φ'), OCR.
Layer = tuple[Any, ...]


@dataclass
class Soil:
    """A column of soil behind (or in front of) a wall: its layers from the ground down, the
    design water table [m below the ground; None: below every depth of interest], a uniform
    surcharge on the ground [kPa], the K0 of a layer without φ', where the values came from,
    and the 1 Soil Report profile they were read from (None: assumed)."""

    layers: list[Layer]
    water_table: float | None
    surcharge: float = 0.0
    k0_cohesive: float = 0.6
    source: str = ""
    profile: Any = None
    notes: list[str] = field(default_factory=list)

    def _layer(self, z: float) -> Layer:
        for layer in self.layers:
            if layer[0] <= z < layer[1]:
                return layer
        return self.layers[-1] if z >= self.layers[-1][0] else self.layers[0]

    def phi(self, z: float) -> float | None:
        return self._layer(z)[4]

    def cohesion(self, z: float) -> float:
        layer = self._layer(z)
        return float(layer[5]) if len(layer) > 5 and layer[5] else 0.0

    def ocr(self, z: float) -> float:
        layer = self._layer(z)
        return float(layer[6]) if len(layer) > 6 and layer[6] else 1.0

    def cuts(self, top: float, bottom: float) -> list[float]:
        """The depths between ``top`` and ``bottom`` where the pressure changes slope: the
        layers' boundaries and the water table, with the ends."""
        cuts = {top, bottom}
        cuts.update(b for layer in self.layers for b in layer[:2] if top < b < bottom)
        if self.water_table is not None and top < self.water_table < bottom:
            cuts.add(self.water_table)
        return sorted(cuts)

    def sigma_v_eff(self, z: float) -> float:
        """σ'v [kPa] at depth z [m]."""
        if z <= 0:
            return 0.0
        total = 0.0
        for a, b in pairwise(self.cuts(0.0, z)):
            total += self.unit_weight((a + b) / 2) * (b - a)
        return total

    def sigma_v(self, z: float) -> float:
        return self.sigma_v_eff(z) + self.u(z)

    def u(self, z: float) -> float:
        """Pore water pressure [kPa], hydrostatic below the water table."""
        if self.water_table is None or z <= self.water_table:
            return 0.0
        return GAMMA_W * (z - self.water_table)

    def unit_weight(self, z: float) -> float:
        """The effective unit weight at depth z (submerged below the water table)."""
        _, _, g, gs, *_ = self._layer(z)
        if self.water_table is not None and z > self.water_table:
            return gs - GAMMA_W
        return g

    def total_unit_weight(self, z: float) -> float:
        """γ above the water table, γsat below it."""
        _, _, g, gs, *_ = self._layer(z)
        return gs if self.water_table is not None and z > self.water_table else g

    def k0(self, z: float) -> float:
        phi = self.phi(z)
        return self.k0_cohesive if phi is None else k0_jaky(phi, self.ocr(z))

    def coefficient(
        self,
        z: float,
        state: State = "atRest",
        beta: float = 0.0,
        delta: float = 0.0,
        alpha: float = 0.0,
        method: Literal["rankine", "coulomb"] = "rankine",
    ) -> float:
        """K of the layer at depth z in ``state`` (see the module's notes)."""
        phi = self.phi(z)
        if state == "atRest" or (phi is None and state == "active"):
            return self.k0(z)
        if phi is None:
            return 1.0
        if state == "active":
            if method == "coulomb":
                return ka_coulomb(phi, delta, beta, alpha)
            return ka_rankine(phi, beta)
        return kp_rankine(phi, beta)

    def lateral(self, z: float) -> float:
        """At-rest ``K0 (σ'v + q) + u`` [kPa] at depth z [m] (0 above the ground)."""
        if z <= 0:
            return 0.0
        return self.k0(z) * (self.sigma_v_eff(z) + self.surcharge) + self.u(z)

    def pressure(
        self,
        z: float,
        state: State = "atRest",
        beta: float = 0.0,
        delta: float = 0.0,
        alpha: float = 0.0,
        method: Literal["rankine", "coulomb"] = "rankine",
        water: bool = True,
        surcharge: bool = True,
    ) -> dict[str, float]:
        """The parts of the pressure on a wall at depth z [kPa]: ``soil`` (K σ'v with the
        cohesion term), ``surcharge`` (K q), ``water`` (u) and their ``total``, with ``K``.
        ``water``: False for a drained wall (weep holes, a drain behind it): no water
        pressure, and the soil taken at its moist unit weight."""
        if z <= 0:
            return {"K": 0.0, "soil": 0.0, "surcharge": 0.0, "water": 0.0, "total": 0.0}
        k = self.coefficient(z, state, beta, delta, alpha, method)
        sigma = self.sigma_v_eff(z) if water else self._sigma_v_drained(z)
        c = self.cohesion(z)
        q = self.surcharge if surcharge else 0.0
        if self.phi(z) is None and state == "passive":
            soil = sigma + 2 * c
        elif state == "passive":
            soil = k * sigma + 2 * c * math.sqrt(k)
        elif state == "active" and self.phi(z) is not None:
            soil = k * sigma - 2 * c * math.sqrt(k)
        else:
            soil = k * sigma
        side = k * q
        if state == "active" and soil + side < 0:  # no tension between soil and wall
            soil = -side
        u = self.u(z) if water else 0.0
        return {"K": k, "soil": soil, "surcharge": side, "water": u, "total": soil + side + u}

    def _sigma_v_drained(self, z: float) -> float:
        total = 0.0
        for a, b in pairwise(self.cuts(0.0, z)):
            _, _, g, *_ = self._layer((a + b) / 2)
            total += g * (b - a)
        return total

    def resultant(
        self,
        top: float,
        bottom: float,
        state: State = "atRest",
        steps: int = 40,
        **options: Any,
    ) -> dict[str, float]:
        """The pressure of :meth:`pressure` integrated from depth ``top`` to ``bottom`` [m]:
        the force [kN/m] of each part (``soil``, ``surcharge``, ``water``, ``total``) and the
        ``arm`` of the total above ``bottom`` [m]. Simpson's rule in each slice between
        :meth:`cuts` (exact for the piecewise linear pressure of uniform layers)."""
        parts = {"soil": 0.0, "surcharge": 0.0, "water": 0.0, "total": 0.0}
        moment = 0.0
        for a, b in pairwise(self.cuts(max(top, 0.0), bottom)):
            n = max(2, 2 * math.ceil(steps * (b - a) / max(bottom - top, 1e-9) / 2))
            h = (b - a) / n
            for k in range(n + 1):
                z = a + k * h
                # Just inside the slice at its ends: the layer of the slice, not the next one's.
                p = self.pressure(min(max(z, a + 1e-9), b - 1e-9), state, **options)
                weight = (1 if k in (0, n) else 4 if k % 2 else 2) * h / 3
                for name in parts:
                    parts[name] += weight * p[name]
                moment += weight * p["total"] * (bottom - z)
        parts["arm"] = moment / parts["total"] if parts["total"] > 1e-12 else 0.0
        return parts

    def below(self, offset: float) -> Soil:
        """The same ground seen from a surface ``offset`` m lower (the soil in front of a wall,
        the floor of an excavation): the layers cut at it and measured from it, the water
        table with them, no surcharge."""
        layers = [
            (max(lay[0] - offset, 0.0), lay[1] - offset, *lay[2:])
            for lay in self.layers
            if lay[1] > offset
        ] or [(0.0, 100.0, *self.layers[-1][2:])]
        water = None if self.water_table is None else max(self.water_table - offset, 0.0)
        return Soil(layers, water, 0.0, self.k0_cohesive, self.source, self.profile)

    def mean(self, top: float, bottom: float) -> tuple[float, float | None]:
        """The thickness-weighted mean total unit weight and φ' between two depths (φ' None
        when no layer there has one); for the seismic increment of a layered backfill."""
        gamma = phi = weight = 0.0
        for a, b in pairwise(self.cuts(max(top, 0.0), bottom)):
            mid = (a + b) / 2
            gamma += self.total_unit_weight(mid) * (b - a)
            if self.phi(mid) is not None:
                phi += float(self.phi(mid)) * (b - a)  # type: ignore[arg-type]
                weight += b - a
        depth = max(bottom - top, 1e-9)
        return gamma / depth, (phi / weight if weight else None)


def seismic_increment(
    soil: Soil,
    height: float,
    kh: float,
    yielding: bool,
    beta: float = 0.0,
    delta: float = 0.0,
) -> dict[str, Any]:
    """The seismic increment on a wall retaining ``height`` m of ``soil`` at the horizontal
    seismic coefficient ``kh``: Mononobe-Okabe on a wall that can yield (the caller passes
    kh = ½ PGA), Wood on one that cannot (kh = PGA); see the module's notes.
    Returns ``{"force", "arm", "bottom", "top", "method", "kh", "note"}`` [kN/m, m above the
    base, kPa]."""
    gamma, phi = soil.mean(0.0, height)
    if kh <= 0 or height <= 0:
        return {"force": 0.0, "arm": 0.0, "bottom": 0.0, "top": 0.0, "method": "", "kh": 0.0}
    if yielding:
        k = kh
        if phi is None:
            return {
                "force": 0.0,
                "arm": 0.0,
                "bottom": 0.0,
                "top": 0.0,
                "method": "Mononobe-Okabe",
                "kh": k,
                "note": "the backfill has no φ'; no Mononobe-Okabe increment (use a granular "
                "backfill or enter φ')",
            }
        kae = kae_mononobe_okabe(phi, k, 0.0, delta, beta)
        if kae is None:
            raise ValueError(
                f"Mononobe-Okabe: the backfill (φ' = {phi:.0f}°, β = {beta:g}°) is not stable "
                f"at kh = {k:.3f}"
            )
        ka = ka_coulomb(phi, delta, beta)
        force = 0.5 * gamma * height**2 * max(kae - ka, 0.0)
        bottom, top = seed_whitman_trapezoid(force, height, 0.6)
        return {
            "force": force,
            "arm": 0.6 * height,
            "bottom": bottom,
            "top": top,
            "method": "Mononobe-Okabe",
            "kh": k,
            "Kae": kae,
            "Ka": ka,
            "note": f"Mononobe-Okabe: kh = {k:.3f}, Kae = {kae:.3f}, Ka = {ka:.3f}, "
            f"ΔPae = ½ γ H² ΔKae = {force:.1f} kN/m at 0.6 H (Seed & Whitman)",
        }
    force = kh * gamma * height**2
    return {
        "force": force,
        "arm": 0.5 * height,
        "bottom": force / height,
        "top": force / height,
        "method": "Wood",
        "kh": kh,
        "note": f"Wood (rigid wall): kh = {kh:.3f}, ΔPe = kh γ H² = {force:.1f} kN/m, a "
        "uniform pressure (resultant at 0.5 H)",
    }


def soil_column(
    profiles: list[Any],
    x: float,
    y: float,
    water_table: float | None = None,
    surcharge: float = 0.0,
    k0_cohesive: float = 0.6,
    override: dict[str, float] | None = None,
) -> Soil:
    """The soil at plan position (x, y) [mm]: the layers of the nearest borehole of 1 Soil
    Report (``profiles``, :func:`saengine.substructure.piles.profiles_of`), with the design
    ``water_table`` [m below the ground] (None: the borehole's measured level), or assumed
    values without a report. ``override`` (``gamma``, ``gammaSat``, ``phi``, ``c``): a
    backfill of known properties instead of the borehole's layers (the soil placed behind a
    retaining wall)."""
    if override:
        g = float(override.get("gamma") or 18.0)
        gs = float(override.get("gammaSat") or g + 2.0)
        phi = override.get("phi")
        c = float(override.get("c") or 0.0)
        water = water_table
        if water is None and profiles:
            from saengine.substructure.piles import nearest_profile

            water = nearest_profile(profiles, x, y)[0].water_table
        return Soil(
            [(0.0, 100.0, g, gs, None if phi is None else float(phi), c)],
            water,
            surcharge,
            k0_cohesive,
            f"backfill: γ = {g:g}, γsat = {gs:g} kN/m³, φ' = "
            + ("—" if phi is None else f"{float(phi):g}°")
            + (f", c' = {c:g} kPa" if c else ""),
        )
    if profiles:
        from saengine.substructure.piles import nearest_profile

        profile, distance = nearest_profile(profiles, x, y)
        layers = [
            (
                lay.top,
                lay.bottom,
                lay.gamma,
                lay.gamma_sat,
                lay.phi,
                (lay.c if lay.phi is not None else (lay.cu or 0.0)),
                getattr(lay, "ocr", 1.0),
            )
            for lay in profile.layers
        ]
        water = profile.water_table if water_table is None else water_table
        source = f"soil report: {profile.id}, {distance / 1e3:.1f} m away"
        return Soil(layers, water, surcharge, k0_cohesive, source, profile)
    return Soil(
        [(0.0, 100.0, 18.0, 20.0, 30.0)],
        water_table,
        surcharge,
        k0_cohesive,
        "no soil report: γ = 18, γsat = 20 kN/m³, φ' = 30° assumed",
    )
