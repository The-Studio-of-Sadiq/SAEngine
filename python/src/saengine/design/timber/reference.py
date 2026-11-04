"""Timber members and joints by reference design values and adjustment factors: the
``referenceDesign`` method of the code pack's ``timber`` table (alpha 9 C3b; with the
aci318-asce7-22 pack the NDS 2018 for wood construction).

The member's reference design values (Fb, Ft, Fv, Fc⊥, Fc, E, Emin) are the pack's
``reference.species`` row of its species combination, grade and size class (sawn dimension
lumber, beams and stringers, posts and timbers, or a glued laminated timber stress class). Each
is multiplied by the adjustment factors that apply to it (the pack's numbers):

- the load duration factor CD of each combination (ASD format: the shortest duration load in
  it governs; dead loads, the material's live load duration, roof live, snow, wind and
  earthquake by the pack's ``duration``) or, in the LRFD format, the format conversion KF, the
  resistance factor φ and the time effect factor λ of the combination;
- the wet service factor CM (the location "wet" or "outside"; dimension lumber with low Fb or
  Fc exempt), the temperature factor Ct (the material's service temperature), the incising
  factor Ci (incised sawn lumber);
- the size factor CF (dimension lumber by depth and thickness; timbers deeper than the pack's
  depth), the flat use factor Cfu (bending about the weak axis of dimension lumber), the
  repetitive member factor Cr (the member type's option), the volume factor CV of glulam (not
  with CL: the lesser governs);
- the beam stability factor CL (le from the unbraced length lu by the pack's general rule, RB
  = √(le d / b²), FbE = 1.20 Emin' / RB²) and the column stability factor CP (FcE = 0.822
  Emin' / (le/d)², c by the product);
- the bearing area factor Cb of a short bearing.

Checks per station and combination: bending about both axes, shear (3V/(2bd), the loads within
d of a supported end left out), tension, compression with CP, combined bending and axial
compression (fc/Fc')² + fb1/(Fb1' (1 - fc/FcE1)) + fb2/(Fb2' [1 - fc/FcE2 - (fb1/FbE)²]) <= 1
and combined bending and tension (ft/Ft' + fb/Fb* <= 1, (fb - ft)/Fb** <= 1), bearing, the
slenderness le/d and RB limits; the deflection with the creep factor (the pack's
``deflection``). Joints: bolts and nails by the yield limit equations of dowel-type fasteners
(modes Im, Is, II, IIIm, IIIs, IV; double shear Im, Is, IIIs, IV), Fe by the specific gravity
and the angle to the grain (Hankinson), adjusted by CD (or KF φz λ), CM, Ct, the group action
factor Cg and the geometry factor CΔ.

Sections: rectangular (sawn or glulam). Units: N, mm, MPa (the pack's values are converted from
its ``units``); the yield limit equations are evaluated in inches and pounds, as the pack's
constants are written.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.design.ductile_members import _row
from saengine.design.timber.members import (
    Section,
    TimberDesignError,
    _flag,
    _support_shear,
    _table,
    clause,
    code_name,
)

KEYS = ("Fb", "Ft", "Fv", "Fcp", "Fc", "E", "Emin")
#: The values CD (or λ) applies to.
TIME_KEYS = ("Fb", "Ft", "Fv", "Fc")
IN = 25.4  # mm per inch
LBF = 4.4482216  # N per pound-force
#: Axial forces up to this [N] are taken as none (no axial and combined rows).
AXIAL_NOISE = 1.0


def active() -> bool:
    """Whether the pack in force designs timber by reference design values."""
    try:
        table = _table()
    except Exception:  # noqa: BLE001 - no pack machinery
        return False
    return getattr(table, "method", "permissibleStress") == "referenceDesign" and (
        getattr(table, "reference", None) is not None
    )


def _ref() -> Any:
    return _table().reference


def design_format() -> str:
    """ "ASD" or "LRFD" (the pack's ``reference.format``, overridable per project)."""
    return str(_ref().format)


def combination_set() -> str:
    """The combinations the members are checked under: "strength" (LRFD) or "allowable"."""
    return "strength" if active() and design_format() == "LRFD" else "allowable"


# ─────────────────────────────────────── values ───────────────────────────────────────


def find_species(name: str | None) -> tuple[str, Any, bool]:
    """``(id, species, defaulted)`` of the pack's reference species by id or name (case
    insensitive); the pack's default species when ``name`` is None or not a reference species
    (``defaulted`` True)."""
    ref = _ref()
    table = ref.species
    if name:
        key = name.strip().lower()
        for sid, sp in table.items():
            if key in (sid.lower(), sp.name.lower()):
                return sid, sp, False
    sid = ref.defaultSpecies
    if sid not in table:
        raise TimberDesignError(f"the code pack's default species '{sid}' is not in its table")
    return sid, table[sid], True


def size_class(section: Section, product: str) -> str:
    """The size class of a section: glulam, else dimension lumber, beams and stringers or posts
    and timbers by its thickness and depth (the pack's ``sizeClasses``)."""
    if product == "glulam":
        return "glulam"
    c = _ref().sizeClasses
    thin, deep = min(section.b, section.d), max(section.b, section.d)
    if thin <= float(c.dimensionMax) + 1e-9:
        return "dimension"
    return "beamsStringers" if deep - thin > float(c.beamsExcess) else "postsTimbers"


def size_factors(grade: str, size: str, section: Section) -> dict[str, float]:
    """CF of Fb (edgewise, by the depth), Ft and Fc: dimension lumber by the pack's rows (by the
    wide face and the thickness), timbers Fb by (depth/d)^(1/x) when deeper; else 1."""
    ref = _ref()
    out = {"Fb": 1.0, "Ft": 1.0, "Fc": 1.0}
    deep, thin = max(section.b, section.d), min(section.b, section.d)
    if size == "dimension":
        group = ref.sizeFactorGroups.get(grade, "default")
        rows = ref.sizeFactors.get(group) or ref.sizeFactors["default"]
        row = next((r for r in rows if r.depthMax is None or deep <= r.depthMax + 1e-9), None)
        if row is None:
            raise TimberDesignError(
                f"grade {grade} {deep:.0f} mm deep: the code pack gives no size factor (a "
                "wider member takes the next lower grade's values)"
            )
        thick = 0 if thin <= float(ref.sizeClasses.thinMax) + 1e-9 else 1
        out = {"Fb": float(row.Fb[thick]), "Ft": float(row.Ft), "Fc": float(row.Fc)}
    elif size in ("beamsStringers", "postsTimbers"):
        c = ref.sizeClasses
        if section.d > float(c.timberDepth):
            out["Fb"] = (float(c.timberDepth) / section.d) ** (1.0 / float(c.timberExponent))
    return out


def flat_use_factor(section: Section, size: str) -> float:
    """Cfu of dimension lumber bent about its weak axis (the wide face loaded), else 1."""
    if size != "dimension":
        return 1.0
    ref = _ref()
    wide, thin = max(section.b, section.d), min(section.b, section.d)
    thick = 0 if thin <= float(ref.sizeClasses.thinMax) + 1e-9 else 1
    row = next((r for r in ref.flatUse if r.widthMax is None or wide <= r.widthMax + 1e-9), None)
    return float(row.factor[thick]) if row is not None else 1.0


def volume_factor(section: Section, length: float) -> float:
    """CV of glulam: (L0/L)^(1/x) (d0/d)^(1/x) (b0/b)^(1/x) <= 1 (length the member's [mm])."""
    v = _ref().volume
    x = 1.0 / float(v.exponent)
    value = (
        (float(v.length) / max(length, 1.0)) ** x
        * (float(v.depth) / section.d) ** x
        * (float(v.width) / section.b) ** x
    )
    return min(value, 1.0)


def temperature_factors(temperature: float | None, wet: bool) -> dict[str, float]:
    """Ct by value at the service temperature [°C] (None: normal, every factor 1)."""
    if temperature is None:
        return dict.fromkeys(KEYS, 1.0)
    rows = sorted(_ref().temperature, key=lambda r: float(r.tMax))
    row = next((r for r in rows if temperature <= float(r.tMax) + 1e-9), None)
    if row is None:
        raise TimberDesignError(
            f"service temperature {temperature:g} °C is above the code pack's temperature "
            f"factors (up to {float(rows[-1].tMax):g} °C)"
        )
    found = row.wet if wet else row.dry
    return {k: float(found.get(k, 1.0)) for k in KEYS}


@dataclass(frozen=True)
class Reference:
    """A timber material's reference design values [MPa] and the factors that do not change
    with the combination (``factors[key]``: the product of CM, Ct, Ci, CF and Cr for that
    value; ``flat``: Cfu of the weak axis; ``cv`` the glulam volume factor)."""

    species: str
    name: str
    grade: str
    size: str
    product: str
    G: float
    values: dict[str, float]
    factors: dict[str, float]
    named: dict[str, dict[str, float]]
    fb_negative: float | None = None
    fby: float | None = None
    flat: float = 1.0
    cv: float = 1.0
    wet: bool = False
    live_duration: str = "continuous"
    notes: tuple[str, ...] = ()
    repetitive: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def of(cls, material: Any, section: Section, length: float, options: Any = None) -> Reference:
        props = getattr(material, "timber", None)
        if props is None:
            raise TimberDesignError(f"'{getattr(material, 'id', '?')}' is not a timber material")
        if section.shape != "rectangle":
            raise TimberDesignError(
                "the reference design value method designs rectangular sawn or glued laminated "
                f"sections, not '{section.shape}'"
            )
        ref = _ref()
        notes: list[str] = []
        sid, sp, defaulted = find_species(getattr(props, "species", None))
        if defaulted:
            notes.append(
                f"species: {sp.name}, the code pack's default "
                + (
                    f"('{props.species}' is not one of its reference species)"
                    if getattr(props, "species", None)
                    else "(the material names none)"
                )
            )
        grade = getattr(props, "referenceGrade", None) or ref.defaultGrade
        if grade not in sp.grades:
            fallback = ref.defaultGrade if ref.defaultGrade in sp.grades else next(iter(sp.grades))
            notes.append(f"grade {grade} is not a grade of {sp.name}: {fallback} taken")
            grade = fallback
        size = size_class(section, sp.product)
        row = sp.grades[grade].get(size)
        if row is None:
            raise TimberDesignError(
                f"{sp.name} {grade}: the code pack gives no reference values for the size class "
                f"'{size}' ({section.b:g} x {section.d:g} mm)"
            )
        k = float(ref.toMPa)
        values = {key: float(getattr(row, key)) * k for key in KEYS}
        location = getattr(props, "location", "inside")
        wet = location in ("wet", "outside")
        named: dict[str, dict[str, float]] = {}
        # CM (wet service), with the dimension lumber exemptions of Fb and Fc.
        cf = size_factors(grade, size, section) if sp.product == "sawn" else {}
        if wet:
            ws = ref.wetService.get(size)
            if ws is None:
                raise TimberDesignError(f"the code pack gives no wet service factors for {size}")
            cm = {key: float(ws.factors.get(key, 1.0)) for key in KEYS}
            if ws.fbExempt is not None and float(row.Fb) * cf.get("Fb", 1.0) <= ws.fbExempt:
                cm["Fb"] = 1.0
            if ws.fcExempt is not None and float(row.Fc) * cf.get("Fc", 1.0) <= ws.fcExempt:
                cm["Fc"] = 1.0
            named["CM"] = cm
        ct = temperature_factors(getattr(props, "temperature", None), wet)
        if any(abs(v - 1.0) > 1e-9 for v in ct.values()):
            named["Ct"] = ct
        if getattr(props, "incised", False) and sp.product == "sawn":
            named["Ci"] = {key: float(ref.incising.get(key, 1.0)) for key in KEYS}
        if cf and any(abs(v - 1.0) > 1e-9 for v in cf.values()):
            named["CF"] = dict(cf)
        repetitive = bool(getattr(options, "repetitive", False)) if options is not None else False
        if repetitive and size == "dimension":
            named["Cr"] = {"Fb": float(ref.repetitive)}
        elif repetitive:
            notes.append(f"repetitive member factor: applies to dimension lumber only ({size})")
        factors = dict.fromkeys(KEYS, 1.0)
        for group in named.values():
            for key, value in group.items():
                factors[key] *= value
        return cls(
            sid,
            sp.name,
            grade,
            size,
            sp.product,
            float(sp.G),
            values,
            factors,
            named,
            float(row.FbNegative) * k if row.FbNegative is not None else None,
            float(row.Fby) * k if row.Fby is not None else None,
            flat_use_factor(section, size),
            volume_factor(section, length) if sp.product == "glulam" else 1.0,
            wet,
            getattr(props, "liveLoadDuration", "continuous"),
            tuple(notes),
            repetitive,
        )

    def adjusted(self, key: str, time: float = 1.0, lrfd: bool = False) -> float:
        """The value ``key`` times its fixed factors, the time factor (CD or λ, of Fb, Ft, Fv,
        Fc only) and, in the LRFD format, KF and φ."""
        value = self.values[key] * self.factors[key]
        if key in TIME_KEYS:
            value *= time
        if lrfd:
            f = _ref().lrfd
            value *= float(f.KF.get(key, 1.0)) * float(f.phi.get(key, 1.0))
        return value

    def weak_bending(self, time: float = 1.0, lrfd: bool = False) -> float:
        """Fb' about the weak axis: the weak-axis reference value (glulam Fby, else Fb) times
        the fixed factors of Fb without Cr, the flat use factor Cfu (dimension lumber), the
        time factor and (LRFD) KF φ; no CL or CV."""
        base = self.fby if self.fby is not None else self.values["Fb"]
        cr = self.named.get("Cr", {}).get("Fb", 1.0)
        value = base * self.factors["Fb"] / cr * self.flat * time
        if lrfd:
            f = _ref().lrfd
            value *= float(f.KF.get("Fb", 1.0)) * float(f.phi.get("Fb", 1.0))
        return value

    def label(self) -> str:
        return f"{self.name} {self.grade} ({self.size})"


# ─────────────────────────────────────── time factors ───────────────────────────────────────


def _case_duration(case: str, live: str) -> float | None:
    """CD of one load case by the longest prefix of its name in the pack's ``duration``."""
    ref = _ref()
    best = None
    for prefix, value in ref.duration.items():
        if case.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, value)
    if best is None:
        return None
    value = best[1]
    if value == "live":
        return float(ref.liveDuration.get(live, 1.0))
    return float(value)


