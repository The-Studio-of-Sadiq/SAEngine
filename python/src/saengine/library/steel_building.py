"""A steel building from a grid and storeys (alpha 9 C3b): the New Building wizard's "Steel
moment frame" and "Steel braced frame" systems (``BuildingSpec.system`` ``steelMomentFrame`` or
``steelBracedFrame``; :func:`saengine.library.generator.generate_building` hands them here).

Columns at every grid intersection from the base to the roof (one per storey), beams on every
grid line of every floor, a reinforced concrete slab in every bay on the beams, and in a braced
frame building X braces in one bay of each perimeter frame line in every storey (BIM additions,
06 BIM). The structural system is the code pack's: the first of its candidates for the kind
(``seismic.generatorSystems``, else the generator's own: ordinary, intermediate, special moment
frames; ordinary, special concentrically braced frames) that the Seismic Design Category and
the height permit; it is written to 02 Project Settings, so Design mode checks the members
with the steel seismic provisions of that system.

The sizes are PRELIMINARY (SAEngine's rules of thumb, stated in the notes; the analysis and
Design mode check every member and propose the lightest passing sections):

- Beams: the lightest section of the beam family whose plastic modulus carries the factored
  gravity moment (1.2 D + 1.6 L, w l²/8; continuous moment frame beams w l²/10 with a lateral
  allowance), whose inertia keeps the live load deflection within span/360 and whose depth is
  at least span/24; the tributary width is half the bays on each side.
- Columns: the axial force of the tributary area of every floor above (1.2 D + 1.6 L) over
  0.5 Fy (braced and gravity columns) or, in moment frames, with the position factors of the RC
  generator and a plastic modulus at least the strong column ratio times the framing beams';
  storey groups as the RC generator's. Every member within the width-thickness limits the
  code pack's steel seismic provisions ask of it in the system (highly or moderately ductile).
- Braces: square hollow sections whose design compressive strength (flexural buckling of the
  full diagonal, K = 1) carries the storey shear share of the larger of the equivalent static
  seismic force (the pack's coefficient at the approximate period) and the wind, the X braces
  of two frame lines per direction sharing it, with Lc/r at most the pack's brace limit.
- Slabs: the two-way rule with stiff supports, ln (0.8 + fy/1400) / (36 + 9 β), at least 90
  mm and the spec's least slab; isolated footings under the columns as the RC generator's.
"""

from __future__ import annotations

import contextlib
import math
from typing import Any

from saengine.codes import context as code_context
from saengine.library import code_data
from saengine.library import steel_sections as tbl
from saengine.library.defaults import default_material_library
from saengine.library.floorplan import FloorPlan
from saengine.library.generator import (
    DEFAULT_BEARING,
    POSITION_FACTOR,
    BuildingSpec,
    G,
    _deep_merge,
    _template,
    ceil_to,
    letters,
    settings_patch,
)
from saengine.library.materials import Category, MaterialDefaults
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import ProjectSettings, partition_case, seismic_weight_rule
from saengine.library.substructure import Substructure

#: The generator's own candidates by kind, least ductile first (a pack's
#: ``seismic.generatorSystems`` replaces them).
CANDIDATES = {
    "steelMomentFrame": ["steelOmf", "steelImf", "steelSmf"],
    "steelBracedFrame": ["steelOcbf", "steelScbf"],
}
#: Section families: beams, braced frame columns, moment frame columns, braces.
BEAM_FAMILY, COLUMN_FAMILY, BRACE_FAMILY = "IPE", "HEB", "SHS"
#: Steel framing self-weight allowance in the gravity loads [kN/m²] (rule of thumb).
FRAMING_WEIGHT = 0.5
#: Beam rules of thumb: live load deflection span/360, depth at least span/24, the lateral
#: allowance on the moment of moment frame beams.
DEFLECTION_DIVISOR, DEPTH_DIVISOR, LATERAL_ALLOWANCE = 360.0, 24.0, 1.5
#: Column rules: gravity columns at 0.5 Fy, the strong column ratio of moment frame columns.
COLUMN_STRESS_SHARE, STRONG_COLUMN = 0.5, 1.2
#: Braces: KL/r at most this when the pack gives no limit.
BRACE_SLENDERNESS = 200.0
PHI_C = 0.9


