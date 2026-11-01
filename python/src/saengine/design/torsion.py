"""Torsion design of reinforced-concrete beams to BNBC 2020 Part 6 Sec 6.4.4 (pp. 926-931).

A beam in torsion is idealised as a thin-walled tube (Figure 6.6.7). Units: N, mm, MPa, N·mm.

- Threshold torsion (Sec 6.4.4.1, p. 926): torsion may be neglected when Tu is below
  φTth = 0.083 φ λ √f'c (Acp²/pcp), times √(1 + Nu / (0.33 Ag λ √f'c)) with axial force
  (Nu positive in compression, negative in tension).
- Flanges (Sec 6.4.4.1.1, p. 927, with Sec 6.5.2.4, p. 945): a beam cast with a slab includes
  the slab on each side up to the beam's projection below it, at most 4 times the slab
  thickness; the flanges are dropped when Acp²/pcp with them is smaller than without.
- Equilibrium torsion (Sec 6.4.4.2.1, Figure 6.6.8) is designed for the full Tu.
  Compatibility torsion (Sec 6.4.4.2.2, Figure 6.6.9: a statically indeterminate member whose
  torsion can drop as it cracks, e.g. a spandrel beam restrained by the slab) may be reduced to
  φTcr = 0.33 φ λ √f'c (Acp²/pcp) √(1 + Nu / (0.33 Ag λ √f'c)); the adjoining members must
  then carry the correspondingly redistributed moments and shears. SAEngine cannot tell the
  two apart from the forces alone: :func:`torsion_kind` states the rule used.
- Section limit, solid sections (Eq. 6.6.59, p. 928):
  √((Vu/(bw d))² + (Tu ph/(1.7 Aoh²))²) <= φ (Vc/(bw d) + 0.66 √f'c).
- Transverse steel (Eqs. 6.6.61, 6.6.62, p. 929): φTn >= Tu with Tn = 2 Ao At fyt cot θ / s,
  Ao = 0.85 Aoh, θ = 45° (30° to 60° permitted). At/s is per leg of the closed stirrup.
- Longitudinal steel (Eq. 6.6.63): Al = (At/s) ph (fyt/fy) cot² θ, at least Al,min =
  0.42 √f'c Acp / fy - (At/s) ph fyt/fy with At/s >= 0.175 bw / fyt (Eq. 6.6.65, p. 930).
  It is added to the flexural steel (Sec 6.4.4.3.8); the reduction of Sec 6.4.4.3.9 in the
  flexural compression zone is not taken (on the safe side).
- Minimum closed stirrups (Eq. 6.6.64): (Av + 2At)/s >= 0.062 √f'c bw / fyt, at least
  0.35 bw / fyt.
- fy, fyt <= 420 MPa (Sec 6.4.4.3.4, p. 929); √f'c <= 8.3 MPa (Sec 6.4.1.2, p. 921).
- Spacing (Sec 6.4.4.6.1, p. 931): s <= ph/8 and 300 mm. Longitudinal bars (Sec 6.4.4.6.2):
  around the perimeter at most 300 mm apart, one in each corner, diameter at least 0.042 s and
  10 mm.
  :func:`torsion_checks` checks these from the section's bars when it is given them
  (:func:`longitudinal_detailing_checks`).

The rule numbers that are limits or choices (θ, the Ao share, the spacing caps, the fy cap)
are read from the code pack's ``concrete`` table, group ``torsion`` (:class:`TorsionRules`);
φ from the ``factors`` table. The equation coefficients stay in the equations, as in
:mod:`saengine.design.rc`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from saengine.design.clauses import limits
from saengine.design.rc import Bar, DesignError, RcSection, bar_area
from saengine.library.objects import RectangleProfile

#: √f'c used in shear and torsion is capped at this [MPa] (BNBC 2020 Part 6 Sec 6.4.1.2).


def _root_fc_max() -> float:
    """√f'c used in shear and torsion is capped at this [MPa]: the pack's
    ``designLimits.shearRootFcMax``."""
    return float(limits().shearRootFcMax)


def __getattr__(name: str) -> float:
    if name == "ROOT_FC_MAX":
        return _root_fc_max()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


TorsionKind = Literal["equilibrium", "compatibility"]


def _check(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check as check

    return check(*args, **kwargs)


def _phi_shear() -> float:
    from saengine.codes import context as code_context

    return float(code_context.table("factors").phi.shear)


@dataclass(frozen=True)
class TorsionRules:
    """The limits and choices of the torsion design (code pack ``concrete.torsion``)."""

    theta: float  # degrees, the angle of the compression diagonals
    ao_share: float  # Ao / Aoh
    spacing_max: float  # mm, the cap on the closed stirrups' spacing
    perimeter_divisor: float  # s <= ph / this
    long_spacing_max: float  # mm, longitudinal bars around the perimeter
    long_dia_ratio: float  # longitudinal bar diameter >= this × s
    long_dia_min: float  # mm
    fy_max: float  # MPa, fy and fyt of torsion steel

    @classmethod
    def from_pack(cls) -> TorsionRules:
        from saengine.codes import context as code_context

        t = code_context.table("concrete").torsion
        return cls(
            theta=float(t["theta"]),
            ao_share=float(t["aoShare"]),
            spacing_max=float(t["spacingMax"]),
            perimeter_divisor=float(t["perimeterDivisor"]),
            long_spacing_max=float(t["longitudinalSpacingMax"]),
            long_dia_ratio=float(t["longitudinalDiaRatio"]),
            long_dia_min=float(t["longitudinalDiaMin"]),
            fy_max=float(t["fyMax"]),
        )


@dataclass(frozen=True)
class TorsionSection:
    """A rectangular beam for torsion, with the slab cast with it.

    ``cover``: clear cover to the stirrups [mm]; ``stirrup_dia`` [mm]; ``d``: effective depth
    for the shear terms [mm]; ``slab``: thickness of the slab cast with the beam (0: none) and
    ``slab_sides`` the sides it is on (1: an edge or spandrel beam, 2: an interior beam)."""

    b: float
    h: float
    cover: float
    stirrup_dia: float
    d: float
    slab: float = 0.0
    slab_sides: int = 0

    @classmethod
    def of(
        cls, section: RcSection, cover: float, slab: float = 0.0, slab_sides: int = 0
    ) -> TorsionSection:
        """From an :class:`RcSection` (rectangular), with ``d`` to the bottom bars (or the top
        bars when there are none at the bottom)."""
        if not isinstance(section.profile, RectangleProfile):
            raise DesignError("torsion is designed for rectangular beams only")
        try:
            d = section.effective_depth(top=False)
        except DesignError:
            d = section.effective_depth(top=True)
        return cls(
            section.profile.xDim,
            section.profile.yDim,
            cover,
            section.transverse_dia,
            d,
            slab,
            slab_sides,
        )

    @property
    def gross_area(self) -> float:
        return self.b * self.h

    @property
    def overhang(self) -> float:
        """Slab width counted on each side (Sec 6.5.2.4): the beam's projection below the
        slab, at most 4 times the slab thickness."""
        if self.slab <= 0 or self.slab_sides <= 0:
            return 0.0
        return max(0.0, min(self.h - self.slab, 4 * self.slab))

    def outline(self) -> tuple[float, float, bool]:
        """(Acp [mm²], pcp [mm], flanges counted): the flanges only when they raise
        Acp²/pcp (Sec 6.4.4.1.1)."""
        acp, pcp = self.b * self.h, 2 * (self.b + self.h)
        ov = self.overhang
        if ov > 0:
            acp_f = acp + self.slab_sides * ov * self.slab
            pcp_f = pcp + 2 * self.slab_sides * ov
            if acp_f**2 / pcp_f > acp**2 / pcp:
                return acp_f, pcp_f, True
        return acp, pcp, False

    @property
    def core(self) -> tuple[float, float]:
        """(x1, y1): the centreline dimensions of the closed stirrup [mm]."""
        inset = 2 * self.cover + self.stirrup_dia
        x1, y1 = self.b - inset, self.h - inset
        if x1 <= 0 or y1 <= 0:
            raise ValueError("the cover leaves no room for closed stirrups")
        return x1, y1

    @property
    def aoh(self) -> float:
        x1, y1 = self.core
        return x1 * y1

    @property
    def ph(self) -> float:
        x1, y1 = self.core
        return 2 * (x1 + y1)


def _root(fc: float) -> float:
    return min(math.sqrt(fc), _root_fc_max())


def _axial_factor(nu: float, ag: float, fc: float, lam: float) -> float:
    """√(1 + Nu / (0.33 Ag λ √f'c)) of Sec 6.4.4.1(b) and 6.4.4.2.2(b); Nu in compression
    positive; 0 when the tension is so large the root would be imaginary."""
    if nu == 0:
        return 1.0
    return math.sqrt(max(0.0, 1 + nu / (0.33 * ag * lam * _root(fc))))


def threshold_torsion(
    sec: TorsionSection, fc: float, nu: float = 0.0, lam: float = 1.0, phi: float | None = None
) -> float:
    """φTth [N·mm] (Sec 6.4.4.1)."""
    phi = _phi_shear() if phi is None else phi
    acp, pcp, _ = sec.outline()
    return 0.083 * phi * lam * _root(fc) * acp**2 / pcp * _axial_factor(nu, sec.gross_area, fc, lam)


def cracking_torsion(
    sec: TorsionSection, fc: float, nu: float = 0.0, lam: float = 1.0, phi: float | None = None
) -> float:
    """φTcr [N·mm]: the compatibility torsion cap of Sec 6.4.4.2.2."""
    phi = _phi_shear() if phi is None else phi
    acp, pcp, _ = sec.outline()
    return 0.33 * phi * lam * _root(fc) * acp**2 / pcp * _axial_factor(nu, sec.gross_area, fc, lam)


def torsion_kind(both_ends_restrained: bool, carries_cantilever: bool) -> tuple[TorsionKind, str]:
    """The torsion kind SAEngine designs a beam for, with the reason.

    Equilibrium (no reduction) when the torque is needed for equilibrium: the beam carries a
    cantilever slab or a cantilever beam from its side (Figure 6.6.8), or one of its ends is
    free (a cantilever beam). Otherwise compatibility (Figure 6.6.9): a beam framed at both ends
    whose torque comes from the rotation of the slab or the beams framing into it."""
    if carries_cantilever:
        return "equilibrium", "carries a cantilever: torque needed for equilibrium (6.4.4.2.1)"
    if not both_ends_restrained:
        return "equilibrium", "an end is free: torque needed for equilibrium (6.4.4.2.1)"
    return (
        "compatibility",
        "framed at both ends: compatibility torsion, Tu may be reduced to φTcr (6.4.4.2.2)",
    )


@dataclass(frozen=True)
class TorsionDesign:
    tu: float  # N·mm, the factored torsion of the analysis (absolute)
    tu_design: float  # N·mm, after the compatibility reduction
    kind: TorsionKind
    phi_tth: float
    phi_tcr: float
    required: bool  # Tu > φTth: design for torsion
    reduced: bool
    at_s: float  # mm²/mm per leg of the closed stirrups
    at_s_min: float  # mm²/mm, 0.175 bw / fyt (the floor in Eq. 6.6.65)
    al: float  # mm², longitudinal torsion steel (at least Al,min)
    al_min: float
    av_2at_s_min: float  # mm²/mm, (Av + 2At)/s minimum (Eq. 6.6.64)
    s_max: float  # mm
    long_dia_min: float  # mm, at the stirrup spacing ``s`` given (else 0)
    stress: float  # MPa, the left side of Eq. 6.6.59
    stress_limit: float  # MPa, its right side
    vc: float  # N, the Vc used in Eq. 6.6.59
    fy: float  # MPa, capped
    fyt: float
    phi: float
    flanges: bool
    notes: tuple[str, ...] = field(default=())
    av_s: float = 0.0  # mm²/mm, all legs: the shear's Av/s at this station (set by the caller)

    @property
    def section_ok(self) -> bool:
        return self.stress <= self.stress_limit


def design_torsion(
    sec: TorsionSection,
    tu: float,
    vu: float,
    fc: float,
    fy: float,
    fyt: float,
    kind: TorsionKind = "equilibrium",
    nu: float = 0.0,
    vc: float | None = None,
    lam: float = 1.0,
    rules: TorsionRules | None = None,
    phi: float | None = None,
    spacing: float | None = None,
) -> TorsionDesign:
    """The torsion steel of a beam section for the simultaneous ``tu`` [N·mm], ``vu`` [N] and
    ``nu`` [N, compression positive]. ``vc`` [N]: the Vc the shear check uses (default
    0.17 λ √f'c bw d, Eq. 6.6.49); ``spacing``: the stirrups' spacing, for the least
    longitudinal bar diameter."""
    rules = TorsionRules.from_pack() if rules is None else rules
    phi = _phi_shear() if phi is None else phi
    tu, vu = abs(tu), abs(vu)
    fy_c, fyt_c = min(fy, rules.fy_max), min(fyt, rules.fy_max)
    root = _root(fc)
    acp, _, flanges = sec.outline()
    aoh, ph = sec.aoh, sec.ph
    phi_tth = threshold_torsion(sec, fc, nu, lam, phi)
    phi_tcr = cracking_torsion(sec, fc, nu, lam, phi)
    notes: list[str] = []
    reduced = kind == "compatibility" and tu > phi_tcr
    tu_design = phi_tcr if reduced else tu
    if reduced:
        notes.append(
            f"compatibility torsion: Tu = {tu / 1e6:.1f} kN·m reduced to φTcr = "
            f"{phi_tcr / 1e6:.1f} kN·m (Sec 6.4.4.2.2); the adjoining members must carry the "
            "redistributed moments"
        )
    required = tu_design > phi_tth
    bw, d = sec.b, sec.d
    if vc is None:
        vc = 0.17 * lam * root * bw * d
    stress = math.hypot(vu / (bw * d), tu_design * ph / (1.7 * aoh**2))
    stress_limit = phi * (vc / (bw * d) + 0.66 * root)
    cot = 1 / math.tan(math.radians(rules.theta))
    at_s_min = 0.175 * bw / fyt_c
    av_2at_s_min = max(0.062 * root, 0.35) * bw / fyt_c
    s_max = min(ph / rules.perimeter_divisor, rules.spacing_max)
    if required:
        ao = rules.ao_share * aoh
        at_s = tu_design / (phi * 2 * ao * fyt_c * cot)
        al_calc = at_s * ph * (fyt_c / fy_c) * cot**2
        al_min = 0.42 * root * acp / fy_c - max(at_s, at_s_min) * ph * fyt_c / fy_c
        al = max(al_calc, al_min, 0.0)
        long_dia = max(rules.long_dia_ratio * spacing, rules.long_dia_min) if spacing else 0.0
        if flanges:
            notes.append("Acp, pcp with the slab flanges (Sec 6.4.4.1.1, 6.5.2.4)")
    else:
        at_s = al = al_min = long_dia = 0.0
    return TorsionDesign(
        tu,
        tu_design,
        kind,
        phi_tth,
        phi_tcr,
        required,
        reduced,
        at_s,
        at_s_min if required else 0.0,
        al,
        max(al_min, 0.0),
        av_2at_s_min if required else 0.0,
        s_max,
        long_dia,
        stress,
        stress_limit,
        vc,
        fy_c,
        fyt_c,
        phi,
        flanges,
        tuple(notes),
    )


def shear_av_s(vu: float, vc: float, d: float, fyt: float, phi: float, fyt_max: float) -> float:
    """Av/s [mm²/mm, all legs] the shear needs beside Vc: (Vu/φ - Vc) / (fyt d) (Eqs. 6.6.47,
    6.6.48, 6.6.56)."""
    return max(abs(vu) / phi - vc, 0.0) / (min(fyt, fyt_max) * d)


def torsion_checks(
    design: TorsionDesign,
    sec: TorsionSection,
    vu: float,
    stirrups: tuple[float, int, float] | None,
    as_provided: float,
    as_flexure: float,
    combination: str | None = None,
    where: str = "",
    fyt_shear_max: float | None = None,
    bars: Sequence[Bar] | None = None,
    rules: TorsionRules | None = None,
) -> list[dict[str, Any]]:
    """Check rows (:func:`saengine.design.check._check`) of a beam's torsion at its governing
    point. ``stirrups``: (dia, legs, spacing) of the closed stirrups (None: none);
    ``as_provided``: all longitudinal bars [mm²]; ``as_flexure``: the flexural steel the
    simultaneous moments need [mm²] (top and bottom), so the bars left for Al are the rest.
    ``bars``: the section's longitudinal bars (:attr:`RcSection.bars`); when given, the
    detailing of Sec 6.4.4.6.2 is checked too (:func:`longitudinal_detailing_checks`).

    Below the threshold a single reported-only row (``flag``) says torsion was neglected. The
    shear part of the stirrups is Av/s = (Vu/φ - Vc)/(fyt d), shared equally by the legs; each
    outer leg must carry At/s on top (Sec 6.4.4.3.8)."""
    at = f"; {where}" if where else ""
    if not design.required:
        return [
            _check(
                "Torsion threshold (Sec 6.4.4.1)",
                design.tu / 1e6,
                design.phi_tth / 1e6,
                "kN·m",
                combination,
                f"Tu below φTth = 0.083 φ λ √f'c Acp²/pcp: torsion neglected{at}",
                flag=True,
            )
        ]
    if fyt_shear_max is None:
        from saengine.codes import context as code_context

        fyt_shear_max = float(code_context.table("concrete").fytShearMax)
    lead = (
        f"Tu = {design.tu / 1e6:.1f} kN·m ({design.kind})"
        + (f", designed for φTcr = {design.tu_design / 1e6:.1f} kN·m" if design.reduced else "")
        + f", φTth = {design.phi_tth / 1e6:.1f} kN·m"
    )
    rows = [
        _check(
            "Shear and torsion: section size (Eq. 6.6.59)",
            design.stress,
            design.stress_limit,
            "MPa",
            combination,
            f"{lead}; √((Vu/bw d)² + (Tu ph/1.7 Aoh²)²) ≤ φ (Vc/bw d + 0.66 √f'c), "
            f"Aoh = {sec.aoh:.0f} mm², ph = {sec.ph:.0f} mm{at}"
            + ("; enlarge the section" if not design.section_ok else ""),
        )
    ]
    av_s = shear_av_s(vu, design.vc, sec.d, design.fyt, design.phi, fyt_shear_max)
    if stirrups is None:
        rows.append(
            _check(
                "Torsion: closed stirrups At/s (Eq. 6.6.62)",
                design.at_s + av_s / 2,
                0.0,
                "mm²/mm",
                combination,
                f"{lead}; no closed stirrups{at}",
            )
        )
    else:
        dia, legs, spacing = stirrups
        leg = bar_area(dia) / spacing
        rows.append(
            _check(
                "Torsion: closed stirrups At/s + Av/(n s) per outer leg (Eq. 6.6.62)",
                design.at_s + av_s / legs,
                leg,
                "mm²/mm",
                combination,
                f"{lead}; At/s = Tu/(2 φ Ao fyt cot θ) = {design.at_s:.3f}, Ao = 0.85 Aoh, "
                f"Av/s for shear = {av_s:.3f} over {legs} legs; provided Ø{dia:g} at "
                f"{spacing:g} mm{at}",
            )
        )
        rows.append(
            _check(
                "Torsion: minimum closed stirrups (Av + 2At)/s (Eq. 6.6.64)",
                design.av_2at_s_min,
                legs * leg,
                "mm²/mm",
                combination,
                "0.062 √f'c bw/fyt, at least 0.35 bw/fyt",
            )
        )
        rows.append(
            _check(
                "Torsion: stirrup spacing (Sec 6.4.4.6.1)",
                spacing,
                design.s_max,
                "mm",
                combination,
                f"s ≤ ph/8 and 300 mm, ph = {sec.ph:.0f} mm",
            )
        )
    rows.append(
        _check(
            "Torsion: longitudinal steel Al (Eqs. 6.6.63, 6.6.65)",
            design.al + as_flexure,
            as_provided,
            "mm²",
            combination,
            f"Al = {design.al:.0f} mm² (Al,min = {design.al_min:.0f}) added to the flexural "
            f"{as_flexure:.0f} mm² (Sec 6.4.4.3.8)",
        )
    )
    if bars is not None:
        rows += longitudinal_detailing_checks(
            design, sec, bars, stirrups[2] if stirrups else None, combination, where, rules
        )
    return rows


def perimeter_bars(bars: Sequence[Bar], sec: TorsionSection) -> tuple[list[Bar], int, float]:
    """(the bars along the inside of the closed stirrups, the corners of the stirrups holding a
    bar, the largest centre-to-centre distance [mm] between neighbouring bars around them).

    Bar coordinates are from the section's centre (as :attr:`RcSection.bars`). The inner face
    of the stirrups is at ±(x1 - ds)/2, ±(y1 - ds)/2 (x1, y1: :attr:`TorsionSection.core`); a
    bar is against a face when its centre is within its own diameter of it, and holds a corner
    when it is against both faces there. Neighbours are taken in order around the perimeter."""
    x1, y1 = sec.core
    ax, ay = (x1 - sec.stirrup_dia) / 2, (y1 - sec.stirrup_dia) / 2

    def faces(b: Bar) -> tuple[bool, bool]:
        return abs(b.x) >= ax - b.dia, abs(b.y) >= ay - b.dia

    on = [b for b in bars if any(faces(b))]
    corners = sum(
        any(
            all(faces(b)) and math.copysign(1, b.x) == sx and math.copysign(1, b.y) == sy
            for b in on
        )
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    )
    if len(on) < 2:
        return on, corners, math.inf
    # Around the perimeter: by the angle of the bar's centre seen from the section's centre,
    # scaled to the cage so a long side is not compressed.
    ordered = sorted(on, key=lambda b: math.atan2(b.y / ay, b.x / ax))
    gaps = [
        math.hypot(q.x - p.x, q.y - p.y)
        for p, q in zip(ordered, ordered[1:] + ordered[:1], strict=True)
    ]
    return on, corners, max(gaps)


def longitudinal_detailing_checks(
    design: TorsionDesign,
    sec: TorsionSection,
    bars: Sequence[Bar],
    spacing: float | None,
    combination: str | None = None,
    where: str = "",
    rules: TorsionRules | None = None,
) -> list[dict[str, Any]]:
    """Check rows of Sec 6.4.4.6.2 (p. 931) for a beam designed for torsion: the longitudinal
    bars around the perimeter at most 300 mm apart, one in each corner, each at least 0.042 s
    (s the closed stirrups' spacing) and 10 mm in diameter. Empty when torsion is neglected."""
    if not design.required:
        return []
    rules = TorsionRules.from_pack() if rules is None else rules
    at = f"; {where}" if where else ""
    need = design.long_dia_min
    if spacing:
        need = max(rules.long_dia_ratio * spacing, rules.long_dia_min)
    elif not need:
        need = rules.long_dia_min
    on, corners, gap = perimeter_bars(bars, sec)
    smallest = min((b.dia for b in on), default=0.0)
    return [
        _check(
            "Torsion: longitudinal bar diameter (Sec 6.4.4.6.2)",
            need,
            smallest,
            "mm",
            combination,
            f"≥ {rules.long_dia_ratio:g} s and {rules.long_dia_min:g} mm"
            + (f", s = {spacing:g} mm" if spacing else "")
            + f"; smallest perimeter bar Ø{smallest:g}{at}",
        ),
        _check(
            "Torsion: a longitudinal bar in each corner (Sec 6.4.4.6.2)",
            4,
            corners,
            "bars",
            combination,
            f"corners of the stirrup cage holding a bar: {corners} of 4{at}",
        ),
        _check(
            "Torsion: longitudinal bars around the perimeter, gap (Sec 6.4.4.6.2)",
            gap if math.isfinite(gap) else 0.0,
            rules.long_spacing_max,
            "mm",
            combination,
            f"largest centre-to-centre gap around the perimeter ≤ {rules.long_spacing_max:g} mm"
            + (f"{at}" if math.isfinite(gap) else f"; fewer than two bars{at}"),
            utilisation=None if math.isfinite(gap) else math.inf,
        ),
    ]
