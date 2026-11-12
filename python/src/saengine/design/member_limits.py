"""Member steel limits, cover and mix by exposure condition, development and lap lengths by the
design bond stress (alpha 9 C8; the pack's ``concreteMethods.memberLimits``, ``cover`` method
``exposureCondition`` and ``anchorage`` method ``bondStressTable``, as IS 456:2000 26 and
Tables 5 and 16 give them).

Rows of the design report (the check format of :func:`saengine.design.check._check`; a "not
less than" row takes the required value as its demand and the provided one as its capacity):

- beams: the neutral axis depth xu / d at most xu,max / d (the bars' strain at least fyd/Es +
  ``neutralAxisStrain``), the least tension steel As/(b d) >= beamMin / fy on each face, the
  largest beamMax × b D, the side face steel of webs deeper than ``sideFaceDepth``, the
  stirrup spacing (the shear method's), the nominal cover, the concrete grade and the
  development and lap lengths of the largest bar (stated, flagged: cut-off points are not
  modelled);
- columns: the steel ratio range, the number and size of the bars, the tie size and pitch,
  the column cover and the grade;
- slabs (:func:`slab_rows`): the least steel each way, the bar size and the spacing.

The exposure condition is the pack's ``defaultExposure`` (Project Settings > Code values to
change it, ``concreteMethods.defaultExposure``).
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design.tabulated_shear import _group, _interp, _paren
from saengine.design.tabulated_shear import rules as shear_rules


def limits() -> Any | None:
    """The pack's ``concreteMethods.memberLimits``, or None."""
    return _group("memberLimits")


def cover_rules() -> Any | None:
    return _group("cover", "exposureCondition")


def bond_rules() -> Any | None:
    return _group("anchorage", "bondStressTable")


def covered() -> bool:
    return limits() is not None


def _row(name: str, demand: float, capacity: float, unit: str, note: str = "", flag: bool = False):
    from saengine.design.check import _check

    return _check(name, demand, capacity, unit, None, note, flag=flag)


def exposure() -> tuple[str, Any] | None:
    """(id, condition) of the exposure in force, or None."""
    from saengine.design.tabulated_shear import _table

    c = cover_rules()
    t = _table()
    if c is None or t is None:
        return None
    key = t.defaultExposure or next(iter(c.conditions))
    found = c.conditions.get(key)
    return (key, found) if found is not None else None


def nominal_cover(bar: float, kind: str = "beam", fck: float = 0.0) -> float | None:
    """The least nominal cover [mm] of a member kind ('beam', 'slab', 'column', 'footing')."""
    c = cover_rules()
    found = exposure()
    if c is None or found is None:
        return None
    key, cond = found
    cover = cond.cover
    if kind in ("beam", "column") and getattr(cond, "beamCover", None) is not None:
        cover = cond.beamCover  # Alpha 9 C20b: beams and columns (GB 50010 Table 8.2.1 type)
    first = next(iter(c.conditions))
    if key == first and bar <= c.smallBarReduction[1]:
        cover -= c.smallBarReduction[0]
    if key in c.gradeReductionConditions and fck >= c.gradeReduction[1]:
        cover -= c.gradeReduction[0]
    if kind == "column":
        cover = max(cover, c.columnCover, bar)
    elif kind == "footing":
        cover = max(cover, c.footingCover)
    return max(cover, bar)


def bond_stress(fck: float) -> float:
    b = bond_rules()
    return _interp(fck, list(b.grades), list(b.bond))


def development_length(
    dia: float, fy: float, fck: float, compression: bool = False, seismic: float = 1.0
) -> float:
    """Ld = φ σs / (4 τbd) [mm], σs = fy / γs; deformed bars (fy above the plain bars').

    Alpha 9 C20b (GB 50010 8.3 type): × ζa of the pack's large bars, at least ``minLength``,
    × ``seismic`` (ζa,E of the seismic grade, 11.1.7; 1 outside earthquake design)."""
    from saengine.design import design_strength

    b = bond_rules()
    lim = limits()
    tau = bond_stress(fck)
    if lim is None or fy > lim.plainFy:
        tau *= b.deformedFactor
    if compression:
        tau *= b.compressionFactor
    ld = dia * design_strength.fyd(fy) / (4 * tau)
    large = getattr(b, "largeBarFactor", None)
    if large is not None and dia > large[0]:
        ld *= float(large[1])
    if seismic != 1.0:
        ld *= seismic
    floor = getattr(b, "minLength", None)
    return max(ld, float(floor)) if floor is not None else ld


