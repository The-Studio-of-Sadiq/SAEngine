"""Laboratory results of the samples: what each test gives, and the values that feed the engine.

A sample's flat values (``cu``, ``c``, ``phi``, ``finesContent``, ``liquidLimit``,
``plasticLimit``, ``Cc``, ``e0``, ``unitWeight``, ``clayFraction``) are what the report
states; when one is empty it is derived from the sample's test groups (:func:`feed`):

- unit weight: γ = γd (1 + w), from the dry unit weight and the moisture content;
- cu: the triaxial UU's cu (entered, else the mean (σ1 - σ3)/2 of its specimens), else the
  unconfined compression's ``cu = qu/2`` (ASTM D2166 takes the undrained shear strength as
  half the unconfined compressive strength);
- c', φ': the direct shear test's (entered, else fitted by least squares to the specimens'
  ``τ = c' + σn tan φ'``), else an effective-stress triaxial's (CD, or CU with pore pressures;
  entered, else fitted to the specimens, :func:`triaxial`);
  a total-stress CU's c and φ do not feed the drained design;
- fines content FC: percent passing 0.075 mm of the grain size curve; clay fraction: passing
  0.005 mm where the hydrometer reaches it;
- PI = LL - PL, 0 for a non-plastic sample;
- Cc, Cr, e0: the consolidation test's (entered, else Cc fitted to the loading points at or
  beyond σ'p, the last two loading points when σ'p is not given, and Cr to the unloading
  points, as the slopes -Δe/Δlog10 σ');
- σ'p: the consolidation test's, for the layer's OCR = σ'p/σ'v0 (:mod:`saengine.soil.profile`
  works out σ'v0 at the sample's mid-depth).

Grading (ASTM D6913/D7928 data): the percent passing a size and the size at a percent passing
are interpolated linearly in log10(size) between the points; nothing is extrapolated beyond the
finest or coarsest point (except 100 % passing above a point that passes 100 %). Gravel is the
part retained on 4.75 mm (No. 4), sand 4.75-0.075 mm, fines below 0.075 mm (No. 200);
``Cu = D60/D10`` and ``Cc = D30²/(D10 D60)``.

USCS group symbol (ASTM D2487-17, the rules applied):

- fine-grained when 50 % or more passes 0.075 mm, else coarse-grained; a coarse soil is a
  gravel (G) when more of its coarse fraction is gravel than sand, else a sand (S);
- coarse with less than 5 % fines: well graded (W) when Cu ≥ 4 (gravel) or Cu ≥ 6 (sand) and
  1 ≤ Cc ≤ 3, else poorly graded (P); more than 12 % fines: GM/SM, GC/SC or GC-GM/SC-SM by the
  plasticity of the fines; 5 to 12 % fines: the dual symbol (GW-GM, SP-SC, ...);
- the plasticity of the fines (the A-line PI = 0.73 (LL - 20)): C (clay) when PI > 7 and on
  or above the A-line, CL-ML when 4 ≤ PI ≤ 7 and on or above it, M (silt) when PI < 4 or below
  it; non-plastic fines are M;
- fine-grained: LL < 50: CL, CL-ML or ML; LL ≥ 50: CH on or above the A-line, MH below;
- organic (OL, OH, PT; the code pack's criteria, :func:`saengine.soil.special_soils.
  organic_group`): PT from the organic content, OL/OH when the oven-dried liquid limit over
  the undried one is below the pack's ratio (0.75).

With fines of unknown plasticity (no LL/PL), or no D10/D30/D60 for the gradation, only what
the data decide is suggested (e.g. "S" with the reason). The group symbol is a suggestion
beside the log's ``uscs``, which the engineer enters.

Chemistry and problem soils: :mod:`saengine.soil.chemistry` (sulphate class, corrosive site,
chloride exposure, corrosivity) and :mod:`saengine.soil.special_soils` (organic, expansive,
collapsible, dispersive), with the code pack's limits; :func:`chemistry_flags` gives their
notes for one sample.
"""

