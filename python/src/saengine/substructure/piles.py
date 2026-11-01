"""Axial capacity of a single pile at a borehole (Part 9, deep foundations).

A pile of diameter D and length L whose head (the underside of its cap) is ``head`` below the
borehole's ground is checked with the soil of that borehole (:class:`saengine.soil.profile.
Profile`, the nearest borehole to the cap: :func:`nearest_profile`). Three ways to get the
ultimate resistances (``design.pileCapacity``); every number comes from the code pack in
force (``foundations``, its ``piles`` group) and every clause from its ``sources``:

- ``"soilReport"``: the unit values of Part 1 (:mod:`saengine.soil.piles`: bored piles by the
  pack's drilled-shaft values, driven piles by API RP 2A in clay and Meyerhof 1976 in sand),
  evaluated slice by slice down the shaft (:data:`SLICE` m slices, each with the effective
  stress and depth at its middle, not the layer's mid-depth value) and summed over the shaft
  area. Where a layer's row carries ``sideExclusion`` (bored piles in cohesive soil) the top
  of the shaft and its bottom diameters carry no side resistance. Fill and organic layers carry
  none either (Part 1: "normally ignored for capacity"), nor does rock (a socket needs the
  rock's strength). End bearing is the unit value of the layer at the tip (for a bored pile
  with the pile's L/Db, the N60 below its base and the large-base reductions); for a driven
  pile in sand Meyerhof's limit 4 pa N60 is reached at 10 D of embedment in the layer and
  taken in proportion below that.
- ``"static"``: the pack's static method (:mod:`saengine.substructure.pile_static`, chosen by
  ``foundations.piles.staticMethod``; the default pack's ``alphaBeta``: α in clay, β and Nq in
  sand with the critical depth, bored piles by shares of the driven values, drilled shafts by
  their own values), slice by slice as above; drilled shafts in cohesive soil leave out the
  same zones.
- ``"spt"`` (formerly ``"bnbcSpt"``): the pack's SPT relations for concrete piles
  (``foundations.piles.spt``: fs = a N̄60 ≤ max, fb = b N60 (× L/D in sand and non-plastic
  silt, then ≤ c N60) ≤ max), with N̄60 the layer's mean N60 for each slice (the "average
  N-value over the pile shaft length", taken layer by layer) and N60 at the tip the mean of the
  tests from the tip down to 3 D below it (else the nearest test below the tip, else the
  layer's mean). L/D is taken with L the embedment in the bearing layer (Meyerhof's meaning;
  the code does not define L there, and its caps are reached at L/D = 10). The overall factor
  is at least the pack's ``sptSafety``.

Capacity (the default pack's Eqs 6.3.11 to 6.3.14): Qs = As fs, Qb = Ab fb,
``Qult = Qs + Qb - W`` in compression, ``Qult ≤ 0.7 Qs + W`` in uplift, ``Qallow = Qult / FS``,
W the pile's weight (γc A L, buoyancy ignored: on the safe side in compression, not in uplift,
where W counts fully as the code writes it). The least overall factor of safety is the pack's
``noLoadTestSafety`` (3.0), or ``loadTestSafety`` (2.0) when the design rests on a load test at
the site with good quality control (``FactorsOfSafety.load_test``); the pack's ``pileSafety``
factors by construction control (permanent structure: 2.0 good, 2.5 normal, 2.8 poor, 3.0 very
poor; :func:`table_factor`) assume load test data, so without a load test the compression
factor is raised to at least 3.0 (a note says so). Uplift alike. Partial factors on skin
friction and end bearing (``partialSkin`` 1.5, ``partialBase`` 3.0) may be used independently,
the allowable load being the minimum of the two: ``Qa = min(Qult / FS, Qs/1.5 + Qb/3.0 - W)``
(W is not factored in the partial form).

Structural capacity of the pile section (:func:`structural_checks`): with reinforcement, the
ACI 318-19 22.4.2 limit φPn,max of the circular section (:class:`saengine.design.rc.RcSection`,
tied or spiral by the transverse bars; the pile is fully embedded, which BNBC Sec 3.10.1.31
says is not limited as a long column where cu > 10 kPa; softer soil and unbraced lengths are
designed as columns by :mod:`saengine.substructure.pile_lateral`) and φ fy As in tension;
without reinforcement, the plain concrete strength φPn = 0.60 × 0.60 f'c Ag (ACI 318-19
14.5.3.1 without the slenderness term, φ of Table 21.2.1) and no tension. Driven precast piles
also get the pack's service stress limit (BNBC 2020: 0.33 f'c on the gross area). A driven
cast-in-place pile (``drivenCastInPlace``) takes the unit values of a driven pile
(:func:`capacity_kind`) on the round section of a bored one.

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
from saengine.substructure import pile_static

#: Slice thickness of the shaft integration [m].
SLICE = 0.1
#: Unit weight of the pile concrete [kN/m³].
CONCRETE_UNIT_WEIGHT = 24.0
#: Uplift: the share of the skin friction that resists pulling out (BNBC Eq 6.3.12).
UPLIFT_SKIN = 0.7

#: The capacity methods (``design.pileCapacity``); "bnbcSpt" is the former name of "spt".
METHODS = ("soilReport", "static", "spt")
ALIASES = {"bnbcSpt": "spt"}


def method_id(method: str) -> str:
    """The current id of a capacity method (a former name mapped)."""
    return ALIASES.get(method, method)


def method_text(method: str) -> str:
    """How a capacity method works, with the active pack's name and clauses."""
    method = method_id(method)
    code = soil_piles.pack_name()
    clause = soil_piles.pile_clause
    common = (
        f"Qult = Qs + Qb - W, uplift 0.7 Qs + W; Qa = min(Qult/FS, Qs/1.5 + Qb/3.0 - W), FS at "
        f"least 3.0 in compression without a load test at the site, 2.0 with one ({code})."
    )
    if method == "spt":
        return (
            f"Pile capacity by the SPT relations of {code} ({clause('spt')}), N̄60 the layer's "
            "mean N60 slice by slice, N60 at the tip the mean over 3 D below it, L/D with L the "
            f"embedment in the bearing layer; FS at least the pack's SPT factor. {common}"
        )
    if method == "static":
        found = pile_static.rules()
        if found is None:
            return pile_static.not_covered("Static pile capacity")
        return (
            f"Pile capacity by the static method '{found.staticMethod}' of {code} "
            f"({clause('staticMethod')}): α method in clay, β method and Nq in sand with the "
            f"critical depth, integrated over the shaft in {SLICE * 1e3:.0f} mm slices; bored "
            f"piles up to {found.drilledShaft.minDiameter:g} mm take "
            f"{found.static.boredSkin:.3g} of the driven fs and {found.static.boredBase:.3g} of "
            "its fb, wider ones the drilled-shaft values (no side resistance in clay over the "
            f"top {found.drilledShaft.sideTop:g} mm and the bottom "
            f"{found.drilledShaft.sideBottom:g} D). {common}"
        )
    return (
        "Pile capacity from the soil report's unit values (Part 1: drilled-shaft values of "
        f"{code} for bored piles, API RP 2A / Meyerhof 1976 for driven piles), integrated over "
        f"the shaft in {SLICE * 1e3:.0f} mm slices with the stresses at each slice; bored piles "
        "in cohesive soil without side resistance over the top of the shaft and the bottom "
        f"diameter; fill, organic soil and rock carry no side resistance. {common}"
    )


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
        method = method_id(method)
        least = _safety("loadTestSafety" if self.load_test else "noLoadTestSafety")
        compression = max(self.compression, least)
        uplift = max(self.uplift, least)
        if method == "spt":
            spt = _safety("sptSafety")
            compression, uplift = max(compression, spt), max(uplift, spt)
        return FactorsOfSafety(compression, uplift, self.skin, self.base, self.load_test)

    def raised(self, method: str) -> str | None:
        """A note when :meth:`for_method` raises the compression or the uplift factor."""
        method = method_id(method)
        factors = self.for_method(method)
        used = factors.compression
        notes = []
        spt = _safety("sptSafety")
        sources = _foundations().sources
        code = soil_piles.pack_name()
        if used > self.compression:
            if method == "spt" and used == spt:
                notes.append(
                    f"FS in compression raised from {self.compression:g} to {spt:g}: {code} "
                    f"asks for {spt:g} with the SPT relations ({sources.get('sptSafety', '')})"
                )
            else:
                notes.append(
                    f"FS in compression raised from {self.compression:g} to {used:g}: {code} "
                    f"asks at least {used:g} unless the design rests on a load test at the site "
                    f"({sources.get('noLoadTestSafety', '')}; the construction-control factors "
                    "assume load test data)"
                )
        if method != "spt" and factors.uplift > self.uplift:
            notes.append(
                f"FS in uplift raised from {self.uplift:g} to {factors.uplift:g}: {code} asks "
                f"at least {factors.uplift:g} on an uplift capacity found by analysis "
                f"({sources.get('noLoadTestSafety', '')})"
            )
        return "; ".join(notes) or None


