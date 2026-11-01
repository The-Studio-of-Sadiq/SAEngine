"""Site class of a borehole from its SPT profile, by the code pack's site classification.

The pack's ``siteInvestigation.siteClassification`` group holds the classes and their limits
(the default pack: BNBC 2020 Part 6 Table 6.2.13, which classifies the site by the average
properties of the top 30 m):

======  =============================================  ===========  =========  ===========
Class   Description (abridged)                         Vs [m/s]     N (SPT)    su [kPa]
======  =============================================  ===========  =========  ===========
SA      Rock or rock-like formation, at most 5 m of    > 800        -          -
        weaker material at the surface
SB      Very dense sand, gravel or very stiff clay,    360-800      > 50       > 250
        at least several tens of metres thick
SC      Deep deposits of dense or medium dense sand,   180-360      15-50      70-250
        gravel or stiff clay
SD      Loose-to-medium cohesionless soil (with or     < 180        < 15       < 70
        without some soft cohesive layers), or
        predominantly soft-to-firm cohesive soil
SE      Surface alluvium with Vs of SC or SD, about    -            -          -
        5-20 m thick, on material with Vs > 800
S1      A layer at least 10 m thick of soft clays or   < 100        -          10-20
        silts with PI > 40 and high water content      (indicative)
S2      Liquefiable soils, sensitive clays, or any     -            -          -
        profile not in SA-SE or S1
======  =============================================  ===========  =========  ===========

(the default pack's table; the same classes and limits as Eurocode 8, EN 1998-1 Table 3.1. For
S1 and S2 the default pack's code asks for "site specific special studies for the ground
motion"; the soil factors S of the classes are the pack's ``seismic.siteClasses``.)

The averages over the classified depth are harmonic, as in ASCE 7-16 20.4 (eq. 20.4-2 and
20.4-3):

- ``N̄ = Σ di / Σ (di / Ni)`` over all the soil, Ni the field blow count (uncorrected), at most
  ``nMax`` (100). Each SPT test stands for the soil from midway to the test above to midway to
  the test below (the first from the ground, the last to the bottom of the borehole); a logged
  rock layer counts as N = nMax.
- ``s̄u = dc / Σ (di / sui)`` over the cohesive layers (dc their total thickness in the depth),
  sui at most ``suMax`` (250 kPa).

The class is the softer of the two when the profile has cohesive layers with an undrained
strength (as ASCE 7-16 20.4.3, which takes the softer of N̄ for the cohesionless and s̄u for
the cohesive soil).

A borehole shorter than the depth is extended with its last N (or its rock) down to it, the
usual practice; the result says so and marks the class ``provisional``. The project's class is
provisional unless a borehole of the governing class reaches the depth.

The class is one of the pack's ``order`` (the project settings' site class); the soft-clay
class (S1), the liquefiable class (S2) and the deep-rock class (SE) are flags (``flags``:
``{"class", "note"}``) the engineer decides on:

- Rock: Vs is not known from the boreholes. Rock within ``rockShallow`` of the ground gives
  ``rockClass`` (SB), not the stiffest class, which needs a measured shear wave velocity above
  ``rockVs``. Rock-like material deeper, to ``rockDeep``, raises the ``rockDeepClass`` (SE)
  flag: it needs the Vs of the alluvium and of the material below, which the SPT cannot give,
  so the class stays the one from N̄ and s̄u.
- Soft clay (``soft``, S1): a run of contiguous cohesive layers (clay, plastic silt, organic
  soil) at least ``thickness`` thick within the depth whose PI > ``pi`` (with su at most the
  top of ``suRange`` or unknown) or whose su is at most that (measured or correlated from the
  SPT, the note says which). The high water content is not checked.
- Liquefiable (S2): :func:`flag_liquefaction` when the liquefaction screening finds a
  liquefiable test (FS < 1): the site needs a site-specific study; ``liquefiableAssumed`` (SD,
  or the softer class found) is used for the design spectrum meanwhile.

A pack without the group does not cover the site class from the SPT: the result says so.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from saengine.soil import code_data
from saengine.soil.profile import Profile


def rules() -> Any | None:
    """The pack's site classification, or None when the pack does not cover it."""
    return code_data.site_classification()


def order() -> list[str]:
    """The site classes, stiffest first (the pack's; else its ``seismic.siteClasses``)."""
    found = rules()
    if found is not None:
        return list(found.order)
    return list(code_data.code_context.table("seismic").siteClasses)


