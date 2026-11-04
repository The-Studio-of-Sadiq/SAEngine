"""The seismic grade in the member design: the grade's force factors, the seismic adjustment
factor γRE and the grade's detailing (alpha 9 C20b; the pack's ``seismic.gradeDesign``, method
``gradeFactors``, with the grades of ``seismic.seismicGrades``, as GB 50011-2010 5.4.2, 6.2
and 6.3 and GB 50010-2010 11.1-11.7 give them).

A pack opts in with ``seismic.gradeDesign`` (empty in every other pack: nothing here runs and
the design is unchanged).

- **The grade** (:func:`set_context`): :func:`saengine.fem.two_level_seismic.seismic_grade` of
  the project's structural system, the model's height (its highest node above its lowest),
  the site's seismic zone and the occupancy category; none (no zone, a system without a row,
  intensity 6 steel ...) leaves the factors at 1 (γRE still applies).
- **Forces** (:func:`apply`, before the member checks, so Design Reinforcement sizes from the
  same forces): in each earthquake combination (EX, EY or a response spectrum envelope) the
  earthquake part (the combination's lateral cases, ``_Piece.sway``) of each concrete member's
  forces is multiplied by the grade's factors (columns: the moments × ``strongColumn`` ηc, the
  shears × ηc × ``columnShear`` ηvc as the shear follows the amplified end moments; beams: the
  shears × ``beamShear`` ηvb), then every force × γRE of the member kind (``adjustment``: S
  <= R / γRE taken as γRE S <= R): concrete beams in bending, columns in compression and
  bending, every concrete shear and torsion, steel beams (strength), steel columns and braces
  (stability). Walls (:func:`wall_forces`, at the wall checks): the in-plane shear ×
  ``wallShear`` ηvw, then γRE of walls (bending) and shear. SAEngine practice, stated in the
  report: ηc on every column end and storey (the code's exemptions of the top storey and of
  μN < 0.15 not taken, on the safe side), the corner columns' 1.1 and the bottom-section
  factor of 6.2.3 not added, ηvw on every storey (the code's strengthened bottom region:
  on the safe side), γRE of columns the one at μN >= 0.15 (the larger: on the safe side), a
  wind part of an earthquake combination amplified with it (on the safe side).
- **Checks** (:func:`beam_rows`, :func:`column_rows`): the axial compression ratio μN = N /
  (fc A) of the earthquake combinations (N before γRE) at most the grade's ``axialRatio``; the
  volumetric ratio of the column hoops ρv at least λv fc / fyv (λv by μN from the grade's
  ``detailing.confinement``, fc at least that of ``confinementFckMin``) and ``confinementMin``;
  the end-zone hoops (spacing, size, length), the least steel of beams at the ends and in the
  span, the ends' x / h0 and As'/As, the columns' least total steel by the bar grade.

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from contextvars import ContextVar
from itertools import pairwise
from typing import Any

import numpy as np

from saengine.codes import context as code_context

#: The building's seismic grade (``two_level_seismic.seismic_grade``) during a design run.
_GRADE: ContextVar[dict[str, Any] | None] = ContextVar("saengine_seismic_grade", default=None)
#: The earthquake combinations' indices and the factors applied, during a design run.
_STATE: ContextVar[dict[str, Any] | None] = ContextVar("saengine_grade_state", default=None)

#: Component order of a piece's forces: N, Vy, Vz, T, My, Mz.
_N, _VY, _VZ, _T, _MY, _MZ = range(6)


def rule() -> Any | None:
    """The pack's ``seismic.gradeDesign`` (method ``gradeFactors``), or None."""
    try:
        found = getattr(code_context.table("seismic"), "gradeDesign", None)
    except Exception:  # noqa: BLE001 - a pack without the seismic table
        return None
    if found is None or getattr(found, "method", None) != "gradeFactors":
        return None
    return found


def _cite(key: str) -> str:
    found = code_context.cite("seismic", key)
    if found:
        return found
    r = rule()
    return getattr(r, "clause", "") if r is not None else ""


def _paren(key: str) -> str:
    found = _cite(key)
    return f" ({found})" if found else ""


def model_height(project: dict[str, Any]) -> float:
    """The model's height [m]: its highest node above its lowest."""
    zs = [float(n["coords"][2]) for n in project.get("nodes", []) if n.get("coords")]
    return max(zs) - min(zs) if zs else 0.0