def _candidates(kind: str, seismic: Any) -> list[str]:
    listed = (getattr(seismic, "generatorSystems", None) or {}).get(kind)
    return list(listed) if listed else list(CANDIDATES[kind])


def choose_system(kind: str, sdc: str | None, height_m: float) -> tuple[str, Any]:
    """``(id, row)`` of the first candidate system of the pack in force that Seismic Design
    Category ``sdc`` (B without one) and the height permit (its ``heightLimits``: none no
    limit, 0 not permitted; a category the row does not list: no limit). Raises
    ``ValueError`` when none is."""
    seismic = code_context.table("seismic")
    category = sdc or "B"
    for system in _candidates(kind, seismic):
        row = seismic.systems.get(system)
        if row is None:
            continue
        limit = (row.heightLimits or {}).get(category)
        if limit is not None and (float(limit) <= 0 or height_m > float(limit)):
            continue
        return system, row
    raise ValueError(
        f"no {kind} system of the code pack is permitted in Seismic Design Category {category} "
        f"at {height_m:.1f} m"
    )


def _family(name: str) -> list[Any]:
    return [s for s in tbl.family(name) if s is not None]


def _always(_section: Any) -> bool:
    return True


def ductility_rule(system_id: str, member: str, fy: float, e: float, material: Any):
    """A test of a section against the width-thickness limits the steel seismic provisions of
    the code pack ask of a ``member`` ("beam", "column", "brace") of ``system_id``
    (``steelSeismic``: highly ductile ``widthThickness``, moderately ductile
    ``widthThicknessModerate``; webs at Ca = 0), and the level ("" without limits)."""
    try:
        t = code_context.table("steelSeismic")
    except Exception:  # noqa: BLE001 - no steel seismic table: no limits
        return _always, ""
    level = ""
    frame = (getattr(t, "systems", None) or {}).get(system_id)
    braced = (getattr(t, "bracedSystems", None) or {}).get(system_id)
    if frame is not None and frame in (t.frames or {}) and member in ("beam", "column"):
        level = {"seismic": "high", "moderate": "moderate"}.get(t.frames[frame].compactness, "")
    elif braced is not None and braced in (getattr(t, "concentric", None) or {}):
        rules = t.concentric[braced]
        if member in (getattr(rules, "compactMembers", None) or []):
            level = "high"
        elif member in (getattr(rules, "moderateMembers", None) or []):
            level = "moderate"
    group = t.widthThickness
    if level == "moderate":
        group = getattr(t, "widthThicknessModerate", None)
        if group is None:
            return _always, ""
    if not level:
        return _always, ""
    from saengine.design.steel.seismic import expected_yield_ratio

    def passes(s: Any) -> bool:
        ry = expected_yield_ratio(material, s.shape, t)
        root = math.sqrt(e / (ry * fy))
        if s.shape == "I":
            web = (s.h - 2 * s.tf - 2 * s.r) / s.tw
            return s.b / (2 * s.tf) <= group.iFlange * root and web <= group.web.linearA * root
        if s.shape == "rectangleHollow":
            return max(s.b, s.h) / s.tw - 3 <= group.rectHss * root
        return True

    return passes, "highly" if level == "high" else "moderately"


def _beam_section(
    span: float, w_dead: float, w_live: float, fy: float, e: float, moment: bool, ok=_always
):
    """The lightest beam section and the governing reason (``span`` [mm], loads [kN/m]);
    ``ok`` the seismic width-thickness test."""
    wu = 1.2 * w_dead + 1.6 * w_live  # kN/m = N/mm
    mu = wu * span**2 / (10.0 if moment else 8.0) * (LATERAL_ALLOWANCE if moment else 1.0)
    z_need = mu / (0.9 * fy)
    i_need = 5 * w_live * span**4 / (384 * e * span / DEFLECTION_DIVISOR)
    d_need = span / DEPTH_DIVISOR
    found = tbl.lightest(
        _family(BEAM_FAMILY),
        lambda s: s.Zx >= z_need and s.Ix >= i_need and s.h >= d_need and ok(s),
    )
    if found is None:
        found = max(_family(BEAM_FAMILY), key=lambda s: s.Zx)
    return found, {"Mu": mu / 1e6, "Zx": z_need, "Ix": i_need, "d": d_need}


