"""Integrator glue: the earthquake-resistant detailing of BNBC 2020 Part 6 Sec 8.3 (pp.
1088-1123) in the design report of :mod:`saengine.design.check`.

This module only wires the three rule modules into the design: it decides nothing of its own
beyond what each needs from the analysis and the building model.

- :mod:`saengine.design.seismic_rules`: which provisions apply (the Seismic Design Category,
  the system, the detailing level, each member's role and its Ω0 need), and the project-level
  checks (system permitted, materials of Sec 8.3.3.3, 8.3.3.4);
- :mod:`saengine.design.ductile_members`: the member checks (dimensions, steel ratios, hoop
  zones lo and so, Ash, splices: Sec 8.3.4, 8.3.5, 8.3.9, 8.3.10, 8.3.12);
- :mod:`saengine.design.ductile_joints`: the capacity design (strong column / weak beam Sec
  8.3.5.2, joints Sec 8.3.7, capacity shear Sec 8.3.8 and 8.3.10.3, members outside the
  seismic force-resisting system Sec 8.3.9.1, 8.3.12).

What this glue derives from the model, where BNBC gives no rule for it (SAEngine choices):

- the clear span ln of a beam: the smallest distance between the faces of consecutive
  supporting columns (frame joints along it), else its length less half of the end columns;
- the clear height lu of a column: per storey, the joint spacing less the deepest beam at the
  top joint; the largest sets lo (ln/6), the smallest the capacity shear (2 Mpr / lu);
- the combinations with earthquake: those with EX or EY, or a response spectrum envelope;
- the axial forces at a joint: the column pieces with an end at the joint's level.

Every detailing check's name starts with ``"Detailing: "`` (the workbench groups them) and has
a ``"clause"``; a failing one sets the member's utilisation, a passing one does not
(:func:`rate`).
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.design import ductile_joints as dj
from saengine.design import ductile_members as dm
from saengine.design import seismic_rules
from saengine.design.clauses import clause, short_name
from saengine.design.rc import DesignError, RcSection

PREFIX = "Detailing: "


def _code() -> str:
    """The code and part the detailing rows cite ("<code> Part 6"), from the pack in force."""
    return clause("seismicDetailing", "part")


def rate(entry: dict[str, Any]) -> None:
    """Sets a checked member's utilisation from its ``checks`` (N-X7 of usability walk 2: every
    member read 1.00 from a detailing equality such as lo 550 against 550 mm):

    - ``strengthUtilisation``: the largest of the strength checks (every counted check not
      named ``"Detailing: "``), ``detailingUtilisation`` the largest of the detailing ones;
    - ``utilisation``: the strength one, or the detailing one when a detailing check fails (a
      passing detailing check never governs);
    - ``governingCheck``: ``{"name", "combination"}`` of the check that sets ``utilisation``;
    - ``ok``: every counted check passes.

    Flagged checks are reported only and count in none of them."""
    counted = [c for c in entry["checks"] if not c["flag"]]
    strength = [c for c in counted if not c["name"].startswith(PREFIX)]
    detailing = [c for c in counted if c["name"].startswith(PREFIX)]
    top_strength = max(strength, key=lambda c: c["utilisation"], default=None)
    top_detailing = max(detailing, key=lambda c: c["utilisation"], default=None)
    governing = top_strength
    failing = any(not c["ok"] for c in detailing)
    if top_detailing is not None and (
        top_strength is None
        or (failing and top_detailing["utilisation"] > top_strength["utilisation"])
    ):
        governing = top_detailing
    entry["strengthUtilisation"] = top_strength["utilisation"] if top_strength else 0.0
    entry["detailingUtilisation"] = top_detailing["utilisation"] if top_detailing else 0.0
    entry["utilisation"] = governing["utilisation"] if governing else 0.0
    entry["governingCheck"] = (
        {"name": governing["name"], "combination": governing.get("combination")}
        if governing
        else None
    )
    entry["ok"] = all(c["ok"] for c in counted)


#: Combinations with earthquake: these cases (static) or a response spectrum envelope.
EARTHQUAKE_CASES = ("EX", "EY")


def _method() -> list[str]:
    """``METHOD``: the method text of the design report, with the clauses of the code pack in
    force (read as a module attribute)."""
    return [
        (
            f"Seismic detailing to {clause('seismicDetailing', 'chapter')}: the detailing level "
            "from the Seismic "
            "Design Category (Sec 8.3.2: D special, C intermediate, B ordinary) and the structural "
            "system (Table 6.2.19); materials of Sec 8.3.3.3, 8.3.3.4."
        ),
        (
            "Members: special moment frame beams Sec 8.3.4 (b ≥ 250 mm and 0.3 h, ln ≥ 4d, ρ limits, "
            "Mn+ ≥ Mn-/2, hoops over 2h at min(d/4, 8 db, 24 dh, 300 mm), d/2 elsewhere), columns "
            "Sec 8.3.5 (least dimension ≥ 300 mm, ρg 1-6 %, Ash by Eq. 6.8.7 and 6.8.8 over lo = "
            "max(h, ln/6, 450 mm) at so = min(b/4, 6 db, 100 + (350 - hx)/3)); intermediate frames "
            "Sec 8.3.10.4, 8.3.10.5 (columns with Pu ≤ 0.1 Ag f'c by 8.3.10.4, Sec 8.3.10.2; "
            "special frame columns with Pu ≤ 0.1 Ag f'c take the stricter of 8.3.5.4 and 8.3.4.3, "
            "an SAEngine choice); ordinary frames Sec 8.3.9; gravity members Sec 8.3.12 (Sec "
            "8.3.12.3 with the capacity shear of 8.3.8 where the induced forces exceed φMn, φVn or "
            "are not computed, as for columns), 8.3.9.1. The hoop spacing in lo reported is the "
            "least of the dimensional limit, Ash and the capacity shear's Av/s with the type's ties."
        ),
        (
            "Capacity design: strong column / weak beam ΣMnc ≥ 1.2 ΣMnb (Sec 8.3.5.2, Eq. 6.8.5), "
            "joint shear Vj = 1.25 fy As - Vcol ≤ 0.85 γ √f'c Aj (Sec 8.3.7.3; bj by ACI 318-19 "
            f"18.8.4.3, {short_name()} does not define it), capacity shear Ve from Mpr at 1.25 fy "
            "(Sec 8.3.8, "
            "Vc = 0 by 8.3.8.2(a)) or 2E (Sec 8.3.10.3); Ω0 combinations for transfer members and "
            "collectors (Sec 2.5.5.6, 2.5.13.4). Foundations (Sec 8.3.11) are Part 9's."
        ),
    ]


@dataclass
class Designed:
    """A beam or column the design checked, with what its detailing needs."""

    id: str
    kind: str  # "beam" or "column"
    element: Any  # the BIM element (BeamElement, ColumnElement, MemberElement, InclinedMember)
    object: Any  # the object type
    section: RcSection
    pieces: list[Any]
    turned: bool
    entry: dict[str, Any]  # the report's element entry (checks are appended to it)
    capacities: dict[bool, Any] | None = None
    #: What the detailing worked from, for the design mode (:func:`capacity_av_s`).
    context: dict[str, Any] | None = None


def scope_of(settings: Any, materials: Any, objects: Any, building: Any, root: Any = None):
    """:func:`seismic_rules.seismic_detailing_scope` with the site class the analysis used (from
    the soil report when the settings say so)."""
    from saengine.library.settings import read_soil_text, resolve_site_class

    resolved, _ = resolve_site_class(settings, read_soil_text(root) if root is not None else None)
    return seismic_rules.seismic_detailing_scope(resolved, materials, objects, building), resolved


def earthquake_indices(extra: dict[str, Any], count: int) -> list[int]:
    """Indices of the combinations with earthquake: EX or EY among their factors (static), or a
    response spectrum envelope (:func:`saengine.fem.seismic_design.design_demands`)."""
    factors = extra.get("factors") or [{}] * count
    envelope = extra.get("envelope") or [{}] * count
    found = []
    for c in range(count):
        f = factors[c] if c < len(factors) else {}
        e = envelope[c] if c < len(envelope) else {}
        if e or any(f.get(k) for k in EARTHQUAKE_CASES):
            found.append(c)
    return found


def _clause(name: str) -> str | None:
    """The clause in a check name's last parentheses: "Width ≥ 250 mm (8.3.4.1(d))"."""
    if not name.endswith(")"):
        return None
    depth = 0
    for k in range(len(name) - 1, -1, -1):
        if name[k] == ")":
            depth += 1
        elif name[k] == "(":
            depth -= 1
            if depth == 0:
                inner = name[k + 1 : -1]
                if re.match(r"\d|Figure|Eq", inner):
                    return f"{_code()} Sec {inner}" if inner[0].isdigit() else f"{_code()} {inner}"
                return None
    return None


