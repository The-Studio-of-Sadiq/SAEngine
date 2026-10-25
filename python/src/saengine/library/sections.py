"""Geometric section properties of object profiles, computed with sectionproperties.

This is the bridge from an object type's IFC-style profile to the elastic section
properties the FEM model needs (A, I, J). Axes follow sectionproperties: x is horizontal
(the profile's width), y vertical (its depth); ``ixx`` is the major-axis moment of inertia
for a beam bending under gravity.
"""

from __future__ import annotations

from dataclasses import dataclass

from sectionproperties.analysis.section import Section
from sectionproperties.pre.geometry import Geometry
from sectionproperties.pre.library import primitive_sections, steel_sections

from saengine.library import objects as o

# Polygon sides for circles: a 64-gon underestimates a circle's area by ~0.16 % and its
# moment of inertia by ~0.32 %.
_CURVE_POINTS = 64


@dataclass(frozen=True)
class SectionProperties:
    area: float  # mm²
    ixx: float  # mm⁴, about the horizontal centroidal axis
    iyy: float  # mm⁴, about the vertical centroidal axis
    j: float  # mm⁴, St. Venant torsion constant
    cx: float  # mm, centroid
    cy: float  # mm


def profile_geometry(profile: o.Profile) -> Geometry:
    match profile:
        case o.RectangleProfile():
            return primitive_sections.rectangular_section(d=profile.yDim, b=profile.xDim)
        case o.CircleProfile():
            return primitive_sections.circular_section(d=2 * profile.radius, n=_CURVE_POINTS)
        case o.RectangleHollowProfile():
            return steel_sections.rectangular_hollow_section(
                d=profile.yDim,
                b=profile.xDim,
                t=profile.wallThickness,
                r_out=profile.outerFilletRadius,
                n_r=8 if profile.outerFilletRadius else 1,
            )
        case o.CircleHollowProfile():
            return steel_sections.circular_hollow_section(
                d=2 * profile.radius, t=profile.wallThickness, n=_CURVE_POINTS
            )
        case o.IShapeProfile():
            return steel_sections.i_section(
                d=profile.overallDepth,
                b=profile.overallWidth,
                t_f=profile.flangeThickness,
                t_w=profile.webThickness,
                r=profile.filletRadius,
                n_r=8 if profile.filletRadius else 1,
            )
        case o.TShapeProfile():
            return steel_sections.tee_section(
                d=profile.depth,
                b=profile.flangeWidth,
                t_f=profile.flangeThickness,
                t_w=profile.webThickness,
                r=profile.filletRadius,
                n_r=8 if profile.filletRadius else 1,
            )
        case o.LShapeProfile():
            return steel_sections.angle_section(
                d=profile.depth,
                b=profile.width,
                t=profile.thickness,
                r_r=profile.filletRadius,
                r_t=profile.edgeRadius,
                n_r=8,
            )
        case o.UShapeProfile():
            return steel_sections.channel_section(
                d=profile.depth,
                b=profile.flangeWidth,
                t_f=profile.flangeThickness,
                t_w=profile.webThickness,
                r=profile.filletRadius,
                n_r=8 if profile.filletRadius else 1,
            )
        case o.DesignedProfile():
            from saengine.library import section_designer

            return section_designer.outline_geometry(section_designer.resolve(profile))
    raise TypeError(f"unsupported profile: {profile!r}")


def section_properties(profile: o.Profile) -> SectionProperties:
    geometry = profile_geometry(profile)
    # Mesh size relative to the section: fine enough for J, quick enough for interactive use.
    xmin, xmax, ymin, ymax = geometry.calculate_extents()
    mesh = max(xmax - xmin, ymax - ymin) ** 2 / 400
    if isinstance(profile, o.DesignedProfile):  # thin walls and plates: finer (see mesh_size)
        from saengine.library import section_designer

        mesh = section_designer.mesh_size(section_designer.resolve(profile))
    geometry.create_mesh(mesh_sizes=mesh)
    section = Section(geometry)
    section.calculate_geometric_properties()
    section.calculate_warping_properties()
    ixx, iyy, _ = section.get_ic()
    cx, cy = section.get_c()
    return SectionProperties(
        area=float(section.get_area()),
        ixx=float(ixx),
        iyy=float(iyy),
        j=float(section.get_j()),
        cx=float(cx),
        cy=float(cy),
    )