def _column_section(pu: float, fy: float, z_beam: float, moment: bool, ok=_always):
    """The lightest column section for ``pu`` [N] (moment frames: also Zx >= the strong
    column ratio × the framing beams' Zx); ``ok`` the seismic width-thickness test."""
    a_need = pu / (COLUMN_STRESS_SHARE * fy)
    z_need = STRONG_COLUMN * z_beam if moment else 0.0
    found = tbl.lightest(
        _family(COLUMN_FAMILY), lambda s: s.A >= a_need and s.Zx >= z_need and ok(s)
    )
    if found is None:
        found = tbl.lightest(_family(COLUMN_FAMILY), lambda s: s.A >= a_need and s.Zx >= z_need)
        if found is not None:
            return (
                found,
                f"{found.name}: no column section meets the seismic width-thickness limits",
            )
        found = max(_family(COLUMN_FAMILY), key=lambda s: s.A)
        return found, f"{found.name}: the largest section of the family is short of the load"
    return found, ""


def _compression(section: Any, length: float, fy: float, e: float) -> float:
    """φc Pn [N] of flexural buckling over ``length`` [mm] (K = 1; the inelastic and elastic
    curves of the specifications' flexural buckling, 0.658^(Fy/Fe) Fy and 0.877 Fe)."""
    r = min(section.rx, section.ry)
    slender = length / r
    fe = math.pi**2 * e / slender**2
    fcr = 0.658 ** (fy / fe) * fy if slender <= 4.71 * math.sqrt(e / fy) else 0.877 * fe
    return PHI_C * fcr * section.A


def _brace_section(force: float, length: float, fy: float, e: float, limit: float, ok=_always):
    """The lightest brace section for the axial ``force`` [N] over ``length`` [mm]; ``ok`` the
    seismic width-thickness test."""
    found = tbl.lightest(
        _family(BRACE_FAMILY),
        lambda s: (
            s.h == s.b
            and length / min(s.rx, s.ry) <= limit
            and _compression(s, length, fy, e) >= force
            and ok(s)
        ),
    )
    if found is None:
        found = max(_family(BRACE_FAMILY), key=lambda s: s.A)
    return found


def generate_steel_building(
    spec: BuildingSpec | dict[str, Any], settings: Any = None
) -> dict[str, Any]:
    """The parts of a steel moment or braced frame building (see the module notes); the result
    has the keys of :func:`saengine.library.generator.generate_building` and ``bimMembers``
    (the braces, 06 BIM additions)."""
    s = spec if isinstance(spec, BuildingSpec) else BuildingSpec.model_validate(spec)
    scope: Any = contextlib.nullcontext()
    if s.codePack:
        from saengine.codes import registry

        scope = code_context.using(registry.load(s.codePack, code_context.project_root()))
    with scope:
        return _generate(s, settings)