#: The clause of the rows whose names carry none (the capacity-design rows of
#: :mod:`saengine.design.ductile_joints`), by the start of the name.
NAME_CLAUSES = (
    ("Strong column / weak beam", "8.3.5.2(b), Eq. 6.8.5"),
    ("Joint shear", "8.3.7.3"),
    ("Beam bars through joint", "8.3.7.1(d)"),
    ("Beam bar anchorage", "8.3.7.1(c), 8.3.7.4(a)"),
    ("Capacity shear Ve (SMF column", "8.3.8.1(b), 8.3.8.2"),
    ("Capacity shear Ve (SMF)", "8.3.8.1(a), 8.3.8.2"),
    ("Capacity shear (IMF", "8.3.10.3"),
)

_NOTE_CLAUSE = re.compile(r"Sec (\d+\.\d+(?:\.\d+)*(?:\([a-z0-9]+\))*)")


def _clause_of(row: dict[str, Any], clause: str | None = None) -> str | None:
    """A row's clause: its own (``row["clause"]``), the one in its name's last parentheses, by
    its name (:data:`NAME_CLAUSES`), ``clause``, else the first "Sec ..." of its note."""
    if row.get("clause"):
        return row["clause"]
    found = _clause(row["name"])
    if found:
        return found
    for start, sec in NAME_CLAUSES:
        if row["name"].startswith(start):
            return f"{_code()} Sec {sec}"
    if clause:
        return clause
    match = _NOTE_CLAUSE.search(row.get("note") or "")
    return f"{_code()} Sec {match.group(1)}" if match else None


