"""Ductile detailing of reinforced-concrete moment frames by prescriptive limits (alpha 9 C8;
the pack's ``concreteMethods.seismic`` method ``ductileDetailing``, as IS 13920:2016 gives it).

A pack that picks this method replaces the default pack's earthquake-resistant detailing
(:mod:`saengine.design.seismic_detailing`, BNBC Sec 8.3) with these rows, for the members of
the seismic-force-resisting system where the project's detailing level is one of the pack's
``frames`` (IS 1893 zones III-V give "special"; a zone II project is designed by the member
rules alone). Rows carry the ``"Detailing: "`` prefix and the pack's clause.

Beams (``beams``): b >= minWidth and >= minRatio × D, D <= depthShare × the clear span; at
least minBars of minBarDia top and bottom; ρ of each face >= rhoMinRoot √fck / fy and <=
rhoMax; the bottom's capacity at least positiveShare × the top's at the joint face and any
section at least anyShare × the most (one layout per type: the faces are the sections);
hoops of at least hoopMinDia within hoopZoneDepths × d of the faces at <= min(a d, b db,min,
c mm), the first within firstHoop, elsewhere <= elsewhereShare × d; the capacity design shear
Vu = Vu,gravity + overstrength (Mu,hog + Mu,sag) / clear span (the design moment capacities)
against the shear resistance of the tabulated method.

Columns (``columns``): least dimension >= minDimension, its ratio to the other >= minRatio;
ρ within rho; special confining reinforcement over lo = max(a D, clear / b, c mm) at
s <= min(a × least dimension, b db,min, c mm) with Ash >= max(a (Ag/Ak - 1), b) s h fck / fy
each way (h the spacing of the legs across the core, at most hxMax), the spirals' ρ likewise
(× Dk); outside lo at most outsideShare × the least dimension.

Joints (``joints``): strong column / weak beam ΣMc >= strongColumn ΣMb in each frame direction
(the columns' design moment at the least favourable axial force of the earthquake combinations,
the beams' design moments in the sense of the sway; joints with no column above are exempt);
joint shear Vj = overstrength fyd (As,top + As,bottom of the beams' two sides) - Vcol <= γ
√fck bj hc, γ by the faces confined by beams covering three quarters of them, bj = min(bb +
widthShare hc, bc).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.design import ductile_joints as dj
from saengine.design import ductile_members as dm
from saengine.design.rc import DesignError, bar_area
from saengine.design.tabulated_shear import _group, _paren

PREFIX = "Detailing: "


def rules() -> Any | None:
    """The pack's ``concreteMethods.seismic`` of method ``ductileDetailing``, or None."""
    return _group("seismic", "ductileDetailing")


def _row(name: str, demand: float, capacity: float, unit: str, note: str = "", key: str = ""):
    from saengine.design.check import _check

    row = _check(f"{PREFIX}{name}{_paren(key) if key else ''}", demand, capacity, unit, None, note)
    return row


def _fyd(fy: float) -> float:
    from saengine.design import design_strength

    return design_strength.fyd(fy)


def _clear_spans(joints: list[Any], by_id: dict[str, Any]) -> dict[str, float]:
    """The clear span [mm] of each beam: its centre-to-centre length less half the column's
    dimension along it at each joint it frames into."""
    halves: dict[str, list[float]] = {}
    lengths: dict[str, float] = {}
    for joint in joints:
        column = by_id.get(joint.below)
        if column is None:
            continue
        rotation = float(getattr(column.element, "rotation", 0.0) or 0.0)
        for beam in joint.beams:
            try:
                frame = dj.column_frame(column.object.profile, rotation, np.asarray(beam.direction))
            except DesignError:
                continue
            halves.setdefault(beam.id, []).append(frame.along / 2)
            lengths[beam.id] = max(lengths.get(beam.id, 0.0), beam.length)
    return {k: max(lengths[k] - sum(v[:2]), 0.5 * lengths[k]) for k, v in halves.items()}