def _generate(s: BuildingSpec, settings: Any) -> dict[str, Any]:
    from saengine.fem import loads as fl
    from saengine.library.settings import derived

    notes: list[str] = []
    braced = s.system == "steelBracedFrame"
    moment = not braced

    # ── materials ──
    materials = default_material_library()
    concrete = materials.get(s.concrete)
    if concrete is None or concrete.category != Category.CONCRETE or concrete.concrete is None:
        raise ValueError(f"'{s.concrete}' is not a concrete of the default materials")
    rebar = materials.get(s.rebar)
    if rebar is None or rebar.category != Category.REBAR or rebar.steel is None:
        raise ValueError(f"'{s.rebar}' is not a rebar of the default materials")
    steel = materials.get(s.steel)
    if steel is None or steel.category != Category.STEEL or steel.steel is None:
        raise ValueError(f"'{s.steel}' is not a structural steel of the default materials")
    materials.defaults = MaterialDefaults(concrete=s.concrete, rebar=s.rebar)
    fy, e = float(steel.steel.fy), float(steel.mechanical.E or 200_000.0)
    fy_bar = float(rebar.steel.fy)
    gamma_c = (concrete.mechanical.density or 2400.0) * G / 1000.0

    # ── settings and the system ──
    base_json, patch, sdc, zone = settings_patch(s, settings, notes)
    stories = s.story_list()
    n = len(stories)
    height_m = sum(st.height for st in stories) / 1000
    system_id, row = choose_system(s.system, sdc, height_m)
    patch["seismic"] = {"system": system_id}
    final = ProjectSettings.model_validate(_deep_merge(base_json, patch))
    notes.append(
        f"Seismic Design Category {sdc or '-'} (zone {zone or '-'}, site class "
        f"{final.site.siteClass}, occupancy category {final.occupancy.category}); system "
        f"{_system_name(system_id, row)} (row {getattr(row, 'row', '-')} of the code pack's "
        "systems: the first of the kind's candidates the category and the height permit)."
    )
    notes.append("PRELIMINARY sizes: the analysis and Design mode check and size every member.")
    floor_load = next(a for a in final.areaLoads if a.id == final.floorLoad)
    roof_load = next(a for a in final.areaLoads if a.id == final.roofLoad)

    # ── grids and storeys ──
    xs = [0.0]
    for d in s.gridsX:
        xs.append(xs[-1] + d)
    ys = [0.0]
    for d in s.gridsY:
        ys.append(ys[-1] + d)
    xl = [letters(i) for i in range(len(xs))]
    yl = [str(j + 1) for j in range(len(ys))]
    nx, ny = len(xs), len(ys)
    levels = [s.baseElevation]
    for st in stories:
        levels.append(levels[-1] + st.height)
    story_ids = ["BASE"] + [f"L{k}" for k in range(1, n + 1)]

    # ── slabs: the two-way rule with stiff supports (the beams) ──
    slab_of: dict[tuple[int, int], float] = {}
    for i in range(nx - 1):
        for j in range(ny - 1):
            lx, ly = xs[i + 1] - xs[i], ys[j + 1] - ys[j]
            ln, short = max(lx, ly), max(min(lx, ly), 1.0)
            h = max(ln * (0.8 + fy_bar / 1400) / (36 + 9 * ln / short), 90.0, s.minSlab)
            slab_of[(i, j)] = ceil_to(h, 5)
    t_slab = max(slab_of.values())

    part_case = partition_case(final)

    def dead(load: Any) -> float:
        """Dead load of a floor [kN/m²]: slab, superimposed dead (with the partitions where the
        pack makes them dead), the framing allowance."""
        return t_slab / 1000 * gamma_c + load.superimposed(part_case) + FRAMING_WEIGHT

    q_dead = {k: dead(roof_load if k == n else floor_load) for k in range(1, n + 1)}
    # Live: the floor live load with the partitions where the pack makes them live.
    q_live = {
        k: (roof_load if k == n else floor_load).floor_live(part_case) for k in range(1, n + 1)
    }

    # The width-thickness limits of the system's members (the steel seismic provisions).
    beam_ok, beam_level = ductility_rule(system_id, "beam", fy, e, steel)
    column_ok, column_level = ductility_rule(system_id, "column", fy, e, steel)
    brace_ok, brace_level = ductility_rule(system_id, "brace", fy, e, steel)
    levels_note = ", ".join(
        f"{what} {level} ductile"
        for what, level in (
            ("beams", beam_level),
            ("columns", column_level),
            ("braces", brace_level),
        )
        if level and (what != "braces" or braced)
    )
    if levels_note:
        notes.append(
            f"Sections chosen within the width-thickness limits of the system's members "
            f"({levels_note}; the code pack's steel seismic provisions, webs at Ca = 0)."
        )

    # ── beams ──
    def tributary(index: int, spacings: list[float]) -> float:
        left = spacings[index - 1] / 2 if index > 0 else 0.0
        right = spacings[index] / 2 if index < len(spacings) else 0.0
        return left + right

    beam_size: dict[tuple[tuple[int, int], tuple[int, int]], Any] = {}
    beam_need: dict[Any, dict[str, float]] = {}
    for j in range(ny):
        width = tributary(j, s.gridsY) / 1000
        for i in range(nx - 1):
            span = xs[i + 1] - xs[i]
            section, need = _beam_section(
                span,
                max(q_dead.values()) * width,
                max(q_live.values()) * width,
                fy,
                e,
                moment,
                beam_ok,
            )
            beam_size[((i, j), (i + 1, j))] = section
            beam_need[section.name] = need
    for i in range(nx):
        width = tributary(i, s.gridsX) / 1000
        for j in range(ny - 1):
            span = ys[j + 1] - ys[j]
            section, need = _beam_section(
                span,
                max(q_dead.values()) * width,
                max(q_live.values()) * width,
                fy,
                e,
                moment,
                beam_ok,
            )
            beam_size[((i, j), (i, j + 1))] = section
            beam_need[section.name] = need

    # ── columns: storey groups, the axial force of the floors above ──
    count = math.ceil(n / s.columnGroupStoreys)
    sizes = [n // count + (1 if k < n % count else 0) for k in range(count)]
    groups: list[list[int]] = []
    start = 1
    for size in sizes:
        groups.append(list(range(start, start + size)))
        start += size

    def position(i: int, j: int) -> str:
        edge_x, edge_y = i in (0, nx - 1), j in (0, ny - 1)
        return "corner" if edge_x and edge_y else "edge" if edge_x or edge_y else "interior"

    def area(i: int, j: int) -> float:
        return tributary(i, s.gridsX) * tributary(j, s.gridsY) / 1e6  # m²

    service: dict[tuple[int, int], float] = {}
    col_size: dict[tuple[int, int, int], Any] = {}
    col_notes: list[str] = []
    for g, members in enumerate(groups):
        bottom = members[0]
        for kind in POSITION_FACTOR:
            pu = 0.0
            z_beam = 0.0
            for i in range(nx):
                for j in range(ny):
                    if position(i, j) != kind:
                        continue
                    a = area(i, j)
                    p = sum((1.2 * q_dead[k] + 1.6 * q_live[k]) * a for k in range(bottom, n + 1))
                    factor = POSITION_FACTOR[kind] if moment else 1.0
                    pu = max(pu, factor * p * 1e3)
                    for edge, section in beam_size.items():
                        if (i, j) in edge:
                            z_beam = max(z_beam, section.Zx)
                    if g == 0:
                        service[(i, j)] = sum((q_dead[k] + q_live[k]) * a for k in range(1, n + 1))
            if pu <= 0:
                continue
            section, why = _column_section(pu, fy, z_beam, moment, column_ok)
            if why:
                col_notes.append(why)
            for i in range(nx):
                for j in range(ny):
                    if position(i, j) == kind:
                        for k in members:
                            col_size[(i, j, k)] = section
    # Never smaller above than below (by area).
    for i in range(nx):
        for j in range(ny):
            for k in range(n - 1, 0, -1):
                if col_size[(i, j, k + 1)].A > col_size[(i, j, k)].A:
                    col_size[(i, j, k)] = col_size[(i, j, k + 1)]

    # ── braces: X braces in one bay of each perimeter line ──
    brace_bays: list[tuple[str, int, int]] = []  # (axis, line index, bay index)
    brace_size: dict[int, Any] = {}
    brace_note = ""
    if braced:
        mid_x, mid_y = (nx - 2) // 2, (ny - 2) // 2
        for j in sorted({0, ny - 1}):
            brace_bays.append(("x", j, mid_x))
        for i in sorted({0, nx - 1}):
            brace_bays.append(("y", i, mid_y))
        values = derived(final)
        weights = []
        plan_area = (xs[-1] - xs[0]) * (ys[-1] - ys[0]) / 1e6
        rule = seismic_weight_rule(final)
        for k in range(1, n + 1):
            load = roof_load if k == n else floor_load
            live = (
                0.0
                if k == n
                else rule.weight(load.live, load.partitions, load.use)
                - (load.partitions if part_case == "SD" else 0.0)
            )
            weights.append((q_dead[k] + live) * plan_area)
        rel = [(lv - levels[0]) / 1000 for lv in levels[1:]]
        ta = fl.approximate_period(rel[-1], system_id, (xs[-1] - xs[0]) / 1000)
        base = 0.0
        how = "no seismic or wind values"
        if values.get("Z"):
            sa = fl.elf_coefficient(
                ta, final.site.siteClass, values["Z"], values["seismicImportance"], values["R"]
            )
            base = sa * sum(weights)
            how = f"seismic Cs = {sa:.3f} at Ta = {ta:.2f} s, W = {sum(weights):.0f} kN"
        shares = fl.vertical_distribution(list(zip(rel, weights, strict=True)), 1.0, ta)
        storey_shear = {k: base * sum(shares[k - 1 :]) for k in range(1, n + 1)}
        if values.get("windSpeed"):
            args = (values["windSpeed"], final.wind.exposure, values["windImportance"])
            for wx, wy in ((ys[-1] - ys[0], xs[-1] - xs[0]), (xs[-1] - xs[0], ys[-1] - ys[0])):
                forces = fl.wind_level_forces(rel, wx / 1000, wy / 1000, *args)
                for k in range(1, n + 1):
                    v = sum(forces[k - 1 :])
                    if v > storey_shear[k]:
                        storey_shear[k] = v
                        how = how + "; wind governs some storeys"
        limit = float(_brace_limit())
        lines = 2  # perimeter lines per direction
        for k in range(1, n + 1):
            worst = None
            for axis, _line, bay in brace_bays:
                spans = s.gridsX if axis == "x" else s.gridsY
                bay_w = spans[bay]
                diag = math.hypot(bay_w, stories[k - 1].height)
                force = storey_shear[k] * 1e3 / (lines * 2 * bay_w / diag)
                section = _brace_section(force, diag, fy, e, limit, brace_ok)
                if worst is None or section.A > worst.A:
                    worst = section
            brace_size[k] = worst
        brace_note = (
            f"Braces: X braces of {BRACE_FAMILY} sections in the middle bay of each perimeter "
            "frame line in every storey (06 BIM inclined members); each diagonal sized for the "
            "storey shear shared by the two X braces of the two lines of its direction (one in "
            "tension and one in compression: 50 %), φc Pn of the full diagonal (K = 1) at "
            f"least that, Lc/r at most {limit:g}; storey shear from the larger of the equivalent "
            f"static seismic force and the wind ({how}). The braced bays' beams and columns "
            "take the brace forces: Design mode checks them."
        )

    # ── object types ──
    objects: list[dict[str, Any]] = []
    type_ids: set[str] = set()

    def add(data: dict[str, Any]) -> str:
        if data["id"] not in type_ids:
            type_ids.add(data["id"])
            objects.append(data)
        return data["id"]

    def tid(prefix: str, section: Any) -> str:
        return f"{prefix}-{section.name.replace(' ', '')}"

    def steel_type(kind: str, prefix: str, section: Any, title: str) -> str:
        return add(
            _template(
                kind,
                id=tid(prefix, section),
                name=f"{title} {section.name}",
                material=s.steel,
                profile=tbl.profile_of(section),
            )
        )

    def slab_type(t: float) -> str:
        return add(
            _template(
                "Slab",
                id=f"S{t:g}",
                name=f"Slab {t:g}",
                material=s.concrete,
                thickness=t,
                system="twoWay",
            )
        )

    # ── the floor plan ──
    def gp(i: int, j: int) -> dict[str, str]:
        return {"x": xl[i], "y": yl[j]}

    def name(i: int, j: int) -> str:
        return f"{xl[i]}{yl[j]}"

    columns, beams, slabs = [], [], []
    for k in range(1, n + 1):
        sid = story_ids[k]
        for i in range(nx):
            for j in range(ny):
                columns.append(
                    {
                        "id": f"C-{name(i, j)}-{sid}",
                        "type": steel_type("Column", "SC", col_size[(i, j, k)], "Steel column"),
                        "at": gp(i, j),
                        "base": story_ids[k - 1],
                        "top": sid,
                    }
                )
        for (a, b), section in beam_size.items():
            beams.append(
                {
                    "id": f"B-{name(*a)}-{name(*b)}-{sid}",
                    "type": steel_type("Beam", "SB", section, "Steel beam"),
                    "story": sid,
                    "start": gp(*a),
                    "end": gp(*b),
                }
            )
        for (i, j), t in sorted(slab_of.items()):
            slabs.append(
                {
                    "id": f"S-{name(i, j)}-{sid}",
                    "type": slab_type(t),
                    "story": sid,
                    "boundary": [gp(i, j), gp(i + 1, j), gp(i + 1, j + 1), gp(i, j + 1)],
                }
            )
    members: list[dict[str, Any]] = []
    for k in range(1, n + 1) if braced else ():
        brace_type = steel_type("Brace", "SBR", brace_size[k], "Steel brace")
        z0, z1 = levels[k - 1], levels[k]
        for axis, line, bay in brace_bays:
            if axis == "x":
                p0, p1 = (xs[bay], ys[line]), (xs[bay + 1], ys[line])
                label = f"{xl[bay]}{yl[line]}-{xl[bay + 1]}{yl[line]}"
            else:
                p0, p1 = (xs[line], ys[bay]), (xs[line], ys[bay + 1])
                label = f"{xl[line]}{yl[bay]}-{xl[line]}{yl[bay + 1]}"
            for tag, (a, b) in (("A", (p0, p1)), ("B", (p1, p0))):
                members.append(
                    {
                        "id": f"BR-{label}-{story_ids[k]}-{tag}",
                        "type": brace_type,
                        "x1": a[0],
                        "y1": a[1],
                        "z1": z0,
                        "x2": b[0],
                        "y2": b[1],
                        "z2": z1,
                    }
                )
    similar = {}
    if s.typical and n >= 3:
        for k in range(3, n + 1):
            same_columns = all(
                col_size[(i, j, k)].name == col_size[(i, j, 2)].name
                for i in range(nx)
                for j in range(ny)
            )
            same_braces = not braced or brace_size[k].name == brace_size[2].name
            if same_columns and same_braces:
                similar[k] = 2
    plan = FloorPlan.model_validate(
        {
            "grids": {
                "x": [{"label": xl[i], "position": xs[i]} for i in range(nx)],
                "y": [{"label": yl[j], "position": ys[j]} for j in range(ny)],
            },
            "stories": [
                {
                    "id": story_ids[k],
                    "name": "Base" if k == 0 else stories[k - 1].name,
                    "elevation": levels[k],
                    **({"similarTo": story_ids[similar[k]]} if k in similar else {}),
                }
                for k in range(n + 1)
            ],
            "columns": columns,
            "beams": beams,
            "walls": [],
            "slabs": slabs,
        }
    )
    library = ObjectLibrary.model_validate({"objects": objects})
    problems = [*library.check_materials(materials), *plan.check_objects(library)]
    if problems:  # pragma: no cover - a generator bug
        raise ValueError("; ".join(problems))

    # ── 09 Substructure: isolated footings ──
    qa = s.allowableBearing or final.foundation.allowableBearing or DEFAULT_BEARING
    foundations: list[dict[str, Any]] = []
    if s.footing == "isolated":
        for i in range(nx):
            for j in range(ny):
                p = service[(i, j)]
                b = max(1000.0, ceil_to(math.sqrt(1.1 * p / qa * 1e6), 100))
                foundations.append(
                    {
                        "id": f"F-{name(i, j)}",
                        "type": "isolated",
                        "columns": [f"C-{name(i, j)}-L1"],
                        "center": [xs[i], ys[j]],
                        "length": b,
                        "width": b,
                        "thickness": max(450.0, ceil_to(b / 4, 50)),
                        "material": s.concrete,
                        "note": f"Preliminary: service load {p:.0f} kN, qa {qa:g} kPa.",
                    }
                )
        notes.append(
            "Isolated footings under every column: side from 1.1 × the gravity service load / "
            f"qa (qa = {qa:g} kPa) rounded up to 100 mm, at least 1000 mm; thickness max(450 "
            "mm, side/4); the base plates and anchor rods are designed in Part 9 and Design "
            "mode (the column bases are fixed in the analysis)."
        )
    elif s.footing == "mat":
        notes.append("A mat is not generated under a steel frame: add it in 09 Substructure.")
    substructure = Substructure.model_validate({"foundations": foundations})

    beam_rule = (
        f"Beams ({BEAM_FAMILY}): the lightest section with Zx >= Mu / (0.9 Fy), Mu = (1.2 D + "
        f"1.6 L) l²/{'10' if moment else '8'}"
        + (f" × {LATERAL_ALLOWANCE:g} (room for the lateral moments)" if moment else "")
        + f", Ix keeping the live load deflection within l/{DEFLECTION_DIVISOR:g} and depth "
        f"at least l/{DEPTH_DIVISOR:g}; tributary width half the bays on each side; D the slab "
        f"({t_slab:g} mm), the superimposed dead load and {FRAMING_WEIGHT:g} kN/m² of framing."
    )
    column_rule = (
        f"Columns ({COLUMN_FAMILY}): the lightest section "
        f"with A >= Pu / ({COLUMN_STRESS_SHARE:g} Fy), Pu = 1.2 D + 1.6 L of the tributary area "
        "of every floor above"
        + (
            f" × the position factor (interior 1.0, edge 1.25, corner 1.5) and Zx at least "
            f"{STRONG_COLUMN:g} × the framing beams' Zx (strong column, SAEngine rule of thumb; "
            "the columns stand in their default orientation, so the frames of one direction "
            "bend them about the weak axis: Design mode checks the moment ratio of every joint, "
            "turn columns in 05 Floor Plan where it fails)"
            if moment
            else ""
        )
        + f", by storey groups of {s.columnGroupStoreys}, never smaller above than below."
    )
    notes += [beam_rule, column_rule, *sorted(set(col_notes))]
    if brace_note:
        notes.append(brace_note)
    notes.append(
        "Slabs: two-way RC slabs on the steel beams (no composite action assumed), ln (0.8 + "
        "fy/1400) / (36 + 9 β) >= 90 mm with the beams as stiff supports, at least the least "
        "slab. Connections: the beams are rigidly connected (moment frames) or as the analysis "
        "model's defaults; set the connection types in 04 Objects."
    )
    summary = {
        "sdc": sdc,
        "warnings": [],
        "suggestCoreWalls": False,
        "columnReasons": {},
        "zone": zone,
        "system": system_id,
        "counts": {
            "columns": len(columns),
            "beams": len(beams),
            "walls": 0,
            "slabs": len(slabs),
            "foundations": len(foundations),
            "braces": len(members),
        },
        "columnTypes": {},
        "beamTypes": sorted({o["id"] for o in objects if o["kind"] == "beam"}),
        "wallTypes": [],
        "slabTypes": sorted({o["id"] for o in objects if o["kind"] == "slab"}),
        "families": [[story_ids[2], *(story_ids[k] for k in sorted(similar))]] if similar else [],
        "lateralSizing": None,
        "stiffness": None,
        "baseServiceLoads": {name(i, j): round(p, 1) for (i, j), p in service.items()},
        "steel": {
            "kind": s.system,
            "material": s.steel,
            "columnTypes": sorted({o["id"] for o in objects if o["kind"] == "column"}),
            "braceTypes": sorted({o["id"] for o in objects if o["kind"] == "brace"}),
        },
    }
    dump = {"mode": "json", "by_alias": True, "exclude_none": True}
    return {
        "materials": materials.model_dump(**dump),
        "objects": library.model_dump(**dump),
        "floorPlan": plan.model_dump(**dump),
        "substructure": substructure.model_dump(**dump),
        "settings": final.model_dump(**dump),
        "settingsPatch": patch,
        "notes": notes,
        "summary": summary,
        "bimMembers": members,
    }


def _brace_limit() -> float:
    """Lc/r of the braces: the pack's SCBF limit when it gives one, else the generator's."""
    try:
        table = code_context.table("steelSeismic")
        scbf = (getattr(table, "concentric", None) or {}).get("scbf")
        found = getattr(scbf, "slendernessMax", None) if scbf is not None else None
        return float(found) if found else BRACE_SLENDERNESS
    except Exception:  # noqa: BLE001 - no steel seismic table
        return BRACE_SLENDERNESS


def _system_name(system_id: str, row: Any) -> str:
    found = code_data.STRUCTURAL_SYSTEMS.get(system_id)
    return getattr(row, "name", None) or (found.name if found is not None else system_id)


__all__ = ["CANDIDATES", "choose_system", "generate_steel_building"]
