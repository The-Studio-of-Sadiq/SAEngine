"""Problem soils: organic, expansive, collapsible, dispersive and soft clays.

The criteria are the code pack's (``siteInvestigation``; the default pack: Sec 3.5.4-3.5.8,
Table 6.3.3, Eqs 6.3.1-6.3.5, Table 6.3.4 and Appendix E). Each function reads what the sample
has and returns None when it has nothing the criterion uses:

- **organic** (Table 6.3.3, Sec 3.5.4): the class by organic content (loss on ignition); peat
  from the pack's peat content;
- **expansive** (Appendix E): every criterion the sample has data for (USBR PI and shrinkage
  limit, linear shrinkage, free swell, free swell index, the IS liquid limit and PI, swelling
  potential, swelling pressure, volume change, the weighted PI = PI × % passing 425 µm), each
  read on its own; the most severe degree is the sample's, flagged from the pack's degree on;
- **collapsible** (Sec 3.5.6): e0 > ec = 0.85 eL + 0.15 eP (Eq 6.3.1, eL = wL Gs/100,
  eP = wP Gs/100); at Sr ≤ 0.6, (eL - e0)/(1 + e0) ≤ 0.10 (Eq 6.3.2); the collapse test's
  relative subsidence imc = (H - H')/H ≥ 0.02 (Eq 6.3.3);
- **dispersive** (Sec 3.5.7): the pinhole class (Table 6.3.4); the chemical screen pH > 7.8,
  then ESP = Na/CEC × 100 > 8 with ESP + EMgP > 15 (Eqs 6.3.4-6.3.5); ESP 7-10 moderately and
  above 15 seriously dispersive;
- **soft clay** (Sec 3.5.8): a cohesive layer with field N ≤ 4 or cu within 10-40 kPa; very
  soft below N 2 / cu 20 kPa.
"""

from __future__ import annotations

from typing import Any

from saengine.library.soil import Sample
from saengine.soil import code_data

#: kPa in one kg/cm² (Appendix E prints the swelling pressure in kg/cm²).
KPA_PER_KG_CM2 = 98.0665
#: The 425 µm sieve of the weighted plasticity index [mm].
SIEVE_425 = 0.425


def organic(sample: Sample) -> dict[str, Any] | None:
    """The organic class of the sample by its organic content: ``{class, label, organic, peat,
    clause}``; None without an organic content."""
    table = code_data.table()
    chem = sample.chemistry
    if table is None or table.organic is None or chem is None or chem.organicContent is None:
        return None
    oc = chem.organicContent
    rows = [row for row in table.organic.classes if oc >= row.min]
    row = rows[-1] if rows else table.organic.classes[0]
    return {
        "class": row.id,
        "label": row.label,
        "organicContent": oc,
        "organic": row.min > 0,
        "peat": oc >= table.organic.peat,
        "clause": table.organic.clause,
    }


def organic_group(sample: Sample, inorganic_symbol: str | None) -> dict[str, str] | None:
    """The organic USCS group (OL, OH, PT) when the sample's data make it organic: peat by
    organic content, OL/OH by the oven-dried liquid limit ratio (LL oven-dried / LL < pack
    ratio, ASTM D2487 as the code adopts it); None otherwise."""
    table = code_data.table()
    if table is None or table.organic is None:
        return None
    chem = sample.chemistry
    oc = chem.organicContent if chem is not None else None
    if oc is not None and oc >= table.organic.peat:
        return {
            "symbol": "PT",
            "name": "Peat",
            "basis": f"organic content {oc:g} % ≥ {table.organic.peat:g} %",
        }
    ll, dried = sample.liquidLimit, sample.liquidLimitOvenDried
    if ll is None or dried is None or ll <= 0:
        return None
    ratio = dried / ll
    if ratio >= table.organic.ovenDriedRatio:
        return None
    if inorganic_symbol is not None and not inorganic_symbol.startswith(("C", "M")):
        return None  # coarse soils keep their group; "with organic fines" is added to the name
    high = ll >= 50
    return {
        "symbol": "OH" if high else "OL",
        "name": "Organic clay or silt" + (" of high plasticity" if high else ""),
        "basis": f"LL oven-dried / LL = {ratio:.2f} < {table.organic.ovenDriedRatio:g}, LL {ll:g}",
    }