def beam_rows(d: Any, r: Any, clear: float | None, demands: Any) -> list[dict[str, Any]]:
    from saengine.design import tabulated_shear

    b = r.beams
    s = d.section
    rows: list[dict[str, Any]] = []
    width, depth = s.width, s.depth
    rows.append(_row(f"Width ≥ {b.minWidth:g} mm", b.minWidth, width, "mm", key="seismicBeams"))
    rows.append(
        _row(
            "Width / depth", b.minRatio, width / depth, "", f"b/D ≥ {b.minRatio:g}", "seismicBeams"
        )
    )
    if clear:
        rows.append(
            _row(
                "Depth / clear span", depth, b.depthShare * clear, "mm",
                f"D ≤ {b.depthShare:g} × the clear span {clear:.0f} mm", "seismicBeams",
            )
        )  # fmt: skip
    caps = d.capacities or {}
    for top, face in ((True, "top"), (False, "bottom")):
        bars = [x for x in s.bars if (x.y > 0 if top else x.y < 0)]
        big = [x for x in bars if x.dia >= b.minBarDia]
        rows.append(
            _row(
                f"Bars of at least {b.minBarDia:g} mm, {face}", b.minBars, len(big), "",
                key="seismicBeams",
            )
        )  # fmt: skip
        if not bars:
            continue
        try:
            dd = s.effective_depth(top=top)
        except DesignError:
            continue
        rho = sum(x.area for x in bars) / (width * dd)
        least = b.rhoMinRoot * math.sqrt(s.fc) / s.fy
        rows.append(
            _row(f"Least steel ratio, {face}", 100 * least, 100 * rho, "%",
                 f"ρ ≥ {b.rhoMinRoot:g} √fck / fy", "seismicBeams")
        )  # fmt: skip
        rows.append(_row(f"Largest steel ratio, {face}", 100 * rho, 100 * b.rhoMax, "%",
                         key="seismicBeams"))  # fmt: skip
    if caps:
        sag, hog = caps[False].phi_mn, caps[True].phi_mn
        rows.append(
            _row("Bottom capacity at the joint face", b.positiveShare * hog, sag, "kN·m",
                 f"Mu,sag ≥ {b.positiveShare:g} Mu,hog", "seismicBeams")
        )  # fmt: skip
        most = max(sag, hog)
        rows.append(
            _row("Capacity at any section", b.anyShare * most, min(sag, hog), "kN·m",
                 f"≥ {b.anyShare:g} × the most at the faces", "seismicBeams")
        )  # fmt: skip
        for row in rows[-2:]:
            row["demand"], row["capacity"] = (
                round(row["demand"] / 1e6, 2),
                round(row["capacity"] / 1e6, 2),
            )
    zones = dm.zones_of(d.object.reinforcement.transverse if d.object.reinforcement else None)
    try:
        dd = s.effective_depth(top=False)
    except DesignError:
        dd = 0.9 * depth
    db = min((x.dia for x in s.bars), default=0.0)
    if zones is None:
        rows.append(_row("Hoops", 1, 0, "", "no hoops", "seismicBeams"))
    else:
        a, nb, mm = b.hoopSpacing
        rows.append(_row("Hoop diameter", b.hoopMinDia, zones.dia, "mm", key="seismicBeams"))
        rows.append(
            _row(
                f"Hoop spacing within {b.hoopZoneDepths:g} d of the faces", zones.in_zone,
                min(a * dd, nb * db, mm), "mm",
                f"≤ min({a:g} d, {nb:g} db, {mm:g} mm), the first ≤ {b.firstHoop:g} mm from the face",
                "seismicBeams",
            )
        )  # fmt: skip
        rows.append(
            _row("Hoop spacing elsewhere", zones.spacing, b.elsewhereShare * dd, "mm",
                 f"≤ {b.elsewhereShare:g} d", "seismicBeams")
        )  # fmt: skip
        if caps and clear and demands is not None:
            vu = (
                demands.gravity_shear
                + b.overstrength * (caps[False].phi_mn + caps[True].phi_mn) / clear
            )
            res = tabulated_shear.beam_shear(s, zones.dia, zones.legs, zones.in_zone)
            rows.append(
                _row(
                    "Capacity design shear", vu / 1e3, res.phi_vn / 1e3, "kN",
                    f"Vu = Vu,gravity {demands.gravity_shear / 1e3:.1f} kN + {b.overstrength:g} "
                    f"(Mu,hog + Mu,sag) / {clear:.0f} mm; resistance with the hoops of the end zones",
                    "capacityDesign",
                )
            )  # fmt: skip
    return rows


