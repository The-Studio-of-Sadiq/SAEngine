"""Static pile capacity methods, chosen by the code pack (Part 9, deep foundations).

The pack's ``foundations.piles.staticMethod`` names the method; its numbers are in
``foundations.piles.static`` (driven piles) and ``foundations.piles.drilledShaft`` (bored
piles wider than the pack's ``minDiameter``), with the clauses in the table's ``sources``.

``alphaBeta`` (:class:`AlphaBeta`), unit values [kPa] at a depth z [m] below the borehole's
ground:

- cohesive soil, α (total stress) method: ``fs = α cu`` with α = the first value at and below
  the first cu, the second at and above the second, ``1 - (cu - cu1) / divisor`` between;
  ``fb = cu Nc ≤ max``, ``Nc = base (1 + slope L/Db) ≤ max``, L the pile's length;
- cohesionless soil (sand, gravel and non-plastic silt), β (effective stress) method: ``fs =
  β σ'v`` with β from the pack's table of φ' (interpolated, the end values outside);
  ``fb = σ'v Nq`` with σ'v at the base at most the pack's limit and Nq the lesser of the pack's
  range by density (interpolated in N60 over the class) and its Nq figure at φ'; both σ'v
  taken at the critical depth (this many diameters by density) where the depth is greater;
- bored piles: ``boredSkin`` × fs and ``boredBase`` × fb of a driven pile, except drilled
  shafts (wider than ``minDiameter``), which take the drilled-shaft unit values of Part 1
  (:func:`saengine.soil.piles.bored`) with the pile's L/Db, the N60 over ``sandBaseDepth`` Db
  below the base, the large-base reductions and the shaft's construction method.

Group rules of drilled shafts (:func:`zeta`, :func:`punching_base`): the reduction ζ of each
shaft's capacity by spacing and the unit tip capacity of an equivalent shaft over a weaker
layer.
"""

from __future__ import annotations

import math
from statistics import fmean
from typing import Any

from saengine.soil import piles as soil_piles
from saengine.soil.profile import Profile, SoilLayer


def rules() -> Any | None:
    """The pack's deep foundation rules, or None when the pack does not cover them."""
    return soil_piles.pile_rules()


def not_covered(what: str) -> str:
    return f"{what}: not covered by the code pack {soil_piles.pack_name()}"


def is_shaft(kind: str, diameter: float, found: Any | None = None) -> bool:
    """Whether a pile of ``diameter`` [m] is a drilled shaft by the pack (bored and wider)."""
    found = found or rules()
    return found is not None and kind == "bored" and diameter * 1e3 > found.drilledShaft.minDiameter


def mean_n60_below(profile: Profile, tip: float, depth: float, layer: SoilLayer) -> float | None:
    """Mean N60 of the tests from ``tip`` to ``depth`` [m] below it, else the nearest test below
    the tip, else the layer's mean."""
    near = [p.n60 for p in profile.spt if tip - 1e-9 <= p.depth <= tip + depth + 1e-9]
    if near:
        return fmean(near)
    below = [p for p in profile.spt if p.depth >= tip]
    if below:
        return min(below, key=lambda p: p.depth).n60
    return layer.n60


