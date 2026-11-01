"""Vertical ground movement on piles: negative skin friction (downdrag) and swelling uplift
(Part 9, deep foundations).

The code pack's ``foundations.piles.downdrag`` group chooses the method and holds its values
(the default pack: Secs 3.10.1.22-3.10.1.23, 3.10.6.17-3.10.6.19); a pack without it does not
cover
them. ``method`` ``"neutralPoint"`` (:func:`neutral_point`), a load-transfer analysis along the
shaft at the borehole nearest the cap, the full ground movement assumed:

- the **settling soil**: from the ground down to the design's ``downdragDepth``, else the run of
  layers from the top whose soil type is one of the pack's ``settlingSoils`` (fill, organic) or,
  with ``softClay``, a soft clay by the pack's site investigation table;
- the unit skin friction along the shaft is that of the capacity method in force, in
  :data:`~saengine.substructure.piles.SLICE` slices; in the settling soil it acts downwards
  (fill and organic layers, ignored for capacity, take the values of their behaviour);
- the **neutral point** is the depth where the load coming down the pile, the sustained load
  plus the negative skin friction above, meets the resistance below it, the skin friction
  below and the end bearing (the ultimate values); it lies at most at the bottom of the
  settling soil, below which the soil does not move down past the pile;
- the **dragload** Qn is the negative skin friction above the neutral point. As part of the
  design load: the largest service pile load plus Qn against the capacity of the shaft below
  the neutral point and the base, over the compression factor of safety; the section at the
  neutral point (the largest axial force) carries the largest factored pile load plus the
  pack's ``dragloadFactor`` × Qn.

**Swelling uplift** (:func:`swelling`): in expansive soil the shaft within the zone of moisture
change (the design's ``swellingDepth``, else the layers whose samples the soil report finds
expansive, from the top) is gripped upwards by the skin friction there; the shaft below the zone
resists as in uplift (``0.7 Qs + W`` of the capacity method, over the uplift factor of safety),
with the least service pile load. The pile section takes the difference in tension.

Units: m and kN inside (as :mod:`saengine.substructure.piles`); reported in mm and kN.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.substructure import pile_static


def rules() -> Any | None:
    """The pack's downdrag rules, or None when the pack does not cover them."""
    found = pile_static.rules()
    return None if found is None else found.downdrag


def cite(key: str) -> str:
    from saengine.substructure.pile_detailing import cite as _cite

    return _cite(key)


def _soft(layer: Any) -> bool:
    from saengine.soil.special_soils import soft_clay

    try:
        return soft_clay(layer.behaviour, layer.n60, layer.cu) is not None
    except Exception:  # noqa: BLE001 - a pack without the soft clay table: not soft
        return False


def settling_depth(profile: Any, given: float | None) -> tuple[float | None, str]:
    """The bottom of the settling soil [m below the borehole's ground] and why; None when no
    soil settles."""
    found = rules()
    if given:
        return given / 1e3, f"settling soil to {given:.0f} mm (design)"
    if found is None:
        return None, ""
    bottom = None
    kinds = []
    for layer in sorted(profile.layers, key=lambda layer: layer.top):
        settles = layer.soil_type in found.settlingSoils or (found.softClay and _soft(layer))
        if not settles:
            break
        bottom = layer.bottom
        kinds.append(f"layer {layer.index + 1} ({layer.soil_type})")
    if bottom is None:
        return None, ""
    return bottom, f"settling soil to {bottom * 1e3:.0f} mm: {', '.join(kinds)}"


def expansive_depth(profile: Any, given: float | None) -> tuple[float | None, str]:
    """The bottom of the swelling zone [m] and why; None without expansive soil."""
    if given:
        return given / 1e3, f"swelling zone to {given:.0f} mm (design)"
    from saengine.soil.special_soils import expansive

    bottom = None
    found = []
    layers = getattr(profile.borehole, "layers", [])
    for layer, soil_layer in zip(layers, profile.layers, strict=False):
        swelling = False
        for sample in profile.samples_in(soil_layer.index, layer):
            try:
                result = expansive(sample)
            except Exception:  # noqa: BLE001 - a sample without data
                result = None
            if result is not None and result.get("expansive"):
                swelling = True
                break
        if not swelling:
            if bottom is not None:
                break
            continue
        bottom = soil_layer.bottom
        found.append(f"layer {soil_layer.index + 1}")
    if bottom is None:
        return None, ""
    return bottom, f"expansive {', '.join(found)} to {bottom * 1e3:.0f} mm (soil report samples)"