def column_rows(d: Any, r: Any, clear: float | None) -> list[dict[str, Any]]:
    c = r.columns
    s = d.section
    rows: list[dict[str, Any]] = []
    least, other = sorted((s.width, s.depth))
    rows.append(_row(f"Least dimension ≥ {c.minDimension:g} mm", c.minDimension, least, "mm",
                     key="seismicColumns"))  # fmt: skip
    rows.append(_row("Least / other dimension", c.minRatio, least / other, "",
                     key="seismicColumns"))  # fmt: skip
    rho = s.steel_area / s.gross_area
    rows.append(_row("Least steel ratio", 100 * c.rho[0], 100 * rho, "%", key="seismicColumns"))
    rows.append(_row("Largest steel ratio", 100 * rho, 100 * c.rho[1], "%", key="seismicColumns"))
    reinforcement = d.object.reinforcement
    zones = dm.zones_of(reinforcement.transverse if reinforcement else None)
    if zones is None:
        rows.append(_row("Special confining reinforcement", 1, 0, "", "no ties", "seismicColumns"))
        return rows
    db = min((x.dia for x in s.bars), default=0.0)
    a, b, mm = c.confinedLength
    lo = max(a * other, (clear or 0.0) / b, mm)
    if zones.zone_length is not None:
        rows.append(_row("Confined length lo", lo, zones.zone_length, "mm",
                         f"lo ≥ max({a:g} D, clear/{b:g}, {mm:g} mm)", "seismicConfinement"))  # fmt: skip
    sa, sb, smm = c.confinedSpacing
    rows.append(
        _row("Hoop spacing in lo", zones.in_zone, min(sa * least, sb * db, smm), "mm",
             f"≤ min({sa:g} × least dimension, {sb:g} db, {smm:g} mm)", "seismicConfinement")
    )  # fmt: skip
    rows.append(_row("Hoop spacing outside lo", zones.spacing, c.outsideShare * least, "mm",
                     f"≤ {c.outsideShare:g} × the least dimension", "seismicColumns"))  # fmt: skip
    cover = reinforcement.cover if reinforcement else 40.0
    area = bar_area(zones.dia)
    fy_t = s.fy
    if s.profile.__class__.__name__ == "CircleProfile":
        dk = 2 * s.profile.radius - 2 * cover
        ak = math.pi * dk**2 / 4
        need = (
            max(c.spiral[0] * (s.gross_area / ak - 1), c.spiral[1])
            * zones.in_zone
            * dk
            * s.fc
            / fy_t
        )
        rows.append(
            _row("Ash of the circular hoops", need, area, "mm²",
                 f"Ash ≥ max({c.spiral[0]:g} (Ag/Ak - 1), {c.spiral[1]:g}) s Dk fck/fy", "seismicConfinement")
        )  # fmt: skip
        return rows
    core_x, core_y = s.width - 2 * cover, s.depth - 2 * cover
    ak = core_x * core_y
    for core, legs, label in ((core_x, zones.legs, "across the width"),
                              (core_y, zones.across_depth, "across the depth")):  # fmt: skip
        h = dm._hx(core, zones.dia, db, legs)
        need = max(c.ash[0] * (s.gross_area / ak - 1), c.ash[1]) * zones.in_zone * h * s.fc / fy_t
        rows.append(
            _row(f"Ash of one leg, {label}", need, area, "mm²",
                 f"Ash ≥ max({c.ash[0]:g} (Ag/Ak - 1), {c.ash[1]:g}) s h fck/fy, h = {h:.0f} mm",
                 "seismicConfinement")
        )  # fmt: skip
        rows.append(_row(f"Leg spacing h, {label}", h, c.hxMax, "mm", key="seismicConfinement"))
    return rows


def _axis_of(column: Any, beam: Any) -> tuple[int, Any]:
    rotation = float(getattr(column.element, "rotation", 0.0) or 0.0)
    frame = dj.column_frame(column.object.profile, rotation, np.asarray(beam.direction))
    return (0 if frame.axis == "x" else 1), frame


