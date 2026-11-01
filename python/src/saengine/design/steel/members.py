"""Strength of steel members by LRFD to the default pack's BNBC 2020 Part 6 Chapter 10 (Bangladesh Gazette,
February 11 2021, pp 3825-3880; the provisions follow AISC 360-05).

Limit states and clauses (page numbers of the Gazette):

- Tension, Sec 10.4 (pp 3834-3838): yielding on the gross section φt = 0.90 Fy Ag (Eq 6.10.11),
  rupture on the net section φt = 0.75 Fu Ae (Eq 6.10.12), Ae = An U (Eq 6.10.13) with the shear
  lag factor U of Table 6.10.2. The connection is not known to the member design: An = Ag
  (welded ends, no holes) unless ``net_ratio`` says otherwise, and U is a stated default per
  shape (:func:`default_shear_lag`). Slenderness L/r <= 300 (Sec 10.4.1).
- Compression, Sec 10.5 (pp 3840-3851), φc = 0.90: flexural buckling Fcr = 0.658^(Fy/Fe) Fy
  when Fe >= 0.44 Fy, else 0.877 Fe (Eqs 6.10.16-19); torsional buckling of doubly symmetric
  I-shapes (Eq 6.10.23) and flexural-torsional buckling of channels (Eq 6.10.24) and tees
  (Eq 6.10.21) (Sec 10.5.4); single angles by the effective slenderness of Sec 10.5.5
  (Eqs 6.10.31-32, connected through the longer leg, planar-truss conditions); slender elements
  by Q = Qs Qa (Sec 10.5.7, Eqs 6.10.36-54): Qs of unstiffened elements, Qa = Aeff / A of
  stiffened ones with the effective widths of Eqs 6.10.52-53 (f = Fcr at Q = 1 for I-shape webs,
  f = Pn / Aeff by iteration for HSS walls) and Eq 6.10.54 for round HSS. KL/r <= 150
  (Sec 10.5.2, p 3841).
- Flexure, Sec 10.6 (pp 3851-3869), φb = 0.90: I-shapes and channels about the major axis with
  compact webs by Sec 10.6.2 (yielding, lateral-torsional buckling with Lp, Lr, Cb, Eqs
  6.10.56-63) and Sec 10.6.3 (flange local buckling, Eqs 6.10.64-65), with noncompact webs by
  Sec 10.6.4 (Rpc, rt, Eqs 6.10.66-78), with slender webs by Sec 10.6.5 (Rpg, Eqs 6.10.81-89);
  about the minor axis by Sec 10.6.6 (Eqs 6.10.91-94); rectangular HSS by Sec 10.6.7 (Eqs
  6.10.95-99); round HSS by Sec 10.6.8 (Eqs 6.10.100-103); tees by Sec 10.6.9 (Eqs
  6.10.104-111); single angles about their geometric axes by Sec 10.6.10 (Eqs 6.10.112-120).
- Shear, Sec 10.7 (pp 3873-3878): Vn = 0.6 Fy Aw Cv (Eq 6.10.136), φv = 1.0 and Cv = 1 for webs
  of rolled I-shapes with h/tw <= 2.24 √(E/Fy) (Sec 10.7.2.1(a)), else φv = 0.90 with Cv of
  Eqs 6.10.138-140 (kv = 5 unstiffened, 1.2 for tee stems); single angles Sec 10.7.4,
  rectangular HSS Sec 10.7.5 (Aw = 2 h t), round HSS Sec 10.7.6 (Eqs 6.10.145-146, Lv the
  segment length: conservative), weak-axis shear Sec 10.7.7 (Aw = bf tf per flange, kv = 1.2).
- Combined axial force and flexure, Sec 10.8.1 (pp 3879-3880): Eq 6.10.147a when Pr/Pc >= 0.2,
  Eq 6.10.147b below, in compression (Pc = φc Pn) and tension (Pc = φt Pn). Moments of members
  in compression are amplified by B1 = Cm / (1 - αPr / Pe1) >= 1 (Sec 10.3.2.1, Eqs 6.10.4,
  6.10.6, 6.10.7; Cm = 0.6 - 0.4 M1/M2 when the segment carries no transverse load, else 1.0).
  B2 (sway) is not applied here: it comes from a second-order (P-Delta) analysis.

Units: mm, MPa, N, N·mm; reported in kN, kN·m.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.clauses import clause
from saengine.design.rc import DesignError
from saengine.design.steel import classify as cl
from saengine.design.steel.lengths import (
    LengthOptions,
    MemberLengths,
    cb_from_diagram,
    member_lengths,
    positions,
    slenderness_note,
    source_tag,
)
from saengine.design.steel.properties import ShapeProperties, shape_properties
from saengine.library import steel_sections


def _shear_modulus() -> float:
    """G of structural steel [MPa], the pack's ``materials.steelShearModulus`` (default pack BNBC 2020:
    77 200 MPa, Sec 10.5.4, p 3843)."""
    return float(code_context.table("materials").steelShearModulus)


def _phi(name: str) -> float:
    """φ ``name`` of the pack's ``steel`` table (default pack BNBC 2020: tensionYield 0.90, tensionRupture
    0.75, compression, flexure and shear 0.90)."""
    return float(code_context.table("steel").phi[name])


def _slenderness(name: str) -> float:
    """The pack's slenderness limit ``name`` (default pack BNBC 2020: KL/r of compression members 150, Sec
    10.5.2; L/r of tension members 300, Sec 10.4.1)."""
    return float(code_context.table("steel").slenderness[name])


def _s(key: str) -> str:
    """The pack's clause of steel member check ``key`` ("<code> Part 6 Sec ...")."""
    return clause("steelMembers", key)


def _method() -> list[str]:
    """``METHOD``: the method text of the design report, with the clauses of the code pack in
    force (read as a module attribute)."""
    return [
        (
            f"Steel members: LRFD to {clause('steelMembers', 'code')}; the load combinations are the "
            "project's factored ones."
        ),
        (
            "Tension: yielding φ 0.90 Fy Ag (Eq 6.10.11) and rupture φ 0.75 Fu Ae (Eq 6.10.12), Ae "
            "= An U (Table 6.10.2 defaults: I-shapes and tees 0.90 / 0.85 by bf ≥ 2/3 d, channels "
            "0.85, angles 0.60, rectangular HSS 1 - x̄/l at l = H, round HSS 1 - 1/π at l = D); "
            "An = Ag (welded ends) unless set."
        ),
        (
            "Compression: flexural, torsional and flexural-torsional buckling (Secs 10.5.3, 10.5.4), "
            "single angles by Sec 10.5.5, slender elements by Q = Qs Qa (Sec 10.5.7); K = 1.0 "
            "(Secs 10.3.1.2.1, 10.3.2.2.2) unless overridden, lengths between the brace points the "
            "analysis model shows."
        ),
        (
            "Flexure: Sec 10.6 by shape (yielding, lateral-torsional buckling with Cb from the "
            "moment diagram, flange and web local buckling); a slab braces the top flange."
        ),
        "Shear: Sec 10.7; combined forces: Sec 10.8.1 (H1), moments amplified by B1 (Eq 6.10.4).",
        (
            "Deflection of beams (serviceability): the deflection relative to the chord between the "
            "member's ends (a cantilever: the free end relative to the support), from the "
            "analysis's unfactored load cases, under the live load (L and Lr), the wind (WX, WY "
            "each) and the code pack's service combination of dead + live load, against the span "
            "divisors of the member's use in the code pack's serviceability table (a cantilever's "
            "span a multiple of its length, as the pack says)."
        ),
        (
            "Torsion (B31, the code pack's member data): hollow sections by their torsional strength "
            "and, above the pack's share of it, the interaction with the other forces; open and "
            "solid sections by the normal and shear stresses of the combined actions (warping "
            "torsion along the member, the ends free to warp unless set) and buckling. Single "
            "angles also by the principal-axis interaction of unsymmetric members; built-up "
            "members by the modified slenderness and the connector spacing; stiffened webs with "
            "tension field action outside the end panels; rectangular bars and rounds."
        ),
        (
            "Not checked here: connections (see the steel connection checks), vibration and "
            "wind-induced motion, fatigue, fire."
        ),
    ]


class SteelDesignError(DesignError):
    """The steel member cannot be checked (not a steel shape, outside the clauses covered)."""


@dataclass(frozen=True)
class Steel:
    fy: float
    fu: float
    e: float = 200_000.0
    name: str = ""
    notes: tuple[str, ...] = ()

    @classmethod
    def of(cls, material: Any) -> Steel:
        """From a :class:`saengine.library.materials.Material` of category steel."""
        steel = getattr(material, "steel", None)
        if steel is None:
            raise SteelDesignError(f"material '{getattr(material, 'id', '?')}' has no fy")
        notes: tuple[str, ...] = ()
        fu = steel.fu
        if fu is None:
            fu = steel.fy
            notes = ("fu not given: tension rupture taken with Fu = Fy (conservative)",)
        e = (material.mechanical.E if material.mechanical else None) or 200_000.0
        return cls(steel.fy, fu, e, getattr(material, "id", ""), notes)


@dataclass(frozen=True)
class Capacity:
    phi: float
    nominal: float
    state: str
    clause: str
    note: str = ""

    @property
    def design(self) -> float:
        return self.phi * self.nominal


# ────────────────────────────────────── tension ──────────────────────────────────────


def default_shear_lag(shape: ShapeProperties) -> tuple[float, str]:
    """A default U of Table 6.10.2 for an unknown end connection, and what it assumes."""
    d = shape.dims
    match shape.family:
        case "I" | "tee":
            u = 0.90 if d["bf"] >= 2 / 3 * d["d"] else 0.85
            return u, f"U = {u:.2f} (Case 7, flanges connected, 3 or more fasteners per line)"
        case "channel":
            return 0.85, "U = 0.85 assumed (Case 2, 1 - x̄/l, connection not known)"
        case "angle":
            return 0.60, "U = 0.60 (Case 8, 2 or 3 fasteners per line; Sec 10.4.3.3 minimum)"
        case "rhs":
            # H is the height in the plane of the connection, B the width at 90° to it; the
            # gusset's face is not known, so the lower U of the two planes is taken.
            def u_of(b: float, h: float) -> float:
                return 1 - (b * b + 2 * b * h) / (4 * (b + h)) / h

            u_y, u_x = u_of(d["B"], d["H"]), u_of(d["H"], d["B"])
            u = min(u_y, u_x)
            if abs(d["B"] - d["H"]) < 1e-9:
                plane = "square"
            else:
                plane = "gusset in the plane of the " + (
                    f"{d['H']:g} mm side" if u_y <= u_x else f"{d['B']:g} mm side"
                )
            return u, (
                f"U = 1 - x̄/l = {u:.3f} (Case 6, single concentric gusset, l = H assumed, "
                f"{plane}: the lower U of the two planes)"
            )
        case "chs":
            u = 1 - 1 / math.pi
            return u, f"U = 1 - x̄/l = {u:.3f} (Case 5, single concentric gusset, l = D assumed)"
    return 1.0, "U = 1.0 (Case 1)"


def tension_yielding(shape: ShapeProperties, steel: Steel) -> Capacity:
    return Capacity(
        _phi("tensionYield"),
        steel.fy * shape.area,
        "tensile yielding",
        _s("tensionYield"),
        f"Ag = {shape.area:.0f} mm², Fy = {steel.fy:g} MPa",
    )


def tension_rupture(
    shape: ShapeProperties, steel: Steel, u: float | None = None, net_ratio: float = 1.0
) -> Capacity:
    if u is None:
        u, why = default_shear_lag(shape)
    else:
        why = f"U = {u:.2f} (given)"
    an = net_ratio * shape.area
    ae = an * u
    return Capacity(
        _phi("tensionRupture"),
        steel.fu * ae,
        "tensile rupture",
        _s("tensionRupture"),
        f"An = {an:.0f} mm²" + (" (= Ag)" if net_ratio == 1.0 else "") + f", {why}, "
        f"Ae = {ae:.0f} mm², Fu = {steel.fu:g} MPa",
    )


# ──────────────────────────────────── compression ────────────────────────────────────


def _fcr(fe: float, fy: float, q: float = 1.0) -> float:
    """Eqs 6.10.17-18 (Q = 1) and 6.10.37-38."""
    if fe <= 0:
        return 0.0
    if fe >= 0.44 * q * fy:
        return q * 0.658 ** (q * fy / fe) * fy
    return 0.877 * fe


def _euler(e: float, kl: float, r: float) -> float:
    return math.pi**2 * e / (kl / r) ** 2 if kl > 0 else math.inf


def _qs_rolled(ratio: float, e: float, fy: float) -> float:
    """Eqs 6.10.39-41: flanges, angles and plates projecting from rolled members."""
    r = math.sqrt(e / fy)
    if ratio <= 0.56 * r:
        return 1.0
    if ratio < 1.03 * r:
        return 1.415 - 0.74 * ratio / r
    return 0.69 * e / (fy * ratio**2)