def _unit_skin(profile: Any, layer: Any, pile: Any, z: float, moving: bool) -> float:
    """Unit skin friction [kPa] of a slice; in moving soil fill and organic layers count."""
    from saengine.soil import piles as soil_piles
    from saengine.substructure import piles

    if layer.behaviour == "rock":
        return 0.0
    if not moving or layer.soil_type not in ("fill", "organic"):
        fs, _ = piles._slice_skin(profile, layer, pile, z)
        if fs is None:
            return 0.0
        if piles._excluded(profile, layer, pile, z) and not moving:
            return 0.0
        return float(fs)
    if pile.method == "spt":
        fs, _ = piles.spt_skin(layer, pile.kind)
    elif pile.method == "static":
        fs, _ = pile.static.skin(profile, layer, pile.kind, z, pile.diameter, pile.construction)
    else:
        values = (
            soil_piles.bored(layer, z, profile.sigma_v_eff(z), diameter=pile.diameter)
            if pile.kind == "bored"
            else soil_piles.driven(layer, z, profile.sigma_v_eff(z))
        )
        fs = values.get("fs")
    return float(fs or 0.0)


def _pile(single: dict[str, Any], construction: Any = None) -> Any:
    """The integration context of :func:`saengine.substructure.piles.single_pile`'s pile."""
    from saengine.substructure import piles

    static = pile_static.method() if single["method"] == "static" else None
    return piles._Pile(
        piles.capacity_kind(single["kind"]),
        single["diameter"] / 1e3,
        single["length"] / 1e3,
        single["head"] / 1e3,
        single["method"],
        static,
        construction,
    )


def _slices(profile: Any, single: dict[str, Any], moving_to: float, construction: Any = None):
    """(depth, skin force [kN]) of each slice down the shaft, the moving soil's to
    ``moving_to`` [m]."""
    from saengine.substructure import piles

    pile = _pile(single, construction)
    perimeter, _ = piles.section_shape(single["kind"], pile.diameter)
    steps = max(1, math.ceil(pile.length / piles.SLICE - 1e-9))
    dz = pile.length / steps
    rows = []
    for k in range(steps):
        z = pile.head + (k + 0.5) * dz
        layer = profile.layer_at(z)
        if layer is None:
            rows.append((z, 0.0))
            continue
        fs = _unit_skin(profile, layer, pile, z, z < moving_to)
        rows.append((z, fs * perimeter * dz))
    return rows, dz


def neutral_point(
    profile: Any,
    single: dict[str, Any],
    sustained: float,
    settling: float,
    construction: Any = None,
) -> dict[str, Any]:
    """The neutral point and the dragload of a pile (see the module notes): ``single`` the
    pile's :func:`~saengine.substructure.piles.single_pile`, ``sustained`` its sustained load
    [kN], ``settling`` the bottom of the settling soil [m]. Returns ``{"neutral" mm, "Qn",
    "Qbelow", "Qb", "W" kN, "settling" mm}``."""
    rows, dz = _slices(profile, single, settling, construction)
    qb, weight = float(single["Qb"]), float(single["W"])
    total = sum(f for _, f in rows)
    above = 0.0
    neutral = None
    for z, force in rows:
        top = z - dz / 2
        # the load coming down meets the resistance below: the neutral point
        if top >= settling - 1e-9 or sustained + above >= qb + total - above:
            neutral = top
            break
        above += force
    if neutral is None:
        neutral = rows[-1][0] + dz / 2 if rows else settling
    neutral = min(neutral, settling)
    qn = sum(f for z, f in rows if z < neutral)
    q_below = sum(f for z, f in rows if z >= neutral)
    return {
        "neutral": round(neutral * 1e3),
        "settling": round(settling * 1e3),
        "Qn": round(qn, 1),
        "Qbelow": round(q_below, 1),
        "Qb": round(qb, 1),
        "W": round(weight, 1),
    }


def swelling(
    profile: Any, single: dict[str, Any], zone: float, construction: Any = None
) -> dict[str, Any]:
    """The swelling uplift on a pile and the resistance below the zone [kN] (see the module
    notes): ``{"zone" mm, "U", "Qbelow", "R"}``, R = upliftSkin Qs(below) + W (the pack's
    share, 0.7 in the default pack)."""
    from saengine.substructure.piles import uplift_skin

    rows, _ = _slices(profile, single, zone, construction)
    uplift = sum(f for z, f in rows if z < zone)
    below = sum(f for z, f in rows if z >= zone)
    return {
        "zone": round(zone * 1e3),
        "U": round(uplift, 1),
        "Qbelow": round(below, 1),
        "R": round(uplift_skin() * below + float(single["W"]), 1),
    }


