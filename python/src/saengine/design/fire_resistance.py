"""Fire resistance of the members by least sizes, from the construction type.

The rating each member is checked for comes from two settings:

- Project Settings > Construction: the construction type, whose ratings of the columns and
  framing, the floors with their beams and the bearing walls are the code pack's
  ``fireResistance.constructionTypes`` (with the exterior bearing wall rating at the fire
  separation distance, when one is given);
- Project Settings > Analysis model > Fire resistance: a least rating per member kind (an
  authority may ask for more for a hazardous use); the larger of the two governs.

The least sizes for a rating are the code pack's (one value per rating; the next rating up):

- slabs and concrete walls: the least equivalent thickness by the concrete's aggregate type
  (``thickness``; Project Settings > Construction > Concrete aggregate);
- columns: the least dimension by aggregate type (``columnSize``, with ``columnSizeFallback``
  for a type the table has no row for);
- masonry walls: the least equivalent thickness by unit (``masonryThickness``; the row from
  :func:`saengine.design.masonry.fire_row`);
- beams: no least size; the covers below only.

The covers of slabs, beams and columns come from the pack's ``advisory`` block when it has one,
labelled with its source; they are flagged rows that never fail a member.

Columns are checked as supporting more than one floor and roof slabs as floors (the larger
ratings of each row). Covers to the main bars are the clear cover to the ties or stirrups plus
their diameter.
"""

from __future__ import annotations

from typing import Any

from saengine.codes import context as code_context

__all__ = [
    "add_fire_checks",
    "construction_summary",
    "member_checks",
    "ratings_of",
    "required",
    "type_ratings",
]

#: The member kinds and the rows of a construction type they take their rating from.
KIND_ROWS: dict[str, tuple[str, ...]] = {
    "column": ("framingMoreFloors",),
    "beam": ("floors", "framingOneFloor"),
    "slab": ("floors",),
    "wall": ("interiorBearingWalls",),
}


def _table() -> Any:
    return code_context.pack_table("fireResistance")


def _clause(key: str) -> str:
    return str(_table().clauses.get(key, ""))


def __getattr__(name: str) -> Any:
    # ``CLAUSE``: the active pack's clause of the least sizes (read by the design checks' note).
    if name == "CLAUSE":
        return _clause("thickness") or "the code pack's fireResistance table"
    raise AttributeError(name)


def _next_up(ratings: list[float], values: list[float], hours: float) -> float | None:
    for rating, value in zip(ratings, values, strict=True):
        if hours <= rating + 1e-9:
            return float(value)
    return None


def required(name: str, hours: float, aggregate: str = "siliceous") -> float | None:
    """The least size [mm] of row ``name`` at ``hours`` (the next rating up), or None above the
    table or without a row for the aggregate (or masonry unit). ``name``: "thickness" (also
    "slabThickness", "wallThickness"), "columnSize", "masonryThickness"."""
    table = _table()
    if name in ("slabThickness", "wallThickness"):
        name = "thickness"
    if name == "masonryThickness":
        row = table.masonryThickness.get(aggregate)
        return None if row is None else _next_up(table.masonryRatings, row, hours)
    rows = getattr(table, name)
    if name == "columnSize" and aggregate not in rows:
        aggregate = table.columnSizeFallback.get(aggregate, aggregate)
    row = rows.get(aggregate)
    return None if row is None else _next_up(table.ratings, row, hours)


def _settings_part(settings: Any, name: str) -> Any:
    return getattr(settings, name, None) if settings is not None else None


def _type_row(settings: Any) -> tuple[str, Any]:
    construction = _settings_part(settings, "construction")
    type_id = str(getattr(construction, "constructionType", "") or "")
    return type_id, _table().constructionTypes.get(type_id) if type_id else None


def _band(distance: float) -> int:
    """The band of ``separationLimits`` a fire separation distance falls in."""
    limits = _table().separationLimits
    if not limits or distance <= limits[0] + 1e-9:
        return 0
    for i, limit in enumerate(limits[1:], start=1):
        if distance < limit - 1e-9:
            return i
    return len(limits)


