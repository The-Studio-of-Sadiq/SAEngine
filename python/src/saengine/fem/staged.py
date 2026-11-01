"""Column shortening of a building built storey by storey, with creep and shrinkage (B25).

The code pack asks for the long-term properties of the materials in the analysis, for the
additional stresses of phased construction and for creep and shrinkage (BNBC 2020 Part 6 Sec
1.2.7, 1.2.16, 1.6.6(h),(j),(l); the clauses come from the pack's ``concreteTime`` sources).
This module works them out for the concrete columns from a finished run:

1. **Column lines.** The vertical frame elements of the analysis model, grouped by plan
   position; each storey of a line is the elements between two levels. Its section gives the
   area, the modulus at 28 days and (from the area and the second moments: a rectangle or a
   circle) the perimeter, so the effective thickness 2A/u.
2. **Loads in time.** The construction sequence's staged dead load ``D`` (when the settings run
   it): stage k's increment of each storey's axial force arrives when stage k is cast,
   ``(k + 1) × cycle`` days after the start, on concrete cast at ``(stage built) × cycle``. A
   storey's age at loading is therefore at least one cycle. Without the staged case the dead
   load arrives at once when the frame is complete. The superimposed dead load ``SD`` and the
   sustained share of the live load ``L`` arrive ``superimposedAfterDays`` after completion.
3. **Strains.** For each load increment: the stress on the transformed section
   ``ΔN / (A (1 + (n - 1) ρ))``, ``n = Es / Et``, its elastic strain ``stress / Et`` and creep
   strain ``stress / Et × cc × share(t - tk)`` (:mod:`saengine.fem.concrete_time`, Eq 6.5.3
   form; ``cc`` at the age at loading), summed (superposition of the creep of each increment);
   plus the shrinkage of the reinforced section from the end of curing. The steel's restraint
   of the creep itself is ignored (more shortening: on the safe side for the shortening).
4. **Shortening.** Each storey shortens by its strain times its height. At a level, the total
   is the sum over the storeys below; what matters for the floors is the shortening **after the
   level was cast** (the floor is cast level, so what happened before it is made up): the sum
   over the storeys below of their shortening after that time.
5. **Differential shortening.** For each beam whose two ends sit on column lines at the same
   level, the difference of the two ends' shortening after casting, at the end of the service
   life, and the indicative end moment ``6 E I Δ / L²`` of a beam fixed at both ends (with the
   beam section's E and Iy: no relief by the beam's own creep, so on the high side).

Values in the model's units: m, N; times in days.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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


@dataclass
class Load:
    """An axial load increment [N, compression positive] arriving at ``time`` [days]."""

    time: float
    force: float


@dataclass
class Storey:
    """One storey of a column line."""

    elements: list[int]
    name: str
    bottom: float  # z [m]
    top: float
    area: float  # m²
    perimeter: float  # m
    modulus: float  # Pa, 28 days
    cast: float  # day
    loads: list[Load] = field(default_factory=list)

    @property
    def height(self) -> float:
        return self.top - self.bottom

    @property
    def thickness(self) -> float:
        """Effective thickness [mm]."""
        return concrete_time.effective_thickness(self.area * 1e6, self.perimeter * 1e3)


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


def _compression(rows: Any, step: int) -> float:
    """Mid-length axial compression [N] of an element's end forces at ``step``."""
    if rows is None or not len(rows):
        return 0.0
    row = np.asarray(rows[min(step, len(rows) - 1)], dtype=float)
    return float((row[0] - row[6]) / 2.0) if row.size >= 12 else 0.0


def _strain(
    storey: Storey,
    t: float,
    conditions: concrete_time.Conditions,
    options: Any,
    steel_e: float,
    before: bool = False,
) -> tuple[float, float, float]:
    """(elastic, creep, shrinkage) strain of ``storey`` at day ``t`` (shortening positive);
    ``before``: without the loads arriving exactly at ``t``."""
    elastic = creep = 0.0
    thickness = storey.thickness
    rho = float(options.steelRatio)
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


