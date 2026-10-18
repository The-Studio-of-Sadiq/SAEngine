"""Load combinations of the analysis results (the project settings' combinations).

The analysis model runs each load case once (OpenSees Studio has no combination object). The
model is linear elastic, so a combination is exactly the factored sum of its cases' results:
displacements, reactions and element end forces. The dead load factor applies to the dead (D)
and superimposed dead (SD) cases.
"""

from __future__ import annotations

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


def _table(
    name: str, title: str, columns: list[str], rows: list[list[Any]], notes: list[str] | None = None
) -> dict[str, Any]:
    return {"name": name, "title": title, "columns": columns, "rows": rows, "notes": notes or []}


def combination_results(
    out_dir: str | Path,
    project: dict[str, Any],
    settings: ProjectSettings,
    thermal: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Result entries (like the run's cases) for each combination, then the force envelope.

    ``thermal``: the temperature case's fixed-end forces (``08 FEM/thermal.json``,
    :func:`saengine.fem.thermal.load_corrections`), added to its end forces.
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
        rows = group.get(key)
        return (
            np.asarray(rows[-1], dtype=float)[:width]
            if rows is not None and len(rows)
            else np.zeros(width)
        )

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
        elements = sorted({e for case in factors for e in by_case[case].element_forces})
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
    return entries


def settings_beside(project_file: str | Path) -> ProjectSettings | None:
    """The project settings of the SAEngine project an analysis model belongs to, if any."""
    root = Path(project_file).resolve().parent.parent
    path = root / "02 Project Settings" / "project-settings.json"
    try:
        return ProjectSettings.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
