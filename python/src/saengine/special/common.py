"""What the special structures share: the project's object types as frame sections, the wind
pressure of the project's site and the pack's strength combinations of dead load and wind."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saengine.special import frame as fr

G = 9.80665


@dataclass(frozen=True)
class MemberType:
    """An object type as a steel member: its shape, steel, frame section and outer width."""

    id: str
    shape: Any  # saengine.design.steel.properties.ShapeProperties (mm)
    steel: Any  # saengine.design.steel.members.Steel
    section: fr.Section
    width: float  # outer width [m]
    round: bool
    label: str


def member_type(type_id: str, objects: Any, materials: Any) -> MemberType:
    """The steel member of object type ``type_id`` (04 Objects) and its material."""
    from saengine.design.steel.members import Steel
    from saengine.design.steel.properties import shape_properties
    from saengine.fem.open_wind import outer_width

    found = _entry(objects, "objects", type_id)
    if found is None or not hasattr(found, "profile"):
        raise ValueError(f"object type '{type_id}' is not a member type in 04 Objects")
    material = _entry(materials, "materials", found.material)
    if material is None:
        raise ValueError(f"object type '{type_id}': material '{found.material}' not found")
    shape = shape_properties(found.profile)
    steel = Steel.of(material)
    e = steel.e * 1e6
    nu = (material.mechanical.nu if material.mechanical else None) or 0.3
    density = (material.mechanical.density if material.mechanical else None) or 7850.0
    area = shape.area * 1e-6
    section = fr.Section(
        area,
        shape.ix * 1e-12,
        shape.iy * 1e-12,
        max(shape.j, 1e-3) * 1e-12,
        e,
        e / (2 * (1 + nu)),
        area * density,
    )
    profile = found.profile
    is_round = getattr(profile, "shape", "") in ("circle", "circleHollow")
    return MemberType(
        type_id, shape, steel, section, outer_width(profile) / 1000, is_round, shape.label
    )


def _entry(library: Any, key: str, entry_id: str) -> Any:
    """Entry ``entry_id`` of a library (its ``key`` list) or of a dict of entries by id."""
    if isinstance(library, dict):
        return library.get(entry_id)
    return next((e for e in getattr(library, key) if e.id == entry_id), None)


def wind_pressure(settings: Any) -> tuple[Any, list[str]]:
    """``qz(z)`` [kN/m²] at height z [m] above the ground by the pack in force and the
    project's site (its wind speed, exposure and importance), and notes; None when the site has
    no wind speed."""
    from saengine.fem.loads import velocity_pressure
    from saengine.library.settings import derived

    values = derived(settings)
    speed = values.get("windSpeed")
    if not speed:
        return None, ["wind: the site has no wind speed (Project Settings, Site)"]
    importance = float(values.get("windImportance") or 1.0)
    exposure = settings.wind.exposure

    from saengine.fem.loads import wind_overrides

    def qz(z: float) -> float:
        with wind_overrides(settings.wind):  # the project's own Kd, Kzt where it gives them
            return float(velocity_pressure(max(z, 0.0), float(speed), exposure, importance))

    return qz, [f"wind: V = {float(speed):g} m/s, exposure {exposure}, importance {importance:g}"]


def strength_pairs(settings: Any, pack: Any) -> tuple[list[tuple[str, float, float]], str]:
    """(name, factor on the dead load, factor on the wind) of the pack's strength combinations
    with wind (and the largest dead-load-only one); SAEngine practice (1.2 D + 1.0 W, 0.9 D +
    1.0 W, 1.4 D) when the pack's combinations cannot be read."""
    from saengine.library.settings import strength_combinations

    try:
        rows = strength_combinations(pack=pack, settings=settings)
    except Exception:  # noqa: BLE001 - the practice factors stand in, said in the notes
        rows = []
    pairs: dict[tuple[float, float], str] = {}
    dead_only: tuple[float, str] | None = None
    for r in rows:
        w = max(abs(r.WX), abs(r.WY))
        if w > 0:
            pairs.setdefault((float(r.D), float(w)), r.name)
        elif r.D > 0 and (dead_only is None or r.D > dead_only[0]):
            dead_only = (float(r.D), r.name)
    if not pairs:
        return (
            [("1.2D + 1.0W", 1.2, 1.0), ("0.9D + 1.0W", 0.9, 1.0), ("1.4D", 1.4, 0.0)],
            "SAEngine practice combinations (the pack's could not be read)",
        )
    out = [(name, d, w) for (d, w), name in pairs.items()]
    if dead_only is not None:
        out.append((dead_only[1], dead_only[0], 0.0))
    return out, "the code pack's strength combinations with wind"


def check_member(
    kind: MemberType,
    length: float,
    k_factor: float,
    axial: float,
    moment: float,
) -> tuple[float, str]:
    """Utilisation of a steel member by the pack's steel method: |N| / N_Rd + |M| / M_Rd
    (compression with the buckling length K L, else tension) and the note. ``length`` [m],
    ``axial`` [N] (tension positive), ``moment`` [N·m]."""
    from saengine.design.steel.pack_resistance import axial as axial_resistance
    from saengine.design.steel.pack_resistance import elastic_moment

    kl = k_factor * length * 1000
    compression = axial < 0
    n_rd, _, note = axial_resistance(kind.shape, kind.steel, kl, kl, compression)
    m_rd, _, _ = elastic_moment(kind.shape, kind.steel)
    ratio = abs(axial) / n_rd if n_rd > 0 else float("inf")
    if moment and m_rd > 0:
        ratio += abs(moment) * 1000 / m_rd
    return ratio, note