def joint_rows(
    joint: Any,
    below: Any,
    above: Any | None,
    beams: dict[str, Any],
    r: Any,
    demands: Any,
    demands_above: Any | None,
) -> list[dict[str, Any]]:
    """Strong column / weak beam and joint shear rows of one joint, per frame direction."""
    j = r.joints
    rows: list[dict[str, Any]] = []
    by_axis: dict[int, list[tuple[Any, Any, Any]]] = {}
    for beam in joint.beams:
        section = beams.get(beam.type)
        if section is None:
            continue
        try:
            axis, frame = _axis_of(below, beam)
        except DesignError:
            continue
        by_axis.setdefault(axis, []).append((beam, section, frame))
    rotation = float(getattr(below.element, "rotation", 0.0) or 0.0)
    try:
        gamma_bnbc, count, _ = dj.joint_confinement(joint, beams, below.object.profile, rotation)
        key = "4" if count == 4 else ("3" if count == 3 or gamma_bnbc == dj._gamma(3) else "other")
    except DesignError:
        key = "other"
    gamma = j.gamma.get(key, j.gamma.get("other", 1.0))
    height = (joint.height_below + (joint.height_above or joint.height_below)) / 2 or 3000.0
    for axis, items in sorted(by_axis.items()):
        frame = items[0][2]
        moments = [dj.beam_moments(sec) for _, sec, _ in items]
        if len(items) >= 2:
            m0, m1 = moments[0], moments[1]
            sum_mb = max(m0.mn_hog + m1.mn_sag, m0.mn_sag + m1.mn_hog)
            tension = max(m0.as_top + m1.as_bottom, m0.as_bottom + m1.as_top)
        else:
            sum_mb = max(moments[0].mn_hog, moments[0].mn_sag)
            tension = max(moments[0].as_top, moments[0].as_bottom)
        label = "x" if axis == 0 else "y"
        if above is not None and demands_above is not None:
            mc_b, _ = dj.lowest_column_moment(
                below.section, demands.pmin, demands.pmax, frame.compression
            )
            mc_a, _ = dj.lowest_column_moment(
                above.section, demands_above.pmin, demands_above.pmax, frame.compression
            )
            rows.append(
                _row(
                    f"Strong column / weak beam at {joint.id}, along {label}",
                    r.columns.strongColumn * sum_mb / 1e6, (mc_b + mc_a) / 1e6, "kN·m",
                    f"ΣMc ≥ {r.columns.strongColumn:g} ΣMb, ΣMb = {sum_mb / 1e6:.1f} kN·m",
                    "strongColumn",
                )
            )  # fmt: skip
        bb = min(sec.width for _, sec, _ in items)
        hc, bc = frame.along, frame.across
        bj = min(bb + j.widthShare * hc, bc)
        fy = min(sec.fy for _, sec, _ in items)
        vcol = j.overstrength * sum_mb / height
        vj = j.overstrength * _fyd(fy) * tension - vcol
        capacity = gamma * math.sqrt(below.section.fc) * bj * hc
        rows.append(
            _row(
                f"Joint shear at {joint.id}, along {label}", vj / 1e3, capacity / 1e3, "kN",
                f"Vj = {j.overstrength:g} fyd ΣAs - Vcol, Vcol = {vcol / 1e3:.0f} kN; ≤ {gamma:g} √fck "
                f"bj hc, bj = {bj:.0f} mm, hc = {hc:.0f} mm ({key} faces confined)",
                "seismicJoints",
            )
        )  # fmt: skip
    return rows


