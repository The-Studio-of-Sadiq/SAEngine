"""Built-up compression members: two or more shapes joined by intermediate connectors, lacing
or tie plates (B31; the code pack's ``steel.members.builtUp``, the default pack's BNBC 2020 Part 6 Sec 10.5.6).

The member's profile is the built-up section as the analysis carries it; :class:`BuiltUp`
describes how its components are joined (a design overwrite of the member or its object type,
:class:`saengine.library.modifiers.BuiltUpMember`):

- the modified slenderness (KL/r)m for the buckling mode that shears the connectors (about the
  member axis ``axis``): snug-tight bolts √((KL/r)o² + (a/ri)²), welds or pretensioned bolts
  √((KL/r)o² + k α²/(1+α²) (a/rib)²) with α = h / (2 rib) (:func:`modified_slenderness`);
- the connector spacing K a / ri against the pack's share of the member's governing KL/r, the
  fastener spacing along outside plates, the lacing bars' L/r and the tie plates' size
  (:func:`dimensional_checks`), and the shear the lacing is designed for (:func:`lacing_shear`).

The component's radii come from the section table when ``component`` names a section (its
least radius ri, and rib about the axis parallel to the member's buckling axis), else as given.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.design.steel.torsion import clause, members_data


@dataclass(frozen=True)
class BuiltUp:
    """How a built-up member's components are joined [mm]."""

    connectors: str = "snugTight"  # "snugTight" or "welded" (welded / pretensioned bolted)
    spacing: float = 0.0  # a, between connectors
    axis: str = "y"  # the member axis whose buckling shears the connectors
    component: str | None = None  # a section of the table
    ri: float | None = None  # least radius of gyration of a component
    rib: float | None = None  # of a component about its axis parallel to ``axis``
    separation: float | None = None  # h, between the components' centroids
    outside_plate: float | None = None  # thickness of the thinner outside plate
    plate_pitch: float | None = None  # fastener / weld spacing along it
    staggered: bool = False
    lacing: str = "none"  # "none", "single", "double"
    lacing_length: float | None = None
    lacing_r: float | None = None
    tie_distance: float | None = None  # between the lines of fasteners / welds of a tie plate
    tie_length: float | None = None  # of the end tie plates
    tie_thickness: float | None = None

    @classmethod
    def of(cls, value: Any) -> BuiltUp | None:
        """From a :class:`saengine.library.modifiers.BuiltUpMember` (or its dict); None for
        None."""
        if value is None or isinstance(value, BuiltUp):
            return value
        if hasattr(value, "model_dump"):
            value = value.model_dump()
        names = {
            "connectors": "connectors",
            "spacing": "spacing",
            "axis": "axis",
            "component": "component",
            "ri": "ri",
            "rib": "rib",
            "separation": "separation",
            "outsidePlate": "outside_plate",
            "platePitch": "plate_pitch",
            "staggered": "staggered",
            "lacing": "lacing",
            "lacingLength": "lacing_length",
            "lacingRadius": "lacing_r",
            "tieDistance": "tie_distance",
            "tieLength": "tie_length",
            "tieThickness": "tie_thickness",
        }
        found = {names[k]: v for k, v in dict(value).items() if k in names and v is not None}
        return cls(**found)

    def radii(self) -> tuple[float | None, float | None]:
        """(ri, rib): as given, else from the component's section in the table."""
        ri, rib = self.ri, self.rib
        if (ri is None or rib is None) and self.component:
            from saengine.library.steel_sections import find

            section = find(self.component)
            if section is not None:
                ri = ri if ri is not None else section.r_min
                rib = rib if rib is not None else (section.ry if self.axis == "y" else section.rx)
        return ri, rib


