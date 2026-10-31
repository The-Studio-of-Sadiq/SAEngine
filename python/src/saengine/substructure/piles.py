"""Axial capacity of a single pile at a borehole (Part 9, deep foundations).

A pile of diameter D and length L whose head (the underside of its cap) is ``head`` below the
borehole's ground is checked with the soil of that borehole (:class:`saengine.soil.profile.
Profile`, the nearest borehole to the cap: :func:`nearest_profile`). Two ways to get the
ultimate resistances (``design.pileCapacity``):

- ``"soilReport"``: the unit values of Part 1 (:mod:`saengine.soil.piles`: bored piles by
  O'Neill & Reese 1999, driven piles by API RP 2A in clay and Meyerhof 1976 in sand),
  evaluated slice by slice down the shaft (:data:`SLICE` m slices, each with the effective
  stress and depth at its middle, not the layer's mid-depth value) and summed over the shaft
  area. Where a layer's row carries ``sideExclusion`` (bored piles in cohesive soil) the top
  1.5 m of the shaft and its bottom one diameter carry no side resistance. Fill and organic
  layers carry none either (Part 1: "normally ignored for capacity"), nor does rock (a socket
  needs the rock's strength). End bearing is the unit value of the layer at the tip; for a
  driven pile in sand Meyerhof's limit 4 pa N60 is reached at 10 D of embedment in the layer
  and taken in proportion below that.
- ``"bnbcSpt"``: BNBC 2020 Part 6's SPT relations for concrete piles, with N̄60 the layer's
  mean N60 for each slice (BNBC's "average N-value over the pile shaft length", taken layer by
  layer) and N60 at the tip the mean of the tests from the tip down to 3 D below it (else the
  nearest test below the tip, else the layer's mean):

  ======================  ======================================  ==============================
  Unit value [kPa]        Bored (Secs 3.10.4.5, 3.10.4.7)         Driven (3.10.1.13, 3.10.1.16)
  ======================  ======================================  ==============================
  Clay, fs                1.2 N̄60 ≤ 70 (Eq 6.3.29)                1.8 N̄60 ≤ 70 (Eq 6.3.21)
  Clay, fb                25 N60 ≤ 4000 (Eq 6.3.30)               45 N60 ≤ 4000 (Eq 6.3.22)
  Sand, fs                1.0 N̄60 ≤ 60 (Eq 6.3.31)                2 N̄60 ≤ 60 (Eq 6.3.25)
  Non-plastic silt, fs    0.9 N̄60 ≤ 60 (Eq 6.3.32)                1.7 N̄60 ≤ 60 (Eq 6.3.26)
  Sand, fb                15 N60 L/D ≤ 150 N60, 4000 (6.3.33)     40 N60 L/D ≤ 400 N60, 11000
                                                                  (6.3.27)
  Non-plastic silt, fb    10 N60 L/D ≤ 100 N60, 4000 (6.3.34)     30 N60 L/D ≤ 300 N60, 11000
                                                                  (6.3.28)
  ======================  ======================================  ==============================

  L/D is taken with L the embedment in the bearing layer (Meyerhof's meaning; the code does not
  define L there, and its caps are reached at L/D = 10). BNBC asks for a factor of safety of
  3.5 with these relations: the overall factor is at least 3.5.

Capacity (BNBC 2020 Part 6 Sec 3.10.1.10, Eqs 6.3.11 to 6.3.14): Qs = As fs, Qb = Ab fb,
``Qult = Qs + Qb - W`` in compression, ``Qult ≤ 0.7 Qs + W`` in uplift, ``Qallow = Qult / FS``,
W the pile's weight (γc A L, buoyancy ignored: on the safe side in compression, not in uplift,
where W counts fully as the code writes it). Sec 3.10.1.18: a minimum overall factor of safety
of 3.0 against bearing failure, or 2.0 when the design rests on a load test at the site with
good quality control (``FactorsOfSafety.load_test``); Table 6.3.10a's factors by construction
control (Permanent structure: 2.0 good, 2.5 normal, 2.8 poor, 3.0 very poor;
:func:`table_factor`) assume load test data (Table 6.3.10b), so without a load test the
compression factor is raised to at least 3.0 (a note says so). Sec 3.11.3 (part1 p796) asks
the same of uplift: a factor of safety of at least 3.0 on an uplift capacity found by analysis,
2.0 on one from a load test (2.0 and 1.5 where the uplift comes from wind or earthquake; not
used, the uplift checks mix the cases), so the uplift factor is raised alike. Partial
factors of 1.5 on skin friction and 3.0 on end bearing may be used independently, the
allowable load being the minimum of the two: ``Qa = min(Qult / FS, Qs/1.5 + Qb/3.0 - W)``
(W is not factored in the partial form). Sec 3.10.4.10: the same factors apply to bored piles.

Structural capacity of the pile section (:func:`structural_checks`): with reinforcement, the
ACI 318-19 22.4.2 limit φPn,max of the circular section (:class:`saengine.design.rc.RcSection`,
tied or spiral by the transverse bars; the pile is fully embedded, which BNBC Sec 3.10.1.31
says is not limited as a long column where cu > 10 kPa) and φ fy As in tension; without
reinforcement, the plain concrete strength φPn = 0.60 × 0.60 f'c Ag (ACI 318-19 14.5.3.1
without the slenderness term, φ of Table 21.2.1) and no tension. Driven precast piles also get
BNBC Sec 3.10.1.31's service stress limit 0.33 f'c on the gross area.

Section: a bored pile is a circle of diameter D; a driven pile is a square precast pile of side
B (``PileType.diameter``, as the BOQ measures it): shaft perimeter 4B and base area B², and its
structural checks on the square section (:mod:`saengine.substructure.precast`, which also
checks its handling and its least bars).

Units: m, kPa and kN inside; reported in mm, kPa and kN.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import fmean
from typing import Any

from saengine.codes import context as code_context
from saengine.soil import piles as soil_piles
from saengine.soil.profile import Profile, SoilLayer

#: Slice thickness of the shaft integration [m].
SLICE = 0.1
#: Unit weight of the pile concrete [kN/m³].
CONCRETE_UNIT_WEIGHT = 24.0
#: Uplift: the share of the skin friction that resists pulling out (BNBC Eq 6.3.12).
UPLIFT_SKIN = 0.7

METHODS = {
    "soilReport": (
        "Pile capacity from the soil report's unit values (Part 1: O'Neill & Reese 1999 for "
        "bored piles, API RP 2A / Meyerhof 1976 for driven piles), integrated over the shaft in "
        f"{SLICE * 1e3:.0f} mm slices with the stresses at each slice; bored piles in cohesive "
        "soil without side resistance over the top 1.5 m of the shaft and the bottom 1 D; fill, "
        "organic soil and rock carry no side resistance. BNBC 2020 Part 6 Eqs 6.3.11-6.3.14: "
        "Qult = Qs + Qb - W, uplift 0.7 Qs + W; Qa = min(Qult/FS, Qs/1.5 + Qb/3.0 - W) "
        "(Sec 3.10.1.18, FS of Table 6.3.10a, at least 3.0 in compression without a load test "
        "at the site, 2.0 with one)."
    ),
    "bnbcSpt": (
        "Pile capacity by BNBC 2020 Part 6's SPT relations (bored: Eqs 6.3.29-6.3.34; driven: "
        "Eqs 6.3.21-6.3.22, 6.3.25-6.3.28), N̄60 the layer's mean N60 slice by slice, N60 at the "
        "tip the mean over 3 D below it, L/D with L the embedment in the bearing layer; FS at "
        "least 3.5 as the code asks for these relations. Qult = Qs + Qb - W, uplift 0.7 Qs + W "
        "(Eqs 6.3.11-6.3.12)."
    ),
}


def _foundations() -> Any:
    """The pack's ``foundations`` table (BNBC 2020 Part 6 Sec 3.10.1)."""
    return code_context.table("foundations")


