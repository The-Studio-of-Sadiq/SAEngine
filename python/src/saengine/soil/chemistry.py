"""Soil chemistry: the ground's aggression to buried concrete and steel.

Every limit, band and score is the code pack's (``siteInvestigation``, :mod:`saengine.soil.
code_data`); with the BNBC 2020 pack:

- **sulphate exposure** of concrete (Table 6.5.2): the class by water-soluble SO4 in the soil
  [% by weight] or in the ground water [ppm], the most severe of the two, with its cement and
  largest water-cement ratio; calcium chloride is not used in the severe classes (Sec 5.5.2.2);
- **corrosive site** for structural elements (Sec 3.10.1.29): chloride ≥ 500 ppm, sulphate
  ≥ 2000 ppm or pH < 6 in the soil or the water; and the pH bands at which steel piles corrode
  faster (fill below 5.5, extremely acid below 4.5, strongly alkaline above 9.1);
- **soil corrosivity** for buried steel (Tables 6.3.6a-b): the sum of the scores of the soil
  composition, ground water, resistivity, moisture, pH, sulphide, carbonate, chloride, sulphate
  and cinder/coke, and its rating; a parameter not tested scores 0 and is listed as missing;
- **chloride exposure** of concrete (Sec 5.5.1.2): where the site is corrosive by its chloride
  the ground is taken as brackish (SAEngine practice, as the pack's note says): w/c ≤ 0.40, or
  0.45 with 12 mm more cover; concrete below the water table w/c ≤ 0.50 (Sec 5.5.1.1).

:func:`concrete_requirement` merges these into what the foundation concrete must meet; the
substructure design links to it (:func:`foundation_concrete`).

Units: soil sulphate and chloride are entered in % by mass (1 % = 10 000 mg/kg = 10 000 ppm),
water in mg/L (ppm).
"""

from __future__ import annotations

from typing import Any

from saengine.library.soil import Borehole, Sample, SoilReport
from saengine.soil import code_data

#: mg/kg (ppm) in one percent by mass.
PPM_PER_PERCENT = 10_000.0


def _ppm(percent: float | None) -> float | None:
    return None if percent is None else percent * PPM_PER_PERCENT


# ─────────────────────────────── sulphate ───────────────────────────────


def sulphate_class(sample: Sample) -> dict[str, Any] | None:
    """The sulphate exposure class of concrete in contact with the sample's soil or water:
    ``{id, name, cement, maxWaterCement, noCalciumChloride, by, clause}``; None without a
    sulphate test or without the pack's table."""
    chem = sample.chemistry
    table = code_data.table()
    if chem is None or table is None or table.sulphate is None:
        return None
    if chem.sulphateSoil is None and chem.sulphateWater is None:
        return None
    worst, by = table.sulphate.classes[0], ""
    for row in table.sulphate.classes:
        for value, bound, what in (
            (chem.sulphateSoil, row.soilMin, f"SO4 {chem.sulphateSoil:g} % in the soil"
             if chem.sulphateSoil is not None else ""),
            (chem.sulphateWater, row.waterMin, f"SO4 {chem.sulphateWater:g} ppm in the water"
             if chem.sulphateWater is not None else ""),
        ):  # fmt: skip
            if value is None:
                continue
            hit = value > bound if row.exclusive else value >= bound
            if hit and bound > 0:
                worst, by = row, what
    return {
        "id": worst.id,
        "name": worst.name,
        "cement": worst.cement,
        "maxWaterCement": worst.maxWaterCement,
        "noCalciumChloride": worst.noCalciumChloride,
        "by": by,
        "clause": table.sulphate.clause,
    }


def _class_rank(class_id: str | None) -> int:
    table = code_data.table()
    if class_id is None or table is None or table.sulphate is None:
        return -1
    ids = [row.id for row in table.sulphate.classes]
    return ids.index(class_id) if class_id in ids else -1


# ─────────────────────────────── corrosive site ───────────────────────────────


def corrosive_site(sample: Sample) -> list[str]:
    """Why the sample makes the site corrosive for structural elements (empty: it does not)."""
    chem = sample.chemistry
    table = code_data.table()
    if chem is None or table is None or table.corrosiveSite is None:
        return []
    limits = table.corrosiveSite
    reasons = []
    for name, soil, water, limit in (
        ("chloride", _ppm(chem.chlorideSoil), chem.chlorideWater, limits.chloride),
        ("sulphate", _ppm(chem.sulphateSoil), chem.sulphateWater, limits.sulphate),
    ):
        for where, value in (("soil", soil), ("water", water)):
            if value is not None and value >= limit:
                reasons.append(f"{name} {value:g} ppm in the {where} ≥ {limit:g} ppm")
    if chem.pH is not None and chem.pH < limits.pHBelow:
        reasons.append(f"pH {chem.pH:g} < {limits.pHBelow:g}")
    return reasons