def duration_factor(cases: dict[str, float], live: str = "continuous") -> float:
    """CD of a combination ``{case: factor}``: the largest of its loads' (the shortest duration
    load governs); a case the pack does not name counts 1.0."""
    found = [_case_duration(c, live) for c, v in cases.items() if v]
    known = [v for v in found if v is not None]
    if not known:
        return 1.0
    if any(v is None for v in found):
        known.append(1.0)
    return max(known)


def time_effect(cases: dict[str, float], live: str = "continuous") -> float:
    """λ of a strength combination: 1.0 with wind or earthquake; the live load's λ (by the
    material's live load duration) where the live load governs (factor at least 1.5); 0.8 with
    roof live, snow or rain governing or a lesser live load; 0.6 for dead load alone."""
    t = _ref().lrfd.timeEffect
    present = {c: v for c, v in cases.items() if v}
    if any(c[:1] in ("W", "E") for c in present):
        return float(t["lateral"])
    live_cases = [v for c, v in present.items() if c == "L" or c.startswith("LP")]
    if live_cases and max(abs(v) for v in live_cases) >= 1.5:
        return float(t.get(live, t["continuous"]))
    if any(c in ("Lr", "S", "R") for c in present) or live_cases:
        return float(t["roof"])
    return float(t["dead"])


