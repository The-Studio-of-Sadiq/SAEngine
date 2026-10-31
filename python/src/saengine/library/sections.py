"""Geometric section properties of object profiles, computed with sectionproperties.

This is the bridge from an object type's IFC-style profile to the elastic section
properties the FEM model needs (A, I, J). Axes follow sectionproperties: x is horizontal
(the profile's width), y vertical (its depth); ``ixx`` is the major-axis moment of inertia
for a beam bending under gravity.

:func:`section_properties` meshes and solves a profile once per process: a building has a few
distinct profiles but thousands of elements, and the analysis model, the design checks and the
others all ask for them (the answer is cached by the profile's dimensions; a designed section
by its whole definition, so editing it gives a new entry). The answers are also kept on disk
(:func:`cache_folder`), so the next derivation, in this project or another with the same
profiles, reads them instead of solving again, and :func:`prefetch_section_properties` solves
the distinct profiles a building still needs in parallel processes.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from pydantic import TypeAdapter
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
    """The profile's properties, worked out once per distinct profile (:func:`profile_key`)."""
    return _properties(profile_key(profile))


#: ``SAENGINE_SECTION_CACHE``: the folder of the on-disk answers, or ``0`` to keep none.
CACHE_ENV = "SAENGINE_SECTION_CACHE"
#: Changes when the way the properties are worked out changes (mesh size, solver), so answers
#: of an earlier way are not read.
CACHE_VERSION = 1


def cache_folder() -> Path | None:
    """Where the worked-out properties are kept between runs: ``$SAENGINE_SECTION_CACHE``, else
    ``%LOCALAPPDATA%/SAEngine/cache/section-properties`` (``~/.cache/saengine/...`` elsewhere);
    None when the variable is ``0``."""
    given = os.environ.get(CACHE_ENV, "").strip()
    if given == "0":
        return None
    if given:
        return Path(given)
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) / "SAEngine" / "cache" if local else Path.home() / ".cache" / "saengine"
    return root / "section-properties"


def _cache_file(key: str) -> Path | None:
    folder = cache_folder()
    if folder is None:
        return None
    from importlib.metadata import PackageNotFoundError, version

    try:
        solver = version("sectionproperties")
    except PackageNotFoundError:
        solver = "?"
    text = json.dumps([CACHE_VERSION, solver, key])
    return folder / f"{hashlib.sha256(text.encode('utf-8')).hexdigest()}.json"


def _read_cached(key: str) -> SectionProperties | None:
    path = _cache_file(key)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("key") != key:
            return None
        return SectionProperties(**data["properties"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_cached(key: str, props: SectionProperties) -> None:
    path = _cache_file(key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(f".{os.getpid()}.tmp")
        part.write_text(json.dumps({"key": key, "properties": asdict(props)}), encoding="utf-8")
        os.replace(part, path)
    except OSError:
        pass  # a read-only or full disk: the answer stays in this process only


#: The answers of this process by profile key (a building has tens of distinct profiles).
_MEMO: dict[str, SectionProperties] = {}
_MEMO_LIMIT = 512


def _remember(key: str, props: SectionProperties) -> SectionProperties:
    if len(_MEMO) >= _MEMO_LIMIT:
        _MEMO.clear()
    _MEMO[key] = props
    return props


def _properties(key: str) -> SectionProperties:
    found = _MEMO.get(key)
    if found is not None:
        return found
    found = _read_cached(key)
    if found is None:
        found = _solve(key)
        _write_cached(key, found)
    return _remember(key, found)


#: Most processes :func:`prefetch_section_properties` starts.
MAX_PREFETCH_JOBS = 4


def prefetch_section_properties(profiles: Iterable[o.Profile]) -> None:
    """Works out the properties of ``profiles`` that are neither known nor kept on disk, in
    parallel processes when there are several (each is a finite-element solve of seconds), so
    the next :func:`section_properties` calls find them. Falls back to one by one when the
    processes cannot start."""
    keys: list[str] = []
    for profile in profiles:
        try:
            key = profile_key(profile)
        except Exception:  # noqa: BLE001, S112 - an unresolvable profile fails where it is used
            continue
        if key in _MEMO or key in keys:
            continue
        cached = _read_cached(key)
        if cached is not None:
            _remember(key, cached)
        else:
            keys.append(key)
    jobs = min(len(keys), MAX_PREFETCH_JOBS, max(1, (os.cpu_count() or 2) // 2))
    if jobs < 2:
        return  # one or none: solved where it is first used
    from concurrent.futures import ProcessPoolExecutor

    try:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            solved = list(pool.map(_solve, keys))
    except Exception:  # noqa: BLE001
        # Processes that could not start or died, or a profile that fails to solve: each is
        # solved (or fails, with its own message) where it is first used.
        return
    for key, props in zip(keys, solved, strict=True):
        _write_cached(key, props)
        _remember(key, props)


def profile_key(profile: o.Profile) -> str:
    """What the properties of ``profile`` depend on, as text: its shape and dimensions, or for
    a designed section the section itself (read from the project)."""
    if isinstance(profile, o.DesignedProfile):
        from saengine.library import section_designer

        section = section_designer.resolve(profile).model_dump(mode="json", by_alias=True)
        return json.dumps({"designed": section}, sort_keys=True)
    return json.dumps(profile.model_dump(mode="json"), sort_keys=True)


_PROFILE = TypeAdapter(o.Profile)


def _solve(key: str) -> SectionProperties:
    """Meshes and solves the profile of ``key`` (:func:`profile_key`)."""
    data = json.loads(key)
    if "designed" in data:
        from saengine.library import section_designer

        section = section_designer.DesignedSection.model_validate(data["designed"])
        geometry = section_designer.outline_geometry(section)
        # Thin walls and plates: finer (see mesh_size).
        mesh = section_designer.mesh_size(section)
    else:
        geometry = profile_geometry(_PROFILE.validate_python(data))
        # Mesh size relative to the section: fine enough for J, quick enough for interactive use.
        xmin, xmax, ymin, ymax = geometry.calculate_extents()
        mesh = max(xmax - xmin, ymax - ymin) ** 2 / 400
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