def steel_pile_notes(sample: Sample) -> list[str]:
    """The pH bands at which steel piles lose more to corrosion."""
    chem = sample.chemistry
    table = code_data.table()
    if chem is None or chem.pH is None or table is None or table.corrosiveSite is None:
        return []
    bands = table.corrosiveSite.steelPile
    clause = table.corrosiveSite.clause
    ph = chem.pH
    if "extremeAcidBelow" in bands and ph < bands["extremeAcidBelow"]:
        return [f"pH {ph:g}: extremely acid soil, high corrosion loss of steel piles ({clause})"]
    if "fillAcidBelow" in bands and ph < bands["fillAcidBelow"]:
        return [f"pH {ph:g}: acidic ground, steel piles may corrode ({clause})"]
    if "strongAlkaliAbove" in bands and ph > bands["strongAlkaliAbove"]:
        return [f"pH {ph:g}: strongly alkaline soil, high corrosion loss of steel piles ({clause})"]
    return []


# ─────────────────────────────── corrosivity score ───────────────────────────────


def _composition(sample: Sample, uscs: str | None, soil_type: str | None) -> tuple[str | None, str]:
    chem = sample.chemistry
    table = code_data.table()
    if chem is not None and chem.soilComposition is not None:
        return chem.soilComposition, "entered"
    if table is None or table.corrosivity is None:
        return None, ""
    if uscs and uscs in table.corrosivity.compositionFromUscs:
        return table.corrosivity.compositionFromUscs[uscs], f"from the USCS group {uscs}"
    if soil_type and soil_type in table.corrosivity.compositionFromSoilType:
        return table.corrosivity.compositionFromSoilType[
            soil_type
        ], f"from the soil type {soil_type}"
    return None, ""


def corrosivity(
    sample: Sample,
    borehole: Borehole | None = None,
    uscs: str | None = None,
    soil_type: str | None = None,
) -> dict[str, Any] | None:
    """The soil corrosivity score of the sample: ``{score, rating, items, missing, clause}``,
    each item ``{parameter, value, score, how}``; None without chemistry or the pack's table."""
    chem = sample.chemistry
    table = code_data.table()
    if chem is None or table is None or table.corrosivity is None:
        return None
    scores = table.corrosivity.scores
    items: list[dict[str, Any]] = []
    missing: list[str] = []

    def by_category(parameter: str, value: str | None, how: str = "") -> None:
        rows = scores.get(parameter)
        if not isinstance(rows, dict):
            return
        if value is None or value not in rows:
            missing.append(parameter)
            return
        items.append({"parameter": parameter, "value": value, "score": rows[value], "how": how})

    def by_band(parameter: str, value: float | None, how: str = "") -> None:
        rows = scores.get(parameter)
        if not isinstance(rows, list):
            return
        if value is None:
            missing.append(parameter)
            return
        row = code_data.band(rows, value)
        if row is not None:
            items.append({"parameter": parameter, "value": round(value, 4), "score": row.score,
                          "how": how})  # fmt: skip

    composition, how = _composition(sample, uscs, soil_type)
    by_category("soilComposition", composition, how)
    water = chem.groundwater
    water_how = "entered"
    if water is None and borehole is not None:
        water = "exist" if borehole.waterTable is not None else "none"
        water_how = "from the borehole's water table (enter 'vary' for a seasonal one)"
    by_category("groundwater", water, water_how)
    by_band("resistivity", chem.resistivity)
    by_band("moisture", sample.moisture)
    by_band("pH", chem.pH)
    by_category("sulphide", chem.sulphide)
    by_band("carbonate", chem.carbonate)
    by_band("chloride", _ppm(chem.chlorideSoil), "mg/kg from % by mass")
    by_band("sulphate", _ppm(chem.sulphateSoil), "mg/kg from % by mass")
    cinder = None if chem.cinderCoke is None else ("exist" if chem.cinderCoke else "none")
    by_category("cinderCoke", cinder)
    if not items:
        return None
    score = sum(float(i["score"]) for i in items)
    rating = code_data.band(table.corrosivity.ratings, score)
    return {
        "score": score,
        "rating": rating.rating if rating is not None else None,
        "items": items,
        "missing": missing,
        "clause": table.corrosivity.clause,
    }