def type_ratings(settings: Any) -> dict[str, tuple[float | None, str]]:
    """The construction type's rating [h] of each member kind with its clause text; empty
    when the type is not set or not in the code pack."""
    type_id, row = _type_row(settings)
    if row is None:
        return {}
    clause = _clause(row.group)
    out: dict[str, tuple[float | None, str]] = {}
    for kind, keys in KIND_ROWS.items():
        values = [getattr(row, k) for k in keys if getattr(row, k) is not None]
        hours = max(values) if values else None
        text = f"type {type_id}, {clause}".strip(", ")
        if kind == "wall":
            distance = getattr(_settings_part(settings, "construction"), "fireSeparation", None)
            if distance is not None:
                exterior = float(row.exteriorBearing[_band(float(distance))])
                if hours is None or exterior > hours:
                    hours = exterior
                    text += f", exterior bearing wall at {float(distance):g} m"
        out[kind] = (hours, text)
    return out


def ratings_of(settings: Any) -> dict[str, tuple[float, str]]:
    """The rating [h] each member kind is checked for, with where it comes from: the larger of
    the construction type's and the least rating of Analysis model > Fire resistance."""
    least = getattr(_settings_part(settings, "analysis"), "fireResistance", None)
    by_type = type_ratings(settings)
    names = {"column": "columns", "beam": "beams", "slab": "slabs", "wall": "walls"}
    out: dict[str, tuple[float, str]] = {}
    for kind, field in names.items():
        own = float(getattr(least, field, 0) or 0) if least is not None else 0.0
        hours, text = by_type.get(kind, (None, ""))
        if hours is not None and hours >= own:
            out[kind] = (float(hours), text)
        elif own > 0:
            out[kind] = (own, "Project Settings")
        else:
            out[kind] = (0.0, text)
    return out


def _row(
    name: str, need: float | None, given: float, hours: float, why: str, clause: str, flag: bool
) -> dict:
    from saengine.design.check import _check as row

    if need is None:
        return row(
            f"Fire resistance: {name}",
            1.0,
            0.0,
            "mm",
            None,
            f"{hours:g} h ({why}): not in the table ({clause}); check by another method",
            flag=True,
        )
    return row(
        f"Fire resistance: {name}",
        need,
        given,
        "mm",
        None,
        f"{hours:g} h ({why}): at least {need:g} mm ({clause})",
        flag=flag,
    )


def _transverse_dia(object_type: Any) -> float:
    transverse = getattr(getattr(object_type, "reinforcement", None), "transverse", None)
    return float(transverse.dia) if transverse is not None else 0.0


def _advisory(name: str, hours: float) -> float | None:
    adv = _table().advisory
    return None if adv is None else _next_up(adv.ratings, getattr(adv, name), hours)