from __future__ import annotations

import itertools
import math
import re
from statistics import fmean
from typing import Any

from saengine.library.soil import Consolidation, DirectShear, Grading, Sample, Triaxial

#: Sieve sizes of the fractions [mm].
NO_4 = 4.75
NO_200 = 0.075
CLAY_SIZE = 0.005

USCS_NAMES = {
    "GW": "Well-graded gravel",
    "GP": "Poorly graded gravel",
    "GM": "Silty gravel",
    "GC": "Clayey gravel",
    "GC-GM": "Silty, clayey gravel",
    "SW": "Well-graded sand",
    "SP": "Poorly graded sand",
    "SM": "Silty sand",
    "SC": "Clayey sand",
    "SC-SM": "Silty, clayey sand",
    "CL": "Lean clay",
    "CL-ML": "Silty clay",
    "ML": "Silt",
    "CH": "Fat clay",
    "MH": "Elastic silt",
    "OL": "Organic clay or silt",
    "OH": "Organic clay or silt of high plasticity",
    "PT": "Peat",
}

#: The 425 µm sieve (No. 40) [mm], for the weighted plasticity index.
NO_40 = 0.425


# ─────────────────────────────── grading ───────────────────────────────


def _curve(grading: Grading) -> list[tuple[float, float]]:
    """(log10 size, passing) from the coarsest point down."""
    return [(math.log10(p.size), p.passing) for p in sorted(grading.sieves, key=lambda p: -p.size)]


def passing(grading: Grading, size: float) -> float | None:
    """Percent passing ``size`` [mm], interpolated in log size; None outside the curve."""
    curve = _curve(grading)
    if not curve:
        return None
    x = math.log10(size)
    if x >= curve[0][0]:
        return curve[0][1] if curve[0][1] >= 100 - 1e-9 or x == curve[0][0] else None
    for (x1, p1), (x2, p2) in itertools.pairwise(curve):
        if x2 <= x <= x1:
            return p2 + (p1 - p2) * (x - x2) / (x1 - x2)
    if curve[-1][1] <= 1e-9:
        return 0.0
    return None


def size_at(grading: Grading, percent: float) -> float | None:
    """The size D [mm] that ``percent`` % of the soil is finer than; None outside the curve."""
    curve = _curve(grading)
    for (x1, p1), (x2, p2) in itertools.pairwise(curve):
        if p2 <= percent <= p1 and p1 > p2:
            return 10 ** (x2 + (x1 - x2) * (percent - p2) / (p1 - p2))
    for x, p in curve:
        if abs(p - percent) < 1e-9:
            return 10**x
    return None


def grading_summary(grading: Grading) -> dict[str, Any]:
    fines = passing(grading, NO_200)
    through_4 = passing(grading, NO_4)
    d10, d30, d60 = (size_at(grading, p) for p in (10, 30, 60))
    cu = d60 / d10 if d10 and d60 else None
    cc = d30**2 / (d10 * d60) if d10 and d30 and d60 else None
    return {
        "fines": fines,
        "gravel": None if through_4 is None else 100 - through_4,
        "sand": None if through_4 is None or fines is None else through_4 - fines,
        "clayFraction": passing(grading, CLAY_SIZE),
        "passing425": passing(grading, NO_40),
        "D10": d10,
        "D30": d30,
        "D60": d60,
        "Cu": cu,
        "Cc": cc,
    }


# ─────────────────────────────── USCS ───────────────────────────────


def a_line(ll: float) -> float:
    """PI of the A-line of the plasticity chart at a liquid limit."""
    return 0.73 * (ll - 20)


def fines_kind(ll: float | None, pl: float | None, non_plastic: bool) -> str | None:
    """'C', 'CM' (CL-ML) or 'M' for the fines' plasticity; None when not known."""
    if non_plastic:
        return "M"
    if ll is None or pl is None:
        return None
    pi = max(0.0, ll - pl)
    above = pi >= a_line(ll)
    if pi < 4 or not above:
        return "M"
    if pi > 7:
        return "C"
    return "CM"