def _qs_angle(ratio: float, e: float, fy: float) -> float:
    """Eqs 6.10.45-47."""
    r = math.sqrt(e / fy)
    if ratio <= 0.45 * r:
        return 1.0
    if ratio <= 0.91 * r:
        return 1.34 - 0.76 * ratio / r
    return 0.53 * e / (fy * ratio**2)


def _qs_stem(ratio: float, e: float, fy: float) -> float:
    """Eqs 6.10.48-50."""
    r = math.sqrt(e / fy)
    if ratio <= 0.75 * r:
        return 1.0
    if ratio <= 1.03 * r:
        return 1.908 - 1.22 * ratio / r
    return 0.69 * e / (fy * ratio**2)


def _effective_width(t: float, ratio: float, e: float, f: float, k: float) -> float:
    """Eqs 6.10.52 (k = 0.34) and 6.10.53 (k = 0.38), at most the width."""
    b = ratio * t
    root = math.sqrt(e / f)
    return min(b, 1.92 * t * root * (1 - k / ratio * root))


def _elastic_buckling(
    shape: ShapeProperties, e: float, klx: float, kly: float, klz: float
) -> tuple[float, str]:
    """Fe and the mode for shapes other than single angles (Eqs 6.10.19, 6.10.23-30)."""
    fex = _euler(e, klx, shape.rx)
    fey = _euler(e, kly, shape.ry)
    modes = [(fex, "flexural buckling about x"), (fey, "flexural buckling about y")]
    torsion = (math.pi**2 * e * shape.cw / klz**2 if klz > 0 else 0.0) + _shear_modulus() * shape.j
    if shape.family == "I":
        modes.append((torsion / (shape.ix + shape.iy), "torsional buckling (Eq 6.10.23)"))
    elif shape.family in ("channel", "tee"):
        fez = torsion / (shape.area * shape.ro2)
        h = shape.big_h
        # Channels are symmetric about x, tees about y: the axis of symmetry couples with Fez.
        fs = fex if shape.family == "channel" else fey
        ft = (
            (fs + fez) / (2 * h) * (1 - math.sqrt(max(0.0, 1 - 4 * fs * fez * h / (fs + fez) ** 2)))
        )
        modes.append((ft, "flexural-torsional buckling (Eq 6.10.24)"))
    return min(modes, key=lambda m: m[0])


def compression(
    shape: ShapeProperties,
    steel: Steel,
    klx: float,
    kly: float,
    klz: float | None = None,
    angle_length: float | None = None,
) -> Capacity:
    """φc Pn of ``shape`` with effective lengths K L [mm] about x, y and for torsion (``klz``,
    default ``kly``); single angles take ``angle_length`` [mm] (default the longer of klx, kly)
    in the effective slenderness of Sec 10.5.5."""
    e, fy = steel.e, steel.fy
    klz = kly if klz is None else klz
    elements = cl.compression_elements(shape, fy, e)
    slender = [el for el in elements if el.slender]
    notes: list[str] = []
    qs = qa = 1.0
    d = shape.dims
    clause = _s("compressionFlexural")

    if shape.family == "angle":
        length = angle_length if angle_length is not None else max(klx, kly)
        long_vertical = d["d"] >= d["b"]
        # The geometric axis parallel to the connected (longer) leg.
        r = shape.ry if long_vertical else shape.rx
        lr = length / r
        kl_r = 72 + 0.75 * lr if lr <= 80 else 32 + 1.25 * lr
        fe = math.pi**2 * e / kl_r**2
        mode = f"single angle, effective KL/r = {kl_r:.1f} from L/rx = {lr:.1f}"
        clause = _s("compressionAngle")
        notes.append(
            "connected through the longer leg, ends loaded through that leg, no transverse "
            "load (Sec 10.5.5 conditions assumed)"
        )
        if slender:
            qs = _qs_angle(slender[0].ratio, e, fy)
    else:
        fe, mode = _elastic_buckling(shape, e, klx, kly, klz)
        if mode.startswith(("torsional", "flexural-torsional")):
            clause = _s("compressionTorsional")
        if shape.family == "tee" and not slender:
            fcry = _fcr(_euler(e, kly, shape.ry), fy)
            fcrz = _shear_modulus() * shape.j / (shape.area * shape.ro2)
            h = shape.big_h
            fcr_t = (
                (fcry + fcrz)
                / (2 * h)
                * (1 - math.sqrt(max(0.0, 1 - 4 * fcry * fcrz * h / (fcry + fcrz) ** 2)))
            )
            fcr_x = _fcr(_euler(e, klx, shape.rx), fy)
            fcr = min(fcr_t, fcr_x)
            note = f"Fcry = {fcry:.1f}, Fcrz = {fcrz:.1f} MPa, H = {h:.3f}"
            state = "flexural-torsional buckling (Eq 6.10.21)" if fcr_t <= fcr_x else mode
            return Capacity(
                _phi("compression"),
                fcr * shape.area,
                state,
                _s("compressionTorsionalBuckling"),
                f"Fcr = {fcr:.1f} MPa; {note}",
            )
        kl_r = max(klx / shape.rx, kly / shape.ry)

    if slender:
        clause = _s("compressionSlender")
        for el in slender:
            if shape.family in ("I", "channel", "tee") and el.name == "flange":
                qs = min(qs, _qs_rolled(el.ratio, e, fy))
            elif el.name == "stem":
                qs = min(qs, _qs_stem(el.ratio, e, fy))
        if shape.family in ("I", "channel") and cl.by_name(slender, "web"):
            web = cl.by_name(slender, "web")
            assert web is not None
            f = _fcr(fe, fy)  # Fcr at Q = 1 (p 3850)
            if f > 0 and web.ratio >= 1.49 * math.sqrt(e / f):
                be = _effective_width(d["tw"], web.ratio, e, f, 0.34)
                qa = (shape.area - (d["h"] - be) * d["tw"]) / shape.area
                notes.append(f"web be = {be:.0f} mm (Eq 6.10.52, f = {f:.0f} MPa)")
        elif shape.family == "rhs":
            t = d["t"]
            q = 1.0
            for _ in range(50):
                fcr = _fcr(fe, fy, q)
                f = fcr / q  # Pn / Aeff
                removed = 0.0
                for flat in (d["b"], d["h"]):
                    ratio = flat / t
                    if ratio >= 1.40 * math.sqrt(e / f):
                        removed += 2 * (flat - _effective_width(t, ratio, e, f, 0.38)) * t
                new = (shape.area - removed) / shape.area
                if abs(new - q) < 1e-6:
                    q = new
                    break
                q = new
            qa = q
            notes.append(f"walls by Eq 6.10.53 with f = Pn / Aeff (iterated), Qa = {qa:.3f}")
        elif shape.family == "chs":
            ratio = d["D"] / d["t"]
            if ratio >= 0.45 * e / fy:
                raise SteelDesignError(
                    f"round HSS with D/t = {ratio:.0f} ≥ 0.45 E/Fy: outside Sec 10.5.7.2(c)"
                )
            qa = 0.038 * e / (fy * ratio) + 2 / 3
    q = qs * qa
    fcr = _fcr(fe, fy, q)
    note = f"KL/r = {kl_r:.1f}, Fe = {fe:.1f} MPa, Fcr = {fcr:.1f} MPa ({mode})"
    if q < 1:
        note += f"; slender elements: Q = Qs Qa = {qs:.3f} × {qa:.3f} = {q:.3f}"
    if notes:
        note += "; " + "; ".join(notes)
    return Capacity(_phi("compression"), fcr * shape.area, mode, clause, note)


def compression_slenderness(shape: ShapeProperties, klx: float, kly: float) -> float:
    """The governing KL/r of the flexural modes (single angles: their least radius)."""
    if shape.family == "angle":
        return max(klx, kly) / shape.rz
    return max(klx / shape.rx, kly / shape.ry)


# ────────────────────────────────────── flexure ──────────────────────────────────────


def _kc(h_tw: float) -> float:
    return min(0.76, max(0.35, 4 / math.sqrt(h_tw)))


def _i_major(shape: ShapeProperties, steel: Steel, lb: float, cb: float) -> Capacity:
    e, fy = steel.e, steel.fy
    d = shape.dims
    flange, web = cl.flexure_elements(shape, fy, e, "x")
    mp = fy * shape.zx
    sx = shape.sx
    ho = d["ho"]
    notes = [flange.describe(), web.describe()]
    candidates: list[tuple[float, str, str]] = []
    channel = shape.family == "channel"

    if web.cls == cl.COMPACT:
        c = ho / 2 * math.sqrt(shape.iy / shape.cw) if channel else 1.0
        rts = math.sqrt(math.sqrt(shape.iy * shape.cw) / sx)
        lp = 1.76 * shape.ry * math.sqrt(e / fy)
        jc = shape.j * c / (sx * ho)
        lr = (
            1.95
            * rts
            * e
            / (0.7 * fy)
            * math.sqrt(jc)
            * math.sqrt(1 + math.sqrt(1 + 6.76 * (0.7 * fy / e / jc) ** 2))
        )
        candidates.append((mp, "yielding", "Sec 10.6.2.1, Eq 6.10.56"))
        notes.append(f"Lb = {lb:.0f} mm, Lp = {lp:.0f} mm, Lr = {lr:.0f} mm, Cb = {cb:.2f}")
        if lb > lp:
            if lb <= lr:
                mn = cb * (mp - (mp - 0.7 * fy * sx) * (lb - lp) / (lr - lp))
            else:
                fcr = (
                    cb
                    * math.pi**2
                    * e
                    / (lb / rts) ** 2
                    * math.sqrt(1 + 0.078 * jc * (lb / rts) ** 2)
                )
                mn = fcr * sx
            candidates.append(
                (min(mn, mp), "lateral-torsional buckling", "Sec 10.6.2.2, Eqs 6.10.57-63")
            )
        if flange.cls == cl.NONCOMPACT:
            lam = flange.ratio
            mn = mp - (mp - 0.7 * fy * sx) * (lam - flange.lambda_p) / (
                flange.lambda_r - flange.lambda_p
            )
            candidates.append((mn, "flange local buckling", "Sec 10.6.3.2(a), Eq 6.10.64"))
        elif flange.cls == cl.SLENDER:
            mn = 0.9 * e * _kc(web.ratio) * sx / flange.ratio**2
            candidates.append((mn, "flange local buckling", "Sec 10.6.3.2(b), Eq 6.10.65"))
        if channel and flange.cls != cl.COMPACT:
            notes.append("channel with a noncompact flange: Sec 10.6.3 applied (approximation)")
    else:
        bf, tf, tw, h = d["bf"], d["tf"], d["tw"], d["h"]
        aw = h * tw / (bf * tf)
        myc = fy * sx
        if web.cls == cl.NONCOMPACT:
            mp = min(mp, 1.6 * sx * fy)
            lam_w = web.ratio
            rpc = min(
                mp / myc,
                mp / myc - (mp / myc - 1) * (lam_w - web.lambda_p) / (web.lambda_r - web.lambda_p),
            )
            rt = bf / math.sqrt(12 * (ho / d["d"] + aw / 6 * h**2 / (ho * d["d"])))
            fl = 0.7 * fy
            lp = 1.1 * rt * math.sqrt(e / fy)
            j = shape.j
            lr = (
                1.95
                * rt
                * e
                / fl
                * math.sqrt(j / (sx * ho))
                * math.sqrt(1 + math.sqrt(1 + 6.76 * (fl * sx * ho / (e * j)) ** 2))
            )
            candidates.append(
                (rpc * myc, "compression flange yielding", "Sec 10.6.4.1, Eq 6.10.66")
            )
            notes.append(f"Rpc = {rpc:.3f}, rt = {rt:.1f} mm, Lp = {lp:.0f}, Lr = {lr:.0f} mm")
            if lb > lp:
                if lb <= lr:
                    mn = cb * (rpc * myc - (rpc * myc - fl * sx) * (lb - lp) / (lr - lp))
                else:
                    fcr = (
                        cb
                        * math.pi**2
                        * e
                        / (lb / rt) ** 2
                        * math.sqrt(1 + 0.078 * j / (sx * ho) * (lb / rt) ** 2)
                    )
                    mn = fcr * sx
                candidates.append(
                    (
                        min(mn, rpc * myc),
                        "lateral-torsional buckling",
                        "Sec 10.6.4.2, Eqs 6.10.67-73",
                    )
                )
            if flange.cls == cl.NONCOMPACT:
                mn = rpc * myc - (rpc * myc - fl * sx) * (flange.ratio - flange.lambda_p) / (
                    flange.lambda_r - flange.lambda_p
                )
                candidates.append((mn, "flange local buckling", "Sec 10.6.4.3(b), Eq 6.10.77"))
            elif flange.cls == cl.SLENDER:
                mn = 0.9 * e * _kc(web.ratio) * sx / flange.ratio**2
                candidates.append((mn, "flange local buckling", "Sec 10.6.4.3(c), Eq 6.10.78"))
        else:
            aw = min(aw, 10.0)
            rpg = min(1.0, 1 - aw / (1200 + 300 * aw) * (web.ratio - 5.7 * math.sqrt(e / fy)))
            rt = bf / math.sqrt(12 * (ho / d["d"] + aw / 6 * h**2 / (ho * d["d"])))
            lp = 1.1 * rt * math.sqrt(e / fy)
            lr = math.pi * rt * math.sqrt(e / (0.7 * fy))
            candidates.append(
                (rpg * fy * sx, "compression flange yielding", "Sec 10.6.5.1, Eq 6.10.81")
            )
            notes.append(f"Rpg = {rpg:.3f}, rt = {rt:.1f} mm, Lp = {lp:.0f}, Lr = {lr:.0f} mm")
            if lb > lp:
                if lb <= lr:
                    fcr = min(fy, cb * (fy - 0.3 * fy * (lb - lp) / (lr - lp)))
                else:
                    fcr = min(fy, cb * math.pi**2 * e / (lb / rt) ** 2)
                candidates.append(
                    (rpg * fcr * sx, "lateral-torsional buckling", "Sec 10.6.5.2, Eqs 6.10.82-85")
                )
            if flange.cls == cl.NONCOMPACT:
                fcr = fy - 0.3 * fy * (flange.ratio - flange.lambda_p) / (
                    flange.lambda_r - flange.lambda_p
                )
                candidates.append(
                    (rpg * fcr * sx, "flange local buckling", "Sec 10.6.5.3(b), Eq 6.10.88")
                )
            elif flange.cls == cl.SLENDER:
                fcr = 0.9 * e * _kc(web.ratio) / flange.ratio**2
                candidates.append(
                    (rpg * fcr * sx, "flange local buckling", "Sec 10.6.5.3(c), Eq 6.10.89")
                )
    return _least(candidates, notes)


