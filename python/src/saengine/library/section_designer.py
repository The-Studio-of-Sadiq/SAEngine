"""Designed sections: arbitrary cross-sections drawn in the Section Designer
(``04 Objects/sections/<id>.json``), like ETABS' or SAP2000's Section Designer.

A designed section is one or more polygonal regions (outline and holes, each with a material
of ``03 Materials``: concrete, structural steel plates) and reinforcing bars at points. Object
types use it through the profile ``{"shape": "designed", "section": "<id>"}``
(:class:`saengine.library.objects.DesignedProfile`).

Nothing is reinvented here:

- geometric and warping properties (A, I, J, Cw, shear areas, centroid, shear centre, plastic
  moduli) come from sectionproperties (MIT) on a mesh sized to the section (see
  :func:`mesh_size`), cached per section and materials;
- the ultimate strength of reinforced-concrete sections (uniaxial interaction diagrams, the
  biaxial P-Mx-My surface) comes from concreteproperties (MIT) with the stress block of
  :mod:`saengine.design.rc` (ACI 318-19 / BNBC 2020 Part 6 Sec 6.2.2: 0.85 f'c over β1 c,
  εcu = 0.003, elastic-perfectly plastic bars). The strength reduction factors φ are read from
  the active code pack's ``factors`` table (``phi.tension``, ``phi.compressionTied``,
  ``phi.compressionSpiral``), never hard-coded: φ goes from the compression-controlled value
  at εt <= εty to ``phi.tension`` at εt >= εty + 0.003, linear between (Table 6.6.2.1 / ACI
  21.2.2), εt measured at the extreme tension bar.
- design of columns of a designed section reuses :class:`saengine.design.rc.InteractionSurface`
  (meridians, contour at Pu, capacity along the demand ray) through :class:`DesignedRcSection`.

Units: mm, MPa, N, N·mm. Coordinates are the drawing's: x to the right, y up; properties are
about the centroid; moments of the interaction diagrams are about the gross (concrete and
plate) centroid, compression positive.
"""

from __future__ import annotations

import functools
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Category, Id, Material, MaterialLibrary

SCHEMA_ID = "saengine.section/1"
SECTIONS_DIR = Path("04 Objects") / "sections"

Point = tuple[float, float]
Ring = Annotated[list[Point], Field(min_length=3)]


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class Region(_Model):
    """A solid region: an outline with holes, all of one material (concrete, or a steel plate
    of a built-up or composite section)."""

    outline: Ring = Field(description="Corner points [mm], either direction.")
    holes: list[Ring] = Field(default_factory=list, description="Openings inside the outline.")
    material: Id
    label: str | None = None


class Bar(_Model):
    """A reinforcing bar at a point."""

    x: float = Field(description="[mm]")
    y: float = Field(description="[mm]")
    dia: float = Field(gt=0, description="Bar diameter [mm].")
    material: Id | None = Field(
        default=None, description="Rebar material; none: the section's rebar material."
    )


class DesignedSection(_Model):
    schema_: Literal["saengine.section/1"] = Field(default=SCHEMA_ID, alias="schema")
    id: Id
    name: str = Field(min_length=1)
    description: str | None = None
    regions: list[Region] = Field(min_length=1)
    bars: list[Bar] = Field(default_factory=list)
    rebar: Id | None = Field(default=None, description="Material of the bars (rebar).")
    confinement: Literal["tied", "spiral"] = Field(
        default="tied",
        description="Transverse reinforcement, which sets the compression-controlled φ and "
        "φPn,max.",
    )
    cover: float | None = Field(
        default=None, gt=0, description="Clear cover to the bars, used by the editor [mm]."
    )
    meshSize: float | None = Field(
        default=None,
        gt=0,
        title="Mesh size",
        description="Largest mesh element area [mm²] for the properties; none: from the section.",
    )

    @model_validator(mode="after")
    def _geometry(self) -> DesignedSection:
        problems = geometry_problems(self)
        if problems:
            raise ValueError("; ".join(problems))
        if self.bars and self.rebar is None and any(b.material is None for b in self.bars):
            raise ValueError("bars need a rebar material (rebar)")
        return self


# ─────────────────────────────────────── files ───────────────────────────────────────


def section_path(root: str | Path, section_id: str) -> Path:
    """``<project>/04 Objects/sections/<id>.json``."""
    return Path(root) / SECTIONS_DIR / f"{section_id}.json"


def load_section(root: str | Path, section_id: str) -> DesignedSection:
    path = section_path(root, section_id)
    if not path.is_file():
        raise SectionError(f"designed section '{section_id}' not found ({path})")
    return DesignedSection.model_validate_json(path.read_text(encoding="utf-8"))