def uscs(
    grading: dict[str, Any] | None,
    ll: float | None,
    pl: float | None,
    non_plastic: bool = False,
) -> dict[str, str] | None:
    """The suggested USCS group: ``{"symbol", "name", "basis"}``, or None without a grading."""
    if grading is None or grading.get("fines") is None:
        return None
    fines = grading["fines"]
    kind = fines_kind(ll, pl, non_plastic)
    if fines >= 50:
        if non_plastic and ll is None:
            return _group("ML", f"fines {fines:.0f} % ≥ 50 %, non-plastic")
        if ll is None or kind is None:
            return {
                "symbol": "M or C",
                "name": "Fine-grained soil",
                "basis": f"fines {fines:.0f} % ≥ 50 %; give LL and PL for the group",
            }
        pi = 0.0 if non_plastic or pl is None else max(0.0, ll - pl)
        basis = f"fines {fines:.0f} % ≥ 50 %, LL {ll:g}, PI {pi:g}, A-line {a_line(ll):.1f}"
        if ll >= 50:
            return _group("CH" if pi >= a_line(ll) else "MH", basis)
        return _group({"C": "CL", "CM": "CL-ML", "M": "ML"}[kind], basis)
    gravel, sand = grading.get("gravel"), grading.get("sand")
    if gravel is None or sand is None:
        return {
            "symbol": "G or S",
            "name": "Coarse-grained soil",
            "basis": f"fines {fines:.0f} % < 50 %; the curve does not reach 4.75 mm",
        }
    main = "G" if gravel > sand else "S"
    basis = f"fines {fines:.0f} %, gravel {gravel:.0f} %, sand {sand:.0f} %"
    graded = None
    cu, cc = grading.get("Cu"), grading.get("Cc")
    if cu is not None and cc is not None:
        well = cu >= (4 if main == "G" else 6) and 1 <= cc <= 3
        graded = "W" if well else "P"
        basis += f", Cu {cu:.1f}, Cc {cc:.2f}"
    if fines < 5:
        if graded is None:
            return {"symbol": main, "name": _main(main), "basis": basis + "; no D10 for Cu, Cc"}
        return _group(main + graded, basis)
    if kind is None:
        return {
            "symbol": main,
            "name": _main(main),
            "basis": basis + "; give LL and PL of the fines for the group",
        }
    if fines > 12:
        symbol = {"M": f"{main}M", "C": f"{main}C", "CM": f"{main}C-{main}M"}[kind]
        return _group(symbol, basis)
    if graded is None:
        return {"symbol": main, "name": _main(main), "basis": basis + "; no D10 for Cu, Cc"}
    fine = "M" if kind == "M" else "C"
    symbol = f"{main}{graded}-{main}{fine}"
    name = f"{USCS_NAMES[main + graded]} with {'silt' if fine == 'M' else 'clay'}"
    return {"symbol": symbol, "name": name, "basis": basis + ", 5-12 % fines: dual symbol"}


def uscs_of(sample: Sample, grading: dict[str, Any] | None = None) -> dict[str, str] | None:
    """The sample's suggested USCS group: :func:`uscs` from its grading and limits, made organic
    (OL, OH, PT) where the code pack's organic criteria say so."""
    from saengine.soil.special_soils import organic_group

    if grading is None and sample.grading is not None:
        grading = grading_summary(sample.grading)
    group = uscs(grading, sample.liquidLimit, sample.plasticLimit, sample.nonPlastic)
    organic = organic_group(sample, group["symbol"] if group else None)
    if organic is None:
        if group is not None and organic_group(sample, None) is not None:
            return {**group, "name": group["name"] + " with organic fines"}
        return group
    return organic


def _main(main: str) -> str:
    return "Gravel" if main == "G" else "Sand"