def _safety(name: str) -> float:
    """The pack's ``foundations.<name>`` factor of safety. BNBC 2020: ``partialSkin`` 1.5 and
    ``partialBase`` 3.0, the partial factors on skin friction and end bearing (Sec 3.10.1.18);
    ``sptSafety`` 3.5, the SPT relations (Secs 3.10.1.13, 3.10.1.16, 3.10.4.5, 3.10.4.7);
    ``noLoadTestSafety`` 3.0 / ``loadTestSafety`` 2.0, the least overall factor without / with
    a load test at the site, in compression (Sec 3.10.1.18; Sec 3.10.4.10 for bored piles) and
    uplift (Sec 3.11.3)."""
    return float(getattr(_foundations(), name))


def _permanent_normal() -> float:
    """Table 6.3.10a's factor for a permanent structure under normal control (BNBC 2020: 2.5)."""
    return table_factor()


@dataclass(frozen=True)
class FactorsOfSafety:
    """Overall factors of safety in compression and uplift, the partial factors, and whether
    the design rests on a load test at the site (BNBC Sec 3.10.1.18)."""

    compression: float = field(default_factory=_permanent_normal)
    uplift: float = field(default_factory=_permanent_normal)
    skin: float = field(default_factory=lambda: _safety("partialSkin"))
    base: float = field(default_factory=lambda: _safety("partialBase"))
    load_test: bool = False

    def for_method(self, method: str) -> FactorsOfSafety:
        """The least overall factors: 3.0 without a load test at the site, 2.0 with one, in
        compression (Sec 3.10.1.18, bored piles by Sec 3.10.4.10) and in uplift (Sec 3.11.3);
        3.5 with the SPT relations."""
        least = _safety("loadTestSafety" if self.load_test else "noLoadTestSafety")
        compression = max(self.compression, least)
        uplift = max(self.uplift, least)
        if method == "bnbcSpt":
            spt = _safety("sptSafety")
            compression, uplift = max(compression, spt), max(uplift, spt)
        return FactorsOfSafety(compression, uplift, self.skin, self.base, self.load_test)

    def raised(self, method: str) -> str | None:
        """A note when :meth:`for_method` raises the compression or the uplift factor."""
        factors = self.for_method(method)
        used = factors.compression
        notes = []
        spt = _safety("sptSafety")
        if used > self.compression:
            if method == "bnbcSpt" and used == spt:
                notes.append(
                    f"FS in compression raised from {self.compression:g} to {spt:g}: BNBC "
                    "asks for 3.5 with the SPT relations"
                )
            else:
                notes.append(
                    f"FS in compression raised from {self.compression:g} to {used:g}: BNBC 2020 "
                    "Sec 3.10.1.18 asks at least 3.0 unless the design rests on a load test at "
                    "the site (Table 6.3.10a's values assume load test data, Table 6.3.10b)"
                )
        if method != "bnbcSpt" and factors.uplift > self.uplift:
            notes.append(
                f"FS in uplift raised from {self.uplift:g} to {factors.uplift:g}: BNBC 2020 Sec "
                "3.11.3 asks at least 3.0 on an uplift capacity found by analysis, 2.0 from a "
                "load test"
            )
        return "; ".join(notes) or None


