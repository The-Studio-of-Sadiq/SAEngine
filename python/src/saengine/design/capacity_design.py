"""Capacity design of earthquake-resistant concrete frames by ductility class (method
``curvatureDuctility`` of the pack's ``concreteMethods.seismic``; alpha 9 C5b): the frame-level
checks that take the place of the parent pack's special-frame detailing
(:mod:`saengine.design.seismic_detailing`) when the pack picks this method.

Units: mm, MPa, N, N·mm. Design resistances are the partial-factor ones (fcd, fyd, φ = 1) of
:mod:`saengine.design.design_strength`: MRb of a beam is its flexural resistance (the
sections' ``mn``), MRc of a column its resistance at the axial force.

- Strong column / weak beam at each joint of the lateral system, per column axis:
  ΣMRc >= ``strongColumn`` ΣMRb, MRc of each column at the axial force (of the combinations
  with earthquake) that gives the lowest resistance, ΣMRb the larger of the two senses; not
  required at the top joint of a column (reported only).
- Joint shear (DCH): Vjhd = γRd (As1 + As2) fyd - VC at interior joints, γRd As1 fyd - VC at
  exterior ones (VC taken 0, on the safe side) against η fcd √(1 - νd/η) bj hjc
  (:func:`saengine.design.curvature_ductility.joint_shear_resistance`), νd of the column above
  (else below) at its largest compression; bj = min(bc, bw + 0.5 hc) where bc > bw, else
  min(bw, bc + 0.5 hc); hjc the distance between the column's outer bars.
- Capacity design shear of beams: VEd = γRd (MRb,1 + MRb,2) / lcl + the gravity shear of the
  combinations with earthquake (both ends' moments taken in full, on the safe side), against
  VRd of the pack's shear method; DCH beams with cot θ = 1 in the critical regions.
- Capacity design shear of columns: VEd = γRd 2 MRc / lcl, MRc the largest over the axial
  range, against VRd with σcp of the least compression.
- Critical regions: beams lcr = factor hw, columns lcr = max(a hc, lcl / b, c), with the hoop
  spacing of the ductility class; Design Reinforcement proposes the hoops there
  (:func:`propose_transverse`).

A low-ductility system (DCL) has no capacity design: the members are designed by the
material code alone (EN 1998-1 5.3); the report says so.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.design import curvature_ductility as cd
from saengine.design import design_strength, method_selection
from saengine.design import ductile_joints as dj
from saengine.design import seismic_detailing as sd
from saengine.design.rc import DesignError, bar_area


def selected() -> bool:
    """True when the pack in force designs earthquake resistance by ductility class."""
    return method_selection.uses("seismic", "curvatureDuctility")


def _row(
    name: str,
    demand: float,
    capacity: float,
    unit: str,
    note: str,
    key: str,
    combination: str | None = None,
    flag: bool = False,
) -> dict[str, Any]:
    from saengine.design.check import _check

    clause = code_context.cite("concreteMethods", key)
    row = _check(name, demand, capacity, unit, combination, note, flag=flag)
    row["clause"] = clause or None
    return row


def _largest_strong_column() -> float:
    return max(c.strongColumn for c in cd.rules().classes.values())


# ─────────────────────────────── joints ───────────────────────────────


def strong_column_rows(
    joint: dj.FrameJoint,
    beams: dict[str, Any],
    below: dj.JointColumn,
    above: dj.JointColumn | None,
    profile: Any,
    ductility: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """ΣMRc >= factor ΣMRb at a joint per column axis (the shape of
    :func:`saengine.design.ductile_joints.strong_column_checks`, rows named "Strong column /
    weak beam, <joint> <axis>"); ``ductility`` None: the largest factor of the classes."""
    directions, notes = dj._directions(joint, beams, below.rotation)
    factor = cd.class_rules(ductility).strongColumn if ductility else _largest_strong_column()
    rows = []
    for d in directions:
        mrc = 0.0
        parts = []
        for name, c in (("below", below), ("above", above)):
            if c is None:
                continue
            own = dj.column_frame(
                c.section.profile if c is not below else profile, c.rotation, d.axis
            )
            m, p = dj.lowest_column_moment(c.section, c.pmin, c.pmax, own.compression)
            mrc += m
            parts.append(f"MRc {name} = {m / 1e6:.1f} kN·m at NEd = {p / 1e3:.0f} kN")
        mrb = max(dj._sum_beams(d, s, probable=False) for s in (1, -1))
        if mrb <= 0:
            continue
        note = (
            f"ΣMRc = {mrc / 1e6:.1f} kN·m >= {factor:g} ΣMRb = {factor:g} × {mrb / 1e6:.1f} kN·m; "
            + "; ".join(parts)
        )
        top = above is None
        if top:
            note += "; the column ends here: not required at the top joint, reported only"
        rows.append(
            _row(
                f"Strong column / weak beam, {joint.id} {d.name}",
                factor * mrb / 1e6,
                mrc / 1e6,
                "kN·m",
                note,
                "strongColumn",
                flag=top,
            )
        )
    return rows, notes


def joint_rows(
    joint: dj.FrameJoint,
    beams: dict[str, Any],
    below: dj.JointColumn,
    above: dj.JointColumn | None,
    profile: Any,
    ductility: str = "DCH",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Joint shear of a DCH joint per column axis (rows "Joint shear, <joint> <axis>")."""
    if ductility != "DCH":
        return [], []
    c = cd.class_rules("DCH")
    directions, notes = dj._directions(joint, beams, below.rotation)
    column = above or below
    fck = column.section.fc
    f_cd = design_strength.fcd(fck)
    nu_d = max(column.pmax, 0.0) / (column.section.gross_area * f_cd)
    gamma = c.gammaRdJoint or c.gammaRdBeam
    rows = []
    for d in directions:
        frame = dj.column_frame(profile, below.rotation, d.axis)
        hc, bc = frame.along, frame.across
        bw = max(section.width for _, section, _ in d.plus + d.minus)
        bj = min(bc, bw + 0.5 * hc) if bc > bw else min(bw, bc + 0.5 * hc)
        db = max((x.dia for x in below.section.bars), default=0.0)
        hjc = max(hc - 2 * (below.cover + below.tie_dia) - db, 1.0)
        f_yd = design_strength.fyd(max(s.fy for _, s, _ in d.plus + d.minus))
        interior = bool(d.plus) and bool(d.minus)
        if interior:
            area = max(
                max(m.as_top for _, _, m in d.plus) + max(m.as_bottom for _, _, m in d.minus),
                max(m.as_top for _, _, m in d.minus) + max(m.as_bottom for _, _, m in d.plus),
            )
        else:
            area = max(m.as_top for _, _, m in d.plus + d.minus)
        vjhd = gamma * area * f_yd
        resist = cd.joint_shear_resistance(fck, nu_d, bj, hjc, exterior=not interior)
        rows.append(
            _row(
                f"Joint shear, {joint.id} {d.name}",
                vjhd / 1e3,
                resist / 1e3,
                "kN",
                f"{'interior' if interior else 'exterior'} joint: Vjhd = γRd ΣAs fyd - VC = "
                f"{gamma:g} × {area:.0f} × {f_yd:.0f} (VC = 0, on the safe side); η fcd √(1 - νd/η) "
                f"bj hjc with νd = {nu_d:.2f}, bj = {bj:.0f} mm, hjc = {hjc:.0f} mm",
                "jointShear",
            )
        )
    return rows, notes


# ─────────────────────────────── members ───────────────────────────────


def _beam_shear_resistance(section: Any, transverse: Any | None, ductility: str) -> float:
    """VRd [N] of a beam's critical region: the pack's shear method, DCH links at cot θ = 1."""
    from saengine.design import strut_shear
    from saengine.design.rc import shear

    dia = getattr(transverse, "dia", None)
    legs = getattr(transverse, "legs", 0) or 0
    spacing = getattr(transverse, "spacing", None)
    zone = getattr(transverse, "zone", None)
    if zone is not None and getattr(zone, "spacing", None):
        spacing = zone.spacing
    if ductility != "DCH":
        return shear(section, dia, legs, spacing).phi_vn
    s = strut_shear.rules()
    u = design_strength.rules()
    b = section.width
    try:
        d = section.effective_depth(top=False)
    except DesignError:
        d = 0.9 * section.depth
    z = s.leverArmShare * d
    vrd_max = (
        s.alphaCw * b * z * strut_shear.nu1(section.fc, s) * design_strength.fcd(section.fc, u) / 2
    )
    if not (dia and spacing and legs):
        return 0.0
    vrd_s = legs * bar_area(dia) / spacing * z * design_strength.fyd(section.fy, u)
    return min(vrd_s, vrd_max)


def _column_shear_rows(
    d: Any, transverse: Any, demand: Any, clear: float, ductility: str
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    from saengine.design import strut_shear
    from saengine.design.column_shear import shear_axes

    c = cd.class_rules(ductility)
    s = strut_shear.rules()
    section = d.section
    rows = []
    need: dict[str, float] = {}
    ag = section.gross_area
    for part in shear_axes(section, transverse):
        angle = 0.0 if part.axis == "x" else math.pi / 2
        mrc, p = dj.highest_column_moment(section, demand.pmin, demand.pmax, angle, probable=False)
        ved = c.gammaRdColumn * 2 * mrc / clear
        rho_l = min(s.rhoLMax, 0.5 * section.steel_area / (part.bw * part.d))
        vrd = strut_shear.concrete_resistance(
            part.bw, part.d, rho_l, section.fc, demand.pmin / ag, s
        )
        spacing = part.spacing
        zone = getattr(transverse, "zone", None)
        if zone is not None and getattr(zone, "spacing", None):
            spacing = zone.spacing
        if part.av and spacing:
            links = strut_shear.link_resistance(part.bw, part.d, part.av, spacing, section.fc,
                                                section.fy, s)  # fmt: skip
            vrd = max(vrd, min(links.vrd_s, links.vrd_max))
        need[part.axis] = ved
        rows.append(
            _row(
                f"Capacity design shear along {part.axis} ({ductility})",
                ved / 1e3,
                vrd / 1e3,
                "kN",
                f"VEd = γRd 2 MRc / lcl = {c.gammaRdColumn:g} × 2 × {mrc / 1e6:.1f} / "
                f"{clear:.0f}, MRc at NEd = {p / 1e3:.0f} kN (the largest over the earthquake "
                "combinations' axial forces)",
                "columnShearCapacity",
            )
        )
    return rows, need


def apply(
    project: dict[str, Any],
    building: Any,
    types: dict[str, Any],
    designed: list[Any],
    combinations: list[str],
    extra: dict[str, Any],
    scope: dict[str, Any],
    ductility: str | None,
    profile_forces: Any,
) -> dict[str, Any]:
    """Adds the capacity design rows (prefixed "Detailing: ") to the members of the lateral
    system and returns ``{"joints": [...], "notes": [...]}`` in the shape of
    :func:`saengine.design.seismic_detailing.apply`."""
    from saengine.library.bim import ColumnElement

    notes: list[str] = []
    joints_out: list[dict[str, Any]] = []
    if ductility is None:
        if scope.get("detailingLevel"):
            notes.append(
                "low ductility (DCL): no capacity design or ductility detailing, the members "
                "by the material code alone"
                + code_context.cited("concreteMethods", "capacityDesign", sep=" (")
                + (")" if code_context.cite("concreteMethods", "capacityDesign") else "")
            )
        return {"joints": joints_out, "notes": notes}
    e_idx = sd.earthquake_indices(extra, len(combinations))
    by_id = {d.id: d for d in designed}
    beam_sections = {d.object.id: d.section for d in designed if d.kind == "beam"}
    beam_depths = {tid: s.depth for tid, s in beam_sections.items()}
    columns = {e.id: e for e in building.elements if isinstance(e, ColumnElement)}
    members_scope = scope.get("members", {})

    def lateral(member_id: str | None) -> bool:
        row = members_scope.get(member_id) if member_id else None
        return bool(row and row.get("role") == "lateral")

    def demands(pieces: list[Any], turned: bool) -> dj.SeismicDemands:
        return dj.seismic_demands(pieces, e_idx, turned, profile_forces)

    try:
        joints = dj.frame_joints(building, types)
    except (DesignError, ValueError, AttributeError) as error:
        joints = []
        notes.append(f"the beam-column joints could not be found: {error}")

    def joint_column(d: Any, level_m: float, below: bool) -> dj.JointColumn:
        dem = demands(sd._at_level(d.pieces, level_m, below) or d.pieces, d.turned)
        reinforcement = d.object.reinforcement
        tie = reinforcement.transverse if reinforcement else None
        return dj.JointColumn(
            d.section,
            float(getattr(d.element, "rotation", 0.0) or 0.0),
            dem.pmin,
            dem.pmax,
            reinforcement.cover if reinforcement else 40.0,
            tie.dia if tie else 10.0,
        )

    for joint in joints:
        below = by_id.get(joint.below)
        if below is None or below.kind != "column" or not lateral(joint.below):
            continue
        beams = {b.type: beam_sections[b.type] for b in joint.beams if b.type in beam_sections}
        if not beams:
            continue
        level_m = joint.level / 1e3
        try:
            jb = joint_column(below, level_m, True)
            above = by_id.get(joint.above) if joint.above else None
            ja = (
                joint_column(above, level_m, False)
                if above is not None and above.kind == "column"
                else None
            )
            strong, strong_notes = strong_column_rows(
                joint, beams, jb, ja, below.object.profile, ductility
            )
            shear_rows, shear_notes = joint_rows(
                joint, beams, jb, ja, below.object.profile, ductility
            )
        except DesignError as error:
            notes.append(f"{joint.id}: joint not checked: {error}")
            continue
        scwb: dict[str, Any] = {}
        factor = cd.class_rules(ductility).strongColumn
        for row in strong:
            axis = row["name"].rsplit(" ", 1)[-1]
            mrb = row["demand"] / factor
            scwb[axis] = {
                "ratio": round(row["capacity"] / mrb, 3) if mrb > 0 else None,
                "sumMnc": row["capacity"],
                "sumMnb": round(mrb, 2),
                "required": factor,
                "utilisation": 0.0 if row["flag"] else row["utilisation"],
                "notRequired": bool(row["flag"]),
            }
        governing = max(shear_rows, key=lambda r: r["utilisation"], default=None)
        rows = sd._tagged(strong + shear_rows)
        strength = [r for r in rows if not r["flag"]]
        rotation = float(getattr(below.element, "rotation", 0.0) or 0.0)
        joints_out.append(
            {
                "id": joint.id,
                "node": sd._node_at(
                    project, joint.position[0] / 1e3, joint.position[1] / 1e3, level_m
                ),
                "column": joint.below,
                "columnAbove": joint.above,
                "beams": sorted({b.id for b in joint.beams}),
                "type": sd._joint_type(joint, rotation),
                "level": joint.level,
                "scwb": {"x": scwb.get("x"), "y": scwb.get("y")},
                "axial": {
                    "below": [jb.pmin, jb.pmax],
                    "above": None if ja is None else [ja.pmin, ja.pmax],
                },
                "shear": None
                if governing is None
                else {
                    "Vj": governing["demand"],
                    "phiVn": governing["capacity"],
                    "utilisation": governing["utilisation"],
                },
                "checks": rows,
                "utilisation": max((r["utilisation"] for r in strength), default=0.0),
                "ok": all(r["ok"] for r in strength),
                "notes": strong_notes + shear_notes,
            }
        )

    c = cd.class_rules(ductility)
    for d in designed:
        if not lateral(d.id):
            continue
        reinforcement = d.object.reinforcement
        transverse = reinforcement.transverse if reinforcement else None
        dem = demands(d.pieces, d.turned)
        rows: list[dict[str, Any]] = []
        member_notes: list[str] = []
        dbl = min((x.dia for x in d.section.bars), default=0.0)
        context: dict[str, Any] = {
            "method": "curvatureDuctility",
            "ductility": ductility,
            "level": None,
            "lateral": True,
            "demands": dem,
            "cover": reinforcement.cover if reinforcement else 40.0,
            "shearLevel": None,
        }
        info: dict[str, Any] = {
            "frameType": ductility,
            "role": "lateral",
            "sdc": scope.get("sdc"),
            "provisions": [],
            "zones": None,
            "Ve": None,
            "phiVn": None,
            "clause": code_context.cite("concreteMethods", "capacityDesign") or None,
            "notes": member_notes,
        }
        try:
            if d.kind == "beam":
                clear = None
                if hasattr(d.element, "start") and len(d.element.start) == 2:
                    clear, _supports = sd._beam_supports(d.element, joints, columns, types)
                hw = d.section.depth
                dia = getattr(transverse, "dia", None) or c.hoopMinDia
                info["zones"] = {
                    "lo": c.beamCritical * hw,
                    "so": cd.beam_hoop_spacing(hw, dia, dbl or dia, ductility),
                    "outside": getattr(transverse, "spacing", None),
                }
                context.update(clearSpan=clear)
                if clear and d.capacities:
                    mrb = d.capacities[False].mn + d.capacities[True].mn
                    ved = cd.beam_capacity_shear(
                        d.capacities[False].mn, d.capacities[True].mn, clear, dem.gravity_shear,
                        ductility,
                    )  # fmt: skip
                    vrd = _beam_shear_resistance(d.section, transverse, ductility)
                    context["capacityShear"] = {"y": ved}
                    rows.append(
                        _row(
                            f"Capacity design shear ({ductility})",
                            ved / 1e3,
                            vrd / 1e3,
                            "kN",
                            f"VEd = γRd ΣMRb / lcl + VG = {c.gammaRdBeam:g} × {mrb / 1e6:.1f} / "
                            f"{clear:.0f} + {dem.gravity_shear / 1e3:.1f} kN"
                            + ("; VRd at cot θ = 1 in the critical regions" if ductility == "DCH"
                               else ""),
                            "beamShearCapacity",
                        )
                    )  # fmt: skip
                    info["Ve"], info["phiVn"] = rows[-1]["demand"], rows[-1]["capacity"]
                elif not clear:
                    member_notes.append("clear span not found: the capacity shear not checked")
            elif isinstance(d.element, ColumnElement):
                heights = sd._column_heights(d.element, joints, beam_depths)
                clear = max(heights) if heights else None
                context.update(clearHeight=clear)
                if clear:
                    hc = max(d.section.width, d.section.depth)
                    cover = context["cover"]
                    b0 = min(d.section.width, d.section.depth) - 2 * cover
                    info["zones"] = {
                        "lo": cd.column_critical_length(hc, clear, ductility),
                        "so": cd.column_hoop_spacing(b0, dbl, ductility),
                        "outside": getattr(transverse, "spacing", None),
                    }
                    found, need = _column_shear_rows(d, transverse, dem, clear, ductility)
                    rows += found
                    context["capacityShear"] = need
                    if found:
                        top = max(found, key=lambda r: r["utilisation"])
                        info["Ve"], info["phiVn"] = top["demand"], top["capacity"]
            else:
                member_notes.append("an inclined member: its capacity shear is not checked")
        except DesignError as error:
            member_notes.append(f"capacity design not checked: {error}")
        zones = info["zones"]
        if zones and transverse is not None:
            zone = getattr(transverse, "zone", None)
            spacing = getattr(zone, "spacing", None) or getattr(transverse, "spacing", None)
            if spacing:
                rows.append(
                    _row(
                        f"Hoop spacing over lcr = {zones['lo']:.0f} mm ({ductility})",
                        spacing,
                        zones["so"],
                        "mm",
                        "the hoops of the type's end zone (else its spacing) in the critical "
                        "regions",
                        "seismicBeams" if d.kind == "beam" else "seismicColumns",
                    )
                )
        d.context = context
        d.entry["checks"] = d.entry["checks"] + sd._tagged(rows)
        d.entry["detailing"] = info
        sd.rate(d.entry)
    notes.append(
        f"capacity design by ductility class {ductility}"
        + code_context.cited("concreteMethods", "capacityDesign", sep=" (")
        + (")" if code_context.cite("concreteMethods", "capacityDesign") else "")
        + "; the parent pack's special-frame detailing is not applied"
    )
    return {"joints": joints_out, "notes": notes}


# ─────────────────────────────── Design Reinforcement ───────────────────────────────


def propose_transverse(
    kind: str,
    section: Any,
    reinforcement: dict[str, Any],
    contexts: list[dict[str, Any]],
    stirrup_diameters: Any,
    min_spacing: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The proposed hoops of a beam or column type in the critical regions of its members:
    the class's hoop spacing and the capacity design shear's Asw/s (the zone at each end over
    lcr, first hoop at the class's distance), the type's spacing elsewhere; and what the
    detailing asks of the type (``{"zones", "sectionTooSmall", "notes"}``)."""
    from saengine.design import strut_shear
    from saengine.design.bars import round_down

    ductility = contexts[0]["ductility"]
    c = cd.class_rules(ductility)
    s = strut_shear.rules()
    u = design_strength.rules()
    t = dict(reinforcement["transverse"])
    legs = int(t.get("legs", 2) or 2)
    dbl = min((x.dia for x in section.bars), default=0.0)
    b, h = section.width, section.depth
    cover = float(reinforcement.get("cover") or 40.0)
    try:
        d = section.effective_depth(top=False) if kind == "beam" else 0.8 * h
    except DesignError:
        d = 0.9 * h
    z = s.leverArmShare * d
    f_ywd = design_strength.fyd(section.fy, u)
    cot = 1.0 if ductility == "DCH" and kind == "beam" else s.cotTheta[1]
    need_av_s = 0.0
    lengths = []
    for ctx in contexts:
        for ved in (ctx.get("capacityShear") or {}).values():
            need_av_s = max(need_av_s, ved / (z * f_ywd * cot))
        if kind == "beam":
            lengths.append(c.beamCritical * h)
        elif ctx.get("clearHeight"):
            lengths.append(cd.column_critical_length(max(b, h), ctx["clearHeight"], ductility))
    notes: list[str] = []
    chosen = None
    for dia in sorted(
        d_ for d_ in stirrup_diameters if d_ >= max(float(t["dia"]), c.hoopMinDia) - 1e-9
    ):
        if kind == "beam":
            so = cd.beam_hoop_spacing(h, dia, dbl or dia, ductility)
        else:
            so = cd.column_hoop_spacing(min(b, h) - 2 * cover, dbl, ductility)
        if need_av_s > 0:
            so = min(so, legs * bar_area(dia) / need_av_s)
        so = round_down(so)
        if so >= min_spacing - 1e-6:
            chosen = (dia, so)
            break
    if chosen is None:
        return reinforcement, {
            "zones": None,
            "sectionTooSmall": [
                (
                    f"no hoops up to Ø{max(stirrup_diameters):g} give the critical regions' "
                    f"spacing at {min_spacing:g} mm or more ({ductility})"
                )
            ],
            "notes": notes,
            "detailable": False,
        }
    dia, so = chosen
    zone = {"length": max(lengths) if lengths else c.beamCritical * h, "spacing": so,
            "first": c.beamFirstHoop}  # fmt: skip
    transverse = {**t, "dia": dia, "zone": zone}
    transverse.pop("splice", None)
    if need_av_s:
        notes.append(
            f"hoops for the capacity design shear ({ductility}): Asw/s {need_av_s:.2f} mm²/mm"
            + code_context.cited("concreteMethods", "capacityDesign", sep=" (")
            + (")" if code_context.cite("concreteMethods", "capacityDesign") else "")
        )
    return {**reinforcement, "transverse": transverse}, {
        "zones": zone,
        "sectionTooSmall": [],
        "notes": notes,
    }
