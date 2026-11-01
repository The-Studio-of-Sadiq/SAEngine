"""Load combinations of the analysis results (the project settings' combinations).

The analysis model runs each load case once (OpenSees Studio has no combination object). The
model is linear elastic, so a combination is exactly the factored sum of its cases' results:
displacements, reactions and element end forces. The dead load factor applies to the dead (D)
and superimposed dead (SD) cases.

A design combination (:class:`DesignCombination`) may also name envelope parts: the response
spectrum results, which have no sign (:mod:`saengine.fem.seismic_design`). Its value at an
item is ``S ± E``, S the factored static cases and E the factored peaks; :func:`variants`
gives its sign patterns. Combinations without envelope parts evaluate exactly as before.
"""

from __future__ import annotations

import dataclasses
import itertools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import Field

from saengine.fem import tension_only as to
from saengine.library.settings import LoadCombination, ProjectSettings

_FACTOR_CASES = {
    "D": ("D", "SD"),
    "L": ("L",),
    "Lr": ("Lr",),
    "WX": ("WX",),
    "WY": ("WY",),
    "EX": ("EX",),
    "EY": ("EY",),
    "T": ("T",),
    "ST": ("ST",),
    "F": ("F",),
    "H": ("H",),
    "EXP": ("EXP",),
    "EXN": ("EXN",),
    "EYP": ("EYP",),
    "EYN": ("EYN",),
    "WTX": ("WTX",),
    "WTY": ("WTY",),
}
#: Cases a combination may name that a model need not have: the fluid case F exists only when
#: 07 MEP puts equipment contents in it, so a combination without its results is formed without
#: it (a model without F has no fluid loads). So is the earth pressure case H (only a model with
#: basement walls has it). T is not optional: its combinations need its case.
OPTIONAL_CASES = frozenset({"F", "H"})
_DOF = ["Ux", "Uy", "Uz", "Rx", "Ry", "Rz"]
_FORCES = ["Fx", "Fy", "Fz", "Mx", "My", "Mz"]
_END_FORCES = ["N", "Vy", "Vz", "T", "My", "Mz"]


# ─────────────────────────────── the code pack's combination rows ───────────────────────────────
#
# The code pack (``combinations.json``) lists its combinations by category as rows of
# ``{id, name, factors: {kind: factor}, source, note}``; the kinds are D (with SD), L, Lr, F, H,
# T, R, W and E. The functions below form the program's combinations from those rows, whatever
# the code: W and E expand to the plan directions and signs, T to a rise and a fall, the
# optional cases the model lacks are left out, "Lr or R" forms a twin on R, and the pack's
# permitted factor changes (``exceptions``) apply by row id. Other tracks add rows to the pack,
# never code here.

#: Factor kinds that act in a plan direction: each expands to +X, -X, +Y and -Y.
DIRECTIONAL = ("W", "E")
#: The analysis cases each factor kind of a pack row stands for (W and E expand by direction).
KIND_CASES = {"D": ("D", "SD")}


def _pack() -> Any:
    from saengine.codes import context as code_context

    return code_context.pack_table("combinations")


def _token(value: float, kind: str) -> str:
    return (
        f"{value:.1f}{kind}" if abs(value * 10 - round(value * 10)) < 1e-9 else f"{value:g}{kind}"
    )


def apply_exception(row: Any, exception: Any) -> Any:
    """A copy of a pack row with ``exception``'s factor (``case`` at ``to``) when the row's id is
    one of its rows, its name updated (``1.0L`` -> ``0.5L``); else the row itself."""
    old = row.factors.get(exception.case)
    if row.id not in exception.rows or old is None or old == exception.to:
        return row
    name = row.name.replace(_token(old, exception.case), _token(exception.to, exception.case), 1)
    if name == row.name:
        name = f"{row.name} ({exception.case} × {exception.to:g})"
    return row.model_copy(
        update={"name": name, "factors": {**row.factors, exception.case: exception.to}}
    )


def exception_applies(
    exception: Any,
    live_loads: list[tuple[str, float]] | None = None,
    directionality: float | None = None,
    material: str | None = None,
) -> tuple[bool, str]:
    """(whether a pack exception's conditions hold, why not): ``live_loads`` the floor area
    loads ``(use, L0)``, ``directionality`` the wind's directionality factor, ``material`` the
    frame's material category."""
    if exception.liveMax is not None:
        if live_loads is None:
            return False, "the area loads are not known"
        heavy = [use for use, live in live_loads if live > exception.liveMax + 1e-9]
        if heavy:
            return False, f"a live load is over {exception.liveMax:g} kN/m² ({', '.join(heavy)})"
        excluded = sorted({use for use, _ in live_loads if use in exception.excludedUses})
        if excluded:
            return False, f"not for {', '.join(excluded)}"
    if exception.directionality is not None and (
        directionality is None or abs(directionality - exception.directionality) > 1e-9
    ):
        return False, f"the wind is reduced by a directionality factor of {directionality}"
    if exception.material is not None and material != exception.material:
        return False, f"only for {exception.material} frames"
    return True, ""


