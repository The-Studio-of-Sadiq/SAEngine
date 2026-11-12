"""Embedded anchor bolts in masonry: allowable shear and tension, their interaction and the
placement rules, from the code pack's ``masonry.anchorBolts`` (absent: not covered by the pack).

Allowable loads (not the factored strengths of :mod:`saengine.design.anchors`, which anchor to
concrete):

- shear Bv: the lesser of shear.factor (f'm Ab)^exponent [N] and shear.steelShare Ab fy, and
  the pack's shear table where the bolt's diameter and f'm are in it (the row at or below f'm,
  the column at or below the diameter). The masonry value (and the table's) falls linearly to
  zero at an edge distance of ``edgeZero`` when the edge distance is below edgeDiameters db,
  and to spacingShare at spacingMin db when bolts are closer than spacingDiameters db;
- tension Bt: the lesser of tension.factor Ap √f'm and tension.steelShare Ab fy, with Ap = π
  min(lb, lbe)² less overlapShare of the area overlapping the next bolts' (a bolt in a row has a
  neighbour on each side), and the tables (masonry by min(lb, lbe), steel by diameter);
- combined bt/Bt + bv/Bv ≤ interaction;
- placement: edge distance, embedment (embedDiameters db and embedMin), spacing.

The tables are used only at or below the values the bolt has (no interpolation upward), so the
lesser of the formulas and the tables satisfies both routes the code allows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.design import masonry as M
from saengine.design.ductile_members import _row


@dataclass(frozen=True)
class AnchorBolt:
    """One bolt of a row of embedded anchor bolts [mm, MPa]."""

    dia: float
    embedment: float  # lb: the effective embedment length
    edge: float  # lbe: to the edge of the masonry in the direction of the load
    spacing: float | None = None  # to the next bolt; None: a single bolt
    fy: float = 250.0
    kind: str = "headed"  # "headed", "plate" or "bent"

    @property
    def area(self) -> float:
        return math.pi * self.dia**2 / 4.0


def rules() -> Any:
    """The code pack's anchor bolt rules, or None (not covered)."""
    return M.table().anchorBolts


def covered() -> bool:
    return rules() is not None


def _lookup(table: Any, fm: float, column: float) -> float | None:
    """The table's value [N] at the row at or below ``fm`` and the column at or below
    ``column``; None below the first row or column."""
    if table is None:
        return None
    rows = [k for k, f in enumerate(table.fm) if f <= fm + 1e-9]
    cols = [k for k, c in enumerate(table.columns) if c <= column + 1e-9]
    if not rows or not cols:
        return None
    return float(table.values[rows[-1]][cols[-1]]) * 1e3


def _steel_lookup(table: Any, dia: float) -> float | None:
    if table is None:
        return None
    return _lookup(table, float(table.fm[0]), dia)


def edge_factor(bolt: AnchorBolt) -> float:
    """The share of the masonry shear at the bolt's edge distance."""
    s = rules().shear
    full = float(s["edgeDiameters"]) * bolt.dia
    zero = float(s["edgeZero"])
    if bolt.edge >= full:
        return 1.0
    if full <= zero:
        return 1.0
    return min(max((bolt.edge - zero) / (full - zero), 0.0), 1.0)


def spacing_factor(bolt: AnchorBolt) -> float:
    """The share of the masonry shear at the bolts' spacing."""
    if bolt.spacing is None:
        return 1.0
    s = rules().shear
    full = float(s["spacingDiameters"]) * bolt.dia
    low = float(s["spacingMin"]) * bolt.dia
    share = float(s["spacingShare"])
    if bolt.spacing >= full:
        return 1.0
    if bolt.spacing <= low:
        return share
    return share + (1.0 - share) * (bolt.spacing - low) / (full - low)


def allowable_shear(bolt: AnchorBolt, fm: float) -> tuple[float, str]:
    """(Bv [N], how it was found)."""
    r = rules()
    s = r.shear
    reduce = edge_factor(bolt) * spacing_factor(bolt)
    masonry = float(s["factor"]) * (fm * bolt.area) ** float(s["exponent"]) * reduce
    steel = float(s["steelShare"]) * bolt.area * bolt.fy
    values = {"masonry": masonry, "steel": steel}
    table = _lookup(r.shearTable, fm, bolt.dia)
    if table is not None:
        values["table"] = table * reduce
    which = min(values, key=values.get)
    note = ", ".join(f"{k} {v / 1e3:.2f} kN" for k, v in values.items())
    if reduce < 1.0:
        note += f"; edge and spacing × {reduce:.2f}"
    return values[which], f"{note}; {which} governs"