def column_shortening(
    project: dict[str, Any],
    results: dict[str, Any],
    levels: list[dict[str, Any]],
    options: Any,
) -> dict[str, Any]:
    """The column shortening of a run (see the module's description).

    ``results``: the static results by case code (``D``, ``SD``, ``L``; ``D`` may be the
    staged case); ``levels``: ``[{"z", "name"}]`` bottom up; ``options``: the settings'
    ``analysis.timeDependent``. Returns ``{"available", "reason"?, "inputs", "times", "levels",
    "lines": [{"line", "x", "y", "storeys": [{"storey", "thickness", "coefficient"}], "rows":
    [{"level", "z", "elastic", "creep", "shrinkage", "total", "afterCasting"}]}],
    "differential": [...], "history": {"days", "lines": [{"line", "values"}]}, "clauses",
    "notes"}`` (lengths in m, days from the start of construction)."""
    try:
        conditions = concrete_time.Conditions.of(options)
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

    def level_of(z: float) -> int:
        return int(np.argmin([abs(z - v) for v in zs]))

    # ── column lines ──
    lines: dict[tuple[int, int], dict[int, list[dict[str, Any]]]] = {}
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
        lines.setdefault(key, {}).setdefault(top, []).append(element)
    if not lines:
        return {"available": False, "reason": "the model has no columns between its levels"}
    complete = (stage_count if staged else len(zs) - 1) * cycle
    later = complete + float(options.superimposedAfterDays)

    def forces(code: str, element_id: int, step: int = -1) -> float:
        found = results.get(code)
        if found is None:
            return 0.0
        return _compression(found.element_forces.get(element_id), step)

    built: list[tuple[str, float, float, list[Storey]]] = []
    for key, by_level in sorted(lines.items()):
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
                cast=(stage if staged else top - 1) * cycle,
            )

            def mean(code: str, step: int = -1, ids: list[int] = ids) -> float:
                return float(np.mean([forces(code, i, step) for i in ids]))

            if staged:
                previous = 0.0
                for k in range(stage_count):
                    now = mean("D", k)
                    if abs(now - previous) > 1e-9:
                        storey.loads.append(Load((k + 1) * cycle, now - previous))
                    previous = now
            elif dead is not None:
                storey.loads.append(Load(complete, mean("D")))
            sustained = mean("SD") + float(options.sustainedLive) * mean("L")
            if abs(sustained) > 1e-9:
                storey.loads.append(Load(later, sustained))
            storeys.append(storey)
        x, y = key[0] * PLAN_TOLERANCE, key[1] * PLAN_TOLERANCE
        built.append((storeys[0].name, x, y, storeys))

    life = float(options.serviceLifeYears) * 365.0
    if life > concrete_time.final_age():
        notes.append(
            f"the service life is longer than the {concrete_time.final_age() / 365:g} years the "
            "code pack's final creep is for: the final values are used beyond it"
        )
    end = complete + life
    if conditions.humidity < min(concrete_time.required_table().creep.relativeHumidity):
        notes.append(
            "the relative humidity is below the creep table's range: its lowest humidity is used"
        )

    def strains(storey: Storey, t: float, before: bool = False) -> tuple[float, float, float]:
        return _strain(storey, t, conditions, options, steel_e, before)

    out_lines = []
    after_casting: dict[tuple[float, float], dict[int, float]] = {}
    for label, x, y, storeys in built:
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
            after_casting.setdefault((x, y), {})[level] = after
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
        out_lines.append(
            {
                "line": label,
                "x": x,
                "y": y,
                "storeys": [
                    {
                        "storey": st.name,
                        "thickness": st.thickness,
                        "coefficient": concrete_time.creep_coefficient(
                            st.thickness,
                            conditions.humidity,
                            max(st.loads[0].time - st.cast, 1.0) if st.loads else 28.0,
                        ),
                    }
                    for st in storeys
                ],
                "rows": rows,
            }
        )

    # ── history of the top of each line ──
    days = sorted({*(complete + d for d in HISTORY_DAYS if d <= life), later, end})
    days = [cycle * k for k in range(1, int(complete / cycle) + 1)] + [
        d for d in days if d > complete
    ]
    history = []
    for label, _, _, storeys in built:
        history.append(
            {
                "line": label,
                "values": [sum(sum(strains(st, t)) * st.height for st in storeys) for t in days],
            }
        )

    differential = _differential(project, coords, sections, after_casting, zs, names)
    if not staged:
        notes.append("turn the construction sequence on for the staged dead load")
    notes.append(
        "the steel restrains the elastic strain (transformed section) but not the creep, and "
        "the beams' end moments take no relief from the beams' own creep: on the high side"
    )
    return {
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


def _differential(
    project: dict[str, Any],
    coords: dict[int, np.ndarray],
    sections: dict[int, dict[str, Any]],
    after_casting: dict[tuple[float, float], dict[int, float]],
    zs: list[float],
    names: list[str],
) -> list[dict[str, Any]]:
    """The beams between two column lines at one level: the difference of their ends'
    shortening after casting and the indicative end moment 6 E I Δ / L², largest first."""
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
        if lp is None or lq is None or lp == lq:
            continue
        sp, sq = after_casting[lp].get(level), after_casting[lq].get(level)
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