def set_context(settings: Any, project: dict[str, Any]) -> dict[str, Any] | None:
    """Works out the building's seismic grade for the design run and keeps it (and resets the
    force state); None without the pack's rule or a grade."""
    _STATE.set(None)
    if rule() is None:
        _GRADE.set(None)
        return None
    from saengine.fem.seismic_design import zone_of
    from saengine.fem.two_level_seismic import seismic_grade
    from saengine.library.settings import derived

    try:
        values = derived(settings)
        zone = values.get("zone")
        z = values.get("Z")
        if zone is None and isinstance(z, int | float):
            zone = zone_of(z)
        found = seismic_grade(
            settings.seismic.system,
            model_height(project),
            zone,
            settings.occupancy.category,
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        found = None
    _GRADE.set(found)
    return found


def current() -> dict[str, Any] | None:
    """The building's seismic grade of the design run (None: none, or no rule)."""
    return _GRADE.get() if rule() is not None else None


def factor(key: str, default: float = 1.0) -> float:
    """The grade's factor ``key`` (strongColumn, columnShear, beamShear, wallShear,
    axialRatio, anchorage ...), ``default`` without a grade or the factor."""
    grade = current()
    if grade is None:
        return default
    return float(grade.get("factors", {}).get(key, default))


def detailing() -> Any | None:
    """The grade's ``detailing`` rules, or None."""
    grade = current()
    if grade is None:
        return None
    rules = code_context.table("seismic").seismicGrades
    found = rules.grades.get(grade["grade"]) if rules is not None else None
    return getattr(found, "detailing", None) if found is not None else None


# ───────────────────────────────────────── forces ─────────────────────────────────────────


def _vectors(kind: str, steel: bool) -> tuple[np.ndarray, np.ndarray] | None:
    """(η, γRE) per force component of a member kind, or None when nothing applies."""
    r = rule()
    if r is None:
        return None
    a = r.adjustment
    eta = np.ones(6)
    if steel:
        g = a.steelStrength if kind == "beam" else a.steelStability
        return eta, np.full(6, float(g))
    if kind == "beam":
        eta[[_VY, _VZ]] = factor("beamShear")
        gamma = np.array([a.beamBending, a.shear, a.shear, a.shear, a.beamBending, a.beamBending])
        return eta, gamma.astype(float)
    if kind == "column":
        eta_c = factor("strongColumn")
        eta[[_MY, _MZ]] = eta_c
        eta[[_VY, _VZ]] = eta_c * factor("columnShear")
        gamma = np.array(
            [a.columnBending, a.shear, a.shear, a.shear, a.columnBending, a.columnBending]
        )
        return eta, gamma.astype(float)
    return None


def _member_kind(object_type: Any, material: Any) -> tuple[str, bool] | None:
    """(kind, steel) of a member the rule acts on, or None."""
    from saengine.design import steel_design
    from saengine.library.materials import Category

    kind = getattr(object_type, "kind", None)
    if kind not in ("beam", "column", "brace") or material is None:
        return None
    if steel_design.is_steel(material):
        return kind, True
    if getattr(material, "category", None) == Category.CONCRETE and kind != "brace":
        return kind, False
    return None


def apply(
    pieces: dict[str, list[Any]],
    combinations: list[str],
    extra: dict[str, Any],
    members: list[tuple[str, str, Any]],
    types: dict[str, Any],
    mats: dict[str, Any],
) -> list[str]:
    """The grade's factors and γRE on the members' forces of the earthquake combinations, in
    place (see the module notes); the notes for the report ([] without the rule or an
    earthquake combination)."""
    from saengine.design.seismic_detailing import earthquake_indices

    if rule() is None:
        return []
    quake = earthquake_indices(extra, len(combinations))
    if not quake:
        return []
    applied: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for member_id, type_id, _element in members:
        t = types.get(type_id)
        if t is None:
            continue
        found = _member_kind(t, mats.get(getattr(t, "material", None)))
        if found is None:
            continue
        vectors = _vectors(*found)
        if vectors is None:
            continue
        eta, gamma = vectors
        for piece in pieces.get(member_id, []):
            _scale(piece, quake, eta, gamma)
        applied[member_id] = (eta, gamma)
    _STATE.set({"quake": set(quake), "applied": applied})
    return notes()


def _scale(piece: Any, quake: list[int], eta: np.ndarray, gamma: np.ndarray) -> None:
    """One piece's forces of the combinations ``quake``: (F + (η - 1) S) γ, its sway η S γ, its
    sustained, live and roof parts × γ (new arrays: the others share none)."""
    forces = list(piece.forces)
    sway = list(piece.sway) if piece.sway is not None else None
    parts = {
        name: list(getattr(piece, name)) if getattr(piece, name) is not None else None
        for name in ("sustained", "live", "roof")
    }
    for c in quake:
        if c >= len(forces) or forces[c] is None:
            continue
        f = np.asarray(forces[c], dtype=float)
        s = None
        if sway is not None and c < len(sway) and sway[c] is not None:
            s = np.asarray(sway[c], dtype=float)
        if s is not None and s.shape == f.shape:
            forces[c] = (f + (eta - 1.0) * s) * gamma
            sway[c] = eta * s * gamma  # type: ignore[index]
        else:
            forces[c] = f * gamma
        for name, values in parts.items():
            if values is not None and c < len(values) and values[c] is not None:
                values[c] = np.asarray(values[c], dtype=float) * gamma
    piece.forces = forces
    if sway is not None:
        piece.sway = sway
    for name, values in parts.items():
        if values is not None:
            setattr(piece, name, values)


def face_rows(
    data: dict[str, Any] | None,
    factors_of: list[dict[str, float]],
    pieces: list[Any],
    member_id: str,
) -> dict[int, list[np.ndarray]]:
    """The analysis's forces at the faces (:func:`saengine.design.face_forces.face_rows_of`)
    with the member's factors of :func:`apply` on the earthquake combinations: (F + (η - 1) E)
    γ, E the rows of the combination's lateral cases alone; unchanged for a member without."""
    from saengine.design import face_forces
    from saengine.design import slender as slenderness_design

    rows = face_forces.face_rows_of(data, factors_of, pieces)
    state = _STATE.get() or {}
    found = state.get("applied", {}).get(member_id)
    if found is None or not rows:
        return rows
    eta, gamma = found
    quake = state.get("quake", set())
    lateral = [
        {c: f for c, f in factors.items() if slenderness_design.is_lateral(c)}
        for factors in factors_of
    ]
    sway = face_forces.face_rows_of(data, lateral, pieces)
    out: dict[int, list[np.ndarray]] = {}
    for pid, per in rows.items():
        side = sway.get(pid)
        new = []
        for c, r in enumerate(per):
            if c not in quake:
                new.append(r)
                continue
            r = np.asarray(r, dtype=float)
            s = np.asarray(side[c], dtype=float) if side is not None and c < len(side) else None
            if s is not None and s.shape == r.shape and r.shape[-1] == 6:
                new.append((r + (eta - 1.0) * s) * gamma)
            elif r.shape[-1] == 6:
                new.append(r * gamma)
            else:
                new.append(r)
        out[pid] = new
    return out


def gamma_of(member_id: str, component: int = _N) -> float:
    """γRE applied to ``member_id``'s component (1 when none was)."""
    state = _STATE.get() or {}
    found = state.get("applied", {}).get(member_id)
    return float(found[1][component]) if found is not None else 1.0


def earthquake_combinations() -> set[int]:
    """The indices of the earthquake combinations the factors were applied to."""
    return set((_STATE.get() or {}).get("quake", set()))


def wall_forces(forces: list[Any]) -> tuple[list[Any], str | None]:
    """The earthquake combinations' pier forces with ηvw on the in-plane shear and γRE (walls'
    bending on P, M3, M2; shear on V2, V3); unchanged without the rule."""
    from dataclasses import replace

    r = rule()
    if r is None or not forces:
        return forces, None
    a = r.adjustment
    eta = factor("wallShear")
    out = []
    for f in forces:
        if not getattr(f, "earthquake", False):
            out.append(f)
            continue
        out.append(
            replace(
                f,
                P=f.P * a.wallBending,
                M3=f.M3 * a.wallBending,
                M2=f.M2 * a.wallBending,
                V2=f.V2 * eta * a.shear,
                V3=f.V3 * a.shear,
            )
        )
    note = (
        f"earthquake combinations: in-plane shear × ηvw = {eta:g} (the seismic grade) and the "
        f"forces × γRE ({a.wallBending:g} bending, {a.shear:g} shear){_paren('adjustment')}"
    )
    return out, note


def notes() -> list[str]:
    """The report's lines of the factors in force."""
    r = rule()
    if r is None:
        return []
    a = r.adjustment
    grade = current()
    out = []
    if grade is not None:
        out.append(
            f"seismic grade {grade['label']} in the member design: earthquake part of the "
            f"forces × columns ηc = {factor('strongColumn'):g} (moments), ηc ηvc = "
            f"{factor('strongColumn') * factor('columnShear'):g} (shears), beams ηvb = "
            f"{factor('beamShear'):g} (shears), walls ηvw = {factor('wallShear'):g} (in-plane "
            f"shear){_paren('grades')}; ηc on every column end and storey, ηvw on every storey "
            "(SAEngine practice, on the safe side)"
        )
    else:
        out.append(
            "no seismic grade found for the system, height and intensity: the grade's force "
            "factors are not applied"
        )
    out.append(
        f"γRE{_paren('adjustment')} on the earthquake combinations' forces: concrete beams "
        f"{a.beamBending:g}, columns {a.columnBending:g}, walls {a.wallBending:g}, shear and "
        f"torsion {a.shear:g}; steel beams {a.steelStrength:g}, steel columns and braces "
        f"{a.steelStability:g} (the columns' value at μN >= 0.15 for every column: on the safe "
        "side)"
    )
    return out


# ───────────────────────────────────────── checks ─────────────────────────────────────────


def _row(name: str, demand: float, capacity: float, unit: str, note: str, **kw: Any):
    from saengine.design.check import _check

    return _check(name, demand, capacity, unit, kw.get("combination"), note, kw.get("flag", False))


def _along(points: list[tuple[float, float]], x: float) -> float:
    pts = sorted((float(a), float(b)) for a, b in points)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in pairwise(pts):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
    return pts[-1][1]


def _fcd(fck: float) -> float:
    from saengine.design import design_strength

    if design_strength.partial_factors():
        return design_strength.fcd(fck)
    return fck


def _fyd(fyk: float) -> float:
    from saengine.design import design_strength

    if design_strength.partial_factors():
        return design_strength.fyd(fyk)
    return fyk


def _ftd(fck: float) -> float:
    from saengine.design import design_strength

    if design_strength.partial_factors():
        return design_strength.fctd(fck)
    return 0.0


def axial_ratio(
    member_id: str,
    section: Any,
    pieces: list[Any],
    combinations: list[str],
    turned: bool,
) -> tuple[float, str | None]:
    """(μN = N / (fcd A), its combination) of a column's earthquake combinations, N before γRE
    (0 without one)."""
    from saengine.design.check import _profile_forces

    quake = earthquake_combinations()
    gamma = gamma_of(member_id, _N)
    best, name = 0.0, None
    area = float(section.gross_area)
    fc = _fcd(section.fc)
    if area <= 0 or fc <= 0:
        return 0.0, None
    for piece in pieces:
        for c, forces in enumerate(piece.forces):
            if c not in quake:
                continue
            values = _profile_forces(piece, turned, forces)
            n = float(np.max(np.asarray(values["P"], dtype=float))) / gamma
            if n / (fc * area) > best:
                best, name = n / (fc * area), combinations[c] if c < len(combinations) else None
    return best, name


def _hoop_ratio(section: Any, transverse: Any, cover: float, spacing: float) -> float:
    """ρv of rectangular hoops: (nx As lx + ny As ly) / (Acor s), the hoops' centrelines."""
    from saengine.design.rc import bar_area

    dia = float(transverse.dia)
    lx = section.width - 2 * cover - dia
    ly = section.depth - 2 * cover - dia
    if lx <= 0 or ly <= 0 or spacing <= 0:
        return 0.0
    legs_y = int(transverse.legs)  # legs along y, counted across x
    legs_x = int(getattr(transverse, "legsX", None) or transverse.legs)
    area = bar_area(dia)
    return (legs_y * area * ly + legs_x * area * lx) / (lx * ly * spacing)


def column_rows(
    member_id: str,
    section: Any,
    transverse: Any,
    cover: float | None,
    pieces: list[Any],
    combinations: list[str],
    turned: bool,
    clear_height: float | None = None,
) -> list[dict[str, Any]]:
    """The grade's rows of a concrete column (see the module notes)."""
    grade = current()
    if grade is None:
        return []
    rows: list[dict[str, Any]] = []
    mu, combination = axial_ratio(member_id, section, pieces, combinations, turned)
    limit = factor("axialRatio", 0.0)
    if limit > 0 and combination is not None:
        rows.append(
            _row(
                f"Axial compression ratio μN{_paren('axialRatio')}",
                mu,
                limit,
                "",
                f"μN = N / (fc A) of the earthquake combinations (N before γRE), at most "
                f"{limit:g} for {grade['label']}",
                combination=combination,
            )
        )
    d = detailing()
    if d is None:
        return rows
    bars = [b.dia for b in section.bars] or [0.0]
    ratio = section.steel_area / section.gross_area if section.gross_area > 0 else 0.0
    if d.columnSteel:
        least = float(d.columnSteel.get("interior", min(d.columnSteel.values())))
        added = 0.0
        for fyk, extra in sorted(d.columnSteelIncrease):
            if section.fy >= fyk - 1e-9:
                added = float(extra)
        need = least + added
        rows.append(
            _row(
                f"Least column steel of the grade{_paren('columnSteel')}",
                100 * need,
                100 * ratio,
                "%",
                f"{100 * least:g} % (interior and edge columns"
                + (
                    f"; corner columns {100 * d.columnSteel['corner']:g} %, not told apart"
                    if "corner" in d.columnSteel
                    else ""
                )
                + (f") + {100 * added:g} % for the bar grade" if added else ")"),
            )
        )
    if transverse is None:
        return rows
    zone = getattr(transverse, "zone", None)
    spacing = float(zone.spacing if zone is not None else transverse.spacing)
    if d.columnHoops is not None:
        a, mm = d.columnHoops
        rows.append(
            _row(
                f"End zone hoop spacing{_paren('columnHoops')}",
                spacing,
                min(a * min(bars), mm),
                "mm",
                f"at most min({a:g} d, {mm:g} mm), d the least longitudinal bar"
                + ("" if zone is not None else "; no end zone given: the spacing all along"),
            )
        )
    if d.columnHoopDia is not None:
        rows.append(
            _row(
                f"End zone hoop diameter{_paren('columnHoops')}",
                d.columnHoopDia,
                float(transverse.dia),
                "mm",
                f"at least {d.columnHoopDia:g} mm",
            )
        )
    if d.columnHoopZone is not None and zone is not None and zone.length:
        a, b, mm = d.columnHoopZone
        hc = max(section.width, section.depth)
        need = max(a * hc, (clear_height or 0.0) / b, mm)
        rows.append(
            _row(
                f"End zone length{_paren('columnHoops')}",
                need,
                float(zone.length),
                "mm",
                f"at least max({a:g} hc, Hn/{b:g}, {mm:g} mm)",
            )
        )
    if d.confinement and cover is not None:
        lam_v = _along(list(d.confinement), mu)
        fck = max(section.fc, d.confinementFckMin or 0.0)
        need = lam_v * _fcd(fck) / _fyd(section.fy)
        if d.confinementMin is not None:
            need = max(need, float(d.confinementMin))
        rho_v = _hoop_ratio(section, transverse, float(cover), spacing)
        rows.append(
            _row(
                f"Hoop volumetric ratio ρv{_paren('confinement')}",
                100 * need,
                100 * rho_v,
                "%",
                f"ρv >= λv fc / fyv, λv = {lam_v:.3f} at μN = {mu:.2f}"
                + (f", fc at least of fck {d.confinementFckMin:g}" if d.confinementFckMin else "")
                + (f", at least {100 * d.confinementMin:g} %" if d.confinementMin else "")
                + " (the hoops' fy taken as the bars')",
            )
        )
    return rows


def beam_rows(section: Any, transverse: Any, capacities: dict[bool, Any]) -> list[dict[str, Any]]:
    """The grade's rows of a concrete beam (see the module notes); ``capacities`` the flexural
    capacities (False sagging, True hogging) for the ends' x / h0."""
    grade = current()
    d = detailing()
    if grade is None or d is None:
        return []
    rows: list[dict[str, Any]] = []
    b, h = section.width, section.depth
    ftd, fyd = _ftd(section.fc), _fyd(section.fy)
    top = sum(x.area for x in section.bars if x.y > 0)
    bottom = sum(x.area for x in section.bars if x.y < 0)
    for name, rule_, area, where in (
        ("ends (top)", d.beamEndSteel, top, "the supports"),
        ("span (bottom)", d.beamSpanSteel, bottom, "the span"),
    ):
        if rule_ is None:
            continue
        ratio, c = rule_
        need = max(float(ratio), c * ftd / fyd if fyd > 0 else 0.0)
        rows.append(
            _row(
                f"Least beam steel of the grade, {name}{_paren('beamSteel')}",
                need * b * h,
                area,
                "mm²",
                f"As/(b h) >= max({100 * ratio:g} %, {c:g} ft/fy) at {where}",
            )
        )
    if d.beamEndCompression is not None and top > 0:
        rows.append(
            _row(
                f"Bottom steel at the ends of the grade{_paren('beamSteel')}",
                d.beamEndCompression * top,
                bottom,
                "mm²",
                f"As'/As >= {d.beamEndCompression:g} at the ends (the bottom bars all along taken)",
            )
        )
    cap = capacities.get(True)
    if d.beamEndDepth is not None and cap is not None and math.isfinite(cap.eps_t):
        from saengine.design import design_strength

        if design_strength.partial_factors():
            eps_cu = design_strength.ultimate_strain(section.fc)
            beta = design_strength.properties(section.fc).lam
            xi = beta * eps_cu / (eps_cu + max(cap.eps_t, 0.0))
            rows.append(
                _row(
                    f"Compression zone at the ends of the grade{_paren('beamEndDepth')}",
                    xi,
                    d.beamEndDepth,
                    "",
                    f"x/h0 = β1 xc/h0 at most {d.beamEndDepth:g} (hogging, the bottom bars in "
                    "compression)",
                )
            )
    if transverse is None:
        return rows
    zone = getattr(transverse, "zone", None)
    spacing = float(zone.spacing if zone is not None else transverse.spacing)
    bars = [x.dia for x in section.bars] or [0.0]
    if d.beamHoops is not None:
        a, k, mm = d.beamHoops
        rows.append(
            _row(
                f"End zone hoop spacing{_paren('beamHoops')}",
                spacing,
                min(h / a, k * min(bars), mm),
                "mm",
                f"at most min(hb/{a:g}, {k:g} d, {mm:g} mm), d the least longitudinal bar"
                + ("" if zone is not None else "; no end zone given: the spacing all along"),
            )
        )
    if d.beamHoopDia is not None:
        rows.append(
            _row(
                f"End zone hoop diameter{_paren('beamHoops')}",
                d.beamHoopDia,
                float(transverse.dia),
                "mm",
                f"at least {d.beamHoopDia:g} mm",
            )
        )
    if d.beamHoopZone is not None and zone is not None and zone.length:
        a, mm = d.beamHoopZone
        rows.append(
            _row(
                f"End zone length{_paren('beamHoops')}",
                max(a * h, mm),
                float(zone.length),
                "mm",
                f"at least max({a:g} hb, {mm:g} mm)",
            )
        )
    return rows


def wall_rows(rho_l: float, rho_t: float) -> list[dict[str, Any]]:
    """The grade's least web steel of a wall, each way."""
    d = detailing()
    if d is None or d.wallWebMin is None:
        return []
    return [
        _row(
            f"Wall web steel of the grade, {name}{_paren('wallSteel')}",
            100 * d.wallWebMin,
            100 * rho,
            "%",
            f"at least {100 * d.wallWebMin:g} % each way",
        )
        for name, rho in (("vertical", rho_l), ("horizontal", rho_t))
    ]


def method_lines() -> list[str]:
    """The report's method line (none without the rule)."""
    r = rule()
    if r is None:
        return []
    return [
        "Seismic grade in the member design"
        + _paren("grades")
        + ": the earthquake part of the forces × the grade's ηc, ηvc, ηvb, ηvw, every force of "
        "the earthquake combinations × γRE"
        + _paren("adjustment")
        + "; the axial compression ratio μN, the hoops' λv, the end zones and the least steel of "
        "the grade checked (Design Reinforcement sizes from the same forces)."
    ]