def expand_rows(rows: list[Any]) -> list[tuple[str, dict[str, float], Any]]:
    """``(name, {kind: factor}, row)`` of pack rows, a row with W or E once per plan direction
    and sign: ``1.2D + 1.6WX + ...``, ``1.2D + 1.6(-WX) + ...`` (kinds W, E become WX, WY, EX,
    EY; the other kinds stay)."""
    out: list[tuple[str, dict[str, float], Any]] = []
    for row in rows:
        factors = dict(row.factors)
        lateral = next((kind for kind in DIRECTIONAL if kind in factors), None)
        if lateral is None:
            out.append((row.name, factors, row))
            continue
        base = {k: v for k, v in factors.items() if k != lateral}
        for axis in ("X", "Y"):
            for sign in (1, -1):
                label = (
                    row.name.replace(lateral, f"{lateral}{axis}", 1)
                    if sign > 0
                    else row.name.replace(lateral, f"(-{lateral}{axis})", 1)
                )
                out.append((label, {**base, f"{lateral}{axis}": sign * factors[lateral]}, row))
    return out


def allowable_combinations(
    present: set[str] | frozenset[str] | None = None,
) -> list[tuple[str, dict[str, float]]]:
    """The code pack's allowable stress combinations (``combinations.allowable``) as ``(name,
    {analysis case: factor})``: wind and earthquake in ±X and ±Y, D on D and SD, T as a rise
    and a fall. With ``present`` (the cases that have results), the pack's optional cases
    (F, H, T, R) the model lacks are left out of a combination (the combination with a load
    not acting, as the code asks), and each combination with Lr is also formed on its
    alternate R when the model has it."""
    table = _pack()
    optional = set(getattr(table, "optionalCases", ()) or ())
    out: list[tuple[str, dict[str, float]]] = []
    for name, factors, _row in expand_rows(list(getattr(table, "allowable", None) or [])):
        cases: dict[str, float] = {}
        for kind, value in factors.items():
            if present is not None and kind in optional and kind not in present:
                continue
            for case in KIND_CASES.get(kind, (kind,)):
                cases[case] = value
        temperature = cases.pop("T", None)
        signs = [(name, cases)]
        if temperature:
            signs = [
                (f"{name} + {_token(temperature, 'T')}", {**cases, "T": temperature}),
                (f"{name} − {_token(temperature, 'T')}", {**cases, "T": -temperature}),
            ]
        for label, combination in signs:
            out.append((label, combination))
            for case, alternates in (getattr(table, "alternates", None) or {}).items():
                if not combination.get(case):
                    continue
                for alternate in alternates:
                    if present is not None and alternate not in present:
                        continue
                    twin = {k: v for k, v in combination.items() if k != case}
                    twin[alternate] = combination[case]
                    out.append((f"{label} [{case} → {alternate}]", twin))
    return out


def allowable_stress_increase(row_id: str | None, overstrength: bool) -> float:
    """The allowable stress increase of allowable stress combination ``row_id`` (the pack row's
    id): the pack's ``allowableStressIncrease`` when the combination takes the overstrength
    seismic load Em (``overstrength``) and the row is one of ``allowableStressIncreaseRows``,
    else 1.0 (no increase, as the code's general rule is)."""
    table = _pack()
    increase = getattr(table, "allowableStressIncrease", None)
    if not increase or not overstrength or row_id not in table.allowableStressIncreaseRows:
        return 1.0
    return float(increase)


def uplift_dead_factor() -> float | None:
    """The factor on the dead load that resists uplift in allowable stress design (the pack's
    ``upliftDeadFactor``), None when the pack sets none."""
    return getattr(_pack(), "upliftDeadFactor", None)


#: The name prefix of the cantilever uplift combination (:func:`cantilever_uplift`); the design
#: applies it to the members with a free end only.
CANTILEVER_PREFIX = "Cantilever uplift: "