def lap_length(
    dia: float,
    fy: float,
    fck: float,
    kind: str = "flexure",
    seismic: float = 1.0,
    share: float | None = None,
) -> float | None:
    """The lap [mm] in flexural tension, direct tension or compression; None above the largest
    bar that may be lapped. Alpha 9 C20b: ll = ζl Ld at least ``lapMinLength`` where the pack
    gives ``lapFactors``: ζl of the first row whose share holds ``share`` (the share of the
    bars lapped at one section; None: the first row's)."""
    b = bond_rules()
    if dia > b.lapLargeBar:
        return None
    factors = getattr(b, "lapFactors", None)
    floor = getattr(b, "lapMinLength", None)
    if factors:
        rows = sorted(factors)
        wanted = rows[0][0] if share is None else share
        zeta = next((z for s, z in rows if s >= wanted - 1e-9), rows[-1][1])
        ld = development_length(dia, fy, fck, kind == "compression", seismic)
        lap = float(zeta) * ld
        return max(lap, float(floor)) if floor is not None else lap
    if kind == "compression":
        return max(development_length(dia, fy, fck, True), b.lapCompression * dia)
    ld = development_length(dia, fy, fck)
    if kind == "direct":
        return max(b.lapDirectTension * ld, b.lapTension * dia)
    return max(ld, b.lapTension * dia)


def _grade_row(fck: float) -> dict[str, Any] | None:
    found = exposure()
    if found is None:
        return None
    key, cond = found
    if cond.cement is None:
        # Alpha 9 C20b: a code without a least cement content (GB 50010 3.5.3 type); the
        # grade named as the pack names it.
        from saengine.design import design_strength

        return _row(
            f"Concrete grade for the exposure{_paren('durability')}",
            cond.grade,
            fck,
            "MPa",
            f"exposure '{key}': at least {design_strength.strength_class(cond.grade)}, "
            f"w/c <= {cond.waterCement:g} (the mix is not checked)",
        )
    return _row(
        f"Concrete grade for the exposure{_paren('durability')}",
        cond.grade,
        fck,
        "MPa",
        f"exposure '{key}': at least M{cond.grade:g}, cement >= {cond.cement:g} kg/m³, free "
        f"w/c <= {cond.waterCement:g} (the mix is not checked)",
    )


def _cover_rows(cover: float | None, bar: float, kind: str, fck: float) -> list[dict[str, Any]]:
    need = nominal_cover(bar, kind, fck)
    if need is None or cover is None:
        return []
    key = exposure()[0]
    return [
        _row(
            f"Nominal cover{_paren('cover')}",
            need,
            cover,
            "mm",
            f"exposure '{key}'"
            + (", columns at least the column cover" if kind == "column" else ""),
        )
    ]


def _anchorage_rows(section: Any, kind: str = "beam") -> list[dict[str, Any]]:
    if bond_rules() is None or not section.bars:
        return []
    dia = max(b.dia for b in section.bars)
    if getattr(bond_rules(), "lapFactors", None):
        return _factored_anchorage_rows(section, dia, kind)  # Alpha 9 C20b
    ld = development_length(dia, section.fy, section.fc)
    lap = lap_length(dia, section.fy, section.fc)
    rows = [
        _row(
            f"Development length of {dia:g} mm bars{_paren('anchorage')}",
            ld,
            ld,
            "mm",
            f"Ld = φ fyd / (4 τbd), τbd = {bond_stress(section.fc):.2f} MPa × the deformed bar "
            f"factor; laps {lap:.0f} mm in flexural tension{_paren('laps')}"
            if lap is not None
            else "bars this large are not lapped: welded or mechanical splices",
            flag=True,
        )
    ]
    b = bond_rules()
    if dia > b.lapLargeBar:
        rows.append(
            _row(
                f"No laps of bars above {b.lapLargeBar:g} mm{_paren('laps')}",
                dia,
                b.lapLargeBar,
                "mm",
                "splice them by welding or couplers",
                flag=True,
            )
        )
    return rows


