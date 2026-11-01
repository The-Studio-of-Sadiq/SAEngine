"""Structural detailing of piles by the code pack (Part 9, deep foundations).

The pack's ``foundations.piles.detailing`` group holds the rules, its ``sources`` the clauses;
a pack without the group does not cover them (:func:`not_covered`). Checks by pile kind
(:func:`detailing_checks`), each a requirement (demand) against what the pile type provides
(capacity), or a limit (capacity) against the pile's value (demand):

- bored cast-in-situ piles and drilled shafts (``bored``): least f'c (the larger of the
  section's value and the foundation concrete table's), least diameter and its step, least
  longitudinal steel by the gross area (``minSteel`` bands), least number of bars, least bar
  size of large piles, least fy, least cover, hoops not closer than ``minHoopPitch``, the cage
  at least ``reinforcedDepth`` below the cut-off and ``casingExtra`` below a temporary casing,
  the least cement content by placement and the water/cement ratio of the mix (from the
  concrete material's composition, where it gives them), the build-ability guidance table and
  the recommended mix (notes);
- driven precast piles (``driven``): least f'c (higher for hard driving), L/B at most
  ``maxSlenderness``, least longitudinal steel by L/B (``steelByLength``), ties at least
  ``minTie`` and their volume at the ends (over ``tieEndLength`` B, the transverse bars' end
  zone spacing) and in the body;
- driven cast-in-place piles (``drivenCastInPlace``): least butt area and tip diameter, least
  cover (more in corrosive ground or concrete placed under water or slurry), least f'c as bored
  piles; they may be plain where the soil supports them laterally;
- every kind on a corrosive site (the soil report's chemistry): cover at least
  ``corrosiveCover`` and the protection notes.

A ``ratio band`` row is ``[from, ratio, inclusive]``: the ratio of the last row whose bound the
value reaches (at or above it when inclusive, above it otherwise).

Units: mm, MPa, kg/m³.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.substructure import pile_static


def rules() -> Any | None:
    """The pack's pile detailing rules, or None when the pack does not cover them."""
    found = pile_static.rules()
    return None if found is None else found.detailing


def not_covered(what: str = "Pile detailing") -> str:
    return pile_static.not_covered(what)


def cite(key: str) -> str:
    """The clause of ``piles.<key>`` in the pack's sources, up to its first colon (the
    reference without its summary); empty when none."""
    from saengine.soil.piles import pile_clause

    text = pile_clause(key)
    return text.split(":")[0].strip() if text else ""


def band_ratio(rows: list[Any], value: float) -> float:
    """The ratio of a ``[from, ratio, inclusive]`` band table at ``value``."""
    found = rows[0][1]
    for bound, ratio, inclusive in rows:
        if value > bound or (inclusive and value >= bound):
            found = ratio
    return found


def concrete_row(kind: str) -> Any | None:
    """The foundation concrete table's row of a pile kind (bored and cast-in-place piles the
    cast-in-situ row)."""
    found = rules()
    if found is None:
        return None
    key = "driven" if kind == "driven" else "bored"
    return next((r for r in found.concrete if r.id == key), None)


def least_fc(kind: str, hard_driving: bool = False) -> tuple[float, str]:
    """The least f'c [MPa] of a pile kind and where it comes from: the larger of the kind's
    section rule and the foundation concrete table."""
    found = rules()
    if found is None:
        return 0.0, ""
    row = concrete_row(kind)
    table = row.fc if row is not None else 0.0
    if kind == "driven":
        rule = found.driven.hardFc if hard_driving else found.driven.minFc
        source = cite("detailing.driven")
    else:
        rule = found.bored.minFc
        source = cite("detailing.bored")
    value = max(rule, table)
    where = f"{source}; {cite('detailing.concrete')}" if table else source
    note = f"the larger of {rule:g} MPa and the table's {table:g} MPa ({where})"
    if kind == "driven" and hard_driving:
        note = f"hard driving: {note}"
    return value, note


def _steel(reinforcement: Any) -> tuple[int, float, float]:
    """Number of bars, their area [mm²] and the least bar diameter [mm]."""
    groups = getattr(reinforcement, "longitudinal", None) or []
    count = sum(g.count for g in groups)
    area = sum(g.count * math.pi * g.dia**2 / 4 for g in groups)
    least = min((g.dia for g in groups), default=0.0)
    return count, area, least