def _least(
    candidates: list[tuple[float, str, str]], notes: list[str], prefix: str | None = None
) -> Capacity:
    """The least of the candidate (Mn, state, clause); ``prefix`` goes before the clause (the
    pack's clause strings, B31, come whole: prefix "")."""
    if prefix is None:
        prefix = _s("part") + " "
    mn, state, clause = min(candidates, key=lambda c: c[0])
    others = ", ".join(f"{s} {m / 1e6:.1f}" for m, s, _ in candidates if s != state)
    note = f"Mn = {mn / 1e6:.1f} kN·m ({state})" + (f"; also {others} kN·m" if others else "")
    if notes:
        note += "; " + "; ".join(notes)
    return Capacity(_phi("flexure"), mn, state, prefix + clause, note)


def _members_table() -> Any:
    """The pack's member limit-state data (B31), or a :class:`SteelDesignError` saying the
    pack in force does not cover the member."""
    from saengine.design.steel.torsion import members_data

    data = members_data()
    if data is None:
        raise SteelDesignError("the code pack in force does not cover solid bars and rounds")
    return data


def _bar_flexure(shape: ShapeProperties, steel: Steel, axis: str, lb: float, cb: float) -> Capacity:
    """Rectangular bars and rounds (the pack's ``members.bars``; the default pack's BNBC 2020 Sec 10.6.11):
    yielding Mp = Fy Z <= 1.6 My, and lateral-torsional buckling of a bar bent about its major
    axis by Lb d / t² (d the depth across the axis, t the width along it)."""
    from saengine.design.steel.torsion import clause

    data = _members_table().bars
    e, fy = steel.e, steel.fy
    d = shape.dims
    z, sm = (shape.zx, shape.sx) if axis == "x" else (shape.zy, shape.sy)
    my = fy * sm
    mp = min(fy * z, data.plasticCap * my)
    ref = clause("bars")
    candidates = [(mp, "yielding", ref)]
    notes: list[str] = []
    if shape.family == "bar":
        depth, t = (d["d"], d["b"]) if axis == "x" else (d["b"], d["d"])
        if depth > t and lb > 0:
            ratio = lb * depth / t**2
            notes.append(f"Lb d / t² = {ratio:.0f}, Cb = {cb:.2f}")
            if ratio > data.yieldLimit * e / fy:
                if ratio <= data.ltbLimit * e / fy:
                    mn = cb * (data.ltbA - data.ltbB * ratio * fy / e) * my
                else:
                    mn = data.elastic * e * cb / ratio * sm
                candidates.append((min(mn, mp), "lateral-torsional buckling", ref))
        else:
            notes.append("bent about its minor axis: no lateral-torsional buckling")
    else:
        notes.append("round: no lateral-torsional buckling")
    return _least(candidates, notes, prefix="")


def flexure_unsymmetric(
    s_least: float, fy: float, fcr_ltb: float | None = None, fcr_local: float | None = None
) -> Capacity:
    """Unsymmetrical shapes other than single angles (default pack BNBC 2020 Sec 10.6.12, Eqs 6.10.125-128):
    Mn = Fn S with S the least elastic modulus, Fn = Fy (yielding) or the lateral-torsional and
    local buckling stresses Fcr <= Fy that an analysis of the section gives (None: that limit
    state not given). No shape of the section table is of this kind (B31): the method is ready
    for designed sections."""
    from saengine.design.steel.torsion import clause

    ref = clause("unsymmetricFlexure")
    candidates = [(fy * s_least, "yielding", ref)]
    if fcr_ltb is not None:
        candidates.append((min(fcr_ltb, fy) * s_least, "lateral-torsional buckling", ref))
    if fcr_local is not None:
        candidates.append((min(fcr_local, fy) * s_least, "local buckling", ref))
    return _least(candidates, [f"S = {s_least / 1e3:.1f}×10³ mm³ (the least)"], prefix="")


def _hss_flexure(shape: ShapeProperties, steel: Steel, axis: str) -> Capacity:
    e, fy = steel.e, steel.fy
    d = shape.dims
    if shape.family == "chs":
        ratio = d["D"] / d["t"]
        if ratio >= 0.45 * e / fy:
            raise SteelDesignError(
                f"round HSS with D/t = {ratio:.0f} ≥ 0.45 E/Fy: outside Sec 10.6.8"
            )
        (wall,) = cl.flexure_elements(shape, fy, e, axis)
        mp = fy * shape.zx
        candidates = [(mp, "yielding", "Sec 10.6.8.1, Eq 6.10.100")]
        if wall.cls == cl.NONCOMPACT:
            candidates.append(
                (
                    (0.021 * e / ratio + fy) * shape.sx,
                    "local buckling",
                    "Sec 10.6.8.2(b), Eq 6.10.101",
                )
            )
        elif wall.cls == cl.SLENDER:
            candidates.append(
                (0.33 * e / ratio * shape.sx, "local buckling", "Sec 10.6.8.2(c), Eqs 6.10.102-103")
            )
        return _least(candidates, [wall.describe()])
    flange, web = cl.flexure_elements(shape, fy, e, axis)
    z, s = (shape.zx, shape.sx) if axis == "x" else (shape.zy, shape.sy)
    mp = fy * z
    t = d["t"]
    candidates = [(mp, "yielding", "Sec 10.6.7.1, Eq 6.10.95")]
    if flange.cls == cl.NONCOMPACT:
        mn = mp - (mp - fy * s) * (3.57 * flange.ratio * math.sqrt(fy / e) - 4.0)
        candidates.append((min(mn, mp), "flange local buckling", "Sec 10.6.7.2(b), Eq 6.10.96"))
    elif flange.cls == cl.SLENDER:
        be = _effective_width(t, flange.ratio, e, fy, 0.38)
        candidates.append(
            (
                fy * _rhs_seff(shape, axis, be),
                "flange local buckling",
                "Sec 10.6.7.2(c), Eqs 6.10.97-98",
            )
        )
    if web.cls == cl.NONCOMPACT:
        mn = mp - (mp - fy * s) * (0.305 * web.ratio * math.sqrt(fy / e) - 0.738)
        candidates.append((min(mn, mp), "web local buckling", "Sec 10.6.7.3(b), Eq 6.10.99"))
    elif web.cls == cl.SLENDER:
        raise SteelDesignError(
            f"rectangular HSS web h/t = {web.ratio:.0f} is slender: outside Sec 10.6.7"
        )
    return _least(candidates, [flange.describe(), web.describe()])


def _rhs_seff(shape: ShapeProperties, axis: str, be: float) -> float:
    """The effective section modulus of a rectangular HSS whose compression flange is ``be``
    of its flat width effective (Sec 10.6.7.2(c))."""
    d = shape.dims
    # Work in the bending axis' frame: "width" across the flanges, "depth" across the axis.
    width, depth = (d["B"], d["H"]) if axis == "x" else (d["H"], d["B"])
    flat = d["b"] if axis == "x" else d["h"]
    t = d["t"]
    effective_top = width - (flat - be)
    parts = [
        (effective_top, t, depth - t / 2),
        (width, t, t / 2),
        (2 * t, depth - 2 * t, depth / 2),
    ]
    area = sum(b * h for b, h, _ in parts)
    y = sum(b * h * c for b, h, c in parts) / area
    i = sum(b * h**3 / 12 + b * h * (c - y) ** 2 for b, h, c in parts)
    return i / max(depth - y, y)


def _tee_flexure(
    shape: ShapeProperties, steel: Steel, lb: float, stem_compression: bool
) -> Capacity:
    e, fy = steel.e, steel.fy
    d = shape.dims
    my = fy * shape.sx
    mp = fy * shape.zx
    limit = my if stem_compression else 1.6 * my
    candidates = [(min(mp, limit), "yielding", "Sec 10.6.9.1, Eqs 6.10.104-106")]
    if lb > 0:
        b = (-1 if stem_compression else 1) * 2.3 * (d["d"] / lb) * math.sqrt(shape.iy / shape.j)
        mcr = (
            math.pi
            * math.sqrt(e * shape.iy * _shear_modulus() * shape.j)
            / lb
            * (b + math.sqrt(1 + b * b))
        )
        candidates.append((mcr, "lateral-torsional buckling", "Sec 10.6.9.2, Eqs 6.10.107-108"))
    (flange,) = cl.flexure_elements(shape, fy, e, "x")
    if not stem_compression and flange.cls != cl.COMPACT:
        lam = flange.ratio
        if flange.cls == cl.NONCOMPACT:
            fcr = fy * (1.19 - 0.50 * lam * math.sqrt(fy / e))
            clause = "Sec 10.6.9.3(b), Eqs 6.10.109-110"
        else:
            fcr = 0.69 * e / lam**2
            clause = "Sec 10.6.9.3(c), Eqs 6.10.109, 6.10.111"
        candidates.append((fcr * shape.sx_top, "flange local buckling", clause))
    return _least(
        candidates,
        [flange.describe(), "stem in " + ("compression" if stem_compression else "tension")],
    )


def _angle_flexure(
    shape: ShapeProperties, steel: Steel, lb: float, cb: float, axis: str
) -> Capacity:
    """Geometric-axis bending of a single angle, the toe of the leg across the axis in
    compression (conservative for either sign) (Sec 10.6.10)."""
    e, fy = steel.e, steel.fy
    d = shape.dims
    t = d["t"]
    if axis == "x":
        leg, sc = d["d"], shape.ix / (d["d"] - d["cy"])
    else:
        leg, sc = d["b"], shape.iy / (d["b"] - d["cx"])
    s_geo = min(sc, shape.sx if axis == "x" else shape.sy)
    notes = [f"toe in compression assumed, leg {leg:g} mm"]
    restrained = lb <= 0
    my = (1.0 if restrained else 0.8) * fy * s_geo
    candidates = [(1.5 * my, "yielding", "Sec 10.6.10.1, Eq 6.10.112")]
    if not restrained:
        cb = min(cb, 1.5)
        me = 0.66 * e * leg**4 * t * cb / lb**2 * (math.sqrt(1 + 0.78 * (lb * t / leg**2) ** 2) - 1)
        if me <= my:
            mn = (0.92 - 0.17 * me / my) * me
        else:
            mn = min((1.92 - 1.17 * math.sqrt(my / me)) * my, 1.5 * my)
        candidates.append((mn, "lateral-torsional buckling", "Sec 10.6.10.2, Eqs 6.10.113-115a"))
        notes.append("My = 0.80 Fy S (no lateral-torsional restraint)")
        if d["d"] != d["b"]:
            notes.append("unequal legs: the equal-leg Me of Eq 6.10.115a used (approximation)")
    ratio = leg / t
    r = math.sqrt(e / fy)
    if ratio > 0.54 * r:
        if ratio <= 0.91 * r:
            mn = fy * sc * (2.43 - 1.72 * ratio / r)
            candidates.append((mn, "leg local buckling", "Sec 10.6.10.3(b), Eq 6.10.118"))
        else:
            mn = 0.71 * e / ratio**2 * sc
            candidates.append((mn, "leg local buckling", "Sec 10.6.10.3(c), Eqs 6.10.119-120"))
    return _least(candidates, notes)


