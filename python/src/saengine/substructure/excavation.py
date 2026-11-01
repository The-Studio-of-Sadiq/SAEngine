"""Excavations and temporary works: the code pack's rules of excavation work, fills,
waterproofing and formwork (Part 9).

Every number and clause comes from the pack's ``construction`` table
(:class:`saengine.codes.tables.ConstructionTable`); a pack without it (or without one of its
groups) does not cover those checks, and the report says so. What is checked:

- an excavation (:class:`saengine.library.substructure.Excavation`):
  - its depth H from the adjacent ground to the deepest point;
  - the geotechnical engineer's check of a deep excavation, or one in soft or erratic soil (the
    soft clay of 1 Soil Report by the pack's site investigation criterion,
    :func:`saengine.soil.special_soils.soft_clay`);
  - the protection of its sides once H reaches the pack's depth: shored, sheeted or retained,
    else sloped (or stepped on average) no steeper than the pack's slope with steps no higher
    than its step height; a permanent excavation needs a retaining wall;
  - the guard rail along open sides, unless access is precluded or the sides are flat enough;
  - spoil, materials and equipment kept back by the surcharge zone (a multiple of H) unless the
    sides are sloped or sheeted and shored for them, and heavy machinery by its setback;
  - sheet piles standing above the ground;
  - the adjoining structures: a foundation at or above the bottom within the surcharge zone
    is underpinned (or protected), one below it is provided for; none within the pack's
    distance under a footing that is not underpinned; the notices, inspection and level
    readings they need;
  - the project's own foundations next to the outline (the same distance under a footing);
  - the ground water: dewatering below the water table, the uplift of an impervious layer at
    the base against its weight (its factor of safety the pack's, else the physical limit 1.0),
    and, with the pack's ``averageGradient`` method, the average seepage gradient round a
    cut-off against the critical gradient γ'/γw (reported only: the exit gradient at the toe is
    higher, so a flow net decides).
- the slab formwork (:class:`saengine.library.substructure.Formwork`): sheeting and joists in
  bending under the pack's load factor times the wet concrete and the workers, against the
  timber's allowable stress; the posts' height and diameter by kind; the standard sizes and
  their span and height limits (reported only);
- footings founded in fill and the waterproofing of below-grade walls and floors (notes);
- the general notes of the drawings (:func:`construction_notes`).

The design of embedded walls and their supports (sheet, contiguous and secant pile walls,
struts and anchors) is not here: the pack's rules give no method for it.

Units: mm and levels in mm (project datum) inside; kPa, kN/m³; depths of the soil in m.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design.check import _check
from saengine.substructure.earth_pressure import GAMMA_W

#: Supports whose sides are shored, sheeted or retained.
RETAINED = ("shored", "sheetPiles", "retainingWall")
#: Supports that may carry a surcharge inside the zone when designed for it.
DESIGNED_SIDES = ("sloped", "stepped", "shored", "sheetPiles", "retainingWall", "rock")


def table() -> Any | None:
    """The pack's ``construction`` table, or None when the pack does not cover it."""
    pack = code_context.current()
    if pack.has("construction"):
        return pack.table("construction")
    from saengine.codes.registry import DEFAULT_PACK

    if pack.id != DEFAULT_PACK:
        return None
    from saengine.codes.tables import builtin_table

    return builtin_table("construction", DEFAULT_PACK)


def group(name: str) -> Any | None:
    found = table()
    return None if found is None else getattr(found, name, None)


def code_name() -> str:
    pack = code_context.current()
    return pack.name or pack.id


def clause(group_name: str, key: str | None = None) -> str:
    """The clause of ``<group>.<key>`` (its ``sources``), else the group's clause."""
    found = group(group_name)
    if found is None:
        return ""
    if key and key in found.sources:
        return found.sources[key]
    return found.clause


def not_covered(what: str) -> str:
    return f"{what}: not covered by the code pack {code_name()}"


def _cite(text: str, group_name: str, key: str | None = None) -> str:
    where = clause(group_name, key)
    return f"{text} ({where})" if where else text


def _rule(name: str, ok: bool, note: str, flag: bool = False) -> dict[str, Any]:
    """A yes/no requirement as a check: utilisation 0 when met, 99 when not."""
    return _check(name, 0.0 if ok else 1.0, 1.0, "", None, note, flag, 0.0 if ok else 99.0)


def method_lines() -> list[str]:
    """The method lines of the report, from the pack."""
    lines: list[str] = []
    rules = group("excavation")
    if rules is not None:
        lines.append(
            f"Excavations: the rules of excavation work of {code_name()} ({rules.clause}): "
            "depth for a geotechnical engineer's check, protection of the sides, guard rail, "
            "surcharge zone and machinery setback, sheet piles above ground, adjoining "
            "structures (underpinning, notices, inspection and monitoring) and the ground "
            "water; the walls and supports themselves are not designed."
        )
    seepage = group("seepage")
    if seepage is not None:
        lines.append(
            f"Ground water at the base ({seepage.clause}): uplift of an impervious layer at the "
            "base against its weight; "
            + (
                "average seepage gradient round the cut-off against γ'/γw (reported only). "
                if seepage.method == "averageGradient"
                else ""
            )
            + (seepage.note or "")
        )
    formwork = group("formwork")
    if formwork is not None:
        lines.append(
            f"Formwork ({formwork.clause}): sheeting and joists as simply supported strips "
            "under the load factor times the wet concrete and the workers, against the "
            "timber's allowable bending stress; posts by kind; standard sizes reported only."
        )
    return lines


