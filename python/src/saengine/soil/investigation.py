"""Adequacy of the site investigation: the number, pattern, spacing and depth of the borings.

What the code pack asks for (``siteInvestigation.borings`` and ``.depth``; with BNBC 2020:
Part 6 Sec 3.4.4(viii)-(ix) and Sec 3.4.5) is checked against the soil report's boreholes for
the building and foundation of ``SoilReport.investigation`` (defaults: a large building on
spread footings, average stratification, the footing of the design options' subgrade width and
depth). Each check is a row ``{id, item, required, provided, status, clause}`` with status
``ok``, ``fail``, ``warning`` (a guideline the code words as "should", or a rule for large
areas) or ``notChecked`` (data missing, with why).

- **number**: at least the pack's least number for the building size;
- **pattern**: the borings not all in one line;
- **spacing**: the largest distance from a boring to its nearest neighbour within the pack's
  spacing for the building size and the stratification;
- **inside**: the share of the borings under the building (the footprint, else the plot);
- **depth** of each boring below the ground, the largest of: the bearing level plus the spread
  rule (2B for L ≤ 2B to 4B for L ≥ 5B, linear between), or the pile/shaft tip plus the larger
  of 6 m and 2 × the group dimension (none for end bearing on rock); the weathering depth and
  never less than 2 m;
- **deep borings**: for a large building, the pack's share of the borings (50 %) to 1.5 × the
  building width below the lowest part of the foundation;
- **rock core**: piles on rock 1.5 m at each boring; shafts the larger of 1.5 m, 3 diameters
  and 2 × the group dimension;
- **bedrock**: one boring to bedrock with 3 m of core, or well below the level of influence
  (taken as deeper than the deepest depth required above; a warning, as it is judgement);
- **geo-hazards**: the review of the pack's hazards (Sec 3.21): unreviewed hazards and
  significant ones (a detailed analysis is needed).

Lengths in the report are mm; the checks work in m.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from saengine.library.soil import GEO_HAZARDS, Investigation, SoilReport
from saengine.soil import code_data


def _row(
    id_: str, item: str, required: str, provided: str, status: str, clause: str, note: str = ""
) -> dict[str, Any]:
    out = {
        "id": id_,
        "item": item,
        "required": required,
        "provided": provided,
        "status": status,
        "clause": clause,
    }
    if note:
        out["note"] = note
    return out


def spread_depth_widths(spread: list[tuple[float, float]], b: float, l_: float) -> float:
    """Depth of exploration below a spread footing B × L in footing widths: the pack's
    (L/B, widths) points, linear between, constant beyond the ends."""
    ratio = max(b, l_) / min(b, l_)
    points = sorted(spread)
    if ratio <= points[0][0]:
        return points[0][1]
    for (r1, d1), (r2, d2) in itertools.pairwise(points):
        if ratio <= r2:
            return d1 + (d2 - d1) * (ratio - r1) / (r2 - r1)
    return points[-1][1]


def zone_widths(b: float, l_: float) -> float:
    """The exploration depth below a footing in footing widths by the pack in force (BNBC 2020
    Sec 3.4.5(i): 2 for L ≤ 2B, 4 for L ≥ 5B); 2 when the pack does not cover it."""
    table = code_data.table()
    if table is None:
        return 2.0
    return spread_depth_widths(table.depth.spread, b, l_)


def _footprint(
    report: SoilReport, inv: Investigation
) -> tuple[list[tuple[float, float]] | None, str]:
    if len(inv.footprint) >= 3:
        return [(float(x), float(y)) for x, y in inv.footprint], "the building footprint"
    from saengine.gis.plot import plot_ring

    ring, _ = plot_ring(report.site)
    if ring and len(ring) >= 3:
        return ring, "the plot (no building footprint entered)"
    return None, ""


def _least_width(ring: list[tuple[float, float]]) -> float:
    """Least plan dimension of a ring [mm]: the short side of its smallest rotated rectangle."""
    from shapely.geometry import Polygon

    rect = Polygon(ring).minimum_rotated_rectangle
    xs = list(rect.exterior.coords)
    sides = [math.dist(xs[i], xs[i + 1]) for i in range(len(xs) - 1)]
    return min(s for s in sides if s > 0) if any(s > 0 for s in sides) else 0.0


def _collinear(points: list[tuple[float, float]], tolerance: float = 1000.0) -> bool:
    """Whether the points lie (within ``tolerance`` mm) on one line."""
    if len(points) < 3:
        return True
    from shapely.geometry import MultiPoint

    hull = MultiPoint(points).minimum_rotated_rectangle
    if hull.geom_type != "Polygon":
        return True
    return _least_width(list(hull.exterior.coords)[:-1]) < tolerance


def _names(keys: list[str]) -> str:
    return ", ".join(GEO_HAZARDS.get(k, k) for k in keys)


def _m(mm: float) -> str:
    return f"{mm / 1e3:.1f} m"


def check(report: SoilReport) -> dict[str, Any]:
    """The adequacy checks of the report's boreholes: ``{covered, code, checks, required,
    basis, notes}``; ``covered`` False (with only the code's name) when the pack in force has
    no site investigation data."""
    table = code_data.table()
    if table is None:
        return {"covered": False, "code": code_data.code_name(), "checks": []}
    inv = report.investigation or Investigation()
    design = report.design
    borings, depth = table.borings, table.depth
    holes = report.boreholes
    checks: list[dict[str, Any]] = []
    notes: list[str] = []
    n = len(holes)
    size = inv.buildingSize

    # Number and pattern.
    need = borings.minimum.get(size)
    if need is not None:
        checks.append(
            _row(
                "number",
                "Number of borings",
                f"≥ {need} ({size} building)",
                str(n),
                "ok" if n >= need else "fail",
                borings.clause,
            )
        )
    points = [(b.x, b.y) for b in holes]
    if borings.notInOneLine:
        if n < 3:
            checks.append(
                _row(
                    "pattern",
                    "Pattern",
                    "not in one line",
                    f"{n} borings",
                    "fail" if n else "notChecked",
                    borings.clause,
                )
            )
        else:
            line = _collinear(points)
            checks.append(
                _row(
                    "pattern",
                    "Pattern",
                    "not in one line",
                    "in one line" if line else "spread over the site",
                    "fail" if line else "ok",
                    borings.clause,
                )
            )

    # Spacing: the largest distance from a boring to its nearest neighbour.
    limit = borings.spacing.get(size, {}).get(inv.stratification)
    if limit is not None:
        if n >= 2:
            nearest = [min(math.dist(p, q) for q in points if q is not p) for p in points]
            worst = max(nearest)
            checks.append(
                _row(
                    "spacing",
                    "Spacing of borings",
                    f"≤ {limit:g} m ({inv.stratification} strata, {size} building)",
                    f"largest {worst / 1e3:.1f} m to the nearest boring",
                    "ok" if worst <= limit * 1e3 + 1e-6 else "fail",
                    borings.clause,
                )
            )
        else:
            checks.append(
                _row(
                    "spacing",
                    "Spacing of borings",
                    f"≤ {limit:g} m",
                    f"{n} boring",
                    "notChecked",
                    borings.clause,
                )
            )

    # Share of the borings under the building.
    ring, ring_how = _footprint(report, inv)
    if borings.insideFootprint is not None:
        if ring is None or n == 0:
            checks.append(
                _row(
                    "inside",
                    "Borings under the building",
                    f"≥ {borings.insideFootprint:.0%}",
                    "no footprint or plot",
                    "notChecked",
                    borings.clause,
                )
            )
        else:
            from shapely.geometry import Point, Polygon

            poly = Polygon(ring).buffer(1.0)
            inside = sum(1 for p in points if poly.contains(Point(p)))
            share = inside / n
            checks.append(
                _row(
                    "inside",
                    "Borings under the building",
                    f"≥ {borings.insideFootprint:.0%}",
                    f"{inside} of {n} ({share:.0%}) inside {ring_how}",
                    "ok" if share >= borings.insideFootprint - 1e-9 else "warning",
                    borings.clause,
                    borings.note,
                )
            )

    # Required depth below the ground [m].
    b = (inv.footingWidth or design.subgradeWidth) / 1e3
    l_ = (inv.footingLength or inv.footingWidth or design.subgradeWidth) / 1e3
    b, l_ = min(b, l_), max(b, l_)
    df = (inv.foundingDepth if inv.foundingDepth is not None else design.subgradeDepth) / 1e3
    required = []
    lowest = df
    if inv.foundation == "spread":
        widths = spread_depth_widths(depth.spread, b, l_)
        required.append(
            (
                df + widths * b,
                f"bearing level {df:g} m + {widths:.2f} × B {b:g} m (L/B {l_ / b:.2f})",
            )
        )
    elif inv.pileTipDepth is None:
        checks.append(
            _row(
                "depth",
                "Depth of borings",
                "below the pile tip",
                "no pile tip depth",
                "notChecked",
                depth.clause,
                "Enter the pile tip depth.",
            )
        )
    else:
        tip = inv.pileTipDepth / 1e3
        lowest = tip
        if inv.onRock:
            required.append((tip, f"tip {tip:g} m (end bearing on rock)"))
        else:
            below = depth.belowPileTip or 0.0
            group = (
                (depth.pileGroupWidths or 0.0) * inv.pileGroupWidth / 1e3
                if inv.pileGroupWidth is not None
                else 0.0
            )
            extra = max(below, group)
            text = (
                f"tip {tip:g} m + max({below:g} m, {depth.pileGroupWidths or 0:g} × group "
                f"{(inv.pileGroupWidth or 0) / 1e3:g} m)"
            )
            required.append((tip + extra, text))
    least = max(depth.minimum, (inv.weatheringDepth or 0) / 1e3)
    required.append((least, f"least depth {least:g} m"))
    need_depth, why = max(required, key=lambda r: r[0])
    if inv.foundation == "spread" or inv.pileTipDepth is not None:
        short = [h for h in holes if h.bottom / 1e3 < need_depth - 1e-6]
        checks.append(
            _row(
                "depth",
                "Depth of each boring",
                f"≥ {need_depth:.1f} m ({why})",
                (
                    "all reach it"
                    if not short and holes
                    else (", ".join(f"{h.id} {_m(h.bottom)}" for h in short) or "no borings")
                ),
                "ok" if holes and not short else "fail",
                depth.clause,
            )
        )

    # Large buildings: a share of the borings to 1.5 × the building width below the foundation.
    width = inv.buildingWidth / 1e3 if inv.buildingWidth else None
    width_how = "entered"
    if width is None and ring is not None:
        width, width_how = _least_width(ring) / 1e3, f"least dimension of {ring_how}"
    deep_need = None
    if size == "large" and depth.buildingWidthFactor is not None:
        if width is None:
            checks.append(
                _row(
                    "deepBorings",
                    "Deep borings",
                    f"{depth.buildingShare:.0%} to {depth.buildingWidthFactor:g} × building width",
                    "no building width or footprint",
                    "notChecked",
                    depth.clause,
                )
            )
        else:
            deep_need = lowest + depth.buildingWidthFactor * width
            deep = [h for h in holes if h.bottom / 1e3 >= deep_need - 1e-6]
            share = len(deep) / n if n else 0.0
            checks.append(
                _row(
                    "deepBorings",
                    "Deep borings",
                    f"{depth.buildingShare:.0%} to ≥ {deep_need:.1f} m ({depth.buildingWidthFactor:g}"
                    f" × width {width:.1f} m, {width_how}, below {lowest:g} m)",
                    f"{len(deep)} of {n} ({share:.0%})",
                    "ok" if n and share >= depth.buildingShare - 1e-9 else "fail",
                    depth.clause,
                )
            )

    # Rock cores.
    if inv.foundation != "spread" and inv.onRock:
        core = depth.rockCore or 0.0
        what = f"{core:g} m"
        if inv.foundation == "shaft":
            parts = [core]
            if inv.shaftDiameter and depth.shaftRockCoreDiameters:
                parts.append(depth.shaftRockCoreDiameters * inv.shaftDiameter / 1e3)
            if inv.pileGroupWidth and depth.shaftGroupRockCoreWidths:
                parts.append(depth.shaftGroupRockCoreWidths * inv.pileGroupWidth / 1e3)
            core = max(parts)
            what = f"{core:.2f} m (max of 1.5 m, diameters, group)"
        short = [h for h in holes if (h.rockCore or 0) / 1e3 < core - 1e-6]
        checks.append(
            _row(
                "rockCore",
                "Rock core at each boring",
                f"≥ {what}",
                (
                    "all have it"
                    if not short
                    else ", ".join(f"{h.id} {_m(h.rockCore or 0)}" for h in short)
                ),
                "ok" if holes and not short else "fail",
                depth.clause,
            )
        )

    # One boring to bedrock or well below the level of influence.
    if depth.bedrockCore is not None and holes:
        cored = [h for h in holes if (h.rockCore or 0) / 1e3 >= depth.bedrockCore - 1e-6]
        deepest = max(holes, key=lambda h: h.bottom)
        influence = max(need_depth, deep_need or 0.0)
        ok = bool(cored) or deepest.bottom / 1e3 > influence + 1e-6
        checks.append(
            _row(
                "bedrock",
                "One boring to bedrock or well below the influence",
                f"bedrock cored ≥ {depth.bedrockCore:g} m, or deeper than {influence:.1f} m",
                (
                    f"{cored[0].id} cored into rock"
                    if cored
                    else f"deepest {deepest.id} {_m(deepest.bottom)}"
                ),
                "ok" if ok else "warning",
                depth.clause,
            )
        )

    # Geo-hazard review.
    hazards = table.geoHazards
    if hazards is not None:
        review = inv.geoHazards
        missing = [h for h in hazards.items if h not in review]
        significant = [h for h in hazards.items if review.get(h) == "significant"]
        possible = [h for h in hazards.items if review.get(h) == "possible"]
        provided = (
            "significant: " + _names(significant)
            if significant
            else "possible: " + _names(possible)
            if possible
            else "none found"
            if not missing
            else "not reviewed: " + _names(missing)
        )
        status = "fail" if significant else "warning" if missing or possible else "ok"
        checks.append(
            _row(
                "geoHazards",
                "Geo-hazard review",
                "preliminary review of each hazard",
                provided,
                status,
                hazards.clause,
                "A significant hazard needs a detailed analysis." if significant else hazards.note,
            )
        )

    failed = [c["item"] for c in checks if c["status"] == "fail"]
    if failed:
        notes.append(
            f"Site investigation ({code_data.code_name()}): not adequate for "
            + ", ".join(c.lower() for c in failed)
            + "; see the site investigation checks."
        )
    return {
        "covered": True,
        "code": code_data.code_name(),
        "checks": checks,
        "requiredDepth": round(need_depth * 1e3),
        "basis": {
            "buildingSize": size,
            "stratification": inv.stratification,
            "foundation": inv.foundation,
            "footing": [round(b * 1e3), round(l_ * 1e3)],
            "foundingDepth": round(df * 1e3),
            "entered": report.investigation is not None,
        },
        "notes": notes,
    }