def __getattr__(name: str) -> Any:
    if name == "ORDER":  # the former module constant
        return tuple(order())
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def liquefiable_assumed() -> str | None:
    """The class used meanwhile for a site with liquefiable soil (the default pack: SD)."""
    found = rules()
    return None if found is None else found.liquefiableAssumed


def _band(rows: list[Any], value: float) -> str:
    found = code_data.band(rows, value)
    return (found or rows[-1]).siteClass


def class_of_n(n: float) -> str:
    return _band(_rules().byN, n)


def class_of_su(su: float) -> str:
    return _band(_rules().bySu, su)


def _rules() -> Any:
    found = rules()
    if found is None:
        raise ValueError(code_data.not_covered("The site class from the SPT"))
    return found


def softer(a: str, b: str) -> str:
    classes = order()
    return a if classes.index(a) >= classes.index(b) else b


def _segments(
    profile: Profile, depth: float, n_max: float
) -> tuple[list[tuple[float, float, float]], bool, float]:
    """(top, bottom, N) pieces of the top ``depth``, whether they were extrapolated, the log's
    bottom."""
    tests = sorted(profile.spt, key=lambda p: p.depth)
    bottom = max([profile.bottom] + [p.depth for p in tests])
    # Each test's range.
    ranges = []
    for i, test in enumerate(tests):
        top = 0.0 if i == 0 else (tests[i - 1].depth + test.depth) / 2
        low = bottom if i == len(tests) - 1 else (test.depth + tests[i + 1].depth) / 2
        ranges.append((top, low, min(float(test.n), n_max)))
    if ranges:
        top, _, n = ranges[-1]
        ranges[-1] = (top, math.inf, n)
    rock = [(layer.top, layer.bottom) for layer in profile.layers if layer.soil_type == "rock"]
    if rock and profile.layers and profile.layers[-1].soil_type == "rock":
        rock[-1] = (rock[-1][0], math.inf)
    cuts = {0.0, depth, *(r[0] for r in ranges), *(r[1] for r in ranges if r[1] < depth)}
    cuts |= {d for r in rock for d in r if d < depth}
    points = sorted(c for c in cuts if 0 <= c <= depth)
    pieces = []
    for top, low in pairwise(points):
        mid = (top + low) / 2
        if any(a <= mid < b for a, b in rock):
            pieces.append((top, low, n_max))
            continue
        n = next((v for a, b, v in ranges if a <= mid < b), None)
        if n is not None:
            pieces.append((top, low, n))
    return pieces, bottom < depth, bottom


def harmonic(pieces: list[tuple[float, float, float]]) -> float | None:
    thickness = sum(b - a for a, b, _ in pieces)
    if thickness <= 0:
        return None
    if any(v <= 0 for _, _, v in pieces):
        return 0.0
    return thickness / sum((b - a) / v for a, b, v in pieces)


