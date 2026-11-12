"""Column shortening of a building built storey by storey, with creep and shrinkage (B25, P2).

The code pack asks for the long-term properties of the materials in the analysis, for the
additional stresses of phased construction and for creep and shrinkage (the default pack's Part 6 Sec
1.2.7, 1.2.16, 1.6.6(h),(j),(l); the clauses come from the pack's ``concreteTime`` sources).
This module works them out for the concrete columns (and, alpha 9 P2, the walls and cores)
from a finished run:

1. **Column lines.** The vertical frame elements of the analysis model, grouped by plan
   position; each storey of a line is the elements between two levels. Its section gives the
   area, the modulus at 28 days and (from the area and the second moments: a rectangle or a
   circle) the perimeter, so the effective thickness 2A/u. **Wall lines** (when the settings
   take walls): the vertical shells of one wall (``W1``, ``W1#2`` ...), per storey band; its
   area the shells' area over the band's height times the plate thickness, its perimeter both
   faces, its axial force the vertical nodal forces of the band's shells at its bottom and top.
2. **Loads in time.** The construction sequence's staged dead load ``D`` (when the settings run
   it): stage k's increment of each storey's axial force arrives when stage k is cast,
   one cycle after the storey of stage k is cast (``(k + 1) × cycle`` days after the start,
   or the level's casting day of the settings plus a cycle), on concrete cast at ``(stage
   built) × cycle``. A storey's age at loading is therefore at least one cycle. Without the
   staged case the dead load arrives at once when the frame is complete. The superimposed dead
   load ``SD`` and the sustained share of the live load ``L`` arrive ``superimposedAfterDays``
   after completion (the live load at ``liveAfterDays`` when given).
3. **Strains.** By the analysis method the pack (or the project) chooses:

   - ``superposition`` (B25): for each load increment the stress on the transformed section
     ``ΔN / (A (1 + (n - 1) ρ))``, ``n = Es / Et``, its elastic strain ``stress / Et`` and creep
     strain ``stress / Eref × φ(t, tk)`` (:mod:`saengine.fem.concrete_time`; Eref the modulus
     the model's φ is relative to), summed (superposition of the creep of each increment);
     plus the shrinkage of the reinforced section (the pack's ε / (1 + K ρ) where it gives K)
     from the end of curing. The steel's restraint of the creep itself is ignored (more
     shortening: on the safe side for the shortening);
   - ``ageAdjusted`` (P2): each increment on the composite section, ``ε0 = ΔN / (Ac Et + As
     Es)``, its creep ``ε0 φ' Ac Ē / (Ac Ē + As Es)`` with ``φ' = φ Et / Eref`` and the
     age-adjusted effective modulus ``Ē = Et / (1 + χ φ')``; the free shrinkage restrained the
     same way (Ē from the start of drying).
4. **Shortening.** Each storey shortens by its strain times its height. At a level, the total
   is the sum over the storeys below; what matters for the floors is the shortening **after the
   level was cast** (the floor is cast level, so what happened before it is made up): the sum
   over the storeys below of their shortening after that time. That is also the **pre-set**
   (camber) to cast the level by: its elevation correction at casting.
5. **Differential shortening.** For each beam whose two ends sit on column (or wall) lines at
   the same level, the difference of the two ends' shortening after casting, at the end of the
   service life, and the indicative end moment ``6 E I Δ / L²`` of a beam fixed at both ends
   (with the beam section's E and Iy: no relief by the beam's own creep, so on the high side);
   and for each line and its nearest neighbours (a column and the nearest wall) the largest
   difference over the levels.
6. **The forces case CS** (P2, :func:`add_creep_shrinkage_case`): each storey's creep and
   shrinkage strain after its floor is cast, per construction stage, imposed on the model as
   equivalent fixed-end loads (the textbook method of :mod:`saengine.fem.thermal`) in a staged
   analysis: the strain increment of each interval acts on the structure built by then. The
   forces are relaxed by the age-adjusted effective modulus, ``1 / (1 + χ φ̄)``, with φ̄ the
   mean creep coefficient of the vertical members at the end. The run then reports the
   induced beam and slab forces, and the redistribution between columns and walls.

Values in the model's units: m, N; times in days.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem import concrete_time

#: Plan tolerance [m] of a vertical element and of a column line.
PLAN_TOLERANCE = 1e-3
#: Level tolerance [m].
LEVEL_TOLERANCE = 1e-3
#: Rows of the differential table (the largest first).
DIFFERENTIAL_ROWS = 40
#: Times (days after completion) of the history chart besides the key times.
HISTORY_DAYS = (0.0, 30.0, 90.0, 182.5, 365.0, 730.0, 1825.0, 3650.0, 7300.0, 10950.0)
#: The creep and shrinkage forces case (alpha 9 P2).
CASE = "CS"
CASE_TITLE = "Creep and shrinkage"
#: Rows of the induced beam moments of the case CS.
INDUCED_ROWS = 15


@dataclass
class Load:
    """An axial load increment [N, compression positive] arriving at ``time`` [days]."""

    time: float
    force: float


@dataclass
class Storey:
    """One storey of a column (or wall) line."""

    elements: list[int]
    name: str
    bottom: float  # z [m]
    top: float
    area: float  # m²
    perimeter: float  # m
    modulus: float  # Pa, 28 days
    cast: float  # day
    loads: list[Load] = field(default_factory=list)
    steel: float = 0.01  # ρ
    strength: float = 28.0  # f'c / fck [MPa], for the models in time
    stage: int = 0
    level: int = 0  # index of the level at its top

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def thickness(self) -> float:
        """Effective thickness [mm]."""
        return concrete_time.effective_thickness(self.area * 1e6, self.perimeter * 1e3)


@dataclass
class Line:
    """A column or wall line: its storeys bottom up."""

    label: str
    x: float
    y: float
    storeys: list[Storey]
    kind: str = "column"
    points: list[tuple[float, float]] = field(default_factory=list)


@dataclass(frozen=True)
class Model:
    """How the strains are worked out (:func:`model_of`)."""

    method: str  # superposition | ageAdjusted
    legacy: bool  # the B25 arithmetic: tabulated creep and shrinkage by superposition
    basis: str  # loading | 28
    tangent: float
    chi: float
    chi_given: bool
    reinforced: bool


def model_of(options: Any) -> Model:
    """The models and the analysis method in force (the project's method over the pack's)."""
    method = concrete_time.analysis_method(getattr(options, "method", None))
    basis, tangent = concrete_time.creep_basis()
    chi, given = concrete_time.ageing()
    legacy = (
        method == "superposition"
        and concrete_time.creep_method() == "tabulatedCoefficient"
        and concrete_time.shrinkage_method() == "tabulatedStrain"
    )
    return Model(
        method, legacy, basis, tangent, chi, given, concrete_time.has_reinforced_shrinkage()
    )


def section_perimeter(section: dict[str, Any]) -> float:
    """The perimeter [m] of a solid section from A, Iy, Iz: a circle when Iy = Iz = A²/4π,
    else the rectangle with those properties (b h = A, b h³ / 12 = I)."""
    area = float(section.get("A") or 0.0)
    iy, iz = float(section.get("Iy") or 0.0), float(section.get("Iz") or 0.0)
    if area <= 0:
        return 0.0
    circle = area**2 / (4 * math.pi)
    if iy > 0 and math.isclose(iy, circle, rel_tol=0.02) and math.isclose(iz, circle, rel_tol=0.02):
        return math.pi * math.sqrt(4 * area / math.pi)
    if iy > 0 and iz > 0:
        h1, h2 = math.sqrt(12 * iy / area), math.sqrt(12 * iz / area)
        if math.isclose(h1 * h2, area, rel_tol=0.05):
            return 2 * (h1 + h2)
    return 4 * math.sqrt(area)  # a square of the same area


def _vertical(coords: dict[int, np.ndarray], element: dict[str, Any]) -> bool:
    nodes = element.get("nodes") or []
    if len(nodes) != 2 or "section_id" not in element:
        return False
    a, b = coords[nodes[0]], coords[nodes[1]]
    return (
        abs(a[0] - b[0]) < PLAN_TOLERANCE
        and abs(a[1] - b[1]) < PLAN_TOLERANCE
        and abs(a[2] - b[2]) > 10 * LEVEL_TOLERANCE
    )


def _vertical_shell(coords: dict[int, np.ndarray], element: dict[str, Any]) -> bool:
    """A wall shell: a plate (3 or 4 nodes) standing upright, not an embedded one."""
    nodes = element.get("nodes") or []
    if element.get("type") != "Shell" or len(nodes) not in (3, 4):
        return False
    if str(element.get("name", "")).split("#")[0].endswith("/embed"):
        return False
    points = [coords[n] for n in nodes]
    heights = [p[2] for p in points]
    if max(heights) - min(heights) < 10 * LEVEL_TOLERANCE:
        return False
    from saengine.fem.thermal import shell_normal

    return abs(float(shell_normal(points)[2])) < 0.1


def _compression(rows: Any, step: int, add: np.ndarray | None = None) -> float:
    """Mid-length axial compression [N] of an element's end forces at ``step`` (``add``: the
    fixed-end forces of an imposed-strain case)."""
    if rows is None or not len(rows):
        return 0.0
    row = np.asarray(rows[min(step, len(rows) - 1)], dtype=float)
    if row.size < 12:
        return 0.0
    if add is not None:
        row = row[:12] + add[:12]
    return float((row[0] - row[6]) / 2.0)


def _shell_area(points: list[np.ndarray]) -> float:
    if len(points) == 4:
        return float(np.linalg.norm(np.cross(points[2] - points[0], points[3] - points[1]))) / 2
    return float(np.linalg.norm(np.cross(points[1] - points[0], points[2] - points[0]))) / 2


def _wall_compression(
    results: Any,
    shells: list[dict[str, Any]],
    coords: dict[int, np.ndarray],
    bottom: float,
    top: float,
    step: int,
    add: dict[int, np.ndarray] | None = None,
) -> float:
    """Mean axial compression [N] of a wall storey from its shells' nodal (resisting) forces:
    the vertical forces at its bottom nodes (+) and at its top nodes (-), halved."""
    if results is None:
        return 0.0
    below = above = 0.0
    for shell in shells:
        nodes = shell["nodes"]
        rows = results.element_forces.get(shell["id"])
        if rows is None or not len(rows):
            continue
        row = np.asarray(rows[min(step, len(rows) - 1)], dtype=float)
        if row.size != 6 * len(nodes):
            continue
        forces = row.reshape(len(nodes), 6)
        if add is not None and shell["id"] in add:
            from saengine.design.wall_forces import stress_nodal_forces

            forces = forces + stress_nodal_forces([coords[n] for n in nodes], add[shell["id"]])
        for k, node in enumerate(nodes):
            z = coords[node][2]
            if abs(z - bottom) < LEVEL_TOLERANCE:
                below += forces[k, 2]
            elif abs(z - top) < LEVEL_TOLERANCE:
                above += forces[k, 2]
    return float((below - above) / 2.0)


def _strain(
    storey: Storey,
    t: float,
    conditions: concrete_time.Conditions,
    options: Any,
    steel_e: float,
    before: bool = False,
    model: Model | None = None,
) -> tuple[float, float, float]:
    """(elastic, creep, shrinkage) strain of ``storey`` at day ``t`` (shortening positive);
    ``before``: without the loads arriving exactly at ``t``."""
    if model is None or model.legacy:
        return _strain_tabulated(storey, t, conditions, options, steel_e, before)
    elastic = creep = 0.0
    thickness, humidity, fck = storey.thickness, conditions.humidity, storey.strength
    rho = storey.steel
    concrete, steel = storey.area * (1.0 - rho), storey.area * rho

    def reference(e_t: float) -> float:
        return e_t if model.basis == "loading" else model.tangent * storey.modulus

    for load in storey.loads:
        if load.time > t or (before and load.time >= t):
            continue
        age = max(load.time - storey.cast, 1.0)
        e_t = storey.modulus * concrete_time.modulus_ratio(age)
        if e_t <= 0:
            continue
        phi = concrete_time.creep_phi(thickness, humidity, age, t - load.time, fck)
        if model.method == "ageAdjusted":
            initial = load.force / (concrete * e_t + steel * steel_e)
            phi_t = phi * e_t / reference(e_t)
            e_bar = e_t / (1.0 + model.chi * phi_t)
            elastic += initial
            creep += initial * phi_t * concrete * e_bar / (concrete * e_bar + steel * steel_e)
        else:
            n = steel_e / e_t
            stress = load.force / (storey.area * (1.0 + (n - 1.0) * rho))
            elastic += stress / e_t
            creep += stress / reference(e_t) * phi
    age = t - storey.cast
    free = concrete_time.free_shrinkage(
        thickness, humidity, age, conditions.curing, fck, conditions.water
    )
    if model.method == "ageAdjusted":
        start = max(conditions.curing, 1.0)
        e_s = storey.modulus * concrete_time.modulus_ratio(start)
        if e_s > 0 and age > start:
            phi_s = concrete_time.creep_phi(thickness, humidity, start, age - start, fck)
            phi_s *= e_s / reference(e_s)
            e_bar = e_s / (1.0 + model.chi * phi_s)
            free *= concrete * e_bar / (concrete * e_bar + steel * steel_e)
        shrinkage = free
    elif model.reinforced:
        shrinkage = concrete_time.reinforced_shrinkage(free, rho, conditions.exposure)
    else:
        shrinkage = free
    return elastic, creep, shrinkage


def _strain_tabulated(
    storey: Storey,
    t: float,
    conditions: concrete_time.Conditions,
    options: Any,
    steel_e: float,
    before: bool = False,
) -> tuple[float, float, float]:
    """The B25 strains: tabulated creep and shrinkage by superposition."""
    elastic = creep = 0.0
    thickness = storey.thickness
    rho = float(storey.steel)
    for load in storey.loads:
        if load.time > t or (before and load.time >= t):
            continue
        age = max(load.time - storey.cast, 1.0)
        e_t = storey.modulus * concrete_time.modulus_ratio(age)
        if e_t <= 0:
            continue
        n = steel_e / e_t
        stress = load.force / (storey.area * (1.0 + (n - 1.0) * rho))
        elastic += stress / e_t
        creep += concrete_time.creep_strain(
            stress, e_t, concrete_time.creep_coefficient(thickness, conditions.humidity, age)
        ) * concrete_time.creep_share(t - load.time)
    drying = t - storey.cast - conditions.curing
    shrinkage = concrete_time.reinforced_shrinkage(
        concrete_time.shrinkage_strain(thickness, conditions.humidity, drying, conditions.water),
        rho,
        conditions.exposure,
    )
    return elastic, creep, shrinkage


def _code(name: str) -> str:
    return str(name).split(":")[0].strip()


@dataclass
class _Context:
    """What :func:`column_shortening` and :func:`add_creep_shrinkage_case` share."""

    conditions: concrete_time.Conditions
    model: Model
    steel_e: float
    coords: dict[int, np.ndarray]
    sections: dict[int, dict[str, Any]]
    zs: list[float]
    names: list[str]
    cycle: float
    staged: bool
    stage_count: int
    stage_times: list[float]
    complete: float
    later: float
    life: float
    end: float
    lines: list[Line]
    walls: dict[str, dict[int, list[dict[str, Any]]]]
    notes: list[str]
    overridden: bool

    def strains(self, storey: Storey, t: float, before: bool = False) -> tuple[float, ...]:
        return _strain(storey, t, self.conditions, None, self.steel_e, before, self.model)

    def inelastic(self, storey: Storey, t: float) -> float:
        """Creep plus shrinkage strain of ``storey`` at ``t``."""
        _, creep, shrinkage = self.strains(storey, t)
        return creep + shrinkage


def _prepare(
    project: dict[str, Any],
    results: dict[str, Any],
    levels: list[dict[str, Any]],
    options: Any,
) -> _Context | dict[str, Any]:
    """The column (and wall) lines with their loads in time, or ``{"available": False}``."""
    try:
        conditions = concrete_time.Conditions.of(options)
        model = model_of(options)
    except concrete_time.NotCovered as error:
        return {"available": False, "reason": str(error)}
    from saengine.codes import context as code_context

    steel_e = float(code_context.current().table("materials").steelE) * 1e6  # Pa
    notes: list[str] = []
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    sections = {s["id"]: s for s in project.get("sections", [])}
    zs = [float(lv["z"]) for lv in levels]
    names = [str(lv["name"]) for lv in levels]
    if len(zs) < 2:
        return {"available": False, "reason": "the model has no storeys"}
    cycle = float(options.cycleDays)
    # Alpha 9 P2: the casting days the settings give per level (else the floor cycle's).
    cast_given: dict[int, float] = {}
    for row in getattr(options, "castDays", None) or []:
        if str(row.level) in names:
            cast_given[names.index(str(row.level))] = float(row.day)
        else:
            notes.append(f"casting day of '{row.level}': no such level, the floor cycle is used")

    def cast_day(level: int) -> float:
        """The day the storey below level ``level`` (1 = the first storey) is cast."""
        return cast_given[level] if level in cast_given else (level - 1) * cycle

    # The staged dead load: element -> stage built; the results' rows per stage.
    dead = results.get("D")
    analyses = {_code(a.get("name", "")): a for a in project.get("analyses", [])}
    staged = analyses.get("D", {}).get("type") == "Staged" and dead is not None
    built_in: dict[int, int] = {}
    stage_count = 0
    if staged:
        stages = analyses["D"].get("stages") or []
        stage_count = len(stages)
        for k, stage in enumerate(stages):
            for element_id in stage.get("element_ids", []):
                built_in[int(element_id)] = k
    else:
        notes.append(
            "the construction sequence is off: the dead load is applied at once when the frame "
            "is complete (each storey cast one cycle after the one below)"
        )

    def stage_time(k: int) -> float:
        """When stage k's loads arrive: one cycle after its storey is cast."""
        return cast_given[k + 1] + cycle if k + 1 in cast_given else (k + 1) * cycle

    def level_of(z: float) -> int:
        return int(np.argmin([abs(z - v) for v in zs]))

    # ── column lines ──
    found: dict[tuple[int, int], dict[int, list[dict[str, Any]]]] = {}
    for element in project.get("elements", []):
        if not _vertical(coords, element):
            continue
        section = sections.get(element["section_id"]) or {}
        if not section.get("A") or not section.get("E"):
            continue
        a, b = (coords[n] for n in element["nodes"])
        key = (round(a[0] / PLAN_TOLERANCE), round(a[1] / PLAN_TOLERANCE))
        top = level_of(max(a[2], b[2]))
        if top == 0:
            continue
        found.setdefault(key, {}).setdefault(top, []).append(element)
    # ── wall lines (alpha 9 P2) ──
    walls: dict[str, dict[int, list[dict[str, Any]]]] = {}
    if getattr(options, "walls", False):
        for element in project.get("elements", []):
            if not _vertical_shell(coords, element):
                continue
            section = sections.get(element.get("section_id")) or {}
            if not section.get("E") or not section.get("h"):
                continue
            middle = float(np.mean([coords[n][2] for n in element["nodes"]]))
            top = next((k for k in range(1, len(zs)) if zs[k] >= middle - LEVEL_TOLERANCE), 0)
            if top == 0:
                continue
            name = str(element.get("name", element["id"])).split("#")[0]
            walls.setdefault(name, {}).setdefault(top, []).append(element)
    if not found and not walls:
        return {"available": False, "reason": "the model has no columns between its levels"}
    stage_times = [stage_time(k) for k in range(stage_count)]
    if staged:
        complete = (
            cast_given[stage_count] + cycle if stage_count in cast_given else stage_count * cycle
        )
    else:
        last = len(zs) - 1
        complete = cast_given[last] + cycle if last in cast_given else last * cycle
    later = complete + float(options.superimposedAfterDays)
    live_after = getattr(options, "liveAfterDays", None)
    live_at = None if live_after is None else complete + float(live_after)

    def forces(code: str, element_id: int, step: int = -1) -> float:
        result = results.get(code)
        if result is None:
            return 0.0
        return _compression(result.element_forces.get(element_id), step)

    def assign(storey: Storey, mean: Any) -> None:
        """The storey's loads in time from ``mean(code, step)``, its axial force per case."""
        if staged:
            previous = 0.0
            for k in range(stage_count):
                now = mean("D", k)
                if abs(now - previous) > 1e-9:
                    storey.loads.append(Load(stage_times[k], now - previous))
                previous = now
        elif dead is not None:
            storey.loads.append(Load(complete, mean("D")))
        if live_at is None:
            sustained = mean("SD") + float(options.sustainedLive) * mean("L")
            if abs(sustained) > 1e-9:
                storey.loads.append(Load(later, sustained))
        else:
            finishes = mean("SD")
            if abs(finishes) > 1e-9:
                storey.loads.append(Load(later, finishes))
            live = float(options.sustainedLive) * mean("L")
            if abs(live) > 1e-9:
                storey.loads.append(Load(live_at, live))
            storey.loads.sort(key=lambda load: load.time)

    given_strength = getattr(options, "strength", None)

    def strength(modulus: float) -> float:
        if model.legacy:
            return 28.0
        if given_strength:
            return float(given_strength)
        return concrete_time.strength_from_modulus(modulus / 1e6)

    lines: list[Line] = []
    for key, by_level in sorted(found.items()):
        storeys: list[Storey] = []
        for top in sorted(by_level):
            elements = by_level[top]
            first = min(elements, key=lambda e: min(coords[n][2] for n in e["nodes"]))
            section = sections[first["section_id"]]
            ids = [int(e["id"]) for e in elements]
            stage = min((built_in.get(i, top - 1) for i in ids), default=top - 1)
            storey = Storey(
                elements=ids,
                name=str(first.get("name", ids[0])).split("#")[0],
                bottom=min(coords[n][2] for e in elements for n in e["nodes"]),
                top=zs[top],
                area=float(section["A"]),
                perimeter=section_perimeter(section),
                modulus=float(section["E"]),
                cast=cast_day(stage + 1) if staged else cast_day(top),
                steel=float(options.steelRatio),
                strength=strength(float(section["E"])),
                stage=stage if staged else top - 1,
                level=top,
            )

            def mean(code: str, step: int = -1, ids: list[int] = ids) -> float:
                return float(np.mean([forces(code, i, step) for i in ids]))

            assign(storey, mean)
            storeys.append(storey)
        x, y = key[0] * PLAN_TOLERANCE, key[1] * PLAN_TOLERANCE
        lines.append(Line(storeys[0].name, x, y, storeys, "column", [(x, y)]))
    for name, by_level in sorted(walls.items()):
        storeys = []
        plan: set[tuple[float, float]] = set()
        for top in sorted(by_level):
            shells = by_level[top]
            points = [coords[n] for e in shells for n in e["nodes"]]
            bottom = min(p[2] for p in points)
            height = max(p[2] for p in points) - bottom
            section = sections[shells[0]["section_id"]]
            thickness = float(section["h"])
            length = sum(_shell_area([coords[n] for n in e["nodes"]]) for e in shells) / height
            ids = [int(e["id"]) for e in shells]
            stage = min((built_in.get(i, top - 1) for i in ids), default=top - 1)
            plan |= {(round(float(p[0]), 3), round(float(p[1]), 3)) for p in points}
            storey = Storey(
                elements=ids,
                name=name,
                bottom=bottom,
                top=zs[top],
                area=thickness * length,
                perimeter=2.0 * (length + thickness),
                modulus=float(section["E"]),
                cast=cast_day(stage + 1) if staged else cast_day(top),
                steel=float(getattr(options, "wallSteelRatio", options.steelRatio)),
                strength=strength(float(section["E"])),
                stage=stage if staged else top - 1,
                level=top,
            )
            top_z = max(p[2] for p in points)

            def wall_mean(
                code: str,
                step: int = -1,
                shells: list[dict[str, Any]] = shells,
                bottom: float = bottom,
                top_z: float = top_z,
            ) -> float:
                return _wall_compression(results.get(code), shells, coords, bottom, top_z, step)

            assign(storey, wall_mean)
            storeys.append(storey)
        xs = [p[0] for p in plan]
        ys = [p[1] for p in plan]
        lines.append(
            Line(name, float(np.mean(xs)), float(np.mean(ys)), storeys, "wall", sorted(plan))
        )

    life = float(options.serviceLifeYears) * 365.0
    final = getattr(options, "finalDays", None)
    if final is not None and float(final) > complete:
        life = float(final) - complete
    elif final is not None:
        notes.append(
            f"the final time ({float(final):g} days) is before the frame is complete "
            f"({complete:g} days): the service life is used"
        )
    if life > concrete_time.final_age():
        notes.append(
            f"the service life is longer than the {concrete_time.final_age() / 365:g} years the "
            "code pack's final creep is for: the final values are used beyond it"
        )
    end = complete + life
    creep_table = concrete_time.required_table().creep
    if creep_table.method == "tabulatedCoefficient" and conditions.humidity < min(
        creep_table.relativeHumidity
    ):
        notes.append(
            "the relative humidity is below the creep table's range: its lowest humidity is used"
        )
    return _Context(
        conditions=conditions,
        model=model,
        steel_e=steel_e,
        coords=coords,
        sections=sections,
        zs=zs,
        names=names,
        cycle=cycle,
        staged=staged,
        stage_count=stage_count,
        stage_times=stage_times,
        complete=complete,
        later=later,
        life=life,
        end=end,
        lines=lines,
        walls=walls,
        notes=notes,
        overridden=bool(cast_given),
    )