def cantilever_uplift(category: str | None) -> LoadCombination | None:
    """The code pack's net upward force on horizontal cantilevers (``cantileverUplift``: a
    share of the dead load, in the Seismic Design Categories it lists) as a combination of the
    dead load acting upward, ``"Cantilever uplift: −0.2D"``; None when the pack has none or
    the category is not one of its."""
    rule = getattr(_pack(), "cantileverUplift", None)
    if rule is None or category not in rule.categories:
        return None
    return LoadCombination(
        name=f"{CANTILEVER_PREFIX}−{rule.factor:g}D", D=-rule.factor, F=0.0, H=0.0
    )


def alternate_combinations(
    combinations: list[LoadCombination], present: set[str] | frozenset[str]
) -> list[LoadCombination] | None:
    """The combinations followed by, for each with a case that has an alternate in the code
    pack (``alternates``: "Lr or R") the model has, a twin with the alternate at the same
    factor, named "<name> [Lr → R]". None when the model has no alternate case."""
    alternates = getattr(_pack(), "alternates", None) or {}
    pairs = [(case, alt) for case, alts in alternates.items() for alt in alts if alt in present]
    if not pairs:
        return None
    out = list(combinations)
    for combination in combinations:
        for case, alternate in pairs:
            value = getattr(combination, case, 0) or 0
            if not value:
                continue
            data = combination.model_dump(by_alias=True)
            out.append(
                CaseCombination(
                    **{
                        **data,
                        case: 0.0,
                        "cases": {**(data.get("cases") or {}), alternate: value},
                        "name": f"{combination.name} [{case} → {alternate}]",
                    }
                )
            )
    return out


def combination_factors(
    combination: LoadCombination, present: set[str] | frozenset[str] | None = None
) -> dict[str, float]:
    """``{case: factor}`` of a combination. With ``present`` (the cases that have results), the
    optional cases (:data:`OPTIONAL_CASES`) without results are left out."""
    factors: dict[str, float] = {}
    for field, cases in _FACTOR_CASES.items():
        value = getattr(combination, field, 0)
        if value:
            for case in cases:
                if present is not None and case in OPTIONAL_CASES and case not in present:
                    continue
                factors[case] = value
    # Cases a formed combination adds by name (CaseCombination: the torsional wind cases, the
    # live load arrangements), never stored in the settings.
    for case, value in (getattr(combination, "cases", None) or {}).items():
        if value:
            factors[case] = factors.get(case, 0.0) + value
    return factors


#: A combination's name that is just its factors (``1.2D + 1.0EX + 1.0L``).
_FACTOR_NAME = re.compile(
    r"^\s*[-+]?\s*\d*\.?\d*\s*[A-Za-z]+(\s*[-+]\s*\d*\.?\d*\s*[A-Za-z]+)*\s*$"
)


def combination_label(
    combination: LoadCombination, present: set[str] | frozenset[str] | None = None
) -> str:
    """The name a combination is shown by: a name that is only factors is written out from
    the factors it applies (the D factor applies to SD too: ``1.2D + 1.2SD + 1.0L``); any other
    name is kept. One label on every surface (the 3D view, the tables, the member window)."""
    name = combination.name
    if not _FACTOR_NAME.match(name) or not re.search(r"\d", name):
        return name
    factors = combination_factors(combination, present)
    if not factors:
        return name
    terms = []
    for case, value in factors.items():
        magnitude = f"{abs(value):.2f}".rstrip("0")
        magnitude = magnitude + "0" if magnitude.endswith(".") else magnitude
        sign = "−" if value < 0 else "+"
        terms.append((sign, f"{magnitude}{case}"))
    text = ("−" if terms[0][0] == "−" else "") + terms[0][1]
    return text + "".join(f" {sign} {term}" for sign, term in terms[1:])


class CaseCombination(LoadCombination):
    """A project combination with factors on further analysis cases by name (``cases``: the
    torsional wind cases WTX, WTY of :func:`wind_case_combinations`, the live load arrangements
    LP1, LP2 ... of :func:`pattern_live_combinations`). Formed for the design, never stored."""

    cases: dict[str, float] = Field(default_factory=dict)


