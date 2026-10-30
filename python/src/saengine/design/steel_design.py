"""Integrator glue: the structural steel members of the design report and of the design mode.

Joins the steel modules to :mod:`saengine.design.check` and :mod:`saengine.design.proposal`:

- :func:`design_member`: one steel beam, column or brace of the analysis, checked to BNBC 2020
  Part 6 Chapter 10 by :func:`saengine.design.steel.design_steel_member`, with the simple
  connection of its object type (``connection`` of 04 Objects, :mod:`saengine.design.
  steel_connections`) checked for the member's end forces: beams for the end shears along the
  depth, braces for their axial forces (tension and compression). The connection's checks are
  listed under ``connections`` and repeated in the member's ``checks`` as ``"Connection: ..."``,
  so they count towards its utilisation.
- :func:`proposal_entries`: the design mode's steel entries, the lightest section of the
  type's family passing every member (:func:`saengine.design.steel_proposal.
  steel_design_proposal`, with the members' own brace points and stations).
"""

from __future__ import annotations

from typing import Any

from saengine.design import steel as steel_members
from saengine.design.steel.lengths import member_lengths

#: The design report's kinds of steel members by object type kind.
KINDS = {"beam": "beam", "column": "column", "brace": "brace"}

#: The method lines of the design report when steel members were designed.
METHOD = [
    *steel_members.METHOD,
    (
        "Steel connections (when the object type sets one): fin plate, shear end plate or brace "
        "gusset checked for the member's end shears or axial forces, BNBC 2020 Part 6 Sec 10.10 "
        "(bolts, bearing, block shear, welds, the Whitmore section); listed as 'Connection: ...' "
        "checks of the member. The analysis pins these member ends (no end moment); an end "
        "kept rigid (at a support or a free end) is flagged as 'end moment at a simple "
        "connection'."
    ),
]


def is_steel(material: Any) -> bool:
    """Whether members of ``material`` are designed as structural steel."""
    return steel_members.is_steel_member(material)


def _connection_demands(stations: list[Any], kind: str) -> list[tuple[str | None, float]]:
    """The connection's demands from the member's stations: a beam's end shears along the
    depth [N], a brace's (and column's) axial forces, tension positive [N], at every station
    (the gusset checks take the largest tension and the largest compression)."""
    demands: list[tuple[str | None, float]] = []
    for st in stations:
        if not len(st.s):
            continue
        if kind == "beam":
            demands.append((st.combination, float(st.Vy[0])))
            demands.append((st.combination, float(st.Vy[-1])))
        else:
            demands += [(st.combination, -float(p)) for p in st.P]
    return demands


#: An end moment above this share of the member's largest moment means the analysis held the end.
_END_MOMENT_SHARE = 0.05


def _end_moment_check(stations: list[Any]) -> dict[str, Any] | None:
    """A flag when the analysis put a moment through a simple connection: the derived model
    pins these ends (:func:`saengine.fem.derive._release_simple_ends`) except at a support or a
    free end, where the moment stays and the connection checks (shear or axial only) do not
    cover it. None when no end carries more than 5 % of the member's largest moment."""
    worst = (0.0, None)
    peak = 0.0
    for st in stations:
        if not len(st.s):
            continue
        moment = (st.Mx**2 + st.My**2) ** 0.5
        peak = max(peak, float(moment.max()))
        for value in (float(moment[0]), float(moment[-1])):
            if value > worst[0]:
                worst = (value, st.combination)
    if peak <= 0 or worst[0] <= _END_MOMENT_SHARE * peak:
        return None
    return {
        "name": "end moment at a simple connection",
        "demand": round(worst[0] / 1e6, 2),
        "capacity": round(_END_MOMENT_SHARE * peak / 1e6, 2),
        "unit": "kN·m",
        "utilisation": round(worst[0] / (_END_MOMENT_SHARE * peak), 3),
        "combination": worst[1],
        "ok": False,
        "note": (
            "the analysis kept this end rigid (at a support or a free end), so a moment reaches "
            "the simple connection, which is checked for shear or axial force only: pin the end "
            "in the model (a pinned support) or use a moment connection"
        ),
        "flag": True,
        "clause": None,
    }


