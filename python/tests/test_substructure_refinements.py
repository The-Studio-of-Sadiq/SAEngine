"""Part 9 foundation refinements: sloped and stepped footings, slabs on grade, by hand.

The slab-on-grade values follow Westergaard / Ioannides et al. (1985) worked out with plain
arithmetic for one slab; the footing volumes are the prismatoid and step sums, and the sloped
footing's mean thickness is checked against a fine numerical integration of its surface.
"""

from __future__ import annotations

import numpy as np
import pytest

from saengine.library.objects import BarMesh
from saengine.library.substructure import Foundation, GroundSlab
from saengine.substructure import ground_slab
from saengine.substructure.shallow import ColumnBase, FootingSpec

# E = 25 000 MPa, h = 150 mm, ν = 0.15, k = 40 000 kN/m³ (0.04 N/mm³):
# l = (25000 × 150³ / (12 × 0.9775 × 0.04))^¼ = 651.2 mm.
E, H, NU, K = 25000.0, 150.0, 0.15, 0.04


def test_radius_of_relative_stiffness() -> None:
    assert ground_slab.relative_stiffness(E, H, NU, K) == pytest.approx(651.2, abs=0.1)


def test_equivalent_radius() -> None:
    # a = 150 / √π = 84.63 mm < 1.724 h: b = √(1.6 a² + h²) - 0.675 h = 83.03 mm.
    assert ground_slab.equivalent_radius(84.628, H) == pytest.approx(83.03, abs=0.01)
    # a ≥ 1.724 h: b = a.
    assert ground_slab.equivalent_radius(300.0, H) == 300.0


def test_westergaard_stresses_for_a_50_kN_post() -> None:
    # P = 50 kN on 150 × 150 mm:
    # σi = 3 × 1.15 × 50000 / (2π × 150²) (ln(651.2 / 83.03) + 0.6159) = 3.26 MPa;
    # σe (Ioannides) = 6.42 MPa; σc = 3 × 50000 / 150² (1 - (150 / 651.2)^0.72) = 4.35 MPa.
    out = ground_slab.westergaard(50e3, 150, H, E, NU, K)
    assert out["interior"] == pytest.approx(3.265, abs=0.005)
    assert out["edge"] == pytest.approx(6.417, abs=0.005)
    assert out["corner"] == pytest.approx(4.350, abs=0.005)


def test_modulus_of_rupture() -> None:
    # ACI 318-19 19.2.3.1: fr = 0.62 √25 = 3.10 MPa.
    assert ground_slab.modulus_of_rupture(25) == pytest.approx(3.10)


def test_plain_punching_round_a_post() -> None:
    # b0 = 4 (150 + 150) = 1200 mm; φVn = 0.60 × 0.22 × 5 × 1200 × 150 = 118.8 kN.
    capacity, b0 = ground_slab.plain_punching(150, 150, 25)
    assert b0 == 1200
    assert capacity == pytest.approx(118.8e3)


def test_ground_slab_checks_names_and_flags() -> None:
    slab = GroundSlab(
        id="GS1",
        outline=[[0, 0], [10000, 0], [10000, 8000]],
        thickness=150,
        material="C25",
        pointLoad=50,
        mesh=BarMesh(dia=8, spacing=200),
        meshMaterial="B420",
    )
    checks = ground_slab.ground_slab_checks(slab, 25, E, NU, 40000, 420)
    names = [c["name"] for c in checks]
    assert names[:4] == [
        "Flexural stress, load at the interior",
        "Flexural stress, load at the edge",
        "Flexural stress, load at the corner",
        "Punching under the concentrated load",
    ]
    mesh = checks[-1]
    assert mesh["flag"]
    # 0.0018 × 150 × 1000 = 270 mm²/m against Ø8 @ 200 = 251 mm²/m.
    assert mesh["demand"] == pytest.approx(270)


def test_concrete_volume_of_stepped_and_sloped_footings() -> None:
    common = {
        "type": "isolated", "columns": ["C1"], "length": 2000, "width": 1600,
        "thickness": 600, "edgeThickness": 300, "topLength": 600, "topWidth": 500,
    }  # fmt: skip
    stepped = Foundation(id="F1", section="stepped", **common)
    sloped = Foundation(id="F2", section="sloped", **common)
    flat = Foundation(id="F3", type="isolated", columns=["C1"], length=2000, width=1600,
                      thickness=600)  # fmt: skip
    # Stepped: 2000 × 1600 × 300 + 600 × 500 × 300 = 1.05e9 mm³.
    assert stepped.concrete_volume() == pytest.approx(1.05e9)
    # Sloped: L B he + (h - he)/6 (L B + Lt Bt + (L + Lt)(B + Bt)) = 1.408e9 mm³.
    assert sloped.concrete_volume() == pytest.approx(1.408e9)
    assert flat.concrete_volume() == pytest.approx(2000 * 1600 * 600)


def test_section_needs_its_dimensions() -> None:
    with pytest.raises(ValueError):
        Foundation(id="F1", type="isolated", columns=["C1"], length=2000, width=1600,
                   thickness=600, section="sloped")  # fmt: skip
    with pytest.raises(ValueError):
        Foundation(id="F1", type="combined", columns=["C1", "C2"], length=4000, width=1600,
                   thickness=600, section="stepped", edgeThickness=300, topLength=600,
                   topWidth=500)  # fmt: skip


def _spec(section: str) -> FootingSpec:
    return FootingSpec(
        id="F1", type="isolated", footing_type="isolated", length=2000, width=1600,
        thickness=600, elevation=0, cover=75, fc=25, fy=420,
        columns=[ColumnBase("C1", 0, 0, 400, 400)], section=section, edge_thickness=300,
        top_length=600, top_width=500,
    )  # fmt: skip


def test_sloped_mean_thickness_matches_its_surface() -> None:
    spec = _spec("sloped")
    u = np.linspace(-1000, 1000, 801)
    v = np.linspace(-800, 800, 641)
    uu, vv = np.meshgrid((u[1:] + u[:-1]) / 2, (v[1:] + v[:-1]) / 2)
    numeric = float(spec.thickness_at(uu, vv).mean())
    assert spec.mean_thickness() == pytest.approx(numeric, rel=2e-3)
    # The full thickness on the top, the edge thickness at the edges.
    assert float(spec.thickness_at(0.0, 0.0)) == 600
    assert float(spec.thickness_at(1000.0, 0.0)) == pytest.approx(300)
    # Halfway down the slope along u: 450 mm.
    assert float(spec.thickness_at(650.0, 0.0)) == pytest.approx(450)


def test_stepped_thickness() -> None:
    spec = _spec("stepped")
    assert float(spec.thickness_at(0.0, 0.0)) == 600
    assert float(spec.thickness_at(400.0, 0.0)) == 300
    # Mean: 300 + 600 × 500 × 300 / (2000 × 1600) = 328.1 mm.
    assert spec.mean_thickness() == pytest.approx(328.125)