def combination_factors(
    factors: Sequence[dict[str, float]], names: Sequence[str], live: str, lrfd: bool
) -> dict[str, float]:
    """The time factor per combination name: λ (LRFD) or CD (ASD)."""
    pick = time_effect if lrfd else duration_factor
    return {n: pick(f, live) for n, f in zip(names, factors, strict=True)}


# ─────────────────────────────────────── stability ───────────────────────────────────────


def effective_length(lu: float, d: float) -> float:
    """le of a bending member from its unbraced length (the pack's rule for any load)."""
    b = _ref().beamStability
    ratio = lu / d
    if ratio < float(b.shortRatio):
        return float(b.shortFactor) * lu
    if ratio <= float(b.longRatio):
        return float(b.midFactor) * lu + float(b.midDepth) * d
    return float(b.longFactor) * lu


def beam_stability(fb_star: float, emin: float, rb: float) -> tuple[float, float]:
    """(CL, FbE) at the slenderness RB."""
    b = _ref().beamStability
    if rb <= 0:
        return 1.0, math.inf
    fbe = float(b.fbe) * emin / rb**2
    alpha = fbe / fb_star
    first = (1 + alpha) / float(b.a)
    return first - math.sqrt(max(first**2 - alpha / float(b.b), 0.0)), fbe


