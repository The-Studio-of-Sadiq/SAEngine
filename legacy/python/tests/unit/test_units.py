"""Unit tests for the unit management system."""

import pytest
from saengine.core.units import UnitManager, UnitSystem


def test_default_units():
    um = UnitManager()
    assert um.active_system == UnitSystem.SI
    assert um.length_unit == "m"
    assert um.force_unit == "kN"
    assert um.mass_unit == "kg"
    assert um.stress_unit == "kN/m²"
    assert um.moment_unit == "kN·m"


def test_unit_conversion_length():
    um = UnitManager(active_system=UnitSystem.SI)
    assert um.length_to_base(5.0) == 5.0
    assert um.length_from_base(5.0) == 5.0

    um.set_system(UnitSystem.SI_MM)
    assert um.length_unit == "mm"
    assert um.length_to_base(1000.0) == pytest.approx(1.0)
    assert um.length_from_base(1.0) == pytest.approx(1000.0)

    um.set_system(UnitSystem.US)
    assert um.length_unit == "in"
    assert um.length_to_base(12.0) == pytest.approx(0.3048)
    assert um.length_from_base(0.3048) == pytest.approx(12.0)


def test_unit_conversion_force():
    um = UnitManager(active_system=UnitSystem.SI)
    assert um.force_to_base(10.0) == 10.0

    um.set_system(UnitSystem.SI_MM)
    assert um.force_unit == "N"
    assert um.force_to_base(1000.0) == pytest.approx(1.0)
    assert um.force_from_base(1.0) == pytest.approx(1000.0)


def test_unit_serialization():
    um = UnitManager(active_system=UnitSystem.US)
    d = um.to_dict()
    assert d["active_system"] == UnitSystem.US.value

    loaded = UnitManager.from_dict(d)
    assert loaded.active_system == UnitSystem.US