def column_shortening(
    project: dict[str, Any],
    results: dict[str, Any],
    levels: list[dict[str, Any]],
    options: Any,
    corrections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The column shortening of a run (see the module's description).

    ``results``: the static results by case code (``D``, ``SD``, ``L``; ``D`` may be the
    staged case; ``CS`` when the forces case ran); ``levels``: ``[{"z", "name"}]`` bottom up;
    ``options``: the settings' ``analysis.timeDependent``; ``corrections``: the imposed-strain
    cases' fixed-end forces (:func:`saengine.fem.thermal.load_corrections`) for the case CS.
    Returns ``{"available", "reason"?, "inputs", "times", "levels", "lines": [{"line", "kind",
    "x", "y", "storeys": [{"storey", "thickness", "coefficient"}], "rows": [{"level", "z",
    "elastic", "creep", "shrinkage", "total", "afterCasting"}]}], "differential": [...],
    "pairs": [...], "camber": [...], "history": {"days", "lines": [{"line", "values"}]},
    "model", "induced"?, "clauses", "notes"}`` (lengths in m, days from the start of
    construction)."""
    ctx = _prepare(project, results, levels, options)
    if isinstance(ctx, dict):
        return ctx
    conditions, notes, cycle = ctx.conditions, ctx.notes, ctx.cycle
    names, zs = ctx.names, ctx.zs
    complete, later, life, end = ctx.complete, ctx.later, ctx.life, ctx.end
    staged = ctx.staged

    def level_of(z: float) -> int:
        return int(np.argmin([abs(z - v) for v in zs]))

    strains = ctx.strains
    out_lines = []
    after_casting: dict[tuple[float, float], dict[int, float]] = {}
    after_line: dict[str, dict[int, float]] = {}
    for line in ctx.lines:
        storeys = line.storeys
        rows = []
        totals = np.zeros(3)
        after = 0.0
        for k, storey in enumerate(storeys):
            e, c, s = (v * storey.height for v in strains(storey, end))
            totals += (e, c, s)
            # The floor at this storey's top is cast with the last load increment of its own
            # stage; what the storeys below shortened before then is built out.
            cast_at = storey.cast + cycle
            after = sum(
                sum(strains(st, end)) * st.height - sum(strains(st, cast_at, True)) * st.height
                for st in storeys[: k + 1]
            )
            level = level_of(storey.top)
            if line.kind == "column":
                after_casting.setdefault((line.x, line.y), {})[level] = after
            after_line.setdefault(line.label, {})[level] = after
            rows.append(
                {
                    "level": names[level],
                    "z": storey.top,
                    "elastic": totals[0],
                    "creep": totals[1],
                    "shrinkage": totals[2],
                    "total": float(totals.sum()),
                    "afterCasting": after,
                }
            )

        def coefficient(st: Storey) -> float:
            age = max(st.loads[0].time - st.cast, 1.0) if st.loads else 28.0
            if ctx.model.legacy:
                return concrete_time.creep_coefficient(st.thickness, conditions.humidity, age)
            start = st.loads[0].time if st.loads else st.cast + age
            return concrete_time.creep_phi(
                st.thickness, conditions.humidity, age, end - start, st.strength
            )

        out_lines.append(
            {
                "line": line.label,
                "kind": line.kind,
                "x": line.x,
                "y": line.y,
                "storeys": [
                    {"storey": st.name, "thickness": st.thickness, "coefficient": coefficient(st)}
                    for st in storeys
                ],
                "rows": rows,
            }
        )

    # ── history of the top of each line ──
    days = sorted({*(complete + d for d in HISTORY_DAYS if d <= life), later, end})
    if ctx.overridden:
        construction = sorted({*ctx.stage_times, complete})
    else:
        construction = [cycle * k for k in range(1, int(complete / cycle) + 1)]
    days = construction + [d for d in days if d > complete]
    history = []
    for line in ctx.lines:
        history.append(
            {
                "line": line.label,
                "values": [
                    sum(sum(strains(st, t)) * st.height for st in line.storeys) for t in days
                ],
            }
        )

    walls_at = {line.label: line for line in ctx.lines if line.kind == "wall"}
    differential = _differential(
        project, ctx.coords, ctx.sections, after_casting, zs, names, walls_at, after_line
    )
    if not staged:
        notes.append("turn the construction sequence on for the staged dead load")
    if ctx.model.legacy:
        notes.append(
            "the steel restrains the elastic strain (transformed section) but not the creep, and "
            "the beams' end moments take no relief from the beams' own creep: on the high side"
        )
    elif ctx.model.method == "ageAdjusted":
        notes.append(
            "the steel restrains the elastic strain, the creep and the shrinkage by the "
            f"age-adjusted effective modulus (χ = {ctx.model.chi:g}"
            + ("" if ctx.model.chi_given else ", SAEngine's generic value: the pack gives none")
            + "); the beams' end moments take no relief from the beams' own creep"
        )
    else:
        notes.append(
            "the steel restrains the elastic strain (transformed section) but not the creep"
            + ("" if ctx.model.reinforced else " nor the shrinkage")
            + ", and the beams' end moments take no relief from their own creep: on the high side"
        )
    if not ctx.model.legacy and not getattr(options, "strength", None):
        notes.append(
            "the concrete strength of each member is taken from its modulus by the code pack's "
            "Ec rule (enter it under Concrete strength to set it)"
        )
    found = {
        "available": True,
        "inputs": {
            "humidity": conditions.humidity,
            "exposure": conditions.exposure,
            "water": conditions.water,
            "curing": conditions.curing,
            "cycle": cycle,
            "superimposedAfter": float(options.superimposedAfterDays),
            "sustainedLive": float(options.sustainedLive),
            "serviceLife": float(options.serviceLifeYears),
            "steelRatio": float(options.steelRatio),
            "staged": staged,
        },
        "times": {"complete": complete, "superimposed": later, "end": end},
        "levels": names,
        "lines": out_lines,
        "differential": differential,
        "history": {"days": days, "lines": history},
        "clauses": {
            key: concrete_time.clause(key)
            for key in (
                "analysis",
                "phased",
                "effects",
                "creep",
                "creepFigure",
                "creepDevelopment",
                "thickness",
                "shrinkage",
                "shrinkageFigure",
                "reinforced",
                "modulus",
            )
        },
        "notes": notes,
    }
    # ── alpha 9 P2: the models, adjacent members, the pre-sets, the forces case ──
    found["model"] = {
        "name": concrete_time.model_name(),
        "creep": concrete_time.creep_method(),
        "shrinkage": concrete_time.shrinkage_method(),
        "analysis": ctx.model.method,
        "chi": ctx.model.chi if ctx.model.method == "ageAdjusted" else None,
        "basis": ctx.model.basis,
    }
    found["pairs"] = _pairs(ctx.lines, after_line, names)
    found["camber"] = _camber(ctx.lines, after_line, names)
    if walls_at:
        found["inputs"]["wallSteelRatio"] = float(getattr(options, "wallSteelRatio", 0.0))
    if getattr(options, "finalDays", None) is not None:
        found["inputs"]["finalDays"] = end
    if results.get(CASE) is not None:
        found["induced"] = _induced(project, ctx, results, corrections)
    return found


def _camber(
    lines: list[Line], after: dict[str, dict[int, float]], names: list[str]
) -> list[dict[str, Any]]:
    """The pre-set of every line at every level: the level is cast higher by its shortening
    after casting (``preset``); the storey below is made longer by the increase over the level
    below (``storey``); ``relative``: over the least of the lines at that level (the
    correction relative to the line that shortens least, often the core)."""
    least: dict[int, float] = {}
    for values in after.values():
        for level, value in values.items():
            least[level] = min(least.get(level, value), value)
    rows = []
    for line in lines:
        values = after.get(line.label, {})
        below = 0.0
        for level in sorted(values):
            rows.append(
                {
                    "line": line.label,
                    "kind": line.kind,
                    "level": names[level],
                    "preset": values[level],
                    "storey": values[level] - below,
                    "relative": values[level] - least.get(level, 0.0),
                }
            )
            below = values[level]
    return rows


def _pairs(
    lines: list[Line], after: dict[str, dict[int, float]], names: list[str]
) -> list[dict[str, Any]]:
    """Each line with its nearest neighbour (and each column with its nearest wall): the
    largest difference of their shortening after casting over their common levels, largest
    first."""
    if len(lines) < 2:
        return []
    points = [np.asarray(line.points or [(line.x, line.y)], dtype=float) for line in lines]

    def distance(i: int, j: int) -> float:
        a, b = points[i], points[j]
        return float(np.min(np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)))

    chosen: set[tuple[int, int]] = set()
    for i, line in enumerate(lines):
        others = [j for j in range(len(lines)) if j != i]
        nearest = min(others, key=lambda j: distance(i, j))
        chosen.add((min(i, nearest), max(i, nearest)))
        if line.kind == "column":
            walls = [j for j in others if lines[j].kind == "wall"]
            if walls:
                wall = min(walls, key=lambda j: distance(i, j))
                chosen.add((min(i, wall), max(i, wall)))
    rows = []
    for i, j in sorted(chosen):
        a, b = after.get(lines[i].label, {}), after.get(lines[j].label, {})
        common = sorted(set(a) & set(b))
        if not common:
            continue
        level = max(common, key=lambda k: abs(a[k] - b[k]))
        gap = distance(i, j)
        difference = abs(a[level] - b[level])
        rows.append(
            {
                "a": lines[i].label,
                "b": lines[j].label,
                "kinds": f"{lines[i].kind}-{lines[j].kind}",
                "distance": gap,
                "level": names[level],
                "difference": difference,
                "slope": difference / gap if gap > 0 else 0.0,
            }
        )
    rows.sort(key=lambda r: -r["difference"])
    return rows[:DIFFERENTIAL_ROWS]


def _differential(
    project: dict[str, Any],
    coords: dict[int, np.ndarray],
    sections: dict[int, dict[str, Any]],
    after_casting: dict[tuple[float, float], dict[int, float]],
    zs: list[float],
    names: list[str],
    walls: dict[str, Line] | None = None,
    after_line: dict[str, dict[int, float]] | None = None,
) -> list[dict[str, Any]]:
    """The beams between two column lines (or a column and a wall line, or two walls) at one
    level: the difference of their ends' shortening after casting and the indicative end
    moment 6 E I Δ / L², largest first."""
    from saengine.fem.member_detail import member_of

    members: dict[str, list[dict[str, Any]]] = {}
    for element in project.get("elements", []):
        nodes = element.get("nodes") or []
        if len(nodes) != 2 or "section_id" not in element:
            continue
        a, b = coords[nodes[0]], coords[nodes[1]]
        if abs(a[2] - b[2]) > LEVEL_TOLERANCE or np.linalg.norm(a - b) < 10 * PLAN_TOLERANCE:
            continue
        members.setdefault(member_of(str(element.get("name", element["id"]))), []).append(element)

    def line_at(point: np.ndarray) -> tuple[float, float] | None:
        for key in after_casting:
            if abs(key[0] - point[0]) < PLAN_TOLERANCE and abs(key[1] - point[1]) < PLAN_TOLERANCE:
                return key
        return None

    def wall_at(point: np.ndarray) -> str | None:
        """A wall line with a node at the point's plan position (P2)."""
        for name, line in (walls or {}).items():
            if any(
                abs(x - point[0]) < 10 * PLAN_TOLERANCE and abs(y - point[1]) < 10 * PLAN_TOLERANCE
                for x, y in line.points
            ):
                return name
        return None

    rows = []
    for name, elements in members.items():
        count: dict[int, int] = {}
        for e in elements:
            for n in e["nodes"]:
                count[n] = count.get(n, 0) + 1
        ends = [n for n, c in count.items() if c == 1]
        if len(ends) != 2:
            continue
        p, q = coords[ends[0]], coords[ends[1]]
        level = int(np.argmin([abs(p[2] - z) for z in zs]))
        if abs(p[2] - zs[level]) > 0.05:
            continue
        lp, lq = line_at(p), line_at(q)
        sp = after_casting[lp].get(level) if lp is not None else None
        sq = after_casting[lq].get(level) if lq is not None else None
        if walls and after_line is not None:
            # A beam end on a wall (a coupling beam, a beam framing into the core).
            wp = wall_at(p) if lp is None else None
            wq = wall_at(q) if lq is None else None
            if wp is not None:
                lp, sp = ("wall", wp), after_line.get(wp, {}).get(level)
            if wq is not None:
                lq, sq = ("wall", wq), after_line.get(wq, {}).get(level)
        if lp is None or lq is None or lp == lq:
            continue
        if sp is None or sq is None:
            continue
        section = sections.get(elements[0]["section_id"]) or {}
        length = float(np.linalg.norm(p[:2] - q[:2]))
        delta = abs(sp - sq)
        e, i = float(section.get("E") or 0.0), float(section.get("Iy") or 0.0)
        rows.append(
            {
                "beam": name,
                "level": names[level],
                "length": length,
                "difference": delta,
                "rotation": delta / length if length > 0 else 0.0,
                "moment": 6 * e * i * delta / length**2 if length > 0 else 0.0,
            }
        )
    rows.sort(key=lambda r: -r["difference"])
    return rows[:DIFFERENTIAL_ROWS]


# ───────────────────────────── alpha 9 P2: the forces case CS ─────────────────────────────


def _relaxation(ctx: _Context) -> tuple[float, float]:
    """(r, φ̄): the age-adjusted relaxation 1 / (1 + χ φ̄) of the induced forces, φ̄ the mean
    creep coefficient (relative to the modulus at loading) of the vertical members from their
    first load to the end."""
    values = []
    for line in ctx.lines:
        for st in line.storeys:
            if not st.loads:
                continue
            t0 = st.loads[0].time
            age = max(t0 - st.cast, 1.0)
            phi = concrete_time.creep_phi(
                st.thickness, ctx.conditions.humidity, age, ctx.end - t0, st.strength
            )
            if ctx.model.basis != "loading":
                e_t = st.modulus * concrete_time.modulus_ratio(age)
                phi *= e_t / (ctx.model.tangent * st.modulus) if st.modulus > 0 else 1.0
            values.append(phi)
    phi_mean = float(np.mean(values)) if values else 0.0
    return 1.0 / (1.0 + ctx.model.chi * phi_mean), phi_mean


def _held_shell(section: dict[str, Any], axes: tuple[np.ndarray, ...], strain: float) -> list:
    """The held membrane resultants (N11 N22 N12 M11 M22 M12 Q13 Q23, the shell's axes) of a
    plate whose vertical strain ``strain`` (shortening positive) is suppressed."""
    e1, e2, _ = axes
    v1, v2 = float(e1[2]), float(e2[2])
    eigen = -strain  # shortening: a negative free strain along the vertical
    e11, e22, g12 = eigen * v1 * v1, eigen * v2 * v2, 2.0 * eigen * v1 * v2
    e, nu, h = float(section["E"]), float(section.get("nu", 0.2)), float(section["h"])
    plate = e * h / (1.0 - nu * nu)
    return [
        -plate * (e11 + nu * e22),
        -plate * (e22 + nu * e11),
        -e * h / (2.0 * (1.0 + nu)) * g12,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    ]


def add_creep_shrinkage_case(
    project: dict[str, Any],
    results: dict[str, Any],
    levels: list[dict[str, Any]],
    options: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Add the creep and shrinkage forces case CS to an OpenSees Studio ``project`` (in place):
    the strains of each storey of the column (and wall) lines after its floor is cast, per
    construction stage, as equivalent fixed-end loads (:mod:`saengine.fem.thermal`'s method).
    With the staged dead load the case is staged the same way: stage k applies the creep and
    shrinkage between stage k and stage k + 1 (the last up to the end) of the storeys built by
    then, to the structure built by then. Without it the case is static, on the complete
    frame. ``results``: the gravity results (:func:`column_shortening`'s). Returns (the
    fixed-end forces to add back, ``{"case", "frames", "shells", "relaxation", "phi", "chi"}``,
    or None; notes)."""
    from saengine.fem.derive import local_axes
    from saengine.fem.thermal import frame_fixed_end_forces

    ctx = _prepare(project, results, levels, options)
    if isinstance(ctx, dict):
        return None, [f"creep and shrinkage forces: not formed ({ctx.get('reason', '')})"]
    from saengine.design.slab import shell_axes
    from saengine.design.wall_forces import stress_nodal_forces

    relax, phi_mean = _relaxation(ctx)
    elements = {e["id"]: e for e in project.get("elements", [])}
    if ctx.staged:
        bounds = [*ctx.stage_times, ctx.end]
        count = ctx.stage_count
    else:
        bounds = []
        count = 1
    nodal: list[dict[int, np.ndarray]] = [{} for _ in range(count)]
    frames: dict[str, np.ndarray] = {}
    shells: dict[str, np.ndarray] = {}
    for line in ctx.lines:
        for st in line.storeys:
            if ctx.staged:
                steps = [
                    (k, ctx.inelastic(st, bounds[k + 1]) - ctx.inelastic(st, bounds[k]))
                    for k in range(min(st.stage, count - 1), count)
                ]
            else:
                start = st.cast + ctx.cycle
                steps = [(0, ctx.inelastic(st, ctx.end) - ctx.inelastic(st, start))]
            for k, strain in steps:
                if abs(strain) < 1e-12:
                    continue
                for element_id in st.elements:
                    element = elements.get(element_id)
                    if element is None:
                        continue
                    section = ctx.sections.get(element.get("section_id")) or {}
                    nodes = list(element["nodes"])
                    if line.kind == "column":
                        a, b = ctx.coords[nodes[0]], ctx.coords[nodes[1]]
                        axes = np.array(local_axes(a, b, element.get("vecxz")))
                        f0 = frame_fixed_end_forces(
                            float(section["E"]),
                            float(section["A"]),
                            float(section.get("Iy") or 0.0),
                            float(section.get("Iz") or 0.0),
                            1.0,
                            -strain * relax,
                        )
                        for j, node in enumerate(nodes):
                            load = nodal[k].setdefault(node, np.zeros(6))
                            load[:3] -= axes.T @ f0[6 * j : 6 * j + 3]
                            load[3:] -= axes.T @ f0[6 * j + 3 : 6 * j + 6]
                        key = str(element_id)
                        frames[key] = frames.get(key, np.zeros(12)) + f0
                    else:
                        points = [ctx.coords[n] for n in nodes]
                        held = np.asarray(
                            _held_shell(section, shell_axes(points), strain * relax), dtype=float
                        )
                        loads = -stress_nodal_forces(points, held[None, :])
                        for j, node in enumerate(nodes):
                            nodal[k].setdefault(node, np.zeros(6))[:] += loads[j]
                        key = str(element_id)
                        shells[key] = shells.get(key, np.zeros(8)) + held
    notes: list[str] = []
    if not frames and not shells:
        return None, ["creep and shrinkage forces: no column or wall strains after casting"]

    patterns = project.setdefault("load_patterns", [])
    series = next(
        (s["id"] for s in project.get("time_series", []) if s.get("type") == "Linear"), None
    )
    if series is None:
        series = 1 + max((s["id"] for s in project.get("time_series", [])), default=0)
        project.setdefault("time_series", []).append(
            {"id": series, "name": "", "type": "Linear", "factor": 1.0}
        )
    pattern_ids: list[int | None] = []
    for k, loads in enumerate(nodal):
        if not loads:
            pattern_ids.append(None)
            continue
        pid = 1 + max((p["id"] for p in patterns), default=0)
        patterns.append(
            {
                "id": pid,
                "name": f"{CASE}, stage {k + 1}" if ctx.staged else CASE,
                "type": "Plain",
                "time_series_id": series,
                "nodal_loads": [
                    {"node_id": n, "forces": [round(float(v), 6) for v in f]}
                    for n, f in sorted(loads.items())
                ],
                "element_loads": [],
            }
        )
        pattern_ids.append(pid)
    analyses = project.setdefault("analyses", [])
    number = 1 + max((a["id"] for a in analyses), default=0)
    name = f"{CASE}: {CASE_TITLE}"
    if ctx.staged:
        dead = next(a for a in analyses if _code(a.get("name", "")) == "D")
        stages = []
        for k, stage in enumerate(dead.get("stages") or []):
            pid = pattern_ids[k] if k < len(pattern_ids) else None
            built = list(stage.get("element_ids", []))
            if built or pid is not None:
                stages.append(
                    {
                        "name": stage.get("name", f"Stage {k + 1}"),
                        "element_ids": built,
                        "pattern_ids": [pid] if pid is not None else [],
                    }
                )
        analysis: dict[str, Any] = {
            "id": number,
            "name": f"{name}, construction sequence",
            "type": "Staged",
            "stages": stages,
            "system": dead.get("system", "BandGeneral"),
            "constraints": dead.get("constraints", "Plain"),
        }
        if any(e.get("geom_transf", "Linear") != "Linear" for e in project.get("elements", [])):
            analysis["linear_geometry"] = True
    else:
        analysis = {
            "id": number,
            "name": name,
            "type": "Static",
            "pattern_ids": [p for p in pattern_ids if p is not None],
            "n_steps": 1,
            "load_factor_increment": 1.0,
            "system": "BandGeneral",
            "constraints": "Plain",
            "integrator": "LoadControl",
            "algorithm": "Linear",
            "test": "NormDispIncr",
            "tolerance": 1e-8,
            "max_iter": 25,
        }
    analyses.append(analysis)
    notes.append(
        f"creep and shrinkage forces: the case {CASE} imposes the creep and shrinkage of "
        f"{sum(1 for line in ctx.lines for _ in line.storeys)} column and wall storeys after "
        "their floors are cast"
        + (f", in {ctx.stage_count} construction stages" if ctx.staged else " on the frame")
        + f"; the forces relaxed by 1 / (1 + χ φ̄) = {relax:.2f} (χ = {ctx.model.chi:g}"
        + ("" if ctx.model.chi_given else ", generic")
        + f", φ̄ = {phi_mean:.2f}), so its deflections are of the relaxed forces too (the "
        "shortening itself is in the column shortening results)"
    )
    corrections = {
        "case": CASE,
        "frames": {k: [float(x) for x in v] for k, v in frames.items()},
        "shells": {k: [float(x) for x in v] for k, v in shells.items()},
        "relaxation": relax,
        "phi": phi_mean,
        "chi": ctx.model.chi,
    }
    return corrections, ctx.notes + notes


def levels_of(project: dict[str, Any], stories: list[Any]) -> list[dict[str, Any]]:
    """The levels ``[{"z", "name"}]`` of the analysis model for :func:`column_shortening`:
    its base (lowest support) and the building's storeys above it, as
    :func:`saengine.fem.story_response.storey_levels` reads them from the project."""
    supports = [
        float(n["coords"][2]) for n in project.get("nodes", []) if any(n.get("restraint") or [])
    ]
    tops = [float(n["coords"][2]) for n in project.get("nodes", [])]
    if not supports or not tops:
        return []
    base, top = round(min(supports), 3), max(tops)
    named = [
        {"z": round(float(s.elevation) / 1e3, 3), "name": str(s.name or s.id)} for s in stories
    ]
    above = sorted(
        (s for s in named if base + LEVEL_TOLERANCE < s["z"] <= top + LEVEL_TOLERANCE),
        key=lambda s: s["z"],
    )
    at_base = next((s["name"] for s in named if abs(s["z"] - base) <= LEVEL_TOLERANCE), None)
    return [{"z": base, "name": at_base or "Base"}, *above]


def derive_case(
    project: dict[str, Any], levels: list[dict[str, Any]], options: Any
) -> tuple[dict[str, Any] | None, list[str]]:
    """The forces case CS of a derived model: its gravity cases (D, staged or not, SD, L and a
    P-Delta preload they take) are run on their own first, for the columns' and walls' axial
    forces in time, then :func:`add_creep_shrinkage_case` adds the case to ``project``."""
    import tempfile

    from opensees_studio.services.result_store import load_manifest, load_results

    from saengine.fem.seismic_design import _run

    analyses = {a["id"]: a for a in project.get("analyses", [])}
    kept = [a for a in analyses.values() if _code(a.get("name", "")) in ("D", "SD", "L")]
    if not any(_code(a.get("name", "")) == "D" for a in kept):
        return None, ["creep and shrinkage forces: the model has no dead load case"]
    preloads = {i for a in kept for i in a.get("preload_case_ids", []) or [] if i in analyses}
    kept += [analyses[i] for i in sorted(preloads)]
    model = {**project, "analyses": kept, "spectra": [], "ground_motions": []}
    model["load_patterns"] = [
        p for p in project.get("load_patterns", []) if p.get("type", "Plain") == "Plain"
    ]
    model["time_series"] = [s for s in project.get("time_series", []) if "record_id" not in s]
    results: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="saengine-creep-") as tmp:
            out = _run(
                model,
                Path(tmp),
                [int(a["id"]) for a in kept],
                what="the gravity run of the creep and shrinkage forces",
            )
            for entry in load_manifest(out)["cases"]:
                code = _code(entry.get("case_name", ""))
                if code in ("D", "SD", "L"):
                    results[code] = load_results(entry, out)
    except (ValueError, OSError) as error:
        return None, [f"creep and shrinkage forces: not formed ({error})"]
    return add_creep_shrinkage_case(project, results, levels, options)


# ───────────────────────────── the induced forces of the case CS ─────────────────────────────


def _induced(
    project: dict[str, Any],
    ctx: _Context,
    results: dict[str, Any],
    corrections: dict[str, Any] | None,
) -> dict[str, Any]:
    """The run's case CS: the change of each line's axial force at its base (the
    redistribution between columns and walls, as a share of its D + SD) and the beams with the
    largest induced end moments."""
    from saengine.fem.member_detail import member_of
    from saengine.fem.thermal import end_force_corrections, shell_force_corrections

    cs = results[CASE]
    frame_add = end_force_corrections(corrections, CASE)
    shell_add = shell_force_corrections(corrections, CASE)
    elements = {e["id"]: e for e in project.get("elements", [])}
    redistribution = []
    for line in ctx.lines:
        if not line.storeys:
            continue
        st = line.storeys[0]
        if line.kind == "column":
            force = float(
                np.sum(
                    [
                        _compression(cs.element_forces.get(i), -1, frame_add.get(i))
                        for i in st.elements
                    ]
                )
            )
            dead = sum(
                float(np.sum([_compression(r.element_forces.get(i), -1) for i in st.elements]))
                for r in (results.get("D"), results.get("SD"))
                if r is not None
            )
        else:
            shells = [elements[i] for i in st.elements if i in elements]
            top = max(ctx.coords[n][2] for e in shells for n in e["nodes"])
            force = _wall_compression(cs, shells, ctx.coords, st.bottom, top, -1, shell_add)
            dead = sum(
                _wall_compression(r, shells, ctx.coords, st.bottom, top, -1)
                for r in (results.get("D"), results.get("SD"))
                if r is not None
            )
        redistribution.append(
            {
                "line": line.label,
                "kind": line.kind,
                "force": force,
                "share": force / dead if abs(dead) > 1e-9 else 0.0,
            }
        )
    beams: dict[str, dict[str, Any]] = {}
    zs, names = ctx.zs, ctx.names
    for element_id, rows in cs.element_forces.items():
        element = elements.get(int(element_id))
        nodes = (element or {}).get("nodes") or []
        if element is None or len(nodes) != 2 or rows is None or not len(rows):
            continue
        a, b = ctx.coords[nodes[0]], ctx.coords[nodes[1]]
        if abs(a[2] - b[2]) > LEVEL_TOLERANCE or np.linalg.norm(a - b) < 10 * PLAN_TOLERANCE:
            continue
        row = np.asarray(rows[-1], dtype=float)[:12]
        if row.size < 12:
            continue
        moment = float(np.max(np.abs(row[[4, 5, 10, 11]])))
        name = member_of(str(element.get("name", element_id)))
        if moment > beams.get(name, {}).get("moment", -1.0):
            level = int(np.argmin([abs(a[2] - z) for z in zs]))
            beams[name] = {"beam": name, "level": names[level], "moment": moment}
    top_beams = sorted(beams.values(), key=lambda r: -r["moment"])[:INDUCED_ROWS]
    columns = sum(r["force"] for r in redistribution if r["kind"] == "column")
    walls = sum(r["force"] for r in redistribution if r["kind"] == "wall")
    case = ((corrections or {}).get("more") or {}).get(CASE) or {}
    return {
        "redistribution": redistribution,
        "beams": top_beams,
        "columns": columns,
        "walls": walls,
        "relaxation": case.get("relaxation"),
        "phi": case.get("phi"),
    }


def from_run(out_dir: Any, project_path: Any) -> dict[str, Any] | None:
    """:func:`column_shortening` of a finished run (``<model>.results``) of a SAEngine model,
    with the settings beside it; None when the settings do not ask for it."""
    import json

    from saengine.fem.combinations import settings_beside
    from saengine.fem.display import _manifest
    from saengine.fem.story_response import load_cached, storey_levels
    from saengine.fem.thermal import load_corrections

    found = settings_beside(project_path)
    options = getattr(getattr(found, "analysis", None), "timeDependent", None)
    if options is None or not options.enabled:
        return None
    manifest = _manifest(out_dir)
    if manifest is None:
        return {"available": False, "reason": "there are no results; run the analysis first"}
    project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    results = {}
    for entry in manifest["cases"]:
        code = _code(entry.get("case_name", ""))
        if code in ("D", "SD", "L", CASE):
            results[code] = load_cached(entry, out_dir)
    return column_shortening(
        project,
        results,
        storey_levels(project, project_path),
        options,
        load_corrections(project_path),
    )