def wind_case_combinations(
    combinations: list[LoadCombination], present: set[str] | frozenset[str]
) -> list[LoadCombination] | None:
    """The combinations with each one-direction wind combination expanded into the design wind
    load cases of BNBC 2020 Part 6 Sec 2.4.11.3 and Figure 6.2.9 (Case 1 as given, Cases 2-4
    with the shares of the code pack's ``wind.designCases`` and the torsional cases WTX, WTY when
    the model has them), named "<name> [Case k ...]". None when the code pack has no design
    cases or the model has neither wind case."""
    from saengine.fem import loads as fl

    cases = fl.wind_design_cases()
    if cases is None or not ({"WX", "WY"} & set(present)):
        return None
    torsion = all(c in present for c in fl.WIND_TORSION_CASES.values())
    out: list[LoadCombination] = []
    for combination in combinations:
        variants = fl.wind_design_variants(
            {"WX": combination.WX, "WY": combination.WY}, cases, torsion=torsion
        )
        if len(variants) == 1 and variants[0][0] == "":
            out.append(combination)
            continue
        # Clad structures: the opposite direction's cases, the pressure variants and ±WI.
        variants = fl.resolve_wind_cases(variants, present)
        data = combination.model_dump(by_alias=True)
        seen: set[tuple[tuple[str, float], ...]] = set()
        for label, factors in variants:
            key = tuple(sorted((k, round(v, 9)) for k, v in factors.items()))
            if key in seen:
                continue
            seen.add(key)
            if label == "Case 1" and set(factors) <= {"WX", "WY"}:
                out.append(combination)
                continue
            extra = {k: v for k, v in factors.items() if k not in ("WX", "WY")}
            out.append(
                CaseCombination(
                    **{
                        **data,
                        "WX": factors.get("WX", 0.0),
                        "WY": factors.get("WY", 0.0),
                        "cases": {**(data.get("cases") or {}), **extra},
                        "name": f"{combination.name} [{label}]",
                    }
                )
            )
    return out


def pattern_live_combinations(
    combinations: list[LoadCombination], present: set[str] | frozenset[str]
) -> list[LoadCombination] | None:
    """The project's combinations followed by, for each gravity combination with live load
    (no wind or earthquake), one per live load arrangement the model has (cases LP1, LP2 ...,
    :mod:`saengine.fem.pattern_live`, BNBC 2020 Part 6 Sec 6.1.12.2) with the live case L
    replaced by the arrangement's case at the same factor, named "<name> [LPk]". None when the
    model has no arrangements."""
    arrangements = sorted(
        (c for c in present if c.startswith("LP") and c[2:].isdigit()), key=lambda c: int(c[2:])
    )
    if not arrangements:
        return None
    out = list(combinations)
    for combination in combinations:
        if combination.L <= 0:
            continue
        # Lateral: wind (W*), earthquake (E*) or response spectrum (R*) cases.
        if any(case[:1] in "WER" for case in combination_factors(combination)):
            continue
        data = combination.model_dump(by_alias=True)
        for case in arrangements:
            out.append(
                CaseCombination(
                    **{
                        **data,
                        "L": 0.0,
                        "cases": {**(data.get("cases") or {}), case: combination.L},
                        "name": f"{combination.name} [{case}]",
                    }
                )
            )
    return out


#: A moving crane load case (:func:`saengine.fem.cranes.crane_load_cases`): crane, part (V
#: vertical, T transverse, B longitudinal), position along the runway, trolley side.
CRANE_CASE = re.compile(r"^C(\d+)([VTB])(\d+)([ab])$")


def crane_combinations(
    combinations: list[LoadCombination], present: set[str] | frozenset[str]
) -> list[LoadCombination] | None:
    """The combinations followed by their crane variants: for each combination with the factor
    kind the code pack's crane rule names (``cranes.combination.factorOf``, the live load),
    each crane position and trolley side, and each set of parts the rule lets act together
    (``gravity`` for rows without wind or earthquake, ``lateral`` for rows with them), one
    combination with the crane cases at that factor, the transverse and longitudinal parts
    both ways, named "<name> [C1 3a V+T]". None when the model has no crane cases."""
    from saengine.codes import context as code_context

    found: dict[tuple[str, str, str], set[str]] = {}
    for case in present:
        match = CRANE_CASE.match(case)
        if match:
            crane, part, position, side = match.groups()
            found.setdefault((crane, position, side), set()).add(part)
    if not found:
        return None
    rule = getattr(code_context.table("cranes"), "combination", None)
    if rule is None:
        return None
    out = list(combinations)
    keys = sorted(found, key=lambda k: (int(k[0]), int(k[1]), k[2]))
    for combination in combinations:
        factor = float(getattr(combination, rule.factorOf, 0) or 0)
        if factor <= 0:
            continue
        lateral = any(case[:1] in "WE" for case in combination_factors(combination))
        sets = rule.lateral if lateral else rule.gravity
        data = combination.model_dump(by_alias=True)
        for crane, position, side in keys:
            parts = found[(crane, position, side)]
            for group in sets:
                if not set(group) <= parts:
                    continue
                signed = [p for p in group if p != "V"]
                for signs in itertools.product((1, -1), repeat=len(signed)):
                    sign_of = dict(zip(signed, signs, strict=True))
                    cases = {
                        f"C{crane}{p}{position}{side}": factor * sign_of.get(p, 1) for p in group
                    }
                    label = "+".join(p if sign_of.get(p, 1) > 0 else f"(-{p})" for p in group)
                    out.append(
                        CaseCombination(
                            **{
                                **data,
                                "cases": {**(data.get("cases") or {}), **cases},
                                "name": f"{combination.name} [C{crane} {position}{side} {label}]",
                            }
                        )
                    )
    return out