def site_class(profile: Profile) -> dict[str, Any]:
    """The borehole's site class with the averages behind it."""
    notes: list[str] = []
    r = rules()
    if r is None:
        return {
            "class": None,
            "N": None,
            "su": None,
            "depth": round(profile.bottom * 1e3),
            "extrapolated": False,
            "note": code_data.not_covered("The site class from the SPT") + ".",
            "notes": [],
            "flags": [],
        }
    depth, table = float(r.depth), r.table or r.clause
    pieces, extrapolated, bottom = _segments(profile, depth, float(r.nMax))
    n_bar = harmonic(pieces)
    su_pieces = []
    for layer in profile.layers:
        if layer.behaviour != "cohesive" or layer.cu is None or layer.top >= depth:
            continue
        su_pieces.append(
            (layer.top, min(layer.bottom, depth), max(min(layer.cu, float(r.suMax)), 1e-6))
        )
    su_bar = harmonic(su_pieces)
    by_n = class_of_n(n_bar) if n_bar is not None else None
    by_su = class_of_su(su_bar) if su_bar is not None else None
    if by_n is None and by_su is None:
        return {
            "class": None,
            "N": None,
            "su": None,
            "depth": round(bottom * 1e3),
            "extrapolated": False,
            "note": "No SPT records or undrained strengths: the site class cannot be worked out.",
            "notes": [],
            "flags": [],
        }
    cls = by_n if by_su is None else by_su if by_n is None else softer(by_n, by_su)
    basis = []
    if n_bar is not None:
        basis.append(f"N̄ = {n_bar:.1f} → {by_n}")
    if su_bar is not None:
        dc = sum(b - a for a, b, _ in su_pieces)
        basis.append(f"s̄u = {su_bar:.0f} kPa over {dc:.1f} m of cohesive soil → {by_su}")
    note = "; ".join(basis) + f" ({r.clause}, harmonic means over the top {depth:g} m)"
    if extrapolated:
        note += (
            f". The borehole ends at {bottom:.1f} m: its last N is taken down to {depth:g} m, "
            "the usual practice; a deeper borehole would confirm the class"
        )
    # The classified depth was not all logged: the class rests on the extension (rock reached
    # ends it).
    provisional = bottom < depth - 1e-6 and not any(
        layer.soil_type == "rock" and layer.bottom >= bottom - 1e-6 for layer in profile.layers
    )
    if provisional:
        notes.append(
            f"Provisional: the borehole ends at {bottom:.1f} m, and {r.clause} classifies the "
            f"site by the top {depth:g} m. Drill one borehole to {depth:g} m (or measure the "
            "shear wave velocity) to confirm the class."
        )
    flags: list[dict[str, str]] = []
    classes = list(r.order)
    rock_top = next((layer.top for layer in profile.layers if layer.soil_type == "rock"), None)
    if rock_top is not None and rock_top < r.rockShallow:
        softer_than_rock = [b.siteClass for b in r.byN if b.siteClass in classes]
        if cls in softer_than_rock and classes.index(cls) > classes.index(r.rockClass):
            cls = r.rockClass
        notes.append(
            f"Rock at {rock_top:.1f} m: {r.rockClass} is used; {classes[0]} needs a measured "
            f"shear wave velocity above {r.rockVs:g} m/s."
        )
    elif rock_top is not None and rock_top <= r.rockDeep:
        alluvium = " or ".join(b.siteClass for b in r.byN[1:])
        text = (
            f"{r.rockDeepClass} possible: rock-like material at {rock_top:.1f} m under the "
            f"alluvium. {table}'s {r.rockDeepClass} is {r.rockShallow:g}-{r.rockDeep:g} m of "
            f"alluvium with the Vs of {alluvium} on material with Vs > {r.rockVs:g} m/s, which "
            "the SPT cannot show: measure Vs to decide. The class from the SPT "
            f"({cls}) is used meanwhile."
        )
        flags.append({"class": r.rockDeepClass, "note": text})
        notes.append(text)
    s1 = soft_run(profile)
    if s1 is not None:
        flags.append({"class": r.soft.siteClass, "note": s1})
        notes.append(s1)
    return {
        "flags": flags,
        "class": cls,
        "N": None if n_bar is None else round(n_bar, 1),
        "su": None if su_bar is None else round(su_bar, 1),
        "byN": by_n,
        "bySu": by_su,
        "depth": round(min(bottom, depth) * 1e3),
        "extrapolated": extrapolated,
        "provisional": provisional,
        "note": note + ".",
        "notes": notes,
    }


def _soft(layer: Any, soft: Any) -> str | None:
    """Why a layer counts towards the soft-clay class, or None."""
    if layer.behaviour != "cohesive":
        return None
    su_max = float(soft.suRange[1])
    is_soft = layer.cu is not None and layer.cu <= su_max
    if layer.pi is not None and layer.pi > soft.pi and (layer.cu is None or is_soft):
        return f"PI = {layer.pi:.0f}"
    if is_soft:
        source = layer.sources.get("cu", "")
        how = "from the SPT" if "Stroud" in source else "measured"
        return f"su = {layer.cu:.0f} kPa ({how})"
    return None