def _group(symbol: str, basis: str) -> dict[str, str]:
    return {"symbol": symbol, "name": USCS_NAMES[symbol], "basis": basis}


# ─────────────────────────────── strength, consolidation ───────────────────────────────


def fit_line(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """(intercept, slope) of the least-squares line through (x, y); None for fewer than two
    distinct x."""
    if len({x for x, _ in points}) < 2:
        return None
    mx = fmean(x for x, _ in points)
    my = fmean(y for _, y in points)
    sxx = sum((x - mx) ** 2 for x, _ in points)
    sxy = sum((x - mx) * (y - my) for x, y in points)
    slope = sxy / sxx
    return my - slope * mx, slope


def direct_shear(test: DirectShear) -> tuple[float | None, float | None, str]:
    """(c', φ', how) of a direct shear test."""
    if test.c is not None and test.phi is not None:
        return test.c, test.phi, "direct shear"
    line = fit_line([(p.normal, p.shear) for p in test.specimens])
    if line is None:
        return test.c, test.phi, "direct shear"
    c, slope = line
    phi = math.degrees(math.atan(max(slope, 0.0)))
    return (
        test.c if test.c is not None else max(c, 0.0),
        test.phi if test.phi is not None else phi,
        f"direct shear, fitted to {len(test.specimens)} specimens",
    )


def triaxial(test: Triaxial) -> dict[str, Any] | None:
    """cu (UU) or c, φ (CU, CD) of a triaxial test with how, or None without a type.

    Entered values win; else from the specimens: UU ``cu = mean (σ1 - σ3)/2``; CD and CU the
    failure line ``q = a + p tan α`` fitted to ``q = (σ1 - σ3)/2``, ``p = σ3 + q`` (with
    ``σ3' = σ3 - u`` where the pore pressure is given), ``sin φ = tan α``, ``c = a/cos φ``. A CU
    with every pore pressure gives effective c', φ'; without them total c, φ, which do not feed
    the drained design.
    """
    kind = test.type
    if kind is None:
        return None
    out: dict[str, Any] = {
        "cu": test.cu, "c": test.c, "phi": test.phi, "effective": test.effective,
        "how": f"triaxial {kind}",
    }  # fmt: skip
    specimens = test.specimens
    if kind == "UU":
        out["effective"] = False
        if out["cu"] is None and specimens:
            out["cu"] = fmean(s.deviator / 2 for s in specimens)
            out["how"] = f"triaxial UU, mean (σ1 - σ3)/2 of {len(specimens)} specimens"
        return out
    out["cu"] = None
    if (test.c is None or test.phi is None) and len(specimens) >= 2:
        # Effective stresses only when every specimen has its pore pressure; a line through
        # a mix of effective and total points would be neither.
        pore = all(s.porePressure is not None for s in specimens)
        partial = not pore and any(s.porePressure is not None for s in specimens)
        points = [
            (s.cell - ((s.porePressure or 0.0) if pore else 0.0) + s.deviator / 2, s.deviator / 2)
            for s in specimens
        ]
        line = fit_line(points)
        if line is not None and 0 <= line[1] < 1:
            phi = math.asin(line[1])
            out["c"] = test.c if test.c is not None else max(0.0, line[0] / math.cos(phi))
            out["phi"] = test.phi if test.phi is not None else math.degrees(phi)
            out["effective"] = kind == "CD" or pore
            out["how"] = f"triaxial {kind}, fitted to {len(specimens)} specimens"
            if kind == "CU" and not pore:
                out["how"] += (
                    ", total stresses (pore pressures not given for every specimen)"
                    if partial
                    else ", total stresses"
                )
    return out


def consolidation(test: Consolidation) -> dict[str, Any]:
    """Cc, Cr (entered or fitted), e0 and σ'p of a consolidation test, with how.

    The points are taken in test order and may hold unload-reload loops. The virgin curve is
    the points that reach a new maximum pressure (a reload up to an earlier pressure is
    recompression, not virgin loading): Cc is fitted to its points at or beyond σ'p, or without
    σ'p the slope of its last two points. Cr is fitted to the unloading branch (a run of falling
    pressures with the point it starts from) that starts at the highest pressure, the last one
    on a tie, so normally the final unloading from the maximum load.
    """
    points = [(p.pressure, p.e) for p in test.points]
    virgin_curve: list[tuple[float, float]] = []
    for pressure, e in points:
        if not virgin_curve or pressure > virgin_curve[-1][0]:
            virgin_curve.append((pressure, e))
    unloading: list[tuple[float, float]] = []
    branch: list[tuple[float, float]] = []
    for i in range(1, len(points) + 1):
        if i < len(points) and points[i][0] < points[i - 1][0]:
            branch = branch or [points[i - 1]]
            branch.append(points[i])
            continue
        if len(branch) >= 2 and (not unloading or branch[0][0] >= unloading[0][0]):
            unloading = branch
        branch = []
    out: dict[str, Any] = {"e0": test.e0, "preconsolidation": test.preconsolidation, "how": {}}
    cc = test.Cc
    if cc is None and len(virgin_curve) >= 2:
        if test.preconsolidation is not None:
            virgin = [p for p in virgin_curve if p[0] >= test.preconsolidation - 1e-9]
            how = "fitted to the virgin loading points at or beyond σ'p"
        else:
            virgin, how = virgin_curve[-2:], "slope of the last two virgin loading points (no σ'p)"
        line = fit_line([(math.log10(p), e) for p, e in virgin]) if len(virgin) >= 2 else None
        if line is not None:
            cc = max(0.0, -line[1])
            out["how"]["Cc"] = how
    cr = test.Cr
    if cr is None and len(unloading) >= 2:
        line = fit_line([(math.log10(p), e) for p, e in unloading])
        if line is not None:
            cr = max(0.0, -line[1])
            out["how"]["Cr"] = (
                f"fitted to the unloading from {unloading[0][0]:g} kPa ({len(unloading)} points)"
            )
    out["Cc"], out["Cr"] = cc, cr
    return out


# ─────────────────────────────── chemistry ───────────────────────────────


def chemistry_flags(sample: Sample) -> list[str]:
    """Durability and problem-soil notes of the sample (nothing is designed): the chemistry's
    (:func:`saengine.soil.chemistry.flags`) and the organic, expansive, collapsible and
    dispersive criteria (:mod:`saengine.soil.special_soils`), with the code pack's clauses."""
    from saengine.soil import chemistry, special_soils

    flags = chemistry.flags(sample)
    grading = grading_summary(sample.grading) if sample.grading is not None else None
    found = special_soils.organic(sample)
    if found is not None and found["organic"]:
        flags.append(
            f"organic content {found['organicContent']:g} %: {found['label']} "
            f"({found['clause']}); bearing capacity lower and compressibility higher"
        )
    found = special_soils.expansive(sample, grading)
    if found is not None and found["expansive"]:
        by = next(c for c in found["criteria"] if c["id"] == found["governing"])
        flags.append(
            f"expansive soil, {_words(found['degree'])} degree of expansion by {by['source']} "
            f"({by['value']:g} {by['unit']}) ({found['clause']})"
        )
    found = special_soils.collapsible(sample)
    if found is not None and found["collapsible"]:
        flags.append(
            "collapsible soil: "
            + "; ".join(c["text"] for c in found["checks"] if c["collapsible"])
            + f" ({found['clause']})"
        )
    found = special_soils.dispersive(sample)
    if found is not None and found["class"] in ("dispersive", "moderate"):
        flags.append(
            f"dispersive soil ({_words(found['class'])}): "
            + "; ".join(found["checks"])
            + f" ({found['clause']}); a concern for embankments and dams, not for the building"
        )
    return flags


def _words(identifier: str) -> str:
    """'veryHigh' -> 'very high'."""
    return re.sub(r"(?<=[a-z])([A-Z])", lambda m: " " + m.group(1).lower(), identifier)


# ─────────────────────────────── the sample's values ───────────────────────────────


def feed(sample: Sample) -> dict[str, tuple[float, str]]:
    """The values the sample gives the layer: ``name -> (value, how)``, ``how`` "" for a value
    the sample states, else the test it was derived from."""
    out: dict[str, tuple[float, str]] = {}

    def put(name: str, value: float | None, how: str = "") -> None:
        if value is not None and name not in out:
            out[name] = (float(value), how)

    for name in (
        "unitWeight", "cu", "c", "phi", "finesContent", "liquidLimit", "plasticLimit",
        "clayFraction", "Cc", "e0", "moisture",
    ):  # fmt: skip
        put(name, getattr(sample, name))
    if sample.dryUnitWeight is not None and sample.moisture is not None:
        put("unitWeight", sample.dryUnitWeight * (1 + sample.moisture / 100), "γd(1 + w)")
    tri = triaxial(sample.triaxial) if sample.triaxial is not None else None
    if tri is not None:
        put("cu", tri["cu"], tri["how"])
    if sample.ucs is not None:
        put("cu", sample.ucs.qu / 2, "UCS qu/2")
    if sample.directShear is not None:
        c, phi, how = direct_shear(sample.directShear)
        if c is not None and phi is not None and "c" not in out and "phi" not in out:
            put("c", c, how)
            put("phi", phi, how)
    fits = tri is not None and tri["effective"] and None not in (tri["c"], tri["phi"])
    if tri is not None and fits and not {"c", "phi"} & set(out):
        put("c", tri["c"], tri["how"])
        put("phi", tri["phi"], tri["how"])
    if sample.grading is not None:  # a curve with a data-entry mistake is ignored
        summary = grading_summary(sample.grading)
        put("finesContent", summary["fines"], "grain size, passing 0.075 mm")
        put("clayFraction", summary["clayFraction"], "grain size, finer than 0.005 mm")
    if sample.nonPlastic:
        put("plasticityIndex", 0.0, "non-plastic")
    elif sample.liquidLimit is not None and sample.plasticLimit is not None:
        put("plasticityIndex", max(0.0, sample.liquidLimit - sample.plasticLimit), "LL - PL")
    if sample.consolidation is not None:
        result = consolidation(sample.consolidation)
        for name in ("Cc", "Cr", "e0"):
            put(name, result[name], result["how"].get(name, "consolidation test"))
        put("preconsolidation", result["preconsolidation"], "consolidation test")
    return out


def summary(sample: Sample) -> dict[str, Any]:
    """Everything derived from a sample, JSON-ready, for the editor's lab view."""

    def r(value: float | None, digits: int = 2) -> float | None:
        return None if value is None else round(value, digits)

    out: dict[str, Any] = {
        "number": sample.number,
        "depth": sample.depth,
        "depthTo": sample.depthTo,
        "type": sample.type,
        "values": {k: {"value": r(v, 4), "how": how} for k, (v, how) in feed(sample).items()},
    }
    grading = grading_summary(sample.grading) if sample.grading is not None else None
    if sample.issues:
        out["issues"] = sample.issues
    if grading is not None:
        out["grainSize"] = {k: r(v, 4 if k.startswith("D") else 2) for k, v in grading.items()}
    group = uscs_of(sample, grading)
    if group is not None:
        out["uscs"] = group
    if sample.consolidation is not None:
        result = consolidation(sample.consolidation)
        out["consolidation"] = {
            "Cc": r(result["Cc"], 3),
            "Cr": r(result["Cr"], 3),
            "e0": r(result["e0"], 3),
            "preconsolidation": result["preconsolidation"],
            "how": result["how"],
        }
    if sample.permeability is not None:
        out["permeability"] = sample.permeability.k
    out["flags"] = chemistry_flags(sample)
    return out