def _value(sample: Sample, parameter: str, grading: dict[str, Any] | None) -> float | None:
    if parameter == "plasticityIndex":
        if sample.liquidLimit is None or sample.plasticLimit is None:
            return 0.0 if sample.nonPlastic else None
        return max(0.0, sample.liquidLimit - sample.plasticLimit)
    if parameter == "swellingPressure":
        return None if sample.swellingPressure is None else sample.swellingPressure / KPA_PER_KG_CM2
    if parameter == "weightedPlasticityIndex":
        pi = _value(sample, "plasticityIndex", grading)
        passing = (grading or {}).get("passing425")
        return None if pi is None or passing is None else pi * passing
    value = getattr(sample, parameter, None)
    return None if value is None else float(value)


def expansive(sample: Sample, grading: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The degree of expansion of the sample by each criterion it has data for: ``{degree,
    expansive, criteria: [{id, parameter, value, unit, degree, source}], clause}``; None
    when it has none. ``grading`` is :func:`saengine.soil.lab.grading_summary` with
    ``passing425`` (for the weighted PI)."""
    table = code_data.table()
    if table is None or table.expansive is None:
        return None
    exp = table.expansive
    rows = []
    for criterion in exp.criteria:
        value = _value(sample, criterion.parameter, grading)
        if value is None:
            continue
        band = code_data.band(criterion.rows, value)
        if band is None:
            continue
        rows.append(
            {
                "id": criterion.id,
                "parameter": criterion.parameter,
                "value": round(value, 3),
                "unit": criterion.unit,
                "degree": band.degree,
                "source": criterion.source,
            }
        )
    # Only the liquid limit and PI are routine: without a swell test the soil is not judged
    # from them alone unless they reach the flag degree.
    if not rows:
        return None
    rank = {d: i for i, d in enumerate(exp.degrees)}
    worst = max(rows, key=lambda r: rank.get(r["degree"], -1))
    return {
        "degree": worst["degree"],
        "expansive": rank.get(worst["degree"], -1) >= rank.get(exp.flagFrom, len(rank)),
        "governing": worst["id"],
        "criteria": rows,
        "clause": exp.clause,
    }


def collapsible(sample: Sample) -> dict[str, Any] | None:
    """The collapse criteria the sample has data for: ``{collapsible, checks: [...], clause}``;
    None without the data of any."""
    table = code_data.table()
    if table is None or table.collapsible is None:
        return None
    col = table.collapsible
    checks: list[dict[str, Any]] = []
    gs, e0, w = sample.specificGravity, sample.e0, sample.moisture
    ll, pl = sample.liquidLimit, sample.plasticLimit
    if gs is not None and e0 is not None and ll is not None and pl is not None:
        e_l, e_p = ll * gs / 100, pl * gs / 100
        a = col.criticalVoidRatio.get("liquidLimit", 0.0)
        b = col.criticalVoidRatio.get("plasticLimit", 0.0)
        ec = a * e_l + b * e_p
        checks.append(
            {
                "check": "criticalVoidRatio",
                "text": f"e0 {e0:.3f} {'>' if e0 > ec else '≤'} ec = {a:g} eL + {b:g} eP = "
                f"{ec:.3f}",
                "collapsible": e0 > ec,
            }
        )
        if w is not None:
            sr = w * gs / 100 / e0
            if sr <= col.saturationMax:
                index = (e_l - e0) / (1 + e0)
                checks.append(
                    {
                        "check": "voidIndex",
                        "text": f"Sr {sr:.2f} ≤ {col.saturationMax:g}: (eL - e0)/(1 + e0) = "
                        f"{index:.3f} {'≤' if index <= col.voidIndexMax else '>'} "
                        f"{col.voidIndexMax:g}",
                        "collapsible": index <= col.voidIndexMax,
                    }
                )
    if sample.collapse is not None:
        h, h2 = sample.collapse.height, sample.collapse.soakedHeight
        imc = (h - h2) / h
        checks.append(
            {
                "check": "relativeSubsidence",
                "text": f"imc = (H - H')/H = {imc:.3f} "
                f"{'≥' if imc >= col.relativeSubsidence else '<'} {col.relativeSubsidence:g}",
                "collapsible": imc >= col.relativeSubsidence,
            }
        )
    if not checks:
        return None
    # The collapse test measures what the void ratio criteria predict: it decides when given.
    test = next((c for c in checks if c["check"] == "relativeSubsidence"), None)
    result = test["collapsible"] if test else any(c["collapsible"] for c in checks)
    return {"collapsible": result, "checks": checks, "clause": col.clause}


def dispersive(sample: Sample) -> dict[str, Any] | None:
    """The dispersion of the sample by the pinhole test or the exchangeable sodium:
    ``{class, checks, clause}`` with class dispersive, moderate, intermediate or
    nonDispersive; None without either test."""
    table = code_data.table()
    if table is None or table.dispersive is None:
        return None
    dis = table.dispersive
    checks = []
    kind = None
    if sample.pinhole is not None:
        kind = dis.pinhole.get(sample.pinhole)
        checks.append(f"pinhole class {sample.pinhole}: {kind}")
    na, mg, cec = (
        sample.exchangeableSodium,
        sample.exchangeableMagnesium,
        sample.cationExchangeCapacity,
    )
    if na is not None and cec:
        esp = na / cec * 100
        emg = None if mg is None else mg / cec * 100
        ph = sample.chemistry.pH if sample.chemistry is not None else None
        text = f"ESP {esp:.1f} %" + ("" if emg is None else f", EMgP {emg:.1f} %")
        if ph is not None:
            text += f", pH {ph:g} ({'>' if ph > dis.pHScreen else '≤'} {dis.pHScreen:g})"
        chem_kind = "nonDispersive"
        if esp > dis.espSerious:
            chem_kind = "dispersive"
            text += f": ESP > {dis.espSerious:g}, serious piping potential"
        elif esp > dis.espDispersive and (emg is None or esp + emg > dis.espPlusEmgDispersive):
            chem_kind = "dispersive"
            text += f": ESP > {dis.espDispersive:g}" + (
                "" if emg is None else f" and ESP + EMgP > {dis.espPlusEmgDispersive:g}"
            )
        elif dis.espModerate[0] <= esp <= dis.espModerate[1]:
            chem_kind = "moderate"
            text += f": ESP {dis.espModerate[0]:g}-{dis.espModerate[1]:g}, moderately dispersive"
        checks.append(text)
        order = ["nonDispersive", "intermediate", "moderate", "dispersive"]
        if kind is None or order.index(chem_kind) > order.index(kind):
            kind = chem_kind
    if kind is None:
        return None
    return {"class": kind, "checks": checks, "clause": dis.clause, "note": dis.note}


def soft_clay(behaviour: str, n_field: float | None, cu: float | None) -> dict[str, Any] | None:
    """Whether a layer is a soft clay: ``{consistency, by, clause}``; None when it is not (or
    when the pack has no criterion)."""
    table = code_data.table()
    if table is None or table.softClay is None or behaviour != "cohesive":
        return None
    soft = table.softClay
    by = []
    if n_field is not None and n_field <= soft.nAtMost:
        by.append(f"N {n_field:g} ≤ {soft.nAtMost:g}")
    if cu is not None and cu <= soft.cuRange[1]:
        # A clay below the range's lower end (about 10 kPa) is softer still.
        by.append(f"cu {cu:g} kPa ≤ {soft.cuRange[1]:g} kPa")
    if not by:
        return None
    consistency = soft.rows[-1].consistency
    for row in soft.rows:
        if (n_field is not None and n_field < row.nBelow) or (cu is not None and cu < row.cuBelow):
            consistency = row.consistency
            break
    return {"consistency": consistency, "by": by, "clause": soft.clause}
