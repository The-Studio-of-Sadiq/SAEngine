"""The finite element (CBFEM) check of steel joints (saengine.design.connection_fe, alpha 9 L6):
a shear end plate example, the plastic strain of a plate fibre, the mesh grid and the
stiffness classification.

Written in the week without test runs (owner, 2026-11-05): not run yet."""

from __future__ import annotations

import itertools

import pytest

from saengine.codes.tables import builtin_table
from saengine.design import connection_fe as cfe
from saengine.design.steel_proposal import SteelMaterial
from saengine.library.objects import EndPlateConnection
from saengine.library.steel_sections import section_of_profile

S275 = SteelMaterial("S275", 275.0, 430.0, 210_000.0, 81_000.0)


def beam():
    """A 300 mm deep I beam, 7.1 mm web (IPE 300 proportions)."""
    return section_of_profile(
        {
            "shape": "I",
            "overallWidth": 150.0,
            "overallDepth": 300.0,
            "webThickness": 7.1,
            "flangeThickness": 10.7,
        }
    )


def end_plate() -> EndPlateConnection:
    return EndPlateConnection(
        boltGrade="A325N",
        boltDiameter=20,
        rows=3,
        pitch=70,
        endDistance=40,
        edgeDistance=40,
        gauge=90,
        plateThickness=10,
        weldSize=6,
        supportThickness=15,
    )


def test_plastic_strain_of_a_uniaxial_fibre():
    """Yielded in tension with 1 % plastic strain (incompressible: εp22 = -0.5 %):
    εp,eq = 1 %."""
    e, nu, fy = 210e9, 0.3, 275e6
    strain = [fy / e + 0.01, -nu * fy / e - 0.005, 0.0, 0.0, 0.0]
    assert cfe.plastic_strain([fy, 0, 0, 0, 0], strain, e, nu) == pytest.approx(0.01, rel=1e-9)
    elastic = [fy / e, -nu * fy / e, 0.0, 0.0, 0.0]
    assert cfe.plastic_strain([fy, 0, 0, 0, 0], elastic, e, nu) == pytest.approx(0.0, abs=1e-12)


def test_grid_passes_through_the_required_lines():
    lines = cfe.grid(0.23, [0.04, 0.11, 0.18], 0.02)
    for x in (0.0, 0.04, 0.11, 0.18, 0.23):
        assert min(abs(v - x) for v in lines) < 1e-9
    assert max(b - a for a, b in itertools.pairwise(lines)) <= 0.02 + 1e-12


def test_classification_bounds_of_the_packs():
    """EN 1993-1-8 5.2.2.5: rigid at 25 E Ib / Lb unbraced, 8 braced, pinned at 0.5; the
    default pack (AISC 360 Commentary B3 basis, SAEngine practice): 20 and 2."""
    ec = builtin_table("connectionFe", "eurocodes")
    e, ib, lb = 210e9, 8.356e-5, 6.0
    unit = e * ib / lb
    assert cfe.classify(30 * unit, e, ib, lb, False, ec)["class"] == "rigid"
    assert cfe.classify(10 * unit, e, ib, lb, False, ec)["class"] == "semiRigid"
    assert cfe.classify(10 * unit, e, ib, lb, True, ec)["class"] == "rigid"
    assert cfe.classify(0.4 * unit, e, ib, lb, True, ec)["class"] == "pinned"
    default = builtin_table("connectionFe")
    assert cfe.classify(1.5 * unit, e, ib, lb, True, default)["class"] == "pinned"
    assert cfe.classify(25 * unit, e, ib, lb, True, default)["class"] == "rigid"


def test_shear_end_plate_carries_its_design_shear():
    """A shear end plate, 6 M20 bolts, V = 150 kN: the joint carries the full load, the plates'
    plastic strain stays under 5 %, each bolt takes about V / 6 in shear (25 kN; the FE share
    within 20-40 kN), the bolts and welds pass, and the joint classes as pinned or
    semi-rigid (never rigid)."""
    result = cfe.check_joint(
        end_plate(), beam(), S275, None, {"V": 150.0, "N": 0.0, "M": 0.0, "combination": "U1"}, 6.0
    )
    assert result["connection"] == "endPlate"
    assert result["loadShare"] == pytest.approx(1.0)
    assert result["plasticStrain"] < 0.05
    shear = next(c for c in result["checks"] if c["name"].startswith("bolt shear"))
    assert 20.0 <= shear["demand"] <= 40.0
    assert result["ok"]
    assert result["classification"]["class"] in ("pinned", "semiRigid")
    assert set(result["mesh"]) == {"end plate", "support", "beam web"}


def test_overloaded_end_plate_fails():
    result = cfe.check_joint(
        end_plate(), beam(), S275, None, {"V": 1500.0, "N": 0.0, "M": 0.0, "combination": "U1"}, 6.0
    )
    assert not result["ok"]


def test_only_end_and_fin_plates_are_built():
    class Gusset:
        type = "gusset"

    with pytest.raises(cfe.ConnectionFeError):
        cfe.check_joint(Gusset(), beam(), S275, None, {"V": 1.0})