def _tagged(rows: list[dict[str, Any]], clause: str | None = None) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        row = dict(row)
        row["clause"] = _clause_of(row, clause)
        row["name"] = PREFIX + row["name"]
        out.append(row)
    return out


def _with_clause(rows: list[dict[str, Any]], clause: str) -> list[dict[str, Any]]:
    """The rows with ``clause`` (a section list such as "8.3.12.3(b), 8.3.8.1(a)") set."""
    return [{**r, "clause": f"{_code()} Sec {clause}"} for r in rows]


# ─────────────────────────────────────── geometry ───────────────────────────────────────


def _beam_supports(
    beam: Any, joints: list[dj.FrameJoint], columns: dict[str, Any], types: dict[str, Any]
) -> tuple[float | None, list[tuple[float, float]]]:
    """(the smallest clear span ln [mm], (c1, c2) of each supporting column) of a beam element:
    c1 the column dimension along the beam."""
    a = np.asarray(beam.start, dtype=float)
    b = np.asarray(beam.end, dtype=float)
    length = float(np.linalg.norm(b - a))
    if length <= 0:
        return None, []
    u = (b - a) / length
    found: list[tuple[float, float, float]] = []  # (t along the beam, c1, c2)
    for joint in joints:
        if not any(jb.id == beam.id for jb in joint.beams):
            continue
        column = columns.get(joint.below)
        profile = getattr(types.get(column.type), "profile", None) if column else None
        if profile is None:
            continue
        try:
            frame = dj.column_frame(profile, float(column.rotation or 0.0), u)
        except DesignError:
            continue
        t = float((np.asarray(joint.position) - a) @ u)
        found.append((t, frame.along, frame.across))
    found.sort()
    supports = [(c1, c2) for _, c1, c2 in found]
    if len(found) >= 2:
        spans = [
            (t2 - c2a / 2) - (t1 + c1a / 2)
            for (t1, c1a, _), (t2, c2a, _) in itertools.pairwise(found)
        ]
        return min(spans), supports
    return length - sum(c1 for _, c1, _ in found) / 2, supports


def _column_heights(
    column: Any, joints: list[dj.FrameJoint], beam_depths: dict[str, float]
) -> list[float]:
    """The clear heights [mm] of a column element per storey: the joint spacing below each of
    its joints less the deepest beam framing in at the top; its height without joints."""
    own = sorted((j for j in joints if j.below == column.id), key=lambda j: j.level)
    if not own:
        if hasattr(column, "top"):
            return [float(column.top - column.bottom)]
        if hasattr(column, "z1"):  # an inclined member: its length
            return [math.dist((column.x1, column.y1, column.z1), (column.x2, column.y2, column.z2))]
        return []
    heights = []
    for joint in own:
        deepest = max((beam_depths.get(b.type, 0.0) for b in joint.beams), default=0.0)
        heights.append(max(joint.height_below - deepest, 1.0))
    return heights


def _at_level(pieces: list[Any], level_m: float, below: bool) -> list[Any]:
    """The column pieces with an end at ``level_m`` [m] and the rest of them below (or above)."""
    out = []
    for p in pieces:
        if p.start is None or p.end is None:
            continue
        zs = (float(p.start[2]), float(p.end[2]))
        if min(abs(z - level_m) for z in zs) > 2e-3:
            continue
        other = zs[1] if abs(zs[0] - level_m) <= 2e-3 else zs[0]
        if (other < level_m) == below:
            out.append(p)
    return out


def _node_at(project: dict[str, Any], x: float, y: float, z: float) -> int | None:
    """The analysis node nearest (x, y, z) [m], within 60 mm."""
    best: tuple[float, int | None] = (0.06, None)
    for n in project.get("nodes", []):
        c = n["coords"]
        d = math.dist((float(c[0]), float(c[1]), float(c[2]) if len(c) > 2 else 0.0), (x, y, z))
        if d < best[0]:
            best = (d, int(n["id"]))
    return best[1]


def _joint_type(joint: dj.FrameJoint, rotation: float) -> str:
    ex, ey = dj.column_axes(rotation)
    sides = set()
    for beam in joint.beams:
        u = np.asarray(beam.direction, dtype=float)
        ux, uy = float(u @ ex), float(u @ ey)
        axis = 0 if abs(ux) >= abs(uy) else 1
        sides.add((axis, 1 if (ux if axis == 0 else uy) > 0 else -1))
    if len(sides) == 4:
        return "interior"
    opposite = {(0, 1), (0, -1)} <= sides or {(1, 1), (1, -1)} <= sides
    return "exterior" if len(sides) == 3 or opposite else "corner"


# ─────────────────────────────────────── the detailing ───────────────────────────────────────


def _frame_for(member: dict[str, Any] | None, scope: dict[str, Any]) -> tuple[str, bool] | None:
    """(ductile_members frame, lateral) of a member from its scope row; None without a Sec 8.3
    provision for it (gravity members in Category C, steel systems, no seismic zone)."""
    if not member or not member.get("provisions"):
        return None
    lateral = member["role"] == "lateral"
    if lateral:
        level = scope.get("detailingLevel")
        return (level, True) if level in dm.FRAMES else None
    # Members not part of the system: 8.3.12 in D (frame "special"), 8.3.9 in B.
    return ("special" if scope.get("sdc") == "D" else "ordinary"), False