def _axial_capacity(kind: str, d: float, fc: float, fy: float, reinforcement: Any) -> float:
    """φPn,max [kN] of the pile section (the plain section's φ 0.6 × 0.6 f'c Ag without bars)."""
    from saengine.design.rc import DesignError, section_of
    from saengine.library.objects import CircleProfile, RectangleProfile
    from saengine.substructure.piles import section_shape

    if reinforcement is not None and reinforcement.longitudinal:
        profile = (
            RectangleProfile(xDim=d, yDim=d) if kind == "driven" else CircleProfile(radius=d / 2)
        )
        try:
            return section_of(profile, reinforcement, fc, fy).phi_pn_max / 1e3
        except DesignError:
            pass
    return 0.60 * 0.60 * fc * section_shape(kind, d)[1] / 1e3


def _tension_capacity(kind: str, d: float, fc: float, fy: float, reinforcement: Any) -> float:
    """φ fy As [kN] of the pile section (0 without bars)."""
    groups = getattr(reinforcement, "longitudinal", None) or []
    steel = sum(g.count * math.pi * g.dia**2 / 4 for g in groups)
    return 0.9 * fy * steel / 1e3


def checks(
    profile: Any,
    single: dict[str, Any],
    design: Any,
    service_max: float,
    service_min: float,
    sustained: float,
    factored_max: float,
    section: dict[str, Any] | None,
    construction: Any = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Downdrag and swelling checks of a cap's piles: ``single`` the pile's capacity,
    ``design`` the substructure's design choices, the largest and least service pile loads,
    the sustained (gravity) load and the largest factored load per pile [kN], ``section``
    ``{"fc", "fy", "reinforcement"}``. Returns ``(checks, notes, detail)``."""
    from saengine.design.check import _check

    found = rules()
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    detail: dict[str, Any] = {}
    if found is None:
        return out, [pile_static.not_covered("Negative skin friction")], detail
    fs = float(single["factors"]["compression"])
    kind = single["kind"]
    d = float(single["diameter"])
    if getattr(design, "downdrag", True):
        settling, why = settling_depth(profile, getattr(design, "downdragDepth", None))
        head = single["head"] / 1e3
        if settling is not None and settling > head + 1e-6:
            result = neutral_point(profile, single, sustained, settling, construction)
            detail["downdrag"] = {**result, "basis": why}
            qa = (result["Qbelow"] + result["Qb"] - result["W"]) / fs
            out.append(
                _check(
                    "Pile with downdrag",
                    service_max + result["Qn"],
                    max(qa, 0.0),
                    "kN",
                    None,
                    f"largest service pile load + dragload Qn = {result['Qn']:.0f} kN to the "
                    f"neutral point at {result['neutral']:.0f} mm ({why}); against the shaft "
                    f"below it and the base, ({result['Qbelow']:.0f} + {result['Qb']:.0f} - "
                    f"{result['W']:.0f}) / {fs:g} ({cite('downdrag')})",
                )
            )
            if section is not None:
                factor = found.dragloadFactor
                capacity = _axial_capacity(
                    kind, d, section["fc"], section["fy"], section.get("reinforcement")
                )
                out.append(
                    _check(
                        "Pile section at the neutral point",
                        factored_max + factor * result["Qn"],
                        capacity,
                        "kN",
                        None,
                        f"largest factored pile load + {factor:g} × Qn "
                        f"({cite('downdrag.dragloadFactor')}) against φPn,max",
                    )
                )
            notes.append(
                "negative skin friction may be reduced by bitumen or other viscous coatings on "
                f"the shaft through the settling soil ({cite('downdrag')})"
            )
    zone, why = expansive_depth(profile, getattr(design, "swellingDepth", None))
    if zone is not None and zone > single["head"] / 1e3 + 1e-6:
        result = swelling(profile, single, zone, construction)
        detail["swelling"] = {**result, "basis": why}
        fs_up = float(single["factors"]["uplift"])
        resisting = max(service_min, 0.0)
        out.append(
            _check(
                "Pile against swelling uplift",
                result["U"],
                result["R"] / fs_up + resisting,
                "kN",
                None,
                f"skin friction in the swelling zone ({why}) against 0.7 Qs below it + W = "
                f"{result['R']:.0f} kN over {fs_up:g} and the least service pile load "
                f"{resisting:.0f} kN ({cite('downdrag')})",
            )
        )
        tension = result["U"] - resisting
        if tension > 0 and section is not None:
            out.append(
                _check(
                    "Pile tension from swelling",
                    tension,
                    _tension_capacity(
                        kind, d, section["fc"], section["fy"], section.get("reinforcement")
                    ),
                    "kN",
                    None,
                    "swelling uplift less the least service pile load against φ fy As; the bars "
                    "through the swelling zone and anchored below it",
                )
            )
        notes.append(
            "expansive soil: leave a clear gap between the ground and the underside of the caps "
            "and grade beams so the swelling ground cannot lift them; coatings on the shaft in "
            f"the swelling zone reduce the uplift ({cite('downdrag')})"
        )
    return out, notes, detail
