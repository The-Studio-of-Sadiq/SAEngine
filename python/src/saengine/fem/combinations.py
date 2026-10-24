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
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

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
    "F": ("F",),
}
#: Cases a combination may name that a model need not have: the fluid case F exists only when
#: 07 MEP puts equipment contents in it, so a combination without its results is formed without
#: it (a model without F has no fluid loads). T is not optional: its combinations need its case.
OPTIONAL_CASES = frozenset({"F"})
_DOF = ["Ux", "Uy", "Uz", "Rx", "Ry", "Rz"]
_FORCES = ["Fx", "Fy", "Fz", "Mx", "My", "Mz"]
_END_FORCES = ["N", "Vy", "Vz", "T", "My", "Mz"]


def combination_factors(
    combination: LoadCombination, present: set[str] | frozenset[str] | None = None
) -> dict[str, float]:
    """``{case: factor}`` of a combination. With ``present`` (the cases that have results), the
    optional cases (:data:`OPTIONAL_CASES`) without results are left out."""
    factors: dict[str, float] = {}
    for field, cases in _FACTOR_CASES.items():
        value = getattr(combination, field)
        if value:
            for case in cases:
                if present is not None and case in OPTIONAL_CASES and case not in present:
                    continue
                factors[case] = value
    return factors


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
                "warnings": [],
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