def _factored_anchorage_rows(section: Any, dia: float, kind: str) -> list[dict[str, Any]]:
    """Alpha 9 C20b: la = ζa lab (lab = φ fyd / (4 τbd)) at least the pack's least length, the
    seismic la,E = ζa,E la of the building's seismic grade, and the laps ll = ζl la (llE = ζl
    la,E) by the share of the bars lapped at one section (GB 50010 8.3, 8.4, 11.1.7 type)."""
    from saengine.design import seismic_grades

    b = bond_rules()
    zeta_e = seismic_grades.factor("anchorage", 1.0)
    share = b.columnLapShare if kind == "column" else None
    la = development_length(dia, section.fy, section.fc)
    lae = development_length(dia, section.fy, section.fc, seismic=zeta_e)
    lap = lap_length(dia, section.fy, section.fc, seismic=zeta_e, share=share)
    rows_ = sorted(b.lapFactors)
    wanted = rows_[0][0] if share is None else share
    zeta_l = next((z for s, z in rows_ if s >= wanted - 1e-9), rows_[-1][1])
    large = b.largeBarFactor
    notes = [
        f"la = ζa lab, lab = φ fyd / (4 τbd), τbd = {bond_stress(section.fc):.2f} MPa"
        + (f", ζa {large[1]:g} above {large[0]:g} mm" if large is not None else "")
        + (f", at least {b.minLength:g} mm" if b.minLength is not None else "")
    ]
    if zeta_e != 1.0:
        notes.append(f"la,E = ζa,E la = {zeta_e:g} × {la:.0f} = {lae:.0f} mm (seismic grade)")
    notes.append(
        f"laps ll = ζl la{',E' if zeta_e != 1.0 else ''} = {lap:.0f} mm (ζl {zeta_l:g}, "
        f"{100 * wanted:g} % of the bars lapped at one section"
        + (f", at least {b.lapMinLength:g} mm" if b.lapMinLength is not None else "")
        + f"){_paren('laps')}"
        if lap is not None
        else "bars this large are not lapped: welded or mechanical splices"
    )
    rows = [
        _row(
            f"Development length of {dia:g} mm bars{_paren('anchorage')}",
            lae,
            lae,
            "mm",
            "; ".join(notes),
            flag=True,
        )
    ]
    if dia > b.lapLargeBar:
        rows.append(
            _row(
                f"No laps of bars above {b.lapLargeBar:g} mm{_paren('laps')}",
                dia,
                b.lapLargeBar,
                "mm",
                "splice them by welding or couplers",
                flag=True,
            )
        )
    return rows


def beam_rows(
    section: Any, transverse: Any, capacities: dict[bool, Any], cover: float | None
) -> list[dict[str, Any]]:
    """The member rows of a beam (see the module notes)."""
    from saengine.design import design_strength

    lim = limits()
    if lim is None:
        return []
    rows: list[dict[str, Any]] = []
    b, h = section.width, section.depth
    eps_cu = design_strength.ultimate_strain(section.fc)
    limit = eps_cu / (eps_cu + design_strength.fyd(section.fy) / section.es + lim.neutralAxisStrain)
    for hogging, face in ((False, "bottom"), (True, "top")):
        tension = [bar for bar in section.bars if (bar.y > 0 if hogging else bar.y < 0)]
        if not tension:
            continue
        area = sum(bar.area for bar in tension)
        d = section.effective_depth(top=hogging)
        cap = capacities.get(hogging)
        if cap is not None and cap.mn > 0 and math.isfinite(cap.eps_t):
            ratio = eps_cu / (eps_cu + max(cap.eps_t, 0.0))
            rows.append(
                _row(
                    f"Neutral axis depth, {face} in tension{_paren('neutralAxis')}",
                    ratio,
                    limit,
                    "",
                    f"xu/d <= xu,max/d = εcu / (εcu + fyd/Es + {lim.neutralAxisStrain:g})",
                )
            )
        if getattr(lim, "beamMinRatio", None) is not None:
            # Alpha 9 C20b: max(ratio, c fctd / fyd) on b h (GB 50010 8.5.1 type).
            tensile = (
                (lim.beamMinTensile or 0.0)
                * design_strength.fctd(section.fc)
                / design_strength.fyd(section.fy)
            )
            least = max(float(lim.beamMinRatio), tensile)
            rows.append(
                _row(
                    f"Least tension steel, {face}{_paren('beamSteel')}",
                    least * b * h,
                    area,
                    "mm²",
                    f"As/(b h) >= max({100 * lim.beamMinRatio:g} %, "
                    f"{lim.beamMinTensile or 0.0:g} fctd/fyd = {100 * tensile:.3f} %)",
                )
            )
        else:
            rows.append(
                _row(
                    f"Least tension steel, {face}{_paren('beamSteel')}",
                    lim.beamMin / section.fy * b * d,
                    area,
                    "mm²",
                    f"As/(b d) >= {lim.beamMin:g}/fy",
                )
            )
        rows.append(
            _row(
                f"Largest steel, {face}{_paren('beamSteel')}",
                area,
                lim.beamMax * b * h,
                "mm²",
                f"As <= {lim.beamMax:g} b D",
            )
        )
    if h > lim.sideFaceDepth:
        inner = [bar for bar in section.bars if abs(bar.y) < 0.3 * h]
        # Alpha 9 C20b: the share of each face (GB 50010 9.2.13 type) doubles the total.
        each = bool(getattr(lim, "sideFaceEach", False))
        rows.append(
            _row(
                f"Side face steel{_paren('sideFace')}",
                lim.sideFaceShare * b * h * (2 if each else 1),
                sum(bar.area for bar in inner),
                "mm²",
                f"D > {lim.sideFaceDepth:g} mm: {lim.sideFaceShare * 100:g} % of the web area on "
                + ("each face" if each else "the two faces")
                + f", at most {lim.sideFaceSpacing:g} mm apart",
            )
        )
    r = shear_rules()
    if r is not None and transverse is not None and getattr(transverse, "spacing", None):
        try:
            d = section.effective_depth(top=False)
        except Exception:  # noqa: BLE001
            d = section.effective_depth(top=True)
        rows.append(
            _row(
                f"Stirrup spacing{_paren('shearSpacing')}",
                transverse.spacing,
                min(r.spacing[0] * d, r.spacing[1]),
                "mm",
                f"sv <= min({r.spacing[0]:g} d, {r.spacing[1]:g} mm)",
            )
        )
    bar = max((x.dia for x in section.bars), default=0.0)
    rows += _cover_rows(cover, bar, "beam", section.fc)
    grade = _grade_row(section.fc)
    if grade is not None:
        rows.append(grade)
    rows += _anchorage_rows(section)
    return rows