#: The eccentric static earthquake cases (``analysis.accidentalEccentricity``,
#: :data:`saengine.fem.derive.ECCENTRIC_CASES`) of each static case.
ECCENTRIC_OF = {"EX": ("EXP", "EXN"), "EY": ("EYP", "EYN")}


class EccentricCombination(LoadCombination):
    """A project combination with its earthquake on an eccentric static case (formed by
    :func:`eccentric_combinations`, never stored)."""

    EXP: float = 0
    EXN: float = 0
    EYP: float = 0
    EYN: float = 0


def model_cases(project: dict[str, Any]) -> set[str]:
    """The case codes of an analysis model's analyses ("EX", "EXP", ...)."""
    return {str(a.get("name", "")).split(":")[0].strip() for a in project.get("analyses", [])}


def eccentric_combinations(
    combinations: list[LoadCombination], present: set[str]
) -> list[LoadCombination] | None:
    """The combinations with each earthquake case replaced by its two eccentric cases (BNBC
    2020 Part 6 Sec 2.5.7.6.2: the masses shifted ±5 % across the force), when the model has
    them (``present``); a combination with EX becomes "... [+e]" on EXP and "... [-e]" on EXN
    (likewise EY). None when the model has no eccentric cases."""
    if not all(c in present for pair in ECCENTRIC_OF.values() for c in pair):
        return None
    out: list[LoadCombination] = []
    for combination in combinations:
        lateral = [case for case in ECCENTRIC_OF if getattr(combination, case, 0)]
        if not lateral:
            out.append(combination)
            continue
        data = combination.model_dump(by_alias=True)
        for sign, label in ((0, "+e"), (1, "-e")):
            update = {case: 0.0 for case in lateral}
            update.update(
                {ECCENTRIC_OF[case][sign]: getattr(combination, case) for case in lateral}
            )
            out.append(
                EccentricCombination(**{**data, **update, "name": f"{combination.name} [{label}]"})
            )
    return out


#: The static cases a project combination names for the earthquake: replaced by the response
#: spectrum combinations when the design uses them (:func:`design_combinations`).
EARTHQUAKE_CASES = ("EX", "EY")


@dataclass(frozen=True)
class DesignCombination:
    """A combination the design evaluates: factors on static cases (as
    :func:`combination_factors` gives them) plus, for the response spectrum, factors on
    envelope parts (``RX``, ``RY``, ``AX``, ``AY`` of :class:`saengine.fem.seismic_design.
    SeismicForces`, peaks ≥ 0) that act with ±: the value is ``S ± Σ f·E``
    (:func:`evaluate`, :func:`variants`). A combination without envelope parts is exactly a
    project combination, as before."""

    name: str
    factors: dict[str, float]
    envelope: dict[str, float] = dataclasses.field(default_factory=dict)
    clause: str = ""

    @property
    def has_envelope(self) -> bool:
        return any(self.envelope.values())

    @classmethod
    def of(
        cls, combination: LoadCombination, present: set[str] | frozenset[str] | None = None
    ) -> DesignCombination:
        """A project combination (static cases only)."""
        return cls(combination.name, combination_factors(combination, present))

    @classmethod
    def from_json(
        cls, data: dict[str, Any], present: set[str] | frozenset[str] | None = None
    ) -> DesignCombination:
        """An entry of :func:`saengine.fem.seismic_design.seismic_design`'s ``combinations``:
        ``{"name", "loads": {LoadCombination factors}, "envelope": {part: factor}, "clause"}``."""
        loads = LoadCombination(name=data["name"], **data.get("loads", {}))
        return cls(
            data["name"],
            combination_factors(loads, present),
            {k: float(v) for k, v in data.get("envelope", {}).items() if v},
            str(data.get("clause", "")),
        )