class AlphaBeta:
    """The α / β static method (see the module notes)."""

    id = "alphaBeta"

    def __init__(self, found: Any) -> None:
        self.rules = found
        self.static = found.static

    # ── driven-pile unit values ──

    def alpha(self, cu: float) -> float:
        s = self.static
        (cu1, a1), (cu2, a2) = s.alphaFull, s.alphaLow
        if cu <= cu1:
            return a1
        if cu >= cu2:
            return a2
        return 1 - (cu - cu1) / s.alphaDivisor

    def nc(self, length: float, diameter: float) -> float:
        s = self.static
        return min(s.ncMax, s.ncBase * (1 + s.ncSlope * length / diameter))

    def critical_depth(self, layer: SoilLayer, diameter: float) -> float:
        """Critical depth [m] of a granular layer by its density (loose when unknown)."""
        cls = soil_piles.density_class(layer, self.rules) or "loose"
        return self.static.criticalDepth[cls] * diameter

    def nq(self, layer: SoilLayer) -> tuple[float, str]:
        s, classes = self.static, self.rules.soilClasses
        n = layer.n60
        by_density = None
        if n is not None:
            if n >= classes.denseN:
                by_density = s.nqDensity["dense"][0]
            elif n >= classes.mediumN:
                lo, hi = s.nqDensity["medium"]
                by_density = lo + (hi - lo) * (n - classes.mediumN) / (
                    classes.denseN - classes.mediumN
                )
            else:
                lo, hi = s.nqDensity["loose"]
                by_density = lo + (hi - lo) * max(n, 0.0) / classes.mediumN
        by_phi = soil_piles.interpolate(s.nq, layer.phi) if layer.phi else None
        values = [v for v in (by_density, by_phi) if v is not None]
        if not values:
            return 0.0, "no N60 or φ' for Nq"
        text = []
        if by_density is not None:
            text.append(f"by density {by_density:.1f}")
        if by_phi is not None:
            text.append(f"by φ' {layer.phi:.1f}° {by_phi:.1f}")
        return min(values), "Nq the lesser of " + " and ".join(text)

    def driven_skin(
        self, profile: Profile, layer: SoilLayer, z: float, diameter: float
    ) -> tuple[float | None, str]:
        if layer.behaviour == "cohesive":
            if layer.cu is None:
                return None, "no cu"
            alpha = self.alpha(layer.cu)
            return alpha * layer.cu, f"α method, α = {alpha:.3f}"
        if not layer.phi:
            return None, "no φ'"
        beta = soil_piles.interpolate(self.static.sandBeta, layer.phi)
        zc = min(z, self.critical_depth(layer, diameter))
        text = f"β method, β = {beta:.3f} at φ' {layer.phi:.1f}°"
        if zc < z:
            text += f", σ'v at the critical depth {zc:.1f} m"
        return beta * profile.sigma_v_eff(zc), text

    def driven_base(
        self, profile: Profile, layer: SoilLayer, tip: float, diameter: float, length: float
    ) -> tuple[float, str]:
        s = self.static
        if layer.behaviour == "cohesive":
            if layer.cu is None:
                return 0.0, "no cu at the tip"
            nc = self.nc(length, diameter)
            return min(s.clayBaseMax, nc * layer.cu), (
                f"fb = cu Nc ≤ {s.clayBaseMax:g} kPa, Nc = {nc:.2f}"
            )
        zc = min(tip, self.critical_depth(layer, diameter))
        sigma = min(profile.sigma_v_eff(zc), s.baseStressMax)
        nq, nq_text = self.nq(layer)
        text = f"fb = σ'v Nq, σ'v = {sigma:.0f} kPa (≤ {s.baseStressMax:g}), {nq_text}"
        if zc < tip:
            text += f"; critical depth {zc:.1f} m"
        return sigma * nq, text

    # ── by pile kind ──

    def skin(
        self,
        profile: Profile,
        layer: SoilLayer,
        kind: str,
        z: float,
        diameter: float,
        construction: tuple[str, str] | None = None,
    ) -> tuple[float | None, str]:
        if is_shaft(kind, diameter, self.rules):
            values = soil_piles.bored(
                layer, z, profile.sigma_v_eff(z), diameter=diameter, construction=construction
            )
            if values.get("fs") is None:
                return None, values.get("note") or "no unit skin friction"
            return float(values["fs"]), str(values.get("method"))
        fs, text = self.driven_skin(profile, layer, z, diameter)
        if fs is None or kind == "driven":
            return fs, text
        share = self.static.boredSkin
        return fs * share, f"{text}; bored: × {share:.3g}"

    def base(
        self,
        profile: Profile,
        layer: SoilLayer,
        kind: str,
        tip: float,
        diameter: float,
        length: float,
    ) -> tuple[float, str, float | None]:
        """Unit end bearing [kPa] at the tip, its text and the N60 used."""
        if is_shaft(kind, diameter, self.rules):
            shaft = self.rules.drilledShaft
            n = mean_n60_below(profile, tip, shaft.sandBaseDepth * diameter, layer)
            values = soil_piles.bored(
                layer,
                tip,
                profile.sigma_v_eff(tip),
                length=length,
                diameter=diameter,
                n_base=n,
            )
            if values.get("qb") is None:
                return 0.0, values.get("note") or "no unit end bearing", n
            return float(values["qb"]), str(values.get("method")), n
        fb, text = self.driven_base(profile, layer, tip, diameter, length)
        if kind == "bored":
            share = self.static.boredBase
            fb, text = fb * share, f"{text}; bored: × {share:.3g}"
        return fb, text, layer.n60


#: The static methods by the id the pack gives in ``foundations.piles.staticMethod``.
METHODS: dict[str, type[AlphaBeta]] = {AlphaBeta.id: AlphaBeta}


