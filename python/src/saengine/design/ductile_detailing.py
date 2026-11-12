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

Alpha 9 C18c (the AS 3600 Appendix C and NZS 3101 forms): with ``basis`` "capacityFactor" the
method runs without partial factors (nominal strengths, the strength design's φ: fyd is fy and
the capacity shear's resistance the parent's φVn); ``levels`` give the groups that differ by
frame level (limited / moderately ductile); columns may take the NZS 3101 10.4.7 type
confinement by the axial load (``ashForm`` "axialLoad"), the confined length by N*/(φ f'c Ag)
(``confinedByAxial``) and the capacity design shear (``capacityShear``); joints the stress cap
min(a f'c, b MPa) and the horizontal joint hoops (``stressLimit``, ``reinforcementShare``);
walls the design shear by overstrength and dynamic magnification (``shearAmplification``,
applied in :func:`saengine.design.walls.wall_checks`), the boundary hoops and the confined
length (``boundaryAsh``, ``boundaryLength``).
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
    """The pack's ``concreteMethods.seismic`` of method ``ductileDetailing``, or None; alpha 9
    C18c: also without partial factors where the group's basis is ``capacityFactor``."""
    found = _group("seismic", "ductileDetailing")
    if found is not None:
        return found
    from saengine.codes.method_tables import chosen
    from saengine.design.tabulated_shear import _table

    found = chosen(_table(), "seismic", "ductileDetailing")
    if found is None or found.basis != "capacityFactor":
        return None
    if "seismic" in (getattr(_table(), "parentMethods", None) or ()):
        return None
    return found


def rules_for(level: str | None) -> Any | None:
    """Alpha 9 C18c: the method's groups for frame level ``level``: its own with the level's
    ``levels`` entry put over them (the method's own where the level gives none)."""
    r = rules()
    if r is None or not level:
        return r
    over = r.levels.get(level)
    if over is None:
        return r
    update = {k: getattr(over, k) for k in ("beams", "columns", "joints", "walls")}
    return r.model_copy(update={k: v for k, v in update.items() if v is not None})


def capacity_factor(r: Any = None) -> bool:
    """Alpha 9 C18c: True when the method runs on nominal strengths with φ."""
    r = r or rules()
    return r is not None and getattr(r, "basis", "designStrength") == "capacityFactor"


def design_yield(fy: float) -> float:
    """The diagonal bars' strength of coupling beams [MPa]: fyd, or φ fy with the walls'
    ``couplingPhi`` (capacity-factor basis; fy without it)."""
    r = rules_for("special")
    if capacity_factor(r):
        phi = r.walls.couplingPhi
        return fy * (float(phi) if phi is not None else 1.0)
    return _fyd(fy)


def _row(name: str, demand: float, capacity: float, unit: str, note: str = "", key: str = ""):
    from saengine.design.check import _check

    row = _check(f"{PREFIX}{name}{_paren(key) if key else ''}", demand, capacity, unit, None, note)
    return row


def _fyd(fy: float) -> float:
    if capacity_factor():  # Alpha 9 C18c: nominal strengths
        return fy
    from saengine.design import design_strength

    return design_strength.fyd(fy)


def _beam_resistance(s: Any, dia: float, legs: int, spacing: float) -> float:
    """φVn [N] of a beam with the hoops of its end zones: the tabulated method's, or (capacity-
    factor basis) the strength design's (:func:`saengine.design.rc.shear`)."""
    if capacity_factor():
        from saengine.design.rc import shear

        return float(shear(s, dia, legs, spacing).phi_vn)
    from saengine.design import tabulated_shear

    return float(tabulated_shear.beam_shear(s, dia, legs, spacing).phi_vn)


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
        zone_of = "D" if b.hoopZoneOnDepth else "d"  # Alpha 9 C18c
        rows.append(_row("Hoop diameter", b.hoopMinDia, zones.dia, "mm", key="seismicBeams"))
        if b.hoopZoneOnDepth and zones.zone_length is not None:
            rows.append(
                _row(
                    "Plastic hinge region", b.hoopZoneDepths * depth, zones.zone_length, "mm",
                    f"the close hoops over {b.hoopZoneDepths:g} D = "
                    f"{b.hoopZoneDepths * depth:.0f} mm from the faces", "seismicHinges",
                )
            )  # fmt: skip
        rows.append(
            _row(
                f"Hoop spacing within {b.hoopZoneDepths:g} {zone_of} of the faces", zones.in_zone,
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
            resistance = _beam_resistance(s, zones.dia, zones.legs, zones.in_zone)
            rows.append(
                _row(
                    "Capacity design shear", vu / 1e3, resistance / 1e3, "kN",
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
    lo_text = f"lo ≥ max({a:g} D, clear/{b:g}, {mm:g} mm)"
    context = getattr(d, "context", None) or {}
    axial = max(float((context.get("axial") or (0.0,))[0] or 0.0), 0.0)
    phi_c = float(c.ashAxial[3]) if c.ashAxial else 0.85
    n_ratio = axial / (phi_c * s.fc * s.gross_area) if s.gross_area > 0 else 0.0
    if c.confinedByAxial:  # Alpha 9 C18c: by N*/(φ f'c Ag) (NZS 3101 10.4.5 type)
        factor = next(
            (k for share, k in c.confinedByAxial if n_ratio <= share + 1e-9),
            c.confinedByAxial[-1][1],
        )
        lo = max(lo, factor * other)
        lo_text += f" and {factor:g} D at N*/(φ f'c Ag) = {n_ratio:.2f}"
    if zones.zone_length is not None:
        rows.append(_row("Confined length lo", lo, zones.zone_length, "mm",
                         lo_text, "seismicConfinement"))  # fmt: skip
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
        text = f"Ash ≥ max({c.ash[0]:g} (Ag/Ak - 1), {c.ash[1]:g}) s h fck/fy, h = {h:.0f} mm"
        if c.ashForm == "axialLoad" and c.ashAxial:
            # Alpha 9 C18c: Ash/(s h'') = (a - ρt m)/b (Ag/Ac) (f'c/fyt) N*/(φ f'c Ag) - c
            # (NZS 3101 10.4.7.4 type), h'' the core across the legs (h above).
            aa, bb, cc, _phi = c.ashAxial
            rho_t = s.steel_area / s.gross_area
            m = s.fy / (0.85 * s.fc)
            ratio = (aa - rho_t * m) / bb * (s.gross_area / ak) * (s.fc / fy_t) * n_ratio - cc
            need = max(ratio, 0.0) * zones.in_zone * h
            text = (
                f"Ash/(s h) ≥ ({aa:g} - ρt m)/{bb:g} (Ag/Ac) (f'c/fyt) N*/(φ f'c Ag) - {cc:g} = "
                f"{max(ratio, 0.0):.5f}, ρt m = {rho_t * m:.3f}, N*/(φ f'c Ag) = {n_ratio:.2f}, "
                f"h = {h:.0f} mm"
            )
        rows.append(_row(f"Ash of one leg, {label}", need, area, "mm²", text, "seismicConfinement"))
        rows.append(_row(f"Leg spacing h, {label}", h, c.hxMax, "mm", key="seismicConfinement"))
    rows += _column_capacity_shear(d, c, clear, zones)
    return rows


def _column_capacity_shear(d: Any, c: Any, clear: float | None, zones: Any) -> list[dict]:
    """Alpha 9 C18c: V*col = capacityShear (Mn,top + Mn,bottom) / the clear height against φVn
    with the hoops of the confined length (NZS 3101 Appendix D type)."""
    context = getattr(d, "context", None) or {}
    dem = context.get("demands")
    if c.capacityShear is None or not clear or dem is None:
        return []
    from saengine.design.rc import shear

    s = d.section
    moments = []
    for p in {float(dem.pmin), float(dem.pmax)}:
        for angle in (0.0, math.pi / 2):
            try:
                moments.append(dj.column_moment(s, p, angle))
            except (DesignError, ValueError):
                continue
    if not moments:
        return []
    mn = max(moments)
    vo = c.capacityShear * 2 * mn / clear
    try:
        resistance = float(shear(s, zones.dia, zones.legs, zones.in_zone).phi_vn)
    except (DesignError, ValueError):
        return []
    return [
        _row(
            "Column capacity design shear", vo / 1e3, resistance / 1e3, "kN",
            f"V*col = {c.capacityShear:g} (Mn,top + Mn,bottom) / {clear:.0f} mm, Mn = "
            f"{mn / 1e6:.1f} kN·m the largest over the earthquake axial forces; φVn with the "
            "hoops of the confined length", "capacityDesign",
        )
    ]  # fmt: skip


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
        limit_text = f"≤ {gamma:g} √fck bj hc"
        if j.stressLimit is not None:  # Alpha 9 C18c: vjh <= min(a f'c, b MPa) (NZS 15.4 type)
            share, cap = j.stressLimit
            capacity = min(share * below.section.fc, cap) * bj * hc
            limit_text = f"vjh ≤ min({share:g} f'c, {cap:g} MPa)"
        rows.append(
            _row(
                f"Joint shear at {joint.id}, along {label}", vj / 1e3, capacity / 1e3, "kN",
                f"Vj = {j.overstrength:g} {'fy' if capacity_factor() else 'fyd'} ΣAs - Vcol, Vcol = "
                f"{vcol / 1e3:.0f} kN; {limit_text}, bj = {bj:.0f} mm, hc = {hc:.0f} mm ({key} "
                "faces confined)", "seismicJoints",
            )
        )  # fmt: skip
        if j.reinforcementShare is not None and vj > 0:
            rows += _joint_hoop_rows(joint, below, items, j, vj, label)
    return rows


def _joint_hoop_rows(joint: Any, below: Any, items: list, j: Any, vjh: float, label: str):
    """Alpha 9 C18c: the horizontal joint hoops Ajh >= share Vjh / fyh (NZS 3101 15.4.4
    type): the column's hoops of its confined length taken through the joint, their legs along
    the frame direction over the beams' depth between the outer bars (SAEngine practice)."""
    reinforcement = below.object.reinforcement
    zones = dm.zones_of(reinforcement.transverse if reinforcement else None)
    need = j.reinforcementShare * vjh / below.section.fy
    depth = min(sec.depth for _, sec, _ in items)
    cover = reinforcement.cover if reinforcement else 40.0
    inside = max(depth - 2 * cover, 0.0)
    if zones is None or not zones.in_zone:
        provided, text = 0.0, "no hoops given"
    else:
        layers = max(math.floor(inside / zones.in_zone) + 1, 1)
        provided = layers * zones.legs * bar_area(zones.dia)
        text = (
            f"{layers} sets of {zones.legs} legs Ø{zones.dia:g} at {zones.in_zone:.0f} mm over "
            f"the beam depth less the covers, {inside:.0f} mm"
        )
    return [
        _row(
            f"Joint horizontal hoops at {joint.id}, along {label}", need, provided, "mm²",
            f"Ajh ≥ {j.reinforcementShare:g} Vjh / fyh = {need:.0f} mm²; {text}",
            "seismicJoints",
        )
    ]  # fmt: skip


def wall_rows(geometry: Any, bars: Any, forces: list[Any], fc: float) -> list[dict[str, Any]]:
    """The special shear wall rows of a wall pier (``walls``): thickness, ρ each way, the two
    curtains (thicker walls or τv above twoCurtainRoot √fck), the bar size and spacing, and the
    boundary elements where the extreme fibre stress of the factored forces exceeds
    boundaryStress × fck (to where it falls below boundaryStop × fck)."""
    from saengine.design.walls import extreme_stress

    r = rules_for("special")
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
        if required:
            rows += _boundary_rows(geometry, bars, worst, fc, w)
    return rows


def _boundary_rows(geometry: Any, bars: Any, worst: Any, fc: float, w: Any) -> list[dict]:
    """Alpha 9 C18c: the confined end of a ductile wall (NZS 3101 11.4.6 type): its length at
    least max(a lw, b c) with c the elastic compression depth of the governing combination
    (SAEngine practice for c), and its hoops Ash/(s h) >= max(a (Ag/Ac - 1), b) f'c/fyt across
    the thickness."""
    rows: list[dict[str, Any]] = []
    t, lw = geometry.thickness, geometry.length
    boundary = bars.boundary
    if w.boundaryLength is not None:
        a, b = w.boundaryLength
        sigma_top = worst.P / (t * lw) + abs(worst.M3) * (lw / 2) / (t * lw**3 / 12)
        sigma_bottom = worst.P / (t * lw) - abs(worst.M3) * (lw / 2) / (t * lw**3 / 12)
        if sigma_top > 0 and sigma_bottom < 0:
            c = lw * sigma_top / (sigma_top - sigma_bottom)
        else:
            c = lw if sigma_top > 0 else 0.0
        need = max(a * lw, b * c)
        rows.append(
            _row(
                "Confined end length", need, boundary.length if boundary else 0.0, "mm",
                f"≥ max({a:g} lw, {b:g} c), c = {c:.0f} mm the elastic compression depth",
                "seismicWallBoundary",
            )
        )  # fmt: skip
    if w.boundaryAsh is not None:
        if boundary is None or not boundary.hoops:
            rows.append(_row("Confined end hoops", 1, 0, "", "no boundary hoops given",
                             "seismicWallBoundary"))  # fmt: skip
            return rows
        a, b = w.boundaryAsh
        cover = bars.cover
        core_t = t - 2 * cover
        core_l = max(boundary.length - cover, 1.0)
        ag, ac = t * boundary.length, max(core_t * core_l, 1.0)
        h = max(core_l / max(boundary.legs_across - 1, 1), 1.0)
        need = max(a * (ag / ac - 1), b) * boundary.hoop_spacing * h * fc / bars_fy(bars)
        rows.append(
            _row(
                "Confined end hoops, one leg", need, bar_area(boundary.hoop_dia), "mm²",
                f"Ash ≥ max({a:g} (Ag/Ac - 1), {b:g}) s h f'c/fyt, s = "
                f"{boundary.hoop_spacing:.0f} mm, h = {h:.0f} mm", "seismicWallBoundary",
            )
        )  # fmt: skip
    return rows


def bars_fy(bars: Any) -> float:
    """fyt of a wall's hoops [MPa]: the type's (``fyt``) where given, else the pack's 500."""
    return float(getattr(bars, "fyt", None) or 500.0)


def coupling_row(
    span: float, depth: float, width: float, vu: float, fc: float, diagonal: bool
) -> dict[str, Any] | None:
    """Whether a coupling beam needs diagonal bars: τv > couplingRoot (ls/D) √fck with ls/D
    below couplingSpanRatio."""
    r = rules_for("special")
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
        zone = b.hoopZoneDepths * (section.depth if b.hoopZoneOnDepth else d)  # Alpha 9 C18c
        return min(a * d, n * db, mm), b.elsewhereShare * d, zone
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

    notes: list[str] = []
    level = scope.get("detailingLevel")
    r = rules_for(level)  # Alpha 9 C18c: the level's groups
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
    joints_out: list[dict[str, Any]] = []
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
        joints_out.append(_joint_entry(project, joint, below, rows, r.columns.strongColumn, sd))
    for d in designed:
        sd.rate(d.entry)
    return {"joints": joints_out, "notes": notes}


def _joint_entry(
    project: dict[str, Any], joint: Any, below: Any, rows: list[dict[str, Any]], factor: float,
    sd: Any,
) -> dict[str, Any]:  # fmt: skip
    """Alpha 9 C9b: one joint of the design report's ``joints`` (the shape of
    :func:`saengine.design.capacity_design.apply`'s), from its strong column and joint shear
    rows, so the workbench's joints view lists the joints under the pack too."""
    import re

    scwb: dict[str, Any] = {}
    shear_rows = []
    for row in rows:
        found = re.search(r"along ([xy])", row["name"])
        axis = found.group(1) if found else "x"
        if "Strong column" in row["name"]:
            mrb = row["demand"] / factor if factor else 0.0
            scwb[axis] = {
                "ratio": round(row["capacity"] / mrb, 3) if mrb > 0 else None,
                "sumMnc": row["capacity"],
                "sumMnb": round(mrb, 2),
                "required": factor,
                "utilisation": row["utilisation"],
                "notRequired": False,
            }
        elif "Joint shear" in row["name"]:
            shear_rows.append(row)
    governing = max(shear_rows, key=lambda r: r["utilisation"], default=None)
    strength = [r for r in rows if not r["flag"]]
    rotation = float(getattr(below.element, "rotation", 0.0) or 0.0)
    return {
        "id": joint.id,
        "node": sd._node_at(
            project, joint.position[0] / 1e3, joint.position[1] / 1e3, joint.level / 1e3
        ),
        "column": joint.below,
        "columnAbove": joint.above,
        "beams": sorted({b.id for b in joint.beams}),
        "type": sd._joint_type(joint, rotation),
        "level": joint.level,
        "scwb": {"x": scwb.get("x"), "y": scwb.get("y")},
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
        "notes": [],
    }