def column_stability(fc_star: float, emin: float, slenderness: float, product: str) -> float:
    """CP at le/d = ``slenderness``."""
    c = _ref().columnStability
    if slenderness <= 0:
        return 1.0
    fce = float(c.fce) * emin / slenderness**2
    cc = float(c.c.get(product, c.c.get("sawn", 0.8)))
    alpha = fce / fc_star
    first = (1 + alpha) / (2 * cc)
    return first - math.sqrt(max(first**2 - alpha / cc, 0.0))


def bearing_area_factor(length: float) -> float:
    """Cb of a bearing ``length`` [mm] long (1 at or above the pack's length)."""
    a, below = _ref().bearingArea
    return (length + float(a)) / length if length < float(below) else 1.0


# ─────────────────────────────────────── the member ───────────────────────────────────────


def check_member(
    section: Section,
    ref: Reference,
    stations: Sequence[Any],
    length: float,
    time: dict[str, float],
    kind: str = "beam",
    options: Any = None,
    lrfd: bool = False,
) -> list[dict[str, Any]]:
    """The checks of a member (see the module notes); ``time`` the CD (ASD) or λ (LRFD) per
    combination name; ``options`` the type's :class:`TimberMember` data."""
    rs = _ref()
    beam = kind == "beam"
    b, d = section.b, section.d
    area = b * d
    zx, zy = b * d * d / 6, d * b * b / 6
    free_end = getattr(options, "freeEnd", "none") if options is not None else "none"
    supported = (free_end != "start", free_end != "end")
    bearing = getattr(options, "bearingLength", None) if options is not None else None
    lu = float(getattr(options, "restraintSpacing", None) or length) if options else length
    emin = ref.adjusted("Emin", lrfd=lrfd)
    tag_format = "λ" if lrfd else "CD"
    # Beam stability (bending about the strong axis of a section deeper than wide).
    if d > b:
        le = effective_length(lu, d)
        rb = math.sqrt(le * d / (b * b))
    else:
        le, rb = 0.0, 0.0
    # Column stability: le = the member length (pinned ends) about both axes.
    slender_x, slender_y = length / d, length / b
    slenderness = max(slender_x, slender_y)
    sign_change = False
    for st in stations:
        mx = np.asarray(st.Mx, dtype=float)
        if len(mx) and float(mx.min()) < 0 < float(mx.max()):
            sign_change = True
    rows: dict[str, dict[str, Any]] = {}

    def offer(key: str, row: dict[str, Any]) -> None:
        if key not in rows or row["utilisation"] > rows[key]["utilisation"]:
            rows[key] = row

    depth_m = d / 1000.0
    for st in stations:
        name = st.combination
        k = float(time.get(name, 1.0))
        tag = f"; {tag_format} = {k:.2f}"
        fb_star = ref.adjusted("Fb", k, lrfd)
        cl, fbe = beam_stability(fb_star, emin, rb) if rb > 0 else (1.0, math.inf)
        stab = min(cl, ref.cv) if ref.product == "glulam" else cl
        fby = ref.weak_bending(k, lrfd)
        ft = ref.adjusted("Ft", k, lrfd)
        fv = ref.adjusted("Fv", k, lrfd)
        fc_star = ref.adjusted("Fc", k, lrfd)
        cp = column_stability(fc_star, emin, slenderness, ref.product)
        fc = fc_star * cp
        fce1 = float(rs.columnStability.fce) * emin / slender_x**2 if slender_x > 0 else math.inf
        fce2 = float(rs.columnStability.fce) * emin / slender_y**2 if slender_y > 0 else math.inf
        if beam:
            v = _support_shear(st, depth_m, supported)
            offer(
                "v",
                _row(
                    f"Shear fv = 3V/(2bd), loads within d of the supports left out "
                    f"({clause('shear')}; {clause('shearSupport')})",
                    1.5 * v / area,
                    fv,
                    "MPa",
                    name,
                    f"V = {v / 1e3:.1f} kN; Fv' = {fv:.2f} MPa{tag}",
                ),
            )
            if bearing:
                cb = bearing_area_factor(float(bearing))
                fcp = ref.adjusted("Fcp", 1.0, lrfd) * cb
                for end, i in ((0, 0), (1, -1)):
                    if not supported[end] or not len(st.Vy):
                        continue
                    r = abs(float(np.asarray(st.Vy)[i]))
                    offer(
                        f"b{end}",
                        _row(
                            f"Bearing perpendicular to the grain at the "
                            f"{'start' if end == 0 else 'end'} support ({clause('bearing')})",
                            r / (b * float(bearing)),
                            fcp,
                            "MPa",
                            name,
                            f"R = {r / 1e3:.1f} kN on {float(bearing):g} mm, Cb = {cb:.3f}",
                        ),
                    )
        for i in range(len(st.s)):
            where = st.where[i] if i < len(st.where) else ""
            p = float(st.P[i])
            mx_signed = float(st.Mx[i])
            mx, my = abs(mx_signed), abs(float(st.My[i]))
            fbx_ref = fb_star
            if ref.fb_negative is not None and (mx_signed > 0 or free_end != "none"):
                # Glulam: the top (compression zone) in tension takes Fbx-.
                fbx_ref = fb_star * ref.fb_negative / ref.values["Fb"]
            fbx = fbx_ref * stab
            sx, sy = mx / zx, my / zy
            offer(
                "bx",
                _row(
                    f"Bending fb = M/S about the strong axis ({clause('bending')}; "
                    f"{clause('beamStability')})",
                    sx,
                    fbx,
                    "MPa",
                    name,
                    f"{where}; Fb' = {fbx:.2f} MPa, CL = {cl:.3f}"
                    + (f", CV = {ref.cv:.3f}" if ref.product == "glulam" else "")
                    + (f", RB = {rb:.1f}" if rb > 0 else "")
                    + tag,
                ),
            )
            if my > 0:
                offer(
                    "by",
                    _row(
                        f"Bending fb = M/S about the weak axis ({clause('bending')}; "
                        f"{clause('flatUse')})",
                        sy,
                        fby,
                        "MPa",
                        name,
                        f"{where}; Fb' = {fby:.2f} MPa, Cfu = {ref.flat:g}{tag}",
                    ),
                )
            if not beam:
                vv = max(abs(float(st.Vy[i])), abs(float(st.Vx[i])))
                offer(
                    "v",
                    _row(
                        f"Shear fv = 3V/(2bd) ({clause('shear')})",
                        1.5 * vv / area,
                        fv,
                        "MPa",
                        name,
                        f"{where}{tag}",
                    ),
                )
            fa = abs(p) / area
            if abs(p) <= AXIAL_NOISE:
                continue  # no axial force: bending and shear only
            if p >= 0:
                offer(
                    "c",
                    _row(
                        f"Compression parallel to the grain fc ≤ Fc' ({clause('column')})",
                        fa,
                        fc,
                        "MPa",
                        name,
                        f"{where}; le/d = {slenderness:.1f}, CP = {cp:.3f}{tag}",
                    ),
                )
                if fa >= fce1 or fa >= fce2 or (rb > 0 and sx >= fbe):
                    combined = math.inf
                else:
                    combined = (fa / fc) ** 2 if fc > 0 else math.inf
                    combined += sx / (fbx * (1 - fa / fce1))
                    if sy > 0:
                        term = 1 - fa / fce2 - ((sx / fbe) ** 2 if math.isfinite(fbe) else 0.0)
                        combined += sy / (fby * term) if term > 0 else math.inf
                offer(
                    "m",
                    _row(
                        "Combined bending and axial compression "
                        f"(fc/Fc')² + fb1/(Fb1' (1 - fc/FcE1)) + fb2/(Fb2' [1 - fc/FcE2 - "
                        f"(fb1/FbE)²]) ({clause('combinedCompression')})",
                        combined,
                        1.0,
                        "",
                        name,
                        f"{where}{tag}",
                        utilisation=combined,
                    ),
                )
            else:
                offer(
                    "t",
                    _row(
                        f"Tension parallel to the grain ft ≤ Ft' ({clause('tension')})",
                        fa,
                        ft,
                        "MPa",
                        name,
                        f"{where}{tag}",
                    ),
                )
                fbx_star = fbx_ref * (ref.cv if ref.product == "glulam" else 1.0)
                first = fa / ft + sx / fbx_star + (sy / fby if sy > 0 else 0.0)
                second = (sx - fa) / (fbx_ref * cl) if sx > fa else 0.0
                combined = max(first, second)
                offer(
                    "m",
                    _row(
                        "Combined bending and axial tension ft/Ft' + fb/Fb* ≤ 1, (fb - ft)/Fb** "
                        f"≤ 1 ({clause('combinedTension')})",
                        combined,
                        1.0,
                        "",
                        name,
                        f"{where}{tag}",
                        utilisation=combined,
                    ),
                )
    order = ("bx", "by", "v", "b0", "b1", "t", "c", "m")
    out = [rows[k] for k in order if k in rows]
    limit = float(rs.columnStability.maxSlenderness)
    if kind in ("column", "brace") or "c" in rows:
        out.append(
            _row(
                f"Slenderness le/d ≤ {limit:g} ({clause('column')})",
                slenderness,
                limit,
                "",
                note=f"le = {length:.0f} mm (the member length), d = {min(b, d):.0f} mm",
            )
        )
    if rb > 0:
        rb_max = float(rs.beamStability.rbMax)
        out.append(
            _row(
                f"Beam slenderness RB ≤ {rb_max:g} ({clause('beamStability')})",
                rb,
                rb_max,
                "",
                note=f"lu = {lu:.0f} mm, le = {le:.0f} mm",
            )
        )
    if sign_change and ref.fb_negative is not None:
        out.append(
            _flag(
                _row(
                    f"Glulam layup ({clause('referenceValues')})",
                    0.0,
                    1.0,
                    "",
                    note="the moment changes sign: Fbx- taken where the top is in tension",
                )
            )
        )
    for note in ref.notes:
        out.append(
            _flag(_row(f"Reference values ({clause('referenceValues')})", 0.0, 1.0, "", note=note))
        )
    return out