def evaluate(
    combination: DesignCombination,
    static: Mapping[str, np.ndarray],
    envelope: Mapping[str, np.ndarray] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """``(S, E)`` of a combination at one item (a section's stations, an element's end forces,
    a support, a shell's points): ``S = Σ f·static[case]`` and ``E = Σ |f|·envelope[part]``
    (≥ 0; zeros without envelope parts). The design value is ``S ± E``. Raises ``KeyError`` for
    a case or part without values."""
    first = next(iter(static.values()), None)
    if first is None and envelope:
        first = next(iter(envelope.values()))
    zero = np.zeros_like(np.asarray(first, dtype=float)) if first is not None else np.zeros(1)
    s = sum((f * np.asarray(static[c], dtype=float) for c, f in combination.factors.items()), zero)
    e = zero.copy()
    for part, f in combination.envelope.items():
        if f:
            if envelope is None or part not in envelope:
                raise KeyError(part)
            e = e + abs(f) * np.abs(np.asarray(envelope[part], dtype=float))
    return np.asarray(s, dtype=float), np.asarray(e, dtype=float)


#: Sign groups of the envelope, per kind of item: the index of the group each component's sign
#: follows. ``frame`` (N Vy Vz T My Mz): N, then My with Vz and Mz with Vy, T with N;
#: ``ends`` (both ends of an element's 12 end forces) likewise; ``reaction`` (Fx Fy Fz Mx My
#: Mz): Fz, then Mx with Fy and My with Fx, Mz with Fz; ``shell`` (N11 N22 N12 M11 M22 M12 Q13
#: Q23): membrane forces, then M11 with M12 and Q13, M22 with Q23.
SIGN_GROUPS: dict[str, tuple[int, ...]] = {
    "frame": (0, 2, 1, 0, 1, 2),
    "ends": (0, 2, 1, 0, 1, 2) * 2,
    "reaction": (2, 1, 0, 1, 2, 0),
    "shell": (0, 0, 0, 1, 2, 1, 1, 2),
}
_GROUP_NAMES = {
    "frame": ("N", "My", "Mz"),
    "ends": ("N", "My", "Mz"),
    "reaction": ("Fz", "Mx", "My"),
    "shell": ("N", "M11", "M22"),
}


def sign_patterns(kind: str = "frame", signs: str = "corners") -> list[tuple[str, np.ndarray]]:
    """``(label, sign vector)`` of the envelope's sign patterns for a kind of item
    (:data:`SIGN_GROUPS`): "corners" gives 8 (every group + or −), "plusMinus" 2 (+E, −E)."""
    groups = SIGN_GROUPS[kind]
    names = _GROUP_NAMES[kind]
    if signs == "plusMinus":
        choices = [(1, 1, 1), (-1, -1, -1)]
        return [
            ("+E" if c[0] > 0 else "−E", np.array([c[g] for g in groups], dtype=float))
            for c in choices
        ]
    out = []
    for c in itertools.product((1, -1), repeat=3):
        label = " ".join(f"{'+' if s > 0 else '−'}{n}" for s, n in zip(c, names, strict=True))
        out.append((label, np.array([c[g] for g in groups], dtype=float)))
    return out


def variants(
    combination: DesignCombination,
    static: Mapping[str, np.ndarray],
    envelope: Mapping[str, np.ndarray] | None = None,
    kind: str = "frame",
    signs: str = "corners",
) -> list[tuple[str, np.ndarray]]:
    """The design values of a combination at one item: ``[(name, S)]`` without envelope parts,
    else ``[(f"{name} [{label}]", S + sign·E)]`` for each sign pattern (:func:`sign_patterns`;
    the sign vector applies along the last axis). The names, and so their order, are the same
    for every item of a kind, so a design can index them like the combinations."""
    s, e = evaluate(combination, static, envelope)
    if not combination.has_envelope:
        return [(combination.name, s)]
    return [
        (f"{combination.name} [{label}]", s + sign * e)
        for label, sign in sign_patterns(kind, signs)
    ]


def design_combinations(
    settings: ProjectSettings,
    present: set[str] | frozenset[str] | None = None,
    seismic: dict[str, Any] | None = None,
) -> list[DesignCombination]:
    """The combinations the design checks: the project's, and with a response spectrum design
    (``seismic``: :func:`saengine.fem.seismic_design.seismic_design`'s summary, available), the
    project's without EX or EY followed by the response spectrum combinations."""
    use_rs = bool(seismic and seismic.get("available") and seismic.get("combinations"))
    result = [
        DesignCombination.of(c, present)
        for c in settings.combinations
        if not (use_rs and any(getattr(c, case) for case in EARTHQUAKE_CASES))
    ]
    if use_rs:
        assert seismic is not None
        result += [DesignCombination.from_json(c, present) for c in seismic["combinations"]]
    return result


def _table(
    name: str, title: str, columns: list[str], rows: list[list[Any]], notes: list[str] | None = None
) -> dict[str, Any]:
    return {"name": name, "title": title, "columns": columns, "rows": rows, "notes": notes or []}


def combination_results(
    out_dir: str | Path,
    project: dict[str, Any],
    settings: ProjectSettings,
    thermal: dict[str, Any] | None = None,
    seismic: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Result entries (like the run's cases) for each combination, then the force envelope.

    ``thermal``: the temperature case's fixed-end forces (``08 FEM/thermal.json``,
    :func:`saengine.fem.thermal.load_corrections`), added to its end forces.
    ``seismic``: a response spectrum design summary
    (:func:`saengine.fem.seismic_design.seismic_design`); its combinations follow, each as an
    ``"Envelope"`` entry of the end forces and reactions, min and max (``S ∓ E``), when its
    modal-force run is there. Without it the entries are as before.
    Units follow the model: m, N, N·m. Values are rounded for display.
    """
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import StaticResults

    from saengine.fem.thermal import end_force_corrections

    manifest = load_manifest(out_dir)
    by_case: dict[str, Any] = {}
    for entry in manifest["cases"]:
        code = str(entry["case_name"]).split(":")[0]
        results = load_results(entry, out_dir)
        if isinstance(results, StaticResults):
            by_case[code] = results
    names = {e["id"]: e["name"] for e in project.get("elements", [])}

    def last(group: dict[int, Any], key: int, width: int) -> np.ndarray:
        value = np.zeros(width)
        rows = group.get(key)
        if rows is not None and len(rows):
            row = np.asarray(rows[-1], dtype=float)[:width]
            value[: len(row)] = row
        return value

    def frame_like(element: int) -> bool:
        """Not a pinned end's link (``<member>/pin``, fem.derive): its spring forces are not
        member end forces."""
        return not str(names.get(element, "")).split("#")[0].endswith("/pin")

    # Tension-only members (saengine.fem.tension_only): their axial force per case.
    releases = to.release_cases(project)
    ids = {name: e for e, name in names.items()}
    released_names = set(releases.values())
    axial = {
        code: {
            name: to.axial_force(last(results.element_forces, ids[name], 12))
            for name in released_names
            if name in ids
        }
        for code, results in by_case.items()
    }

    def release_of(factors: dict[str, float]) -> to.Release:
        return to.release_factors(factors, axial, releases) if releases else to.Release()

    entries: list[dict[str, Any]] = []
    envelope: dict[tuple[int, int], list[float]] = {}
    for number, combination in enumerate(settings.combinations, start=1):
        factors = combination_factors(combination, set(by_case))
        missing = [case for case in factors if case not in by_case]
        if missing:
            entries.append(
                {
                    "caseId": 1000 + number,
                    "caseName": combination.name,
                    "resultType": "Combination",
                    "earlyStop": False,
                    "warnings": [
                        f"not formed: case {', '.join(missing)} has no results (run it first)"
                    ],
                    "tables": [],
                }
            )
            continue
        release = release_of(factors)
        factors = {**factors, **release.factors}
        nodes = sorted({n for case in factors for n in by_case[case].node_disp})
        supports = sorted({n for case in factors for n in by_case[case].node_reaction})
        elements = sorted(
            {e for case in factors for e in by_case[case].element_forces if frame_like(e)}
        )
        disp = {
            n: sum(f * last(by_case[c].node_disp, n, 6) for c, f in factors.items()) for n in nodes
        }
        react = {
            n: sum(f * last(by_case[c].node_reaction, n, 6) for c, f in factors.items())
            for n in supports
        }
        added = {c: end_force_corrections(thermal, c) for c in factors}
        forces = {
            e: sum(
                f * (last(by_case[c].element_forces, e, 12) + added[c].get(e, 0.0))
                for c, f in factors.items()
            )
            for e in elements
        }
        for e in elements:
            if names.get(e) in release.slack:
                forces[e] = np.zeros(12)  # a released tension-only member carries nothing
        total = sum(react.values(), np.zeros(6))
        tables = [
            _table(
                "Reactions",
                "Reactions (N, N·m)",
                ["Node", *_FORCES],
                [[n, *np.round(v, 1).tolist()] for n, v in react.items()]
                + [["Total", *np.round(total, 1).tolist()]],
            ),
            _table(
                "Displacements",
                "Displacements (m, rad)",
                ["Node", *_DOF],
                [[n, *np.round(v, 6).tolist()] for n, v in disp.items()],
            ),
            _table(
                "Element forces",
                "Element end forces (N, N·m), local axes",
                ["Element", "End", *_END_FORCES],
                [
                    [names.get(e, e), end, *np.round(v[6 * k : 6 * k + 6], 1).tolist()]
                    for e, v in forces.items()
                    for k, end in enumerate(("i", "j"))
                ],
            ),
        ]
        for e, v in forces.items():
            for k in range(12):
                lo_hi = envelope.setdefault((e, k), [float("inf"), float("-inf")])
                lo_hi[0], lo_hi[1] = min(lo_hi[0], float(v[k])), max(lo_hi[1], float(v[k]))
        entries.append(
            {
                "caseId": 1000 + number,
                "caseName": combination.name,
                "resultType": "Combination",
                "earlyStop": False,
                "warnings": release.warnings
                + (
                    [f"tension-only members released: {', '.join(sorted(release.members))}"]
                    if release.members
                    else []
                ),
                "tables": tables,
            }
        )

    if envelope:
        rows = [
            [names.get(e, e), "i" if k < 6 else "j", _END_FORCES[k % 6], round(lo, 1), round(hi, 1)]
            for (e, k), (lo, hi) in sorted(envelope.items())
        ]
        entries.append(
            {
                "caseId": 2000,
                "caseName": "Envelope of all combinations",
                "resultType": "Envelope",
                "earlyStop": False,
                "warnings": [],
                "tables": [
                    _table(
                        "Envelope",
                        "Element end forces, min and max over the combinations (N, N·m)",
                        ["Element", "End", "Force", "Min", "Max"],
                        rows,
                    )
                ],
            }
        )
    if seismic and seismic.get("available"):
        entries += _seismic_entries(out_dir, project, seismic, by_case, names, last)
    return entries


def _seismic_entries(
    out_dir: str | Path,
    project: dict[str, Any],
    seismic: dict[str, Any],
    by_case: dict[str, Any],
    names: dict[int, Any],
    last: Any,
) -> list[dict[str, Any]]:
    """The response spectrum design combinations as min/max entries (``S ∓ E``)."""
    from saengine.fem.seismic_design import load_seismic_forces

    forces = load_seismic_forces(out_dir)
    if forces is None:
        return []
    entries = []
    elements = sorted(
        {
            e
            for r in by_case.values()
            for e in r.element_forces
            if not str(names.get(e, "")).split("#")[0].endswith("/pin")
        }
    )
    supports = sorted({n for r in by_case.values() for n in r.node_reaction})
    for number, data in enumerate(seismic.get("combinations", []), start=1):
        combination = DesignCombination.from_json(data, set(by_case))
        missing = [c for c in combination.factors if c not in by_case]
        if missing:
            continue
        element_rows, reaction_rows = [], []
        for e in elements:
            s, env = evaluate(
                combination,
                {c: last(by_case[c].element_forces, e, 12) for c in combination.factors},
                forces.end_forces(e),
            )
            for k in range(12):
                element_rows.append(
                    [
                        names.get(e, e),
                        "i" if k < 6 else "j",
                        _END_FORCES[k % 6],
                        round(float(s[k] - env[k]), 1),
                        round(float(s[k] + env[k]), 1),
                    ]
                )
        for n in supports:
            s, env = evaluate(
                combination,
                {c: last(by_case[c].node_reaction, n, 6) for c in combination.factors},
                forces.reaction(n),
            )
            reaction_rows.append(
                [n, *np.round(s - env, 1).tolist(), *np.round(s + env, 1).tolist()]
            )
        entries.append(
            {
                "caseId": 3000 + number,
                "caseName": combination.name,
                "resultType": "Envelope",
                "earlyStop": False,
                "warnings": [],
                "tables": [
                    _table(
                        "Element forces",
                        "Element end forces, S − E and S + E (N, N·m), local axes",
                        ["Element", "End", "Force", "Min", "Max"],
                        element_rows,
                        [combination.clause] if combination.clause else [],
                    ),
                    _table(
                        "Reactions",
                        "Reactions, S − E and S + E (N, N·m)",
                        ["Node", *(f"{f} min" for f in _FORCES), *(f"{f} max" for f in _FORCES)],
                        reaction_rows,
                    ),
                ],
            }
        )
    return entries


def settings_beside(project_file: str | Path) -> ProjectSettings | None:
    """The project settings of the SAEngine project an analysis model belongs to, if any."""
    root = Path(project_file).resolve().parent.parent
    path = root / "02 Project Settings" / "project-settings.json"
    try:
        return ProjectSettings.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