def member_checks(
    kind: str,
    object_type: Any,
    hours: float,
    aggregate: str = "siliceous",
    why: str = "",
    masonry: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The fire checks of one member of ``kind`` ("beam", "column", "slab", "wall") for a rating
    of ``hours``. ``aggregate``: the concrete's aggregate type; ``why``: where the rating comes
    from; ``masonry``: for a masonry wall, ``{"row": <masonryThickness row>, "equivalent":
    <the wall thickness is its equivalent thickness>}`` (:func:`saengine.design.masonry.
    fire_row`)."""
    if hours <= 0 or object_type is None:
        return []
    table = _table()
    adv = table.advisory
    label = adv.label if adv is not None else ""
    why = why or "Project Settings"
    rows: list[dict[str, Any]] = []
    reinforcement = getattr(object_type, "reinforcement", None)
    cover = float(getattr(reinforcement, "cover", 0.0) or 0.0)
    if kind == "wall" and masonry is not None:
        clause = _clause("masonryThickness")
        unit = str(masonry.get("row", ""))
        if not masonry.get("equivalent", True):
            rows.append(
                _row("equivalent thickness", None, 0.0, hours, why,
                     f"{clause}: hollow units not fully grouted, their equivalent thickness "
                     "is not known", True)
            )  # fmt: skip
        else:
            need = required("masonryThickness", hours, unit)
            rows.append(
                _row("equivalent thickness", need, float(object_type.thickness), hours, why,
                     f"{clause}, {unit}" if need is not None else f"{clause}, no row {unit}",
                     False)
            )  # fmt: skip
        return rows
    if kind in ("slab", "wall"):
        need = required("thickness", hours, aggregate)
        rows.append(
            _row("thickness", need, float(object_type.thickness), hours, why,
                 f"{_clause('thickness')}, {aggregate}", False)
        )  # fmt: skip
        if kind == "slab" and reinforcement is not None and adv is not None:
            rows.append(
                _row("cover", _advisory("slabCover", hours), cover, hours, why,
                     f"advisory: {label}", True)
            )  # fmt: skip
        return rows
    if kind not in ("beam", "column"):
        return rows
    profile = getattr(object_type, "profile", None)
    if profile is None:
        return []
    if getattr(profile, "shape", "") == "circle":
        least = 2 * float(profile.radius)
    else:
        least = min(float(profile.xDim), float(profile.yDim))
    main_cover = cover + _transverse_dia(object_type)
    if kind == "column":
        need = required("columnSize", hours, aggregate)
        fallback = table.columnSizeFallback.get(aggregate)
        text = f"{_clause('columnSize')}, {fallback or aggregate}"
        if fallback:
            text += f" for {aggregate} ({table.sources.get('columnSizeFallback', '')})"
        rows.append(_row("least dimension", need, least, hours, why, text, False))
        if adv is not None:
            need = min(adv.columnCoverPerHour * hours, adv.columnCoverMax)
            rows.append(
                _row("cover to the main bars", need, main_cover, hours, why,
                     f"advisory: {label}", True)
            )  # fmt: skip
        return rows
    if adv is not None:
        width = float(profile.xDim) if hasattr(profile, "xDim") else least
        if width < adv.beamWidth:
            rows.append(
                _row("width", float(adv.beamWidth), width, hours, why,
                     f"advisory: {label}; narrower beams need larger covers", True)
            )  # fmt: skip
        rows.append(
            _row("cover to the main bars", _advisory("beamCover", hours), main_cover, hours, why,
                 f"advisory: {label}", True)
        )  # fmt: skip
    return rows


def add_fire_checks(checked: list[dict[str, Any]], types: dict[str, Any], settings: Any) -> int:
    """Adds the fire checks to the designed elements in place (the ratings of
    :func:`ratings_of`); returns how many elements got them. Flagged rows (advisory covers,
    sizes the table has no row for) never fail an element."""
    if settings is None:
        return 0
    ratings = ratings_of(settings)
    aggregate = str(
        getattr(_settings_part(settings, "construction"), "aggregate", "siliceous") or "siliceous"
    )
    count = 0
    for element in checked:
        kind = element.get("kind")
        if kind not in ratings:
            continue
        hours, why = ratings[kind]
        masonry = element.get("fireMasonry") if kind == "wall" else None
        rows = member_checks(
            kind, types.get(element.get("type")), hours, aggregate, why, masonry=masonry
        )
        if not rows:
            continue
        element.setdefault("checks", []).extend(rows)
        failed = [r for r in rows if not r["ok"] and not r["flag"]]
        if failed:
            element["ok"] = False
            element["utilisation"] = max(
                float(element.get("utilisation", 0.0)), *(r["utilisation"] for r in failed)
            )
        count += 1
    return count


def construction_summary(settings: Any, height: float | None = None) -> dict[str, Any]:
    """The construction type for the report: its label, the ratings each member kind is checked
    for and the warnings (a combustible type above the pack's non-combustible height; a type the
    code pack does not know). ``height``: the building's height [m]."""
    table = _table()
    type_id, row = _type_row(settings)
    construction = _settings_part(settings, "construction")
    aggregate = str(getattr(construction, "aggregate", "siliceous") or "siliceous")
    warnings: list[str] = []
    if type_id and row is None:
        warnings.append(
            f"Construction type '{type_id}' is not in the code pack's fireResistance table: "
            "its ratings are not checked."
        )
    limit = table.nonCombustibleAbove
    tall = limit is not None and height is not None and height > limit
    if row is not None and tall and row.group != "nonCombustible":
        warnings.append(
            f"The building is {height:.1f} m high: above {limit:g} m it must be of "
            f"non-combustible construction ({_clause('nonCombustibleAbove')}), but the "
            f"construction type is {row.label}."
        )
    if aggregate not in table.thickness:
        warnings.append(
            f"The code pack's fire table has no rows for {aggregate} aggregate: the least "
            "concrete sizes are not checked."
        )
    rated = ratings_of(settings)
    return {
        "type": type_id,
        "label": row.label if row is not None else ("Not classified" if not type_id else type_id),
        "group": row.group if row is not None else None,
        "aggregate": table.aggregates.get(aggregate, aggregate),
        "ratings": {kind: hours for kind, (hours, _why) in rated.items()},
        "note": row.note if row is not None else None,
        "warnings": warnings,
    }