# ─────────────────────────────────────── joints ───────────────────────────────────────


def dowel_bearing(g: float, d_mm: float, theta: float) -> float:
    """Fe [psi] of wood at ``theta`` [rad] to the grain for a dowel ``d_mm`` [mm] (Hankinson
    between the parallel and perpendicular values; small dowels one value)."""
    w = _ref().dowels
    if d_mm < float(w.smallDiameter):
        return float(w.small) * g ** float(w.smallExponent)
    d_in = d_mm / IN
    par = float(w.parallel) * g
    per = float(w.perpendicular) * g ** float(w.perpendicularExponent) / math.sqrt(d_in)
    return par * per / (par * math.sin(theta) ** 2 + per * math.cos(theta) ** 2)


def reduction_terms(d_mm: float, theta: float) -> dict[str, float]:
    """Rd by mode: Kθ × the pack's terms (D >= smallDiameter), else KD for every mode."""
    w = _ref().dowels
    if d_mm < float(w.smallDiameter):
        limit, low, a = w.rdSmall
        kd = float(low) if d_mm <= float(limit) else float(a) * d_mm / IN + 0.5
        return {"I": kd, "II": kd, "III": kd}
    k_theta = 1 + float(w.kTheta) * math.degrees(theta) / 90
    return {mode: float(v) * k_theta for mode, v in w.rdLarge.items()}