def apply(
    project: dict[str, Any],
    building: Any,
    types: dict[str, Any],
    designed: list[Designed],
    combinations: list[str],
    extra: dict[str, Any],
    scope: dict[str, Any],
    settings: Any,
    profile_forces: Any,
) -> dict[str, Any]:
    """Adds the detailing checks to each designed member's report entry (``checks`` with the
    ``"Detailing: "`` prefix, ``detailing``) and returns ``{"joints": [...], "notes": [...]}``:
    the joints in the shape the workbench reads (see the module notes of
    :mod:`saengine.design.check`)."""
    from saengine.library.bim import ColumnElement

    notes: list[str] = []
    joints_out: list[dict[str, Any]] = []
    if scope.get("detailingLevel") is None:
        return {"joints": joints_out, "notes": notes}
    e_idx = earthquake_indices(extra, len(combinations))
    by_id = {d.id: d for d in designed}
    beam_sections = {d.object.id: d.section for d in designed if d.kind == "beam"}
    beam_depths = {tid: s.depth for tid, s in beam_sections.items()}
    columns = {e.id: e for e in building.elements if isinstance(e, ColumnElement)}
    members_scope = scope.get("members", {})
    sdc = scope.get("sdc")

    try:
        joints = dj.frame_joints(building, types)
    except (DesignError, ValueError, AttributeError) as error:
        joints = []
        notes.append(f"the beam-column joints could not be found: {error}")

    # The Ω0 combinations (Sec 2.5.13.4) count for the elements scope["omega"] names only: the
    # others carry no force in them (check._drop_combinations), so they must not take part in
    # their earthquake demands either (a zero axial force would set pmin to 0).
    omega_set = set((scope.get("omega") or {}).get("elements") or [])
    omega_c = {c for c, name in enumerate(combinations) if name.startswith("Ω0: ")}
    e_plain = [c for c in e_idx if c not in omega_c]

    def e_for(member_id: str | None) -> list[int]:
        return e_idx if member_id in omega_set else e_plain

    def demands(pieces: list[Any], turned: bool, member_id: str | None) -> dj.SeismicDemands:
        return dj.seismic_demands(pieces, e_for(member_id), turned, profile_forces)

    axial_share = dm._special("axialShare")
    strong_ratio = dj._joints("strongColumnRatio")

    def heavy(d: Designed, pmax: float) -> bool:
        return pmax > axial_share * d.section.gross_area * d.section.fc

    # ── joints: strong column / weak beam (8.3.5.2) and joint shear (8.3.7) ──
    full_height: set[str] = set()
    mpr_at: dict[str, dict[str, float]] = {}  # joint id -> ΣMpr per column axis
    #: Sec 8.3.7.1 rows of the joints of gravity columns with Pu > 0.1 Ag f'c (8.3.12.3(c)).
    gravity_joint_rows: dict[str, list[dict[str, Any]]] = {}
    for joint in joints:
        below = by_id.get(joint.below)
        if below is None or below.kind != "column":
            continue
        frame = _frame_for(members_scope.get(joint.below), scope)
        beams = {b.type: beam_sections[b.type] for b in joint.beams if b.type in beam_sections}
        if not beams:
            continue
        rotation = float(getattr(below.element, "rotation", 0.0) or 0.0)
        try:
            mpr_at[joint.id] = dj.joint_beam_mpr(joint, beams, rotation)
        except DesignError:
            pass
        special = frame == ("special", True)
        gravity_d = frame == ("special", False) and sdc == "D"
        if not special and not gravity_d:
            continue  # 8.3.5.2 and 8.3.7: special moment frames (and 8.3.12.3(c)) only
        level_m = joint.level / 1e3
        dem = demands(
            _at_level(below.pieces, level_m, True) or below.pieces, below.turned, joint.below
        )
        if gravity_d and not heavy(below, dem.pmax):
            continue  # 8.3.12.3(b): no joint rule for a lightly loaded gravity column
        tie = below.object.reinforcement.transverse if below.object.reinforcement else None
        cover = below.object.reinforcement.cover if below.object.reinforcement else 40.0
        jb = dj.JointColumn(
            below.section, rotation, dem.pmin, dem.pmax, cover, tie.dia if tie else 10.0
        )
        above = by_id.get(joint.above) if joint.above else None
        ja = None
        if above is not None and above.kind == "column":
            dem_a = demands(
                _at_level(above.pieces, level_m, False) or above.pieces, above.turned, joint.above
            )
            tie_a = above.object.reinforcement.transverse if above.object.reinforcement else None
            ja = dj.JointColumn(
                above.section,
                float(getattr(above.element, "rotation", 0.0) or 0.0),
                dem_a.pmin,
                dem_a.pmax,
                above.object.reinforcement.cover if above.object.reinforcement else 40.0,
                tie_a.dia if tie_a else 10.0,
            )
        if gravity_d:
            # 8.3.12.3(c) asks 8.3.7.1 of these joints: the bars through or anchored in them.
            try:
                found, _ = dj.joint_checks(joint, beams, jb, ja, below.object.profile)
            except DesignError as error:
                notes.append(f"{joint.id}: Sec 8.3.7.1 not checked: {error}")
                continue
            gravity_joint_rows.setdefault(joint.below, []).extend(
                _with_clause(
                    [r for r in found if r["name"].startswith("Beam bar")],
                    "8.3.12.3(c), "
                    + (
                        "8.3.7.1(d)"
                        if any("through" in r["name"] for r in found)
                        else "8.3.7.1(c), 8.3.7.4(a)"
                    ),
                )
            )
            continue
        try:
            strong, strong_notes = dj.strong_column_checks(
                joint, beams, jb, ja, below.object.profile
            )
            shear_rows, shear_notes = dj.joint_checks(joint, beams, jb, ja, below.object.profile)
        except DesignError as error:
            notes.append(f"{joint.id}: joint not checked: {error}")
            continue
        scwb: dict[str, Any] = {}
        for row in strong:
            axis = row["name"].rsplit(" ", 1)[-1]
            mnb = row["demand"] / strong_ratio
            scwb[axis] = {
                "ratio": round(row["capacity"] / mnb, 3) if mnb > 0 else None,
                "sumMnc": row["capacity"],
                "sumMnb": round(mnb, 2),
                "required": strong_ratio,
                "utilisation": 0.0 if row["flag"] else row["utilisation"],
                "notRequired": bool(row["flag"]),
            }
            if not row["flag"] and not row["ok"]:
                full_height.update(c for c in (joint.below, joint.above) if c)
        shear_main = [r for r in shear_rows if r["name"].startswith("Joint shear")]
        governing_shear = max(shear_main, key=lambda r: r["utilisation"], default=None)
        rows = _tagged(strong + shear_rows)
        strength = [r for r in rows if not r["flag"]]
        utilisation = max((r["utilisation"] for r in strength), default=0.0)
        joints_out.append(
            {
                "id": joint.id,
                "node": _node_at(
                    project, joint.position[0] / 1e3, joint.position[1] / 1e3, level_m
                ),
                "column": joint.below,
                "columnAbove": joint.above,
                "beams": sorted({b.id for b in joint.beams}),
                "type": _joint_type(joint, rotation),
                "level": joint.level,
                "scwb": {"x": scwb.get("x"), "y": scwb.get("y")},
                # The factored axial forces of the columns at the joint [N, pmin and pmax over
                # the combinations with earthquake]: Design Reinforcement checks ΣMnc with them.
                "axial": {
                    "below": [jb.pmin, jb.pmax],
                    "above": None if ja is None else [ja.pmin, ja.pmax],
                },
                "shear": None
                if governing_shear is None
                else {
                    "Vj": governing_shear["demand"],
                    "phiVn": governing_shear["capacity"],
                    "utilisation": governing_shear["utilisation"],
                },
                "checks": rows,
                "utilisation": utilisation,
                "ok": all(r["ok"] for r in strength),
                # The rows the joint view has no line of its own for (bars through the joint,
                # hooked anchorage), as notes: the verdict's utilisation may come from them.
                "notes": [
                    f"{r['name']}: {r['demand']:g} against {r['capacity']:g} {r['unit']} "
                    f"({r['utilisation']:.2f}{', fails' if not r['ok'] else ''})"
                    for r in shear_rows
                    if not r["name"].startswith("Joint shear")
                ]
                + strong_notes
                + shear_notes,
            }
        )

    # ── members ──
    for d in designed:
        row = members_scope.get(d.id)
        frame = _frame_for(row, scope)
        if frame is None:
            continue
        level, lateral = frame
        obj = d.object
        reinforcement = obj.reinforcement
        transverse = reinforcement.transverse if reinforcement else None
        zones = dm.zones_of(transverse)
        axial = (0.0, None)
        for piece in d.pieces:
            every = dj.stacked_parts(piece.forces, list(range(len(piece.forces))))
            if every is not None and every.ndim == 3:
                # Each combination's largest P at once, then the first of the largest.
                peaks = profile_forces(piece, d.turned, every)["P"].max(axis=1).tolist()
            else:
                peaks = [
                    float(np.max(profile_forces(piece, d.turned, forces)["P"]))
                    for forces in piece.forces
                ]
            for c, p in enumerate(peaks):
                if p > axial[0]:
                    axial = (float(p), combinations[c])
        dem = demands(d.pieces, d.turned, d.id)
        stirrups = dj.Stirrups(zones.dia, zones.legs, zones.in_zone) if zones is not None else None
        rows: list[dict[str, Any]] = []
        member_notes: list[str] = []
        info: dict[str, Any] = {
            "frameType": level,
            "role": row["role"],
            "sdc": sdc,
            "provisions": row["provisions"],
            "zones": None,
            "Ve": None,
            "phiVn": None,
            "clause": f"{_code()} Sec " + ", ".join(row["provisions"]),
            "notes": member_notes,
        }
        context: dict[str, Any] = {
            "level": level,
            "lateral": lateral,
            "axial": axial,
            "demands": dem,
            "cover": reinforcement.cover if reinforcement else 40.0,
            "fullHeight": d.id in full_height,
            # The capacity shear rule the member follows: Sec 8.3.8 ("special"), 8.3.10.3
            # ("intermediate"), or None.
            "shearLevel": level if lateral and level in ("special", "intermediate") else None,
        }
        d.context = context
        gravity_d = not lateral and sdc == "D"
        try:
            if d.kind == "beam":
                clear_span, supports = (None, [])
                if hasattr(d.element, "start") and len(d.element.start) == 2:
                    clear_span, supports = _beam_supports(d.element, joints, columns, types)
                context.update(clearSpan=clear_span, supports=supports)
                out = dm.beam_checks(
                    d.section,
                    transverse,
                    level,
                    clear_span=clear_span,
                    axial=axial,
                    supports=supports,
                    capacities=d.capacities,
                    lateral=lateral,
                    zones=zones,
                )
                rows += out.checks
                member_notes += out.notes
                need = out.need
                if need is not None:
                    info["zones"] = {
                        "lo": need.zone_length,
                        "so": need.zone_spacing,
                        "outside": need.outside_spacing,
                    }
                if not lateral:
                    found, found_notes = _gravity_beam(
                        d, e_for(d.id), scope, settings, stirrups, profile_forces, rows
                    )
                    rows[:] = found["rows"]
                    member_notes[:] = [
                        n
                        for n in member_notes
                        if not (found["computed"] and n.startswith(_NOT_COMPUTED))
                        # 8.3.12.2(a) asks 8.3.4.2(a) only, not the splices of 8.3.4.2(b).
                        and not (found["only4_2a"] and n.startswith("lap splices (8.3.4.2(b))"))
                    ] + found_notes
                    if gravity_d and found["capacityShear"]:
                        context["shearLevel"] = "special"
                if context["shearLevel"] and clear_span:
                    shear_rows = dj.beam_capacity_shear(
                        d.section,
                        clear_span,
                        dem.gravity_shear,
                        dem.shear,
                        stirrups,
                        axial=max(dem.pmax, 0.0),
                        level=context["shearLevel"],
                        doubled_e_shear=dem.doubled_e_shear,
                    )
                    if not lateral:
                        shear_rows = _with_clause(shear_rows, "8.3.12.3(b), 8.3.8.1(a)")
                    rows += shear_rows
                    if shear_rows:
                        info["Ve"], info["phiVn"] = (
                            shear_rows[0]["demand"],
                            shear_rows[0]["capacity"],
                        )
                elif context["shearLevel"]:
                    member_notes.append("clear span not found: the capacity shear not checked")
            else:
                heights = _column_heights(d.element, joints, beam_depths)
                context.update(clearHeight=max(heights) if heights else None)
                cover = reinforcement.cover if reinforcement else 40.0
                out = dm.column_checks(
                    d.section,
                    transverse,
                    level,
                    cover,
                    clear_height=max(heights) if heights else None,
                    axial=axial,
                    lateral=lateral,
                    full_height=d.id in full_height,
                    zones=zones,
                )
                rows += out.checks
                member_notes += out.notes
                if d.id in full_height:
                    member_notes.append(
                        "a joint of this column fails the strong-column rule: Sec 8.3.5.4 "
                        "confinement over the full height (8.3.5.2(c))"
                    )
                need = out.need
                if need is not None:
                    info["zones"] = {
                        "lo": need.zone_length,
                        "so": need.zone_spacing,
                        "outside": need.outside_spacing,
                    }
                light = not heavy(d, axial[0])
                if gravity_d:
                    member_notes.append(
                        f"{_NOT_COMPUTED} for columns, so Sec 8.3.12.3 applies (8.3.12.1): "
                        + (
                            "8.3.12.3(b) asks 8.3.4.2 and 8.3.8 with ties at d/2; the beam "
                            "steel ratios of 8.3.4.2 are not checked for a column section"
                            if light
                            else "8.3.12.3(c) asks 8.3.5.3, 8.3.5.4, 8.3.7.1 and 8.3.8"
                        )
                    )
                    context["shearLevel"] = "special"
                    if not light:
                        rows += gravity_joint_rows.get(d.id, [])
                if context["shearLevel"]:
                    if isinstance(d.element, ColumnElement):
                        found = _column_shear(
                            d,
                            context["shearLevel"],
                            joints,
                            beam_sections,
                            mpr_at,
                            heights,
                            dem,
                            zones,
                            info,
                            context,
                        )
                        if not lateral:
                            found = _with_clause(
                                found, f"8.3.12.3({'b' if light else 'c'}), 8.3.8.1(b)"
                            )
                        rows += found
                    else:
                        member_notes.append(
                            "an inclined member: its capacity shear (Sec 8.3.8, 8.3.10.3) is "
                            "not checked"
                        )
        except DesignError as error:
            member_notes.append(f"seismic detailing not checked: {error}")
        tagged = _tagged(rows)
        if info["zones"] is not None:
            info["zones"].update(_zone_spacing(info["zones"], tagged, zones))
        d.entry["checks"] = d.entry["checks"] + tagged
        d.entry["detailing"] = info
        rate(d.entry)
    return {"joints": joints_out, "notes": notes}