#: Corrosivity ratings, least severe first (for the worst of a site).
def _rating_rank(rating: str | None) -> int:
    table = code_data.table()
    if rating is None or table is None or table.corrosivity is None:
        return -1
    order = [r.rating for r in reversed(table.corrosivity.ratings)]
    return order.index(rating) if rating in order else -1


# ─────────────────────────────── flags of one sample ───────────────────────────────


def flags(sample: Sample) -> list[str]:
    """The durability notes of one sample's chemistry, with the pack's clauses."""
    chem = sample.chemistry
    if chem is None:
        return []
    table = code_data.table()
    if table is None:
        return [code_data.not_covered("Soil chemistry")]
    out = []
    sulphate = sulphate_class(sample)
    if sulphate is not None:
        if sulphate["maxWaterCement"] is None:
            out.append(f"sulphate: {sulphate['name']} exposure ({sulphate['clause']})")
        else:
            out.append(
                f"sulphate: {sulphate['name']} exposure by {sulphate['by']} "
                f"({sulphate['clause']}): cement {sulphate['cement']}, w/c ≤ "
                f"{sulphate['maxWaterCement']:g} for buried concrete"
                + ("; no calcium chloride admixture" if sulphate["noCalciumChloride"] else "")
            )
    reasons = corrosive_site(sample)
    if reasons and table.corrosiveSite is not None:
        out.append(
            f"corrosive site ({table.corrosiveSite.clause}): "
            + ", ".join(reasons)
            + "; protect steel piles (coating, cathodic protection or more steel) and use dense "
            "concrete"
        )
    chloride = _chloride_brackish(sample)
    if chloride and table.chloride is not None:
        c = table.chloride
        extra = (
            f", or {c.maxWaterCementExtraCover:g} with {c.extraCover:g} mm more cover"
            if c.maxWaterCementExtraCover is not None and c.extraCover is not None
            else ""
        )
        out.append(
            f"chloride {chloride}: reinforced concrete in brackish ground, w/c ≤ "
            f"{c.maxWaterCement:g}{extra} ({c.clause}; ground taken as brackish by its chloride: "
            "SAEngine practice)"
        )
    out += steel_pile_notes(sample)
    return out


def _chloride_brackish(sample: Sample) -> str | None:
    """The chloride that makes the ground brackish for the chloride exposure (the corrosive
    site's chloride limit), as text; None below it."""
    chem = sample.chemistry
    table = code_data.table()
    if chem is None or table is None or table.corrosiveSite is None:
        return None
    limit = table.corrosiveSite.chloride
    for where, value in (("soil", _ppm(chem.chlorideSoil)), ("water", chem.chlorideWater)):
        if value is not None and value >= limit:
            return f"{value:g} ppm in the {where} (≥ {limit:g} ppm)"
    return None


# ─────────────────────────────── the site ───────────────────────────────


def concrete_requirement(samples: list[Sample], below_water: bool = False) -> dict[str, Any] | None:
    """What concrete in the ground must meet, from all the samples' chemistry: ``{maxWaterCement,
    cement, noCalciumChloride, sulphateClass, reasons}`` (the smallest w/c of the rules that
    apply); None when nothing applies or the pack has no table."""
    table = code_data.table()
    if table is None:
        return None
    wc: float | None = None
    cement = None
    no_cacl2 = False
    worst = None
    reasons: list[str] = []

    def limit(value: float | None, why: str) -> None:
        nonlocal wc
        if value is None:
            return
        reasons.append(why)
        wc = value if wc is None else min(wc, value)

    for sample in samples:
        sulphate = sulphate_class(sample)
        if sulphate is not None and _class_rank(sulphate["id"]) > _class_rank(
            worst and worst["id"]
        ):
            worst = sulphate
    if worst is not None and worst["maxWaterCement"] is not None:
        limit(
            worst["maxWaterCement"],
            f"{worst['name']} sulphate exposure by {worst['by']} ({worst['clause']})",
        )
        cement = worst["cement"]
        no_cacl2 = worst["noCalciumChloride"]
    if table.chloride is not None:
        brackish = next((c for c in map(_chloride_brackish, samples) if c), None)
        if brackish:
            limit(
                table.chloride.maxWaterCement,
                f"chloride {brackish}, taken as brackish (SAEngine practice; {table.chloride.clause})",
            )
        if below_water and table.chloride.lowPermeabilityWaterCement is not None:
            limit(
                table.chloride.lowPermeabilityWaterCement,
                f"concrete below the water table (SAEngine practice; {table.chloride.clause})",
            )
    if wc is None:
        return None
    c = table.chloride
    return {
        "maxWaterCement": wc,
        "cement": cement,
        "noCalciumChloride": no_cacl2,
        "sulphateClass": worst["name"] if worst else None,
        "extraCoverOption": (
            {"maxWaterCement": c.maxWaterCementExtraCover, "extraCover": c.extraCover}
            if c is not None
            and c.maxWaterCementExtraCover is not None
            and any(_chloride_brackish(s) for s in samples)
            and wc >= c.maxWaterCement
            else None
        ),
        "reasons": reasons,
    }