def yield_limit(
    d_mm: float,
    lm_mm: float,
    ls_mm: float,
    fem: float,
    fes: float,
    fyb: float,
    theta: float,
    double: bool,
) -> tuple[float, str]:
    """(Z [N], governing mode) of one dowel: single shear (modes Im, Is, II, IIIm, IIIs, IV)
    or double shear (Im, Is, IIIs, IV), lm the main and ls the (each) side member's bearing
    length [mm], Fe and Fyb [psi]."""
    dd, lm, ls = d_mm / IN, lm_mm / IN, ls_mm / IN
    rd = reduction_terms(d_mm, theta)
    re = fem / fes
    rt = lm / ls
    k3 = -1 + math.sqrt(2 * (1 + re) / re + 2 * fyb * (2 + re) * dd**2 / (3 * fem * ls**2))
    modes: dict[str, float] = {}
    if double:
        modes["Im"] = dd * lm * fem / rd["I"]
        modes["Is"] = 2 * dd * ls * fes / rd["I"]
        modes["IIIs"] = 2 * k3 * dd * ls * fem / ((2 + re) * rd["III"])
        modes["IV"] = 2 * dd**2 / rd["III"] * math.sqrt(2 * fem * fyb / (3 * (1 + re)))
    else:
        k1 = (math.sqrt(re + 2 * re**2 * (1 + rt + rt**2) + rt**2 * re**3) - re * (1 + rt)) / (
            1 + re
        )
        k2 = -1 + math.sqrt(2 * (1 + re) + 2 * fyb * (1 + 2 * re) * dd**2 / (3 * fem * lm**2))
        modes["Im"] = dd * lm * fem / rd["I"]
        modes["Is"] = dd * ls * fes / rd["I"]
        modes["II"] = k1 * dd * ls * fes / rd["II"]
        modes["IIIm"] = k2 * dd * lm * fem / ((1 + 2 * re) * rd["III"])
        modes["IIIs"] = k3 * dd * ls * fem / ((2 + re) * rd["III"])
        modes["IV"] = dd**2 / rd["III"] * math.sqrt(2 * fem * fyb / (3 * (1 + re)))
    mode = min(modes, key=lambda m: modes[m])
    return modes[mode] * LBF, mode