def table_factor(structure: str = "permanent", control: str = "normal") -> float:
    """The pack's ``foundations.pileSafety`` factor of safety (BNBC 2020 Part 6 Table 6.3.10a,
    design factor of safety for deep foundations, downward and upward load: structure ->
    (good, normal, poor, very poor control), e.g. permanent 2.00, 2.50, 2.80, 3.00), the
    control's place in ``foundations.pileControls`` (good, normal, poor, veryPoor)."""
    f = _foundations()
    return f.pileSafety[structure][list(f.pileControls).index(control)]


#: The pile kinds; a driven cast-in-place pile has the capacity of a driven pile and the round
#: section of a bored one.
KINDS = ("bored", "driven", "drivenCastInPlace")


def capacity_kind(kind: str) -> str:
    """The kind whose unit values a pile takes: driven cast-in-place piles those of driven
    piles (they displace the soil as they are driven)."""
    return "driven" if kind == "drivenCastInPlace" else kind


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


def _spt_relation(layer: SoilLayer, kind: str) -> tuple[Any | None, str]:
    """The pack's SPT relation of a layer (clay, sand or non-plastic silt) for a pile kind."""
    found = pile_static.rules()
    if found is None:
        return None, pile_static.not_covered("SPT relations")
    if layer.behaviour == "cohesive":
        soil = "clay"
    else:
        soil = "silt" if _is_silt(layer) else "sand"
    relation = found.spt.get(kind, {}).get(soil)
    if relation is None:
        return None, pile_static.not_covered(f"SPT relation of {kind} piles in {soil}")
    return relation, soil


