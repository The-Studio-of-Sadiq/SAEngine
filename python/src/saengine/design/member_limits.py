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


def development_length(dia: float, fy: float, fck: float, compression: bool = False) -> float:
    """Ld = φ σs / (4 τbd) [mm], σs = fy / γs; deformed bars (fy above the plain bars')."""
    from saengine.design import design_strength

    b = bond_rules()
    lim = limits()
    tau = bond_stress(fck)
    if lim is None or fy > lim.plainFy:
        tau *= b.deformedFactor
    if compression:
        tau *= b.compressionFactor
    return dia * design_strength.fyd(fy) / (4 * tau)


def lap_length(dia: float, fy: float, fck: float, kind: str = "flexure") -> float | None:
    """The lap [mm] in flexural tension, direct tension or compression; None above the largest
    bar that may be lapped."""
    b = bond_rules()
    if dia > b.lapLargeBar:
        return None
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


def _anchorage_rows(section: Any) -> list[dict[str, Any]]:
    if bond_rules() is None or not section.bars:
        return []
    dia = max(b.dia for b in section.bars)
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
        rows.append(
            _row(
                f"Side face steel{_paren('sideFace')}",
                lim.sideFaceShare * b * h,
                sum(bar.area for bar in inner),
                "mm²",
                f"D > {lim.sideFaceDepth:g} mm: {lim.sideFaceShare * 100:g} % of the web area on the "
                f"two faces, at most {lim.sideFaceSpacing:g} mm apart",
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
    rows += _anchorage_rows(section)
    return rows


def slab_rows(
    thickness: float,
    d: float,
    fy: float,
    bar: float,
    spacing: float | None,
    area_per_m: float,
    main: bool = True,
) -> list[dict[str, Any]]:
    """The least steel (per metre width), bar size and spacing of a solid slab direction."""
    lim = limits()
    if lim is None:
        return []
    share = lim.slabMin[1] if fy <= lim.plainFy else lim.slabMin[0]
    rows = [
        _row(
            f"Least slab steel{_paren('slabSteel')}",
            share * 1000 * thickness,
            area_per_m,
            "mm²/m",
            f"{share * 100:g} % of b D",
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