def group_action(
    n: int, spacing_mm: float, d_mm: float, e_mpa: float, am_mm2: float, as_mm2: float
) -> float:
    """Cg of a row of ``n`` dowels at ``spacing`` (wood main and side members of moduli E):
    the pack's load/slip modulus γ = groupGamma D^1.5, REA, u, m."""
    if n <= 1 or spacing_mm <= 0:
        return 1.0
    w = _ref().dowels
    psi = e_mpa / float(_ref().toMPa)
    em_am = psi * am_mm2 / IN**2
    es_as = psi * as_mm2 / IN**2
    gamma = float(w.groupGamma) * (d_mm / IN) ** 1.5
    s = spacing_mm / IN
    rea = min(es_as / em_am, em_am / es_as)
    u = 1 + gamma * s / 2 * (1 / em_am + 1 / es_as)
    m = u - math.sqrt(u * u - 1)
    mn, m2n = m**n, m ** (2 * n)
    cg = m * (1 - m2n) / (n * ((1 + rea * mn) * (1 + m) - 1 + m2n)) * (1 + rea) / (1 - m)
    return min(max(cg, 0.0), 1.0)


def geometry_factor(joint: Any, d_mm: float, tension: bool) -> tuple[float, str]:
    """CΔ of the end distance and the spacing in a row (the least), and the rule that failed
    ("" when both are at least the least values)."""
    w = _ref().dowels
    which = (
        ("tensionHardwood" if getattr(joint, "hardwood", False) else "tensionSoftwood")
        if tension
        else "compression"
    )
    end = float(getattr(joint, "endDistance", 0.0)) / d_mm
    full, least = float(w.endFull[which]), float(w.endMin[which])
    fail = ""
    if end < least - 1e-9:
        fail = f"end distance {end:.1f} D below the least {least:g} D ({which})"
    c_end = 1.0 if end >= full else max(end / full, 0.5)
    spacing = float(getattr(joint, "spacing", 0.0)) / d_mm
    c_sp = 1.0
    if int(getattr(joint, "count", 1)) > int(getattr(joint, "rows", 1)):
        if spacing < float(w.spacingMin) - 1e-9:
            fail = fail or f"spacing {spacing:.1f} D below the least {float(w.spacingMin):g} D"
        c_sp = 1.0 if spacing >= float(w.spacingFull) else spacing / float(w.spacingFull)
    return min(c_end, c_sp), fail