def flexure_major(
    shape: ShapeProperties, steel: Steel, lb: float, cb: float = 1.0, top_compression: bool = True
) -> Capacity:
    """φb Mn about the profile's x-axis with the compression flange unbraced over ``lb`` [mm]."""
    match shape.family:
        case "I" | "channel":
            return _i_major(shape, steel, lb, cb)
        case "rhs" | "chs":
            return _hss_flexure(shape, steel, "x")
        case "tee":
            return _tee_flexure(shape, steel, lb, stem_compression=not top_compression)
        case "angle":
            return _angle_flexure(shape, steel, lb, cb, "x")
        case "bar" | "round":
            return _bar_flexure(shape, steel, "x", lb, cb)
    raise SteelDesignError(f"unknown shape family {shape.family}")


def flexure_minor(
    shape: ShapeProperties, steel: Steel, lb: float = 0.0, cb: float = 1.0
) -> Capacity:
    """φb Mn about the profile's y-axis."""
    e, fy = steel.e, steel.fy
    match shape.family:
        case "I" | "channel":
            (flange,) = cl.flexure_elements(shape, fy, e, "y")
            mp = min(fy * shape.zy, 1.6 * fy * shape.sy)
            candidates = [(mp, "yielding", "Sec 10.6.6.1, Eq 6.10.91")]
            if flange.cls == cl.NONCOMPACT:
                mn = mp - (mp - 0.7 * fy * shape.sy) * (flange.ratio - flange.lambda_p) / (
                    flange.lambda_r - flange.lambda_p
                )
                candidates.append((mn, "flange local buckling", "Sec 10.6.6.2(b), Eq 6.10.92"))
            elif flange.cls == cl.SLENDER:
                fcr = 0.69 * e / flange.ratio**2
                candidates.append(
                    (fcr * shape.sy, "flange local buckling", "Sec 10.6.6.2(c), Eqs 6.10.93-94")
                )
            return _least(candidates, [flange.describe()])
        case "rhs" | "chs":
            return _hss_flexure(shape, steel, "y")
        case "tee":
            mn = min(fy * shape.zy, 1.6 * fy * shape.sy)
            return _least(
                [(mn, "yielding", "Sec 10.6.6.1, Eq 6.10.91 (applied to the tee flange)")],
                ["tee about its axis of symmetry: yielding of the flange only (approximation)"],
            )
        case "angle":
            return _angle_flexure(shape, steel, lb, cb, "y")
        case "bar" | "round":
            return _bar_flexure(shape, steel, "y", lb, cb)
    raise SteelDesignError(f"unknown shape family {shape.family}")


# ─────────────────────────────────────── shear ───────────────────────────────────────


def web_shear_coefficient(h_tw: float, kv: float, e: float, fy: float) -> float:
    """Cv of Eqs 6.10.138-140."""
    r = math.sqrt(kv * e / fy)
    if h_tw <= 1.10 * r:
        return 1.0
    if h_tw <= 1.37 * r:
        return 1.10 * r / h_tw
    return 1.51 * e * kv / (h_tw**2 * fy)


def _chs_shear(shape: ShapeProperties, steel: Steel, lv: float) -> Capacity:
    e, fy = steel.e, steel.fy
    dd, t = shape.dims["D"], shape.dims["t"]
    ratio = dd / t
    fa = 1.60 * e / (math.sqrt(max(lv, dd) / dd) * ratio**1.25)
    fb = 0.78 * e / ratio**1.5
    fcr = min(max(fa, fb), 0.6 * fy)
    return Capacity(
        _phi("shear"),
        fcr * shape.area / 2,
        "shear yielding / buckling",
        _s("shearRound"),
        f"Fcr = {fcr:.1f} MPa, Lv = {lv:.0f} mm (the unbraced segment: conservative)",
    )


def _bar_shear(shape: ShapeProperties, steel: Steel) -> Capacity:
    """Solid bars and rounds: 0.6 Fy at the peak of the elastic shear stress, 1.5 V / A of a
    rectangle and 4/3 V / A of a circle (the pack labels the rule, B31)."""
    from saengine.design.steel.torsion import clause

    _members_table()
    peak = 1.5 if shape.family == "bar" else 4 / 3
    return Capacity(
        _phi("shear"),
        0.6 * steel.fy * shape.area / peak,
        "shear yielding",
        clause("barShear"),
        f"A = {shape.area:.0f} mm², peak shear stress {peak:.2f} V / A",
    )


def stiffened_web(shape: ShapeProperties, steel: Steel, a: float) -> dict[str, Any] | None:
    """kv and tension field data of an I-shape or channel web with transverse stiffeners at
    the clear spacing ``a`` [mm] (the pack's ``members.tensionField``; the default pack's BNBC 2020 Secs 10.7.2.1,
    10.7.3.1): ``{kv, aspect, tfa, why}``, ``tfa`` whether tension field action may be counted
    (not in end panels: the caller decides those); None without the pack's data."""
    from saengine.design.steel.torsion import members_data

    data = members_data()
    if data is None or a <= 0 or shape.family not in ("I", "channel"):
        return None
    tf_data = data.tensionField
    d = shape.dims
    h, tw = d["h"], d["tw"]
    aspect = a / h
    h_tw = h / tw
    plain = aspect > tf_data.aspectMax or aspect > (tf_data.webLimit / h_tw) ** 2
    kv = tf_data.kv if plain else tf_data.kv + tf_data.kv / aspect**2
    why = []
    if plain:
        why.append(f"a/h = {aspect:.2f} beyond the limits: kv of an unstiffened web")
    flanges = 2 * d["bf"] * d["tf"]
    if 2 * d["d"] * tw / flanges > tf_data.webFlange:
        why.append(f"2 Aw / (Afc + Aft) > {tf_data.webFlange:g}")
    if h / d["bf"] > tf_data.depthFlange:
        why.append(f"h / bf > {tf_data.depthFlange:g}")
    return {"kv": kv, "aspect": aspect, "tfa": not plain and len(why) == 0, "why": why}


def shear_major(
    shape: ShapeProperties,
    steel: Steel,
    lv: float = 0.0,
    stiffeners: float | None = None,
    tension_field: bool = False,
) -> Capacity:
    """φv Vn along the profile's depth (y). ``stiffeners``: the clear spacing a [mm] of the
    transverse web stiffeners of an I-shape or channel (kv of a stiffened web, B31);
    ``tension_field``: count tension field action where it is permitted (Sec 10.7.3; the
    caller leaves it off in the end panels)."""
    e, fy = steel.e, steel.fy
    d = shape.dims
    web = stiffened_web(shape, steel, stiffeners) if stiffeners else None
    match shape.family:
        case "I" | "channel" if web is not None:
            return _stiffened_shear(shape, steel, web, stiffeners or 0.0, tension_field)
        case "I" | "channel":
            h_tw = d["h"] / d["tw"]
            aw = d["d"] * d["tw"]
            if h_tw >= 260:
                raise SteelDesignError(f"web h/tw = {h_tw:.0f} ≥ 260 needs stiffeners (Sec 10.7.2)")
            if shape.family == "I" and h_tw <= 2.24 * math.sqrt(e / fy):
                return Capacity(
                    1.0,
                    0.6 * fy * aw,
                    "shear yielding",
                    _s("shearWebYield"),
                    f"Aw = d tw = {aw:.0f} mm², h/tw = {h_tw:.1f}, φv = 1.0, Cv = 1.0",
                )
            cv = web_shear_coefficient(h_tw, 5.0, e, fy)
            return Capacity(
                _phi("shear"),
                0.6 * fy * aw * cv,
                "shear yielding / buckling",
                _s("shearWeb"),
                f"Aw = {aw:.0f} mm², h/tw = {h_tw:.1f}, kv = 5, Cv = {cv:.3f}",
            )
        case "tee":
            aw = d["d"] * d["tw"]
            cv = web_shear_coefficient(d["d"] / d["tw"], 1.2, e, fy)
            return Capacity(
                _phi("shear"),
                0.6 * fy * aw * cv,
                "shear yielding / buckling",
                _s("shearWeb"),
                f"tee stem: Aw = d tw = {aw:.0f} mm², kv = 1.2, Cv = {cv:.3f}",
            )
        case "angle":
            aw = d["d"] * d["t"]
            return Capacity(
                _phi("shear"),
                0.6 * fy * aw,
                "shear yielding",
                _s("shearSingly"),
                f"leg {d['d']:g} mm: Aw = b t = {aw:.0f} mm², Cv = 1.0",
            )
        case "rhs":
            return _rhs_shear(shape, steel, d["h"])
        case "chs":
            return _chs_shear(shape, steel, lv)
        case "bar" | "round":
            return _bar_shear(shape, steel)
    raise SteelDesignError(f"unknown shape family {shape.family}")


def _stiffened_shear(
    shape: ShapeProperties, steel: Steel, web: dict[str, Any], a: float, tension_field: bool
) -> Capacity:
    """A stiffened web: Vn of Sec 10.7.2.1 with kv of the stiffener spacing, or with tension
    field action (Sec 10.7.3.2, Eqs 6.10.142-143) when permitted and asked for."""
    from saengine.design.steel.torsion import clause, members_data

    e, fy = steel.e, steel.fy
    d = shape.dims
    h_tw = d["h"] / d["tw"]
    aw = d["d"] * d["tw"]
    kv, aspect = web["kv"], web["aspect"]
    cv = web_shear_coefficient(h_tw, kv, e, fy)
    note = f"Aw = {aw:.0f} mm², h/tw = {h_tw:.1f}, a = {a:.0f} mm, a/h = {aspect:.2f}, kv = "
    note += f"{kv:.2f}, Cv = {cv:.3f}"
    if tension_field and web["tfa"]:
        factor = members_data().tensionField.factor
        if h_tw <= 1.10 * math.sqrt(kv * e / fy):
            vn = 0.6 * fy * aw
        else:
            vn = 0.6 * fy * aw * (cv + (1 - cv) / (factor * math.sqrt(1 + aspect**2)))
        return Capacity(
            _phi("shear"),
            vn,
            "tension field yielding",
            clause("tensionField"),
            note + "; tension field action",
        )
    if web["why"]:
        note += "; no tension field action: " + ", ".join(web["why"])
    if h_tw >= 260 and kv <= members_data().tensionField.kv:
        raise SteelDesignError(f"web h/tw = {h_tw:.0f} ≥ 260 needs stiffeners (Sec 10.7.2)")
    return Capacity(
        _phi("shear"),
        0.6 * fy * aw * cv,
        "shear yielding / buckling",
        clause("stiffenedShear"),
        note,
    )


def stiffener_requirements(
    shape: ShapeProperties, steel: Steel, a: float, vr_vc: float, tension_field: bool
) -> list[str]:
    """What the transverse stiffeners at ``a`` [mm] must provide (default pack BNBC 2020 Secs 10.7.2.2,
    10.7.3.3: Eqs 6.10.141, 6.10.144), for the member's notes; ``vr_vc`` the largest Vr / Vc of
    the panels with tension field action. Pairs of stiffeners of the web's steel assumed."""
    from saengine.design.steel.torsion import clause, members_data

    data = members_data()
    web = stiffened_web(shape, steel, a)
    if data is None or web is None:
        return []
    k = data.tensionField
    e, fy = steel.e, steel.fy
    d = shape.dims
    h, tw = d["h"], d["tw"]
    ref = clause("stiffeners")
    out = []
    if h / tw <= k.stiffenerFree * math.sqrt(e / fy):
        out.append(
            f"transverse stiffeners not required by the web: h/tw = {h / tw:.1f} <= "
            f"{k.stiffenerFree:g} √(E/Fy) ({ref})"
        )
    ja, jb, jc = k.stiffenerJ
    j = max(ja / web["aspect"] ** 2 - jb, jc)
    out.append(
        f"transverse stiffeners at a = {a:.0f} mm: Ist >= a tw³ j = {a * tw**3 * j / 1e4:.1f}"
        f"×10⁴ mm⁴ (j = {j:.2f}) ({ref})"
    )
    if tension_field and web["tfa"]:
        cv = web_shear_coefficient(h / tw, web["kv"], e, fy)
        ds = k.Ds.get("pair", 1.0)
        ast = max(0.0, k.stiffenerArea * ds * h * tw * (1 - cv) * vr_vc - k.stiffenerWeb * tw**2)
        out.append(
            f"tension field stiffeners (pairs, Ds = {ds:g}, Fyst = Fy): (b/t)st <= "
            f"{k.stiffenerBt * (e / fy) ** 0.5:.1f}, Ast >= {ast:.0f} mm² at Vr/Vc = "
            f"{vr_vc:.2f} ({ref})"
        )
    return out