def table_factor(structure: str = "permanent", control: str = "normal") -> float:
    """The pack's ``foundations.pileSafety`` factor of safety (BNBC 2020 Part 6 Table 6.3.10a,
    design factor of safety for deep foundations, downward and upward load: structure ->
    (good, normal, poor, very poor control), e.g. permanent 2.00, 2.50, 2.80, 3.00), the
    control's place in ``foundations.pileControls`` (good, normal, poor, veryPoor)."""
    f = _foundations()
    return f.pileSafety[structure][list(f.pileControls).index(control)]


def section_shape(kind: str, size: float) -> tuple[float, float]:
    """Shaft perimeter and section area of a pile of ``size`` (any unit): a bored pile a circle
    of diameter ``size``, a driven precast pile a square of side ``size``."""
    if kind == "driven":
        return 4 * size, size * size
    return math.pi * size, math.pi * size**2 / 4


def nearest_profile(profiles: list[Profile], x_mm: float, y_mm: float) -> tuple[Profile, float]:
    """The borehole nearest to a plan point (mm) and its distance [mm]."""
    if not profiles:
        raise ValueError("the soil report has no boreholes")
    best = min(profiles, key=lambda p: math.hypot(p.x * 1e3 - x_mm, p.y * 1e3 - y_mm))
    return best, math.hypot(best.x * 1e3 - x_mm, best.y * 1e3 - y_mm)