def connection_result(
    object_type: Any, material: Any, mats: dict[str, Any], stations: list[Any], kind: str
) -> dict[str, Any] | None:
    """The checks of the type's simple connection (None when it has none), with ``end`` "both"
    and a ``description``. Raises ``ValueError`` or ``TypeError`` when it cannot be checked."""
    from saengine.design import steel_connections as sc
    from saengine.design.steel_proposal import SteelMaterial
    from saengine.library.steel_sections import section_of_profile

    connection = getattr(object_type, "connection", None)
    if connection is None:
        return None
    plate = mats.get(connection.plateMaterial) if connection.plateMaterial else None
    if plate is not None and not is_steel(plate):
        raise ValueError(f"plate material '{plate.id}' is not structural steel")
    result = sc.check_connection(
        connection,
        section_of_profile(object_type.profile),
        SteelMaterial.from_material(material),
        SteelMaterial.from_material(plate) if plate is not None else None,
        _connection_demands(stations, kind),
    )
    moment = _end_moment_check(stations)
    if moment is not None:
        result["checks"].append(moment)
    result["end"] = "both"
    result["description"] = {
        "finPlate": "fin plate (shear tab) at both ends",
        "endPlate": "shear end plate at both ends",
        "gusset": "bolted gusset at both ends",
    }.get(connection.type, connection.type)
    return result


def design_member(
    member_id: str,
    kind: str,
    object_type: Any,
    material: Any,
    mats: dict[str, Any],
    pieces: list[Any],
    combinations: list[str],
    turned: bool,
    project: dict[str, Any],
    options: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The design report entry of one steel member and what the design mode needs of it
    (``{"id", "kind", "type", "object", "material", "lengths", "stations", "checks"}``).
    Raises :class:`saengine.design.steel.SteelDesignError` when it cannot be checked."""
    options = steel_members.SteelOptions.of(options)
    entry = steel_members.design_steel_member(
        member_id,
        kind,
        object_type.id,
        object_type,
        material,
        pieces,
        combinations,
        turned,
        project,
        options,
    )
    entry["material"] = material.id
    stations = steel_members.member_stations(pieces, combinations, turned)
    try:
        connection = connection_result(object_type, material, mats, stations, kind)
    except (ValueError, TypeError, KeyError) as error:
        connection = None
        entry["section"]["notes"] = [
            *entry["section"].get("notes", []),
            f"connection not checked: {error}",
        ]
    if connection is not None:
        entry["connections"] = [connection]
        for check in connection["checks"]:
            entry["checks"].append({**check, "name": f"Connection: {check['name']}"})
        strength = [c for c in entry["checks"] if not c["flag"]]
        entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
        entry["ok"] = all(c["ok"] for c in strength)
    collected = {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "object": object_type,
        "material": material,
        "lengths": member_lengths(project, pieces, turned, options.lengths),
        "stations": stations,
        "checks": entry["checks"],
    }
    return entry, collected


def proposal_entries(
    collected: list[dict[str, Any]], originals: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """The design mode's steel type entries (:func:`saengine.design.steel_proposal.
    propose_type`'s shape, with ``family`` and ``current``/``proposed`` ``{section, mass,
    profile, text}``) for the steel members ``collected`` by :func:`design_member`, and notes.
    ``originals``: the 04 Objects types as JSON by id."""
    from saengine.design.steel_proposal import (
        SteelMaterial,
        SteelMemberDemand,
        steel_design_proposal,
    )

    if not collected:
        return [], []
    demands: dict[str, list[SteelMemberDemand]] = {}
    materials: dict[str, SteelMaterial] = {}
    for m in collected:
        demands.setdefault(m["type"], []).append(
            SteelMemberDemand(m["id"], m["lengths"], m["stations"], m["kind"])
        )
        materials[m["material"].id] = SteelMaterial.from_material(m["material"])
    types = [originals[t] for t in demands if t in originals]
    found = steel_design_proposal(types, materials, demands)
    notes = [f"{s['type']}: {s['reason']}" for s in found.get("skipped", [])]
    return found["types"], notes


__all__ = ["KINDS", "connection_result", "design_member", "is_steel", "proposal_entries"]
