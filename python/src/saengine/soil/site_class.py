"""Site class of a borehole from its SPT profile (BNBC 2020 Part 6, Table 6.2.13).

Table 6.2.13 classifies the site by the average properties of the top 30 m:

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

For S1 and S2 "site specific special studies for the ground motion should be done" (Sec
2.5.3.1).

(the same classes and limits as Eurocode 8, EN 1998-1 Table 3.1, from which the table is
adopted; :data:`saengine.library.bnbc.SITE_CLASSES` names SA..SE and
:data:`saengine.library.bnbc.SITE_FACTORS` gives their soil factors S).

The averages over the top 30 m are harmonic, as in ASCE 7-16 20.4 (eq. 20.4-2 and 20.4-3):

- ``N̄ = Σ di / Σ (di / Ni)`` over all the soil, Ni the field blow count (uncorrected), at most
  100. Each SPT test stands for the soil from midway to the test above to midway to the test
  below (the first from the ground, the last to the bottom of the borehole); a logged rock
  layer counts as N = 100.
- ``s̄u = dc / Σ (di / sui)`` over the cohesive layers (dc their total thickness in the top
  30 m), sui at most 250 kPa.

The class is the softer of the two when the profile has cohesive layers with an undrained
strength (as ASCE 7-16 20.4.3, which takes the softer of N̄ for the cohesionless and s̄u for
the cohesive soil).

A borehole shorter than 30 m is extended with its last N (or its rock) down to 30 m, the usual
practice; the result says so.

The class is one of SA-SE (the project settings' site class); S1, S2 and SE are flags
(``flags``: ``{"class", "note"}``) the engineer decides on:

- Rock: Vs is not known from the boreholes. Rock within 5 m of the ground gives SB, not SA,
  which needs a measured shear wave velocity above 800 m/s. Rock-like material 5-20 m deep
  raises the SE flag: SE needs the Vs of the alluvium (SC or SD) and of the material below
  (> 800 m/s), which the SPT cannot give, so the class stays the one from N̄ and s̄u.
- S1: a run of contiguous cohesive layers (clay, plastic silt, organic soil) at least 10 m
  thick within the top 30 m whose PI > 40 (with su ≤ 20 kPa or unknown) or whose su ≤ 20 kPa
  (the su of S1 is 10-20 kPa; measured or correlated from the SPT, the note says which). The
  high water content of Table 6.2.13 is not checked.
- S2: :func:`flag_liquefaction` when the liquefaction screening finds a liquefiable test
  (FS < 1): Table 6.2.13 classes the site S2, which needs a site-specific study; SD (or the
  softer class found) is used for the design spectrum meanwhile.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from saengine.soil.profile import Profile

DEPTH = 30.0  # m
N_MAX = 100.0
SU_MAX = 250.0  # kPa

#: (class, lower limit of N̄ exclusive, of s̄u exclusive), from the stiffest.
ORDER = ("SA", "SB", "SC", "SD", "SE")


def class_of_n(n: float) -> str:
    if n > 50:
        return "SB"
    if n >= 15:
        return "SC"
    return "SD"


def class_of_su(su: float) -> str:
    if su > 250:
        return "SB"
    if su >= 70:
        return "SC"
    return "SD"


def softer(a: str, b: str) -> str:
    return a if ORDER.index(a) >= ORDER.index(b) else b


def _segments(profile: Profile) -> tuple[list[tuple[float, float, float]], bool, float]:
    """(top, bottom, N) pieces of the top 30 m, whether they were extrapolated, the log's bottom."""
    tests = sorted(profile.spt, key=lambda p: p.depth)
    bottom = max([profile.bottom] + [p.depth for p in tests])
    # Each test's range.
    ranges = []
    for i, test in enumerate(tests):
        top = 0.0 if i == 0 else (tests[i - 1].depth + test.depth) / 2
        low = bottom if i == len(tests) - 1 else (test.depth + tests[i + 1].depth) / 2
        ranges.append((top, low, min(float(test.n), N_MAX)))
    if ranges:
        top, _, n = ranges[-1]
        ranges[-1] = (top, math.inf, n)
    rock = [(layer.top, layer.bottom) for layer in profile.layers if layer.soil_type == "rock"]
    if rock and profile.layers and profile.layers[-1].soil_type == "rock":
        rock[-1] = (rock[-1][0], math.inf)
    cuts = {0.0, DEPTH, *(r[0] for r in ranges), *(r[1] for r in ranges if r[1] < DEPTH)}
    cuts |= {d for r in rock for d in r if d < DEPTH}
    points = sorted(c for c in cuts if 0 <= c <= DEPTH)
    pieces = []
    for top, low in pairwise(points):
        mid = (top + low) / 2
        if any(a <= mid < b for a, b in rock):
            pieces.append((top, low, N_MAX))
            continue
        n = next((v for a, b, v in ranges if a <= mid < b), None)
        if n is not None:
            pieces.append((top, low, n))
    return pieces, bottom < DEPTH, bottom


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
    pieces, extrapolated, bottom = _segments(profile)
    n_bar = harmonic(pieces)
    su_pieces = []
    for layer in profile.layers:
        if layer.behaviour != "cohesive" or layer.cu is None or layer.top >= DEPTH:
            continue
        su_pieces.append((layer.top, min(layer.bottom, DEPTH), max(min(layer.cu, SU_MAX), 1e-6)))
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
    note = "; ".join(basis) + " (BNBC 2020 Table 6.2.13, harmonic means over the top 30 m)"
    if extrapolated:
        note += (
            f". The borehole ends at {bottom:.1f} m: its last N is taken down to 30 m, the usual "
            "practice; a deeper borehole would confirm the class"
        )
    flags: list[dict[str, str]] = []
    rock_top = next((layer.top for layer in profile.layers if layer.soil_type == "rock"), None)
    if rock_top is not None and rock_top < 5.0:
        cls = "SB" if cls in ("SC", "SD") else cls
        notes.append(
            f"Rock at {rock_top:.1f} m: SB is used; SA needs a measured shear wave velocity "
            "above 800 m/s."
        )
    elif rock_top is not None and rock_top <= 20.0:
        text = (
            f"SE possible: rock-like material at {rock_top:.1f} m under the alluvium. Table "
            "6.2.13's SE is 5-20 m of alluvium with the Vs of SC or SD on material with Vs > "
            "800 m/s, which the SPT cannot show: measure Vs to decide. The class from the SPT "
            f"({cls}) is used meanwhile."
        )
        flags.append({"class": "SE", "note": text})
        notes.append(text)
    s1 = soft_run(profile)
    if s1 is not None:
        flags.append({"class": "S1", "note": s1})
        notes.append(s1)
    return {
        "flags": flags,
        "class": cls,
        "N": None if n_bar is None else round(n_bar, 1),
        "su": None if su_bar is None else round(su_bar, 1),
        "byN": by_n,
        "bySu": by_su,
        "depth": round(min(bottom, DEPTH) * 1e3),
        "extrapolated": extrapolated,
        "note": note + ".",
        "notes": notes,
    }