def _rhs_shear(shape: ShapeProperties, steel: Steel, h: float) -> Capacity:
    t = shape.dims["t"]
    aw = 2 * h * t
    cv = web_shear_coefficient(h / t, 5.0, steel.e, steel.fy)
    return Capacity(
        _phi("shear"),
        0.6 * steel.fy * aw * cv,
        "shear yielding / buckling",
        _s("shearHss"),
        f"Aw = 2 h t = {aw:.0f} mm², h/t = {h / t:.1f}, kv = 5, Cv = {cv:.3f}",
    )


def shear_minor(shape: ShapeProperties, steel: Steel, lv: float = 0.0) -> Capacity:
    """φv Vn along the profile's width (x)."""
    e, fy = steel.e, steel.fy
    d = shape.dims
    match shape.family:
        case "I" | "channel" | "tee":
            flanges = 1 if shape.family == "tee" else 2
            b = d["bf"] / 2 if shape.family != "channel" else d["bf"]
            cv = web_shear_coefficient(b / d["tf"], 1.2, e, fy)
            aw = flanges * d["bf"] * d["tf"]
            return Capacity(
                _phi("shear"),
                0.6 * fy * aw * cv,
                "shear yielding / buckling",
                _s("shearMinor"),
                f"Aw = bf tf per flange, {aw:.0f} mm², b/t = {b / d['tf']:.1f}, kv = 1.2, "
                f"Cv = {cv:.3f}",
            )
        case "angle":
            aw = d["b"] * d["t"]
            return Capacity(
                _phi("shear"),
                0.6 * fy * aw,
                "shear yielding",
                _s("shearSingly"),
                f"leg {d['b']:g} mm: Aw = b t = {aw:.0f} mm², Cv = 1.0",
            )
        case "rhs":
            return _rhs_shear(shape, steel, d["b"])
        case "chs":
            return _chs_shear(shape, steel, lv)
        case "bar" | "round":
            return _bar_shear(shape, steel)
    raise SteelDesignError(f"unknown shape family {shape.family}")


# ─────────────────────────────────── interaction ───────────────────────────────────


def interaction(
    pr: float, pc: float, mrx: float, mcx: float, mry: float, mcy: float
) -> tuple[float, str]:
    """Eq 6.10.147a / b with absolute required and design strengths; (ratio, equation)."""
    p = abs(pr) / pc if pc > 0 else (0.0 if pr == 0 else math.inf)
    mx = abs(mrx) / mcx if mcx > 0 else (0.0 if mrx == 0 else math.inf)
    my = abs(mry) / mcy if mcy > 0 else (0.0 if mry == 0 else math.inf)
    if p >= 0.2:
        return p + 8 / 9 * (mx + my), "Eq 6.10.147a"
    return p / 2 + mx + my, "Eq 6.10.147b"


@dataclass(frozen=True)
class AnglePrincipal:
    """A single angle about its principal axes for Sec 10.8.2 (B31): ``cos``, ``sin`` of the
    major principal axis w from the profile's x-axis, the design strengths φb Mn about w and z
    [N·mm] (toe in compression: the lower of either sense) and how they were found."""

    cos: float
    sin: float
    mcw: float
    mcz: float
    note: str


def _angle_beta_w(shape: ShapeProperties, w: np.ndarray, z: np.ndarray) -> float:
    """|βw| of an unequal-leg angle, (1/Iw) ∫ z (w² + z²) dA - 2 z0 on the legs' centrelines
    (z0: the shear centre, at the legs' intersection), in the principal frame."""
    d = shape.dims
    t, cx, cy = d["t"], d["cx"], d["cy"]
    n = 200
    ys = np.linspace(0, d["d"], n + 1)
    xs = np.linspace(t, d["b"], n + 1)
    pts = [(t / 2 - cx, 0.5 * (ys[i] + ys[i + 1]) - cy, (ys[i + 1] - ys[i]) * t) for i in range(n)]
    pts += [(0.5 * (xs[i] + xs[i + 1]) - cx, t / 2 - cy, (xs[i + 1] - xs[i]) * t) for i in range(n)]
    iw = integral = 0.0
    for x, y, da in pts:
        pw, pz = x * w[0] + y * w[1], x * z[0] + y * z[1]
        iw += pz * pz * da
        integral += pz * (pw * pw + pz * pz) * da
    x0, y0 = t / 2 - cx, t / 2 - cy
    z0 = x0 * z[0] + y0 * z[1]
    return abs(integral / iw - 2 * z0) if iw > 0 else 0.0


def angle_principal(shape: ShapeProperties, steel: Steel, lb: float, cb: float) -> AnglePrincipal:
    """φb Mn of a single angle about its major (w) and minor (z) principal axes (Sec 10.6.10:
    yielding 1.5 My, lateral-torsional buckling about w with Me of Eq 6.10.116 (equal legs) or
    6.10.117 (unequal legs, βw negative: the long leg taken in compression, conservative), and
    leg local buckling with the toe in compression)."""
    e, fy = steel.e, steel.fy
    d = shape.dims
    t = d["t"]
    # Principal directions of the second-moment matrix [[∫x², ∫xy], [∫xy, ∫y²]]: the axis of
    # the largest inertia (w) is normal to the eigenvector of the largest eigenvalue.
    values, vectors = np.linalg.eigh(np.array([[shape.iy, shape.ixy], [shape.ixy, shape.ix]]))
    n_w, n_z = vectors[:, 1], vectors[:, 0]  # normals: distance from w along n_w
    iw, iz = float(values[1]), float(values[0])
    w_dir = np.array([-n_w[1], n_w[0]])  # the w axis itself
    cx, cy = d["cx"], d["cy"]
    corners = [(0, 0), (0, d["d"]), (t, d["d"]), (d["b"], 0), (d["b"], t), (t, t)]
    toes = corners[1:5]

    def modulus(normal: np.ndarray, inertia: float, points: list) -> float:
        reach = max(abs((x - cx) * normal[0] + (y - cy) * normal[1]) for x, y in points)
        return inertia / reach

    s_w, s_z = modulus(n_w, iw, corners), modulus(n_z, iz, corners)
    sc_w, sc_z = modulus(n_w, iw, toes), modulus(n_z, iz, toes)
    leg = max(d["d"], d["b"])
    ratio = leg / t
    root = math.sqrt(e / fy)

    def local(sc: float) -> float | None:
        if ratio <= 0.54 * root:
            return None
        if ratio <= 0.91 * root:
            return fy * sc * (2.43 - 1.72 * ratio / root)
        return 0.71 * e / ratio**2 * sc

    my_w, my_z = fy * s_w, fy * s_z
    mn_w = [1.5 * my_w]
    notes = [f"principal axes: Iw = {iw / 1e4:.1f}, Iz = {iz / 1e4:.1f}×10⁴ mm⁴"]
    if lb > 0:
        cbx = min(cb, 1.5)
        if abs(d["d"] - d["b"]) < 1e-9:
            me = 0.46 * e * leg**2 * t**2 * cbx / lb
            notes.append(f"Me = {me / 1e6:.1f} kN·m (Eq 6.10.116)")
        else:
            beta = -_angle_beta_w(shape, w_dir, np.array([-w_dir[1], w_dir[0]]))
            rz = math.sqrt(iz / shape.area)
            me = (
                4.9
                * e
                * iz
                * cbx
                / lb**2
                * (math.sqrt(beta**2 + 0.052 * (lb * t / rz) ** 2) + beta)
            )
            notes.append(f"Me = {me / 1e6:.1f} kN·m (Eq 6.10.117, βw = {beta:.1f} mm)")
        if me <= my_w:
            mn_w.append((0.92 - 0.17 * me / my_w) * me)
        else:
            mn_w.append(min((1.92 - 1.17 * math.sqrt(my_w / me)) * my_w, 1.5 * my_w))
    mn_z = [1.5 * my_z]
    for target, sc in ((mn_w, sc_w), (mn_z, sc_z)):
        found = local(sc)
        if found is not None:
            target.append(found)
    phi = _phi("flexure")
    return AnglePrincipal(
        float(w_dir[0]),
        float(w_dir[1]),
        phi * min(mn_w),
        phi * min(mn_z),
        "; ".join(notes),
    )


def unsymmetric_interaction(
    p: float, pc: float, mx: float, my: float, principal: AnglePrincipal
) -> tuple[float, float, float]:
    """Eq 6.10.149 of a single angle, |fa/Fa| + |fbw/Fbw| + |fbz/Fbz| with the stress ratios
    at their critical points added (conservative: the sense of the stresses is not used):
    (ratio, Mw, Mz). ``mx``, ``my``: the (amplified) moments about the profile's axes [N·mm]."""
    mw = abs(mx * principal.cos) + abs(my * principal.sin)
    mz = abs(mx * principal.sin) + abs(my * principal.cos)
    pa = abs(p) / pc if pc > 0 else (0.0 if p == 0 else math.inf)
    fw = mw / principal.mcw if principal.mcw > 0 else math.inf
    fz = mz / principal.mcz if principal.mcz > 0 else math.inf
    return pa + fw + fz, mw, mz


def amplifier_b1(cm: float, pr: float, pe1: float) -> float:
    """B1 = Cm / (1 - αPr / Pe1) >= 1 (Eq 6.10.4, α = 1.0 for LRFD)."""
    if pr <= 0:
        return 1.0
    if pr >= pe1:
        return math.inf
    return max(1.0, cm / (1 - pr / pe1))


def moment_coefficient(s: np.ndarray, m: np.ndarray, start: float, end: float) -> float:
    """Cm (Eq 6.10.6) of the segment [start, end]: 0.6 - 0.4 M1/M2 when the diagram is linear
    between the ends (no transverse load), else 1.0 (Sec 10.3.2.1, p 3832)."""
    inside = (s >= start - 1e-9) & (s <= end + 1e-9)
    if inside.sum() < 2:
        return 1.0
    ss, mm = s[inside], m[inside]
    m1, m2 = float(np.interp(start, s, m)), float(np.interp(end, s, m))
    line = m1 + (m2 - m1) * (ss - start) / max(end - start, 1e-12)
    peak = float(np.max(np.abs(mm)))
    if peak <= 0:
        return 1.0
    if float(np.max(np.abs(mm - line))) > 0.02 * peak:
        return 1.0
    small, large = sorted((m1, m2), key=abs)
    if abs(large) <= 0:
        return 1.0
    # The moments are in one convention along the member (positive stretches the top), so
    # end moments of the same sign bend it in single curvature: M1/M2 is then negative.
    ratio = -small / large
    return 0.6 - 0.4 * ratio


# ──────────────────────────────────── the member ────────────────────────────────────


@dataclass
class SteelOptions:
    """``erw``: hollow sections are ERW (0.93 t); ``net_ratio``: An / Ag of tension members;
    ``shear_lag``: U (default per shape, :func:`default_shear_lag`); ``lengths``: bracing
    overrides; ``amplify``: moments of members in compression by B1; ``stability``: the
    stability design method of the run (:class:`saengine.design.steel.stability.Stability`;
    None: K from the bracing, no stability checks); ``anchors``: the earthquake side of the run
    for the anchors in concrete (:class:`saengine.design.anchors.SeismicContext`; None: no
    seismic anchor rules). B31: ``stiffener_spacing`` the clear distance a [mm] between the
    transverse web stiffeners (None: unstiffened web), ``tension_field`` whether tension field
    action is counted where it is permitted, ``warping`` the ends' restraint against warping
    ("free" or "fixed") in the torsion of open sections, ``built_up`` how the components of a
    built-up member are joined (:class:`saengine.design.steel.built_up.BuiltUp` or its
    model)."""

    erw: bool = True
    net_ratio: float = 1.0
    shear_lag: float | None = None
    lengths: LengthOptions = field(default_factory=LengthOptions)
    amplify: bool = True
    stability: Any = None
    anchors: Any = None
    stiffener_spacing: float | None = None
    tension_field: bool = True
    warping: str = "free"
    built_up: Any = None

    @classmethod
    def of(cls, value: SteelOptions | dict[str, Any] | None) -> SteelOptions:
        if isinstance(value, SteelOptions):
            return value
        value = dict(value or {})
        lengths = value.pop("lengths", None)
        options = cls(**{k: v for k, v in value.items() if k in cls.__dataclass_fields__})
        if isinstance(lengths, dict):
            options.lengths = LengthOptions(**lengths)
        elif isinstance(lengths, LengthOptions):
            options.lengths = lengths
        return options


@dataclass
class Stations:
    """One combination's section forces along a member, sorted by position: ``s`` [m], ``P``
    (compression positive) [N], ``Mx`` (positive stretches the top) and ``My`` [N·mm], ``Vy``
    (along the depth) and ``Vx`` [N], and where each station is; ``T`` the torque about the
    member's axis [N·mm] (B31; None: not known, torsion is not checked)."""

    combination: str
    s: np.ndarray
    P: np.ndarray
    Mx: np.ndarray
    My: np.ndarray
    Vy: np.ndarray
    Vx: np.ndarray
    where: list[str]
    T: np.ndarray | None = None


