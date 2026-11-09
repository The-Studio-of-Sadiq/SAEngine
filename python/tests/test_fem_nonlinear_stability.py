"""Nonlinear buckling (GNIA, GMNIA) of a column (saengine.fem.nonlinear_stability) against the
Euler load and the Perry-Robertson first-yield load, and the pack's imperfections (alpha 9 L4).

Written in the week without test runs (owner, 2026-11-05): not run yet."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.codes.tables import builtin_table
from saengine.fem import nonlinear_stability as ns

E = 200e9  # Pa
FY = 250e6  # Pa
PIECES = 8
PINNED_BASE = (True, True, True, False, False, True)
PINNED_TOP = (True, True, False, False, False, True)


def column(length: float, area: float, inertia: float, load: float) -> dict:
    """A pinned-pinned column along Z in ``PIECES`` elements, its top pushed down by ``load``
    [N] in the load case D."""
    nodes = []
    for k in range(PIECES + 1):
        restraint = PINNED_BASE if k == 0 else PINNED_TOP if k == PIECES else (False,) * 6
        nodes.append(
            {"id": k + 1, "coords": [0.0, 0.0, length * k / PIECES], "restraint": restraint}
        )
    elements = [
        {
            "id": k + 1,
            "name": f"C1#{k + 1}",
            "type": "ElasticBeamColumn",
            "nodes": [k + 1, k + 2],
            "section_id": 1,
        }
        for k in range(PIECES)
    ]
    return {
        "nodes": nodes,
        "elements": elements,
        "sections": [
            {
                "id": 1,
                "type": "ElasticSection",
                "E": E,
                "A": area,
                "Iz": inertia,
                "Iy": inertia,
                "G": E / 2.6,
                "J": 2 * inertia,
            }
        ],
        "materials": [],
        "mp_constraints": [],
        "load_patterns": [
            {
                "id": 1,
                "name": "D",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [
                    {"node_id": PIECES + 1, "forces": [0.0, 0.0, -load, 0.0, 0.0, 0.0]}
                ],
                "element_loads": [],
            }
        ],
    }


def eurocodes():
    return builtin_table("nonlinearStability", "eurocodes")


def test_elastic_column_path_tends_to_the_euler_load():
    """GNIA of a slender column, bow L/1000 from the first mode: αcr is the Euler load over P
    and the path's load factor approaches it (λ / αcr within a few % at a deflection of
    L/10: the elastica rises only 1-2 % there and the imperfection takes 1-2 % off)."""
    length, area, inertia, load = 4.0, 0.01, 1e-5, 600e3
    pcr = math.pi**2 * E * inertia / length**2
    options = ns.StabilityOptions(
        imperfection="eigenmode", material="elastic", bowRatio=1000.0, segments=1
    )
    result = ns.analyse(column(length, area, inertia, load), {"D": 1.0}, options, eurocodes())
    assert result.alphaCr == pytest.approx(pcr / load, rel=0.01)
    assert result.imperfection["kind"] == "eigenmode"
    assert result.imperfection["amplitude"] == pytest.approx(length / 1000, rel=1e-6)
    assert result.deformedAtDesign is not None  # λ = 1 is below αcr ≈ 2.06
    assert 0.95 * result.alphaCr <= result.limitFactor <= 1.06 * result.alphaCr


def test_gmnia_column_between_perry_first_yield_and_squash_or_euler():
    """GMNIA of a stocky square column (80 mm solid, L = 2 m, S250, bow L/1000): its limit
    load lies between the Perry-Robertson first-yield load (elastic-plastic redistribution
    adds to it) and the least of Npl and Ncr; the path turns down past its peak."""
    b, length, load = 0.08, 2.0, 500e3
    area, inertia = b * b, b**4 / 12
    i2 = inertia / area
    ncr = math.pi**2 * E * inertia / length**2
    npl = area * FY
    # Perry-Robertson: (fy - σ)(σE - σ) = η σ σE, η = e0 c / i².
    sigma_e = ncr / area
    eta = (length / 1000) * (b / 2) / i2
    bb = FY + sigma_e * (1 + eta)
    sigma = (bb - math.sqrt(bb * bb - 4 * FY * sigma_e)) / 2
    first_yield = sigma * area
    fibre = {
        "id": 9,
        "name": "square fibres",
        "type": "FiberSection",
        "GJ": E / 2.6 * 0.141 * b**4,
        "patches": [
            {
                "kind": "rect",
                "material_id": 1,
                "n_fib_y": 12,
                "n_fib_z": 12,
                "y_i": -b / 2,
                "z_i": -b / 2,
                "y_j": b / 2,
                "z_j": b / 2,
            }
        ],
        "layers": [],
        "fibres": [],
    }
    steel = {
        "id": 1,
        "name": "S250",
        "type": "Steel02",
        "Fy": FY,
        "E0": E,
        "b": 0.01,
        "R0": 18.0,
        "cR1": 0.925,
        "cR2": 0.15,
    }
    options = ns.StabilityOptions(
        imperfection="eigenmode", material="plastic", bowRatio=1000.0, segments=1
    )
    result = ns.analyse(
        column(length, area, inertia, load), {"D": 1.0}, options, eurocodes(), {1: fibre}, [steel]
    )
    limit = result.limitFactor * load
    assert limit >= 0.98 * first_yield
    assert limit <= 1.01 * min(npl, ncr)
    assert result.limitFactor < result.alphaCr
    assert result.limitReached


def test_stability_model_cuts_elements_and_lumps_uniform_loads():
    """A beam element cut into 4 pieces: 3 new nodes, the uniform load's total kept and
    spread as w L / 4 per piece."""
    linear = {
        "nodes": [
            {"id": 1, "coords": [0.0, 0.0, 0.0], "restraint": (True,) * 6},
            {"id": 2, "coords": [6.0, 0.0, 0.0], "restraint": (True,) * 6},
        ],
        "elements": [
            {"id": 1, "name": "B1#1", "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1}
        ],
        "sections": [
            {
                "id": 1,
                "type": "ElasticSection",
                "E": E,
                "A": 0.01,
                "Iz": 1e-5,
                "Iy": 2e-5,
                "G": E / 2.6,
                "J": 1e-6,
            }
        ],
        "materials": [],
        "mp_constraints": [],
        "load_patterns": [],
    }
    uniform = {1: np.array([0.0, 0.0, -10e3])}
    model, loads, members, _ = ns.stability_model(linear, {}, uniform, segments=4)
    assert len(model["nodes"]) == 5 and len(model["elements"]) == 4
    assert members["B1"] == [e["id"] for e in model["elements"]]
    total = sum(v[2] for v in loads.values())
    assert total == pytest.approx(-60e3)
    interior = [v[2] for n, v in loads.items() if n not in (1, 2)]
    assert interior == pytest.approx([-15e3] * 3)


def test_pack_imperfections_eurocodes_and_default():
    """EN 1993-1-1 5.3.2(3): φ = φ0 αh αm (h = 4 m: αh = 1; m = 2: αm = √0.75); Table 5.1 bow
    L/150 for curve c with plasticity; the default pack's fixed L/1000 and L/500."""
    ec = eurocodes()
    options = ns.StabilityOptions(material="plastic")
    assert ns.sway_angle(ec, options, 4.0, 2) == pytest.approx(math.sqrt(0.75) / 200)
    assert ns.sway_angle(ec, options, 100.0, 1) == pytest.approx(2 / 3 / 200, rel=1e-3)
    assert ns.bow_ratio(ec, options, "c") == 150.0
    assert ns.bow_ratio(ec, ns.StabilityOptions(material="elastic"), "c") == 200.0
    default = builtin_table("nonlinearStability")
    assert ns.bow_ratio(default, options) == 1000.0
    assert ns.sway_angle(default, options, 30.0, 10) == pytest.approx(1 / 500)
    # A project's own ratio wins.
    assert ns.bow_ratio(ec, ns.StabilityOptions(bowRatio=400.0)) == 400.0
