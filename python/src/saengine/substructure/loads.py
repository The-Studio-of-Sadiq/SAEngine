"""The loads the columns and walls put on their foundations: the support reactions of the
analysis (Part 8), per static case and per load combination.

The analysis model ends the columns and walls at fixed supports at their bases (a column at one
node, a wall along its whole base edge). Each support reaction, reversed, is what the column or
wall puts on its foundation. The model is linear, so a combination is the factored sum of its
static cases, as :mod:`saengine.fem.combinations` forms them.

Two kinds of combinations, as is usual for foundations (ACI 318-19 13.2.6.1, 13.3.1.1):

- SERVICE (unfactored) allowable-stress combinations for bearing, settlement and the pile
  loads against their allowable capacities: BNBC 2020 Part 6 2.7.2 (ASCE 7-05 2.4.1), for this
  project's nominal (service-level) wind: D, D + L + Lr (enveloping BNBC 2.7.2.1 (2)-(4): D + L,
  D + Lr and D + 0.75L + Lr), D + W, D + 0.75L + 0.75Lr + 0.75W,
  0.6D + W, D + 0.7E, D + 0.75L + 0.75Lr + 0.525E and 0.6D + 0.7E, wind and earthquake in ±X
  and ±Y, D standing for the dead and superimposed dead cases. When the project's strength
  combinations treat wind as strength-level (no wind factor above 1.0), the ASCE 7-16 2.4.1
  factors 0.6W and 0.45W are used instead.
- STRENGTH (factored) combinations of Project Settings for the concrete design.

Units: the reactions as the results store them, N and N·m in global axes; positions in mm.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.library.bim import BuildingModel, ColumnElement, WallElement
from saengine.library.settings import ProjectSettings


def service_combinations(
    cases: set[str] | list[str] | dict[str, Any], strength_level_wind: bool = False
) -> list[tuple[str, dict[str, float]]]:
    """The allowable-stress combinations of :func:`_service_combinations`, then those with the
    temperature case T when it was analysed (BNBC 2020 Part 6 Sec 2.7.2.1 combinations 2 and 4,
    :func:`saengine.fem.thermal.service_combinations_with_t`), the earth pressure H in every
    one, and the fluid case F wherever D is
    (a tank's contents act with its weight; there is no 0.6D service combination with F)."""
    from saengine.fem.thermal import service_combinations_with_t

    result = _service_combinations(cases, strength_level_wind)
    result += service_combinations_with_t(cases)
    if "H" in set(cases):
        # The earth pressure acts with every service combination (ASCE 7-05 2.4.1: D + H + F
        # + L ..., 0.6D + W + H; BNBC 2020 Part 6 Sec 2.7.2.1).
        result = [(name, {**factors, "H": 1.0}) for name, factors in result]
    if "F" in set(cases):
        result = [
            (name, {**factors, "F": factors.get("D", factors.get("SD", 0.0))})
            if (factors.get("D", factors.get("SD", 0.0)) >= 1.0)
            else (name, factors)
            for name, factors in result
        ]
    return result


def _service_combinations(
    cases: set[str] | list[str] | dict[str, Any], strength_level_wind: bool = False
) -> list[tuple[str, dict[str, float]]]:
    """The allowable-stress combinations the static ``cases`` allow, as (name, {case: factor});
    ``D`` stands for the dead and superimposed dead cases. Wind is nominal (service-level) as
    BNBC 2020 Part 6 defines it, with the 2.7.2 combinations (ASCE 7-05 2.4.1): D + W,
    D + 0.75L + 0.75Lr + 0.75W and 0.6D + W; ``strength_level_wind`` takes the ASCE 7-16 2.4.1
    factors 0.6W and 0.45W instead. Each wind term is each design wind load case of BNBC 2020
    Figure 6.2.9 (Sec 2.4.11.3: Case 1, and Cases 2-4 with WTX, WTY when they were analysed),
    named "<combination> [Case k ...]". Earthquake is strength-level: 0.7E and 0.525E."""
    cases = set(cases)
    dead = [c for c in ("D", "SD") if c in cases]
    if not dead:
        return []
    live = [c for c in ("L", "Lr") if c in cases]

    def terms(*parts: tuple[float, list[str]]) -> tuple[str, dict[str, float]]:
        factors: dict[str, float] = {}
        words: list[str] = []
        for factor, group in parts:
            for case in group:
                factors[case] = factor
            shown = ["D"] if group == dead else group
            for case in shown:
                magnitude = abs(factor)
                text = f"{'' if magnitude == 1 else f'{magnitude:g}'}{case}"
                if words:
                    words.append(("- " if factor < 0 else "+ ") + text)
                else:
                    words.append(("-" if factor < 0 else "") + text)
        return " ".join(words), factors

    result = [terms((1.0, dead))]
    if live:
        result.append(terms((1.0, dead), (1.0, live)))
    wind = (0.6, 0.45, 0.6) if strength_level_wind else (1.0, 0.75, 1.0)
    variants = _wind_variants(cases)
    for lateral, alone, with_live, light in (
        ("W", *wind),
        ("E", 0.7, 0.525, 0.7),
    ):
        for axis in ("X", "Y"):
            case = f"{lateral}{axis}"
            if case not in cases:
                continue
            for sign in (1.0, -1.0):
                # Wind: each design wind load case of Figure 6.2.9 (Case 1 alone, Cases 2-4
                # when the model has them), as in the strength combinations.
                shapes = variants(case, sign) if lateral == "W" else [("", {case: sign})]
                for label, shape in shapes:
                    suffix = f" [{label}]" if label else ""
                    for head, scale in (
                        ([(1.0, dead)], alone),
                        ([(1.0, dead), (0.75, live)] if live else None, with_live),
                        ([(0.6, dead)], light),
                    ):
                        if head is None:
                            continue
                        lateral_terms = [(scale * f, [c]) for c, f in shape.items()]
                        name, factors = terms(*head, *lateral_terms)
                        result.append((name + suffix, factors))
    return result


def _wind_variants(cases: set[str]) -> Any:
    """``(case, sign) -> [(label, {case: unit factor})]``: the design wind load cases of BNBC
    2020 Part 6 Sec 2.4.11.3 and Figure 6.2.9 (p. 559 and pp. 574-575) of one wind direction,
    from :func:`saengine.fem.loads.wind_design_variants` (one definition with the strength
    combinations); Case 1 is labelled "" and duplicates are dropped. Only Case 1 when the code
    pack has no design cases."""
    from saengine.fem import loads as fl

    design_cases = fl.wind_design_cases()
    torsion = all(c in cases for c in fl.WIND_TORSION_CASES.values())

    def variants(case: str, sign: float) -> list[tuple[str, dict[str, float]]]:
        if design_cases is None:
            return [("", {case: sign})]
        out: list[tuple[str, dict[str, float]]] = []
        seen: set[tuple[tuple[str, float], ...]] = set()
        for label, factors in fl.wind_design_variants({case: sign}, design_cases, torsion):
            factors = {c: f for c, f in factors.items() if f and c in cases}
            key = tuple(sorted((c, round(f, 9)) for c, f in factors.items()))
            if not factors or key in seen:
                continue
            seen.add(key)
            out.append(("" if label == "Case 1" else label, factors))
        return out

    return variants


def case_reactions(
    out_dir: str | Path, nodes: Iterable[int] | None = None
) -> dict[str, dict[int, np.ndarray]]:
    """The support reactions ``[Fx, Fy, Fz, Mx, My, Mz]`` [N, N·m, global axes] of each static
    case of the results in ``out_dir``, by case code (D, SD, L, ...) and node id; only those of
    ``nodes`` when given (the other results are not read). Raises ``ValueError`` when there are
    no results."""
    from opensees_studio.services.result_store import load_manifest, load_node_reactions

    from saengine.fem.display import _code, _last

    try:
        manifest = load_manifest(out_dir)
    except (OSError, ValueError) as error:
        raise ValueError("there are no results; run the analysis first") from error
    by_case: dict[str, dict[int, np.ndarray]] = {}
    wanted = None if nodes is None else set(nodes)
    for entry in manifest["cases"]:
        reactions = load_node_reactions(entry, out_dir, wanted)
        if reactions is None:
            continue
        by_case[_code(entry["case_name"])] = {int(n): _last(reactions, n, 6) for n in reactions}
    return by_case


def column_action(
    reaction: np.ndarray, arm: float, axis_u: np.ndarray, axis_v: np.ndarray
) -> np.ndarray:
    """``[P, Cu, Cv]`` a column puts on its footing (see :data:`saengine.substructure.shallow.
    Loads`) from its support reaction ``[Fx, Fy, Fz, Mx, My, Mz]`` [N, N·m, global axes];
    ``arm`` [mm] from the footing's underside up to the column base, where the horizontal force
    acts."""
    force = -np.asarray(reaction[:3], dtype=float)
    moment = -np.asarray(reaction[3:], dtype=float) * 1e3
    fu, fv = float(force @ axis_u), float(force @ axis_v)
    mu, mv = float(moment @ axis_u), float(moment @ axis_v)
    return np.array([-float(force[2]), mu - arm * fv, mv + arm * fu])


def combine(per_case: dict[str, list[np.ndarray]], factors: dict[str, float]) -> list[np.ndarray]:
    """The factored sum of ``per_case`` lists of arrays (one array per column)."""
    first = next(iter(per_case.values()), [])
    count = len(first)
    width = len(first[0]) if count else 3
    return [
        sum((f * per_case[case][k] for case, f in factors.items()), np.zeros(width))
        for k in range(count)
    ]


def strength_combinations(
    settings: ProjectSettings, cases: set[str] | dict[str, Any]
) -> list[tuple[str, dict[str, float]]]:
    """The project's strength combinations whose cases were all analysed, each one-direction
    wind combination for the design wind load cases of BNBC 2020 Part 6 Figure 6.2.9 when the
    model has them (:func:`saengine.fem.combinations.wind_case_combinations`)."""
    from saengine.fem.combinations import (
        combination_factors,
        crane_combinations,
        wind_case_combinations,
    )

    result: list[tuple[str, dict[str, float]]] = []
    formed = wind_case_combinations(list(settings.combinations), set(cases))
    # The moving crane load cases on the foundations too (saengine.fem.cranes).
    with_cranes = crane_combinations(
        formed if formed is not None else list(settings.combinations), set(cases)
    )
    formed = with_cranes if with_cranes is not None else formed
    for combination in formed if formed is not None else settings.combinations:
        factors = combination_factors(combination, set(cases))
        if all(case in cases for case in factors):
            result.append((combination.name, factors))
    return result


def is_strength_level_wind(strength: list[tuple[str, dict[str, float]]]) -> bool:
    """Wind is nominal when a strength combination factors it above 1.0 (1.6W, BNBC 2.7.3)."""
    factors = [abs(f) for _, fs in strength for case, f in fs.items() if case[:1] == "W"]
    return bool(factors) and max(factors) <= 1.0 + 1e-9


def support_nodes(project: dict[str, Any]) -> dict[tuple[int, int, int], int]:
    """Fully restrained nodes of the analysis model, by position rounded to mm."""
    supports: dict[tuple[int, int, int], int] = {}
    for node in project.get("nodes", []):
        if any(node.get("restraint") or []):
            key = tuple(round(float(c) * 1000) for c in node["coords"][:3])
            supports[key] = int(node["id"])  # type: ignore[index]
    return supports


@dataclass
class Base:
    """A column or wall base standing on a foundation: its support nodes and their positions."""

    id: str
    element: ColumnElement | WallElement
    nodes: list[tuple[int, np.ndarray]]  # (node id, [x, y, z] mm)

    @property
    def level(self) -> float:
        return float(self.element.bottom)


@dataclass
class BaseLoads:
    """The support reactions of the column and wall bases of an analysed model, and the
    combinations to combine them with."""

    cases: dict[str, dict[int, np.ndarray]]  # case code -> node -> reaction [N, N·m]
    bases: dict[str, Base]  # column or wall id -> its support nodes
    strength: list[tuple[str, dict[str, float]]]
    service: list[tuple[str, dict[str, float]]]
    dead: dict[str, float]  # strength combination -> its dead-load factor
    strength_level_wind: bool
    unsupported: list[str] = field(default_factory=list)  # bases without a support node
    #: Per base: the factor on its floor live load cases (L, LP...), the live load reduction
    #: of the column it is (:func:`reduce_live_loads`); 1 when not reduced.
    live_factors: dict[str, float] = field(default_factory=dict)
    live_notes: dict[str, str] = field(default_factory=dict)

    def reaction(self, node: int, factors: dict[str, float]) -> np.ndarray:
        """The combined reaction of one support node [N, N·m]."""
        total = np.zeros(6)
        for case, factor in factors.items():
            total += factor * self.cases.get(case, {}).get(node, np.zeros(6))
        return total

    def resultant(self, base_id: str, factors: dict[str, float], about: Any) -> np.ndarray:
        """``[Fx, Fy, Fz, Mx, My, Mz]`` [N, N·mm] the base puts on its foundation under the
        combination ``factors``, the moment about the point ``about`` [x, y, z] mm: the support
        reactions reversed."""
        point = np.asarray(about, dtype=float)
        force, moment = np.zeros(3), np.zeros(3)
        for node, xyz in self.bases[base_id].nodes:
            r = -self.reaction(node, factors)
            force += r[:3]
            moment += r[3:] * 1e3 + np.cross(xyz - point, r[:3])
        return np.concatenate([force, moment])

    def max_axial(self, base_id: str, combinations: str = "strength") -> float:
        """The largest downward force [N] of a base under the strength (or ``"service"``)
        combinations; 0 when it is never in compression."""
        chosen = self.strength if combinations == "strength" else self.service
        base = self.bases[base_id]
        about = base.nodes[0][1]
        return max((float(-self.resultant(base_id, f, about)[2]) for _, f in chosen), default=0.0)


def base_loads(
    project: dict[str, Any], out_dir: str | Path, building: BuildingModel, settings: ProjectSettings
) -> BaseLoads:
    """The reactions of the column and wall bases of ``building`` that stand on supports of the
    analysis model ``project`` (``08 FEM/model.osmodel``) under the results in ``out_dir``.
    Raises ``ValueError`` when there are no results."""
    supports = support_nodes(project)
    cases = case_reactions(out_dir, supports.values())
    bases: dict[str, Base] = {}
    unsupported: list[str] = []
    for element in building.elements:
        if isinstance(element, ColumnElement):
            key = (round(element.position[0]), round(element.position[1]), round(element.bottom))
            if key in supports:
                bases[element.id] = Base(
                    element.id, element, [(supports[key], np.array(key, float))]
                )
            else:
                unsupported.append(element.id)
        elif isinstance(element, WallElement):
            start = np.array([*element.start, element.bottom], dtype=float)
            end = np.array([*element.end, element.bottom], dtype=float)
            along = end - start
            length = float(np.linalg.norm(along))
            nodes = []
            for key, node in supports.items():
                xyz = np.array(key, dtype=float)
                if abs(xyz[2] - element.bottom) > 1 or length <= 0:
                    continue
                t = float((xyz - start) @ along) / length**2
                off = float(np.linalg.norm(xyz - start - t * along))
                if -1e-6 <= t <= 1 + 1e-6 and off < 1:
                    nodes.append((node, xyz))
            if nodes:
                nodes.sort(key=lambda item: float((item[1] - start) @ along))
                bases[element.id] = Base(element.id, element, nodes)
            else:
                unsupported.append(element.id)
    strength = strength_combinations(settings, cases)
    level = is_strength_level_wind(strength)
    dead = {name: factors.get("D", factors.get("SD", 0.0)) for name, factors in strength}
    return BaseLoads(
        cases, bases, strength, service_combinations(cases, level), dead, level, unsupported
    )


def reduce_live_loads(loads: BaseLoads, building: BuildingModel, settings: ProjectSettings) -> None:
    """The floor live load of each column base reduced as in the column's design (the "normal
    live load" of the geotechnical design of shallow foundations): when Project Settings asks
    for live load reduction, by the code pack's rule (:mod:`saengine.design.live_reduction`)
    with the tributary area AT = the base's live reaction under L over the floors' live load
    L0, the floors at and above the column's top, KLL of an interior or an edge column. Fills
    ``loads.live_factors`` (under the code pack in force); walls are not reduced."""
    from saengine.design import live_reduction

    loads.live_factors.clear()
    loads.live_notes.clear()
    design = getattr(settings, "design", None)
    if not getattr(design, "liveLoadReduction", False) or "L" not in loads.cases:
        return
    try:
        scope = live_reduction.LiveScope.of(settings)
        table = live_reduction._table()
    except Exception:  # noqa: BLE001 - a pack without the rule reduces nothing
        return
    if scope.live <= 0:
        return
    for base_id, base in loads.bases.items():
        element = base.element
        if not isinstance(element, ColumnElement):
            continue
        live = -float(loads.resultant(base_id, {"L": 1.0}, base.nodes[0][1])[2])
        area = live / (scope.live * 1e3)
        if area <= 0:
            continue
        top = float(element.top)
        floors = sum(1 for s in building.stories if float(s.elevation) >= top - 1.0)
        interior = live_reduction._interior(element, building)
        kll = table.kll.interiorColumn if interior else table.kll.cornerColumnCantilever
        factor, why = live_reduction.reduction(kll, area, max(floors, 1), scope)
        if factor < 1.0:
            loads.live_factors[base_id] = factor
            loads.live_notes[base_id] = why