# ─────────────────────────────────────── unit values ───────────────────────────────────────


def _is_silt(layer: SoilLayer) -> bool:
    return layer.soil_type == "silt"


def spt_skin(layer: SoilLayer, kind: str) -> tuple[float | None, str]:
    """BNBC's unit skin friction [kPa] of a layer from its mean N60, and the equation."""
    n = layer.n60
    if n is None:
        return None, "no SPT in the layer"
    if layer.behaviour == "cohesive":
        if kind == "bored":
            return min(70.0, 1.2 * n), "Eq 6.3.29: 1.2 N̄60 ≤ 70 kPa"
        return min(70.0, 1.8 * n), "Eq 6.3.21: 1.8 N̄60 ≤ 70 kPa"
    if _is_silt(layer):
        if kind == "bored":
            return min(60.0, 0.9 * n), "Eq 6.3.32: 0.9 N̄60 ≤ 60 kPa"
        return min(60.0, 1.7 * n), "Eq 6.3.26: 1.7 N̄60 ≤ 60 kPa"
    if kind == "bored":
        return min(60.0, 1.0 * n), "Eq 6.3.31: 1.0 N̄60 ≤ 60 kPa"
    return min(60.0, 2.0 * n), "Eq 6.3.25: 2 N̄60 ≤ 60 kPa"


def spt_base(layer: SoilLayer, kind: str, n60: float, embed_d: float) -> tuple[float, str]:
    """BNBC's unit end bearing [kPa] from N60 at the tip and the embedment ratio L/D."""
    if layer.behaviour == "cohesive":
        if kind == "bored":
            return min(4000.0, 25 * n60), "Eq 6.3.30: 25 N60 ≤ 4000 kPa"
        return min(4000.0, 45 * n60), "Eq 6.3.22: 45 N60 ≤ 4000 kPa"
    silt = _is_silt(layer)
    if kind == "bored":
        a, cap, eq = (10.0, 100.0, "6.3.34") if silt else (15.0, 150.0, "6.3.33")
        limit = 4000.0
    else:
        a, cap, eq = (30.0, 300.0, "6.3.28") if silt else (40.0, 400.0, "6.3.27")
        limit = 11000.0
    value = min(a * n60 * embed_d, cap * n60, limit)
    return value, f"Eq {eq}: {a:g} N60 L/D ≤ {cap:g} N60, ≤ {limit:g} kPa"


def tip_n60(profile: Profile, tip: float, diameter: float, layer: SoilLayer) -> float | None:
    """N60 in the vicinity of the tip: the tests from the tip to 3 D below it, else the
    nearest test below the tip, else the layer's mean."""
    near = [p.n60 for p in profile.spt if tip - 1e-9 <= p.depth <= tip + 3 * diameter + 1e-9]
    if near:
        return fmean(near)
    below = [p for p in profile.spt if p.depth >= tip]
    if below:
        return min(below, key=lambda p: p.depth).n60
    return layer.n60


# ─────────────────────────────────────── single pile ───────────────────────────────────────


