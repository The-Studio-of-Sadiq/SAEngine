"""Integrator glue: the structural steel members of the design report and of the design mode.

Joins the steel modules to :mod:`saengine.design.check` and :mod:`saengine.design.proposal`:

- :func:`design_member`: one steel beam, column or brace of the analysis, checked to the default pack's BNBC 2020
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
from saengine.design.steel import composite as composite_design
from saengine.design.steel.lengths import member_lengths

#: The design report's kinds of steel members by object type kind.
KINDS = {"beam": "beam", "column": "column", "brace": "brace"}

#: The method lines of the design report when steel members were designed.


def _method() -> list[str]:
    """``METHOD``: the method text of the design report, with the clauses of the code pack in
    force (read as a module attribute)."""
    return [
        *steel_members.METHOD,
        (
            "Steel connections (when the object type sets one): fin plate, shear end plate or brace "
            "gusset checked for the member's end shears or axial forces, Part 6 Sec 10.10 of the code pack "
            "(bolts, bearing, block shear, welds, the Whitmore section); listed as 'Connection: ...' "
            "checks of the member. The analysis pins these member ends (no end moment); an end "
            "kept rigid (at a support or a free end) is flagged as 'end moment at a simple "
            "connection'. Flange-plate moment connections (beam ends kept rigid; with the column "
            "flange, web and panel zone checks of Sec 10.10.10), cover-plate splices (Sec "
            "10.10.6), column base plates on concrete (bearing Sec 10.10.8, anchor rod steel) and "
            "welded HSS truss joints (Sec 10.11.2) are checked the same way when the type sets "
            "them; also slip-critical bolts, end plates under axial tension (prying), the column "
            "stiffeners and doublers (Sec 10.10.10.8-9), plates and cap plates on HSS (Sec 10.11.1), "
            "overlapped K joints and HSS moment connections (Sec 10.11.3)."
        ),
        *composite_design.METHOD,  # B32: composite beams and columns
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


def _steel_of(mats: dict[str, Any], material_id: str | None, what: str) -> Any:
    """The steel material ``material_id`` as a design material, None when not given."""
    from saengine.design.steel_proposal import SteelMaterial

    found = mats.get(material_id) if material_id else None
    if found is None:
        return None
    if not is_steel(found):
        raise ValueError(f"{what} material '{found.id}' is not structural steel")
    return SteelMaterial.from_material(found)


def _section_named(name: str | None, what: str) -> Any:
    from saengine.library.steel_sections import find

    if not name:
        return None
    section = find(name)
    if section is None:
        raise ValueError(f"{what} section '{name}' is not in the steel sections table")
    return section


#: Descriptions of the connection kinds in the design report.
DESCRIPTIONS = {
    "finPlate": "fin plate (shear tab) at both ends",
    "endPlate": "shear end plate at both ends",
    "gusset": "bolted gusset at both ends",
    "flangePlate": "bolted flange-plate moment connection at both ends",
    "hssJoint": "welded HSS truss joint at both ends",
    "coverPlate": "bolted cover-plate splice",
    "basePlate": "column base plate and anchor rods",
    "hssMoment": "welded HSS moment connection at both ends",
    "capPlate": "cap plate on the HSS column top",
}


def _end_forces(stations: list[Any]) -> list[tuple[str | None, float, float]]:
    """``(combination, V [N], N [N] tension +)`` at both ends of every combination."""
    rows = []
    for st in stations:
        if not len(st.s):
            continue
        for k in (0, -1):
            rows.append((st.combination, float(st.Vy[k]), -float(st.P[k])))
    return rows


def _end_moment_rows(stations: list[Any]) -> list[tuple[str | None, float, float, float]]:
    """``(combination, N [N] tension +, M in-plane (major) [N·mm], M out-of-plane (minor))`` at
    both ends of every combination."""
    rows = []
    for st in stations:
        if not len(st.s):
            continue
        for k in (0, -1):
            rows.append((st.combination, -float(st.P[k]), float(st.Mx[k]), float(st.My[k])))
    return rows


def _top_rows(stations: list[Any]) -> list[tuple[str | None, float]]:
    """``(combination, P [N] compression +)`` at the member's upper (last) end."""
    return [(st.combination, float(st.P[-1])) for st in stations if len(st.s)]