# ─────────────────────────────────────── soil ───────────────────────────────────────


def _behaviour(soil: Any, z: float) -> str | None:
    """'cohesive' or 'granular' of the layer at depth z of the soil report (None: assumed)."""
    profile = getattr(soil, "profile", None)
    if profile is None:
        return None
    for layer in profile.layers:
        if layer.top <= z < layer.bottom:
            return layer.behaviour
    return None


def soft_layers(soil: Any, depth: float) -> list[str]:
    """The soft clay layers the excavation to ``depth`` [m] passes through or stands on."""
    from saengine.soil.special_soils import soft_clay

    profile = getattr(soil, "profile", None)
    if profile is None:
        return []
    found = []
    for layer in profile.layers:
        if layer.top > depth:
            break
        try:
            soft = soft_clay(layer.behaviour, layer.n60, layer.cu)
        except Exception:  # noqa: BLE001 - a pack without the soft clay table
            soft = None
        if soft is not None:
            found.append(
                f"layer {layer.index + 1} ({soft['consistency']}: {', '.join(soft['by'])})"
            )
    return found


def base_uplift(soil: Any, depth: float, factor: float) -> dict[str, Any] | None:
    """The uplift of an impervious (cohesive) layer at the base of an excavation to ``depth``
    [m] by the water in a permeable layer under it: the weight of the soil between the base and
    the top of the permeable layer against the water pressure there (from the outside water
    table), as a check; None when it does not apply."""
    if soil.water_table is None or _behaviour(soil, depth + 1e-6) != "cohesive":
        return None
    profile = soil.profile
    below = [layer for layer in profile.layers if layer.top >= depth - 1e-9]
    below.sort(key=lambda layer: layer.top)
    top = None
    for layer in below:
        if layer.behaviour == "granular":
            top = layer.top
            break
    if top is None or top <= depth:
        return None
    u = GAMMA_W * max(top - soil.water_table, 0.0)
    if u <= 0:
        return None
    weight = 0.0
    steps = 20
    for k in range(steps):
        z = depth + (top - depth) * (k + 0.5) / steps
        layer = soil._layer(z)
        weight += layer[3] * (top - depth) / steps  # saturated: the clay plug under the water
    return _check(
        "Uplift of the base",
        u * factor,
        weight,
        "kPa",
        None,
        f"the clay from the base ({depth:.2f} m) to the permeable layer at {top:.2f} m weighs "
        f"{weight:.1f} kPa against the water pressure {u:.1f} kPa there"
        + (f" times {factor:g}" if factor != 1 else " (no factor of safety given: 1.0)")
        + "; lower the water in the permeable layer (relief wells) if it fails",
    )


def seepage_gradient(
    soil: Any, depth: float, embedment: float, factor: float
) -> dict[str, Any] | None:
    """The average gradient i = Δh / (Δh + 2 d) along the shortest flow path round a cut-off
    embedded ``embedment`` [m] below the base of an excavation to ``depth`` [m], the water
    lowered to the base inside, against the critical gradient γ'/γw of the soil at the base
    (reported only)."""
    if soil.water_table is None or depth <= soil.water_table or embedment <= 0:
        return None
    head = depth - soil.water_table
    i = head / (head + 2 * embedment)
    layer = soil._layer(depth + 1e-6)
    critical = (layer[3] - GAMMA_W) / GAMMA_W
    return _check(
        "Seepage gradient at the base",
        i * factor,
        critical,
        "",
        None,
        f"average i = Δh / (Δh + 2d) = {head:.2f} / ({head:.2f} + 2 × {embedment:.2f}) = "
        f"{i:.3f} against icr = γ'/γw = {critical:.3f}; the exit gradient at the toe is "
        "higher: confirm by a flow net. Reported only",
        flag=True,
    )


# ─────────────────────────────────────── excavations ───────────────────────────────────────


def _footprint(ctx: Any, foundation: Any) -> Any | None:
    """A foundation's plan outline (shapely), or None."""
    from shapely.geometry import LineString, Polygon

    try:
        if foundation.type == "raft" and foundation.outline:
            return Polygon(foundation.outline)
        if foundation.type == "strip" and foundation.path and foundation.width:
            return LineString(foundation.path).buffer(foundation.width / 2, cap_style="flat")
        if foundation.length and foundation.width:
            from saengine.library.substructure import cap_outline

            center = ctx.center(foundation)
            if foundation.center is None:
                foundation = foundation.model_copy(update={"center": [*map(float, center)]})
            return Polygon(cap_outline(foundation))
    except Exception:  # noqa: BLE001 - a foundation without a place is not checked here
        return None
    return None