def modified_slenderness(built: BuiltUp, kl_r0: float) -> tuple[float, str, str]:
    """(KL/r)m of the member whose slenderness acting as a unit is ``kl_r0``, the note and the
    clause; ``kl_r0`` unchanged (and a note why) when the data are missing."""
    data = members_data()
    if data is None or built.spacing <= 0:
        return kl_r0, "", ""
    ri, rib = built.radii()
    a = built.spacing
    if built.connectors == "welded":
        if not rib or not built.separation:
            return kl_r0, "built-up: rib and h needed for Eq 6.10.35, not modified", ""
        alpha = built.separation / (2 * rib)
        k = data.builtUp.welded
        m = math.sqrt(kl_r0**2 + k * alpha**2 / (1 + alpha**2) * (a / rib) ** 2)
        note = (
            f"built-up, welded / pretensioned connectors at a = {a:.0f} mm: α = h / 2rib = "
            f"{alpha:.2f}, (KL/r)m = {m:.1f} from (KL/r)o = {kl_r0:.1f}"
        )
        return m, note, clause("builtUpWelded")
    if not ri:
        return kl_r0, "built-up: ri needed for Eq 6.10.34, not modified", ""
    m = math.sqrt(kl_r0**2 + (a / ri) ** 2)
    note = (
        f"built-up, snug-tight bolts at a = {a:.0f} mm: a/ri = {a / ri:.1f}, (KL/r)m = {m:.1f} "
        f"from (KL/r)o = {kl_r0:.1f}"
    )
    return m, note, clause("builtUpSnug")


def lacing_shear(phi_pn: float) -> float:
    """The shear normal to the member the lacing is proportioned for [N] (0 without data)."""
    data = members_data()
    return data.builtUp.lacingShear * phi_pn if data is not None else 0.0


def _row(name: str, demand: float, capacity: float, note: str, ref: str, unit: str = "") -> dict:
    u = demand / capacity if capacity > 0 else 99.0
    return {
        "name": name,
        "demand": round(demand, 2),
        "capacity": round(capacity, 2),
        "unit": unit,
        "utilisation": round(u, 3),
        "combination": None,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": False,
        "clause": ref,
    }


def dimensional_checks(built: BuiltUp, governing: float, fy: float, e: float) -> list[dict]:
    """The dimensional limits of Sec 10.5.6.2 that the data allow (``governing``: the member's
    governing KL/r), as check rows."""
    data = members_data()
    if data is None:
        return []
    b = data.builtUp
    ref = clause("builtUpSpacing")
    rows: list[dict] = []
    ri, _ = built.radii()
    if built.spacing > 0 and ri:
        ka = b.componentK * built.spacing / ri
        rows.append(
            _row(
                "Built-up: connector spacing K a / ri",
                ka,
                b.componentShare * governing,
                f"a = {built.spacing:.0f} mm, ri = {ri:.1f} mm, K = {b.componentK:g}; limit "
                f"{b.componentShare:g} × KL/r = {governing:.1f}",
                ref,
            )
        )
    if built.outside_plate and built.plate_pitch:
        root = math.sqrt(e / fy)
        if built.staggered:
            limit = min(b.plateStaggered * root * built.outside_plate, b.plateStaggeredMax)
            how = f"staggered: {b.plateStaggered:g} √(E/Fy) t <= {b.plateStaggeredMax:g} mm"
        else:
            limit = min(b.plateSpacing * root * built.outside_plate, b.plateSpacingMax)
            how = f"{b.plateSpacing:g} √(E/Fy) t <= {b.plateSpacingMax:g} mm"
        rows.append(
            _row(
                "Built-up: fastener spacing along the outside plate",
                built.plate_pitch,
                limit,
                f"t = {built.outside_plate:g} mm, {how}",
                ref,
                "mm",
            )
        )
    if built.lacing in ("single", "double") and built.lacing_length and built.lacing_r:
        double = built.lacing == "double"
        length = built.lacing_length * (b.lacingDoubleLength if double else 1.0)
        limit = b.lacingDouble if double else b.lacingSingle
        rows.append(
            _row(
                f"Built-up: {built.lacing} lacing L/r",
                length / built.lacing_r,
                limit,
                f"L = {length:.0f} mm, r = {built.lacing_r:.1f} mm",
                ref,
            )
        )
    if built.tie_distance:
        if built.tie_length:
            rows.append(
                _row(
                    "Built-up: end tie plate length",
                    b.tiePlateEnd * built.tie_distance,
                    built.tie_length,
                    f"at least {b.tiePlateEnd:g} × the distance between the lines, "
                    f"{built.tie_distance:.0f} mm (intermediate plates "
                    f"{b.tiePlateIntermediate:g} ×)",
                    ref,
                    "mm",
                )
            )
        if built.tie_thickness:
            rows.append(
                _row(
                    "Built-up: tie plate thickness",
                    b.tiePlateThickness * built.tie_distance,
                    built.tie_thickness,
                    f"at least {b.tiePlateThickness:g} × {built.tie_distance:.0f} mm",
                    ref,
                    "mm",
                )
            )
    return rows


__all__ = ["BuiltUp", "dimensional_checks", "lacing_shear", "modified_slenderness"]