def single_pile(
    profile: Profile,
    kind: str,
    diameter: float,
    length: float,
    head: float,
    method: str = "soilReport",
    factors: FactorsOfSafety | None = None,
    unit_weight: float = CONCRETE_UNIT_WEIGHT,
) -> dict[str, Any]:
    """Ultimate and allowable axial capacity [kN] of a circular pile D × L [m] whose head is
    ``head`` m below the borehole's ground (see the module notes)."""
    if kind not in ("bored", "driven"):
        raise ValueError(f"pile kind {kind!r}: bored or driven")
    if method not in METHODS:
        raise ValueError(f"pile capacity method {method!r}: soilReport or bnbcSpt")
    if diameter <= 0 or length <= 0:
        raise ValueError("the pile needs a diameter and a length")
    given = factors or FactorsOfSafety()
    factors = given.for_method(method)
    tip = head + length
    perimeter, area = section_shape(kind, diameter)
    notes: list[str] = []
    raised = given.raised(method)
    if raised:
        notes.append(raised)
    rows: dict[int, dict[str, Any]] = {}
    qs = 0.0
    steps = max(1, math.ceil(length / SLICE - 1e-9))
    dz = length / steps
    skipped: set[str] = set()
    for k in range(steps):
        z = head + (k + 0.5) * dz
        layer = profile.layer_at(z)
        if layer is None:
            continue
        row = rows.setdefault(
            layer.index,
            {
                "layer": layer.index,
                "soilType": layer.soil_type,
                "top": z - dz / 2,
                "bottom": z + dz / 2,
                "Qs": 0.0,
                "excluded": 0.0,
                "fs": [],
                "method": None,
            },
        )
        row["bottom"] = z + dz / 2
        fs, why = _slice_skin(profile, layer, kind, z, method)
        if fs is None:
            skipped.add(f"layer {layer.index + 1} ({layer.soil_type}): {why}")
            fs = 0.0
        else:
            row["method"] = why
        excluded = method == "soilReport" and _excluded(
            profile, layer, kind, z, head, tip, diameter
        )
        if excluded:
            row["excluded"] += dz
            fs = 0.0
        row["fs"].append(fs)
        row["Qs"] += fs * perimeter * dz
        qs += fs * perimeter * dz
    notes += sorted(skipped)

    base_layer = profile.layer_at(tip + 1e-6)
    qb, base_note, n_tip = 0.0, "no layer at the tip", None
    if base_layer is not None:
        qb, base_note, n_tip = _base(profile, base_layer, kind, tip, head, diameter, method)
    qb_force = qb * area
    weight = unit_weight * area * length
    q_ult = qs + qb_force - weight
    overall = q_ult / factors.compression
    partial = qs / factors.skin + qb_force / factors.base - weight
    qa = max(0.0, min(overall, partial))
    t_ult = UPLIFT_SKIN * qs + weight
    ta = t_ult / factors.uplift
    if profile.bottom < tip + 3 * diameter - 1e-9:
        notes.append(
            f"the borehole ends at {profile.bottom:.1f} m, less than 3 D below the tip "
            f"({tip + 3 * diameter:.1f} m): the soil below the tip is assumed to continue"
        )
    layers = []
    for row in sorted(rows.values(), key=lambda r: r["top"]):
        fs_values = row.pop("fs")
        layers.append(
            {
                **row,
                "top": round(row["top"] * 1e3),
                "bottom": round(row["bottom"] * 1e3),
                "fs": round(fmean(fs_values), 1) if fs_values else 0.0,
                "fsMax": round(max(fs_values), 1) if fs_values else 0.0,
                "Qs": round(row["Qs"], 1),
                "excluded": round(row["excluded"] * 1e3),
            }
        )
    return {
        "borehole": profile.id,
        "kind": kind,
        "method": method,
        "diameter": round(diameter * 1e3),
        "length": round(length * 1e3),
        "head": round(head * 1e3),
        "tip": round(tip * 1e3),
        "Qs": round(qs, 1),
        "Qb": round(qb_force, 1),
        "qb": round(qb, 1),
        "W": round(weight, 1),
        "Qult": round(q_ult, 1),
        "QaOverall": round(overall, 1),
        "QaPartial": round(partial, 1),
        "Qa": round(qa, 1),
        "Tult": round(t_ult, 1),
        "Ta": round(ta, 1),
        "factors": {
            "compression": factors.compression,
            "uplift": factors.uplift,
            "skin": factors.skin,
            "base": factors.base,
            "loadTest": factors.load_test,
        },
        "base": {
            "layer": base_layer.index if base_layer else None,
            "soilType": base_layer.soil_type if base_layer else None,
            "qb": round(qb, 1),
            "N60": None if n_tip is None else round(n_tip, 1),
            "method": base_note,
        },
        "layers": layers,
        "governs": "overall" if overall <= partial else "partial",
        "methodText": METHODS[method],
        "notes": notes,
    }