def member_stations(
    pieces: Sequence[Any], combinations: Sequence[str], turned: bool = False
) -> list[Stations]:
    """The forces of the member's analysis pieces per combination, in the profile's axes
    (as :func:`saengine.design.check._profile_forces` gives them) and sorted along it."""
    from saengine.design.check import _profile_forces

    if not pieces:
        return []
    count = len(pieces[0].forces[0]) if pieces[0].forces else 0
    s, order = positions(pieces, count)
    result = []
    for c, name in enumerate(combinations):
        values = [_profile_forces(p, turned, p.forces[c]) for p in pieces]

        def gather(key: str, values: list[dict[str, np.ndarray]] = values) -> np.ndarray:
            return np.array([float(values[p][key][k]) for p, k in order])

        where = [f"{pieces[p].name} at {k / max(count - 1, 1):.2f} L" for p, k in order]
        result.append(
            Stations(
                name,
                s,
                gather("P"),
                gather("Mx"),
                gather("My"),
                gather("Vy"),
                gather("Vx"),
                where,
                _torque(pieces, c, order),
            )
        )
    return result


def _torque(pieces: Sequence[Any], c: int, order: Sequence[tuple[int, int]]) -> np.ndarray | None:
    """The torque [N·mm] of combination ``c`` at the stations ``order`` (B31): column 3 of the
    pieces' forces [N·m]; None when the forces carry no torque column."""
    try:
        return np.array([float(np.asarray(pieces[p].forces[c])[k, 3]) * 1e3 for p, k in order])
    except (IndexError, TypeError, ValueError):
        return None


@dataclass
class _Worst:
    utilisation: float = -1.0
    demand: float = 0.0
    capacity: float = 0.0
    combination: str | None = None
    note: str = ""
    clause: str = ""

    def offer(
        self, u: float, demand: float, capacity: float, combination: str, note: str, clause: str
    ) -> None:
        if u > self.utilisation:
            self.utilisation, self.demand, self.capacity = u, demand, capacity
            self.combination, self.note, self.clause = combination, note, clause


def _check(
    name: str,
    worst: _Worst,
    unit: str,
    scale: float,
    flag: bool = False,
) -> dict[str, Any]:
    u = worst.utilisation
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(worst.demand) / scale, 2),
        "capacity": round(float(worst.capacity) / scale, 2),
        "unit": unit,
        "utilisation": u,
        "combination": worst.combination,
        "ok": bool(u <= 1.0),
        "note": worst.note,
        "flag": flag,
        "clause": worst.clause,
    }


def _ratio(demand: float, capacity: float) -> float:
    if capacity > 0:
        return demand / capacity
    return 0.0 if demand <= 0 else math.inf


class _MemberTorsion:
    """The torsion checks of one member (B31, :mod:`saengine.design.steel.torsion`): HSS by
    their torsional strength and the interaction with the other forces, other members by the
    normal and shear stresses of the combined actions and buckling."""

    def __init__(self, shape: ShapeProperties, steel: Steel, length: float, warping: str) -> None:
        from saengine.design.steel import torsion as tor

        self.tor = tor
        self.shape, self.steel, self.length, self.warping = shape, steel, length, warping
        data = tor.members_data()
        self.data = data.torsion
        self.hss = shape.family in ("rhs", "chs")
        self.capacity = tor.hss_torsion(shape, steel.fy, steel.e, length) if self.hss else None
        methods = self.data.methods
        self.open_method = methods.get("openSection") == "warping" and not self.hss
        self.buckling = methods.get("buckling") == "leastCritical" and not self.hss
        self.section = tor.section_torsion(shape) if not self.hss else None
        self.g = _shear_modulus()
        self.solutions: dict[int, Any] = {}
        self.worst = {k: _Worst() for k in ("t", "t155", "tn", "tv", "tb")}
        self.combined = False

    @classmethod
    def of(
        cls,
        shape: ShapeProperties,
        steel: Steel,
        stations: Sequence[Stations],
        length: float,
        warping: str,
    ) -> _MemberTorsion | None:
        from saengine.design.steel.torsion import has_torsion, members_data

        if members_data() is None or not any(has_torsion(st.T) for st in stations):
            return None
        return cls(shape, steel, length, warping)

    def solution(self, st: Stations) -> Any:
        key = id(st)
        if key not in self.solutions:
            self.solutions[key] = self.tor.solve_warping(
                st.s, st.T, self.g, self.steel.e, self.shape.j, self.shape.cw, self.warping
            )
        return self.solutions[key]

    def offer(
        self,
        st: Stations,
        k: int,
        p: float,
        pc: float,
        cap_c: Capacity | None,
        cap_mx: Capacity,
        mrx: float,
        mry: float,
        mcy: float,
        vy: float,
        vx: float,
        vcy: float,
        vcx: float,
        where: str,
    ) -> None:
        if st.T is None:
            return
        tor, shape, fy = self.tor, self.shape, self.steel.fy
        phi = self.data.phi
        tr = abs(float(st.T[k]))
        if self.hss:
            cap = self.capacity
            if cap is None:
                return
            tc = cap.design
            self.worst["t"].offer(
                _ratio(tr, tc), tr, tc, st.combination, f"{cap.note}; {where}", cap.clause
            )
            if tr > self.data.neglect * tc:
                self.combined = True
                pr = _ratio(abs(p), pc)
                mr = _ratio(mrx, cap_mx.design) + _ratio(mry, mcy)
                vr = _ratio(vy, vcy) + _ratio(vx, vcx)
                ratio = tor.hss_interaction(pr, mr, vr, _ratio(tr, tc))
                self.worst["t155"].offer(
                    ratio,
                    ratio,
                    1.0,
                    st.combination,
                    f"Pr/Pc = {pr:.2f}, ΣMr/Mc = {mr:.2f}, ΣVr/Vc = {vr:.2f}, Tr/Tc = "
                    f"{_ratio(tr, tc):.2f}; {where}",
                    tor.clause("torsionHssCombined"),
                )
            return
        if not self.open_method:
            return
        sol = self.solution(st)
        stress = tor.torsion_stresses(
            self.section,
            self.g,
            self.steel.e,
            float(sol.phi1[k]),
            float(sol.phi2[k]),
            float(sol.phi3[k]),
        )
        fa = abs(p) / shape.area
        fbx, fby = mrx / shape.sx, mry / shape.sy
        normal = fa + fbx + fby + stress.normal
        limit = phi * self.data.normalYield * fy
        what = (
            f"fa = {fa:.1f}, fbx = {fbx:.1f}, fby = {fby:.1f}, σw = {stress.normal:.1f} MPa; T = "
            f"{float(sol.torque[k]) / 1e6:.2f} kN·m (warping {self.warping} at the supports); "
            f"{where}"
        )
        self.worst["tn"].offer(
            normal / limit, normal, limit, st.combination, what, tor.clause("torsionNormal")
        )
        v_flange, v_web = tor.shear_stresses(shape, vy, vx)
        flange, web = v_flange + stress.shear_flange, v_web + stress.shear_web
        tau = max(flange, web)
        limit_v = phi * self.data.shearYield * fy
        self.worst["tv"].offer(
            tau / limit_v,
            tau,
            limit_v,
            st.combination,
            f"flange {flange:.1f} MPa (shear {v_flange:.1f} + torsion {stress.shear_flange:.1f}), "
            f"web {web:.1f} MPa (shear {v_web:.1f} + torsion {stress.shear_web:.1f}); {where}",
            tor.clause("torsionShear"),
        )
        if not self.buckling:
            return
        critical = []
        if p > 0 and cap_c is not None:
            critical.append((cap_c.nominal / shape.area, "axial"))
        if mrx > 0:
            critical.append((cap_mx.nominal / shape.sx, "lateral-torsional"))
        if not critical:
            return
        fcr, mode = min(critical)
        compressive = (fa if p > 0 else 0.0) + fbx + fby + stress.normal
        cap = phi * min(fcr, fy)
        self.worst["tb"].offer(
            compressive / cap,
            compressive,
            cap,
            st.combination,
            f"compressive stress {compressive:.1f} MPa against φT Fcr, Fcr = {fcr:.1f} MPa "
            f"({mode}, the least critical stress); {where}",
            tor.clause("torsionBuckling"),
        )

    def rows(self) -> list[dict[str, Any]]:
        if self.hss:
            if self.capacity is None:
                return []
            out = [_check("Torsion (HSS)", self.worst["t"], "kN·m", 1e6)]
            if self.combined:
                out.append(
                    _check(
                        "Torsion, shear, flexure and axial force (HSS)", self.worst["t155"], "", 1
                    )
                )
            else:
                out[0]["note"] += (
                    f"; Tr <= {self.data.neglect:g} Tc: torsion neglected, the combined-force "
                    "check governs"
                )
            return out
        out = []
        if self.open_method:
            out.append(_check("Torsion: normal stress (yielding)", self.worst["tn"], "MPa", 1.0))
            out.append(_check("Torsion: shear stress (yielding)", self.worst["tv"], "MPa", 1.0))
        if self.buckling and self.worst["tb"].combination is not None:
            out.append(_check("Torsion: buckling", self.worst["tb"], "MPa", 1.0))
        return out