def requirement_text(req: dict[str, Any]) -> str:
    """One line for the notes: what the foundation concrete must meet."""
    text = f"Concrete in the ground: w/c ≤ {req['maxWaterCement']:g}"
    if req.get("cement"):
        text += f", cement {req['cement']}"
    if req.get("noCalciumChloride"):
        text += ", no calcium chloride admixture"
    option = req.get("extraCoverOption")
    if option:
        text += (
            f" (w/c {option['maxWaterCement']:g} allowed with {option['extraCover']:g} mm more "
            "cover)"
        )
    return text + " — " + "; ".join(req["reasons"]) + "."


def site(
    report: SoilReport,
    uscs_of: dict[tuple[str, int], str | None] | None = None,
    soil_type_of: dict[tuple[str, int], str | None] | None = None,
) -> dict[str, Any]:
    """The site's chemistry: per sample (``samples``), the worst sulphate class and
    corrosivity rating, whether the site is corrosive, the foundation concrete requirement and
    the pack's steel corrosion rates. ``uscs_of`` / ``soil_type_of`` give the USCS group and the
    layer soil type by (borehole id, sample index) for the corrosivity score."""
    table = code_data.table()
    if table is None:
        return {"covered": False, "code": code_data.code_name()}
    uscs_of = uscs_of or {}
    soil_type_of = soil_type_of or {}
    rows = []
    samples: list[Sample] = []
    below_water = water_at_foundation(report)
    worst_rating = None
    corrosive: list[str] = []
    for borehole in report.boreholes:
        for i, sample in enumerate(borehole.samples):
            if sample.chemistry is None:
                continue
            samples.append(sample)
            score = corrosivity(
                sample, borehole, uscs_of.get((borehole.id, i)), soil_type_of.get((borehole.id, i))
            )
            if score is not None and _rating_rank(score["rating"]) > _rating_rank(worst_rating):
                worst_rating = score["rating"]
            reasons = corrosive_site(sample)
            corrosive += [f"{borehole.id} {sample.number or f'{sample.depth:g} mm'}: {r}"
                          for r in reasons]  # fmt: skip
            rows.append(
                {
                    "borehole": borehole.id,
                    "sample": sample.number,
                    "depth": sample.depth,
                    "sulphate": sulphate_class(sample),
                    "corrosive": reasons,
                    "corrosivity": score,
                    "flags": flags(sample),
                }
            )
    requirement = concrete_requirement(samples, below_water)
    worst_sulphate = max(
        (r["sulphate"] for r in rows if r["sulphate"]),
        key=lambda s: _class_rank(s["id"]),
        default=None,
    )
    return {
        "covered": True,
        "code": code_data.code_name(),
        "samples": rows,
        "sulphateClass": worst_sulphate["name"] if worst_sulphate else None,
        "corrosivityRating": worst_rating,
        "corrosive": corrosive,
        "corrosiveClause": table.corrosiveSite.clause if table.corrosiveSite else None,
        "concrete": requirement,
        "steelCorrosion": {
            k: v for k, v in table.steelCorrosion.items() if isinstance(v, int | float)
        },
        "steelCorrosionClause": table.steelCorrosion.get("clause"),
    }


def foundation_concrete(soil_text: str | None) -> dict[str, Any] | None:
    """The foundation concrete requirement of the project's soil report (for the substructure
    design): :func:`concrete_requirement` over every sample with chemistry; None without one."""
    if not soil_text:
        return None
    from saengine.soil.report import parse

    report = parse(soil_text)
    if isinstance(report, list):
        return None
    samples = [s for b in report.boreholes for s in b.samples if s.chemistry is not None]
    return concrete_requirement(samples, water_at_foundation(report)) if samples else None


def water_at_foundation(report: SoilReport) -> bool:
    """Whether some borehole met the water table at or above the founding depth (the
    investigation's, else the subgrade founding depth of the design options)."""
    inv = report.investigation
    depth = (
        inv.pileTipDepth
        if inv is not None and inv.foundation != "spread" and inv.pileTipDepth
        else inv.foundingDepth
        if inv is not None and inv.foundingDepth is not None
        else report.design.subgradeDepth
    )
    return any(b.waterTable is not None and b.waterTable <= depth for b in report.boreholes)