def spt_skin(layer: SoilLayer, kind: str) -> tuple[float | None, str]:
    """The pack's unit skin friction [kPa] of a layer from its mean N60, and the relation."""
    n = layer.n60
    if n is None:
        return None, "no SPT in the layer"
    relation, soil = _spt_relation(layer, kind)
    if relation is None:
        return None, soil
    return (
        min(relation.skinMax, relation.skin * n),
        f"SPT, {soil}: fs = {relation.skin:g} N̄60 ≤ {relation.skinMax:g} kPa",
    )


def spt_base(layer: SoilLayer, kind: str, n60: float, embed_d: float) -> tuple[float, str]:
    """The pack's unit end bearing [kPa] from N60 at the tip and the embedment ratio L/D."""
    relation, soil = _spt_relation(layer, kind)
    if relation is None:
        return 0.0, soil
    if relation.baseCapN is None:
        return (
            min(relation.baseMax, relation.base * n60),
            f"SPT, {soil}: fb = {relation.base:g} N60 ≤ {relation.baseMax:g} kPa",
        )
    value = min(relation.base * n60 * embed_d, relation.baseCapN * n60, relation.baseMax)
    return value, (
        f"SPT, {soil}: fb = {relation.base:g} N60 L/D ≤ {relation.baseCapN:g} N60, "
        f"≤ {relation.baseMax:g} kPa"
    )


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
    construction: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Ultimate and allowable axial capacity [kN] of a circular pile D × L [m] whose head is
    ``head`` m below the borehole's ground (see the module notes). ``construction``: the
    drilled shaft's (K/K0, δ/φ) construction ids of the pack, for its β in sand."""
    if kind not in KINDS:
        raise ValueError(f"pile kind {kind!r}: {', '.join(KINDS)}")
    shape_kind, kind = kind, capacity_kind(kind)
    method = method_id(method)
    if method not in METHODS:
        raise ValueError(f"pile capacity method {method!r}: {', '.join(METHODS)}")
    if diameter <= 0 or length <= 0:
        raise ValueError("the pile needs a diameter and a length")
    static = None
    if method == "static":
        static = pile_static.method()
        if static is None:
            raise ValueError(pile_static.not_covered("Static pile capacity"))
    ctx = _Pile(kind, diameter, length, head, method, static, construction)
    given = factors or FactorsOfSafety()
    factors = given.for_method(method)
    tip = head + length
    perimeter, area = section_shape(shape_kind, diameter)
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
        fs, why = _slice_skin(profile, layer, ctx, z)
        if fs is None:
            skipped.add(f"layer {layer.index + 1} ({layer.soil_type}): {why}")
            fs = 0.0
        else:
            row["method"] = why
        excluded = _excluded(profile, layer, ctx, z)
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
        qb, base_note, n_tip = _base(profile, base_layer, ctx)
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
        "kind": shape_kind,
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
        "methodText": method_text(method),
        "notes": notes,
    }