def check_member(
    shape: ShapeProperties,
    steel: Steel,
    stations: Sequence[Stations],
    lengths: MemberLengths,
    kind: str = "member",
    options: SteelOptions | dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The strength checks of one steel member, enveloping its combinations and stations, in
    the design report's format (``{name, demand, capacity, unit, utilisation, combination, ok,
    note, flag, clause}``, forces in kN and kN·m)."""
    options = SteelOptions.of(options)
    e = steel.e
    tension_y = tension_yielding(shape, steel)
    tension_r = tension_rupture(shape, steel, options.shear_lag, options.net_ratio)
    phi_tn = min(tension_y.design, tension_r.design)
    lv = max(lengths.x.longest(), lengths.y.longest()) * 1e3
    v_major = shear_major(shape, steel, lv)
    v_minor = shear_minor(shape, steel, lv)
    m_minor = flexure_minor(shape, steel, lengths.ltb_top.longest() * 1e3)
    # B31: a stiffened web (tension field action outside the end panels), a built-up member,
    # torsion, and single angles about their principal axes (Sec 10.8.2).
    from saengine.design.steel.built_up import BuiltUp, dimensional_checks, modified_slenderness
    from saengine.design.steel.torsion import clause as pack_clause
    from saengine.design.steel.torsion import members_data

    stiffened = options.stiffener_spacing if shape.family in ("I", "channel") else None
    v_end = v_major
    if stiffened and members_data() is not None:
        v_major = shear_major(shape, steel, lv, stiffened, options.tension_field)
        v_end = shear_major(shape, steel, lv, stiffened, False)
        if v_major.state == "tension field yielding":
            v_end = Capacity(
                v_end.phi,
                v_end.nominal,
                v_end.state,
                v_end.clause,
                f"{v_end.note}; end panel: no tension field action",
            )
    else:
        stiffened = None
    worst_tfa = 0.0
    built = BuiltUp.of(options.built_up)
    torsion = _MemberTorsion.of(shape, steel, stations, lengths.length * 1e3, options.warping)
    principal = (
        angle_principal(
            shape,
            steel,
            max(lengths.ltb_top.longest(), lengths.ltb_bottom.longest()) * 1e3,
            1.0,
        )
        if shape.family == "angle" and members_data() is not None
        else None
    )

    compression_cache: dict[tuple[float, float, float], Capacity] = {}
    flexure_cache: dict[tuple[float, float, bool], Capacity] = {}
    # The stability design method (saengine.design.steel.stability): the direct analysis
    # method's K and reduced stiffness for B1.
    stability = options.stability
    unit_k = getattr(stability, "unit_k", None)
    direct = bool(getattr(stability, "direct", False))
    py_member = steel.fy * shape.area

    def comp(klx: float, kly: float, klz: float) -> Capacity:
        key = (round(klx, 1), round(kly, 1), round(klz, 1))
        if key not in compression_cache:
            note = ref = ""
            if built is not None and built.spacing > 0:
                # The buckling mode that shears the connectors: KL/r replaced by (KL/r)m.
                r = shape.ry if built.axis == "y" else shape.rx
                kl = kly if built.axis == "y" else klx
                modified, note, ref = modified_slenderness(built, kl / r)
                if built.axis == "y":
                    kly = modified * r
                else:
                    klx = modified * r
            cap = compression(shape, steel, klx, kly, klz)
            if note:
                cap = Capacity(
                    cap.phi,
                    cap.nominal,
                    cap.state,
                    f"{cap.clause}; {ref}" if ref else cap.clause,
                    f"{cap.note}; {note}",
                )
            compression_cache[key] = cap
        return compression_cache[key]

    def flex(lb: float, cb: float, top: bool) -> Capacity:
        key = (round(lb, 1), round(cb, 3), top)
        if key not in flexure_cache:
            flexure_cache[key] = flexure_major(shape, steel, lb, cb, top)
        return flexure_cache[key]

    worst = {
        k: _Worst()
        for k in ("ty", "tr", "c", "mx", "my", "vy", "vx", "h1", "klr", "lr", "k1", "h2")
    }
    compressed = tensioned = False
    for st in stations:
        s = st.s
        for k in range(len(s)):
            p = float(st.P[k])
            where = st.where[k]
            kx, lx, _ = lengths.effective("x", float(s[k]), unit_k)
            ky, ly, _ = lengths.effective("y", float(s[k]), unit_k)
            kz = lengths.k.get("z", 1.0) if unit_k is None else unit_k
            if p < 0:
                tensioned = True
                t = -p
                worst["ty"].offer(
                    _ratio(t, tension_y.design),
                    t,
                    tension_y.design,
                    st.combination,
                    f"{tension_y.note}; {where}",
                    tension_y.clause,
                )
                worst["tr"].offer(
                    _ratio(t, tension_r.design),
                    t,
                    tension_r.design,
                    st.combination,
                    f"{tension_r.note}; {where}",
                    tension_r.clause,
                )
                r_least = shape.rz if shape.family == "angle" else min(shape.rx, shape.ry)
                lr = max(lx, ly) / r_least
                worst["lr"].offer(
                    lr / _slenderness("tension"),
                    lr,
                    _slenderness("tension"),
                    st.combination,
                    f"L/r with r = {r_least:.1f} mm; {where}",
                    _s("tensionSlenderness"),
                )
            pc = phi_tn
            cap_c = None
            if p > 0:
                compressed = True
                cap_c = comp(kx * lx, ky * ly, kz * ly)
                pc = cap_c.design
                worst["c"].offer(
                    _ratio(p, pc), p, pc, st.combination, f"{cap_c.note}; {where}", cap_c.clause
                )
                klr = compression_slenderness(shape, kx * lx, ky * ly)
                worst["klr"].offer(
                    klr / _slenderness("compression"),
                    klr,
                    _slenderness("compression"),
                    st.combination,
                    (
                        f"K = {kx:g} / {ky:g} (direct analysis method), "
                        if direct
                        else f"K = {kx:g}{source_tag(lengths, 'kx')} / "
                        f"{ky:g}{source_tag(lengths, 'ky')}, "
                    )
                    + f"L = {lx:.0f}{source_tag(lengths, 'Lx')} / {ly:.0f}"
                    f"{source_tag(lengths, 'Ly')} mm; {where}",
                    _s("compressionSlenderness"),
                )
                if kind == "column" and not direct:
                    share = getattr(stability, "first_order_axial", 0.5)
                    worst["k1"].offer(
                        _ratio(p, share * py_member),
                        p,
                        share * py_member,
                        st.combination,
                        f"K = 1 by first-order analysis needs αPr ≤ {share:g} Py; otherwise use "
                        "K from a sidesway analysis",
                        stability.clause("firstOrderUnitK")
                        if stability is not None
                        else _s("firstOrderUnitK"),
                    )

            # Flexure about x: the unbraced length of the flange in compression.
            mx = float(st.Mx[k])
            top = mx < 0
            ltb = lengths.ltb_top if top else lengths.ltb_bottom
            # At a brace point both segments meeting there are checked; the weaker governs.
            cap_mx = min(
                (
                    flex((b - a) * 1e3, 1.0 if free else cb_from_diagram(s, st.Mx, a, b), top)
                    for a, b, free in ltb.around_all(float(s[k]))
                ),
                key=lambda c: c.design,
            )
            my = float(st.My[k])
            b1x = b1y = 1.0
            if p > 0 and options.amplify:
                xa, xb, _ = lengths.x.around(float(s[k]))
                ya, yb, _ = lengths.y.around(float(s[k]))
                # Direct analysis method: Pe1 on the reduced stiffness 0.8 τb EI.
                e1 = e * (stability.flexural_stiffness(p, py_member) if direct else 1.0)
                b1x = amplifier_b1(
                    moment_coefficient(s, st.Mx, xa, xb), p, _euler_load(e1, shape.ix, kx * lx)
                )
                b1y = amplifier_b1(
                    moment_coefficient(s, st.My, ya, yb), p, _euler_load(e1, shape.iy, ky * ly)
                )
            mrx, mry = abs(mx) * b1x, abs(my) * b1y
            note_b1 = f"; B1 = {b1x:.2f} / {b1y:.2f}" if (b1x > 1 or b1y > 1) else ""
            worst["mx"].offer(
                _ratio(mrx, cap_mx.design),
                mrx,
                cap_mx.design,
                st.combination,
                f"{cap_mx.note}{note_b1}; {where}",
                cap_mx.clause,
            )
            worst["my"].offer(
                _ratio(mry, m_minor.design),
                mry,
                m_minor.design,
                st.combination,
                f"{m_minor.note}{note_b1}; {where}",
                m_minor.clause,
            )
            vy, vx = abs(float(st.Vy[k])), abs(float(st.Vx[k]))
            v_here = v_major
            if stiffened:
                # No tension field action in the end panels (Sec 10.7.3.1).
                at = float(s[k] - s[0]) * 1e3
                if at < stiffened or float(s[-1] - s[k]) * 1e3 < stiffened:
                    v_here = v_end
                elif v_here is not v_end:
                    worst_tfa = max(worst_tfa, _ratio(vy, v_here.design))
            worst["vy"].offer(
                _ratio(vy, v_here.design),
                vy,
                v_here.design,
                st.combination,
                f"{v_here.note}; {where}",
                v_here.clause,
            )
            worst["vx"].offer(
                _ratio(vx, v_minor.design),
                vx,
                v_minor.design,
                st.combination,
                f"{v_minor.note}; {where}",
                v_minor.clause,
            )
            ratio, eq = interaction(p, pc, mrx, cap_mx.design, mry, m_minor.design)
            sense = "compression" if p > 0 else "tension"
            worst["h1"].offer(
                ratio,
                ratio,
                1.0,
                st.combination,
                f"{eq}: Pr = {abs(p) / 1e3:.1f} kN ({sense}), Pc = {pc / 1e3:.1f} kN, "
                f"Mrx = {mrx / 1e6:.1f} / Mcx = {cap_mx.design / 1e6:.1f}, Mry = {mry / 1e6:.1f} "
                f"/ Mcy = {m_minor.design / 1e6:.1f} kN·m{note_b1}; {where}",
                _s("interaction") + ", " + eq,
            )
            if principal is not None:
                ratio2, mw, mz = unsymmetric_interaction(p, pc, mrx, mry, principal)
                worst["h2"].offer(
                    ratio2,
                    ratio2,
                    1.0,
                    st.combination,
                    f"Pr = {abs(p) / 1e3:.1f} kN ({sense}), Pc = {pc / 1e3:.1f} kN, Mw = "
                    f"{mw / 1e6:.2f} / Mcw = {principal.mcw / 1e6:.2f}, Mz = {mz / 1e6:.2f} / Mcz = "
                    f"{principal.mcz / 1e6:.2f} kN·m (the stress ratios at their critical "
                    f"points added); {principal.note}{note_b1}; {where}",
                    pack_clause("unsymmetric"),
                )
            if torsion is not None:
                torsion.offer(
                    st,
                    k,
                    p,
                    pc,
                    cap_c,
                    cap_mx,
                    mrx,
                    mry,
                    m_minor.design,
                    vy,
                    vx,
                    v_here.design,
                    v_minor.design,
                    where,
                )

    checks: list[dict[str, Any]] = []
    if tensioned:
        checks.append(_check("Tension: yielding (gross section)", worst["ty"], "kN", 1e3))
        checks.append(_check("Tension: rupture (net section)", worst["tr"], "kN", 1e3))
    if compressed:
        checks.append(_check("Compression: buckling", worst["c"], "kN", 1e3))
    checks.append(_check("Flexure about x (major)", worst["mx"], "kN·m", 1e6))
    checks.append(_check("Flexure about y (minor)", worst["my"], "kN·m", 1e6))
    checks.append(_check("Shear along y (depth)", worst["vy"], "kN", 1e3))
    checks.append(_check("Shear along x (width)", worst["vx"], "kN", 1e3))
    checks.append(_check("Axial force and flexure (H1)", worst["h1"], "", 1.0))
    if shape.family == "tee":
        checks[-1]["note"] += "; H1 of Sec 10.8.1 applied to a tee (singly symmetric)"
    elif shape.family == "angle" and principal is not None:
        # B31: a single angle is unsymmetric; Sec 10.8.2 governs and H1 stays for information.
        checks[-1]["flag"] = True
        checks[-1]["note"] += "; single angle: for information, Eq 6.10.149 governs"
        checks.append(
            _check("Axial force and flexure, unsymmetric (principal axes)", worst["h2"], "", 1.0)
        )
    elif shape.family == "angle":
        checks[-1]["note"] += "; single angle: the code pack has no rule for unsymmetric members"
    if torsion is not None:
        checks.extend(torsion.rows())
    if built is not None and compressed:
        checks.extend(dimensional_checks(built, worst["klr"].demand, steel.fy, steel.e))
    if stiffened:
        tfa_notes = stiffener_requirements(
            shape, steel, stiffened, worst_tfa, options.tension_field
        )
        for c in checks:
            if c["name"].startswith("Shear along y"):
                c["note"] += "; " + "; ".join(tfa_notes)
    # The slenderness limits are for members designed for axial force; a beam's axial force
    # from the frame is usually incidental, so for beams they are reported as flags.
    beam = kind == "beam"
    if compressed:
        checks.append(_check("Slenderness KL/r (compression)", worst["klr"], "", 1.0, flag=beam))
    if tensioned:
        checks.append(_check("Slenderness L/r (tension)", worst["lr"], "", 1.0, flag=beam))
    if compressed and kind == "column" and not direct:
        share = getattr(stability, "first_order_axial", 0.5)
        checks.append(
            _check(
                f"K = 1 by first-order analysis (αPr ≤ {share:g} Py)",
                worst["k1"],
                "kN",
                1e3,
                flag=True,
            )
        )
    if stability is not None:
        from saengine.design.steel.stability import member_checks

        checks.extend(member_checks(stability, shape, steel, stations, lengths.length, kind))
    for c in checks:
        if c["utilisation"] < 0:
            c.update(utilisation=0.0, ok=True, demand=0.0)
    return checks


def _euler_load(e: float, i: float, kl: float) -> float:
    """Pe1 = π² E I / (K1 L)² (Eq 6.10.7)."""
    return math.pi**2 * e * i / kl**2 if kl > 0 else math.inf


def _density(material: Any) -> float:
    mechanical = getattr(material, "mechanical", None)
    return (getattr(mechanical, "density", None) if mechanical else None) or 7850.0


def _mass_per_metre(profile: Any, material: Any) -> float:
    """The member's steel weight [kg/m] as the bill of quantities measures it
    (:func:`saengine.library.steel_sections.mass_per_metre`: the nominal section with its
    corner radii, not the design wall thickness), so the report and the BOQ agree; the sharp-
    cornered nominal section when the table cannot read the profile."""
    try:
        return steel_sections.mass_per_metre(profile, _density(material))
    except (TypeError, ValueError, KeyError, AttributeError):
        return round(shape_properties(profile, erw=False).area * 1e-6 * _density(material), 3)


# ─────────────────────────────── serviceability: deflection (B9) ───────────────────────────────


def _relative_deflection(
    s: np.ndarray, axis: np.ndarray, moved: np.ndarray, free_end: str
) -> float:
    """Largest deflection [same unit as ``moved``] of a member's nodes across its axis: relative
    to the chord between its ends, or for a cantilever (``free_end`` "start" / "end") of the
    free end relative to the supported one. ``moved``: (n, 3) node displacements along ``s``."""
    across = moved - np.outer(moved @ axis, axis)  # the part across the member
    if free_end in ("start", "end"):
        tip, root = (0, -1) if free_end == "start" else (-1, 0)
        return float(np.linalg.norm(across[tip] - across[root]))
    t = (s - s[0]) / (s[-1] - s[0])
    chord = across[0] + np.outer(t, across[-1] - across[0])
    return float(np.max(np.linalg.norm(across - chord, axis=1)))


def deflection_checks(
    s: np.ndarray,
    axis: np.ndarray,
    profiles: dict[str, np.ndarray],
    use: str | None = None,
    free_end: str = "none",
    table: Any = None,
) -> list[dict[str, Any]]:
    """The deflection rows of a beam under the code pack's member deflection limits
    (``serviceability.deflection``): ``s`` the nodes' positions along it [m], ``axis`` its unit
    direction, ``profiles`` per unfactored load case the nodes' displacements (n, 3) [m];
    ``use`` the id of the member's use in the pack (None: the pack's default). Rows of the live
    load (L + Lr), the wind (WX, WY, the larger) and the pack's dead + live service combination,
    where the use has that limit; [] when the pack has no deflection limits or the use is not
    in them."""
    from saengine.fem.combinations import service_combinations

    if table is None:
        pack = code_context.current()
        table = pack.table("serviceability") if pack.has("serviceability") else None
    limits = getattr(table, "deflection", None)
    if limits is None or len(s) < 2 or s[-1] - s[0] <= 0 or "D" not in profiles:
        return []
    key = use or limits.default
    row = limits.uses.get(key)
    if row is None:
        return []
    length = float(s[-1] - s[0]) * 1000.0
    cantilever = free_end in ("start", "end")
    span = length * (float(limits.cantileverSpan) if cantilever else 1.0)
    clause = row.source or limits.source or ""

    def summed(factors: dict[str, float]) -> np.ndarray | None:
        parts = [f * profiles[c] for c, f in factors.items() if c in profiles and f]
        return sum(parts) if parts else None

    kinds: list[tuple[str, float | None, list[tuple[str, dict[str, float]]]]] = [
        ("live load", row.live, [("L + Lr", {"L": 1.0, "Lr": 1.0})]),
        ("wind", row.wind, [(c, {c: 1.0}) for c in ("WX", "WY")]),
        (
            "dead + live load",
            row.deadLive,
            [(n, f) for n, f, _r in service_combinations(set(profiles), limits.combination)],
        ),
    ]
    out = []
    for what, divisor, combinations in kinds:
        if not divisor:
            continue
        best: tuple[float, str] | None = None
        for name, factors in combinations:
            moved = summed(factors)
            if moved is None:
                continue
            value = 1000.0 * _relative_deflection(s, axis, moved, free_end)
            if best is None or value > best[0]:
                best = (value, name)
        if best is None:
            continue
        limit = span / float(divisor)
        u = best[0] / limit if limit > 0 else 99.0
        out.append(
            {
                "name": f"Deflection: {what} ≤ l/{float(divisor):g}",
                "demand": round(best[0], 2),
                "capacity": round(limit, 2),
                "unit": "mm",
                "utilisation": round(u, 3),
                "combination": best[1],
                "ok": bool(u <= 1.0),
                "note": f"{row.label}; l = {span:.0f} mm"
                + (
                    f" ({float(limits.cantileverSpan):g} × the cantilever length), free end"
                    if cantilever
                    else ", relative to the chord"
                ),
                "flag": False,
                "clause": clause,
            }
        )
    return out


def _bracing_table() -> Any:
    """The stability bracing data of the steel table (None: the pack in force has none)."""
    try:
        return code_context.pack_table("steel").bracing
    except Exception:  # noqa: BLE001 - no pack at all
        return None


#: Above this many brace points a direction is taken as continuously braced (a slab).
_DISCRETE_BRACES = 10


def bracing_requirements(
    shape: ShapeProperties,
    stations: Sequence[Stations],
    lengths: MemberLengths,
    kind: str,
) -> list[dict[str, Any]]:
    """The strength and stiffness the stability braces of a column or beam need so that the
    member strengths taken with K = 1 between them hold (Sec 10.19 of the code pack's steel
    table): ``[{what, type, points, Lb [m], demand, Pbr [kN] or Mbr, betaBr [kN/mm], note}]``.

    Columns: nodal braces at the intermediate brace points (Eqs 6.10.287-288), or relative
    bracing at the ends when the column is braced only there (Eqs 6.10.285-286, the storey's
    bracing system). Beams (I and channel shapes): lateral nodal braces of the compression
    flange at its intermediate brace points (Eqs 6.10.291-292, Cd = 2 when the moment changes
    sign: conservative for every brace). A direction braced at many points (a slab) is
    continuous bracing and is not listed."""
    table = _bracing_table()
    if table is None:
        return []
    phi = table.phi
    out: list[dict[str, Any]] = []
    if kind == "column":
        pr = max((float(p) for st in stations for p in st.P), default=0.0)
        if pr <= 0:
            return []
        for axis, seg in (("x", lengths.x), ("y", lengths.y)):
            inner = len(seg.points) - 2
            lb = seg.longest() * 1e3
            if lb <= 0 or inner > _DISCRETE_BRACES:
                continue
            row, kind_, eqs = (
                (table.columnNodal, "nodal", "Sec 10.19.2.2 Eqs 6.10.287-288")
                if inner > 0
                else (table.columnRelative, "relative", "Sec 10.19.2.1 Eqs 6.10.285-286")
            )
            out.append(
                {
                    "what": f"column, buckling about {axis}",
                    "type": kind_,
                    "points": max(inner, 0),
                    "Lb": round(lb / 1e3, 3),
                    "demand": f"Pr = {pr / 1e3:.1f} kN",
                    "Pbr": round(row.strength * pr / 1e3, 2),
                    "betaBr": round(row.stiffness * pr / (phi * lb) / 1e3, 3),
                    "note": eqs,
                }
            )
        return out
    if kind == "beam" and shape.family in ("I", "channel"):
        ho = shape.dims.get("ho") or (shape.dims.get("d", 0.0) - shape.dims.get("tf", 0.0))
        if ho <= 0:
            return []
        mx = [float(m) for st in stations for m in st.Mx]
        if not mx:
            return []
        mr = max(abs(m) for m in mx)
        cd = 2.0 if min(mx) < 0 < max(mx) else 1.0
        for label, seg in (("top flange", lengths.ltb_top), ("bottom flange", lengths.ltb_bottom)):
            inner = len(seg.points) - 2
            if inner <= 0 or inner > _DISCRETE_BRACES or mr <= 0:
                continue
            lb = seg.longest() * 1e3
            row = table.beamNodal
            out.append(
                {
                    "what": f"beam, lateral bracing of the {label}",
                    "type": "nodal",
                    "points": inner,
                    "Lb": round(lb / 1e3, 3),
                    "demand": f"Mr = {mr / 1e6:.1f} kN·m, Cd = {cd:g}, ho = {ho:.0f} mm",
                    "Pbr": round(row.strength * mr * cd / ho / 1e3, 2),
                    "betaBr": round(row.stiffness * mr * cd / (phi * lb * ho) / 1e3, 3),
                    "note": "Sec 10.19.3.1(b) Eqs 6.10.291-292",
                }
            )
    return out


def torsional_bracing(
    mr: float,
    span: float,
    braces: int,
    cb: float,
    iy: float,
    ho: float,
    tw: float,
    e: float = 200_000.0,
    ts: float = 0.0,
    bs: float = 0.0,
    lb: float | None = None,
) -> dict[str, float] | None:
    """Nodal torsional bracing of a beam (Sec 10.19.3.2(a)): the brace moment Mbr = 0.024 Mr L
    / (n Cb Lb) (Eq 6.10.293) and the cross-frame or diaphragm stiffness βTb = βT / (1 - βT /
    βsec) (Eq 6.10.294), βT = 2.4 L Mr² / (φ n E Iy Cb²) (Eq 6.10.295), βsec = 3.3 E / ho
    (1.5 ho tw³ / 12 + ts bs³ / 12) (Eq 6.10.296); [N·mm, mm, N·mm/rad]. ``lb``: the unbraced
    length (default L / (n + 1)). ``betaTb`` is None when βsec <= βT: torsional bracing is not
    effective (inadequate web distortional stiffness). None when the pack has no bracing data."""
    table = _bracing_table()
    if table is None:
        return None
    lb = lb or span / (braces + 1)
    mbr = table.torsionalMoment * mr * span / (braces * cb * lb)
    beta_t = table.torsionalStiffness * span * mr**2 / (table.phi * braces * e * iy * cb**2)
    beta_sec = table.distortional * e / ho * (1.5 * ho * tw**3 / 12 + ts * bs**3 / 12)
    beta_tb = beta_t / (1 - beta_t / beta_sec) if beta_sec > beta_t else None
    return {"Mbr": mbr, "betaT": beta_t, "betaSec": beta_sec, "betaTb": beta_tb}


def brace_slenderness_check(
    shape: ShapeProperties, lengths: MemberLengths
) -> dict[str, Any] | None:
    """L/r of a brace member against the limit of stability bracing (Sec 10.19.4), as a flag
    (whether the brace is a stability brace is not known here)."""
    table = _bracing_table()
    if table is None:
        return None
    r = shape.rz if shape.family == "angle" else min(shape.rx, shape.ry)
    lr = lengths.length * 1e3 / r
    worst = _Worst()
    worst.offer(
        lr / table.slenderness,
        lr,
        table.slenderness,
        None,
        f"L/r with r = {r:.1f} mm; applies when the member is a stability brace of a column or "
        "beam (unless a second-order analysis justifies more)",
        "Sec 10.19.4",
    )
    return _check("Slenderness L/r (stability bracing)", worst, "", 1.0, flag=True)


def _b31_notes(
    shape: ShapeProperties,
    stations: Sequence[Stations],
    checks: list[dict[str, Any]],
    options: SteelOptions,
) -> list[str]:
    """The member's notes of B31: torsion the pack in force does not cover, the shear the
    lacing of a built-up member is designed for."""
    from saengine.design.steel.built_up import BuiltUp, lacing_shear
    from saengine.design.steel.torsion import has_torsion, members_data

    out = []
    if members_data() is None and any(has_torsion(st.T) for st in stations):
        out.append("torsion: not covered by the code pack in force (not checked)")
    built = BuiltUp.of(options.built_up)
    if built is not None and built.lacing in ("single", "double"):
        comp = next((c for c in checks if c["name"] == "Compression: buckling"), None)
        if comp is not None:
            v = lacing_shear(comp["capacity"] * 1e3)
            out.append(
                f"built-up member: the lacing is designed for a shear of {v / 1e3:.1f} kN normal "
                "to the member"
            )
    return out


def is_steel_member(material: Any) -> bool:
    """Whether a member of ``material`` is designed here (structural steel with fy)."""
    category = getattr(
        getattr(material, "category", None), "value", getattr(material, "category", None)
    )
    return category == "steel" and getattr(material, "steel", None) is not None


def design_steel_member(
    member_id: str,
    kind: str,
    type_id: str,
    object_type: Any,
    material: Any,
    pieces: Sequence[Any],
    combinations: Sequence[str],
    turned: bool = False,
    project: dict[str, Any] | None = None,
    options: SteelOptions | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The design report entry of one steel beam, column or brace (``kind``): ``{id, kind,
    type, members, checks, utilisation, ok, section, lengths}``. ``pieces``: its analysis
    elements with their combined forces (:func:`saengine.design.check._demands`), ``project``:
    the OpenSees Studio model they come from (for the bracing; without it the member is braced
    at its ends only). Raises :class:`SteelDesignError` when it cannot be checked."""
    options = SteelOptions.of(options)
    if not pieces:
        raise SteelDesignError("not in the analysis results")
    try:
        shape = shape_properties(object_type.profile, options.erw)
    except ValueError as error:
        raise SteelDesignError(str(error)) from error
    steel = Steel.of(material)
    if project is not None:
        lengths = member_lengths(project, pieces, turned, options.lengths)
    else:
        s, _ = positions(pieces, 2)
        lengths = MemberLengths.simple(float(s[-1] - s[0]), k=options.lengths.k).overwritten(
            options.lengths
        )
    stations = member_stations(pieces, combinations, turned)
    checks = check_member(shape, steel, stations, lengths, kind, options)
    if kind == "brace":
        slender = brace_slenderness_check(shape, lengths)
        if slender is not None:
            checks.append(slender)
    bracing = bracing_requirements(shape, stations, lengths, kind)
    extra = _b31_notes(shape, stations, checks, options)
    for note in (*shape.notes, *steel.notes):
        for c in checks:
            if c["name"].startswith(("Tension", "Compression")):
                c["note"] = f"{c['note']}; {note}" if c["note"] else note
    strength = [c for c in checks if not c["flag"]]
    elements = cl.compression_elements(shape, steel.fy, steel.e)
    return {
        "id": member_id,
        "kind": kind,
        "type": type_id,
        "members": [p.id for p in pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "section": {
            "family": shape.family,
            "label": shape.label,
            "area": round(shape.area, 1),
            "class": cl.section_class(elements),
            "elements": [el.describe() for el in elements],
            "massPerMetre": _mass_per_metre(object_type.profile, material),
            "notes": [
                *shape.notes,
                *steel.notes,
                *(
                    f"stability bracing ({b['what']}, {b['type']}, {b['note']}): each brace "
                    f"needs {b['Pbr']:g} kN and {b['betaBr']:g} kN/mm ({b['demand']}, "
                    f"Lb = {b['Lb']:g} m)"
                    for b in bracing
                ),
                *extra,
            ],
        },
        "lengths": slenderness_note(lengths),
        "bracing": bracing,
    }


def __getattr__(name: str) -> list[str]:
    # The method text names the clauses of the pack in force: built when it is read.
    if name == "METHOD":
        return _method()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
