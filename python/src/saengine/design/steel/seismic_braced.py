"""Capacity design of steel braced frames of the seismic load resisting system: special and
ordinary concentrically braced frames, eccentrically braced frames and buckling-restrained
braced frames.

Every number is the code pack's ``steelSeismic`` table (BNBC 2020: Part 6 Sec 10.20.13-10.20.16,
Eqs 6.10.303-6.10.306); every clause reference comes from the table's ``sources``. The table's
``bracedSystems`` maps the structural systems of Project Settings to the braced kind (``scbf``,
``ocbf``, ``ebf``, ``brbf``; ``spsw`` walls are :mod:`saengine.design.steel.seismic_walls`).
The moment frames, Ry and Rt, the seismically compact limits and the column strength under the
amplified seismic load are :mod:`saengine.design.steel.seismic` (B35), reused here.

What is built:

- **When the provisions apply** (:func:`braced_provisions`): R taken above the trigger for a
  system the table maps to a braced kind.
- **Concentric braces** (:func:`concentric_brace_checks`): KL/r ≤ c √(E/Fy) (all braces, or
  those in K, V and inverted-V of ordinary frames) with the slender-brace exception, seismically
  compact braces (and columns), the net section at the expected yield strength, the stitches of
  built-up braces, the bracing connections re-checked at Ry Fy Ag in tension and 1.1 Ry Pn in
  compression (the flexural strength 1.1 Ry Mp as a flag), the protected zone.
- **The lateral force distribution** (:func:`tension_share_checks`): along each line of
  bracing, the braces in tension resist between the table's shares of the horizontal force.
- **V and inverted-V bracing** (:func:`chevron_demand`): the beam with the braces giving no
  gravity support and the unbalanced force of the tension braces at Ry Fy Ag and the
  compression braces at 0.3 Pn (or the adjusted strengths of buckling-restrained braces).
- **K-type bracing**: refused where the kind does not permit it.
- **Links of eccentrically braced frames** (:func:`link_strength`, :func:`link_checks`): the
  shear strength with the axial force (Eqs 6.10.303-6.10.304), the length limit (Eqs
  6.10.305-6.10.306), the link rotation angle, the stiffeners and the lateral bracing they need;
  the diagonal brace (1.25 Ry Vn), the beam outside the link (1.1 Ry Vn, its strength × Ry) and
  the columns (1.1 Ry Vn of the links above).
- **Buckling-restrained braces** (:func:`restrained_strengths`, :func:`restrained_checks`): the
  core's strength, β and ω of the tests, the connections at 1.1 × the adjusted compression and
  the beams and columns at the adjusted strengths.
- **Column splices** of SCBF and BRBF (half the lesser flexural strength, ΣMpc / H).

The model is read from the building's geometry: a beam line (collinear beams at one level)
with the columns on it gives the panels; braces meeting a beam inside a panel make a V (two
braces at one point) or an eccentric brace (the link between the brace point and the next brace
point or the column). Where the code takes the largest force the system can deliver as a cap,
SAEngine takes the capacity-design force (conservative). Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.design.steel import seismic as S
from saengine.design.steel.seismic import PREFIX, _check, _rule, cite

#: The braced kinds this module designs.
KINDS = ("scbf", "ocbf", "ebf", "brbf")
#: Geometric tolerance [mm] for points meeting a beam line or a column (SAEngine practice).
TOL = 50.0


# ───────────────────────────────────── when they apply ─────────────────────────────────────


@dataclass
class BracedProvisions:
    """Whether the braced frame or plate wall provisions apply, and to which kinds."""

    applies: bool
    kinds: list[str] = field(default_factory=list)
    systems: list[str] = field(default_factory=list)
    r: float | None = None
    reason: str = ""


def braced_provisions(settings: Any, table: Any | None = None) -> BracedProvisions:
    """The braced kinds of the systems in use (``bracedSystems``) with R taken above
    ``trigger.rAbove`` (Sec 10.1.1.2, 10.20.1)."""
    t = table if table is not None else S.seismic_table()
    if t is None or not t.bracedSystems:
        return BracedProvisions(False, reason=f"{S.pack_name()} has no braced frame provisions")
    from saengine.codes import context as code_context

    rows = code_context.table("seismic").systems
    kinds: list[str] = []
    systems: list[str] = []
    below: list[str] = []
    largest: float | None = None
    for system, override in S._systems_in_use(settings):
        kind = t.bracedSystems.get(system)
        if kind is None:
            continue
        row = rows.get(system)
        r = float(override if override is not None else (row.R if row is not None else 0.0))
        if r <= t.trigger.rAbove:
            below.append(system)
            continue
        if kind not in kinds:
            kinds.append(kind)
        systems.append(system)
        largest = r if largest is None else max(largest, r)
    if not kinds:
        reason = (
            f"R of {', '.join(below)} is not above {t.trigger.rAbove:g}: the braced frame "
            f"provisions are not required ({cite(t, 'trigger')})"
            if below
            else "no steel braced frame or plate wall system is selected"
        )
        return BracedProvisions(False, systems=below, reason=reason)
    return BracedProvisions(True, kinds, systems, largest)


# ───────────────────────────────────── concentric braces ─────────────────────────────────────


def brace_slenderness_checks(
    klr: float, fy: float, e: float, kind: str, chevron: bool, table: Any | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """KL/r of a concentric brace (Sec 10.20.13.2.1, 10.20.14.2): ``(checks, slender)`` with
    ``slender`` True when the brace uses the exception up to ``slendernessMax`` (the columns
    must then take Ry times the braces' nominal strengths)."""
    t = S._table(table)
    c = t.concentric[kind]
    if c.slenderness is None or (c.slendernessChevronOnly and not chevron):
        return [], False
    key = "scbfSlenderness" if kind == "scbf" else "ocbfBrace"
    limit = c.slenderness * math.sqrt(e / fy)
    if klr <= limit or c.slendernessMax is None:
        return [
            _check(
                "brace slenderness",
                klr,
                limit,
                "",
                cite(t, key),
                f"KL/r ≤ {c.slenderness:g} √(E/Fy) = {limit:.1f}"
                + (" (a brace of a K, V or inverted-V)" if c.slendernessChevronOnly else ""),
            )
        ], False
    return [
        _check(
            "brace slenderness (slender brace exception)",
            klr,
            c.slendernessMax,
            "",
            cite(t, key),
            f"KL/r {klr:.1f} > {c.slenderness:g} √(E/Fy) = {limit:.1f}: permitted up to "
            f"{c.slendernessMax:g} where the columns take Ry times the nominal strengths of the "
            "connecting braces (checked on the columns)",
        )
    ], True


def brace_compact_checks(
    shape: Any,
    fy: float,
    e: float,
    kind: str,
    member: str,
    filled: bool = False,
    ca: float = 0.0,
    table: Any | None = None,
) -> list[dict[str, Any]]:
    """Seismically compact braces, columns or beams of a braced kind (Sec 10.20.8.2.2, Table
    6.10.18) as the kind asks (``compactMembers``); a concrete-filled HSS brace of an ordinary
    frame is exempt. ``ca``: Pu / (φb Py) of a column's web."""
    t = S._table(table)
    if kind in ("scbf", "ocbf"):
        rules = t.concentric[kind]
        if member not in rules.compactMembers or (filled and rules.filledHssExempt):
            return []
        clause = cite(t, "scbfCompact" if kind == "scbf" else "ocbfBrace")
    elif kind == "ebf":
        clause = cite(t, "linkScope" if member == "link" else "ebfColumns")
    elif kind == "brbf":
        if member == "brace":
            return []
        clause = cite(t, "brbfMembers")
    else:
        clause = cite(t, "compact")
    return [
        _check(
            f"{name} width-thickness (seismically compact)",
            ratio,
            limit,
            "",
            clause,
            f"λ = {ratio:.1f} ≤ λps = {limit:.1f}" + (f", Ca = {ca:.3f}" if ca else ""),
        )
        for name, ratio, limit in S.seismic_compact_limits(shape, fy, e, member, kind, ca, t)
    ]


@dataclass
class BraceForces:
    """The capacity-design forces of a brace [N, N·mm]."""

    tension: float  # expected (or adjusted) tension
    compression: float  # expected (or adjusted) compression for the connections
    beam_compression: float  # the compression a V-braced beam is designed with
    connection_tension: float
    connection_compression: float
    connection_moment: float | None = None
    what: str = ""


def concentric_forces(
    ry: float, fy: float, area: float, pn: float, mp: float, kind: str, table: Any | None = None
) -> BraceForces:
    """Sec 10.20.13.3 / 10.20.14.4: the connections take Ry Fy Ag in tension and (special
    frames) 1.1 Ry Pn in compression and 1.1 Ry Mp in flexure; V-braced beams take Ry Fy Ag and
    0.3 Pn (Sec 10.20.13.4.1, 10.20.14.3)."""
    c = S._table(table).concentric[kind]
    tension = ry * fy * area
    comp = (c.connectionCompression or 0.0) * ry * pn
    return BraceForces(
        tension,
        ry * pn,
        c.postBuckling * pn,
        tension,
        comp,
        (c.connectionFlexure * ry * mp) if c.connectionFlexure else None,
        f"Ry Fy Ag = {tension / 1e3:.0f} kN"
        + (f", {c.connectionCompression:g} Ry Pn = {comp / 1e3:.0f} kN" if comp else ""),
    )


def net_section_check(
    ry: float, fy: float, area: float, phi_fu_ae: float, kind: str, table: Any | None = None
) -> dict[str, Any]:
    """Sec 10.20.13.2.2: where the effective net area is below the gross, the brace's net
    section fracture strength at least the expected yield Ry Fy Ag (the system's largest force
    as the cap is not taken: conservative)."""
    t = S._table(table)
    return _check(
        "brace net section at the expected yield strength",
        ry * fy * area / 1e3,
        phi_fu_ae / 1e3,
        "kN",
        cite(t, "scbfBrace"),
        f"φ Fu Ae ≥ Ry Fy Ag = {ry:g} × {fy:g} × {area:.0f}",
    )


def stitch_check(
    spacing: float, ri: float, klr: float, shear: bool, kind: str, table: Any | None = None
) -> list[dict[str, Any]]:
    """Sec 10.20.13.2.5: the stitches of a built-up brace at most ``stitchRatio`` (or
    ``stitchRatioNoShear`` when buckling causes no shear in them) × the governing KL/r apart
    (l/r of an element between stitches)."""
    t = S._table(table)
    c = t.concentric[kind]
    if c.stitchRatio is None or ri <= 0 or spacing <= 0:
        return []
    share = c.stitchRatio if shear else (c.stitchRatioNoShear or c.stitchRatio)
    return [
        _check(
            "stitch spacing of the built-up brace",
            spacing / ri,
            share * klr,
            "",
            cite(t, "scbfStitches"),
            f"l/r between stitches ≤ {share:g} × KL/r {klr:.1f}; at least {c.stitchesMin or 1} "
            "stitches, bolted ones not in the middle quarter, their shear at least each "
            "element's tensile strength",
        )
    ]


def protected_zone(length: float, depth: float, kind: str, table: Any | None = None) -> dict:
    """The protected zone of a brace: the middle share of its length and one brace depth next
    to each connection (SCBF), or the steel core (BRBF)."""
    t = S._table(table)
    if kind == "brbf":
        return {"core": True, "clause": cite(t, "brbfProtected")}
    if kind != "scbf":
        return {}
    c = t.concentric[kind]
    return {
        "middle": round((c.protectedMiddle or 0.0) * length, 1),
        "ends": round(depth, 1),
        "clause": cite(t, "scbfProtected"),
        "note": "with the gussets and elements connecting the braces to beams and columns",
    }


@dataclass
class BraceLine:
    """The braces of one line of bracing in one storey and direction."""

    name: str
    positive: float = 0.0  # Σ Ag cos θ of the braces in tension under + direction
    negative: float = 0.0
    braces: list[str] = field(default_factory=list)


def tension_share_checks(lines: list[BraceLine], table: Any | None = None) -> list[dict]:
    """Sec 10.20.13.2.3: along each line of bracing the braces in tension resist between
    ``tensionShareMin`` and ``tensionShareMax`` of the horizontal force, for either direction
    (shares by Ag cos θ of the braces; the exception for braces strong enough in compression
    under the amplified seismic load is not taken: conservative)."""
    t = S._table(table)
    c = t.concentric["scbf"]
    if c.tensionShareMin is None or c.tensionShareMax is None:
        return []
    out = []
    for line in lines:
        total = line.positive + line.negative
        if total <= 0:
            continue
        share = line.positive / total
        worst = max(share, 1 - share)
        ok = c.tensionShareMin - 1e-9 <= min(share, 1 - share) and worst <= c.tensionShareMax + 1e-9
        check = _check(
            f"lateral force distribution, {line.name}",
            worst,
            c.tensionShareMax,
            "",
            cite(t, "scbfDistribution"),
            f"braces in tension resist {share:.0%} for one direction and {1 - share:.0%} for "
            f"the other; between {c.tensionShareMin:.0%} and {c.tensionShareMax:.0%} "
            f"({', '.join(line.braces)})",
        )
        check["ok"] = bool(ok)
        if not ok:
            check["utilisation"] = max(check["utilisation"], 1.001)
        out.append(check)
    return out


def chevron_demand(
    tensions: list[tuple[float, float]],
    compressions: list[tuple[float, float]],
    a: float,
    b: float,
) -> tuple[float, float]:
    """``(Q, Mq)``: the unbalanced vertical force at the intersection of V or inverted-V braces
    (``tensions`` and ``compressions`` as ``(force, angle to the horizontal)``) and its moment
    on the beam spanning ``a + b`` between the columns with the braces giving no support."""
    up = sum(f * math.sin(ang) for f, ang in tensions)
    down = sum(f * math.sin(ang) for f, ang in compressions)
    q = abs(up - down)
    span = a + b
    return q, (q * a * b / span if span > 0 else 0.0)


# ───────────────────────────────────── eccentric braces ─────────────────────────────────────


@dataclass
class Link:
    """An EBF link and what its checks need (mm, MPa, N)."""

    id: str
    e: float  # link length
    d: float
    tf: float
    tw: float
    bf: float
    area: float
    z: float
    fy: float
    ry: float
    pu: float = 0.0  # required axial (magnitude)
    vu: float = 0.0  # required shear
    span: float = 0.0  # bay width L
    height: float = 0.0  # storey height
    angle: float = 0.0  # the diagonal brace's angle to the horizontal [rad]
    at_column: bool = False


def link_strength(link: Link, table: Any | None = None) -> dict[str, float]:
    """Sec 10.20.15.2.2: Vp = 0.6 Fy Aw, Mp = Fy Z, Vn = min(Vp, 2 Mp / e); with Pu above
    0.15 Py the reduced Vpa = Vp √(1 - (Pr/Pc)²) and Mpa = 1.18 Mp (1 - Pr/Pc) (Eqs
    6.10.303-6.10.304) and the length limit (Eqs 6.10.305-6.10.306)."""
    k = S._table(table).eccentric
    aw = (link.d - 2 * link.tf) * link.tw
    vp = k.shearYield * link.fy * aw
    mp = link.fy * link.z
    py = link.fy * link.area
    vn = min(vp, k.flexureShear * mp / link.e) if link.e > 0 else vp
    out = {"Aw": aw, "Vp": vp, "Mp": mp, "Py": py, "Vn": vn, "axial": 0.0}
    out["ratio"] = link.e / (mp / vp) if vp > 0 else math.inf
    if py > 0 and link.pu > k.axialLimit * py:
        pr = min(link.pu / py, 1.0)
        vpa = vp * math.sqrt(max(1 - pr**2, 0.0))
        mpa = k.mpaFactor * mp * (1 - pr)
        out.update({"axial": 1.0, "Vpa": vpa, "Mpa": mpa})
        out["Vn"] = min(vpa, k.flexureShear * mpa / link.e) if link.e > 0 else vpa
        rho = link.pu / link.vu if link.vu > 0 else math.inf
        out["rho"] = rho
        if rho * aw / link.area >= k.lengthRatio:
            out["lengthMax"] = (
                (k.lengthA - k.lengthB * rho * aw / link.area) * k.shortLink * mp / vp
            )
        else:
            out["lengthMax"] = k.shortLink * mp / vp
    return out


def rotation_limit(ratio: float, table: Any | None = None) -> float:
    """Sec 10.20.15.2.3: 0.08 rad up to e = 1.6 Mp/Vp, 0.02 rad from 2.6 Mp/Vp, linear between
    (``ratio`` = e Vp / Mp)."""
    k = S._table(table).eccentric
    if ratio <= k.shortLink:
        return k.rotationShort
    if ratio >= k.longLink:
        return k.rotationLong
    f = (ratio - k.shortLink) / (k.longLink - k.shortLink)
    return k.rotationShort + f * (k.rotationLong - k.rotationShort)


def link_rotation(link: Link, drift_ratio: float) -> float:
    """The link rotation angle at the storey drift ratio Δ / h: γp = (L / e) Δ / h (the
    rigid-plastic mechanism of the bay)."""
    return link.span / link.e * drift_ratio if link.e > 0 else math.inf


def link_checks(
    link: Link,
    drift_ratio: float | None,
    table: Any | None = None,
    drift_source: str = "the design storey drift",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The checks of an EBF link and its summary: φv Vn ≥ Vu, the length limit with axial
    force, the rotation angle at the drift, the web (no doubler, no penetration), the
    stiffeners and the lateral bracing it needs (flags with the sizes)."""
    t = S._table(table)
    k = t.eccentric
    st = link_strength(link, t)
    vp, _mp = st["Vp"], st["Mp"]
    checks = [
        _check(
            "link shear",
            link.vu / 1e3,
            k.phi * st["Vn"] / 1e3,
            "kN",
            cite(t, "linkShear"),
            f"Vn = min(Vp, {k.flexureShear:g} Mp / e) = {st['Vn'] / 1e3:.0f} kN, Vp = "
            f"{vp / 1e3:.0f} kN, e = {link.e:.0f} mm"
            + (
                f"; Pu {link.pu / 1e3:.0f} kN > {k.axialLimit:g} Py: Vpa, Mpa"
                if st["axial"]
                else ""
            ),
        )
    ]
    if "lengthMax" in st:
        checks.append(
            _check(
                "link length with axial force",
                link.e,
                st["lengthMax"],
                "mm",
                cite(t, "linkShear"),
                f"ρ' = Pu / Vu = {st.get('rho', 0):.2f}",
            )
        )
    limit = rotation_limit(st["ratio"], t)
    summary = {
        "id": link.id,
        "e": round(link.e, 0),
        "eVpMp": round(st["ratio"], 3),
        "Vn": round(st["Vn"] / 1e3, 1),
        "rotationLimit": round(limit, 4),
        "atColumn": link.at_column,
    }
    if drift_ratio is not None and link.span > 0:
        gamma = link_rotation(link, drift_ratio)
        summary["rotation"] = round(gamma, 4)
        checks.append(
            _check(
                "link rotation angle",
                gamma,
                limit,
                "rad",
                cite(t, "linkRotation"),
                f"γp = (L / e) Δ / h = ({link.span:.0f} / {link.e:.0f}) × {drift_ratio:.4f} at "
                f"{drift_source} (the whole drift taken as plastic: conservative); limit by "
                f"e Vp / Mp = {st['ratio']:.2f}",
            )
        )
    checks.append(
        _rule(
            "link web single thickness",
            True,
            cite(t, "linkScope"),
            "the link web takes no doubler plate and no penetration; the link is a protected "
            "zone (only its stiffeners are welded to it)",
            flag=True,
        )
    )
    checks += link_stiffener_rows(link, st["ratio"], limit, t)
    ho = link.d - link.tf
    if ho > 0:
        pb = k.braceStrength * link.ry * link.z * link.fy / ho
        checks.append(
            _rule(
                "lateral bracing at the link ends",
                False,
                cite(t, "linkBracing"),
                f"both flanges braced at both link ends, each brace Pb = {k.braceStrength:g} Ry Z "
                f"Fy / ho = {pb / 1e3:.1f} kN, stiffness by Eq 6.10.292 with Cd = 1, Lb = e",
                flag=True,
            )
        )
    if link.at_column:
        checks.append(
            _rule(
                "link-to-column connection qualified",
                False,
                cite(t, "linkColumn"),
                f"a connection prequalified for EBF or qualified by cyclic tests, at least Vn "
                f"{st['Vn'] / 1e3:.0f} kN at the rotation {limit:g} rad; CJP welds of the link "
                "to the column are demand critical",
                flag=True,
            )
        )
    return checks, summary


def link_stiffener_rows(
    link: Link, ratio: float, rotation: float, table: Any | None = None
) -> list[dict[str, Any]]:
    """Sec 10.20.15.3: the link's end and intermediate web stiffeners as detailing flags."""
    t = S._table(table)
    k = t.eccentric
    clause = cite(t, "linkStiffeners")
    end_t = max(k.endStiffenerThickness * link.tw, k.stiffenerThicknessMin)
    rows = [
        _rule(
            "link end stiffeners",
            False,
            clause,
            f"full depth, both sides of the web at the brace ends: combined width ≥ bf - "
            f"{k.endStiffenerWidth:g} tw = {link.bf - k.endStiffenerWidth * link.tw:.0f} mm, "
            f"t ≥ {end_t:.0f} mm",
            flag=True,
        )
    ]
    parts = []
    if ratio <= k.longLink:
        f = (rotation - k.rotationLong) / (k.rotationShort - k.rotationLong)
        coef = k.spacingLong + f * (k.spacingShort - k.spacingLong)
        spacing = coef * link.tw - link.d / k.spacingDepthDivisor
        parts.append(
            f"spaced at most {spacing:.0f} mm ({coef:.1f} tw - d / {k.spacingDepthDivisor:g})"
        )
    if k.shortLink < ratio < k.flexuralLink:
        parts.append(
            f"at {k.flangeDistance:g} bf = {k.flangeDistance * link.bf:.0f} mm from each end"
        )
    if not parts:
        return rows
    one = link.d < k.twoSidedDepth
    t_one = max(k.oneSidedThickness * link.tw, k.stiffenerThicknessMin)
    rows.append(
        _rule(
            "link intermediate stiffeners",
            False,
            clause,
            "full depth, "
            + "; ".join(parts)
            + (
                f"; one side (d < {k.twoSidedDepth:g} mm): t ≥ {t_one:.0f} mm, width ≥ "
                f"{k.oneSidedWidth * link.bf:.0f} mm"
                if one
                else "; both sides of the web"
            )
            + f"; welds to the web {k.weldWebShare:g} Ast Fy, to the flanges "
            f"{k.weldFlangeShare:g} Ast Fy",
            flag=True,
        )
    )
    return rows


def ebf_demands(link: Link, vn: float, table: Any | None = None) -> dict[str, float]:
    """Sec 10.20.15.6, 10.20.15.8: the diagonal brace's axial force at 1.25 Ry Vn, the beam
    outside the link at 1.1 Ry Vn (the link end moment Vn e / 2 and the brace's horizontal
    component) and a column's share 1.1 Ry Vn of each link above."""
    k = S._table(table).eccentric
    sin = math.sin(link.angle) if link.angle > 0 else 1.0
    tan = math.tan(link.angle) if link.angle > 0 else math.inf
    beam_v = k.beamFactor * link.ry * vn
    return {
        "brace": k.braceFactor * link.ry * vn / sin,
        "beamMoment": beam_v * link.e / 2,
        "beamAxial": beam_v / tan if math.isfinite(tan) else 0.0,
        "column": k.columnFactor * link.ry * vn,
    }


# ───────────────────────────────── buckling-restrained braces ─────────────────────────────────


def restrained_strengths(
    restrained: Any, fysc: float, ry: float, table: Any | None = None
) -> BraceForces:
    """Sec 10.20.16.2.1, 10.20.16.2.4, 10.20.16.3.1: Pysc = Fysc Asc; the adjusted strengths
    ω Ry Pysc in tension and β ω Ry Pysc in compression (Ry not applied with a coupon Fysc);
    the connections at 1.1 × the adjusted compression, in tension and compression."""
    b = S._table(table).restrained
    pysc = fysc * restrained.coreArea
    factor = 1.0 if restrained.couponFy else ry
    beta = max(restrained.beta, b.betaMin)
    tension = restrained.omega * factor * pysc
    comp = beta * restrained.omega * factor * pysc
    conn = b.connectionFactor * comp
    return BraceForces(
        tension,
        comp,
        comp,
        conn,
        conn,
        None,
        f"Pysc = {pysc / 1e3:.0f} kN, ω = {restrained.omega:g}, β = {beta:g}",
    )


def restrained_checks(
    restrained: Any, fysc: float, pu: float, table: Any | None = None
) -> list[dict[str, Any]]:
    """The steel core's design strength φ Pysc against the largest axial force, β of the tests
    at least the table's least, the restraining system and the tests (flags)."""
    t = S._table(table)
    b = t.restrained
    pysc = fysc * restrained.coreArea
    return [
        _check(
            "buckling-restrained core yielding",
            pu / 1e3,
            b.phi * pysc / 1e3,
            "kN",
            cite(t, "brbfCore"),
            f"φ Pysc = {b.phi:g} × {fysc:g} × {restrained.coreArea:.0f}, tension and "
            "compression; the core takes the whole axial force, no splices in it",
        ),
        _check(
            "compression adjustment β of the tests",
            b.betaMin,
            restrained.beta,
            "",
            cite(t, "brbfAdjusted"),
            f"β at least {b.betaMin:g}",
        ),
        _rule(
            "qualifying cyclic tests",
            False,
            cite(t, "brbfRestraint"),
            f"the restraining system holds the core to {b.testDrift:g} × the design storey "
            "drift; two qualifying cyclic tests (a subassemblage and a uniaxial or "
            f"subassemblage test) give β and ω; core plates of {b.coreToughness:g} mm or more "
            "need the notch toughness",
            flag=True,
        ),
    ]


# ───────────────────────────────────────── geometry ─────────────────────────────────────────


def _cross(a: np.ndarray, b: np.ndarray) -> float:
    """The z component of the cross product of two plan vectors."""
    return float(a[0] * b[1] - a[1] * b[0])


def _ends(element: Any) -> tuple[np.ndarray, np.ndarray] | None:
    """The 3D ends of a brace element (a member element or an inclined member) [mm]."""
    if hasattr(element, "x1"):
        return (
            np.array([element.x1, element.y1, element.z1], dtype=float),
            np.array([element.x2, element.y2, element.z2], dtype=float),
        )
    start, end = getattr(element, "start", None), getattr(element, "end", None)
    if start is not None and end is not None and len(start) == 3 and len(end) == 3:
        return np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    return None


@dataclass
class _BeamOnLine:
    id: str
    t0: float
    t1: float
    flipped: bool


@dataclass
class _Line:
    origin: np.ndarray
    u: np.ndarray
    level: float
    beams: list[_BeamOnLine] = field(default_factory=list)
    columns: list[tuple[float, str]] = field(default_factory=list)
    points: list[tuple[float, str, int]] = field(default_factory=list)  # (t, brace, end)


@dataclass
class FrameBeam:
    id: str
    start: np.ndarray  # plan [mm]
    end: np.ndarray
    elevation: float
    type: str | None = None


@dataclass
class FrameColumn:
    id: str
    position: np.ndarray  # plan [mm]
    bottom: float
    top: float
    rotation: float = 0.0
    type: str | None = None


def frame_members(
    building: Any, types: dict[str, Any] | None = None
) -> tuple[list[FrameBeam], list[FrameColumn]]:
    """The building's beams and columns: its beam and column elements, and its members in
    space (special structures, inclined members) that are horizontal or vertical and not of a
    brace type."""
    from saengine.library.bim import BeamElement, ColumnElement

    beams: list[FrameBeam] = []
    columns: list[FrameColumn] = []
    elements = list(getattr(building, "elements", []))
    elements += list(getattr(getattr(building, "additions", None), "members", []) or [])
    for e in elements:
        if isinstance(e, BeamElement):
            beams.append(
                FrameBeam(
                    e.id,
                    np.asarray(e.start, dtype=float),
                    np.asarray(e.end, dtype=float),
                    float(e.elevation),
                    e.type,
                )
            )
            continue
        if isinstance(e, ColumnElement):
            columns.append(
                FrameColumn(
                    e.id,
                    np.asarray(e.position, dtype=float),
                    float(e.bottom),
                    float(e.top),
                    float(e.rotation or 0.0),
                    e.type,
                )
            )
            continue
        ends = _ends(e)
        if ends is None:
            continue
        kind = getattr((types or {}).get(getattr(e, "type", None)), "kind", None)
        if kind == "brace":
            continue
        p0, p1 = ends
        if abs(p1[2] - p0[2]) <= TOL and np.linalg.norm(p1[:2] - p0[:2]) > TOL:
            beams.append(FrameBeam(e.id, p0[:2], p1[:2], float(max(p0[2], p1[2])), e.type))
        elif np.linalg.norm(p1[:2] - p0[:2]) <= TOL and abs(p1[2] - p0[2]) > TOL:
            columns.append(
                FrameColumn(
                    e.id,
                    p0[:2],
                    float(min(p0[2], p1[2])),
                    float(max(p0[2], p1[2])),
                    float(getattr(e, "rotation", 0.0) or 0.0),
                    e.type,
                )
            )
    return beams, columns


def beam_lines(
    building: Any,
    braces: dict[str, tuple[np.ndarray, np.ndarray]],
    types: dict[str, Any] | None = None,
) -> list[_Line]:
    """The beam lines of the building (collinear beams at one level), with the columns on them
    and the brace ends meeting them."""
    beams, columns = frame_members(building, types)
    lines: list[_Line] = []
    for beam in beams:
        a, b = beam.start, beam.end
        span = float(np.linalg.norm(b - a))
        if span <= 0:
            continue
        u = (b - a) / span
        level = float(beam.elevation)
        found = None
        for line in lines:
            if abs(line.level - level) > TOL or abs(_cross(line.u, u)) > 1e-3:
                continue
            off = a - line.origin
            if abs(_cross(line.u, off)) <= TOL:
                found = line
                break
        if found is None:
            found = _Line(a, u, level)
            lines.append(found)
        ta = float((a - found.origin) @ found.u)
        tb = float((b - found.origin) @ found.u)
        found.beams.append(_BeamOnLine(beam.id, min(ta, tb), max(ta, tb), tb < ta))
    for line in lines:
        lo = min(b.t0 for b in line.beams) - TOL
        hi = max(b.t1 for b in line.beams) + TOL
        for c in columns:
            p = np.asarray(c.position, dtype=float)
            off = p - line.origin
            if abs(_cross(line.u, off)) > TOL:
                continue
            if not (c.bottom - TOL <= line.level <= c.top + TOL):
                continue
            tc = float(off @ line.u)
            if lo <= tc <= hi and all(abs(tc - x) > TOL for x, _ in line.columns):
                line.columns.append((tc, c.id))
        line.columns.sort()
        for bid, (p0, p1) in braces.items():
            for k, p in enumerate((p0, p1)):
                if abs(p[2] - line.level) > _level_tolerance():
                    continue
                off = p[:2] - line.origin
                if abs(_cross(line.u, off)) > TOL:
                    continue
                tp = float(off @ line.u)
                if lo <= tp <= hi:
                    line.points.append((tp, bid, k))
        line.points.sort()
    return lines


def _level_tolerance() -> float:
    """Vertical tolerance of a brace end meeting a beam: the beam's level is its top; the
    analysis node may sit at the top or the centreline (SAEngine practice)."""
    return 600.0


def _clusters(points: list[tuple[float, str, int]]) -> list[list[tuple[float, str, int]]]:
    groups: list[list[tuple[float, str, int]]] = []
    for p in points:
        if groups and p[0] - groups[-1][-1][0] <= TOL:
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


@dataclass
class Panel:
    """A bay of a beam line between two columns with the brace points inside it."""

    line: _Line
    ta: float
    tb: float
    left: str
    right: str
    clusters: list[list[tuple[float, str, int]]]


def panels(line: _Line) -> list[Panel]:
    out = []
    for (ta, ca), (tb, cb) in zip(line.columns, line.columns[1:], strict=False):
        inside = [p for p in line.points if ta + TOL < p[0] < tb - TOL]
        if inside:
            out.append(Panel(line, ta, tb, ca, cb, _clusters(inside)))
    return out


def _angle(p0: np.ndarray, p1: np.ndarray) -> float:
    d = p1 - p0
    return math.atan2(abs(float(d[2])), float(np.hypot(d[0], d[1])))


def _beam_at(line: _Line, t: float) -> _BeamOnLine | None:
    return next((b for b in line.beams if b.t0 - 1e-6 <= t <= b.t1 + 1e-6), None)


def _local(beam: _BeamOnLine, t: float) -> float:
    """Distance along the beam element from its start [mm] of the line position ``t``."""
    return (beam.t1 - t) if beam.flipped else (t - beam.t0)


# ───────────────────────────────────────── integrator glue ─────────────────────────────────────────


def _rescore(entry: dict[str, Any]) -> None:
    strength = [c for c in entry["checks"] if not c["flag"]]
    entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
    entry["ok"] = all(c["ok"] for c in strength)


def _capacity(entry: dict[str, Any], prefix: str) -> float:
    found = next((c for c in entry["checks"] if c["name"].startswith(prefix)), None)
    return float(found["capacity"]) * 1e3 if found else 0.0


def _moment_capacity(entry: dict[str, Any]) -> float:
    """φMn about the major axis [N·mm] of a member's design entry."""
    found = next((c for c in entry["checks"] if c["name"].startswith("Flexure about x")), None)
    return float(found["capacity"]) * 1e6 if found else 0.0


def storey_drift(
    drifts: list[dict[str, Any]] | None,
    level: float,
    height: float,
    axis: str,
    allowable: float | None,
) -> tuple[float | None, str]:
    """``(Δ / h, what)`` of the storey under the beam ``level`` [mm]: the response spectrum's
    design storey drift along ``axis``, else the allowable storey drift."""
    for row in drifts or []:
        top = float(row.get("top", 0.0)) * 1e3
        if row.get("direction") == axis and abs(top - level) <= _level_tolerance():
            return float(row["ratio"]), "the design storey drift of the response spectrum"
    return allowable, (
        "the allowable storey drift (no response spectrum drift: SAEngine practice, conservative)"
    )


def _demand(entry: dict[str, Any], prefix: str) -> float | None:
    found = next((c for c in entry["checks"] if c["name"].startswith(prefix)), None)
    return float(found["demand"]) if found else None


def _steel_phi(name: str) -> float:
    from saengine.codes import context as code_context

    return float(code_context.table("steel").phi[name])


def _drift_ratio(settings: Any) -> float | None:
    try:
        from saengine.fem import seismic_design

        return float(seismic_design.settings_drift_limit(settings)["ratio"])
    except Exception:  # noqa: BLE001 - no drift limit for these settings: no rotation check
        return None


def apply(
    project: dict[str, Any],
    building: Any,
    types: dict[str, Any],
    mats: dict[str, Any],
    members: list[Any],
    combinations: list[str],
    earthquake: list[int],
    settings: Any,
    drifts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Adds the braced frame checks to the steel members' report entries
    (:class:`saengine.design.steel.seismic.SteelMember`, braces included) and returns the
    summary ``{"applies", "kinds", "systems", "R", "braces", "links", "chevrons", "checks",
    "notes", "clauses"}`` (``checks``: the project's own, the lines of bracing). ``drifts``: the
    response spectrum's design storey drifts (``{"direction", "bottom", "top", "ratio"}``, m) for
    the link rotation; without them the allowable storey drift is taken."""
    from saengine.design import overwrites as design_overwrites
    from saengine.design import steel_connections as sc
    from saengine.design.steel import members as sm
    from saengine.design.steel.properties import shape_properties
    from saengine.design.steel_proposal import SteelMaterial
    from saengine.library.steel_sections import section_of_profile

    t = S.seismic_table()
    prov = braced_provisions(settings, t)
    out: dict[str, Any] = {
        "applies": prov.applies,
        "kinds": prov.kinds,
        "systems": prov.systems,
        "R": prov.r,
        "braces": {},
        "links": [],
        "chevrons": [],
        "checks": [],
        "notes": [prov.reason] if prov.reason else [],
        "clauses": dict(t.sources) if t is not None else {},
    }
    kinds = [k for k in prov.kinds if k in KINDS]
    if not prov.applies or t is None or not kinds:
        return out
    concentric = next((k for k in ("scbf", "ocbf") if k in kinds), None)
    ebf = "ebf" in kinds
    brbf = "brbf" in kinds
    omega = {c for c, name in enumerate(combinations) if name.startswith("Ω0: ")}
    plain = [c for c in range(len(combinations)) if c not in omega]
    gravity_idx = [c for c in plain if c not in set(earthquake)] or plain

    by_id = {m.id: m for m in members}
    info: dict[str, dict[str, Any]] = {}
    for m in members:
        try:
            shape = shape_properties(m.object.profile)
            steel = sm.Steel.of(m.material)
        except (ValueError, sm.SteelDesignError) as error:
            out["notes"].append(f"{m.id}: not checked for the braced frame provisions: {error}")
            continue
        ry, _rt, _what = S.expected_ratios(m.material, shape.family, t)
        stations = sm.member_stations(m.pieces, combinations, m.turned)
        info[m.id] = {"shape": shape, "steel": steel, "ry": ry, "stations": stations}

    def lateral(m: Any) -> bool:
        return S._role(m) != "gravity"

    braces = [m for m in members if m.kind == "brace" and m.id in info and lateral(m)]
    geometry = {m.id: g for m in braces if (g := _ends(m.element)) is not None}
    extra: dict[str, list[dict[str, Any]]] = {}  # checks per member id, added at the end

    def add(mid: str, rows: list[dict[str, Any]]) -> None:
        extra.setdefault(mid, []).extend(rows)

    # The beam lines, panels, chevrons and links.
    try:
        lines = beam_lines(building, geometry, types) if building is not None else []
    except Exception as error:  # noqa: BLE001 - a model the line search cannot read
        lines = []
        out["notes"].append(f"the beam lines could not be found: {error}")
    chevron_braces: set[str] = set()
    link_of_brace: dict[str, Link] = {}
    links: list[tuple[Link, Panel, _BeamOnLine]] = []
    chevrons: list[tuple[Panel, list[tuple[float, str, int]]]] = []
    for line in lines:
        for panel in panels(line):
            single = len(panel.clusters) == 1
            v_shape = single and len({p[1] for p in panel.clusters[0]}) >= 2
            if ebf and not v_shape:
                if not single:
                    pairs = [
                        (panel.clusters[i], panel.clusters[i + 1], False)
                        for i in range(len(panel.clusters) - 1)
                    ]
                else:
                    c0 = panel.clusters[0]
                    tp = c0[0][0]
                    near_left = tp - panel.ta <= panel.tb - tp
                    edge = [(panel.ta if near_left else panel.tb, "", -1)]
                    pairs = [(edge, c0, True) if near_left else (c0, edge, True)]
                for lo, hi, at_column in pairs:
                    a, b = lo[-1][0], hi[0][0]
                    mid = (a + b) / 2
                    beam = _beam_at(line, mid)
                    if beam is None or beam.id not in info or beam.id not in by_id:
                        continue
                    shape = info[beam.id]["shape"]
                    if shape.family != "I":
                        out["notes"].append(f"{beam.id}: an EBF link must be an I-shape")
                        continue
                    face = 0.0
                    if at_column:
                        col = panel.left if lo[0][2] == -1 else panel.right
                        if col in info:
                            face = info[col]["shape"].dims.get("d", 0.0) / 2
                    e_len = max(b - a - face, 1.0)
                    bracing = [p for p in (lo + hi) if p[2] >= 0]
                    angle = _angle(*geometry[bracing[0][1]]) if bracing else 0.0
                    height = (
                        abs(float(geometry[bracing[0][1]][1][2] - geometry[bracing[0][1]][0][2]))
                        if bracing
                        else 0.0
                    )
                    d = shape.dims
                    link = Link(
                        beam.id,
                        e_len,
                        d["d"],
                        d["tf"],
                        d["tw"],
                        d["bf"],
                        shape.area,
                        shape.zx,
                        info[beam.id]["steel"].fy,
                        info[beam.id]["ry"],
                        span=panel.tb - panel.ta,
                        height=height,
                        angle=angle,
                        at_column=at_column,
                    )
                    s0, s1 = sorted((_local(beam, a), _local(beam, b)))
                    st = info[beam.id]["stations"]
                    vu = pu = 0.0
                    for c in plain:
                        if c >= len(st) or not len(st[c].s):
                            continue
                        s = np.asarray(st[c].s) * 1e3
                        inside = (s >= s0 - TOL) & (s <= s1 + TOL)
                        if not inside.any():
                            inside = np.ones_like(s, dtype=bool)
                        vu = max(vu, float(np.max(np.abs(np.asarray(st[c].Vy)[inside]))))
                        pu = max(pu, float(np.max(np.abs(np.asarray(st[c].P)[inside]))))
                    link.vu, link.pu = vu, pu
                    links.append((link, panel, beam))
                    for p in bracing:
                        link_of_brace[p[1]] = link
                continue
            for cluster in panel.clusters:
                ids = {p[1] for p in cluster}
                if len(ids) >= 2:
                    chevrons.append((panel, cluster))
                    chevron_braces |= ids
                else:
                    beam = _beam_at(line, cluster[0][0])
                    out["notes"].append(
                        f"{next(iter(ids))}: meets beam {beam.id if beam else '?'} away from a "
                        "joint in a concentrically braced frame (not checked as a V)"
                    )

    # K-type bracing: a brace end on a column between the beam levels.
    columns = frame_members(building, types)[1] if building is not None else []
    column_at = {c.id: c for c in columns}
    levels_at: dict[str, list[float]] = {}
    for line in lines:
        for _tc, cid in line.columns:
            levels_at.setdefault(cid, []).append(line.level)
    k_braces: set[str] = set()
    for bid, (p0, p1) in geometry.items():
        for p in (p0, p1):
            for c in columns:
                if np.linalg.norm(p[:2] - np.asarray(c.position, dtype=float)) > TOL:
                    continue
                if not (c.bottom + _level_tolerance() < p[2] < c.top - _level_tolerance()):
                    continue
                if any(abs(p[2] - lv) <= _level_tolerance() for lv in levels_at.get(c.id, [])):
                    continue
                k_braces.add(bid)

    # Braces.
    capacity_forces: dict[str, BraceForces] = {}
    slender: set[str] = set()
    for m in braces:
        i = info[m.id]
        shape, steel, ry = i["shape"], i["steel"], i["ry"]
        p0, p1 = geometry.get(m.id, (None, None))
        length = float(np.linalg.norm(p1 - p0)) if p0 is not None else 0.0
        rows: list[dict[str, Any]] = []
        restrained = getattr(m.object, "restrained", None)
        pu = max(
            (
                float(np.max(np.abs(i["stations"][c].P)))
                for c in plain
                if c < len(i["stations"]) and len(i["stations"][c].s)
            ),
            default=0.0,
        )
        summary: dict[str, Any] = {"Ry": ry}
        if restrained is not None:
            if not brbf:
                out["notes"].append(
                    f"{m.id}: a buckling-restrained brace in a system that is not a BRBF"
                )
            kind = "brbf"
            ry = S.expected_ratios(m.material, "plate", t)[0]  # the core is a plate
            summary["Ry"] = ry
            forces = restrained_strengths(restrained, steel.fy, ry, t)
            rows += restrained_checks(restrained, steel.fy, pu, t)
            summary["kind"] = "brbf"
        elif m.id in link_of_brace:
            kind = "ebf"
            link = link_of_brace[m.id]
            vn = link_strength(link, t)["Vn"]
            demand = ebf_demands(link, vn, t)
            phi_pn = _capacity(m.entry, "Compression: buckling")
            rows.append(
                _check(
                    "diagonal brace at the link's strength",
                    demand["brace"] / 1e3,
                    phi_pn / 1e3,
                    "kN",
                    cite(t, "ebfBrace"),
                    f"{t.eccentric.braceFactor:g} Ry Vn / sin θ of link {link.id} (Vn "
                    f"{vn / 1e3:.0f} kN); the brace's share of the link end moment is not "
                    "taken (pinned brace)",
                )
            )
            rows += _compact_rows(shape, steel, "brace", t)
            forces = BraceForces(
                demand["brace"],
                demand["brace"],
                demand["brace"],
                demand["brace"],
                demand["brace"],
                None,
                f"{t.eccentric.braceFactor:g} Ry Vn = {demand['brace'] / 1e3:.0f} kN",
            )
            summary.update({"kind": "ebf", "link": link.id})
        else:
            kind = concentric or ("scbf" if ebf else None)
            if kind is None:
                continue
            if ebf:
                out["notes"].append(
                    f"{m.id}: not at a link; checked as a special concentric brace (the top "
                    f"storey of an EBF above {t.eccentric.upperStoreysAbove} storeys may be a CBF)"
                )
            klr = _demand(m.entry, "Slenderness KL/r") or (
                length / max(min(shape.rx, shape.ry), 1e-9) if length else 0.0
            )
            sl_rows, is_slender = brace_slenderness_checks(
                klr, steel.fy, steel.e, kind, m.id in chevron_braces or m.id in k_braces, t
            )
            rows += sl_rows
            if is_slender:
                slender.add(m.id)
            filled = getattr(getattr(m.object, "composite", None), "form", None) == "filled"
            rows += brace_compact_checks(shape, steel.fy, steel.e, kind, "brace", filled, table=t)
            phi_c = _steel_phi("compression")
            pn = _capacity(m.entry, "Compression: buckling") / phi_c
            if pn <= 0:
                rows.append(
                    _rule(
                        "brace compression strength",
                        False,
                        cite(t, "scbfConnection"),
                        "the brace was not designed for compression (tension only): a "
                        "concentric brace's connections and beams need its Pn",
                    )
                )
            mp = steel.fy * (shape.zy or shape.zx)
            forces = concentric_forces(ry, steel.fy, shape.area, pn, mp, kind, t)
            rupture = _capacity(m.entry, "Tension: rupture")
            if rupture > 0 and kind == "scbf":
                ae = rupture / (_steel_phi("tensionRupture") * steel.fu)
                if ae < shape.area * (1 - 1e-6):
                    rows.append(net_section_check(ry, steel.fy, shape.area, rupture, kind, t))
            try:
                resolved = design_overwrites.resolve(m.element, m.object)
                if kind == "scbf" and resolved.has("builtUp"):
                    from saengine.design.steel.built_up import BuiltUp

                    built = BuiltUp.of(resolved.get("builtUp"))
                    ri = built.radii()[0] if built is not None else None
                    if built is not None and ri:
                        rows += stitch_check(built.spacing, ri, klr, True, kind, t)
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                out["notes"].append(f"{m.id}: stitches not checked: {error}")
            if forces.connection_moment:
                rows.append(
                    _rule(
                        "bracing connection flexure",
                        False,
                        cite(t, "scbfConnection"),
                        f"the connection develops {forces.connection_moment / 1e6:.1f} kN·m "
                        "(1.1 Ry Mp about the buckling axis), unless it accommodates the brace's "
                        "post-buckling rotation (a gusset free to fold)",
                        flag=True,
                    )
                )
            zone = protected_zone(length, shape.dims.get("d") or shape.dims.get("H", 0.0), kind, t)
            if zone:
                summary["protectedZone"] = zone
            summary["kind"] = kind
        if m.id in k_braces:
            rules_k = (
                t.restrained.kBracing
                if kind == "brbf"
                else (t.concentric[kind].kBracing if kind in ("scbf", "ocbf") else True)
            )
            key = {"scbf": "scbfKBracing", "ocbf": "ocbfChevron", "brbf": "brbfChevron"}.get(
                kind, "scbfKBracing"
            )
            rows.append(
                _rule(
                    "K-type bracing",
                    rules_k,
                    cite(t, key),
                    "the brace meets a column between floors (K-type)"
                    + (
                        ": the column is continuous and takes the unbalanced brace force "
                        "(not checked by SAEngine)"
                        if rules_k
                        else f": not permitted in a {kind.upper()}"
                    ),
                    flag=bool(rules_k),
                )
            )
        capacity_forces[m.id] = forces
        summary.update(
            {
                "tension": round(forces.tension / 1e3, 1),
                "compression": round(forces.compression / 1e3, 1),
            }
        )
        # The connection re-checked at the capacity-design forces.
        conn = getattr(m.object, "connection", None)
        if conn is not None and getattr(conn, "type", None) == "gusset":
            try:
                section = section_of_profile(m.object.profile)
                plate = mats.get(conn.plateMaterial) if conn.plateMaterial else None
                found = sc.check_brace_gusset(
                    conn,
                    section,
                    SteelMaterial.from_material(m.material),
                    SteelMaterial.from_material(plate) if plate is not None else None,
                    [
                        ("expected tension", forces.connection_tension),
                        ("expected compression", -forces.connection_compression)
                        if forces.connection_compression > 0
                        else ("expected compression", 0.0),
                    ],
                )
                key = {
                    "scbf": "scbfConnection",
                    "ocbf": "ocbfConnection",
                    "brbf": "brbfConnection",
                    "ebf": "ebfBrace",
                }[kind]
                drop_slip = kind == "ocbf" and t.concentric["ocbf"].slipWithoutOmega
                for c in found["checks"]:
                    if drop_slip and "slip" in c["name"]:
                        continue
                    rows.append(
                        {
                            **c,
                            "name": f"{PREFIX}bracing connection at the capacity forces: "
                            f"{c['name']}",
                            "clause": cite(t, key),
                            "note": (c.get("note") or "") + f"; {forces.what}",
                        }
                    )
            except (ValueError, TypeError, KeyError) as error:
                out["notes"].append(f"{m.id}: bracing connection not re-checked: {error}")
        elif conn is None:
            rows.append(
                _rule(
                    "bracing connection",
                    False,
                    cite(t, "scbfConnection" if kind != "brbf" else "brbfConnection"),
                    f"no connection on the brace type: design it for {forces.what}",
                    flag=True,
                )
            )
        out["braces"][m.id] = summary
        add(m.id, rows)

    # Lines of bracing (SCBF): the tension share.
    if concentric == "scbf" and geometry:
        out["checks"] += tension_share_checks(_brace_lines(building, braces, geometry, info), t)

    # Chevrons: the beam with the unbalanced force.
    for panel, cluster in chevrons:
        tp = cluster[0][0]
        beam = _beam_at(panel.line, tp)
        if beam is None or beam.id not in by_id or beam.id not in info:
            continue
        ids = sorted({p[1] for p in cluster})
        forces = [capacity_forces[b] for b in ids if b in capacity_forces]
        if len(forces) < 2:
            continue
        angles = [_angle(*geometry[b]) for b in ids if b in capacity_forces]
        a, b = tp - panel.ta, panel.tb - tp
        best = (0.0, 0.0)
        for k in range(len(forces)):
            tens = [(forces[k].tension, angles[k])]
            comps = [(f.beam_compression, angles[j]) for j, f in enumerate(forces) if j != k]
            q, mq = chevron_demand(tens, comps, a, b)
            if mq > best[1]:
                best = (q, mq)
        q, mq = best
        # The gravity moment with the braces giving no support: the analysis moment plus the
        # braces' gravity support taken off as a point load at the intersection.
        bm = by_id[beam.id]
        st = info[beam.id]["stations"]
        mg = 0.0
        for c in gravity_idx:
            if c >= len(st) or not len(st[c].s):
                continue
            support = 0.0
            for bid, ang in zip(ids, [_angle(*geometry[x]) for x in ids], strict=False):
                bst = info[bid]["stations"] if bid in info else []
                if c < len(bst) and len(bst[c].s):
                    support += max(-float(np.mean(bst[c].P)), 0.0) * math.sin(ang)
            span = a + b
            mg = max(mg, float(np.max(np.abs(st[c].Mx))) + support * a * b / max(span, 1e-9))
        phi_mn = _moment_capacity(bm.entry)
        restrained_v = any(
            getattr(by_id[x].object, "restrained", None) is not None for x in ids if x in by_id
        )
        kind_c = "brbf" if restrained_v else (concentric or "scbf")
        key = {"scbf": "scbfChevron", "ocbf": "ocbfChevron", "brbf": "brbfChevron"}[kind_c]
        what = (
            "the adjusted brace strengths in tension and compression"
            if kind_c == "brbf"
            else f"Ry Fy Ag in tension and {t.concentric[kind_c].postBuckling:g} Pn in compression"
        )
        rows = [
            _check(
                "V-braced beam with the unbalanced brace force",
                (mq + mg) / 1e6,
                phi_mn / 1e6,
                "kN·m",
                cite(t, key),
                f"Q = {q / 1e3:.0f} kN at {a:.0f} mm from the column ({what}) on a beam "
                f"spanning {a + b:.0f} mm without the braces' support, plus the gravity moment "
                f"{mg / 1e6:.0f} kN·m of the largest gravity combination (conservative); the "
                "beam's axial force is not added",
            ),
            _rule(
                "V-braced beam continuity and bracing",
                False,
                cite(t, key),
                "the beam is continuous between the columns, both flanges braced (Lb ≤ Lpd), "
                "at least one set of lateral braces at the brace intersection, braces for Ry Z Fy "
                "with Cd = 1",
                flag=True,
            ),
        ]
        out["chevrons"].append(
            {"beam": beam.id, "braces": ids, "Q": round(q / 1e3, 1), "M": round(mq / 1e6, 1)}
        )
        add(beam.id, rows)

    # Links: the link checks and the beam outside the link.
    allowable = _drift_ratio(settings)
    link_columns: dict[str, list[tuple[float, float]]] = {}
    for link, panel, beam in links:
        axis = "X" if abs(panel.line.u[0]) >= abs(panel.line.u[1]) else "Y"
        drift, source = storey_drift(drifts, panel.line.level, link.height, axis, allowable)
        rows, summary = link_checks(link, drift, t, source)
        shape = info[beam.id]["shape"]
        steel = info[beam.id]["steel"]
        ca = S.axial_coefficient(link.pu, shape.area * steel.fy, t)
        rows += [
            _check(
                f"link {name} width-thickness (seismically compact)",
                ratio,
                limit,
                "",
                cite(t, "linkScope"),
                f"λ = {ratio:.1f} ≤ λps = {limit:.1f}, Ca = {ca:.3f}",
            )
            for name, ratio, limit in S.seismic_compact_limits(
                shape, steel.fy, steel.e, "beam", "ebf", ca, t
            )
        ]
        vn = link_strength(link, t)["Vn"]
        dem = ebf_demands(link, vn, t)
        phi_mn = _moment_capacity(by_id[beam.id].entry)
        rows.append(
            _check(
                "beam outside the link at the link's strength",
                dem["beamMoment"] / 1e6,
                link.ry * phi_mn / 1e6,
                "kN·m",
                cite(t, "ebfBeam"),
                f"M = {t.eccentric.beamFactor:g} Ry Vn e / 2 against Ry φMn; axial "
                f"{dem['beamAxial'] / 1e3:.0f} kN from the brace not added; the brace and beam "
                "centrelines meet at the link end or inside the link",
            )
        )
        summary["beamMoment"] = round(dem["beamMoment"] / 1e6, 1)
        out["links"].append(summary)
        add(beam.id, rows)
        # The link's shear reaches the columns of its bay (each taken at the whole: the share
        # each column takes is not resolved, conservative).
        for cid in (panel.left, panel.right):
            link_columns.setdefault(cid, []).append((panel.line.level, dem["column"]))

    # Columns: the capacity-design axial force from the braces (BRBF, slender SCBF braces) and
    # the links above (EBF), against φPn; the splices of SCBF and BRBF.
    in_bays = {cid for _link, panel, _beam in links for cid in (panel.left, panel.right)}
    for m in members:
        if m.kind != "column" or m.id not in info or not lateral(m):
            continue
        col = column_at.get(m.id)
        if col is None:
            continue
        position, top = col.position, col.top
        # The columns of the braced bays: a brace end on the column (or a link's bay), or
        # marked lateral; the other columns are gravity columns.
        touched = m.id in in_bays or any(
            np.linalg.norm(p[:2] - position) <= TOL
            and col.bottom - _level_tolerance() <= p[2] <= col.top + _level_tolerance()
            for g in geometry.values()
            for p in g
        )
        if not touched and S._role(m) != "lateral":
            continue
        i = info[m.id]
        st = i["stations"]
        p_grav = max(
            (float(np.max(st[c].P)) for c in gravity_idx if c < len(st) and len(st[c].s)),
            default=0.0,
        )
        add_p = 0.0
        sources: list[str] = []
        for bid, (p0, p1) in geometry.items():
            if bid not in capacity_forces:
                continue
            f = capacity_forces[bid]
            use = by_id[bid].object is not None and (
                getattr(by_id[bid].object, "restrained", None) is not None or bid in slender
            )
            if not use:
                continue
            for p in (p0, p1):
                if np.linalg.norm(p[:2] - position) <= TOL and p[2] >= top - _level_tolerance():
                    add_p += max(f.tension, f.compression) * math.sin(_angle(p0, p1))
                    sources.append(bid)
        if ebf:
            for level, v in link_columns.get(m.id, []):
                if level >= top - _level_tolerance():
                    add_p += v
                    sources.append("link")
        rows: list[dict[str, Any]] = []
        kind_col = "ebf" if ebf else ("brbf" if brbf else concentric)
        done = any(
            c["name"].startswith(PREFIX) and "width-thickness" in c["name"]
            for c in m.entry["checks"]
        )  # a moment frame column of a dual system: already checked (B35)
        if kind_col and not done:
            pu_plain = max(
                (float(np.max(st[c].P)) for c in plain if c < len(st) and len(st[c].s)),
                default=0.0,
            )
            ca = S.axial_coefficient(pu_plain, i["shape"].area * i["steel"].fy, t)
            rows += brace_compact_checks(
                i["shape"], i["steel"].fy, i["steel"].e, kind_col, "column", ca=ca, table=t
            )
        if add_p > 0:
            phi_pn = _capacity(m.entry, "Compression: buckling")
            key = "ebfColumns" if ebf else ("brbfMembers" if brbf else "scbfSlenderness")
            rows.append(
                _check(
                    "column at the braces' and links' capacity forces",
                    (p_grav + add_p) / 1e3,
                    phi_pn / 1e3,
                    "kN",
                    cite(t, key),
                    f"the largest gravity compression {p_grav / 1e3:.0f} kN + "
                    f"{add_p / 1e3:.0f} kN from {len(sources)} brace(s) or link(s) at and above "
                    "its top (vertical components summed: conservative where braces on both "
                    "sides counteract; the system's largest force as a cap is not taken)",
                )
            )
        splice = getattr(m.object, "splice", None)
        share = (
            t.restrained.spliceFlexureShare
            if brbf
            else (t.concentric[concentric].spliceFlexureShare if concentric else None)
        )
        height = max((float(x.s[-1]) for x in st if len(x.s)), default=0.0) * 1e3
        if splice is not None and share and height > 0:
            phi_mn = _moment_capacity(m.entry)
            mreq = share * phi_mn
            vreq = 2 * i["shape"].zx * i["steel"].fy / height
            try:
                section = section_of_profile(m.object.profile)
                plate = mats.get(splice.plateMaterial) if splice.plateMaterial else None
                found = sc.check_splice(
                    splice,
                    section,
                    SteelMaterial.from_material(m.material),
                    SteelMaterial.from_material(plate) if plate is not None else None,
                    [("capacity design", 0.0, mreq, vreq)],
                    column=True,
                )
                key = "brbfMembers" if brbf else "scbfSplices"
                rows += [
                    {
                        **c,
                        "name": f"{PREFIX}splice at {share:g} φMn and ΣMpc / H: {c['name']}",
                        "clause": cite(t, key),
                    }
                    for c in found["checks"]
                ]
            except (ValueError, TypeError, KeyError) as error:
                out["notes"].append(f"{m.id}: splice not re-checked: {error}")
        add(m.id, rows)

    for mid, rows in extra.items():
        m = by_id.get(mid)
        if m is None or not rows:
            continue
        m.entry["checks"].extend(rows)
        _rescore(m.entry)
    return out


def _compact_rows(shape: Any, steel: Any, member: str, table: Any) -> list[dict[str, Any]]:
    """Sec 10.20.15.6.1: EBF diagonal braces compact (Sec 10.20.8.2.1, Table 6.10.1)."""
    from saengine.design.steel import classify as cl

    out = []
    elements = cl.flexure_elements(shape, steel.fy, steel.e, "x") or cl.compression_elements(
        shape, steel.fy, steel.e
    )
    for el in elements:
        limit = el.lambda_p if el.lambda_p is not None else el.lambda_r
        out.append(
            _check(
                f"{member} {el.name} width-thickness (compact)",
                el.ratio,
                limit,
                "",
                cite(table, "ebfBrace"),
                f"λ = {el.ratio:.1f} ≤ {limit:.1f} of Table 6.10.1 case {el.case}",
            )
        )
    return out


def _brace_lines(
    building: Any,
    braces: list[Any],
    geometry: dict[str, tuple[np.ndarray, np.ndarray]],
    info: dict[str, dict[str, Any]],
) -> list[BraceLine]:
    """The lines of bracing: braces of one storey along X or Y whose plan lines lie within the
    table's offset share of the building's dimension across them."""
    t = S._table(None)
    share = t.concentric["scbf"].lineOffset or 0.0
    pts = np.array([p for g in geometry.values() for p in g], dtype=float)
    if not len(pts):
        return []
    extent = {"X": float(np.ptp(pts[:, 1])), "Y": float(np.ptp(pts[:, 0]))}
    groups: dict[tuple[str, float], list[tuple[float, str, float, int]]] = {}
    for m in braces:
        if m.id not in geometry:
            continue
        p0, p1 = geometry[m.id]
        d = p1 - p0
        if abs(d[0]) < 1e-6 and abs(d[1]) < 1e-6:
            continue
        axis = "X" if abs(d[0]) >= abs(d[1]) else "Y"
        h = d[0] if axis == "X" else d[1]
        sign = 1 if h * d[2] > 0 else -1
        across = (p0[1] + p1[1]) / 2 if axis == "X" else (p0[0] + p1[0]) / 2
        storey = round(float(max(p0[2], p1[2])) / 100.0) * 100.0
        weight = info[m.id]["shape"].area * abs(h) / float(np.linalg.norm(d))
        groups.setdefault((axis, storey), []).append((across, m.id, weight, sign))
    lines: list[BraceLine] = []
    for (axis, storey), rows in sorted(groups.items()):
        rows.sort()
        tol = max(share * extent[axis], TOL)
        current: list[tuple[float, str, float, int]] = []
        for row in rows:
            if current and row[0] - current[0][0] > tol:
                lines.append(_line_of(axis, storey, current))
                current = []
            current.append(row)
        if current:
            lines.append(_line_of(axis, storey, current))
    return lines


def _line_of(axis: str, storey: float, rows: list[tuple[float, str, float, int]]) -> BraceLine:
    across = sum(r[0] for r in rows) / len(rows)
    line = BraceLine(f"{axis} line at {across / 1e3:.2f} m, level {storey / 1e3:.2f} m")
    for _a, bid, w, sign in rows:
        if sign > 0:
            line.positive += w
        else:
            line.negative += w
        line.braces.append(bid)
    return line


def method_lines(found: dict[str, Any] | None = None) -> list[str]:
    t = S._table(None)
    kinds = ", ".join(k.upper() for k in (found or {}).get("kinds", [])) or "braced frames"
    return [
        (
            f"Steel braced frames ({S.pack_name()} {cite(t, 'scbfSlenderness').split(' (')[0]} to "
            f"{cite(t, 'brbfProtected')}; {kinds}): the braces' slenderness and width-thickness "
            "limits, the bracing connections at the braces' expected (or adjusted) strengths, the "
            "tension share along each line of bracing, V-braced beams with the unbalanced brace "
            "force, eccentrically braced links (shear with axial force, length, rotation at the "
            "allowable storey drift, stiffeners) with the braces, beams and columns at the links' "
            "strength, buckling-restrained braces from their test β and ω ('Seismic: ...' checks). "
            "The model's geometry gives the panels: braces meeting a beam inside a bay make a V or "
            "an eccentric brace."
        )
    ]


__all__ = [
    "KINDS",
    "BraceForces",
    "BraceLine",
    "BracedProvisions",
    "Link",
    "apply",
    "brace_compact_checks",
    "brace_slenderness_checks",
    "braced_provisions",
    "chevron_demand",
    "concentric_forces",
    "ebf_demands",
    "link_checks",
    "link_rotation",
    "link_strength",
    "method_lines",
    "net_section_check",
    "protected_zone",
    "restrained_checks",
    "restrained_strengths",
    "rotation_limit",
    "stitch_check",
    "tension_share_checks",
]