@dataclass(frozen=True)
class _Pile:
    """The pile being integrated and how."""

    kind: str
    diameter: float
    length: float
    head: float
    method: str
    static: Any = None
    construction: tuple[str, str] | None = None

    @property
    def tip(self) -> float:
        return self.head + self.length

    @property
    def shaft(self) -> bool:
        return pile_static.is_shaft(self.kind, self.diameter)


def _slice_skin(
    profile: Profile, layer: SoilLayer, pile: _Pile, z: float
) -> tuple[float | None, str]:
    """Unit skin friction [kPa] of a slice at depth ``z``, or None with the reason."""
    if layer.behaviour == "rock":
        return None, "rock: no side resistance (a socket needs the rock's strength)"
    if layer.soil_type in ("fill", "organic"):
        return None, f"{layer.soil_type}: ignored for capacity (check downdrag)"
    if pile.method == "spt":
        return spt_skin(layer, pile.kind)
    if pile.method == "static":
        return pile.static.skin(profile, layer, pile.kind, z, pile.diameter, pile.construction)
    if pile.kind == "bored":
        values = soil_piles.bored(
            layer,
            z,
            profile.sigma_v_eff(z),
            diameter=pile.diameter,
            construction=pile.construction,
        )
    else:
        values = soil_piles.driven(layer, z, profile.sigma_v_eff(z))
    if values.get("fs") is None:
        return None, values.get("note") or "no unit skin friction"
    return float(values["fs"]), str(values.get("method"))


def _excluded(profile: Profile, layer: SoilLayer, pile: _Pile, z: float) -> bool:
    """Whether a slice lies in a zone without side resistance: Part 1's ``sideExclusion`` of
    bored piles in cohesive soil (the soil report's values, and drilled shafts by the static
    method)."""
    if pile.kind != "bored" or pile.method == "spt":
        return False
    if pile.method == "static" and not pile.shaft:
        return False
    if layer.behaviour != "cohesive" or layer.soil_type in ("fill", "organic"):
        return False
    values = soil_piles.bored(layer, z, profile.sigma_v_eff(z))
    zone = values.get("sideExclusion")
    if not zone:
        return False
    return (
        z - pile.head < zone["top"] / 1e3 or pile.tip - z < zone["bottomDiameters"] * pile.diameter
    )