def soft_run(profile: Profile) -> str | None:
    """The soft-clay flag's text when contiguous soft cohesive layers are thick enough."""
    r = rules()
    if r is None or r.soft is None:
        return None
    soft, depth = r.soft, float(r.depth)
    runs: list[list[tuple[Any, str]]] = []
    current: list[tuple[Any, str]] = []
    for layer in profile.layers:
        why = _soft(layer, soft) if layer.top < depth else None
        if why is None:
            if current:
                runs.append(current)
            current = []
            continue
        current.append((layer, why))
    if current:
        runs.append(current)
    best = None
    for run in runs:
        top, bottom = run[0][0].top, min(run[-1][0].bottom, depth)
        if bottom - top >= soft.thickness - 1e-9 and (
            best is None or bottom - top > best[1] - best[0]
        ):
            best = (top, bottom, run)
    if best is None:
        return None
    top, bottom, run = best
    layers = ", ".join(f"layer {layer.index + 1} {why}" for layer, why in run)
    low, high = soft.suRange
    return (
        f"{soft.siteClass} possible: {bottom - top:.1f} m of soft clay/silt from {top:.1f} to "
        f"{bottom:.1f} m ({layers}). {r.table or r.clause}'s {soft.siteClass} is a layer at "
        f"least {soft.thickness:g} m thick of soft clays/silts with PI > {soft.pi:g} and a high "
        f"water content (su {low:g}-{high:g} kPa), which needs a site-specific study "
        f"({site_specific_clause()}); the water content is not checked. The class from the SPT "
        "is used meanwhile."
    )


def s2_note(cls: str, clause: str | None = None) -> str:
    """The liquefiable-site flag's text; ``cls`` the class used meanwhile."""
    r = rules()
    flag = (r.liquefiableClass if r is not None else None) or "S2"
    table = (r.table or r.clause) if r is not None else "the code"
    clause = site_specific_clause() if clause is None else clause
    return (
        f"{flag} — liquefiable layers found: {table} classes the site {flag}, which needs a "
        f"site-specific study ({clause}); {cls} is used for the design spectrum meanwhile."
    )


def site_specific_clause() -> str:
    """Where the code in force asks for a site-specific study: its name and the pack's
    ``seismic.siteSpecificStudy.clause``."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    clause = code_context.table("seismic").siteSpecificStudy.clause
    return f"{pack.edition or pack.name} {clause}".strip()


def flag_liquefaction(site: dict[str, Any], liquefiable: bool) -> dict[str, Any]:
    """The borehole's site class with the liquefiable-site flag when its screening found
    liquefiable soil: the class becomes the pack's ``liquefiableAssumed`` (SD) unless it is
    already as soft (SE)."""
    r = rules()
    if (
        not liquefiable
        or not site.get("class")
        or r is None
        or not r.liquefiableClass
        or not r.liquefiableAssumed
    ):
        return site
    cls = softer(site["class"], r.liquefiableAssumed)
    note = s2_note(cls)
    out = {**site, "flags": [*site.get("flags", []), {"class": r.liquefiableClass, "note": note}]}
    if cls != site["class"]:
        out["class"], out["fromSpt"] = cls, site["class"]
    out["notes"] = [*site.get("notes", []), note]
    return out


def governing(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The project's site class: the softest of the boreholes'."""
    classes = {bh: r["class"] for bh, r in results.items() if r.get("class")}
    if not classes:
        return {
            "class": None,
            "governing": None,
            "note": "No borehole gives a site class.",
            "flags": [],
        }
    r = _rules()
    ordered = list(r.order)
    table = r.table or r.clause
    cls = max(classes.values(), key=ordered.index)
    # Of the boreholes of that class, the one with the lowest N̄ first.
    which = sorted(
        (bh for bh, c in classes.items() if c == cls),
        key=lambda bh: results[bh].get("N") if results[bh].get("N") is not None else math.inf,
    )
    listing = ", ".join(f"{bh} {c}" for bh, c in classes.items())
    note = (
        f"{cls}, the softest of the boreholes ({listing}), in the order {ordered[0]} to "
        f"{ordered[-1]} of {table}."
    )
    if len(set(classes.values())) > 1:
        note += " The boreholes differ: check that the site is not better split into zones."
    # Confirmed when a borehole of that class reaches the depth; else it rests on the extension.
    provisional = all(results[bh].get("provisional", False) for bh in which)
    if provisional:
        note += (
            f" Provisional: no borehole of this class reaches {float(r.depth):g} m, the depth "
            f"{table} classifies by."
        )
    flags: dict[str, dict[str, Any]] = {}
    for bh, res in results.items():
        for flag in res.get("flags", []):
            entry = flags.setdefault(
                flag["class"], {"class": flag["class"], "note": flag["note"], "boreholes": []}
            )
            entry["boreholes"].append(bh)
    return {
        "class": cls,
        "governing": which[0],
        "boreholes": which,
        "provisional": provisional,
        "note": note,
        "flags": sorted(flags.values(), key=lambda f: f["class"]),
    }
