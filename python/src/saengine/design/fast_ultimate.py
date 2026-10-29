"""The ultimate actions of an RC section at a neutral axis, in closed form (scale round).

concreteproperties integrates the concrete over a triangle mesh, split at the neutral axis and
at the edge of the stress block, three Gauss points per triangle: about 20 ms a call, and a
10-storey building's design asks for tens of thousands (interaction surfaces, the columns'
moments at their axial forces for strong column / weak beam and capacity shear). With
SAEngine's sections, a rectangular stress block on the concrete (Whitney: α f'c over γ·d_n)
and lumped bars (elastic-perfectly plastic), the integral is exact without the mesh: α f'c
times the area and first moments of the concrete inside the block (the polygon clipped by a
half-plane, bar holes and all), and each bar's force at its centroid's strain. The same
numbers to rounding, about a hundred times faster.

:class:`FastConcreteSection` overrides
:meth:`~concreteproperties.concrete_section.ConcreteSection.calculate_ultimate_section_actions`
only, so ``ultimate_bending_capacity`` and everything else built on it take the closed form;
a section of other materials or stress-strain profiles keeps concreteproperties' integration.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from concreteproperties.concrete_section import ConcreteSection
from concreteproperties.results import UltimateBendingResults
from concreteproperties.stress_strain_profile import RectangularStressBlock, SteelElasticPlastic


class FastConcreteSection(ConcreteSection):
    """A :class:`ConcreteSection` whose ultimate actions are worked out in closed form when its
    concrete has a rectangular stress block and its bars are lumped and elastic-perfectly
    plastic (see the module notes)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fast = self._closed_form()

    def _closed_form(self) -> dict[str, Any] | None:
        from shapely.geometry import MultiPolygon, Polygon
        from shapely.ops import unary_union

        concrete = self.concrete_geometries
        if not concrete or self.strand_geometries or self.reinf_geometries_meshed:
            return None
        profiles = {id(g.material.ultimate_stress_strain_profile): g for g in concrete}
        if len(profiles) != 1:
            return None
        block = concrete[0].material.ultimate_stress_strain_profile
        if not isinstance(block, RectangularStressBlock):
            return None
        bars = self.reinf_geometries_lumped
        steel = [b.material.stress_strain_profile for b in bars]
        if not all(isinstance(s, SteelElasticPlastic) for s in steel):
            return None
        shape = unary_union([g.geom for g in concrete])
        if isinstance(shape, Polygon):
            shape = MultiPolygon([shape])
        centroids = np.array([b.calculate_centroid() for b in bars]).reshape(-1, 2)
        return {
            "shape": shape,
            "stress": block.alpha * block.compressive_strength,
            "gamma": block.gamma,
            "eps_cu": block.ultimate_strain,
            "area": float(shape.area),
            "centroid": np.array(shape.centroid.coords[0]),
            "points": np.asarray(self.compound_geometry.points, dtype=float),
            "bar_xy": centroids,
            "bar_area": np.array([b.calculate_area() for b in bars], dtype=float),
            "fy": np.array([s.yield_strength for s in steel], dtype=float),
            "es": np.array([s.elastic_modulus for s in steel], dtype=float),
            # Their profile's strains: beyond them the stress is extrapolated flat.
            "fracture": np.array([s.fracture_strain for s in steel], dtype=float),
        }

    def calculate_ultimate_section_actions(
        self,
        d_n: float,
        ultimate_results: UltimateBendingResults | None = None,
    ) -> UltimateBendingResults:
        """concreteproperties' ultimate actions at the neutral axis depth ``d_n`` (from the
        extreme compression fibre) and the angle of ``ultimate_results``, in closed form."""
        fast = self._fast
        if fast is None:
            return super().calculate_ultimate_section_actions(d_n, ultimate_results)
        if ultimate_results is None:
            ultimate_results = UltimateBendingResults(default_units=self.default_units, theta=0)
        if d_n <= 0:
            raise ValueError("d_n must be positive.")
        theta = ultimate_results.theta
        c, s = math.cos(theta), math.sin(theta)
        points = fast["points"]
        v_points = points[:, 1] * c - points[:, 0] * s
        ef_v = float(v_points.max())
        eps_cu = fast["eps_cu"]
        xy = fast["bar_xy"]
        v_bars = xy[:, 1] * c - xy[:, 0] * s
        if math.isinf(d_n):
            # The whole section at the ultimate strain.
            area, centroid = fast["area"], fast["centroid"]
            strain = np.full(len(xy), eps_cu)
        else:
            v_na = ef_v - d_n
            # The stress block: strain >= eps_cu (1 - gamma), split there exactly (the mesh is).
            edge = v_na + d_n * (1 - fast["gamma"])
            area, centroid = self._clipped(edge, c, s)
            strain = eps_cu * (v_bars - v_na) / d_n
        # Moments about the section's moment centroid, as concreteproperties takes them.
        mx0, my0 = self.moment_centroid[1], self.moment_centroid[0]
        force = fast["stress"] * area
        n = force
        m_x = force * (centroid[1] - mx0)
        m_y = force * (centroid[0] - my0)
        stress = np.clip(fast["es"] * strain, -fast["fy"], fast["fy"])
        bar_force = stress * fast["bar_area"]
        n += float(bar_force.sum())
        m_x += float((bar_force * (xy[:, 1] - mx0)).sum())
        m_y += float((bar_force * (xy[:, 0] - my0)).sum())
        ultimate_results.d_n = d_n
        ultimate_results.n = n
        ultimate_results.m_x = m_x
        ultimate_results.m_y = m_y
        ultimate_results.m_xy = math.hypot(m_x, m_y)
        if len(xy):
            ultimate_results.k_u = float(np.min(d_n / (ef_v - v_bars)))
        return ultimate_results

    def _clipped(self, edge: float, c: float, s: float) -> tuple[float, np.ndarray]:
        """Area and centroid of the concrete where the local v (y c - x s) is ``edge`` or more."""
        from shapely.geometry import Polygon

        fast = self._fast
        v_points = fast["points"][:, 1] * c - fast["points"][:, 0] * s
        if edge <= v_points.min():  # the block covers the whole section (d_n beyond it)
            return fast["area"], fast["centroid"]
        if edge >= v_points.max():
            return 0.0, np.zeros(2)
        # The edge crosses the section: the rectangle below reaches across all of it.
        shape = fast["shape"]
        minx, miny, maxx, maxy = shape.bounds
        reach = 2 * math.hypot(maxx - minx, maxy - miny) + 1.0
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        # The half-plane as a large rectangle: u along the axis, v across it.
        u = np.array([c, s])
        v = np.array([-s, c])
        v0 = edge - (cy * c - cx * s)
        origin = np.array([cx, cy]) + v0 * v
        corners = [
            origin - reach * u,
            origin + reach * u,
            origin + reach * u + reach * v,
            origin - reach * u + reach * v,
        ]
        part = shape.intersection(Polygon(corners))
        area = float(part.area)
        if area <= 0:
            return 0.0, np.zeros(2)
        return area, np.array(part.centroid.coords[0])