def _slice_skin(
    profile: Profile, layer: SoilLayer, kind: str, z: float, method: str
) -> tuple[float | None, str]:
    """Unit skin friction [kPa] of a slice at depth ``z``, or None with the reason."""
    if layer.behaviour == "rock":
        return None, "rock: no side resistance (a socket needs the rock's strength)"
    if layer.soil_type in ("fill", "organic"):
        return None, f"{layer.soil_type}: ignored for capacity (check downdrag)"
    if method == "bnbcSpt":
        return spt_skin(layer, kind)
    values = (soil_piles.bored if kind == "bored" else soil_piles.driven)(
        layer, z, profile.sigma_v_eff(z)
    )
    if values.get("fs") is None:
        return None, values.get("note") or "no unit skin friction"
    return float(values["fs"]), str(values.get("method"))


def _excluded(
    profile: Profile,
    layer: SoilLayer,
    kind: str,
    z: float,
    head: float,
    tip: float,
    diameter: float,
) -> bool:
    """Whether a slice lies in a zone without side resistance (Part 1's ``sideExclusion``)."""
    if layer.behaviour == "rock" or layer.soil_type in ("fill", "organic"):
        return False
    values = (soil_piles.bored if kind == "bored" else soil_piles.driven)(
        layer, z, profile.sigma_v_eff(z)
    )
    zone = values.get("sideExclusion")
    if not zone:
        return False
    return z - head < zone["top"] / 1e3 or tip - z < zone["bottomDiameters"] * diameter


def _base(
    profile: Profile,
    layer: SoilLayer,
    kind: str,
    tip: float,
    head: float,
    diameter: float,
    method: str,
) -> tuple[float, str, float | None]:
    """Unit end bearing [kPa] at the tip, its source and the N60 used."""
    if layer.behaviour == "rock":
        return 0.0, "rock at the tip: socket design needs the rock strength (not covered)", None
    embed = tip - max(layer.top, head)
    if method == "bnbcSpt":
        n = tip_n60(profile, tip, diameter, layer)
        if n is None:
            return 0.0, "no SPT near the tip", None
        value, text = spt_base(layer, kind, n, embed / diameter)
        return value, text, n
    values = (soil_piles.bored if kind == "bored" else soil_piles.driven)(
        layer, tip, profile.sigma_v_eff(tip)
    )
    if values.get("qb") is None:
        return 0.0, values.get("note") or "no unit end bearing", layer.n60
    qb = float(values["qb"])
    text = str(values.get("method"))
    if kind == "driven" and layer.behaviour == "granular":
        share = min(1.0, embed / (10 * diameter))
        if share < 1.0:
            text += f"; {embed:.2f} m in the layer < 10 D: × {share:.2f}"
        qb *= share
    return qb, text, layer.n60


def capacity_table(
    profile: Profile,
    kind: str,
    diameters: list[float],
    lengths: list[float],
    head: float,
    method: str = "soilReport",
    factors: FactorsOfSafety | None = None,
) -> dict[str, Any]:
    """Allowable compression and uplift [kN] for each diameter × length [mm], as the soil
    reports tabulate them: ``{"diameters", "lengths", "rows", "borehole", "head", "method"}``,
    each row ``{"D", "L", "Qs", "Qb", "W", "Qult", "Qa", "Ta"}``."""
    rows = []
    for d in diameters:
        for length in lengths:
            r = single_pile(profile, kind, d / 1e3, length / 1e3, head, method, factors)
            rows.append(
                {
                    "D": d,
                    "L": length,
                    **{k: r[k] for k in ("Qs", "Qb", "W", "Qult", "Qa", "Ta")},
                }
            )
    return {
        "borehole": profile.id,
        "kind": kind,
        "method": method,
        "head": round(head * 1e3),
        "diameters": list(diameters),
        "lengths": list(lengths),
        "rows": rows,
        "methodText": METHODS[method],
    }