#: The start of ductile_members' note that the induced moments were not computed.
_NOT_COMPUTED = (
    "not part of the seismic-force-resisting system: the moments induced by the design "
    "displacement are not computed"
)


def _zone_spacing(
    zones: dict[str, Any], rows: list[dict[str, Any]], ties: dm.Zones | None
) -> dict[str, Any]:
    """The largest hoop spacing in lo with the type's ties: the dimensional limit (Sec
    8.3.4.3(b), 8.3.5.4(b), ...) and what the confinement Ash (8.3.5.4(a)) and the capacity
    shear's Av/s (8.3.8, 8.3.10.3) allow with the type's bar diameter and legs. Both of those
    grow with the spacing as s × required / provided, so the spacing they allow is s ×
    provided / required. ``{"so", "soDetailing", "soRule"}``; empty without a zone rule."""
    so = zones.get("so")
    if so is None:
        return {}
    limits = {"dimensions": float(so)}
    if ties is not None and ties.in_zone > 0:
        s = ties.in_zone
        for r in rows:
            name = r["name"]
            if r["flag"] or r["demand"] <= 0 or r["capacity"] <= 0:
                continue
            if "Confinement Ash" in name and name.endswith("in lo (8.3.5.4(a)(ii))"):
                key = "Ash"
            elif name.endswith(": transverse steel Av/s"):
                key = "capacity shear Av/s"
            else:
                continue
            allowed = math.floor(s * r["capacity"] / r["demand"])
            limits[key] = min(limits.get(key, math.inf), allowed)
    governing = min(limits, key=lambda k: limits[k])
    rule = ", ".join(f"{k} {v:g} mm" for k, v in limits.items())
    return {
        "so": limits[governing],
        "soDetailing": float(so),
        "soRule": f"min({rule}) with the type's ties"
        + (f" Ø{ties.dia:g}" if ties is not None else "")
        + f": {governing} governs",
    }