def projected_area(bolt: AnchorBolt) -> float:
    """Ap [mm²]: π min(lb, lbe)², less the pack's share of the overlap with a neighbour on each
    side when the bolts are closer than 2 min(lb, lbe)."""
    r = min(bolt.embedment, bolt.edge)
    area = math.pi * r * r
    s = bolt.spacing
    if s is not None and s < 2 * r:
        lens = 2 * r * r * math.acos(s / (2 * r)) - (s / 2) * math.sqrt(4 * r * r - s * s)
        area -= 2 * float(rules().tension["overlapShare"]) * lens
    return max(area, 0.0)


def allowable_tension(bolt: AnchorBolt, fm: float) -> tuple[float, str]:
    """(Bt [N], how it was found)."""
    r = rules()
    t = r.tension
    ap = projected_area(bolt)
    values = {
        "masonry": float(t["factor"]) * ap * math.sqrt(fm),
        "steel": float(t["steelShare"]) * bolt.area * bolt.fy,
    }
    radius = min(bolt.embedment, bolt.edge)
    table = _lookup(r.tensionTable, fm, radius)
    if table is not None:  # a single bolt's value: reduced by the overlap like Ap
        values["masonry table"] = table * ap / (math.pi * radius * radius)
    steel_table = _steel_lookup(r.steelTension, bolt.dia)
    if steel_table is not None:
        values["steel table"] = steel_table
    which = min(values, key=values.get)
    note = f"Ap {ap:.0f} mm²; " + ", ".join(f"{k} {v / 1e3:.2f} kN" for k, v in values.items())
    return values[which], f"{note}; {which} governs"


def bolt_checks(
    bolt: AnchorBolt, fm: float, tension: float, shear: float, combination: str | None = None
) -> list[dict[str, Any]]:
    """The rows of one bolt under ``tension`` and ``shear`` [N] (service loads)."""
    r = rules()
    if r is None:
        return []
    bt_allow, bt_note = allowable_tension(bolt, fm)
    bv_allow, bv_note = allowable_shear(bolt, fm)
    rows = [
        _row(
            f"Anchor bolt tension bt ≤ Bt ({M.clause('anchorTension')})",
            tension / 1e3,
            bt_allow / 1e3,
            "kN",
            combination,
            bt_note,
        ),
        _row(
            f"Anchor bolt shear bv ≤ Bv ({M.clause('anchorShear')})",
            shear / 1e3,
            bv_allow / 1e3,
            "kN",
            combination,
            bv_note,
        ),
    ]
    combined = (tension / bt_allow if bt_allow > 0 else math.inf) + (
        shear / bv_allow if bv_allow > 0 else math.inf
    )
    rows.append(
        _row(
            f"Anchor bolt bt/Bt + bv/Bv ≤ {float(r.interaction):g} ({M.clause('anchorCombined')})",
            combined,
            float(r.interaction),
            "",
            combination,
        )
    )
    place = M.clause("anchorPlacement")
    rows.append(_row(f"Anchor bolt edge distance ({place})", float(r.edgeMin), bolt.edge, "mm"))
    embed = max(float(r.embedDiameters) * bolt.dia, float(r.embedMin))
    rows.append(_row(f"Anchor bolt embedment ({place})", embed, bolt.embedment, "mm"))
    if bolt.spacing is not None:
        least = float(r.spacingDiameters) * bolt.dia
        rows.append(_row(f"Anchor bolt spacing ({place})", least, bolt.spacing, "mm"))
    return rows


def wall_anchorage_checks(
    bolts: Any, fm: float, force_per_metre: float, shear_per_metre: float = 0.0
) -> list[dict[str, Any]]:
    """The rows of a wall's anchor bolts (a ``library.objects.MasonryAnchorBolts``) under the
    wall's anchorage force per metre [kN/m]: a bolt in the face of the wall takes it as tension,
    a bolt in the top of the wall as shear; ``shear_per_metre`` [kN/m] the other way (gravity
    on a ledger, or diaphragm shear on a sill)."""
    if rules() is None:
        return []
    bolt = AnchorBolt(
        float(bolts.dia),
        float(bolts.embedment),
        float(bolts.edge),
        float(bolts.spacing),
        float(bolts.fy),
        str(bolts.kind),
    )
    per_bolt = float(bolts.spacing)  # N per bolt for 1 kN/m (= 1 N/mm) of wall
    anchorage = force_per_metre * per_bolt
    other = shear_per_metre * per_bolt
    if bolts.placement == "face":
        tension, shear = anchorage, other
    else:
        tension, shear = 0.0, math.hypot(anchorage, other)
    return bolt_checks(bolt, fm, tension, shear)


__all__ = [
    "AnchorBolt",
    "allowable_shear",
    "allowable_tension",
    "bolt_checks",
    "covered",
    "edge_factor",
    "projected_area",
    "rules",
    "spacing_factor",
    "wall_anchorage_checks",
]