def save_section(root: str | Path, section: DesignedSection) -> Path:
    path = section_path(root, section.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(section.model_dump(mode="json", by_alias=True, exclude_none=True), indent=2)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def list_sections(root: str | Path) -> list[str]:
    """Ids of the project's designed sections."""
    folder = Path(root) / SECTIONS_DIR
    return sorted(p.stem for p in folder.glob("*.json")) if folder.is_dir() else []


def resolve(profile: Any, root: str | Path | None = None) -> DesignedSection:
    """The designed section of a ``{"shape": "designed"}`` profile, from ``root``, else the
    project in force (:func:`saengine.codes.context.project_root`, set by the RPC server, the
    command line and Run All for every request on a project)."""
    if root is None:
        from saengine.codes import context

        root = context.project_root()
    if root is None:
        raise SectionError(
            f"designed section '{profile.section}': no project folder to read it from"
        )
    return load_section(root, profile.section)


# ─────────────────────────────────────── geometry ───────────────────────────────────────


def _polygon(region: Region):
    from shapely.geometry import Polygon

    return Polygon(region.outline, region.holes)


def outline_geometry(section: DesignedSection):
    """The section's solid as one sectionproperties ``Geometry`` without materials (the union
    of its regions), for what treats profiles as shapes: extents, quantities, geometric
    properties (:func:`saengine.library.sections.profile_geometry`)."""
    from sectionproperties.pre.geometry import CompoundGeometry, Geometry
    from shapely.ops import unary_union

    solid = unary_union([_polygon(r) for r in section.regions])
    if solid.geom_type == "Polygon":
        return Geometry(solid)
    return CompoundGeometry([Geometry(part) for part in solid.geoms])  # separate plates


def geometry_problems(section: DesignedSection) -> list[str]:
    """Self-intersecting or overlapping regions, holes outside their outline, bars outside
    the concrete or on a hole."""
    from shapely.ops import unary_union

    problems: list[str] = []
    polygons = []
    for k, region in enumerate(section.regions):
        name = region.label or f"region {k + 1}"
        polygon = _polygon(region)
        if not polygon.exterior.is_valid or not polygon.is_valid:
            problems.append(f"{name}: the outline crosses itself or a hole leaves it")
            continue
        if polygon.area <= 0:
            problems.append(f"{name}: no area")
            continue
        for j, other in enumerate(polygons):
            if other is not None and polygon.intersection(other).area > 1e-6 * polygon.area:
                problems.append(f"{name} overlaps region {j + 1}")
        polygons.append(polygon)
    if problems or not section.bars:
        return problems
    solid = unary_union(polygons)
    for k, bar in enumerate(section.bars):
        from shapely.geometry import Point as ShapelyPoint

        if not solid.contains(ShapelyPoint(bar.x, bar.y).buffer(bar.dia / 2, 8)):
            problems.append(f"bar {k + 1} at ({bar.x:g}, {bar.y:g}) is not inside the section")
    return problems


def mesh_size(section: DesignedSection) -> float:
    """Largest element area [mm²]: 1/400 of the square of the section's extent (as
    :mod:`saengine.library.sections`), but no more than the square of the mean wall thickness
    (2 A / perimeter) so thin walls and plates get at least two elements through their
    thickness (J, Cw, shear areas), and not so fine that a section has over ~6000 elements."""
    if section.meshSize:
        return section.meshSize
    polygons = [_polygon(r) for r in section.regions]
    area = sum(p.area for p in polygons)
    perimeter = sum(p.length for p in polygons)
    xs = [x for r in section.regions for x, _ in r.outline]
    ys = [y for r in section.regions for _, y in r.outline]
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    thickness = 2 * area / perimeter
    return max(min(extent**2 / 400, (thickness / 2) ** 2), area / 6000)


# ─────────────────────────────────────── materials ───────────────────────────────────────


@dataclass(frozen=True)
class _Mat:
    id: str
    category: str
    E: float
    nu: float
    density: float  # kg/m³
    fc: float | None
    fy: float | None


def _mat(materials: MaterialLibrary | Iterable[Material], material_id: str) -> _Mat:
    found = (
        materials.get(material_id)
        if isinstance(materials, MaterialLibrary)
        else next((m for m in materials if m.id == material_id), None)
    )
    if found is None:
        raise SectionError(f"unknown material '{material_id}'")
    m = found
    if m.category not in (Category.CONCRETE, Category.STEEL, Category.REBAR):
        raise SectionError(f"material '{m.id}' is {m.category.value}: concrete or steel only")
    e = m.mechanical.E
    if e is None:  # the material model requires E for these categories
        raise SectionError(f"material '{m.id}' has no E")
    nu = (
        m.mechanical.nu
        if m.mechanical.nu is not None
        else (0.2 if m.category == Category.CONCRETE else 0.3)
    )
    density = m.mechanical.density or (2400.0 if m.category == Category.CONCRETE else 7850.0)
    return _Mat(
        id=m.id,
        category=m.category.value,
        E=e,
        nu=nu,
        density=density,
        fc=m.concrete.fc if m.concrete else None,
        fy=m.steel.fy if m.steel else None,
    )


class SectionError(ValueError):
    """The section cannot be analysed (unknown material, no bars for an RC capacity, ...)."""


# ─────────────────────────────────────── properties ───────────────────────────────────────


@dataclass(frozen=True)
class SectionProperties:
    """Elastic and plastic properties about the centroid [mm, mm², mm³, mm⁴, mm⁶].

    Sections of more than one material (concrete with steel plates, plates of different
    grades) are transformed to the reference material, the first region's: A, I, J, Cw and the
    shear areas are E-weighted (E A / E_ref ...); the plastic moduli are given for sections of
    one material only. Bars are not included (as ETABS' Section Designer gross properties)."""

    referenceMaterial: str
    E: float  # MPa, of the reference material
    G: float
    area: float
    perimeter: float
    massPerLength: float  # kg/m
    cx: float
    cy: float
    ixx: float
    iyy: float
    ixy: float
    i11: float  # principal
    i22: float
    principalAngle: float  # degrees, from x to the 1-1 axis
    rx: float
    ry: float
    sxTop: float  # elastic section moduli to the extreme fibres
    sxBottom: float
    syRight: float
    syLeft: float
    zx: float | None  # plastic section moduli
    zy: float | None
    j: float
    cw: float  # warping constant
    asx: float  # shear areas
    asy: float
    scx: float  # shear centre
    scy: float
    barArea: float
    barRatio: float  # bar area / concrete area
    mesh: float  # element area used [mm²]
    elements: int

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _key(section: DesignedSection, materials: list[_Mat]) -> str:
    return json.dumps(
        [section.model_dump(mode="json", by_alias=True), [m.__dict__ for m in materials]],
        sort_keys=True,
    )


def _region_mats(section: DesignedSection, materials: Any) -> list[_Mat]:
    return [_mat(materials, r.material) for r in section.regions]


def properties(section: DesignedSection, materials: Any) -> SectionProperties:
    """The section's properties, computed with sectionproperties (cached)."""
    mats = _region_mats(section, materials)
    return _properties_cached(_key(section, mats))


@functools.lru_cache(maxsize=64)
def _properties_cached(key: str) -> SectionProperties:
    data, mats_raw = json.loads(key)
    section = DesignedSection.model_validate(data)
    mats = [_Mat(**m) for m in mats_raw]
    return _compute_properties(section, mats)


def _sp_geometry(section: DesignedSection, mats: list[_Mat]):
    """Regions with their materials (E, ν: the shear areas and J depend on ν). Yield strength 1
    so that sectionproperties' plastic moment is the plastic section modulus."""
    from sectionproperties.pre.geometry import CompoundGeometry, Geometry
    from sectionproperties.pre.pre import Material as SpMaterial

    geoms = []
    for region, m in zip(section.regions, mats, strict=True):
        material = SpMaterial(
            name=m.id,
            elastic_modulus=m.E,
            poissons_ratio=m.nu,
            yield_strength=1.0,
            density=m.density * 1e-9,  # kg/mm³
            color="lightgrey" if m.category == "concrete" else "steelblue",
        )
        geoms.append(Geometry(_polygon(region), material=material))
    return geoms[0] if len(geoms) == 1 else CompoundGeometry(geoms)


def _compute_properties(section: DesignedSection, mats: list[_Mat]) -> SectionProperties:
    from sectionproperties.analysis.section import Section

    ref = mats[0]
    single = len({(m.E, m.nu) for m in mats}) == 1
    geometry = _sp_geometry(section, mats)
    mesh = mesh_size(section)
    geometry.create_mesh(mesh_sizes=mesh)
    sec = Section(geometry)
    sec.calculate_geometric_properties()
    sec.calculate_warping_properties()
    e_ref = ref.E
    area = sec.get_ea(e_ref=e_ref)
    ixx, iyy, ixy = sec.get_eic(e_ref=e_ref)
    zxx_p, zxx_m, zyy_p, zyy_m = sec.get_ez(e_ref=e_ref)
    j = sec.get_ej(e_ref=e_ref)
    cw = sec.get_egamma(e_ref=e_ref)
    asx, asy = sec.get_eas(e_ref=e_ref)
    i11, i22 = sec.get_eip(e_ref=e_ref)
    zx = zy = None
    if single:
        sec.calculate_plastic_properties()
        zx, zy = sec.get_mp()  # fy = 1
    cx, cy = sec.get_c()
    scx, scy = sec.get_sc()
    mass = sum(
        _polygon(r).area * m.density * 1e-6 for r, m in zip(section.regions, mats, strict=True)
    )
    concrete = sum(
        _polygon(r).area
        for r, m in zip(section.regions, mats, strict=True)
        if m.category == "concrete"
    )
    bar_area = sum(math.pi * b.dia**2 / 4 for b in section.bars)
    return SectionProperties(
        referenceMaterial=ref.id,
        E=e_ref,
        G=e_ref / (2 * (1 + ref.nu)),
        area=float(area),
        perimeter=float(sec.get_perimeter()),
        massPerLength=float(mass),
        cx=float(cx),
        cy=float(cy),
        ixx=float(ixx),
        iyy=float(iyy),
        ixy=float(ixy),
        i11=float(i11),
        i22=float(i22),
        principalAngle=float(sec.get_phi()),
        rx=math.sqrt(ixx / area),
        ry=math.sqrt(iyy / area),
        sxTop=float(zxx_p),
        sxBottom=float(zxx_m),
        syRight=float(zyy_p),
        syLeft=float(zyy_m),
        zx=None if zx is None else float(zx),
        zy=None if zy is None else float(zy),
        j=float(j),
        cw=float(cw),
        asx=float(asx),
        asy=float(asy),
        scx=float(scx),
        scy=float(scy),
        barArea=bar_area,
        barRatio=bar_area / concrete if concrete else 0.0,
        mesh=mesh,
        elements=len(sec.elements),
    )


# ─────────────────────────────────── reinforced concrete ───────────────────────────────────
# saengine.design imports the whole design package (which reads object profiles through
# saengine.library.sections), so its modules are imported where they are used.


@dataclass(frozen=True)
class Phi:
    """Strength reduction factors of the pack in force (``factors`` table, ``phi`` group)."""

    tension: float
    compression: float  # tied or spiral, as the section's confinement

    @staticmethod
    def from_pack(pack: Any = None, spiral: bool = False) -> Phi:
        """φ of ``pack`` (a :class:`saengine.codes.registry.CodePack`), else of the pack in force
        (:func:`saengine.codes.context.current`)."""
        if pack is None:
            from saengine.codes import context

            pack = context.current()
        phi = pack.table("factors").phi
        return Phi(
            tension=float(phi["tension"]),
            compression=float(phi["compressionSpiral" if spiral else "compressionTied"]),
        )

    def at(self, eps_t: float, eps_ty: float) -> float:
        """φ for the net tensile strain εt of the extreme tension bar."""
        from saengine.design.rc import EPS_CU

        if eps_t <= eps_ty:
            return self.compression
        if eps_t >= eps_ty + EPS_CU:
            return self.tension
        return self.compression + (self.tension - self.compression) * (eps_t - eps_ty) / EPS_CU


#: Strain of the bars and plates' stress-strain profile end. ACI 318 / BNBC put no limit on the
#: steel strain (fy beyond εy); concreteproperties drops the stress past the profile's end, which
#: at 0.05 (as design/rc.py) left the bars of very shallow neutral axes without force.
_NO_RUPTURE = 1.0


@dataclass(frozen=True)
class _RcBar:
    """A bar as :class:`saengine.design.rc.InteractionSurface` reads it."""

    x: float
    y: float
    area: float
    dia: float


class DesignedRcSection:
    """A reinforced-concrete designed section, analysed with concreteproperties.

    It offers what :class:`saengine.design.rc.InteractionSurface` reads of an
    :class:`~saengine.design.rc.RcSection` (``analysis``, ``bars``, ``fy``, ``es``, ``spiral``,
    ``symmetric``, ``phi_pn_max``, ``phi_tension``), so a column of a designed section is
    designed on the same surface as a rectangular one (:func:`design_surface`)."""

    def __init__(self, section: DesignedSection, materials: Any, pack: Any = None) -> None:
        self.section = section
        mats = _region_mats(section, materials)
        if not any(m.category == "concrete" for m in mats):
            raise SectionError("no concrete region: an RC capacity needs concrete")
        if not section.bars:
            raise SectionError("no bars")
        self.region_mats = mats
        self.bar_mats = [_mat(materials, b.material or section.rebar or "") for b in section.bars]
        for m in self.bar_mats:
            if m.fy is None:
                raise SectionError(f"bar material '{m.id}' has no fy")
        for m in mats:
            if m.category == "concrete" and m.fc is None:
                raise SectionError(f"concrete '{m.id}' has no f'c")
            if m.category != "concrete" and m.fy is None:
                raise SectionError(f"steel '{m.id}' has no fy")
        self.spiral = section.confinement == "spiral"
        self.phi = Phi.from_pack(pack, self.spiral)
        # εty of the bars (εt is measured at the extreme tension bar): with one grade of bars
        # (the usual) the same for all, else the highest (the later φ transition).
        governing = max(self.bar_mats, key=lambda m: (m.fy or 0.0) / m.E)
        self.fy = governing.fy or 0.0
        self.es = governing.E
        polygons = [_polygon(r) for r in section.regions]
        total = sum(p.area for p in polygons)
        # Moments about the gross centroid of the regions (untransformed, as rc.py's sections).
        self.centroid = (
            sum(p.centroid.x * p.area for p in polygons) / total,
            sum(p.centroid.y * p.area for p in polygons) / total,
        )
        self.bars = tuple(_RcBar(b.x, b.y, math.pi * b.dia**2 / 4, b.dia) for b in section.bars)

    @functools.cached_property
    def analysis(self):
        from concreteproperties.concrete_section import ConcreteSection
        from concreteproperties.material import Concrete, Steel, SteelBar
        from concreteproperties.pre import add_bar
        from concreteproperties.stress_strain_profile import (
            ConcreteLinear,
            RectangularStressBlock,
            SteelElasticPlastic,
        )
        from sectionproperties.pre.geometry import CompoundGeometry, Geometry

        from saengine.design.rc import EPS_CU, beta1

        geoms = []
        for region, m in zip(self.section.regions, self.region_mats, strict=True):
            if m.category == "concrete":
                fc = m.fc or 0.0
                material: Any = Concrete(
                    name=m.id,
                    density=m.density * 1e-9,
                    stress_strain_profile=ConcreteLinear(elastic_modulus=m.E),
                    ultimate_stress_strain_profile=RectangularStressBlock(
                        compressive_strength=fc,
                        alpha=0.85,
                        gamma=beta1(fc),
                        ultimate_strain=EPS_CU,
                    ),
                    flexural_tensile_strength=0.62 * math.sqrt(fc),
                    colour="lightgrey",
                )
            else:
                material = Steel(
                    name=m.id,
                    density=m.density * 1e-9,
                    stress_strain_profile=SteelElasticPlastic(
                        yield_strength=m.fy or 0.0, elastic_modulus=m.E, fracture_strain=_NO_RUPTURE
                    ),
                    colour="steelblue",
                )
            geoms.append(Geometry(_polygon(region), material=material))
        geometry: Any = CompoundGeometry(geoms) if len(geoms) > 1 else geoms[0]
        steels: dict[str, Any] = {}
        for bar, m in zip(self.section.bars, self.bar_mats, strict=True):
            steel = steels.setdefault(
                m.id,
                SteelBar(
                    name=m.id,
                    density=m.density * 1e-9,
                    stress_strain_profile=SteelElasticPlastic(
                        yield_strength=m.fy or 0.0, elastic_modulus=m.E, fracture_strain=_NO_RUPTURE
                    ),
                    colour="grey",
                ),
            )
            geometry = add_bar(
                geometry, area=math.pi * bar.dia**2 / 4, material=steel, x=bar.x, y=bar.y
            )
        return ConcreteSection(geometry, moment_centroid=self.centroid)

    # ── what InteractionSurface reads ──

    @property
    def steel_area(self) -> float:
        return sum(b.area for b in self.bars)

    @functools.cached_property
    def p0(self) -> float:
        """Nominal axial strength at zero eccentricity [N] (ACI 22.4.2.2): 0.85 f'c on the
        concrete less the bars in it, fy on the bars and plates."""
        from shapely.geometry import Point as ShapelyPoint

        p0 = 0.0
        for region, m in zip(self.section.regions, self.region_mats, strict=True):
            polygon = _polygon(region)
            if m.category == "concrete":
                inside = sum(b.area for b in self.bars if polygon.contains(ShapelyPoint(b.x, b.y)))
                p0 += 0.85 * (m.fc or 0.0) * (polygon.area - inside)
            else:
                p0 += (m.fy or 0.0) * polygon.area
        p0 += sum(b.area * (m.fy or 0.0) for b, m in zip(self.bars, self.bar_mats, strict=True))
        return p0

    @property
    def phi_pn_max(self) -> float:
        """Largest design axial compression [N] (ACI Table 22.4.2.1: 0.80 φ P0 tied, 0.85 φ P0
        spiral), φ from the pack."""
        return (0.85 if self.spiral else 0.80) * self.phi.compression * self.p0

    @property
    def phi_tension(self) -> float:
        """Design axial tension [N]: the bars and plates at yield."""
        plates = sum(
            _polygon(r).area * (m.fy or 0.0)
            for r, m in zip(self.section.regions, self.region_mats, strict=True)
            if m.category != "concrete"
        )
        bars = sum(b.area * (m.fy or 0.0) for b, m in zip(self.bars, self.bar_mats, strict=True))
        return self.phi.tension * (plates + bars)

    @functools.cached_property
    def symmetric(self) -> bool:
        """True when regions, materials and bars are symmetric about both centroidal axes (the
        design surface is then computed over one quadrant)."""
        from shapely.affinity import scale
        from shapely.ops import unary_union

        if len({(m.fc, m.fy) for m in self.region_mats}) > 1:
            return False
        cx, cy = self.centroid
        solid = unary_union([_polygon(r) for r in self.section.regions])
        for sx, sy in ((-1, 1), (1, -1)):
            mirrored = scale(solid, xfact=sx, yfact=sy, origin=(cx, cy))
            if solid.symmetric_difference(mirrored).area > 1e-6 * solid.area:
                return False
            for b in self.bars:
                mx, my = cx + sx * (b.x - cx), cy + sy * (b.y - cy)
                if not any(
                    abs(o.x - mx) < 1 and abs(o.y - my) < 1 and abs(o.area - b.area) < 1
                    for o in self.bars
                ):
                    return False
        return True

    # ── results ──

    def point(self, theta: float, d_n: float) -> dict[str, float]:
        """Nominal and factored actions at neutral-axis angle ``theta`` [rad] and depth ``d_n``
        [mm] (``math.inf``: uniform compression)."""
        from concreteproperties.results import UltimateBendingResults

        from saengine.design.rc import EPS_CU

        cp = self.analysis
        result = cp.calculate_ultimate_section_actions(
            d_n=d_n,
            ultimate_results=UltimateBendingResults(default_units=cp.default_units, theta=theta),
        )
        k_u = result.k_u if result.k_u else math.inf
        eps_t = EPS_CU * (1 / k_u - 1) if math.isfinite(d_n) else -EPS_CU
        phi = self.phi.at(eps_t, self.fy / self.es)
        return {
            "P": float(result.n),
            "Mx": float(result.m_x),
            "My": float(result.m_y),
            "phi": phi,
            "epsT": float(eps_t),
            "phiP": float(phi * result.n),
            "phiMx": float(phi * result.m_x),
            "phiMy": float(phi * result.m_y),
        }

    def _depths(self, theta: float, count: int) -> list[float]:
        """Neutral-axis depths of a meridian, from tension to compression: shares of the depth
        of the extreme tension bar, with points over the φ transition, then uniform
        compression."""
        from concreteproperties.utils import calculate_extreme_fibre, global_to_local

        from saengine.design.rc import EPS_CU

        points = self.analysis.compound_geometry.points
        fibre, _ = calculate_extreme_fibre(points=points, theta=theta)
        _, fibre_v = global_to_local(theta=theta, x=fibre[0], y=fibre[1])
        d_bar = max(fibre_v - global_to_local(theta=theta, x=b.x, y=b.y)[1] for b in self.bars)
        eps_ty = self.fy / self.es
        transition = EPS_CU / (EPS_CU + eps_ty + EPS_CU * np.linspace(0, 1, 5))
        ends = max(3, count // 5)
        ratios = np.unique(
            np.concatenate(
                [
                    np.geomspace(2e-3, 0.06, ends),
                    np.linspace(0.08, 1.4, count),
                    np.geomspace(1.6, 6.0, ends),
                    transition,
                ]
            )
        )
        return [*(float(r) * d_bar for r in ratios), math.inf]

    def tension(self) -> dict[str, float]:
        """Uniform tension: bars and plates at yield, the concrete cracked (the end of every
        meridian on the tension side); moments about the centroid (unsymmetric bars)."""
        cx, cy = self.centroid
        forces = [
            (-b.area * (m.fy or 0.0), b.x, b.y)
            for b, m in zip(self.bars, self.bar_mats, strict=True)
        ]
        for region, m in zip(self.section.regions, self.region_mats, strict=True):
            if m.category != "concrete":
                polygon = _polygon(region)
                forces.append(
                    (-polygon.area * (m.fy or 0.0), polygon.centroid.x, polygon.centroid.y)
                )
        p = sum(f for f, _, _ in forces)
        mx = sum(f * (y - cy) for f, _, y in forces)
        my = sum(f * (x - cx) for f, x, _ in forces)
        phi = self.phi.tension
        row = {"P": p, "Mx": mx, "My": my, "phi": phi, "epsT": math.inf}
        row.update(phiP=phi * p, phiMx=phi * mx, phiMy=phi * my, phiPcapped=phi * p)
        return row

    def meridian(self, theta: float, count: int = 18) -> list[dict[str, float]]:
        """Points of the P-M diagram at neutral-axis angle ``theta``, from uniform tension to
        uniform compression, with ``phiPcapped``: φP at most φPn,max (ACI 22.4.2.1)."""
        cap = self.phi_pn_max
        rows = [self.point(theta, d) for d in self._depths(theta, count)]
        for row in rows:
            row["phiPcapped"] = min(row["phiP"], cap)
        return [self.tension(), *rows]

    def uniaxial(self, axis: Literal["x", "y"] = "x", count: int = 18) -> dict[str, Any]:
        """The interaction diagram for bending about ``axis``: both signs of the moment, as rows
        (P, M, φP, φM, φ, εt), M signed; the positive branch from tension to compression, then
        the negative one back, one closed curve to plot."""
        # Neutral axis along x with compression on top (theta 0) gives +Mx, theta π -Mx; about
        # y, theta π/2 gives compression on the left (-My)... the sign is read off the result.
        thetas = (0.0, math.pi) if axis == "x" else (-math.pi / 2, math.pi / 2)
        key = "Mx" if axis == "x" else "My"
        branches = []
        for theta in thetas:
            rows = self.meridian(theta, count)
            branches.append(
                [
                    {
                        "P": r["P"],
                        "M": r[key],
                        "phiP": r["phiPcapped"],
                        "phiM": r["phi" + key],
                        "phi": r["phi"],
                        "epsT": r["epsT"] if math.isfinite(r["epsT"]) else None,
                    }
                    for r in rows
                ]
            )
        first, second = branches
        return {
            "axis": axis,
            "points": [*first, *reversed(second)],
            "phiPnMax": self.phi_pn_max,
            "phiTension": self.phi_tension,
            "p0": self.p0,
        }

    def surface(self, angles: int = 24, count: int = 14) -> dict[str, Any]:
        """The P-Mx-My surface as meridians at ``angles`` neutral-axis angles over the full
        turn, for the FEM viewer and the detail windows: rows (φP capped, φMx, φMy, P, Mx, My)
        [N, N·mm]."""
        meridians = []
        for k in range(angles):
            theta = -math.pi + 2 * math.pi * k / angles
            rows = self.meridian(theta, count)
            meridians.append(
                {
                    "theta": theta,
                    "points": [
                        [r["phiPcapped"], r["phiMx"], r["phiMy"], r["P"], r["Mx"], r["My"]]
                        for r in rows
                    ],
                }
            )
        return {
            "columns": ["phiP", "phiMx", "phiMy", "P", "Mx", "My"],
            "units": {"force": "N", "moment": "N·mm"},
            "meridians": meridians,
            "phiPnMax": self.phi_pn_max,
            "phiTension": self.phi_tension,
            "centroid": list(self.centroid),
            "phi": {"tension": self.phi.tension, "compression": self.phi.compression},
        }


@functools.cache
def _surface_class() -> type:
    from saengine.design.rc import InteractionSurface

    class DesignedSurface(InteractionSurface):
        """:class:`saengine.design.rc.InteractionSurface` of a :class:`DesignedRcSection`,
        with the pack's φ."""

        def _point(self, theta: float, d_n: float) -> list[float]:
            row = self.section.point(theta, d_n)  # type: ignore[attr-defined]
            mx, my = row["phiMx"], row["phiMy"]
            if self.symmetric:
                mx, my = abs(mx), abs(my)
            return [row["phiP"], mx, my]

    return DesignedSurface


def design_surface(
    section: DesignedSection, materials: Any, pack: Any = None, coarse: bool = False
):
    """The φ-factored interaction surface of a designed RC section for column design: an
    :class:`saengine.design.rc.InteractionSurface` (``check(pu, mux, muy)``,
    ``moment_capacity``, ``contour``) whose φ comes from the pack."""
    return _surface_class()(DesignedRcSection(section, materials, pack), coarse=coarse)


# ─────────────────────────────── use in the model (wiring helpers) ───────────────────────────────
# fem/derive.py and design/check.py read designed profiles through these (the wiring is a few
# lines in each; see the pull request that added this module).


def frame_section(profile: Any, materials: Any, root: str | Path | None = None) -> dict[str, Any]:
    """Elastic frame properties of a member with a designed profile, for the analysis model:
    E, G of the reference material (the first region's) and the transformed A, Ixx, Iyy, J,
    shear areas [MPa, mm², mm⁴], centroid and shear centre [mm]. Sections of one material give
    what :func:`saengine.library.sections.section_properties` gives, plus the shear areas."""
    props = properties(resolve(profile, root), materials)
    return {
        "E": props.E,
        "G": props.G,
        "A": props.area,
        "Ixx": props.ixx,
        "Iyy": props.iyy,
        "J": props.j,
        "Asx": props.asx,
        "Asy": props.asy,
        "cx": props.cx,
        "cy": props.cy,
        "scx": props.scx,
        "scy": props.scy,
        "massPerLength": props.massPerLength,
    }


def column_surface(
    profile: Any,
    materials: Any,
    pack: Any = None,
    root: str | Path | None = None,
    coarse: bool = False,
):
    """``(section, surface)`` for designing an RC column of a designed profile, as
    ``design/check.py`` builds them for rectangles (``section_of`` + ``InteractionSurface``):
    ``surface.check(pu, mux, muy)``; ``section.phi_pn_max``, ``section.phi_tension``. The bars
    are the designed section's own (the object type's ``reinforcement`` groups do not apply)."""
    surface = design_surface(resolve(profile, root), materials, pack, coarse=coarse)
    return surface.section, surface


def ifc_profile(run: Any, file: Any, section: DesignedSection, name: str) -> Any:
    """The section as an IfcArbitraryProfileDefWithVoids (an IfcCompositeProfileDef of them for
    separate plates), centred on the gross centroid like IFC's parameterized profiles.
    ``run``: the IFC writer's ``ifcopenshell.api`` runner."""
    from shapely.geometry import polygon as shapely_polygon
    from shapely.ops import unary_union

    solid = unary_union([_polygon(r) for r in section.regions])
    cx, cy = solid.centroid.x, solid.centroid.y
    parts = [solid] if solid.geom_type == "Polygon" else list(solid.geoms)

    def ring(coords) -> list[tuple[float, float]]:
        return [(float(x - cx), float(y - cy)) for x, y in coords]

    profiles = []
    for part in parts:
        part = shapely_polygon.orient(part)
        outer = ring(part.exterior.coords)
        holes = [ring(h.coords) for h in part.interiors]
        if holes:
            profile = run(
                "profile.add_arbitrary_profile_with_voids",
                file,
                outer_profile=outer,
                inner_profiles=holes,
                name=name,
            )
        else:
            profile = run("profile.add_arbitrary_profile", file, profile=outer, name=name)
        profiles.append(profile)
    if len(profiles) == 1:
        return profiles[0]
    return file.create_entity(
        "IfcCompositeProfileDef", ProfileType="AREA", ProfileName=name, Profiles=profiles
    )


# ─────────────────────────────────────── the editor ───────────────────────────────────────


def _materials_of(materials_text: str | None, root: str | Path | None) -> MaterialLibrary:
    if materials_text is None and root is not None:
        path = Path(root) / "03 Materials" / "materials.json"
        materials_text = path.read_text(encoding="utf-8") if path.is_file() else None
    if materials_text is None:
        from saengine.library.defaults import default_material_library

        return default_material_library()
    return MaterialLibrary.model_validate_json(materials_text)


def analyse(
    text: str,
    materials_text: str | None = None,
    root: str | Path | None = None,
    capacity: bool = True,
    surface: bool = False,
    moment_curvature: dict[str, Any] | None = None,
    contour_at: float | None = None,
) -> dict[str, Any]:
    """What the Section Designer shows (RPC ``section/analyse``): ``problems`` (validation;
    nothing else then), ``properties``, and for RC sections the ``uniaxial`` diagrams about x
    and y (``capacity``) and the P-Mx-My ``surface`` (``surface``); ``capacityNote`` says why
    there is no capacity. Sections without concrete get the plastic (cross-section yield)
    diagrams of :class:`saengine.library.section_capacity.PlasticSection` instead
    (``capacityKind`` "plastic", else "rc").

    ``moment_curvature`` (``{axial [N], theta [rad], tension, steelLimit}``) adds the
    ``momentCurvature`` curve and its key points, and ``contour_at`` [N] the M-M ``contour``
    at that axial force (:mod:`saengine.library.section_capacity`). The pack in force is the
    project's (the RPC server sets it)."""
    from pydantic import ValidationError

    try:
        section = DesignedSection.model_validate_json(text)
    except ValidationError as error:
        return {
            "problems": [
                {
                    "path": ".".join(str(p) for p in e["loc"]),
                    "message": str(e["msg"]).removeprefix("Value error, "),
                }
                for e in error.errors()
            ]
        }
    try:
        materials = _materials_of(materials_text, root)
        result: dict[str, Any] = {
            "problems": [],
            "properties": properties(section, materials).as_dict(),
        }
    except (SectionError, ValidationError) as error:
        return {"problems": [{"path": "", "message": str(error)}]}
    from saengine.library import section_capacity

    if moment_curvature is not None:
        try:
            result["momentCurvature"] = section_capacity.moment_curvature(
                section,
                materials,
                axial=float(moment_curvature.get("axial", 0.0)),
                theta=float(moment_curvature.get("theta", 0.0)),
                tension=bool(moment_curvature.get("tension", True)),
                steel_limit=float(
                    moment_curvature.get("steelLimit", section_capacity.DEFAULT_STEEL_LIMIT)
                ),
            )
        except SectionError as error:
            result["momentCurvatureNote"] = str(error)
    if not (capacity or surface or contour_at is not None):
        return result
    pack = _pack_for(root)
    has_concrete = any(_mat(materials, r.material).category == "concrete" for r in section.regions)
    if not has_concrete:
        try:
            plastic = section_capacity.PlasticSection(section, materials, pack)
        except SectionError as error:
            result["capacityNote"] = str(error)
            return result
        result["capacityKind"] = "plastic"
        if capacity:
            result["uniaxial"] = {axis: plastic.uniaxial(axis) for axis in ("x", "y")}
        if contour_at is not None:
            result["contour"] = _contour_result(contour_at, plastic.contour(contour_at))
        result["phi"] = {
            "tension": plastic.phi["tension"],
            "compression": plastic.phi["compression"],
            "flexure": plastic.phi["flexure"],
        }
        return result
    try:
        rc = DesignedRcSection(section, materials, pack)
    except SectionError as error:
        result["capacityNote"] = str(error)
        return result
    result["capacityKind"] = "rc"
    if capacity:
        result["uniaxial"] = {axis: rc.uniaxial(axis, count=12) for axis in ("x", "y")}
    if surface:
        result["surface"] = rc.surface()
    if contour_at is not None:
        result["contour"] = _contour_result(contour_at, section_capacity.rc_contour(rc, contour_at))
    result["phi"] = {"tension": rc.phi.tension, "compression": rc.phi.compression}
    return result


def _contour_result(axial: float, rows: list[dict[str, float]] | None) -> dict[str, Any]:
    """The M-M contour for the editor: the rows, or a note when the force is beyond it."""
    if rows is None:
        return {"axial": axial, "points": [], "note": "beyond the section's axial capacity"}
    return {"axial": axial, "points": rows}


def _pack_for(root: str | Path | None) -> Any:
    """The project's pack (its settings' ``codePack``), else the pack in force."""
    from saengine.codes import context

    if root is None:
        return context.current()
    settings_path = Path(root) / "02 Project Settings" / "project-settings.json"
    settings = (
        json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else None
    )
    return context.pack_for(settings, root)