def _gravity_beam(
    d: Designed,
    e_idx: list[int],
    scope: dict[str, Any],
    settings: Any,
    stirrups: dj.Stirrups | None,
    profile_forces: Any,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Sec 8.3.12 (D) or 8.3.9.1 (B) of a beam outside the seismic force-resisting system,
    with ``rows`` its member checks: ``({"rows", "computed", "capacityShear", "only4_2a"}, notes)``.

    In D the induced forces under δu decide (8.3.12.1): within φMn and φVn, 8.3.12.2(a)
    (8.3.4.2(a), stirrups at d/2); beyond them or not computed, 8.3.12.3(b) (8.3.4.2, the
    capacity shear of 8.3.8, d/2). The d/2 row of the member checks is kept (renamed to the
    clause that applies) and the full-length row of :func:`dj.non_sfrs_checks` dropped."""
    found: list[dict[str, Any]] = []
    notes: list[str] = []
    if e_idx:
        found, notes = _non_sfrs_beam(d, e_idx, scope, settings, stirrups, profile_forces)
    induced = [r for r in found if r["name"].startswith("Induced ")]
    computed = bool(induced) and all(r["capacity"] > 0 for r in induced)
    exceeds = not computed or any(r["utilisation"] > 1 for r in induced)
    out = list(rows)
    if scope.get("sdc") == "D":
        clause = "8.3.12.3(b)" if exceeds else "8.3.12.2(a)"
        out = [
            {**r, "name": r["name"].replace("(8.3.12.3(b))", f"({clause})")}
            if r["name"].startswith("Stirrup spacing elsewhere")
            else r
            for r in out
        ]
        if not exceeds:  # 8.3.12.2(a): 8.3.4.2(a) only
            out = [r for r in out if "(8.3.4.2(b))" not in r["name"]]
        has_d2 = any(r["name"].startswith("Stirrup spacing elsewhere") for r in out)
        found = [r for r in found if not (has_d2 and r["name"].startswith("Stirrup spacing (full"))]
        if not computed:
            notes.append(
                f"{d.id}: the induced forces under δu could not be computed (no combination with "
                "E, or no φMn): Sec 8.3.12.3 applies (8.3.12.1)"
            )
        if exceeds:
            notes.append(f"{d.id}: the capacity shear of Sec 8.3.8 applies (8.3.12.3(b))")
    only = scope.get("sdc") == "D" and not exceeds
    return {
        "rows": out + found,
        "computed": computed,
        "capacityShear": exceeds,
        "only4_2a": only,
    }, notes


def _column_shear(
    d: Designed,
    level: str,
    joints: list[dj.FrameJoint],
    beam_sections: dict[str, RcSection],
    mpr_at: dict[str, dict[str, float]],
    heights: list[float],
    dem: dj.SeismicDemands,
    zones: dm.Zones | None,
    info: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """The capacity shear of a column in its two profile directions (Sec 8.3.8.1(b),
    8.3.10.3): lu the smallest clear height; the beams' limit from the ΣMpr at its top and
    bottom joints (none at a base without beams)."""
    rotation = float(getattr(d.element, "rotation", 0.0) or 0.0)
    lu = min(heights) if heights else float(d.element.top - d.element.bottom)
    own = sorted((j for j in joints if j.below == d.id), key=lambda j: j.level)
    bottom = next(
        (
            j
            for j in joints
            if j.above == d.id and j.below != d.id and abs(j.level - d.element.bottom) < 60
        ),
        None,
    )
    top = own[-1] if own else None
    rows: list[dict[str, Any]] = []
    best: tuple[float, float, float] = (-1.0, 0.0, 0.0)
    context.update(lu=lu, rotation=rotation, beamLimit={}, baseBeamMoment={})
    for k, direction in enumerate(dj.column_axes(rotation)):
        axis = "xy"[k]
        beam_limit = base_moment = None
        if top is not None and bottom is None and top.id in mpr_at:
            # On a base: the hinge there takes the column's Mpr, the top joint's beams limit
            # the other end (Sec 8.3.8.1(b)).
            base_moment = (0.5 if top.above else 1.0) * mpr_at[top.id].get(axis, 0.0)
        if top is not None and bottom is not None:
            share_top = 0.5 if top.above else 1.0
            beam_limit = dj.beam_limited_column_shear(
                mpr_at.get(top.id, {}).get(axis, 0.0),
                mpr_at.get(bottom.id, {}).get(axis, 0.0),
                lu,
                share_top,
                0.5,
            )
        context["beamLimit"][axis] = beam_limit
        context["baseBeamMoment"][axis] = base_moment
        legs = (zones.across_depth if k == 0 else zones.legs) if zones else 0
        stirrups = dj.Stirrups(zones.dia, legs, zones.in_zone) if zones and legs else None
        found = dj.column_capacity_shear(
            d.section,
            rotation,
            direction,
            lu,
            dem.pmin,
            dem.pmax,
            dem.shear_x if k == 0 else dem.shear,
            beam_limit,
            stirrups,
            level=level,
            doubled_e_shear=dem.doubled_e_shear_x if k == 0 else dem.doubled_e_shear,
            base_beam_moment=base_moment,
        )
        rows += found
        if found and found[0]["utilisation"] > best[0]:
            best = (found[0]["utilisation"], found[0]["demand"], found[0]["capacity"])
    if best[0] >= 0:
        info["Ve"], info["phiVn"] = best[1], best[2]
    return rows


def _non_sfrs_beam(
    d: Designed,
    e_idx: list[int],
    scope: dict[str, Any],
    settings: Any,
    stirrups: dj.Stirrups | None,
    profile_forces: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Sec 8.3.12 (D) / 8.3.9.1 (others) of a gravity beam: the induced moment and shear under
    the design displacement (Cd/I times the elastic lateral part in D, twice it otherwise)."""
    from saengine.design.rc import shear
    from saengine.library.settings import derived

    values = derived(settings)
    factor = values["Cd"] / values["seismicImportance"] if scope.get("sdc") == "D" else 2.0
    moment = shear_force = gravity_axial = 0.0
    for piece in d.pieces:
        for c in e_idx:
            total = profile_forces(piece, d.turned, piece.forces[c])
            sway = profile_forces(
                piece, d.turned, piece.sway[c] if piece.sway else np.zeros_like(piece.forces[c])
            )
            # The elastic lateral part: the factored E of the combination (1.0 E in BNBC's).
            moment = max(moment, dj.induced_forces(total["Mx"] - sway["Mx"], sway["Mx"], factor))
            shear_force = max(
                shear_force, dj.induced_forces(total["Vy"] - sway["Vy"], sway["Vy"], factor)
            )
            gravity_axial = max(gravity_axial, float(np.max(total["P"] - sway["P"])))
    caps = d.capacities or {}
    phi_mn = min((caps[h].phi_mn for h in caps if caps[h].phi_mn > 0), default=0.0)
    resistance = shear(
        d.section,
        stirrups.dia if stirrups else None,
        stirrups.legs if stirrups else 0,
        stirrups.spacing if stirrups else None,
    )
    rows, notes = dj.non_sfrs_checks(
        d.id,
        d.section,
        gravity_axial,
        moment,
        shear_force,
        phi_mn,
        resistance.phi_vn,
        scope.get("sdc"),
        stirrups,
    )
    return rows, notes


def capacity_av_s(section: RcSection, kind: str, context: dict[str, Any]) -> dict[str, float]:
    """The transverse steel Av/s [mm²/mm] the capacity shear asks of ``section`` (the design
    mode's proposed bars, whose Mpr sets Ve) for a member's detailing ``context`` (see
    :class:`Designed`): beams ``{"y": ...}``, columns ``{"x": ..., "y": ...}``; empty when no
    capacity shear rule applies (Sec 8.3.8 special, 8.3.10.3 intermediate frames)."""
    level, dem = context.get("shearLevel"), context.get("demands")
    if level not in ("special", "intermediate") or dem is None:
        return {}
    out: dict[str, float] = {}
    if kind == "beam":
        if not context.get("clearSpan"):
            return {}
        rows = dj.beam_capacity_shear(
            section,
            context["clearSpan"],
            dem.gravity_shear,
            dem.shear,
            None,
            axial=max(dem.pmax, 0.0),
            level=level,
            doubled_e_shear=dem.doubled_e_shear,
        )
        if len(rows) > 1:
            out["y"] = rows[1]["demand"]
        return out
    if "lu" not in context:
        return {}
    for k, direction in enumerate(dj.column_axes(context["rotation"])):
        axis = "xy"[k]
        rows = dj.column_capacity_shear(
            section,
            context["rotation"],
            direction,
            context["lu"],
            dem.pmin,
            dem.pmax,
            dem.shear_x if k == 0 else dem.shear,
            context["beamLimit"].get(axis),
            None,
            level=level,
            doubled_e_shear=dem.doubled_e_shear_x if k == 0 else dem.doubled_e_shear,
            base_beam_moment=context.get("baseBeamMoment", {}).get(axis),
        )
        if len(rows) > 1:
            out[axis] = rows[1]["demand"]
    return out


def __getattr__(name: str) -> list[str]:
    # The method text names the clauses of the pack in force: built when it is read.
    if name == "METHOD":
        return _method()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
