"""Composite members of a steel seismic load resisting system: the seismic provisions for
composite structural systems on top of the composite member design
(:mod:`saengine.design.steel.composite`).

Every number is the code pack's ``steelSeismic`` table, group ``compositeSeismic`` (default pack BNBC 2020:
Part 6 Sec 13.5, Eqs 6.13.26-6.13.27); the clauses come from its ``sources``. The code pack has
no composite structural systems of its own (Table 6.2.19 lists none), so a composite member of
a steel system follows the level (``levels``: ordinary, intermediate, special) of the system's
frame or braced kind.

- **Materials** (:func:`concrete_checks`): f'c at least the table's least, and at most the
  table's cap for the strength (normal-weight and lightweight).
- **Encased columns** (:func:`encased_column_checks`): the steel share (else the column is a
  reinforced concrete column), the shear strength φ (Vn of the steel + Vs of the ties), the
  shear connectors' spacing, the ties' size and spacing of the level, Ash of Eq 6.13.27 for
  special systems.
- **Filled columns** (:func:`filled_column_checks`): the steel share, the shear on the steel
  alone, the wall thickness of rectangular HSS in special moment frames.
- **Composite beams of special moment frames** (:func:`composite_beam_checks`): the depth of
  the plastic neutral axis (Eq 6.13.26).

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.design.steel import seismic as S
from saengine.design.steel.seismic import PREFIX, _check, _rule, cite

LEVELS = ("ordinary", "intermediate", "special")


def level_of(kinds: list[str], table: Any | None = None) -> str | None:
    """The strictest seismic system level of the frame or braced ``kinds`` in use."""
    t = S._table(table)
    if t.compositeSeismic is None:
        return None
    found = [t.compositeSeismic.levels[k] for k in kinds if k in t.compositeSeismic.levels]
    return max(found, key=LEVELS.index) if found else None


def concrete_checks(fc: float, light: bool, table: Any | None = None) -> list[dict[str, Any]]:
    """Sec 13.5.4.2: f'c at least ``concreteMin``; for the nominal strength at most the cap of
    normal-weight or lightweight concrete (the strengths use the given f'c: a larger one fails
    here)."""
    t = S._table(table)
    c = t.compositeSeismic
    cap = c.concreteMaxLight if light else c.concreteMaxNormal
    clause = cite(t, "compositeMaterials")
    return [
        _check(
            "composite concrete f'c (least)",
            c.concreteMin,
            fc,
            "MPa",
            clause,
            f"at least {c.concreteMin:g} MPa",
        ),
        _check(
            "composite concrete f'c for the strength",
            fc,
            cap,
            "MPa",
            clause,
            f"at most {cap:g} MPa for {'lightweight' if light else 'normal-weight'} concrete "
            "in a seismic composite member: give the concrete at or below it",
        ),
    ]


def tie_spacing_limit(col: Any, level: str, smf: bool, table: Any | None = None) -> float:
    """The largest tie spacing of an encased column at the level [mm] (the end-zone spacing for
    intermediate systems, the confined spacing for columns of special moment frames)."""
    t = S._table(table)
    rules = getattr(t.compositeSeismic, level)
    least = min(col.width, col.depth)
    limits = []
    if rules.spacingLeastShare:
        limits.append(rules.spacingLeastShare * least)
    if rules.spacingBarDiameters and col.bars:
        limits.append(rules.spacingBarDiameters * col.barDiameter)
    if rules.spacingTieDiameters:
        limits.append(rules.spacingTieDiameters * col.tieDiameter)
    if rules.spacingMax:
        limits.append(rules.spacingMax)
    if level == "special" and smf:
        if rules.confinedLeastShare:
            limits.append(rules.confinedLeastShare * least)
        if rules.confinedMax:
            limits.append(rules.confinedMax)
    if level != "ordinary":
        limits.append(tie_spacing_limit(col, "ordinary", False, t))
    return min(limits) if limits else math.inf


def ash_required(
    hcc: float, s: float, fy: float, area: float, pn: float, fc: float, fyh: float, table=None
) -> float:
    """Eq 6.13.27: Ash = c hcc s (1 - Fy As / Pn) (f'c / Fyh) [mm²]."""
    c = S._table(table).compositeSeismic.special
    return (c.ashCoefficient or 0.0) * hcc * s * max(1 - fy * area / pn, 0.0) * fc / fyh


def encased_column_checks(
    col: Any,
    shape: Any,
    steel: Any,
    fc: float,
    pn: float,
    vu: float,
    level: str,
    smf: bool,
    table: Any | None = None,
) -> list[dict[str, Any]]:
    """Sec 13.5.5.3: an encased composite column of the seismic system. ``pn``: the composite
    column's nominal compressive strength [N]; ``vu``: its largest shear along the web [N]."""
    from saengine.design.steel import members as sm

    t = S._table(table)
    c = t.compositeSeismic
    ag = col.width * col.depth
    share = shape.area / ag if ag > 0 else 0.0
    rows = [
        _check(
            "encased steel share",
            c.steelShareMin,
            share,
            "",
            cite(t, "encasedScope"),
            f"As / Ag = {share:.3f} at least {c.steelShareMin:g}; below it the column is a "
            "reinforced concrete column with the steel shape's contribution",
        )
    ]
    # Shear: the steel shape plus the ties (Sec 13.5.5.3.1(a)).
    clause = cite(t, "encasedOrdinary")
    vn_steel = sm.shear_major(shape, steel).nominal
    legs = 2
    av = legs * math.pi * col.tieDiameter**2 / 4
    dv = col.depth - col.cover - col.tieDiameter - col.barDiameter / 2
    vs = av * col.barFy * dv / col.tieSpacing
    rows.append(
        _check(
            "encased column shear",
            vu / 1e3,
            c.shearPhi * (vn_steel + vs) / 1e3,
            "kN",
            clause,
            f"φ (Vn steel {vn_steel / 1e3:.0f} + Vs ties {vs / 1e3:.0f} kN), Vs = Av fy d / s "
            f"with {legs} legs, d = {dv:.0f} mm",
        )
    )
    if col.loadApplied in ("steel", "concrete"):
        rows.append(
            _check(
                "encased column shear connector spacing",
                col.studSpacing,
                c.connectorSpacingMax,
                "mm",
                clause,
                f"at most {c.connectorSpacingMax:g} mm along the outside flange faces",
            )
        )
    # Ties: size and spacing.
    o = c.ordinary
    greatest = max(col.width, col.depth)
    need = max((o.tieGreatestShare or 0.0) * greatest, o.tieMin or 0.0)
    if o.tieMax:
        need = min(need, o.tieMax)
    rows.append(
        _check(
            "encased column tie diameter",
            need,
            col.tieDiameter,
            "mm",
            clause,
            f"at least {o.tieGreatestShare:g} × the greatest side, not below {o.tieMin:g} mm, "
            f"need not exceed {o.tieMax:g} mm",
        )
    )
    key = {"ordinary": "encasedOrdinary", "intermediate": "encasedIntermediate"}.get(
        level, "encasedSpecial"
    )
    limit = tie_spacing_limit(col, level, smf, t)
    rows.append(
        _check(
            f"encased column tie spacing ({level} system)",
            col.tieSpacing,
            limit,
            "mm",
            cite(t, key),
            "one tie spacing over the column height is held to the strictest zone"
            + ("; columns of special moment frames: the confined spacing" if smf else ""),
        )
    )
    if level == "special" and pn > 0:
        sp = c.special
        for side, dim in (("across the width", col.width), ("across the depth", col.depth)):
            hcc = dim - 2 * col.cover - col.tieDiameter
            need_ash = ash_required(hcc, col.tieSpacing, steel.fy, shape.area, pn, fc, col.barFy, t)
            rows.append(
                _check(
                    f"encased column hoops Ash ({side})",
                    need_ash,
                    legs * math.pi * col.tieDiameter**2 / 4,
                    "mm²",
                    cite(t, "encasedSpecial"),
                    f"Ash = {sp.ashCoefficient:g} hcc s (1 - Fy As / Pn)(f'c / Fyh), hcc = "
                    f"{hcc:.0f} mm, Pn = {pn / 1e3:.0f} kN; hoops, no welded wire fabric; the "
                    "exemption of a steel section alone above 1.0D + 0.5L is not taken",
                )
            )
        rows.append(
            _rule(
                "encased column hoop extent",
                False,
                cite(t, "encasedSpecial"),
                f"the hoops run the full length in braced frames above {sp.bracedAxialShare:g} "
                f"Po and below discontinued stiff members above {sp.discontinuityShare:g} Po; "
                f"they extend {sp.footingExtension:g} mm into a footing; cross ties at most "
                f"{sp.crossTieSpacing:g} mm apart",
                flag=True,
            )
        )
    return rows


def filled_column_checks(
    col: Any, shape: Any, steel: Any, smf: bool, table: Any | None = None
) -> list[dict[str, Any]]:
    """Sec 13.5.5.4: a concrete-filled HSS column of the seismic system."""
    t = S._table(table)
    c = t.compositeSeismic
    clause = cite(t, "filledSeismic")
    d = shape.dims
    if shape.family == "rhs":
        outer = d.get("B", 0.0) * d.get("H", 0.0)
    else:
        outer = math.pi * d.get("D", 0.0) ** 2 / 4
    share = shape.area / outer if outer > 0 else 0.0
    rows = [
        _check(
            "filled steel share",
            c.steelShareMin,
            share,
            "",
            clause,
            f"As / Ag = {share:.3f} at least {c.steelShareMin:g}",
        ),
        _rule(
            "filled column shear on the steel alone",
            True,
            clause,
            "the design shear strength is the steel section's alone (the member's shear checks)",
            flag=True,
        ),
    ]
    if smf and shape.family == "rhs":
        for face in ("b", "h"):
            flat = d.get(face, 0.0)
            need = flat * math.sqrt(steel.fy / (c.filledWall * steel.e))
            rows.append(
                _check(
                    f"filled HSS wall thickness ({face})",
                    need,
                    d.get("t", 0.0),
                    "mm",
                    clause,
                    f"t ≥ {face} √(Fy / ({c.filledWall:g} Es)) in a special moment frame",
                )
            )
    return rows


def composite_beam_checks(
    shape: Any,
    steel: Any,
    beam: Any,
    concrete: Any,
    span: float,
    ratio: float,
    table: Any | None = None,
) -> list[dict[str, Any]]:
    """Eq 6.13.26: the plastic neutral axis of a composite beam of a special moment frame at
    most (Ycon + db) / (1 + c Fy / Es) below the top of the concrete, with the beam's degree of
    composite action ``ratio``."""
    from saengine.design.steel import composite as cm

    t = S._table(table)
    c = t.compositeSeismic
    ct = cm.composite_table()
    geom = cm.beam_geometry(shape, steel.fy, steel.e, beam, span, ct)
    conc = cm.concrete_of(concrete, ct, "slab concrete")
    alpha = ct.stressBlock.concrete
    full = min(alpha * conc.fc * geom.slab.area(), geom.steel_area * geom.fy)
    found = cm.plastic_positive(geom, conc.fc, max(ratio, 1e-6) * full, ct)
    cs = max(0.0, (geom.steel_area * geom.fy - found["C"]) / 2)
    depth = geom.steel.depth_for(cs / geom.fy) if cs > 1e-6 else found["a"]
    ycon = geom.tc
    limit = (ycon + geom.d) / (1 + c.beamStrain * steel.fy / steel.e)
    return [
        _check(
            "composite beam plastic neutral axis depth",
            depth,
            limit,
            "mm",
            cite(t, "compositeBeam"),
            f"from the top of the concrete at most (Ycon + db) / (1 + {c.beamStrain:g} Fy / Es) "
            f"= ({ycon:.0f} + {geom.d:.0f}) / (1 + {c.beamStrain * steel.fy / steel.e:.2f}); "
            f"{ratio:.0%} composite",
        )
    ]


def apply(
    members: list[Any],
    mats: dict[str, Any],
    combinations: list[str],
    kinds: list[str],
    roles: dict[str, str],
    table: Any | None = None,
) -> list[str]:
    """Adds the composite seismic checks to the composite steel members of the seismic system
    (``members``: :class:`saengine.design.steel.seismic.SteelMember`; ``kinds``: the frame and
    braced kinds in use; ``roles``: lateral or gravity by member id). Returns notes."""
    from saengine.design.steel import composite as cm
    from saengine.design.steel import members as sm
    from saengine.design.steel.properties import shape_properties

    t = table if table is not None else S.seismic_table()
    if t is None or t.compositeSeismic is None:
        return []
    level = level_of(kinds, t)
    if level is None:
        return []
    ct = cm.composite_table()
    smf = "smf" in kinds
    plain = [c for c, name in enumerate(combinations) if not name.startswith("Ω0: ")]
    notes: list[str] = []
    for m in members:
        comp = getattr(m.object, "composite", None)
        if comp is None or roles.get(m.id, "lateral") == "gravity":
            continue
        try:
            shape = shape_properties(m.object.profile)
            steel = sm.Steel.of(m.material)
            concrete = mats.get(comp.concrete)
            if concrete is None or ct is None:
                raise ValueError(f"no concrete '{comp.concrete}'")
            conc = cm.concrete_of(concrete, ct)
        except (ValueError, sm.SteelDesignError, cm.CompositeError) as error:
            notes.append(f"{m.id}: composite seismic provisions not checked: {error}")
            continue
        rows = concrete_checks(conc.fc_given, conc.light, t)
        stations = sm.member_stations(m.pieces, combinations, m.turned)
        summary = m.entry.get("composite") or {}
        try:
            if m.kind == "column" and comp.type == "compositeColumn":
                if comp.form == "encased":
                    vu = max(
                        (
                            float(np.max(np.abs(stations[c].Vy)))
                            for c in plain
                            if c < len(stations) and len(stations[c].s)
                        ),
                        default=0.0,
                    )
                    pn = float(summary.get("Pn") or 0.0) * 1e3
                    rows += encased_column_checks(
                        comp, shape, steel, conc.fc_given, pn, vu, level, smf, t
                    )
                else:
                    rows += filled_column_checks(comp, shape, steel, smf, t)
            elif m.kind == "beam" and comp.type == "compositeBeam" and smf:
                span = max((float(st.s[-1]) for st in stations if len(st.s)), default=0.0) * 1e3
                rows += composite_beam_checks(
                    shape, steel, comp, concrete, span, float(summary.get("ratio") or 1.0), t
                )
        except (ValueError, KeyError, ZeroDivisionError, cm.CompositeError) as error:
            notes.append(f"{m.id}: composite seismic provisions not checked: {error}")
            continue
        for r in rows:
            if not r["name"].startswith(PREFIX):
                r["name"] = PREFIX + r["name"]
        m.entry["checks"].extend(rows)
        strength = [c for c in m.entry["checks"] if not c["flag"]]
        m.entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
        m.entry["ok"] = all(c["ok"] for c in strength)
    return notes


def method_lines() -> list[str]:
    t = S._table(None)
    return [
        (
            f"Composite members of the steel seismic system ({S.pack_name()} "
            f"{cite(t, 'compositeMaterials').split(',')[0]} to {cite(t, 'compositeWall')}): the "
            "concrete limits, encased columns' steel share, shear with the ties, connectors and "
            "the ties of the system's level (ordinary, intermediate, special), filled columns' "
            "steel share and walls, and the plastic neutral axis of composite beams in special "
            "moment frames."
        )
    ]


__all__ = [
    "LEVELS",
    "apply",
    "ash_required",
    "composite_beam_checks",
    "concrete_checks",
    "encased_column_checks",
    "filled_column_checks",
    "level_of",
    "method_lines",
    "tie_spacing_limit",
]