# ─────────────────────────────────────── structural ───────────────────────────────────────


def structural_checks(
    kind: str,
    diameter: float,
    fc: float,
    fy: float,
    reinforcement: Any,
    pu: float,
    tu: float,
    service: float,
    combination: str | None = None,
    tension_combination: str | None = None,
) -> list[dict[str, Any]]:
    """Checks of the pile section [kN]: ``pu`` the largest factored compression, ``tu`` the
    largest factored tension (positive), ``service`` the largest service compression;
    ``diameter`` in mm, f'c and fy in MPa, ``reinforcement`` a LinearReinforcement or None."""
    from saengine.design.check import _check
    from saengine.design.rc import DesignError, section_of
    from saengine.library.objects import CircleProfile, RectangleProfile

    square = kind == "driven"
    area = section_shape(kind, diameter)[1]  # mm²
    shape = f"{diameter:.0f} mm square" if square else f"Ø{diameter:.0f}"
    checks: list[dict[str, Any]] = []
    section = None
    reason = "no reinforcement"
    if reinforcement is not None and reinforcement.longitudinal:
        profile = (
            RectangleProfile(xDim=diameter, yDim=diameter)
            if square
            else CircleProfile(radius=diameter / 2)
        )
        try:
            section = section_of(profile, reinforcement, fc, fy)
        except DesignError as error:
            reason = str(error)
    if section is not None:
        bars = ", ".join(f"{g.count}Ø{g.dia:g}" for g in reinforcement.longitudinal)
        tie = "spiral" if section.spiral else "tied"
        checks.append(
            _check(
                "Pile axial compression (section)",
                pu,
                section.phi_pn_max / 1e3,
                "kN",
                combination,
                f"ACI 318-19 22.4.2 φPn,max of the {shape} section ({tie}), {bars}, "
                f"As = {section.steel_area:.0f} mm² ({100 * section.steel_area / area:.2f} %); "
                "fully embedded: not a long column (BNBC Sec 3.10.1.31)",
            )
        )
        checks.append(
            _check(
                "Pile axial tension (section)",
                tu,
                section.phi_tension / 1e3,
                "kN",
                tension_combination,
                f"φ fy As = 0.9 × {fy:g} × {section.steel_area:.0f} mm²",
            )
        )
    else:
        phi_pn = 0.60 * 0.60 * fc * area
        checks.append(
            _check(
                "Pile axial compression (plain section)",
                pu,
                phi_pn / 1e3,
                "kN",
                combination,
                f"{reason}: plain concrete φPn = 0.60 × 0.60 f'c Ag (ACI 318-19 14.5.3.1 without "
                "the slenderness term, φ by Table 21.2.1)",
            )
        )
        if tu > 0:
            checks.append(
                _check(
                    "Pile axial tension (plain section)",
                    tu,
                    0.0,
                    "kN",
                    tension_combination,
                    f"{reason}: an unreinforced pile cannot carry tension; reinforce it",
                )
            )
    if kind == "driven":
        checks.append(
            _check(
                "Pile service stress (driven precast)",
                service * 1e3 / area,
                0.33 * fc,
                "MPa",
                None,
                "BNBC 2020 Part 6 Sec 3.10.1.31: at most 0.33 f'c on a precast concrete pile",
            )
        )
    return checks