def check_joint(
    joint: Any,
    section: Section,
    ref: Reference,
    stations: Sequence[Any],
    time: dict[str, float],
    lrfd: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The member's end joints by the yield limit equations (bolts and nails); split rings and
    disc-dowels are not covered by this method (flagged)."""
    from saengine.design.timber.connections import end_forces

    w = _ref().dowels
    kind = getattr(joint, "type", None)
    forces = end_forces(stations)
    tension = any(p < 0 for _, _, p, _ in forces)
    summary: dict[str, Any] = {"type": kind, "count": getattr(joint, "count", 0)}
    if kind not in ("bolts", "nails"):
        return [
            _flag(
                _row(
                    f"Joint: {kind} ({clause('dowels')})",
                    0.0,
                    1.0,
                    "kN",
                    note="not covered: the reference design value method designs bolted and "
                    "nailed joints (dowel-type fasteners)",
                )
            )
        ], summary
    if kind == "bolts":
        d = float(joint.diameter)
        double = joint.shear == "double"
        lm = float(joint.mainThickness or section.b)
        fyb = float(w.boltFyb)
        rows_n = max(int(joint.rows), 1)
        per_row = max(math.ceil(joint.count / rows_n), 1)
        title = f"Joint: {joint.count} bolts {d:g} mm per end, {joint.shear} shear"
    else:
        d = float(joint.size)
        double = True
        lm = float(section.b)
        fyb = next((float(f) for dmax, f in w.nailFyb if d <= float(dmax) + 1e-9), None)
        if fyb is None:
            fyb = float(w.nailFyb[-1][1])
        rows_n, per_row = 1, 1
        title = f"Joint: {joint.count} nails {d:g} mm per end, double shear"
    ls = float(joint.sideThickness)
    # CM, Ct of connections: the pack's wet service of fasteners, Ct of Fb.
    cm = float(w.wetService) if ref.wet else 1.0
    ct = ref.named.get("Ct", {}).get("Fb", 1.0)
    e = ref.adjusted("E")
    am = section.b * section.d
    as_ = (2 if double else 1) * ls * section.d
    cg = group_action(per_row, float(getattr(joint, "spacing", 0.0)), d, e, am, as_)
    if kind == "nails":
        cg = 1.0
    c_delta, fail = geometry_factor(joint, d, tension) if kind == "bolts" else (1.0, "")
    best = (0.0, 1.0, "", "", 0.0, "")
    worst = -1.0
    for name, end, p, v in forces:
        f = math.hypot(p, v)
        if f <= 0:
            continue
        theta = math.atan2(v, abs(p))
        fe = dowel_bearing(ref.G, d, theta)
        z, mode = yield_limit(d, lm, ls, fe, fe, fyb, theta, double)
        t = float(time.get(name, 1.0))
        factor = t * cm * ct * cg * c_delta
        if lrfd:
            factor *= float(_ref().lrfd.connectionKF) * float(_ref().lrfd.connectionPhi)
        cap = joint.count * z * factor
        u = f / cap if cap > 0 else math.inf
        if u > worst:
            worst, best = u, (f, cap, name, end, theta, mode)
    demand, cap, name, end, theta, mode = best
    note = (
        f"{end}: θ = {math.degrees(theta):.0f}° to the grain, mode {mode}; Cg = {cg:.3f}, "
        f"CΔ = {c_delta:.2f}"
        + (f", CM = {cm:g}" if cm != 1 else "")
        + (" (KF φz λ)" if lrfd else " (CD)")
    )
    rows = [
        _row(
            f"{title} ({clause('dowels')}; {clause('group')})",
            demand / 1e3,
            cap / 1e3,
            "kN",
            name or None,
            note,
        )
    ]
    if fail:
        rows.append(
            _row(
                f"Joint geometry ({clause('geometry')})",
                1.0,
                0.0,
                "",
                note=fail,
                utilisation=99.0,
            )
        )
    summary.update({"diameter": d, "mode": mode, "Cg": round(cg, 3), "CDelta": round(c_delta, 3)})
    return rows, summary


# ─────────────────────────────────────── the report ───────────────────────────────────────


def method() -> list[str]:
    """The design report's method paragraph of timber members by this method."""
    fmt = design_format()
    how = (
        "the strength combinations, with the format conversion factor KF, the resistance factor "
        f"φ and the time effect factor λ of each combination ({clause('lrfd')}; "
        f"{clause('timeEffect')})"
        if fmt == "LRFD"
        else "the allowable stress combinations, with the load duration factor CD of each "
        f"combination ({clause('duration')})"
    )
    return [
        (
            "Timber members: reference design values adjusted by their factors "
            f"({clause('chapter')}; {clause('referenceValues')}), {fmt} format under {how}. Wet "
            f"service CM ({clause('wetService')}), temperature Ct ({clause('temperature')}), "
            f"incising Ci ({clause('incising')}), size CF ({clause('sizeFactor')}), flat use Cfu "
            f"({clause('flatUse')}), repetitive member Cr ({clause('repetitive')}), glulam volume "
            f"CV ({clause('volume')}), beam stability CL ({clause('beamStability')}), column "
            f"stability CP ({clause('column')}), bearing area Cb ({clause('bearing')}); bending, "
            f"shear with the loads within d of the supports left out ({clause('shear')}), tension, "
            f"compression, combined stresses ({clause('combinedCompression')}; "
            f"{clause('combinedTension')}) and the deflection with creep ({clause('deflection')}). "
            "Rectangular sawn and glued laminated sections; le is the member length (pinned ends), "
            "lu the type's restraint spacing. Joints: bolts and nails by the yield limit equations "
            f"of dowel-type fasteners ({clause('dowels')}), Cg and CΔ ({clause('group')}; "
            f"{clause('geometry')})."
        )
    ]


def design_entry(
    member_id: str,
    kind: str,
    object_type: Any,
    material: Any,
    section: Section,
    stations: Sequence[Any],
    length: float,
    factors: Sequence[dict[str, float]] | None,
    names: Sequence[str],
    profiles: dict[str, Sequence[tuple[float, float]]] | None,
    e_analysis: float | None,
    pieces: Sequence[Any],
) -> dict[str, Any]:
    """The design report entry of one member by this method (the keys of
    :func:`saengine.design.timber.members.design_timber_member`)."""
    from saengine.design.timber.members import deflection_row

    options = getattr(object_type, "timber", None)
    ref = Reference.of(material, section, length, options)
    lrfd = design_format() == "LRFD"
    time = combination_factors(factors or [{} for _ in names], names, ref.live_duration, lrfd)
    checks = check_member(section, ref, stations, length, time, kind, options, lrfd)
    if kind == "beam" and profiles:
        e = ref.adjusted("E")
        row = deflection_row(profiles, (e_analysis / e) if e_analysis else 1.0, options)
        if row is not None:
            checks.append(row)
    joint = getattr(object_type, "timberJoint", None)
    joint_out = None
    if joint is not None:
        rows, joint_out = check_joint(joint, section, ref, stations, time, lrfd)
        checks += rows
    strength = [c for c in checks if not c["flag"]]
    factors_out = {
        f"{name} ({key})": round(value, 3)
        for name, group in ref.named.items()
        for key, value in group.items()
    }
    entry = {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "members": [p.id for p in pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "material": material.id,
        "timber": {
            "label": f"{section.b:g} x {section.d:g} timber ({section.shape})",
            "group": None,
            "species": ref.label(),
            "location": getattr(material.timber, "location", "inside"),
            "E": round(ref.adjusted("E"), 0),
            "stresses": {
                "Fb": round(ref.values["Fb"], 2),
                "Ft": round(ref.values["Ft"], 2),
                "Fv": round(ref.values["Fv"], 2),
                "Fc": round(ref.values["Fc"], 2),
                "Fcn": round(ref.values["Fcp"], 2),
            },
            "factors": factors_out,
            "length": round(length, 0),
            "code": code_name(),
            "basis": clause("chapter"),
            "method": "referenceDesign",
            "format": "LRFD" if lrfd else "ASD",
        },
    }
    if joint_out is not None:
        entry["timber"]["joint"] = joint_out
    return entry


__all__ = [
    "Reference",
    "active",
    "beam_stability",
    "bearing_area_factor",
    "check_joint",
    "check_member",
    "column_stability",
    "combination_factors",
    "combination_set",
    "design_entry",
    "design_format",
    "dowel_bearing",
    "duration_factor",
    "effective_length",
    "find_species",
    "geometry_factor",
    "group_action",
    "method",
    "size_class",
    "size_factors",
    "time_effect",
    "volume_factor",
    "yield_limit",
]