def guidance_note(diameter: float) -> str | None:
    """The pack's build-ability guidance for a bored pile of this diameter [mm]."""
    found = rules()
    if found is None or not found.bored.guidance:
        return None
    rows = sorted(found.bored.guidance, key=lambda r: r.diameter)
    row = next((r for r in rows if diameter <= r.diameter + 1e-6), rows[-1])
    return (
        f"guidance for a Ø{diameter:.0f} bored pile in compression only (fy "
        f"{found.bored.guidanceFy:g}): {row.count}Ø{row.bar:g}, hoops Ø{row.hoop:g} @ "
        f"{row.pitch:g}, to at least {found.bored.reinforcedDepth / 1e3:g} m below the cut-off "
        f"({cite('detailing.bored.guidance')}); not for piles in tension or bending, or in "
        "very soft soil"
    )


def recommended_mix(diameter: float, placement: str) -> str | None:
    """The pack's recommended mix of a bored pile by placement and diameter."""
    found = rules()
    if found is None or not found.bored.mixes:
        return None
    mixes = {m.id: m for m in found.bored.mixes}
    ordered = sorted(found.bored.mixes, key=lambda m: m.slump)
    if placement == "submerged":
        mix = ordered[-1]
    elif diameter < found.bored.largeDiameter and len(ordered) > 1:
        mix = ordered[1]
    else:
        mix = ordered[0]
    mix = mixes.get(mix.id, mix)
    cement = found.bored.cement.get(placement)
    return (
        f"concrete: mix {mix.id}, slump {mix.slump:g} mm ({mix.use}); cement at least "
        f"{cement:g} kg/m³, w/c {found.bored.waterCement:g} ({cite('detailing.bored')})"
    )