def min_reinforcement_note(diameter: float) -> str:
    """BNBC Table 6.3.11's guidance for a bored pile of this diameter [mm] (build-ability)."""
    rows = (
        (400, "6Ø16, hoops Ø8 @ 200"),
        (450, "6Ø16, hoops Ø8 @ 200"),
        (500, "8Ø16, hoops Ø8 @ 250"),
        (600, "8Ø16, hoops Ø8 @ 250"),
        (750, "10Ø16, hoops Ø10 @ 300"),
        (900, "10Ø16, hoops Ø10 @ 300"),
        (1050, "12Ø16, hoops Ø10 @ 300"),
        (1200, "12Ø16, hoops Ø10 @ 300"),
        (1500, "12Ø20, hoops Ø10 @ 400"),
        (1800, "12Ø20, hoops Ø10 @ 400"),
        (2100, "16Ø20, hoops Ø10 @ 400"),
        (2400, "16Ø25, hoops Ø12 @ 500"),
    )
    found = next((text for d, text in rows if diameter <= d + 1e-6), rows[-1][1])
    return (
        f"BNBC Table 6.3.11 (guidance, compression only, fy 420): {found} for a Ø{diameter:.0f} "
        "bored pile, to at least 3 m below the cut-off"
    )


# ─────────────────────────────────────── tables for the editor ───────────────────────────────

#: Diameters the capacity tables offer next to a pile type's own [mm].
STANDARD_DIAMETERS = (400, 450, 500, 600, 750, 900, 1050, 1200, 1500)
#: Step of the lengths in the capacity tables [mm].
LENGTH_STEP = 1500.0


def profiles_of(soil_text: str | None) -> tuple[list[Profile], Any, list[str]]:
    """The boreholes' profiles of a soil report text, the report, and its problems."""
    from saengine.soil.report import parse

    if not soil_text or not soil_text.strip():
        return [], None, ["there is no soil report"]
    report = parse(soil_text)
    if isinstance(report, list):
        return [], None, report
    return [Profile(report, b) for b in report.boreholes], report, []


def table_sizes(
    diameter: float, length: float, available: float
) -> tuple[list[float], list[float]]:
    """Diameters [mm] near ``diameter`` (0.6 to 1.6 times) and lengths [mm] every 1.5 m from
    6 m up to ``available`` (the log below the head less 3 D), with the pile's own."""
    diameters = sorted({float(diameter)} | {
        float(d) for d in STANDARD_DIAMETERS if 0.6 * diameter <= d <= 1.6 * diameter
    })  # fmt: skip
    lengths: set[float] = {float(length)}
    value = 6000.0
    while value <= available + 1e-6 and len(lengths) < 16:
        lengths.add(value)
        value += LENGTH_STEP
    return diameters, sorted(lengths)


def capacity_tables(
    soil_text: str | None,
    pile_types: list[Any],
    head_level: float,
    method: str = "soilReport",
    factors: FactorsOfSafety | None = None,
) -> dict[str, Any]:
    """Per pile type × borehole, the allowable capacities against diameter and length, for the
    editor (as the soil reports tabulate them). ``pile_types``: the substructure's
    (:class:`saengine.library.substructure.PileType`); ``head_level``: the level of the pile
    heads (project datum, mm), e.g. the default founding level of the caps. Returns
    ``{"tables": [{"pileType", "borehole", ...capacity_table}], "notes"}``."""
    profiles, report, problems = profiles_of(soil_text)
    if not profiles:
        return {"tables": [], "notes": problems or ["the soil report has no boreholes"]}
    tables = []
    notes: list[str] = []
    for pile_type in pile_types:
        for profile in profiles:
            head = (report.ground_level(profile.borehole) - head_level) / 1e3
            if head < 0:
                notes.append(
                    f"{pile_type.id} at {profile.id}: the pile heads lie above the borehole's "
                    "ground; taken at the ground"
                )
                head = 0.0
            available = (profile.bottom - head) * 1e3 - 3 * pile_type.diameter
            diameters, lengths = table_sizes(pile_type.diameter, pile_type.length, available)
            table = capacity_table(
                profile, pile_type.kind, diameters, lengths, head, method, factors
            )
            tables.append({"pileType": pile_type.id, **table})
    return {"tables": tables, "notes": notes}