def wall_rows(geometry: Any, bars: Any, forces: list[Any], fc: float) -> list[dict[str, Any]]:
    """The special shear wall rows of a wall pier (``walls``): thickness, ρ each way, the two
    curtains (thicker walls or τv above twoCurtainRoot √fck), the bar size and spacing, and the
    boundary elements where the extreme fibre stress of the factored forces exceeds
    boundaryStress × fck (to where it falls below boundaryStop × fck)."""
    from saengine.design.walls import extreme_stress

    r = rules()
    if r is None:
        return []
    w = r.walls
    t, lw = geometry.thickness, geometry.length
    rows = [
        _row(
            f"Wall thickness ≥ {w.minThickness:g} mm", w.minThickness, t, "mm", key="seismicWalls"
        ),
        _row("Vertical steel ratio", 100 * w.rhoMin, 100 * bars.rho_l(t), "%", key="seismicWalls"),
        _row(
            "Horizontal steel ratio", 100 * w.rhoMin, 100 * bars.rho_t(t), "%", key="seismicWalls"
        ),
    ]
    vu = max((abs(f.V2) for f in forces), default=0.0)
    tv = vu / (t * 0.8 * lw) if lw > 0 else 0.0
    if t > w.twoCurtainThickness or tv > w.twoCurtainRoot * math.sqrt(fc):
        rows.append(
            _row("Two curtains", 2, bars.layers, "layers",
                 f"t > {w.twoCurtainThickness:g} mm or τv > {w.twoCurtainRoot:g} √fck", "seismicWalls")
        )  # fmt: skip
    dia = max(bars.vertical_dia, bars.horizontal_dia)
    rows.append(_row("Bar diameter", dia, w.barDiaShare * t, "mm",
                     f"≤ t / {1 / w.barDiaShare:g}", "seismicWalls"))  # fmt: skip
    a, b, mm = w.spacing
    limit = min(lw / a, b * t, mm)
    rows.append(_row("Bar spacing", max(bars.vertical_spacing, bars.horizontal_spacing), limit,
                     "mm", f"≤ min(lw/{a:g}, {b:g} t, {mm:g} mm)", "seismicWalls"))  # fmt: skip
    if forces:
        worst = max(forces, key=lambda f: extreme_stress(geometry, f.P, f.M3))
        sigma = extreme_stress(geometry, worst.P, worst.M3)
        required = sigma > w.boundaryStress * fc
        row = _row(
            "Boundary elements", 1.0 if required else 0.0, 1.0 if bars.boundary is not None else 0.0,
            "", f"σ = {sigma:.2f} MPa {'>' if required else '≤'} {w.boundaryStress:g} fck "
            f"({w.boundaryStress * fc:.2f} MPa); they may stop where σ < {w.boundaryStop:g} fck; "
            "confined as the columns' special confining reinforcement", "seismicWalls",
        )  # fmt: skip
        if not required:
            row["flag"] = True
        rows.append(row)
    return rows


def coupling_row(
    span: float, depth: float, width: float, vu: float, fc: float, diagonal: bool
) -> dict[str, Any] | None:
    """Whether a coupling beam needs diagonal bars: τv > couplingRoot (ls/D) √fck with ls/D
    below couplingSpanRatio."""
    r = rules()
    if r is None or depth <= 0:
        return None
    w = r.walls
    ratio = span / depth
    tv = vu / (width * 0.9 * depth)
    need = ratio < w.couplingSpanRatio and tv > w.couplingRoot * ratio * math.sqrt(fc)
    row = _row(
        "Coupling beam diagonal bars", 1.0 if need else 0.0, 1.0 if diagonal else 0.0, "",
        f"ls/D = {ratio:.2f}, τv = {tv:.2f} MPa against {w.couplingRoot:g} (ls/D) √fck; "
        "diagonal bars carry Vu = 2 Asd fyd sin α", "seismicCoupling",
    )  # fmt: skip
    if not need:
        row["flag"] = True
    return row


def proposal_caps(kind: str, section: Any) -> tuple[float, float, float] | None:
    """Design Reinforcement: (zone spacing, spacing elsewhere, least zone length) [mm] of a
    beam or column type by the pack's limits (None without the method)."""
    r = rules()
    if r is None:
        return None
    db = min((x.dia for x in section.bars), default=0.0)
    if kind == "beam":
        b = r.beams
        try:
            d = section.effective_depth(top=False)
        except DesignError:
            d = 0.9 * section.depth
        a, n, mm = b.hoopSpacing
        return min(a * d, n * db, mm), b.elsewhereShare * d, b.hoopZoneDepths * d
    c = r.columns
    least, other = sorted((section.width, section.depth))
    sa, sb, smm = c.confinedSpacing
    return (
        min(sa * least, sb * db, smm),
        c.outsideShare * least,
        max(c.confinedLength[0] * other, c.confinedLength[2]),
    )