def _end_rows(stations: list[Any]) -> list[tuple[str | None, float, float]]:
    """``(combination, M [N·mm], V [N])`` at both ends of every combination."""
    rows = []
    for st in stations:
        if not len(st.s):
            continue
        for k in (0, -1):
            rows.append((st.combination, float(st.Mx[k]), float(st.Vy[k])))
    return rows


def _rows_at(stations: list[Any], s: float) -> list[tuple[str | None, float, float, float]]:
    """``(combination, P, Mx, Vy)`` at the station nearest ``s`` [m] of every combination;
    empty when ``s`` is beyond the member."""
    rows = []
    for st in stations:
        if not len(st.s) or s > float(st.s[-1]) + 1e-6:
            continue
        k = int(abs(st.s - s).argmin())
        rows.append((st.combination, float(st.P[k]), float(st.Mx[k]), float(st.Vy[k])))
    return rows


def _base_rows(
    stations: list[Any], pieces: list[Any], project: dict[str, Any] | None
) -> list[tuple[str | None, float, float, float]]:
    """``(combination, P, V, M)`` at the column's lower end when it stands on a support (a node
    of the analysis model restrained in translation there); empty otherwise."""
    if not project or not pieces:
        return []
    ends = [p.start for p in pieces if p.start is not None]
    ends += [p.end for p in pieces if p.end is not None]
    if not ends:
        return []
    low = min(ends, key=lambda xyz: float(xyz[2]))
    supported = any(
        all((n.get("restraint") or [False] * 3)[:3])
        and sum((float(a) - float(b)) ** 2 for a, b in zip(n["coords"], low)) < 1e-6
        for n in project.get("nodes", [])
    )
    if not supported:
        return []
    rows = []
    for st in stations:
        if not len(st.s):
            continue
        v = (float(st.Vx[0]) ** 2 + float(st.Vy[0]) ** 2) ** 0.5
        m = (float(st.Mx[0]) ** 2 + float(st.My[0]) ** 2) ** 0.5
        rows.append((st.combination, float(st.P[0]), v, m))
    return rows


def connection_results(
    object_type: Any,
    material: Any,
    mats: dict[str, Any],
    stations: list[Any],
    kind: str,
    pieces: list[Any] | None = None,
    project: dict[str, Any] | None = None,
    seismic: Any = None,
) -> list[dict[str, Any]]:
    """The checks of the type's connection, splice and base plate, the end connection first
    (each with ``end`` and a ``description``). Raises ``ValueError`` or ``TypeError`` when one
    cannot be checked."""
    from saengine.design import steel_connections as sc
    from saengine.design.steel_proposal import SteelMaterial
    from saengine.library.steel_sections import section_of_profile

    member = SteelMaterial.from_material(material)
    section = section_of_profile(object_type.profile)
    results: list[dict[str, Any]] = []
    connection = getattr(object_type, "connection", None)
    if connection is not None:
        plate = _steel_of(mats, connection.plateMaterial, "plate")
        if connection.type == "flangePlate":
            if kind != "beam":
                raise ValueError("flange-plate moment connections are for beams")
            result = sc.check_flange_plate(
                connection,
                section,
                member,
                plate,
                _end_rows(stations),
                _section_named(connection.columnSection, "column"),
                _steel_of(mats, connection.columnMaterial, "column"),
            )
        elif connection.type == "hssJoint":
            chord = _section_named(connection.chordSection, "chord")
            if chord is None:
                raise ValueError("the HSS joint has no chord section")
            result = sc.check_hss_joint(
                connection,
                section,
                member,
                chord,
                _steel_of(mats, connection.chordMaterial, "chord"),
                _connection_demands(stations, "brace"),
                _section_named(connection.overlappedSection, "overlapped branch"),
                _steel_of(mats, connection.overlappedMaterial, "overlapped branch"),
            )
        elif connection.type == "hssMoment":
            if kind != "beam":
                raise ValueError("HSS moment connections are for beams")
            chord = _section_named(connection.chordSection, "chord")
            if chord is None:
                raise ValueError("the HSS moment connection has no chord section")
            result = sc.check_hss_moment(
                connection,
                section,
                member,
                chord,
                _steel_of(mats, connection.chordMaterial, "chord"),
                _end_moment_rows(stations),
            )
        elif connection.type == "finPlate":
            result = sc.check_fin_plate(
                connection,
                section,
                member,
                plate,
                _connection_demands(stations, kind),
                _section_named(connection.supportSection, "support"),
                _steel_of(mats, connection.supportMaterial, "support"),
            )
        elif connection.type == "endPlate":
            result = sc.check_end_plate(
                connection,
                section,
                member,
                plate,
                _connection_demands(stations, kind),
                _end_forces(stations),
            )
        else:
            result = sc.check_connection(
                connection, section, member, plate, _connection_demands(stations, kind)
            )
        if connection.type in ("finPlate", "endPlate", "gusset"):
            moment = _end_moment_check(stations)
            if moment is not None:
                result["checks"].append(moment)
        result["end"] = "both"
        result["description"] = DESCRIPTIONS.get(connection.type, connection.type)
        results.append(result)
    splice = getattr(object_type, "splice", None)
    if splice is not None and kind in ("beam", "column"):
        rows = _rows_at(stations, splice.distance / 1e3)
        if rows:
            result = sc.check_splice(
                splice,
                section,
                member,
                _steel_of(mats, splice.plateMaterial, "plate"),
                rows,
                column=kind == "column",
            )
            result["end"] = None
            result["description"] = (
                f"{DESCRIPTIONS['coverPlate']} {splice.distance:g} mm from the lower end"
            )
            results.append(result)
    base = getattr(object_type, "basePlate", None)
    if base is not None and kind == "column":
        rows = _base_rows(stations, pieces or [], project)
        if rows:
            result = sc.check_base_plate(
                base, section, member, _steel_of(mats, base.plateMaterial, "plate"), rows, seismic
            )
            result["end"] = None
            result["description"] = DESCRIPTIONS["basePlate"]
            results.append(result)
    cap = getattr(object_type, "capPlate", None)
    if cap is not None and kind == "column":
        rows = _top_rows(stations)
        if rows:
            result = sc.check_cap_plate(cap, section, member, rows)
            result["end"] = None
            result["description"] = DESCRIPTIONS["capPlate"]
            results.append(result)
    return results