def method() -> AlphaBeta | None:
    """The pack's static method, or None when the pack does not cover it."""
    found = rules()
    if found is None:
        return None
    cls = METHODS.get(found.staticMethod)
    return cls(found) if cls else None


# ─────────────────────────────────────── drilled-shaft groups ───────────────────────────────


def zeta(spacing: float, diameter: float, cohesive: bool) -> float | None:
    """Reduction ζ of a drilled shaft's capacity in a group at c/c ``spacing`` (same unit as
    ``diameter``): the pack's low value at its least spacing, 1.0 at its full spacing (clay or
    sand), linear between (the low value below). None when the pack does not cover it."""
    found = rules()
    if found is None:
        return None
    shaft = found.drilledShaft
    ratio = spacing / diameter
    full = shaft.clayFullSpacing if cohesive else shaft.sandFullSpacing
    if ratio >= full:
        return 1.0
    if ratio <= shaft.spacingLow:
        return float(shaft.zetaLow)
    return shaft.zetaLow + (1 - shaft.zetaLow) * (ratio - shaft.spacingLow) / (
        full - shaft.spacingLow
    )


def punching_base(q_upper: float, q_lower: float, distance: float, width: float) -> float:
    """Unit tip capacity [kPa] of an equivalent shaft in a strong layer over a weaker one,
    ``distance`` [m] from the tip down to the weak layer, ``width`` [m] the equivalent shaft's:
    ``qLo + H / (span B) (qUP - qLo) ≤ qUP`` (see the pack's note on the printed form)."""
    found = rules()
    span = found.drilledShaft.punchingSpan if found is not None else 10.0
    if q_lower >= q_upper:
        return q_upper
    return min(q_upper, q_lower + distance / (span * width) * (q_upper - q_lower))


def equivalent_pier(
    profile: Profile, head: float, length: float, bg: float, lg: float
) -> tuple[float | None, str]:
    """Ultimate capacity [kN] of the equivalent pier of a drilled-shaft group: the perimeter
    of the outline Bg × Lg [m] over the shaft length with the soil's full strength (cu without
    α in clay, β σ'v in sand) and the whole base area at the unit end bearing of the drilled
    shaft (Nc from L/Bg); the cap's own capacity left out. A weaker layer within 10 B below
    the tip (by the pack's span) reduces the base by :func:`punching_base`."""
    found = rules()
    if found is None:
        return None, not_covered("equivalent pier")
    shaft = found.drilledShaft
    perimeter = 2 * (bg + lg)
    steps = max(1, math.ceil(length / 0.1 - 1e-9))
    dz = length / steps
    qs = 0.0
    for k in range(steps):
        z = head + (k + 0.5) * dz
        layer = profile.layer_at(z)
        if layer is None or layer.behaviour == "rock" or layer.soil_type in ("fill", "organic"):
            continue
        if layer.behaviour == "cohesive":
            fs = layer.cu or 0.0
        else:
            beta, _ = soil_piles.shaft_beta(layer, z, shaft)
            fs = beta * profile.sigma_v_eff(z)
            if shaft.skinMax is not None:
                fs = min(fs, shaft.skinMax)
        qs += fs * perimeter * dz
    tip = head + length
    width = min(bg, lg)

    def unit_base(layer: SoilLayer | None, at: float) -> float:
        if layer is None or layer.behaviour == "rock":
            return 0.0
        if layer.behaviour == "cohesive":
            return soil_piles.shaft_clay_base(layer.cu or 0.0, length, width, shaft)[0]
        n = mean_n60_below(profile, at, shaft.sandBaseDepth * width, layer)
        return soil_piles.shaft_sand_base(n or 0.0, width, shaft)[0] if n else 0.0

    base_layer = profile.layer_at(tip + 1e-6)
    qb = unit_base(base_layer, tip)
    text = f"equivalent pier {bg:.2f} × {lg:.2f} m: Qs = {qs:.0f} kN, qb = {qb:.0f} kPa"
    # a weaker layer below the tip within the span (Sec on strong over weak soil)
    reach = shaft.punchingSpan * width
    for layer in profile.layers:
        if layer.top <= tip or layer.top > tip + reach:
            continue
        q_lower = unit_base(layer, layer.top)
        if q_lower < qb:
            reduced = punching_base(qb, q_lower, layer.top - tip, width)
            text += f"; weaker layer {layer.index + 1} at {layer.top:.1f} m: qE = {reduced:.0f} kPa"
            qb = reduced
            break
    return qs + qb * bg * lg, text