def method_lines() -> list[str]:
    from saengine.design.tabulated_shear import cite

    return [
        (
            f"Ductile detailing ({cite('seismicDetailing')}) of the members of the seismic-force-"
            "resisting system where the detailing level is the pack's: beams (dimensions, bars, steel "
            "ratios, hoops in the end zones, capacity design shear from the moment capacities), "
            "columns (dimensions, steel ratio, special confining reinforcement over lo), joints "
            "(strong column / weak beam, joint shear) and, with the walls' design, special shear "
            "walls; they take the place of the parent pack's earthquake-resistant detailing."
        )
    ]


def apply(
    project: dict[str, Any],
    building: Any,
    types: dict[str, Any],
    designed: list[Any],
    combinations: list[str],
    extra: dict[str, Any],
    scope: dict[str, Any],
    settings: Any,
    profile_forces: Any,
) -> dict[str, Any]:
    """The ductile detailing rows of every designed member (``seismic_detailing.apply``'s
    signature and result: ``{"joints": [], "notes": [...]}``)."""
    from saengine.design import seismic_detailing as sd

    r = rules()
    notes: list[str] = []
    level = scope.get("detailingLevel")
    if r is None or level not in r.frames:
        return {"joints": [], "notes": notes}
    members_scope = scope.get("members", {})
    e_idx = sd.earthquake_indices(extra, len(combinations))
    by_id = {d.id: d for d in designed}
    beam_sections = {d.object.id: d.section for d in designed if d.kind == "beam"}
    try:
        joints = dj.frame_joints(building, types)
    except (DesignError, ValueError, AttributeError) as error:
        joints = []
        notes.append(f"the beam-column joints could not be found: {error}")
    clear = _clear_spans(joints, by_id)

    def lateral(d: Any) -> bool:
        m = members_scope.get(d.id)
        return bool(m and m.get("provisions") and m.get("role") == "lateral")

    def demands(d: Any) -> Any:
        return dj.seismic_demands(d.pieces, e_idx, d.turned, profile_forces) if e_idx else None

    heights: dict[str, float] = {}
    for joint in joints:
        if joint.below:
            heights[joint.below] = max(heights.get(joint.below, 0.0), joint.height_below)
    for d in designed:
        if not lateral(d):
            continue
        try:
            dem = demands(d)
            height = heights.get(d.id)
            clear_height = (
                height - max(beam_sections.values(), key=lambda x: x.depth).depth
                if height and beam_sections
                else height
            )
            # What Design Reinforcement proposes the hoop zones from (the parent's context
            # form, :func:`saengine.design.proposal.seismic_transverse`; capped by
            # :func:`proposal_caps`), without the parent's capacity shear rule.
            d.context = {
                "level": level,
                "lateral": True,
                "axial": (max(dem.pmax, 0.0) if dem is not None else 0.0, None),
                "demands": dem,
                "cover": d.object.reinforcement.cover if d.object.reinforcement else 40.0,
                "fullHeight": False,
                "shearLevel": None,
                "clearSpan": clear.get(d.id),
                "supports": [],
                "clearHeight": clear_height,
            }
            if d.kind == "beam":
                rows = beam_rows(d, r, clear.get(d.id), dem)
            else:
                rows = column_rows(d, r, clear_height)
        except (DesignError, ValueError, KeyError) as error:
            notes.append(f"{d.id}: ductile detailing not checked: {error}")
            continue
        d.entry["checks"].extend(rows)
    for joint in joints:
        below = by_id.get(joint.below)
        if below is None or below.kind != "column" or not lateral(below):
            continue
        beams = {b.type: beam_sections[b.type] for b in joint.beams if b.type in beam_sections}
        if not beams or not e_idx:
            continue
        above = by_id.get(joint.above) if joint.above else None
        try:
            rows = joint_rows(
                joint, below, above if above is not None and above.kind == "column" else None,
                beams, r, demands(below), demands(above) if above is not None else None,
            )  # fmt: skip
        except (DesignError, ValueError) as error:
            notes.append(f"{joint.id}: joint not checked: {error}")
            continue
        below.entry["checks"].extend(rows)
    for d in designed:
        sd.rate(d.entry)
    return {"joints": [], "notes": notes}