def detailing_checks(
    pile_type: Any,
    fc: float,
    fy: float,
    *,
    composition: Any = None,
    corrosive: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The detailing checks of a pile type (see the module notes): ``fc`` its concrete's f'c,
    ``fy`` its bars', ``composition`` the concrete material's mix (cement and w/c where it
    gives them), ``corrosive`` why the site is corrosive (empty: it is not). Returns
    ``(checks, notes)``."""
    from saengine.design.check import _check

    found = rules()
    if found is None:
        return [], [not_covered()]
    kind = pile_type.kind
    d = float(pile_type.diameter)
    length = float(pile_type.length)
    reinforcement = pile_type.reinforcement
    count, steel, least_bar = _steel(reinforcement)
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    fc_min, fc_note = least_fc(kind, bool(getattr(pile_type, "hardDriving", False)))
    checks.append(_check("Pile concrete grade", fc_min, fc, "MPa", None, f"least f'c: {fc_note}"))
    if kind == "bored":
        checks += _bored(found.bored, pile_type, d, fy, count, steel, least_bar, composition)
        guide = guidance_note(d)
        if guide:
            notes.append(guide)
        mix = recommended_mix(d, getattr(pile_type, "placement", "submerged"))
        if mix:
            notes.append(mix)
    elif kind == "driven":
        checks += _driven(found.driven, d, length, reinforcement, steel)
    else:
        checks += _cast_in_place(found.castInPlace, pile_type, d, reinforcement)
    cover = getattr(reinforcement, "cover", None)
    if corrosive:
        why = "; ".join(corrosive[:3])
        if reinforcement is not None and reinforcement.longitudinal and cover is not None:
            checks.append(
                _check(
                    "Pile cover, corrosive site",
                    found.corrosiveCover,
                    cover,
                    "mm",
                    None,
                    f"the site is corrosive ({why}): cover at least {found.corrosiveCover:g} mm "
                    f"({cite('detailing.corrosiveCover')})",
                )
            )
        notes.append(
            f"corrosive site ({why}): dense impermeable concrete, sulphate-resisting cement, the "
            "least covers and protective coatings for concrete piles; steel piles and shells "
            f"need protection ({cite('detailing.corrosiveCover')})"
        )
    return checks, notes


def _bored(
    rules_: Any,
    pile_type: Any,
    d: float,
    fy: float,
    count: int,
    steel: float,
    least_bar: float,
    composition: Any,
) -> list[dict[str, Any]]:
    from saengine.design.check import _check

    source = cite("detailing.bored")
    checks = [
        _check(
            "Pile diameter",
            rules_.minDiameter,
            d,
            "mm",
            None,
            f"bored piles at least {rules_.minDiameter:g} mm ({source})",
        )
    ]
    step = rules_.diameterStep
    off = d % step
    if min(off, step - off) > 1e-6:
        checks.append(
            _check(
                "Pile diameter step",
                d,
                math.floor(d / step) * step,
                "mm",
                None,
                f"shafts are sized in {step:g} mm steps ({source}). Reported only",
                flag=True,
            )
        )
    area = math.pi * d * d / 4
    ratio = band_ratio(rules_.minSteel, area / 1e6)
    reinforcement = pile_type.reinforcement
    checks.append(
        _check(
            "Pile longitudinal steel",
            ratio * area,
            steel,
            "mm²",
            None,
            f"at least {100 * ratio:.3g} % of Ac = {area / 1e6:.3f} m² ({source}); provided "
            f"{100 * steel / area:.2f} %",
        )
    )
    if reinforcement is None or not reinforcement.longitudinal:
        return checks
    checks.append(
        _check(
            "Pile bars",
            rules_.minBars,
            count,
            "bars",
            None,
            f"at least {rules_.minBars} longitudinal bars ({source})",
        )
    )
    if d >= rules_.largeDiameter - 1e-6:
        checks.append(
            _check(
                "Pile bar size",
                rules_.largeMinBar,
                least_bar,
                "mm",
                None,
                f"bars at least Ø{rules_.largeMinBar:g} in piles of Ø{rules_.largeDiameter:g} "
                f"and more ({source})",
            )
        )
    checks.append(
        _check(
            "Pile bar grade",
            rules_.minFy,
            fy,
            "MPa",
            None,
            f"high-yield bars, fy at least {rules_.minFy:g} MPa ({source})",
        )
    )
    checks.append(
        _check(
            "Pile cover",
            rules_.cover,
            reinforcement.cover,
            "mm",
            None,
            f"least concrete cover to the cage {rules_.cover:g} mm ({source})",
        )
    )
    transverse = reinforcement.transverse
    if transverse is not None:
        spacings = [float(transverse.spacing)]
        if transverse.zone is not None:
            spacings.append(float(transverse.zone.spacing))
        checks.append(
            _check(
                "Pile hoop pitch",
                rules_.minHoopPitch,
                min(spacings),
                "mm",
                None,
                f"hoops not closer than {rules_.minHoopPitch:g} mm, so the concrete flows "
                f"({source})",
            )
        )
    cage = getattr(pile_type, "reinforcedLength", None)
    if cage is not None:
        need = rules_.reinforcedDepth
        why = f"{rules_.reinforcedDepth / 1e3:g} m below the cut-off"
        casing = getattr(pile_type, "casingDepth", None)
        if casing and casing + rules_.casingExtra > need:
            need = casing + rules_.casingExtra
            why = (
                f"{rules_.casingExtra / 1e3:g} m below the {casing / 1e3:g} m temporary casing "
                f"({cite('detailing.bored.casingExtra')})"
            )
        need = min(need, float(pile_type.length))
        checks.append(
            _check(
                "Pile cage length",
                need,
                cage,
                "mm",
                None,
                f"the bars at least {why} ({cite('detailing.bored.guidance')}); piles in "
                "tension or bending need them below the zone of bending too",
            )
        )
    checks += _mix_checks(rules_, getattr(pile_type, "placement", "submerged"), composition)
    return checks


def _mix_checks(rules_: Any, placement: str, composition: Any) -> list[dict[str, Any]]:
    """Cement content and water/cement ratio of the pile concrete, where the material's mix
    gives them."""
    from saengine.design.check import _check

    if composition is None:
        return []
    checks = []
    source = cite("detailing.bored")
    cement = getattr(composition, "cement", None)
    need = rules_.cement.get(placement)
    if cement is not None and need is not None:
        where = "in a dry bore" if placement == "dry" else "by tremie under water or slurry"
        checks.append(
            _check(
                "Pile concrete cement content",
                need,
                cement,
                "kg/m³",
                None,
                f"at least {need:g} kg/m³ placed {where} ({source}; {cite('detailing.concrete')})",
            )
        )
    wc = getattr(composition, "waterCement", None)
    water = getattr(composition, "water", None)
    if wc is None and water is not None and cement:
        wc = water / cement
    if wc is not None:
        checks.append(
            _check(
                "Pile concrete w/c",
                wc,
                rules_.waterCement,
                "",
                None,
                f"water/cement ratio {rules_.waterCement:g} recommended ({source}). Reported only",
                flag=True,
            )
        )
    return checks


def tie_volume_ratio(side: float, cover: float, dia: float, spacing: float) -> float:
    """Volume of square closed ties over the gross volume of a square pile of ``side``: one
    tie of perimeter 4 (B - 2 cover - dia) per ``spacing``."""
    if spacing <= 0:
        return 0.0
    perimeter = 4 * max(side - 2 * cover - dia, 0.0)
    return perimeter * math.pi * dia**2 / 4 / spacing / (side * side)


def _driven(
    rules_: Any, side: float, length: float, reinforcement: Any, steel: float
) -> list[dict[str, Any]]:
    from saengine.design.check import _check

    source = cite("detailing.driven")
    slenderness = length / side
    checks = [
        _check(
            "Precast pile slenderness L/B",
            slenderness,
            rules_.maxSlenderness,
            "",
            None,
            f"L/B at most {rules_.maxSlenderness:g} against whipping in handling, else a "
            f"segmental pile ({source})",
        )
    ]
    ratio = band_ratio(rules_.steelByLength, slenderness)
    gross = side * side
    checks.append(
        _check(
            "Precast pile bars",
            ratio * gross,
            steel,
            "mm²",
            None,
            f"at least {100 * ratio:.3g} % of the {side:.0f} mm square at L/B = "
            f"{slenderness:.1f} ({source}); provided {100 * steel / gross:.2f} %; its handling "
            "is checked separately",
        )
    )
    transverse = getattr(reinforcement, "transverse", None)
    if transverse is None:
        checks.append(
            _check(
                "Precast pile ties",
                rules_.minTie,
                0.0,
                "mm",
                None,
                f"ties of at least Ø{rules_.minTie:g} resist the driving stresses ({source})",
            )
        )
        return checks
    checks.append(
        _check(
            "Precast pile tie size",
            rules_.minTie,
            transverse.dia,
            "mm",
            None,
            f"ties at least Ø{rules_.minTie:g} ({source})",
        )
    )
    cover = float(reinforcement.cover)
    end_spacing = float(transverse.zone.spacing) if transverse.zone else float(transverse.spacing)
    for label, share, spacing, where in (
        ("ends", rules_.tieEnd, end_spacing, f"over {rules_.tieEndLength:g} B at each end"),
        ("body", rules_.tieBody, float(transverse.spacing), "in the body"),
    ):
        provided = tie_volume_ratio(side, cover, transverse.dia, spacing)
        checks.append(
            _check(
                f"Precast pile tie volume, {label}",
                100 * share,
                100 * provided,
                "%",
                None,
                f"Ø{transverse.dia:g} @ {spacing:g}: {100 * provided:.2f} % of the gross volume, "
                f"at least {100 * share:.2g} % {where} ({source}); the end zone spacing is the "
                "ties' zone spacing",
            )
        )
    return checks


def _cast_in_place(
    rules_: Any, pile_type: Any, d: float, reinforcement: Any
) -> list[dict[str, Any]]:
    from saengine.design.check import _check

    source = cite("detailing.castInPlace")
    tip = float(getattr(pile_type, "tipDiameter", None) or d)
    checks = [
        _check(
            "Cast-in-place pile butt area",
            rules_.minButtArea / 100,
            math.pi * d * d / 4 / 100,
            "cm²",
            None,
            f"at least {rules_.minButtArea / 100:g} cm² at the butt ({source})",
        ),
        _check(
            "Cast-in-place pile tip",
            rules_.minTip,
            tip,
            "mm",
            None,
            f"at least {rules_.minTip:g} mm at the tip ({source})",
        ),
    ]
    if reinforcement is not None and reinforcement.longitudinal:
        submerged = getattr(pile_type, "placement", "submerged") == "submerged"
        need = rules_.corrosiveCover if submerged else rules_.cover
        why = "concrete placed under water or slurry" if submerged else "cased or uncased sides"
        checks.append(
            _check(
                "Pile cover",
                need,
                reinforcement.cover,
                "mm",
                None,
                f"clear cover at least {need:g} mm, {why} ({source}); the bars to within 100 mm "
                "of the cap's edge",
            )
        )
    return checks