#: su of the S1 soft clays and silts, at most [kPa] (Table 6.2.13: 10-20 kPa).
S1_SU = 20.0
#: Thickness of the S1 layer, at least [m].
S1_THICKNESS = 10.0


def _soft(layer: Any) -> str | None:
    """Why a layer counts towards S1, or None."""
    if layer.behaviour != "cohesive":
        return None
    soft = layer.cu is not None and layer.cu <= S1_SU
    if layer.pi is not None and layer.pi > 40 and (layer.cu is None or soft):
        return f"PI = {layer.pi:.0f}"
    if soft:
        source = layer.sources.get("cu", "")
        how = "from the SPT" if "Stroud" in source else "measured"
        return f"su = {layer.cu:.0f} kPa ({how})"
    return None


def soft_run(profile: Profile) -> str | None:
    """The S1 flag's text when contiguous soft cohesive layers are at least 10 m thick."""
    runs: list[list[tuple[Any, str]]] = []
    current: list[tuple[Any, str]] = []
    for layer in profile.layers:
        why = _soft(layer) if layer.top < DEPTH else None
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
        top, bottom = run[0][0].top, min(run[-1][0].bottom, DEPTH)
        if bottom - top >= S1_THICKNESS - 1e-9 and (
            best is None or bottom - top > best[1] - best[0]
        ):
            best = (top, bottom, run)
    if best is None:
        return None
    top, bottom, run = best
    layers = ", ".join(f"layer {layer.index + 1} {why}" for layer, why in run)
    return (
        f"S1 possible: {bottom - top:.1f} m of soft clay/silt from {top:.1f} to {bottom:.1f} m "
        f"({layers}). BNBC Table 6.2.13's S1 is a layer at least 10 m thick of soft clays/silts "
        "with PI > 40 and a high water content (su 10-20 kPa), which needs a site-specific "
        "study (Sec 2.5.3.1); the water content is not checked. The class from the SPT is used "
        "meanwhile."
    )


S2_NOTE = (
    "S2 — liquefiable layers found: BNBC Table 6.2.13 classes the site S2, which needs a "
    "site-specific study (Sec 2.5.3.1); {cls} is used for the design spectrum meanwhile."
)


def flag_liquefaction(site: dict[str, Any], liquefiable: bool) -> dict[str, Any]:
    """The borehole's site class with the S2 flag when its screening found liquefiable soil:
    the class becomes SD unless it is already as soft (SE)."""
    if not liquefiable or not site.get("class"):
        return site
    cls = softer(site["class"], "SD")
    note = S2_NOTE.format(cls=cls)
    out = {**site, "flags": [*site.get("flags", []), {"class": "S2", "note": note}]}
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
    cls = max(classes.values(), key=ORDER.index)
    # Of the boreholes of that class, the one with the lowest N̄ first.
    which = sorted(
        (bh for bh, c in classes.items() if c == cls),
        key=lambda bh: results[bh].get("N") if results[bh].get("N") is not None else math.inf,
    )
    listing = ", ".join(f"{bh} {c}" for bh, c in classes.items())
    note = (
        f"{cls}, the softest of the boreholes ({listing}), in the order SA to SE of Table 6.2.13."
    )
    if len(set(classes.values())) > 1:
        note += " The boreholes differ: check that the site is not better split into zones."
    flags: dict[str, dict[str, Any]] = {}
    for bh, r in results.items():
        for flag in r.get("flags", []):
            entry = flags.setdefault(
                flag["class"], {"class": flag["class"], "note": flag["note"], "boreholes": []}
            )
            entry["boreholes"].append(bh)
    return {
        "class": cls,
        "governing": which[0],
        "boreholes": which,
        "note": note,
        "flags": sorted(flags.values(), key=lambda f: f["class"]),
    }