def connection_result(
    object_type: Any, material: Any, mats: dict[str, Any], stations: list[Any], kind: str
) -> dict[str, Any] | None:
    """The checks of the type's end connection (None when it has none), with ``end`` "both"
    and a ``description``. Raises ``ValueError`` or ``TypeError`` when it cannot be checked."""
    if getattr(object_type, "connection", None) is None:
        return None
    found = connection_results(object_type, material, mats, stations, kind)
    return found[0] if found else None


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
        connections = connection_results(
            object_type, material, mats, stations, kind, pieces, project, options.anchors
        )
    except (ValueError, TypeError, KeyError) as error:
        connections = []
        entry["section"]["notes"] = [
            *entry["section"].get("notes", []),
            f"connection not checked: {error}",
        ]
    if connections:
        entry["connections"] = connections
        for connection in connections:
            for check in connection["checks"]:
                entry["checks"].append({**check, "name": f"Connection: {check['name']}"})
        strength = [c for c in entry["checks"] if not c["flag"]]
        entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
        entry["ok"] = all(c["ok"] for c in strength)
    lengths = member_lengths(project, pieces, turned, options.lengths)
    # B32: a composite beam or column's checks (none for a steel-alone type).
    composite_design.apply(
        entry, kind, object_type, material, mats, stations, lengths, list(combinations)
    )
    collected = {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "object": object_type,
        "material": material,
        "lengths": lengths,
        "stations": stations,
        # B17: the stability design method, for the design mode's re-checks.
        "options": steel_members.SteelOptions(stability=options.stability)
        if options.stability is not None
        else None,
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
            SteelMemberDemand(m["id"], m["lengths"], m["stations"], m["kind"], m.get("options"))
        )
        materials[m["material"].id] = SteelMaterial.from_material(m["material"])
    types = [originals[t] for t in demands if t in originals]
    found = steel_design_proposal(types, materials, demands)
    notes = [f"{s['type']}: {s['reason']}" for s in found.get("skipped", [])]
    return found["types"], notes


__all__ = [
    "KINDS",
    "connection_result",
    "connection_results",
    "design_member",
    "is_steel",
    "proposal_entries",
]


def __getattr__(name: str) -> list[str]:
    # The method text names the clauses of the pack in force: built when it is read.
    if name == "METHOD":
        return _method()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
