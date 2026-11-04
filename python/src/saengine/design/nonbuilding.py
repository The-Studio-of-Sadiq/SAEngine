"""Seismic forces of non-building structures (alpha 9 P7): tanks on legs, towers and masts on
roofs, storage racks, signs, cooling towers.

The method and the coefficients are the code pack's ``nonBuilding`` table
(:class:`saengine.codes.practice_tables.NonBuildingTable`, method ``responseModification``);
a pack without it does not design non-building structures. The default pack's BNBC 2020 Part 6
Sec 2.5.18 adopts ASCE/SEI 7-05 Chapter 15 for them, with its own design spectrum (Sec 2.5).

A non-building structure is a piece of 07 MEP equipment whose ``nonBuilding`` names a type of
the table (:class:`saengine.library.mep.Equipment`); every piece of equipment keeps its
nonstructural component force too (:mod:`saengine.design.nonstructural`, the one home of
component forces), and this module says which governs:

- supported by the building (on a storey above the base) with Wp / (Wp + Ws) below
  ``supportedShare`` (Ws the building's seismic weight from the analysis' derivation): a
  nonstructural component, its component force governs;
- otherwise (on the ground, or heavier): V = Cs Wp with Cs = Sa(T) I / R of the project's
  design spectrum (:func:`saengine.fem.loads.design_acceleration`, R the type's, I the
  occupancy's seismic importance), at least a SDS I and b (``minimumCoefficient``), SDS the
  design spectrum's short-period plateau (R = I = 1); a rigid structure (T below
  ``rigidPeriod``) V = ``rigidFactor`` SDS I Wp. Without a period, the plateau (on the safe
  side). A heavy supported structure is analysed with the building (its interaction): the
  report says so, with the type's Ω0 for its anchorage and Cd for its displacements.

Units: kN, s, g.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from saengine.codes import context as code_context

TABLE = "nonBuilding"
#: Periods [s] the plateau SDS is searched over.
PLATEAU_PERIODS = [0.02 * k for k in range(1, 76)]


def table(pack: Any = None) -> Any | None:
    target = pack if pack is not None else code_context.current()
    return target.table(TABLE) if target.has(TABLE) else None


def plateau(site_class: str, z: Any) -> float:
    """SDS: the largest design spectral acceleration with R = I = 1 [g]."""
    from saengine.fem.loads import design_acceleration

    return max(design_acceleration(t, site_class, z, 1.0, 1.0) for t in PLATEAU_PERIODS)


def coefficient(
    type_id: str,
    period: float | None,
    site_class: str,
    z: Any,
    importance: float,
    pack: Any = None,
) -> dict[str, Any]:
    """Cs of a non-building structure of ``type_id`` and ``period`` [s] (None: the plateau):
    ``{"Cs", "SDS", "R", "omega0", "Cd", "rigid", "basis"}`` (the pack in force, or
    ``pack``)."""
    from saengine.fem.loads import design_acceleration

    rules = table(pack)
    row = rules.types[type_id]
    with code_context.using(pack) if pack is not None else nullcontext():
        sds = plateau(site_class, z)
        a, b = rules.minimumCoefficient
        if period is not None and period < rules.rigidPeriod:
            cs = rules.rigidFactor * sds * importance
            basis = (
                f"rigid (T = {period:.3f} s < {rules.rigidPeriod:g} s): Cs = "
                f"{rules.rigidFactor:g} SDS I = {rules.rigidFactor:g} × {sds:.3f} × "
                f"{importance:g}"
            )
            return {"Cs": cs, "SDS": sds, "R": row.R, "omega0": row.omega0, "Cd": row.Cd,
                    "rigid": True, "basis": basis}  # fmt: skip
        if period is None:
            sa = max(
                design_acceleration(t, site_class, z, importance, row.R) for t in PLATEAU_PERIODS
            )
            at = "the plateau (no period given)"
        else:
            sa = design_acceleration(period, site_class, z, importance, row.R)
            at = f"T = {period:.2f} s"
    least = max(a * sds * importance, b)
    cs = max(sa, least)
    basis = (
        f"Cs = Sa I / R at {at} = {sa:.4f} (R = {row.R:g}, I = {importance:g}), at least "
        f"{a:g} SDS I and {b:g} = {least:.4f}; SDS = {sds:.3f} g"
    )
    return {"Cs": cs, "SDS": sds, "R": row.R, "omega0": row.omega0, "Cd": row.Cd,
            "rigid": False, "basis": basis}  # fmt: skip


def building_weight(root: Path) -> float | None:
    """The building's seismic weight W [kN] of the analysis' last derivation, None without."""
    from saengine.report.build import DERIVATION_FILE

    try:
        data = json.loads((root / DERIVATION_FILE).read_text(encoding="utf-8"))
        return float(data["summary"]["seismicWeight"]["total_kN"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def structures(
    root: str | Path, mep: Any, settings: Any, ground: Any, elevations: dict[str, float], pack: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    """The non-building structures of 07 MEP (``mep``: its equipment with ``nonBuilding``):
    one row each ``{"id", "name", "type", "story", "W", "share", "Cs", "V", "omega0", "Cd",
    "governs", "basis"}``, and notes."""
    from saengine.library.settings import derived

    rules = table(pack)
    items = [e for e in getattr(mep, "equipment", []) or [] if getattr(e, "nonBuilding", None)]
    if not items:
        return [], []
    if rules is None:
        return [], [f"non-building structures: not covered by the code pack {pack.name}"]
    values = derived(settings)
    z = values["Z"]
    importance = float(values.get("seismicImportance") or 1.0)
    site = settings.site.siteClass
    ws = building_weight(Path(root))
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    for item in items:
        type_id = item.nonBuilding
        if type_id not in rules.types:
            notes.append(f"{item.id}: '{type_id}' is not a non-building type of the code pack")
            continue
        try:
            found = coefficient(type_id, getattr(item, "period", None), site, z, importance, pack)
        except (ValueError, KeyError) as error:
            notes.append(f"{item.id}: non-building force not worked out ({error})")
            continue
        w = float(item.operatingWeight)
        level = elevations.get(item.story)
        supported = level is not None and level > ground.base + 1.0
        share = w / (w + ws) if supported and ws else None
        if supported and share is not None and share < rules.supportedShare:
            governs = (
                f"component: Wp / (Wp + Ws) = {100 * share:.1f} % < "
                f"{100 * rules.supportedShare:g} %, its component force governs"
            )
        elif supported:
            governs = (
                "non-building structure analysed with the building (interaction)"
                + (f": Wp / (Wp + Ws) = {100 * share:.1f} %" if share is not None else
                   ": the building's seismic weight is not known yet (run the analysis)")
            )  # fmt: skip
        else:
            governs = "non-building structure on the ground"
        rows.append(
            {
                "id": item.id,
                "name": item.name or item.id,
                "type": rules.types[type_id].label,
                "story": item.story,
                "W": w,
                "share": share,
                "Cs": found["Cs"],
                "V": found["Cs"] * w,
                "R": found["R"],
                "omega0": found["omega0"],
                "Cd": found["Cd"],
                "governs": governs,
                "basis": found["basis"],
            }
        )
    clauses = rules.clauses or {}
    if rows:
        notes.append(
            "Non-building structures: "
            + "; ".join(str(clauses[k]) for k in ("required", "supported", "types") if k in clauses)
        )
    return rows, notes