def column_rows(section: Any, transverse: Any, cover: float | None) -> list[dict[str, Any]]:
    """The member rows of a column (see the module notes)."""
    lim = limits()
    if lim is None:
        return []
    rows: list[dict[str, Any]] = []
    ag = section.gross_area
    rho = section.steel_area / ag
    low, high = lim.columnRho
    rows.append(_row(f"Least steel ratio{_paren('columnSteel')}", 100 * low, 100 * rho, "%"))
    rows.append(_row(f"Largest steel ratio{_paren('columnSteel')}", 100 * rho, 100 * high, "%"))
    circular = section.profile.__class__.__name__ == "CircleProfile"
    rows.append(
        _row(
            f"Number of bars{_paren('columnSteel')}",
            lim.columnBars[1 if circular else 0],
            len(section.bars),
            "",
        )
    )
    small = min(b.dia for b in section.bars)
    large = max(b.dia for b in section.bars)
    rows.append(_row(f"Bar diameter{_paren('columnSteel')}", lim.columnBarDia, small, "mm"))
    if transverse is not None:
        tie = float(transverse.dia)
        rows.append(
            _row(
                f"Tie diameter{_paren('columnLinks')}",
                max(lim.tieDiaShare * large, lim.tieDiaMin),
                tie,
                "mm",
                f"at least {lim.tieDiaShare:g} × the largest bar and {lim.tieDiaMin:g} mm",
            )
        )
        if getattr(transverse, "spacing", None):
            least = min(section.width, section.depth)
            n, mm = lim.tiePitch
            rows.append(
                _row(
                    f"Tie pitch{_paren('columnLinks')}",
                    transverse.spacing,
                    min(least, n * small, mm),
                    "mm",
                    f"at most min(least dimension, {n:g} φ, {mm:g} mm)",
                )
            )
    rows += _cover_rows(cover, large, "column", section.fc)
    grade = _grade_row(section.fc)
    if grade is not None:
        rows.append(grade)
    rows += _anchorage_rows(section, "column")
    return rows


def slab_rows(
    thickness: float,
    d: float,
    fy: float,
    bar: float,
    spacing: float | None,
    area_per_m: float,
    main: bool = True,
    fc: float | None = None,
) -> list[dict[str, Any]]:
    """The least steel (per metre width), bar size and spacing of a solid slab direction
    (alpha 9 C20b: ``fc`` [MPa] for the pack's ``slabMinTensile``)."""
    lim = limits()
    if lim is None:
        return []
    share = lim.slabMin[1] if fy <= lim.plainFy else lim.slabMin[0]
    how = f"{share * 100:g} % of b D"
    tensile_c = getattr(lim, "slabMinTensile", None)
    if tensile_c is not None and fy > lim.plainFy and fc:
        # Alpha 9 C20b: at least c fctd / fyd too (GB 50010 8.5.1 type), where the caller
        # gives the slab's concrete.
        from saengine.design import design_strength

        tensile = tensile_c * design_strength.fctd(fc) / design_strength.fyd(fy)
        how = f"max({share * 100:g} %, {tensile_c:g} fctd/fyd = {100 * tensile:.3f} %) of b D"
        share = max(share, tensile)
    rows = [
        _row(
            f"Least slab steel{_paren('slabSteel')}",
            share * 1000 * thickness,
            area_per_m,
            "mm²/m",
            how,
        ),
        _row(
            f"Slab bar diameter{_paren('slabSteel')}",
            bar,
            lim.slabBarShare * thickness,
            "mm",
            f"at most D/{1 / lim.slabBarShare:g}",
        ),
    ]
    if spacing:
        n, mm = lim.slabSpacing if main else lim.slabDistributionSpacing
        rows.append(
            _row(
                f"Slab bar spacing{_paren('slabSteel')}",
                spacing,
                min(n * d, mm),
                "mm",
                f"at most min({n:g} d, {mm:g} mm)",
            )
        )
    return rows