def excavation_checks(
    excavation: Any,
    ground_level: float,
    soil: Any,
    foundations: list[tuple[str, float, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of one excavation and its requirements (texts). ``soil``: the
    :class:`~saengine.substructure.earth_pressure.Soil` at the excavation (depths below its
    adjacent ground); ``foundations``: the project's ``(id, underside level, plan outline)``
    to check against its outline."""
    rules = group("excavation")
    checks: list[dict[str, Any]] = []
    needs: list[str] = []
    if rules is None:
        return checks, [not_covered("The rules of excavation work")]
    ground = excavation.groundLevel if excavation.groundLevel is not None else ground_level
    depth = ground - excavation.bottomLevel
    if depth <= 0:
        return checks, ["its bottom is not below the adjacent ground: nothing to check"]
    support = excavation.support
    slope = excavation.sideSlope

    # A geotechnical engineer checks deep excavations and those in soft or erratic soil.
    soft = soft_layers(soil, depth / 1e3)
    if rules.geotechnicalDepth is not None:
        why = []
        if depth > rules.geotechnicalDepth:
            why.append(f"deeper than {rules.geotechnicalDepth / 1e3:g} m")
        if soft:
            why.append("in soft soil: " + "; ".join(soft))
        if excavation.erraticSoil:
            why.append("in erratic soil")
        checks.append(
            _check(
                "Depth for a geotechnical engineer's check",
                depth,
                rules.geotechnicalDepth,
                "mm",
                None,
                _cite(
                    "the design and construction are checked by a competent geotechnical "
                    "engineer" + (f": {', '.join(why)}" if why else " beyond this depth"),
                    "excavation",
                    "geotechnicalDepth",
                ),
                flag=True,
            )
        )
        if why:
            needs.append(
                _cite(
                    f"A competent geotechnical engineer checks its design and construction "
                    f"({', '.join(why)})",
                    "excavation",
                    "geotechnicalDepth",
                )
            )

    # Permanent excavations are retained.
    if excavation.permanent:
        checks.append(
            _rule(
                "Permanent excavation retained",
                support in ("retainingWall", "rock"),
                _cite(
                    "a permanent excavation has retaining walls of steel, masonry or reinforced "
                    "concrete for the embankment and its surcharge",
                    "excavation",
                    "permanent",
                ),
            )
        )

    # Protection of the sides.
    if rules.protectionDepth is not None and depth >= rules.protectionDepth and support != "rock":
        if support in RETAINED:
            needs.append(
                _cite(
                    "The shoring, sheeting or retaining structure resists the earth and "
                    "surcharge pressures; its design is checked by a qualified geotechnical "
                    "engineer; the sides are inspected after rainstorms",
                    "excavation",
                    "protectionDepth",
                )
            )
        elif support in ("sloped", "stepped") and rules.slopeHorizontal is not None:
            if slope is None:
                checks.append(
                    _rule(
                        "Side slope",
                        False,
                        "enter the side slope (horizontal per vertical) of the sloped sides",
                    )
                )
            else:
                checks.append(
                    _check(
                        "Side slope (V per H)"
                        + (", average of the steps" if support == "stepped" else ""),
                        1 / slope,
                        1 / rules.slopeHorizontal,
                        "",
                        None,
                        _cite(
                            f"1 : {slope:g} against at most 1 : {rules.slopeHorizontal:g} for "
                            f"sides {rules.protectionDepth / 1e3:g} m deep or deeper",
                            "excavation",
                            "slopeHorizontal",
                        ),
                    )
                )
            if support == "stepped" and rules.maxStepHeight is not None:
                height = excavation.stepHeight
                if height is None:
                    checks.append(_rule("Step height", False, "enter the height of the steps"))
                else:
                    checks.append(
                        _check(
                            "Step height",
                            height,
                            rules.maxStepHeight,
                            "mm",
                            None,
                            _cite("highest step of a stepped side", "excavation", "maxStepHeight"),
                        )
                    )
        else:
            checks.append(
                _check(
                    "Unsupported vertical sides",
                    depth,
                    rules.protectionDepth,
                    "mm",
                    None,
                    _cite(
                        f"sides {rules.protectionDepth / 1e3:g} m deep or deeper are shored, "
                        "braced and sheeted, sheet piled or retained, or sloped",
                        "excavation",
                        "protectionDepth",
                    ),
                )
            )

    # Guard rail.
    if rules.guardRailHeight is not None:
        exempt = excavation.accessPrecluded or (
            rules.guardRailSlopeExempt is not None
            and support in ("sloped", "stepped")
            and slope is not None
            and slope >= rules.guardRailSlopeExempt
        )
        checks.append(
            _rule(
                "Guard rail",
                excavation.guardRail or exempt,
                _cite(
                    f"a guard rail or solid enclosure at least {rules.guardRailHeight / 1e3:g} m "
                    "high along the open sides"
                    + (
                        f", unless access is precluded or the sides slope at 1 : "
                        f"{rules.guardRailSlopeExempt:g} or flatter"
                        if rules.guardRailSlopeExempt
                        else ""
                    ),
                    "excavation",
                    "guardRailHeight",
                ),
            )
        )

    # Sheet piles above the ground.
    if support == "sheetPiles" and rules.sheetPileProjection is not None:
        top = excavation.sheetPileTop
        if top is None:
            checks.append(
                _rule(
                    "Sheet piles above ground",
                    False,
                    "enter the height of the sheet piles above the natural ground",
                )
            )
        else:
            checks.append(
                _check(
                    "Sheet piles above ground",
                    rules.sheetPileProjection,
                    top,
                    "mm",
                    None,
                    _cite(
                        f"at least {rules.sheetPileProjection:g} mm above the natural ground",
                        "excavation",
                        "sheetPileProjection",
                    ),
                )
            )

    # Spoil, materials, equipment and machinery beside it.
    zone = None if rules.surchargeZone is None else rules.surchargeZone * depth
    setback = None
    if rules.machinerySetback is not None:
        setback = rules.machinerySetback * depth
        if rules.machinerySetbackMax is not None:
            setback = min(setback, rules.machinerySetbackMax)
    for k, load in enumerate(excavation.loads, 1):
        label = f"{load.kind} {k}"
        if zone is not None:
            designed = support in DESIGNED_SIDES
            pressure = f" ({load.pressure:g} kPa)" if load.pressure else ""
            checks.append(
                _check(
                    f"Surcharge zone: {label}",
                    zone,
                    max(load.distance, 1e-6),
                    "mm",
                    None,
                    _cite(
                        f"kept {rules.surchargeZone:g} × H = {zone / 1e3:.2f} m from the edge"
                        + (
                            f"; closer, the {support} sides must be designed for its load{pressure}"
                            if designed
                            else ""
                        ),
                        "excavation",
                        "surchargeZone",
                    ),
                    flag=designed,
                )
            )
        if load.kind == "machinery" and setback is not None:
            checks.append(
                _check(
                    f"Machinery setback: {label}",
                    setback,
                    max(load.distance, 1e-6),
                    "mm",
                    None,
                    _cite(
                        f"heavy machinery kept {rules.machinerySetback:g} × depth"
                        + (
                            f", at most {rules.machinerySetbackMax / 1e3:g} m"
                            if rules.machinerySetbackMax
                            else ""
                        )
                        + " from the edge",
                        "excavation",
                        "machinerySetback",
                    ),
                )
            )

    # Adjoining structures.
    notices = rules.notices
    for adj in excavation.adjoining:
        name = f"{adj.id}" + (f" ({adj.name})" if adj.name else "")
        close = zone is None or adj.distance < zone
        above = adj.foundingLevel >= excavation.bottomLevel
        if rules.underFooting is not None and above:
            within = adj.distance < rules.underFooting
            if within:
                checks.append(
                    _rule(
                        f"Under the footing of {adj.id}",
                        adj.underpinned,
                        _cite(
                            f"the excavation comes within {rules.underFooting:g} mm under its "
                            "foundation: underpin it or protect it against settlement first",
                            "excavation",
                            "underFooting",
                        ),
                    )
                )
        if close and above:
            checks.append(
                _rule(
                    f"Adjoining {adj.id} supported",
                    adj.underpinned,
                    _cite(
                        f"its foundation ({adj.foundingLevel / 1e3:.2f} m) is at or above the "
                        f"bottom ({excavation.bottomLevel / 1e3:.2f} m)"
                        + (f" within {zone / 1e3:.2f} m of the edge" if zone else "")
                        + ": its vertical load is carried by proper foundations, underpinning "
                        "or other equivalent means",
                        "excavation",
                        "adjoining",
                    ),
                )
            )
        elif close:
            needs.append(
                _cite(
                    f"{name}: its foundation is below the bottom: provide for the increased "
                    "vertical and lateral load the new construction puts on it",
                    "excavation",
                    "adjoining",
                )
            )
        if adj.otherProperty and close:
            days = notices.adjoiningDays
            needs.append(
                _cite(
                    f"{name}: written notice to its owner"
                    + (f" at least {days:g} days" if days else "")
                    + " before the excavation, with the protective measures; the Authority's "
                    "approval of them and the owner's written permission",
                    "excavation",
                    "adjoiningDays",
                )
            )
        if adj.sensitive and excavation.piling:
            needs.append(
                _cite(
                    f"{name}: tell-tales fixed on it to monitor it while piling is in progress",
                    "excavation",
                    "piling",
                )
            )
    if excavation.adjoining:
        if excavation.piling and notices.operationsHours:
            needs.append(
                _cite(
                    f"Written notice {notices.operationsHours:g} h before piling, compaction or "
                    "densification to the owners of the property it may affect",
                    "excavation",
                    "operationsHours",
                )
            )
        if notices.monitoringHours:
            needs.append(
                _cite(
                    "Where a potential hazard exists, the levels of the adjacent buildings are "
                    f"recorded at intervals of {notices.monitoringHours:g} h or less",
                    "excavation",
                    "monitoringHours",
                )
            )
        if rules.inspectionDepth is not None and depth >= rules.inspectionDepth:
            needs.append(
                _cite(
                    "Underpinning and the excavation's support of adjacent property under "
                    "controlled inspection; their details on the plans or shop drawings "
                    "approved by the engineer of the plans",
                    "excavation",
                    "inspectionDepth",
                )
            )

    # The project's own foundations next to the outline.
    if excavation.outline and foundations and rules.underFooting is not None:
        from shapely.geometry import Polygon

        pit = Polygon(excavation.outline)
        if pit.is_valid and pit.area > 0:
            for fid, underside, shape in foundations:
                if shape is None or underside < excavation.bottomLevel:
                    continue
                if pit.contains(shape):
                    continue
                gap = pit.distance(shape)
                if gap < rules.underFooting:
                    checks.append(
                        _check(
                            f"Clear of the footing {fid}",
                            rules.underFooting,
                            max(gap, 1e-6),
                            "mm",
                            None,
                            _cite(
                                f"the excavation's edge is {gap:.0f} mm from {fid}, whose "
                                f"underside ({underside / 1e3:.2f} m) is above its bottom: "
                                "underpin or protect it first, or keep clear",
                                "excavation",
                                "underFooting",
                            ),
                        )
                    )

    # Means of escape.
    if rules.escapeDepth is not None and depth > rules.escapeDepth:
        lux = (
            f"; lighting of at least {rules.nightLighting:g} lux at night"
            if rules.nightLighting
            else ""
        )
        needs.append(
            _cite(
                f"Ladders, ramps or other means of escape, and staging{lux}",
                "excavation",
                "escapeDepth",
            )
        )

    # Ground water.
    water = soil.water_table
    if water is not None and depth / 1e3 > water:
        needs.append(
            _cite(
                f"The bottom is {depth / 1e3 - water:.2f} m below the water table: drain and pump "
                "while it is open, with protective filters, drawing the water away from the "
                "excavation; investigate the effect of the lowering on adjacent foundations; "
                "a basement relying on the building's weight against flotation is pumped "
                "until that weight is in place",
                "excavation",
                "dewatering",
            )
        )
        if not excavation.dewatered:
            checks.append(
                _rule(
                    "Dewatering",
                    False,
                    _cite(
                        "the bottom is below the water table: plan dewatering or a cut-off "
                        "(tick 'dewatered' once planned)",
                        "excavation",
                        "dewatering",
                    ),
                )
            )
        seepage = group("seepage")
        if seepage is not None:
            factor = seepage.factorOfSafety or 1.0
            uplift = base_uplift(soil, depth / 1e3, factor)
            if uplift is not None:
                uplift["note"] = _cite(uplift["note"], "seepage")
                checks.append(uplift)
            if (
                seepage.method == "averageGradient"
                and excavation.cutoffLevel is not None
                and support in RETAINED
            ):
                embed = (excavation.bottomLevel - excavation.cutoffLevel) / 1e3
                found = seepage_gradient(soil, depth / 1e3, embed, factor)
                if found is not None:
                    found["note"] = _cite(found["note"], "seepage")
                    checks.append(found)
        else:
            needs.append(not_covered("The seepage checks at the base"))
    return checks, needs


def design_excavations(ctx: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The excavations of the substructure in the report's format, and notes."""
    from saengine.substructure.earth_pressure import soil_column
    from saengine.substructure.piles import profiles_of

    substructure = ctx.substructure
    if not substructure.excavations:
        return [], []
    profiles = profiles_of(ctx.soil_text)[0]
    own = []
    for f in substructure.foundations:
        own.append((f.id, ctx.founding_level(f), _footprint(ctx, f)))
    results: list[dict[str, Any]] = []
    notes: list[str] = []
    for excavation in substructure.excavations:
        if excavation.outline:
            from shapely.geometry import Polygon

            c = Polygon(excavation.outline).centroid
            x, y = c.x, c.y
        else:
            x, y = 0.0, 0.0
        water = excavation.designWaterTable
        if water is None:
            water = substructure.earthPressure.designWaterTable
        soil = soil_column(profiles, x, y, water)
        checks, needs = excavation_checks(excavation, ctx.ground_level, soil, own)
        ground = excavation.groundLevel if excavation.groundLevel is not None else ctx.ground_level
        counted = [c for c in checks if not c["flag"]]
        results.append(
            {
                "id": excavation.id,
                "type": "excavation",
                "columns": [],
                "checks": checks,
                "utilisation": max((c["utilisation"] for c in counted), default=0.0),
                "ok": all(c["ok"] for c in counted),
                "sizes": {"depth": round(ground - excavation.bottomLevel)},
                "requirements": needs,
                "soil": soil.source,
            }
        )
        notes += [f"{excavation.id}: {n}" for n in needs]
    return results, notes


# ─────────────────────────────────────── formwork ───────────────────────────────────────


def formwork_checks(
    formwork: Any, thickness: float, unit_weight: float | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """The checks of the slab formwork for a slab ``thickness`` [mm]; ``unit_weight``: the
    concrete's [kN/m³] (the pack's wet concrete weight when larger)."""
    rules = group("formwork")
    if rules is None:
        return [], [not_covered("The formwork checks")]
    checks: list[dict[str, Any]] = []
    needs: list[str] = []
    factor = rules.loadFactor or 1.0
    gamma = max(rules.concreteWeight or 0.0, unit_weight or 0.0)
    live = formwork.liveLoad
    if live is None:
        live = rules.liveLoad[1] if rules.liveLoad else 0.0
    w = factor * (gamma * thickness / 1e3 + live)  # kPa
    load_text = f"w = {factor:g} × ({gamma:g} × {thickness / 1e3:.3f} + {live:g}) = {w:.2f} kPa"
    allowable = rules.timberBending
    if allowable is not None:
        # Sheeting: a 1 m strip spanning between the joists.
        s = formwork.joistSpacing / 1e3
        m = w * s**2 / 8  # kN·m per m
        z = 1000 * formwork.sheeting**2 / 6  # mm³ per m
        checks.append(
            _check(
                "Sheeting bending",
                m * 1e6 / z * 1e3,
                allowable,
                "kPa",
                None,
                _cite(
                    f"{load_text}; M = w s²/8 over the joist spacing {formwork.joistSpacing:g} mm, "
                    f"sheeting {formwork.sheeting:g} mm",
                    "formwork",
                    "timberBending",
                ),
            )
        )
        line = w * s  # kN/m on a joist
        span = formwork.joistSpan / 1e3
        m = line * span**2 / 8
        z = formwork.joistWidth * formwork.joistDepth**2 / 6
        checks.append(
            _check(
                "Joist bending",
                m * 1e6 / z * 1e3,
                allowable,
                "kPa",
                None,
                _cite(
                    f"{line:.2f} kN/m on a {formwork.joistWidth:g} × {formwork.joistDepth:g} joist "
                    f"over {formwork.joistSpan:g} mm, M = w L²/8",
                    "formwork",
                    "timberBending",
                ),
            )
        )
    post = rules.posts.get(formwork.postKind)
    if post is not None:
        if post.maxHeight is not None:
            checks.append(
                _check(
                    f"{post.name} height",
                    formwork.postHeight,
                    post.maxHeight,
                    "mm",
                    None,
                    _cite(
                        f"{post.name.lower()}s up to {post.maxHeight / 1e3:g} m",
                        "formwork",
                        "posts",
                    ),
                )
            )
        if post.minDiameter is not None:
            if formwork.postDiameter is None:
                checks.append(_rule(f"{post.name} diameter", False, "enter the post diameter"))
            else:
                checks.append(
                    _check(
                        f"{post.name} diameter",
                        post.minDiameter,
                        formwork.postDiameter,
                        "mm",
                        None,
                        _cite(
                            f"at least {post.minDiameter:g} mm"
                            + (
                                f", spread to {post.topDiameter:g} mm at the top"
                                if post.topDiameter
                                else ""
                            )
                            + (f"; {post.note}" if post.note else ""),
                            "formwork",
                            "posts",
                        ),
                    )
                )
    sizes = {s.id: s for s in rules.sizes}
    for key, b, h in (
        ("sheeting", formwork.sheeting, formwork.sheeting),
        ("joist", formwork.joistWidth, formwork.joistDepth),
    ):
        size = sizes.get(key)
        if size is None:
            continue
        low = min(b, h) >= min(size.min) and max(b, h) >= max(size.min)
        high = size.max is None or (min(b, h) <= min(size.max) and max(b, h) <= max(size.max))
        checks.append(
            _rule(
                f"Standard size: {size.name.lower()}",
                low and high,
                _cite(
                    f"{b:g} × {h:g} against {size.min[0]:g} × {size.min[1]:g}"
                    + (f" to {size.max[0]:g} × {size.max[1]:g}" if size.max else "")
                    + " mm; outside the range, size by calculation. Reported only",
                    "formwork",
                    "sizes",
                ),
                flag=True,
            )
        )
    within = (rules.tableHeight is None or formwork.postHeight <= rules.tableHeight) and (
        rules.tableSpan is None or formwork.span is None or formwork.span <= rules.tableSpan
    )
    if not within:
        needs.append(
            _cite(
                "Beyond the standard sizes' span or height: formwork and supports sized by "
                "calculation and approved by the engineer before use",
                "formwork",
                "tableSpan",
            )
        )
    if rules.bracedPostHeight is not None and formwork.postHeight > rules.bracedPostHeight:
        needs.append(
            _cite(
                f"Posts higher than {rules.bracedPostHeight / 1e3:g} m braced horizontally and "
                "diagonally",
                "formwork",
                "bracedPostHeight",
            )
        )
    if rules.lateralBracingHeight is not None and formwork.postHeight > rules.lateralBracingHeight:
        needs.append(
            _cite(
                "All centering and props braced for lateral stability (floor height over "
                f"{rules.lateralBracingHeight / 1e3:g} m)",
                "formwork",
                "lateralBracingHeight",
            )
        )
    return checks, needs


def design_formwork(ctx: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The slab formwork of the substructure in the report's format, and notes."""
    formwork = ctx.substructure.formwork
    if formwork is None:
        return [], []
    thickness = formwork.slabThickness
    notes: list[str] = []
    if thickness is None:
        slabs = [
            float(o.thickness)
            for o in getattr(ctx.objects, "objects", [])
            if getattr(o, "kind", None) == "slab" and getattr(o, "thickness", None)
        ]
        if not slabs:
            return [], ["Formwork: enter the slab thickness (no slab type in 04 Objects)."]
        thickness = max(slabs)
        notes.append(f"Formwork: the thickest slab type of 04 Objects, {thickness:g} mm")
    unit_weight = None
    if formwork.material:
        try:
            density = ctx.concrete(formwork.material, "formwork").mechanical.density
        except Exception:  # noqa: BLE001 - an unknown material: the pack's weight
            density = None
        if density:
            unit_weight = density * 9.81 / 1e3
    checks, needs = formwork_checks(formwork, thickness, unit_weight)
    counted = [c for c in checks if not c["flag"]]
    return [
        {
            "id": "Formwork",
            "type": "formwork",
            "columns": [],
            "checks": checks,
            "utilisation": max((c["utilisation"] for c in counted), default=0.0),
            "ok": all(c["ok"] for c in counted),
            "sizes": {"thickness": thickness},
            "requirements": needs,
        }
    ], notes + [f"Formwork: {n}" for n in needs]


# ─────────────────────────────────────── fills and waterproofing ───────────────────────────────────────


def fill_notes(ctx: Any) -> list[str]:
    """Warnings for the foundations founded in fill (the soil report's fill layers)."""
    rules = group("fill")
    substructure = ctx.substructure
    shallow = [
        f for f in substructure.foundations if f.type in ("isolated", "combined", "strip", "raft")
    ]
    if rules is None or not shallow or not ctx.soil_text:
        return []
    from shapely.geometry import MultiPoint

    from saengine.substructure.piles import nearest_profile, profiles_of

    profiles = profiles_of(ctx.soil_text)[0]
    if not profiles:
        return []
    on_fill = []
    points = []
    for f in shallow:
        try:
            center = ctx.center(f)
        except Exception:  # noqa: BLE001, S112 - a foundation without a place
            continue
        points.append((float(center[0]), float(center[1])))
        profile, _ = nearest_profile(profiles, float(center[0]), float(center[1]))
        depth = (ctx.ground_level - ctx.founding_level(f)) / 1e3
        for layer in profile.layers:
            if layer.top <= depth < layer.bottom and layer.soil_type in rules.soilTypes:
                on_fill.append(f"{f.id} ({profile.id}, layer {layer.index + 1})")
                break
    if not on_fill:
        return []
    area = MultiPoint(points).convex_hull.area / 1e6 if len(points) >= 3 else 0.0
    pits = ""
    if rules.testPitArea and area > 0:
        count = max(1, math.ceil(area / rules.testPitArea))
        pits = (
            f"; in an uncontrolled fill at least {count} test pit(s) (one per "
            f"{rules.testPitArea:g} m² of the {area:.0f} m² under the foundations)"
            + (
                f", {rules.testPitDepth / 1e3:g} m below the foundations"
                if rules.testPitDepth
                else ""
            )
        )
    spec = []
    if rules.compaction:
        spec.append(
            f"compacted to {rules.compaction * 100:g}% of {rules.compactionTest or 'the laboratory maximum'}"
        )
    if rules.maxLift:
        spec.append(f"in layers of at most {rules.maxLift:g} mm")
    if rules.maxParticle:
        spec.append(f"no particle over {rules.maxParticle:g} mm")
    return [
        _cite(
            f"Founded in fill: {', '.join(on_fill)}. Not on loosely filled ground of non-uniform "
            "density unless the ground is improved; a controlled fill " + ", ".join(spec) + pits,
            "fill",
            "footingsOnFill",
        )
    ]


def _below_grade(ctx: Any) -> float | None:
    """Depth [m] of the lowest below-grade floor: basement walls' and permanent excavations'."""
    s = ctx.substructure
    levels = [w.foundingLevel for w in s.retainingWalls if w.kind == "basement"]
    levels += [e.bottomLevel for e in s.excavations if e.permanent]
    if not levels:
        return None
    return (ctx.ground_level - min(levels)) / 1e3


def waterproofing_notes(ctx: Any) -> list[str]:
    """What the below-grade walls and floors need: waterproofing where the water table rises
    above the lowest floor (hydrostatic pressure), else damp-proofing and a perimeter drain."""
    rules = group("waterproofing")
    depth = _below_grade(ctx)
    if rules is None or depth is None:
        return []
    from saengine.substructure.earth_pressure import soil_column
    from saengine.substructure.piles import profiles_of

    profiles = profiles_of(ctx.soil_text)[0]
    soil = soil_column(profiles, 0.0, 0.0, ctx.substructure.earthPressure.designWaterTable)
    water = soil.water_table
    if water is not None and water < depth:
        return [
            _cite(
                f"Below-grade walls and floors under hydrostatic pressure (water table "
                f"{water:.2f} m, lowest floor {depth:.2f} m): waterproof them"
                + waterproofing_spec(rules),
                "waterproofing",
                "hydrostatic",
            )
        ]
    return [
        _cite(
            "Below-grade walls and floors above the water table: damp-proof them"
            + damp_proofing_spec(rules),
            "waterproofing",
            "hydrostatic",
        )
    ]


def waterproofing_spec(rules: Any) -> str:
    parts = []
    if rules.membrane:
        parts.append(f"membrane at least {rules.membrane:g} mm under the floor and on the walls")
    if rules.lap:
        parts.append(f"joints lapped {rules.lap:g} mm and sealed")
    if rules.aboveWaterTable:
        parts.append(
            f"walls from {rules.aboveWaterTable:g} mm above the highest water table down to the "
            "foundation"
            + (
                f", damp-proofed above to {rules.dampAboveGrade:g} mm over grade"
                if rules.dampAboveGrade
                else ""
            )
        )
    if rules.pargeting:
        parts.append(f"masonry walls pargeted with {rules.pargeting:g} mm of cement mortar")
    return (": " + "; ".join(parts)) if parts else ""


def damp_proofing_spec(rules: Any) -> str:
    parts = []
    if rules.dampAboveGrade:
        parts.append(f"walls from {rules.dampAboveGrade:g} mm above grade down to the foundation")
    if rules.floorBase:
        fines = (
            f" with at most {rules.finesPassing * 100:g}% passing 4.75 mm"
            if rules.finesPassing
            else ""
        )
        parts.append(
            f"a {rules.floorBase:g} mm gravel or crushed stone base under the floor{fines}"
        )
    if rules.drainBeyond:
        parts.append(
            f"a perimeter drain {rules.drainBeyond:g} mm beyond the foundation's edge"
            + (
                f", its top {rules.drainAboveFoundation:g} mm above the foundation"
                if rules.drainAboveFoundation
                else ""
            )
        )
    if rules.gradingSlope and rules.gradingDistance:
        parts.append(
            f"ground sloped away at 1 : {rules.gradingSlope:g} for {rules.gradingDistance / 1e3:g} m"
        )
    return (": " + "; ".join(parts)) if parts else ""


# ─────────────────────────────────────── drawing notes ───────────────────────────────────────


def construction_notes(substructure: Any | None) -> list[str]:
    """The general notes of the drawings from the pack's construction rules: earthwork and
    excavation (when the substructure has foundations or excavations), fills, waterproofing
    (with basement walls or permanent excavations) and formwork."""
    found = table()
    if found is None:
        return []
    notes: list[str] = []
    has_ground = substructure is not None and (
        substructure.foundations or substructure.excavations or substructure.retainingWalls
    )
    ex = found.excavation
    if ex is not None and has_ground:
        text = []
        if ex.underFooting:
            text.append(
                f"no excavation within {ex.underFooting:g} mm under a footing that is not "
                "underpinned"
            )
        if ex.protectionDepth:
            slope = (
                f" or sloped no steeper than 1 : {ex.slopeHorizontal:g}"
                if ex.slopeHorizontal
                else ""
            )
            steps = (
                f" (steps at most {ex.maxStepHeight / 1e3:g} m high)" if ex.maxStepHeight else ""
            )
            text.append(
                f"sides {ex.protectionDepth / 1e3:g} m deep or deeper shored, sheeted or "
                f"retained{slope}{steps}"
            )
        if ex.guardRailHeight:
            text.append(f"guard rail at least {ex.guardRailHeight / 1e3:g} m high along open sides")
        if ex.surchargeZone:
            text.append(
                f"spoil, materials and equipment kept {ex.surchargeZone:g} × the depth from the "
                "edge"
            )
        if ex.machinerySetback:
            cap = f", at most {ex.machinerySetbackMax / 1e3:g} m" if ex.machinerySetbackMax else ""
            text.append(f"heavy machinery {ex.machinerySetback:g} × the depth{cap}")
        if ex.sheetPileProjection:
            text.append(f"sheet piles at least {ex.sheetPileProjection:g} mm above ground")
        if ex.geotechnicalDepth:
            text.append(
                f"excavations deeper than {ex.geotechnicalDepth / 1e3:g} m or in soft or erratic "
                "soil checked by a geotechnical engineer"
            )
        text.append("excavations drained and dewatered as long as they are open")
        notes.append("Excavation: " + "; ".join(text) + f" ({ex.clause}).")
    fill = found.fill
    if fill is not None and has_ground:
        text = [
            "backfill free of organic matter, debris and large rocks, placed in compacted lifts"
        ]
        if fill.compaction:
            text.append(
                f"fill under foundations compacted to {fill.compaction * 100:g}% of "
                f"{fill.compactionTest or 'the laboratory maximum dry density'}"
                + (f" in layers of at most {fill.maxLift:g} mm" if fill.maxLift else "")
            )
        if fill.maxParticle:
            text.append(f"no particle over {fill.maxParticle:g} mm")
        text.append("in-situ density tested in each layer before the next")
        notes.append("Fill: " + "; ".join(text) + f" ({fill.clause}).")
    wp = found.waterproofing
    below = substructure is not None and (
        any(w.kind == "basement" for w in substructure.retainingWalls)
        or any(e.permanent for e in substructure.excavations)
    )
    if wp is not None and below:
        notes.append(
            "Waterproofing: under hydrostatic pressure"
            + waterproofing_spec(wp)
            + ". Otherwise damp-proofing"
            + damp_proofing_spec(wp)
            + f" ({wp.clause})."
        )
    fw = found.formwork
    if fw is not None:
        text = []
        if fw.loadFactor:
            load = []
            if fw.concreteWeight:
                load.append(f"wet concrete {fw.concreteWeight:g} kN/m³")
            if fw.liveLoad:
                load.append(f"workers {fw.liveLoad[0]:g}-{fw.liveLoad[1]:g} kPa")
            text.append(
                f"formwork and scaffolds carry {fw.loadFactor:g} × the load"
                + (f" ({', '.join(load)})" if load else "")
            )
        if fw.timberBending:
            text.append(f"soft timber bending stress at most {fw.timberBending / 1e3:g} MPa")
        if fw.camber:
            cant = f", cantilevers 1 in {fw.cantileverCamber:g}" if fw.cantileverCamber else ""
            text.append(f"camber of beams and slabs 1 in {fw.camber:g}{cant}")
        for post in fw.posts.values():
            if post.maxHeight and post.minDiameter:
                text.append(
                    f"{post.name.lower()}s at least {post.minDiameter:g} mm, up to "
                    f"{post.maxHeight / 1e3:g} m high"
                )
        if fw.bracedPostHeight:
            text.append(f"posts over {fw.bracedPostHeight / 1e3:g} m braced")
        notes.append("Formwork: " + "; ".join(text) + f" ({fw.clause}).")
    return notes