def _base(profile: Profile, layer: SoilLayer, pile: _Pile) -> tuple[float, str, float | None]:
    """Unit end bearing [kPa] at the tip, its source and the N60 used."""
    if layer.behaviour == "rock":
        return 0.0, "rock at the tip: socket design needs the rock strength (not covered)", None
    kind, tip, diameter = pile.kind, pile.tip, pile.diameter
    embed = tip - max(layer.top, pile.head)
    if pile.method == "spt":
        n = tip_n60(profile, tip, diameter, layer)
        if n is None:
            return 0.0, "no SPT near the tip", None
        value, text = spt_base(layer, kind, n, embed / diameter)
        return value, text, n
    if pile.method == "static":
        return pile.static.base(profile, layer, kind, tip, diameter, pile.length)
    if kind == "bored":
        found = pile_static.rules()
        depth = (found.drilledShaft.sandBaseDepth if found else 2.0) * diameter
        n = pile_static.mean_n60_below(profile, tip, depth, layer)
        values = soil_piles.bored(
            layer,
            tip,
            profile.sigma_v_eff(tip),
            length=pile.length,
            diameter=diameter,
            n_base=n,
        )
        if values.get("qb") is None:
            return 0.0, values.get("note") or "no unit end bearing", n
        return float(values["qb"]), str(values.get("method")), n
    values = soil_piles.driven(layer, tip, profile.sigma_v_eff(tip))
    if values.get("qb") is None:
        return 0.0, values.get("note") or "no unit end bearing", layer.n60
    qb = float(values["qb"])
    text = str(values.get("method"))
    if layer.behaviour == "granular":
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
    construction: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Allowable compression and uplift [kN] for each diameter × length [mm], as the soil
    reports tabulate them: ``{"diameters", "lengths", "rows", "borehole", "head", "method"}``,
    each row ``{"D", "L", "Qs", "Qb", "W", "Qult", "Qa", "Ta"}``."""
    method = method_id(method)
    rows = []
    for d in diameters:
        for length in lengths:
            r = single_pile(
                profile,
                kind,
                d / 1e3,
                length / 1e3,
                head,
                method,
                factors,
                construction=construction,
            )
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
        "methodText": method_text(method),
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
                f"fully embedded: not a long column ({_embedded_clause()})",
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
    from saengine.substructure.pile_detailing import cite, rules

    found = rules()
    if kind == "driven" and found is not None:
        share = found.driven.serviceStress
        checks.append(
            _check(
                "Pile service stress (driven precast)",
                service * 1e3 / area,
                share * fc,
                "MPa",
                None,
                f"at most {share:g} f'c on a precast concrete pile ({cite('detailing.driven')})",
            )
        )
    return checks


def _embedded_clause() -> str:
    """The clause by which a fully embedded pile is not a long column (the pack's)."""
    from saengine.substructure.pile_detailing import cite

    return cite("lateral.unbracedCu") or "where the soil supports it laterally"


def min_reinforcement_note(diameter: float) -> str:
    """The code pack's build-ability guidance for a bored pile of this diameter [mm]."""
    from saengine.substructure.pile_detailing import guidance_note, not_covered

    return guidance_note(diameter) or not_covered("Bored pile reinforcement guidance")


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


def shaft_construction(pile_type: Any) -> tuple[str, str] | None:
    """The (K/K0, δ/φ) construction ids of a pile type's drilled shaft, or None."""
    k_id = getattr(pile_type, "shaftConstruction", None)
    d_id = getattr(pile_type, "shaftConcreting", None)
    return (k_id, d_id) if k_id and d_id else None


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
                profile,
                pile_type.kind,
                diameters,
                lengths,
                head,
                method,
                factors,
                shaft_construction(pile_type),
            )
            tables.append({"pileType": pile_type.id, **table})
    return {"tables": tables, "notes": notes}
