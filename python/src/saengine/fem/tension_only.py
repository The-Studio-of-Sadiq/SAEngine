"""Tension-only members (rod and slender-angle bracing) in a linear analysis model.

A brace type marked ``tensionOnly`` (Part 4 object types) carries tension but no compression:
under a load combination that compresses it, it buckles at a negligible load and drops out, and
the rest of the structure carries the load without it. The analysis model stays linear (each
load case is run once and the combinations are factored sums, :mod:`saengine.fem.combinations`),
so the slack members are released per combination by superposition, which is exact for the
linear model without them:

- :func:`saengine.fem.derive.derive_fem` adds one *release case* per tension-only element:
  ``TOk``, a unit pair of forces (``UNIT`` N) on the element's two end nodes along its axis,
  pulling them apart. The case's results give, for every element and node, the effect of
  pulling that element's ends apart on the complete structure;
- removing element k from the structure is the same as leaving it in and pulling its ends
  apart by the force it carries (its pull on the nodes is then cancelled). With T0 the axial
  forces of the combination (tension positive) and G the forces in the tension-only elements
  per unit pull (column j: release case j), the pulls X on the released set S solve
  ``(I - G_SS) X_S = T0_S``; every result of the combination is then the factored sum plus
  ``Σ X_j / UNIT`` times release case j (:func:`release_factors` returns them as extra case
  factors, so every consumer that forms ``Σ f·case`` gets the released structure). The released
  elements carry no force (:func:`release_factors` names them for the design to zero);
- which members are slack is found by the active-set iteration of :func:`solve`: release the
  members in compression, re-solve, take back a released member whose ends move apart (its
  pull is a tension) and release any other that the redistribution compresses, until no set
  changes. A member split into several elements (meshing, crossing members) is released or
  kept as a whole, by the mean axial force of its pieces.

What it does not do: the modal and response spectrum cases keep every member (the initial
stiffness: about twice the stiffness of an X-braced panel), and an envelope combination
(``S ± E``) releases by its static part only; the release is not followed through second-order
effects of the released structure beyond the preload's tangent stiffness. These are the usual
limits of tension-only bracing in a linear analysis. The released members are then designed
for tension alone (BNBC 2020 Part 6 Chapter 10, Sec 10.4 design of members for tension, which
adopts AISC 360-05 chapter D; page to be checked against the BNBC text). BNBC gives no analysis
procedure of its own for tension-only members: the release above is the structural mechanics
of removing a member from a linear model, not a code clause.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Size of the unit pull of a release case [N].
UNIT = 1000.0
#: Description of a release case, followed by its element's name.
RELEASE_LABEL = "tension-only release of"
#: Case code of a release case: ``TO1``, ``TO2``...
CODE = re.compile(r"^TO(\d+)$")
#: Iterations of the active set before giving up (each changes the set).
MAX_ITERATIONS = 50


def is_release_case(code: str) -> bool:
    return bool(CODE.match(code))


def member_of(element_name: str) -> str:
    """The structural member an analysis element belongs to: its name without the piece
    (``/p0``) and duplicate (``#2``) suffixes."""
    return element_name.split("#")[0].split("/")[0]


def tension_only_cases(
    elements: Iterable[dict[str, Any]],
    coords: Mapping[int, np.ndarray],
    sources: set[str],
) -> list[tuple[str, str, dict[int, np.ndarray]]]:
    """The release cases of the frame elements of ``sources`` (tension-only members):
    ``(code, element name, {node: 6 nodal forces})``, numbered in element order."""
    if not sources:
        return []
    result = []
    for element in elements:
        if element.get("type") != "ElasticBeamColumn":
            continue
        name = str(element["name"])
        if member_of(name) not in sources:
            continue
        i, j = element["nodes"]
        axis = np.asarray(coords[j], dtype=float) - np.asarray(coords[i], dtype=float)
        length = float(np.linalg.norm(axis))
        if length <= 0:
            continue
        u = axis / length * UNIT
        pair = {
            int(i): np.array([-u[0], -u[1], -u[2], 0.0, 0.0, 0.0]),
            int(j): np.array([u[0], u[1], u[2], 0.0, 0.0, 0.0]),
        }
        result.append((f"TO{len(result) + 1}", name, pair))
    return result


def release_cases(project: dict[str, Any]) -> dict[str, str]:
    """``{release case code: element name}`` of a derived project (from its analyses' names,
    ``"TOk: tension-only release of <element>"``)."""
    found = {}
    for analysis in project.get("analyses", []):
        code, _, label = str(analysis.get("name", "")).partition(":")
        label = label.strip()
        if is_release_case(code) and label.startswith(RELEASE_LABEL):
            found[code] = label[len(RELEASE_LABEL) :].strip()
    return found


def axial_force(end_forces: np.ndarray) -> float:
    """Tension (positive) of a frame element from its 12 local end forces (OpenSees
    ``localForce``: -N at end i, +N at end j)."""
    f = np.asarray(end_forces, dtype=float)
    return 0.5 * (float(f[6]) - float(f[0]))


@dataclass
class Release:
    """The slack members of one combination and the pulls that release them."""

    #: Extra factors on the release cases (``Σ f·case`` then gives the released structure).
    factors: dict[str, float] = field(default_factory=dict)
    #: Names of the elements released (they carry no force).
    slack: set[str] = field(default_factory=set)
    #: The members released (by :func:`member_of`).
    members: set[str] = field(default_factory=set)
    #: Axial force of every tension-only element after the release [N].
    forces: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def solve(
    t0: np.ndarray, g: np.ndarray, groups: list[int]
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Active-set release of tension-only elements.

    ``t0``: axial forces of the combination (tension positive), one per element; ``g[i, j]``:
    force in element i per unit pull of element j; ``groups[i]``: the member of element i
    (released as a whole). Returns ``(pulls X, released mask, warnings)``; the forces after the
    release are ``t0 + g @ X``, zero for the released elements."""
    t0 = np.asarray(t0, dtype=float)
    g = np.asarray(g, dtype=float)
    n = len(t0)
    group_ids = np.asarray(groups)
    members = sorted(set(groups))
    warnings: list[str] = []

    def mean_by_member(values: np.ndarray) -> dict[int, float]:
        return {m: float(np.mean(values[group_ids == m])) for m in members}

    slack = {m for m, v in mean_by_member(t0).items() if v < 0}
    x = np.zeros(n)
    seen: set[frozenset[int]] = set()
    for _ in range(MAX_ITERATIONS):
        mask = np.isin(group_ids, sorted(slack))
        x = np.zeros(n)
        if mask.any():
            idx = np.flatnonzero(mask)
            a = np.eye(len(idx)) - g[np.ix_(idx, idx)]
            if np.linalg.matrix_rank(a) < len(idx):
                warnings.append(
                    "releasing the compressed tension-only members leaves a mechanism: the "
                    "bracing cannot carry this combination in tension alone"
                )
                x[idx] = np.linalg.lstsq(a, t0[idx], rcond=None)[0]
            else:
                x[idx] = np.linalg.solve(a, t0[idx])
        t = t0 + g @ x  # for a released element: the force it would carry if put back
        by_member = mean_by_member(t)
        new = {m for m in members if (m in slack and by_member[m] <= 0) or by_member[m] < 0}
        if new == slack:
            break
        key = frozenset(new)
        if key in seen:
            warnings.append("the tension-only release did not settle (cycling); last set kept")
            break
        seen.add(frozenset(slack))
        slack = new
    else:
        warnings.append("the tension-only release did not settle in the iterations allowed")
    return x, np.isin(group_ids, sorted(slack)), warnings


def release_factors(
    factors: Mapping[str, float],
    axial: Mapping[str, Mapping[str, float]],
    cases: Mapping[str, str],
) -> Release:
    """The release of one combination.

    ``factors``: the combination's case factors; ``axial``: per case the axial force [N] of
    each tension-only element (by name), the release cases included; ``cases``: release case
    code -> element name (:func:`release_cases`). Without release cases: no release."""
    codes = [c for c in sorted(cases, key=lambda c: int(CODE.match(c).group(1))) if c in axial]
    if not codes:
        return Release()
    names = [cases[c] for c in codes]
    t0 = np.array(
        [
            sum(f * float(axial.get(case, {}).get(name, 0.0)) for case, f in factors.items())
            for name in names
        ]
    )
    g = np.array([[float(axial[c].get(name, 0.0)) / UNIT for c in codes] for name in names])
    member_index: dict[str, int] = {}
    groups = [member_index.setdefault(member_of(n), len(member_index)) for n in names]
    x, released, warnings = solve(t0, g, groups)
    forces = t0 + g @ x
    return Release(
        factors={c: float(v) / UNIT for c, v in zip(codes, x, strict=True) if v != 0.0},
        slack={n for n, r in zip(names, released, strict=True) if r},
        members={member_of(n) for n, r in zip(names, released, strict=True) if r},
        forces={n: 0.0 if r else float(f) for n, f, r in zip(names, forces, released, strict=True)},
        warnings=warnings,
    )
